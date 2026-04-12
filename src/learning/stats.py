"""
Statistical gate for prompt promotion decisions.

Uses three statistical tests:
  1. Wilcoxon signed-rank (paired): primary test for composite improvement
  2. Wilcoxon signed-rank (paired): compliance must not regress
  3. Bootstrap CI (10,000 resamples): confirm improvement CI lower bound > 0

Promotion requires ALL of:
  - 100% compliance pass rate (zero hard-gate violations)
  - Compliance dimension did not regress (Wilcoxon one-sided, p >= alpha)
  - Composite improvement is significant (Wilcoxon one-sided, p < alpha)
  - Bootstrap 95% CI lower bound of paired deltas > 0
"""

from __future__ import annotations

import random


def bootstrap_ci(
    data: list[float],
    n_bootstrap: int = 10_000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval for the mean of `data`.
    Returns (lower_bound, upper_bound) at the given confidence level.
    Uses 10,000 resamples for tight bounds.
    """
    if not data:
        return (0.0, 0.0)

    n = len(data)
    boot_means = sorted(sum(random.choices(data, k=n)) / n for _ in range(n_bootstrap))
    alpha = (1.0 - ci) / 2.0
    lower_idx = int(alpha * n_bootstrap)
    upper_idx = int((1.0 - alpha) * n_bootstrap) - 1
    return (boot_means[lower_idx], boot_means[upper_idx])


def _wilcoxon_pvalue(
    x: list[float], y: list[float], alternative: str = "greater"
) -> float:
    """
    Non-parametric Wilcoxon signed-rank test on paired data.
    alternative: "greater" tests x > y, "less" tests x < y.
    Returns p-value (float).
    Falls back to bootstrap-based heuristic if scipy unavailable.
    """
    try:
        from scipy.stats import wilcoxon

        if len(x) < 2:
            return 1.0
        # Compute differences
        diffs = [xi - yi for xi, yi in zip(x, y)]
        # Remove ties (zero differences)
        diffs = [d for d in diffs if d != 0]
        if not diffs:
            return 1.0
        _, p = wilcoxon(diffs, alternative=alternative)
        return float(p)
    except ImportError:
        # Fallback: bootstrap-based p-value estimate
        return _bootstrap_pvalue(x, y, alternative)


def _bootstrap_pvalue(x: list[float], y: list[float], alternative: str) -> float:
    """Fallback bootstrap-based p-value when scipy unavailable."""
    deltas = [xi - yi for xi, yi in zip(x, y)]
    observed_mean = sum(deltas) / len(deltas) if deltas else 0.0
    # Permutation test
    n_perm = 5000
    count_extreme = 0
    for _ in range(n_perm):
        perm = [d * random.choice([-1, 1]) for d in deltas]
        perm_mean = sum(perm) / len(perm)
        if alternative == "greater" and perm_mean >= observed_mean:
            count_extreme += 1
        elif alternative == "less" and perm_mean <= observed_mean:
            count_extreme += 1
    return count_extreme / n_perm


def should_promote(
    baseline_scores: list[float],
    candidate_scores: list[float],
    candidate_compliance_rate: float,
    baseline_compliance_scores: list[float] | None = None,
    candidate_compliance_scores: list[float] | None = None,
    alpha: float = 0.05,
) -> tuple[bool, str, dict]:
    """
    Decide whether to promote a candidate prompt over the baseline.

    Args:
        baseline_scores: composite scores from baseline eval (one per conversation)
        candidate_scores: composite scores from candidate eval (same seeds, paired)
        candidate_compliance_rate: fraction of candidate conversations with composite > 0
        baseline_compliance_scores: per-conversation compliance dimension scores (optional)
        candidate_compliance_scores: per-conversation compliance dimension scores (optional)
        alpha: significance level for statistical tests (default 0.05)

    Returns:
        (should_promote: bool, reason: str)
    """
    gate: dict = {
        "gate1_pass": None,
        "gate2_pass": None,
        "gate2_p": None,
        "gate3_pass": None,
        "gate3_p": None,
        "gate4_pass": None,
        "gate4_ci_lower": None,
        "gate4_ci_upper": None,
    }

    if len(baseline_scores) != len(candidate_scores):
        return (
            False,
            (
                f"Score list length mismatch: baseline={len(baseline_scores)}, "
                f"candidate={len(candidate_scores)}. Cannot do paired comparison."
            ),
            gate,
        )

    n = len(baseline_scores)

    # Hard rule 1: 100% compliance pass rate
    gate["gate1_pass"] = candidate_compliance_rate >= 1.0
    if not gate["gate1_pass"]:
        failing = sum(1 for s in candidate_scores if s == 0.0)
        return (
            False,
            (
                f"Compliance gate failed: {failing}/{n} conversations had hard-gate violations "
                f"(compliance_pass_rate={candidate_compliance_rate:.1%}). "
                "All conversations must pass to be eligible for promotion."
            ),
            gate,
        )

    baseline_mean = sum(baseline_scores) / n
    candidate_mean = sum(candidate_scores) / n
    deltas = [c - b for c, b in zip(candidate_scores, baseline_scores)]
    delta_mean = sum(deltas) / len(deltas)

    # Rule 2: Compliance dimension must not regress (Wilcoxon one-sided: candidate < baseline = bad)
    compliance_regress_p = None
    if (
        baseline_compliance_scores
        and candidate_compliance_scores
        and len(baseline_compliance_scores) == n
    ):
        compliance_regress_p = _wilcoxon_pvalue(
            candidate_compliance_scores, baseline_compliance_scores, alternative="less"
        )
        gate["gate2_p"] = compliance_regress_p
        gate["gate2_pass"] = compliance_regress_p >= alpha
        if not gate["gate2_pass"]:
            return (
                False,
                (
                    f"Compliance dimension regressed (Wilcoxon p={compliance_regress_p:.3f} < {alpha}). "
                    f"Candidate compliance scores are significantly lower than baseline. "
                    "Compliance must not regress."
                ),
                gate,
            )
    else:
        gate["gate2_pass"] = True  # no compliance data, skip

    # Rule 3: Composite improvement must be statistically significant (Wilcoxon)
    wilcoxon_p = _wilcoxon_pvalue(
        candidate_scores, baseline_scores, alternative="greater"
    )
    gate["gate3_p"] = wilcoxon_p
    gate["gate3_pass"] = wilcoxon_p < alpha
    if not gate["gate3_pass"]:
        return (
            False,
            (
                f"Improvement not statistically significant by Wilcoxon test "
                f"(p={wilcoxon_p:.3f} >= alpha={alpha}). "
                f"Baseline mean={baseline_mean:.4f}, candidate mean={candidate_mean:.4f}, "
                f"delta mean={delta_mean:+.4f}."
            ),
            gate,
        )

    # Rule 4: Bootstrap CI lower bound > 0
    ci_lower, ci_upper = bootstrap_ci(deltas)
    gate["gate4_ci_lower"] = ci_lower
    gate["gate4_ci_upper"] = ci_upper
    gate["gate4_pass"] = ci_lower > 0.0
    if not gate["gate4_pass"]:
        return (
            False,
            (
                f"Bootstrap CI includes zero (CI=[{ci_lower:+.4f}, {ci_upper:+.4f}]). "
                f"Improvement not reliably above noise. "
                f"Baseline mean={baseline_mean:.4f}, candidate mean={candidate_mean:.4f}."
            ),
            gate,
        )

    return (
        True,
        (
            f"Promoted: baseline mean={baseline_mean:.4f}, candidate mean={candidate_mean:.4f}, "
            f"delta mean={delta_mean:+.4f}, "
            f"Wilcoxon p={wilcoxon_p:.4f}, "
            f"95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}], "
            f"compliance_pass_rate={candidate_compliance_rate:.1%}."
        ),
        gate,
    )
