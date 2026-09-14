"use client";

import { useCallback, useEffect, useState } from "react";
import { getConversationSummaries } from "./api";
import type { ConversationSummary } from "../types";

interface ChatHistoryState {
  summaries: ConversationSummary[];
  isLoading: boolean;
  isError: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Past-chats list via the normal API client. Plain hook (not react-query):
 * this app has no QueryClientProvider, and use-assistant-chat follows the
 * same useState/useEffect shape. Callers invoke `refetch()` after a new
 * chat lands so the panel stays newest-first without a full reload.
 */
export function useChatHistory(token: string | null): ChatHistoryState {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setIsLoading(true);
    setIsError(false);
    setError(null);
    try {
      setSummaries(await getConversationSummaries(token));
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err.message : "Failed to load chats");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  const refetch = useCallback(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  return { summaries, isLoading, isError, error, refetch };
}
