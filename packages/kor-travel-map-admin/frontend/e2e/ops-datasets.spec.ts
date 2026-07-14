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
type OpsDatasetRunSummary = components["schemas"]["OpsDatasetRunSummary"];
type OpsDatasetsGridResponse = components["schemas"]["OpsDatasetsGridResponse"];
type FeatureUpdateRequestCreateRequest =
  components["schemas"]["FeatureUpdateRequestCreateRequest"];
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestRecord =
  components["schemas"]["FeatureUpdateRequestRecord"];
type ProviderRefreshPolicyRecord =
  components["schemas"]["ProviderRefreshPolicyRecord"];
type ProviderRefreshPolicyUpsertRequest =
  components["schemas"]["ProviderRefreshPolicyUpsertRequest"];

const MOCK_OLD = "2026-06-01T00:00:00.000Z";
const KMA_PROVIDER = "python-kma-api";
const KMA_DATASET = "kma_short_forecast";
const MOIS_PROVIDER = "python-mois-api";
const MOIS_DATASET = "mois_license_features_bulk";
const KREX_PROVIDER = "python-krex-api";
const KREX_DATASET = "krex_rest_areas";
const REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const NEW_REQUEST_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

/** isStale(>48h) 판정이 Date.now 기준이라 fresh 행은 실행 시각 근처 값을 쓴다. */
const FRESH_AT = new Date().toISOString();

function makeMeta(requestId: string): Meta {
  return { duration_ms: 1, request_id: requestId };
}

function makeCatalog(
  overrides: Partial<OpsDatasetCatalogInfo> = {},
): OpsDatasetCatalogInfo {
  return {
    feature_kind: "weather",
    default_sync_scope: "target_grids",
    label: "KMA 단기예보",
    is_feature_load: false,
    is_refreshable: true,
    preview: "fixture",
    ...overrides,
  };
}

function makeGridRow(overrides: Partial<OpsDatasetGridRow> = {}): OpsDatasetGridRow {
  return {
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET,
    sync_scope: "grid:60,127",
    status: "active",
    last_success_at: FRESH_AT,
    last_failure_at: null,
    next_run_after: null,
    consecutive_failures: 0,
    catalog: makeCatalog(),
    refresh_policy: null,
    open_issue_count: 0,
    issue_severity_counts: {},
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
    rate_limit_source: {},
    created_at: MOCK_OLD,
    updated_at: "2026-06-08T00:30:00.000Z",
    ...overrides,
  };
}

function makeRunSummary(
  overrides: Partial<OpsDatasetRunSummary> = {},
): OpsDatasetRunSummary {
  return {
    request_id: REQUEST_ID,
    status: "done",
    run_mode: "queued",
    scope_type: "provider_dataset",
    dry_run: false,
    priority: 75,
    job_id: JOB_ID,
    dagster_run_id: null,
    job_status: "done",
    job_progress: 100,
    job_current_stage: "loading",
    operator: "local-admin",
    reason: "e2e",
    error_message: null,
    created_at: MOCK_OLD,
    started_at: MOCK_OLD,
    finished_at: MOCK_OLD,
    updated_at: MOCK_OLD,
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
        sync_scope: "grid:60,127",
        status: "active",
        cursor: { base_date: "20260714", base_time: "0500" },
        last_success_at: FRESH_AT,
        last_failure_at: null,
        next_run_after: null,
        consecutive_failures: 0,
      },
    ],
    refresh_policy: null,
    recent_runs: [],
    recent_events: [],
    open_issue_count: 0,
    issue_severity_counts: {},
    ...overrides,
  };
}

function makeGridResponse(items: OpsDatasetGridRow[]): OpsDatasetsGridResponse {
  return { data: { items }, meta: makeMeta("e2e-ops-datasets") };
}

function makeDetailResponse(detail: OpsDatasetDetailData): OpsDatasetDetailResponse {
  return { data: detail, meta: makeMeta("e2e-ops-dataset-detail") };
}

function makeRequestRecord(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
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
    run_mode: "queued",
    priority: 75,
    status: "queued",
    dry_run: false,
    matched_scope: {},
    job_id: null,
    dagster_run_id: null,
    operator: "local-admin",
    reason: "dataset refresh from ops/datasets",
    error_message: null,
    created_at: FRESH_AT,
    started_at: null,
    finished_at: null,
    updated_at: FRESH_AT,
    ...overrides,
  };
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
 * `/v1/ops/datasets`(그리드) + `/{provider}/{dataset}`(상세) + refresh-policy PUT
 * + preview POST를 한 glob으로 잡고 pathname/method로 분기한다(T-217g idiom).
 */
async function mockOpsDatasets(
  page: Page,
  options: {
    items: OpsDatasetGridRow[];
    details?: Record<string, OpsDatasetDetailData>;
    previewStatus?: number;
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
      await fulfillJson(route, makeGridResponse(options.items));
      return;
    }
    if (pathname.endsWith("/refresh-policy") && request.method() === "PUT") {
      const body = request.postDataJSON() as ProviderRefreshPolicyUpsertRequest;
      policyPuts.push({ path: pathname, body });
      const [provider, dataset] = pathname
        .replace("/v1/ops/datasets/", "")
        .replace("/refresh-policy", "")
        .split("/");
      const response: OpsDatasetRefreshPolicyResponse = {
        data: makeRefreshPolicy({
          provider: decodeURIComponent(provider),
          dataset_key: decodeURIComponent(dataset),
          targeted_policy: body.targeted_policy ?? "follow_system",
          enabled: body.enabled ?? true,
        }),
        meta: makeMeta("e2e-policy-upsert"),
      };
      await fulfillJson(route, response);
      return;
    }
    if (pathname.endsWith("/preview") && request.method() === "POST") {
      counts.preview += 1;
      previewPosts.push({
        path: pathname,
        source: url.searchParams.get("source"),
      });
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
          dataset: KMA_DATASET,
          source: "fixture",
          variant: "WeatherValue",
          description: "KMA 단기예보 fixture",
          items: [{ metric_key: "temperature_c", value: 23.5 }],
        },
        meta: makeMeta("e2e-preview"),
      };
      await fulfillJson(route, response);
      return;
    }
    counts.detail += 1;
    const key = decodeURIComponent(pathname.replace("/v1/ops/datasets/", ""));
    const detail = options.details?.[key];
    if (!detail) {
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
    await fulfillJson(route, makeDetailResponse(detail));
  });

  return { counts, policyPuts, previewPosts };
}

/** `POST /v1/ops/pipeline/requests`(지금 갱신) + 실행 상세 GET(상태 추적) mock. */
async function mockPipelineRequests(
  page: Page,
  options: { createStatus?: number; executionStatus?: string } = {},
) {
  const posts: { body: FeatureUpdateRequestCreateRequest }[] = [];
  const executionGets: string[] = [];

  await page.route("**/api/proxy/v1/ops/pipeline/**", async (route) => {
    const request = route.request();
    const pathname = apiPathname(new URL(request.url()));
    if (pathname === "/v1/ops/pipeline/requests" && request.method() === "POST") {
      const body = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
      posts.push({ body });
      if (options.createStatus === 409) {
        await route.fulfill({
          body: JSON.stringify({
            type: "https://kor-travel-map/errors/conflict",
            title: "동일 scope 갱신이 이미 실행 중입니다.",
            status: 409,
            detail: "동일 scope 갱신이 이미 실행 중입니다.",
            code: "CONFLICT",
            request_id: "e2e-refresh-409",
            errors: [],
          }),
          contentType: "application/json",
          headers: { "Retry-After": "30" },
          status: 409,
        });
        return;
      }
      const response: FeatureUpdateRequestCreateResponse = {
        data: makeRequestRecord(),
        meta: makeMeta("e2e-refresh-now"),
      };
      await fulfillJson(route, response, 201);
      return;
    }
    if (
      pathname.startsWith("/v1/ops/pipeline/executions/update_request/") &&
      request.method() === "GET"
    ) {
      executionGets.push(pathname);
      const response: DatasetRefreshExecutionDetailResponse = {
        data: {
          execution: {
            kind: "update_request",
            id: NEW_REQUEST_ID,
            status: options.executionStatus ?? "done",
            created_at: FRESH_AT,
            error_message: null,
            dagster_run_id: null,
            job_id: JOB_ID,
            started_at: FRESH_AT,
            finished_at: FRESH_AT,
            detail_url:
              "/v1/ops/pipeline/executions/update_request/" + NEW_REQUEST_ID,
          },
          update_request: makeRequestRecord({
            status: options.executionStatus ?? "done",
          }),
        },
        meta: makeMeta("e2e-execution-detail"),
      };
      await fulfillJson(route, response);
      return;
    }
    throw new Error(`Unexpected pipeline call: ${request.method()} ${pathname}`);
  });

  return { posts, executionGets };
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
      default_sync_scope: "default",
      label: "MOIS 인허가 bulk",
      is_feature_load: true,
      preview: "none",
    }),
  });
  const krex = makeGridRow({
    provider: KREX_PROVIDER,
    dataset_key: KREX_DATASET,
    sync_scope: "default",
    status: "active",
    last_success_at: MOCK_OLD,
    consecutive_failures: 2,
    open_issue_count: 3,
    issue_severity_counts: { error: 2, warning: 1 },
    refresh_policy: makeRefreshPolicy({
      provider: KREX_PROVIDER,
      dataset_key: KREX_DATASET,
    }),
    catalog: makeCatalog({
      feature_kind: "place",
      default_sync_scope: "default",
      label: "고속도로 휴게소",
      is_feature_load: true,
      preview: "fixture",
    }),
  });
  return {
    items: [kma, mois, krex],
    details: {
      [`${KMA_PROVIDER}/${KMA_DATASET}`]: makeDetail({
        recent_runs: [makeRunSummary()],
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
          default_sync_scope: "default",
          label: "MOIS 인허가 bulk",
          is_feature_load: true,
          preview: "none",
        }),
        scopes: [
          {
            sync_scope: "default",
            status: "never_run",
            cursor: {},
            last_success_at: null,
            last_failure_at: null,
            next_run_after: null,
            consecutive_failures: 0,
          },
        ],
      }),
      [`${KREX_PROVIDER}/${KREX_DATASET}`]: makeDetail({
        provider: KREX_PROVIDER,
        dataset_key: KREX_DATASET,
        catalog: makeCatalog({
          feature_kind: "place",
          default_sync_scope: "default",
          label: "고속도로 휴게소",
          is_feature_load: true,
          preview: "fixture",
        }),
        refresh_policy: makeRefreshPolicy({
          provider: KREX_PROVIDER,
          dataset_key: KREX_DATASET,
        }),
        open_issue_count: 3,
        issue_severity_counts: { error: 2, warning: 1 },
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
    await expect(page.getByText(/오래됨\(>48h\) 0/)).toBeVisible();
    await expect(page.getByText("미실행 1")).toBeVisible();
    await expect(page.getByText("이슈 3")).toBeVisible();

    const grid = page.getByRole("table", { name: "데이터셋 그리드" });
    // 3원 행 — scope가 grid:60,127로 노출.
    const kmaRow = grid.getByRole("row", { name: /kma_short_forecast/ });
    await expect(kmaRow).toContainText("grid:60,127");
    // never_run 행은 "미실행" 상태 배지.
    const moisRow = grid.getByRole("row", { name: /mois_license_features_bulk/ });
    await expect(moisRow).toContainText("미실행");
    // 이슈/실패/오래됨 배지 + 정책 요약.
    const krexRow = grid.getByRole("row", { name: /krex_rest_areas/ });
    await expect(krexRow).toContainText("allow_targeted");
    await expect(krexRow).toContainText("오래됨");
    await expect(krexRow).toContainText("2"); // 연속 실패
    await expect(krexRow).toContainText("3"); // 이슈
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

  test("drawer 상태·이력 — scope 배열, cursor JSON, 최근 실행 파이프라인 딥링크, 이벤트", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");

    // 첫 행(kma)이 자동 선택되어 drawer가 뜬다.
    await expect(page.getByText("데이터셋 상세")).toBeVisible();
    await expect(
      page.getByText(`${KMA_PROVIDER}/${KMA_DATASET}`).first(),
    ).toBeVisible();
    await expect.poll(() => mocks.counts.detail).toBeGreaterThanOrEqual(1);

    // scope 상태 테이블 + cursor JSON.
    const scopeTable = page.getByRole("table", { name: "sync scope 상태" });
    await expect(scopeTable.getByRole("row", { name: /grid:60,127/ })).toBeVisible();
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

  test("정책 편집 — PUT /ops/datasets/{p}/{d}/refresh-policy 발화 + 저장 배지", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    await expect(page.getByText("데이터셋 상세")).toBeVisible();

    await page.getByRole("tab", { name: "갱신 정책" }).click();
    await expect(page.getByText("갱신 정책", { exact: true }).first()).toBeVisible();

    await page.getByLabel("타깃 갱신 정책", { exact: true }).selectOption("allow_targeted");
    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => mocks.policyPuts.length).toBe(1);
    expect(mocks.policyPuts[0].path).toBe(
      `/v1/ops/datasets/${KMA_PROVIDER}/${KMA_DATASET}/refresh-policy`,
    );
    expect(mocks.policyPuts[0].body).toMatchObject({
      source_kind: "openapi",
      targeted_policy: "allow_targeted",
      max_concurrent: 1,
      config_source: "db",
      enabled: true,
    });
    await expect(page.getByText(/^저장됨 /)).toBeVisible();
  });

  test("정책 편집 — 양의 정수 검증 실패는 PUT을 막는다", async ({ page }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    await page.getByRole("tab", { name: "갱신 정책" }).click();

    await page.getByLabel("시간당 요청 수", { exact: true }).fill("0");
    await page.getByRole("button", { name: "저장" }).click();

    await expect(page.getByText("양의 정수를 입력하세요.").first()).toBeVisible();
    await expect.poll(() => mocks.policyPuts.length).toBe(0);
  });

  test("ETL 미리보기 — fixture 실행 결과 렌더", async ({ page }) => {
    const { items, details } = defaultGrid();
    const mocks = await mockOpsDatasets(page, { items, details });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    await page.getByRole("tab", { name: "ETL 미리보기" }).click();
    await page.getByRole("button", { name: "fixture 실행" }).click();

    await expect.poll(() => mocks.previewPosts.length).toBe(1);
    expect(mocks.previewPosts[0].path).toBe(
      `/v1/ops/datasets/${KMA_PROVIDER}/${KMA_DATASET}/preview`,
    );
    expect(mocks.previewPosts[0].source).toBe("fixture");
    await expect(page.getByText("WeatherValue")).toBeVisible();
    await expect(page.getByText(/"metric_key": "temperature_c"/)).toBeVisible();
  });

  test("ETL 미리보기 — live는 서버 opt-in flag 403을 안내한다", async ({ page }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details, previewStatus: 403 });
    await mockPipelineRequests(page);

    await page.goto("/ops/datasets");
    await page.getByRole("tab", { name: "ETL 미리보기" }).click();
    await page.getByRole("button", { name: "live 실행" }).click();

    await expect(page.getByText("live 미리보기 비활성")).toBeVisible();
    await expect(
      page.getByText(/KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED/),
    ).toBeVisible();
  });

  test("지금 갱신 — provider_dataset 요청 생성 + 인라인 상태 추적 + 신선도 refetch", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    const datasetMocks = await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, {
      executionStatus: "done",
    });

    await page.goto("/ops/datasets");
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
        sync_scope: "grid:60,127",
      },
      providers: [KMA_PROVIDER],
      dataset_keys: [KMA_DATASET],
      dry_run: false,
      run_mode: "queued",
      operator: "local-admin",
    });

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

  test("지금 갱신 — 동일 scope 409는 Retry-After 안내를 띄운다", async ({
    page,
  }) => {
    const { items, details } = defaultGrid();
    await mockOpsDatasets(page, { items, details });
    const pipeline = await mockPipelineRequests(page, { createStatus: 409 });

    await page.goto("/ops/datasets");
    await page.getByRole("button", { name: "지금 갱신" }).click();

    await expect.poll(() => pipeline.posts.length).toBe(1);
    await expect(page.getByText("동일 범위 갱신이 이미 진행 중")).toBeVisible();
    await expect(page.getByText(/Retry-After/)).toBeVisible();
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
