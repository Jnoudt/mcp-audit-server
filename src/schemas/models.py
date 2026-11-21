"""Pydantic v2 schemas for deterministic MCP audit operations."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and floating-point values."""

    model_config = ConfigDict(extra="forbid", strict=True)


class TaxJurisdiction(str, Enum):
    US_FEDERAL = "US_FEDERAL"
    US_STATE = "US_STATE"


class MoneyInput(StrictModel):
    amount: Decimal = Field(..., description="Decimal amount, without floating-point approximation")
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("amount")
    @classmethod
    def finite_and_scaled(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("amount must be finite")
        return value

    @field_validator("currency")
    @classmethod
    def normalized_currency(cls, value: str) -> str:
        return value.upper()


class TaxCalculateRequest(StrictModel):
    amount: Decimal = Field(..., gt=Decimal("0"))
    tax_rate: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    jurisdiction: TaxJurisdiction = TaxJurisdiction.US_FEDERAL

    @field_validator("amount", "tax_rate", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)


class TaxCalculateResult(StrictModel):
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    jurisdiction: TaxJurisdiction


class ComplianceCheckRequest(StrictModel):
    transaction_id: str = Field(..., min_length=1, max_length=128)
    amount: Decimal = Field(..., gt=Decimal("0"))
    currency: str = Field(default="USD", min_length=3, max_length=3)
    jurisdiction: TaxJurisdiction = TaxJurisdiction.US_FEDERAL

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)


class ComplianceCheckResult(StrictModel):
    transaction_id: str
    compliant: bool
    reasons: list[str]


class AuditRecord(StrictModel):
    trace_id: str = Field(..., min_length=1, max_length=128)
    tenantId: str = Field(..., min_length=1, max_length=128)
    tool_name: str = Field(..., min_length=1, max_length=128)
    method: Literal["tools/call"] = "tools/call"
    request_summary: dict[str, Any]
    output_summary: dict[str, Any]
    duration_ms: int = Field(..., ge=0)
    status: Literal["success", "error"]
    error_code: int | None = None
    timestamp: str


class JSONRPCRequest(StrictModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class InvoiceLineItem(StrictModel):
    description: str = Field(default="", max_length=256)
    quantity: Decimal = Field(..., gt=Decimal("0"))
    unit_price: Decimal = Field(..., ge=Decimal("0"))

    @field_validator("quantity", "unit_price", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)


class InvoiceReconciliationRequest(StrictModel):
    tenantId: str = Field(..., min_length=1, max_length=128)
    invoice_id: str = Field(..., min_length=1, max_length=128)
    line_items: list[InvoiceLineItem] = Field(..., min_length=1, max_length=1000)
    reported_subtotal: Decimal = Field(..., ge=Decimal("0"))
    tax_rate: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))
    reported_tax: Decimal = Field(..., ge=Decimal("0"))
    reported_total: Decimal = Field(..., ge=Decimal("0"))

    @field_validator("reported_subtotal", "tax_rate", "reported_tax", "reported_total", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)

    @field_validator("tenantId")
    @classmethod
    def invoice_tenant_must_be_safe(cls, value: str) -> str:
        return validate_tenant_id(value)


class InvoiceReconciliationResult(StrictModel):
    invoice_id: str
    calculated_line_sum: Decimal
    reported_subtotal: Decimal
    subtotal_variance: Decimal
    calculated_tax: Decimal
    reported_tax: Decimal
    tax_variance: Decimal
    calculated_total: Decimal
    reported_total: Decimal
    total_variance: Decimal
    pass_reconciliation: bool
    findings: list[str]


class PolicyThresholds(StrictModel):
    spend_limit: Decimal = Field(..., ge=Decimal("0"))
    require_vat: bool = False
    sla_days: int = Field(default=30, ge=0, le=3650)

    @field_validator("spend_limit", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)


class PolicyComplianceRequest(StrictModel):
    tenantId: str = Field(..., min_length=1, max_length=128)
    amount: Decimal = Field(..., ge=Decimal("0"))
    currency: str = Field(default="USD", min_length=3, max_length=3)
    approval_tier: str | None = Field(default=None, max_length=64)
    vat_registered: bool = False
    due_date: date | None = None
    as_of_date: date = Field(default_factory=date.today)
    policy: PolicyThresholds

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_values(cls, value: Any) -> Any:
        return _decimal_from_json(value)

    @field_validator("due_date", "as_of_date", mode="before")
    @classmethod
    def parse_iso_dates(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("dates must use ISO YYYY-MM-DD format") from exc
        return value

    @field_validator("tenantId")
    @classmethod
    def tenant_must_be_safe(cls, value: str) -> str:
        return validate_tenant_id(value)

    @field_validator("approval_tier")
    @classmethod
    def approval_tier_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in APPROVAL_TIERS:
            raise ValueError("approval_tier is not supported")
        return value


class PolicyComplianceResult(StrictModel):
    tenant_id: str
    compliant: bool
    violations: list[str]
    approval_tier: str


class AuditTrailRequest(StrictModel):
    tenantId: str = Field(..., min_length=1, max_length=128)
    tool_name: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)

    @field_validator("tenantId")
    @classmethod
    def tenant_must_be_safe(cls, value: str) -> str:
        return validate_tenant_id(value)


class AuditTrailResult(StrictModel):
    tenant_id: str
    records: list[dict[str, Any]]
    next_cursor: str | None
    count: int


TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
APPROVAL_TIERS = {"none", "manager", "executive"}


def validate_tenant_id(value: str) -> str:
    if not TENANT_ID_PATTERN.fullmatch(value):
        raise ValueError("tenantId contains unsupported characters")
    return value


def _decimal_from_json(value: Any) -> Any:
    if isinstance(value, (float, bool)):
        raise ValueError("floating-point values are not allowed; send a decimal string")
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception as exc:
            raise ValueError("invalid decimal string") from exc
    return value
