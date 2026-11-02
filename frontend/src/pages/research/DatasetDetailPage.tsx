import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Globe } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { DetailList } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ErrorState, LoadingRows } from "@/components/ui/States";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { useAuth } from "@/auth/AuthContext";
import { useDataset, usePublish } from "@/lib/hooks";
import { flagStyle, formatBytes, formatDate, formatDateTime, formatNumber } from "@/lib/format";

export function DatasetDetailPage() {
  const { datasetId } = useParams();
  const navigate = useNavigate();
  const id = datasetId ? Number(datasetId) : null;
  const dataset = useDataset(Number.isFinite(id) ? id : null);
  const { can: hasPermission } = useAuth();
  const publish = usePublish("datasets", ["datasets"]);

  if (dataset.isLoading) {
    return (
      <div>
        <BackLink />
        <Card>
          <LoadingRows rows={6} />
        </Card>
      </div>
    );
  }

  if (dataset.isError || !dataset.data) {
    return (
      <div>
        <BackLink />
        <Card>
          <ErrorState error={dataset.error} onRetry={() => dataset.refetch()} />
        </Card>
      </div>
    );
  }

  const d = dataset.data;
  const style = flagStyle(d.quality_flag);
  const stats = d.band_statistics ?? {};

  return (
    <div>
      <BackLink />
      <PageHeader
        title={d.title}
        description={
          d.is_raw
            ? "Observed retrieval. Values are stored in physical units; no scientific conclusion is implied by their presence."
            : "Derived product produced by preprocessing. This is not an observation — it depends on the documented operations applied to its inputs."
        }
        actions={
          <div className="flex items-center gap-2">
            <Badge
              className={d.is_raw ? "bg-water-50 text-water-700" : "bg-signal-100 text-signal-700"}
            >
              {d.is_raw ? "Observed" : "Derived"}
            </Badge>
            <Badge className={style.className} title={style.help}>
              {style.label}
            </Badge>
            {hasPermission("public.publish") ? (
              <Button
                variant="secondary"
                size="sm"
                loading={publish.isPending}
                onClick={() =>
                  publish.mutate({ id: d.id, is_public: !d.is_public })
                }
              >
                <Globe size={14} />
                {d.is_public ? "Remove from public" : "Publish publicly"}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Metadata" />
          <CardBody>
            <DetailList
              columns={3}
              items={[
                { label: "Provider", value: d.provider_key },
                { label: "Category", value: d.category },
                { label: "Product type", value: d.product_type || "—" },
                { label: "Data source", value: d.data_source_name ?? "—" },
                { label: "Study area", value: d.study_area_name ?? "—" },
                { label: "CRS", value: d.crs ?? "—" },
                { label: "Start date", value: formatDate(d.start_date) },
                { label: "End date", value: formatDate(d.end_date) },
                {
                  label: "Resolution",
                  value: d.resolution_m ? `${formatNumber(d.resolution_m, { digits: 0 })} m` : "—",
                },
                { label: "Format", value: d.format ?? "—" },
                { label: "Size", value: formatBytes(d.size_bytes) },
                { label: "Checksum", value: <span className="font-mono text-xs">{d.checksum ?? "—"}</span> },
                { label: "Stored", value: formatDateTime(d.created_at) },
              ]}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Quality" description={`Rule version governs how flags are assigned.`} />
          <CardBody>
            <p className="text-sm text-ink-soft">{d.quality_reason || "No note recorded."}</p>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">Coverage</dt>
                <dd className="tabular">{d.coverage_fraction != null ? `${(d.coverage_fraction * 100).toFixed(1)}%` : "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Indicator results</dt>
                <dd className="tabular">{d.indicator_result_count}</dd>
              </div>
            </dl>
            {d.quality_assessments.length > 0 ? (
              <ul className="mt-4 space-y-2 border-t border-border pt-3">
                {d.quality_assessments.map((qa) => (
                  <li key={qa.id} className="text-xs">
                    <Badge className={flagStyle(qa.flag).className}>{flagStyle(qa.flag).label}</Badge>
                    <span className="ml-2 text-muted">rules {qa.rule_version}</span>
                    <p className="mt-0.5 text-muted">{qa.reason}</p>
                  </li>
                ))}
              </ul>
            ) : null}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title="Bands"
          description="Scale and offset are the provider's documented values; stored values are already in physical units."
        />
        <Table>
          <thead>
            <tr>
              <Th>Band</Th>
              <Th>Unit</Th>
              <Th align="right">Scale</Th>
              <Th align="right">Offset</Th>
              <Th align="right">Wavelength (nm)</Th>
              <Th>Description</Th>
            </tr>
          </thead>
          <tbody>
            {d.bands.map((band) => (
              <Tr key={band.key}>
                <Td>
                  <span className="font-mono text-xs">{band.key}</span>
                  <p className="text-xs text-muted">{band.label}</p>
                </Td>
                <Td>{band.unit || "—"}</Td>
                <Td align="right">{band.scale}</Td>
                <Td align="right">{band.offset}</Td>
                <Td align="right">{band.wavelength_nm ?? "—"}</Td>
                <Td className="max-w-sm text-xs">{band.description || "—"}</Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {Object.keys(stats).length > 0 ? (
        <Card className="mt-5">
          <CardHeader
            title="Descriptive statistics"
            description="Summary of stored values for exploration only. These are descriptive, not indicator results."
          />
          <Table>
            <thead>
              <tr>
                <Th>Band</Th>
                <Th align="right">Valid pixels</Th>
                <Th align="right">Valid fraction</Th>
                <Th align="right">Min</Th>
                <Th align="right">Max</Th>
                <Th align="right">Mean</Th>
                <Th align="right">Std</Th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats).map(([band, s]) => (
                <Tr key={band}>
                  <Td>
                    <span className="font-mono text-xs">{band}</span>
                  </Td>
                  <Td align="right">{s.count.toLocaleString()}</Td>
                  <Td align="right">
                    {s.valid_fraction != null ? `${(s.valid_fraction * 100).toFixed(1)}%` : "—"}
                  </Td>
                  <Td align="right">{formatNumber(s.min)}</Td>
                  <Td align="right">{formatNumber(s.max)}</Td>
                  <Td align="right">{formatNumber(s.mean)}</Td>
                  <Td align="right">{formatNumber(s.std)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}

      {d.provenance ? (
        <Card className="mt-5">
          <CardHeader title="Provenance" description="How this dataset was obtained or produced." />
          <CardBody>
            <pre className="max-h-72 overflow-auto rounded bg-canvas p-3 text-xs text-ink-soft">
              {JSON.stringify(d.provenance, null, 2)}
            </pre>
          </CardBody>
        </Card>
      ) : null}

      <div className="mt-5 flex gap-2">
        <Button variant="secondary" onClick={() => navigate("/research/datasets")}>
          <ArrowLeft size={16} /> Back to datasets
        </Button>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/research/datasets" className="mb-3 inline-flex items-center gap-1 text-sm text-water-700 hover:underline">
      <ArrowLeft size={14} /> Datasets
    </Link>
  );
}
