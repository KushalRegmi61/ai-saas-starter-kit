"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  createProjectToken,
  listProjectTokens,
  revokeProjectToken,
} from "../../lib/api";
import type {
  AssistantProjectToken,
  AssistantRole,
  CreatedProjectToken,
} from "../../types";

interface ProjectTokenPanelProps {
  projectId: string;
  role: AssistantRole;
  token: string | null;
}

const PROJECT_MCP_URL =
  process.env.NEXT_PUBLIC_PROJECT_MCP_URL ||
  "https://agentic-assistant-sha-42efdfb.onrender.com/mcp";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export function ProjectTokenPanel({ projectId, role, token }: ProjectTokenPanelProps) {
  const [tokens, setTokens] = useState<AssistantProjectToken[]>([]);
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<CreatedProjectToken | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canManage = role === "lead" || role === "admin";

  const refresh = useCallback(async () => {
    if (!token || !canManage) return;
    setLoading(true);
    try {
      setTokens(await listProjectTokens(projectId, token));
      setError(null);
    } catch {
      setError("Unable to load coding-agent credentials.");
    } finally {
      setLoading(false);
    }
  }, [canManage, projectId, token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token || !label.trim()) return;
    setSaving(true);
    try {
      const result = await createProjectToken(projectId, { label: label.trim() }, token);
      setCreated(result);
      setLabel("");
      await refresh();
    } catch {
      setError("Unable to generate the coding-agent credential.");
    } finally {
      setSaving(false);
    }
  };

  const handleRevoke = async (item: AssistantProjectToken) => {
    if (!token || !window.confirm(`Revoke ${item.label}? Existing agent connections will stop working.`)) {
      return;
    }
    setSaving(true);
    try {
      await revokeProjectToken(projectId, item.id, token);
      await refresh();
    } catch {
      setError("Unable to revoke the credential.");
    } finally {
      setSaving(false);
    }
  };

  if (!canManage) return null;

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 space-y-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-red-600">Coding-agent access</p>
        <p className="mt-1 text-xs text-slate-500">
          Credentials can access and update only this project and expire after 30 days.
        </p>
      </div>

      {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</p>}

      {created && (
        <div className="rounded-lg border border-amber-700 bg-amber-950/30 p-4 space-y-3">
          <p className="text-xs font-semibold text-amber-200">Copy this credential now</p>
          <p className="text-[11px] text-amber-300">It will not be shown again. Never commit it or paste it into shared chat.</p>
          <code className="block break-all rounded bg-[#0f172a] p-3 text-[11px] text-slate-200">{created.token}</code>
          <button type="button" onClick={() => void navigator.clipboard?.writeText(created.token)} className="rounded bg-amber-700 px-3 py-2 text-xs font-semibold hover:bg-amber-600">Copy token</button>
          <pre className="overflow-x-auto rounded bg-[#0f172a] p-3 text-[10px] text-slate-300">{`export PROJECT_MCP_TOKEN="paste-token-here"

# Claude Code
claude mcp add --transport http project-status ${PROJECT_MCP_URL} --header "Authorization: Bearer $PROJECT_MCP_TOKEN"

# Codex
[mcp_servers.project_status]
url = "${PROJECT_MCP_URL}"
bearer_token_env_var = "PROJECT_MCP_TOKEN"

# OpenCode
{
  "mcp": {
    "project-status": {
      "type": "remote",
      "url": "${PROJECT_MCP_URL}",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:PROJECT_MCP_TOKEN}" }
    }
  }
}`}</pre>
          <button type="button" onClick={() => setCreated(null)} className="text-xs text-slate-400 underline">Close one-time display</button>
        </div>
      )}

      {role === "lead" && (
        <form onSubmit={handleCreate} className="flex gap-2">
          <input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={100} placeholder="Token label, e.g. Claude laptop" className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-900" required />
          <button disabled={saving} className="rounded-lg bg-[#e11d24] px-3 py-2 text-xs font-semibold text-white hover:bg-[#c81119] disabled:opacity-50">Generate</button>
        </form>
      )}

      {loading ? <p className="text-xs text-slate-500">Loading credentials…</p> : tokens.length === 0 ? <p className="text-xs text-slate-500">No credentials generated.</p> : (
        <div className="space-y-2">
          {tokens.map((item) => {
            const inactive = Boolean(item.revoked_at) || new Date(item.expires_at) <= new Date();
            return (
              <div key={item.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-3 text-xs">
                <div><p className="font-semibold text-slate-900">{item.label}</p><p className="text-[10px] text-slate-500">Expires {formatDate(item.expires_at)} · Last used {formatDate(item.last_used_at)}</p></div>
                <div className="flex items-center gap-2"><span className={inactive ? "text-slate-500" : "text-emerald-600"}>{item.revoked_at ? "Revoked" : inactive ? "Expired" : "Active"}</span>{!item.revoked_at && <button type="button" disabled={saving} onClick={() => void handleRevoke(item)} className="text-red-600 underline disabled:opacity-50">Revoke</button>}</div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
