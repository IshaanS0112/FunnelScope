"""Tests for cohort retention censoring — the trap this project is built to avoid."""

import pandas as pd
import pytest

from funnelscope import retention


LAST_DATE = pd.Timestamp("2021-01-31")


def frame():
    """Two cohorts: one early with runway, one late without."""
    return pd.DataFrame([
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 0, "active_users": 1000},
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 4, "active_users": 120},
        {"cohort_week": "2021-01-24", "cohort_size": 800,  "weeks_since_first": 0, "active_users": 800},
        {"cohort_week": "2021-01-24", "cohort_size": 800,  "weeks_since_first": 1, "active_users": 40},
    ])


def test_early_cohort_cells_are_observable():
    out = retention.mark_censored(frame(), LAST_DATE)
    early = out[out.cohort_week == pd.Timestamp("2020-11-01")]
    assert not early["censored"].any()


def test_late_cohort_week_beyond_the_window_is_censored():
    """2021-01-24 + 1 week ends 2021-02-06, past the last date in the data."""
    out = retention.mark_censored(frame(), LAST_DATE)
    late = out[(out.cohort_week == pd.Timestamp("2021-01-24")) &
               (out.weeks_since_first == 1)]
    assert bool(late["censored"].iloc[0])


def test_censored_cells_never_reach_the_average_curve():
    out = retention.mark_censored(frame(), LAST_DATE)
    curve = retention.average_curve(out)
    w1 = curve[curve.weeks_since_first == 1]
    assert w1.empty, "a censored week must not appear in the pooled curve at all"


def test_pooled_curve_is_weighted_not_a_mean_of_rates():
    df = pd.DataFrame([
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 1,
         "active_users": 100, "censored": False},
        {"cohort_week": "2020-11-08", "cohort_size": 10, "weeks_since_first": 1,
         "active_users": 9, "censored": False},
    ])
    df["retention_rate"] = df.active_users / df.cohort_size
    curve = retention.average_curve(df)
    # 109/1010 = 10.8%, not mean(10%, 90%) = 50%
    assert curve.retention_rate.iloc[0] == pytest.approx(109 / 1010)


def test_matrix_blanks_censored_cells_rather_than_zeroing_them():
    out = retention.mark_censored(frame(), LAST_DATE)
    m = retention.matrix(out, drop_censored=True)
    assert pd.isna(m.loc[pd.Timestamp("2021-01-24").date(), 1])


def test_censoring_summary_reports_share():
    out = retention.mark_censored(frame(), LAST_DATE)
    s = retention.censoring_summary(out)
    assert s["cells_total"] == 4 and s["cells_censored"] == 1
    assert s["share_censored"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Densification — the bug that made the censored share read as zero
# ---------------------------------------------------------------------------

def sparse_frame():
    """A grid as the SQL actually emits it: rows exist only where someone came back.

    Cohort 2020-11-01 has no row at week 2 — nobody returned that week. Cohort
    2021-01-24 has no rows past week 0 because week 1 is outside the data. Those two
    absences are indistinguishable until the grid is densified.
    """
    return pd.DataFrame([
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 0, "active_users": 1000},
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 1, "active_users": 200},
        {"cohort_week": "2020-11-01", "cohort_size": 1000, "weeks_since_first": 3, "active_users": 90},
        {"cohort_week": "2021-01-24", "cohort_size": 800,  "weeks_since_first": 0, "active_users": 800},
    ])


def test_densify_fills_the_full_rectangle():
    dense = retention.densify(sparse_frame(), LAST_DATE)
    cohorts = dense["cohort_week"].nunique()
    weeks = dense["weeks_since_first"].nunique()
    assert len(dense) == cohorts * weeks, "every cohort must have every week"


def test_densify_turns_a_missing_observable_week_into_a_real_zero():
    """Week 2 of the November cohort was observable and nobody came back. That is a 0%,
    and it belongs in the average — dropping it silently inflates retention."""
    dense = retention.densify(sparse_frame(), LAST_DATE)
    cell = dense[(dense.cohort_week == pd.Timestamp("2020-11-01")) &
                 (dense.weeks_since_first == 2)]
    assert len(cell) == 1 and int(cell["active_users"].iloc[0]) == 0


def test_densify_carries_cohort_size_onto_the_filled_cells():
    dense = retention.densify(sparse_frame(), LAST_DATE)
    late = dense[dense.cohort_week == pd.Timestamp("2021-01-24")]
    assert set(late["cohort_size"]) == {800}


def test_censored_share_is_nonzero_only_after_densifying():
    """The regression this exists for: on the sparse grid nothing is censored, because
    censoring can only be marked on rows that exist."""
    sparse = retention.mark_censored(sparse_frame(), LAST_DATE)
    dense = retention.mark_censored(retention.densify(sparse_frame(), LAST_DATE), LAST_DATE)
    assert retention.censoring_summary(sparse)["cells_censored"] == 0
    assert retention.censoring_summary(dense)["cells_censored"] > 0


def test_densified_zero_cells_lower_the_pooled_curve():
    """Sparse-grid retention is biased upward: a week with no returners is invisible
    rather than zero, so the denominator silently shrinks."""
    sparse = retention.mark_censored(sparse_frame(), LAST_DATE)
    dense = retention.mark_censored(retention.densify(sparse_frame(), LAST_DATE), LAST_DATE)
    w2_sparse = retention.average_curve(sparse).query("weeks_since_first == 2")
    w2_dense = retention.average_curve(dense).query("weeks_since_first == 2")
    assert w2_sparse.empty, "week 2 does not exist at all in the sparse grid"
    assert float(w2_dense["retention_rate"].iloc[0]) == pytest.approx(0.0)
