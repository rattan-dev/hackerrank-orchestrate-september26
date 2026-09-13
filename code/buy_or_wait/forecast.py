from __future__ import annotations

import calendar
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .data import Dataset
from .models import CashEvent, CandidatePlan, Profile, Request, SpendingChange, ZERO, floor_money


ONE_TIME_INCOME = (
    "bonus", "commission", "arrears", "refund", "reversal", "prize", "windfall",
    "lottery", "investment", "sale proceeds", "one-time", "one time",
)
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
ENDED_INCOME = ("final employer", "final payroll", "employment ended", "last salary")
VALID_INTERVALS = (5, 7, 10, 14, 15, 21)
NON_RECURRING_EVENT_TYPES = {
    "refund", "reversal", "reimbursement", "investment_purchase", "investment_sale",
    "investment_valuation", "internal_transfer", "transfer", "prize", "windfall",
}
NON_RECURRING_TEXT = (
    "one-time", "one time", "internal transfer", "between your two accounts",
    "reimbursement", "refund", "reversal", "investment", "prize", "lottery",
)
AGGREGATE_VARIABLE_CATEGORIES = {"groceries", "transport", "dining"}


def normalized_description(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\b\d+\b", "#", value.lower())).strip()


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def amount_stat(events: list[CashEvent]) -> Decimal:
    values = [event.amount or ZERO for event in events]
    if not values:
        return ZERO
    mean = sum(values, ZERO) / len(values)
    if max(values) - min(values) <= max(Decimal("0.01"), mean * Decimal("0.01")):
        return values[-1]
    # Repeated variable spending is forecast at its observed long-run mean.
    return mean


class Forecaster:
    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset

    def horizon_end(self, request: Request) -> date:
        return request.request_date + timedelta(days=90)

    def _home_amount_stat(self, events: list[CashEvent], profile: Profile) -> Decimal:
        converted = []
        for event in events:
            value = self.dataset.convert(
                event.amount or ZERO, event.currency, profile.home_currency, event.settlement_date
            )
            converted.append(value)
        if not converted:
            return ZERO
        if events[0].category == "salary" and events[0].direction == "credit":
            # A stable historical salary is safer than averaging a one-cycle
            # reduction into every future month. Explicit messages still override it.
            counts = Counter(converted)
            highest = max(counts.values())
            if highest >= 2:
                modes = {value for value, count in counts.items() if count == highest}
                return next(value for value in reversed(converted) if value in modes)
        mean = sum(converted, ZERO) / len(converted)
        if max(converted) - min(converted) <= max(Decimal("0.01"), mean * Decimal("0.01")):
            return converted[-1]
        return mean

    def _regular_income_events(self, events: list[CashEvent]) -> list[CashEvent]:
        return [
            event for event in events
            if event.category == "salary"
            and event.direction == "credit"
            and event.status == "settled"
            and event.amount is not None
            and not event.linked_event_id
            and not any(term in event.description.lower() for term in ONE_TIME_INCOME)
        ]

    def _message_salary_override(self, request: Request, profile: Profile) -> dict:
        fact = {
            "amount": None, "currency": profile.home_currency, "date": None,
            "confirmed": False, "extra": ZERO, "first_only": False,
            "replace_all": False, "ended": False,
        }
        money_pattern = re.compile(
            r"\b(INR|IDR|USD|EUR|ZAR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
            re.IGNORECASE,
        )
        for row in self.dataset.messages_by_user.get(request.user_id, []):
            if row.get("source_type", "").lower() != "employer":
                continue
            sent = row.get("sent_at", "")[:10]
            if sent and date.fromisoformat(sent) > request.request_date:
                continue
            text = row.get("message_text", "")
            lower = text.lower()
            # Embedded directives are ignored; only employer/service factual language is parsed.
            if any(term in lower for term in (
                "confirmed salary", "confirmed base salary", "gaji bulanan", "gaji pokok",
                "monthly pay", "monthly salary", "next payroll", "expected on",
                "first salary", "regular salary", "salary of", "salary credit",
                "gaji pertama", "gaji rutin", "gaji sebesar", "penggajian berikutnya",
                "next salary is reduced", "temporary monthly pay", "gaji bulanan sementara",
                "confirmed credit date", "tanggal kredit yang dikonfirmasi",
                "salary resumes", "gaji kembali",
            )):
                fact["confirmed"] = True
            matches = money_pattern.findall(text)
            if matches and fact["confirmed"]:
                fact["currency"] = matches[0][0].upper()
                fact["amount"] = Decimal(matches[0][1].replace(",", ""))
                if len(matches) > 1 and any(term in lower for term in ("arrears", "tunggakan", "one-time")):
                    fact["extra"] = Decimal(matches[1][1].replace(",", ""))
            dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)
            if dates and any(term in lower for term in (
                "expected on", "berlaku mulai", "effective", "applies from", "credit date",
                "confirmed for", "scheduled for", "dijadwalkan", "dikonfirmasi untuk",
                "resumes on", "kembali pada", "tanggal kredit yang dikonfirmasi",
            )):
                fact["date"] = date.fromisoformat(dates[-1])
            natural = re.findall(
                r"\b([0-3]?\d)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
                text, re.IGNORECASE,
            )
            if natural and fact["confirmed"]:
                day_text, month_text, year_text = natural[-1]
                fact["date"] = date(int(year_text), MONTHS[month_text.lower()], int(day_text))
            if any(term in lower for term in (
                "one household employment record has ended", "salah satu sumber pendapatan",
            )):
                fact["replace_all"] = True
            if any(term in lower for term in (
                "next salary is reduced", "temporary monthly pay", "gaji bulanan sementara",
                "gaji berikutnya dikurangi",
            )):
                fact["first_only"] = True
            if any(term in lower for term in (
                "contract has ended", "no off-season income", "no renewal has been confirmed",
                "employment has ended", "kontrak musiman saat ini telah berakhir",
                "belum ada pendapatan di luar musim", "pekerjaan anda telah berakhir",
            )):
                fact["ended"] = True
            if any(term in lower for term in ("not withdrawable", "is still pending", "masih menunggu")):
                # This invalidates gig/bonus projections but does not erase a regular base salary.
                if any(term in lower for term in ("payout", "bonus", "commission", "komisi")):
                    fact["confirmed"] = False
        return fact

    def _recurrence(self, events: list[CashEvent]) -> tuple[str, int] | None:
        dates = sorted({event.event_date for event in events})
        if len(dates) < 4:
            return None
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        recent = gaps[-6:]
        monthly_votes = sum(28 <= gap <= 31 for gap in recent)
        if monthly_votes >= max(3, len(recent) - 1):
            return "monthly", 1
        median = int(round(statistics.median(recent)))
        interval = min(VALID_INTERVALS, key=lambda value: abs(value - median))
        if sum(abs(gap - interval) <= 1 for gap in recent) >= max(3, len(recent) - 1):
            return "days", interval
        return None

    def _recurrence_confidence(
        self, events: list[CashEvent], recurrence: tuple[str, int]
    ) -> dict[str, str | int]:
        dates = sorted({event.event_date for event in events})
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])][-6:]
        mode, step = recurrence
        matches = sum(
            28 <= gap <= 31 if mode == "monthly" else abs(gap - step) <= 1
            for gap in gaps
        )
        values = [event.amount or ZERO for event in events]
        mean = sum(values, ZERO) / len(values) if values else ZERO
        spread = (max(values) - min(values)) / mean if mean else ZERO
        ratio = Decimal(matches) / Decimal(len(gaps)) if gaps else ZERO
        return {
            "level": "high" if len(events) >= 5 and ratio >= Decimal("0.8") else "medium",
            "evidence_count": len(events),
            "interval_match_ratio": str(ratio.quantize(Decimal("0.001"))),
            "relative_amount_spread": str(spread.quantize(Decimal("0.001"))),
        }

    def recurring_streams(self, request: Request, profile: Profile):
        history = [
            event for event in self.dataset.events.get(request.user_id, [])
            if event.status == "settled" and event.event_date <= request.request_date
            and event.amount is not None
            and event.direction in {"debit", "credit"}
            and event.event_type not in NON_RECURRING_EVENT_TYPES
            and event.category not in {"windfall", "investment"}
            and not any(term in event.description.lower() for term in NON_RECURRING_TEXT)
        ]
        grouped: dict[tuple[str, str, str], list[CashEvent]] = defaultdict(list)
        for event in history:
            if event.category == "salary":
                continue
            description_key = "*" if event.category in AGGREGATE_VARIABLE_CATEGORIES else (
                normalized_description(event.description)
            )
            grouped[(event.category, event.direction, description_key)].append(event)

        streams = []
        for (category, direction, _description_key), events in grouped.items():
            events.sort(key=lambda event: (event.event_date, event.event_id))
            recurrence = self._recurrence(events)
            if recurrence is None:
                continue
            streams.append({
                "category": category,
                "direction": direction,
                "events": events,
                "representative": events[-1],
                "recurrence": recurrence,
                "amount": self._home_amount_stat(events, profile),
                "currency": profile.home_currency,
                "anchor": events[-1].event_date,
                "confidence": self._recurrence_confidence(events, recurrence),
            })

        # Salary can contain several monthly streams (e.g. two household earners).
        salary_events = self._regular_income_events(history)
        salary_groups: dict[int, list[CashEvent]] = defaultdict(list)
        for event in salary_events:
            salary_groups[event.event_date.day].append(event)
        salary_streams = []
        for day_of_month, events in sorted(salary_groups.items()):
            events.sort(key=lambda event: event.event_date)
            distinct_months = {(e.event_date.year, e.event_date.month) for e in events}
            if len(distinct_months) < 3:
                continue
            expected_next = add_months(events[-1].event_date, 1)
            if expected_next + timedelta(days=7) < request.request_date:
                # A missing expected payroll cycle is safer evidence that this
                # particular stream ended than silently projecting stale income.
                continue
            if any(term in events[-1].description.lower() for term in ENDED_INCOME):
                continue
            salary_streams.append({
                "category": "salary", "direction": "credit", "events": events,
                "representative": events[-1], "recurrence": ("monthly", 1),
                "amount": self._home_amount_stat(events, profile), "currency": profile.home_currency,
                "anchor": events[-1].event_date,
                "confidence": self._recurrence_confidence(events, ("monthly", 1)),
            })
        streams.extend(salary_streams)

        # Scheduled salary and trusted payroll messages override the matching stream.
        scheduled = [
            event for event in self.dataset.events.get(request.user_id, [])
            if event.category == "salary" and event.direction == "credit"
            and event.status == "scheduled" and event.settlement_date > request.request_date
        ]
        salary_fact = self._message_salary_override(request, profile)
        msg_amount = salary_fact["amount"]
        msg_date = salary_fact["date"]
        msg_confirmed = salary_fact["confirmed"]
        message_text = " ".join(
            row.get("message_text", "").lower()
            for row in self.dataset.messages_by_user.get(request.user_id, [])
            if not row.get("sent_at") or date.fromisoformat(row["sent_at"][:10]) <= request.request_date
        )
        if salary_fact["ended"] or any(term in message_text for term in (
            "contract has ended", "no off-season income", "employment has ended",
            "no renewal has been confirmed", "kontrak musiman saat ini telah berakhir",
            "belum ada pendapatan di luar musim", "pekerjaan anda telah berakhir",
        )):
            for stream in list(streams):
                if stream["category"] == "salary": streams.remove(stream)
            salary_streams = []
        if any(term in message_text for term in (
            "payout is still pending", "payout masih tertunda", "isn’t withdrawable",
            "isn't withdrawable", "belum dapat ditarik",
        )):
            # A variable platform balance does not invalidate unrelated payroll.
            # Remove only gig/payout streams implicated by the message.
            for stream in list(streams):
                description = stream["representative"].description.lower()
                if stream["category"] == "salary" and any(term in description for term in (
                    "payout", "platform", "marketplace", "gig", "driver", "delivery",
                )):
                    streams.remove(stream)
            salary_streams = [stream for stream in salary_streams if stream in streams]
        salary = None
        if salary_streams:
            target_day = (scheduled[0].settlement_date.day if scheduled else
                          msg_date.day if msg_date else salary_streams[0]["anchor"].day)
            salary = min(salary_streams, key=lambda stream: abs(stream["anchor"].day - target_day))
        if salary:
            # A scheduled/confirmed row updates the matching payroll stream. Other
            # current household streams remain unless explicit evidence replaces all;
            # stale streams were already excluded above.
            if salary_fact["replace_all"]:
                for extra in list(streams):
                    if extra["category"] == "salary" and extra is not salary:
                        streams.remove(extra)
            if scheduled:
                next_salary = scheduled[0]
                salary["anchor"] = next_salary.settlement_date
                salary["amount"] = self.dataset.convert(
                    next_salary.amount or ZERO, next_salary.currency, profile.home_currency,
                    next_salary.settlement_date,
                )
                salary["currency"] = profile.home_currency
                salary["first_is_anchor"] = True
            if msg_amount is not None:
                previous_amount = salary["amount"]
                salary["amount"] = msg_amount
                salary["currency"] = salary_fact["currency"]
                if salary_fact["first_only"]:
                    salary["after_first_amount"] = previous_amount
                    salary["after_first_currency"] = profile.home_currency
                salary["first_extra"] = salary_fact["extra"]
            if msg_date is not None and msg_date > request.request_date:
                salary["anchor"] = msg_date
                salary["first_is_anchor"] = True
        elif scheduled or msg_confirmed:
            base = scheduled[0] if scheduled else None
            historical = self._regular_income_events(history)
            if base or historical:
                amount = base.amount if base else msg_amount or self._home_amount_stat(historical, profile)
                anchor = base.settlement_date if base else msg_date or add_months(historical[-1].event_date, 1)
                streams.append({
                    "category": "salary", "direction": "credit", "events": historical,
                    "representative": base or historical[-1], "recurrence": ("monthly", 1),
                    "amount": msg_amount or amount,
                    "currency": salary_fact["currency"] if msg_amount else base.currency if base else profile.home_currency,
                    "anchor": anchor, "first_is_anchor": True,
                    "first_extra": salary_fact["extra"],
                    "after_first_amount": amount if salary_fact["first_only"] else None,
                    "after_first_currency": base.currency if base else profile.home_currency,
                    "confidence": {
                        "level": "high", "evidence_count": len(historical),
                        "interval_match_ratio": "1.000", "relative_amount_spread": "0.000",
                    },
                })
        # Apply explicit percentage amendments to the next recurring rent amount.
        for row in self.dataset.messages_by_user.get(request.user_id, []):
            sent = row.get("sent_at", "")[:10]
            if sent and date.fromisoformat(sent) > request.request_date:
                continue
            if row.get("source_type", "").lower() != "service_provider":
                continue
            text = row.get("message_text", "").lower()
            match = re.search(
                r"(?:rent by|sewa bulanan sebesar)\s*([0-9]+(?:\.[0-9]+)?)%", text
            )
            if not match:
                continue
            factor = Decimal("1") + Decimal(match.group(1)) / Decimal("100")
            for stream in streams:
                if stream["category"] == "rent" and stream["direction"] == "debit":
                    stream["amount"] = (stream["amount"] * factor).quantize(Decimal("0.01"))
        return streams

    def _resolved_future_debits(
        self, request: Request, profile: Profile
    ) -> list[dict]:
        end = self.horizon_end(request)
        invalid = {"cancelled", "canceled", "failed", "reversed", "unrealized"}
        result = []
        for event in self.dataset.events.get(request.user_id, []):
            if event.status in invalid or event.status not in {"pending", "scheduled"}:
                continue
            if event.direction != "debit" or not (
                request.request_date <= event.settlement_date <= end
            ):
                continue
            resolved_day = event.settlement_date
            resolved_amount = event.amount or ZERO
            provenance = [{
                "source": "financial_events.csv", "source_timestamp": event.source_timestamp,
                "event_id": event.event_id, "action": "scheduled",
                "amount": str(resolved_amount), "date": resolved_day.isoformat(),
            }]
            # First retain only the newest explicit instruction from each source.
            # If sources still disagree, reserve the larger debit (then the earlier
            # date) rather than silently choosing a more affordable interpretation.
            explicit_by_source: dict[str, dict] = {}
            for row in self.dataset.messages_by_event.get(event.event_id, []):
                sent = row.get("sent_at", "")[:10]
                if sent and date.fromisoformat(sent) > request.request_date:
                    continue
                fact = self.dataset.extractor.message_facts(row.get("message_text", ""))
                provenance.append({
                    "source": row.get("source_type", "unknown"),
                    "source_timestamp": row.get("sent_at", ""),
                    "event_id": event.event_id, "action": fact.action,
                    "amount": str(fact.amount) if fact.amount is not None else "",
                    "date": fact.date,
                })
                if fact.action not in {"cancel", "settle", "amend", "delay"}:
                    continue
                source = row.get("source_type", "unknown").lower()
                prior = explicit_by_source.get(source)
                candidate_amount = prior["amount"] if prior else resolved_amount
                candidate_day = prior["day"] if prior else resolved_day
                if fact.action in {"cancel", "settle"}:
                    candidate_amount = ZERO
                elif fact.action == "amend" and fact.amount is not None:
                    candidate_amount = fact.amount
                if fact.action in {"amend", "delay"} and fact.date:
                    candidate_day = date.fromisoformat(fact.date)
                explicit_by_source[source] = {
                    "amount": candidate_amount, "day": candidate_day,
                    "timestamp": row.get("sent_at", ""), "action": fact.action,
                }
            if explicit_by_source:
                # Debit safety order: higher amount first, then earlier occurrence.
                selected = max(
                    explicit_by_source.values(),
                    key=lambda item: (item["amount"], -item["day"].toordinal()),
                )
                resolved_amount = selected["amount"]
                resolved_day = selected["day"]
            if resolved_amount > ZERO and request.request_date <= resolved_day <= end:
                amount = self.dataset.convert(
                    resolved_amount, event.currency, profile.home_currency, resolved_day
                )
                result.append({
                    "event": event, "day": resolved_day, "amount": amount,
                    "original_amount": event.amount or ZERO,
                    "original_day": event.settlement_date,
                    "provenance": provenance,
                    "resolution_rule": (
                        "explicit action; newest record per source; then larger/earlier debit"
                    ),
                })
        return result

    def _stream_dates(self, stream, start: date, end: date) -> list[date]:
        anchor = stream["anchor"]
        mode, step = stream["recurrence"]
        dates = []
        current = anchor if stream.get("first_is_anchor") else (
            add_months(anchor, step) if mode == "monthly" else anchor + timedelta(days=step)
        )
        while current < start:
            current = add_months(current, step) if mode == "monthly" else current + timedelta(days=step)
        while current <= end:
            dates.append(current)
            current = add_months(current, step) if mode == "monthly" else current + timedelta(days=step)
        return dates

    def daily_cashflows(
        self, request: Request, profile: Profile,
        changes: list[SpendingChange] | None = None,
    ) -> dict[date, Decimal]:
        end = self.horizon_end(request)
        flows: dict[date, Decimal] = defaultdict(lambda: ZERO)
        change_map = {change.event_id: change for change in changes or []}
        streams = self.recurring_streams(request, profile)
        explicit_debits = self._resolved_future_debits(request, profile)
        for stream in streams:
            representative = stream["representative"]
            amount = stream["amount"]
            change = change_map.get(representative.event_id)
            if change:
                amount = ZERO if change.kind == "stop" else change.new_amount or ZERO
            sign = Decimal("1") if stream["direction"] == "credit" else Decimal("-1")
            for index, day in enumerate(self._stream_dates(stream, request.request_date, end)):
                if any(
                    record["day"] == day
                    and record["event"].category == stream["category"]
                    and normalized_description(record["event"].description)
                    == normalized_description(representative.description)
                    for record in explicit_debits
                ):
                    continue
                use_amount = amount
                use_currency = stream.get("currency", profile.home_currency)
                if index > 0 and stream.get("after_first_amount") is not None:
                    use_amount = stream["after_first_amount"]
                    use_currency = stream.get("after_first_currency", use_currency)
                converted = self.dataset.convert(use_amount, use_currency, profile.home_currency, day)
                if index == 0 and stream.get("first_extra"):
                    converted += self.dataset.convert(
                        stream["first_extra"], stream.get("currency", profile.home_currency),
                        profile.home_currency, day,
                    )
                flows[day] += sign * converted

        # Reserve explicit future debits. Credits count only once confirmed/scheduled.
        scheduled_retry_parents = {
            event.linked_event_id
            for event in self.dataset.events.get(request.user_id, [])
            if event.linked_event_id and event.status == "scheduled"
            and event.direction == "debit"
            and request.request_date <= event.settlement_date <= end
        }
        for record in explicit_debits:
            # An explicit future row outranks a recurrence estimate. It may be an
            # arrears balance or retry in the same category, so never replace its
            # supplied amount with a category-level forecast override.
            flows[record["day"]] -= record["amount"]

        # A service-provider message can itself be the only record of confirmed invoice income.
        money_re = re.compile(r"\b(INR|IDR|USD|EUR|ZAR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
        for row in self.dataset.messages_by_user.get(request.user_id, []):
            sent = row.get("sent_at", "")[:10]
            if sent and date.fromisoformat(sent) > request.request_date:
                continue
            text = row.get("message_text", "")
            lower = text.lower()
            if not ("client approved an invoice" in lower or "klien menyetujui pembayaran faktur" in lower):
                continue
            amounts = money_re.findall(text)
            dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)
            if not amounts or not dates:
                continue
            day = date.fromisoformat(dates[-1])
            if request.request_date < day <= end:
                currency, value = amounts[0]
                flows[day] += self.dataset.convert(
                    Decimal(value.replace(",", "")), currency.upper(), profile.home_currency, day
                )

        # Failed debits explicitly described as still outstanding remain protected obligations.
        for event in self.dataset.events.get(request.user_id, []):
            if event.status != "failed":
                continue
            if event.event_id in scheduled_retry_parents:
                continue
            text = " ".join(
                row.get("message_text", "").lower()
                for row in self.dataset.messages_by_event.get(event.event_id, [])
                if not row.get("sent_at")
                or date.fromisoformat(row["sent_at"][:10]) <= request.request_date
            )
            if "still outstanding" in text or "another debit will be attempted" in text:
                flows[request.request_date] -= self.dataset.convert(
                    event.amount or ZERO, event.currency, profile.home_currency, request.request_date
                )
        return flows

    def trajectory(self, request: Request, profile: Profile,
                   payments: list[tuple[date, Decimal]] | None = None,
                   changes: list[SpendingChange] | None = None) -> dict[date, Decimal]:
        end, flows = self.horizon_end(request), self.daily_cashflows(request, profile, changes)
        for day, amount in payments or []:
            if request.request_date <= day <= end: flows[day] -= amount
        balance, result, day = profile.available_balance, {}, request.request_date
        while day <= end:
            balance += flows.get(day, ZERO)
            result[day] = balance
            day += timedelta(days=1)
        return result

    def is_safe(self, request: Request, profile: Profile,
                payments: list[tuple[date, Decimal]],
                changes: list[SpendingChange] | None = None) -> tuple[bool, Decimal]:
        end = self.horizon_end(request)
        if any(day < request.request_date or day > end for day, _ in payments):
            return False, Decimal("-Infinity")
        minimum = min(self.trajectory(request, profile, payments, changes).values())
        return minimum >= profile.minimum_balance, minimum

    def baseline_capacity(self, request: Request, profile: Profile) -> tuple[Decimal, date | None]:
        trajectory = self.trajectory(request, profile)
        min_from, running = {}, Decimal("Infinity")
        for day in sorted(trajectory, reverse=True):
            running = min(running, trajectory[day])
            min_from[day] = running
        today_capacity = max(ZERO, min_from[request.request_date] - profile.minimum_balance)
        safe_today = floor_money(min(request.requested_amount, today_capacity))
        earliest = next((
            day for day in sorted(min_from)
            if min_from[day] - profile.minimum_balance >= request.requested_amount
        ), None)
        return safe_today, earliest

    def evaluate(self, request: Request, profile: Profile, plan: CandidatePlan) -> CandidatePlan:
        plan.safe, plan.minimum_projected_balance = self.is_safe(
            request, profile, plan.payments, plan.changes
        )
        return plan

    def flexible_streams(self, request: Request, profile: Profile):
        result = []
        for stream in self.recurring_streams(request, profile):
            event = stream["representative"]
            if stream["direction"] != "debit" or not event.flexible:
                continue
            if event.category in profile.protected_categories:
                continue
            can_stop = event.flexibility in {"stoppable", "reducible_or_stoppable"} and event.category in profile.stoppable_categories
            can_reduce = event.flexibility in {"reducible", "reducible_or_stoppable"} and event.category in profile.reducible_categories
            if can_stop or can_reduce:
                result.append((stream, can_stop, can_reduce))
        return sorted(result, key=lambda item: item[0]["representative"].event_id)
