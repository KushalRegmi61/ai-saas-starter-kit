"use client";

import { useAuth } from "../../components/auth/auth-provider";
import { AdminDashboard } from "../../components/admin/admin-dashboard";

export default function AdminPage() {
  const { token, isAdmin, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-950 text-slate-400 text-xs">
        Loading Admin Console...
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-950 text-slate-400 text-xs p-6 text-center space-y-2">
        <h2 className="text-rose-400 font-semibold text-sm">Access Denied</h2>
        <p>You must have an Admin role to view the Assistant Admin Console.</p>
      </div>
    );
  }

  return <AdminDashboard token={token} />;
}
