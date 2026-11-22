"""Math accents and scripts reconstructed from PDF font outlines and baselines."""

import io, math, os, shutil, subprocess
from pathlib import Path
from functools import lru_cache
from collections import defaultdict
from lxml import etree as E
from fontTools.ttLib import TTFont

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
A14 = "http://schemas.microsoft.com/office/drawing/2010/main"

# Cambria Math spacing accents, in the font's 2048-unit em. The PDF
# may use a wider OpenType MATH variant with a different side bearing.
# These nominal metrics also work on conversion hosts without Office fonts.
SPACING_ACCENTS = {
    "\u0302": ("\u02c6", 6, -1442, 578, -1070, 583),
    "\u0303": ("\u02dc", -38, -1366, 624, -1128, 583),
}
VISIO_MATH_ASCENT = 0.75  # Top of a zero-inset Visio text block to the baseline, in em.
VISIO_FONT_SCALE = "{http://schemas.microsoft.com/office/visio/2012/main}FontScale"


def visio_accent(g):
    """Fit editable spacing text to the embedded accent's ink in its local axes."""
    metrics = SPACING_ACCENTS.get(g["s"])
    if (
        not metrics
        or "ink_offsets" not in g
        or "CambriaMath" not in g["font"].replace(" ", "")
    ):
        return g
    char, left, top, right, bottom, advance = metrics
    l, t, r, b = g["ink_offsets"]
    if r <= l or b <= t:
        return g
    vertical = (b - t) / (bottom - top)
    horizontal = (r - l) / (right - left)
    # Visio limits character width to 600%. Preserve the center if clamped.
    scale = min(horizontal / vertical, 6)
    horizontal = vertical * scale
    dx = (l + r - (left + right) * horizontal) / 2
    dy = t - top * vertical
    a = math.radians(g["angle"])
    co, si = math.cos(a), math.sin(a)
    return dict(
        g, s=char, size=2048 * vertical, advance=advance * horizontal,
        x=g["x"] + co * dx - si * dy,
        y=g["y"] + si * dx + co * dy,
        font_scale=scale,
    )


def elem(ns, name, parent=None):
    q = "{%s}%s" % (ns, name)
    return E.Element(q, nsmap={"m": M}) if parent is None else E.SubElement(parent, q)


@lru_cache(maxsize=1)
def reference_math_font():
    """Use an installed math font only for disambiguating corrupt PDF character maps."""
    paths = [
        os.environ.get("PDF_TO_PPTX_MATH_FONT"),
        str(Path(os.environ.get("WINDIR", "/Windows")) / "Fonts" / "cambria.ttc"),
        "/Library/Fonts/Microsoft/Cambria Math.ttf",
        "/Library/Fonts/Microsoft/Cambria.ttc",
    ]
    if os.name != "nt" and shutil.which("fc-match"):
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", "Cambria Math"],
            capture_output=True,
            text=True,
        )
        paths.append(result.stdout)
    for path in filter(None, paths):
        if not Path(path).is_file():
            continue
        for index in range(2):
            try:
                font = TTFont(path, fontNumber=index)
            except Exception:
                break
            if font["name"].getDebugName(1) != "Cambria Math":
                font.close()
                continue
            unicode_map = {name: chr(u) for u, name in font.getBestCmap().items()}
            if "GSUB" in font:
                gsub = font["GSUB"].table
                for feature in gsub.FeatureList.FeatureRecord:
                    if feature.FeatureTag != "ssty":
                        continue
                    for lookup in feature.Feature.LookupListIndex:
                        for table in gsub.LookupList.Lookup[lookup].SubTable:
                            table = getattr(table, "ExtSubTable", table)
                            for name, variants in getattr(
                                table, "alternates", {}
                            ).items():
                                if name in unicode_map:
                                    for v in variants:
                                        unicode_map[v] = unicode_map[name]
            return font, unicode_map
    return None


def glyph_metrics(page):
    """Classify a missing accent from its actual embedded outline, not its CID."""
    need = {
        (i.data["font"], i.data["cid"])
        for i in page.items
        if i.kind == "glyph" and i.data["s"] == "\ufffd"
    }
    mapping = {}
    glyphs = [i.data for i in page.items if i.kind == "glyph"]
    by_font = defaultdict(list)
    for g in glyphs:
        if "CambriaMath" in g["font"].replace(" ", ""):
            by_font[g["font"]].append(g)
    for ref in page.pdf_page["/Resources"].get("/Font", {}).values():
        pdf_font = ref.get_object()
        name = str(pdf_font.get("/BaseFont", "")).strip("/").split("+")[-1]
        if name not in by_font or "/DescendantFonts" not in pdf_font:
            continue
        desc = pdf_font["/DescendantFonts"][0].get_object()
        stream = desc["/FontDescriptor"].get("/FontFile2")
        if stream is None:
            continue
        font = TTFont(io.BytesIO(stream.get_object().get_data()))
        gids = desc.get("/CIDToGIDMap", "/Identity")
        gidmap = None if str(gids) == "/Identity" else gids.get_object().get_data()
        if "glyf" not in font:
            continue
        units = font["head"].unitsPerEm
        groups = defaultdict(set)
        for g in by_font[name]:
            groups[g["s"]].add(g["cid"])
        dubious = {
            cid
            for s, cids in groups.items()
            if len(cids) > 1 and len(s) == 1 and ord(s) > 0xFFFF
            for cid in cids
        }
        for g in by_font[name]:
            cid = g["cid"]
            gid = (
                cid
                if gidmap is None
                else int.from_bytes(gidmap[2 * cid : 2 * cid + 2], "big")
            )
            if gid >= len(font.getGlyphOrder()):
                continue
            glyph = font["glyf"][font.getGlyphName(gid)]
            if not glyph.numberOfContours:
                continue
            scale = g["size"] / units
            g["ink_offsets"] = (
                glyph.xMin * scale * g.get("aspect", 1),
                -glyph.yMax * scale,
                glyph.xMax * scale * g.get("aspect", 1),
                -glyph.yMin * scale,
            )
            if cid not in dubious:
                continue
            reference = reference_math_font()
            if reference is not None and gid < len(reference[0].getGlyphOrder()):
                full, cmap = reference
                glyphname = full.getGlyphName(gid)
                other = full["glyf"][glyphname]
                if (
                    glyphname in cmap
                    and font["head"].unitsPerEm == full["head"].unitsPerEm
                    and glyph.getCoordinates(font["glyf"])[:2]
                    == other.getCoordinates(full["glyf"])[:2]
                ):
                    g["s"] = cmap[glyphname]
                    continue
            page.warnings.add(
                "Ambiguous math character mapping in %s (CID %s)." % (name, cid)
            )
        for f, cid in need:
            if f != name:
                continue
            gid = (
                cid
                if gidmap is None
                else int.from_bytes(gidmap[2 * cid : 2 * cid + 2], "big")
            )
            if gid >= len(font.getGlyphOrder()):
                continue
            glyph = font["glyf"][font.getGlyphName(gid)]
            if glyph.numberOfContours != 1:
                continue
            coords, _, _ = glyph.getCoordinates(font["glyf"])
            xs, ys = zip(*coords)
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if (
                not w
                or not h
                or w / h < 1.5
                or min(ys) < font["head"].unitsPerEm * 0.42
            ):
                continue
            norm = [((x - min(xs)) / w, (y - min(ys)) / h) for x, y in coords]
            peaks = [x for x, y in norm if y > 0.85]
            valleys = [x for x, y in norm if y < 0.15]
            if (
                peaks
                and all(0.25 < x < 0.75 for x in peaks)
                and min(valleys) < 0.15
                and max(valleys) > 0.85
            ):
                mapping[f, cid] = "\u0302"
            elif any(0.1 < x < 0.45 for x in peaks) and any(
                0.55 < x < 0.9 for x in valleys
            ):
                mapping[f, cid] = "\u0303"
    return mapping


def run_properties(parent, size, rgb):
    rp = elem(A, "rPr", parent)
    rp.set("sz", str(round(size * 100)))
    fill = elem(A, "solidFill", rp)
    elem(A, "srgbClr", fill).set("val", bytes(rgb).hex().upper())
    elem(A, "latin", rp).set("typeface", "Cambria Math")
    return rp


def mr(s, parent, size, rgb):
    node = elem(M, "r", parent)
    style = elem(M, "rPr", node)
    elem(M, "nor", style)
    run_properties(node, size, rgb)
    tx = elem(M, "t", node)
    tx.text = s
    if s.isspace():
        tx.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return node


def math_content(glyphs, accents):
    """Resolve one level of simultaneous sub/superscripts. Deeper layout is reviewable text."""
    g = [dict(t) for t in glyphs if t["s"].strip()]
    if not g or not all("CambriaMath" in t["font"].replace(" ", "") for t in g):
        return
    main = max(t["size"] for t in g)
    roots = [t for t in g if t["size"] > 0.94 * main and t["s"] != "\ufffd"]
    if not roots:
        return
    base = sorted(t["y"] for t in roots)[len(roots) // 2]
    node = elem(M, "oMath")
    clusters = []
    pending = None
    for t in g:
        if t["s"] == "\ufffd":
            accent = accents.get((t["font"], t["cid"]))
            if not accent or pending:
                return
            pending = (accent, t)
            continue
        dy = t["y"] - base
        if t["size"] > 0.91 * main and abs(dy) < main * 0.18:
            clusters.append(dict(root=t, accent=None, sub=[], sup=[]))
            if pending:
                ac, mark = pending
                if abs(mark["x"] - t["x"]) > main * 0.7:
                    return
                clusters[-1]["accent"] = ac
                pending = None
        else:
            if (
                not clusters
                or pending
                or abs(dy) < 0.07 * main
                or t["size"] < 0.66 * main
            ):
                return
            key = "sub" if dy > 0 else "sup"
            group = clusters[-1][key]
            if group and abs(group[0]["y"] - t["y"]) > main * 0.14:
                return
            group.append(t)
    if pending:
        return
    for c in clusters:
        t = c["root"]
        sup, sub = c["sup"], c["sub"]
        parent = node
        if sub or sup:
            kind = "sSubSup" if sub and sup else ("sSub" if sub else "sSup")
            script = elem(M, kind, node)
            run_properties(
                elem(M, "ctrlPr", elem(M, kind + "Pr", script)), main, t["rgb"]
            )
            parent = elem(M, "e", script)
        if c["accent"]:
            acc = elem(M, "acc", parent)
            props = elem(M, "accPr", acc)
            elem(M, "chr", props).set("{%s}val" % M, c["accent"])
            run_properties(elem(M, "ctrlPr", props), main, t["rgb"])
            parent = elem(M, "e", acc)
        mr(t["s"], parent, main, t["rgb"])
        for typ, chars in (("sub", sub), ("sup", sup)):
            if chars:
                part = elem(M, typ, script)
                mr("".join(a["s"] for a in chars), part, main, t["rgb"])
    return node, main, base
