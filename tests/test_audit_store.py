from __future__ import annotations

from typing import Any

import pytest

from src import audit_store


@pytest.mark.parametrize(
    ("settings", "expected_database", "expected_container"),
    [
        (
            {
                "COSMOS_DATABASE_NAME": "infra-db",
                "COSMOS_CONTAINER_NAME": "infra-container",
                "COSMOS_DATABASE": "legacy-db",
                "COSMOS_CONTAINER": "legacy-container",
            },
            "infra-db",
            "infra-container",
        ),
        (
            {
                "COSMOS_DATABASE": "legacy-db",
                "COSMOS_CONTAINER": "legacy-container",
            },
            "legacy-db",
            "legacy-container",
        ),
    ],
)
def test_create_audit_store_uses_infra_settings_with_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, str],
    expected_database: str,
    expected_container: str,
) -> None:
    for name in (
        "COSMOS_ENDPOINT",
        "COSMOS_DATABASE_NAME",
        "COSMOS_CONTAINER_NAME",
        "COSMOS_DATABASE",
        "COSMOS_CONTAINER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://example.documents.azure.com:443/")
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    captured: dict[str, str] = {}

    def fake_cosmos_store(
        endpoint: str,
        database_name: str,
        container_name: str,
    ) -> object:
        captured.update(
            endpoint=endpoint,
            database_name=database_name,
            container_name=container_name,
        )
        return object()

    monkeypatch.setattr(audit_store, "CosmosAuditStore", fake_cosmos_store)

    store, backend = audit_store.create_audit_store()

    assert backend == "cosmos"
    assert store is not None
    assert captured["database_name"] == expected_database
    assert captured["container_name"] == expected_container


@pytest.mark.asyncio
async def test_cosmos_audit_store_routes_queries_to_tenant_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from azure import cosmos, identity

    captured: dict[str, Any] = {}

    class FakeContainer:
        def query_items(self, **kwargs: Any) -> list[dict[str, str]]:
            captured["query_args"] = kwargs
            return []

    class FakeDatabase:
        def create_container_if_not_exists(self, **kwargs: Any) -> object:
            captured.update(kwargs)
            return FakeContainer()

    class FakeCosmosClient:
        def __init__(self, endpoint: str, credential: object) -> None:
            captured["endpoint"] = endpoint
            captured["credential"] = credential

        def create_database_if_not_exists(self, id: str) -> FakeDatabase:
            captured["database_id"] = id
            return FakeDatabase()

    monkeypatch.setattr(cosmos, "CosmosClient", FakeCosmosClient)
    monkeypatch.setattr(cosmos, "PartitionKey", lambda path: path)
    monkeypatch.setattr(
        identity,
        "DefaultAzureCredential",
        lambda **kwargs: object(),
    )

    store = audit_store.CosmosAuditStore(
        "https://example.documents.azure.com:443/",
        "audit-db",
        "audit-events",
    )
    await store.query("tenant-a", None, 10, None)

    assert captured["partition_key"] == "/tenantId"
    assert captured["query_args"]["partition_key"] == "tenant-a"
