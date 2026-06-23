"use client";

import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  GitCompareArrowsIcon,
  ExternalLinkIcon,
  ListChecksIcon,
  ListIcon,
  MapIcon,
  RefreshCwIcon,
  RouteIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { type ColumnDef, type SortingState } from "@tanstack/react-table";

import {
  FEATURE_KINDS,
  useFeatureDetail,
  useFeaturesInBbox,
  type FeatureKind,
  type FeatureSummary,
} from "@/api/features";
import { FeatureWeatherPanel } from "@/components/feature-weather-panel";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  VWorldFeatureClusters,
  VWorldMapView,
} from "@/components/vworld-map-view";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { useMapStore, type FeatureViewMode } from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

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
  const detailQuery = useFeatureDetail(featureId);

  return (
    <Card
      className="absolute right-3 top-3 z-10 max-h-[calc(100%-1.5rem)] w-[min(24rem,calc(100%-1.5rem))] overflow-auto shadow-lg"
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
        {detailQuery.isLoading ? <Skeleton className="h-48 w-full" /> : null}
        {detailQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>상세 호출 실패</AlertTitle>
            <AlertDescription>{detailQuery.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {detailQuery.data ? (
          <>
            <div className="flex flex-col gap-2">
              <h2 className="text-base font-semibold">{detailQuery.data.name}</h2>
              <div className="flex flex-wrap gap-2">
                <Badge>{detailQuery.data.kind}</Badge>
                <Badge variant="secondary">{detailQuery.data.status}</Badge>
                <Badge variant="outline">{detailQuery.data.category}</Badge>
              </div>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">coord</dt>
              <dd className="font-mono">
                {typeof detailQuery.data.lon === "number" &&
                typeof detailQuery.data.lat === "number"
                  ? `${detailQuery.data.lon.toFixed(5)}, ${detailQuery.data.lat.toFixed(5)}`
                  : "없음"}
              </dd>
              <dt className="text-muted-foreground">sigungu</dt>
              <dd>{detailQuery.data.sigungu_code ?? "없음"}</dd>
            </dl>
            <details>
              <summary className="cursor-pointer text-sm font-medium">address</summary>
              <JsonBlock value={detailQuery.data.address} />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">detail</summary>
              <JsonBlock value={detailQuery.data.detail} />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">urls</summary>
              <JsonBlock value={detailQuery.data.urls} />
            </details>
            <FeatureWeatherPanel compact featureId={featureId} />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function FeaturesClient() {
  const viewport = useMapStore((state) => state.viewport);
  const setViewport = useMapStore((state) => state.setViewport);
  const featureViewMode = useMapStore((state) => state.featureViewMode);
  const setFeatureViewMode = useMapStore((state) => state.setFeatureViewMode);
  const selectedFeatureId = useMapStore((state) => state.selectedFeatureId);
  const setSelectedFeatureId = useMapStore((state) => state.setSelectedFeatureId);
  const activeFeatureKinds = useMapStore((state) => state.activeFeatureKinds);
  const toggleFeatureKind = useMapStore((state) => state.toggleFeatureKind);
  const clearFeatureKinds = useMapStore((state) => state.clearFeatureKinds);

  const [bbox, setBbox] = useState<Bbox | null>(null);
  const kindFilter = useMemo(
    () => Array.from(activeFeatureKinds) as FeatureKind[],
    [activeFeatureKinds],
  );

  const featuresQuery = useFeaturesInBbox(
    {
      ...(bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 }),
      kinds: kindFilter.length > 0 ? kindFilter : undefined,
      // 서버 in-bounds 파라미터는 `page_size`(최대 500). 과거엔 `limit`을 보내
      // 서버가 무시 → 항상 기본 100건만 표시됐다(110만 중 100개, 필터 체감 약함).
      includeGeometry: true,
      page_size: 500,
      zoom: viewport.zoom,
    },
    { enabled: bbox !== null },
  );

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
  const featureColumns = useMemo<ColumnDef<FeatureSummary, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "name",
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
        header: "kind",
        cell: ({ row }) => <Badge variant="outline">{row.original.kind}</Badge>,
      },
      { accessorKey: "status", header: "status" },
      {
        id: "coord",
        header: "coord",
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
    if (featuresQuery.isLoading) return "feature 로딩 중";
    if (featuresQuery.isError) return "feature 호출 실패";
    return `${featuresQuery.data?.data.items.length ?? 0}건 표시`;
  }, [bbox, featuresQuery]);

  return (
    <main className="flex h-screen flex-col bg-muted/30">
      <header className="flex flex-col gap-3 border-b bg-background px-6 py-4 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">Features</Badge>
            <Badge variant={featuresQuery.isError ? "destructive" : "outline"}>
              {status}
            </Badge>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Feature 지도</h1>
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
            {activeFeatureKinds.size > 0 ? (
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={clearFeatureKinds}
              >
                초기화
              </Button>
            ) : null}
          </div>
          <Link className={cn(buttonVariants({ variant: "outline" }))} href="/">
            홈
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/ops/import-jobs"
          >
            <ListChecksIcon data-icon="inline-start" />
            Jobs
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/feature-update-requests"
          >
            <RefreshCwIcon data-icon="inline-start" />
            Update
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/poi-cache-targets"
          >
            <RouteIcon data-icon="inline-start" />
            Targets
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/dedup-reviews"
          >
            <GitCompareArrowsIcon data-icon="inline-start" />
            Dedup
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/dagster"
          >
            <WorkflowIcon data-icon="inline-start" />
            Dagster
          </Link>
        </div>
      </header>

      {featuresQuery.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>feature 호출 실패</AlertTitle>
          <AlertDescription>{featuresQuery.error.message}</AlertDescription>
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
          <Card className="relative h-[calc(100vh-12.5rem)] overflow-hidden p-0">
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
                testId="map-canvas-container"
                zoom={viewport.zoom}
                onLoad={updateViewportFromMap}
                onMoveEnd={updateViewportFromMap}
              >
                <VWorldFeatureClusters
                  features={featureItems}
                  onSelectFeature={setSelectedFeatureId}
                />
              </VWorldMapView>
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
          <Card className="h-[calc(100vh-12.5rem)] overflow-hidden">
            <CardHeader>
              <CardTitle>이름순 feature</CardTitle>
              <CardDescription>
                현재 bbox와 kind 필터에 해당하는 feature를 이름순으로 표시합니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="min-h-0">
              <DataTable
                columns={featureColumns}
                data={featureItems}
                getRowId={(feature) => feature.feature_id}
                isLoading={featuresQuery.isLoading}
                emptyMessage="표시할 feature가 없습니다."
                onRowClick={(feature) => setSelectedFeatureId(feature.feature_id)}
                isRowActive={(feature) => feature.feature_id === selectedFeatureId}
                sorting={tableSorting}
                onSortingChange={setTableSorting}
                virtualized
                estimateRowSize={41}
                containerClassName="h-[calc(100vh-19rem)]"
                ariaLabel="이름순 feature"
              />
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
    </main>
  );
}
