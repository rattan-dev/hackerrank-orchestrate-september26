#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from buy_or_wait import FinancialAgent
from buy_or_wait.data import Dataset
from buy_or_wait.validation import OUTPUT_COLUMNS, validate_decisions


def arguments() -> argparse.Namespace:
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Generate Buy or Wait? affordability decisions")
    parser.add_argument("--dataset", type=Path, default=repo / "dataset")
    parser.add_argument("--output", type=Path, default=repo / "output.csv")
    parser.add_argument("--check-samples", action="store_true")
    parser.add_argument("--use-llm", action="store_true", help="Use a configured compatible LLM for fact extraction")
    return parser.parse_args()


def write_output(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sample_report(dataset: Dataset, agent: FinancialAgent) -> None:
    fields = ["affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment"]
    scores = {field: 0 for field in fields}
    for request in dataset.sample_requests:
        actual = agent.decide(request).row()
        expected = dataset.sample_answers[request.request_id]
        for field in fields:
            scores[field] += actual[field] == expected[field]
    total = len(dataset.sample_requests)
    print("Public sample checks:")
    for field in fields:
        print(f"  {field}: {scores[field]}/{total}")


def main() -> int:
    args = arguments()
    try:
        dataset = Dataset(args.dataset.resolve(), use_llm=args.use_llm)
        agent = FinancialAgent(dataset)
        if args.check_samples:
            sample_report(dataset, agent)
        decisions = agent.decide_all()
        validate_decisions(dataset, dataset.requests, decisions)
        write_output(args.output.resolve(), [decision.row() for decision in decisions])
        print(f"Wrote {len(decisions)} validated decisions to {args.output.resolve()}")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
