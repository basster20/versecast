"""Pass 2: sample the live/main screen plus Settings sub-pages."""
import os
from collections import Counter

from PIL import Image

S = r"C:\Users\DELL\Pictures\Screenshots"

SHOTS = [
    ("09_settings_translations", "Screenshot 2026-10-22 170328.png"),
    ("10_settings_translations2", "Screenshot 2026-10-22 170336.png"),
    ("11_settings_audio", "Screenshot 2026-10-22 170350.png"),
    ("12_settings_audio2", "Screenshot 2026-10-22 170358.png"),
    ("13_settings_language", "Screenshot 2026-10-22 170413.png"),
    ("14_settings_help", "Screenshot 2026-10-22 170435.png"),
    ("15_main_live", "Screenshot 2026-10-22 170451.png"),
]

POINTS = {
    "09_settings_translations": [
        ("group_card", 0.60, 0.16),
        ("modal_bg", 0.60, 0.09),
        ("check_icon", 0.930, 0.317),
        ("row_text", 0.360, 0.317),
        ("accent_nav", 0.060, 0.227),
    ],
    "11_settings_audio": [
        ("seg_active", 0.836, 0.200),
        ("seg_trough", 0.940, 0.200),
        ("dropdown_bg", 0.83, 0.375),
        ("secondary_btn", 0.920, 0.528),
        ("slider_track", 0.70, 0.866),
        ("warn_banner", 0.85, 0.985),
    ],
    "12_settings_audio2": [
        ("meter_bar", 0.890, 0.186),
        ("toggle_off", 0.945, 0.335),
        ("toggle_on", 0.940, 0.503),
        ("chip_bg", 0.400, 0.727),
        ("add_disabled", 0.925, 0.885),
        ("section_label", 0.380, 0.587),
    ],
    "13_settings_language": [
        ("dropdown_panel", 0.83, 0.36),
        ("dropdown_selected", 0.780, 0.360),
        ("pack_card", 0.42, 0.60),
        ("pack_dl_btn", 0.437, 0.631),
    ],
    "14_settings_help": [
        ("keycap_bg", 0.918, 0.264),
        ("keycap_border", 0.897, 0.264),
        ("help_accent", 0.055, 0.647),
    ],
    "15_main_live": [
        ("topbar_bg", 0.50, 0.075),
        ("nav_active", 0.056, 0.105),
        ("nav_idle", 0.145, 0.105),
        ("live_btn", 0.529, 0.102),
        ("black_btn", 0.578, 0.102),
        ("iconbtn_bg", 0.700, 0.095),
        ("iconbtn_label", 0.700, 0.138),
        ("panel_border", 0.185, 0.175),
        ("panel_bg", 0.100, 0.300),
        ("panel_title", 0.030, 0.198),
        ("live_display_active", 0.560, 0.300),
        ("live_display_ref", 0.430, 0.283),
        ("live_display_border", 0.560, 0.375),
        ("output_label", 0.943, 0.198),
        ("search_input", 0.300, 0.666),
        ("verse_row_idle", 0.200, 0.886),
        ("verse_row_sel", 0.200, 0.800),
        ("verse_sel_border", 0.0215, 0.800),
        ("verse_number", 0.032, 0.800),
        ("section_head", 0.030, 0.719),
        ("green_text", 0.048, 0.545),
        ("stop_circle", 0.142, 0.545),
        ("preview_panel", 0.62, 0.63),
        ("queue_title", 0.780, 0.535),
    ],
}


def hexs(p):
    return "#%02x%02x%02x" % p[:3]


def dominant(im, box, n=4):
    c = im.crop(box)
    cols = c.getcolors(c.size[0] * c.size[1])
    cols.sort(reverse=True)
    t = c.size[0] * c.size[1]
    return [("%s %.0f%%" % (hexs(col[1]), 100 * col[0] / t)) for col in cols[:n]]


def main():
    for key, fname in SHOTS:
        path = os.path.join(S, fname)
        if not os.path.exists(path):
            print(key, "MISSING")
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        print(f"\n=== {key} ({w}x{h})")
        small = im.resize((w // 4, h // 4), Image.NEAREST)
        counts = Counter(small.getdata())
        tot = sum(counts.values())
        print("  dominant:", ", ".join(f"{hexs(c)} {100*n/tot:.1f}%" for c, n in counts.most_common(8)))
        for label, fx, fy in POINTS.get(key, []):
            x, y = min(int(fx * w), w - 1), min(int(fy * h), h - 1)
            print(f"  {label:20s} ({x:4d},{y:4d}) -> {hexs(im.getpixel((x, y)))}")

    # targeted crops on the main screen for flat fills
    im = Image.open(os.path.join(S, "Screenshot 2026-10-22 170451.png")).convert("RGB")
    w, h = im.size
    print("\n--- main screen crops")
    for label, box in [
        ("live_btn", (int(0.505 * w), int(0.078 * h), int(0.545 * w), int(0.118 * h))),
        ("black_btn", (int(0.555 * w), int(0.078 * h), int(0.595 * w), int(0.118 * h))),
        ("nav_pill", (int(0.020 * w), int(0.075 * h), int(0.080 * w), int(0.125 * h))),
        ("verse_selected", (int(0.100 * w), int(0.770 * h), int(0.400 * w), int(0.800 * h))),
        ("verse_idle", (int(0.100 * w), int(0.860 * h), int(0.400 * w), int(0.885 * h))),
        ("live_display_bg", (int(0.450 * w), int(0.230 * h), int(0.650 * w), int(0.260 * h))),
        ("panel_gap", (int(0.170 * w), int(0.140 * h), int(0.180 * w), int(0.190 * h))),
        ("icon_group", (int(0.660 * w), int(0.085 * h), int(0.700 * w), int(0.120 * h))),
    ]:
        print(f"  {label:18s}", dominant(im, box, 4))


if __name__ == "__main__":
    main()
