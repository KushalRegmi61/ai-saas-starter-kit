"use client";

import React, { useState } from "react";
import { FileText, Shield, Sparkles, ChevronDown, ChevronUp, Database } from "lucide-react";
import type { RAGSourceEvidence } from "../../types";

interface RagEvidencePanelProps {
  rewriteQuery?: string;
  expandedQueries?: string[];
  sources?: RAGSourceEvidence[];
}

export function RagEvidencePanel({
  rewriteQuery,
  expandedQueries,
  sources,
}: RagEvidencePanelProps) {
  const [isOpen, setIsOpen] = useState(true);

  if (!sources?.length && !rewriteQuery) {
    return null;
  }

  return (
    <div className="my-3 rounded-xl border border-indigo-900/40 bg-slate-900/60 backdrop-blur-md overflow-hidden text-xs transition-all shadow-lg">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-3.5 py-2.5 flex items-center justify-between bg-slate-800/50 hover:bg-slate-800/80 transition-colors text-slate-300 font-medium border-b border-indigo-900/30"
      >
        <div className="flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-semibold text-indigo-200">RAG Verification &amp; Evidence</span>
          {sources && (
            <span className="px-1.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono text-[10px]">
              {sources.length} sources
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-slate-400">
          <span>{isOpen ? "Hide" : "Inspect"}</span>
          {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </div>
      </button>

      {isOpen && (
        <div className="p-3.5 space-y-3 text-slate-300">
          {/* Query Rewrite Step */}
          {rewriteQuery && (
            <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
              <div className="flex items-center gap-1.5 font-semibold text-indigo-300 text-[11px] mb-1">
                <Sparkles className="w-3 h-3 text-amber-400" />
                <span>Agent Query Rewriter</span>
              </div>
              <p className="text-slate-200 font-mono text-[11px]">&quot;{rewriteQuery}&quot;</p>
              {expandedQueries && expandedQueries.length > 0 && (
                <div className="mt-1.5 pt-1.5 border-t border-slate-800 flex flex-wrap gap-1">
                  <span className="text-[10px] text-slate-400">Expansions:</span>
                  {expandedQueries.map((q, idx) => (
                    <span
                      key={idx}
                      className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]"
                    >
                      {q}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Retrieved Sources */}
          {sources && sources.length > 0 && (
            <div className="space-y-2">
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                Retrieved Context Documents
              </div>
              <div className="grid gap-2">
                {sources.map((src, index) => (
                  <div
                    key={`${src.doc_id}_${index}`}
                    className="p-2.5 rounded-lg bg-slate-950/70 border border-slate-800/80 hover:border-indigo-500/40 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="flex items-center gap-1.5 font-medium text-slate-200 truncate">
                        <FileText className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                        <span className="truncate">{src.title || src.source}</span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {src.department && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                            {src.department}
                          </span>
                        )}
                        {src.access_level && (
                          <span className="px-1.5 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800/50 text-[10px] flex items-center gap-0.5">
                            <Shield className="w-2.5 h-2.5" />
                            {src.access_level}
                          </span>
                        )}
                        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">
                          {(src.score * 100).toFixed(0)}% match
                        </span>
                      </div>
                    </div>
                    <p className="text-slate-400 text-[11px] line-clamp-3 italic leading-relaxed pl-5 border-l-2 border-indigo-500/30">
                      &quot;{src.snippet}&quot;
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
