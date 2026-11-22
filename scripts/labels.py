import math
from itertools import groupby
from lxml import etree as E
from pptx.util import Pt
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from geometry import avg
from math_text import elem, math_content, A14


def family(name):
    name = name.split("+")[-1]
    if name.startswith("Arial"):
        return "Arial"
    if name.startswith("CambriaMath"):
        return "Cambria Math"
    if name.startswith("MicrosoftYaHei"):
        return "Microsoft YaHei"
    if name.startswith("TimesNewRoman"):
        return "Times New Roman"
    return name.split("-")[0].removesuffix("MT")


def setup(slide, x, y, w, h):
    shape = slide.shapes.add_textbox(Pt(x), Pt(y), Pt(max(0.1, w)), Pt(max(0.1, h)))
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    return shape


def style_run(run, g):
    run.font.name = family(g["font"])
    run.font.size = Pt(g["size"])
    run.font.bold = "Bold" in g["font"]
    run.font.italic = any(x in g["font"] for x in ("Italic", "Oblique"))
    run.font.color.rgb = RGBColor(*g["rgb"])


def lines_of(glyphs):
    lines = []
    for g in glyphs:
        if not lines:
            lines.append([g])
            continue
        prev = lines[-1][-1]
        angle = math.radians(prev["angle"])
        dx, dy = g["x"] - prev["x"], g["y"] - prev["y"]
        along = dx * math.cos(angle) + dy * math.sin(angle)
        across = -dx * math.sin(angle) + dy * math.cos(angle)
        if (
            abs(across) > max(0.22, g["size"] * 0.045)
            or along < -0.2
            or along - prev["advance"] > max(3, prev["size"] * 0.55)
        ):
            lines.append([g])
        else:
            lines[-1].append(g)
    return lines


def add_line(slide, chars):
    first = chars[0]
    size = max(g["size"] for g in chars)
    origin = first["x"], first["y"]
    angle = math.radians(first["angle"])
    u = (math.cos(angle), math.sin(angle))
    last = chars[-1]
    width = (
        (last["x"] - origin[0]) * u[0]
        + (last["y"] - origin[1]) * u[1]
        + last["advance"]
    )
    height = 1.35 * size
    width = max(0.1, width + size * 0.28)
    offset = (0.94 if family(first["font"]) == "Cambria Math" else 0.905) * size
    # Rotate the text frame about its center while holding the PDF baseline fixed.
    center = (
        origin[0] + u[0] * width / 2 - u[1] * (height / 2 - offset),
        origin[1] + u[1] * width / 2 + u[0] * (height / 2 - offset),
    )
    shape = setup(slide, center[0] - width / 2, center[1] - height / 2, width, height)
    shape.rotation = first["angle"] % 360
    para = shape.text_frame.paragraphs[0]
    para.space_before = para.space_after = Pt(0)
    for _, chunk in groupby(
        chars, key=lambda g: (g["font"], round(g["size"], 2), g["rgb"])
    ):
        gs = list(chunk)
        run = para.add_run()
        run.text = "".join(g["s"] for g in gs)
        style_run(run, gs[0])
    return shape


def equation_coordinates(glyphs):
    first = glyphs[0]
    angle = math.radians(first["angle"])
    cosine, sine = math.cos(angle), math.sin(angle)
    local = []
    for g in glyphs:
        if (
            abs((g["angle"] - first["angle"] + 180) % 360 - 180) > 0.1
            or not 0.94 < g.get("aspect", 1) < 1.06
        ):
            return None
        dx, dy = g["x"] - first["x"], g["y"] - first["y"]
        local.append(dict(g, x=cosine * dx + sine * dy, y=-sine * dx + cosine * dy))
    return local


def equation_frame(glyphs, local, containers, size):
    boxes = []
    for g in local:
        if not g["s"].strip():
            continue
        l, t, r, b = g.get(
            "ink_offsets", (0, -0.70 * g["size"], g["advance"], 0.12 * g["size"])
        )
        boxes.append((g["x"] + l, g["y"] + t, g["x"] + r, g["y"] + b))
    l = min(b[0] for b in boxes)
    t = min(b[1] for b in boxes)
    r = max(b[2] for b in boxes)
    b = max(b[3] for b in boxes)
    first = glyphs[0]
    theta = math.radians(first["angle"])
    co, si = math.cos(theta), math.sin(theta)

    def absolute(x, y):
        return first["x"] + co * x - si * y, first["y"] + si * x + co * y

    cx, cy = absolute((l + r) / 2, (t + b) / 2)
    pad = 0.1 * size
    # Expand symmetrically only into space that was available around the PDF
    # ink. This preserves labels intentionally placed outside a panel.
    corners = [absolute(x, y) for x in (l, r) for y in (t, b)]
    x0 = min(q[0] for q in corners)
    x1 = max(q[0] for q in corners)
    y0 = min(q[1] for q in corners)
    y1 = max(q[1] for q in corners)
    for x, y, w, h in containers:
        if x <= x0 and y <= y0 and x1 <= x + w and y1 <= y + h:
            pad = min(
                pad, min(x0 - x, x + w - x1, y0 - y, y + h - y1) / (abs(co) + abs(si))
            )
    w = r - l + 2 * pad
    h = b - t + 2 * pad
    return cx - w / 2, cy - h / 2, w, h


def add_label(slide, items, accents, allow_math, containers):
    glyphs = [i.data for i in items]
    local = equation_coordinates(glyphs) if allow_math else None
    usable = math_content(local, accents) if local else None
    if usable and len(glyphs) == 1 and glyphs[0]["s"] in ("⋱", "Σ", "t"):
        usable = None
    if usable:
        math_node, size, base = usable
        shape = setup(slide, *equation_frame(glyphs, local, containers, size))
        shape.rotation = glyphs[0]["angle"] % 360
        shape.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = shape.text_frame.paragraphs[0]
        para.space_before = para.space_after = Pt(0)
        para.alignment = PP_ALIGN.CENTER
        para.font.name = "Cambria Math"
        para.font.size = Pt(size)
        end = para._p.get_or_add_endParaRPr()
        end.set("sz", str(round(size * 100)))
        math = E.Element("{%s}m" % A14, nsmap={"a14": A14, "m": math_node.nsmap["m"]})
        para._p.insert(para._p.index(end), math)
        block = elem(math_node.nsmap["m"], "oMathPara", math)
        block.append(math_node)
        return [shape], "OMML"
    if any(g["s"] == "\ufffd" for g in glyphs):
        glyphs = [
            (
                dict(g, s=accents.get((g["font"], g["cid"]), g["s"]))
                if g["s"] == "\ufffd"
                else g
            )
            for g in glyphs
        ]
    lines = lines_of(glyphs)
    shapes = [
        add_line(slide, line) for line in lines if any(c["s"].strip() for c in line)
    ]
    return shapes, (
        "positioned math text"
        if any(family(g["font"]) == "Cambria Math" for g in glyphs)
        else "text"
    )


def join(slide, shapes, name):
    if not shapes:
        return
    shape = slide.shapes.add_group_shape(shapes) if len(shapes) > 1 else shapes[0]
    shape.name = name
    return shape
