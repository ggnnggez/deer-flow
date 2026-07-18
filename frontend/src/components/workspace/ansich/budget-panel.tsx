"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnsichTaskBudgets, useAnsichTaskUsage } from "@/core/ansich/hooks";
import { getBudgetPresentation } from "@/core/ansich/presentation";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichBudgetPanel({
  taskId,
  polling,
}: {
  taskId: string;
  polling: boolean;
}) {
  const { t } = useI18n();
  const usageQuery = useAnsichTaskUsage(taskId, true, polling);
  const budgetsQuery = useAnsichTaskBudgets(taskId, true, polling);
  if (usageQuery.isPending || budgetsQuery.isPending) {
    return <Skeleton className="h-48 w-full" />;
  }
  const error = usageQuery.error ?? budgetsQuery.error;
  if (error) {
    return (
      <div className="text-destructive rounded-lg border p-4 text-sm">
        {error.message}
      </div>
    );
  }
  const usage = usageQuery.data?.usage.local ?? [];
  const budgets = budgetsQuery.data?.budgets.budgets ?? [];
  const health = budgetsQuery.data?.health ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.localUsage}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          {usage.length ? (
            usage.map((item) => (
              <div key={item.dimension} className="rounded-lg border p-3">
                <div className="text-muted-foreground text-xs">
                  {item.dimension}
                </div>
                <div className="mt-1 text-lg font-semibold tabular-nums">
                  {item.value.toLocaleString()}
                </div>
              </div>
            ))
          ) : (
            <div className="text-muted-foreground text-sm">
              {t.ansich.evidenceInsufficient}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t.ansich.budgets}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {budgets.length ? (
            budgets.map((budget) => {
              const belief = health.find(
                (item) =>
                  item.dimension === budget.dimension &&
                  item.aggregation_scope === budget.aggregation_scope,
              );
              const presentation = getBudgetPresentation(budget, belief);
              return (
                <div
                  key={budget.entity_id}
                  className="space-y-2 rounded-lg border p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="font-medium">{budget.dimension}</div>
                      <div className="text-muted-foreground text-xs">
                        {budget.aggregation_scope} · {budget.source_kind}
                      </div>
                    </div>
                    <Badge variant="outline">
                      {presentation.status === "unconfigured"
                        ? t.ansich.unconfigured
                        : t.ansich.budgetState[presentation.status]}
                    </Badge>
                  </div>
                  {presentation.percent === null ? (
                    <div className="text-muted-foreground text-sm">
                      {presentation.status === "unknown"
                        ? t.ansich.evidenceInsufficient
                        : t.ansich.unconfigured}
                    </div>
                  ) : (
                    <>
                      <Progress value={Math.min(100, presentation.percent)} />
                      <div className="flex justify-between text-xs tabular-nums">
                        <span>
                          {belief?.usage_value?.toLocaleString()} /{" "}
                          {budget.hard_limit?.toLocaleString()}
                        </span>
                        <span>{presentation.percent}%</span>
                      </div>
                    </>
                  )}
                  {presentation.overshoot ? (
                    <div className="text-destructive text-sm font-medium">
                      {t.ansich.overshoot}:{" "}
                      {presentation.overshoot.toLocaleString()}
                    </div>
                  ) : null}
                  <div className="text-muted-foreground text-xs">
                    {t.ansich.enforcement}:{" "}
                    {budget.enforcement ? t.ansich.enforced : t.ansich.shadow}
                    {budget.requested_value !== null &&
                    budget.requested_value !== budget.effective_value
                      ? ` · requested ${budget.requested_value}, effective ${budget.effective_value}`
                      : ""}
                  </div>
                </div>
              );
            })
          ) : (
            <div className="text-muted-foreground text-sm">
              {t.ansich.unconfigured}
            </div>
          )}
          <div className="text-muted-foreground text-xs">
            inclusive: {t.ansich.notAvailable}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
