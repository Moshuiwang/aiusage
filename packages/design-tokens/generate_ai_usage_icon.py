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
MAC_RESOURCES_DIR = ROOT / "clients" / "macos" / "Resources"
MAC_ICONSET_DIR = MAC_RESOURCES_DIR / "AIUsageMenuBar.iconset"
MAC_ICNS = MAC_RESOURCES_DIR / "AIUsageMenuBar.icns"

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

MAC_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
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
    scale = size / 100
    image = Image.new("RGBA", (size, size), (12, 13, 24, 255))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            dx = (x / size - 0.35) / 0.88
            dy = (y / size - 0.30) / 0.75
            t = min((dx * dx + dy * dy) ** 0.5, 1.0)
            rgb = (
                _lerp(30, 12, t),
                _lerp(32, 13, t),
                _lerp(53, 24, t),
            )
            pixels[x, y] = (*rgb, 255)

    draw = ImageDraw.Draw(image, "RGBA")
    outer_width = max(2, round(11 * scale))
    inner_width = max(2, round(9 * scale))
    outer_r = 38 * scale
    inner_r = 20 * scale
    cx = cy = size / 2
    outer_box = tuple(round(v) for v in (cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r))
    inner_box = tuple(round(v) for v in (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r))

    draw.ellipse(outer_box, outline=(218, 119, 86, 46), width=outer_width)
    _draw_arc(draw, outer_box, -90, 162, outer_width, (218, 119, 86, 255))
    draw.ellipse(inner_box, outline=(10, 132, 255, 46), width=inner_width)
    _draw_arc(draw, inner_box, -90, 72, inner_width, (10, 132, 255, 255))

    dot = 3.5 * scale
    draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(255, 255, 255, 166))
    return image


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    copyfile(SOURCE, ICON_DIR / "AIUsageIconSource.svg")
    for name, size in SIZES.items():
        make_icon(size).save(ICON_DIR / name)
    MAC_ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in MAC_SIZES.items():
        make_icon(size).save(MAC_ICONSET_DIR / name)
    try:
        import subprocess

        subprocess.run(
            ["iconutil", "-c", "icns", str(MAC_ICONSET_DIR), "-o", str(MAC_ICNS)],
            check=True,
        )
    except Exception:
        make_icon(1024).save(MAC_ICNS, format="PNG")


if __name__ == "__main__":
    main()
