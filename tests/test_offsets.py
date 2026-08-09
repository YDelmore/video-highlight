"""Tests for the shared adaptive-offset helper."""

from __future__ import annotations

from video_highlight.metrics._offsets import scaled_offset


def test_scaled_offset_keeps_absolute_for_long_stream():
    # duration 3400s: 5min offset stays 300
    assert scaled_offset(300, 3400) == 300


def test_scaled_offset_caps_at_ratio_for_short_stream():
    # duration 100s: cap = 25
    assert scaled_offset(300, 100) == 25


def test_scaled_offset_never_exceeds_ratio():
    assert scaled_offset(1200, 100) == 25
    assert scaled_offset(600, 400) == 100


def test_scaled_offset_between():
    # duration 1796s: cap = 449
    assert scaled_offset(1200, 1796) == 449
    assert scaled_offset(120, 1796) == 120
