const { app, core, imaging, action, constants } = require("photoshop");
const FillCore = require("./fillcore.js");

const FLATS_NAME = "Flats";
let lineArtLayerId = null; // null = use the active layer

// ---------- UI helpers ----------
const $ = (id) => document.getElementById(id);

function bindSlider(id, labelId, suffix) {
  const s = $(id);
  const update = () => { $(labelId).textContent = Math.round(Number(s.value)) + suffix; };
  s.addEventListener("input", update);
  s.addEventListener("change", update);
  update();
}
bindSlider("gap", "gapVal", " px");
bindSlider("ink", "inkVal", "%");
bindSlider("minRegion", "minVal", " px");

function status(msg, isError) {
  const el = $("status");
  el.textContent = msg;
  el.className = isError ? "error" : "";
}

function options() {
  return {
    gapSize: Number($("gap").value) / 2, // slider is gap WIDTH; walls grow from both sides
    inkThreshold: Number($("ink").value) / 100,
    minRegion: Number($("minRegion").value),
    fillUnderLines: $("underLines").checked,
    skipOutside: $("skipOutside").checked,
  };
}

// ---------- Photoshop helpers ----------
function allLayers(layers, out = []) {
  for (const l of layers) {
    out.push(l);
    if (l.layers && l.layers.length) allLayers(l.layers, out);
  }
  return out;
}

function findLayerById(doc, id) {
  return allLayers(doc.layers).find((l) => l.id === id) || null;
}

function getLineArtLayer(doc) {
  if (lineArtLayerId != null) {
    const l = findLayerById(doc, lineArtLayerId);
    if (l) return l;
  }
  const active = doc.activeLayers[0];
  if (!active) throw new Error("Select your line art layer first.");
  if (active.name === FLATS_NAME) {
    throw new Error('The "Flats" layer is selected. Select your line art layer (or click "Use active layer as line art").');
  }
  return active;
}

function docSize(doc) {
  return { w: Math.round(doc.width), h: Math.round(doc.height) };
}

/** Reads a layer into a full-document RGBA buffer (transparent where empty). */
async function readLayerRGBA(doc, layer, w, h) {
  const out = new Uint8Array(w * h * 4);
  let res;
  try {
    res = await imaging.getPixels({
      documentID: doc.id,
      layerID: layer.id,
      sourceBounds: { left: 0, top: 0, right: w, bottom: h },
      componentSize: 8,
      colorSpace: "RGB",
    });
  } catch (e) {
    return out; // empty layer
  }
  const img = res.imageData;
  try {
    const data = await img.getData({ chunky: true });
    const comps = img.components;
    const b = res.sourceBounds;
    const bw = img.width, bh = img.height;
    for (let y = 0; y < bh; y++) {
      const ty = b.top + y;
      if (ty < 0 || ty >= h) continue;
      for (let x = 0; x < bw; x++) {
        const tx = b.left + x;
        if (tx < 0 || tx >= w) continue;
        const s = (y * bw + x) * comps;
        const d = (ty * w + tx) * 4;
        out[d] = data[s];
        out[d + 1] = data[s + 1];
        out[d + 2] = data[s + 2];
        out[d + 3] = comps === 4 ? data[s + 3] : 255;
      }
    }
  } finally {
    img.dispose();
  }
  return out;
}

async function writeLayerRGBA(doc, layer, rgba, w, h) {
  const img = await imaging.createImageDataFromBuffer(rgba, {
    width: w,
    height: h,
    components: 4,
    chunky: true,
    colorSpace: "RGB",
    colorProfile: "sRGB IEC61966-2.1",
  });
  try {
    await imaging.putPixels({
      documentID: doc.id,
      layerID: layer.id,
      imageData: img,
      replace: true,
      targetBounds: { left: 0, top: 0 },
    });
  } finally {
    img.dispose();
  }
}

/** Finds the Flats layer, or creates it just below the line art. */
async function getOrCreateFlats(doc, lineLayer) {
  const existing = allLayers(doc.layers).find((l) => l.name === FLATS_NAME && l.id !== lineLayer.id);
  if (existing) return existing;

  await action.batchPlay(
    [
      { _obj: "select", _target: [{ _ref: "layer", _id: lineLayer.id }], makeVisible: false },
      { _obj: "make", _target: [{ _ref: "layer" }], using: { _obj: "layer", name: FLATS_NAME } },
    ],
    {}
  );
  const flats = doc.activeLayers[0];
  if (lineLayer.isBackgroundLayer) {
    // Nothing can go under a Background layer: keep flats on top and multiply them.
    flats.blendMode = constants.BlendMode.MULTIPLY;
  } else {
    flats.move(lineLayer, constants.ElementPlacement.PLACEAFTER);
  }
  return flats;
}

/** Collects the region labels under color samplers and under the current selection. */
async function markedLabels(doc, seg, w, h) {
  const chosen = new Set();
  const L = seg.labels;

  try {
    for (const s of doc.colorSamplers) {
      const x = Math.floor(s.position.x), y = Math.floor(s.position.y);
      if (x >= 0 && y >= 0 && x < w && y < h) {
        const l = L[y * w + x];
        if (l !== 0) chosen.add(l);
      }
    }
  } catch (e) { /* no samplers */ }

  try {
    const sel = await imaging.getSelection({
      documentID: doc.id,
      sourceBounds: { left: 0, top: 0, right: w, bottom: h },
    });
    if (sel && sel.imageData) {
      const img = sel.imageData;
      const data = await img.getData({ chunky: true });
      const b = sel.sourceBounds;
      const votes = new Map();
      for (let y = 0; y < img.height; y++) {
        for (let x = 0; x < img.width; x++) {
          if (data[y * img.width + x] < 128) continue;
          const tx = b.left + x, ty = b.top + y;
          if (tx < 0 || ty < 0 || tx >= w || ty >= h) continue;
          const l = L[ty * w + tx];
          if (l !== 0) votes.set(l, (votes.get(l) || 0) + 1);
        }
      }
      img.dispose();
      // ignore areas the selection only grazes by a few pixels
      for (const [l, v] of votes) if (v >= 4) chosen.add(l);
    }
  } catch (e) { /* no selection */ }

  return chosen;
}

async function clearSamplersIfWanted(doc) {
  if (!$("clearSamplers").checked) return;
  try { doc.colorSamplers.removeAll(); } catch (e) { /* older PS */ }
}

/** Runs fn inside a modal scope as a single undo step. */
async function runModal(name, fn) {
  const doc = app.activeDocument;
  if (!doc) throw new Error("Open a document first.");
  if (doc.mode !== constants.DocumentMode.RGB) {
    throw new Error("Document must be in RGB mode (Image > Mode > RGB Color).");
  }
  if (doc.bitsPerChannel !== constants.BitsPerChannelType.EIGHT) {
    throw new Error("Document must be 8 bits/channel (Image > Mode > 8 Bits/Channel).");
  }
  return core.executeAsModal(async (ctx) => {
    const hist = await ctx.hostControl.suspendHistory({ documentID: doc.id, name });
    try {
      return await fn(doc);
    } finally {
      await ctx.hostControl.resumeHistory(hist);
    }
  }, { commandName: name });
}

async function analyse(doc, opts) {
  const { w, h } = docSize(doc);
  const line = getLineArtLayer(doc);
  const rgba = await readLayerRGBA(doc, line, w, h);
  const seg = FillCore.segment(rgba, w, h, opts);
  return { w, h, line, seg };
}

// ---------- Commands ----------
async function flatAll() {
  const opts = options();
  const n = await runModal("Smart Flat Fill: flat everything", async (doc) => {
    const { w, h, line, seg } = await analyse(doc, opts);
    const flats = await getOrCreateFlats(doc, line);
    const rgba = FillCore.renderFlats(seg, w, h, Math.random());
    await writeLayerRGBA(doc, flats, rgba, w, h);
    return seg.count;
  });
  status(`Done: ${n} areas flatted on the "${FLATS_NAME}" layer. Use Magic Wand (Contiguous off) on it to pick and recolour areas.`);
}

async function fillMarked() {
  const opts = options();
  const fg = app.foregroundColor.rgb;
  const rgb = [Math.round(fg.red), Math.round(fg.green), Math.round(fg.blue)];
  const n = await runModal("Smart Flat Fill: fill", async (doc) => {
    const { w, h, line, seg } = await analyse(doc, opts);
    const chosen = await markedLabels(doc, seg, w, h);
    if (!chosen.size) throw new Error("Nothing marked. Click inside areas with the Color Sampler tool (Shift+I), or make a rough selection touching them.");
    const flats = await getOrCreateFlats(doc, line);
    const target = await readLayerRGBA(doc, flats, w, h);
    FillCore.paintLabels(seg, chosen, target, rgb);
    await writeLayerRGBA(doc, flats, target, w, h);
    await clearSamplersIfWanted(doc);
    return chosen.size;
  });
  status(`Filled ${n} area${n === 1 ? "" : "s"} on the "${FLATS_NAME}" layer.`);
}

async function selectMarked() {
  const opts = options();
  const n = await runModal("Smart Flat Fill: select", async (doc) => {
    const { w, h, seg } = await analyse(doc, opts);
    const chosen = await markedLabels(doc, seg, w, h);
    if (!chosen.size) throw new Error("Nothing marked. Click inside areas with the Color Sampler tool (Shift+I), or make a rough selection touching them.");
    const mask = FillCore.maskOfLabels(seg, chosen);
    const img = await imaging.createImageDataFromBuffer(mask, {
      width: w, height: h, components: 1, chunky: true, colorSpace: "Grayscale",
    });
    try {
      await imaging.putSelection({ documentID: doc.id, imageData: img });
    } finally {
      img.dispose();
    }
    await clearSamplersIfWanted(doc);
    return chosen.size;
  });
  status(`Selected ${n} area${n === 1 ? "" : "s"}. Fill it with any tool (e.g. Alt+Backspace).`);
}

function guard(fn) {
  return async () => {
    status("Working…");
    try {
      await fn();
    } catch (e) {
      console.error(e);
      status(e && e.message ? e.message : String(e), true);
    }
  };
}

$("btnFlatAll").addEventListener("click", guard(flatAll));
$("btnFillMarked").addEventListener("click", guard(fillMarked));
$("btnSelectMarked").addEventListener("click", guard(selectMarked));
$("btnSetLine").addEventListener("click", () => {
  const doc = app.activeDocument;
  const l = doc && doc.activeLayers[0];
  if (!l) return status("Select a layer first.", true);
  lineArtLayerId = l.id;
  $("lineArtName").textContent = l.name;
  status(`Line art set to "${l.name}".`);
});
