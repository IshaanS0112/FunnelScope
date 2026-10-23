<p align="center">
  <img src="docs/screenshots/hero.png" alt="FunnelScope report: four in five shoppers leave before they add to cart" width="100%">
</p>

# FunnelScope

**Where shoppers leave a GA4 ecommerce funnel, what it is worth, and what to fix first.**
A product-analytics case study on 4.3 million raw GA4 events, delivered as a decision memo
rather than a dashboard.

[![Live report](https://img.shields.io/badge/live_report-open-1D3FD8)](https://ishaans0112.github.io/FunnelScope/)
[![CI](https://github.com/Ishaana0112/FunnelScope/actions/workflows/ci.yml/badge.svg)](https://github.com/Ishaana0112/FunnelScope/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-175_passing-0F8A5F)
![Python](https://img.shields.io/badge/Python-3.12-15171A)
![License](https://img.shields.io/badge/license-MIT-5B5F66)

**[Read the memo →](docs/MEMO.md)** · [Live report](https://ishaans0112.github.io/FunnelScope/) · [Methodology](docs/methodology.md) · [Interview defence](docs/INTERVIEW.md)

---

## Results snapshot

| | |
|---|---|
| **Data** | 4,295,584 GA4 events · Google Merchandise Store · 1 Nov 2020 – 31 Jan 2021 |
| **Funnel** | 61,252 viewers → 11,114 carts → 4,167 checkouts → **2,356 purchases (3.85%)** |
| **Biggest leak** | **81.9%** of viewers never add to cart — 85% of every shopper the funnel loses |
| **Real segment gap** | Returning shoppers convert at **1.8×** new ones (6.40% vs 3.60%, adjusted p = 2e-24) |
| **Not a finding** | Desktop vs mobile: 3.77% vs 3.95%, **p = 0.27** — noise, so no mobile project |
| **Largest prize** | Up to **$41k** from a 5-point lift in add-to-cart (upper bound) |
| **Test plan** | A **+2-point** lift is detectable in **3 weeks** (6,072 shoppers per arm) |
| **Recommendation** | Rework the product-page add-to-cart path — 4.8× the next option on RICE |

## Business question → decision

| # | Business question | What the data says | Decision |
|---|---|---|---|
| 01 | Where do shoppers leave? | 81.9% drop before cart; later steps keep 37% and 57% | Fix the product page before checkout |
| 02 | Is the loss concentrated in a segment? | New vs returning is real; device is noise | Don't fund a mobile-specific fix |
| 03 | Which channels bring buyers? | Conversion spans 3.6% – 5.7% | Rebalance spend, after checking lifetime value |
| 04 | Do shoppers come back? | 4.3% return in week one; 22% of purchases need a return visit | Persist the cart across sessions |
| 05 | What is each fix worth? | $41k / $20k / $13k ceilings by step | Treat as ceilings, never forecasts |
| 06 | What do we do first? | Product page leads RICE 23,398 to 4,861 | Start with the product page |
| 07 | How do we prove it worked? | Only add-to-cart is testable at this traffic | 3-week 50/50 test; ship only if guardrails hold |
| 08 | Why trust any of this? | Funnel computed two independent ways, agreeing exactly | Pipeline refuses to publish if they diverge |

## How it works

```mermaid
flowchart LR
    A[(GA4 export<br/>BigQuery)] -->|11 SQL queries<br/>2.7 GB| B[CSV exports<br/>+ provenance manifest]
    B --> C{Correctness gates}
    C -->|monotonic and methods agree| D[analyze.py<br/>z-tests · Holm · sizing · RICE]
    C -->|diverge| X[Stop: nothing published]
    D --> T[experiment.py<br/>sample size · duration · guardrails]
    D --> E[metrics.json]
    T --> E
    E --> F[Decision memo]
    E --> G[Static report site]
    E --> H[Streamlit dashboard]
```

**The gate is the part worth reading.** The funnel is computed twice: once by comparing
timestamps, once by a regex over each shopper's event sequence. On the first real export
they disagreed by 17%, and neither query had a bug. GA4 users repeat steps constantly, and
GA4 stamps every event in one request with the same microsecond. Both are now handled, the
methods agree exactly, and any future drift above 0.5% stops the pipeline.
Full story in [methodology.md](docs/methodology.md).

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/segments.png" alt="Forest plot: device gap crosses zero, new vs returning does not"></td>
    <td width="50%"><img src="docs/screenshots/retention.png" alt="Cohort retention heatmap with right-censored cells hatched"></td>
  </tr>
  <tr>
    <td><sub>Segment gaps with 95% intervals. Device crosses zero, so it is not written up as a finding.</sub></td>
    <td><sub>Cohort retention. Hatched cells are not yet observable, not zero, and are excluded from every average.</sub></td>
  </tr>
</table>

## Repository layout

| Folder | What it holds |
|---|---|
| [`sql/`](sql/) | 11 parameterised BigQuery queries: funnel, validation, segments, cohorts, revenue |
| [`funnelscope/`](funnelscope/) | The only place maths happens: gates, z-tests, Holm, sizing, censoring, RICE, test design |
| [`scripts/`](scripts/) | The pipeline: export → analyse → render memo → build site |
| [`docs/`](docs/) | **[MEMO.md](docs/MEMO.md)** (the deliverable), methodology, interview defence, query costs |
| [`web/`](web/) | The report site: plain HTML/CSS/JS, opens from `file://`, deploys to GitHub Pages |
| [`app/`](app/) | Streamlit dashboard for interactive filtering |
| [`tests/`](tests/) | 175 tests: SQL checks, funnel invariants, statistics vs SciPy and statsmodels |

## Run it

```bash
git clone https://github.com/Ishaana0112/FunnelScope.git && cd FunnelScope
bash setup.sh                      # Windows: .\setup.ps1
open web/index.html                # the report, no server needed
```

`streamlit run app/streamlit_app.py` for the dashboard · `pytest` for the tests · `make all`
to rebuild everything. Re-exporting from BigQuery needs a free Sandbox project; see
[sql/README.md](sql/README.md).

## Tags

Business intelligence · data analysis · product analytics · ecommerce analytics · funnel
and cohort analysis · A/B test design · statistics · KPI reporting · dashboards · BigQuery ·
SQL · Google Analytics 4 · Python · pandas · Streamlit

## Scope, honestly

This is Google's public obfuscated GA4 sample, not a business problem I found. Channel and
product names are redacted at source. What is real is the analysis: SQL against GA4's nested
schema, a funnel that survives two independent implementations, statistics corrected for
multiple comparisons, and recommendations that state their assumptions. Every revenue figure
is an upper bound, and nothing has been A/B tested yet; the test plan says how it would be.

---

<sub>MIT licence · Built by Ishaan Singh</sub>
