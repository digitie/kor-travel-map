import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

/**
 * `/ops/pipeline` — ADR-064 페이지 ① route-mocked spec (T-ADM-C5).
 *
 * 모든 backend 호출은 브라우저 계층에서 가로챈다(BFF `/api/proxy` 도달 전) —
 * glob은 `**?/v1/ops/pipeline/...**` + `url.pathname.endsWith(...)` 판별
 * (dagster-interactions.spec.ts idiom, proxy prefix 유무 무관). ops-live WS는
 * `installInertOpsLiveWebSocket`(#503)으로 inert 처리해 invalidation이 호출
 * 카운트 단언을 흔들지 않게 한다.
 *
 * 검증 계약:
 * - 상태 스트립: KPI + 큐 sensor 중지 시 destructive alert(설계 §1 — 침묵 정지
 *   실장애 모드 노출).
 * - root 타임라인(C3b 소비 정본 #689): request branch/standalone root 행,
 *   effective providers/dataset_keys + provider_datasets exact pair 표시,
 *   projected_job 상태·진행 분리. Dagster run 상세는 C3c(#690) endpoint 소비.
 * - 상세 패널(행 클릭/딥링크), 스케줄 조작(성공 + problem+json 실패),
 *   요청 dialog(6-type scope 전환·별도 preview·409 Retry-After·MOIS 조건부 경고),
 *   `?schedule=` 실동작 하이라이트.
 */

type Schemas = components["schemas"];
type PipelineOverviewResponse = Schemas["PipelineOverviewResponse"];
type PipelineExecutionRecord = Schemas["PipelineExecutionRecord"];
type PipelineExecutionRootRecord = Schemas["PipelineExecutionRootRecord"];
type PipelineDagsterRunDetailResponse = Schemas["DagsterRunDetailResponse"];
type PipelineExecutionsListResponse = Schemas["PipelineExecutionsListResponse"];
type PipelineExecutionDetailResponse =
  Schemas["PipelineExecutionDetailResponse"];
type PipelineDagsterRunsResponse = Schemas["PipelineDagsterRunsResponse"];
type PipelineEventsListResponse = Schemas["PipelineEventsListResponse"];
type PipelineSchedulesResponse = Schemas["PipelineSchedulesResponse"];
type PipelineScheduleCommandResponse =
  Schemas["PipelineScheduleCommandResponse"];
type PipelineScheduleClaimResolutionResponse =
  Schemas["PipelineScheduleClaimResolutionResponse"];
type FeatureUpdateRequestCreateResponse =
  Schemas["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestMutationResponse =
  Schemas["FeatureUpdateRequestMutationResponse"];
type FeatureUpdateRequestPreviewResponse =
  Schemas["FeatureUpdateRequestPreviewResponse"];
type PipelineJobPrecheckResponse = Schemas["PipelineJobPrecheckResponse"];
type OpsDatasetGridRow = Schemas["OpsDatasetGridRow"];
type OpsDatasetsGridResponse = Schemas["OpsDatasetsGridResponse"];

const REQUEST_ID = "22222222-2222-2222-2222-222222222222";
const TWIN_JOB_ID = "11111111-1111-1111-1111-111111111111";
const SOLO_JOB_ID = "99999999-9999-4999-8999-999999999999";
const NEW_REQUEST_ID = "33333333-3333-4333-8333-333333333333";
const SCHEDULE_NAME = "feature_weather_kma_short_forecast_hourly_schedule";

async function expectScheduleControlsDisabled(page: Page): Promise<void> {
  await expect(page.getByLabel("명령 사유 (선택)")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", {
      name: new RegExp(`${SCHEDULE_NAME} 스케줄 (시작|중지)`),
    }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: `${SCHEDULE_NAME} 상태 기본값 복귀` }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` }),
  ).toBeDisabled();
}

const META = { duration_ms: 1, request_id: "e2e-pipeline" };

function makeCatalogRow(
  provider: string,
  datasetKey: string,
  syncScope: string,
): OpsDatasetGridRow {
  const scopeRefresh =
    syncScope === "target_grids"
      ? {
          supported: true,
          selector: "poi_cache_targets" as const,
          effect: "sync_scope" as const,
          default_sync_scope: "target_grids",
          allowed_sync_scopes: ["target_grids"],
          reason: null,
        }
      : {
          supported: true,
          selector: "none" as const,
          effect: "dataset_wide" as const,
          default_sync_scope: "dataset_wide",
          allowed_sync_scopes: [],
          reason: null,
        };
  return {
    provider,
    dataset_key: datasetKey,
    detail_url: `/v1/ops/datasets/detail?provider=${provider}&dataset_key=${datasetKey}`,
    sync_scope: syncScope,
    status: "active",
    last_success_at: "2026-07-14T09:00:00.000Z",
    last_failure_at: null,
    consecutive_failures: 0,
    eligible_after: null,
    freshness: {
      state: "fresh",
      basis: "policy_stale_after",
      sla_seconds: 3600,
      due_at: "2026-07-14T10:00:00.000Z",
      is_overdue: false,
      overdue_by_seconds: 0,
    },
    schedule: {
      source: "dagster_graphql",
      basis: "not_scheduled",
      status: null,
      schedule_names: [],
      active_schedule_names: [],
      next_scheduled_at: null,
    },
    latest_execution: null,
    catalog_state: "canonical",
    orphan_reason: null,
    mutable: true,
    catalog: {
      feature_kind: "place",
      provider_state_default_scope: syncScope,
      label: datasetKey,
      is_feature_load: true,
      is_refreshable: true,
      scope_refresh: scopeRefresh,
      preview: {
        supported: false,
        sources: [],
        input_kind: "none",
        default_max_items: 20,
        max_items_limit: 100,
        timeout_seconds: 5,
        external_call_budget: 0,
      },
    },
    refresh_policy: null,
    dataset_issues: { open_count: 0, severity_counts: {} },
    provider_issues: { open_count: 0, severity_counts: {} },
  };
}

function makeCatalogResponse(
  items: OpsDatasetGridRow[] = [
    makeCatalogRow("python-kma-api", "kma_short_forecast", "target_grids"),
    makeCatalogRow("python-mois-api", "mois_licenses", "default"),
    makeCatalogRow("python-opinet-api", "opinet_stations", "default"),
  ],
): OpsDatasetsGridResponse {
  return {
    data: {
      items,
      schedule_source_status: "ok",
      schedule_source_errors: [],
      latest_execution_coverage: "db_recorded_canonical_operations",
    },
    meta: META,
  };
}

function makeMoisPrecheckResponse(
  overrides: Partial<PipelineJobPrecheckResponse["data"]> = {},
): PipelineJobPrecheckResponse {
  return {
    data: {
      job_name: "mois_localdata_source_sync",
      ready: true,
      checked_at: "2026-07-17T09:00:00.000Z",
      max_age_hours: 24,
      age_hours: 1,
      latest_run: {
        run_id: "mois-source-run-1",
        job_name: "mois_localdata_source_sync",
        status: "SUCCESS",
        start_time: Date.parse("2026-07-17T07:55:00.000Z") / 1000,
        end_time: Date.parse("2026-07-17T08:00:00.000Z") / 1000,
        update_time: Date.parse("2026-07-17T08:00:00.000Z") / 1000,
        tags: {},
      },
      disabled_reason: null,
      ...overrides,
    },
    meta: META,
  };
}

function makeExecution(
  overrides: Partial<PipelineExecutionRecord> = {},
): PipelineExecutionRecord {
  return {
    kind: "import_job",
    id: SOLO_JOB_ID,
    status: "done",
    created_at: "2026-07-14T09:00:00.000Z",
    job_kind: "provider_load",
    provider: "python-opinet-api",
    dataset_key: "opinet_stations",
    progress: 100,
    current_stage: "load",
    scope_type: null,
    priority: null,
    run_mode: null,
    operator: null,
    error_message: null,
    started_at: "2026-07-14T09:00:10.000Z",
    finished_at: "2026-07-14T09:02:00.000Z",
    dagster_run_id: "run-solo",
    dagster_run_status: "SUCCESS",
    trigger_kind: "manual",
    operation_registry_version: null,
    job_id: null,
    request_id: null,
    load_batch_id: null,
    parent_job_id: null,
    detail_url: `/v1/ops/pipeline/executions/import_job/${SOLO_JOB_ID}`,
    ...overrides,
  };
}

/** C3b(#689) root 목록 — request branch root + standalone import root. */
function makeRoots(): PipelineExecutionRootRecord[] {
  const requestRoot: PipelineExecutionRootRecord = {
    kind: "update_request",
    id: REQUEST_ID,
    status: "running",
    created_at: "2026-07-14T10:00:00.000Z",
    providers: ["python-kma-api"],
    dataset_keys: ["kma_short_forecast"],
    provider_datasets: [
      {
        provider: "python-kma-api",
        dataset_key: "kma_short_forecast",
        sync_scope: "target_grids",
        operation_member_id: TWIN_JOB_ID,
        status: "running",
      },
    ],
    scope_type: "provider_dataset",
    priority: 50,
    run_mode: "queued",
    operator: "tester",
    error_message: null,
    started_at: "2026-07-14T10:00:05.000Z",
    finished_at: null,
    progress: null,
    current_stage: null,
    dagster_run_id: "run-pair",
    dagster_run_status: "STARTED",
    trigger_kind: "update_request",
    operation_registry_version: null,
    cancellation: null,
    linked_job_count: 2,
    requested_job_id: TWIN_JOB_ID,
    projected_job: {
      id: TWIN_JOB_ID,
      job_kind: "feature_update_request",
      status: "running",
      progress: 40,
      current_stage: "loading",
      depth: 0,
      created_at: "2026-07-14T10:00:00.000Z",
      started_at: "2026-07-14T10:00:05.000Z",
      finished_at: null,
      error_message: null,
      dagster_run_id: null,
      dagster_run_status: null,
      trigger_kind: "update_request",
      operation_registry_version: null,
      load_batch_id: null,
      parent_job_id: null,
      detail_url: `/v1/ops/pipeline/executions/import_job/${TWIN_JOB_ID}`,
    },
    detail_url: `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
  };
  const standaloneRoot: PipelineExecutionRootRecord = {
    kind: "import_job",
    id: SOLO_JOB_ID,
    status: "done",
    created_at: "2026-07-14T09:00:00.000Z",
    providers: ["python-opinet-api"],
    dataset_keys: ["opinet_stations"],
    provider_datasets: [
      {
        provider: "python-opinet-api",
        dataset_key: "opinet_stations",
        sync_scope: "dataset_wide",
        operation_member_id: SOLO_JOB_ID,
        status: "done",
      },
    ],
    scope_type: null,
    priority: null,
    run_mode: null,
    operator: null,
    error_message: null,
    started_at: "2026-07-14T09:00:10.000Z",
    finished_at: "2026-07-14T09:02:00.000Z",
    progress: 100,
    current_stage: "load",
    dagster_run_id: "run-solo",
    dagster_run_status: "SUCCESS",
    trigger_kind: "manual",
    operation_registry_version: null,
    cancellation: null,
    linked_job_count: 1,
    requested_job_id: null,
    projected_job: {
      id: SOLO_JOB_ID,
      job_kind: "provider_load",
      status: "done",
      progress: 100,
      current_stage: "load",
      depth: 0,
      created_at: "2026-07-14T09:00:00.000Z",
      started_at: "2026-07-14T09:00:10.000Z",
      finished_at: "2026-07-14T09:02:00.000Z",
      error_message: null,
      dagster_run_id: "run-solo",
      dagster_run_status: "SUCCESS",
      trigger_kind: "manual",
      operation_registry_version: null,
      load_batch_id: null,
      parent_job_id: null,
      detail_url: `/v1/ops/pipeline/executions/import_job/${SOLO_JOB_ID}`,
    },
    detail_url: `/v1/ops/pipeline/executions/import_job/${SOLO_JOB_ID}`,
  };
  return [requestRoot, standaloneRoot];
}

function makeOverview(options: {
  queueSensorStatus?: string | null;
  queueSensorPresent?: boolean;
  includeOtherSensor?: boolean;
  dagsterStatus?: "ok" | "unavailable" | "error";
}): PipelineOverviewResponse {
  const dagsterStatus = options.dagsterStatus ?? "ok";
  const sensors = [];
  if (options.queueSensorPresent !== false) {
    sensors.push({
      name: "feature_update_request_queue_sensor",
      status:
        options.queueSensorStatus === undefined
          ? "RUNNING"
          : options.queueSensorStatus,
      recent_ticks: [],
    });
  }
  if (options.includeOtherSensor !== false) {
    sensors.push({
      name: "feature_update_request_failure_sensor",
      status: "RUNNING",
      recent_ticks: [],
    });
  }
  return {
    data: {
      checked_at: "2026-07-14T10:00:00.000Z",
      dagster: {
        status: dagsterStatus,
        dagster_url: "http://dagster.example:12702",
        graphql_url: "http://dagster.example:12702/graphql",
        version: "1.13.7",
        run_counts: { SUCCESS: 4, FAILURE: 1 },
        recent_runs: [],
        schedule_count: 3,
        sensor_count: sensors.length,
        sensors,
        errors: dagsterStatus === "ok" ? [] : ["dagster down"],
      },
      operations_by_status: { queued: 2, running: 1, done: 7, failed: 3 },
      active_operations: 3,
      failed_operations_24h: 3,
    },
    meta: META,
  };
}

function makeDetail(): PipelineExecutionDetailResponse {
  // running 요청은 run-now가 거부(409)라 버튼이 숨는다 — 상세 mock은 queued로.
  const queuedRequest: PipelineExecutionRecord = makeExecution({
    kind: "update_request",
    id: REQUEST_ID,
    status: "queued",
    created_at: "2026-07-14T10:00:00.000Z",
    job_kind: null,
    provider: "python-kma-api",
    dataset_key: "kma_short_forecast",
    progress: null,
    current_stage: null,
    scope_type: "provider_dataset",
    priority: 50,
    run_mode: "queued",
    operator: "tester",
    dagster_run_id: "run-pair",
    job_id: TWIN_JOB_ID,
    request_id: null,
    detail_url: `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
  });
  return {
    data: {
      execution: queuedRequest,
      import_job: {
        job_id: TWIN_JOB_ID,
        kind: "feature_update_request",
        load_batch_id: null,
        parent_job_id: null,
        payload: { request_id: REQUEST_ID },
        status: "running",
        progress: 40,
        current_stage: "loading",
        source_checksum: null,
        error_message: null,
        dagster_run_id: "run-pair",
        dagster_run_status: "STARTED",
        trigger_kind: "update_request",
        operation_registry_version: null,
        provider: "python-kma-api",
        dataset_key: "kma_short_forecast",
        created_at: "2026-07-14T10:00:00.000Z",
        started_at: "2026-07-14T10:00:05.000Z",
        finished_at: null,
        heartbeat_at: "2026-07-14T10:01:00.000Z",
      },
      update_request: {
        request_id: REQUEST_ID,
        scope_type: "provider_dataset",
        scope: {
          type: "provider_dataset",
          provider: "python-kma-api",
          dataset_key: "kma_short_forecast",
          sync_scope: "target_grids",
        },
        requested_sync_scope: "target_grids",
        effective_sync_scope: "target_grids",
        providers: [],
        dataset_keys: [],
        update_policy: {},
        run_mode: "queued",
        priority: 50,
        status: "queued",
        matched_scope: { feature_count: 12 },
        job_id: TWIN_JOB_ID,
        dagster_run_id: "run-pair",
        dispatch_requested_at: null,
        operator: "tester",
        reason: "e2e",
        error_message: null,
        created_at: "2026-07-14T10:00:00.000Z",
        started_at: "2026-07-14T10:00:05.000Z",
        finished_at: null,
        generation: 1,
        status_url: `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
      },
      root: { ...makeRoots()[0], status: "queued" },
      cancellation: null,
      events: [
        {
          event_id: "55555555-5555-5555-5555-555555555555",
          job_id: TWIN_JOB_ID,
          provider: "python-kma-api",
          dataset_key: "kma_short_forecast",
          feature_id: null,
          stage: "loading",
          level: "error",
          code: "provider.timeout",
          message: "kma fetch timeout",
          payload: {},
          occurred_at: "2026-07-14T10:01:00.000Z",
        },
      ],
      events_next_cursor: null,
    },
    meta: META,
  };
}

function makeImportDetail(): PipelineExecutionDetailResponse {
  const source = makeDetail();
  const execution = makeExecution({
    id: TWIN_JOB_ID,
    status: "running",
    provider: "python-kma-api",
    dataset_key: "kma_short_forecast",
    request_id: REQUEST_ID,
    detail_url: `/v1/ops/pipeline/executions/import_job/${TWIN_JOB_ID}`,
  });
  return {
    data: {
      execution,
      import_job: source.data.import_job,
      update_request: null,
      root: source.data.root,
      cancellation: null,
      events: [
        {
          ...source.data.events[0],
          event_id: "66666666-6666-4666-8666-666666666666",
          message: "B execution event",
        },
      ],
      events_next_cursor: null,
    },
    meta: META,
  };
}

function makeSchedules(): PipelineSchedulesResponse {
  return {
    data: {
      status: "ok",
      dagster_url: "http://dagster.example:12702",
      graphql_url: "http://dagster.example:12702/graphql",
      checked_at: "2026-07-14T10:00:00.000Z",
      schedules: [
        {
          name: SCHEDULE_NAME,
          description: null,
          pipeline_name: "kma_short_forecast_job",
          mode: "default",
          cron_schedule: "20 * * * *",
          default_cron_schedule: "20 * * * *",
          override_cron_schedule: "40 * * * *",
          effective_cron_schedule: "20 * * * *",
          override_saved: true,
          override_effective: false,
          execution_timezone: "Asia/Seoul",
          default_status: "RUNNING",
          can_reset: true,
          status: "RUNNING",
          state_id: "state-1::sel",
          selector_id: "sel-1",
          repository_name: "__repository__",
          repository_location_name: "kortravelmap.dagster.definitions",
          schedule_note: null,
          can_run_now: true,
          disabled_reason: null,
          recent_ticks: [],
        },
      ],
      sensors: [
        {
          name: "feature_update_request_queue_sensor",
          status: "RUNNING",
          recent_ticks: [],
        },
        {
          name: "feature_update_request_failure_sensor",
          status: "STOPPED",
          recent_ticks: [],
        },
      ],
      errors: [],
    },
    meta: META,
  };
}

function makeCommandResult(options: {
  auditStatus?: "recorded" | "terminal_record_failed";
  command: "update" | "clear_override" | "run" | "start" | "stop" | "reset";
  status?: "ok" | "error";
  errors?: string[];
}): PipelineScheduleCommandResponse {
  return {
    data: {
      status: options.status ?? "ok",
      dagster_url: "http://dagster.example:12702",
      graphql_url: "http://dagster.example:12702/graphql",
      checked_at: "2026-07-14T10:05:00.000Z",
      schedule_name: SCHEDULE_NAME,
      command: options.command,
      cron_schedule: options.command === "update" ? "15 5 * * *" : "20 * * * *",
      default_cron_schedule: "20 * * * *",
      override_cron_schedule:
        options.command === "update" ? "15 5 * * *" : null,
      effective_cron_schedule: "20 * * * *",
      schedule_status: "RUNNING",
      run_id: options.command === "run" ? "run-launched" : null,
      run_status: options.command === "run" ? "QUEUED" : null,
      save_status:
        options.command === "update"
          ? "saved"
          : options.command === "clear_override"
            ? "cleared"
            : "not_applicable",
      reload_status:
        options.command === "update" || options.command === "clear_override"
          ? "succeeded"
          : "not_requested",
      effective_status:
        options.command === "update" || options.command === "clear_override"
          ? "pending_verification"
          : "confirmed",
      outcome_certainty: "confirmed",
      audit_command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      audit_status: options.auditStatus ?? "recorded",
      errors: options.errors ?? [],
    },
    meta: META,
  };
}

async function fulfillJson(
  route: Route,
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Promise<void> {
  await route.fulfill({
    status,
    contentType:
      status >= 400 ? "application/problem+json" : "application/json",
    headers,
    body: JSON.stringify(body),
  });
}

interface MockOptions {
  executions?: PipelineExecutionRootRecord[];
  executionsForQuery?: (
    query: URLSearchParams,
  ) => PipelineExecutionRootRecord[];
  headExecution?: PipelineExecutionRootRecord;
  headExecutions?: PipelineExecutionRootRecord[];
  nextCursor?: string;
  overview?: PipelineOverviewResponse;
  scheduleCommandStatus?: "ok" | "error";
  schedulePatchStatus?: "ok" | "error";
  scheduleActionStatus?: "ok" | "error";
  scheduleActionStatuses?: Array<"ok" | "error">;
  scheduleActionConflict?: boolean;
  scheduleActionConflictActiveCommandId?: string | null;
  scheduleActionResponseLossOnce?: boolean;
  scheduleUncertainOutcome?: boolean;
  scheduleAuditStatus?: "recorded" | "terminal_record_failed";
  scheduleResponseDelayMs?: number;
  claimResolutionResponseLossOnce?: boolean;
  claimResolutionResponseDelayMs?: number;
  claimResolutionErrorOnce?: { status: number; body: unknown };
  previewResponseDelaysMs?: number[];
  previewFeatureCounts?: number[];
  schedulesResponse?: PipelineSchedulesResponse;
  reusedActiveRequest?: boolean;
  requestCreate?: {
    status?: number;
    headers?: Record<string, string>;
    body?: unknown;
  };
  requestCreateDelayMs?: number;
  requestCreateResponseLossOnce?: boolean;
  detailFactory?: (
    executionId: string,
    query: URLSearchParams,
  ) => PipelineExecutionDetailResponse;
  cancelResponse?: {
    status: number;
    headers?: Record<string, string>;
    body: unknown;
  };
  catalogResponse?: { status: number; body: unknown };
  catalogResponses?: Array<{ status: number; body: unknown }>;
  moisPrecheckResponse?: { status: number; body: unknown };
  moisPrecheckResponses?: Array<{ status: number; body: unknown }>;
}

interface MockCounters {
  executionQueries: URLSearchParams[];
  patchBodies: unknown[];
  commandBodies: unknown[];
  scheduleKeys: string[];
  claimResolutionBodies: unknown[];
  claimResolutionPaths: string[];
  claimResolutionRows: Array<{
    scheduleName: string;
    commandId: string;
    body: unknown;
    response: PipelineScheduleClaimResolutionResponse;
  }>;
  requestBodies: unknown[];
  requestKeys: string[];
  requestRows: Array<{
    idempotencyKey: string;
    body: unknown;
    requestId: string;
  }>;
  previewBodies: unknown[];
  runNowBodies: Array<string | null>;
  detailQueries: Array<{ executionId: string; query: URLSearchParams }>;
  cancelBodies: unknown[];
  legacyProviderCalls: number;
  catalogCalls: number;
  moisPrecheckCalls: number;
}

async function installPipelineMocks(
  page: Page,
  options: MockOptions = {},
): Promise<MockCounters> {
  const counters: MockCounters = {
    executionQueries: [],
    patchBodies: [],
    commandBodies: [],
    scheduleKeys: [],
    claimResolutionBodies: [],
    claimResolutionPaths: [],
    claimResolutionRows: [],
    requestBodies: [],
    requestKeys: [],
    requestRows: [],
    previewBodies: [],
    runNowBodies: [],
    detailQueries: [],
    cancelBodies: [],
    legacyProviderCalls: 0,
    catalogCalls: 0,
    moisPrecheckCalls: 0,
  };
  const claimResolutionLedger = new Map<
    string,
    MockCounters["claimResolutionRows"][number]
  >();
  const executions = options.executions ?? makeRoots();
  let firstPageQueries = 0;

  await page.route("**/v1/ops/pipeline/**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (pathname.endsWith("/v1/ops/pipeline/overview")) {
      await fulfillJson(route, options.overview ?? makeOverview({}));
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/prechecks/mois-source-sync")) {
      const response =
        options.moisPrecheckResponses?.[
          Math.min(
            counters.moisPrecheckCalls,
            options.moisPrecheckResponses.length - 1,
          )
        ] ?? options.moisPrecheckResponse;
      counters.moisPrecheckCalls += 1;
      if (response) {
        await fulfillJson(route, response.body, response.status);
        return;
      }
      await fulfillJson(route, makeMoisPrecheckResponse());
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/executions")) {
      counters.executionQueries.push(url.searchParams);
      const queriedExecutions =
        options.executionsForQuery?.(url.searchParams) ?? executions;
      const cursor = url.searchParams.get("cursor");
      if (!cursor) {
        firstPageQueries += 1;
      }
      const items = cursor
        ? queriedExecutions.slice(1)
        : (options.headExecutions || options.headExecution) &&
            firstPageQueries > 1
          ? [
              ...(options.headExecutions ?? [options.headExecution!]),
              ...queriedExecutions,
            ]
          : queriedExecutions;
      const body: PipelineExecutionsListResponse = {
        data: { items },
        meta: {
          ...META,
          page: {
            page_size: 50,
            next_cursor: cursor ? null : (options.nextCursor ?? null),
            total: null,
          },
        },
      };
      await fulfillJson(route, body);
      return;
    }
    if (
      /\/v1\/ops\/pipeline\/executions\/[^/]+\/[^/]+\/cancel$/.test(pathname)
    ) {
      counters.cancelBodies.push(request.postDataJSON());
      const response = options.cancelResponse;
      if (response) {
        await fulfillJson(
          route,
          response.body,
          response.status,
          response.headers ?? {},
        );
      } else {
        await fulfillJson(route, {
          data: {
            cancellation_id: "77777777-7777-4777-8777-777777777777",
            committed_data_rolled_back: false,
            dagster_runs: [],
            error: null,
            finished_at: null,
            members: [],
            previous_cancellation_id: null,
            reason: "e2e cancel",
            requested_at: "2026-07-14T10:03:00.000Z",
            requested_by: "admin:e2e",
            retryable: false,
            root: { kind: "update_request", id: REQUEST_ID },
            status: "in_progress",
            unresolved_member_count: 1,
            updated_at: "2026-07-14T10:03:00.000Z",
            warnings: [],
          },
          meta: META,
        });
      }
      return;
    }
    if (/\/v1\/ops\/pipeline\/executions\/[^/]+\/[^/]+$/.test(pathname)) {
      const executionId = decodeURIComponent(pathname.split("/").at(-1) ?? "");
      counters.detailQueries.push({ executionId, query: url.searchParams });
      await fulfillJson(
        route,
        options.detailFactory?.(executionId, url.searchParams) ?? makeDetail(),
      );
      return;
    }
    if (/\/v1\/ops\/pipeline\/dagster-runs\/[^/]+$/.test(pathname)) {
      const body: PipelineDagsterRunDetailResponse = {
        data: {
          status: "ok",
          dagster_url: "http://dagster.example:12702",
          graphql_url: "http://dagster.example:12702/graphql",
          checked_at: "2026-07-14T10:00:00.000Z",
          run: {
            run_id: "run-orphan",
            job_name: "kma_short_forecast_job",
            status: "FAILURE",
            start_time: 1789344000,
            end_time: null,
            update_time: null,
            tags: {},
          },
          events: [
            {
              event_type: "MessageEvent",
              message: "step failed: kma fetch",
              timestamp: "1789344001000",
              level: "ERROR",
              step_id: "load_step",
              dagster_event_type: "STEP_FAILURE",
              error: null,
            },
          ],
          failure_reason: "STEP_FAILURE: kma fetch timeout",
          failure_events: [],
          event_cursor: null,
          event_has_more: false,
          errors: [],
        },
        meta: META,
      };
      await fulfillJson(route, body);
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/dagster-runs")) {
      const body: PipelineDagsterRunsResponse = {
        data: {
          status: "ok",
          dagster_url: "http://dagster.example:12702",
          graphql_url: "http://dagster.example:12702/graphql",
          checked_at: "2026-07-14T10:00:00.000Z",
          run_counts: { FAILURE: 1 },
          runs: [
            {
              run_id: "run-orphan",
              job_name: "kma_short_forecast_job",
              status: "FAILURE",
              start_time: 1789344000,
              end_time: null,
              update_time: null,
              tags: {},
            },
          ],
          errors: [],
        },
        meta: META,
      };
      await fulfillJson(route, body);
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/events")) {
      const body: PipelineEventsListResponse = {
        data: { items: makeDetail().data.events ?? [] },
        meta: {
          ...META,
          page: { page_size: 50, next_cursor: null, total: null },
        },
      };
      await fulfillJson(route, body);
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/schedules")) {
      await fulfillJson(route, options.schedulesResponse ?? makeSchedules());
      return;
    }
    if (
      /\/v1\/ops\/pipeline\/schedules\/[^/]+\/claims\/[^/]+\/resolve$/.test(
        pathname,
      )
    ) {
      const body = request.postDataJSON();
      const parts = pathname.split("/");
      const commandId = decodeURIComponent(parts.at(-2) ?? "");
      const scheduleName = decodeURIComponent(parts.at(-4) ?? "");
      const ledgerKey = JSON.stringify([scheduleName, commandId]);
      const existingRow = claimResolutionLedger.get(ledgerKey);
      counters.claimResolutionBodies.push(body);
      counters.claimResolutionPaths.push(pathname);
      if (
        existingRow &&
        JSON.stringify(existingRow.body) !== JSON.stringify(body)
      ) {
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-idempotency-conflict",
            title: "Idempotency conflict",
            status: 409,
            detail: "같은 schedule claim에 다른 확인 결과를 기록할 수 없습니다.",
            code: "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
            request_id: "e2e-pipeline",
            errors: [],
            details: { active_command_id: commandId },
          },
          409,
        );
        return;
      }
      if (
        options.claimResolutionErrorOnce &&
        counters.claimResolutionBodies.length === 1
      ) {
        await fulfillJson(
          route,
          options.claimResolutionErrorOnce.body,
          options.claimResolutionErrorOnce.status,
        );
        return;
      }
      const response: PipelineScheduleClaimResolutionResponse =
        existingRow?.response ?? {
          data: {
            resolution_id: 42,
            command_id: commandId,
            schedule_name: scheduleName,
            resolution: body.resolution,
            actor: "admin:e2e",
            reason: body.reason,
            resolved_at: "2026-07-14T10:06:00.000Z",
            replayed: false,
          },
          meta: META,
        };
      if (!existingRow) {
        const row = { scheduleName, commandId, body, response };
        claimResolutionLedger.set(ledgerKey, row);
        counters.claimResolutionRows.push(row);
      }
      if (options.claimResolutionResponseDelayMs) {
        await new Promise((resolve) =>
          setTimeout(resolve, options.claimResolutionResponseDelayMs),
        );
      }
      if (
        options.claimResolutionResponseLossOnce &&
        counters.claimResolutionBodies.length === 1
      ) {
        await route.abort("connectionreset");
        return;
      }
      await fulfillJson(
        route,
        existingRow
          ? { ...response, data: { ...response.data, replayed: true } }
          : response,
      );
      return;
    }
    if (/\/v1\/ops\/pipeline\/schedules\/[^/]+$/.test(pathname)) {
      counters.patchBodies.push(request.postDataJSON());
      counters.scheduleKeys.push(request.headers()["idempotency-key"] ?? "");
      const body = request.postDataJSON() as { cron_schedule: string | null };
      if (options.scheduleResponseDelayMs) {
        await new Promise((resolve) =>
          setTimeout(resolve, options.scheduleResponseDelayMs),
        );
      }
      if (
        (options.schedulePatchStatus ?? options.scheduleCommandStatus) ===
        "error"
      ) {
        const partial = makeCommandResult({
          command: body.cron_schedule === null ? "clear_override" : "update",
          errors: ["Dagster mutation failed"],
          status: "error",
        });
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-command-failed",
            title: "Dagster mutation failed",
            status: 502,
            detail: "Dagster mutation failed",
            code: "DAGSTER_SCHEDULE_COMMAND_FAILED",
            request_id: "e2e-pipeline",
            errors: [],
            details: partial.data,
          },
          502,
        );
        return;
      }
      await fulfillJson(
        route,
        makeCommandResult({
          auditStatus: options.scheduleAuditStatus,
          command: body.cron_schedule === null ? "clear_override" : "update",
        }),
      );
      return;
    }
    if (pathname.endsWith("/commands")) {
      counters.commandBodies.push(request.postDataJSON());
      counters.scheduleKeys.push(request.headers()["idempotency-key"] ?? "");
      const body = request.postDataJSON() as { command: string };
      if (
        options.scheduleActionResponseLossOnce &&
        counters.commandBodies.length === 1
      ) {
        await route.abort("connectionreset");
        return;
      }
      if (
        options.scheduleActionResponseLossOnce &&
        counters.commandBodies.length === 2
      ) {
        const activeCommandId = counters.scheduleKeys[0];
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-idempotency-conflict",
            title: "이전 명령 결과 확인 필요",
            status: 409,
            detail: "이 schedule 명령은 실행 중이거나 결과 확인이 필요합니다.",
            code: "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
            request_id: "e2e-pipeline",
            errors: [],
            details: {
              command_id: activeCommandId,
              active_command_id: activeCommandId,
            },
          },
          409,
        );
        return;
      }
      const actionStatuses = options.scheduleActionStatuses;
      const actionStatus =
        (actionStatuses && actionStatuses.length > 0
          ? actionStatuses[
              Math.min(
                counters.commandBodies.length - 1,
                actionStatuses.length - 1,
              )
            ]
          : undefined) ??
        options.scheduleActionStatus ??
        options.scheduleCommandStatus;
      if (options.scheduleResponseDelayMs) {
        await new Promise((resolve) =>
          setTimeout(resolve, options.scheduleResponseDelayMs),
        );
      }
      if (options.scheduleActionConflict) {
        const activeCommandId =
          options.scheduleActionConflictActiveCommandId === undefined
            ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            : options.scheduleActionConflictActiveCommandId;
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-idempotency-conflict",
            title: "이전 명령 결과 확인 필요",
            status: 409,
            detail: "이 schedule의 이전 명령 결과가 확정되지 않았습니다.",
            code: "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
            request_id: "e2e-pipeline",
            errors: [],
            details: {
              command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
              active_command_id: activeCommandId,
            },
          },
          409,
        );
        return;
      }
      if (options.scheduleUncertainOutcome) {
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-outcome-uncertain",
            title: "Dagster 결과 불명",
            status: 500,
            detail: "응답 유실로 실제 반영 여부를 확인해야 합니다.",
            code: "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN",
            request_id: "e2e-pipeline",
            errors: [],
            details: {
              command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              active_command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              outcome_certainty: "uncertain",
            },
          },
          500,
        );
        return;
      }
      if (actionStatus === "error") {
        const partial = makeCommandResult({
          command: body.command as "run" | "start" | "stop" | "reset",
          errors: ["Dagster mutation failed"],
          status: "error",
        });
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/dagster-schedule-command-failed",
            title: "Dagster mutation failed",
            status: 502,
            detail: "Dagster mutation failed",
            code: "DAGSTER_SCHEDULE_COMMAND_FAILED",
            request_id: "e2e-pipeline",
            errors: [],
            details: partial.data,
          },
          502,
        );
        return;
      }
      await fulfillJson(
        route,
        makeCommandResult({
          auditStatus: options.scheduleAuditStatus,
          command: body.command as "run" | "start" | "stop" | "reset",
        }),
      );
      return;
    }
    if (pathname.endsWith("/run-now")) {
      counters.runNowBodies.push(request.postData());
      const updateRequest = makeDetail().data.update_request;
      const body: FeatureUpdateRequestMutationResponse = {
        data: {
          ...updateRequest!,
          dispatch_requested_at: "2026-07-14T10:02:00.000Z",
        },
        meta: META,
      };
      await fulfillJson(route, body);
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/requests/preview")) {
      counters.previewBodies.push(request.postDataJSON());
      const previewIndex = counters.previewBodies.length - 1;
      const previewDelay = options.previewResponseDelaysMs?.[previewIndex] ?? 0;
      if (previewDelay > 0) {
        await new Promise((resolve) => setTimeout(resolve, previewDelay));
      }
      const preview: FeatureUpdateRequestPreviewResponse = {
        data: {
          result_kind: "preview",
          scope_type: "provider_dataset",
          scope: {
            type: "provider_dataset",
            provider: "python-mois-api",
            dataset_key: "mois_licenses",
          },
          providers: [],
          dataset_keys: [],
          update_policy: {},
          run_mode: "queued",
          priority: 50,
          matched_scope: {
            feature_count: options.previewFeatureCounts?.[previewIndex] ?? 12,
          },
        },
        meta: META,
      };
      await fulfillJson(route, preview);
      return;
    }
    if (pathname.endsWith("/v1/ops/pipeline/requests")) {
      const requestBody = request.postDataJSON();
      const idempotencyKey = request.headers()["idempotency-key"] ?? "";
      counters.requestBodies.push(requestBody);
      counters.requestKeys.push(idempotencyKey);
      if (options.requestCreateDelayMs) {
        await new Promise((resolve) =>
          setTimeout(resolve, options.requestCreateDelayMs),
        );
      }
      const custom = options.requestCreate;
      if (custom && custom.status && custom.status >= 400) {
        await fulfillJson(
          route,
          custom.body ?? {
            type: "https://kor-travel-map/errors/lock-busy",
            title: "동일 feature update scope가 이미 실행 중입니다.",
            status: 409,
            detail: "동일 feature update scope가 이미 실행 중입니다.",
            code: "ACTIVE_SCOPE_CONFLICT",
            request_id: "e2e",
            errors: [],
            details: { request_id: REQUEST_ID },
          },
          custom.status,
          custom.headers ?? {},
        );
        return;
      }
      const existingRow = counters.requestRows.find(
        (row) => row.idempotencyKey === idempotencyKey,
      );
      if (
        existingRow &&
        JSON.stringify(existingRow.body) !== JSON.stringify(requestBody)
      ) {
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/feature-update-idempotency-conflict",
            title: "Idempotency-Key conflict",
            status: 409,
            detail: "같은 키를 다른 body에 사용할 수 없습니다.",
            code: "FEATURE_UPDATE_IDEMPOTENCY_CONFLICT",
            request_id: "e2e",
            errors: [],
          },
          409,
        );
        return;
      }
      if (!existingRow) {
        counters.requestRows.push({
          idempotencyKey,
          body: requestBody,
          requestId: REQUEST_ID,
        });
      }
      if (
        options.requestCreateResponseLossOnce &&
        counters.requestBodies.length === 1
      ) {
        await route.abort("connectionreset");
        return;
      }
      const idempotentReplay = existingRow !== undefined;
      const created: FeatureUpdateRequestCreateResponse = {
        data: {
          result_kind: "request",
          request_id: REQUEST_ID,
          scope_type: "provider_dataset",
          scope: {
            type: "provider_dataset",
            provider: "python-kma-api",
            dataset_key: "kma_short_forecast",
            sync_scope: "target_grids",
          },
          requested_sync_scope: "target_grids",
          effective_sync_scope: "target_grids",
          providers: [],
          dataset_keys: [],
          update_policy: {},
          run_mode: "queued",
          priority: 50,
          status: "queued",
          matched_scope: { feature_count: 12 },
          job_id: TWIN_JOB_ID,
          dagster_run_id: null,
          dispatch_requested_at: null,
          operator: "tester",
          reason: null,
          error_message: null,
          created_at: "2026-07-14T10:00:00.000Z",
          started_at: null,
          finished_at: null,
          generation: 1,
          status_url: `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
        },
        idempotent_replay: idempotentReplay,
        reused_active_request: options.reusedActiveRequest ?? false,
        meta: META,
      };
      await fulfillJson(
        route,
        created,
        idempotentReplay || options.reusedActiveRequest ? 200 : 201,
      );
      return;
    }
    await route.continue();
  });

  await page.route("**/v1/debug/etl/providers**", async (route) => {
    counters.legacyProviderCalls += 1;
    await fulfillJson(route, { data: { providers: [] }, meta: META });
  });

  // 요청 dialog는 C4와 같은 canonical ops datasets catalog만 사용한다.
  await page.route("**/v1/ops/datasets", async (route) => {
    const sequenceResponse =
      options.catalogResponses?.[
        Math.min(counters.catalogCalls, options.catalogResponses.length - 1)
      ];
    counters.catalogCalls += 1;
    const configuredResponse = sequenceResponse ?? options.catalogResponse;
    if (configuredResponse) {
      await fulfillJson(
        route,
        configuredResponse.body,
        configuredResponse.status,
      );
      return;
    }
    await fulfillJson(route, makeCatalogResponse());
  });
  return counters;
}

/**
 * #520 인증 게이트: middleware가 유효 세션 없는 페이지 접근을 /login으로
 * 돌린다. live suite의 auth.setup.ts와 같은 규약 — `E2E_ADMIN_PASSWORD`가
 * 설정된 대상에서는 UI 로그인으로 세션을 만들고(로그인 → same-site 내비게이션
 * 이라 SameSite=Strict 쿠키 유지), 미설정이면 인증이 꺼진 대상으로 간주한다.
 */
async function loginIfConfigured(page: Page): Promise<void> {
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!password) {
    return;
  }
  const username = process.env.E2E_ADMIN_USERNAME ?? "admin";
  await page.goto("/login");
  await page.locator("#admin-username").fill(username);
  await page.locator("#admin-password").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 15_000,
  });
}

test.describe("/ops/pipeline", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
    await loginIfConfigured(page);
  });

  test("상태 스트립 + root 타임라인(projected_job 분리 표시)", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline");

    await expect(
      page.getByRole("heading", { level: 1, name: "파이프라인" }),
    ).toBeVisible();
    await expect(page.getByText("활성 작업")).toBeVisible();
    await expect(page.getByText("대기", { exact: true })).toBeVisible();
    await expect(page.getByText("실행 중", { exact: true })).toBeVisible();
    await expect(page.getByText("최근 24시간 실패")).toBeVisible();

    // C3b (a): root 2건 응답 → 표시 행 2행. descendant job은 별도 행이 아니다.
    const requestRow = page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`);
    await expect(requestRow).toBeVisible();
    await expect(requestRow.getByText("작업 2")).toBeVisible();
    // C3b (b): effective provider_datasets exact pair로 대상 표시.
    await expect(requestRow.getByText("python-kma-api")).toBeVisible();
    await expect(requestRow.getByText("kma_short_forecast")).toBeVisible();
    await expect(requestRow.getByText("target_grids")).toBeVisible();
    // C3b (c): request 상태와 projected_job 진행률·단계 분리 표시.
    await expect(requestRow.getByText("40% · loading")).toBeVisible();
    await expect(
      page.getByTestId(`pipeline-execution-row-${SOLO_JOB_ID}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`pipeline-execution-row-${TWIN_JOB_ID}`),
    ).toHaveCount(0);

    // Dagster 보조 패널 — 순수 Dagster 실패 가시성 + C3c run 상세 소비.
    const panel = page.getByTestId("pipeline-dagster-runs-panel");
    await expect(panel.getByText("run-orph")).toBeVisible();
    await panel
      .getByRole("button", { name: "run run-orph... 상세 열기" })
      .click();
    const runDetail = page.getByTestId(
      "pipeline-dagster-run-detail-run-orphan",
    );
    await expect(runDetail).toBeVisible();
    await expect(runDetail).toContainText("STEP_FAILURE: kma fetch timeout");
  });

  test("큐 sensor 중지 시 destructive alert", async ({ page }) => {
    await installPipelineMocks(page, {
      overview: makeOverview({ queueSensorStatus: "STOPPED" }),
    });
    await page.goto("/ops/pipeline");

    const alert = page.getByTestId("queue-sensor-alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("갱신 요청 큐 sensor 중지됨");
    await expect(
      page.getByRole("button", {
        name: "갱신 요청 생성 (큐 sensor 확인 필요)",
      }),
    ).toBeDisabled();
  });

  for (const scenario of [
    {
      name: "unknown",
      overview: makeOverview({ queueSensorStatus: null }),
    },
    {
      name: "missing",
      overview: makeOverview({
        queueSensorPresent: false,
        includeOtherSensor: false,
      }),
    },
    {
      name: "other-only",
      overview: makeOverview({ queueSensorPresent: false }),
    },
  ]) {
    test(`큐 sensor ${scenario.name} 응답도 fail-closed`, async ({ page }) => {
      await installPipelineMocks(page, { overview: scenario.overview });
      await page.goto("/ops/pipeline");

      await expect(page.getByTestId("queue-sensor-alert")).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: "갱신 요청 생성 (큐 sensor 확인 필요)",
        }),
      ).toBeDisabled();
      await expect(
        page.getByRole("button", { name: "갱신 요청 생성", exact: true }),
      ).toHaveCount(0);
    });
  }

  test("큐 sensor RUNNING일 때만 요청 생성을 연다", async ({ page }) => {
    await installPipelineMocks(page, {
      overview: makeOverview({ queueSensorStatus: "RUNNING" }),
    });
    await page.goto("/ops/pipeline");

    await expect(page.getByTestId("queue-sensor-alert")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "갱신 요청 생성", exact: true }),
    ).toBeEnabled();
  });

  test("Dagster overview degrade 중에도 DB 타임라인은 유지", async ({
    page,
  }) => {
    await installPipelineMocks(page, {
      overview: makeOverview({ dagsterStatus: "unavailable" }),
    });
    await page.goto("/ops/pipeline");

    await expect(page.getByText("Dagster 연결 불가")).toBeVisible();
    await expect(
      page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`),
    ).toBeVisible();
  });

  test("필터가 executions 쿼리 파라미터로 전달된다", async ({ page }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    await expect(
      page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`),
    ).toBeVisible();

    await page.getByLabel("실행 상태").selectOption("running");
    await page.getByLabel("provider 필터").fill("python-kma-api");
    await page.getByLabel("데이터셋 필터").fill("kma_short_forecast");
    await page.getByLabel("sync scope 필터").fill("target_grids");

    await expect
      .poll(() => {
        const last = counters.executionQueries.at(-1);
        return [
          last?.get("status"),
          last?.get("provider"),
          last?.get("dataset_key"),
          last?.get("sync_scope"),
        ].join("|");
      })
      .toBe("running|python-kma-api|kma_short_forecast|target_grids");
  });

  test("텍스트 필터는 여러 글자를 입력해도 focus와 URL 상태를 유지한다", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    const provider = page.getByLabel("provider 필터");

    await provider.pressSequentially("python-kma-api");

    await expect(provider).toBeFocused();
    await expect(provider).toHaveValue("python-kma-api");
    await expect(page).toHaveURL(/provider=python-kma-api/);
  });

  test("필터·탭 URL을 초기 복원하고 back/forward로 조사 상태를 재현", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto(
      "/ops/pipeline?kind=update_request&status=running&provider=python-kma-api&dataset_key=kma_short_forecast&sync_scope=target_grids&created_from=2026-07-14T09%3A00&created_to=2026-07-14T12%3A00&tab=executions",
    );

    await expect(page.getByLabel("실행 종류")).toHaveValue("update_request");
    await expect(page.getByLabel("실행 상태")).toHaveValue("running");
    await expect(page.getByLabel("provider 필터")).toHaveValue(
      "python-kma-api",
    );
    await expect(page.getByLabel("데이터셋 필터")).toHaveValue(
      "kma_short_forecast",
    );
    await expect(page.getByLabel("sync scope 필터")).toHaveValue(
      "target_grids",
    );
    await expect(page.getByLabel("생성 시작일")).toHaveValue(
      "2026-07-14T09:00",
    );
    await expect(page.getByLabel("생성 종료일")).toHaveValue(
      "2026-07-14T12:00",
    );

    await page.getByLabel("실행 상태").selectOption("failed");
    await expect(page).toHaveURL(/status=failed/);
    await page.getByRole("tab", { name: "전역 이벤트" }).click();
    await expect(page).toHaveURL(/tab=events/);

    await page.goBack();
    await expect(
      page.getByRole("tab", { name: "실행 타임라인" }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(page.getByLabel("실행 상태")).toHaveValue("failed");
    await page.goBack();
    await expect(page.getByLabel("실행 상태")).toHaveValue("running");
    await page.goForward();
    await expect(page.getByLabel("실행 상태")).toHaveValue("failed");
  });

  test("잘못된 날짜 딥링크는 화면을 깨뜨리지 않고 서버 필터에서 제외", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto(
      "/ops/pipeline?created_from=not-a-date&created_to=%25invalid&tab=executions",
    );

    await expect(
      page.getByRole("heading", { name: "파이프라인" }),
    ).toBeVisible();
    await expect(page.getByLabel("생성 시작일")).toHaveValue("");
    await expect(page.getByLabel("생성 종료일")).toHaveValue("");
    await expect
      .poll(() => {
        const last = counters.executionQueries.at(-1);
        return `${last?.has("created_from")}|${last?.has("created_to")}`;
      })
      .toBe("false|false");
  });

  test("UTC 날짜 딥링크를 datetime-local로 표시하고 같은 instant를 조회", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    const source = "2026-07-14T00:30:00.000Z";
    await page.goto(
      `/ops/pipeline?created_from=${encodeURIComponent(source)}&tab=executions`,
    );
    const expectedLocal = await page.evaluate((iso) => {
      const value = new Date(iso);
      const pad = (part: number) => String(part).padStart(2, "0");
      return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
    }, source);

    await expect(page.getByLabel("생성 시작일")).toHaveValue(expectedLocal);
    await expect
      .poll(() => counters.executionQueries.at(-1)?.get("created_from"))
      .toBe(source);
  });

  test("cursor 페이지 조사 중에는 목록을 재정렬하지 않고 새 실행 배지를 표시", async ({
    page,
  }) => {
    const headExecution: PipelineExecutionRootRecord = {
      ...makeRoots()[0],
      id: NEW_REQUEST_ID,
      created_at: "2026-07-14T11:00:00.000Z",
      detail_url: `/v1/ops/pipeline/executions/update_request/${NEW_REQUEST_ID}`,
    };
    await installPipelineMocks(page, {
      headExecution,
      nextCursor: "cursor-page-2",
    });
    await page.goto("/ops/pipeline");

    await page
      .getByRole("button", { name: "실행 타임라인 다음 페이지" })
      .click();
    await expect(page.getByText("page 2 · 이 페이지 1행")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "새 실행 1건 반영" }),
    ).toBeVisible();
    await expect(
      page.getByTestId(`pipeline-execution-row-${NEW_REQUEST_ID}`),
    ).toHaveCount(0);
  });

  test("새 실행 배지는 created_at/id/kind total order와 50+ 상한을 보존", async ({
    page,
  }) => {
    const baseline = makeRoots()[1];
    const sameIdentityOtherKind: PipelineExecutionRootRecord = {
      ...baseline,
      kind: "update_request",
      id: baseline.id,
      providers: [],
      dataset_keys: [],
      provider_datasets: [],
      linked_job_count: 1,
      detail_url: `/v1/ops/pipeline/executions/update_request/${baseline.id}`,
    };
    const headExecutions = Array.from({ length: 50 }, (_, index) => ({
      ...sameIdentityOtherKind,
      id:
        index === 0
          ? baseline.id
          : `ffffffff-ffff-4fff-8fff-${String(index).padStart(12, "0")}`,
      created_at:
        index === 0 ? baseline.created_at : "2026-07-14T12:00:00.000Z",
    }));
    await installPipelineMocks(page, {
      executions: [baseline],
      headExecutions,
      nextCursor: "cursor-page-2",
    });
    await page.goto("/ops/pipeline");

    await page
      .getByRole("button", { name: "실행 타임라인 다음 페이지" })
      .click();
    await expect(
      page.getByRole("button", { name: "새 실행 50+건 반영" }),
    ).toBeVisible();
  });

  test("행 클릭 → 상세 패널(이벤트·연결 개체·run-now 문구)", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline");

    await page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`).click();

    const panel = page.getByTestId("pipeline-execution-detail");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("kma fetch timeout")).toBeVisible();
    await expect(panel.getByText("40% · loading")).toBeVisible();
    await expect(
      panel.getByRole("button", { name: "즉시 재큐잉 (run-now)" }),
    ).toBeVisible();
    await expect(
      panel.getByText("새 요청을 만들지 않고", { exact: false }),
    ).toBeVisible();
    await expect(
      panel.getByRole("button", { name: "취소 요청" }),
    ).toBeVisible();
  });

  test("A→B 상세 전환은 cursor·취소 사유·mutation 오류 상태를 격리", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      detailFactory: (executionId) => {
        if (executionId === TWIN_JOB_ID) {
          return makeImportDetail();
        }
        const detail = makeDetail();
        return {
          ...detail,
          data: { ...detail.data, events_next_cursor: "cursor-a" },
        };
      },
      cancelResponse: {
        status: 503,
        headers: { "Retry-After": "7" },
        body: {
          type: "https://kor-travel-map/errors/dagster-unavailable",
          title: "Dagster 연결 실패",
          status: 503,
          detail: "Dagster terminal 확인에 실패했습니다.",
          code: "DAGSTER_UNAVAILABLE",
          request_id: "e2e-cancel",
          errors: [],
          details: {
            cancellation_id: "77777777-7777-4777-8777-777777777777",
            status: "retryable",
            retryable: true,
            unresolved_member_count: 1,
          },
        },
      },
    });
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);

    let panel = page.getByTestId("pipeline-execution-detail");
    await panel.getByLabel("이벤트 레벨").selectOption("warning");
    await panel.getByRole("button", { name: "이전 이벤트 더 보기" }).click();
    await panel.getByLabel("취소 사유").fill("A only reason");
    await panel.getByRole("button", { name: "취소 요청" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "취소 요청", exact: true })
      .click();

    await expect(panel.getByText("취소 실패")).toBeVisible();
    await expect(panel).toContainText("DAGSTER_UNAVAILABLE");
    await expect(panel).toContainText("7초 후 재시도 가능");
    await expect(panel.getByLabel("취소 실패 상세 근거")).toContainText(
      '"retryable":true',
    );
    await expect
      .poll(
        () =>
          counters.detailQueries.filter(
            (entry) => entry.executionId === REQUEST_ID,
          ).length,
      )
      .toBeGreaterThan(2);

    await panel.getByRole("button", { name: /대표 작업/ }).click();
    panel = page.getByTestId("pipeline-execution-detail");
    await expect(panel).toContainText("B execution event");
    await expect(panel.getByLabel("이벤트 레벨")).toHaveValue("all");
    await expect(panel.getByLabel("이벤트 처음")).toBeDisabled();
    await expect(panel.getByLabel("취소 사유")).toHaveValue("");
    await expect(panel.getByText("취소 실패")).toHaveCount(0);
    expect(counters.cancelBodies).toEqual([{ reason: "A only reason" }]);
  });

  test("취소 진행 중에는 중복 취소와 run-now를 함께 차단", async ({ page }) => {
    await installPipelineMocks(page, {
      detailFactory: () => {
        const detail = makeDetail();
        return {
          ...detail,
          data: {
            ...detail.data,
            cancellation: {
              cancellation_id: "77777777-7777-4777-8777-777777777777",
              committed_data_rolled_back: false,
              dagster_runs: [],
              error: null,
              finished_at: null,
              members: [],
              previous_cancellation_id: null,
              reason: "operator request",
              requested_at: "2026-07-14T10:03:00.000Z",
              requested_by: "admin:e2e",
              retryable: false,
              root: { kind: "update_request", id: REQUEST_ID },
              status: "in_progress",
              unresolved_member_count: 1,
              updated_at: "2026-07-14T10:03:00.000Z",
              warnings: [],
            },
          },
        };
      },
    });
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);

    const panel = page.getByTestId("pipeline-execution-detail");
    await expect(
      panel.getByText("취소 진행 중", { exact: true }),
    ).toBeVisible();
    await expect(panel.getByRole("button", { name: "취소 요청" })).toHaveCount(
      0,
    );
    await expect(panel.getByRole("button", { name: /run-now/ })).toHaveCount(0);
  });

  test("재시도 불가 취소 이력이 있으면 활성 실행도 중복 취소를 차단", async ({
    page,
  }) => {
    await installPipelineMocks(page, {
      detailFactory: () => {
        const detail = makeDetail();
        return {
          ...detail,
          data: {
            ...detail.data,
            cancellation: {
              cancellation_id: "77777777-7777-4777-8777-777777777777",
              committed_data_rolled_back: false,
              dagster_runs: [],
              error: "Dagster 종료 여부를 확정할 수 없음",
              finished_at: "2026-07-14T10:04:00.000Z",
              members: [],
              previous_cancellation_id: null,
              reason: "operator request",
              requested_at: "2026-07-14T10:03:00.000Z",
              requested_by: "admin:e2e",
              retryable: false,
              root: { kind: "update_request", id: REQUEST_ID },
              status: "failed",
              unresolved_member_count: 1,
              updated_at: "2026-07-14T10:04:00.000Z",
              warnings: [],
            },
          },
        };
      },
    });
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);

    const panel = page.getByTestId("pipeline-execution-detail");
    await expect(panel.getByText("취소 작업 failed")).toBeVisible();
    await expect(panel.getByRole("button", { name: "취소 요청" })).toHaveCount(
      0,
    );
    await expect(
      panel.getByRole("button", { name: "취소 재시도" }),
    ).toHaveCount(0);
  });

  test("run-now는 body 없이 같은 canonical request를 200으로 갱신", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);
    await expect.poll(() => counters.catalogCalls).toBeGreaterThan(0);
    const catalogCallsBeforeRunNow = counters.catalogCalls;

    const panel = page.getByTestId("pipeline-execution-detail");
    await panel.getByRole("button", { name: "즉시 재큐잉 (run-now)" }).click();

    await expect(panel.getByText("우선 dispatch 요청됨")).toBeVisible();
    await expect(panel.getByText(REQUEST_ID.slice(0, 12))).toBeVisible();
    expect(counters.runNowBodies).toEqual([null]);
    await expect
      .poll(() => counters.catalogCalls)
      .toBeGreaterThan(catalogCallsBeforeRunNow);
    const detailCallsBeforeSameSelection = counters.detailQueries.length;
    await panel.getByRole("button", { name: "같은 요청 다시 열기" }).click();
    await expect
      .poll(() => counters.detailQueries.length)
      .toBeGreaterThan(detailCallsBeforeSameSelection);
  });

  test("running request run-now는 동일 canonical 요청을 멱등 확인", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      detailFactory: () => {
        const detail = makeDetail();
        return {
          ...detail,
          data: {
            ...detail.data,
            execution: { ...detail.data.execution, status: "running" },
            update_request: {
              ...detail.data.update_request!,
              status: "running",
            },
          },
        };
      },
    });
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);

    const panel = page.getByTestId("pipeline-execution-detail");
    await panel
      .getByRole("button", { name: "실행 중 요청 확인 (run-now)" })
      .click();
    await expect(panel.getByText("우선 dispatch 요청됨")).toBeVisible();
    expect(counters.runNowBodies).toEqual([null]);
  });

  test("딥링크 execution= 로 상세가 열리고 schedule= 로 스케줄 탭 하이라이트", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto(`/ops/pipeline?execution=update_request:${REQUEST_ID}`);
    await expect(page.getByTestId("pipeline-execution-detail")).toBeVisible();

    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);
    const row = page.getByTestId(`pipeline-schedule-row-${SCHEDULE_NAME}`);
    await expect(row).toBeVisible();
    await expect(row).toHaveClass(/ring-2/);
    await expect(row.getByText("override")).toBeVisible();
  });

  test("상세 열기/닫기 URL은 browser history로 복원", async ({ page }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline");

    await page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`).click();
    await expect(page).toHaveURL(
      new RegExp(`execution=update_request%3A${REQUEST_ID}`),
    );
    await page.getByRole("button", { name: "실행 상세 닫기" }).click();
    await expect(page).not.toHaveURL(/execution=/);
    await expect(
      page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`),
    ).toBeFocused();
    await page.goBack();
    await expect(page.getByTestId("pipeline-execution-detail")).toBeVisible();
  });

  test("programmatic history 변경도 detail과 tab의 단일 URL 상태를 반영", async ({
    page,
  }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline");

    await page.evaluate((requestId) => {
      window.history.pushState(
        null,
        "",
        `/ops/pipeline?execution=update_request%3A${requestId}&tab=executions`,
      );
    }, REQUEST_ID);
    await expect(page.getByTestId("pipeline-execution-detail")).toBeVisible();

    await page.evaluate((scheduleName) => {
      window.history.pushState(
        null,
        "",
        `/ops/pipeline?schedule=${encodeURIComponent(scheduleName)}&tab=schedules`,
      );
    }, SCHEDULE_NAME);
    await expect(page.getByRole("tab", { name: "스케줄" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(
      page.getByTestId(`pipeline-schedule-row-${SCHEDULE_NAME}`),
    ).toHaveClass(/ring-2/);
  });

  test("history filter 변경은 이전 cursor와 신규 배지 baseline을 폐기한다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      nextCursor: "cursor-page-2",
    });
    await page.goto("/ops/pipeline");
    await page
      .getByRole("button", { name: "실행 타임라인 다음 페이지" })
      .click();
    await expect(page.getByText(/page 2/)).toBeVisible();
    await expect
      .poll(() =>
        counters.executionQueries.some(
          (query) => query.get("cursor") === "cursor-page-2",
        ),
      )
      .toBe(true);

    const beforeFilterChange = counters.executionQueries.length;
    await page.evaluate(() => {
      window.history.pushState(null, "", "/ops/pipeline?status=failed");
    });
    await expect(page.getByText(/page 1/)).toBeVisible();
    await expect
      .poll(() => {
        return counters.executionQueries
          .slice(beforeFilterChange)
          .some(
            (query) =>
              query.get("status") === "failed" && !query.has("cursor"),
          );
      })
      .toBe(true);
    await expect(
      page.getByRole("button", { name: /새 실행 .*건 반영/ }),
    ).toHaveCount(0);

    await page.goBack();
    await expect(page.getByText(/page 1/)).toBeVisible();
    await expect(page.getByLabel("실행 상태")).toHaveValue("all");
    expect(
      counters.executionQueries.some(
        (query) => !query.has("status") && !query.has("cursor"),
      ),
    ).toBe(true);
  });

  test("상세 원 행이 필터로 사라지면 닫기 focus를 첫 표시 행으로 복귀", async ({
    page,
  }) => {
    await installPipelineMocks(page, {
      executionsForQuery: (query) =>
        query.get("status") === "failed" ? [makeRoots()[1]!] : makeRoots(),
    });
    await page.goto("/ops/pipeline");
    await page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`).click();
    await page.getByLabel("실행 상태").selectOption("failed");
    await expect(
      page.getByTestId(`pipeline-execution-row-${REQUEST_ID}`),
    ).toHaveCount(0);

    await page.getByRole("button", { name: "실행 상세 닫기" }).click();

    await expect(
      page.getByTestId(`pipeline-execution-row-${SOLO_JOB_ID}`),
    ).toBeFocused();
  });

  test("스케줄 조작 시작은 tab/schedule URL을 기록", async ({ page }) => {
    await installPipelineMocks(page);
    await page.goto("/ops/pipeline?tab=schedules");

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` })
      .click();
    await expect(page).toHaveURL(/tab=schedules/);
    await expect(page).toHaveURL(
      new RegExp(`schedule=${encodeURIComponent(SCHEDULE_NAME)}`),
    );
  });

  test("스케줄 can_run_now=false는 즉시 실행 사유와 함께 비활성화", async ({
    page,
  }) => {
    const schedules = makeSchedules();
    const firstSchedule = schedules.data.schedules[0];
    if (!firstSchedule) {
      throw new Error("schedule fixture가 필요합니다.");
    }
    schedules.data.schedules[0] = {
      ...firstSchedule,
      pipeline_name: null,
      can_run_now: false,
      disabled_reason: "schedule job 이름이 없습니다.",
    };
    await installPipelineMocks(page, { schedulesResponse: schedules });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await expect(
      page.getByText("즉시 실행 불가: schedule job 이름이 없습니다."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` }),
    ).toBeDisabled();
  });

  test("스케줄 cron 수정(PATCH)과 기본값 복귀(null) + 지연 반영 안내", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` })
      .click();
    const editDialog = page.getByRole("dialog", { name: "스케줄 cron 수정" });
    await editDialog
      .getByRole("textbox", { name: "cron", exact: true })
      .fill("15 5 * * *");
    await editDialog.getByLabel("수정 사유").fill("e2e cron edit");
    await editDialog.getByRole("button", { name: "저장", exact: true }).click();

    const result = page.getByTestId("schedule-command-result");
    await expect(result).toBeVisible();
    await expect(result).toContainText("cron 수정");
    await expect(result).toContainText("코드 위치 새로고침 요청됨");
    expect(counters.patchBodies.at(0)).toMatchObject({
      cron_schedule: "15 5 * * *",
      reason: "e2e cron edit",
    });
    expect(counters.patchBodies.at(0)).not.toHaveProperty("operator");
    expect(counters.scheduleKeys.at(0)).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );

    // 기본값 복귀 = PATCH {cron_schedule: null}.
    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` })
      .click();
    await page.getByRole("button", { name: "기본값으로 되돌리기" }).click();
    await expect(result).toContainText("기본값 복귀(override 삭제)");
    expect(counters.patchBodies.at(1)).toMatchObject({ cron_schedule: null });
  });

  test("스케줄 명령 502 problem은 호출 실패 alert로 표시", async ({ page }) => {
    const counters = await installPipelineMocks(page, {
      scheduleCommandStatus: "error",
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page.getByLabel("명령 사유 (선택)").fill("e2e manual run");

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    await expect(page.getByText("스케줄 명령 호출 실패")).toBeVisible();
    await expect(
      page.getByText("Dagster mutation failed").first(),
    ).toBeVisible();
    await expect(page.getByTestId("schedule-command-result")).toBeVisible();
    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "실패(error)",
    );
    expect(counters.commandBodies.at(0)).toMatchObject({
      command: "run",
      reason: "e2e manual run",
    });
    expect(counters.commandBodies.at(0)).not.toHaveProperty("operator");
    expect(counters.scheduleKeys.at(0)).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    await expect(page.getByTestId("schedule-claim-recovery")).toHaveCount(0);
  });

  test("확정된 502 실패 뒤 동일 명령은 새 idempotency key로 재시도", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleActionStatuses: ["error", "ok"],
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);
    await page.getByLabel("명령 사유 (선택)").fill("확정 실패 재시도");

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await page
        .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
        .click();
      await page
        .getByRole("button", { name: "즉시 실행", exact: true })
        .click();
      if (attempt === 0) {
        await expect(page.getByText("스케줄 명령 호출 실패")).toBeVisible();
        await expect(page.getByTestId("schedule-claim-recovery")).toHaveCount(
          0,
        );
      }
    }

    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "즉시 실행 · 성공",
    );
    expect(counters.commandBodies).toHaveLength(2);
    expect(counters.commandBodies[1]).toEqual(counters.commandBodies[0]);
    expect(counters.scheduleKeys[1]).not.toBe(counters.scheduleKeys[0]);
  });

  test("스케줄 409 active command ID를 claim recovery 조작으로 연결", async ({
    page,
  }) => {
    await installPipelineMocks(page, { scheduleActionConflict: true });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` })
      .click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    await expect(recovery).toContainText(SCHEDULE_NAME);
  });

  test("스케줄 응답 유실 재시도는 같은 key의 active claim을 해제한다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleActionResponseLossOnce: true,
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await page
        .getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` })
        .click();
      if (attempt === 0) {
        await expect(page.getByText("스케줄 명령 호출 실패")).toBeVisible();
      }
    }

    expect(counters.scheduleKeys).toHaveLength(2);
    expect(counters.scheduleKeys[1]).toBe(counters.scheduleKeys[0]);
    const recovery = page.getByTestId("schedule-claim-recovery");
    await expect(recovery).toContainText(counters.scheduleKeys[0]);
    await recovery
      .getByLabel("확인 근거·해제 사유 (필수)")
      .fill("응답 유실 뒤 Dagster에서 미반영 확인");
    await recovery.getByRole("button", { name: "claim 해제" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "확인 결과 기록 후 해제" })
      .click();

    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toContainText("Dagster 미반영 확인");
    expect(counters.claimResolutionRows).toHaveLength(1);
    expect(counters.claimResolutionRows[0]).toMatchObject({
      scheduleName: SCHEDULE_NAME,
      commandId: counters.scheduleKeys[0],
    });
  });

  test("스케줄 409에 active command ID가 없으면 recovery를 노출하지 않는다", async ({
    page,
  }) => {
    await installPipelineMocks(page, {
      scheduleActionConflict: true,
      scheduleActionConflictActiveCommandId: null,
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` })
      .click();

    await expect(page.getByTestId("schedule-claim-recovery")).toHaveCount(0);
  });

  test("결과 불명 500의 active command ID를 recovery로 연결", async ({
    page,
  }) => {
    await installPipelineMocks(page, { scheduleUncertainOutcome: true });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` })
      .click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
  });

  test("명령 502 후 다른 cron 수정 성공은 이전 오류 상태를 제거", async ({
    page,
  }) => {
    await installPipelineMocks(page, { scheduleActionStatus: "error" });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();
    await expect(page.getByText("스케줄 명령 호출 실패")).toBeVisible();

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` })
      .click();
    const dialog = page.getByRole("dialog", { name: "스케줄 cron 수정" });
    await dialog
      .getByRole("textbox", { name: "cron", exact: true })
      .fill("10 4 * * *");
    await dialog.getByRole("button", { name: "저장", exact: true }).click();

    const result = page.getByTestId("schedule-command-result");
    await expect(result).toContainText("cron 수정 · 성공");
    await expect(page.getByText("스케줄 명령 호출 실패")).toHaveCount(0);
    await expect(result).not.toContainText("실패(error)");
  });

  test("스케줄 명령 진행 중에는 cron과 다른 명령도 함께 차단", async ({
    page,
  }) => {
    await installPipelineMocks(page, { scheduleResponseDelayMs: 600 });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    await expect(
      page.getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` }),
    ).toBeDisabled();
    await expect(page.getByTestId("schedule-command-result")).toBeVisible();
  });

  test("같은 render의 terminal schedule 명령 double click은 첫 결과를 보존", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
      scheduleResponseDelayMs: 400,
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 스케줄 중지` })
      .evaluate((button) => {
        button.click();
        button.click();
      });

    await expect.poll(() => counters.commandBodies.length).toBe(1);
    const recovery = page.getByTestId("schedule-claim-recovery");
    await expect(recovery).toContainText(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    await expectScheduleControlsDisabled(page);
    expect(counters.scheduleKeys).toHaveLength(1);
  });

  test("스케줄 명령의 terminal 감사 성공은 사유를 비운다", async ({ page }) => {
    await installPipelineMocks(page);
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);
    const reason = page.getByLabel("명령 사유 (선택)");
    await reason.fill("성공 후 삭제될 사유");

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "감사 명령 ID",
    );
    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    await expect(reason).toHaveValue("");
  });

  test("cron terminal audit 실패 후 patch UI와 다른 명령을 잠근다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);
    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} cron 수정` })
      .click();
    const dialog = page.getByRole("dialog", { name: "스케줄 cron 수정" });
    const reason = dialog.getByLabel("수정 사유");
    await dialog
      .getByRole("textbox", { name: "cron", exact: true })
      .fill("15 5 * * *");
    await reason.fill("감사 결과 확인 필요");
    await dialog.getByRole("button", { name: "저장", exact: true }).click();

    await expect(dialog).toBeVisible();
    await expect(reason).toHaveValue("감사 결과 확인 필요");
    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    await expect(
      dialog.getByRole("textbox", { name: "cron", exact: true }),
    ).toBeDisabled();
    await expect(reason).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "기본값으로 되돌리기" }),
    ).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "저장", exact: true }),
    ).toBeDisabled();
    expect(counters.scheduleKeys).toHaveLength(1);
    expect(counters.patchBodies).toHaveLength(1);
  });

  test("terminal audit 실패 claim이 남으면 모든 schedule 조작을 잠근다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);
    const reason = page.getByLabel("명령 사유 (선택)");
    await reason.fill("감사 결과 확인 필요");

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();
    await expect(page.getByTestId("schedule-command-result")).toContainText(
      "terminal 감사 기록에 실패",
    );
    await expect(reason).toHaveValue("감사 결과 확인 필요");
    await expectScheduleControlsDisabled(page);
    expect(counters.scheduleKeys).toHaveLength(1);
    expect(counters.commandBodies).toHaveLength(1);
  });

  test("결과 불명 schedule claim을 실제 상태 확인 근거와 함께 해제", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    await expect(recovery).toBeVisible();
    await expect(recovery).toContainText(
      "Dagster 실행 목록과 스케줄 상태를 직접 확인",
    );
    await expect(
      recovery.getByRole("button", { name: "claim 해제" }),
    ).toBeDisabled();
    await recovery
      .getByLabel("schedule claim 실제 반영 확인 결과")
      .selectOption("confirmed_not_applied");
    await recovery
      .getByLabel("확인 근거·해제 사유 (필수)")
      .fill("Dagster run 목록에 해당 실행이 없음을 확인");
    await recovery.getByRole("button", { name: "claim 해제" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "확인 결과 기록 후 해제" })
      .click();

    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toContainText("Dagster 미반영 확인");
    expect(counters.claimResolutionBodies).toEqual([
      {
        resolution: "confirmed_not_applied",
        reason: "Dagster run 목록에 해당 실행이 없음을 확인",
      },
    ]);
    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "즉시 실행", exact: true })
      .click();
    await expect.poll(() => counters.scheduleKeys.length).toBe(2);
    expect(counters.scheduleKeys[1]).not.toBe(counters.scheduleKeys[0]);
    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toHaveCount(0);
  });

  test("claim 해제 응답 유실은 같은 body로 안전하게 replay", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
      claimResolutionResponseLossOnce: true,
      claimResolutionResponseDelayMs: 400,
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    await recovery
      .getByLabel("확인 근거·해제 사유 (필수)")
      .fill("Dagster run 목록에서 미반영 확인");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await recovery.getByRole("button", { name: "claim 해제" }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "확인 결과 기록 후 해제" })
        .click();
      if (attempt === 0) {
        await expect.poll(() => counters.claimResolutionBodies.length).toBe(1);
        await expect(
          recovery.getByLabel("schedule claim 실제 반영 확인 결과"),
        ).toBeDisabled();
        await expect(
          recovery.getByLabel("확인 근거·해제 사유 (필수)"),
        ).toBeDisabled();
        await expect(page.getByText("claim 해제 실패")).toBeVisible();
        await expectScheduleControlsDisabled(page);
      }
    }

    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toContainText("Dagster 미반영 확인");
    expect(counters.claimResolutionBodies).toHaveLength(2);
    expect(counters.claimResolutionBodies[1]).toEqual(
      counters.claimResolutionBodies[0],
    );
    expect(counters.claimResolutionPaths[1]).toBe(
      counters.claimResolutionPaths[0],
    );
    expect(counters.claimResolutionRows).toHaveLength(1);
    expect(counters.claimResolutionRows[0]).toMatchObject({
      scheduleName: SCHEDULE_NAME,
      commandId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      body: counters.claimResolutionBodies[0],
    });
  });

  test("claim 해제 503은 frozen body와 schedule 잠금을 유지해 replay한다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
      claimResolutionErrorOnce: {
        status: 503,
        body: {
          type: "https://kor-travel-map/errors/service-unavailable",
          title: "Service Unavailable",
          status: 503,
          detail: "해제 결과를 확정할 수 없습니다.",
          code: "SERVICE_UNAVAILABLE",
          request_id: "e2e",
        },
      },
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    await recovery
      .getByLabel("확인 근거·해제 사유 (필수)")
      .fill("Dagster 실행 미반영을 확인함");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await recovery.getByRole("button", { name: "claim 해제" }).click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "확인 결과 기록 후 해제" })
        .click();
      if (attempt === 0) {
        await expect(page.getByText("claim 해제 실패")).toBeVisible();
        await expect(
          recovery.getByLabel("schedule claim 실제 반영 확인 결과"),
        ).toBeDisabled();
        await expect(
          recovery.getByLabel("확인 근거·해제 사유 (필수)"),
        ).toBeDisabled();
        await expectScheduleControlsDisabled(page);
      }
    }

    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toContainText("Dagster 미반영 확인");
    expect(counters.claimResolutionBodies).toHaveLength(2);
    expect(counters.claimResolutionBodies[1]).toEqual(
      counters.claimResolutionBodies[0],
    );
  });

  test("claim 해제 422는 frozen body를 해제해 사유를 수정할 수 있다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      scheduleAuditStatus: "terminal_record_failed",
      claimResolutionErrorOnce: {
        status: 422,
        body: {
          type: "https://kor-travel-map/errors/validation-error",
          title: "Validation Error",
          status: 422,
          detail: "확인 사유를 수정하세요.",
          code: "VALIDATION_ERROR",
          request_id: "e2e",
          errors: [],
        },
      },
    });
    await page.goto(`/ops/pipeline?schedule=${SCHEDULE_NAME}`);

    await page
      .getByRole("button", { name: `${SCHEDULE_NAME} 즉시 실행` })
      .click();
    await page.getByRole("button", { name: "즉시 실행", exact: true }).click();

    const recovery = page.getByTestId("schedule-claim-recovery");
    const reason = recovery.getByLabel("확인 근거·해제 사유 (필수)");
    await reason.fill("수정 전 사유");
    await recovery.getByRole("button", { name: "claim 해제" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "확인 결과 기록 후 해제" })
      .click();

    await expect(page.getByText("claim 해제 실패")).toBeVisible();
    await expect(reason).toBeEnabled();
    await expect(
      recovery.getByLabel("schedule claim 실제 반영 확인 결과"),
    ).toBeEnabled();
    await expectScheduleControlsDisabled(page);
    await reason.fill("수정한 확인 사유");
    await recovery.getByRole("button", { name: "claim 해제" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "확인 결과 기록 후 해제" })
      .click();

    await expect(
      page.getByTestId("schedule-claim-resolution-result"),
    ).toBeVisible();
    expect(counters.claimResolutionBodies).toEqual([
      { resolution: "confirmed_not_applied", reason: "수정 전 사유" },
      { resolution: "confirmed_not_applied", reason: "수정한 확인 사유" },
    ]);
  });

  test("요청 dialog — scope 전환·MOIS 경고·별도 preview", async ({ page }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");

    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await expect(dialog).toBeVisible();

    // 기본 scope는 provider_dataset. bbox로 전환하면 좌표 4필드가 나온다.
    await dialog.getByLabel("scope 유형").selectOption("bbox");
    await expect(dialog.getByLabel("min_lon")).toBeVisible();
    await dialog.getByLabel("scope 유형").selectOption("provider_dataset");

    // MOIS 조건부 경고 — provider 입력이 mois 계열일 때만.
    await expect(dialog.getByTestId("mois-precheck-notice")).toHaveCount(0);
    await dialog.getByLabel("provider").first().fill("python-mois-api");
    const moisNotice = dialog.getByTestId("mois-precheck-notice");
    await expect(moisNotice).toBeVisible();
    await expect(moisNotice).toContainText("mois_localdata_source_sync");
    await expect(moisNotice).toContainText("정상");

    // preview 제출 → 매칭 대상 표시, 행 생성 없음.
    await dialog.getByLabel("dataset_key").fill("mois_licenses");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    const resultAlert = dialog.getByTestId("request-preview-result");
    await expect(resultAlert).toBeVisible();
    await expect(resultAlert).toContainText("미리보기 결과");
    await expect(resultAlert).toContainText('"feature_count":12');
    expect(counters.previewBodies.at(0)).toMatchObject({
      scope: { type: "provider_dataset", provider: "python-mois-api" },
    });
    expect(counters.requestBodies).toHaveLength(0);
    expect(counters.legacyProviderCalls).toBe(0);
  });

  test("요청 dialog — 입력 변경 즉시 이전 dry-run 결과를 무효화", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    await expect(dialog.getByTestId("request-preview-result")).toBeVisible();

    await dialog.getByLabel("dataset_key").fill("opinet_stations");

    await expect(dialog.getByTestId("request-preview-result")).toHaveCount(0);
    expect(counters.previewBodies).toHaveLength(1);
  });

  test("요청 dialog — 닫고 다시 열면 preview·생성 결과가 남지 않는다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    await expect(dialog.getByTestId("request-preview-result")).toBeVisible();

    await dialog.getByRole("button", { name: "닫기" }).click();
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    await expect(dialog.getByTestId("request-preview-result")).toHaveCount(0);
    expect(counters.previewBodies).toHaveLength(1);

    await dialog
      .getByLabel("dry-run(행을 만들지 않고 대상 수만 확인)")
      .uncheck();
    await dialog
      .getByRole("button", { name: "요청 생성", exact: true })
      .click();
    await expect(dialog.getByTestId("request-create-result")).toBeVisible();
    await dialog.getByRole("button", { name: "닫기" }).click();
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();

    await expect(dialog.getByTestId("request-create-result")).toHaveCount(0);
    await expect(dialog.getByTestId("request-preview-result")).toHaveCount(0);
    expect(counters.requestBodies).toHaveLength(1);
  });

  test("요청 dialog — 이전 pending 응답이 재오픈 후 새 결과를 덮지 않는다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      previewResponseDelaysMs: [700, 0],
      previewFeatureCounts: [11, 22],
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    await expect.poll(() => counters.previewBodies.length).toBe(1);

    await dialog.getByRole("button", { name: "닫기" }).click();
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    const result = dialog.getByTestId("request-preview-result");
    await expect(result).toContainText('"feature_count":22');

    await page.waitForTimeout(800);
    await expect(result).toContainText('"feature_count":22');
    await expect(result).not.toContainText('"feature_count":11');
    expect(counters.previewBodies).toHaveLength(2);
  });

  test("요청 dialog — non-provider create pending 중 닫기와 중복 POST를 차단", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      requestCreateDelayMs: 700,
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("scope 유형").selectOption("bbox");
    await dialog.getByLabel("데이터셋 키 필터").fill("kma_short_forecast");
    await dialog
      .getByLabel("dry-run(행을 만들지 않고 대상 수만 확인)")
      .uncheck();
    await dialog
      .getByRole("button", { name: "요청 생성", exact: true })
      .click();
    await expect.poll(() => counters.requestBodies.length).toBe(1);

    const closeButton = dialog.getByRole("button", { name: "닫기" });
    await expect(closeButton).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "요청 생성", exact: true }),
    ).toBeDisabled();
    await expect(dialog.getByLabel("scope 유형")).toBeDisabled();
    await expect(dialog.getByLabel("데이터셋 키 필터")).toBeDisabled();
    await expect(
      dialog.getByLabel("dry-run(행을 만들지 않고 대상 수만 확인)"),
    ).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await page.mouse.click(4, 4);
    await expect(dialog).toBeVisible();

    await expect(dialog.getByTestId("request-create-result")).toBeVisible();
    await expect(dialog.getByLabel("데이터셋 키 필터")).toHaveValue(
      "kma_short_forecast",
    );
    await expect(closeButton).toBeEnabled();
    await closeButton.click();
    await expect(dialog).toBeHidden();
    expect(counters.requestBodies).toHaveLength(1);
  });

  test("요청 dialog — 응답 유실 재시도는 같은 key로 한 request만 생성", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      requestCreateResponseLossOnce: true,
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("scope 유형").selectOption("bbox");
    await dialog.getByLabel("데이터셋 키 필터").fill("kma_short_forecast");
    await dialog
      .getByLabel("dry-run(행을 만들지 않고 대상 수만 확인)")
      .uncheck();
    const submit = dialog.getByRole("button", {
      name: "요청 생성",
      exact: true,
    });
    await submit.click();
    await expect(page.getByText("요청 생성 실패")).toBeVisible();
    await submit.click();

    await expect(dialog.getByTestId("request-create-result")).toContainText(
      "동일 요청 결과 재생",
    );
    expect(counters.requestBodies).toHaveLength(2);
    expect(counters.requestBodies[1]).toEqual(counters.requestBodies[0]);
    expect(counters.requestKeys).toHaveLength(2);
    expect(counters.requestKeys[1]).toBe(counters.requestKeys[0]);
    expect(counters.requestRows).toEqual([
      {
        idempotencyKey: counters.requestKeys[0],
        body: counters.requestBodies[0],
        requestId: REQUEST_ID,
      },
    ]);
  });

  test("요청 dialog — priority 소수는 전송 없이 명시적으로 거부", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByLabel("priority").fill("12.5");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();

    await expect(dialog.getByText("priority는 0~1000 사이 정수")).toBeVisible();
    expect(counters.previewBodies).toHaveLength(0);
    expect(counters.requestBodies).toHaveLength(0);
  });

  test("요청 dialog — 빈 priority는 0으로 강제 변환하지 않고 거부", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page);
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByLabel("priority").fill("");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();

    await expect(
      dialog.getByText("priority는 비울 수 없습니다."),
    ).toBeVisible();
    expect(counters.previewBodies).toHaveLength(0);
    expect(counters.requestBodies).toHaveLength(0);
  });

  test("요청 dialog — canonical catalog 장애는 fail-closed", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      catalogResponse: {
        status: 503,
        body: {
          type: "https://kor-travel-map/errors/catalog-unavailable",
          title: "catalog unavailable",
          status: 503,
          detail: "catalog unavailable",
          code: "CATALOG_UNAVAILABLE",
          request_id: "e2e",
          errors: [],
        },
      },
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });

    await expect(dialog.getByText("canonical catalog 조회 실패")).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "dry-run 실행" }),
    ).toBeDisabled();
    expect(counters.previewBodies).toHaveLength(0);
    expect(counters.legacyProviderCalls).toBe(0);
  });

  test("요청 dialog — 열린 후 catalog 장애도 제출 직전 재확인으로 차단", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      catalogResponses: [
        { status: 200, body: makeCatalogResponse() },
        {
          status: 503,
          body: {
            type: "https://kor-travel-map/errors/catalog-unavailable",
            title: "catalog unavailable",
            status: 503,
            detail: "catalog unavailable",
            code: "CATALOG_UNAVAILABLE",
            request_id: "e2e",
            errors: [],
          },
        },
      ],
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();

    await expect(
      dialog.getByText("provider/dataset 카탈로그 최신 상태를 확인할 수 없어"),
    ).toBeVisible();
    expect(counters.catalogCalls).toBeGreaterThanOrEqual(2);
    expect(counters.previewBodies).toHaveLength(0);
  });

  test("요청 dialog — 제출 직전 catalog에서 사라진 exact pair를 차단", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      catalogResponses: [
        { status: 200, body: makeCatalogResponse() },
        {
          status: 200,
          body: makeCatalogResponse([
            makeCatalogRow("python-mois-api", "mois_licenses", "default"),
          ]),
        },
      ],
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();

    await expect(
      dialog.getByText(
        "현재 canonical catalog에 없는 provider/dataset 조합입니다.",
      ),
    ).toBeVisible();
    expect(counters.previewBodies).toHaveLength(0);
  });

  test("요청 dialog — 초기 MOIS precheck 성공 후 제출 직전 장애를 차단", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      moisPrecheckResponses: [
        { status: 200, body: makeMoisPrecheckResponse() },
        {
          status: 503,
          body: {
            type: "https://kor-travel-map/errors/dagster-unavailable",
            title: "Dagster unavailable",
            status: 503,
            detail: "Dagster unavailable",
            code: "DAGSTER_UNAVAILABLE",
            request_id: "e2e",
            errors: [],
          },
        },
      ],
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-mois-api");
    await dialog.getByLabel("dataset_key").fill("mois_licenses");
    await expect(dialog.getByTestId("mois-precheck-notice")).toContainText(
      "정상",
    );
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();

    await expect(
      dialog.getByText("MOIS 선행 source sync 최신 상태를 조회할 수 없어"),
    ).toBeVisible();
    expect(counters.moisPrecheckCalls).toBeGreaterThanOrEqual(2);
    expect(counters.previewBodies).toHaveLength(0);
  });

  test("요청 dialog — dataset-only MOIS와 Dagster precheck 장애를 fail-closed", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      moisPrecheckResponse: {
        status: 503,
        body: {
          type: "https://kor-travel-map/errors/dagster-unavailable",
          title: "Dagster unavailable",
          status: 503,
          detail: "Dagster unavailable",
          code: "DAGSTER_UNAVAILABLE",
          request_id: "e2e",
          errors: [],
        },
      },
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("scope 유형").selectOption("center_radius");
    await dialog.getByLabel("데이터셋 키 필터").fill("mois_licenses");

    const notice = dialog.getByTestId("mois-precheck-notice");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("Dagster run 조회 실패");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    await expect(
      dialog.getByText("MOIS 선행 source sync 최신 상태를 조회할 수 없어"),
    ).toBeVisible();
    expect(counters.previewBodies).toHaveLength(0);
  });

  test("요청 dialog — MOIS 최근 run이 TTL을 넘으면 차단", async ({ page }) => {
    const stalePrecheck: PipelineJobPrecheckResponse = {
      data: {
        job_name: "mois_localdata_source_sync",
        ready: false,
        checked_at: "2026-07-17T09:00:00.000Z",
        max_age_hours: 24,
        age_hours: 48,
        latest_run: {
          run_id: "mois-source-run-stale",
          job_name: "mois_localdata_source_sync",
          status: "SUCCESS",
          start_time: Date.parse("2026-07-15T08:55:00.000Z") / 1000,
          end_time: Date.parse("2026-07-15T09:00:00.000Z") / 1000,
          update_time: Date.parse("2026-07-15T09:00:00.000Z") / 1000,
          tags: {},
        },
        disabled_reason:
          "MOIS source sync 최신 성공이 TTL(24시간)을 넘었습니다.",
      },
      meta: META,
    };
    await installPipelineMocks(page, {
      moisPrecheckResponse: { status: 200, body: stalePrecheck },
    });
    await page.goto("/ops/pipeline");
    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-mois-api");
    await dialog.getByLabel("dataset_key").fill("mois_licenses");

    const notice = dialog.getByTestId("mois-precheck-notice");
    await expect(notice).toContainText("TTL(24시간)을 넘었습니다");
    await dialog.getByRole("button", { name: "dry-run 실행" }).click();
    await expect(
      dialog.getByText(
        "MOIS source sync 최신 성공이 TTL(24시간)을 넘었습니다.",
      ),
    ).toBeVisible();
  });

  test("요청 생성 409는 Retry-After 안내로 표시", async ({ page }) => {
    await installPipelineMocks(page, {
      requestCreate: { status: 409, headers: { "Retry-After": "15" } },
    });
    await page.goto("/ops/pipeline");

    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByLabel("실행 모드").selectOption("now");
    await dialog.getByRole("checkbox").first().uncheck();
    await dialog.getByRole("button", { name: "요청 생성" }).click();

    await expect(dialog.getByText("요청 생성 실패")).toBeVisible();
    await expect(
      dialog.getByText("약 15초 후 다시 시도하세요", { exact: false }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "기존 활성 요청 열기" }),
    ).toBeVisible();
  });

  test("동일 활성 계획 200 재사용을 새 요청과 구분하고 canonical id를 연다", async ({
    page,
  }) => {
    const counters = await installPipelineMocks(page, {
      reusedActiveRequest: true,
    });
    await page.goto("/ops/pipeline");

    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-kma-api");
    await dialog.getByLabel("dataset_key").fill("kma_short_forecast");
    await dialog.getByRole("checkbox").uncheck();
    await dialog.getByRole("button", { name: "요청 생성" }).click();

    await expect(dialog.getByText("기존 활성 요청 재사용")).toBeVisible();
    expect(counters.requestBodies.at(0)).toMatchObject({
      scope: {
        dataset_key: "kma_short_forecast",
        provider: "python-kma-api",
        type: "provider_dataset",
      },
    });
    expect(counters.requestBodies.at(0)).not.toHaveProperty("dry_run");
    expect(counters.requestBodies.at(0)).not.toHaveProperty("operator");
  });
});
