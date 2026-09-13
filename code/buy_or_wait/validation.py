from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .data import Dataset
from .forecast import Forecaster
from .ledger import IndependentLedgerVerifier, LedgerSnapshot
from .models import Decision, Request, SpendingChange, ZERO, floor_money


OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]
STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


def parse_plan(text: str) -> list[tuple[date, Decimal]]:
    if text == "none":
        return []
    result = []
    for item in text.split("|"):
        day, amount = item.split(":", 1)
        result.append((date.fromisoformat(day), Decimal(amount)))
    return result


def parse_changes(text: str) -> list[SpendingChange]:
    if text == "none":
        return []
    result = []
    for item in text.split("|"):
        if re.fullmatch(r"stop:[^:|]+", item):
            _, event_id = item.split(":")
            result.append(SpendingChange("stop", event_id))
            continue
        match = re.fullmatch(r"reduce_to:([^:|]+):([0-9]+(?:\.[0-9]{1,2})?)", item)
        if not match:
            raise ValueError(f"Malformed spending change: {item}")
        amount = Decimal(match.group(2))
        result.append(SpendingChange("reduce_to", match.group(1), amount))
    return result


def validate_decisions(dataset: Dataset, requests: list[Request], decisions: list[Decision]) -> None:
    if len(decisions) != len(requests):
        raise ValueError(f"Expected {len(requests)} decisions, got {len(decisions)}")
    if [d.request_id for d in decisions] != [r.request_id for r in requests]:
        raise ValueError("Decision request IDs/order do not match requests.csv")
    request_by_id = {r.request_id: r for r in requests}
    forecaster = Forecaster(dataset)
    for decision in decisions:
        request = request_by_id[decision.request_id]
        profile = dataset.profiles[request.user_id]
        if not ZERO <= decision.amount_safe_to_pay <= request.requested_amount:
            raise ValueError(f"Invalid safe amount for {decision.request_id}")
        if decision.amount_safe_to_pay != floor_money(decision.amount_safe_to_pay):
            raise ValueError(f"Safe amount has invalid precision for {decision.request_id}")
        if decision.affordability_status not in STATUSES:
            raise ValueError(f"Invalid status for {decision.request_id}")
        if decision.recommended_payment_method not in METHODS:
            raise ValueError(f"Invalid method for {decision.request_id}")
        try:
            payments = parse_plan(decision.payment_plan)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Malformed payment plan for {decision.request_id}") from error
        if payments != sorted(payments):
            raise ValueError(f"Non-chronological plan for {decision.request_id}")
        if any(amount <= ZERO for _, amount in payments):
            raise ValueError(f"Non-positive payment for {decision.request_id}")
        if any(day > request.desired_completion_date for day, _ in payments):
            raise ValueError(f"Plan misses completion deadline for {decision.request_id}")
        safe_today, earliest = forecaster.baseline_capacity(request, profile)
        baseline_snapshot = LedgerSnapshot.build(
            request, profile, forecaster.daily_cashflows(request, profile)
        )
        independent_today, independent_earliest = IndependentLedgerVerifier.baseline_capacity(
            baseline_snapshot, request.requested_amount
        )
        if (safe_today, earliest) != (floor_money(independent_today), independent_earliest):
            raise ValueError(f"Independent baseline replay mismatch for {decision.request_id}")
        if decision.amount_safe_to_pay != safe_today:
            raise ValueError(f"Safe amount is not the baseline capacity for {decision.request_id}")
        if decision.earliest_date_for_full_payment != earliest:
            raise ValueError(f"Earliest full-payment date mismatch for {decision.request_id}")
        if decision.affordability_status == "affordable_now" and decision.earliest_date_for_full_payment != request.request_date:
            raise ValueError(f"affordable_now date mismatch for {decision.request_id}")
        method = decision.recommended_payment_method
        if method in {"full_payment", "partial_payment", "installments"} and method not in profile.methods:
            raise ValueError(f"Method violates user preference for {decision.request_id}")
        if method == "wait" and "full_payment" not in profile.methods:
            raise ValueError(f"Wait requires full-payment preference for {decision.request_id}")
        if method == "full_payment":
            if payments != [(request.request_date, request.requested_amount)]:
                raise ValueError(f"Invalid full-payment plan for {decision.request_id}")
        if method == "wait":
            if not earliest or payments != [(earliest, request.requested_amount)]:
                raise ValueError(f"Invalid wait plan for {decision.request_id}")
        if decision.recommended_payment_method == "partial_payment":
            if (
                not request.allows_partial_payment
                or len(payments) != 2
                or payments[0] != (request.request_date, decision.amount_safe_to_pay)
                or not earliest
                or payments[1] != (earliest, request.requested_amount - decision.amount_safe_to_pay)
                or sum((x[1] for x in payments), ZERO) != request.requested_amount
            ):
                raise ValueError(f"Invalid partial plan for {decision.request_id}")
        if decision.recommended_payment_method == "installments":
            supplied = [
                option for option in dataset.options.get(decision.request_id, [])
                if option.method == "installments" and option.schedule() == payments
            ]
            if not supplied:
                raise ValueError(f"Installment plan is not a supplied option: {decision.request_id}")
            if profile.max_installment_months is None or all(
                option.payment_count > profile.max_installment_months for option in supplied
            ):
                raise ValueError(f"Installment term violates preference: {decision.request_id}")
        changes = parse_changes(decision.spending_changes_needed)
        if len(changes) > 3:
            raise ValueError(f"Too many spending changes for {decision.request_id}")
        changed_ids = [change.event_id for change in changes]
        if len(changed_ids) != len(set(changed_ids)):
            raise ValueError(f"Duplicate spending change target for {decision.request_id}")
        flexible = {
            stream["representative"].event_id: (stream, can_stop, can_reduce)
            for stream, can_stop, can_reduce in forecaster.flexible_streams(request, profile)
        }
        for change in changes:
            if change.event_id not in flexible:
                raise ValueError(f"Unauthorized spending change for {decision.request_id}: {change.event_id}")
            stream, can_stop, can_reduce = flexible[change.event_id]
            event = stream["representative"]
            if change.kind == "stop" and not can_stop:
                raise ValueError(f"Unauthorized stop for {decision.request_id}: {change.event_id}")
            if change.kind == "reduce_to":
                minimum = dataset.convert(
                    event.minimum_allowed_amount or ZERO,
                    event.currency,
                    profile.home_currency,
                    event.settlement_date,
                )
                if not can_reduce or change.new_amount is None or not minimum <= change.new_amount < stream["amount"]:
                    raise ValueError(f"Unauthorized reduction for {decision.request_id}: {change.event_id}")
        expected_status = {
            "wait": "affordable_later",
            "partial_payment": "affordable_with_plan",
            "installments": "affordable_with_plan",
        }.get(method)
        if method == "full_payment":
            expected_status = "affordable_with_plan" if changes else "affordable_now"
        if method == "not_recommended":
            expected_status = "not_affordable"
            if payments or changes:
                raise ValueError(f"Fallback decision contains a plan for {decision.request_id}")
        if decision.affordability_status != expected_status:
            raise ValueError(f"Status/method mismatch for {decision.request_id}")
        if payments:
            safe, _minimum = forecaster.is_safe(request, profile, payments, changes)
            if not safe:
                raise ValueError(f"Recommended plan fails safety replay: {decision.request_id}")
            changed_snapshot = LedgerSnapshot.build(
                request, profile, forecaster.daily_cashflows(request, profile, changes)
            )
            if not IndependentLedgerVerifier.replay(changed_snapshot, payments).safe:
                raise ValueError(
                    f"Recommended plan fails independent ledger replay: {decision.request_id}"
                )
        if not decision.decision_explanation.strip() or len(decision.decision_explanation) > 1000:
            raise ValueError(f"Invalid explanation for {decision.request_id}")
