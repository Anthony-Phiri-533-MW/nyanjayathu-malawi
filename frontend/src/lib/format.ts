import type { QualityFlag } from "@/lib/types";

/** Format an ISO date/time for display. Returns an em dash for nothing. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

/**
 * Format a measurement. `null` means "not computed" (never zero) so it is
 * rendered explicitly rather than as 0.
 */
export function formatNumber(
  value: number | null | undefined,
  options: { digits?: number; unit?: string; notComputedLabel?: string } = {},
): string {
  const { digits = 3, unit, notComputedLabel = "not computed" } = options;
  if (value === null || value === undefined || Number.isNaN(value)) return notComputedLabel;
  const abs = Math.abs(value);
  const resolvedDigits = abs !== 0 && abs < 1 ? Math.max(digits, 4) : digits;
  const text = value.toLocaleString(undefined, {
    maximumFractionDigits: resolvedDigits,
    minimumFractionDigits: 0,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Quality flags drive colour. The mapping is fixed and documented so the same
 * flag always reads the same way anywhere in the console.
 */
export interface FlagStyle {
  label: string;
  className: string;
  help: string;
}

export const QUALITY_FLAG_STYLES: Record<QualityFlag, FlagStyle> = {
  VALID: {
    label: "Valid",
    className: "bg-success-light text-success-dark",
    help: "Meets the documented coverage and quality rules.",
  },
  LOW_QUALITY: {
    label: "Low quality",
    className: "bg-warning-light text-warning-dark",
    help: "Usable but within a degraded range (e.g. marginal coverage or cloud).",
  },
  INSUFFICIENT_COVERAGE: {
    label: "Insufficient coverage",
    className: "bg-warning-light text-warning-dark",
    help: "Too little of the study area is represented to report a value.",
  },
  CLOUD_CONTAMINATED: {
    label: "Cloud contaminated",
    className: "bg-warning-light text-warning-dark",
    help: "Cloud/shadow masking removed too much of the observation.",
  },
  MISSING_DATA: {
    label: "Missing data",
    className: "bg-canvas text-muted",
    help: "No usable observation was available for this record.",
  },
  PROCESSING_FAILED: {
    label: "Processing failed",
    className: "bg-danger-light text-danger-dark",
    help: "The computation did not complete; no value is reported.",
  },
  UNVALIDATED: {
    label: "Unvalidated",
    className: "bg-signal-100 text-signal-700",
    help: "A proxy or unvalidated method: treat the value as indicative only.",
  },
};

export function flagStyle(flag: string): FlagStyle {
  return (
    QUALITY_FLAG_STYLES[flag as QualityFlag] ?? {
      label: titleCase(flag),
      className: "bg-canvas text-muted",
      help: "",
    }
  );
}

/** Flag text/colour for an arbitrary job or source status. */
export function statusStyle(status: string): string {
  switch (status) {
    case "succeeded":
    case "verified":
    case "ok":
    case "approved":
      return "bg-success-light text-success-dark";
    case "running":
    case "pending":
    case "configured":
    case "pending_review":
      return "bg-info-light text-info-dark";
    case "failed":
    case "error":
    case "canceled":
      return "bg-danger-light text-danger-dark";
    case "provisional":
      return "bg-signal-100 text-signal-700";
    default:
      return "bg-canvas text-muted";
  }
}
