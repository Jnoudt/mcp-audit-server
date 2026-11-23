import { useCallback, useEffect, useState } from "react";
import { DEMO_SERVICE_IDS, getService, isDemoServiceId } from "./workspace";

type AuditFinding = {
  id: string;
  documentId: string;
  sourceRowNumber: number | null;
  ruleCode: string;
  title: string;
  severity: string;
  disposition?: { status: string; note: string; createdAt: string } | null;
};

type AuditRun = {
  id: string;
  status: string;
  ruleVersion: string;
  createdAt: string;
  summary: {
    source_count: number;
    rows_analyzed: number;
    finding_count: number;
    by_rule: Record<string, number>;
  };
  findings: AuditFinding[];
};

export type AuditRequest = {
  id: string;
  serviceId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  documents: { id: string; fileName: string }[];
  latestRun: AuditRun | null;
};

type AIStatus = {
  enabled: boolean;
  configured: boolean;
  ready: boolean;
  message: string;
};

type AuditData = {
  requests: AuditRequest[];
  totalRequests: number;
  storage: string;
  ai: AIStatus;
};

export type ControlRoomAuditData = {
  requests: AuditRequest[];
  totalRequests: number;
  storage: string;
  ai: AIStatus | null;
  isLoading: boolean;
  error: string;
  refresh: () => void;
};

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "";
const API_ROOT = `${API_BASE_URL}/api/demo`;
const MAX_DETAILED_REQUESTS = 20;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isAuditFinding(value: unknown): value is AuditFinding {
  if (!isRecord(value)) return false;
  const disposition = value.disposition;
  return (
    typeof value.id === "string" &&
    typeof value.documentId === "string" &&
    (value.sourceRowNumber === null || typeof value.sourceRowNumber === "number") &&
    typeof value.ruleCode === "string" &&
    typeof value.title === "string" &&
    typeof value.severity === "string" &&
    (disposition === undefined ||
      disposition === null ||
      (isRecord(disposition) &&
        typeof disposition.status === "string" &&
        typeof disposition.note === "string" &&
        typeof disposition.createdAt === "string"))
  );
}

function isAuditRun(value: unknown): value is AuditRun {
  if (!isRecord(value) || !isRecord(value.summary)) return false;
  const summary = value.summary;
  return (
    typeof value.id === "string" &&
    typeof value.status === "string" &&
    typeof value.ruleVersion === "string" &&
    typeof value.createdAt === "string" &&
    typeof summary.source_count === "number" &&
    typeof summary.rows_analyzed === "number" &&
    typeof summary.finding_count === "number" &&
    isRecord(summary.by_rule) &&
    Object.values(summary.by_rule).every(
      (count) => typeof count === "number" && Number.isFinite(count),
    ) &&
    Array.isArray(value.findings) &&
    value.findings.every(isAuditFinding)
  );
}

function isAuditRequest(value: unknown): value is AuditRequest {
  if (!isRecord(value) || !Array.isArray(value.documents)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.serviceId === "string" &&
    isDemoServiceId(value.serviceId) &&
    typeof value.status === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.updatedAt === "string" &&
    value.documents.every(
      (document) =>
        isRecord(document) &&
        typeof document.id === "string" &&
        typeof document.fileName === "string",
    ) &&
    (value.latestRun === null || isAuditRun(value.latestRun))
  );
}

function isRequestSummary(value: unknown): value is { id: string } {
  return isRecord(value) && typeof value.id === "string";
}

async function fetchJSON(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { cache: "no-store", signal });
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
  return payload;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function getLatestRuns(requests: AuditRequest[]): AuditRequest[] {
  return requests
    .filter((request) => request.latestRun !== null)
    .sort((left, right) =>
      (right.latestRun?.createdAt || "").localeCompare(left.latestRun?.createdAt || ""),
    );
}

export function findingHref(requestId: string, findingId: string): string {
  return `#/demo/requests/${encodeURIComponent(requestId)}?finding=${encodeURIComponent(findingId)}`;
}

export function useControlRoomAuditData(enabled: boolean): ControlRoomAuditData {
  const [data, setData] = useState<AuditData>({
    requests: [],
    totalRequests: 0,
    storage: "",
    ai: { enabled: false, configured: false, ready: false, message: "Status unavailable." },
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((current) => current + 1), []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let active = true;
    setIsLoading(true);
    setError("");

    async function load() {
      try {
        const [requestPayload, statusPayload] = await Promise.all([
          fetchJSON(`${API_ROOT}/requests`, controller.signal),
          fetchJSON(`${API_ROOT}/status`, controller.signal),
        ]);
        if (
          !isRecord(requestPayload) ||
          !Array.isArray(requestPayload.requests) ||
          !requestPayload.requests.every(isRequestSummary)
        ) {
          throw new Error("The demo API returned an invalid request list.");
        }
        if (
          !isRecord(statusPayload) ||
          !isRecord(statusPayload.ai) ||
          typeof statusPayload.ai.enabled !== "boolean" ||
          typeof statusPayload.ai.configured !== "boolean" ||
          typeof statusPayload.ai.ready !== "boolean" ||
          typeof statusPayload.ai.message !== "string"
        ) {
          throw new Error("The demo API returned an invalid status response.");
        }

        const requestSummaries = requestPayload.requests.slice(0, MAX_DETAILED_REQUESTS);
        const requests = await Promise.all(
          requestSummaries.map(async (summary) => {
            const result = await fetchJSON(
              `${API_ROOT}/requests/${encodeURIComponent(summary.id)}`,
              controller.signal,
            );
            if (!isAuditRequest(result)) {
              throw new Error("The demo API returned an invalid audit request.");
            }
            return result;
          }),
        );
        if (!active) return;
        setData({
          requests,
          totalRequests: requestPayload.requests.length,
          storage: typeof statusPayload.storage === "string"
            ? statusPayload.storage
            : "Storage status unavailable.",
          ai: {
            enabled: statusPayload.ai.enabled,
            configured: statusPayload.ai.configured,
            ready: statusPayload.ai.ready,
            message: statusPayload.ai.message,
          },
        });
      } catch (reason) {
        if (active && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Could not load audit activity.");
        }
      } finally {
        if (active) setIsLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [enabled, refreshKey]);

  return { ...data, isLoading, error, refresh };
}

function LoadState({ data }: { data: ControlRoomAuditData }) {
  return (
    <>
      {data.isLoading && (
        <div className="loading-status" role="status">
          <span className="loading-spinner" aria-hidden="true" />
          Loading recent audit runs and findings…
        </div>
      )}
      {data.error && <p className="control-room-error" role="alert">{data.error}</p>}
    </>
  );
}

function runMetrics(request: AuditRequest) {
  const run = request.latestRun;
  if (!run) return null;
  return (
    <div className="audit-run-metrics">
      <span><strong>{run.summary.rows_analyzed.toLocaleString()}</strong> rows</span>
      <span><strong>{run.summary.finding_count.toLocaleString()}</strong> findings</span>
      <span><strong>{run.summary.source_count.toLocaleString()}</strong> source files</span>
    </div>
  );
}

export function ControlRoomOverview({
  data,
}: {
  data: ControlRoomAuditData;
}) {
  const latestRuns = getLatestRuns(data.requests);
  const completedRuns = latestRuns.length;
  const findingCount = latestRuns.reduce(
    (total, request) => total + (request.latestRun?.summary.finding_count || 0),
    0,
  );
  const aiLabel = data.ai
    ? data.ai.enabled
      ? data.ai.ready ? "Ready" : "Unavailable"
      : "Disabled"
    : "Unknown";

  return (
    <>
      <LoadState data={data} />
      <section className="kpi-grid" aria-label="ReconFlow audit summary">
        <article className="kpi-card">
          <div className="kpi-top"><span>Demo requests</span><span className="kpi-icon blue">≋</span></div>
          <strong>{data.isLoading ? "…" : data.totalRequests.toLocaleString()}</strong>
          <small>Saved run details inspected for the newest 20</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-top"><span>Assessments</span><span className="kpi-icon green">✓</span></div>
          <strong>{data.isLoading ? "…" : completedRuns.toLocaleString()}</strong>
          <small>Completed runs within the newest 20 requests</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-top"><span>Latest-run findings</span><span className="kpi-icon amber">!</span></div>
          <strong>{data.isLoading ? "…" : findingCount.toLocaleString()}</strong>
          <small>Latest-run candidates in the newest 20 requests</small>
        </article>
        <article className="kpi-card">
          <div className="kpi-top"><span>Foundry review</span><span className="kpi-icon red">AI</span></div>
          <strong>{aiLabel}</strong>
          <small>{data.ai?.message || "Status is loading."}</small>
        </article>
      </section>

      <section className="control-room-data-grid">
        <article className="panel">
          <div className="workspace-section-heading">
            <div>
              <p className="eyebrow">RECENT ACTIVITY</p>
              <h2>Latest audit runs</h2>
            </div>
            <a href="#/control-room/audit-trail">Open audit trail <span aria-hidden="true">→</span></a>
          </div>
          {!data.isLoading && !data.error && latestRuns.length === 0 && (
            <p className="empty-inline">No audit assessments have been saved yet. Run one of the three demo services to populate this view.</p>
          )}
          <div className="control-room-run-list">
            {latestRuns.slice(0, 5).map((request) => {
              const service = getService(request.serviceId);
              const run = request.latestRun;
              if (!service || !run) return null;
              const firstFinding = run.findings[0];
              return (
                <article className="control-room-run-row" key={request.id}>
                  <div>
                    <strong>{service.title}</strong>
                    <span>{formatTime(run.createdAt)} · Run {run.id.slice(0, 8)}</span>
                  </div>
                  <span>{run.summary.rows_analyzed.toLocaleString()} rows · {run.summary.finding_count.toLocaleString()} findings</span>
                  <a href={firstFinding ? findingHref(request.id, firstFinding.id) : `#/demo/requests/${request.id}`}>
                    {firstFinding ? "Open a finding" : "Open assessment"} <span aria-hidden="true">→</span>
                  </a>
                </article>
              );
            })}
          </div>
        </article>

        <article className="panel control-room-governance">
          <p className="eyebrow">SECURITY &amp; GOVERNANCE</p>
          <h2>Reviewable, synthetic-data workflow</h2>
          <p>Use demonstration data only. The hosted guest demo stores request and upload data in {data.storage || "the configured demo store"}; it is not Azure SQL persistence.</p>
          <p>Deterministic findings are screening candidates, not audit conclusions. An auditor reviews the source evidence and records a disposition.</p>
          <p>Hosted AI is {aiLabel.toLowerCase()}. Do not send real client or personal information.</p>
          <a href="#/control-room/audit-trail">Review runs and findings <span aria-hidden="true">→</span></a>
        </article>
      </section>
    </>
  );
}

export function ControlRoomToolkit({
  data,
}: {
  data: ControlRoomAuditData;
}) {
  const latestRuns = getLatestRuns(data.requests);

  return (
    <>
      <LoadState data={data} />
      <section className="toolkit-grid" aria-label="Runnable audit services">
        {DEMO_SERVICE_IDS.map((serviceId) => {
          const service = getService(serviceId);
          const request = latestRuns.find((item) => item.serviceId === serviceId);
          const run = request?.latestRun;
          const firstFinding = run?.findings[0];
          return (
            <article className="panel toolkit-card" key={serviceId}>
              <p className="eyebrow">RUNNABLE CAATS SERVICE</p>
              <h2>{service?.title || serviceId}</h2>
              <p>{service?.summary}</p>
              {data.isLoading ? (
                <p className="empty-inline">Loading latest assessment…</p>
              ) : run && request ? (
                <>
                  {runMetrics(request)}
                  <p className="toolkit-rule-counts">
                    {Object.entries(run.summary.by_rule)
                      .map(([rule, count]) => `${rule}: ${count.toLocaleString()}`)
                      .join(" · ") || "No screening findings in the latest run."}
                  </p>
                  <a href={firstFinding ? findingHref(request.id, firstFinding.id) : `#/demo/requests/${request.id}`}>
                    {firstFinding ? "Open latest finding" : "Open latest run"} <span aria-hidden="true">→</span>
                  </a>
                </>
              ) : (
                <a href={`#/demo/${serviceId}`}>Start sample assessment <span aria-hidden="true">→</span></a>
              )}
            </article>
          );
        })}
      </section>
      <p className="control-room-source-note">
        This toolkit lists the three implemented CAATs workflows. The MCP JSON-RPC
        inspector below is a separate interface and does not run these ledger assessments.
      </p>
    </>
  );
}

export function ControlRoomAuditTrail({
  data,
  requestFilter,
}: {
  data: ControlRoomAuditData;
  requestFilter?: string;
}) {
  const latestRuns = getLatestRuns(data.requests).filter(
    (request) => !requestFilter || request.id === requestFilter,
  );

  return (
    <section className="panel audit-run-history" aria-labelledby="audit-run-history-title">
      <div className="audit-heading">
        <div>
          <p className="eyebrow">RECONFLOW CAATS</p>
          <h2 id="audit-run-history-title">Audit runs and findings</h2>
          <p className="panel-intro">Each finding links to its request and exact review card. These are screening results, not immutable audit records.</p>
        </div>
        <button className="button button-outline" onClick={data.refresh} disabled={data.isLoading}>
          Refresh results
        </button>
      </div>
      <LoadState data={data} />
      {requestFilter && (
        <div className="request-filter-notice">
          <span>Showing audit runs for request {requestFilter}</span>
          <a href="#/control-room/audit-trail">Clear request filter</a>
        </div>
      )}
      {!data.isLoading && !data.error && latestRuns.length === 0 && (
        <p className="empty-inline">
          No completed audit runs match this view. Start a runnable service from the{" "}
          <a href="#/control-room/tool-inspector">audit toolkit</a>.
        </p>
      )}
      <div className="control-room-run-list">
        {latestRuns.map((request) => {
          const service = getService(request.serviceId);
          const run = request.latestRun;
          if (!service || !run) return null;
          const visibleFindings = run.findings.slice(0, 10);
          const documentNames = new Map(
            request.documents.map((document) => [document.id, document.fileName]),
          );
          return (
            <article className="panel audit-run-card" key={request.id}>
              <div className="workspace-section-heading">
                <div>
                  <p className="eyebrow">{service.title}</p>
                  <h3>Run {run.id.slice(0, 8)}</h3>
                </div>
                <span className="status-tag success"><i /> {run.status}</span>
              </div>
              <p className="audit-run-request">
                Request <a href={`#/demo/requests/${encodeURIComponent(request.id)}`}>{request.id}</a>
                {" · "}{formatTime(run.createdAt)}{" · "}Rule version {run.ruleVersion}
              </p>
              {runMetrics(request)}
              {visibleFindings.length ? (
                <>
                  <ul className="audit-finding-link-list">
                    {visibleFindings.map((finding) => (
                      <li key={finding.id}>
                        <a className="audit-finding-link" href={findingHref(request.id, finding.id)}>
                          <span>
                            <strong>{finding.ruleCode}</strong> · {finding.title}
                            <small>
                              {documentNames.get(finding.documentId) || "Source CSV"} ·{" "}
                              {finding.sourceRowNumber === null
                                ? "Population-level screen"
                                : `source row ${finding.sourceRowNumber}`}
                            </small>
                          </span>
                          <span className={`request-status ${finding.severity === "high" ? "finding-high" : ""}`}>
                            {finding.disposition?.status || "needs review"}
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                  {run.findings.length > visibleFindings.length && (
                    <p className="audit-run-more">
                      Showing {visibleFindings.length} of {run.findings.length.toLocaleString()} findings.{" "}
                      <a href={`#/demo/requests/${encodeURIComponent(request.id)}`}>Open all findings →</a>
                    </p>
                  )}
                </>
              ) : (
                <p className="empty-inline">No finding records were saved for this run.</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
