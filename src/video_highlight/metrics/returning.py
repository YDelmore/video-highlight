"""Metric 8: 回锅用户比例 (per the strategy doc).

A "returning" user in a highlight window [t_start, t_end]:
  spoke in [0, gap_start)            (was active before the silence gap)
  zero speeches in [gap_start, gap_end)  (proved absent)
  speaks again in the window             (proved recalled)
where gap_start = t_start - scaled_offset(1200, duration) and
      gap_end   = t_start - scaled_offset(120, duration).

We use "active before the gap" rather than the strategy's literal "first 30
minutes" so the definition stays well-defined on streams shorter than the
gap (where the two windows would overlap).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics._offsets import scaled_offset


@dataclass(frozen=True)
class ReturningWindow:
    t_start: float
    t_end: float
    returning_count: int
    total_users: int
    ratio: float
    gap_start: float
    gap_end: float


@dataclass(frozen=True)
class ReturningResult:
    windows: list[ReturningWindow]


def compute(df: pd.DataFrame, highlights: list[HighlightCandidate]) -> ReturningResult:
    if df.empty:
        return ReturningResult([])

    t = df["t"].astype(float).values
    uids = df["uid"].tolist()
    duration = float(t.max() - t.min())

    # user -> sorted speech times
    user_times: dict[str, list[float]] = {}
    for uid, tt in zip(uids, t):
        user_times.setdefault(uid, []).append(tt)
    for times in user_times.values():
        times.sort()

    out: list[ReturningWindow] = []
    for h in highlights:
        ts, te = float(h.t_start), float(h.t_end)
        gap_start = ts - scaled_offset(1200, duration)
        gap_end = ts - scaled_offset(120, duration)
        window_uids = {u for u, tt in zip(uids, t) if ts <= tt <= te}

        returning = 0
        for u in window_uids:
            times = user_times[u]
            before_gap = any(tt < gap_start for tt in times)
            if not before_gap:
                continue
            in_gap = any(gap_start <= tt < gap_end for tt in times)
            if in_gap:
                continue
            returning += 1

        total = len(window_uids)
        ratio = returning / total if total else 0.0
        out.append(
            ReturningWindow(
                t_start=ts,
                t_end=te,
                returning_count=returning,
                total_users=total,
                ratio=ratio,
                gap_start=gap_start,
                gap_end=gap_end,
            )
        )
    return ReturningResult(out)
