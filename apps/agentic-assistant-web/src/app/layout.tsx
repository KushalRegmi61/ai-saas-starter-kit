import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "../components/auth/auth-provider";
import { AppNav } from "../components/layout/app-nav";

export const metadata: Metadata = {
  title: "Agentic Assistant",
  description: "Enterprise Knowledge Assistant with RAG evidence and streaming chat",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full bg-white text-slate-900">
      <body className="h-full flex flex-col antialiased bg-white text-slate-900">
        <AuthProvider>
          <AppNav />
          <main className="flex-1 overflow-hidden flex flex-col">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
