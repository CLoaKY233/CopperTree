"""
One-time script: backfill DECISION_JOURNAL.md from existing MongoDB learning_iterations.

Run once after upgrading to the new journal system:
    PYTHONPATH=. uv run python scripts/bootstrap_decision_journal.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.learning.journal import _JOURNAL_PATH, append_decision, _ensure_header
from src.storage.mongo import _get_db


def main() -> None:
    db = _get_db()
    iterations_col = db["learning_iterations"]

    existing_content = _JOURNAL_PATH.read_text() if _JOURNAL_PATH.exists() else ""

    raw_iterations = list(iterations_col.find({}).sort("created_at", 1))
    if not raw_iterations:
        print("[bootstrap] No learning iterations found in MongoDB.")
        return

    print(f"[bootstrap] Found {len(raw_iterations)} iterations to backfill.")

    backfilled = 0
    for raw in raw_iterations:
        baseline_run_id = raw.get("baseline_run_id", "")
        candidate_run_id = raw.get("candidate_run_id", "")

        # Skip if this iteration is already in the journal
        candidate_version = raw.get("candidate_version", "")
        if candidate_version and candidate_version in existing_content:
            print(f"[bootstrap] Skipping {candidate_version} (already in journal)")
            continue

        reason = raw.get("reason", "")

        # Parse gate details from reason string if available
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

        gate_details = {
            "gate1_pass": raw.get("candidate_compliance_rate", 0.0) >= 1.0,
            "gate2_pass": None,
            "gate2_p": None,
            "gate3_pass": wilcoxon_p is not None and wilcoxon_p < 0.05,
            "gate3_p": wilcoxon_p,
            "gate4_pass": ci_lower is not None and ci_lower > 0,
            "gate4_ci_lower": ci_lower,
            "gate4_ci_upper": ci_upper,
        }

        try:
            append_decision(
                agent=raw.get("agent", "unknown"),
                baseline_version=raw.get("baseline_version", "unknown"),
                candidate_version=candidate_version,
                decision=raw.get("decision", "unknown"),
                reason=reason,
                baseline_mean=raw.get("baseline_mean", 0.0),
                baseline_std=0.0,
                baseline_compliance_rate=raw.get("baseline_compliance_rate", 0.0),
                candidate_mean=raw.get("candidate_mean", 0.0),
                candidate_std=0.0,
                candidate_compliance_rate=raw.get("candidate_compliance_rate", 0.0),
                n_conversations=raw.get("n_conversations", 0),
                seed=raw.get("seed", 42),
                gate_details=gate_details,
                baseline_run_id=baseline_run_id,
                candidate_run_id=candidate_run_id,
            )
            print(
                f"[bootstrap] Written: {raw.get('baseline_version')} → {candidate_version} ({raw.get('decision')})"
            )
            backfilled += 1
        except Exception as exc:
            print(f"[bootstrap] ERROR for {candidate_version}: {exc}")

    print(f"\n[bootstrap] Done. {backfilled} entries written to {_JOURNAL_PATH}")


if __name__ == "__main__":
    main()
