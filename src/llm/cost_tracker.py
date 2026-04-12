from datetime import datetime, timezone
from typing import Optional

from src.storage.mongo import cost_log


def log_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    provider: str = "azure",  # "azure" | "anthropic"
    role: str = "agent",  # "agent" | "borrower" | "judge" | "proposer"
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> None:
    try:
        cost_log.insert_one(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "provider": provider,
                "role": role,
                "run_id": run_id,
                "conversation_id": conversation_id,
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        print(f"[WARN] cost_tracker: failed to log cost — {e}")


def get_provider_spend(provider: str) -> float:
    """Return cumulative spend in USD for a given provider."""
    try:
        pipeline = [
            {"$match": {"provider": provider}},
            {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
        ]
        result = list(cost_log.aggregate(pipeline))
        return result[0]["total"] if result else 0.0
    except Exception:
        return 0.0


def get_total_spend() -> dict[str, float]:
    """Return per-provider cumulative spend."""
    try:
        pipeline = [{"$group": {"_id": "$provider", "total": {"$sum": "$cost_usd"}}}]
        return {r["_id"]: r["total"] for r in cost_log.aggregate(pipeline)}
    except Exception:
        return {}


def get_run_breakdown(run_id: str) -> dict:
    """
    Return a detailed cost breakdown for a single eval run.
    Groups by provider and role.
    """
    try:
        pipeline = [
            {"$match": {"run_id": run_id}},
            {
                "$group": {
                    "_id": {
                        "provider": "$provider",
                        "role": "$role",
                        "model": "$model",
                    },
                    "total_cost": {"$sum": "$cost_usd"},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "calls": {"$sum": 1},
                }
            },
        ]
        rows = list(cost_log.aggregate(pipeline))
        breakdown: dict = {"run_id": run_id, "by_provider_role": [], "total": 0.0}
        for r in rows:
            entry = {
                "provider": r["_id"]["provider"],
                "role": r["_id"]["role"],
                "model": r["_id"]["model"],
                "calls": r["calls"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cost_usd": round(r["total_cost"], 6),
            }
            breakdown["by_provider_role"].append(entry)
            breakdown["total"] = round(breakdown["total"] + r["total_cost"], 6)
        return breakdown
    except Exception:
        return {"run_id": run_id, "by_provider_role": [], "total": 0.0}


def get_agent_loop_breakdown(agent: str) -> dict:
    """
    Return aggregated cost for all learning-loop runs associated with an agent.
    Looks for run_ids matching eval_{agent}_*.
    """
    try:
        pipeline = [
            {"$match": {"run_id": {"$regex": f"^eval_{agent}_"}}},
            {
                "$group": {
                    "_id": {
                        "provider": "$provider",
                        "role": "$role",
                        "model": "$model",
                    },
                    "total_cost": {"$sum": "$cost_usd"},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "calls": {"$sum": 1},
                }
            },
        ]
        rows = list(cost_log.aggregate(pipeline))
        breakdown: dict = {
            "agent": agent,
            "by_provider_role": [],
            "total": 0.0,
            "by_provider": {},
        }
        for r in rows:
            provider = r["_id"]["provider"]
            entry = {
                "provider": provider,
                "role": r["_id"]["role"],
                "model": r["_id"]["model"],
                "calls": r["calls"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cost_usd": round(r["total_cost"], 6),
            }
            breakdown["by_provider_role"].append(entry)
            breakdown["total"] = round(breakdown["total"] + r["total_cost"], 6)
            breakdown["by_provider"][provider] = round(
                breakdown["by_provider"].get(provider, 0.0) + r["total_cost"], 6
            )
        return breakdown
    except Exception:
        return {"agent": agent, "by_provider_role": [], "total": 0.0, "by_provider": {}}
