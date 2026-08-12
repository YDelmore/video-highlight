"""Tests for the Plotly figure builders (hover time formatting)."""

from __future__ import annotations

import re

import pytest

from video_highlight import charts
from video_highlight.metrics.density import compute as compute_density
from video_highlight.scoring import ScoredCandidate
from tests.fixtures.synthetic_density import SAMPLE_DF

HMS = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def _hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def test_metric_chart_hover_shows_hms_time() -> None:
    density = compute_density(SAMPLE_DF)
    fig = charts.density_figure(density, t_current=0.0)
    trace = fig.data[0]
    assert "<b>%{customdata[0]}</b>" in trace.hovertemplate
    labels = [row[0] for row in trace.customdata]
    assert len(labels) == len(trace.x)
    assert all(HMS.match(label) for label in labels)
    # every label agrees with its numeric x (seconds -> HH:MM:SS)
    for x, label in list(zip(trace.x, labels))[::100]:
        assert label == _hms(int(x))


def test_heat_chart_hover_and_clock_annotation_show_hms() -> None:
    density = compute_density(SAMPLE_DF)
    fig = charts.heat_figure(density.D, [], t_current=0.0)
    trace = fig.data[0]
    assert "%{customdata[0]}" in trace.hovertemplate
    assert all(HMS.match(row[0]) for row in trace.customdata)
    # master-clock annotation uses the same format
    texts = [a.text for a in fig.layout.annotations if getattr(a, "text", None)]
    assert any("当前 00:00:00" in t for t in texts)


def test_event_map_hover_shows_hms_bounds() -> None:
    cand = ScoredCandidate(
        t_start=687.0,
        t_end=734.0,
        peak_t=700.0,
        peak_density=10.0,
        base_level="candidate",
        score=0.633,
        grade="A",
        heat_mean=0.5,
        heat_peak=0.8,
        converted_ratio=0.3,
        returning_ratio=0.2,
    )
    fig = charts.event_map_figure([cand], duration=1800.0, t_current=0.0)
    trace = fig.data[0]
    custom = trace.customdata[0]
    assert custom[0] == 0  # click-to-jump index unchanged
    assert custom[5] == "00:11:27"  # 687 s
    assert custom[6] == "00:12:14"  # 734 s
    assert "%{customdata[5]}" in trace.hovertemplate
