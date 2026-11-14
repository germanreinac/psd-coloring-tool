"""Write results as editable layers: PNGs + a Photoshop stacking script, and a layered PSD."""
import json
import os
import numpy as np
from PIL import Image

BLEND_JSX = {"normal": "BlendMode.NORMAL", "multiply": "BlendMode.MULTIPLY", "screen": "BlendMode.SCREEN",
             "overlay": "BlendMode.OVERLAY"}


def layer_images(ink, labels, colours, cfg):
    h, w = labels.shape
    lines = np.zeros((h, w, 4), np.uint8)  # black line art on transparent
    lines[..., 3] = (np.clip(ink, 0, 1) * 255).astype(np.uint8)
    flats = colours[labels]
    empty = np.zeros((h, w, 4), np.uint8)
    paper = np.full((h, w, 3), 255, np.uint8)
    L = cfg["layers"]
    # top to bottom, like the Photoshop layers panel
    return [
        (L["lines"], Image.fromarray(lines, "RGBA")),
        (L["lights"], Image.fromarray(empty, "RGBA")),
        (L["shadows"], Image.fromarray(empty, "RGBA")),
        (L["flats"], Image.fromarray(flats, "RGB")),
        (L["paper"], Image.fromarray(paper, "RGB")),
    ]


def write_pngs_and_jsx(layers, out_dir, dpi, page_name):
    files = []
    for i, (spec, img) in enumerate(layers):
        fn = f"{i + 1:02d}_{spec['name'].replace(' ', '_')}.png"
        img.save(os.path.join(out_dir, fn), dpi=(dpi, dpi), compress_level=1)
        files.append((spec, fn))

    # Photoshop script: stacks the PNGs into a new layered document.
    lines = [
        "// Run in Photoshop: File > Scripts > Browse... and pick this file.",
        "#target photoshop",
        "var here = new File($.fileName).parent;",
        f"var first = app.open(new File(here + '/{files[-1][1]}'));",
        "var doc = first;",
        f"doc.activeLayer.isBackgroundLayer = false; doc.activeLayer.name = '{files[-1][0]['name']}';",
    ]
    for spec, fn in reversed(files[:-1]):  # bottom to top
        lines += [
            f"var src = app.open(new File(here + '/{fn}'));",
            "src.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING); src.close(SaveOptions.DONOTSAVECHANGES);",
            "app.activeDocument = doc;",
            f"doc.activeLayer.name = '{spec['name']}';",
            f"doc.activeLayer.blendMode = {BLEND_JSX.get(spec.get('blend', 'normal'), 'BlendMode.NORMAL')};",
            f"doc.activeLayer.opacity = {spec.get('opacity', 100)};",
        ]
    lines.append(f"doc.saveAs(new File(here + '/{page_name}_flats_from_script.psd'));")
    with open(os.path.join(out_dir, "build_layers.jsx"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def add_rgba_layer(parent, img, name, left=0, top=0):
    """Add a pixel layer that keeps the image's alpha as real layer transparency.
    (psd-tools' own helpers turn alpha into a layer mask on plain RGB documents.)"""
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import Compression

    psd = parent._psd if hasattr(parent, "_psd") and parent._psd is not None else parent
    rec, chans = PixelLayer._build_layer_record_and_channels(
        img.convert("RGBA"), name, left, top, Compression.RLE,
        version=psd._record.header.version, depth=psd._record.header.depth)
    layer = PixelLayer(parent, rec, chans)
    parent.append(layer)
    return layer


def write_psd(layers, path, dpi):
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import BlendMode

    modes = {"normal": BlendMode.NORMAL, "multiply": BlendMode.MULTIPLY, "screen": BlendMode.SCREEN}
    w, h = layers[0][1].size
    psd = PSDImage.new("RGB", (w, h), depth=8)
    for spec, img in reversed(layers):  # psd-tools appends bottom-up
        layer = add_rgba_layer(psd, img, spec["name"])
        layer.blend_mode = modes.get(spec.get("blend", "normal"), BlendMode.NORMAL)
        layer.opacity = round(spec.get("opacity", 100) * 2.55)
        psd.append(layer)
    _set_dpi(psd, dpi)
    psd.save(path)


def _set_dpi(psd, dpi):
    """Store the page resolution so Photoshop opens it at the source dpi (not 72)."""
    from psd_tools.constants import Resource
    from psd_tools.psd.image_resources import ImageResource, ResoulutionInfo

    fixed = int(round(dpi * 65536))
    info = ResoulutionInfo(horizontal=fixed, horizontal_unit=1, width_unit=1,
                           vertical=fixed, vertical_unit=1, height_unit=1)
    psd.image_resources[Resource.RESOLUTION_INFO] = ImageResource(key=Resource.RESOLUTION_INFO.value, data=info)


def write_preview(ink, rgb, alpha, path, max_side=2400):
    """Flats (empty areas shown white) with the line art multiplied on top."""
    flats = np.where(alpha[..., None], rgb, 255).astype(np.float32)
    shown = flats * (1.0 - ink[..., None])
    img = Image.fromarray(shown.clip(0, 255).astype(np.uint8))
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    img.save(path, quality=90)


def write_report(path, meta, cfg, n_regions, seconds, colours=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"areas": n_regions, "seconds": round(seconds, 1), "size": meta["size"], "dpi": meta["dpi"],
                   "hint_layers": meta.get("hint_layers"), "colours": colours,
                   "panels": {k: [int(v) for v in b] for k, b in meta["panels"].items()},
                   "line_layers_used": meta["used_layers"],
                   "settings": {k: v for k, v in cfg.items() if not k.startswith("_")}}, f, indent=2)
