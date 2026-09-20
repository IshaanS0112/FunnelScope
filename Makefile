# FunnelScope — the pipeline, in dependency order.
#
# Every target downstream of analyze depends on the correctness gates having passed,
# because analyze raises rather than returning bad metrics. That ordering is the point:
# `make memo` on a broken funnel fails at the gate, not at the memo.

PYTHON ?= python

.PHONY: help setup fixture analyze memo web all dash test test-all clean costs

help:
	@echo "setup     create .venv (3.12), install deps, build the fixture"
	@echo "fixture   regenerate the synthetic event log and its CSVs"
	@echo "analyze   run the gates and write data/processed/metrics.json"
	@echo "memo      render docs/MEMO.md from metrics.json"
	@echo "web       build web/data.js for the static site"
	@echo "all       analyze + memo + web"
	@echo "dash      run the Streamlit dashboard"
	@echo "test      unit tests, SQL static checks, front-end smoke tests"
	@echo "test-all  the above plus the end-to-end pipeline chain"
	@echo "costs     BigQuery dry run — reports bytes per query, nothing billed"

setup:
	bash setup.sh

fixture:
	$(PYTHON) scripts/make_fixture.py

analyze:
	$(PYTHON) scripts/analyze.py

memo: analyze
	$(PYTHON) scripts/render_memo.py

web: analyze
	$(PYTHON) scripts/build_web.py

all: analyze
	$(PYTHON) scripts/render_memo.py
	$(PYTHON) scripts/build_web.py

dash:
	streamlit run app/streamlit_app.py

test:
	$(PYTHON) -m pytest -q

test-all:
	$(PYTHON) -m pytest -q
	$(PYTHON) -m pytest -q -m slow

costs:
	$(PYTHON) scripts/run_queries.py --dry-run

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
