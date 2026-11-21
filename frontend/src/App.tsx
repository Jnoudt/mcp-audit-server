import { useMemo, useState } from "react";

type ToolDefinition = {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
};

type AuditRecord = {
  trace_id?: string;
  tenantId?: string;
  tool_name?: string;
  status?: string;
  duration_ms?: number;
  timestamp?: string;
  error_code?: number | null;
  request_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
};

type AuthMode = "none" | "function" | "api" | "bearer";
type ViewMode = "demo" | "connected" | "connecting";
type FilterMode = "all" | "success" | "error" | "findings";

const DEMO_TOOLS: ToolDefinition[] = [
  {
    name: "validate_invoice_math",
    description: "Deterministically reconcile invoice line items, tax, subtotal, and total.",
    inputSchema: {
      required: [
        "tenantId",
        "invoice_id",
        "line_items",
        "reported_subtotal",
        "tax_rate",
        "reported_tax",
        "reported_total",
      ],
    },
  },
  {
    name: "evaluate_policy_compliance",
    description: "Evaluate deterministic spend, approval, VAT, and SLA policy rules.",
    inputSchema: { required: ["tenantId", "amount", "policy"] },
  },
  {
    name: "query_audit_trail",
    description: "Query recent tenant audit records with optional tool filtering and pagination.",
    inputSchema: { required: ["tenantId"] },
  },
];

const DEMO_RECORDS: AuditRecord[] = [
  {
    trace_id: "demo-trace-8f31",
    tenantId: "tenant-demo",
    tool_name: "validate_invoice_math",
    status: "success",
    duration_ms: 18,
    timestamp: "2026-11-21T09:42:18Z",
    request_summary: { invoice_id: "INV-2048" },
    output_summary: { findings: ["tax_amount_mismatch", "total_mismatch"] },
  },
  {
    trace_id: "demo-trace-5b27",
    tenantId: "tenant-demo",
    tool_name: "evaluate_policy_compliance",
    status: "error",
    duration_ms: 12,
    timestamp: "2026-11-21T09:38:04Z",
    error_code: -32602,
    request_summary: { amount: "840.00" },
    output_summary: { error: "Invalid tool arguments" },
  },
  {
    trace_id: "demo-trace-2a19",
    tenantId: "tenant-demo",
    tool_name: "query_audit_trail",
    status: "success",
    duration_ms: 7,
    timestamp: "2026-11-21T09:31:52Z",
    request_summary: { limit: "20" },
    output_summary: { count: 6 },
  },
];

const EXAMPLE_ARGUMENTS: Record<string, string> = {
  validate_invoice_math: JSON.stringify(
    {
      tenantId: "tenant-demo",
      invoice_id: "INV-2048",
      line_items: [
        { description: "Advisory", quantity: "2", unit_price: "125.00" },
        { description: "Travel", quantity: "1", unit_price: "50.00" },
      ],
      reported_subtotal: "300.00",
      tax_rate: "0.20",
      reported_tax: "58.00",
      reported_total: "358.00",
    },
    null,
    2,
  ),
  evaluate_policy_compliance: JSON.stringify(
    {
      tenantId: "tenant-demo",
      amount: "840.00",
      approval_tier: "none",
      vat_registered: true,
      as_of_date: "2026-11-21",
      policy: { spend_limit: "1000.00", require_vat: true, sla_days: 30 },
    },
    null,
    2,
  ),
  query_audit_trail: JSON.stringify(
    { tenantId: "tenant-demo", limit: 20 },
    null,
    2,
  ),
};

function demoResult(toolName: string): Record<string, unknown> {
  if (toolName === "validate_invoice_math") {
    return {
      invoice_id: "INV-2048",
      pass_reconciliation: false,
      calculated_line_sum: "300.00",
      reported_subtotal: "300.00",
      calculated_tax: "60.00",
      reported_tax: "58.00",
      calculated_total: "360.00",
      reported_total: "358.00",
      findings: ["tax_amount_mismatch", "total_mismatch"],
      demo: true,
    };
  }
  if (toolName === "evaluate_policy_compliance") {
    return {
      tenant_id: "tenant-demo",
      compliant: true,
      approval_tier: "none",
      violations: [],
      demo: true,
    };
  }
  return {
    tenant_id: "tenant-demo",
    count: DEMO_RECORDS.length,
    records: DEMO_RECORDS,
    next_cursor: null,
    demo: true,
  };
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function isToolDefinition(value: unknown): value is ToolDefinition {
  const tool = objectValue(value);
  return (
    tool !== null &&
    typeof tool.name === "string" &&
    typeof tool.description === "string" &&
    (tool.inputSchema === undefined || objectValue(tool.inputSchema) !== null)
  );
}

function isAuditRecord(value: unknown): value is AuditRecord {
  const record = objectValue(value);
  return (
    record !== null &&
    (record.trace_id === undefined || typeof record.trace_id === "string") &&
    (record.tenantId === undefined || typeof record.tenantId === "string") &&
    (record.tool_name === undefined || typeof record.tool_name === "string") &&
    (record.status === undefined || typeof record.status === "string") &&
    (record.timestamp === undefined || typeof record.timestamp === "string") &&
    (record.duration_ms === undefined || typeof record.duration_ms === "number") &&
    (record.output_summary === undefined || objectValue(record.output_summary) !== null)
  );
}

function correlationId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `trace-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function formatTime(value: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function getFindings(record: AuditRecord): string[] {
  const output = record.output_summary;
  if (!output) return [];
  const findings = output.findings ?? output.violations;
  return Array.isArray(findings)
    ? findings.filter((item): item is string => typeof item === "string")
    : [];
}

function requestHeaders(
  authMode: AuthMode,
  authKey: string,
  traceId: string,
): Headers {
  const headers = new Headers({ "x-correlation-id": traceId });
  const key = authKey.trim();
  if (!key || authMode === "none") return headers;
  if (authMode === "function") headers.set("x-functions-key", key);
  if (authMode === "api") headers.set("x-api-key", key);
  if (authMode === "bearer") headers.set("Authorization", `Bearer ${key}`);
  return headers;
}

async function postRpc(
  endpoint: string,
  authMode: AuthMode,
  authKey: string,
  request: Record<string, unknown>,
  traceId: string,
): Promise<unknown> {
  const headers = requestHeaders(authMode, authKey, traceId);
  headers.set("Content-Type", "application/json");
  const response = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  const payload: unknown = await response.json();
  const envelope = objectValue(payload);
  if (!envelope) throw new Error("Invalid JSON-RPC response");
  if ("error" in envelope) {
    const error = objectValue(envelope.error);
    throw new Error(
      typeof error?.message === "string" ? error.message : "MCP request failed",
    );
  }
  return envelope.result;
}

function extractArguments(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  const args = objectValue(parsed);
  if (!args) throw new Error("Tool arguments must be a JSON object.");
  return args;
}

function App() {
  const [endpoint, setEndpoint] = useState("/api/mcp");
  const [authMode, setAuthMode] = useState<AuthMode>("none");
  const [authKey, setAuthKey] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("demo");
  const [tools, setTools] = useState<ToolDefinition[]>(DEMO_TOOLS);
  const [records, setRecords] = useState<AuditRecord[]>(DEMO_RECORDS);
  const [selectedTool, setSelectedTool] = useState(DEMO_TOOLS[0].name);
  const [argumentsText, setArgumentsText] = useState(
    EXAMPLE_ARGUMENTS[DEMO_TOOLS[0].name],
  );
  const [resultText, setResultText] = useState(
    JSON.stringify(demoResult(DEMO_TOOLS[0].name), null, 2),
  );
  const [filter, setFilter] = useState<FilterMode>("all");
  const [tenantFilter, setTenantFilter] = useState("tenant-demo");
  const [notice, setNotice] = useState(
    "Offline/local demo is active. Connect to a running MCP endpoint to use live tools.",
  );
  const [lastTraceId, setLastTraceId] = useState("demo-trace-8f31");
  const [isBusy, setIsBusy] = useState(false);

  const filteredRecords = useMemo(
    () =>
      records.filter((record) => {
        const status = (record.status || "").toLowerCase();
        const hasFindings = getFindings(record).length > 0;
        if (
          tenantFilter.trim() &&
          record.tenantId &&
          record.tenantId !== tenantFilter.trim()
        ) return false;
        if (filter === "success" && status !== "success") return false;
        if (filter === "error" && status !== "error") return false;
        if (filter === "findings" && !hasFindings) return false;
        return true;
      }),
    [filter, records, tenantFilter],
  );

  const findingCount = records.reduce(
    (count, record) => count + getFindings(record).length,
    0,
  );
  const successfulCount = records.filter(
    (record) => record.status === "success",
  ).length;
  const errorCount = records.filter((record) => record.status === "error").length;

  async function connect() {
    setIsBusy(true);
    setViewMode("connecting");
    const traceId = correlationId();
    try {
      const headers = requestHeaders(authMode, authKey, traceId);
      const discovery = await fetch(endpoint, {
        method: "GET",
        headers,
        cache: "no-store",
      });
      if (!discovery.ok) throw new Error(`Discovery failed (${discovery.status})`);

      await postRpc(
        endpoint,
        authMode,
        authKey,
        { jsonrpc: "2.0", id: "console-initialize", method: "initialize", params: {} },
        traceId,
      );
      const response = await postRpc(
        endpoint,
        authMode,
        authKey,
        { jsonrpc: "2.0", id: "console-tools", method: "tools/list", params: {} },
        traceId,
      );
      const payload = objectValue(response);
      const liveTools = payload?.tools;
      if (!Array.isArray(liveTools) || !liveTools.length || !liveTools.every(isToolDefinition)) {
        throw new Error("MCP tools/list returned an invalid response");
      }

      setTools(liveTools);
      setViewMode("connected");
      setNotice("Connected to the MCP endpoint. Calls are sent to the configured backend.");
      setLastTraceId(traceId);
    } catch {
      setTools(DEMO_TOOLS);
      setRecords(DEMO_RECORDS);
      setViewMode("demo");
      setNotice(
        "Backend unavailable or not authorized. Offline/local demo is active; demo actions send no requests.",
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function refreshAuditTrail() {
    if (viewMode !== "connected") {
      setRecords(DEMO_RECORDS);
      setNotice("Showing bundled offline/local demo audit events.");
      return;
    }

    setIsBusy(true);
    const traceId = correlationId();
    try {
      const response = await postRpc(
        endpoint,
        authMode,
        authKey,
        {
          jsonrpc: "2.0",
          id: traceId,
          method: "tools/call",
          params: {
            name: "query_audit_trail",
            arguments: { tenantId: tenantFilter, limit: 100 },
          },
        },
        traceId,
      );
      const data = objectValue(response);
      const auditRecords = data?.records;
      if (!Array.isArray(auditRecords)) {
        throw new Error("Audit query returned an invalid response");
      }
      setRecords(
        auditRecords.filter(isAuditRecord),
      );
      setLastTraceId(traceId);
      setNotice("Audit trail refreshed from the connected MCP server.");
    } catch {
      setNotice("Audit trail could not be refreshed. Check the endpoint and authorization.");
    } finally {
      setIsBusy(false);
    }
  }

  async function invokeTool() {
    let args: Record<string, unknown>;
    try {
      args = extractArguments(argumentsText);
    } catch {
      setNotice("Invalid tool arguments. Enter a valid JSON object and try again.");
      return;
    }

    const traceId = correlationId();
    setLastTraceId(traceId);
    setIsBusy(true);
    try {
      if (viewMode === "connected") {
        const response = await postRpc(
          endpoint,
          authMode,
          authKey,
          {
            jsonrpc: "2.0",
            id: traceId,
            method: "tools/call",
            params: { name: selectedTool, arguments: args },
          },
          traceId,
        );
        setResultText(JSON.stringify(response, null, 2));
        const tenantId =
          typeof args.tenantId === "string" ? args.tenantId : tenantFilter;
        setTenantFilter(tenantId);
        setNotice("Tool completed. Refresh the audit trail to inspect persisted events.");
      } else {
        const demo = demoResult(selectedTool);
        setResultText(JSON.stringify(demo, null, 2));
        const currentTime = new Date().toISOString();
        const demoRecord: AuditRecord = {
          trace_id: traceId,
          tenantId: "tenant-demo",
          tool_name: selectedTool,
          status: "success",
          duration_ms: 12,
          timestamp: currentTime,
          request_summary: { demo: true },
          output_summary: {
            findings:
              selectedTool === "validate_invoice_math"
                ? ["tax_amount_mismatch", "total_mismatch"]
                : [],
          },
        };
        setRecords((current) => [demoRecord, ...current]);
        setNotice("Demo result shown. No request was sent to a backend.");
      }
    } catch {
      setNotice("Tool call failed. Check the endpoint, authorization, and JSON-RPC configuration.");
    } finally {
      setIsBusy(false);
    }
  }

  function changeTool(toolName: string) {
    setSelectedTool(toolName);
    setArgumentsText(
      EXAMPLE_ARGUMENTS[toolName] ||
        JSON.stringify({ tenantId: tenantFilter }, null, 2),
    );
    setResultText("");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">A</div>
          <div>
            <span className="brand-kicker">MCP OPERATIONS</span>
            <strong>Control room</strong>
          </div>
        </div>
        <nav className="side-nav" aria-label="Primary">
          <a className="nav-item active" href="#overview"><span>◫</span> Overview</a>
          <a className="nav-item" href="#tool-inspector"><span>⌘</span> Tool inspector</a>
          <a className="nav-item" href="#audit-trail"><span>≋</span> Audit trail</a>
        </nav>
        <div className="sidebar-bottom">
          <span className="side-status"><i /> Deterministic engine</span>
          <span className="side-caption">Decimal-safe · Tenant-scoped</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs">Workspaces <span>/</span> Finance operations</div>
          <div className="topbar-right">
            <span className={`connection-pill ${viewMode}`}>
              <i />
              {viewMode === "connected"
                ? "Backend connected"
                : viewMode === "connecting"
                  ? "Connecting"
                  : "Local demo"}
            </span>
            <div className="avatar" aria-label="Local session">LO</div>
          </div>
        </header>

        <div className="page-wrap">
          <section className="page-heading" id="overview">
            <div>
              <p className="eyebrow">FINANCE OPERATIONS <span>•</span> MCP AUDIT SERVER</p>
              <h1>Audit &amp; reconciliation</h1>
              <p className="page-subtitle">
                Inspect deterministic decisions, invoke governed tools, and trace every operation.
              </p>
            </div>
            <div className="heading-meta">
              <span className="date-label">SESSION</span>
              <strong>Local workspace</strong>
            </div>
          </section>

          <section className={`mode-banner ${viewMode === "connected" ? "live" : "demo"}`} role="status">
            <span className="banner-icon">{viewMode === "connected" ? "✓" : "i"}</span>
            <div>
              <strong>{viewMode === "connected" ? "Live MCP connection" : "Offline / local demo mode"}</strong>
              <p>{notice}</p>
            </div>
            <button className="button button-subtle" onClick={() => void connect()} disabled={isBusy}>
              {viewMode === "connected" ? "Reconnect" : "Connect to backend"}
            </button>
          </section>

          <section className="kpi-grid" aria-label="Audit summary">
            <article className="kpi-card">
              <div className="kpi-top"><span>Audit events</span><span className="kpi-icon blue">≋</span></div>
              <strong>{records.length.toLocaleString()}</strong>
              <small>{viewMode === "connected" ? "Loaded from server" : "Bundled demo events"}</small>
            </article>
            <article className="kpi-card">
              <div className="kpi-top"><span>Successful</span><span className="kpi-icon green">✓</span></div>
              <strong>{successfulCount.toLocaleString()}</strong>
              <small>Recorded successful calls</small>
            </article>
            <article className="kpi-card">
              <div className="kpi-top"><span>Findings</span><span className="kpi-icon amber">!</span></div>
              <strong>{findingCount.toLocaleString()}</strong>
              <small>Deterministic findings surfaced</small>
            </article>
            <article className="kpi-card">
              <div className="kpi-top"><span>Errors</span><span className="kpi-icon red">×</span></div>
              <strong>{errorCount.toLocaleString()}</strong>
              <small>Recorded error events</small>
            </article>
          </section>

          <section className="workspace-grid">
            <article className="panel inspector-panel" id="tool-inspector">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">MCP TOOLING</p>
                  <h2>Tool inspector</h2>
                </div>
                <span className="tool-count">{tools.length} tools</span>
              </div>
              <div className="tool-select-row">
                <label htmlFor="tool-select">Select tool</label>
                <select
                  id="tool-select"
                  value={selectedTool}
                  onChange={(event) => changeTool(event.target.value)}
                >
                  {tools.map((tool) => (
                    <option key={tool.name} value={tool.name}>{tool.name}</option>
                  ))}
                </select>
              </div>
              <p className="tool-description">
                {tools.find((tool) => tool.name === selectedTool)?.description ||
                  "Tool description is not available."}
              </p>
              <label className="field-label" htmlFor="tool-arguments">Arguments <span>JSON</span></label>
              <textarea
                id="tool-arguments"
                className="code-input"
                value={argumentsText}
                onChange={(event) => setArgumentsText(event.target.value)}
                spellCheck={false}
                aria-describedby="argument-help"
              />
              <div className="editor-footer">
                <span id="argument-help">Use decimal strings for monetary values.</span>
                <button className="button button-primary" onClick={() => void invokeTool()} disabled={isBusy}>
                  {isBusy ? "Working…" : "Run tool"} <span aria-hidden="true">→</span>
                </button>
              </div>
              <div className="result-block">
                <div className="result-heading">
                  <span>Structured response</span>
                  <span className="response-type">JSON</span>
                </div>
                <pre>{resultText || "Run a tool to inspect its structured response."}</pre>
              </div>
              <div className="trace-row">
                <span>Correlation / trace ID</span>
                <code>{lastTraceId}</code>
              </div>
            </article>

            <article className="panel connection-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">SESSION CONFIGURATION</p>
                  <h2>Backend connection</h2>
                </div>
                <span className="lock-icon" aria-label="Credentials are not saved">⌑</span>
              </div>
              <p className="panel-intro">
                Credentials stay in this tab’s React state and are never written to browser storage.
              </p>
              <label className="field-label" htmlFor="endpoint">MCP HTTP endpoint</label>
              <input
                id="endpoint"
                className="text-input"
                value={endpoint}
                onChange={(event) => setEndpoint(event.target.value)}
                autoComplete="url"
                spellCheck={false}
              />
              <label className="field-label" htmlFor="auth-mode">Authorization type</label>
              <select
                id="auth-mode"
                className="text-input"
                value={authMode}
                onChange={(event) => setAuthMode(event.target.value as AuthMode)}
              >
                <option value="none">No key</option>
                <option value="function">Azure Functions key</option>
                <option value="api">API key (x-api-key)</option>
                <option value="bearer">Bearer token</option>
              </select>
              <label className="field-label" htmlFor="auth-key">Session key / token</label>
              <input
                id="auth-key"
                className="text-input"
                type="password"
                value={authKey}
                onChange={(event) => setAuthKey(event.target.value)}
                autoComplete="new-password"
                spellCheck={false}
                placeholder="Enter only for this browser tab"
              />
              <div className="security-note">
                <span aria-hidden="true">◇</span>
                <p>Cleared when this page is closed or refreshed. Never paste production credentials into a shared device.</p>
              </div>
              <div className="connection-meta">
                <span>Transport</span><strong>JSON-RPC 2.0 over HTTPS</strong>
                <span>Trace header</span><code>x-correlation-id</code>
                <span>Demo actions</span><strong>Local only · no network requests</strong>
              </div>
            </article>
          </section>

          <section className="panel audit-panel" id="audit-trail">
            <div className="audit-heading">
              <div>
                <p className="eyebrow">GOVERNANCE &amp; OBSERVABILITY</p>
                <h2>Audit event stream</h2>
                <p className="panel-intro">Tenant-scoped records with trace IDs and deterministic findings.</p>
              </div>
              <button className="button button-outline" onClick={() => void refreshAuditTrail()} disabled={isBusy}>
                Refresh audit trail
              </button>
            </div>
            <div className="audit-toolbar">
              <label className="tenant-filter">
                <span>Tenant</span>
                <input
                  value={tenantFilter}
                  onChange={(event) => setTenantFilter(event.target.value)}
                  aria-label="Filter by tenant ID"
                />
              </label>
              <label className="filter-select">
                <span>Show</span>
                <select value={filter} onChange={(event) => setFilter(event.target.value as FilterMode)}>
                  <option value="all">All events</option>
                  <option value="success">Successful</option>
                  <option value="error">Errors</option>
                  <option value="findings">With findings</option>
                </select>
              </label>
              <span className="event-count">{filteredRecords.length} events</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Operation</th>
                    <th>Status</th>
                    <th>Findings</th>
                    <th>Trace ID</th>
                    <th>Duration</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRecords.map((record, index) => {
                    const findings = getFindings(record);
                    return (
                      <tr key={`${record.trace_id || "event"}-${index}`}>
                        <td>
                          <strong className="operation-name">{record.tool_name || "Unknown tool"}</strong>
                          <small>{record.tenantId || "Tenant unavailable"}</small>
                        </td>
                        <td>
                          <span className={`status-tag ${(record.status || "unknown").toLowerCase()}`}>
                            <i /> {record.status || "unknown"}
                          </span>
                        </td>
                        <td>
                          {findings.length ? (
                            <div className="finding-tags">
                              {findings.map((finding) => <span className="finding-tag" key={finding}>{finding}</span>)}
                            </div>
                          ) : <span className="muted">—</span>}
                        </td>
                        <td><code className="trace-cell">{record.trace_id || "—"}</code></td>
                        <td>{typeof record.duration_ms === "number" ? `${record.duration_ms} ms` : "—"}</td>
                        <td>{formatTime(record.timestamp)}</td>
                      </tr>
                    );
                  })}
                  {!filteredRecords.length && (
                    <tr><td className="empty-row" colSpan={6}>No events match this filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {viewMode === "demo" && (
              <div className="demo-footnote">
                Sample records are illustrative local fixtures, not backend audit data.
              </div>
            )}
          </section>
          <footer className="page-footer">
            <span>Remote MCP Tool Server</span>
            <span>Deterministic by design <i /> Session-only credentials</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
