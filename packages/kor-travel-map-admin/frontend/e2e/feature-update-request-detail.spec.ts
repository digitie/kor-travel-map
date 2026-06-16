import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/admin/feature-update-requests/[requestId]` 상세 — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.3).
 *
 * 임의 requestId는 빈 DB에서 404가 되므로, `admin-ops.spec.ts`와 같은 mocked-route
 * 패턴으로 상세 GET / cancel / run-now만 가로채고(`**​/v1/admin/feature-update-requests/**`),
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
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];

const REQUEST_ID = "66666666-6666-4666-8666-666666666666";
const JOB_ID = "77777777-7777-4777-8777-777777777777";
const DETAIL_PATH = `/v1/admin/feature-update-requests/${REQUEST_ID}`;

function makeUpdateRequest(
  overrides: Partial<FeatureUpdateRequestRecord> = {},
): FeatureUpdateRequestRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    dagster_run_id: "dagster-run-fur-001",
    dataset_keys: ["festival_open_api"],
    dry_run: true,
    job_id: JOB_ID,
    matched_scope: { sido_code: "11" },
    operator: "local-admin",
    priority: 100,
    providers: ["python-visitkorea-api"],
    reason: "e2e",
    request_id: REQUEST_ID,
    run_mode: "queued",
    scope: { kind: "sido", sido_code: "11" },
    scope_type: "sido",
    status: "queued",
    update_policy: { mode: "upsert" },
    updated_at: "2026-06-08T00:05:00.000Z",
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
 * 상세 GET / cancel / run-now를 가로챈다. cancel·run-now가 도착하면 이후 상세 GET이
 * 반환할 status를 갈아끼워, 성공 후 re-fetch로 액션 가시성이 바뀌는 것까지 검증한다.
 */
async function mockUpdateRequest(
  page: Page,
  options: { initialStatus?: string; detailStatus?: number } = {},
) {
  const calls = { detail: 0, cancel: 0, runNow: 0 };
  let status = options.initialStatus ?? "queued";

  await page.route(
    "**/v1/admin/feature-update-requests/**",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();

      if (method === "POST" && url.pathname === `${DETAIL_PATH}/cancel`) {
        calls.cancel += 1;
        status = "cancelled";
        const body: FeatureUpdateRequestCreateResponse = {
          data: makeUpdateRequest({ status }),
          meta,
        };
        await fulfillJson(route, body);
        return;
      }
      if (method === "POST" && url.pathname === `${DETAIL_PATH}/run-now`) {
        calls.runNow += 1;
        status = "running";
        const body: FeatureUpdateRequestCreateResponse = {
          data: makeUpdateRequest({ status, run_mode: "now" }),
          meta,
        };
        await fulfillJson(route, body, 201);
        return;
      }
      if (method === "GET" && url.pathname === DETAIL_PATH) {
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

test.describe("/admin/feature-update-requests/[requestId]", () => {
  test("queued 상세 render — scope/policy + cancel + run-now 노출", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update request" }),
    ).toBeVisible();
    await expect(page.getByText("Scope", { exact: true })).toBeVisible();
    await expect(page.getByText("Matched scope", { exact: true })).toBeVisible();
    await expect(page.getByText("Policy", { exact: true })).toBeVisible();
    await expect(page.getByText("dry-run", { exact: true })).toBeVisible();
    // job 셀은 import-job 상세로 deeplink.
    await expect(
      page.getByRole("link", { name: /77777777/ }),
    ).toHaveAttribute("href", `/ops/import-jobs/${JOB_ID}`);
    await expect(page.getByRole("button", { name: "cancel" })).toBeVisible();
    await expect(page.getByRole("button", { name: "run-now" })).toBeVisible();
  });

  test("terminal(done) — cancel 숨김, run-now는 유지(재큐잉)", async ({
    page,
  }) => {
    await mockUpdateRequest(page, { initialStatus: "done" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feature update request" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "cancel" })).toBeHidden();
    await expect(page.getByRole("button", { name: "run-now" })).toBeVisible();
  });

  test("running — cancel 노출, run-now 숨김", async ({ page }) => {
    await mockUpdateRequest(page, { initialStatus: "running" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(page.getByRole("button", { name: "cancel" })).toBeVisible();
    await expect(page.getByRole("button", { name: "run-now" })).toBeHidden();
  });

  test("cancel 액션 → 성공 re-fetch 후 cancel 버튼 사라짐", async ({ page }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const cancel = page.getByRole("button", { name: "cancel" });
    await expect(cancel).toBeVisible();
    await cancel.click();
    // cancel 성공 → status=cancelled → invalidate → re-fetch → canCancel=false.
    await expect(cancel).toBeHidden();
    expect(calls.cancel).toBe(1);
  });

  test("run-now 액션 → POST /run-now(201) 수신", async ({ page }) => {
    const calls = await mockUpdateRequest(page, { initialStatus: "queued" });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    const runNow = page.getByRole("button", { name: "run-now" });
    await expect(runNow).toBeVisible();
    await runNow.click();
    // run-now 성공 → status=running → re-fetch → run-now 숨김(=처리됨).
    await expect(runNow).toBeHidden();
    expect(calls.runNow).toBe(1);
  });

  test("404 — request 조회 실패 alert", async ({ page }) => {
    await mockUpdateRequest(page, { detailStatus: 404 });
    await page.goto(`/admin/feature-update-requests/${REQUEST_ID}`);

    await expect(page.getByText("request 조회 실패")).toBeVisible();
  });
});
