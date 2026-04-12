"""
TerminalIO — real human borrower via stdin/stdout.
Used when EVAL_MODE=false for Assessment and Final Notice stages.
"""


class TerminalIO:
    """
    ConversationIO implementation that prints agent messages and reads your input.
    Type 'quit' or press Ctrl+C to end the conversation early.
    """

    def __init__(self, stage_label: str = "Agent") -> None:
        self.stage_label = stage_label

    def get_response(self, agent_message: str) -> str | None:
        print(f"\n\033[94m[{self.stage_label}]\033[0m {agent_message}\n")
        try:
            user_input = input("\033[92m[You]\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Conversation ended by user]")
            return None

        if user_input.lower() in ("quit", "exit", "bye", "q"):
            print("[Conversation ended]")
            return None

        return user_input if user_input else None
