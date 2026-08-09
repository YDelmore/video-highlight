"""Reporting: formatted console output and optional matplotlib charts."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import TextIO

import pandas as pd

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.activation import ActivationResult
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.concentration import ConcentrationResult
from video_highlight.metrics.density import DensityResult
from video_highlight.metrics.length_dist import LengthDistResult
from video_highlight.metrics.lifecycle import LifecycleResult
from video_highlight.metrics.overlap import OverlapResult
from video_highlight.metrics.returning import ReturningResult


def _mean_in_window(series: pd.Series, t_start: float, t_end: float) -> float | None:
    """Mean of non-NaN series values within [t_start, t_end]; None if none."""
    sel = series[(series.index >= t_start) & (series.index <= t_end)].dropna()
    return float(sel.mean()) if len(sel) else None


def _format_pct(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.1f}%"


def console_print(
    *,
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    activation: ActivationResult,
    length_dist: LengthDistResult,
    concentration: ConcentrationResult,
    overlap: OverlapResult,
    lifecycle: LifecycleResult,
    returning: ReturningResult,
    danmaku_count: int,
    duration_seconds: float,
    stream: TextIO = sys.stdout,
) -> None:
    """Print a fixed-section analysis report to ``stream``."""
    out = stream
    duration_minutes = duration_seconds / 60.0

    out.write("=== 分析概览 ===\n")
    out.write(f"弹幕总数: {danmaku_count}\n")
    out.write(f"时间跨度: {duration_seconds:.1f} 秒 ({duration_minutes:.1f} 分钟)\n")

    out.write("\n=== 指标1: 弹幕密度 (W=10s) ===\n")
    if density.sigma <= 0 or not math.isfinite(density.sigma):
        out.write("[WARN] baseline unreliable for short streams\n")
    valid = density.D.dropna()
    if len(valid):
        peak_idx = valid.idxmax()
        out.write(f"均值: μ={density.mu:.3f} / 标准差: σ={density.sigma:.3f}\n")
        out.write(f"最大值: {valid.max():.0f} / 峰时 t={peak_idx:.1f}\n")
    else:
        out.write("（无有效数据）\n")

    cand_count = sum(1 for h in highlights if h.level == "candidate")
    strong_count = sum(1 for h in highlights if h.level == "strong")
    out.write(
        f"候选区间 (D > μ+2σ): {cand_count} 个；"
        f"强候选 (D > μ+3σ): {strong_count} 个\n"
    )
    if highlights:
        out.write(_format_highlight_table(highlights))

    out.write("\n=== 指标2: 爆发速率 ===\n")
    valid_S = burst.S.dropna()
    if len(valid_S):
        out.write(f"S 均值: {burst.mu_S:.3f} / S 标准差: {burst.sigma_S:.3f}\n")
        peak_S_idx = valid_S.idxmax()
        out.write(f"最大 S: {valid_S.max():.3f} at t={peak_S_idx:.1f}\n")
        valid_Srel = burst.S_rel.dropna()
        if len(valid_Srel):
            peak_rel_idx = valid_Srel.idxmax()
            out.write(f"最大 S_rel: {valid_Srel.max():.3f} at t={peak_rel_idx:.1f}\n")
    else:
        out.write("（无有效 S 数据）\n")

    out.write("\n=== 指标3: 沉默用户激活率 ===\n")
    out.write(f"观测期: {activation.observation_seconds:.1f} 秒\n")
    out.write(
        f"沉默池: {activation.n_silent} 人 / 活跃: {activation.n_active} 人 (K=2)\n"
    )
    if activation.n_silent == 0:
        out.write("[WARN] 无沉默用户，激活率恒为 0\n")
    act = activation.activation
    act_valid = act.dropna()
    if len(act_valid):
        peak_idx = act_valid.idxmax()
        out.write(f"有效区间: t >= {activation.observation_seconds:.1f}\n")
        out.write(
            f"激活率 均值: {act_valid.mean():.3f} / "
            f"峰值: {act_valid.max():.3f} at t={peak_idx:.1f}\n"
        )
        if highlights:
            means = [
                f"#{i + 1}: {_format_pct(_mean_in_window(act, h.t_start, h.t_end))}"
                for i, h in enumerate(highlights)
            ]
            out.write("候选窗口内平均激活率:  " + "  ".join(means) + "\n")
    else:
        out.write("[WARN] 观测期覆盖全部数据，无有效激活率区间\n")

    out.write("\n=== 指标4: 弹幕长度分布 (W=10s) ===\n")
    sr, mr, lr = (
        length_dist.short_ratio,
        length_dist.mid_ratio,
        length_dist.long_ratio,
    )
    sr_valid = sr.dropna()
    if len(sr_valid):
        mask = sr_valid.index
        out.write(
            f"短/中/长占比均值: {sr[mask].mean():.3f} / "
            f"{mr[mask].mean():.3f} / {lr[mask].mean():.3f}\n"
        )
        out.write(
            f"短弹幕激增(>70%)窗口数: {int((sr_valid > 0.70).sum())}  / "
            f"长弹幕激增(>30%)窗口数: {int((lr[mask] > 0.30).sum())}\n"
        )
        if highlights:
            parts = []
            for i, h in enumerate(highlights):
                s = _mean_in_window(sr, h.t_start, h.t_end)
                l = _mean_in_window(lr, h.t_start, h.t_end)
                parts.append(f"#{i + 1}: {_format_pct(s)}/{_format_pct(l)}")
            out.write("候选窗口内平均 短/长占比:  " + "  ".join(parts) + "\n")
    else:
        out.write("（无有效长度分布数据）\n")

    out.write("\n=== 指标5: 发言集中度 (Top-3, W=10s) ===\n")
    conc = concentration.concentration
    conc_valid = conc.dropna()
    if len(conc_valid):
        peak_idx = conc_valid.idxmax()
        out.write(
            f"均值: {conc_valid.mean():.3f} / 峰值: {conc_valid.max():.3f} at t={peak_idx:.1f}\n"
        )
        if highlights:
            parts = [
                f"#{i + 1}: {_format_pct(_mean_in_window(conc, h.t_start, h.t_end))}"
                for i, h in enumerate(highlights)
            ]
            out.write("候选窗口内均值:  " + "  ".join(parts) + "\n")
    else:
        out.write("（无有效数据）\n")

    out.write("\n=== 指标6: 用户重合度 (30s窗) ===\n")
    ov = overlap.overlap
    ov_valid = ov.dropna()
    if len(ov_valid):
        out.write(f"均值: {ov_valid.mean():.3f}\n")
        drops = int((ov_valid < 0.30).sum())
        out.write(f"重合度跌破30%的窗口数: {drops}\n")
    else:
        out.write("（无有效数据）\n")

    out.write("\n=== 高潮候选区间（合并后） ===\n")
    if highlights:
        out.write(_format_highlight_table(highlights))
    else:
        out.write("（未检出候选区间；可考虑下调阈值至 1.5σ）\n")

    out.write("\n=== 指标7: 用户生命周期 ===\n")
    if lifecycle.windows:
        for w in lifecycle.windows:
            total = w.total_users
            pct = lambda n: (f"{n / total * 100:.0f}%" if total else "--")
            out.write(
                f"候选 [{w.t_start:.1f},{w.t_end:.1f}] (偏移 A={w.offset_a:.0f}s "
                f"B={w.offset_b:.0f}s C={w.offset_c:.0f}s): "
                f"瞬时 {w.instant} ({pct(w.instant)}) / "
                f"持续 {w.persistent} ({pct(w.persistent)}) / "
                f"转化 {w.converted} ({pct(w.converted)}) / 窗口用户 {total}\n"
            )
    else:
        out.write("（无候选窗口）\n")

    out.write("\n=== 指标8: 回锅用户比例 ===\n")
    if returning.windows:
        for w in returning.windows:
            ratio_str = "nan" if math.isnan(w.ratio) else f"{w.ratio * 100:.1f}%"
            line = (
                f"候选 [{w.t_start:.1f},{w.t_end:.1f}]: "
                f"回锅 {w.returning_count} / 总数 {w.total_users} → {ratio_str}"
            )
            if w.gap_start < 0:
                line += "  [静默间隙超出流起点]"
            out.write(line + "\n")
    else:
        out.write("（无候选窗口）\n")


def _format_highlight_table(highlights: list[HighlightCandidate]) -> str:
    lines = ["# | t_start | t_end | duration(s) | peak_D | level"]
    for i, h in enumerate(highlights, 1):
        lines.append(
            f"{i} | {h.t_start:.1f} | {h.t_end:.1f} | {h.duration:.1f} "
            f"| {h.peak_density:.0f} | {h.level}"
        )
    return "\n".join(lines) + "\n"


def _configure_cjk_font() -> None:
    """Prefer a CJK-capable font for Chinese chart labels, when available."""
    try:
        import matplotlib as mpl

        candidates = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"]
        available = {f.name for f in mpl.font_manager.fontManager.ttflist}
        for name in candidates:
            if name in available:
                mpl.rcParams["font.family"] = "sans-serif"
                mpl.rcParams["font.sans-serif"] = [name]
                return
    except Exception:  # pragma: no cover - best-effort
        return


def plot(
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    *,
    activation: ActivationResult,
    length_dist: LengthDistResult,
    concentration: ConcentrationResult,
    overlap: OverlapResult,
    lifecycle: LifecycleResult,
    returning: ReturningResult,
    output_path: str | Path,
) -> bool:
    """Render a 3x3 chart to ``output_path``. Return False if matplotlib unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    _configure_cjk_font()

    fig, axes = plt.subplots(3, 3, figsize=(16, 12))

    ax = axes[0, 0]
    ax.plot(density.D.index, density.D.values, label="D(t)", color="tab:blue")
    if density.sigma > 0:
        ax.axhline(density.mu + 2 * density.sigma, color="tab:orange", linestyle="--", label="μ+2σ")
        ax.axhline(density.mu + 3 * density.sigma, color="tab:red", linestyle="--", label="μ+3σ")
    ax.set_title("弹幕密度 D(t)")
    ax.set_xlabel("t (s)")
    ax.set_ylabel("bullets / 10s")
    ax.legend(loc="best")

    ax = axes[0, 1]
    ax.plot(burst.S.index, burst.S.values, label="S(t)", color="tab:purple")
    if burst.sigma_S > 0:
        ax.axhline(3 * burst.sigma_S, color="tab:red", linestyle="--", label="3σ")
    ax.set_title("爆发速率 S(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    ax = axes[0, 2]
    ax.plot(activation.activation.index, activation.activation.values, label="activation(t)", color="tab:red")
    for pct in (0.4, 0.6, 0.8):
        ax.axhline(pct, color="tab:gray", linestyle=":", linewidth=0.8)
    ax.set_title("沉默用户激活率")
    ax.set_xlabel("t (s)")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="best")

    ax = axes[1, 0]
    ax.plot(burst.S_rel.index, burst.S_rel.values, label="S_rel(t)", color="tab:green")
    ax.set_title("相对爆发速率 S_rel(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    ax = axes[1, 1]
    sr = length_dist.short_ratio
    lr = length_dist.long_ratio
    ax.plot(sr.index, sr.values, label="short", color="tab:blue")
    ax.plot(lr.index, lr.values, label="long", color="tab:orange")
    ax.axhline(0.70, color="tab:gray", linestyle=":", linewidth=0.8)
    ax.axhline(0.30, color="tab:gray", linestyle=":", linewidth=0.8)
    ax.set_title("弹幕长度分布 (短/长)")
    ax.set_xlabel("t (s)")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="best")

    ax = axes[1, 2]
    valid = density.D.dropna()
    ax.vlines(valid.index, 0, valid.values, color="tab:gray", alpha=0.6)
    ax.set_title("密度柱状视图")
    ax.set_xlabel("t (s)")

    ax = axes[2, 0]
    ax.plot(concentration.concentration.index, concentration.concentration.values, label="top3 share", color="tab:brown")
    ax.set_title("发言集中度 (Top-3)")
    ax.set_xlabel("t (s)")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="best")

    ax = axes[2, 1]
    ax.plot(overlap.overlap.index, overlap.overlap.values, label="overlap", color="tab:cyan")
    ax.axhline(0.30, color="tab:gray", linestyle=":", linewidth=0.8)
    ax.set_title("用户重合度 (Jaccard)")
    ax.set_xlabel("t (s)")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="best")

    ax = axes[2, 2]
    ax.plot(density.D.index, density.D.values, color="tab:blue", alpha=0.6)
    for h in highlights:
        ax.axvspan(h.t_start, h.t_end, color="tab:orange", alpha=0.25)
    ax.set_title("候选窗口")
    ax.set_xlabel("t (s)")
    ax.set_ylabel("D(t)")

    fig.tight_layout()
    fig.savefig(Path(output_path), dpi=120)
    plt.close(fig)
    return True
