/**
 * `/v1/admin/feature-update-requests/*` 업데이트 요청 queue hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FeatureUpdateSchemas = components["schemas"];
type FeatureUpdateListQuery = NonNullable<
  paths["/v1/admin/feature-update-requests"]["get"]["parameters"]["query"]
>;
type GeneratedFeatureUpdateRequestCreateRequest =
  paths["/v1/admin/feature-update-requests"]["post"]["requestBody"]["content"]["application/json"];

export type FeatureUpdateStatus = Exclude<
  FeatureUpdateListQuery["status"],
  null | undefined
>;
export type FeatureUpdateRunMode =
  FeatureUpdateSchemas["FeatureUpdateRequestRecord"]["run_mode"];
export type FeatureUpdateScopeMode =
  FeatureUpdateSchemas["CacheTargetKeysScope"]["scope_mode"];
export type FeatureUpdatePoint = FeatureUpdateSchemas["FeatureUpdatePoint"];
export type FeatureUpdateScope = GeneratedFeatureUpdateRequestCreateRequest["scope"];
export type FeatureUpdatePolicy = FeatureUpdateSchemas["FeatureUpdatePolicy"];
export type FeatureUpdateRequestCreateRequest = Omit<
  GeneratedFeatureUpdateRequestCreateRequest,
  "dry_run" | "priority" | "run_mode"
> &
  Partial<
    Pick<
      GeneratedFeatureUpdateRequestCreateRequest,
      "dry_run" | "priority" | "run_mode"
    >
  >;
export type FeatureUpdateRequestRecord =
  FeatureUpdateSchemas["FeatureUpdateRequestRecord"];
export type FeatureUpdateRequestCreateResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestCreateResponse"];
export type FeatureUpdateRequestListResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestListResponse"];
export type FeatureUpdateRequestDetailResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestDetailResponse"];
export type FeatureUpdateRequestListParams = Omit<
  FeatureUpdateListQuery,
  "created_from" | "created_to"
> & {
  created_from?: string | Date;
  created_to?: string | Date;
};
export type FeatureUpdateRequestCancelRequest =
  FeatureUpdateSchemas["FeatureUpdateRequestCancelRequest"];
export type FeatureUpdateRequestRunNowRequest =
  FeatureUpdateSchemas["FeatureUpdateRequestRunNowRequest"];

function invalidateFeatureSurfaces(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["features"] });
  void queryClient.invalidateQueries({ queryKey: ["feature"] });
  void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
}

function fetchFeatureUpdateRequests(
  params: FeatureUpdateRequestListParams = {},
  signal?: AbortSignal,
): Promise<FeatureUpdateRequestListResponse> {
  return getJson<FeatureUpdateRequestListResponse>(
    pathWithQuery("/v1/admin/feature-update-requests", {
      status: params.status,
      scope_type: params.scope_type,
      provider: params.provider,
      dataset_key: params.dataset_key,
      created_from: params.created_from,
      created_to: params.created_to,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

function fetchFeatureUpdateRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<FeatureUpdateRequestDetailResponse> {
  return getJson<FeatureUpdateRequestDetailResponse>(
    `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}`,
    { signal },
  );
}

function createFeatureUpdateRequest(
  body: FeatureUpdateRequestCreateRequest,
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    "/v1/admin/feature-update-requests",
    body,
  );
}

function cancelFeatureUpdateRequest(
  requestId: string,
  body: FeatureUpdateRequestCancelRequest = {},
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}/cancel`,
    body,
  );
}

function runFeatureUpdateRequestNow(
  requestId: string,
  body: FeatureUpdateRequestRunNowRequest = {},
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    `/v1/admin/feature-update-requests/${encodeURIComponent(requestId)}/run-now`,
    body,
  );
}

export function useFeatureUpdateRequests(
  params: FeatureUpdateRequestListParams = {},
) {
  return useQuery<FeatureUpdateRequestListResponse, Error>({
    queryKey: ["feature-update-requests", params],
    queryFn: ({ signal }) => fetchFeatureUpdateRequests(params, signal),
    refetchInterval: (query) => {
      const hasActiveRequest = query.state.data?.data.items.some((item) =>
        ["queued", "running"].includes(item.status),
      );
      return hasActiveRequest ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useFeatureUpdateRequest(requestId: string | null) {
  return useQuery<FeatureUpdateRequestDetailResponse, Error>({
    queryKey: ["feature-update-request", requestId],
    queryFn: ({ signal }) =>
      fetchFeatureUpdateRequest(requestId as string, signal),
    enabled: Boolean(requestId),
    refetchInterval: (query) => {
      const status = query.state.data?.data.status;
      return status && ["queued", "running"].includes(status) ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useCreateFeatureUpdateRequestMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestCreateResponse,
    Error,
    FeatureUpdateRequestCreateRequest
  >({
    mutationFn: createFeatureUpdateRequest,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      if (!variables.dry_run) {
        invalidateFeatureSurfaces(queryClient);
      }
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
    },
  });
}

export function useCancelFeatureUpdateRequestMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestCreateResponse,
    Error,
    { requestId: string; body?: FeatureUpdateRequestCancelRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      cancelFeatureUpdateRequest(requestId, body),
    onSuccess: (data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-request", variables.requestId],
      });
      if (data.data.job_id) {
        void queryClient.invalidateQueries({
          queryKey: ["import-job", data.data.job_id],
        });
      }
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
    },
  });
}

export function useRunFeatureUpdateRequestNowMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestCreateResponse,
    Error,
    { requestId: string; body?: FeatureUpdateRequestRunNowRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      runFeatureUpdateRequestNow(requestId, body),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      invalidateFeatureSurfaces(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      void queryClient.invalidateQueries({ queryKey: ["ops-providers"] });
      if (data.data.request_id) {
        void queryClient.invalidateQueries({
          queryKey: ["feature-update-request", data.data.request_id],
        });
      }
    },
  });
}
