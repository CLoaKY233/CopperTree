"""
Decision journal — append-only timestamped log of every learning-loop promote/reject decision.

Written to DECISION_JOURNAL.md at repo root. Entries are never edited or removed,
making the journal a tamper-evident audit trail of the prompt improvement history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_JOURNAL_PATH = Path(__file__).parent.parent.parent / "DECISION_JOURNAL.md"


def _ensure_header() -> None:
    if not _JOURNAL_PATH.exists():
        _JOURNAL_PATH.write_text(
            "# CopperTree — Decision Journal\n\n"
            "Append-only log of every learning-loop promote/reject decision.\n"
            "Each entry records the statistical gate results, score deltas, "
            "and artifact file paths.\n\n"
            "---\n\n"
        )


def append_decision(
    *,
    agent: str,
    baseline_version: str,
    candidate_version: str,
    decision: str,  # "promoted" | "rejected"
    reason: str,
    baseline_mean: float,
    baseline_std: float,
    baseline_compliance_rate: float,
    candidate_mean: float,
    candidate_std: float,
    candidate_compliance_rate: float,
    n_conversations: int,
    seed: int,
    gate_details: dict,  # keys: gate1_pass, gate2_pass, gate2_p, gate3_pass, gate3_p, gate4_pass, gate4_ci_lower
    baseline_run_id: str,
    candidate_run_id: str,
    proposer_change_summary: str = "",
) -> None:
    """
    Append one timestamped decision entry to DECISION_JOURNAL.md.

    gate_details keys:
        gate1_pass: bool         — 100% compliance requirement
        gate2_pass: bool         — compliance non-regression (Wilcoxon)
        gate2_p: float | None    — Wilcoxon p-value
        gate3_pass: bool         — composite improvement (Wilcoxon)
        gate3_p: float | None    — Wilcoxon p-value
        gate4_pass: bool | None  — bootstrap 95% CI lower > 0
        gate4_ci_lower: float | None
        gate4_ci_upper: float | None
    """
    _ensure_header()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    delta = candidate_mean - baseline_mean
    delta_str = f"{delta:+.4f}"

    g = gate_details

    def _pass_icon(v: bool | None) -> str:
        if v is None:
            return "—"
        return "PASS" if v else "FAIL"

    gate1_line = (
        f"- **Gate 1** (100% compliance required): {_pass_icon(g.get('gate1_pass'))}"
    )
    gate2_p_str = f"p={g['gate2_p']:.4f}" if g.get("gate2_p") is not None else "n/a"
    gate2_line = f"- **Gate 2** (compliance non-regression, Wilcoxon one-sided): {_pass_icon(g.get('gate2_pass'))}  ({gate2_p_str})"
    gate3_p_str = f"p={g['gate3_p']:.4f}" if g.get("gate3_p") is not None else "n/a"
    gate3_line = f"- **Gate 3** (composite improvement, Wilcoxon one-sided): {_pass_icon(g.get('gate3_pass'))}  ({gate3_p_str})"
    ci_lower = g.get("gate4_ci_lower")
    ci_upper = g.get("gate4_ci_upper")
    ci_str = f"CI=[{ci_lower:.4f}, {ci_upper:.4f}]" if ci_lower is not None else "n/a"
    gate4_line = f"- **Gate 4** (bootstrap 95% CI lower > 0): {_pass_icon(g.get('gate4_pass'))}  ({ci_str})"

    change_section = (
        f"\n**Proposer change:** {proposer_change_summary}\n"
        if proposer_change_summary
        else ""
    )

    entry = (
        f"## {ts} — {agent} — {baseline_version} → {candidate_version}\n\n"
        f"**Decision:** {decision.upper()}  \n"
        f"**Reason:** {reason}\n\n"
        f"**Baseline ({baseline_version}):** "
        f"composite={baseline_mean:.4f} ± {baseline_std:.4f}, "
        f"compliance_pass={baseline_compliance_rate:.1%}, N={n_conversations}, seed={seed}  \n"
        f"**Candidate ({candidate_version}):** "
        f"composite={candidate_mean:.4f} ± {candidate_std:.4f}, "
        f"compliance_pass={candidate_compliance_rate:.1%}  \n"
        f"**Delta:** {delta_str}"
        f"{change_section}\n"
        f"**Statistical gate:**\n"
        f"{gate1_line}  \n"
        f"{gate2_line}  \n"
        f"{gate3_line}  \n"
        f"{gate4_line}\n\n"
        f"**Artifacts:**  \n"
        f"- Baseline: `data/eval_runs/{baseline_run_id}.jsonl`  \n"
        f"- Candidate: `data/eval_runs/{candidate_run_id}.jsonl`\n\n"
        f"---\n\n"
    )

    with _JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(entry)
