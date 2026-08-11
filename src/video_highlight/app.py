"""Streamlit analysis platform for livestream danmaku highlights.

A lightweight interactive dashboard over the already-implemented metrics
(dimension 1 热度与规模 / dimension 2 用户行为与参与模式). Features:

- dimension weights + per-indicator weights -> per-second composite heat H(t)
- S/A/B/C grading of detected climax intervals and the whole stream
- a bottom **master timeline** that drives every chart (all metrics highlight
  the current time)
- climax bands coloured by grade on the timeline; clicking a band (or the
  chip below it) jumps the clock to that climax's start

Run: ``uv run streamlit run src/video_highlight/app.py``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from video_highlight import charts
from video_highlight.exceptions import DanmakuParseError
from video_highlight.highlights import HighlightCandidate, find_candidates
from video_highlight.loader import to_dataframe
from video_highlight.metrics.activation import (
    ActivationResult,
    compute as compute_activation,
)
from video_highlight.metrics.burst import (
    BurstResult,
    compute as compute_burst,
)
from video_highlight.metrics.concentration import (
    ConcentrationResult,
    compute as compute_concentration,
)
from video_highlight.metrics.density import (
    DensityResult,
    compute as compute_density,
)
from video_highlight.metrics.length_dist import (
    LengthDistResult,
    compute as compute_length_dist,
)
from video_highlight.metrics.lifecycle import (
    LifecycleResult,
    compute as compute_lifecycle,
)
from video_highlight.metrics.overlap import (
    OverlapResult,
    compute as compute_overlap,
)
from video_highlight.metrics.returning import (
    ReturningResult,
    compute as compute_returning,
)
from video_highlight.parser import Danmaku, parse_xml
from video_highlight.scoring import (
    GRADE_COLORS,
    GradeThresholds,
    MetricWeights,
    score_all,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XML = PROJECT_ROOT / "docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml"


@dataclass
class Analysis:
    """All raw metric results for one XML, produced once per file."""

    df: pd.DataFrame
    density: DensityResult
    burst: BurstResult
    activation: ActivationResult
    length_dist: LengthDistResult
    concentration: ConcentrationResult
    overlap: OverlapResult
    lifecycle: LifecycleResult
    returning: ReturningResult
    highlights: list[HighlightCandidate]
    duration: float
    n_records: int


@st.cache_data
def load_analysis(xml_path: str) -> Analysis:
    """Parse + run every implemented metric; cached per XML path."""
    return _build_analysis(parse_xml(xml_path))


@st.cache_data
def load_analysis_upload(xml_name: str, xml_bytes: bytes) -> Analysis:
    """Same pipeline for an uploaded file; cached per (name, content)."""
    return _build_analysis(parse_xml(xml_bytes, name=xml_name))


def _build_analysis(records: list[Danmaku]) -> Analysis:
    """Run every implemented metric over parsed records (uncached core)."""
    df = to_dataframe(records)
    density = compute_density(df)
    burst = compute_burst(density)
    highlights = find_candidates(density)
    return Analysis(
        df=df,
        density=density,
        burst=burst,
        activation=compute_activation(df),
        length_dist=compute_length_dist(df),
        concentration=compute_concentration(df),
        overlap=compute_overlap(df),
        lifecycle=compute_lifecycle(df, highlights),
        returning=compute_returning(df, highlights),
        highlights=highlights,
        duration=float(density.duration_seconds),
        n_records=len(records),
    )


# --------------------------------------------------------------------------
# Callbacks (run before the script body, so a jump lands the same rerun)
# --------------------------------------------------------------------------

def _on_timeline_changed() -> None:
    st.session_state["current_time"] = float(st.session_state["timeline_slider"])


def _jump_to_candidate(idx: int) -> None:
    result = st.session_state.get("analysis")
    if not result or idx >= len(result.scored_candidates):
        return
    st.session_state["jump_to"] = float(result.scored_candidates[idx].t_start)


def _on_event_map_select() -> None:
    """Read the clicked climax band (customdata[0] = candidate index)."""
    event = st.session_state.get("climax_map")
    if not event:
        return
    selection = getattr(event, "selection", None)
    points = getattr(selection, "points", None) if selection is not None else None
    if not points:
        return
    custom = points[0].get("customdata")
    if custom:
        _jump_to_candidate(int(custom[0]))


def _jump_button(idx: int) -> None:
    _jump_to_candidate(idx)


def _grade_legend() -> None:
    """Coloured chips for the S/A/B/C ladder (status colour always with a label)."""
    names = {
        "S": "S 级 · 红",
        "A": "A 级 · 橙",
        "B": "B 级 · 黄",
        "C": "C 级 · 绿",
        "": "未定级 · 灰",
    }
    chips = "".join(
        (
            f'<span style="display:inline-block;margin:2px 10px 2px 0;padding:2px 10px;'
            f'border-radius:10px;background:{GRADE_COLORS[g]};'
            f'color:{"#0b0b0b" if g == "B" else "#ffffff"};font-size:12px;">{names[g]}</span>'
        )
        for g in ("S", "A", "B", "C", "")
    )
    st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------------

def _sidebar_controls() -> tuple[object | None, str, MetricWeights, GradeThresholds]:
    st.sidebar.header("数据源")
    uploaded = st.sidebar.file_uploader(
        "上传弹幕 XML 文件",
        type=["xml"],
        key="uploaded_xml",
        help="直接上传虎牙风格弹幕 XML；上传后优先使用上传的文件。",
    )
    xml_input = st.sidebar.text_input(
        "或填写服务器上的 XML 路径", value=str(DEFAULT_XML), key="xml_path"
    )

    st.sidebar.header("权重配置")
    dim_heat = st.sidebar.slider(
        "维度一 · 热度与规模", 0.0, 1.0, 0.60, 0.05, key="dim_heat",
        help="维度一（指标1-4）占总评分的比重；维度二自动补全为剩余部分。",
    )
    dim_behavior = round(1.0 - dim_heat, 4)
    st.sidebar.caption(f"维度二 · 用户行为与参与模式 = {dim_behavior:.2f}（自动补全）")

    st.sidebar.markdown("**维度一内指标**（滑动后自动归一）")
    dim1_raw = [
        st.sidebar.slider("指标1 弹幕密度", 0.0, 1.0, 0.30, 0.05, key="w_density"),
        st.sidebar.slider("指标2 爆发速率", 0.0, 1.0, 0.20, 0.05, key="w_burst"),
        st.sidebar.slider("指标3 沉默用户激活率", 0.0, 1.0, 0.35, 0.05, key="w_activation"),
        st.sidebar.slider("指标4 弹幕长度分布", 0.0, 1.0, 0.15, 0.05, key="w_length"),
    ]
    s1 = sum(dim1_raw) or 1.0

    st.sidebar.markdown("**维度二内指标**（滑动后自动归一）")
    dim2_raw = [
        st.sidebar.slider("指标5 发言集中度", 0.0, 1.0, 0.30, 0.05, key="w_concentration"),
        st.sidebar.slider("指标6 用户重合度", 0.0, 1.0, 0.20, 0.05, key="w_overlap"),
        st.sidebar.slider("指标7 用户生命周期", 0.0, 1.0, 0.30, 0.05, key="w_lifecycle"),
        st.sidebar.slider("指标8 回锅用户比例", 0.0, 1.0, 0.20, 0.05, key="w_returning"),
    ]
    s2 = sum(dim2_raw) or 1.0

    weights = MetricWeights(
        dim_heat=dim_heat,
        dim_behavior=dim_behavior,
        density=dim1_raw[0] / s1,
        burst=dim1_raw[1] / s1,
        activation=dim1_raw[2] / s1,
        length_dist=dim1_raw[3] / s1,
        concentration=dim2_raw[0] / s2,
        overlap=dim2_raw[1] / s2,
        lifecycle=dim2_raw[2] / s2,
        returning=dim2_raw[3] / s2,
    )

    st.sidebar.header("分级阈值")
    thresholds = GradeThresholds(
        s=st.sidebar.number_input("S 阈值", 0.0, 1.0, 0.75, 0.05, key="th_s"),
        a=st.sidebar.number_input("A 阈值", 0.0, 1.0, 0.60, 0.05, key="th_a"),
        b=st.sidebar.number_input("B 阈值", 0.0, 1.0, 0.45, 0.05, key="th_b"),
        c=st.sidebar.number_input("C 阈值", 0.0, 1.0, 0.30, 0.05, key="th_c"),
    )
    return uploaded, xml_input, weights, thresholds


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

st.set_page_config(page_title="直播弹幕高潮分析平台", page_icon="📊", layout="wide")
st.title("直播弹幕高潮分析平台")
st.caption(
    "维度一 热度与规模 · 维度二 用户行为与参与模式｜"
    "拖拽底部时间轴联动所有图表，点击高潮色带跳转到该高潮起点"
)

# --- master clock: single source of truth for the current time ---
if "current_time" not in st.session_state:
    st.session_state["current_time"] = 0.0

jump = st.session_state.pop("jump_to", None)
if jump is not None:
    st.session_state["current_time"] = float(jump)
    st.session_state["timeline_slider"] = float(jump)  # move the slider widget
t_current = float(st.session_state.get("current_time", 0.0))

uploaded, xml_input, weights, thresholds = _sidebar_controls()

if uploaded is not None:
    try:
        analysis = load_analysis_upload(uploaded.name, uploaded.getvalue())
    except DanmakuParseError as exc:
        st.error(f"解析上传文件失败（{uploaded.name}）：{exc}")
        st.stop()
    source_label = f"已上传：{uploaded.name}"
else:
    if not Path(xml_input).is_file():
        st.error(f"找不到弹幕文件：{xml_input}")
        st.info("请在上方上传弹幕 XML 文件，或在侧边栏「数据源」填入正确的路径。")
        st.stop()
    analysis = load_analysis(str(xml_input))
    source_label = f"本地文件：{xml_input}"

if analysis.n_records == 0:
    st.warning("该 XML 未解析出任何弹幕。")
    st.stop()

st.caption(f"数据源：{source_label}")

result = score_all(
    density=analysis.density,
    burst=analysis.burst,
    activation=analysis.activation,
    length_dist=analysis.length_dist,
    concentration=analysis.concentration,
    overlap=analysis.overlap,
    highlights=analysis.highlights,
    lifecycle=analysis.lifecycle,
    returning=analysis.returning,
    weights=weights,
    thresholds=thresholds,
)
st.session_state["analysis"] = result

# --- headline metrics ---
st.markdown("---")
cols = st.columns(6)
overall_grade_label = result.overall_grade if result.overall_grade else "未定级"
cols[0].metric(
    "全场综合评分",
    f"{result.overall_score:.3f}",
    delta=f"等级 {overall_grade_label}",
    delta_color="off",
)
best = max(result.scored_candidates, key=lambda c: c.score, default=None)
cols[1].metric(
    "最佳高潮",
    f"等级 {best.grade}" if best and best.grade else "无",
    delta=f"评分 {best.score:.3f}" if best else None,
    delta_color="off",
)
cols[2].metric("弹幕总数", f"{analysis.n_records:,}")
cols[3].metric("时间跨度", f"{analysis.duration / 60:.1f} 分钟")
cols[4].metric("高潮区间", f"{result.n_candidates} 个")
gc = result.grade_counts
cols[5].metric("S / A / B / C", f"{gc['S']} / {gc['A']} / {gc['B']} / {gc['C']}")

# --- hero: composite heat + grade-coloured climax bands ---
st.plotly_chart(
    charts.heat_figure(result.heat, result.scored_candidates, t_current),
    width="stretch",
)

# --- the six per-second metric charts, all linked to the master clock ---
col_a, col_b = st.columns(2)
with col_a:
    st.plotly_chart(
        charts.density_figure(analysis.density, t_current), width="stretch"
    )
    st.plotly_chart(
        charts.activation_figure(analysis.activation, t_current),
        width="stretch",
    )
    st.plotly_chart(
        charts.concentration_figure(analysis.concentration, t_current),
        width="stretch",
    )
with col_b:
    st.plotly_chart(
        charts.burst_figure(analysis.burst, t_current), width="stretch"
    )
    st.plotly_chart(
        charts.length_figure(analysis.length_dist, t_current), width="stretch"
    )
    st.plotly_chart(
        charts.overlap_figure(analysis.overlap, t_current), width="stretch"
    )

# --- climax event map: clickable, grade-coloured timeline ---
st.markdown("---")
st.subheader("高潮事件图谱")
_grade_legend()
if result.scored_candidates:
    st.plotly_chart(
        charts.event_map_figure(result.scored_candidates, analysis.duration, t_current),
        width="stretch",
        key="climax_map",
        on_select=_on_event_map_select,
        selection_mode="points",
    )
    st.caption("提示：点击上方色带，或下方任一高潮按钮，时间轴即跳转到该高潮起点。")
    chip_cols = st.columns(len(result.scored_candidates))
    for i, (col, cand) in enumerate(zip(chip_cols, result.scored_candidates)):
        with col:
            st.button(
                f"{cand.grade or '未定级'} · {cand.t_start:.0f}s",
                key=f"jump_{i}",
                on_click=_jump_button,
                args=(i,),
                width="stretch",
            )
else:
    st.info("未检出高潮候选区间（可更换数据源或下调密度阈值后重试）。")

# --- candidate detail table ---
st.markdown("---")
st.subheader("高潮明细")
if result.scored_candidates:
    rows = [
        {
            "#": i + 1,
            "等级": c.grade if c.grade else "未定级",
            "区间 (s)": f"[{c.t_start:.0f}, {c.t_end:.0f}]",
            "时长 (s)": f"{c.duration:.0f}",
            "综合评分": round(c.score, 3),
            "峰值热度": round(c.heat_peak, 3),
            "峰值密度": round(c.peak_density, 0),
            "转化用户占比": f"{c.converted_ratio * 100:.0f}%",
            "回锅用户占比": f"{c.returning_ratio * 100:.0f}%",
            "检出级别": c.base_level,
        }
        for i, c in enumerate(result.scored_candidates)
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.info("无高潮明细。")

# --- bottom master timeline (drives every chart above) ---
st.markdown("---")
st.slider(
    "⏱️ 全场时间轴（主控：拖拽联动所有图表高亮当前值）",
    min_value=0.0,
    max_value=max(analysis.duration, 1.0),
    value=t_current,
    step=1.0,
    key="timeline_slider",
    on_change=_on_timeline_changed,
)
st.caption(
    "综合评分 = 各指标归一化热度的加权平均（维度权重 × 指标权重）。"
    "分级阈值：S/A/B/C 见侧边栏；评分低于 C 阈值的候选记为「未定级」。"
)
