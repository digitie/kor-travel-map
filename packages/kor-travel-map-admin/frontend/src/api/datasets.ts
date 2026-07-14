/**
 * `/v1/ops/datasets/*` 데이터셋 상태·정책 hooks (ADR-064 T-ADM-C4, 페이지 ②).
 *
 * "지금 갱신"은 datasets 그룹에 숏컷 endpoint를 두지 않고 pipeline 그룹의
 * `POST /v1/ops/pipeline/requests`(provider_dataset scope)를 직접 호출한다
 * (ADR-064 — 리소스 생성 중복 제거).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, postJson, putJson } from "./client";
import type { components, paths } from "./types";

type DatasetSchemas = components["schemas"];

export type OpsDatasetCatalogInfo = DatasetSchemas["OpsDatasetCatalogInfo"];
export type OpsDatasetGridRow = DatasetSchemas["OpsDatasetGridRow"];
export type OpsDatasetsGridResponse = DatasetSchemas["OpsDatasetsGridResponse"];
export type OpsDatasetDetailData = DatasetSchemas["OpsDatasetDetailData"];
export type OpsDatasetDetailResponse = DatasetSchemas["OpsDatasetDetailResponse"];
export type OpsDatasetScopeState = DatasetSchemas["OpsDatasetScopeState"];
export type OpsDatasetRunSummary = DatasetSchemas["OpsDatasetRunSummary"];
export type OpsDatasetEventRecord = DatasetSchemas["OpsDatasetEventRecord"];
export type OpsDatasetPreviewResponse = DatasetSchemas["OpsDatasetPreviewResponse"];
export type OpsDatasetPreviewData = DatasetSchemas["OpsDatasetPreviewData"];
export type OpsDatasetRefreshPolicyResponse =
  DatasetSchemas["OpsDatasetRefreshPolicyResponse"];
export type ProviderRefreshPolicyRecord =
  DatasetSchemas["ProviderRefreshPolicyRecord"];
export type ProviderRefreshPolicyUpsertRequest =
  DatasetSchemas["ProviderRefreshPolicyUpsertRequest"];
export type DatasetRefreshRequestCreateRequest =
  paths["/v1/ops/pipeline/requests"]["post"]["requestBody"]["content"]["application/json"];
export type DatasetRefreshRequestCreateResponse =
  DatasetSchemas["FeatureUpdateRequestCreateResponse"];
export type DatasetRefreshRequestRecord =
  DatasetSchemas["FeatureUpdateRequestRecord"];

/** "지금 갱신" 요청 생성 endpoint — pipeline 그룹(T-ADM-C3) 소유. */
export const DATASET_REFRESH_REQUESTS_PATH = "/v1/ops/pipeline/requests";

function datasetPath(provider: string, dataset: string, suffix = ""): string {
  return (
    `/v1/ops/datasets/${encodeURIComponent(provider)}/` +
    `${encodeURIComponent(dataset)}${suffix}`
  );
}

function fetchOpsDatasets(signal?: AbortSignal): Promise<OpsDatasetsGridResponse> {
  return getJson<OpsDatasetsGridResponse>("/v1/ops/datasets", { signal });
}

function fetchOpsDataset(
  provider: string,
  dataset: string,
  signal?: AbortSignal,
): Promise<OpsDatasetDetailResponse> {
  return getJson<OpsDatasetDetailResponse>(datasetPath(provider, dataset), {
    signal,
  });
}

export function useOpsDatasets() {
  return useQuery<OpsDatasetsGridResponse, Error>({
    queryKey: ["ops-datasets"],
    queryFn: ({ signal }) => fetchOpsDatasets(signal),
    staleTime: 15_000,
  });
}

export function useOpsDataset(
  selection: { provider: string; datasetKey: string } | null,
) {
  return useQuery<OpsDatasetDetailResponse, Error>({
    queryKey: ["ops-dataset", selection?.provider, selection?.datasetKey],
    queryFn: ({ signal }) =>
      fetchOpsDataset(
        selection?.provider as string,
        selection?.datasetKey as string,
        signal,
      ),
    enabled: Boolean(selection),
    staleTime: 10_000,
  });
}

/** 그리드/상세 신선도 무효화 — "지금 갱신" 완료·정책 저장 후 refetch 경로. */
export function invalidateOpsDatasetQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  void queryClient.invalidateQueries({ queryKey: ["ops-datasets"] });
  void queryClient.invalidateQueries({ queryKey: ["ops-dataset"] });
}

export function useUpsertOpsDatasetRefreshPolicyMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    OpsDatasetRefreshPolicyResponse,
    Error,
    { provider: string; datasetKey: string; body: ProviderRefreshPolicyUpsertRequest }
  >({
    mutationFn: ({ provider, datasetKey, body }) =>
      putJson<OpsDatasetRefreshPolicyResponse>(
        datasetPath(provider, datasetKey, "/refresh-policy"),
        body,
      ),
    onSuccess: () => {
      invalidateOpsDatasetQueries(queryClient);
    },
  });
}

export function useOpsDatasetPreviewMutation() {
  return useMutation<
    OpsDatasetPreviewResponse,
    Error,
    { provider: string; datasetKey: string; source: "fixture" | "live" }
  >({
    mutationFn: ({ provider, datasetKey, source }) =>
      postJson<OpsDatasetPreviewResponse>(
        datasetPath(provider, datasetKey, `/preview?source=${source}`),
      ),
  });
}

/**
 * "지금 갱신" — pipeline 그룹에 provider_dataset scope 요청을 생성한다.
 *
 * 생성 후 상태 추적은 drawer가 WS topic `feature_update_request:{id}` +
 * `useDatasetRefreshRequestStatus` 폴링 fallback으로 잇는다(인라인 폐루프).
 */
export function useOpsDatasetRefreshNowMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    DatasetRefreshRequestCreateResponse,
    Error,
    DatasetRefreshRequestCreateRequest
  >({
    mutationFn: (body) =>
      postJson<DatasetRefreshRequestCreateResponse>(
        DATASET_REFRESH_REQUESTS_PATH,
        body,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feature-update-requests"] });
      invalidateOpsDatasetQueries(queryClient);
    },
  });
}

/**
 * `GET /v1/ops/pipeline/executions/update_request/{id}` 응답 — pipeline
 * 그룹(#677)의 생성 타입 바인딩(지금 갱신 상태 추적용).
 */
export type DatasetRefreshExecutionDetailResponse =
  DatasetSchemas["PipelineExecutionDetailResponse"];

function fetchDatasetRefreshExecution(
  requestId: string,
  signal?: AbortSignal,
): Promise<DatasetRefreshExecutionDetailResponse> {
  return getJson<DatasetRefreshExecutionDetailResponse>(
    "/v1/ops/pipeline/executions/update_request/" +
      `${encodeURIComponent(requestId)}?page_size=1`,
    { signal },
  );
}

/**
 * 생성된 갱신 요청 1건의 상태 추적 query (인라인 폐루프).
 *
 * queryKey는 `["feature-update-request", id]` — `api/live.ts`의
 * `feature_update_request:{id}` WS topic invalidation과 같은 키를 써서
 * 실시간 갱신을 그대로 받는다. WS가 꺼진 환경을 위해 queued/running 동안
 * 2s 폴링 fallback을 함께 둔다.
 */
export function useDatasetRefreshRequestStatus(requestId: string | null) {
  return useQuery<DatasetRefreshExecutionDetailResponse, Error>({
    queryKey: ["feature-update-request", requestId],
    queryFn: ({ signal }) =>
      fetchDatasetRefreshExecution(requestId as string, signal),
    enabled: Boolean(requestId),
    refetchInterval: (query) => {
      const status = query.state.data?.data.execution.status;
      return status && ["queued", "running"].includes(status) ? 2_000 : false;
    },
    staleTime: 1_000,
  });
}
