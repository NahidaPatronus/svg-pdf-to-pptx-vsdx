"""Map common SVG endpoint markers to native Office line ends."""

import math
import re
from fontTools.misc.transform import Identity
from geometry import poly, dist
from svg_geometry import contour, name, transformed
from svg_style import DEFAULTS, length, numbers, transform, viewport, color


def fragment(value):
    m = re.fullmatch(r"""url\(\s*['"]?#([^'")\s]+)['"]?\s*\)""", value.strip())
    if not m:
        raise ValueError(f"Expected a local SVG fragment, got {value!r}")
    return m[1]


def markers(cmds, s, t, style, ids, cascade):
    for side, prop in (("start", "marker-start"), ("end", "marker-end")):
        ref = s.get(prop, "none")
        if ref == "none":
            continue
        marker = ids.get(fragment(ref))
        if marker is None or name(marker) != "marker":
            raise ValueError(f"Unknown SVG marker {ref}")
        children = [
            c
            for c in marker
            if isinstance(c.tag, str) and name(c) not in ("title", "desc")
        ]
        if len(children) != 1:
            raise ValueError(f"Compound SVG marker {ref} is unsupported")
        child = children[0]
        mw, mh = (length(marker.get(k, 3)) for k in ("markerWidth", "markerHeight"))
        box = numbers(marker.get("viewBox", f"0 0 {mw} {mh}"))
        vt = viewport(box, mw, mh, marker.get("preserveAspectRatio"))
        mx = length(marker.get("refX", 0), box[2])
        my = length(marker.get("refY", 0), box[3])
        m = vt.transform(transform(child.get("transform")))
        local = transformed(contour(child, box[2:]), m)
        if not local:
            continue
        pts = poly(local)
        attr = cascade.style(child, cascade.style(marker, DEFAULTS))
        kind = name(child)
        if kind in ("circle", "ellipse"):
            tip = "oval"
        elif len(pts) == 3:
            tip = "arrow" if attr.get("fill") == "none" else "triangle"
        elif len(pts) == 4:
            tip = "diamond"
        else:
            raise ValueError(f"Unsupported shape in SVG marker {ref}")
        paint = attr["stroke"] if tip == "arrow" else attr["fill"]
        if paint == "context-stroke":
            paint = s["stroke"]
        if color(paint) != style["stroke"]:
            raise ValueError(f"SVG marker {ref} has a separate color from its shaft")
        orient = marker.get("orient", "0")
        if orient not in ("auto", "auto-start-reverse"):
            raise ValueError(
                f"Fixed-angle marker {ref} cannot be a rotating PowerPoint line end"
            )
        allpts = [p for cmd in local for p in cmd[1:]]
        lx = min(p[0] for p in allpts)
        rx = max(p[0] for p in allpts)
        ty = min(p[1] for p in allpts)
        by = max(p[1] for p in allpts)
        scale = math.sqrt(abs(t.xx * t.yy - t.xy * t.yx))
        if marker.get("markerUnits", "strokeWidth") == "strokeWidth":
            scale *= style["width"] / scale
        width = (by - ty) * scale
        depth = (rx - lx) * scale
        if min(width, depth) <= 0:
            continue
        sign = -1 if side == "start" and orient == "auto" else 1
        if tip in ("triangle", "arrow"):
            edge = rx if sign > 0 else lx
            outer = min(pts, key=lambda p: abs(p[0] - edge))
            if abs(outer[1] - (ty + by) / 2) > 0.12 * (by - ty):
                raise ValueError(
                    f"SVG marker {ref} points inward or has an asymmetric tip"
                )
        refx, refy = vt.transformPoint((mx, my))
        if abs(refy - (ty + by) / 2) > 0.15 * (by - ty):
            raise ValueError(f"Off-axis SVG marker {ref}")
        if side == "start":
            idx = 0
            endpoint = cmds[0][-1]
            near = cmds[1][1]
        else:
            idx = len(cmds) - 1
            if cmds[idx][0] not in ("c", "l"):
                raise ValueError("Marker on a closed contour")
            endpoint = cmds[idx][-1]
            near = cmds[idx][-2] if cmds[idx][0] == "c" else cmds[idx - 1][-1]
        distance = dist(endpoint, near)
        if distance:
            overhang = ((rx - refx) if sign > 0 else (refx - lx)) * scale
            point = tuple(
                a + (a - b) * overhang / distance for a, b in zip(endpoint, near)
            )
            cmds[idx] = (*cmds[idx][:-1], point)

        def closest(n, small):
            return min(
                ((small, "sm"), (1.5 * small, "med"), (2 * small, "lg")),
                key=lambda p: abs(p[0] - n),
            )[1]

        small = max(2 * style["width"], 5 if tip == "arrow" else 3)
        style[side] = (
            tip,
            closest(width, small),
            closest(depth, max(2 * style["width"], 4) if tip == "arrow" else small),
        )
        style[side + "_pt"] = (width, depth)
