"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { useCallback, useState } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { shortId } from "@/core/ansich/presentation";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/**
 * L1 identity primitive (IA §4.2 "downgrade, not delete"): renders a short,
 * monospace id with a copy control; the full value is reachable via the tooltip
 * and clipboard, never printed inline on a first screen.
 */
export function AnsichShortId({
  value,
  length = 8,
  label,
  className,
}: {
  value: string;
  length?: number;
  label?: string;
  className?: string;
}) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const onCopy = useCallback(async () => {
    const ok = await writeTextToClipboard(value);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  }, [value]);

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <code className="font-mono text-xs" aria-label={label}>
            {shortId(value, length)}
          </code>
        </TooltipTrigger>
        <TooltipContent>
          <span className="font-mono break-all">{value}</span>
        </TooltipContent>
      </Tooltip>
      <button
        type="button"
        onClick={onCopy}
        aria-label={
          copied ? t.clipboard.copiedToClipboard : t.clipboard.copyToClipboard
        }
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded p-0.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        {copied ? (
          <CheckIcon className="size-3" />
        ) : (
          <CopyIcon className="size-3" />
        )}
      </button>
    </span>
  );
}
