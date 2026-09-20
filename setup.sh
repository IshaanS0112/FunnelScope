#!/usr/bin/env bash
# FunnelScope setup — macOS / Linux.  Windows: use setup.ps1.
#
# Creates a Python 3.12 virtual environment, installs the dependencies, and builds the
# synthetic fixture so the dashboard and the memo have something to render immediately.
#
#   bash setup.sh
#
# Python is pinned to 3.12: some dependencies still have no 3.13/3.14 wheels on Windows,
# and a setup script that works on one machine is not a setup script.

set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.12 not found (looked for '$PYTHON_BIN')." >&2
  echo "  macOS:  brew install python@3.12" >&2
  echo "  Ubuntu: sudo apt install python3.12 python3.12-venv" >&2
  echo "Or set PYTHON_BIN to another 3.12 interpreter and re-run." >&2
  exit 1
fi

echo "==> Creating .venv with $("$PYTHON_BIN" --version)"
"$PYTHON_BIN" -m venv .venv

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo "==> Building the synthetic fixture so the pipeline has data to run on"
python scripts/make_fixture.py
python scripts/analyze.py >/dev/null
python scripts/render_memo.py

cat <<'EOF'

Done. The data in data/processed/ is a SYNTHETIC FIXTURE, not an analysis — every
artifact it produces says so, on purpose.

Next:
  source .venv/bin/activate
  streamlit run app/streamlit_app.py     # dashboard
  python scripts/build_web.py            # static site -> web/index.html
  pytest -q                              # test suite

To replace the fixture with real GA4 data:
  pip install google-cloud-bigquery db-dtypes
  gcloud auth application-default login
  export GOOGLE_CLOUD_PROJECT=your-sandbox-project-id
  python scripts/run_queries.py --dry-run   # cost estimate, nothing billed
  python scripts/run_queries.py && python scripts/analyze.py && python scripts/render_memo.py
EOF
