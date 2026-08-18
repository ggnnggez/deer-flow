"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAnsichAgentReleaseComparison,
  useAnsichAgentReleases,
  useAnsichTaskAgentRelease,
} from "@/core/ansich/hooks";
import { getAgentReleaseDiffGroups } from "@/core/ansich/release-presentation";
import type {
  AnsichAgentReleaseManifest,
  AnsichAgentReleaseComparison,
  AnsichAgentReleaseSummary,
} from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

import { AnsichReleaseQualitySection } from "./release-quality-section";

export function AnsichAgentReleasePanel({
  taskId,
  polling,
}: {
  taskId: string;
  polling: boolean;
}) {
  const { t } = useI18n();
  const [rightReleaseId, setRightReleaseId] = useState<string | null>(null);
  // The committed cohort is separate from what is being typed: every change
  // is a different comparison request, so it is committed on Enter or blur
  // rather than on each keystroke.
  const [cohortDraft, setCohortDraft] = useState("");
  const [cohort, setCohort] = useState<string | null>(null);
  const taskReleaseQuery = useAnsichTaskAgentRelease(taskId, true, polling);
  const binding = taskReleaseQuery.data?.binding ?? null;
  const currentReleaseId = binding?.release.summary.release_id ?? null;
  const releasesQuery = useAnsichAgentReleases(100, Boolean(binding));
  const comparisonQuery = useAnsichAgentReleaseComparison(
    currentReleaseId,
    rightReleaseId,
    true,
    cohort,
  );

  // A blank box asks for every cohort. The backend's empty-string cohort is a
  // distinct declared-no-cohort bucket, which a text field cannot express
  // apart from "unset", so it stays reachable only through the per-row label.
  function commitCohort() {
    const next = cohortDraft.trim();
    setCohort(next.length > 0 ? next : null);
  }

  if (taskReleaseQuery.isPending) {
    return <Skeleton className="h-72 w-full" />;
  }
  if (taskReleaseQuery.error) {
    return (
      <div className="text-destructive rounded-lg border p-4 text-sm">
        {taskReleaseQuery.error.message}
      </div>
    );
  }
  if (!binding) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.agentRelease}</CardTitle>
          <CardDescription>{t.ansich.noAgentRelease}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const { summary, manifest } = binding.release;
  const providerDrift = taskReleaseQuery.data?.provider_drift ?? null;
  const driftValue = providerDrift?.value.value;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t.ansich.agentRelease}</CardTitle>
              <CardDescription>
                {manifest.namespace}/{manifest.agent_name} · schema v
                {manifest.schema_version}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              {/* Hardcoded, not read from `summary.quality_status`: the backend
                  still pins that field to the literal `"unassessed"`
                  (ansich/release/manifest.py). Requalify this badge — and drop
                  the literal — when real aggregate release quality lands. */}
              <Badge variant="outline">
                {t.ansich.quality}: {t.ansich.unassessed}
              </Badge>
              <Badge variant="outline">
                {t.ansich.operationalDistribution}: {t.ansich.unavailable}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <ReleaseIdentity
              label={t.ansich.releaseHash}
              value={summary.release_hash}
            />
            <ReleaseIdentity
              label={t.ansich.releaseId}
              value={summary.release_id}
            />
            <ReleaseIdentity
              label={t.ansich.releaseTasks}
              value={String(summary.task_count)}
            />
          </div>
          <ComponentHashes summary={summary} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.configurationDrift}</CardTitle>
          <CardDescription>
            {providerDrift
              ? `${providerDrift.assessor.name}@${providerDrift.assessor.version}`
              : t.ansich.evidenceInsufficient}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <Badge
            variant={driftValue === "mismatch" ? "destructive" : "outline"}
          >
            {typeof driftValue === "string"
              ? driftValue
              : t.ansich.evidenceInsufficient}
          </Badge>
          {providerDrift ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <ReleaseIdentity
                label={t.ansich.effectiveModel}
                value={displayScalar(providerDrift.value.effective_model)}
              />
              <ReleaseIdentity
                label={t.ansich.providerReportedModel}
                value={displayScalar(
                  providerDrift.value.provider_reported_model,
                )}
              />
              <div className="sm:col-span-2">
                <div className="text-muted-foreground mb-1 text-xs">
                  {t.ansich.evidence}
                </div>
                <div className="flex flex-wrap gap-2">
                  {providerDrift.evidence_obs_ids.map((obsId) => (
                    <code
                      key={obsId}
                      className="bg-muted rounded px-2 py-1 text-xs"
                    >
                      {obsId}
                    </code>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ReleaseManifestCard manifest={manifest} />

      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.compareReleases}</CardTitle>
          <CardDescription>
            {t.ansich.compareReleasesDescription}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {releasesQuery.error ? (
            <div className="text-destructive text-sm">
              {releasesQuery.error.message}
            </div>
          ) : (
            <div className="flex flex-wrap gap-3">
              <Select
                value={rightReleaseId ?? undefined}
                onValueChange={setRightReleaseId}
              >
                <SelectTrigger
                  aria-label={t.ansich.selectRelease}
                  className="w-full max-w-xl"
                >
                  <SelectValue placeholder={t.ansich.selectRelease} />
                </SelectTrigger>
                <SelectContent>
                  {(releasesQuery.data?.items ?? [])
                    .filter((item) => item.release_id !== currentReleaseId)
                    .map((item) => (
                      <SelectItem key={item.release_id} value={item.release_id}>
                        {item.agent_name} · {shortHash(item.release_hash)} ·{" "}
                        {item.created_at}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <Input
                aria-label={t.ansich.qualityCohortPlaceholder}
                placeholder={t.ansich.qualityCohortPlaceholder}
                className="w-full max-w-xs"
                value={cohortDraft}
                onChange={(event) => setCohortDraft(event.currentTarget.value)}
                onBlur={commitCohort}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    commitCohort();
                  }
                }}
              />
            </div>
          )}
          {comparisonQuery.isFetching ? (
            <Skeleton className="h-40 w-full" />
          ) : comparisonQuery.error ? (
            <div className="text-destructive text-sm">
              {comparisonQuery.error.message}
            </div>
          ) : comparisonQuery.data ? (
            <ReleaseComparison comparison={comparisonQuery.data.comparison} />
          ) : null}
        </CardContent>
      </Card>

      {/* Semantic quality lives in its own card region, never mixed into the
          structural diff above (spec §7). */}
      {comparisonQuery.isFetching ? null : (
        <AnsichReleaseQualitySection quality={comparisonQuery.data?.quality} />
      )}
    </div>
  );
}

function ComponentHashes({ summary }: { summary: AnsichAgentReleaseSummary }) {
  const { t } = useI18n();
  const hashes: Array<[string, string]> = [
    [t.ansich.model, summary.model_hash],
    [t.ansich.prompt, summary.prompt_hash],
    [t.ansich.tools, summary.tool_catalog_hash],
    [t.ansich.policy, summary.policy_hash],
    [t.ansich.runtimeBuild, summary.runtime_build_id],
  ];
  return (
    <div>
      <div className="text-muted-foreground mb-2 text-xs">
        {t.ansich.componentHashes}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {hashes.map(([label, hash]) => (
          <div key={label} className="rounded-lg border p-3">
            <div className="text-muted-foreground text-xs">{label}</div>
            <code className="mt-1 block text-xs" title={hash}>
              {shortHash(hash)}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReleaseManifestCard({
  manifest,
}: {
  manifest: AnsichAgentReleaseManifest;
}) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.ansich.effectiveConfiguration}</CardTitle>
        <CardDescription>
          {t.ansich.sanitizedReleaseDescription}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 text-sm">
        <section className="grid gap-3 sm:grid-cols-2">
          <ReleaseIdentity
            label={t.ansich.effectiveModel}
            value={manifest.model.effective}
          />
          <ReleaseIdentity
            label={t.ansich.requestedModel}
            value={manifest.model.requested ?? "—"}
          />
          <ReleaseJson
            label={t.ansich.modelParameters}
            value={manifest.model.behavior_parameters}
          />
        </section>
        <section className="space-y-2 border-t pt-4">
          <h3 className="font-medium">{t.ansich.prompt}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <ReleaseIdentity
              label={t.ansich.template}
              value={manifest.prompt.template_id}
            />
            <ReleaseIdentity
              label={t.ansich.promptHash}
              value={manifest.prompt.rendered_base_prompt_hash}
            />
          </div>
          <div>
            <div className="text-muted-foreground mb-1 text-xs">
              {t.ansich.promptPreview}
            </div>
            <pre className="bg-muted/60 max-h-48 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
              {manifest.prompt.rendered_base_prompt_preview}
            </pre>
          </div>
        </section>
        <section className="space-y-2 border-t pt-4">
          <h3 className="font-medium">
            {t.ansich.tools} ({manifest.tools.length})
          </h3>
          {manifest.tools.map((tool) => (
            <details
              key={`${tool.source}:${tool.name}`}
              className="rounded-lg border p-3"
            >
              <summary className="cursor-pointer font-mono text-sm">
                {tool.source}:{tool.name}
              </summary>
              <div className="mt-3 space-y-3">
                <p className="text-muted-foreground">{tool.description}</p>
                <ReleaseJson
                  label={t.ansich.argumentSchema}
                  value={tool.argument_schema}
                />
                <ReleaseJson
                  label={t.ansich.behaviorMetadata}
                  value={tool.behavior_metadata}
                />
              </div>
            </details>
          ))}
        </section>
        <section className="grid gap-3 border-t pt-4 sm:grid-cols-2">
          <ReleaseJson label={t.ansich.policy} value={manifest.policy} />
          <ReleaseJson
            label={t.ansich.runtimeBuild}
            value={manifest.runtime_build}
          />
        </section>
      </CardContent>
    </Card>
  );
}

function ReleaseComparison({
  comparison,
}: {
  comparison: AnsichAgentReleaseComparison;
}) {
  const { t } = useI18n();
  const groups = getAgentReleaseDiffGroups(comparison);
  if (!groups.length) {
    return (
      <div className="text-muted-foreground text-sm">
        {t.ansich.noReleaseChanges}
      </div>
    );
  }
  // No quality label here: the structural diff states structural facts only,
  // and the quality section below reports what the evaluations actually say.
  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <section key={group.component} className="rounded-lg border p-3">
          <h3 className="mb-2 font-medium">{group.component}</h3>
          <div className="space-y-2">
            {group.items.map((item, index) => (
              <div
                key={`${item.kind}:${item.path}:${index}`}
                className="grid gap-2 border-t pt-2 text-xs first:border-0 first:pt-0 sm:grid-cols-[10rem_1fr_1fr]"
              >
                <code>
                  {item.kind} · {item.path}
                </code>
                <pre className="overflow-auto whitespace-pre-wrap">
                  {displayValue(item.left)}
                </pre>
                <pre className="overflow-auto whitespace-pre-wrap">
                  {displayValue(item.right)}
                </pre>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ReleaseIdentity({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted-foreground mb-1 text-xs">{label}</div>
      <code className="block text-xs break-all">{value}</code>
    </div>
  );
}

function ReleaseJson({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="text-muted-foreground mb-1 text-xs">{label}</div>
      <pre className="bg-muted/60 max-h-72 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
        {displayValue(value)}
      </pre>
    </div>
  );
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 16)}…` : value;
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? String(value);
}

function displayScalar(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return `${value}`;
  }
  return displayValue(value);
}
