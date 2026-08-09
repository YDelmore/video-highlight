"""Metric 6: 用户重合度 (Jaccard, per the strategy doc).

overlap(t) = |U(t) ∩ U(t-30)| / |U(t) ∪ U(t-30)|
where U(x) is the set of uids speaking in the trailing window [x-30, x).
NaN when t < 2*W (either window not full) or both windows empty; 0 when
exactly one window is empty.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OverlapResult:
    overlap: pd.Series


def compute(df: pd.DataFrame, *, window_seconds: int = 30) -> OverlapResult:
    if df.empty:
        return OverlapResult(pd.Series([], dtype=float))

    t = df["t"].astype(float).values
    secs = np.floor(t).astype(np.int64)

    by_sec: dict[int, set] = {}
    for s, uid in zip(secs, df["uid"].tolist()):
        by_sec.setdefault(int(s), set()).add(uid)

    grid = np.arange(0.0, float(t.max()) + 1.5, 1.0)
    w = int(window_seconds)
    values = np.full(len(grid), np.nan)
    for i, gt in enumerate(grid):
        if gt < 2 * w:
            continue
        u_now: set = set()
        for s in range(int(gt) - w, int(gt)):
            u_now |= by_sec.get(s, set())
        u_prev: set = set()
        for s in range(int(gt) - 2 * w, int(gt) - w):
            u_prev |= by_sec.get(s, set())
        union = u_now | u_prev
        if not union:
            continue  # both empty -> NaN
        values[i] = len(u_now & u_prev) / len(union)

    return OverlapResult(pd.Series(values, index=grid))
