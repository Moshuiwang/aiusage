from __future__ import annotations

import ctypes
import ctypes.util
import subprocess
from pathlib import Path


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

# On macOS with Homebrew, cairocffi cannot auto-detect libcairo.
# Pre-load it so dlopen succeeds.
_HOMEBREW_CAIRO = "/opt/homebrew/lib/libcairo.2.dylib"
_orig_find_library = ctypes.util.find_library


def _patched_find_library(name: str) -> str | None:
    if name in ("cairo", "cairo-2", "libcairo-2"):
        import os
        if os.path.exists(_HOMEBREW_CAIRO):
            return _HOMEBREW_CAIRO
    return _orig_find_library(name)


ctypes.util.find_library = _patched_find_library

import cairosvg  # noqa: E402  (must come after the patch)


def render_png(size: int) -> bytes:
    svg_data = SOURCE.read_bytes()
    return cairosvg.svg2png(
        bytestring=svg_data,
        output_width=size,
        output_height=size,
    )


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        (ICON_DIR / name).write_bytes(render_png(size))
        print(f"  {name} ({size}px)")

    MAC_ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in MAC_SIZES.items():
        (MAC_ICONSET_DIR / name).write_bytes(render_png(size))
        print(f"  {name} ({size}px)")

    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(MAC_ICONSET_DIR), "-o", str(MAC_ICNS)],
            check=True,
        )
        print(f"  AIUsageMenuBar.icns")
    except Exception as exc:
        print(f"  iconutil failed ({exc}), skipping .icns")


if __name__ == "__main__":
    main()
