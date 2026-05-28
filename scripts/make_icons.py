#!/usr/bin/env python3
"""Render SVG sources into menu-bar template PNGs and the app .icns.
macOS-only (uses rsvg-convert + iconutil). Run: python scripts/make_icons.py"""
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def run(cmd):
    subprocess.run(cmd, check=True)


def svg_to_png(svg: Path, png: Path, *, height=None, width=None):
    cmd = ["rsvg-convert", str(svg), "-o", str(png)]
    if height:
        cmd += ["-h", str(height)]
    if width:
        cmd += ["-w", str(width)]
    run(cmd)


def main():
    # menu-bar template icons (alpha-only black glyphs, ~18pt @2x = 36px tall)
    for name in ("menubar_idle", "menubar_syncing", "menubar_error"):
        svg_to_png(ASSETS / f"{name}.svg", ASSETS / f"{name}.png", height=36)
        print("wrote", name + ".png")

    # app icon -> .iconset -> .icns
    iconset = ASSETS / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    sizes = [16, 32, 128, 256, 512]
    for s in sizes:
        svg_to_png(ASSETS / "appicon.svg", iconset / f"icon_{s}x{s}.png", width=s, height=s)
        svg_to_png(ASSETS / "appicon.svg", iconset / f"icon_{s}x{s}@2x.png",
                   width=s * 2, height=s * 2)
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "AppIcon.icns")])
    print("wrote AppIcon.icns")


if __name__ == "__main__":
    sys.exit(main())
