from src.agents.base import ConversationIO
from src.llm.client import LLMClient


class SimulatedBorrower:
    """
    ConversationIO implementation that uses the LLM to simulate a borrower.
    Used in tests and in Temporal activities before real chat/voice I/O is wired up.
    """

    def __init__(self, llm: LLMClient, persona_description: str) -> None:
        self.llm = llm
        self.persona_description = persona_description
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

        if any(phrase in response.lower() for phrase in ["goodbye", "need to go", "have to go", "bye"]):
            self._done = True

        return response
