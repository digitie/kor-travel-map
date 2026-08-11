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
  pathWithQuery,
  postJson,
  putJson,
  withIdempotencyKey,
} from "./client";
import {
  canonicalFeatureUpdateIdempotencyBody,
  featureUpdateIdempotencyOperationKey,
} from "./feature-update-idempotency";
import type { OpsLiveConnectionState, OpsLiveMode, OpsLiveTopic } from "./live";
import type { components, paths } from "./types";

type DatasetSchemas = components["schemas"];

export type OpsDatasetCatalogInfo = DatasetSchemas["OpsDatasetCatalogInfo"];
export type OpsDatasetGridRow = DatasetSchemas["OpsDatasetGridRow"];
export type OpsDatasetsGridResponse = DatasetSchemas["OpsDatasetsGridResponse"];
export type OpsDatasetDetailData = DatasetSchemas["OpsDatasetDetailData"];
export type OpsDatasetDetailResponse =
  DatasetSchemas["OpsDatasetDetailResponse"];
export type OpsDatasetScopeState = DatasetSchemas["OpsDatasetScopeState"];
export type OpsDatasetExecution = DatasetSchemas["OpsDatasetExecution"];
export type OpsDatasetScopeRefreshCapability =
  DatasetSchemas["OpsDatasetScopeRefreshCapability"];
export type OpsDatasetEventRecord = DatasetSchemas["OpsDatasetEventRecord"];
export type OpsDatasetFreshness = DatasetSchemas["OpsDatasetFreshness"];
export type OpsDatasetPreviewRequest =
  DatasetSchemas["OpsDatasetPreviewRequest"];
export type OpsDatasetPreviewResponse =
  DatasetSchemas["OpsDatasetPreviewResponse"];
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

type DatasetRefreshPolicyQuery = NonNullable<
  paths["/v1/ops/datasets/refresh-policy"]["put"]["parameters"]["query"]
>;
type PipelineExecutionDetailQuery = NonNullable<
  paths["/v1/ops/pipeline/executions/{kind}/{execution_id}"]["get"]["parameters"]["query"]
>;

export type DatasetRefreshNowInput = {
  /** provider/dataset 자연키가 아닌 immutable canonical member 식별자. */
  providerDatasetId: number;
  /** canonical operation member의 논리 scope. */
  syncScope: string;
  /** 같은 dataset/scope의 operation을 구분하는 immutable handler key. */
  operationKey: string;
  priority?: number;
  reason?: string | null;
};

export type DatasetRefreshScopeDecision =
  | { allowed: true; syncScope: string }
  | { allowed: false; reason: string };

export type DatasetRefreshConflict = {
  code: string;
  requestId: string;
  status: string | null;
  detailUrl: string | null;
};

export type OpsDatasetCatalogOption = {
  provider: string;
  datasets: string[];
};

/** canonical dataset 행을 provider 필터/입력 보조용 2원 목록으로 축약한다. */
export function opsDatasetCatalogOptions(
  rows: readonly OpsDatasetGridRow[],
): OpsDatasetCatalogOption[] {
  const datasetsByProvider = new Map<string, Set<string>>();
  for (const row of rows) {
    if (row.catalog_state !== "canonical") continue;
    const datasets = datasetsByProvider.get(row.provider) ?? new Set<string>();
    datasets.add(row.dataset_key);
    datasetsByProvider.set(row.provider, datasets);
  }
  return Array.from(datasetsByProvider, ([provider, datasets]) => ({
    provider,
    datasets: Array.from(datasets).sort(),
  })).sort((left, right) => left.provider.localeCompare(right.provider));
}

/** "지금 갱신" 요청 생성 endpoint — pipeline 그룹(T-ADM-C3) 소유. */
export const DATASET_REFRESH_REQUESTS_PATH = "/v1/ops/pipeline/requests";

/**
 * 데이터셋 projection을 바꾸는 global live topic.
 *
 * active cache 유무와 무관하게 외부에서 생성·진행된 canonical operation,
 * provider sync state, 이슈/POI projection, Dagster schedule 변화를 grid/detail에
 * 반영한다.
 */
export const OPS_DATASET_LIVE_TOPICS = [
  "provider_sync",
  "dataset_projection",
  "import_jobs",
  "feature_update_requests",
  "dagster_runs",
  "dagster_schedules",
] as const satisfies readonly OpsLiveTopic[];

export function opsDatasetLiveBadgeLabel(live: {
  state: OpsLiveConnectionState;
  mode: OpsLiveMode;
}): string {
  if (live.state === "unauthorized") {
    return "로그인 필요";
  }
  if (live.mode === "live") {
    return "실시간 갱신";
  }
  if (live.mode === "polling") {
    return "REST 폴링 갱신";
  }
  return live.state === "disabled"
    ? "자동 갱신 꺼짐"
    : live.state === "unavailable"
      ? "WebSocket 미지원"
      : live.state === "reconnecting"
        ? "재연결 중"
        : "연결 중";
}

function datasetDetailPath(
  providerDatasetId: number,
  syncScope: string,
  operationKey: string,
): string {
  return pathWithQuery(`/v1/ops/datasets/${providerDatasetId}`, {
    sync_scope: syncScope,
    // 빈 문자열은 **보내지 않는다**. UI 내부에서 ""는 "실행 가능한 operation이
    // 없는 catalog 행"을 뜻하는 정규화 값인데(rowOperationKey), 서버의
    // `operation_key`는 `min_length=1`이라 `operation_key=`를 받으면 422다.
    // 그 행은 seed에 실재하므로(개수는 DB마다 다르다) 빼먹으면 상세가 열리지 않는다.
    operation_key: operationKey || null,
  });
}

function datasetPreviewPath(
  providerDatasetId: number,
  syncScope: string,
  operationKey: string,
): string {
  return pathWithQuery(`/v1/ops/datasets/${providerDatasetId}/preview`, {
    sync_scope: syncScope,
    // 빈 문자열은 **보내지 않는다**. UI 내부에서 ""는 "실행 가능한 operation이
    // 없는 catalog 행"을 뜻하는 정규화 값인데(rowOperationKey), 서버의
    // `operation_key`는 `min_length=1`이라 `operation_key=`를 받으면 422다.
    // 그 행은 seed에 실재하므로(개수는 DB마다 다르다) 빼먹으면 상세가 열리지 않는다.
    operation_key: operationKey || null,
  });
}

function refreshPolicyPath(providerDatasetId: number): string {
  return pathWithQuery("/v1/ops/datasets/refresh-policy", {
    provider_dataset_id: providerDatasetId,
  } satisfies DatasetRefreshPolicyQuery);
}

function fetchOpsDatasets(
  signal?: AbortSignal,
): Promise<OpsDatasetsGridResponse> {
  return getJson<OpsDatasetsGridResponse>("/v1/ops/datasets", { signal });
}

export function fetchOpsDataset(
  providerDatasetId: number,
  syncScope: string,
  operationKey: string,
  signal?: AbortSignal,
): Promise<OpsDatasetDetailResponse> {
  return getJson<OpsDatasetDetailResponse>(
    datasetDetailPath(providerDatasetId, syncScope, operationKey),
    { signal },
  );
}

/**
 * 서버 capability를 제출 가능한 `sync_scope`로 해석한다.
 *
 * 조합이 모순되거나 target scope가 현재 allow-list에서 빠졌으면 fail-closed한다.
 * 일반 dataset도 canonical `dataset_wide` scope를 명시한다. 요청 경계는
 * provider/dataset 자연키나 nullable scope를 다시 받지 않는다.
 *
 * `effect: "none"`은 **제출 가능한 scope가 하나도 없다**는 서버 판정이다. 이 축이
 * 없던 앞 판에서는 갱신 불가 dataset의 payload가 정상 dataset-wide capability와
 * `reason` 문자열 하나만 달랐고, 이 함수는 허용 경로에서 `reason`을 읽지 않아
 * `{allowed: true, syncScope: "dataset_wide"}`를 돌려줬다. 그 판정으로 '지금 갱신'
 * 버튼이 켜졌고, 눌러도 `datasets-client`가 빈 `operationKey`에서 되돌아가 요청도
 * 오류도 없이 아무 일이 일어나지 않았다.
 */
export function resolveDatasetRefreshScope(
  capability: OpsDatasetScopeRefreshCapability | null | undefined,
  selectedSyncScope: string,
): DatasetRefreshScopeDecision {
  if (!capability) {
    return { allowed: false, reason: "갱신 scope capability가 없습니다." };
  }
  if (capability.effect === "none") {
    return {
      allowed: false,
      reason: capability.reason ?? "이 dataset에 걸 수 있는 갱신 범위가 없습니다.",
    };
  }
  if (capability.effect === "dataset_wide") {
    if (
      capability.selector !== "none" ||
      capability.supported ||
      capability.default_sync_scope !== "dataset_wide" ||
      capability.allowed_sync_scopes.length > 0 ||
      selectedSyncScope !== capability.default_sync_scope
    ) {
      return {
        allowed: false,
        reason: "dataset-wide scope 계약이 모순됩니다.",
      };
    }
    return { allowed: true, syncScope: capability.default_sync_scope };
  }
  // `selector`는 여기서 보지 않는다. 그것은 "**scope 안의 대상**을 무엇이 고르는가"이고
  // (`poi_cache_targets` | `none`), scope 자체를 고를 수 있는지와는 다른 축이다.
  // `target_grids`를 선언하지 않은 dataset — 예: `dataset_wide` + `external_system:*` —
  // 도 scope를 고를 수 있지만 POI target selector는 없다. 앞 판은 두 축을 하나로 묶어
  // 그런 dataset을 "선택 scope 갱신을 지원하지 않습니다"로 막았다.
  if (
    !capability.supported ||
    capability.allowed_sync_scopes.length === 0 ||
    !capability.allowed_sync_scopes.includes(capability.default_sync_scope)
  ) {
    return {
      allowed: false,
      reason: capability.reason ?? "선택 scope 갱신을 지원하지 않습니다.",
    };
  }
  if (!capability.allowed_sync_scopes.includes(selectedSyncScope)) {
    return {
      allowed: false,
      // 판정 근거는 POI target 목록이 아니라 **카탈로그 선언**이다
      // (`provider_dataset_operation_scopes`). 앞 판의 "현재 활성 target에 포함되지 않은"은
      // POI target이 하나도 없는 dataset에 대해서도 나왔다.
      reason: "카탈로그가 선언하지 않은 sync scope입니다.",
    };
  }
  return { allowed: true, syncScope: selectedSyncScope };
}

/**
 * 상세의 "범위 계약" 줄에 그리는 `효과` 문장.
 *
 * `effect`는 값이 셋이므로(`dataset_wide` | `sync_scope` | `none`) 문장도 셋이어야
 * 한다. 배타 열거(`effect === "sync_scope" ? … : …`)로 그리면 `none`이 진짜
 * dataset-wide 계약과 **같은 문장**이 되고, 같은 패널이 바로 아래에
 * `resolveDatasetRefreshScope`의 `effect === "none"` 사유("걸 수 있는 갱신 범위가
 * 없습니다")를 함께 띄우므로 한 화면이 서로 반대되는 두 문장을 동시에 말한다.
 *
 * `none`은 "제출 가능한 scope가 하나도 없다"는 뜻이다. 그 상태에서도
 * `default_sync_scope`는 `dataset_wide`로 내려온다 —
 * `api/ops_dataset_service.py::_scope_refresh_capability`의 `if not entry.is_refreshable`
 * 분기가 그 값을 고정한다(그 분기가 `effect="none"`을 내는 유일한 자리다). 그러므로
 * 이 문장이 기본값을 근거로 실행 가능성을 말하면 안 된다.
 */
export function opsDatasetScopeEffectSentence(
  effect: OpsDatasetScopeRefreshCapability["effect"],
): string {
  switch (effect) {
    case "sync_scope":
      return "효과 선택 scope 갱신";
    case "dataset_wide":
      return "효과 dataset 전체 갱신";
    case "none":
      return "효과 없음(제출 가능한 갱신 범위 없음)";
  }
}

export function buildDatasetRefreshNowRequest({
  providerDatasetId,
  syncScope,
  operationKey,
  priority = 75,
  reason = "dataset refresh from ops/datasets",
}: DatasetRefreshNowInput): DatasetRefreshRequestCreateRequest {
  return {
    scope: {
      type: "provider_dataset",
      provider_dataset_id: providerDatasetId,
      sync_scope: syncScope,
      operation_key: operationKey,
    },
    run_mode: "now",
    priority,
    reason,
  };
}

export async function createDatasetRefreshNow(
  input: DatasetRefreshNowInput,
): Promise<DatasetRefreshRequestCreateResponse> {
  const body = canonicalFeatureUpdateIdempotencyBody(
    buildDatasetRefreshNowRequest(input),
  );
  const operationKey = await featureUpdateIdempotencyOperationKey(
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
  return Boolean(response?.data.items.some((row) => row.active_execution));
}

export function hasActiveDatasetDetailExecution(
  response: OpsDatasetDetailResponse | undefined,
): boolean {
  return Boolean(response?.data.active_execution);
}

export function resolveOpsDatasetRefetchInterval(
  activeExecution: boolean,
  pollingFallback: boolean,
): number | false {
  if (activeExecution) {
    return 2_000;
  }
  return pollingFallback ? 5_000 : false;
}

export function useOpsDatasets({
  pollingFallback = false,
}: {
  pollingFallback?: boolean;
} = {}) {
  return useQuery<OpsDatasetsGridResponse, Error>({
    queryKey: ["ops-datasets"],
    queryFn: ({ signal }) => fetchOpsDatasets(signal),
    // C7A의 global live invalidation 이전에도 진입 전부터 존재한 active 작업이
    // terminal로 바뀌면 버튼 차단이 자동 해제되어야 한다.
    refetchInterval: (query) =>
      resolveOpsDatasetRefetchInterval(
        hasActiveDatasetExecution(query.state.data),
        pollingFallback,
      ),
    refetchIntervalInBackground: pollingFallback,
    staleTime: 15_000,
  });
}

/** provider/dataset 입력 후보용 observer — 운영 grid의 active-run polling을 승계하지 않는다. */
export function useOpsDatasetCatalog() {
  return useQuery<OpsDatasetsGridResponse, Error>({
    queryKey: ["ops-datasets"],
    queryFn: ({ signal }) => fetchOpsDatasets(signal),
    staleTime: 60_000,
  });
}

export function useOpsDataset(
  selection: {
    providerDatasetId: number;
    syncScope: string;
    operationKey: string;
  } | null,
  {
    pollingFallback = false,
  }: {
    pollingFallback?: boolean;
  } = {},
) {
  return useQuery<OpsDatasetDetailResponse, Error>({
    queryKey: [
      "ops-dataset",
      selection?.providerDatasetId,
      selection?.syncScope,
      selection?.operationKey,
    ],
    queryFn: ({ signal }) =>
      fetchOpsDataset(
        selection?.providerDatasetId as number,
        selection?.syncScope as string,
        selection?.operationKey as string,
        signal,
      ),
    enabled: Boolean(selection),
    refetchInterval: (query) =>
      resolveOpsDatasetRefetchInterval(
        hasActiveDatasetDetailExecution(query.state.data),
        pollingFallback,
      ),
    refetchIntervalInBackground: pollingFallback,
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
    { providerDatasetId: number; body: ProviderRefreshPolicyUpsertRequest }
  >({
    mutationFn: ({ providerDatasetId, body }) =>
      upsertOpsDatasetRefreshPolicy(providerDatasetId, body),
    onSuccess: () => {
      invalidateOpsDatasetQueries(queryClient);
    },
  });
}

export function upsertOpsDatasetRefreshPolicy(
  providerDatasetId: number,
  body: ProviderRefreshPolicyUpsertRequest,
): Promise<OpsDatasetRefreshPolicyResponse> {
  return putJson<OpsDatasetRefreshPolicyResponse>(
    refreshPolicyPath(providerDatasetId),
    body,
  );
}

export function useOpsDatasetPreviewMutation() {
  // #678 typed preview 계약 — body(`source=fixture`, `max_items`)만 받는다.
  return useMutation<
    OpsDatasetPreviewResponse,
    Error,
    {
      providerDatasetId: number;
      syncScope: string;
      operationKey: string;
      body: OpsDatasetPreviewRequest;
    }
  >({
    mutationFn: ({ providerDatasetId, syncScope, operationKey, body }) =>
      previewOpsDataset(providerDatasetId, syncScope, operationKey, body),
  });
}

export function previewOpsDataset(
  providerDatasetId: number,
  syncScope: string,
  operationKey: string,
  body: OpsDatasetPreviewRequest,
): Promise<OpsDatasetPreviewResponse> {
  return postJson<OpsDatasetPreviewResponse>(
    datasetPreviewPath(providerDatasetId, syncScope, operationKey),
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
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
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
  return [
    "pipeline",
    "execution",
    "update_request",
    requestId,
    { page_size: 1 },
  ] as const;
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
 * queryKey는 pipeline 상세 훅과 같은
 * `["pipeline", "execution", "update_request", id, {page_size: 1}]` 계약을 쓴다.
 * 따라서 `feature_update_request:{id}` live topic이 canonical 상세 cache를 직접
 * 무효화한다. WS가 꺼진 환경을 위해 queued/running 동안 2s 폴링 fallback을 둔다.
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
