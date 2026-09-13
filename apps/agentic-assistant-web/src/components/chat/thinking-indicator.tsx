"use client";

import React from "react";
import type { AgentStep } from "../../types";

export type { AgentStep };

interface ThinkingIndicatorProps {
  /** The pipeline step currently active, or "idle" before first step lands */
  step?: AgentStep;
}

const STEP_CONFIG: Record<
  AgentStep,
  { label: string; icon: string; color: string }
> = {
  rewrite: {
    label: "Rewriting query…",
    icon: "✦",
    color: "text-amber-400",
  },
  retrieve: {
    label: "Retrieving sources…",
    icon: "◈",
    color: "text-sky-400",
  },
  generate: {
    label: "Generating answer…",
    icon: "◉",
    color: "text-indigo-400",
  },
  idle: {
    label: "Thinking…",
    icon: "◌",
    color: "text-slate-400",
  },
};

export function ThinkingIndicator({ step = "idle" }: ThinkingIndicatorProps) {
  const cfg = STEP_CONFIG[step];

  return (
    <div className="flex items-center gap-3 py-1 select-none">
      {/* Spinning gradient ring with bouncing dots inside */}
      <div className="relative w-8 h-8 shrink-0 flex items-center justify-center">
        {/* Outer spinning conic ring */}
        <div
          className="absolute inset-0 rounded-full spin-ring"
          style={{
            background:
              "conic-gradient(from 0deg, #6366f1, #8b5cf6, #06b6d4, #6366f1)",
            padding: "2px",
          }}
        >
          <div className="w-full h-full rounded-full bg-slate-900" />
        </div>

        {/* Bouncing dots in the centre */}
        <div className="relative flex items-end gap-[3px]">
          <span className="dot-1 w-1 h-1 rounded-full bg-indigo-400 block" />
          <span className="dot-2 w-1 h-1 rounded-full bg-violet-400 block" />
          <span className="dot-3 w-1 h-1 rounded-full bg-sky-400 block" />
        </div>
      </div>

      {/* Step label */}
      <div className="flex flex-col gap-0.5">
        <span className={`text-xs font-semibold tracking-wide ${cfg.color}`}>
          {cfg.icon} {cfg.label}
        </span>

        {/* Step progress pills */}
        <div className="flex items-center gap-1.5 mt-0.5">
          {(["rewrite", "retrieve", "generate"] as AgentStep[]).map((s) => {
            const order = ["rewrite", "retrieve", "generate"];
            const stepIdx = order.indexOf(step === "idle" ? "rewrite" : step);
            const pillIdx = order.indexOf(s);
            const isDone = pillIdx < stepIdx;
            const isActive = pillIdx === stepIdx;
            const isPending = pillIdx > stepIdx;

            return (
              <span
                key={s}
                className={[
                  "h-1 rounded-full transition-all duration-500",
                  isActive
                    ? "w-6 step-active bg-indigo-500"
                    : isDone
                    ? "w-3 bg-indigo-800"
                    : isPending
                    ? "w-3 bg-slate-700"
                    : "",
                ].join(" ")}
              />
            );
          })}
          <span className="text-[10px] text-slate-500 ml-1 capitalize">
            {step === "idle" ? "starting" : step}
          </span>
        </div>
      </div>
    </div>
  );
}
