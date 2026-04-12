# CopperTree

AI-powered debt collections pipeline with self-improving agents, professional evaluation infrastructure, and full FDCPA compliance enforcement.

## What it does

Three-stage pipeline per borrower, orchestrated by Temporal:

1. **Assessment (chat)** — AI agent verifies identity, gathers financial situation and hardship signals
2. **Resolution (voice via Retell)** — negotiates a payment arrangement using assessment context
3. **Final Notice (chat)** — closes with a commitment or delivers a final notice

The system evaluates itself using a dual-model architecture: **gpt-5.4-mini** runs the agents, **Claude Sonnet** judges the output across 24 metrics and 10 FDCPA compliance checks. A self-learning loop proposes and statistically validates prompt improvements.

---

## Quick Start (Judge / Reviewer)

### Prerequisites
- Python 3.11+ and `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A populated `.env` file

### 1. Configure

```bash
cp .env.example .env
```

Fill in three values:
```
AZURE_OPENAI_API_KEY=...    ← Azure OpenAI key
ANTHROPIC_API_KEY=...       ← Anthropic key (Claude Sonnet judge)
MONGO_URI=mongodb+srv://... ← MongoDB Atlas URI
```

### 2. Run

```bash
./judge.sh
```

That's it. No Docker, no manual setup. This single script:
- Installs dependencies
- Seeds the database
- Runs 5 evaluated conversations (Claude Sonnet scores each on 24 metrics)
- Runs 1 learning loop iteration (proposes a prompt improvement → tests it → statistical gate)
- Prints cost breakdown and generates an HTML report

**Takes ~3 minutes. Costs ~$0.10 on Claude.**

### 3. Read the results

```bash
# HTML report — open in browser
open evolution_report.html

# Per-conversation scores, judge reasoning, full transcripts
ls data/eval_runs/*.jsonl

# Promote/reject decisions with statistical gate details
cat DECISION_JOURNAL.md

# Cost breakdown
PYTHONPATH=. uv run python scripts/cost_breakdown.py
```

---

## Docker (Alternative)

If you prefer Docker over local Python, the eval profile runs the full pipeline in a single container using your cloud MongoDB:

```bash
# Build and run (~5 minutes)
docker compose --profile eval up --exit-code-from eval-runner

# Artifacts land in ./data/:
ls data/eval_runs/*.jsonl          # per-conversation scores
cat data/DECISION_JOURNAL.md       # decision journal
open data/evolution_report.html    # evolution report
cat data/cost_breakdown.json       # cost breakdown
```

Override parameters:
```bash
EVAL_N=10 EVAL_SEED=1337 docker compose --profile eval up --exit-code-from eval-runner
```

For the full stack (Temporal + local MongoDB + worker — for live collection workflows):
```bash
docker compose --profile full up
```

This starts MongoDB, Temporal, PostgreSQL, the worker, and the Temporal UI (http://localhost:8080).

---

## Full Reproduction

For a timestamped artifact bundle with config snapshot, eval results, learning loop, evolution report, cost breakdown, and decision journal:

```bash
./reproduce.sh                        # default: n=5, seed=42, 1 iteration
./reproduce.sh --n 20 --iterations 2  # better statistics (~$4 total)
```

Output: `data/reproductions/{timestamp}/` — see [REPRODUCE.md](REPRODUCE.md) for the full artifact inventory.

---

## Local Development

```bash
# Install dependencies
uv sync

# Seed database
PYTHONPATH=. uv run python scripts/seed_db.py

# Run eval (5 conversations)
PYTHONPATH=. uv run python scripts/run_eval.py --agent assessment --n 5 --seed 42

# Run learning loop (1 iteration)
PYTHONPATH=. uv run python scripts/run_eval.py --loop --agent assessment --n 5 --seed 42 --iterations 1

# Generate evolution report (CLI / JSON / HTML)
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format json --include-raw --output evolution_report.json
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format html --output evolution_report.html

# Cost breakdown
PYTHONPATH=. uv run python scripts/cost_breakdown.py
PYTHONPATH=. uv run python scripts/cost_breakdown.py --format json --output cost_breakdown.json

# DGM meta-evaluation demo
PYTHONPATH=. uv run python scripts/run_eval.py --meta-eval --demo --agent assessment --n 10

# Tests
uv run pytest tests/ -v
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Temporal Workflow: CollectionsWorkflow                  │
│                                                         │
│  Activity 1          Activity 2          Activity 3     │
│  ┌──────────┐        ┌──────────┐        ┌──────────┐  │
│  │Assessment│──────▶ │Resolution│──────▶ │  Final   │  │
│  │  (chat)  │handoff │ (voice)  │handoff │  Notice  │  │
│  └──────────┘        └──────────┘        └──────────┘  │
│                                                         │
│  Agent model: gpt-5.4-mini (Azure, $20 budget)         │
│  Judge model: claude-sonnet-4-6 (Anthropic, $30 budget) │
└─────────────────────────────────────────────────────────┘
```

### Self-Learning Loop

```
Current prompt
     │
     ▼
Baseline eval (N conversations, Claude judge)
     │
     ▼
Failure analysis (bottom 10 conversations)
     │
     ▼
Proposer (gpt-5.4-mini suggests one targeted change)
     │
     ▼
Candidate eval (same seeds — paired comparison)
     │
     ▼
Statistical gate:
  Gate 1: 100% compliance pass rate required
  Gate 2: Compliance must not regress (Wilcoxon, p < 0.05)
  Gate 3: Composite improvement significant (Wilcoxon, p < 0.05)
  Gate 4: Bootstrap 95% CI lower bound > 0 (10,000 resamples)
     │
     ▼
Promote or reject → DECISION_JOURNAL.md
```

---

## Evaluation Framework

**24 metrics across 5 dimensions:**

| Dimension | Sub-metrics | Hard Gate |
|-----------|-------------|-----------|
| Compliance | 10 FDCPA checks (Mini-Miranda, validation rights, no false threats, cease-contact, ...) | Yes — any failure → composite = 0.0 |
| Quality | Turn efficiency, info extraction, escalation, empathy | No |
| Continuity | Handoff utilization, contradictions, redundancy | No |
| Outcome | Resolution type, commitment specificity, terms, engagement | No |
| Safety | Hallucination, boundaries, prompt injection | Yes — hallucination < 0.5 → composite = 0.0 |

**Composite formula:**
```
if compliance_fail OR hallucination < 0.5:  composite = 0.0
else: 0.25·compliance + 0.30·quality + 0.25·outcome + 0.20·safety
```

---

## Compliance

FDCPA rules enforced at two layers:

**Deterministic (pre-LLM):** Time-of-day §1692c(a)(1), stop-contact §1692c(c), debt dispute §1692g(b), hardship detection — these fire on regex before the agent sees the message and cannot be bypassed by a bad prompt.

**Judge-evaluated:** 10 FDCPA checks including Mini-Miranda §1692e(11), validation rights §1692g, no false threats §1692d/e — hard-gated to 0.0 composite on any failure.

---

## DGM Meta-Evaluation

The system can detect and fix flaws in its own evaluation logic. Demo:

```bash
PYTHONPATH=. uv run python scripts/run_eval.py --meta-eval --demo --agent assessment --n 10
```

A deliberately flawed judge (compliance weighted at 0.25 instead of hard-gated) would promote an aggressive, non-compliant prompt. `MetaEvaluator` detects `compliance_not_hard_gated`, re-runs under the correct judge, and blocks promotion.

---

## File Structure

```
src/
  agents/          — assessment, resolution, final_notice agents + simulator
  compliance/      — FDCPA regex checks, PII redactor
  evaluation/      — judge (Claude Sonnet), 24-metric framework, runner, reporter
  handoff/         — HandoffPacket, 500-token context budget
  learning/        — learning loop, prompt proposer, Wilcoxon stats, decision journal
  llm/             — Azure LLMClient, AnthropicJudgeClient, cost tracker
  models/          — CaseFile, DebtInfo, NegotiationLedger Pydantic models
  storage/         — MongoDB collections, prompt registry
  voice/           — Retell client
  worker.py        — Temporal worker entrypoint

scripts/
  run_eval.py                    — eval, learning loop, DGM demo
  generate_evolution_report.py   — CLI/JSON/HTML evolution reports
  cost_breakdown.py              — LLM spend aggregation
  bootstrap_decision_journal.py  — backfill DECISION_JOURNAL.md from MongoDB
  snapshot_config.py             — redacted config artifact
  seed_db.py                     — populate prompt registry + borrower profiles

prompts/v1/        — assessment, resolution, final_notice prompt templates
data/
  scenarios/       — borrower_profiles.json (5 personas)
  eval_runs/       — per-run JSONL + summaries
  reproductions/   — timestamped artifact bundles from reproduce.sh
```

---

## Key Documents

| File | Contents |
|------|----------|
| `WRITEUP.md` | Full technical writeup: architecture, dual-model strategy, 24-metric framework, judge design, statistical gate, DGM, compliance strategy, cost tracking, known limitations |
| `REPRODUCE.md` | Step-by-step reproduction guide, artifact directory layout, troubleshooting |
| `DECISION_JOURNAL.md` | Append-only log of every learning loop promote/reject decision with gate details |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | Yes | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | `gpt-5.4-mini` | Agent model deployment name |
| `MONGO_URI` | Yes | — | MongoDB connection string |
| `MONGO_DB` | No | `collections_agents` | Database name |
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key (Claude Sonnet judge) |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Judge model |
| `ANTHROPIC_BUDGET_USD` | No | `30.0` | Anthropic spend ceiling |
| `AZURE_BUDGET_USD` | No | `20.0` | Azure spend ceiling |
| `RETELL_API_KEY` | No | — | Retell API key (voice stage) |
| `EVAL_MODE` | No | `true` | Skip Temporal, run eval pipeline directly |
