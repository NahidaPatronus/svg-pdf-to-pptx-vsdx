"""Serialize the in-memory editable drawing to Visio, without Office or an intermediate file."""

import math
import re
from lxml import etree as ET
from visio_format import EMU, appearance, text_block
from visio_geometry import (
    NAMES,
    cell,
    cells,
    el,
    freeform,
    geometry,
    preset,
    row,
    value,
)
from visio_package import Package, ordered


def local(tag):
    return ET.QName(tag).localname


class Frame:
    """PPT uses a top-left origin. A Visio parent uses a bottom-left origin."""

    def __init__(self, x, y, sx, sy, h):
        self.x, self.y, self.sx, self.sy, self.h = x, y, sx, sy, h

    def point(self, x, y):
        return (x - self.x) * self.sx, self.h - (y - self.y) * self.sy


def xform(s, cx, cy, w, h, angle=0, fx=False, fy=False):
    cells(
        s,
        PinX=cx,
        PinY=cy,
        Width=w,
        Height=h,
        Angle=angle,
        FlipX=int(fx),
        FlipY=int(fy),
    )
    cell(s, "LocPinX", w / 2, "Width/2")
    cell(s, "LocPinY", h / 2, "Height/2")


def edge_xform(s, a, b, *, curved=False, elbow_angle=None):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)
    cells(s, BeginX=ax, BeginY=ay, EndX=bx, EndY=by, GlueType=2 if curved else 0)
    cell(s, "PinX", (ax + bx) / 2, "(BeginX+EndX)/2")
    cell(s, "PinY", (ay + by) / 2, "(BeginY+EndY)/2")
    if elbow_angle is None:
        w = span
        h = w if curved else 0
        cell(s, "Width", w, "SQRT((EndX-BeginX)^2+(EndY-BeginY)^2)")
        cell(s, "Height", h, "Width" if curved else "0")
        cell(s, "Angle", math.atan2(dy, dx), "ATAN2(EndY-BeginY,EndX-BeginX)")
    else:
        angle = elbow_angle
        co, si = math.cos(angle), math.sin(angle)
        u, v = dx * co + dy * si, dy * co - dx * si
        w, h = abs(u), abs(v)
        uf = "((EndX-BeginX)*COS(Angle)+(EndY-BeginY)*SIN(Angle))"
        vf = "((EndY-BeginY)*COS(Angle)-(EndX-BeginX)*SIN(Angle))"
        cell(s, "Angle", angle)
        cell(s, "Width", w, "ABS(" + uf + ")")
        cell(s, "Height", h, "ABS(" + vf + ")")
        cell(s, "FlipX", int(u < 0), uf + "<0")
        cell(s, "FlipY", int(v > 0), vf + ">0")
    cell(s, "LocPinX", w / 2, "Width/2")
    cell(s, "LocPinY", h / 2, "Height/2")
    return w, h


def curve_edge(s, path, to_parent):
    pw = max(1, int(path.get("w", 1)))
    ph = max(1, int(path.get("h", 1)))
    cmds = [
        (local(c), [to_parent(int(p.get("x")) / pw, int(p.get("y")) / ph) for p in c])
        for c in path
    ]
    a, b = cmds[0][1][0], cmds[-1][1][-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    if den < 1e-14:
        return False
    edge_xform(s, a, b, curved=True)
    g = geometry(s)
    cell(g, "NoFill", 1)
    for i, (mode, pts) in enumerate(cmds, 1):
        uv = [
            (
                ((x - a[0]) * dx + (y - a[1]) * dy) / den,
                0.5 + ((y - a[1]) * dx - (x - a[0]) * dy) / den,
            )
            for x, y in pts
        ]
        x, y = uv[-1]
        if mode == "cubicBezTo":
            (p, q), (r, t) = uv[:2]
            row(g, "RelCubBezTo", i, X=x, Y=y, A=p, B=q, C=r, D=t)
        else:
            row(g, "RelMoveTo" if mode == "moveTo" else "RelLineTo", i, X=x, Y=y)
    return True


def render_shape(pkg, page, shape, parent, frame, warnings, glue):
    tag = local(shape._element)
    group = tag == "grpSp"
    picture = tag == "pic"
    props = shape._element.find("{*}grpSpPr" if group else "{*}spPr")
    xf = props.find("{*}xfrm")
    cx, cy = frame.point(shape.left + shape.width / 2, shape.top + shape.height / 2)
    w, h = shape.width * frame.sx, shape.height * frame.sy
    angle = -math.radians(shape.rotation)
    fx = xf.get("flipH") in ("1", "true")
    fy = xf.get("flipV") in ("1", "true")
    # Source labels can repeat or contain formula syntax. Keep sheet names
    # unique independently of the editable text stored in the Text element.
    label = re.sub(r"[^\w ]+", " ", shape.name or "Shape").strip()[:48] or "Shape"
    sheet_name = f"{label}_{shape.shape_id}"
    s = el(
        parent,
        "Shape",
        ID=shape.shape_id,
        Type="Group" if group else "Foreign" if picture else "Shape",
        Name=sheet_name,
        NameU=sheet_name,
        IsCustomName=1,
        IsCustomNameU=1,
        LineStyle=0,
        FillStyle=0,
        TextStyle=0,
    )
    if group:
        xform(s, cx, cy, w, h, angle, fx, fy)
        # A transparent group has no outline of its own.
        cells(s, LinePattern=0, FillPattern=0, SelectMode=2)
        off = xf.find("{*}chOff")
        ext = xf.find("{*}chExt")
        sw = int(ext.get("cx"))
        sh = int(ext.get("cy"))
        child_frame = Frame(
            int(off.get("x")),
            int(off.get("y")),
            w / sw if sw else frame.sx,
            h / sh if sh else frame.sy,
            h,
        )
        children = el(s, "Shapes")
        for child in shape.shapes:
            render_shape(pkg, page, child, children, child_frame, warnings, glue)
    elif picture:
        xform(s, cx, cy, w, h, angle, fx, fy)
        cells(s, FillPattern=0, LinePattern=0, ImgOffsetX=0, ImgOffsetY=0)
        cell(s, "ImgWidth", w, "Width")
        cell(s, "ImgHeight", h, "Height")
        preset(s, "rect", w, h, {})
        pkg.picture(s, page, shape.image.blob, shape.image.ext)
    else:
        g = props.find("{*}prstGeom")
        kind = g.get("prst") if g is not None else "custom"
        if tag == "cxnSp" and kind == "line":
            kind = "straightConnector1"
        adj = (
            {
                v.get("name"): int(v.get("fmla").split()[-1]) / 100000
                for v in g.findall("{*}avLst/{*}gd")
            }
            if g is not None
            else {}
        )

        def physical(u, v):
            x = ((1 - u if fx else u) - 0.5) * w
            y = (0.5 - (1 - v if fy else v)) * h
            co, si = math.cos(angle), math.sin(angle)
            return cx + co * x - si * y, cy + si * x + co * y

        body = shape._element.find("{*}txBody")
        is_text = body is not None and body.find(".//{*}t") is not None
        if not is_text and kind in NAMES:
            s.set("Master", str(pkg.master(kind, page)))
        if kind in ("line", "straightConnector1", "bentConnector2", "bentConnector3"):
            a, b = physical(0, 0), physical(1, 1)
            edge_angle = None
            if kind.startswith("bent"):
                edge_angle = angle + (math.pi if fx else 0)
            ew, eh = edge_xform(s, a, b, elbow_angle=edge_angle)
            preset(s, kind, ew, eh, adj)
            for key, side in (("stCxn", "Begin"), ("endCxn", "End")):
                ref = shape._element.find(".//{*}" + key)
                if ref is not None:
                    glue.append((s, side, int(ref.get("id")), int(ref.get("idx"))))
        elif kind == "custom":
            custom = props.find("{*}custGeom")
            paths = custom.findall("{*}pathLst/{*}path")
            arrow = (
                props.find("{*}ln/{*}tailEnd") is not None
                or props.find("{*}ln/{*}headEnd") is not None
            )
            as_edge = (
                arrow
                and len(paths) == 1
                and all(local(c) in ("moveTo", "cubicBezTo", "lnTo") for c in paths[0])
                and curve_edge(s, paths[0], physical)
            )
            if not as_edge:
                xform(s, cx, cy, w, h, angle, fx, fy)
                freeform(s, custom)
        else:
            xform(s, cx, cy, w, h, angle, fx, fy)
            if not is_text:
                preset(s, kind, w, h, adj)
        appearance(s, props, warnings)
        if is_text:
            text_block(s, body, pkg.faces)
    ordered(s)


def write_vsdx(deck, dest, reports, sizes):
    pkg = Package()
    for i, (slide, size) in enumerate(zip(deck.slides, sizes, strict=True), 1):
        w, h = (length / EMU for length in size)
        page, root = pkg.page(i, w, h)
        shapes = el(root, "Shapes")
        glue = []
        warnings = set()
        frame = Frame(0, 0, 1 / EMU, 1 / EMU, h)
        for shape in slide.shapes:
            render_shape(pkg, page, shape, shapes, frame, warnings, glue)
        if glue:
            connections = el(root, "Connects")
            for shape, side, target, port in glue:
                addr = f"Sheet.{target}!Connections."
                formula = f"PAR(PNT({addr}X{port+1},{addr}Y{port+1}))"
                for k in ("X", "Y"):
                    shape.find("{*}Cell[@N='" + side + k + "']").set("F", formula)
                el(
                    connections,
                    "Connect",
                    FromSheet=shape.get("ID"),
                    FromCell=side + "X",
                    FromPart=9 if side == "Begin" else 12,
                    ToSheet=target,
                    ToCell="Connections.X" + str(port + 1),
                    ToPart=100 + port,
                )
        reports[i - 1]["output_format"] = "vsdx"
        reports[i - 1]["warnings"] += sorted(warnings)
    pkg.save(dest)
