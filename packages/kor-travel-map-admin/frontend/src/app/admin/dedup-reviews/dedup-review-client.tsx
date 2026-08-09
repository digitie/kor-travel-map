"use client";

import {
  type ColumnDef,
  type Row,
  type RowSelectionState,
} from "@tanstack/react-table";
import {
  CheckIcon,
  EyeIcon,
  MergeIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { type Map as MapLibreMap } from "maplibre-gl";
import { useCallback, useDeferredValue, useMemo, useReducer } from "react";

import {
  type DedupDecision,
  type DedupFeatureRecord,
  type DedupReviewDetailResponse,
  type DedupReviewRecord,
  type DedupStatus,
  useDedupDecisionMutation,
  useDedupReviewDetail,
  useDedupReviews,
} from "@/api/dedup";
import { AdminShell } from "@/components/admin-shell";
import { EntityLink } from "@/components/entity-link";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { MultiFilterCombobox } from "@/components/multi-filter-combobox";
import { uniqueSorted } from "@/lib/string-list";
import { CursorPager } from "@/components/pagination-bar";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
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
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<DedupStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "merged",
  "ignored",
  "all",
];
const DEDUP_KINDS = [
  "place",
  "event",
  "notice",
  "price",
  "weather",
  "route",
  "area",
] as const;
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const SCORE_FILTERS = [
  { value: "all", label: "score all" },
  { value: "high", label: "score >= 90", min: 90 },
  { value: "middle", label: "score 70-90", min: 70, max: 90 },
  { value: "low", label: "score < 70", max: 70 },
] as const;

type DedupKindFilter = (typeof DEDUP_KINDS)[number] | "all";
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

function scoreBounds(value: ScoreFilter): { min?: number; max?: number } {
  const found = SCORE_FILTERS.find((item) => item.value === value);
  return {
    min: found && "min" in found ? found.min : undefined,
    max: found && "max" in found ? found.max : undefined,
  };
}

function formatScore(value: number): string {
  return value.toFixed(1);
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}km`;
  return `${value.toFixed(1)}m`;
}

/**
 * master 자동 선정 추천(`core.scoring.select_master` 1순위 = 좌표 보유)의 클라이언트
 * 힌트. backend가 좌표→updated_at→provider 우선순위로 최종 결정하므로 여기서는 운영자
 * 판단을 돕는 좌표 보유 여부만 노출한다.
 */
function hasCoord(feature: DedupFeatureRecord): boolean {
  return typeof feature.lon === "number" && typeof feature.lat === "number";
}

type DedupReviewDetail = DedupReviewDetailResponse["data"];
type DetailFeature = DedupReviewDetail["feature_a"];

function formatMaybe(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  return JSON.stringify(value);
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-52 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function DetailMetric({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">{formatMaybe(value)}</dd>
    </div>
  );
}

function FeatureDetailPanel({
  accentClassName,
  feature,
  label,
}: {
  accentClassName: string;
  feature: DetailFeature;
  label: string;
}) {
  const primarySource = feature.sources.find(
    (source) => source.source_role === "primary",
  );
  return (
    <section className="min-w-0 rounded-lg border bg-background p-4">
      <div className="mb-3">
        <div className={`text-xs font-medium ${accentClassName}`}>{label}</div>
        <h3 className="break-words text-base font-semibold">{feature.name}</h3>
        <div className="break-all font-mono text-xs text-muted-foreground">
          <EntityLink
            className="text-xs"
            id={feature.feature_id}
            kind="feature"
            newTab
          />
        </div>
      </div>
      <dl className="grid gap-3 sm:grid-cols-2">
        <DetailMetric label="종류" value={feature.kind} />
        <DetailMetric label="카테고리" value={feature.category} />
        <div>
          <dt className="text-xs text-muted-foreground">상태 축</dt>
          <dd className="mt-1">
            <FeatureStateBadges
              lifecycleState={feature.lifecycle_state}
              publicationState={feature.publication_state}
              qualityState={feature.quality_state}
            />
          </dd>
        </div>
        <DetailMetric label="출처" value={feature.data_origin} />
        <DetailMetric label="경도" value={feature.lon?.toFixed(6)} />
        <DetailMetric label="위도" value={feature.lat?.toFixed(6)} />
        <DetailMetric
          label="primary provider"
          value={primarySource?.provider}
        />
        <DetailMetric
          label="primary entity"
          value={primarySource?.source_entity_id}
        />
      </dl>
      <div className="mt-4 space-y-3">
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            detail
          </div>
          <JsonBlock value={feature.detail} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            address
          </div>
          <JsonBlock value={feature.address} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            sources
          </div>
          <JsonBlock value={feature.sources} />
        </div>
      </div>
    </section>
  );
}

function DedupDetailDialog({
  detail,
  error,
  isLoading,
  onClose,
}: {
  detail: DedupReviewDetail | undefined;
  error: Error | null;
  isLoading: boolean;
  onClose: () => void;
}) {
  const featureA = detail?.feature_a;
  const featureB = detail?.feature_b;
  const hasMap =
    typeof featureA?.lon === "number" &&
    typeof featureA.lat === "number" &&
    typeof featureB?.lon === "number" &&
    typeof featureB.lat === "number";
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent aria-label="dedup review detail" className="max-w-6xl">
        <DialogHeader>
          <div>
            <DialogTitle>중복 상세 비교</DialogTitle>
            <DialogDescription>
              {detail
                ? `${shortId(detail.review_id)} · ${formatDistance(detail.distance_m)}`
                : "loading"}
            </DialogDescription>
          </div>
          <Button size="sm" type="button" variant="ghost" onClick={onClose}>
            닫기
          </Button>
        </DialogHeader>
        <div className="space-y-4 p-4">
          {isLoading ? (
            <div className="text-sm text-muted-foreground">불러오는 중</div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertTitle>상세 조회 실패</AlertTitle>
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : detail && featureA && featureB ? (
            <>
              <div className="flex flex-col gap-3 rounded-lg border bg-muted/40 p-3 lg:flex-row lg:items-center lg:justify-between">
                <dl className="grid flex-1 gap-3 sm:grid-cols-5">
                  <DetailMetric
                    label="total"
                    value={formatScore(detail.total_score)}
                  />
                  <DetailMetric
                    label="이름"
                    value={formatScore(detail.name_score)}
                  />
                  <DetailMetric
                    label="distance score"
                    value={formatScore(detail.spatial_score)}
                  />
                  <DetailMetric
                    label="카테고리"
                    value={formatScore(detail.category_score)}
                  />
                  <DetailMetric
                    label="거리"
                    value={formatDistance(detail.distance_m)}
                  />
                </dl>
              </div>
              {hasMap ? (
                <section className="overflow-hidden rounded-lg border">
                  <div className="border-b px-4 py-2 text-sm font-medium">
                    위치 비교
                  </div>
                  <div className="relative h-80 min-h-72">
                    <VWorldMapView
                      apiKey={VWORLD_KEY}
                      center={[
                        ((featureA.lon ?? 0) + (featureB.lon ?? 0)) / 2,
                        ((featureA.lat ?? 0) + (featureB.lat ?? 0)) / 2,
                      ]}
                      className="absolute inset-0 h-full w-full"
                      key={detail.review_id}
                      navigation
                      onLoad={(map) =>
                        fitMapToPoints(map, [
                          [featureA.lon ?? 0, featureA.lat ?? 0],
                          [featureB.lon ?? 0, featureB.lat ?? 0],
                        ])
                      }
                      scale
                      testId="dedup-detail-map"
                      zoom={14}
                    >
                      <VWorldMarker
                        lngLat={[featureA.lon ?? 0, featureA.lat ?? 0]}
                        markerColor="#2563eb"
                        selected
                        title={`Feature A: ${featureA.name}`}
                      />
                      <VWorldMarker
                        lngLat={[featureB.lon ?? 0, featureB.lat ?? 0]}
                        markerColor="#dc2626"
                        title={`Feature B: ${featureB.name}`}
                      />
                    </VWorldMapView>
                  </div>
                </section>
              ) : null}
              <div className="grid gap-4 lg:grid-cols-2">
                <FeatureDetailPanel
                  accentClassName="text-blue-700"
                  feature={featureA}
                  label="후보 A"
                />
                <FeatureDetailPanel
                  accentClassName="text-red-700"
                  feature={featureB}
                  label="후보 B"
                />
              </div>
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface DedupReviewFilters {
  q: string;
  status: DedupStatus | "all";
  kind: DedupKindFilter;
  providers: string[];
  datasetKeys: string[];
  categories: string[];
  scoreFilter: ScoreFilter;
  pageSize: (typeof PAGE_SIZE_OPTIONS)[number];
}

interface DedupReviewState extends DedupReviewFilters {
  mergeKey: string | null;
  detailReviewId: string | null;
  rowSelection: RowSelectionState;
  pageIndex: number;
  cursor: string | null;
}

type RowSelectionUpdate =
  | RowSelectionState
  | ((previous: RowSelectionState) => RowSelectionState);

type DedupReviewAction =
  | { type: "change-filters"; patch: Partial<DedupReviewFilters> }
  | { type: "first-page" }
  | { type: "next-page"; cursor: string }
  | { type: "open-detail"; reviewId: string }
  | { type: "close-detail" }
  | { type: "select-merge"; reviewId: string | null }
  | { type: "select-rows"; update: RowSelectionUpdate };

const INITIAL_DEDUP_REVIEW_STATE: DedupReviewState = {
  q: "",
  status: "pending",
  kind: "all",
  providers: [],
  datasetKeys: [],
  categories: [],
  scoreFilter: "all",
  pageSize: 100,
  mergeKey: null,
  detailReviewId: null,
  rowSelection: {},
  pageIndex: 1,
  cursor: null,
};

function resetDedupPage(
  state: DedupReviewState,
  patch: Partial<DedupReviewFilters> = {},
): DedupReviewState {
  return {
    ...state,
    ...patch,
    cursor: null,
    pageIndex: 1,
    mergeKey: null,
    detailReviewId: null,
    rowSelection: {},
  };
}

function dedupReviewReducer(
  state: DedupReviewState,
  action: DedupReviewAction,
): DedupReviewState {
  switch (action.type) {
    case "change-filters":
      return resetDedupPage(state, action.patch);
    case "first-page":
      return resetDedupPage(state);
    case "next-page":
      return {
        ...state,
        cursor: action.cursor,
        pageIndex: state.pageIndex + 1,
        mergeKey: null,
        detailReviewId: null,
        rowSelection: {},
      };
    case "open-detail":
      return {
        ...state,
        detailReviewId: action.reviewId,
        mergeKey: null,
      };
    case "close-detail":
      return { ...state, detailReviewId: null };
    case "select-merge":
      return { ...state, mergeKey: action.reviewId };
    case "select-rows":
      return {
        ...state,
        rowSelection:
          typeof action.update === "function"
            ? action.update(state.rowSelection)
            : action.update,
      };
  }
}

function DedupReviewFiltersPanel({
  categoryOptions,
  datasetOptions,
  filters,
  providerOptions,
  onChange,
}: {
  categoryOptions: string[];
  datasetOptions: string[];
  filters: DedupReviewFilters;
  providerOptions: string[];
  onChange: (patch: Partial<DedupReviewFilters>) => void;
}) {
  return (
    <section className="rounded-lg border bg-background p-4">
      <div className="grid gap-3 lg:grid-cols-[minmax(12rem,1fr)_auto_auto_minmax(10rem,14rem)_minmax(10rem,14rem)_minmax(8rem,12rem)_auto_auto]">
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            aria-label="dedup search"
            className="pl-8"
            placeholder="feature id, name"
            value={filters.q}
            onChange={(event) => onChange({ q: event.target.value })}
          />
        </div>
        <NativeSelect
          aria-label="dedup status"
          value={filters.status}
          onChange={(event) =>
            onChange({ status: event.target.value as DedupStatus | "all" })
          }
        >
          {statuses.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {item}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="dedup kind"
          value={filters.kind}
          onChange={(event) =>
            onChange({ kind: event.target.value as DedupKindFilter })
          }
        >
          <NativeSelectOption value="all">all kinds</NativeSelectOption>
          {DEDUP_KINDS.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {item}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <MultiFilterCombobox
          ariaLabel="dedup provider"
          options={providerOptions}
          placeholder="provider"
          values={filters.providers}
          onChange={(providers) => onChange({ providers })}
        />
        <MultiFilterCombobox
          ariaLabel="dedup dataset"
          options={datasetOptions}
          placeholder="dataset"
          values={filters.datasetKeys}
          onChange={(datasetKeys) => onChange({ datasetKeys })}
        />
        <MultiFilterCombobox
          ariaLabel="dedup category"
          options={categoryOptions}
          placeholder="category"
          values={filters.categories}
          onChange={(categories) => onChange({ categories })}
        />
        <NativeSelect
          aria-label="dedup score filter"
          value={filters.scoreFilter}
          onChange={(event) =>
            onChange({ scoreFilter: event.target.value as ScoreFilter })
          }
        >
          {SCORE_FILTERS.map((item) => (
            <NativeSelectOption key={item.value} value={item.value}>
              {item.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <NativeSelect
          aria-label="dedup page size"
          value={String(filters.pageSize)}
          onChange={(event) =>
            onChange({
              pageSize: Number(
                event.target.value,
              ) as DedupReviewFilters["pageSize"],
            })
          }
        >
          {PAGE_SIZE_OPTIONS.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {item}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
    </section>
  );
}

function DedupReviewPager({
  hasNext,
  isFetching,
  isFirst,
  itemCount,
  pageIndex,
  placement,
  totalItems,
  onFirst,
  onNext,
}: {
  hasNext: boolean;
  isFetching: boolean;
  isFirst: boolean;
  itemCount: number;
  pageIndex: number;
  placement: "top" | "bottom";
  totalItems: number | null;
  onFirst: () => void;
  onNext: () => void;
}) {
  return (
    <CursorPager
      ariaPrefix="dedup"
      hasNext={hasNext}
      isFetching={isFetching}
      isFirst={isFirst}
      placement={placement}
      summary={
        <>
          page {pageIndex.toLocaleString("ko-KR")}
          {totalItems !== null ? (
            <> · 총 {totalItems.toLocaleString("ko-KR")}건</>
          ) : null}{" "}
          · 이 페이지 {itemCount.toLocaleString("ko-KR")}개
        </>
      }
      onFirst={onFirst}
      onNext={onNext}
    />
  );
}

function useDedupReviewColumns({
  decisionPending,
  mergeKey,
  onDecide,
  onMerge,
  onOpenDetail,
  onSelectMerge,
}: {
  decisionPending: boolean;
  mergeKey: string | null;
  onDecide: (reviewId: string, decision: DedupDecision) => void;
  onMerge: (reviewId: string, masterFeatureId?: string) => void;
  onOpenDetail: (reviewId: string) => void;
  onSelectMerge: (reviewId: string | null) => void;
}) {
  return useMemo<ColumnDef<DedupReviewRecord, unknown>[]>(
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
        accessorKey: "total_score",
        header: "점수",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="space-y-1 font-mono text-xs">
            <div>total {formatScore(row.original.total_score)}</div>
            <div>name {formatScore(row.original.name_score)}</div>
            <div>distance {formatScore(row.original.spatial_score)}</div>
          </div>
        ),
      },
      {
        accessorKey: "distance_m",
        header: "거리",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">
            {formatDistance(row.original.distance_m)}
          </span>
        ),
      },
      {
        id: "feature_a",
        header: "후보 A",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.feature_a.name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.feature_a.provider ?? "-"} ·{" "}
              {row.original.feature_a.category}
            </div>
          </>
        ),
      },
      {
        id: "feature_b",
        header: "후보 B",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.feature_b.name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.feature_b.provider ?? "-"} ·{" "}
              {row.original.feature_b.category}
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
          <span className="text-muted-foreground">
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
            return (
              <div
                className="flex flex-wrap items-center gap-1"
                onClick={(event) => event.stopPropagation()}
              >
                <Button
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => onOpenDetail(item.review_id)}
                >
                  <EyeIcon data-icon="inline-start" />
                  detail
                </Button>
                <span className="text-sm text-muted-foreground">완료</span>
              </div>
            );
          }
          if (mergeKey === item.review_id) {
            return (
              <div
                className="flex flex-col gap-1"
                onClick={(event) => event.stopPropagation()}
              >
                <span className="text-xs text-muted-foreground">
                  master 선택 (병합 시 나머지는 master로 흡수)
                </span>
                <div className="flex flex-wrap gap-1">
                  <Button
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => onOpenDetail(item.review_id)}
                  >
                    <EyeIcon data-icon="inline-start" />
                    detail
                  </Button>
                  <Button
                    disabled={decisionPending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      onMerge(item.review_id, item.feature_a.feature_id)
                    }
                  >
                    A: {item.feature_a.name}
                    {hasCoord(item.feature_a) ? " · 좌표✓" : ""}
                  </Button>
                  <Button
                    disabled={decisionPending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      onMerge(item.review_id, item.feature_b.feature_id)
                    }
                  >
                    B: {item.feature_b.name}
                    {hasCoord(item.feature_b) ? " · 좌표✓" : ""}
                  </Button>
                  <Button
                    disabled={decisionPending}
                    size="sm"
                    type="button"
                    variant="secondary"
                    onClick={() => onMerge(item.review_id)}
                  >
                    자동 선정
                  </Button>
                  <Button
                    disabled={decisionPending}
                    size="sm"
                    type="button"
                    variant="ghost"
                    onClick={() => onSelectMerge(null)}
                  >
                    취소
                  </Button>
                </div>
              </div>
            );
          }
          return (
            <div
              className="flex flex-wrap gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => onOpenDetail(item.review_id)}
              >
                <EyeIcon data-icon="inline-start" />
                detail
              </Button>
              <Button
                disabled={decisionPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => onDecide(item.review_id, "accepted")}
              >
                <CheckIcon data-icon="inline-start" />
                accept
              </Button>
              <Button
                disabled={decisionPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => onDecide(item.review_id, "rejected")}
              >
                <XIcon data-icon="inline-start" />
                reject
              </Button>
              <Button
                disabled={decisionPending}
                size="sm"
                type="button"
                variant="default"
                onClick={() => onSelectMerge(item.review_id)}
              >
                <MergeIcon data-icon="inline-start" />
                merge
              </Button>
              <Button
                disabled={decisionPending}
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
    [decisionPending, mergeKey, onDecide, onMerge, onOpenDetail, onSelectMerge],
  );
}

function DedupReviewTable({
  columns,
  data,
  detailReviewId,
  decisionPending,
  isLoading,
  rowSelection,
  onDecide,
  onOpenDetail,
  onRowSelectionChange,
}: {
  columns: ColumnDef<DedupReviewRecord, unknown>[];
  data: DedupReviewRecord[];
  detailReviewId: string | null;
  decisionPending: boolean;
  isLoading: boolean;
  rowSelection: RowSelectionState;
  onDecide: (reviewId: string, decision: DedupDecision) => void;
  onOpenDetail: (reviewId: string) => void;
  onRowSelectionChange: (update: RowSelectionUpdate) => void;
}) {
  return (
    <DataTable
      columns={columns}
      data={data}
      getRowId={(row) => row.review_id}
      emptyMessage="dedup review가 없습니다."
      isLoading={isLoading}
      manualSorting={false}
      containerClassName="overflow-auto rounded-lg border bg-background"
      onRowClick={(row) => onOpenDetail(row.review_id)}
      isRowActive={(row) => row.review_id === detailReviewId}
      enableRowSelection={(row) => row.original.status === "pending"}
      rowSelection={rowSelection}
      onRowSelectionChange={onRowSelectionChange}
      renderBulkActions={(rows: Row<DedupReviewRecord>[]) => {
        const decideBulk = (value: DedupDecision) => {
          for (const row of rows) {
            if (row.original.status === "pending") {
              onDecide(row.original.review_id, value);
            }
          }
          onRowSelectionChange({});
        };
        return (
          <div className="flex flex-wrap gap-1">
            <Button
              disabled={decisionPending}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => decideBulk("accepted")}
            >
              <CheckIcon data-icon="inline-start" />
              선택 accept
            </Button>
            <Button
              disabled={decisionPending}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => decideBulk("rejected")}
            >
              <XIcon data-icon="inline-start" />
              선택 reject
            </Button>
          </div>
        );
      }}
    />
  );
}

export function DedupReviewClient() {
  const [state, dispatch] = useReducer(
    dedupReviewReducer,
    INITIAL_DEDUP_REVIEW_STATE,
  );
  const deferredQ = useDeferredValue(state.q.trim());
  const deferredProviders = useDeferredValue(state.providers);
  const deferredDatasetKeys = useDeferredValue(state.datasetKeys);
  const deferredCategories = useDeferredValue(state.categories);
  const bounds = scoreBounds(state.scoreFilter);
  const reviewParams = useMemo(
    () => ({
      status: state.status === "all" ? undefined : [state.status],
      kind: state.kind === "all" ? undefined : [state.kind],
      provider: deferredProviders.length > 0 ? deferredProviders : undefined,
      dataset_key:
        deferredDatasetKeys.length > 0 ? deferredDatasetKeys : undefined,
      category: deferredCategories.length > 0 ? deferredCategories : undefined,
      min_score: bounds.min,
      max_score: bounds.max,
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: state.pageSize,
      cursor: state.cursor ?? undefined,
    }),
    [
      bounds.max,
      bounds.min,
      deferredCategories,
      deferredDatasetKeys,
      deferredProviders,
      deferredQ,
      state.cursor,
      state.kind,
      state.pageSize,
      state.status,
    ],
  );
  const reviews = useDedupReviews(reviewParams);
  const detail = useDedupReviewDetail(state.detailReviewId);
  const decision = useDedupDecisionMutation();
  const items = useMemo(
    () => reviews.data?.data.items ?? [],
    [reviews.data?.data.items],
  );
  const providerOptions = useMemo(
    () =>
      uniqueSorted([
        ...state.providers,
        ...items.flatMap((item) => [
          item.feature_a.provider ?? "",
          item.feature_b.provider ?? "",
        ]),
      ]),
    [items, state.providers],
  );
  const datasetOptions = useMemo(
    () =>
      uniqueSorted([
        ...state.datasetKeys,
        ...items.flatMap((item) => [
          item.feature_a.dataset_key ?? "",
          item.feature_b.dataset_key ?? "",
        ]),
      ]),
    [items, state.datasetKeys],
  );
  const categoryOptions = useMemo(
    () =>
      uniqueSorted([
        ...state.categories,
        ...items.flatMap((item) => [
          item.feature_a.category,
          item.feature_b.category,
        ]),
      ]),
    [items, state.categories],
  );
  const totalItems = reviews.data?.meta.page?.total ?? null;
  const nextCursor = reviews.data?.meta.page?.next_cursor ?? null;

  const goNextPage = useCallback(() => {
    if (!nextCursor) return;
    dispatch({ type: "next-page", cursor: nextCursor });
  }, [nextCursor]);

  const decide = useCallback(
    (reviewId: string, value: DedupDecision) => {
      decision.mutate({
        reviewKey: reviewId,
        body: {
          decision: value,
          decision_reason: `admin-ui ${value}`,
        },
      });
    },
    [decision],
  );

  const merge = useCallback(
    (reviewId: string, masterFeatureId?: string) => {
      decision.mutate(
        {
          reviewKey: reviewId,
          body: {
            decision: "merged",
            master_feature_id: masterFeatureId,
            decision_reason: masterFeatureId
              ? "admin-ui merge (master 수동 선택)"
              : "admin-ui merge (master 자동 선정)",
          },
        },
        {
          onSettled: () => dispatch({ type: "select-merge", reviewId: null }),
        },
      );
    },
    [decision],
  );

  const openDetail = useCallback((reviewId: string) => {
    dispatch({ type: "open-detail", reviewId });
  }, []);
  const selectMerge = useCallback((reviewId: string | null) => {
    dispatch({ type: "select-merge", reviewId });
  }, []);
  const columns = useDedupReviewColumns({
    decisionPending: decision.isPending,
    mergeKey: state.mergeKey,
    onDecide: decide,
    onMerge: merge,
    onOpenDetail: openDetail,
    onSelectMerge: selectMerge,
  });

  return (
    <AdminShell
      actions={
        <Button
          disabled={reviews.isFetching}
          type="button"
          variant="outline"
          onClick={() => void reviews.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="중복 후보를 검토해 채택·거절·무시하거나 병합합니다."
      title="중복 검토"
    >
      <div className="flex flex-col gap-4">
        {(reviews.isError || decision.isError) && (
          <Alert variant="destructive">
            <AlertTitle>dedup review 처리 실패</AlertTitle>
            <AlertDescription>
              {reviews.error?.message ?? decision.error?.message}
            </AlertDescription>
          </Alert>
        )}

        {state.detailReviewId ? (
          <DedupDetailDialog
            detail={detail.data?.data}
            error={detail.error ?? null}
            isLoading={detail.isLoading}
            onClose={() => dispatch({ type: "close-detail" })}
          />
        ) : null}

        <DedupReviewFiltersPanel
          categoryOptions={categoryOptions}
          datasetOptions={datasetOptions}
          filters={state}
          providerOptions={providerOptions}
          onChange={(patch) => dispatch({ type: "change-filters", patch })}
        />

        <DedupReviewPager
          hasNext={Boolean(nextCursor)}
          isFetching={reviews.isFetching}
          isFirst={state.cursor === null}
          itemCount={items.length}
          pageIndex={state.pageIndex}
          placement="top"
          totalItems={totalItems}
          onFirst={() => dispatch({ type: "first-page" })}
          onNext={goNextPage}
        />

        <DedupReviewTable
          columns={columns}
          data={items}
          detailReviewId={state.detailReviewId}
          decisionPending={decision.isPending}
          isLoading={reviews.isLoading}
          rowSelection={state.rowSelection}
          onDecide={decide}
          onOpenDetail={openDetail}
          onRowSelectionChange={(update) =>
            dispatch({ type: "select-rows", update })
          }
        />

        <DedupReviewPager
          hasNext={Boolean(nextCursor)}
          isFetching={reviews.isFetching}
          isFirst={state.cursor === null}
          itemCount={items.length}
          pageIndex={state.pageIndex}
          placement="bottom"
          totalItems={totalItems}
          onFirst={() => dispatch({ type: "first-page" })}
          onNext={goNextPage}
        />
      </div>
    </AdminShell>
  );
}
