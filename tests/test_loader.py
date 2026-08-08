"""Tests for the loader (list[Danmaku] -> DataFrame)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.loader import to_dataframe
from video_highlight.parser import Danmaku


def _dm(ts_ms: int, uid: str, text: str) -> Danmaku:
    return Danmaku(uid=uid, ts_ms=ts_ms, text=text)


def test_to_dataframe_basic_columns():
    """Returns a DataFrame with required columns."""
    records = [
        _dm(1000, "u1", "hello"),
        _dm(2000, "u2", "world"),
    ]
    df = to_dataframe(records, live_start_ms=0)
    assert set(df.columns) >= {"t", "uid", "text", "length"}
    assert len(df) == 2
    assert df["uid"].iloc[0] == "u1"
    assert df["text"].iloc[1] == "world"


def test_to_dataframe_relative_time():
    """t column is (ts_ms - live_start_ms) / 1000."""
    records = [
        _dm(1500, "u1", "x"),
        _dm(2500, "u2", "y"),
    ]
    df = to_dataframe(records, live_start_ms=1000)
    assert df["t"].iloc[0] == 0.5
    assert df["t"].iloc[1] == 1.5


def test_to_dataframe_length_is_char_count():
    """length is character count (not bytes)."""
    records = [_dm(0, "u", "你好世界"), _dm(1000, "u", "abc")]
    df = to_dataframe(records, live_start_ms=0)
    assert df["length"].iloc[0] == 4
    assert df["length"].iloc[1] == 3


def test_to_dataframe_no_live_start_uses_min():
    """When live_start_ms is None, the smallest ts_ms becomes time 0."""
    records = [
        _dm(5000, "u1", "a"),
        _dm(7000, "u2", "b"),
        _dm(6000, "u3", "c"),
    ]
    df = to_dataframe(records)
    assert df["t"].min() == 0.0
    assert df["t"].max() == 2.0


def test_to_dataframe_empty_list():
    df = to_dataframe([], live_start_ms=0)
    assert len(df) == 0
    assert set(df.columns) == {"t", "uid", "text", "length"}


def test_to_dataframe_does_not_mutate_input():
    """Function must not mutate the input list."""
    records = [_dm(1000, "u1", "x")]
    snapshot = list(records)
    to_dataframe(records, live_start_ms=0)
    assert records == snapshot
