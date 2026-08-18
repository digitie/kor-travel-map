import { useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type CuratedSchemas = components["schemas"];

type AdminCuratedSourcesQuery = NonNullable<
  paths["/v1/admin/curated-sources"]["get"]["parameters"]["query"]
>;
type AdminCuratedThemesQuery = NonNullable<
  paths["/v1/admin/curated-themes"]["get"]["parameters"]["query"]
>;

export type CuratedFeature = CuratedSchemas["CuratedFeatureView"];
export type CuratedFeaturePatchRequest =
  CuratedSchemas["CuratedFeaturePatchRequest"];
export type CuratedFeatureResponse = CuratedSchemas["CuratedFeatureResponse"];
export type CuratedFeatureStatusRequest =
  CuratedSchemas["CuratedFeatureStatusRequest"];
export type CuratedSource = CuratedSchemas["CuratedSourceView"];
export type CuratedSourcesResponse = CuratedSchemas["CuratedSourcesResponse"];
export type CuratedTheme = CuratedSchemas["CuratedThemeView"];
export type CuratedThemesResponse = CuratedSchemas["CuratedThemesResponse"];
export type CuratedFeatureDetailSnapshot =
  CuratedSchemas["CuratedFeatureDetailSnapshotView"];
export type CuratedFeatureDetailSnapshotResponse =
  CuratedSchemas["CuratedFeatureDetailSnapshotResponse"];
export type CuratedPlaceSearchHit = CuratedSchemas["PlaceSearchHitView"];
export type CuratedPlaceSearchResponse =
  CuratedSchemas["CuratedPlaceSearchResponse"];

export type CuratedReusePolicy = Exclude<
  CuratedFeaturePatchRequest["reuse_policy"],
  null | undefined
>;
export type CuratedCurationRelation = Exclude<
  CuratedFeaturePatchRequest["curation_relation"],
  null | undefined
>;
export type AdminCuratedSourcesParams = AdminCuratedSourcesQuery;
export type AdminCuratedThemesParams = AdminCuratedThemesQuery;

// T-VN-40A: legacy `curated_features` write mutation(select/unselect/archive/patch)은 fence로
// 410이 됐고 여기서 삭제했다. 이 모듈은 read hook만 남는다 — 40C에서 legacy 표와 함께 지운다.
// canonical 편집은 `./curations`(collection/item command)다.


async function fetchAdminCuratedFeature(
  curatedFeatureId: string,
  signal?: AbortSignal,
): Promise<CuratedFeatureResponse> {
  return getJson<CuratedFeatureResponse>(
    `/v1/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`,
    { signal },
  );
}

export function useAdminCuratedFeature(curatedFeatureId: string | null) {
  return useQuery<CuratedFeatureResponse, Error>({
    queryKey: ["curated-feature", curatedFeatureId] as const,
    queryFn: ({ signal }) =>
      fetchAdminCuratedFeature(curatedFeatureId as string, signal),
    enabled: curatedFeatureId !== null && curatedFeatureId.length > 0,
    staleTime: 30_000,
  });
}
async function fetchAdminCuratedSources(
  params: AdminCuratedSourcesParams,
  signal?: AbortSignal,
): Promise<CuratedSourcesResponse> {
  return getJson<CuratedSourcesResponse>(
    pathWithQuery("/v1/admin/curated-sources", {
      provider_dataset_id: params.provider_dataset_id,
      provider_status: params.provider_status,
      limit: params.limit,
    }),
    { signal },
  );
}

export function useAdminCuratedSources(
  params: AdminCuratedSourcesParams = { limit: 200 },
) {
  return useQuery<CuratedSourcesResponse, Error>({
    queryKey: ["curated-sources", params] as const,
    queryFn: ({ signal }) => fetchAdminCuratedSources(params, signal),
    staleTime: 60_000,
  });
}


async function fetchAdminCuratedThemes(
  params: AdminCuratedThemesParams,
  signal?: AbortSignal,
): Promise<CuratedThemesResponse> {
  return getJson<CuratedThemesResponse>(
    pathWithQuery("/v1/admin/curated-themes", {
      visibility: params.visibility,
      theme_group: params.theme_group,
      limit: params.limit,
    }),
    { signal },
  );
}

export function useAdminCuratedThemes(
  params: AdminCuratedThemesParams = { limit: 200 },
) {
  return useQuery<CuratedThemesResponse, Error>({
    queryKey: ["curated-themes", params] as const,
    queryFn: ({ signal }) => fetchAdminCuratedThemes(params, signal),
    staleTime: 60_000,
  });
}

async function fetchCuratedFeatureDetailSnapshot(
  curatedFeatureId: string,
  signal?: AbortSignal,
): Promise<CuratedFeatureDetailSnapshotResponse> {
  return getJson<CuratedFeatureDetailSnapshotResponse>(
    `/v1/admin/features/curated/${encodeURIComponent(
      curatedFeatureId,
    )}/detail-snapshot`,
    { signal },
  );
}

export function useCuratedFeatureDetailSnapshot(curatedFeatureId: string | null) {
  return useQuery<CuratedFeatureDetailSnapshotResponse, Error>({
    queryKey: ["curated-feature-detail", curatedFeatureId] as const,
    queryFn: ({ signal }) =>
      fetchCuratedFeatureDetailSnapshot(curatedFeatureId as string, signal),
    enabled: curatedFeatureId !== null && curatedFeatureId.length > 0,
    staleTime: 30_000,
  });
}

async function fetchCuratedFeaturePlaceSearch(
  curatedFeatureId: string,
  query: string,
  signal?: AbortSignal,
): Promise<CuratedPlaceSearchResponse> {
  return getJson<CuratedPlaceSearchResponse>(
    pathWithQuery(
      `/v1/admin/features/curated/${encodeURIComponent(
        curatedFeatureId,
      )}/place-search`,
      { q: query },
    ),
    { signal },
  );
}

export function useCuratedFeaturePlaceSearch(
  curatedFeatureId: string | null,
  query: string,
  enabled: boolean,
) {
  return useQuery<CuratedPlaceSearchResponse, Error>({
    queryKey: ["curated-feature-place-search", curatedFeatureId, query] as const,
    queryFn: ({ signal }) =>
      fetchCuratedFeaturePlaceSearch(curatedFeatureId as string, query, signal),
    enabled:
      enabled &&
      curatedFeatureId !== null &&
      curatedFeatureId.length > 0 &&
      query.trim().length > 0,
    staleTime: 60_000,
  });
}
