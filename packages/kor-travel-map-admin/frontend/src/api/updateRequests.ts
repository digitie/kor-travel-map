/**
 * `/v1/admin/features/update-requests/*` 업데이트 요청 queue hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiClientError,
  getJson,
  pathWithQuery,
  postJson,
  withIdempotencyKey,
} from "./client";
import {
  canonicalFeatureUpdateIdempotencyBody,
  featureUpdateIdempotencyOperationKey,
} from "./feature-update-idempotency";
import { pipelineCancellationQueryKeys } from "./pipelineCancellationInvalidation";
import { invalidateOpsProviderQueries } from "./providers";
import type { components, paths } from "./types";

type FeatureUpdateSchemas = components["schemas"];
type FeatureUpdateListQuery = NonNullable<
  paths["/v1/admin/features/update-requests"]["get"]["parameters"]["query"]
>;
type GeneratedFeatureUpdateRequestCreateRequest =
  paths["/v1/admin/features/update-requests"]["post"]["requestBody"]["content"]["application/json"];
type GeneratedFeatureUpdateRequestPreviewRequest =
  paths["/v1/admin/features/update-requests/preview"]["post"]["requestBody"]["content"]["application/json"];

export type FeatureUpdateStatus = Exclude<
  FeatureUpdateListQuery["status"],
  null | undefined
>;
export type FeatureUpdateRunMode =
  FeatureUpdateSchemas["FeatureUpdateRequestRecord"]["run_mode"];
export type FeatureUpdateScopeMode =
  FeatureUpdateSchemas["CacheTargetKeysScope"]["scope_mode"];
export type FeatureUpdatePoint = FeatureUpdateSchemas["FeatureUpdatePoint"];
export type FeatureUpdateScope =
  GeneratedFeatureUpdateRequestCreateRequest["scope"];
export type FeatureUpdatePolicy = FeatureUpdateSchemas["FeatureUpdatePolicy"];
export type FeatureUpdateRequestCreateRequest = Omit<
  GeneratedFeatureUpdateRequestCreateRequest,
  "priority" | "run_mode"
> &
  Partial<
    Pick<GeneratedFeatureUpdateRequestCreateRequest, "priority" | "run_mode">
  >;
export type FeatureUpdateRequestPreviewRequest = Omit<
  GeneratedFeatureUpdateRequestPreviewRequest,
  "priority" | "run_mode"
> &
  Partial<
    Pick<GeneratedFeatureUpdateRequestPreviewRequest, "priority" | "run_mode">
  >;
export type FeatureUpdateRequestRecord =
  FeatureUpdateSchemas["FeatureUpdateRequestRecord"];
export type FeatureUpdateRequestCreateResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestCreateResponse"];
export type FeatureUpdateRequestPreviewResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestPreviewResponse"];
export type FeatureUpdateRequestMutationResponse =
  FeatureUpdateSchemas["FeatureUpdateRequestMutationResponse"];
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
export type PipelineCancellationRequest =
  FeatureUpdateSchemas["PipelineCancellationRequest"];
export type PipelineCancellationResponse =
  FeatureUpdateSchemas["PipelineCancellationResponse"];
export type FeatureUpdateRequestRunNowRequest =
  FeatureUpdateSchemas["FeatureUpdateRequestRunNowRequest"];

function invalidateFeatureSurfaces(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  void queryClient.invalidateQueries({ queryKey: ["features"] });
  void queryClient.invalidateQueries({ queryKey: ["feature"] });
  void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
}

function fetchFeatureUpdateRequests(
  params: FeatureUpdateRequestListParams = {},
  signal?: AbortSignal,
): Promise<FeatureUpdateRequestListResponse> {
  return getJson<FeatureUpdateRequestListResponse>(
    pathWithQuery("/v1/admin/features/update-requests", {
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
    `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}`,
    { signal },
  );
}

function createFeatureUpdateRequest(
  body: FeatureUpdateRequestCreateRequest,
): Promise<FeatureUpdateRequestCreateResponse> {
  const canonicalBody = canonicalFeatureUpdateIdempotencyBody(body);
  return featureUpdateIdempotencyOperationKey(
    "admin:update-request:create",
    canonicalBody,
  ).then(
    (operationKey) =>
      withIdempotencyKey(operationKey, (idempotencyKey) =>
        postJson<FeatureUpdateRequestCreateResponse>(
          "/v1/admin/features/update-requests",
          canonicalBody,
          { headers: { "Idempotency-Key": idempotencyKey } },
        ),
      ),
  );
}

function previewFeatureUpdateRequest(
  body: FeatureUpdateRequestPreviewRequest,
): Promise<FeatureUpdateRequestPreviewResponse> {
  return postJson<FeatureUpdateRequestPreviewResponse>(
    "/v1/admin/features/update-requests/preview",
    body,
  );
}

function cancelFeatureUpdateRequest(
  requestId: string,
  body: PipelineCancellationRequest = {},
): Promise<PipelineCancellationResponse> {
  return postJson<PipelineCancellationResponse>(
    `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}/cancel`,
    body,
  );
}

function runFeatureUpdateRequestNow(
  requestId: string,
  body: FeatureUpdateRequestRunNowRequest = {},
): Promise<FeatureUpdateRequestMutationResponse> {
  return postJson<FeatureUpdateRequestMutationResponse>(
    `/v1/admin/features/update-requests/${encodeURIComponent(requestId)}/run-now`,
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
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      invalidateFeatureSurfaces(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      invalidateOpsProviderQueries(queryClient);
    },
  });
}

export function usePreviewFeatureUpdateRequestMutation() {
  return useMutation<
    FeatureUpdateRequestPreviewResponse,
    Error,
    FeatureUpdateRequestPreviewRequest
  >({
    mutationFn: previewFeatureUpdateRequest,
  });
}

export function useCancelFeatureUpdateRequestMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PipelineCancellationResponse,
    ApiClientError,
    { requestId: string; body?: PipelineCancellationRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      cancelFeatureUpdateRequest(requestId, body),
    onSettled: (data, _error, variables) => {
      // 409/502/503도 durable cancellation attempt를 만들 수 있으므로 항상 reload한다.
      for (const queryKey of pipelineCancellationQueryKeys(
        data?.data.members,
        data?.data.root,
      )) {
        void queryClient.invalidateQueries({
          queryKey,
        });
      }
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-request", variables.requestId],
      });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      invalidateOpsProviderQueries(queryClient);
    },
  });
}

export function useRunFeatureUpdateRequestNowMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestMutationResponse,
    Error,
    { requestId: string; body?: FeatureUpdateRequestRunNowRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      runFeatureUpdateRequestNow(requestId, body),
    onSuccess: (data, variables) => {
      // run-now는 새 요청을 만들지 않고 기존 canonical request의
      // dispatch 의도를 갱신한다. 동일 identity의 상세 cache를 즉시 교체한다.
      queryClient.setQueryData<FeatureUpdateRequestDetailResponse>(
        ["feature-update-request", variables.requestId],
        data,
      );
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      invalidateFeatureSurfaces(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["providers"] });
      invalidateOpsProviderQueries(queryClient);
    },
  });
}
