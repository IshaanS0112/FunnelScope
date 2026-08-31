#!/usr/bin/env python3
"""Turn the exported CSVs into every number the memo and the dashboard quote.

Order of operations matters here. The correctness gates run FIRST and raise on
failure, so it is not possible to produce a metrics file — and therefore a memo —
from a funnel that failed validation.

    1. monotonicity check on every funnel table
    2. cross-validation of method A against method B
    3. rates, segment cuts, significance tests
    4. opportunity sizing + sensitivity sweep
    5. retention with censoring marked
    6. RICE ranking, reach measured from the data
    -> data/processed/metrics.json

Usage:  python scripts/analyze.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from funnelscope import FUNNEL_STAGES, STAGE_LABELS, funnel, io as fio, retention, rice, sizing  # noqa: E402

METRICS_PATH = fio.PROCESSED_DIR / "metrics.json"

# Candidate interventions. Reach is measured from the data at scoring time; impact,
# effort and confidence are judgement, stated here so a reader can disagree with a
# specific number rather than with the ranking as a whole.
INTERVENTION_CATALOG = {
    "added_to_cart": dict(
        name="Rework the product page add-to-cart path on the weakest device",
        impact=rice.IMPACT_SCALE["high"], confidence=0.7, effort=3.0,
        rationale="Largest absolute loss sits between viewing an item and adding one. "
                  "The device split says this is a layout and interaction problem, not "
                  "an intent problem.",
        assumptions="Assumes the gap is friction rather than a difference in visit "
                    "intent by device. Untested — an A/B test on the mobile PDP settles it.",
    ),
    "began_checkout": dict(
        name="Reduce cart-to-checkout friction (persistent cart, single-tap checkout entry)",
        impact=rice.IMPACT_SCALE["high"], confidence=0.6, effort=4.0,
        rationale="Users who add to cart have declared intent. Losing them before "
                  "checkout even starts is the most recoverable kind of loss.",
        assumptions="Assumes abandonment is friction-driven. Price shock at the cart "
                    "step would produce the same signature and needs a different fix.",
    ),
    "purchased": dict(
        name="Shorten the checkout form and surface total cost earlier",
        impact=rice.IMPACT_SCALE["medium"], confidence=0.55, effort=5.0,
        rationale="Checkout-stage loss is the classic form-length and unexpected-cost "
                  "problem, but it is also the stage with the fewest users left.",
        assumptions="Assumes shipping cost and form length dominate. No field-level "
                    "abandonment data exists in this dataset to confirm it.",
    ),
    "channel": dict(
        name="Rebalance paid spend away from the worst-converting channel",
        impact=rice.IMPACT_SCALE["medium"], confidence=0.75, effort=1.5,
        rationale="A channel with high volume and low conversion is a targeting or "
                  "expectation-mismatch problem and is cheap to act on — it is a "
                  "budget decision, not an engineering project.",
        assumptions="Assumes conversion, not lifetime value, is the right objective for "
                    "that channel. A brand-awareness channel would be misjudged by this.",
    ),
}


def _row(df: pd.DataFrame, value: str) -> pd.Series:
    return df[df["segment_value"] == value].iloc[0]


def main() -> int:
    manifest = fio.read_manifest()
    print(manifest.banner())
    print()

    overall = fio.load("02_funnel_overall")
    validation = fio.load("02b_funnel_validation")
    by_device = fio.load("03_funnel_by_device")
    by_source = fio.load("04_funnel_by_source")
    by_visitor = fio.load("05_funnel_by_visitor_type")
    cohorts = fio.load("06_cohort_retention")
    revenue = fio.load("07_revenue_by_segment")

    # ---- 1. gates ---------------------------------------------------------------
    for name, df in (("overall", overall), ("device", by_device),
                     ("source", by_source), ("visitor", by_visitor)):
        funnel.check_monotonic(df)
    print("PASS  funnel monotonicity, all segment tables")

    xval = funnel.cross_validate(overall, validation)
    print("PASS  cross-validation, timestamp method vs sequence method")
    print(xval.to_string(index=False))
    print()

    # ---- 2. headline funnel ------------------------------------------------------
    row = overall.iloc[0]
    rates = funnel.with_rates(overall).iloc[0]
    worst = funnel.worst_step(row)
    aov = sizing.aov_from_revenue(revenue)

    print(f"Funnel: " + "  ->  ".join(
        f"{STAGE_LABELS[s]} {int(row[s]):,}" for s in FUNNEL_STAGES))
    print(f"End-to-end conversion: {row['purchased'] / row['viewed'] * 100:.2f}%")
    print(f"Steepest step drop-off: {STAGE_LABELS[worst.from_stage]} -> "
          f"{STAGE_LABELS[worst.to_stage]} ({worst.drop_off * 100:.1f}% lost)")
    print(f"AOV (transaction-weighted): ${aov:,.2f}\n")

    # ---- 3. opportunity sizing ---------------------------------------------------
    opportunities = sizing.size_all_stages(row, aov, improvement_pp=0.05)
    sensitivity = sizing.sensitivity_table(row, aov)
    biggest = opportunities.iloc[0]
    equivalent = sizing.ranking_matches_step_conversion(row)
    print("Recoverable revenue at a 5pp lift on each step's conversion rate:")
    for _, o in opportunities.iterrows():
        print(f"  {STAGE_LABELS[o['to_stage']]:<18} lost {int(o['users_lost']):>7,} "
              f"users, recovers {o['users_recovered']:>8,.0f}  ->  "
              f"${o['recoverable_revenue']:>12,.0f}")
    print(f"  [ranking identical to worst-step-conversion ordering: {equivalent}] "
          f"-- expected, and proved in funnelscope/sizing.py. Sizing prices the stages; "
          f"it does not re-rank them. Effort does, in the RICE table below.")
    print()

    # ---- 4. significance ---------------------------------------------------------
    from funnelscope.stats import ProportionTest
    tests = []

    dev = by_device.sort_values("viewed", ascending=False)
    if len(dev) >= 2:
        a, b = dev.iloc[0], dev.iloc[1]
        tests.append(ProportionTest(str(a["segment_value"]), str(b["segment_value"]),
                                    int(a["purchased"]), int(a["viewed"]),
                                    int(b["purchased"]), int(b["viewed"])))
    vis = by_visitor.sort_values("viewed", ascending=False)
    if len(vis) >= 2:
        a, b = vis.iloc[0], vis.iloc[1]
        tests.append(ProportionTest(str(a["segment_value"]), str(b["segment_value"]),
                                    int(a["purchased"]), int(a["viewed"]),
                                    int(b["purchased"]), int(b["viewed"])))

    src = by_source[by_source["segment_value"] != "(long tail)"].copy()
    src["conv"] = src["purchased"] / src["viewed"]
    src = src.sort_values("viewed", ascending=False)
    if len(src) >= 2:
        best = src.sort_values("conv", ascending=False).iloc[0]
        worst_ch = src.sort_values("conv").iloc[0]
        tests.append(ProportionTest(str(best["segment_value"]), str(worst_ch["segment_value"]),
                                    int(best["purchased"]), int(best["viewed"]),
                                    int(worst_ch["purchased"]), int(worst_ch["viewed"])))

    for t in tests:
        print(" ", t.verdict())
    print()

    # ---- 5. segment gap value ----------------------------------------------------
    gap = None
    if len(dev) >= 2:
        lo, hi = dev.iloc[0], dev.iloc[1]
        if (lo["purchased"] / lo["viewed"]) > (hi["purchased"] / hi["viewed"]):
            lo, hi = hi, lo
        gap = sizing.segment_gap_value(lo, hi, aov)
        print(f"Closing the {gap['segment_a']} -> {gap['segment_b']} conversion gap "
              f"({gap['gap_pp']:.2f}pp) would be worth ${gap['value_if_closed']:,.0f} "
              f"in this window (upper bound).\n")

    # ---- 6. retention ------------------------------------------------------------
    last_date = pd.to_datetime(fio.load("01_event_overview")["last_date"]).max()
    coh = retention.mark_censored(cohorts, last_date)
    curve = retention.average_curve(coh)
    censoring = retention.censoring_summary(coh)
    w1 = curve[curve.weeks_since_first == 1]
    w4 = curve[curve.weeks_since_first == 4]
    print(f"Retention (uncensored cells only): "
          f"W1 {float(w1.retention_rate.iloc[0]) * 100:.1f}%" if len(w1) else "Retention: n/a",
          end="")
    print(f", W4 {float(w4.retention_rate.iloc[0]) * 100:.1f}%" if len(w4) else "")
    print(f"{censoring['share_censored'] * 100:.0f}% of the cohort grid is right-censored "
          f"and excluded from every retention figure above.\n")

    # ---- 7. RICE -----------------------------------------------------------------
    recs = []
    for _, o in opportunities.iterrows():
        spec = INTERVENTION_CATALOG.get(o["to_stage"])
        if not spec:
            continue
        recs.append(rice.Recommendation(
            name=spec["name"], rationale=spec["rationale"],
            reach=float(o["users_lost"]), impact=spec["impact"],
            confidence=spec["confidence"], effort=spec["effort"],
            evidence=(f"{int(o['users_lost']):,} users lost at this step; "
                      f"${o['recoverable_revenue']:,.0f} recoverable at +5pp "
                      f"(upper bound)."),
            assumptions=spec["assumptions"],
        ))
    if len(src) >= 2:
        worst_ch = src.sort_values("conv").iloc[0]
        spec = INTERVENTION_CATALOG["channel"]
        recs.append(rice.Recommendation(
            name=f"{spec['name']}: {worst_ch['segment_value']}",
            rationale=spec["rationale"], reach=float(worst_ch["viewed"]),
            impact=spec["impact"], confidence=spec["confidence"], effort=spec["effort"],
            evidence=(f"{int(worst_ch['viewed']):,} users from "
                      f"{worst_ch['segment_value']} converting at "
                      f"{worst_ch['conv'] * 100:.2f}% vs "
                      f"{row['purchased'] / row['viewed'] * 100:.2f}% overall."),
            assumptions=spec["assumptions"],
        ))
    ranked = rice.rank(recs)
    print("RICE ranking:")
    for _, r in ranked.iterrows():
        print(f"  {int(r['rank'])}. {r['name']}  (RICE {r['rice_score']:,.0f})")

    # ---- 8. persist --------------------------------------------------------------
    metrics = {
        "provenance": {
            "source": manifest.source, "is_real": manifest.is_real,
            "banner": manifest.banner(), "dataset": manifest.dataset,
            "window_start": manifest.window_start, "window_end": manifest.window_end,
            "generated_at": manifest.generated_at,
        },
        "validation": {
            "monotonic": True,
            "cross_validation": xval.to_dict("records"),
        },
        "funnel": {s: int(row[s]) for s in FUNNEL_STAGES}
        | {
            "end_to_end_conversion": float(row["purchased"] / row["viewed"]),
            "step_conversion": {
                s: float(rates[f"step_conv_{s}"]) for s in FUNNEL_STAGES[1:]
            },
            "worst_step": {
                "from": worst.from_stage, "to": worst.to_stage,
                "step_conversion": worst.step_conversion, "lost": worst.lost,
            },
        },
        "aov": aov,
        "opportunities": opportunities.to_dict("records"),
        "sizing_ranking_equals_step_conversion": bool(equivalent),
        "sensitivity": sensitivity.to_dict("records"),
        "biggest_opportunity": biggest.to_dict(),
        "significance_tests": [t.to_dict() for t in tests],
        "segment_gap": gap,
        "segments": {
            "device": by_device.to_dict("records"),
            "source": by_source.to_dict("records"),
            "visitor_type": by_visitor.to_dict("records"),
        },
        "retention": {
            "curve": curve.to_dict("records"),
            "censoring": censoring,
        },
        "rice": ranked.to_dict("records"),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    print(f"\nWrote {METRICS_PATH.relative_to(REPO_ROOT)}")
    print("Next: python scripts/render_memo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
