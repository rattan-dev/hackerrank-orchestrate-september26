from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from .extraction import UntrustedContentExtractor
from .models import CashEvent, ImageFact, PaymentOption, Profile, Request, ZERO
from .utils import boolean, decimal, first, normalize_method, parse_date, split_set


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class Dataset:
    REQUIRED = {
        "requests.csv", "financial_profiles.csv", "financial_events.csv",
        "request_payment_options.csv", "messages.csv", "images.csv", "exchange_rates.csv",
    }

    def __init__(self, root: Path, use_llm: bool = False) -> None:
        self.root = root
        self.extractor = UntrustedContentExtractor(use_llm=use_llm)
        config_root = Path(__file__).resolve().parents[1] / "config"
        facts_path = config_root / "image_facts.csv"
        self.schema_versions = json.loads(
            (config_root / "schema_version.json").read_text(encoding="utf-8")
        )
        self.image_facts = {}
        for row in read_csv(facts_path):
            amount = decimal(row["amount"])
            if amount is None:
                raise ValueError(f"Invalid cached image amount: {row.get('image_id', '')}")
            fact = ImageFact(
                image_id=row["image_id"], amount=amount, currency=row["currency"].upper(),
                selected_label=row["selected_label"], image_sha256=row["image_sha256"].lower(),
                extraction_method=row["extraction_method"], review_status=row["review_status"],
                confidence=row["confidence"],
            )
            self.image_facts[fact.image_id] = fact
        names = self.REQUIRED | {"sample_requests.csv"}
        self.raw = {name: read_csv(root / name) for name in names}
        self.missing_files = sorted(name for name in self.REQUIRED if not (root / name).exists())
        self.requests = self._requests(self.raw["requests.csv"])
        self.sample_requests = self._requests(self.raw["sample_requests.csv"])
        self.sample_answers = {row["request_id"]: row for row in self.raw["sample_requests.csv"]}
        self.profiles = self._profiles()
        self.rates = self._rates()
        self.messages_by_event, self.messages_by_user, self.messages_by_request = self._messages()
        self.image_rows = self._images()
        self.events = self._events()
        self.options = self._options()

    def validate(self) -> None:
        if self.missing_files:
            raise FileNotFoundError("Missing required dataset files: " + ", ".join(self.missing_files))
        required_versions = {"input_schema", "output_schema", "image_fact_cache"}
        if set(self.schema_versions) != required_versions:
            raise ValueError("schema_version.json does not define the required schema versions")
        self._validate_unique("requests.csv", "request_id")
        self._validate_unique("sample_requests.csv", "request_id")
        self._validate_unique("financial_profiles.csv", "user_id")
        self._validate_unique("financial_events.csv", "event_id")
        self._validate_unique("request_payment_options.csv", "payment_option_id")
        self._validate_unique("messages.csv", "message_id")
        self._validate_unique("images.csv", "image_id")
        self._validate_unique("exchange_rates.csv", "rate_date", "from_currency", "to_currency")
        sample_ids = {first(row, "request_id") for row in self.raw["sample_requests.csv"]}
        evaluation_ids = {first(row, "request_id") for row in self.raw["requests.csv"]}
        request_ids = sample_ids | evaluation_ids
        if sample_ids & evaluation_ids:
            raise ValueError("sample_requests.csv and requests.csv contain overlapping IDs")
        missing_profiles = {
            r.user_id for r in self.requests + self.sample_requests
        } - self.profiles.keys()
        if missing_profiles:
            raise ValueError(f"Missing profiles for {len(missing_profiles)} request users")
        valid_types = {
            "purchase", "travel", "education", "family_transfer", "debt_repayment",
            "investment", "housing", "emergency_expense", "other",
        }
        for request in self.requests + self.sample_requests:
            if not request.request_id or not request.user_id:
                raise ValueError("Request IDs and user IDs must be non-empty")
            if request.request_type not in valid_types:
                raise ValueError(f"Invalid request type for {request.request_id}: {request.request_type}")
            if request.requested_amount <= ZERO:
                raise ValueError(f"Requested amount must be positive: {request.request_id}")
            if request.desired_completion_date < request.request_date:
                raise ValueError(f"Completion date precedes request date: {request.request_id}")
        for profile in self.profiles.values():
            if profile.available_balance < ZERO or profile.minimum_balance < ZERO:
                raise ValueError(f"Negative balance or minimum for {profile.user_id}")
            if profile.max_installment_months is not None and profile.max_installment_months <= 0:
                raise ValueError(f"Invalid installment limit for {profile.user_id}")
        event_rows = {first(row, "event_id"): row for row in self.raw["financial_events.csv"]}
        valid_statuses = {
            "settled", "pending", "scheduled", "failed", "cancelled", "canceled",
            "reversed", "unrealized",
        }
        for event_id, row in event_rows.items():
            status = first(row, "status").lower()
            if status not in valid_statuses:
                raise ValueError(f"Invalid status for {event_id}: {status}")
            raw_amount = decimal(first(row, "amount"))
            if raw_amount is not None and raw_amount <= ZERO:
                raise ValueError(f"Non-positive supplied amount for {event_id}")
            flexibility = first(row, "flexibility", default="fixed").lower()
            if flexibility not in {"fixed", "reducible", "stoppable", "reducible_or_stoppable"}:
                raise ValueError(f"Invalid flexibility for {event_id}: {flexibility}")
            minimum = decimal(first(row, "minimum_allowed_amount"))
            if minimum is not None and (minimum < ZERO or raw_amount is not None and minimum >= raw_amount):
                raise ValueError(f"Invalid minimum allowed amount for {event_id}")
            linked = first(row, "linked_event_id")
            if linked:
                if linked not in event_rows:
                    raise ValueError(f"Unknown linked event for {event_id}: {linked}")
                if first(event_rows[linked], "user_id") != first(row, "user_id"):
                    raise ValueError(f"Cross-user event link for {event_id}: {linked}")
        for file_name in ("messages.csv", "images.csv"):
            for row in self.raw[file_name]:
                linked = first(row, "related_event_id")
                if linked and linked not in event_rows:
                    raise ValueError(f"Unknown related event in {file_name}: {linked}")
                if linked and first(event_rows[linked], "user_id") != first(row, "user_id"):
                    raise ValueError(f"Cross-user event reference in {file_name}: {linked}")
                request_id = first(row, "request_id")
                if request_id and request_id not in request_ids:
                    raise ValueError(f"Unknown request in {file_name}: {request_id}")
                if request_id:
                    linked_request = next(
                        request for request in self.requests + self.sample_requests
                        if request.request_id == request_id
                    )
                    if linked_request.user_id != first(row, "user_id"):
                        raise ValueError(f"Cross-user request reference in {file_name}: {request_id}")
        for row in self.raw["images.csv"]:
            image_id = first(row, "image_id")
            image_path = self.root / "media" / "images" / f"{image_id}.png"
            if not image_path.exists():
                raise FileNotFoundError(f"Missing linked image: {image_id}.png")
            fact = self.image_facts.get(image_id)
            if fact is None:
                continue
            linked_event = event_rows[first(row, "related_event_id")]
            if fact.currency != first(linked_event, "currency").upper():
                raise ValueError(f"Cached image currency mismatch: {image_id}")
            if fact.review_status != "verified" or fact.confidence not in {"medium", "high"}:
                raise ValueError(f"Unreviewed or low-confidence cached image fact: {image_id}")
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if digest != fact.image_sha256:
                raise ValueError(f"Cached image hash mismatch: {image_id}")
        for request_id, options in self.options.items():
            if request_id not in request_ids:
                raise ValueError(f"Payment option references unknown request: {request_id}")
            for option in options:
                if option.method not in {"full_payment", "installments"}:
                    raise ValueError(f"Invalid option method: {option.payment_option_id}")
                if option.payment_count <= 0 or option.total_payable <= ZERO:
                    raise ValueError(f"Invalid payment option: {option.payment_option_id}")
                if any(amount <= ZERO for _, amount in option.schedule()):
                    raise ValueError(f"Non-positive option payment: {option.payment_option_id}")
                if sum((amount for _, amount in option.schedule()), ZERO) != option.total_payable:
                    raise ValueError(f"Option payments do not total payable: {option.payment_option_id}")
        for user_id, events in self.events.items():
            if user_id not in self.profiles:
                raise ValueError(f"Financial event references unknown user: {user_id}")
            for event in events:
                if event.amount is None or event.amount < ZERO:
                    raise ValueError(f"Invalid amount for {event.event_id}")
                if event.direction not in {"credit", "debit", "non_cash"}:
                    raise ValueError(f"Invalid direction for {event.event_id}: {event.direction}")

    def _validate_unique(self, file_name: str, *keys: str) -> None:
        seen: set[tuple[str, ...]] = set()
        for row in self.raw[file_name]:
            value = tuple(first(row, key) for key in keys)
            if not all(value):
                raise ValueError(f"Blank key in {file_name}: {keys}")
            if value in seen:
                raise ValueError(f"Duplicate key in {file_name}: {value}")
            seen.add(value)

    def _requests(self, rows: list[dict[str, str]]) -> list[Request]:
        return [
            Request(
                request_id=first(row, "request_id"), user_id=first(row, "user_id"),
                request_date=parse_date(first(row, "request_date")),
                request_type=first(row, "request_type").lower(),
                requested_amount=decimal(first(row, "requested_amount"), ZERO) or ZERO,
                desired_completion_date=parse_date(first(row, "desired_completion_date")),
                allows_partial_payment=boolean(first(row, "allows_partial_payment")),
                request_text=first(row, "request_text"),
            ) for row in rows
        ]

    def _profiles(self) -> dict[str, Profile]:
        result = {}
        for row in self.raw["financial_profiles.csv"]:
            user = first(row, "user_id")
            months = decimal(first(row, "max_installment_months"))
            result[user] = Profile(
                user_id=user, home_currency=first(row, "home_currency").upper(),
                available_balance=decimal(first(row, "current_available_balance"), ZERO) or ZERO,
                minimum_balance=decimal(first(row, "minimum_balance_to_keep"), ZERO) or ZERO,
                methods={normalize_method(x) for x in split_set(first(row, "payment_methods_user_will_consider"))},
                priorities=first(row, "financial_priorities"),
                protected_categories=split_set(first(row, "expense_categories_to_protect")),
                reducible_categories=split_set(first(row, "expense_categories_user_is_willing_to_reduce")),
                stoppable_categories=split_set(first(row, "expense_categories_user_is_willing_to_stop")),
                max_installment_months=int(months) if months is not None else None,
            )
        return result

    def _rates(self) -> dict[tuple[str, str, date], Decimal]:
        result = {}
        for row in self.raw["exchange_rates.csv"]:
            source, target = first(row, "from_currency").upper(), first(row, "to_currency").upper()
            day, rate = parse_date(first(row, "rate_date")), decimal(first(row, "rate"))
            if source and target and rate:
                result[(source, target, day)] = rate
        return result

    def convert(self, amount: Decimal, source: str, target: str, day: date) -> Decimal:
        if not source or source == target:
            return amount
        exact = self.rates.get((source, target, day))
        if exact is None:
            raise ValueError(f"Missing exact exchange rate for {source}->{target} on {day}")
        return amount * exact

    def _messages(self):
        by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
        by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
        by_request: dict[str, list[dict[str, str]]] = defaultdict(list)
        for index, row in enumerate(self.raw["messages.csv"]):
            row["__order"] = str(index)
            by_user[first(row, "user_id")].append(row)
            if first(row, "related_event_id"):
                by_event[first(row, "related_event_id")].append(row)
            if first(row, "request_id"):
                by_request[first(row, "request_id")].append(row)
        key = lambda r: (first(r, "sent_at"), int(r["__order"]))
        for mapping in (by_event, by_user, by_request):
            for rows in mapping.values(): rows.sort(key=key)
        return by_event, by_user, by_request

    def _images(self) -> dict[str, list[dict[str, str]]]:
        by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.raw["images.csv"]:
            if first(row, "related_event_id"):
                by_event[first(row, "related_event_id")].append(row)
        return by_event

    def _image_amount(self, event_id: str, description: str) -> Decimal | None:
        amounts = []
        for row in self.image_rows.get(event_id, []):
            image_id = first(row, "image_id")
            if self.image_facts.get(image_id) is not None:
                amounts.append(self.image_facts[image_id].amount)
                continue
            path = self.root / "media" / "images" / f"{image_id}.png"
            if path.exists():
                found = self.extractor.financial_document_amount(
                    self.extractor.image_text(path), description
                )
                if found is not None: amounts.append(found)
        return amounts[-1] if amounts else None

    def _events(self) -> dict[str, list[CashEvent]]:
        parsed: dict[str, CashEvent] = {}
        for row in self.raw["financial_events.csv"]:
            event_id, description = first(row, "event_id"), first(row, "description")
            amount = decimal(first(row, "amount"))
            if amount is None: amount = self._image_amount(event_id, description)
            if amount is None: raise ValueError(f"Could not extract amount for {event_id}: {description}")
            event_day = parse_date(first(row, "event_date"))
            parsed[event_id] = CashEvent(
                event_id=event_id, user_id=first(row, "user_id"), event_date=event_day,
                settlement_date=parse_date(first(row, "settlement_date"), event_day),
                amount=abs(amount), currency=first(row, "currency").upper(),
                direction=first(row, "direction").lower(), status=first(row, "status").lower(),
                event_type=first(row, "event_type").lower(), category=first(row, "category").lower(),
                description=description, flexibility=first(row, "flexibility", default="fixed").lower(),
                minimum_allowed_amount=decimal(first(row, "minimum_allowed_amount")),
                linked_event_id=first(row, "linked_event_id"), source_timestamp=first(row, "settlement_date", "event_date"),
            )
        # A link describes a lifecycle but does not itself erase either cash row.
        # Only explicit cancellations/reversals and settled refunds supersede the
        # earlier event for recurrence training. A failed child is not a reversal,
        # and a settled correction linked to a cancelled attempt is real cash.
        superseded = {
            event.linked_event_id for event in parsed.values()
            if event.linked_event_id and (
                event.status in {"cancelled", "canceled", "reversed"}
                or (event.status == "settled" and event.event_type in {"refund", "reversal"})
            )
        }
        grouped: dict[str, list[CashEvent]] = defaultdict(list)
        for event in parsed.values():
            if event.event_id not in superseded: grouped[event.user_id].append(event)
        for events in grouped.values(): events.sort(key=lambda e: (e.settlement_date, e.event_id))
        return grouped

    def _options(self) -> dict[str, list[PaymentOption]]:
        grouped: dict[str, list[PaymentOption]] = defaultdict(list)
        for row in self.raw["request_payment_options.csv"]:
            count = int(decimal(first(row, "number_of_payments"), Decimal("1")) or 1)
            amount = decimal(first(row, "payment_amount"), ZERO) or ZERO
            request_id = first(row, "request_id")
            grouped[request_id].append(PaymentOption(
                payment_option_id=first(row, "payment_option_id"), request_id=request_id,
                method=normalize_method(first(row, "payment_method")),
                first_payment_date=parse_date(first(row, "first_payment_date")), payment_count=count,
                interval_days=int(decimal(first(row, "payment_frequency_days"), ZERO) or 0),
                total_payable=decimal(first(row, "total_payable_amount"), ZERO) or ZERO,
                payments=tuple([amount] * count),
            ))
        return grouped
