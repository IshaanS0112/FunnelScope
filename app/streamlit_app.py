"""FunnelScope dashboard.

Reads the committed CSVs in data/processed/ — no BigQuery connection, no credentials,
no network. Anyone who clones the repo can run it, which is the entire reason the
architecture exports to CSV instead of querying live.

    streamlit run app/streamlit_app.py

The dashboard supports the memo; it is not the deliverable. If a chart here does not
help someone act on docs/MEMO.md, it should not exist.
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

PALETTE = ["#4C6EF5", "#F59F00", "#12B886", "#E8590C", "#7048E8", "#1098AD"]


@st.cache_data
def load_all():
    manifest = fio.read_manifest()
    metrics_path = fio.PROCESSED_DIR / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
    data = {name: fio.load(name) for name in (
        "01_event_overview", "02_funnel_overall", "03_funnel_by_device",
        "04_funnel_by_source", "05_funnel_by_visitor_type",
        "06_cohort_retention", "07_revenue_by_segment")}
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
    df = pd.DataFrame({
        "Stage": [STAGE_LABELS[s] for s in FUNNEL_STAGES],
        "Users": [int(row[s]) for s in FUNNEL_STAGES],
    })
    df["% of viewers"] = df["Users"] / df["Users"].iloc[0]
    st.bar_chart(df.set_index("Stage")["Users"], color=PALETTE[0], horizontal=True)
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
    coh = retention.mark_censored(data["06_cohort_retention"], last_date)

    st.warning(
        "Cells whose observation window extends past the end of the data are "
        "**right-censored** and shown as blanks, not zeros. A cohort formed in the last "
        "weeks of the window physically cannot show week-8 retention. Reading those "
        "blanks as a retention decline is the most common error in this chart.",
        icon="📐")

    m = retention.matrix(coh)
    display = (m * 100).round(1)
    display.columns = [f"W{c}" for c in display.columns]
    st.dataframe(display.style.format("{:.1f}%", na_rep="—")
                 .background_gradient(cmap="Blues", axis=None),
                 use_container_width=True)

    st.subheader("Pooled retention curve (uncensored cells only)")
    curve = retention.average_curve(coh)
    st.line_chart(curve.set_index("weeks_since_first")["retention_rate"], color=PALETTE[2])

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
    st.code("recoverable = users_lost × improvement_pp × P(purchase | next stage) × AOV",
            language="text")
    st.error(
        "**Upper bound, not a forecast.** The model applies the purchase rate of users "
        "who completed a stage to users who did not. Recovered users almost certainly "
        "convert worse. These numbers rank stages against each other; they do not "
        "predict revenue.", icon="⚠️")

    opp = pd.DataFrame(metrics["opportunities"])
    opp["Step"] = opp.apply(
        lambda r: f"{STAGE_LABELS[r['from_stage']]} → {STAGE_LABELS[r['to_stage']]}", axis=1)
    st.dataframe(
        opp[["Step", "users_lost", "step_conversion", "downstream_conversion",
             "recoverable_revenue"]]
        .rename(columns={"users_lost": "Users lost", "step_conversion": "Step conversion",
                         "downstream_conversion": "P(purchase | next stage)",
                         "recoverable_revenue": "Recoverable at +5pp"})
        .style.format({"Users lost": "{:,.0f}", "Step conversion": "{:.1%}",
                       "P(purchase | next stage)": "{:.1%}",
                       "Recoverable at +5pp": "${:,.0f}"}),
        use_container_width=True, hide_index=True)

    st.subheader("Sensitivity to the improvement assumption")
    st.caption("The ranking holds across the sweep; only the absolute figures move. "
               "That is the defensible claim.")
    st.dataframe(pd.DataFrame(metrics["sensitivity"]), use_container_width=True,
                 hide_index=True)

    st.subheader("Is the segment gap real?")
    for t in metrics["significance_tests"]:
        (st.success if t["significant"] else st.info)(t["verdict"])

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
    st.sidebar.markdown("**The memo is the deliverable.** This dashboard supports it: "
                        "[`docs/MEMO.md`](https://github.com/IshaanS0112/FunnelScope/blob/main/docs/MEMO.md)")
    if not manifest.is_real:
        st.sidebar.error("Synthetic fixture data", icon="⚠️")

    provenance_banner(manifest)
    {"Funnel": page_funnel, "Retention": page_retention,
     "Acquisition": page_acquisition, "Opportunity": page_opportunity}[page](metrics, data)


main()
