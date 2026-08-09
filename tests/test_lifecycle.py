"""Tests for metric 7 (用户生命周期聚类)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.lifecycle import LifecycleResult, compute


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def _hl(t_start: float, t_end: float) -> HighlightCandidate:
    return HighlightCandidate(t_start, t_end, (t_start + t_end) / 2, 10.0, "candidate")


def test_returns_result_dataclass():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df, [])
    assert isinstance(res, LifecycleResult)


def test_categories_hand_computed():
    # duration 3400 -> offsets A=300, B=120, C=600. Window [1500,1600].
    rows = [
        {"t": 100.0, "uid": "U2", "text": "x", "length": 1},   # 持续
        {"t": 1500.0, "uid": "U2", "text": "x", "length": 1},
        {"t": 3500.0, "uid": "U2", "text": "x", "length": 1},
        {"t": 1520.0, "uid": "U3", "text": "x", "length": 1},  # 瞬时
        {"t": 1590.0, "uid": "U3", "text": "x", "length": 1},
        {"t": 1400.0, "uid": "U4", "text": "x", "length": 1},  # 转化
        {"t": 1520.0, "uid": "U4", "text": "x", "length": 1},
        {"t": 2500.0, "uid": "U4", "text": "x", "length": 1},
        {"t": 1400.0, "uid": "U5", "text": "x", "length": 1},  # 其他
        {"t": 1550.0, "uid": "U5", "text": "x", "length": 1},
        {"t": 1750.0, "uid": "U5", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), [_hl(1500, 1600)])
    assert len(res.windows) == 1
    w = res.windows[0]
    assert w.instant == 1       # U3
    assert w.persistent == 1    # U2
    assert w.converted == 1     # U4
    assert w.total_users == 4   # U2,U3,U4,U5 all speak in [1500,1600]
    assert w.offset_a == 300.0
    assert w.offset_b == 120.0
    assert w.offset_c == 600.0


def test_offsets_shrink_for_short_stream():
    rows = [
        {"t": 0.0, "uid": "a", "text": "x", "length": 1},
        {"t": 100.0, "uid": "a", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), [_hl(50, 60)])
    w = res.windows[0]
    # duration=100 -> cap=25 -> all offsets 25
    assert w.offset_a == 25.0
    assert w.offset_b == 25.0
    assert w.offset_c == 25.0


def test_no_highlights():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df, [])
    assert res.windows == []
