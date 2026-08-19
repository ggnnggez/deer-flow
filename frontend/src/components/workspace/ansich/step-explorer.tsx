"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchAnsichContentPayload,
  fetchAnsichToolRawResult,
  fetchAnsichToolVisibleResult,
} from "@/core/ansich/api";
import {
  useAnsichStepContext,
  useAnsichTaskSteps,
  useAnsichTaskToolEnvSamples,
} from "@/core/ansich/hooks";
import { countMissingContextItems } from "@/core/ansich/presentation";
import type {
  AnsichContextItem,
  AnsichContextSnapshot,
  AnsichLlmAttempt,
  AnsichStep,
  AnsichToolCall,
  AnsichToolEnvSample,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import {
  AnsichBlockLineageExplorer,
  AnsichCompressionExplorer,
} from "./lineage-explorer";
import { formatBytes } from "./system-health-drawer";

export function AnsichStepsPanel({
  taskId,
  polling = true,
}: {
  taskId: string;
  polling?: boolean;
}) {
  const { t } = useI18n();
  const query = useAnsichTaskSteps(taskId, true, polling);
  // One bounded, non-polling read for the whole Task rather than a detail
  // fetch per ToolCall row. Fails quiet: no samples means the rows render
  // exactly as they did before this line existed.
  const environmentSamples = useAnsichTaskToolEnvSamples(taskId);
  const sampleByToolCallId = new Map(
    (environmentSamples.data?.samples ?? []).map((sample) => [
      sample.tool_call_id,
      sample,
    ]),
  );

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
            <StepCard
              key={step.step_id}
              step={step}
              sampleByToolCallId={sampleByToolCallId}
            />
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

export function AnsichContextPanel({
  taskId,
  compressionIds = [],
  compressionError = null,
  compressionHasNextPage = false,
  compressionLoadingMore = false,
  onLoadMoreCompressions,
  polling = true,
}: {
  taskId: string;
  compressionIds?: string[];
  compressionError?: string | null;
  compressionHasNextPage?: boolean;
  compressionLoadingMore?: boolean;
  onLoadMoreCompressions?: () => void;
  polling?: boolean;
}) {
  const { t } = useI18n();
  const stepsQuery = useAnsichTaskSteps(taskId, true, polling);
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

  const contextQuery = useAnsichStepContext(selectedStepId, true, polling);
  const compressionExplorer = (
    <AnsichCompressionExplorer
      compressionIds={compressionIds}
      error={compressionError}
      hasNextPage={compressionHasNextPage}
      loadingMore={compressionLoadingMore}
      onLoadMore={onLoadMoreCompressions}
    />
  );

  if (stepsQuery.isPending)
    return (
      <div className="space-y-4">
        <Skeleton className="h-48 w-full" />
        {compressionExplorer}
      </div>
    );
  if (stepsQuery.error)
    return (
      <div className="space-y-4">
        <InlineError message={stepsQuery.error.message} />
        {compressionExplorer}
      </div>
    );
  if (eligibleSteps.length === 0) {
    const contextUnavailable =
      (stepsQuery.data?.projection_status.failed_jobs ?? 0) > 0;
    return (
      <div className="space-y-4">
        {contextUnavailable ? (
          <ProjectionUnavailableState
            message={t.ansich.contextProjectionUnavailable}
          />
        ) : (
          <EmptyState message={t.ansich.noContext} />
        )}
        {compressionExplorer}
      </div>
    );
  }

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
        <div className="space-y-4">
          <ContextSnapshotCard context={contextQuery.data.context} />
          {compressionExplorer}
        </div>
      ) : null}
    </div>
  );
}

function StepCard({
  step,
  sampleByToolCallId,
}: {
  step: AnsichStep;
  sampleByToolCallId: Map<string, AnsichToolEnvSample>;
}) {
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
        {step.tool_calls.map((toolCall) => (
          <ToolCallChain
            key={toolCall.tool_call_id}
            toolCall={toolCall}
            environmentSample={
              sampleByToolCallId.get(toolCall.tool_call_id) ?? null
            }
          />
        ))}
        {step.tool_calls.length === 0 && step.issued_tools.length > 0 && (
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

function ToolCallChain({
  toolCall,
  environmentSample,
}: {
  toolCall: AnsichToolCall;
  environmentSample: AnsichToolEnvSample | null;
}) {
  const { t } = useI18n();
  const [raw, setRaw] = useState<unknown>(undefined);
  const [visible, setVisible] = useState<unknown>(undefined);
  const [loading, setLoading] = useState<"raw" | "visible" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const transform = toolCall.derivations[0]?.transform_kind ?? "unknown";

  async function loadResult(role: "raw" | "visible") {
    setLoading(role);
    setError(null);
    try {
      if (role === "raw") {
        const response = await fetchAnsichToolRawResult(toolCall.tool_call_id);
        setRaw(response.raw_payload?.body);
      } else {
        const response = await fetchAnsichToolVisibleResult(
          toolCall.tool_call_id,
        );
        setVisible(response.visible_payload?.body);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t.ansich.loadFailed);
    } finally {
      setLoading(null);
    }
  }

  return (
    <section
      className="space-y-3 rounded-md border p-3"
      aria-label={`${t.ansich.toolCall} #${toolCall.call_seq}: ${toolCall.tool_name}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">
          {t.ansich.toolCall} #{toolCall.call_seq}: {toolCall.tool_name}
        </div>
        <code className="text-muted-foreground text-xs break-all">
          {toolCall.tool_call_id}
        </code>
      </div>
      {environmentSample ? (
        <ToolCallEnvironmentLine sample={environmentSample} />
      ) : null}
      <div className="grid gap-2 lg:grid-cols-4">
        <ToolStage
          label={t.ansich.issued}
          value={toolCall.issued_obs_id ? t.ansich.observed : "unknown"}
        >
          <code
            className="text-muted-foreground block truncate text-xs"
            title={toolCall.args_hash}
          >
            sha256:{toolCall.args_hash}
          </code>
        </ToolStage>
        <ToolStage
          label={t.ansich.authorization}
          value={toolCall.authorization.value}
        />
        <ToolStage label={t.ansich.execution} value={toolCall.execution.value}>
          {toolCall.duration_ms !== null && (
            <div className="text-muted-foreground text-xs">
              {toolCall.duration_ms} ms
            </div>
          )}
          {toolCall.raw_results.some((result) => result.payload_available) &&
            raw === undefined && (
              <Button
                size="sm"
                variant="outline"
                disabled={loading !== null}
                onClick={() => loadResult("raw")}
              >
                {loading === "raw" ? t.ansich.loading : t.ansich.loadToolRaw}
              </Button>
            )}
        </ToolStage>
        <ToolStage
          label={t.ansich.visibleToModel}
          value={toolCall.visible_result.value}
        >
          <div className="text-muted-foreground text-xs">
            {t.ansich.transform}: {transform}
          </div>
          {toolCall.visible_results.some(
            (result) => result.payload_available,
          ) &&
            visible === undefined && (
              <Button
                size="sm"
                variant="outline"
                disabled={loading !== null}
                onClick={() => loadResult("visible")}
              >
                {loading === "visible"
                  ? t.ansich.loading
                  : t.ansich.loadToolVisible}
              </Button>
            )}
        </ToolStage>
      </div>
      {error && <div className="text-destructive text-xs">{error}</div>}
      {raw !== undefined && (
        <ResultPayload label={t.ansich.rawResult} value={raw} />
      )}
      {visible !== undefined && (
        <ResultPayload label={t.ansich.visibleResult} value={visible} />
      )}
    </section>
  );
}

/**
 * The per-command environment sample for one ToolCall, as sibling metadata.
 *
 * Rendered only when the sampler actually produced a row for this call
 * (local sandbox bash, per-command sampling on); a counter the sampler did
 * not report is omitted rather than shown as 0 — missing is not zero.
 */
function ToolCallEnvironmentLine({ sample }: { sample: AnsichToolEnvSample }) {
  const { t } = useI18n();
  const parts: string[] = [];
  if (sample.fd_peak !== null) {
    parts.push(`${t.ansich.environmentFdPeak} ${sample.fd_peak}`);
  }
  if (sample.io_read_bytes !== null) {
    parts.push(
      `${t.ansich.environmentIoRead} ${formatBytes(sample.io_read_bytes)}`,
    );
  }
  if (sample.io_write_bytes !== null) {
    parts.push(
      `${t.ansich.environmentIoWrite} ${formatBytes(sample.io_write_bytes)}`,
    );
  }
  if (parts.length === 0) return null;
  return (
    <div className="text-muted-foreground text-xs">{parts.join(" · ")}</div>
  );
}

function ToolStage({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="bg-muted/40 space-y-2 rounded-md p-3 text-sm">
      <div className="text-muted-foreground text-xs font-medium uppercase">
        {label}
      </div>
      <Badge
        variant={
          value === "failed" || value === "denied" ? "destructive" : "outline"
        }
      >
        {value}
      </Badge>
      {children}
    </div>
  );
}

function ResultPayload({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="space-y-1">
      <div className="text-muted-foreground text-xs font-medium">{label}</div>
      <pre className="bg-muted/60 max-h-72 overflow-auto rounded-md p-3 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
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
  const missingCount = countMissingContextItems(context.items);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t.ansich.contextInventory}</CardTitle>
        <Badge
          variant={context.status === "complete" ? "secondary" : "outline"}
        >
          {context.status === "complete"
            ? t.ansich.snapshotComplete
            : t.ansich.snapshotIncomplete}
        </Badge>
        <div className="text-muted-foreground text-xs">
          {context.adapter_name} · {context.estimated_tokens} {t.ansich.tokens}{" "}
          · {context.visible_bytes} bytes
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {context.status === "incomplete" && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300">
            {missingCount} {t.ansich.missingContextBlocks}
          </div>
        )}
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
          <span className="font-medium">
            {item.kind ?? t.ansich.unknownContent}
          </span>
          {item.resolution_status === "missing" && (
            <Badge variant="outline">{t.ansich.missingBlocks}</Badge>
          )}
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
        <span className="truncate" title={item.content_hash ?? undefined}>
          {item.content_hash ? `sha256:${item.content_hash}` : "sha256:—"}
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
      {item.resolution_status === "available" && (
        <AnsichBlockLineageExplorer blockId={item.block_id} />
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

function ProjectionUnavailableState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-5 text-sm text-amber-800 dark:text-amber-300">
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
