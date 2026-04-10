from src.storage.mongo import prompt_versions


def get_current_prompt(agent: str) -> dict | None:
    return prompt_versions.find_one({"agent": agent, "is_current": True})


def save_new_version(
    agent: str,
    prompt_text: str,
    parent_version: int,
    change_description: str,
    token_count: int,
) -> str:
    version = parent_version + 1
    doc_id = f"{agent}_v{version}"
    prompt_versions.insert_one({
        "_id": doc_id,
        "agent": agent,
        "version": version,
        "parent_version": parent_version,
        "prompt_text": prompt_text,
        "token_count": token_count,
        "is_current": False,
        "change_description": change_description,
        "eval_results": None,
    })
    return doc_id


def promote_version(doc_id: str) -> None:
    doc = prompt_versions.find_one({"_id": doc_id})
    if doc is None:
        raise ValueError(f"Prompt version {doc_id!r} not found")
    prompt_versions.update_many(
        {"agent": doc["agent"], "is_current": True},
        {"$set": {"is_current": False}},
    )
    prompt_versions.update_one({"_id": doc_id}, {"$set": {"is_current": True}})


def rollback(agent: str, to_version: int) -> None:
    promote_version(f"{agent}_v{to_version}")
