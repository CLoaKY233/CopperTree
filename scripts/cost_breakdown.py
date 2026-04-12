"""
CopperTree cost breakdown — aggregate LLM spend from cost_log collection.

Usage:
    # All-time summary
    PYTHONPATH=. uv run python scripts/cost_breakdown.py

    # Specific run
    PYTHONPATH=. uv run python scripts/cost_breakdown.py --run-id eval_assessment_42_abc123

    # All runs for an agent's learning loop
    PYTHONPATH=. uv run python scripts/cost_breakdown.py --agent assessment --learning-loop

    # JSON output (for artifacts)
    PYTHONPATH=. uv run python scripts/cost_breakdown.py --format json --output cost_breakdown.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.config import settings
from src.storage.mongo import cost_log


def _all_time_breakdown() -> dict:
    """Full aggregation: per-provider, per-role, per-model, budget utilization."""
    try:
        # By provider
        by_provider_rows = list(
            cost_log.aggregate(
                [
                    {
                        "$group": {
                            "_id": "$provider",
                            "total": {"$sum": "$cost_usd"},
                            "calls": {"$sum": 1},
                            "input_tokens": {"$sum": "$input_tokens"},
                            "output_tokens": {"$sum": "$output_tokens"},
                        }
                    }
                ]
            )
        )
        by_provider = {
            (r["_id"] or "unknown"): {
                "total_usd": round(r["total"], 6),
                "calls": r["calls"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
            }
            for r in by_provider_rows
        }

        # By role
        by_role_rows = list(
            cost_log.aggregate(
                [
                    {
                        "$group": {
                            "_id": "$role",
                            "total": {"$sum": "$cost_usd"},
                            "calls": {"$sum": 1},
                        }
                    }
                ]
            )
        )
        by_role = {
            (r["_id"] or "unknown"): {
                "total_usd": round(r["total"], 6),
                "calls": r["calls"],
            }
            for r in by_role_rows
        }

        # By model
        by_model_rows = list(
            cost_log.aggregate(
                [
                    {
                        "$group": {
                            "_id": {"model": "$model", "provider": "$provider"},
                            "total": {"$sum": "$cost_usd"},
                            "input_tokens": {"$sum": "$input_tokens"},
                            "output_tokens": {"$sum": "$output_tokens"},
                            "calls": {"$sum": 1},
                        }
                    }
                ]
            )
        )
        by_model = []
        for r in by_model_rows:
            id_obj = r.get("_id") or {}
            by_model.append(
                {
                    "model": id_obj.get("model") or "unknown",
                    "provider": id_obj.get("provider") or "unknown",
                    "total_usd": round(r["total"], 6),
                    "calls": r["calls"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                }
            )

        # Per run_id summary (top 20 most recent)
        by_run_rows = list(
            cost_log.aggregate(
                [
                    {
                        "$group": {
                            "_id": "$run_id",
                            "total": {"$sum": "$cost_usd"},
                            "calls": {"$sum": 1},
                        }
                    },
                    {"$sort": {"total": -1}},
                    {"$limit": 20},
                ]
            )
        )
        by_run = [
            {
                "run_id": r["_id"],
                "total_usd": round(r["total"], 6),
                "calls": r["calls"],
            }
            for r in by_run_rows
        ]

        grand_total = sum(r["total_usd"] for r in by_provider.values())

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "grand_total_usd": round(grand_total, 6),
            "by_provider": by_provider,
            "by_role": by_role,
            "by_model": by_model,
            "by_run": by_run,
            "budget_utilization": {
                "azure": {
                    "spent": round(
                        by_provider.get("azure", {}).get("total_usd", 0.0), 4
                    ),
                    "budget": settings.azure_budget_usd,
                    "pct": round(
                        by_provider.get("azure", {}).get("total_usd", 0.0)
                        / settings.azure_budget_usd
                        * 100,
                        1,
                    ),
                },
                "anthropic": {
                    "spent": round(
                        by_provider.get("anthropic", {}).get("total_usd", 0.0), 4
                    ),
                    "budget": settings.anthropic_budget_usd,
                    "pct": round(
                        by_provider.get("anthropic", {}).get("total_usd", 0.0)
                        / settings.anthropic_budget_usd
                        * 100,
                        1,
                    ),
                },
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


def _format_cli(data: dict) -> str:
    lines = []
    lines.append("═" * 65)
    lines.append("  CopperTree — LLM Cost Breakdown")
    lines.append(f"  Generated: {data.get('generated_at', 'unknown')}")
    lines.append("─" * 65)

    if "error" in data:
        lines.append(f"  ERROR: {data['error']}")
        return "\n".join(lines)

    lines.append(f"  Grand total: ${data['grand_total_usd']:.4f}")
    lines.append("")

    # Budget utilization
    bu = data.get("budget_utilization", {})
    lines.append("  Budget utilization:")
    for provider, info in bu.items():
        bar_width = 30
        filled = int(min(info["pct"], 100) / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        lines.append(
            f"    {provider:10s}  [{bar}]  "
            f"${info['spent']:.4f} / ${info['budget']:.2f}  ({info['pct']:.1f}%)"
        )

    lines.append("")
    lines.append("  By provider:")
    for provider, info in data.get("by_provider", {}).items():
        lines.append(
            f"    {provider:12s}  ${info['total_usd']:.4f}  "
            f"({info['calls']} calls, "
            f"{info['input_tokens']:,} in + {info['output_tokens']:,} out tokens)"
        )

    lines.append("")
    lines.append("  By role:")
    for role, info in sorted(data.get("by_role", {}).items()):
        lines.append(
            f"    {role:12s}  ${info['total_usd']:.4f}  ({info['calls']} calls)"
        )

    lines.append("")
    lines.append("  By model:")
    for m in sorted(data.get("by_model", []), key=lambda x: -x["total_usd"]):
        lines.append(
            f"    [{m['provider']:10s}] {m['model']:35s}  "
            f"${m['total_usd']:.4f}  ({m['calls']} calls)"
        )

    if data.get("by_run"):
        lines.append("")
        lines.append("  Top runs by cost:")
        for r in data["by_run"][:10]:
            rid = (r["run_id"] or "null")[:45]
            lines.append(f"    {rid:45s}  ${r['total_usd']:.4f}")

    lines.append("═" * 65)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="CopperTree cost breakdown")
    parser.add_argument("--run-id", help="Breakdown for a specific run_id")
    parser.add_argument("--agent", help="Agent name (for --learning-loop)")
    parser.add_argument(
        "--learning-loop",
        action="store_true",
        help="Show breakdown for all runs of an agent",
    )
    parser.add_argument("--format", default="cli", choices=["cli", "json"])
    parser.add_argument("--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.run_id:
        from src.llm.cost_tracker import get_run_breakdown

        data = get_run_breakdown(args.run_id)
    elif args.learning_loop and args.agent:
        from src.llm.cost_tracker import get_agent_loop_breakdown

        data = get_agent_loop_breakdown(args.agent)
        data["generated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        data = _all_time_breakdown()

    if args.format == "json":
        output = json.dumps(data, indent=2)
    else:
        output = _format_cli(data)

    if args.output:
        Path(args.output).write_text(output)
        print(f"[cost] Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
