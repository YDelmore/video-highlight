"""Tests for metric 2 (爆发速率)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.burst import BurstResult, compute
from video_highlight.metrics.density import DensityResult, compute as compute_density
from tests.fixtures.synthetic_density import SAMPLE_DF


@pytest.fixture
def density():
    return compute_density(SAMPLE_DF)


def test_burst_returns_result_dataclass(density):
    result = compute(density)
    assert isinstance(result, BurstResult)
    assert isinstance(result.S, pd.Series)
    assert isinstance(result.S_rel, pd.Series)


def test_burst_smoothing_is_three_point_centered():
    """S = D_smooth(t) - D_smooth(t-1), where D_smooth is 3-point centered MA.

    With D = [0,0,4,0,0] and min_periods=1:
      D_smooth = [0, 4/3, 4/3, 4/3, 0]
      S        = [NaN, 4/3, 0, 0, -4/3]
    """
    D = pd.Series([0.0, 0.0, 4.0, 0.0, 0.0], index=[0.0, 1.0, 2.0, 3.0, 4.0])
    density = DensityResult(D=D, mu=0.8, sigma=1.6, n_total=4, duration_seconds=4.0)
    result = compute(density)
    assert result.S.loc[1.0] == pytest.approx(4.0 / 3.0)
    assert result.S.loc[2.0] == pytest.approx(0.0)
    assert result.S.loc[4.0] == pytest.approx(-4.0 / 3.0)


def test_burst_srel_protects_against_zero(density):
    """S_rel divides by max(D.shift(1), 1) — never divides by zero.

    At the first valid density point, the shifted value is NaN; treating it
    as 1 makes S_rel == D there.
    """
    result = compute(density)
    first_idx = density.D.first_valid_index()
    assert result.S_rel.loc[first_idx] == density.D.loc[first_idx]


def test_burst_mu_sigma_on_valid_only(density):
    result = compute(density)
    valid_s = result.S.dropna()
    assert result.mu_S == pytest.approx(float(valid_s.mean()))
    assert result.sigma_S == pytest.approx(float(valid_s.std(ddof=0)))


def test_burst_empty_density():
    density = DensityResult(
        D=pd.Series([], dtype=float),
        mu=0.0,
        sigma=0.0,
        n_total=0,
        duration_seconds=0.0,
    )
    result = compute(density)
    assert result.mu_S == 0.0
    assert result.sigma_S == 0.0
