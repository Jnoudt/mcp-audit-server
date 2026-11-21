"""Azure Functions entry point for the Remote MCP audit tool server."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

import azure.functions as func
from pydantic import ValidationError

sys.path.insert(0, ".")

from src.audit_store import create_audit_store
from src.schemas.models import (
    AuditRecord,
    ComplianceCheckRequest,
    ComplianceCheckResult,
    JSONRPCRequest,
    TaxCalculateRequest,
    TaxCalculateResult,
)
from src.tools.audit_trail import query_audit_trail
from src.tools.policy_check import evaluate_policy_compliance
from src.tools.reconcile import validate_invoice_math

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_AUDIT_STORE, _AUDIT_BACKEND = create_audit_store()
_LOGGER = logging.getLogger("mcp-audit-server")


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return value


def _structured_log(trace_id: str, event: str, **fields: Any) -> None:
    payload = {"trace_id": trace_id, "event": event, **_json_safe(fields)}
    _LOGGER.info(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))


def _redact_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "loc": [str(part) for part in detail.get("loc", ())],
            "type": detail.get("type", "validation_error"),
        }
        for detail in exc.errors(include_url=False)
    ]


def _safe_request_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    sensitive_names = {"secret", "password", "token", "api_key", "authorization", "cookie"}
    summary: dict[str, Any] = {}
    for key, value in list(arguments.items())[:20]:
        normalized = str(key).lower()
        if any(name in normalized for name in sensitive_names):
            summary[str(key)] = "[REDACTED]"
        elif isinstance(value, (str, int, float, bool, type(None))):
            summary[str(key)] = str(value)[:128]
        elif isinstance(value, (dict, list)):
            summary[str(key)] = {"type": type(value).__name__, "items": len(value)}
        else:
            summary[str(key)] = type(value).__name__
    return summary


def _rpc_error(request_id: Any, trace_id: str, error: MCPError) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": error.code,
            "message": error.message,
            "data": _json_safe(error.data),
            "trace_id": trace_id,
        },
    }


_TOOLS = [
    {
        "name": "validate_invoice_math",
        "description": "Deterministically reconcile invoice line items, tax, subtotal, and total.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tenantId", "invoice_id", "line_items", "reported_subtotal", "tax_rate", "reported_tax", "reported_total"],
            "properties": {
                "tenantId": {"type": "string", "minLength": 1, "maxLength": 128},
                "invoice_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "line_items": {"type": "array", "minItems": 1, "maxItems": 1000},
                "reported_subtotal": {"type": "string"},
                "tax_rate": {"type": "string"},
                "reported_tax": {"type": "string"},
                "reported_total": {"type": "string"},
            },
        },
    },
    {
        "name": "evaluate_policy_compliance",
        "description": "Evaluate deterministic spend, approval, VAT, and SLA policy rules.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tenantId", "amount", "policy"],
            "properties": {
                "tenantId": {"type": "string", "minLength": 1, "maxLength": 128},
                "amount": {"type": "string"},
                "policy": {"type": "object"},
            },
        },
    },
    {
        "name": "query_audit_trail",
        "description": "Query recent tenant audit records with optional tool filtering and pagination.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tenantId"],
            "properties": {
                "tenantId": {"type": "string", "minLength": 1, "maxLength": 128},
                "tool_name": {"type": "string", "minLength": 1, "maxLength": 128},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "cursor": {"type": "string", "maxLength": 4096},
            },
        },
    },
]


def _calculate_tax(arguments: dict[str, Any]) -> dict[str, Any]:
    request = TaxCalculateRequest.model_validate(arguments)
    subtotal = request.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax_amount = (subtotal * request.tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = (subtotal + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    result = TaxCalculateResult(
        subtotal=subtotal,
        tax_rate=request.tax_rate,
        tax_amount=tax_amount,
        total=total,
        jurisdiction=request.jurisdiction,
    )
    return {"content": [{"type": "json", "json": _json_safe(result)}], "isError": False}


def _check_compliance(arguments: dict[str, Any]) -> dict[str, Any]:
    request = ComplianceCheckRequest.model_validate(arguments)
    reasons: list[str] = []

    if request.currency != "USD":
        reasons.append("Only USD is currently accepted")
    if request.amount > Decimal("100000000.00"):
        reasons.append("Amount exceeds deterministic review threshold")

    result = ComplianceCheckResult(
        transaction_id=request.transaction_id,
        compliant=not reasons,
        reasons=reasons,
    )
    return {"content": [{"type": "json", "json": _json_safe(result)}], "isError": False}


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "validate_invoice_math":
        return validate_invoice_math(arguments)
    if name == "evaluate_policy_compliance":
        return evaluate_policy_compliance(arguments)
    if name == "query_audit_trail":
        return await query_audit_trail(arguments, _AUDIT_STORE)
    raise MCPError(-32602, "Unknown tool name", {"name": name})


async def _handle_rpc(payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
    try:
        request = JSONRPCRequest.model_validate(payload)
    except ValidationError as exc:
        raise MCPError(-32600, "Invalid JSON-RPC request", _redact_validation_errors(exc))

    if request.method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mcp-audit-server", "version": "0.1.0"},
            },
        }

    if request.method == "tools/list":
        return {"jsonrpc": "2.0", "id": request.id, "result": {"tools": _TOOLS}}

    if request.method == "tools/call":
        name = request.params.get("name")
        arguments = request.params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise MCPError(-32602, "Invalid tools/call parameters")

        try:
            started = time.perf_counter()
            result = await _call_tool(name, arguments)
            duration_ms = round((time.perf_counter() - started) * 1000)
            status: Literal["success", "error"] = "success"
            error_code = None
            tenant_id = str(arguments.get("tenantId", "unknown"))
            _structured_log(trace_id, "tool_call_success", tool=name, tenantId=tenant_id, duration_ms=duration_ms)
        except ValidationError as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            tenant_id = str(arguments.get("tenantId", "unknown"))
            error = MCPError(-32602, "Invalid tool arguments", _redact_validation_errors(exc))
            status = "error"
            error_code = error.code
            _structured_log(trace_id, "tool_call_validation_error", tool=name, tenantId=tenant_id, duration_ms=duration_ms, error=error.message)
            error_record = AuditRecord(
                trace_id=trace_id,
                tenantId=tenant_id,
                tool_name=name,
                method="tools/call",
                request_summary=_safe_request_summary(arguments),
                output_summary={"error": error.message},
                duration_ms=max(duration_ms, 0),
                status=status,
                error_code=error_code,
                timestamp=datetime.now(UTC).isoformat(),
            )
            await _AUDIT_STORE.write(_json_safe(error_record))
            raise error
        except MCPError as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            tenant_id = str(arguments.get("tenantId", "unknown"))
            status = "error"
            error_code = exc.code
            _structured_log(trace_id, "tool_call_error", tool=name, tenantId=tenant_id, duration_ms=duration_ms, error=exc.message)
            error_record = AuditRecord(
                trace_id=trace_id,
                tenantId=tenant_id,
                tool_name=name,
                method="tools/call",
                request_summary=_safe_request_summary(arguments),
                output_summary={"error": exc.message},
                duration_ms=max(duration_ms, 0),
                status=status,
                error_code=error_code,
                timestamp=datetime.now(UTC).isoformat(),
            )
            await _AUDIT_STORE.write(_json_safe(error_record))
            raise

        record = AuditRecord(
            trace_id=trace_id,
            tenantId=tenant_id,
            tool_name=name,
            method="tools/call",
            request_summary=_safe_request_summary(arguments),
            output_summary={"keys": sorted(result.keys())},
            duration_ms=max(duration_ms, 0),
            status=status,
            error_code=error_code,
            timestamp=datetime.now(UTC).isoformat(),
        )
        await _AUDIT_STORE.write(_json_safe(record))
        return {"jsonrpc": "2.0", "id": request.id, "result": result}

    raise MCPError(-32601, "Method not found", {"method": request.method})


@app.route(route="mcp", methods=["POST", "GET"])
async def mcp(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())

    if req.method == "GET":
        _structured_log(trace_id, "mcp_discovery", audit_backend=_AUDIT_BACKEND)
        return func.HttpResponse(
            json.dumps({"status": "ready", "audit_backend": _AUDIT_BACKEND}, separators=(",", ":")),
            status_code=200,
            mimetype="application/json",
            headers={"x-correlation-id": trace_id},
        )

    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            raise MCPError(-32600, "Invalid JSON-RPC request")
        response = await _handle_rpc(payload, trace_id)
        status_code = 200
    except MCPError as exc:
        response = _rpc_error(payload.get("id") if isinstance(payload, dict) else None, trace_id, exc)
        status_code = 200
        _structured_log(trace_id, "rpc_error", code=exc.code, message=exc.message)
    except Exception as exc:
        _structured_log(trace_id, "rpc_internal_error", error_type=type(exc).__name__)
        response = _rpc_error(None, trace_id, MCPError(-32603, "Internal error", {"trace_id": trace_id}))
        status_code = 500

    return func.HttpResponse(
        json.dumps(_json_safe(response), separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
        headers={"x-correlation-id": trace_id},
    )
