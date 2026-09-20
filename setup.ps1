# FunnelScope setup — Windows PowerShell.  macOS / Linux: use setup.sh.
#
# Creates a Python 3.12 virtual environment, installs the dependencies, and builds the
# synthetic fixture so the dashboard and the memo have something to render immediately.
#
#   .\setup.ps1
#
# If PowerShell refuses to run this, its execution policy is blocking local scripts:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Python is pinned to 3.12: some dependencies still have no 3.13/3.14 wheels on Windows.

$ErrorActionPreference = "Stop"

Write-Host "==> Checking for Python 3.12"
try {
    $version = & py -3.12 --version
} catch {
    Write-Error @"
Python 3.12 not found.
Install it from https://www.python.org/downloads/release/python-3120/ or run:
    winget install Python.Python.3.12
Then re-run .\setup.ps1
"@
    exit 1
}

Write-Host "==> Creating .venv with $version"
py -3.12 -m venv .venv
& .\.venv\Scripts\Activate.ps1

Write-Host "==> Installing dependencies"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

Write-Host "==> Building the synthetic fixture so the pipeline has data to run on"
python scripts\make_fixture.py
python scripts\analyze.py | Out-Null
python scripts\render_memo.py

Write-Host @"

Done. The data in data\processed\ is a SYNTHETIC FIXTURE, not an analysis — every
artifact it produces says so, on purpose.

Next:
  .\.venv\Scripts\Activate.ps1
  streamlit run app\streamlit_app.py     # dashboard
  python scripts\build_web.py            # static site -> web\index.html
  pytest -q                              # test suite

To replace the fixture with real GA4 data:
  pip install google-cloud-bigquery db-dtypes
  gcloud auth application-default login
  `$env:GOOGLE_CLOUD_PROJECT = "your-sandbox-project-id"
  python scripts\run_queries.py --dry-run   # cost estimate, nothing billed
  python scripts\run_queries.py; python scripts\analyze.py; python scripts\render_memo.py
"@
