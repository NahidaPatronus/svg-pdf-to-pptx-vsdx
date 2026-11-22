"""DrawingML geometry, fills, pictures and editable line ends."""

import io, math
from lxml import etree as ET
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE as ST, MSO_CONNECTOR
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt
from geometry import bounds, sub, dist, unit, avg, poly, dot, Geometry, close, identify

TYPES = {
    "rect": ST.RECTANGLE,
    "roundRect": ST.ROUNDED_RECTANGLE,
    "ellipse": ST.OVAL,
    "diamond": ST.DIAMOND,
    "rightBrace": ST.RIGHT_BRACE,
    "rightArrow": ST.RIGHT_ARROW,
    "triangle": ST.ISOSCELES_TRIANGLE,
    "parallelogram": ST.PARALLELOGRAM,
}


def tag(parent, q, **attrs):
    el = OxmlElement(q)
    for k, v in attrs.items():
        el.set(k, str(v))
    parent.append(el)
    return el


def ink(parent, color, alpha=1):
    if color is None:
        tag(parent, "a:noFill")
        return
    node = tag(tag(parent, "a:solidFill"), "a:srgbClr", val=bytes(color).hex().upper())
    if alpha < 0.99999:
        tag(node, "a:alpha", val=round(alpha * 100000))


def appearance(shape, style):
    sp = shape._element.spPr
    theme = shape._element.find("{*}style")
    if theme is not None:
        shape._element.remove(theme)
    for e in list(sp):
        if ET.QName(e).localname in (
            "solidFill",
            "noFill",
            "ln",
            "gradFill",
            "pattFill",
        ):
            sp.remove(e)
    ink(sp, style["fill"], style["ca"])
    line = tag(sp, "a:ln", w=max(1, round(style["width"] * 12700)))
    ink(line, style["stroke"], style["CA"])
    if len(style["dash"]) == 2 and any(
        max(
            abs(style["dash"][0] / style["width"] - d),
            abs(style["dash"][1] / style["width"] - g),
        )
        < 0.12
        for d, g in ((1, 1), (4, 3), (8, 3))
    ):
        ratio = style["dash"][0] / style["width"]
        tag(
            line,
            "a:prstDash",
            val="sysDot" if ratio < 2 else ("dash" if ratio < 6 else "lgDash"),
        )
    elif style["dash"] and all(x > 0 for x in style["dash"]):
        d = style["dash"]
        d = d if len(d) % 2 == 0 else d * 2
        custom = tag(line, "a:custDash")
        for length, space in zip(d[::2], d[1::2]):
            tag(
                custom,
                "a:ds",
                d=round(100000 * length / style["width"]),
                sp=round(100000 * space / style["width"]),
            )
    if style.get("cap"):
        line.set("cap", style["cap"])
    if style.get("join"):
        tag(line, "a:" + style["join"])
    for side, element in (("start", "a:headEnd"), ("end", "a:tailEnd")):
        if style.get(side):
            tip, width, length = style[side]
            tag(line, element, type=tip, w=width, len=length)


def add_path(slide, item, geom=None):
    cmds = item.data
    geom = geom or identify(cmds)
    x, y, w, h = geom.box
    if geom.kind in ("bentConnector2", "bentConnector3"):
        shape = slide.shapes.add_connector(
            MSO_CONNECTOR.ELBOW, Pt(x), Pt(y), Pt(x + w), Pt(y + h)
        )
        shape.rotation = geom.angle
        properties = shape._element.spPr
        properties.prstGeom.set("prst", geom.kind)
        if geom.adjusts.get("flipV"):
            properties.xfrm.set("flipV", "1")
        adjustments = properties.prstGeom.find("{*}avLst")
        if "adj1" in geom.adjusts:
            tag(
                adjustments,
                "a:gd",
                name="adj1",
                fmla="val " + str(geom.adjusts["adj1"]),
            )
    elif geom.kind == "line":
        a, b = poly(cmds)
        if item.style.get("end") or item.style.get("start"):
            shape = slide.shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT, *[Pt(n) for n in (*a, *b)]
            )
        else:
            shape = slide.shapes.add_shape(ST.RECTANGLE, Pt(x), Pt(y), Pt(w), Pt(h))
            sp = shape._element.spPr
            sp.prstGeom.set("prst", "line")
            if b[0] < a[0]:
                sp.xfrm.set("flipH", "1")
            if b[1] < a[1]:
                sp.xfrm.set("flipV", "1")
    else:
        shape = slide.shapes.add_shape(
            TYPES.get(geom.kind, ST.RECTANGLE),
            Pt(x),
            Pt(y),
            Pt(max(0.001, w)),
            Pt(max(0.001, h)),
        )
        shape.rotation = geom.angle
        sp = shape._element.spPr
        if geom.kind == "custom":
            old = sp.prstGeom
            custom = OxmlElement("a:custGeom")
            sp.replace(old, custom)
            for name in ["avLst", "gdLst", "ahLst", "cxnLst"]:
                tag(custom, "a:" + name)
            tag(custom, "a:rect", l="l", t="t", r="r", b="b")
            path = tag(
                tag(custom, "a:pathLst"),
                "a:path",
                w=max(1, round(w * 12700)),
                h=max(1, round(h * 12700)),
            )
            for op, *pts in cmds:
                nd = tag(
                    path,
                    "a:"
                    + {"m": "moveTo", "l": "lnTo", "c": "cubicBezTo", "h": "close"}[op],
                )
                for px, py in pts:
                    tag(
                        nd, "a:pt", x=round((px - x) * 12700), y=round((py - y) * 12700)
                    )
        else:
            adjusts = sp.prstGeom.find("{*}avLst")
            for k, v in geom.adjusts.items():
                if k == "flipH":
                    if v:
                        sp.xfrm.set("flipH", "1")
                else:
                    tag(adjusts, "a:gd", name=k, fmla="val " + str(v))
    appearance(shape, item.style)
    return shape, geom


def add_picture(slide, item):
    image, (a, b, c) = item.data
    dx, dy = sub(b, a), sub(c, a)
    w, h = dist(b, a), dist(c, a)
    center = (a[0] + (dx[0] + dy[0]) / 2, a[1] + (dx[1] + dy[1]) / 2)
    if w * h < 0.0001:
        raise ValueError("Degenerate picture transform")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    obj = slide.shapes.add_picture(
        stream, Pt(center[0] - w / 2), Pt(center[1] - h / 2), Pt(w), Pt(h)
    )
    obj.rotation = math.degrees(math.atan2(dx[1], dx[0])) % 360
    if dx[0] * dy[1] - dx[1] * dy[0] < 0:
        obj._element.spPr.xfrm.set("flipV", "1")
    return obj


def outline_key(cmds):
    points = []
    for cmd in cmds:
        if cmd[0] == "h":
            continue
        if (
            cmd[0] == "l"
            and close(cmd[-1], cmds[0][-1])
            and cmd is cmds[-2 if cmds[-1][0] == "h" else -1]
        ):
            continue
        points.append((cmd[0], *[(round(x, 2), round(y, 2)) for x, y in cmd[1:]]))
    return points


def combine(first, second):
    a, b = first.style, second.style
    if (
        a["fill"] is not None
        and a["stroke"] is None
        and b["stroke"] is not None
        and b["fill"] is None
    ):
        if outline_key(first.data) == outline_key(second.data):
            first.data = second.data
            first.style = {**b, "fill": a["fill"], "ca": a["ca"]}
            return True
    if (
        a["stroke"] is None
        or len(first.data) < 2
        or first.data[-1][0] not in ("l", "c")
    ):
        return False
    if any(op[0] not in ("m", "l", "h") for op in second.data):
        return False
    pts = poly(second.data)
    if len(pts) != 3 or (b["fill"] or b["stroke"]) != a["stroke"]:
        return False
    last = first.data[-1]
    end = last[-1]
    incoming = last[-2] if last[0] == "c" else first.data[-2][-1]
    axis = unit(sub(end, incoming))
    tip = max(pts, key=lambda q: dot(sub(q, end), axis))
    base = [q for q in pts if q != tip]
    if len(base) != 2:
        return False
    mid = avg(*base)
    width = dist(*base)
    length = dist(mid, tip)
    if (
        length == 0
        or dot(unit(sub(tip, mid)), axis) < 0.94
        or dist(end, tip) > 1.05 * length
    ):
        return False

    def size(n, axis):
        # Office gives thin arrowheads a minimum physical footprint. PDFMaker
        # draws small open ends about 5 pt wide and 4 pt long on hairlines.
        if b["fill"] is None:
            small = max(5.0 if axis == "width" else 4.0, 2 * a["width"])
            options = ((small, "sm"), (1.5 * small, "med"), (2 * small, "lg"))
        else:
            small = max(3.0, 2 * a["width"])
            options = ((small, "sm"), (4 * small / 3, "med"), (2 * small, "lg"))
        return min(options, key=lambda p: abs(p[0] - n))[1]

    a["marker_pt"] = (width, length)
    first.data[-1] = (*last[:-1], tip)
    a["end"] = (
        "triangle" if b["fill"] is not None else "arrow",
        size(width, "width"),
        size(length, "length"),
    )
    return True
