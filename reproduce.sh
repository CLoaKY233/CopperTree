#!/usr/bin/env bash
# =============================================================================
# CopperTree — Full Pipeline Reproduction Script
#
# Produces a timestamped artifact directory under data/reproductions/{ts}/
# containing: config snapshot, eval results, learning loop artifacts,
# evolution report (CLI + JSON + HTML), cost breakdown, and decision journal.
#
# Requirements:
#   - uv installed (https://docs.astral.sh/uv/)
#   - .env file with required credentials (see .env.example)
#
# Usage:
#   ./reproduce.sh                     # full run with seed=42, n=5
#   ./reproduce.sh --n 10              # larger eval (~$0.60 on Claude judge)
#   ./reproduce.sh --n 20 --iterations 2  # best statistics (~$4 total)
#
# Output:
#   data/reproductions/{timestamp}/
#     config.json               — redacted settings + git SHA
#     baseline_eval.jsonl       — per-conversation scores from baseline run
#     baseline_eval_summary.json
#     learning_loop/            — per-iteration artifacts
#     evolution_report.cli      — formatted text report
#     evolution_report.json     — full JSON with statistical analysis
#     evolution_report.html     — HTML report
#     cost_breakdown.json       — LLM spend breakdown by provider/role/model
#     DECISION_JOURNAL.md       — copy of the append-only decision log
# =============================================================================
set -euo pipefail

SEED=42
N=5
AGENT=assessment
ITERATIONS=1

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --n) N="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Load env
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# Verify required env vars
for var in AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_OPENAI_DEPLOYMENT MONGO_URI MONGO_DB ANTHROPIC_API_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is not set. Populate .env first (see .env.example)."
    exit 1
  fi
done

TS=$(date +%Y%m%dT%H%M%S)
ARTIFACT_DIR="data/reproductions/${TS}"
mkdir -p "${ARTIFACT_DIR}/learning_loop"

echo "============================================================"
echo "  CopperTree Reproduction"
echo "  Timestamp : ${TS}"
echo "  Agent     : ${AGENT}"
echo "  N         : ${N} conversations/run"
echo "  Seed      : ${SEED}"
echo "  Iterations: ${ITERATIONS} learning loop"
echo "  Artifacts : ${ARTIFACT_DIR}/"
echo "============================================================"
echo ""

# ── Step 1: Seed database ─────────────────────────────────────────
echo "[1/7] Seeding MongoDB (prompt registry + borrower profiles)..."
PYTHONPATH=. uv run python scripts/seed_db.py

# ── Step 2: Snapshot config ───────────────────────────────────────
echo ""
echo "[2/7] Capturing config snapshot..."
PYTHONPATH=. uv run python scripts/snapshot_config.py > "${ARTIFACT_DIR}/config.json"
echo "      Written: ${ARTIFACT_DIR}/config.json"

# ── Step 3: Baseline eval ─────────────────────────────────────────
echo ""
echo "[3/7] Running baseline eval (n=${N}, seed=${SEED}, agent=${AGENT})..."
PYTHONPATH=. uv run python scripts/run_eval.py \
  --agent "${AGENT}" \
  --n "${N}" \
  --seed "${SEED}" \
  2>&1 | tee "${ARTIFACT_DIR}/baseline_eval.log"

# Copy the JSONL + summary produced by the runner
LATEST_JSONL=$(ls -t data/eval_runs/eval_"${AGENT}"_"${SEED}"_*.jsonl 2>/dev/null | grep -v failures | grep -v summary | head -1 || true)
LATEST_SUMMARY=$(ls -t data/eval_runs/eval_"${AGENT}"_"${SEED}"_*_summary.json 2>/dev/null | head -1 || true)
if [ -n "${LATEST_JSONL}" ]; then
  cp "${LATEST_JSONL}" "${ARTIFACT_DIR}/baseline_eval.jsonl"
  echo "      Copied: ${ARTIFACT_DIR}/baseline_eval.jsonl"
fi
if [ -n "${LATEST_SUMMARY}" ]; then
  cp "${LATEST_SUMMARY}" "${ARTIFACT_DIR}/baseline_eval_summary.json"
fi

# ── Step 4: Learning loop ─────────────────────────────────────────
echo ""
echo "[4/7] Running learning loop (${ITERATIONS} iteration(s))..."
PYTHONPATH=. uv run python scripts/run_eval.py \
  --loop \
  --agent "${AGENT}" \
  --n "${N}" \
  --seed "${SEED}" \
  --iterations "${ITERATIONS}" \
  2>&1 | tee "${ARTIFACT_DIR}/learning_loop/loop.log"

# Copy all new eval_runs artifacts
for f in $(ls -t data/eval_runs/eval_"${AGENT}"_*.jsonl 2>/dev/null | head -20); do
  basename_f=$(basename "$f")
  if [ ! -f "${ARTIFACT_DIR}/learning_loop/${basename_f}" ]; then
    cp "$f" "${ARTIFACT_DIR}/learning_loop/"
  fi
done

# ── Step 5: Bootstrap decision journal ───────────────────────────
echo ""
echo "[5/7] Bootstrapping decision journal..."
PYTHONPATH=. uv run python scripts/bootstrap_decision_journal.py 2>&1
if [ -f "DECISION_JOURNAL.md" ]; then
  cp "DECISION_JOURNAL.md" "${ARTIFACT_DIR}/DECISION_JOURNAL.md"
  echo "      Copied: ${ARTIFACT_DIR}/DECISION_JOURNAL.md"
fi

# ── Step 6: Evolution report ──────────────────────────────────────
echo ""
echo "[6/7] Generating evolution report..."
PYTHONPATH=. uv run python scripts/generate_evolution_report.py \
  --agent "${AGENT}" \
  --format cli \
  --output "${ARTIFACT_DIR}/evolution_report.cli" 2>&1 || echo "[WARN] CLI report generation failed"

PYTHONPATH=. uv run python scripts/generate_evolution_report.py \
  --agent "${AGENT}" \
  --format json \
  --include-raw \
  --output "${ARTIFACT_DIR}/evolution_report.json" 2>&1 || echo "[WARN] JSON report generation failed"

PYTHONPATH=. uv run python scripts/generate_evolution_report.py \
  --agent "${AGENT}" \
  --format html \
  --output "${ARTIFACT_DIR}/evolution_report.html" 2>&1 || echo "[WARN] HTML report generation failed"

echo "      Written: evolution_report.{cli,json,html}"

# ── Step 7: Cost breakdown ────────────────────────────────────────
echo ""
echo "[7/7] Generating cost breakdown..."
PYTHONPATH=. uv run python scripts/cost_breakdown.py --format json --output "${ARTIFACT_DIR}/cost_breakdown.json"
PYTHONPATH=. uv run python scripts/cost_breakdown.py

# ── Final summary ─────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Reproduction complete."
echo "  Artifacts: ${ARTIFACT_DIR}/"
echo ""
ls -lh "${ARTIFACT_DIR}/"
echo ""
echo "  To review:"
echo "    cat ${ARTIFACT_DIR}/evolution_report.cli"
echo "    cat DECISION_JOURNAL.md"
echo "    open ${ARTIFACT_DIR}/evolution_report.html"
echo "============================================================"
