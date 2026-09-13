"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, FolderKanban, Shield, LogOut, MessageSquare } from "lucide-react";
import { useAuth } from "../auth/auth-provider";

export function AppNav() {
  const { user, isAdmin, logout } = useAuth();
  const pathname = usePathname();

  if (!user || pathname === "/login") return null;

  return (
    <nav className="bg-slate-900 border-b border-slate-800 px-6 py-2.5 flex items-center justify-between shrink-0 text-xs">
      <div className="flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2 font-bold text-white text-sm">
          <div className="w-6 h-6 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
            <Bot className="w-4 h-4" />
          </div>
          <span>Assistant App</span>
        </Link>

        <div className="flex items-center gap-1">
          <Link
            href="/"
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 font-medium transition-colors ${
              pathname === "/"
                ? "bg-slate-800 text-indigo-300 font-semibold"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Chat</span>
          </Link>

          {user && user.role !== "employee" && (
            <Link
              href="/projects"
              className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 font-medium transition-colors ${
                pathname === "/projects"
                  ? "bg-slate-800 text-indigo-300 font-semibold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <FolderKanban className="w-3.5 h-3.5" />
              <span>Projects</span>
            </Link>
          )}

          {isAdmin && (
            <Link
              href="/admin"
              className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 font-medium transition-colors ${
                pathname === "/admin"
                  ? "bg-slate-800 text-indigo-300 font-semibold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Shield className="w-3.5 h-3.5 text-indigo-400" />
              <span>Admin Console</span>
            </Link>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 text-slate-400">
        <div className="text-right">
          <p className="font-medium text-slate-200">{user.email}</p>
          <p className="text-[10px] uppercase font-bold text-indigo-400">{user.role}</p>
        </div>
        <button
          type="button"
          onClick={logout}
          title="Sign Out"
          className="p-1.5 rounded-lg border border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </nav>
  );
}
