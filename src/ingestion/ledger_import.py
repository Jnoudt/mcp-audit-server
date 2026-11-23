"""Canonicalize a profiled DataFrame and store it under immutable ownership keys."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy.engine import Connection, Engine

from .ledger_types import LedgerType, canonical_column_map, identify_ledger_type
from .schema_builder import create_schema, ledger_imports, ledger_tables, source_columns
from .type_detection import ColumnProfile, DataKind, profile_dataframe

_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_DATE_FIELDS = {"invoice_date", "posting_date", "due_date", "in_service_date", "value_date"}
_DECIMAL_FIELDS = {
    "amount",
    "acquisition_cost",
    "accumulated_depreciation",
    "period_depreciation",
    "quantity",
    "unit_cost",
    "total_cost",
}


@dataclass(frozen=True)
class LedgerImportResult:
    import_id: str
    ledger_type: LedgerType
    row_count: int
    column_profiles: tuple[dict[str, Any], ...]


def import_ledger_dataframe(
    engine: Engine | Connection,
    frame: pd.DataFrame,
    *,
    tenant_id: str,
    owner_user_id: str,
    request_id: str,
    document_id: str,
    source_system: str,
    batch_size: int = 500,
) -> LedgerImportResult:
    """Insert a known ledger profile into its fixed SQL table in one transaction."""
    for label, value in (
        ("tenant_id", tenant_id),
        ("owner_user_id", owner_user_id),
        ("request_id", request_id),
        ("document_id", document_id),
    ):
        if not _IDENTITY_PATTERN.fullmatch(value):
            raise ValueError(f"{label} has an invalid format.")
    if not source_system.strip() or len(source_system) > 128:
        raise ValueError("source_system must contain 1 to 128 characters.")
    if batch_size < 1 or batch_size > 5000:
        raise ValueError("batch_size must be between 1 and 5000.")
    if frame.empty:
        raise ValueError("A ledger import must contain at least one row.")

    ledger_type = identify_ledger_type(frame.columns)
    column_map = canonical_column_map(ledger_type, frame.columns)
    profiles = profile_dataframe(frame)
    excluded_columns = {profile.name for profile in profiles if not profile.analysis_allowed}
    _validate_profile(ledger_type, profiles, column_map)
    table = ledger_tables[ledger_type]
    import_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)

    def insert_rows(connection: Connection) -> None:
        connection.execute(
            ledger_imports.insert().values(
                tenant_id=tenant_id,
                import_id=import_id,
                document_id=document_id,
                request_id=request_id,
                owner_user_id=owner_user_id,
                ledger_type=ledger_type.value,
                source_system=source_system.strip(),
                schema_version=1,
                row_count=len(frame.index),
                created_at=created_at,
            )
        )
        canonical_by_source = {
            source_name: canonical_name
            for canonical_name, source_name in column_map.items()
        }
        connection.execute(
            source_columns.insert(),
            [
                {
                    "tenant_id": tenant_id,
                    "import_id": import_id,
                    "ordinal": ordinal,
                    "source_name": profile.name,
                    "canonical_name": canonical_by_source.get(profile.name),
                    "inferred_type": profile.kind.value,
                    "is_nullable": profile.nullable,
                    "analysis_allowed": profile.analysis_allowed,
                }
                for ordinal, profile in enumerate(profiles, start=1)
            ],
        )
        batch: list[dict[str, Any]] = []
        for row_number, values in enumerate(frame.itertuples(index=False, name=None), start=1):
            source_row = dict(zip(frame.columns, values, strict=True))
            record: dict[str, Any] = {
                "tenant_id": tenant_id,
                "import_id": import_id,
                "row_number": row_number,
                "document_id": document_id,
                "request_id": request_id,
                "owner_user_id": owner_user_id,
                "source_payload_json": json.dumps(
                    {
                        str(name): _source_value(value)
                        for name, value in source_row.items()
                        if str(name) not in excluded_columns
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
            for canonical_name, source_name in column_map.items():
                record[canonical_name] = _convert_value(
                    canonical_name,
                    source_row[source_name],
                    row_number,
                )
            _validate_record(ledger_type, record, row_number)
            batch.append(record)
            if len(batch) >= batch_size:
                connection.execute(table.insert(), batch)
                batch.clear()
        if batch:
            connection.execute(table.insert(), batch)

    create_schema(engine)
    if isinstance(engine, Engine):
        with engine.begin() as connection:
            insert_rows(connection)
    else:
        insert_rows(engine)

    return LedgerImportResult(
        import_id=import_id,
        ledger_type=ledger_type,
        row_count=len(frame.index),
        column_profiles=tuple(
            {
                "name": profile.name,
                "kind": profile.kind.value,
                "nullable": profile.nullable,
                "analysis_allowed": profile.analysis_allowed,
            }
            for profile in profiles
        ),
    )


def _convert_value(name: str, raw_value: Any, row_number: int) -> Any:
    value = "" if raw_value is None or pd.isna(raw_value) else str(raw_value).strip()
    if not value:
        return None
    try:
        if name in _DATE_FIELDS:
            return date.fromisoformat(value)
        if name in _DECIMAL_FIELDS:
            result = Decimal(value)
            if not result.is_finite():
                raise ValueError
            return result
        if name == "fiscal_year":
            return int(value)
        if name == "currency":
            currency = value.upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError
            return currency
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"Invalid {name} value at source row {row_number}; verify the column mapping and format."
        ) from exc
    return value


def _source_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value)
    return text if text else None


def _validate_record(ledger_type: LedgerType, record: dict[str, Any], row_number: int) -> None:
    required_by_type: dict[LedgerType, tuple[str, ...]] = {
        LedgerType.GENERAL_LEDGER: ("document_number", "posting_date", "account_code", "amount"),
        LedgerType.ACCOUNTS_RECEIVABLE: ("customer_id", "invoice_number", "invoice_date", "amount"),
        LedgerType.ACCOUNTS_PAYABLE: ("vendor_id", "invoice_number", "invoice_date", "amount"),
        LedgerType.FIXED_ASSETS: ("asset_id", "acquisition_cost", "accumulated_depreciation"),
        LedgerType.INVENTORY: ("item_id", "movement_type", "posting_date", "quantity"),
        LedgerType.CASH_BANK: ("bank_account", "transaction_id", "value_date", "amount"),
    }
    missing = [field for field in required_by_type[ledger_type] if record.get(field) is None]
    if missing:
        raise ValueError(
            f"Required values missing at source row {row_number}: {', '.join(missing)}."
        )


def _validate_profile(
    ledger_type: LedgerType,
    profiles: list[ColumnProfile],
    column_map: dict[str, str],
) -> None:
    profile_by_name = {profile.name: profile for profile in profiles}
    source_by_canonical = {
        canonical_name: source_name
        for canonical_name, source_name in column_map.items()
    }
    date_fields = {
        "posting_date",
        "invoice_date",
        "due_date",
        "in_service_date",
        "value_date",
    }
    decimal_fields = {
        "amount",
        "acquisition_cost",
        "accumulated_depreciation",
        "period_depreciation",
        "quantity",
        "unit_cost",
        "total_cost",
    }
    required_fields = {
        LedgerType.GENERAL_LEDGER: ("posting_date", "amount"),
        LedgerType.ACCOUNTS_RECEIVABLE: ("invoice_date", "amount"),
        LedgerType.ACCOUNTS_PAYABLE: ("invoice_date", "amount"),
        LedgerType.FIXED_ASSETS: ("acquisition_cost", "accumulated_depreciation"),
        LedgerType.INVENTORY: ("posting_date", "quantity"),
        LedgerType.CASH_BANK: ("value_date", "amount"),
    }[ledger_type]
    allowed_numeric_kinds = {DataKind.DECIMAL, DataKind.INTEGER}
    for canonical_name in required_fields:
        profile = profile_by_name[source_by_canonical[canonical_name]]
        allowed = (
            {DataKind.DATE}
            if canonical_name in date_fields
            else allowed_numeric_kinds
            if canonical_name in decimal_fields
            else {DataKind.TEXT}
        )
        if profile.kind not in allowed:
            raise ValueError(
                f"Column '{profile.name}' does not match the expected {canonical_name} data type; "
                "review the file mapping before import."
            )
