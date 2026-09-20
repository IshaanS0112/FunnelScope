#!/usr/bin/env python3
"""Turn the exported CSVs into every number the memo and the dashboard quote.

Order of operations matters here. The correctness gates run FIRST and raise on
failure, so it is not possible to produce a metrics file — and therefore a memo —
from a funnel that failed validation.

    1. monotonicity check on every funnel table
    2. cross-validation of method A against method B
    3. user-scoped vs session-scoped funnel comparison
    4. rates, segment cuts, significance tests with Holm-Bonferroni correction
    5. opportunity sizing + sensitivity sweep + bootstrap intervals
    6. retention with censoring marked
    7. RICE ranking, reach measured from the data
    8. diff against the previous export, so a broken re-run is visible immediately
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


def _headline_scalars(m: dict) -> dict:
    """The handful of numbers whose movement between exports is worth reporting.

    Deliberately small. A diff over every field in metrics.json would be dominated by
    floating-point noise and by fields that move for uninteresting reasons; the point of
    the comparison is to catch a query that broke or a window that shifted.
    """
    out = {}
    for s in FUNNEL_STAGES:
        out[f"funnel.{s}"] = m.get("funnel", {}).get(s)
    out["funnel.end_to_end_conversion"] = m.get("funnel", {}).get("end_to_end_conversion")
    out["aov"] = m.get("aov")
    for o in m.get("opportunities", []):
        out[f"recoverable.{o['to_stage']}"] = o.get("recoverable_revenue")
    out["retention.censored_share"] = (
        m.get("retention", {}).get("censoring", {}).get("share_censored"))
    for c in m.get("retention", {}).get("curve", []):
        if c.get("weeks_since_first") in (1, 4):
            out[f"retention.w{c['weeks_since_first']}"] = c.get("retention_rate")
    return {k: v for k, v in out.items() if isinstance(v, (int, float))}


def reexport_diff(new: dict, previous: dict | None) -> list[dict]:
    """What moved since the last export, as a list of changed headline scalars.

    A pipeline that silently produces different numbers on a re-run is the failure mode
    this catches: a query edited by hand, a window quietly widened, a segment that
    vanished because a source stopped firing. Printing the movement makes a broken
    re-export obvious at the moment it happens rather than three artifacts later.
    """
    if not previous:
        return []
    before, after = _headline_scalars(previous), _headline_scalars(new)
    rows = []
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        if a is None or b is None:
            rows.append({"metric": key, "previous": a, "current": b,
                         "change_pct": None, "note": "appeared" if a is None else "disappeared"})
            continue
        if a == b:
            continue
        rows.append({"metric": key, "previous": a, "current": b,
                     "change_pct": ((b - a) / a * 100) if a else None, "note": ""})
    return rows


def main() -> int:
    manifest = fio.read_manifest()
    print(manifest.banner())
    print()

    previous_metrics = (json.loads(METRICS_PATH.read_text())
                        if METRICS_PATH.exists() else None)

    overall = fio.load("02_funnel_overall")
    validation = fio.load("02b_funnel_validation")
    by_device = fio.load("03_funnel_by_device")
    by_source = fio.load("04_funnel_by_source")
    by_visitor = fio.load("05_funnel_by_visitor_type")
    cohorts = fio.load("06_cohort_retention")
    revenue = fio.load("07_revenue_by_segment")
    # Optional: only present once sql/09 has been exported.
    try:
        sessions = fio.load("09_funnel_session_scoped")
    except FileNotFoundError:
        sessions = None

    # ---- 1. gates ---------------------------------------------------------------
    tables = [("overall", overall), ("device", by_device),
              ("source", by_source), ("visitor", by_visitor)]
    if sessions is not None:
        tables.append(("session-scoped", sessions))
    for name, df in tables:
        funnel.check_monotonic(df)
    print(f"PASS  funnel monotonicity, {len(tables)} segment tables")

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

    # ---- 2b. user-scoped vs session-scoped ---------------------------------------
    scope_gap = None
    if sessions is not None:
        scope_gap = funnel.session_gap(row, sessions.iloc[0])
        print(f"Scope comparison: {scope_gap['user_conversion'] * 100:.2f}% of viewing "
              f"USERS convert, {scope_gap['session_conversion'] * 100:.2f}% of viewing "
              f"SESSIONS do ({scope_gap['gap_pp']:.2f}pp apart). "
              f"{scope_gap['return_visit_dependence'] * 100:.0f}% of user-level "
              f"conversion depends on a return visit.\n")

    # ---- 3. opportunity sizing ---------------------------------------------------
    opportunities = sizing.size_all_stages(row, aov, improvement_pp=0.05)
    sensitivity = sizing.sensitivity_table(row, aov)
    intervals = sizing.bootstrap_recoverable(row, aov, improvement_pp=0.05)
    biggest = opportunities.iloc[0]
    equivalent = sizing.ranking_matches_step_conversion(row)
    print("Recoverable revenue at a 5pp lift on each step's conversion rate:")
    for _, o in opportunities.iterrows():
        print(f"  {STAGE_LABELS[o['to_stage']]:<18} lost {int(o['users_lost']):>7,} "
              f"users, recovers {o['users_recovered']:>8,.0f}  ->  "
              f"${o['recoverable_revenue']:>12,.0f}")
    for _, iv in intervals.iterrows():
        print(f"  {STAGE_LABELS[iv['to_stage']]:<18} 95% CI "
              f"[${iv['ci_low']:,.0f}, ${iv['ci_high']:,.0f}]  "
              f"(counts only — the model's assumptions are not in this interval)")
    print(f"  [ranking identical to worst-step-conversion ordering: {equivalent}] "
          f"-- expected, and proved in funnelscope/sizing.py. Sizing prices the stages; "
          f"it does not re-rank them. Effort does, in the RICE table below.")
    print()

    # ---- 4. significance ---------------------------------------------------------
    # Every comparison below belongs to ONE family, so the family-wise error rate is
    # what matters, not the per-test alpha. Holm-Bonferroni is applied across all of
    # them and the corrected verdict is the one that gets quoted anywhere.
    from funnelscope.stats import ProportionTest, correct_family
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

    corrected = correct_family(tests, alpha=0.05)
    for c in corrected:
        print(" ", c["verdict"])
    flipped = [c for c in corrected if c["significant_raw"] and not c["significant_holm"]]
    print(f"  [Holm-Bonferroni across {len(corrected)} comparisons: "
          f"{sum(c['significant_holm'] for c in corrected)} survive, "
          f"{len(flipped)} lost significance to the correction]")
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
    # Densify BEFORE censoring: the query emits no row for a week with no returners,
    # so without this a zero cell and an unobservable cell look identical.
    coh = retention.mark_censored(retention.densify(cohorts, last_date), last_date)
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
        "sizing_intervals": intervals.to_dict("records"),
        "biggest_opportunity": biggest.to_dict(),
        "significance_tests": corrected,
        "multiple_comparisons": {
            "method": "Holm-Bonferroni",
            "alpha": 0.05,
            "family_size": len(corrected),
            "n_significant_raw": sum(c["significant_raw"] for c in corrected),
            "n_significant_after_correction": sum(c["significant_holm"] for c in corrected),
            "changed_by_correction": [c["comparison"] for c in flipped],
        },
        "scope_comparison": scope_gap,
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

    # ---- 9. what moved since the last export -------------------------------------
    moved = reexport_diff(metrics, previous_metrics)
    metrics["reexport_diff"] = moved
    if previous_metrics is None:
        print("\nNo previous metrics.json to compare against — this is a first export.")
    elif not moved:
        print("\nRe-export diff: no headline metric changed.")
    else:
        print(f"\nRe-export diff — {len(moved)} headline metric(s) moved:")
        for d in moved:
            if d["change_pct"] is None:
                print(f"  {d['metric']:<38} {d['note']}  ({d['previous']} -> {d['current']})")
            else:
                print(f"  {d['metric']:<38} {d['previous']:>14,.4f} -> "
                      f"{d['current']:>14,.4f}  ({d['change_pct']:+.2f}%)")
        print("  A re-export that moves a number you did not expect to move is a broken "
              "query until proven otherwise.")

    METRICS_PATH.write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    print(f"\nWrote {METRICS_PATH.relative_to(REPO_ROOT)}")
    print("Next: python scripts/render_memo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
