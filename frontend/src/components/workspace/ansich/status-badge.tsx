import { Badge } from "@/components/ui/badge";
import type { AnsichControlValue } from "@/core/ansich/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<AnsichControlValue, string> = {
  unknown: "text-muted-foreground",
  created: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  running: "border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  completed:
    "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  failed: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
  interrupted:
    "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
};

export function AnsichStatusBadge({ value }: { value: AnsichControlValue }) {
  const { t } = useI18n();

  return (
    <Badge variant="outline" className={cn(STATUS_STYLES[value])}>
      {t.ansich.status[value]}
    </Badge>
  );
}
