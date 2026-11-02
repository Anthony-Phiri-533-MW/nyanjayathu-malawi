import { cn } from "@/lib/cn";

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  className,
  align = "left",
}: {
  children?: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      scope="col"
      className={cn(
        "table-head px-4 py-2.5",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
  align = "left",
}: {
  children?: React.ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <td
      className={cn(
        "border-b border-border px-4 py-2.5 align-top text-ink-soft",
        align === "right" && "tabular text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function Tr({
  children,
  className,
  onClick,
}: {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <tr
      className={cn(onClick && "cursor-pointer hover:bg-canvas", className)}
      onClick={onClick}
    >
      {children}
    </tr>
  );
}

/** Page controls for paginated endpoints. */
export function Pagination({
  page,
  pages,
  total,
  onChange,
}: {
  page: number;
  pages: number;
  total: number;
  onChange: (page: number) => void;
}) {
  if (pages <= 1) {
    return <p className="px-4 py-3 text-xs text-muted">{total} record(s)</p>;
  }
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <p className="text-xs text-muted">
        Page {page} of {pages} · {total} record(s)
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className="btn-secondary px-2.5 py-1 text-xs"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          Previous
        </button>
        <button
          type="button"
          className="btn-secondary px-2.5 py-1 text-xs"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
