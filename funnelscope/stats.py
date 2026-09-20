"""Significance testing for segment comparisons.

A two-proportion z-test is the whole content of this module, but it is the piece most
portfolio funnel analyses omit, and omitting it is what lets a 0.3pp difference get
written up as a finding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Normal CDF via the error function -- avoids a SciPy dependency for one lookup.
def _norm_sf(z: float) -> float:
    """Upper-tail probability of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


@dataclass
class ProportionTest:
    label_a: str
    label_b: str
    successes_a: int
    trials_a: int
    successes_b: int
    trials_b: int
    alpha: float = 0.05

    @property
    def p_a(self) -> float:
        return self.successes_a / self.trials_a if self.trials_a else 0.0

    @property
    def p_b(self) -> float:
        return self.successes_b / self.trials_b if self.trials_b else 0.0

    @property
    def difference(self) -> float:
        """Percentage-point difference, a minus b."""
        return self.p_a - self.p_b

    @property
    def z(self) -> float:
        """Pooled two-proportion z statistic."""
        n_a, n_b = self.trials_a, self.trials_b
        if not n_a or not n_b:
            return 0.0
        pooled = (self.successes_a + self.successes_b) / (n_a + n_b)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
        return (self.p_a - self.p_b) / se if se else 0.0

    @property
    def p_value(self) -> float:
        """Two-sided."""
        return 2.0 * _norm_sf(abs(self.z))

    @property
    def significant(self) -> bool:
        return self.p_value < self.alpha

    def confidence_interval(self, z_crit: float = 1.959964) -> tuple[float, float]:
        """Unpooled Wald interval on the difference in proportions."""
        n_a, n_b = self.trials_a, self.trials_b
        if not n_a or not n_b:
            return (0.0, 0.0)
        se = math.sqrt(self.p_a * (1 - self.p_a) / n_a + self.p_b * (1 - self.p_b) / n_b)
        d = self.difference
        return (d - z_crit * se, d + z_crit * se)

    def verdict(self) -> str:
        """One sentence, written the way it would appear in the memo."""
        lo, hi = self.confidence_interval()
        direction = "higher" if self.difference > 0 else "lower"
        if self.significant:
            return (
                f"{self.label_a} converts {abs(self.difference) * 100:.2f}pp {direction} "
                f"than {self.label_b} ({self.p_a * 100:.2f}% vs {self.p_b * 100:.2f}%). "
                f"z = {self.z:.2f}, p = {self.p_value:.2e}, 95% CI "
                f"[{lo * 100:+.2f}, {hi * 100:+.2f}]pp. Real, not sampling noise."
            )
        return (
            f"{self.label_a} vs {self.label_b}: {self.p_a * 100:.2f}% vs "
            f"{self.p_b * 100:.2f}% (difference {self.difference * 100:+.2f}pp). "
            f"z = {self.z:.2f}, p = {self.p_value:.3f}, 95% CI "
            f"[{lo * 100:+.2f}, {hi * 100:+.2f}]pp. Not distinguishable from noise "
            f"at this sample size — do not act on it."
        )

    def to_dict(self) -> dict:
        lo, hi = self.confidence_interval()
        return {
            "comparison": f"{self.label_a} vs {self.label_b}",
            "rate_a": self.p_a,
            "rate_b": self.p_b,
            "difference_pp": self.difference * 100,
            "z": self.z,
            "p_value": self.p_value,
            "ci_low_pp": lo * 100,
            "ci_high_pp": hi * 100,
            "significant": self.significant,
            "verdict": self.verdict(),
        }


# ---------------------------------------------------------------------------
# Multiple comparisons
# ---------------------------------------------------------------------------
# Running several segment comparisons at alpha = 0.05 each does not hold the
# family-wise error rate at 0.05. With m independent tests the probability of at
# least one false positive is 1 - (1 - alpha)^m: four comparisons is already 18.5%.
# An analysis that cuts a funnel four ways and reports whatever came back significant
# is therefore manufacturing findings at a rate it has not disclosed.
#
# Holm-Bonferroni is used rather than plain Bonferroni because it is uniformly more
# powerful and costs nothing: same assumptions, same guarantee, strictly more rejections.

def holm_bonferroni(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Holm-Bonferroni step-down. Returns one reject/keep decision per input p-value.

    Sort the p-values ascending. The k-th smallest is compared against
    `alpha / (m - k)`. The procedure stops at the first failure: every remaining
    hypothesis is retained, whatever its own p-value. That step-down stop is the
    whole difference from Bonferroni, and forgetting it is the usual implementation
    bug -- it turns a valid procedure into an invalid, more powerful one.

    Results are returned in the caller's original order, not in sorted order.
    """
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        if p_values[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            break
    return reject


def adjusted_p_values(p_values: list[float]) -> list[float]:
    """Holm-adjusted p-values: `min(1, max over the step-down prefix of (m-k) * p_k)`.

    The running maximum enforces monotonicity -- an adjusted p-value can never be
    smaller than that of a more significant hypothesis. Reporting these alongside the
    raw values lets a reader see exactly how much the correction cost, which is the
    honest way to present it.
    """
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    out = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p_values[i])
        out[i] = min(1.0, running)
    return out


def correct_family(tests: list[ProportionTest], alpha: float = 0.05) -> list[dict]:
    """Apply Holm across a family of comparisons and return them fully annotated.

    Every comparison the pipeline runs belongs to one family. The corrected verdict,
    not the raw one, is what the memo is allowed to quote.
    """
    raw = [t.p_value for t in tests]
    rejects = holm_bonferroni(raw, alpha)
    adjusted = adjusted_p_values(raw)
    out = []
    for t, rej, adj in zip(tests, rejects, adjusted):
        d = t.to_dict()
        d["p_value_adjusted"] = adj
        d["significant_raw"] = d["significant"]
        d["significant_holm"] = bool(rej)
        d["significant"] = bool(rej)          # the corrected verdict is THE verdict
        d["family_size"] = len(tests)
        d["correction"] = "Holm-Bonferroni"
        if d["significant_raw"] and not rej:
            d["verdict"] += (
                f" Survives at alpha = {alpha} alone but NOT after Holm correction "
                f"across {len(tests)} comparisons (adjusted p = {adj:.3f}) — "
                f"treat as unproven.")
        elif rej:
            d["verdict"] += (
                f" Holds after Holm correction across {len(tests)} comparisons "
                f"(adjusted p = {adj:.2e}).")
        out.append(d)
    return out
