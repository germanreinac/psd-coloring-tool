"""Write the colour key as a Photoshop swatch file: python -m megalith_flats.swatches
Load it in Photoshop: Swatches panel > menu > Import Swatches... > 'Megalith key.aco'."""
import os
import struct

from .hints import key_colours
from .palette import load

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_aco(names, cols, path):
    def entry(c):
        r, g, b = (int(v) * 257 for v in c)
        return struct.pack(">5H", 0, r, g, b, 0)

    data = struct.pack(">2H", 1, len(cols)) + b"".join(entry(c) for c in cols)
    data += struct.pack(">2H", 2, len(cols))
    for name, c in zip(names, cols):
        data += entry(c) + struct.pack(">I", len(name) + 1) + name.encode("utf-16-be") + b"\0\0"
    with open(path, "wb") as f:
        f.write(data)


def main():
    names, cols = key_colours(load(os.path.join(HERE, "palette.json")))
    path = os.path.join(HERE, "Megalith key.aco")
    write_aco(names, cols, path)
    print(f"{len(names)} swatches -> {path}")


if __name__ == "__main__":
    main()
