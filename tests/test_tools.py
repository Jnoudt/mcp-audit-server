from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from src.audit_store import CosmosAuditStore, InMemoryAuditStore
from src.schemas.models import (
    AuditTrailRequest,
    InvoiceReconciliationRequest,
    PolicyComplianceRequest,
)
from src.tools.audit_trail import query_audit_trail
from src.tools.policy_check import evaluate_policy_compliance
from src.tools.reconcile import validate_invoice_math


@pytest.fixture
def invoice_args() -> dict[str, object]:
    return {
        "tenantId": "tenant-a",
        "invoice_id": "INV-100",
        "line_items": [
            {"description": "Consulting", "quantity": "2", "unit_price": "125.50"},
            {"description": "Expense", "quantity": "1", "unit_price": "49.00"},
        ],
        "reported_subtotal": "300.00",
        "tax_rate": "0.20",
        "reported_tax": "60.00",
        "reported_total": "360.00",
    }


def test_reconcile_happy_path_uses_decimal_round_half_up(invoice_args: dict[str, object]) -> None:
    result = validate_invoice_math(invoice_args)

    assert result["pass_reconciliation"] is True
    assert result["findings"] == []
    assert Decimal(str(result["calculated_line_sum"])) == Decimal("300.00")
    assert Decimal(str(result["calculated_tax"])) == Decimal("60.00")
    assert Decimal(str(result["calculated_total"])) == Decimal("360.00")


def test_reconcile_reports_each_variance(invoice_args: dict[str, object]) -> None:
    invoice_args["reported_subtotal"] = "299.00"
    invoice_args["reported_tax"] = "59.00"
    invoice_args["reported_total"] = "358.00"

    result = validate_invoice_math(invoice_args)

    assert result["pass_reconciliation"] is False
    findings = result["findings"]
    assert isinstance(findings, list)
    assert set(findings) == {
        "line_item_total_mismatch",
        "tax_amount_mismatch",
        "total_mismatch",
    }
    assert Decimal(str(result["subtotal_variance"])) == Decimal("1.00")
    assert Decimal(str(result["tax_variance"])) == Decimal("0.80")
    assert Decimal(str(result["total_variance"])) == Decimal("0.80")


def test_reconcile_rounds_to_cents_with_half_up() -> None:
    arguments: dict[str, object] = {
        "tenantId": "tenant-a",
        "invoice_id": "INV-ROUND",
        "line_items": [{"quantity": "1", "unit_price": "1.005"}],
        "reported_subtotal": "1.01",
        "tax_rate": "0.00",
        "reported_tax": "0.00",
        "reported_total": "1.01",
    }
    result = validate_invoice_math(arguments)

    assert result["pass_reconciliation"] is True


@pytest.mark.parametrize("amount", [None, "NaN", "Infinity", "-1", 12.5])
def test_reconcile_rejects_invalid_decimal_inputs(amount: object) -> None:
    arguments: dict[str, object] = {
        "tenantId": "tenant-a",
        "invoice_id": "INV-BAD",
        "line_items": [{"quantity": "1", "unit_price": amount}],
        "reported_subtotal": "1.00",
        "tax_rate": "0.10",
        "reported_tax": "0.10",
        "reported_total": "1.10",
    }

    with pytest.raises(ValidationError):
        validate_invoice_math(arguments)


def test_reconcile_rejects_extra_fields(invoice_args: dict[str, object]) -> None:
    invoice_args["unexpected"] = True

    with pytest.raises(ValidationError):
        InvoiceReconciliationRequest.model_validate(invoice_args)


def test_policy_compliant() -> None:
    result = evaluate_policy_compliance({
        "tenantId": "tenant-a",
        "amount": "500.00",
        "currency": "USD",
        "approval_tier": "none",
        "vat_registered": True,
        "as_of_date": "2026-11-21",
        "due_date": "2026-12-01",
        "policy": {"spend_limit": "1000.00", "require_vat": True, "sla_days": 30},
    })

    assert result["compliant"] is True
    assert result["violations"] == []


def test_policy_reports_all_violation_types() -> None:
    result = evaluate_policy_compliance({
        "tenantId": "tenant-a",
        "amount": "20000.00",
        "approval_tier": "manager",
        "vat_registered": False,
        "as_of_date": "2026-11-21",
        "due_date": "2026-11-20",
        "policy": {"spend_limit": "1000.00", "require_vat": True, "sla_days": 30},
    })

    assert result["compliant"] is False
    violations = result["violations"]
    assert isinstance(violations, list)
    assert set(violations) >= {
        "spend_limit_exceeded",
        "executive_approval_required",
        "vat_registration_required",
        "past_due",
    }


def test_policy_sla_window_and_float_rejection() -> None:
    result = evaluate_policy_compliance({
        "tenantId": "tenant-a",
        "amount": "1001.00",
        "approval_tier": "manager",
        "as_of_date": "2026-11-21",
        "due_date": "2027-01-21",
        "policy": {"spend_limit": "5000.00", "require_vat": False, "sla_days": 30},
    })
    violations = result["violations"]
    assert isinstance(violations, list)
    assert "sla_window_exceeded" in violations

    with pytest.raises(ValidationError):
        PolicyComplianceRequest.model_validate({
            "tenantId": "tenant-a",
            "amount": 100.1,
            "policy": {"spend_limit": "500.00"},
        })


@pytest.mark.asyncio
async def test_in_memory_store_write_filter_and_cursor_pagination() -> None:
    store = InMemoryAuditStore()

    for index in range(4):
        await store.write({
            "tenantId": "tenant-a" if index < 3 else "tenant-b",
            "tool_name": "validate_invoice_math" if index % 2 == 0 else "evaluate_policy_compliance",
            "trace_id": f"trace-{index}",
        })

    records, cursor = await store.query("tenant-a", None, 2, None)
    assert len(records) == 2
    assert cursor is not None

    second, next_cursor = await store.query("tenant-a", None, 2, cursor)
    assert len(second) == 1
    assert next_cursor is None

    filtered, filtered_cursor = await store.query(
        "tenant-a", "validate_invoice_math", 10, None
    )
    assert filtered_cursor is None
    assert len(filtered) == 2


@pytest.mark.asyncio
async def test_in_memory_store_rejects_invalid_cursor() -> None:
    store = InMemoryAuditStore()
    records, cursor = await store.query("tenant-a", None, 20, "not-base64")
    assert records == []
    assert cursor is None


@pytest.mark.asyncio
async def test_query_audit_trail_schema_and_pagination() -> None:
    store = InMemoryAuditStore()
    await store.write({
        "tenantId": "tenant-a",
        "tool_name": "validate_invoice_math",
        "trace_id": "trace-1",
    })

    result = await query_audit_trail(
        {"tenantId": "tenant-a", "limit": 10}, store
    )

    assert result["count"] == 1
    assert result["tenant_id"] == "tenant-a"
    records = result["records"]
    assert isinstance(records, list)
    assert records[0]["trace_id"] == "trace-1"

    with pytest.raises(ValidationError):
        AuditTrailRequest.model_validate({"tenantId": "tenant-a", "limit": 101})


def test_cosmos_retry_succeeds_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    cosmos_store = object.__new__(CosmosAuditStore)
    cosmos_store._container = Mock()
    cosmos_store._container.upsert_item.side_effect = [RuntimeError("busy"), {"id": "ok"}]

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def fake_to_thread(function: object, *args: object) -> object:
        return function(*args)  # type: ignore[operator]

    monkeypatch.setattr("src.audit_store.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("src.audit_store.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("src.audit_store.secrets.SystemRandom.uniform", lambda _self, _minimum, _maximum: 0.0)

    asyncio.run(CosmosAuditStore.write(
        cosmos_store,
        {"trace_id": "trace-1", "tenantId": "tenant-a"},
    ))

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.1)


def test_cosmos_retry_exhaustion() -> None:
    cosmos_store = object.__new__(CosmosAuditStore)
    cosmos_store._container = Mock()
    cosmos_store._container.upsert_item.side_effect = RuntimeError("unavailable")

    async def run() -> None:
        await CosmosAuditStore.write(cosmos_store, {"trace_id": "trace-x", "tenantId": "tenant-a"})

    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(run())
