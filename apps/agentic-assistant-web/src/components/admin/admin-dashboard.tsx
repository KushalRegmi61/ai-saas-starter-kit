"use client";

import React, { useState, useEffect } from "react";
import {
  Users,
  Upload,
  Trash2,
  UserPlus,
  Shield,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import {
  listAssistantUsers,
  createAssistantUser,
  updateAssistantUserRole,
  ingestDocument,
  deleteSource,
} from "../../lib/api";
import type { AssistantUser, AssistantRole } from "../../types";

interface AdminDashboardProps {
  token: string | null;
}

export function AdminDashboard({ token }: AdminDashboardProps) {
  const [activeTab, setActiveTab] = useState<"users" | "ingest">("users");

  // User Management State
  const [users, setUsers] = useState<AssistantUser[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [userError, setUserError] = useState<string | null>(null);
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<AssistantRole>("employee");

  // Ingestion State
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [department, setDepartment] = useState("");
  const [accessLevel, setAccessLevel] = useState("internal");
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<string | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  // Deletion State
  const [deleteSourceInput, setDeleteSourceInput] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState<string | null>(null);

  const fetchUsers = React.useCallback(async () => {
    if (!token) return;
    setIsLoadingUsers(true);
    setUserError(null);
    try {
      const data = await listAssistantUsers(token);
      setUsers(data);
    } catch (err: unknown) {
      setUserError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setIsLoadingUsers(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) {
      void fetchUsers();
    }
  }, [token, fetchUsers]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newEmail || !newPassword) return;
    try {
      await createAssistantUser(
        { email: newEmail, password: newPassword, role: newRole },
        token
      );
      setShowCreateUserModal(false);
      setNewEmail("");
      setNewPassword("");
      setNewRole("employee");
      void fetchUsers();
    } catch (err: unknown) {
      setUserError(err instanceof Error ? err.message : "Failed to create user");
    }
  };

  const handleRoleChange = async (userId: string, role: AssistantRole) => {
    if (!token) return;
    try {
      await updateAssistantUserRole(userId, role, token);
      void fetchUsers();
    } catch (err: unknown) {
      setUserError(err instanceof Error ? err.message : "Failed to update role");
    }
  };

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !file || !source) return;
    setIsIngesting(true);
    setIngestResult(null);
    setIngestError(null);
    try {
      const res = await ingestDocument(
        file,
        source,
        department || undefined,
        accessLevel || undefined,
        token
      );
      setIngestResult(`Indexed ${res.chunks_indexed} chunks for document ${res.doc_id}`);
      setFile(null);
      setSource("");
    } catch (err: unknown) {
      setIngestError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setIsIngesting(false);
    }
  };

  const handleDeleteSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !deleteSourceInput) return;
    setIsDeleting(true);
    setDeleteResult(null);
    try {
      const res = await deleteSource(deleteSourceInput, token);
      setDeleteResult(res.purged ? "Source successfully purged" : "Purge completed with warning");
      setDeleteSourceInput("");
    } catch (err: unknown) {
      setDeleteResult(err instanceof Error ? err.message : "Deletion failed");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 font-sans p-6 overflow-y-auto">
      <div className="max-w-5xl mx-auto w-full space-y-6">
        {/* Title */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Shield className="w-5 h-5 text-indigo-400" />
              <span>Assistant Admin Management</span>
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Identity store role management, RAG document indexing, and source purging.
            </p>
          </div>
          <div className="flex bg-slate-900 border border-slate-800 rounded-xl p-1 text-xs">
            <button
              type="button"
              onClick={() => setActiveTab("users")}
              className={`px-3 py-1.5 rounded-lg transition-colors font-medium ${
                activeTab === "users" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Users & Roles
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("ingest")}
              className={`px-3 py-1.5 rounded-lg transition-colors font-medium ${
                activeTab === "ingest" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              RAG Ingest & Delete
            </button>
          </div>
        </div>

        {/* Users Tab */}
        {activeTab === "users" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <Users className="w-4 h-4 text-indigo-400" />
                <span>Assistant Identity Store Users ({users.length})</span>
              </h2>
              <button
                type="button"
                onClick={() => setShowCreateUserModal(true)}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>Create User</span>
              </button>
            </div>

            {userError && (
              <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800/50 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400" />
                <span>{userError}</span>
              </div>
            )}

            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-900 border-b border-slate-800 uppercase text-[10px] text-slate-400 font-semibold">
                  <tr>
                    <th className="p-3">User ID</th>
                    <th className="p-3">Email</th>
                    <th className="p-3">Role</th>
                    <th className="p-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {isLoadingUsers ? (
                    <tr>
                      <td colSpan={4} className="p-6 text-center text-slate-500 font-sans">
                        Loading users...
                      </td>
                    </tr>
                  ) : users.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="p-6 text-center text-slate-500 font-sans">
                        No assistant users found.
                      </td>
                    </tr>
                  ) : (
                    users.map((u) => (
                      <tr key={u.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="p-3 text-slate-400">{u.id.slice(0, 8)}...</td>
                        <td className="p-3 text-slate-200 font-sans font-medium">{u.email}</td>
                        <td className="p-3">
                          <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-indigo-950 text-indigo-300 border border-indigo-800/50">
                            {u.role}
                          </span>
                        </td>
                        <td className="p-3 text-right font-sans">
                          <select
                            value={u.role}
                            onChange={(e) =>
                              handleRoleChange(u.id, e.target.value as AssistantRole)
                            }
                            className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none"
                          >
                            <option value="employee">employee</option>
                            <option value="lead">lead</option>
                            <option value="manager">manager</option>
                            <option value="admin">admin</option>
                          </select>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Create User Modal */}
        {showCreateUserModal && (
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 max-w-md w-full space-y-4">
              <h3 className="text-base font-semibold text-slate-100">Create Assistant User</h3>
              <form onSubmit={handleCreateUser} className="space-y-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Email Address</label>
                  <input
                    type="email"
                    required
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Role</label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value as AssistantRole)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-slate-200"
                  >
                    <option value="employee">employee</option>
                    <option value="lead">lead</option>
                    <option value="manager">manager</option>
                    <option value="admin">admin</option>
                  </select>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowCreateUserModal(false)}
                    className="px-3 py-2 border border-slate-800 rounded-lg text-slate-400 hover:bg-slate-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-semibold"
                  >
                    Create User
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Ingest & Delete Tab */}
        {activeTab === "ingest" && (
          <div className="grid md:grid-cols-2 gap-6">
            {/* Ingest Form */}
            <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
              <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <Upload className="w-4 h-4 text-indigo-400" />
                <span>Ingest Document</span>
              </h3>
              <form onSubmit={handleIngest} className="space-y-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">File Upload</label>
                  <input
                    type="file"
                    required
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="w-full text-slate-300 bg-slate-950 border border-slate-800 rounded-lg p-2"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Source Name / URI</label>
                  <input
                    type="text"
                    required
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                    placeholder="docs/security-policy.pdf"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-slate-200"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-slate-400 mb-1">Department</label>
                    <select
                      value={department}
                      onChange={(e) => setDepartment(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-slate-200 focus:outline-none"
                    >
                      <option value="">— infer from filename —</option>
                      <option value="general">general</option>
                      <option value="hr">hr</option>
                      <option value="security">security</option>
                      <option value="product">product</option>
                      <option value="finance">finance</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Access Level</label>
                    <select
                      value={accessLevel}
                      onChange={(e) => setAccessLevel(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-slate-200 focus:outline-none"
                    >
                      <option value="public">public</option>
                      <option value="internal">internal</option>
                      <option value="confidential">confidential</option>
                      <option value="restricted">restricted</option>
                    </select>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={isIngesting || !file || !source}
                  className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-semibold disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
                >
                  {isIngesting ? <RefreshCw className="w-4 h-4 animate-spin" /> : "Index Document"}
                </button>
              </form>

              {ingestResult && (
                <div className="p-3 rounded-lg bg-emerald-950/50 border border-emerald-800/50 text-emerald-300 text-xs flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>{ingestResult}</span>
                </div>
              )}
              {ingestError && (
                <div className="p-3 rounded-lg bg-rose-950/50 border border-rose-800/50 text-rose-300 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                  <span>{ingestError}</span>
                </div>
              )}
            </div>

            {/* Purge Source Form */}
            <div className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 space-y-4">
              <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <Trash2 className="w-4 h-4 text-rose-400" />
                <span>Purge Source from RAG Index</span>
              </h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Remove all chunks associated with a source document from both vector storage and keyword indexes.
              </p>
              <form onSubmit={handleDeleteSource} className="space-y-3 text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Source Name / Key</label>
                  <input
                    type="text"
                    required
                    value={deleteSourceInput}
                    onChange={(e) => setDeleteSourceInput(e.target.value)}
                    placeholder="docs/security-policy.pdf"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-slate-200"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isDeleting || !deleteSourceInput}
                  className="w-full py-2.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg font-semibold disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
                >
                  {isDeleting ? <RefreshCw className="w-4 h-4 animate-spin" /> : "Purge Indexed Source"}
                </button>
              </form>

              {deleteResult && (
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 text-xs">
                  {deleteResult}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
