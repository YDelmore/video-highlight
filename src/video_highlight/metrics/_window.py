"""Internal rolling-window helpers used by metric modules.

Convention: input `series` is a 1-D pandas Series whose index is the
relative time (float seconds) and whose values are per-event counts
(usually 1 per event). Windows are computed in *time*, bucketed to whole
seconds, so non-uniformly sampled streams work correctly.

The result is defined on a regular 1-second grid so that ``D(t)`` means
"events in the trailing window [t - W, t)" at every integer second ``t``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_sum(series: pd.Series, window_seconds: int | float) -> pd.Series:
    """Return trailing-window sums over a 1-second grid.

    Buckets ``series`` by whole second (floor), then for each integer ``t``
    returns the number of events in the trailing window ``[t - W, t)``
    (right-open, matching the strategy doc's trailing-window wording).

    Returns a Series indexed by float seconds (the grid), dtype float.
    Values where the window is not yet full (``t < window_seconds``) are NaN.
    """
    if series.empty:
        return series.astype(float)

    w = int(window_seconds)
    max_t = float(series.index.max())

    # 1-second grid covering the full stream (plus one extra point so the
    # last event still has a complete window to its right).
    grid = np.arange(0.0, max_t + 1.5, 1.0)
    grid_int = np.floor(grid).astype(np.int64)

    # Bucket events into whole seconds and aggregate counts per second.
    secs = np.floor(np.asarray(series.index, dtype=float)).astype(np.int64)
    per_second = pd.Series(series.values).groupby(secs).sum()
    full = per_second.reindex(grid_int, fill_value=0.0)

    # The grid is uniform (1/s), so count-based rolling equals time-based
    # rolling. Rolling(window=w) at position t covers [t-w+1, t]; shifting
    # by one makes the window [t-w, t) — right-open, exactly D(t).
    win = full.rolling(w, min_periods=w).sum().shift(1)

    # Restore float-second index (public contract: never a DatetimeIndex).
    win.index = grid
    return win.astype(float)
