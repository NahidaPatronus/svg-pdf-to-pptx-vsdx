"""Write the OPC parts of a standalone, macro-free Visio drawing."""

import posixpath
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET
from visio_geometry import NS, OFFICE, el, cell, cells

REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
VISREL = "http://schemas.microsoft.com/visio/2010/relationships/"
PREFIX = "application/vnd.ms-visio."


def xmlroot(name):
    node = ET.Element("{%s}%s" % (NS, name), nsmap={None: NS, "r": OFFICE})
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return node


def reference(node, rid):
    el(node, "Rel").set("{%s}id" % OFFICE, rid)


def page_size(parent, w, h):
    s = el(parent, "PageSheet", LineStyle=0, FillStyle=0, TextStyle=0)
    for name, val in (
        ("PageWidth", w),
        ("PageHeight", h),
        ("PageScale", 1),
        ("DrawingScale", 1),
    ):
        cell(s, name, val, unit="IN")
    cells(
        s,
        DrawingSizeType=0,
        DrawingScaleType=0,
        DrawingResizeType=0,
    )


def ordered(shape):
    # Visio's ShapeSheet elements put scalar cells before sections and payloads.
    positions = {
        "Cell": 0,
        "Trigger": 1,
        "Section": 2,
        "Shapes": 3,
        "Text": 4,
        "ForeignData": 7,
    }
    shape[:] = sorted(shape, key=lambda e: positions.get(ET.QName(e).localname, 8))


class Package:
    def __init__(self):
        self.parts = {}
        self.types = {}
        self.rels = {}
        self.images = {}
        self.faces = set()
        self.pages = xmlroot("Pages")
        self.windows = xmlroot("Windows")
        self.link("", "visio/document.xml", "document")
        self.link("visio/document.xml", "visio/pages/pages.xml", "pages")

    def part(self, path, kind, xml):
        self.parts[path] = xml
        self.types[path] = PREFIX + kind + "+xml"

    def link(self, source, target, kind):
        table = self.rels.setdefault(source, {})
        if target not in table:
            table[target] = (f"rId{len(table)+1}", kind)
        return table[target][0]

    def page(self, i, w, h):
        path = f"visio/pages/page{i}.xml"
        root = xmlroot("PageContents")
        self.part(path, "page", root)
        view = dict(ViewScale=-1, ViewCenterX=w / 2, ViewCenterY=h / 2)
        meta = el(
            self.pages, "Page", ID=i - 1, NameU=f"Page-{i}", Name=f"Page-{i}", **view
        )
        if i == 1:
            el(
                self.windows,
                "Window",
                ID=0,
                WindowType="Drawing",
                WindowState=1073741824,
                ContainerType="Page",
                Page=0,
                **view,
            )
        page_size(meta, w, h)
        reference(meta, self.link("visio/pages/pages.xml", path, "page"))
        return path, root

    def picture(self, s, page, blob, ext):
        path = self.images.get(blob)
        if path is None:
            path = f"visio/media/image{len(self.images)+1}.{ext}"
            self.images[blob] = path
            self.parts[path] = blob
        d = el(
            s,
            "ForeignData",
            ForeignType="Bitmap",
            CompressionType={"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}[ext],
        )
        reference(d, self.link(page, path, OFFICE + "/image"))

    def document(self):
        doc = xmlroot("VisioDocument")
        el(
            doc,
            "DocumentSettings",
            TopPage=0,
            DefaultTextStyle=3,
            DefaultLineStyle=3,
            DefaultFillStyle=3,
            DefaultGuideStyle=4,
        )
        faces = el(doc, "FaceNames")
        for name in sorted(self.faces | {"Arial"}):
            el(faces, "FaceName", NameU=name)
        styles = el(doc, "StyleSheets")
        style = el(
            styles,
            "StyleSheet",
            ID=0,
            NameU="No Style",
            Name="No Style",
        )
        cells(
            style,
            EnableLineProps=1,
            EnableFillProps=1,
            EnableTextProps=1,
            LinePattern=1,
            LineCap=2,
            LineColor="#000000",
            LineWeight=0.01,
            FillPattern=1,
            FillForegnd="#ffffff",
        )
        cells(
            el(el(style, "Section", N="Character"), "Row", IX=0),
            Font="Arial",
            Size=1 / 6,
            Style=0,
            Color="#000000",
        )
        cells(
            el(el(style, "Section", N="Paragraph"), "Row", IX=0), HorzAlign=0, SpLine=-1
        )
        for num, name in enumerate(("Text Only", "None", "Normal", "Guide"), 1):
            sheet = el(
                styles,
                "StyleSheet",
                ID=num,
                NameU=name,
                Name=name,
                LineStyle=0,
                FillStyle=0,
                TextStyle=0,
            )
            if num in (1, 2):
                cells(sheet, LinePattern=0, FillPattern=0)
        ds = el(
            doc,
            "DocumentSheet",
            NameU="TheDoc",
            Name="TheDoc",
            IsCustomNameU=1,
            IsCustomName=1,
            LineStyle=0,
            FillStyle=0,
            TextStyle=0,
        )
        cells(ds, OutputFormat=0, PreviewScope=0)
        self.link("visio/document.xml", "visio/windows.xml", "windows")
        self.part("visio/windows.xml", "windows", self.windows)
        self.part("visio/document.xml", "drawing.main", doc)
        self.part("visio/pages/pages.xml", "pages", self.pages)

    def save(self, dest):
        self.document()
        types = ET.Element("{%s}Types" % CT, nsmap={None: CT})
        for extension, mime in (
            ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
            ("xml", "application/xml"),
            ("png", "image/png"),
            ("jpg", "image/jpeg"),
            ("jpeg", "image/jpeg"),
        ):
            ET.SubElement(
                types, "{%s}Default" % CT, Extension=extension, ContentType=mime
            )
        for path, mime in self.types.items():
            ET.SubElement(
                types, "{%s}Override" % CT, PartName="/" + path, ContentType=mime
            )
        self.parts["[Content_Types].xml"] = types
        for source, table in self.rels.items():
            folder, file = posixpath.split(source)
            rr = ET.Element("{%s}Relationships" % REL, nsmap={None: REL})
            for target, (rid, kind) in table.items():
                ET.SubElement(
                    rr,
                    "{%s}Relationship" % REL,
                    Id=rid,
                    Type=kind if kind.startswith("http") else VISREL + kind,
                    Target=posixpath.relpath(target, folder or "."),
                )
            self.parts[posixpath.join(folder, "_rels", file + ".rels")] = rr
        with ZipFile(dest, "w", ZIP_DEFLATED) as z:
            # Use the same leading OPC records as a desktop-saved Office file.
            for path in sorted(
                self.parts,
                key=lambda p: (p != "[Content_Types].xml", p != "_rels/.rels", p),
            ):
                data = self.parts[path]
                z.writestr(
                    path,
                    (
                        data
                        if isinstance(data, bytes)
                        else ET.tostring(
                            data,
                            encoding="UTF-8",
                            xml_declaration=True,
                            standalone=True,
                        )
                    ),
                )
