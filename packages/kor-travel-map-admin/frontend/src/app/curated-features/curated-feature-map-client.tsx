"use client";

import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ExternalLinkIcon,
  ListIcon,
  MapIcon,
  SparklesIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useDeferredValue,
  useMemo,
  useState,
} from "react";

import { type ColumnDef, type SortingState } from "@tanstack/react-table";

import {
  useAdminCuratedFeature,
  useAdminCuratedFeatures,
  useAdminCuratedSources,
  useAdminCuratedThemes,
  type CuratedFeature,
} from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
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
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type ClusterFeatureInput,
  VWorldFeatureClusters,
  VWorldMapView,
} from "@/components/vworld-map-view";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { DEFAULT_VIEWPORT, type FeatureViewMode, type MapViewport } from "@/state/map";

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

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function curatedFeatureHref(curatedFeatureId: string): string {
  return `/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`;
}

function coordLabel(feature: CuratedFeature): string {
  return typeof feature.lon === "number" && typeof feature.lat === "number"
    ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
    : "없음";
}

function titleLabel(feature: CuratedFeature): string {
  return feature.display_title ?? "제목 없음";
}

function sourceLabel(feature: CuratedFeature): string {
  return `${feature.source_name} · ${feature.provider}/${feature.dataset_key}`;
}

function toClusterFeature(feature: CuratedFeature): ClusterFeatureInput {
  return {
    feature_id: feature.curated_feature_id,
    name: feature.feature_name,
    kind: feature.feature_kind,
    category: feature.feature_category,
    lon: feature.lon ?? null,
    lat: feature.lat ?? null,
    marker_icon: null,
    marker_color: null,
    geometry: null,
  };
}

function CuratedDetailPanel({
  curatedFeatureId,
  fallback,
  onClose,
}: {
  curatedFeatureId: string;
  fallback: CuratedFeature | null;
  onClose: () => void;
}) {
  const detail = useAdminCuratedFeature(curatedFeatureId);
  const feature = detail.data?.data ?? fallback;

  return (
    <Card className="absolute right-3 top-3 z-10 max-h-[calc(100%-1.5rem)] w-[min(26rem,calc(100%-1.5rem))] overflow-auto shadow-lg">
      <CardHeader className="grid-cols-[1fr_auto]">
        <div>
          <CardTitle>선택 Curated Feature</CardTitle>
          <CardDescription className="break-all font-mono">
            {curatedFeatureId}
          </CardDescription>
        </div>
        <div className="flex items-center gap-1">
          <Link
            aria-label="curated 상세 열기"
            className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
            href={curatedFeatureHref(curatedFeatureId)}
          >
            <ExternalLinkIcon />
          </Link>
          {feature ? (
            <Link
              aria-label="feature 상세 열기"
              className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
              href={featureDetailHref(feature.feature_id)}
            >
              <SparklesIcon />
            </Link>
          ) : null}
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
        {detail.isLoading && !feature ? <Skeleton className="h-48 w-full" /> : null}
        {detail.isError ? (
          <Alert variant="destructive">
            <AlertTitle>curated feature 상세 호출 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {feature ? (
          <>
            <div className="flex flex-col gap-2">
              <h2 className="text-base font-semibold">{feature.feature_name}</h2>
              <div className="flex flex-wrap gap-2">
                <Badge>{feature.feature_kind}</Badge>
                <Badge variant="secondary">{feature.theme_name}</Badge>
                <Badge variant="outline">{feature.curation_status}</Badge>
              </div>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">제목</dt>
              <dd>{titleLabel(feature)}</dd>
              <dt className="text-muted-foreground">소스</dt>
              <dd>{sourceLabel(feature)}</dd>
              <dt className="text-muted-foreground">coord</dt>
              <dd className="font-mono">{coordLabel(feature)}</dd>
              <dt className="text-muted-foreground">feature_id</dt>
              <dd>
                <Link
                  className="break-all font-mono text-primary underline-offset-4 hover:underline"
                  href={featureDetailHref(feature.feature_id)}
                >
                  {shortId(feature.feature_id, 28)}
                </Link>
              </dd>
              <dt className="text-muted-foreground">selected</dt>
              <dd>{formatDateTime(feature.selected_at)}</dd>
              <dt className="text-muted-foreground">updated</dt>
              <dd>{formatDateTime(feature.updated_at)}</dd>
            </dl>
            <FeatureKindDetailPanel
              compact
              feature={{
                feature_id: feature.feature_id,
                kind: feature.feature_kind,
                name: feature.feature_name,
                category: feature.feature_category,
                detail: feature.detail,
                updated_at: feature.updated_at,
              }}
              featureId={feature.feature_id}
            />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function CuratedFeatureMapClient() {
  const [viewport, setViewport] = useState<MapViewport>(DEFAULT_VIEWPORT);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [viewMode, setViewMode] = useState<FeatureViewMode>("map");
  const [selectedCuratedId, setSelectedCuratedId] = useState<string | null>(null);
  const [poiName, setPoiName] = useState("");
  const [themeId, setThemeId] = useState("");
  const [displayTitle, setDisplayTitle] = useState("");
  const [sourceId, setSourceId] = useState("");
  const deferredPoiName = useDeferredValue(poiName);

  const themes = useAdminCuratedThemes({ limit: 500 });
  const sources = useAdminCuratedSources({ limit: 500 });
  const titleOptionsQuery = useAdminCuratedFeatures({
    curation_status: "curated",
    page_size: 200,
  });

  const featuresQuery = useAdminCuratedFeatures({
    ...(bbox ?? {}),
    curation_status: "curated",
    feature_name: deferredPoiName.trim() || undefined,
    theme_id: themeId || undefined,
    display_title: displayTitle || undefined,
    source_id: sourceId || undefined,
    include_archived: false,
    page_size: 200,
  });

  const updateViewportFromMap = useCallback((map: MapLibreMap) => {
    const center = map.getCenter();
    setViewport({ lon: center.lng, lat: center.lat, zoom: map.getZoom() });
    setBbox(boundsToBbox(map.getBounds()));
  }, []);

  const curatedItems = useMemo(
    () => featuresQuery.data?.data.items ?? [],
    [featuresQuery.data],
  );
  const clusterItems = useMemo(
    () => curatedItems.map(toClusterFeature),
    [curatedItems],
  );
  const selectedFeature =
    curatedItems.find((item) => item.curated_feature_id === selectedCuratedId) ??
    null;

  const titleOptions = useMemo(() => {
    const titles = new Set(
      (titleOptionsQuery.data?.data.items ?? [])
        .map((item) => item.display_title)
        .filter((value): value is string => Boolean(value)),
    );
    if (displayTitle) titles.add(displayTitle);
    return Array.from(titles).sort((a, b) => a.localeCompare(b, "ko"));
  }, [displayTitle, titleOptionsQuery.data]);

  const sourceOptions = sources.data?.data.items ?? [];
  const themeOptions = themes.data?.data.items ?? [];

  const [tableSorting, setTableSorting] = useState<SortingState>([
    { id: "feature_name", desc: false },
  ]);
  const columns = useMemo<ColumnDef<CuratedFeature, unknown>[]>(
    () => [
      {
        accessorKey: "feature_name",
        header: "POI명",
        sortingFn: (rowA, rowB) =>
          rowA.original.feature_name.localeCompare(
            rowB.original.feature_name,
            "ko",
          ),
        cell: ({ row }) => (
          <div className="max-w-[22rem] whitespace-normal">
            <Link
              className="font-medium text-primary underline-offset-4 hover:underline"
              href={featureDetailHref(row.original.feature_id)}
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.feature_name}
            </Link>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {shortId(row.original.feature_id, 18)}
            </div>
          </div>
        ),
      },
      {
        accessorKey: "theme_name",
        header: "테마",
        cell: ({ row }) => <Badge variant="secondary">{row.original.theme_name}</Badge>,
      },
      {
        accessorKey: "display_title",
        header: "제목",
        cell: ({ row }) => titleLabel(row.original),
      },
      {
        accessorKey: "source_name",
        header: "데이터소스",
        cell: ({ row }) => sourceLabel(row.original),
      },
      {
        id: "coord",
        header: "좌표",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {coordLabel(row.original)}
          </span>
        ),
      },
    ],
    [],
  );

  const status = useMemo(() => {
    if (featuresQuery.isLoading) return "curated feature 로딩 중";
    if (featuresQuery.isError) return "curated feature 호출 실패";
    const count = featuresQuery.data?.data.items.length ?? 0;
    return featuresQuery.isFetching ? `${count}건 표시 · 갱신 중` : `${count}건 표시`;
  }, [featuresQuery]);

  const clearSelectionAnd = (action: () => void) => {
    action();
    setSelectedCuratedId(null);
  };

  return (
    <AdminShell
      description={status}
      section="Curated Feature"
      title="Curated Feature 지도"
    >
      <div className="flex min-h-[calc(100vh-12rem)] flex-col rounded-lg border bg-muted/30">
        <div className="flex flex-col gap-3 border-b bg-background px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">Curated 지도</Badge>
            <Badge variant={featuresQuery.isError ? "destructive" : "outline"}>
              {status}
            </Badge>
          </div>
          <div className="grid gap-2 md:grid-cols-[minmax(12rem,1.2fr)_minmax(10rem,1fr)_minmax(10rem,1fr)_minmax(12rem,1fr)]">
            <Input
              aria-label="POI명 필터"
              placeholder="POI명"
              value={poiName}
              onChange={(event) =>
                clearSelectionAnd(() => setPoiName(event.target.value))
              }
            />
            <NativeSelect
              aria-label="테마 필터"
              value={themeId}
              onChange={(event) =>
                clearSelectionAnd(() => setThemeId(event.target.value))
              }
            >
              <NativeSelectOption value="">테마 전체</NativeSelectOption>
              {themeOptions.map((theme) => (
                <NativeSelectOption key={theme.theme_id} value={theme.theme_id}>
                  {theme.theme_name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="제목 필터"
              value={displayTitle}
              onChange={(event) =>
                clearSelectionAnd(() => setDisplayTitle(event.target.value))
              }
            >
              <NativeSelectOption value="">제목 전체</NativeSelectOption>
              {titleOptions.map((title) => (
                <NativeSelectOption key={title} value={title}>
                  {title}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="데이터소스 필터"
              value={sourceId}
              onChange={(event) =>
                clearSelectionAnd(() => setSourceId(event.target.value))
              }
            >
              <NativeSelectOption value="">데이터소스 전체</NativeSelectOption>
              {sourceOptions.map((source) => (
                <NativeSelectOption key={source.source_id} value={source.source_id}>
                  {source.source_name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </div>

        {featuresQuery.isError ? (
          <Alert className="m-4" variant="destructive">
            <AlertTitle>curated feature 호출 실패</AlertTitle>
            <AlertDescription>{featuresQuery.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <Tabs
          className="min-h-0 flex-1 p-4"
          value={viewMode}
          onValueChange={(value) => setViewMode(value as FeatureViewMode)}
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
              <div className="absolute inset-0 h-full w-full">
                <VWorldMapView
                  apiKey={VWORLD_KEY}
                  center={[viewport.lon, viewport.lat]}
                  className="absolute inset-0 h-full w-full"
                  testId="curated-map-canvas-container"
                  zoom={viewport.zoom}
                  onLoad={updateViewportFromMap}
                  onMoveEnd={updateViewportFromMap}
                >
                  <VWorldFeatureClusters
                    features={clusterItems}
                    selectedFeatureId={selectedCuratedId}
                    onSelectFeature={setSelectedCuratedId}
                  />
                </VWorldMapView>
              </div>
              {selectedCuratedId ? (
                <CuratedDetailPanel
                  curatedFeatureId={selectedCuratedId}
                  fallback={selectedFeature}
                  onClose={() => setSelectedCuratedId(null)}
                />
              ) : null}
            </Card>
          </TabsContent>

          <TabsContent value="table">
            <Card className="h-[calc(100vh-22rem)] min-h-[28rem] overflow-hidden">
              <CardHeader>
                <CardTitle>Curated feature</CardTitle>
                <CardDescription>
                  현재 지도 범위와 필터에 해당하는 curated feature입니다.
                </CardDescription>
              </CardHeader>
              <CardContent className="min-h-0">
                <DataTable
                  columns={columns}
                  data={curatedItems}
                  getRowId={(feature) => feature.curated_feature_id}
                  isLoading={featuresQuery.isLoading}
                  emptyMessage="표시할 curated feature가 없습니다."
                  onRowClick={(feature) =>
                    setSelectedCuratedId(feature.curated_feature_id)
                  }
                  isRowActive={(feature) =>
                    feature.curated_feature_id === selectedCuratedId
                  }
                  sorting={tableSorting}
                  onSortingChange={setTableSorting}
                  manualSorting={false}
                  virtualized
                  estimateRowSize={52}
                  containerClassName="h-[calc(100vh-28rem)] min-h-80"
                  ariaLabel="Curated feature"
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
      </div>
    </AdminShell>
  );
}
