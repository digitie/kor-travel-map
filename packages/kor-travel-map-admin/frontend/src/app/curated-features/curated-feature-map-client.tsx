"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (map) · design-system: design.md · designed-as-app

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
import { DetailList } from "@/components/detail-list";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card } from "@/components/ui/card";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type ClusterFeatureInput,
  VWorldFeatureClusters,
  VWorldMapView,
} from "@/components/vworld-map-view";
import { NULL_GLYPH, formatCount, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isVWorldApiKeyConfigured } from "@/lib/vworld-style";
import { DEFAULT_VIEWPORT, type FeatureViewMode, type MapViewport } from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
/** 지도/테이블 작업면 높이 — 뷰포트 비율(고정 rem 오프셋 금지, m6). */
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

function coordLabel(group: PublicCurationGroup): string | null {
  const { lon, lat } = group.feature;
  return typeof lon === "number" && typeof lat === "number"
    ? `${lon.toFixed(5)}, ${lat.toFixed(5)}`
    : null;
}

function addressLabel(address: Record<string, unknown>): string | null {
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
  return strings.join(" ") || null;
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

/** 소속 1건 — 테두리 박스 대신 hairline으로 나뉜 행(C3). 상태는 StatusBadge 1개, 나머지는 텍스트(M22). */
function MembershipRow({ item }: { item: PublicCurationItem }) {
  return (
    <li
      className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0"
      data-testid="curation-membership"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-xs font-medium text-text-primary">{item.theme_name}</span>
        {item.edition_key ? (
          <span className="text-xs text-text-secondary tabular-nums">{item.edition_key}</span>
        ) : null}
        <StatusBadge status={item.status} />
      </div>
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-medium text-text-primary">{itemTitle(item)}</p>
        {item.item_title && item.item_title !== item.title ? (
          <p className="text-xs text-text-secondary">컬렉션: {item.title}</p>
        ) : null}
      </div>
      <DetailList
        items={[
          { label: "테마", value: `${item.theme_name} (${item.theme_slug})` },
          {
            label: "출처",
            value: item.source_url ? (
              <a
                className="inline-flex items-center gap-1 rounded-control text-brand underline-offset-4 hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                href={item.source_url}
                rel="noreferrer"
                target="_blank"
              >
                {sourceLabel(item)}
                <ExternalLinkIcon aria-hidden="true" className="size-3" />
              </a>
            ) : (
              sourceLabel(item)
            ),
          },
          { label: "항목 ID", value: item.external_item_id, mono: true },
          { label: "관계", value: item.curation_relation, mono: true },
        ]}
        layout="inline"
      />
      {item.item_summary ? (
        <p className="text-xs whitespace-pre-wrap text-text-secondary">{item.item_summary}</p>
      ) : null}
      <details className="group/details">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-control py-1 text-xs font-medium text-text-secondary select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
            +
          </span>
          <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
            −
          </span>
          membership 전체 정보
        </summary>
        <div className="pt-1">
          <DetailList
            items={[
              { label: "collection_key", value: item.collection_key, mono: true },
              { label: "collection_id", value: item.collection_id, mono: true },
              { label: "curation_item_id", value: item.curation_item_id, mono: true },
              { label: "theme", value: `${item.theme_group} · ${item.theme_slug}` },
              { label: "place_name", value: item.place_name || null },
              { label: "address_hint", value: item.address_hint ?? null },
              { label: "relation", value: item.curation_relation, mono: true },
              { label: "reuse_policy", value: item.reuse_policy, mono: true },
              { label: "sort_order", value: item.sort_order, numeric: true },
              { label: "created_at", value: item.created_at, mono: true },
              { label: "updated_at", value: item.updated_at, mono: true },
              { label: "archived_at", value: item.archived_at ?? null, mono: true },
            ]}
            layout="inline"
          />
        </div>
      </details>
    </li>
  );
}

/**
 * 선택 그룹 inspector. 지도 위에서는 floating(overlay → shadow-elevated, 축척 컨트롤 위에 머문다),
 * 테이블 옆에서는 우측 rail(`--rail`)의 flat 패널이다.
 */
function CurationGroupDetailPanel({
  group,
  placement,
  onClose,
}: {
  group: PublicCurationGroup;
  placement: "floating" | "rail";
  onClose: () => void;
}) {
  const floating = placement === "floating";
  return (
    <Card
      className={cn(
        "gap-3 overflow-auto p-4",
        floating
          ? "absolute top-20 right-3 bottom-24 z-10 w-[min(var(--rail),calc(100%-1.5rem))] shadow-elevated"
          : cn("min-h-0", WORKSPACE_HEIGHT_CLASS),
      )}
      data-testid="curation-group-detail"
      size="sm"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border pb-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="text-md leading-snug font-semibold break-keep text-text-primary">
            {group.feature.name}
          </h2>
          <span className="text-xs text-text-secondary tabular-nums">
            큐레이션 소속 {formatCount(group.curations.length)}건
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
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
      </div>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-1">
          <Badge variant="neutral">{group.feature.kind}</Badge>
          <Badge variant="outline">{group.feature.category}</Badge>
        </div>
        <DetailList
          items={[
            { label: "주소", value: addressLabel(group.feature.address) },
            { label: "좌표", value: coordLabel(group), mono: true },
            {
              label: "feature_id",
              value: group.feature.feature_id,
              mono: true,
              href: featureDetailHref(group.feature.feature_id),
            },
          ]}
          layout="inline"
        />
        <ul className="divide-y divide-border border-t border-border pt-3">
          {group.curations.map((item) => (
            <MembershipRow item={item} key={item.curation_item_id} />
          ))}
        </ul>
      </div>
    </Card>
  );
}

function useCuratedFeatureMapClientController() {
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
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className="flex max-w-[22rem] min-w-0 flex-col gap-0.5">
            <Link
              className="rounded-control font-medium text-brand underline-offset-4 hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              href={featureDetailHref(row.original.feature.feature_id)}
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.feature.name}
            </Link>
            <span className="font-mono text-2xs break-all text-text-secondary slashed-zero">
              {shortId(row.original.feature.feature_id, 18)}
            </span>
          </div>
        ),
      },
      {
        id: "curation_count",
        accessorFn: (group) => group.curations.length,
        header: "소속",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => `${formatCount(row.original.curations.length)}건`,
      },
      {
        id: "themes",
        header: "테마",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className="flex max-w-64 flex-col gap-0.5 text-xs">
            {Array.from(new Set(row.original.curations.map((item) => item.theme_name))).map(
              (theme) => (
                <span key={theme}>{theme}</span>
              ),
            )}
          </div>
        ),
      },
      {
        id: "collections",
        header: "컬렉션 / 연도",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className="flex max-w-72 flex-col gap-0.5 text-sm">
            {row.original.curations.map((item) => (
              <span key={item.curation_item_id}>
                {item.title}{item.edition_key ? ` · ${item.edition_key}` : ""}
              </span>
            ))}
          </div>
        ),
      },
      {
        id: "sources",
        header: "데이터소스",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <div className="flex max-w-64 flex-col gap-0.5 text-xs text-text-secondary">
            {Array.from(new Set(row.original.curations.map(sourceLabel))).map((source) => (
              <span key={source}>{source}</span>
            ))}
          </div>
        ),
      },
      {
        id: "coord",
        header: "좌표",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const coordinate = coordLabel(row.original);
          return (
            <span
              className={cn(
                "font-mono text-xs slashed-zero",
                coordinate ? "text-text-secondary" : "text-text-tertiary",
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
    if (bbox === null) return "지도 범위 준비 중";
    if (groupsQuery.isLoading) return "큐레이션 그룹 로딩 중";
    if (groupsQuery.isError) return "큐레이션 그룹 호출 실패";
    const count = groups.length;
    const pages = groupsQuery.data?.pages_loaded ?? 0;
    return groupsQuery.isFetching
      ? `${count}곳 · ${pages}페이지 누적 · 갱신 중`
      : `${count}곳 · ${pages}페이지 전체 반영`;
  }, [bbox, groups, groupsQuery]);

  return {
    clusterItems,
    collectionsQuery,
    columns,
    editionKey,
    filterOptions,
    groups,
    groupsQuery,
    provider,
    search,
    selectedFeatureId,
    selectedGroup,
    setEditionKey,
    setProvider,
    setSearch,
    setSelectedFeatureId,
    setTableSorting,
    setThemeSlug,
    setViewMode,
    status,
    tableSorting,
    themeSlug,
    updateViewportFromMap,
    viewMode,
    viewport,
  };
}

function CuratedFeatureMapClientView({
  clusterItems,
  collectionsQuery,
  columns,
  editionKey,
  filterOptions,
  groups,
  groupsQuery,
  provider,
  search,
  selectedFeatureId,
  selectedGroup,
  setEditionKey,
  setProvider,
  setSearch,
  setSelectedFeatureId,
  setTableSorting,
  setThemeSlug,
  setViewMode,
  status,
  tableSorting,
  themeSlug,
  updateViewportFromMap,
  viewMode,
  viewport,
}: ReturnType<typeof useCuratedFeatureMapClientController>) {
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
      description="공개 큐레이션에 소속된 feature를 지도 범위·테마·연도·제공자로 걸러 봅니다."
      title="큐레이션 지도"
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3">
          <FilterBar>
            <FilterField htmlFor="curated-map-search" label="검색">
              <Input
                aria-label="POI명 또는 큐레이션 제목 필터"
                className="w-64"
                id="curated-map-search"
                placeholder="예: 경복궁, 한국관광 100선"
                size="sm"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setSelectedFeatureId(null);
                }}
              />
            </FilterField>
            <FilterField htmlFor="curated-map-theme" label="테마">
              <NativeSelect
                aria-label="테마 필터"
                className="w-52"
                id="curated-map-theme"
                size="sm"
                value={themeSlug}
                onChange={(event) => {
                  setThemeSlug(event.target.value);
                  setSelectedFeatureId(null);
                }}
              >
                <NativeSelectOption value="">테마 전체</NativeSelectOption>
                {filterOptions.themes.map((theme) => (
                  <NativeSelectOption key={theme.value} value={theme.value}>
                    {theme.label}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField htmlFor="curated-map-edition" label="연도">
              <NativeSelect
                aria-label="연도 필터"
                className="w-44"
                id="curated-map-edition"
                size="sm"
                value={editionKey}
                onChange={(event) => {
                  setEditionKey(event.target.value);
                  setSelectedFeatureId(null);
                }}
              >
                <NativeSelectOption value="">연도 전체</NativeSelectOption>
                {filterOptions.editions.map((edition) => (
                  <NativeSelectOption key={edition} value={edition}>{edition}</NativeSelectOption>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField htmlFor="curated-map-provider" label="제공자">
              <NativeSelect
                aria-label="제공자 필터"
                className="w-44"
                id="curated-map-provider"
                size="sm"
                value={provider}
                onChange={(event) => {
                  setProvider(event.target.value);
                  setSelectedFeatureId(null);
                }}
              >
                <NativeSelectOption value="">제공자 전체</NativeSelectOption>
                {filterOptions.providers.map((value) => (
                  <NativeSelectOption key={value} value={value}>{value}</NativeSelectOption>
                ))}
              </NativeSelect>
            </FilterField>
          </FilterBar>

          {groupsQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>큐레이션 그룹 호출 실패</AlertTitle>
              <AlertDescription>
                {groupsQuery.error.message} — 지도를 조금 움직이거나 필터를 바꾸면 다시
                조회합니다.
              </AlertDescription>
            </Alert>
          ) : null}
          {collectionsQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>큐레이션 필터 조회 실패</AlertTitle>
              <AlertDescription>
                {collectionsQuery.error.message} — 테마·연도·제공자 옵션이 비어 있을 수
                있습니다.
              </AlertDescription>
            </Alert>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={groupsQuery.isError ? "destructive" : "neutral"}>{status}</Badge>
          </div>
        </div>

        <Tabs
          className="min-h-0"
          value={viewMode}
          onValueChange={(value) => setViewMode(value as FeatureViewMode)}
        >
          {/* 좌표 readout은 탭 헤더 행 — 지도/테이블 두 탭 모두 지도 bounds로 필터되므로 공통 컨텍스트다. */}
          <div className="flex flex-wrap items-center justify-between gap-2">
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
            <span className="font-mono text-2xs text-text-secondary tabular-nums">
              center {viewport.lon.toFixed(4)}, {viewport.lat.toFixed(4)} · z{" "}
              {viewport.zoom.toFixed(1)}
            </span>
          </div>

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
              {selectedGroup ? (
                <CurationGroupDetailPanel
                  group={selectedGroup}
                  placement="floating"
                  onClose={() => setSelectedFeatureId(null)}
                />
              ) : null}
            </div>
          </TabsContent>

          <TabsContent value="table">
            <div
              className={cn(
                "grid gap-4",
                selectedGroup && "xl:grid-cols-[minmax(0,1fr)_var(--rail)]",
              )}
            >
              <DataTable
                ariaLabel="큐레이션 Feature 그룹"
                columns={columns}
                containerClassName={WORKSPACE_HEIGHT_CLASS}
                data={groups}
                emptyState={{
                  title: "표시할 큐레이션 Feature가 없습니다.",
                  description:
                    "현재 지도 범위와 검색·테마·연도·제공자 필터에 맞는 feature가 없습니다 — 지도를 이동하거나 필터를 넓혀 보세요.",
                }}
                estimateRowSize={64}
                getRowId={(group) => group.feature.feature_id}
                isLoading={groupsQuery.isLoading}
                isRowActive={(group) =>
                  group.feature.feature_id === selectedFeatureId
                }
                manualSorting={false}
                onRowClick={(group) => setSelectedFeatureId(group.feature.feature_id)}
                onSortingChange={setTableSorting}
                sorting={tableSorting}
                virtualized
              />
              {selectedGroup ? (
                <CurationGroupDetailPanel
                  group={selectedGroup}
                  placement="rail"
                  onClose={() => setSelectedFeatureId(null)}
                />
              ) : null}
            </div>
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
    </AdminShell>
  );
}

export function CuratedFeatureMapClient() {
  const controller = useCuratedFeatureMapClientController();
  return <CuratedFeatureMapClientView {...controller} />;
}
