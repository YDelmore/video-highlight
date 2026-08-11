# video-highlight

A tool that surfaces highlight candidates in livestream danmaku data.

## Status

Implements **indicators 1-8** of the 19-indicator strategy in
`docs/分析策略.md`:
- 维度一 热度与规模：指标 1 弹幕密度 / 2 爆发速率 / 3 沉默用户激活率 / 4 弹幕长度分布
- 维度二 用户行为与参与模式：指标 5 发言集中度 / 6 用户重合度 / 7 用户生命周期 / 8 回锅用户比例

指标 1-6 是逐秒时间序列，指标 7-8 是每个高潮候选窗口的统计。CLI 输出固定分节报告
（`console_print`）+ matplotlib 3×3 静态图（`plot`）；另有基于 **Streamlit + Plotly**
的交互分析平台（见下）。

## Install

```bash
uv sync                  # core deps (pandas, numpy)
uv sync --extra plot     # + matplotlib for charting
uv sync --extra app      # + streamlit/plotly for the interactive platform
uv sync --extra dev      # + pytest for tests
```

## 分析平台（Streamlit）

轻量级交互平台：为两个维度配置权重计算**逐秒综合热度 H(t)** 与 **全场综合评分**，
对检测到的高潮区间按评分分**级（S/A/B/C）**，并用联动图表展示。

```bash
uv sync --extra app
uv run streamlit run src/video_highlight/app.py
```

核心交互（时间轴为主控，所有图表联动）：
- **上传弹幕文件**：侧边栏可直接上传虎牙风格弹幕 XML（`st.file_uploader`），
  上传后优先于本地路径使用；也可在「数据源」填写服务器上的 XML 路径；
- 底部一条可拖拽的**全场时间轴**；拖拽时所有指标图同步高亮当前时间点；
- 时间轴上按等级着色标记高潮区间：**S 级红 / A 级橙 / B 级黄 / C 级绿**；
- 点击任一高潮色带（或下方对应的按钮），时间轴自动跳转到该高潮的**起点**；
- 侧边栏可实时调整维度权重、指标权重与分级阈值，评分与分级即时更新。

评分逻辑：每个指标先归一化到 [0,1]（语义见 `scoring.compute_signals`），
`H(t)` 为六个时间序列指标的加权有效均值；每个高潮候选的评分 = 全部 8 个指标的加权
均值（指标 1-2 取窗口内峰值、3-6 取窗口内均值、7-8 取转化/回锅占比）。

## Usage

```bash
uv run video-highlight path/to/danmaku.xml
uv run video-highlight path/to/danmaku.xml --plot chart.png
```

`xml_path` is optional: when omitted, `docs/danmaku.xml` in the current
directory is used if present (handy for IDE "Run" buttons).

Output is a fixed-section console report:

```
=== 分析概览 ===
弹幕总数: N
时间跨度: T 秒 (X 分钟)

=== 指标1: 弹幕密度 (W=10s) ===
均值: μ / 标准差: σ / 最大值: max / 峰时 t_peak
候选区间 (D > μ+2σ): K 个

=== 指标2: 爆发速率 ===
S 均值 / S 标准差 / 最大 S / 最大 S_rel

=== 高潮候选区间（合并后） ===
```

## Run tests

```bash
uv run pytest
```

## Project layout

```
src/video_highlight/
├── parser.py        XML -> list[Danmaku] (uid, ts_ms, text)
├── loader.py        list[Danmaku] -> DataFrame (t, uid, text, length)
├── metrics/
│   ├── _window.py   time-based rolling window helper
│   ├── _offsets.py  adaptive time-offset scaling
│   ├── density.py   metric 1 (弹幕密度)
│   ├── burst.py     metric 2 (爆发速率)
│   ├── activation.py   metric 3 (沉默用户激活率)
│   ├── length_dist.py  metric 4 (弹幕长度分布)
│   ├── concentration.py metric 5 (发言集中度)
│   ├── overlap.py       metric 6 (用户重合度)
│   ├── lifecycle.py     metric 7 (用户生命周期)
│   └── returning.py     metric 8 (回锅用户比例)
├── highlights.py    candidate segmentation (μ+2σ / μ+3σ)
├── scoring.py       composite scoring: weights -> heat H(t) -> S/A/B/C grades
├── charts.py        Plotly figure builders (linked to the master clock)
├── app.py           Streamlit analysis platform
└── report.py        console + optional matplotlib chart
```

See `docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md`
for the full design and `docs/分析策略.md` for the 19-indicator strategy.
