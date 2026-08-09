"""Shared adaptive time-offset helpers for metrics 7 & 8.

Scaled offsets keep the strategy's absolute values on long streams and shrink
them on short streams so the indicators stay observable. Same philosophy as
metric 3's observation period (min(300, duration*0.25)).
"""

from __future__ import annotations


def scaled_offset(offset_seconds: float, duration_seconds: float, ratio: float = 0.25) -> float:
    """Cap an absolute time offset at a fraction of the stream duration.

    Returns min(offset_seconds, duration_seconds * ratio).
    """
    return min(offset_seconds, duration_seconds * ratio)
