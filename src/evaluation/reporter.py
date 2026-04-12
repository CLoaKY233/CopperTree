"""
Evolution report generator for CopperTree learning loop.

Reads from MongoDB: learning_iterations, eval_runs, prompt_versions.
Generates a comprehensive report showing prompt improvement history,
score trajectories, compliance preservation, and cost breakdown.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.llm.cost_tracker import get_total_spend
from src.storage.mongo import _get_db


@dataclass
class IterationSummary:
    iteration_num: int
    baseline_version: str
    candidate_version: str
    baseline_run_id: str
    candidate_run_id: str
    decision: str  # "promoted" | "rejected"
    reason: str
    baseline_mean: float
    baseline_std: float
    candidate_mean: float
    candidate_std: float
    delta: float
    baseline_compliance: float
    candidate_compliance: float
    change_description: str = ""  # from proposer
    seed: int = 42
    n_conversations: int = 0
    # Statistical analysis
    wilcoxon_p_value: Optional[float] = None
    bootstrap_ci_lower: Optional[float] = None
    bootstrap_ci_upper: Optional[float] = None
    per_persona_deltas: dict = field(default_factory=dict)
    # Raw per-conversation scores (populated when include_raw=True)
    baseline_conversations: list[dict] = field(default_factory=list)
    candidate_conversations: list[dict] = field(default_factory=list)


@dataclass
class EvolutionReport:
    agent_name: str
    generated_at: str
    current_version: str
    initial_version: str
    n_iterations: int
    n_promoted: int
    iterations: list[IterationSummary] = field(default_factory=list)
    score_trajectory: list[dict] = field(default_factory=list)
    prompt_diff: str = ""
    compliance_preserved: bool = True
    cost_breakdown: dict = field(default_factory=dict)
    persona_trends: dict = field(default_factory=dict)


def _extract_wilcoxon_and_ci(
    reason: str,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Parse Wilcoxon p and bootstrap CI from the reason string."""
    import re

    wilcoxon_p = None
    ci_lower = None
    ci_upper = None
    m = re.search(r"Wilcoxon p=([\d.]+)", reason)
    if m:
        wilcoxon_p = float(m.group(1))
    m = re.search(r"CI=\[([-+]?[\d.]+),\s*([-+]?[\d.]+)\]", reason)
    if m:
        ci_lower = float(m.group(1))
        ci_upper = float(m.group(2))
    # Also check "p=([\d.]+)" pattern used in rejection messages
    if wilcoxon_p is None:
        m = re.search(r"p=([\d.]+)", reason)
        if m:
            wilcoxon_p = float(m.group(1))
    return wilcoxon_p, ci_lower, ci_upper


class EvolutionReporter:
    """Generates evolution reports from MongoDB learning history."""

    def generate(self, agent_name: str, include_raw: bool = False) -> EvolutionReport:
        db = _get_db()
        iterations_col = db["learning_iterations"]
        eval_runs_col = db["eval_runs"]
        eval_conversations_col = db["eval_conversations"]
        prompt_versions_col = db["prompt_versions"]

        # Load all iterations for this agent (chronological)
        raw_iterations = list(
            iterations_col.find({"agent": agent_name}).sort("created_at", 1)
        )

        # Load all prompt versions for this agent
        versions = {
            v["_id"]: v for v in prompt_versions_col.find({"agent": agent_name})
        }

        # Current version
        current_doc = prompt_versions_col.find_one(
            {"agent": agent_name, "is_current": True}
        )
        current_version = current_doc["_id"] if current_doc else "unknown"

        # Initial version (lowest version number)
        sorted_versions = sorted(versions.values(), key=lambda v: v.get("version", 0))
        initial_version = sorted_versions[0]["_id"] if sorted_versions else "unknown"

        def _load_run_conversations(run_id: str) -> list[dict]:
            """Load per-conversation records for a given run_id."""
            if not run_id:
                return []
            try:
                docs = list(eval_conversations_col.find({"run_id": run_id}))
                # Remove MongoDB _id field (not JSON-serializable by default)
                for doc in docs:
                    doc.pop("_id", None)
                return docs
            except Exception:
                return []

        def _std_from_conversations(convs: list[dict]) -> float:
            scores = [c.get("scores", {}).get("composite", 0.0) for c in convs]
            if not scores:
                return 0.0
            mean = sum(scores) / len(scores)
            return (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5

        def _persona_deltas(
            baseline_convs: list[dict], candidate_convs: list[dict]
        ) -> dict:
            """Compute per-persona score deltas between baseline and candidate."""
            baseline_by_persona: dict[str, list[float]] = {}
            candidate_by_persona: dict[str, list[float]] = {}
            for conv in baseline_convs:
                p = conv.get("persona", "unknown")
                score = conv.get("scores", {}).get("composite", 0.0)
                baseline_by_persona.setdefault(p, []).append(score)
            for conv in candidate_convs:
                p = conv.get("persona", "unknown")
                score = conv.get("scores", {}).get("composite", 0.0)
                candidate_by_persona.setdefault(p, []).append(score)
            result = {}
            all_personas = set(baseline_by_persona) | set(candidate_by_persona)
            for persona in all_personas:
                b_scores = baseline_by_persona.get(persona, [])
                c_scores = candidate_by_persona.get(persona, [])
                b_mean = sum(b_scores) / len(b_scores) if b_scores else 0.0
                c_mean = sum(c_scores) / len(c_scores) if c_scores else 0.0
                result[persona] = {
                    "baseline": round(b_mean, 4),
                    "candidate": round(c_mean, 4),
                    "delta": round(c_mean - b_mean, 4),
                }
            return result

        # Build iteration summaries
        summaries: list[IterationSummary] = []
        for i, raw in enumerate(raw_iterations):
            candidate_v = raw.get("candidate_version", "")
            baseline_v = raw.get("baseline_version", "")
            candidate_doc = versions.get(candidate_v, {})
            baseline_run_id = raw.get("baseline_run_id", "")
            candidate_run_id = raw.get("candidate_run_id", "")
            reason = raw.get("reason", "")
            wilcoxon_p, ci_lower, ci_upper = _extract_wilcoxon_and_ci(reason)

            baseline_convs: list[dict] = []
            candidate_convs: list[dict] = []
            if include_raw:
                baseline_convs = _load_run_conversations(baseline_run_id)
                candidate_convs = _load_run_conversations(candidate_run_id)

            # std from conversations if available, else estimate from mongo
            baseline_std = (
                _std_from_conversations(baseline_convs) if baseline_convs else 0.0
            )
            candidate_std = (
                _std_from_conversations(candidate_convs) if candidate_convs else 0.0
            )

            per_persona = (
                _persona_deltas(baseline_convs, candidate_convs)
                if (baseline_convs or candidate_convs)
                else {}
            )

            summaries.append(
                IterationSummary(
                    iteration_num=i + 1,
                    baseline_version=baseline_v,
                    candidate_version=candidate_v,
                    baseline_run_id=baseline_run_id,
                    candidate_run_id=candidate_run_id,
                    decision=raw.get("decision", "unknown"),
                    reason=reason,
                    baseline_mean=raw.get("baseline_mean", 0.0),
                    baseline_std=baseline_std,
                    candidate_mean=raw.get("candidate_mean", 0.0),
                    candidate_std=candidate_std,
                    delta=raw.get("delta_mean", 0.0),
                    baseline_compliance=raw.get("baseline_compliance_rate", 0.0),
                    candidate_compliance=raw.get("candidate_compliance_rate", 0.0),
                    change_description=candidate_doc.get("change_description", ""),
                    seed=raw.get("seed", 42),
                    n_conversations=raw.get("n_conversations", 0),
                    wilcoxon_p_value=wilcoxon_p,
                    bootstrap_ci_lower=ci_lower,
                    bootstrap_ci_upper=ci_upper,
                    per_persona_deltas=per_persona,
                    baseline_conversations=baseline_convs,
                    candidate_conversations=candidate_convs,
                )
            )

        # Score trajectory — one entry per promoted version
        trajectory = []
        for v in sorted_versions:
            # Find the eval_run that evaluated this version
            run = eval_runs_col.find_one(
                {"prompt_version_id": v["_id"], "agent_name": agent_name},
                sort=[("created_at", 1)],
            )
            if run:
                trajectory.append(
                    {
                        "version": v["_id"],
                        "is_current": v.get("is_current", False),
                        "composite_mean": run.get("composite_mean", 0.0),
                        "compliance_pass_rate": run.get("compliance_pass_rate", 0.0),
                        "n_conversations": run.get("n_conversations", 0),
                        "change_description": v.get("change_description", "—"),
                    }
                )

        # Prompt diff: initial vs current
        initial_text = (
            sorted_versions[0].get("prompt_text", "") if sorted_versions else ""
        )
        current_text = current_doc.get("prompt_text", "") if current_doc else ""
        diff_lines = list(
            difflib.unified_diff(
                initial_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile=f"{initial_version} (initial)",
                tofile=f"{current_version} (current)",
            )
        )
        prompt_diff = "".join(diff_lines) if diff_lines else "(no changes)"

        # Compliance preservation: check no promoted version has compliance < initial
        initial_compliance = (
            trajectory[0]["compliance_pass_rate"] if trajectory else 1.0
        )
        promoted_summaries = [s for s in summaries if s.decision == "promoted"]
        compliance_preserved = all(
            s.candidate_compliance >= initial_compliance * 0.95  # 5% tolerance
            for s in promoted_summaries
        )

        # Cost breakdown
        cost_breakdown = get_total_spend()
        cost_breakdown["total"] = sum(cost_breakdown.values())

        # Per-persona trends (from eval_runs for promoted versions)
        persona_trends: dict = {}
        promoted_versions = [s.candidate_version for s in promoted_summaries]
        for v_id in promoted_versions:
            run = eval_runs_col.find_one(
                {"prompt_version_id": v_id, "agent_name": agent_name}
            )
            if run and "persona_breakdown" in run:
                for persona, stats in run["persona_breakdown"].items():
                    persona_trends.setdefault(persona, []).append(
                        {
                            "version": v_id,
                            "mean": stats.get("mean", 0.0)
                            if isinstance(stats, dict)
                            else stats,
                        }
                    )

        return EvolutionReport(
            agent_name=agent_name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            current_version=current_version,
            initial_version=initial_version,
            n_iterations=len(summaries),
            n_promoted=len(promoted_summaries),
            iterations=summaries,
            score_trajectory=trajectory,
            prompt_diff=prompt_diff,
            compliance_preserved=compliance_preserved,
            cost_breakdown=cost_breakdown,
            persona_trends=persona_trends,
        )

    def format_cli(self, report: EvolutionReport) -> str:
        lines = []
        w = 70
        bar = "═" * w
        thin = "─" * w

        lines.append(f"\n{bar}")
        lines.append(f"  COPPERTREE EVOLUTION REPORT — {report.agent_name.upper()}")
        lines.append(f"  Generated: {report.generated_at}")
        lines.append(f"  Versions: {report.initial_version} → {report.current_version}")
        lines.append(
            f"  Iterations: {report.n_iterations}  |  Promoted: {report.n_promoted}"
        )
        lines.append(thin)

        # Score trajectory
        lines.append("  SCORE TRAJECTORY")
        lines.append(
            f"  {'Version':<20} {'Composite':>10} {'Compliance':>12} {'N':>4}  Change"
        )
        lines.append(f"  {'─' * 20} {'─' * 10} {'─' * 12} {'─' * 4}  {'─' * 20}")
        for t in report.score_trajectory:
            flag = " ◄ current" if t["is_current"] else ""
            lines.append(
                f"  {t['version']:<20} {t['composite_mean']:>10.4f} "
                f"{t['compliance_pass_rate']:>11.1%} {t['n_conversations']:>4}  "
                f"{t['change_description'][:35]}{flag}"
            )
        lines.append(thin)

        # Iteration details
        lines.append("  ITERATION DETAILS")
        for s in report.iterations:
            decision_icon = "✓ PROMOTED" if s.decision == "promoted" else "✗ REJECTED"
            lines.append(
                f"\n  [{s.iteration_num}] {s.baseline_version} → {s.candidate_version}  [{decision_icon}]"
            )
            if s.change_description:
                lines.append(f"      Change:    {s.change_description[:70]}")
            lines.append(
                f"      Scores:    baseline={s.baseline_mean:.4f} ± {s.baseline_std:.4f} → "
                f"candidate={s.candidate_mean:.4f} ± {s.candidate_std:.4f}  (Δ{s.delta:+.4f})"
            )
            lines.append(
                f"      Compliance: {s.baseline_compliance:.1%} → {s.candidate_compliance:.1%}"
            )
            # Statistical analysis
            lines.append("      Statistics:")
            if s.wilcoxon_p_value is not None:
                sig = (
                    " (significant)"
                    if s.wilcoxon_p_value < 0.05
                    else " (not significant)"
                )
                lines.append(f"        Wilcoxon p = {s.wilcoxon_p_value:.4f}{sig}")
            if s.bootstrap_ci_lower is not None:
                includes_zero = (
                    "includes zero" if s.bootstrap_ci_lower <= 0 else "above zero"
                )
                lines.append(
                    f"        Bootstrap 95% CI = [{s.bootstrap_ci_lower:+.4f}, {s.bootstrap_ci_upper:+.4f}] ({includes_zero})"
                )
            if s.per_persona_deltas:
                lines.append("      Per-persona deltas:")
                for persona, deltas in sorted(s.per_persona_deltas.items()):
                    arrow = (
                        "↑"
                        if deltas["delta"] > 0.005
                        else ("↓" if deltas["delta"] < -0.005 else "→")
                    )
                    lines.append(
                        f"        {persona:12s}: {deltas['baseline']:.3f} → {deltas['candidate']:.3f}  "
                        f"{arrow} {deltas['delta']:+.3f}"
                    )
            lines.append(f"      Reason:    {s.reason[:120]}")
        lines.append(thin)

        # Compliance preservation
        status = (
            "✓ PRESERVED" if report.compliance_preserved else "✗ REGRESSION DETECTED"
        )
        lines.append(f"  COMPLIANCE PRESERVATION: {status}")
        lines.append(thin)

        # Cost breakdown
        lines.append("  COST BREAKDOWN")
        for provider, amount in report.cost_breakdown.items():
            if provider != "total":
                lines.append(f"    {provider:15s}: ${amount:.4f}")
        lines.append(f"    {'TOTAL':15s}: ${report.cost_breakdown.get('total', 0):.4f}")
        lines.append(bar)

        return "\n".join(lines)

    def format_json(self, report: EvolutionReport, include_raw: bool = True) -> str:
        import dataclasses

        def _to_dict(obj):
            if dataclasses.is_dataclass(obj):
                d = dataclasses.asdict(obj)
                if not include_raw:
                    d.pop("baseline_conversations", None)
                    d.pop("candidate_conversations", None)
                return d
            return obj

        top = _to_dict(report)
        top["iterations"] = [_to_dict(s) for s in report.iterations]
        return json.dumps(top, indent=2, default=str)

    def format_html(self, report: EvolutionReport) -> str:
        rows = ""
        for t in report.score_trajectory:
            flag = " <b>(current)</b>" if t["is_current"] else ""
            rows += (
                f"<tr><td>{t['version']}{flag}</td>"
                f"<td>{t['composite_mean']:.4f}</td>"
                f"<td>{t['compliance_pass_rate']:.1%}</td>"
                f"<td>{t['n_conversations']}</td>"
                f"<td>{t['change_description'][:60]}</td></tr>\n"
            )

        compliance_badge = (
            '<span style="color:green">✓ Preserved</span>'
            if report.compliance_preserved
            else '<span style="color:red">✗ Regression</span>'
        )

        cost_rows = "".join(
            f"<tr><td>{p}</td><td>${v:.4f}</td></tr>\n"
            for p, v in report.cost_breakdown.items()
        )

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>CopperTree Evolution Report — {report.agent_name}</title>
<style>
  body {{ font-family: monospace; padding: 2em; background: #1a1a1a; color: #e0e0e0; }}
  h1 {{ color: #f0a000; }} h2 {{ color: #80c0ff; border-bottom: 1px solid #444; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ padding: 6px 12px; border: 1px solid #444; text-align: left; }}
  th {{ background: #2a2a2a; }} tr:hover {{ background: #252525; }}
  pre {{ background: #0d1117; padding: 1em; border-radius: 4px; overflow-x: auto; font-size: 0.85em; }}
  .promoted {{ color: #50fa7b; }} .rejected {{ color: #ff5555; }}
</style>
</head><body>
<h1>CopperTree Evolution Report — {report.agent_name}</h1>
<p><b>Generated:</b> {report.generated_at}<br>
<b>Versions:</b> {report.initial_version} → {report.current_version}<br>
<b>Iterations:</b> {report.n_iterations} | <b>Promoted:</b> {report.n_promoted}<br>
<b>Compliance:</b> {compliance_badge}</p>

<h2>Score Trajectory</h2>
<table><tr><th>Version</th><th>Composite Mean</th><th>Compliance Pass</th><th>N</th><th>Change</th></tr>
{rows}</table>

<h2>Iteration Details</h2>
{
            "".join(
                f"<p><b>[{s.iteration_num}]</b> {s.baseline_version} → {s.candidate_version} "
                f'<span class="{s.decision}">[{s.decision.upper()}]</span><br>'
                f"<i>{s.change_description[:80]}</i><br>"
                f"Scores: {s.baseline_mean:.4f} → {s.candidate_mean:.4f} (Δ{s.delta:+.4f})<br>"
                f"Compliance: {s.baseline_compliance:.1%} → {s.candidate_compliance:.1%}</p>"
                for s in report.iterations
            )
        }

<h2>Prompt Diff</h2>
<pre>{report.prompt_diff}</pre>

<h2>Cost Breakdown</h2>
<table><tr><th>Provider</th><th>Spend</th></tr>{cost_rows}</table>
</body></html>"""
