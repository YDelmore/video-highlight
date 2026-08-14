"""Repeated-text (刷屏/机器人) detection for false-peak filtering.

``repeat_ratio(t)`` = fraction of bullets in the trailing window [t-W, t)
whose *normalised text* occurs at least ``min_repeats`` times inside that
window. A window where most bullets are copies of the same few messages is a
spam/刷屏 signature; the strategy doc's 指标1 note calls for filtering exactly
these fake peaks (抽奖/红包机器刷屏).

This alone would also flag genuine crowd formations (队形, e.g. "全体起立"),
which the strategy treats as *real* rituals (指标12). The distinction is user
breadth, so ``spam_exclude_mask`` combines repeat_ratio with 指标5 发言集中度
(Top-3 share): a second is spam-dominated only when the window is mostly
repeated text **and** a few users own most of it. Genuine formations spread
across many users (low concentration) and stay candidates.

Implementation: one incremental pass over the 1-second grid with a running
text counter — O(n_bullets + grid), unlike the naive per-window recount.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from video_highlight.metrics.concentration import ConcentrationResult


@dataclass(frozen=True)
class RepeatResult:
    """Output of metric: repeated-text ratio on the 1-second grid.

    Values are NaN only where the trailing window has no bullets at all; the
    index matches the density grid (float seconds).
    """

    repeat_ratio: pd.Series


def _norm(text: object) -> str:
    """Normalise a danmaku text for exact-repeat comparison."""
    return str(text).strip()


def compute(
    df: pd.DataFrame,
    *,
    window_seconds: int = 10,
    min_repeats: int = 3,
) -> RepeatResult:
    """Compute repeat_ratio(t) on a 1-second grid (trailing window [t-W, t)).

    Expects ``df`` with columns ``t`` and ``text`` (as produced by
    loader.to_dataframe). ``min_repeats`` is how many copies of one text in the
    window count as "repeated" (strategy 指标12's minimum chain length, 3).
    """
    if df.empty:
        return RepeatResult(pd.Series([], dtype=float))

    k = max(2, int(min_repeats))
    w = int(window_seconds)
    t = df["t"].astype(float).values
    texts = [_norm(txt) for txt in df["text"].tolist()]
    max_t = float(t.max())

    grid = np.arange(0.0, max_t + 1.5, 1.0)
    grid_int = np.floor(grid).astype(np.int64)
    secs = np.floor(t).astype(np.int64)

    # Per-second lists of normalised texts.
    sec_texts: dict[int, list[str]] = {}
    for s, txt in zip(secs, texts):
        sec_texts.setdefault(int(s), []).append(txt)

    # Sliding window with a running counter. Loop invariant: at the top of
    # iteration `gt` the counter holds the trailing window [gt-W, gt). For
    # each text with count c the window contributes f(c) = c if c >= k else
    # 0, maintained incrementally.
    cnt: dict[str, int] = {}
    flagged = 0  # Σ f(c) over texts in the window
    total = 0  # Σ c over texts in the window
    values = np.full(len(grid), np.nan)
    for i, gt in enumerate(grid_int):
        if total > 0:
            values[i] = flagged / total
        # Advance the window: drop second (gt-W), add second gt.
        leave = gt - w
        if leave >= 0:
            for txt in sec_texts.get(leave, ()):
                total -= 1
                c = cnt[txt]
                if c > k:
                    flagged -= 1
                elif c == k:
                    flagged -= k
                if c == 1:
                    del cnt[txt]
                else:
                    cnt[txt] = c - 1
        for txt in sec_texts.get(int(gt), ()):
            total += 1
            c = cnt.get(txt, 0)
            if c >= k:
                flagged += 1
            elif c == k - 1:
                flagged += k
            cnt[txt] = c + 1

    return RepeatResult(pd.Series(values, index=grid))


def spam_exclude_mask(
    repeat: RepeatResult,
    concentration: ConcentrationResult,
    *,
    max_ratio: float = 0.8,
    conc_threshold: float = 0.6,
) -> pd.Series:
    """Boolean mask of spam-dominated seconds (True = exclude from candidacy).

    A second is spam-dominated when its window is mostly repeated text
    (``repeat_ratio >= max_ratio``) **and** the window's Top-3 发言占比 is high
    (``concentration >= conc_threshold``) — i.e. a few users own the flood.
    The result is aligned to the repeat grid, NaN-filled to False.
    """
    r = repeat.repeat_ratio
    c = concentration.concentration
    idx = r.index.union(c.index)
    mask = (r.reindex(idx) >= max_ratio) & (c.reindex(idx) >= conc_threshold)
    return mask.where(mask.notna(), False).astype(bool)
