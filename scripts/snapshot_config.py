"""
Emit a redacted configuration snapshot for reproducibility artifacts.

Outputs JSON with all settings EXCEPT actual secret values (API keys, passwords).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


_REDACT_KEYS = {
    "azure_openai_api_key",
    "anthropic_api_key",
    "retell_api_key",
    "mongo_uri",
    "retell_webhook_secret",
}


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _git_branch() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def main() -> None:
    from src.config import settings

    config = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "git_branch": _git_branch(),
        "models": {
            "agent": settings.azure_openai_deployment,
            "judge": settings.anthropic_model,
        },
        "budgets_usd": {
            "azure": settings.azure_budget_usd,
            "anthropic": settings.anthropic_budget_usd,
        },
        "eval_mode": settings.eval_mode,
        "mongo_db": settings.mongo_db,
        "settings_redacted": list(_REDACT_KEYS),
    }

    # Include env file keys (redacted)
    env_snapshot = {}
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key_lower = key.strip().lower()
            if key_lower in _REDACT_KEYS:
                env_snapshot[key.strip()] = "<REDACTED>"
            else:
                env_snapshot[key.strip()] = val.strip()
    config["env"] = env_snapshot

    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
