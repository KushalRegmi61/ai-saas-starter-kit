"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  assignProjectLead,
  createProject,
  listAssistantUsers,
  listProjects,
  updateProject,
} from "../../lib/api";
import type {
  AssistantProject,
  AssistantRole,
  AssistantUser,
  ProjectStatus,
} from "../../types";
import { ProjectTokenPanel } from "./project-token-panel";
import { ProjectStatePanel } from "./project-state-panel";

const STATUS_LABELS: Record<ProjectStatus, string> = {
  ON_TRACK: "On track",
  AT_RISK: "At risk",
  BLOCKED: "Blocked",
  COMPLETED: "Completed",
};

interface ProjectsDashboardProps {
  token: string | null;
  role: AssistantRole;
}

export function ProjectsDashboard({ token, role }: ProjectsDashboardProps) {
  const [projects, setProjects] = useState<AssistantProject[]>([]);
  const [leads, setLeads] = useState<AssistantUser[]>([]);
  const [selected, setSelected] = useState<AssistantProject | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canEdit = role === "admin";
  const title = role === "lead" ? "My Projects" : "Projects";
  const leadById = useMemo(() => new Map(leads.map((lead) => [lead.id, lead])), [leads]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const result = await listProjects(token);
      setProjects(result);
      setSelected((current) => result.find((item) => item.id === current?.id) ?? result[0] ?? null);
    } catch {
      setError("Unable to load projects.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!token || role !== "admin") return;
    void listAssistantUsers(token)
      .then((users) => setLeads(users.filter((user) => user.role === "lead")))
      .catch(() => setError("Unable to load lead assignments."));
  }, [role, token]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token || !name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createProject({ name: name.trim(), description: description.trim() || null }, token);
      setName("");
      setDescription("");
      setShowCreate(false);
      await refresh();
    } catch {
      setError("Unable to create project.");
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token || !selected) return;
    setSaving(true);
    setError(null);
    try {
      await updateProject(
        selected.id,
        { name: selected.name, description: selected.description, status: selected.status },
        token
      );
      await refresh();
    } catch {
      setError("Unable to update project.");
    } finally {
      setSaving(false);
    }
  };

  const handleLeadChange = async (nextLeadId: string) => {
    if (!token || !selected) return;
    const currentName = selected.lead_id ? leadById.get(selected.lead_id)?.email : "unassigned";
    const nextName = nextLeadId ? leadById.get(nextLeadId)?.email : "unassigned";
    if (!window.confirm(`Change project lead from ${currentName ?? "current lead"} to ${nextName ?? "unassigned"}?`)) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await assignProjectLead(selected.id, { lead_id: nextLeadId || null }, token);
      await refresh();
    } catch {
      setError("Unable to update project lead.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto space-y-5">
        <header className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-xl font-bold">{title}</h1>
            <p className="text-xs text-slate-400 mt-1">Project ownership and delivery status.</p>
          </div>
          {canEdit && (
            <button type="button" onClick={() => setShowCreate((open) => !open)} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold hover:bg-indigo-500">
              {showCreate ? "Close" : "Create project"}
            </button>
          )}
        </header>

        {error && <div className="rounded-lg border border-rose-900 bg-rose-950/40 p-3 text-xs text-rose-300">{error}</div>}

        {showCreate && canEdit && (
          <form onSubmit={handleCreate} className="rounded-xl border border-slate-800 bg-slate-900 p-4 grid gap-3 md:grid-cols-[1fr_2fr_auto]">
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Project name" maxLength={200} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs" required />
            <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description (optional)" maxLength={2000} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs" />
            <button disabled={saving} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold disabled:opacity-50">Create</button>
          </form>
        )}

        {loading ? (
          <div className="text-xs text-slate-400">Loading projects…</div>
        ) : projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-xs text-slate-400">No projects are assigned or created yet.</div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
            <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
              <div className="grid grid-cols-[1fr_100px_70px_110px] border-b border-slate-800 px-4 py-3 text-[10px] uppercase tracking-wide text-slate-500">
                <span>Project</span><span>Status</span><span>Done</span><span>Updated</span>
              </div>
              {projects.map((project) => (
                <button key={project.id} type="button" onClick={() => setSelected(project)} className={`grid w-full grid-cols-[1fr_100px_70px_110px] border-b border-slate-800 px-4 py-4 text-left text-xs hover:bg-slate-800/70 ${selected?.id === project.id ? "bg-slate-800" : ""}`}>
                  <span className="font-semibold text-slate-100">{project.name}</span>
                  <span className="text-slate-300">{STATUS_LABELS[project.status]}</span>
                  <span className="text-slate-300">{project.completion_percentage}%</span>
                  <span className="truncate text-slate-400">{project.updated_at ? new Date(project.updated_at).toLocaleDateString() : "—"}</span>
                </button>
              ))}
            </div>

            {selected && (
              <div className="space-y-5">
              <form onSubmit={handleSave} className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-indigo-400">Project detail</p>
                  {canEdit ? (
                    <input value={selected.name} onChange={(event) => setSelected({ ...selected, name: event.target.value })} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-semibold" />
                  ) : <h2 className="mt-2 text-lg font-semibold">{selected.name}</h2>}
                </div>
                {canEdit ? (
                  <textarea value={selected.description ?? ""} onChange={(event) => setSelected({ ...selected, description: event.target.value })} className="min-h-24 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs" placeholder="Description" />
                ) : <p className="text-xs text-slate-400">{selected.description || "No description provided."}</p>}
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-xs text-slate-400">Status<select disabled={!canEdit} value={selected.status} onChange={(event) => setSelected({ ...selected, status: event.target.value as ProjectStatus })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"><option value="ON_TRACK">On track</option><option value="AT_RISK">At risk</option><option value="BLOCKED">Blocked</option><option value="COMPLETED">Completed</option></select></label>
                  {canEdit && <label className="text-xs text-slate-400">Lead<select value={selected.lead_id ?? ""} onChange={(event) => void handleLeadChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"><option value="">Unassigned</option>{leads.map((lead) => <option key={lead.id} value={lead.id}>{lead.email}</option>)}</select></label>}
                </div>
                {canEdit && <button disabled={saving} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold disabled:opacity-50">Save changes</button>}
              </form>
              <ProjectTokenPanel projectId={selected.id} role={role} token={token} />
              <ProjectStatePanel projectId={selected.id} token={token} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
