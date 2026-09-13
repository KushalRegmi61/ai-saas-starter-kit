export type AssistantRole = "employee" | "lead" | "manager" | "admin";

export type ProjectStatus = "ON_TRACK" | "AT_RISK" | "BLOCKED" | "COMPLETED";

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
  created_at: string | null;
  updated_at: string | null;
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
