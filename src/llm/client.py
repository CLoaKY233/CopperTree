import tiktoken
from openai import OpenAI

from src.config import settings
from src.llm.cost_tracker import log_cost

PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4-nano": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
}

_DEFAULT_ENCODING = "cl100k_base"


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(
            base_url=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
        )
        self.default_model = settings.azure_openai_deployment
        self._encoder = tiktoken.get_encoding(_DEFAULT_ENCODING)

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 500,
    ) -> str:
        model = model or self.default_model
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            max_completion_tokens=max_tokens,
        )
        usage = resp.usage
        pricing = PRICING.get(model, PRICING["gpt-5.4-nano"])
        cost = (
            usage.prompt_tokens * pricing["input"]
            + usage.completion_tokens * pricing["output"]
        )
        log_cost(
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=cost,
        )
        return resp.choices[0].message.content
