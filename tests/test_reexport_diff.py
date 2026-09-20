"""Tests for the re-export diff.

The diff exists to make a broken re-run visible the moment it happens. Its failure mode
is being either too noisy to read or too quiet to notice, so both directions are pinned.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import analyze  # noqa: E402


def metrics(viewed=10_000, purchased=900, aov=50.0, censored=0.25):
    return {
        "funnel": {"viewed": viewed, "added_to_cart": 3_000, "began_checkout": 1_500,
                   "purchased": purchased,
                   "end_to_end_conversion": purchased / viewed},
        "aov": aov,
        "opportunities": [{"to_stage": "added_to_cart", "recoverable_revenue": 7_500.0}],
        "retention": {"censoring": {"share_censored": censored},
                      "curve": [{"weeks_since_first": 1, "retention_rate": 0.31},
                                {"weeks_since_first": 4, "retention_rate": 0.12}]},
    }


def test_first_export_has_nothing_to_compare_against():
    assert analyze.reexport_diff(metrics(), None) == []


def test_an_unchanged_re_export_reports_nothing():
    assert analyze.reexport_diff(metrics(), metrics()) == []


def test_a_moved_metric_is_reported_with_its_percentage_change():
    moved = analyze.reexport_diff(metrics(purchased=990), metrics(purchased=900))
    by_metric = {d["metric"]: d for d in moved}
    assert by_metric["funnel.purchased"]["change_pct"] == pytest.approx(10.0)
    assert by_metric["funnel.purchased"]["previous"] == 900
    assert by_metric["funnel.purchased"]["current"] == 990


def test_a_metric_that_vanishes_is_flagged_rather_than_ignored():
    """A channel that stops firing, or a query that silently returns fewer rows, must
    not disappear quietly."""
    before = metrics()
    after = metrics()
    after["opportunities"] = []
    moved = analyze.reexport_diff(after, before)
    assert any(d["note"] == "disappeared" for d in moved)


def test_a_new_metric_is_flagged_as_appeared():
    before = metrics()
    before["opportunities"] = []
    moved = analyze.reexport_diff(metrics(), before)
    assert any(d["note"] == "appeared" for d in moved)


def test_diff_ignores_non_numeric_fields():
    """Only scalars are compared; a changed banner string is not a moved metric."""
    a, b = metrics(), metrics()
    a["provenance"] = {"banner": "one"}
    b["provenance"] = {"banner": "two"}
    assert analyze.reexport_diff(a, b) == []


def test_zero_previous_value_does_not_divide_by_zero():
    moved = analyze.reexport_diff(metrics(censored=0.4), metrics(censored=0.0))
    entry = next(d for d in moved if d["metric"] == "retention.censored_share")
    assert entry["change_pct"] is None
