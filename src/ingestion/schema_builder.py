"""Relational ownership, request, document, import, and ledger table definitions."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Connection, Engine

from .ledger_types import LedgerType

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("user_id", String(128), primary_key=True),
    Column("email", String(320), nullable=False),
    Column("display_name", String(256), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
)

requests = Table(
    "requests",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("request_id", String(128), primary_key=True),
    Column("owner_user_id", String(128), nullable=False),
    Column("service_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("modified_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        ["users.tenant_id", "users.user_id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "request_id", "owner_user_id"),
)

documents = Table(
    "documents",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("document_id", String(128), primary_key=True),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("blob_name", String(512), nullable=False, unique=True),
    Column("original_file_name", String(255), nullable=False),
    Column("content_type", String(128), nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("modified_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "request_id", "owner_user_id"],
        ["requests.tenant_id", "requests.request_id", "requests.owner_user_id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "document_id", "request_id", "owner_user_id"),
)
Index("ix_documents_owner_modified", documents.c.tenant_id, documents.c.owner_user_id, documents.c.modified_at)

ledger_imports = Table(
    "ledger_imports",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("import_id", String(128), primary_key=True),
    Column("document_id", String(128), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("ledger_type", String(64), nullable=False),
    Column("source_system", String(128), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("row_count", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "document_id", "request_id", "owner_user_id"],
        [
            "documents.tenant_id",
            "documents.document_id",
            "documents.request_id",
            "documents.owner_user_id",
        ],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "import_id", "document_id", "request_id", "owner_user_id"),
)

source_columns = Table(
    "source_columns",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("import_id", String(128), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("source_name", String(128), nullable=False),
    Column("canonical_name", String(128)),
    Column("inferred_type", String(32), nullable=False),
    Column("is_nullable", Boolean, nullable=False),
    Column("analysis_allowed", Boolean, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "import_id"],
        ["ledger_imports.tenant_id", "ledger_imports.import_id"],
        ondelete="CASCADE",
    ),
)

assessment_answers = Table(
    "assessment_answers",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("request_id", String(128), primary_key=True),
    Column("question_id", String(128), primary_key=True),
    Column("answer_json", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "request_id"],
        ["requests.tenant_id", "requests.request_id"],
        ondelete="CASCADE",
    ),
)

audit_runs = Table(
    "audit_runs",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("run_id", String(128), primary_key=True),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("rule_version", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("summary_json", Text, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "request_id", "owner_user_id"],
        ["requests.tenant_id", "requests.request_id", "requests.owner_user_id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "run_id", "request_id", "owner_user_id"),
)

audit_findings = Table(
    "audit_findings",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("run_id", String(128), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("import_id", String(128), nullable=False),
    Column("document_id", String(128), nullable=False),
    Column("source_row_number", BigInteger),
    Column("rule_code", String(128), nullable=False),
    Column("severity", String(32), nullable=False),
    Column("title", String(256), nullable=False),
    Column("description", Text, nullable=False),
    Column("recommendation", Text, nullable=False),
    Column("evidence_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "run_id", "request_id", "owner_user_id"],
        ["audit_runs.tenant_id", "audit_runs.run_id", "audit_runs.request_id", "audit_runs.owner_user_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "import_id"],
        ["ledger_imports.tenant_id", "ledger_imports.import_id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "document_id", "request_id", "owner_user_id"],
        ["documents.tenant_id", "documents.document_id", "documents.request_id", "documents.owner_user_id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "finding_id", "run_id", "request_id", "owner_user_id"),
)
Index("ix_audit_findings_run", audit_findings.c.tenant_id, audit_findings.c.run_id, audit_findings.c.rule_code)

finding_dispositions = Table(
    "finding_dispositions",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("disposition_id", String(128), primary_key=True),
    Column("finding_id", String(128), nullable=False),
    Column("run_id", String(128), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("disposition", String(32), nullable=False),
    Column("reviewer_note", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "finding_id", "run_id", "request_id", "owner_user_id"],
        ["audit_findings.tenant_id", "audit_findings.finding_id", "audit_findings.run_id", "audit_findings.request_id", "audit_findings.owner_user_id"],
        ondelete="RESTRICT",
    ),
)

ai_conversations = Table(
    "ai_conversations",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("conversation_id", String(128), primary_key=True),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("run_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("modified_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "request_id", "owner_user_id"],
        ["requests.tenant_id", "requests.request_id", "requests.owner_user_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "run_id", "request_id", "owner_user_id"],
        ["audit_runs.tenant_id", "audit_runs.run_id", "audit_runs.request_id", "audit_runs.owner_user_id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "conversation_id", "request_id", "owner_user_id"),
)

ai_messages = Table(
    "ai_messages",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("message_id", String(128), primary_key=True),
    Column("conversation_id", String(128), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model_deployment", String(128), nullable=False),
    Column("prompt_tokens", Integer),
    Column("completion_tokens", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id", "request_id", "owner_user_id"],
        ["ai_conversations.tenant_id", "ai_conversations.conversation_id", "ai_conversations.request_id", "ai_conversations.owner_user_id"],
        ondelete="CASCADE",
    ),
    UniqueConstraint("tenant_id", "message_id", "request_id", "owner_user_id"),
)

ai_message_findings = Table(
    "ai_message_findings",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("message_id", String(128), primary_key=True),
    Column("finding_id", String(128), primary_key=True),
    Column("run_id", String(128), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("owner_user_id", String(128), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "message_id", "request_id", "owner_user_id"],
        ["ai_messages.tenant_id", "ai_messages.message_id", "ai_messages.request_id", "ai_messages.owner_user_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "finding_id", "run_id", "request_id", "owner_user_id"],
        ["audit_findings.tenant_id", "audit_findings.finding_id", "audit_findings.run_id", "audit_findings.request_id", "audit_findings.owner_user_id"],
        ondelete="RESTRICT",
    ),
)

_LEDGER_COLUMNS: dict[LedgerType, tuple[Column, ...]] = {
    LedgerType.GENERAL_LEDGER: (
        Column("company_code", String(128)),
        Column("document_number", String(128), nullable=False),
        Column("fiscal_year", Integer),
        Column("document_type", String(64)),
        Column("posting_date", Date, nullable=False),
        Column("account_code", String(128), nullable=False),
        Column("cost_center", String(128)),
        Column("direction", String(16)),
        Column("amount", Numeric(precision=30, scale=8), nullable=False),
        Column("currency", String(3)),
        Column("description", Text),
    ),
    LedgerType.ACCOUNTS_RECEIVABLE: (
        Column("company_code", String(128)),
        Column("customer_id", String(128), nullable=False),
        Column("transaction_id", String(128)),
        Column("invoice_number", String(128), nullable=False),
        Column("invoice_date", Date, nullable=False),
        Column("posting_date", Date),
        Column("due_date", Date),
        Column("amount", Numeric(precision=30, scale=8), nullable=False),
        Column("currency", String(3)),
        Column("tax_code", String(128)),
    ),
    LedgerType.ACCOUNTS_PAYABLE: (
        Column("company_code", String(128)),
        Column("vendor_id", String(128), nullable=False),
        Column("transaction_id", String(128)),
        Column("invoice_number", String(128), nullable=False),
        Column("invoice_date", Date, nullable=False),
        Column("posting_date", Date),
        Column("purchase_order", String(128)),
        Column("amount", Numeric(precision=30, scale=8), nullable=False),
        Column("currency", String(3)),
        Column("tax_code", String(128)),
    ),
    LedgerType.FIXED_ASSETS: (
        Column("company_code", String(128)),
        Column("asset_id", String(128), nullable=False),
        Column("asset_class", String(128)),
        Column("description", Text),
        Column("in_service_date", Date),
        Column("useful_life_years", Numeric(precision=12, scale=4)),
        Column("acquisition_cost", Numeric(precision=30, scale=8), nullable=False),
        Column("accumulated_depreciation", Numeric(precision=30, scale=8), nullable=False),
        Column("period_depreciation", Numeric(precision=30, scale=8)),
        Column("currency", String(3)),
    ),
    LedgerType.INVENTORY: (
        Column("location", String(128)),
        Column("item_id", String(128), nullable=False),
        Column("description", Text),
        Column("movement_type", String(128), nullable=False),
        Column("reference_number", String(128)),
        Column("posting_date", Date, nullable=False),
        Column("quantity", Numeric(precision=30, scale=8), nullable=False),
        Column("unit_of_measure", String(32)),
        Column("unit_cost", Numeric(precision=30, scale=8)),
        Column("total_cost", Numeric(precision=30, scale=8)),
        Column("currency", String(3)),
    ),
    LedgerType.CASH_BANK: (
        Column("company_code", String(128)),
        Column("bank_account", String(128), nullable=False),
        Column("account_identifier", String(128)),
        Column("transaction_id", String(128), nullable=False),
        Column("value_date", Date, nullable=False),
        Column("posting_date", Date),
        Column("payment_type", String(128)),
        Column("amount", Numeric(precision=30, scale=8), nullable=False),
        Column("currency", String(3)),
        Column("reference", Text),
    ),
}

ledger_tables: dict[LedgerType, Table] = {}
for _ledger_type, _columns in _LEDGER_COLUMNS.items():
    _table = Table(
        f"{_ledger_type.value}_rows",
        metadata,
        Column("tenant_id", String(128), primary_key=True),
        Column("import_id", String(128), primary_key=True),
        Column("row_number", BigInteger, primary_key=True),
        Column("document_id", String(128), nullable=False),
        Column("request_id", String(128), nullable=False),
        Column("owner_user_id", String(128), nullable=False),
        *_columns,
        Column("source_payload_json", Text, nullable=False),
        ForeignKeyConstraint(
            ["tenant_id", "import_id", "document_id", "request_id", "owner_user_id"],
            [
                "ledger_imports.tenant_id",
                "ledger_imports.import_id",
                "ledger_imports.document_id",
                "ledger_imports.request_id",
                "ledger_imports.owner_user_id",
            ],
            ondelete="CASCADE",
        ),
    )
    Index(f"ix_{_ledger_type.value}_owner", _table.c.tenant_id, _table.c.owner_user_id, _table.c.request_id)
    ledger_tables[_ledger_type] = _table


def create_schema(engine: Engine | Connection) -> None:
    """Create the fixed, reviewed relational schema on a SQLAlchemy engine."""
    metadata.create_all(engine)
