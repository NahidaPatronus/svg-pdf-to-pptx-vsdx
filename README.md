# SVG / PDF to editable PowerPoint and Visio

[English](README.md) · [简体中文](README.zh-CN.md)

Turn an SVG or vector PDF into a diagram you can revise in PowerPoint (`.pptx`) or Visio (`.vsdx`). Move a box, reconnect an arrow, or edit a label while the surrounding figure stays intact. Runs locally with Python 3.11+ and works without Office installed.

## What stays editable?

| Source element | In the output |
| --- | --- |
| Recognized rectangles, rounded boxes, ellipses, braces and block arrows | Individual native shapes with editable dimensions and supported adjustments |
| Lines and arrows | Native line ends. A straight arrow binds to nodes when both endpoints match unambiguously. |
| Text and equations | Editable text. Recognized PDF math can become Office equations in PowerPoint; Visio preserves positioned text and scripts. |
| Irregular paths and embedded images | Editable vector paths with control points, and separate bitmap objects |

Scanned pages remain images. Outlined letters remain paths. Complex clipping, unsupported SVG effects and missing fonts can affect fidelity. Use `--audit report.json` to inspect warnings.

## Install as an Agent Skill

From your project directory, run the following for Codex, Antigravity or DeepSeek Harness. You need read access to this private repository. For Claude Code, use `.claude/skills` in both commands. DeepSeek Harness needs its filesystem skill provider enabled.

```sh
git clone https://github.com/NahidaPatronus/svg-pdf-to-pptx-vsdx.git .agents/skills/svg-pdf-to-pptx-vsdx
python -m pip install -r .agents/skills/svg-pdf-to-pptx-vsdx/requirements.txt
```

Example request

> Use svg-pdf-to-pptx-vsdx to convert figure.pdf to figure.vsdx. Keep the boxes, arrows and labels editable.

## Run directly

From the cloned skill directory, choose the output format with the filename extension. Either input supports either output.

```sh
python scripts/convert.py diagram.svg -o diagram.pptx
python scripts/convert.py figure.pdf -o figure.vsdx --audit report.json
```

## Inspiration and implementation

Existing work on editable SVG-to-PowerPoint export and programmatic Visio editing informed the design. This project adds recognition of diagram shapes from PDF contours, arrowhead matching, connector binding and a single conversion command for both editors. [svg2ooxml](https://github.com/BramAlkema/svg2ooxml) · [vsdx](https://github.com/dave-howard/vsdx)

The implementation reads PDF drawing operations, glyphs and images with pdfminer.six and pypdf, builds PowerPoint objects with python-pptx, and writes Visio ShapeSheet geometry directly. In a desktop Visio open-and-save check on a scientific diagram, all **499 objects**, **200 text objects** and **14 glued connector endpoints** survived. [pdfminer.six](https://github.com/pdfminer/pdfminer.six) · [pypdf](https://github.com/py-pdf/pypdf) · [python-pptx](https://github.com/scanny/python-pptx)
