"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAnsichContentPayload } from "@/core/ansich/api";
import { useAnsichStepContext, useAnsichTaskSteps } from "@/core/ansich/hooks";
import type {
  AnsichContextItem,
  AnsichContextSnapshot,
  AnsichLlmAttempt,
  AnsichStep,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichStepsPanel({ taskId }: { taskId: string }) {
  const { t } = useI18n();
  const query = useAnsichTaskSteps(taskId);

  if (query.isPending) return <Skeleton className="h-48 w-full" />;
  if (query.error) return <InlineError message={query.error.message} />;

  const steps = query.data?.items ?? [];
  const systemOperations = query.data?.system_operations ?? [];
  return (
    <div className="space-y-5">
      {steps.length === 0 ? (
        <EmptyState message={t.ansich.noSteps} />
      ) : (
        <div className="space-y-3">
          {steps.map((step) => (
            <StepCard key={step.step_id} step={step} />
          ))}
        </div>
      )}

      <section className="space-y-3" aria-labelledby="ansich-system-operations">
        <h3 id="ansich-system-operations" className="font-semibold">
          {t.ansich.systemOperations} ({systemOperations.length})
        </h3>
        {systemOperations.length === 0 ? (
          <EmptyState message={t.ansich.noSystemOperations} />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {systemOperations.map((attempt) => (
              <Card key={attempt.attempt_id} className="border-dashed py-4">
                <CardContent className="space-y-2 px-4 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">
                      {attempt.operation_kind ?? "other"}
                    </span>
                    <AttemptStatus attempt={attempt} />
                  </div>
                  <code className="text-muted-foreground block text-xs break-all">
                    {attempt.operation_id}
                  </code>
                  <div className="text-muted-foreground text-xs">
                    {t.ansich.attempt} {attempt.attempt_no}
                    {attempt.latency_ms === null
                      ? ""
                      : ` · ${attempt.latency_ms} ms`}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export function AnsichContextPanel({ taskId }: { taskId: string }) {
  const { t } = useI18n();
  const stepsQuery = useAnsichTaskSteps(taskId);
  const eligibleSteps = (stepsQuery.data?.items ?? []).filter(
    (step) => step.effective_context_snapshot_id !== null,
  );
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  useEffect(() => {
    if (
      eligibleSteps.length > 0 &&
      !eligibleSteps.some((step) => step.step_id === selectedStepId)
    ) {
      setSelectedStepId(eligibleSteps[0]?.step_id ?? null);
    }
  }, [eligibleSteps, selectedStepId]);

  const contextQuery = useAnsichStepContext(selectedStepId);
  if (stepsQuery.isPending) return <Skeleton className="h-48 w-full" />;
  if (stepsQuery.error)
    return <InlineError message={stepsQuery.error.message} />;
  if (eligibleSteps.length === 0)
    return <EmptyState message={t.ansich.noContext} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {eligibleSteps.map((step) => (
          <Button
            key={step.step_id}
            size="sm"
            variant={selectedStepId === step.step_id ? "default" : "outline"}
            onClick={() => setSelectedStepId(step.step_id)}
          >
            {t.ansich.step} #{step.step_seq}
          </Button>
        ))}
      </div>
      {contextQuery.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : contextQuery.error ? (
        <InlineError message={contextQuery.error.message} />
      ) : contextQuery.data ? (
        <ContextSnapshotCard context={contextQuery.data.context} />
      ) : null}
    </div>
  );
}

function StepCard({ step }: { step: AnsichStep }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-base">
            {t.ansich.step} #{step.step_seq}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{step.actor_kind}</Badge>
            <Badge variant="secondary">{step.result ?? step.status}</Badge>
          </div>
        </div>
        <code className="text-muted-foreground text-xs break-all">
          {step.step_id}
        </code>
      </CardHeader>
      <CardContent className="space-y-3">
        {step.attempts.map((attempt) => (
          <div
            key={attempt.attempt_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
          >
            <div>
              <span className="font-medium">
                {t.ansich.attempt} {attempt.attempt_no}
              </span>
              {attempt.effective && (
                <Badge className="ml-2" variant="secondary">
                  {t.ansich.effective}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-3">
              {attempt.latency_ms !== null && (
                <span className="text-muted-foreground text-xs">
                  {attempt.latency_ms} ms
                </span>
              )}
              <AttemptStatus attempt={attempt} />
            </div>
          </div>
        ))}
        {step.issued_tools.length > 0 && (
          <div className="text-sm">
            <span className="text-muted-foreground">
              {t.ansich.issuedTools}:{" "}
            </span>
            {step.issued_tools.map((tool, index) => (
              <code
                key={safeText(tool.provider_call_id, String(index))}
                className="mr-2 text-xs"
              >
                {safeText(tool.name, "unknown")}
              </code>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AttemptStatus({ attempt }: { attempt: AnsichLlmAttempt }) {
  return (
    <Badge variant={attempt.status === "failed" ? "destructive" : "outline"}>
      {attempt.status}
    </Badge>
  );
}

function ContextSnapshotCard({ context }: { context: AnsichContextSnapshot }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t.ansich.contextInventory}</CardTitle>
        <div className="text-muted-foreground text-xs">
          {context.adapter_name} · {context.estimated_tokens} {t.ansich.tokens}{" "}
          · {context.visible_bytes} bytes
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {context.items.map((item) => (
          <ContextItem key={`${item.ordinal}:${item.block_id}`} item={item} />
        ))}
      </CardContent>
    </Card>
  );
}

function ContextItem({ item }: { item: AnsichContextItem }) {
  const { t } = useI18n();
  const [raw, setRaw] = useState<unknown>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadRaw() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAnsichContentPayload(item.block_id);
      setRaw(response.payload.body);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t.ansich.loadFailed);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">#{item.ordinal}</Badge>
          <span className="font-medium">{item.kind}</span>
          <span className="text-muted-foreground">
            {item.role ?? item.channel}
          </span>
        </div>
        {item.payload_available && raw === undefined && (
          <Button
            size="sm"
            variant="outline"
            disabled={loading}
            onClick={loadRaw}
          >
            {loading ? t.ansich.loading : t.ansich.loadRaw}
          </Button>
        )}
      </div>
      <div className="text-muted-foreground grid gap-1 font-mono text-xs sm:grid-cols-2">
        <span className="truncate" title={item.content_hash}>
          sha256:{item.content_hash}
        </span>
        <span>
          {item.estimated_tokens} {t.ansich.tokens} · {item.visible_bytes} bytes
        </span>
      </div>
      {error && <div className="text-destructive text-xs">{error}</div>}
      {raw !== undefined && (
        <pre className="bg-muted/60 max-h-72 overflow-auto rounded-md p-3 text-xs">
          {JSON.stringify(raw, null, 2)}
        </pre>
      )}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
      {message}
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="text-destructive border-destructive/30 rounded-lg border p-4 text-sm">
      {message}
    </div>
  );
}

function safeText(value: unknown, fallback: string): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : fallback;
}
