# `sql/` — what each query answers, and what it costs

Every query is parameterised (`@start_suffix`, `@end_suffix`) and run by
`scripts/run_queries.py`. None of them create tables or views: BigQuery Sandbox
expires both after 60 days and blocks DML, so the repo persists *results*, not
*derived tables*.

| File | Question it answers | Output CSV | Est. scan |
|---|---|---|---|
| `01_event_overview.sql` | What events exist, how many, over what dates, from how many users | `01_event_overview.csv` | ~0.4 GB |
| `02_funnel_ordered.sql` | Ordered view → cart → checkout → purchase funnel, all users | `02_funnel_overall.csv` | ~0.5 GB |
| `02b_funnel_validation.sql` | The same funnel by an unrelated method, as a correctness gate | `02b_funnel_validation.csv` | ~0.5 GB |
| `03_funnel_by_device.sql` | Funnel cut by device category | `03_funnel_by_device.csv` | ~0.6 GB |
| `04_funnel_by_source.sql` | Funnel cut by acquisition channel (long tail folded) | `04_funnel_by_source.csv` | ~0.7 GB |
| `05_funnel_new_vs_returning.sql` | Funnel cut by new vs returning visitor | `05_funnel_by_visitor_type.csv` | ~0.5 GB |
| `06_cohort_retention.sql` | Weekly cohort retention, with cohort sizes | `06_cohort_retention.csv` | ~0.4 GB |
| `07_revenue_by_segment.sql` | Purchases, revenue and AOV by device and channel | `07_revenue_by_segment.csv` | ~0.3 GB |
| `08_event_params_reference.sql` | How to extract nested `event_params` (reference only) | `08_event_params_sample.csv` | ~1.2 GB · **narrow the range** |
| `09_funnel_session_scoped.sql` | The same funnel scoped to the session, not the user | `09_funnel_session_scoped.csv` | ~0.9 GB |

Total for a full refresh excluding `08`: **≈ 4.9 GB**, against the sandbox's 1 TiB
monthly allowance — roughly 200 free re-runs a month. `09` is the second most expensive
query in the set because `ga_session_id` lives inside `event_params`, and reading one key
out of that column costs the same as reading the column.

Actual dry-run bytes, logged per run, are in [`docs/QUERY_COSTS.md`](../docs/QUERY_COSTS.md).

## Cost control, in order of how much they matter

1. **`_TABLE_SUFFIX` on every wildcard query.** Without it BigQuery scans every daily
   table in the dataset. This is the mistake that burns the free tier.
2. **Never `SELECT *`.** BigQuery is columnar and bills on bytes scanned per column.
   `event_params` alone is heavier than every scalar column combined — `08` costs more
   than the entire rest of the pipeline for that reason.
3. **`LIMIT` does not reduce cost.** It truncates the result, not the scan. `08` still
   reads its full column set despite `LIMIT 500`.
4. **`WHERE event_name = ...` does not reduce cost either.** It reduces rows, not the
   columns read. Useful for correctness, not for the bill.
5. **Dry-run first.** `python scripts/run_queries.py --dry-run` reports exact bytes for
   every query without executing or being billed. Do this before any change to the range.

## Conventions used across the funnel queries

- **Ordering is cumulative.** Stage *N* re-asserts every predicate from stages
  1..*N*−1, so each stage is a strict subset of the previous one and the funnel cannot
  go non-monotonic. See the header comment in `02_funnel_ordered.sql` for why the
  obvious independent-predicate form is wrong.
- **Segment attribution is first-touch** in `03`/`04` (a funnel follows one journey) and
  **event-level in `07`** (revenue belongs to the transaction). Deliberate, documented in
  each file, and discussed in `docs/methodology.md`.
- **Scope is the user in `02`–`05`, the session in `09`.** Both are the same cumulative
  funnel; only the partition key differs. Session-scoped conversion is necessarily no
  higher, and the gap measures how much of the funnel depends on return visits —
  `funnelscope.funnel.session_gap` asserts the inequality and reports the gap.
- **Every funnel query emits the same four columns** — `viewed`, `added_to_cart`,
  `began_checkout`, `purchased` — plus `segment_type` / `segment_value`, so the
  application code has exactly one funnel shape to handle.
