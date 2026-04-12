# CopperTree — Reproduction Guide

Every result in this project can be reproduced from a clean clone with a single command.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | Required for local runs |
| `uv` | ≥ 0.4 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | ≥ 24.0 | Only needed for Docker eval profile |
| `.env` | — | Populate from `.env.example` (see below) |

### Populate `.env`

```bash
cp .env.example .env
# Fill in:
#   AZURE_OPENAI_API_KEY    — your Azure OpenAI API key
#   ANTHROPIC_API_KEY       — Anthropic API key (for Claude Sonnet judge)
#   MONGO_URI               — MongoDB Atlas connection string
```

---

## Option A: Quick Start (recommended)

```bash
./judge.sh
```

Requires only Python 3.11+ and `uv`. Seeds the database, runs 5 evaluated conversations, runs 1 learning loop iteration, generates reports. Takes ~3 minutes, costs ~$0.10 on Claude.

---

## Option B: Full reproduction with artifacts

```bash
./reproduce.sh
```

Runs the full pipeline and produces a timestamped artifact directory:

1. Seeds the database (prompt registry + borrower profiles)
2. Captures a redacted config snapshot (git SHA, model names, budgets)
3. Runs baseline eval: **N=5 conversations**, seed=42, assessment agent
4. Runs **1 learning loop iteration** (propose → eval → gate → promote/reject)
5. Backfills `DECISION_JOURNAL.md` from MongoDB
6. Generates evolution report in CLI, JSON, and HTML formats
7. Generates cost breakdown by provider and role

Output: `data/reproductions/{timestamp}/`

### Larger eval (more reliable statistics)

```bash
./reproduce.sh --n 20 --iterations 2
```

Cost estimate: ~$1.20 Azure + ~$3.50 Anthropic for N=20 × 4 runs.

---

## Option C: Docker eval profile

Runs the full eval pipeline in a Docker container, using your cloud MongoDB from `.env`:

```bash
docker compose --profile eval up --exit-code-from eval-runner
```

Artifacts land in `./data/`:
- `data/eval_runs/*.jsonl` — per-conversation scores
- `data/DECISION_JOURNAL.md` — decision journal
- `data/evolution_report.html` — HTML report
- `data/cost_breakdown.json` — cost breakdown

Override parameters:
```bash
EVAL_N=10 EVAL_SEED=1337 docker compose --profile eval up --exit-code-from eval-runner
```

---

## Option D: Full stack with Temporal (live workflow mode)

```bash
docker compose --profile full up
```

Starts Temporal + PostgreSQL + worker + seeder + Temporal UI (http://localhost:8080).
Uses cloud MongoDB from `.env`. Use this profile for testing live voice/chat collection workflows.

---

## Artifact Directory Layout

After `./reproduce.sh`:

```
data/reproductions/{timestamp}/
├── config.json                 # Redacted settings, git SHA, model versions
├── baseline_eval.jsonl         # Per-conversation scores, judge reasoning, transcripts
├── baseline_eval_summary.json  # Aggregated stats for the baseline run
├── baseline_eval.log           # Full stdout from the eval run
├── learning_loop/
│   ├── loop.log                # Full stdout from the learning loop
│   └── eval_assessment_*.jsonl # Candidate eval JSONL files
├── evolution_report.cli        # Human-readable score trajectory + stats
├── evolution_report.json       # Full JSON with Wilcoxon p, bootstrap CI, raw scores
├── evolution_report.html       # HTML report (open in browser)
├── cost_breakdown.json         # LLM spend by provider, role, model, run_id
└── DECISION_JOURNAL.md         # Timestamped promote/reject decisions with gate details
```

### Key files explained

**`baseline_eval.jsonl`** — One JSON object per evaluated conversation:
```json
{
  "conversation_id": "eval_assessment_42_abc_c000",
  "persona": "cooperative",
  "transcript": [...],
  "scores": {
    "composite": 0.766,
    "compliance": { "compliance_pass": true, "score": 0.92, ... },
    "quality": { "score": 0.78, ... },
    "outcome": { "resolution_label": "no_deal", "score": 0.62 },
    "safety": { "hallucination": 1.0, "score": 0.97 }
  },
  "judge_reasoning": "The agent delivered...",
  "gate_failed": null
}
```

**`evolution_report.json`** — Includes per-iteration statistical analysis:
```json
{
  "iterations": [{
    "wilcoxon_p_value": 0.12,
    "bootstrap_ci_lower": -0.05,
    "bootstrap_ci_upper": 0.31,
    "per_persona_deltas": { "combative": { "delta": +0.18 }, ... },
    "baseline_conversations": [...],
    "candidate_conversations": [...]
  }]
}
```

**`DECISION_JOURNAL.md`** — Append-only, timestamped audit trail:
```
## 2026-04-12T14:30:00Z — assessment_v5 → assessment_v6

**Decision:** REJECTED
**Gate 1** (100% compliance): FAIL (candidate=80%)
...
```

**`cost_breakdown.json`** — Full cost accounting:
```json
{
  "grand_total_usd": 1.83,
  "by_provider": { "azure": { "total_usd": 0.09 }, "anthropic": { "total_usd": 1.74 } },
  "by_role": { "agent": ..., "borrower": ..., "judge": ..., "proposer": ... }
}
```

---

## Running individual steps

```bash
# Just the eval
PYTHONPATH=. uv run python scripts/run_eval.py --agent assessment --n 5 --seed 42

# Just the learning loop
PYTHONPATH=. uv run python scripts/run_eval.py --loop --agent assessment --n 5 --iterations 1

# DGM meta-evaluation demo
PYTHONPATH=. uv run python scripts/run_eval.py --meta-eval --demo --agent assessment --n 10

# Evolution report (CLI / JSON / HTML)
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format json --include-raw
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format html --output evolution_report.html

# Cost breakdown
PYTHONPATH=. uv run python scripts/cost_breakdown.py
PYTHONPATH=. uv run python scripts/cost_breakdown.py --format json --output cost_breakdown.json

# Tests
uv run pytest tests/ -v
```

---

## Seeds and Determinism

All eval runs use a fixed seed (default 42). The seed controls:
- Which borrower profiles are selected for each conversation slot (round-robin by persona)
- The per-conversation seed (`seed + i`) passed to `_build_case_file()` which determines debt amounts, dates, and account numbers

The LLM calls themselves are not seeded (temperature > 0), so exact transcripts will vary between runs. Composite score means will vary by ≤0.05 across reruns with identical seeds.

---

## Troubleshooting

**MongoDB connection error:** Make sure `MONGO_URI` in `.env` points to a live MongoDB Atlas instance.

**Azure 400 content_filter error:** Normal for combative personas — the simulator catches this and returns a graceful end-of-conversation response. Does not affect eval validity.

**Anthropic rate limit:** The judge client retries with exponential backoff (1s, 2s, 4s, 8s, 16s). If you hit the $30 budget ceiling, reduce `--n` or reset the `cost_log` collection.

**`assessment_v5` not found:** Run `PYTHONPATH=. uv run python scripts/seed_db.py` to ensure the prompt registry is populated.

**Docker eval fails:** Make sure `.env` is populated — the Docker eval profile reads API keys and `MONGO_URI` directly from your `.env` file. It uses your cloud MongoDB, not a local container.
