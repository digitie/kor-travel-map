import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, patchJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type CuratedSchemas = components["schemas"];

type AdminCuratedFeaturesQuery = NonNullable<
  paths["/v1/admin/curated-features"]["get"]["parameters"]["query"]
>;
type AdminCuratedSourcesQuery = NonNullable<
  paths["/v1/admin/curated-sources"]["get"]["parameters"]["query"]
>;
type AdminCuratedSourceRulesQuery = NonNullable<
  paths["/v1/admin/curated-source-rules"]["get"]["parameters"]["query"]
>;
type AdminCuratedThemesQuery = NonNullable<
  paths["/v1/admin/curated-themes"]["get"]["parameters"]["query"]
>;

export type CuratedFeature = CuratedSchemas["CuratedFeatureView"];
export type CuratedFeaturesResponse = CuratedSchemas["CuratedFeaturesResponse"];
export type CuratedFeaturePatchRequest =
  CuratedSchemas["CuratedFeaturePatchRequest"];
export type CuratedFeatureResponse = CuratedSchemas["CuratedFeatureResponse"];
export type CuratedFeatureStatusRequest =
  CuratedSchemas["CuratedFeatureStatusRequest"];
export type CuratedSource = CuratedSchemas["CuratedSourceView"];
export type CuratedSourcesResponse = CuratedSchemas["CuratedSourcesResponse"];
export type CuratedSourceRule = CuratedSchemas["CuratedSourceRuleView"];
export type CuratedSourceRulesResponse =
  CuratedSchemas["CuratedSourceRulesResponse"];
export type CuratedSourceRulePatchRequest =
  CuratedSchemas["CuratedSourceRulePatchRequest"];
export type CuratedSourceRuleResponse =
  CuratedSchemas["CuratedSourceRuleResponse"];
export type CuratedTheme = CuratedSchemas["CuratedThemeView"];
export type CuratedThemesResponse = CuratedSchemas["CuratedThemesResponse"];
export type RuleApplyResponse = CuratedSchemas["RuleApplyResponse"];
export type CuratedFeatureDetailSnapshot =
  CuratedSchemas["CuratedFeatureDetailSnapshotView"];
export type CuratedFeatureDetailSnapshotResponse =
  CuratedSchemas["CuratedFeatureDetailSnapshotResponse"];

export type CuratedFeatureStatus = Exclude<
  AdminCuratedFeaturesQuery["curation_status"],
  null | undefined
>;
export type CuratedReusePolicy = Exclude<
  CuratedFeaturePatchRequest["reuse_policy"],
  null | undefined
>;
export type CuratedCurationRelation = Exclude<
  CuratedFeaturePatchRequest["curation_relation"],
  null | undefined
>;
export type CuratedRuleAction = Exclude<
  CuratedSourceRulePatchRequest["default_action"],
  null | undefined
>;

export type AdminCuratedFeaturesParams = AdminCuratedFeaturesQuery;
export type AdminCuratedSourcesParams = AdminCuratedSourcesQuery;
export type AdminCuratedSourceRulesParams = AdminCuratedSourceRulesQuery;
export type AdminCuratedThemesParams = AdminCuratedThemesQuery;

function invalidateCurated(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["curated-features"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-feature-detail"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-source-rules"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-sources"] });
  void queryClient.invalidateQueries({ queryKey: ["curated-themes"] });
}

async function fetchAdminCuratedFeatures(
  params: AdminCuratedFeaturesParams,
  signal?: AbortSignal,
): Promise<CuratedFeaturesResponse> {
  return getJson<CuratedFeaturesResponse>(
    pathWithQuery("/v1/admin/curated-features", {
      theme_id: params.theme_id,
      theme_slug: params.theme_slug,
      source_id: params.source_id,
      provider: params.provider,
      dataset_key: params.dataset_key,
      curation_status: params.curation_status,
      include_archived: params.include_archived,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

export function useAdminCuratedFeatures(params: AdminCuratedFeaturesParams) {
  return useQuery<CuratedFeaturesResponse, Error>({
    queryKey: ["curated-features", params] as const,
    queryFn: ({ signal }) => fetchAdminCuratedFeatures(params, signal),
    staleTime: 30_000,
  });
}

async function fetchAdminCuratedSources(
  params: AdminCuratedSourcesParams,
  signal?: AbortSignal,
): Promise<CuratedSourcesResponse> {
  return getJson<CuratedSourcesResponse>(
    pathWithQuery("/v1/admin/curated-sources", {
      provider: params.provider,
      dataset_key: params.dataset_key,
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

async function fetchAdminCuratedSourceRules(
  params: AdminCuratedSourceRulesParams,
  signal?: AbortSignal,
): Promise<CuratedSourceRulesResponse> {
  return getJson<CuratedSourceRulesResponse>(
    pathWithQuery("/v1/admin/curated-source-rules", {
      theme_id: params.theme_id,
      theme_slug: params.theme_slug,
      source_id: params.source_id,
      provider: params.provider,
      dataset_key: params.dataset_key,
      enabled: params.enabled,
      limit: params.limit,
    }),
    { signal },
  );
}

export function useAdminCuratedSourceRules(
  params: AdminCuratedSourceRulesParams,
) {
  return useQuery<CuratedSourceRulesResponse, Error>({
    queryKey: ["curated-source-rules", params] as const,
    queryFn: ({ signal }) => fetchAdminCuratedSourceRules(params, signal),
    staleTime: 30_000,
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
    `/v1/admin/curated-features/${encodeURIComponent(
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

export function useSelectCuratedFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedFeatureResponse,
    Error,
    { curatedFeatureId: string; body: CuratedFeatureStatusRequest }
  >({
    mutationFn: ({ curatedFeatureId, body }) =>
      postJson<CuratedFeatureResponse>(
        `/v1/admin/curated-features/${encodeURIComponent(
          curatedFeatureId,
        )}/select`,
        body,
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
      postJson<CuratedFeatureResponse>(
        `/v1/admin/curated-features/${encodeURIComponent(
          curatedFeatureId,
        )}/unselect`,
        body,
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
      deleteJson<CuratedFeatureResponse>(
        `/v1/admin/curated-features/${encodeURIComponent(curatedFeatureId)}`,
        body,
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
      patchJson<CuratedFeatureResponse>(
        `/v1/admin/curated-features/${encodeURIComponent(curatedFeatureId)}`,
        body,
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}

export function usePatchCuratedSourceRuleMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    CuratedSourceRuleResponse,
    Error,
    { ruleId: string; body: CuratedSourceRulePatchRequest }
  >({
    mutationFn: ({ ruleId, body }) =>
      patchJson<CuratedSourceRuleResponse>(
        `/v1/admin/curated-source-rules/${encodeURIComponent(ruleId)}`,
        body,
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}

export function useApplyCuratedSourceRuleMutation() {
  const queryClient = useQueryClient();
  return useMutation<RuleApplyResponse, Error, { ruleId: string }>({
    mutationFn: ({ ruleId }) =>
      postJson<RuleApplyResponse>(
        `/v1/admin/curated-source-rules/${encodeURIComponent(ruleId)}/apply`,
      ),
    onSuccess: () => invalidateCurated(queryClient),
  });
}
