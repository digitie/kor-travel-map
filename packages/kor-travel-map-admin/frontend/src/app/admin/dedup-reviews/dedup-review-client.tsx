"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import {
  type ColumnDef,
  type Row,
  type RowSelectionState,
} from "@tanstack/react-table";
import { CheckIcon, MergeIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { type Map as MapLibreMap } from "maplibre-gl";
import {
  useCallback,
  useDeferredValue,
  useMemo,
  useReducer,
  useState,
  type ReactNode,
} from "react";

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
// enum → 한글 라벨(design.md §Copy — 옵션도 raw enum 금지).
const FEATURE_KIND_LABELS: Record<(typeof DEDUP_KINDS)[number], string> = {
  place: "장소",
  event: "행사",
  notice: "공지",
  price: "가격",
  weather: "날씨",
  route: "경로",
  area: "구역",
};
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const SCORE_FILTERS = [
  { value: "all", label: "전체" },
  { value: "high", label: "≥ 90", min: 90 },
  { value: "middle", label: "70–90", min: 70, max: 90 },
  { value: "low", label: "< 70", max: 70 },
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

function formatScore(value: number): string {
  return value.toFixed(1);
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return NULL_GLYPH;
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

function statusOptionLabel(value: DedupStatus | "all"): string {
  return value === "all" ? "전체" : statusLabel(value);
}

function CompareColumn({
  eyebrow,
  eyebrowClassName,
  feature,
}: {
  eyebrow: string;
  eyebrowClassName: string;
  feature: DetailFeature;
}) {
  const primarySource = feature.sources.find(
    (source) => source.source_role === "primary",
  );
  const items: DetailItem[] = [
    {
      label: "종류",
      value: FEATURE_KIND_LABELS[feature.kind as (typeof DEDUP_KINDS)[number]] ?? feature.kind,
    },
    { label: "카테고리", value: feature.category },
    {
      label: "상태 축",
      value: (
        <FeatureStateBadges
          lifecycleState={feature.lifecycle_state}
          publicationState={feature.publication_state}
          qualityState={feature.quality_state}
        />
      ),
    },
    { label: "경도", value: feature.lon?.toFixed(6) ?? null, mono: true },
    { label: "위도", value: feature.lat?.toFixed(6) ?? null, mono: true },
    { label: "primary provider", value: primarySource?.provider ?? null },
    { label: "primary entity", value: primarySource?.source_entity_id ?? null, mono: true },
  ];
  return (
    <section className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-0.5">
        <div className={`text-2xs font-medium ${eyebrowClassName}`}>{eyebrow}</div>
        <h3 className="text-md font-semibold break-words text-text-primary">{feature.name}</h3>
        <div className="font-mono text-xs break-all text-text-secondary">
          <EntityLink
            className="text-xs"
            id={feature.feature_id}
            kind="feature"
            newTab
          />
        </div>
      </div>
      <DetailList items={items} layout="inline" />
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-2xs font-medium text-text-secondary">detail</span>
          <JsonViewer aria-label={`${eyebrow} detail`} copyable maxHeight="sm" value={feature.detail ?? {}} />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-2xs font-medium text-text-secondary">address</span>
          <JsonViewer aria-label={`${eyebrow} address`} copyable maxHeight="sm" value={feature.address ?? {}} />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-2xs font-medium text-text-secondary">sources</span>
          <JsonViewer aria-label={`${eyebrow} sources`} copyable maxHeight="sm" value={feature.sources} />
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
  const markerColors = useCompareMarkerColors();
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
          <div className="flex min-w-0 flex-col gap-0.5">
            <DialogTitle>중복 상세 비교</DialogTitle>
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
          ) : detail && featureA && featureB ? (
            <>
              <StatStrip
                ariaLabel="중복 점수"
                items={[
                  { label: "총점", value: formatScore(detail.total_score) },
                  { label: "이름 점수", value: formatScore(detail.name_score) },
                  { label: "거리 점수", value: formatScore(detail.spatial_score) },
                  { label: "카테고리 점수", value: formatScore(detail.category_score) },
                  { label: "거리", value: formatDistance(detail.distance_m) },
                ]}
              />
              {hasMap ? (
                <section className="flex flex-col gap-2 border-t border-border pt-4">
                  <div className="flex flex-wrap items-center gap-3 text-2xs font-medium text-text-secondary">
                    <span>위치 비교</span>
                    <span className="flex items-center gap-1">
                      <span aria-hidden="true" className="size-2 rounded-full bg-compare-a" />
                      A
                    </span>
                    <span className="flex items-center gap-1">
                      <span aria-hidden="true" className="size-2 rounded-full bg-compare-b" />
                      B
                    </span>
                  </div>
                  <div className="relative h-80 min-h-72 overflow-hidden rounded-control border border-border">
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
                        markerColor={markerColors.a}
                        selected
                        title={`Feature A: ${featureA.name}`}
                      />
                      <VWorldMarker
                        lngLat={[featureB.lon ?? 0, featureB.lat ?? 0]}
                        markerColor={markerColors.b}
                        title={`Feature B: ${featureB.name}`}
                      />
                    </VWorldMapView>
                  </div>
                </section>
              ) : null}
              <div className="grid gap-6 border-t border-border pt-4 lg:grid-cols-2 lg:gap-8 lg:divide-x lg:divide-border lg:[&>*:last-child]:pl-8">
                <CompareColumn
                  eyebrow="후보 A"
                  eyebrowClassName="text-compare-a"
                  feature={featureA}
                />
                <CompareColumn
                  eyebrow="후보 B"
                  eyebrowClassName="text-compare-b"
                  feature={featureB}
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

/** MultiFilterCombobox 는 자체 라벨 슬롯이 없어 FilterField 와 같은 라벨 리듬으로 감싼다. */
function ComboboxField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex w-56 min-w-0 flex-col gap-1" data-slot="filter-field">
      <span className="text-2xs leading-none font-medium text-text-secondary">{label}</span>
      {children}
    </div>
  );
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
    <FilterBar>
      <FilterField className="w-64" label="검색">
        <Input
          aria-label="dedup search"
          placeholder="feature id, name"
          value={filters.q}
          onChange={(event) => onChange({ q: event.target.value })}
        />
      </FilterField>
      <FilterField label="상태">
        <NativeSelect
          aria-label="dedup status"
          value={filters.status}
          onChange={(event) =>
            onChange({ status: event.target.value as DedupStatus | "all" })
          }
        >
          {statuses.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {statusOptionLabel(item)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <FilterField label="종류">
        <NativeSelect
          aria-label="dedup kind"
          value={filters.kind}
          onChange={(event) =>
            onChange({ kind: event.target.value as DedupKindFilter })
          }
        >
          <NativeSelectOption value="all">전체 종류</NativeSelectOption>
          {DEDUP_KINDS.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {FEATURE_KIND_LABELS[item]}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <ComboboxField label="provider">
        <MultiFilterCombobox
          ariaLabel="dedup provider"
          className="w-full"
          options={providerOptions}
          placeholder="provider"
          values={filters.providers}
          onChange={(providers) => onChange({ providers })}
        />
      </ComboboxField>
      <ComboboxField label="dataset">
        <MultiFilterCombobox
          ariaLabel="dedup dataset"
          className="w-full"
          options={datasetOptions}
          placeholder="dataset"
          values={filters.datasetKeys}
          onChange={(datasetKeys) => onChange({ datasetKeys })}
        />
      </ComboboxField>
      <ComboboxField label="category">
        <MultiFilterCombobox
          ariaLabel="dedup category"
          className="w-full"
          options={categoryOptions}
          placeholder="category"
          values={filters.categories}
          onChange={(categories) => onChange({ categories })}
        />
      </ComboboxField>
      <FilterField label="점수">
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
      </FilterField>
      <FilterField label="페이지 크기">
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
      </FilterField>
    </FilterBar>
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

/** master 후보 버튼 라벨 — 좌표 보유는 글리프(✓)가 아니라 lucide CheckIcon으로 표시한다(m2). */
function MasterCandidateLabel({
  prefix,
  feature,
}: {
  prefix: "A" | "B";
  feature: DedupFeatureRecord;
}) {
  return (
    <>
      {prefix}: {feature.name}
      {hasCoord(feature) ? (
        <span className="flex items-center gap-0.5 text-text-secondary">
          · 좌표
          <CheckIcon aria-hidden="true" className="size-3.5 text-success" />
        </span>
      ) : null}
    </>
  );
}

function useDedupReviewColumns({
  decisionPending,
  mergeKey,
  pendingReviewId,
  pendingDecision,
  pendingMasterFeatureId,
  onDecide,
  onMerge,
  onSelectMerge,
}: {
  decisionPending: boolean;
  mergeKey: string | null;
  pendingReviewId: string | null;
  /** 진행 중인 결정이 무엇인지 — 행 안에서 **누른 버튼**을 특정하는 축(mutation variables). */
  pendingDecision: DedupDecision | null;
  pendingMasterFeatureId: string | null;
  onDecide: (reviewId: string, decision: DedupDecision) => void;
  onMerge: (reviewId: string, masterFeatureId?: string) => void;
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
          <div className="flex flex-col gap-0.5 text-xs text-text-secondary tabular-nums">
            <div className="text-text-primary">total {formatScore(row.original.total_score)}</div>
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
        id: "feature_a",
        header: "후보 A",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.feature_a.name}</div>
            <div className="text-xs text-text-secondary">
              {row.original.feature_a.provider ?? NULL_GLYPH} ·{" "}
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
            <div className="text-xs text-text-secondary">
              {row.original.feature_b.provider ?? NULL_GLYPH} ·{" "}
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
          const busy = decisionPending && pendingReviewId === item.review_id;
          const reason =
            decisionPending && !busy ? "다른 결정을 처리하는 중입니다" : undefined;
          // P1-5: 진행 표면은 **누른 버튼**에 붙어야 한다. 그룹 첫 버튼에 고정하면 방금 누른
          // 버튼은 native disabled가 되어 포커스를 잃고(돌아갈 자리가 사라진다) spinner는
          // 엉뚱한 버튼에서 돈다. "무엇을 눌렀는지"의 정본은 mutation variables다.
          const busyWith = (value: DedupDecision) => busy && pendingDecision === value;
          const busyMerge = (masterFeatureId: string | null) =>
            busyWith("merged") && pendingMasterFeatureId === masterFeatureId;
          if (mergeKey === item.review_id) {
            return (
              <div
                className="flex flex-col gap-1"
                onClick={(event) => event.stopPropagation()}
              >
                <span className="text-2xs text-text-secondary">
                  master 선택 (병합 시 나머지는 master로 흡수)
                </span>
                <div className="flex flex-wrap gap-1">
                  <Button
                    disabled={decisionPending}
                    disabledReason={reason}
                    loading={busyMerge(item.feature_a.feature_id)}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      onMerge(item.review_id, item.feature_a.feature_id)
                    }
                  >
                    <MasterCandidateLabel feature={item.feature_a} prefix="A" />
                  </Button>
                  <Button
                    disabled={decisionPending}
                    disabledReason={reason}
                    loading={busyMerge(item.feature_b.feature_id)}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      onMerge(item.review_id, item.feature_b.feature_id)
                    }
                  >
                    <MasterCandidateLabel feature={item.feature_b} prefix="B" />
                  </Button>
                  {/*
                    A · B · 자동은 같은 축의 **동등한 세 선택지**라 셋 다 `outline`이다.
                    `secondary`(brand-tint 채움 + `border-brand`)는 design.md §CTA voice에서
                    **토글의 눌린 상태 전용**이다 — 이 시스템의 brand tint는 어디서나 "선택됨"을
                    뜻하는데(SelectableRow 선택 행 · Checkbox `data-checked` · field
                    `has-data-checked`), 아직 아무것도 고르지 않은 자리에서 한 버튼만 tint를
                    쓰면 "이미 자동이 선택돼 있다"로 잘못 읽힌다.
                  */}
                  <Button
                    disabled={decisionPending}
                    disabledReason={reason}
                    loading={busyMerge(null)}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => onMerge(item.review_id)}
                  >
                    자동 선정
                  </Button>
                  <Button
                    disabled={decisionPending}
                    disabledReason={reason}
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
                disabled={decisionPending}
                disabledReason={reason}
                loading={busyWith("accepted")}
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
                disabledReason={reason}
                loading={busyWith("rejected")}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => onDecide(item.review_id, "rejected")}
              >
                <XIcon data-icon="inline-start" />
                reject
              </Button>
              <Button
                disabled={decisionPending}
                disabledReason={reason}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => onSelectMerge(item.review_id)}
              >
                <MergeIcon data-icon="inline-start" />
                merge
              </Button>
              <Button
                disabled={decisionPending}
                disabledReason={reason}
                loading={busyWith("ignored")}
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
    [
      decisionPending,
      mergeKey,
      onDecide,
      onMerge,
      onSelectMerge,
      pendingDecision,
      pendingMasterFeatureId,
      pendingReviewId,
    ],
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
      emptyState={{
        title: "dedup review가 없습니다.",
        description: "상태 필터를 전체로 바꾸거나 점수·provider·dataset 조건을 넓혀 보세요.",
      }}
      isLoading={isLoading}
      manualSorting={false}
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
              disabledReason="다른 결정을 처리하는 중입니다"
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
              disabledReason="다른 결정을 처리하는 중입니다"
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
    pendingReviewId: decision.isPending ? (decision.variables?.reviewKey ?? null) : null,
    pendingDecision: decision.isPending
      ? (decision.variables?.body.decision ?? null)
      : null,
    pendingMasterFeatureId: decision.isPending
      ? (decision.variables?.body.master_feature_id ?? null)
      : null,
    onDecide: decide,
    onMerge: merge,
    onSelectMerge: selectMerge,
  });
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
      description="중복 후보를 검토해 채택·거절·무시하거나 병합합니다."
      title="중복 검토"
    >
      <div className="flex flex-col gap-4">
        {errorLines.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>dedup review 처리 실패</AlertTitle>
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
