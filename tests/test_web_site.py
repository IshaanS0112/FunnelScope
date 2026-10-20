"""Tests for the static site and its data bundle.

The site has no build step and no framework, so there is no compiler to catch a typo in
a key name. These tests are that compiler: they check the bundle carries what the page
reads, and that the provenance banner cannot be lost.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "web"
DATA_JS = WEB / "data.js"
INDEX = WEB / "index.html"
APP_JS = WEB / "app.js"


def bundle() -> dict:
    if not DATA_JS.exists():
        pytest.skip("web/data.js not built yet — run scripts/build_web.py")
    text = DATA_JS.read_text()
    return json.loads(text[text.index("{"):text.rindex(";")])


def test_site_files_exist():
    for path in (INDEX, APP_JS, WEB / "styles.css", WEB / "tokens.css"):
        assert path.exists(), f"{path.name} is missing"


def test_data_is_a_script_not_a_fetch():
    """A browser blocks fetch() against file://, so a site that fetched its JSON would
    work when served and break when opened by double-click. The data must be a plain
    script assignment."""
    assert "window.FUNNELSCOPE_DATA" in DATA_JS.read_text()
    assert 'src="data.js"' in INDEX.read_text()
    assert not re.search(r"fetch\(\s*['\"]data\.js", APP_JS.read_text())


def test_no_external_resources():
    """No CDN, no Google Fonts, no analytics. The page must render with the network off,
    which is also what makes it safe to hand to someone."""
    html = INDEX.read_text()
    # The SVG/XHTML namespace URIs are identifiers, not fetches — nothing is requested.
    html = html.replace("http://www.w3.org/2000/svg", "") \
               .replace("http://www.w3.org/1999/xhtml", "")
    for pattern in ("http://", "//cdn", "googleapis", "unpkg", "jsdelivr"):
        offenders = [ln for ln in html.splitlines() if pattern in ln]
        assert not offenders, f"external resource '{pattern}': {offenders[:2]}"

    # Only LOADED resources are checked. An <a href> to the repository is navigation
    # the reader chooses; a <script src> is a third party the page depends on to render.
    loaded = (re.findall(r'<script[^>]+src="([^"]+)"', html)
              + re.findall(r'<link[^>]+href="([^"]+)"', html)
              + re.findall(r'<img[^>]+src="([^"]+)"', html))
    for ref in loaded:
        if ref.startswith("data:"):
            continue
        assert not ref.startswith(("http", "//")), f"remote asset loaded: {ref}"


def test_bundle_has_every_key_the_page_reads():
    b = bundle()
    for key in ("provenance", "funnel", "retention", "acquisition", "opportunities",
                "sensitivity", "significance_tests", "rice", "aov", "validation",
                "stage_labels", "stages", "overview"):
        assert key in b, f"web/data.js is missing '{key}'"


def test_every_chapter_in_the_nav_exists_in_the_html():
    """The chapter list lives in app.js and the sections live in index.html. A mismatch
    is a nav link to nowhere, and there is no framework to complain about it."""
    ids = re.findall(r'\{ id: "(\w+)", label:', APP_JS.read_text())
    assert ids, "could not find the CHAPTERS list in app.js"
    html = INDEX.read_text()
    for chapter in ids:
        assert re.search(rf'<section[^>]+id="{chapter}"', html), (
            f"app.js links to chapter '{chapter}' with no section")


def test_every_chapter_states_a_business_question_and_a_decision():
    """The report's structure is the point: each chapter opens with the business
    question it answers and closes with what to do about it."""
    html = INDEX.read_text()
    sections = re.findall(r'<section class="chapter[^"]*" id="(\w+)">(.*?)</section>', html, re.S)
    assert len(sections) >= 6, "expected the numbered report chapters"
    for sid, body in sections:
        assert "Business question" in body, f"chapter '{sid}' has no business question"
        assert 'class="decision"' in body, f"chapter '{sid}' has no decision"


def test_fonts_are_self_hosted():
    """The design system's fonts are bundled so the page still renders offline and from
    file:// — fetching them from Google would break both."""
    tokens = (WEB / "tokens.css").read_text()
    for url in re.findall(r'url\("([^"]+)"\)', tokens):
        assert not url.startswith(("http", "//")), f"remote font: {url}"
        assert (WEB / url).exists(), f"missing font file {url}"


def test_data_strings_are_escaped_before_innerhtml():
    """GA4's obfuscated channel names ('<Other> / <Other>') are valid HTML tags. Any
    channel or segment name interpolated into innerHTML without esc() silently
    disappears from the page — which is exactly what the first version did."""
    js = APP_JS.read_text()
    for field in ("worstCh.channel", "bestCh.channel", "gap.segment_a", "gap.segment_b"):
        for m in re.finditer(re.escape(field), js):
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            if "setHTML" in line or "decision(" in line or '"<' in line or "parts.push" in line:
                assert f"esc({field}" in line or f"esc(cap({field}" in line, (
                    f"{field} reaches innerHTML unescaped: {line.strip()}")


def test_every_mount_target_exists_in_the_html():
    """mount() silently no-ops on a missing id, so a renamed element would drop a whole
    section without an error anywhere."""
    html = INDEX.read_text()
    for target in set(re.findall(r'mount\("([\w-]+)"', APP_JS.read_text())):
        assert f'id="{target}"' in html, f"app.js mounts into missing #{target}"


def test_funnel_segments_are_all_present():
    b = bundle()
    for key in ("overall", "device", "source", "visitor"):
        assert b["funnel"][key], f"no rows for funnel segment '{key}'"
    overall = b["funnel"]["overall"][0]
    assert overall["counts"]["viewed"] >= overall["counts"]["purchased"]
    assert len(overall["steps"]) == len(b["stages"]) - 1


def test_retention_grid_is_rectangular():
    """Every cohort must span the full week range, or the heatmap misaligns silently."""
    r = bundle()["retention"]
    width = len(r["weeks"])
    for cohort in r["cohorts"]:
        assert len(cohort["values"]) == width, f"{cohort['cohort']} has a ragged row"


def test_censored_cells_are_null_not_zero():
    """A zero would render as a real 0% and read as a retention collapse. That is the
    exact error this project exists to avoid."""
    r = bundle()["retention"]
    if r["censoring"]["cells_censored"] == 0:
        pytest.skip("nothing censored in this export")
    assert any(v is None for c in r["cohorts"] for v in c["values"])


def test_provenance_banner_matches_the_manifest_in_both_directions():
    """Fixture data must carry the banner; real data must not."""
    from funnelscope import io as fio
    manifest = fio.read_manifest()
    b = bundle()
    assert b["provenance"]["source"] == manifest.source
    assert b["provenance"]["is_real"] == manifest.is_real

    app = APP_JS.read_text()
    assert "NOT AN ANALYSIS" in app, "the fixture banner text is gone from app.js"
    assert "p.is_real" in app, "the banner is no longer keyed on the manifest"


def test_significance_tests_carry_the_correction():
    for t in bundle()["significance_tests"]:
        assert "p_value_adjusted" in t, "raw p-values are being published uncorrected"
        assert t["significant"] == t["significant_holm"], (
            "the corrected verdict must be the one the site shows")


@pytest.mark.slow
def test_build_web_is_reproducible():
    """Two builds from the same metrics.json must be byte-identical, so a diff on
    web/data.js always means the numbers moved."""
    before = DATA_JS.read_text()
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_web.py")],
                            capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    assert DATA_JS.read_text() == before


def test_test_plan_chapter_has_a_precomputed_grid():
    """The planner only looks values up; the grid must come from the pipeline."""
    b = bundle()
    exp = b.get("experiment")
    assert exp and exp["plans"], "web/data.js has no experiment plans"
    for plan in exp["plans"]:
        assert plan["grid"], f"no grid for {plan['step_to']}"
        assert {"lift", "n_per_arm", "days", "fits", "worth_up_to"} <= set(plan["grid"][0])
    assert re.search(r'<section[^>]+id="test"', INDEX.read_text())
