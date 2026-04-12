"""
Retell AI voice client — Single Prompt Agent mode.

Architecture decision: agent is pre-created on the Retell dashboard (not
programmatically per-call). This gives full dashboard control over voice,
latency tuning, post-call extraction config, and webhook setup.

Flow (production):
  1. make_call(to_number) using RETELL_AGENT_ID from config
  2. Retell handles STT + GPT-4.1 + TTS
  3. After call ends, Retell POSTs call_ended webhook → src/voice/webhook.py processes it
     OR we poll get_transcript(call_id) as fallback

Flow (EVAL_MODE=true):
  simulate_as_text() runs the same system prompt as text chat — no real call.
  transcript_turns format is identical so downstream code is unaffected.
"""

import time
from dataclasses import dataclass
from typing import Optional

from src.config import settings


@dataclass
class RetellCallResult:
    call_id: str
    status: str                      # "completed" | "failed" | "simulated"
    transcript: str                  # plain-text full transcript
    transcript_turns: list[dict]     # [{"role": "agent"|"user", "content": str}]
    call_successful: Optional[bool] = None   # from Retell post-call extraction
    call_summary: Optional[str] = None       # from Retell post-call extraction
    user_sentiment: Optional[str] = None     # from Retell post-call extraction
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None


class RetellVoiceClient:
    """
    Thin wrapper around retell-sdk for outbound debt collections calls.

    Uses a single pre-configured Retell agent (RETELL_AGENT_ID).
    The agent's system prompt is managed on the Retell dashboard or via
    update_agent_prompt() for programmatic updates from the learning loop.
    """

    def __init__(self) -> None:
        self._client = None
        if settings.retell_api_key:
            try:
                from retell import Retell
                self._client = Retell(api_key=settings.retell_api_key)
            except ImportError:
                print("[WARN] retell_client: retell-sdk not installed — run: uv add retell-sdk")

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError("Retell client not initialized — check RETELL_API_KEY in .env")

    # ------------------------------------------------------------------
    # Agent prompt management (called by learning loop on promotion)
    # ------------------------------------------------------------------

    def update_agent_prompt(self, system_prompt: str) -> None:
        """
        Update the LLM prompt on the pre-created Retell agent.
        Called when the learning loop promotes a new prompt version.

        The agent_id is fixed (RETELL_AGENT_ID). Only the LLM's
        general_prompt is updated — voice, latency settings unchanged.
        """
        self._require_client()
        agent_id = settings.retell_agent_id
        if not agent_id:
            raise RuntimeError("RETELL_AGENT_ID not set — configure in .env")

        # Retrieve current agent to get its llm_id
        agent = self._client.agent.retrieve(agent_id)
        response_engine = getattr(agent, "response_engine", None)
        if response_engine is None:
            raise RuntimeError(f"Agent {agent_id} has no response_engine (not a Single Prompt Agent?)")

        llm_id = getattr(response_engine, "llm_id", None)
        if not llm_id:
            raise RuntimeError(f"Could not find llm_id on agent {agent_id}")

        self._client.llm.update(llm_id, general_prompt=system_prompt)
        print(f"[retell] Updated LLM prompt on agent={agent_id}, llm={llm_id}")

    # ------------------------------------------------------------------
    # Call lifecycle
    # ------------------------------------------------------------------

    def make_call(
        self,
        to_number: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Initiate outbound call using the pre-configured agent.
        Returns call_id immediately — call is async.

        Args:
            to_number: borrower E.164 phone number
            metadata: dict stored on call record (borrower_id, stage, etc.)
        """
        self._require_client()
        agent_id = settings.retell_agent_id
        from_number = settings.retell_phone_number
        if not agent_id:
            raise RuntimeError("RETELL_AGENT_ID not set")
        if not from_number:
            raise RuntimeError("RETELL_PHONE_NUMBER not set")

        call = self._client.call.create_phone_call(
            agent_id=agent_id,
            to_number=to_number,
            from_number=from_number,
            metadata=metadata or {},
        )
        print(f"[retell] Call initiated: call_id={call.call_id}, to={to_number}")
        return call.call_id

    def get_transcript(
        self,
        call_id: str,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
    ) -> RetellCallResult:
        """
        Poll until call ends, return transcript + post-call extraction data.

        Prefer webhook over polling in production (webhook.py handles call_ended).
        Polling is used as fallback when webhook is unavailable or during testing.

        Args:
            call_id: from make_call()
            poll_interval: seconds between polls (default 3s)
            timeout: max seconds to wait; raises TimeoutError if exceeded
        """
        self._require_client()
        deadline = time.time() + timeout
        terminal_statuses = {"ended", "error"}

        while time.time() < deadline:
            call = self._client.call.retrieve(call_id)
            status = getattr(call, "call_status", "unknown")

            if status in terminal_statuses:
                return self._build_result(call, status)

            time.sleep(poll_interval)

        raise TimeoutError(
            f"Retell call {call_id} did not complete within {timeout}s"
        )

    def get_call_result(self, call_id: str) -> RetellCallResult:
        """
        Retrieve a completed call's result without polling.
        Used from webhook handler after call_ended event arrives.
        """
        self._require_client()
        call = self._client.call.retrieve(call_id)
        return self._build_result(call, getattr(call, "call_status", "ended"))

    def _build_result(self, call, status: str) -> RetellCallResult:
        turns = self._extract_turns(call)
        transcript_text = self._turns_to_text(turns)
        duration = getattr(call, "duration_ms", None)

        # Post-call extraction fields (configured on Retell dashboard)
        call_analysis = getattr(call, "call_analysis", None) or {}
        if hasattr(call_analysis, "__dict__"):
            call_analysis = call_analysis.__dict__

        return RetellCallResult(
            call_id=call.call_id,
            status="completed" if status == "ended" else "failed",
            transcript=transcript_text,
            transcript_turns=turns,
            call_successful=call_analysis.get("call_successful"),
            call_summary=call_analysis.get("call_summary"),
            user_sentiment=call_analysis.get("user_sentiment"),
            duration_seconds=duration / 1000.0 if duration else None,
            error_message=getattr(call, "disconnection_reason", None) if status == "error" else None,
        )

    def _extract_turns(self, call) -> list[dict]:
        raw = getattr(call, "transcript_object", None) or []
        turns = []
        for item in raw:
            role = getattr(item, "role", "unknown")
            content = getattr(item, "content", "")
            turns.append({"role": role, "content": content})
        return turns

    def _turns_to_text(self, turns: list[dict]) -> str:
        lines = []
        for t in turns:
            prefix = "Agent" if t["role"] == "agent" else "Borrower"
            lines.append(f"{prefix}: {t['content']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Eval mode — text simulation (no real call)
    # ------------------------------------------------------------------

    def simulate_as_text(
        self,
        system_prompt: str,
        borrower_description: str,
        max_turns: int = 10,
    ) -> RetellCallResult:
        """
        EVAL_MODE fallback: runs agent prompt as text chat, no phone call.
        transcript_turns format matches production output exactly.
        """
        from src.agents.simulator import SimulatedBorrower
        from src.llm.client import LLMClient

        llm = LLMClient()
        borrower_io = SimulatedBorrower(llm=llm, persona_description=borrower_description)

        messages: list[dict] = []
        turns: list[dict] = []

        begin = (
            "This is an automated call from a licensed collections agency. "
            "This call may be recorded. "
            "Am I speaking with the account holder?"
        )
        messages.append({"role": "assistant", "content": begin})
        turns.append({"role": "agent", "content": begin})

        for _ in range(max_turns - 1):
            borrower_reply = borrower_io.get_response(begin if len(messages) == 1 else messages[-1]["content"])
            if borrower_reply is None:
                break
            messages.append({"role": "user", "content": borrower_reply})
            turns.append({"role": "user", "content": borrower_reply})

            agent_reply = llm.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=300,
            )
            messages.append({"role": "assistant", "content": agent_reply})
            turns.append({"role": "agent", "content": agent_reply})

        transcript_text = self._turns_to_text(turns)
        return RetellCallResult(
            call_id=f"sim_{int(time.time())}",
            status="simulated",
            transcript=transcript_text,
            transcript_turns=turns,
            call_successful=None,
            call_summary=None,
            user_sentiment=None,
        )
