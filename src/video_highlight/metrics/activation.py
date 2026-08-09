"""Metric 3: 沉默用户激活率 (per the strategy doc).

Adaptive observation period: O = min(max_observation_seconds, duration * observation_ratio).
Users are classified by their post-observation speech count:
  count == 0 -> not in the pool (only spoke during the entry period)
  count <= k  -> silent
  count > k   -> active
Activation rate at grid second t (trailing window [t-W, t)):
  t < O          -> NaN (skip the entry period)
  window empty   -> NaN
  otherwise      -> |window_uids ∩ silent| / |window_uids|

Complexity note: this uses O(grid × window) set unions, fine for clip-sized
streams; a per-uid 0/1 grid + rolling sum is the vectorized alternative for
very long streams (out of scope).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ActivationResult:
    activation: pd.Series
    silent_uids: frozenset[str]
    active_uids: frozenset[str]
    observation_seconds: float
    n_silent: int
    n_active: int


def compute(
    df: pd.DataFrame,
    *,
    window_seconds: int = 10,
    k: int = 2,
    max_observation_seconds: float = 300.0,
    observation_ratio: float = 0.25,
) -> ActivationResult:
    if df.empty:
        empty_series = pd.Series([], dtype=float)
        return ActivationResult(
            activation=empty_series,
            silent_uids=frozenset(),
            active_uids=frozenset(),
            observation_seconds=0.0,
            n_silent=0,
            n_active=0,
        )

    t = df["t"].astype(float).values
    duration = float(t.max() - t.min())
    obs = min(max_observation_seconds, duration * observation_ratio)

    post_mask = t >= obs
    post_counts = df.loc[post_mask].groupby("uid").size() if post_mask.any() \
        else pd.Series(dtype="int64")
    silent = frozenset(post_counts[post_counts <= k].index)
    active = frozenset(post_counts[post_counts > k].index)

    grid = np.arange(0.0, float(t.max()) + 1.5, 1.0)
    grid_int = np.floor(grid).astype(np.int64)

    # Per-second sets of uids who spoke in that whole second.
    secs = np.floor(t).astype(np.int64)
    by_sec: dict[int, set[str]] = {}
    for s, uid in zip(secs, df["uid"].tolist()):
        by_sec.setdefault(int(s), set()).add(uid)

    w = int(window_seconds)
    values = np.full(len(grid), np.nan)
    for i, gt in enumerate(grid_int):
        gt_f = float(gt)
        if gt_f < obs:
            continue  # skip the entry period
        window_uids: set[str] = set()
        for s in range(int(gt_f) - w, int(gt_f)):
            window_uids |= by_sec.get(s, set())
        total = len(window_uids)
        if total == 0:
            continue  # NaN
        silent_count = len(window_uids & silent)
        values[i] = silent_count / total

    activation = pd.Series(values, index=grid)
    return ActivationResult(
        activation=activation,
        silent_uids=silent,
        active_uids=active,
        observation_seconds=obs,
        n_silent=len(silent),
        n_active=len(active),
    )
