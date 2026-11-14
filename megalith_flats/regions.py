"""Find enclosed areas in the line art and give every pixel (lines included) to one area.

Steps:
1. Line mask = ink above the threshold, minus tiny specks.
2. Close gaps: thicken lines by `gap_close_px`, so small breaks seal shut.
3. Each enclosed area of paper left over becomes a region ("seed").
4. Small areas that the thickening swallowed (eyes, buttons) are added back
   from the un-thickened line art.
5. Every remaining pixel (lines, closed gaps) joins its nearest region,
   so fills tuck under the lines with no white halo.
"""
import cv2
import numpy as np
from scipy import ndimage


def _components(mask):
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4, ltype=cv2.CV_32S)
    return n, lab


_NB = np.array([[1, 2, 4], [128, 0, 8], [64, 32, 16]], np.float32)  # neighbour code, clockwise from top-left


def _codes(mask):
    return cv2.filter2D(mask.astype(np.uint8), cv2.CV_32F, _NB, borderType=cv2.BORDER_CONSTANT).astype(np.uint8)


def _thin_luts():
    """Zhang-Suen thinning rules as lookup tables over the 8-neighbour code."""
    l1, l2 = np.zeros(256, bool), np.zeros(256, bool)
    for c in range(256):
        p = [(c >> i) & 1 for i in range(8)]  # P9,P2,P3,P4,P5,P6,P7,P8 (clockwise from top-left)
        p9, p2, p3, p4, p5, p6, p7, p8 = p
        seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
        b = sum(p)
        a = sum(1 for i in range(8) if seq[i] == 0 and seq[i + 1] == 1)
        if 2 <= b <= 6 and a == 1:
            l1[c] = p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0
            l2[c] = p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0
    return l1, l2


def skeleton(mask, max_iter=60):
    """One-pixel-wide centre lines of the line art."""
    sk = mask.copy()
    l1, l2 = _thin_luts()
    for _ in range(max_iter):
        changed = False
        for lut in (l1, l2):
            rm = sk & lut[_codes(sk)]
            if rm.any():
                sk &= ~rm
                changed = True
        if not changed:
            break
    return sk


def bridge_gaps(line, cfg, log=print):
    """Find where strokes stop short of another line and return thin invisible 'bridge' lines that close
    those gaps. A bridge is only made in the direction the stroke is heading, to a line that is not the
    stroke itself, within `gap_bridge_px`."""
    R = int(cfg.get("gap_bridge_px", 30))
    if R <= 0:
        return np.zeros_like(line)
    cone = np.cos(np.radians(float(cfg.get("gap_bridge_angle", 50))))
    h, w = line.shape
    sk = skeleton(line)
    nbr = np.unpackbits(_codes(sk)[..., None], axis=2).sum(2)
    # short marks (hair dashes, whiskers, cheek lines) are details, not outlines: they never bridge
    _, comp, st, _ = cv2.connectedComponentsWithStats(sk.astype(np.uint8), connectivity=8)
    long_stroke = st[:, cv2.CC_STAT_AREA] >= int(cfg.get("gap_min_stroke_px", 120))
    long_stroke[0] = False
    ys, xs = np.where(sk & (nbr == 1) & long_stroke[comp])
    bridges = np.zeros((h, w), np.uint8)
    made = 0
    for y, x in zip(ys, xs):
        y0, y1, x0, x1 = max(y - R, 0), min(y + R + 1, h), max(x - R, 0), min(x + R + 1, w)
        win = sk[y0:y1, x0:x1]
        ey, ex = y - y0, x - x0
        # walk back along the stroke from its end: these pixels are "itself", and give its direction
        dist = {(ey, ex): 0}
        frontier = [(ey, ex)]
        while frontier:
            nxt = []
            for cy, cx in frontier:
                d = dist[(cy, cx)] + 1
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        qy, qx = cy + dy, cx + dx
                        if 0 <= qy < win.shape[0] and 0 <= qx < win.shape[1] and win[qy, qx] and (qy, qx) not in dist:
                            dist[(qy, qx)] = d
                            nxt.append((qy, qx))
            frontier = nxt
        back = [p for p, d in dist.items() if 6 <= d <= 12]
        if not back:
            continue  # stroke too short to know its direction (a dot or tiny hatch)
        by, bx = np.mean([p[0] for p in back]), np.mean([p[1] for p in back])
        dvec = np.array([ey - by, ex - bx])
        dn = np.hypot(*dvec)
        if dn == 0:
            continue
        dvec /= dn
        cy, cx = np.where(win)
        vy, vx = cy - ey, cx - ex
        e = np.hypot(vy, vx)
        ok = (e >= 2) & (e <= R)
        ok &= (vy * dvec[0] + vx * dvec[1]) >= cone * np.maximum(e, 1e-6)  # ahead of the stroke
        own = np.array([dist.get((a, b), 10 ** 6) for a, b in zip(cy, cx)])
        ok &= own > 2.5 * e + 4  # not the stroke curling back on itself
        if not ok.any():
            continue
        i = np.argmin(np.where(ok, e, np.inf))
        cv2.line(bridges, (int(x), int(y)), (int(cx[i] + x0), int(cy[i] + y0)), 1, 2)
        made += 1
    log(f"  gap bridges: {made} (from {len(ys)} line ends)")
    return bridges.astype(bool)


def find_regions(ink, cfg, cuts=None, log=print):
    """cuts: hand-placed invisible lines from the colour plan ([[x, y], ...] each) that close gaps
    the automatic bridges can't, e.g. a wall that stops short of the ground."""
    line = ink >= cfg["line_threshold"]

    # 1. drop isolated specks
    n, lab, stats, _ = cv2.connectedComponentsWithStats(line.astype(np.uint8), connectivity=8)
    small = stats[:, cv2.CC_STAT_AREA] < cfg["min_speck_px"]
    small[0] = False
    line &= ~small[lab]
    log(f"  line pixels: {line.mean() * 100:.1f}% of page")
    line_only = line.copy()
    line = line | bridge_gaps(line, cfg, log)
    if cuts:
        c = np.zeros(line.shape, np.uint8)
        for pts in cuts:
            cv2.polylines(c, [np.array(pts, np.int32)], False, 1, 4)
        line |= c.astype(bool)
        log(f"  cut lines from the colour plan: {len(cuts)}")

    # 2. close gaps
    r = int(cfg["gap_close_px"])
    if r > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        thick = cv2.dilate(line.astype(np.uint8), k).astype(bool)
    else:
        thick = line

    # 3. seeds from the sealed paper areas
    n_seed, seeds = _components(~thick)
    min_area = cfg["min_region_px"]
    areas = np.bincount(seeds.ravel(), minlength=n_seed)
    keep = areas >= min_area
    keep[0] = False
    remap = np.zeros(n_seed, np.int32)
    remap[keep] = np.arange(1, keep.sum() + 1)
    seeds = remap[seeds]
    next_id = int(keep.sum()) + 1

    # 4. add back small areas that only exist in the thin line art
    n_raw, raw = _components(~line)
    raw_areas = np.bincount(raw.ravel(), minlength=n_raw)
    seeded = np.bincount(raw.ravel(), weights=(seeds > 0).ravel(), minlength=n_raw)
    rescue = (seeded == 0) & (raw_areas >= min_area)
    rescue[0] = False
    if rescue.any():
        ids = np.zeros(n_raw, np.int32)
        ids[rescue] = np.arange(next_id, next_id + rescue.sum())
        add = ids[raw]
        seeds = np.where(seeds == 0, add, seeds)
        next_id += int(rescue.sum())
    log(f"  regions: {next_id - 1} ({int(rescue.sum())} small ones rescued)")

    # 5. hand every unassigned pixel to its nearest region
    idx = ndimage.distance_transform_edt(seeds == 0, return_distances=False, return_indices=True)
    labels = seeds[idx[0], idx[1]]
    del idx
    return labels, line_only


def selection_colours(n, seed):
    """n distinct, mid-to-bright random colours (no near-black/white, no duplicates)."""
    rng = np.random.default_rng(seed)
    out, used = np.zeros((n + 1, 3), np.uint8), set()
    i = 1
    while i <= n:
        c = tuple(int(v) for v in rng.integers(30, 236, 3))
        if c in used:
            continue
        used.add(c)
        out[i] = c
        i += 1
    return out
