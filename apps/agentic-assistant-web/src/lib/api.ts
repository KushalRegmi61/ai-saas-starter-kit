import type {
  AssistantUser,
  CreateUserPayload,
  DeleteSourceResponse,
  IngestionResult,
  LoginResponse,
  WebSocketTicketResponse,
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

export async function ingestDocument(
  file: File,
  source: string,
  department: string | undefined,
  accessLevel: string | undefined,
  token: string
): Promise<IngestionResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);
  if (department) formData.append("department", department);
  if (accessLevel) formData.append("access_level", accessLevel);

  return fetchAssistant<IngestionResult>(
    "/ingest",
    {
      method: "POST",
      body: formData,
    },
    token
  );
}

export async function deleteSource(
  source: string,
  token: string
): Promise<DeleteSourceResponse> {
  const query = new URLSearchParams({ source }).toString();
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
