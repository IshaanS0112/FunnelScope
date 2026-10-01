"""Funnel arithmetic and the correctness gate that guards it."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import FUNNEL_STAGES


class FunnelValidationError(AssertionError):
    """Raised when a funnel violates an invariant that must hold by construction."""


def check_monotonic(df: pd.DataFrame) -> None:
    """Each stage must be a subset of the one before it, in every row.

    A violation means the SQL's ordering predicates are not cumulative — the most
    common way a funnel query is silently wrong.
    """
    for i in range(1, len(FUNNEL_STAGES)):
        prev, curr = FUNNEL_STAGES[i - 1], FUNNEL_STAGES[i]
        bad = df[df[curr] > df[prev]]
        if not bad.empty:
            rows = bad[["segment_value", prev, curr]].to_dict("records")
            raise FunnelValidationError(
                f"Funnel is not monotonic: '{curr}' exceeds '{prev}' in {len(bad)} row(s). "
                f"The stage predicates are not cumulative. Offending rows: {rows[:5]}"
            )


def cross_validate(primary: pd.DataFrame, secondary: pd.DataFrame,
                   tolerance: float = 0.005) -> pd.DataFrame:
    """Compare the timestamp funnel against the sequence-regex funnel.

    The funnel logic is independent, so a non-cumulative predicate cannot survive the
    comparison. Both methods use the same tie rule, so any drift above `tolerance` is
    a bug. See docs/methodology.md for the two divergences this caught.
    """
    rows = []
    for stage in FUNNEL_STAGES:
        a = int(primary[stage].iloc[0])
        b = int(secondary[stage].iloc[0])
        denom = max(a, b, 1)
        rel = abs(a - b) / denom
        rows.append({
            "stage": stage,
            "method_a_timestamps": a,
            "method_b_sequence": b,
            "abs_diff": abs(a - b),
            "rel_diff": rel,
            "within_tolerance": rel <= tolerance,
        })
    result = pd.DataFrame(rows)
    failures = result[~result["within_tolerance"]]
    if not failures.empty:
        raise FunnelValidationError(
            "Two independent funnel implementations disagree beyond "
            f"{tolerance:.1%}:\n{failures.to_string(index=False)}\n"
            "Do not publish these numbers. Fix the SQL first."
        )
    return result


@dataclass
class StageTransition:
    """One step of the funnel: who entered, who continued, who was lost."""

    from_stage: str
    to_stage: str
    entered: int
    completed: int

    @property
    def lost(self) -> int:
        return self.entered - self.completed

    @property
    def step_conversion(self) -> float:
        return self.completed / self.entered if self.entered else 0.0

    @property
    def drop_off(self) -> float:
        return 1.0 - self.step_conversion


def transitions(row: pd.Series) -> list[StageTransition]:
    """Break one funnel row into its stage-to-stage transitions."""
    out = []
    for i in range(1, len(FUNNEL_STAGES)):
        prev, curr = FUNNEL_STAGES[i - 1], FUNNEL_STAGES[i]
        out.append(StageTransition(prev, curr, int(row[prev]), int(row[curr])))
    return out


def with_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Add step conversion, cumulative conversion and drop-off columns."""
    out = df.copy()
    top = out[FUNNEL_STAGES[0]].replace(0, pd.NA)
    for i, stage in enumerate(FUNNEL_STAGES):
        out[f"cum_conv_{stage}"] = out[stage] / top
        if i:
            prev = FUNNEL_STAGES[i - 1]
            denom = out[prev].replace(0, pd.NA)
            out[f"step_conv_{stage}"] = out[stage] / denom
            out[f"lost_at_{prev}"] = out[prev] - out[stage]
    return out


def worst_step(row: pd.Series) -> StageTransition:
    """The transition with the steepest percentage drop-off.

    Same stage as the largest recoverable revenue, always — see sizing.py. Rate and
    dollars are one fact, not two.
    """
    return min(transitions(row), key=lambda t: t.step_conversion)


def session_gap(user_row: pd.Series, session_row: pd.Series) -> dict:
    """Compare the user-scoped funnel against the session-scoped one.

    Session conversion cannot exceed user conversion — a user converts if any of their
    sessions does — so that inequality is checked, not assumed. The gap measures how
    much of the funnel depends on people coming back.
    """
    u_view, u_buy = float(user_row["viewed"]), float(user_row["purchased"])
    s_view, s_buy = float(session_row["viewed"]), float(session_row["purchased"])
    user_conv = u_buy / u_view if u_view else 0.0
    session_conv = s_buy / s_view if s_view else 0.0

    if session_conv > user_conv + 1e-12:
        raise FunnelValidationError(
            f"Session-scoped conversion ({session_conv:.4%}) exceeds user-scoped "
            f"({user_conv:.4%}). That is impossible — a user converts if any of their "
            f"sessions does — so one of the two funnel queries is wrong."
        )

    share = session_conv / user_conv if user_conv else 0.0
    return {
        "user_conversion": user_conv,
        "session_conversion": session_conv,
        "gap_pp": (user_conv - session_conv) * 100,
        "session_share_of_user_conversion": share,
        "return_visit_dependence": 1 - share,
        "sessions_per_viewing_user": s_view / u_view if u_view else 0.0,
    }
