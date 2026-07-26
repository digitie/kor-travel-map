"use client";

import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  GitCompareArrowsIcon,
  ExternalLinkIcon,
  ListChecksIcon,
  ListIcon,
  MapIcon,
  MapPinnedIcon,
  RefreshCwIcon,
  RouteIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { type ColumnDef, type SortingState } from "@tanstack/react-table";

import {
  opsDatasetCatalogOptions,
  useOpsDatasetCatalog,
} from "@/api/datasets";
import {
  ADMIN_FEATURE_STATUSES,
  FEATURE_CLUSTER_MAX_ZOOM,
  FEATURE_KINDS,
  useAdminFeatureClustersInBbox,
  useAdminFeatureDetail,
  useAdminFeaturesInBbox,
  type AdminFeatureMapItem,
  type AdminFeatureStatus,
  type FeatureKind,
} from "@/api/features";
import { useOpsLiveInvalidation } from "@/api/live";
import { AdminShell } from "@/components/admin-shell";
import { FeatureAssociations } from "@/components/feature-associations";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  VWorldFeatureClusters,
  VWorldMapView,
  VWorldServerClusters,
} from "@/components/vworld-map-view";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import {
  DEFAULT_FEATURE_MAP_KINDS,
  useMapStore,
  type FeatureViewMode,
} from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const AREA_GEOMETRY_MIN_ZOOM = 14;

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

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
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
  const dataOrigin = adminDetailQuery.data?.data.feature.data_origin ?? null;

  return (
    <Card
      className="absolute right-3 top-20 z-10 max-h-[calc(100%-5.75rem)] w-[min(24rem,calc(100%-1.5rem))] overflow-auto shadow-lg"
      data-testid="feature-detail-panel"
    >
      <CardHeader className="grid-cols-[1fr_auto]">
        <div>
          <CardTitle>선택 Feature</CardTitle>
          <CardDescription className="break-all font-mono">
            {featureId}
          </CardDescription>
        </div>
        <div className="flex items-center gap-1">
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
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {adminDetailQuery.isLoading ? <Skeleton className="h-48 w-full" /> : null}
        {adminDetailQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상세 호출 실패</AlertTitle>
            <AlertDescription>{adminDetailQuery.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {feature ? (
          <>
            <div className="flex flex-col gap-2">
              <h2 className="text-base font-semibold">{feature.name}</h2>
              <div className="flex flex-wrap gap-2">
                <Badge>{feature.kind}</Badge>
                <Badge variant="secondary">
                  {statusLabel(feature.status)}
                </Badge>
                <Badge variant="outline">{feature.category}</Badge>
              </div>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">coord</dt>
              <dd className="font-mono">
                {typeof feature.lon === "number" && typeof feature.lat === "number"
                  ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                  : "없음"}
              </dd>
              <dt className="text-muted-foreground">sigungu</dt>
              <dd>{feature.sigungu_code ?? "없음"}</dd>
              <dt className="text-muted-foreground">소스</dt>
              <dd className="flex flex-wrap gap-1">
                {adminDetailQuery.isLoading ? (
                  <span className="text-muted-foreground">로딩 중</span>
                ) : adminDetailQuery.isError ? (
                  <span className="text-destructive">조회 실패</span>
                ) : sourceProviders.length > 0 ? (
                  sourceProviders.map((provider) => (
                    <Badge key={provider} variant="outline">
                      {provider}
                    </Badge>
                  ))
                ) : (
                  <span className="text-muted-foreground">없음</span>
                )}
              </dd>
              <dt className="text-muted-foreground">data_origin</dt>
              <dd>
                {adminDetailQuery.isError ? "조회 실패" : dataOrigin ?? "없음"}
              </dd>
            </dl>
            <details>
              <summary className="cursor-pointer text-sm font-medium">address</summary>
              <JsonBlock value={feature.address} />
            </details>
            <FeatureKindDetailPanel
              compact
              feature={feature}
              featureId={featureId}
            />
            {adminDetailQuery.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : adminDetailQuery.data ? (
              <FeatureAssociations
                compact
                curations={adminDetailQuery.data.data.curations}
                observations={adminDetailQuery.data.data.sources}
              />
            ) : null}
            <details>
              <summary className="cursor-pointer text-sm font-medium">detail</summary>
              <JsonBlock value={feature.detail} />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">urls</summary>
              <JsonBlock value={feature.urls} />
            </details>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function FeaturesClient() {
  useOpsLiveInvalidation({ topics: ["feature_update_requests"] });

  const viewport = useMapStore((state) => state.viewport);
  const setViewport = useMapStore((state) => state.setViewport);
  const featureViewMode = useMapStore((state) => state.featureViewMode);
  const setFeatureViewMode = useMapStore((state) => state.setFeatureViewMode);
  const selectedFeatureId = useMapStore((state) => state.selectedFeatureId);
  const setSelectedFeatureId = useMapStore((state) => state.setSelectedFeatureId);
  const activeFeatureKinds = useMapStore((state) => state.activeFeatureKinds);
  const toggleFeatureKind = useMapStore((state) => state.toggleFeatureKind);
  const resetFeatureKinds = useMapStore((state) => state.resetFeatureKinds);

  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [providerFilter, setProviderFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<AdminFeatureStatus | "all">(
    "all",
  );
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
  const clusterMode = viewport.zoom <= FEATURE_CLUSTER_MAX_ZOOM;
  const featuresQuery = useAdminFeaturesInBbox(
    {
      ...(bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 }),
      kinds: kindFilter.length > 0 ? kindFilter : undefined,
      provider: effectiveProvider ? [effectiveProvider] : undefined,
      statuses: statusFilter === "all" ? undefined : [statusFilter],
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
      statuses: statusFilter === "all" ? undefined : [statusFilter],
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
            className="font-medium text-primary underline-offset-4 hover:underline"
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
        cell: ({ row }) => <Badge variant="outline">{row.original.kind}</Badge>,
      },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => statusLabel(row.original.status),
      },
      {
        id: "coord",
        header: "좌표",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <span className="font-mono text-xs text-muted-foreground">
              {typeof feature.lon === "number" && typeof feature.lat === "number"
                ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                : "없음"}
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
    return featuresQuery.isFetching ? `${count}건 표시 · 갱신 중` : `${count}건 표시`;
  }, [bbox, clusterMode, clustersQuery, featuresQuery]);

  // tiled fetch가 일부 tile 잘림/실패를 보고하면(부분 결과) 조용히 누락되지 않도록
  // 작은 affordance를 띄운다(#502 M2). 클러스터 모드는 tiling이 없어 해당 없음.
  const truncated = clusterMode
    ? (clustersQuery.data?.data.truncated ?? false)
    : (featuresQuery.data?.data.truncated ?? false);

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
            href="/ops/pipeline?kind=import_job"
          >
            <ListChecksIcon data-icon="inline-start" />
            Jobs
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/ops/pipeline?kind=update_request"
          >
            <RefreshCwIcon data-icon="inline-start" />
            Update
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/poi-cache-targets"
          >
            <RouteIcon data-icon="inline-start" />
            POI 캐시 대상
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/dedup-reviews"
          >
            <GitCompareArrowsIcon data-icon="inline-start" />
            중복 검토
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/ops/pipeline?tab=schedules"
          >
            <WorkflowIcon data-icon="inline-start" />
            작업 자동화
          </Link>
        </>
      }
      description={status}
      title="Feature 지도"
    >
      <div className="flex min-h-[calc(100vh-12rem)] flex-col rounded-lg border bg-muted/30">
        <div className="flex flex-col gap-3 border-b bg-background px-4 py-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">Feature 지도</Badge>
            <Badge
              variant={
                (clusterMode ? clustersQuery.isError : featuresQuery.isError)
                  ? "destructive"
                  : "outline"
              }
            >
              {status}
            </Badge>
            {truncated ? (
              <Badge
                data-testid="features-partial-indicator"
                title="현재 bbox 결과가 서버 상한에서 잘렸습니다. 더 확대해 범위를 좁히세요."
                variant="destructive"
              >
                부분 결과
              </Badge>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
                  variant={active ? "default" : "outline"}
                  onClick={() => toggleFeatureKind(kind)}
                >
                  {kind}
                </Button>
              );
            })}
            <Button
              disabled={isDefaultKindFilter}
              size="sm"
              type="button"
              variant="outline"
              onClick={resetFeatureKinds}
            >
              <XIcon data-icon="inline-start" />
              초기화
            </Button>
          </div>
          <NativeSelect
            aria-label="상태 필터"
            className="w-40"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as AdminFeatureStatus | "all")
            }
          >
            <NativeSelectOption value="all">모든 운영 상태</NativeSelectOption>
            {ADMIN_FEATURE_STATUSES.map((featureStatus) => (
              <NativeSelectOption key={featureStatus} value={featureStatus}>
                {statusLabel(featureStatus)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="소스 필터"
            className="w-44"
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
        </div>
        </div>

      {!clusterMode && featuresQuery.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>feature 호출 실패</AlertTitle>
          <AlertDescription>{featuresQuery.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {clusterMode && clustersQuery.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>클러스터 호출 실패</AlertTitle>
          <AlertDescription>{clustersQuery.error.message}</AlertDescription>
        </Alert>
      ) : null}

      <Tabs
        className="min-h-0 flex-1 p-4"
        value={featureViewMode}
        onValueChange={(value) => setFeatureViewMode(value as FeatureViewMode)}
      >
        <div className="mb-3 flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="map">
              <MapIcon data-icon="inline-start" />
              지도
            </TabsTrigger>
            <TabsTrigger value="table">
              <ListIcon data-icon="inline-start" />
              테이블
            </TabsTrigger>
          </TabsList>
          <span className="text-sm text-muted-foreground">
            center {viewport.lon.toFixed(4)}, {viewport.lat.toFixed(4)} · z{" "}
            {viewport.zoom.toFixed(1)}
          </span>
        </div>

        <TabsContent className="min-h-0" value="map">
          <Card className="relative h-[calc(100vh-22rem)] min-h-[28rem] overflow-hidden p-0">
            <div
              className="absolute inset-0 h-full w-full"
              style={{
                height: "100%",
                inset: 0,
                position: "absolute",
                width: "100%",
              }}
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
              {clusterMode ? (
                <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md bg-background/90 px-2 py-1 text-xs text-muted-foreground shadow-sm">
                  지역 클러스터 뷰 · 확대하면 개별 feature가 표시됩니다
                </div>
              ) : null}
            </div>
            {selectedFeatureId ? (
              <FeatureDetailPanel
                featureId={selectedFeatureId}
                onClose={() => setSelectedFeatureId(null)}
              />
            ) : null}
          </Card>
        </TabsContent>

        <TabsContent value="table">
          <Card className="h-[calc(100vh-22rem)] min-h-[28rem] overflow-hidden">
            <CardHeader>
              <CardTitle>이름순 feature</CardTitle>
              <CardDescription>
                현재 bbox와 kind 필터에 해당하는 feature를 이름순으로 표시합니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="min-h-0">
              {clusterMode ? (
                <div className="flex h-[calc(100vh-28rem)] min-h-80 items-center justify-center px-6 text-center text-sm text-muted-foreground">
                  저zoom에서는 개별 feature 대신 지역 클러스터로 집계됩니다. 지도를
                  확대(zoom {FEATURE_CLUSTER_MAX_ZOOM + 1}+)하면 개별 feature 목록이
                  표시됩니다.
                </div>
              ) : (
                <DataTable
                  columns={featureColumns}
                  data={featureItems}
                  getRowId={(feature) => feature.feature_id}
                  isLoading={featuresQuery.isLoading}
                  emptyMessage="표시할 feature가 없습니다."
                  onRowClick={(feature) => setSelectedFeatureId(feature.feature_id)}
                  isRowActive={(feature) =>
                    feature.feature_id === selectedFeatureId
                  }
                  sorting={tableSorting}
                  onSortingChange={setTableSorting}
                  manualSorting={false}
                  virtualized
                  estimateRowSize={41}
                  containerClassName="h-[calc(100vh-28rem)] min-h-80"
                  ariaLabel="이름순 feature"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {!isVWorldApiKeyConfigured(VWORLD_KEY) ? (
        <Alert className="mx-4 mb-4">
          <AlertTitle>VWorld key 미설정</AlertTitle>
          <AlertDescription>
            NEXT_PUBLIC_VWORLD_API_KEY 미설정 상태라 회색 배경으로 표시합니다.
            마커와 bbox 조회는 계속 동작합니다.
          </AlertDescription>
        </Alert>
      ) : null}
      </div>
    </AdminShell>
  );
}
