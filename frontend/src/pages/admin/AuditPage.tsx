import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useAuditActions, useAuditEvents, useAuditResourceTypes } from "@/lib/hooks";
import { formatDateTime, statusStyle } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";

/**
 * The audit log is append-only and read-only here: no console action can
 * modify or delete an entry. `details` is expanded on demand because it can be
 * large; the backend has already scrubbed sensitive keys before persisting.
 */
export function AuditPage() {
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [outcome, setOutcome] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);

  const events = useAuditEvents({
    search: search || undefined,
    action: action || undefined,
    resource_type: resourceType || undefined,
    outcome: outcome || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    page,
    size: 25,
  });
  const actions = useAuditActions();
  const resourceTypes = useAuditResourceTypes();

  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Audit log"
        description="An append-only record of administrative and research actions: who did what, to which resource, and whether it succeeded. Credentials and tokens are never recorded."
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              setSearch("");
              setAction("");
              setResourceType("");
              setOutcome("");
              setDateFrom("");
              setDateTo("");
              resetPage();
            }}
          >
            Clear filters
          </Button>
        }
      />

      <Card className="mb-5">
        <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Search" htmlFor="au-search" hint="Matches action, message, actor, resource.">
            <TextInput
              id="au-search"
              value={search}
              placeholder="e.g. water_extent"
              onChange={(e) => {
                setSearch(e.target.value);
                resetPage();
              }}
            />
          </Field>
          <Field label="Action" htmlFor="au-action">
            <Select
              id="au-action"
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                resetPage();
              }}
            >
              <option value="">All actions</option>
              {(actions.data ?? []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Resource type" htmlFor="au-resource">
            <Select
              id="au-resource"
              value={resourceType}
              onChange={(e) => {
                setResourceType(e.target.value);
                resetPage();
              }}
            >
              <option value="">All resources</option>
              {(resourceTypes.data ?? []).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Outcome" htmlFor="au-outcome">
            <Select
              id="au-outcome"
              value={outcome}
              onChange={(e) => {
                setOutcome(e.target.value);
                resetPage();
              }}
            >
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </Select>
          </Field>
          <Field label="From" htmlFor="au-from">
            <TextInput
              id="au-from"
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                resetPage();
              }}
            />
          </Field>
          <Field label="To" htmlFor="au-to">
            <TextInput
              id="au-to"
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                resetPage();
              }}
            />
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Events" description={`${events.data?.total ?? 0} event(s)`} />
        {events.isLoading ? (
          <LoadingRows rows={6} />
        ) : events.isError ? (
          <ErrorState error={events.error} onRetry={() => events.refetch()} />
        ) : events.data && events.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Actor</Th>
                  <Th>Action</Th>
                  <Th>Resource</Th>
                  <Th>Outcome</Th>
                  <Th align="right" />
                </tr>
              </thead>
              <tbody>
                {events.data.items.map((event) => (
                  <EventRow
                    key={event.id}
                    event={event}
                    expanded={expanded === event.id}
                    onToggle={() => setExpanded(expanded === event.id ? null : event.id)}
                  />
                ))}
              </tbody>
            </Table>
            <Pagination
              page={events.data.page}
              pages={events.data.pages}
              total={events.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No audit events match"
            description="Broaden the filters or the date range."
          />
        )}
      </Card>
    </div>
  );
}

function EventRow({
  event,
  expanded,
  onToggle,
}: {
  event: AuditEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <Tr>
        <Td className="whitespace-nowrap text-xs">{formatDateTime(event.created_at)}</Td>
        <Td>
          <p className="text-xs font-medium text-ink-soft">{event.actor_email ?? "system"}</p>
          {event.ip_address ? <p className="text-xs text-muted">{event.ip_address}</p> : null}
        </Td>
        <Td>
          <p className="font-mono text-xs text-ink">{event.action}</p>
          {event.message ? <p className="max-w-md text-xs text-muted">{event.message}</p> : null}
        </Td>
        <Td>
          <p className="text-xs">{event.resource_type}</p>
          {event.resource_id ? <p className="text-xs text-muted">#{event.resource_id}</p> : null}
        </Td>
        <Td>
          <Badge className={statusStyle(event.outcome === "success" ? "succeeded" : "failed")}>
            {event.outcome}
          </Badge>
        </Td>
        <Td align="right">
          {event.details ? (
            <Button variant="secondary" size="sm" onClick={onToggle}>
              {expanded ? "Hide" : "Details"}
            </Button>
          ) : null}
        </Td>
      </Tr>
      {expanded && event.details ? (
        <tr>
          <td colSpan={6} className="border-b border-border bg-canvas px-4 py-3">
            <pre className="max-h-64 overflow-auto rounded bg-surface p-3 text-xs text-ink-soft">
              {JSON.stringify(event.details, null, 2)}
            </pre>
            {event.request_id ? (
              <p className="mt-2 text-xs text-muted">Request ID: {event.request_id}</p>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}
