"""Metric 1: 弹幕密度 (per the strategy doc).

D(t) = count of bullets whose timestamp lies in the trailing window [t-W, t),
       where W is the window size in seconds and t is evaluated on a 1-second
       grid. The strategy doc's formula writes [t, t+W); we use the trailing
       form ("过去10秒内的弹幕数") so D(t) at time t reflects known data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from video_highlight.metrics._window import rolling_sum


WINDOW_SECONDS: int = 10


@dataclass(frozen=True)
class DensityResult:
    """Output of metric 1.

    `D` is a Series indexed by relative seconds (float); values are bullet
    counts in the trailing W-second window. The first WINDOW_SECONDS seconds
    are NaN (history not yet complete).
    """

    D: pd.Series
    mu: float
    sigma: float
    n_total: int
    duration_seconds: float


def compute(
    df: pd.DataFrame,
    *,
    window_seconds: int = WINDOW_SECONDS,
) -> DensityResult:
    """Compute density D[t] from a danmaku DataFrame.

    Expects columns ``t``, ``uid``, ``text``, ``length`` (as produced by
    loader.to_dataframe). Only ``t`` is consumed here; the rest are kept so
    later metrics can reuse the same DataFrame.
    """
    if df.empty:
        empty_series = pd.Series([], dtype=float)
        return DensityResult(
            D=empty_series,
            mu=0.0,
            sigma=0.0,
            n_total=0,
            duration_seconds=0.0,
        )

    # One event per bullet, indexed by its relative second.
    events = pd.Series(
        np.ones(len(df), dtype=float),
        index=df["t"].astype(float).values,
    )
    D = rolling_sum(events, window_seconds=window_seconds)

    duration = float(df["t"].max() - df["t"].min())

    valid = D.dropna()
    mu = float(valid.mean()) if len(valid) else 0.0
    sigma = float(valid.std(ddof=0)) if len(valid) else 0.0

    return DensityResult(
        D=D,
        mu=mu,
        sigma=sigma,
        n_total=len(df),
        duration_seconds=duration,
    )
