"use client";

import { type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

export type ConversationView = "chat" | "trajectory";

export function ConversationViewToggle({
  chatLabel,
  className,
  onChange,
  trajectoryLabel,
  value,
}: {
  chatLabel: string;
  className?: string;
  onChange: (view: ConversationView) => void;
  trajectoryLabel: string;
  value: ConversationView;
}) {
  const selectAdjacent = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    const next = value === "chat" ? "trajectory" : "chat";
    onChange(next);
    const sibling =
      event.currentTarget.parentElement?.querySelector<HTMLElement>(
        `[data-conversation-view="${next}"]`,
      );
    sibling?.focus();
  };

  return (
    <div
      aria-label="Conversation view"
      className={cn(
        "bg-muted/60 flex h-8 items-center rounded-lg p-0.5",
        className,
      )}
      role="tablist"
    >
      {(
        [
          ["chat", chatLabel],
          ["trajectory", trajectoryLabel],
        ] as const
      ).map(([view, label]) => {
        const selected = value === view;
        return (
          <button
            key={view}
            aria-selected={selected}
            className={cn(
              "text-muted-foreground hover:text-foreground h-7 rounded-md px-2.5 text-xs font-medium transition-colors",
              selected && "bg-background text-foreground shadow-xs",
            )}
            data-conversation-view={view}
            role="tab"
            tabIndex={selected ? 0 : -1}
            type="button"
            onClick={() => onChange(view)}
            onKeyDown={selectAdjacent}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
