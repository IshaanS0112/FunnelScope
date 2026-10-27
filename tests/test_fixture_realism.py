"""The fixture must reproduce the GA4 behaviours that break a naive funnel.

PART 7 / "Gate 3" of the spec: a fixture that satisfies the cross-validation gate
trivially tests nothing. The first version of this fixture gave every user exactly one
of each event at distinct timestamps, so the two funnel methods agreed no matter which
was wrong -- and the divergence was only found when the real BigQuery export failed the
gate. These tests exist so that cannot happen twice.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import make_fixture  # noqa: E402


@pytest.fixture(scope="module")
def log() -> pd.DataFrame:
    return make_fixture.simulate(np.random.default_rng(make_fixture.SEED))


def test_users_repeat_funnel_steps(log):
    """Without repeat events, "first cart after first view" and "ever carted after ever
    viewing" are the same question, and a method-B regex over all events cannot diverge
    from method A however wrong either is. On the real GA4 export they differed by 17%."""
    per_user = log[log.event_name == "view_item"].groupby("user_pseudo_id").size()
    assert per_user.max() > 1, "no user views an item more than once"
    assert (per_user > 1).mean() > 0.3, "repeat browsing is too rare to exercise anything"

    carts = log[log.event_name == "add_to_cart"].groupby("user_pseudo_id").size()
    assert (carts > 1).any(), "no user ever adds to cart twice"


def test_some_users_cart_at_the_same_microsecond_as_viewing(log):
    """GA4 stamps every event in one request with the same event_timestamp, so adding to
    cart from a listing ties with the view. 11.3% of carting users on the real export.
    Strict `>` ordering drops all of them, and an arbitrary sequence order keeps about
    half -- which is what made the two methods disagree."""
    first = (log[log.event_name.isin(("view_item", "add_to_cart"))]
             .groupby(["user_pseudo_id", "event_name"])["event_timestamp"].min()
             .unstack())
    both = first.dropna()
    ties = (both["view_item"] == both["add_to_cart"]).sum()
    assert ties > 0, "no timestamp ties — the tie-break rule is untested"
    assert ties / len(both) > 0.05, "ties too rare to catch a broken tie-break"


def test_both_funnel_methods_agree_exactly_on_the_fixture(log):
    """No tolerance. The fixture has no source of drift the two methods handle
    differently, so anything other than an exact match is a defect in one of them."""
    a = make_fixture.funnel_by_timestamps(log, None)
    b = make_fixture.funnel_by_sequence(log)
    for stage in ("viewed", "added_to_cart", "began_checkout", "purchased"):
        assert int(a[stage].iloc[0]) == int(b[stage].iloc[0]), (
            f"methods disagree at '{stage}': {int(a[stage].iloc[0])} vs "
            f"{int(b[stage].iloc[0])}")


def test_sequence_method_would_diverge_without_the_first_occurrence_rule(log):
    """The bug this all came from, reproduced: aggregating EVERY event into the sequence
    counts users whose first cart preceded their first view but who carted again after.
    If this ever stops diverging, the fixture has gone back to being too clean to test
    anything."""
    codes = log[log.event_name.isin(make_fixture.STAGE_CODE)].copy()
    codes["code"] = codes.event_name.map(make_fixture.STAGE_CODE)
    all_events = (codes.sort_values("event_timestamp")
                  .groupby("user_pseudo_id")["code"].apply("".join))
    all_events = all_events[all_events.str.contains("V")]
    naive_cart = int(all_events.str.contains(r"V.*C", regex=True).sum())

    correct = int(make_fixture.funnel_by_sequence(log)["added_to_cart"].iloc[0])
    assert naive_cart > correct, (
        "the all-events reading no longer over-counts, so the fixture cannot "
        "distinguish it from the first-occurrence reading")


def test_tie_report_matches_the_funnel_it_describes(log):
    """10_timestamp_ties must agree with the funnel on what the strict rule counted,
    or the disclosure describes a different analysis from the one published."""
    ties = make_fixture.timestamp_ties(log).set_index("step")
    funnel = make_fixture.funnel_by_timestamps(log, None).iloc[0]
    assert int(ties.loc["viewed -> added_to_cart", "counted_strict"]) == int(
        funnel["added_to_cart"])
    assert int(ties.loc["began_checkout -> purchased", "counted_strict"]) == int(
        funnel["purchased"])
    row = ties.loc["viewed -> added_to_cart"]
    assert int(row["counted_at_or_after"]) == int(row["counted_strict"]) + int(
        row["excluded_by_tie"]), "the >= count must be the strict count plus the ties"
