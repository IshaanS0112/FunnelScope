"""Cohort retention, with right-censoring handled.

In a fixed window a cohort formed in week 10 cannot show week-8 retention — week 18 is
outside the data. Plotted naively those cells read as zero and late cohorts look like a
collapse. They are censored, not worse, so they are excluded from every average and
chart and left blank in the heatmap.
"""

from __future__ import annotations

import pandas as pd


def densify(df: pd.DataFrame, last_date: pd.Timestamp) -> pd.DataFrame:
    """Expand the grid to the full cohort x week rectangle, filling gaps with zero.

    Must run BEFORE censoring is marked. The query emits no row for a week nobody
    returned, so a real zero and an unobservable cell look identical — and censoring
    can only be marked on rows that exist. On the sparse grid the censored share comes
    out far too low, sometimes exactly zero.

    Horizon is the earliest cohort's runway; later cohorts get the same week range, and
    the cells past their own runway are what mark_censored flags.
    """
    d = df.copy()
    d["cohort_week"] = pd.to_datetime(d["cohort_week"])
    sizes = d.groupby("cohort_week")["cohort_size"].max()
    earliest = sizes.index.min()
    horizon = max(int((pd.Timestamp(last_date) - earliest).days // 7),
                  int(d["weeks_since_first"].max()))

    grid = pd.MultiIndex.from_product(
        [sizes.index, range(horizon + 1)],
        names=["cohort_week", "weeks_since_first"]).to_frame(index=False)
    out = grid.merge(d[["cohort_week", "weeks_since_first", "active_users"]],
                     on=["cohort_week", "weeks_since_first"], how="left")
    out["active_users"] = out["active_users"].fillna(0).astype(int)
    out["cohort_size"] = out["cohort_week"].map(sizes).astype(int)
    return out[["cohort_week", "cohort_size", "weeks_since_first", "active_users"]] \
        .sort_values(["cohort_week", "weeks_since_first"]).reset_index(drop=True)


def mark_censored(df: pd.DataFrame, last_date: pd.Timestamp) -> pd.DataFrame:
    """Tag cells whose 7-day observation window ends after `last_date`."""
    out = df.copy()
    out["cohort_week"] = pd.to_datetime(out["cohort_week"])
    week_start = out["cohort_week"] + pd.to_timedelta(out["weeks_since_first"] * 7, unit="D")
    week_end = week_start + pd.Timedelta(days=6)
    out["observation_week_end"] = week_end
    out["censored"] = week_end > pd.Timestamp(last_date)
    out["retention_rate"] = out["active_users"] / out["cohort_size"]
    return out


def matrix(df: pd.DataFrame, drop_censored: bool = True) -> pd.DataFrame:
    """Cohort x week retention matrix, censored cells as NaN.

    Reindexed over the full week range so a censored cell is a visible blank rather
    than a missing column — "not yet observable", not "no data collected".
    """
    d = df.copy()
    if drop_censored and "censored" in d.columns:
        d = d[~d["censored"]]
    m = d.pivot_table(index="cohort_week", columns="weeks_since_first",
                      values="retention_rate", aggfunc="first")
    all_weeks = range(int(df["weeks_since_first"].min()),
                      int(df["weeks_since_first"].max()) + 1)
    all_cohorts = pd.to_datetime(df["cohort_week"]).sort_values().unique()
    m = m.reindex(index=all_cohorts, columns=list(all_weeks))
    m.index = pd.to_datetime(m.index).date
    return m


def average_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Retention by week, pooled across cohorts, uncensored cells only.

    Sum(active)/sum(cohort_size), not a mean of per-cohort rates, so a tiny cohort
    cannot swing the curve.
    """
    d = df[~df["censored"]] if "censored" in df.columns else df
    g = d.groupby("weeks_since_first").agg(
        active_users=("active_users", "sum"),
        cohort_size=("cohort_size", "sum"),
        cohorts_observed=("cohort_week", "nunique"),
    ).reset_index()
    g["retention_rate"] = g["active_users"] / g["cohort_size"]
    return g


def censoring_summary(df: pd.DataFrame) -> dict:
    """How much of the grid is censored. Quoted in the memo's limitations."""
    total = len(df)
    censored = int(df["censored"].sum()) if "censored" in df.columns else 0
    per_cohort = (
        df[~df["censored"]].groupby("cohort_week")["weeks_since_first"].max()
        if "censored" in df.columns else pd.Series(dtype=float)
    )
    return {
        "cells_total": total,
        "cells_censored": censored,
        "share_censored": censored / total if total else 0.0,
        "max_observable_week_by_cohort": {
            str(pd.Timestamp(k).date()): int(v) for k, v in per_cohort.items()
        },
    }
