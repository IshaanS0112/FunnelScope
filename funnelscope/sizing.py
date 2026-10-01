"""Opportunity sizing: turning a drop-off into a revenue figure.

    users_recovered(S, x) = min(users_entering_S * x, users_lost_at_S)
    recoverable(S, x)     = users_recovered * P(purchase | completed S) * AOV

Every figure is an UPPER BOUND: it applies the purchase rate of users who completed a
stage to users who did not. Two corrections to the textbook form, both derived in
docs/methodology.md:

  1. A percentage-point lift applies to users ENTERING, not users LOST. The lost-basis
     form is only (1 - rate) of the correct figure.
  2. This model cannot re-rank the stages. Recoverable revenue is a monotone function of
     step conversion, so ranking by dollars and by worst drop-off are the same ordering.
     ranking_matches_step_conversion() asserts it; a property test checks it.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from .funnel import StageTransition, transitions


@dataclass
class Opportunity:
    from_stage: str
    to_stage: str
    users_entering: int
    users_completing: int
    users_lost: int
    step_conversion: float
    downstream_conversion: float
    aov: float
    improvement_pp: float
    basis: str
    users_recovered: float
    recoverable_revenue: float

    def to_dict(self) -> dict:
        return asdict(self)


def downstream_conversion(row: pd.Series, stage: str) -> float:
    """P(purchase | reached `stage`), measured on the users who reached it."""
    reached = float(row[stage])
    if not reached:
        return 0.0
    return float(row["purchased"]) / reached


def size_stage(row: pd.Series, t: StageTransition, aov: float,
               improvement_pp: float = 0.05, basis: str = "entering") -> Opportunity:
    """Size one transition. `improvement_pp` is a fraction (0.05 = 5pp).

    basis="entering" raises the stage's conversion rate by improvement_pp (the correct
    reading). basis="lost" recovers that share of the users lost — a weaker, different
    claim, kept for comparison. Recovery is capped at the users actually lost.
    """
    if basis not in ("entering", "lost"):
        raise ValueError(f"basis must be 'entering' or 'lost', got {basis!r}")
    raw = t.entered * improvement_pp if basis == "entering" else t.lost * improvement_pp
    recovered = min(raw, float(t.lost))
    dsc = downstream_conversion(row, t.to_stage)
    return Opportunity(
        from_stage=t.from_stage,
        to_stage=t.to_stage,
        users_entering=t.entered,
        users_completing=t.completed,
        users_lost=t.lost,
        step_conversion=t.step_conversion,
        downstream_conversion=dsc,
        aov=aov,
        improvement_pp=improvement_pp,
        basis=basis,
        users_recovered=recovered,
        recoverable_revenue=recovered * dsc * aov,
    )


def size_all_stages(row: pd.Series, aov: float, improvement_pp: float = 0.05,
                    basis: str = "entering") -> pd.DataFrame:
    """Size every transition in one funnel row, ranked by absolute recoverable revenue."""
    rows = [size_stage(row, t, aov, improvement_pp, basis).to_dict()
            for t in transitions(row)]
    df = pd.DataFrame(rows)
    return df.sort_values("recoverable_revenue", ascending=False).reset_index(drop=True)


def sensitivity_table(row: pd.Series, aov: float,
                      improvements=(0.01, 0.02, 0.05, 0.10)) -> pd.DataFrame:
    """Recoverable revenue per stage across a sweep of improvement assumptions.

    The absolute figures move; the ranking does not. That stability is the claim.
    """
    frames = []
    for pp in improvements:
        d = size_all_stages(row, aov, pp)[["to_stage", "improvement_pp", "recoverable_revenue"]]
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    return out.pivot(index="to_stage", columns="improvement_pp",
                     values="recoverable_revenue").reset_index()


def aov_from_revenue(revenue_df: pd.DataFrame) -> float:
    """Transaction-weighted average order value across the whole window."""
    purchases = float(revenue_df["purchases"].sum())
    revenue = float(revenue_df["revenue_usd"].sum())
    return revenue / purchases if purchases else 0.0


def segment_gap_value(row_a: pd.Series, row_b: pd.Series, aov: float) -> dict:
    """Worth of closing the conversion gap between two segments.

    Counterfactual: A converts at B's rate on A's traffic. Also an upper bound.
    """
    conv_a = float(row_a["purchased"]) / float(row_a["viewed"]) if row_a["viewed"] else 0.0
    conv_b = float(row_b["purchased"]) / float(row_b["viewed"]) if row_b["viewed"] else 0.0
    gap = conv_b - conv_a
    extra_purchases = gap * float(row_a["viewed"])
    return {
        "segment_a": row_a["segment_value"],
        "segment_b": row_b["segment_value"],
        "conversion_a": conv_a,
        "conversion_b": conv_b,
        "gap_pp": gap * 100,
        "additional_purchases_if_closed": extra_purchases,
        "value_if_closed": extra_purchases * aov,
    }


def ranking_matches_step_conversion(row: pd.Series, aov: float = 1.0,
                                    improvement_pp: float = 0.05) -> bool:
    """True when ranking by recoverable revenue equals ranking by worst step rate.

    Holds for every strictly ordered funnel. Exposed so a model change that breaks the
    equivalence fails a test instead of quietly manufacturing a finding.
    """
    sized = size_all_stages(row, aov, improvement_pp)
    by_revenue = list(sized.sort_values("recoverable_revenue", ascending=False)["to_stage"])
    by_rate = list(sized.sort_values("step_conversion")["to_stage"])
    return by_revenue == by_rate


def bootstrap_recoverable(row: pd.Series, aov: float, improvement_pp: float = 0.05,
                          basis: str = "entering", n_resamples: int = 2_000,
                          seed: int = 20201101,
                          confidence: float = 0.95) -> pd.DataFrame:
    """Percentile confidence intervals on recoverable revenue, per stage.

    Parametric bootstrap over the funnel's nested binomials — the per-user rows never
    leave BigQuery, so a nonparametric resample is not available downstream.

    It prices sampling variation in the counts and nothing else: not improvement_pp
    (chosen, not measured) and not the assumption that recovered users purchase like
    unaided completers, which dominates the error and is not random. A tight interval
    means the counts are large, not that the number is right.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    stages = [t for t in transitions(row)]
    top = int(row[stages[0].from_stage])
    rates = [t.step_conversion for t in stages]

    draws = {t.to_stage: [] for t in stages}
    lo_q = (1 - confidence) / 2
    hi_q = 1 - lo_q

    for _ in range(n_resamples):
        counts = {stages[0].from_stage: top}
        n = top
        for t, rate in zip(stages, rates):
            n = int(rng.binomial(n, rate)) if n > 0 else 0
            counts[t.to_stage] = n
        resampled = pd.Series(counts)
        for t in transitions(resampled):
            o = size_stage(resampled, t, aov, improvement_pp, basis)
            draws[t.to_stage].append(o.recoverable_revenue)

    point = size_all_stages(row, aov, improvement_pp, basis).set_index("to_stage")
    out = []
    for t in stages:
        sample = np.asarray(draws[t.to_stage], dtype=float)
        out.append({
            "from_stage": t.from_stage,
            "to_stage": t.to_stage,
            "recoverable_revenue": float(point.loc[t.to_stage, "recoverable_revenue"]),
            "ci_low": float(np.quantile(sample, lo_q)),
            "ci_high": float(np.quantile(sample, hi_q)),
            "confidence": confidence,
            "n_resamples": n_resamples,
            "covers": "sampling variation in the funnel counts only",
        })
    return pd.DataFrame(out).sort_values("recoverable_revenue",
                                         ascending=False).reset_index(drop=True)
