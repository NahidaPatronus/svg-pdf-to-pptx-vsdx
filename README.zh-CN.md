# SVG / PDF 转可编辑 PowerPoint 与 Visio

[English](README.md) · [简体中文](README.zh-CN.md)

把 SVG 或矢量 PDF 转成可以继续修改的 PowerPoint（`.pptx`）或 Visio（`.vsdx`）图。修改论文流程图时，可以直接移动一个框、调整一根箭头或改一行标签。需要 Python 3.11+，转换在本地运行，无需安装 Office。

## 哪些内容可以编辑？

| 源图元素 | 转换结果 |
| --- | --- |
| 可识别的矩形、圆角框、椭圆、大括号、块箭头 | 每个图形独立可选，可修改尺寸及支持的形状参数 |
| 线条与箭头 | 使用原生线端。直箭头两端都能唯一匹配节点时，移动节点会带动连线。 |
| 文字与公式 | 可识别的 PDF 数学式在 PowerPoint 中生成原生公式。在 Visio 中，符号和上下标均可编辑，Cambria Math 帽子与波浪号按源字形的位置和宽度排版。 |
| 不规则轮廓与嵌入位图 | 轮廓保留为可调控制点的矢量路径，位图保留为独立图片 |

扫描页保留为图片，已转曲文字保留为路径。复杂裁剪、尚未支持的 SVG 效果和字体缺失会影响还原度，可用 `--audit report.json` 查看警告。

## 安装为 Agent Skill

在项目根目录运行以下命令，适用于 Codex、Antigravity 和 DeepSeek Harness。Claude Code 用户将两条命令中的 `.agents/skills` 换成 `.claude/skills`。DeepSeek Harness 需启用文件系统技能扩展。

```sh
git clone https://github.com/NahidaPatronus/svg-pdf-to-pptx-vsdx.git .agents/skills/svg-pdf-to-pptx-vsdx
python -m pip install -r .agents/skills/svg-pdf-to-pptx-vsdx/requirements.txt
```

安装后的调用示例

> 用 svg-pdf-to-pptx-vsdx 把 figure.pdf 转为 figure.vsdx，保留可编辑的框、箭头和文字。

## 命令行用法

在克隆下来的技能目录运行。SVG、PDF 都能输出两种格式，由输出文件的扩展名决定。

```sh
python scripts/convert.py diagram.svg -o diagram.pptx
python scripts/convert.py figure.pdf -o figure.vsdx --audit report.json
```

## 灵感与实现

项目借鉴了已有工具将 SVG 转为可编辑 PowerPoint 对象、用程序编辑 Visio 图形的思路。在此基础上，我们增加了从 PDF 轮廓识别原生图形、将独立箭头尖端与线段配对、把连接线绑定到节点的能力，并为两种目标格式提供了统一入口。[svg2ooxml](https://github.com/BramAlkema/svg2ooxml) · [vsdx](https://github.com/dave-howard/vsdx)

实现中用 pdfminer.six 和 pypdf 读取 PDF 绘图指令、字形和图片，用 python-pptx 构建 PowerPoint 对象，直接写入 Visio 图形的 ShapeSheet。在一张科研框架图的桌面 Visio 打开与另存实测中，**499 个对象、其中 200 个文本对象，以及 14 个连接线胶合端点**全部保留。[pdfminer.six](https://github.com/pdfminer/pdfminer.six) · [pypdf](https://github.com/py-pdf/pypdf) · [python-pptx](https://github.com/scanny/python-pptx)

## 许可与署名

项目自身代码和文档中受著作权或类似权利保护的部分采用 CC BY 4.0。分享时注明项目名 `svg-pdf-to-pptx-vsdx`，附上仓库与许可证链接，并注明所作修改。第三方依赖按各自许可证使用。[项目许可证](LICENSE) · [第三方许可与署名](THIRD_PARTY_NOTICES.md)
