"""Audit persistence with an offline in-memory fallback."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import secrets
from threading import Lock
from typing import Any


class AuditStore:
    async def write(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    async def query(
        self,
        tenant_id: str,
        tool_name: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        raise NotImplementedError


class InMemoryAuditStore(AuditStore):
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._lock = Lock()

    async def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    async def query(
        self,
        tenant_id: str,
        tool_name: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        with self._lock:
            matching = [
                dict(record)
                for record in reversed(self._records)
                if record.get("tenantId") == tenant_id
                and (tool_name is None or record.get("tool_name") == tool_name)
            ]

        try:
            offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        except (ValueError, TypeError, binascii.Error):
            offset = -1
        if offset < 0:
            return [], None

        page = matching[offset:offset + limit]
        next_cursor = None
        if offset + limit < len(matching):
            next_cursor = base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        return page, next_cursor


class CosmosAuditStore(AuditStore):
    """Cosmos DB writer using DefaultAzureCredential and bounded retries."""

    def __init__(self, endpoint: str, database_name: str, container_name: str) -> None:
        from azure.cosmos import CosmosClient, PartitionKey
        from azure.identity import DefaultAzureCredential

        self._credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True
        )
        self._client = CosmosClient(endpoint, credential=self._credential)
        database = self._client.create_database_if_not_exists(id=database_name)
        self._container = database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path="/trace_id"),
        )

    async def write(self, record: dict[str, Any]) -> None:
        item = dict(record)
        item.setdefault("id", record["trace_id"])

        for attempt in range(5):
            try:
                await asyncio.to_thread(self._container.upsert_item, item)
                return
            except Exception:
                if attempt == 4:
                    raise
                delay = (2**attempt) * 0.1 + secrets.SystemRandom().uniform(0, 0.05)
                await asyncio.sleep(delay)

    async def query(
        self,
        tenant_id: str,
        tool_name: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        except (ValueError, TypeError):
            offset = -1
        if offset < 0:
            return [], None

        query = "SELECT * FROM c WHERE c.tenantId = @tenantId"
        parameters: list[dict[str, Any]] = [
            {"name": "@tenantId", "value": tenant_id}
        ]

        if tool_name:
            query += " AND c.tool_name = @toolName"
            parameters.append({"name": "@toolName", "value": tool_name})

        query += " ORDER BY c.timestamp DESC OFFSET @offset LIMIT @limit"
        parameters.extend([
            {"name": "@offset", "value": offset},
            {"name": "@limit", "value": limit + 1},
        ])

        items = await asyncio.to_thread(
            lambda: list(self._container.query_items(query=query, parameters=parameters)),
        )

        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            next_cursor = base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        return page, next_cursor


def create_audit_store() -> tuple[AuditStore, str]:
    endpoint = os.getenv("COSMOS_ENDPOINT")
    database_name = os.getenv("COSMOS_DATABASE", "mcp-audit")
    container_name = os.getenv("COSMOS_CONTAINER", "audit-records")

    if endpoint:
        return CosmosAuditStore(endpoint, database_name, container_name), "cosmos"
    return InMemoryAuditStore(), "memory"
