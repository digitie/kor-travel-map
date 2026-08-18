"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list) · design-system: design.md · designed-as-app

import {
  AlertTriangleIcon,
  EyeIcon,
  ExternalLinkIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import {
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
} from "@tanstack/react-table";
import Link from "next/link";
import { useCallback, useDeferredValue, useMemo, useState } from "react";

import {
  FEATURE_KINDS,
  FEATURE_LIFECYCLE_STATES,
  FEATURE_PUBLICATION_STATES,
  FEATURE_QUALITY_STATES,
  featureStateLabel,
  fetchAdminFeatureCorrectionBasis,
  useAdminFeatures,
  useAdminFeatureDetail,
  usePatchAdminFeatureStateMutation,
  type AdminFeatureDetailData,
  type AdminFeatureRecord,
  type AdminFeatureSort,
  type FeatureKind,
  type FeatureLifecycleState,
  type FeaturePublicationState,
  type FeatureQualityState,
  type SortOrder,
} from "@/api/features";
import { AdminShell } from "@/components/admin-shell";
import { CursorPager } from "@/components/pagination-bar";
import { useConfirm } from "@/components/confirm-dialog";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { FeatureAssociations } from "@/components/feature-associations";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { JsonViewer } from "@/components/json-viewer";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;
const SORT_OPTIONS: AdminFeatureSort[] = [
  "name",
  "updated_at",
  "created_at",
  "kind",
  "provider",
  "issue_count",
];
const SORT_LABELS: Record<AdminFeatureSort, string> = {
  name: "이름",
  updated_at: "수정 시각",
  created_at: "생성 시각",
  kind: "종류",
  provider: "provider",
  issue_count: "이슈 수",
};
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
/** 미리보기 마커 색은 토큰만(design.md §Theme — `--compare-a/b`). */
const PREVIEW_MARKER_COLOR = "var(--compare-a)";

type HasIssueFilter = "all" | "yes" | "no";
type AxisFilter<T extends string> = T | "all";

function parseProviderDatasetId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const providerDatasetId = Number(value);
  return Number.isSafeInteger(providerDatasetId) && providerDatasetId > 0
    ? providerDatasetId
    : null;
}

function coordLabel(feature: {
  lon?: number | null;
  lat?: number | null;
}): string | null {
  if (typeof feature.lon === "number" && typeof feature.lat === "number") {
    return `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`;
  }
  return null;
}

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

/** inspector 안 접이식 payload(address/detail) — summary 12px/500 + JsonViewer. */
function PayloadDisclosure({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="group/details">
      <summary className="inline-flex h-control-sm cursor-pointer list-none items-center gap-1 rounded-control font-mono text-xs text-text-secondary select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        {label}
      </summary>
      <div className="pt-1">
        <JsonViewer maxHeight="sm" value={value} />
      </div>
    </details>
  );
}

function FeatureLocationMap({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"] | null | undefined;
}) {
  const hasCoord =
    typeof feature?.lon === "number" && typeof feature?.lat === "number";
  if (!hasCoord) {
    return (
      <EmptyState
        description="주소나 좌표를 보정하면 지도에 표시됩니다."
        size="sm"
        title="좌표가 없어 지도 marker를 표시할 수 없습니다."
      />
    );
  }

  return (
    <div className="relative h-52 overflow-hidden rounded-panel border border-border bg-surface-subtle">
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
          markerColor={PREVIEW_MARKER_COLOR}
          selected
          title={feature.name}
        />
      </VWorldMapView>
    </div>
  );
}

/** 우측 inspector rail(design.md list — 행 선택 시 `--rail` 폭 패널, 안쪽은 hairline으로만 나눈 flat 블록). */
function FeatureDetailInspector({
  featureId,
  onClose,
}: {
  featureId: string | null;
  onClose: () => void;
}) {
  const detail = useAdminFeatureDetail(featureId);
  const data = detail.data?.data;
  const feature = data?.feature;

  if (!featureId) {
    return (
      <EmptyState
        description="행을 클릭하거나 preview를 누르면 이 자리에 열립니다."
        framed
        title="table에서 feature를 선택하면 상세와 kind별 패널을 확인할 수 있습니다."
      />
    );
  }

  return (
    <Card className="gap-0 p-0">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          {feature ? (
            <h2 className="text-md leading-snug font-semibold break-keep text-text-primary">
              {feature.name}
            </h2>
          ) : (
            <span className="text-xs font-medium text-text-secondary">선택 Feature</span>
          )}
          <span className="font-mono text-xs break-all text-text-secondary slashed-zero">
            {featureId}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Link
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            href={featureDetailHref(featureId)}
          >
            <PencilIcon data-icon="inline-start" />
            편집
          </Link>
          <Button
            aria-label="미리보기 닫기"
            size="icon-sm"
            type="button"
            variant="ghost"
            onClick={onClose}
          >
            <XIcon />
          </Button>
        </div>
      </div>
      <div className="flex flex-col divide-y divide-border px-4 [&>*]:py-4">
        {detail.isLoading ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : null}
        {detail.isError ? (
          <div>
            <Alert variant="destructive">
              <AlertTitle>feature 상세 조회 실패</AlertTitle>
              <AlertDescription>{detail.error.message}</AlertDescription>
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
              </AlertActions>
            </Alert>
          </div>
        ) : null}
        {data && feature ? (
          <>
            <div className="flex flex-wrap gap-1">
              <FeatureStateBadges
                lifecycleState={feature.lifecycle_state}
                publicationState={feature.publication_state}
                qualityState={feature.quality_state}
              />
              <Badge variant="neutral">{feature.kind}</Badge>
              <Badge variant="outline">{feature.category}</Badge>
            </div>
            <FeatureLocationMap feature={feature} />
            <DetailList
              items={[
                { label: "coord", value: coordLabel(feature), mono: true },
                { label: "sigungu", value: feature.sigungu_code ?? null, mono: true },
              ]}
              layout="inline"
            />
            <div className="flex flex-col gap-2">
              <PayloadDisclosure label="address" value={feature.address} />
              <PayloadDisclosure label="detail" value={feature.detail} />
            </div>
            <FeatureAssociations
              compact
              curations={data.curations}
              observations={data.sources}
            />
            <FeatureKindDetailPanel compact feature={feature} featureId={featureId} />
          </>
        ) : null}
      </div>
    </Card>
  );
}

function useAdminFeaturesClientController({
  initialQ,
  initialKind,
  initialLifecycleState,
  initialPublicationState,
  initialQualityState,
  initialProviderDatasetId,
  initialHasIssue,
}: {
  initialQ?: string;
  initialKind?: string;
  initialLifecycleState?: string;
  initialPublicationState?: string;
  initialQualityState?: string;
  initialProviderDatasetId?: string;
  initialHasIssue?: string;
} = {}) {
  const [q, setQ] = useState(initialQ ?? "");
  const deferredQ = useDeferredValue(q.trim());
  const [kind, setKind] = useState<FeatureKind | "all">(() =>
    initialKind && (FEATURE_KINDS as readonly string[]).includes(initialKind)
      ? (initialKind as FeatureKind)
      : "all",
  );
  const [lifecycleState, setLifecycleState] = useState<
    AxisFilter<FeatureLifecycleState>
  >(() =>
    initialLifecycleState &&
    ([...FEATURE_LIFECYCLE_STATES, "all"] as string[]).includes(
      initialLifecycleState,
    )
      ? (initialLifecycleState as AxisFilter<FeatureLifecycleState>)
      : "all",
  );
  const [publicationState, setPublicationState] = useState<
    AxisFilter<FeaturePublicationState>
  >(() =>
    initialPublicationState &&
    ([...FEATURE_PUBLICATION_STATES, "all"] as string[]).includes(
      initialPublicationState,
    )
      ? (initialPublicationState as AxisFilter<FeaturePublicationState>)
      : "all",
  );
  const [qualityState, setQualityState] = useState<
    AxisFilter<FeatureQualityState>
  >(() =>
    initialQualityState &&
    ([...FEATURE_QUALITY_STATES, "all"] as string[]).includes(
      initialQualityState,
    )
      ? (initialQualityState as AxisFilter<FeatureQualityState>)
      : "all",
  );
  // retire의 **mutation 이전** 실패(correction basis fetch)를 담는다. mutation이
  // 시작되지 않으면 `stateMutation.isError`가 false로 남아 화면에 아무것도 뜨지 않는다.
  const [retireError, setRetireError] = useState<string | null>(null);
  const [hasIssue, setHasIssue] = useState<HasIssueFilter>(() =>
    initialHasIssue === "yes" || initialHasIssue === "no"
      ? initialHasIssue
      : "all",
  );
  const [providerDatasetId, setProviderDatasetId] = useState<number | null>(
    () => parseProviderDatasetId(initialProviderDatasetId),
  );
  const [sort, setSort] = useState<AdminFeatureSort>("name");
  const [order, setOrder] = useState<SortOrder>("asc");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(1);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(
    null,
  );

  const params = useMemo(
    () => ({
      q: deferredQ.length > 0 ? deferredQ : undefined,
      kind: kind === "all" ? undefined : [kind],
      lifecycle_state: lifecycleState === "all" ? undefined : [lifecycleState],
      publication_state:
        publicationState === "all" ? undefined : [publicationState],
      quality_state: qualityState === "all" ? undefined : [qualityState],
      has_issue: hasIssue === "all" ? undefined : hasIssue === "yes",
      provider_dataset_id: providerDatasetId ?? undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
      sort,
      order,
    }),
    [
      cursor,
      deferredQ,
      hasIssue,
      kind,
      order,
      pageSize,
      providerDatasetId,
      sort,
      lifecycleState,
      publicationState,
      qualityState,
    ],
  );
  const features = useAdminFeatures(params);
  const stateMutation = usePatchAdminFeatureStateMutation();
  const confirm = useConfirm();
  const items = features.data?.data.items ?? [];
  const nextCursor = features.data?.meta.page?.next_cursor ?? null;

  const resetCursor = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goFirstPage = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goNextPage = () => {
    if (!nextCursor) return;
    setCursor(nextCursor);
    setPageIndex((page) => page + 1);
  };
  const refresh = () => {
    void features.refetch();
  };

  const retireFeature = useCallback(
    async (feature: AdminFeatureRecord) => {
      if (feature.lifecycle_state === "retired") return;
      const ok = await confirm({
        title: `${feature.name} feature를 종료할까요?`,
        description: "provider 재적재로 다시 활성화되지 않도록 잠급니다.",
        confirmLabel: "종료",
        destructive: true,
      });
      if (!ok) return;
      setRetireError(null);
      // mutation **이전** 단계다. `fetchAdminFeatureCorrectionBasis`는 revision/detail
      // 3회 불일치나 4xx/5xx에서 reject하는데, 여기서 새어 나가면 mutation이 시작조차
      // 되지 않아 `stateMutation.isError`가 false로 남는다 — 운영자 입장에서는 버튼을
      // 눌렀는데 아무 일도, 아무 메시지도 없다. 실패를 화면의 같은 Alert로 올린다.
      let basis: Awaited<ReturnType<typeof fetchAdminFeatureCorrectionBasis>>;
      try {
        basis = await fetchAdminFeatureCorrectionBasis(feature.feature_id);
      } catch (error: unknown) {
        setRetireError(error instanceof Error ? error.message : String(error));
        return;
      }
      stateMutation.mutate({
        featureId: basis.featureId,
        entityTag: basis.entityTag,
        body: { action: "retire", reason_code: "admin_ui_retire" },
      });
    },
    [confirm, stateMutation],
  );

  // 서버 정렬(keyset cursor)이므로 sort/order state를 react-table SortingState로
  // 양방향 미러링한다. 기존 sort NativeSelect + asc/desc Button과 동일 state를 공유한다.
  const sorting = useMemo<SortingState>(
    () => [{ id: sort, desc: order === "desc" }],
    [sort, order],
  );
  const handleSortingChange: OnChangeFn<SortingState> = (updater) => {
    const next = typeof updater === "function" ? updater(sorting) : updater;
    const first = next[0];
    if (!first) return;
    setSort(first.id as AdminFeatureSort);
    setOrder(first.desc ? "desc" : "asc");
    resetCursor();
  };

  const columns = useMemo<ColumnDef<AdminFeatureRecord, unknown>[]>(
    () => [
      {
        id: "name",
        header: "feature",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate font-medium">{feature.name}</span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {shortId(feature.feature_id, 18)}
              </span>
            </div>
          );
        },
      },
      {
        id: "kind_state",
        header: "종류/상태",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex flex-wrap gap-1">
                <Badge variant="neutral">{feature.kind}</Badge>
                <FeatureStateBadges
                  lifecycleState={feature.lifecycle_state}
                  publicationState={feature.publication_state}
                  qualityState={feature.quality_state}
                />
              </div>
              <span className="font-mono text-2xs text-text-secondary slashed-zero">
                {feature.category}
              </span>
            </div>
          );
        },
      },
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className={cn("truncate", !feature.primary_provider && "text-text-tertiary")}>
                {feature.primary_provider ?? NULL_GLYPH}
              </span>
              <span className="truncate font-mono text-2xs text-text-secondary slashed-zero">
                {feature.primary_dataset_key ?? NULL_GLYPH}
              </span>
            </div>
          );
        },
      },
      {
        id: "issue_count",
        header: "이슈",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              {feature.issue_count > 0 ? (
                <EntityLink
                  className="font-medium text-destructive tabular-nums hover:text-destructive"
                  id=""
                  kind="issue"
                  params={{ feature_id: feature.feature_id }}
                >
                  {feature.issue_count}
                </EntityLink>
              ) : (
                <span className="text-text-tertiary tabular-nums">{feature.issue_count}</span>
              )}
              {feature.issues.slice(0, 2).map((issue) => (
                <span
                  className="max-w-48 truncate text-2xs text-text-secondary"
                  key={issue.issue_id ?? issue.message}
                >
                  {issue.violation_type ?? "issue"} · {issue.message ?? NULL_GLYPH}
                </span>
              ))}
            </div>
          );
        },
      },
      {
        id: "coord_address",
        header: "좌표/주소",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          const coordinate = coordLabel(feature);
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span
                className={cn(
                  "font-mono text-xs slashed-zero",
                  coordinate ? "text-text-primary" : "text-text-tertiary",
                )}
              >
                {coordinate ?? NULL_GLYPH}
              </span>
              <span className="max-w-64 truncate text-2xs text-text-secondary">
                {feature.address_label || NULL_GLYPH}
              </span>
            </div>
          );
        },
      },
      {
        id: "updated_at",
        header: "수정",
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          const retired = feature.lifecycle_state === "retired";
          return (
            <div className="flex flex-wrap gap-1">
              <Link
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                )}
                href={featureDetailHref(feature.feature_id)}
                onClick={(event) => {
                  event.stopPropagation();
                }}
              >
                <ExternalLinkIcon data-icon="inline-start" />
                detail
              </Link>
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedFeatureId(feature.feature_id);
                }}
              >
                <EyeIcon data-icon="inline-start" />
                preview
              </Button>
              <Button
                className="text-destructive hover:text-destructive"
                disabled={stateMutation.isPending || retired}
                disabledReason={
                  retired ? "이미 종료된 feature입니다" : "다른 상태 변경이 진행 중입니다"
                }
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  void retireFeature(feature);
                }}
              >
                <XCircleIcon data-icon="inline-start" />
                retire
              </Button>
            </div>
          );
        },
      },
    ],
    [retireFeature, stateMutation.isPending],
  );

  return {
    columns,
    cursor,
    retireError,
    stateMutation,
    features,
    goFirstPage,
    goNextPage,
    handleSortingChange,
    hasIssue,
    items,
    kind,
    nextCursor,
    order,
    pageIndex,
    pageSize,
    providerDatasetId,
    q,
    refresh,
    resetCursor,
    selectedFeatureId,
    setHasIssue,
    setKind,
    setOrder,
    setPageSize,
    setProviderDatasetId,
    setQ,
    setSelectedFeatureId,
    setSort,
    setLifecycleState,
    setPublicationState,
    setQualityState,
    sort,
    sorting,
    lifecycleState,
    publicationState,
    qualityState,
  };
}

type AdminFeatureFilterBarProps = Pick<
  ReturnType<typeof useAdminFeaturesClientController>,
  | "hasIssue"
  | "kind"
  | "lifecycleState"
  | "order"
  | "pageSize"
  | "providerDatasetId"
  | "publicationState"
  | "q"
  | "qualityState"
  | "resetCursor"
  | "setHasIssue"
  | "setKind"
  | "setLifecycleState"
  | "setOrder"
  | "setPageSize"
  | "setProviderDatasetId"
  | "setPublicationState"
  | "setQ"
  | "setQualityState"
  | "setSort"
  | "sort"
>;

/** 목록 상단 검색·필터·정렬 툴바(FilterBar/FilterField 표준 — 가시 라벨, wrap, M26).
 *
 * T-VN-34에서 단일 ``status`` 필터가 lifecycle/publication/quality 3축으로
 * 갈라지며 이 구간만 세 배가 됐다. 목록/상세 레이아웃과 축 필터는 서로를
 * 참조하지 않으므로 툴바를 별도 컴포넌트로 둔다. 정렬 select + asc/desc는 서버
 * keyset 정렬의 유일한 표면이라 유지한다(표 컬럼은 display 전용).
 */
function AdminFeatureFilterBar({
  hasIssue,
  kind,
  lifecycleState,
  order,
  pageSize,
  providerDatasetId,
  publicationState,
  q,
  qualityState,
  resetCursor,
  setHasIssue,
  setKind,
  setLifecycleState,
  setOrder,
  setPageSize,
  setProviderDatasetId,
  setPublicationState,
  setQ,
  setQualityState,
  setSort,
  sort,
}: AdminFeatureFilterBarProps) {
  return (
    <FilterBar>
      <FilterField htmlFor="admin-feature-search" label="검색">
        <Input
          aria-label="feature search"
          className="w-64"
          id="admin-feature-search"
          placeholder="이름 · 주소 · feature_id"
          size="sm"
          type="search"
          value={q}
          onChange={(event) => {
            setQ(event.target.value);
            resetCursor();
          }}
        />
      </FilterField>
      <FilterField htmlFor="admin-feature-kind" label="종류">
        <NativeSelect
          aria-label="feature kind"
          className="w-32"
          id="admin-feature-kind"
          size="sm"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value as FeatureKind | "all");
            resetCursor();
          }}
        >
          <NativeSelectOption value="all">모든 종류</NativeSelectOption>
          {FEATURE_KINDS.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {item}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <FilterField htmlFor="admin-feature-lifecycle" label="수명">
        <NativeSelect
          aria-label="feature lifecycle state"
          className="w-32"
          id="admin-feature-lifecycle"
          size="sm"
          value={lifecycleState}
          onChange={(event) => {
            setLifecycleState(
              event.target.value as AxisFilter<FeatureLifecycleState>,
            );
            resetCursor();
          }}
        >
          <NativeSelectOption value="all">모든 수명</NativeSelectOption>
          {FEATURE_LIFECYCLE_STATES.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {featureStateLabel("lifecycle", item)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <FilterField htmlFor="admin-feature-publication" label="공개">
        <NativeSelect
          aria-label="feature publication state"
          className="w-32"
          id="admin-feature-publication"
          size="sm"
          value={publicationState}
          onChange={(event) => {
            setPublicationState(
              event.target.value as AxisFilter<FeaturePublicationState>,
            );
            resetCursor();
          }}
        >
          <NativeSelectOption value="all">모든 공개</NativeSelectOption>
          {FEATURE_PUBLICATION_STATES.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {featureStateLabel("publication", item)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <FilterField htmlFor="admin-feature-quality" label="품질">
        <NativeSelect
          aria-label="feature quality state"
          className="w-32"
          id="admin-feature-quality"
          size="sm"
          value={qualityState}
          onChange={(event) => {
            setQualityState(event.target.value as AxisFilter<FeatureQualityState>);
            resetCursor();
          }}
        >
          <NativeSelectOption value="all">모든 품질</NativeSelectOption>
          {FEATURE_QUALITY_STATES.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {featureStateLabel("quality", item)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <FilterField htmlFor="admin-feature-has-issue" label="이슈">
        <NativeSelect
          aria-label="has issue"
          className="w-32"
          id="admin-feature-has-issue"
          size="sm"
          value={hasIssue}
          onChange={(event) => {
            setHasIssue(event.target.value as HasIssueFilter);
            resetCursor();
          }}
        >
          <NativeSelectOption value="all">이슈 전체</NativeSelectOption>
          <NativeSelectOption value="yes">이슈 있음</NativeSelectOption>
          <NativeSelectOption value="no">이슈 없음</NativeSelectOption>
        </NativeSelect>
      </FilterField>
      <FilterField
        hint="숫자 ID · 데이터셋 화면에서 복사"
        htmlFor="admin-feature-provider-dataset"
        label="provider dataset ID"
      >
        <Input
          aria-label="feature provider dataset ID"
          className="w-36"
          id="admin-feature-provider-dataset"
          inputMode="numeric"
          min={1}
          placeholder="예: 703"
          size="sm"
          type="number"
          value={providerDatasetId ?? ""}
          onChange={(event) => {
            setProviderDatasetId(parseProviderDatasetId(event.target.value));
            resetCursor();
          }}
        />
      </FilterField>
      <Link
        aria-label="데이터셋에서 선택"
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "shrink-0 self-end")}
        href="/ops/datasets"
      >
        데이터셋에서 선택
      </Link>
      <FilterField htmlFor="admin-feature-sort" label="정렬">
        <NativeSelect
          aria-label="feature sort"
          className="w-36"
          id="admin-feature-sort"
          size="sm"
          value={sort}
          onChange={(event) => {
            setSort(event.target.value as AdminFeatureSort);
            resetCursor();
          }}
        >
          {SORT_OPTIONS.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {SORT_LABELS[item]}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </FilterField>
      <div className="flex min-w-0 flex-col gap-1">
        <span aria-hidden="true" className="text-2xs leading-none font-medium text-text-secondary">
          방향
        </span>
        <div aria-label="정렬 방향" className="flex items-center gap-1" role="group">
          <Button
            aria-pressed={order === "asc"}
            size="sm"
            type="button"
            variant={order === "asc" ? "default" : "outline"}
            onClick={() => {
              setOrder("asc");
              resetCursor();
            }}
          >
            asc
          </Button>
          <Button
            aria-pressed={order === "desc"}
            size="sm"
            type="button"
            variant={order === "desc" ? "default" : "outline"}
            onClick={() => {
              setOrder("desc");
              resetCursor();
            }}
          >
            desc
          </Button>
        </div>
      </div>
      <FilterActions>
        <FilterField htmlFor="admin-feature-page-size" label="페이지 크기">
          <NativeSelect
            aria-label="feature page size"
            className="w-24"
            id="admin-feature-page-size"
            size="sm"
            value={String(pageSize)}
            onChange={(event) => {
              setPageSize(Number(event.target.value) as typeof pageSize);
              resetCursor();
            }}
          >
            {PAGE_SIZE_OPTIONS.map((item) => (
              <NativeSelectOption key={item} value={item}>
                {item}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
      </FilterActions>
    </FilterBar>
  );
}

type FailureItem = { source: string; message: string | undefined };

function AdminFeaturesClientView({
  columns,
  cursor,
  retireError,
  stateMutation,
  features,
  goFirstPage,
  goNextPage,
  handleSortingChange,
  items,
  nextCursor,
  pageIndex,
  pageSize,
  refresh,
  selectedFeatureId,
  setSelectedFeatureId,
  sorting,
  ...filters
}: ReturnType<typeof useAdminFeaturesClientController>) {
  const failureCandidates: Array<FailureItem | null> = [
    features.isError ? { source: "목록 조회", message: features.error?.message } : null,
    stateMutation.isError
      ? { source: "상태 변경", message: stateMutation.error?.message }
      : null,
    retireError !== null ? { source: "종료 준비", message: retireError } : null,
  ];
  const failures = failureCandidates.filter((item): item is FailureItem => item !== null);
  return (
    <AdminShell
      actions={
        <>
          <Button
            loading={features.isFetching}
            type="button"
            variant="outline"
            onClick={refresh}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Link
            className={cn(buttonVariants({ variant: "default" }))}
            href="/admin/features/new"
          >
            <PlusIcon data-icon="inline-start" />새 작성
          </Link>
        </>
      }
      description="적재된 feature를 검색·필터·정렬하고 행을 선택해 상세와 kind별 패널을 확인합니다."
      title="Feature 목록"
    >
      <div className="flex flex-col gap-4">
        {failures.length > 0 ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>admin feature 처리 실패</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-0.5 pl-4">
                {failures.map((item) => (
                  <li key={item.source}>
                    <span className="font-medium">{item.source}</span>
                    {item.message ? <> — {item.message}</> : null}
                  </li>
                ))}
              </ul>
            </AlertDescription>
            <AlertActions>
              <Button
                loading={features.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={refresh}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        <AdminFeatureFilterBar {...filters} pageSize={pageSize} />

        <section
          className={cn(
            "grid gap-4",
            "xl:grid-cols-[minmax(0,1fr)_var(--rail)]",
          )}
        >
          <div className="flex min-w-0 flex-col gap-2">
            <CursorPager
              hasNext={Boolean(nextCursor)}
              isFetching={features.isFetching}
              isFirst={cursor === null}
              placement="top"
              summary={
                <>
                  {formatCount(items.length)} rows · page {formatCount(pageIndex)} · page
                  size {formatCount(pageSize)}
                </>
              }
              onFirst={goFirstPage}
              onNext={goNextPage}
            />
            <DataTable
              columns={columns}
              data={items}
              emptyState={{
                title: "feature가 없습니다.",
                description:
                  "검색어·종류·상태 축·이슈·provider dataset 조건에 맞는 feature가 없습니다 — 필터를 넓혀 보세요.",
              }}
              getRowId={(feature) => feature.feature_id}
              isLoading={features.isLoading}
              isRowActive={(feature) =>
                selectedFeatureId === feature.feature_id
              }
              manualSorting
              onRowClick={(feature) => setSelectedFeatureId(feature.feature_id)}
              onSortingChange={handleSortingChange}
              skeletonRowCount={8}
              sorting={sorting}
            />
          </div>

          <FeatureDetailInspector
            featureId={selectedFeatureId}
            onClose={() => setSelectedFeatureId(null)}
          />
        </section>
      </div>
    </AdminShell>
  );
}

export function AdminFeaturesClient({
  initialQ,
  initialKind,
  initialLifecycleState,
  initialPublicationState,
  initialQualityState,
  initialProviderDatasetId,
  initialHasIssue,
}: {
  initialQ?: string;
  initialKind?: string;
  initialLifecycleState?: string;
  initialPublicationState?: string;
  initialQualityState?: string;
  initialProviderDatasetId?: string;
  initialHasIssue?: string;
} = {}) {
  const controller = useAdminFeaturesClientController({
    initialQ,
    initialKind,
    initialLifecycleState,
    initialPublicationState,
    initialQualityState,
    initialProviderDatasetId,
    initialHasIssue,
  });
  return <AdminFeaturesClientView {...controller} />;
}
