"""Plotly figure builders for the analysis platform.

Pure figure functions (no streamlit imports) so the chart construction is
unit-testable and the Streamlit app only wires them to widgets. Every chart
carries the master-clock vertical line (``t_current``) so dragging the bottom
timeline highlights the current value across all metrics at once.

Colours follow the project dataviz convention: series use categorical slots,
the composite heat hero uses a sequential blue step, and the S/A/B/C climax
grades reuse the fixed status palette (red/orange/yellow/green) — the grade
letter always travels with the colour.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.graph_objects as go

from video_highlight.metrics.activation import ActivationResult
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.concentration import ConcentrationResult
from video_highlight.metrics.density import DensityResult
from video_highlight.metrics.length_dist import LengthDistResult
from video_highlight.metrics.overlap import OverlapResult
from video_highlight.scoring import GRADE_COLORS, ScoredCandidate

# --- chrome / ink (light surface #fcfcfb) ---
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# --- series colours (categorical slots) ---
DENSITY = "#2a78d6"     # slot 1 blue
BURST = "#eb6834"       # slot 2 orange
ACTIVATION = "#1baf7a"  # slot 3 aqua
SHORT = "#eda100"       # slot 4 yellow
LONG = "#008300"        # slot 6 green
CONCENTRATION = "#e87ba4"  # slot 5 magenta
OVERLAP = "#4a3aa7"     # slot 7 violet
HEAT = "#256abf"        # sequential blue step 500

# --- reference lines ---
REF_HL = "#e34948"  # slot 8 red (μ+3σ / 3σ)
REF_MID = "#eb6834"  # orange (μ+2σ)
REF_DOT = "#898781"  # dotted threshold guides

_X_TITLE = "t (s)"


def _base_layout(
    *,
    title: str,
    y_title: str | None = None,
    height: int = 220,
    showlegend: bool = False,
    y_range: tuple[float | None, float | None] | None = None,
    clickmode: bool = False,
) -> go.Layout:
    layout = go.Layout(
        title=dict(text=title, x=0.02, font=dict(size=15, color=INK)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family='system-ui, -apple-system, "Segoe UI", sans-serif',
            color=INK,
        ),
        xaxis=dict(
            title=dict(text=_X_TITLE, font=dict(size=11, color=MUTED)),
            gridcolor=GRID,
            zerolinecolor=AXIS,
            tickfont=dict(size=10, color=MUTED),
            linecolor=AXIS,
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(size=11, color=MUTED)),
            gridcolor=GRID,
            zerolinecolor=AXIS,
            tickfont=dict(size=10, color=MUTED),
            linecolor=AXIS,
            range=list(y_range) if y_range else None,
        ),
        margin=dict(l=8, r=8, t=38, b=8),
        height=height,
        showlegend=showlegend,
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor=AXIS,
            font=dict(color=INK, family='system-ui, "Segoe UI", sans-serif'),
        ),
    )
    if clickmode:
        layout.update(clickmode="event+select")
    return layout


def _add_vline(fig: go.Figure, t_current: float, *, annotate: bool = False) -> None:
    """Dashed master-clock line at ``t_current`` (no-op when it can't be shown)."""
    if t_current is None or pd.isna(t_current):
        return
    kwargs: dict = dict(
        x=float(t_current),
        line=dict(color=INK, width=1.5, dash="dash"),
        layer="above",
    )
    if annotate:
        kwargs["annotation_text"] = f"当前 t={float(t_current):.0f}s"
        kwargs["annotation_position"] = "top right"
        kwargs["annotation_font"] = dict(color=INK, size=11)
    fig.add_vline(**kwargs)


def _ref_hline(fig: go.Figure, value: float, color: str, dash: str = "dot") -> None:
    fig.add_hline(y=value, line=dict(color=color, width=1, dash=dash))


def line_figure(
    *,
    title: str,
    series: Iterable[tuple[str, pd.Series, str]],
    y_title: str | None = None,
    y_range: tuple[float | None, float | None] | None = None,
    ref_lines: Iterable[tuple[float, str, str]] = (),
    t_current: float | None = None,
    height: int = 220,
    showlegend: bool = False,
) -> go.Figure:
    """Generic one-axis line chart for a metric's raw time series.

    ``series`` is (label, Series indexed by t, colour). ``ref_lines`` are
    (y value, colour, dash). NaN samples are left as gaps (no bridging).
    """
    fig = go.Figure()
    for label, s, color in series:
        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s.values,
                mode="lines",
                name=label,
                line=dict(color=color, width=2),
                connectgaps=False,
                hoverinfo="y" if label else "skip",
                hovertemplate="%{y:.2f}<extra>%{fullData.name}</extra>",
            )
        )
    for value, color, dash in ref_lines:
        _ref_hline(fig, value, color, dash)
    _add_vline(fig, t_current)
    fig.update_layout(
        _base_layout(
            title=title,
            y_title=y_title,
            height=height,
            showlegend=showlegend,
            y_range=y_range,
        )
    )
    return fig


# ---------------------------------------------------------------------------
# Metric charts
# ---------------------------------------------------------------------------

def density_figure(density: DensityResult, t_current: float | None = None) -> go.Figure:
    refs: list[tuple[float, str, str]] = []
    if density.sigma > 0:
        refs.append((density.mu + 2 * density.sigma, REF_MID, "dash"))
        refs.append((density.mu + 3 * density.sigma, REF_HL, "dash"))
    return line_figure(
        title="指标1 · 弹幕密度 D(t)",
        y_title="条 / 10s",
        series=[("D(t)", density.D, DENSITY)],
        ref_lines=refs,
        t_current=t_current,
    )


def burst_figure(burst: BurstResult, t_current: float | None = None) -> go.Figure:
    refs: list[tuple[float, str, str]] = []
    if burst.sigma_S > 0:
        refs.append((3 * burst.sigma_S, REF_HL, "dash"))
    return line_figure(
        title="指标2 · 爆发速率 S(t)",
        y_title="弹幕差 / 步",
        series=[("S(t)", burst.S, BURST)],
        ref_lines=refs,
        t_current=t_current,
    )


def activation_figure(
    activation: ActivationResult, t_current: float | None = None
) -> go.Figure:
    return line_figure(
        title="指标3 · 沉默用户激活率",
        y_title="比例",
        series=[("activation(t)", activation.activation, ACTIVATION)],
        y_range=(0, 1),
        ref_lines=[(0.4, REF_DOT, "dot"), (0.6, REF_DOT, "dot"), (0.8, REF_DOT, "dot")],
        t_current=t_current,
    )


def length_figure(
    length_dist: LengthDistResult, t_current: float | None = None
) -> go.Figure:
    return line_figure(
        title="指标4 · 弹幕长度分布 (短/长)",
        y_title="占比",
        series=[
            ("短弹幕 ≤5字", length_dist.short_ratio, SHORT),
            ("长弹幕 >15字", length_dist.long_ratio, LONG),
        ],
        y_range=(0, 1),
        ref_lines=[(0.7, REF_DOT, "dot"), (0.3, REF_DOT, "dot")],
        t_current=t_current,
        showlegend=True,
    )


def concentration_figure(
    concentration: ConcentrationResult, t_current: float | None = None
) -> go.Figure:
    return line_figure(
        title="指标5 · 发言集中度 (Top-3占比)",
        y_title="占比（低=群体共鸣）",
        series=[("Top-3 占比", concentration.concentration, CONCENTRATION)],
        y_range=(0, 1),
        ref_lines=[(0.6, REF_DOT, "dot")],
        t_current=t_current,
    )


def overlap_figure(overlap: OverlapResult, t_current: float | None = None) -> go.Figure:
    return line_figure(
        title="指标6 · 用户重合度 (Jaccard)",
        y_title="重合度（低=新事件）",
        series=[("overlap(t)", overlap.overlap, OVERLAP)],
        y_range=(0, 1),
        ref_lines=[(0.3, REF_DOT, "dot")],
        t_current=t_current,
    )


# ---------------------------------------------------------------------------
# Composite heat (hero) and clickable climax event map
# ---------------------------------------------------------------------------

def _grade_text_color(grade: str) -> str:
    """Dark text on yellow bands, white elsewhere (light surface contrast)."""
    return "#0b0b0b" if grade == "B" else "#ffffff"


def heat_figure(
    heat: pd.Series,
    candidates: list[ScoredCandidate],
    t_current: float | None = None,
) -> go.Figure:
    """Composite heat H(t) as a filled area, with grade-coloured climax bands."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=heat.index,
            y=heat.values,
            mode="lines",
            name="综合热度 H(t)",
            line=dict(color=HEAT, width=2),
            fill="tozeroy",
            fillcolor="rgba(37,107,191,0.15)",
            connectgaps=False,
            hovertemplate="%{y:.3f}<extra>综合热度</extra>",
        )
    )
    for c in candidates:
        color = GRADE_COLORS.get(c.grade, GRADE_COLORS[""])
        fig.add_shape(
            type="rect",
            x0=c.t_start,
            x1=c.t_end,
            y0=0,
            y1=1,
            fillcolor=color,
            opacity=0.22,
            line=dict(color=color, width=1),
            layer="below",
        )
        fig.add_annotation(
            x=(c.t_start + c.t_end) / 2,
            y=0.96,
            text=c.grade,
            showarrow=False,
            font=dict(size=12, color=color),
        )
    _add_vline(fig, t_current, annotate=True)
    fig.update_layout(
        _base_layout(
            title="综合热度曲线 H(t)（0-1，各指标加权）",
            y_title="热度",
            height=280,
            y_range=(0, 1),
        )
    )
    return fig


def event_map_figure(
    candidates: list[ScoredCandidate],
    duration: float,
    t_current: float | None = None,
) -> go.Figure:
    """Clickable climax timeline: one grade-coloured band per climax.

    Each band is a horizontal ``go.Bar`` carrying ``customdata=[idx, t_start,
    t_end, score, grade]``. Streamlit's ``selection_mode="points"`` makes the
    band clickable — the app reads the index and jumps the clock to
    ``t_start``.
    """
    fig = go.Figure()
    if candidates:
        base = [c.t_start for c in candidates]
        widths = [max(c.t_end - c.t_start, 1.0) for c in candidates]
        colors = [GRADE_COLORS.get(c.grade, GRADE_COLORS[""]) for c in candidates]
        letters = [c.grade if c.grade else "·" for c in candidates]
        text_colors = [
            _grade_text_color(c.grade) if c.grade else INK for c in candidates
        ]
        custom = [
            [i, c.t_start, c.t_end, round(c.score, 3), c.grade]
            for i, c in enumerate(candidates)
        ]
        fig.add_trace(
            go.Bar(
                orientation="h",
                y=[0] * len(candidates),
                base=base,
                x=widths,
                marker=dict(color=colors, line=dict(width=0)),
                text=letters,
                textfont=dict(size=11, color=text_colors),
                textposition="inside",
                customdata=custom,
                hovertemplate=(
                    "<b>高潮 #%{customdata[0]}</b> "
                    "等级 %{customdata[4]}<br>"
                    "[%{customdata[1]:.0f}, %{customdata[2]:.0f}]s · "
                    "评分 %{customdata[3]:.3f}<br>"
                    "<b>点击跳转到该高潮起点</b><extra></extra>"
                ),
                cliponaxis=False,
            )
        )
    _add_vline(fig, t_current, annotate=True)
    fig.update_layout(
        _base_layout(
            title="高潮事件图谱（点击色带跳转到高潮起点）",
            height=96,
            clickmode=True,
        )
    )
    fig.update_xaxes(range=[0, float(duration)])
    fig.update_yaxes(range=[-0.4, 0.4], showticklabels=False, visible=False)
    return fig
