"""Draw the Utter logo (assets/utter.ico, assets/utter.png). Run: python assets/make_icon.py

The sidebar logo in utter/web/index.html is the same drawing as inline SVG.

Teal rounded square; two short white bars flank a 'u' made of two longer
bars joined at the bottom, so the mark reads as both a sound wave and a u.
Coordinates are on a 64-unit grid, rendered at 1024 px and downsampled.
"""
from pathlib import Path

from PIL import Image, ImageDraw

TEAL = (31, 95, 87, 255)
WHITE = (255, 255, 255, 255)
SCALE = 16          # 64-unit grid -> 1024 px
STROKE = 5.5        # bar width in grid units


def _bar(draw, x, y1, y2):
    """Vertical bar with round caps."""
    r = STROKE / 2
    draw.rounded_rectangle([(x - r) * SCALE, (y1 - r) * SCALE, (x + r) * SCALE, (y2 + r) * SCALE],
                           radius=r * SCALE, fill=WHITE)


def draw_logo(size=1024):
    image = Image.new('RGBA', (64 * SCALE, 64 * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, 64 * SCALE - 1, 64 * SCALE - 1], radius=15 * SCALE, fill=TEAL)

    _bar(draw, 13.5, 27, 37)            # outer left
    _bar(draw, 50.5, 27, 37)            # outer right
    # the 'u': two arms joined by a half circle
    left, right, top, bottom = 24, 40, 19, 35
    _bar(draw, left, top, bottom)
    _bar(draw, right, top, bottom)
    radius = (right - left) / 2
    cx, cy = (left + right) / 2, bottom
    half = STROKE / 2
    draw.arc([(cx - radius - half) * SCALE, (cy - radius - half) * SCALE,
              (cx + radius + half) * SCALE, (cy + radius + half) * SCALE],
             start=0, end=180, fill=WHITE, width=int(STROKE * SCALE))
    return image.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    here = Path(__file__).parent
    logo = draw_logo()
    logo.resize((256, 256), Image.LANCZOS).save(here / 'utter.png')
    logo.save(here / 'utter.ico', sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('wrote utter.ico and utter.png')
