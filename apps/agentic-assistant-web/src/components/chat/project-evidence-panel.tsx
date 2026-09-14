"use client";

import React, { useState } from "react";
import { CheckCircle2, ChevronDown, ClipboardList, CircleAlert } from "lucide-react";
import type { ProjectToolEvidence } from "../../types";

interface ProjectEvidencePanelProps {
  evidence?: ProjectToolEvidence[];
}

const labels: Record<string, string> = {
  get_project_overview: "Project overview",
  get_project_features: "Project features",
  get_project_blockers: "Project blockers",
  get_project_activity: "Project activity",
  search_project_knowledge: "Project knowledge search",
};

function emptyMessage(item: ProjectToolEvidence): string | null {
  if (item.status !== "resolved" || item.result_count !== 0) return null;
  if (item.tool === "get_project_blockers") return "No blockers currently reported.";
  if (item.tool === "get_project_features") return "No features currently recorded.";
  if (item.tool === "get_project_activity") return "No daily updates or feature history currently recorded.";
  if (item.tool === "search_project_knowledge") return "No supporting project knowledge found.";
  return null;
}

export function ProjectEvidencePanel({ evidence }: ProjectEvidencePanelProps) {
  const [isOpen, setIsOpen] = useState(true);
  if (!evidence?.length) return null;

  return (
    <div className="rounded-xl border border-emerald-900/40 bg-slate-900/60 overflow-hidden text-xs shadow-md">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="w-full px-3.5 py-2.5 flex items-center justify-between bg-slate-800/40 hover:bg-slate-800/70 text-slate-300 border-b border-emerald-900/30"
      >
        <span className="flex items-center gap-2">
          <ClipboardList className="w-3.5 h-3.5 text-emerald-400" />
          <span className="font-semibold text-emerald-200 text-[11px] uppercase tracking-wide">
            Project Evidence
          </span>
          <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 font-mono text-[10px]">
            {evidence.length} tools
          </span>
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      <div className={`accordion-content ${isOpen ? "open" : ""}`}>
        <div className="accordion-inner">
          <div className="p-3.5 space-y-2">
            {evidence.map((item, index) => {
              const empty = emptyMessage(item);
              const failed = item.status !== "resolved";
              return (
                <div key={`${item.tool}-${index}`} className="rounded-lg border border-slate-800/70 bg-slate-950/60 p-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-slate-200 font-medium">
                        {failed ? <CircleAlert className="w-3.5 h-3.5 text-amber-400 shrink-0" /> : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
                        <span>{labels[item.tool] ?? item.tool}</span>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-500 font-mono">source: {item.tool}</p>
                    </div>
                    <span className="shrink-0 rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">
                      {item.status} · {item.result_count} result{item.result_count === 1 ? "" : "s"}
                    </span>
                  </div>

                  {item.project_name && <p className="mt-2 text-[11px] text-slate-400">Project: {item.project_name}</p>}
                  {empty && <p className="mt-2 text-[11px] text-emerald-300">{empty}</p>}
                  {item.message && failed && <p className="mt-2 text-[11px] text-amber-300">{item.message}</p>}
                  {item.records.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      {item.records.map((record, recordIndex) => (
                        <div key={recordIndex} className="border-l-2 border-emerald-500/30 pl-2 text-[11px] text-slate-400">
                          {String(record.title ?? record.name ?? record.summary ?? record.source ?? record.feature_name ?? "Recorded project evidence")}
                          {typeof record.status === "string" && (
                            <span className="ml-2 text-slate-500">({record.status})</span>
                          )}
                          {typeof record.severity === "string" && (
                            <span className="ml-2 text-amber-300">{record.severity}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
