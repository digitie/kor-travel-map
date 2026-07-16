import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { makePipelineCancellationResponse } from "./pipeline-cancellation-fixture";

/**
 * `/admin/features/update-requests/[requestId]` 상세 — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.3).
 *
 * 임의 requestId는 빈 DB에서 404가 되므로, `admin-ops.spec.ts`와 같은 mocked-route
 * 패턴으로 상세 GET / cancel / run-now만 가로채고(`**​/v1/admin/features/update-requests/**`),
 * 페이지 document·RSC·WS(`/v1/ops/live`)는 그대로 통과시킨다. mock body는 생성된
 * OpenAPI 타입에 바인딩해 계약 drift를 컴파일 단계에서 잡는다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다(`playwright.config.ts`). 본 spec은
 * 실 컴포넌트 인벤토리 기준으로 작성됐고 라이브 실행 검증은 Windows 런이 필요하다.
 */

type FeatureUpdateRequestRecord =
  components["schemas"]["FeatureUpdateRequestRecord"];
type FeatureUpdateRequestDetailResponse =
  components["schemas"]["FeatureUpdateRequestDetailResponse"];
type FeatureUpdateRequestMutationResponse =
  components["schemas"]["FeatureUpdateRequestMutationResponse"];
type FeatureUpdateStatus = FeatureUpdateRequestRecord["status"];
type ScopeDispatchFeatureUpdateRequestRecord = FeatureUpdateRequestRecord & {
  requested_sync_scope: string | null;
  effective_sync_scope: string | null;
  dispatch_requested_at: string | null;
};

const REQUEST_ID = "66666666-6666-4666-8666-666666666666";
const JOB_ID = "77777777-7777-4777-8777-777777777777";
const DETAIL_PATH = `/v1/admin/features/update-requests/${REQUEST_ID}`;

function makeUpdateRequest(
  overrides: Partial<ScopeDispatchFeatureUpdateRequestRecord> = {},
): ScopeDispatchFeatureUpdateRequestRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    dagster_run_id: "dagster-run-fur-001",
    dataset_keys: ["festival_open_api"],
    dispatch_requested_at: null,
    effective_sync_scope: null,
    error_message: null,
    finished_at: null,
    job_id: JOB_ID,
    matched_scope: { feature_count: 1, sigungu_codes: ["11110"] },
    operator: "e2e-authenticated-admin",
    priority: 100,
    providers: ["python-visitkorea-api"],
    reason: "e2e",
    requested_sync_scope: null,
    request_id: REQUEST_ID,
    run_mode: "queued",
    scope: {
      type: "center_radius",
      center: { lon: 126.978, lat: 37.5665 },
      radius_km: 5,
    },
    scope_type: "center_radius",
    status: "queued",
    status_url: `/v1/admin/features/update-requests/${REQUEST_ID}`,
    started_at: null,
    update_policy: { mode: "refresh_existing" },
    generation: 1,
    ...overrides,
  };
}

const meta = { duration_ms: 1, request_id: "e2e-fur-detail" };

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

/**
 * 상세 GET / cancel / run-now를 가로챈다. cancel은 원 요청 상태를 바꾸고,
 * run-now는 같은 canonical 요청의 즉시 dispatch 완료를 200으로 반환한다.
 */
async function mockUpdateRequest(
  page: Page,
  options: { initialStatus?: FeatureUpdateStatus; detailStatus?: number } = {},
) {
  const calls: {
    detail: number;
    cancel: number;
    runNow: number;
    runNowJobId: string | null;
    runNowRequestId: string | null;
  } = {
    detail: 0,
    cancel: 0,
    runNow: 0,
    runNowJobId: null,
    runNowRequestId: null,
  };
  let status = options.initialStatus ?? "queued";

  await page.route(
    "**/v1/admin/features/update-requests/**",
    async (route) => {
      const request = route.request();
      const pathname = bffApiPath(request.url());
      const method = request.method();

      if (method === "POST" && pathname === `${DETAIL_PATH}/cancel`) {
        calls.cancel += 1;
        status = "cancelled";
        const body = makePipelineCancellationResponse({
          rootKind: "update_request",
          rootId: REQUEST_ID,
          initialStatus: options.initialStatus ?? "queued",
          reason: "cancelled from feature update request detail",
          members: [{ jobId: JOB_ID }],
        });
        await fulfillJson(route, body);
        return;
      }
      if (method === "POST" && pathname === `${DETAIL_PATH}/run-now`) {
        calls.runNow += 1;
        calls.runNowJobId = JOB_ID;
        calls.runNowRequestId = REQUEST_ID;
        const body: FeatureUpdateRequestMutationResponse = {
          data: makeUpdateRequest({
            request_id: REQUEST_ID,
            job_id: JOB_ID,
            dispatch_requested_at: "2026-06-08T00:00:01.000Z",
            run_mode: "queued",
            status: "queued",
            status_url: `/v1/admin/features/update-requests/${REQUEST_ID}`,
          }),
          meta,
        };
        await fulfillJson(route, body);
        return;
      }
      if (method === "GET" && pathname === DETAIL_PATH) {
        calls.detail += 1;
        if (options.detailStatus && options.detailStatus >= 400) {
          await fulfillJson(
            route,
            { detail: "request_id 없음" },
            options.detailStatus,
          );
          return;
        }
        const body: FeatureUpdateRequestDetailResponse = {
          data: makeUpdateRequest({ status }),
          meta,
        };
        await fulfillJson(route, body);
        return;
      }
      await route.continue();
    },
  );

  return calls;
}

test.describe("/admin/features/update-requests/[requestId]", () => {
  test("queued 상세 render — scope/policy + cancel + run-now 노출", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "갱신 요청 상세" }),
    ).toBeVisible();
    await expect(page.getByText("스코프", { exact: true })).toBeVisible();
    await expect(page.getByText("매칭된 스코프", { exact: true })).toBeVisible();
    await expect(page.getByText("정책", { exact: true })).toBeVisible();
    await expect(page.getByText("실행 세대", { exact: true })).toBeVisible();
    // job 셀은 import-job 상세로 deeplink.
    await expect(
      page.getByRole("link", { name: /77777777/ }),
    ).toHaveAttribute("href", `/ops/import-jobs/${JOB_ID}`);
    await expect(page.getByRole("button", { name: "취소" })).toBeVisible();
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeVisible();
  });

  test("terminal(done) — cancel과 run-now 모두 숨김", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "done" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "갱신 요청 상세" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "취소" })).toBeHidden();
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeHidden();
  });

  test("running — cancel과 run-now 노출", async ({ page }) => {
    await mockUpdateRequest(page, { initialStatus: "running" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(page.getByRole("button", { name: "취소" })).toBeVisible();
    await expect(page.getByRole("button", { name: "즉시 실행" })).toBeVisible();
  });

  test("cancel 액션 → 성공 re-fetch 후 cancel 버튼 사라짐", async ({ page }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "취소" });
    await expect(cancel).toBeVisible();
    await cancel.click();
    // cancel 성공 → status=cancelled → invalidate → re-fetch → canCancel=false.
    await expect(cancel).toBeHidden();
    expect(calls.cancel).toBe(1);
  });

  test("run-now 액션 → 같은 canonical 요청 dispatch 완료", async ({ page }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "즉시 실행" });
    await expect(runNow).toBeVisible();
    await runNow.click();
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "즉시 실행 요청 완료" });
    await expect(
      successAlert.getByRole("link", { name: REQUEST_ID }),
    ).toHaveAttribute(
      "href",
      `/admin/features/update-requests/${REQUEST_ID}`,
    );
    await expect(successAlert).toContainText(
      "기존 요청의 즉시 dispatch를 요청했습니다.",
    );
    await expect(runNow).toBeVisible();
    await expect(page.getByText("대기", { exact: true })).toBeVisible();
    expect(calls.runNow).toBe(1);
    expect(calls.runNowRequestId).toBe(REQUEST_ID);
    expect(calls.runNowJobId).toBe(JOB_ID);
  });

  test("404 — request 조회 실패 alert", async ({ page }) => {
    await mockUpdateRequest(page, { detailStatus: 404 });
    await page.goto(`/admin/features/update-requests/${REQUEST_ID}`);

    await expect(page.getByText("요청 조회 실패")).toBeVisible();
  });
});
