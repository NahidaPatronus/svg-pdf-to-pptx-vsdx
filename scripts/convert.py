"""Convert an SVG or vector PDF to an editable PowerPoint presentation."""

import argparse
from collections import Counter
from itertools import groupby
import json, math, os, tempfile
from pathlib import Path
from pptx import Presentation
from pptx.util import Pt
from pdf_input import read_pages
from geometry import poly, dist, unit, sub, dot, identify
from office_shapes import add_picture, add_path, combine, tag
from labels import add_label, join
from math_text import glyph_metrics


def ports(geom):
    x, y, w, h = geom.box
    return [(x + w / 2, y), (x, y + h / 2), (x + w / 2, y + h), (x + w, y + h / 2)]


def connect(edges, nodes):
    linked = []
    for shape, points in edges:
        chosen = []
        for p, other in zip(points, reversed(points)):
            outward = unit(sub(other, p))
            hits = []
            for node, geom in nodes:
                for idx, (port, normal) in enumerate(
                    zip(ports(geom), [(0, -1), (-1, 0), (0, 1), (1, 0)])
                ):
                    error = dist(p, port)
                    if error < 3 and dot(outward, normal) > 0.88:
                        hits.append((error, node.shape_id, idx))
            hits.sort()
            chosen.append(
                hits[0]
                if hits and (len(hits) == 1 or hits[1][0] - hits[0][0] > 1)
                else None
            )
        if not all(chosen) or chosen[0][1] == chosen[1][1]:
            continue
        nv = shape._element.nvCxnSpPr.cNvCxnSpPr
        for q, (_, nodeid, site) in zip(("stCxn", "endCxn"), chosen):
            tag(nv, "a:" + q, id=nodeid, idx=site)
        linked.append([shape.shape_id, *[c[1] for c in chosen]])
    return linked


def process(slide, page, bind):
    counts = Counter()
    edges = []
    nodes = []
    audit = []
    accents = glyph_metrics(page)
    containers = []
    for item in page.items:
        if item.kind == "path":
            geom = identify(item.data)
            if geom.kind in ("rect", "roundRect") and geom.angle == 0:
                containers.append(geom.box)
    clusters = groupby(page.items, key=lambda i: i.owner)
    for owner, items in clusters:
        group = list(items)
        mixed = len({i.kind for i in group}) > 1
        container = []
        for kind, items in groupby(group, key=lambda i: i.kind):
            parts = list(items)
            if kind == "glyph":
                chunks = [parts] if owner is not None else split_unmarked(parts)
                for chunk in chunks:
                    shapes, mode = add_label(
                        slide, chunk, accents, owner is None or not mixed, containers
                    )
                    label = "".join(
                        accents.get((g.data["font"], g.data["cid"]), g.data["s"])
                        for g in chunk
                    ).strip()
                    obj = join(slide, shapes, mode + " " + label[:58])
                    if obj is not None:
                        container.append(obj)
                        counts[mode] += 1
                        audit.append(
                            dict(id=obj.shape_id, owner=owner, type=mode, text=label)
                        )
            elif kind == "image":
                for item in parts:
                    obj = add_picture(slide, item)
                    obj.name = f"Picture {obj.shape_id}"
                    counts["picture"] += 1
                    container.append(obj)
            else:
                n = 0
                while n < len(parts):
                    item = parts[n]
                    n += 1
                    if n < len(parts) and combine(item, parts[n]):
                        n += 1
                    obj, geom = add_path(slide, item)
                    kindname = geom.kind + (" arrow" if item.style.get("end") else "")
                    obj.name = f"{kindname} {obj.shape_id}"
                    counts[kindname] += 1
                    container.append(obj)
                    audit.append(
                        dict(
                            id=obj.shape_id,
                            owner=owner,
                            type=kindname,
                            box=geom.box,
                            angle=geom.angle,
                            adjustments=geom.adjusts,
                        )
                    )
                    if item.style.get("end"):
                        audit[-1].update(
                            marker_pt=item.style["marker_pt"],
                            native_end=item.style["end"],
                        )
                    if (
                        geom.kind in ("rect", "roundRect")
                        and geom.angle == 0
                        and min(geom.box[2:]) > 9
                    ):
                        nodes.append((obj, geom))
                    if geom.kind == "line" and item.style.get("end"):
                        edges.append((obj, poly(item.data)))
        if owner is not None and mixed and len(container) > 1:
            join(slide, container, f"PDF group {owner}")
    linked = connect(edges, nodes) if bind else []
    return dict(
        objects=dict(counts),
        bound_arrows=linked,
        detail=audit,
        resolved_accent_glyphs=[
            dict(font=k[0], cid=k[1], mark=v) for k, v in accents.items()
        ],
        warnings=sorted(
            w
            for w in page.warnings
            if w not in {"Unmapped PDF glyph %s CID %s" % k for k in accents}
        ),
        crop=page.crop,
    )


def split_unmarked(items):
    from labels import lines_of

    chunks = []
    for math_font, run in groupby(
        items, key=lambda g: "CambriaMath" in g.data["font"].replace(" ", "")
    ):
        run = list(run)
        if not math_font:
            start = 0
            for line in lines_of([i.data for i in run]):
                chunks.append(run[start : start + len(line)])
                start += len(line)
            continue
        chunk = []
        for item in run:
            g = item.data
            if chunk:
                prev = chunk[-1].data
                angle = math.radians(prev["angle"])
                dx = g["x"] - prev["x"]
                dy = g["y"] - prev["y"]
                along = dx * math.cos(angle) + dy * math.sin(angle)
                across = -dx * math.sin(angle) + dy * math.cos(angle)
                em = max(g["size"], prev["size"], chunk[0].data["size"])
                if (
                    abs(across) > em
                    or not -1.75 * em <= along <= prev["advance"] + 0.65 * em
                    or abs(prev["angle"] - g["angle"]) > 0.1
                ):
                    chunks.append(chunk)
                    chunk = []
            chunk.append(item)
        if chunk:
            chunks.append(chunk)
    return chunks


def convert(source, dest, bind=True):
    if (
        Path(dest).suffix.lower() != ".pptx"
        or Path(source).resolve() == Path(dest).resolve()
    ):
        raise ValueError("Choose a separate .pptx output path.")
    deck = Presentation()
    report = []
    suffix = Path(source).suffix.lower()
    if suffix == ".svg":
        from svg_input import svg_slide

        report.append(svg_slide(deck, source, connect if bind else None))
    elif suffix == ".pdf":
        for index, page in enumerate(read_pages(source)):
            size = Pt(page.width), Pt(page.height)
            if index == 0:
                deck.slide_width, deck.slide_height = size
            elif size != (deck.slide_width, deck.slide_height):
                raise ValueError("Mixed page sizes need separate decks.")
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            report.append(process(slide, page, bind))
    else:
        raise ValueError("Choose an .svg or .pdf source file.")
    if not report:
        raise ValueError("Empty PDF")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=dest.parent, suffix=".pptx", delete=False
    ) as tmp:
        path = tmp.name
    try:
        deck.save(path)
        os.replace(path, dest)
    finally:
        Path(path).unlink(missing_ok=True)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--audit", type=Path)
    ap.add_argument("--no-bind", action="store_true")
    args = ap.parse_args()
    if args.audit and args.audit.resolve() in {
        args.source.resolve(),
        args.output.resolve(),
    }:
        ap.error("The audit requires its own file path.")
    report = convert(args.source, args.output, not args.no_bind)
    if args.audit:
        args.audit.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
    for page in report:
        print(page["objects"])
