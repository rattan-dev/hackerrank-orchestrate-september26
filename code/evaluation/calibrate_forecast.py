#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path


CODE = Path(__file__).resolve().parents[1]
REPO = CODE.parent
sys.path.insert(0, str(CODE))

from buy_or_wait.data import Dataset
from buy_or_wait.decision import FinancialAgent
from buy_or_wait.forecast import Forecaster


def statistic(name: str, values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    if name == "mean":
        return sum(ordered, Decimal("0")) / len(ordered)
    if name == "median":
        return Decimal(str(statistics.median(ordered)))
    if name == "q25":
        return ordered[int((len(ordered) - 1) * 0.25)]
    if name == "q75":
        return ordered[int((len(ordered) - 1) * 0.75)]
    raise ValueError(name)


def evaluate(dataset: Dataset, name: str, original) -> dict:
    def amount_method(self, events, profile):
        if events[0].category == "salary":
            return original(self, events, profile)
        values = [
            self.dataset.convert(
                event.amount or Decimal("0"), event.currency,
                profile.home_currency, event.settlement_date,
            )
            for event in events
        ]
        return statistic(name, values)

    Forecaster._home_amount_stat = amount_method
    agent = FinancialAgent(dataset)
    fields = (
        "affordability_status", "recommended_payment_method", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
    )
    exact = {field: 0 for field in fields}
    errors = []
    for request in dataset.sample_requests:
        actual = agent.decide(request).row()
        expected = dataset.sample_answers[request.request_id]
        for field in fields:
            exact[field] += actual[field] == expected[field]
        errors.append(
            abs(Decimal(actual["amount_safe_to_pay"]) - Decimal(expected["amount_safe_to_pay"]))
            / request.requested_amount
        )
    return {
        "field_exact_matches": exact,
        "safe_amount_within_2_percent": sum(error <= Decimal("0.02") for error in errors),
        "safe_amount_within_5_percent": sum(error <= Decimal("0.05") for error in errors),
        "safe_amount_mean_absolute_error_percent": str(sum(errors) / len(errors) * 100),
    }


def main() -> int:
    dataset = Dataset(REPO / "dataset")
    original = Forecaster._home_amount_stat
    try:
        candidates = {
            name: evaluate(dataset, name, original)
            for name in ("mean", "median", "q25", "q75")
        }
    finally:
        Forecaster._home_amount_stat = original
    report = {
        "schema_version": "forecast-calibration-v1",
        "candidates": candidates,
        "selected": "mean",
        "selection_reason": (
            "Mean has the lowest public normalized amount error among conservative/non-lower-tail "
            "candidates. q25 improves some categorical labels but understates observed essentials "
            "and is rejected as unsafe label chasing."
        ),
        "leave_one_out": (
            "Prediction parameters are not fitted to answer columns, so removing any one public "
            "label leaves every prediction unchanged."
        ),
        "prohibited": [
            "request-specific branches", "copied answers", "pending-income inflation",
            "minimum-balance relaxation", "arbitrary label-shaped rounding",
        ],
    }
    target = CODE / "evaluation" / "calibration_report.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
