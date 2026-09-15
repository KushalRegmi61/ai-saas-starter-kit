"use client";

import React, { useState } from "react";
import {
  FileText,
  Shield,
  Sparkles,
  ChevronDown,
  Database,
} from "lucide-react";
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

  if (!sources?.length && !rewriteQuery) return null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden text-xs shadow-sm">
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="w-full px-3.5 py-2.5 flex items-center justify-between bg-slate-50 hover:bg-red-50/60 transition-colors text-slate-700 border-b border-slate-100"
      >
        <div className="flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-red-600" />
          <span className="font-semibold text-slate-900 text-[11px] tracking-wide uppercase">
            RAG Evidence
          </span>
          {sources?.length ? (
            <span className="px-1.5 py-0.5 rounded-full bg-red-50 text-red-700 font-mono text-[10px] border border-red-100">
              {sources.length} src
            </span>
          ) : null}
        </div>
        <ChevronDown
          className={`w-3.5 h-3.5 text-slate-500 transition-transform duration-300 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Smooth accordion via CSS grid rows trick */}
      <div className={`accordion-content ${isOpen ? "open" : ""}`}>
        <div className="accordion-inner">
          <div className="p-3.5 space-y-3 text-slate-600">
            {/* Query rewrite */}
            {rewriteQuery && (
              <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
                <div className="flex items-center gap-1.5 font-semibold text-red-600 text-[10px] mb-1.5 uppercase tracking-widest">
                  <Sparkles className="w-3 h-3" />
                  Query Rewriter
                </div>
                <p className="text-slate-900 font-mono text-[11px] leading-relaxed">
                  &ldquo;{rewriteQuery}&rdquo;
                </p>

                {expandedQueries && expandedQueries.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-slate-200 flex flex-wrap gap-1">
                    <span className="text-[10px] text-slate-500 self-center">
                      expansions:
                    </span>
                    {expandedQueries.map((q, idx) => (
                      <span
                        key={idx}
                        className="px-1.5 py-0.5 rounded-md bg-white text-slate-600 text-[10px] border border-slate-200"
                      >
                        {q}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Retrieved sources */}
            {sources && sources.length > 0 && (
              <div className="space-y-2">
                <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
                  Context Documents
                </div>
                <div className="grid gap-2">
                  {sources.map((src, index) => (
                    <div
                      key={`${src.doc_id}_${index}`}
                      className="source-card p-2.5 rounded-xl bg-white border border-slate-200 hover:border-red-200 transition-colors"
                      style={{ animationDelay: `${index * 50}ms` }}
                    >
                      {/* Source header */}
                      <div className="flex items-center justify-between gap-2 mb-1.5">
                        <div className="flex items-center gap-1.5 font-medium text-slate-900 min-w-0">
                          <FileText className="w-3.5 h-3.5 text-red-600 shrink-0" />
                          <span className="truncate text-[11px]">
                            {src.title || src.source}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {src.department && (
                            <span className="px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-500 text-[10px] border border-slate-200">
                              {src.department}
                            </span>
                          )}
                          {src.access_level && (
                            <span className="px-1.5 py-0.5 rounded-md bg-purple-950/60 text-purple-300 border border-purple-800/40 text-[10px] flex items-center gap-0.5">
                              <Shield className="w-2.5 h-2.5" />
                              {src.access_level}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Snippet */}
                      {src.snippet ? (
                        <p className="text-slate-500 text-[11px] line-clamp-3 italic leading-relaxed pl-4 border-l-2 border-red-200">
                          &ldquo;{src.snippet}&rdquo;
                        </p>
                      ) : (
                        <p className="text-slate-400 text-[11px] italic pl-4 border-l-2 border-slate-200">
                          Snippet unavailable
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
