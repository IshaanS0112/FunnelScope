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
