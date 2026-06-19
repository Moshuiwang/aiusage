from __future__ import annotations

import math
from pathlib import Path
from shutil import copyfile

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = (
    ROOT
    / "mobile"
    / "ios-xcode"
    / "Resources"
    / "Assets.xcassets"
    / "AppIcon.appiconset"
)
SOURCE = Path(__file__).with_name("ai-usage-icon.svg")

SIZES = {
    "AppIcon-20@2x.png": 40,
    "AppIcon-20@3x.png": 60,
    "AppIcon-29@2x.png": 58,
    "AppIcon-29@3x.png": 87,
    "AppIcon-40@2x.png": 80,
    "AppIcon-40@3x.png": 120,
    "AppIcon-60@2x.png": 120,
    "AppIcon-60@3x.png": 180,
    "AppIcon-1024.png": 1024,
}


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _draw_arc(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], start: int, end: int, width: int, fill: tuple[int, int, int, int]) -> None:
    draw.arc(box, start=start, end=end, fill=fill, width=width)
    radius = (box[2] - box[0]) / 2
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    cap = width / 2
    for angle in (start, end):
        point = (
            center[0] + radius * math.cos(math.radians(angle)),
            center[1] + radius * math.sin(math.radians(angle)),
        )
        draw.ellipse(
            (point[0] - cap, point[1] - cap, point[0] + cap, point[1] + cap),
            fill=fill,
        )


def make_icon(size: int) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (7, 9, 16, 255))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            dx = (x / size - 0.34) / 0.82
            dy = (y / size - 0.27) / 0.82
            t = min((dx * dx + dy * dy) ** 0.5, 1.0)
            if t < 0.46:
                k = t / 0.46
                rgb = (
                    _lerp(45, 20, k),
                    _lerp(49, 24, k),
                    _lerp(72, 39, k),
                )
            else:
                k = (t - 0.46) / 0.54
                rgb = (
                    _lerp(20, 7, k),
                    _lerp(24, 9, k),
                    _lerp(39, 16, k),
                )
            pixels[x, y] = (*rgb, 255)

    draw = ImageDraw.Draw(image, "RGBA")
    outer_width = max(4, round(92 * scale))
    inner_width = max(4, round(78 * scale))
    outer_r = 350 * scale
    inner_r = 184 * scale
    cx = cy = size / 2
    outer_box = tuple(round(v) for v in (cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r))
    inner_box = tuple(round(v) for v in (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r))

    draw.ellipse(outer_box, outline=(255, 255, 255, 26), width=outer_width)
    _draw_arc(draw, outer_box, -96, 157, outer_width, (218, 119, 86, 255))
    draw.ellipse(inner_box, outline=(255, 255, 255, 28), width=inner_width)
    _draw_arc(draw, inner_box, -90, 124, inner_width, (10, 132, 255, 255))

    pulse = 56 * scale
    dot = 18 * scale
    draw.ellipse((cx - pulse, cy - pulse, cx + pulse, cy + pulse), fill=(255, 255, 255, 214))
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(10, 132, 255, 255))
    return image


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    copyfile(SOURCE, ICON_DIR / "AIUsageIconSource.svg")
    for name, size in SIZES.items():
        make_icon(size).save(ICON_DIR / name)


if __name__ == "__main__":
    main()
