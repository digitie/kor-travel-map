"use client";

import { createMarkerElement } from "@krtour/map-marker-react";
import "maplibre-vworld/style.css";
import maplibregl, { LngLatBounds, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  GitCompareArrowsIcon,
  ListChecksIcon,
  ListIcon,
  MapIcon,
  RefreshCwIcon,
  RouteIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  FEATURE_KINDS,
  useFeatureDetail,
  useFeaturesInBbox,
  type FeatureKind,
  type FeatureSummary,
} from "@/api/features";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useMapStore, type FeatureViewMode } from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const VWORLD_ATTRIBUTION = "공간정보 오픈플랫폼 브이월드";
const VWORLD_IMAGERY_LAYERS = new Set<VWorldLayerType>(["Hybrid", "Satellite"]);

type VWorldLayerType = "Base" | "gray" | "midnight" | "Hybrid" | "Satellite";

interface Bbox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

function buildStyle(): StyleSpecification {
  if (VWORLD_KEY && VWORLD_KEY !== "CHANGE_ME") {
    return getClientVWorldStyle(VWORLD_KEY, "Base");
  }
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "bg",
        type: "background",
        paint: { "background-color": "#edf1f5" },
      },
    ],
  };
}

function getVWorldTileUrl(apiKey: string, layerType: VWorldLayerType): string {
  const extension = layerType === "Satellite" ? "jpeg" : "png";
  const layerName = layerType === "gray" ? "white" : layerType;
  return `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(
    apiKey.trim(),
  )}/${layerName}/{z}/{y}/{x}.${extension}`;
}

function getVWorldMaxZoom(layerType: VWorldLayerType): number {
  return VWORLD_IMAGERY_LAYERS.has(layerType) ? 18 : 19;
}

function getClientVWorldStyle(
  apiKey: string,
  layerType: VWorldLayerType,
): StyleSpecification {
  const maxzoom = getVWorldMaxZoom(layerType);
  const sources: StyleSpecification["sources"] = {};
  const layers: StyleSpecification["layers"] = [];

  const appendRasterLayer = (
    sourceId: string,
    layerId: string,
    sourceLayerType: VWorldLayerType,
  ) => {
    sources[sourceId] = {
      type: "raster",
      tiles: [getVWorldTileUrl(apiKey, sourceLayerType)],
      tileSize: 256,
      attribution: VWORLD_ATTRIBUTION,
      maxzoom,
    };
    layers.push({
      id: layerId,
      type: "raster",
      source: sourceId,
      minzoom: 0,
    });
  };

  if (layerType === "Hybrid") {
    appendRasterLayer(
      "vworld-satellite",
      "vworld-satellite-layer",
      "Satellite",
    );
  }
  appendRasterLayer(`vworld-${layerType}`, `vworld-${layerType}-layer`, layerType);

  return {
    version: 8,
    sources,
    layers,
  };
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
        <Button
          aria-label="닫기"
          size="icon-sm"
          type="button"
          variant="ghost"
          onClick={onClose}
        >
          <XIcon />
        </Button>
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
                {detailQuery.data.lon !== null && detailQuery.data.lat !== null
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
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function FeaturesClient() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerLayerRef = useRef<maplibregl.Marker[]>([]);

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
    },
    { enabled: bbox !== null },
  );

  useEffect(() => {
    if (containerRef.current === null) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [viewport.lon, viewport.lat],
      zoom: viewport.zoom,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    const updateBbox = () => {
      const center = map.getCenter();
      setViewport({
        lon: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
      });
      setBbox(boundsToBbox(map.getBounds()));
    };
    map.on("load", updateBbox);
    map.on("moveend", updateBbox);

    return () => {
      map.off("load", updateBbox);
      map.off("moveend", updateBbox);
      for (const marker of markerLayerRef.current) marker.remove();
      markerLayerRef.current = [];
      map.remove();
      mapRef.current = null;
    };
    // maplibre 인스턴스는 mount 1회만 생성하고 viewport는 store에 동기화한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mapRef.current === null) return;
    const data: FeatureSummary[] = featuresQuery.data?.items ?? [];
    for (const marker of markerLayerRef.current) marker.remove();
    markerLayerRef.current = [];
    for (const feature of data) {
      if (feature.lon === null || feature.lat === null) continue;
      const element = createMarkerElement({
        markerIcon: feature.marker_icon,
        markerColor: feature.marker_color,
        size: 24,
        title: `${feature.name} (${feature.kind})`,
        onClick: () => setSelectedFeatureId(feature.feature_id),
      });
      const marker = new maplibregl.Marker({ element })
        .setLngLat([feature.lon, feature.lat])
        .addTo(mapRef.current);
      markerLayerRef.current.push(marker);
    }
  }, [featuresQuery.data, setSelectedFeatureId]);

  const sortedFeatures = useMemo(
    () =>
      (featuresQuery.data?.items ?? []).toSorted((a, b) =>
        a.name.localeCompare(b.name, "ko"),
      ),
    [featuresQuery.data],
  );

  const status = useMemo(() => {
    if (!bbox) return "지도 로딩 중";
    if (featuresQuery.isLoading) return "feature 로딩 중";
    if (featuresQuery.isError) return "feature 호출 실패";
    return `${featuresQuery.data?.count ?? 0}건 표시`;
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
            href="/admin/dedup-review"
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
              ref={containerRef}
              className="absolute inset-0 h-full w-full"
              data-testid="map-canvas-container"
            />
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
            <CardContent className="overflow-auto">
              {featuresQuery.isLoading ? <Skeleton className="h-72 w-full" /> : null}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>name</TableHead>
                    <TableHead>kind</TableHead>
                    <TableHead>status</TableHead>
                    <TableHead>coord</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedFeatures.map((feature) => (
                    <TableRow
                      className="cursor-pointer"
                      key={feature.feature_id}
                      onClick={() => setSelectedFeatureId(feature.feature_id)}
                    >
                      <TableCell className="font-medium">{feature.name}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{feature.kind}</Badge>
                      </TableCell>
                      <TableCell>{feature.status}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {feature.lon !== null && feature.lat !== null
                          ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                          : "없음"}
                      </TableCell>
                    </TableRow>
                  ))}
                  {sortedFeatures.length === 0 && !featuresQuery.isLoading ? (
                    <TableRow>
                      <TableCell
                        className="h-28 text-center text-muted-foreground"
                        colSpan={4}
                      >
                        표시할 feature가 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {!VWORLD_KEY || VWORLD_KEY === "CHANGE_ME" ? (
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
