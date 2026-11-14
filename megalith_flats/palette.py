"""Palette flats: colour regions from the Megalith colour key instead of random colours.

- Character parts come from a per-page map file: named key colour -> points on the page.
- Every other region gets a town colour from finished pages, chosen so that touching
  regions never share a colour (keeps them separate for the magic wand).
"""
import json
import numpy as np


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _neighbours(labels, n):
    lab = labels[::2, ::2]
    pairs = []
    for a, b in ((lab[:, :-1], lab[:, 1:]), (lab[:-1, :], lab[1:, :])):
        d = a != b
        pairs.append(np.stack([a[d], b[d]], 1))
    p = np.concatenate(pairs)
    p = np.unique(np.sort(p, 1).astype(np.int64), axis=0)
    nb = [set() for _ in range(n + 1)]
    for x, y in p:
        nb[x].add(y)
        nb[y].add(x)
    return nb


def palette_colours(labels, key, page_map, log=print):
    n = int(labels.max())
    cols = np.zeros((n + 1, 3), np.uint8)
    fixed = {}
    chars = key["characters"]
    for name, pts in page_map.items():
        if name.startswith("_"):
            continue
        if name not in chars:
            log(f"  map entry '{name}' is not in the colour key, skipped")
            continue
        for x, y in pts:
            if 0 <= y < labels.shape[0] and 0 <= x < labels.shape[1]:
                fixed[int(labels[y, x])] = name
    for r, name in fixed.items():
        cols[r] = chars[name]
    log(f"  {len(fixed)} regions coloured from the character key")

    town = [tuple(c) for c in key["town"]]
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    nb = _neighbours(labels, n)
    done = set(fixed)
    for r in np.argsort(-areas):
        if r == 0 or r in done:
            continue
        taken = {tuple(cols[q]) for q in nb[r] if q in done}
        start = r % len(town)
        pick = next((town[(start + i) % len(town)] for i in range(len(town))
                     if town[(start + i) % len(town)] not in taken), town[start])
        cols[r] = pick
        done.add(r)
    return cols, fixed
