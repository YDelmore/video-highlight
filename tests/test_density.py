"""Tests for metric 1 (弹幕密度)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from video_highlight.metrics.density import WINDOW_SECONDS, DensityResult, compute
from tests.fixtures.synthetic_density import SAMPLE_DF


def test_density_returns_result_dataclass():
    result = compute(SAMPLE_DF)
    assert isinstance(result, DensityResult)
    assert result.n_total == 5
    assert result.duration_seconds == pytest.approx(20.0)


def test_density_window_size_constant():
    # W is documented in the spec and strategy doc.
    assert WINDOW_SECONDS == 10


def test_density_series_index_is_float_seconds():
    result = compute(SAMPLE_DF)
    # Index values are floats (seconds), not datetime
    assert result.D.index.dtype.kind == "f"


def test_density_values_on_synthetic():
    """5 bullets at t=0,1,1,1,20 with W=10s, trailing window [t-10, t):
       D(10) = events in [0,10) = {0,1,1,1} -> 4
       D(20) = events in [10,20) = {}      -> 0
       D(21) = events in [11,21) = {20}    -> 1
       D(5)  = NaN (window not yet full)
    """
    result = compute(SAMPLE_DF)
    assert result.D.loc[10.0] == 4
    assert result.D.loc[20.0] == 0
    assert result.D.loc[21.0] == 1
    assert pd.isna(result.D.loc[5.0])


def test_density_mu_sigma_computed():
    result = compute(SAMPLE_DF)
    # Drop NaN from first WINDOW_SECONDS seconds
    valid = result.D.dropna()
    assert math.isclose(result.mu, float(valid.mean()))
    assert math.isclose(result.sigma, float(valid.std(ddof=0)))


def test_density_with_empty_dataframe():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    result = compute(empty)
    assert result.n_total == 0
    assert result.D.empty
    assert result.mu == 0.0
    assert result.sigma == 0.0
