"use client";

import type { AnsichPrimarySignal } from "@/core/ansich/presentation";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichSignalBadge } from "./signal-badge";

interface DiagnosticBlock {
  label: string;
  sublabel?: string | null;
}

/**
 * First-screen diagnostic summary (IA §6.2): three semantic blocks — current
 * activity, why attention is needed, impact — replacing the Belief metadata
 * grid. Each block shows `Insufficient evidence` when unknown, never a green
 * healthy placeholder.
 */
export function AnsichTaskDiagnosticStrip({
  currentActivity,
  primarySignal,
  impact,
}: {
  currentActivity: DiagnosticBlock | null;
  primarySignal: AnsichPrimarySignal | null;
  impact: DiagnosticBlock | null;
}) {
  const { t } = useI18n();

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <DiagnosticCell title={t.ansich.currentActivity} block={currentActivity}>
        {currentActivity ? (
          <>
            <div className="text-sm font-medium">{currentActivity.label}</div>
            {currentActivity.sublabel ? (
              <div className="text-muted-foreground text-xs">
                {currentActivity.sublabel}
              </div>
            ) : null}
          </>
        ) : null}
      </DiagnosticCell>

      <DiagnosticCell title={t.ansich.whyAttention} block>
        <AnsichSignalBadge signal={primarySignal} />
      </DiagnosticCell>

      <DiagnosticCell title={t.ansich.impact} block={impact}>
        {impact ? (
          <>
            <div className="text-sm font-medium">{impact.label}</div>
            {impact.sublabel ? (
              <div className="text-muted-foreground text-xs">
                {impact.sublabel}
              </div>
            ) : null}
          </>
        ) : null}
      </DiagnosticCell>
    </div>
  );
}

function DiagnosticCell({
  title,
  block,
  children,
}: {
  title: string;
  block: DiagnosticBlock | boolean | null;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="rounded-lg border p-3">
      <div className="text-muted-foreground mb-1.5 text-xs font-medium">
        {title}
      </div>
      {block ? (
        children
      ) : (
        <span className="text-muted-foreground border-muted-foreground/40 inline-block border-b border-dashed text-sm">
          {t.ansich.evidenceInsufficient}
        </span>
      )}
    </div>
  );
}
