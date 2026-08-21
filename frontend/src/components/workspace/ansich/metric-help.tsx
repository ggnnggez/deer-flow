"use client";

import { CircleHelpIcon } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * The keyboard-focusable help trigger every Ansich metric label carries: a
 * localized tooltip explaining what the metric means and how to read it.
 *
 * One component for every metric wall (System details drawer, Observability
 * health panel) so the affordance a reader learns in one place behaves the same
 * in the other — same icon, same focus ring, same accessible name.
 */
export function AnsichMetricHelp({ description }: { description: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={description}
          className="hover:text-foreground focus-visible:ring-ring rounded-sm outline-none focus-visible:ring-2"
        >
          <CircleHelpIcon className="size-3.5" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">{description}</TooltipContent>
    </Tooltip>
  );
}
