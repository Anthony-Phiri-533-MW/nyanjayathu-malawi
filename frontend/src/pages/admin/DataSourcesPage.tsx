import { useState } from "react";
import { CheckCircle2, Plus, RefreshCw, Trash2, XCircle } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Select, TextArea, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useCreateDataSource,
  useDataSources,
  useDeleteDataSource,
  useProviders,
  useTestDataSource,
  useUpdateDataSource,
} from "@/lib/hooks";
import { formatDateTime, titleCase } from "@/lib/format";
import type { DataSource, Provider } from "@/lib/types";

export function DataSourcesPage() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<DataSource | null>(null);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const sources = useDataSources({
    search: search || undefined,
    category: category || undefined,
    page,
    size: 20,
  });
  const providers = useProviders();
  const test = useTestDataSource();
  const remove = useDeleteDataSource();

  const canWrite = can("admin.data_sources.write");
  const canTest = can("admin.data_sources.test");
  const categories = Array.from(new Set((providers.data ?? []).map((p) => p.category))).sort();
  const [testingId, setTestingId] = useState<number | null>(null);

  return (
    <div>
      <PageHeader
        title="Data sources"
        description="Provider integrations: which datasets are configured, when they were last verified, and whether retrieval is working. Credentials for restricted services are referenced by name only — never stored in plain text."
        actions={
          canWrite ? (
            <Button onClick={() => setShowForm((v) => !v)}>
              <Plus size={16} /> New source
            </Button>
          ) : null
        }
      />

      {banner ? (
        <div
          className={
            banner.tone === "ok"
              ? "mb-4 rounded-md border border-success/30 bg-success-light px-3 py-2 text-sm text-success-dark"
              : "mb-4 rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark"
          }
        >
          {banner.text}
        </div>
      ) : null}

      {showForm && canWrite ? (
        <SourceForm
          providers={providers.data ?? []}
          onClose={() => setShowForm(false)}
          onDone={(message) => {
            setShowForm(false);
            setBanner({ tone: "ok", text: message });
          }}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : null}

      {editing ? (
        <SourceForm
          providers={providers.data ?? []}
          existing={editing}
          onClose={() => setEditing(null)}
          onDone={(message) => {
            setEditing(null);
            setBanner({ tone: "ok", text: message });
          }}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : null}

      <Card>
        <CardHeader
          title="Configured sources"
          description={`${sources.data?.total ?? 0} source(s)`}
          actions={
            <div className="flex gap-2">
              <Select
                className="w-44"
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All categories</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {titleCase(c)}
                  </option>
                ))}
              </Select>
              <TextInput
                className="w-56"
                placeholder="Search name"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          }
        />

        {sources.isLoading ? (
          <LoadingRows />
        ) : sources.isError ? (
          <ErrorState error={sources.error} onRetry={() => sources.refetch()} />
        ) : sources.data && sources.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Source</Th>
                  <Th>Provider</Th>
                  <Th>Status</Th>
                  <Th>Last verified</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {sources.data.items.map((source) => (
                  <Tr key={source.id}>
                    <Td>
                      <p className="font-medium text-ink">{source.name}</p>
                      <p className="text-xs text-muted">{source.dataset_name || source.dataset_identifier}</p>
                      <p className="text-xs text-muted">{source.dataset_count} dataset(s) stored</p>
                    </Td>
                    <Td>
                      <p className="text-xs font-medium text-ink-soft">{source.provider_key}</p>
                      <p className="text-xs text-muted">{titleCase(source.category)}</p>
                      <p className="text-xs text-muted">
                        {source.auth_method === "none" ? "No credentials" : `${source.auth_method} (referenced)`}
                      </p>
                    </Td>
                    <Td>
                      <Badge
                        className={
                          source.error_status
                            ? "bg-danger-light text-danger-dark"
                            : source.status === "configured"
                              ? "bg-info-light text-info-dark"
                              : "bg-canvas text-muted"
                        }
                      >
                        {source.error_status ? "error" : source.status}
                      </Badge>
                      {source.last_test_message ? (
                        <p className="mt-1 max-w-xs text-xs text-muted">{source.last_test_message}</p>
                      ) : null}
                    </Td>
                    <Td>
                      <p>{formatDateTime(source.last_test_at)}</p>
                      {source.last_success_at ? (
                        <p className="text-xs text-muted">Ingested {formatDateTime(source.last_success_at)}</p>
                      ) : null}
                    </Td>
                    <Td align="right">
                      {canWrite || canTest ? (
                        <div className="flex flex-wrap justify-end gap-1">
                          {canTest ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              loading={testingId === source.id && test.isPending}
                              onClick={async () => {
                                setBanner(null);
                                setTestingId(source.id);
                                try {
                                  const result = await test.mutateAsync(source.id);
                                  setBanner({
                                    tone: result.status === "verified" ? "ok" : "error",
                                    text: `${source.name}: ${result.message}`,
                                  });
                                } catch (error) {
                                  setBanner({
                                    tone: "error",
                                    text: error instanceof ApiError ? error.message : "Test failed.",
                                  });
                                } finally {
                                  setTestingId(null);
                                }
                              }}
                            >
                              <RefreshCw size={14} /> Test
                            </Button>
                          ) : null}
                          {canWrite ? (
                            <>
                              <Button variant="secondary" size="sm" onClick={() => setEditing(source)}>
                                Edit
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                title="Delete source"
                                loading={remove.isPending}
                                onClick={async () => {
                                  if (!window.confirm(`Delete "${source.name}"? Stored datasets are kept.`)) return;
                                  try {
                                    await remove.mutateAsync(source.id);
                                    setBanner({ tone: "ok", text: `Deleted ${source.name}.` });
                                  } catch (error) {
                                    setBanner({
                                      tone: "error",
                                      text: error instanceof ApiError ? error.message : "Delete failed.",
                                    });
                                  }
                                }}
                              >
                                <Trash2 size={14} />
                              </Button>
                            </>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-xs text-muted">Read only</span>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={sources.data.page}
              pages={sources.data.pages}
              total={sources.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No data sources configured"
            description="Add a provider integration to make its datasets available for ingestion."
          />
        )}
      </Card>

      <ProviderCatalogue />
    </div>
  );
}

function SourceForm({
  providers,
  existing,
  onClose,
  onDone,
  onError,
}: {
  providers: Provider[];
  existing?: DataSource;
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (text: string) => void;
}) {
  const create = useCreateDataSource();
  const update = useUpdateDataSource();

  const [providerKey, setProviderKey] = useState(existing?.provider_key ?? providers[0]?.key ?? "");
  const provider = providers.find((p) => p.key === providerKey);

  const [name, setName] = useState(existing?.name ?? "");
  const [datasetName, setDatasetName] = useState(existing?.dataset_name ?? "");
  const [datasetIdentifier, setDatasetIdentifier] = useState(existing?.dataset_identifier ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [temporalStart, setTemporalStart] = useState(existing?.temporal_start?.slice(0, 10) ?? "");
  const [temporalEnd, setTemporalEnd] = useState(existing?.temporal_end?.slice(0, 10) ?? "");
  const [isEnabled, setIsEnabled] = useState(existing?.is_enabled ?? true);
  const [variables, setVariables] = useState<string[]>(
    existing
      ? Array.isArray(existing.variables)
        ? (existing.variables as Array<{ key?: string }>).map((v) => String(v.key ?? "")).filter(Boolean)
        : []
      : [],
  );

  const availableVariables = (provider?.variables ?? []).map((v) => String((v as { key?: string }).key ?? ""));
  const pending = create.isPending || update.isPending;

  const submit = async () => {
    if (!provider) {
      onError("Choose a provider.");
      return;
    }
    const payload = {
      name: name.trim(),
      provider_key: provider.key,
      category: provider.category,
      dataset_name: datasetName.trim(),
      dataset_identifier: datasetIdentifier.trim(),
      description: description.trim(),
      is_enabled: isEnabled,
      temporal_start: temporalStart || null,
      temporal_end: temporalEnd || null,
      variables: availableVariables
        .filter((v) => variables.includes(v))
        .map((key) => (provider.variables as Array<{ key: string }>).find((x) => x.key === key) ?? { key }),
      auth_method: provider.auth_method,
    };
    try {
      if (existing) {
        await update.mutateAsync({ id: existing.id, payload });
        onDone(`Updated "${payload.name}".`);
      } else {
        const created = await create.mutateAsync(payload);
        onDone(`Created "${created.name}".`);
      }
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "Could not save the source.");
    }
  };

  return (
    <Card className="mb-5">
      <CardHeader
        title={existing ? `Edit — ${existing.name}` : "New data source"}
        description="A source binds a provider product to the variables and time span you intend to ingest."
        actions={
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
        }
      />
      <form
        className="grid gap-4 px-5 py-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Provider" htmlFor="ds-provider" required>
          <Select
            id="ds-provider"
            value={providerKey}
            onChange={(e) => {
              setProviderKey(e.target.value);
              setVariables([]);
            }}
            disabled={Boolean(existing)}
          >
            {providers.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Name" htmlFor="ds-name" required>
          <TextInput
            id="ds-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CHIRPS daily rainfall"
            required
          />
        </Field>
        <Field label="Dataset name" htmlFor="ds-dataset" hint="Human-readable product name.">
          <TextInput id="ds-dataset" value={datasetName} onChange={(e) => setDatasetName(e.target.value)} />
        </Field>
        <Field label="Dataset identifier" htmlFor="ds-identifier" hint="Provider collection identifier, e.g. chirps-v2.0.">
          <TextInput
            id="ds-identifier"
            value={datasetIdentifier}
            onChange={(e) => setDatasetIdentifier(e.target.value)}
          />
        </Field>
        <Field label="Description" htmlFor="ds-desc" className="sm:col-span-2">
          <TextArea
            id="ds-desc"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field label="Temporal start" htmlFor="ds-start" hint="Earliest date to ingest (optional).">
          <TextInput
            id="ds-start"
            type="date"
            value={temporalStart}
            onChange={(e) => setTemporalStart(e.target.value)}
          />
        </Field>
        <Field label="Temporal end" htmlFor="ds-end" hint="Latest date to ingest (optional).">
          <TextInput
            id="ds-end"
            type="date"
            value={temporalEnd}
            onChange={(e) => setTemporalEnd(e.target.value)}
          />
        </Field>
        <Field label="Variables" className="sm:col-span-2" hint="Which measurements to retrieve.">
          {availableVariables.length > 0 ? (
            <div className="flex flex-wrap gap-4 pt-1.5">
              {availableVariables.map((v) => (
                <Checkbox
                  key={v}
                  label={v.replace(/_/g, " ")}
                  checked={variables.includes(v)}
                  onChange={() =>
                    setVariables((prev) =>
                      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v],
                    )
                  }
                />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted">This provider publishes a fixed variable set.</p>
          )}
        </Field>
        <div className="sm:col-span-2">
          <Checkbox
            label="Enabled for ingestion"
            checked={isEnabled}
            onChange={(e) => setIsEnabled(e.currentTarget.checked)}
          />
        </div>
        {provider ? (
          <div className="rounded-md border border-border bg-canvas px-3 py-2 text-xs text-muted sm:col-span-2">
            <p className="font-medium text-ink-soft">{provider.label}</p>
            {provider.product_type ? <p>Product type: {provider.product_type}</p> : null}
            <p>Authentication: {provider.auth_method === "none" ? "none (open endpoint)" : provider.auth_method}</p>
            {provider.verification_note ? <p className="mt-1">{provider.verification_note}</p> : null}
          </div>
        ) : null}
        <div className="flex items-center gap-2 sm:col-span-2">
          <Button type="submit" loading={pending} disabled={!name.trim()}>
            {existing ? "Save changes" : "Create source"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ProviderCatalogue() {
  const providers = useProviders();

  return (
    <Card className="mt-6">
      <CardHeader
        title="Available providers"
        description="Adapters shipped with this deployment and their live-verification status. A grey status means the adapter exists but has not been exercised against the live endpoint."
      />
      {providers.isLoading ? (
        <LoadingRows rows={3} />
      ) : providers.isError ? (
        <ErrorState error={providers.error} onRetry={() => providers.refetch()} />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Provider</Th>
              <Th>Category</Th>
              <Th>Variables</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {(providers.data ?? []).map((p) => (
              <Tr key={p.key}>
                <Td>
                  <p className="font-medium text-ink">{p.label}</p>
                  <p className="text-xs text-muted">{p.key}</p>
                </Td>
                <Td>{titleCase(p.category)}</Td>
                <Td>
                  <div className="flex flex-wrap gap-1">
                    {p.variables.slice(0, 4).map((v) => (
                      <Badge key={String((v as { key: string }).key)} className="bg-canvas text-muted">
                        {String((v as { key: string }).key).replace(/_/g, " ")}
                      </Badge>
                    ))}
                    {p.variables.length > 4 ? (
                      <span className="text-xs text-muted">+{p.variables.length - 4}</span>
                    ) : null}
                  </div>
                </Td>
                <Td>
                  <Badge
                    className={
                      p.adapter_status === "tested"
                        ? "bg-success-light text-success-dark"
                        : "bg-canvas text-muted"
                    }
                  >
                    {p.adapter_status === "tested" ? (
                      <CheckCircle2 size={12} />
                    ) : (
                      <XCircle size={12} />
                    )}
                    {p.adapter_status === "tested" ? "Verified" : "Untested"}
                  </Badge>
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
