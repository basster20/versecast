"""Measure geometry (accent bounding boxes, corner radii) of key controls."""
import os
from PIL import Image

SHOTS = r"C:\Users\DELL\Pictures\Screenshots"


def is_orange(p):
    r, g, b = p[:3]
    return r > 225 and 55 < g < 130 and b < 45


def bbox_of(im, box, pred):
    crop = im.crop(box)
    w, h = crop.size
    px = crop.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if pred(px[x, y]):
                if x < minx: minx = x
                if y < miny: miny = y
                if x > maxx: maxx = x
                if y > maxy: maxy = y
    if maxx < 0:
        return None
    return (box[0] + minx, box[1] + miny, box[0] + maxx, box[1] + maxy)


def radius_estimate(im, bb):
    """How far in the top row does the fill start, vs the left edge at mid height."""
    px = im.load()
    x0, y0, x1, y1 = bb
    mid = (y0 + y1) // 2
    left_mid = next((x for x in range(x0, x1 + 1) if is_orange(px[x, mid])), x0)
    # walk down the left edge until the fill reaches left_mid
    r = 0
    for y in range(y0, mid):
        first = next((x for x in range(x0, x1 + 1) if is_orange(px[x, y])), None)
        if first is not None and first <= left_mid + 1:
            r = y - y0
            break
    return r


def dominant(im, box):
    crop = im.crop(box)
    colors = crop.getcolors(crop.size[0] * crop.size[1])
    colors.sort(reverse=True)
    return ["#%02x%02x%02x %d%%" % (c[1][0], c[1][1], c[1][2], 100 * c[0] // (crop.size[0] * crop.size[1]))
            for c in colors[:4]]


def main():
    im1 = Image.open(os.path.join(SHOTS, "Screenshot 2026-10-22 170150.png")).convert("RGB")
    W, H = im1.size
    print("img1", W, H)

    # Save changes button (top right)
    bb = bbox_of(im1, (int(0.82 * W), int(0.06 * H), int(0.93 * W), int(0.16 * H)), is_orange)
    print("save_btn bbox", bb, "size", (bb[2] - bb[0] + 1, bb[3] - bb[1] + 1), "radius~", radius_estimate(im1, bb))
    if bb:
        print("  fill", dominant(im1, (bb[0] + 20, bb[1] + 5, bb[0] + 40, bb[3] - 5)))

    # toggle in inspector
    bb2 = bbox_of(im1, (int(0.72 * W), int(0.83 * H), int(0.78 * W), int(0.89 * H)), is_orange)
    print("toggle bbox", bb2, "size", (bb2[2] - bb2[0] + 1, bb2[3] - bb2[1] + 1) if bb2 else None)

    # card metrics: caption strip
    print("card caption strip", dominant(im1, (int(0.02 * W), int(0.76 * H), int(0.24 * W), int(0.79 * H))))

    im8 = Image.open(os.path.join(SHOTS, "Screenshot 2026-10-22 170319.png")).convert("RGB")
    W8, H8 = im8.size
    print("\nimg8", W8, H8)
    bb = bbox_of(im8, (int(0.80 * W8), int(0.16 * H8), int(0.90 * W8), int(0.23 * H8)), is_orange)
    print("Auto chip bbox", bb, "size", (bb[2] - bb[0] + 1, bb[3] - bb[1] + 1) if bb else None,
          "radius~", radius_estimate(im8, bb) if bb else None)
    if bb:
        print("  fill", dominant(im8, (bb[0] + 15, bb[1] + 5, bb[0] + 35, bb[3] - 5)))
    bb2 = bbox_of(im8, (int(0.90 * W8), int(0.46 * H8), int(0.97 * W8), int(0.54 * H8)), is_orange)
    print("toggle bbox", bb2, "size", (bb2[2] - bb2[0] + 1, bb2[3] - bb2[1] + 1) if bb2 else None)

    im7 = Image.open(os.path.join(SHOTS, "Screenshot 2026-10-22 170300.png")).convert("RGB")
    W7, H7 = im7.size
    bb = bbox_of(im7, (int(0.25 * W7), int(0.66 * H7), int(0.40 * W7), int(0.74 * H7)), is_orange)
    print("\npublish_btn bbox", bb, "size", (bb[2] - bb[0] + 1, bb[3] - bb[1] + 1) if bb else None,
          "radius~", radius_estimate(im7, bb) if bb else None)
    if bb:
        print("  fill", dominant(im7, (bb[0] + 20, bb[1] + 5, bb[0] + 40, bb[3] - 5)))
    # tab underline
    print("tab underline", dominant(im7, (int(0.03 * W7), int(0.735 * H7), int(0.07 * W7), int(0.745 * H7))))


if __name__ == "__main__":
    main()
