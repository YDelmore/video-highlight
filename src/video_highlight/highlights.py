"""Highlight candidate segmentation from a density curve.

A "highlight candidate" is a contiguous run of seconds where the density
D(t) exceeds μ + 2σ. Runs separated by less than `merge_gap_seconds` are
merged. A run is marked "strong" if its peak exceeds μ + 3σ.

Both thresholds use strict `>` per the strategy doc (候选 D>μ+2σ,
强候选 D>μ+3σ).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from video_highlight.metrics.density import DensityResult


@dataclass(frozen=True)
class HighlightCandidate:
    t_start: float
    t_end: float
    peak_t: float
    peak_density: float
    level: str  # "candidate" | "strong"

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


def find_candidates(
    density: DensityResult,
    *,
    strong_sigma: float = 3.0,
    merge_gap_seconds: float = 30.0,
) -> list[HighlightCandidate]:
    """Return a list of highlight candidates, sorted by peak_t."""
    D = density.D.dropna()
    if D.empty:
        return []

    mu, sigma = density.mu, density.sigma
    if sigma == 0:
        return []

    thr_candidate = mu + 2.0 * sigma
    thr_strong = mu + strong_sigma * sigma

    # Build mask of seconds strictly above the candidate threshold.
    mask = D.values > thr_candidate
    if not mask.any():
        return []

    # Find contiguous runs in `mask`.
    runs: list[tuple[int, int]] = []
    in_run = False
    start_idx = 0
    for i, on in enumerate(mask):
        if on and not in_run:
            in_run = True
            start_idx = i
        elif not on and in_run:
            in_run = False
            runs.append((start_idx, i - 1))
    if in_run:
        runs.append((start_idx, len(mask) - 1))

    # Merge runs that are close together.
    merged: list[tuple[int, int]] = []
    for r in runs:
        if merged and (D.index[r[0]] - D.index[merged[-1][1]]) < merge_gap_seconds:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)

    out: list[HighlightCandidate] = []
    idx_values = D.index.values
    val_values = D.values
    for start_i, end_i in merged:
        seg = val_values[start_i : end_i + 1]
        peak_offset = int(np.argmax(seg))
        peak_i = start_i + peak_offset
        peak_d = float(seg[peak_offset])
        level = "strong" if peak_d > thr_strong else "candidate"
        out.append(
            HighlightCandidate(
                t_start=float(idx_values[start_i]),
                t_end=float(idx_values[end_i]),
                peak_t=float(idx_values[peak_i]),
                peak_density=peak_d,
                level=level,
            )
        )

    out.sort(key=lambda c: c.peak_t)
    return out
