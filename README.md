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
- **高潮检测参数**（「高潮检测参数」展开面板）：阈值基线（`sigma`=μ+kσ 策略默认 /
  `robust`=中位数+k·MAD 抗离群尖峰 / `percentile`=密度分位数）、候选/强候选
  阈值倍数、最短候选时长（过滤单秒噪声尖峰）、候选合并间隔，以及**刷屏假峰过滤**
  的两个阈值（重复文本占比 + Top-3 集中度，详见下）；调整后整条候选管线重算；
- **刷屏假峰过滤**：抽奖/机器人刷屏会造成纯密度假峰。按窗口内**重复文本占比**与
  **Top-3 发言集中度**联合判定——两者同时超标（默认重复≥80% 且 Top-3≥60%，
  即少数人垄断刷屏）的秒被排除出候选；多人自发刷同一句的**队形仪式**集中度低，
  不会被误杀（与指标12 的"复制率高+集中度低=真仪式"一致）；
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

### 高潮检测参数（CLI）

```bash
uv run video-highlight danmaku.xml --threshold-mode robust --min-duration 5
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--threshold-mode` | `sigma` | `sigma`=μ+kσ（策略默认）；`robust`=中位数+k·MAD，抗单个极端尖峰抬高阈值遮蔽真实信号；`percentile`=密度曲线分位数 |
| `--candidate-sigma` | 2.0 | 候选阈值倍数（μ/中位数 + k·σ/MAD） |
| `--strong-sigma` | 3.0 | 强候选阈值倍数 |
| `--min-duration` | 3 | 丢弃短于此的候选（秒），过滤单秒噪声尖峰 |
| `--merge-gap` | 30 | 间隔短于此且用户重合度达标的相邻候选合并为一段 |
| `--no-spam-filter` | 关 | 关闭重复文本（刷屏）假峰过滤 |

候选合并还受**用户重合度**约束（指标6）：两个间隔 < `--merge-gap` 的区间，
只有重合度 ≥ 50% 才合并——避免把"时间上挨得近但人群不同的两个事件"误并成
一个高潮。

## 高潮切片（把检测结果切成视频片段）

```bash
# 单个文件：自动定位同目录同名前缀的视频（.flv/.mp4/...）
uv run python -m video_highlight.clip_cli docs/xxx.xml --out clips

# 整场直播：传分片根目录，自动按场次聚合 + 每个候选跨分片定位
uv run python -m video_highlight.clip_cli E:/huya/HuYa/主播 --out clips

# 只打印 ffmpeg 命令不执行；快速模式用 -c copy
uv run python -m video_highlight.clip_cli xxx.xml --dry-run
uv run python -m video_highlight.clip_cli xxx.xml --fast
```

时间模型：弹幕 t=0 锚定在首条弹幕的 `ts_ms`（与分析平台一致），视频分片的
起始时刻取自文件名的 `yyyy-MM-dd-HH-mm-ss-fff` 前缀（与录制器命名一致）；
高潮区间加**前后缓冲**（默认前 10s ≥ 弹幕窗口 W / 后 15s 让余波完整）、按时长
上限截断（默认 300s，以峰值为中心），然后逐分片求交得到 `(文件, 片内偏移)`，
生成 ffmpeg 命令（精确模式 h264+aac 重编码帧级精确；`--fast` 关键帧对齐秒出）。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--pre-roll` / `--post-roll` | 10 / 15 | 高潮前后缓冲（秒） |
| `--max-duration` | 300 | 单条切片时长上限（0=不限） |
| `--fast` | 关 | `-c copy` 快速切割（起点偏差 ≤1 GOP） |
| `--anchor-ms` | 首条弹幕 | 弹幕 t=0 的墙钟毫秒（录制器先开后播时用来校准） |
| `--threshold-mode` 等 | 同检测 CLI | 检测参数与 `video-highlight` 一致 |

输出：每条候选一个 mp4（`clip_{序号}_{等级}_{形态}_{起}-{止}.mp4`，跨分片的
候选按段输出 `_p1/_p2/...`），切片后用 ffprobe 校验时长与音视频流，并写一份
**`manifest.csv`**（候选 → 源文件 → 片内偏移 → 输出 → 校验状态），下游上传/
审核直接消费，重复运行幂等覆盖。

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
│   ├── returning.py     metric 8 (回锅用户比例)
│   └── repeat.py        重复文本刷屏检测（假峰过滤 + spam_exclude_mask）
├── clipper.py       高潮切片：候选→墙钟区间→分片偏移→ffmpeg 命令→manifest
├── clip_cli.py      python -m video_highlight.clip_cli <xml|root> 切片入口
├── highlights.py    candidate segmentation (σ/robust/percentile 阈值,
│                    exclude 掩码, 重合度合并, 最短时长, 形态分类)
├── scoring.py       composite scoring: weights -> heat H(t) -> S/A/B/C grades
├── charts.py        Plotly figure builders (linked to the master clock)
├── app.py           Streamlit analysis platform
└── report.py        console + optional matplotlib chart
```

See `docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md`
for the full design and `docs/分析策略.md` for the 19-indicator strategy.
