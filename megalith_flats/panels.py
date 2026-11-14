"""Work out each panel's area from the panel borders, and put flats into each panel's color folder."""
import cv2
import numpy as np
from scipy import ndimage

from .export import add_rgba_layer
from .extract import PANEL_SCALE


def panel_masks(meta, cfg, labels=None, log=print):
    """Return {panel name: full-size bool mask}. Panel shapes come from the layout borders;
    each shape is matched to the panel folder whose line art sits inside it."""
    border = meta["border"] >= cfg["line_threshold"]
    h, w = border.shape
    r = int(cfg.get("border_gap_px", 6))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    sealed = cv2.dilate(border.astype(np.uint8), k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((1 - sealed).astype(np.uint8), connectivity=4)

    min_area = 0.004 * h * w
    names = list(meta["panel_ink"].keys())
    out = {}
    small_lab = lab[::PANEL_SCALE, ::PANEL_SCALE]
    for c in range(1, n):
        x, y, cw, ch, area = stats[c]
        if area < min_area or x == 0 or y == 0 or x + cw >= w or y + ch >= h:
            continue  # tiny, or the gutter that touches the page edge
        comp = small_lab == c
        scores = [float((meta["panel_ink"][p][:comp.shape[0], :comp.shape[1]] * comp).sum()) for p in names]
        if max(scores) <= 0:
            continue
        best = names[int(np.argmax(scores))]
        out.setdefault(best, np.zeros((h, w), bool))
        out[best] |= lab == c

    # Panels drawn inside another panel (e.g. a circle inset whose border is part of its own line art)
    # get no shape from the layout. Give them the regions their own line art encloses, and take
    # those regions away from the panel they sit in.
    for p in names:
        if p in out:
            continue
        small_ink = meta["panel_ink"][p] >= cfg["line_threshold"]
        hull = ndimage.binary_fill_holes(cv2.dilate(small_ink.astype(np.uint8), np.ones((3, 3), np.uint8)))
        if hull.sum() == 0:
            continue
        big = cv2.resize(hull.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)[:h, :w].astype(bool)
        if labels is not None:  # snap to whole regions for crisp edges
            inside = np.bincount(labels.ravel(), weights=big.ravel(), minlength=labels.max() + 1)
            total = np.bincount(labels.ravel(), minlength=labels.max() + 1)
            big = (inside / np.maximum(total, 1) > 0.5)[labels]
        out[p] = big
        for q in out:
            if q != p:
                out[q] &= ~big
        log(f"  panel {p}: inset panel, area taken from its own line art")

    # Areas that belong to no panel but are not the gutter (they don't reach the page edge), like the
    # sky inside a circle inset, join the panel they touch most.
    if labels is not None and out:
        n = int(labels.max())
        pidx = np.zeros((h, w), np.uint8)
        order = list(out)
        for i, p in enumerate(order, 1):
            pidx[out[p]] = i
        areas = np.bincount(labels.ravel(), minlength=n + 1)
        covered = np.bincount(labels.ravel(), weights=(pidx > 0).ravel(), minlength=n + 1)
        edge = np.zeros(n + 1, bool)
        edge[np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))] = True
        boxes = ndimage.find_objects(labels)
        min_px = int(cfg.get("inner_area_min_px", 20000))
        for r in np.where((covered < 0.5 * areas) & ~edge & (areas >= min_px))[0]:
            if r == 0:
                continue
            sl = boxes[r - 1]
            sl = (slice(max(sl[0].start - 20, 0), sl[0].stop + 20), slice(max(sl[1].start - 20, 0), sl[1].stop + 20))
            m = labels[sl] == r
            ring = cv2.dilate(m.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool) & ~m
            votes = np.bincount(pidx[sl][ring], minlength=len(order) + 1)
            votes[0] = 0
            if votes.max() == 0:
                continue
            p = order[int(votes.argmax()) - 1]
            for q in out:
                out[q][sl] &= ~m
            out[p][sl] |= m
            log(f"  panel {p}: added an enclosed area of {int(areas[r])} px (e.g. sky inside an inset)")

    # grow each panel a little so the flats tuck under its border line
    tuck = int(cfg.get("border_tuck_px", 14))
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * tuck + 1, 2 * tuck + 1))
    core = {p: m.copy() for p, m in out.items()}
    for p in out:
        out[p] = cv2.dilate(out[p].astype(np.uint8), k2).astype(bool)
    for p in out:  # never grow into another panel's own area
        for q, m in core.items():
            if q != p:
                out[p] &= ~m
    missing = [p for p in names if p not in out]
    log(f"  panel areas found for: {sorted(out, key=_num)}" + (f"; no area for {missing}" if missing else ""))
    return out


def _to_bottom(group, layer):
    """psd-tools lists a group's layers bottom-first; move `layer` to index 0."""
    if group.index(layer) != 0:
        group.remove(layer)
        group.insert(0, layer)


def _num(s):
    try:
        return int(s)
    except ValueError:
        return 0


def panel_flat_images(rgb, alpha, masks):
    """{panel: (PIL RGBA cropped to the panel, left, top)} with only that panel's flats."""
    from PIL import Image

    res = {}
    for p, m in masks.items():
        m = m & alpha
        if not m.any():
            continue
        ys, xs = np.where(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgba = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
        rgba[..., :3] = rgb[y0:y1, x0:x1]
        rgba[..., 3] = m[y0:y1, x0:x1] * 255
        res[p] = (Image.fromarray(rgba, "RGBA"), int(x0), int(y0))
    return res


def write_into_psd(path, panel_paths, flats, cfg, hint_seed=None, log=print):
    """Edit the page copy in place: put a 'Flats' layer at the bottom of each panel's color folder
    (replacing the Flats from an earlier run), and make sure the page has a 'Flat hints' layer on top.
    If a panel has no color folder directly inside it (e.g. split into FG/BG), a new 'color' folder is
    made at the bottom of the panel so the flats sit under all of that panel's line art."""
    import os
    from PIL import Image
    from psd_tools import PSDImage

    names = {s.lower() for s in cfg.get("color_group_names", ["color", "colour"])}
    layer_name = cfg["layers"]["flats"]["name"]
    hint_name = cfg.get("hint_layer_name", "Flat hints")
    word = cfg.get("hint_layer_word", "hint").lower()
    psd = PSDImage.open(path)
    notes = []
    for panel, (img, left, top) in sorted(flats.items(), key=lambda kv: _num(kv[0])):
        group = psd
        for step in panel_paths[panel]:
            group = next(g for g in group if g.is_group() and g.name.strip() == step)
        target = next((g for g in group if g.is_group() and g.name.strip().lower() in names), None)
        if target is None:
            target = group.create_group(name="color")
            _to_bottom(group, target)  # bottom of the panel
            where = f"{'/'.join(panel_paths[panel])}/color (new folder)"
        else:
            where = f"{'/'.join(panel_paths[panel])}/{target.name}"
        for old in [l for l in target if not l.is_group() and l.name.strip() == layer_name]:
            target.remove(old)  # Flats from an earlier run
        layer = add_rgba_layer(target, img, layer_name, left=left, top=top)
        _to_bottom(target, layer)
        notes.append(where)
        log(f"  panel {panel}: Flats -> {where}")

    def has_hint(group):
        return any(has_hint(l) if l.is_group() else word in l.name.lower() for l in group)

    if not has_hint(psd):
        if hint_seed is not None and hint_seed[..., 3].any():
            ys, xs = np.where(hint_seed[..., 3] > 0)
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            img, left, top = Image.fromarray(hint_seed[y0:y1, x0:x1], "RGBA"), int(x0), int(y0)
        else:
            img, left, top = Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 0, 0
        add_rgba_layer(psd, img, hint_name, left=left, top=top)  # appended = top of the layer stack
        log(f"  added a '{hint_name}' layer at the top of the page")

    tmp = path + ".saving"
    psd.save(tmp)
    del psd
    os.replace(tmp, path)  # only replace the page once the save has fully worked
    return notes
