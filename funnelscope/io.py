"""Loading exported CSVs, and the data-provenance manifest.

Every write of data/processed/ stamps a manifest recording whether the numbers came from
BigQuery or the synthetic fixture. Every consumer reads that stamp and labels itself, so
fixture numbers cannot be published as an analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
MANIFEST_PATH = PROCESSED_DIR / "_manifest.json"

SOURCE_BIGQUERY = "bigquery"
SOURCE_FIXTURE = "synthetic-fixture"

FIXTURE_WARNING = (
    "THESE NUMBERS ARE FROM A SYNTHETIC FIXTURE, NOT FROM GA4. "
    "They exist so the pipeline can be executed and tested end to end without GCP "
    "credentials. They describe nothing about Google's demo store and must not be "
    "quoted as findings. Run `python scripts/run_queries.py` to replace them."
)


@dataclass
class Manifest:
    """Provenance record for whatever currently sits in data/processed/."""

    source: str
    generated_at: str
    dataset: str
    window_start: str
    window_end: str
    note: str = ""

    @property
    def is_real(self) -> bool:
        return self.source == SOURCE_BIGQUERY

    def banner(self) -> str:
        """One line for the top of any artifact built from this data.

        No "Data:" prefix — every consumer supplies its own label.
        """
        if self.is_real:
            return (
                f"{self.dataset}, {self.window_start} to {self.window_end}. "
                f"Exported {self.generated_at[:10]}."
            )
        return f"[SYNTHETIC FIXTURE] {FIXTURE_WARNING}"

    def write(self) -> None:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(asdict(self), indent=2) + "\n")


def write_manifest(source: str, dataset: str, window_start: str, window_end: str,
                   note: str = "") -> Manifest:
    manifest = Manifest(
        source=source,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dataset=dataset,
        window_start=window_start,
        window_end=window_end,
        note=note,
    )
    manifest.write()
    return manifest


def read_manifest() -> Manifest:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No manifest at {MANIFEST_PATH}. Run `python scripts/run_queries.py` "
            f"(real data) or `python scripts/make_fixture.py` (pipeline test) first."
        )
    return Manifest(**json.loads(MANIFEST_PATH.read_text()))


def load(name: str) -> pd.DataFrame:
    """Load one processed CSV by stem, e.g. load('02_funnel_overall')."""
    path = PROCESSED_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Available: "
            f"{sorted(p.stem for p in PROCESSED_DIR.glob('*.csv')) or 'nothing yet'}"
        )
    return pd.read_csv(path)


def save(df: pd.DataFrame, name: str) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    return path
