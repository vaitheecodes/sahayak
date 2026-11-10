#!/usr/bin/env python3
"""Draws the app icon, Android adaptive layers, splash mark and favicon
into assets/. Plain shapes only (no fonts, no stock art): a speech bubble
with a check mark, i.e. "ask, and it gets solved". Needs Pillow.

    python3 scripts/make-icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

TEAL = (23, 104, 123, 255)  # palettes.light.primary (#17687b)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)
SS = 4  # supersampling for smooth edges

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def mark(draw: ImageDraw.ImageDraw, size: int, scale: float, bubble, check) -> None:
    """The bubble and check, centred, `scale` of `size` wide."""
    w = size * scale
    h = w * 0.74
    x0 = (size - w) / 2
    y0 = (size - h) / 2 - w * 0.06
    r = w * 0.22
    draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=r, fill=bubble)
    # The tail, bottom left, pointing down.
    tx = x0 + w * 0.24
    draw.polygon([(tx, y0 + h - 1), (tx + w * 0.22, y0 + h - 1), (tx - w * 0.02, y0 + h + w * 0.18)], fill=bubble)
    # The check, drawn as a thick polyline with round joints.
    cx, cy = x0 + w / 2, y0 + h / 2
    pts = [(cx - w * 0.2, cy + w * 0.01), (cx - w * 0.06, cy + w * 0.14), (cx + w * 0.21, cy - w * 0.13)]
    stroke = w * 0.085
    draw.line(pts, fill=check, width=round(stroke), joint="curve")
    for px, py in (pts[0], pts[-1]):
        draw.ellipse([px - stroke / 2, py - stroke / 2, px + stroke / 2, py + stroke / 2], fill=check)


def render(size: int, background, scale: float, bubble, check, tile_radius: float | None = None) -> Image.Image:
    big = size * SS
    im = Image.new("RGBA", (big, big), CLEAR)
    d = ImageDraw.Draw(im)
    if background is not None:
        if tile_radius is None:
            d.rectangle([0, 0, big, big], fill=background)
        else:
            d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * tile_radius, fill=background)
    mark(d, big, scale, bubble, check)
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    # iOS / store icon: full-bleed square (the OS rounds the corners), no alpha.
    render(1024, TEAL, 0.58, WHITE, TEAL).convert("RGB").save(ASSETS / "icon.png")
    # Android adaptive icon: the mark inside the 66% safe circle.
    render(1024, None, 0.44, WHITE, TEAL).save(ASSETS / "android-icon-foreground.png")
    Image.new("RGBA", (1024, 1024), TEAL).save(ASSETS / "android-icon-background.png")
    # Themed (monochrome) icon: the OS tints it, so the check is cut out.
    render(1024, None, 0.44, WHITE, CLEAR).save(ASSETS / "android-icon-monochrome.png")
    # Splash: a rounded teal tile on the splash background colour.
    render(1024, TEAL, 0.58, WHITE, TEAL, tile_radius=0.22).save(ASSETS / "splash-icon.png")
    render(48, TEAL, 0.62, WHITE, TEAL, tile_radius=0.22).save(ASSETS / "favicon.png")
    print("Wrote icons to", ASSETS)


if __name__ == "__main__":
    main()
