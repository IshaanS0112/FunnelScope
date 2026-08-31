"""Opportunity sizing: converting a drop-off into a defensible revenue number.

The model, stated plainly so it can be argued with:

    users_recovered(S, x) = min(users_entering_S x x, users_lost_at_S)
    recoverable(S, x)     = users_recovered x P(purchase | completed S) x AOV

Each term is an assumption, and each is wrong in a knowable direction:

  * users_entering_S / users_lost_at_S -- measured, not assumed.
  * x (improvement)          -- chosen, not derived. There is no engineering estimate
                                behind it. It is a sensitivity input, which is why
                                `sensitivity_table` sweeps it rather than fixing a value.
  * P(purchase | completed)  -- measured on users who DID complete the stage. Applying
                                it to users who did not is the load-bearing assumption
                                of the whole model: it treats recovered users as
                                behaving like already-converting users. They almost
                                certainly convert worse. Every figure here is an
                                UPPER BOUND, and should be presented as one.
  * AOV                      -- transaction-weighted from actual purchase revenue.

TWO THINGS THIS MODULE GETS RIGHT THAT THE STANDARD FORMULATION DOES NOT
-----------------------------------------------------------------------

**1. `users_lost x x` is the wrong denominator.**
The usual write-up is `users_lost x improvement_pp x downstream x AOV`. But a
percentage-point improvement is a change in the stage's *conversion rate*, and that
rate's denominator is users *entering*, not users *lost*. Raising a 30% step to 35%
recovers `users_entering x 0.05`, not `users_lost x 0.05`. The two differ by a factor
of `1 / (1 - rate)` -- 43% too low at a 30% step, and worse the higher the rate.
`basis="lost"` is available for the other reading ("we recover x of the users we
lose"), but it is a different claim and is labelled as one.

**2. This model cannot re-rank the stages, and pretending otherwise is a mistake.**
A common claim about opportunity sizing is that the stage with the largest absolute
recoverable revenue is usually *not* the stage with the worst percentage drop-off, and
that the gap between the two is the interesting finding. In a strictly ordered funnel
that gap cannot exist. Every purchaser passed through every stage, so

    P(purchase | completed stage j) = total_purchases / count_j

with `total_purchases` constant across stages. Therefore

    recoverable_i  proportional to  count_i / count_j  =  1 / step_conversion_i

which is strictly monotone in the step conversion rate. Ranking by recoverable revenue
and ranking by worst step conversion are the *same ordering*, necessarily, for every
funnel. `ranking_matches_step_conversion()` asserts this, and a test in
tests/test_sizing_and_rice.py checks it over thousands of random funnels.

So what is sizing for? Two things, neither of which is re-ranking stages:
  * it converts a rate into a currency figure that can be weighed against *effort*,
    which is where the real re-ranking happens (see funnelscope/rice.py); and
  * across *segments* at the same stage it does carry independent information, because
    traffic volume and downstream conversion vary between segments in ways step
    conversion alone does not capture. `segment_gap_value` is where that lives.
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
    """Size one transition.

    `improvement_pp` is a fraction (0.05 = 5 percentage points).
    `basis` selects what those percentage points apply to:
      "entering" -- the stage's conversion rate rises by `improvement_pp`. Correct
                    reading of "improve stage S conversion by X pp". Default.
      "lost"     -- `improvement_pp` of the users lost at this stage are recovered.
                    A different, weaker claim. Available for comparison, labelled.
    Recovery is capped at the number of users actually lost: you cannot recover more
    users than left.
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

    Publishing the sweep instead of one number is the point: it shows the ranking of
    stages is stable even though the absolute figures are not.
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
    """What closing the end-to-end conversion gap between two segments would be worth.

    Counterfactual: segment A converts at segment B's rate, holding A's traffic fixed.
    Also an upper bound, and for the same reason as above.
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
    """True when ranking stages by recoverable revenue equals ranking by worst step rate.

    Proved above to hold for every strictly ordered funnel. Exposed as a callable so the
    property is asserted by the test suite rather than only asserted in a docstring, and
    so a future change to the model that breaks the equivalence fails loudly.
    """
    sized = size_all_stages(row, aov, improvement_pp)
    by_revenue = list(sized.sort_values("recoverable_revenue", ascending=False)["to_stage"])
    by_rate = list(sized.sort_values("step_conversion")["to_stage"])
    return by_revenue == by_rate
