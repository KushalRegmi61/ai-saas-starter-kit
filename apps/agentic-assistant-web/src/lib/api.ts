import type {
  AssistantUser,
  AssistantProject,
  AssistantProjectToken,
  ProjectAuditEvent,
  ProjectContext,
  ProjectFeature,
  DailyProjectUpdate,
  FeatureStatusHistory,
  CreateUserPayload,
  CreateProjectPayload,
  CreateProjectTokenPayload,
  CreatedProjectToken,
  DeleteSourceResponse,
  IndexedDocument,
  IngestJobAccepted,
  IngestJobStatus,
  LoginResponse,
  WebSocketTicketResponse,
  ProjectLeadPayload,
  UpdateProjectPayload,
  ConversationSummary,
  ConversationTurn,
  StreamEvent,
} from "../types";

// The agentic-assistant backend serves both REST and the /ask WebSocket.
// Local default is :8000 (see services/agentic-assistant); override with
// NEXT_PUBLIC_ASSISTANT_API_URL (documented in .env.example).
export const ASSISTANT_API_BASE =
  process.env.NEXT_PUBLIC_ASSISTANT_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchAssistant<T>(
  path: string,
  init?: RequestInit,
  token?: string | null
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${ASSISTANT_API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Failed to reach the Agentic Assistant server", 0);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : `Request failed with status ${res.status}`;
    throw new ApiError(detail, res.status);
  }

  return res.json();
}

export async function loginAssistant(email: string, password: string): Promise<LoginResponse> {
  return fetchAssistant<LoginResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function getWsTicket(token: string): Promise<WebSocketTicketResponse> {
  return fetchAssistant<WebSocketTicketResponse>(
    "/auth/ws-ticket",
    { method: "POST" },
    token
  );
}

export async function listAssistantUsers(token: string): Promise<AssistantUser[]> {
  return fetchAssistant<AssistantUser[]>("/auth/users", { method: "GET" }, token);
}

export async function createAssistantUser(
  payload: CreateUserPayload,
  token: string
): Promise<AssistantUser> {
  return fetchAssistant<AssistantUser>(
    "/auth/users",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    token
  );
}

export async function updateAssistantUserRole(
  userId: string,
  role: string,
  token: string
): Promise<AssistantUser> {
  return fetchAssistant<AssistantUser>(
    `/auth/users/${userId}/role`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
    token
  );
}

export async function listProjects(token: string): Promise<AssistantProject[]> {
  return fetchAssistant<AssistantProject[]>("/projects", { method: "GET" }, token);
}

export async function getProject(projectId: string, token: string): Promise<AssistantProject> {
  return fetchAssistant<AssistantProject>(`/projects/${projectId}`, { method: "GET" }, token);
}

export async function getProjectContext(projectId: string, token: string): Promise<ProjectContext> {
  return fetchAssistant<ProjectContext>(`/projects/${projectId}/context`, { method: "GET" }, token);
}

export async function listProjectFeatures(projectId: string, token: string): Promise<ProjectFeature[]> {
  return fetchAssistant<ProjectFeature[]>(`/projects/${projectId}/features`, { method: "GET" }, token);
}

export async function listProjectUpdates(projectId: string, token: string): Promise<DailyProjectUpdate[]> {
  return fetchAssistant<DailyProjectUpdate[]>(`/projects/${projectId}/updates?limit=50`, { method: "GET" }, token);
}

export async function listProjectHistory(projectId: string, token: string): Promise<FeatureStatusHistory[]> {
  return fetchAssistant<FeatureStatusHistory[]>(`/projects/${projectId}/history?limit=100`, { method: "GET" }, token);
}

export async function listProjectAudit(projectId: string, token: string): Promise<ProjectAuditEvent[]> {
  return fetchAssistant<ProjectAuditEvent[]>(`/projects/${projectId}/audit?limit=100`, { method: "GET" }, token);
}

export async function createProject(
  payload: CreateProjectPayload,
  token: string
): Promise<AssistantProject> {
  return fetchAssistant<AssistantProject>(
    "/projects",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    token
  );
}

export async function updateProject(
  projectId: string,
  payload: UpdateProjectPayload,
  token: string
): Promise<AssistantProject> {
  return fetchAssistant<AssistantProject>(
    `/projects/${projectId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    token
  );
}

export async function assignProjectLead(
  projectId: string,
  payload: ProjectLeadPayload,
  token: string
): Promise<AssistantProject> {
  return fetchAssistant<AssistantProject>(
    `/projects/${projectId}/lead`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    token
  );
}

export async function listProjectTokens(
  projectId: string,
  token: string
): Promise<AssistantProjectToken[]> {
  return fetchAssistant<AssistantProjectToken[]>(
    `/projects/${projectId}/tokens`,
    { method: "GET" },
    token
  );
}

export async function createProjectToken(
  projectId: string,
  payload: CreateProjectTokenPayload,
  token: string
): Promise<CreatedProjectToken> {
  return fetchAssistant<CreatedProjectToken>(
    `/projects/${projectId}/tokens`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    token
  );
}

export async function revokeProjectToken(
  projectId: string,
  tokenId: string,
  token: string
): Promise<AssistantProjectToken> {
  return fetchAssistant<AssistantProjectToken>(
    `/projects/${projectId}/tokens/${tokenId}/revoke`,
    { method: "POST" },
    token
  );
}

export async function ingestDocument(
  file: File,
  source: string,
  department: string | undefined,
  accessLevel: string | undefined,
  token: string
): Promise<IngestJobAccepted> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);
  if (department) formData.append("department", department);
  if (accessLevel) formData.append("access_level", accessLevel);

  return fetchAssistant<IngestJobAccepted>(
    "/ingest",
    {
      method: "POST",
      body: formData,
    },
    token
  );
}

export async function getIngestStatus(
  jobId: string,
  token: string
): Promise<IngestJobStatus> {
  return fetchAssistant<IngestJobStatus>(
    `/ingest/${jobId}`,
    { method: "GET" },
    token
  );
}

export async function listSources(token: string): Promise<IndexedDocument[]> {
  return fetchAssistant<IndexedDocument[]>(
    "/sources",
    { method: "GET" },
    token
  );
}

export async function deleteSource(
  source: string,
  token: string,
  tenant?: string | null
): Promise<DeleteSourceResponse> {
  const params: Record<string, string> = { source };
  if (tenant) params.tenant = tenant;
  const query = new URLSearchParams(params).toString();
  return fetchAssistant<DeleteSourceResponse>(
    `/sources?${query}`,
    { method: "DELETE" },
    token
  );
}

export async function getConversationHistory(
  conversationId: string,
  token: string
): Promise<ConversationTurn[]> {
  return fetchAssistant<ConversationTurn[]>(
    `/conversations/${conversationId}`,
    { method: "GET" },
    token
  );
}

export async function getConversationSummaries(
  token: string
): Promise<ConversationSummary[]> {
  return fetchAssistant<ConversationSummary[]>(
    "/conversations",
    { method: "GET" },
    token
  );
}

export interface AssistantSocketHandlers {
  onEvent: (event: StreamEvent) => void;
  onReadyStateChange: (connected: boolean) => void;
}

export function assistantWsUrl(): string {
  return ASSISTANT_API_BASE.replace(/^http/, "ws") + "/ask";
}

/** Single connection path for the /ask WebSocket: auth on open, JSON parse per frame. */
export function connectAssistantSocket(
  ticket: string,
  handlers: AssistantSocketHandlers
): WebSocket {
  const ws = new WebSocket(assistantWsUrl());

  ws.onopen = () => {
    ws.send(
      JSON.stringify({
        type: "auth",
        access_token: ticket,
      })
    );
  };

  ws.onmessage = (event) => {
    try {
      handlers.onEvent(JSON.parse(event.data) as StreamEvent);
    } catch {
      // Ignore malformed frames; the stream continues.
    }
  };

  ws.onclose = () => handlers.onReadyStateChange(false);
  ws.onerror = () => handlers.onReadyStateChange(false);

  return ws;
}
