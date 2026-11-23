"""Local-only persistence for the ReconFlow ledger audit demonstration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.engine import Connection, Engine

from src.caats_engine import (
    RULE_VERSION,
    SERVICE_LEDGER_TYPES,
    analyze_sources,
    count_rows_in_scope,
    summarize_findings,
)
from src.ingestion.dataframe_loader import load_csv_dataframe
from src.ingestion.ledger_import import import_ledger_dataframe
from src.ingestion.ledger_types import LedgerType, identify_ledger_type
from src.ingestion.schema_builder import (
    ai_conversations,
    ai_message_findings,
    ai_messages,
    assessment_answers,
    audit_findings,
    audit_runs,
    create_schema,
    documents,
    finding_dispositions,
    ledger_imports,
    ledger_tables,
    requests,
    source_columns,
    tenants,
    users,
)

LOCAL_TENANT_ID = "tenant-local-demo"
LOCAL_USER_ID = "user-local-auditor"
MAX_REQUEST_ROWS = 250_000
MAX_DOCUMENTS_PER_REQUEST = 24
MAX_REQUEST_BYTES = 100 * 1024 * 1024
MAX_QUESTION_LENGTH = 2_000
MAX_AI_FINDING_SAMPLES = 2
MAX_AI_FINDING_TEXT_LENGTH = 120
ALLOWED_DISPOSITIONS = {"accepted", "rejected", "needs_follow_up"}
_SAFE_FILE_NAME = re.compile(r"^[^<>:\"|?*\x00-\x1f]{1,255}\.csv$", re.IGNORECASE)
_VALID_ERP_NAMES = {
    "Unspecified",
    "SAP S/4HANA",
    "Oracle NetSuite",
    "Xero",
    "Sage Intacct",
    "Microsoft Dynamics 365",
    "QuickBooks Online",
}
_SAMPLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "sample_data"
    / "Enterprise_ERP_Ledgers_and_Audit_CAATs_Pack"
    / "ledgers"
)
_ERP_FOLDER_NAMES = {
    "01_SAP_S4HANA": "SAP S/4HANA",
    "02_Oracle_NetSuite": "Oracle NetSuite",
    "03_Xero_Cloud": "Xero",
    "04_Sage_Intacct": "Sage Intacct",
    "05_Microsoft_Dynamics_365": "Microsoft Dynamics 365",
    "06_QuickBooks_Online": "QuickBooks Online",
}


class DemoNotFoundError(LookupError):
    """Raised when a local demo request or finding does not exist."""


class DemoValidationError(ValueError):
    """Raised for invalid local demo inputs."""


class DemoStore:
    def __init__(
        self,
        engine: Engine | None = None,
        storage_root: Path | None = None,
    ) -> None:
        if engine is None:
            db_path = Path(
                os.getenv("RECONFLOW_LOCAL_DB_PATH", ".local/reconflow-demo.sqlite3")
            ).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{db_path.as_posix()}",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            self._configure_sqlite(engine)
        self.engine = engine
        self.storage_root = (
            storage_root
            or Path(os.getenv("RECONFLOW_LOCAL_STORAGE_DIR", ".local/uploads")).resolve()
        )
        self.storage_root.mkdir(parents=True, exist_ok=True)
        create_schema(self.engine)
        self._seed_local_user()

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    def _seed_local_user(self) -> None:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            if connection.execute(
                select(tenants.c.tenant_id).where(tenants.c.tenant_id == LOCAL_TENANT_ID)
            ).first() is None:
                connection.execute(tenants.insert().values(tenant_id=LOCAL_TENANT_ID, created_at=now))
            if connection.execute(
                select(users.c.user_id).where(
                    users.c.tenant_id == LOCAL_TENANT_ID,
                    users.c.user_id == LOCAL_USER_ID,
                )
            ).first() is None:
                connection.execute(
                    users.insert().values(
                        tenant_id=LOCAL_TENANT_ID,
                        user_id=LOCAL_USER_ID,
                        email="local-demo@reconflow.invalid",
                        display_name="Local Demo Auditor",
                        created_at=now,
                    )
                )

    def create_request(self, service_id: str) -> dict[str, Any]:
        if service_id not in SERVICE_LEDGER_TYPES:
            raise DemoValidationError("This service is not available in the local demo.")
        now = datetime.now(UTC)
        request_id = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(
                requests.insert().values(
                    tenant_id=LOCAL_TENANT_ID,
                    request_id=request_id,
                    owner_user_id=LOCAL_USER_ID,
                    service_id=service_id,
                    status="in_progress",
                    created_at=now,
                    modified_at=now,
                )
            )
        return self.get_request(request_id)

    def list_requests(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(requests)
                .where(
                    requests.c.tenant_id == LOCAL_TENANT_ID,
                    requests.c.owner_user_id == LOCAL_USER_ID,
                )
                .order_by(requests.c.modified_at.desc())
            ).mappings().all()
        return [
            {
                "id": row["request_id"],
                "serviceId": row["service_id"],
                "status": row["status"],
                "createdAt": _iso(row["created_at"]),
                "updatedAt": _iso(row["modified_at"]),
            }
            for row in rows
        ]

    def get_request(self, request_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            request_row = connection.execute(
                select(requests).where(
                    requests.c.tenant_id == LOCAL_TENANT_ID,
                    requests.c.request_id == request_id,
                    requests.c.owner_user_id == LOCAL_USER_ID,
                )
            ).mappings().first()
            if request_row is None:
                raise DemoNotFoundError("Demo request was not found.")

            answer_rows = connection.execute(
                select(assessment_answers).where(
                    assessment_answers.c.tenant_id == LOCAL_TENANT_ID,
                    assessment_answers.c.request_id == request_id,
                )
            ).mappings().all()
            document_rows = connection.execute(
                select(
                    documents.c.document_id,
                    documents.c.original_file_name,
                    documents.c.size_bytes,
                    documents.c.created_at,
                    ledger_imports.c.import_id,
                    ledger_imports.c.ledger_type,
                    ledger_imports.c.row_count,
                    ledger_imports.c.source_system,
                )
                .select_from(
                    documents.outerjoin(
                        ledger_imports,
                        (documents.c.tenant_id == ledger_imports.c.tenant_id)
                        & (documents.c.document_id == ledger_imports.c.document_id),
                    )
                )
                .where(
                    documents.c.tenant_id == LOCAL_TENANT_ID,
                    documents.c.request_id == request_id,
                    documents.c.owner_user_id == LOCAL_USER_ID,
                )
                .order_by(documents.c.created_at)
            ).mappings().all()
            latest_run = connection.execute(
                select(audit_runs)
                .where(
                    audit_runs.c.tenant_id == LOCAL_TENANT_ID,
                    audit_runs.c.request_id == request_id,
                    audit_runs.c.owner_user_id == LOCAL_USER_ID,
                )
                .order_by(audit_runs.c.created_at.desc())
                .limit(1)
            ).mappings().first()

            assessment = {
                row["question_id"]: json.loads(row["answer_json"])
                for row in answer_rows
            }
            documents_result = [
                self._document_result(connection, row)
                for row in document_rows
            ]
            run_result = None
            if latest_run:
                finding_rows = connection.execute(
                    select(audit_findings)
                    .where(
                        audit_findings.c.tenant_id == LOCAL_TENANT_ID,
                        audit_findings.c.run_id == latest_run["run_id"],
                        audit_findings.c.request_id == request_id,
                    )
                    .order_by(audit_findings.c.rule_code, audit_findings.c.source_row_number)
                ).mappings().all()
                disposition_rows = connection.execute(
                    select(finding_dispositions)
                    .where(
                        finding_dispositions.c.tenant_id == LOCAL_TENANT_ID,
                        finding_dispositions.c.run_id == latest_run["run_id"],
                        finding_dispositions.c.request_id == request_id,
                    )
                    .order_by(finding_dispositions.c.created_at.desc())
                ).mappings().all()
                latest_disposition: dict[str, dict[str, Any]] = {}
                for item in disposition_rows:
                    latest_disposition.setdefault(
                        item["finding_id"],
                        {
                            "status": item["disposition"],
                            "note": item["reviewer_note"],
                            "createdAt": _iso(item["created_at"]),
                        },
                    )
                run_result = {
                    "id": latest_run["run_id"],
                    "status": latest_run["status"],
                    "ruleVersion": latest_run["rule_version"],
                    "createdAt": _iso(latest_run["created_at"]),
                    "summary": json.loads(latest_run["summary_json"]),
                    "findings": [
                        {
                            "id": row["finding_id"],
                            "importId": row["import_id"],
                            "documentId": row["document_id"],
                            "sourceRowNumber": row["source_row_number"],
                            "ruleCode": row["rule_code"],
                            "severity": row["severity"],
                            "title": row["title"],
                            "description": row["description"],
                            "recommendation": row["recommendation"],
                            "evidence": json.loads(row["evidence_json"]),
                            "disposition": latest_disposition.get(row["finding_id"]),
                        }
                        for row in finding_rows
                    ],
                    "aiMessages": self._load_ai_messages(connection, request_id, latest_run["run_id"]),
                }

        return {
            "id": request_row["request_id"],
            "serviceId": request_row["service_id"],
            "status": request_row["status"],
            "createdAt": _iso(request_row["created_at"]),
            "updatedAt": _iso(request_row["modified_at"]),
            "assessment": assessment,
            "documents": documents_result,
            "latestRun": run_result,
        }

    @staticmethod
    def _document_result(
        connection: Connection,
        row: Any,
    ) -> dict[str, Any]:
        column_map = []
        if row["import_id"]:
            profiles = connection.execute(
                select(source_columns)
                .where(
                    source_columns.c.tenant_id == LOCAL_TENANT_ID,
                    source_columns.c.import_id == row["import_id"],
                )
                .order_by(source_columns.c.ordinal)
            ).mappings().all()
            column_map = [
                {
                    "sourceName": profile["source_name"],
                    "canonicalName": profile["canonical_name"],
                    "inferredType": profile["inferred_type"],
                    "analysisAllowed": profile["analysis_allowed"],
                }
                for profile in profiles
            ]
        return {
            "id": row["document_id"],
            "fileName": row["original_file_name"],
            "sizeBytes": row["size_bytes"],
            "createdAt": _iso(row["created_at"]),
            "importId": row["import_id"],
            "ledgerType": row["ledger_type"],
            "rowCount": row["row_count"],
            "sourceSystem": row["source_system"],
            "columnMap": column_map,
        }

    def save_assessment(self, request_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        request_row = self._get_request_row(request_id)
        validated = _validate_assessment(request_row["service_id"], answers)
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            for question_id, answer in validated.items():
                existing = connection.execute(
                    select(assessment_answers.c.question_id).where(
                        assessment_answers.c.tenant_id == LOCAL_TENANT_ID,
                        assessment_answers.c.request_id == request_id,
                        assessment_answers.c.question_id == question_id,
                    )
                ).first()
                values = {
                    "answer_json": json.dumps(answer, ensure_ascii=False, separators=(",", ":")),
                    "updated_at": now,
                }
                if existing:
                    connection.execute(
                        update(assessment_answers)
                        .where(
                            assessment_answers.c.tenant_id == LOCAL_TENANT_ID,
                            assessment_answers.c.request_id == request_id,
                            assessment_answers.c.question_id == question_id,
                        )
                        .values(**values)
                    )
                else:
                    connection.execute(
                        assessment_answers.insert().values(
                            tenant_id=LOCAL_TENANT_ID,
                            request_id=request_id,
                            question_id=question_id,
                            **values,
                        )
                    )
            connection.execute(
                update(requests)
                .where(
                    requests.c.tenant_id == LOCAL_TENANT_ID,
                    requests.c.request_id == request_id,
                )
                .values(modified_at=now)
            )
        return self.get_request(request_id)

    def upload_csv(
        self,
        request_id: str,
        file_name: str,
        content: bytes,
        source_system: str,
    ) -> dict[str, Any]:
        request_row = self._get_request_row(request_id)
        if source_system not in _VALID_ERP_NAMES:
            raise DemoValidationError("Select a supported ERP/export source or choose Unspecified.")
        safe_name = _safe_csv_name(file_name)
        frame = load_csv_dataframe(content, file_name=safe_name)
        ledger_type = identify_ledger_type(frame.columns)
        if ledger_type.value not in SERVICE_LEDGER_TYPES[request_row["service_id"]]:
            raise DemoValidationError(
                f"This service does not accept a {ledger_type.value.replace('_', ' ')} ledger."
            )

        document_count, existing_rows, existing_bytes = self._request_import_totals(request_id)
        if document_count >= MAX_DOCUMENTS_PER_REQUEST:
            raise DemoValidationError(
                f"A request can contain no more than {MAX_DOCUMENTS_PER_REQUEST} CSV files."
            )
        if existing_rows + len(frame.index) > MAX_REQUEST_ROWS:
            raise DemoValidationError(
                f"A request can contain no more than {MAX_REQUEST_ROWS} imported rows."
            )
        if existing_bytes + len(content) > MAX_REQUEST_BYTES:
            raise DemoValidationError(
                f"A request can contain no more than {MAX_REQUEST_BYTES} total upload bytes."
            )

        document_id = str(uuid.uuid4())
        relative_path = Path(LOCAL_TENANT_ID) / request_id / f"{document_id}.csv"
        target_path = self.storage_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(".tmp")
        now = datetime.now(UTC)
        try:
            temp_path.write_bytes(content)
            temp_path.replace(target_path)
            with self.engine.begin() as connection:
                connection.execute(
                    documents.insert().values(
                        tenant_id=LOCAL_TENANT_ID,
                        document_id=document_id,
                        request_id=request_id,
                        owner_user_id=LOCAL_USER_ID,
                        blob_name=relative_path.as_posix(),
                        original_file_name=safe_name,
                        content_type="text/csv",
                        content_sha256=hashlib.sha256(content).hexdigest(),
                        size_bytes=len(content),
                        created_at=now,
                        modified_at=now,
                    )
                )
                result = import_ledger_dataframe(
                    connection,
                    frame,
                    tenant_id=LOCAL_TENANT_ID,
                    owner_user_id=LOCAL_USER_ID,
                    request_id=request_id,
                    document_id=document_id,
                    source_system=source_system,
                )
                connection.execute(
                    update(requests)
                    .where(
                        requests.c.tenant_id == LOCAL_TENANT_ID,
                        requests.c.request_id == request_id,
                    )
                    .values(modified_at=now)
                )
        except Exception:
            target_path.unlink(missing_ok=True)
            raise

        return {
            "id": document_id,
            "fileName": safe_name,
            "sizeBytes": len(content),
            "ledgerType": result.ledger_type.value,
            "rowCount": result.row_count,
            "sourceSystem": source_system,
            "importId": result.import_id,
            "analysisColumns": [
                profile["name"] for profile in result.column_profiles if profile["analysis_allowed"]
            ],
        }

    def list_sample_files(self, service_id: str) -> list[dict[str, Any]]:
        allowed_types = SERVICE_LEDGER_TYPES.get(service_id)
        if allowed_types is None:
            raise DemoValidationError("This service is not available in the local demo.")
        return [
            item
            for item in _sample_catalog()
            if item["ledgerType"] in allowed_types
        ]

    def upload_sample(self, request_id: str, sample_id: str) -> dict[str, Any]:
        sample = next(
            (item for item in _sample_catalog() if item["id"] == sample_id),
            None,
        )
        if sample is None:
            raise DemoValidationError("Choose a test-pack CSV from the available sample list.")
        path = _SAMPLE_ROOT / Path(sample_id)
        return self.upload_csv(
            request_id,
            sample["fileName"],
            path.read_bytes(),
            sample["sourceSystem"],
        )

    def run_audit(self, request_id: str) -> dict[str, Any]:
        request_row = self._get_request_row(request_id)
        assessment = self._load_assessment(request_id)
        if not {"period_start", "period_end"}.issubset(assessment):
            raise DemoValidationError("Save the assessment period before running the audit.")
        sources = self._load_sources(request_id)
        if not sources:
            raise DemoValidationError("Upload at least one ledger CSV before running the audit.")
        applicable_types = SERVICE_LEDGER_TYPES[request_row["service_id"]]
        applicable_sources = [source for source in sources if source["ledger_type"] in applicable_types]
        findings = analyze_sources(request_row["service_id"], applicable_sources, assessment)
        rows_analyzed = count_rows_in_scope(
            request_row["service_id"],
            applicable_sources,
            assessment,
        )
        summary = summarize_findings(findings, len(applicable_sources))
        summary["rows_analyzed"] = rows_analyzed
        summary["finding_count"] = len(findings)
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        with self.engine.begin() as connection:
            connection.execute(
                audit_runs.insert().values(
                    tenant_id=LOCAL_TENANT_ID,
                    run_id=run_id,
                    request_id=request_id,
                    owner_user_id=LOCAL_USER_ID,
                    status="completed",
                    rule_version=RULE_VERSION,
                    created_at=now,
                    completed_at=now,
                    summary_json=json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                )
            )
            if findings:
                connection.execute(
                    audit_findings.insert(),
                    [
                        {
                            "tenant_id": LOCAL_TENANT_ID,
                            "finding_id": str(uuid.uuid4()),
                            "run_id": run_id,
                            "request_id": request_id,
                            "owner_user_id": LOCAL_USER_ID,
                            "import_id": finding["import_id"],
                            "document_id": finding["document_id"],
                            "source_row_number": finding["source_row_number"],
                            "rule_code": finding["rule_code"],
                            "severity": finding["severity"],
                            "title": finding["title"],
                            "description": finding["description"],
                            "recommendation": finding["recommendation"],
                            "evidence_json": json.dumps(finding["evidence"], ensure_ascii=False, separators=(",", ":")),
                            "created_at": now,
                        }
                        for finding in findings
                    ],
                )
            connection.execute(
                update(requests)
                .where(
                    requests.c.tenant_id == LOCAL_TENANT_ID,
                    requests.c.request_id == request_id,
                )
                .values(status="completed", modified_at=now)
            )
        return self.get_request(request_id)

    def save_disposition(
        self,
        request_id: str,
        run_id: str,
        finding_id: str,
        disposition: str,
        reviewer_note: str,
    ) -> dict[str, Any]:
        if disposition not in ALLOWED_DISPOSITIONS:
            raise DemoValidationError("Choose accepted, rejected, or needs_follow_up.")
        note = reviewer_note.strip()
        if len(note) > MAX_QUESTION_LENGTH:
            raise DemoValidationError(f"Reviewer notes must be {MAX_QUESTION_LENGTH} characters or fewer.")
        with self.engine.begin() as connection:
            finding_exists = connection.execute(
                select(audit_findings.c.finding_id).where(
                    audit_findings.c.tenant_id == LOCAL_TENANT_ID,
                    audit_findings.c.finding_id == finding_id,
                    audit_findings.c.run_id == run_id,
                    audit_findings.c.request_id == request_id,
                    audit_findings.c.owner_user_id == LOCAL_USER_ID,
                )
            ).first()
            if finding_exists is None:
                raise DemoNotFoundError("Finding was not found in this request.")
            connection.execute(
                finding_dispositions.insert().values(
                    tenant_id=LOCAL_TENANT_ID,
                    disposition_id=str(uuid.uuid4()),
                    finding_id=finding_id,
                    run_id=run_id,
                    request_id=request_id,
                    owner_user_id=LOCAL_USER_ID,
                    disposition=disposition,
                    reviewer_note=note,
                    created_at=datetime.now(UTC),
                )
            )
        return self.get_request(request_id)

    def record_ai_exchange(
        self,
        request_id: str,
        run_id: str,
        question: str,
        answer: str,
        model_deployment: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> dict[str, Any]:
        question = question.strip()
        if not question or len(question) > MAX_QUESTION_LENGTH:
            raise DemoValidationError(
                f"AI questions must contain 1 to {MAX_QUESTION_LENGTH} characters."
            )
        self._get_request_row(request_id)
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            conversation = connection.execute(
                select(ai_conversations.c.conversation_id).where(
                    ai_conversations.c.tenant_id == LOCAL_TENANT_ID,
                    ai_conversations.c.request_id == request_id,
                    ai_conversations.c.run_id == run_id,
                    ai_conversations.c.owner_user_id == LOCAL_USER_ID,
                )
            ).first()
            conversation_id = conversation[0] if conversation else str(uuid.uuid4())
            if not conversation:
                connection.execute(
                    ai_conversations.insert().values(
                        tenant_id=LOCAL_TENANT_ID,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        owner_user_id=LOCAL_USER_ID,
                        run_id=run_id,
                        created_at=now,
                        modified_at=now,
                    )
                )
            message_ids: dict[str, str] = {}
            for role, content, tokens in (
                ("user", question, prompt_tokens),
                ("assistant", answer, completion_tokens),
            ):
                message_id = str(uuid.uuid4())
                message_ids[role] = message_id
                connection.execute(
                    ai_messages.insert().values(
                        tenant_id=LOCAL_TENANT_ID,
                        message_id=message_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        owner_user_id=LOCAL_USER_ID,
                        role=role,
                        content=content,
                        provider="Microsoft Foundry",
                        model_deployment=model_deployment,
                        prompt_tokens=tokens if role == "user" else None,
                        completion_tokens=tokens if role == "assistant" else None,
                        created_at=now,
                    )
                )
            finding_ids = connection.execute(
                select(audit_findings.c.finding_id).where(
                    audit_findings.c.tenant_id == LOCAL_TENANT_ID,
                    audit_findings.c.run_id == run_id,
                    audit_findings.c.request_id == request_id,
                )
            ).scalars().all()
            if finding_ids:
                connection.execute(
                    ai_message_findings.insert(),
                    [
                        {
                            "tenant_id": LOCAL_TENANT_ID,
                            "message_id": message_ids["assistant"],
                            "finding_id": finding_id,
                            "run_id": run_id,
                            "request_id": request_id,
                            "owner_user_id": LOCAL_USER_ID,
                        }
                        for finding_id in finding_ids
                    ],
                )
            connection.execute(
                update(ai_conversations)
                .where(
                    ai_conversations.c.tenant_id == LOCAL_TENANT_ID,
                    ai_conversations.c.conversation_id == conversation_id,
                )
                .values(modified_at=now)
            )
        return self.get_request(request_id)

    def get_ai_context(self, request_id: str, run_id: str) -> dict[str, Any]:
        self._get_request_row(request_id)
        with self.engine.connect() as connection:
            run = connection.execute(
                select(audit_runs).where(
                    audit_runs.c.tenant_id == LOCAL_TENANT_ID,
                    audit_runs.c.run_id == run_id,
                    audit_runs.c.request_id == request_id,
                )
            ).mappings().first()
            if run is None:
                raise DemoNotFoundError("Audit run was not found.")
            found = connection.execute(
                select(
                    audit_findings.c.rule_code,
                    audit_findings.c.severity,
                    audit_findings.c.title,
                    audit_findings.c.description,
                    audit_findings.c.recommendation,
                ).where(
                    audit_findings.c.tenant_id == LOCAL_TENANT_ID,
                    audit_findings.c.run_id == run_id,
                    audit_findings.c.request_id == request_id,
                )
            ).mappings().all()
            conversation_rows = connection.execute(
                select(ai_messages.c.role, ai_messages.c.content)
                .select_from(
                    ai_messages.join(
                        ai_conversations,
                        (ai_messages.c.tenant_id == ai_conversations.c.tenant_id)
                        & (ai_messages.c.conversation_id == ai_conversations.c.conversation_id),
                    )
                )
                .where(
                    ai_messages.c.tenant_id == LOCAL_TENANT_ID,
                    ai_messages.c.request_id == request_id,
                    ai_messages.c.owner_user_id == LOCAL_USER_ID,
                    ai_conversations.c.run_id == run_id,
                )
                .order_by(ai_messages.c.created_at, ai_messages.c.message_id)
                .limit(10)
            ).mappings().all()
        summary = json.loads(run["summary_json"])
        finding_samples = [
            {
                "rule_code": row["rule_code"],
                "severity": row["severity"],
                "title": row["title"][:MAX_AI_FINDING_TEXT_LENGTH],
                "description": row["description"][:MAX_AI_FINDING_TEXT_LENGTH],
                "recommendation": row["recommendation"][:MAX_AI_FINDING_TEXT_LENGTH],
            }
            for row in found[:MAX_AI_FINDING_SAMPLES]
        ]
        return {
            "summary": summary,
            "findings": finding_samples,
            "finding_sample_count": len(finding_samples),
            "findings_are_representative_samples": True,
            "conversation": [
                {"role": row["role"], "content": row["content"]}
                for row in conversation_rows
            ],
        }

    def _load_ai_messages(
        self,
        connection: Connection,
        request_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            select(ai_messages)
            .where(
                ai_messages.c.tenant_id == LOCAL_TENANT_ID,
                ai_messages.c.request_id == request_id,
                ai_messages.c.owner_user_id == LOCAL_USER_ID,
            )
            .order_by(ai_messages.c.created_at, ai_messages.c.message_id)
        ).mappings().all()
        return [
            {
                "id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "modelDeployment": row["model_deployment"],
                "promptTokens": row["prompt_tokens"],
                "completionTokens": row["completion_tokens"],
                "createdAt": _iso(row["created_at"]),
            }
            for row in rows
            if connection.execute(
                select(ai_conversations.c.run_id).where(
                    ai_conversations.c.tenant_id == LOCAL_TENANT_ID,
                    ai_conversations.c.conversation_id == row["conversation_id"],
                    ai_conversations.c.run_id == run_id,
                )
            ).first()
        ]

    def _load_assessment(self, request_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(assessment_answers).where(
                    assessment_answers.c.tenant_id == LOCAL_TENANT_ID,
                    assessment_answers.c.request_id == request_id,
                )
            ).mappings().all()
        return {row["question_id"]: json.loads(row["answer_json"]) for row in rows}

    def _load_sources(self, request_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            imports = connection.execute(
                select(
                    ledger_imports.c.import_id,
                    ledger_imports.c.document_id,
                    ledger_imports.c.ledger_type,
                    documents.c.original_file_name,
                    ledger_imports.c.row_count,
                )
                .select_from(
                    ledger_imports.join(
                        documents,
                        (ledger_imports.c.tenant_id == documents.c.tenant_id)
                        & (ledger_imports.c.document_id == documents.c.document_id),
                    )
                )
                .where(
                    ledger_imports.c.tenant_id == LOCAL_TENANT_ID,
                    ledger_imports.c.request_id == request_id,
                )
                .order_by(ledger_imports.c.created_at)
            ).mappings().all()
            result = []
            for imported in imports:
                ledger_type = LedgerType(imported["ledger_type"])
                table = ledger_tables[ledger_type]
                rows = connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == LOCAL_TENANT_ID,
                        table.c.import_id == imported["import_id"],
                        table.c.request_id == request_id,
                    )
                    .order_by(table.c.row_number)
                ).mappings().all()
                result.append(
                    {
                        "import_id": imported["import_id"],
                        "document_id": imported["document_id"],
                        "file_name": imported["original_file_name"],
                        "ledger_type": ledger_type.value,
                        "rows": [dict(row) for row in rows],
                    }
                )
        return result

    def _get_request_row(self, request_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(requests).where(
                    requests.c.tenant_id == LOCAL_TENANT_ID,
                    requests.c.request_id == request_id,
                    requests.c.owner_user_id == LOCAL_USER_ID,
                )
            ).mappings().first()
        if row is None:
            raise DemoNotFoundError("Demo request was not found.")
        return dict(row)

    def _request_import_totals(self, request_id: str) -> tuple[int, int, int]:
        with self.engine.connect() as connection:
            imported_rows = connection.execute(
                select(ledger_imports.c.row_count).where(
                    ledger_imports.c.tenant_id == LOCAL_TENANT_ID,
                    ledger_imports.c.request_id == request_id,
                )
            ).scalars().all()
            document_sizes = connection.execute(
                select(documents.c.size_bytes).where(
                    documents.c.tenant_id == LOCAL_TENANT_ID,
                    documents.c.request_id == request_id,
                )
            ).scalars().all()
        return len(document_sizes), sum(imported_rows), sum(document_sizes)


@lru_cache(maxsize=1)
def get_demo_store() -> DemoStore:
    local_demo = os.getenv("RECONFLOW_LOCAL_DEMO", "").casefold() == "true"
    hosted_demo = os.getenv("RECONFLOW_HOSTED_DEMO", "").casefold() == "true"
    if local_demo and not os.getenv("WEBSITE_INSTANCE_ID"):
        return DemoStore()
    if hosted_demo:
        return DemoStore()
    raise DemoValidationError("The ReconFlow guest demo is disabled.")
    return DemoStore()


@lru_cache(maxsize=1)
def _sample_catalog() -> tuple[dict[str, Any], ...]:
    if not _SAMPLE_ROOT.is_dir():
        return ()
    samples = []
    for path in sorted(_SAMPLE_ROOT.glob("*/*.csv")):
        frame = load_csv_dataframe(path)
        source_system = _ERP_FOLDER_NAMES.get(path.parent.name)
        if source_system is None:
            continue
        samples.append(
            {
                "id": path.relative_to(_SAMPLE_ROOT).as_posix(),
                "fileName": path.name,
                "sourceSystem": source_system,
                "ledgerType": identify_ledger_type(frame.columns).value,
                "rowCount": len(frame.index),
            }
        )
    return tuple(samples)


def _validate_assessment(service_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(answers, dict):
        raise DemoValidationError("Assessment answers must be a JSON object.")
    common = {"period_start", "period_end", "currency"}
    allowed = {
        "journal-entry-analytics": common | {
            "approval_threshold",
            "round_amount_quantum",
            "round_amount_minimum",
        },
        "invoice-integrity-review": common | {"approval_threshold"},
        "inventory-asset-controls": common | {"asset_snapshot_date"},
    }.get(service_id)
    if allowed is None:
        raise DemoValidationError("This service is not available in the local demo.")
    unknown = set(answers) - allowed
    if unknown:
        raise DemoValidationError(f"Unknown assessment question: {min(unknown)}.")
    missing = common - set(answers)
    if missing:
        raise DemoValidationError(f"Complete the assessment question: {min(missing)}.")

    start = _parse_date(answers["period_start"], "period_start")
    end = _parse_date(answers["period_end"], "period_end")
    if start > end:
        raise DemoValidationError("The assessment start date must be on or before the end date.")
    currency = answers["currency"]
    if not isinstance(currency, str) or currency not in {"ZAR", "USD", "EUR", "GBP"}:
        raise DemoValidationError("Select a supported reporting currency.")

    cleaned: dict[str, Any] = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "currency": currency,
    }
    if service_id in {"journal-entry-analytics", "invoice-integrity-review"}:
        cleaned["approval_threshold"] = _positive_amount(
            answers.get("approval_threshold", "50000"), "approval_threshold"
        )
    if service_id == "journal-entry-analytics":
        cleaned["round_amount_quantum"] = _positive_amount(
            answers.get("round_amount_quantum", "10000"), "round_amount_quantum"
        )
        cleaned["round_amount_minimum"] = _positive_amount(
            answers.get("round_amount_minimum", "100000"), "round_amount_minimum"
        )
    if service_id == "inventory-asset-controls" and answers.get("asset_snapshot_date"):
        cleaned["asset_snapshot_date"] = _parse_date(
            answers["asset_snapshot_date"], "asset_snapshot_date"
        ).isoformat()
    return cleaned


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise DemoValidationError(f"{field_name} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DemoValidationError(f"{field_name} must be an ISO date (YYYY-MM-DD).") from exc


def _positive_amount(value: Any, field_name: str) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DemoValidationError(f"{field_name} must be a positive number.") from exc
    if not amount.is_finite() or amount <= 0 or len(str(amount)) > 32:
        raise DemoValidationError(f"{field_name} must be a positive number.")
    return format(amount, "f")


def _safe_csv_name(value: str) -> str:
    name = str(value).replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not _SAFE_FILE_NAME.fullmatch(name):
        raise DemoValidationError("Upload a CSV file with a safe file name.")
    return name


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
