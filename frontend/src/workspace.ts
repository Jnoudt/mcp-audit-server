export type ServiceGroup = "Audit" | "Compliance" | "Risk" | "Governance";

export type WorkflowKey =
  | "audit"
  | "caats"
  | "reconciliation"
  | "evidence"
  | "workpapers"
  | "controls"
  | "requirements"
  | "third-party"
  | "risk"
  | "governance"
  | "education"
  | "conflict";

export type ServiceDefinition = {
  id: string;
  group: ServiceGroup;
  title: string;
  summary: string;
  requirements: string[];
  workflow: WorkflowKey;
  demoReady?: boolean;
};

export type WorkflowPlan = {
  steps: string[];
  output: string;
  aiBoundary: string;
};

export type RequestActivity = {
  action: string;
  occurredAt: string;
};

export type WorkspaceDocument = {
  id: string;
  fileName: string;
  contentType: string;
  createdAt: string;
  modifiedAt: string;
};

export type WorkspaceRequest = {
  id: string;
  serviceId: string;
  createdAt: string;
  updatedAt: string;
  lastOpenedAt?: string;
  documents?: WorkspaceDocument[];
  completedSteps: number;
  activity: RequestActivity[];
};

export const SERVICE_GROUPS: ServiceGroup[] = [
  "Audit",
  "Compliance",
  "Risk",
  "Governance",
];

export const WORKFLOW_PLANS: Record<WorkflowKey, WorkflowPlan> = {
  audit: {
    steps: [
      "Define engagement objectives, scope, entity, and period",
      "Assess risks, controls, and prior findings",
      "Perform procedures and gather supporting evidence",
      "Review findings, assign actions, and prepare the report",
      "Complete reviewer approval and export the engagement record",
    ],
    output: "A scoped engagement record with reviewable procedures, findings, and actions.",
    aiBoundary: "AI may help organize or summarize cited evidence; auditors own testing and conclusions.",
  },
  caats: {
    steps: [
      "Select ERP and audit period, then provide a ledger CSV",
      "Map columns and validate dates, currency, and population completeness",
      "Run deterministic full-population tests",
      "Review exceptions and record auditor dispositions",
      "Export reproducible results with dataset and rule lineage",
    ],
    output: "A reproducible analysis run and a reviewable list of exceptions.",
    aiBoundary: "AI may suggest column mappings; calculations and exception rules stay deterministic.",
  },
  reconciliation: {
    steps: [
      "Select period and accounts, then provide bank/subledger and GL exports",
      "Map columns and validate balances, currencies, and duplicate rows",
      "Apply deterministic matching rules",
      "Review unmatched or ambiguous items and document adjustments separately",
      "Complete preparer/reviewer sign-off and export the reconciliation",
    ],
    output: "A reconciliation summary with matched, unmatched, and reviewer-approved items.",
    aiBoundary: "AI may suggest candidate matches only; a person reviews ambiguous items and approves matches.",
  },
  evidence: {
    steps: [
      "Provide a ledger population and supporting documents",
      "Map identifiers, dates, and amounts",
      "Review proposed links and unmatched items against source evidence",
      "Confirm or reject links and record reviewer rationale",
      "Export the matching log with evidence provenance",
    ],
    output: "A traceable evidence-link register with reviewer decisions.",
    aiBoundary: "Automated or AI matching can propose links, never confirm them on an auditor's behalf.",
  },
  workpapers: {
    steps: [
      "Create an engagement and define scope and materiality",
      "Define risks, controls, and audit procedures",
      "Request evidence and document procedure results",
      "Review findings and draft narrative with source citations if enabled",
      "Complete auditor sign-off, reviewer review, and export",
    ],
    output: "An engagement workpaper set with linked evidence, findings, and approvals.",
    aiBoundary: "AI-generated wording remains a cited draft; qualified auditors own conclusions and sign-off.",
  },
  controls: {
    steps: [
      "Select a control, framework, entity, and period",
      "Define the owner, population, and test procedure",
      "Collect evidence and validate its completeness",
      "Test design and operation, then document exceptions",
      "Obtain reviewer approval and track remediation",
    ],
    output: "A control test record with evidence, exceptions, and remediation actions.",
    aiBoundary: "AI may organize evidence; control effectiveness and compliance decisions require human review.",
  },
  requirements: {
    steps: [
      "Choose jurisdictions, frameworks, entities, and reporting period",
      "Identify authoritative requirements and source references",
      "Map obligations to owners, policies, and controls",
      "Review gaps and assign remediation actions",
      "Approve and export the requirements register",
    ],
    output: "A reviewable requirements register with source references and accountable owners.",
    aiBoundary: "AI can assist with discovery and summaries; legal applicability must be verified by a qualified reviewer.",
  },
  "third-party": {
    steps: [
      "Identify the third party, relationship, and assessment scope",
      "Request authorized questionnaires and supporting evidence",
      "Validate completeness and review approved screening sources",
      "Confirm or reject candidate matches and record analyst rationale",
      "Approve the assessment and schedule follow-up",
    ],
    output: "A third-party assessment record with evidence, decisions, and follow-up dates.",
    aiBoundary: "AI may organize evidence or suggest candidate matches; analysts make and record decisions.",
  },
  risk: {
    steps: [
      "Define the entity scope, risk taxonomy, and assessment period",
      "Identify inherent risks and related controls and evidence",
      "Apply disclosed, configurable scoring criteria",
      "Assign an owner, treatment, and target date",
      "Review changes, approve the register, and report",
    ],
    output: "A risk register with disclosed scoring, owners, treatments, and approvals.",
    aiBoundary: "AI may suggest categories or draft descriptions; it never silently changes a risk score.",
  },
  governance: {
    steps: [
      "Identify the entity, record owner, and governance scope",
      "Create or provide the policy, entity, or meeting record",
      "Route the record to the appropriate approvers",
      "Record versions, attestations, actions, and exceptions",
      "Publish or export the approved audit record",
    ],
    output: "A versioned governance record with attributed approvals and actions.",
    aiBoundary: "AI may help draft or summarize records; authorized people approve and publish them.",
  },
  education: {
    steps: [
      "Select the framework, audience, and learning objective",
      "Choose the guided content or checklist and due dates",
      "Complete the learning or advisory checklist",
      "Record completion and any required attestation",
      "Track gaps and actions, then export the completion record",
    ],
    output: "A learning or advisory completion record with follow-up actions.",
    aiBoundary: "Guidance is educational and does not replace legal, accounting, or professional advice.",
  },
  conflict: {
    steps: [
      "Identify the person, role, and disclosure period",
      "Record the disclosure and supporting information",
      "Review the potential conflict and proposed mitigation",
      "Have an authorized approver record the disposition",
      "Track follow-up and export the decision log",
    ],
    output: "A restricted disclosure record with an attributed disposition and follow-up.",
    aiBoundary: "AI may help classify a disclosure for review; authorized reviewers decide and document outcomes.",
  },
};

export const SERVICE_CATALOG: ServiceDefinition[] = [
  {
    id: "internal-audit",
    group: "Audit",
    title: "Internal Audit",
    summary: "Plan an audit engagement, document procedures, and track findings through review.",
    requirements: ["Engagement objective and scope", "Entity and audit period", "Risk areas, evidence owners, and reviewer"],
    workflow: "audit",
  },
  {
    id: "internal-controls",
    group: "Audit",
    title: "Internal Controls",
    summary: "Document key controls and organize evidence for design and operating-effectiveness testing.",
    requirements: ["Control description and owner", "Entity, period, and test population", "Test procedure and evidence sources"],
    workflow: "controls",
  },
  {
    id: "caats-ledger-analytics",
    group: "Audit",
    title: "CAATs / Ledger Analytics",
    summary: "Run reproducible, deterministic checks across a ledger export and review flagged exceptions.",
    requirements: ["Ledger CSV and ERP/export type", "Audit period and currency", "Column mapping and population context"],
    workflow: "caats",
  },
  {
    id: "journal-entry-analytics",
    group: "Audit",
    title: "Journal Entry Analytics",
    summary: "Screen general-ledger populations for weekend postings, large round amounts, approval splits, and Benford distribution.",
    requirements: ["General-ledger CSV from a supported ERP export", "Reporting period and approval threshold", "Auditor review of flagged source rows"],
    workflow: "caats",
    demoReady: true,
  },
  {
    id: "invoice-integrity-review",
    group: "Audit",
    title: "Invoice Integrity Review",
    summary: "Screen accounts-payable and receivable ledgers for repeated invoice references, approval-threshold patterns, and missing PO references.",
    requirements: ["AP and/or AR CSV from a supported ERP export", "Reporting period and approval threshold", "Source invoices and approval evidence for follow-up"],
    workflow: "caats",
    demoReady: true,
  },
  {
    id: "inventory-asset-controls",
    group: "Audit",
    title: "Inventory & Fixed Asset Controls",
    summary: "Screen inventory movements and fixed-asset balances for negative quantities and accumulated depreciation above cost.",
    requirements: ["Inventory movement and/or fixed-asset CSV", "Reporting period and asset snapshot date", "Inventory balance and asset-subledger evidence for review"],
    workflow: "caats",
    demoReady: true,
  },
  {
    id: "account-reconciliation",
    group: "Audit",
    title: "Account Reconciliation",
    summary: "Compare bank or subledger exports with general-ledger balances and review unmatched items.",
    requirements: ["Bank/subledger and GL exports", "Accounts and reconciliation period", "Currencies, tolerances, and reviewer"],
    workflow: "reconciliation",
  },
  {
    id: "evidence-matching",
    group: "Audit",
    title: "Evidence Matching",
    summary: "Link ledger rows to supporting evidence while retaining source references and reviewer decisions.",
    requirements: ["Ledger population and evidence files", "Identifiers, dates, and amounts to compare", "Authorized evidence sources"],
    workflow: "evidence",
  },
  {
    id: "audit-workpapers",
    group: "Audit",
    title: "Audit Workpapers",
    summary: "Organize engagement scope, procedures, evidence, findings, and reviewer sign-off.",
    requirements: ["Engagement scope and materiality", "Risks, controls, and procedures", "Evidence owners and reviewer"],
    workflow: "workpapers",
  },
  {
    id: "compliance-education",
    group: "Compliance",
    title: "Compliance Education",
    summary: "Guide a team through framework-related learning, checklists, and completion tracking.",
    requirements: ["Framework and learning objective", "Audience and due dates", "Required completion or attestation"],
    workflow: "education",
  },
  {
    id: "compliance-requirements",
    group: "Compliance",
    title: "Compliance Requirements",
    summary: "Map applicable requirements to sources, accountable owners, and controls for review.",
    requirements: ["Jurisdictions and frameworks", "Entities and reporting period", "Authoritative source references"],
    workflow: "requirements",
  },
  {
    id: "due-diligence",
    group: "Compliance",
    title: "Due Diligence",
    summary: "Collect authorized information and evidence for a structured, reviewable due-diligence assessment.",
    requirements: ["Subject and assessment purpose", "Authorized questionnaire and evidence", "Assessment owner and reviewer"],
    workflow: "third-party",
  },
  {
    id: "third-party-manager",
    group: "Compliance",
    title: "Third-Party Manager",
    summary: "Organize third-party records, assessments, evidence, owners, and follow-up dates.",
    requirements: ["Third-party inventory and relationship", "Assessment scope and owner", "Evidence and review schedule"],
    workflow: "third-party",
  },
  {
    id: "third-party-risk-intelligence",
    group: "Compliance",
    title: "Third-Party Risk Intelligence",
    summary: "Review approved information sources and document analyst-confirmed third-party risk signals.",
    requirements: ["Third-party identity and scope", "Approved data sources", "Analyst rationale and reviewer"],
    workflow: "third-party",
  },
  {
    id: "conflict-of-interest",
    group: "Compliance",
    title: "Conflict of Interest",
    summary: "Record disclosures, route them to authorized approvers, and track dispositions and actions.",
    requirements: ["Person, role, and disclosure period", "Disclosure details and supporting information", "Authorized approver and follow-up owner"],
    workflow: "conflict",
  },
  {
    id: "compliance-advisory",
    group: "Compliance",
    title: "Compliance Advisory",
    summary: "Guide users through a structured compliance question and keep the resulting checklist reviewable.",
    requirements: ["Question and business context", "Relevant framework or jurisdiction", "Reviewer for any resulting actions"],
    workflow: "education",
  },
  {
    id: "it-compliance",
    group: "Compliance",
    title: "IT Compliance",
    summary: "Organize IT control evidence and track compliance test results, exceptions, and remediation.",
    requirements: ["Framework and IT control set", "Systems, owners, and assessment period", "Evidence and test procedure"],
    workflow: "controls",
  },
  {
    id: "ai-risk-essentials",
    group: "Risk",
    title: "AI Risk Essentials",
    summary: "Structure an AI-system risk review with documented scope, controls, evidence, and ownership.",
    requirements: ["AI system purpose and accountable owner", "Use context, affected parties, and risk criteria", "Controls, evidence, and reviewer"],
    workflow: "risk",
  },
  {
    id: "enterprise-risk-management",
    group: "Risk",
    title: "Enterprise Risk Management",
    summary: "Maintain a reviewable enterprise risk register with owners, treatments, and approvals.",
    requirements: ["Entity and assessment scope", "Risk taxonomy and scoring criteria", "Risk owners and target dates"],
    workflow: "risk",
  },
  {
    id: "it-cyber-risk-management",
    group: "Risk",
    title: "IT & Cyber Risk Management",
    summary: "Document technology and cyber risks, related controls, treatment owners, and review decisions.",
    requirements: ["Systems and assessment scope", "Risk criteria and related controls", "Evidence, owners, and treatment dates"],
    workflow: "risk",
  },
  {
    id: "third-party-risk-management",
    group: "Risk",
    title: "Third-Party Risk Management",
    summary: "Track third-party risk assessments, evidence, analyst decisions, and ongoing follow-up.",
    requirements: ["Third-party inventory and relationship", "Assessment scope and risk criteria", "Evidence, analyst, and reviewer"],
    workflow: "third-party",
  },
  {
    id: "entities",
    group: "Governance",
    title: "Entities",
    summary: "Maintain governed entity records, accountable owners, versions, and approval history.",
    requirements: ["Entity identity and jurisdiction", "Record owner and key attributes", "Approvers and supporting records"],
    workflow: "governance",
  },
  {
    id: "policy-manager",
    group: "Governance",
    title: "Policy Manager",
    summary: "Route policy drafts and revisions for approval while retaining versions and attestations.",
    requirements: ["Policy scope and accountable owner", "Draft or current policy version", "Approvers, effective date, and audience"],
    workflow: "governance",
  },
  {
    id: "board-governance",
    group: "Governance",
    title: "Board Governance",
    summary: "Organize board governance records, decisions, action items, and attributed approvals.",
    requirements: ["Board or committee and meeting scope", "Agenda, records, and authorized participants", "Decision owners and follow-up dates"],
    workflow: "governance",
  },
  {
    id: "community-governance",
    group: "Governance",
    title: "Community / Public-Sector Governance",
    summary: "Track public-sector or community governance records, approvals, actions, and exceptions.",
    requirements: ["Entity, jurisdiction, and meeting scope", "Records and authorized participants", "Approval process and action owners"],
    workflow: "governance",
  },
  {
    id: "governance-intelligence",
    group: "Governance",
    title: "Governance Intelligence",
    summary: "Review and summarize approved governance records with links back to their sources.",
    requirements: ["Governance question and entity scope", "Approved source records", "Reviewer for summaries and follow-up"],
    workflow: "governance",
  },
];

export const DEMO_SERVICE_IDS = [
  "journal-entry-analytics",
  "invoice-integrity-review",
  "inventory-asset-controls",
] as const;

export type DemoServiceId = (typeof DEMO_SERVICE_IDS)[number];

export function isDemoServiceId(serviceId: string): serviceId is DemoServiceId {
  return DEMO_SERVICE_IDS.some((demoServiceId) => demoServiceId === serviceId);
}

const REQUEST_STORAGE_KEY = "audit-workspace.requests.v1";

export function getService(serviceId: string): ServiceDefinition | undefined {
  return SERVICE_CATALOG.find((service) => service.id === serviceId);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isRequestActivity(value: unknown): value is RequestActivity {
  return (
    isObject(value) &&
    typeof value.action === "string" &&
    typeof value.occurredAt === "string"
  );
}

function isWorkspaceDocument(value: unknown): value is WorkspaceDocument {
  return (
    isObject(value) &&
    typeof value.id === "string" &&
    typeof value.fileName === "string" &&
    typeof value.contentType === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.modifiedAt === "string"
  );
}

function isWorkspaceRequest(value: unknown): value is WorkspaceRequest {
  if (!isObject(value)) return false;
  const serviceId = value.serviceId;
  const service = typeof serviceId === "string" ? getService(serviceId) : undefined;
  if (!service || !Array.isArray(value.activity)) return false;
  const maxSteps = WORKFLOW_PLANS[service.workflow].steps.length;
  return (
    typeof value.id === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.updatedAt === "string" &&
    (value.lastOpenedAt === undefined || typeof value.lastOpenedAt === "string") &&
    (value.documents === undefined ||
      (Array.isArray(value.documents) && value.documents.every(isWorkspaceDocument))) &&
    typeof value.completedSteps === "number" &&
    Number.isInteger(value.completedSteps) &&
    value.completedSteps >= 0 &&
    value.completedSteps <= maxSteps &&
    value.activity.every(isRequestActivity)
  );
}

export function readWorkspaceRequests(): {
  requests: WorkspaceRequest[];
  warning: string;
} {
  if (typeof window === "undefined") return { requests: [], warning: "" };
  try {
    const stored = window.localStorage.getItem(REQUEST_STORAGE_KEY);
    if (!stored) return { requests: [], warning: "" };
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed) || !parsed.every(isWorkspaceRequest)) {
      return {
        requests: [],
        warning: "Saved prototype requests could not be read. New requests can still be created in this tab.",
      };
    }
    return { requests: parsed, warning: "" };
  } catch {
    return {
      requests: [],
      warning: "This browser could not read saved prototype requests. New requests can still be created in this tab.",
    };
  }
}

export function saveWorkspaceRequests(requests: WorkspaceRequest[]): string {
  if (typeof window === "undefined") {
    return "Requests are only saved in this browser prototype.";
  }
  try {
    window.localStorage.setItem(REQUEST_STORAGE_KEY, JSON.stringify(requests));
    return "";
  } catch {
    return "The browser could not save this request. It remains available only until this tab is closed.";
  }
}

export function createWorkspaceRequest(
  serviceId: string,
  now: string,
  id: string,
): WorkspaceRequest {
  const service = getService(serviceId);
  if (!service) throw new Error(`Unknown service: ${serviceId}`);
  return {
    id,
    serviceId,
    createdAt: now,
    updatedAt: now,
    documents: [],
    completedSteps: 0,
    activity: [{ action: "Request created", occurredAt: now }],
  };
}
