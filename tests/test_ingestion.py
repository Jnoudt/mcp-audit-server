from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError

from src.ingestion.dataframe_loader import CSVInputError, load_csv_dataframe
from src.ingestion.ledger_import import import_ledger_dataframe
from src.ingestion.ledger_types import LedgerType, identify_ledger_type
from src.ingestion.schema_builder import (
    create_schema,
    documents,
    ledger_imports,
    ledger_tables,
    requests,
    source_columns,
    tenants,
    users,
)
from src.ingestion.type_detection import DataKind, profile_dataframe

PACK_ROOT = (
    Path(__file__).parents[1]
    / "sample_data"
    / "Enterprise_ERP_Ledgers_and_Audit_CAATs_Pack"
)


def _sqlite_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _seed_owner_graph(engine):
    create_schema(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(tenants.insert(), {"tenant_id": "tenant-1", "created_at": now})
        connection.execute(
            users.insert(),
            {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "email": "auditor@example.test",
                "display_name": "Test Auditor",
                "created_at": now,
            },
        )
        connection.execute(
            requests.insert(),
            {
                "tenant_id": "tenant-1",
                "request_id": "request-1",
                "owner_user_id": "user-1",
                "service_id": "caats-ledger-analytics",
                "status": "in_progress",
                "created_at": now,
                "modified_at": now,
            },
        )
        connection.execute(
            documents.insert(),
            {
                "tenant_id": "tenant-1",
                "document_id": "document-1",
                "request_id": "request-1",
                "owner_user_id": "user-1",
                "blob_name": "tenant-1/user-1/document-1",
                "original_file_name": "ledger.csv",
                "content_type": "text/csv",
                "content_sha256": "a" * 64,
                "size_bytes": 100,
                "created_at": now,
                "modified_at": now,
            },
        )


def test_all_sample_csv_files_are_rectangular_and_recognized():
    ledger_files = sorted((PACK_ROOT / "ledgers").glob("*/*.csv"))
    audit_files = sorted((PACK_ROOT / "audit_examples").glob("*.csv"))
    manifest = PACK_ROOT / "DATASET_MANIFEST_AND_SCHEMA_GUIDE.csv"

    assert len(ledger_files) == 36
    assert len(audit_files) == 4
    assert load_csv_dataframe(manifest).shape == (36, 5)

    for path in ledger_files:
        frame = load_csv_dataframe(path)
        assert len(frame.index) == 1050, path.name
        assert identify_ledger_type(frame.columns) in set(LedgerType), path.name
        tags = [profile for profile in profile_dataframe(frame) if profile.kind is DataKind.GROUND_TRUTH]
        assert tags and all(not profile.analysis_allowed for profile in tags), path.name

    for path in audit_files:
        frame = load_csv_dataframe(path)
        assert frame.shape == (3, 7), path.name
        profiles = profile_dataframe(frame)
        assert any(
            profile.name == "Injected_Anomaly_Flag"
            and profile.kind is DataKind.GROUND_TRUTH
            and not profile.analysis_allowed
            for profile in profiles
        )


def test_all_sample_ledgers_import_to_their_domain_tables():
    engine = _sqlite_engine()
    create_schema(engine)
    now = datetime.now(UTC)
    ledger_files = sorted((PACK_ROOT / "ledgers").glob("*/*.csv"))
    with engine.begin() as connection:
        connection.execute(tenants.insert(), {"tenant_id": "tenant-1", "created_at": now})
        connection.execute(
            users.insert(),
            {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "email": "auditor@example.test",
                "display_name": "Test Auditor",
                "created_at": now,
            },
        )
        for index, path in enumerate(ledger_files, start=1):
            request_id = f"request-{index}"
            document_id = f"document-{index}"
            connection.execute(
                requests.insert(),
                {
                    "tenant_id": "tenant-1",
                    "request_id": request_id,
                    "owner_user_id": "user-1",
                    "service_id": "caats-ledger-analytics",
                    "status": "in_progress",
                    "created_at": now,
                    "modified_at": now,
                },
            )
            connection.execute(
                documents.insert(),
                {
                    "tenant_id": "tenant-1",
                    "document_id": document_id,
                    "request_id": request_id,
                    "owner_user_id": "user-1",
                    "blob_name": f"tenant-1/user-1/{document_id}",
                    "original_file_name": path.name,
                    "content_type": "text/csv",
                    "content_sha256": "b" * 64,
                    "size_bytes": path.stat().st_size,
                    "created_at": now,
                    "modified_at": now,
                },
            )

    for index, path in enumerate(ledger_files, start=1):
        frame = load_csv_dataframe(path)
        import_ledger_dataframe(
            engine,
            frame,
            tenant_id="tenant-1",
            owner_user_id="user-1",
            request_id=f"request-{index}",
            document_id=f"document-{index}",
            source_system=path.parent.name,
        )

    with engine.connect() as connection:
        counts = {
            ledger_type: connection.execute(
                select(func.count()).select_from(ledger_tables[ledger_type]).where(
                    ledger_tables[ledger_type].c.tenant_id == "tenant-1"
                )
            ).scalar_one()
            for ledger_type in LedgerType
        }
        source_count = connection.execute(select(source_columns)).all()

    assert sum(counts.values()) == 36 * 1050
    assert len(source_count) > 0


def test_loader_rejects_duplicate_headers_and_ragged_rows():
    with pytest.raises(CSVInputError, match="duplicate headers"):
        load_csv_dataframe(b"Account, account\n1,2\n")
    with pytest.raises(CSVInputError, match="expected 2"):
        load_csv_dataframe(b"Account,Amount\n100,10.00,extra\n")
    with pytest.raises(CSVInputError, match="maximum size"):
        load_csv_dataframe(b"Account,Amount\n1,2\n", max_bytes=8)


def test_type_inference_preserves_ids_and_marks_ground_truth():
    frame = pd.DataFrame(
        {
            "Account_Num": ["00123", "00456"],
            "HKTID": ["00123456789", "00987654321"],
            "Invoice_Date": ["2026-01-02", "2026-02-03"],
            "Amount": ["100.20", "0.01"],
            "GJAHR": ["2026", "2027"],
            "AuditTag": ["CLEAN", "ANOMALY:TEST"],
        },
        dtype="string",
    )
    profiles = {profile.name: profile for profile in profile_dataframe(frame)}

    assert profiles["Account_Num"].kind is DataKind.TEXT
    assert profiles["HKTID"].kind is DataKind.TEXT
    assert profiles["Invoice_Date"].kind is DataKind.DATE
    assert profiles["Amount"].kind is DataKind.DECIMAL
    assert profiles["GJAHR"].kind is DataKind.INTEGER
    assert profiles["AuditTag"].kind is DataKind.GROUND_TRUTH
    assert profiles["AuditTag"].analysis_allowed is False


def test_dataframe_import_persists_canonical_rows_and_schema_under_owner_fks():
    engine = _sqlite_engine()
    _seed_owner_graph(engine)
    source = PACK_ROOT / "ledgers" / "01_SAP_S4HANA" / "03_Accounts_Payable_Ledger.csv"
    frame = load_csv_dataframe(source).head(3)

    result = import_ledger_dataframe(
        engine,
        frame,
        tenant_id="tenant-1",
        owner_user_id="user-1",
        request_id="request-1",
        document_id="document-1",
        source_system="SAP S/4HANA",
    )

    assert result.ledger_type is LedgerType.ACCOUNTS_PAYABLE
    assert result.row_count == 3
    with engine.connect() as connection:
        imported = connection.execute(
            select(ledger_tables[LedgerType.ACCOUNTS_PAYABLE]).where(
                ledger_tables[LedgerType.ACCOUNTS_PAYABLE].c.import_id == result.import_id
            )
        ).mappings().all()
        import_record = connection.execute(
            select(ledger_imports).where(ledger_imports.c.import_id == result.import_id)
        ).mappings().one()
        schema_rows = connection.execute(
            select(source_columns).where(source_columns.c.import_id == result.import_id)
        ).mappings().all()

    assert len(imported) == 3
    assert import_record["row_count"] == 3
    assert imported[0]["amount"] is not None
    assert imported[0]["owner_user_id"] == "user-1"
    assert all("Audit_Tag" not in json.loads(row["source_payload_json"]) for row in imported)
    assert any(row["inferred_type"] == "ground_truth_only" for row in schema_rows)
    assert all(row["tenant_id"] == "tenant-1" for row in imported)


def test_import_rejects_a_different_owner_from_the_document_owner():
    engine = _sqlite_engine()
    _seed_owner_graph(engine)
    frame = load_csv_dataframe(
        PACK_ROOT / "ledgers" / "01_SAP_S4HANA" / "01_General_Ledger.csv"
    ).head(1)

    with pytest.raises(IntegrityError):
        import_ledger_dataframe(
            engine,
            frame,
            tenant_id="tenant-1",
            owner_user_id="different-user",
            request_id="request-1",
            document_id="document-1",
            source_system="SAP S/4HANA",
        )

    with engine.connect() as connection:
        assert connection.execute(select(ledger_imports)).first() is None
