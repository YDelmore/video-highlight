"""Metric 5: 发言集中度 (Top-3 占比, per the strategy doc).

concentration(t) = (bullets from the 3 most active users in window) / (all bullets in window)
Trailing right-open window [t-W, t) on a 1-second grid. NaN where window empty
or not yet full. With fewer than 3 users the top-3 is all of them -> ratio 1.0.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ConcentrationResult:
    concentration: pd.Series


def compute(df: pd.DataFrame, *, window_seconds: int = 10) -> ConcentrationResult:
    if df.empty:
        return ConcentrationResult(pd.Series([], dtype=float))

    t = df["t"].astype(float).values
    secs = np.floor(t).astype(np.int64)

    by_sec: dict[int, Counter] = {}
    for s, uid in zip(secs, df["uid"].tolist()):
        by_sec.setdefault(int(s), Counter())[uid] += 1

    grid = np.arange(0.0, float(t.max()) + 1.5, 1.0)
    w = int(window_seconds)
    values = np.full(len(grid), np.nan)
    empty = Counter()
    for i, gt in enumerate(grid):
        if gt < w:
            continue
        counter = Counter()
        for s in range(int(gt) - w, int(gt)):
            counter.update(by_sec.get(s, empty))
        total = sum(counter.values())
        if total == 0:
            continue
        top = sum(count for _, count in counter.most_common(3))
        values[i] = top / total

    return ConcentrationResult(pd.Series(values, index=grid))
