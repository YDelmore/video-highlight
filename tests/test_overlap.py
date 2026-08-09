"""Tests for metric 6 (用户重合度, Jaccard)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.overlap import OverlapResult, compute


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def test_returns_result_dataclass():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df)
    assert isinstance(res, OverlapResult)
    assert isinstance(res.overlap, pd.Series)


def test_jaccard_hand_computed():
    rows = [
        {"t": 0.0, "uid": "A", "text": "x", "length": 1},
        {"t": 1.0, "uid": "B", "text": "x", "length": 1},
        {"t": 32.0, "uid": "B", "text": "x", "length": 1},
        {"t": 33.0, "uid": "C", "text": "x", "length": 1},
        {"t": 70.0, "uid": "D", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=30)
    # grid 0..71
    # t=61: U(t)={B,C}, U(t-30)={B} -> 1/2
    assert res.overlap.loc[61.0] == pytest.approx(0.5)
    # t=62: U(t)={B,C}, U(t-30)=empty -> 0
    assert res.overlap.loc[62.0] == 0.0
    # t=30: window not yet full
    assert pd.isna(res.overlap.loc[30.0])


def test_both_windows_empty_is_nan():
    rows = [
        {"t": 0.0, "uid": "A", "text": "x", "length": 1},
        {"t": 100.0, "uid": "B", "text": "x", "length": 1},
        {"t": 101.0, "uid": "C", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=30)
    # t=61: both U(t) and U(t-30) empty -> NaN
    assert pd.isna(res.overlap.loc[61.0])


def test_empty_df():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    res = compute(empty)
    assert res.overlap.empty


def test_reverse_one_empty_is_zero():
    # current window empty, previous window non-empty -> 0
    rows = [
        {"t": 1.0, "uid": "A", "text": "x", "length": 1},
        {"t": 100.0, "uid": "B", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=30)
    # t=61: U(61)=[31,61) empty; U(31)=[1,31)={A} -> 0
    assert res.overlap.loc[61.0] == 0.0


def test_two_w_bounds():
    rows = [
        {"t": 0.0, "uid": "A", "text": "x", "length": 1},
        {"t": 1.0, "uid": "B", "text": "x", "length": 1},
        {"t": 32.0, "uid": "B", "text": "x", "length": 1},
        {"t": 33.0, "uid": "C", "text": "x", "length": 1},
        {"t": 70.0, "uid": "D", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=30)
    # t < 2*W are NaN; t=60 first valid: U(60)={B,C}, U(30)={A,B} -> 1/3
    assert pd.isna(res.overlap.loc[29.0])
    assert pd.isna(res.overlap.loc[59.0])
    assert res.overlap.loc[60.0] == pytest.approx(1 / 3)
