"""Draw the Mtrini Bots icon: the camel mascot on a dark rounded tile.

Writes assets/bots.ico (for the exe and installer) and frontend/public/bots.png (for the window).
Run from the repo root: python scripts/make-bots-icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CAMEL = [  # the same sprite as frontend/src/bots/mascots.ts
    "........XX..",
    ".......XXXX.",
    ".......X.XXo",
    ".......XXXXo",
    "...XX..XXX..",
    "..XXXX.XXX..",
    ".XXXXXXXXX..",
    "XXXXXXXXXX..",
    "XXXXXXXXXX..",
    "xXXXXXXXXX..",
    ".XX....XX...",
    ".xx....xx...",
]
FILL = {"X": "#5ad1e6", "x": "#38828f", "o": "#f5efe2"}
TILE = "#17191d"


def icon(size: int) -> Image.Image:
    scale = 4  # draw big, shrink once: clean rounded corners, crisp pixels
    big = size * scale
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.22), fill=TILE)
    cell = big // 16  # 12 cells of sprite, 2 of margin each side
    off = (big - cell * 12) // 2
    for y, row in enumerate(CAMEL):
        for x, ch in enumerate(row):
            if ch in FILL:
                d.rectangle([off + x * cell, off + y * cell, off + (x + 1) * cell - 1, off + (y + 1) * cell - 1], fill=FILL[ch])
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    (ROOT / "assets").mkdir(exist_ok=True)
    icon(256).save(ROOT / "assets" / "bots.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon(256).save(ROOT / "frontend" / "public" / "bots.png")
    print("wrote assets/bots.ico and frontend/public/bots.png")
