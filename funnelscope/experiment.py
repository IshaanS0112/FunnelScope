"""Experiment design: turning a recommendation into a test that can actually be run.

"Validate with an A/B test" is where most analyses stop. This module answers the
questions that come next: what metric decides it, how big a lift can this store's
traffic detect, how long the test must run, and what must not get worse.

Sample size uses Cohen's h (the arcsine transform of a proportion), which is what
statsmodels' NormalIndPower solves, so the test suite can check it exactly. Quantiles
come from statistics.NormalDist, so the runtime still needs no SciPy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from statistics import NormalDist

import pandas as pd

from . import FUNNEL_STAGES, STAGE_LABELS
from .funnel import transitions
from .sizing import size_stage

# Shortest a test may run, whatever the sample size says: two full weekly cycles, so a
# weekend effect cannot masquerade as a treatment effect.
MIN_DAYS = 14
# Longest worth planning: past four weeks novelty wears off and the cost of a held-out
# control group starts to outweigh what the test can tell you.
MAX_DAYS = 28

LIFT_GRID = tuple(round(x * 0.005, 3) for x in range(1, 21))  # 0.5pt to 10pt


def cohens_h(p1: float, p2: float) -> float:
    """Effect size between two proportions on the arcsine scale."""
    return 2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1))


def sample_size_per_arm(baseline: float, lift: float, alpha: float = 0.05,
                        power: float = 0.80) -> int:
    """Users needed in EACH arm to detect an absolute lift in a conversion rate.

    Two-sided test, 50/50 split. `lift` is absolute: 0.02 means 18.1% -> 20.1%.
    """
    target = baseline + lift
    if not 0 < baseline < 1 or not 0 < target < 1:
        raise ValueError(f"rates must be in (0, 1): {baseline} -> {target}")
    h = abs(cohens_h(baseline, target))
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(power)
    return math.ceil(2 * ((z_alpha + z_power) / h) ** 2)


def days_to_run(n_per_arm: int, eligible_per_day: float, arms: int = 2) -> float:
    """Calendar days to reach `n_per_arm` users in every arm at the current traffic."""
    return (n_per_arm * arms) / eligible_per_day if eligible_per_day else math.inf


def planned_days(raw_days: float) -> int:
    """Round up to whole weeks, never below MIN_DAYS."""
    return max(MIN_DAYS, int(math.ceil(raw_days / 7) * 7))


@dataclass
class TestPlan:
    step_from: str
    step_to: str
    primary_metric: str
    baseline: float
    eligible_per_day: float
    smallest_detectable_lift: float | None
    planned_days: int | None
    n_per_arm: int | None
    guardrails: list[dict] = field(default_factory=list)
    grid: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def guardrails_for(row: pd.Series, step_to: str, aov: float) -> list[dict]:
    """What must NOT get worse while the primary metric is being moved.

    Pushing more marginal shoppers through one step tends to lower conversion at the
    next — the same reason every sizing figure is an upper bound — so the step after
    the one being tested is always a guardrail. AOV guards against a fix that converts
    more people into smaller baskets.
    """
    out = []
    idx = FUNNEL_STAGES.index(step_to)
    if idx + 1 < len(FUNNEL_STAGES):
        nxt = FUNNEL_STAGES[idx + 1]
        rate = float(row[nxt]) / float(row[step_to]) if row[step_to] else 0.0
        out.append({
            "metric": f"{STAGE_LABELS[step_to]} → {STAGE_LABELS[nxt].lower()} rate",
            "baseline": rate,
            "rule": "must not fall",
            "why": "the extra shoppers this step lets through are the least committed",
        })
    out.append({
        "metric": "Average order value",
        "baseline": aov,
        "rule": "must not fall",
        "why": "more orders into smaller baskets is not a win",
    })
    return out


def plan_for_step(row: pd.Series, step_to: str, aov: float, window_days: int,
                  alpha: float = 0.05, power: float = 0.80,
                  lifts: tuple[float, ...] = LIFT_GRID) -> TestPlan:
    """A complete test plan for raising one funnel step's conversion rate.

    The grid is precomputed here, so the report's interactive planner only looks values
    up — the browser never does the arithmetic.
    """
    t = next(x for x in transitions(row) if x.to_stage == step_to)
    eligible_per_day = t.entered / window_days if window_days else 0.0

    grid = []
    for lift in lifts:
        if t.step_conversion + lift >= 1:
            continue
        n = sample_size_per_arm(t.step_conversion, lift, alpha, power)
        raw = days_to_run(n, eligible_per_day)
        grid.append({
            "lift": lift,
            "n_per_arm": n,
            "days": raw,
            "planned_days": planned_days(raw),
            "fits": raw <= MAX_DAYS,
            "worth_up_to": size_stage(row, t, aov, improvement_pp=lift).recoverable_revenue,
        })

    feasible = [g for g in grid if g["fits"]]
    best = feasible[0] if feasible else None
    return TestPlan(
        step_from=t.from_stage,
        step_to=step_to,
        primary_metric=f"{STAGE_LABELS[t.from_stage]} → {STAGE_LABELS[step_to].lower()} rate",
        baseline=t.step_conversion,
        eligible_per_day=eligible_per_day,
        smallest_detectable_lift=best["lift"] if best else None,
        planned_days=best["planned_days"] if best else None,
        n_per_arm=best["n_per_arm"] if best else None,
        guardrails=guardrails_for(row, step_to, aov),
        grid=grid,
    )
