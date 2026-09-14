"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getWsTicket, connectAssistantSocket } from "./api";
import type {
  AgentStep,
  ConversationTurn,
  RAGSourceEvidence,
  ProjectToolEvidence,
  StreamEvent,
} from "../types";

export interface ActiveChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  agentStep?: AgentStep;
  rewriteQuery?: string;
  expandedQueries?: string[];
  sources?: RAGSourceEvidence[];
  projectEvidence?: ProjectToolEvidence[];
  error?: string;
}

/**
 * Wire Source dict ({source, page?, chunk_index?, score?, snippet?}) ->
 * evidence card. Already-shaped cards pass through; missing score/snippet
 * stay undefined so the panel hides those parts instead of rendering NaN.
 */
function toEvidence(raw: unknown): RAGSourceEvidence {
  const src = (raw ?? {}) as Record<string, unknown>;
  const source = typeof src.source === "string" ? src.source : "unknown";
  const page = typeof src.page === "number" ? ` (p. ${src.page})` : "";
  const basename = source.split("/").pop() || source;
  return {
    doc_id: typeof src.doc_id === "string" ? src.doc_id : source,
    title:
      typeof src.title === "string" && src.title
        ? src.title
        : `${basename}${page}`,
    source,
    score: typeof src.score === "number" ? src.score : undefined,
    snippet:
      typeof src.snippet === "string" && src.snippet ? src.snippet : undefined,
  };
}

/** Backend graph node name -> thinking-indicator step. Unmapped names are ignored. */
const NODE_STEP_MAP: Record<string, AgentStep> = {
  classify_intent: "rewrite",
  agent: "retrieve",
  tools: "retrieve",
  agent_budget: "retrieve",
  chitchat_respond: "generate",
  generate_final: "generate",
};

export function useAssistantChat(token: string | null) {
  const [messages, setMessages] = useState<ActiveChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<{
    rewriteQuery?: string;
    expandedQueries?: string[];
    sources?: RAGSourceEvidence[];
  } | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const activeRequestIdRef = useRef<string | null>(null);
  // Synchronous busy flag: React state updates are async, so two rapid
  // submits can both observe isBusy === false. The ref closes that race —
  // only one ask is ever in flight, so tokens can't orphan onto the wrong
  // assistant message.
  const busyRef = useRef(false);

  const handleStreamEvent = useCallback((event: StreamEvent) => {
    if (event.type === "ready") {
      setIsConnected(true);
      return;
    }

    if (event.type === "step") {
      if (event.name === "rewrite" && event.query) {
        setActiveEvidence((prev) => ({
          ...prev,
          rewriteQuery: event.query,
          expandedQueries: event.expanded_queries,
        }));
      } else if (event.name === "retrieve" && event.sources) {
        const stepSources = event.sources;
        setActiveEvidence((prev) => ({
          ...prev,
          sources: stepSources.map(toEvidence),
        }));
      }

      const agentStep =
        event.name !== undefined ? NODE_STEP_MAP[event.name] : undefined;

      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.id === event.request_id) {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              agentStep: agentStep ?? last.agentStep,
              rewriteQuery:
                event.name === "rewrite" ? event.query : last.rewriteQuery,
              expandedQueries:
                event.name === "rewrite"
                  ? event.expanded_queries
                  : last.expandedQueries,
              sources:
                event.name === "retrieve"
                  ? (event.sources ?? []).map(toEvidence)
                  : last.sources,
            },
          ];
        }
        return prev;
      });
    } else if (event.type === "token") {
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.id === event.request_id) {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              content: last.content + event.content,
            },
          ];
        }
        return prev;
      });
    } else if (event.type === "done") {
      setIsBusy(false);
      busyRef.current = false;
      setConversationId(event.conversation_id);
      activeRequestIdRef.current = null;
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.id === event.request_id) {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              content: event.answer || last.content,
              sources: event.sources
                ? event.sources.map(toEvidence)
                : last.sources,
              projectEvidence: event.project_evidence,
              isStreaming: false,
            },
          ];
        }
        return prev;
      });
    } else if (event.type === "error") {
      setIsBusy(false);
      busyRef.current = false;
      activeRequestIdRef.current = null;
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant") {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              error: event.text,
              isStreaming: false,
            },
          ];
        }
        return prev;
      });
    }
  }, []);

  const connectSocket = useCallback(async () => {
    if (!token) return;
    try {
      const ticketRes = await getWsTicket(token);
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      socketRef.current = connectAssistantSocket(ticketRes.access_token, {
        onEvent: handleStreamEvent,
        onReadyStateChange: setIsConnected,
      });
    } catch {
      setIsConnected(false);
    }
  }, [token, handleStreamEvent]);

  useEffect(() => {
    let isMounted = true;
    if (token && !socketRef.current) {
      // Async boundary first: setState only runs in promise callbacks below.
      getWsTicket(token)
        .then((ticketRes) => {
          if (!isMounted) return;
          if (socketRef.current) {
            socketRef.current.close();
            socketRef.current = null;
          }
          socketRef.current = connectAssistantSocket(ticketRes.access_token, {
            onEvent: handleStreamEvent,
            onReadyStateChange: (connected) => {
              if (isMounted) setIsConnected(connected);
            },
          });
        })
        .catch(() => {
          if (isMounted) setIsConnected(false);
        });
    }
    return () => {
      isMounted = false;
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [token, handleStreamEvent]);

  const sendAsk = useCallback(
    // Retrieval is always hybrid; no mode knob reaches the wire.
    (question: string, topK: number = 4) => {
      if (busyRef.current) return;
      busyRef.current = true;

      const requestId = "req_" + Math.random().toString(36).substring(2, 9);
      activeRequestIdRef.current = requestId;

      const userMsg: ActiveChatMessage = {
        id: `user_${requestId}`,
        role: "user",
        content: question,
      };

      const socket = socketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        // Offline: never drop the question silently. Show what happened,
        // kick off a reconnect, and leave the composer usable for retry.
        void connectSocket();
        busyRef.current = false;
        activeRequestIdRef.current = null;
        setMessages((prev) => [
          ...prev,
          userMsg,
          {
            id: requestId,
            role: "assistant",
            content: "",
            isStreaming: false,
            error: "Not connected — reconnecting. Press send to retry.",
          },
        ]);
        return;
      }

      setIsBusy(true);
      setMessages((prev) => [
        ...prev,
        userMsg,
        {
          id: requestId,
          role: "assistant",
          content: "",
          isStreaming: true,
        },
      ]);
      setActiveEvidence(null);

      try {
        socket.send(
          JSON.stringify({
            type: "ask",
            request_id: requestId,
            question,
            top_k: topK,
            search_mode: "hybrid",
            conversation_id: conversationId,
          })
        );
      } catch {
        // Socket died between the OPEN check and the send: mark the
        // just-appended assistant message instead of throwing.
        busyRef.current = false;
        activeRequestIdRef.current = null;
        setIsBusy(false);
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === "assistant" && last.id === requestId) {
            return [
              ...prev.slice(0, -1),
              {
                ...last,
                isStreaming: false,
                error: "Send failed — the connection dropped. Press send to retry.",
              },
            ];
          }
          return prev;
        });
      }
    },
    [connectSocket, conversationId]
  );

  const loadHistory = useCallback((turns: ConversationTurn[], convId: string) => {
    setConversationId(convId);
    const historyMsgs: ActiveChatMessage[] = [];
    turns.forEach((turn) => {
      historyMsgs.push({
        id: `hist_u_${turn.turn_index}`,
        role: "user",
        content: turn.question,
      });
      historyMsgs.push({
        id: `hist_a_${turn.turn_index}`,
        role: "assistant",
        content: turn.answer,
        sources: turn.sources,
        isStreaming: false,
      });
    });
    setMessages(historyMsgs);
  }, []);

  const resetChat = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setActiveEvidence(null);
    setIsBusy(false);
    busyRef.current = false;
    activeRequestIdRef.current = null;
  }, []);

  return {
    messages,
    conversationId,
    isConnected,
    isBusy,
    activeEvidence,
    sendAsk,
    loadHistory,
    resetChat,
  };
}
