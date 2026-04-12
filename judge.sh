#!/usr/bin/env bash
# =============================================================================
# CopperTree — Judge Quick Start
# Run this to see the full system in action.
#
# Requirements:
#   1. uv installed  →  curl -LsSf https://astral.sh/uv/install.sh | sh
#   2. .env file populated (copy .env.example, fill in 3 keys)
#
# Usage:
#   ./judge.sh
# =============================================================================
set -e

echo ""
echo "============================================================"
echo "  CopperTree — Judge Quick Start"
echo "============================================================"
echo ""

# ── Check .env ────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env file not found."
  echo ""
  echo "  cp .env.example .env"
  echo "  # then fill in AZURE_OPENAI_API_KEY, ANTHROPIC_API_KEY, MONGO_URI"
  exit 1
fi

set -a; source .env; set +a

for var in AZURE_OPENAI_API_KEY ANTHROPIC_API_KEY MONGO_URI; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is not set in .env"
    exit 1
  fi
done

# ── Check uv ─────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
  echo "ERROR: uv not found."
  echo "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# ── Install dependencies ──────────────────────────────────────────
echo "[1/5] Installing dependencies..."
uv sync -q

# ── Seed database ─────────────────────────────────────────────────
echo "[2/5] Seeding database..."
PYTHONPATH=. uv run python scripts/seed_db.py

# ── Run eval ──────────────────────────────────────────────────────
echo ""
echo "[3/5] Running 5 evaluated conversations (Claude Sonnet judge)..."
echo "      This takes ~2 minutes and costs ~\$0.10 on Claude."
echo ""
PYTHONPATH=. uv run python scripts/run_eval.py --agent assessment --n 5 --seed 42

# ── Run learning loop ─────────────────────────────────────────────
echo ""
echo "[4/5] Running 1 learning loop iteration..."
echo "      Proposes a prompt improvement → tests it → statistical gate."
echo ""
PYTHONPATH=. uv run python scripts/run_eval.py --loop --agent assessment --n 5 --seed 42 --iterations 1

# ── Reports ───────────────────────────────────────────────────────
echo ""
echo "[5/5] Generating reports..."
PYTHONPATH=. uv run python scripts/bootstrap_decision_journal.py
PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format html --output evolution_report.html 2>/dev/null || true
PYTHONPATH=. uv run python scripts/cost_breakdown.py

echo ""
echo "============================================================"
echo "  Done. Results:"
echo ""
echo "  Per-conversation scores + judge reasoning:"
echo "    ls data/eval_runs/*.jsonl"
echo ""
echo "  Evolution report (open in browser):"
echo "    open evolution_report.html"
echo ""
echo "  Decision journal:"
echo "    cat DECISION_JOURNAL.md"
echo "============================================================"
echo ""
