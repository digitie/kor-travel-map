/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, patchJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FeatureSchemas = components["schemas"];

export type FeatureSummary = FeatureSchemas["FeatureSummary"];
export type FeaturesInBboxResponse = FeatureSchemas["FeaturesInBboxResponse"];

export interface FeaturesInBboxParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  kinds?: string[];
  limit?: number;
}

async function fetchFeaturesInBbox(
  params: FeaturesInBboxParams,
): Promise<FeaturesInBboxResponse> {
  return getJson<FeaturesInBboxResponse>(
    pathWithQuery("/v1/features", {
      min_lon: params.min_lon,
      min_lat: params.min_lat,
      max_lon: params.max_lon,
      max_lat: params.max_lat,
      limit: params.limit,
      kind: params.kinds,
    }),
  );
}

/**
 * react-query hook — bbox 변화에 따라 자동 refetch. 좌표는 소수 4자리로 양자화해
 * (~11m) 미세 viewport 변동에 의한 과도한 호출을 방지.
 */
export function useFeaturesInBbox(
  params: FeaturesInBboxParams,
  options?: { enabled?: boolean },
) {
  const q4 = (n: number) => Number(n.toFixed(4));
  const key = [
    "features",
    q4(params.min_lon),
    q4(params.min_lat),
    q4(params.max_lon),
    q4(params.max_lat),
    params.kinds?.join(",") ?? "",
    params.limit ?? 1000,
  ] as const;
  return useQuery({
    queryKey: key,
    queryFn: () => fetchFeaturesInBbox(params),
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
  });
}

// ── feature 단건 상세 (`GET /v1/features/{feature_id}`) ────────────────────────

export type FeatureDetail = FeatureSchemas["FeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  FeatureSchemas["FeatureDetailEnvelopeResponse"];
export type FeatureWeatherResponse = FeatureSchemas["FeatureWeatherResponse"];
export type WeatherCardData = FeatureSchemas["WeatherCardData"];
export type WeatherMetric = FeatureSchemas["WeatherMetricOut"];

async function fetchFeatureDetail(featureId: string): Promise<FeatureDetail> {
  const body = await getJson<FeatureDetailEnvelopeResponse>(
    `/v1/features/${encodeURIComponent(featureId)}`,
  );
  return body.data;
}

/** react-query hook — `selectedFeatureId` 변경 시 자동 fetch. */
export function useFeatureDetail(featureId: string | null) {
  return useQuery({
    queryKey: ["feature", featureId] as const,
    queryFn: () => fetchFeatureDetail(featureId as string),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

async function fetchFeatureWeather(
  featureId: string,
  params: { asof?: string | Date | null } = {},
): Promise<FeatureWeatherResponse> {
  return getJson<FeatureWeatherResponse>(
    pathWithQuery(`/v1/features/${encodeURIComponent(featureId)}/weather`, {
      asof: params.asof,
    }),
  );
}

export function useFeatureWeather(
  featureId: string | null,
  params: { asof?: string | Date | null } = {},
) {
  return useQuery<FeatureWeatherResponse, Error>({
    queryKey: ["feature", featureId, "weather", params.asof ?? null] as const,
    queryFn: () => fetchFeatureWeather(featureId as string, params),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

// ── kind 필터 — backend가 받는 7종 (data-model.md §1 FeatureKind) ───────────

export const FEATURE_KINDS = [
  "place",
  "event",
  "notice",
  "price",
  "weather",
  "route",
  "area",
] as const;
export type FeatureKind = (typeof FEATURE_KINDS)[number];

// ── admin feature 목록/비활성화 (`/v1/admin/features`) ───────────────────────

type AdminFeaturesListQuery = NonNullable<
  paths["/v1/admin/features"]["get"]["parameters"]["query"]
>;

export type AdminFeatureSort = NonNullable<AdminFeaturesListQuery["sort"]>;
export type SortOrder = Exclude<
  AdminFeaturesListQuery["order"],
  null | undefined
>;
export type AdminFeatureIssue = FeatureSchemas["AdminFeatureIssueRecord"];
export type AdminFeatureRecord = FeatureSchemas["AdminFeatureRecord"];
export type AdminFeaturesListResponse =
  FeatureSchemas["AdminFeaturesListResponse"];
export type AdminFeaturesListParams = Omit<
  AdminFeaturesListQuery,
  "cursor" | "updated_from" | "updated_to"
> & {
  cursor?: string;
  updated_from?: string | Date;
  updated_to?: string | Date;
};
export type AdminFeatureDeactivateRequest =
  FeatureSchemas["AdminFeatureDeactivateRequest"];
export type AdminFeatureOverride = FeatureSchemas["AdminFeatureOverrideRecord"];
export type AdminFeatureDeactivateResponse =
  FeatureSchemas["AdminFeatureDeactivateResponse"];

type AdminFeatureChangeListQuery = NonNullable<
  paths["/v1/admin/features/change-requests"]["get"]["parameters"]["query"]
>;

export type AdminFeatureChangeStatus = Exclude<
  NonNullable<AdminFeatureChangeListQuery["status"]>[number],
  null | undefined
>;
export type AdminFeatureChangeAction = Exclude<
  NonNullable<AdminFeatureChangeListQuery["action"]>[number],
  null | undefined
>;
export type AdminFeatureChangeRecord =
  FeatureSchemas["AdminFeatureChangeRequestRecord"];
export type AdminFeatureChangeListResponse =
  FeatureSchemas["AdminFeatureChangeListResponse"];
export type AdminFeatureChangeResponse =
  FeatureSchemas["AdminFeatureChangeResponse"];
export type AdminFeatureCreateRequest =
  FeatureSchemas["AdminFeatureCreateRequest"];
export type AdminFeaturePatchRequest =
  FeatureSchemas["AdminFeaturePatchRequest"];
export type AdminFeatureDeleteRequest =
  FeatureSchemas["AdminFeatureDeleteRequest"];
export type AdminFeatureReviewActionRequest =
  FeatureSchemas["AdminFeatureReviewActionRequest"];
export type AdminFeatureChangeListParams = Omit<
  AdminFeatureChangeListQuery,
  "action" | "q" | "status"
> & {
  action?: AdminFeatureChangeAction[];
  q?: string;
  status?: AdminFeatureChangeStatus[];
};

function fetchAdminFeatures(
  params: AdminFeaturesListParams = {},
): Promise<AdminFeaturesListResponse> {
  return getJson<AdminFeaturesListResponse>(
    pathWithQuery("/v1/admin/features", {
      q: params.q,
      kind: params.kind,
      category: params.category,
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      has_coord: params.has_coord,
      has_issue: params.has_issue,
      issue_type: params.issue_type,
      updated_from: params.updated_from,
      updated_to: params.updated_to,
      page_size: params.page_size,
      cursor: params.cursor,
      sort: params.sort,
      order: params.order,
    }),
  );
}

function deactivateAdminFeature(
  featureId: string,
  body: AdminFeatureDeactivateRequest,
): Promise<AdminFeatureDeactivateResponse> {
  return postJson<AdminFeatureDeactivateResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}/deactivate`,
    body,
  );
}

function fetchAdminFeatureChangeRequests(
  params: AdminFeatureChangeListParams = {},
): Promise<AdminFeatureChangeListResponse> {
  return getJson<AdminFeatureChangeListResponse>(
    pathWithQuery("/v1/admin/features/change-requests", {
      status: params.status,
      action: params.action,
      q: params.q,
      page_size: params.page_size,
    }),
  );
}

function createAdminFeature(
  body: AdminFeatureCreateRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>("/v1/admin/features", body);
}

function patchAdminFeature(
  featureId: string,
  body: AdminFeaturePatchRequest,
): Promise<AdminFeatureChangeResponse> {
  return patchJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}`,
    body,
  );
}

function deleteAdminFeature(
  featureId: string,
  body: AdminFeatureDeleteRequest,
): Promise<AdminFeatureChangeResponse> {
  return deleteJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}`,
    body,
  );
}

function approveAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/change-requests/${encodeURIComponent(requestId)}/approve`,
    body,
  );
}

function rejectAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/change-requests/${encodeURIComponent(requestId)}/reject`,
    body,
  );
}

export function useAdminFeatures(params: AdminFeaturesListParams = {}) {
  return useQuery<AdminFeaturesListResponse, Error>({
    queryKey: ["admin-features", params],
    queryFn: () => fetchAdminFeatures(params),
    staleTime: 30_000,
  });
}

export function useDeactivateAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureDeactivateResponse,
    Error,
    { featureId: string; body: AdminFeatureDeactivateRequest }
  >({
    mutationFn: ({ featureId, body }) => deactivateAdminFeature(featureId, body),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["features"] });
      void queryClient.invalidateQueries({
        queryKey: ["feature", variables.featureId],
      });
    },
  });
}

export function useAdminFeatureChangeRequests(
  params: AdminFeatureChangeListParams = {},
) {
  return useQuery<AdminFeatureChangeListResponse, Error>({
    queryKey: ["admin-feature-changes", params],
    queryFn: () => fetchAdminFeatureChangeRequests(params),
    staleTime: 15_000,
  });
}

function invalidateFeatureChangeQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  featureId?: string,
) {
  void queryClient.invalidateQueries({ queryKey: ["admin-feature-changes"] });
  void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
  void queryClient.invalidateQueries({ queryKey: ["features"] });
  if (featureId) {
    void queryClient.invalidateQueries({ queryKey: ["feature", featureId] });
  }
}

export function useCreateAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<AdminFeatureChangeResponse, Error, AdminFeatureCreateRequest>({
    mutationFn: createAdminFeature,
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}

export function usePatchAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { featureId: string; body: AdminFeaturePatchRequest }
  >({
    mutationFn: ({ featureId, body }) => patchAdminFeature(featureId, body),
    onSuccess: (data, variables) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id || variables.featureId,
      ),
  });
}

export function useDeleteAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { featureId: string; body: AdminFeatureDeleteRequest }
  >({
    mutationFn: ({ featureId, body }) => deleteAdminFeature(featureId, body),
    onSuccess: (data, variables) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id || variables.featureId,
      ),
  });
}

export function useApproveAdminFeatureChangeMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { requestId: string; body: AdminFeatureReviewActionRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      approveAdminFeatureChangeRequest(requestId, body),
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}

export function useRejectAdminFeatureChangeMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { requestId: string; body: AdminFeatureReviewActionRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      rejectAdminFeatureChangeRequest(requestId, body),
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}
