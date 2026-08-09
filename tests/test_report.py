"""Tests for the reporter (console + matplotlib)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.activation import ActivationResult
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.density import DensityResult
from video_highlight.metrics.length_dist import LengthDistResult
from video_highlight.report import console_print, plot


def _density() -> DensityResult:
    D = pd.Series(
        [0.0, 1.0, 2.0, 3.0, 4.0],
        index=[0.0, 1.0, 2.0, 3.0, 4.0],
        dtype=float,
    )
    return DensityResult(
        D=D,
        mu=2.0,
        sigma=1.4142135623730951,
        n_total=4,
        duration_seconds=4.0,
    )


def _burst() -> BurstResult:
    S = pd.Series([1.0, 1.0, 1.0, 1.0], index=[1.0, 2.0, 3.0, 4.0], dtype=float)
    S_rel = pd.Series(
        [1.0, 1.5, 1.5, 1.5], index=[1.0, 2.0, 3.0, 4.0], dtype=float
    )
    return BurstResult(S=S, S_rel=S_rel, mu_S=1.0, sigma_S=0.0)


def _activation() -> ActivationResult:
    act = pd.Series([0.2, 0.5, 0.8], index=[2.0, 3.0, 4.0], dtype=float)
    return ActivationResult(
        activation=act,
        silent_uids=frozenset({"s1"}),
        active_uids=frozenset({"a1", "a2"}),
        observation_seconds=0.0,
        n_silent=1,
        n_active=2,
    )


def _length_dist() -> LengthDistResult:
    idx = [2.0, 3.0, 4.0]
    return LengthDistResult(
        short_ratio=pd.Series([0.5, 0.6, 0.7], index=idx, dtype=float),
        mid_ratio=pd.Series([0.3, 0.3, 0.3], index=idx, dtype=float),
        long_ratio=pd.Series([0.2, 0.1, 0.0], index=idx, dtype=float),
    )


def test_console_print_contains_metric_sections():
    buf = io.StringIO()
    console_print(
        density=_density(),
        burst=_burst(),
        highlights=[],
        activation=_activation(),
        length_dist=_length_dist(),
        danmaku_count=4,
        duration_seconds=4.0,
        stream=buf,
    )
    out = buf.getvalue()
    assert "=== 分析概览 ===" in out
    assert "=== 指标1: 弹幕密度" in out
    assert "=== 指标2: 爆发速率" in out
    assert "弹幕总数: 4" in out


def test_console_print_includes_metric_3_and_4_sections():
    buf = io.StringIO()
    console_print(
        density=_density(),
        burst=_burst(),
        highlights=[],
        activation=_activation(),
        length_dist=_length_dist(),
        danmaku_count=4,
        duration_seconds=4.0,
        stream=buf,
    )
    out = buf.getvalue()
    assert "=== 指标3: 沉默用户激活率" in out
    assert "=== 指标4: 弹幕长度分布" in out
    assert "沉默池: 1 人 / 活跃: 2 人" in out


def test_console_print_includes_highlight_table_and_candidate_means():
    cand = HighlightCandidate(
        t_start=2.0, t_end=3.0, peak_t=2.5, peak_density=3.0, level="candidate"
    )
    buf = io.StringIO()
    console_print(
        density=_density(),
        burst=_burst(),
        highlights=[cand],
        activation=_activation(),
        length_dist=_length_dist(),
        danmaku_count=4,
        duration_seconds=4.0,
        stream=buf,
    )
    out = buf.getvalue()
    assert "=== 高潮候选区间（合并后） ===" in out
    assert "candidate" in out
    # candidate window [2,3]: activation mean of (0.2, 0.5) = 0.35 -> 35.0%
    assert "35.0%" in out


def test_plot_returns_true_or_false(tmp_path: Path):
    out = tmp_path / "plot.png"
    ok = plot(
        _density(),
        _burst(),
        [],
        activation=_activation(),
        length_dist=_length_dist(),
        output_path=out,
    )
    assert isinstance(ok, bool)
