"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (map) · design-system: design.md · designed-as-app

import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ExternalLinkIcon,
  GitCompareArrowsIcon,
  ListIcon,
  MapIcon,
  MapPinnedIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { type ColumnDef, type SortingState } from "@tanstack/react-table";

import { opsDatasetCatalogOptions, useOpsDatasetCatalog } from "@/api/datasets";
import {
  FEATURE_CLUSTER_MAX_ZOOM,
  FEATURE_KINDS,
  FEATURE_LIFECYCLE_STATES,
  FEATURE_PUBLICATION_STATES,
  FEATURE_QUALITY_STATES,
  featureStateLabel,
  isAdminFeatureClusterZoom,
  useAdminFeatureClustersInBbox,
  useAdminFeatureDetail,
  useAdminFeaturesInBbox,
  type AdminFeatureMapItem,
  type FeatureKind,
  type FeatureLifecycleState,
  type FeaturePublicationState,
  type FeatureQualityState,
} from "@/api/features";
import { useOpsLiveInvalidation } from "@/api/live";
import { AdminShell } from "@/components/admin-shell";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { FeatureAssociations } from "@/components/feature-associations";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { JsonViewer } from "@/components/json-viewer";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card } from "@/components/ui/card";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  VWorldFeatureClusters,
  VWorldMapView,
  VWorldServerClusters,
} from "@/components/vworld-map-view";
import { NULL_GLYPH } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import {
  DEFAULT_FEATURE_MAP_KINDS,
  useMapStore,
  type FeatureViewMode,
} from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const AREA_GEOMETRY_MIN_ZOOM = 14;
type AxisFilter<T extends string> = "" | T;

/** 지도/테이블 작업면 높이 — 헤더·툴바를 뺀 뷰포트 비율(고정 rem 오프셋 금지, m6). */
const WORKSPACE_HEIGHT_CLASS = "h-[70dvh] min-h-[28rem]";

interface Bbox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

function boundsToBbox(bounds: LngLatBounds): Bbox {
  return {
    min_lon: bounds.getWest(),
    min_lat: bounds.getSouth(),
    max_lon: bounds.getEast(),
    max_lat: bounds.getNorth(),
  };
}

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

/** 필터 툴바 안 접이식 payload 블록(주소/상세/URL) — 제목은 12px/500, 본문은 JsonViewer. */
function PayloadDisclosure({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  return (
    <details className="group/details">
      <summary className="inline-flex h-control-sm cursor-pointer list-none items-center gap-1 rounded-control text-xs font-medium text-text-secondary outline-none select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
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

function FeatureDetailPanel({
  featureId,
  onClose,
}: {
  featureId: string;
  onClose: () => void;
}) {
  const adminDetailQuery = useAdminFeatureDetail(featureId);
  const feature = adminDetailQuery.data?.data.feature;
  const sourceProviders = useMemo(() => {
    const sources = adminDetailQuery.data?.data.sources ?? [];
    return Array.from(new Set(sources.map((source) => source.provider))).sort();
  }, [adminDetailQuery.data]);

  const coordinate =
    feature && typeof feature.lon === "number" && typeof feature.lat === "number"
      ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
      : null;

  return (
    <Card
      className="absolute top-20 right-3 bottom-24 z-10 w-[min(var(--rail),calc(100%-1.5rem))] gap-3 overflow-auto p-4 shadow-elevated"
      data-testid="feature-detail-panel"
      size="sm"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border pb-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-2xs font-medium text-text-secondary">선택 Feature</span>
          <span className="font-mono text-xs break-all text-text-primary slashed-zero">
            {featureId}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Link
            aria-label="상세 열기"
            className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
            href={featureDetailHref(featureId)}
          >
            <ExternalLinkIcon />
          </Link>
          <Button
            aria-label="닫기"
            size="icon-sm"
            type="button"
            variant="ghost"
            onClick={onClose}
          >
            <XIcon />
          </Button>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {adminDetailQuery.isLoading ? (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : null}
        {adminDetailQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상세 호출 실패</AlertTitle>
            <AlertDescription>
              {adminDetailQuery.error.message} — 다시 선택하거나 새로고침하세요.
            </AlertDescription>
          </Alert>
        ) : null}
        {feature ? (
          <>
            <div className="flex flex-col gap-2">
              <h2 className="text-md leading-snug font-semibold text-text-primary">
                {feature.name}
              </h2>
              <div className="flex flex-wrap gap-1">
                <Badge variant="neutral">{feature.kind}</Badge>
                <FeatureStateBadges
                  lifecycleState={feature.lifecycle_state}
                  publicationState={feature.publication_state}
                  qualityState={feature.quality_state}
                />
                <Badge variant="outline">{feature.category}</Badge>
              </div>
            </div>
            <DetailList
              items={[
                { label: "좌표", value: coordinate, mono: true },
                { label: "시군구", value: feature.sigungu_code ?? null, mono: true },
                {
                  label: "소스",
                  value: adminDetailQuery.isError ? (
                    <span className="text-destructive">조회 실패</span>
                  ) : sourceProviders.length > 0 ? (
                    <span className="flex flex-wrap gap-1">
                      {sourceProviders.map((provider) => (
                        <Badge key={provider} variant="outline">
                          {provider}
                        </Badge>
                      ))}
                    </span>
                  ) : null,
                },
              ]}
              layout="inline"
            />
            <PayloadDisclosure label="주소(address)" value={feature.address} />
            <FeatureKindDetailPanel
              compact
              feature={feature}
              featureId={featureId}
            />
            {adminDetailQuery.data ? (
              <FeatureAssociations
                compact
                curations={adminDetailQuery.data.data.curations}
                observations={adminDetailQuery.data.data.sources}
              />
            ) : null}
            <PayloadDisclosure label="상세(detail)" value={feature.detail} />
            <PayloadDisclosure label="URL(urls)" value={feature.urls} />
          </>
        ) : null}
      </div>
    </Card>
  );
}

function useFeaturesClientController() {
  useOpsLiveInvalidation({ topics: ["feature_update_requests"] });

  const viewport = useMapStore((state) => state.viewport);
  const setViewport = useMapStore((state) => state.setViewport);
  const featureViewMode = useMapStore((state) => state.featureViewMode);
  const setFeatureViewMode = useMapStore((state) => state.setFeatureViewMode);
  const selectedFeatureId = useMapStore((state) => state.selectedFeatureId);
  const setSelectedFeatureId = useMapStore(
    (state) => state.setSelectedFeatureId,
  );
  const activeFeatureKinds = useMapStore((state) => state.activeFeatureKinds);
  const toggleFeatureKind = useMapStore((state) => state.toggleFeatureKind);
  const resetFeatureKinds = useMapStore((state) => state.resetFeatureKinds);

  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [providerFilter, setProviderFilter] = useState<string>("");
  const [lifecycleStateFilter, setLifecycleStateFilter] =
    useState<AxisFilter<FeatureLifecycleState>>("");
  const [publicationStateFilter, setPublicationStateFilter] =
    useState<AxisFilter<FeaturePublicationState>>("");
  const [qualityStateFilter, setQualityStateFilter] =
    useState<AxisFilter<FeatureQualityState>>("");
  const kindFilter = useMemo(
    () => Array.from(activeFeatureKinds) as FeatureKind[],
    [activeFeatureKinds],
  );
  const isDefaultKindFilter =
    activeFeatureKinds.size === DEFAULT_FEATURE_MAP_KINDS.length &&
    DEFAULT_FEATURE_MAP_KINDS.every((kind) => activeFeatureKinds.has(kind));

  // 소스(provider) 필터 옵션: feature 선택 시 그 feature가 묶인 provider만, 아니면
  // 전체 provider 목록. 선택이 바뀌어 현재 값이 옵션에 없으면 "모두 보기"로 되돌린다.
  const datasetsQuery = useOpsDatasetCatalog();
  const selectedFeatureAdminDetail = useAdminFeatureDetail(selectedFeatureId);
  const providerOptions = useMemo<string[]>(() => {
    if (selectedFeatureId) {
      const sources = selectedFeatureAdminDetail.data?.data.sources ?? [];
      return Array.from(
        new Set(sources.map((source) => source.provider)),
      ).sort();
    }
    return opsDatasetCatalogOptions(datasetsQuery.data?.data.items ?? []).map(
      (entry) => entry.provider,
    );
  }, [selectedFeatureId, selectedFeatureAdminDetail.data, datasetsQuery.data]);

  // 선택이 바뀌어 저장된 값이 현재 옵션에 없으면, effect로 setState하지 않고
  // 렌더 시점에 "모두 보기"(빈 값)로 환원한다 (react-hooks/set-state-in-effect 회피).
  const effectiveProvider =
    providerFilter && providerOptions.includes(providerFilter)
      ? providerFilter
      : "";
  const includeFeatureGeometry =
    kindFilter.length === 0 ||
    kindFilter.includes("route") ||
    (kindFilter.includes("area") && viewport.zoom >= AREA_GEOMETRY_MIN_ZOOM);
  const showAreaGeometry = viewport.zoom >= AREA_GEOMETRY_MIN_ZOOM;

  // 저zoom(≤13)에선 개별 feature를 tile로 대량 조회하지 않고 서버측 region 클러스터를
  // 쓴다(#649). 개별 fetch와 클러스터 fetch는 zoom에 따라 상호 배타적으로 enable된다.
  const clusterMode = isAdminFeatureClusterZoom(viewport.zoom);
  const featuresQuery = useAdminFeaturesInBbox(
    {
      ...(bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 }),
      kinds: kindFilter.length > 0 ? kindFilter : undefined,
      provider: effectiveProvider ? [effectiveProvider] : undefined,
      lifecycleStates: lifecycleStateFilter
        ? [lifecycleStateFilter]
        : undefined,
      publicationStates: publicationStateFilter
        ? [publicationStateFilter]
        : undefined,
      qualityStates: qualityStateFilter ? [qualityStateFilter] : undefined,
      includeGeometry: includeFeatureGeometry,
      zoom: viewport.zoom,
    },
    { enabled: bbox !== null && !clusterMode },
  );
  const clustersQuery = useAdminFeatureClustersInBbox(
    {
      ...(bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 }),
      kinds: kindFilter.length > 0 ? kindFilter : undefined,
      provider: effectiveProvider ? [effectiveProvider] : undefined,
      lifecycleStates: lifecycleStateFilter
        ? [lifecycleStateFilter]
        : undefined,
      publicationStates: publicationStateFilter
        ? [publicationStateFilter]
        : undefined,
      qualityStates: qualityStateFilter ? [qualityStateFilter] : undefined,
      zoom: viewport.zoom,
    },
    { enabled: bbox !== null && clusterMode },
  );
  const clusterItems = clustersQuery.data?.data.clusters ?? [];

  const updateViewportFromMap = useCallback(
    (map: MapLibreMap) => {
      const center = map.getCenter();
      setViewport({
        lon: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
      });
      setBbox(boundsToBbox(map.getBounds()));
    },
    [setViewport],
  );

  const featureItems = featuresQuery.data?.data.items ?? [];
  const [tableSorting, setTableSorting] = useState<SortingState>([
    { id: "name", desc: false },
  ]);
  const featureColumns = useMemo<ColumnDef<AdminFeatureMapItem, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "이름",
        sortingFn: (rowA, rowB) =>
          rowA.original.name.localeCompare(rowB.original.name, "ko"),
        cell: ({ row }) => (
          <Link
            className="rounded-control font-medium text-brand underline-offset-4 outline-none hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            href={featureDetailHref(row.original.feature_id)}
            onClick={(event) => event.stopPropagation()}
          >
            {row.original.name}
          </Link>
        ),
      },
      {
        accessorKey: "kind",
        header: "종류",
        cell: ({ row }) => <Badge variant="neutral">{row.original.kind}</Badge>,
      },
      {
        id: "state",
        header: "상태 축",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            <FeatureStateBadges
              lifecycleState={row.original.lifecycle_state}
              publicationState={row.original.publication_state}
              qualityState={row.original.quality_state}
            />
          </div>
        ),
      },
      {
        id: "coord",
        header: "좌표",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const { lon, lat } = row.original;
          const coordinate =
            typeof lon === "number" && typeof lat === "number"
              ? `${lon.toFixed(5)}, ${lat.toFixed(5)}`
              : null;
          return (
            <span
              className={cn(
                "font-mono text-xs slashed-zero",
                coordinate !== null ? "text-text-secondary" : "text-text-tertiary",
              )}
            >
              {coordinate ?? NULL_GLYPH}
            </span>
          );
        },
      },
    ],
    [],
  );

  const status = useMemo(() => {
    if (!bbox) return "지도 로딩 중";
    if (clusterMode) {
      if (clustersQuery.isLoading) return "클러스터 로딩 중";
      if (clustersQuery.isError) return "클러스터 호출 실패";
      const regions = clustersQuery.data?.data.clusters.length ?? 0;
      const total = (clustersQuery.data?.data.clusters ?? []).reduce(
        (sum, cluster) => sum + cluster.feature_count,
        0,
      );
      const label = `${regions}개 지역 · ${total.toLocaleString("ko")}건 집계`;
      return clustersQuery.isFetching ? `${label} · 갱신 중` : label;
    }
    if (featuresQuery.isLoading) return "feature 로딩 중";
    if (featuresQuery.isError) return "feature 호출 실패";
    const count = featuresQuery.data?.data.items.length ?? 0;
    return featuresQuery.isFetching
      ? `${count}건 표시 · 갱신 중`
      : `${count}건 표시`;
  }, [bbox, clusterMode, clustersQuery, featuresQuery]);

  // tiled fetch가 일부 tile 잘림/실패를 보고하면(부분 결과) 조용히 누락되지 않도록
  // 작은 affordance를 띄운다(#502 M2). 클러스터 모드는 tiling이 없어 해당 없음.
  const truncated = clusterMode
    ? (clustersQuery.data?.data.truncated ?? false)
    : (featuresQuery.data?.data.truncated ?? false);

  return {
    activeFeatureKinds,
    clusterItems,
    clusterMode,
    clustersQuery,
    effectiveProvider,
    featureColumns,
    featureItems,
    featureViewMode,
    featuresQuery,
    isDefaultKindFilter,
    lifecycleStateFilter,
    providerOptions,
    publicationStateFilter,
    qualityStateFilter,
    resetFeatureKinds,
    selectedFeatureId,
    setFeatureViewMode,
    setLifecycleStateFilter,
    setProviderFilter,
    setPublicationStateFilter,
    setQualityStateFilter,
    setSelectedFeatureId,
    setTableSorting,
    showAreaGeometry,
    status,
    tableSorting,
    toggleFeatureKind,
    truncated,
    updateViewportFromMap,
    viewport,
  };
}

const filterLabelClass = "text-2xs leading-none font-medium text-text-secondary";

function FeatureMapToolbar({
  activeFeatureKinds,
  clusterMode,
  clustersQuery,
  effectiveProvider,
  featuresQuery,
  isDefaultKindFilter,
  lifecycleStateFilter,
  providerOptions,
  publicationStateFilter,
  qualityStateFilter,
  resetFeatureKinds,
  setLifecycleStateFilter,
  setProviderFilter,
  setPublicationStateFilter,
  setQualityStateFilter,
  status,
  toggleFeatureKind,
  truncated,
}: Pick<
  ReturnType<typeof useFeaturesClientController>,
  | "activeFeatureKinds"
  | "clusterMode"
  | "clustersQuery"
  | "effectiveProvider"
  | "featuresQuery"
  | "isDefaultKindFilter"
  | "lifecycleStateFilter"
  | "providerOptions"
  | "publicationStateFilter"
  | "qualityStateFilter"
  | "resetFeatureKinds"
  | "setLifecycleStateFilter"
  | "setProviderFilter"
  | "setPublicationStateFilter"
  | "setQualityStateFilter"
  | "status"
  | "toggleFeatureKind"
  | "truncated"
>) {
  const queryFailed = clusterMode ? clustersQuery.isError : featuresQuery.isError;
  return (
    <div className="flex flex-col gap-3">
      <FilterBar>
        <div className="flex min-w-0 flex-col gap-1">
          <span aria-hidden="true" className={filterLabelClass}>
            종류
          </span>
          <div
            aria-label="kind 필터"
            className="flex flex-wrap gap-1"
            data-testid="kind-filter"
            role="group"
          >
            {FEATURE_KINDS.map((kind) => {
              const active = activeFeatureKinds.has(kind);
              return (
                <Button
                  aria-pressed={active}
                  key={kind}
                  size="sm"
                  type="button"
                  variant={active ? "secondary" : "outline"}
                  onClick={() => toggleFeatureKind(kind)}
                >
                  {kind}
                </Button>
              );
            })}
            <Button
              disabled={isDefaultKindFilter}
              disabledReason="기본 종류(weather·notice)만 선택된 상태입니다"
              size="sm"
              type="button"
              variant="ghost"
              onClick={resetFeatureKinds}
            >
              <XIcon data-icon="inline-start" />
              초기화
            </Button>
          </div>
        </div>
        <FilterField htmlFor="feature-provider-filter" label="소스">
          <NativeSelect
            aria-label="소스 필터"
            className="w-44"
            id="feature-provider-filter"
            size="sm"
            value={effectiveProvider}
            onChange={(event) => setProviderFilter(event.target.value)}
          >
            <NativeSelectOption value="">모두 보기</NativeSelectOption>
            {providerOptions.map((provider) => (
              <NativeSelectOption key={provider} value={provider}>
                {provider}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
        <FilterField htmlFor="feature-lifecycle-filter" label="수명주기">
          <NativeSelect
            aria-label="수명주기 필터"
            className="w-36"
            id="feature-lifecycle-filter"
            size="sm"
            value={lifecycleStateFilter}
            onChange={(event) =>
              setLifecycleStateFilter(
                event.target.value as AxisFilter<FeatureLifecycleState>,
              )
            }
          >
            <NativeSelectOption value="">모든 수명주기</NativeSelectOption>
            {FEATURE_LIFECYCLE_STATES.map((value) => (
              <NativeSelectOption key={value} value={value}>
                {featureStateLabel("lifecycle", value)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
        <FilterField htmlFor="feature-publication-filter" label="공개 상태">
          <NativeSelect
            aria-label="공개 상태 필터"
            className="w-36"
            id="feature-publication-filter"
            size="sm"
            value={publicationStateFilter}
            onChange={(event) =>
              setPublicationStateFilter(
                event.target.value as AxisFilter<FeaturePublicationState>,
              )
            }
          >
            <NativeSelectOption value="">모든 공개 상태</NativeSelectOption>
            {FEATURE_PUBLICATION_STATES.map((value) => (
              <NativeSelectOption key={value} value={value}>
                {featureStateLabel("publication", value)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
        <FilterField htmlFor="feature-quality-filter" label="품질 상태">
          <NativeSelect
            aria-label="품질 상태 필터"
            className="w-36"
            id="feature-quality-filter"
            size="sm"
            value={qualityStateFilter}
            onChange={(event) =>
              setQualityStateFilter(
                event.target.value as AxisFilter<FeatureQualityState>,
              )
            }
          >
            <NativeSelectOption value="">모든 품질 상태</NativeSelectOption>
            {FEATURE_QUALITY_STATES.map((value) => (
              <NativeSelectOption key={value} value={value}>
                {featureStateLabel("quality", value)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
      </FilterBar>

      {!clusterMode && featuresQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>feature 호출 실패</AlertTitle>
          <AlertDescription>
            {featuresQuery.error.message} — 지도를 조금 움직이거나 필터를 바꾸면 다시
            조회합니다.
          </AlertDescription>
        </Alert>
      ) : null}
      {clusterMode && clustersQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>클러스터 호출 실패</AlertTitle>
          <AlertDescription>
            {clustersQuery.error.message} — 지도를 조금 움직이거나 필터를 바꾸면 다시
            조회합니다.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={queryFailed ? "destructive" : "neutral"}>{status}</Badge>
        {truncated ? (
          <Badge
            data-testid="features-partial-indicator"
            title="현재 bbox 결과가 서버 상한에서 잘렸습니다. 더 확대해 범위를 좁히세요."
            variant="warning"
          >
            부분 결과
          </Badge>
        ) : null}
        {truncated ? (
          <span className="text-2xs text-text-secondary">
            결과가 서버 상한에서 잘렸습니다 — 더 확대해 범위를 좁히세요.
          </span>
        ) : null}
      </div>
    </div>
  );
}

function FeatureMapWorkspace({
  clusterItems,
  clusterMode,
  featureColumns,
  featureItems,
  featureViewMode,
  featuresQuery,
  selectedFeatureId,
  setFeatureViewMode,
  setSelectedFeatureId,
  setTableSorting,
  showAreaGeometry,
  tableSorting,
  updateViewportFromMap,
  viewport,
}: Pick<
  ReturnType<typeof useFeaturesClientController>,
  | "clusterItems"
  | "clusterMode"
  | "featureColumns"
  | "featureItems"
  | "featureViewMode"
  | "featuresQuery"
  | "selectedFeatureId"
  | "setFeatureViewMode"
  | "setSelectedFeatureId"
  | "setTableSorting"
  | "showAreaGeometry"
  | "tableSorting"
  | "updateViewportFromMap"
  | "viewport"
>) {
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        className="min-h-0"
        value={featureViewMode}
        onValueChange={(value) => setFeatureViewMode(value as FeatureViewMode)}
      >
        <TabsList aria-label="보기 전환">
          <TabsTrigger value="map">
            <MapIcon data-icon="inline-start" />
            지도
          </TabsTrigger>
          <TabsTrigger value="table">
            <ListIcon data-icon="inline-start" />
            테이블
          </TabsTrigger>
        </TabsList>

        <TabsContent className="min-h-0" value="map">
          <div
            className={cn(
              "relative overflow-hidden rounded-panel border border-border bg-surface-subtle",
              WORKSPACE_HEIGHT_CLASS,
            )}
          >
            <VWorldMapView
              apiKey={VWORLD_KEY}
              center={[viewport.lon, viewport.lat]}
              className="absolute inset-0 h-full w-full"
              navigation
              scale
              testId="map-canvas-container"
              zoom={viewport.zoom}
              onLoad={updateViewportFromMap}
              onMoveEnd={updateViewportFromMap}
            >
              {clusterMode ? (
                <VWorldServerClusters clusters={clusterItems} />
              ) : (
                <VWorldFeatureClusters
                  features={featureItems}
                  selectedFeatureId={selectedFeatureId}
                  showAreaGeometry={showAreaGeometry}
                  onSelectFeature={setSelectedFeatureId}
                />
              )}
            </VWorldMapView>
            {/* 지도 위 flat status strip: 좌표 readout(mono) + 클러스터 안내 — 프레임 없는 칩(m6). */}
            <div className="pointer-events-none absolute top-3 left-3 z-10 flex max-w-[calc(100%-6rem)] flex-col items-start gap-1">
              <span className="rounded-control border border-border bg-card px-2 py-1 font-mono text-2xs text-text-secondary tabular-nums">
                {viewport.lon.toFixed(4)}, {viewport.lat.toFixed(4)} · z{" "}
                {viewport.zoom.toFixed(1)}
              </span>
              {clusterMode ? (
                <span className="rounded-control border border-border bg-card px-2 py-1 text-2xs text-text-secondary">
                  지역 클러스터 뷰 · 확대하면 개별 feature가 표시됩니다
                </span>
              ) : null}
            </div>
            {selectedFeatureId ? (
              <FeatureDetailPanel
                featureId={selectedFeatureId}
                onClose={() => setSelectedFeatureId(null)}
              />
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="table">
          {clusterMode ? (
            <EmptyState
              description={`지도를 확대(zoom ${FEATURE_CLUSTER_MAX_ZOOM + 1}+)하면 개별 feature 목록이 표시됩니다.`}
              framed
              title="저zoom에서는 개별 feature 대신 지역 클러스터로 집계됩니다."
            />
          ) : (
            <DataTable
              ariaLabel="이름순 feature"
              columns={featureColumns}
              containerClassName={WORKSPACE_HEIGHT_CLASS}
              data={featureItems}
              emptyState={{
                title: "표시할 feature가 없습니다.",
                description:
                  "현재 지도 범위와 종류·소스·상태 축 필터에 맞는 feature가 없습니다 — 지도를 이동하거나 필터를 넓혀 보세요.",
              }}
              estimateRowSize={41}
              getRowId={(feature) => feature.feature_id}
              isLoading={featuresQuery.isLoading}
              isRowActive={(feature) =>
                feature.feature_id === selectedFeatureId
              }
              manualSorting={false}
              onRowClick={(feature) =>
                setSelectedFeatureId(feature.feature_id)
              }
              onSortingChange={setTableSorting}
              sorting={tableSorting}
              virtualized
            />
          )}
        </TabsContent>
      </Tabs>

      {!isVWorldApiKeyConfigured(VWORLD_KEY) ? (
        <Alert>
          <AlertTitle>VWorld key 미설정</AlertTitle>
          <AlertDescription>
            NEXT_PUBLIC_VWORLD_API_KEY 미설정 상태라 회색 배경으로 표시합니다.
            마커와 bbox 조회는 계속 동작합니다.
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

function FeaturesClientView({
  activeFeatureKinds,
  clusterItems,
  clusterMode,
  clustersQuery,
  effectiveProvider,
  featureColumns,
  featureItems,
  featureViewMode,
  featuresQuery,
  isDefaultKindFilter,
  lifecycleStateFilter,
  providerOptions,
  publicationStateFilter,
  qualityStateFilter,
  resetFeatureKinds,
  selectedFeatureId,
  setFeatureViewMode,
  setLifecycleStateFilter,
  setProviderFilter,
  setPublicationStateFilter,
  setQualityStateFilter,
  setSelectedFeatureId,
  setTableSorting,
  showAreaGeometry,
  status,
  tableSorting,
  toggleFeatureKind,
  truncated,
  updateViewportFromMap,
  viewport,
}: ReturnType<typeof useFeaturesClientController>) {
  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/curated-features"
          >
            <MapPinnedIcon data-icon="inline-start" />
            큐레이션 지도
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/dedup-reviews"
          >
            <GitCompareArrowsIcon data-icon="inline-start" />
            중복 검토
          </Link>
        </>
      }
      description="현재 지도 범위의 feature를 종류·소스·상태 축으로 걸러 지도와 테이블로 봅니다."
      title="Feature 지도"
    >
      <div className="flex flex-col gap-4">
        <FeatureMapToolbar
          activeFeatureKinds={activeFeatureKinds}
          clusterMode={clusterMode}
          clustersQuery={clustersQuery}
          effectiveProvider={effectiveProvider}
          featuresQuery={featuresQuery}
          isDefaultKindFilter={isDefaultKindFilter}
          lifecycleStateFilter={lifecycleStateFilter}
          providerOptions={providerOptions}
          publicationStateFilter={publicationStateFilter}
          qualityStateFilter={qualityStateFilter}
          resetFeatureKinds={resetFeatureKinds}
          setLifecycleStateFilter={setLifecycleStateFilter}
          setProviderFilter={setProviderFilter}
          setPublicationStateFilter={setPublicationStateFilter}
          setQualityStateFilter={setQualityStateFilter}
          status={status}
          toggleFeatureKind={toggleFeatureKind}
          truncated={truncated}
        />

        <FeatureMapWorkspace
          clusterItems={clusterItems}
          clusterMode={clusterMode}
          featureColumns={featureColumns}
          featureItems={featureItems}
          featureViewMode={featureViewMode}
          featuresQuery={featuresQuery}
          selectedFeatureId={selectedFeatureId}
          setFeatureViewMode={setFeatureViewMode}
          setSelectedFeatureId={setSelectedFeatureId}
          setTableSorting={setTableSorting}
          showAreaGeometry={showAreaGeometry}
          tableSorting={tableSorting}
          updateViewportFromMap={updateViewportFromMap}
          viewport={viewport}
        />
      </div>
    </AdminShell>
  );
}

export function FeaturesClient() {
  const controller = useFeaturesClientController();
  return <FeaturesClientView {...controller} />;
}
