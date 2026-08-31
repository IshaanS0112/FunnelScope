"""RICE prioritisation.

RICE = (Reach x Impact x Confidence) / Effort.

The scores below are not engineering estimates -- there is no engineering team attached
to this analysis. Reach is taken from measured segment sizes so at least one term is
grounded. Impact and Effort are judgement, Confidence reflects how much of the claim is
measured versus assumed. The value of the framework here is that the ranking is
reproducible from stated inputs rather than asserted, and that a reader who disagrees
with a score can change it and see the ranking move.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

# Impact scale, as used by the framework's originators (Intercom).
IMPACT_SCALE = {"massive": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5, "minimal": 0.25}


@dataclass
class Recommendation:
    name: str
    rationale: str
    reach: float          # users affected in the analysis window (measured)
    impact: float         # IMPACT_SCALE value (judgement)
    confidence: float     # 0..1 (how much of the claim is measured vs assumed)
    effort: float         # person-weeks (judgement)
    evidence: str = ""
    assumptions: str = ""

    @property
    def score(self) -> float:
        return (self.reach * self.impact * self.confidence) / self.effort if self.effort else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rice_score"] = self.score
        return d


def rank(recommendations: list[Recommendation]) -> pd.DataFrame:
    df = pd.DataFrame([r.to_dict() for r in recommendations])
    if df.empty:
        return df
    df = df.sort_values("rice_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    return df
