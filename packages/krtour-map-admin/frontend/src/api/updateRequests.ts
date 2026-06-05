/**
 * `/admin/feature-update-requests/*` 업데이트 요청 queue hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";

export type FeatureUpdateState =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled";
export type FeatureUpdateRunMode = "queued" | "now";
export type FeatureUpdateScopeMode = "center_radius" | "sigungu_by_radius";

export interface FeatureUpdatePoint {
  lon: number;
  lat: number;
}

export type FeatureUpdateScope =
  | {
      type: "feature_ids";
      feature_ids: string[];
    }
  | {
      type: "center_radius";
      center: FeatureUpdatePoint;
      radius_km: number;
    }
  | {
      type: "sigungu_by_radius";
      center: FeatureUpdatePoint;
      radius_km: number;
      match?: "intersects" | "contains_center" | "feature_sigungu";
    }
  | {
      type: "bbox";
      min_lon: number;
      min_lat: number;
      max_lon: number;
      max_lat: number;
    }
  | {
      type: "provider_dataset";
      provider: string;
      dataset_key: string;
      sync_scope?: string | null;
    }
  | {
      type: "cache_target_keys";
      external_system: string;
      target_keys: string[];
      radius_km?: number | null;
      scope_mode?: FeatureUpdateScopeMode;
    };

export interface FeatureUpdatePolicy {
  mode?: "refresh_existing" | null;
  include_inactive?: boolean | null;
  force_provider_call?: boolean | null;
  dedup_after_load?: boolean | null;
  consistency_check_after_load?: boolean | null;
  prevent_provider_reactivation?: boolean | null;
}

export interface FeatureUpdateRequestCreateRequest {
  scope: FeatureUpdateScope;
  providers?: string[];
  dataset_keys?: string[];
  update_policy?: FeatureUpdatePolicy;
  run_mode?: FeatureUpdateRunMode;
  priority?: number;
  dry_run?: boolean;
  operator?: string | null;
  reason?: string | null;
}

export interface FeatureUpdateRequestRecord {
  request_id: string | null;
  scope_type: string;
  scope: Record<string, unknown>;
  providers: string[];
  dataset_keys: string[];
  update_policy: Record<string, unknown>;
  run_mode: FeatureUpdateRunMode;
  priority: number;
  state: string;
  dry_run: boolean;
  matched_scope: Record<string, unknown>;
  job_id: string | null;
  dagster_run_id: string | null;
  operator: string | null;
  reason: string | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
  status_url: string | null;
}

export interface FeatureUpdateRequestCreateResponse {
  data: FeatureUpdateRequestRecord;
  meta: {
    duration_ms: number;
  };
}

export interface FeatureUpdateRequestListResponse {
  count: number;
  items: FeatureUpdateRequestRecord[];
  next_cursor: string | null;
}

export interface FeatureUpdateRequestListParams {
  state?: FeatureUpdateState;
  scope_type?: string;
  provider?: string;
  dataset_key?: string;
  created_from?: string | Date;
  created_to?: string | Date;
  page_size?: number;
  cursor?: string;
}

export interface FeatureUpdateRequestCancelRequest {
  error_message?: string | null;
}

export interface FeatureUpdateRequestRunNowRequest {
  priority?: number | null;
  operator?: string | null;
  reason?: string | null;
}

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
): Promise<FeatureUpdateRequestRecord> {
  return getJson<FeatureUpdateRequestRecord>(
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
      const hasActiveRequest = query.state.data?.items.some((item) =>
        ["queued", "running"].includes(item.state),
      );
      return hasActiveRequest ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useFeatureUpdateRequest(requestId: string | null) {
  return useQuery<FeatureUpdateRequestRecord, Error>({
    queryKey: ["feature-update-request", requestId],
    queryFn: () => fetchFeatureUpdateRequest(requestId as string),
    enabled: requestId !== null && requestId.length > 0,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
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
