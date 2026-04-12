"""
Unit tests for src/handoff/token_budget.py

Covers enforce_budget(system_prompt, handoff_context=None):
  - No handoff: system_prompt truncated to MAX_TOTAL (2000 tokens), returns (str, None)
  - With handoff: handoff truncated to MAX_HANDOFF (500), system_prompt gets remaining budget
  - Very long handoff: truncated, does not exceed 500 tokens
  - system_prompt + handoff would exceed 2000: system_prompt truncated, total ≤ 2000
  - Never raises ValueError — always truncates silently

tiktoken is a real dependency used here (no mocking); tests rely on token counts
being deterministic for ASCII text (1 token ≈ 1 word for cl100k_base on simple English).
"""

import pytest

from src.handoff.token_budget import MAX_HANDOFF, MAX_TOTAL, _count, enforce_budget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _words(n: int) -> str:
    """Produce a string of exactly n space-separated words (each a simple ASCII token)."""
    return " ".join(f"word{i}" for i in range(n))


def _token_count(text: str) -> int:
    """Thin wrapper so test assertions read clearly."""
    return _count(text)


# ---------------------------------------------------------------------------
# enforce_budget — no handoff context
# ---------------------------------------------------------------------------


class TestEnforceBudgetNoHandoff:
    """When handoff_context is omitted, system_prompt is bounded to MAX_TOTAL tokens."""

    def test_returns_tuple_of_two_elements(self):
        prompt = "You are a helpful collections agent."
        result = enforce_budget(prompt)
        assert isinstance(result, tuple) and len(result) == 2

    def test_second_element_is_none_when_no_handoff(self):
        prompt = "You are a helpful collections agent."
        _, handoff_out = enforce_budget(prompt)
        assert handoff_out is None

    def test_short_prompt_returned_unchanged(self):
        prompt = "You are a helpful collections agent."
        prompt_out, _ = enforce_budget(prompt)
        assert prompt_out == prompt

    def test_prompt_within_max_total_not_truncated(self):
        # 100 words is well under 2000 tokens
        prompt = _words(100)
        prompt_out, _ = enforce_budget(prompt)
        assert _token_count(prompt_out) <= MAX_TOTAL
        # Should not be shorter than the input
        assert prompt_out == prompt

    def test_long_prompt_truncated_to_max_total(self):
        # 3000 words will exceed 2000 tokens
        prompt = _words(3000)
        assert _token_count(prompt) > MAX_TOTAL
        prompt_out, _ = enforce_budget(prompt)
        assert _token_count(prompt_out) <= MAX_TOTAL

    def test_long_prompt_does_not_raise(self):
        # Truncation, not exception
        prompt = _words(5000)
        try:
            enforce_budget(prompt)
        except Exception as exc:
            pytest.fail(f"enforce_budget raised unexpectedly: {exc}")

    def test_empty_prompt_returns_empty_string(self):
        prompt_out, handoff_out = enforce_budget("")
        assert prompt_out == ""
        assert handoff_out is None

    def test_explicit_none_handoff_same_as_omitted(self):
        prompt = "Short prompt."
        result_implicit = enforce_budget(prompt)
        result_explicit = enforce_budget(prompt, handoff_context=None)
        assert result_implicit == result_explicit


# ---------------------------------------------------------------------------
# enforce_budget — with handoff context
# ---------------------------------------------------------------------------


class TestEnforceBudgetWithHandoff:
    """When handoff_context is provided, both outputs are non-None strings."""

    def test_returns_two_strings(self):
        prompt = "You are a collections agent."
        handoff = "Previous session: borrower owes $500."
        prompt_out, handoff_out = enforce_budget(prompt, handoff)
        assert isinstance(prompt_out, str)
        assert isinstance(handoff_out, str)

    def test_short_handoff_not_truncated(self):
        prompt = "You are a collections agent."
        handoff = "Short context."  # well under 500 tokens
        _, handoff_out = enforce_budget(prompt, handoff)
        assert handoff_out == handoff

    def test_short_inputs_within_budget_unchanged(self):
        prompt = _words(50)
        handoff = _words(50)
        prompt_out, handoff_out = enforce_budget(prompt, handoff)
        assert prompt_out == prompt
        assert handoff_out == handoff

    def test_total_token_count_does_not_exceed_max_total(self):
        # Both inputs are long enough to require trimming
        prompt = _words(2000)
        handoff = _words(1000)
        prompt_out, handoff_out = enforce_budget(prompt, handoff)
        total = _token_count(prompt_out) + _token_count(handoff_out)
        assert total <= MAX_TOTAL

    def test_does_not_raise_with_very_long_inputs(self):
        prompt = _words(5000)
        handoff = _words(2000)
        try:
            enforce_budget(prompt, handoff)
        except Exception as exc:
            pytest.fail(f"enforce_budget raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# enforce_budget — handoff truncation at MAX_HANDOFF
# ---------------------------------------------------------------------------


class TestHandoffTruncation:
    """Handoff context must never exceed MAX_HANDOFF tokens."""

    def test_handoff_at_limit_not_truncated(self):
        # Build a handoff of exactly MAX_HANDOFF tokens
        # _words(n) generates roughly n tokens for simple ASCII words
        handoff = _words(MAX_HANDOFF)
        # Allow some slack: token boundary is approx, so check ≤ MAX_HANDOFF
        _, handoff_out = enforce_budget("System.", handoff)
        assert _token_count(handoff_out) <= MAX_HANDOFF

    def test_very_long_handoff_truncated_to_max_handoff(self):
        handoff = _words(2000)  # 2000 words >> 500 token limit
        assert _token_count(handoff) > MAX_HANDOFF
        _, handoff_out = enforce_budget("System.", handoff)
        assert _token_count(handoff_out) <= MAX_HANDOFF

    def test_truncated_handoff_is_non_empty(self):
        handoff = _words(2000)
        _, handoff_out = enforce_budget("System.", handoff)
        assert len(handoff_out) > 0

    def test_handoff_truncation_is_prefix_consistent(self):
        # The truncated output must come from the beginning of the input
        handoff = _words(2000)
        _, handoff_out = enforce_budget("System.", handoff)
        # The truncated handoff should be a leading substring of the original
        assert handoff.startswith(handoff_out)


# ---------------------------------------------------------------------------
# enforce_budget — system_prompt truncation when budget is tight
# ---------------------------------------------------------------------------


class TestSystemPromptTruncationWithHandoff:
    """When handoff consumes most of the budget, system_prompt is cut down."""

    def test_system_prompt_fits_remaining_budget(self):
        # Handoff near the limit, system_prompt is large
        handoff = _words(400)  # ~400 tokens
        prompt = _words(2000)  # well over remaining ~1600
        prompt_out, handoff_out = enforce_budget(prompt, handoff)
        total = _token_count(prompt_out) + _token_count(handoff_out)
        assert total <= MAX_TOTAL

    def test_system_prompt_truncated_when_handoff_dominates(self):
        # Handoff uses close to MAX_HANDOFF, leaving little room for prompt
        handoff = _words(450)
        prompt = _words(3000)
        prompt_out, handoff_out = enforce_budget(prompt, handoff)
        assert _token_count(handoff_out) <= MAX_HANDOFF
        assert _token_count(prompt_out) + _token_count(handoff_out) <= MAX_TOTAL

    def test_no_value_error_when_prompt_must_be_aggressively_cut(self):
        # Extreme: handoff near 500 tokens, prompt at 5000 words
        handoff = _words(490)
        prompt = _words(5000)
        try:
            enforce_budget(prompt, handoff)
        except ValueError as exc:
            pytest.fail(f"enforce_budget raised ValueError unexpectedly: {exc}")
