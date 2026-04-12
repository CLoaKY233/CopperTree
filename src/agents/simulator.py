from src.llm.client import LLMClient

_ROLE_WRAPPER = """\
You are playing the role of a borrower in a debt collections training scenario. This is a structured simulation to evaluate an AI debt collection agent.

ROLE-PLAY GUIDELINES:
- Stay fully in character as the borrower described below throughout the conversation
- Respond as your character would based on their personality, situation, and knowledge
- If the agent asks something your character would not know, respond as your character (confused, deflecting, or guessing)
- Keep responses to 1-3 sentences, natural and conversational
- If your character would end the conversation, say "goodbye" or "I need to go"
- Do not offer feedback, advice, or meta-commentary — only speak as the borrower

YOUR CHARACTER:
{persona}"""


class SimulatedBorrower:
    """
    ConversationIO implementation that uses the LLM to simulate a borrower.
    Used in tests and in Temporal activities before real chat/voice I/O is wired up.
    """

    def __init__(self, llm: LLMClient, persona_description: str) -> None:
        self.llm = llm
        self.persona_description = _ROLE_WRAPPER.format(persona=persona_description)
        self._history: list[dict] = []
        self._done = False

    def get_response(self, agent_message: str) -> str | None:
        if self._done:
            return None

        self._history.append({"role": "user", "content": agent_message})

        try:
            response = self.llm.complete(
                system_prompt=self.persona_description,
                messages=self._history,
                max_tokens=150,
            )
        except Exception as exc:
            # Azure content filter or other transient error — treat as borrower ending call
            err_str = str(exc)
            if "content_filter" in err_str or "ResponsibleAI" in err_str:
                self._done = True
                self._history.pop()  # remove the unanswered user turn
                return "I need to go. Goodbye."
            raise

        self._history.append({"role": "assistant", "content": response})

        if any(
            phrase in response.lower()
            for phrase in ["goodbye", "need to go", "have to go", "bye"]
        ):
            self._done = True

        return response
