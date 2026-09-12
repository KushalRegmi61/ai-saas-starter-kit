export type AssistantRole = "employee" | "lead" | "manager" | "admin";

export interface AssistantUser {
  id: string;
  email: string;
  role: AssistantRole;
  created_at: string;
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

export type SearchMode = "auto" | "vector" | "bm25" | "hybrid";

export interface AskSocketRequest {
  type: "ask";
  request_id: string;
  question: string;
  top_k?: number;
  search_mode?: SearchMode;
  conversation_id?: string | null;
}

export interface RAGSourceEvidence {
  doc_id: string;
  title: string;
  source: string;
  department?: string;
  access_level?: string;
  score: number;
  snippet: string;
}

export interface StreamEventReady {
  type: "ready";
  expires_at: string;
}

export interface StreamEventStep {
  type: "step";
  request_id: string;
  name: "rewrite" | "retrieve" | "generate";
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

export interface DeleteSourceResponse {
  purged: boolean;
}
