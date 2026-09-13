"use client";

import React, { useEffect, useState } from "react";
import { ApiError, getProjectContext, listProjectAudit, listProjectFeatures, listProjectHistory, listProjectUpdates } from "../../lib/api";
import type { DailyProjectUpdate, FeatureStatusHistory, ProjectAuditEvent, ProjectContext, ProjectFeature } from "../../types";

interface Props { projectId: string; token: string | null }

const date = (value: string | null) => value ? new Date(value).toLocaleString() : "Unknown";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-slate-800 bg-slate-900 p-4"><h3 className="text-[10px] uppercase tracking-wide text-indigo-400">{title}</h3><div className="mt-3">{children}</div></section>;
}

export function ProjectStatePanel({ projectId, token }: Props) {
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [features, setFeatures] = useState<ProjectFeature[]>([]);
  const [updates, setUpdates] = useState<DailyProjectUpdate[]>([]);
  const [history, setHistory] = useState<FeatureStatusHistory[]>([]);
  const [audit, setAudit] = useState<ProjectAuditEvent[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.all([
      getProjectContext(projectId, token), listProjectFeatures(projectId, token),
      listProjectUpdates(projectId, token), listProjectHistory(projectId, token),
      listProjectAudit(projectId, token),
    ]).then(([nextContext, nextFeatures, nextUpdates, nextHistory, nextAudit]) => {
      if (!active) return;
      setContext(nextContext); setFeatures(nextFeatures); setUpdates(nextUpdates);
      setHistory(nextHistory); setAudit(nextAudit);
      setLoadedProjectId(projectId);
    }).catch((cause: unknown) => {
      if (!active) return;
      setError(cause instanceof ApiError && cause.status === 401 ? "Your assistant session expired. Sign in again to view this project." : "Unable to load project delivery state.");
      setLoadedProjectId(projectId);
    });
    return () => { active = false; };
  }, [projectId, token]);

  if (loadedProjectId !== projectId) return <div className="text-xs text-slate-400">Loading delivery state…</div>;
  if (error || !context) return <div className="rounded-lg border border-rose-900 bg-rose-950/40 p-3 text-xs text-rose-300">{error ?? "Project state unavailable."} {error?.includes("expired") && <a className="ml-1 underline" href="/login">Sign in</a>}</div>;

  return <div className="space-y-4">
    <Section title="Delivery summary"><div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div><p className="text-[10px] text-slate-500">Completion</p><p className="mt-1 text-lg font-semibold">{context.project.completion_percentage}%</p></div>
      <div><p className="text-[10px] text-slate-500">Status</p><p className="mt-1 text-sm font-semibold">{context.project.status.replaceAll("_", " ")}</p></div>
      <div><p className="text-[10px] text-slate-500">Features</p><p className="mt-1 text-lg font-semibold">{features.length}</p></div>
      <div><p className="text-[10px] text-slate-500">Open blockers</p><p className="mt-1 text-lg font-semibold">{context.open_blockers.length}</p></div>
    </div><div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full bg-indigo-500" style={{ width: `${context.project.completion_percentage}%` }} /></div></Section>

    <Section title="Feature status"><div className="flex flex-wrap gap-2 text-[11px]">{Object.entries(context.feature_counts).map(([status, count]) => <span key={status} className="rounded-full border border-slate-700 px-2 py-1 text-slate-300">{status}: {count}</span>)}</div><div className="mt-3 space-y-2">{features.length === 0 ? <p className="text-xs text-slate-500">No features recorded.</p> : features.map((feature) => <div key={feature.id} className="flex items-center justify-between rounded-lg border border-slate-800 px-3 py-2 text-xs"><span>{feature.name}</span><span className="text-slate-400">{feature.status}</span></div>)}</div></Section>

    <Section title="Open blockers">{context.open_blockers.length === 0 ? <p className="text-xs text-slate-500">No open blockers.</p> : <div className="space-y-2">{context.open_blockers.map((blocker) => <div key={blocker.id} className="rounded-lg border border-amber-900/60 bg-amber-950/20 px-3 py-2 text-xs"><div className="flex justify-between gap-3"><span className="font-semibold">{blocker.title}</span><span className="text-amber-300">{blocker.severity}</span></div>{blocker.description && <p className="mt-1 text-slate-400">{blocker.description}</p>}</div>)}</div>}</Section>

    <Section title="Daily updates">{updates.length === 0 ? <p className="text-xs text-slate-500">No daily updates recorded.</p> : <div className="space-y-3">{updates.map((update) => <article key={update.id} className="border-b border-slate-800 pb-3 last:border-0 last:pb-0"><div className="flex justify-between gap-3 text-[10px] text-slate-500"><span>{date(update.created_at)}</span><span>{update.completion_percentage}%</span></div><p className="mt-1 text-xs text-slate-300">{update.summary}</p></article>)}</div>}</Section>

    <Section title="Feature history">{history.length === 0 ? <p className="text-xs text-slate-500">No feature transitions recorded.</p> : <div className="space-y-2">{history.map((item) => <div key={item.id} className="flex justify-between gap-3 text-xs"><span>{item.feature_name}: {item.old_status} → {item.new_status}</span><span className="shrink-0 text-[10px] text-slate-500">{date(item.changed_at)}</span></div>)}</div>}</Section>

    <Section title="Project audit">{audit.length === 0 ? <p className="text-xs text-slate-500">No project audit events recorded.</p> : <div className="space-y-2">{audit.map((event) => <div key={event.id} className="flex justify-between gap-3 text-xs"><span>{event.action}</span><span className="shrink-0 text-[10px] text-slate-500">{date(event.created_at)}</span></div>)}</div>}</Section>
  </div>;
}
