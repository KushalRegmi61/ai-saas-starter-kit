"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getWsTicket, ASSISTANT_API_BASE } from "./api";
import type {
  ConversationTurn,
  RAGSourceEvidence,
  SearchMode,
  StreamEvent,
} from "../types";

export interface ActiveChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  rewriteQuery?: string;
  expandedQueries?: string[];
  sources?: RAGSourceEvidence[];
  error?: string;
}

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
        setActiveEvidence((prev) => ({
          ...prev,
          sources: event.sources,
        }));
      }

      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.id === event.request_id) {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              rewriteQuery:
                event.name === "rewrite" ? event.query : last.rewriteQuery,
              expandedQueries:
                event.name === "rewrite"
                  ? event.expanded_queries
                  : last.expandedQueries,
              sources:
                event.name === "retrieve" ? event.sources : last.sources,
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
              sources: event.sources || last.sources,
              isStreaming: false,
            },
          ];
        }
        return prev;
      });
    } else if (event.type === "error") {
      setIsBusy(false);
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
      const wsUrl = ASSISTANT_API_BASE.replace(/^http/, "ws") + "/ask";
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            type: "auth",
            access_token: ticketRes.access_token,
          })
        );
      };

      ws.onmessage = (event) => {
        try {
          const data: StreamEvent = JSON.parse(event.data);
          handleStreamEvent(data);
        } catch {
          // Parse failure
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        socketRef.current = null;
      };

      ws.onerror = () => {
        setIsConnected(false);
      };

      socketRef.current = ws;
    } catch {
      setIsConnected(false);
    }
  }, [token, handleStreamEvent]);

  useEffect(() => {
    let isMounted = true;
    if (token && !socketRef.current) {
      getWsTicket(token)
        .then((ticketRes) => {
          if (!isMounted) return;
          const wsUrl = ASSISTANT_API_BASE.replace(/^http/, "ws") + "/ask";
          const ws = new WebSocket(wsUrl);

          ws.onopen = () => {
            ws.send(
              JSON.stringify({
                type: "auth",
                access_token: ticketRes.access_token,
              })
            );
          };

          ws.onmessage = (event) => {
            try {
              const data: StreamEvent = JSON.parse(event.data);
              handleStreamEvent(data);
            } catch {
              // Parse failure
            }
          };

          ws.onclose = () => {
            if (isMounted) setIsConnected(false);
            socketRef.current = null;
          };

          ws.onerror = () => {
            if (isMounted) setIsConnected(false);
          };

          socketRef.current = ws;
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
    (question: string, searchMode: SearchMode = "auto", topK: number = 4) => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        void connectSocket();
        return;
      }
      if (isBusy) return;

      const requestId = "req_" + Math.random().toString(36).substring(2, 9);
      activeRequestIdRef.current = requestId;
      setIsBusy(true);

      const userMsg: ActiveChatMessage = {
        id: `user_${requestId}`,
        role: "user",
        content: question,
      };

      const assistantMsg: ActiveChatMessage = {
        id: requestId,
        role: "assistant",
        content: "",
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setActiveEvidence(null);

      socketRef.current.send(
        JSON.stringify({
          type: "ask",
          request_id: requestId,
          question,
          top_k: topK,
          search_mode: searchMode,
          conversation_id: conversationId,
        })
      );
    },
    [connectSocket, conversationId, isBusy]
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
