"""Metric 2: 爆发速率 (per the strategy doc).

S(t) = D_smooth(t) - D_smooth(t-1), where D_smooth is a 3-point centered MA.
S_rel(t) = D(t) / max(D(t-1), 1) — relative burst rate, which catches
explosions from a low base (e.g. 5 -> 50 bullets is a 10x jump).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from video_highlight.metrics.density import DensityResult


@dataclass(frozen=True)
class BurstResult:
    S: pd.Series
    S_rel: pd.Series
    mu_S: float
    sigma_S: float


def compute(density: DensityResult) -> BurstResult:
    """Compute burst rate S and relative burst S_rel from a DensityResult."""
    D = density.D
    if D.empty:
        empty_series = pd.Series([], dtype=float)
        return BurstResult(
            S=empty_series,
            S_rel=empty_series,
            mu_S=0.0,
            sigma_S=0.0,
        )

    # 3-point centered moving average, then first difference.
    D_smooth = D.rolling(window=3, center=True, min_periods=1).mean()
    S = D_smooth.diff()

    # S_rel protects against division by zero (and leading NaN) by treating
    # max(D(t-1), 1) as at least 1.0.
    denom = D.shift(1).fillna(1.0).clip(lower=1.0)
    S_rel = D / denom

    valid = S.dropna()
    mu_S = float(valid.mean()) if len(valid) else 0.0
    sigma_S = float(valid.std(ddof=0)) if len(valid) else 0.0

    return BurstResult(S=S, S_rel=S_rel, mu_S=mu_S, sigma_S=sigma_S)
