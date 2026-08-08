# video-highlight

A tool that surfaces highlight candidates in livestream danmaku data.

## Status

Currently implements only **indicators 1 + 2** (弹幕密度 / 爆发速率) of the
19-indicator strategy in `docs/分析策略.md`. The data layer is shaped so
indicators 3 + 4 (沉默用户激活率 / 弹幕长度分布) can be added without touching
existing code — `loader.to_dataframe` already carries `uid` and `length`.

## Install

```bash
uv sync                  # core deps (pandas, numpy)
uv sync --extra plot     # + matplotlib for charting
uv sync --extra dev      # + pytest for tests
```

## Usage

```bash
uv run video-highlight path/to/danmaku.xml
uv run video-highlight path/to/danmaku.xml --plot chart.png
```

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
│   ├── _window.py   time-based rolling window helper (reused by later metrics)
│   ├── density.py   metric 1 (弹幕密度)
│   └── burst.py     metric 2 (爆发速率)
├── highlights.py    candidate segmentation (μ+2σ / μ+3σ)
└── report.py        console + optional matplotlib chart
```

See `docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md`
for the full design and `docs/分析策略.md` for the 19-indicator strategy.
