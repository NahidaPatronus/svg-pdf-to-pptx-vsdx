"""Lengths, viewport transforms and the SVG presentation cascade."""

import math
import re
from fontTools.misc.transform import Identity, Transform
from PIL import ImageColor

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
UNITS = {
    "": 1,
    "px": 1,
    "pt": 96 / 72,
    "in": 96,
    "pc": 16,
    "mm": 96 / 25.4,
    "cm": 96 / 2.54,
    "q": 96 / 101.6,
}
DEFAULTS = {
    "fill": "black",
    "stroke": "none",
    "stroke-width": "1",
    "color": "black",
    "font-family": "sans-serif",
    "font-size": "16",
    "font-weight": "normal",
    "font-style": "normal",
    "text-anchor": "start",
    "visibility": "visible",
}
INHERITED = set(DEFAULTS) | set(
    "fill-opacity stroke-opacity fill-rule stroke-dasharray stroke-linejoin stroke-linecap stroke-dashoffset marker-start marker-end marker-mid dominant-baseline".split()
)
PROPS = INHERITED | set(
    "display opacity vector-effect baseline-shift clip-path mask filter".split()
)


def numbers(value):
    return [float(x) for x in re.findall(NUMBER, str(value))]


def length(value, percent=0, em=16):
    m = re.fullmatch(r"\s*(" + NUMBER + r")([a-zA-Z%]*)\s*", str(value))
    if not m:
        raise ValueError(f"Unsupported SVG length {value!r}")
    unit = m[2].lower()
    if unit == "%":
        return float(m[1]) * percent / 100
    if unit in ("em", "ex"):
        return float(m[1]) * em * (0.5 if unit == "ex" else 1)
    if unit not in UNITS:
        raise ValueError(f"Unsupported SVG unit {unit!r}")
    return float(m[1]) * UNITS[unit]


def transform(value):
    out = Identity
    for m in re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", value or ""):
        op = m[1]
        v = numbers(m[2])
        if op == "matrix" and len(v) == 6:
            t = Transform(*v)
        elif op == "translate" and len(v) in (1, 2):
            t = Identity.translate(v[0], v[1] if len(v) > 1 else 0)
        elif op == "scale" and len(v) in (1, 2):
            t = Identity.scale(*v)
        elif op == "rotate" and len(v) in (1, 3):
            x, y = v[1:] if len(v) == 3 else (0, 0)
            t = Identity.translate(x, y).rotate(math.radians(v[0])).translate(-x, -y)
        elif op in ("skewX", "skewY") and len(v) == 1:
            t = Identity.skew(
                math.radians(v[0]) if op == "skewX" else 0,
                math.radians(v[0]) if op == "skewY" else 0,
            )
        else:
            raise ValueError(f"Unsupported transform {m[0]}")
        out = out.transform(t)
    if re.sub(r"([A-Za-z]+)\s*\(([^)]*)\)", "", value or "").strip(" ,\t\r\n"):
        raise ValueError(f"Malformed transform {value}")
    return out


def viewport(box, w, h, aspect):
    x, y, bw, bh = box
    if min(w, h, bw, bh) <= 0:
        raise ValueError("SVG viewport must have positive dimensions")
    sx, sy = w / bw, h / bh
    align, _, mode = (aspect or "xMidYMid meet").strip().partition(" ")
    if align == "none":
        return Identity.scale(sx, sy).translate(-x, -y)
    scale = max(sx, sy) if mode == "slice" else min(sx, sy)
    ax = 1 if "xMax" in align else 0.5 if "xMid" in align else 0
    ay = 1 if "YMax" in align else 0.5 if "YMid" in align else 0
    return (
        Identity.translate((w - scale * bw) * ax, (h - scale * bh) * ay)
        .scale(scale)
        .translate(-x, -y)
    )


def color(value):
    if value == "none":
        return None
    return ImageColor.getrgb(value)[:3]


def alpha(value):
    value = str(value).strip()
    return max(
        0, min(1, float(value[:-1]) / 100 if value.endswith("%") else float(value))
    )


def declarations(raw):
    return {
        k.strip(): v.strip()
        for s in raw.split(";")
        if ":" in s
        for k, v in [s.split(":", 1)]
    }


class Cascade:
    def __init__(self, root, warnings):
        self.rules = []
        for node in root.xpath('.//*[local-name()="style"]'):
            body = re.sub(r"/\*.*?\*/", "", node.text or "", flags=re.S)
            for sels, props in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
                for sel in sels.split(","):
                    sel = sel.strip()
                    if not re.fullmatch(r"(?:\*|[\w-]+)?(?:[.#][\w-]+)*", sel):
                        warnings.add(f"Unsupported CSS selector {sel!r}")
                        continue
                    parts = re.findall(r"[.#][\w-]+|^[\w*-]+", sel)
                    priority = (
                        sum(p[0] == "#" for p in parts),
                        sum(p[0] == "." for p in parts),
                        sum(p[0] not in "#.*" for p in parts),
                    )
                    self.rules.append(
                        (priority, len(self.rules), parts, declarations(props))
                    )
        self.rules.sort()

    def style(self, node, parent):
        s = {k: v for k, v in parent.items() if k in INHERITED}
        attrs = node.attrib
        raw = {k: v for k, v in attrs.items() if k in PROPS}
        keys = {node.tag.split("}")[-1], "*", "#" + attrs.get("id", "")} | {
            "." + c for c in attrs.get("class", "").split()
        }
        for _, _, parts, props in self.rules:
            if all(p in keys for p in parts):
                raw.update(props)
        raw.update(declarations(attrs.get("style", "")))
        for k, v in raw.items():
            if v == "inherit":
                s[k] = parent.get(k, DEFAULTS.get(k, ""))
            else:
                s[k] = v
        if "font-size" in raw:
            s["font-size"] = str(
                length(
                    s["font-size"],
                    float(parent.get("font-size", 16)),
                    float(parent.get("font-size", 16)),
                )
            )
        for k in ("fill", "stroke"):
            if s.get(k) == "currentColor":
                s[k] = s.get("color", "black")
        return s
