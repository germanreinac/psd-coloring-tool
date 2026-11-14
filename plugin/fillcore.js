/*
 * Gap-closing flat fill for line art.
 * Pure JavaScript, no Photoshop dependencies, so it can be tested in a browser.
 *
 * How it works:
 *  1. Turn the line art into an "ink" mask (dark and/or opaque pixels).
 *  2. Distance transform: every pixel learns how far it is from the nearest ink.
 *  3. Pixels closer than `gapSize` to ink are temporarily treated as wall.
 *     This thickens the lines, so any gap up to ~2 x gapSize gets sealed.
 *  4. Label the connected areas that remain (the region "cores").
 *  5. Grow the cores back out through the non-ink pixels, so each region
 *     reaches the line again at its full size.
 *  6. Areas that were completely swallowed by step 3 (thin closed strips)
 *     become regions of their own.
 *  7. Optionally grow every region under the lines, so flats have no white halo.
 */
(function (root) {
  "use strict";

  const OUTSIDE = -1; // label for the area touching the canvas edge (when skipped)
  const NONE = 0;

  /** rgba: Uint8Array/Uint8ClampedArray (w*h*4). Returns Float32 ink 0..1. */
  function inkFromRGBA(rgba, w, h, opts) {
    const n = w * h;
    const ink = new Uint8Array(n);
    const thr = Math.round((opts.inkThreshold ?? 0.5) * 255);
    for (let i = 0, p = 0; i < n; i++, p += 4) {
      const a = rgba[p + 3];
      // luminance-based darkness, weighted by opacity
      const lum = (rgba[p] * 54 + rgba[p + 1] * 183 + rgba[p + 2] * 19) >> 8;
      const dark = ((255 - lum) * a) / 255;
      ink[i] = dark >= thr ? 1 : 0;
    }
    return ink;
  }

  /** Two-pass chamfer (3-4) distance to nearest ink, in pixel units * 3. */
  function distanceToInk(ink, w, h) {
    const n = w * h;
    const BIG = 1 << 29;
    const d = new Int32Array(n);
    for (let i = 0; i < n; i++) d[i] = ink[i] ? 0 : BIG;
    // forward
    for (let y = 0; y < h; y++) {
      const row = y * w;
      for (let x = 0; x < w; x++) {
        const i = row + x;
        let v = d[i];
        if (v === 0) continue;
        if (x > 0) v = Math.min(v, d[i - 1] + 3);
        if (y > 0) {
          v = Math.min(v, d[i - w] + 3);
          if (x > 0) v = Math.min(v, d[i - w - 1] + 4);
          if (x < w - 1) v = Math.min(v, d[i - w + 1] + 4);
        }
        d[i] = v;
      }
    }
    // backward
    for (let y = h - 1; y >= 0; y--) {
      const row = y * w;
      for (let x = w - 1; x >= 0; x--) {
        const i = row + x;
        let v = d[i];
        if (v === 0) continue;
        if (x < w - 1) v = Math.min(v, d[i + 1] + 3);
        if (y < h - 1) {
          v = Math.min(v, d[i + w] + 3);
          if (x < w - 1) v = Math.min(v, d[i + w + 1] + 4);
          if (x > 0) v = Math.min(v, d[i + w - 1] + 4);
        }
        d[i] = v;
      }
    }
    return d;
  }

  /** 4-connected labeling of pixels where mask[i] && labels[i]===NONE. */
  function labelComponents(mask, labels, w, h, nextLabel, minArea, queue) {
    const n = w * h;
    const areas = [0];
    for (let s = 0; s < n; s++) {
      if (!mask[s] || labels[s] !== NONE) continue;
      const lab = nextLabel;
      let head = 0, tail = 0;
      queue[tail++] = s;
      labels[s] = lab;
      while (head < tail) {
        const i = queue[head++];
        const x = i % w;
        if (x > 0) { const j = i - 1; if (mask[j] && labels[j] === NONE) { labels[j] = lab; queue[tail++] = j; } }
        if (x < w - 1) { const j = i + 1; if (mask[j] && labels[j] === NONE) { labels[j] = lab; queue[tail++] = j; } }
        if (i >= w) { const j = i - w; if (mask[j] && labels[j] === NONE) { labels[j] = lab; queue[tail++] = j; } }
        if (i < n - w) { const j = i + w; if (mask[j] && labels[j] === NONE) { labels[j] = lab; queue[tail++] = j; } }
      }
      if (tail < minArea) {
        // too small: un-label so it gets absorbed by a neighbour later
        for (let k = 0; k < tail; k++) labels[queue[k]] = NONE;
      } else {
        areas[lab] = tail;
        nextLabel++;
      }
    }
    return nextLabel;
  }

  /** Multi-source BFS: grow existing labels into pixels where allow[i] is set. */
  function grow(labels, allow, w, h, queue, blockLabel) {
    const n = w * h;
    let head = 0, tail = 0;
    for (let i = 0; i < n; i++) {
      const l = labels[i];
      if (l === NONE || l === blockLabel) continue;
      const x = i % w;
      if ((x > 0 && labels[i - 1] === NONE && allow[i - 1]) ||
          (x < w - 1 && labels[i + 1] === NONE && allow[i + 1]) ||
          (i >= w && labels[i - w] === NONE && allow[i - w]) ||
          (i < n - w && labels[i + w] === NONE && allow[i + w])) {
        queue[tail++] = i;
      }
    }
    while (head < tail) {
      const i = queue[head++];
      const lab = labels[i];
      const x = i % w;
      if (x > 0) { const j = i - 1; if (labels[j] === NONE && allow[j]) { labels[j] = lab; queue[tail++] = j; } }
      if (x < w - 1) { const j = i + 1; if (labels[j] === NONE && allow[j]) { labels[j] = lab; queue[tail++] = j; } }
      if (i >= w) { const j = i - w; if (labels[j] === NONE && allow[j]) { labels[j] = lab; queue[tail++] = j; } }
      if (i < n - w) { const j = i + w; if (labels[j] === NONE && allow[j]) { labels[j] = lab; queue[tail++] = j; } }
    }
  }

  /**
   * Main entry.
   * opts: { gapSize (px), inkThreshold (0..1), minRegion (px), skipOutside (bool), fillUnderLines (bool) }
   * Returns { labels: Int32Array, count, outside: Set of label ids touching edge (if skipOutside) }
   */
  function segment(rgba, w, h, opts) {
    opts = opts || {};
    const gap = Math.max(0, opts.gapSize ?? 4);
    const minRegion = Math.max(1, opts.minRegion ?? 20);
    const n = w * h;

    const ink = inkFromRGBA(rgba, w, h, opts);
    const labels = new Int32Array(n);
    const queue = new Int32Array(n);

    // core = far enough from ink that small gaps are sealed
    const core = new Uint8Array(n);
    if (gap > 0) {
      const dist = distanceToInk(ink, w, h);
      const limit = Math.round(gap * 3);
      for (let i = 0; i < n; i++) core[i] = dist[i] > limit ? 1 : 0;
    } else {
      for (let i = 0; i < n; i++) core[i] = ink[i] ? 0 : 1;
    }

    let next = labelComponents(core, labels, w, h, 1, minRegion, queue);

    // grow cores back to the line through paper (non-ink) pixels
    const paper = new Uint8Array(n);
    for (let i = 0; i < n; i++) paper[i] = ink[i] ? 0 : 1;
    grow(labels, paper, w, h, queue);

    // thin closed areas that had no core: make them their own regions
    next = labelComponents(paper, labels, w, h, next, minRegion, queue);
    // tiny leftover paper specks join a neighbour
    grow(labels, paper, w, h, queue);

    // find regions touching the canvas border
    const outside = new Set();
    if (opts.skipOutside) {
      for (let x = 0; x < w; x++) { addOut(labels[x]); addOut(labels[n - w + x]); }
      for (let y = 0; y < h; y++) { addOut(labels[y * w]); addOut(labels[y * w + w - 1]); }
    }
    function addOut(l) { if (l > 0) outside.add(l); }

    if (opts.skipOutside && outside.size) {
      for (let i = 0; i < n; i++) if (outside.has(labels[i])) labels[i] = OUTSIDE;
    }

    if (opts.fillUnderLines !== false) {
      const all = new Uint8Array(n).fill(1);
      // outside area does not spread under the lines; inner regions do
      grow(labels, all, w, h, queue, OUTSIDE);
    }

    return { labels, count: next - 1, OUTSIDE, NONE };
  }

  /** Distinct-ish colours via golden-ratio hue stepping. */
  function regionPalette(count, seed) {
    const cols = new Uint8Array((count + 1) * 3);
    let hue = (seed ?? 0.13) % 1;
    const used = new Set();
    for (let l = 1; l <= count; l++) {
      hue = (hue + 0.618033988749895) % 1;
      const s = 0.45 + ((l * 7) % 5) * 0.1;
      const v = 0.65 + ((l * 3) % 4) * 0.1;
      let [r, g, b] = hsv(hue, s, v);
      let key = (r << 16) | (g << 8) | b;
      while (used.has(key)) { r = (r + 1) & 255; key = (r << 16) | (g << 8) | b; }
      used.add(key);
      cols[l * 3] = r; cols[l * 3 + 1] = g; cols[l * 3 + 2] = b;
    }
    return cols;
  }

  function hsv(h, s, v) {
    const i = Math.floor(h * 6), f = h * 6 - i;
    const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
    const m = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
    return m.map((c) => Math.round(c * 255));
  }

  /** Paint every region with its own colour into an RGBA buffer. */
  function renderFlats(seg, w, h, seed) {
    const out = new Uint8Array(w * h * 4);
    const pal = regionPalette(seg.count, seed);
    const L = seg.labels;
    for (let i = 0, p = 0; i < L.length; i++, p += 4) {
      const l = L[i];
      if (l <= 0) continue;
      out[p] = pal[l * 3]; out[p + 1] = pal[l * 3 + 1]; out[p + 2] = pal[l * 3 + 2]; out[p + 3] = 255;
    }
    return out;
  }

  /** Paint chosen labels with one colour on top of an existing RGBA buffer. */
  function paintLabels(seg, chosen, target, rgb) {
    const L = seg.labels;
    let painted = 0;
    for (let i = 0, p = 0; i < L.length; i++, p += 4) {
      if (!chosen.has(L[i])) continue;
      target[p] = rgb[0]; target[p + 1] = rgb[1]; target[p + 2] = rgb[2]; target[p + 3] = 255;
      painted++;
    }
    return painted;
  }

  /** 0/255 mask of chosen labels (for making a selection). */
  function maskOfLabels(seg, chosen) {
    const L = seg.labels;
    const m = new Uint8Array(L.length);
    for (let i = 0; i < L.length; i++) if (chosen.has(L[i])) m[i] = 255;
    return m;
  }

  const api = { segment, renderFlats, paintLabels, maskOfLabels, regionPalette };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FillCore = api;
})(typeof window !== "undefined" ? window : this);
