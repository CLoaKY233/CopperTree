"""
Statistical gate for prompt promotion decisions.

Uses bootstrap confidence intervals on paired score deltas.
A candidate prompt is only promoted if:
  1. 100% compliance pass rate (zero violations in all conversations)
  2. The 95% CI lower bound of paired deltas is strictly > 0
     (i.e., improvement is statistically significant, not noise)
"""

import random


def bootstrap_ci(
    data: list[float],
    n_bootstrap: int = 1000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval for the mean of `data`.
    Returns (lower_bound, upper_bound) at the given confidence level.
    """
    if not data:
        return (0.0, 0.0)

    n = len(data)
    boot_means = []
    for _ in range(n_bootstrap):
        resample = [random.choice(data) for _ in range(n)]
        boot_means.append(sum(resample) / n)

    boot_means.sort()
    alpha = (1.0 - ci) / 2.0
    lower_idx = int(alpha * n_bootstrap)
    upper_idx = int((1.0 - alpha) * n_bootstrap) - 1
    return (boot_means[lower_idx], boot_means[upper_idx])


def should_promote(
    baseline_scores: list[float],
    candidate_scores: list[float],
    candidate_compliance_rate: float,
) -> tuple[bool, str]:
    """
    Decide whether to promote a candidate prompt over the baseline.

    Args:
        baseline_scores: composite scores from baseline eval (one per conversation)
        candidate_scores: composite scores from candidate eval (same seeds, paired)
        candidate_compliance_rate: fraction of candidate conversations with no compliance violation
                                   (i.e., composite > 0.0 — since 0.0 means hard gate triggered)

    Returns:
        (should_promote: bool, reason: str) with detailed numbers in the reason string.
    """
    if len(baseline_scores) != len(candidate_scores):
        return False, (
            f"Score list length mismatch: baseline={len(baseline_scores)}, "
            f"candidate={len(candidate_scores)}. Cannot do paired comparison."
        )

    # Hard rule 1: 100% compliance required
    if candidate_compliance_rate < 1.0:
        failing = sum(1 for s in candidate_scores if s == 0.0)
        return False, (
            f"Compliance gate failed: {failing}/{len(candidate_scores)} conversations had "
            f"compliance violations (compliance_pass_rate={candidate_compliance_rate:.1%}). "
            "All conversations must pass compliance to be eligible for promotion."
        )

    baseline_mean = sum(baseline_scores) / len(baseline_scores)
    candidate_mean = sum(candidate_scores) / len(candidate_scores)

    # Paired deltas
    deltas = [c - b for c, b in zip(candidate_scores, baseline_scores)]
    delta_mean = sum(deltas) / len(deltas)
    ci_lower, ci_upper = bootstrap_ci(deltas)

    # Hard rule 2: improvement must be statistically significant
    if ci_lower <= 0.0:
        return False, (
            f"Improvement not statistically significant. "
            f"Baseline mean={baseline_mean:.4f}, candidate mean={candidate_mean:.4f}, "
            f"delta mean={delta_mean:+.4f}, 95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}]. "
            f"CI lower bound must be > 0 for promotion."
        )

    return True, (
        f"Promoted: baseline mean={baseline_mean:.4f}, candidate mean={candidate_mean:.4f}, "
        f"delta mean={delta_mean:+.4f}, 95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}], "
        f"compliance_pass_rate={candidate_compliance_rate:.1%}."
    )
