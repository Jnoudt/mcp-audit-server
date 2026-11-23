import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import {
  DEMO_SERVICE_IDS,
  getService,
  type DemoServiceId,
} from "./workspace";

type DemoDocument = {
  id: string;
  fileName: string;
  sizeBytes: number;
  createdAt: string;
  importId: string | null;
  ledgerType: string | null;
  rowCount: number | null;
  sourceSystem: string | null;
  columnMap: {
    sourceName: string;
    canonicalName: string | null;
    inferredType: string;
    analysisAllowed: boolean;
  }[];
};

type DemoFinding = {
  id: string;
  importId: string;
  documentId: string;
  sourceRowNumber: number | null;
  ruleCode: string;
  severity: string;
  title: string;
  description: string;
  recommendation: string;
  evidence: Record<string, string | number>;
  disposition: { status: string; note: string; createdAt: string } | null;
};

type DemoMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  modelDeployment: string;
  promptTokens: number | null;
  completionTokens: number | null;
  createdAt: string;
};

type DemoRun = {
  id: string;
  status: string;
  ruleVersion: string;
  createdAt: string;
  summary: {
    source_count: number;
    rows_analyzed: number;
    finding_count: number;
    by_rule: Record<string, number>;
    by_severity: Record<string, number>;
    limitations: string[];
  };
  findings: DemoFinding[];
  aiMessages: DemoMessage[];
};

type DemoRequest = {
  id: string;
  serviceId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  assessment: Record<string, string>;
  documents: DemoDocument[];
  latestRun: DemoRun | null;
};

type DemoRequestSummary = {
  id: string;
  serviceId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
};

type SampleFile = {
  id: string;
  fileName: string;
  sourceSystem: string;
  ledgerType: string;
  rowCount: number;
};

type AIStatus = {
  enabled: boolean;
  configured: boolean;
  ready: boolean;
  provider: string;
  message: string;
};

type Assessment = Record<string, string>;
type AssessmentField = {
  key: string;
  label: string;
  type: "date" | "number";
  required: boolean;
  options?: string[];
  help?: string;
};

type DemoRequestBusyAction =
  | "importing-samples"
  | "uploading-files"
  | "saving-assessment"
  | "running-audit"
  | "requesting-ai";

const ERP_SOURCES = [
  "Unspecified",
  "SAP S/4HANA",
  "Oracle NetSuite",
  "Xero",
  "Sage Intacct",
  "Microsoft Dynamics 365",
  "QuickBooks Online",
];

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "";
const API_ROOT = `${API_BASE_URL}/api/demo`;
const API_MODE_LABEL = API_BASE_URL ? "Hosted API" : "Local API";
const STORAGE_NOTICE = API_BASE_URL
  ? "Connected to the hosted API. Requests and files currently use instance-local SQLite/files, not Azure SQL; a restart or scale-out may make them unavailable. Use synthetic data only."
  : "Requests and files stay on this machine in local SQLite and uploads. Do not use client or personal data.";

function LoadingStatus({ label, className = "" }: { label: string; className?: string }) {
  return (
    <div className={`loading-status ${className}`.trim()} role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, cache: "no-store" });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The demo API returned an unreadable response (${response.status}).`);
  }
  if (!response.ok) {
    const error = isRecord(payload) && typeof payload.error === "string"
      ? payload.error
      : `Request failed (${response.status}).`;
    throw new Error(error);
  }
  if (!isRecord(payload)) throw new Error("The demo API returned an invalid response.");
  return payload as T;
}

function requestPath(requestId: string): string {
  return `${API_ROOT}/requests/${encodeURIComponent(requestId)}`;
}

function initialAssessment(serviceId: DemoServiceId): Assessment {
  const common = {
    period_start: "2026-01-01",
    period_end: "2026-12-31",
    currency: "ZAR",
  };
  if (serviceId === "journal-entry-analytics") {
    return {
      ...common,
      approval_threshold: "50000",
      round_amount_quantum: "10000",
      round_amount_minimum: "100000",
    };
  }
  if (serviceId === "invoice-integrity-review") {
    return { ...common, approval_threshold: "50000" };
  }
  return { ...common, asset_snapshot_date: "2026-12-31" };
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function serviceTitle(serviceId: string): string {
  return getService(serviceId)?.title || "Audit service";
}

function downloadAuditRun(request: DemoRequest) {
  if (!request.latestRun) return;
  const contents = JSON.stringify(
    {
      requestId: request.id,
      serviceId: request.serviceId,
      assessment: request.assessment,
      sourceFiles: request.documents.map(({ fileName, ledgerType, rowCount, sourceSystem }) => ({
        fileName,
        ledgerType,
        rowCount,
        sourceSystem,
      })),
      run: request.latestRun,
    },
    null,
    2,
  );
  const downloadUrl = URL.createObjectURL(
    new Blob([contents], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = `reconflow-${request.serviceId}-${request.latestRun.id.slice(0, 8)}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
}

export function DemoLandingPage() {
  return (
    <div className="workspace-page demo-workflow-page">
      <section className="welcome-hero">
        <div>
          <p className="eyebrow">SYNTHETIC-DATA AUDIT DEMO</p>
          <h1>Run an audit workflow</h1>
          <p>
            Choose a service, import files from the bundled ERP test pack or upload your own
            synthetic CSVs, answer the scope questions, then review real deterministic results.
          </p>
        </div>
        <a className="button button-outline" href="#/demo/requests">Request history</a>
      </section>

      <div className="demo-safety-note" role="note">
        <strong>{API_MODE_LABEL} · storage boundary</strong>
        <span>{STORAGE_NOTICE} AI is off unless separately configured and explicitly confirmed.</span>
      </div>

      <section className="workspace-section">
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">THREE RUNNABLE SERVICES</p>
            <h2>Select a workflow</h2>
          </div>
        </div>
        <div className="service-card-grid">
          {DEMO_SERVICE_IDS.map((serviceId) => {
            const service = getService(serviceId);
            if (!service) return null;
            return (
              <a className="service-card panel" href={`#/demo/${service.id}`} key={service.id}>
                <span className="service-card-group">Demo-ready</span>
                <h3>{service.title}</h3>
                <p>{service.summary}</p>
                <span className="card-link">Start assessment <span aria-hidden="true">→</span></span>
              </a>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export function DemoServicePage({ serviceId }: { serviceId: string }) {
  const service = getService(serviceId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function createRequest() {
    if (!service || !DEMO_SERVICE_IDS.includes(service.id as DemoServiceId)) return;
    setBusy(true);
    setError("");
    try {
      const result = await fetchJSON<DemoRequest>(`${API_ROOT}/requests`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ serviceId: service.id }),
      });
      window.location.hash = `/demo/requests/${encodeURIComponent(result.id)}`;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the demo request.");
    } finally {
      setBusy(false);
    }
  }

  if (!service || !DEMO_SERVICE_IDS.includes(service.id as DemoServiceId)) {
    return <NotFound title="Demo service not found" />;
  }

  return (
    <div className="workspace-page demo-workflow-page">
      <a className="back-link" href="#/demo">← All demo services</a>
      <section className="service-detail-hero">
        <div>
          <p className="eyebrow">AUDIT DEMO WORKFLOW</p>
          <h1>{service.title}</h1>
          <p className="service-detail-summary">{service.summary}</p>
        </div>
        <span className="prototype-tag">Demo-ready</span>
      </section>
      <div className="service-detail-grid">
        <section className="panel workflow-panel">
          <p className="eyebrow">HOW THE DEMO WORKS</p>
          <ol className="workflow-list">
            <li><span className="workflow-number">1</span><span>Select test-pack samples or upload synthetic CSVs.</span></li>
            <li><span className="workflow-number">2</span><span>Set the audit period and applicable service parameters.</span></li>
            <li><span className="workflow-number">3</span><span>Click Run Audit Assessment to run deterministic rules; each finding links to its source file and row.</span></li>
            <li><span className="workflow-number">4</span><span>Record accept, reject, or follow-up dispositions with reviewer notes.</span></li>
            <li><span className="workflow-number">5</span><span>Optionally request a summary-only AI draft from an already configured Foundry deployment.</span></li>
          </ol>
          <div className="workflow-output">
            <strong>Evidence boundary</strong>
            <p>
              The application does not send ground-truth tags to the detectors. Screening flags are
              candidates, not proof of fraud, cutoff error, negative on-hand stock, or a control breach.
            </p>
          </div>
        </section>
        <aside className="panel service-requirements">
          <p className="eyebrow">SUPPORTED INPUTS</p>
          <h2>Before you start</h2>
          <ul className="requirement-list">
            {service.requirements.map((requirement) => (
              <li key={requirement}><span aria-hidden="true">✓</span>{requirement}</li>
            ))}
          </ul>
          <div className="demo-safety-note compact">
            <strong>Demo identity</strong>
            <span>This preview uses a fixed demo owner, not customer sign-in or tenant authorization.</span>
          </div>
          {error && <p className="workspace-notice" role="alert">{error}</p>}
          <button className="button button-primary start-request-button" onClick={() => void createRequest()} disabled={busy} aria-busy={busy}>
            {busy && <span className="loading-spinner" aria-hidden="true" />}
            {busy ? "Creating…" : "Create demo request"} <span aria-hidden="true">→</span>
          </button>
          <a className="demo-guide-link" href={`#/services/${service.id}`}>Read service guide</a>
        </aside>
      </div>
    </div>
  );
}

export function DemoRequestsPage() {
  const [requests, setRequests] = useState<DemoRequestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void fetchJSON<{ requests: DemoRequestSummary[] }>(`${API_ROOT}/requests`)
      .then((result) => {
        if (active) setRequests(result.requests);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load requests.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  return (
    <div className="workspace-page demo-workflow-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">{API_MODE_LABEL.toUpperCase()}</p>
          <h1>Demo requests</h1>
          <p className="page-subtitle">Requests, assessments, uploaded files, runs, and reviews for the synthetic-data demo.</p>
        </div>
        <a className="button button-primary" href="#/demo">New audit request</a>
      </section>
      {error && <p className="workspace-notice" role="alert">{error}</p>}
      {loading ? (
        <LoadingStatus label="Loading demo requests…" className="page-loading" />
      ) : requests.length ? (
        <section className="request-list" aria-label="Demo requests">
          {requests.map((request) => (
            <article className="panel request-card" key={request.id}>
              <div className="request-card-top">
                <div>
                  <span className="service-card-group">Demo</span>
                  <h2><a href={`#/demo/requests/${encodeURIComponent(request.id)}`}>{serviceTitle(request.serviceId)}</a></h2>
                  <p>Request {request.id}</p>
                </div>
                <span className={`request-status ${request.status === "completed" ? "complete" : ""}`}>
                  {request.status === "completed" ? "Run completed" : "In progress"}
                </span>
              </div>
              <div className="request-card-meta">
                <time dateTime={request.createdAt}>Created {formatTime(request.createdAt)}</time>
                <time dateTime={request.updatedAt}>Updated {formatTime(request.updatedAt)}</time>
                <a href={`#/demo/requests/${encodeURIComponent(request.id)}`}>Open request →</a>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <section className="panel empty-requests">
          <h2>No demo requests yet</h2>
          <p>Create a request to start a file-based audit workflow.</p>
          <a className="button button-primary" href="#/demo">Choose a service</a>
        </section>
      )}
    </div>
  );
}

export function DemoRequestPage({
  requestId,
  findingId,
}: {
  requestId: string;
  findingId?: string;
}) {
  const [request, setRequest] = useState<DemoRequest | null>(null);
  const [samples, setSamples] = useState<SampleFile[]>([]);
  const [requestLoading, setRequestLoading] = useState(true);
  const [samplesLoading, setSamplesLoading] = useState(true);
  const [selectedSamples, setSelectedSamples] = useState<string[]>([]);
  const [assessment, setAssessment] = useState<Assessment>({
    period_start: "2026-01-01",
    period_end: "2026-12-31",
    currency: "ZAR",
  });
  const [sourceSystem, setSourceSystem] = useState("Unspecified");
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null);
  const [question, setQuestion] = useState("");
  const [confirmedAI, setConfirmedAI] = useState(false);
  const [dispositionNotes, setDispositionNotes] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState<DemoRequestBusyAction | null>(null);
  const [busyFinding, setBusyFinding] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const service = request ? getService(request.serviceId) : undefined;
  const demoServiceId = request && DEMO_SERVICE_IDS.includes(request.serviceId as DemoServiceId)
    ? request.serviceId as DemoServiceId
    : undefined;
  const busy = busyAction !== null;

  async function refreshRequest() {
    const result = await fetchJSON<DemoRequest>(requestPath(requestId));
    setRequest(result);
    if (demoServiceId) {
      setAssessment({ ...initialAssessment(demoServiceId), ...result.assessment });
    } else {
      setAssessment({ ...assessment, ...result.assessment });
    }
  }

  useEffect(() => {
    let active = true;
    setRequestLoading(true);
    void Promise.all([
      fetchJSON<DemoRequest>(requestPath(requestId)),
      fetchJSON<{ ai: AIStatus }>(`${API_ROOT}/status`),
    ])
      .then(([loadedRequest, status]) => {
        if (!active) return;
        setRequest(loadedRequest);
        const loadedServiceId = loadedRequest.serviceId as DemoServiceId;
        setAssessment({
          ...initialAssessment(loadedServiceId),
          ...loadedRequest.assessment,
        });
        setAIStatus(status.ai);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not open this request.");
      })
      .finally(() => {
        if (active) setRequestLoading(false);
      });
    return () => { active = false; };
  }, [requestId]);

  useEffect(() => {
    if (!findingId || requestLoading || !request) return;
    const findingCard = document.getElementById(`finding-${findingId}`);
    if (!findingCard) return;
    findingCard.focus({ preventScroll: true });
    findingCard.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "center",
    });
  }, [findingId, requestLoading, request?.id]);

  useEffect(() => {
    if (!demoServiceId) return;
    let active = true;
    setSamplesLoading(true);
    void fetchJSON<{ samples: SampleFile[] }>(
      `${API_ROOT}/sample-files?serviceId=${encodeURIComponent(demoServiceId)}`,
    )
      .then((result) => {
        if (active) setSamples(result.samples);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load test-pack files.");
      })
      .finally(() => {
        if (active) setSamplesLoading(false);
      });
    return () => { active = false; };
  }, [demoServiceId]);

  const documentNames = useMemo(
    () => new Map((request?.documents || []).map((document) => [document.id, document.fileName])),
    [request?.documents],
  );

  function updateAssessment(field: string, value: string) {
    setAssessment((current) => ({ ...current, [field]: value }));
  }

  async function saveAssessment(): Promise<DemoRequest> {
    if (!demoServiceId) throw new Error("This request is not a runnable demo service.");
    const result = await fetchJSON<DemoRequest>(`${requestPath(requestId)}/assessment`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(assessment),
    });
    setRequest(result);
    setNotice("Assessment answers saved to the demo request.");
    return result;
  }

  async function handleSaveAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyAction("saving-assessment");
    setError("");
    setNotice("");
    try {
      await saveAssessment();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save assessment.");
    } finally {
      setBusyAction(null);
    }
  }

  async function importSelectedSamples() {
    if (!selectedSamples.length) {
      setError("Select one or more test-pack files first.");
      return;
    }
    setBusyAction("importing-samples");
    setError("");
    setNotice("");
    try {
      for (const sampleId of selectedSamples) {
        await fetchJSON(`${requestPath(requestId)}/samples`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ sampleId }),
        });
      }
      await refreshRequest();
      setSelectedSamples([]);
      setNotice("Selected test-pack files were imported and linked to this request.");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not import the selected sample.";
      setError(message);
      try {
        await refreshRequest();
      } catch (refreshReason) {
        const refreshMessage = refreshReason instanceof Error
          ? refreshReason.message
          : "The request could not be refreshed.";
        setError(`${message} ${refreshMessage}`);
      }
    } finally {
      setBusyAction(null);
    }
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    setBusyAction("uploading-files");
    setError("");
    setNotice("");
    try {
      for (const file of files) {
        await fetchJSON(`${requestPath(requestId)}/uploads`, {
          method: "POST",
          headers: {
            "content-type": "text/csv",
            "x-file-name": encodeURIComponent(file.name),
            "x-source-system": sourceSystem,
          },
          body: await file.arrayBuffer(),
        });
      }
      await refreshRequest();
      setNotice(`${files.length} CSV file${files.length === 1 ? "" : "s"} imported.`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not upload the selected CSV.";
      setError(message);
      try {
        await refreshRequest();
      } catch (refreshReason) {
        const refreshMessage = refreshReason instanceof Error
          ? refreshReason.message
          : "The request could not be refreshed.";
        setError(`${message} ${refreshMessage}`);
      }
    } finally {
      setBusyAction(null);
    }
  }

  async function runAudit() {
    setBusyAction("running-audit");
    setError("");
    setNotice("");
    try {
      await saveAssessment();
      const result = await fetchJSON<DemoRequest>(`${requestPath(requestId)}/runs`, {
        method: "POST",
      });
      setRequest(result);
      setNotice("Deterministic audit run completed and findings were saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The audit run could not complete.");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveDisposition(
    finding: DemoFinding,
    disposition: "accepted" | "rejected" | "needs_follow_up",
  ) {
    if (!request?.latestRun) return;
    setBusyFinding(finding.id);
    setError("");
    try {
      const result = await fetchJSON<DemoRequest>(
        `${requestPath(requestId)}/runs/${encodeURIComponent(request.latestRun.id)}/findings/${encodeURIComponent(finding.id)}/disposition`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            disposition,
            note: dispositionNotes[finding.id] || "",
          }),
        },
      );
      setRequest(result);
      setNotice("Reviewer disposition saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save reviewer disposition.");
    } finally {
      setBusyFinding("");
    }
  }

  async function askAI(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyAction("requesting-ai");
    setError("");
    setNotice("");
    try {
      const result = await fetchJSON<DemoRequest>(`${requestPath(requestId)}/ai-review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, confirmSend: confirmedAI }),
      });
      setRequest(result);
      setQuestion("");
      setConfirmedAI(false);
      setNotice("AI draft saved to this request. Review it before using any wording.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI review was not completed.");
    } finally {
      setBusyAction(null);
    }
  }

  if (requestLoading) {
    return <LoadingStatus label="Loading demo request…" className="page-loading" />;
  }
  if (!request && error) return <NotFound title="Request unavailable" detail={error} />;
  if (!request || !service || !demoServiceId) {
    return <LoadingStatus label="Preparing demo workflow…" className="page-loading" />;
  }

  const fields = assessmentFields(demoServiceId);

  return (
    <div className="workspace-page demo-workflow-page">
      <a className="back-link" href="#/demo/requests">← All demo requests</a>
      <section className="page-heading request-detail-heading">
        <div>
          <p className="eyebrow">DEMO REQUEST · {service.title.toUpperCase()}</p>
          <h1>{service.title}</h1>
          <p className="page-subtitle">
            Request {request.id} · Updated {formatTime(request.updatedAt)} · Demo owner
          </p>
        </div>
        <span className={`request-status ${request.latestRun ? "complete" : ""}`}>
          {request.latestRun ? "Run completed" : "In progress"}
        </span>
      </section>

      <div className="demo-safety-note" role="note">
        <strong>{API_MODE_LABEL} · synthetic data only</strong>
        <span>{STORAGE_NOTICE} No raw source rows or planted labels are sent to AI.</span>
      </div>
      {error && <p className="workspace-notice" role="alert">{error}</p>}
      {notice && <p className="demo-success-notice" role="status">{notice}</p>}

      <section className="panel demo-step-panel" aria-busy={busy}>
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">01 · TEST DATA</p>
            <h2>Choose bundled samples or upload CSVs</h2>
          </div>
        </div>
        {samplesLoading ? (
          <LoadingStatus label="Loading the bundled test pack…" />
        ) : samples.length ? (
          <div className="demo-sample-picker">
            <div className="demo-sample-field">
              <span className="demo-sample-label">Test-pack CSVs for this service</span>
              <p className="demo-sample-help">Check each file to attach, then import. Imported files appear below.</p>
              <div className="demo-sample-list" role="group" aria-label="Test-pack CSV files">
                {samples.map((sample) => {
                  const selected = selectedSamples.includes(sample.id);
                  return (
                    <label className={`demo-sample-option${selected ? " selected" : ""}`} key={sample.id}>
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={busy}
                        onChange={(event) => setSelectedSamples((current) => event.target.checked
                          ? [...current, sample.id]
                          : current.filter((id) => id !== sample.id))}
                      />
                      <span>
                        <strong>{sample.sourceSystem} · {humanizeLedgerType(sample.ledgerType)}</strong>
                        <span>{sample.fileName} · {sample.rowCount.toLocaleString()} rows</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
            <button className="button button-outline" onClick={() => void importSelectedSamples()} disabled={busy || !selectedSamples.length}>
              {busyAction === "importing-samples" && <span className="loading-spinner" aria-hidden="true" />}
              {busyAction === "importing-samples"
                ? "Importing and parsing…"
                : `Import ${selectedSamples.length || ""} selected test file${selectedSamples.length === 1 ? "" : "s"}`}
            </button>
          </div>
        ) : (
          <p className="empty-inline">No bundled samples are available for this service.</p>
        )}
        {busyAction === "importing-samples" && (
          <LoadingStatus label="Importing and parsing selected test files…" />
        )}
        <div className="demo-upload-controls">
          <label className="contact-field">
            <span>ERP/export source for your upload</span>
            <select value={sourceSystem} onChange={(event) => setSourceSystem(event.target.value)}>
              {ERP_SOURCES.map((source) => <option value={source} key={source}>{source}</option>)}
            </select>
          </label>
          <label className="demo-file-input">
            <span>Upload synthetic CSV files</span>
            <input type="file" accept=".csv,text/csv" multiple onChange={(event) => void uploadFiles(event)} disabled={busy} />
          </label>
        </div>
        {busyAction === "uploading-files" && (
          <LoadingStatus label="Uploading and parsing CSV file(s)…" />
        )}
        <div className="demo-document-list">
          {request.documents.length ? request.documents.map((document) => (
            <div className="demo-document-row" key={document.id}>
              <strong>{document.fileName}</strong>
              <span>{humanizeLedgerType(document.ledgerType || "unclassified")} · {document.rowCount?.toLocaleString() || 0} rows</span>
              <span>{document.sourceSystem || "Unspecified ERP"} · {formatBytes(document.sizeBytes)}</span>
              <details className="demo-column-map">
                <summary>Column mapping</summary>
                <p>Automatically detected; remapping is not supported in this demo.</p>
                <ul>
                  {document.columnMap.map((column) => (
                    <li key={column.sourceName}>
                      <code>{column.sourceName}</code>
                      {" → "}
                      {column.canonicalName ? <code>{column.canonicalName}</code> : "not mapped"}
                      {" · "}
                      {column.analysisAllowed ? column.inferredType : "excluded ground-truth label"}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )) : (
            <p className="empty-inline">No files attached yet. Check a sample above and select Import, or upload a synthetic CSV.</p>
          )}
        </div>
      </section>

      <section className="panel demo-step-panel">
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">02 · ASSESSMENT</p>
            <h2>Set scope and analytic assumptions</h2>
          </div>
        </div>
        <form className="demo-assessment-form" onSubmit={(event) => void handleSaveAssessment(event)}>
          {fields.map((field) => (
            <label className="contact-field" key={field.key}>
              <span>{field.label}{field.required ? " *" : ""}</span>
              {field.options ? (
                <select
                  required={field.required}
                  value={assessment[field.key] || ""}
                  onChange={(event) => updateAssessment(field.key, event.target.value)}
                >
                  {field.options.map((option) => <option value={option} key={option}>{option}</option>)}
                </select>
              ) : (
                <input
                  required={field.required}
                  type={field.type}
                  min={field.type === "number" ? "0.01" : undefined}
                  step={field.type === "number" ? "0.01" : undefined}
                  value={assessment[field.key] || ""}
                  onChange={(event) => updateAssessment(field.key, event.target.value)}
                />
              )}
              {field.help && <small>{field.help}</small>}
            </label>
          ))}
          <div className="demo-form-actions">
            <button className="button button-outline" type="submit" disabled={busy} aria-busy={busyAction === "saving-assessment"}>
              {busyAction === "saving-assessment" && <span className="loading-spinner" aria-hidden="true" />}
              Save assessment
            </button>
            <button className="button button-primary" type="button" onClick={() => void runAudit()} disabled={busy || !request.documents.length} aria-busy={busyAction === "running-audit"}>
              {busyAction === "running-audit" && <span className="loading-spinner" aria-hidden="true" />}
              {busyAction === "running-audit" ? "Running audit assessment…" : "Run Audit Assessment"}
            </button>
          </div>
          <p className="prototype-disclosure">
            Date-range defaults match the synthetic pack and are editable. Thresholds are demo
            parameters, not universal policy or materiality settings.
          </p>
        </form>
      </section>

      {request.latestRun && (
        <>
          <section className="panel demo-step-panel">
            <div className="workspace-section-heading">
              <div>
                <p className="eyebrow">03 · DETERMINISTIC RESULTS</p>
                <h2>Run {request.latestRun.id.slice(0, 8)}</h2>
              </div>
              <span className="prototype-tag">{request.latestRun.ruleVersion}</span>
            </div>
            <div className="demo-kpi-grid">
              <div><span>Rows analyzed</span><strong>{request.latestRun.summary.rows_analyzed.toLocaleString()}</strong></div>
              <div><span>Findings</span><strong>{request.latestRun.summary.finding_count.toLocaleString()}</strong></div>
              <div><span>Source files</span><strong>{request.latestRun.summary.source_count.toLocaleString()}</strong></div>
            </div>
            <div className="demo-form-actions">
              <button
                className="button button-outline"
                type="button"
                onClick={() => downloadAuditRun(request)}
              >
                Download result JSON
              </button>
            </div>
            <div className="demo-rule-counts">
              {Object.entries(request.latestRun.summary.by_rule).map(([rule, count]) => (
                <span key={rule}>{rule}: <strong>{count}</strong></span>
              ))}
              {!Object.keys(request.latestRun.summary.by_rule).length && <span>No screening findings were produced.</span>}
            </div>
            <div className="demo-limitations">
              <strong>Known limitations</strong>
              <ul>
                {request.latestRun.summary.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
              </ul>
            </div>
          </section>

          <section className="workspace-section demo-findings-section">
            <div className="workspace-section-heading">
              <div>
                <p className="eyebrow">04 · HUMAN REVIEW</p>
                <h2>Findings and dispositions</h2>
              </div>
            </div>
            {request.latestRun.findings.length ? (
              request.latestRun.findings.map((finding) => (
                <article
                  className="panel demo-finding-card"
                  id={`finding-${finding.id}`}
                  key={finding.id}
                  tabIndex={finding.id === findingId ? -1 : undefined}
                >
                  <div className="demo-finding-heading">
                    <div>
                      <span className={`request-status ${finding.severity === "high" ? "finding-high" : ""}`}>{finding.severity}</span>
                      <h3>{finding.title}</h3>
                      <p className="demo-finding-meta">
                        {documentNames.get(finding.documentId) || "Source CSV"} ·{" "}
                        {finding.sourceRowNumber === null ? "Population-level screen" : `source row ${finding.sourceRowNumber}`}
                      </p>
                    </div>
                    <code>{finding.ruleCode}</code>
                  </div>
                  <p>{finding.description}</p>
                  <p><strong>Suggested follow-up:</strong> {finding.recommendation}</p>
                  {Object.keys(finding.evidence).length > 0 && (
                    <dl className="demo-evidence-list">
                      {Object.entries(finding.evidence).map(([key, value]) => (
                        <div key={key}><dt>{humanizeKey(key)}</dt><dd>{String(value)}</dd></div>
                      ))}
                    </dl>
                  )}
                  {finding.disposition ? (
                    <p className="demo-disposition-saved">
                      Reviewer marked <strong>{humanizeKey(finding.disposition.status)}</strong>
                      {finding.disposition.note ? ` — ${finding.disposition.note}` : ""}
                    </p>
                  ) : (
                    <div className="demo-disposition-controls">
                      <label className="contact-field">
                        <span>Reviewer note (optional)</span>
                        <input
                          maxLength={2000}
                          value={dispositionNotes[finding.id] || ""}
                          onChange={(event) => setDispositionNotes((current) => ({
                            ...current,
                            [finding.id]: event.target.value,
                          }))}
                        />
                      </label>
                      <div>
                        <button type="button" className="button button-outline" disabled={busyFinding === finding.id} onClick={() => void saveDisposition(finding, "accepted")}>Accept</button>
                        <button type="button" className="button button-outline" disabled={busyFinding === finding.id} onClick={() => void saveDisposition(finding, "rejected")}>Reject</button>
                        <button type="button" className="button button-outline" disabled={busyFinding === finding.id} onClick={() => void saveDisposition(finding, "needs_follow_up")}>Follow up</button>
                      </div>
                    </div>
                  )}
                </article>
              ))
            ) : (
              <article className="panel demo-finding-card"><p>No findings for the selected population and scope.</p></article>
            )}
          </section>

          <section className="panel demo-step-panel demo-ai-panel">
            <div className="workspace-section-heading">
              <div>
                <p className="eyebrow">05 · OPTIONAL AI REVIEW</p>
                <h2>Ask about the deterministic results</h2>
              </div>
              <span className={`connection-pill ${aiStatus?.ready ? "connected" : "demo"}`}>
                <i />{aiStatus?.ready ? "Foundry ready" : "AI offline"}
              </span>
            </div>
            <p className="demo-ai-status">{aiStatus?.message || "Checking AI configuration…"}</p>
            <p className="prototype-disclosure">
              When enabled, the model receives the question, up to 10 recent chat messages, and a
              summary of finding rules/counts/descriptions—never the source CSVs, row identifiers, or planted labels.
              AI wording is a draft, not an audit opinion.
            </p>
            <div className="demo-chat-history" aria-live="polite">
              {request.latestRun.aiMessages.map((message) => (
                <article className={`demo-chat-message ${message.role}`} key={message.id}>
                  <strong>{message.role === "user" ? "You" : `AI draft · ${message.modelDeployment}`}</strong>
                  <p>{message.content}</p>
                  {message.promptTokens !== null && <small>Prompt tokens: {message.promptTokens}</small>}
                  {message.completionTokens !== null && <small> · Response tokens: {message.completionTokens}</small>}
                </article>
              ))}
            </div>
            <form className="demo-chat-form" onSubmit={(event) => void askAI(event)}>
              <label className="contact-field">
                <span>Your question (do not include personal or client data)</span>
                <textarea
                  maxLength={2000}
                  required
                  rows={3}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="What evidence should an auditor inspect for this type of finding?"
                />
              </label>
              <label className="demo-consent-check">
                <input
                  type="checkbox"
                  checked={confirmedAI}
                  onChange={(event) => setConfirmedAI(event.target.checked)}
                />
                <span>
                  I approve sending my question, recent chat, and de-identified finding summary to the
                  already configured Foundry deployment.
                </span>
              </label>
              <button className="button button-primary" type="submit" disabled={busy || !aiStatus?.ready || !confirmedAI} aria-busy={busyAction === "requesting-ai"}>
                {busyAction === "requesting-ai" && <span className="loading-spinner" aria-hidden="true" />}
                {busyAction === "requesting-ai" ? "Requesting review…" : "Send confirmed AI request"}
              </button>
            </form>
          </section>
        </>
      )}
    </div>
  );
}

function assessmentFields(serviceId: DemoServiceId): AssessmentField[] {
  const fields: AssessmentField[] = [
    { key: "period_start", label: "Reporting period start", type: "date" as const, required: true },
    { key: "period_end", label: "Reporting period end", type: "date" as const, required: true },
    { key: "currency", label: "Reporting currency", type: "number" as const, required: true, options: ["ZAR", "USD", "EUR", "GBP"] },
  ];
  if (serviceId === "journal-entry-analytics") {
    fields.push(
      { key: "approval_threshold", label: "Approval-threshold screen (amount)", type: "number", required: true, help: "Configurable screening parameter only; not a legal or universal approval limit." },
      { key: "round_amount_quantum", label: "Round-amount quantum", type: "number", required: true, help: "For example, 10000 flags amounts divisible by ZAR 10,000." },
      { key: "round_amount_minimum", label: "Minimum absolute amount for round-sum screen", type: "number", required: true },
    );
  } else if (serviceId === "invoice-integrity-review") {
    fields.push({
      key: "approval_threshold",
      label: "Approval-threshold screen (amount)",
      type: "number",
      required: true,
      help: "Used only to surface potential same-day threshold patterns.",
    });
  } else {
    fields.push({
      key: "asset_snapshot_date",
      label: "Fixed-asset snapshot date",
      type: "date",
      required: false,
      help: "Recorded as scope context. Over-cost depreciation is a balance-sheet screen on the full uploaded asset snapshot.",
    });
  }
  return fields.map((field) => ({
    ...field,
    options: field.key === "currency" ? ["ZAR", "USD", "EUR", "GBP"] : undefined,
  }));
}

function humanizeLedgerType(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function humanizeKey(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function NotFound({ title, detail = "Choose an available demo service or request." }: { title: string; detail?: string }) {
  return (
    <section className="panel workspace-not-found">
      <h1>{title}</h1>
      <p>{detail}</p>
      <a className="button button-primary" href="#/demo">Browse demo services</a>
    </section>
  );
}
