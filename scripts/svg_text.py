"""Represent SVG text chunks as anchored, editable, mixed-script PowerPoint text."""

import math
import re
import unicodedata
from itertools import groupby
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Pt
from labels import setup
from math_text import VISIO_MATH_ASCENT
from office_shapes import tag
from svg_style import length, color, alpha

GENERIC = {
    "serif": "Times New Roman",
    "sans-serif": "Arial",
    "monospace": "Courier New",
}


def font_names(style):
    names = [x.strip().strip("'\"") for x in style["font-family"].split(",")]
    latin = GENERIC.get(names[0], names[0])
    ea_names = (
        "simsun",
        "simhei",
        "yahei",
        "dengxian",
        "mingliu",
        "jhenghei",
        "songti",
        "heiti",
        "fangsong",
        "kaiti",
        "cjk",
        "source han",
        "pingfang",
        "hiragino",
        "meiryo",
        "gothic",
        "mincho",
        "malgun",
        "batang",
        "宋体",
        "黑体",
        "楷体",
        "明體",
        "思源",
        "微软雅黑",
    )
    east = next((n for n in names if any(k in n.lower() for k in ea_names)), None)
    return latin, east or (
        latin
        if latin not in GENERIC.values()
        else ("SimSun" if latin == "Times New Roman" else "Microsoft YaHei")
    )


def script_runs(runs):
    # Some PPT renderers ignore a:ea on mixed-script runs. Preserve the
    # original textbox while assigning the East Asian face to both font slots.
    def east_asian(c):
        u = ord(c)
        return (
            0x2E80 <= u <= 0xA4CF
            or 0xAC00 <= u <= 0xD7FF
            or 0xF900 <= u <= 0xFAFF
            or 0xFE10 <= u <= 0xFE6F
            or 0xFF01 <= u <= 0xFFEE
            or 0x20000 <= u <= 0x323AF
        )

    for text, st in runs:
        latin, east = font_names(st)
        for cjk, part in groupby(text, key=east_asian):
            yield "".join(part), st, east if cjk else latin, east


def chunks(root, style, cascade, view, warnings):
    cursor = [0.0, 0.0]
    runs = []
    result = []

    def flush():
        if runs:
            result.append((origin[0], origin[1], list(runs)))
            runs.clear()

    origin = [0.0, 0.0]

    def emit(text, s, preserve):
        if not text:
            return
        if not preserve:
            text = re.sub(r"[ \t\r\n]+", " ", text)
            if not runs:
                text = text.lstrip(" ")
            elif runs[-1][0].endswith(" "):
                text = text.lstrip(" ")
        if not text:
            return
        runs.append((text, s))
        # Only used when a later tspan explicitly shifts the pen.
        sz = float(s["font-size"])
        cursor[0] += (
            sum(1 if unicodedata.east_asian_width(c) in "WF" else 0.55 for c in text)
            * sz
        )

    def walk(n, s, preserve):
        preserve = (
            n.get(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve" if preserve else "default",
            )
            == "preserve"
        )
        if any(k in n.attrib for k in ("x", "y", "dx", "dy")):
            flush()
            for k, idx, relative in (
                ("x", 0, False),
                ("y", 1, False),
                ("dx", 0, True),
                ("dy", 1, True),
            ):
                if k in n.attrib:
                    vs = re.split(r"[,\s]+", n.get(k).strip())
                    if len(vs) > 1:
                        warnings.add(
                            "Per-character SVG text positioning uses the first coordinate."
                        )
                    value = length(vs[0], view[idx], float(s["font-size"]))
                    cursor[idx] = cursor[idx] + value if relative else value
            origin[:] = cursor
        emit(n.text, s, preserve)
        for child in n:
            if isinstance(child.tag, str) and child.tag.split("}")[-1] == "tspan":
                walk(child, cascade.style(child, s), preserve)
            elif isinstance(child.tag, str) and child.tag.split("}")[-1] not in (
                "title",
                "desc",
            ):
                raise ValueError(f"Unsupported element inside SVG text: {child.tag}")
            emit(child.tail, s, preserve)

    walk(root, style, False)
    flush()
    return result


def draw_text(slide, node, s, t, cascade, view, opacity, warnings, visio=False):
    result = []
    sx = math.hypot(t.xx, t.xy)
    sy = math.hypot(t.yx, t.yy)
    if not min(sx, sy):
        return []
    if (
        abs(sx - sy) > 0.01 * max(sx, sy)
        or abs(t.xx * t.yx + t.xy * t.yy) > 0.01 * sx * sy
    ):
        warnings.add("Text uses a nonuniform transform; check glyph width and slant.")
    co, si = t.xx / sx, t.xy / sx
    for x, y, runs in chunks(node, s, cascade, view, warnings):
        anchor = runs[0][1].get("text-anchor", "start")
        size = max(float(st["font-size"]) * sy for _, st in runs)
        if size <= 0:
            continue
        width = max(
            size,
            sum(
                sum(
                    1 if unicodedata.east_asian_width(c) in "WF" else 0.72 for c in text
                )
                * float(st["font-size"])
                * sx
                for text, st in runs
            )
            + size * 0.35,
        )
        h = 1.4 * size
        anchor_offset = {"start": 0, "middle": width / 2, "end": width}[anchor]
        baseline = runs[0][1].get("dominant-baseline", "alphabetic")
        # SVG y is a baseline. Account for the line box above that baseline
        # when anchoring a PowerPoint paragraph with zero top inset.
        offset = {
            "middle": 0.56,
            "central": 0.62,
            "hanging": 0.2,
            "text-before-edge": 0,
        }.get(baseline, 1.0) * size
        if visio and baseline in ("auto", "alphabetic") and all(
            font_names(st)[0].replace(" ", "").lower() == "cambriamath" for _, st in runs
        ):
            offset = VISIO_MATH_ASCENT * size
        px, py = t.transformPoint((x, y))
        cx = px + co * (width / 2 - anchor_offset) - si * (h / 2 - offset)
        cy = py + si * (width / 2 - anchor_offset) + co * (h / 2 - offset)
        shape = setup(slide, cx - width / 2, cy - h / 2, width, h)
        shape.rotation = math.degrees(math.atan2(si, co)) % 360
        p = shape.text_frame.paragraphs[0]
        p.space_before = p.space_after = Pt(0)
        p.alignment = {
            "start": PP_ALIGN.LEFT,
            "middle": PP_ALIGN.CENTER,
            "end": PP_ALIGN.RIGHT,
        }[anchor]
        for text, st, latin, east in script_runs(runs):
            run = p.add_run()
            run.text = text
            f = run.font
            f.name = latin
            f.size = Pt(float(st["font-size"]) * sy)
            weight = st.get("font-weight", "normal")
            f.bold = (
                weight in ("bold", "bolder") or weight.isdigit() and int(weight) >= 600
            )
            f.italic = st.get("font-style") in ("italic", "oblique")
            fill = st.get("fill", "black")
            rgb = color(fill)
            f.color.rgb = RGBColor(*(rgb or (0, 0, 0)))
            rp = run._r.get_or_add_rPr()
            alpha_value = opacity * alpha(st.get("fill-opacity", 1)) if rgb else 0
            if alpha_value < 1:
                tag(
                    rp.find("{*}solidFill/{*}srgbClr"),
                    "a:alpha",
                    val=round(100000 * alpha_value),
                )
            tag(rp, "a:ea", typeface=east)
            shift = st.get("baseline-shift")
            if shift and shift not in ("baseline", "0"):
                em = float(st["font-size"])
                dy = (
                    em * (0.35 if shift == "super" else -0.2)
                    if shift in ("super", "sub")
                    else length(shift, em, em)
                )
                rp.set("baseline", str(round(100000 * dy / em)))
        shape.name = node.get("id") or "".join(tx for tx, _ in runs)[:64]
        result.append(shape)
    return result
