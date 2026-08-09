"""Tests for metric 3 (沉默用户激活率)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.activation import ActivationResult, compute
from tests.fixtures.synthetic_density import SAMPLE_DF


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])


def test_returns_result_dataclass():
    res = compute(SAMPLE_DF)
    assert isinstance(res, ActivationResult)
    assert res.n_silent == 1      # uid_b (one post-entry speech)
    assert res.n_active == 0
    assert res.silent_uids == frozenset({"uid_b"})


def test_observation_period_adaptive_25pct():
    df = _df([
        {"t": 0.0, "uid": "a", "text": "x", "length": 1},
        {"t": 100.0, "uid": "b", "text": "x", "length": 1},
    ])
    res = compute(df)
    # duration=100 -> O = min(300, 25) = 25
    assert res.observation_seconds == 25.0


def test_observation_period_caps_at_300():
    df = _df([
        {"t": 0.0, "uid": "a", "text": "x", "length": 1},
        {"t": 2000.0, "uid": "b", "text": "x", "length": 1},
    ])
    res = compute(df)
    assert res.observation_seconds == 300.0


def test_classification_excludes_entry_only_users():
    rows = [
        {"t": 0.0, "uid": "pre", "text": "a", "length": 1},   # only pre-entry
        {"t": 10.0, "uid": "sil", "text": "a", "length": 1},  # 1 post
        {"t": 11.0, "uid": "sil", "text": "b", "length": 1},  # 2 post -> silent
        {"t": 12.0, "uid": "act", "text": "c", "length": 1},
        {"t": 13.0, "uid": "act", "text": "d", "length": 1},
        {"t": 14.0, "uid": "act", "text": "e", "length": 1},  # 3 post -> active
    ]
    # duration=14 -> O = min(300, 3.5) = 3.5
    res = compute(_df(rows))
    assert "sil" in res.silent_uids
    assert "act" in res.active_uids
    assert "pre" not in res.silent_uids
    assert "pre" not in res.active_uids
    assert res.n_silent == 1
    assert res.n_active == 1


def test_activation_values_on_synthetic():
    res = compute(SAMPLE_DF)
    # duration=20 -> O = 5
    assert pd.isna(res.activation.loc[4.0])   # t < O
    assert res.activation.loc[5.0] == pytest.approx(1 / 3)
    assert res.activation.loc[10.0] == pytest.approx(1 / 3)
    assert pd.isna(res.activation.loc[20.0])  # empty window -> NaN
    assert res.activation.loc[21.0] == 1


def test_activation_empty_df():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    res = compute(empty)
    assert res.activation.empty
    assert res.n_silent == 0
    assert res.n_active == 0
