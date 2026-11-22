"""Write the OPC parts of a standalone, macro-free Visio drawing."""

import posixpath
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET
from visio_geometry import NS, OFFICE, NAMES, el, cell, cells, preset

REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
VISREL = "http://schemas.microsoft.com/visio/2010/relationships/"
PREFIX = "application/vnd.ms-visio."


def xmlroot(name):
    node = ET.Element("{%s}%s" % (NS, name), nsmap={None: NS, "r": OFFICE})
    return node


def reference(node, rid):
    el(node, "Rel").set("{%s}id" % OFFICE, rid)


def page_size(parent, w, h):
    s = el(parent, "PageSheet", LineStyle=0, FillStyle=0, TextStyle=0)
    cells(
        s,
        PageWidth=w,
        PageHeight=h,
        PageScale=1,
        DrawingScale=1,
        DrawingSizeType=0,
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
        self.masters = {}
        self.images = {}
        self.faces = set()
        self.pages = xmlroot("Pages")
        self.masterlist = xmlroot("Masters")
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
        meta = el(self.pages, "Page", ID=i - 1, NameU=f"Page-{i}", Name=f"Page-{i}")
        page_size(meta, w, h)
        reference(meta, self.link("visio/pages/pages.xml", path, "page"))
        return path, root

    def master(self, kind, page):
        idx = self.masters.get(kind, len(self.masters) + 1)
        path = f"visio/masters/master{idx}.xml"
        self.link(page, path, "master")
        if kind in self.masters:
            return idx
        if not self.masters:
            self.link("visio/document.xml", "visio/masters/masters.xml", "masters")
        idx = self.masters[kind] = len(self.masters) + 1
        name = NAMES[kind]

        def guid(label):
            return (
                "{"
                + str(
                    uuid5(NAMESPACE_URL, "urn:editable-diagram:" + label + kind)
                ).upper()
                + "}"
            )

        master = el(
            self.masterlist,
            "Master",
            ID=idx,
            NameU=name,
            Name=name,
            MasterType=2,
            BaseID=guid("base:"),
            UniqueID=guid("master:"),
            MatchByName=0,
            IconSize=1,
            PatternFlags=0,
        )
        page_size(master, 1, 1)
        reference(master, self.link("visio/masters/masters.xml", path, "master"))
        root = xmlroot("MasterContents")
        s = el(
            el(root, "Shapes"),
            "Shape",
            ID=1,
            Type="Shape",
            LineStyle=0,
            FillStyle=0,
            TextStyle=0,
        )
        linear = kind in ("straightConnector1", "line")
        cells(s, PinX=0.5, PinY=0.5, Width=1, Height=0 if linear else 1)
        cell(s, "LocPinX", 0.5, "Width/2")
        cell(s, "LocPinY", 0 if linear else 0.5, "Height/2")
        if linear:
            cells(s, BeginX=0, BeginY=0.5, EndX=1, EndY=0.5)
        preset(s, kind, 1, 0 if linear else 1, {})
        ordered(s)
        self.part(path, "master", root)
        return idx

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
            DefaultTextStyle=0,
            DefaultLineStyle=0,
            DefaultFillStyle=0,
            DefaultGuideStyle=0,
        )
        faces = el(doc, "FaceNames")
        for name in sorted(self.faces | {"Arial"}):
            el(faces, "FaceName", NameU=name)
        style = el(
            el(doc, "StyleSheets"),
            "StyleSheet",
            ID=0,
            NameU="No Style",
            Name="No Style",
        )
        cells(
            style,
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
        self.part("visio/document.xml", "drawing.main", doc)
        self.part("visio/pages/pages.xml", "pages", self.pages)
        if self.masters:
            self.part("visio/masters/masters.xml", "masters", self.masterlist)

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
            for path, data in self.parts.items():
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
