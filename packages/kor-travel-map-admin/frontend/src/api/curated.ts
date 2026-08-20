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

export type CuratedSource = CuratedSchemas["CuratedSourceView"];
export type CuratedSourcesResponse = CuratedSchemas["CuratedSourcesResponse"];
export type CuratedTheme = CuratedSchemas["CuratedThemeView"];
export type CuratedThemesResponse = CuratedSchemas["CuratedThemesResponse"];

export type AdminCuratedSourcesParams = AdminCuratedSourcesQuery;
export type AdminCuratedThemesParams = AdminCuratedThemesQuery;

// T-VN-40C: legacy `curated_features` 표와 그 read hook(useAdminCuratedFeature /
// useCuratedFeatureDetailSnapshot)은 물리 제거됐다. 이 모듈에는 canonical
// source/theme 카탈로그 read hook만 남는다 — feature 단위 큐레이션 편집·조회는
// `./curations`(collection/item command)가 정본이다.

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
