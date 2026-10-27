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


@pytest.fixture
def preserve_artifacts():
    """Snapshot and restore everything the pipeline writes.

    The end-to-end test runs make_fixture.py, which overwrites data/processed/ — so
    without this, running the test suite silently replaces a real BigQuery export with
    synthetic data, and the next commit ships fixture numbers with a real-data manifest.
    That is exactly the provenance failure the manifest exists to prevent, arriving
    through the back door.

    Snapshot-and-restore rather than redirecting the paths: it needs no indirection in
    the scripts, and it covers every artifact they touch rather than the ones a path
    override happened to reach.
    """
    targets = [REPO_ROOT / "data" / "processed", REPO_ROOT / "docs" / "MEMO.md",
               REPO_ROOT / "web" / "data.js"]
    saved = {}
    for path in targets:
        if path.is_dir():
            saved[path] = {f: f.read_bytes() for f in path.iterdir() if f.is_file()}
        elif path.exists():
            saved[path] = path.read_bytes()
    try:
        yield
    finally:
        for path, blob in saved.items():
            if isinstance(blob, dict):
                for f in path.iterdir():
                    if f.is_file() and f not in blob:
                        f.unlink()
                for f, data in blob.items():
                    f.write_bytes(data)
            else:
                path.write_bytes(blob)


@pytest.mark.slow
@pytest.mark.usefixtures("preserve_artifacts")
def test_pipeline_runs_end_to_end():
    """fixture -> analyze -> memo -> site, as a subprocess chain, exactly as a user
    would run it. Chained as subprocesses rather than function calls so an import-time
    or CLI regression is caught too."""
    for script in ("make_fixture.py", "analyze.py", "render_memo.py", "build_web.py"):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script)],
            capture_output=True, text=True, cwd=REPO_ROOT)
        assert result.returncode == 0, f"{script} failed:\n{result.stderr}"
    memo = (REPO_ROOT / "docs" / "MEMO.md").read_text()
    assert "{{" not in memo, "memo has unfilled template tokens"
    assert "window.FUNNELSCOPE_DATA" in (REPO_ROOT / "web" / "data.js").read_text()


def test_fixture_output_is_labelled_as_fixture():
    """The provenance guard, asserted in both directions: fixture data must never render
    as a clean analysis, and real data must never carry a banner that would make a
    recruiter discard a genuine result."""
    memo = (REPO_ROOT / "docs" / "MEMO.md")
    if not memo.exists():
        pytest.skip("memo not rendered yet")
    from funnelscope import io as fio
    manifest = fio.read_manifest()
    if manifest.is_real:
        assert "SYNTHETIC FIXTURE" not in memo.read_text()
        assert "NOT AN ANALYSIS" not in memo.read_text()
    else:
        assert "NOT AN ANALYSIS" in memo.read_text()
        assert memo.read_text().lstrip().startswith(">"), (
            "the banner must be the first thing in the file, not buried in it")


def test_every_sql_file_has_an_output_mapping():
    """A query nobody exports is a query that silently rots. run_queries.py must know
    where every file in sql/ writes to."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_queries
    for path in SQL_FILES:
        assert path.stem in run_queries.OUTPUTS, (
            f"{path.name} has no entry in run_queries.OUTPUTS")


def test_manifest_window_is_iso_dates():
    """The memo prints these verbatim. BigQuery wants the wildcard suffix form
    (20201101); everything downstream wants 2020-11-01, and mixing them puts a raw
    suffix in the memo header."""
    from funnelscope import io as fio
    m = fio.read_manifest()
    for value in (m.window_start, m.window_end):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), (
            f"manifest window {value!r} is not an ISO date")


def test_streamlit_app_runs_without_exceptions():
    at = pytest.importorskip("streamlit.testing.v1")
    app = at.AppTest.from_file(str(REPO_ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    app.run()
    assert not app.exception, f"dashboard raised: {app.exception}"
    for i in range(1, 4):
        app.sidebar.radio[0].set_value(
            ["Funnel", "Retention", "Acquisition", "Opportunity"][i]).run()
        assert not app.exception, f"page {i} raised: {app.exception}"
