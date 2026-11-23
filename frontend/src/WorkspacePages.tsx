import { useState, type FormEvent } from "react";
import {
  SERVICE_CATALOG,
  SERVICE_GROUPS,
  WORKFLOW_PLANS,
  getService,
  isDemoServiceId,
  type ServiceDefinition,
  type WorkspaceDocument,
  type WorkspaceRequest,
} from "./workspace";

type WelcomePageProps = {
  onContinue: () => void;
};

export function ReconFlowWordmark({ variant = "new" }: { variant?: "new" | "legacy" }) {
  return (
    <span className={`product-wordmark ${variant === "legacy" ? "legacy" : ""}`}>
      {variant === "legacy" ? (
        <>
          <img src="/reconflow-mark.svg" alt="" />
          <strong>ReconFlow</strong>
        </>
      ) : (
        <img src="/reconflow-logo.webp" alt="ReconFlow" />
      )}
    </span>
  );
}

export function WelcomePage({ onContinue }: WelcomePageProps) {
  return (
    <main className="welcome-shell">
      <header className="welcome-topbar">
        <span className="welcome-context">AUDIT, RISK &amp; GOVERNANCE</span>
        <ReconFlowWordmark variant="legacy" />
      </header>
      <section className="welcome-card" aria-labelledby="welcome-title">
        <p className="eyebrow">WELCOME</p>
        <h1 id="welcome-title">Your audit work, organized.</h1>
        <p className="welcome-copy">
          Explore guided audit and governance services, keep track of requests,
          and review activity from one workspace.
        </p>
        <div className="welcome-note" role="note">
          <strong>Open prototype access</strong>
          <span>
            Sign-in is not connected yet. Continue as a guest to preview the
            workspace; do not enter confidential client information.
          </span>
        </div>
        <button className="button button-primary welcome-button" onClick={onContinue}>
          Continue to workspace <span aria-hidden="true">→</span>
        </button>
        <p className="welcome-footnote">
          Prototype request metadata is saved only in this browser.
        </p>
      </section>
    </main>
  );
}

type HomePageProps = {
  requests: WorkspaceRequest[];
};

export function HomePage({ requests }: HomePageProps) {
  const activeRequests = requests.filter((request) => {
    const service = getService(request.serviceId);
    return service && request.completedSteps < WORKFLOW_PLANS[service.workflow].steps.length;
  });
  const featuredServices = SERVICE_CATALOG.filter((service) =>
    ["journal-entry-analytics", "invoice-integrity-review", "inventory-asset-controls"].includes(service.id),
  );
  const recentRequests = [...requests]
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, 5);

  return (
    <div className="workspace-page">
      <section className="welcome-hero">
        <div>
          <p className="eyebrow">AUDITOR WORKSPACE</p>
          <h1>Welcome to ReconFlow</h1>
          <p>
            ReconFlow guides auditors through ledger analytics, reconciliation, audit workpapers,
            compliance, risk, and governance workflows, with reviewable progress in one workspace.
          </p>
        </div>
        <a className="button button-primary" href="#/services">
          Browse services <span aria-hidden="true">→</span>
        </a>
      </section>

      <section className="home-summary-grid" aria-label="Workspace summary">
        <article className="home-summary-card">
          <span>Active requests</span>
          <strong>{activeRequests.length}</strong>
          <a href="#/requests">Review request progress <span aria-hidden="true">→</span></a>
        </article>
        <article className="home-summary-card">
          <span>Available service guides</span>
          <strong>{SERVICE_CATALOG.length}</strong>
          <a href="#/services">Explore the service catalog <span aria-hidden="true">→</span></a>
        </article>
      </section>

      <section className="workspace-section">
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">GET STARTED</p>
            <h2>Common audit workflows</h2>
          </div>
          <a href="#/services">View all services <span aria-hidden="true">→</span></a>
        </div>
        <div className="service-card-grid">
          {featuredServices.map((service) => (
            <ServiceCard key={service.id} service={service} />
          ))}
        </div>
      </section>

      <section className="workspace-callout">
        <div>
          <strong>Need to return to a request?</strong>
          <p>Requests keep their checklist progress and activity history in this browser prototype.</p>
        </div>
        <a className="button button-outline" href="#/demo">Open ledger demos</a>
      </section>

      <section className="panel home-recent-panel">
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">RECENT ACTIVITY</p>
            <h2>Recent requests and documents</h2>
          </div>
          <a href="#/requests">View all requests <span aria-hidden="true">→</span></a>
        </div>
        {recentRequests.length ? (
          <div className="home-recent-list">
            {recentRequests.map((request) => {
              const service = getService(request.serviceId);
              if (!service) return null;
              const firstDocument = request.documents?.[0];
              return (
                <article className="home-recent-row" key={request.id}>
                  <a href={`#/requests/${request.id}`}>{service.title}</a>
                  {firstDocument ? (
                    <a href="#/control-room/documents">
                      {firstDocument.fileName}
                    </a>
                  ) : (
                    <span>No document attached</span>
                  )}
                  <span>Owner: Guest preview</span>
                  <time dateTime={request.createdAt}>Created {formatWorkspaceTime(request.createdAt)}</time>
                  <time dateTime={request.updatedAt}>Modified {formatWorkspaceTime(request.updatedAt)}</time>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="empty-inline">Created requests and linked documents will appear here.</p>
        )}
        <p className="prototype-disclosure">
          Guest preview activity is stored in this browser only. Secure uploads and shared document storage are not enabled.
        </p>
      </section>
    </div>
  );
}

export function ServicesPage() {
  return (
    <div className="workspace-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">SERVICE CATALOG</p>
          <h1>Services</h1>
          <p className="page-subtitle">
            Each guide explains the purpose, information to prepare, and review steps.
          </p>
        </div>
      </section>
      {SERVICE_GROUPS.map((group) => {
        const services = SERVICE_CATALOG.filter((service) => service.group === group);
        return (
          <section className="workspace-section" key={group}>
            <div className="workspace-section-heading">
              <div>
                <p className="eyebrow">{services.length} GUIDES</p>
                <h2>{group}</h2>
              </div>
            </div>
            <div className="service-card-grid">
              {services.map((service) => (
                <ServiceCard key={service.id} service={service} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

type ServiceCardProps = {
  service: ServiceDefinition;
};

function ServiceCard({ service }: ServiceCardProps) {
  const demoReady = isDemoServiceId(service.id);
  return (
    <a className="service-card panel" href={demoReady ? `#/demo/${service.id}` : `#/services/${service.id}`}>
      <span className="service-card-group">{service.group}</span>
      <h3>{service.title}</h3>
      <p>{service.summary}</p>
      <span className="card-link">
        {demoReady ? "Run demo workflow" : "View requirements and steps"} <span aria-hidden="true">→</span>
      </span>
    </a>
  );
}

type ServiceDetailPageProps = {
  service: ServiceDefinition;
  onStartRequest: (serviceId: string) => void;
};

export function ServiceDetailPage({ service, onStartRequest }: ServiceDetailPageProps) {
  const plan = WORKFLOW_PLANS[service.workflow];

  return (
    <div className="workspace-page">
      <a className="back-link" href="#/services">← All services</a>
      <section className="service-detail-hero">
        <div>
          <p className="eyebrow">{service.group.toUpperCase()} SERVICE GUIDE</p>
          <h1>{service.title}</h1>
          <p className="service-detail-summary">{service.summary}</p>
        </div>
        <span className="prototype-tag">Guided prototype</span>
      </section>
      <div className="service-detail-grid">
        <section className="panel workflow-panel">
          <div className="workspace-section-heading">
            <div>
              <p className="eyebrow">PROCESS</p>
              <h2>Steps in this service</h2>
            </div>
          </div>
          <ol className="workflow-list">
            {plan.steps.map((step, index) => (
              <li key={step}>
                <span className="workflow-number">{index + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <div className="workflow-output">
            <strong>Expected output</strong>
            <p>{plan.output}</p>
          </div>
        </section>
        <aside className="panel service-requirements">
          <p className="eyebrow">BEFORE YOU START</p>
          <h2>What you will need</h2>
          <ul className="requirement-list">
            {service.requirements.map((requirement) => (
              <li key={requirement}><span aria-hidden="true">✓</span>{requirement}</li>
            ))}
          </ul>
          <div className="ai-boundary">
            <strong>AI and reviewer boundary</strong>
            <p>{plan.aiBoundary}</p>
          </div>
          <div className="prototype-disclosure">
            This guide is a prototype. Starting a request creates a local checklist;
            it does not upload files or run an audit procedure.
          </div>
          <button
            className="button button-primary start-request-button"
            onClick={() => onStartRequest(service.id)}
          >
            Start a request <span aria-hidden="true">→</span>
          </button>
        </aside>
      </div>
    </div>
  );
}

type RequestsPageProps = {
  requests: WorkspaceRequest[];
  onDeleteRequest: (requestId: string) => void;
};

export function RequestsPage({ requests, onDeleteRequest }: RequestsPageProps) {
  const sortedRequests = [...requests].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const recentlyOpened = [...requests]
    .filter((request) => request.lastOpenedAt)
    .sort((left, right) => (right.lastOpenedAt || "").localeCompare(left.lastOpenedAt || ""));
  const mostRecentlyOpened = recentlyOpened[0];

  return (
    <div className="workspace-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">YOUR WORKSPACE</p>
          <h1>Requests</h1>
          <p className="page-subtitle">Resume a service checklist and review its activity.</p>
        </div>
        <a className="button button-primary" href="#/services">Start a request</a>
      </section>
      <section className="request-summary-grid" aria-label="Request summary">
        <article className="request-summary-card">
          <span>All created requests</span>
          <strong>{requests.length}</strong>
          <p>Every request created in this browser preview.</p>
        </article>
        <article className="request-summary-card">
          <span>Recently opened</span>
          <strong>{mostRecentlyOpened ? getService(mostRecentlyOpened.serviceId)?.title || "Request" : "—"}</strong>
          {mostRecentlyOpened ? (
            <a href={`#/requests/${mostRecentlyOpened.id}`}>
              Opened {formatWorkspaceTime(mostRecentlyOpened.lastOpenedAt || "")}
            </a>
          ) : (
            <p>Requests you open will appear here.</p>
          )}
        </article>
      </section>
      {sortedRequests.length ? (
        <section className="request-list" aria-label="Requests">
          {sortedRequests.map((request) => {
            const service = getService(request.serviceId);
            if (!service) return null;
            const plan = WORKFLOW_PLANS[service.workflow];
            const complete = request.completedSteps === plan.steps.length;
            const progress = Math.round((request.completedSteps / plan.steps.length) * 100);
            const firstDocument = request.documents?.[0];
            return (
              <article className="panel request-card" key={request.id}>
                <div className="request-card-top">
                  <div>
                    <span className="service-card-group">{service.group}</span>
                    <h2><a href={`#/requests/${request.id}`}>{service.title}</a></h2>
                    <p>Request {request.id}</p>
                  </div>
                  <span className={`request-status ${complete ? "complete" : ""}`}>
                    {complete ? "Completed" : "In progress"}
                  </span>
                </div>
                <div className="request-progress-label">
                  <span>{complete ? "Checklist complete" : `Step ${request.completedSteps + 1} of ${plan.steps.length}`}</span>
                  <strong>{progress}%</strong>
                </div>
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-label={`${service.title} request progress`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                >
                  <span style={{ width: `${progress}%` }} />
                </div>
                <p className="request-next-step">
                  {complete ? "All checklist milestones are complete." : plan.steps[request.completedSteps]}
                </p>
                <div className="request-card-meta">
                  {firstDocument ? (
                    <a href="#/control-room/documents">
                      {firstDocument.fileName}
                    </a>
                  ) : (
                    <span>No document attached</span>
                  )}
                  <span>Owner: Guest preview</span>
                  <time dateTime={request.createdAt}>Created {formatWorkspaceTime(request.createdAt)}</time>
                  <time dateTime={request.updatedAt}>Modified {formatWorkspaceTime(request.updatedAt)}</time>
                  <button
                    className="request-delete-button"
                    onClick={() => onDeleteRequest(request.id)}
                    type="button"
                  >
                    Delete
                  </button>
                </div>
              </article>
            );
          })}
        </section>
      ) : (
        <section className="panel empty-requests">
          <span className="empty-requests-icon" aria-hidden="true">↗</span>
          <h2>No requests yet</h2>
          <p>Choose a service to see its requirements and create your first guided checklist.</p>
          <a className="button button-primary" href="#/services">Explore services</a>
        </section>
      )}
      <p className="local-storage-note">
        Prototype requests are saved in this browser only. They are not yet stored in a secure shared account.
      </p>
    </div>
  );
}

type DocumentsPageProps = {
  requests: WorkspaceRequest[];
};

export function DocumentsPage({ requests }: DocumentsPageProps) {
  const documents = requests
    .flatMap((request) =>
      (request.documents || []).map((document: WorkspaceDocument) => ({
        ...document,
        requestId: request.id,
        service: getService(request.serviceId)?.title || "Service",
      })),
    )
    .sort((left, right) => right.modifiedAt.localeCompare(left.modifiedAt));

  return (
    <div className="workspace-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">CONTROL ROOM</p>
          <h1>Documents</h1>
          <p className="page-subtitle">Review files linked to their requests and source activity.</p>
        </div>
      </section>
      {documents.length ? (
        <section className="document-list" aria-label="Uploaded documents">
          {documents.map((document) => (
            <article className="panel document-card" key={document.id}>
              <div>
                <h2>{document.fileName}</h2>
                <p>{document.service} · Request {document.requestId}</p>
              </div>
              <div className="document-card-dates">
                <time dateTime={document.createdAt}>Created {formatWorkspaceTime(document.createdAt)}</time>
                <time dateTime={document.modifiedAt}>Modified {formatWorkspaceTime(document.modifiedAt)}</time>
              </div>
              <a className="button button-outline" href={`#/requests/${document.requestId}`}>
                Open request
              </a>
            </article>
          ))}
        </section>
      ) : (
        <section className="panel empty-requests">
          <h2>No uploaded documents</h2>
          <p>Documents will appear here after authenticated, private uploads are connected.</p>
          <p className="prototype-disclosure">
            File upload is not enabled in this guest preview. Do not upload client evidence here.
          </p>
          <a className="button button-outline" href="#/requests">View requests</a>
        </section>
      )}
    </div>
  );
}

type RequestDetailPageProps = {
  request: WorkspaceRequest;
  service: ServiceDefinition;
  onCompleteStep: (requestId: string) => void;
};

export function RequestDetailPage({
  request,
  service,
  onCompleteStep,
}: RequestDetailPageProps) {
  const plan = WORKFLOW_PLANS[service.workflow];
  const isComplete = request.completedSteps === plan.steps.length;
  const progress = Math.round((request.completedSteps / plan.steps.length) * 100);

  return (
    <div className="workspace-page">
      <a className="back-link" href="#/requests">← All requests</a>
      <section className="page-heading request-detail-heading">
        <div>
          <p className="eyebrow">{service.group.toUpperCase()} REQUEST</p>
          <h1>{service.title}</h1>
          <p className="page-subtitle">Request {request.id} · Updated {formatWorkspaceTime(request.updatedAt)}</p>
        </div>
        <span className={`request-status ${isComplete ? "complete" : ""}`}>
          {isComplete ? "Completed" : "In progress"}
        </span>
      </section>
      <section className="panel request-progress-panel">
        <div className="request-progress-label">
          <div>
            <p className="eyebrow">MILESTONES</p>
            <h2>{isComplete ? "Checklist complete" : "Current step"}</h2>
          </div>
          <strong>{progress}%</strong>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Request progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <span style={{ width: `${progress}%` }} />
        </div>
        <ol className="request-milestones">
          {plan.steps.map((step, index) => {
            const completed = index < request.completedSteps;
            const current = index === request.completedSteps && !isComplete;
            return (
              <li className={completed ? "completed" : current ? "current" : ""} key={step}>
                <span className="milestone-marker" aria-hidden="true">{completed ? "✓" : index + 1}</span>
                <span>{step}</span>
                <small>{completed ? "Complete" : current ? "Current" : "Upcoming"}</small>
              </li>
            );
          })}
        </ol>
        {!isComplete && (
          <button
            className="button button-primary"
            onClick={() => onCompleteStep(request.id)}
          >
            Complete prototype checkpoint <span aria-hidden="true">→</span>
          </button>
        )}
        <p className="prototype-disclosure">
          Checkpoints update local prototype progress only. No documents are processed,
          and completing a checklist is not an audit approval or sign-off.
        </p>
      </section>
      <div className="request-detail-grid">
        <section className="panel request-activity-panel">
          <div className="workspace-section-heading">
            <div>
              <p className="eyebrow">HISTORY</p>
              <h2>Request activity</h2>
            </div>
            <a href={`#/control-room/audit-trail?request=${encodeURIComponent(request.id)}`}>
              View in audit trail <span aria-hidden="true">→</span>
            </a>
          </div>
          <ol className="activity-list">
            {[...request.activity].reverse().map((entry, index) => (
              <li key={`${entry.occurredAt}-${index}`}>
                <span className="activity-dot" aria-hidden="true" />
                <div>
                  <strong>{entry.action}</strong>
                  <small>{formatWorkspaceTime(entry.occurredAt)}</small>
                </div>
              </li>
            ))}
          </ol>
          <p className="local-storage-note">
            Activity is shown in the Control Room audit trail as local prototype history, not as a server audit record.
          </p>
        </section>
        <aside className="panel request-requirements-panel">
          <p className="eyebrow">SERVICE GUIDE</p>
          <h2>{service.title}</h2>
          <p>{service.summary}</p>
          <h3>Information to prepare</h3>
          <ul className="requirement-list">
            {service.requirements.map((requirement) => (
              <li key={requirement}><span aria-hidden="true">•</span>{requirement}</li>
            ))}
          </ul>
          <a className="button button-outline" href={`#/services/${service.id}`}>Open service guide</a>
        </aside>
      </div>
    </div>
  );
}

function formatWorkspaceTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function ContactPage() {
  const [submissionStatus, setSubmissionStatus] = useState("");
  const [draftHref, setDraftHref] = useState("");
  const [phone, setPhone] = useState("+27");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const cleanText = (value: FormDataEntryValue | null) =>
      String(value ?? "")
        .replace(/\p{Cc}/gu, " ")
        .replace(/\s+/g, " ")
        .trim();
    const name = cleanText(formData.get("name")).slice(0, 100);
    const email = cleanText(formData.get("email")).slice(0, 254);
    const normalizedPhone = String(formData.get("phone") ?? "").replace(/[^\d+]/g, "");
    const topic = cleanText(formData.get("topic")).slice(0, 40);
    const message = cleanText(formData.get("message")).slice(0, 2000);

    if (!/^\+[1-9]\d{7,14}$/.test(normalizedPhone)) {
      setDraftHref("");
      setSubmissionStatus("Enter a valid international phone number, such as +27 82 123 4567.");
      return;
    }

    const subject = encodeURIComponent(`ReconFlow support - ${topic}`);
    const body = encodeURIComponent(
      `Name: ${name}\nWork email: ${email}\nMobile: ${normalizedPhone}\nInquiry type: ${topic}\n\n${message}`,
    );
    setDraftHref(`mailto:support@reconflow.ai?subject=${subject}&body=${body}`);
    setSubmissionStatus(
      "Your details were validated and prepared in a local email draft. ReconFlow does not send or store this inquiry; review the draft and send it from your email app.",
    );
  }

  return (
    <div className="workspace-page contact-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">SUPPORT</p>
          <h1>Contact us</h1>
          <p className="page-subtitle">Get help with your ReconFlow workspace.</p>
        </div>
      </section>
      <section className="panel contact-panel">
        <aside className="contact-details" aria-label="Support information">
          <div className="contact-detail">
            <span className="contact-detail-icon" aria-hidden="true">◷</span>
            <div>
              <strong>Support Hours:</strong>
              <span>Not configured for this demo</span>
            </div>
          </div>
          <div className="contact-detail">
            <span className="contact-detail-icon" aria-hidden="true">✉</span>
            <div>
              <strong>Email:</strong>
              <a href="mailto:support@reconflow.ai">support@reconflow.ai</a>
            </div>
          </div>
          <div className="contact-detail">
            <span className="contact-detail-icon" aria-hidden="true">◷</span>
            <div>
              <strong>Response Time:</strong>
              <span>Not configured for this demo</span>
            </div>
          </div>
        </aside>
        <form className="contact-form" onSubmit={handleSubmit}>
          <div className="contact-form-grid">
            <label className="contact-field" htmlFor="contact-name">
              Full Name
              <input
                id="contact-name"
                name="name"
                autoComplete="name"
                placeholder="e.g. Sarah van der Merwe"
                maxLength={100}
                required
              />
            </label>
            <label className="contact-field" htmlFor="contact-email">
              Work Email
              <input
                id="contact-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="e.g. sarah@company.co.za"
                maxLength={254}
                required
              />
            </label>
            <label className="contact-field" htmlFor="contact-phone">
              Cell / Mobile Number
              <input
                id="contact-phone"
                name="phone"
                type="tel"
                autoComplete="tel"
                inputMode="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+27 82 123 4567"
                maxLength={32}
                required
              />
            </label>
            <label className="contact-field" htmlFor="contact-topic">
              Inquiry Type / Topic
              <select id="contact-topic" name="topic" defaultValue="technical">
                <option value="technical">Technical Issue / Bug Report</option>
                <option value="account">Account &amp; Billing</option>
                <option value="audit">Audit / Compliance Services</option>
                <option value="data">Data Import / Reconciliation</option>
                <option value="general">General Question</option>
              </select>
              <small>Tell us what you need help with.</small>
            </label>
            <label className="contact-field contact-field-wide" htmlFor="contact-message">
              Message / Details
              <textarea
                id="contact-message"
                name="message"
                rows={4}
                placeholder="Describe your inquiry, ERP integration, or ledger anomaly issue..."
                maxLength={2000}
                required
              />
            </label>
          </div>
          <div className="contact-form-actions">
            <p className="contact-privacy">
              <span aria-hidden="true">⌑</span>
              Do not include sensitive client ledger records, credentials, or confidential financial information.
            </p>
            <button className="button button-primary" type="submit">
              <span aria-hidden="true">➤</span> Prepare Email Draft
            </button>
          </div>
          {submissionStatus && (
            <p className="contact-form-notice" role="status">
              {submissionStatus}
              {draftHref && (
                <>
                  {" "}
                  <a href={draftHref}>Open email draft</a>
                </>
              )}
            </p>
          )}
        </form>
      </section>
    </div>
  );
}

export function ProfilePage() {
      return (
        <div className="workspace-page">
          <section className="page-heading">
            <div>
              <p className="eyebrow">ACCOUNT</p>
              <h1>User profile</h1>
              <p className="page-subtitle">Manage your profile, plan, billing, and AI provider settings.</p>
            </div>
          </section>
          <section className="account-section-grid">
            <article className="panel account-placeholder">
              <h2>Profile information</h2>
              <dl className="account-details">
                <div><dt>Name</dt><dd>Not connected</dd></div>
                <div><dt>Company / organisation</dt><dd>Not connected</dd></div>
                <div><dt>Email</dt><dd>Not connected</dd></div>
                <div><dt>Cell phone</dt><dd>Not connected</dd></div>
              </dl>
            </article>
            <article className="panel account-placeholder">
              <h2>Plan and billing</h2>
              <p>Billing provider and subscription management are not configured in this preview.</p>
            </article>
            <article className="panel account-placeholder">
              <h2>AI resources</h2>
              <p>
                Provider selection and customer API keys are not enabled. No API key is stored in this
                browser; configure server-side secret storage and provider-specific access controls before
                enabling BYO AI.
              </p>
            </article>
          </section>
          <p className="prototype-disclosure">
            Sign-in and a server-backed account profile are not connected. Profile and billing changes are unavailable.
          </p>
        </div>
      );
}
