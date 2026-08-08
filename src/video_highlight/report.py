"""Reporting: formatted console output and optional matplotlib charts."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import TextIO

import pandas as pd

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.density import DensityResult


def console_print(
    *,
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
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

    out.write("\n=== 高潮候选区间（合并后） ===\n")
    if highlights:
        out.write(_format_highlight_table(highlights))
    else:
        out.write("（未检出候选区间；可考虑下调阈值至 1.5σ）\n")


def _format_highlight_table(highlights: list[HighlightCandidate]) -> str:
    lines = ["# | t_start | t_end | duration(s) | peak_D | level"]
    for i, h in enumerate(highlights, 1):
        lines.append(
            f"{i} | {h.t_start:.1f} | {h.t_end:.1f} | {h.duration:.1f} "
            f"| {h.peak_density:.0f} | {h.level}"
        )
    return "\n".join(lines) + "\n"


def _configure_cjk_font() -> None:
    """Prefer a CJK-capable font for Chinese chart labels, when available.

    matplotlib's default fonts lack CJK glyphs (titles render as boxes).
    Silently no-ops if no CJK font is installed; the caller keeps working.
    """
    try:
        import matplotlib as mpl

        candidates = [
            "Microsoft YaHei",  # Windows
            "SimHei",  # Windows fallback
            "PingFang SC",  # macOS
            "Noto Sans CJK SC",  # Linux
        ]
        available = {f.name for f in mpl.font_manager.fontManager.ttflist}
        for name in candidates:
            if name in available:
                mpl.rcParams["font.family"] = "sans-serif"
                mpl.rcParams["font.sans-serif"] = [name]
                return
    except Exception:  # pragma: no cover - font setup is best-effort
        return


def plot(
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    *,
    output_path: str | Path,
) -> bool:
    """Render a 2x2 chart to ``output_path``. Return False if matplotlib unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    _configure_cjk_font()

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # Subplot 1: density curve + thresholds
    ax = axes[0, 0]
    ax.plot(density.D.index, density.D.values, label="D(t)", color="tab:blue")
    if density.sigma > 0:
        ax.axhline(
            density.mu + 2 * density.sigma,
            color="tab:orange",
            linestyle="--",
            label="μ+2σ",
        )
        ax.axhline(
            density.mu + 3 * density.sigma,
            color="tab:red",
            linestyle="--",
            label="μ+3σ",
        )
    ax.set_title("弹幕密度 D(t)")
    ax.set_xlabel("t (s)")
    ax.set_ylabel("bullets / 10s")
    ax.legend(loc="best")

    # Subplot 2: burst S(t)
    ax = axes[0, 1]
    ax.plot(burst.S.index, burst.S.values, label="S(t)", color="tab:purple")
    if burst.sigma_S > 0:
        ax.axhline(3 * burst.sigma_S, color="tab:red", linestyle="--", label="3σ")
    ax.set_title("爆发速率 S(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    # Subplot 3: S_rel
    ax = axes[1, 0]
    ax.plot(
        burst.S_rel.index,
        burst.S_rel.values,
        label="S_rel(t)",
        color="tab:green",
    )
    ax.set_title("相对爆发速率 S_rel(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    # Subplot 4: density stem view
    ax = axes[1, 1]
    valid = density.D.dropna()
    ax.vlines(valid.index, 0, valid.values, color="tab:gray", alpha=0.6)
    ax.set_title("密度柱状视图")
    ax.set_xlabel("t (s)")

    fig.tight_layout()
    fig.savefig(Path(output_path), dpi=120)
    plt.close(fig)
    return True
