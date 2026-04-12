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
    # Find the actual max version to avoid duplicate key errors on re-runs
    latest = prompt_versions.find_one({"agent": agent}, sort=[("version", -1)])
    try:
        max_existing = (
            int(latest["version"]) if latest and isinstance(latest, dict) else 0
        )
    except (KeyError, TypeError, ValueError):
        max_existing = 0
    version = max(parent_version + 1, max_existing + 1)
    doc_id = f"{agent}_v{version}"
    prompt_versions.insert_one(
        {
            "_id": doc_id,
            "agent": agent,
            "version": version,
            "parent_version": parent_version,
            "prompt_text": prompt_text,
            "token_count": token_count,
            "is_current": False,
            "change_description": change_description,
            "eval_results": None,
        }
    )
    return doc_id


def update_eval_results(doc_id: str, eval_results: dict) -> None:
    if prompt_versions.find_one({"_id": doc_id}) is None:
        raise ValueError(f"Prompt version {doc_id!r} not found")
    prompt_versions.update_one(
        {"_id": doc_id}, {"$set": {"eval_results": eval_results}}
    )


def promote_version(doc_id: str, eval_results: dict | None = None) -> None:
    doc = prompt_versions.find_one({"_id": doc_id})
    if doc is None:
        raise ValueError(f"Prompt version {doc_id!r} not found")
    if eval_results is not None:
        prompt_versions.update_one(
            {"_id": doc_id}, {"$set": {"eval_results": eval_results}}
        )
    prompt_versions.update_many(
        {"agent": doc["agent"], "is_current": True},
        {"$set": {"is_current": False}},
    )
    prompt_versions.update_one({"_id": doc_id}, {"$set": {"is_current": True}})


def rollback(agent: str, to_version: int) -> None:
    _rollback_id = f"{agent}_v{to_version}"
    doc = prompt_versions.find_one({"_id": _rollback_id})
    if doc is None:
        raise ValueError(f"Prompt version {_rollback_id!r} not found")
    prompt_versions.update_many(
        {"agent": doc["agent"], "is_current": True},
        {"$set": {"is_current": False}},
    )
    prompt_versions.update_one({"_id": _rollback_id}, {"$set": {"is_current": True}})
