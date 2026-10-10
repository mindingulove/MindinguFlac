"""Build the themed-icon glyph: a seated figure listening to a stone, on a rock.

Everything is expressed as primitives on the adaptive-icon's 108x108 canvas so
the same definition can be rendered for eyeballing and emitted as Android
vector pathData. Content is kept inside the 66dp safe circle (radius 33 about
54,54) so no launcher mask can clip it.
"""
import math
from PIL import Image, ImageDraw

CANVAS = 108
CENTRE = (54.0, 54.0)
SAFE_R = 32.5

def ellipse(cx, cy, rx, ry):
    return ("ellipse", (cx, cy, rx, ry))

def circle(cx, cy, r):
    return ellipse(cx, cy, r, r)

def capsule(x0, y0, x1, y1, w):
    return ("capsule", (x0, y0, x1, y1, w))

def rect(x0, y0, x1, y1):
    return ("rect", (x0, y0, x1, y1))

def poly(points):
    return ("poly", tuple(points))

# Deliberately few, fat shapes with real gaps between them: a themed icon is
# drawn at roughly 48dp, where anything finer than ~3 units of this canvas
# turns to mush. Head, hat, body, rock and the note each have to survive on
# their own silhouette.
SHAPES = [
    # the rock he sits on — a solid base bar
    ellipse(54, 77, 24, 7.5),
    # body: one seated mass, no separate legs/torso at this size
    ellipse(52, 64, 14, 10),
    # head
    circle(50, 48, 9),
    # bucket hat: crown + a wide brim, the most recognisable part
    ellipse(50, 35.5, 8.2, 5.4),
    ellipse(50, 40.5, 14, 3.4),
    # arm raised to the ear, holding the stone
    capsule(58.5, 59, 61.5, 50, 6),
    circle(62, 47, 4.6),
    # one music note, set well clear of the stone so the gap survives
    circle(74, 44, 4.4),
    rect(76.6, 31, 78.6, 44),
    poly([(76.6, 31), (84, 28), (84, 31.5), (76.6, 34.5)]),
]

# Fit the whole composition inside the safe circle rather than hand-tuning
# every coordinate against it.
def _fit(shapes, limit):
    import math as _m
    worst = 0.0
    for kind, v in shapes:
        if kind == "ellipse":
            cx, cy, rx, ry = v
            pts = [(cx + rx, cy), (cx - rx, cy), (cx, cy + ry), (cx, cy - ry)]
        elif kind == "capsule":
            x0, y0, x1, y1, w = v
            pts = _capsule_polys(x0, y0, x1, y1, w)
        elif kind == "rect":
            x0, y0, x1, y1 = v
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:
            pts = list(v)
        for x, y in pts:
            worst = max(worst, _m.hypot(x - CENTRE[0], y - CENTRE[1]))
    if worst <= limit:
        return shapes
    k = limit / worst
    out = []
    for kind, v in shapes:
        if kind == "ellipse":
            cx, cy, rx, ry = v
            out.append(("ellipse", (CENTRE[0] + (cx - CENTRE[0]) * k,
                                    CENTRE[1] + (cy - CENTRE[1]) * k, rx * k, ry * k)))
        elif kind == "capsule":
            x0, y0, x1, y1, w = v
            out.append(("capsule", (CENTRE[0] + (x0 - CENTRE[0]) * k, CENTRE[1] + (y0 - CENTRE[1]) * k,
                                    CENTRE[0] + (x1 - CENTRE[0]) * k, CENTRE[1] + (y1 - CENTRE[1]) * k, w * k)))
        elif kind == "rect":
            x0, y0, x1, y1 = v
            out.append(("rect", (CENTRE[0] + (x0 - CENTRE[0]) * k, CENTRE[1] + (y0 - CENTRE[1]) * k,
                                 CENTRE[0] + (x1 - CENTRE[0]) * k, CENTRE[1] + (y1 - CENTRE[1]) * k)))
        else:
            out.append(("poly", tuple((CENTRE[0] + (x - CENTRE[0]) * k,
                                       CENTRE[1] + (y - CENTRE[1]) * k) for x, y in v)))
    return out


def _capsule_polys(x0, y0, x1, y1, w):
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * w / 2, dx / length * w / 2
    return [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]


SHAPES = _fit(SHAPES, SAFE_R)


def check_safe():
    worst = 0.0
    for kind, v in SHAPES:
        if kind == "ellipse":
            cx, cy, rx, ry = v
            pts = [(cx + rx, cy), (cx - rx, cy), (cx, cy + ry), (cx, cy - ry)]
        elif kind == "capsule":
            x0, y0, x1, y1, w = v
            pts = _capsule_polys(x0, y0, x1, y1, w)
        elif kind == "rect":
            x0, y0, x1, y1 = v
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        else:
            pts = list(v)
        for x, y in pts:
            worst = max(worst, math.hypot(x - CENTRE[0], y - CENTRE[1]))
    return worst


def render(size):
    scale = size / CANVAS
    im = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = scale * 4
    for kind, v in SHAPES:
        if kind == "ellipse":
            cx, cy, rx, ry = v
            d.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s], fill=(0, 0, 0, 255))
        elif kind == "circle":
            pass
        elif kind == "capsule":
            x0, y0, x1, y1, w = v
            d.polygon([(x * s, y * s) for x, y in _capsule_polys(x0, y0, x1, y1, w)], fill=(0, 0, 0, 255))
            for px, py in ((x0, y0), (x1, y1)):
                d.ellipse([(px - w / 2) * s, (py - w / 2) * s, (px + w / 2) * s, (py + w / 2) * s], fill=(0, 0, 0, 255))
        elif kind == "rect":
            x0, y0, x1, y1 = v
            d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], fill=(0, 0, 0, 255))
        else:
            d.polygon([(x * s, y * s) for x, y in v], fill=(0, 0, 0, 255))
    return im.resize((size, size), Image.LANCZOS)


def path_data():
    parts = []
    for kind, v in SHAPES:
        if kind == "ellipse":
            cx, cy, rx, ry = v
            parts.append(
                f"M{cx - rx:g},{cy:g}a{rx:g},{ry:g} 0 1,0 {2 * rx:g},0a{rx:g},{ry:g} 0 1,0 {-2 * rx:g},0Z")
        elif kind == "capsule":
            x0, y0, x1, y1, w = v
            pts = _capsule_polys(x0, y0, x1, y1, w)
            parts.append("M" + "L".join(f"{x:g},{y:g}" for x, y in pts) + "Z")
            for px, py in ((x0, y0), (x1, y1)):
                r = w / 2
                parts.append(f"M{px - r:g},{py:g}a{r:g},{r:g} 0 1,0 {2 * r:g},0a{r:g},{r:g} 0 1,0 {-2 * r:g},0Z")
        elif kind == "rect":
            x0, y0, x1, y1 = v
            parts.append(f"M{x0:g},{y0:g}H{x1:g}V{y1:g}H{x0:g}Z")
        else:
            parts.append("M" + "L".join(f"{x:g},{y:g}" for x, y in v) + "Z")
    return "".join(parts)


if __name__ == "__main__":
    import sys
    print(f"furthest point from centre: {check_safe():.1f} (safe limit {SAFE_R})")
    strip = Image.new("RGBA", (300, 110), (255, 255, 255, 255))
    x = 8
    for size in (96, 64, 48, 32, 24):
        g = render(size)
        bg = Image.new("RGBA", g.size, (238, 238, 238, 255))
        bg.alpha_composite(g)
        strip.alpha_composite(bg, (x, 8))
        x += size + 8
    strip.convert("RGB").save(sys.argv[1])
    print("preview ->", sys.argv[1])
    print()
    print(path_data())
