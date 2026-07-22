"use client";

import { ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

/**
 * A labeled, collapsible section for the Evidence view (IA §4/§6.3): the
 * densest L3 surface is grouped into named subsections so timeline, context &
 * lineage, agent release and belief audit stay scannable and individually
 * foldable instead of one long stack.
 */
export function AnsichEvidenceSection({
  title,
  description,
  defaultOpen = false,
  children,
  className,
}: {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className={cn("group/es rounded-lg border", className)}
    >
      <CollapsibleTrigger className="hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center gap-2 rounded-lg px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none">
        <ChevronRightIcon className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[state=open]/es:rotate-90" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{title}</span>
          {description ? (
            <span className="text-muted-foreground block text-xs">
              {description}
            </span>
          ) : null}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-4 py-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
