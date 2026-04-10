from src.storage.mongo import ping_db
from src.llm.client import LLMClient


def main() -> None:
    print("=== CopperTree Smoke Test ===\n")

    print("Checking MongoDB connection...")
    ping_db()
    print("  MongoDB: OK\n")

    print("Checking Azure OpenAI connection...")
    llm = LLMClient()
    response = llm.complete(
        system_prompt="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Say 'CopperTree is ready.' and nothing else."}],
        max_tokens=20,
    )
    print(f"  LLM response: {response}\n")

    print("All systems nominal.")


if __name__ == "__main__":
    main()
