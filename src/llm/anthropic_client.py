"""
Anthropic SDK client for the CopperTree judge.

This is intentionally separate from LLMClient (Azure OpenAI) — the judge
runs on Claude Sonnet for quality, agents run on gpt-5.4-mini for cost.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import anthropic

from src.config import settings
from src.llm.cost_tracker import log_cost

logger = logging.getLogger(__name__)

# Anthropic pricing per token (as of 2025)
_ANTHROPIC_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-sonnet-4-5": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-opus-4-6": {"input": 5.0 / 1_000_000, "output": 25.0 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
}


class AnthropicJudgeClient:
    """
    Wraps the Anthropic SDK for evaluation judge calls.
    Logs cost to MongoDB under provider="anthropic", role="judge".
    """

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env to use the Claude judge."
            )
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2000,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        Single call to Claude. Returns raw text content.
        Retries up to 5 times on rate limits with exponential backoff.
        """
        last_exc: Exception | None = None
        response = None
        for attempt in range(5):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                last_exc = None
                break
            except anthropic.RateLimitError as exc:
                last_exc = exc
                wait = 2**attempt
                print(f"[Anthropic] Rate limited, retrying in {wait}s...")
                time.sleep(wait)
        if last_exc is not None:
            raise last_exc
        assert response is not None

        # Log cost
        usage = response.usage
        pricing = _ANTHROPIC_PRICING.get(
            self.model, _ANTHROPIC_PRICING["claude-sonnet-4-6"]
        )
        cost_usd = (
            usage.input_tokens * pricing["input"]
            + usage.output_tokens * pricing["output"]
        )

        log_cost(
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
            provider="anthropic",
            role="judge",
            run_id=run_id,
            conversation_id=conversation_id,
        )

        content = response.content[0]
        if content.type != "text":
            raise RuntimeError(f"Unexpected Anthropic response type: {content.type}")
        return content.text
