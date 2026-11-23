import { useEffect, useMemo, useState } from "react";
import {
  HomePage,
  DocumentsPage,
  ContactPage,
  ProfilePage,
  ReconFlowWordmark,
  RequestDetailPage,
  RequestsPage,
  ServiceDetailPage,
  ServicesPage,
  WelcomePage,
} from "./WorkspacePages";
import {
  DemoLandingPage,
  DemoRequestPage,
  DemoRequestsPage,
  DemoServicePage,
} from "./DemoWorkflow";
import {
  ControlRoomAuditTrail,
  ControlRoomOverview,
  ControlRoomToolkit,
  useControlRoomAuditData,
} from "./ControlRoomAudit";
import {
  isDemoServiceId,
  WORKFLOW_PLANS,
  createWorkspaceRequest,
  getService,
  readWorkspaceRequests,
  saveWorkspaceRequests,
  type WorkspaceRequest,
} from "./workspace";

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
  request_id?: string;
  request_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
};

type AuthMode = "none" | "function" | "api" | "bearer";
type ViewMode = "demo" | "connected" | "connecting";
type FilterMode = "all" | "success" | "error" | "findings";
type ControlRoomRoute = "overview" | "tool-inspector" | "audit-trail" | "documents";
type AppRoute =
  | { kind: "welcome" }
  | { kind: "home" }
  | { kind: "contact" }
  | { kind: "profile" }
  | { kind: "services" }
  | { kind: "service"; serviceId: string }
  | { kind: "requests" }
  | { kind: "request"; requestId: string }
  | { kind: "demo" }
  | { kind: "demo-service"; serviceId: string }
  | { kind: "demo-requests" }
  | { kind: "demo-request"; requestId: string; findingId?: string }
  | { kind: "control-room"; page: ControlRoomRoute; requestId?: string };

function routeFromHash(hash: string): AppRoute {
  const [rawPath = "", query = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const path = rawPath.replace(/\/+$/, "");
  const segments = path.split("/");
  if (!path || path === "welcome") return { kind: "welcome" };
  if (path === "contact") return { kind: "contact" };
  if (path === "profile") return { kind: "profile" };
  if (path === "home") return { kind: "home" };
  if (path === "services") return { kind: "services" };
  if (segments[0] === "services" && segments[1]) {
    return { kind: "service", serviceId: segments[1] };
  }
  if (path === "requests") return { kind: "requests" };
  if (segments[0] === "requests" && segments[1]) {
    return { kind: "request", requestId: segments[1] };
  }
  if (path === "demo") return { kind: "demo" };
  if (path === "demo/requests") return { kind: "demo-requests" };
  if (segments[0] === "demo" && segments[1] === "requests" && segments[2]) {
    const findingId = new URLSearchParams(query).get("finding") || undefined;
    return { kind: "demo-request", requestId: segments[2], findingId };
  }
  if (segments[0] === "demo" && segments[1]) {
    return { kind: "demo-service", serviceId: segments[1] };
  }
  if (segments[0] === "control-room") {
    const page = segments[1];
    const controlRoomPage: ControlRoomRoute =
      page === "tool-inspector"
        ? "tool-inspector"
        : page === "audit-trail"
          ? "audit-trail"
          : page === "documents"
            ? "documents"
            : "overview";
    const requestId = new URLSearchParams(query).get("request") || undefined;
    return { kind: "control-room", page: controlRoomPage, requestId };
  }
  return { kind: "welcome" };
}

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
    (record.request_id === undefined || typeof record.request_id === "string") &&
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

function describeError(error: unknown, fallback: string): string {
  if (!(error instanceof Error) || !error.message.trim()) return fallback;
  return error.message.replace(/[\r\n]+/g, " ").slice(0, 240);
}

function App() {
  const [route, setRoute] = useState<AppRoute>(() =>
    routeFromHash(window.location.hash),
  );
  const controlRoomAuditData = useControlRoomAuditData(route.kind === "control-room");
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [requestStore, setRequestStore] = useState(readWorkspaceRequests);
  const requests = requestStore.requests;
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

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const updateRoute = () => {
      const nextRoute = routeFromHash(window.location.hash);
      setRoute(nextRoute);
      if (nextRoute.kind === "request") {
        setRequestStore((current) => {
          if (!current.requests.some((request) => request.id === nextRoute.requestId)) {
            return current;
          }
          const openedAt = new Date().toISOString();
          const nextRequests = current.requests.map((request) =>
            request.id === nextRoute.requestId
              ? { ...request, lastOpenedAt: openedAt }
              : request,
          );
          const warning = saveWorkspaceRequests(nextRequests);
          return { requests: nextRequests, warning };
        });
      }
    };
    if (!window.location.hash) {
      window.location.hash = "/welcome";
    } else {
      updateRoute();
    }
    window.addEventListener("hashchange", updateRoute);
    return () => window.removeEventListener("hashchange", updateRoute);
  }, []);

  function persistRequests(nextRequests: WorkspaceRequest[]) {
    const warning = saveWorkspaceRequests(nextRequests);
    setRequestStore({ requests: nextRequests, warning });
  }

  function startRequest(serviceId: string) {
    if (isDemoServiceId(serviceId)) {
      window.location.hash = `/demo/${serviceId}`;
      return;
    }
    const request = createWorkspaceRequest(
      serviceId,
      new Date().toISOString(),
      `request-${correlationId().slice(0, 8)}`,
    );
    persistRequests([request, ...requests]);
    window.location.hash = `/requests/${request.id}`;
  }

  function completeRequestStep(requestId: string) {
    const request = requests.find((item) => item.id === requestId);
    const service = request ? getService(request.serviceId) : undefined;
    if (!request || !service) return;
    const steps = WORKFLOW_PLANS[service.workflow].steps;
    if (request.completedSteps >= steps.length) return;

    const occurredAt = new Date().toISOString();
    const action = `Checkpoint completed: ${steps[request.completedSteps]}`;
    const updatedRequest: WorkspaceRequest = {
      ...request,
      completedSteps: request.completedSteps + 1,
      updatedAt: occurredAt,
      activity: [...request.activity, { action, occurredAt }],
    };
    persistRequests(
      requests.map((item) => (item.id === requestId ? updatedRequest : item)),
    );
  }

  function deleteRequest(requestId: string) {
    if (!window.confirm("Delete this request and its browser-stored progress?")) return;
    persistRequests(requests.filter((request) => request.id !== requestId));
    if (route.kind === "request" && route.requestId === requestId) {
      window.location.hash = "/requests";
    }
  }

  const workflowRecords = useMemo(
    () =>
      requests.flatMap((request) => {
        const service = getService(request.serviceId);
        if (!service) return [];
        return request.activity.map((activity, index): AuditRecord => ({
          trace_id: `${request.id}-activity-${index + 1}`,
          request_id: request.id,
          tool_name: activity.action === "Request created"
            ? "workspace.request_created"
            : "workspace.checkpoint_completed",
          status: "success",
          duration_ms: 0,
          timestamp: activity.occurredAt,
          request_summary: {
            service: service.title,
            action: activity.action,
          },
          output_summary: { findings: [] },
        }));
      }),
    [requests],
  );
  const auditRecords = useMemo(
    () => [...records, ...workflowRecords],
    [records, workflowRecords],
  );
  const requestFilter =
    route.kind === "control-room" && route.page === "audit-trail"
      ? route.requestId
      : undefined;

  const filteredRecords = useMemo(
    () =>
      auditRecords.filter((record) => {
        const status = (record.status || "").toLowerCase();
        const hasFindings = getFindings(record).length > 0;
        if (requestFilter && record.request_id !== requestFilter) return false;
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
    [auditRecords, filter, requestFilter, tenantFilter],
  );

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
    } catch (error) {
      setTools(DEMO_TOOLS);
      setRecords(DEMO_RECORDS);
      setViewMode("demo");
      setNotice(
        `Connection failed: ${describeError(error, "Unknown connection error.")}. Offline/local demo is active; demo actions send no requests.`,
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
    } catch (error) {
      setNotice(
        `Audit trail could not be refreshed: ${describeError(error, "Unknown error.")}`,
      );
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
    } catch (error) {
      setNotice(
        `Tool call failed: ${describeError(error, "Unknown error.")}`,
      );
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

  function signOut() {
    setProfileMenuOpen(false);
    setAuthMode("none");
    setAuthKey("");
    setViewMode("demo");
    setTools(DEMO_TOOLS);
    setRecords(DEMO_RECORDS);
    setArgumentsText(EXAMPLE_ARGUMENTS[DEMO_TOOLS[0].name]);
    setResultText(JSON.stringify(demoResult(DEMO_TOOLS[0].name), null, 2));
    setLastTraceId("demo-trace-8f31");
    setNotice("Offline/local demo is active. Connect to a running MCP endpoint to use live tools.");
    window.location.hash = "/";
  }

  const controlRoomPage = route.kind === "control-room" ? route.page : undefined;
  const selectedService =
    route.kind === "service" ? getService(route.serviceId) : undefined;
  const selectedRequest =
    route.kind === "request"
      ? requests.find((request) => request.id === route.requestId)
      : undefined;
  const requestService = selectedRequest
    ? getService(selectedRequest.serviceId)
    : undefined;
  const pageTitle =
    controlRoomPage === "documents"
      ? "Documents"
      : controlRoomPage === "tool-inspector"
      ? "Audit toolkit & MCP tools"
      : controlRoomPage === "audit-trail"
        ? "Audit trail"
        : "Audit & reconciliation";
  const pageSubtitle =
    controlRoomPage === "documents"
      ? "Review files linked to requests and source activity."
      : controlRoomPage === "tool-inspector"
      ? "Run the implemented ledger checks, or use the separate MCP inspector for JSON-RPC tools."
      : controlRoomPage === "audit-trail"
        ? "Review CAATs audit runs and findings separately from MCP tool events and traces."
        : "Inspect deterministic decisions, invoke governed tools, and trace every operation.";
  const breadcrumbs =
    route.kind === "control-room"
      ? `Control Room / ${route.page === "overview" ? "Overview" : pageTitle}`
      : route.kind === "contact"
        ? "Contact us"
        : route.kind === "profile"
          ? "User profile"
      : route.kind === "home"
        ? "Home"
        : route.kind === "requests"
          ? "Requests"
          : route.kind === "request"
            ? `Requests / ${route.requestId}`
              : route.kind === "demo"
                ? "Local audit demos"
                : route.kind === "demo-service"
                  ? `Local audit demos / ${getService(route.serviceId)?.title || "Service not found"}`
                  : route.kind === "demo-requests"
                    ? "Local audit demos / Requests"
                    : route.kind === "demo-request"
                      ? `Local audit demos / ${route.requestId}`
            : route.kind === "services"
              ? "Services"
              : route.kind === "service"
                ? `Services / ${selectedService?.title || "Service not found"}`
                : "Workspace";

  if (route.kind === "welcome") {
    return <WelcomePage onContinue={() => { window.location.hash = "/home"; }} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#/home">
          <div className="brand-mark" aria-hidden="true">
            <img src="/reconflow-mark.svg" alt="" />
          </div>
          <div className="brand-copy">
            <span>WELCOME TO RECONFLOW</span>
            <strong>Auditor Workspace</strong>
          </div>
        </a>
        <nav className="side-nav" aria-label="Primary">
          <a
            className={`nav-item ${route.kind === "home" ? "active" : ""}`}
            href="#/home"
            aria-current={route.kind === "home" ? "page" : undefined}
          >
            <span>⌂</span> Home
          </a>
          <a
            className={`nav-item ${route.kind === "requests" || route.kind === "request" ? "active" : ""}`}
            href="#/requests"
            aria-current={route.kind === "requests" || route.kind === "request" ? "page" : undefined}
          >
            <span>▤</span> Requests
          </a>
          <a
            className={`nav-item ${route.kind === "services" || route.kind === "service" ? "active" : ""}`}
            href="#/services"
            aria-current={route.kind === "services" ? "page" : undefined}
          >
            <span>◇</span> Services
          </a>
          <a
            className={`nav-item ${route.kind === "demo" || route.kind === "demo-service" || route.kind === "demo-requests" || route.kind === "demo-request" ? "active" : ""}`}
            href="#/demo"
            aria-current={route.kind === "demo" || route.kind === "demo-service" || route.kind === "demo-requests" || route.kind === "demo-request" ? "page" : undefined}
          >
            <span>◉</span> Ledger demos
          </a>
          <div className="sidebar-control-room">
            <a
              className={`nav-item ${route.kind === "control-room" ? "active" : ""}`}
              href="#/control-room/overview"
              aria-current={route.kind === "control-room" && route.page === "overview" ? "page" : undefined}
            >
              <span>▣</span> Control Room
            </a>
            <div className="control-room-subnav">
              <a
                className={controlRoomPage === "overview" ? "active" : ""}
                href="#/control-room/overview"
                aria-current={controlRoomPage === "overview" ? "page" : undefined}
              >
                Overview
              </a>
              <a
                className={controlRoomPage === "tool-inspector" ? "active" : ""}
                href="#/control-room/tool-inspector"
                aria-current={controlRoomPage === "tool-inspector" ? "page" : undefined}
              >
                Toolkit &amp; MCP
              </a>
              <a
                className={controlRoomPage === "audit-trail" ? "active" : ""}
                href="#/control-room/audit-trail"
                aria-current={controlRoomPage === "audit-trail" ? "page" : undefined}
              >
                Audit trail
              </a>
              <a
                className={controlRoomPage === "documents" ? "active" : ""}
                href="#/control-room/documents"
                aria-current={controlRoomPage === "documents" ? "page" : undefined}
              >
                Documents
              </a>
            </div>
          </div>
        </nav>
        <div className="sidebar-bottom">
          <span className="side-status"><i /> Guest preview</span>
          <span className="side-caption">No account or client data required</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs">{breadcrumbs}</div>
          <div className="topbar-right">
            <button
              className="theme-toggle"
              type="button"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              aria-pressed={theme === "dark"}
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "Light mode" : "Dark mode"}
            </button>
            {route.kind === "control-room" ? (
              <span className={`connection-pill ${viewMode}`}>
                <i />
                {viewMode === "connected"
                  ? "Backend connected"
                  : viewMode === "connecting"
                    ? "Connecting"
                    : "Local demo"}
              </span>
            ) : (
              <span className="connection-pill demo"><i /> Guest preview</span>
            )}
            <a className="contact-link" href="#/contact">Contact us</a>
            <div
              className="topbar-profile"
              onMouseEnter={() => setProfileMenuOpen(true)}
              onMouseLeave={(event) => {
                if (!event.currentTarget.contains(document.activeElement)) {
                  setProfileMenuOpen(false);
                }
              }}
              onFocus={() => setProfileMenuOpen(true)}
              onBlur={(event) => {
                if (
                  !(event.relatedTarget instanceof Node) ||
                  !event.currentTarget.contains(event.relatedTarget)
                ) {
                  setProfileMenuOpen(false);
                }
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") setProfileMenuOpen(false);
              }}
            >
              <button
                className="topbar-profile-trigger"
                type="button"
                aria-expanded={profileMenuOpen}
                aria-controls="topbar-account-menu"
                onClick={() => setProfileMenuOpen(true)}
              >
                <span className="avatar" aria-hidden="true">G</span>
                <span>Guest profile</span>
              </button>
              {profileMenuOpen && (
                <div className="topbar-profile-menu" id="topbar-account-menu">
                  <a href="#/profile" onClick={() => setProfileMenuOpen(false)}>Profile</a>
                  <button type="button" onClick={signOut}>Sign out</button>
                </div>
              )}
            </div>
            <ReconFlowWordmark />
          </div>
        </header>

        <div className={route.kind === "contact" ? "page-wrap contact-page-wrap" : "page-wrap"}>
          {requestStore.warning && (
            <p className="workspace-notice" role="status">{requestStore.warning}</p>
          )}

          {route.kind === "home" && <HomePage requests={requests} />}
          {route.kind === "contact" && <ContactPage />}
          {route.kind === "profile" && <ProfilePage />}
          {route.kind === "services" && <ServicesPage />}
          {route.kind === "service" && selectedService && (
            <ServiceDetailPage service={selectedService} onStartRequest={startRequest} />
          )}
          {route.kind === "service" && !selectedService && (
            <section className="panel workspace-not-found">
              <h1>Service not found</h1>
              <p>Choose an available service from the catalog.</p>
              <a className="button button-primary" href="#/services">Browse services</a>
            </section>
          )}
          {route.kind === "demo" && <DemoLandingPage />}
          {route.kind === "demo-service" && <DemoServicePage serviceId={route.serviceId} />}
          {route.kind === "demo-requests" && <DemoRequestsPage />}
          {route.kind === "demo-request" && (
            <DemoRequestPage requestId={route.requestId} findingId={route.findingId} />
          )}
          {route.kind === "requests" && (
            <RequestsPage requests={requests} onDeleteRequest={deleteRequest} />
          )}
          {route.kind === "request" && selectedRequest && requestService && (
            <RequestDetailPage
              request={selectedRequest}
              service={requestService}
              onCompleteStep={completeRequestStep}
            />
          )}
          {route.kind === "request" && (!selectedRequest || !requestService) && (
            <section className="panel workspace-not-found">
              <h1>Request not found</h1>
              <p>This request is not available in the current browser workspace.</p>
              <a className="button button-primary" href="#/requests">View requests</a>
            </section>
          )}

          {route.kind === "control-room" && route.page === "documents" && (
            <DocumentsPage requests={requests} />
          )}

          {route.kind === "control-room" && route.page !== "documents" && (
            <>
              <section className="page-heading">
                <div>
                  <p className="eyebrow">FINANCE OPERATIONS <span>•</span> MCP AUDIT SERVER</p>
                  <h1>{pageTitle}</h1>
                  <p className="page-subtitle">{pageSubtitle}</p>
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
            </>
          )}

          {route.kind === "control-room" && route.page === "overview" && (
            <>
              <ControlRoomOverview data={controlRoomAuditData} />
              <section className="control-room-cards" aria-label="Control Room pages">
                <a className="panel control-room-card" href="#/control-room/tool-inspector">
                  <span className="eyebrow">AUDIT TOOLKIT &amp; MCP</span>
                  <h2>Audit toolkit and MCP inspector</h2>
                  <p>Run a supported ledger assessment or inspect the separate MCP JSON-RPC tools.</p>
                  <span className="card-link">Open toolkit &amp; MCP <span aria-hidden="true">→</span></span>
                </a>
                <a className="panel control-room-card" href="#/control-room/audit-trail">
                  <span className="eyebrow">AUDIT &amp; OBSERVABILITY</span>
                  <h2>Audit trail</h2>
                  <p>Review saved CAATs findings, linked requests, MCP events, errors, and traces.</p>
                  <span className="card-link">Review runs and events <span aria-hidden="true">→</span></span>
                </a>
              </section>
            </>
          )}

          {route.kind === "control-room" && route.page === "tool-inspector" && (
            <>
            <ControlRoomToolkit data={controlRoomAuditData} />
            <section className="workspace-grid">
            <article className="panel inspector-panel" id="tool-inspector">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">SEPARATE MCP JSON-RPC INTERFACE</p>
                  <h2>MCP tool inspector</h2>
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
            </>
          )}

          {route.kind === "control-room" && route.page === "audit-trail" && (
            <>
            <ControlRoomAuditTrail data={controlRoomAuditData} requestFilter={requestFilter} />
            <section className="panel audit-panel" id="audit-trail">
            <div className="audit-heading">
              <div>
                <p className="eyebrow">MCP OBSERVABILITY</p>
                <h2>MCP tool event stream</h2>
                <p className="panel-intro">MCP server calls and local workspace checkpoints. CAATs findings are listed separately above.</p>
              </div>
              <button className="button button-outline" onClick={() => void refreshAuditTrail()} disabled={isBusy}>
                Refresh audit trail
              </button>
            </div>
            {requestFilter && (
              <div className="request-filter-notice">
                <span>Showing activity for request {requestFilter}</span>
                <a href="#/control-room/audit-trail">Clear request filter</a>
              </div>
            )}
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
                          {record.request_id ? (
                            <small>
                              <a href={`#/requests/${record.request_id}`}>Request {record.request_id}</a>
                            </small>
                          ) : (
                            <small>{record.tenantId || "Tenant unavailable"}</small>
                          )}
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
                Sample records and request checkpoints are illustrative local prototype data, not immutable server audit records.
              </div>
            )}
            {viewMode === "connected" && workflowRecords.length > 0 && (
              <div className="demo-footnote">
                Request checkpoints are stored locally in this prototype and are not part of the server audit log.
              </div>
            )}
            </section>
            </>
          )}
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
