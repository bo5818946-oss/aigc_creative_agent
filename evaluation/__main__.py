"""CLI entry point: python -m evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation.runner import run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the 20-case AIGC workflow evaluation suite.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/evaluation",
        help="Directory for evaluation_report.md and .json",
    )
    args = parser.parse_args(argv)

    report = run_evaluation(output_dir=args.output_dir)
    metrics = report["metrics"]
    print(
        f"cases={metrics['total_cases']} "
        f"passed={metrics['suite_passed']} "
        f"failed={metrics['suite_failed']}"
    )
    print(
        "status_counts="
        + ", ".join(
            f"{key}:{value}"
            for key, value in sorted(metrics["status_counts"].items())
        )
    )
    print(
        "report="
        + str(Path(args.output_dir) / "evaluation_report.md")
    )
    print(
        "json="
        + str(Path(args.output_dir) / "evaluation_report.json")
    )
    return 0 if metrics["suite_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
