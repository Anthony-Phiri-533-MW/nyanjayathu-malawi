import { useMemo } from "react";
import { cn } from "@/lib/cn";

/** Consistent page heading with optional actions on the right. */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  meta,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** Small contextual line above the heading (section, area, period). */
  eyebrow?: React.ReactNode;
  /** Secondary status line below the description (freshness, scope, notes). */
  meta?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-5 flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        {eyebrow ? (
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-water-700">{eyebrow}</p>
        ) : null}
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>
        ) : null}
        {meta ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            {meta}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/**
 * Marks a value or configuration that is provisional / not scientifically
 * validated. Used wherever a default threshold or proxy method is shown.
 */
export function ProvisionalNote({ children }: { children?: React.ReactNode }) {
  return (
    <p className="rounded-md border border-signal-200 bg-signal-50 px-3 py-2 text-xs text-signal-700">
      <span className="font-semibold">Provisional — not validated.</span>{" "}
      {children ?? "This configuration uses placeholder values and must be reviewed before operational use."}
    </p>
  );
}

/** Compact two-column definition list for metadata panels. */
export function DetailList({
  items,
  columns = 2,
}: {
  items: Array<{ label: string; value: React.ReactNode }>;
  columns?: 1 | 2 | 3;
}) {
  const grid = useMemo(
    () =>
      ({ 1: "grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3" })[
        columns
      ],
    [columns],
  );
  return (
    <dl className={cn("grid gap-x-6 gap-y-3", grid)}>
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs font-medium uppercase tracking-wide text-muted">{item.label}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink-soft">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
