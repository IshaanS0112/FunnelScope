"""Tests for the funnel invariants and the gates that enforce them."""

import pandas as pd
import pytest

from funnelscope import FUNNEL_STAGES, funnel


def make_row(viewed=1000, cart=300, checkout=150, purchased=80, value="all"):
    return pd.DataFrame([{
        "segment_type": "all", "segment_value": value, "viewed": viewed,
        "added_to_cart": cart, "began_checkout": checkout, "purchased": purchased,
    }])


def test_monotonic_funnel_passes():
    funnel.check_monotonic(make_row())


def test_non_monotonic_funnel_is_rejected():
    """The exact failure mode of independent (non-cumulative) stage predicates:
    more users beginning checkout than ever added to cart."""
    bad = make_row(cart=300, checkout=310)
    with pytest.raises(funnel.FunnelValidationError, match="not monotonic"):
        funnel.check_monotonic(bad)


def test_cross_validation_accepts_small_tie_driven_drift():
    a = make_row(1000, 300, 150, 80)
    b = make_row(1000, 301, 150, 80)   # 0.33% — plausible timestamp ties
    result = funnel.cross_validate(a, b, tolerance=0.005)
    assert result["within_tolerance"].all()


def test_cross_validation_rejects_real_divergence():
    a = make_row(1000, 300, 150, 80)
    b = make_row(1000, 380, 150, 80)   # 21% — a bug, not ties
    with pytest.raises(funnel.FunnelValidationError, match="disagree"):
        funnel.cross_validate(a, b, tolerance=0.005)


def test_transitions_cover_every_step():
    ts = funnel.transitions(make_row().iloc[0])
    assert [t.to_stage for t in ts] == list(FUNNEL_STAGES[1:])
    assert ts[0].entered == 1000 and ts[0].completed == 300
    assert ts[0].lost == 700
    assert ts[0].step_conversion == pytest.approx(0.30)


def test_worst_step_is_by_rate_not_by_volume():
    """view->cart loses the most users; cart->checkout has the worse rate.
    worst_step must pick the rate, because the volume story is the sizing model's job."""
    row = make_row(viewed=1000, cart=500, checkout=100, purchased=90).iloc[0]
    w = funnel.worst_step(row)
    assert (w.from_stage, w.to_stage) == ("added_to_cart", "began_checkout")


def test_with_rates_adds_expected_columns():
    out = funnel.with_rates(make_row())
    assert out["cum_conv_purchased"].iloc[0] == pytest.approx(0.08)
    assert out["step_conv_added_to_cart"].iloc[0] == pytest.approx(0.30)
    assert out["lost_at_viewed"].iloc[0] == 700


def test_zero_viewers_does_not_divide_by_zero():
    out = funnel.with_rates(make_row(0, 0, 0, 0))
    assert pd.isna(out["cum_conv_purchased"].iloc[0])
