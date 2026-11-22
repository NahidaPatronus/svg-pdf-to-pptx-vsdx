---
name: pdf-to-editable-pptx
description: Convert SVG diagrams and vector PDFs into editable PowerPoint (.pptx) slides or Visio (.vsdx) drawings. Use for flowcharts and scientific figures that need native shapes, connectors, text, bitmap images, or a reconstruction audit.
---

# SVG / PDF 转可编辑 PowerPoint 或 Visio

## 使用

需要 Python 3.11 或更高版本。安装依赖后可离线转换，无需安装 Office。以下命令从技能目录运行。两种输入均支持两种输出，由 `-o` 的扩展名选择格式。

```sh
python -m pip install -r requirements.txt
python scripts/convert.py "graph.svg" -o "graph_editable.vsdx"
python scripts/convert.py "figure.pdf" -o "figure_editable.pptx"
```

将整个仓库作为 `pdf-to-editable-pptx` 子目录放在宿主的技能目录中，保留 `SKILL.md`、`requirements.txt` 和 `scripts/` 的相对位置。也可直接使用命令行。由代理调用时，使用已安装目录内脚本的绝对路径，输入和输出路径相对于用户工作目录解析。

| 宿主 | 项目内的安装目录 |
| --- | --- |
| Claude Code | `.claude/skills/pdf-to-editable-pptx/` |
| DeepSeek Harness | `.dsh/skills/pdf-to-editable-pptx/` 或 `.agents/skills/pdf-to-editable-pptx/`，启用 skill 和 skill-filesystem 扩展 |
| Antigravity | `.agents/skills/pdf-to-editable-pptx/` |

## 转换与核对

1. 仅提供 SVG 或 PDF 原件。SVG 保留 viewBox 和长宽比，CSS 像素按 96 dpi 换算。PDF 以每个 MediaBox 生成一页。Visio 可保留各页不同的尺寸。PowerPoint 使用统一页面尺寸，SVG 超出其画布范围时等比适配。
2. 为输出选择新文件名。已有同名输出会被替换。需要检查对象时，加上 `--audit figure.audit.json`。报告逐页列出对象类型、箭头匹配和连接、字形及转换警告。
3. 能根据位置与方向唯一匹配两个节点的直箭头会连接到节点，使用 `--no-bind` 可保留绝对位置。在 PowerPoint 的选择窗格或 Visio 的绘图资源管理器中选取对象，编辑文字与形状，移动节点核对连线。
4. Visio 使用文档内原生母版绘制支持的形状，保留线端箭头、连接点、可调大括号及块箭头。普通曲线作为单个可编辑路径，位图为独立图片。PDF 数学式按原字形基线输出为可编辑的 Visio 定位文字；PowerPoint 可使用下述 Office 公式。Visio 自定义虚线匹配内置线型，虚线段长和间距可能变化。
5. 核对密集区域的上下标、字体、细线箭头和小框边界。跨设备排版受所装字体影响。报告中出现字符映射或裁剪警告时，标明受影响的页面。
6. 报告 VSDX 验证结果时注明实际读取它的程序。用桌面 Visio 打开文件后，记录是否正常显示绘图、是否出现修复提示；只做过结构检查时，标明桌面打开待验证。

## SVG

- 从 XML 读取绘制顺序、嵌套组、局部变换、内部 use 引用、样式继承及常见元素、类和 ID 选择器。圆、椭圆、矩形、圆角矩形、菱形等优先使用原生形状。单段线、常见直角折线和支持的起止箭头使用原生线条或连接符。一般路径保留为可编辑自由形状。
- 支持实色、局部线性渐变、线宽和自定义虚线。文字保留为可编辑文本框，支持常用 tspan、居中与右对齐、中西文字体、上下标文字和全角空格。嵌入或相对路径引用的位图单独插入；转换时保持配套图片与 SVG 的目录关系。
- 逐字符定位、非均匀拉伸文字和透明组重叠可能产生显示差异，请查看审计警告。遮罩、滤镜、复杂裁剪、SVG 中的 HTML、复合或固定角度的端点标记尚未实现，遇到这些元素会报告错误。已轮廓化文字作为路径编辑。SVG 文字和上下标保留为文本，PDF 的数学公式识别见下节。

## PDF

- 从路径识别矩形、圆角矩形、椭圆、等腰三角形、平行四边形、有尖端的单大括号和块箭头，并保留可调参数。直线及配对箭头使用原生线端。其他绘制路径保留为含贝塞尔控制点的 自由形状。每个源路径构成一个对象。
- 根据颜色、方向、端点与大小匹配相邻的箭头和线段，并按源箭头的物理尺寸选择 Office 档位。非常规箭头可能保留为独立图形。Office 的箭头尺寸只有离散档位。
- 文字保留为可编辑文本框。PPTX 输出中，可辨识的 Cambria Math 基线、重音及一层上下标组合为 Office 原生公式。按原 PDF 字形的可见边界居中放置公式，为运算结构写入字号，法向旋转一致的公式在局部坐标中排版。较复杂的表达式保留为定位文本。
- Unicode 映射含糊时，可利用本机 Cambria Math 完整字体核对嵌入字形的轮廓和 OpenType 上下标替换表。可通过环境变量 `PDF_TO_PPTX_MATH_FONT` 指定合法安装的字体文件（TTF 或 TTC）。字体缺失且无法消歧时，查看审计警告。
- 嵌入位图保留为独立图片。扫描件只保留已有图像。路径化文字、数学表达式的语义、原始箭头连接关系与作者的分组均有恢复上限。复杂裁剪、渐变、混合模式、剪切变换和未支持的图案需人工核对。
