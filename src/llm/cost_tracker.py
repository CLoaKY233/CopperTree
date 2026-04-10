from datetime import datetime, timezone

from src.storage.mongo import cost_log


def log_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    cost_log.insert_one(
        {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
    )
