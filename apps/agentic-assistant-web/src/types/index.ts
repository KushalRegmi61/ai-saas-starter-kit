export type AssistantRole = "employee" | "lead" | "manager" | "admin";

export type ProjectStatus = "ON_TRACK" | "AT_RISK" | "BLOCKED" | "COMPLETED";
export type FeatureStatus = "DEV" | "QA" | "UAT" | "PROD" | "BUG" | "BLOCKED";
export type BlockerStatus = "OPEN" | "RESOLVED";
export type BlockerSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface AssistantUser {
  id: string;
  email: string;
  role: AssistantRole;
  created_at: string;
}

export interface AssistantProject {
  id: string;
  name: string;
  description: string | null;
  lead_id: string | null;
  status: ProjectStatus;
  completion_percentage: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectFeature {
  id: string;
  project_id: string;
  name: string;
  status: FeatureStatus;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectBlocker {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  severity: BlockerSeverity;
  status: BlockerStatus;
  created_at: string | null;
  resolved_at: string | null;
}

export interface DailyProjectUpdate {
  id: string;
  project_id: string;
  submitted_by: string;
  summary: string;
  completion_percentage: number;
  blocker_ids: string[];
  created_at: string | null;
}

export interface ProjectContext {
  project: AssistantProject;
  feature_counts: Record<FeatureStatus, number>;
  open_blockers: ProjectBlocker[];
  latest_update: DailyProjectUpdate | null;
  scope: { project_id: string };
}

export interface FeatureStatusHistory {
  id: number;
  feature_id: string;
  feature_name: string;
  old_status: FeatureStatus;
  new_status: FeatureStatus;
  changed_by: string;
  changed_at: string | null;
}

export interface ProjectAuditEvent {
  id: number;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  resource: string;
  target_id: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

export interface CreateProjectPayload {
  name: string;
  description?: string | null;
}

export interface UpdateProjectPayload {
  name?: string;
  description?: string | null;
  status?: ProjectStatus;
}

export interface ProjectLeadPayload {
  lead_id: string | null;
}

export interface AssistantProjectToken {
  id: string;
  project_id: string;
  label: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
}

export interface CreateProjectTokenPayload {
  label: string;
}

export interface CreatedProjectToken extends AssistantProjectToken {
  token: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AssistantUser;
}

export interface WebSocketTicketResponse {
  access_token: string;
  token_type: "ws-ticket";
  expires_in: number;
}

/** Retrieval is locked to hybrid (dense + sparse); the UI offers no mode choice. */
export type SearchMode = "hybrid";

export interface AskSocketRequest {
  type: "ask";
  request_id: string;
  question: string;
  top_k?: number;
  search_mode?: SearchMode;
  conversation_id?: string | null;
}

/**
 * Evidence card for one retrieved chunk. The wire sends backend Source
 * dicts ({source, page?, chunk_index?, score?, snippet?}); toEvidence()
 * adapts them here. score/snippet stay optional because the backend may
 * omit them (unscored or pre-snippet history) — the panel hides those parts.
 */
export interface RAGSourceEvidence {
  doc_id: string;
  title: string;
  source: string;
  department?: string;
  access_level?: string;
  score?: number;
  snippet?: string;
}

export interface StreamEventReady {
  type: "ready";
  expires_at: string;
}

export type AgentStep = "rewrite" | "retrieve" | "generate" | "idle";

export interface StreamEventStep {
  type: "step";
  request_id: string;
  // Backend graph node name (classify_intent, agent, tools, ...) or a
  // legacy pipeline stage (rewrite, retrieve, generate). Absent on
  // service-level steps such as memory compaction.
  name?: string;
  text?: string;
  query?: string;
  expanded_queries?: string[];
  sources?: RAGSourceEvidence[];
}

export interface StreamEventToken {
  type: "token";
  request_id: string;
  content: string;
}

export interface StreamEventDone {
  type: "done";
  request_id: string;
  conversation_id: string;
  answer: string;
  sources: RAGSourceEvidence[];
  project_evidence: ProjectToolEvidence[];
}

export type ProjectToolName =
  | "get_project_overview"
  | "get_project_features"
  | "get_project_blockers"
  | "get_project_activity"
  | "search_project_knowledge";

export interface ProjectToolEvidence {
  tool: ProjectToolName;
  status: "resolved" | "unresolved" | "not_found" | "ambiguous" | "forbidden" | "validation_error";
  project_name?: string | null;
  result_count: number;
  summary: Record<string, unknown>;
  records: Array<Record<string, unknown>>;
  message?: string | null;
}

export interface StreamEventError {
  type: "error";
  request_id?: string;
  code: string;
  text: string;
}

export type StreamEvent =
  | StreamEventReady
  | StreamEventStep
  | StreamEventToken
  | StreamEventDone
  | StreamEventError;

export interface ConversationTurn {
  turn_index: number;
  question: string;
  answer: string;
  sources: RAGSourceEvidence[];
  created_at: string;
}

export interface CreateUserPayload {
  email: string;
  password: string;
  role: AssistantRole;
}

export interface IngestionResult {
  doc_id: string;
  source: string;
  chunks_indexed: number;
}

export interface IngestJobAccepted {
  job_id: string;
  status: string;
}

export interface IngestJobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  result?: IngestionResult | null;
  error?: string | null;
}

export interface DeleteSourceResponse {
  purged: boolean;
}

/** One row of the backend documents registry (GET /sources). */
export interface IndexedDocument {
  tenant?: string | null;
  source: string;
  department?: string | null;
  access_level?: string | null;
  chunks_count: number;
  indexed_at?: string | null;
  status?: string | null;
}
