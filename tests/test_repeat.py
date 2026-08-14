"""Tests for the repeated-text (刷屏) false-peak filter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from video_highlight.metrics.concentration import compute as compute_concentration
from video_highlight.metrics.repeat import (
    RepeatResult,
    compute,
    spam_exclude_mask,
)
from tests.fixtures.synthetic_density import make_df


def test_repeat_ratio_flags_spam_seconds():
    """10 copies of one text from 2 users → repeat_ratio 1.0 in their window;
    distinct messages later → 0."""
    rows = [
        {"t": float(5 + i), "uid": f"u{i % 2}", "text": "666", "length": 3}
        for i in range(10)
    ] + [
        {"t": float(20 + i), "uid": f"v{i}", "text": f"msg{i}", "length": 4}
        for i in range(10)
    ]
    rep = compute(make_df(rows), window_seconds=10, min_repeats=3)

    # empty windows (no bullets at all) -> NaN
    assert rep.repeat_ratio.loc[:4.0].isna().all()
    # windows fully inside the flood -> 1.0
    assert (rep.repeat_ratio.loc[10.0:20.0].dropna() == 1.0).all()
    # windows fully inside the distinct-chat stretch -> 0.0
    assert (rep.repeat_ratio.loc[25.0:29.0].dropna() == 0.0).all()


def test_repeat_ratio_min_repeats_boundary():
    k3 = make_df(
        [{"t": float(5 + i), "uid": f"u{i}", "text": "666", "length": 3} for i in range(3)]
    )
    rep3 = compute(k3, window_seconds=10, min_repeats=3)
    # t=8: window [0,8) holds exactly 3 copies -> all flagged
    assert rep3.repeat_ratio.loc[8.0] == 1.0

    k2 = make_df(
        [{"t": float(5 + i), "uid": f"u{i}", "text": "666", "length": 3} for i in range(2)]
    )
    rep2 = compute(k2, window_seconds=10, min_repeats=3)
    # t=7: window [0,7) holds 2 copies < 3 -> nothing flagged
    assert rep2.repeat_ratio.loc[7.0] == 0.0


def test_repeat_ratio_zero_for_unique_texts():
    df = make_df(
        [{"t": float(i), "uid": f"u{i}", "text": f"t{i}", "length": 2} for i in range(30)]
    )
    rep = compute(df, window_seconds=10, min_repeats=3)
    valid = rep.repeat_ratio.dropna()
    assert (valid == 0.0).all()


def test_repeat_ratio_ignores_whitespace():
    df = make_df(
        [
            {"t": 5.0, "uid": "u0", "text": " 666 ", "length": 3},
            {"t": 6.0, "uid": "u1", "text": "666", "length": 3},
            {"t": 7.0, "uid": "u2", "text": " 666", "length": 3},
        ]
    )
    rep = compute(df, window_seconds=10, min_repeats=3)
    assert rep.repeat_ratio.loc[8.0] == 1.0


def test_repeat_ratio_empty_df():
    rep = compute(pd.DataFrame({"t": [], "uid": [], "text": [], "length": []}))
    assert rep.repeat_ratio.empty


def test_spam_exclude_mask_needs_both_repeat_and_concentration():
    """Spam = repeated text *and* few users owning it. A crowd formation
    (repeated text, many users) must NOT be excluded."""
    spam_rows = [
        {"t": float(5 + i), "uid": f"u{i % 2}", "text": "666", "length": 3}
        for i in range(10)
    ]
    formation_rows = [
        {"t": float(100 + i), "uid": f"v{i}", "text": "全体起立", "length": 4}
        for i in range(10)
    ]
    df = make_df(spam_rows + formation_rows)
    rep = compute(df, window_seconds=10, min_repeats=3)
    conc = compute_concentration(df, window_seconds=10)

    mask = spam_exclude_mask(rep, conc)

    # spam stretch: repeat=1.0 and top-3 share=1.0 (only 2 uids) -> excluded
    assert mask.loc[10.0:15.0].all()
    # formation stretch: repeat=1.0 but 10 distinct uids in the full window
    # (top-3 share 0.3) -> not excluded
    assert not mask.loc[110.0]


def test_spam_exclude_mask_custom_thresholds():
    """5 repeated bullets from one user + 1 unique bullet -> repeat ≈ 0.83,
    concentration ≈ 0.83: spam at the defaults, not spam with a 95% repeat
    bar."""
    rows = [
        {"t": float(5 + i), "uid": "u0", "text": "刷屏", "length": 2}
        for i in range(5)
    ] + [{"t": 10.0, "uid": "u1", "text": "正常讨论", "length": 4}]
    df = make_df(rows)
    rep = compute(df, window_seconds=10, min_repeats=3)
    conc = compute_concentration(df, window_seconds=10)

    assert spam_exclude_mask(rep, conc).loc[11.0]
    assert not spam_exclude_mask(rep, conc, max_ratio=0.95).loc[11.0]
