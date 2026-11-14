# Smart Flat Fill — Photoshop plugin

Flats line art even when the lines have small gaps. A normal Paint Bucket leaks through gaps; this plugin closes them first.

Requires **Photoshop 2023 (v24.2) or newer**, RGB, 8 bits/channel.

## Install

**Option A: double-click** `SmartFlatFill.ccx`. Creative Cloud installs it (it may warn that the plugin is not from the Marketplace). Restart Photoshop.

**Option B: UXP Developer Tool** (free in the Creative Cloud app, under "All apps"):
1. Open UXP Developer Tool → **Add Plugin** → pick `manifest.json` in this folder.
2. Click **Load** (••• → Load) with Photoshop open.

Open the panel from **Plugins → Smart Flat Fill**.

## Use

1. Select your line art layer (or click **Use active layer as line art** once so it stays set).
2. Set **Close gaps up to** a bit larger than the biggest gap in your lines.

**Flat everything** — every closed area gets its own random colour on a new `Flats` layer under the line art. Then use the Magic Wand (Contiguous **off**, Anti-alias **off**) on the Flats layer to grab an area and recolour it.

**Fill marked areas** — fills only the areas you mark, with the foreground colour:
- Click inside areas with the **Color Sampler tool** (Shift+I, up to 10 points), or
- make a rough selection (lasso, brush in Quick Mask) touching the areas.

**Select marked areas** — same marking, but makes a selection instead of filling.

Every action is a single undo step.

## Settings

| Setting | What it does |
|---|---|
| Close gaps up to | Gaps narrower than this are treated as closed. Too high also splits narrow necks of shapes (e.g. thin fingers) — lower it if that happens. |
| Line threshold | How dark/opaque a pixel must be to count as line. Lower it for light pencil lines. |
| Ignore regions smaller than | Tiny specks become part of the neighbouring area. |
| Extend fill under the lines | Flats go under the line art, so there is no white halo at antialiased edges. |
| Leave outside area empty | The area touching the canvas border stays transparent in "Flat everything". |

Works with line art on white paper or on a transparent layer. If the line art is the locked Background layer, the Flats layer is placed on top in Multiply mode.

## Files

- `fillcore.js` — the gap-closing algorithm (no Photoshop code; testable in a browser).
- `main.js`, `index.html`, `manifest.json` — the Photoshop panel.
- `test/test.html` — browser test page comparing gap-closing vs normal fill (open it directly, or serve the folder with `python -m http.server` and open `/test/test.html`).

## Packaging

`SmartFlatFill.ccx` is just a zip of `manifest.json`, `index.html`, `main.js` and `fillcore.js`:

```bash
cd plugin && zip -X SmartFlatFill.ccx manifest.json index.html main.js fillcore.js
```
