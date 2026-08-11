import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteJson,
  domainCommandSlot,
  getJson,
  patchJson,
  pathWithQuery,
  postJson,
  withDomainIdempotencySubmission,
} from "./client";
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

function invalidateCurated(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["curated-features"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-feature"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-feature-detail"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-source-rules"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-sources"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-themes"] });
}


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

export function useSelectCuratedFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedFeatureResponse,
    Error,
    { curatedFeatureId: string; body: CuratedFeatureStatusRequest }
  >({
    mutationFn: ({ curatedFeatureId, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curated-feature.select", curatedFeatureId),
        { curatedFeatureId, body },
        (submission, idempotencyKey) =>
          postJson<CuratedFeatureResponse>(
            `/v1/admin/features/curated/${encodeURIComponent(
              submission.curatedFeatureId,
            )}/select`,
            submission.body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}

export function useUnselectCuratedFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedFeatureResponse,
    Error,
    { curatedFeatureId: string; body: CuratedFeatureStatusRequest }
  >({
    mutationFn: ({ curatedFeatureId, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curated-feature.unselect", curatedFeatureId),
        { curatedFeatureId, body },
        (submission, idempotencyKey) =>
          postJson<CuratedFeatureResponse>(
            `/v1/admin/features/curated/${encodeURIComponent(
              submission.curatedFeatureId,
            )}/unselect`,
            submission.body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}

export function useArchiveCuratedFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedFeatureResponse,
    Error,
    { curatedFeatureId: string; body: CuratedFeatureStatusRequest }
  >({
    mutationFn: ({ curatedFeatureId, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curated-feature.delete", curatedFeatureId),
        { curatedFeatureId, body },
        (submission, idempotencyKey) =>
          deleteJson<CuratedFeatureResponse>(
            `/v1/admin/features/curated/${encodeURIComponent(
              submission.curatedFeatureId,
            )}`,
            submission.body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}

export function usePatchCuratedFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedFeatureResponse,
    Error,
    { curatedFeatureId: string; body: CuratedFeaturePatchRequest }
  >({
    mutationFn: ({ curatedFeatureId, body }) =>
      withDomainIdempotencySubmission(
        domainCommandSlot("admin.curated-feature.patch", curatedFeatureId),
        { curatedFeatureId, body },
        (submission, idempotencyKey) =>
          patchJson<CuratedFeatureResponse>(
            `/v1/admin/features/curated/${encodeURIComponent(
              submission.curatedFeatureId,
            )}`,
            submission.body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}
