"use client";

/**
 * `/v1/ops/pipeline/*` — 파이프라인 페이지 ① 훅 (ADR-064 T-ADM-C5).
 *
 * 실행 타임라인(DB-only UNION keyset cursor)·overview 상태 스트립·전역 이벤트·
 * Dagster runs 보조 패널·스케줄 조작·갱신 요청 생성을 바인딩한다.
 *
 * query key 규약:
 * - `["pipeline", "executions", "live", params]` — 1페이지(cursor 없음) 전용.
 *   `/ops/live` WS invalidation이 이 key만 무효화한다(자동 갱신 1페이지 한정 —
 *   설계 §1: 조사 중 목록 재정렬 방지).
 * - `["pipeline", "executions", "paged", params, cursor]` — cursor 진입 후.
 *   WS가 건드리지 않으며 "새 실행 N건" 배지 + 수동 반영으로만 갱신한다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiClientError,
  clearIdempotencyKeys,
  getJson,
  patchJson,
  pathWithQuery,
  postJson,
  withIdempotencyKey,
} from "./client";
import type { components, paths } from "./types";

type Schemas = components["schemas"];

export type PipelineOverviewResponse = Schemas["PipelineOverviewResponse"];
export type PipelineDagsterOverview = Schemas["PipelineDagsterOverview"];
export type PipelineSensor = Schemas["DagsterSensor"];
export type PipelineExecutionsListResponse =
  Schemas["PipelineExecutionsListResponse"];
export type PipelineExecutionRecord = Schemas["PipelineExecutionRecord"];
export type PipelineExecutionRootRecord =
  Schemas["PipelineExecutionRootRecord"];
export type PipelineProjectedJobRecord = Schemas["PipelineProjectedJobRecord"];
export type PipelineDagsterRunDetailResponse =
  Schemas["DagsterRunDetailResponse"];
export type PipelineExecutionDetailResponse =
  Schemas["PipelineExecutionDetailResponse"];
export type PipelineExecutionCancelResponse =
  Schemas["PipelineCancellationResponse"];
export type PipelineExecutionCancelRequest =
  Schemas["PipelineCancellationRequest"];
export type PipelineEventsListResponse = Schemas["PipelineEventsListResponse"];
export type PipelineJobEventRecord = Schemas["PipelineJobEventRecord"];
export type PipelineDagsterRunsResponse =
  Schemas["PipelineDagsterRunsResponse"];
export type PipelineDatasetsCatalogResponse =
  Schemas["OpsDatasetsGridResponse"];
export type PipelineJobPrecheckResponse =
  Schemas["PipelineJobPrecheckResponse"];
export type PipelineSchedule = Schemas["DagsterSchedule"];
export type PipelineSchedulesResponse = Schemas["PipelineSchedulesResponse"];
export type PipelineScheduleCommandResponse =
  Schemas["PipelineScheduleCommandResponse"];
export type PipelineScheduleUpdateRequest =
  Schemas["PipelineScheduleUpdateRequest"];
export type PipelineScheduleCommandRequest =
  Schemas["PipelineScheduleCommandRequest"];
export type PipelineScheduleClaimResolutionRequest =
  Schemas["PipelineScheduleClaimResolutionRequest"];
export type PipelineScheduleClaimResolutionResponse =
  Schemas["PipelineScheduleClaimResolutionResponse"];
export type FeatureUpdateRequestCreateRequest =
  Schemas["FeatureUpdateRequestCreateRequest"];
export type FeatureUpdateRequestCreateResponse =
  Schemas["FeatureUpdateRequestCreateResponse"];
export type FeatureUpdateRequestPreviewRequest =
  Schemas["FeatureUpdateRequestPreviewRequest"];
export type FeatureUpdateRequestPreviewResponse =
  Schemas["FeatureUpdateRequestPreviewResponse"];
export type FeatureUpdateRequestMutationResponse =
  Schemas["FeatureUpdateRequestMutationResponse"];
export type FeatureUpdateScope = FeatureUpdateRequestCreateRequest["scope"];

type ExecutionsQuery = NonNullable<
  paths["/v1/ops/pipeline/executions"]["get"]["parameters"]["query"]
>;
type EventsQuery = NonNullable<
  paths["/v1/ops/pipeline/events"]["get"]["parameters"]["query"]
>;
type DetailQuery = NonNullable<
  paths["/v1/ops/pipeline/executions/{kind}/{execution_id}"]["get"]["parameters"]["query"]
>;

export type ExecutionKind = Exclude<ExecutionsQuery["kind"], null | undefined>;
export type ExecutionStatus = Exclude<
  ExecutionsQuery["status"],
  null | undefined
>;
export type JobEventLevel = Exclude<EventsQuery["level"], null | undefined>;
export type PipelineScheduleCommand = PipelineScheduleCommandRequest["command"];

export const EXECUTION_KINDS: readonly ExecutionKind[] = [
  "import_job",
  "update_request",
];
export const EXECUTION_STATUSES: readonly ExecutionStatus[] = [
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
];
export const JOB_EVENT_LEVELS: readonly JobEventLevel[] = [
  "debug",
  "info",
  "warning",
  "error",
  "critical",
];

export interface PipelineExecutionsParams {
  kind?: ExecutionKind;
  status?: ExecutionStatus;
  provider?: string;
  dataset_key?: string;
  sync_scope?: string;
  created_from?: string;
  created_to?: string;
  page_size?: number;
  cursor?: string | null;
}

export interface PipelineEventsParams {
  job_id?: string;
  level?: JobEventLevel;
  provider?: string;
  dataset_key?: string;
  page_size?: number;
  cursor?: string | null;
}

export interface PipelineExecutionDetailParams {
  level?: DetailQuery["level"];
  page_size?: number;
  cursor?: string | null;
}

function fetchOverview(
  runLimit: number,
  signal?: AbortSignal,
): Promise<PipelineOverviewResponse> {
  return getJson<PipelineOverviewResponse>(
    pathWithQuery("/v1/ops/pipeline/overview", { run_limit: runLimit }),
    { signal },
  );
}

function fetchExecutions(
  params: PipelineExecutionsParams,
  signal?: AbortSignal,
): Promise<PipelineExecutionsListResponse> {
  return getJson<PipelineExecutionsListResponse>(
    pathWithQuery("/v1/ops/pipeline/executions", {
      kind: params.kind,
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      sync_scope: params.sync_scope,
      created_from: params.created_from,
      created_to: params.created_to,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

function fetchExecutionDetail(
  kind: ExecutionKind,
  executionId: string,
  params: PipelineExecutionDetailParams,
  signal?: AbortSignal,
): Promise<PipelineExecutionDetailResponse> {
  return getJson<PipelineExecutionDetailResponse>(
    pathWithQuery(
      `/v1/ops/pipeline/executions/${kind}/${encodeURIComponent(executionId)}`,
      {
        level: params.level,
        page_size: params.page_size,
        cursor: params.cursor,
      },
    ),
    { signal },
  );
}

function fetchEvents(
  params: PipelineEventsParams,
  signal?: AbortSignal,
): Promise<PipelineEventsListResponse> {
  return getJson<PipelineEventsListResponse>(
    pathWithQuery("/v1/ops/pipeline/events", {
      job_id: params.job_id,
      level: params.level,
      provider: params.provider,
      dataset_key: params.dataset_key,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

function fetchDagsterRuns(
  limit: number,
  signal?: AbortSignal,
): Promise<PipelineDagsterRunsResponse> {
  return getJson<PipelineDagsterRunsResponse>(
    pathWithQuery("/v1/ops/pipeline/dagster-runs", { limit }),
    { signal },
  );
}

function fetchSchedules(
  signal?: AbortSignal,
): Promise<PipelineSchedulesResponse> {
  return getJson<PipelineSchedulesResponse>("/v1/ops/pipeline/schedules", {
    signal,
  });
}

function fetchDatasetsCatalog(
  signal?: AbortSignal,
): Promise<PipelineDatasetsCatalogResponse> {
  return getJson<PipelineDatasetsCatalogResponse>("/v1/ops/datasets", {
    signal,
  });
}

function fetchMoisSourceSyncPrecheck(
  signal?: AbortSignal,
): Promise<PipelineJobPrecheckResponse> {
  return getJson<PipelineJobPrecheckResponse>(
    "/v1/ops/pipeline/prechecks/mois-source-sync",
    { signal },
  );
}

export function usePipelineOverview(runLimit = 10) {
  return useQuery<PipelineOverviewResponse, Error>({
    queryKey: ["pipeline", "overview", runLimit],
    queryFn: ({ signal }) => fetchOverview(runLimit, signal),
    refetchInterval: 30_000,
    staleTime: 5_000,
  });
}

/**
 * 실행 타임라인 조회. `cursor`가 없으면 live key(WS invalidation 대상)를,
 * cursor 진입 후에는 paged key(수동 반영 전용)를 사용한다.
 */
export function usePipelineExecutions(params: PipelineExecutionsParams) {
  const { cursor, ...filters } = params;
  const isFirstPage = !cursor;
  return useQuery<PipelineExecutionsListResponse, Error>({
    queryKey: isFirstPage
      ? ["pipeline", "executions", "live", filters]
      : ["pipeline", "executions", "paged", filters, cursor],
    queryFn: ({ signal }) => fetchExecutions(params, signal),
    refetchInterval: isFirstPage ? 10_000 : false,
    staleTime: 3_000,
  });
}

/**
 * cursor 페이지 조사 중 "새 실행 N건" 배지용 head 조회 — 1페이지를 별도 key로
 * 폴링해 현재 조사 화면을 재정렬하지 않고 신규 행 수만 계산한다(설계 §1).
 */
export function usePipelineExecutionsHead(
  params: Omit<PipelineExecutionsParams, "cursor">,
  options: { enabled: boolean },
) {
  return useQuery<PipelineExecutionsListResponse, Error>({
    queryKey: ["pipeline", "executions", "head", params],
    queryFn: ({ signal }) => fetchExecutions(params, signal),
    enabled: options.enabled,
    refetchInterval: options.enabled ? 15_000 : false,
    staleTime: 5_000,
  });
}

export function usePipelineExecutionDetail(
  kind: ExecutionKind | null,
  executionId: string | null,
  params: PipelineExecutionDetailParams = {},
) {
  return useQuery<PipelineExecutionDetailResponse, Error>({
    queryKey: ["pipeline", "execution", kind, executionId, params],
    queryFn: ({ signal }) => {
      if (!kind || !executionId) {
        throw new Error("execution kind/id가 필요합니다.");
      }
      return fetchExecutionDetail(kind, executionId, params, signal);
    },
    enabled: Boolean(kind && executionId),
    staleTime: 2_000,
  });
}

export function usePipelineEvents(params: PipelineEventsParams) {
  const { cursor, ...filters } = params;
  const isFirstPage = !cursor;
  return useQuery<PipelineEventsListResponse, Error>({
    queryKey: isFirstPage
      ? ["pipeline", "events", "live", filters]
      : ["pipeline", "events", "paged", filters, cursor],
    queryFn: ({ signal }) => fetchEvents(params, signal),
    staleTime: 3_000,
  });
}

export function usePipelineDagsterRuns(limit = 20) {
  // 순수 Dagster 실패는 WS로 오지 않으므로(스냅샷이 job-연결 run만 파생)
  // 보조 패널은 GraphQL 폴링을 유지한다(설계 §1).
  return useQuery<PipelineDagsterRunsResponse, Error>({
    queryKey: ["pipeline", "dagster-runs", limit],
    queryFn: ({ signal }) => fetchDagsterRuns(limit, signal),
    refetchInterval: 30_000,
    staleTime: 5_000,
  });
}

export function usePipelineSchedules() {
  return useQuery<PipelineSchedulesResponse, Error>({
    queryKey: ["pipeline", "schedules"],
    queryFn: ({ signal }) => fetchSchedules(signal),
    staleTime: 10_000,
  });
}

/**
 * 요청 작성기의 provider/dataset 정본. C4 데이터셋 화면과 같은 endpoint/query key를
 * 사용해 legacy debug catalog 의존과 서로 다른 provider 목록을 만들지 않는다.
 */
export function usePipelineDatasetsCatalog() {
  return useQuery<PipelineDatasetsCatalogResponse, Error>({
    queryKey: ["ops-datasets"],
    queryFn: ({ signal }) => fetchDatasetsCatalog(signal),
    staleTime: 15_000,
  });
}

export function useMoisSourceSyncPrecheck(enabled: boolean) {
  return useQuery<PipelineJobPrecheckResponse, Error>({
    queryKey: ["pipeline", "precheck", "mois-source-sync"],
    queryFn: ({ signal }) => fetchMoisSourceSyncPrecheck(signal),
    enabled,
    staleTime: 30_000,
    retry: false,
  });
}

export function useCancelExecutionMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PipelineExecutionCancelResponse,
    ApiClientError,
    {
      kind: ExecutionKind;
      executionId: string;
      body?: PipelineExecutionCancelRequest;
    }
  >({
    mutationFn: ({ kind, executionId, body }) =>
      postJson<PipelineExecutionCancelResponse>(
        `/v1/ops/pipeline/executions/${kind}/${encodeURIComponent(executionId)}/cancel`,
        body ?? {},
      ),
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({
        queryKey: [
          "pipeline",
          "execution",
          variables.kind,
          variables.executionId,
        ],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

export function useCreateUpdateRequestMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestCreateResponse,
    Error,
    FeatureUpdateRequestCreateRequest
  >({
    mutationFn: (body) =>
      postJson<FeatureUpdateRequestCreateResponse>(
        "/v1/ops/pipeline/requests",
        body,
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

export function usePreviewUpdateRequestMutation() {
  return useMutation<
    FeatureUpdateRequestPreviewResponse,
    Error,
    FeatureUpdateRequestPreviewRequest
  >({
    mutationFn: (body) =>
      postJson<FeatureUpdateRequestPreviewResponse>(
        "/v1/ops/pipeline/requests/preview",
        body,
      ),
  });
}

export function useRunNowUpdateRequestMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    FeatureUpdateRequestMutationResponse,
    Error,
    { requestId: string }
  >({
    mutationFn: ({ requestId }) =>
      postJson<FeatureUpdateRequestMutationResponse>(
        `/v1/ops/pipeline/requests/${encodeURIComponent(requestId)}/run-now`,
      ),
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      void queryClient.invalidateQueries({
        queryKey: [
          "pipeline",
          "execution",
          "update_request",
          variables.requestId,
        ],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

export function usePatchScheduleMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PipelineScheduleCommandResponse,
    Error,
    { scheduleName: string; body: PipelineScheduleUpdateRequest }
  >({
    mutationFn: ({ scheduleName, body }) =>
      withIdempotencyKey(
        `pipeline:schedule:${scheduleName}:patch:${JSON.stringify(body)}`,
        (idempotencyKey) =>
          patchJson<PipelineScheduleCommandResponse>(
            `/v1/ops/pipeline/schedules/${encodeURIComponent(scheduleName)}`,
            body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
        {
          retainOnSuccess: (response) =>
            response.data.audit_status === "terminal_record_failed",
        },
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "schedules"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

export function useScheduleCommandMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PipelineScheduleCommandResponse,
    Error,
    { scheduleName: string; body: PipelineScheduleCommandRequest }
  >({
    mutationFn: ({ scheduleName, body }) =>
      withIdempotencyKey(
        `pipeline:schedule:${scheduleName}:command:${JSON.stringify(body)}`,
        (idempotencyKey) =>
          postJson<PipelineScheduleCommandResponse>(
            `/v1/ops/pipeline/schedules/${encodeURIComponent(scheduleName)}/commands`,
            body,
            { headers: { "Idempotency-Key": idempotencyKey } },
          ),
        {
          retainOnSuccess: (response) =>
            response.data.audit_status === "terminal_record_failed",
        },
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "schedules"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "dagster-runs"],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

export function useResolveScheduleClaimMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PipelineScheduleClaimResolutionResponse,
    Error,
    {
      scheduleName: string;
      commandId: string;
      body: PipelineScheduleClaimResolutionRequest;
    }
  >({
    mutationFn: ({ scheduleName, commandId, body }) =>
      postJson<PipelineScheduleClaimResolutionResponse>(
        `/v1/ops/pipeline/schedules/${encodeURIComponent(scheduleName)}/claims/${encodeURIComponent(commandId)}/resolve`,
        body,
      ),
    onSuccess: (_response, variables) => {
      clearIdempotencyKeys(`pipeline:schedule:${variables.scheduleName}:`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "schedules"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "overview"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "dagster-runs"],
      });
      invalidatePipelineDatasetQueries(queryClient);
    },
  });
}

function invalidatePipelineDatasetQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  void queryClient.invalidateQueries({ queryKey: ["ops-datasets"] });
  void queryClient.invalidateQueries({ queryKey: ["ops-dataset"] });
}

/**
 * `GET /ops/pipeline/dagster-runs/{run_id}` — C3c 정본(#690). 구 그룹과 달리
 * 404/502/503은 problem+json으로 온다(200 degrade 아님) — 오류는
 * `ApiClientError.status`로 구분한다.
 */
export function usePipelineDagsterRunDetail(
  runId: string | null,
  params: { page_size?: number; after?: string | null } = {},
) {
  return useQuery<PipelineDagsterRunDetailResponse, Error>({
    queryKey: ["pipeline", "dagster-run", runId, params],
    queryFn: ({ signal }) => {
      if (!runId) {
        throw new Error("run_id가 필요합니다.");
      }
      return getJson<PipelineDagsterRunDetailResponse>(
        pathWithQuery(
          `/v1/ops/pipeline/dagster-runs/${encodeURIComponent(runId)}`,
          { page_size: params.page_size, after: params.after },
        ),
        { signal },
      );
    },
    enabled: Boolean(runId),
    staleTime: 5_000,
    retry: false,
  });
}
