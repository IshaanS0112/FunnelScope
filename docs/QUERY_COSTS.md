# Query costs

Actual bytes scanned, from `python scripts/run_queries.py --dry-run`. A dry run is never
billed, so this table can be refreshed as often as you like — and should be, before any
change to the date range or to a column list.

**Why log it at all.** An estimate in a header comment goes stale the moment the query
changes. A logged measurement does not, and the difference between the two is how you
notice that a query you thought was cheap now reads `event_params`.

## Budget

BigQuery Sandbox gives **1 TiB of query processing per month**, permanently, with no
billing account. A full refresh of this project is **2.7 GB**, so the pipeline can be
re-run roughly **380 times a month** for free.

## Measured

Dry run of 2026-09-20, against
`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, window 2020-11-01 to
2021-01-31 (2021-01-25 to 2021-01-31 for `08`).

| Query | Measured | Header estimate | Note |
|---|---:|---:|---|
| `01_event_overview.sql` | 170.8 MB | ~0.4 GB | over-estimated |
| `02_funnel_ordered.sql` | 170.8 MB | ~0.5 GB | over-estimated |
| `02b_funnel_validation.sql` | 170.8 MB | ~0.2 GB | |
| `03_funnel_by_device.sql` | 206.0 MB | ~0.6 GB | `device.category` adds 35 MB |
| `04_funnel_by_source.sql` | 255.7 MB | ~0.7 GB | two `traffic_source` columns |
| `05_funnel_new_vs_returning.sql` | 170.8 MB | ~0.5 GB | |
| `06_cohort_retention.sql` | 117.5 MB | ~0.4 GB | cheapest — two columns only |
| `07_revenue_by_segment.sql` | 258.2 MB | ~0.3 GB | |
| `08_event_params_reference.sql` | 99.2 MB | ~1.2 GB | 7 days, not 92 — the range is why |
| `09_funnel_session_scoped.sql` | **981.9 MB** | ~0.9 GB | reads `event_params` |
| `10_timestamp_ties.sql` | 170.8 MB | ~0.2 GB | |
| **Total** | **2.7 GB** | ~4.9 GB | 0.26% of the monthly allowance |

**The one number worth reading twice is `09`.** It scans more than the next four queries
combined, for one integer: `ga_session_id` lives inside `event_params`, and BigQuery
cannot read one key out of a repeated record without reading the record. Pulling a single
session id costs 5.7× what the same funnel costs partitioned on `user_pseudo_id`.

`08` looks cheap only because its window is 7 days rather than 92. Per day it is the most
expensive query here by a wide margin, which is exactly why its range is narrowed.

## How to refresh this table

```bash
python scripts/run_queries.py --dry-run
```

Every line it prints is one row here. Nothing is executed and nothing is billed.

## What moves these numbers

1. **The date range.** Bytes scale almost linearly with the number of daily tables the
   wildcard matches. Widening `_TABLE_SUFFIX` by a month costs a third more.
2. **Adding a column.** BigQuery is columnar and bills per column read. Adding
   `event_params` to a query that did not read it is the single most expensive edit
   available — `09` is the measured proof, at 5.7× the equivalent scalar query.
3. **Nothing else.** `LIMIT` truncates the result, not the scan. `WHERE event_name = ...`
   reduces rows, not columns. Neither reduces the bill by a byte.
