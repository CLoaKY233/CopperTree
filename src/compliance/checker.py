import re

MAX_BORROWER_MSG_LEN = 2000

_STOP_PATTERNS = [
    # Must be an affirmative command — exclude "I haven't told you to stop", "don't stop", etc.
    re.compile(
        r"(?<!n't\s)(?<!not\s)(?<!never\s)\b(please\s+)?(stop|cease|quit)\s+(calling|contacting|texting|emailing|reaching\s+out)\b",
        re.I,
    ),
    re.compile(r"\bdo\s+not\s+contact\s+me\b", re.I),
    re.compile(r"\bdo\s+not\s+call\s+me\b", re.I),
    re.compile(r"\bdon'?t\s+(call|contact)\s+me\s+(again|anymore)\b", re.I),
    re.compile(r"\bleave\s+me\s+alone\b", re.I),
    re.compile(r"\btalk\s+to\s+my\s+(lawyer|attorney)\b", re.I),
    re.compile(r"\bcease\s+and\s+desist\b", re.I),
    re.compile(r"\bno\s+more\s+(calls?|messages?|contact)\b", re.I),
    re.compile(r"\bstop\s+harassing\b", re.I),
    re.compile(r"\bi\s+said\s+stop\b", re.I),
    re.compile(
        r"\bsend\s+(everything|all\s+correspondence)\s+(in\s+writing|by\s+mail)\b", re.I
    ),
]

_HARDSHIP_PATTERNS = [
    re.compile(r"\blost\s+my\s+job\b", re.I),
    re.compile(r"\b(unemployed|unemployment)\b", re.I),
    re.compile(r"\blaid\s+off\b", re.I),
    re.compile(r"\b(disabled|disability|on\s+disability)\b", re.I),
    re.compile(r"\bcan'?t\s+afford\b", re.I),
    re.compile(r"\bhomeless\b", re.I),
    re.compile(r"\bmedical\s+bills?\b", re.I),
    re.compile(r"\bno\s+income\b", re.I),
    re.compile(r"\bbankrupt(cy)?\b", re.I),
    re.compile(r"\bfiling\s+for\s+(bankruptcy|chapter\s+(7|13))\b", re.I),
]

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"(^|\s)system\s*:", re.I),
    re.compile(r"<\|?(im_start|im_end|endoftext)\|?>", re.I),
    re.compile(r"```\s*(system|prompt|instruction)", re.I),
    re.compile(r"disregard\s+(all\s+)?(prior|previous|above)\s+instructions?", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
]


def check_compliance_triggers(message: str) -> dict[str, bool]:
    """
    Deterministic regex check — must run on every borrower message before the LLM.
    Stop-contact detection is legal-critical (FDCPA) and cannot rely on LLM judgment.
    """
    return {
        "stop_contact": any(p.search(message) for p in _STOP_PATTERNS),
        "hardship_flag": any(p.search(message) for p in _HARDSHIP_PATTERNS),
    }


def sanitize_borrower_input(text: str) -> tuple[str, list[str]]:
    """
    Sanitize raw borrower input before it enters the LLM conversation.
    Returns (sanitized_text, injection_flags).
    Injection flags trigger logging for human review — we do not block the conversation.
    """
    flags: list[str] = []

    if len(text) > MAX_BORROWER_MSG_LEN:
        text = text[:MAX_BORROWER_MSG_LEN]
        flags.append("truncated")

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            flags.append("injection_pattern_detected")
            break

    return text, flags
