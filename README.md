# FunnelScope

**Product analysis of raw GA4 event data: an ordered conversion funnel, cohort retention,
opportunity sizing, and a RICE-prioritised recommendation memo.**

`BigQuery SQL` · `Python` · `Streamlit` · `pytest`

> **The deliverable is [`docs/MEMO.md`](docs/MEMO.md).** The dashboard supports it.
> Read the memo first; the SQL is where the work is.

---

## What this is, honestly

This analyses **Google's public obfuscated GA4 sample export** —
`bigquery-public-data.ga4_obfuscated_sample_ecommerce`, 1 Nov 2020 to 31 Jan 2021. It is
a demo dataset, not a business problem I uncovered, and the repo does not pretend
otherwise. What is real is the analysis: SQL written against GA4's genuinely nested event
schema, an ordered funnel that survives being computed two independent ways, significance
testing on every segment claim, and a memo that says what it would do and what it cannot
know.

I built it because a portfolio full of *systems I built* had nothing in it that was
*analysis I performed on real event data*, which is the core competency for product- and
business-analyst work. That is the gap it fills, and that is the whole claim.

---

## Quick start

```bash
git clone https://github.com/IshaanS0112/FunnelScope.git
cd FunnelScope
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The dashboard reads committed CSVs, so **it runs for anyone, with no GCP account and no
credentials.** That is a deliberate architectural choice, not a shortcut — see below.

To regenerate everything from BigQuery yourself:

```bash
pip install google-cloud-bigquery db-dtypes
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-sandbox-project-id

python scripts/run_queries.py --dry-run   # cost estimate, nothing billed
python scripts/run_queries.py             # export sql/ results to data/processed/
python scripts/analyze.py                 # gates, sizing, z-tests, RICE -> metrics.json
python scripts/render_memo.py             # metrics.json -> docs/MEMO.md
```

BigQuery Sandbox is free, needs no billing account, and gives 1 TiB/month. A full refresh
here is ≈ 4 GB.

---

## Architecture, and why it looks like this

```
sql/*.sql                    versioned queries, parameterised, documented
   │  scripts/run_queries.py
   ▼
data/processed/*.csv         committed  ──►  _manifest.json records provenance
   │  scripts/analyze.py     ── correctness gates run FIRST ──
   ▼
data/processed/metrics.json  every number the memo and dashboard quote
   ├─► scripts/render_memo.py ──► docs/MEMO.md
   └─► app/streamlit_app.py   ──► dashboard
```

**Two BigQuery Sandbox constraints shaped this:** tables and views expire after 60 days,
and DML is blocked. So nothing is persisted server-side; the repo persists *results*.

The consequence is the good part. Because the dashboard reads CSVs rather than querying
BigQuery live, anyone can run it — a recruiter, an interviewer, you. A live-query
dashboard would run for exactly one person and would be dead in 60 days.

---

## The parts worth looking at

**`sql/02_funnel_ordered.sql` — cumulative ordering predicates.**
Each funnel stage re-asserts every earlier condition. The obvious independent form
(`COUNTIF(checkout_ts > cart_ts)` on its own) lets the funnel go non-monotonic. Explained
in the file, enforced by `funnelscope.funnel.check_monotonic`, and grepped for by a test.

**`sql/02b_funnel_validation.sql` — the same funnel, computed a second way.**
Events are collapsed into an ordered string and matched with a sequence regex. It shares
no logic with the timestamp method. The pipeline **refuses to emit metrics** if the two
disagree by more than 0.5%, so a memo cannot be produced from a funnel that failed
validation.

**`funnelscope/sizing.py` — a correction and a proof.**
The standard sizing formula `users_lost × improvement_pp × …` uses the wrong denominator:
a percentage-point lift applies to the conversion *rate*, whose denominator is users
entering. More interestingly, the frequent claim that "the biggest recoverable revenue is
rarely the worst drop-off stage, and that gap is the finding" is **impossible** in a
strictly ordered funnel — recoverable revenue reduces to a monotone function of step
conversion, so the two rankings are identical by construction. Proved in the module
docstring, asserted over random funnels in the test suite, and stated in the memo instead
of a finding that cannot exist.

**`funnelscope/retention.py` — right-censoring.**
A cohort formed in the last weeks of a fixed window cannot show later-week retention.
Every unobservable cell is tagged and excluded rather than plotted as a zero, so late
cohorts read as truncated rather than as a retention collapse.

**`funnelscope/io.py` — provenance you cannot bypass.**
Every write stamps `data/processed/_manifest.json` with `bigquery` or
`synthetic-fixture`. The memo renderer and the dashboard read that stamp and label
themselves. Fixture numbers physically cannot render as a clean analysis.

---

## Repository layout

```
sql/            9 documented queries + a README with per-query scan costs
funnelscope/    funnel maths, censoring, sizing, z-tests, RICE  (one implementation,
                shared by the notebook, the memo and the dashboard)
scripts/        run_queries · make_fixture · analyze · render_memo
data/processed/ committed CSVs + _manifest.json + metrics.json
notebooks/      analysis.ipynb — exploration and the sensitivity work
app/            streamlit_app.py — Funnel · Retention · Acquisition · Opportunity
docs/           MEMO.md (the deliverable) · MEMO_TEMPLATE.md · methodology.md
tests/          101 tests: invariants, SQL static checks, full pipeline, dashboard
```

## Tests

```bash
pytest                    # unit + SQL static checks + dashboard smoke test
pytest -m slow            # full fixture -> analyze -> memo chain
```

The SQL cannot be executed without GCP, so it is checked for what is statically knowable
and expensive when wrong: a missing `_TABLE_SUFFIX` filter, a `SELECT *`, any DDL/DML,
missing header documentation, and — for the funnel queries specifically — stage predicates
that are not cumulative. `sqlglot` parses every file against the BigQuery dialect.

## Without a GCP account

```bash
python scripts/make_fixture.py   # simulated GA4-shaped event log
python scripts/analyze.py
python scripts/render_memo.py
```

This exercises the whole pipeline with no credentials. It is a **fixture, not an
analysis**: the manifest records it as synthetic, and the memo it produces carries a
banner saying so.

## Licence

MIT — see [LICENSE](LICENSE).
