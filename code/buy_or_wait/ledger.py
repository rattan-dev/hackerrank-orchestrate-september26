from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from .models import Profile, Request, ZERO


@dataclass(frozen=True)
class LedgerSnapshot:
    """Immutable normalized forecast input for an independent arithmetic replay."""

    start: date
    end: date
    opening_balance: Decimal
    minimum_balance: Decimal
    flows: Mapping[date, Decimal]

    @classmethod
    def build(
        cls, request: Request, profile: Profile, flows: Mapping[date, Decimal]
    ) -> "LedgerSnapshot":
        copied = {
            day: Decimal(amount)
            for day, amount in flows.items()
            if request.request_date <= day <= request.request_date + timedelta(days=90)
        }
        return cls(
            start=request.request_date,
            end=request.request_date + timedelta(days=90),
            opening_balance=profile.available_balance,
            minimum_balance=profile.minimum_balance,
            flows=MappingProxyType(copied),
        )


@dataclass(frozen=True)
class ReplayResult:
    safe: bool
    minimum_projected_balance: Decimal
    minimum_day: date
    closing_balance: Decimal


class IndependentLedgerVerifier:
    """Replays normalized cash flows without using Forecaster.trajectory/is_safe."""

    @staticmethod
    def balances(
        snapshot: LedgerSnapshot,
        payments: list[tuple[date, Decimal]],
    ) -> dict[date, Decimal] | None:
        payment_map: dict[date, Decimal] = {}
        for day, amount in payments:
            if day < snapshot.start or day > snapshot.end or amount <= ZERO:
                return None
            payment_map[day] = payment_map.get(day, ZERO) + amount
        balance = snapshot.opening_balance
        result = {}
        day = snapshot.start
        while day <= snapshot.end:
            balance += snapshot.flows.get(day, ZERO) - payment_map.get(day, ZERO)
            result[day] = balance
            day += timedelta(days=1)
        return result

    @classmethod
    def replay(
        cls, snapshot: LedgerSnapshot, payments: list[tuple[date, Decimal]],
    ) -> ReplayResult:
        balances = cls.balances(snapshot, payments)
        if balances is None:
            invalid_day = payments[0][0] if payments else snapshot.start
            return ReplayResult(
                False, Decimal("-Infinity"), invalid_day, Decimal("-Infinity")
            )
        minimum_day, minimum = min(balances.items(), key=lambda item: (item[1], item[0]))
        return ReplayResult(
            safe=minimum >= snapshot.minimum_balance,
            minimum_projected_balance=minimum,
            minimum_day=minimum_day,
            closing_balance=balances[snapshot.end],
        )

    @classmethod
    def baseline_capacity(
        cls, snapshot: LedgerSnapshot, requested_amount: Decimal
    ) -> tuple[Decimal, date | None]:
        balances = cls.balances(snapshot, [])
        if balances is None:  # pragma: no cover - empty payments are always valid
            raise AssertionError("empty replay unexpectedly failed")
        minimum_from: dict[date, Decimal] = {}
        running = Decimal("Infinity")
        for day in sorted(balances, reverse=True):
            running = min(running, balances[day])
            minimum_from[day] = running
        capacity = max(ZERO, minimum_from[snapshot.start] - snapshot.minimum_balance)
        safe_today = min(requested_amount, capacity)
        earliest = next((
            day for day in sorted(minimum_from)
            if minimum_from[day] - snapshot.minimum_balance >= requested_amount
        ), None)
        return safe_today, earliest
