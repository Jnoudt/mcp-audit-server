# Security and Governance Policy

## 1. Purpose

This policy establishes security, governance, and version-currency requirements for the MCP audit server and its Azure infrastructure. It is intended to reduce supply-chain, identity, data-exposure, and operational-risk outcomes while keeping the project usable on Azure free-tier and local-development resources.

## 2. Scope

The policy applies to:

- Azure Functions application code and MCP JSON-RPC tools.
- Azure Cosmos DB audit records.
- Azure Key Vault references and secrets.
- Application Insights telemetry.
- Terraform infrastructure and GitHub Actions workflows.
- Developer workstations and CI runners.

## 3. Resource Tagging

Every Azure resource managed through Terraform must carry these tags where the provider and resource type support tagging:

| Tag | Required value pattern | Purpose |
|---|---|---|
| `environment` | `dev`, `test`, or `prod` | Environment separation |
| `project` | `mcp-audit` | Portfolio/resource grouping |
| `owner` | Named team or accountable maintainer | Incident ownership |
| `costCenter` | Approved cost center or `portfolio` | Cost attribution |
| `dataClassification` | `internal` or documented approved level | Data handling expectations |
| `managedBy` | `terraform` | Infrastructure ownership |

Tagging policy exceptions require a documented reason, an issue or ADR reference, and a remediation owner. Untagged resources must not be promoted to production. Azure Policy, if enabled, should deny or audit missing mandatory tags.

## 4. RBAC and Least Privilege

- Use Microsoft Entra ID workload identities; never embed service-account keys or publish profiles in source, environment files, or workflow YAML.
- Locally, `DefaultAzureCredential` may resolve Azure CLI credentials only for development.
- In Azure, `DefaultAzureCredential` must resolve the Function App user-assigned or system-assigned managed identity.
- Cosmos DB access should use a narrowly scoped data-plane role granting the server the minimum required item operations. The server must not receive owner, subscription, or account-management roles.
- Key Vault access must use the smallest applicable secret or certificate role. The server should prefer managed-secret references or runtime retrieval only when strictly necessary.
- GitHub Actions deployment identity must use OpenID Connect federated credentials constrained by repository, branch, or environment subject claims.
- Subscription-level deployments require separate infrastructure identity permissions; application runtime identity permissions must remain isolated from deployment identity permissions.
- Human administrator access must be temporary, reviewed, and scoped to the minimum RBAC role and resource scope required.

## 5. MCP Input Threat Mitigation

### Validation and type safety

- Pydantic v2 strict models are mandatory at tool boundaries.
- Unknown fields must be rejected.
- JSON floating-point values must not be accepted for monetary or deterministic compliance fields; decimal strings are required.
- Strings must enforce type, length, character, enum, and tenant constraints.
- Arrays must enforce item count and nested item limits.
- `Decimal` values must be finite, bounded, and processed with explicit precision and `ROUND_HALF_UP` where cent rounding applies.

### Input abuse defenses

- Enforce request-body size limits at Azure Functions/API gateway boundaries.
- Enforce per-tenant and per-client rate limits where deployed behind API Management or an equivalent gateway.
- Bound cursor length and list result limits.
- Reject unbounded or recursive structures before they reach deterministic tool logic.
- Return MCP JSON-RPC error codes and redacted error data. Do not echo stack traces, credentials, resource IDs, SDK exceptions, or filesystem paths.
- Correlate all failures and successes with a generated or supplied `trace_id`/correlation ID, with length constraints.

### Deterministic boundary

No LLM, prompt, or probabilistic service may determine tax, invoice, spend, approval, or compliance results. Those operations must remain reproducible from structured inputs using Pydantic and `Decimal`.

## 6. Audit Log Threat Mitigation

- Audit records must contain tenant ID, trace ID, tool name, request/output summaries, duration, status, error code, and UTC timestamp.
- Do not record secrets, authorization headers, raw connection strings, private keys, full payloads containing sensitive data, or unnecessary personal data.
- Tenant filtering is mandatory in all audit queries. Authorization must occur before data selection or pagination.
- Cursor values must be opaque and bounded. Cursor decoding must fail safely and never expose internal offsets or storage identifiers.
- Restrict audit container access by tenant/partition design and RBAC.
- Preserve append-oriented audit behavior where supported. In Cosmos DB, use deterministic IDs and immutable retention patterns appropriate to the governance requirement.
- Export audit and Application Insights records to a retention tier that meets the intended evidence and privacy schedule.
- Treat log injection as untrusted input: emit structured JSON, sanitize control characters, and avoid user-derived free text in log labels.

## 7. Application and Secret Hardening

- Keep the Azure Functions route behind function authorization or an approved API gateway in production.
- Use HTTPS-only configuration and restrict CORS to known origins.
- Pin application dependencies and GitHub Actions major versions where practical, and review transitive dependency findings.
- Do not add local settings or environment files containing secrets to Git.
- Rotate credentials and OIDC federated subject bindings during repository transfer or ownership changes.
- Disable anonymous or unrestricted access unless a time-bounded threat model explicitly accepts it.
- Apply secure transport, TLS, and TLS policy requirements supported by the infrastructure provider.

## 8. Version Currency and Support Policy

The baseline supported versions are:

| Component | Minimum/current target | Enforcement |
|---|---|---|
| Python runtime | 3.12 | CI and Azure Functions runtime must use 3.12 consistently; maintain a dated review of support lifecycle |
| Terraform | 1.8 or newer | Pin CLI/workflow Terraform to a tested maintained version |
| AzureRM provider | 4.x | Pin provider major line and test upgrades in a non-production state |
| Azure Functions runtime | v4 | Configure function runtime in `host.json` and deployment tooling |
| GitHub Actions | Maintained action major versions | Pin or regularly update `checkout`, `setup-python`, `azure/login`, and `functions-action` |

Version checks must run quarterly and before production release. Checks must include:

- Python EOL and Azure Functions runtime support status.
- Terraform CLI and AzureRM provider release/security status.
- Azure SKU and service API deprecation notices.
- GitHub Actions action deprecation advisories.
- Python package security and outdated direct dependencies.

### Current alignment rule

Python 3.12.10 is currently the local environment baseline. All local, CI, Azure Functions, and documentation references must use Python 3.12 until an approved migration moves the project. Terraform infrastructure must not claim a Python 3.11 runtime unless application CI and deployment are also changed to the same runtime.

## 9. Scanning and Release Gates

Free/default release checks:

- Python dependency auditing.
- Static application security analysis for Python.
- Source vulnerability scanning for introduced dependencies and known vulnerable functions.
- Terraform format and validation checks.
- Unit, schema, hostile-payload, and audit-sink tests.
- Secret scanning and workflow YAML validation.

Commercial scanners are optional and conditional:

- Mend OSS/SCA runs only when required Mend variables and credentials are configured.
- Checkmarx scans run only when its required CI variables and credentials are configured.
- A missing commercial license must not block the free security baseline; absence must be represented as a documented skip, not as success.

## 10. Deprecated and Outdated Azure SKU Controls

Before release, infrastructure review must verify:

- No deprecated Azure Functions extension/runtime package is deployed.
- Consumption or supporting resource SKUs are still available and not retired.
- Cosmos DB free-tier and regional settings match the documented free-tier constraints.
- Resource APIs, provider features, and deployment scripts are supported in AzureRM 4.x.
- Application Insights resource configuration follows the current Azure Monitor integration model.

Any Azure retirement notice found during review requires an owner, migration target, exception date, and tracked remediation issue.

## 11. Governance Review Cadence

- Pull requests: automated security baseline and tests.
- Monthly: dependency and platform-currency review.
- Quarterly: full threat review, RBAC review, secret review, and Azure resource/SKU review.
- Before production: identity, retention, public exposure, rate limiting, and rollback checks.
- After a security incident: update controls and add a focused regression test.

## 12. Policy Exceptions

Exceptions must contain:

1. The violated requirement.
2. Threat and operational justification.
3. Compensating controls.
4. A named owner.
5. An expiration or remediation date.
6. An approval record or tracked governance issue.

Expired exceptions must trigger a block or escalation rather than remain silent CI skips.

## 13. Security Verification Evidence

Security claims must be supported by test output, CI logs, scanner artifacts, Terraform plan output, and identity configuration evidence. The README and workflow badges may summarize status but must not imply that commercial scanners ran when they were skipped.
