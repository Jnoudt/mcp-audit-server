"""Safe audit-trail querying."""

from __future__ import annotations

from src.audit_store import AuditStore
from src.schemas.models import AuditTrailRequest, AuditTrailResult


async def query_audit_trail(
    arguments: dict[str, object],
    audit_store: AuditStore,
) -> dict[str, object]:
    request = AuditTrailRequest.model_validate(arguments)
    records, next_cursor = await audit_store.query(
        tenant_id=request.tenantId,
        tool_name=request.tool_name,
        limit=request.limit,
        cursor=request.cursor,
    )

    result = AuditTrailResult(
        tenant_id=request.tenantId,
        records=records,
        next_cursor=next_cursor,
        count=len(records),
    )
    return result.model_dump(mode="json")
