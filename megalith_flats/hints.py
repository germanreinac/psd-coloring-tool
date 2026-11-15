"""Decide the flat colour of every area inside the panels.

Where the colours come from, strongest first:
1. Germán's 'Flat hints' layer in the page (any layer with "hint" in its name, hidden or not).
   Every area a scribble touches gets that colour; colours close to a key colour snap to it;
   two colours in one area split it; white means "leave empty".
2. The page's colour plan, maps/<page name>.json, written per page (by Claude or by hand).
   Each entry is "colour name": [items], where an item is
     [x, y]                      a point: the area under it gets the colour
     [[x, y], [x, y], ...]       a stroke: every area it crosses gets the colour
     {"area": [[x, y], ...]}     an outline: every area mostly inside it gets the colour
                                 (whole objects with inner detail lines, e.g. "the whole ice cream is pink").
   "Colour name | note" is allowed, so the same colour can be listed for several objects.
   Outlines are weaker than points/strokes, so a point can still pick out e.g. a window.
3. Everything else gets a colour from the comic's palette, chosen by size (big = soft tones,
   small = accents) and never the same as a touching area, so every element stays separate.
"""
import cv2
import numpy as np
from scipy import ndimage

from .palette import _neighbours

EMPTY = (-1, -1, -1)
DOT_R = 10


def key_colours(key):
    names, cols = [], []
    for sec in ("characters", "cast", "scene", "colours"):
        for name, c in key.get(sec, {}).items():
            if not name.startswith("_"):
                names.append(name)
                cols.append(c)
    for i, c in enumerate(key.get("town", [])):
        names.append(f"town {i + 1}")
        cols.append(c)
    return names, np.array(cols, np.int32).reshape(-1, 3)


def colour_of(name, key):
    name = name.split("|")[0].strip()
    if name.startswith("#") and len(name) == 7:
        return [int(name[i:i + 2], 16) for i in (1, 3, 5)]
    if name.lower() in ("empty", "none"):
        return list(EMPTY)
    name = key.get("aliases", {}).get(name, name)  # names used by older plans
    for sec in ("characters", "cast", "scene", "colours"):
        if name in key.get(sec, {}):
            return list(key[sec][name])
    return None


def read_hint_layers(psd, cfg):
    """Return (ys, xs, rgb) of solid hint pixels from all hint layers, and the list of layer paths."""
    word = cfg.get("hint_layer_word", "hint").lower()
    w, h = psd.size
    ys, xs, cs, found = [], [], [], []

    def walk(group, trail):
        for layer in group:
            name = layer.name.strip()
            if layer.is_group():
                walk(layer, trail + [name])
                continue
            if word not in name.lower() or layer.width <= 1 or layer.height <= 1:
                continue
            found.append("/".join(trail + [name]))
            a = np.asarray(layer.topil().convert("RGBA"))
            yy, xx = np.where(a[..., 3] >= 200)
            c = a[yy, xx, :3]
            yy, xx = yy + layer.top, xx + layer.left
            ok = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            ys.append(yy[ok]); xs.append(xx[ok]); cs.append(c[ok])

    walk(psd, [])
    if not ys:
        return (np.zeros(0, int), np.zeros(0, int), np.zeros((0, 3), np.int32)), found
    return (np.concatenate(ys), np.concatenate(xs), np.concatenate(cs).astype(np.int32)), found


def read_plan(page_map, key, size, log=print):
    """Colour plan file -> (point/stroke pixels (ys, xs, rgb), [(outline polygon, rgb), ...])."""
    w, h = size
    canvas = np.zeros((h, w), np.int32)  # colour index + 1 (strokes)
    cols, areas, points = [], [], []
    for name, items in page_map.items():
        if name.startswith("_"):
            continue
        c = colour_of(name, key)
        if c is None:
            log(f"  plan: colour '{name}' is not in the colour key, skipped")
            continue
        cols.append(c)
        ci = len(cols)
        for it in items:
            if isinstance(it, dict):
                areas.append((np.array(it["area"], np.int32), c))
            elif len(it) == 2 and not isinstance(it[0], (list, tuple)):
                if 0 <= int(it[0]) < w and 0 <= int(it[1]) < h:
                    points.append((int(it[1]), int(it[0]), c))  # only the area right under the point
            else:
                cv2.polylines(canvas, [np.array(it, np.int32)], False, ci, 2 * DOT_R)
    ys, xs = np.nonzero(canvas)
    rgb = np.array(cols, np.int32).reshape(-1, 3)[canvas[ys, xs] - 1] if len(ys) else np.zeros((0, 3), np.int32)
    py = np.array([p[0] for p in points], int)
    px = np.array([p[1] for p in points], int)
    pc = np.array([p[2] for p in points], np.int32).reshape(-1, 3)
    return (ys, xs, rgb), areas, (py, px, pc)


def _pixel_votes(labels, line, hints, keyc, snap, min_px, snap_on):
    """Per area: which hint colours touch it (enough pixels). Returns (per_region, ucol, ys, xs, cid, lab).
    line=None: count every pixel, even on a line (used for single plan points)."""
    ys, xs, hc = hints
    keep = ~line[ys, xs] if line is not None else np.ones(len(ys), bool)
    ys, xs, hc = ys[keep], xs[keep], hc[keep].astype(np.int32)
    if not len(ys):
        z = np.zeros(0, np.int64)
        return {}, np.zeros((0, 3), np.int32), z, z, z, z
    col = hc.copy()
    if snap_on and len(keyc):
        d = np.sqrt(((hc[:, None, :] - keyc[None, :, :]) ** 2).sum(2))
        j = d.argmin(1)
        near = d[np.arange(len(hc)), j] <= snap
        col[near] = keyc[j[near]]
        col[(hc >= 250).all(1)] = EMPTY
    ucol, cid = np.unique(col, axis=0, return_inverse=True)
    cid = cid.ravel()
    lab = labels[ys, xs].astype(np.int64)
    pair, cnt = np.unique(lab * len(ucol) + cid, return_counts=True)
    per = {}
    for p in pair[cnt >= min_px]:
        per.setdefault(int(p // len(ucol)), []).append(int(p % len(ucol)))
    return per, ucol, ys, xs, cid, lab


def _border_counts(labels, n):
    """{(a, b): shared border length} for touching areas (a < b), measured at half size."""
    lab = labels[::2, ::2]
    keys = []
    for a, b in ((lab[:, :-1], lab[:, 1:]), (lab[:-1, :], lab[1:, :])):
        d = a != b
        lo = np.minimum(a[d], b[d]).astype(np.int64)
        hi = np.maximum(a[d], b[d]).astype(np.int64)
        keys.append(lo * (n + 1) + hi)
    u, c = np.unique(np.concatenate(keys), return_counts=True)
    return u // (n + 1), u % (n + 1), c


def _slivers(labels, line, n, cfg):
    """Leftover bits that are not objects: thin strips squeezed between lines, or crumbs."""
    inside = ~line
    dt = cv2.distanceTransform(inside.astype(np.uint8), cv2.DIST_L2, 5)
    widest = ndimage.maximum(dt, labels, index=np.arange(n + 1)) * 2
    body = np.bincount(labels.ravel(), weights=inside.ravel(), minlength=n + 1)
    return (widest < float(cfg.get("sliver_width_px", 14))) | (body < float(cfg.get("sliver_min_px", 600)))


def colour_flats(labels, line, layer_hints, key, cfg, plan=None, log=print):
    """Return (rgb HxWx3 uint8, alpha HxW bool, summary dict)."""
    n = int(labels.max())
    names, keyc = key_colours(key)
    snap = float(cfg.get("hint_snap", 40))
    min_px = int(cfg.get("hint_min_px", 8))
    areas = np.bincount(labels.ravel(), minlength=n + 1)

    regcol = np.zeros((n + 1, 3), np.int32)
    state = np.zeros(n + 1, np.uint8)  # 0 open, 1 outline, 2 point/stroke, 3 hint layer, 5 split
    splits = {}

    none = (np.zeros(0, int), np.zeros(0, int), np.zeros((0, 3), np.int32))
    plan_px, plan_areas, plan_pts = plan if plan else (none, [], none)
    for poly, c in plan_areas:  # whole objects
        m = np.zeros(labels.shape, np.uint8)
        cv2.fillPoly(m, [poly], 1)
        frac = np.bincount(labels.ravel(), weights=m.ravel(), minlength=n + 1) / np.maximum(areas, 1)
        sel = frac >= float(cfg.get("outline_min_inside", 0.6))
        sel[0] = False
        regcol[sel], state[sel] = c, 1

    # a point that landed on a line moves to the nearest spot that isn't line
    py, px, pc = plan_pts
    py, px = py.copy(), px.copy()
    R_ = 25
    for i in np.where(line[py, px])[0]:
        y0, x0 = max(py[i] - R_, 0), max(px[i] - R_, 0)
        free = ~line[y0:py[i] + R_ + 1, x0:px[i] + R_ + 1]
        if free.any():
            yy, xx = np.nonzero(free)
            j = ((yy + y0 - py[i]) ** 2 + (xx + x0 - px[i]) ** 2).argmin()
            py[i], px[i] = yy[j] + y0, xx[j] + x0
    plan_pts = (py, px, pc)

    # plan strokes, then plan points, then the hint layer (strongest)
    plan_both = tuple(np.concatenate([a, b]) for a, b in zip(plan_px, plan_pts))
    for level, src, snap_on, ln, mp in ((2, plan_both, False, None, 1), (3, layer_hints, True, line, min_px)):
        if level == 2:  # stroke pixels on lines don't count; points always count
            on_line = np.zeros(len(src[0]), bool)
            on_line[:len(plan_px[0])] = line[plan_px[0], plan_px[1]]
            src = tuple(a[~on_line] for a in src)
            # a stroke must cover a few pixels of an area to count; a point counts once
            per, ucol, ys, xs, cid, lab = _pixel_votes(labels, None, src, keyc, snap, 1, snap_on)
        else:
            per, ucol, ys, xs, cid, lab = _pixel_votes(labels, ln, src, keyc, snap, mp, snap_on)
        for r, cids in per.items():
            if len(cids) == 1:
                regcol[r], state[r] = ucol[cids[0]], level
                splits.pop(r, None)
            else:
                state[r] = 5
                splits[r] = (ucol, ys, xs, cid, lab, cids)

    # everything nobody gave a colour: palette colours by size, never the same as a touching area
    tiers = key.get("auto_tiers", {})
    scene = key.get("scene", {})
    tier_cols = {t: [tuple(scene[c]) for c in tiers.get(t, []) if c in scene] for t in ("large", "medium", "small")}
    if not all(tier_cols.values()):
        tier_cols = {t: [tuple(c) for c in key["town"]] for t in tier_cols}
    page = labels.size
    nb = _neighbours(labels, n)
    sliver = _slivers(labels, line, n, cfg) & (state == 0)
    sliver[0] = False
    auto = 0
    for r in np.argsort(-areas):
        if r == 0 or state[r] != 0 or sliver[r]:
            continue
        t = "large" if areas[r] >= 0.01 * page else "medium" if areas[r] >= 0.0006 * page else "small"
        choices = tier_cols[t]
        taken = {tuple(regcol[q]) for q in nb[r] if state[q] != 0}
        start = (r * 7) % len(choices)
        order = choices[start:] + choices[:start]
        regcol[r] = next((c for c in order if c not in taken), order[0])
        state[r] = 4
        auto += 1

    # slivers and crumbs take the colour of the neighbour they share the most edge with
    a_, b_, cnt = _border_counts(labels, n)
    best = {}
    for x, y, c in zip(a_, b_, cnt):
        for r, q in ((x, y), (y, x)):
            if sliver[r] and q != 0:
                best.setdefault(r, []).append((c, q))
    todo = [r for r in np.where(sliver)[0]]
    for _ in range(10):
        left = []
        for r in todo:
            ok = [(c, q) for c, q in best.get(r, []) if state[q] != 0]
            if not ok:
                left.append(r)
                continue
            regcol[r], state[r] = regcol[max(ok)[1]], 6
        if not left or len(left) == len(todo):
            todo = left
            break
        todo = left
    for r in todo:  # isolated crumbs: any palette colour
        regcol[r], state[r] = tier_cols["small"][0], 4
    absorbed = int((state == 6).sum())

    rgb = np.clip(regcol, 0, 255).astype(np.uint8)[labels]
    alpha = ~(regcol == EMPTY).all(1)[labels]

    if splits:  # areas with two or more hint colours: the nearest hint wins
        boxes = ndimage.find_objects(labels)
        for r, (ucol, ys, xs, cid, lab, cids) in splits.items():
            sl = boxes[r - 1]
            m = labels[sl] == r
            sel = (lab == r) & np.isin(cid, cids)
            seed = np.full(m.shape, -1, np.int32)
            seed[ys[sel] - sl[0].start, xs[sel] - sl[1].start] = cid[sel]
            idx = ndimage.distance_transform_edt(seed < 0, return_distances=False, return_indices=True)
            c = ucol[seed[idx[0], idx[1]]]
            sub_rgb, sub_a = rgb[sl], alpha[sl]
            sub_rgb[m] = np.clip(c[m], 0, 255)
            sub_a[m] = ~(c[m] == EMPTY).all(-1)

    summary = {
        "areas": n,
        "from_hint_layer": int((state == 3).sum()),
        "from_plan_points": int((state == 2).sum()),
        "from_plan_outlines": int((state == 1).sum()),
        "split_between_hints": len(splits),
        "auto_palette": auto,
        "slivers_joined_to_neighbour": absorbed,
    }
    log(f"  colours: {summary['from_hint_layer']} from your hint layer, {summary['from_plan_points']} from plan points, "
        f"{summary['from_plan_outlines']} from plan outlines, {len(splits)} split, {auto} automatic, "
        f"{absorbed} slivers joined to a neighbour")
    return rgb, alpha, summary
