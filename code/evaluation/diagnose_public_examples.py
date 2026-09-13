#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path


CODE = Path(__file__).resolve().parents[1]
REPO = CODE.parent
sys.path.insert(0, str(CODE))

from buy_or_wait.data import Dataset
from buy_or_wait.decision import FinancialAgent


FIELDS = (
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
)


def text(value) -> str:
    return str(value) if value is not None else ""


def build_report(dataset: Dataset, agent: FinancialAgent) -> dict:
    examples = []
    for request in dataset.sample_requests:
        profile = dataset.profiles[request.user_id]
        actual = agent.decide(request).row()
        expected = dataset.sample_answers[request.request_id]
        streams = []
        for stream in agent.forecaster.recurring_streams(request, profile):
            streams.append({
                "category": stream["category"],
                "direction": stream["direction"],
                "amount": text(stream["amount"]),
                "representative_event_id": stream["representative"].event_id,
                "description": stream["representative"].description,
                "evidence_count": len(stream["events"]),
                "recurrence": list(stream["recurrence"]),
                "confidence": stream.get("confidence", {}),
                "projected_dates": [
                    day.isoformat() for day in agent.forecaster._stream_dates(
                        stream, request.request_date, agent.forecaster.horizon_end(request)
                    )
                ],
            })
        baseline = agent.forecaster.trajectory(request, profile)
        low_day, low_balance = min(baseline.items(), key=lambda item: (item[1], item[0]))
        dated_flows = agent.forecaster.daily_cashflows(request, profile)
        evidence_trace = []
        for record in agent.forecaster._resolved_future_debits(request, profile):
            evidence_trace.append({
                "event_id": record["event"].event_id,
                "description": record["event"].description,
                "original_amount": text(record["original_amount"]),
                "resolved_amount": text(record["amount"]),
                "original_date": record["original_day"].isoformat(),
                "resolved_date": record["day"].isoformat(),
                "resolution_rule": record["resolution_rule"],
                "provenance": record["provenance"],
            })
        safe_today, earliest = agent.forecaster.baseline_capacity(request, profile)
        base_candidates = agent._candidate_plans(request, profile, safe_today, earliest)
        evaluated = [agent.forecaster.evaluate(request, profile, item) for item in base_candidates]
        changed_candidates = agent._plans_with_changes(request, profile, base_candidates)
        candidates = sorted(evaluated + changed_candidates, key=agent._rank)
        mismatches = {
            field: {"expected": expected[field], "actual": actual[field]}
            for field in FIELDS if expected[field] != actual[field]
        }
        examples.append({
            "request_id": request.request_id,
            "user_id": request.user_id,
            "opening_balance": text(profile.available_balance),
            "minimum_balance": text(profile.minimum_balance),
            "requested_amount": text(request.requested_amount),
            "deadline": request.desired_completion_date.isoformat(),
            "mismatches": mismatches,
            "projected_low": {"date": low_day.isoformat(), "balance": text(low_balance)},
            "dated_nonzero_flows": [
                {"date": day.isoformat(), "amount": text(dated_flows[day])}
                for day in sorted(dated_flows) if dated_flows[day]
            ],
            "streams": streams,
            "candidate_ranking": [
                {
                    "rank_key": [text(value) for value in agent._rank(candidate)],
                    "method": candidate.method,
                    "option_id": candidate.option_id,
                    "safe": candidate.safe,
                    "total_payable": text(candidate.total_payable),
                    "payments": [
                        {"date": day.isoformat(), "amount": text(amount)}
                        for day, amount in candidate.payments
                    ],
                    "changes": [change.serialize() for change in candidate.changes],
                    "minimum_projected_balance": text(candidate.minimum_projected_balance),
                }
                for candidate in candidates
            ],
            "evidence_trace": evidence_trace,
            "selected": actual,
        })
    return {
        "schema_version": "public-diagnostics-v1",
        "examples": examples,
        "recommendation_changing_mismatches": [
            item["request_id"] for item in examples
            if any(field in item["mismatches"] for field in (
                "affordability_status", "recommended_payment_method", "payment_plan"
            ))
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain public-example mismatches")
    parser.add_argument("--output", type=Path, default=CODE / "evaluation" / "public_diagnostics.json")
    args = parser.parse_args()
    dataset = Dataset(REPO / "dataset")
    agent = FinancialAgent(dataset)
    report = build_report(dataset, agent)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    mismatches = sum(bool(item["mismatches"]) for item in report["examples"])
    print(f"Wrote diagnostics for {len(report['examples'])} examples; {mismatches} differ.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
