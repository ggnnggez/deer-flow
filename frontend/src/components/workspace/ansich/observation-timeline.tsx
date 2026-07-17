import { CircleIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { formatAnsichTimestamp } from "@/core/ansich/presentation";
import type { AnsichObservation } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";

export function AnsichObservationTimeline({
  observations,
}: {
  observations: AnsichObservation[];
}) {
  const { t, locale } = useI18n();

  if (observations.length === 0) {
    return (
      <div className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
        {t.ansich.noObservations}
      </div>
    );
  }

  return (
    <ol className="before:bg-border relative space-y-4 before:absolute before:top-3 before:bottom-3 before:left-[0.4375rem] before:w-px">
      {observations.map((observation) => (
        <li key={observation.obs_id} className="relative pl-7">
          <CircleIcon className="fill-background text-primary absolute top-5 left-0 size-3.5" />
          <Card className="gap-4 py-4">
            <CardContent className="space-y-4 px-4 sm:px-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-mono text-sm font-semibold">
                    {observation.kind}
                  </div>
                  <div className="text-muted-foreground mt-1 font-mono text-xs">
                    {observation.obs_id}
                  </div>
                </div>
                <div className="grid gap-1 text-right text-xs tabular-nums">
                  <EvidenceField
                    label={t.ansich.occurredAt}
                    value={formatAnsichTimestamp(
                      observation.occurred_at,
                      locale,
                    )}
                  />
                  <EvidenceField
                    label={t.ansich.recordedAt}
                    value={formatAnsichTimestamp(
                      observation.recorded_at,
                      locale,
                    )}
                  />
                </div>
              </div>
              <div className="grid gap-3 text-sm sm:grid-cols-2">
                <EvidenceField
                  label={t.ansich.producer}
                  value={`${observation.producer.name}@${observation.producer.version} (${observation.producer.instance_id})`}
                  mono
                />
                <EvidenceField
                  label={t.ansich.sourceEvent}
                  value={observation.source_event_id}
                  mono
                />
              </div>
              <div>
                <div className="text-muted-foreground mb-1 text-xs">
                  {t.ansich.payload}
                </div>
                <pre className="bg-muted/60 max-w-full overflow-x-auto rounded-md p-3 text-xs leading-relaxed">
                  {JSON.stringify(observation.payload, null, 2)}
                </pre>
              </div>
            </CardContent>
          </Card>
        </li>
      ))}
    </ol>
  );
}

function EvidenceField({
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
      <span className="text-muted-foreground">{label}: </span>
      <span className={mono ? "font-mono break-all" : ""}>{value}</span>
    </div>
  );
}
