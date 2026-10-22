"""Generate the Mtrini Workspace logo and every icon asset.

Design: a pixel-art camel with a teal and saffron saddle blanket and a little
saffron star, on a deep-ink rounded tile with a soft teal glow. Original artwork.
Requires: pillow
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PUBLIC = ROOT / "frontend" / "public"

# 20x20 grid. "." empty, S sand, D shade, E eye, T teal, Y saffron, W highlight.
GRID = [
    "....................",
    "....................",
    "....Y...............",
    "...YYY..............",
    "....Y...........SS..",
    "..............SSSSS.",
    "..............SESSSS",
    "........SS....SSSSD.",
    ".......SWSS..SS.....",
    "......SSSSSS.SS.....",
    ".....SSSSSSSSSS.....",
    "....SSTYTYTYSSS.....",
    "...DSSYTYTYTSSS.....",
    "....SSSSSSSSSSD.....",
    ".....DSSDDDDSSD.....",
    ".....SS....SS.......",
    ".....SS....SS.......",
    ".....DD....DD.......",
    "....DDD...DDD.......",
    "....................",
]
COLORS = {"S": "#ecc890", "D": "#c4914f", "E": "#141a20", "T": "#22a6bf", "Y": "#e0a33a", "W": "#fbe6c2"}

CELL = 36
OX = (1024 - 20 * CELL) / 2 - 8
OY = (1024 - 20 * CELL) / 2 + 4
TILE = (64, 64, 960, 960)
RADIUS = 216
INK_A, INK_B = (0x16, 0x30, 0x3A), (0x0A, 0x12, 0x18)
GLOW = (0x5A, 0xD1, 0xE6)


def rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def svg() -> str:
    rects = "".join(
        f'<rect x="{OX + x * CELL:g}" y="{OY + y * CELL:g}" width="{CELL + 0.5:g}" height="{CELL + 0.5:g}" fill="{COLORS[ch]}"/>'
        for y, row in enumerate(GRID) for x, ch in enumerate(row) if ch in COLORS
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" shape-rendering="crispEdges">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#16303a"/>
      <stop offset="1" stop-color="#0a1218"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.3" cy="0.25" r="0.85">
      <stop offset="0" stop-color="#5ad1e6" stop-opacity="0.26"/>
      <stop offset="1" stop-color="#5ad1e6" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x="64" y="64" width="896" height="896" rx="216" fill="url(#tile)"/>
  <rect x="64" y="64" width="896" height="896" rx="216" fill="url(#glow)"/>
  <rect x="{OX + 2 * CELL:g}" y="{OY + 19 * CELL - 6:g}" width="{16 * CELL}" height="10" rx="5" fill="#5ad1e6" opacity="0.25"/>
  <rect x="65.5" y="65.5" width="893" height="893" rx="214.5" fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="3"/>
  <g>{rects}</g>
</svg>
"""


def draw() -> Image.Image:
    """Draw the 1024 px icon."""
    size = 1024
    x0, y0, x1, y1 = TILE
    w = x1 - x0
    # Diagonal ink gradient: average of a vertical and a horizontal ramp.
    ramp = Image.linear_gradient("L").resize((w, w))
    diag = ImageChops.add(ramp, ramp.rotate(90).transpose(Image.Transpose.FLIP_LEFT_RIGHT), scale=2.0)
    tile = Image.composite(Image.new("RGB", (w, w), INK_B), Image.new("RGB", (w, w), INK_A), diag)
    # Soft teal glow toward the top left.
    r = int(0.85 * w)
    glow_mask = ImageChops.invert(Image.radial_gradient("L").resize((2 * r, 2 * r))).point(lambda v: int(v * 0.26))
    glow = Image.new("L", (w, w), 0)
    glow.paste(glow_mask, (int(0.3 * w) - r, int(0.25 * w) - r))
    tile = Image.composite(Image.new("RGB", (w, w), GLOW), tile, glow)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(TILE, radius=RADIUS, fill=255)
    full = Image.new("RGB", (size, size))
    full.paste(tile, (x0, y0))
    img.paste(full, (0, 0), mask)

    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5], radius=RADIUS - 1.5, outline=(255, 255, 255, 20), width=3)
    sy = OY + 19 * CELL - 6
    d.rounded_rectangle([OX + 2 * CELL, sy, OX + 18 * CELL, sy + 10], radius=5, fill=GLOW + (40,))
    for y, row in enumerate(GRID):
        for x, ch in enumerate(row):
            if ch in COLORS:
                left, top = OX + x * CELL, OY + y * CELL
                d.rectangle([left, top, left + CELL, top + CELL], fill=rgb(COLORS[ch]) + (255,))
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    text = svg()
    for target in (ASSETS / "logo.svg", PUBLIC / "logo.svg"):
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    big = draw()
    big.save(ASSETS / "logo-1024.png")
    for n in (256, 48, 32, 16):
        big.resize((n, n), Image.LANCZOS).save(ASSETS / f"logo-{n}.png")
    big.resize((256, 256), Image.LANCZOS).save(PUBLIC / "logo.png")
    big.save(ASSETS / "logo.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("logo assets written to", ASSETS, "and", PUBLIC)


if __name__ == "__main__":
    main()
