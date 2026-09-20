# Query costs

Actual bytes scanned, from `python scripts/run_queries.py --dry-run`. A dry run is never
billed, so this table can be refreshed as often as you like — and should be, before any
change to the date range or to a column list.

**Why log it at all.** An estimate in a header comment goes stale the moment the query
changes. A logged measurement does not, and the difference between the two is how you
notice that a query you thought was cheap now reads `event_params`.

## Budget

BigQuery Sandbox gives **1 TiB of query processing per month**, permanently, with no
billing account. A full refresh of this project is roughly **4.9 GB**, so the pipeline can
be re-run about **200 times a month** for free. The numbers below are what that claim
rests on.

## Log

Add a row per dry run. Keep the old rows: the point is the trend, not the latest value.

| Date | Query | Bytes scanned | Notes |
|---|---|---:|---|
| _pending first BigQuery run_ | `01_event_overview.sql` | — | estimate ~0.4 GB |
| _pending first BigQuery run_ | `02_funnel_ordered.sql` | — | estimate ~0.5 GB |
| _pending first BigQuery run_ | `02b_funnel_validation.sql` | — | estimate ~0.5 GB |
| _pending first BigQuery run_ | `03_funnel_by_device.sql` | — | estimate ~0.6 GB |
| _pending first BigQuery run_ | `04_funnel_by_source.sql` | — | estimate ~0.7 GB |
| _pending first BigQuery run_ | `05_funnel_new_vs_returning.sql` | — | estimate ~0.5 GB |
| _pending first BigQuery run_ | `06_cohort_retention.sql` | — | estimate ~0.4 GB |
| _pending first BigQuery run_ | `07_revenue_by_segment.sql` | — | estimate ~0.3 GB |
| _pending first BigQuery run_ | `08_event_params_reference.sql` | — | estimate ~1.2 GB, narrow range |
| _pending first BigQuery run_ | `09_funnel_session_scoped.sql` | — | estimate ~0.9 GB |

The estimates above are the figures in each query's header comment. They are replaced by
measurements on the first real dry run; until then this file records what has *not* yet
been verified, which is more useful than an empty file.

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
   available — it is heavier than every scalar column combined.
3. **Nothing else.** `LIMIT` truncates the result, not the scan. `WHERE event_name = ...`
   reduces rows, not columns. Neither reduces the bill by a byte.
