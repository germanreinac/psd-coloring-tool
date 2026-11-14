"""Prove that a flatted page is the original plus Flats, and nothing else.

Takes a fingerprint of every layer and folder (name, kind, visibility, opacity, blend mode, position,
clipping, pixels, mask) before and after, and lists anything that differs. The only differences
allowed are the Flats layers the tool adds, a new 'color' folder that holds one, and a hint layer.
"""
import hashlib

import numpy as np


def _hash_channels(layer):
    """Hash of the layer's stored pixel data (all channels, the mask channel included)."""
    h = hashlib.sha1()
    try:
        for info, ch in zip(layer._record.channel_info, layer._channels):
            h.update(str(int(info.id)).encode())
            h.update(bytes(ch.data))
        return h.hexdigest()
    except Exception:
        return None


def _hash_pixels(layer):
    """Hash of the decoded pixels and mask (slower; used when the stored data was re-packed)."""
    h = hashlib.sha1()
    if not layer.is_group() and layer.width and layer.height:
        try:
            a = layer.numpy()
            h.update(np.ascontiguousarray((a * 255).round().astype(np.uint8)).tobytes())
        except Exception:
            pass
    if layer.has_mask() and layer.mask.width and layer.mask.height:
        h.update(layer.mask.topil().tobytes())
    return h.hexdigest()


def _entry(layer):
    mask = None
    if layer.has_mask():
        m = layer.mask
        mask = (tuple(m.bbox), int(m.background_color), bool(m.disabled))
    return {
        "name": layer.name, "kind": layer.kind, "visible": bool(layer.visible), "opacity": int(layer.opacity),
        "blend": str(layer.blend_mode), "bbox": None if layer.is_group() else tuple(layer.bbox),
        "clipping": bool(getattr(layer, "clipping", False)), "mask": mask,
        "vector_mask": bool(layer.has_vector_mask()), "effects": bool(layer.has_effects()),
        "raw": _hash_channels(layer),
    }


def _added(layer, cfg):
    """True for things the tool itself puts in the page."""
    flats = cfg["layers"]["flats"]["name"]
    names = {s.lower() for s in cfg.get("color_group_names", ["color", "colour"])}
    name = layer.name.strip()
    if layer.is_group():
        kids = list(layer)
        return name.lower() in names and len(kids) == 1 and not kids[0].is_group() and kids[0].name.strip() == flats
    if name == flats:
        return True
    return name == cfg.get("hint_layer_name", "Flat hints") and layer.width <= 1 and layer.height <= 1


def snapshot(psd, cfg, deep=False):
    """Flat list of (path, fingerprint) for everything in the page that the tool did not add."""
    out = []

    def walk(group, trail):
        for i, layer in enumerate(l for l in group if not _added(l, cfg)):
            path = trail + [f"{i}:{layer.name.strip()}"]
            e = _entry(layer)
            if deep or e["raw"] is None:
                e["pixels"] = _hash_pixels(layer)
            out.append(("/".join(path), e))
            if layer.is_group():
                walk(layer, path)

    walk(psd, [])
    return {"size": tuple(psd.size), "mode": str(psd.color_mode), "depth": int(psd.depth), "layers": out}


def compare(before, after_psd, cfg, before_psd=None):
    """Return a list of plain-language differences (empty = the page is untouched apart from Flats)."""
    after = snapshot(after_psd, cfg)
    diffs = []
    for k in ("size", "mode", "depth"):
        if before[k] != after[k]:
            diffs.append(f"document {k} changed: {before[k]} -> {after[k]}")
    b, a = before["layers"], after["layers"]
    if [p for p, _ in b] != [p for p, _ in a]:
        gone = [p for p in (p for p, _ in b) if p not in {q for q, _ in a}]
        new = [p for p in (p for p, _ in a) if p not in {q for q, _ in b}]
        diffs.append(f"layer list changed: missing {gone[:10]}, unexpected {new[:10]}")
        return diffs
    lookup_b = _by_path(before_psd, cfg) if before_psd is not None else {}
    lookup_a = _by_path(after_psd, cfg)
    for (path, eb), (_, ea) in zip(b, a):
        for k in eb:
            if k in ("raw", "pixels") or eb[k] == ea.get(k):
                continue
            what = "mask" if k == "mask" else k
            diffs.append(f"{path}: {what} changed: {eb[k]} -> {ea.get(k)}")
        if eb["raw"] != ea["raw"] or eb["raw"] is None:
            # stored bytes differ (e.g. re-packed): compare the actual pixels and mask
            pb = eb.get("pixels") or (_hash_pixels(lookup_b[path]) if path in lookup_b else None)
            pa = _hash_pixels(lookup_a[path])
            if pb is None:
                diffs.append(f"{path}: could not confirm the pixels are unchanged")
            elif pb != pa:
                diffs.append(f"{path}: pixels or mask changed")
    return diffs


def _by_path(psd, cfg):
    out = {}

    def walk(group, trail):
        for i, layer in enumerate(l for l in group if not _added(l, cfg)):
            path = trail + [f"{i}:{layer.name.strip()}"]
            out["/".join(path)] = layer
            if layer.is_group():
                walk(layer, path)

    walk(psd, [])
    return out
