"""Tests for metric 5 (发言集中度, Top-3)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.concentration import ConcentrationResult, compute


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def test_returns_result_dataclass():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df)
    assert isinstance(res, ConcentrationResult)
    assert isinstance(res.concentration, pd.Series)


def test_top3_share_hand_computed():
    # 12 bullets at t=15: A×5, B×2, C×2, D×1, E×1, F×1
    rows = [
        {"t": 15.0, "uid": u, "text": "x", "length": 1}
        for u in ["A"] * 5 + ["B"] * 2 + ["C"] * 2 + ["D"] + ["E"] + ["F"]
    ]
    res = compute(_df(rows), window_seconds=10)
    # grid 0..16; at t=16 window [6,16) -> sec 15; top3 = 5+2+2 = 9 / 12
    assert res.concentration.loc[16.0] == pytest.approx(9 / 12)


def test_fewer_than_three_users_is_1():
    rows = [
        {"t": 15.0, "uid": "A", "text": "x", "length": 1},
        {"t": 15.0, "uid": "B", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=10)
    assert res.concentration.loc[16.0] == 1.0


def test_empty_window_is_nan():
    rows = [
        {"t": 5.0, "uid": "A", "text": "x", "length": 1},
        {"t": 20.0, "uid": "B", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), window_seconds=10)
    assert res.concentration.loc[15.0] == 1.0   # window [5,15)
    assert pd.isna(res.concentration.loc[20.0])  # window [10,20) empty
    assert res.concentration.loc[21.0] == 1.0    # window [11,21)


def test_empty_df():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    res = compute(empty)
    assert res.concentration.empty
