#!/usr/bin/env python3
"""Run the SQL in sql/ against BigQuery and export results to data/processed/.

This is the only script that touches GCP. Everything downstream reads the CSVs, which
is why the dashboard runs for anyone without credentials.

Usage
-----
    python scripts/run_queries.py --dry-run      # cost estimate only, never billed
    python scripts/run_queries.py                # execute and export
    python scripts/run_queries.py --only 02      # one query by filename prefix

Prerequisites
-------------
    pip install google-cloud-bigquery db-dtypes
    gcloud auth application-default login
    export GOOGLE_CLOUD_PROJECT=your-sandbox-project-id

BigQuery Sandbox is free, needs no billing account, and gives 1 TiB of query
processing per month. A full refresh here is about 4 GB.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from funnelscope import io as fio  # noqa: E402

DATASET = "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*"
# BigQuery wants the wildcard suffix form; every artifact downstream wants ISO dates.
# Keeping both here, rather than formatting at each use site, is why the memo header
# reads "2020-11-01" and not "20201101".
WINDOW_START = "20201101"
WINDOW_END = "20210131"
WINDOW_START_ISO = "2020-11-01"
WINDOW_END_ISO = "2021-01-31"

# Sample range for the event_params reference query only. event_params is by far the
# widest column in the schema, so this one is deliberately restricted to a few days.
SAMPLE_START = "20210125"
SAMPLE_END = "20210131"

# sql filename -> output CSV stem
OUTPUTS = {
    "01_event_overview":          "01_event_overview",
    "02_funnel_ordered":          "02_funnel_overall",
    "02b_funnel_validation":      "02b_funnel_validation",
    "03_funnel_by_device":        "03_funnel_by_device",
    "04_funnel_by_source":        "04_funnel_by_source",
    "05_funnel_new_vs_returning": "05_funnel_by_visitor_type",
    "06_cohort_retention":        "06_cohort_retention",
    "07_revenue_by_segment":      "07_revenue_by_segment",
    "08_event_params_reference":  "08_event_params_sample",
    "09_funnel_session_scoped":   "09_funnel_session_scoped",
    "10_timestamp_ties":          "10_timestamp_ties",
}

MIN_USERS_PER_CHANNEL = 500  # channels smaller than this fold into '(long tail)'


def build_params(bigquery, sql_text: str):
    """Only bind the parameters a given query actually references."""
    candidates = {
        "start_suffix":        bigquery.ScalarQueryParameter("start_suffix", "STRING", WINDOW_START),
        "end_suffix":          bigquery.ScalarQueryParameter("end_suffix", "STRING", WINDOW_END),
        "sample_start_suffix": bigquery.ScalarQueryParameter("sample_start_suffix", "STRING", SAMPLE_START),
        "sample_end_suffix":   bigquery.ScalarQueryParameter("sample_end_suffix", "STRING", SAMPLE_END),
        "min_users":           bigquery.ScalarQueryParameter("min_users", "INT64", MIN_USERS_PER_CHANNEL),
    }
    return [p for name, p in candidates.items() if f"@{name}" in sql_text]


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="report bytes each query would scan; nothing is executed or billed")
    ap.add_argument("--only", help="run only queries whose filename starts with this")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    help="GCP project id (defaults to $GOOGLE_CLOUD_PROJECT)")
    args = ap.parse_args()

    try:
        from google.cloud import bigquery
    except ImportError:
        print("google-cloud-bigquery is not installed.\n"
              "  pip install google-cloud-bigquery db-dtypes", file=sys.stderr)
        return 1

    if not args.project:
        print("No GCP project. Set GOOGLE_CLOUD_PROJECT or pass --project.", file=sys.stderr)
        return 1

    client = bigquery.Client(project=args.project)
    sql_dir = REPO_ROOT / "sql"
    files = sorted(p for p in sql_dir.glob("*.sql"))
    if args.only:
        files = [p for p in files if p.stem.startswith(args.only)]
        if not files:
            print(f"No SQL file starts with {args.only!r}.", file=sys.stderr)
            return 1

    total_bytes = 0
    for path in files:
        sql_text = path.read_text()
        params = build_params(bigquery, sql_text)

        estimate = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                           query_parameters=params)
        job = client.query(sql_text, job_config=estimate)
        scanned = job.total_bytes_processed or 0
        total_bytes += scanned
        print(f"{path.name:<34} would scan {human_bytes(scanned):>10}")

        if args.dry_run:
            continue

        cfg = bigquery.QueryJobConfig(query_parameters=params)
        df = client.query(sql_text, job_config=cfg).to_dataframe()
        out = fio.save(df, OUTPUTS[path.stem])
        print(f"{'':<34} -> {out.relative_to(REPO_ROOT)}  ({len(df):,} rows)")

    print(f"\nTotal: {human_bytes(total_bytes)} of the 1 TiB monthly sandbox allowance.")

    if not args.dry_run and not args.only:
        fio.write_manifest(
            source=fio.SOURCE_BIGQUERY,
            dataset=DATASET,
            window_start=WINDOW_START_ISO,
            window_end=WINDOW_END_ISO,
            note=f"Exported by run_queries.py from project {args.project}.",
        )
        print("Wrote data/processed/_manifest.json (source=bigquery).")
        print("Next: python scripts/analyze.py && python scripts/render_memo.py")
    elif not args.dry_run:
        print("\nPartial run (--only): manifest NOT updated. Run a full export before "
              "regenerating the memo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
