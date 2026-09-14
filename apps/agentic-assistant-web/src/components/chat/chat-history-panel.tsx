"use client";

import React from "react";
import { History, Loader2, MessageSquare, RefreshCw } from "lucide-react";
import type { ConversationSummary } from "../../types";

interface ChatHistoryPanelProps {
  summaries: ConversationSummary[];
  activeId: string | null;
  isLoading: boolean;
  isError: boolean;
  error: string | null;
  selectingId: string | null;
  onRetry: () => void;
  onSelect: (conversationId: string) => void;
}

function formatUpdatedAt(value: string | null): string {
  if (!value) return "Unknown date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ChatHistoryPanel({
  summaries,
  activeId,
  isLoading,
  isError,
  error,
  selectingId,
  onRetry,
  onSelect,
}: ChatHistoryPanelProps) {
  return (
    <aside className="w-64 shrink-0 border-r border-slate-800/80 bg-slate-900/50 hidden md:flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-2 shrink-0">
        <History className="w-4 h-4 text-slate-400" />
        <h2 className="text-xs font-semibold text-slate-200 tracking-wide uppercase">
          Past chats
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto chat-scroll p-2 space-y-1">
        {isLoading && summaries.length === 0 ? (
          <div className="space-y-2 p-1" aria-label="Loading past chats">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-16 rounded-xl bg-slate-800/50 animate-pulse"
              />
            ))}
          </div>
        ) : isError && summaries.length === 0 ? (
          <div className="p-3 text-center space-y-2">
            <p className="text-xs text-rose-400">
              {error ?? "Couldn't load past chats."}
            </p>
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-slate-700 text-slate-300 hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry
            </button>
          </div>
        ) : summaries.length === 0 ? (
          <p className="p-3 text-xs text-slate-500 text-center leading-relaxed">
            No chats yet — ask a question to start your first.
          </p>
        ) : (
          summaries.map((chat) => {
            const isActive = chat.conversation_id === activeId;
            const isSelecting = chat.conversation_id === selectingId;
            return (
              <button
                key={chat.conversation_id}
                type="button"
                disabled={isSelecting}
                onClick={() => onSelect(chat.conversation_id)}
                title={chat.preview || "Open chat"}
                className={`w-full text-left px-3 py-2.5 rounded-xl border transition-colors flex items-start gap-2.5 disabled:cursor-wait ${
                  isActive
                    ? "bg-indigo-950/60 border-indigo-700/50"
                    : "border-transparent hover:bg-slate-800/60"
                }`}
              >
                <MessageSquare className="w-4 h-4 mt-0.5 shrink-0 text-slate-500" />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs text-slate-200 truncate">
                    {chat.preview || "New conversation"}
                  </span>
                  <span className="mt-1 flex items-center gap-2 text-[10px] text-slate-500">
                    <span>
                      {chat.turn_count === 1
                        ? "1 turn"
                        : `${chat.turn_count} turns`}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>{formatUpdatedAt(chat.updated_at)}</span>
                  </span>
                </span>
                {isSelecting && (
                  <Loader2 className="w-3.5 h-3.5 mt-1 shrink-0 animate-spin text-indigo-400" />
                )}
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
