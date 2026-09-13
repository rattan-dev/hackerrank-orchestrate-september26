from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Iterable


ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass
class Profile:
    user_id: str
    home_currency: str
    available_balance: Decimal
    minimum_balance: Decimal
    methods: set[str]
    priorities: str = ""
    protected_categories: set[str] = field(default_factory=set)
    reducible_categories: set[str] = field(default_factory=set)
    stoppable_categories: set[str] = field(default_factory=set)
    max_installment_months: int | None = None


@dataclass
class CashEvent:
    event_id: str
    user_id: str
    event_date: date
    settlement_date: date
    amount: Decimal | None
    currency: str
    direction: str
    status: str
    event_type: str
    category: str = ""
    description: str = ""
    flexibility: str = "fixed"
    minimum_allowed_amount: Decimal | None = None
    linked_event_id: str = ""
    source_timestamp: str = ""

    @property
    def signed_amount(self) -> Decimal:
        if self.amount is None:
            return ZERO
        return self.amount if self.direction == "credit" else -self.amount

    @property
    def flexible(self) -> bool:
        return self.flexibility in {"reducible", "stoppable", "reducible_or_stoppable"}


@dataclass(frozen=True)
class ImageFact:
    image_id: str
    amount: Decimal
    currency: str
    selected_label: str
    image_sha256: str
    extraction_method: str
    review_status: str
    confidence: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    method: str
    first_payment_date: date
    payment_count: int
    interval_days: int
    total_payable: Decimal
    payments: tuple[Decimal, ...] = ()

    def schedule(self) -> list[tuple[date, Decimal]]:
        from datetime import timedelta

        if self.payments:
            amounts = list(self.payments)
        else:
            quantum = Decimal("0.01")
            regular = (self.total_payable / self.payment_count).quantize(quantum)
            amounts = [regular] * self.payment_count
            amounts[-1] += self.total_payable - sum(amounts, ZERO)
        return [
            (self.first_payment_date + timedelta(days=i * self.interval_days), amount)
            for i, amount in enumerate(amounts)
        ]


@dataclass(frozen=True)
class SpendingChange:
    kind: str
    event_id: str
    new_amount: Decimal | None = None

    def serialize(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{money(self.new_amount or ZERO)}"


@dataclass
class CandidatePlan:
    method: str
    payments: list[tuple[date, Decimal]]
    total_payable: Decimal
    changes: list[SpendingChange] = field(default_factory=list)
    option_id: str = ""
    safe: bool = False
    minimum_projected_balance: Decimal = ZERO


@dataclass
class Decision:
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str
    decision_explanation: str

    def row(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": money(self.amount_safe_to_pay),
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment
                else ""
            ),
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


def money(value: Decimal) -> str:
    value = value.quantize(MONEY_QUANTUM)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def floor_money(value: Decimal) -> Decimal:
    """Round toward zero so reported capacity is never overstated by a cent."""
    return max(ZERO, value).quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


def payment_plan_text(payments: Iterable[tuple[date, Decimal]]) -> str:
    items = list(payments)
    if not items:
        return "none"
    def plan_amount(value: Decimal) -> str:
        if value == value.to_integral_value():
            return str(value.quantize(Decimal("1")))
        return format(value.quantize(Decimal("0.01")), "f")

    return "|".join(f"{day.isoformat()}:{plan_amount(amount)}" for day, amount in items)
