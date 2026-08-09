"""Tests for the reporter (console + matplotlib)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.activation import ActivationResult
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.concentration import ConcentrationResult
from video_highlight.metrics.density import DensityResult
from video_highlight.metrics.length_dist import LengthDistResult
from video_highlight.metrics.lifecycle import LifecycleResult, LifecycleWindow
from video_highlight.metrics.overlap import OverlapResult
from video_highlight.metrics.returning import ReturningResult, ReturningWindow
from video_highlight.report import console_print, plot


def _density() -> DensityResult:
    D = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0], index=[0.0, 1.0, 2.0, 3.0, 4.0], dtype=float)
    return DensityResult(D=D, mu=2.0, sigma=1.4142135623730951, n_total=4, duration_seconds=4.0)


def _burst() -> BurstResult:
    S = pd.Series([1.0, 1.0, 1.0, 1.0], index=[1.0, 2.0, 3.0, 4.0], dtype=float)
    S_rel = pd.Series([1.0, 1.5, 1.5, 1.5], index=[1.0, 2.0, 3.0, 4.0], dtype=float)
    return BurstResult(S=S, S_rel=S_rel, mu_S=1.0, sigma_S=0.0)


def _activation() -> ActivationResult:
    act = pd.Series([0.2, 0.5, 0.8], index=[2.0, 3.0, 4.0], dtype=float)
    return ActivationResult(activation=act, silent_uids=frozenset({"s1"}),
                            active_uids=frozenset({"a1", "a2"}),
                            observation_seconds=0.0, n_silent=1, n_active=2)


def _length_dist() -> LengthDistResult:
    idx = [2.0, 3.0, 4.0]
    return LengthDistResult(short_ratio=pd.Series([0.5, 0.6, 0.7], index=idx, dtype=float),
                            mid_ratio=pd.Series([0.3, 0.3, 0.3], index=idx, dtype=float),
                            long_ratio=pd.Series([0.2, 0.1, 0.0], index=idx, dtype=float))


def _concentration() -> ConcentrationResult:
    return ConcentrationResult(pd.Series([0.5, 0.6, 0.9], index=[2.0, 3.0, 4.0], dtype=float))


def _overlap() -> OverlapResult:
    return OverlapResult(pd.Series([0.4, 0.3, 0.2], index=[2.0, 3.0, 4.0], dtype=float))


def _lifecycle() -> LifecycleResult:
    return LifecycleResult([LifecycleWindow(2.0, 3.0, 5, 2, 1, 10, 300.0, 120.0, 600.0)])


def _returning() -> ReturningResult:
    return ReturningResult([ReturningWindow(2.0, 3.0, 2, 10, 0.2, 1.0, 2.0)])


def _cand() -> HighlightCandidate:
    return HighlightCandidate(2.0, 3.0, 2.5, 3.0, "candidate")


def test_console_print_contains_all_metric_sections():
    buf = io.StringIO()
    console_print(
        density=_density(), burst=_burst(), highlights=[], activation=_activation(),
        length_dist=_length_dist(), concentration=_concentration(), overlap=_overlap(),
        lifecycle=_lifecycle(), returning=_returning(),
        danmaku_count=4, duration_seconds=4.0, stream=buf,
    )
    out = buf.getvalue()
    for marker in ["指标1", "指标2", "指标3", "指标4", "指标5", "指标6", "指标7", "指标8"]:
        assert marker in out


def test_console_print_metric_5_6_stats():
    buf = io.StringIO()
    console_print(
        density=_density(), burst=_burst(), highlights=[], activation=_activation(),
        length_dist=_length_dist(), concentration=_concentration(), overlap=_overlap(),
        lifecycle=_lifecycle(), returning=_returning(),
        danmaku_count=4, duration_seconds=4.0, stream=buf,
    )
    out = buf.getvalue()
    assert "发言集中度" in out
    assert "用户重合度" in out
    assert "重合度跌破30%的窗口数" in out


def test_console_print_metric_7_8_per_window():
    buf = io.StringIO()
    console_print(
        density=_density(), burst=_burst(), highlights=[_cand()], activation=_activation(),
        length_dist=_length_dist(), concentration=_concentration(), overlap=_overlap(),
        lifecycle=_lifecycle(), returning=_returning(),
        danmaku_count=4, duration_seconds=4.0, stream=buf,
    )
    out = buf.getvalue()
    assert "用户生命周期" in out
    assert "回锅用户比例" in out
    # lifecycle: instant 5 / persistent 2 / converted 1 over 10 users
    assert "瞬时 5" in out
    # returning: 2 / 10 -> 20.0%
    assert "20.0%" in out


def test_plot_creates_3x3_layout(tmp_path: Path, monkeypatch):
    captured: dict = {}
    import matplotlib.pyplot as plt

    real_subplots = plt.subplots

    def spy(*args, **kwargs):
        fig, axes = real_subplots(*args, **kwargs)
        captured["shape"] = axes.shape
        return fig, axes

    monkeypatch.setattr(plt, "subplots", spy)
    out = tmp_path / "plot.png"
    ok = plot(
        _density(), _burst(), [_cand()],
        activation=_activation(), length_dist=_length_dist(),
        concentration=_concentration(), overlap=_overlap(),
        lifecycle=_lifecycle(), returning=_returning(),
        output_path=out,
    )
    assert isinstance(ok, bool)
    assert captured["shape"] == (3, 3)
