import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback } from "react";

import { getJson, pathWithQuery } from "./client";
import type {
  CurationCollectionStatus,
  CurationCollectionVisibility,
  CurationItemStatus,
  CurationRelation,
  CurationReusePolicy,
} from "./curations";

export interface PublicCurationFeature {
  feature_id: string;
  name: string;
  kind: string;
  category: string;
  lon: number | null;
  lat: number | null;
  address: Record<string, unknown>;
  status: string;
}

export interface PublicCurationItem {
  curation_item_id: string;
  collection_id: string;
  collection_key: string;
  title: string;
  edition_key: string;
  theme_slug: string;
  theme_name: string;
  theme_group: string;
  provider: string | null;
  dataset_key: string | null;
  source_name: string | null;
  source_url: string | null;
  feature_id: string | null;
  feature_name: string | null;
  feature_kind: string | null;
  feature_category: string | null;
  lon: number | null;
  lat: number | null;
  address: Record<string, unknown>;
  external_item_id: string;
  place_name: string;
  address_hint: string | null;
  status: CurationItemStatus;
  sort_order: number;
  item_title: string | null;
  item_summary: string | null;
  curation_relation: CurationRelation;
  reuse_policy: CurationReusePolicy;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface PublicCurationGroup {
  feature: PublicCurationFeature;
  curations: PublicCurationItem[];
  curation_count: number;
}

export interface PublicCurationCollection {
  collection_id: string;
  collection_key: string;
  theme_id: string;
  theme_slug: string;
  theme_name: string;
  theme_group: string;
  source_id: string | null;
  provider: string | null;
  dataset_key: string | null;
  source_name: string | null;
  source_url: string | null;
  title: string;
  edition_key: string;
  description: string | null;
  status: CurationCollectionStatus;
  visibility: CurationCollectionVisibility;
  item_count: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

interface PageMeta {
  next_cursor?: string | null;
  page_size: number;
  total?: number | null;
}

interface ApiMeta {
  page?: PageMeta | null;
  [key: string]: unknown;
}

interface PublicCurationGroupsPageResponse {
  data: { items: PublicCurationGroup[] };
  meta: ApiMeta;
}

export interface PublicCurationGroupsResponse
  extends PublicCurationGroupsPageResponse {
  pages_loaded: number;
}

export interface PublicCurationCollectionsResponse {
  data: { items: PublicCurationCollection[] };
  meta: ApiMeta;
}

export interface PublicCurationGroupsParams {
  theme_slug?: string;
  edition_key?: string;
  provider?: string;
  q?: string;
  min_lon?: number;
  min_lat?: number;
  max_lon?: number;
  max_lat?: number;
  page_size?: number;
}

const CURATION_BBOX_CELLS_PER_VIEWPORT = 4;
const MIN_CURRATION_BBOX_STEP = 2 ** -10;
const MERCATOR_LAT_LIMIT = 85.05112878;

function paddedQuantizedRange(
  first: number,
  second: number,
  domainMin: number,
  domainMax: number,
): [number, number] {
  const min = Math.min(first, second);
  const max = Math.max(first, second);
  const span = max - min;
  // viewport 폭의 약 1/4을 power-of-two cell로 고정한다. 같은 zoom band에서 작은
  // pan은 동일 중심 cell을 재사용하고, 중심 반올림 여유를 둔 padding이 화면을 보장한다.
  const targetStep = Math.max(
    span / CURATION_BBOX_CELLS_PER_VIEWPORT,
    MIN_CURRATION_BBOX_STEP,
  );
  const step = 2 ** Math.floor(Math.log2(targetStep));
  const center = (min + max) / 2;
  const quantizedCenter = Math.round(center / step) * step;
  // 중심 반올림 오차(최대 0.5 cell)까지 포함할 만큼만 확장한다. 무조건 한 cell을
  // 더하는 것보다 fetch 면적을 줄이면서 원 viewport 포함 조건은 유지한다.
  const halfCells = Math.ceil(span / (2 * step) + 0.5);
  return [
    Math.max(domainMin, quantizedCenter - halfCells * step),
    Math.min(domainMax, quantizedCenter + halfCells * step),
  ];
}

/**
 * 지도 bbox를 zoom-band별 grid에 맞춘 padded bbox로 바꾼다. query key와 실제 API
 * 요청이 같은 정규화 params를 사용하므로 작은 pan은 캐시를 재사용하면서도 현재
 * viewport가 캐시 범위를 벗어나 stale marker를 보이는 문제를 피한다.
 */
export function stabilizePublicCurationGroupsParams(
  params: PublicCurationGroupsParams,
): PublicCurationGroupsParams {
  const { min_lon, min_lat, max_lon, max_lat } = params;
  if (
    typeof min_lon !== "number" ||
    !Number.isFinite(min_lon) ||
    typeof min_lat !== "number" ||
    !Number.isFinite(min_lat) ||
    typeof max_lon !== "number" ||
    !Number.isFinite(max_lon) ||
    typeof max_lat !== "number" ||
    !Number.isFinite(max_lat)
  ) {
    return params;
  }
  const [minLon, maxLon] = paddedQuantizedRange(
    min_lon,
    max_lon,
    -180,
    180,
  );
  const [minLat, maxLat] = paddedQuantizedRange(
    min_lat,
    max_lat,
    -MERCATOR_LAT_LIMIT,
    MERCATOR_LAT_LIMIT,
  );
  return {
    ...params,
    min_lon: minLon,
    min_lat: minLat,
    max_lon: maxLon,
    max_lat: maxLat,
  };
}

interface PublicCurationViewportBounds {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

function publicCurationViewportBounds(
  params: PublicCurationGroupsParams,
): PublicCurationViewportBounds | null {
  const { min_lon, min_lat, max_lon, max_lat } = params;
  if (
    typeof min_lon !== "number" ||
    !Number.isFinite(min_lon) ||
    typeof min_lat !== "number" ||
    !Number.isFinite(min_lat) ||
    typeof max_lon !== "number" ||
    !Number.isFinite(max_lon) ||
    typeof max_lat !== "number" ||
    !Number.isFinite(max_lat)
  ) {
    return null;
  }
  return {
    minLon: Math.min(min_lon, max_lon),
    minLat: Math.min(min_lat, max_lat),
    maxLon: Math.max(min_lon, max_lon),
    maxLat: Math.max(min_lat, max_lat),
  };
}

/**
 * padded bbox로 받은 캐시 응답을 현재 viewport로 다시 자른다. 이 함수는 queryFn이
 * 아니라 observer의 select에서 실행해 작은 pan의 네트워크 캐시는 공유하되, 지도와
 * 테이블에는 화면 밖 POI 및 padded bbox의 total이 노출되지 않게 한다.
 */
export function filterPublicCurationGroupsToViewport(
  response: PublicCurationGroupsResponse,
  viewportParams: PublicCurationGroupsParams,
): PublicCurationGroupsResponse {
  const bounds = publicCurationViewportBounds(viewportParams);
  if (bounds === null) return response;

  const items = response.data.items.filter((group) => {
    const { lon, lat } = group.feature;
    return (
      typeof lon === "number" &&
      Number.isFinite(lon) &&
      typeof lat === "number" &&
      Number.isFinite(lat) &&
      lon >= bounds.minLon &&
      lon <= bounds.maxLon &&
      lat >= bounds.minLat &&
      lat <= bounds.maxLat
    );
  });
  const page = response.meta.page;
  return {
    ...response,
    data: { items },
    meta: {
      ...response.meta,
      page: page ? { ...page, total: items.length } : page,
    },
  };
}

function mergeGroup(
  existing: PublicCurationGroup,
  incoming: PublicCurationGroup,
): PublicCurationGroup {
  const byItemId = new Map(
    existing.curations.map((item) => [item.curation_item_id, item]),
  );
  for (const item of incoming.curations) {
    byItemId.set(item.curation_item_id, item);
  }
  const curations = Array.from(byItemId.values());
  return { ...incoming, curations, curation_count: curations.length };
}

/**
 * 현재 bbox의 cursor 페이지를 끝까지 누적한다. 공개 큐레이션은 Feature 그룹 수가
 * 수천 단위라 지도에 필요한 범위에서는 이 방식이 가장 단순하며, 고정 페이지 상한으로
 * 뒷부분을 조용히 버리지 않는다.
 */
export async function fetchAllPublicCurationGroups(
  params: PublicCurationGroupsParams,
  signal?: AbortSignal,
): Promise<PublicCurationGroupsResponse> {
  const groups = new Map<string, PublicCurationGroup>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let lastResponse: PublicCurationGroupsPageResponse | null = null;
  let pagesLoaded = 0;

  for (;;) {
    const response: PublicCurationGroupsPageResponse =
      await getJson<PublicCurationGroupsPageResponse>(
        pathWithQuery("/v1/curations", {
          ...params,
          page_size: params.page_size ?? 500,
          cursor,
        }),
        { signal },
      );
    lastResponse = response;
    pagesLoaded += 1;

    for (const group of response.data.items) {
      const existing = groups.get(group.feature.feature_id);
      groups.set(
        group.feature.feature_id,
        existing ? mergeGroup(existing, group) : group,
      );
    }

    const nextCursor: string | null = response.meta.page?.next_cursor ?? null;
    if (nextCursor === null) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("큐레이션 API가 같은 cursor를 반복해서 반환했습니다.");
    }
    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }

  return {
    data: { items: Array.from(groups.values()) },
    meta: {
      ...(lastResponse?.meta ?? {}),
      page: lastResponse?.meta.page
        ? { ...lastResponse.meta.page, next_cursor: null }
        : lastResponse?.meta.page,
    },
    pages_loaded: pagesLoaded,
  };
}

export function usePublicCurationGroups(
  params: PublicCurationGroupsParams,
  options: { enabled?: boolean } = {},
) {
  const stableParams = stabilizePublicCurationGroupsParams(params);
  const selectViewportGroups = useCallback(
    (response: PublicCurationGroupsResponse) =>
      filterPublicCurationGroupsToViewport(response, {
        min_lat: params.min_lat,
        min_lon: params.min_lon,
        max_lat: params.max_lat,
        max_lon: params.max_lon,
      }),
    [params.max_lat, params.max_lon, params.min_lat, params.min_lon],
  );
  return useQuery<PublicCurationGroupsResponse, Error>({
    queryKey: ["public-curation-groups", stableParams] as const,
    queryFn: ({ signal }) => fetchAllPublicCurationGroups(stableParams, signal),
    select: selectViewportGroups,
    enabled: options.enabled ?? true,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function usePublicCurationCollections() {
  return useQuery<PublicCurationCollectionsResponse, Error>({
    queryKey: ["public-curation-collections"] as const,
    queryFn: ({ signal }) => fetchAllPublicCurationCollections(signal),
    staleTime: 60_000,
  });
}

export async function fetchAllPublicCurationCollections(
  signal?: AbortSignal,
): Promise<PublicCurationCollectionsResponse> {
  const items: PublicCurationCollection[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let lastResponse: PublicCurationCollectionsResponse | null = null;
  for (;;) {
    const response: PublicCurationCollectionsResponse =
      await getJson<PublicCurationCollectionsResponse>(
        pathWithQuery("/v1/curations/collections", { page_size: 500, cursor }),
        { signal },
      );
    items.push(...response.data.items);
    lastResponse = response;
    const nextCursor = response.meta.page?.next_cursor ?? null;
    if (nextCursor === null) break;
    if (seenCursors.has(nextCursor)) {
      throw new Error("공개 큐레이션 컬렉션 API가 같은 cursor를 반복했습니다.");
    }
    seenCursors.add(nextCursor);
    cursor = nextCursor;
  }
  return {
    data: { items },
    meta: {
      ...(lastResponse?.meta ?? {}),
      page: lastResponse?.meta.page
        ? { ...lastResponse.meta.page, next_cursor: null }
        : lastResponse?.meta.page,
    },
  };
}
