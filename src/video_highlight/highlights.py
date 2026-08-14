"""Highlight candidate segmentation from a density curve.

A "highlight candidate" is a contiguous run of seconds where the density
D(t) exceeds a threshold derived from the stream baseline. Threshold modes:

- ``"sigma"``      μ + k·σ — the strategy doc's baseline (μ/σ from
                   ``DensityResult``)
- ``"robust"``     median + k·1.4826·MAD — resists a single outlier inflating
                   σ and masking the real signal; falls back to ``"sigma"``
                   when MAD == 0 (e.g. a mostly-flat curve)
- ``"percentile"`` the ``candidate_percentile`` / ``strong_percentile``
                   quantile of the valid D values
- explicit        caller-provided ``candidate_threshold`` /
                   ``strong_threshold`` always win over the derived values

Runs separated by less than ``merge_gap_seconds`` are merged; when
``merge_overlap`` is provided, a merge additionally requires the user-overlap
(Jaccard) at the second run's start to be ≥ ``merge_overlap_min`` (missing /
NaN overlap counts as *unknown* → merge, so the default time-only behaviour is
unchanged). ``exclude`` marks seconds that can never be part of a candidate
(e.g. spam-dominated seconds filtered out upstream). Runs whose duration is
shorter than ``min_duration_seconds`` are dropped.

A run is "strong" when its peak exceeds the strong threshold. ``shape``
classifies duration per 指标16: spike (<60s) / short (<3min) / plateau
(<10min) / long (≥10min).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from video_highlight.metrics.density import DensityResult

# Duration morphology per 指标16 (time in seconds).
SHAPE_LABELS: dict[str, str] = {
    "spike": "尖峰型",
    "short": "短高潮",
    "plateau": "高原型",
    "long": "超长高潮",
}


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

    @property
    def shape(self) -> str:
        """Duration morphology per 指标16: spike/short/plateau/long."""
        d = self.duration
        if d < 60:
            return "spike"
        if d < 180:
            return "short"
        if d < 600:
            return "plateau"
        return "long"


@dataclass(frozen=True)
class DetectionParams:
    """Detection-layer knobs shared by the CLI and the Streamlit app.

    All fields default to the strategy doc's behaviour; the spam filter is the
    only knob that is on by default in the pipelines (not in the low-level
    ``find_candidates``).
    """

    threshold_mode: str = "sigma"  # "sigma" | "robust" | "percentile"
    candidate_sigma: float = 2.0  # μ/median + k·σ/MAD for candidates
    strong_sigma: float = 3.0  # μ/median + k·σ/MAD for strong candidates
    candidate_percentile: float = 97.5  # percentile-mode candidate cut
    strong_percentile: float = 99.0  # percentile-mode strong cut
    min_duration_seconds: float = 3.0  # drop runs shorter than this
    merge_gap_seconds: float = 30.0  # merge runs closer than this
    merge_overlap_min: float = 0.5  # merge also needs Jaccard ≥ this
    spam_max_ratio: float = 0.8  # window repeat-ratio cut for spam seconds
    spam_concentration: float = 0.6  # window Top-3 share cut for spam seconds
    spam_min_repeats: int = 3  # copies of one text to count as "repeated"

    def find_kwargs(self) -> dict[str, object]:
        """Keyword args for ``find_candidates`` (spam knobs excluded)."""
        return {
            "threshold_mode": self.threshold_mode,
            "candidate_sigma": self.candidate_sigma,
            "strong_sigma": self.strong_sigma,
            "candidate_percentile": self.candidate_percentile,
            "strong_percentile": self.strong_percentile,
            "min_duration_seconds": self.min_duration_seconds,
            "merge_gap_seconds": self.merge_gap_seconds,
            "merge_overlap_min": self.merge_overlap_min,
        }


def resolve_thresholds(
    density: DensityResult,
    *,
    threshold_mode: str = "sigma",
    candidate_threshold: float | None = None,
    strong_threshold: float | None = None,
    candidate_sigma: float = 2.0,
    strong_sigma: float = 3.0,
    candidate_percentile: float = 97.5,
    strong_percentile: float = 99.0,
) -> tuple[float | None, float | None]:
    """Derive the (candidate, strong) density thresholds for a curve.

    Returns ``(None, None)`` when no usable baseline exists (e.g. σ == 0).
    Explicit thresholds override the derived values per side.
    """
    if threshold_mode not in ("sigma", "robust", "percentile"):
        raise ValueError(f"unknown threshold_mode: {threshold_mode!r}")

    D = density.D.dropna()
    if D.empty:
        return None, None

    thr_c: float | None
    thr_s: float | None

    if threshold_mode == "percentile":
        thr_c = float(D.quantile(candidate_percentile / 100.0))
        thr_s = float(D.quantile(strong_percentile / 100.0))
    else:
        if threshold_mode == "robust":
            med = float(D.median())
            mad = float((D - med).abs().median()) * 1.4826
            if mad > 0:
                thr_c = med + candidate_sigma * mad
                thr_s = med + strong_sigma * mad
            else:
                # MAD zero (many ties) -> fall back to the sigma baseline.
                thr_c = thr_s = None
        else:
            thr_c = thr_s = None
        if thr_c is None and density.sigma > 0 and math.isfinite(density.sigma):
            thr_c = density.mu + candidate_sigma * density.sigma
            thr_s = density.mu + strong_sigma * density.sigma
        if thr_c is None:
            return None, None

    if candidate_threshold is not None:
        thr_c = float(candidate_threshold)
    if strong_threshold is not None:
        thr_s = float(strong_threshold)
    return thr_c, thr_s


def _overlap_allows_merge(
    merge_overlap: pd.Series | None,
    merge_overlap_min: float,
    t: float,
) -> bool:
    """True when the Jaccard series permits merging runs at time ``t``.

    Missing / NaN overlap is treated as unknown → merge (backwards-compatible
    with the time-only merge rule).
    """
    if merge_overlap is None:
        return True
    ov = merge_overlap.get(t)
    if ov is None:
        return True
    ov = float(ov)
    if math.isnan(ov):
        return True
    return ov >= merge_overlap_min


def find_candidates(
    density: DensityResult,
    *,
    strong_sigma: float = 3.0,
    merge_gap_seconds: float = 30.0,
    min_duration_seconds: float = 0.0,
    threshold_mode: str = "sigma",
    candidate_sigma: float = 2.0,
    candidate_threshold: float | None = None,
    strong_threshold: float | None = None,
    candidate_percentile: float = 97.5,
    strong_percentile: float = 99.0,
    exclude: pd.Series | None = None,
    merge_overlap: pd.Series | None = None,
    merge_overlap_min: float = 0.5,
) -> list[HighlightCandidate]:
    """Return a list of highlight candidates, sorted by peak_t.

    ``exclude`` is a boolean Series (same time index as ``density.D``) marking
    seconds that must not be part of any candidate (e.g. spam-dominated
    seconds). ``merge_overlap`` is the 指标6 Jaccard series used to require
    user continuity when merging close runs.
    """
    D = density.D.dropna()
    if D.empty:
        return []

    thr_c, thr_s = resolve_thresholds(
        density,
        threshold_mode=threshold_mode,
        candidate_threshold=candidate_threshold,
        strong_threshold=strong_threshold,
        candidate_sigma=candidate_sigma,
        strong_sigma=strong_sigma,
        candidate_percentile=candidate_percentile,
        strong_percentile=strong_percentile,
    )
    if thr_c is None:
        return []

    # Build mask of seconds strictly above the candidate threshold.
    mask = D.values > thr_c
    if exclude is not None:
        excluded = exclude.reindex(D.index)
        excluded = excluded.where(excluded.notna(), False).to_numpy(dtype=bool)
        mask &= ~excluded
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

    # Merge runs that are close together (and, when the overlap series is
    # given, whose user sets still bridge the gap).
    merged: list[tuple[int, int]] = []
    for r in runs:
        if merged and (
            D.index[r[0]] - D.index[merged[-1][1]] < merge_gap_seconds
        ) and _overlap_allows_merge(merge_overlap, merge_overlap_min, float(D.index[r[0]])):
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)

    # Drop runs shorter than the configured minimum duration.
    if min_duration_seconds > 0:
        merged = [
            (s, e)
            for s, e in merged
            if float(D.index[e] - D.index[s]) >= min_duration_seconds
        ]
        if not merged:
            return []

    out: list[HighlightCandidate] = []
    idx_values = D.index.values
    val_values = D.values
    for start_i, end_i in merged:
        seg = val_values[start_i : end_i + 1]
        peak_offset = int(np.argmax(seg))
        peak_i = start_i + peak_offset
        peak_d = float(seg[peak_offset])
        level = "strong" if peak_d > thr_s else "candidate"
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
