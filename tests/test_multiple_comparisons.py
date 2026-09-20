"""Tests for Holm-Bonferroni correction across a family of segment comparisons.

The correction is cheap to implement and easy to implement wrongly. The two bugs worth
guarding are (a) forgetting the step-down stop, which silently makes the procedure
invalid and more powerful, and (b) losing the caller's ordering when returning results.
"""

import pytest

from funnelscope.stats import (ProportionTest, adjusted_p_values, correct_family,
                               holm_bonferroni)


def test_empty_family_is_not_an_error():
    assert holm_bonferroni([]) == []
    assert adjusted_p_values([]) == []


def test_single_test_is_uncorrected():
    assert holm_bonferroni([0.04]) == [True]
    assert adjusted_p_values([0.04]) == pytest.approx([0.04])


def test_smallest_p_is_compared_against_alpha_over_m():
    """m = 4, so the smallest p-value faces 0.05/4 = 0.0125."""
    assert holm_bonferroni([0.012, 0.9, 0.9, 0.9])[0] is True
    assert holm_bonferroni([0.013, 0.9, 0.9, 0.9])[0] is False


def test_holm_stops_at_the_first_failure():
    """The step-down stop is the whole difference from Bonferroni. p = 0.030 would clear
    its own threshold of 0.05/2 = 0.025... it does not, and because it fails, the 0.031
    behind it is retained too even though 0.031 < 0.05."""
    reject = holm_bonferroni([0.001, 0.030, 0.031], alpha=0.05)
    assert reject == [True, False, False]


def test_holm_is_at_least_as_powerful_as_bonferroni():
    ps = [0.001, 0.012, 0.02, 0.4]
    holm = holm_bonferroni(ps, alpha=0.05)
    bonferroni = [p <= 0.05 / len(ps) for p in ps]
    assert sum(holm) >= sum(bonferroni)


def test_results_come_back_in_the_callers_order():
    """Input is deliberately unsorted; output must line up with the input, not with the
    internal sort."""
    ps = [0.9, 0.0001, 0.5]
    assert holm_bonferroni(ps) == [False, True, False]
    adj = adjusted_p_values(ps)
    assert adj[1] < adj[2] <= adj[0]


def test_adjusted_p_values_are_monotone_in_the_sorted_order():
    """An adjusted p-value must never be smaller than that of a more significant
    hypothesis, which is what the running maximum enforces."""
    ps = [0.001, 0.02, 0.021, 0.5]
    adj = adjusted_p_values(ps)
    in_sorted_order = [adj[i] for i in sorted(range(len(ps)), key=lambda i: ps[i])]
    assert in_sorted_order == sorted(in_sorted_order)


def test_adjusted_p_values_are_capped_at_one():
    assert all(p <= 1.0 for p in adjusted_p_values([0.4, 0.5, 0.9]))


def test_adjusted_p_values_agree_with_statsmodels_if_available():
    sm = pytest.importorskip("statsmodels.stats.multitest")
    ps = [0.001, 0.012, 0.02, 0.04, 0.4]
    _, adj, _, _ = sm.multipletests(ps, alpha=0.05, method="holm")
    assert adjusted_p_values(ps) == pytest.approx(list(adj))


def test_correct_family_overrides_the_raw_verdict():
    """A comparison that clears alpha alone but not the family correction must come back
    labelled as unproven -- the corrected verdict is the one the memo is allowed to
    quote."""
    strong = ProportionTest("a", "b", 400, 10_000, 200, 10_000)
    # p is about 0.044 each: clears alpha alone, fails alpha/(m-k) at m = 4.
    borderline = [ProportionTest(f"c{i}", f"d{i}", 62, 1_000, 42, 1_000) for i in range(3)]
    out = correct_family([strong] + borderline, alpha=0.05)

    assert out[0]["significant_holm"] is True
    for row in out[1:]:
        assert row["significant_raw"] is True, "each is significant on its own"
        assert row["significant_holm"] is False
        assert row["significant"] is False, "the corrected verdict must be THE verdict"
        assert "NOT after Holm" in row["verdict"]
        assert row["p_value_adjusted"] > row["p_value"]


def test_correct_family_records_the_family_size():
    tests = [ProportionTest("a", "b", 400, 10_000, 200, 10_000)] * 3
    for row in correct_family(tests):
        assert row["family_size"] == 3
        assert row["correction"] == "Holm-Bonferroni"
