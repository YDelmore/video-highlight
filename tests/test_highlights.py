"""Tests for highlight candidate extraction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from video_highlight.highlights import (
    HighlightCandidate,
    find_candidates,
    resolve_thresholds,
)
from video_highlight.metrics.density import DensityResult


def _density_with(D_values: list[float]) -> DensityResult:
    """Build a DensityResult whose D values exactly equal D_values (1 Hz)."""
    index = np.arange(len(D_values), dtype=float)
    D = pd.Series(D_values, index=index, dtype=float)
    valid = D.dropna()
    return DensityResult(
        D=D,
        mu=float(valid.mean()),
        sigma=float(valid.std(ddof=0)) if len(valid) else 0.0,
        n_total=int(D.sum()),
        duration_seconds=float(index[-1] - index[0]),
    )


def test_find_candidates_empty_density():
    density = _density_with([0.0] * 5)
    result = find_candidates(density)
    assert result == []


def test_find_candidates_detects_single_high_run():
    """A spike of 4 in the middle, rest = 0, should produce 1 candidate."""
    # mean=0.4, sigma≈1.2 → candidate threshold ≈2.8 → only the spike
    # qualifies; strong threshold = 4.0, and 4 is not *strictly* above it.
    density = _density_with([0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    result = find_candidates(density)
    assert len(result) == 1
    cand = result[0]
    assert cand.peak_t == 2.0
    assert cand.peak_density == 4.0
    assert cand.level == "candidate"


def test_find_candidates_marks_strong_when_above_3sigma():
    """A clearly-strong spike gets level='strong'."""
    density = _density_with([0.0] * 50 + [10.0] + [0.0] * 50)
    result = find_candidates(density)
    assert len(result) == 1
    assert result[0].level == "strong"


def test_find_candidates_merges_close_runs():
    """Two runs separated by <30s are merged into one segment."""
    # Two 20-bullet spikes at seconds 40-44 and 55-59, gap = 11s < 30s.
    density = _density_with(
        [0.0] * 40 + [20.0] * 5 + [0.0] * 10 + [20.0] * 5 + [0.0] * 40
    )
    result = find_candidates(density, merge_gap_seconds=30.0)
    assert len(result) == 1
    merged = result[0]
    assert merged.t_start == 40.0
    assert merged.t_end == 59.0


def test_find_candidates_sorted_by_peak_t():
    density = _density_with(
        [0.0] * 30 + [10.0] * 3 + [0.0] * 30 + [10.0] * 3 + [0.0] * 30,
    )
    result = find_candidates(density)
    # Gap between runs is 63-32=31s > 30s -> two separate candidates.
    assert len(result) == 2
    peak_times = [c.peak_t for c in result]
    assert peak_times == sorted(peak_times)


# ---------------------------------------------------------------------------
# Robust / percentile thresholds (self-masking resistance)
# ---------------------------------------------------------------------------

def test_robust_mode_detects_plateau_missed_by_sigma():
    """One extreme outlier inflates σ so μ+2σ misses a real plateau; robust
    (median + k·MAD) still finds it."""
    baseline = [4.0, 5.0, 4.0, 6.0, 5.0, 4.0, 5.0, 6.0, 4.0, 5.0]
    D = baseline * 12 + [25.0] * 20 + [0.0] * 10 + [1000.0] + baseline * 10
    density = _density_with(D)

    sigma_res = find_candidates(density)  # default "sigma"
    # The outlier inflated σ -> only the 1000 spike survives.
    assert len(sigma_res) == 1
    assert sigma_res[0].peak_density == 1000.0
    assert sigma_res[0].t_start != 120.0  # the plateau was masked

    robust_res = find_candidates(density, threshold_mode="robust")
    assert len(robust_res) == 1
    # plateau [120, 139] is now detected (merged with the outlier at 150).
    assert robust_res[0].t_start == 120.0
    assert robust_res[0].t_end == 150.0


def test_percentile_mode_threshold():
    """A gentle ramp [1..20]: the 80th percentile cut picks the top of the
    ramp that μ+2σ would miss entirely."""
    D = [float(i) for i in range(1, 21)]
    density = _density_with(D)
    # sigma mode: μ=10.5, σ≈5.77 -> threshold 22 > max -> nothing.
    assert find_candidates(density) == []

    result = find_candidates(
        density, threshold_mode="percentile",
        candidate_percentile=80.0, strong_percentile=95.0,
    )
    assert len(result) == 1
    cand = result[0]
    assert cand.t_start == 16.0  # values 17..20 (index 16..19)
    assert cand.t_end == 19.0
    assert cand.level == "strong"  # 20 > 95th percentile (~19.05)


def test_resolve_thresholds_modes_and_overrides():
    density = _density_with([float(i) for i in range(1, 21)])
    c, s = resolve_thresholds(density)
    assert c == pytest.approx(10.5 + 2.0 * np.std(np.arange(1.0, 21.0)))
    assert s == pytest.approx(10.5 + 3.0 * np.std(np.arange(1.0, 21.0)))

    c2, s2 = resolve_thresholds(
        density, threshold_mode="percentile",
        candidate_percentile=80.0, strong_percentile=95.0,
    )
    assert c2 == pytest.approx(16.2)
    assert s2 == pytest.approx(19.05)

    # explicit thresholds win over the mode
    c3, s3 = resolve_thresholds(
        density, threshold_mode="sigma", candidate_threshold=5.0,
        strong_threshold=6.0,
    )
    assert (c3, s3) == (5.0, 6.0)

    with pytest.raises(ValueError):
        resolve_thresholds(density, threshold_mode="bogus")


# ---------------------------------------------------------------------------
# Exclude mask (spam / fake-peak filtering)
# ---------------------------------------------------------------------------

def test_exclude_mask_removes_seconds():
    D = [0.0] * 30 + [10.0] * 5 + [0.0] * 60 + [10.0] * 5 + [0.0] * 30
    density = _density_with(D)
    assert len(find_candidates(density)) == 2

    # runs are at [30,34] and [95,99]; spam-mask the second one
    exclude = pd.Series(True, index=[95.0, 96.0, 97.0, 98.0, 99.0])
    result = find_candidates(density, exclude=exclude)
    assert len(result) == 1
    assert result[0].t_start == 30.0  # second run was spam-masked


def test_exclude_mask_can_zero_out_all_candidates():
    D = [0.0] * 30 + [10.0] * 5 + [0.0] * 30
    density = _density_with(D)
    exclude = pd.Series(True, index=[30.0, 31.0, 32.0, 33.0, 34.0])
    assert find_candidates(density, exclude=exclude) == []


# ---------------------------------------------------------------------------
# Merge with user-overlap condition
# ---------------------------------------------------------------------------

def test_merge_requires_user_overlap():
    """Two runs 20s apart merge by time alone, but stay split when the
    user-overlap at the second run's start is below the threshold."""
    D = [0.0] * 40 + [10.0] * 5 + [0.0] * 20 + [10.0] * 5 + [0.0] * 40
    density = _density_with(D)

    # default: time-only merge -> one candidate
    assert len(find_candidates(density)) == 1

    low = pd.Series(0.1, index=[65.0])
    res_low = find_candidates(density, merge_overlap=low, merge_overlap_min=0.5)
    assert len(res_low) == 2
    assert [c.t_start for c in res_low] == [40.0, 65.0]

    high = pd.Series(0.8, index=[65.0])
    res_high = find_candidates(density, merge_overlap=high, merge_overlap_min=0.5)
    assert len(res_high) == 1
    assert res_high[0].t_start == 40.0

    # NaN / missing overlap counts as unknown -> time-only merge (back-compat)
    unknown = pd.Series([np.nan], index=[65.0])
    assert len(find_candidates(density, merge_overlap=unknown)) == 1


# ---------------------------------------------------------------------------
# Minimum duration & shape
# ---------------------------------------------------------------------------

def test_min_duration_filters_fragments():
    """A 1-second blip (duration 0) is dropped; a 5-second run survives."""
    D = [0.0] * 30 + [10.0] * 1 + [0.0] * 40 + [10.0] * 5 + [0.0] * 30
    density = _density_with(D)
    # blip at 30, run at 71-75 (gap 41s > 30s -> separate runs)
    result = find_candidates(density, min_duration_seconds=3.0)
    assert len(result) == 1
    assert result[0].t_start == 71.0
    assert result[0].t_end == 75.0


def test_highlight_candidate_shape():
    assert HighlightCandidate(0.0, 10.0, 5.0, 9.0, "candidate").shape == "spike"
    assert HighlightCandidate(0.0, 120.0, 60.0, 9.0, "candidate").shape == "short"
    assert HighlightCandidate(0.0, 400.0, 200.0, 9.0, "candidate").shape == "plateau"
    assert HighlightCandidate(0.0, 700.0, 350.0, 9.0, "candidate").shape == "long"


def test_explicit_thresholds_override_level():
    D = [0.0] * 30 + [5.0] * 5 + [0.0] * 30
    density = _density_with(D)
    res = find_candidates(density, candidate_threshold=4.0, strong_threshold=10.0)
    assert len(res) == 1
    assert res[0].level == "candidate"
    res2 = find_candidates(density, candidate_threshold=4.0, strong_threshold=4.5)
    assert res2[0].level == "strong"
