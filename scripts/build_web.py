#!/usr/bin/env python3
"""Build the static site's data bundle: metrics.json + CSVs -> web/data.js.

Written as a .js assignment rather than .json because browsers block fetch() against
file:// — a site that fetched its data would work when served and break when opened by
double-click. A classic <script src> has no such restriction.

No maths happens here. Every number is read from metrics.json or computed by importing
funnelscope/, exactly like the memo and the dashboard.

Usage:  python scripts/build_web.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from funnelscope import FUNNEL_STAGES, STAGE_LABELS, io as fio, retention  # noqa: E402

WEB_DIR = REPO_ROOT / "web"
DATA_JS = WEB_DIR / "data.js"


def funnel_rows(df: pd.DataFrame) -> list[dict]:
    """One row per segment, with display rates already attached."""
    out = []
    for _, r in df.iterrows():
        viewed = float(r["viewed"])
        row = {
            "segment": str(r["segment_value"]),
            "counts": {s: int(r[s]) for s in FUNNEL_STAGES},
            "conversion": (float(r["purchased"]) / viewed) if viewed else 0.0,
            "steps": [],
        }
        for i in range(1, len(FUNNEL_STAGES)):
            prev, curr = FUNNEL_STAGES[i - 1], FUNNEL_STAGES[i]
            entered, completed = float(r[prev]), float(r[curr])
            row["steps"].append({
                "from": prev,
                "to": curr,
                "label": f"{STAGE_LABELS[prev]} → {STAGE_LABELS[curr]}",
                "entered": int(entered),
                "completed": int(completed),
                "lost": int(entered - completed),
                "step_conversion": (completed / entered) if entered else 0.0,
            })
        out.append(row)
    return out


def retention_block(cohorts: pd.DataFrame, overview: pd.DataFrame) -> dict:
    """The cohort grid, censored cells as nulls so the site renders them blank.

    Densified first — see funnelscope/retention.py.
    """
    last_date = pd.to_datetime(overview["last_date"]).max()
    dense = retention.mark_censored(retention.densify(cohorts, last_date), last_date)
    grid = retention.matrix(dense)
    curve = retention.average_curve(dense)

    cells = []
    for cohort, row in grid.iterrows():
        values = [None if pd.isna(v) else float(v) for v in row.tolist()]
        size = int(dense[dense["cohort_week"] == pd.Timestamp(cohort)]["cohort_size"].max())
        cells.append({"cohort": str(cohort), "cohort_size": size, "values": values})

    return {
        "weeks": [int(c) for c in grid.columns],
        "cohorts": cells,
        "curve": [{"week": int(r["weeks_since_first"]),
                   "rate": float(r["retention_rate"]),
                   "cohort_size": int(r["cohort_size"]),
                   "cohorts_observed": int(r["cohorts_observed"])}
                  for _, r in curve.iterrows()],
        "censoring": retention.censoring_summary(dense),
        "last_date": str(pd.Timestamp(last_date).date()),
    }


def acquisition_block(by_source: pd.DataFrame, revenue: pd.DataFrame) -> list[dict]:
    """Volume and rate together — the whole point of the Acquisition page.

    A ranked table hides the difference between "high traffic, low conversion" (spend
    less) and "low traffic, high conversion" (spend more).
    """
    rev = (revenue.groupby("source_medium")
           .agg(purchases=("purchases", "sum"), revenue_usd=("revenue_usd", "sum"))
           .reset_index())
    merged = by_source.merge(rev, left_on="segment_value",
                             right_on="source_medium", how="left")
    out = []
    for _, r in merged.iterrows():
        viewed = float(r["viewed"])
        revenue_usd = float(r["revenue_usd"]) if pd.notna(r.get("revenue_usd")) else 0.0
        out.append({
            "channel": str(r["segment_value"]),
            "viewed": int(viewed),
            "cart_rate": float(r["added_to_cart"]) / viewed if viewed else 0.0,
            "conversion": float(r["purchased"]) / viewed if viewed else 0.0,
            "purchased": int(r["purchased"]),
            "revenue_usd": revenue_usd,
            "revenue_per_viewer": revenue_usd / viewed if viewed else 0.0,
            "is_long_tail": str(r["segment_value"]) == "(long tail)",
        })
    return sorted(out, key=lambda d: -d["viewed"])


def main() -> int:
    metrics_path = fio.PROCESSED_DIR / "metrics.json"
    if not metrics_path.exists():
        print("No metrics.json. Run `python scripts/analyze.py` first.", file=sys.stderr)
        return 1
    m = json.loads(metrics_path.read_text(encoding="utf-8"))

    overall = fio.load("02_funnel_overall")
    by_device = fio.load("03_funnel_by_device")
    by_source = fio.load("04_funnel_by_source")
    by_visitor = fio.load("05_funnel_by_visitor_type")
    cohorts = fio.load("06_cohort_retention")
    revenue = fio.load("07_revenue_by_segment")
    overview = fio.load("01_event_overview")

    bundle = {
        "provenance": m["provenance"],
        "stage_labels": STAGE_LABELS,
        "stages": list(FUNNEL_STAGES),
        "overview": {
            "events_total": int(overview["events"].sum()),
            "by_event": [{"event": str(r["event_name"]), "events": int(r["events"]),
                          "users": int(r["users"])}
                         for _, r in overview.sort_values("events", ascending=False).iterrows()],
            "first_date": str(overview["first_date"].min()),
            "last_date": str(overview["last_date"].max()),
        },
        "funnel": {
            "overall": funnel_rows(overall),
            "device": funnel_rows(by_device),
            "source": funnel_rows(by_source),
            "visitor": funnel_rows(by_visitor),
        },
        "validation": m["validation"],
        "scope_comparison": m.get("scope_comparison"),
        "aov": m["aov"],
        "opportunities": m["opportunities"],
        "sizing_intervals": m.get("sizing_intervals", []),
        "sensitivity": m["sensitivity"],
        "sizing_ranking_equals_step_conversion": m.get(
            "sizing_ranking_equals_step_conversion"),
        "significance_tests": m["significance_tests"],
        "multiple_comparisons": m.get("multiple_comparisons"),
        "segment_gap": m.get("segment_gap"),
        "segment_gaps_all": m.get("segment_gaps_all", []),
        "retention": retention_block(cohorts, overview),
        "acquisition": acquisition_block(by_source, revenue),
        "rice": m["rice"],
        "experiment": m.get("experiment"),
        "reexport_diff": m.get("reexport_diff", []),
    }

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, indent=1, default=str, ensure_ascii=False)
    DATA_JS.write_text(
        "// Generated by scripts/build_web.py — do not edit by hand.\n"
        "// Every number here comes from data/processed/metrics.json, which is itself\n"
        "// produced only after the funnel correctness gates have passed.\n"
        f"window.FUNNELSCOPE_DATA = {payload};\n"
    , encoding="utf-8")

    size_kb = DATA_JS.stat().st_size / 1024
    print(f"Wrote {DATA_JS.relative_to(REPO_ROOT)}  ({size_kb:,.0f} KB)")
    if not m["provenance"]["is_real"]:
        print("Provenance: SYNTHETIC FIXTURE — the site will render its warning banner.")
    print("Open web/index.html, or serve the web/ directory from GitHub Pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
