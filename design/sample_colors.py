"""Extract the Pewbeam palette from the reference screenshots.

For each image: report size, the most common RGB values (the UI palette),
and a few targeted point samples given as fractions of width/height.
"""
import os
import sys
from collections import Counter

from PIL import Image

SHOTS = r"C:\Users\DELL\Pictures\Screenshots"

FILES = [
    ("01_theme_designer_blue", "Screenshot 2026-10-22 170150.png"),
    ("02_layout_panel", "Screenshot 2026-10-22 170208.png"),
    ("03_scripture_panel", "Screenshot 2026-10-22 170215.png"),
    ("04_effects_dropshadow", "Screenshot 2026-10-22 170220.png"),
    ("05_outline_panel", "Screenshot 2026-10-22 170225.png"),
    ("06_theme_designer_orange", "Screenshot 2026-10-22 170246.png"),
    ("07_content_studio", "Screenshot 2026-10-22 170300.png"),
    ("08_settings", "Screenshot 2026-10-22 170319.png"),
]

# (label, fx, fy) as fractions of the image size
POINTS = {
    "01_theme_designer_blue": [
        ("sidebar_bg", 0.14, 0.42),
        ("canvas_bg", 0.29, 0.42),
        ("inspector_bg", 0.86, 0.72),
        ("save_btn", 0.855, 0.111),
        ("close_btn", 0.945, 0.111),
        ("toolbar_pill", 0.50, 0.278),
        ("new_btn", 0.052, 0.228),
        ("card_blue", 0.135, 0.50),
        ("card_blue_2", 0.135, 0.62),
        ("card_caption", 0.135, 0.773),
        ("card_green", 0.135, 0.86),
        ("input_bg", 0.625, 0.55),
        ("toggle", 0.755, 0.858),
        ("title_text", 0.056, 0.104),
        ("label_text", 0.762, 0.325),
    ],
    "02_layout_panel": [
        ("panel_bg", 0.75, 0.60),
        ("seg_selected", 0.438, 0.430),
        ("seg_idle", 0.300, 0.430),
        ("input_bg", 0.40, 0.545),
        ("save_btn", 0.50, 0.10),
        ("close_btn", 0.79, 0.10),
        ("divider", 0.5, 0.262),
    ],
    "03_scripture_panel": [
        ("panel_bg", 0.75, 0.75),
        ("dropdown_bg", 0.45, 0.415),
        ("color_swatch", 0.185, 0.785),
        ("seg_selected", 0.297, 0.925),
        ("save_btn", 0.50, 0.082),
        ("label_text", 0.165, 0.358),
        ("value_text", 0.75, 0.782),
    ],
    "04_effects_dropshadow": [
        ("panel_bg", 0.80, 0.80),
        ("slider_track", 0.60, 0.672),
        ("slider_fill", 0.60, 0.675),
        ("swatch", 0.288, 0.825),
        ("save_btn", 0.50, 0.082),
    ],
    "05_outline_panel": [
        ("panel_bg", 0.80, 0.80),
        ("dropdown_bg", 0.40, 0.545),
        ("swatch", 0.243, 0.784),
        ("save_btn", 0.48, 0.082),
    ],
    "06_theme_designer_orange": [
        ("sidebar_bg", 0.14, 0.42),
        ("canvas_bg", 0.29, 0.42),
        ("inspector_bg", 0.86, 0.72),
        ("save_btn", 0.855, 0.111),
        ("card_orange_top", 0.135, 0.53),
        ("card_orange_bottom", 0.135, 0.63),
        ("swatch", 0.790, 0.328),
    ],
    "07_content_studio": [
        ("sidebar_bg", 0.25, 0.55),
        ("canvas_bg", 0.72, 0.50),
        ("card_bg", 0.070, 0.46),
        ("publish_btn", 0.328, 0.700),
        ("tab_underline", 0.064, 0.752),
        ("close_btn", 0.949, 0.108),
        ("search_bg", 0.30, 0.813),
    ],
    "08_settings": [
        ("modal_bg", 0.42, 0.30),
        ("sidebar_bg", 0.10, 0.45),
        ("accent_icon", 0.069, 0.227),
        ("accent_text", 0.108, 0.227),
        ("seg_selected", 0.855, 0.196),
        ("seg_idle", 0.918, 0.196),
        ("toggle_on", 0.939, 0.502),
        ("upgrade_pill", 0.256, 0.817),
        ("divider", 0.70, 0.246),
        ("backdrop", 0.02, 0.20),
    ],
}


def hexs(rgb):
    return "#%02x%02x%02x" % rgb[:3]


def main():
    for key, fname in FILES:
        path = os.path.join(SHOTS, fname)
        if not os.path.exists(path):
            print(f"{key}: MISSING {path}")
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        print(f"\n=== {key}  ({w}x{h})  {fname}")

        small = im.resize((w // 4, h // 4), Image.NEAREST)
        counts = Counter(small.getdata())
        top = counts.most_common(14)
        total = sum(counts.values())
        print("  dominant:", ", ".join(f"{hexs(c)} {100*n/total:.1f}%" for c, n in top[:10]))

        for label, fx, fy in POINTS.get(key, []):
            x, y = min(int(fx * w), w - 1), min(int(fy * h), h - 1)
            print(f"  {label:16s} ({x:4d},{y:4d}) -> {hexs(im.getpixel((x, y)))}")


if __name__ == "__main__":
    sys.exit(main())
