"""
PII redaction for transcript storage.

Redacts full identifiers (SSN, account numbers, phone numbers, email addresses)
before transcripts are written to MongoDB. Partial identifiers — e.g. "ends in 4321"
or "last four 4321" — are deliberately preserved because agents use them for
identity verification and the last-4 digits are not considered sensitive in this context.

All redaction is purely regex-based so behaviour is deterministic and auditable.
"""

import re

# ---------------------------------------------------------------------------
# Pre-compiled patterns
# ---------------------------------------------------------------------------

# SSN: ddd-dd-dddd (canonical) or exactly 9 consecutive digits not bounded by
# more digits on either side (bare SSN like "123456789").
# The word-boundary (\b) on a bare digit run ensures we do not redact the
# middle of a longer number (e.g. a 12-digit account that starts with 9 digits).
_SSN_DASHED = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SSN_BARE = re.compile(r"(?<!\d)\d{9}(?!\d)")

# Account / credit-card numbers: runs of 12–19 digits, optionally space- or
# dash-separated in groups (e.g. "4111 1111 1111 1111" or "4111-1111-1111-1111").
# We match the grouped form as well as unspaced runs.
_ACCOUNT_GROUPED = re.compile(
    r"(?<!\d)"
    r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?:[-\s]\d{1,4})?"  # 16-20 digit groups
    r"(?!\d)"
)
_ACCOUNT_BARE = re.compile(r"(?<!\d)\d{12,19}(?!\d)")

# Guard patterns that indicate the surrounding digits are a *partial* reference
# ("ends in 4321", "last four 4321", "last 4 digits 4321", "****1234").
# If a short digit sequence (4 digits) is preceded by these phrases we skip it.
_PARTIAL_REF = re.compile(
    r"\b(?:ends?\s+in|last\s+(?:four|4)(?:\s+digits?)?)\s+\d{1,4}\b",
    re.I,
)
_MASKED_PARTIAL = re.compile(r"[\*x]{3,}-{0,1}\d{1,4}", re.I)

# Phone numbers: optional +1 country code, optional area-code parens,
# separators may be space, dot, or hyphen.
# We explicitly do NOT match already-masked patterns like "***-***-1234".
_PHONE = re.compile(
    r"(?<!\*)"  # not preceded by masking asterisk
    r"(?:\+1[-.\s]?)?"  # optional country code
    r"\(?\d{3}\)?[-.\s]?"  # area code
    r"\d{3}[-.\s]?\d{4}"  # subscriber number
    r"(?!\d)"
)

# Email addresses.
_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_pii(text: str) -> str:
    """
    Redact PII from a text string before storage.

    Returns text with full PII replaced by typed placeholders:
      - [REDACTED-SSN]
      - [REDACTED-ACCOUNT]
      - [REDACTED-PHONE]
      - [REDACTED-EMAIL]

    Partial identifiers (last 4 digits, masked phone stubs like ***-***-1234)
    are preserved because they are legitimately used for identity verification.
    """
    # Work on a copy; replacements are applied in priority order.
    result = text

    # --- SSN ---
    result = _SSN_DASHED.sub("[REDACTED-SSN]", result)
    result = _SSN_BARE.sub("[REDACTED-SSN]", result)

    # --- Account numbers ---
    # First, protect partial references so we don't accidentally catch the
    # trailing digits inside them with the bare account pattern.
    # Strategy: replace account-number runs only when they are NOT part of
    # a known partial-reference phrase.
    result = _redact_accounts(result)

    # --- Phone numbers ---
    # Skip already-masked stubs (e.g. "***-***-1234") — the negative lookbehind
    # in _PHONE handles most cases; _MASKED_PARTIAL handles the remainder.
    result = _redact_phones(result)

    # --- Email ---
    result = _EMAIL.sub("[REDACTED-EMAIL]", result)

    return result


def redact_messages(messages: list[dict]) -> list[dict]:
    """
    Apply redact_pii to the 'content' field of each message dict.

    Returns a new list of dicts; the originals are not mutated. Message dicts
    without a 'content' key (or with non-string content) are copied unchanged
    so the list structure is always preserved.
    """
    redacted: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            redacted.append({**msg, "content": redact_pii(content)})
        else:
            redacted.append(dict(msg))
    return redacted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_accounts(text: str) -> str:
    """
    Redact full account/card numbers while preserving partial-reference phrases.

    The approach:
    1. Collect spans of all partial-reference matches (these are protected zones).
    2. Redact grouped card numbers (e.g. "4111 1111 1111 1111") outside those zones.
    3. Redact bare 12–19 digit runs outside those zones.
    """
    protected: list[tuple[int, int]] = [
        m.span() for m in _PARTIAL_REF.finditer(text)
    ] + [m.span() for m in _MASKED_PARTIAL.finditer(text)]

    def _is_protected(start: int, end: int) -> bool:
        return any(ps <= start and end <= pe for ps, pe in protected)

    def _replace_if_unprotected(
        pattern: re.Pattern[str], replacement: str, s: str
    ) -> str:
        parts: list[str] = []
        prev = 0
        for m in pattern.finditer(s):
            start, end = m.span()
            parts.append(s[prev:start])
            parts.append(replacement if not _is_protected(start, end) else m.group())
            prev = end
        parts.append(s[prev:])
        return "".join(parts)

    text = _replace_if_unprotected(_ACCOUNT_GROUPED, "[REDACTED-ACCOUNT]", text)
    text = _replace_if_unprotected(_ACCOUNT_BARE, "[REDACTED-ACCOUNT]", text)
    return text


def _redact_phones(text: str) -> str:
    """
    Redact full phone numbers, leaving already-masked stubs (***-***-1234) intact.

    We walk the matches and skip any that overlap a _MASKED_PARTIAL span.
    """
    protected: list[tuple[int, int]] = [
        m.span() for m in _MASKED_PARTIAL.finditer(text)
    ]

    parts: list[str] = []
    prev = 0
    for m in _PHONE.finditer(text):
        start, end = m.span()
        parts.append(text[prev:start])
        if any(ps <= start and end <= pe for ps, pe in protected):
            parts.append(m.group())
        else:
            parts.append("[REDACTED-PHONE]")
        prev = end
    parts.append(text[prev:])
    return "".join(parts)
