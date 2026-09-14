"use client";

import React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-1 text-lg font-semibold text-slate-100">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-4 text-base font-semibold text-slate-100">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-sm font-semibold text-indigo-200">{children}</h3>
  ),
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-indigo-400/60 pl-3 text-slate-400">
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-indigo-300 underline decoration-indigo-400/50 underline-offset-2 hover:text-indigo-200"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-4 border-slate-700" />,
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-slate-700">
      <table className="min-w-full divide-y divide-slate-700 text-left text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="bg-slate-800/70 px-3 py-2 font-semibold text-slate-200">{children}</th>,
  td: ({ children }) => <td className="border-t border-slate-800 px-3 py-2 align-top">{children}</td>,
  code: ({ children, className, ...props }) => {
    const isBlock = Boolean(className) || String(children).includes("\n");
    if (!isBlock) {
      return (
        <code className="rounded bg-slate-800 px-1.5 py-0.5 text-[0.9em] text-indigo-200" {...props}>
          {children}
        </code>
      );
    }

    return (
      <pre className="my-3 overflow-x-auto rounded-lg border border-slate-700 bg-slate-950/80 p-3 text-xs leading-5 text-slate-300">
        <code className={className}>{String(children).replace(/\n$/, "")}</code>
      </pre>
    );
  },
};

interface MarkdownMessageProps {
  content: string;
}

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <div className="markdown-message leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
