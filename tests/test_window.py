"""Tests for the internal rolling-window helper.

Contract: the input Series' INDEX is the event times (float seconds), and
the VALUES are per-event counts (1 for a single event).
"""

from __future__ import annotations

import pandas as pd

from video_highlight.metrics._window import rolling_sum


def test_rolling_sum_returns_series_with_float_index():
    times = pd.Series([1.0, 1.0, 1.0, 1.0], index=[0.0, 1.0, 2.0, 3.0])
    result = rolling_sum(times, window_seconds=2)
    # Result is on a 1-second grid with float index (never DatetimeIndex).
    assert result.index.dtype.kind == "f"
    assert result.dtype.kind == "f"
    assert result.index[0] == 0.0


def test_rolling_sum_window_inclusion_right_open():
    """At t=3, trailing window [0,3) includes events at 0,1,2 -> sum=3."""
    times = pd.Series([1.0, 1.0, 1.0, 1.0], index=[0.0, 1.0, 2.0, 3.0])
    result = rolling_sum(times, window_seconds=3)
    assert result.loc[3.0] == 3
    # At t=4: window [1,4) -> events 1,2,3 -> 3
    assert result.loc[4.0] == 3


def test_rolling_sum_window_handles_irregular_times():
    """Bucket by whole second; t=15.0 and t=15.1 both land in second 15."""
    times = pd.Series(
        [1.0, 1.0, 1.0, 1.0, 1.0], index=[0.0, 5.5, 9.9, 15.0, 15.1]
    )
    result = rolling_sum(times, window_seconds=10)
    # At t=16: window [6,16) -> events 9.9, 15.0, 15.1 -> 3
    assert result.loc[16.0] == 3
    # At t=10: window [0,10) -> events 0.0, 5.5, 9.9 -> 3
    assert result.loc[10.0] == 3


def test_rolling_sum_nan_for_insufficient_history():
    """Before t reaches window_seconds, result is NaN, not 0."""
    times = pd.Series([1.0, 1.0], index=[0.0, 1.0])
    result = rolling_sum(times, window_seconds=10)
    assert pd.isna(result.loc[0.0])
    assert pd.isna(result.loc[1.0])
