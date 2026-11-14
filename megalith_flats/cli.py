"""Command line: python -m megalith_flats.cli "<page.psd>"

Give it a page from `whole project` (or its copy in `output`). The first time, the page is copied to
output/<page name>/<page name>.psd. From then on that one copy is edited in place: Flats go into
each panel's color folder, and any hints you scribbled in its 'Flat hints' layer are used.
The page in `whole project` is only ever read.
"""
import argparse
import json
import os
import shutil
import time

import numpy as np

from . import export, extract, hints, palette, panels, regions

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTECTED = "whole project"


def _inside(path, folder_name):
    parts = [p.lower() for p in os.path.normpath(os.path.abspath(path)).split(os.sep)]
    return folder_name.lower() in parts


def main():
    ap = argparse.ArgumentParser(description="Add flats to a copy of a Megalith page.")
    ap.add_argument("page", help="the page PSD in 'whole project', or its copy in 'output'")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--output", default=os.path.join(HERE, "output"), help="where page copies live")
    ap.add_argument("--fresh", action="store_true",
                    help="throw away the existing copy (and its hints) and copy the page again")
    ap.add_argument("--map", help="colour plan file (default: maps/<page name>.json)")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    t0 = time.time()

    name = os.path.splitext(os.path.basename(args.page))[0]
    if _inside(args.page, PROTECTED):
        folder = os.path.join(args.output, name)
        work = os.path.join(folder, os.path.basename(args.page))
        os.makedirs(folder, exist_ok=True)
        if args.fresh or not os.path.exists(work):
            print(f"Copying the page into {folder} (the original is not changed)")
            shutil.copy2(args.page, work)
        else:
            print(f"Using the existing copy {work}")
    else:
        work, folder = args.page, os.path.dirname(os.path.abspath(args.page))
    if _inside(work, PROTECTED):
        raise SystemExit(f"Refusing to edit a file inside '{PROTECTED}': {work}")
    check = os.path.join(folder, "check")
    os.makedirs(check, exist_ok=True)

    print(f"Reading {work}")
    ink, meta = extract.ink_from_psd(work, cfg)

    key = palette.load(os.path.join(HERE, "palette.json"))
    plan, cuts = None, None
    plan_path = args.map or os.path.join(HERE, "maps", f"{name}.json")
    if os.path.exists(plan_path):
        print(f"Using the colour plan {os.path.basename(plan_path)}")
        page_map = palette.load(plan_path)
        plan = hints.read_plan(page_map, key, meta["size"])
        cuts = page_map.get("_cuts")

    print("Finding areas")
    labels, line = regions.find_regions(ink, cfg, cuts)
    n = int(labels.max())

    print("Working out each panel's area")
    masks = panels.panel_masks(meta, cfg, labels)

    print("Choosing colours")
    rgb, alpha, summary = hints.colour_flats(labels, line, meta["hints"], key, cfg, plan)

    print("Adding Flats to each panel's color folder (saving takes a few minutes)")
    flats = panels.panel_flat_images(rgb, alpha, masks)
    panels.write_into_psd(work, meta["panel_paths"], flats, cfg, hint_seed=None)
    in_panels = np.zeros_like(alpha)
    for m in masks.values():
        in_panels |= m
    export.write_preview(ink, rgb, alpha & in_panels, os.path.join(check, "preview.jpg"))
    export.write_report(os.path.join(check, "report.json"), meta, cfg, n, time.time() - t0, summary)
    print(f"Done in {time.time() - t0:.0f}s: {work}")


if __name__ == "__main__":
    main()
