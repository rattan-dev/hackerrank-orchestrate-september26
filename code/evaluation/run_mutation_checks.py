#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path


CODE = Path(__file__).resolve().parents[1]
REPO = CODE.parent
sys.path.insert(0, str(CODE))

from buy_or_wait.data import Dataset
from buy_or_wait.decision import FinancialAgent
from buy_or_wait.validation import validate_decisions


def rejected(dataset, decisions, index, **changes) -> bool:
    mutated = deepcopy(decisions)
    mutated[index] = replace(mutated[index], **changes)
    try:
        validate_decisions(dataset, dataset.requests, mutated)
    except ValueError:
        return True
    return False


def main() -> int:
    dataset = Dataset(REPO / "dataset")
    decisions = FinancialAgent(dataset).decide_all()
    target = decisions[0]
    request = dataset.requests[0]
    mutations = {
        "overstated_safe_amount": rejected(
            dataset, decisions, 0,
            amount_safe_to_pay=target.amount_safe_to_pay + Decimal("0.01"),
        ),
        "contradictory_status": rejected(
            dataset, decisions, 0, affordability_status="not_affordable",
        ),
        "late_payment": rejected(
            dataset, decisions, 0,
            payment_plan=f"{request.desired_completion_date + timedelta(days=1)}:1",
        ),
        "unauthorized_change": rejected(
            dataset, decisions, 0, spending_changes_needed="stop:not_an_event",
        ),
        "unsupported_installment": rejected(
            dataset, decisions, 0,
            recommended_payment_method="installments",
            affordability_status="affordable_with_plan",
            payment_plan=f"{request.request_date}:1",
        ),
        "empty_explanation": rejected(
            dataset, decisions, 0, decision_explanation="",
        ),
    }
    print(json.dumps(mutations, indent=2, sort_keys=True))
    return 0 if all(mutations.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
