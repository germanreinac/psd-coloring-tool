"""Build a small stand-in page with the same layer layout as a Megalith page, to test the tool:
layout (panel borders), panel folders 1 and 2 with line art (with gaps) and a color folder."""
import sys

import cv2
import numpy as np
from PIL import Image
from psd_tools import PSDImage

from megalith_flats.export import add_rgba_layer

W, H = 1600, 2000


def lines_layer(draw):
    a = np.zeros((H, W), np.uint8)
    draw(a)
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = a
    return Image.fromarray(rgba, "RGBA")


def border(a):
    cv2.rectangle(a, (80, 80), (1520, 950), 255, 10)
    cv2.rectangle(a, (80, 1050), (1520, 1920), 255, 10)


def panel1(a):  # a character-like figure and a horizon, with gaps in the strokes
    cv2.line(a, (85, 650), (700, 650), 255, 6)           # ground, stops short of the figure
    cv2.line(a, (1010, 650), (1515, 650), 255, 6)
    cv2.ellipse(a, (850, 400), (150, 150), 0, 20, 370, 255, 6)   # head with a gap
    cv2.circle(a, (800, 380), 22, 255, 5)                 # eyes
    cv2.circle(a, (900, 380), 22, 255, 5)
    cv2.rectangle(a, (720, 560), (980, 940), 255, 6)      # body
    cv2.line(a, (720, 700), (930, 700), 255, 6)           # belt, 50 px short of the body edge
    cv2.circle(a, (1300, 250), 90, 255, 6)                # sun


def panel2(a):  # buildings
    cv2.line(a, (85, 1700), (1515, 1700), 255, 6)
    cv2.rectangle(a, (200, 1300), (600, 1700), 255, 6)
    cv2.rectangle(a, (300, 1400), (400, 1500), 255, 5)
    cv2.rectangle(a, (700, 1200), (1100, 1700), 255, 6)
    cv2.line(a, (700, 1200), (900, 1100), 255, 6)
    cv2.line(a, (910, 1100), (1100, 1200), 255, 6)        # roof with a small gap at the top


def main(path):
    psd = PSDImage.new("RGB", (W, H), depth=8)
    add_rgba_layer(psd, Image.new("RGBA", (W, H), (255, 255, 255, 255)), "Paper")
    boxes = {"1": (80, 80, 1520, 950), "2": (80, 1050, 1520, 1920)}
    for name, draw in (("2", panel2), ("1", panel1)):
        g = psd.create_group(name=name)
        if name == "1":  # panel 2 has no color folder, so the tool has to make one
            c = g.create_group(name="color")
            add_rgba_layer(c, Image.new("RGBA", (40, 40), (200, 80, 80, 255)), "old paint", left=100, top=100)
        add_rgba_layer(g, lines_layer(draw), "lines")
        x0, y0, x1, y1 = boxes[name]  # panel folders are masked to the panel, like the real pages
        m = np.zeros((H, W), np.uint8)
        m[y0:y1, x0:x1] = 255
        # a new folder's two records share one channel list in psd-tools; split them or the mask corrupts the file
        g._channels = type(g._channels)(list(g._channels))
        g.create_mask(Image.fromarray(m, "L"), top=0, left=0)
    lay = psd.create_group(name="layout")
    add_rgba_layer(lay, lines_layer(border), "borders")
    psd.save(path)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1])
