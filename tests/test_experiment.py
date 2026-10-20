"""Tests for experiment design.

The sample-size formula is the one piece here that is easy to get confidently wrong
(one-sided vs two-sided, per arm vs total, absolute vs relative lift), so it is pinned
against statsmodels rather than against a number worked out by hand.
"""

import math

import pandas as pd
import pytest

from funnelscope import experiment as ex

ROW = pd.Series({"segment_value": "all", "viewed": 61_252, "added_to_cart": 11_114,
                 "began_checkout": 4_167, "purchased": 2_356})


@pytest.mark.parametrize("baseline,lift", [(0.181, 0.01), (0.181, 0.02), (0.375, 0.05),
                                           (0.565, 0.03), (0.05, 0.005)])
def test_sample_size_matches_statsmodels(baseline, lift):
    power = pytest.importorskip("statsmodels.stats.power")
    prop = pytest.importorskip("statsmodels.stats.proportion")
    expected = power.NormalIndPower().solve_power(
        effect_size=prop.proportion_effectsize(baseline + lift, baseline),
        alpha=0.05, power=0.80, ratio=1.0, alternative="two-sided")
    assert ex.sample_size_per_arm(baseline, lift) == math.ceil(expected) or \
        ex.sample_size_per_arm(baseline, lift) == pytest.approx(expected, rel=1e-3)


def test_smaller_lifts_need_more_users():
    sizes = [ex.sample_size_per_arm(0.181, lift) for lift in (0.005, 0.01, 0.02, 0.05)]
    assert sizes == sorted(sizes, reverse=True)


def test_halving_the_lift_roughly_quadruples_the_sample():
    """n scales with 1/effect^2 — the reason small lifts are so expensive to detect."""
    ratio = ex.sample_size_per_arm(0.181, 0.01) / ex.sample_size_per_arm(0.181, 0.02)
    assert 3.6 < ratio < 4.4


def test_more_power_needs_more_users():
    assert ex.sample_size_per_arm(0.181, 0.02, power=0.9) > ex.sample_size_per_arm(0.181, 0.02)


def test_rates_outside_zero_one_are_rejected():
    with pytest.raises(ValueError):
        ex.sample_size_per_arm(0.98, 0.05)


def test_days_count_both_arms():
    assert ex.days_to_run(n_per_arm=1_000, eligible_per_day=100) == pytest.approx(20.0)


def test_planned_days_never_drop_below_two_weekly_cycles():
    assert ex.planned_days(3.2) == ex.MIN_DAYS
    assert ex.planned_days(18.2) == 21
    assert ex.planned_days(21.0) == 21


def test_plan_finds_the_smallest_lift_that_fits_four_weeks():
    plan = ex.plan_for_step(ROW, "added_to_cart", aov=63.63, window_days=92)
    assert plan.baseline == pytest.approx(11_114 / 61_252)
    assert plan.eligible_per_day == pytest.approx(61_252 / 92)
    fits = [g for g in plan.grid if g["fits"]]
    assert plan.smallest_detectable_lift == fits[0]["lift"]
    assert all(not g["fits"] for g in plan.grid if g["lift"] < plan.smallest_detectable_lift)
    assert plan.planned_days <= ex.MAX_DAYS


def test_later_steps_are_harder_to_test():
    """Fewer shoppers reach each later step, so the detectable lift can only grow."""
    lifts = [ex.plan_for_step(ROW, s, 63.63, 92).smallest_detectable_lift
             for s in ("added_to_cart", "began_checkout", "purchased")]
    assert lifts == sorted(lifts)


def test_guardrails_always_include_aov_and_the_next_step():
    cart = ex.plan_for_step(ROW, "added_to_cart", aov=63.63, window_days=92)
    names = [g["metric"] for g in cart.guardrails]
    assert any("order value" in n for n in names)
    assert any("began checkout" in n for n in names), "the step after the test must be guarded"
    last = ex.plan_for_step(ROW, "purchased", aov=63.63, window_days=92)
    assert [g["metric"] for g in last.guardrails] == ["Average order value"]


def test_grid_value_matches_the_sizing_model():
    """The planner's 'worth if it works' must be the same number sizing.py produces."""
    from funnelscope import funnel, sizing
    plan = ex.plan_for_step(ROW, "added_to_cart", aov=63.63, window_days=92)
    t = next(x for x in funnel.transitions(ROW) if x.to_stage == "added_to_cart")
    g = next(g for g in plan.grid if g["lift"] == 0.02)
    assert g["worth_up_to"] == pytest.approx(
        sizing.size_stage(ROW, t, 63.63, improvement_pp=0.02).recoverable_revenue)
