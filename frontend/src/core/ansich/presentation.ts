import type { AnsichLostRange } from "./types";

export function countMissingContextItems(
  items: Array<{ resolution_status: "available" | "missing" }>,
): number {
  return items.filter((item) => item.resolution_status === "missing").length;
}

export function countLostObservations(ranges: AnsichLostRange[]): number {
  return ranges.reduce(
    (total, range) =>
      total + Math.max(0, range.last_sequence - range.first_sequence + 1),
    0,
  );
}

export function formatAnsichTimestamp(
  value: string | null,
  locale: string,
): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}
