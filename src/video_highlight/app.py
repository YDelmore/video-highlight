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
from datetime import time, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from video_highlight import charts
from video_highlight.exceptions import DanmakuParseError
from video_highlight.highlights import (
    DetectionParams,
    HighlightCandidate,
    find_candidates,
)
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
from video_highlight.metrics.repeat import (
    RepeatResult,
    compute as compute_repeat,
    spam_exclude_mask,
)
from video_highlight.metrics.returning import (
    ReturningResult,
    compute as compute_returning,
)
from video_highlight.parser import Danmaku, parse_xml
from video_highlight.sessions import (
    DanmakuSession,
    SessionNotes,
    discover_sessions,
    load_records,
)
from video_highlight.scoring import (
    GRADE_COLORS,
    GradeThresholds,
    MetricWeights,
    score_all,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XML = PROJECT_ROOT / "docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml"

FILE_MODE = "单个弹幕文件"
SESSION_MODE = "整场直播（分片聚合）"
SOURCE_MODES = (FILE_MODE, SESSION_MODE)
DEFAULT_SESSION_ROOT = "E:/huya"


@dataclass
class SourceConfig:
    """What the sidebar says about where the danmaku comes from."""

    mode: str
    uploaded: object | None
    xml_path: str
    root: str
    session: DanmakuSession | None
    interval: tuple[int, int]


@st.cache_data
def _discover_sessions_cached(
    root: str,
) -> tuple[list[DanmakuSession], list[Path]]:
    """Cached session scan (metadata-only, one head-read per file)."""
    return discover_sessions(root)


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
    window_seconds: int
    t_min: float
    spam_excluded_seconds: int = 0
    threshold_mode: str = "sigma"


@st.cache_data
def load_analysis(
    xml_path: str,
    window_seconds: int = 10,
    detection: DetectionParams = DetectionParams(),
) -> Analysis:
    """Parse + run every implemented metric; cached per (XML path, window, detection)."""
    return _build_analysis(parse_xml(xml_path), window_seconds, detection=detection)


@st.cache_data
def load_analysis_upload(
    xml_name: str,
    xml_bytes: bytes,
    window_seconds: int = 10,
    detection: DetectionParams = DetectionParams(),
) -> Analysis:
    """Same pipeline for an uploaded file; cached per (name, content, window, detection)."""
    return _build_analysis(
        parse_xml(xml_bytes, name=xml_name), window_seconds, detection=detection
    )


@st.cache_data
def load_session_records(
    session: DanmakuSession,
) -> tuple[list[Danmaku], SessionNotes]:
    """Aggregate all of a session's chunks once; cached per session."""
    return load_records(session)


@st.cache_data
def load_analysis_interval(
    session: DanmakuSession,
    window_seconds: int,
    start_seconds: int,
    end_seconds: int,
    detection: DetectionParams = DetectionParams(),
) -> tuple[Analysis, SessionNotes]:
    """Analyse the session, but only the danmaku inside ``[start, end]``.

    A full 24h stream spreads the density signal over tens of thousands of
    seconds and dilutes the highlights, so the user picks a sub-interval to
    focus on. There is no reliable ``live_start_time``, so the timeline is
    anchored at the session's first danmaku (``t=0``), matching the loader's
    default; the master slider spans the interval in place. Cached per
    (session, window, start, end, detection) so dragging the range slider only
    recomputes when the interval is actually applied.
    """
    records, notes = load_session_records(session)
    live = records[0].ts_ms if records else 0
    lo = live + start_seconds * 1000
    hi = live + end_seconds * 1000
    filtered = [r for r in records if lo <= r.ts_ms <= hi]
    return (
        _build_analysis(
            filtered, window_seconds, detection=detection, live_start_ms=live
        ),
        notes,
    )


def _build_analysis(
    records: list[Danmaku],
    window_seconds: int = 10,
    *,
    detection: DetectionParams = DetectionParams(),
    live_start_ms: int | None = None,
) -> Analysis:
    """Run every implemented metric over parsed records (uncached core).

    ``window_seconds`` is the danmaku aggregation window (default 10s): it
    drives density (and thus burst, highlights, lifecycle, returning) plus
    activation, length distribution, concentration and the repeat-text spam
    filter. Overlap keeps its own 30s design window for cross-window user
    re-entry detection.

    ``detection`` carries the highlight-detection knobs (threshold baseline,
    minimum duration, spam filter thresholds, ...). ``live_start_ms`` anchors
    the timeline for aggregated chunked sessions; when omitted (single-file
    input) the first bullet lands at t=0.
    """
    df = to_dataframe(records, live_start_ms=live_start_ms)
    density = compute_density(df, window_seconds=window_seconds)
    burst = compute_burst(density)
    concentration = compute_concentration(df, window_seconds=window_seconds)
    overlap = compute_overlap(df)
    repeat = compute_repeat(df, window_seconds=window_seconds)
    exclude = spam_exclude_mask(
        repeat,
        concentration,
        max_ratio=detection.spam_max_ratio,
        conc_threshold=detection.spam_concentration,
    )
    highlights = find_candidates(
        density,
        exclude=exclude,
        merge_overlap=overlap.overlap,
        **detection.find_kwargs(),
    )
    return Analysis(
        df=df,
        density=density,
        burst=burst,
        activation=compute_activation(df, window_seconds=window_seconds),
        length_dist=compute_length_dist(df, window_seconds=window_seconds),
        concentration=concentration,
        overlap=overlap,
        lifecycle=compute_lifecycle(df, highlights),
        returning=compute_returning(df, highlights),
        highlights=highlights,
        duration=float(density.duration_seconds),
        n_records=len(records),
        window_seconds=int(window_seconds),
        t_min=float(df["t"].min()) if not df.empty else 0.0,
        spam_excluded_seconds=int(exclude.sum()),
        threshold_mode=detection.threshold_mode,
    )


# --------------------------------------------------------------------------
# Callbacks (run before the script body, so a jump lands the same rerun)
# --------------------------------------------------------------------------

def _t_to_time(seconds: float) -> time:
    """Seconds since stream origin -> naive ``time`` (HH:MM:SS, wraps at 24h)."""
    seconds = max(int(seconds), 0) % 86_400
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return time(h, m, s)


def _time_to_t(value: time) -> float:
    """Naive ``time`` -> seconds since stream origin (float)."""
    return float(value.hour * 3600 + value.minute * 60 + value.second)


def _on_timeline_changed() -> None:
    v = st.session_state["timeline_slider"]
    if isinstance(v, time):
        v = _time_to_t(v)
    st.session_state["current_time"] = float(v)


def _render_master_timeline(slider_min: float, slider_max: float, t_current: float) -> None:
    """Bottom master timeline, displayed in HH:MM:SS (``time`` slider).

    ``time`` wraps at 24h, so spans that long fall back to a seconds slider.
    """
    label = "⏱️ 全场时间轴（主控：拖拽联动所有图表高亮当前值）"
    if slider_max < 86_400.0:
        st.slider(
            label,
            min_value=_t_to_time(slider_min),
            max_value=_t_to_time(slider_max),
            value=_t_to_time(min(max(t_current, slider_min), slider_max)),
            step=timedelta(seconds=1),
            format="HH:mm:ss",
            key="timeline_slider",
            on_change=_on_timeline_changed,
        )
    else:
        st.slider(
            label,
            min_value=slider_min,
            max_value=slider_max,
            value=min(max(t_current, slider_min), slider_max),
            step=1.0,
            key="timeline_slider",
            on_change=_on_timeline_changed,
        )
        st.caption("直播时长超过 24 小时，时间轴回退为秒显示。")


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
# Session cascade (平台 → 主播 → 直播场次) + time-interval controls
# --------------------------------------------------------------------------

def _reset_streamer_selects() -> None:
    """Changing the platform re-defaults the streamer and session pickers."""
    st.session_state.pop("sel_streamer", None)
    st.session_state.pop("sel_session", None)


def _reset_session_select() -> None:
    """Changing the streamer re-defaults the session picker."""
    st.session_state.pop("sel_session", None)


def _session_controls(root: str) -> tuple[DanmakuSession | None, tuple[int, int]]:
    """Cascade platform → streamer → session, plus an analysis time-interval.

    Returns ``(session, interval)`` where ``interval`` is the applied in-stream
    ``(start_s, end_s)`` — the whole stream by default, or a user-chosen
    sub-range. The range preview (record count) updates live while dragging;
    the full metric pipeline only re-runs when 「应用区间分析」 is clicked.
    """
    sessions, _ = _discover_sessions_cached(root)
    if not sessions:
        return None, (0, 0)

    platforms = sorted({s.platform for s in sessions})
    platform = st.sidebar.selectbox(
        "平台", platforms, key="sel_platform", on_change=_reset_streamer_selects
    )
    streamers = sorted({s.user_name for s in sessions if s.platform == platform})
    streamer = st.sidebar.selectbox(
        "主播", streamers, key="sel_streamer", on_change=_reset_session_select
    )
    chosen = [
        s for s in sessions if s.platform == platform and s.user_name == streamer
    ]
    labels = [f"{s.label}（{len(s.chunks)}分片）" for s in chosen]
    session = chosen[
        st.sidebar.selectbox(
            "直播场次",
            list(range(len(chosen))),
            format_func=lambda i: labels[i],
            key="sel_session",
            help="同一场直播的所有分片会在后台聚合为连续时间轴。"
            "分场按文件创建时间排序，相邻分片的上一文件修改时间与下一文件创建时间"
            "间隔 ≤1 小时且标题相同才视为同一场。",
        )
    ]

    records, _notes = load_session_records(session)
    if not records:
        return session, (0, 0)
    origin = records[0].ts_ms
    duration = max(int((records[-1].ts_ms - origin) / 1000), 1)

    # Reset the picked range when switching to a different session.
    if st.session_state.get("range_session_key") != session.key:
        st.session_state["range_session_key"] = session.key
        st.session_state["range_value"] = (0, duration)

    opts = list(range(0, duration, 60))
    if opts[-1] != duration:
        opts.append(duration)
    picked = st.sidebar.select_slider(
        "分析时间区间",
        options=opts,
        value=st.session_state.get("range_value", (0, duration)),
        format_func=charts.fmt_hms,
        key="range_value",
        help="整场直播较长时数据过密会稀释高潮信号：限定区间，只分析该时段。"
        "拖动即预览区间内弹幕量，点「应用区间分析」才重算指标。",
    )
    if not isinstance(picked, (tuple, list)):
        picked = (picked, picked)
    picked = (int(picked[0]), int(picked[1]))
    lo = origin + picked[0] * 1000
    hi = origin + picked[1] * 1000
    n_in = sum(1 for r in records if lo <= r.ts_ms <= hi)
    st.sidebar.caption(
        f"区间 {charts.fmt_hms(picked[0])} → {charts.fmt_hms(picked[1])}｜"
        f"约 {n_in:,} 条弹幕"
    )
    if st.sidebar.button("应用区间分析", key="apply_range"):
        st.session_state["applied_interval"] = tuple(picked)
        st.session_state["applied_interval_key"] = session.key

    if st.session_state.get("applied_interval_key") == session.key:
        interval = st.session_state["applied_interval"]
    else:
        interval = (0, duration)
    return session, interval


# --------------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------------

def _sidebar_controls() -> tuple[
    SourceConfig, int, MetricWeights, GradeThresholds, DetectionParams
]:
    st.sidebar.header("数据源")
    mode = st.sidebar.radio(
        "数据源",
        SOURCE_MODES,
        index=0,
        key="source_mode",
        help="整场直播模式：扫描分片根目录，把同一场直播的分片在后台聚合后再分析。",
    )
    uploaded = None
    xml_input = str(DEFAULT_XML)
    root = DEFAULT_SESSION_ROOT
    session: DanmakuSession | None = None
    interval = (0, 0)
    if mode == SESSION_MODE:
        root = st.sidebar.text_input(
            "分片根目录",
            value=DEFAULT_SESSION_ROOT,
            key="session_root",
            help="目录结构：平台 → 主播 → 分片 xml；按 metadata 的 live_start_time 聚合同一场直播。",
        )
        session, interval = _session_controls(root)
    else:
        uploaded = st.sidebar.file_uploader(
            "上传弹幕 XML 文件",
            type=["xml"],
            key="uploaded_xml",
            help="直接上传虎牙风格弹幕 XML；上传后优先使用上传的文件。",
        )
        xml_input = st.sidebar.text_input(
            "或填写服务器上的 XML 路径", value=str(DEFAULT_XML), key="xml_path"
        )

    st.sidebar.header("指标参数")
    window_seconds = st.sidebar.slider(
        "弹幕窗口 W（秒）",
        min_value=3,
        max_value=120,
        value=10,
        step=1,
        key="window_seconds",
        help="弹幕聚合窗口，默认 10s。影响弹幕密度、爆发速率、激活率、"
        "长度分布、集中度及高潮候选区间；用户重合度（指标6）使用独立窗口。",
    )

    st.sidebar.header("高潮检测参数")
    with st.sidebar.expander("候选检测（高级）", expanded=False):
        threshold_mode = st.selectbox(
            "阈值基线",
            ["sigma", "robust", "percentile"],
            index=0,
            key="thr_mode",
            help="sigma=μ+kσ（策略默认）；robust=中位数+k·MAD，抗离群尖峰抬"
            "高阈值；percentile=密度曲线分位数。",
        )
        candidate_sigma = st.slider(
            "候选阈值倍数 k", 1.0, 4.0, 2.0, 0.1, key="cand_sigma",
            help="候选阈值 = 基线 + k×σ/MAD（或分位数模式的 k 无关）。",
        )
        strong_sigma = st.slider(
            "强候选阈值倍数", 2.0, 6.0, 3.0, 0.1, key="strong_sigma",
        )
        min_duration = st.slider(
            "最短候选时长（秒）", 0, 300, 3, 1, key="min_duration",
            help="丢弃短于此的候选（过滤单秒噪声尖峰）。",
        )
        merge_gap = st.slider(
            "候选合并间隔（秒）", 5, 180, 30, 5, key="merge_gap",
            help="间隔短于此且用户重合度达标的相邻候选合并为一段。",
        )
        spam_max_ratio = st.slider(
            "刷屏重复占比阈值", 0.50, 1.00, 0.80, 0.05, key="spam_ratio",
            help="窗口内重复文本占比 ≥ 此值 且 Top-3 集中度达标 → 判定为刷屏秒，"
            "从候选排除。",
        )
        spam_conc = st.slider(
            "刷屏集中度阈值", 0.30, 1.00, 0.60, 0.05, key="spam_conc",
            help="Top-3 发言占比 ≥ 此值才视为少数人垄断刷屏；真正的队形仪式"
            "集中度低，不会被误杀。",
        )
    detection = DetectionParams(
        threshold_mode=threshold_mode,
        candidate_sigma=float(candidate_sigma),
        strong_sigma=float(strong_sigma),
        min_duration_seconds=float(min_duration),
        merge_gap_seconds=float(merge_gap),
        spam_max_ratio=float(spam_max_ratio),
        spam_concentration=float(spam_conc),
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
    return (
        SourceConfig(mode, uploaded, xml_input, root, session, interval),
        window_seconds,
        weights,
        thresholds,
        detection,
    )


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
    # Let the widget re-register from its own value= (and own type), instead
    # of writing a raw float that would clash with the HH:MM:SS time slider.
    st.session_state.pop("timeline_slider", None)
t_current = float(st.session_state.get("current_time", 0.0))

cfg, window_seconds, weights, thresholds, detection = _sidebar_controls()

if cfg.mode == SESSION_MODE:
    if cfg.session is None:
        st.error(f"在 {cfg.root} 下未发现任何弹幕分片 XML。")
        st.stop()
    session = cfg.session
    analysis, notes = load_analysis_interval(
        session, window_seconds, *cfg.interval, detection
    )
    interval_note = ""
    if cfg.interval[0] > 0 or cfg.interval[1] < max(int(analysis.duration), 1):
        interval_note = (
            f"｜区间 {charts.fmt_hms(cfg.interval[0])} → {charts.fmt_hms(cfg.interval[1])}"
        )
    source_label = f"整场直播：{session.label}（{len(session.chunks)} 分片聚合）{interval_note}"
    _sessions, unclassified = _discover_sessions_cached(cfg.root)
else:
    if cfg.uploaded is not None:
        try:
            analysis = load_analysis_upload(
                cfg.uploaded.name, cfg.uploaded.getvalue(), window_seconds, detection
            )
        except DanmakuParseError as exc:
            st.error(f"解析上传文件失败（{cfg.uploaded.name}）：{exc}")
            st.stop()
        source_label = f"已上传：{cfg.uploaded.name}"
    else:
        if not Path(cfg.xml_path).is_file():
            st.error(f"找不到弹幕文件：{cfg.xml_path}")
            st.info("请在上方上传弹幕 XML 文件，或在侧边栏「数据源」填入正确的路径。")
            st.stop()
        analysis = load_analysis(str(cfg.xml_path), window_seconds, detection)
        source_label = f"本地文件：{cfg.xml_path}"

if analysis.n_records == 0:
    st.warning("该数据源未解析出任何弹幕。")
    st.stop()

detection_note = (
    f"阈值基线 {analysis.threshold_mode}｜"
    f"已排除 {analysis.spam_excluded_seconds} 个刷屏秒级窗口"
)
st.caption(
    f"数据源：{source_label}｜弹幕窗口 W={analysis.window_seconds}s｜{detection_note}"
)
if cfg.mode == SESSION_MODE:
    for fn, reason in notes.recovered:
        st.warning(f"分片 {fn}：{reason}（已修复后纳入聚合）")
    for fn, err in notes.skipped:
        st.warning(f"分片 {fn} 无法解析，已跳过：{err}")
    if unclassified:
        st.caption(f"另有 {len(unclassified)} 个 XML 缺少平台/主播信息，未归入任何场次。")

# Master timeline spans the analysed interval, and the clock starts at it.
slider_min = analysis.t_min
slider_max = max(analysis.duration, slider_min + 1.0)
if t_current < slider_min or t_current > slider_max:
    t_current = slider_min
    st.session_state["current_time"] = slider_min

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
        charts.density_figure(
            analysis.density, t_current, window_seconds=analysis.window_seconds
        ),
        width="stretch",
    )
    st.caption(
        f"含义：每 {analysis.window_seconds}s 窗口内弹幕条数。"
        "值越高该时刻参与越活跃；虚线为 μ+2σ / μ+3σ 高潮线。"
    )
    st.plotly_chart(
        charts.activation_figure(analysis.activation, t_current),
        width="stretch",
    )
    st.caption("含义：此前沉默的用户此刻重新发言的比例。越高 = 潜水观众被激活（出圈信号）。")
    st.plotly_chart(
        charts.concentration_figure(analysis.concentration, t_current),
        width="stretch",
    )
    st.caption("含义：Top-3 用户弹幕占比。越低 = 发言越分散、群体共鸣（真热度）；越高 = 少数人刷屏。")
with col_b:
    st.plotly_chart(
        charts.burst_figure(analysis.burst, t_current), width="stretch"
    )
    st.caption("含义：密度上升的陡峭度（正爆发）。值越高 = 弹幕在短时间内急剧爆发（名场面/关键时刻）。")
    st.plotly_chart(
        charts.length_figure(analysis.length_dist, t_current), width="stretch"
    )
    st.caption("含义：短弹幕（≤5字）与长弹幕（>15字）占比。短弹幕激增 = 情绪刷屏；长弹幕高 = 深度讨论。")
    st.plotly_chart(
        charts.overlap_figure(analysis.overlap, t_current), width="stretch"
    )
    st.caption("含义：相邻窗口重复发言用户的 Jaccard 重合度。越低 = 人群更新快、有新事件；越高 = 同一批人刷屏。")

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
                f"{cand.grade or '未定级'} · {charts.fmt_hms(cand.t_start)}",
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
            "区间": f"{charts.fmt_hms(c.t_start)} → {charts.fmt_hms(c.t_end)}",
            "时长": f"{int(c.duration) // 60:02d}:{int(c.duration) % 60:02d}",
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
_render_master_timeline(slider_min, slider_max, t_current)
st.caption(
    "综合评分 = 各指标归一化热度的加权平均（维度权重 × 指标权重）。"
    "分级阈值：S/A/B/C 见侧边栏；评分低于 C 阈值的候选记为「未定级」。"
)
