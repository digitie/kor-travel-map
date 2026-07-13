import { useQuery } from "@tanstack/react-query";

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
  source_record_key: string | null;
  external_item_id: string;
  place_name: string;
  address_hint: string | null;
  status: CurationItemStatus;
  sort_order: number;
  item_title: string | null;
  item_summary: string | null;
  curation_relation: CurationRelation;
  reuse_policy: CurationReusePolicy;
  metadata: Record<string, unknown>;
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
  metadata: Record<string, unknown>;
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
  return useQuery<PublicCurationGroupsResponse, Error>({
    queryKey: ["public-curation-groups", params] as const,
    queryFn: ({ signal }) => fetchAllPublicCurationGroups(params, signal),
    enabled: options.enabled ?? true,
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
