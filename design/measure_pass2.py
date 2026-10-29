"""Pass 2b: panel geometry + text colors (brightest pixel in a tight crop)."""
import os
from PIL import Image

S = r"C:\Users\DELL\Pictures\Screenshots"
MAIN = os.path.join(S, "Screenshot 2026-10-22 170451.png")


def hexs(p):
    return "#%02x%02x%02x" % p[:3]


def lum(p):
    r, g, b = p[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def runs(im, y, x0, x1, tol=6):
    px = im.load()
    out = []
    cur = px[x0, y][:3]
    start = x0
    for x in range(x0 + 1, x1):
        c = px[x, y][:3]
        if max(abs(a - b) for a, b in zip(c, cur)) > tol:
            if x - start >= 3:
                out.append((start, x - 1, hexs(cur)))
            cur = c
            start = x
    out.append((start, x1 - 1, hexs(cur)))
    return out


def vruns(im, x, y0, y1, tol=6):
    px = im.load()
    out = []
    cur = px[x, y0][:3]
    start = y0
    for y in range(y0 + 1, y1):
        c = px[x, y][:3]
        if max(abs(a - b) for a, b in zip(c, cur)) > tol:
            if y - start >= 3:
                out.append((start, y - 1, hexs(cur)))
            cur = c
            start = y
    out.append((start, y1 - 1, hexs(cur)))
    return out


def brightest(im, box):
    c = im.crop(box)
    px = c.load()
    best = None
    for y in range(c.size[1]):
        for x in range(c.size[0]):
            p = px[x, y][:3]
            if best is None or lum(p) > lum(best):
                best = p
    return hexs(best) if best else None


def most_saturated(im, box):
    c = im.crop(box)
    px = c.load()
    best, bs = None, -1
    for y in range(c.size[1]):
        for x in range(c.size[0]):
            p = px[x, y][:3]
            s = max(p) - min(p)
            if s + lum(p) * 0.15 > bs:
                bs, best = s + lum(p) * 0.15, p
    return hexs(best) if best else None


def main():
    im = Image.open(MAIN).convert("RGB")
    W, H = im.size
    print("main", W, H)

    print("\n-- horizontal runs at y=0.30H (panel columns)")
    for a, b, c in runs(im, int(0.30 * H), 0, W):
        print(f"  x {a:4d}-{b:4d} ({b-a+1:4d}px) {c}")

    print("\n-- vertical runs at x=0.05W (panel rows)")
    for a, b, c in vruns(im, int(0.05 * W), 0, H):
        print(f"  y {a:4d}-{b:4d} ({b-a+1:4d}px) {c}")

    print("\n-- text colors (brightest px in crop)")
    for label, (x0, y0, x1, y1) in {
        "app_title_pewbeam": (0.02, 0.0, 0.10, 0.02),
        "live_transcript_title": (0.018, 0.178, 0.115, 0.205),
        "recent_detections_title": (0.185, 0.178, 0.29, 0.205),
        "live_display_title": (0.393, 0.178, 0.49, 0.205),
        "genesis_ref_orange": (0.398, 0.268, 0.49, 0.29),
        "genesis_body": (0.398, 0.298, 0.68, 0.318),
        "main_output": (0.757, 0.192, 0.845, 0.212),
        "traditional": (0.865, 0.192, 0.945, 0.212),
        "queue_title": (0.757, 0.525, 0.81, 0.548),
        "search_text": (0.196, 0.655, 0.245, 0.678),
        "section_genesis1": (0.018, 0.712, 0.075, 0.732),
        "verse_num_1": (0.026, 0.792, 0.034, 0.812),
        "verse_body_selected": (0.040, 0.792, 0.200, 0.812),
        "verse_body_idle": (0.040, 0.878, 0.200, 0.896),
        "transcribing_green": (0.033, 0.538, 0.105, 0.558),
    }.items():
        print(f"  {label:24s} {brightest(im, (int(x0*W), int(y0*H), int(x1*W), int(y1*H)))}")

    print("\n-- accent / semantic colors (most saturated px in crop)")
    for label, (x0, y0, x1, y1) in {
        "live_red": (0.505, 0.088, 0.548, 0.112),
        "nav_pill": (0.020, 0.085, 0.082, 0.118),
        "live_display_bottom_border": (0.40, 0.372, 0.70, 0.380),
        "verse_selected_border": (0.018, 0.775, 0.450, 0.790),
        "icon_stop_ring": (0.132, 0.530, 0.155, 0.560),
    }.items():
        print(f"  {label:28s} {most_saturated(im, (int(x0*W), int(y0*H), int(x1*W), int(y1*H)))}")

    # keycap + settings text colors
    im2 = Image.open(os.path.join(S, "Screenshot 2026-10-22 170435.png")).convert("RGB")
    W2, H2 = im2.size
    print("\n-- help page")
    print("  keycap box", hexs(im2.getpixel((int(0.918 * W2), int(0.264 * H2)))))
    print("  keycap text", brightest(im2, (int(0.905 * W2), int(0.255 * H2), int(0.933 * W2), int(0.273 * H2))))
    print("  row label", brightest(im2, (int(0.345 * W2), int(0.245 * H2), int(0.44 * W2), int(0.265 * H2))))
    print("  desc text", brightest(im2, (int(0.345 * W2), int(0.135 * H2), int(0.50 * W2), int(0.155 * H2))))
    print("  license body", brightest(im2, (int(0.345 * W2), int(0.745 * H2), int(0.60 * W2), int(0.765 * H2))))

    im3 = Image.open(os.path.join(S, "Screenshot 2026-10-22 170358.png")).convert("RGB")
    W3, H3 = im3.size
    print("\n-- audio page 2")
    print("  COMMANDS label", brightest(im3, (int(0.345 * W3), int(0.578 * H3), int(0.43 * W3), int(0.596 * H3))))
    print("  chip text", brightest(im3, (int(0.360 * W3), int(0.712 * H3), int(0.42 * W3), int(0.732 * H3))))
    print("  chip fill", hexs(im3.getpixel((int(0.352 * W3), int(0.722 * H3)))))
    print("  disabled add text", brightest(im3, (int(0.900 * W3), int(0.874 * H3), int(0.940 * W3), int(0.894 * H3))))


if __name__ == "__main__":
    main()
