"""Metric 4: 弹幕长度分布 (per the strategy doc).

Bins bullets by character count:
  short = length <= 5
  long  = length > 15
  mid   = 5 < length <= 15
Ratios are computed on the trailing window [t-W, t) on the 1-second grid,
reusing the time-based rolling_sum helper.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from video_highlight.metrics._window import rolling_sum


@dataclass(frozen=True)
class LengthDistResult:
    short_ratio: pd.Series
    long_ratio: pd.Series
    mid_ratio: pd.Series


def compute(df: pd.DataFrame, *, window_seconds: int = 10) -> LengthDistResult:
    if df.empty:
        empty_series = pd.Series([], dtype=float)
        return LengthDistResult(empty_series, empty_series, empty_series)

    t = df["t"].astype(float).values
    length = df["length"].astype(int).values
    max_t = float(t.max())

    total_events = pd.Series(1.0, index=t)
    short_events = pd.Series(1.0, index=t[length <= 5])
    long_events = pd.Series(1.0, index=t[length > 15])

    # rolling_sum derives its 1-second grid from each series' own max time,
    # so a bucket whose last event precedes the stream end would produce a
    # shorter grid and misalign in the ratio division below. Pad each bucket
    # with a zero event at the stream end to force identical grid coverage.
    def _extend_to_total(events: pd.Series) -> pd.Series:
        if len(events) and float(events.index.max()) < max_t:
            events = pd.concat([events, pd.Series([0.0], index=[max_t])])
        return events

    short_events = _extend_to_total(short_events)
    long_events = _extend_to_total(long_events)

    total_window = rolling_sum(total_events, window_seconds=window_seconds)
    short_window = rolling_sum(short_events, window_seconds=window_seconds)
    long_window = rolling_sum(long_events, window_seconds=window_seconds)

    # NaN where window is empty or not yet full.
    total_safe = total_window.where(total_window > 0)
    short_ratio = short_window / total_safe
    long_ratio = long_window / total_safe
    mid_ratio = 1.0 - short_ratio - long_ratio

    return LengthDistResult(
        short_ratio=short_ratio,
        long_ratio=long_ratio,
        mid_ratio=mid_ratio,
    )
