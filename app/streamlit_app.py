"""FunnelScope dashboard.

Reads the committed CSVs in data/processed/ — no BigQuery connection, no credentials,
no network, so anyone who clones the repo can run it.

    streamlit run app/streamlit_app.py

The dashboard supports the memo; it is not the deliverable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from funnelscope import FUNNEL_STAGES, STAGE_LABELS, io as fio, retention  # noqa: E402

st.set_page_config(page_title="FunnelScope", page_icon="📉", layout="wide")

# Paper theme: accent for the series that carries the point, greys for context.
PALETTE = ["#1D3FD8", "#8C9097", "#C9C5B9"]
ACCENT, MUTED, FAINT = PALETTE


@st.cache_data
def load_all():
    manifest = fio.read_manifest()
    metrics_path = fio.PROCESSED_DIR / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
    data = {name: fio.load(name) for name in (
        "01_event_overview", "02_funnel_overall", "03_funnel_by_device",
        "04_funnel_by_source", "05_funnel_by_visitor_type",
        "06_cohort_retention", "07_revenue_by_segment")}
    try:  # only present once sql/09 has been exported
        data["09_funnel_session_scoped"] = fio.load("09_funnel_session_scoped")
    except FileNotFoundError:
        pass
    return manifest, metrics, data


def provenance_banner(manifest) -> None:
    if manifest.is_real:
        st.caption(manifest.banner())
    else:
        st.error(
            "**Synthetic fixture — not an analysis.** Every figure on this page comes "
            "from `scripts/make_fixture.py`, a simulated event log used to exercise the "
            "pipeline without GCP credentials. It describes nothing about Google's demo "
            "store. Run `python scripts/run_queries.py` to replace it with real GA4 data.",
            icon="⚠️")


def funnel_chart(row: pd.Series):
    """Horizontal bars in funnel order.

    Altair, not st.bar_chart: the latter sorts the index and renders the stages
    alphabetically, and a funnel whose bars are out of order is worse than no chart.
    """
    import altair as alt

    df = pd.DataFrame({
        "Stage": [STAGE_LABELS[s] for s in FUNNEL_STAGES],
        "Users": [int(row[s]) for s in FUNNEL_STAGES],
    })
    df["% of viewers"] = df["Users"] / df["Users"].iloc[0]
    df["Label"] = df.apply(
        lambda r: f"{r['Users']:,}  ({r['% of viewers']:.1%})", axis=1)

    order = [STAGE_LABELS[s] for s in FUNNEL_STAGES]
    base = alt.Chart(df).encode(
        y=alt.Y("Stage:N", sort=order, title=None),
        x=alt.X("Users:Q", title=None, axis=alt.Axis(format="~s")),
    )
    chart = (base.mark_bar(color=FAINT, cornerRadius=2)
             + base.mark_text(align="left", dx=5, fontSize=11).encode(text="Label:N"))
    st.altair_chart(chart.properties(height=36 * len(df)), use_container_width=True)
    return df


def page_funnel(metrics, data):
    st.header("Funnel")
    st.write("Ordered funnel: each stage must occur **after** the previous one. "
             "An unordered funnel counts a user who bought and then browsed more items "
             "as a completed journey, and inflates conversion for free.")

    segment_choice = st.selectbox(
        "Segment by", ["All users", "Device", "Acquisition channel", "New vs returning"])
    table = {
        "All users": data["02_funnel_overall"],
        "Device": data["03_funnel_by_device"],
        "Acquisition channel": data["04_funnel_by_source"],
        "New vs returning": data["05_funnel_by_visitor_type"],
    }[segment_choice]

    if segment_choice != "All users":
        values = table["segment_value"].tolist()
        chosen = st.multiselect("Show", values, default=values[:4])
        table = table[table["segment_value"].isin(chosen)]

    cols = st.columns(max(len(table), 1))
    for col, (_, row) in zip(cols, table.iterrows()):
        with col:
            st.subheader(str(row["segment_value"]))
            conv = row["purchased"] / row["viewed"] if row["viewed"] else 0
            st.metric("End-to-end conversion", f"{conv * 100:.2f}%",
                      help="Purchased ÷ viewed an item")
            funnel_chart(row)

    st.divider()
    st.subheader("Step conversion")
    rows = []
    for _, r in table.iterrows():
        for i in range(1, len(FUNNEL_STAGES)):
            prev, curr = FUNNEL_STAGES[i - 1], FUNNEL_STAGES[i]
            rows.append({
                "Segment": r["segment_value"],
                "Step": f"{STAGE_LABELS[prev]} → {STAGE_LABELS[curr]}",
                "Conversion": (r[curr] / r[prev]) if r[prev] else 0,
                "Users lost": int(r[prev] - r[curr]),
            })
    steps = pd.DataFrame(rows)
    st.dataframe(
        steps.style.format({"Conversion": "{:.1%}", "Users lost": "{:,}"}),
        use_container_width=True, hide_index=True)

    scope = (metrics or {}).get("scope_comparison")
    if scope:
        st.divider()
        st.subheader("User-scoped vs session-scoped")
        c1, c2, c3 = st.columns(3)
        c1.metric("User-scoped conversion", f"{scope['user_conversion'] * 100:.2f}%",
                  help="Does this user ever get there — the right frame for product fixes")
        c2.metric("Session-scoped conversion", f"{scope['session_conversion'] * 100:.2f}%",
                  help="Does this visit complete — the right frame for a landing experience")
        c3.metric("Runs on return visits", f"{scope['return_visit_dependence'] * 100:.0f}%",
                  help="Share of user-level conversion that needed a second session")
        st.caption(
            "Same cumulative funnel, different partition key. Session-scoped conversion "
            "is necessarily no higher — a user converts if *any* of their sessions does — "
            "so the gap measures how much of this funnel depends on people coming back. "
            "A single-session optimisation would be attacking the wrong surface for that "
            "share of it.")

    if metrics and metrics["validation"]["cross_validation"]:
        with st.expander("Correctness gate — two independent funnel implementations"):
            st.write("The funnel is computed twice: once from per-user first-occurrence "
                     "timestamps, once by collapsing each user's events into an ordered "
                     "string and matching a sequence regex. The two share no logic. "
                     "The pipeline refuses to publish if they diverge by more than 0.5%.")
            xv = pd.DataFrame(metrics["validation"]["cross_validation"])
            st.dataframe(xv.style.format({"rel_diff": "{:.4%}"}),
                         use_container_width=True, hide_index=True)


def page_retention(metrics, data):
    st.header("Retention")
    last_date = pd.to_datetime(data["01_event_overview"]["last_date"]).max()
    coh = retention.mark_censored(
        retention.densify(data["06_cohort_retention"], last_date), last_date)

    st.warning(
        "Cells whose observation window extends past the end of the data are "
        "**right-censored** and shown as blanks, not zeros. A cohort formed in the last "
        "weeks of the window physically cannot show week-8 retention. Reading those "
        "blanks as a retention decline is the most common error in this chart.",
        icon="📐")

    m = retention.matrix(coh)
    display = (m * 100).round(1)
    display.columns = [f"W{c}" for c in display.columns]

    # Censored cells must read as a visible BLANK. st.dataframe renders its own grid
    # rather than the Styler's HTML, printing "None" on a solid black background — which
    # reads as a catastrophic zero, the misreading this page exists to prevent.
    # Rendering the Styler's HTML sidesteps it; the heatmap needs no sorting anyway.
    observable = display.drop(columns=["W0"], errors="ignore")
    vmax = float(observable.max().max()) if not observable.empty else 100.0

    def cell(value):
        if pd.isna(value):
            return ("background: repeating-linear-gradient(45deg, transparent, "
                    "transparent 4px, rgba(130,130,130,.30) 4px, "
                    "rgba(130,130,130,.30) 5px);")
        weight = min((value / vmax) ** 0.55, 1.0) if vmax else 0.0
        colour = "color:#fff;font-weight:600;" if weight > 0.62 else ""
        return f"background-color: rgba(29,63,216,{weight * 0.8:.3f});{colour}"

    styled = (display.style
              .format("{:.1f}%", na_rep="")
              .map(cell)
              .set_table_styles([
                  {"selector": "", "props": [("border-collapse", "collapse"),
                                             ("font-size", "13px"),
                                             ("width", "100%")]},
                  {"selector": "th", "props": [("font-size", "12px"),
                                               ("font-weight", "600"),
                                               ("padding", "6px 8px"),
                                               ("text-align", "center")]},
                  {"selector": "td", "props": [("padding", "6px 8px"),
                                               ("text-align", "center"),
                                               ("border", "1px solid rgba(128,128,128,.12)")]},
                  {"selector": "th.row_heading", "props": [("text-align", "left"),
                                                           ("font-family", "monospace"),
                                                           ("white-space", "nowrap")]},
              ]))
    st.markdown(styled.to_html(), unsafe_allow_html=True)
    st.caption("Hatched cells are right-censored — the observation window extends past "
               "the end of the data, so the number does not exist yet. They are not "
               "zeros, and they are excluded from every figure on this page.")

    st.subheader("Pooled retention curve (uncensored cells only)")
    curve = retention.average_curve(coh)
    # Week 0 is 100% by definition; plotted, it owns the y-axis and squashes the rest.
    plotted = curve[curve.weeks_since_first > 0]
    st.line_chart(plotted.set_index("weeks_since_first")["retention_rate"],
                  color=ACCENT, y_label="Retention", x_label="Weeks since first seen")
    st.caption("Week 0 is 100% for every cohort by construction and is omitted — plotted, "
               "it owns the axis and flattens every week that carries information.")

    summary = retention.censoring_summary(coh)
    st.caption(f"{summary['cells_censored']} of {summary['cells_total']} cells "
               f"({summary['share_censored']:.0%}) are censored and excluded above. "
               f"Pooled as Σactive ÷ Σcohort_size, so a small cohort cannot swing the curve.")


def page_acquisition(metrics, data):
    st.header("Acquisition")
    st.write("High volume with low conversion is a landing-page or expectation-mismatch "
             "problem. Low volume with high conversion is a scale opportunity. "
             "They need opposite responses, so this page keeps volume and rate side by side.")

    src = data["04_funnel_by_source"].copy()
    src["conversion"] = src["purchased"] / src["viewed"]
    src["cart_rate"] = src["added_to_cart"] / src["viewed"]

    rev = data["07_revenue_by_segment"].groupby("source_medium").agg(
        purchases=("purchases", "sum"), revenue_usd=("revenue_usd", "sum")).reset_index()
    merged = src.merge(rev, left_on="segment_value", right_on="source_medium", how="left")
    merged["revenue_per_viewer"] = merged["revenue_usd"] / merged["viewed"]

    st.dataframe(
        merged[["segment_value", "viewed", "cart_rate", "conversion",
                "revenue_usd", "revenue_per_viewer"]]
        .rename(columns={"segment_value": "Channel", "viewed": "Viewers",
                         "cart_rate": "Cart rate", "conversion": "Conversion",
                         "revenue_usd": "Revenue", "revenue_per_viewer": "Revenue / viewer"})
        .style.format({"Viewers": "{:,}", "Cart rate": "{:.2%}", "Conversion": "{:.2%}",
                       "Revenue": "${:,.0f}", "Revenue / viewer": "${:,.2f}"}),
        use_container_width=True, hide_index=True)

    st.subheader("Volume vs conversion")
    st.scatter_chart(merged, x="viewed", y="conversion", size="revenue_usd",
                     color="segment_value")


def page_opportunity(metrics, data):
    st.header("Opportunity")
    if not metrics:
        st.info("Run `python scripts/analyze.py` to generate metrics.json.")
        return

    st.subheader("Sizing model")
    st.code("users_recovered = min(users_entering × improvement_pp, users_lost)\n"
            "recoverable     = users_recovered × P(purchase | next stage) × AOV",
            language="text")
    st.caption("The percentage-point lift applies to users **entering** the stage, "
               "because that is the denominator of the conversion rate it changes. "
               "The common `users_lost × pp` form is only `(1 − rate)` of this figure — "
               "30% short at a 30% step, half at a 50% step.")
    st.error(
        "**Upper bound, not a forecast.** The model applies the purchase rate of users "
        "who completed a stage to users who did not. Recovered users almost certainly "
        "convert worse. These numbers rank stages against each other; they do not "
        "predict revenue.", icon="⚠️")

    opp = pd.DataFrame(metrics["opportunities"])
    opp["Step"] = opp.apply(
        lambda r: f"{STAGE_LABELS[r['from_stage']]} → {STAGE_LABELS[r['to_stage']]}", axis=1)
    intervals = {iv["to_stage"]: iv for iv in metrics.get("sizing_intervals", [])}
    opp["95% CI"] = opp["to_stage"].map(
        lambda s: (f"${intervals[s]['ci_low']:,.0f} – ${intervals[s]['ci_high']:,.0f}"
                   if s in intervals else "—"))
    st.dataframe(
        opp[["Step", "users_lost", "step_conversion", "downstream_conversion",
             "recoverable_revenue", "95% CI"]]
        .rename(columns={"users_lost": "Users lost", "step_conversion": "Step conversion",
                         "downstream_conversion": "P(purchase | next stage)",
                         "recoverable_revenue": "Recoverable at +5pp"})
        .style.format({"Users lost": "{:,.0f}", "Step conversion": "{:.1%}",
                       "P(purchase | next stage)": "{:.1%}",
                       "Recoverable at +5pp": "${:,.0f}"}),
        use_container_width=True, hide_index=True)
    if intervals:
        st.caption(
            "The intervals price sampling variation in the funnel counts only. They do "
            "not price the improvement assumption, and they do not price the model's "
            "load-bearing assumption that recovered users purchase like unaided "
            "completers — which dominates the error and is not random. A tight interval "
            "means the counts are large, not that the number is right.")

    st.info(
        "**Sizing prices the stages; it does not re-rank them.** In a strictly ordered "
        "funnel every purchaser passed every stage, so `P(purchase | stage j) = "
        "purchases ÷ count_j` and recoverable revenue collapses to a monotone function "
        "of step conversion. Ranking by dollars and by worst drop-off are the same "
        "ordering, necessarily — treating them as two findings double-counts one fact. "
        "Effort is what re-ranks the work, which is the RICE table below.",
        icon="📐")

    st.subheader("Sensitivity to the improvement assumption")
    st.caption("The ranking holds across the sweep; only the absolute figures move. "
               "That is the defensible claim, which is why the sweep is published "
               "instead of a single number.")
    sens = pd.DataFrame(metrics["sensitivity"])
    # Column keys are raw fractions ("0.01"); label them as percentage points.
    pp_cols = [c for c in sens.columns if c != "to_stage"]
    pp_cols.sort(key=float)
    sens = sens.set_index("to_stage").loc[
        [o["to_stage"] for o in metrics["opportunities"]], pp_cols].reset_index()
    sens["to_stage"] = sens["to_stage"].map(lambda s: STAGE_LABELS.get(s, s))
    sens.columns = ["Stage"] + [f"+{float(c) * 100:.0f}pp" for c in pp_cols]
    st.dataframe(
        sens.style.format({c: "${:,.0f}" for c in sens.columns if c != "Stage"}),
        use_container_width=True, hide_index=True)

    st.subheader("Is the segment gap real?")
    mc = metrics.get("multiple_comparisons")
    if mc:
        st.caption(
            f"{mc['n_significant_after_correction']} of {mc['family_size']} comparisons "
            f"survive {mc['method']} correction. Running several segment comparisons at "
            f"α = {mc['alpha']} each does not hold the family-wise error rate at "
            f"{mc['alpha']} — with four comparisons it is 18.5%. The corrected verdict "
            f"is the one quoted."
            + (f" The correction changed the conclusion for: "
               f"{'; '.join(mc['changed_by_correction'])}."
               if mc.get("changed_by_correction") else ""))
    for test in metrics["significance_tests"]:
        (st.success if test["significant"] else st.info)(test["verdict"])

    st.subheader("RICE-ranked recommendations")
    rice_df = pd.DataFrame(metrics["rice"])
    st.dataframe(
        rice_df[["rank", "name", "reach", "impact", "confidence", "effort", "rice_score"]]
        .rename(columns={"rank": "#", "name": "Recommendation", "reach": "Reach",
                         "impact": "Impact", "confidence": "Confidence",
                         "effort": "Effort (wk)", "rice_score": "RICE"})
        .style.format({"Reach": "{:,.0f}", "RICE": "{:,.0f}"}),
        use_container_width=True, hide_index=True)
    for _, r in rice_df.iterrows():
        with st.expander(f"{int(r['rank'])}. {r['name']}"):
            st.write(f"**Rationale.** {r['rationale']}")
            st.write(f"**Evidence.** {r['evidence']}")
            st.write(f"**Assumption to challenge.** {r['assumptions']}")


def main():
    try:
        manifest, metrics, data = load_all()
    except FileNotFoundError as exc:
        st.title("FunnelScope")
        st.error(str(exc))
        st.stop()

    st.sidebar.title("FunnelScope")
    st.sidebar.caption("GA4 event data · BigQuery · funnel, retention and opportunity sizing")
    page = st.sidebar.radio("Page", ["Funnel", "Retention", "Acquisition", "Opportunity"])
    st.sidebar.divider()
    st.sidebar.markdown(
        "**The memo is the deliverable.** This dashboard supports it: "
        "[`docs/MEMO.md`](https://github.com/IshaanS0112/FunnelScope/blob/main/docs/MEMO.md)")
    st.sidebar.caption(
        "There is also a dependency-free static version of this dashboard in `web/`, "
        "which opens by double-click and needs no Python. Build it with "
        "`python scripts/build_web.py`.")
    if not manifest.is_real:
        st.sidebar.error("Synthetic fixture data", icon="⚠️")

    provenance_banner(manifest)
    {"Funnel": page_funnel, "Retention": page_retention,
     "Acquisition": page_acquisition, "Opportunity": page_opportunity}[page](metrics, data)


main()
