import tiktoken

MAX_TOTAL = 2000
MAX_HANDOFF = 500

_encoder = tiktoken.get_encoding("cl100k_base")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    print(f"[WARN] token_budget: truncating {len(tokens)} → {max_tokens} tokens")
    return _encoder.decode(tokens[:max_tokens])


def enforce_budget(
    system_prompt: str,
    handoff_context: str | None = None,
) -> tuple[str, str | None]:
    if handoff_context is None:
        return _truncate_to_tokens(system_prompt, MAX_TOTAL), None

    handoff_context = _truncate_to_tokens(handoff_context, MAX_HANDOFF)
    remaining = MAX_TOTAL - _count(handoff_context)
    system_prompt = _truncate_to_tokens(system_prompt, remaining)
    return system_prompt, handoff_context
