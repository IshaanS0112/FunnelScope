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
