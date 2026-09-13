from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


TRUE_VALUES = {"1", "true", "yes", "y", "flexible", "active"}


def first(row: dict[str, str], *names: str, default: str = "") -> str:
    lowered = {str(k).strip().lower(): (v or "") for k, v in row.items()}
    for name in names:
        value = lowered.get(name.lower(), "")
        if str(value).strip() != "":
            return str(value).strip()
    return default


def parse_date(value: str, fallback: date | None = None) -> date:
    text = str(value or "").strip()
    if not text:
        if fallback is None:
            raise ValueError("missing date")
        return fallback
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def decimal(value: str | int | float | Decimal | None, default: Decimal | None = None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return default
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return default


def boolean(value: str) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def split_set(value: str) -> set[str]:
    return {
        item.strip().lower()
        for item in re.split(r"[|,;]", str(value or ""))
        if item.strip()
    }


def normalize_method(value: str) -> str:
    text = str(value or "").lower().replace("-", "_").replace(" ", "_")
    if "install" in text or "emi" in text:
        return "installments"
    if "partial" in text or "split" in text:
        return "partial_payment"
    if "full" in text or text in {"cash", "pay_now", "one_time"}:
        return "full_payment"
    return text


def numeric_id_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", value or "")
    return tuple(int(p) if p.isdigit() else p for p in parts)

