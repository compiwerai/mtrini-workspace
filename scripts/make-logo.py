"""Generate the Mtrini Workspace logo (original design) + all icon assets.

Design: deep-navy rounded tile, light monogram 'M' whose middle vertex is a
diamond (the brand mark), flat and professional. No third-party artwork.
Requires: pillow
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PUBLIC = ROOT / "frontend" / "public"

NAVY_TOP = (27, 34, 48)
NAVY_BOT = (14, 17, 22)
LIGHT = (219, 226, 238)
ACCENT = (79, 140, 255)
GREEN = (52, 201, 142)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1b2230"/>
      <stop offset="1" stop-color="#0e1116"/>
    </linearGradient>
  </defs>
  <rect x="112" y="112" width="800" height="800" rx="180" fill="url(#bg)"/>
  <polyline points="250,700 250,340 512,560 774,340 774,700" fill="none"
            stroke="#dbe2ee" stroke-width="96" stroke-linecap="round" stroke-linejoin="round"/>
  <polygon points="512,470 602,560 512,650 422,560" fill="#4f8cff"/>
  <polygon points="512,515 557,560 512,605 467,560" fill="#0e1116"/>
  <polygon points="512,535 537,560 512,585 487,560" fill="#34c98e"/>
</svg>
"""


def draw(size: int) -> Image.Image:
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # vertical gradient tile via mask
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOT)))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([112 * s, 112 * s, 912 * s, 912 * s], radius=180 * s, fill=255)
    img.paste(Image.new("RGBA", (size, size), (0, 0, 0, 0)), (0, 0))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(Image.merge("RGBA", (*grad.split(), Image.new("L", (size, size), 255))), (0, 0), mask)
    img = Image.alpha_composite(img, tile)
    d = ImageDraw.Draw(img)

    def X(x: float) -> float:
        return x * s

    pts = [(250, 700), (250, 340), (512, 560), (774, 340), (774, 700)]
    d.line([(X(x), X(y)) for x, y in pts], fill=LIGHT + (255,), width=int(96 * s), joint="curve")
    cx, cy = X(512), X(560)
    r1, r2, r3 = 90 * s, 45 * s, 25 * s
    d.polygon([(cx, cy - r1), (cx + r1, cy), (cx, cy + r1), (cx - r1, cy)], fill=ACCENT + (255,))
    d.polygon([(cx, cy - r2), (cx + r2, cy), (cx, cy + r2), (cx - r2, cy)], fill=NAVY_BOT + (255,))
    d.polygon([(cx, cy - r3), (cx + r3, cy), (cx, cy + r3), (cx - r3, cy)], fill=GREEN + (255,))
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (ASSETS / "logo.svg").write_text(SVG, encoding="utf-8")
    big = draw(1024)
    big.save(ASSETS / "logo-1024.png")
    for n in (256, 48, 32, 16):
        draw(256 if n > 64 else 64).resize((n, n), Image.LANCZOS).save(ASSETS / f"logo-{n}.png")
    big.save(ASSETS / "logo.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    (PUBLIC / "logo.svg").write_text(SVG, encoding="utf-8")
    draw(256).save(PUBLIC / "logo.png")
    print("logo assets written to", ASSETS, "and", PUBLIC)


if __name__ == "__main__":
    main()
