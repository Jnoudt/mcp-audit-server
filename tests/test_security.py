from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import function_app
from src.audit_store import InMemoryAuditStore
from src.schemas.models import (
    AuditTrailRequest,
    InvoiceReconciliationRequest,
    JSONRPCRequest,
    PolicyComplianceRequest,
)
from src.tools.audit_trail import query_audit_trail
from src.tools.policy_check import evaluate_policy_compliance
from src.tools.reconcile import validate_invoice_math

SECRET_MARKERS = (
    "secret",
    "password",
    "authorization",
    "api-key",
    "cookie",
    "traceback",
    "C:\\Projects",
)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "NaN"),
        ("quantity", "Infinity"),
        ("quantity", "-1"),
        ("quantity", 1.25),
        ("unit_price", True),
    ],
)
def test_numeric_tampering_is_rejected(field: str, value: object) -> None:
    line_item: dict[str, object] = {"quantity": "1", "unit_price": "1.00"}
    line_item[field] = value

    with pytest.raises(ValidationError) as exc_info:
        validate_invoice_math({
            "tenantId": "tenant-a",
            "invoice_id": "INV-SEC",
            "line_items": [line_item],
            "reported_subtotal": "1.00",
            "tax_rate": "0.10",
            "reported_tax": "0.10",
            "reported_total": "1.10",
        })

    redacted = function_app._redact_validation_errors(exc_info.value)
    serialized = json.dumps(redacted)
    assert "C:\\Projects" not in serialized
    assert "Traceback" not in serialized


def test_oversized_invoice_payload_is_rejected() -> None:
    oversized_items = [
        {"description": "x" * 257, "quantity": "1", "unit_price": "1.00"}
        for _ in range(1001)
    ]

    with pytest.raises(ValidationError):
        InvoiceReconciliationRequest.model_validate({
            "tenantId": "tenant-a",
            "invoice_id": "INV-LARGE",
            "line_items": oversized_items,
            "reported_subtotal": "1001.00",
            "tax_rate": "0.10",
            "reported_tax": "100.10",
            "reported_total": "1101.10",
        })


@pytest.mark.parametrize(
    "tenant_id",
    ["", "x" * 129, "tenant-a<script>", "tenant-a\\nforged"],
)
def test_hostile_tenant_identifiers_are_rejected(tenant_id: str) -> None:
    with pytest.raises(ValidationError):
        AuditTrailRequest.model_validate({
            "tenantId": tenant_id,
            "limit": 20,
        })


def test_unknown_json_rpc_fields_and_methods_are_rejected() -> None:
    with pytest.raises(ValidationError):
        JSONRPCRequest.model_validate({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {},
            "password": "super-secret",
        })


@pytest.mark.asyncio
async def test_cross_tenant_audit_query_returns_no_other_tenant_records() -> None:
    store = InMemoryAuditStore()
    await store.write({
        "tenantId": "tenant-a",
        "tool_name": "validate_invoice_math",
        "trace_id": "trace-a",
    })
    await store.write({
        "tenantId": "tenant-b",
        "tool_name": "validate_invoice_math",
        "trace_id": "trace-b",
        "authorization": "Bearer secret-token",
    })

    result = await query_audit_trail({"tenantId": "tenant-a", "limit": 100}, store)

    assert result["count"] == 1
    records = result["records"]
    assert isinstance(records, list)
    assert records[0]["tenantId"] == "tenant-a"
    assert all(record["tenantId"] != "tenant-b" for record in records)


@pytest.mark.asyncio
async def test_invalid_cursor_is_tenant_safe_and_bounded() -> None:
    store = InMemoryAuditStore()
    result = await query_audit_trail({
        "tenantId": "tenant-a",
        "limit": 100,
        "cursor": "../../secret-token",
    }, store)

    assert result["count"] == 0
    assert result["next_cursor"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"tenantId": "tenant-a", "amount": "Infinity", "policy": {"spend_limit": "100"}},
        {"tenantId": "tenant-a", "amount": True, "policy": {"spend_limit": "100"}},
        {"tenantId": "tenant-a", "amount": 12.5, "policy": {"spend_limit": "100"}},
        {"tenantId": "tenant-a", "amount": "100", "policy": {"spend_limit": "NaN"}},
    ],
)
def test_policy_payload_tampering_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PolicyComplianceRequest.model_validate(payload)


def test_hostile_strings_do_not_change_policy_outcome() -> None:
    with pytest.raises(ValidationError):
        evaluate_policy_compliance({
            "tenantId": "tenant-a<script>",
            "amount": "100.00",
            "approval_tier": "manager\n<script>",
            "policy": {"spend_limit": "500.00"},
        })


def test_sensitive_request_summary_is_redacted() -> None:
    summary = function_app._safe_request_summary({
        "tenantId": "tenant-a",
        "authorization": "Bearer super-secret",
        "api_key": "key-secret",
        "amount": "100.00",
        "line_items": [{"secret": "nested"}],
    })

    assert summary["authorization"] == "[REDACTED]"
    assert summary["api_key"] == "[REDACTED]"
    assert summary["line_items"] == {"type": "list", "items": 1}


def test_validation_error_data_is_redacted() -> None:
    try:
        InvoiceReconciliationRequest.model_validate({
            "tenantId": "tenant-a",
            "invoice_id": "INV-SECRET",
            "line_items": [],
            "reported_subtotal": "secret-value",
            "tax_rate": "0.10",
            "reported_tax": "0.10",
            "reported_total": "1.10",
        })
    except ValidationError as exc:
        redacted = function_app._redact_validation_errors(exc)
    else:
        pytest.fail("Expected validation failure")

    serialized = json.dumps(redacted)
    for marker in SECRET_MARKERS:
        assert marker.lower() not in serialized.lower()


def test_mcp_error_contains_no_internal_details() -> None:
    error = function_app.MCPError(
        -32603,
        "Internal error",
        {"trace_id": "trace-a"},
    )
    response = function_app._rpc_error(1, "trace-a", error)

    serialized = json.dumps(response)
    assert "Traceback" not in serialized
    assert "C:\\Projects" not in serialized
    assert "password" not in serialized.lower()
    assert response["error"]["trace_id"] == "trace-a"
