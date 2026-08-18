"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import {
  FEATURE_QUALITY_STATES,
  allowedPublicationStates,
  featureStateLabel,
  useAdminFeatureCorrectionBasis,
  useAdminFeatureDetail,
  useAdminFeatureStateTransitions,
  useNearbyFeatures,
  usePatchAdminFeatureStateMutation,
  useReactivateAdminFeatureStateMutation,
  type AdminFeatureDetailData,
  type NearbyFeatureSummary,
} from "@/api/features";
import { useConfirm } from "@/components/confirm-dialog";
import { CopyButton } from "@/components/copy-button";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { JsonViewer } from "@/components/json-viewer";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  DataTableClampCell,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

type SourceRow = AdminFeatureDetailData["sources"][number];
type CurationRow = AdminFeatureDetailData["curations"][number];
type IssueRow = AdminFeatureDetailData["issues"][number];
type OverrideRow = AdminFeatureDetailData["overrides"][number];
type FileRow = AdminFeatureDetailData["files"][number];
type StateTransitionRow = AdminFeatureDetailData["state_transitions"][number];

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
/** 비교/강조 마커 색은 토큰만(design.md §Theme — marker colours read `--compare-a/b`). */
const DETAIL_MARKER_COLOR = "var(--compare-a)";

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function coordLabel(
  lon: number | null | undefined,
  lat: number | null | undefined,
): string | null {
  if (typeof lon === "number" && typeof lat === "number") {
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return null;
}

function distanceLabel(distanceM: number): string {
  if (distanceM >= 1000) {
    return `${(distanceM / 1000).toFixed(2)} km`;
  }
  return `${Math.round(distanceM)} m`;
}

/** 표 셀 안 1차/2차 텍스트 — 이름 위, 식별자(mono) 아래. 최대 2줄(M27). */
function CellStack({
  primary,
  secondary,
  mono = true,
}: {
  primary: ReactNode;
  secondary?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate">{primary}</span>
      {secondary !== undefined && secondary !== null ? (
        <span
          className={cn(
            "truncate text-2xs text-text-secondary",
            mono && "font-mono slashed-zero",
          )}
        >
          {secondary}
        </span>
      ) : null}
    </div>
  );
}

/** 표 셀 안 접이식 payload — summary는 12px/500, 본문은 JsonViewer(그룹 유일 JSON 렌더러). */
function CellDisclosure({
  summary,
  value,
  mono = false,
}: {
  summary: ReactNode;
  value: unknown;
  mono?: boolean;
}) {
  return (
    <details className="group/details">
      <summary
        className={cn(
          "inline-flex cursor-pointer list-none items-center gap-1 rounded-control text-xs font-medium text-text-secondary outline-none select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden",
          mono && "font-mono font-normal slashed-zero",
        )}
      >
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        {summary}
      </summary>
      <div className="mt-2 min-w-72 max-w-xl">
        <JsonViewer maxHeight="md" value={value} />
      </div>
    </details>
  );
}

/**
 * 상세 페이지의 flush 섹션(design.md §Macrostructure detail — hairline으로만 구분, 카드 없음).
 * 제목은 h3(15px/600), 건수는 muted tabular 텍스트(배지 아님, M22).
 */
function Section({
  title,
  count,
  description,
  actions,
  children,
}: {
  title: string;
  count?: number;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3 className="text-sm leading-snug font-semibold text-text-primary">{title}</h3>
          {typeof count === "number" ? (
            <span
              aria-label={`${title} ${formatCount(count)}건`}
              className="text-xs text-text-secondary tabular-nums"
            >
              {formatCount(count)}
            </span>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        {description ? (
          <p className="basis-full text-xs text-text-secondary">{description}</p>
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function SourcesTable({ data }: { data: AdminFeatureDetailData }) {
  const columns = useMemo<ColumnDef<SourceRow, unknown>[]>(
    () => [
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => (
          <CellStack
            primary={<span className="font-medium">{row.original.provider}</span>}
            secondary={row.original.dataset_key}
          />
        ),
      },
      {
        id: "role",
        header: "role",
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original;
          return (
            <CellStack
              mono={false}
              primary={
                <span className="inline-flex flex-wrap items-center gap-1">
                  <Badge variant={source.source_role === "primary" ? "secondary" : "outline"}>
                    {source.source_role}
                  </Badge>
                </span>
              }
              secondary={`${source.match_method} · ${source.confidence}`}
            />
          );
        },
      },
      {
        id: "entity",
        header: "entity",
        cell: ({ row }) => (
          <CellStack
            primary={row.original.source_entity_type}
            secondary={row.original.source_entity_id}
          />
        ),
      },
      {
        id: "raw",
        header: "raw",
        enableSorting: false,
        cell: ({ row }) => (
          <CellDisclosure
            mono
            summary={shortId(row.original.source_record_key, 18)}
            value={row.original}
          />
        ),
      },
      {
        id: "imported",
        header: "seen",
        cell: ({ row }) => (
          <CellStack
            mono={false}
            primary={
              <span className="text-text-secondary">
                {formatDateTime(row.original.observed_at)}
              </span>
            }
            secondary={`imported ${formatDateTime(row.original.imported_at)}`}
          />
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.sources.length} title="Sources">
      <DataTable
        columns={columns}
        data={data.sources}
        emptyState={{
          title: "연결된 source가 없습니다.",
          description: "provider 적재 결과가 이 feature에 연결되면 여기에 표시됩니다.",
        }}
        getRowId={(row) => row.source_record_key}
        manualSorting={false}
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
          <div className="flex min-w-56 flex-col gap-1">
            <span className="font-medium">{row.original.title}</span>
            <span className="text-2xs text-text-secondary">
              {row.original.theme_name}
              {row.original.edition_key ? <> · {row.original.edition_key}</> : null}
            </span>
          </div>
        ),
      },
      {
        id: "source",
        header: "출처",
        cell: ({ row }) => {
          const item = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate">
                {item.source_url ? (
                  <a
                    className="rounded-control text-brand underline-offset-4 outline-none hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                    href={item.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {item.source_name ?? item.source_url}
                  </a>
                ) : (
                  (item.source_name ?? NULL_GLYPH)
                )}
              </span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {item.provider ?? NULL_GLYPH} / {item.dataset_key ?? NULL_GLYPH}
              </span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {item.source_record_key ?? "source record 없음"}
              </span>
            </div>
          );
        },
      },
      {
        id: "item",
        header: "항목",
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-1">
            <span>{row.original.item_title ?? row.original.feature_name}</span>
            {row.original.item_summary ? (
              <span className="text-2xs text-text-secondary">{row.original.item_summary}</span>
            ) : null}
            <span className="font-mono text-2xs break-all text-text-secondary slashed-zero">
              {row.original.external_item_id}
            </span>
            {row.original.address_hint ? (
              <span className="text-2xs text-text-secondary">{row.original.address_hint}</span>
            ) : null}
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <StatusBadge status={row.original.status} />
              <span className="text-2xs text-text-secondary tabular-nums">
                순서 {row.original.sort_order}
              </span>
              <span className="font-mono text-2xs text-text-secondary">
                {row.original.curation_relation}
              </span>
              <span className="font-mono text-2xs text-text-secondary">
                {row.original.reuse_policy}
              </span>
            </span>
          </div>
        ),
      },
      {
        id: "detail",
        header: "상세",
        enableSorting: false,
        cell: ({ row }) => <CellDisclosure summary="전체 정보" value={row.original} />,
      },
    ],
    [],
  );

  return (
    <Section count={data.curations.length} title="큐레이션">
      <DataTable
        columns={columns}
        data={data.curations}
        emptyState={{
          title: "연결된 큐레이션 항목이 없습니다.",
          description: "큐레이션 collection에서 이 feature를 연결하면 여기에 표시됩니다.",
        }}
        getRowId={(row) => row.curation_item_id}
        manualSorting={false}
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

function noticeHistoryState(source: SourceRow): string | null {
  return (
    noticeRawValue(source, "process_status") ??
    noticeRawValue(source, "level") ??
    noticeRawValue(source, "incident_type")
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
          <CellStack
            primary={
              <span className="text-text-secondary">
                {formatDateTime(row.original.observed_at)}
              </span>
            }
            secondary={shortId(row.original.raw_payload_hash, 12)}
          />
        ),
      },
      {
        id: "notice",
        header: "notice",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const source = row.original;
          return (
            <div className="flex max-w-md min-w-0 flex-col gap-0.5">
              <DataTableClampCell className="font-medium" lines={2}>
                {noticeHistorySummary(source)}
              </DataTableClampCell>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {source.provider} · {source.dataset_key}
              </span>
            </div>
          );
        },
      },
      {
        id: "state",
        header: "state",
        cell: ({ row }) => {
          const state = noticeHistoryState(row.original);
          return (
            <span className={cn("text-text-secondary", state === null && "text-text-tertiary")}>
              {state ?? NULL_GLYPH}
            </span>
          );
        },
      },
      {
        id: "raw",
        header: "raw",
        enableSorting: false,
        cell: ({ row }) => (
          <CellDisclosure
            mono
            summary={shortId(row.original.source_record_key, 18)}
            value={row.original.raw_data}
          />
        ),
      },
    ],
    [],
  );

  if (data.feature.kind !== "notice") return null;

  return (
    <Section count={rows.length} title="Notice History">
      <DataTable
        columns={columns}
        data={rows}
        emptyState={{
          title: "notice 이력이 없습니다.",
          description: "primary source가 관측되면 최신 순으로 쌓입니다.",
        }}
        getRowId={(row) => row.source_record_key}
        manualSorting={false}
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
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const issue = row.original;
          return (
            <div className="flex max-w-md min-w-0 flex-col gap-1">
              <DataTableClampCell lines={2}>{issue.message}</DataTableClampCell>
              {Object.keys(issue.payload).length > 0 ? (
                <CellDisclosure summary="payload" value={issue.payload} />
              ) : null}
            </div>
          );
        },
      },
      {
        id: "detected",
        header: "detected",
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.detected_at)}
          </span>
        ),
      },
    ],
    [data.feature.feature_id],
  );

  return (
    <Section count={data.issues.length} title="Issues">
      <DataTable
        columns={columns}
        data={data.issues}
        emptyState={{
          title: "열린 이슈가 없습니다.",
          description: "정합성 점검에서 위반이 발견되면 여기에 표시됩니다.",
        }}
        getRowId={(row) => row.issue_id}
        manualSorting={false}
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
          <span className="font-mono text-xs slashed-zero">{row.original.field_path}</span>
        ),
      },
      {
        id: "value",
        header: "value",
        enableSorting: false,
        cell: ({ row }) => {
          const override = row.original;
          return (
            <CellDisclosure
              summary="override"
              value={{
                source: override.source_value,
                override: override.override_value,
              }}
            />
          );
        },
      },
      {
        id: "reason",
        header: "reason",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className={cn(!row.original.reason && "text-text-tertiary")}>
            {row.original.reason ?? NULL_GLYPH}
          </span>
        ),
      },
      {
        id: "created",
        header: "created",
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.overrides.length} title="Overrides">
      <DataTable
        columns={columns}
        data={data.overrides}
        emptyState={{
          title: "필드 override가 없습니다.",
          description: "운영자가 값을 덮어쓰면 여기에 이력이 남습니다.",
        }}
        getRowId={(row) => row.override_id}
        manualSorting={false}
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
        cell: ({ row }) => (
          <CellStack
            mono={false}
            primary={<Badge variant="outline">{row.original.role}</Badge>}
            secondary={row.original.file_type}
          />
        ),
      },
      {
        id: "object",
        header: "object",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const file = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="font-mono text-xs break-all slashed-zero">{file.object_key}</span>
              {file.public_url ? (
                <Link
                  className="inline-flex w-fit rounded-control text-xs text-brand underline-offset-4 outline-none hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  href={file.public_url}
                  rel="noreferrer"
                  target="_blank"
                  onClick={(event) => event.stopPropagation()}
                >
                  public_url
                </Link>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => (
          <CellStack
            primary={row.original.provider ?? NULL_GLYPH}
            secondary={row.original.dataset_key ?? NULL_GLYPH}
          />
        ),
      },
      {
        accessorKey: "byte_size",
        header: "size",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className={cn("tabular-nums", row.original.byte_size == null && "text-text-tertiary")}>
            {row.original.byte_size == null ? NULL_GLYPH : formatCount(row.original.byte_size)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={data.files.length} title="Files">
      <DataTable
        columns={columns}
        data={data.files}
        emptyState={{
          title: "연결된 파일이 없습니다.",
          description: "이미지·첨부가 적재되면 object key와 함께 표시됩니다.",
        }}
        getRowId={(row) => row.file_id}
        manualSorting={false}
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
            <CellStack
              primary={
                <Link
                  className="rounded-control font-medium text-brand underline-offset-4 outline-none hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  href={featureHref(item.feature_id)}
                  onClick={(event) => event.stopPropagation()}
                >
                  {item.name}
                </Link>
              }
              secondary={shortId(item.feature_id, 16)}
            />
          );
        },
      },
      {
        id: "kind",
        header: "kind",
        cell: ({ row }) => <Badge variant="neutral">{row.original.kind}</Badge>,
      },
      {
        accessorKey: "distance_m",
        header: "distance",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="tabular-nums">{distanceLabel(row.original.distance_m)}</span>
        ),
      },
    ],
    [],
  );

  return (
    <Section count={items.length} title="Nearby">
      {!hasCoord ? (
        <EmptyState
          description="좌표가 있어야 반경 3 km 안의 feature를 찾을 수 있습니다."
          size="sm"
          title="좌표가 없습니다."
        />
      ) : nearby.isError ? (
        <Alert variant="destructive">
          <AlertTitle>nearby 호출 실패</AlertTitle>
          <AlertDescription>{nearby.error.message}</AlertDescription>
          <AlertActions>
            <Button
              loading={nearby.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => void nearby.refetch()}
            >
              다시 시도
            </Button>
          </AlertActions>
        </Alert>
      ) : (
        <DataTable
          columns={columns}
          data={items}
          emptyState={{
            title: "주변 feature가 없습니다.",
            description: "반경 3 km 안에 다른 feature가 없습니다.",
          }}
          getRowId={(row) => row.feature_id}
          isLoading={nearby.isLoading}
          manualSorting={false}
          skeletonRowCount={4}
        />
      )}
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
    <Section title="Map">
      {hasCoord ? (
        <div className="relative h-64 overflow-hidden rounded-panel border border-border bg-surface-subtle">
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
              markerColor={DETAIL_MARKER_COLOR}
              selected
              title={feature.name}
            />
          </VWorldMapView>
        </div>
      ) : (
        <EmptyState
          description="주소나 좌표를 보정하면 지도에 표시됩니다."
          size="sm"
          title="좌표가 없어 지도 marker를 표시할 수 없습니다."
        />
      )}
    </Section>
  );
}

function RawDisclosure({
  label,
  value,
  defaultOpen = false,
}: {
  label: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  return (
    <details className="group/details" open={defaultOpen}>
      <summary className="inline-flex h-control-sm cursor-pointer list-none items-center gap-1 rounded-control text-xs font-medium text-text-secondary outline-none select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        <span className="font-mono font-normal slashed-zero">{label}</span>
      </summary>
      <div className="pt-1">
        <JsonViewer copyable maxHeight="md" value={value} />
      </div>
    </details>
  );
}

function RawPanels({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section title="Raw">
      <div className="flex flex-col gap-2">
        <RawDisclosure defaultOpen label="detail" value={data.feature.detail} />
        <RawDisclosure label="raw_refs" value={data.feature.raw_refs} />
        <RawDisclosure label="urls" value={data.feature.urls} />
        <RawDisclosure label="address" value={data.feature.address} />
      </div>
    </Section>
  );
}

// 상태 전이 감사 컬럼 — 상태/핸들러 의존이 없어 모듈 상수로 둔다(컴포넌트 크기 분리).
const TRANSITION_COLUMNS: ColumnDef<StateTransitionRow, unknown>[] = [
  {
    id: "transition",
    header: "전이",
    cell: ({ row }) => (
      <CellStack
        primary={row.original.transition_kind}
        secondary={`#${row.original.transition_id}`}
      />
    ),
  },
  {
    id: "states",
    header: "상태 축",
    cell: ({ row }) => (
      <div className="flex flex-col gap-0.5 font-mono text-2xs slashed-zero">
        <span className="text-text-secondary">
          {row.original.from_lifecycle_state ?? NULL_GLYPH} /{" "}
          {row.original.from_publication_state ?? NULL_GLYPH} /{" "}
          {row.original.from_quality_state ?? NULL_GLYPH}
        </span>
        <span>
          → {row.original.to_lifecycle_state} /{" "}
          {row.original.to_publication_state} /{" "}
          {row.original.to_quality_state}
        </span>
      </div>
    ),
  },
  {
    id: "receipt",
    header: "감사",
    cell: ({ row }) => (
      <div className="flex flex-col gap-0.5 text-xs">
        <span className="font-mono slashed-zero">{row.original.reason_code}</span>
        <span className="text-text-secondary">
          {row.original.principal} · r{row.original.row_revision}
        </span>
        <span className="text-text-secondary">
          {formatDateTime(row.original.occurred_at)}
        </span>
      </div>
    ),
  },
];

/**
 * 종료된 feature를 현재 source 기준으로 재활성화하는 입력 묶음 — 세 입력이 모두 있어야 활성.
 * FeatureStatePanel에서 분리(컴포넌트 크기 분리); mutation 객체는 부모가 소유해 오류를 한 곳에 모은다.
 */
function ReactivateSection({
  basis,
  reactivate,
  reasonCode,
}: {
  basis: ReturnType<typeof useAdminFeatureCorrectionBasis>;
  reactivate: ReturnType<typeof useReactivateAdminFeatureStateMutation>;
  reasonCode: string;
}) {
  const [providerDatasetId, setProviderDatasetId] = useState("");
  const [sourceEntityKey, setSourceEntityKey] = useState("");
  const [sourceRecordKey, setSourceRecordKey] = useState("");

  const parsedDatasetId = Number(providerDatasetId);
  const reactivateReady =
    Number.isSafeInteger(parsedDatasetId) &&
    parsedDatasetId >= 1 &&
    sourceEntityKey.trim().length > 0 &&
    sourceRecordKey.trim().length > 0;

  const submitReactivate = () => {
    if (!basis.data || !reactivateReady) {
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

  const reactivateDisabledReason = basis.isLoading
    ? "상태 기준(entity tag)을 불러오는 중입니다"
    : !reactivateReady
      ? "provider dataset ID·source entity key·source record key를 모두 입력하세요"
      : undefined;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4">
      <p className="text-xs font-medium text-text-primary">현재 source로 재활성화</p>
      <div className="grid gap-x-3 gap-y-1 md:grid-cols-3">
        <FormField
          aria-label="재활성 provider dataset ID"
          inputMode="numeric"
          label="provider dataset ID"
          min={1}
          placeholder="예: 703"
          reserveMessage={false}
          size="sm"
          value={providerDatasetId}
          onChange={(event) => setProviderDatasetId(event.target.value)}
        />
        <FormField
          aria-label="재활성 source entity key"
          label="source entity key"
          placeholder="provider::dataset::entity"
          reserveMessage={false}
          size="sm"
          value={sourceEntityKey}
          onChange={(event) => setSourceEntityKey(event.target.value)}
        />
        <FormField
          aria-label="재활성 source record key"
          label="source record key"
          placeholder="provider::dataset::record"
          reserveMessage={false}
          size="sm"
          value={sourceRecordKey}
          onChange={(event) => setSourceRecordKey(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <div>
          <Button
            disabled={basis.isLoading || !reactivateReady}
            disabledReason={reactivateDisabledReason}
            loading={reactivate.isPending}
            size="sm"
            type="button"
            variant="outline"
            onClick={submitReactivate}
          >
            현재 source로 재활성화
          </Button>
        </div>
        <p className="min-h-[1lh] text-2xs text-text-secondary">
          {reactivateDisabledReason ?? "입력한 source 기준으로 수명 상태를 운영으로 되돌립니다."}
        </p>
      </div>
    </div>
  );
}

function FeatureStatePanel({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"];
}) {
  const confirm = useConfirm();
  const basis = useAdminFeatureCorrectionBasis(feature.feature_id);
  const transitions = useAdminFeatureStateTransitions(feature.feature_id);
  const patchState = usePatchAdminFeatureStateMutation();
  const reactivate = useReactivateAdminFeatureStateMutation();
  const [publicationState, setPublicationState] = useState(
    feature.publication_state,
  );
  const [qualityState, setQualityState] = useState(feature.quality_state);
  const [reasonCode, setReasonCode] = useState("admin_ui_state_patch");

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

  const publicationChanged = publicationState !== feature.publication_state;
  const qualityChanged = qualityState !== feature.quality_state;
  const hasStateChange = publicationChanged || qualityChanged;
  const isRetired = feature.lifecycle_state === "retired";

  const submitPatch = () => {
    if (!basis.data) return;
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

  const retire = async () => {
    if (!basis.data || isRetired) return;
    const ok = await confirm({
      title: `${feature.name} feature를 종료할까요?`,
      description:
        "수명 상태가 종료로 바뀌고 공개가 비공개로 잠깁니다. 이후에는 현재 source로만 재활성화할 수 있습니다.",
      confirmLabel: "종료",
      destructive: true,
    });
    if (!ok) return;
    patchState.mutate({
      featureId: basis.data.featureId,
      entityTag: basis.data.entityTag,
      body: {
        action: "retire",
        reason_code: reasonCode.trim() || "admin_ui_retire",
      },
    });
  };

  const transitionRows = transitions.data?.data.items ?? [];

  const commandError =
    basis.error?.message ?? patchState.error?.message ?? reactivate.error?.message;
  const applyDisabledReason = basis.isLoading
    ? "상태 기준(entity tag)을 불러오는 중입니다"
    : !hasStateChange
      ? "공개 또는 품질 상태를 바꾸면 적용할 수 있습니다"
      : undefined;
  const retireDisabledReason = basis.isLoading
    ? "상태 기준(entity tag)을 불러오는 중입니다"
    : isRetired
      ? "이미 종료된 feature입니다"
      : undefined;

  return (
    <Section count={transitionRows.length} title="상태 축과 감사 이력">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-1">
          <FeatureStateBadges
            lifecycleState={feature.lifecycle_state}
            publicationState={feature.publication_state}
            qualityState={feature.quality_state}
          />
        </div>
        <div className="grid gap-x-3 gap-y-1 md:grid-cols-3">
          <FormSelect
            aria-label="공개 상태 변경"
            label="공개 상태"
            reserveMessage={false}
            size="sm"
            value={publicationState}
            onChange={(event) =>
              setPublicationState(
                event.target.value as typeof feature.publication_state,
              )
            }
          >
            {allowedPublicationStates(feature.lifecycle_state).map((state) => (
              <NativeSelectOption key={state} value={state}>
                {featureStateLabel("publication", state)}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormSelect
            aria-label="품질 상태 변경"
            label="품질 상태"
            reserveMessage={false}
            size="sm"
            value={qualityState}
            onChange={(event) =>
              setQualityState(
                event.target.value as typeof feature.quality_state,
              )
            }
          >
            {FEATURE_QUALITY_STATES.map((state) => (
              <NativeSelectOption key={state} value={state}>
                {featureStateLabel("quality", state)}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormField
            aria-label="상태 변경 사유 코드"
            label="사유 코드"
            reserveMessage={false}
            size="sm"
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={basis.isLoading || !hasStateChange}
              disabledReason={applyDisabledReason}
              loading={patchState.isPending}
              size="sm"
              type="button"
              variant="outline"
              onClick={submitPatch}
            >
              공개·품질 적용
            </Button>
            <Button
              disabled={basis.isLoading || isRetired}
              disabledReason={retireDisabledReason}
              loading={patchState.isPending}
              size="sm"
              type="button"
              variant="destructive"
              onClick={() => void retire()}
            >
              종료
            </Button>
          </div>
          <p className="min-h-[1lh] text-2xs text-text-secondary">
            {applyDisabledReason ?? retireDisabledReason ?? "종료는 확인 후 실행됩니다."}
          </p>
        </div>
        {isRetired ? (
          <ReactivateSection basis={basis} reactivate={reactivate} reasonCode={reasonCode} />
        ) : null}
        {commandError ? (
          <Alert variant="destructive">
            <AlertTitle>상태 명령을 적용하지 못했습니다</AlertTitle>
            <AlertDescription>
              {commandError} — 값을 확인한 뒤 다시 시도하세요.
            </AlertDescription>
          </Alert>
        ) : null}
        {transitions.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상태 감사 이력을 불러오지 못했습니다</AlertTitle>
            <AlertDescription>{transitions.error.message}</AlertDescription>
            <AlertActions>
              <Button
                loading={transitions.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void transitions.refetch()}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : (
          <DataTable
            columns={TRANSITION_COLUMNS}
            data={transitionRows}
            emptyState={{
              title: "상태 전이 이력이 없습니다.",
              description: "공개·품질·수명 상태를 바꾸면 감사 이력이 여기에 남습니다.",
            }}
            getRowId={(row) => String(row.transition_id)}
            isLoading={transitions.isLoading}
            manualSorting={false}
            skeletonRowCount={3}
          />
        )}
      </div>
    </Section>
  );
}

function FeatureDetailSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 border-b border-border pb-5">
        <div className="flex gap-1">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-20" />
        </div>
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-4 w-96" />
      </div>
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
        <div className="flex flex-col gap-6">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
        <div className="flex flex-col gap-6">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    </div>
  );
}

export function FeatureDetailView({ featureId }: { featureId: string }) {
  const detail = useAdminFeatureDetail(featureId);
  const data = detail.data?.data;
  const feature = data?.feature;

  if (detail.isLoading) {
    return <FeatureDetailSkeleton />;
  }

  if (detail.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>feature 상세 조회 실패</AlertTitle>
        <AlertDescription>
          {detail.error.message} — feature ID를 확인하거나 잠시 후 다시 시도하세요.
        </AlertDescription>
        <AlertActions>
          <Button
            loading={detail.isFetching}
            size="sm"
            type="button"
            variant="outline"
            onClick={() => void detail.refetch()}
          >
            다시 시도
          </Button>
          <Link
            className="rounded-control text-xs text-brand underline-offset-4 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            href="/admin/features"
          >
            Feature 목록으로
          </Link>
        </AlertActions>
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
    <div className="flex flex-col gap-6" data-testid="feature-detail-view">
      {/* 식별 밴드: 상태 배지 → 이름(h2) → ID(mono + 복사). 프레임 없이 hairline만(M7/M31). */}
      <header className="flex flex-col gap-3 border-b border-border pb-5">
        <div className="flex flex-wrap gap-1">
          <FeatureStateBadges
            lifecycleState={feature.lifecycle_state}
            publicationState={feature.publication_state}
            qualityState={feature.quality_state}
          />
          <Badge variant="neutral">{feature.kind}</Badge>
          <Badge variant="outline">{feature.category}</Badge>
        </div>
        <div className="flex flex-col gap-1">
          <h2 className="text-lg leading-tight font-semibold break-keep text-text-primary">
            {feature.name}
          </h2>
          <div className="flex items-center gap-1 font-mono text-xs break-all text-text-secondary slashed-zero">
            <span>{feature.feature_id}</span>
            <CopyButton label="feature ID" value={feature.feature_id} />
          </div>
        </div>
      </header>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
        <div className="flex min-w-0 flex-col divide-y divide-border [&>section]:py-6 [&>section:first-child]:pt-0 [&>section:last-child]:pb-0">
          <SourcesTable data={data} />
          <CurationsTable data={data} />
          <NoticeHistoryPanel data={data} />
          <IssuesTable data={data} />
          <OverridesTable data={data} />
          <FeatureStatePanel feature={feature} />
          <FilesTable data={data} />
        </div>
        <aside className="flex min-w-0 flex-col divide-y divide-border [&>*]:py-6 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
          <DetailList
            items={[
              { label: "coord", value: coordLabel(feature.lon, feature.lat), mono: true },
              { label: "sigungu", value: feature.sigungu_code ?? null, mono: true },
              { label: "updated", value: formatDateTime(feature.updated_at), numeric: true },
              { label: "provider", value: primarySource?.provider ?? null },
            ]}
            layout="inline"
          />
          <FeatureMapPanel feature={feature} />
          <FeatureKindDetailPanel feature={feature} featureId={featureId} />
          <NearbyPanel feature={feature} featureId={featureId} />
          <RawPanels data={data} />
        </aside>
      </div>
    </div>
  );
}
