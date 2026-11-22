---
name: pdf-to-editable-pptx
description: Convert SVG diagrams and vector PDFs to editable PowerPoint slides. Use for flowcharts and scientific figures with native shapes, arrows, editable text, pictures, or equations, including requests to check reconstruction quality.
---

# SVG / PDF 图转可编辑 PowerPoint

## 使用

从本目录运行。需要 Python 3.11 或更高版本。转换可在本机离线执行，无需启动 Office。

```sh
python -m pip install -r requirements.txt
python scripts/convert.py "graph.svg" -o "graph_editable.pptx"
python scripts/convert.py "figure.pdf" -o "figure_editable.pptx"
```

在支持 Agent Skills 的应用中，将整个 `pdf-to-editable-pptx` 目录放到应用的技能目录，保留 `SKILL.md` 与 `scripts/` 的相对位置。例如 Codex 用户级目录为 `~/.agents/skills/pdf-to-editable-pptx/`。也可以直接在仓库目录运行上述命令。

## 转换流程

1. 直接传入 SVG 或 PDF。SVG 单文件生成一张幻灯片，保留 viewBox 和长宽比，CSS 像素按 96 dpi 换算。过小、过大的画布按 PowerPoint 尺寸限制等比调整。同尺寸多页 PDF 每页生成一张幻灯片，大小取 MediaBox。同名参考 PPTX 仅用于独立核对。
2. 为输出选择新的文件名。已有同名输出会被替换。需要检查对象时，加上 `--audit figure.audit.json`。该文件按页列出对象类别、箭头尺寸与连接、识别的重音符及警告。
3. 在 PowerPoint 的选择窗格中选择对象。在“设置形状格式”中更改圆角、箭头样式、尺寸或颜色。编辑文字和支持的 Office 公式。程序会为端点和方向均能唯一匹配的直箭头连接节点。需要保留箭头绝对位置时加上 `--no-bind`。
4. 核对密集区域。对照 PDF 查看公式的上下标、字形、位置、细线箭头和小框边界。报告中有字符映射或裁剪警告时，指出受影响的页面。

## SVG

- 从 XML 读取绘制顺序、嵌套组、局部变换、内部 use 引用、样式继承及常见元素、类和 ID 选择器。圆、椭圆、矩形、圆角矩形、菱形等优先使用原生形状。单段线、常见直角折线和支持的起止箭头使用原生线条或连接符。一般路径保留为可编辑自由形状。
- 支持实色、局部线性渐变、线宽和自定义虚线。文字保留为可编辑文本框，支持常用 tspan、居中与右对齐、中西文字体、上下标文字和全角空格。嵌入或相对路径引用的位图单独插入；转换时保持配套图片与 SVG 的目录关系。
- 逐字符定位、非均匀拉伸文字和透明组重叠可能产生显示差异，请查看审计警告。遮罩、滤镜、复杂裁剪、SVG 中的 HTML、复合或固定角度的端点标记尚未实现，遇到这些元素会报告错误。已轮廓化文字作为路径编辑。SVG 文字和上下标保留为文本，PDF 的数学公式识别见下节。

## PDF

- 从路径识别矩形、圆角矩形、椭圆、等腰三角形、平行四边形、有尖端的单大括号和块箭头，并保留可调参数。直线及配对箭头使用原生线端。其他绘制路径保留为含贝塞尔控制点的 PowerPoint 自由形状。每个源路径构成一个对象。
- 根据颜色、方向、端点与大小匹配相邻的箭头和线段，并按源箭头的物理尺寸选择 Office 档位。非常规箭头可能保留为独立图形。Office 的箭头尺寸只有离散档位。
- 文字保留为可编辑文本框。可辨识的 Cambria Math 基线、重音及一层上下标组合为 Office 原生公式。按原 PDF 字形的可见边界居中放置公式，为运算结构写入字号，法向旋转一致的公式在局部坐标中排版。较复杂的表达式保留为定位文本。
- Unicode 映射含糊时，可利用本机 Cambria Math 完整字体核对嵌入字形的轮廓和 OpenType 上下标替换表。可通过环境变量 `PDF_TO_PPTX_MATH_FONT` 指定合法安装的字体文件（TTF 或 TTC）。字体缺失且无法消歧时，查看审计警告。
- 嵌入位图保留为独立图片。扫描件只保留已有图像。路径化文字、数学表达式的语义、原始箭头连接关系与作者的分组均有恢复上限。复杂裁剪、渐变、混合模式、剪切变换和未支持的图案需人工核对。当前输出格式为 PPTX。
