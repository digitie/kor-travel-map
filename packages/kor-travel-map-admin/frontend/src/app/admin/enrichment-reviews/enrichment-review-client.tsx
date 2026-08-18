"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { CheckIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { type Map as MapLibreMap } from "maplibre-gl";
import {
  useCallback,
  useDeferredValue,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  type EnrichmentDecision,
  type EnrichmentReviewDetailResponse,
  type EnrichmentReviewRecord,
  type EnrichmentStatus,
  useEnrichmentDecisionMutation,
  useEnrichmentReviewDetail,
  useEnrichmentReviews,
} from "@/api/enrichment";
import { AdminShell } from "@/components/admin-shell";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EntityLink } from "@/components/entity-link";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { JsonViewer } from "@/components/json-viewer";
import { MultiFilterCombobox } from "@/components/multi-filter-combobox";
import { uniqueSorted } from "@/lib/string-list";
import { CursorPager } from "@/components/pagination-bar";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { NULL_GLYPH, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

const statuses: Array<EnrichmentStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "ignored",
  "all",
];

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const SCORE_FILTERS = [
  { value: "all", label: "전체" },
  { value: "high", label: "≥ 90", min: 90 },
  { value: "middle", label: "70–90", min: 70, max: 90 },
  { value: "low", label: "< 70", max: 70 },
] as const;
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

type ScoreFilter = (typeof SCORE_FILTERS)[number]["value"];
type MapPoint = [number, number];

function fitMapToPoints(map: MapLibreMap, points: readonly MapPoint[]) {
  if (points.length === 0) return;
  if (points.length === 1) {
    map.easeTo({
      center: points[0],
      zoom: Math.max(map.getZoom(), 15),
      duration: 0,
    });
    return;
  }
  const lons = points.map((point) => point[0]);
  const lats = points.map((point) => point[1]);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  if (minLon === maxLon && minLat === maxLat) {
    map.easeTo({
      center: points[0],
      zoom: Math.max(map.getZoom(), 15),
      duration: 0,
    });
    return;
  }
  map.fitBounds(
    [
      [minLon, minLat],
      [maxLon, maxLat],
    ],
    { duration: 0, maxZoom: 16, padding: 64 },
  );
}

/**
 * 비교 마커 색은 design.md `--compare-a/--compare-b` 토큰을 읽는다(M21). VWorldMarker는 `#hex`
 * 또는 팔레트 코드만 받으므로 canvas fillStyle 직렬화(브라우저 표준: 불투명 색 → `#rrggbb`)로
 * OKLCH → sRGB hex를 얻는다. 해석 실패 시 null → 마커 기본색.
 */
function resolveCssColorHex(variable: string): string | null {
  if (typeof document === "undefined") return null;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  if (!raw) return null;
  if (/^#[0-9a-f]{6}$/i.test(raw)) return raw;
  const context = document.createElement("canvas").getContext("2d");
  if (!context) return null;
  const sentinel = "#000001";
  context.fillStyle = sentinel;
  context.fillStyle = raw;
  const resolved = context.fillStyle;
  return typeof resolved === "string" &&
    /^#[0-9a-f]{6}$/i.test(resolved) &&
    resolved !== sentinel
    ? resolved
    : null;
}

/**
 * 비교 dialog는 사용자 상호작용 뒤 클라이언트에서만 마운트되므로(SSR 마크업 없음) lazy state
 * 초기화로 한 번만 토큰을 읽는다 — effect 안 setState(cascading render)를 피한다.
 */
function useCompareMarkerColors(): { a: string | null; b: string | null } {
  const [colors] = useState<{ a: string | null; b: string | null }>(() => ({
    a: resolveCssColorHex("--compare-a"),
    b: resolveCssColorHex("--compare-b"),
  }));
  return colors;
}

function scoreBounds(value: ScoreFilter): { min?: number; max?: number } {
  const found = SCORE_FILTERS.find((item) => item.value === value);
  return {
    min: found && "min" in found ? found.min : undefined,
    max: found && "max" in found ? found.max : undefined,
  };
}

function formatScore(value: number | null | undefined): string {
  return typeof value === "number" ? value.toFixed(1) : NULL_GLYPH;
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return NULL_GLYPH;
  if (value >= 1000) return `${(value / 1000).toFixed(2)}km`;
  return `${value.toFixed(1)}m`;
}

function formatDateOnly(value: string | null | undefined): string {
  if (!value) return NULL_GLYPH;
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function formatPeriod(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const left = formatDateOnly(start);
  const right = formatDateOnly(end);
  if (left === NULL_GLYPH && right === NULL_GLYPH) return NULL_GLYPH;
  return `${left} ~ ${right}`;
}

type EnrichmentReviewDetail = EnrichmentReviewDetailResponse["data"];
type EnrichmentDetailSource = EnrichmentReviewDetail["default_detail_source"];

const DETAIL_SOURCE_LABELS: Record<EnrichmentDetailSource, string> = {
  target: "정리된 datagokr",
  visitkorea: "visitkorea",
};

function statusOptionLabel(value: EnrichmentStatus | "all"): string {
  return value === "all" ? "전체" : statusLabel(value);
}

function CompareColumn({
  eyebrow,
  eyebrowClassName,
  heading,
  identity,
  items,
  children,
}: {
  eyebrow: string;
  eyebrowClassName: string;
  heading: string;
  identity: ReactNode;
  items: DetailItem[];
  children?: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <div className={`text-2xs font-medium ${eyebrowClassName}`}>{eyebrow}</div>
        <h3 className="text-md font-semibold break-words text-text-primary">{heading}</h3>
        <div className="font-mono text-xs break-all text-text-secondary">{identity}</div>
      </div>
      <DetailList items={items} layout="inline" />
      {children}
    </section>
  );
}

function EnrichmentDetailDialog({
  detail,
  error,
  isLoading,
  isPending,
  onAccept,
  onClose,
  onSelectDetailSource,
  selectedDetailSource,
}: {
  detail: EnrichmentReviewDetail | undefined;
  error: Error | null;
  isLoading: boolean;
  isPending: boolean;
  onAccept: () => void;
  onClose: () => void;
  onSelectDetailSource: (value: EnrichmentDetailSource) => void;
  selectedDetailSource: EnrichmentDetailSource | null;
}) {
  const target = detail?.target;
  const source = detail?.source;
  const markerColors = useCompareMarkerColors();
  const hasMap =
    typeof target?.lon === "number" &&
    typeof target.lat === "number" &&
    typeof detail?.source_lon === "number" &&
    typeof detail.source_lat === "number";
  const acceptBlockedReason =
    detail && detail.status !== "pending" ? "이미 결정된 리뷰입니다." : null;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        aria-label="enrichment review detail"
        className="max-w-6xl"
      >
        <DialogHeader>
          <div className="flex min-w-0 flex-col gap-0.5">
            <DialogTitle>보강 상세 비교</DialogTitle>
            <DialogDescription>
              {detail ? (
                <span className="tabular-nums">
                  <span className="font-mono">{shortId(detail.review_id)}</span> ·{" "}
                  {formatDistance(detail.distance_m)}
                </span>
              ) : (
                NULL_GLYPH
              )}
            </DialogDescription>
          </div>
          <Button size="sm" type="button" variant="ghost" onClick={onClose}>
            닫기
          </Button>
        </DialogHeader>
        <div className="flex flex-col gap-6 p-4">
          {isLoading ? (
            <div className="flex flex-col gap-3" aria-busy="true">
              <Skeleton className="h-control w-full" />
              <Skeleton className="h-80 w-full" />
              <div className="grid gap-4 lg:grid-cols-2">
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-40 w-full" />
              </div>
            </div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertTitle>상세를 불러오지 못했습니다</AlertTitle>
              <AlertDescription>{error.message}</AlertDescription>
              <AlertActions>
                <Button size="sm" type="button" variant="outline" onClick={onClose}>
                  닫기
                </Button>
              </AlertActions>
            </Alert>
          ) : detail && target && source ? (
            <>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <StatStrip
                  ariaLabel="보강 점수"
                  className="flex-1"
                  items={[
                    { label: "이름 점수", value: formatScore(detail.name_score) },
                    { label: "거리 점수", value: formatScore(detail.spatial_score) },
                    { label: "거리", value: formatDistance(detail.distance_m) },
                    {
                      label: "감사 기본 소스",
                      value: DETAIL_SOURCE_LABELS[detail.default_detail_source],
                    },
                  ]}
                />
                <div className="flex flex-wrap items-end gap-2">
                  <FilterField
                    hint={
                      <span id="enrichment-detail-source-note">
                        선택값은 accept 적용 데이터 변경 없이 decision reason에 기록됩니다.
                      </span>
                    }
                    label="기록 소스"
                  >
                    <NativeSelect
                      aria-describedby="enrichment-detail-source-note"
                      aria-label="enrichment detail source audit note"
                      value={selectedDetailSource ?? detail.default_detail_source}
                      onChange={(event) =>
                        onSelectDetailSource(
                          event.target.value as EnrichmentDetailSource,
                        )
                      }
                    >
                      <NativeSelectOption
                        disabled={!detail.target_detail_available}
                        value="target"
                      >
                        기록: {DETAIL_SOURCE_LABELS.target}
                      </NativeSelectOption>
                      <NativeSelectOption value="visitkorea">
                        기록: {DETAIL_SOURCE_LABELS.visitkorea}
                      </NativeSelectOption>
                    </NativeSelect>
                  </FilterField>
                  <div className="flex flex-col gap-1 pb-5.5">
                    <Button
                      disabled={acceptBlockedReason !== null || isPending}
                      disabledReason={acceptBlockedReason ?? "다른 결정을 처리하는 중입니다"}
                      loading={isPending}
                      type="button"
                      variant="default"
                      onClick={onAccept}
                    >
                      <CheckIcon data-icon="inline-start" />
                      accept
                    </Button>
                  </div>
                </div>
              </div>
              {hasMap ? (
                <section className="flex flex-col gap-2 border-t border-border pt-4">
                  <div className="flex flex-wrap items-center gap-3 text-2xs font-medium text-text-secondary">
                    <span>위치 비교</span>
                    <span className="flex items-center gap-1">
                      <span aria-hidden="true" className="size-2 rounded-full bg-compare-a" />
                      datagokr
                    </span>
                    <span className="flex items-center gap-1">
                      <span aria-hidden="true" className="size-2 rounded-full bg-compare-b" />
                      visitkorea
                    </span>
                  </div>
                  <div className="relative h-80 min-h-72 overflow-hidden rounded-control border border-border">
                    <VWorldMapView
                      apiKey={VWORLD_KEY}
                      center={[
                        ((target.lon ?? 0) + (detail.source_lon ?? 0)) / 2,
                        ((target.lat ?? 0) + (detail.source_lat ?? 0)) / 2,
                      ]}
                      className="absolute inset-0 h-full w-full"
                      key={detail.review_id}
                      navigation
                      onLoad={(map) =>
                        fitMapToPoints(map, [
                          [target.lon ?? 0, target.lat ?? 0],
                          [detail.source_lon ?? 0, detail.source_lat ?? 0],
                        ])
                      }
                      scale
                      testId="enrichment-detail-map"
                      zoom={14}
                    >
                      <VWorldMarker
                        lngLat={[target.lon ?? 0, target.lat ?? 0]}
                        markerColor={markerColors.a}
                        selected
                        title={`datagokr: ${target.name}`}
                      />
                      <VWorldMarker
                        lngLat={[
                          detail.source_lon ?? 0,
                          detail.source_lat ?? 0,
                        ]}
                        markerColor={markerColors.b}
                        title={`visitkorea: ${detail.source_name}`}
                      />
                    </VWorldMapView>
                  </div>
                </section>
              ) : null}
              <div className="grid gap-6 border-t border-border pt-4 lg:grid-cols-2 lg:gap-8 lg:divide-x lg:divide-border lg:[&>*:last-child]:pl-8">
                <CompareColumn
                  eyebrow="1차 datagokr"
                  eyebrowClassName="text-compare-a"
                  heading={target.name}
                  identity={
                    <EntityLink
                      className="text-xs"
                      id={target.feature_id}
                      kind="feature"
                      newTab
                    />
                  }
                  items={[
                    { label: "종류", value: target.kind },
                    { label: "카테고리", value: target.category },
                    {
                      label: "기간",
                      value: formatPeriod(detail.target_start_date, detail.target_end_date),
                    },
                    {
                      label: "상태 축",
                      value: (
                        <FeatureStateBadges
                          lifecycleState={target.lifecycle_state}
                          publicationState={target.publication_state}
                          qualityState={target.quality_state}
                        />
                      ),
                    },
                    { label: "경도", value: target.lon?.toFixed(6) ?? null, mono: true },
                    { label: "위도", value: target.lat?.toFixed(6) ?? null, mono: true },
                  ]}
                >
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                      <span className="text-2xs font-medium text-text-secondary">detail</span>
                      <JsonViewer aria-label="target detail" copyable value={target.detail ?? {}} />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-2xs font-medium text-text-secondary">address</span>
                      <JsonViewer aria-label="target address" copyable value={target.address ?? {}} />
                    </div>
                  </div>
                </CompareColumn>
                <CompareColumn
                  eyebrow="2차 visitkorea"
                  eyebrowClassName="text-compare-b"
                  heading={detail.source_name}
                  identity={
                    <>
                      {source.provider} · {source.source_entity_id}
                    </>
                  }
                  items={[
                    { label: "데이터셋", value: source.dataset_key, mono: true },
                    {
                      label: "기간",
                      value: formatPeriod(detail.source_start_date, detail.source_end_date),
                    },
                    { label: "경도", value: detail.source_lon?.toFixed(6) ?? null, mono: true },
                    { label: "위도", value: detail.source_lat?.toFixed(6) ?? null, mono: true },
                    { label: "레코드", value: source.source_record_key, mono: true },
                  ]}
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-2xs font-medium text-text-secondary">raw_data</span>
                    <JsonViewer aria-label="source raw data" copyable value={source.raw_data ?? {}} />
                  </div>
                </CompareColumn>
              </div>
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function EnrichmentReviewTable({
  detailReviewId,
  isLoading,
  isPending,
  items,
  pendingReviewId,
  onDecide,
  onOpenDetail,
}: {
  detailReviewId: string | null;
  isLoading: boolean;
  isPending: boolean;
  items: EnrichmentReviewRecord[];
  pendingReviewId: string | null;
  onDecide: (reviewId: string, decision: EnrichmentDecision) => void;
  onOpenDetail: (reviewId: string) => void;
}) {
  const columns = useMemo<ColumnDef<EnrichmentReviewRecord, unknown>[]>(
    () => [
      {
        id: "review",
        header: "리뷰",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.review_id)}
          </span>
        ),
      },
      {
        accessorKey: "name_score",
        header: "점수",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5 text-xs text-text-secondary tabular-nums">
            <div>name {formatScore(row.original.name_score)}</div>
            <div>distance {formatScore(row.original.spatial_score)}</div>
          </div>
        ),
      },
      {
        accessorKey: "distance_m",
        header: "거리",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatDistance(row.original.distance_m),
      },
      {
        id: "target",
        header: "1차 (datagokr)",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.target_name}</div>
            <div className="text-xs text-text-secondary">
              {row.original.target_category ?? NULL_GLYPH} ·{" "}
              <span onClick={(event) => event.stopPropagation()}>
                <EntityLink
                  className="text-xs"
                  id={row.original.target_feature_id}
                  kind="feature"
                  newTab
                >
                  {shortId(row.original.target_feature_id)}
                </EntityLink>
              </span>
            </div>
            <div className="text-xs text-text-secondary tabular-nums">
              {formatPeriod(
                row.original.target_start_date,
                row.original.target_end_date,
              )}
            </div>
          </>
        ),
      },
      {
        id: "source",
        header: "2차 (visitkorea)",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.source_name}</div>
            <div className="text-xs text-text-secondary">
              {row.original.source_provider} · {row.original.source_entity_id}
            </div>
            <div className="text-xs text-text-secondary tabular-nums">
              {formatPeriod(
                row.original.source_start_date,
                row.original.source_end_date,
              )}
            </div>
          </>
        ),
      },
      {
        accessorKey: "status",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "created_at",
        header: "생성",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const item = row.original;
          if (item.status !== "pending") {
            return <span className="text-xs text-text-secondary">완료</span>;
          }
          const busy = isPending && pendingReviewId === item.review_id;
          const otherBusy = isPending && !busy;
          const reason = otherBusy ? "다른 결정을 처리하는 중입니다" : undefined;
          return (
            <div
              className="flex flex-wrap gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <Button
                disabled={isPending}
                disabledReason={reason}
                loading={busy}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => onDecide(item.review_id, "accepted")}
              >
                <CheckIcon data-icon="inline-start" />
                accept
              </Button>
              <Button
                disabled={isPending}
                disabledReason={reason}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => onDecide(item.review_id, "rejected")}
              >
                <XIcon data-icon="inline-start" />
                reject
              </Button>
              <Button
                disabled={isPending}
                disabledReason={reason}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => onDecide(item.review_id, "ignored")}
              >
                ignore
              </Button>
            </div>
          );
        },
      },
    ],
    [isPending, onDecide, pendingReviewId],
  );

  return (
    <DataTable
      columns={columns}
      data={items}
      getRowId={(row) => row.review_id}
      isLoading={isLoading}
      emptyState={{
        title: "enrichment review가 없습니다.",
        description: "상태 필터를 전체로 바꾸거나 점수·provider 조건을 넓혀 보세요.",
      }}
      onRowClick={(row) => onOpenDetail(row.review_id)}
      isRowActive={(row) => row.review_id === detailReviewId}
    />
  );
}

export function EnrichmentReviewClient() {
  const [q, setQ] = useState("");
  const [providers, setProviders] = useState<string[]>([]);
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [status, setStatus] = useState<EnrichmentStatus | "all">("pending");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [pageIndex, setPageIndex] = useState(1);
  const [cursor, setCursor] = useState<string | null>(null);
  const [detailReviewId, setDetailReviewId] = useState<string | null>(null);
  const [selectedDetailSource, setSelectedDetailSource] =
    useState<EnrichmentDetailSource | null>(null);
  const deferredQ = useDeferredValue(q.trim());
  const deferredProviders = useDeferredValue(providers);
  const bounds = scoreBounds(scoreFilter);
  const reviewParams = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      provider: deferredProviders.length > 0 ? deferredProviders : undefined,
      min_score: bounds.min,
      max_score: bounds.max,
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
    }),
    [
      bounds.max,
      bounds.min,
      cursor,
      deferredProviders,
      deferredQ,
      pageSize,
      status,
    ],
  );
  const reviews = useEnrichmentReviews(reviewParams);
  const detail = useEnrichmentReviewDetail(detailReviewId);
  const decision = useEnrichmentDecisionMutation();

  const items = useMemo(
    () => reviews.data?.data.items ?? [],
    [reviews.data?.data.items],
  );
  const providerOptions = useMemo(
    () =>
      uniqueSorted([
        ...providers,
        ...items.map((item) => item.source_provider),
      ]),
    [items, providers],
  );
  const totalItems = reviews.data?.meta.page?.total ?? null;
  const nextCursor = reviews.data?.meta.page?.next_cursor ?? null;

  const resetPage = () => {
    setCursor(null); // 필터 바뀌면 1페이지로.
    setPageIndex(1);
    setDetailReviewId(null);
    setSelectedDetailSource(null);
  };
  const changeStatus = (value: EnrichmentStatus | "all") => {
    setStatus(value);
    resetPage();
  };
  // keyset 페이지 이동 시 상세/소스 선택을 함께 초기화한다.
  const goFirstPage = () => {
    resetPage();
  };
  const goNextPage = () => {
    if (!nextCursor) return;
    setCursor(nextCursor);
    setPageIndex((page) => page + 1);
    setDetailReviewId(null);
    setSelectedDetailSource(null);
  };

  const decide = useCallback(
    (
      reviewId: string,
      value: EnrichmentDecision,
      detailSource?: EnrichmentDetailSource | null,
    ) => {
      decision.mutate({
        reviewKey: reviewId,
        body: {
          decision: value,
          decision_reason: `admin-ui ${value}`,
          selected_detail_source: detailSource ?? undefined,
        },
      });
    },
    [decision],
  );

  const openDetail = useCallback((reviewId: string) => {
    setDetailReviewId(reviewId);
    setSelectedDetailSource(null);
  }, []);

  const renderPagination = (placement: "top" | "bottom") => (
    <CursorPager
      hasNext={Boolean(nextCursor)}
      isFetching={reviews.isFetching}
      isFirst={cursor === null}
      placement={placement}
      summary={
        <>
          page {pageIndex.toLocaleString("ko-KR")}
          {totalItems !== null ? (
            <> · 총 {totalItems.toLocaleString("ko-KR")}건</>
          ) : null}{" "}
          · 이 페이지 {items.length.toLocaleString("ko-KR")}개
        </>
      }
      onFirst={goFirstPage}
      onNext={goNextPage}
    />
  );
  const errorLines = [
    reviews.error ? `목록: ${reviews.error.message}` : null,
    decision.error ? `결정: ${decision.error.message}` : null,
  ].filter((line): line is string => line !== null);
  return (
    <AdminShell
      actions={
        <Button
          loading={reviews.isFetching}
          type="button"
          variant="outline"
          onClick={() => void reviews.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="축제 enrichment 후보를 검토해 연결하거나 거절합니다."
      title="보강 검토"
    >
      <div className="flex flex-col gap-4">
        {errorLines.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>enrichment review 처리 실패</AlertTitle>
            <AlertDescription>
              {errorLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
              <p>잠시 후 다시 시도하세요.</p>
            </AlertDescription>
            <AlertActions>
              <Button
                loading={reviews.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => {
                  decision.reset();
                  void reviews.refetch();
                }}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        {detailReviewId ? (
          <EnrichmentDetailDialog
            detail={detail.data?.data}
            error={detail.error ?? null}
            isLoading={detail.isLoading}
            isPending={decision.isPending}
            selectedDetailSource={selectedDetailSource}
            onAccept={() =>
              decide(
                detailReviewId,
                "accepted",
                selectedDetailSource ??
                  detail.data?.data.default_detail_source ??
                  "visitkorea",
              )
            }
            onClose={() => {
              setDetailReviewId(null);
              setSelectedDetailSource(null);
            }}
            onSelectDetailSource={setSelectedDetailSource}
          />
        ) : null}

        <FilterBar>
          <FilterField className="w-64" label="검색">
            <Input
              aria-label="enrichment search"
              placeholder="review, target, source"
              value={q}
              onChange={(event) => {
                setQ(event.target.value);
                resetPage();
              }}
            />
          </FilterField>
          <FilterField label="상태">
            <NativeSelect
              aria-label="enrichment status"
              value={status}
              onChange={(event) =>
                changeStatus(event.target.value as EnrichmentStatus | "all")
              }
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {statusOptionLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <div className="flex w-56 min-w-0 flex-col gap-1" data-slot="filter-field">
            <span className="text-2xs leading-none font-medium text-text-secondary">
              소스 provider
            </span>
            <MultiFilterCombobox
              ariaLabel="enrichment provider"
              className="w-full"
              options={providerOptions}
              placeholder="소스 provider"
              values={providers}
              onChange={(values) => {
                setProviders(values);
                resetPage();
              }}
            />
          </div>
          <FilterField label="점수">
            <NativeSelect
              aria-label="enrichment score filter"
              value={scoreFilter}
              onChange={(event) => {
                setScoreFilter(event.target.value as ScoreFilter);
                resetPage();
              }}
            >
              {SCORE_FILTERS.map((item) => (
                <NativeSelectOption key={item.value} value={item.value}>
                  {item.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="페이지 크기">
            <NativeSelect
              aria-label="enrichment page size"
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value) as typeof pageSize);
                resetPage();
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
        </FilterBar>

        {renderPagination("top")}

        <EnrichmentReviewTable
          detailReviewId={detailReviewId}
          isLoading={reviews.isLoading}
          isPending={decision.isPending}
          items={items}
          pendingReviewId={decision.isPending ? (decision.variables?.reviewKey ?? null) : null}
          onDecide={decide}
          onOpenDetail={openDetail}
        />

        {renderPagination("bottom")}
      </div>
    </AdminShell>
  );
}
