"""Static checks on the SQL, and an end-to-end run of the whole pipeline.

The SQL cannot be executed without GCP, so it is checked for the things that are
statically knowable and that actually cost money or correctness when wrong.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"
SQL_FILES = sorted(SQL_DIR.glob("*.sql"))

FUNNEL_QUERIES = [p for p in SQL_FILES if "funnel" in p.name]


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_every_query_filters_the_wildcard_table(path):
    """The one mistake that burns the free tier: an unfiltered wildcard scans the
    entire dataset."""
    text = path.read_text()
    assert "_TABLE_SUFFIX BETWEEN" in text, f"{path.name} has no _TABLE_SUFFIX filter"


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_no_select_star(path):
    """BigQuery bills per column scanned; SELECT * bills for all of them."""
    text = re.sub(r"--.*", "", path.read_text())
    assert not re.search(r"SELECT\s+\*", text, re.IGNORECASE), f"{path.name} uses SELECT *"


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_query_documents_itself(path):
    head = path.read_text()[:900]
    for marker in ("Question:", "Output:", "Est. scan:"):
        assert marker in head, f"{path.name} header is missing '{marker}'"


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: p.name)
def test_no_ddl_or_dml(path):
    """BigQuery Sandbox blocks DML and expires tables after 60 days, so the pipeline
    must never depend on writing anything server-side."""
    text = re.sub(r"--.*", "", path.read_text()).upper()
    for stmt in ("INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "CREATE OR REPLACE"):
        assert stmt not in text, f"{path.name} contains {stmt.strip()}"


@pytest.mark.parametrize("path", FUNNEL_QUERIES, ids=lambda p: p.name)
def test_funnel_stage_predicates_are_cumulative(path):
    """Guards the exact bug documented in 02_funnel_ordered.sql: a `purchased` stage
    that does not re-assert the earlier ordering conditions is not a funnel."""
    text = path.read_text()
    if "purchase_ts > checkout_ts" not in text:
        pytest.skip("not a timestamp-ordering funnel query")
    match = re.search(
        r"COUNTIF\((?P<body>[^)]*purchase_ts > checkout_ts[^)]*)\)", text, re.DOTALL)
    assert match, f"{path.name}: could not locate the purchased predicate"
    body = match.group("body")
    assert "cart_ts > view_ts" in body and "checkout_ts > cart_ts" in body, (
        f"{path.name}: the purchased stage does not re-assert earlier ordering "
        f"conditions, so the funnel can go non-monotonic")


def test_sql_parses_as_bigquery():
    sqlglot = pytest.importorskip("sqlglot")
    for path in SQL_FILES:
        text = path.read_text()
        # sqlglot has no notion of @named query parameters; substitute literals.
        text = re.sub(r"@\w+", "'X'", text)
        sqlglot.parse_one(text, dialect="bigquery")


@pytest.mark.slow
def test_pipeline_runs_end_to_end(tmp_path):
    """fixture -> analyze -> memo, as a subprocess chain, exactly as a user would run it."""
    for script in ("make_fixture.py", "analyze.py", "render_memo.py"):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script)],
            capture_output=True, text=True, cwd=REPO_ROOT)
        assert result.returncode == 0, f"{script} failed:\n{result.stderr}"
    memo = (REPO_ROOT / "docs" / "MEMO.md").read_text()
    assert "{{" not in memo, "memo has unfilled template tokens"


def test_fixture_output_is_labelled_as_fixture():
    """The provenance guard: fixture data must never render as a clean analysis."""
    memo = (REPO_ROOT / "docs" / "MEMO.md")
    if not memo.exists():
        pytest.skip("memo not rendered yet")
    from funnelscope import io as fio
    manifest = fio.read_manifest()
    if manifest.is_real:
        assert "SYNTHETIC FIXTURE" not in memo.read_text()
    else:
        assert "NOT AN ANALYSIS" in memo.read_text()


def test_streamlit_app_runs_without_exceptions():
    at = pytest.importorskip("streamlit.testing.v1")
    app = at.AppTest.from_file(str(REPO_ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    app.run()
    assert not app.exception, f"dashboard raised: {app.exception}"
    for i in range(1, 4):
        app.sidebar.radio[0].set_value(
            ["Funnel", "Retention", "Acquisition", "Opportunity"][i]).run()
        assert not app.exception, f"page {i} raised: {app.exception}"
