"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  DatabaseIcon,
  FileTextIcon,
  GitBranchIcon,
  Layers3Icon,
  LinkIcon,
  MapPinIcon,
  ScrollTextIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import {
  FEATURE_QUALITY_STATES,
  allowedPublicationStates,
  useAdminFeatureCorrectionBasis,
  useAdminFeatureDetail,
  useAdminFeatureStateTransitions,
  useNearbyFeatures,
  usePatchAdminFeatureStateMutation,
  useReactivateAdminFeatureStateMutation,
  type AdminFeatureDetailData,
  type NearbyFeatureSummary,
} from "@/api/features";
import { EntityLink } from "@/components/entity-link";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatDateTime, shortId } from "@/lib/format";

type SourceRow = AdminFeatureDetailData["sources"][number];
type CurationRow = AdminFeatureDetailData["curations"][number];
type IssueRow = AdminFeatureDetailData["issues"][number];
type OverrideRow = AdminFeatureDetailData["overrides"][number];
type FileRow = AdminFeatureDetailData["files"][number];
type StateTransitionRow = AdminFeatureDetailData["state_transitions"][number];

const EMPTY_MESSAGE = "데이터가 없습니다.";
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function coordLabel(
  lon: number | null | undefined,
  lat: number | null | undefined,
) {
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
        {typeof count === "number" ? (
          <Badge variant="secondary">{count}</Badge>
        ) : null}
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
              <span className="font-medium">{source.provider}</span>
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
                {source.source_role === "primary" ? (
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
                <JsonBlock value={source} />
              </div>
            </details>
          );
        },
      },
      {
        id: "imported",
        header: "seen",
        cell: ({ row }) => {
          const source = row.original;
          return (
            <>
              <div className="text-muted-foreground">
                {formatDateTime(source.observed_at)}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                imported {formatDateTime(source.imported_at)}
              </div>
            </>
          );
        },
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

function CurationsTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<CurationRow, unknown>[]>(
    () => [
      {
        id: "collection",
        header: "큐레이션",
        cell: ({ row }) => (
          <div className="min-w-56">
            <div className="font-medium">{row.original.title}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge variant="outline">{row.original.theme_name}</Badge>
              {row.original.edition_key ? (
                <Badge variant="secondary">{row.original.edition_key}</Badge>
              ) : null}
            </div>
          </div>
        ),
      },
      {
        id: "source",
        header: "출처",
        cell: ({ row }) => {
          const item = row.original;
          return (
            <div>
              <div>
                {item.source_url ? (
                  <a
                    className="text-primary underline-offset-4 hover:underline"
                    href={item.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {item.source_name ?? item.source_url}
                  </a>
                ) : (
                  (item.source_name ?? "-")
                )}
              </div>
              <div className="font-mono text-xs text-muted-foreground">
                {item.provider ?? "-"} / {item.dataset_key ?? "-"}
              </div>
              <div className="break-all font-mono text-xs text-muted-foreground">
                {item.source_record_key ?? "source record 없음"}
              </div>
            </div>
          );
        },
      },
      {
        id: "item",
        header: "항목",
        cell: ({ row }) => (
          <div>
            <div>{row.original.item_title ?? row.original.feature_name}</div>
            {row.original.item_summary ? (
              <div className="mt-1 text-xs text-muted-foreground">
                {row.original.item_summary}
              </div>
            ) : null}
            <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
              {row.original.external_item_id}
            </div>
            {row.original.address_hint ? (
              <div className="mt-1 text-xs text-muted-foreground">
                {row.original.address_hint}
              </div>
            ) : null}
            <div className="mt-1 flex flex-wrap gap-1">
              <StatusBadge status={row.original.status} />
              <Badge variant="outline">순서 {row.original.sort_order}</Badge>
              <Badge variant="outline">{row.original.curation_relation}</Badge>
              <Badge variant="outline">{row.original.reuse_policy}</Badge>
            </div>
          </div>
        ),
      },
      {
        id: "detail",
        header: "상세",
        enableSorting: false,
        cell: ({ row }) => (
          <details>
            <summary className="cursor-pointer text-xs font-medium">
              전체 정보
            </summary>
            <div className="mt-2 min-w-80">
              <JsonBlock value={row.original} />
            </div>
          </details>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.curations.length} icon={Layers3Icon} title="큐레이션">
      <DataTable
        columns={columns}
        data={data.curations}
        getRowId={(row) => row.curation_item_id}
        emptyMessage={EMPTY_MESSAGE}
        manualSorting={false}
        containerClassName="overflow-auto"
      />
    </Section>
  );
}

function noticeRawValue(source: SourceRow, key: string): string | null {
  const value = source.raw_data[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function noticeHistorySummary(source: SourceRow): string {
  return (
    noticeRawValue(source, "message") ??
    noticeRawValue(source, "description") ??
    noticeRawValue(source, "title") ??
    source.source_record_key
  );
}

function noticeHistoryState(source: SourceRow): string {
  return (
    noticeRawValue(source, "process_status") ??
    noticeRawValue(source, "level") ??
    noticeRawValue(source, "incident_type") ??
    "-"
  );
}

function NoticeHistoryPanel({ data }: { data: AdminFeatureDetailData }) {
  const rows = useMemo(() => {
    const primary = data.sources.filter(
      (source) => source.source_role === "primary",
    );
    return (primary.length > 0 ? primary : data.sources).toSorted(
      (a, b) =>
        Date.parse(b.observed_at) - Date.parse(a.observed_at) ||
        Date.parse(b.imported_at) - Date.parse(a.imported_at) ||
        b.source_record_key.localeCompare(a.source_record_key),
    );
  }, [data.sources]);

  const columns = useMemo<ColumnDef<SourceRow, unknown>[]>(
    () => [
      {
        id: "seen",
        header: "seen",
        cell: ({ row }) => (
          <>
            <div className="text-muted-foreground">
              {formatDateTime(row.original.observed_at)}
            </div>
            <div className="mt-1 font-mono text-xs text-muted-foreground">
              {shortId(row.original.raw_payload_hash, 12)}
            </div>
          </>
        ),
      },
      {
        id: "notice",
        header: "notice",
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original;
          return (
            <div className="max-w-md">
              <div className="truncate font-medium">
                {noticeHistorySummary(source)}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge variant="outline">{source.provider}</Badge>
                <Badge variant="secondary">{source.dataset_key}</Badge>
              </div>
            </div>
          );
        },
      },
      {
        id: "state",
        header: "state",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {noticeHistoryState(row.original)}
          </span>
        ),
      },
      {
        id: "raw",
        header: "raw",
        enableSorting: false,
        cell: ({ row }) => (
          <details>
            <summary className="cursor-pointer font-mono text-xs">
              {shortId(row.original.source_record_key, 18)}
            </summary>
            <div className="mt-2 min-w-72">
              <JsonBlock value={row.original.raw_data} />
            </div>
          </details>
        ),
      },
    ],
    [],
  );

  if (data.feature.kind !== "notice") return null;

  return (
    <Section count={rows.length} icon={ScrollTextIcon} title="Notice History">
      <DataTable
        columns={columns}
        data={rows}
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
          <EntityLink
            className="font-mono text-xs"
            id=""
            kind="issue"
            params={{ feature_id: data.feature.feature_id }}
          >
            {row.original.violation_type}
          </EntityLink>
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
    [data.feature.feature_id],
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
    <Section
      count={data.overrides.length}
      icon={GitBranchIcon}
      title="Overrides"
    >
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
              <div className="break-all font-mono text-xs">
                {file.object_key}
              </div>
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
          <span className="font-mono text-xs">
            {row.original.byte_size ?? "-"}
          </span>
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

function NearbyPanel({
  featureId,
  feature,
}: {
  featureId: string;
  feature: AdminFeatureDetailData["feature"];
}) {
  const hasCoord =
    typeof feature.lon === "number" && typeof feature.lat === "number";
  const nearby = useNearbyFeatures(
    hasCoord
      ? {
          lon: feature.lon as number,
          lat: feature.lat as number,
          radius_m: 3000,
          page_size: 12,
          sort: "distance",
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
      {hasCoord &&
      !nearby.isLoading &&
      !nearby.isError &&
      items.length === 0 ? (
        <div className="text-sm text-muted-foreground">
          주변 feature가 없습니다.
        </div>
      ) : null}
    </Section>
  );
}

function FeatureMapPanel({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"];
}) {
  const hasCoord =
    typeof feature.lon === "number" && typeof feature.lat === "number";

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
          <summary className="cursor-pointer text-sm font-medium">
            detail
          </summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.detail} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            raw_refs
          </summary>
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
          <summary className="cursor-pointer text-sm font-medium">
            address
          </summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.address} />
          </div>
        </details>
      </div>
    </Section>
  );
}

function FeatureStatePanel({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"];
}) {
  const basis = useAdminFeatureCorrectionBasis(feature.feature_id);
  const transitions = useAdminFeatureStateTransitions(feature.feature_id);
  const patchState = usePatchAdminFeatureStateMutation();
  const reactivate = useReactivateAdminFeatureStateMutation();
  const [publicationState, setPublicationState] = useState(
    feature.publication_state,
  );
  const [qualityState, setQualityState] = useState(feature.quality_state);
  const [reasonCode, setReasonCode] = useState("admin_ui_state_patch");
  const [providerDatasetId, setProviderDatasetId] = useState("");
  const [sourceEntityKey, setSourceEntityKey] = useState("");
  const [sourceRecordKey, setSourceRecordKey] = useState("");

  // 서버가 새 상태를 돌려주면 편집 중이던 select 값을 그것으로 되돌린다.
  //
  // `useEffect`로 하면 렌더 -> effect -> setState -> 재렌더가 되어 한 프레임 동안
  // 낡은 값이 그려진다. React 19의 `react-hooks/set-state-in-effect`가 막는 것이
  // 그 cascading render다. 대신 렌더 중에 직전 동기화 지점을 비교해 조정한다 -
  // React가 문서화한 "prop이 바뀔 때 state 조정" 패턴이고, 재렌더가 커밋 전에
  // 합쳐져 낡은 값이 화면에 나가지 않는다.
  const [syncedState, setSyncedState] = useState({
    publication: feature.publication_state,
    quality: feature.quality_state,
  });
  if (
    syncedState.publication !== feature.publication_state ||
    syncedState.quality !== feature.quality_state
  ) {
    setSyncedState({
      publication: feature.publication_state,
      quality: feature.quality_state,
    });
    setPublicationState(feature.publication_state);
    setQualityState(feature.quality_state);
  }

  const submitPatch = () => {
    if (!basis.data) return;
    const publicationChanged = publicationState !== feature.publication_state;
    const qualityChanged = qualityState !== feature.quality_state;
    if (!publicationChanged && !qualityChanged) return;
    patchState.mutate({
      featureId: basis.data.featureId,
      entityTag: basis.data.entityTag,
      body: {
        action: "patch",
        publication_state: publicationChanged ? publicationState : undefined,
        quality_state: qualityChanged ? qualityState : undefined,
        reason_code: reasonCode.trim() || "admin_ui_state_patch",
      },
    });
  };

  const retire = () => {
    if (!basis.data || feature.lifecycle_state === "retired") return;
    patchState.mutate({
      featureId: basis.data.featureId,
      entityTag: basis.data.entityTag,
      body: {
        action: "retire",
        reason_code: reasonCode.trim() || "admin_ui_retire",
      },
    });
  };

  const submitReactivate = () => {
    const parsedDatasetId = Number(providerDatasetId);
    if (
      !basis.data ||
      !Number.isSafeInteger(parsedDatasetId) ||
      parsedDatasetId < 1 ||
      sourceEntityKey.trim().length === 0 ||
      sourceRecordKey.trim().length === 0
    ) {
      return;
    }
    reactivate.mutate({
      featureId: basis.data.featureId,
      entityTag: basis.data.entityTag,
      body: {
        provider_dataset_id: parsedDatasetId,
        source_entity_key: sourceEntityKey.trim(),
        source_record_key: sourceRecordKey.trim(),
        reason_code: reasonCode.trim() || "admin_ui_reactivate",
      },
    });
  };

  const transitionRows = transitions.data?.data.items ?? [];
  const transitionColumns = useMemo<ColumnDef<StateTransitionRow, unknown>[]>(
    () => [
      {
        id: "transition",
        header: "전이",
        cell: ({ row }) => (
          <div className="flex flex-col gap-1">
            <span className="font-mono text-xs">
              #{row.original.transition_id}
            </span>
            <span>{row.original.transition_kind}</span>
          </div>
        ),
      },
      {
        id: "states",
        header: "상태 축",
        cell: ({ row }) => (
          <div className="text-xs">
            <div>
              {row.original.from_lifecycle_state ?? "-"} /{" "}
              {row.original.from_publication_state ?? "-"} /{" "}
              {row.original.from_quality_state ?? "-"}
            </div>
            <div>
              → {row.original.to_lifecycle_state} /{" "}
              {row.original.to_publication_state} /{" "}
              {row.original.to_quality_state}
            </div>
          </div>
        ),
      },
      {
        id: "receipt",
        header: "감사",
        cell: ({ row }) => (
          <div className="text-xs">
            <div>{row.original.reason_code}</div>
            <div className="text-muted-foreground">
              {row.original.principal} · r{row.original.row_revision}
            </div>
            <div className="text-muted-foreground">
              {formatDateTime(row.original.occurred_at)}
            </div>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <Section
      count={transitionRows.length}
      icon={GitBranchIcon}
      title="상태 축과 감사 이력"
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-1">
          <FeatureStateBadges
            lifecycleState={feature.lifecycle_state}
            publicationState={feature.publication_state}
            qualityState={feature.quality_state}
          />
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          <NativeSelect
            aria-label="공개 상태 변경"
            value={publicationState}
            onChange={(event) =>
              setPublicationState(
                event.target.value as typeof feature.publication_state,
              )
            }
          >
            {allowedPublicationStates(feature.lifecycle_state).map((state) => (
              <NativeSelectOption key={state} value={state}>
                {state}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="품질 상태 변경"
            value={qualityState}
            onChange={(event) =>
              setQualityState(
                event.target.value as typeof feature.quality_state,
              )
            }
          >
            {FEATURE_QUALITY_STATES.map((state) => (
              <NativeSelectOption key={state} value={state}>
                {state}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Input
            aria-label="상태 변경 사유 코드"
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={
              basis.isLoading ||
              patchState.isPending ||
              (publicationState === feature.publication_state &&
                qualityState === feature.quality_state)
            }
            size="sm"
            type="button"
            variant="outline"
            onClick={submitPatch}
          >
            공개·품질 적용
          </Button>
          <Button
            disabled={
              basis.isLoading ||
              patchState.isPending ||
              feature.lifecycle_state === "retired"
            }
            size="sm"
            type="button"
            variant="destructive"
            onClick={retire}
          >
            종료
          </Button>
        </div>
        {feature.lifecycle_state === "retired" ? (
          <div className="grid gap-2 rounded-md border p-3 md:grid-cols-4">
            <Input
              aria-label="재활성 provider dataset ID"
              inputMode="numeric"
              min={1}
              placeholder="provider dataset ID"
              value={providerDatasetId}
              onChange={(event) => setProviderDatasetId(event.target.value)}
            />
            <Input
              aria-label="재활성 source entity key"
              placeholder="source entity key"
              value={sourceEntityKey}
              onChange={(event) => setSourceEntityKey(event.target.value)}
            />
            <Input
              aria-label="재활성 source record key"
              placeholder="current source record key"
              value={sourceRecordKey}
              onChange={(event) => setSourceRecordKey(event.target.value)}
            />
            <Button
              disabled={basis.isLoading || reactivate.isPending}
              size="sm"
              type="button"
              variant="outline"
              onClick={submitReactivate}
            >
              현재 source로 재활성화
            </Button>
          </div>
        ) : null}
        {basis.isError || patchState.isError || reactivate.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상태 명령 실패</AlertTitle>
            <AlertDescription>
              {basis.error?.message ??
                patchState.error?.message ??
                reactivate.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {transitions.isLoading ? <Skeleton className="h-28" /> : null}
        {transitions.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상태 감사 이력 조회 실패</AlertTitle>
            <AlertDescription>{transitions.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {transitionRows.length > 0 ? (
          <DataTable
            columns={transitionColumns}
            data={transitionRows}
            getRowId={(row) => String(row.transition_id)}
            emptyMessage={EMPTY_MESSAGE}
            manualSorting={false}
            containerClassName="overflow-auto"
          />
        ) : null}
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

  const primarySource = data.sources.find(
    (source) => source.source_role === "primary",
  );

  return (
    <div className="flex flex-col gap-4" data-testid="feature-detail-view">
      <section className="rounded-lg border bg-background p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-2">
              <FeatureStateBadges
                lifecycleState={feature.lifecycle_state}
                publicationState={feature.publication_state}
                qualityState={feature.quality_state}
              />
              <Badge variant="outline">{feature.kind}</Badge>
              <Badge variant="outline">{feature.category}</Badge>
            </div>
            <h2 className="mt-3 break-keep text-xl font-semibold">
              {feature.name}
            </h2>
            <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
              {feature.feature_id}
            </div>
          </div>
          <dl className="grid min-w-64 grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">coord</dt>
            <dd className="font-mono">
              {coordLabel(feature.lon, feature.lat)}
            </dd>
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
          <CurationsTable data={data} />
          <NoticeHistoryPanel data={data} />
          <IssuesTable data={data} />
          <OverridesTable data={data} />
          <FeatureStatePanel feature={feature} />
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
