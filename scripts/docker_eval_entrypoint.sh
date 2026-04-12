#!/usr/bin/env bash
# =============================================================================
# Docker eval entrypoint. Seeds DB, runs eval + learning loop, generates reports.
# Expects MONGO_URI, API keys etc. from environment (passed via .env).
# =============================================================================
set -euo pipefail

SEED="${EVAL_SEED:-42}"
N="${EVAL_N:-5}"
AGENT="${EVAL_AGENT:-assessment}"
ITERATIONS="${EVAL_ITERATIONS:-1}"

echo ""
echo "============================================================"
echo "  CopperTree Docker Eval"
echo "  Agent: ${AGENT}  N: ${N}  Seed: ${SEED}"
echo "============================================================"
echo ""

# ── Verify MongoDB connectivity ──────────────────────────────────
echo "[1/6] Checking MongoDB connection..."
uv run python -c "
from pymongo import MongoClient
import os, sys
try:
    c = MongoClient(os.environ['MONGO_URI'], serverSelectionTimeoutMS=5000)
    c.admin.command('ping')
    print('      MongoDB OK.')
except Exception as e:
    print(f'ERROR: Cannot reach MongoDB: {e}')
    sys.exit(1)
"

# ── Seed ─────────────────────────────────────────────────────────
echo "[2/6] Seeding database..."
PYTHONPATH=/app uv run python scripts/seed_db.py

# ── Baseline eval ────────────────────────────────────────────────
echo ""
echo "[3/6] Running ${N} evaluated conversations (Claude Sonnet judge)..."
PYTHONPATH=/app uv run python scripts/run_eval.py \
  --agent "${AGENT}" --n "${N}" --seed "${SEED}"

# ── Learning loop ────────────────────────────────────────────────
echo ""
echo "[4/6] Running learning loop (${ITERATIONS} iteration)..."
PYTHONPATH=/app uv run python scripts/run_eval.py \
  --loop --agent "${AGENT}" --n "${N}" --seed "${SEED}" --iterations "${ITERATIONS}"

# ── Reports ──────────────────────────────────────────────────────
echo ""
echo "[5/6] Generating reports..."
PYTHONPATH=/app uv run python scripts/bootstrap_decision_journal.py
cp -f /app/DECISION_JOURNAL.md /app/data/DECISION_JOURNAL.md 2>/dev/null || true
PYTHONPATH=/app uv run python scripts/generate_evolution_report.py \
  --agent "${AGENT}" --format html \
  --output /app/data/evolution_report.html 2>/dev/null || true
PYTHONPATH=/app uv run python scripts/generate_evolution_report.py \
  --agent "${AGENT}" --format json --include-raw \
  --output /app/data/evolution_report.json 2>/dev/null || true

# ── Cost breakdown ───────────────────────────────────────────────
echo ""
echo "[6/6] Cost breakdown:"
PYTHONPATH=/app uv run python scripts/cost_breakdown.py
PYTHONPATH=/app uv run python scripts/cost_breakdown.py --format json --output /app/data/cost_breakdown.json

echo ""
echo "============================================================"
echo "  Done! Artifacts written to ./data/"
echo ""
echo "  Eval runs:        data/eval_runs/*.jsonl"
echo "  Evolution report:  data/evolution_report.html"
echo "  Decision journal:  DECISION_JOURNAL.md"
echo "============================================================"
echo ""
