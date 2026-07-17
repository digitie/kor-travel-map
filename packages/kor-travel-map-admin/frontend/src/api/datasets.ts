/**
 * `/v1/ops/datasets/*` 데이터셋 상태·정책 hooks (ADR-064 T-ADM-C4, 페이지 ②).
 *
 * "지금 갱신"은 datasets 그룹에 숏컷 endpoint를 두지 않고 pipeline 그룹의
 * `POST /v1/ops/pipeline/requests`(provider_dataset scope)를 직접 호출한다
 * (ADR-064 — 리소스 생성 중복 제거).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiClientError,
  getJson,
  idempotencyOperationKey,
  pathWithQuery,
  postJson,
  putJson,
  withIdempotencyKey,
} from "./client";
import type { components, paths } from "./types";

type DatasetSchemas = components["schemas"];

export type OpsDatasetCatalogInfo = DatasetSchemas["OpsDatasetCatalogInfo"];
export type OpsDatasetGridRow = DatasetSchemas["OpsDatasetGridRow"];
export type OpsDatasetsGridResponse = DatasetSchemas["OpsDatasetsGridResponse"];
export type OpsDatasetDetailData = DatasetSchemas["OpsDatasetDetailData"];
export type OpsDatasetDetailResponse = DatasetSchemas["OpsDatasetDetailResponse"];
export type OpsDatasetScopeState = DatasetSchemas["OpsDatasetScopeState"];
export type OpsDatasetLatestExecution =
  DatasetSchemas["OpsDatasetLatestExecution"];
export type OpsDatasetScopeRefreshCapability =
  DatasetSchemas["OpsDatasetScopeRefreshCapability"];
export type OpsDatasetEventRecord = DatasetSchemas["OpsDatasetEventRecord"];
export type OpsDatasetFreshness = DatasetSchemas["OpsDatasetFreshness"];
export type OpsDatasetPreviewRequest =
  DatasetSchemas["OpsDatasetPreviewRequest"];
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

type DatasetDetailQuery = NonNullable<
  paths["/v1/ops/datasets/detail"]["get"]["parameters"]["query"]
>;
type DatasetPreviewQuery = NonNullable<
  paths["/v1/ops/datasets/preview"]["post"]["parameters"]["query"]
>;
type DatasetRefreshPolicyQuery = NonNullable<
  paths["/v1/ops/datasets/refresh-policy"]["put"]["parameters"]["query"]
>;
type PipelineExecutionDetailQuery = NonNullable<
  paths["/v1/ops/pipeline/executions/{kind}/{execution_id}"]["get"]["parameters"]["query"]
>;

export type DatasetRefreshNowInput = {
  provider: string;
  datasetKey: string;
  /** `null`은 dataset-wide 요청이며 target selector에는 허용하지 않는다. */
  syncScope: string | null;
  priority?: number;
  reason?: string | null;
};

export type DatasetRefreshScopeDecision =
  | { allowed: true; syncScope: string | null }
  | { allowed: false; reason: string };

export type DatasetRefreshConflict = {
  code: string;
  requestId: string;
  status: string | null;
  detailUrl: string | null;
};

/** "지금 갱신" 요청 생성 endpoint — pipeline 그룹(T-ADM-C3) 소유. */
export const DATASET_REFRESH_REQUESTS_PATH = "/v1/ops/pipeline/requests";

function datasetQueryPath(
  path:
    | "/v1/ops/datasets/detail"
    | "/v1/ops/datasets/preview"
    | "/v1/ops/datasets/refresh-policy",
  query: DatasetDetailQuery | DatasetPreviewQuery | DatasetRefreshPolicyQuery,
): string {
  return pathWithQuery(path, {
    provider: query.provider,
    dataset_key: query.dataset_key,
    ...("sync_scope" in query ? { sync_scope: query.sync_scope } : {}),
  });
}

function fetchOpsDatasets(signal?: AbortSignal): Promise<OpsDatasetsGridResponse> {
  return getJson<OpsDatasetsGridResponse>("/v1/ops/datasets", { signal });
}

export function fetchOpsDataset(
  provider: string,
  dataset: string,
  syncScope: string,
  signal?: AbortSignal,
): Promise<OpsDatasetDetailResponse> {
  return getJson<OpsDatasetDetailResponse>(
    datasetQueryPath("/v1/ops/datasets/detail", {
      provider,
      dataset_key: dataset,
      sync_scope: syncScope,
    }),
    { signal },
  );
}

/**
 * 서버 capability를 제출 가능한 `sync_scope`로 해석한다.
 *
 * 조합이 모순되거나 target scope가 현재 allow-list에서 빠졌으면 fail-closed한다.
 * 일반 dataset은 선택 scope를 지원하지 않으므로 `null`을 보내고 서버가
 * `dataset_wide` effective scope로 정규화하게 한다.
 */
export function resolveDatasetRefreshScope(
  capability: OpsDatasetScopeRefreshCapability | null | undefined,
  selectedSyncScope: string,
  providerStateDefaultScope: string | null | undefined,
): DatasetRefreshScopeDecision {
  if (!capability) {
    return { allowed: false, reason: "갱신 scope capability가 없습니다." };
  }
  if (capability.effect === "dataset_wide") {
    if (
      capability.selector !== "none" ||
      capability.supported ||
      capability.default_sync_scope !== "dataset_wide" ||
      capability.allowed_sync_scopes.length > 0 ||
      !providerStateDefaultScope ||
      selectedSyncScope !== providerStateDefaultScope
    ) {
      return { allowed: false, reason: "dataset-wide scope 계약이 모순됩니다." };
    }
    return { allowed: true, syncScope: null };
  }
  if (
    capability.selector !== "poi_cache_targets" ||
    !capability.supported ||
    capability.allowed_sync_scopes.length === 0 ||
    !capability.allowed_sync_scopes.includes(capability.default_sync_scope)
  ) {
    return { allowed: false, reason: capability.reason ?? "선택 scope 갱신을 지원하지 않습니다." };
  }
  if (!capability.allowed_sync_scopes.includes(selectedSyncScope)) {
    return {
      allowed: false,
      reason: "현재 활성 target에 포함되지 않은 sync scope입니다.",
    };
  }
  return { allowed: true, syncScope: selectedSyncScope };
}

/**
 * 선택 행과 다른 scope의 canonical operation이 drawer에 섞이지 않게 한다.
 *
 * 이력 조회는 mutation capability의 현재 allow-list와 독립적이다. target이 삭제되어
 * 더는 갱신할 수 없는 stale external scope와 catalog에서 사라진 orphan scope도 과거
 * 실행을 확인할 수 있어야 한다. 서버가 dataset-wide라고 명시한 canonical 기본
 * state만 저장 전환기의 ``NULL``/``dataset_wide``를 함께 취급한다.
 */
export function filterDatasetRecentRuns(
  runs: readonly OpsDatasetLatestExecution[],
  selectedSyncScope: string,
  capability: OpsDatasetScopeRefreshCapability | null | undefined,
  providerStateDefaultScope: string | null | undefined,
): OpsDatasetLatestExecution[] {
  const isCanonicalDatasetWideState =
    capability?.effect === "dataset_wide" &&
    selectedSyncScope === providerStateDefaultScope;
  const isOrphanDefaultState = !capability && selectedSyncScope === "default";
  if (isCanonicalDatasetWideState || isOrphanDefaultState) {
    return runs.filter(
      (run) =>
        run.sync_scope === selectedSyncScope ||
        run.sync_scope === null ||
        run.sync_scope === "dataset_wide",
    );
  }
  return runs.filter((run) => run.sync_scope === selectedSyncScope);
}

export function buildDatasetRefreshNowRequest({
  provider,
  datasetKey,
  syncScope,
  priority = 75,
  reason = "dataset refresh from ops/datasets",
}: DatasetRefreshNowInput): DatasetRefreshRequestCreateRequest {
  return {
    scope: {
      type: "provider_dataset",
      provider,
      dataset_key: datasetKey,
      ...(syncScope === null ? {} : { sync_scope: syncScope }),
    },
    run_mode: "now",
    priority,
    reason,
  };
}

export async function createDatasetRefreshNow(
  input: DatasetRefreshNowInput,
): Promise<DatasetRefreshRequestCreateResponse> {
  const body = buildDatasetRefreshNowRequest(input);
  const operationKey = await idempotencyOperationKey(
    "datasets:update-request:create",
    body,
  );
  return withIdempotencyKey(operationKey, (idempotencyKey) =>
    postJson<DatasetRefreshRequestCreateResponse>(
      DATASET_REFRESH_REQUESTS_PATH,
      body,
      { headers: { "Idempotency-Key": idempotencyKey } },
    ),
  );
}

/** 409 ProblemDetail의 기존 canonical request 링크를 안전하게 추출한다. */
export function datasetRefreshConflict(
  error: unknown,
): DatasetRefreshConflict | null {
  if (!(error instanceof ApiClientError) || error.status !== 409) {
    return null;
  }
  const problem = error.problem;
  if (!problem) {
    return null;
  }
  if (
    problem.code !== "ACTIVE_SCOPE_CONFLICT" &&
    problem.code !== "REQUEST_NOT_DISPATCHABLE"
  ) {
    return null;
  }
  const details = problem.details;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const requestId = "request_id" in details ? details.request_id : null;
  if (typeof requestId !== "string" || requestId.length === 0) {
    return null;
  }
  const status = "status" in details ? details.status : null;
  const detailUrl = "detail_url" in details ? details.detail_url : null;
  return {
    code: problem.code,
    requestId,
    status: typeof status === "string" ? status : null,
    detailUrl: typeof detailUrl === "string" ? detailUrl : null,
  };
}

export function hasActiveDatasetExecution(
  response: OpsDatasetsGridResponse | undefined,
): boolean {
  return Boolean(
    response?.data.items.some((row) => {
      const execution = row.latest_execution;
      return (
        execution !== null &&
        ([execution.status, execution.pair_status] as const).some((status) =>
          ["queued", "running"].includes(status),
        )
      );
    }),
  );
}

export function hasActiveDatasetDetailExecution(
  response: OpsDatasetDetailResponse | undefined,
): boolean {
  return response?.data.recent_runs.some((execution) =>
    [execution.status, execution.pair_status].some((status) =>
      ["queued", "running"].includes(status),
    ),
  ) ?? false;
}

export function useOpsDatasets() {
  return useQuery<OpsDatasetsGridResponse, Error>({
    queryKey: ["ops-datasets"],
    queryFn: ({ signal }) => fetchOpsDatasets(signal),
    // C7A의 global live invalidation 이전에도 진입 전부터 존재한 active 작업이
    // terminal로 바뀌면 버튼 차단이 자동 해제되어야 한다.
    refetchInterval: (query) =>
      hasActiveDatasetExecution(query.state.data) ? 2_000 : false,
    staleTime: 15_000,
  });
}

export function useOpsDataset(
  selection: {
    provider: string;
    datasetKey: string;
    syncScope: string;
  } | null,
) {
  return useQuery<OpsDatasetDetailResponse, Error>({
    queryKey: [
      "ops-dataset",
      selection?.provider,
      selection?.datasetKey,
      selection?.syncScope,
    ],
    queryFn: ({ signal }) =>
      fetchOpsDataset(
        selection?.provider as string,
        selection?.datasetKey as string,
        selection?.syncScope as string,
        signal,
      ),
    enabled: Boolean(selection),
    refetchInterval: (query) =>
      hasActiveDatasetDetailExecution(query.state.data) ? 2_000 : false,
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
      upsertOpsDatasetRefreshPolicy(provider, datasetKey, body),
    onSuccess: () => {
      invalidateOpsDatasetQueries(queryClient);
    },
  });
}

export function upsertOpsDatasetRefreshPolicy(
  provider: string,
  datasetKey: string,
  body: ProviderRefreshPolicyUpsertRequest,
): Promise<OpsDatasetRefreshPolicyResponse> {
  return putJson<OpsDatasetRefreshPolicyResponse>(
    datasetQueryPath("/v1/ops/datasets/refresh-policy", {
      provider,
      dataset_key: datasetKey,
    }),
    body,
  );
}

export function useOpsDatasetPreviewMutation() {
  // #678 typed preview 계약 — body(`source=fixture`, `max_items`)만 받는다.
  return useMutation<
    OpsDatasetPreviewResponse,
    Error,
    { provider: string; datasetKey: string; body: OpsDatasetPreviewRequest }
  >({
    mutationFn: ({ provider, datasetKey, body }) =>
      previewOpsDataset(provider, datasetKey, body),
  });
}

export function previewOpsDataset(
  provider: string,
  datasetKey: string,
  body: OpsDatasetPreviewRequest,
): Promise<OpsDatasetPreviewResponse> {
  return postJson<OpsDatasetPreviewResponse>(
    datasetQueryPath("/v1/ops/datasets/preview", {
      provider,
      dataset_key: datasetKey,
    }),
    body,
  );
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
    ApiClientError,
    DatasetRefreshNowInput
  >({
    mutationFn: createDatasetRefreshNow,
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

export function datasetRefreshExecutionQueryKey(requestId: string | null) {
  return ["feature-update-request", requestId, "pipeline-execution"] as const;
}

export function fetchDatasetRefreshExecution(
  requestId: string,
  signal?: AbortSignal,
): Promise<DatasetRefreshExecutionDetailResponse> {
  return getJson<DatasetRefreshExecutionDetailResponse>(
    pathWithQuery(
      "/v1/ops/pipeline/executions/update_request/" +
        encodeURIComponent(requestId),
      { page_size: 1 } satisfies PipelineExecutionDetailQuery,
    ),
    { signal },
  );
}

/**
 * 생성된 갱신 요청 1건의 상태 추적 query (인라인 폐루프).
 *
 * queryKey는 `["feature-update-request", id, "pipeline-execution"]` —
 * `api/live.ts`의 `feature_update_request:{id}` invalidation(prefix 매칭)을 그대로
 * 받으면서, 같은 prefix를 쓰는 구 상세 훅(`updateRequests.ts`, 다른 응답 shape)과
 * 캐시가 섞이지 않게 세그먼트를 분리한다(리뷰 검출 — 동일 키에 이형 shape 캐시
 * 충돌). WS가 꺼진 환경을 위해 queued/running 동안 2s 폴링 fallback을 함께 둔다.
 */
export function useDatasetRefreshRequestStatus(requestId: string | null) {
  return useQuery<DatasetRefreshExecutionDetailResponse, Error>({
    queryKey: datasetRefreshExecutionQueryKey(requestId),
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
