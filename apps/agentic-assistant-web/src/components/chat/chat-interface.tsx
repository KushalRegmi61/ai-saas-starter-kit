"use client";

import React, { useState } from "react";
import { Send, Bot, User, RefreshCw, Sparkles, Sliders, PlusCircle } from "lucide-react";
import { useAssistantChat } from "../../lib/use-assistant-chat";
import { RagEvidencePanel } from "./rag-evidence-panel";
import type { SearchMode } from "../../types";

interface ChatInterfaceProps {
  token: string | null;
}

export function ChatInterface({ token }: ChatInterfaceProps) {
  const [prompt, setPrompt] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("auto");
  const [topK, setTopK] = useState(4);
  const [showSettings, setShowSettings] = useState(false);

  const {
    messages,
    conversationId,
    isConnected,
    isBusy,
    sendAsk,
    resetChat,
  } = useAssistantChat(token);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isBusy) return;
    const q = prompt.trim();
    setPrompt("");
    sendAsk(q, searchMode, topK);
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 font-sans">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-semibold text-base flex items-center gap-2">
              <span>Agentic RAG Assistant</span>
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  isConnected ? "bg-emerald-400 shadow-sm shadow-emerald-400" : "bg-amber-500"
                }`}
              />
            </h1>
            <p className="text-xs text-slate-400">
              {conversationId ? `Conversation #${conversationId.slice(0, 8)}` : "New Session"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2 rounded-lg border text-xs font-medium transition-colors flex items-center gap-1.5 ${
              showSettings
                ? "bg-indigo-900/40 border-indigo-700 text-indigo-200"
                : "border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span className="hidden sm:inline">Retrieval Parameters</span>
          </button>
          <button
            type="button"
            onClick={resetChat}
            className="p-2 rounded-lg border border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-medium transition-colors flex items-center gap-1.5"
          >
            <PlusCircle className="w-4 h-4" />
            <span className="hidden sm:inline">New Chat</span>
          </button>
        </div>
      </header>

      {/* Settings Bar */}
      {showSettings && (
        <div className="px-6 py-3 bg-slate-900 border-b border-slate-800 flex items-center justify-between text-xs text-slate-300 transition-all">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-400">Search Strategy:</span>
              <select
                value={searchMode}
                onChange={(e) => setSearchMode(e.target.value as SearchMode)}
                className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="auto">Auto (Agent Decides)</option>
                <option value="hybrid">Hybrid (Dense + Sparse)</option>
                <option value="vector">Vector Only</option>
                <option value="bm25">BM25 Keyword Only</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-400">Top-K Documents:</span>
              <input
                type="number"
                min={1}
                max={10}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-14 bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-200 text-center focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>
          <span className="text-[11px] text-slate-500">
            RBAC + Authz metadata applied automatically
          </span>
        </div>
      )}

      {/* Message List */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-4 text-slate-400">
            <div className="w-12 h-12 rounded-2xl bg-indigo-950/60 border border-indigo-800/40 flex items-center justify-center text-indigo-400">
              <Sparkles className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-slate-200 font-semibold text-base mb-1">
                Ask the Knowledge Assistant
              </h3>
              <p className="text-xs text-slate-400">
                Ask questions over enterprise documentation. Full RAG evidence, query expansion, and source verification will be rendered for each turn.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 max-w-3xl ${
                msg.role === "user" ? "ml-auto flex-row-reverse" : "mr-auto"
              }`}
            >
              <div
                className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-semibold ${
                  msg.role === "user"
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-800 text-indigo-400 border border-slate-700"
                }`}
              >
                {msg.role === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              <div className="space-y-1.5 min-w-0 max-w-2xl">
                <div
                  className={`p-4 rounded-2xl text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-indigo-600 text-white rounded-tr-none"
                      : "bg-slate-900 border border-slate-800/90 text-slate-200 rounded-tl-none"
                  }`}
                >
                  {msg.content || (msg.isStreaming ? "Thinking & searching..." : "")}
                  {msg.isStreaming && (
                    <span className="inline-block ml-1 animate-pulse text-indigo-400">
                      ▋
                    </span>
                  )}
                  {msg.error && (
                    <p className="text-rose-400 text-xs mt-1">Error: {msg.error}</p>
                  )}
                </div>

                {/* Evidence Section for Assistant Responses */}
                {msg.role === "assistant" && (
                  <RagEvidencePanel
                    rewriteQuery={msg.rewriteQuery}
                    expandedQueries={msg.expandedQueries}
                    sources={msg.sources}
                  />
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Prompt Form */}
      <div className="p-4 border-t border-slate-800/80 bg-slate-900/40 backdrop-blur-md shrink-0">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto relative flex items-center">
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ask a question about your knowledge base..."
            disabled={isBusy}
            className="w-full bg-slate-950 border border-slate-800 rounded-2xl py-3.5 pl-4 pr-12 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/80 disabled:opacity-50 transition-all shadow-inner"
          />
          <button
            type="submit"
            disabled={!prompt.trim() || isBusy}
            className="absolute right-2.5 p-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:hover:bg-indigo-600 transition-colors"
          >
            {isBusy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>
    </div>
  );
}
