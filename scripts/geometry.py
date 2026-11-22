"""Recover Office presets and their handles from contours, independent of object names."""

import math
from dataclasses import dataclass, field

EPS = 0.035


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def dist(a, b):
    return math.dist(a, b)


def unit(v):
    length = math.hypot(*v)
    return (v[0] / length, v[1] / length) if length else (1, 0)


def avg(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def close(a, b):
    return dist(a, b) < EPS


def bounds(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def poly(cmds):
    pts = [c[-1] for c in cmds if c[0] in ("m", "l")]
    if len(pts) > 1 and close(pts[0], pts[-1]):
        pts.pop()
    return pts


@dataclass
class Geometry:
    kind: str
    box: tuple
    angle: float = 0
    adjusts: dict = field(default_factory=dict)


def frame(kind, origin, xdir, w, h, adjusts=None):
    u = unit(xdir)
    return Geometry(
        kind,
        (origin[0] - w / 2, origin[1] - h / 2, w, h),
        math.degrees(math.atan2(u[1], u[0])) % 360,
        adjusts or {},
    )


def brace(cmds):
    cubics = [c for c in cmds if c[0] == "c"]
    if len(cubics) != 4 or cmds[-1][0] == "h" or len(cmds) > 7:
        return
    start, end = cmds[0][-1], cmds[-1][-1]
    axis = sub(end, start)
    length = math.hypot(*axis)
    if length < EPS:
        return
    along = unit(axis)
    perp = (-along[1], along[0])
    cusp = cubics[1][-1]
    delta = sub(cusp, start)
    depth = dot(delta, perp)
    station = dot(delta, along) / length
    if abs(depth) < EPS or not 0.04 < station < 0.96:
        return
    a = unit(sub(cusp, cubics[1][-2]))
    b = unit(sub(cubics[2][1], cusp))
    if dot(a, b) > -0.995 or abs(dot(a, along)) > 0.03:
        return
    right = (math.copysign(1, depth) * perp[0], math.copysign(1, depth) * perp[1])
    center = avg(start, end)
    center = (
        center[0] + right[0] * abs(depth) / 2,
        center[1] + right[1] * abs(depth) / 2,
    )
    shoulder = abs(dot(sub(cubics[0][-1], start), along))
    if dot((-right[1], right[0]), along) < 0:
        station = 1 - station
    return frame(
        "rightBrace",
        center,
        right,
        abs(depth),
        length,
        {
            "adj1": round(100000 * shoulder / min(length, abs(depth))),
            "adj2": round(100000 * station),
        },
    )


def block_arrow(pts):
    if len(pts) != 7:
        return
    for i, tip in enumerate(pts):
        p = [pts[(i + j) % 7] for j in range(7)]
        base = avg(p[3], p[4])
        axis = unit(sub(tip, base))
        length = dist(tip, base)
        perp = (-axis[1], axis[0])
        xs = [dot(sub(q, base), axis) for q in p]
        ys = [dot(sub(q, base), perp) for q in p]
        h = abs(ys[1] - ys[6])
        neck = xs[1]
        if h < EPS or length < EPS or not EPS < neck < length:
            continue
        if (
            max(abs(xs[j] - neck) for j in (2, 5, 6)) > EPS
            or max(abs(xs[j]) for j in (3, 4)) > EPS
        ):
            continue
        if (
            abs(ys[1] + ys[6]) > EPS
            or abs(ys[2] - ys[3]) > EPS
            or abs(ys[4] - ys[5]) > EPS
        ):
            continue
        return frame(
            "rightArrow",
            avg(tip, base),
            axis,
            length,
            h,
            {
                "adj1": round(100000 * abs(ys[3] - ys[4]) / h),
                "adj2": round(100000 * (length - neck) / min(h, length)),
            },
        )


def triangle(pts):
    for i, tip in enumerate(pts):
        a, b = pts[(i + 1) % 3], pts[(i + 2) % 3]
        mid = avg(a, b)
        up = unit(sub(tip, mid))
        w, h = dist(a, b), dist(tip, mid)
        if min(w, h) > EPS and abs(dot(sub(b, a), up)) < max(EPS, 0.007 * w):
            return frame("triangle", avg(tip, mid), (-up[1], up[0]), w, h)


def identify(cmds):
    points = [p for c in cmds for p in c[1:]]
    box = bounds(points)
    x, y, w, h = box
    curves = [c for c in cmds if c[0] == "c"]
    ops = "".join(c[0] for c in cmds)
    if curves and ops.count("m") == 1:
        b = brace(cmds)
        if b:
            return b
        if len(curves) == 4 and min(w, h) > EPS:
            if "l" in ops and ops.endswith("h"):
                radii = [
                    abs(c[-1][0] - last[0])
                    for c, last in zip(cmds[1:], [k[-1] for k in cmds[:-1]])
                    if c[0] == "c"
                ]
                ys = [
                    abs(c[-1][1] - last[1])
                    for c, last in zip(cmds[1:], [k[-1] for k in cmds[:-1]])
                    if c[0] == "c"
                ]
                if radii and max(radii + ys) - min(radii + ys) < max(
                    0.04, min(w, h) * 0.002
                ):
                    return Geometry(
                        "roundRect",
                        box,
                        adjusts={
                            "adj": round(100000 * sum(radii) / len(radii) / min(w, h))
                        },
                    )
            if "l" not in ops and close(cmds[0][-1], curves[-1][-1]):
                mids = [
                    (x, y + h / 2),
                    (x + w, y + h / 2),
                    (x + w / 2, y),
                    (x + w / 2, y + h),
                ]
                if all(
                    min(dist(c[-1], p) for p in mids) < max(EPS, min(w, h) * 0.003)
                    for c in curves
                ):
                    return Geometry("ellipse", box)
    if not curves and ops.count("m") == 1:
        p = poly(cmds)
        if len(p) == 2:
            return Geometry("line", box)
        if len(p) == 3:
            t = triangle(p)
            if t:
                return t
        if len(p) == 4:
            u, v = sub(p[1], p[0]), sub(p[2], p[1])
            w1, h1 = math.hypot(*u), math.hypot(*v)
            if min(w1, h1) > EPS and dist(avg(p[0], p[2]), avg(p[1], p[3])) < EPS:
                if abs(dot(unit(u), unit(v))) < 0.003:
                    if all(
                        any(
                            close(q, k)
                            for k in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
                        )
                        for q in p
                    ):
                        return Geometry("rect", box)
                    return frame("rect", avg(p[0], p[2]), u, w1, h1)
                # Office parallelogram has horizontal top and bottom and an editable slant.
                for j in range(2):
                    a, b, c, d = (p[(j + k) % 4] for k in range(4))
                    if (
                        abs(a[1] - b[1]) < EPS
                        and abs(c[1] - d[1]) < EPS
                        and min(w, h) > EPS
                    ):
                        top = min((a, b) if a[1] < c[1] else (c, d), key=lambda q: q[0])
                        bottom = min(
                            (c, d) if a[1] < c[1] else (a, b), key=lambda q: q[0]
                        )
                        shift = top[0] - bottom[0]
                        return Geometry(
                            "parallelogram",
                            box,
                            adjusts={
                                "adj": round(abs(shift) * 100000 / min(w, h)),
                                "flipH": shift < 0,
                            },
                        )
        ar = block_arrow(p)
        if ar:
            return ar
    return Geometry("custom", box)
