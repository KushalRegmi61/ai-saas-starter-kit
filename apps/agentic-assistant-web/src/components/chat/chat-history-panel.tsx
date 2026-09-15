"use client";

import React from "react";
import { History, Loader2, RefreshCw } from "lucide-react";
import type { ConversationSummary } from "../../types";

interface ChatHistoryPanelProps {
  summaries: ConversationSummary[];
  activeId: string | null;
  isLoading: boolean;
  isError: boolean;
  error: string | null;
  selectingId: string | null;
  open: boolean;
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
  open,
  onRetry,
  onSelect,
}: ChatHistoryPanelProps) {
  return (
    <aside
      className={`shrink-0 border-slate-200 bg-slate-50/80 hidden md:flex flex-col min-h-0 overflow-hidden transition-[width] duration-200 ease-out ${
        open ? "w-64 border-r" : "w-0 border-r-0"
      }`}
    >
      <div className="px-4 py-3 border-b border-slate-200 flex items-center gap-2 shrink-0 w-64">
        <History className="w-4 h-4 text-slate-400" />
        <h2 className="text-xs font-semibold text-slate-900 tracking-wide uppercase">
          Past chats
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden chat-scroll p-2 space-y-0.5 w-64">
        {isLoading && summaries.length === 0 ? (
          <div className="space-y-2 p-1" aria-label="Loading past chats">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-16 rounded-xl bg-slate-100 animate-pulse"
              />
            ))}
          </div>
        ) : isError && summaries.length === 0 ? (
          <div className="p-3 text-center space-y-2">
            <p className="text-xs text-red-600">
              {error ?? "Couldn't load past chats."}
            </p>
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 transition-colors"
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
                className={`w-full text-left px-3 py-2 rounded-lg transition-colors flex items-center gap-2 disabled:cursor-wait ${
                  isActive ? "bg-red-50 border border-red-100" : "hover:bg-slate-100 border border-transparent"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-xs text-slate-900 truncate">
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
                  <Loader2 className="w-3.5 h-3.5 mt-1 shrink-0 animate-spin text-red-600" />
                )}
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
