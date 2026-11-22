---
name: pdf-to-editable-pptx
description: Reconstruct editable PowerPoint slides from vector PDFs of scientific diagrams and flowcharts. Use when users ask to turn a PDF figure into native PowerPoint shapes, arrows, text, pictures, and Office equations, or to assess diagram editability.
---

# PDF 流程图转可编辑 PowerPoint

## 使用

从本目录运行。需要 Python 3.11 或更高版本。转换可在本机离线执行，无需启动 Office。

```sh
python -m pip install -r requirements.txt
python scripts/convert.py "figure.pdf" -o "figure_editable.pptx"
```

在支持 Agent Skills 的应用中，将整个 `pdf-to-editable-pptx` 目录放到应用的技能目录，保留 `SKILL.md` 与 `scripts/` 的相对位置。例如 Codex 用户级目录为 `~/.agents/skills/pdf-to-editable-pptx/`。也可以直接在仓库目录运行上述命令。

## 转换流程

1. 以原始 PDF 为输入。若另有同名 PPTX，将其留作独立对照。对于 SVG，可先用矢量编辑器导出 PDF，并选择保留文本。每个同尺寸 PDF 页面输出为一张幻灯片，幻灯片大小取 PDF 的 MediaBox。
2. 为输出选择新的文件名。已有同名输出会被替换。需要检查对象时，加上 `--audit figure.audit.json`。该文件按页列出对象类别、箭头尺寸与连接、识别的重音符及警告。
3. 在 PowerPoint 的选择窗格中选择对象。在“设置形状格式”中更改圆角、箭头样式、尺寸或颜色。编辑文字和支持的 Office 公式。程序会为端点和方向均能唯一匹配的直箭头连接节点。需要保留箭头绝对位置时加上 `--no-bind`。
4. 核对密集区域。对照 PDF 查看公式的上下标、字形、位置、细线箭头和小框边界。报告中有字符映射或裁剪警告时，指出受影响的页面。

## 重建范围

- 从路径识别矩形、圆角矩形、椭圆、等腰三角形、平行四边形、有尖端的单大括号和块箭头，并保留可调参数。直线及配对箭头使用原生线端。其他绘制路径保留为含贝塞尔控制点的 PowerPoint 自由形状。每个源路径构成一个对象。
- 根据颜色、方向、端点与大小匹配相邻的箭头和线段，并按源箭头的物理尺寸选择 Office 档位。非常规箭头可能保留为独立图形。Office 的箭头尺寸只有离散档位。
- 文字保留为可编辑文本框。可辨识的 Cambria Math 基线、重音及一层上下标组合为 Office 原生公式。按原 PDF 字形的可见边界居中放置公式，为运算结构写入字号，法向旋转一致的公式在局部坐标中排版。较复杂的表达式保留为定位文本。
- Unicode 映射含糊时，可利用本机 Cambria Math 完整字体核对嵌入字形的轮廓和 OpenType 上下标替换表。可通过环境变量 `PDF_TO_PPTX_MATH_FONT` 指定合法安装的字体文件（TTF 或 TTC）。字体缺失且无法消歧时，查看审计警告。
- 嵌入位图保留为独立图片。扫描件只保留已有图像。路径化文字、数学表达式的语义、原始箭头连接关系与作者的分组均有恢复上限。复杂裁剪、渐变、混合模式、剪切变换和未支持的图案需人工核对。当前输出格式为 PPTX。
