#!/usr/bin/env bash
# Full pipeline reproduction from clean state.
# Requires: Docker, uv, and a .env file with Azure OpenAI credentials.
set -e

echo "=== CopperTree Reproduction Script ==="
echo ""

# Start infrastructure
echo "[1/5] Starting infrastructure (mongo, temporal, temporal-db)..."
docker compose up -d mongo temporal temporal-db

echo "[2/5] Waiting for services to be healthy (30s)..."
sleep 30

# Seed database
echo "[3/5] Seeding MongoDB..."
docker compose run --rm seeder

# Run evaluation
echo "[4/5] Running evaluation pipeline (eval mode)..."
EVAL_MODE=true uv run python scripts/run_eval.py --agent assessment --n 60 --seed 42

echo ""
echo "[5/5] Running learning loop (2 iterations)..."
EVAL_MODE=true uv run python scripts/run_eval.py --loop --agent assessment --iterations 2

echo ""
echo "[bonus] Running DGM meta-evaluation demo..."
EVAL_MODE=true uv run python scripts/run_eval.py --meta-eval --demo --agent assessment --n 20

echo ""
echo "=== Reproduction complete ==="
