"""Tests for metric 8 (回锅用户比例)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.returning import ReturningResult, compute


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def _hl(t_start: float, t_end: float) -> HighlightCandidate:
    return HighlightCandidate(t_start, t_end, (t_start + t_end) / 2, 10.0, "candidate")


def test_returns_result_dataclass():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df, [])
    assert isinstance(res, ReturningResult)


def test_returning_hand_computed():
    # duration 1420 -> gap_start = 1500 - min(1200, 355) = 1145,
    #                gap_end   = 1500 - min(120, 355)  = 1380
    rows = [
        {"t": 100.0, "uid": "U1", "text": "x", "length": 1},  # 回锅
        {"t": 1520.0, "uid": "U1", "text": "x", "length": 1},
        {"t": 100.0, "uid": "U2", "text": "x", "length": 1},  # 间隙内发言 -> 否
        {"t": 1200.0, "uid": "U2", "text": "x", "length": 1},
        {"t": 1520.0, "uid": "U2", "text": "x", "length": 1},
        {"t": 1520.0, "uid": "U3", "text": "x", "length": 1},  # 间隙前无发言 -> 否
        {"t": 1300.0, "uid": "U4", "text": "x", "length": 1},  # 间隙前无发言 -> 否
        {"t": 1520.0, "uid": "U4", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), [_hl(1500, 1600)])
    w = res.windows[0]
    assert w.returning_count == 1
    assert w.total_users == 4
    assert w.ratio == pytest.approx(0.25)
    assert w.gap_start == pytest.approx(1145.0)
    assert w.gap_end == pytest.approx(1380.0)


def test_gap_before_stream_start_yields_zero():
    # gap_start < 0: no one can have spoken before the gap -> returning 0
    rows = [
        {"t": 50.0, "uid": "U1", "text": "x", "length": 1},
        {"t": 10.0, "uid": "U2", "text": "x", "length": 1},  # speaks in window
    ]
    res = compute(_df(rows), [_hl(0, 20)])
    w = res.windows[0]
    assert w.gap_start < 0
    assert w.returning_count == 0
    assert w.ratio == 0.0
    assert w.total_users == 1


def test_empty_window_ratio_is_nan():
    rows = [
        {"t": 100.0, "uid": "A", "text": "x", "length": 1},
        {"t": 200.0, "uid": "B", "text": "x", "length": 1},
    ]
    res = compute(_df(rows), [_hl(0, 20)])
    w = res.windows[0]
    assert w.total_users == 0
    assert pd.isna(w.ratio)


def test_no_highlights():
    df = _df([{"t": 0.0, "uid": "a", "text": "x", "length": 1}])
    res = compute(df, [])
    assert res.windows == []
