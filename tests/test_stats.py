"""Tests for the two-proportion z-test."""

import pytest

from funnelscope.stats import ProportionTest


def test_large_real_gap_is_significant():
    t = ProportionTest("mobile", "desktop", 200, 10_000, 400, 10_000)
    assert t.significant
    assert t.p_value < 1e-10
    assert "Real, not sampling noise" in t.verdict()


def test_same_gap_at_small_n_is_not_significant():
    """2.0% vs 4.0% is the same effect size as above; at n=100 it is not detectable.
    This is the whole point of running the test."""
    t = ProportionTest("mobile", "desktop", 2, 100, 4, 100)
    assert not t.significant
    assert "do not act on it" in t.verdict()


def test_identical_proportions_give_zero_z():
    t = ProportionTest("a", "b", 50, 1000, 50, 1000)
    assert t.z == pytest.approx(0.0)
    assert t.p_value == pytest.approx(1.0)


def test_p_value_matches_scipy():
    scipy = pytest.importorskip("scipy.stats")
    t = ProportionTest("a", "b", 210, 5000, 260, 5000)
    expected = 2 * scipy.norm.sf(abs(t.z))
    assert t.p_value == pytest.approx(expected, rel=1e-9)


def test_confidence_interval_brackets_the_difference():
    t = ProportionTest("a", "b", 200, 10_000, 400, 10_000)
    lo, hi = t.confidence_interval()
    assert lo < t.difference < hi
    assert hi < 0          # a is genuinely worse, so the whole interval is negative


def test_empty_segment_does_not_raise():
    t = ProportionTest("a", "b", 0, 0, 10, 100)
    assert t.z == 0.0 and t.confidence_interval() == (0.0, 0.0)
