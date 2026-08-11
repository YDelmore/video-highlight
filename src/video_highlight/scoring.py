"""Composite scoring: dimension weights → per-second heat → per-candidate grades.

The strategy doc (`docs/分析策略.md`) groups indicators into dimensions. The
platform needs two numbers on top of the raw metrics:

1. a per-second composite **heat curve** ``H(t)`` — "how hot is this moment"
   relative to the whole stream, used to highlight and link every chart;
2. a single **grade (S/A/B/C)** per climax interval, and one for the whole
   stream.

Both are built from one consistent weighting scheme:

    effective weight of metric m = (dimension weight) × (within-dimension weight)

Metrics 1-6 are per-second time series; metrics 7-8 are per-candidate
statistics. So:

- ``H(t)``  = weighted valid mean of the six *normalized* time-series signals.
  Each signal is mapped to [0,1] with the semantics in ``compute_signals``;
  per time point only the metrics that are valid contribute (their weights are
  renormalised over the valid set), so the early stream where some metrics are
  NaN is still scored from the rest.
- candidate score = weighted valid mean over **all 8** metrics, where metrics
  1-2 (density, burst) contribute their normalized-signal PEAK across the
  window (a climax is how intense it got), metrics 3-6 contribute their MEAN
  (sustained character of the moment), and metrics 7/8 contribute their
  per-window ratios (转化占比 / 回锅比例).
- ``grade`` buckets a score with the configured thresholds (S≥0.75, A≥0.60,
  B≥0.45, C≥0.30 by default); anything below C is "unrated".

Weights and thresholds are plain data — the Streamlit app makes them
editable. This module is pure pandas/numpy (no streamlit, no plotly) so the
scoring logic is unit-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
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


@dataclass(frozen=True)
class MetricWeights:
    """Dimension and per-indicator weights for the composite score.

    Dimension weights answer "how much does this dimension count"; the
    within-dimension weights divide each dimension's budget across its
    indicators (each dimension's four indicators sum to 1). Defaults follow
    the strategy doc's emphasis: metric 3 (沉默用户激活率) is called out as the
    key indicator of dimension 1, and metrics 5+7 (集中度 / 生命周期) as the
    powerful pair of dimension 2.
    """

    # Dimension weights
    dim_heat: float = 0.60      # 维度一 热度与规模
    dim_behavior: float = 0.40  # 维度二 用户行为与参与模式
    # Within-dimension weights (each dimension sums to 1)
    density: float = 0.30       # 指标1
    burst: float = 0.20         # 指标2
    activation: float = 0.35    # 指标3 (策略文档重点指标)
    length_dist: float = 0.15   # 指标4
    concentration: float = 0.30  # 指标5
    overlap: float = 0.20        # 指标6
    lifecycle: float = 0.30      # 指标7
    returning: float = 0.20      # 指标8

    # Indicator names by kind (order matters for display).
    TIME_SERIES: tuple[str, ...] = (
        "density",
        "burst",
        "activation",
        "length_dist",
        "concentration",
        "overlap",
    )
    PER_CANDIDATE: tuple[str, ...] = ("lifecycle", "returning")
    ALL: tuple[str, ...] = TIME_SERIES + PER_CANDIDATE

    def effective(self) -> dict[str, float]:
        """Map indicator name → (dimension weight × within-dimension weight).

        Sums to ``dim_heat + dim_behavior == 1`` across all 8 indicators.
        """
        dim = {
            "density": self.dim_heat,
            "burst": self.dim_heat,
            "activation": self.dim_heat,
            "length_dist": self.dim_heat,
            "concentration": self.dim_behavior,
            "overlap": self.dim_behavior,
            "lifecycle": self.dim_behavior,
            "returning": self.dim_behavior,
        }
        inner = {
            "density": self.density,
            "burst": self.burst,
            "activation": self.activation,
            "length_dist": self.length_dist,
            "concentration": self.concentration,
            "overlap": self.overlap,
            "lifecycle": self.lifecycle,
            "returning": self.returning,
        }
        return {m: dim[m] * inner[m] for m in self.ALL}

    def heat_weights(self) -> dict[str, float]:
        """Weights for the per-second heat curve (time-series indicators only).

        Renormalises the effective weights over the six time-series indicators
        so ``H(t)`` stays in [0,1] while keeping dimension influence.
        """
        eff = self.effective()
        ts = {m: eff[m] for m in self.TIME_SERIES}
        total = sum(ts.values())
        if total <= 0:
            return {m: 0.0 for m in self.TIME_SERIES}
        return {m: w / total for m, w in ts.items()}


@dataclass(frozen=True)
class GradeThresholds:
    """Score thresholds for the S/A/B/C grade ladder (defaults are the plan's)."""

    s: float = 0.75
    a: float = 0.60
    b: float = 0.45
    c: float = 0.30


# Grade → colour. Status palette (fixed, never themed); the grade letter always
# travels with the colour, so the colour never carries meaning alone.
GRADE_COLORS: dict[str, str] = {
    "S": "#d03b3b",  # critical 红
    "A": "#ec835a",  # serious  橙
    "B": "#fab219",  # warning  黄
    "C": "#0ca30c",  # good     绿
    "": "#898781",   # unrated  灰
}
GRADE_ORDER: tuple[str, ...] = ("S", "A", "B", "C")


@dataclass(frozen=True)
class ScoredCandidate:
    """A highlight interval plus its composite score and grade."""

    t_start: float
    t_end: float
    peak_t: float
    peak_density: float
    base_level: str  # "candidate" | "strong" from find_candidates
    score: float
    grade: str
    heat_mean: float
    heat_peak: float
    converted_ratio: float  # 指标7: 转化用户占比
    returning_ratio: float  # 指标8: 回锅用户比例

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


@dataclass(frozen=True)
class ScoringResult:
    """Everything the platform needs from the scoring layer."""

    heat: pd.Series
    signals: dict[str, pd.Series]  # normalized per-second signals (metrics 1-6)
    scored_candidates: list[ScoredCandidate]
    overall_score: float
    overall_grade: str
    grade_counts: dict[str, int]

    @property
    def n_candidates(self) -> int:
        return len(self.scored_candidates)


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

def normalize_max(series: pd.Series) -> pd.Series:
    """Scale non-NaN values to [0,1] by dividing by the series max.

    NaN positions stay NaN; an all-zero (or all-NaN) series stays zero.
    """
    valid = series.dropna()
    if len(valid) == 0:
        return series * 0.0
    peak = valid.max()
    if peak == 0:
        return series * 0.0
    return series / peak


def compute_signals(
    *,
    density: DensityResult,
    burst: BurstResult,
    activation: ActivationResult,
    length_dist: LengthDistResult,
    concentration: ConcentrationResult,
    overlap: OverlapResult,
) -> dict[str, pd.Series]:
    """Build the six normalized per-second heat signals (indicator → Series).

    Signal semantics (higher = "hotter / more eventful", all ∈ [0,1]):

    - density      D / D_max                      基础热度峰值归一到 1
    - burst        clip(S,0,∞) / max             只奖励正爆发(爬升陡峭度)
    - activation   原值(∈[0,1])                   出圈程度
    - length_dist  short_ratio(∈[0,1])            短弹幕激增=情绪宣泄
    - concentration 1 - Top3占比(∈[0,1])         低集中度=群体共鸣=真热度
    - overlap      1 - Jaccard(∈[0,1])            人群更新=事件发生
    """
    burst_pos = burst.S.clip(lower=0.0)
    return {
        "density": normalize_max(density.D),
        "burst": normalize_max(burst_pos),
        "activation": activation.activation,
        "length_dist": length_dist.short_ratio,
        "concentration": 1.0 - concentration.concentration,
        "overlap": 1.0 - overlap.overlap,
    }


def compute_heat(
    signals: dict[str, pd.Series],
    weights: MetricWeights,
) -> pd.Series:
    """Return the per-second composite heat curve H(t) ∈ [0,1].

    H(t) is a weighted valid mean of the normalized signals: at each time
    point only the metrics that are valid contribute, and their weights are
    renormalised over the valid set, so NaN regions (activation observation
    period, overlap's warm-up) don't zero the score out.
    """
    hw = weights.heat_weights()
    frame = pd.DataFrame({m: signals[m] for m in weights.TIME_SERIES if m in signals})
    if frame.empty:
        return pd.Series([], dtype=float)

    weight_of = {m: hw[m] for m in frame.columns}
    wsum = sum(weight_of.values())
    if wsum <= 0:
        return pd.Series([], dtype=float)

    weight_present = frame.notna().mul(weight_of)
    numerator = frame.fillna(0.0).mul(weight_of).sum(axis=1)
    denominator = weight_present.sum(axis=1)

    heat = numerator / denominator
    heat = heat.where(denominator > 0)
    heat.name = "heat"
    return heat


# --------------------------------------------------------------------------
# Candidate scoring & grading
# --------------------------------------------------------------------------

# Metrics 1-2 (density, burst) define the climax's intensity *ceiling* — a
# sustained plateau can carry a high mean-density but no single spike, so the
# window PEAK is the right summary. Metrics 3-6 characterize the sustained
# engagement during the window (character of the moment), so the MEAN is used.
_INTENSITY_METRICS: tuple[str, ...] = ("density", "burst")


def _window_mean(series: pd.Series, t_start: float, t_end: float) -> float | None:
    """Mean of non-NaN values within [t_start, t_end]; None if none."""
    sel = series[(series.index >= t_start) & (series.index <= t_end)].dropna()
    return float(sel.mean()) if len(sel) else None


def _window_peak(series: pd.Series, t_start: float, t_end: float) -> float | None:
    """Max of non-NaN values within [t_start, t_end]; None if none."""
    sel = series[(series.index >= t_start) & (series.index <= t_end)].dropna()
    return float(sel.max()) if len(sel) else None


def _valid(value: float | None) -> bool:
    return value is not None and not math.isnan(value)


def _weighted_valid_mean(
    values: dict[str, float],
    weights: dict[str, float],
) -> float:
    """Weighted mean over valid entries, weights renormalised over them."""
    num = 0.0
    den = 0.0
    for m, v in values.items():
        if not _valid(v):
            continue
        num += weights[m] * v
        den += weights[m]
    return float(num / den) if den > 0 else 0.0


def score_candidates(
    highlights: list[HighlightCandidate],
    heat: pd.Series,
    signals: dict[str, pd.Series],
    lifecycle: LifecycleResult,
    returning: ReturningResult,
    weights: MetricWeights,
    thresholds: GradeThresholds = GradeThresholds(),
) -> list[ScoredCandidate]:
    """Score and grade every highlight interval.

    Metrics 1-2 (density, burst) contribute their normalized-signal PEAK over
    the window (a climax is how intense it got); metrics 3-6 contribute their
    MEAN (sustained character of the moment); metric 7 contributes 转化用户占比
    and metric 8 回锅用户比例. The composite is a weighted valid mean over all
    8 metrics, then graded with the configured thresholds.
    """
    eff = weights.effective()
    lc_by_start = {w.t_start: w for w in lifecycle.windows}
    rt_by_start = {w.t_start: w for w in returning.windows}

    out: list[ScoredCandidate] = []
    for h in highlights:
        ts, te = float(h.t_start), float(h.t_end)

        values = {
            m: (_window_peak if m in _INTENSITY_METRICS else _window_mean)(
                signals[m], ts, te
            )
            for m in weights.TIME_SERIES
        }

        lc = lc_by_start.get(ts)
        rt = rt_by_start.get(ts)
        conv_ratio = lc.converted / lc.total_users if lc and lc.total_users else 0.0
        ret_ratio = rt.ratio if rt and _valid(rt.ratio) else 0.0
        values["lifecycle"] = conv_ratio
        values["returning"] = ret_ratio

        score = float(np.clip(_weighted_valid_mean(values, eff), 0.0, 1.0))

        heat_mean = _window_mean(heat, ts, te)
        heat_peak_sel = heat[(heat.index >= ts) & (heat.index <= te)].dropna()
        heat_peak = float(heat_peak_sel.max()) if len(heat_peak_sel) else 0.0

        out.append(
            ScoredCandidate(
                t_start=ts,
                t_end=te,
                peak_t=float(h.peak_t),
                peak_density=h.peak_density,
                base_level=h.level,
                score=score,
                grade=grade(score, thresholds),
                heat_mean=heat_mean if heat_mean is not None else 0.0,
                heat_peak=heat_peak,
                converted_ratio=conv_ratio,
                returning_ratio=ret_ratio,
            )
        )
    return out


def grade(score: float, thresholds: GradeThresholds) -> str:
    """Bucket a score into S/A/B/C (or "" when below the C threshold)."""
    if score >= thresholds.s:
        return "S"
    if score >= thresholds.a:
        return "A"
    if score >= thresholds.b:
        return "B"
    if score >= thresholds.c:
        return "C"
    return ""


def compute_overall(
    heat: pd.Series,
    thresholds: GradeThresholds,
) -> tuple[float, str]:
    """Whole-stream composite score and grade.

    ``overall = 0.5 * mean(H) + 0.5 * max(H)`` — overall engagement plus how
    hot the peak got. Same grade ladder as the candidates.
    """
    valid = heat.dropna()
    mean_h = float(valid.mean()) if len(valid) else 0.0
    peak_h = float(valid.max()) if len(valid) else 0.0
    overall = 0.5 * mean_h + 0.5 * peak_h
    return overall, grade(overall, thresholds)


def score_all(
    *,
    density: DensityResult,
    burst: BurstResult,
    activation: ActivationResult,
    length_dist: LengthDistResult,
    concentration: ConcentrationResult,
    overlap: OverlapResult,
    highlights: list[HighlightCandidate],
    lifecycle: LifecycleResult,
    returning: ReturningResult,
    weights: MetricWeights = MetricWeights(),
    thresholds: GradeThresholds = GradeThresholds(),
) -> ScoringResult:
    """Convenience: normalize → heat → candidate scores → overall score."""
    signals = compute_signals(
        density=density,
        burst=burst,
        activation=activation,
        length_dist=length_dist,
        concentration=concentration,
        overlap=overlap,
    )
    heat = compute_heat(signals, weights)
    scored = score_candidates(
        highlights, heat, signals, lifecycle, returning, weights, thresholds
    )
    overall, overall_grade = compute_overall(heat, thresholds)
    counts = {g: sum(1 for c in scored if c.grade == g) for g in GRADE_ORDER}
    return ScoringResult(
        heat=heat,
        signals=signals,
        scored_candidates=scored,
        overall_score=overall,
        overall_grade=overall_grade,
        grade_counts=counts,
    )
