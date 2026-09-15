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
    <nav className="bg-white border-b border-slate-200 px-6 py-2.5 flex items-center justify-between shrink-0 text-xs">
      <div className="flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2 font-bold text-slate-900 text-sm">
          <div className="w-6 h-6 rounded-lg bg-[#e11d24] flex items-center justify-center text-white">
            <Bot className="w-4 h-4" />
          </div>
          <span>Assistant App</span>
        </Link>

        <div className="flex items-center gap-1">
          <Link
            href="/"
            className={`px-3 py-1.5 rounded-lg flex items-center gap-1.5 font-medium transition-colors ${
              pathname === "/"
                ? "bg-red-50 text-red-600 font-semibold"
                : "text-slate-600 hover:text-slate-900"
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
                  ? "bg-red-50 text-red-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900"
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
                  ? "bg-red-50 text-red-600 font-semibold"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Shield className="w-3.5 h-3.5 text-red-600" />
              <span>Admin Console</span>
            </Link>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 text-slate-500">
        <div className="text-right">
          <p className="font-medium text-slate-900">{user.email}</p>
          <p className="text-[10px] uppercase font-bold text-red-600">{user.role}</p>
        </div>
        <button
          type="button"
          onClick={logout}
          title="Sign Out"
          className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-slate-900 transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </nav>
  );
}
