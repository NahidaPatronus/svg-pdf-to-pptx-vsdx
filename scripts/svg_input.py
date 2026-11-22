"""Build a slide directly from SVG XML. Coordinates are resolved into slide points."""

import base64
from collections import Counter
from io import BytesIO
import math
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit
from fontTools.misc.transform import Identity
from lxml import etree as ET
from PIL import Image
from pptx.util import Pt
from geometry import poly, bounds
from labels import join
from office_shapes import add_path, add_picture
from pdf_input import Item
from svg_geometry import name, contour, transformed, geometry
from svg_markers import markers, fragment
from svg_gradient import apply_gradient
from svg_style import (
    DEFAULTS,
    Cascade,
    alpha,
    color,
    length,
    numbers,
    transform,
    viewport,
)
from svg_text import draw_text

DRAWABLE = {"line", "polyline", "polygon", "rect", "circle", "ellipse", "path"}
SKIP = {
    "title",
    "desc",
    "metadata",
    "defs",
    "style",
    "marker",
    "symbol",
    "clipPath",
    "mask",
    "pattern",
    "linearGradient",
    "radialGradient",
    "script",
}


def href(node):
    return node.get("href", node.get("{http://www.w3.org/1999/xlink}href", ""))


def image_data(node, folder):
    ref = href(node)
    if ref.startswith("data:"):
        header, payload = ref.split(",", 1)
        data = (
            base64.b64decode(payload)
            if ";base64" in header
            else unquote_to_bytes(payload)
        )
        with Image.open(BytesIO(data)) as im:
            return im.convert("RGBA")
    u = urlsplit(ref)
    if u.scheme or u.netloc or u.fragment:
        raise ValueError("SVG images must be embedded or local relative files.")
    from urllib.parse import unquote

    path = Path(unquote(u.path))
    if path.is_absolute():
        raise ValueError("Use relative paths for local SVG images.")
    with Image.open(folder / path) as im:
        return im.convert("RGBA")


class SVGSlide:
    def __init__(self, root, folder):
        self.root = root
        self.folder = folder
        self.ids = {
            el.get("id"): el
            for el in root.iter()
            if isinstance(el.tag, str) and el.get("id")
        }
        self.warnings = set()
        self.cascade = Cascade(root, self.warnings)
        self.counts = Counter()
        self.detail = []
        self.edges = []
        self.nodes = []
        box = numbers(root.get("viewBox", ""))
        if box and len(box) != 4:
            raise ValueError("Malformed SVG viewBox")
        fw, fh = box[2:] if box else (300, 150)
        self.width = length(root.get("width", fw), fw)
        self.height = length(root.get("height", fh), fh)
        self.box = box or (0, 0, self.width, self.height)

    def record(self, shape, node, kind, **extra):
        if node.get("id"):
            shape.name = node.get("id")
        self.counts[kind] += 1
        self.detail.append(
            dict(id=shape.shape_id, source=name(node), type=kind, **extra)
        )
        return shape

    def path(self, node, s, t, view, opacity):
        local = contour(node, view)
        if not local or len(local) < 2:
            return []
        cmds = transformed(local, t)
        scale = math.sqrt(abs(t.xx * t.yy - t.xy * t.yx))
        diag = math.hypot(*view) / math.sqrt(2)
        stroke_scale = 0.75 if s.get("vector-effect") == "non-scaling-stroke" else scale
        width = length(s.get("stroke-width", 1), diag) * stroke_scale
        paint = s.get("fill", "black") if name(node) != "line" else "none"
        gradient = fragment(paint) if paint.startswith("url(") else None
        fill = (0, 0, 0) if gradient else color(paint)
        stroke = color(s.get("stroke", "none")) if width > 0 else None
        if fill is None and stroke is None:
            return []
        ds = s.get("stroke-dasharray", "none")
        import re

        dash = (
            []
            if ds == "none"
            else [
                length(v, diag) * stroke_scale
                for v in re.split(r"[,\s]+", ds.strip())
                if v
            ]
        )
        st = dict(
            fill=fill,
            stroke=stroke,
            width=max(0.001, width),
            dash=dash,
            ca=opacity * alpha(s.get("fill-opacity", 1)),
            CA=opacity * alpha(s.get("stroke-opacity", 1)),
            cap={"round": "rnd", "square": "sq", "butt": "flat"}[
                s.get("stroke-linecap", "butt")
            ],
            join={"round": "round", "bevel": "bevel", "miter": "miter"}[
                s.get("stroke-linejoin", "miter")
            ],
        )
        if s.get("fill-rule") == "evenodd" and sum(c[0] == "m" for c in local) > 1:
            self.warnings.add(
                "Check holes in compound paths using the evenodd fill rule."
            )
        if s.get("stroke-dashoffset", "0") not in ("0", "0px"):
            self.warnings.add("PowerPoint dash patterns start at zero phase.")
        if s.get("marker-mid", "none") != "none":
            raise ValueError("SVG mid-path markers need separate symbols.")
        markers(cmds, s, t, st, self.ids, self.cascade)
        geom = geometry(node, local, cmds, t, fill)
        if geom is None or not max(geom.box[2:]):
            return []
        if geom.kind == "line" and len(poly(cmds)) != 2:
            return []
        shape, _ = add_path(self.slide, Item("path", None, cmds, st), geom)
        if gradient:
            box = bounds(p for cmd in local for p in cmd[1:])
            apply_gradient(
                shape,
                self.ids.get(gradient),
                self.cascade,
                box,
                t,
                geom,
                view,
                st["ca"],
            )
        ends = {k: st[k] for k in ("start", "end") if k in st}
        kind = geom.kind + (" arrow" if ends else "")
        self.record(shape, node, kind, box=geom.box, ends=ends)
        if geom.kind == "line" and ends:
            self.edges.append((shape, poly(cmds)))
        if geom.kind in ("rect", "roundRect") and not geom.angle:
            self.nodes.append((shape, geom))
        return [shape]

    def picture(self, node, t, view, opacity):
        image = image_data(node, self.folder)
        if opacity < 1:
            image.putalpha(image.getchannel("A").point(lambda n: round(n * opacity)))
        x, y, w, h = [
            length(node.get(k, 0), view[i % 2])
            for i, k in enumerate(("x", "y", "width", "height"))
        ]
        if min(w, h) <= 0:
            return []
        aspect = node.get("preserveAspectRatio", "xMidYMid meet")
        v = viewport((0, 0, *image.size), w, h, aspect)
        if "slice" in aspect:
            a, b = v.inverse().transformPoint((0, 0))
            c, d = v.inverse().transformPoint((w, h))
            image = image.crop((round(a), round(b), round(c), round(d)))
            v = viewport((0, 0, *image.size), w, h, "none")
        image_t = t.translate(x, y).transform(v)
        basis = [
            image_t.transformPoint(p)
            for p in ((0, 0), (image.width, 0), (0, image.height))
        ]
        obj = add_picture(self.slide, Item("image", None, (image, basis)))
        return [self.record(obj, node, "picture")]

    def walk(self, node, parent, t, view, opacity, visited=()):
        if not isinstance(node.tag, str):
            return []
        kind = name(node)
        if kind in SKIP:
            return []
        s = self.cascade.style(node, parent)
        if s.get("display") == "none":
            return []
        t = t.transform(transform(node.get("transform")))
        opacity *= alpha(s.get("opacity", 1))
        if opacity <= 0 or abs(t.xx * t.yy - t.xy * t.yx) < 1e-12:
            return []
        for k in ("clip-path", "filter", "mask"):
            if s.get(k, "none") != "none":
                raise ValueError(f"Unsupported SVG {k} on {node.get('id') or kind}")
        if kind in ("svg", "g", "a", "switch"):
            if kind == "switch":
                raise ValueError("SVG conditional switch requires a selected branch.")
            if kind == "svg" and node is not self.root:
                w = length(node.get("width", "100%"), view[0])
                h = length(node.get("height", "100%"), view[1])
                if min(w, h) <= 0:
                    return []
                box = numbers(node.get("viewBox", f"0 0 {w} {h}"))
                t = t.translate(
                    length(node.get("x", 0), view[0]), length(node.get("y", 0), view[1])
                ).transform(viewport(box, w, h, node.get("preserveAspectRatio")))
                view = box[2:]
            if alpha(s.get("opacity", 1)) < 1 and len(node) > 1:
                self.warnings.add(
                    "Group opacity is applied per object; overlapping translucent objects may differ."
                )
            shapes = [
                sh
                for child in node
                for sh in self.walk(child, s, t, view, opacity, visited)
            ]
            if kind == "g" and len(shapes) > 1:
                return [join(self.slide, shapes, node.get("id", "SVG group"))]
            return shapes
        if kind == "use":
            key = href(node)
            if not key.startswith("#") or key[1:] not in self.ids:
                raise ValueError(f"Unknown local SVG use reference {key!r}")
            if key in visited:
                raise ValueError("Circular SVG use reference")
            ref = self.ids[key[1:]]
            t = t.translate(
                length(node.get("x", 0), view[0]), length(node.get("y", 0), view[1])
            )
            if name(ref) == "symbol":
                box = numbers(ref.get("viewBox", f"0 0 {view[0]} {view[1]}"))
                w = length(node.get("width", box[2]), view[0])
                h = length(node.get("height", box[3]), view[1])
                t = t.transform(viewport(box, w, h, ref.get("preserveAspectRatio")))
                rs = self.cascade.style(ref, s)
                return [
                    sh
                    for child in ref
                    for sh in self.walk(
                        child, rs, t, box[2:], opacity, visited + (key,)
                    )
                ]
            return self.walk(ref, s, t, view, opacity, visited + (key,))
        if s.get("visibility") in ("hidden", "collapse"):
            return []
        if kind in DRAWABLE:
            return self.path(node, s, t, view, opacity)
        if kind == "text":
            return [
                self.record(sh, node, "text")
                for sh in draw_text(
                    self.slide, node, s, t, self.cascade, view, opacity, self.warnings
                )
            ]
        if kind == "image":
            return self.picture(node, t, view, opacity)
        raise ValueError(f"Unsupported SVG element <{kind}>")


def svg_slide(deck, source, bind_edges):
    root = ET.parse(
        str(source),
        ET.XMLParser(resolve_entities=False, no_network=True, remove_comments=True),
    ).getroot()
    if name(root) != "svg":
        raise ValueError("Expected an SVG root element")
    page = SVGSlide(root, Path(source).parent)
    w, h = page.width * 0.75, page.height * 0.75
    if min(w, h) <= 0:
        raise ValueError("SVG slide dimensions must be positive.")
    scale = min(max(1, 72 / min(w, h)), 4032 / max(w, h))
    sw, sh = max(72, w * scale), max(72, h * scale)
    deck.slide_width, deck.slide_height = Pt(sw), Pt(sh)
    if scale != 1 or sw != w or sh != h:
        page.warnings.add("SVG fitted uniformly to PowerPoint slide-size limits.")
    page.slide = deck.slides.add_slide(deck.slide_layouts[6])
    t = (
        Identity.translate((sw - w * scale) / 2, (sh - h * scale) / 2)
        .scale(0.75 * scale)
        .transform(
            viewport(page.box, page.width, page.height, root.get("preserveAspectRatio"))
        )
    )
    page.walk(root, DEFAULTS, t, page.box[2:], 1)
    if not page.detail:
        raise ValueError("The SVG contains no visible objects")
    return dict(
        format="svg",
        objects=dict(page.counts),
        detail=page.detail,
        bound_arrows=bind_edges(page.edges, page.nodes) if bind_edges else [],
        warnings=sorted(page.warnings),
    )
