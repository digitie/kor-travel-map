/**
 * `/admin/feature-update-requests/*` 업데이트 요청 queue hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FeatureUpdateSchemas = components["schemas"];
type FeatureUpdateListQuery = NonNullable<
  paths["/admin/feature-update-requests"]["get"]["parameters"]["query"]
>;
type GeneratedFeatureUpdateRequestCreateRequest =
  paths["/admin/feature-update-requests"]["post"]["requestBody"]["content"]["application/json"];

export type FeatureUpdateState = Exclude<
  FeatureUpdateListQuery["state"],
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

function fetchFeatureUpdateRequests(
  params: FeatureUpdateRequestListParams = {},
): Promise<FeatureUpdateRequestListResponse> {
  return getJson<FeatureUpdateRequestListResponse>(
    pathWithQuery("/admin/feature-update-requests", {
      state: params.state,
      scope_type: params.scope_type,
      provider: params.provider,
      dataset_key: params.dataset_key,
      created_from: params.created_from,
      created_to: params.created_to,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchFeatureUpdateRequest(
  requestId: string,
): Promise<FeatureUpdateRequestDetailResponse> {
  return getJson<FeatureUpdateRequestDetailResponse>(
    `/admin/feature-update-requests/${encodeURIComponent(requestId)}`,
  );
}

function createFeatureUpdateRequest(
  body: FeatureUpdateRequestCreateRequest,
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    "/admin/feature-update-requests",
    body,
  );
}

function cancelFeatureUpdateRequest(
  requestId: string,
  body: FeatureUpdateRequestCancelRequest = {},
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    `/admin/feature-update-requests/${encodeURIComponent(requestId)}/cancel`,
    body,
  );
}

function runFeatureUpdateRequestNow(
  requestId: string,
  body: FeatureUpdateRequestRunNowRequest = {},
): Promise<FeatureUpdateRequestCreateResponse> {
  return postJson<FeatureUpdateRequestCreateResponse>(
    `/admin/feature-update-requests/${encodeURIComponent(requestId)}/run-now`,
    body,
  );
}

export function useFeatureUpdateRequests(
  params: FeatureUpdateRequestListParams = {},
) {
  return useQuery<FeatureUpdateRequestListResponse, Error>({
    queryKey: ["feature-update-requests", params],
    queryFn: () => fetchFeatureUpdateRequests(params),
    refetchInterval: (query) => {
      const hasActiveRequest = query.state.data?.data.items.some((item) =>
        ["queued", "running"].includes(item.state),
      );
      return hasActiveRequest ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useFeatureUpdateRequest(requestId: string | null) {
  return useQuery<FeatureUpdateRequestDetailResponse, Error>({
    queryKey: ["feature-update-request", requestId],
    queryFn: () => fetchFeatureUpdateRequest(requestId as string),
    enabled: requestId !== null && requestId.length > 0,
    refetchInterval: (query) => {
      const state = query.state.data?.data.state;
      return state === "queued" || state === "running" ? 2_000 : false;
    },
    staleTime: 2_000,
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
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
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
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      if (data.data.request_id) {
        void queryClient.invalidateQueries({
          queryKey: ["feature-update-request", data.data.request_id],
        });
      }
    },
  });
}
