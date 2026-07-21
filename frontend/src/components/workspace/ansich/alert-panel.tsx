"use client";

import { AlertTriangleIcon, ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useAnsichAlert,
  useAnsichAlertWorkflow,
  useAnsichTaskAction,
} from "@/core/ansich/hooks";
import {
  formatAnsichTimestamp,
  getAlertPresentationCategory,
} from "@/core/ansich/presentation";
import type {
  AnsichAlertSummary,
  AnsichBeliefAssertion,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichObservationTimeline } from "./observation-timeline";
import { AnsichTechnicalEvidence } from "./technical-evidence";

type AlertAction = "acknowledge" | "dismiss" | "interrupt" | "rollback";

export function AnsichAlertPanel({
  alerts,
  isPending,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  alerts: AnsichAlertSummary[];
  isPending: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}) {
  const { t, locale } = useI18n();
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);

  return (
    <section aria-labelledby="ansich-alert-list-title">
      <h2 id="ansich-alert-list-title" className="sr-only">
        {t.ansich.alerts}
      </h2>
      <div className="text-muted-foreground mb-2 hidden grid-cols-[minmax(12rem,1.4fr)_minmax(9rem,1fr)_auto_auto_auto_auto] gap-3 px-4 text-xs font-medium md:grid">
        <span>{t.ansich.alertType}</span>
        <span>{t.ansich.task}</span>
        <span>{t.ansich.severity}</span>
        <span>{t.ansich.workflow}</span>
        <span>{t.ansich.asOf}</span>
        <span className="w-4" />
      </div>
      <div className="space-y-2">
        {isPending ? (
          <AlertListSkeleton />
        ) : alerts.length ? (
          alerts.map((alert) => (
            <button
              key={alert.alert_id}
              type="button"
              onClick={() => setSelectedAlertId(alert.alert_id)}
              className="bg-card hover:bg-accent/40 focus-visible:ring-ring grid w-full gap-3 rounded-lg border p-4 text-left shadow-xs transition-colors focus-visible:ring-2 focus-visible:outline-none md:grid-cols-[minmax(12rem,1.4fr)_minmax(9rem,1fr)_auto_auto_auto_auto] md:items-center"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">
                  {t.ansich.alertTypeLabel[alert.alert_type]}
                </span>
                <span className="text-muted-foreground mt-1 block text-xs">
                  {
                    t.ansich.alertCategory[
                      getAlertPresentationCategory(alert.alert_type)
                    ]
                  }
                  {alert.shadow ? ` · ${t.ansich.shadow}` : ""}
                </span>
              </span>
              <span className="truncate font-mono text-xs">
                {alert.subject_id}
              </span>
              <AlertSeverityBadge severity={alert.severity} />
              <Badge variant="outline">
                {t.ansich.alertWorkflow[alert.workflow_state]}
              </Badge>
              <span className="text-muted-foreground text-xs tabular-nums">
                {formatAnsichTimestamp(alert.as_of, locale)}
              </span>
              <ExternalLinkIcon className="text-muted-foreground size-4" />
            </button>
          ))
        ) : (
          <div className="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
            {t.ansich.noAlerts}
          </div>
        )}
        {hasNextPage ? (
          <div className="flex justify-center pt-2">
            <Button
              variant="outline"
              disabled={isFetchingNextPage}
              onClick={onLoadMore}
            >
              {isFetchingNextPage ? t.ansich.loading : t.common.loadMore}
            </Button>
          </div>
        ) : null}
      </div>
      <AlertDetailDialog
        alertId={selectedAlertId}
        onClose={() => setSelectedAlertId(null)}
      />
    </section>
  );
}

function AlertDetailDialog({
  alertId,
  onClose,
}: {
  alertId: string | null;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const detailQuery = useAnsichAlert(alertId);
  const workflowMutation = useAnsichAlertWorkflow();
  const taskActionMutation = useAnsichTaskAction();
  const [pendingAction, setPendingAction] = useState<AlertAction | null>(null);
  const [dismissalReason, setDismissalReason] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const detail = detailQuery.data?.alert;
  const mutationPending =
    workflowMutation.isPending || taskActionMutation.isPending;

  function closeConfirmation() {
    if (mutationPending) return;
    setPendingAction(null);
    setDismissalReason("");
    setIdempotencyKey(null);
  }

  function selectAction(action: AlertAction) {
    setPendingAction(action);
    setDismissalReason("");
    setIdempotencyKey(
      action === "interrupt" || action === "rollback"
        ? globalThis.crypto.randomUUID()
        : null,
    );
  }

  async function confirmAction() {
    if (!detail || !pendingAction) return;
    if (pendingAction === "dismiss" && !dismissalReason.trim()) return;
    try {
      if (pendingAction === "acknowledge" || pendingAction === "dismiss") {
        await workflowMutation.mutateAsync({
          alertId: detail.alert.alert_id,
          workflowVersion: detail.alert.workflow_version,
          action: pendingAction,
          reason:
            pendingAction === "dismiss" ? dismissalReason.trim() : undefined,
        });
        toast.success(t.ansich.workflowActionSucceeded);
      } else {
        const response = await taskActionMutation.mutateAsync({
          taskId: detail.alert.subject_id,
          action: pendingAction,
          idempotencyKey: idempotencyKey ?? globalThis.crypto.randomUUID(),
        });
        if (response.audit_status === "degraded") {
          toast.warning(t.ansich.operatorActionAuditDegraded);
        } else {
          toast.success(t.ansich.operatorActionSucceeded);
        }
      }
      setPendingAction(null);
      setDismissalReason("");
      setIdempotencyKey(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.ansich.loadFailed);
    }
  }

  const actionWarning =
    pendingAction === "interrupt"
      ? t.ansich.interruptWarning
      : pendingAction === "rollback"
        ? t.ansich.rollbackWarning
        : null;

  return (
    <>
      <Dialog
        open={Boolean(alertId)}
        onOpenChange={(open) => {
          if (!open && !mutationPending) onClose();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{t.ansich.alertDetails}</DialogTitle>
            <DialogDescription className="font-mono break-all">
              {alertId}
            </DialogDescription>
          </DialogHeader>
          {detailQuery.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          ) : detailQuery.error ? (
            <Alert variant="destructive">
              <AlertTriangleIcon />
              <AlertTitle>{t.ansich.loadFailed}</AlertTitle>
              <AlertDescription>{detailQuery.error.message}</AlertDescription>
            </Alert>
          ) : detail ? (
            <div className="space-y-6">
              {/* 1. Event summary + 2. severity / workflow / active */}
              <div className="space-y-2">
                <h3 className="text-base font-semibold">
                  {t.ansich.alertTypeLabel[detail.alert.alert_type]}
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <AlertSeverityBadge severity={detail.alert.severity} />
                  <Badge variant="outline">
                    {t.ansich.alertWorkflow[detail.alert.workflow_state]}
                  </Badge>
                  {detail.alert.workflow_state === "open" ? (
                    <Badge
                      variant="outline"
                      className="border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300"
                    >
                      {t.ansich.active}
                    </Badge>
                  ) : null}
                </div>
              </div>

              {/* 3. impact / current activity — the owning Task */}
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" asChild>
                  <Link
                    href={`/workspace/ansich/tasks/${encodeURIComponent(detail.alert.subject_id)}`}
                  >
                    {t.ansich.task}
                    <ExternalLinkIcon />
                  </Link>
                </Button>
                {/* 4. operator actions */}
                {detail.available_actions.map((action) => (
                  <Button
                    key={action}
                    size="sm"
                    variant={action === "rollback" ? "destructive" : "outline"}
                    disabled={mutationPending}
                    onClick={() => selectAction(action)}
                  >
                    {t.ansich[action]}
                  </Button>
                ))}
              </div>

              {/* 5. why it triggered — source belief */}
              <BeliefSection
                title={t.ansich.sourceBelief}
                beliefs={[detail.source_belief]}
              />

              {/* 6. observation timeline */}
              <section className="space-y-3">
                <h3 className="font-semibold">{t.ansich.evidence}</h3>
                <AnsichObservationTimeline observations={detail.evidence} />
              </section>

              {/* 7. rule / version / config hash / workflow history — folded */}
              <AnsichTechnicalEvidence>
                <div className="space-y-6">
                  <div className="grid gap-3 rounded-lg border p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
                    <DetailField
                      label={t.ansich.category}
                      value={
                        t.ansich.alertCategory[
                          getAlertPresentationCategory(detail.alert.alert_type)
                        ]
                      }
                    />
                    <DetailField
                      label={t.ansich.episode}
                      value={String(detail.alert.episode)}
                    />
                    <DetailField
                      label={t.ansich.evidenceCount}
                      value={String(detail.alert.evidence_count)}
                    />
                    <DetailField
                      label={t.ansich.rule}
                      value={`${detail.alert.rule.name}@${detail.alert.rule.version}`}
                      mono
                    />
                    <DetailField
                      label={t.ansich.configHash}
                      value={detail.alert.rule_config_hash}
                      mono
                    />
                    <DetailField
                      label={t.ansich.asOf}
                      value={formatAnsichTimestamp(detail.alert.as_of, locale)}
                    />
                    {detail.alert.resolution_reason ? (
                      <DetailField
                        label={t.ansich.resolutionReason}
                        value={detail.alert.resolution_reason}
                      />
                    ) : null}
                    {detail.alert.dismissal_reason ? (
                      <DetailField
                        label={t.ansich.dismissalReason}
                        value={detail.alert.dismissal_reason}
                      />
                    ) : null}
                  </div>

                  <BeliefSection
                    title={t.ansich.currentBehavior}
                    beliefs={detail.current_beliefs.filter(
                      (belief) => belief.field_name === "behavior",
                    )}
                  />

                  <section className="space-y-3">
                    <h3 className="font-semibold">
                      {t.ansich.workflowHistory}
                    </h3>
                    {detail.workflow_history.length ? (
                      <ol className="space-y-2">
                        {detail.workflow_history.map((event) => (
                          <li
                            key={event.event_id}
                            className="grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-[1fr_auto]"
                          >
                            <span>
                              {event.action}:{" "}
                              {t.ansich.alertWorkflow[event.from_state]} →{" "}
                              {t.ansich.alertWorkflow[event.to_state]}
                              {event.reason ? ` · ${event.reason}` : ""}
                            </span>
                            <span className="text-muted-foreground text-xs">
                              {event.operator_id
                                ? `${t.ansich.operator}: ${event.operator_id} · `
                                : ""}
                              {formatAnsichTimestamp(event.occurred_at, locale)}
                            </span>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <div className="text-muted-foreground text-sm">—</div>
                    )}
                  </section>
                </div>
              </AnsichTechnicalEvidence>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(pendingAction)}
        onOpenChange={(open) => {
          if (!open) closeConfirmation();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.ansich.confirmAction}</DialogTitle>
            <DialogDescription>
              {pendingAction ? t.ansich[pendingAction] : ""}
            </DialogDescription>
          </DialogHeader>
          {actionWarning ? (
            <Alert variant="destructive">
              <AlertTriangleIcon />
              <AlertTitle>{t.ansich.confirmAction}</AlertTitle>
              <AlertDescription>{actionWarning}</AlertDescription>
            </Alert>
          ) : null}
          {pendingAction === "dismiss" ? (
            <div className="space-y-2">
              <label
                htmlFor="ansich-dismissal-reason"
                className="text-sm font-medium"
              >
                {t.ansich.dismissReason}
              </label>
              <Textarea
                id="ansich-dismissal-reason"
                value={dismissalReason}
                disabled={mutationPending}
                onChange={(event) => setDismissalReason(event.target.value)}
                aria-invalid={!dismissalReason.trim()}
              />
              {!dismissalReason.trim() ? (
                <p className="text-destructive text-xs">
                  {t.ansich.dismissReasonRequired}
                </p>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={mutationPending}
              onClick={closeConfirmation}
            >
              {t.ansich.cancel}
            </Button>
            <Button
              variant={pendingAction === "rollback" ? "destructive" : "default"}
              disabled={
                mutationPending ||
                (pendingAction === "dismiss" && !dismissalReason.trim())
              }
              onClick={() => void confirmAction()}
            >
              {mutationPending
                ? t.ansich.loading
                : pendingAction
                  ? t.ansich[pendingAction]
                  : t.ansich.confirmAction}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function BeliefSection({
  title,
  beliefs,
}: {
  title: string;
  beliefs: AnsichBeliefAssertion[];
}) {
  const { t } = useI18n();
  return (
    <section className="space-y-3">
      <h3 className="font-semibold">{title}</h3>
      {beliefs.length ? (
        beliefs.map((belief) => (
          <div
            key={belief.assertion_id}
            className="space-y-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap justify-between gap-2 text-sm">
              <span className="font-mono font-medium">{belief.field_name}</span>
              <span className="text-muted-foreground">
                {belief.assessor.name}@{belief.assessor.version} ·{" "}
                {t.ansich.configHash}:{" "}
                <span className="font-mono">{belief.config_hash}</span>
              </span>
            </div>
            <pre className="bg-muted/60 overflow-x-auto rounded-md p-3 text-xs">
              {JSON.stringify(belief.value, null, 2)}
            </pre>
          </div>
        ))
      ) : (
        <div className="text-muted-foreground text-sm">
          {t.ansich.evidenceInsufficient}
        </div>
      )}
    </section>
  );
}

function AlertSeverityBadge({
  severity,
}: {
  severity: AnsichAlertSummary["severity"];
}) {
  const { t } = useI18n();
  return (
    <Badge variant={severity === "critical" ? "destructive" : "secondary"}>
      {t.ansich.alertSeverity[severity]}
    </Badge>
  );
}

function DetailField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className={mono ? "mt-1 font-mono text-xs break-all" : "mt-1"}>
        {value}
      </div>
    </div>
  );
}

function AlertListSkeleton() {
  return Array.from({ length: 4 }, (_, index) => (
    <Skeleton key={index} className="h-20 w-full" />
  ));
}
