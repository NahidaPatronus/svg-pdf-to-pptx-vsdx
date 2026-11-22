"""Linear SVG fill gradients mapped to DrawingML's color-stop axis."""

import math
from svg_style import DEFAULTS, alpha, color, length, transform
from svg_geometry import name
from office_shapes import tag


def apply_gradient(shape, gradient, cascade, box, ctm, geom, view, opacity):
    if gradient is None or name(gradient) != "linearGradient":
        raise ValueError("Only local linear SVG fill gradients are supported.")
    if gradient.get("spreadMethod", "pad") != "pad":
        raise ValueError("Repeating or reflected gradients need a different fill.")
    x, y, w, h = box
    if min(w, h) <= 0:
        return
    absolute = gradient.get("gradientUnits", "objectBoundingBox") == "userSpaceOnUse"
    t = ctm if absolute else ctm.translate(x, y).scale(w, h)
    t = t.transform(transform(gradient.get("gradientTransform")))
    ref = view if absolute else (1, 1)
    x1, y1, x2, y2 = [
        length(gradient.get(k, v), ref[i % 2])
        for i, (k, v) in enumerate(
            (("x1", "0%"), ("y1", "0%"), ("x2", "100%"), ("y2", "0%"))
        )
    ]
    dx, dy = x2 - x1, y2 - y1
    den = dx * dx + dy * dy
    if den == 0:
        raise ValueError("Degenerate SVG linear gradient")
    inv = t.inverse()
    # Project the target shape's bounding corners onto the source gradient axis.
    ux = (dx * inv.xx + dy * inv.xy) / den
    uy = (dx * inv.yx + dy * inv.yy) / den
    gx, gy, gw, gh = geom.box
    cx, cy = gx + gw / 2, gy + gh / 2
    rot = math.radians(geom.angle)
    co, si = math.cos(rot), math.sin(rot)
    vx = co * ux + si * uy
    vy = -si * ux + co * uy
    half = (abs(vx) * gw + abs(vy) * gh) / 2
    start = inv.transformPoint((cx, cy))
    center = ((start[0] - x1) * dx + (start[1] - y1) * dy) / den
    lo, hi = center - half, center + half
    if hi - lo < 1e-10:
        raise ValueError("Degenerate gradient extent")
    stops = []
    for ch in gradient:
        if not isinstance(ch.tag, str) or name(ch) != "stop":
            continue
        st = cascade.style(ch, DEFAULTS)
        rgb = color(st.get("stop-color", ch.get("stop-color", "black")))
        ca = alpha(st.get("stop-opacity", ch.get("stop-opacity", 1))) * opacity
        offset = max(stops[-1][0] if stops else 0, alpha(ch.get("offset", 0)))
        stops.append((offset, tuple(rgb) + (ca * 255,)))
    if not stops:
        raise ValueError("SVG linear gradient has no local color stops")

    def interp(v):
        if v <= stops[0][0]:
            return stops[0][1]
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if v <= b and b > a:
                return tuple(x + (y - x) * (v - a) / (b - a) for x, y in zip(ca, cb))
        return stops[-1][1]

    fitted = [
        (lo, interp(lo)),
        *[(p, c) for p, c in stops if lo < p < hi],
        (hi, interp(hi)),
    ]
    sp = shape._element.spPr
    old = sp.find("{*}solidFill")
    grad = tag(sp, "a:gradFill", rotWithShape="1")
    sp.remove(grad)
    sp.replace(old, grad)
    gs = tag(grad, "a:gsLst")
    for p, c in fitted:
        stop = tag(gs, "a:gs", pos=round(100000 * (p - lo) / (hi - lo)))
        srgb = tag(stop, "a:srgbClr", val=bytes(round(v) for v in c[:3]).hex().upper())
        if c[3] < 254.99:
            tag(srgb, "a:alpha", val=round(c[3] * 100000 / 255))
    tag(
        grad,
        "a:lin",
        ang=round(math.degrees(math.atan2(vy, vx)) % 360 * 60000) % 21600000,
        scaled="0",
    )
