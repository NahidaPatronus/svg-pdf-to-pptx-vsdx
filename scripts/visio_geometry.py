"""Native ShapeSheet geometry for independent, resizable page shapes (inches)."""

from lxml import etree as ET

NS = "http://schemas.microsoft.com/office/visio/2012/main"
OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def value(n):
    return format(n, ".14g") if isinstance(n, float) else str(n)


def el(parent, tag, **attrs):
    return ET.SubElement(
        parent, "{%s}%s" % (NS, tag), {k: value(v) for k, v in attrs.items()}
    )


def cell(parent, name, v, formula=None, unit=None):
    attrs = {"N": name, "V": value(v)}
    if formula is not None:
        attrs["F"] = formula
    if unit:
        attrs["U"] = unit
    return el(parent, "Cell", **attrs)


def cells(parent, **values):
    for k, v in values.items():
        cell(parent, k, v)


def geometry(shape):
    return el(shape, "Section", N="Geometry", IX=0)


def row(section, kind, index, **coords):
    node = el(section, "Row", T=kind, IX=index)
    for key, v in coords.items():
        if isinstance(v, tuple):
            cell(node, key, *v)
        else:
            cell(node, key, v)
    return node


def ports(shape, w, h):
    s = el(shape, "Section", N="Connection")
    for i, (fx, fy) in enumerate(((0.5, 1), (0, 0.5), (0.5, 0), (1, 0.5))):
        r = el(s, "Row", T="Connection", IX=i)
        cell(r, "X", w * fx, f"Width*{fx}")
        cell(r, "Y", h * fy, f"Height*{fy}")
        cells(r, DirX=0, DirY=0, Type=0)


def control(s, name, x, y, xf, yf, behavior=(0, 0)):
    r = el(s, "Row", N=name)
    cell(r, "X", x, xf)
    cell(r, "Y", y, yf)
    cells(r, XCon=behavior[0], YCon=behavior[1])


def preset(shape, kind, w, h, adj):
    """Keep adjustment handles and live formulas as well as evaluated row values."""
    if kind in (
        "rect",
        "roundRect",
        "ellipse",
        "diamond",
        "triangle",
        "parallelogram",
        "rightArrow",
        "rightBrace",
    ):
        if kind == "roundRect":
            ratio = adj.get("adj", 0.16667)
            cell(
                shape, "Rounding", min(w, h) * ratio, f"MIN(Width,Height)*{ratio:.12g}"
            )
        ports(shape, w, h)
    xslant = min(w, h) * adj.get("adj", 0.25)
    if kind in ("rightArrow", "rightBrace", "parallelogram"):
        ctl = el(shape, "Section", N="Control")
        if kind == "rightArrow":
            neck = max(0, w - min(w, h) * adj.get("adj2", 0.5))
            shoulder = (1 - adj.get("adj1", 0.5)) * h / 2
            control(
                ctl,
                "Neck",
                neck,
                shoulder,
                "Width-MIN(Width,Height)*" + value(adj.get("adj2", 0.5)),
                "Height*" + value(shoulder / h),
            )
        elif kind == "parallelogram":
            control(
                ctl,
                "Slant",
                xslant,
                h,
                "MIN(Width,Height)*" + value(adj.get("adj", 0.25)),
                "Height",
                (0, 1),
            )
        else:
            cusp = 1 - adj.get("adj2", 0.5)
            radius = min(
                max(0, adj.get("adj1", 0.0833)) * min(w, h) / h,
                cusp / 2,
                (1 - cusp) / 2,
            )
            control(ctl, "Tip", w, cusp * h, "Width", "Height*" + value(cusp), (1, 0))
            control(
                ctl,
                "Bend",
                0,
                radius * h,
                "0",
                "MIN(Width,Height)*" + value(adj.get("adj1", 0.0833)),
                (1, 0),
            )
    g = geometry(shape)
    if kind == "ellipse":
        row(
            g,
            "Ellipse",
            1,
            X=(w / 2, "Width/2"),
            Y=(h / 2, "Height/2"),
            A=(w, "Width"),
            B=(h / 2, "Height/2"),
            C=(w / 2, "Width/2"),
            D=(h, "Height"),
        )
        return
    if kind == "rightBrace":
        cell(g, "NoFill", 1)
        # Use two editable controls for the cusp and the shoulder radius.
        # Relative coordinates preserve the brace through rotation and resizing.
        cf = "Controls.Tip.Y/Height"
        rf = "MIN(Controls.Bend.Y/Height,MIN(" + cf + ",1-" + cf + ")/2)"

        def yy(a, b):
            return (
                a + b * radius,
                ("1" if a == 1 else cf if a == cusp else "0")
                + ("+" if b >= 0 else "-")
                + value(abs(b))
                + "*"
                + rf,
            )

        row(g, "RelMoveTo", 1, X=0, Y=1)
        row(g, "RelCubBezTo", 2, A=0.28, B=1, C=0.5, D=yy(1, -0.45), X=0.5, Y=yy(1, -1))
        row(g, "RelLineTo", 3, X=0.5, Y=yy(cusp, 1))
        row(
            g,
            "RelCubBezTo",
            4,
            A=0.5,
            B=yy(cusp, 0.45),
            C=0.72,
            D=(cusp, cf),
            X=1,
            Y=(cusp, cf),
        )
        row(
            g,
            "RelCubBezTo",
            5,
            A=0.72,
            B=(cusp, cf),
            C=0.5,
            D=yy(cusp, -0.45),
            X=0.5,
            Y=yy(cusp, -1),
        )
        row(g, "RelLineTo", 6, X=0.5, Y=yy(0, 1))
        row(g, "RelCubBezTo", 7, A=0.5, B=yy(0, 0.45), C=0.28, D=0, X=0, Y=0)
        return
    if kind in ("rect", "roundRect"):
        path = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    elif kind == "triangle":
        path = [(0.5, 1), (1, 0), (0, 0), (0.5, 1)]
    elif kind == "diamond":
        path = [(0.5, 1), (1, 0.5), (0.5, 0), (0, 0.5), (0.5, 1)]
    elif kind == "parallelogram":
        k = (xslant / w, "Controls.Slant.X/Width")
        kk = (1 - k[0], "1-Controls.Slant.X/Width")
        path = [(k, 1), (1, 1), (kk, 0), (0, 0), (k, 1)]
    elif kind == "rightArrow":
        k = (neck / w, "Controls.Neck.X/Width")
        y = (shoulder / h, "Controls.Neck.Y/Height")
        top = (1 - y[0], "1-Controls.Neck.Y/Height")
        path = [(0, y), (k, y), (k, 0), (1, 0.5), (k, 1), (k, top), (0, top), (0, y)]
    elif kind in ("line", "straightConnector1"):
        cell(g, "NoFill", 1)
        path = [(0, 0), (1, 0)]
    elif kind == "bentConnector2":
        cell(g, "NoFill", 1)
        path = [(0, 1), (1, 1), (1, 0)]
    elif kind == "bentConnector3":
        cell(g, "NoFill", 1)
        k = adj.get("adj1", 0.5)
        path = [(0, 1), (k, 1), (k, 0), (1, 0)]
    else:
        raise ValueError(f"Unknown Visio preset: {kind}")
    for i, (x, y) in enumerate(path):
        row(g, "RelMoveTo" if i == 0 else "RelLineTo", i + 1, X=x, Y=y)


def freeform(shape, custom):
    for i, path in enumerate(custom.findall("{*}pathLst/{*}path")):
        sec = el(shape, "Section", N="Geometry", IX=i)
        w = max(1, int(path.get("w", "1")))
        h = max(1, int(path.get("h", "1")))
        if path.get("fill") == "none":
            cell(sec, "NoFill", 1)
        origin = (0, 0)
        for j, c in enumerate(path, 1):
            mode = ET.QName(c).localname
            pts = [(int(p.get("x")) / w, 1 - int(p.get("y")) / h) for p in c]
            if mode == "moveTo":
                origin = pts[0]
            if mode == "cubicBezTo":
                (a, b), (c, d), (x, y) = pts
                row(sec, "RelCubBezTo", j, X=x, Y=y, A=a, B=b, C=c, D=d)
            elif mode in ("moveTo", "lnTo", "close"):
                x, y = origin if mode == "close" else pts[0]
                row(sec, "RelMoveTo" if mode == "moveTo" else "RelLineTo", j, X=x, Y=y)
            else:
                raise ValueError(f"Unsupported ShapeSheet path command {mode}")
