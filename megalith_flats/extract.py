"""Pull the line art out of a layered page (or a flat PNG/JPG) as a single ink map.

The ink map is a float array (0 = paper, 1 = solid line) the size of the page.
"""
import re
import numpy as np
from PIL import Image


def _place(canvas, layer_rgba, left, top, opacity):
    """Composite one layer's ink (alpha * darkness) onto the canvas with 'over'."""
    h, w = canvas.shape
    lh, lw = layer_rgba.shape[:2]
    x0, y0 = max(left, 0), max(top, 0)
    x1, y1 = min(left + lw, w), min(top + lh, h)
    if x1 <= x0 or y1 <= y0:
        return
    sub = layer_rgba[y0 - top:y1 - top, x0 - left:x1 - left]
    alpha = sub[..., 3] if sub.shape[2] == 4 else np.ones(sub.shape[:2], np.float32)
    darkness = 1.0 - sub[..., :3].mean(axis=2)  # black line = 1, white = 0
    ink = (alpha * darkness * opacity).astype(np.float32)
    region = canvas[y0:y1, x0:x1]
    region[:] = region + ink * (1.0 - region)  # 'over' for ink coverage


def ink_from_psd(path, cfg, log=print):
    from psd_tools import PSDImage

    gcfg = cfg["line_groups"]
    panel_re = re.compile(gcfg["panel_group_pattern"])
    skip = {s.lower() for s in gcfg["skip_groups"]}
    hint_word = cfg.get("hint_layer_word", "hint").lower()
    psd = PSDImage.open(path)
    w, h = psd.size
    ink = np.zeros((h, w), np.float32)
    border = np.zeros((h, w), np.float32)  # panel borders only (layout group)
    small = (h // PANEL_SCALE + 1, w // PANEL_SCALE + 1)
    meta = {"size": (w, h), "panels": {}, "used_layers": [], "panel_ink": {}, "panel_paths": {}}

    def visible(layer):
        return gcfg["include_hidden"] or layer.visible

    def collect(group, trail, panel):
        for layer in group:
            if not visible(layer):
                continue
            name = layer.name.strip()
            if layer.is_group():
                if name.lower() in skip:
                    continue
                collect(layer, trail + [name], panel)
                continue
            if layer.kind not in ("pixel",) or layer.width == 0 or layer.height == 0:
                continue
            if hint_word in name.lower():
                continue  # colour instructions, not line art
            arr = layer.numpy()
            _place(ink, arr, layer.left, layer.top, layer.opacity / 255.0)
            meta["used_layers"].append("/".join(trail + [name]))
            if panel is None:
                _place(border, arr, layer.left, layer.top, layer.opacity / 255.0)
            else:
                # low-res copy of this panel's ink, used to match panel shapes to panel folders
                pi = meta["panel_ink"].setdefault(panel, np.zeros(small, np.float32))
                a = arr[::PANEL_SCALE, ::PANEL_SCALE]
                tmp = np.zeros(small, np.float32)
                _place(tmp, a, layer.left // PANEL_SCALE, layer.top // PANEL_SCALE, layer.opacity / 255.0)
                np.maximum(pi, tmp, out=pi)
                bb = meta["panels"].setdefault(panel, list(layer.bbox))
                bb[0], bb[1] = min(bb[0], layer.left), min(bb[1], layer.top)
                bb[2], bb[3] = max(bb[2], layer.right), max(bb[3], layer.bottom)

    def scan(group, trail):
        for top in group:
            name = top.name.strip()
            if not top.is_group() or not visible(top):
                continue
            if panel_re.match(name):
                meta["panel_paths"][name] = trail + [name]
                collect(top, trail + [name], name)
            elif name.lower() == gcfg["border_group"].lower():
                collect(top, trail + [name], None)
            elif name.lower() in {p.lower() for p in gcfg.get("panel_parents", [])}:
                scan(top, trail + [name])  # e.g. a "Panels" folder holding 1, 2, 3...

    scan(psd, [])
    log(f"  used {len(meta['used_layers'])} line layers from {len(meta['panels'])} panels + borders")
    meta["dpi"] = _dpi(psd)
    from .hints import read_hint_layers
    meta["hints"], meta["hint_layers"] = read_hint_layers(psd, cfg)
    log(f"  hint layers: {meta['hint_layers'] or 'none'} ({len(meta['hints'][0])} hint pixels)")
    meta["border"] = np.clip(border, 0, 1)
    return np.clip(ink, 0, 1), meta


PANEL_SCALE = 8


def _dpi(psd):
    try:
        res = psd.image_resources.get_data(1005)  # ResolutionInfo, 16.16 fixed point
        return res.horizontal / 65536.0
    except Exception:
        return 300.0


def ink_from_image(path, log=print):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA"):
        a = np.asarray(img.convert("RGBA"), np.float32) / 255.0
        ink = a[..., 3] * (1.0 - a[..., :3].mean(axis=2))
    else:
        g = np.asarray(img.convert("L"), np.float32) / 255.0
        ink = 1.0 - g
    dpi = img.info.get("dpi", (300, 300))[0]
    log(f"  read flat image {img.size}")
    return ink.astype(np.float32), {"size": img.size, "panels": {}, "used_layers": [path], "dpi": float(dpi)}
