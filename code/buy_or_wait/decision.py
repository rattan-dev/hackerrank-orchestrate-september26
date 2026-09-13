from __future__ import annotations

import itertools
from copy import deepcopy
from datetime import date
from decimal import Decimal

from .data import Dataset
from .forecast import Forecaster
from .models import (
    CandidatePlan,
    Decision,
    Profile,
    Request,
    SpendingChange,
    ZERO,
    money,
    payment_plan_text,
)
from .utils import numeric_id_key


class FinancialAgent:
    def __init__(self, dataset: Dataset) -> None:
        dataset.validate()
        self.dataset = dataset
        self.forecaster = Forecaster(dataset)

    def decide_all(self) -> list[Decision]:
        return [self.decide(request) for request in self.dataset.requests]

    def decide(self, request: Request) -> Decision:
        profile = self.dataset.profiles[request.user_id]
        safe_today, earliest = self.forecaster.baseline_capacity(request, profile)
        candidates = self._candidate_plans(request, profile, safe_today, earliest)

        safe_plans = [self.forecaster.evaluate(request, profile, p) for p in candidates]
        safe_plans = [p for p in safe_plans if p.safe]

        if not safe_plans:
            safe_plans = self._plans_with_changes(request, profile, candidates)

        if safe_plans:
            chosen = min(safe_plans, key=self._rank)
            chosen = self._remove_redundant_changes(request, profile, chosen)
            if chosen.method == "full_payment" and not chosen.changes:
                status = "affordable_now"
            elif chosen.method == "wait":
                status = "affordable_later"
            else:
                status = "affordable_with_plan"
            changes = "|".join(change.serialize() for change in chosen.changes) or "none"
            explanation = self._explain(
                request, profile, safe_today, earliest, chosen, status
            )
            return Decision(
                request_id=request.request_id,
                amount_safe_to_pay=safe_today,
                affordability_status=status,
                recommended_payment_method=chosen.method,
                payment_plan=payment_plan_text(chosen.payments),
                earliest_date_for_full_payment=earliest,
                spending_changes_needed=changes,
                decision_explanation=explanation,
            )

        baseline = self.forecaster.trajectory(request, profile)
        low_day, low = min(
            baseline.items(), key=lambda item: (item[1], item[0]),
            default=(request.request_date, profile.available_balance),
        )
        material_obligation = self._material_obligation(request, profile)
        reason = (
            f"Only {profile.home_currency} {money(safe_today)} is safe today; no eligible plan "
            f"can finish {profile.home_currency} {money(request.requested_amount)} by "
            f"{request.desired_completion_date.isoformat()} while preserving the minimum balance "
            f"of {profile.home_currency} {money(profile.minimum_balance)}. "
            f"Baseline 90-day low: {profile.home_currency} {money(low)} on "
            f"{low_day.isoformat()}."
        )
        if material_obligation:
            description, day, amount = material_obligation
            reason += (
                f" A material obligation is {description}: {profile.home_currency} "
                f"{money(amount)} on {day.isoformat()}."
            )
        reason += " This is a forecast, not a guarantee of future cash flow."
        return Decision(
            request_id=request.request_id,
            amount_safe_to_pay=safe_today,
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            payment_plan="none",
            earliest_date_for_full_payment=earliest,
            spending_changes_needed="none",
            decision_explanation=reason,
        )

    def _candidate_plans(
        self,
        request: Request,
        profile: Profile,
        safe_today: Decimal,
        earliest,
    ) -> list[CandidatePlan]:
        plans: list[CandidatePlan] = []
        if "full_payment" in profile.methods:
            plans.append(
                CandidatePlan(
                    method="full_payment",
                    payments=[(request.request_date, request.requested_amount)],
                    total_payable=request.requested_amount,
                )
            )
            if earliest and request.request_date < earliest <= request.desired_completion_date:
                plans.append(
                    CandidatePlan(
                        method="wait",
                        payments=[(earliest, request.requested_amount)],
                        total_payable=request.requested_amount,
                    )
                )
        if (
            request.allows_partial_payment
            and "partial_payment" in profile.methods
            and ZERO < safe_today < request.requested_amount
            and earliest
            and earliest <= request.desired_completion_date
        ):
            plans.append(
                CandidatePlan(
                    method="partial_payment",
                    payments=[
                        (request.request_date, safe_today),
                        (earliest, request.requested_amount - safe_today),
                    ],
                    total_payable=request.requested_amount,
                )
            )
        if "installments" in profile.methods:
            for option in self.dataset.options.get(request.request_id, []):
                if option.method != "installments":
                    continue
                if profile.max_installment_months is None or option.payment_count > profile.max_installment_months:
                    continue
                schedule = option.schedule()
                if not schedule or schedule[0][0] < request.request_date:
                    continue
                if schedule[-1][0] > request.desired_completion_date:
                    continue
                plans.append(
                    CandidatePlan(
                        method="installments",
                        payments=schedule,
                        total_payable=option.total_payable,
                        option_id=option.payment_option_id,
                    )
                )
        return plans

    def _plans_with_changes(
        self,
        request: Request,
        profile: Profile,
        base_plans: list[CandidatePlan],
    ) -> list[CandidatePlan]:
        streams = self.forecaster.flexible_streams(request, profile)
        actions = []
        for stream, can_stop, can_reduce in streams:
            event = stream["representative"]
            choices = []
            if can_stop:
                choices.append(SpendingChange("stop", event.event_id))
            if can_reduce and event.minimum_allowed_amount is not None:
                minimum_home = self.dataset.convert(
                    event.minimum_allowed_amount,
                    event.currency,
                    profile.home_currency,
                    event.settlement_date,
                )
                choices.append(SpendingChange("reduce_to", event.event_id, minimum_home))
            actions.append(choices)
        found: list[CandidatePlan] = []
        # Search every legal set of at most three category-level adjustments.
        for plan in base_plans:
            indexed = [(i, action) for i, choices in enumerate(actions) for action in choices]
            for count in range(1, min(3, len(actions)) + 1):
                for selected in itertools.combinations(indexed, count):
                    if len({index for index, _ in selected}) != count:
                        continue
                    candidate = deepcopy(plan)
                    candidate.changes = [action for _, action in selected]
                    self.forecaster.evaluate(request, profile, candidate)
                    if candidate.safe:
                        found.append(candidate)
        return found

    def _remove_redundant_changes(
        self, request: Request, profile: Profile, plan: CandidatePlan
    ) -> CandidatePlan:
        candidate = deepcopy(plan)
        changed = True
        while changed:
            changed = False
            for action in list(candidate.changes):
                trial = deepcopy(candidate)
                trial.changes.remove(action)
                self.forecaster.evaluate(request, profile, trial)
                if trial.safe:
                    candidate = trial
                    changed = True
                    break
        return self.forecaster.evaluate(request, profile, candidate)

    def _rank(self, plan: CandidatePlan) -> tuple:
        return (
            1 if plan.changes else 0,
            plan.total_payable,
            plan.payments[0][0] if plan.payments else date.max,
            len(plan.payments),
            len(plan.changes),
            numeric_id_key(plan.option_id),
        )

    def _material_obligation(
        self, request: Request, profile: Profile
    ) -> tuple[str, date, Decimal] | None:
        """Return the largest individually supported debit in the forecast."""
        candidates: list[tuple[str, date, Decimal]] = []
        end = self.forecaster.horizon_end(request)
        for stream in self.forecaster.recurring_streams(request, profile):
            if stream["direction"] != "debit":
                continue
            dates = self.forecaster._stream_dates(stream, request.request_date, end)
            if dates:
                candidates.append((
                    stream["representative"].description or stream["category"],
                    dates[0], stream["amount"],
                ))
        for record in self.forecaster._resolved_future_debits(request, profile):
            event = record["event"]
            candidates.append((event.description or event.category, record["day"], record["amount"]))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[2], -item[1].toordinal(), item[0]))

    def _explain(
        self,
        request: Request,
        profile: Profile,
        safe_today: Decimal,
        earliest,
        plan: CandidatePlan,
        status: str,
    ) -> str:
        currency = profile.home_currency
        parts = [
            f"{currency} {money(safe_today)} is safe to pay today before optional cuts.",
            f"The recommended {plan.method.replace('_', ' ')} keeps the 90-day balance at or above "
            f"{currency} {money(profile.minimum_balance)} (projected low {currency} "
            f"{money(plan.minimum_projected_balance)}).",
        ]
        flows = self.forecaster.daily_cashflows(request, profile)
        credits = sorted(
            ((day, amount) for day, amount in flows.items() if amount > ZERO),
            key=lambda item: (item[0], -item[1]),
        )
        material_obligation = self._material_obligation(request, profile)
        if material_obligation:
            description, day, amount = material_obligation
            parts.append(
                f"A material obligation is {description}: {currency} {money(amount)} "
                f"on {day.isoformat()}."
            )
        if credits:
            day, amount = credits[0]
            parts.append(
                f"Confirmed forecast income includes {currency} {money(amount)} on "
                f"{day.isoformat()}; pending credits are excluded."
            )
        if plan.method == "installments":
            fee = plan.total_payable - request.requested_amount
            parts.append(
                f"This exact provider offer has {len(plan.payments)} payments, total cost "
                f"{currency} {money(plan.total_payable)}, and fee {currency} {money(fee)}; "
                "it is the highest-ranked safe eligible offer."
            )
        elif plan.method == "wait" and credits:
            preceding = [item for item in credits if item[0] <= plan.payments[0][0]]
            if preceding:
                day, amount = preceding[-1]
                parts.append(
                    f"Waiting uses the confirmed {currency} {money(amount)} inflow on "
                    f"{day.isoformat()} before the full payment."
                )
        if plan.changes:
            stream_by_id = {
                stream["representative"].event_id: stream
                for stream, _can_stop, _can_reduce in self.forecaster.flexible_streams(request, profile)
            }
            savings = ZERO
            change_labels = []
            for change in plan.changes:
                stream = stream_by_id[change.event_id]
                current = stream["amount"]
                savings += current if change.kind == "stop" else current - (change.new_amount or ZERO)
                action = "stop" if change.kind == "stop" else f"reduce to {currency} {money(change.new_amount or ZERO)}"
                change_labels.append(
                    f"{action} {stream['representative'].description or stream['category']}"
                )
            parts.append(
                f"The {len(plan.changes)} authorized flexible-spending adjustment(s) save "
                f"about {currency} {money(savings)} per recurrence ({'; '.join(change_labels)}) "
                "and are minimal for this plan."
            )
        if earliest and earliest != request.request_date:
            parts.append(f"A single full payment first becomes safe on {earliest.isoformat()}.")
        if profile.priorities:
            priorities = profile.priorities.replace("|", ", ").replace("_", " ")
            parts.append(f"This preserves the user's stated priorities: {priorities}.")
        parts.append("The recommendation is safe under the stated 90-day forecast, not guaranteed.")
        return " ".join(parts)
