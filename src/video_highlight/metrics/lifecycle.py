"""Metric 7: 用户生命周期聚类 (per the strategy doc).

For each highlight window [t_start, t_end], classify window speakers by their
global first/last speech times, using stream-scaled offsets:
  A = scaled_offset(300, duration)   persistent buffer (5 min)
  B = scaled_offset(120, duration)   converted front window (2 min)
  C = scaled_offset(600, duration)   converted rear window (10 min)
Categories are mutually exclusive by construction:
  instant     first ∈ window ∧ last ∈ window
  persistent  first < t_start - A ∧ last > t_end + A
  converted   first ∈ [t_start - B, t_end] ∧ last > t_end + C
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from video_highlight.metrics._offsets import scaled_offset


@dataclass(frozen=True)
class LifecycleWindow:
    t_start: float
    t_end: float
    instant: int
    persistent: int
    converted: int
    total_users: int
    offset_a: float
    offset_b: float
    offset_c: float


@dataclass(frozen=True)
class LifecycleResult:
    windows: list[LifecycleWindow]


def compute(df: pd.DataFrame, highlights: list) -> LifecycleResult:
    if df.empty:
        return LifecycleResult([])

    t = df["t"].astype(float).values
    uids = df["uid"].tolist()
    duration = float(t.max() - t.min())

    a = scaled_offset(300, duration)
    b = scaled_offset(120, duration)
    c = scaled_offset(600, duration)

    first: dict[str, float] = {}
    last: dict[str, float] = {}
    for uid, tt in zip(uids, t):
        if uid not in first or tt < first[uid]:
            first[uid] = tt
        if uid not in last or tt > last[uid]:
            last[uid] = tt

    out: list[LifecycleWindow] = []
    for h in highlights:
        ts, te = float(h.t_start), float(h.t_end)
        window_uids = {u for u, tt in zip(uids, t) if ts <= tt <= te}
        instant = persistent = converted = 0
        for u in window_uids:
            f, l = first[u], last[u]
            if ts <= f <= te and ts <= l <= te:
                instant += 1
            elif f < ts - a and l > te + a:
                persistent += 1
            elif ts - b <= f <= te and l > te + c:
                converted += 1
        out.append(
            LifecycleWindow(
                t_start=ts,
                t_end=te,
                instant=instant,
                persistent=persistent,
                converted=converted,
                total_users=len(window_uids),
                offset_a=a,
                offset_b=b,
                offset_c=c,
            )
        )
    return LifecycleResult(out)
