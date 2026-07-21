"use client";

import { AlertTriangleIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAnsichTaskScopes,
  useAnsichTaskSteps,
  useAnsichToolAuthorization,
  useAnsichToolEffects,
} from "@/core/ansich/hooks";
import type { AnsichToolCall, AnsichToolEffect } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichScopeEffectsPanel({
  taskId,
  polling = true,
}: {
  taskId: string;
  polling?: boolean;
}) {
  const { t } = useI18n();
  const scopesQuery = useAnsichTaskScopes(taskId, true, polling);
  const stepsQuery = useAnsichTaskSteps(taskId, true, polling);
  if (scopesQuery.isPending || stepsQuery.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }
  const error = scopesQuery.error ?? stepsQuery.error;
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangleIcon />
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  const scopes = scopesQuery.data?.scopes.scopes ?? [];
  const toolCalls = (stepsQuery.data?.items ?? []).flatMap(
    (step) => step.tool_calls,
  );
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.scopes}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {scopes.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t.ansich.noScopes}
            </p>
          ) : (
            scopes.map((scope) => (
              <Badge key={`${scope.scope_id}:${scope.relation_role}`} variant="outline">
                {scope.scope_kind}: {scope.display_label} · {scope.relation_role}
              </Badge>
            ))
          )}
        </CardContent>
      </Card>
      {toolCalls.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground p-6 text-sm">
            {t.ansich.noSteps}
          </CardContent>
        </Card>
      ) : (
        toolCalls.map((toolCall) => (
          <ToolSafetyChain
            key={toolCall.tool_call_id}
            toolCall={toolCall}
            polling={polling}
          />
        ))
      )}
    </div>
  );
}

function EffectList({ effects }: { effects: AnsichToolEffect[] }) {
  if (effects.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="space-y-1">
      {effects.map((effect) => (
        <div key={effect.effect_id} className="text-xs">
          <code>{effect.effect_class}</code>
          {effect.target_preview ? ` → ${effect.target_preview}` : ""}
        </div>
      ))}
    </div>
  );
}

function ToolSafetyChain({
  toolCall,
  polling,
}: {
  toolCall: AnsichToolCall;
  polling: boolean;
}) {
  const { t } = useI18n();
  const authorizationQuery = useAnsichToolAuthorization(
    toolCall.tool_call_id,
    true,
    polling,
  );
  const effectsQuery = useAnsichToolEffects(toolCall.tool_call_id, true, polling);
  if (authorizationQuery.isPending || effectsQuery.isPending) {
    return <Skeleton className="h-32 w-full" />;
  }
  const authorization = authorizationQuery.data?.authorization;
  const effects = effectsQuery.data?.effects;
  const intended =
    effects?.effects.filter((effect) => effect.phase === "intended") ?? [];
  const observed =
    effects?.effects.filter((effect) => effect.phase === "observed") ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {toolCall.tool_name}
          <code className="text-muted-foreground text-xs font-normal">
            {toolCall.tool_call_id}
          </code>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          <Stage title={t.ansich.effectIntent}>
            <EffectList effects={intended} />
          </Stage>
          <Stage title={t.ansich.authorization}>
            <Badge variant="outline">
              {authorization?.current_decision ?? "unknown"}
            </Badge>
            {authorization?.snapshots.at(-1) && (
              <div className="text-muted-foreground mt-1 text-xs">
                {t.ansich.policy}: {authorization.snapshots.at(-1)?.policy_id}@
                {authorization.snapshots.at(-1)?.policy_version}
              </div>
            )}
          </Stage>
          <Stage title={t.ansich.effectObserved}>
            <EffectList effects={observed} />
          </Stage>
        </div>
        <div className="text-muted-foreground text-xs">
          {t.ansich.coverage}: {effects?.coverage ?? "unknown"}
        </div>
        {(effects?.coverage ?? "unknown") === "unknown" && (
          <Alert>
            <AlertTriangleIcon />
            <AlertDescription>{t.ansich.unknownEffectCoverage}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function Stage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-muted/40 rounded-md border p-3">
      <div className="text-muted-foreground mb-2 text-xs font-medium uppercase">
        {title}
      </div>
      {children}
    </div>
  );
}
