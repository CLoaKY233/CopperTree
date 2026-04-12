"""
Seed MongoDB with initial test data:
- One test CaseFile document
- One prompt_versions document per agent (seeded from prompts/v1/*.txt)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import ASCENDING

from src.llm.client import LLMClient
from src.storage.mongo import case_files, ping_db, prompt_versions, transcripts

AGENTS = ["assessment", "resolution", "final_notice"]
PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "v1"

TEST_CASE = {
    "_id": "borrower_test_001",
    "borrower_id": "borrower_test_001",
    "stage": "assessment",
    "attempt": 1,
    "identity_verified": False,
    "partial_account": "4321",
    "debt": {
        "amount": 12450.0,
        "creditor": "XYZ Bank",
        "default_date": "2025-01-15",
        "allowed_actions": ["settlement", "payment_plan", "hardship_referral"],
    },
    "financial": {
        "income_status": None,
        "monthly_income_est": None,
        "obligations": None,
        "hardship_flags": [],
    },
    "negotiation": {
        "offers_made": [],
        "borrower_responses": [],
        "commitments": [],
        "objections": [],
    },
    "compliance": {
        "ai_disclosed": False,
        "recording_disclosed": False,
        "stop_contact": False,
        "hardship_offered": False,
    },
    "borrower_sentiment": None,
    "cooperation_level": None,
}


def seed_case_file() -> None:
    existing = case_files.find_one({"_id": TEST_CASE["_id"]})
    if existing:
        print(f"  case_files: {TEST_CASE['_id']} already exists, skipping")
        return
    case_files.insert_one(TEST_CASE)
    print(f"  case_files: inserted {TEST_CASE['_id']}")


def seed_prompts(llm: LLMClient) -> None:
    for agent in AGENTS:
        doc_id = f"{agent}_v1"
        existing = prompt_versions.find_one({"_id": doc_id})
        if existing:
            print(f"  prompt_versions: {doc_id} already exists, skipping")
            continue

        prompt_file = PROMPTS_DIR / f"{agent}.txt"
        prompt_text = prompt_file.read_text()
        token_count = llm.count_tokens(prompt_text)

        prompt_versions.insert_one(
            {
                "_id": doc_id,
                "agent": agent,
                "version": 1,
                "parent_version": None,
                "prompt_text": prompt_text,
                "token_count": token_count,
                "is_current": True,
                "change_description": "Initial version seeded from prompts/v1/",
                "eval_results": None,
            }
        )
        print(f"  prompt_versions: inserted {doc_id} ({token_count} tokens)")


def ensure_indexes() -> None:
    """Create indexes if they don't exist. Idempotent."""
    transcripts.create_index(
        [
            ("borrower_id", ASCENDING),
            ("stage", ASCENDING),
            ("workflow_run_id", ASCENDING),
        ],
        unique=True,
        name="transcript_idempotency",
    )
    print("  indexes: transcript_idempotency OK")


def reseed_prompts(llm: LLMClient) -> None:
    """Delete all prompt_versions and re-insert from v1 files."""
    prompt_versions.delete_many({})
    print("  prompt_versions: cleared all existing versions")
    for agent in AGENTS:
        prompt_file = PROMPTS_DIR / f"{agent}.txt"
        prompt_text = prompt_file.read_text()
        token_count = llm.count_tokens(prompt_text)
        doc_id = f"{agent}_v2"
        prompt_versions.insert_one(
            {
                "_id": doc_id,
                "agent": agent,
                "version": 2,
                "parent_version": 1,
                "prompt_text": prompt_text,
                "token_count": token_count,
                "is_current": True,
                "change_description": "v2: production-grade rewrite with template vars, amount ceilings, ordered disclosures, seamless handoff",
                "eval_results": None,
            }
        )
        print(f"  prompt_versions: inserted {doc_id} ({token_count} tokens)")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Delete and re-seed all prompts from v1 files",
    )
    args = parser.parse_args()

    print("Pinging MongoDB...")
    ping_db()
    print("  MongoDB: OK")

    llm = LLMClient()

    print("Seeding case_files...")
    seed_case_file()

    if args.reseed:
        print("Re-seeding prompt_versions (v2)...")
        reseed_prompts(llm)
    else:
        print("Seeding prompt_versions...")
        seed_prompts(llm)

    print("Ensuring indexes...")
    ensure_indexes()

    print("Done.")


if __name__ == "__main__":
    main()
