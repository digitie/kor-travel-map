import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { makePipelineCancellationResponse } from "./pipeline-cancellation-fixture";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type FeatureUpdateRequestRecord =
  components["schemas"]["FeatureUpdateRequestRecord"];
type FeatureUpdateRequestListResponse =
  components["schemas"]["FeatureUpdateRequestListResponse"];
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type FeatureUpdateRequestCreateRequest =
  components["schemas"]["FeatureUpdateRequestCreateRequest"];
type FeatureUpdateRequestPreviewRequest =
  components["schemas"]["FeatureUpdateRequestPreviewRequest"];
type FeatureUpdateRequestPreviewResponse =
  components["schemas"]["FeatureUpdateRequestPreviewResponse"];
type FeatureUpdateRequestMutationResponse =
  components["schemas"]["FeatureUpdateRequestMutationResponse"];
type PipelineCancellationRequest =
  components["schemas"]["PipelineCancellationRequest"];
type FeatureUpdateRequestRunNowRequest =
  components["schemas"]["FeatureUpdateRequestRunNowRequest"];
type ProvidersResponse = components["schemas"]["ProvidersResponse"];
type ScopeDispatchFeatureUpdateRequestRecord = FeatureUpdateRequestRecord & {
  requested_sync_scope: string | null;
  effective_sync_scope: string | null;
  dispatch_requested_at: string | null;
};

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
// detail deeplink truncation을 검증할 수 있게 12자 초과 uuid를 쓴다(shortId는 12자+"...").
const DONE_REQUEST_ID = "aaaaaaaa-1111-4111-8111-111111111111";
const QUEUED_REQUEST_ID = "bbbbbbbb-2222-4222-8222-222222222222";
const RUNNING_REQUEST_ID = "cccccccc-4444-4444-8444-444444444444";
const CREATED_REQUEST_ID = "dddddddd-0000-4000-8000-000000000001";
const JOB_ID = "cccccccc-3333-4333-8333-333333333333";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeRequest(
  overrides: Partial<ScopeDispatchFeatureUpdateRequestRecord> = {},
): ScopeDispatchFeatureUpdateRequestRecord {
  return {
    created_at: MOCK_NOW,
    dagster_run_id: null,
    dataset_keys: [],
    dispatch_requested_at: null,
    effective_sync_scope: null,
    error_message: null,
    finished_at: null,
    job_id: JOB_ID,
    matched_scope: {},
    operator: "e2e-authenticated-admin",
    priority: 50,
    providers: [],
    reason: "admin ui request",
    requested_sync_scope: null,
    request_id: QUEUED_REQUEST_ID,
    run_mode: "queued",
    scope: {
      type: "center_radius",
      center: { lon: 126.978, lat: 37.5665 },
      radius_km: 5,
    },
    scope_type: "center_radius",
    started_at: null,
    status: "queued",
    status_url: `/v1/admin/features/update-requests/${QUEUED_REQUEST_ID}`,
    update_policy: {},
    generation: 1,
    ...overrides,
  };
}

function listResponse(
  items: FeatureUpdateRequestRecord[],
): FeatureUpdateRequestListResponse {
  return {
    data: { items },
    meta: {
      // 이 페이지는 cursor를 절대 따라가지 않으므로(useFeatureUpdateRequests는
      // page_size:100 하드코딩, cursor 컨트롤 없음) next_cursor는 항상 null로 둔다.
      duration_ms: 1,
      page: { page_size: 100, next_cursor: null, total: items.length },
      request_id: "e2e-feature-update-list",
    },
  };
}

function createResponse(
  record: FeatureUpdateRequestRecord,
): FeatureUpdateRequestCreateResponse {
  return {
    data: { ...record, result_kind: "request" },
    reused_active_request: false,
    meta: { duration_ms: 1, request_id: "e2e-feature-update-create" },
  } as FeatureUpdateRequestCreateResponse & { reused_active_request: boolean };
}

function previewResponse(
  body: FeatureUpdateRequestPreviewRequest,
  matchedScope: Record<string, unknown> = {
    feature_count: 0,
    sigungu_codes: [],
  },
): FeatureUpdateRequestPreviewResponse {
  return {
    data: {
      result_kind: "preview",
      scope_type: body.scope.type,
      scope: body.scope,
      providers: body.providers ?? [],
      dataset_keys: body.dataset_keys ?? [],
      update_policy: body.update_policy ?? {},
      run_mode: body.run_mode ?? "queued",
      priority: body.priority ?? 50,
      matched_scope: matchedScope,
    },
    meta: { duration_ms: 1, request_id: "e2e-feature-update-preview" },
  };
}

function mutationResponse(
  record: FeatureUpdateRequestRecord,
): FeatureUpdateRequestMutationResponse {
  return {
    data: record,
    meta: { duration_ms: 1, request_id: "e2e-feature-update-mutation" },
  };
}

interface FeatureUpdateMocks {
  /** create POST 호출 수(pathname === base). */
  create: number;
  /** preview POST 호출 수. */
  preview: number;
  /** run-now POST 호출 수(pathname endsWith /run-now). */
  runNow: number;
  /** cancel POST 호출 수(pathname endsWith /cancel). */
  cancel: number;
  /** GET list 호출 수(2초 폴링이 있으므로 create/mutation count만 정확하다). */
  list: number;
  createBodies: FeatureUpdateRequestCreateRequest[];
  previewBodies: FeatureUpdateRequestPreviewRequest[];
  runNowBodies: FeatureUpdateRequestRunNowRequest[];
  runNowRecords: ScopeDispatchFeatureUpdateRequestRecord[];
  cancelBodies: PipelineCancellationRequest[];
}

/**
 * list + create + cancel + run-now가 모두 같은 feature-update-requests glob에
 * 걸린다. method + pathname suffix로 분기하고, Next.js RSC/document 네비게이션은
 * route.continue()로 흘려보낸다(admin-ops mockOfflineUploadMutations와 동일 가드).
 */
async function mockFeatureUpdateRequests(
  page: Page,
  options: {
    initial?: FeatureUpdateRequestRecord[];
    createStatus?: number;
    createErrorBody?: unknown;
    previewStatus?: number;
    previewErrorBody?: unknown;
    previewMatchedScopes?: Record<string, unknown>[];
  } = {},
): Promise<FeatureUpdateMocks> {
  let items = [...(options.initial ?? [])];
  const mocks: FeatureUpdateMocks = {
    create: 0,
    preview: 0,
    runNow: 0,
    cancel: 0,
    list: 0,
    createBodies: [],
    previewBodies: [],
    runNowBodies: [],
    runNowRecords: [],
    cancelBodies: [],
  };
  const base = "/v1/admin/features/update-requests";
  const providersResponse: ProvidersResponse = {
    data: { providers: [] },
    meta: { duration_ms: 1, request_id: "e2e-feature-update-providers" },
  };

  await page.route("**/v1/debug/etl/providers**", async (route) => {
    bffApiPath(route.request().url());
    await fulfillJson(route, providersResponse);
  });

  await page.route("**/v1/admin/features/update-requests**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const pathname = bffApiPath(request.url());
    // Next.js RSC prefetch 요청(?_rsc=...)은 mock하지 않고 흘려보낸다.
    if (url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }

    const method = request.method();

    if (method === "GET" && pathname === base) {
      mocks.list += 1;
      // status 파라미터: 없으면(=all) 전체, 있으면 해당 status만.
      const status = url.searchParams.get("status");
      const filtered = status
        ? items.filter((item) => item.status === status)
        : items;
      await fulfillJson(route, listResponse(filtered));
      return;
    }

    if (method === "POST" && pathname === `${base}/preview`) {
      mocks.preview += 1;
      const body = request.postDataJSON() as FeatureUpdateRequestPreviewRequest;
      mocks.previewBodies.push(body);
      if (options.previewStatus && options.previewStatus >= 400) {
        await fulfillJson(
          route,
          options.previewErrorBody ?? {
            detail: "feature update preview failed",
          },
          options.previewStatus,
        );
        return;
      }
      await fulfillJson(
        route,
        previewResponse(
          body,
          options.previewMatchedScopes?.[mocks.preview - 1],
        ),
      );
      return;
    }

    if (method === "POST" && pathname === base) {
      mocks.create += 1;
      const body = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
      mocks.createBodies.push(body);
      if (options.createStatus && options.createStatus >= 400) {
        await fulfillJson(
          route,
          options.createErrorBody ?? { detail: "feature update create failed" },
          options.createStatus,
        );
        return;
      }
      const createdRequestId = `dddddddd-0000-4000-8000-${String(mocks.create).padStart(12, "0")}`;
      const created = makeRequest({
        request_id: createdRequestId,
        job_id: `abababab-0000-4000-8000-${String(mocks.create).padStart(12, "0")}`,
        status_url: `/v1/admin/features/update-requests/${createdRequestId}`,
        providers: body.providers ?? [],
        dataset_keys: body.dataset_keys ?? [],
        update_policy: body.update_policy ?? {},
        run_mode: body.run_mode ?? "queued",
        priority: body.priority ?? 50,
        reason: body.reason ?? null,
        status: "queued",
        scope: body.scope as FeatureUpdateRequestRecord["scope"],
        scope_type: body.scope.type,
      });
      // invalidateQueries refetch가 새 행을 보도록 list에 push.
      items = [created, ...items];
      await fulfillJson(route, createResponse(created));
      return;
    }

    if (method === "POST" && url.pathname.endsWith("/run-now")) {
      mocks.runNow += 1;
      const body = request.postDataJSON() as FeatureUpdateRequestRunNowRequest;
      mocks.runNowBodies.push(body);
      const requestId = url.pathname.split("/").at(-2) ?? "";
      const target =
        items.find((item) => item.request_id === requestId) ?? makeRequest();
      const dispatched = makeRequest({
        ...target,
        request_id: target.request_id,
        job_id: target.job_id,
        dispatch_requested_at: "2026-06-08T00:00:01.000Z",
        run_mode: target.run_mode,
        status_url: `/v1/admin/features/update-requests/${target.request_id}`,
        status: target.status,
      });
      mocks.runNowRecords.push(dispatched);
      await fulfillJson(route, mutationResponse(dispatched));
      return;
    }

    if (method === "POST" && url.pathname.endsWith("/cancel")) {
      mocks.cancel += 1;
      mocks.cancelBodies.push(
        request.postDataJSON() as PipelineCancellationRequest,
      );
      const requestId = url.pathname.split("/").at(-2) ?? "";
      const target =
        items.find((item) => item.request_id === requestId) ?? makeRequest();
      const cancelled = makeRequest({
        ...target,
        request_id: requestId,
        status: "cancelled",
      });
      items = [
        cancelled,
        ...items.filter((item) => item.request_id !== requestId),
      ];
      await fulfillJson(
        route,
        makePipelineCancellationResponse({
          rootKind: "update_request",
          rootId: requestId,
          initialStatus: target.status,
          dagsterRunId: target.dagster_run_id,
          reason: "cancelled from admin ui",
          members: [
            {
              jobId: target.job_id,
              dagsterRunId: target.dagster_run_id,
              operationKind: "feature_update_request",
            },
          ],
        }),
      );
      return;
    }

    throw new Error(
      `Unhandled feature-update-requests route: ${method} ${url}`,
    );
  });

  return mocks;
}

test.describe("admin/features/update-requests list + create depth", () => {
  test("create queued request: POST fires persisted payload, success Alert, new row", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");

    // pre-fill 기본값(lon=126.9780, lat=37.5665, radius km=5) 확인.
    await expect(page.getByLabel("경도")).toHaveValue("126.9780");
    await expect(page.getByLabel("위도")).toHaveValue("37.5665");
    await expect(page.getByLabel("반경(km)")).toHaveValue("5");

    await page.getByLabel(/미리보기/).uncheck();
    await expect(page.getByLabel(/미리보기/)).not.toBeChecked();
    await page.getByLabel("데이터셋 키").fill("mois_license_features_bulk");

    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    expect(mocks.createBodies[0]).toMatchObject({
      scope: {
        type: "center_radius",
        center: { lon: 126.978, lat: 37.5665 },
        radius_km: 5,
      },
      run_mode: "queued",
      reason: "admin ui request",
    });
    expect(mocks.createBodies[0]).not.toHaveProperty("operator");

    // 성공 Alert(role=status): request_id + status 노출.
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "요청 처리 완료" });
    await expect(successAlert).toBeVisible();
    await expect(successAlert).toContainText("대기");
    await expect(successAlert).toContainText(CREATED_REQUEST_ID);

    // 생성 후 list refetch가 새 queued 행을 보인다. 'all'로 바꿔도 보이도록 방어.
    await page.getByLabel("요청 상태 필터").selectOption("all");
    await expect(
      page.getByRole("row", {
        name: new RegExp(CREATED_REQUEST_ID.slice(0, 12)),
      }),
    ).toBeVisible();
  });

  test("preview endpoint와 create now: preview는 비영속, now 요청은 생성", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      previewMatchedScopes: [
        {
          feature_count: 37,
          sigungu_codes: ["11110", "11140"],
          provider_datasets: [
            {
              provider: "kma",
              dataset_key: "weather_short",
              feature_count: 30,
            },
            {
              provider: "tourapi",
              dataset_key: "tour_spot",
              feature_count: 7,
            },
          ],
        },
        {
          feature_count: 2,
          sigungu_codes: ["26110"],
          deduped_provider_scopes: [
            {
              provider: "tourapi",
              dataset_key: "tour_spot",
              feature_count: 2,
            },
          ],
        },
      ],
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("데이터셋 키").fill("tour_spot, weather_short");

    // Branch A — 기본 미리보기는 별도 200 endpoint를 쓴다.
    await expect(page.getByLabel(/미리보기/)).toBeChecked();
    await page.getByRole("button", { name: "미리보기" }).click();

    await expect.poll(() => mocks.preview).toBe(1);
    expect(mocks.create).toBe(0);
    expect(mocks.previewBodies[0]).toMatchObject({
      dataset_keys: ["tour_spot", "weather_short"],
      run_mode: "queued",
    });
    const previewAlert = page
      .getByRole("status")
      .filter({ hasText: "미리보기 완료" });
    await expect(previewAlert).toContainText("대상 Feature 37개");
    await expect(previewAlert).toContainText("시군구 2개");
    await expect(previewAlert).toContainText("11110, 11140");
    await expect(previewAlert).toContainText("제공자 전체");
    await expect(previewAlert).toContainText(
      "데이터셋 tour_spot, weather_short",
    );
    await expect(previewAlert).toContainText("실제 적재 그룹 2개");
    await expect(previewAlert).toContainText(
      "kma / weather_short · Feature 30개",
    );
    await expect(previewAlert).toContainText(
      "tourapi / tour_spot · Feature 7개",
    );

    // 같은 입력이라도 서버가 다시 계산한 응답으로 결과가 교체되어야 한다.
    await page.getByRole("button", { name: "미리보기" }).click();
    await expect.poll(() => mocks.preview).toBe(2);
    await expect(previewAlert).toContainText("대상 Feature 2개");
    await expect(previewAlert).toContainText("시군구 1개");
    await expect(previewAlert).toContainText("26110");
    await expect(previewAlert).toContainText("실제 적재 그룹 1개");
    await expect(previewAlert).toContainText(
      "tourapi / tour_spot · Feature 2개",
    );
    await expect(previewAlert).not.toContainText("11110");
    await expect(previewAlert).not.toContainText("kma / weather_short");

    // Branch B — 미리보기 해제 + run mode=now 제출.
    await page.getByLabel(/미리보기/).uncheck();
    await page.getByLabel("실행 모드").selectOption("now");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    expect(mocks.createBodies[0]).toMatchObject({
      run_mode: "now",
      reason: "admin ui request",
    });
    expect(mocks.createBodies[0]).not.toHaveProperty("operator");
  });

  test("row run-now는 queued/running canonical identity를 그대로 dispatch한다", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      initial: [
        // terminal 행에는 lifecycle mutation을 노출하지 않는다.
        makeRequest({
          request_id: DONE_REQUEST_ID,
          status: "done",
          finished_at: MOCK_NOW,
        }),
        makeRequest({
          request_id: RUNNING_REQUEST_ID,
          status: "running",
          started_at: MOCK_NOW,
        }),
        // active queued/running 행에는 cancel + run-now를 모두 노출한다.
        makeRequest({ request_id: QUEUED_REQUEST_ID, status: "queued" }),
      ],
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("요청 상태 필터").selectOption("done");

    const doneRow = page.getByRole("row", {
      name: new RegExp(DONE_REQUEST_ID.slice(0, 12)),
    });
    await expect(doneRow).toBeVisible();
    // done 행: cancel/run-now 모두 없음.
    await expect(doneRow.getByRole("button", { name: "취소" })).toHaveCount(0);
    await expect(
      doneRow.getByRole("button", { name: "즉시 실행" }),
    ).toHaveCount(0);

    await page.getByLabel("요청 상태 필터").selectOption("running");
    const runningRow = page.getByRole("row", {
      name: new RegExp(RUNNING_REQUEST_ID.slice(0, 12)),
    });
    await expect(runningRow).toBeVisible();
    await expect(
      runningRow.getByRole("button", { name: "즉시 실행" }),
    ).toBeVisible();
    await runningRow.getByRole("button", { name: "즉시 실행" }).click();
    await expect.poll(() => mocks.runNow).toBe(1);
    expect(mocks.runNowBodies[0]).toEqual({});
    const runningSuccessAlert = page
      .getByRole("status")
      .filter({ hasText: "즉시 실행 요청 완료" });
    await expect(runningSuccessAlert).toContainText("요청이 이미 실행 중입니다.");

    await page.getByLabel("요청 상태 필터").selectOption("queued");
    const queuedRow = page.getByRole("row", {
      name: new RegExp(QUEUED_REQUEST_ID.slice(0, 12)),
    });
    await expect(queuedRow).toBeVisible();
    await queuedRow.getByRole("button", { name: "즉시 실행" }).click();
    await expect.poll(() => mocks.runNow).toBe(2);
    expect(mocks.runNowBodies[1]).toEqual({});
    expect(mocks.runNowRecords[1]).toMatchObject({
      request_id: QUEUED_REQUEST_ID,
      job_id: JOB_ID,
      dispatch_requested_at: "2026-06-08T00:00:01.000Z",
      priority: 50,
      reason: "admin ui request",
      run_mode: "queued",
      status: "queued",
    });
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "즉시 실행 요청 완료" });
    await expect(successAlert).toContainText(
      "기존 요청의 즉시 dispatch를 요청했습니다.",
    );
    await expect(
      successAlert.getByRole("link", { name: QUEUED_REQUEST_ID }),
    ).toHaveAttribute(
      "href",
      `/admin/features/update-requests/${QUEUED_REQUEST_ID}`,
    );
    // dispatch 뒤에도 같은 queued 행과 identity가 유지된다.
    await expect(queuedRow).toBeVisible();
    await expect(
      queuedRow.getByRole("button", { name: "즉시 실행" }),
    ).toBeVisible();
    const listBeforeCancel = mocks.list;
    await queuedRow.getByRole("button", { name: "취소" }).click();

    await expect.poll(() => mocks.cancel).toBe(1);
    expect(mocks.cancelBodies[0]).toMatchObject({
      reason: "cancelled from admin ui",
    });
    const cancelSuccessAlert = page
      .getByRole("status")
      .filter({ hasText: "요청 취소 처리 결과" });
    await expect(cancelSuccessAlert).toContainText(QUEUED_REQUEST_ID);
    await expect.poll(() => mocks.list).toBeGreaterThan(listBeforeCancel);
    await expect(queuedRow).toHaveCount(0);
    await expect(cancelSuccessAlert).toContainText("원 요청 상태 cancelled");
    await expect(cancelSuccessAlert).not.toContainText("확인 중");
    await expect(cancelSuccessAlert).toContainText("취소 처리 상태 completed");
  });

  test("empty list: zero items -> empty message and 0 rows badge", async ({
    page,
  }) => {
    await mockFeatureUpdateRequests(page, { initial: [] });

    await page.goto("/admin/features/update-requests");

    // 목록 쿼리가 끝나기 전 절대단언 race를 막기 위해 empty 행이 렌더될 때까지 대기.
    await expect(page.getByText("요청이 없습니다.")).toBeVisible();
    await expect(page.getByText("0건")).toBeVisible();
  });

  test("list error: GET 500 -> 요청 목록 조회 실패 alert", async ({ page }) => {
    await page.route("**/v1/debug/etl/providers**", async (route) => {
      bffApiPath(route.request().url());
      await fulfillJson(route, {
        data: { providers: [] },
        meta: {
          duration_ms: 1,
          request_id: "e2e-feature-update-providers-error",
        },
      } satisfies ProvidersResponse);
    });
    await page.route(
      "**/v1/admin/features/update-requests**",
      async (route) => {
        const request = route.request();
        if (request.resourceType() === "document") {
          await route.continue();
          return;
        }
        const url = new URL(request.url());
        if (url.searchParams.has("_rsc")) {
          await route.continue();
          return;
        }
        await fulfillJson(route, { detail: "boom" }, 500);
      },
    );

    await page.goto("/admin/features/update-requests");

    // 목록 실패 배너는 create/preview/mutation 실패와 다른 제목을 쓴다.
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "요청 목록 조회 실패" });
    await expect(errorAlert).toBeVisible();
    // ApiClientError.message: "GET /v1/... 실패 (HTTP 500) ...".
    await expect(page.getByText(/HTTP 500/)).toBeVisible();
  });

  test("form validation errors: lon required + lat range + radius min block POST", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");

    await page.getByLabel("경도").fill("");
    await page.getByLabel("위도").fill("44");
    await page.getByLabel("반경(km)").fill("0.01");
    await page.getByLabel(/미리보기/).uncheck();
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(page.getByText("경도를 입력하세요.")).toBeVisible();
    await expect(
      page.getByText(
        "좌표는 대한민국 범위 안의 숫자로 입력하세요. 경도는 124~132, 위도는 33~39.5 사이입니다.",
      ),
    ).toBeVisible();
    await expect(page.getByText("반경은 0.1 이상이어야 합니다.")).toBeVisible();
    expect(mocks.create).toBe(0);
  });

  test("provider와 dataset filter가 모두 비면 제출을 차단한다", async ({ page }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");
    await page.getByLabel(/미리보기/).uncheck();
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(
      page.getByRole("alert").filter({
        hasText: "제공자 또는 데이터셋 키를 하나 이상 선택하세요.",
      }),
    ).toBeVisible();
    expect(mocks.create).toBe(0);
    expect(mocks.preview).toBe(0);
  });

  test("create API 422 -> 요청 생성 실패 alert + HTTP detail", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      createStatus: 422,
      createErrorBody: {
        detail: "radius_km must be less than or equal to 500",
      },
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("데이터셋 키").fill("mois_license_features_bulk");
    await page.getByLabel(/미리보기/).uncheck();
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "요청 생성 실패" });
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText("HTTP 422");
    await expect(errorAlert).toContainText("radius_km");
  });

  test("preview API 422 -> 미리보기 실패 alert", async ({ page }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      previewStatus: 422,
      previewErrorBody: { detail: "preview radius_km is invalid" },
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("데이터셋 키").fill("mois_license_features_bulk");
    await page.getByRole("button", { name: "미리보기" }).click();

    await expect.poll(() => mocks.preview).toBe(1);
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "미리보기 실패" });
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText("HTTP 422");
  });

  test("row -> detail deeplink: request column link href uses full id, text is shortId", async ({
    page,
  }) => {
    await mockFeatureUpdateRequests(page, {
      initial: [
        makeRequest({
          request_id: DONE_REQUEST_ID,
          status: "done",
          finished_at: MOCK_NOW,
        }),
      ],
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("요청 상태 필터").selectOption("all");

    const row = page.getByRole("row", {
      name: new RegExp(DONE_REQUEST_ID.slice(0, 12)),
    });
    await expect(row).toBeVisible();
    const link = row.getByRole("link");
    // href는 FULL id(표시 텍스트는 truncate되지만 링크 대상은 전체 id).
    await expect(link).toHaveAttribute(
      "href",
      `/admin/features/update-requests/${DONE_REQUEST_ID}`,
    );
    // 표시 텍스트는 shortId(첫 12자 + "...").
    await expect(link).toHaveText(`${DONE_REQUEST_ID.slice(0, 12)}...`);
  });
});
