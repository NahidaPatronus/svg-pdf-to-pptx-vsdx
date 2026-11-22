"""SVG paths in local coordinates and editable Office geometry in slide points."""

import math
from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path
from geometry import Geometry, bounds, identify
from svg_style import length, numbers


class PathPen(BasePen):
    def __init__(self):
        super().__init__(None)
        self.commands = []

    def _moveTo(self, p):
        self.commands.append(("m", p))

    def _lineTo(self, p):
        self.commands.append(("l", p))

    def _curveToOne(self, p, q, r):
        self.commands.append(("c", p, q, r))

    def _closePath(self):
        self.commands.append(("h",))


def name(node):
    return node.tag.split("}")[-1]


def contour(node, view):
    kind = name(node)
    vw, vh = view
    diag = math.hypot(vw, vh) / math.sqrt(2)

    def val(key, default=0):
        ref = (
            vw
            if key in ("x", "width", "rx", "x1", "x2", "cx")
            else diag if key == "r" else vh
        )
        return length(node.get(key, default), ref)

    if kind == "line":
        return [("m", (val("x1"), val("y1"))), ("l", (val("x2"), val("y2")))]
    if kind in ("polygon", "polyline"):
        vs = numbers(node.get("points", ""))
        if len(vs) % 2:
            raise ValueError("Odd coordinate count in SVG points")
        pts = list(zip(vs[::2], vs[1::2]))
        if len(pts) < 2:
            return []
        return [("m", pts[0]), *(("l", p) for p in pts[1:])] + (
            [("h",)] if kind == "polygon" else []
        )
    if kind == "rect":
        x, y, w, h = [val(k) for k in ("x", "y", "width", "height")]
        if min(w, h) <= 0:
            return []
        rx = val("rx", node.get("ry", 0))
        ry = val("ry", node.get("rx", 0))
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if min(rx, ry) <= 0:
            return [
                ("m", (x, y)),
                ("l", (x + w, y)),
                ("l", (x + w, y + h)),
                ("l", (x, y + h)),
                ("h",),
            ]
        path = f"M{x+rx},{y} H{x+w-rx} a{rx},{ry} 0 0 1 {rx},{ry} V{y+h-ry} a{rx},{ry} 0 0 1 {-rx},{ry} H{x+rx} a{rx},{ry} 0 0 1 {-rx},{-ry} V{y+ry} a{rx},{ry} 0 0 1 {rx},{-ry} Z"
    elif kind in ("ellipse", "circle"):
        cx, cy = val("cx"), val("cy")
        rx = val("r" if kind == "circle" else "rx")
        ry = rx if kind == "circle" else val("ry")
        if min(rx, ry) <= 0:
            return []
        path = f"M{cx-rx},{cy} a{rx},{ry} 0 1 0 {2*rx},0 a{rx},{ry} 0 1 0 {-2*rx},0 Z"
    else:
        path = node.get("d", "")
    pen = PathPen()
    parse_path(path, pen)
    cmds = pen.commands
    # SVG path parser may explicitly repeat the initial vertex before close.
    if (
        len(cmds) > 2
        and cmds[-1][0] == "h"
        and cmds[-2][0] == "l"
        and cmds[-2][-1] == cmds[0][-1]
    ):
        cmds.pop(-2)
    return cmds


def transformed(cmds, ctm):
    return [(op, *(ctm.transformPoint(p) for p in pts)) for op, *pts in cmds]


def geometry(node, local, cmds, t, fill):
    kind = name(node)
    points = [p for c in cmds for p in c[1:]]
    if not points:
        return None
    if (
        len(cmds) in (3, 4)
        and [c[0] for c in cmds] == ["m"] + ["l"] * (len(cmds) - 1)
        and fill is None
    ):
        p = [c[-1] for c in cmds]
        dx, dy = p[1][0] - p[0][0], p[1][1] - p[0][1]
        span = math.hypot(dx, dy)
        if span > 0:
            co, si = dx / span, dy / span
            local_points = [
                (
                    (x - p[0][0]) * co + (y - p[0][1]) * si,
                    -(x - p[0][0]) * si + (y - p[0][1]) * co,
                )
                for x, y in p
            ]
            ex, ey = local_points[-1]
            if (
                ex > 0
                and abs(ey) > 0.001
                and abs(local_points[2][0] - span) < 0.001
                and abs(local_points[2][1] - ey) < 0.001
                and span <= ex + 0.001
            ):
                cx, cy = (p[0][0] + p[-1][0]) / 2, (p[0][1] + p[-1][1]) / 2
                g = Geometry(
                    "bentConnector" + str(len(cmds) - 1),
                    (cx - ex / 2, cy - abs(ey) / 2, ex, abs(ey)),
                    math.degrees(math.atan2(si, co)) % 360,
                )
                if ey < 0:
                    g.adjusts["flipV"] = True
                if len(p) == 4:
                    g.adjusts["adj1"] = round(100000 * span / ex)
                return g
    if kind in ("rect", "circle", "ellipse"):
        # Fit the primitive in its own axes first, so rotation does not turn a preset into a freeform.
        x, y, w, h = bounds(p for cmd in local for p in cmd[1:])
        sx = math.hypot(t.xx, t.xy)
        sy = math.hypot(t.yx, t.yy)
        cx, cy = t.transformPoint((x + w / 2, y + h / 2))
        if abs(t.xx * t.yx + t.xy * t.yy) < 1e-8 * max(1, sx * sy):
            kw, kh = w * sx, h * sy
            rot = math.degrees(math.atan2(t.xy, t.xx)) % 360
            adjustments = {}
            preset = "ellipse" if kind != "rect" else "rect"
            if kind == "rect" and any(c[0] == "c" for c in local):
                first = local[0][1]
                rx = (first[0] - x) * sx
                first_curve = next(c for c in local if c[0] == "c")
                ry = (first_curve[-1][1] - y) * sy
                if abs(rx - ry) > 0.035:
                    return Geometry("custom", bounds(points))
                preset = "roundRect"
                adjustments = {"adj": round(100000 * rx / min(kw, kh))}
            return Geometry(
                preset, (cx - kw / 2, cy - kh / 2, kw, kh), rot, adjustments
            )
    if (
        kind in ("polygon", "path")
        and cmds[-1][0] == "h"
        and [c[0] for c in cmds].count("l") == 3
    ):
        x, y, w, h = bounds(points)
        mids = ((x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2))
        if min(w, h) > 0 and all(
            any(math.dist(p, q) < 0.025 for p in points) for q in mids
        ):
            return Geometry("diamond", (x, y, w, h))
    guess = identify(cmds)
    if (
        guess.kind in ("triangle", "rect", "parallelogram", "rightArrow")
        and cmds[-1][0] != "h"
        and fill is None
    ):
        return Geometry("custom", bounds(points))
    return guess
