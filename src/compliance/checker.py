import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

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
    re.compile(r"\bcannot\s+afford\b", re.I),
    re.compile(r"\bcan'?t\s+afford\b", re.I),
    re.compile(r"\bhomeless\b", re.I),
    re.compile(r"\bmedical\s+bills?\b", re.I),
    re.compile(r"\bno\s+income\b", re.I),
    re.compile(r"\bbankrupt(cy)?\b", re.I),
    re.compile(r"\bfiling\s+for\s+(bankruptcy|chapter\s+(7|13))\b", re.I),
]

_DISPUTE_PATTERNS = [
    # Direct denial of the debt
    re.compile(r"\bi\s+dispute\s+this\s+debt\b", re.I),
    re.compile(r"\bi\s+don'?t\s+owe\s+this\b", re.I),
    re.compile(r"\bthis\s+is\s+not\s+my\s+debt\b", re.I),
    re.compile(r"\bthat'?s?\s+not\s+my\s+(account|debt|bill)\b", re.I),
    re.compile(r"\bi\s+never\s+owed\s+this\b", re.I),
    # Requests for validation / proof
    re.compile(r"\bsend\s+(me\s+)?(a\s+)?validation\s+notice\b", re.I),
    re.compile(r"\bsend\s+(me\s+)?debt\s+validation\b", re.I),
    re.compile(r"\bdebt\s+validation\s+(letter|notice|request)\b", re.I),
    re.compile(r"\bprove\s+(that\s+)?i\s+owe\b", re.I),
    re.compile(r"\bshow\s+me\s+proof\b", re.I),
    re.compile(r"\bverif(y|ication)\s+(this\s+)?(debt|account|balance)\b", re.I),
    # Requests for written documentation
    re.compile(r"\bi\s+want\s+it\s+in\s+writing\b", re.I),
    re.compile(r"\bput\s+it\s+in\s+writing\b", re.I),
    re.compile(r"\bsend\s+(me\s+)?something\s+in\s+writing\b", re.I),
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
        "dispute_flag": any(p.search(message) for p in _DISPUTE_PATTERNS),
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


def check_contact_time(borrower_timezone: Optional[str] = None) -> None:
    """
    FDCPA §805(a)(1): calls allowed only between 8am and 9pm borrower local time.
    Raises ApplicationError(non_retryable=True) if outside allowed hours.

    Args:
        borrower_timezone: IANA timezone string, e.g. "America/New_York".
                           Defaults to "America/New_York" if None.
    """
    try:
        from temporalio.exceptions import ApplicationError
    except ImportError:
        # Outside Temporal context (e.g. tests) — raise a plain ValueError instead
        class ApplicationError(Exception):  # type: ignore[no-redef]
            def __init__(self, msg: str, non_retryable: bool = False):
                super().__init__(msg)

    tz_name = borrower_timezone or "America/New_York"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")

    hour = datetime.now(tz).hour
    if not (8 <= hour < 21):
        raise ApplicationError(  # type: ignore[call-arg]
            f"FDCPA: contact time violation — borrower local hour={hour} in tz={tz_name} (allowed 8–20)",
            non_retryable=True,
        )


def generate_validation_notice(debt_amount: float, creditor: str, borrower_id: str) -> str:
    """
    Generate the FDCPA §809 required debt validation notice text.
    This must be sent/logged when a dispute_flag is triggered.

    Under FDCPA §809(a), within 5 days of initial contact the debt collector must
    send a written notice containing the five required disclosures below.
    Under §809(b), if the consumer disputes in writing within 30 days, the collector
    must cease collection and obtain verification before resuming.

    Returns plain text notice string. Caller is responsible for delivery and logging.
    """
    return (
        f"DEBT VALIDATION NOTICE\n"
        f"{'=' * 40}\n"
        f"Borrower Reference: {borrower_id}\n"
        f"Creditor: {creditor}\n"
        f"Amount of Debt: ${debt_amount:,.2f}\n\n"
        f"IMPORTANT NOTICE REGARDING YOUR RIGHTS\n\n"
        f"1. The amount of the debt is ${debt_amount:,.2f}. The name of the creditor "
        f"to whom the debt is owed is {creditor}.\n\n"
        f"2. Unless you, the consumer, dispute the validity of this debt, or any portion "
        f"thereof, within thirty (30) days after receipt of this notice, this debt will "
        f"be assumed to be valid by this office.\n\n"
        f"3. If you notify this office in writing within thirty (30) days of receiving "
        f"this notice that you dispute the validity of this debt, or any portion thereof, "
        f"this office will obtain verification of the debt or a copy of a judgment and "
        f"mail you a copy of such verification or judgment.\n\n"
        f"4. If you request in writing within thirty (30) days of receiving this notice, "
        f"this office will provide you with the name and address of the original creditor, "
        f"if different from the current creditor.\n\n"
        f"This communication is from a debt collector. This is an attempt to collect a "
        f"debt. Any information obtained will be used for that purpose.\n"
        f"{'=' * 40}"
    )
