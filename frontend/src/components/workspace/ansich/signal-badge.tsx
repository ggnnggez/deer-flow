"use client";

import {
  AlertTriangleIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  OctagonAlertIcon,
} from "lucide-react";
import type { ComponentType } from "react";

import { Badge } from "@/components/ui/badge";
import type { AnsichPrimarySignal } from "@/core/ansich/presentation";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<AnsichPrimarySignal["severity"], string> = {
  critical: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
  warning:
    "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  info: "border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  none: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
};

const SEVERITY_ICON: Record<
  AnsichPrimarySignal["severity"],
  ComponentType<{ className?: string }>
> = {
  critical: OctagonAlertIcon,
  warning: AlertTriangleIcon,
  info: CircleHelpIcon,
  none: CircleCheckIcon,
};

const KIND_LABEL: Record<
  AnsichPrimarySignal["kind"],
  keyof ReturnType<typeof useI18n>["t"]["ansich"]["signal"]
> = {
  behavior: "behavior",
  budget: "budgetExceeded",
  scope: "scopeRealized",
  heartbeat: "heartbeatStale",
  observability: "observabilityDegraded",
  healthy: "healthy",
};

/**
 * Renders a resolved primary signal (IA §7.1): color always pairs with an icon
 * and text; `null` renders the neutral "Insufficient evidence" state, never a
 * green healthy placeholder.
 */
export function AnsichSignalBadge({
  signal,
  className,
}: {
  signal: AnsichPrimarySignal | null;
  className?: string;
}) {
  const { t } = useI18n();

  if (signal === null) {
    return (
      <Badge
        variant="outline"
        className={cn(
          "text-muted-foreground border-dashed gap-1",
          className,
        )}
      >
        <CircleHelpIcon className="size-3" />
        {t.ansich.evidenceInsufficient}
      </Badge>
    );
  }

  // Budget/scope kinds carry both severities; refine the label by severity.
  const labelKey =
    signal.kind === "budget" && signal.severity === "warning"
      ? "budgetWarning"
      : signal.kind === "scope" && signal.severity === "warning"
        ? "scopeAttempted"
        : KIND_LABEL[signal.kind];
  const Icon = SEVERITY_ICON[signal.severity];

  return (
    <Badge
      variant="outline"
      className={cn("gap-1", SEVERITY_STYLES[signal.severity], className)}
    >
      <Icon className="size-3" />
      {t.ansich.signal[labelKey]}
    </Badge>
  );
}
