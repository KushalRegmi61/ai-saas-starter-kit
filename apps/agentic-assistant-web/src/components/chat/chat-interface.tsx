"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  Bot,
  User,
  Loader2,
  Sparkles,
  Sliders,
  PlusCircle,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useAssistantChat } from "../../lib/use-assistant-chat";
import { RagEvidencePanel } from "./rag-evidence-panel";
import { ProjectEvidencePanel } from "./project-evidence-panel";
import { MarkdownMessage } from "./markdown-message";
import { ThinkingIndicator } from "./thinking-indicator";
import type { AgentStep } from "./thinking-indicator";

interface ChatInterfaceProps {
  token: string | null;
}

/** Derive the active agent step: live node mapping wins, metadata heuristic as fallback */
function deriveStep(msg: {
  agentStep?: AgentStep;
  rewriteQuery?: string;
  sources?: unknown[];
  content: string;
}): AgentStep {
  if (msg.agentStep && msg.agentStep !== "idle") return msg.agentStep;
  if (msg.content.length > 0) return "generate";
  if (msg.sources && msg.sources.length > 0) return "generate";
  if (msg.rewriteQuery) return "retrieve";
  return "rewrite";
}

export function ChatInterface({ token }: ChatInterfaceProps) {
  const [prompt, setPrompt] = useState("");
  const [topK, setTopK] = useState(4);
  const [showSettings, setShowSettings] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { messages, conversationId, isConnected, isBusy, sendAsk, resetChat } =
    useAssistantChat(token);

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isBusy) return;
    const q = prompt.trim();
    setPrompt("");
    sendAsk(q, topK);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 font-sans">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="px-5 py-3.5 border-b border-slate-800/80 bg-slate-900/70 backdrop-blur-md flex items-center justify-between shrink-0 gap-4">
        <div className="flex items-center gap-3 min-w-0">
          {/* Logo */}
          <div className="w-9 h-9 shrink-0 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/25">
            <Bot className="w-5 h-5 text-white" />
          </div>

          <div className="min-w-0">
            <h1 className="font-semibold text-sm sm:text-base leading-tight flex items-center gap-2 truncate">
              Agentic RAG Assistant
              <span
                title={isConnected ? "Connected" : "Connecting…"}
                className={`shrink-0 inline-block w-2 h-2 rounded-full transition-colors ${
                  isConnected
                    ? "bg-emerald-400 shadow-sm shadow-emerald-400/60"
                    : "bg-amber-400 animate-pulse"
                }`}
              />
            </h1>
            <p className="text-[11px] text-slate-500 truncate">
              {conversationId
                ? `Session · ${conversationId.slice(0, 8)}`
                : "New session"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-lg border text-xs font-medium transition-all flex items-center gap-1.5 ${
              showSettings
                ? "bg-indigo-900/50 border-indigo-600/60 text-indigo-200"
                : "border-slate-800 hover:bg-slate-800/80 text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span className="hidden sm:inline">Retrieval</span>
          </button>

          <button
            type="button"
            onClick={resetChat}
            className="p-2 rounded-lg border border-slate-800 hover:bg-slate-800/80 text-slate-400 hover:text-slate-200 text-xs font-medium transition-all flex items-center gap-1.5"
          >
            <PlusCircle className="w-4 h-4" />
            <span className="hidden sm:inline">New chat</span>
          </button>
        </div>
      </header>

      {/* ── Settings bar ──────────────────────────────────────── */}
      <div
        className={`overflow-hidden transition-all duration-300 ${
          showSettings ? "max-h-20 opacity-100" : "max-h-0 opacity-0"
        }`}
      >
        <div className="px-5 py-3 bg-slate-900/80 border-b border-slate-800/60 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-300">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-slate-400 font-medium">Strategy:</span>
              <span className="px-2 py-1.5 text-xs text-slate-200">
                Hybrid (Dense + Sparse)
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-400 font-medium">Top-K:</span>
              <input
                type="number"
                min={1}
                max={10}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-14 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-200 text-center focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>
          </div>
          <span className="text-[10px] text-slate-600">
            RBAC + Authz metadata applied automatically
          </span>
        </div>
      </div>

      {/* ── Message list ──────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto chat-scroll px-4 sm:px-6 py-6 space-y-6">
        {messages.length === 0 ? (
          /* Empty state */
          <div className="h-full flex flex-col items-center justify-center text-center max-w-sm mx-auto space-y-5 pb-16">
            <div className="relative">
              <div className="w-16 h-16 rounded-2xl bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center">
                <Sparkles className="w-7 h-7 text-indigo-400" />
              </div>
              <div className="absolute -inset-2 rounded-3xl bg-indigo-500/10 blur-xl" />
            </div>
            <div>
              <h3 className="text-slate-100 font-semibold text-base mb-2">
                Ask the Knowledge Assistant
              </h3>
              <p className="text-xs text-slate-500 leading-relaxed">
                Ask questions over enterprise documentation. Full RAG evidence,
                query expansion, and source verification rendered for each turn.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {[
                "Summarise Q3 highlights",
                "What's our data retention policy?",
                "Who owns the GDPR process?",
              ].map((hint) => (
                <button
                  key={hint}
                  type="button"
                  onClick={() => {
                    setPrompt(hint);
                  }}
                  className="px-3 py-1.5 rounded-full text-xs bg-slate-800/60 border border-slate-700/60 text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={msg.id}
              className={`msg-enter flex gap-3 ${
                msg.role === "user"
                  ? "ml-auto flex-row-reverse max-w-xl"
                  : "mr-auto max-w-2xl"
              }`}
              style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
            >
              {/* Avatar */}
              <div
                className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                  msg.role === "user"
                    ? "bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-md shadow-indigo-500/20"
                    : "bg-slate-800/80 text-indigo-400 border border-slate-700/60"
                }`}
              >
                {msg.role === "user" ? (
                  <User className="w-4 h-4" />
                ) : (
                  <Bot className="w-4 h-4" />
                )}
              </div>

              <div className="space-y-2 min-w-0 flex-1">
                {/* Bubble */}
                <div
                  className={`px-4 py-3 rounded-2xl text-sm leading-relaxed break-words ${
                    msg.role === "user"
                      ? "bg-gradient-to-br from-indigo-600 to-violet-600 text-white rounded-tr-sm shadow-md shadow-indigo-500/20"
                      : "bg-slate-900/80 border border-slate-800/70 text-slate-200 rounded-tl-sm"
                  }`}
                >
                  {/* Thinking state — no content yet, streaming */}
                  {msg.role === "assistant" && msg.isStreaming && !msg.content ? (
                    <ThinkingIndicator step={deriveStep(msg)} />
                  ) : (
                    <>
                      <MarkdownMessage content={msg.content} />
                      {msg.isStreaming && (
                        <span className="blink inline-block ml-0.5 -mb-0.5 w-[2px] h-[1em] bg-indigo-400 rounded-sm" />
                      )}
                    </>
                  )}

                  {msg.error && (
                    <p className="text-rose-400 text-xs mt-2 flex items-center gap-1">
                      <span>⚠</span> {msg.error}
                    </p>
                  )}
                </div>

                {/* RAG Evidence (assistant only) */}
                {msg.role === "assistant" && (
                  <>
                    <RagEvidencePanel
                      rewriteQuery={msg.rewriteQuery}
                      expandedQueries={msg.expandedQueries}
                      sources={msg.sources}
                    />
                    <ProjectEvidencePanel evidence={msg.projectEvidence} />
                  </>
                )}
              </div>
            </div>
          ))
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Disconnected banner ───────────────────────────────── */}
      {!isConnected && (
        <div className="px-5 py-2 bg-amber-950/40 border-t border-amber-800/30 flex items-center gap-2 text-xs text-amber-400 shrink-0">
          <WifiOff className="w-3.5 h-3.5 shrink-0" />
          <span>Connecting to assistant…</span>
          <span className="ml-auto flex gap-0.5">
            <span className="dot-1 w-1 h-1 rounded-full bg-amber-400 block" />
            <span className="dot-2 w-1 h-1 rounded-full bg-amber-400 block" />
            <span className="dot-3 w-1 h-1 rounded-full bg-amber-400 block" />
          </span>
        </div>
      )}

      {/* ── Input area ────────────────────────────────────────── */}
      <div className="px-4 sm:px-6 py-4 border-t border-slate-800/70 bg-slate-900/50 backdrop-blur-md shrink-0">
        <form
          onSubmit={handleSubmit}
          className="max-w-4xl mx-auto flex items-end gap-3"
        >
          {/* Textarea wrapper with animated busy ring */}
          <div
            className={`relative flex-1 rounded-2xl transition-all duration-300 ${
              isBusy
                ? "p-[1.5px] input-busy-ring shadow-lg shadow-indigo-500/10"
                : "p-[1px] bg-slate-700/40"
            }`}
          >
            <textarea
              rows={1}
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                // Auto-resize up to ~5 lines
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`;
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                isBusy
                  ? "Agent is thinking…"
                  : "Ask a question  ·  Shift+Enter for new line"
              }
              disabled={isBusy}
              className="w-full bg-slate-950 rounded-[calc(1rem-1.5px)] py-3 pl-4 pr-4 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none leading-relaxed disabled:cursor-not-allowed transition-colors"
              style={{ minHeight: "44px" }}
            />
          </div>

          {/* Send / loading button */}
          <button
            type="submit"
            disabled={!prompt.trim() || isBusy}
            className="shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white disabled:opacity-40 disabled:hover:from-indigo-600 disabled:hover:to-violet-600 transition-all shadow-md shadow-indigo-500/20 flex items-center justify-center"
          >
            {isBusy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </form>

        {/* Bottom caption */}
        <p className="mt-2 text-center text-[10px] text-slate-600">
          {isConnected ? (
            <span className="flex items-center justify-center gap-1">
              <Wifi className="w-3 h-3 text-emerald-600" />
              Streaming via WebSocket
            </span>
          ) : (
            "Waiting for connection…"
          )}
        </p>
      </div>
    </div>
  );
}
