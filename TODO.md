# CopperTree — TODO

Status as of 2026-04-10. Derived from a full 3-agent codebase audit.
Overall completion: ~30–35%.

Legend: `[ ]` not started · `[~]` partial · `[x]` done

---

## CRITICAL — Bugs that break things right now

- [ ] **`enforce_budget` raises instead of truncates** (`src/handoff/token_budget.py:21–37`)
  A prompt or handoff over the token limit crashes the Temporal activity (3 retries → permanent fail).
  Fix: drop lowest-priority `key_facts` entries until under `MAX_HANDOFF`, shorten system prompt sections until under `MAX_TOTAL`. Never raise — degrade gracefully.

- [ ] **`summarizer.py` ignores `enforce_budget` return value** (`src/handoff/summarizer.py:34`)
  `enforce_budget` is called but its result is discarded. Truncation is unreachable.
  Fix: use the returned `(system_prompt, handoff_context)` tuple.

- [ ] **`LLMClient.complete()` returns `None` on Azure content filter** (`src/llm/client.py:50`)
  `resp.choices[0].message.content` is `None` when content is filtered. Caller appends `None` to message list → downstream API error.
  Fix: null-check the return value; raise a typed `ContentFilteredError` that `base.py` can catch and handle separately from generic errors.

- [ ] **`resp.choices` can be empty → `IndexError`** (`src/llm/client.py:50`)
  Fix: guard with `if not resp.choices` and raise `ContentFilteredError`.

- [ ] **`cost_tracker.log_cost` has no error handling** (`src/llm/cost_tracker.py:11`)
  A MongoDB hiccup during cost logging kills the LLM call. Secondary concern must not take down primary functionality.
  Fix: wrap `insert_one` in `try/except`, log warning, continue.

- [ ] **Bare `except Exception` swallows errors silently** (`src/agents/base.py:136–143`)
  LLM failures, rate limits, network errors — all invisible to operators.
  Fix: `logger.exception(...)` before the `break`. Wire to structured logging or Sentry.

- [ ] **Extraction failure silently returns zero-state compliance** (`src/agents/assessment.py:82–86`, `src/agents/final_notice.py:73–75`)
  If `parse_llm_json` raises, the case file is saved with `ai_disclosed=False`, `recording_disclosed=False`, etc. Looks like a clean case in the DB.
  Fix: set a `extraction_failed: bool` flag on the transcript document; add to a human review queue.

- [ ] **Injection flags are collected but never persisted or acted on** (`src/agents/base.py:112–114`)
  `sanitize_borrower_input` returns flags into a local list that is never used again. Flagged text goes to the LLM unchanged.
  Fix: persist `injection_log` to the transcript document; if injection patterns fire, add a `needs_review: true` flag and consider ending the conversation early.

- [ ] **`budget.record_turn()` called before null-checking LLM response** (`src/agents/base.py:99–105`)
  Fix: check response is not `None` before recording the turn.

---

## CRITICAL — Security

- [ ] **Rotate credentials NOW** (`.env`)
  The Azure OpenAI API key and MongoDB Atlas credentials (`coppertree:7AE4H8blbIvWKKYr`) are in the working tree as plaintext. One `git add .` commits them permanently.
  Action: rotate both in Azure portal and MongoDB Atlas immediately. Add a pre-commit hook that blocks `.env` files.

- [ ] **Commitment amount not validated against debt record** (`src/agents/final_notice.py:81–87`)
  A hallucinating LLM can write a negative, zero, or astronomically large commitment to the ledger.
  Fix: validate `0 < commitment_amount <= case_file.debt.amount` and `commitment_type in case_file.debt.allowed_actions` before appending.

- [ ] **Identity verification is not cross-referenced with the database** (`src/agents/assessment.py`, `src/workflows/activities.py`)
  Whether the borrower "verified" their identity is determined by asking the LLM if the borrower confirmed their account digits. The LLM never checks the claimed digits against `case_file.partial_account`.
  Fix: deterministic check — extract the digit string from the borrower's message using regex and compare to `case_file.partial_account`.

- [ ] **`ai_disclosed` and `recording_disclosed` set from LLM self-assessment** (`src/agents/assessment.py:96–97`)
  The LLM is asked if it disclosed. A jailbroken or hallucinating LLM can lie.
  Fix: scan the first agent turn deterministically for the required phrases (e.g., "AI", "automated", "recorded"). Set flags from the scan result, not from extraction.

- [ ] **Mini-Miranda not verified deterministically**
  The compliance block instructs the LLM to include the Mini-Miranda warning. There is no code that verifies this phrase appears in the first agent message.
  Fix: scan first assistant message for "attempt to collect a debt" before the conversation proceeds. If absent, prepend it.

- [ ] **No Temporal authentication** (`src/worker.py:14`)
  `Client.connect()` with no mTLS, no namespace auth, no API key. Anyone who can reach the Temporal host can submit workflows.
  Fix: configure mTLS or API key auth before any non-local deployment.

- [ ] **PII stored in plaintext transcripts** (`src/workflows/activities.py:55–60`)
  Every borrower message is stored verbatim in `transcripts` collection — SSN fragments, account numbers, addresses, medical information.
  Fix: run `redact_pii(text)` (regex for SSN-like patterns, full account numbers) on every message before inserting. Set `pii_redacted: true` on the document.

---

## HIGH — Temporal / Activity safety

- [ ] **Activities are not idempotent — `transcripts.insert_one` on every retry** (`src/workflows/activities.py:55–60, 88–93`)
  3 Temporal retries = 3 transcript records for 1 conversation.
  Fix: add a unique index on `(borrower_id, stage, workflow_run_id)` to `transcripts`. Pass `workflow_run_id` via `activity.info().workflow_id` and use `update_one(..., upsert=True)`.

- [ ] **No stage guard at activity entry** (`src/workflows/activities.py:34, 74`)
  If `run_assessment` is retried after the case already advanced to RESOLUTION, it runs a full new LLM conversation against the case.
  Fix: at the top of each activity, check `case_file.stage` matches the expected stage. If already advanced, return the cached result without re-running.

- [ ] **`stop_contact=True` in DB not checked before re-running conversation** (`src/workflows/activities.py:34`)
  If the first run wrote `stop_contact=True` to MongoDB but crashed before returning, the retry loads the updated case file and runs a new conversation anyway.
  Fix: check `case_file.compliance.stop_contact` at activity start; if `True`, return `{"status": "stop_contact_already_set"}` immediately.

- [ ] **`run_final_notice` receives `handoff_json: str` but never deserializes to `HandoffPacket`** (`src/workflows/activities.py:74`)
  The handoff JSON is passed as raw string context. Token budget enforcement never runs on it properly.
  Fix: deserialize `HandoffPacket.model_validate_json(handoff_json)`, re-serialize with `build_handoff_packet` to enforce the 500-token budget before passing as `handoff_context`.

---

## HIGH — FDCPA / Legal compliance gaps

- [ ] **No time-of-day enforcement before workflow execution**
  FDCPA prohibits contact before 8am or after 9pm in the borrower's local time zone. Nothing enforces this.
  Fix: add `borrower_timezone: str` to `CaseFile`; add a Temporal workflow gate that checks current time in borrower's TZ before executing any activity. If out-of-window, use a Temporal timer to delay until 8am.

- [ ] **Debt dispute not detected**
  If a borrower says "I dispute this debt," all collection must stop until written verification is mailed. The regex patterns do not catch dispute language.
  Fix: add dispute patterns to `src/compliance/checker.py` (e.g., "I dispute", "not my debt", "prove I owe this"). Handle identically to stop-contact — break immediately, set `case_file.compliance.disputed = True`.

- [ ] **No debt validation notice generated**
  FDCPA requires written notice within 5 days of first contact including debt amount, creditor name, and right to dispute.
  Fix: after `run_assessment` completes, emit a validation notice document (letter/email template) to a `notices` collection. Mark `validation_notice_sent_at` on the case file.

- [ ] **Statute of limitations not checked**
  `default_date` exists in `DebtInfo` but is never read. Time-barred debts are pursued identically to valid ones.
  Fix: calculate age of debt from `default_date`; if past SoL (varies by state/debt type, default 6 years), flag the case and halt collection.

- [ ] **Call frequency limits not enforced**
  No throttle prevents contacting the same borrower multiple times per day or week.
  Fix: query `transcripts` collection for recent contact before executing the workflow. Enforce a configurable minimum gap between contacts.

---

## HIGH — Missing features (spec requirements)

- [ ] **Agent 2 — Voice / Retell pipeline** (`src/voice/` — empty)
  The entire middle stage of the pipeline is absent. Spec requires a voice agent that negotiates settlements over phone.
  Files to create:
  - `src/voice/retell_client.py` — register Retell agent, initiate call with handoff context as call metadata
  - `src/voice/transcript_extractor.py` — poll or receive Retell webhook for call transcript, extract structured data
  - `src/workflows/activities.py` — implement `run_resolution(borrower_id, handoff_json) -> dict`
  - Retell webhook endpoint (FastAPI route) to receive `call_started`, `agent_response`, `call_ended` events
  - Wire `run_resolution` into `collections.py` between assessment and final notice

- [ ] **Real borrower I/O** (`src/workflows/activities.py:39–46, 82–89`)
  Both activities hardwire `SimulatedBorrower`. No real borrower ever reached.
  Fix: create `src/agents/chat_io.py` with a `ChatIO(ConversationIO)` that reads/writes to a real message queue or WebSocket. Inject via activity parameter or env flag. `SimulatedBorrower` should only be used when `SIMULATION_MODE=true`.

- [ ] **Self-learning loop** (`src/evaluation/` and `src/learning/` — empty)
  Files to create:
  - `src/evaluation/judge.py` — LLM-as-judge that scores conversations on compliance, resolution rate, empathy, FDCPA risk (0–1 per dimension, composite weighted score)
  - `src/evaluation/runner.py` — runs N conversations per persona, stores per-conversation scores to `eval_runs` collection and `data/eval_runs/{run_id}.jsonl`
  - `src/evaluation/simulator.py` — persona-driven borrower runner covering all 5 required behaviors
  - `src/evaluation/meta_eval.py` — Darwin Godel layer: measures judge accuracy against hand-labeled ground truth, proposes judge prompt updates when accuracy < 0.85
  - `src/learning/proposer.py` — given failing eval runs + judge feedback, generates N candidate prompt mutations via LLM
  - `src/learning/stats.py` — bootstrap 95% CI, paired significance test (require lower CI bound > baseline mean before promotion)
  - `src/learning/loop.py` — outer orchestration: run eval → propose mutation → eval candidates → gate → promote or reject
  - `scripts/run_eval.py` — CLI: `--prompt-version`, `--seed`, `--n-runs`, `--agent`, writes JSONL + summary JSON

- [ ] **Statistical gate on `promote_version`** (`src/storage/prompt_registry.py`)
  Currently `promote_version(doc_id)` requires no evidence. A prompt with no eval data can be promoted.
  Fix: require `EvalResults` argument; enforce `composite_score_ci_95[0] > baseline_composite_mean` (lower CI bound must exceed baseline mean) before allowing promotion.

- [ ] **Darwin Godel meta-evaluation**
  The system must evaluate and improve its own evaluation methodology.
  Fix: maintain a hand-labeled dataset of "known good" and "known bad" conversations in `data/judge_ground_truth.jsonl`. After each eval run, measure judge precision/recall vs. ground truth. If accuracy < 0.85, trigger judge prompt update via `proposer.py`. Demonstrate at least one case where the meta-eval caught a flaw in the primary evaluator.

- [ ] **Global $20 LLM spend ceiling**
  Per-conversation budget exists (`ConversationBudget`). No outer loop guard.
  Fix: at the start of each eval iteration, query `cost_log` summed by `eval_run_id`. If projected total > $20, abort with a clear error. Tag every `log_cost` call with the current `eval_run_id`.

- [ ] **Missing personas: combative and confused** (`scripts/test_agent1.py`)
  Spec requires 5 personas. Only 3 exist (cooperative, evasive, hardship).
  Fix: add to `PERSONAS` list:
  - `combative`: angry, accusatory, denies owing the debt, may threaten to sue after 2–3 exchanges
  - `confused`: doesn't understand the call, asks for repetition, mixes up names/numbers, frustrated

- [ ] **Populate `data/scenarios/borrower_profiles.json`**
  Currently `[]`. Spec requires structured borrower data for reproducible runs.
  Fix: add 5 borrower profile objects (one per persona) with `borrower_id`, `debt`, `persona_description`, `seed`, `partial_account`. Wire into `SimulatedBorrower` via the seed script.

- [ ] **Reproducibility infrastructure**
  Fix:
  - Add `--seed` flag to `scripts/run_eval.py` and pass `seed` to every OpenAI call
  - Set `temperature=0` on judge and simulator calls for determinism
  - Write per-conversation output to `data/eval_runs/{run_id}.jsonl` (JSONL, one object per conversation)
  - Write summary to `data/eval_runs/{run_id}_summary.json` (means, SDs, bootstrap 95% CIs per metric)
  - Include `scripts/reproduce.sh` — single command that reruns the full eval pipeline end-to-end

- [ ] **Docker Compose — self-contained system** (`docker-compose.yml`)
  Fix: add services:
  - `mongo` — `mongo:7` with `mongo_data` volume (currently Atlas-only, cannot run fresh)
  - `worker` — app service running `uv run python src/worker.py`
  - `seeder` — one-shot `uv run python scripts/seed_db.py` that runs before worker starts
  Goal: `docker compose up` starts the full system in < 5 minutes on a fresh machine.

---

## MEDIUM — Architecture improvements

- [ ] **`is_complete()` uses brittle keyword matching** (`src/agents/assessment.py:68–75`, `src/agents/final_notice.py:56–63`)
  Closing signal keywords ("we'll be in touch", "resolution options") are fragile — LLM phrasing variation will miss them and the conversation loops to `max_turns`.
  Fix: add a structured signal to the extraction schema — `assessment_complete: bool` / `conversation_complete: bool`. Check this flag in `is_complete()` instead of string matching.

- [ ] **MongoDB collections initialized at module import time** (`src/storage/mongo.py:22–25`)
  Fix: make collection references lazy properties or use `functools.cached_property`. Don't connect at import.

- [ ] **Pricing dict falls back silently to wrong model** (`src/llm/client.py:39`)
  Fix: `raise KeyError` if model not in `PRICING`. Force explicit pricing entries for every model used.

- [ ] **SimulatedBorrower doesn't maintain proper conversation perspective** (`src/agents/simulator.py`)
  The simulator sends the agent's last message as `role: user` to an LLM with the borrower persona as system prompt. This works but doesn't correctly flip assistant/user roles across the full history.
  Fix: invert roles when building the simulator's history — agent messages become `user`, simulator responses become `assistant`.

- [ ] **Handoff packet serializes to JSON string, never back to `HandoffPacket`** (`src/workflows/activities.py`)
  The handoff crosses activity boundaries as `json.dumps(packet.model_dump())` and is never deserialized.
  Fix: deserialize on the receiving end; run token count and budget enforcement on the deserialized object, not the raw string.

- [ ] **No structured logging** (throughout)
  `print()` is used everywhere. No log levels, no request IDs, no structured fields.
  Fix: replace with `logging` module or `structlog`; include `borrower_id`, `stage`, `workflow_run_id` on every log line.

- [ ] **`enforce_budget` token counting uses `cl100k_base` encoding for all models** (`src/handoff/token_budget.py:7`)
  `cl100k_base` is the encoding for GPT-4 and GPT-3.5. `gpt-5.4-nano` may use a different tokenizer.
  Fix: resolve the correct encoding for the deployed model and document the assumption.

---

## LOW — Polish

- [ ] **`src/worker.py` has no graceful shutdown handling**
  Fix: catch `SIGTERM`, flush in-flight activities, close MongoDB connection cleanly.

- [ ] **`tests/` directory is empty**
  Fix: add `pytest`-based unit tests for at minimum:
  - `compliance/checker.py` — all regex patterns (stop-contact true/false positives, hardship, injection)
  - `handoff/token_budget.py` — budget enforcement edge cases
  - `llm/utils.py` — `parse_llm_json` with fenced, unfenced, invalid, and empty inputs
  - `storage/prompt_registry.py` — promote, rollback, save_new_version

- [ ] **`data/scenarios/borrower_profiles.json` should be the source of truth for seeds**
  Currently personas live only as Python strings in `test_agent1.py`. Move to JSON, load in all scripts.

- [ ] **`f"injection_pattern_detected"` is an f-string with no interpolation** (`src/compliance/checker.py:69`)
  Fix: `flags.append("injection_pattern_detected")` — remove the `f`.

- [ ] **`.env.example` shows stale service account fields** (`.env.example`)
  The example still references `MONGO_HOST`, `MONGO_APP`, `MONGO_SA_CLIENT_ID`, `MONGO_SA_CLIENT_SECRET` from an abandoned auth approach.
  Fix: clean `.env.example` to match the actual `config.py` fields: `MONGO_URI`, `MONGO_DB`, `TEMPORAL_HOST`.

---

## Build Order (recommended)

```
1. Fix the 3 crash bugs         (enforce_budget truncation, None return, cost_tracker try/except)
2. Fix idempotency + stage guards on Temporal activities
3. Add combative + confused personas, populate borrower_profiles.json
4. Build eval runner (run_eval.py) with JSONL output + seeds
5. Build LLM-as-judge scorer (evaluation/judge.py)
6. Add statistical gate to promote_version
7. Build prompt mutation engine (learning/proposer.py + loop.py)
8. Build Darwin Godel meta-eval (evaluation/meta_eval.py)
9. Build Agent 2 voice pipeline (voice/ + Retell integration)
10. Build real borrower I/O adapter (agents/chat_io.py)
11. Add Docker Compose services (mongo, worker, seeder)
12. FDCPA gaps (time-of-day, dispute detection, validation notice)
13. PII redaction before transcript storage
14. Statistical reproducibility (seeds, CSV/JSON, reproduce.sh)
15. Unit tests (tests/)
```
