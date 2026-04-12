from datetime import datetime, timezone

from src.storage.mongo import cost_log


def log_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    try:
        cost_log.insert_one(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "logged_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        print(f"[WARN] cost_tracker: failed to log cost — {e}")
