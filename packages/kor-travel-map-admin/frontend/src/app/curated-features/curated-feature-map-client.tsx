"use client";

import type { LngLatBounds, Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ExternalLinkIcon,
  ListIcon,
  MapIcon,
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
  usePublicCurationCollections,
  usePublicCurationGroups,
  type PublicCurationGroup,
  type PublicCurationItem,
} from "@/api/public-curations";
import { AdminShell } from "@/components/admin-shell";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type ClusterFeatureInput,
  VWorldFeatureClusters,
  VWorldMapView,
} from "@/components/vworld-map-view";
import { shortId } from "@/lib/format";
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

function coordLabel(group: PublicCurationGroup): string {
  const { lon, lat } = group.feature;
  return typeof lon === "number" && typeof lat === "number"
    ? `${lon.toFixed(5)}, ${lat.toFixed(5)}`
    : "없음";
}

function addressLabel(address: Record<string, unknown>): string {
  const preferredKeys = [
    "road_address",
    "roadAddress",
    "address",
    "jibun_address",
    "full_address",
  ];
  for (const key of preferredKeys) {
    const value = address[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  const strings = Object.values(address).filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0,
  );
  return strings.join(" ") || "없음";
}

function sourceLabel(item: PublicCurationItem): string {
  const parts = [item.source_name, item.provider, item.dataset_key].filter(
    (value): value is string => Boolean(value),
  );
  return parts.join(" · ") || "출처 없음";
}

function itemTitle(item: PublicCurationItem): string {
  return item.item_title || item.title;
}

function toClusterFeature(group: PublicCurationGroup): ClusterFeatureInput {
  return {
    feature_id: group.feature.feature_id,
    name: group.feature.name,
    kind: group.feature.kind,
    category: group.feature.category,
    lon: group.feature.lon,
    lat: group.feature.lat,
    marker_icon: null,
    marker_color: null,
    geometry: null,
  };
}

function MembershipCard({ item }: { item: PublicCurationItem }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border p-3"
      data-testid="curation-membership"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{item.theme_name}</Badge>
        {item.edition_key ? <Badge variant="outline">{item.edition_key}</Badge> : null}
        <Badge variant="outline">{item.status}</Badge>
      </div>
      <div>
        <p className="font-medium">{itemTitle(item)}</p>
        {item.item_title && item.item_title !== item.title ? (
          <p className="text-xs text-muted-foreground">컬렉션: {item.title}</p>
        ) : null}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">테마</dt>
        <dd>{item.theme_name} ({item.theme_slug})</dd>
        <dt className="text-muted-foreground">출처</dt>
        <dd>
          {item.source_url ? (
            <a
              className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
              href={item.source_url}
              rel="noreferrer"
              target="_blank"
            >
              {sourceLabel(item)}
              <ExternalLinkIcon className="size-3" />
            </a>
          ) : (
            sourceLabel(item)
          )}
        </dd>
        <dt className="text-muted-foreground">항목 ID</dt>
        <dd className="break-all font-mono">{item.external_item_id}</dd>
        <dt className="text-muted-foreground">관계</dt>
        <dd>{item.curation_relation}</dd>
      </dl>
      {item.item_summary ? (
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">
          {item.item_summary}
        </p>
      ) : null}
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">
          membership 전체 정보
        </summary>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">collection_key</dt>
          <dd className="break-all font-mono">{item.collection_key}</dd>
          <dt className="text-muted-foreground">collection_id</dt>
          <dd className="break-all font-mono">{item.collection_id}</dd>
          <dt className="text-muted-foreground">curation_item_id</dt>
          <dd className="break-all font-mono">{item.curation_item_id}</dd>
          <dt className="text-muted-foreground">theme</dt>
          <dd>{item.theme_group} · {item.theme_slug}</dd>
          <dt className="text-muted-foreground">place_name</dt>
          <dd>{item.place_name || "-"}</dd>
          <dt className="text-muted-foreground">address_hint</dt>
          <dd>{item.address_hint ?? "-"}</dd>
          <dt className="text-muted-foreground">relation</dt>
          <dd>{item.curation_relation}</dd>
          <dt className="text-muted-foreground">reuse_policy</dt>
          <dd>{item.reuse_policy}</dd>
          <dt className="text-muted-foreground">sort_order</dt>
          <dd>{item.sort_order}</dd>
          <dt className="text-muted-foreground">created_at</dt>
          <dd>{item.created_at}</dd>
          <dt className="text-muted-foreground">updated_at</dt>
          <dd>{item.updated_at}</dd>
          <dt className="text-muted-foreground">archived_at</dt>
          <dd>{item.archived_at ?? "-"}</dd>
        </dl>
      </details>
    </div>
  );
}

function CurationGroupDetailPanel({
  group,
  avoidMapControls,
  onClose,
}: {
  group: PublicCurationGroup;
  avoidMapControls: boolean;
  onClose: () => void;
}) {
  return (
    <Card
      className={cn(
        "absolute right-3 top-20 z-10 w-[min(28rem,calc(100%-1.5rem))] overflow-auto shadow-lg",
        avoidMapControls ? "bottom-24" : "max-h-[calc(100%-5.75rem)]",
      )}
      data-testid="curation-group-detail"
    >
      <CardHeader className="grid-cols-[1fr_auto]">
        <div>
          <CardTitle>{group.feature.name}</CardTitle>
          <CardDescription>
            큐레이션 소속 {group.curations.length}건
          </CardDescription>
        </div>
        <div className="flex items-center gap-1">
          <Link
            aria-label="feature 상세 열기"
            className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
            href={featureDetailHref(group.feature.feature_id)}
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
        <div className="flex flex-wrap gap-2">
          <Badge>{group.feature.kind}</Badge>
          <Badge variant="outline">{group.feature.category}</Badge>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">주소</dt>
          <dd>{addressLabel(group.feature.address)}</dd>
          <dt className="text-muted-foreground">좌표</dt>
          <dd className="font-mono">{coordLabel(group)}</dd>
          <dt className="text-muted-foreground">feature_id</dt>
          <dd className="break-all font-mono">
            <Link
              className="text-primary underline-offset-4 hover:underline"
              href={featureDetailHref(group.feature.feature_id)}
            >
              {group.feature.feature_id}
            </Link>
          </dd>
        </dl>
        <div className="flex flex-col gap-2">
          {group.curations.map((item) => (
            <MembershipCard item={item} key={item.curation_item_id} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function CuratedFeatureMapClient() {
  const [viewport, setViewport] = useState<MapViewport>(DEFAULT_VIEWPORT);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [viewMode, setViewMode] = useState<FeatureViewMode>("map");
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [themeSlug, setThemeSlug] = useState("");
  const [editionKey, setEditionKey] = useState("");
  const [provider, setProvider] = useState("");
  const deferredSearch = useDeferredValue(search);

  const collectionsQuery = usePublicCurationCollections();
  const groupsQuery = usePublicCurationGroups(
    {
      ...(bbox ?? {}),
      q: deferredSearch.trim() || undefined,
      theme_slug: themeSlug || undefined,
      edition_key: editionKey || undefined,
      provider: provider || undefined,
      page_size: 500,
    },
    { enabled: bbox !== null },
  );

  const updateViewportFromMap = useCallback((map: MapLibreMap) => {
    const center = map.getCenter();
    setViewport({ lon: center.lng, lat: center.lat, zoom: map.getZoom() });
    setBbox(boundsToBbox(map.getBounds()));
  }, []);

  const groups = useMemo(() => groupsQuery.data?.data.items ?? [], [groupsQuery.data]);
  const clusterItems = useMemo(() => groups.map(toClusterFeature), [groups]);
  const selectedGroup =
    groups.find((group) => group.feature.feature_id === selectedFeatureId) ?? null;

  const filterOptions = useMemo(() => {
    const collections = collectionsQuery.data?.data.items ?? [];
    const themes = new Map<string, string>();
    const editions = new Set<string>();
    const providers = new Set<string>();
    for (const collection of collections) {
      themes.set(collection.theme_slug, collection.theme_name);
      if (collection.edition_key) editions.add(collection.edition_key);
      if (collection.provider) providers.add(collection.provider);
    }
    return {
      themes: Array.from(themes, ([value, label]) => ({ value, label })).sort((a, b) =>
        a.label.localeCompare(b.label, "ko"),
      ),
      editions: Array.from(editions).sort((a, b) => b.localeCompare(a, "ko")),
      providers: Array.from(providers).sort((a, b) => a.localeCompare(b, "ko")),
    };
  }, [collectionsQuery.data]);

  const [tableSorting, setTableSorting] = useState<SortingState>([
    { id: "feature_name", desc: false },
  ]);
  const columns = useMemo<ColumnDef<PublicCurationGroup, unknown>[]>(
    () => [
      {
        id: "feature_name",
        accessorFn: (group) => group.feature.name,
        header: "POI명",
        sortingFn: (rowA, rowB) =>
          rowA.original.feature.name.localeCompare(rowB.original.feature.name, "ko"),
        cell: ({ row }) => (
          <div className="max-w-[22rem] whitespace-normal">
            <Link
              className="font-medium text-primary underline-offset-4 hover:underline"
              href={featureDetailHref(row.original.feature.feature_id)}
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.feature.name}
            </Link>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {shortId(row.original.feature.feature_id, 18)}
            </div>
          </div>
        ),
      },
      {
        id: "curation_count",
        accessorFn: (group) => group.curations.length,
        header: "소속",
        cell: ({ row }) => `${row.original.curations.length}건`,
      },
      {
        id: "themes",
        header: "테마",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex max-w-64 flex-wrap gap-1">
            {Array.from(new Set(row.original.curations.map((item) => item.theme_name))).map(
              (theme) => (
                <Badge key={theme} variant="secondary">{theme}</Badge>
              ),
            )}
          </div>
        ),
      },
      {
        id: "collections",
        header: "컬렉션 / 연도",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="max-w-72 space-y-1 whitespace-normal text-sm">
            {row.original.curations.map((item) => (
              <div key={item.curation_item_id}>
                {item.title}{item.edition_key ? ` · ${item.edition_key}` : ""}
              </div>
            ))}
          </div>
        ),
      },
      {
        id: "sources",
        header: "데이터소스",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="max-w-64 space-y-1 whitespace-normal text-xs">
            {Array.from(new Set(row.original.curations.map(sourceLabel))).map((source) => (
              <div key={source}>{source}</div>
            ))}
          </div>
        ),
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
    if (bbox === null) return "지도 범위 준비 중";
    if (groupsQuery.isLoading) return "큐레이션 그룹 로딩 중";
    if (groupsQuery.isError) return "큐레이션 그룹 호출 실패";
    const count = groups.length;
    const pages = groupsQuery.data?.pages_loaded ?? 0;
    return groupsQuery.isFetching
      ? `${count}곳 · ${pages}페이지 누적 · 갱신 중`
      : `${count}곳 · ${pages}페이지 전체 반영`;
  }, [bbox, groups, groupsQuery]);

  const clearSelectionAnd = (action: () => void) => {
    action();
    setSelectedFeatureId(null);
  };

  return (
    <AdminShell
      actions={
        <>
          <Link className={buttonVariants({ variant: "outline" })} href="/features">
            Feature 지도
          </Link>
          <Link
            className={buttonVariants({ variant: "outline" })}
            href="/admin/curated-features"
          >
            큐레이션 관리
          </Link>
        </>
      }
      description={status}
      title="큐레이션 지도"
    >
      <div className="flex min-h-[calc(100vh-12rem)] flex-col rounded-lg border bg-muted/30">
        <div className="flex flex-col gap-3 border-b bg-background px-4 py-3 xl:flex-row xl:items-center">
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Badge variant="secondary">Feature 그룹 지도</Badge>
            <Badge variant={groupsQuery.isError ? "destructive" : "outline"}>
              {status}
            </Badge>
          </div>
          <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 xl:justify-end">
            <Input
              aria-label="POI명 또는 큐레이션 제목 필터"
              className="w-64 shrink-0"
              placeholder="POI명, 제목, 테마 검색"
              value={search}
              onChange={(event) =>
                clearSelectionAnd(() => setSearch(event.target.value))
              }
            />
            <NativeSelect
              aria-label="테마 필터"
              className="w-52 shrink-0"
              value={themeSlug}
              onChange={(event) =>
                clearSelectionAnd(() => setThemeSlug(event.target.value))
              }
            >
              <NativeSelectOption value="">테마 전체</NativeSelectOption>
              {filterOptions.themes.map((theme) => (
                <NativeSelectOption key={theme.value} value={theme.value}>
                  {theme.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="연도 필터"
              className="w-44 shrink-0"
              value={editionKey}
              onChange={(event) =>
                clearSelectionAnd(() => setEditionKey(event.target.value))
              }
            >
              <NativeSelectOption value="">연도 전체</NativeSelectOption>
              {filterOptions.editions.map((edition) => (
                <NativeSelectOption key={edition} value={edition}>{edition}</NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="제공자 필터"
              className="w-44 shrink-0"
              value={provider}
              onChange={(event) =>
                clearSelectionAnd(() => setProvider(event.target.value))
              }
            >
              <NativeSelectOption value="">제공자 전체</NativeSelectOption>
              {filterOptions.providers.map((value) => (
                <NativeSelectOption key={value} value={value}>{value}</NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </div>

        {groupsQuery.isError ? (
          <Alert className="m-4" variant="destructive">
            <AlertTitle>큐레이션 그룹 호출 실패</AlertTitle>
            <AlertDescription>{groupsQuery.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {collectionsQuery.isError ? (
          <Alert className="mx-4 mt-4" variant="destructive">
            <AlertTitle>큐레이션 필터 조회 실패</AlertTitle>
            <AlertDescription>{collectionsQuery.error.message}</AlertDescription>
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
                  navigation
                  scale
                  testId="curated-map-canvas-container"
                  zoom={viewport.zoom}
                  onLoad={updateViewportFromMap}
                  onMoveEnd={updateViewportFromMap}
                >
                  <VWorldFeatureClusters
                    features={clusterItems}
                    selectedFeatureId={selectedFeatureId}
                    onSelectFeature={setSelectedFeatureId}
                  />
                </VWorldMapView>
              </div>
              {selectedGroup ? (
                <CurationGroupDetailPanel
                  group={selectedGroup}
                  avoidMapControls
                  onClose={() => setSelectedFeatureId(null)}
                />
              ) : null}
            </Card>
          </TabsContent>

          <TabsContent value="table">
            <Card className="relative h-[calc(100vh-22rem)] min-h-[28rem] overflow-hidden">
              <CardHeader>
                <CardTitle>큐레이션 Feature 그룹</CardTitle>
                <CardDescription>
                  한 행은 한 Feature이며, 관련된 모든 큐레이션 소속을 함께 표시합니다.
                </CardDescription>
              </CardHeader>
              <CardContent className="min-h-0">
                <DataTable
                  columns={columns}
                  data={groups}
                  getRowId={(group) => group.feature.feature_id}
                  isLoading={groupsQuery.isLoading}
                  emptyMessage="표시할 큐레이션 Feature가 없습니다."
                  onRowClick={(group) => setSelectedFeatureId(group.feature.feature_id)}
                  isRowActive={(group) =>
                    group.feature.feature_id === selectedFeatureId
                  }
                  sorting={tableSorting}
                  onSortingChange={setTableSorting}
                  manualSorting={false}
                  virtualized
                  estimateRowSize={64}
                  containerClassName="h-[calc(100vh-28rem)] min-h-80"
                  ariaLabel="큐레이션 Feature 그룹"
                />
              </CardContent>
              {selectedGroup ? (
                <CurationGroupDetailPanel
                  group={selectedGroup}
                  avoidMapControls={false}
                  onClose={() => setSelectedFeatureId(null)}
                />
              ) : null}
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
