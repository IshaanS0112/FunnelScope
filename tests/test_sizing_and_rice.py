"""Tests for opportunity sizing and RICE ranking."""

import random

import pandas as pd
import pytest

from funnelscope import rice, sizing


ROW = pd.DataFrame([{
    "segment_type": "all", "segment_value": "all",
    "viewed": 10_000, "added_to_cart": 3_000,
    "began_checkout": 1_500, "purchased": 900,
}]).iloc[0]


def test_downstream_conversion_is_measured_on_completers():
    assert sizing.downstream_conversion(ROW, "added_to_cart") == pytest.approx(0.30)
    assert sizing.downstream_conversion(ROW, "purchased") == pytest.approx(1.0)


def test_sizing_formula_is_exactly_the_documented_one():
    """A 5pp lift on a 30% step recovers 5% of users ENTERING, not 5% of users lost."""
    opps = sizing.size_all_stages(ROW, aov=50.0, improvement_pp=0.05)
    top = opps[opps.to_stage == "added_to_cart"].iloc[0]
    assert top["users_recovered"] == pytest.approx(10_000 * 0.05)
    assert top["recoverable_revenue"] == pytest.approx(10_000 * 0.05 * 0.30 * 50.0)


def test_lost_basis_understates_a_percentage_point_lift():
    """The textbook `users_lost x pp` form is a different, smaller claim. Both are
    available; they must not be confused, so the gap is pinned down here."""
    entering = sizing.size_all_stages(ROW, aov=50.0, basis="entering")
    lost = sizing.size_all_stages(ROW, aov=50.0, basis="lost")
    e = entering[entering.to_stage == "added_to_cart"].iloc[0]
    l = lost[lost.to_stage == "added_to_cart"].iloc[0]
    step_rate = 3_000 / 10_000
    assert l["recoverable_revenue"] == pytest.approx(
        e["recoverable_revenue"] * (1 - step_rate))


def test_recovery_is_capped_at_the_users_actually_lost():
    """A 50pp lift on a step that only loses 40% of users cannot recover 50%."""
    row = pd.DataFrame([{"viewed": 1_000, "added_to_cart": 600,
                         "began_checkout": 300, "purchased": 100}]).iloc[0]
    opps = sizing.size_all_stages(row, aov=10.0, improvement_pp=0.50)
    top = opps[opps.to_stage == "added_to_cart"].iloc[0]
    assert top["users_recovered"] == 400  # not 500


@pytest.mark.parametrize("seed", range(25))
def test_sizing_cannot_rerank_stages(seed):
    """The claim that biggest-revenue and worst-rate are usually different stages is
    false for any strictly ordered funnel: recoverable revenue is a monotone transform
    of step conversion. Asserted over random funnels so a model change that breaks the
    equivalence fails loudly rather than silently inventing a finding."""
    rng = random.Random(seed)
    v = rng.randint(1_000, 200_000)
    c = rng.randint(1, v)
    k = rng.randint(1, c)
    p = rng.randint(1, k)
    row = pd.DataFrame([{"viewed": v, "added_to_cart": c,
                         "began_checkout": k, "purchased": p}]).iloc[0]
    assert sizing.ranking_matches_step_conversion(row)


def test_sensitivity_preserves_ranking_across_assumptions():
    sens = sizing.sensitivity_table(ROW, aov=50.0)
    numeric = sens.set_index("to_stage").drop(columns=[], errors="ignore")
    orders = [tuple(numeric[c].sort_values(ascending=False).index) for c in numeric.columns]
    assert len(set(orders)) == 1, "ranking must not depend on the improvement assumption"


def test_aov_is_transaction_weighted():
    rev = pd.DataFrame([{"purchases": 100, "revenue_usd": 5_000.0},
                        {"purchases": 900, "revenue_usd": 18_000.0}])
    # 23000 / 1000, not the mean of 50 and 20
    assert sizing.aov_from_revenue(rev) == pytest.approx(23.0)


def test_zero_purchases_gives_zero_aov_not_nan():
    rev = pd.DataFrame([{"purchases": 0, "revenue_usd": 0.0}])
    assert sizing.aov_from_revenue(rev) == 0.0


def test_segment_gap_value():
    a = pd.Series({"segment_value": "mobile", "viewed": 10_000, "purchased": 200})
    b = pd.Series({"segment_value": "desktop", "viewed": 8_000, "purchased": 320})
    gap = sizing.segment_gap_value(a, b, aov=50.0)
    assert gap["gap_pp"] == pytest.approx(2.0)          # 4.0% - 2.0%
    assert gap["value_if_closed"] == pytest.approx(0.02 * 10_000 * 50.0)


def test_rice_ranks_by_score_and_effort_matters():
    recs = [
        rice.Recommendation("cheap", "", reach=1000, impact=1.0, confidence=0.8, effort=1.0),
        rice.Recommendation("expensive", "", reach=1000, impact=1.0, confidence=0.8, effort=8.0),
    ]
    ranked = rice.rank(recs)
    assert list(ranked["name"]) == ["cheap", "expensive"]
    assert ranked.iloc[0]["rice_score"] == pytest.approx(800.0)


def test_rice_handles_zero_effort_without_dividing_by_zero():
    r = rice.Recommendation("x", "", reach=10, impact=1, confidence=1, effort=0)
    assert r.score == 0.0


# ---------------------------------------------------------------------------
# Bootstrap intervals
# ---------------------------------------------------------------------------

def test_bootstrap_interval_brackets_the_point_estimate():
    out = sizing.bootstrap_recoverable(ROW, aov=50.0, n_resamples=400)
    for _, r in out.iterrows():
        assert r["ci_low"] <= r["recoverable_revenue"] <= r["ci_high"]


def test_bootstrap_point_estimates_match_the_deterministic_model():
    """The interval is uncertainty around the sizing model, not a different model."""
    point = sizing.size_all_stages(ROW, aov=50.0).set_index("to_stage")
    out = sizing.bootstrap_recoverable(ROW, aov=50.0, n_resamples=200).set_index("to_stage")
    for stage in point.index:
        assert out.loc[stage, "recoverable_revenue"] == pytest.approx(
            point.loc[stage, "recoverable_revenue"])


def test_bootstrap_is_reproducible_from_the_seed():
    a = sizing.bootstrap_recoverable(ROW, aov=50.0, n_resamples=200, seed=7)
    b = sizing.bootstrap_recoverable(ROW, aov=50.0, n_resamples=200, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_bootstrap_interval_narrows_as_the_funnel_gets_bigger():
    """Sampling variation is what this interval prices, so a 100x larger funnel with the
    same rates must produce a proportionally tighter relative interval."""
    def rel_width(row, aov):
        out = sizing.bootstrap_recoverable(row, aov=aov, n_resamples=600, seed=3)
        top = out.iloc[0]
        return (top["ci_high"] - top["ci_low"]) / top["recoverable_revenue"]

    small = pd.DataFrame([{"viewed": 1_000, "added_to_cart": 300,
                           "began_checkout": 150, "purchased": 90}]).iloc[0]
    assert rel_width(ROW, 50.0) < rel_width(small, 50.0)


def test_bootstrap_ranking_matches_the_point_estimate_ranking():
    """The no-re-ranking result is a property of the model, so resampling must not
    disturb it."""
    out = sizing.bootstrap_recoverable(ROW, aov=50.0, n_resamples=200)
    point = sizing.size_all_stages(ROW, aov=50.0)
    assert list(out["to_stage"]) == list(point["to_stage"])
