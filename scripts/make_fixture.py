#!/usr/bin/env python3
"""Generate a synthetic GA4-shaped event log and aggregate it into the same CSVs
that sql/ produces against BigQuery.

WHY THIS EXISTS: so the analysis, the tests, the memo renderer and the dashboard can
be exercised end to end with no GCP account. It is a pipeline fixture, nothing else.

WHAT IT IS NOT: an analysis. The manifest it writes is stamped
`source: synthetic-fixture`, and every downstream artifact reads that stamp and labels
itself as fixture output. Replace it by running scripts/run_queries.py.

The simulator emits an actual per-user event log with timestamps, and the funnel CSVs
are aggregated from that log twice by two different methods -- exactly as
02_funnel_ordered.sql and 02b_funnel_validation.sql do -- so the cross-validation gate
in scripts/analyze.py is genuinely exercised rather than trivially satisfied.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from funnelscope import io as fio  # noqa: E402

WINDOW_START = pd.Timestamp("2020-11-01")
WINDOW_END = pd.Timestamp("2021-01-31")
N_USERS = 60_000
SEED = 20201101

DEVICES = {"mobile": 0.52, "desktop": 0.41, "tablet": 0.07}
SOURCES = {
    "google / organic":   0.34,
    "(direct) / (none)":  0.27,
    "google / cpc":       0.16,
    "youtube.com / referral": 0.09,
    "shop.googlemerch / referral": 0.06,
    "newsletter / email": 0.05,
    "partner-a / referral": 0.02,
    "partner-b / referral": 0.01,
}

# Per-step continuation probabilities. Base rates, then multipliers by segment.
BASE = {"cart": 0.28, "checkout": 0.42, "purchase": 0.55}
DEVICE_MULT = {"mobile": 0.78, "desktop": 1.18, "tablet": 0.92}
SOURCE_MULT = {
    "google / organic": 1.05, "(direct) / (none)": 1.22, "google / cpc": 0.74,
    "youtube.com / referral": 0.55, "shop.googlemerch / referral": 1.31,
    "newsletter / email": 1.40, "partner-a / referral": 0.61, "partner-b / referral": 0.68,
}
NEW_MULT = {"new": 0.82, "returning": 1.35}

STAGE_CODE = {"view_item": "V", "add_to_cart": "C", "begin_checkout": "K", "purchase": "P"}

# Probability that a funnel step happens in a LATER session rather than the current one.
# Without this the session-scoped funnel (09) would be identical to the user-scoped one
# (02) and the comparison between them would measure nothing.
P_RETURN_BEFORE = {"add_to_cart": 0.22, "begin_checkout": 0.14, "purchase": 0.18}

MIN_USERS_PER_CHANNEL = 500   # mirrors @min_users in sql/04_funnel_by_source.sql


def simulate(rng: np.random.Generator) -> pd.DataFrame:
    """Return a long event log: one row per (user, event)."""
    n = N_USERS
    device = rng.choice(list(DEVICES), size=n, p=list(DEVICES.values()))
    source = rng.choice(list(SOURCES), size=n, p=list(SOURCES.values()))
    visitor = np.where(rng.random(n) < 0.71, "new", "returning")

    span_days = (WINDOW_END - WINDOW_START).days
    first_day = rng.integers(0, span_days + 1, size=n)
    # Traffic skews to the shopping season -- squeeze the distribution toward late Nov.
    first_day = np.clip((first_day * 0.85 + rng.integers(0, 20, size=n)), 0, span_days).astype(int)

    dmul = np.array([DEVICE_MULT[d] for d in device])
    smul = np.array([SOURCE_MULT[s] for s in source])
    vmul = np.array([NEW_MULT[v] for v in visitor])
    combined = dmul * smul * vmul

    p_cart = np.clip(BASE["cart"] * combined, 0, 0.95)
    p_checkout = np.clip(BASE["checkout"] * (1 + (combined - 1) * 0.6), 0, 0.95)
    p_purchase = np.clip(BASE["purchase"] * (1 + (combined - 1) * 0.4), 0, 0.95)

    did_cart = rng.random(n) < p_cart
    did_checkout = did_cart & (rng.random(n) < p_checkout)
    did_purchase = did_checkout & (rng.random(n) < p_purchase)

    rows = []
    base_ts = WINDOW_START.value // 1000  # microseconds
    day_us = 86_400_000_000
    window_end_us = WINDOW_END.value // 1000
    for i in range(n):
        t0 = base_ts + int(first_day[i]) * day_us + int(rng.integers(0, day_us))
        common = dict(user_pseudo_id=f"u{i:07d}", device_category=device[i],
                      source_medium=source[i], visitor_type=visitor[i])
        session = 1

        def emit(event_name, ts, revenue=0.0):
            rows.append({**common, "event_name": event_name, "event_timestamp": ts,
                         "ga_session_id": session, "revenue_usd": revenue})

        if visitor[i] == "new":
            emit("first_visit", t0 - 1)
        emit("view_item", t0)
        t = t0

        def advance(step, t):
            """Move time forward, and sometimes start a new session while doing it."""
            nonlocal session
            if rng.random() < P_RETURN_BEFORE[step]:
                session += 1
                return t + int(rng.integers(1, 14)) * day_us + int(rng.integers(0, day_us))
            return t + int(rng.integers(30_000_000, 3_600_000_000))

        if did_cart[i]:
            t = advance("add_to_cart", t)
            emit("add_to_cart", t)
        if did_checkout[i]:
            t = advance("begin_checkout", t)
            emit("begin_checkout", t)
        if did_purchase[i]:
            t = advance("purchase", t)
            emit("purchase", t, float(np.round(rng.lognormal(mean=4.0, sigma=0.55), 2)))
        # Return visits, so retention is not degenerate.
        for k in range(int(rng.poisson(1.1 if did_purchase[i] else 0.5))):
            back = t0 + int(rng.integers(1, 45)) * day_us
            if back <= window_end_us:
                session += 1
                emit("session_start", back)
    out = pd.DataFrame(rows)
    # Funnel events that ran past the window end would not appear in a real export
    # restricted by _TABLE_SUFFIX. Drop them here for the same reason.
    return out[out["event_timestamp"] <= window_end_us].reset_index(drop=True)


def funnel_by_timestamps(log: pd.DataFrame, by: str | None,
                         unit: tuple[str, ...] = ("user_pseudo_id",)) -> pd.DataFrame:
    """Method A -- first-occurrence timestamps per `unit`, with cumulative predicates.
    Mirrors 02_funnel_ordered.sql (unit = the user) and 09_funnel_session_scoped.sql
    (unit = the user's session)."""
    keys = list(unit) + ([by] if by else [])
    piv = (log[log.event_name.isin(STAGE_CODE)]
           .pivot_table(index=keys, columns="event_name",
                        values="event_timestamp", aggfunc="min"))
    for col in STAGE_CODE:
        if col not in piv.columns:
            piv[col] = np.nan
    piv = piv.reset_index()
    piv = piv[piv["view_item"].notna()]

    c1 = piv["add_to_cart"] > piv["view_item"]
    c2 = c1 & (piv["begin_checkout"] > piv["add_to_cart"])
    c3 = c2 & (piv["purchase"] > piv["begin_checkout"])
    piv = piv.assign(_cart=c1, _checkout=c2, _purchase=c3)

    group = piv.groupby(by) if by else [("all", piv)]
    out = []
    for value, g in (group if by else group):
        out.append({
            "segment_type": by or "all",
            "segment_value": value,
            "viewed": len(g),
            "added_to_cart": int(g["_cart"].sum()),
            "began_checkout": int(g["_checkout"].sum()),
            "purchased": int(g["_purchase"].sum()),
        })
    return pd.DataFrame(out).sort_values("viewed", ascending=False).reset_index(drop=True)


def funnel_by_sequence(log: pd.DataFrame) -> pd.DataFrame:
    """Method B -- collapse each user's events to an ordered string, test with regex.
    Mirrors 02b_funnel_validation.sql. Shares no logic with method A."""
    d = log[log.event_name.isin(STAGE_CODE)].sort_values("event_timestamp")
    seq = (d.assign(code=d.event_name.map(STAGE_CODE))
             .groupby("user_pseudo_id")["code"].apply("".join))
    seq = seq[seq.str.contains("V")]
    return pd.DataFrame([{
        "segment_type": "all",
        "segment_value": "all",
        "viewed": int(len(seq)),
        "added_to_cart": int(seq.str.contains(r"V.*C", regex=True).sum()),
        "began_checkout": int(seq.str.contains(r"V.*C.*K", regex=True).sum()),
        "purchased": int(seq.str.contains(r"V.*C.*K.*P", regex=True).sum()),
    }])


def funnel_by_sessions(log: pd.DataFrame) -> pd.DataFrame:
    """The same funnel scoped to the session rather than the user.
    Mirrors 09_funnel_session_scoped.sql. Its conversion is necessarily <= the
    user-scoped figure, and the gap measures dependence on return visits."""
    out = funnel_by_timestamps(log, None, unit=("user_pseudo_id", "ga_session_id"))
    out["segment_type"] = "scope"
    out["segment_value"] = "session"
    return out


def fold_long_tail(df: pd.DataFrame, min_users: int = MIN_USERS_PER_CHANNEL) -> pd.DataFrame:
    """Collapse channels below `min_users` into '(long tail)'.

    Mirrors the @min_users branch in sql/04_funnel_by_source.sql. A channel with 40
    users and one purchase has a confidence interval wide enough to contain almost
    anything; reporting it as a finding would be noise dressed as signal. Applied here
    too so the fixture and the BigQuery export have the same shape -- a fixture that
    skips this would not exercise the '(long tail)' handling downstream.
    """
    small = df["viewed"] < min_users
    if not small.any():
        return df
    d = df.copy()
    d.loc[small, "segment_value"] = "(long tail)"
    agg = (d.groupby(["segment_type", "segment_value"], as_index=False)
             [["viewed", "added_to_cart", "began_checkout", "purchased"]].sum())
    return agg.sort_values("viewed", ascending=False).reset_index(drop=True)


def cohort_retention(log: pd.DataFrame) -> pd.DataFrame:
    d = log.assign(date=pd.to_datetime(log.event_timestamp, unit="us").dt.floor("D"))
    d["week"] = d["date"] - pd.to_timedelta((d["date"].dt.dayofweek + 1) % 7, unit="D")
    first = d.groupby("user_pseudo_id")["week"].min().rename("cohort_week")
    act = d[["user_pseudo_id", "week"]].drop_duplicates().join(first, on="user_pseudo_id")
    act["weeks_since_first"] = ((act["week"] - act["cohort_week"]).dt.days // 7)
    sizes = first.reset_index().groupby("cohort_week").size().rename("cohort_size")
    g = (act.groupby(["cohort_week", "weeks_since_first"])["user_pseudo_id"]
            .nunique().rename("active_users").reset_index()
            .join(sizes, on="cohort_week"))
    return g[["cohort_week", "cohort_size", "weeks_since_first", "active_users"]] \
        .sort_values(["cohort_week", "weeks_since_first"]).reset_index(drop=True)


def main() -> int:
    rng = np.random.default_rng(SEED)
    print(f"Simulating {N_USERS:,} users ...")
    log = simulate(rng)
    print(f"  {len(log):,} events generated")

    overview = (log.groupby("event_name")
                .agg(events=("user_pseudo_id", "size"),
                     users=("user_pseudo_id", "nunique"))
                .reset_index().sort_values("events", ascending=False))
    dates = pd.to_datetime(log.event_timestamp, unit="us").dt.date
    overview["first_date"] = dates.min()
    overview["last_date"] = dates.max()
    fio.save(overview, "01_event_overview")

    fio.save(funnel_by_timestamps(log, None), "02_funnel_overall")
    fio.save(funnel_by_sequence(log), "02b_funnel_validation")
    fio.save(funnel_by_timestamps(log, "device_category")
             .rename(columns={"device_category": "segment_value"}), "03_funnel_by_device")
    fio.save(fold_long_tail(funnel_by_timestamps(log, "source_medium")
             .rename(columns={"source_medium": "segment_value"})), "04_funnel_by_source")
    fio.save(funnel_by_timestamps(log, "visitor_type")
             .rename(columns={"visitor_type": "segment_value"}), "05_funnel_by_visitor_type")
    fio.save(cohort_retention(log), "06_cohort_retention")
    fio.save(funnel_by_sessions(log), "09_funnel_session_scoped")

    rev = (log[log.event_name == "purchase"]
           .groupby(["device_category", "source_medium"])
           .agg(purchases=("user_pseudo_id", "size"),
                purchasing_users=("user_pseudo_id", "nunique"),
                revenue_usd=("revenue_usd", "sum"))
           .reset_index().sort_values("revenue_usd", ascending=False))
    rev["revenue_usd"] = rev["revenue_usd"].round(2)
    fio.save(rev, "07_revenue_by_segment")

    fio.write_manifest(
        source=fio.SOURCE_FIXTURE,
        dataset="synthetic GA4-shaped event log (scripts/make_fixture.py)",
        window_start=str(WINDOW_START.date()),
        window_end=str(WINDOW_END.date()),
        note=f"seed={SEED}, n_users={N_USERS}. Not GA4 data. Not an analysis.",
    )
    print("Wrote data/processed/*.csv and _manifest.json (source=synthetic-fixture).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
