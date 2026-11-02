import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardHeader } from "@/components/ui/Card";
import { Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { useDataSources, useDatasets, useQualityFlags, useStudyAreas } from "@/lib/hooks";
import { flagStyle, formatDate, formatNumber, titleCase } from "@/lib/format";

/**
 * Observed (raw retrieval) and derived (processing product) datasets are shown
 * together but always labelled, because a derived product is not an
 * observation.
 */
export function DatasetsPage() {
  const [search, setSearch] = useState("");
  const [qualityFlag, setQualityFlag] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [studyAreaId, setStudyAreaId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [page, setPage] = useState(1);

  const datasets = useDatasets({
    search: search || undefined,
    quality_flag: qualityFlag || undefined,
    data_source_id: sourceId ? Number(sourceId) : undefined,
    study_area_id: studyAreaId ? Number(studyAreaId) : undefined,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    page,
    size: 20,
  });
  const flags = useQualityFlags();
  const sources = useDataSources({ page: 1, size: 100 });
  const studyAreas = useStudyAreas();

  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Datasets"
        description="Retrieved satellite and climate observations, plus any derived products created by preprocessing. Rate each record with its quality flag before using it."
      />

      <Card className="mb-5">
        <div className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
          <TextInput
            placeholder="Search title"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              resetPage();
            }}
          />
          <Select
            value={qualityFlag}
            onChange={(e) => {
              setQualityFlag(e.target.value);
              resetPage();
            }}
          >
            <option value="">All quality flags</option>
            {(flags.data?.flags ?? []).map((f) => (
              <option key={f} value={f}>
                {flagStyle(f).label}
              </option>
            ))}
          </Select>
          <Select
            value={sourceId}
            onChange={(e) => {
              setSourceId(e.target.value);
              resetPage();
            }}
          >
            <option value="">All data sources</option>
            {(sources.data?.items ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
          <Select
            value={studyAreaId}
            onChange={(e) => {
              setStudyAreaId(e.target.value);
              resetPage();
            }}
          >
            <option value="">All study areas</option>
            {(studyAreas.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          <TextInput
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              resetPage();
            }}
          />
          <TextInput
            type="date"
            value={endDate}
            onChange={(e) => {
              setEndDate(e.target.value);
              resetPage();
            }}
          />
        </div>
      </Card>

      <Card>
        <CardHeader title="Stored datasets" description={`${datasets.data?.total ?? 0} dataset(s)`} />
        {datasets.isLoading ? (
          <LoadingRows rows={6} />
        ) : datasets.isError ? (
          <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
        ) : datasets.data && datasets.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Dataset</Th>
                  <Th>Origin</Th>
                  <Th>Period</Th>
                  <Th>Quality</Th>
                  <Th align="right">Detail</Th>
                </tr>
              </thead>
              <tbody>
                {datasets.data.items.map((dataset) => {
                  const style = flagStyle(dataset.quality_flag);
                  return (
                    <Tr key={dataset.id}>
                      <Td>
                        <p className="font-medium text-ink">{dataset.title}</p>
                        <p className="text-xs text-muted">
                          {titleCase(dataset.category)} · {dataset.bands.length} band(s)
                          {dataset.resolution_m ? ` · ${formatNumber(dataset.resolution_m, { digits: 0 })} m` : ""}
                        </p>
                      </Td>
                      <Td>
                        <Badge
                          className={
                            dataset.is_raw
                              ? "bg-water-50 text-water-700"
                              : "bg-signal-100 text-signal-700"
                          }
                        >
                          {dataset.is_raw ? "Observed" : "Derived"}
                        </Badge>
                        <p className="mt-1 text-xs text-muted">
                          {dataset.data_source_name ?? dataset.provider_key}
                        </p>
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        <p>{formatDate(dataset.start_date)}</p>
                        <p className="text-muted">{formatDate(dataset.end_date)}</p>
                      </Td>
                      <Td>
                        <Badge className={style.className} title={style.help}>
                          {style.label}
                        </Badge>
                        {dataset.quality_reason ? (
                          <p className="mt-1 max-w-xs text-xs text-muted">{dataset.quality_reason}</p>
                        ) : null}
                      </Td>
                      <Td align="right">
                        <Link to={`/research/datasets/${dataset.id}`} className="btn-ghost px-2.5 py-1 text-xs">
                          Open
                        </Link>
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={datasets.data.page}
              pages={datasets.data.pages}
              total={datasets.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No datasets yet"
            description="Request an ingestion job, or run preprocessing on existing data to create a derived product."
          />
        )}
      </Card>
    </div>
  );
}
