"use client";

import { useAuth } from "../components/auth/auth-provider";
import { ChatInterface } from "../components/chat/chat-interface";

export default function HomePage() {
  const { token, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-950 text-slate-400 text-xs">
        Initializing Agentic Assistant...
      </div>
    );
  }

  return <ChatInterface token={token} />;
}
