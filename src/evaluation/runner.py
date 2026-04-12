"""
Evaluation runner — executes N conversations with a given prompt version,
scores each with ConversationJudge, and saves results to MongoDB + JSONL.
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.final_notice import FinalNoticeAgent
from src.agents.resolution import ResolutionAgent
from src.agents.simulator import SimulatedBorrower
from src.evaluation.judge import ConversationJudge, JudgeOutput
from src.llm.client import LLMClient
from src.models.case_file import CaseFile, DebtInfo, FinancialInfo, NegotiationLedger, ComplianceState
from src.storage.mongo import eval_runs as eval_runs_collection
from src.storage.prompt_registry import get_current_prompt

_PROFILES_PATH = Path(__file__).parent.parent.parent / "data" / "scenarios" / "borrower_profiles.json"
_EVAL_RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "eval_runs"


def _load_profiles() -> list[dict]:
    return json.loads(_PROFILES_PATH.read_text())


def _build_case_file(profile: dict, seed: int) -> CaseFile:
    """Create a fresh in-memory CaseFile from a borrower profile. Not persisted to MongoDB."""
    borrower_id = f"eval_{profile['persona']}_{seed}"
    return CaseFile(
        borrower_id=borrower_id,
        partial_account=profile["account_ending"],
        debt=DebtInfo(
            amount=profile["debt_amount"],
            creditor=profile["creditor"],
            default_date="2025-01-15",
        ),
        financial=FinancialInfo(
            income_status=profile.get("income_status"),
            monthly_income_est=profile.get("monthly_income"),
        ),
        negotiation=NegotiationLedger(),
        compliance=ComplianceState(),
    )


@dataclass
class EvalRunResult:
    run_id: str
    prompt_version_id: str
    agent_name: str
    scores: list[dict] = field(default_factory=list)  # serialized JudgeOutput dicts
    composite_mean: float = 0.0
    composite_std: float = 0.0
    compliance_pass_rate: float = 0.0
    seed: int = 42
    n_conversations: int = 0


class EvalRunner:
    """
    Runs N conversations with a given agent + prompt version, scores each, saves results.

    Usage:
        runner = EvalRunner()
        result = runner.run_evaluation("assessment", prompt_version_id="assessment_v1", n_conversations=10)
    """

    def __init__(self, judge: ConversationJudge | None = None) -> None:
        self.judge = judge or ConversationJudge()

    def run_evaluation(
        self,
        agent_name: str,
        prompt_version_id: str | None = None,
        n_conversations: int = 60,
        seed: int = 42,
        persist: bool = False,
    ) -> EvalRunResult:
        """
        Run N conversations, rotating through all 5 personas.
        Each conversation uses a deterministic seed (seed + i) for reproducibility.

        Args:
            agent_name: "assessment", "resolution", or "final_notice"
            prompt_version_id: specific version to eval, or None to use current
            n_conversations: number of conversations to run
            seed: base seed for reproducibility
            persist: if True, write CaseFiles to MongoDB (default False — in-memory only)
        """
        profiles = _load_profiles()
        if not profiles:
            raise RuntimeError("No borrower profiles found. Check data/scenarios/borrower_profiles.json.")

        # Cost ceiling check
        _COST_CEILING_USD = 20.0
        try:
            from src.storage.mongo import cost_log
            pipeline = [{"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}}]
            result_agg = list(cost_log.aggregate(pipeline))
            cumulative_cost = result_agg[0]["total"] if result_agg else 0.0
            if cumulative_cost >= _COST_CEILING_USD:
                raise RuntimeError(
                    f"Cost ceiling reached: ${cumulative_cost:.2f} >= ${_COST_CEILING_USD:.2f}. "
                    "Aborting eval run to prevent overspend."
                )
            print(f"[eval] Cumulative LLM cost so far: ${cumulative_cost:.2f} / ${_COST_CEILING_USD:.2f}")
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[WARN] eval_runner: could not check cost ceiling — {e}")

        if prompt_version_id is None:
            doc = get_current_prompt(agent_name)
            if doc is None:
                raise RuntimeError(f"No current prompt for agent '{agent_name}'")
            prompt_version_id = doc.get("_id", "unknown")

        run_id = f"eval_{agent_name}_{seed}_{uuid.uuid4().hex[:8]}"
        llm = LLMClient()
        scores_raw: list[dict] = []

        print(f"[eval] Starting run {run_id} — {n_conversations} conversations, seed={seed}")

        for i in range(n_conversations):
            profile = profiles[i % len(profiles)]
            conversation_seed = seed + i

            try:
                score_dict = self._run_single(
                    agent_name=agent_name,
                    profile=profile,
                    conversation_seed=conversation_seed,
                    llm=llm,
                )
                score_dict["persona"] = profile["persona"]
                score_dict["seed"] = conversation_seed
                score_dict["run_index"] = i
                scores_raw.append(score_dict)
                print(
                    f"  [{i+1}/{n_conversations}] persona={profile['persona']} "
                    f"composite={score_dict.get('composite', 0):.3f}"
                )
            except Exception as e:
                print(f"  [{i+1}/{n_conversations}] ERROR: {e}")
                scores_raw.append({
                    "persona": profile["persona"],
                    "seed": conversation_seed,
                    "run_index": i,
                    "error": str(e),
                    "composite": 0.0,
                })

        composites = [s.get("composite", 0.0) for s in scores_raw]
        mean = sum(composites) / len(composites) if composites else 0.0
        variance = sum((c - mean) ** 2 for c in composites) / len(composites) if composites else 0.0
        std = variance ** 0.5
        compliance_pass_rate = sum(1 for c in composites if c > 0.0) / len(composites) if composites else 0.0

        result = EvalRunResult(
            run_id=run_id,
            prompt_version_id=prompt_version_id,
            agent_name=agent_name,
            scores=scores_raw,
            composite_mean=mean,
            composite_std=std,
            compliance_pass_rate=compliance_pass_rate,
            seed=seed,
            n_conversations=n_conversations,
        )

        self._save_results(result)
        return result

    def _run_single(
        self,
        agent_name: str,
        profile: dict,
        conversation_seed: int,
        llm: LLMClient,
    ) -> dict:
        """Run one conversation and return score dict."""
        case_before = _build_case_file(profile, conversation_seed)
        case_file = _build_case_file(profile, conversation_seed)

        borrower_io = SimulatedBorrower(llm=llm, persona_description=profile["description"])
        budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)

        if agent_name == "assessment":
            agent = AssessmentAgent(llm)
        elif agent_name == "resolution":
            agent = ResolutionAgent(llm)
        elif agent_name == "final_notice":
            agent = FinalNoticeAgent(llm)
        else:
            raise ValueError(f"Unknown agent_name: {agent_name!r}")

        messages, updated_case, _injection_flags = agent.run_conversation(
            case_file=case_file,
            io=borrower_io,
            budget=budget,
        )

        score: JudgeOutput = self.judge.score_conversation(
            transcript=messages,
            case_before=case_before.model_dump(mode="json"),
            case_after=updated_case.model_dump(mode="json"),
            stage=agent_name,
        )
        return score.model_dump(mode="json")

    def _save_results(self, result: EvalRunResult) -> None:
        """Save results to MongoDB eval_runs collection and JSONL file."""
        # MongoDB
        try:
            eval_runs_collection.insert_one({
                "_id": result.run_id,
                "prompt_version_id": result.prompt_version_id,
                "agent_name": result.agent_name,
                "composite_mean": result.composite_mean,
                "composite_std": result.composite_std,
                "compliance_pass_rate": result.compliance_pass_rate,
                "seed": result.seed,
                "n_conversations": result.n_conversations,
                "scores": result.scores,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            print(f"[WARN] eval_runner: failed to save to MongoDB — {e}")

        # JSONL file
        _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        jsonl_path = _EVAL_RUNS_DIR / f"{result.run_id}.jsonl"
        with jsonl_path.open("w") as f:
            for score in result.scores:
                f.write(json.dumps(score) + "\n")
        print(f"[eval] Results saved to {jsonl_path}")
        print(
            f"[eval] Summary: mean={result.composite_mean:.4f} ± {result.composite_std:.4f}, "
            f"compliance_pass_rate={result.compliance_pass_rate:.1%}"
        )
