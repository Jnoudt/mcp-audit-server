from __future__ import annotations

import json

import azure.functions as func
import pytest

import function_app
from src.audit_store import InMemoryAuditStore


@pytest.fixture
def api_store(monkeypatch: pytest.MonkeyPatch) -> InMemoryAuditStore:
    store = InMemoryAuditStore()
    monkeypatch.setattr(function_app, "_AUDIT_STORE", store)
    return store


def _request(
    method: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> func.HttpRequest:
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/mcp",
        headers=headers or {},
        params={},
        route_params={},
        body=body,
    )


def _response_json(response: func.HttpResponse) -> dict[str, object]:
    result = json.loads(response.get_body())
    assert isinstance(result, dict)
    return result


@pytest.mark.asyncio
async def test_mcp_get_discovery_returns_ready_and_correlation_id() -> None:
    response = await function_app.mcp(
        _request("GET", headers={"x-correlation-id": "trace-discovery"})
    )
    payload = _response_json(response)

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert response.headers["x-correlation-id"] == "trace-discovery"


@pytest.mark.asyncio
async def test_mcp_tools_list_exposes_registered_tools() -> None:
    request = _request(
        "POST",
        json.dumps({
            "jsonrpc": "2.0",
            "id": "list-tools",
            "method": "tools/list",
            "params": {},
        }).encode(),
    )

    response = await function_app.mcp(request)
    payload = _response_json(response)
    result = payload["result"]
    assert isinstance(result, dict)

    assert response.status_code == 200
    assert {tool["name"] for tool in result["tools"]} == {
        "validate_invoice_math",
        "evaluate_policy_compliance",
        "query_audit_trail",
    }


@pytest.mark.asyncio
async def test_mcp_initialize_returns_protocol_and_server_info() -> None:
    request = _request(
        "POST",
        json.dumps({
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {},
        }).encode(),
    )

    response = await function_app.mcp(request)
    payload = _response_json(response)
    result = payload["result"]
    assert isinstance(result, dict)

    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == "mcp-audit-server"


@pytest.mark.asyncio
async def test_mcp_tool_call_returns_result_and_writes_audit_record(
    api_store: InMemoryAuditStore,
) -> None:
    request = _request(
        "POST",
        json.dumps({
            "jsonrpc": "2.0",
            "id": "call-reconcile",
            "method": "tools/call",
            "params": {
                "name": "validate_invoice_math",
                "arguments": {
                    "tenantId": "tenant-api",
                    "invoice_id": "INV-API-1",
                    "line_items": [{"quantity": "2", "unit_price": "10.00"}],
                    "reported_subtotal": "20.00",
                    "tax_rate": "0.10",
                    "reported_tax": "2.00",
                    "reported_total": "22.00",
                },
            },
        }).encode(),
        headers={"x-correlation-id": "trace-reconcile"},
    )

    response = await function_app.mcp(request)
    payload = _response_json(response)
    result = payload["result"]
    assert isinstance(result, dict)

    assert response.status_code == 200
    assert result["pass_reconciliation"] is True
    records, cursor = await api_store.query("tenant-api", None, 10, None)
    assert cursor is None
    assert len(records) == 1
    assert records[0]["trace_id"] == "trace-reconcile"


@pytest.mark.asyncio
async def test_mcp_policy_tool_call_executes_policy_rules() -> None:
    request = _request(
        "POST",
        json.dumps({
            "jsonrpc": "2.0",
            "id": "call-policy",
            "method": "tools/call",
            "params": {
                "name": "evaluate_policy_compliance",
                "arguments": {
                    "tenantId": "tenant-api",
                    "amount": "500.00",
                    "currency": "USD",
                    "approval_tier": "none",
                    "vat_registered": True,
                    "as_of_date": "2026-11-21",
                    "due_date": "2026-12-01",
                    "policy": {
                        "spend_limit": "1000.00",
                        "require_vat": True,
                        "sla_days": 30,
                    },
                },
            },
        }).encode(),
    )

    response = await function_app.mcp(request)
    payload = _response_json(response)
    result = payload["result"]
    assert isinstance(result, dict)

    assert result["compliant"] is True
    assert result["violations"] == []


@pytest.mark.asyncio
async def test_mcp_audit_tool_call_queries_tenant_records(
    api_store: InMemoryAuditStore,
) -> None:
    await api_store.write({
        "tenantId": "tenant-api",
        "trace_id": "trace-existing",
        "tool_name": "validate_invoice_math",
        "method": "tools/call",
        "request_summary": {},
        "output_summary": {},
        "duration_ms": 1,
        "status": "success",
    })
    request = _request(
        "POST",
        json.dumps({
            "jsonrpc": "2.0",
            "id": "call-audit",
            "method": "tools/call",
            "params": {
                "name": "query_audit_trail",
                "arguments": {"tenantId": "tenant-api", "limit": 10},
            },
        }).encode(),
    )

    response = await function_app.mcp(request)
    payload = _response_json(response)
    result = payload["result"]
    assert isinstance(result, dict)
    records = result["records"]
    assert isinstance(records, list)

    assert result["count"] == 1
    assert records[0]["trace_id"] == "trace-existing"


@pytest.mark.asyncio
async def test_mcp_malformed_json_returns_json_rpc_parse_error() -> None:
    response = await function_app.mcp(_request("POST", b"{"))
    payload = _response_json(response)
    error = payload["error"]
    assert isinstance(error, dict)

    assert response.status_code == 200
    assert error["code"] == -32700
    assert error["message"] == "Parse error"
