# Remote MCP Audit Server

A production-oriented Model Context Protocol (MCP) tool server implemented as an Azure Function, designed for deterministic financial and compliance operations, auditable execution, and tenant-safe retrieval.

This repository also includes the local-first ReconFlow audit demo: a React/Vite workspace,
Python Function API, deterministic CAATs engine, optional consent-gated Foundry review, and
synthetic ERP fixtures in `sample_data/`. Infrastructure is maintained separately in
`mcp-audit-infra`.

## Architecture

```mermaid
flowchart LR
    Client[MCP client] -->|JSON-RPC 2.0| AF[Azure Functions HTTP MCP endpoint]
    AF --> Tools[Deterministic tool implementations]
    Tools --> Decimal[Decimal and Pydantic v2 validation]
    AF --> Store[Audit store abstraction]
    Store --> Memory[In-memory sink for local development]
    Store --> Cosmos[(Azure Cosmos DB)]
    AF --> AI[Application Insights]

    MI[Managed Identity / Azure CLI] --> Cosmos
    MI --> KeyVault[Azure Key Vault]
```

The HTTP endpoint implements MCP initialization and `tools/list`/`tools/call`. Tool operations use Pydantic v2 strict schemas and Python `Decimal` arithmetic. Azure storage and credentials are isolated behind `AuditStore` implementations.

## ReconFlow demo workflows

The demo UI currently has three executable, deterministic workflows: Journal Entry Analytics,
Invoice Integrity Review, and Inventory & Fixed Asset Controls. The other catalog cards are
workflow previews, not implemented services. The bundled fixture pack contains 36 synthetic
ERP ledger CSVs, four audit examples, and a manifest. Local processing keeps uploads and
review state in ignored `.local/` files and SQLite; Azure SQL has a schema, but application
persistence to Azure SQL is not wired yet.

The demo engine detects candidate exceptions; results are not audit opinions, fraud findings,
or proof that a control failed. The optional Foundry adapter is separately consent-gated and
receives a summary rather than raw ledger rows or planted ground-truth labels. AI is disabled
by default.

## Tools

### `validate_invoice_math`

Reconciles line-item totals, reported subtotal, tax amount, and reported total using `Decimal`, `ROUND_HALF_UP`, and cent precision. It returns exact variances and structured findings.

### `evaluate_policy_compliance`

Evaluates configured spend limits, approval tiers, VAT registration, and SLA/due-date rules. Policy evaluation is deterministic and never invokes an LLM.

### `query_audit_trail`

Queries tenant-scoped audit records, optionally filtered by tool name, with bounded limits and opaque cursor pagination. A tenant boundary is enforced in both the in-memory and Cosmos implementations.

## Deterministic vs. Probabilistic Boundary

- All money, tax, invoice, threshold, and compliance decisions use `Decimal` values from JSON strings; JSON floats and booleans are rejected.
- Pydantic v2 rejects unknown fields and validates ranges, lengths, finite decimals, and required policy fields.
- Probabilistic components, such as an LLM client, must only assist with language or recommendation workflows and must not calculate financial values or determine compliance outcomes.

## Audit and Failure Handling

Every tool invocation records:

- `trace_id` correlation ID
- `tenantId`
- tool name
- request summary
- output or error summary
- duration in milliseconds
- status and JSON-RPC error code
- UTC timestamp

Cosmos writes use `DefaultAzureCredential`, which selects Managed Identity in Azure and Azure CLI or developer credentials locally. Writes use bounded exponential backoff with jitter. Invalid JSON-RPC requests return structured JSON-RPC error objects rather than HTTP 500 responses.

## Security and Identity

- No keys, connection strings, publish profiles, or credentials are stored in source.
- Cosmos access uses Azure RBAC and `DefaultAzureCredential`.
- GitHub Actions authenticates through OIDC using `azure/login@v2`; no secrets are serialized to the deployment job.
- The HTTP route should remain function-authenticated or be placed behind an approved API gateway in production.
- Restrict Cosmos container and Key Vault role assignments to the server managed identity.

The Cosmos endpoint and database/container names may be configured by environment variables. If `COSMOS_ENDPOINT` is absent, the server uses the local in-memory audit sink.

## Cost and Latency Trade-offs

| Concern | Choice | Trade-off |
|---|---|---|
| Hosting | Linux Consumption | Low idle cost; cold starts and limited always-on predictability |
| Persistence | Cosmos DB Free Tier | Low-cost start; monitor RU consumption and partition growth |
| Audit writes | Cosmos upsert | Stronger durability; network latency and retry cost |
| Local testing | In-memory sink | Fast/offline; process-local and not durable |
| Logs | Application Insights | Production observability; ingestion/sample cost |
| Query pagination | Opaque offset cursors | Deterministic and bounded; not a distributed continuation token guarantee |

Cold starts can be reduced operationally by moving to a warmer plan, but this changes the portfolio's cost profile. Monitoring should include duration, write failures, Cosmos throttling, cold-start frequency, and per-tenant request volume.

## Local Development

Use [LOCAL_DEMO_GUIDE.txt](LOCAL_DEMO_GUIDE.txt) to start the API and frontend, run the three
sample workflows, or point the local UI at the existing Azure API. Use
[PUSH_AND_DEPLOY_GUIDE.txt](PUSH_AND_DEPLOY_GUIDE.txt) for safe GitHub account, push, and
deployment steps. [INTERVIEW_VIDEO_GUIDE.txt](INTERVIEW_VIDEO_GUIDE.txt) is a five-minute
interview outline. The local `docs/` folder is intentionally gitignored.

## Cloud Deployment

Deployment uses Python 3.12 consistently in:

- the local virtual environment
- GitHub Actions setup
- Azure Function runtime configuration

The deployment workflow expects these repository variables:

| Variable | Purpose |
|---|---|
| `AZURE_CLIENT_ID` | Federated Entra application/client ID |
| `AZURE_TENANT_ID` | Microsoft Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_FUNCTIONAPP_NAME` | Linux Function App name |

Configure Terraform or Azure policy to align the Function App runtime with Python 3.12. Configure federated credentials for the repository and branch/environment being used. The workflow uses `azure/login@v2` and `Azure/functions-action@v1` without publish-profile secrets.

The app deployment workflow deploys the Function API from `main`. The
`swa-deploy.yml` workflow builds and publishes the prebuilt React/Vite frontend to the
existing Static Web App on changes to `frontend/` merged or pushed to `main`, or on a
manual dispatch from `main`. It requires the GitHub Actions secret
`AZURE_STATIC_WEB_APPS_API_TOKEN`; the optional repository variable
`RECONFLOW_API_BASE_URL` defaults to the existing Function API URL. Never put the
deployment token in source or logs. The workflow does not provision Azure resources.

Existing demo resources in `rg-mcp-audit-dev` include a Function App, Static Web App,
Azure SQL, Storage, Foundry, and Application Insights. The live Function uses managed
identity for Foundry and Storage. The inspected resource group has no VNet/private
endpoints; current public-endpoint demo calls work without VNet integration. The
Terraform root is not reconciled with those live resources and is not ready to apply.

Example Azure runtime settings:

```text
COSMOS_ENDPOINT=<resource-specific-account-endpoint>
COSMOS_DATABASE_NAME=<database-name>
COSMOS_CONTAINER_NAME=<container-name>
```

The Cosmos container must use `/tenantId` as its partition key, matching the Terraform configuration. `COSMOS_DATABASE` and `COSMOS_CONTAINER` remain supported as legacy aliases for local setups.

Do not configure Cosmos keys or connection strings. Grant the Function App managed identity the required Cosmos data-plane role and least-privilege Key Vault role separately.

## Architecture Decision Record

### ADR-001: Separate deterministic tools from probabilistic clients

**Status:** Accepted

**Context:** Financial reconciliation and policy compliance are high-consequence decisions. Floating-point arithmetic or model-generated calculations can create nondeterministic or disputed outcomes.

**Decision:** Pydantic v2 schemas and `Decimal` are mandatory at MCP tool boundaries. Monetary operations use explicit cent quantization and `ROUND_HALF_UP`. LLM or probabilistic components are not used for tool calculations.

**Consequences:** Requests must use decimal strings rather than JSON floats. Tests assert exact `Decimal` results and edge cases. External consumers gain a reproducible decision boundary at the cost of stricter input contracts.

### ADR-002: Audit store abstraction with in-memory fallback

**Status:** Accepted

**Context:** Local development must remain offline while Azure deployment requires durable audit storage.

**Decision:** Introduce `AuditStore` with in-memory and Cosmos implementations selected from `COSMOS_ENDPOINT` configuration. Cosmos writes use managed identity and bounded retries.

**Consequences:** Local behavior is convenient but ephemeral. Cosmos behavior is durable but requires Azure RBAC and network availability.

## Repository Structure

```text
function_app.py
host.json
requirements.txt
requirements-dev.txt
src/
  audit_store.py
  schemas/models.py
  tools/
    reconcile.py
    policy_check.py
    audit_trail.py
tests/test_tools.py
.github/workflows/app-deploy.yml
```
