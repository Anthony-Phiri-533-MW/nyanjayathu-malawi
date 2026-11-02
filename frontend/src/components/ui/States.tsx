import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export function LoadingRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2 p-5", className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 animate-pulse rounded-md bg-canvas" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-5 py-12 text-center">
      <p className="text-sm font-medium text-ink-soft">{title}</p>
      {description ? <p className="max-w-md text-sm text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/**
 * Surfaces an `ApiError` (or any thrown value). The backend's message is shown
 * verbatim: it is written for the operator, and inventing a friendlier one
 * would hide e.g. "the selection matched no datasets".
 */
export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const isApi = error instanceof ApiError;
  const title = isApi && error.status === 403 ? "Not permitted" : "Something went wrong";
  const message =
    error instanceof Error ? error.message : "An unexpected error occurred.";

  return (
    <div className="flex flex-col items-start gap-2 px-5 py-8">
      <p className="text-sm font-semibold text-danger-dark">{title}</p>
      <p className="text-sm text-ink-soft">{message}</p>
      {isApi && Object.keys(error.fieldErrors).length > 0 ? (
        <ul className="mt-1 list-inside list-disc text-xs text-danger">
          {Object.entries(error.fieldErrors).map(([field, msg]) => (
            <li key={field}>
              <span className="font-medium">{field}</span>: {msg}
            </li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
