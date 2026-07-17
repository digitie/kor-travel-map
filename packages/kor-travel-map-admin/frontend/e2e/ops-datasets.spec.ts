import { expect, type Page, type Route, test } from "@playwright/test";

import type { DatasetRefreshExecutionDetailResponse } from "../src/api/datasets";
import type { components } from "../src/api/types";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다 — 백엔드
// DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패해 drift를 감지한다.
// (pipeline 실행 상세는 `src/api/datasets.ts` re-export를 통해 #677의
// `PipelineExecutionDetailResponse` 생성 타입에 바인딩된다.)
type Meta = components["schemas"]["Meta"];
type OpsDatasetCatalogInfo = components["schemas"]["OpsDatasetCatalogInfo"];
type OpsDatasetDetailData = components["schemas"]["OpsDatasetDetailData"];
type OpsDatasetDetailResponse = components["schemas"]["OpsDatasetDetailResponse"];
type OpsDatasetGridRow = components["schemas"]["OpsDatasetGridRow"];
type OpsDatasetPreviewResponse = components["schemas"]["OpsDatasetPreviewResponse"];
type OpsDatasetRefreshPolicyResponse =
  components["schemas"]["OpsDatasetRefreshPolicyResponse"];
type OpsDatasetLatestExecution =
  components["schemas"]["OpsDatasetLatestExecution"];
type OpsDatasetsGridResponse = components["schemas"]["OpsDatasetsGridResponse"];
type FeatureUpdateRequestCreateRequest =
  components["schemas"]["FeatureUpdateRequestCreateRequest"];
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestCreatedRecord =
  components["schemas"]["FeatureUpdateRequestCreatedRecord"];
type FeatureUpdateRequestRecord = components["schemas"]["FeatureUpdateRequestRecord"];
type ProviderRefreshPolicyRecord =
  components["schemas"]["ProviderRefreshPolicyRecord"];
type ProviderRefreshPolicyUpsertRequest =
  components["schemas"]["ProviderRefreshPolicyUpsertRequest"];

const MOCK_OLD = "2026-06-01T00:00:00.000Z";
const KMA_PROVIDER = "python-kma-api";
const KMA_DATASET = "kma_short_forecast";
const KMA_SCOPE = "target_grids";
const ACTIVE_EXTERNAL_SCOPE = "external_system:concierge";
const STALE_EXTERNAL_SCOPE = "external_system:retired";
// URL query가 선택 정본이라(#684 C4R) drawer를 여는 테스트는 딥링크로 진입한다
// (자동 row0 선택 fallback 제거 — 비선택 진입은 빈 상태).
const KMA_DEEP_LINK =
  `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
  `&sync_scope=${KMA_SCOPE}`;
const MOIS_PROVIDER = "python-mois-api";
const MOIS_DATASET = "mois_license_features_bulk";
const KREX_PROVIDER = "python-krex-api";
const KREX_DATASET = "krex_rest_areas";
const REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const NEW_REQUEST_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// 신선도는 서버 계산 `freshness.state` 정본을 쓴다(브라우저 48h 계산 제거,
// T-ADM-C4R). FRESH_AT은 last_success_at 표시용 최근 시각일 뿐 판정에 안 쓰인다.
const FRESH_AT = new Date().toISOString();

function makeMeta(requestId: string): Meta {
  return { duration_ms: 1, request_id: requestId };
}

type OpsDatasetFreshness = components["schemas"]["OpsDatasetFreshness"];
type OpsIssueSummary = components["schemas"]["OpsIssueSummary"];
type OpsDatasetScheduleSummary =
  components["schemas"]["OpsDatasetScheduleSummary"];

function makeFreshness(
  overrides: Partial<OpsDatasetFreshness> = {},
): OpsDatasetFreshness {
  return {
    state: "fresh",
    basis: "policy_stale_after",
    due_at: "2026-07-16T00:00:00.000Z",
    is_overdue: false,
    overdue_by_seconds: 0,
    sla_seconds: 172_800,
    ...overrides,
  };
}

function makeIssueSummary(
  overrides: Partial<OpsIssueSummary> = {},
): OpsIssueSummary {
  return { open_count: 0, severity_counts: {}, ...overrides };
}

function makeScheduleSummary(
  overrides: Partial<OpsDatasetScheduleSummary> = {},
): OpsDatasetScheduleSummary {
  return {
    source: "dagster_graphql",
    basis: "dagster_definition_tags",
    schedule_names: ["feature_weather_kma_short_forecast_hourly_schedule"],
    active_schedule_names: ["feature_weather_kma_short_forecast_hourly_schedule"],
    next_scheduled_at: "2026-07-15T01:20:00.000Z",
    status: "RUNNING",
    ...overrides,
  };
}

function makeCatalog(
  overrides: Partial<OpsDatasetCatalogInfo> = {},
): OpsDatasetCatalogInfo {
  return {
    feature_kind: "weather",
    provider_state_default_scope: "target_grids",
    label: "KMA 단기예보",
    is_feature_load: false,
    is_refreshable: true,
    scope_refresh: {
      allowed_sync_scopes: ["target_grids", ACTIVE_EXTERNAL_SCOPE],
      default_sync_scope: "target_grids",
      effect: "sync_scope",
      reason: null,
      selector: "poi_cache_targets",
      supported: true,
    },
    preview: {
      supported: true,
      input_kind: "none",
      sources: ["fixture"],
      default_max_items: 20,
      max_items_limit: 100,
      external_call_budget: 0,
      timeout_seconds: 5,
    },
    ...overrides,
  };
}

function makeGridRow(overrides: Partial<OpsDatasetGridRow> = {}): OpsDatasetGridRow {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    sync_scope: KMA_SCOPE,
    status: "active",
    last_success_at: FRESH_AT,
    last_failure_at: null,
    eligible_after: null,
    consecutive_failures: 0,
    catalog: makeCatalog(),
    catalog_state: "canonical",
    orphan_reason: null,
    mutable: true,
    refresh_policy: null,
    freshness: makeFreshness(),
    schedule: makeScheduleSummary(),
    dataset_issues: makeIssueSummary(),
    provider_issues: makeIssueSummary(),
    latest_execution: null,
    detail_url:
      `/v1/ops/datasets/detail?provider=${KMA_PROVIDER}` +
      `&dataset_key=${KMA_DATASET}&sync_scope=${encodeURIComponent(KMA_SCOPE)}`,
    ...overrides,
  };
}

function makeRefreshPolicy(
  overrides: Partial<ProviderRefreshPolicyRecord> = {},
): ProviderRefreshPolicyRecord {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    source_kind: "openapi",
    targeted_policy: "allow_targeted",
    config_source: "db",
    enabled: true,
    max_concurrent: 1,
    system_interval_seconds: 3600,
    optimal_interval_seconds: null,
    min_interval_seconds: null,
    max_requests_per_minute: 30,
    max_requests_per_hour: null,
    max_requests_per_day: null,
    burst_size: null,
    stale_after_minutes: 2880,
    rate_limit_source: {},
    created_at: MOCK_OLD,
    updated_at: "2026-06-08T00:30:00.000Z",
    ...overrides,
  };
}

function makeLatestExecution(
  overrides: Partial<OpsDatasetLatestExecution> = {},
): OpsDatasetLatestExecution {
  return {
    id: REQUEST_ID,
    kind: "update_request",
    status: "done",
    pair_status: "done",
    operation_member_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    operation_registry_version: "provider_operation_registry.v1",
    providers: [KMA_PROVIDER],
    dataset_keys: [KMA_DATASET],
    provider_datasets: [
      {
        provider: KMA_PROVIDER,
        dataset_key: KMA_DATASET,
        sync_scope: KMA_SCOPE,
        status: "done",
        operation_member_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      },
    ],
    sync_scope: KMA_SCOPE,
    dagster_run_id: null,
    dagster_run_status: null,
    error_message: null,
    created_at: MOCK_OLD,
    started_at: MOCK_OLD,
    finished_at: MOCK_OLD,
    trigger_kind: "manual",
    detail_url: `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
    cancellation: null,
    projected_job: {
      id: JOB_ID,
      job_kind: "feature_update",
      status: "done",
      progress: 100,
      current_stage: "loading",
      created_at: MOCK_OLD,
      started_at: MOCK_OLD,
      finished_at: MOCK_OLD,
      error_message: null,
      dagster_run_id: null,
      dagster_run_status: null,
      trigger_kind: "manual",
      detail_url: `/v1/ops/pipeline/executions/import_job/${JOB_ID}`,
      depth: 1,
      operation_registry_version: "provider_operation_registry.v1",
    },
    ...overrides,
  };
}

function makeDetail(
  overrides: Partial<OpsDatasetDetailData> = {},
): OpsDatasetDetailData {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    catalog: makeCatalog(),
    scopes: [
      {
        sync_scope: KMA_SCOPE,
        status: "active",
        cursor: { base_date: "20260714", base_time: "0500" },
        last_success_at: FRESH_AT,
        last_failure_at: null,
        eligible_after: null,
        freshness: makeFreshness(),
        consecutive_failures: 0,
      },
    ],
    catalog_state: "canonical",
    orphan_reason: null,
    mutable: true,
    refresh_policy: null,
    recent_runs: [],
    recent_runs_coverage: "db_recorded_canonical_operations",
    recent_runs_next_cursor: null,
    recent_events: [],
    schedule: makeScheduleSummary(),
    schedule_source_status: "ok",
    schedule_source_errors: [],
    pipeline_history_url:
      `/v1/ops/pipeline/executions?provider=${KMA_PROVIDER}` +
      `&dataset_key=${KMA_DATASET}&sync_scope=${encodeURIComponent(KMA_SCOPE)}`,
    dataset_issues: makeIssueSummary(),
    provider_issues: makeIssueSummary(),
    ...overrides,
  };
}

function makeGridResponse(
  items: OpsDatasetGridRow[],
  degrade: {
    status?: "ok" | "unavailable" | "error";
    errors?: string[];
  } = {},
): OpsDatasetsGridResponse {
  return {
    data: {
      items,
      latest_execution_coverage: "db_recorded_canonical_operations",
      schedule_source_status: degrade.status ?? "ok",
      schedule_source_errors: degrade.errors ?? [],
    },
    meta: makeMeta("e2e-ops-datasets"),
  };
}

function makeDetailResponse(detail: OpsDatasetDetailData): OpsDatasetDetailResponse {
  return { data: detail, meta: makeMeta("e2e-ops-dataset-detail") };
}

function makeCreatedRequest(
  overrides: Partial<FeatureUpdateRequestCreatedRecord> = {},
): FeatureUpdateRequestCreatedRecord {
  return {
    request_id: NEW_REQUEST_ID,
    scope_type: "provider_dataset",
    scope: {
      type: "provider_dataset",
      provider: KMA_PROVIDER,
      dataset_key: KMA_DATASET,
    },
    providers: [KMA_PROVIDER],
    dataset_keys: [KMA_DATASET],
    update_policy: {},
    run_mode: "now",
    priority: 75,
    status: "queued",
    matched_scope: {},
    job_id: JOB_ID,
    dagster_run_id: null,
    operator: "local-admin",
    reason: "dataset refresh from ops/datasets",
    error_message: null,
    created_at: FRESH_AT,
    started_at: null,
    finished_at: null,
    requested_sync_scope: KMA_SCOPE,
    effective_sync_scope: KMA_SCOPE,
    dispatch_requested_at: FRESH_AT,
    generation: 1,
    status_url:
      `/v1/ops/pipeline/executions/update_request/${NEW_REQUEST_ID}`,
    result_kind: "request",
    ...overrides,
  };
}

function makeRequestRecord(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
  return makeCreatedRequest(overrides);
}

function apiPathname(url: URL): string {
  return url.pathname.replace(/^\/api\/proxy/, "");
}

/**
 * 로그인 게이트(#520) 대응 — live suite의 `E2E_ADMIN_PASSWORD` 관례를 따른다.
 *
 * 미들웨어가 admin 세션 없는 내비게이션을 `/login`으로 돌려보내므로, mock
 * suite도 서버에 UI 인증이 구성돼 있으면(`E2E_ADMIN_PASSWORD` 설정) 각 테스트
 * 시작 시 UI 로그인으로 세션을 만든다. 미설정이면 게이트 없는 서버로 간주한다.
 */
async function loginIfGateEnabled(page: Page) {
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!password) {
    return;
  }
  const username = process.env.E2E_ADMIN_USERNAME ?? "admin";
  await page.goto("/login");
  // 이미 유효 세션이면 미들웨어가 홈으로 되돌린다.
  if (!new URL(page.url()).pathname.startsWith("/login")) {
    return;
  }
  await page.locator("#admin-username").fill(username);
  await page.locator("#admin-password").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

/**
 * dataset API는 모두 고정 route를 사용하고 provider/dataset_key를 query로 받는다.
 * segment 동적 경로를 mock하지 않아 legacy client가 되살아나면 즉시 실패한다.
 */
async function mockOpsDatasets(
  page: Page,
  options: {
    items: OpsDatasetGridRow[] | ((listCount: number) => OpsDatasetGridRow[]);
    details?: Record<
      string,
      OpsDatasetDetailData | ((detailCount: number) => OpsDatasetDetailData)
    >;
    previewStatus?: number;
    scheduleSourceStatus?: "ok" | "unavailable" | "error";
    scheduleSourceErrors?: string[];
  },
) {
  const counts = { list: 0, detail: 0, preview: 0 };
  const policyPuts: { path: string; body: ProviderRefreshPolicyUpsertRequest }[] =
    [];
  const previewPosts: { path: string; source: string | null }[] = [];

  await page.route("**/api/proxy/v1/ops/datasets**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = apiPathname(url);
    if (pathname === "/v1/ops/datasets") {
      counts.list += 1;
      const items =
        typeof options.items === "function"
          ? options.items(counts.list)
          : options.items;
      await fulfillJson(
        route,
        makeGridResponse(items, {
          status: options.scheduleSourceStatus,
          errors: options.scheduleSourceErrors,
        }),
      );
      return;
    }
    if (
      pathname === "/v1/ops/datasets/refresh-policy" &&
      request.method() === "PUT"
    ) {
      const body = request.postDataJSON() as ProviderRefreshPolicyUpsertRequest;
      policyPuts.push({ path: pathname + url.search, body });
      const provider = url.searchParams.get("provider") ?? "";
      const dataset = url.searchParams.get("dataset_key") ?? "";
      const response: OpsDatasetRefreshPolicyResponse = {
        data: makeRefreshPolicy({
          provider,
          dataset_key: dataset,
          targeted_policy: body.targeted_policy ?? "follow_system",
          enabled: body.enabled ?? true,
        }),
        meta: makeMeta("e2e-policy-upsert"),
      };
      await fulfillJson(route, response);
      return;
    }
    if (pathname === "/v1/ops/datasets/preview" && request.method() === "POST") {
      counts.preview += 1;
      const previewBody = (request.postDataJSON() ?? {}) as {
        source?: string;
        max_items?: number;
      };
      previewPosts.push({ path: pathname + url.search, source: previewBody.source ?? null });
      const status = options.previewStatus ?? 200;
      if (status === 403) {
        await fulfillJson(
          route,
          {
            type: "https://kor-travel-map/errors/forbidden",
            title: "live ETL preview가 비활성화되어 있습니다",
            status: 403,
            detail: "live ETL preview가 비활성화되어 있습니다 — opt-in 필요.",
            code: "FORBIDDEN",
            request_id: "e2e-preview-403",
            errors: [],
          },
          403,
        );
        return;
      }
      const response: OpsDatasetPreviewResponse = {
        data: {
          provider: KMA_PROVIDER,
          dataset_key: KMA_DATASET,
          source: "fixture",
          variant: "WeatherValue",
          description: "KMA 단기예보 fixture",
          items: [{ metric_key: "temperature_c", value: 23.5 }],
          returned_items: 1,
          total_items: 1,
          truncated: false,
          budget: {
            external_call_budget: 0,
            max_items: 20,
            timeout_seconds: 5,
          },
        },
        meta: makeMeta("e2e-preview"),
      };
      await fulfillJson(route, response);
      return;
    }
    if (pathname !== "/v1/ops/datasets/detail" || request.method() !== "GET") {
      throw new Error(`Unexpected datasets call: ${request.method()} ${pathname}`);
    }
    counts.detail += 1;
    const provider = url.searchParams.get("provider") ?? "";
    const dataset = url.searchParams.get("dataset_key") ?? "";
    const key = `${provider}/${dataset}`;
    const detailSource = options.details?.[key];
    if (!detailSource) {
      await fulfillJson(
        route,
        {
          type: "https://kor-travel-map/errors/not-found",
          title: "ops dataset 없음",
          status: 404,
          detail: `ops dataset 없음: ${key}`,
          code: "NOT_FOUND",
          request_id: "e2e-dataset-404",
          errors: [],
        },
        404,
      );
      return;
    }
    const detail =
      typeof detailSource === "function"
        ? detailSource(counts.detail)
        : detailSource;
    await fulfillJson(route, makeDetailResponse(detail));
  });

  return { counts, policyPuts, previewPosts };
}

/** `POST /v1/ops/pipeline/requests`(지금 갱신) + 실행 상세 GET(상태 추적) mock. */
async function mockPipelineRequests(
  page: Page,
  options: {
    createStatus?: number;
    conflictCode?: "ACTIVE_SCOPE_CONFLICT" | "LOCK_BUSY";
    reusedActiveRequest?: boolean;
    createResponseLossOnce?: boolean;
    executionStatus?: string | ((executionGetCount: number) => string);
    executionGetStatus?: number;
  } = {},
) {
  const posts: {
    body: FeatureUpdateRequestCreateRequest;
    bodyJson: string;
    idempotencyKey: string;
  }[] = [];
  const requestLedger = new Map<
    string,
    { bodyJson: string; response: FeatureUpdateRequestCreateResponse }
  >();
  const executionGets: string[] = [];

  await page.route("**/api/proxy/v1/ops/pipeline/**", async (route) => {
    const request = route.request();
    const pathname = apiPathname(new URL(request.url()));
    if (pathname === "/v1/ops/pipeline/requests" && request.method() === "POST") {
      const idempotencyKey = request.headers()["idempotency-key"] ?? "";
      if (!UUID_PATTERN.test(idempotencyKey)) {
        throw new Error(
          `pipeline request Idempotency-Key must be UUID: ${idempotencyKey}`,
        );
      }
      const bodyJson = request.postData() ?? "";
      const body = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
      posts.push({ body, bodyJson, idempotencyKey });
      if (options.createStatus === 409) {
        const conflictCode = options.conflictCode ?? "ACTIVE_SCOPE_CONFLICT";
        await route.fulfill({
          body: JSON.stringify({
            type: "https://kor-travel-map/errors/conflict",
            title:
              conflictCode === "LOCK_BUSY"
                ? "scope lock 경합"
                : "동일 scope 갱신이 이미 실행 중입니다.",
            status: 409,
            detail:
              conflictCode === "LOCK_BUSY"
                ? "scope lock 경합"
                : "동일 scope 갱신이 이미 실행 중입니다.",
            code: conflictCode,
            details:
              conflictCode === "LOCK_BUSY"
                ? { retry_after_seconds: 30 }
                : {
                    request_id: REQUEST_ID,
                    status: "running",
                    detail_url:
                      `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
                  },
            request_id: "e2e-refresh-409",
            errors: [],
          }),
          contentType: "application/json",
          headers: conflictCode === "LOCK_BUSY" ? { "Retry-After": "30" } : {},
          status: 409,
        });
        return;
      }
      const existing = requestLedger.get(idempotencyKey);
      if (existing) {
        if (existing.bodyJson !== bodyJson) {
          await fulfillJson(
            route,
            {
              type: "https://kor-travel-map/errors/idempotency-conflict",
              title: "Idempotency conflict",
              status: 409,
              detail: "같은 Idempotency-Key의 body가 다릅니다.",
              code: "IDEMPOTENCY_CONFLICT",
              request_id: "e2e-refresh-conflict",
            },
            409,
          );
          return;
        }
        await fulfillJson(
          route,
          { ...existing.response, idempotent_replay: true },
        );
        return;
      }
      const response: FeatureUpdateRequestCreateResponse = {
        data: makeCreatedRequest(
          options.reusedActiveRequest
            ? {
                request_id: REQUEST_ID,
                status: "running",
                dispatch_requested_at: MOCK_OLD,
              }
            : {},
        ),
        meta: makeMeta("e2e-refresh-now"),
        idempotent_replay: false,
        reused_active_request: options.reusedActiveRequest ?? false,
      };
      requestLedger.set(idempotencyKey, { bodyJson, response });
      if (options.createResponseLossOnce && posts.length === 1) {
        await route.abort("connectionreset");
        return;
      }
      await fulfillJson(route, response, options.reusedActiveRequest ? 200 : 201);
      return;
    }
    if (
      pathname.startsWith("/v1/ops/pipeline/executions/update_request/") &&
      request.method() === "GET"
    ) {
      const queriedRequestId = pathname.split("/").at(-1) ?? NEW_REQUEST_ID;
      executionGets.push(pathname);
      if (options.executionGetStatus && options.executionGetStatus >= 400) {
        await route.fulfill({
          body: JSON.stringify({
            type: "https://kor-travel-map/errors/service-unavailable",
            title: "execution store unavailable",
            status: options.executionGetStatus,
            detail: "execution store unavailable",
            code: "SERVICE_UNAVAILABLE",
            request_id: "e2e-exec-get-error",
            errors: [],
          }),
          contentType: "application/problem+json",
          status: options.executionGetStatus,
        });
        return;
      }
      const executionStatus =
        typeof options.executionStatus === "function"
          ? options.executionStatus(executionGets.length)
          : (options.executionStatus ?? "done");
      const response: DatasetRefreshExecutionDetailResponse = {
        data: {
          execution: {
            kind: "update_request",
            id: queriedRequestId,
            status: executionStatus as "done",
            created_at: FRESH_AT,
            error_message: null,
            dagster_run_id: null,
            dagster_run_status: null,
            job_id: JOB_ID,
            started_at: FRESH_AT,
            finished_at: FRESH_AT,
            current_stage: null,
            dataset_key: KMA_DATASET,
            job_kind: null,
            load_batch_id: null,
            operation_registry_version: "provider_operation_registry.v1",
            operator: "local-admin",
            parent_job_id: null,
            priority: 75,
            progress: 100,
            provider: KMA_PROVIDER,
            request_id: queriedRequestId,
            run_mode: "now",
            scope_type: "provider_dataset",
            trigger_kind: "manual",
            detail_url:
              "/v1/ops/pipeline/executions/update_request/" + queriedRequestId,
          },
          update_request: makeRequestRecord({
            request_id: queriedRequestId,
            status: executionStatus as "done",
          }),
          import_job: null,
          cancellation: null,
          events: [],
          events_next_cursor: null,
          root: {
            id: queriedRequestId,
            kind: "update_request",
            status: executionStatus as "done",
            created_at: FRESH_AT,
            started_at: FRESH_AT,
            finished_at: FRESH_AT,
            error_message: null,
            providers: [KMA_PROVIDER],
            dataset_keys: [KMA_DATASET],
            provider_datasets: [
              {
                provider: KMA_PROVIDER,
                dataset_key: KMA_DATASET,
                sync_scope: KMA_SCOPE,
                status: executionStatus as "done",
                operation_member_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
              },
            ],
            linked_job_count: 1,
            requested_job_id: JOB_ID,
            operator: "local-admin",
            priority: 75,
            progress: 100,
            current_stage: null,
            dagster_run_id: null,
            dagster_run_status: null,
            run_mode: "now",
            scope_type: "provider_dataset",
            trigger_kind: "manual",
            operation_registry_version: "provider_operation_registry.v1",
            detail_url:
              `/v1/ops/pipeline/executions/update_request/${queriedRequestId}`,
            cancellation: null,
            projected_job: {
              id: JOB_ID,
              job_kind: "feature_update",
              status: executionStatus as "done",
              progress: 100,
              current_stage: null,
              created_at: FRESH_AT,
              started_at: FRESH_AT,
              finished_at: FRESH_AT,
              error_message: null,
              dagster_run_id: null,
              dagster_run_status: null,
              trigger_kind: "manual",
              detail_url: `/v1/ops/pipeline/executions/import_job/${JOB_ID}`,
              depth: 1,
              load_batch_id: null,
              parent_job_id: null,
              operation_registry_version: "provider_operation_registry.v1",
            },
          },
        },
        meta: makeMeta("e2e-execution-detail"),
      };
      await fulfillJson(route, response);
      return;
    }
    throw new Error(`Unexpected pipeline call: ${request.method()} ${pathname}`);
  });

  return {
    posts,
    executionGets,
    persistedRequestCount: () => requestLedger.size,
  };
}

function defaultGrid(): {
  items: OpsDatasetGridRow[];
  details: Record<string, OpsDatasetDetailData>;
} {
  const kma = makeGridRow();
  const mois = makeGridRow({
    provider: MOIS_PROVIDER,
    dataset_key: MOIS_DATASET,
    sync_scope: "default",
    status: "never_run",
    last_success_at: null,
    catalog: makeCatalog({
      feature_kind: "place",
      provider_state_default_scope: "default",
      label: "MOIS 인허가 bulk",
      is_feature_load: true,
      scope_refresh: {
        allowed_sync_scopes: [],
        default_sync_scope: "dataset_wide",
        effect: "dataset_wide",
        reason: "이 dataset은 전체 dataset 단위로만 갱신합니다.",
        selector: "none",
        supported: false,
      },
      preview: {
        supported: false,
        input_kind: "none",
        sources: [],
        default_max_items: 20,
        max_items_limit: 100,
        external_call_budget: 0,
        timeout_seconds: 5,
      },
    }),
  });
  const krex = makeGridRow({
    provider: KREX_PROVIDER,
    dataset_key: KREX_DATASET,
    sync_scope: "default",
    status: "active",
    last_success_at: MOCK_OLD,
    last_failure_at: "2026-07-14T23:30:00.000Z",
    consecutive_failures: 2,
    freshness: makeFreshness({
      state: "overdue",
      is_overdue: true,
      overdue_by_seconds: 172_800,
      due_at: MOCK_OLD,
    }),
    dataset_issues: makeIssueSummary({
      open_count: 3,
      severity_counts: { error: 2, warning: 1 },
    }),
    refresh_policy: makeRefreshPolicy({
      provider: KREX_PROVIDER,
      dataset_key: KREX_DATASET,
    }),
    catalog: makeCatalog({
      feature_kind: "place",
      provider_state_default_scope: "default",
      label: "고속도로 휴게소",
      is_feature_load: true,
      scope_refresh: {
        allowed_sync_scopes: [],
        default_sync_scope: "dataset_wide",
        effect: "dataset_wide",
        reason: "이 dataset은 전체 dataset 단위로만 갱신합니다.",
        selector: "none",
        supported: false,
      },
    }),
  });
  return {
    items: [kma, mois, krex],
    details: {
      [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
        // source_kind는 서버 정본(openapi)이라 select가 아닌 readOnly로 뜨고,
        // null nullable 필드는 draft에 빈 값으로 로드돼 PUT에서 null로 보존된다.
        refresh_policy: makeRefreshPolicy({
          source_kind: "openapi",
          targeted_policy: "follow_system",
          system_interval_seconds: 3600,
          optimal_interval_seconds: null,
          min_interval_seconds: null,
          max_requests_per_minute: 30,
          max_requests_per_hour: null,
          max_requests_per_day: null,
          burst_size: null,
          stale_after_minutes: null,
        }),
        recent_runs: [makeLatestExecution()],
        recent_events: [
          {
            event_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            job_id: JOB_ID,
            stage: "loading",
            level: "error",
            code: "provider.timeout",
            message: "provider timeout",
            occurred_at: MOCK_OLD,
          },
        ],
      }),
      [`${MOIS_PROVIDER}/${MOIS_DATASET}`]: makeDetail({
        provider: MOIS_PROVIDER,
        dataset_key: MOIS_DATASET,
        catalog: makeCatalog({
          feature_kind: "place",
          provider_state_default_scope: "default",
          label: "MOIS 인허가 bulk",
          is_feature_load: true,
          scope_refresh: {
            allowed_sync_scopes: [],
            default_sync_scope: "dataset_wide",
            effect: "dataset_wide",
            reason: "이 dataset은 전체 dataset 단위로만 갱신합니다.",
            selector: "none",
            supported: false,
          },
          preview: {
            supported: false,
            input_kind: "none",
            sources: [],
            default_max_items: 20,
            max_items_limit: 100,
            external_call_budget: 0,
            timeout_seconds: 5,
          },
        }),
        scopes: [
          {
            sync_scope: "default",
            status: "never_run",
            cursor: {},
            last_success_at: null,
            last_failure_at: null,
            eligible_after: null,
            freshness: makeFreshness({
              state: "never_run",
              basis: "unknown",
              due_at: null,
              sla_seconds: null,
            }),
            consecutive_failures: 0,
          },
        ],
      }),
      [`${KREX_PROVIDER}/${KREX_DATASET}`]: makeDetail({
        provider: KREX_PROVIDER,
        dataset_key: KREX_DATASET,
        catalog: makeCatalog({
          feature_kind: "place",
          provider_state_default_scope: "default",
          label: "고속도로 휴게소",
          is_feature_load: true,
          scope_refresh: {
            allowed_sync_scopes: [],
            default_sync_scope: "dataset_wide",
            effect: "dataset_wide",
            reason: "이 dataset은 전체 dataset 단위로만 갱신합니다.",
            selector: "none",
            supported: false,
          },
        }),
        refresh_policy: makeRefreshPolicy({
          provider: KREX_PROVIDER,
          dataset_key: KREX_DATASET,
        }),
        dataset_issues: makeIssueSummary({
          open_count: 3,
          severity_counts: { error: 2, warning: 1 },
        }),
      }),
    },
  };
}

test.describe("/ops/datasets 페이지 ② (T-ADM-C4)", () => {
  test.beforeEach(async ({ page }) => {
    // mocked suite에서 ops-live WS를 inert로 — 지금 갱신 폐루프는 폴링 fallback 경로.
    await installInertOpsLiveWebSocket(page);
    await loginIfGateEnabled(page);
  });

  test("그리드 로드 — 3원 행, never_run 배지, 이슈 배지, 요약 배지", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");

    await expect(
      page.getByRole("heading", { level: 1, name: "데이터셋" }),
    ).toBeVisible();

    // 요약 배지 — 실패/오래됨/미실행/이슈 (never_run은 stale로 세지 않는다).
    await expect(page.getByText("행 3")).toBeVisible();
    await expect(page.getByText("실패 1")).toBeVisible();
    await expect(page.getByText(/오래됨\(SLA 초과\) 1/)).toBeVisible();
    await expect(page.getByText("미실행 1")).toBeVisible();
    await expect(page.getByText("이슈 3")).toBeVisible();

    const grid = page.getByRole("table", { name: "데이터셋 그리드" });
    await expect(
      grid.getByRole("columnheader", { name: "마지막 실패" }),
    ).toBeVisible();
    // 3원 행 — scope가 canonical target_grids로 노출.
    const kmaRow = grid.getByRole("row", { name: /kma_short_forecast/ });
    await expect(kmaRow).toContainText(KMA_SCOPE);
    // never_run 행은 "미실행" 상태 배지.
    const moisRow = grid.getByRole("row", { name: /mois_license_features_bulk/ });
    await expect(moisRow).toContainText("미실행");
    // 이슈/실패/오래됨 배지 + 정책 요약.
    const krexRow = grid.getByRole("row", { name: /krex_rest_areas/ });
    await expect(krexRow).toContainText("allow_targeted");
    await expect(krexRow).toContainText("오래됨");
    await expect(krexRow.getByText("2", { exact: true })).toBeVisible();
    await expect(krexRow.getByText("3", { exact: true })).toBeVisible();
    await expect(krexRow).toContainText(/26\. 7\. 15\. (?:오전|AM) 8:30:00/);
  });

  test("검색·상태 필터가 행을 좁힌다", async ({ page }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    const grid = page.getByRole("table", { name: "데이터셋 그리드" });
    await expect(grid.getByRole("row", { name: /kma_short_forecast/ })).toBeVisible();

    await page.getByLabel("검색").fill("krex");
    await expect(grid.getByRole("row", { name: /krex_rest_areas/ })).toBeVisible();
    await expect(grid.getByRole("row", { name: /kma_short_forecast/ })).toHaveCount(0);

    await page.getByLabel("검색").fill("");
    await page.locator("#datasets-status").selectOption("never_run");
    await expect(
      grid.getByRole("row", { name: /mois_license_features_bulk/ }),
    ).toBeVisible();
    await expect(grid.getByRole("row", { name: /krex_rest_areas/ })).toHaveCount(0);

    await page.locator("#datasets-status").selectOption("issues");
    await expect(grid.getByRole("row", { name: /krex_rest_areas/ })).toBeVisible();
    await expect(
      grid.getByRole("row", { name: /mois_license_features_bulk/ }),
    ).toHaveCount(0);
  });

  test("이슈 있음은 dataset 또는 provider open issue가 있는 행을 모두 남긴다", async ({
    page,
  }) => {
    const issueRows = [
      makeGridRow({
        provider: "provider-only",
        dataset_key: "provider_issue_dataset",
        provider_issues: makeIssueSummary({ open_count: 1 }),
      }),
      makeGridRow({
        provider: "dataset-only",
        dataset_key: "dataset_issue_dataset",
        dataset_issues: makeIssueSummary({ open_count: 2 }),
      }),
      makeGridRow({
        provider: "both",
        dataset_key: "both_issue_dataset",
        dataset_issues: makeIssueSummary({ open_count: 3 }),
        provider_issues: makeIssueSummary({ open_count: 4 }),
      }),
      makeGridRow({
        provider: "neither",
        dataset_key: "no_issue_dataset",
      }),
    ];
    await mockOpsDatasets(page, { items: issueRows, details: {} });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    const grid = page.getByRole("table", { name: "데이터셋 그리드" });
    const providerOnly = grid.getByRole("row", {
      name: /provider_issue_dataset/,
    });
    const datasetOnly = grid.getByRole("row", {
      name: /dataset_issue_dataset/,
    });
    const both = grid.getByRole("row", { name: /both_issue_dataset/ });
    const neither = grid.getByRole("row", { name: /no_issue_dataset/ });

    await expect(providerOnly.getByTitle("제공자 이슈")).toContainText("P1");
    await expect(providerOnly.getByTitle("데이터셋 이슈")).toHaveCount(0);
    await expect(datasetOnly.getByTitle("데이터셋 이슈")).toContainText("2");
    await expect(both.getByTitle("데이터셋 이슈")).toContainText("3");
    await expect(both.getByTitle("제공자 이슈")).toContainText("P4");
    await expect(neither.getByTitle(/이슈/)).toHaveCount(0);
    await expect(page.getByText("이슈 10", { exact: true })).toBeVisible();

    await page.locator("#datasets-status").selectOption("issues");
    await expect(providerOnly).toBeVisible();
    await expect(datasetOnly).toBeVisible();
    await expect(both).toBeVisible();
    await expect(neither).toHaveCount(0);
  });

  test("drawer 상태·이력 — scope 배열, cursor JSON, 최근 실행 파이프라인 딥링크, 이벤트", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);

    // 딥링크로 KMA 행을 선택해 drawer가 뜬다.
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    await expect(
      page.getByText(`${KMA_PROVIDER}/${KMA_DATASET}`).first(),
    ).toBeVisible();
    await expect.poll(() => mocks.counts.detail).toBeGreaterThanOrEqual(1);

    // scope 상태 테이블 + cursor JSON.
    const scopeTable = page.getByRole("table", { name: "sync scope 상태" });
    await expect(
      scopeTable.getByRole("columnheader", { name: "마지막 실패" }),
    ).toBeVisible();
    await expect(scopeTable.getByRole("row", { name: /target_grids/ })).toBeVisible();
    await expect(page.getByText(/"base_date": "20260714"/)).toBeVisible();

    // 최근 실행 — 페이지 ① 실행 상세 딥링크(`execution={kind}:{id}`).
    const runsTable = page.getByRole("table", { name: "최근 실행" });
    const runRow = runsTable.getByRole("row", {
      name: new RegExp(REQUEST_ID.slice(0, 12)),
    });
    await expect(runRow).toBeVisible();
    await expect(runRow.getByRole("link", { name: "실행 상세" })).toHaveAttribute(
      "href",
      `/ops/pipeline?execution=update_request:${REQUEST_ID}`,
    );

    // 최근 이벤트 + Feature 보기 링크.
    await expect(page.getByText("provider timeout")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "생성된 Feature 보기" }),
    ).toHaveAttribute(
      "href",
      `/admin/features?provider=${KMA_PROVIDER}&dataset_key=${KMA_DATASET}`,
    );
  });

  test("정책 편집 — 고정 refresh-policy route+query 발화 + 저장 배지", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);
    await expect(page.getByText("데이터셋 상세")).toBeVisible();

    await page.getByRole("tab", { name: "갱신 정책" }).click();
    await expect(page.getByText("갱신 정책", { exact: true }).first()).toBeVisible();

    await page.getByLabel("타깃 갱신 정책", { exact: true }).selectOption("allow_targeted");
    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => mocks.policyPuts.length).toBe(1);
    expect(mocks.policyPuts[0].path).toBe(
      `/v1/ops/datasets/refresh-policy?provider=${KMA_PROVIDER}` +
        `&dataset_key=${KMA_DATASET}`,
    );
    expect(mocks.policyPuts[0].body).toMatchObject({
      source_kind: "openapi",
      targeted_policy: "allow_targeted",
      max_concurrent: 1,
      config_source: "db",
      enabled: true,
      // full PUT null 보존(#684) — 서버 record의 null interval/quota가 임의
      // 기본값으로 덮이지 않고 null로 남는다.
      optimal_interval_seconds: null,
      min_interval_seconds: null,
      max_requests_per_hour: null,
      max_requests_per_day: null,
      burst_size: null,
    });
    // provenance 필드는 UI가 보내지 않는다(rate_limit_source 서버 기록).
    expect(
      (mocks.policyPuts[0].body as Record<string, unknown>).rate_limit_source,
    ).toBeUndefined();
    await expect(page.getByText(/^저장됨 /)).toBeVisible();
  });

  test("정책 편집 — 양의 정수 검증 실패는 PUT을 막는다", async ({ page }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("tab", { name: "갱신 정책" }).click();

    await page.getByLabel("시간당 요청 수", { exact: true }).fill("0");
    await page.getByRole("button", { name: "저장" }).click();

    await expect(page.getByText("양의 정수를 입력하세요.").first()).toBeVisible();
    await expect.poll(() => mocks.policyPuts.length).toBe(0);
  });

  test("정책 편집 — 작성 중 refetch는 draft를 보존하고 서버 값 적용을 명시 선택한다", async ({
    page,
  }) => {
    const { items } = defaultGrid();
    const initialPolicy = makeRefreshPolicy({
      targeted_policy: "follow_system",
      updated_at: "2026-07-14T00:00:00.000Z",
    });
    const changedPolicy = makeRefreshPolicy({
      targeted_policy: "disabled",
      updated_at: "2026-07-15T00:00:00.000Z",
    });
    const mocks = await mockOpsDatasets(page, {
      items,
      details: {
        [`${KMA_PROVIDER}/${KMA_DATASET}`]: (detailCount) =>
          makeDetail({
            refresh_policy: detailCount === 1 ? initialPolicy : changedPolicy,
          }),
      },
    });
    await mockPipelineRequests(page);

    await page.goto(`${KMA_DEEP_LINK}&panel=policy`);
    const targetedPolicy = page.getByLabel("타깃 갱신 정책", { exact: true });
    await expect(targetedPolicy).toHaveValue("follow_system");
    await targetedPolicy.selectOption("allow_targeted");

    await page.getByRole("button", { name: "새로고침" }).click();
    await expect.poll(() => mocks.counts.detail).toBeGreaterThan(1);
    await expect(page.getByText("서버 정책이 변경됨")).toBeVisible();
    await expect(targetedPolicy).toHaveValue("allow_targeted");

    await page.getByRole("button", { name: "서버 값 다시 불러오기" }).click();
    await expect(targetedPolicy).toHaveValue("disabled");
    await expect(page.getByText("서버 정책이 변경됨")).toHaveCount(0);
  });

  test("정책 편집 — orphan 행은 저장 UI를 열지 않는다", async ({
    page,
  }) => {
    const orphan = makeGridRow({
      provider: "retired-provider",
      dataset_key: "retired-dataset",
      sync_scope: "legacy",
      catalog: null,
      catalog_state: "orphan",
      orphan_reason: "카탈로그에서 제거됨",
      mutable: false,
      detail_url:
        "/v1/ops/datasets/detail?provider=retired-provider&dataset_key=retired-dataset&sync_scope=legacy",
    });
    const mocks = await mockOpsDatasets(page, {
      items: [orphan],
      details: {
        "retired-provider/retired-dataset": makeDetail({
          provider: "retired-provider",
          dataset_key: "retired-dataset",
          catalog: null,
          catalog_state: "orphan",
          orphan_reason: "카탈로그에서 제거됨",
          mutable: false,
          scopes: [
            {
              ...makeDetail().scopes[0],
              sync_scope: "legacy",
            },
          ],
        }),
      },
    });
    await mockPipelineRequests(page);

    await page.goto(
      "/ops/datasets?provider=retired-provider&dataset=retired-dataset" +
        "&sync_scope=legacy&panel=policy",
    );

    await expect(page.getByTestId("policy-readonly-alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "저장" })).toHaveCount(0);
    await expect.poll(() => mocks.policyPuts.length).toBe(0);
  });

  test("정책 편집 — canonical mutable=false 행도 독립적으로 저장 UI를 막는다", async ({
    page,
  }) => {
    const row = makeGridRow({ mutable: false });
    const mocks = await mockOpsDatasets(page, {
      items: [row],
      details: {
        [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({ mutable: false }),
      },
    });
    await mockPipelineRequests(page);

    await page.goto(`${KMA_DEEP_LINK}&panel=policy`);

    await expect(page.getByTestId("policy-readonly-alert")).toContainText(
      "mutable=false",
    );
    await expect(page.getByRole("button", { name: "저장" })).toHaveCount(0);
    await expect.poll(() => mocks.policyPuts.length).toBe(0);
  });

  test("ETL 미리보기 — fixture 실행 결과 렌더", async ({ page }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("tab", { name: "ETL 미리보기" }).click();
    await page.getByRole("button", { name: "fixture 실행" }).click();

    await expect.poll(() => mocks.previewPosts.length).toBe(1);
    expect(mocks.previewPosts[0].path).toBe(
      `/v1/ops/datasets/preview?provider=${KMA_PROVIDER}` +
        `&dataset_key=${KMA_DATASET}`,
    );
    expect(mocks.previewPosts[0].source).toBe("fixture");
    await expect(page.getByText("WeatherValue")).toBeVisible();
    await expect(page.getByText(/"metric_key": "temperature_c"/)).toBeVisible();
  });

  test("ETL 미리보기 — capability 미지원이면 실행 버튼이 fail-closed로 비활성", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    // MOIS 행은 preview.supported=false — live 경로는 계약에서 제거됐고(#678)
    // fixture 버튼도 capability 없이는 활성화되지 않는다(#684 fail-closed).
    await page.goto(
      `/ops/datasets?provider=${MOIS_PROVIDER}&dataset=${MOIS_DATASET}` +
        "&sync_scope=default&panel=preview",
    );
    await expect(page.getByRole("button", { name: "live 실행" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "fixture 실행" }),
    ).toBeDisabled();
    await expect(page.getByText("미리보기 미지원")).toBeVisible();
  });

  test("지금 갱신 — provider_dataset 요청 생성 + 인라인 상태 추적 + 신선도 refetch", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const datasetMocks = await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, {
      executionStatus: "done",
    });

    await page.goto(KMA_DEEP_LINK);
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    const listCountBefore = datasetMocks.counts.list;

    await page.getByRole("button", { name: "지금 갱신" }).click();

    // POST 본문 — provider_dataset scope + 감사 필드.
    await expect.poll(() => pipeline.posts.length).toBe(1);
    expect(pipeline.posts[0].body).toMatchObject({
      scope: {
        type: "provider_dataset",
        provider: KMA_PROVIDER,
        dataset_key: KMA_DATASET,
        sync_scope: KMA_SCOPE,
      },
      run_mode: "now",
    });
    expect(pipeline.posts[0].body).not.toHaveProperty("providers");
    expect(pipeline.posts[0].body).not.toHaveProperty("dataset_keys");
    expect(pipeline.posts[0].body).not.toHaveProperty("dry_run");
    // actor는 서버가 인증 컨텍스트에서 파생한다 — body에 operator를 보내지
    // 않는다(#684 감사 위조 방지).
    expect(
      (pipeline.posts[0].body as Record<string, unknown>).operator,
    ).toBeUndefined();

    // 실행 상세 GET으로 상태 추적 → terminal 어휘 "done"을 성공으로 인식해야
    // 한다(리뷰 S2 — 백엔드 _TERMINAL_STATES에 "succeeded"는 없다): 상태 배지
    // "완료"(statusLabel("done")) + 완료 alert + 페이지 ① 링크.
    await expect.poll(() => pipeline.executionGets.length).toBeGreaterThanOrEqual(1);
    await expect(page.getByText("완료", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("갱신 완료")).toBeVisible();
    await expect(page.getByRole("link", { name: "자세히" })).toHaveAttribute(
      "href",
      `/ops/pipeline?execution=update_request:${NEW_REQUEST_ID}`,
    );
    // 완료 전이 시 그리드 신선도 refetch(무효화 → 목록 재조회).
    await expect
      .poll(() => datasetMocks.counts.list)
      .toBeGreaterThan(listCountBefore);
  });

  test("지금 갱신 — 응답 유실은 같은 UUID key와 exact body로 한 요청을 replay한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, {
      createResponseLossOnce: true,
      executionStatus: "done",
    });
    await page.goto(KMA_DEEP_LINK);

    await page.getByRole("button", { name: "지금 갱신" }).click();
    await expect.poll(() => pipeline.posts.length).toBe(1);
    await expect(page.getByText("갱신 요청 실패")).toBeVisible();
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect.poll(() => pipeline.posts.length).toBe(2);
    await expect(page.getByTestId("refresh-create-result")).toHaveText(
      "동일 요청 결과 재생(200)",
    );
    expect(pipeline.posts[0].idempotencyKey).toMatch(UUID_PATTERN);
    expect(pipeline.posts[1].idempotencyKey).toBe(
      pipeline.posts[0].idempotencyKey,
    );
    expect(pipeline.posts[1].bodyJson).toBe(pipeline.posts[0].bodyJson);
    expect(pipeline.persistedRequestCount()).toBe(1);
  });

  test("지금 갱신 — 다른 계획의 활성 scope 409는 기존 요청 링크를 제공한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, { createStatus: 409 });

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect.poll(() => pipeline.posts.length).toBe(1);
    await expect(page.getByText("동일 범위 갱신이 이미 진행 중")).toBeVisible();
    const existing = page.getByRole("link", { name: /기존 요청 .* 보기/ });
    await expect(existing).toHaveAttribute(
      "href",
      `/ops/pipeline?execution=update_request:${REQUEST_ID}`,
    );
    await expect(existing).toHaveAttribute(
      "data-api-detail-url",
      `/v1/ops/pipeline/executions/update_request/${REQUEST_ID}`,
    );
  });

  test("지금 갱신 — LOCK_BUSY 409만 Retry-After 안내를 표시한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page, {
      createStatus: 409,
      conflictCode: "LOCK_BUSY",
    });

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect(page.getByText(/약 30초 후 다시 시도/)).toBeVisible();
    await expect(page.getByRole("link", { name: /기존 요청/ })).toHaveCount(0);
  });

  test("지금 갱신 — 동일 활성 요청 200 재사용을 명시하고 같은 요청으로 연결한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page, {
      executionStatus: "running",
      reusedActiveRequest: true,
    });

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect(page.getByTestId("refresh-create-result")).toHaveText(
      "활성 요청 재사용(200)",
    );
    await expect(page.getByRole("link", { name: "자세히" })).toHaveAttribute(
      "href",
      `/ops/pipeline?execution=update_request:${REQUEST_ID}`,
    );
    await expect(page.getByTestId("active-local-request")).toBeVisible();
    await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
  });

  test("지금 갱신 — 생성한 active 요청은 projection 반영 전 재POST를 막고 terminal 뒤 해제한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, {
      executionStatus: (executionGetCount) =>
        executionGetCount === 1 ? "running" : "done",
    });

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect(page.getByTestId("active-local-request")).toBeVisible();
    await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
    await expect.poll(() => pipeline.posts.length).toBe(1);
    await expect
      .poll(() => pipeline.executionGets.length, { timeout: 6_000 })
      .toBeGreaterThan(1);
    await expect(page.getByTestId("active-local-request")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeEnabled();
    await expect.poll(() => pipeline.posts.length).toBe(1);
  });

  test("지금 갱신 — latest root/pair가 active면 POST 전에 기존 operation으로 연결한다", async ({
    page,
  }) => {
    const activeExecution = makeLatestExecution({
      status: "running",
      pair_status: "running",
      finished_at: null,
      projected_job: {
        ...makeLatestExecution().projected_job,
        status: "running",
        progress: 42,
        finished_at: null,
      },
    });
    const row = makeGridRow({ latest_execution: activeExecution });
    await mockOpsDatasets(page, {
      items: [row],
      details: {
        [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
          recent_runs: [activeExecution],
        }),
      },
    });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);

    const active = page.getByTestId("active-latest-execution");
    await expect(active).toBeVisible();
    await expect(active).toContainText("실행중");
    await expect(active.getByRole("link", { name: /실행 .* 보기/ })).toHaveAttribute(
      "href",
      `/ops/pipeline?execution=update_request:${REQUEST_ID}`,
    );
    await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
    await expect.poll(() => pipeline.posts.length).toBe(0);
  });

  for (const activeSide of ["root", "pair"] as const) {
    test(`지금 갱신 — ${activeSide}만 active여도 기존 operation을 선제 사용한다`, async ({
      page,
    }) => {
      const activeExecution = makeLatestExecution({
        status: activeSide === "root" ? "running" : "done",
        pair_status: activeSide === "pair" ? "running" : "done",
        finished_at: null,
      });
      await mockOpsDatasets(page, {
        items: [makeGridRow({ latest_execution: activeExecution })],
        details: {
          [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
            recent_runs: [activeExecution],
          }),
        },
      });
      const pipeline = await mockPipelineRequests(page);

      await page.goto(KMA_DEEP_LINK);

      await expect(page.getByTestId("active-latest-execution")).toBeVisible();
      await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
      await expect.poll(() => pipeline.posts.length).toBe(0);
    });
  }

  test("지금 갱신 — 진입 전 active 작업의 terminal 전이를 polling해 버튼 차단을 해제한다", async ({
    page,
  }) => {
    const activeExecution = makeLatestExecution({
      status: "running",
      pair_status: "running",
      finished_at: null,
    });
    const terminalExecution = makeLatestExecution();
    const datasets = await mockOpsDatasets(page, {
      items: (listCount) => [
        makeGridRow({
          latest_execution:
            listCount === 1 ? activeExecution : terminalExecution,
        }),
      ],
      details: {
        [`${KMA_PROVIDER}/${KMA_DATASET}`]: (detailCount) =>
          makeDetail({
            recent_runs: [
              detailCount === 1 ? activeExecution : terminalExecution,
            ],
          }),
      },
    });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);
    await expect(page.getByTestId("active-latest-execution")).toBeVisible();

    await expect.poll(() => datasets.counts.list, { timeout: 6_000 }).toBeGreaterThan(1);
    await expect
      .poll(() => datasets.counts.detail, { timeout: 6_000 })
      .toBeGreaterThan(1);
    await expect(page.getByTestId("active-latest-execution")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeEnabled();
    const recentRun = page
      .getByRole("table", { name: "최근 실행" })
      .getByRole("row", { name: new RegExp(REQUEST_ID.slice(0, 12)) });
    await expect(recentRun).toContainText("완료");
  });

  for (const policyCase of [
    {
      name: "enabled=false",
      policy: makeRefreshPolicy({
        enabled: false,
        targeted_policy: "allow_targeted",
      }),
      reason: /enabled=false/,
    },
    {
      name: "targeted_policy=disabled",
      policy: makeRefreshPolicy({
        enabled: true,
        targeted_policy: "disabled",
      }),
      reason: /targeted_policy=disabled/,
    },
  ]) {
    test(`지금 갱신 — ${policyCase.name} 정책은 독립적으로 조작을 차단한다`, async ({
      page,
    }) => {
      await mockOpsDatasets(page, {
        items: [makeGridRow({ refresh_policy: policyCase.policy })],
        details: {
          [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
            refresh_policy: policyCase.policy,
          }),
        },
      });
      const pipeline = await mockPipelineRequests(page);

      await page.goto(KMA_DEEP_LINK);

      await expect(page.getByRole("button", { name: "지금 갱신" })).toBeDisabled();
      await expect(page.getByText(policyCase.reason)).toBeVisible();
      await expect.poll(() => pipeline.posts.length).toBe(0);
    });
  }

  test("scope capability — active external 첫 실행은 허용하고 다른 scope 이력을 섞지 않는다", async ({
    page,
  }) => {
    const items = [
      makeGridRow(),
      makeGridRow({
        sync_scope: ACTIVE_EXTERNAL_SCOPE,
        status: "never_run",
        last_success_at: null,
        latest_execution: null,
        freshness: makeFreshness({
          state: "never_run",
          basis: "unknown",
          due_at: null,
          sla_seconds: null,
        }),
      }),
    ];
    const detail = makeDetail({
      scopes: [
        ...makeDetail().scopes,
        {
          sync_scope: ACTIVE_EXTERNAL_SCOPE,
          status: "never_run",
          cursor: {},
          last_success_at: null,
          last_failure_at: null,
          eligible_after: null,
          freshness: makeFreshness({
            state: "never_run",
            basis: "unknown",
            due_at: null,
            sla_seconds: null,
          }),
          consecutive_failures: 0,
        },
      ],
      // 다른 target scope의 이력만 존재 — external 첫 실행에는 섞이면 안 된다.
      recent_runs: [makeLatestExecution()],
    });
    await mockOpsDatasets(page, {
      items,
      details: { [`${KMA_PROVIDER}/${KMA_DATASET}`]: detail },
    });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
        `&sync_scope=${encodeURIComponent(ACTIVE_EXTERNAL_SCOPE)}`,
    );
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeEnabled();
    const runs = page.getByRole("table", { name: "최근 실행" });
    await expect(runs).toContainText("최근 실행 기록이 없습니다.");

    await page.getByRole("button", { name: "지금 갱신" }).click();
    await expect.poll(() => pipeline.posts.length).toBe(1);
    expect(pipeline.posts[0].body.scope).toMatchObject({
      type: "provider_dataset",
      sync_scope: ACTIVE_EXTERNAL_SCOPE,
    });
  });

  test("scope capability — grid에만 남은 exact external scope는 상세 확인 실패로 조작을 막는다", async ({
    page,
  }) => {
    const externalRow = makeGridRow({
      sync_scope: ACTIVE_EXTERNAL_SCOPE,
      status: "never_run",
      last_success_at: null,
    });
    await mockOpsDatasets(page, {
      items: [externalRow],
      details: {
        [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
          // capability allow-list에는 남아 있지만 exact state가 응답에서 사라진 경합.
          scopes: makeDetail().scopes,
        }),
      },
    });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
        `&sync_scope=${encodeURIComponent(ACTIVE_EXTERNAL_SCOPE)}`,
    );

    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeDisabled();
    await expect(page.getByText(/exact sync scope가 상세 응답에 없어/)).toBeVisible();
    await expect.poll(() => pipeline.posts.length).toBe(0);
  });

  test("scope history — mixed 최근 실행에서 선택 external scope만 표시한다", async ({
    page,
  }) => {
    const externalExecution = makeLatestExecution({
      id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      sync_scope: ACTIVE_EXTERNAL_SCOPE,
      provider_datasets: [
        {
          provider: KMA_PROVIDER,
          dataset_key: KMA_DATASET,
          sync_scope: ACTIVE_EXTERNAL_SCOPE,
          status: "done",
          operation_member_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
        },
      ],
    });
    const externalRow = makeGridRow({
      sync_scope: ACTIVE_EXTERNAL_SCOPE,
      latest_execution: externalExecution,
    });
    const detail = makeDetail({
      scopes: [
        ...makeDetail().scopes,
        {
          ...makeDetail().scopes[0],
          sync_scope: ACTIVE_EXTERNAL_SCOPE,
        },
      ],
      recent_runs: [makeLatestExecution(), externalExecution],
    });
    await mockOpsDatasets(page, {
      items: [externalRow],
      details: { [`${KMA_PROVIDER}/${KMA_DATASET}`]: detail },
    });
    await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
        `&sync_scope=${encodeURIComponent(ACTIVE_EXTERNAL_SCOPE)}`,
    );

    const runs = page.getByRole("table", { name: "최근 실행" });
    await expect(runs).toContainText("eeeeeeee-eee");
    await expect(runs).not.toContainText(REQUEST_ID.slice(0, 12));
  });

  test("scope capability — 삭제된 external scope는 상태만 보이고 실행은 fail-closed한다", async ({
    page,
  }) => {
    const staleExecution = makeLatestExecution({
      id: "99999999-9999-4999-8999-999999999999",
      sync_scope: STALE_EXTERNAL_SCOPE,
      provider_datasets: [
        {
          provider: KMA_PROVIDER,
          dataset_key: KMA_DATASET,
          sync_scope: STALE_EXTERNAL_SCOPE,
          status: "done",
          operation_member_id: "88888888-8888-4888-8888-888888888888",
        },
      ],
    });
    const staleRow = makeGridRow({
      sync_scope: STALE_EXTERNAL_SCOPE,
      latest_execution: staleExecution,
    });
    const detail = makeDetail({
      scopes: [
        ...makeDetail().scopes,
        {
          sync_scope: STALE_EXTERNAL_SCOPE,
          status: "active",
          cursor: {},
          last_success_at: MOCK_OLD,
          last_failure_at: null,
          eligible_after: null,
          freshness: makeFreshness(),
          consecutive_failures: 0,
        },
      ],
      recent_runs: [makeLatestExecution(), staleExecution],
    });
    await mockOpsDatasets(page, {
      items: [staleRow],
      details: { [`${KMA_PROVIDER}/${KMA_DATASET}`]: detail },
    });
    await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
        `&sync_scope=${encodeURIComponent(STALE_EXTERNAL_SCOPE)}`,
    );
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeDisabled();
    await expect(
      page.getByText(/현재 활성 POI target에 없는 잔존 external scope/),
    ).toBeVisible();
    const runs = page.getByRole("table", { name: "최근 실행" });
    await expect(runs).toContainText("99999999-999");
    await expect(runs).not.toContainText(REQUEST_ID.slice(0, 12));
  });

  test("dataset-wide — 기본 state 행은 sync_scope 필드 없이 now 요청한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const moisDetail = details[`${MOIS_PROVIDER}/${MOIS_DATASET}`];
    details[`${MOIS_PROVIDER}/${MOIS_DATASET}`] = {
      ...moisDetail,
      recent_runs: [
        makeLatestExecution({
          id: "11111111-1111-4111-8111-111111111111",
          sync_scope: "default",
        }),
        makeLatestExecution({
          id: "22222222-2222-4222-8222-222222222222",
          sync_scope: "dataset_wide",
        }),
        makeLatestExecution({
          id: "33333333-3333-4333-8333-333333333333",
          sync_scope: null,
        }),
      ],
    };
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${MOIS_PROVIDER}&dataset=${MOIS_DATASET}` +
        "&sync_scope=default",
    );
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeEnabled();
    const recentRuns = page.getByRole("table", { name: "최근 실행" });
    await expect(recentRuns).toContainText("11111111");
    await expect(recentRuns).toContainText("22222222");
    await expect(recentRuns).toContainText("33333333");
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect.poll(() => pipeline.posts.length).toBe(1);
    expect(pipeline.posts[0].body).toMatchObject({
      scope: {
        type: "provider_dataset",
        provider: MOIS_PROVIDER,
        dataset_key: MOIS_DATASET,
      },
      run_mode: "now",
    });
    expect(pipeline.posts[0].body.scope).not.toHaveProperty("sync_scope");
  });

  test("dataset-wide — provider 기본 state가 아닌 잔존 scope는 실행하지 않는다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const mois = items.find((row) => row.provider === MOIS_PROVIDER);
    if (!mois) {
      throw new Error("MOIS fixture row missing");
    }
    const staleRow = makeGridRow({
      ...mois,
      sync_scope: "legacy_scope",
    });
    const moisDetail = details[`${MOIS_PROVIDER}/${MOIS_DATASET}`];
    await mockOpsDatasets(page, {
      items: [staleRow],
      details: {
        [`${MOIS_PROVIDER}/${MOIS_DATASET}`]: {
          ...moisDetail,
          scopes: [
            ...moisDetail.scopes,
            {
              ...moisDetail.scopes[0],
              sync_scope: "legacy_scope",
              status: "active",
            },
          ],
        },
      },
    });
    await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${MOIS_PROVIDER}&dataset=${MOIS_DATASET}` +
        "&sync_scope=legacy_scope",
    );
    await expect(page.getByRole("button", { name: "지금 갱신" })).toBeDisabled();
    await expect(page.getByText(/잔존 비기본 scope/)).toBeVisible();
  });

  test("지금 갱신 — 상태 폴링 오류는 queued 고정 대신 명시 오류·재시도를 보여준다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, {
      executionStatus: "done",
      executionGetStatus: 503,
    });

    await page.goto(KMA_DEEP_LINK);
    await page.getByRole("button", { name: "지금 갱신" }).click();
    await expect.poll(() => pipeline.posts.length).toBe(1);

    const errorAlert = page.getByTestId("refresh-status-error");
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText("갱신 상태 확인 실패");
    await expect(errorAlert).toContainText("고정하지 않습니다");
    await expect(
      errorAlert.getByRole("button", { name: "다시 확인" }),
    ).toBeVisible();
    await expect(page.getByTestId("active-local-request")).toBeVisible();
    await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
    await expect.poll(() => pipeline.posts.length).toBe(1);
    // 오류 중에는 마지막 상태 배지를 진실처럼 표시하지 않는다.
    await expect(page.getByText("갱신 완료")).toHaveCount(0);
  });

  test("행 선택·panel이 URL로 반영되고 뒤로 가기로 복원된다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    // KREX 행 선택 → URL query 반영.
    await page
      .getByRole("button", {
        name: `${KREX_PROVIDER} ${KREX_DATASET} default 상세 열기`,
      })
      .click();
    await expect(page).toHaveURL(/provider=python-krex-api/);
    await expect(page).toHaveURL(/dataset=krex_rest_areas/);
    // panel 전환도 URL로.
    await page.getByRole("tab", { name: "갱신 정책" }).click();
    await expect(page).toHaveURL(/panel=policy/);

    // 뒤로 가기 → 선택 없는 진입 상태(빈 상태)로 복원(자동 row0 없음, C4R).
    await page.goBack();
    await page.goBack();
    await expect(page).not.toHaveURL(/provider=python-krex-api/);
    await expect(
      page.getByText("선택된 데이터셋 행이 없습니다."),
    ).toBeVisible();
  });

  test("provider-only 링크는 첫 canonical 3원 행으로 URL을 완성한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const orphanFirst = makeGridRow({
      provider: KMA_PROVIDER,
      dataset_key: "retired_dataset",
      sync_scope: "external_system:retired",
      catalog: null,
      catalog_state: "orphan",
      orphan_reason: "카탈로그에서 제거됨",
      mutable: false,
    });
    const staleCanonicalFirst = makeGridRow({
      sync_scope: STALE_EXTERNAL_SCOPE,
      freshness: makeFreshness({ state: "overdue" }),
    });
    await mockOpsDatasets(page, {
      items: [staleCanonicalFirst, orphanFirst, ...items],
      details,
    });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(`/ops/datasets?provider=${KMA_PROVIDER}`);

    await expect(page).toHaveURL(
      new RegExp(
        `provider=${KMA_PROVIDER}.*dataset=${KMA_DATASET}.*sync_scope=${KMA_SCOPE}`,
      ),
    );
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    await page.getByRole("button", { name: "지금 갱신" }).click();
    await expect.poll(() => pipeline.posts.length).toBe(1);
    expect(pipeline.posts[0].body.scope).toEqual({
      type: "provider_dataset",
      provider: KMA_PROVIDER,
      dataset_key: KMA_DATASET,
      sync_scope: KMA_SCOPE,
    });
  });

  test("잘못된 full tuple 딥링크는 provider 첫 행으로 대체하지 않는다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=${KMA_DATASET}` +
        "&sync_scope=external_system%3Amissing",
    );

    await expect(page.getByTestId("invalid-dataset-deep-link")).toBeVisible();
    await expect(page.getByText("데이터셋 상세")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "지금 갱신" })).toHaveCount(0);
    await expect(page).toHaveURL(/external_system%3Amissing/);
  });

  test("잘못된 dataset 딥링크는 같은 provider 대표 행으로 대체하지 않는다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KMA_PROVIDER}&dataset=missing_dataset` +
        `&sync_scope=${KMA_SCOPE}`,
    );

    await expect(page.getByTestId("invalid-dataset-deep-link")).toBeVisible();
    await expect(page.getByText("데이터셋 상세")).toHaveCount(0);
    await expect.poll(() => pipeline.posts.length).toBe(0);
  });

  test("딥링크 진입 후 닫기(X)로 상세가 닫히고 빈 상태로 수렴한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    // 딥링크로 KREX 상세 진입.
    await page.goto(
      `/ops/datasets?provider=${KREX_PROVIDER}&dataset=${KREX_DATASET}` +
        "&sync_scope=default",
    );
    await expect(
      page.getByText(`${KREX_PROVIDER}/${KREX_DATASET}`).first(),
    ).toBeVisible();

    // 닫기(X) → 상세가 실제로 닫히고 빈 상태에 도달(딥링크 값이 되살아나지
    // 않는다 — 리뷰 S2 회귀 가드).
    await page.getByRole("button", { name: "데이터셋 상세 닫기" }).click();
    await expect(page).not.toHaveURL(/provider=/);
    await expect(page.getByText("선택된 데이터셋 행이 없습니다.")).toBeVisible();
    await expect(page.getByText("데이터셋 상세")).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: `${KREX_PROVIDER} ${KREX_DATASET} default 상세 열기`,
      }),
    ).toBeFocused();
  });

  test("비딥링크 진입 후 행 선택→Escape로 빈 상태에 도달한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    // 비딥링크 진입은 빈 상태에서 시작(자동 row0 없음).
    await page.goto("/ops/datasets");
    await expect(page.getByText("선택된 데이터셋 행이 없습니다.")).toBeVisible();

    // 행 선택 → 상세 → Escape로 닫힘 → 다시 빈 상태(딥링크와 일관).
    await page
      .getByRole("button", {
        name: `${KMA_PROVIDER} ${KMA_DATASET} ${KMA_SCOPE} 상세 열기`,
      })
      .click();
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    const closeButton = page.getByRole("button", { name: "데이터셋 상세 닫기" });
    await closeButton.focus();
    await expect(closeButton).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(page).not.toHaveURL(/provider=/);
    await expect(page.getByText("선택된 데이터셋 행이 없습니다.")).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: `${KMA_PROVIDER} ${KMA_DATASET} ${KMA_SCOPE} 상세 열기`,
      }),
    ).toBeFocused();
  });

  test("선택 행이 필터로 사라진 뒤 닫으면 검색 필드로 focus가 복귀한다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(KMA_DEEP_LINK);
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    const search = page.getByLabel("검색");
    await search.fill("no-matching-row");
    await page.getByRole("button", { name: "데이터셋 상세 닫기" }).click();

    await expect(page).not.toHaveURL(/provider=/);
    await expect(search).toBeFocused();
  });

  test("Dagster 스케줄 소스 degrade가 배너/컬럼에 노출된다", async ({ page }) => {
    const { items, details } = defaultGrid();
    // GraphQL degrade 시 backend는 행 schedule.basis를 unknown으로 내린다.
    const degradedItems = items.map((row) => ({
      ...row,
      schedule: makeScheduleSummary({
        basis: "unknown",
        next_scheduled_at: null,
        status: "unknown",
        schedule_names: [],
        active_schedule_names: [],
      }),
    }));
    await mockOpsDatasets(page, {
      items: degradedItems,
      details,
      scheduleSourceStatus: "unavailable",
      scheduleSourceErrors: ["dagster graphql unreachable"],
    });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    const banner = page.getByTestId("schedule-degrade-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("dagster graphql unreachable");
    // 그리드 "다음 스케줄" 컬럼은 basis=unknown이면 "확인 불가"로 degrade 표시.
    const grid = page.getByRole("table", { name: "데이터셋 그리드" });
    await expect(
      grid.getByRole("row", { name: /kma_short_forecast/ }).getByText("확인 불가"),
    ).toBeVisible();
  });

  test("딥링크 — provider/dataset/sync_scope/panel=policy가 초기 상태로 반영된다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto(
      `/ops/datasets?provider=${KREX_PROVIDER}&dataset=${KREX_DATASET}` +
        `&sync_scope=default&panel=policy`,
    );

    // 딥링크 행이 선택되어 drawer 부제와 정책 탭이 초기 활성.
    await expect(
      page.getByText(`${KREX_PROVIDER}/${KREX_DATASET}`).first(),
    ).toBeVisible();
    const policyTab = page.getByRole("tab", { name: "갱신 정책" });
    await expect(policyTab).toHaveAttribute("aria-selected", "true");
    // 기존 정책 값이 draft에 프리필된다.
    await expect(page.getByLabel("타깃 갱신 정책", { exact: true })).toHaveValue("allow_targeted");
  });

  test("빈 그리드 — empty 문구 + placeholder", async ({ page }) => {
    await mockOpsDatasets(page, { items: [] });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");

    await expect(
      page.getByText("조건에 맞는 데이터셋 행이 없습니다."),
    ).toBeVisible();
    await expect(page.getByText("선택된 데이터셋 행이 없습니다.")).toBeVisible();
  });

  test("그리드 조회 실패 — destructive alert", async ({ page }) => {
    await page.route("**/api/proxy/v1/ops/datasets**", async (route) => {
      await fulfillJson(
        route,
        {
          type: "https://kor-travel-map/errors/internal-error",
          title: "서버 내부 오류",
          status: 500,
          detail: "datasets 조회 중 오류",
          code: "INTERNAL_ERROR",
          request_id: "e2e-datasets-500",
          errors: [],
        },
        500,
      );
    });

    await page.goto("/ops/datasets");

    await expect(
      page.getByRole("heading", { level: 1, name: "데이터셋" }),
    ).toBeVisible();
    const alert = page.getByRole("alert").filter({ hasText: "데이터셋 조회 실패" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/HTTP 500/);
  });
});
