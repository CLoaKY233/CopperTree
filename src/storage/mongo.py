from pymongo import MongoClient
from src.config import settings

_client: MongoClient | None = None


def _get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongo_uri)
    return _client


def _get_db():
    return _get_client().get_database(settings.mongo_db)


def ping_db() -> None:
    _get_db().command("ping")


case_files = _get_db()["case_files"]
transcripts = _get_db()["transcripts"]
prompt_versions = _get_db()["prompt_versions"]
eval_runs = _get_db()["eval_runs"]
cost_log = _get_db()["cost_log"]
