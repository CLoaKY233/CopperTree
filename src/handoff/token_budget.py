import tiktoken

MAX_TOTAL = 2000
MAX_HANDOFF = 500

_encoder = tiktoken.get_encoding("cl100k_base")


def _count(text: str) -> int:
    return len(_encoder.encode(text))


def enforce_budget(
    system_prompt: str,
    handoff_context: str | None = None,
) -> tuple[str, str | None]:
    sys_tokens = _count(system_prompt)

    if handoff_context is None:
        if sys_tokens > MAX_TOTAL:
            raise ValueError(
                f"System prompt is {sys_tokens} tokens, exceeds limit of {MAX_TOTAL}"
            )
        return system_prompt, None

    handoff_tokens = _count(handoff_context)
    if handoff_tokens > MAX_HANDOFF:
        raise ValueError(
            f"Handoff context is {handoff_tokens} tokens, exceeds limit of {MAX_HANDOFF}"
        )

    total = sys_tokens + handoff_tokens
    if total > MAX_TOTAL:
        raise ValueError(
            f"Combined prompt is {total} tokens (sys={sys_tokens}, handoff={handoff_tokens}), "
            f"exceeds limit of {MAX_TOTAL}"
        )

    return system_prompt, handoff_context
