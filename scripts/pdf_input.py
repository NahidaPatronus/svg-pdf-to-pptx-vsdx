"""Capture ordered paths, glyphs and images in page coordinates (points, y down)."""

import math
from dataclasses import dataclass, field
from pdfminer.pdfdevice import PDFTextDevice
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import literal_name
from pdfminer.utils import apply_matrix_pt
from pdfminer.pdffont import PDFUnicodeNotDefined
from pypdf import PdfReader
from pypdf.generic import IndirectObject


@dataclass
class Item:
    kind: str
    owner: object
    data: object
    style: dict = field(default_factory=dict)


def color(value):
    v = value if isinstance(value, (tuple, list)) else (value,)
    if len(v) == 1:
        v = v * 3
    if len(v) == 4:
        v = tuple((1 - x) * (1 - v[3]) for x in v[:3])
    return tuple(round(255 * min(1, max(0, x))) for x in v[:3])


class Interpreter(PDFPageInterpreter):
    def init_state(self, ctm):
        super().init_state(ctm)
        self.opacity_stack = []
        self.device.opacity = (1.0, 1.0)

    def do_q(self):
        super().do_q()
        self.opacity_stack.append(self.device.opacity)

    def do_Q(self):
        super().do_Q()
        if self.opacity_stack:
            self.device.opacity = self.opacity_stack.pop()

    def do_gs(self, name):
        states = resolve1(self.resources.get("ExtGState", {}))
        state = resolve1(states.get(literal_name(name), {}))
        ca, CA = self.device.opacity
        self.device.opacity = float(state.get("ca", ca)), float(state.get("CA", CA))
        if "BM" in state and literal_name(state["BM"]) not in ("Normal", "Compatible"):
            self.device.warnings.add("Non-normal blend mode requires review.")

    def do_W(self):
        if "".join(op[0] for op in self.curpath) not in ("mlllh", "mllllh"):
            self.device.warnings.add("Non-rectangular clipping requires review.")

    do_W_a = do_W


class Collector(PDFTextDevice):
    def __init__(self, manager, reader, pdf_page):
        super().__init__(manager)
        self.reader, self.pdf_page = reader, pdf_page
        self.items, self.tags, self.warnings = [], [], set()
        self.opacity = (1.0, 1.0)
        self.text_mode = 0
        self.images = None

    def begin_page(self, page, ctm):
        x, y, X, Y = page.mediabox
        self.width, self.height = X - x, Y - y
        if page.rotate in (90, 270):
            self.width, self.height = self.height, self.width
        a, b, A, B = page.cropbox
        pts = [apply_matrix_pt(ctm, p) for p in ((a, b), (a, B), (A, b), (A, B))]
        self.crop = (
            min(p[0] for p in pts),
            self.height - max(p[1] for p in pts),
            max(p[0] for p in pts),
            self.height - min(p[1] for p in pts),
        )

    def begin_tag(self, tag, props=None):
        props = resolve1(props)
        self.tags.append(props.get("MCID") if isinstance(props, dict) else None)

    def end_tag(self):
        if self.tags:
            self.tags.pop()

    @property
    def owner(self):
        return next((t for t in reversed(self.tags) if t is not None), None)

    def point(self, x, y):
        a, b = apply_matrix_pt(self.ctm, (x, y))
        return a, self.height - b

    def paint_path(self, gs, stroke, fill, evenodd, path):
        cmds = []
        last = start = (0, 0)
        for op, *coords in path:
            pts = [self.point(x, y) for x, y in zip(coords[::2], coords[1::2])]
            if op == "v":
                op, pts = "c", [last] + pts
            if op == "y":
                op, pts = "c", pts + [pts[-1]]
            if op == "m":
                start = pts[0]
            last = pts[-1] if pts else start
            cmds.append((op, *pts))
        a, b, c, d, *_ = self.ctm
        scale = math.sqrt(abs(a * d - b * c))
        style = dict(
            fill=color(gs.ncolor) if fill else None,
            stroke=color(gs.scolor) if stroke else None,
            width=max(0.15, float(gs.linewidth or 0) * scale),
            dash=tuple(float(n) * scale for n in (gs.dash[0] if gs.dash else ())),
            ca=self.opacity[0],
            CA=self.opacity[1],
        )
        if cmds:
            self.items.append(Item("path", self.owner, cmds, style))

    def render_image(self, name, stream):
        if stream.objid is None:
            raise ValueError("Inline image decoding is not supported.")
        ref = IndirectObject(stream.objid, stream.genno or 0, self.reader)
        if self.images is None:
            self.images = {im.indirect_reference: im for im in self.pdf_page.images}
        entry = self.images.get(ref)
        if entry is None:
            raise ValueError(f"Unresolved PDF image {name}")
        img = entry.image.copy()
        if self.opacity[0] < 1:
            img = img.convert("RGBA")
            img.putalpha(
                img.getchannel("A").point(lambda n: round(n * self.opacity[0]))
            )
        basis = [self.point(*p) for p in ((0, 1), (1, 1), (0, 0))]
        self.items.append(Item("image", self.owner, (img, basis)))

    def render_string(self, textstate, seq, ncs, graphicstate):
        self.text_mode = textstate.render
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, gs):
        adv = font.char_width(cid) * fontsize * scaling
        if self.text_mode in (3, 7):
            return adv
        try:
            s = font.to_unichr(cid)
        except PDFUnicodeNotDefined:
            s = "\ufffd"
        if len(s) == 2 and s[0] == s[1] and ord(s[0]) > 0xFFFF:
            s = s[0]
        a, b, c, d, x, y = matrix
        name = (
            font.fontname.decode("latin1")
            if isinstance(font.fontname, bytes)
            else font.fontname
        )
        if "\ufffd" in s:
            self.warnings.add(
                "Unmapped PDF glyph %s CID %s" % (name.split("+")[-1], cid)
            )
        glyph = dict(
            s=s,
            x=x + c * rise,
            y=self.height - y - d * rise,
            advance=adv * math.hypot(a, b),
            size=abs(fontsize) * math.hypot(c, d),
            aspect=abs(scaling) * math.hypot(a, b) / max(1e-9, math.hypot(c, d)),
            font=name.split("+")[-1],
            angle=-math.degrees(math.atan2(b, a)),
            rgb=color(gs.ncolor),
            cid=cid,
        )
        self.items.append(Item("glyph", self.owner, glyph))
        return adv


def read_pages(filename):
    reader = PdfReader(str(filename))
    with open(filename, "rb") as stream:
        for index, page in enumerate(PDFPage.get_pages(stream)):
            manager = PDFResourceManager()
            device = Collector(manager, reader, reader.pages[index])
            Interpreter(manager, device).process_page(page)
            yield device
