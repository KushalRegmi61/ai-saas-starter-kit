"use client";

import { useAuth } from "../../components/auth/auth-provider";
import { ProjectsDashboard } from "../../components/projects/projects-dashboard";

export default function ProjectsPage() {
  const { token, user, isLoading } = useAuth();

  if (isLoading) {
    return <div className="flex-1 grid place-items-center bg-white text-slate-500 text-xs">Loading projects…</div>;
  }

  if (!user || user.role === "employee") {
    return (
      <div className="flex-1 grid place-items-center bg-white text-rose-600 text-xs">
        You do not have access to projects.
      </div>
    );
  }

  return <ProjectsDashboard token={token} role={user.role} />;
}
