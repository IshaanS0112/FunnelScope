"""Cohort retention, and the censoring correction that keeps it honest.

The trap this module exists to defuse: in a fixed 3-month window, a cohort formed in
week 10 cannot possibly show week-8 retention -- week 18 is outside the data. Plotted
naively, those cells read as zero and the late cohorts look like a retention collapse.
They are right-censored, not worse.

Every cell is therefore tagged `censored` when the cohort's week-N observation window
extends past the last date present in the data, and no censored cell is ever included
in an average, a trend, or a chart.
"""

from __future__ import annotations

import pandas as pd


def densify(df: pd.DataFrame, last_date: pd.Timestamp) -> pd.DataFrame:
    """Expand the grid to the full cohort x week rectangle, filling gaps with zero.

    WHY THIS HAS TO HAPPEN BEFORE CENSORING IS MARKED. The retention query joins
    cohorts to activity, so it emits a row only where `active_users > 0`. A week in
    which nobody from a cohort came back produces no row at all -- which makes a
    genuinely-zero cell indistinguishable from a cell that lies outside the data.
    Censoring can only ever be marked on rows that exist, so on a sparse grid the
    censored share is computed over observed cells only and comes out far too low; in
    a grid that happens to end on a week boundary it comes out as exactly zero, and
    the whole censoring apparatus silently tests nothing.

    Densifying first separates the two cases properly:
      * observable and nobody returned -> a real 0%, included in every average;
      * not observable yet             -> censored, excluded from every average.

    The horizon is set by the earliest cohort, which is the only one with a full
    runway: weeks 0..floor((last_date - earliest_cohort_week) / 7). Later cohorts get
    rows across that same range, and the ones past their own runway are exactly the
    cells `mark_censored` will flag.
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
    """Tag (cohort_week, weeks_since_first) cells whose window runs past the data end.

    A cell is observable only if cohort_week + weeks_since_first weeks is fully
    contained in the data, i.e. the whole 7-day observation week ends on or before
    `last_date`.
    """
    out = df.copy()
    out["cohort_week"] = pd.to_datetime(out["cohort_week"])
    week_start = out["cohort_week"] + pd.to_timedelta(out["weeks_since_first"] * 7, unit="D")
    week_end = week_start + pd.Timedelta(days=6)
    out["observation_week_end"] = week_end
    out["censored"] = week_end > pd.Timestamp(last_date)
    out["retention_rate"] = out["active_users"] / out["cohort_size"]
    return out


def matrix(df: pd.DataFrame, drop_censored: bool = True) -> pd.DataFrame:
    """Cohort x weeks-since-first retention matrix. Censored cells become NaN.

    The grid is reindexed over the full observed week range so that a censored cell is
    a visible blank in the heatmap rather than a column that quietly does not exist.
    A missing column reads as "no data collected"; a blank cell reads as "not yet
    observable", which is the true statement.
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
    """Retention by week-since-first, pooled across cohorts, uncensored cells only.

    Pooled as sum(active)/sum(cohort_size) rather than as a mean of per-cohort rates,
    so a tiny cohort cannot swing the curve as much as a large one.
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
    """How much of the grid is censored -- quoted in the memo's limitations section."""
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
