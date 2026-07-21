"use client";

import { ChevronRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/**
 * L3 audit disclosure (IA §4.1/§6.5): UUIDs, hashes, resolver/producer
 * versions, causation/lineage edges and payload access live behind an explicit
 * "Technical evidence" toggle so they never compete with L1 state on a first
 * screen. Collapsed by default.
 */
export function AnsichTechnicalEvidence({
  label,
  children,
  className,
}: {
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <Collapsible className={cn("group/te", className)}>
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring flex items-center gap-1 rounded text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none">
        <ChevronRightIcon className="size-3 transition-transform group-data-[state=open]/te:rotate-90" />
        {label ?? t.ansich.technicalEvidence}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2">{children}</CollapsibleContent>
    </Collapsible>
  );
}
