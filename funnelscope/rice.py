"""RICE prioritisation: (Reach x Impact x Confidence) / Effort.

Reach is measured from the funnel. Impact, Confidence and Effort are judgement — there
is no engineering team attached to this analysis. The value of the framework here is a
ranking reproducible from stated inputs, not that the scores are right.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

# Intercom's impact scale.
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
