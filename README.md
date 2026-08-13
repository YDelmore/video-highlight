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
- **整场直播（分片聚合）**：录制若为分片存储（如 `E:\huya\<平台>\<主播>\`
  下的多个 xml），侧边栏数据源切到「整场直播」并填分片根目录，后台把同一场直播的
  分片**聚合为连续时间轴**后再跑全部分析（录制中断处留空）。分场判定**不依赖
  `live_start_time`**（主播切换设备/下播再开播会使其不一致），而是按**文件时间 + 标题**：
  分片按创建时间排序，相邻分片的上一个修改时间与下一个创建时间间隔 **≤1 小时且标题相同**
  才视为同一场直播（标题不同视为不同场次）。损坏分片（含控制字符 / 截断）会自动修复，
  完全无法读取的分片会跳过并提示；
  - **分级选择场次**：以「平台 → 主播 → 直播场次」三级联动选择目标场次
    （切换上级会自动重置下级），场次以**年月日 + 序号 + 直播标题**（`2026-08-12
    第3场 · 到成都 特训24小时直播间`，同主播按时间连续编号、**跨天重置**，标题取该场
    首个分片的 `room_title`）显示并标注分片数；
  - **时间区间选择**：整场直播过长、数据过密会稀释高潮信号，侧边栏可框选
    「分析时间区间」（以 HH:MM:SS 显示），实时预览该区间的弹幕量，点
    「应用区间分析」后只对所选时段跑完整指标管线（拖拽区间不会反复重算）；
- **上传弹幕文件**：侧边栏可直接上传虎牙风格弹幕 XML（`st.file_uploader`），
  上传后优先于本地路径使用；也可在「数据源」填写服务器上的 XML 路径；
- **弹幕窗口可调**：侧边栏「指标参数」可动态选择弹幕聚合窗口 W（默认 10s，
  3–120s），弹幕密度、爆发速率、激活率、长度分布、集中度及高潮候选随之重算；
- 底部一条可拖拽的**全场时间轴**（以 HH:MM:SS 显示，超 24h 回退为秒）；拖拽时
  所有指标图同步高亮当前时间点；
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
├── parser.py        XML -> list[Danmaku] (uid, ts_ms, text); parse_metadata + 容错解析
├── sessions.py      分片录制 -> 整场直播聚合 (DanmakuSession / discover_sessions / load_records)
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
