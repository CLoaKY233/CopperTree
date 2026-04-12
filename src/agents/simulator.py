from src.llm.client import LLMClient

_ROLE_WRAPPER = """\
You are role-playing as a specific person in a debt collections scenario. You MUST stay in character at all times.

STRICT RULES:
- NEVER break character or acknowledge that you are an AI or language model
- NEVER say "I don't have a real-world identity" or similar meta-commentary
- NEVER reference being a simulation, test, or automated system
- If the agent asks something your character wouldn't know, respond as your character would (confused, deflecting, guessing)
- Keep responses to 1-3 sentences, natural and conversational
- If your character would end the conversation, say "goodbye" or "I need to go"
- Respond only as your character — do not offer advice, templates, or suggestions to the agent

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

        response = self.llm.complete(
            system_prompt=self.persona_description,
            messages=self._history,
            max_tokens=150,
        )

        self._history.append({"role": "assistant", "content": response})

        if any(
            phrase in response.lower()
            for phrase in ["goodbye", "need to go", "have to go", "bye"]
        ):
            self._done = True

        return response
