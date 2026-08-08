"""Tests for highlight candidate extraction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate, find_candidates
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
