"""Conservative column profiling; inferred types never mutate source values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

import pandas as pd


class DataKind(StrEnum):
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "timestamp"
    DECIMAL = "decimal"
    INTEGER = "integer"
    TEXT = "text"
    GROUND_TRUTH = "ground_truth_only"


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    kind: DataKind
    row_count: int
    non_empty_count: int
    empty_count: int
    nullable: bool
    analysis_allowed: bool


_GROUND_TRUTH_NAMES = {"audittag", "auditlabel", "injectedanomalyflag"}
_IDENTIFIER_MARKERS = (
    "account",
    "acct",
    "asset",
    "bankaccount",
    "accountid",
    "accountno",
    "acctno",
    "code",
    "company",
    "customer",
    "document",
    "entity",
    "iban",
    "hktid",
    "ibanlocal",
    "invoice",
    "item",
    "number",
    "payment",
    "phone",
    "po",
    "postal",
    "record",
    "reference",
    "routing",
    "sku",
    "tax",
    "vendor",
    "voucher",
    "zip",
)
_DATE_MARKERS = ("date", "budat", "bldat", "valut", "whenposted", "whendue", "aktiv")
_NUMERIC_MARKERS = (
    "amount",
    "amt",
    "balance",
    "cost",
    "debit",
    "credit",
    "depreciation",
    "hsl",
    "quantity",
    "qty",
    "rate",
    "total",
    "value",
    "wrbtr",
    "dmbtr",
)
_BOOLEAN_VALUES = {"true", "false", "yes", "no", "y", "n"}
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


def profile_dataframe(frame: pd.DataFrame) -> list[ColumnProfile]:
    """Infer conservative SQL-oriented types for all columns in a DataFrame."""
    profiles: list[ColumnProfile] = []
    for name in frame.columns:
        values = frame[name].astype("string").str.strip()
        present = values[values.ne("") & values.notna()]
        normalized_name = _normalize_name(str(name))
        ground_truth = normalized_name in _GROUND_TRUTH_NAMES
        if ground_truth:
            kind = DataKind.GROUND_TRUTH
        elif not len(present):
            kind = DataKind.TEXT
        else:
            kind = _infer_kind(normalized_name, present.tolist())
        empty_count = len(frame.index) - len(present)
        profiles.append(
            ColumnProfile(
                name=str(name),
                kind=kind,
                row_count=len(frame.index),
                non_empty_count=len(present),
                empty_count=empty_count,
                nullable=empty_count > 0,
                analysis_allowed=not ground_truth,
            )
        )
    return profiles


def _infer_kind(name: str, values: list[str]) -> DataKind:
    if any(marker in name for marker in _DATE_MARKERS):
        if all(_is_date(value) for value in values):
            return DataKind.DATE
        if all(_is_datetime(value) for value in values):
            return DataKind.DATETIME
        return DataKind.TEXT
    if _is_identifier_name(name) and not any(marker in name for marker in _NUMERIC_MARKERS):
        return DataKind.TEXT
    if name in {"gjahr", "fiscalyear", "financialyear", "taxyear", "year"}:
        return DataKind.INTEGER if all(_is_integer(value) for value in values) else DataKind.TEXT
    lowered = {value.casefold() for value in values}
    if lowered <= _BOOLEAN_VALUES:
        return DataKind.BOOLEAN
    decimals = [_as_decimal(value) for value in values]
    if all(value is not None for value in decimals):
        if any(
            _INTEGER_PATTERN.fullmatch(value) and len(value) > 1 and value.startswith("0")
            for value in values
        ):
            return DataKind.TEXT
        return (
            DataKind.INTEGER
            if all(_INTEGER_PATTERN.fullmatch(value) for value in values)
            else DataKind.DECIMAL
        )
    if all(_is_date(value) for value in values):
        return DataKind.DATE
    if all(_is_datetime(value) for value in values):
        return DataKind.DATETIME
    return DataKind.TEXT


def _is_identifier_name(name: str) -> bool:
    return (
        name in {"id", "uuid", "guid", "rowid"}
        or name.endswith("id")
        or any(marker in name for marker in _IDENTIFIER_MARKERS)
    )


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _is_integer(value: str) -> bool:
    return bool(_INTEGER_PATTERN.fullmatch(value))


def _is_date(value: str) -> bool:
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_datetime(value: str) -> bool:
    if len(value) <= 10:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _as_decimal(value: str) -> Decimal | None:
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None
