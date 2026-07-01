import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

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
type FeatureUpdateRequestCancelRequest =
  components["schemas"]["FeatureUpdateRequestCancelRequest"];
type FeatureUpdateRequestRunNowRequest =
  components["schemas"]["FeatureUpdateRequestRunNowRequest"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
// detail deeplink truncation을 검증할 수 있게 12자 초과 uuid를 쓴다(shortId는 12자+"...").
const DONE_REQUEST_ID = "aaaaaaaa-1111-4111-8111-111111111111";
const QUEUED_REQUEST_ID = "bbbbbbbb-2222-4222-8222-222222222222";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeRequest(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
  return {
    created_at: MOCK_NOW,
    dagster_run_id: null,
    dataset_keys: [],
    dry_run: false,
    error_message: null,
    finished_at: null,
    job_id: null,
    matched_scope: {},
    operator: "local-admin",
    priority: 50,
    providers: [],
    reason: "admin ui request",
    request_id: QUEUED_REQUEST_ID,
    run_mode: "queued",
    scope: { type: "center_radius", center: { lon: 126.978, lat: 37.5665 }, radius_km: 5 },
    scope_type: "center_radius",
    started_at: null,
    status: "queued",
    status_url: null,
    update_policy: {},
    updated_at: MOCK_NOW,
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
    data: record,
    meta: { duration_ms: 1, request_id: "e2e-feature-update-create" },
  };
}

interface FeatureUpdateMocks {
  /** create POST 호출 수(pathname === base). */
  create: number;
  /** run-now POST 호출 수(pathname endsWith /run-now). */
  runNow: number;
  /** cancel POST 호출 수(pathname endsWith /cancel). */
  cancel: number;
  /** GET list 호출 수(2초 폴링이 있으므로 create/mutation count만 정확하다). */
  list: number;
  createBodies: FeatureUpdateRequestCreateRequest[];
  runNowBodies: FeatureUpdateRequestRunNowRequest[];
  cancelBodies: FeatureUpdateRequestCancelRequest[];
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
  } = {},
): Promise<FeatureUpdateMocks> {
  let items = [...(options.initial ?? [])];
  const mocks: FeatureUpdateMocks = {
    create: 0,
    runNow: 0,
    cancel: 0,
    list: 0,
    createBodies: [],
    runNowBodies: [],
    cancelBodies: [],
  };
  const base = "/v1/admin/features/update-requests";

  await page.route("**/v1/admin/features/update-requests**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    // Next.js RSC prefetch 요청(?_rsc=...)은 mock하지 않고 흘려보낸다.
    if (url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }

    const method = request.method();

    if (method === "GET" && url.pathname === base) {
      mocks.list += 1;
      // status 파라미터: 없으면(=all) 전체, 있으면 해당 status만.
      const status = url.searchParams.get("status");
      const filtered = status
        ? items.filter((item) => item.status === status)
        : items;
      await fulfillJson(route, listResponse(filtered));
      return;
    }

    if (method === "POST" && url.pathname === base) {
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
      // dry-run preview는 request_id 없이 반환(actions 컬럼이 'dry-run' 텍스트 렌더).
      const created = body.dry_run
        ? makeRequest({
            request_id: null,
            dry_run: true,
            run_mode: body.run_mode,
            reason: body.reason,
            status: "done",
            scope: body.scope as FeatureUpdateRequestRecord["scope"],
            scope_type: "center_radius",
          })
        : makeRequest({
            request_id: `created-${mocks.create}-00000000-0000-4000-8000-000000000000`,
            dry_run: false,
            run_mode: body.run_mode,
            reason: body.reason,
            status: "queued",
            scope: body.scope as FeatureUpdateRequestRecord["scope"],
            scope_type: "center_radius",
          });
      // invalidateQueries refetch가 새 행을 보도록 list에 push.
      items = [created, ...items];
      await fulfillJson(route, createResponse(created));
      return;
    }

    if (method === "POST" && url.pathname.endsWith("/run-now")) {
      mocks.runNow += 1;
      mocks.runNowBodies.push(
        request.postDataJSON() as FeatureUpdateRequestRunNowRequest,
      );
      const requestId = url.pathname.split("/").at(-2) ?? "";
      const target =
        items.find((item) => item.request_id === requestId) ?? makeRequest();
      const requeued = makeRequest({
        ...target,
        request_id: requestId,
        status: "queued",
      });
      items = [
        requeued,
        ...items.filter((item) => item.request_id !== requestId),
      ];
      await fulfillJson(route, createResponse(requeued));
      return;
    }

    if (method === "POST" && url.pathname.endsWith("/cancel")) {
      mocks.cancel += 1;
      mocks.cancelBodies.push(
        request.postDataJSON() as FeatureUpdateRequestCancelRequest,
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
      await fulfillJson(route, createResponse(cancelled));
      return;
    }

    throw new Error(`Unhandled feature-update-requests route: ${method} ${url}`);
  });

  return mocks;
}

test.describe("admin/feature-update-requests list + create depth", () => {
  test("create queued request: POST fires queued+dry_run=false payload, success Alert, new row", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");

    // pre-fill 기본값(lon=126.9780, lat=37.5665, radius km=5) 확인.
    await expect(page.getByLabel("lon")).toHaveValue("126.9780");
    await expect(page.getByLabel("lat")).toHaveValue("37.5665");
    await expect(page.getByLabel("radius km")).toHaveValue("5");

    // native <input type=checkbox> dry-run을 해제(base-ui Checkbox gotcha 미적용).
    await page.getByLabel("dry-run").uncheck();
    await expect(page.getByLabel("dry-run")).not.toBeChecked();

    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    expect(mocks.createBodies[0]).toMatchObject({
      scope: {
        type: "center_radius",
        center: { lon: 126.978, lat: 37.5665 },
        radius_km: 5,
      },
      dry_run: false,
      run_mode: "queued",
      operator: "local-admin",
      reason: "admin ui request",
    });

    // 성공 Alert(role=status): request_id + status 노출.
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "요청 처리 완료" });
    await expect(successAlert).toBeVisible();
    await expect(successAlert).toContainText("queued");
    await expect(successAlert).toContainText("created-1");

    // 생성 후 list refetch가 새 queued 행을 보인다. 'all'로 바꿔도 보이도록 방어.
    await page.getByLabel("request status").selectOption("all");
    await expect(
      page.getByRole("row", { name: /created-1/ }),
    ).toBeVisible();
  });

  test("dry-run vs run-now kill switch: dry_run=true preview row, then run_mode=now create", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");

    // Branch A — dry-run(기본 checked) 그대로 제출.
    await expect(page.getByLabel("dry-run")).toBeChecked();
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    expect(mocks.createBodies[0]).toMatchObject({
      dry_run: true,
      run_mode: "queued",
      reason: "admin ui dry-run",
    });

    // request_id가 null인 dry-run preview 행은 actions 컬럼에 'dry-run' 텍스트만 렌더.
    await page.getByLabel("request status").selectOption("all");
    const dryRunCell = page.getByRole("cell", { name: "dry-run", exact: true });
    await expect(dryRunCell).toBeVisible();
    const dryRunRow = page.getByRole("row").filter({ has: dryRunCell });
    await expect(dryRunRow.getByRole("button", { name: "cancel" })).toHaveCount(0);
    await expect(dryRunRow.getByRole("button", { name: "run-now" })).toHaveCount(0);

    // Branch B — dry-run 해제 + run mode=now 제출.
    await page.getByLabel("dry-run").uncheck();
    await page.getByLabel("run mode").selectOption("now");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(2);
    expect(mocks.createBodies[1]).toMatchObject({
      dry_run: false,
      run_mode: "now",
      reason: "admin ui request",
    });
  });

  test("row run-now re-queues existing request (POST .../run-now)", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      initial: [
        // done 행: actions에 run-now만(cancel은 queued/running 전용).
        makeRequest({
          request_id: DONE_REQUEST_ID,
          status: "done",
          finished_at: MOCK_NOW,
        }),
        // queued 행: actions에 cancel + run-now 둘 다.
        makeRequest({ request_id: QUEUED_REQUEST_ID, status: "queued" }),
      ],
    });

    await page.goto("/admin/features/update-requests");
    await page.getByLabel("request status").selectOption("done");

    const doneRow = page.getByRole("row", {
      name: new RegExp(DONE_REQUEST_ID.slice(0, 12)),
    });
    await expect(doneRow).toBeVisible();
    // done 행: run-now 존재, cancel 없음.
    await expect(doneRow.getByRole("button", { name: "cancel" })).toHaveCount(0);
    await doneRow.getByRole("button", { name: "run-now" }).click();

    await expect.poll(() => mocks.runNow).toBe(1);
    expect(mocks.runNowBodies[0]).toMatchObject({
      reason: "run-now from admin ui",
    });

    // queued 행은 cancel + run-now 둘 다 노출 + cancel은 /cancel POST.
    await page.getByLabel("request status").selectOption("queued");
    const queuedRow = page.getByRole("row", {
      name: new RegExp(QUEUED_REQUEST_ID.slice(0, 12)),
    });
    await expect(queuedRow).toBeVisible();
    await expect(queuedRow.getByRole("button", { name: "run-now" })).toBeVisible();
    await queuedRow.getByRole("button", { name: "cancel" }).click();

    await expect.poll(() => mocks.cancel).toBe(1);
    expect(mocks.cancelBodies[0]).toMatchObject({
      error_message: "cancelled from admin ui",
    });
  });

  test("empty list: zero items -> empty message and 0 rows badge", async ({
    page,
  }) => {
    await mockFeatureUpdateRequests(page, { initial: [] });

    await page.goto("/admin/features/update-requests");

    // 목록 쿼리가 끝나기 전 절대단언 race를 막기 위해 empty 행이 렌더될 때까지 대기.
    await expect(page.getByText("요청이 없습니다.")).toBeVisible();
    await expect(page.getByText("0 rows")).toBeVisible();
  });

  test("list error: GET 500 -> destructive Alert 'request 처리 실패' with HTTP 500 message", async ({
    page,
  }) => {
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

    // 목록 실패 배너는 role=alert(destructive) + 'request 처리 실패'(CREATE 실패는 '요청 생성 실패').
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "request 처리 실패" });
    await expect(errorAlert).toBeVisible();
    // ApiClientError.message: "GET /v1/... 실패 (HTTP 500) ...".
    await expect(page.getByText(/HTTP 500/)).toBeVisible();
  });

  test("form validation errors: lon required + lat range + radius min block POST", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page);

    await page.goto("/admin/features/update-requests");

    await page.getByLabel("lon").fill("");
    await page.getByLabel("lat").fill("44");
    await page.getByLabel("radius km").fill("0.01");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect(page.getByText("경도(lon)는 필수입니다.")).toBeVisible();
    await expect(page.getByText("위도는 33~43 범위여야 합니다.")).toBeVisible();
    await expect(page.getByText("반경은 0.1 이상이어야 합니다.")).toBeVisible();
    expect(mocks.create).toBe(0);
  });

  test("create API 422 -> 요청 생성 실패 alert + HTTP detail", async ({
    page,
  }) => {
    const mocks = await mockFeatureUpdateRequests(page, {
      createStatus: 422,
      createErrorBody: { detail: "radius_km must be less than or equal to 500" },
    });

    await page.goto("/admin/features/update-requests");
    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => mocks.create).toBe(1);
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "요청 생성 실패" });
    await expect(errorAlert).toBeVisible();
    await expect(errorAlert).toContainText("HTTP 422");
    await expect(errorAlert).toContainText("radius_km");
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
    await page.getByLabel("request status").selectOption("all");

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
