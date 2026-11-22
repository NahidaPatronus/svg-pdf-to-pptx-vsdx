"""Translate DrawingML formatting to native Visio shape and character cells."""

import math
from visio_geometry import cell, cells, el

EMU = 914400


def rgb(parent, default="#000000"):
    sc = parent.find("{*}srgbClr") if parent is not None else None
    if sc is None:
        return default, 0
    opacity = sc.find("{*}alpha")
    return "#" + sc.get("val"), (
        1 - int(opacity.get("val")) / 100000 if opacity is not None else 0
    )


def appearance(shape, sp, warnings):
    solid = sp.find("{*}solidFill")
    gradient = sp.find("{*}gradFill")
    color, trans = rgb(solid)
    cells(
        shape,
        FillPattern=int(solid is not None or gradient is not None),
        FillForegnd=color,
        FillForegndTrans=trans,
    )
    if gradient is not None:
        stops = gradient.findall("{*}gsLst/{*}gs")
        lin = gradient.find("{*}lin")
        cells(
            shape,
            FillGradientEnabled=1,
            FillGradientDir=0,
            FillGradientAngle=(
                -math.radians(int(lin.get("ang", "0")) / 60000)
                if lin is not None
                else 0
            ),
        )
        section = el(shape, "Section", N="FillGradient")
        for i, stop in enumerate(stops):
            r = el(section, "Row", IX=i)
            c, a = rgb(stop)
            cells(
                r,
                GradientStopColor=c,
                GradientStopColorTrans=a,
                GradientStopPosition=int(stop.get("pos")) / 100000,
            )
    ln = sp.find("{*}ln")
    stroke = ln.find("{*}solidFill") if ln is not None else None
    if stroke is None:
        cell(shape, "LinePattern", 0)
        return
    c, a = rgb(stroke)
    dash = ln.find("{*}prstDash")
    custom = ln.find("{*}custDash")
    pattern = 1
    if dash is not None:
        pattern = {
            "dot": 3,
            "sysDot": 3,
            "dash": 2,
            "sysDash": 2,
            "lgDash": 2,
            "dashDot": 4,
        }.get(dash.get("val"), 1)
    if custom is not None:
        pairs = custom.findall("{*}ds")
        pattern = 3 if pairs and int(pairs[0].get("d")) <= 100000 else 2
        warnings.add("Visio uses a native dash pattern for custom dash lengths.")
    cells(
        shape,
        LinePattern=pattern,
        LineColor=c,
        LineColorTrans=a,
        LineWeight=int(ln.get("w", "12700")) / EMU,
        LineCap={"rnd": 0, "sq": 1, "flat": 2}.get(ln.get("cap"), 2),
    )
    for tag, name in (("headEnd", "Begin"), ("tailEnd", "End")):
        nd = ln.find("{*}" + tag)
        if nd is None:
            continue
        style = nd.get("type")
        if style == "diamond":
            warnings.add("Diamond line ends use Visio's open diamond.")
        cell(
            shape,
            name + "Arrow",
            {"triangle": 2, "arrow": 1, "oval": 10, "diamond": 22, "none": 0}.get(
                style, 2
            ),
        )
        cell(
            shape,
            name + "ArrowSize",
            {"sm": 0, "med": 2, "lg": 4}.get(nd.get("len", "med"), 2),
        )


def text_block(shape, body, faces):
    paras = body.findall("{*}p")
    if not any(p.find(".//{*}t") is not None for p in paras):
        return False
    bodypr = body.find("{*}bodyPr")
    cells(
        shape,
        LeftMargin=0,
        RightMargin=0,
        TopMargin=0,
        BottomMargin=0,
        VerticalAlign={"t": 0, "ctr": 1, "b": 2}.get(bodypr.get("anchor", "t"), 0),
    )
    characters = el(shape, "Section", N="Character")
    paragraphs = el(shape, "Section", N="Paragraph")
    txt = el(shape, "Text")
    styles = {}
    for pi, p in enumerate(paras):
        pp = p.find("{*}pPr")
        pr = el(paragraphs, "Row", IX=pi)
        cells(
            pr,
            HorzAlign={"l": 0, "ctr": 1, "r": 2}.get(
                pp.get("algn", "l") if pp is not None else "l", 0
            ),
            IndFirst=0,
            IndLeft=0,
            IndRight=0,
            SpBefore=0,
            SpAfter=0,
            SpLine=-1,
        )
        el(txt, "pp", IX=pi)
        for r in p.findall("{*}r"):
            chars = r.findtext("{*}t", "")
            rp = r.find("{*}rPr")
            if not chars or rp is None:
                continue
            latin = rp.find("{*}latin")
            ea = rp.find("{*}ea")
            font = latin.get("typeface") if latin is not None else "Arial"
            east = ea.get("typeface") if ea is not None else font
            faces.update((font, east))
            co, tr = rgb(rp.find("{*}solidFill"))
            shift = int(rp.get("baseline", "0"))
            pos = 1 if shift > 0 else 2 if shift < 0 else 0
            args = dict(
                Font=font,
                AsianFont=east,
                Size=int(rp.get("sz", "1200")) / 7200,
                Style=int(rp.get("b") == "1") + 2 * int(rp.get("i") == "1"),
                Color=co,
                ColorTrans=tr,
                Pos=pos,
            )
            key = tuple(args.values())
            if key not in styles:
                idx = styles[key] = len(styles)
                row = el(characters, "Row", IX=idx)
                cells(row, **args)
            el(txt, "cp", IX=styles[key]).tail = chars
        if pi + 1 < len(paras):
            last = txt[-1]
            last.tail = (last.tail or "") + "\n"
    return True
