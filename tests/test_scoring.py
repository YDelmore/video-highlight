"""Tests for the composite scoring layer (weights, heat, grades)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.activation import ActivationResult
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.concentration import ConcentrationResult
from video_highlight.metrics.density import DensityResult
from video_highlight.metrics.length_dist import LengthDistResult
from video_highlight.metrics.lifecycle import LifecycleResult, LifecycleWindow
from video_highlight.metrics.overlap import OverlapResult
from video_highlight.metrics.returning import ReturningResult, ReturningWindow
from video_highlight.scoring import (
    GradeThresholds,
    MetricWeights,
    compute_heat,
    compute_overall,
    compute_signals,
    grade,
    normalize_max,
    score_all,
    score_candidates,
)
from tests.fixtures.synthetic_density import SAMPLE_DF


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

def test_effective_weights_sum_to_one() -> None:
    eff = MetricWeights().effective()
    assert sum(eff.values()) == pytest.approx(1.0)
    assert MetricWeights().effective()["activation"] == pytest.approx(0.6 * 0.35)
    assert MetricWeights().effective()["returning"] == pytest.approx(0.4 * 0.20)


def test_heat_weights_sum_to_one() -> None:
    assert sum(MetricWeights().heat_weights().values()) == pytest.approx(1.0)


def test_effective_respects_dimension_weight() -> None:
    w = MetricWeights(dim_heat=0.8, dim_behavior=0.2)
    eff = w.effective()
    # dimension-1 metrics carry 0.8 of the total
    dim1_total = sum(eff[m] for m in ("density", "burst", "activation", "length_dist"))
    assert dim1_total == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_max() -> None:
    s = pd.Series([0.0, 2.0, 4.0, np.nan])
    out = normalize_max(s)
    assert out.iloc[0:3].tolist() == [0.0, 0.5, 1.0]
    assert np.isnan(out.iloc[3])
    zeros = normalize_max(pd.Series([0.0, 0.0]))
    assert zeros.tolist() == [0.0, 0.0]
    empty = normalize_max(pd.Series([], dtype=float))
    assert empty.empty


# ---------------------------------------------------------------------------
# Heat curve
# ---------------------------------------------------------------------------

def test_compute_heat_weighted_valid_mean() -> None:
    w = MetricWeights()
    hw = w.heat_weights()
    sig = {
        "density": pd.Series([1.0, 0.5, np.nan], index=[0.0, 1.0, 2.0]),
        "burst": pd.Series([0.0, 1.0, 1.0], index=[0.0, 1.0, 2.0]),
        "activation": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "length_dist": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "concentration": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "overlap": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
    }
    heat = compute_heat(sig, w)

    # t=0: all six valid -> plain weighted mean.
    expected_0 = sum(hw[m] * sig[m].iloc[0] for m in sig)
    assert heat.iloc[0] == pytest.approx(expected_0)

    # t=2: density NaN -> renormalise over the other five.
    den = sum(hw[m] for m in sig if m != "density")
    expected_2 = sum(hw[m] * sig[m].iloc[2] for m in sig if m != "density") / den
    assert heat.iloc[2] == pytest.approx(expected_2)

    # values stay in [0, 1]
    assert float(heat.min()) >= 0.0 and float(heat.max()) <= 1.0


def test_compute_heat_all_nan_is_nan() -> None:
    w = MetricWeights()
    sig = {
        "density": pd.Series([np.nan], index=[0.0]),
        "burst": pd.Series([np.nan], index=[0.0]),
        "activation": pd.Series([np.nan], index=[0.0]),
        "length_dist": pd.Series([np.nan], index=[0.0]),
        "concentration": pd.Series([np.nan], index=[0.0]),
        "overlap": pd.Series([np.nan], index=[0.0]),
    }
    heat = compute_heat(sig, w)
    assert np.isnan(heat.iloc[0])


def test_compute_signals_shapes() -> None:
    den = _density(SAMPLE_DF)
    signals = compute_signals(
        density=den,
        burst=BurstResult(
            S=den.D,
            S_rel=den.D,
            mu_S=0.0,
            sigma_S=0.0,
        ),
        activation=ActivationResult(
            activation=pd.Series([], dtype=float),
            silent_uids=frozenset(),
            active_uids=frozenset(),
            observation_seconds=0.0,
            n_silent=0,
            n_active=0,
        ),
        length_dist=LengthDistResult(
            short_ratio=pd.Series([], dtype=float),
            long_ratio=pd.Series([], dtype=float),
            mid_ratio=pd.Series([], dtype=float),
        ),
        concentration=ConcentrationResult(pd.Series([], dtype=float)),
        overlap=OverlapResult(pd.Series([], dtype=float)),
    )
    assert set(signals) == set(MetricWeights.TIME_SERIES)
    # normalized signals are bounded by [0, 1] on valid points
    for s in signals.values():
        valid = s.dropna()
        if len(valid):
            assert valid.max() <= 1.0 and valid.min() >= 0.0


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def test_grade_boundaries() -> None:
    th = GradeThresholds(s=0.75, a=0.60, b=0.45, c=0.30)
    assert grade(0.80, th) == "S"
    assert grade(0.75, th) == "S"
    assert grade(0.70, th) == "A"
    assert grade(0.60, th) == "A"
    assert grade(0.50, th) == "B"
    assert grade(0.45, th) == "B"
    assert grade(0.35, th) == "C"
    assert grade(0.30, th) == "C"
    assert grade(0.29, th) == ""


def test_grade_custom_thresholds() -> None:
    assert grade(0.50, GradeThresholds(s=0.40)) == "S"


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------

def test_score_candidates_hand_calc() -> None:
    cand = HighlightCandidate(
        t_start=0.0, t_end=2.0, peak_t=1.0, peak_density=10.0, level="candidate"
    )
    sig = {
        "density": pd.Series([1.0, 1.0, 1.0], index=[0.0, 1.0, 2.0]),
        "burst": pd.Series([1.0, 1.0, 1.0], index=[0.0, 1.0, 2.0]),
        "activation": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "length_dist": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "concentration": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
        "overlap": pd.Series([0.5, 0.5, 0.5], index=[0.0, 1.0, 2.0]),
    }
    heat = pd.Series([0.6, 0.6, 0.6], index=[0.0, 1.0, 2.0])
    lifecycle = LifecycleResult(
        [
            LifecycleWindow(
                t_start=0.0, t_end=2.0, instant=0, persistent=0, converted=10,
                total_users=10, offset_a=1.0, offset_b=1.0, offset_c=1.0,
            )
        ]
    )
    returning = ReturningResult(
        [
            ReturningWindow(
                t_start=0.0, t_end=2.0, returning_count=5, total_users=10,
                ratio=0.5, gap_start=0.0, gap_end=0.0,
            )
        ]
    )
    scored = score_candidates([cand], heat, sig, lifecycle, returning, MetricWeights())
    s = scored[0]
    eff = MetricWeights().effective()
    expected = (
        eff["density"] * 1.0
        + eff["burst"] * 1.0
        + eff["activation"] * 0.5
        + eff["length_dist"] * 0.5
        + eff["concentration"] * 0.5
        + eff["overlap"] * 0.5
        + eff["lifecycle"] * 1.0  # converted 10/10
        + eff["returning"] * 0.5
    )
    assert s.score == pytest.approx(expected)
    assert s.converted_ratio == pytest.approx(1.0)
    assert s.returning_ratio == pytest.approx(0.5)
    assert s.heat_peak == pytest.approx(0.6)
    assert s.grade == grade(expected, GradeThresholds())


# ---------------------------------------------------------------------------
# Overall + full pipeline + edge cases
# ---------------------------------------------------------------------------

def test_compute_overall() -> None:
    heat = pd.Series([0.0, 0.5, 1.0], index=[0.0, 1.0, 2.0])
    score, g = compute_overall(heat, GradeThresholds())
    assert score == pytest.approx(0.5 * 0.5 + 0.5 * 1.0)  # 0.5*mean + 0.5*max
    assert g == grade(score, GradeThresholds())


def test_score_all_pipeline_on_sample() -> None:
    df = SAMPLE_DF
    den = _density(df)
    res = score_all(
        density=den,
        burst=BurstResult(S=den.D, S_rel=den.D, mu_S=0.0, sigma_S=0.0),
        activation=ActivationResult(
            activation=pd.Series([], dtype=float),
            silent_uids=frozenset(),
            active_uids=frozenset(),
            observation_seconds=0.0,
            n_silent=0,
            n_active=0,
        ),
        length_dist=LengthDistResult(
            short_ratio=pd.Series([], dtype=float),
            long_ratio=pd.Series([], dtype=float),
            mid_ratio=pd.Series([], dtype=float),
        ),
        concentration=ConcentrationResult(pd.Series([], dtype=float)),
        overlap=OverlapResult(pd.Series([], dtype=float)),
        highlights=[],
        lifecycle=LifecycleResult([]),
        returning=ReturningResult([]),
    )
    assert res.n_candidates == 0
    assert res.grade_counts == {"S": 0, "A": 0, "B": 0, "C": 0}
    assert 0.0 <= res.overall_score <= 1.0
    assert res.heat.empty is False


def test_score_all_respects_custom_thresholds() -> None:
    df = SAMPLE_DF
    den = _density(df)
    res = score_all(
        density=den,
        burst=BurstResult(S=den.D, S_rel=den.D, mu_S=0.0, sigma_S=0.0),
        activation=ActivationResult(
            activation=pd.Series([], dtype=float),
            silent_uids=frozenset(),
            active_uids=frozenset(),
            observation_seconds=0.0,
            n_silent=0,
            n_active=0,
        ),
        length_dist=LengthDistResult(
            short_ratio=pd.Series([], dtype=float),
            long_ratio=pd.Series([], dtype=float),
            mid_ratio=pd.Series([], dtype=float),
        ),
        concentration=ConcentrationResult(pd.Series([], dtype=float)),
        overlap=OverlapResult(pd.Series([], dtype=float)),
        highlights=[],
        lifecycle=LifecycleResult([]),
        returning=ReturningResult([]),
        thresholds=GradeThresholds(c=0.0),  # everything is at least C
    )
    assert res.overall_grade != ""  # overall score >= 0 is now C or better


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _density(df: pd.DataFrame) -> DensityResult:
    from video_highlight.metrics.density import compute as compute_density

    return compute_density(df)
