# Megalith flatting tool

Adds a **Flats** layer to each panel's `color` folder in a copy of a Megalith page, with every element inside the panels in its own flat colour from the Megalith palette, so the page is ready for painting. The tool never paints: it only makes flats.

Rebuilt from the `coloring tool` folder on Drive. The Photoshop panel experiment (Smart Flat Fill) is kept separately in [`plugin/`](plugin/).

## Set up

```bash
pip install -r requirements.txt
```

## Rule: originals are never touched
Anything inside a folder called `whole project` is read-only. The tool refuses to save there.

## One page = one folder = one PSD
```
output/
  Chapter 2_Scene5_page1/
    Chapter 2_Scene5_page1.psd   <- the copy (same name as the original); the tool edits this one
    check/preview.jpg            <- quick look at the flats
    check/report.json            <- what was done (for troubleshooting)
```
- The first run copies the page from `whole project`.
- Every later run reuses that same copy, so your hints are kept. The old Flats layers are replaced, never stacked.
- `--fresh` throws the copy away and copies the original again. This also loses your hints.

## Run it
```bash
python -m megalith_flats.cli "../whole project/0_Pages/Chapter 2/Scene 5/P 01/Chapter 2_Scene5_page1.psd"
```
- You can also pass the copy in `output` directly. Either way, the copy is what gets edited.
- A run takes about 10 minutes for a 250 MB page; saving the PSD is the slow part.

## How colours are chosen
Everything inside a panel gets a flat colour, backgrounds included. Only the area outside the panels stays empty. Every element gets its own colour, so the magic wand can pick it.

Colours come from three places. The first one that applies wins:
1. **Your Flat hints layer**, at the top of the copy.
   - Any layer with "hint" in its name works.
   - Scribble with key colours (import `Megalith key.aco` into the Swatches panel), then save and rerun.
   - Every area a scribble touches gets that colour.
   - Two colours in one area split it.
   - White means "leave empty".
2. **The page's colour plan**, `maps/<page name>.json`. This says what each object is.
   - `"candy pink | ice cream": [...]` with points `[x, y]`, strokes `[[x, y], ...]`, or outlines `{"area": [[x, y], ...]}`.
   - An outline gives a whole object one colour even when it has inner detail lines.
   - A point colours only the area right under it (e.g. the lenses of the sunglasses).
   - `"_cuts": [[[x, y], [x, y], ...], ...]` are invisible lines that close gaps the automatic bridges miss.
3. **Automatic colours** for everything else, from the named palette in `palette.json` (`scene`).
   - Big areas get soft tones and small parts get accents.
   - Touching areas never share a colour.
   - Thin strips and crumbs between lines join the neighbour they share the most edge with.

## Gaps in the line art
Where a stroke stops short of another line, the tool draws an invisible "bridge" to close the gap. Bridges are never added to your art. A bridge is only made in the direction the stroke is heading, and short marks (hair dashes, whiskers) never get bridges. If a gap still leaks, raise `gap_bridge_px`, or put two colours in the merged area (on the hint layer or in the plan).

## Panels
- Each panel folder (`1`, `2`, … at the top level, or inside `Panels`) gets **Flats** at the bottom of its `color` folder, holding only that panel's flats.
- If a panel has no `color` folder, a new one is made at the bottom of the panel.
- Panel shapes come from the `layout` border layer. An inset panel whose border is in its own line art is found from its own lines.

## Colours
- `palette.json` is the colour key: Dji and Skit, 35 named scene colours from Chapter 1, and the colour sets used for automatic colouring.
- After editing it, run `python -m megalith_flats.swatches` to rebuild `Megalith key.aco`.

## Settings (`config.json`)
Every setting has a plain explanation next to it. The ones you're most likely to touch are `gap_bridge_px` and `hint_snap`.

## Test without a real page
```bash
python -m tests.make_test_page /tmp/testpage.psd
python -m megalith_flats.cli /tmp/testpage.psd --map tests/testpage_plan.json
```
This builds a small stand-in page with the same layer layout (`layout`, panel folders, `color` folders) and flats it.
