"""Tests for metric 4 (弹幕长度分布)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.length_dist import LengthDistResult, compute


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def test_returns_result_dataclass():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 5}])
    res = compute(df)
    assert isinstance(res, LengthDistResult)
    assert isinstance(res.short_ratio, pd.Series)


def test_buckets_and_ratios():
    # short: len<=5 (5,3); mid: 5<len<=15 (6,15); long: len>15 (16)
    rows = [
        {"t": 10.0, "uid": "a", "text": "x", "length": 5},
        {"t": 10.5, "uid": "b", "text": "x", "length": 6},
        {"t": 11.0, "uid": "c", "text": "x", "length": 15},
        {"t": 11.5, "uid": "d", "text": "x", "length": 16},
        {"t": 12.0, "uid": "e", "text": "x", "length": 3},
    ]
    res = compute(_df(rows), window_seconds=10)
    # At t=13: window [3,13) includes all 5 bullets
    assert res.short_ratio.loc[13.0] == pytest.approx(2 / 5)
    assert res.mid_ratio.loc[13.0] == pytest.approx(2 / 5)
    assert res.long_ratio.loc[13.0] == pytest.approx(1 / 5)


def test_ratios_sum_to_one_on_valid_points():
    rows = [
        {"t": 10.0, "uid": "a", "text": "x", "length": 5},
        {"t": 10.5, "uid": "b", "text": "x", "length": 6},
        {"t": 11.0, "uid": "c", "text": "x", "length": 15},
        {"t": 11.5, "uid": "d", "text": "x", "length": 16},
        {"t": 12.0, "uid": "e", "text": "x", "length": 3},
    ]
    res = compute(_df(rows), window_seconds=10)
    valid = res.short_ratio.dropna()
    assert not valid.empty
    for t in valid.index:
        total = (
            res.short_ratio.loc[t] + res.mid_ratio.loc[t] + res.long_ratio.loc[t]
        )
        assert total == pytest.approx(1.0)


def test_nan_when_empty_or_insufficient():
    df = _df([{"t": 20.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df, window_seconds=10)
    assert pd.isna(res.short_ratio.loc[5.0])    # t < window
    assert pd.isna(res.short_ratio.loc[10.0])   # empty window [0,10)
    assert res.short_ratio.loc[21.0] == 1.0     # window [11,21) has the bullet


def test_empty_df():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    res = compute(empty)
    assert res.short_ratio.empty
    assert res.long_ratio.empty


def test_empty_bucket_ratios_are_zero_not_nan():
    # No long bullets in the stream -> long_ratio must be 0, and ratios sum to 1.
    rows = [
        {"t": 10.0, "uid": "a", "text": "x", "length": 5},
        {"t": 11.0, "uid": "b", "text": "x", "length": 6},
        {"t": 12.0, "uid": "c", "text": "x", "length": 15},
    ]
    res = compute(_df(rows), window_seconds=10)
    # At t=13: window [3,13) has 3 bullets, all short/mid.
    assert res.short_ratio.loc[13.0] == pytest.approx(1 / 3)
    assert res.long_ratio.loc[13.0] == pytest.approx(0.0)
    total = (
        res.short_ratio.loc[13.0]
        + res.mid_ratio.loc[13.0]
        + res.long_ratio.loc[13.0]
    )
    assert total == pytest.approx(1.0)


def test_partial_bucket_tail_is_not_nan():
    # long bullet ends before stream end (t=12.0) -> tail ratio must be valid.
    rows = [
        {"t": 10.5, "uid": "a", "text": "x", "length": 16},
        {"t": 12.0, "uid": "b", "text": "x", "length": 5},
    ]
    res = compute(_df(rows), window_seconds=10)
    # At t=13: window [3,13) has both bullets -> long = 1/2, short = 1/2.
    assert res.long_ratio.loc[13.0] == pytest.approx(0.5)
    assert res.short_ratio.loc[13.0] == pytest.approx(0.5)
