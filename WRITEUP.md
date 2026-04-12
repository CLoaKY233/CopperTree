# CopperTree Technical Writeup

## Architecture Overview

CopperTree is a three-stage AI debt collections pipeline orchestrated by Temporal, with MongoDB for persistence and Azure OpenAI as the LLM backend. Each borrower runs as a single named Temporal workflow (`CollectionsWorkflow`), and all three stages execute as sequential activities within that workflow.

**Stage 1 — Assessment (chat).** The agent gathers identity, financial situation, and hardship signals via a multi-turn chat conversation. Every borrower message is run through deterministic regex checks (`check_compliance_triggers`) before reaching the LLM. If a stop-contact trigger fires, the workflow returns immediately with `outcome: stop_contact` and no further contact is attempted. The stage exits with a `HandoffPacket` serialized to JSON.

**Stage 2 — Resolution (voice via Retell).** The resolution agent takes the assessment handoff as context and attempts negotiation. This stage is currently stubbed — the Retell integration compiles but has not been tested against the live Retell API. The stage has a 15-minute `start_to_close_timeout` and uses a `non_retryable_error_types=["ApplicationError"]` policy so FDCPA time-of-day violations (`check_contact_time`) are not retried.

**Stage 3 — Final Notice (chat).** Receives the resolution handoff and either closes with a payment commitment or delivers a final notice. The workflow returns the terminal outcome, any commitments recorded, and a `stop_contact` flag.

Temporal provides durable execution — if a worker crashes mid-stage, the workflow resumes from the last completed activity. Retry policies use exponential backoff (5s initial, 2x coefficient, max 3 attempts).

---

## Cross-Modal Handoff Design

Context passes between stages as a `HandoffPacket` (Pydantic model), serialized to JSON and passed as an activity argument. The packet contains:

- `borrower_id` — correlation key
- `stage` — which stage produced this packet
- `key_facts` — a curated list of strings (identity verified, income status, hardship flags, commitments made, offers made)
- `compliance_flags` — full dict from the compliance checker (stop_contact, hardship_flag, dispute_flag)
- `sentiment` — borrower sentiment string from the case file
- `token_count` — actual tokens consumed by this packet, measured post-truncation

The packet is built by `build_handoff_packet()` in `src/handoff/summarizer.py`, which pulls from a `CaseFile` object and extracts only the fields that carry decision-relevant signal for the next stage. Raw conversation history is not forwarded — only structured facts. This is intentional: forwarding raw transcript would consume most of the context budget, and the next stage agent does not need to re-read the full conversation to pick up where it left off.

The chat→voice transition (Assessment → Resolution) passes the packet as a JSON string argument to the Retell activity. The voice→chat transition (Resolution → Final Notice) follows the same pattern.

---

## 500-Token Context Budget

`src/handoff/token_budget.py` enforces a hard cap of 2000 total tokens for the combined system prompt + handoff context, with a 500-token sub-cap on the handoff context itself.

`enforce_budget(system_prompt, handoff_context)` works in two phases:

1. If `handoff_context` is provided, it is first truncated to `MAX_HANDOFF=500` tokens using tiktoken (`cl100k_base` encoding).
2. The remaining budget (`2000 - tokens(handoff_context)`) is computed, and the system prompt is truncated to that remainder.

This means handoff context gets priority up to its 500-token cap, and the system prompt fills the rest. Truncation is token-exact (re-encode and slice), not character-based, so the model always receives syntactically complete tokens.

**The core tradeoff:** 500 tokens is enough for structured key-facts (a dozen bullet points) but not for free-text summaries or raw transcript excerpts. A richer handoff would require either a larger context budget (cost increases) or a smarter compression step (summarization before serialization). Currently the budget is fixed; there is no dynamic allocation based on model or conversation complexity.

---

## Self-Learning Loop

The `LearningLoop` class in `src/learning/loop.py` runs one improvement iteration per call. The cycle:

1. **Baseline eval** — evaluate the current prompt on N conversations (default 60) using the `EvalRunner` and `ConversationJudge`.
2. **Failure analysis** — sort by composite score, take the bottom 10 conversations.
3. **Candidate proposal** — the `PromptProposer` (GPT-4o) analyzes the worst conversations and proposes a single targeted modification to the current prompt. The single-change rule prevents multi-dimensional edits that would make it impossible to attribute improvements or regressions to a specific change.
4. **Candidate eval** — run the candidate prompt on the identical seeds as the baseline (paired comparison). Identical seeds ensure the same simulated borrower profiles are used, so score differences are attributable to the prompt change alone.
5. **Statistical gate** (`should_promote` in `src/learning/stats.py`) — two hard rules before promotion:
   - `candidate_compliance_rate` must be 1.0 (zero compliance violations across all conversations — the composite hard gate means any compliance failure scores 0.0, so this is equivalent to no zero-scored conversations).
   - The 95% bootstrap confidence interval lower bound of paired score deltas must be strictly greater than 0. This rules out noise-level improvements. Bootstrap uses 1000 resamplings of the paired delta distribution.
6. **Promotion or rejection** — promoted prompts are written to MongoDB via `promote_version()`. Rejected candidates are saved but not promoted.

**Judge dimensions (4):**
- `compliance` — hard gate: AI disclosure, Mini-Miranda, no false threats, hardship handling, stop-contact respect.
- `continuity` — did the agent use handoff context correctly? How many repeated questions?
- `effectiveness` — resolution outcome (deal/partial/no_deal/disengaged), identity verified, turns to outcome.
- `borrower_experience` — professional tone, appropriate empathy.

Composite scoring (production judge): if `compliance.score < 1.0` or `violations` is non-empty, composite = 0.0 regardless of other dimensions. Otherwise: `0.35 * effectiveness + 0.35 * continuity + 0.30 * borrower_experience`.

---

## DGM Meta-Evaluation

The Darwin Godel Machine demo in `src/evaluation/meta_eval.py` demonstrates that the system can audit and fix its own evaluation logic.

**The planted flaw:** `ConversationJudge_FLAWED` treats compliance as a weighted component (0.25) rather than a hard gate. Under this judge, an aggressive prompt scoring 0.9 on effectiveness but 0.7 on compliance yields composite ≈ 0.77, which beats a compliant baseline at 0.65. The aggressive prompt gets promoted despite having active compliance violations.

**The six-step demo:**
1. Run baseline under flawed judge.
2. Generate an adversarial prompt that adds aggressive pressure language ("explain consequences of non-payment", "move quickly to resolution", "time is limited") — designed to maximize effectiveness scores while tending to skip compliance disclosures.
3. Run candidate under flawed judge — the inflated effectiveness score outweighs the compliance penalty. The flawed judge would promote it.
4. `MetaEvaluator.audit_evaluation_framework()` scans the promoted run records and flags any promoted prompt where `candidate_compliance_rate < 1.0`. It identifies the flaw as `compliance_not_hard_gated`.
5. Re-run baseline under the correct judge (`ConversationJudge` with hard gate).
6. Re-run aggressive candidate under correct judge — compliance violations set composite to 0.0, and the statistical gate's compliance requirement (100% pass rate) blocks promotion.

**Why this matters:** In a financial compliance environment, an evaluation framework that allows effectiveness to compensate for compliance failures is not just suboptimal — it is a regulatory liability. The meta-evaluator demonstrates that evaluation design itself must be tested and auditable, not assumed correct.

---

## Compliance Strategy

Eight FDCPA rules are enforced:

1. **Time-of-day** (§805(a)(1)) — `check_contact_time()` raises a non-retryable `ApplicationError` if the borrower's local hour is outside 8–20. Defaults to America/New_York if timezone is unknown.
2. **Stop contact** (§805(c)) — deterministic regex on every borrower message. If triggered, the workflow halts immediately.
3. **Debt dispute** (§809(b)) — deterministic regex detects explicit dispute language. Triggers `dispute_flag`. Caller must halt collection and issue a validation notice via `generate_validation_notice()`.
4. **Hardship detection** — regex flags financial distress. Agent system prompts are required to offer hardship options when flagged. The judge checks `hardship_handled`.
5. **AI disclosure** — judge verifies agent explicitly identified itself as AI.
6. **Recording disclosure** — judge verifies agent stated the call may be recorded.
7. **Mini-Miranda** — judge verifies the required "this is an attempt to collect a debt" disclosure was delivered.
8. **No false threats** — judge verifies no false legal threats or misrepresentations were made.

Rules 1–4 are enforced deterministically (regex + hard workflow logic). Rules 5–8 are enforced via the LLM judge with a hard gate: a single compliance failure floors the composite to 0.0, making promotion impossible. A compliance block is appended to every agent system prompt instructing the agent on required disclosures.

The key property: no prompt change can engineer away rules 1–4. Stop-contact and dispute detection happen before the LLM sees the message. Time-of-day check happens before the activity runs. Only the LLM-evaluated rules (5–8) can theoretically be degraded by a bad prompt — and the judge's hard gate ensures any degradation is caught at eval time.

---

## Known Limitations

- **SimulatedBorrower role inversion** — in multi-turn eval mode, the simulated borrower sometimes generates agent-side language (offering payment plans, not just responding to them). This inflates continuity and effectiveness scores in simulation, making evals somewhat optimistic.
- **No real chat UI** — the system is eval-mode only. There is no production-facing chat interface; conversations are simulated by the `EvalRunner` and `SimulatedBorrower`. Live deployment would require a chat transport layer.
- **Retell integration untested** — the voice stage compiles and the Retell activity is wired into the workflow, but it has not been validated against the live Retell API. Error handling for Retell-specific failure modes (call drops, webhook timeouts) is incomplete.
- **Cost ceiling not stress-tested** — the $20 ceiling is implemented as a guard in the LLM client, but it has not been validated under high-concurrency load. Parallel eval runs could exceed the limit before the guard fires.
- **No Statute of Limitations (SoL) check** — there is no check for whether the debt is time-barred in the borrower's state. Attempting to collect on an SoL-expired debt is a significant FDCPA risk.
- **Dispute validation notice delivery** — `generate_validation_notice()` returns a text string, but there is no delivery mechanism (mail, email, or in-platform message). The caller must implement delivery and logging. Until delivery is implemented, FDCPA §809(b) compliance on dispute handling is incomplete.

---

## Cost Budget

The `LLMClient` enforces a `$20` ceiling tracked via a `SpendTracker` that accumulates token costs against published Azure OpenAI pricing. When the ceiling is reached, further LLM calls are blocked.

**Model selection rationale:**
- `gpt-4o` is used for the judge and the prompt proposer. The judge requires high-quality reasoning over compliance nuances and long transcripts; the proposer needs to produce coherent, targeted prompt edits. Cheaper models produce more hallucinated compliance scores and less coherent proposals.
- The simulated borrower can use a cheaper model (e.g., `gpt-4o-mini`) since behavioral fidelity of the simulator is less critical than correctness of the judge. This is not yet parameterized in the current codebase but is the intended optimization path.
- A 60-conversation eval run with gpt-4o for all roles costs roughly $8–12, leaving headroom for one improvement iteration plus a candidate eval run within the $20 ceiling. Running `--loop` for multiple iterations without resetting the tracker will hit the ceiling mid-loop.
