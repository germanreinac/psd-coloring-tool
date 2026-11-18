"""Numbered region sheets, for writing a page's colour plan by area number instead of by coordinates.

  python -m megalith_flats.sheet make  "<page.psd>"   -> output/<page>/check/regions/panel_XX.jpg + regions.json
  python -m megalith_flats.sheet apply "<page name>"  -> maps/<page>.json from maps/<page>.ids.json

maps/<page>.ids.json looks like {"Skit fur | p3 cat": [12, 15], ...}: colour name -> area numbers as
printed on the sheets. `apply` turns each number into a point deep inside that area, so the plan keeps
working with the normal tool. "_cuts" and "_front" entries are copied over unchanged.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from . import extract, palette, panels, regions

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extras(name):
    for fn in (f"{name}.ids.json", f"{name}.json"):
        path = os.path.join(HERE, "maps", fn)
        if os.path.exists(path):
            m = palette.load(path)
            return m.get("_cuts"), m.get("_front")
    return None, None


def make(page, max_side=1500):
    cfg = palette.load(os.path.join(HERE, "config.json"))
    name = os.path.splitext(os.path.basename(page))[0]
    out = os.path.join(HERE, "output", name, "check", "regions")
    os.makedirs(out, exist_ok=True)
    cuts, fronts = _extras(name)
    ink, meta = extract.ink_from_psd(page, cfg)
    ink = regions.combine_ink(ink, meta.pop("back", None), fronts, cfg)
    labels, line = regions.find_regions(ink, cfg, cuts)
    masks = panels.panel_masks(meta, cfg, labels)
    n = int(labels.max())
    boxes = ndimage.find_objects(labels)
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    info = {}
    for r in range(1, n + 1):
        sl = boxes[r - 1]
        if sl is None:
            continue
        m = (labels[sl] == r) & ~line[sl]
        if not m.any():
            m = labels[sl] == r
        dt = cv2.distanceTransform(np.pad(m, 1).astype(np.uint8), cv2.DIST_L2, 3)[1:-1, 1:-1]
        y, x = np.unravel_index(dt.argmax(), dt.shape)
        info[r] = {"xy": [int(x + sl[1].start), int(y + sl[0].start)], "area": int(areas[r]), "width": float(dt.max() * 2)}
    sheets = {}
    np.savez_compressed(os.path.join(out, "labels.npz"), labels=labels.astype(np.int32), line=line)
    rng = np.random.default_rng(3)
    tint = rng.integers(150, 256, (n + 1, 3)).astype(np.uint8)
    for p, mask in sorted(masks.items()):
        ys, xs = np.where(mask)
        y0, y1, x0, x1 = max(ys.min() - 40, 0), ys.max() + 40, max(xs.min() - 40, 0), xs.max() + 40
        lab = labels[y0:y1, x0:x1]
        img = tint[lab].astype(np.float32)
        img[~mask[y0:y1, x0:x1]] = 255
        img *= (1.0 - ink[y0:y1, x0:x1, None])
        s = min(1.0, max_side / max(img.shape[:2]))
        sheets[p] = {"x0": int(x0), "y0": int(y0), "scale": s}  # page x = x0 + sheet x / scale
        im = Image.fromarray(img.clip(0, 255).astype(np.uint8))
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for r, i in info.items():
            x, y = i["xy"]
            if not (x0 <= x < x1 and y0 <= y < y1) or not mask[y, x]:
                continue
            i["panel"] = p
            size = 22 if i["width"] * s > 60 else 15 if i["width"] * s > 22 else 11
            d.text(((x - x0) * s, (y - y0) * s), str(r), fill=(200, 0, 0), anchor="mm",
                   font=ImageFont.load_default(size), stroke_width=2, stroke_fill="white")
        im.save(os.path.join(out, f"panel_{p}.jpg"), quality=90)
    with open(os.path.join(out, "regions.json"), "w") as f:
        json.dump({"size": meta["size"], "sheets": sheets, "regions": info}, f)
    print(f"{n} areas, sheets in {out}")


def apply(name):
    out = os.path.join(HERE, "output", name, "check", "regions", "regions.json")
    reg = palette.load(out)["regions"]
    ids = palette.load(os.path.join(HERE, "maps", f"{name}.ids.json"))
    plan = {"_help": "Made from the .ids.json file by megalith_flats.sheet; edit that file and run 'apply' again."}
    missing = []
    for key, vals in ids.items():
        if key.startswith("_"):
            if key in ("_cuts", "_front"):
                plan[key] = vals
            continue
        pts = []
        for v in vals:
            if isinstance(v, int):
                if str(v) in reg:
                    pts.append(reg[str(v)]["xy"])
                else:
                    missing.append(v)
            else:
                pts.append(v)  # a point, stroke or outline written by hand
        plan[key] = pts
    with open(os.path.join(HERE, "maps", f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1)
    used = {v for k, vals in ids.items() if not k.startswith("_") for v in vals if isinstance(v, int)}
    print(f"{len(used)} areas given a colour, {len(reg) - len(used)} left to automatic" + (f"; unknown numbers {missing}" if missing else ""))


if __name__ == "__main__":
    {"make": make, "apply": apply}[sys.argv[1]](sys.argv[2])
