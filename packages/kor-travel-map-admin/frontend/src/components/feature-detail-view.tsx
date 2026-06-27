"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  DatabaseIcon,
  FileTextIcon,
  GitBranchIcon,
  LinkIcon,
  MapPinIcon,
  ScrollTextIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, type ReactNode } from "react";

import {
  useAdminFeatureDetail,
  useNearbyFeatures,
  type AdminFeatureDetailData,
  type NearbyFeatureSummary,
} from "@/api/features";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatDateTime, shortId } from "@/lib/format";

type SourceRow = AdminFeatureDetailData["sources"][number];
type IssueRow = AdminFeatureDetailData["issues"][number];
type OverrideRow = AdminFeatureDetailData["overrides"][number];
type FileRow = AdminFeatureDetailData["files"][number];
type VersionRow = AdminFeatureDetailData["versions"][number];
type ChangeRequestRow = AdminFeatureDetailData["change_requests"][number];

const EMPTY_MESSAGE = "데이터가 없습니다.";
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function coordLabel(lon: number | null | undefined, lat: number | null | undefined) {
  if (typeof lon === "number" && typeof lat === "number") {
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return "-";
}

function distanceLabel(distanceM: number): string {
  if (distanceM >= 1000) {
    return `${(distanceM / 1000).toFixed(2)} km`;
  }
  return `${Math.round(distanceM)} m`;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Section({
  title,
  count,
  icon: Icon,
  children,
}: {
  title: string;
  count?: number;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2 font-medium">
          <Icon className="size-4 text-muted-foreground" />
          <span>{title}</span>
        </div>
        {typeof count === "number" ? <Badge variant="secondary">{count}</Badge> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function SourcesTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<SourceRow, unknown>[]>(
    () => [
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => {
          const source = row.original;
          return (
            <>
              <div className="font-medium">{source.provider}</div>
              <div className="font-mono text-xs text-muted-foreground">
                {source.dataset_key}
              </div>
            </>
          );
        },
      },
      {
        id: "role",
        header: "role",
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original;
          return (
            <>
              <div className="flex flex-wrap gap-1">
                <Badge variant="outline">{source.source_role}</Badge>
                {source.is_primary_source ? (
                  <Badge variant="secondary">primary</Badge>
                ) : null}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {source.match_method} · {source.confidence}
              </div>
            </>
          );
        },
      },
      {
        id: "entity",
        header: "entity",
        cell: ({ row }) => {
          const source = row.original;
          return (
            <>
              <div>{source.source_entity_type}</div>
              <div className="break-all font-mono text-xs text-muted-foreground">
                {source.source_entity_id}
              </div>
            </>
          );
        },
      },
      {
        id: "raw",
        header: "raw",
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original;
          return (
            <details>
              <summary className="cursor-pointer font-mono text-xs">
                {shortId(source.source_record_key, 18)}
              </summary>
              <div className="mt-2 min-w-72">
                <JsonBlock value={source.raw_data} />
              </div>
            </details>
          );
        },
      },
      {
        id: "imported",
        header: "imported",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.imported_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.sources.length} icon={DatabaseIcon} title="Sources">
      <DataTable
        columns={columns}
        data={data.sources}
        getRowId={(row) => row.source_record_key}
        emptyMessage={EMPTY_MESSAGE}
        manualSorting={false}
        containerClassName="overflow-auto"
      />
    </Section>
  );
}

function IssuesTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<IssueRow, unknown>[]>(
    () => [
      {
        id: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "severity",
        header: "severity",
        cell: ({ row }) => <StatusBadge status={row.original.severity} />,
      },
      {
        accessorKey: "violation_type",
        header: "type",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.violation_type}</span>
        ),
      },
      {
        id: "message",
        header: "message",
        enableSorting: false,
        cell: ({ row }) => {
          const issue = row.original;
          return (
            <div className="max-w-md">
              <div className="truncate">{issue.message}</div>
              {Object.keys(issue.payload).length > 0 ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-muted-foreground">
                    payload
                  </summary>
                  <JsonBlock value={issue.payload} />
                </details>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "detected",
        header: "detected",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.detected_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.issues.length} icon={AlertTriangleIcon} title="Issues">
      <DataTable
        columns={columns}
        data={data.issues}
        getRowId={(row) => row.issue_id}
        emptyMessage={EMPTY_MESSAGE}
        manualSorting={false}
        containerClassName="overflow-auto"
      />
    </Section>
  );
}

function OverridesTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<OverrideRow, unknown>[]>(
    () => [
      {
        id: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "field_path",
        header: "field",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.field_path}</span>
        ),
      },
      {
        id: "value",
        header: "value",
        enableSorting: false,
        cell: ({ row }) => {
          const override = row.original;
          return (
            <details>
              <summary className="cursor-pointer text-xs text-muted-foreground">
                override
              </summary>
              <div className="mt-2 min-w-72">
                <JsonBlock
                  value={{
                    source: override.source_value,
                    override: override.override_value,
                  }}
                />
              </div>
            </details>
          );
        },
      },
      {
        id: "reason",
        header: "reason",
        enableSorting: false,
        cell: ({ row }) => <>{row.original.reason ?? "-"}</>,
      },
      {
        id: "created",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.overrides.length} icon={GitBranchIcon} title="Overrides">
      <DataTable
        columns={columns}
        data={data.overrides}
        getRowId={(row) => row.override_id}
        emptyMessage={EMPTY_MESSAGE}
        manualSorting={false}
        containerClassName="overflow-auto"
      />
    </Section>
  );
}

function FilesTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<FileRow, unknown>[]>(
    () => [
      {
        id: "role",
        header: "role",
        cell: ({ row }) => {
          const file = row.original;
          return (
            <>
              <Badge variant="outline">{file.role}</Badge>
              <div className="mt-1 text-xs text-muted-foreground">
                {file.file_type}
              </div>
            </>
          );
        },
      },
      {
        id: "object",
        header: "object",
        enableSorting: false,
        cell: ({ row }) => {
          const file = row.original;
          return (
            <>
              <div className="break-all font-mono text-xs">{file.object_key}</div>
              {file.public_url ? (
                <Link
                  className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
                  href={file.public_url}
                  rel="noreferrer"
                  target="_blank"
                  onClick={(event) => event.stopPropagation()}
                >
                  public_url
                </Link>
              ) : null}
            </>
          );
        },
      },
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => {
          const file = row.original;
          return (
            <>
              <div>{file.provider ?? "-"}</div>
              <div className="font-mono text-xs text-muted-foreground">
                {file.dataset_key ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        accessorKey: "byte_size",
        header: "size",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.byte_size ?? "-"}</span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.files.length} icon={FileTextIcon} title="Files">
      <DataTable
        columns={columns}
        data={data.files}
        getRowId={(row) => row.file_id}
        emptyMessage={EMPTY_MESSAGE}
        manualSorting={false}
        containerClassName="overflow-auto"
      />
    </Section>
  );
}

function HistoryPanel({ data }: { data: AdminFeatureDetailData }) {
  const versionColumns = useMemo<ColumnDef<VersionRow, unknown>[]>(
    () => [
      {
        accessorKey: "version",
        header: "version",
        cell: ({ row }) => <span className="font-mono">{row.original.version}</span>,
      },
      { accessorKey: "origin", header: "origin" },
      { accessorKey: "change_kind", header: "change" },
      {
        id: "created",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
    ],
    [],
  );

  const changeColumns = useMemo<ColumnDef<ChangeRequestRow, unknown>[]>(
    () => [
      {
        id: "request",
        header: "request",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.request_id, 12)}
          </span>
        ),
      },
      { accessorKey: "action", header: "action" },
      {
        id: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "created",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section
      count={data.versions.length + data.change_requests.length}
      icon={ScrollTextIcon}
      title="History"
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <DataTable
          columns={versionColumns}
          data={data.versions}
          getRowId={(row) => `${row.feature_id}:${row.version}`}
          emptyMessage={EMPTY_MESSAGE}
          manualSorting={false}
          containerClassName="overflow-auto"
        />
        <DataTable
          columns={changeColumns}
          data={data.change_requests}
          getRowId={(row) => row.request_id}
          emptyMessage={EMPTY_MESSAGE}
          manualSorting={false}
          containerClassName="overflow-auto"
        />
      </div>
    </Section>
  );
}

function NearbyPanel({
  featureId,
  feature,
}: {
  featureId: string;
  feature: AdminFeatureDetailData["feature"];
}) {
  const hasCoord = typeof feature.lon === "number" && typeof feature.lat === "number";
  const nearby = useNearbyFeatures(
    hasCoord
      ? {
          lon: feature.lon as number,
          lat: feature.lat as number,
          radius_m: 3000,
          page_size: 12,
          sort: "distance",
          status: ["active"],
        }
      : null,
  );
  const items = (nearby.data?.data.items ?? [])
    .filter((item: NearbyFeatureSummary) => item.feature_id !== featureId)
    .slice(0, 10);

  const columns = useMemo<ColumnDef<NearbyFeatureSummary, unknown>[]>(
    () => [
      {
        id: "feature",
        header: "feature",
        cell: ({ row }) => {
          const item = row.original;
          return (
            <>
              <Link
                className="font-medium text-primary underline-offset-4 hover:underline"
                href={featureHref(item.feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                {item.name}
              </Link>
              <div className="font-mono text-xs text-muted-foreground">
                {shortId(item.feature_id, 16)}
              </div>
            </>
          );
        },
      },
      {
        id: "kind",
        header: "kind",
        cell: ({ row }) => <Badge variant="outline">{row.original.kind}</Badge>,
      },
      {
        accessorKey: "distance_m",
        header: "distance",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {distanceLabel(row.original.distance_m)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={items.length} icon={MapPinIcon} title="Nearby">
      {nearby.isLoading ? <Skeleton className="h-36 w-full" /> : null}
      {nearby.isError ? (
        <Alert variant="destructive">
          <AlertTitle>nearby 호출 실패</AlertTitle>
          <AlertDescription>{nearby.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {!hasCoord ? (
        <div className="text-sm text-muted-foreground">좌표가 없습니다.</div>
      ) : null}
      {items.length > 0 ? (
        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.feature_id}
          emptyMessage={EMPTY_MESSAGE}
          manualSorting={false}
          containerClassName="overflow-auto"
        />
      ) : null}
      {hasCoord && !nearby.isLoading && !nearby.isError && items.length === 0 ? (
        <div className="text-sm text-muted-foreground">주변 feature가 없습니다.</div>
      ) : null}
    </Section>
  );
}

function FeatureMapPanel({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"];
}) {
  const hasCoord = typeof feature.lon === "number" && typeof feature.lat === "number";

  return (
    <Section icon={MapPinIcon} title="Map">
      {hasCoord ? (
        <div className="relative h-64 overflow-hidden rounded-md border">
          <VWorldMapView
            apiKey={VWORLD_KEY}
            center={[feature.lon as number, feature.lat as number]}
            className="absolute inset-0 h-full w-full"
            key={feature.feature_id}
            navigation
            scale
            zoom={14}
          >
            <VWorldMarker
              lngLat={[feature.lon as number, feature.lat as number]}
              markerColor="#2563eb"
              selected
              title={feature.name}
            />
          </VWorldMapView>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">
          좌표가 없어 지도 marker를 표시할 수 없습니다.
        </div>
      )}
    </Section>
  );
}

function RawPanels({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section icon={LinkIcon} title="Raw">
      <div className="flex flex-col gap-3">
        <details open>
          <summary className="cursor-pointer text-sm font-medium">detail</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.detail} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">raw_refs</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.raw_refs} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">urls</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.urls} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">address</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.address} />
          </div>
        </details>
      </div>
    </Section>
  );
}

export function FeatureDetailView({ featureId }: { featureId: string }) {
  const detail = useAdminFeatureDetail(featureId);
  const data = detail.data?.data;
  const feature = data?.feature;

  if (detail.isLoading) {
    return <Skeleton className="h-[36rem] w-full" />;
  }

  if (detail.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>feature 상세 조회 실패</AlertTitle>
        <AlertDescription>{detail.error.message}</AlertDescription>
      </Alert>
    );
  }

  if (!data || !feature) {
    return null;
  }

  const primarySource = data.sources.find((source) => source.is_primary_source);

  return (
    <div className="flex flex-col gap-4" data-testid="feature-detail-view">
      <section className="rounded-lg border bg-background p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-2">
              <StatusBadge status={feature.status} />
              <Badge variant="outline">{feature.kind}</Badge>
              <Badge variant="outline">{feature.category}</Badge>
              <Badge variant="secondary">{feature.data_origin}</Badge>
            </div>
            <h2 className="mt-3 break-keep text-xl font-semibold">{feature.name}</h2>
            <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
              {feature.feature_id}
            </div>
          </div>
          <dl className="grid min-w-64 grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">coord</dt>
            <dd className="font-mono">{coordLabel(feature.lon, feature.lat)}</dd>
            <dt className="text-muted-foreground">sigungu</dt>
            <dd>{feature.sigungu_code ?? "-"}</dd>
            <dt className="text-muted-foreground">updated</dt>
            <dd>{formatDateTime(feature.updated_at)}</dd>
            <dt className="text-muted-foreground">provider</dt>
            <dd>{primarySource?.provider ?? "-"}</dd>
          </dl>
        </div>
      </section>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <SourcesTable data={data} />
          <IssuesTable data={data} />
          <OverridesTable data={data} />
          <HistoryPanel data={data} />
          <FilesTable data={data} />
        </div>
        <aside className="flex min-w-0 flex-col gap-4">
          <FeatureMapPanel feature={feature} />
          <FeatureKindDetailPanel feature={feature} featureId={featureId} />
          <NearbyPanel feature={feature} featureId={featureId} />
          <RawPanels data={data} />
        </aside>
      </div>
    </div>
  );
}
