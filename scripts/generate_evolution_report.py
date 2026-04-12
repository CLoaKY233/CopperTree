"""
Generate an evolution report for a CopperTree agent's learning history.

Usage:
    PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment
    PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format json
    PYTHONPATH=. uv run python scripts/generate_evolution_report.py --agent assessment --format html --output report.html
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.evaluation.reporter import EvolutionReporter


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CopperTree evolution report")
    parser.add_argument(
        "--agent",
        default="assessment",
        choices=["assessment", "resolution", "final_notice"],
    )
    parser.add_argument("--format", default="cli", choices=["cli", "json", "html"])
    parser.add_argument(
        "--output", default=None, help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include per-conversation raw scores in JSON output",
    )
    args = parser.parse_args()

    # For JSON format, include raw by default unless explicitly disabled
    include_raw = args.include_raw or args.format == "json"

    reporter = EvolutionReporter()
    report = reporter.generate(args.agent, include_raw=include_raw)

    if report.n_iterations == 0:
        print(
            f"[reporter] No learning iterations found for agent '{args.agent}' in MongoDB."
        )
        print(
            "[reporter] Run the learning loop first: python scripts/run_eval.py --loop --agent ..."
        )
        return

    if args.format == "cli":
        output = reporter.format_cli(report)
    elif args.format == "json":
        output = reporter.format_json(report, include_raw=include_raw)
    else:
        output = reporter.format_html(report)

    if args.output:
        Path(args.output).write_text(output)
        print(f"[reporter] Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
