"""
FastAPI webhook server — receives Retell call events.

Retell posts to this endpoint when a call ends. The webhook handler:
  1. Validates the request (optional HMAC signature if RETELL_WEBHOOK_SECRET set)
  2. Retrieves full call result from Retell API
  3. Stores result in MongoDB pending Temporal activity pickup

To run standalone (for testing):
    uv run python src/voice/webhook.py

In production, run alongside the Temporal worker:
    uv run python src/voice/webhook.py &
    uv run python src/worker.py

Configure on Retell dashboard:
    Agent Level Webhook URL: https://<your-host>/retell/webhook
    Webhook Events: call_ended, call_started (optional)
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

from src.config import settings
from src.storage.mongo import _get_db
from src.voice.retell_client import RetellVoiceClient

logger = logging.getLogger(__name__)
app = FastAPI(title="CopperTree Retell Webhook", docs_url=None, redoc_url=None)

_voice_client = RetellVoiceClient()


def _verify_signature(body: bytes, signature: str | None) -> None:
    """Validate Retell webhook HMAC-SHA256 signature if secret is configured."""
    secret = settings.retell_webhook_secret
    if not secret:
        return  # signature validation disabled
    if not signature:
        raise HTTPException(status_code=401, detail="Missing x-retell-signature header")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@app.post("/retell/webhook")
async def retell_webhook(
    request: Request,
    x_retell_signature: str | None = Header(default=None),
) -> dict:
    """
    Receives all Retell webhook events.
    Only call_ended is processed — others are acknowledged and ignored.
    """
    body = await request.body()
    _verify_signature(body, x_retell_signature)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    event = payload.get("event")
    call_id = payload.get("data", {}).get("call_id") or payload.get("call_id")

    logger.info(f"[webhook] Received event={event}, call_id={call_id}")

    if event != "call_ended":
        return {"status": "ignored", "event": event}

    if not call_id:
        raise HTTPException(status_code=400, detail="call_id missing from payload")

    await _process_call_ended(call_id, payload)
    return {"status": "ok", "call_id": call_id}


async def _process_call_ended(call_id: str, payload: dict) -> None:
    """
    Fetch full call result and store in MongoDB for Temporal activity pickup.
    Temporal's run_resolution activity polls this collection when webhook mode is active.
    """
    db = _get_db()
    retell_calls = db["retell_calls"]

    # Idempotency — skip if already processed
    if retell_calls.find_one({"_id": call_id}):
        logger.info(f"[webhook] call_id={call_id} already processed, skipping")
        return

    try:
        result = _voice_client.get_call_result(call_id)
    except Exception as e:
        logger.error(f"[webhook] Failed to retrieve call {call_id}: {e}")
        # Store error state so Temporal activity doesn't hang
        retell_calls.insert_one(
            {
                "_id": call_id,
                "status": "fetch_error",
                "error": str(e),
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    # Extract borrower_id from call metadata (set in make_call)
    borrower_id = payload.get("data", {}).get("metadata", {}).get("borrower_id")

    retell_calls.insert_one(
        {
            "_id": call_id,
            "borrower_id": borrower_id,
            "status": result.status,
            "transcript": result.transcript,
            "transcript_turns": result.transcript_turns,
            "call_successful": result.call_successful,
            "call_summary": result.call_summary,
            "user_sentiment": result.user_sentiment,
            "duration_seconds": result.duration_seconds,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    logger.info(
        f"[webhook] Stored call result: call_id={call_id}, borrower_id={borrower_id}, "
        f"status={result.status}, turns={len(result.transcript_turns)}"
    )


def wait_for_webhook_result(
    call_id: str, timeout: float = 600.0, poll_interval: float = 2.0
) -> dict | None:
    """
    Used by run_resolution activity to wait for webhook-delivered call result.
    Polls the retell_calls collection until the result arrives or timeout.

    Returns raw call doc or None on timeout.
    """
    import time

    db = _get_db()
    retell_calls = db["retell_calls"]
    deadline = time.time() + timeout

    while time.time() < deadline:
        doc = retell_calls.find_one({"_id": call_id})
        if doc:
            return doc
        time.sleep(poll_interval)

    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=settings.webhook_port)
