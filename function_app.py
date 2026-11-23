"""Azure Functions entry point for the Remote MCP audit tool server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from urllib.parse import unquote

import azure.functions as func
from pydantic import ValidationError

sys.path.insert(0, ".")

from src.ai_review import (
    AIReviewConfigurationError,
    AIReviewConsentError,
    AIReviewError,
    AIReviewProviderError,
    ai_review_status,
    request_ai_review,
)
from src.audit_store import create_audit_store
from src.demo_store import (
    DemoNotFoundError,
    DemoStore,
    DemoValidationError,
    get_demo_store,
)
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
_LOCAL_DEMO_AUTH_LEVEL = (
    func.AuthLevel.ANONYMOUS
    if (
        os.getenv("RECONFLOW_LOCAL_DEMO", "").casefold() == "true"
        and not os.getenv("WEBSITE_INSTANCE_ID")
    )
    or os.getenv("RECONFLOW_HOSTED_DEMO", "").casefold() == "true"
    else func.AuthLevel.FUNCTION
)


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
    except ValueError as exc:
        _structured_log(trace_id, "rpc_parse_error", error_type=type(exc).__name__)
        response = _rpc_error(None, trace_id, MCPError(-32700, "Parse error"))
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


def _demo_response(
    payload: dict[str, Any],
    status_code: int = 200,
    trace_id: str | None = None,
) -> func.HttpResponse:
    headers = {"cache-control": "no-store"}
    if trace_id:
        headers["x-correlation-id"] = trace_id
    return func.HttpResponse(
        json.dumps(_json_safe(payload), separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
        headers=headers,
    )


def _local_demo_store() -> DemoStore:
    local_demo = (
        os.getenv("RECONFLOW_LOCAL_DEMO", "").casefold() == "true"
        and not os.getenv("WEBSITE_INSTANCE_ID")
    )
    hosted_demo = (
        os.getenv("RECONFLOW_HOSTED_DEMO", "").casefold() == "true"
    )
    if not (local_demo or hosted_demo):
        raise DemoValidationError("The ReconFlow guest demo is unavailable.")
    return get_demo_store()


def _demo_error(exc: Exception, trace_id: str) -> func.HttpResponse:
    if isinstance(exc, DemoNotFoundError):
        return _demo_response({"error": str(exc)}, 404, trace_id)
    if isinstance(exc, (DemoValidationError, ValueError)):
        return _demo_response({"error": str(exc)}, 400, trace_id)
    if isinstance(exc, AIReviewConfigurationError):
        return _demo_response({"error": str(exc)}, 409, trace_id)
    if isinstance(exc, AIReviewConsentError):
        return _demo_response({"error": str(exc)}, 400, trace_id)
    if isinstance(exc, AIReviewProviderError):
        cause = exc.__cause__
        provider_status = getattr(cause, "status_code", None)
        if not isinstance(provider_status, int):
            provider_status = None
        _structured_log(
            trace_id,
            "demo_ai_provider_error",
            error_type=type(exc).__name__,
            reason_code=exc.reason_code,
            cause_type=type(cause).__name__ if cause else None,
            provider_status=provider_status,
            finish_reason=exc.finish_reason,
            prompt_tokens=exc.prompt_tokens,
            completion_tokens=exc.completion_tokens,
        )
        if provider_status == 429:
            return _demo_response(
                {"error": "The Foundry model deployment is rate-limited. Retry after a short wait."},
                429,
                trace_id,
            )
        return _demo_response({"error": str(exc)}, 502, trace_id)
    if isinstance(exc, AIReviewError):
        return _demo_response({"error": str(exc)}, 400, trace_id)
    _structured_log(trace_id, "demo_request_error", error_type=type(exc).__name__)
    return _demo_response(
        {"error": "The local demo request could not be completed.", "trace_id": trace_id},
        500,
        trace_id,
    )


@app.route(
    route="demo/status",
    methods=["GET"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_status(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    local_demo = (
        os.getenv("RECONFLOW_LOCAL_DEMO", "").casefold() == "true"
        and not os.getenv("WEBSITE_INSTANCE_ID")
    )
    hosted_demo = (
        os.getenv("RECONFLOW_HOSTED_DEMO", "").casefold() == "true"
    )
    if not (local_demo or hosted_demo):
        return _demo_response({"error": "The ReconFlow guest demo is unavailable."}, 404, trace_id)
    return _demo_response(
        {"enabled": True, "ai": ai_review_status(), "storage": "local SQLite + local files"},
        trace_id=trace_id,
    )


@app.route(
    route="demo/requests",
    methods=["GET"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_list_requests(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        store = _local_demo_store()
        result = await asyncio.to_thread(store.list_requests)
        return _demo_response({"requests": result}, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/sample-files",
    methods=["GET"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_sample_files(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        service_id = req.params.get("serviceId", "")
        store = _local_demo_store()
        samples = await asyncio.to_thread(store.list_sample_files, service_id)
        return _demo_response({"samples": samples}, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_create_request(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        payload = req.get_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("serviceId"), str):
            raise DemoValidationError("Provide a supported serviceId.")
        store = _local_demo_store()
        result = await asyncio.to_thread(store.create_request, payload["serviceId"])
        return _demo_response(result, 201, trace_id)
    except ValueError as exc:
        return _demo_error(exc, trace_id)
    except (DemoNotFoundError, DemoValidationError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}",
    methods=["GET"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_get_request(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        store = _local_demo_store()
        result = await asyncio.to_thread(store.get_request, req.route_params["request_id"])
        return _demo_response(result, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/assessment",
    methods=["PUT"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_save_assessment(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            raise DemoValidationError("Assessment answers must be a JSON object.")
        store = _local_demo_store()
        result = await asyncio.to_thread(
            store.save_assessment,
            req.route_params["request_id"],
            payload,
        )
        return _demo_response(result, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/uploads",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_upload_csv(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        file_name = unquote(req.headers.get("x-file-name", ""))
        source_system = req.headers.get("x-source-system", "Unspecified")
        content = req.get_body()
        store = _local_demo_store()
        result = await asyncio.to_thread(
            store.upload_csv,
            req.route_params["request_id"],
            file_name,
            content,
            source_system,
        )
        return _demo_response(result, 201, trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/samples",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_upload_sample(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        payload = req.get_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("sampleId"), str):
            raise DemoValidationError("Provide a sampleId from the test-pack file list.")
        store = _local_demo_store()
        result = await asyncio.to_thread(
            store.upload_sample,
            req.route_params["request_id"],
            payload["sampleId"],
        )
        return _demo_response(result, 201, trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/runs",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_run_audit(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        store = _local_demo_store()
        result = await asyncio.to_thread(store.run_audit, req.route_params["request_id"])
        return _demo_response(result, 201, trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/runs/{run_id}/findings/{finding_id}/disposition",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_save_disposition(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            raise DemoValidationError("Disposition must be a JSON object.")
        store = _local_demo_store()
        result = await asyncio.to_thread(
            store.save_disposition,
            req.route_params["request_id"],
            req.route_params["run_id"],
            req.route_params["finding_id"],
            payload.get("disposition", ""),
            payload.get("note", ""),
        )
        return _demo_response(result, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)


@app.route(
    route="demo/requests/{request_id}/ai-review",
    methods=["POST"],
    auth_level=_LOCAL_DEMO_AUTH_LEVEL,
)
async def demo_ai_review(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = req.headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            raise DemoValidationError("AI review request must be a JSON object.")
        question = payload.get("question")
        if not isinstance(question, str):
            raise DemoValidationError("Provide a question for the AI reviewer.")
        store = _local_demo_store()
        request_record = await asyncio.to_thread(
            store.get_request,
            req.route_params["request_id"],
        )
        latest_run = request_record.get("latestRun")
        if not isinstance(latest_run, dict):
            raise DemoValidationError("Run the deterministic audit before requesting AI review.")
        context = await asyncio.to_thread(
            store.get_ai_context,
            req.route_params["request_id"],
            latest_run["id"],
        )
        history = context.pop("conversation", [])
        ai_result = await asyncio.to_thread(
            request_ai_review,
            question,
            context,
            confirmed_send=payload.get("confirmSend") is True,
            history=history,
        )
        result = await asyncio.to_thread(
            store.record_ai_exchange,
            req.route_params["request_id"],
            latest_run["id"],
            question,
            ai_result.answer,
            ai_result.model_deployment,
            ai_result.prompt_tokens,
            ai_result.completion_tokens,
        )
        return _demo_response(result, trace_id=trace_id)
    except (DemoNotFoundError, DemoValidationError, ValueError) as exc:
        return _demo_error(exc, trace_id)
    except AIReviewError as exc:
        return _demo_error(exc, trace_id)
