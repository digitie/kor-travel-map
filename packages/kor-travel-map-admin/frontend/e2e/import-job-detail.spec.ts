import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/ops/import-jobs/[jobId]` 상세 — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.4).
 *
 * 임의 jobId는 빈 DB에서 404이므로 mocked-route 패턴으로 상세 GET / events GET /
 * cancel POST만 가로챈다(`**​/v1/ops/import-jobs/**`). 페이지 document·RSC·WS·
 * `/v1/ops/metrics` invalidation은 통과시킨다. mock body는 생성 OpenAPI 타입 바인딩.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 라이브 실행 검증은 Windows 런 필요.
 */

type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type OpsImportJobEventRecord =
  components["schemas"]["OpsImportJobEventRecord"];
type OpsImportJobResponse = components["schemas"]["OpsImportJobResponse"];
type OpsImportJobEventsListResponse =
  components["schemas"]["OpsImportJobEventsListResponse"];

const JOB_ID = "88888888-8888-4888-8888-888888888888";
const DETAIL_PATH = `/v1/ops/import-jobs/${JOB_ID}`;
const meta = { duration_ms: 1, request_id: "e2e-import-job-detail" };

function makeJob(
  overrides: Partial<OpsImportJobRecord> = {},
): OpsImportJobRecord {
  return {
    created_at: "2026-06-08T00:00:00.000Z",
    current_stage: "load",
    error_message: null,
    finished_at: null,
    heartbeat_at: "2026-06-08T00:01:00.000Z",
    job_id: JOB_ID,
    kind: "provider_sync",
    links: [
      { href: `/v1/ops/import-jobs/${JOB_ID}`, label: null, rel: "self" },
      {
        href: "/v1/admin/feature-update-requests",
        label: "update request",
        rel: "feature_update_request",
      },
    ],
    load_batch_id: "batch-001",
    parent_job_id: null,
    payload: { provider: "python-visitkorea-api", dataset_key: "festival" },
    progress: 42,
    source_checksum: null,
    started_at: "2026-06-08T00:00:30.000Z",
    status: "running",
    status_url: DETAIL_PATH,
    ...overrides,
  };
}

function makeEvent(
  overrides: Partial<OpsImportJobEventRecord> = {},
): OpsImportJobEventRecord {
  return {
    code: "ok",
    dataset_key: "festival",
    event_id: "evt-001",
    feature_id: null,
    job_id: JOB_ID,
    level: "info",
    message: "loaded 10 features",
    occurred_at: "2026-06-08T00:01:00.000Z",
    payload: { count: 10 },
    provider: "python-visitkorea-api",
    stage: "load",
    ...overrides,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockImportJob(
  page: Page,
  options: {
    initialStatus?: string;
    events?: OpsImportJobEventRecord[];
    detailStatus?: number;
  } = {},
) {
  const calls = { detail: 0, events: 0, cancel: 0 };
  let status = options.initialStatus ?? "running";
  const events = options.events ?? [makeEvent()];

  await page.route("**/v1/ops/import-jobs/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();

    if (method === "POST" && url.pathname === `${DETAIL_PATH}/cancel`) {
      calls.cancel += 1;
      status = "cancelled";
      const body: OpsImportJobResponse = {
        data: makeJob({ status, finished_at: "2026-06-08T00:02:00.000Z" }),
        meta,
      };
      await fulfillJson(route, body);
      return;
    }
    if (method === "GET" && url.pathname === `${DETAIL_PATH}/events`) {
      calls.events += 1;
      const body: OpsImportJobEventsListResponse = {
        data: { items: events },
        meta,
      };
      await fulfillJson(route, body);
      return;
    }
    if (method === "GET" && url.pathname === DETAIL_PATH) {
      calls.detail += 1;
      if (options.detailStatus && options.detailStatus >= 400) {
        await fulfillJson(route, { detail: "job_id 없음" }, options.detailStatus);
        return;
      }
      const body: OpsImportJobResponse = { data: makeJob({ status }), meta };
      await fulfillJson(route, body);
      return;
    }
    await route.continue();
  });

  return calls;
}

test.describe("/ops/import-jobs/[jobId]", () => {
  test("running 상세 render — Job/Events/Payload + status·progress", async ({
    page,
  }) => {
    await mockImportJob(page, { initialStatus: "running" });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(
      page.getByRole("heading", { level: 1, name: "Import job" }),
    ).toBeVisible();
    await expect(page.getByText("Job", { exact: true })).toBeVisible();
    await expect(page.getByText("Events", { exact: true })).toBeVisible();
    await expect(page.getByText("Payload", { exact: true })).toBeVisible();
    await expect(page.getByText("42%", { exact: true })).toBeVisible();
    // Events 테이블 컬럼 + 행 1건.
    await expect(
      page.getByRole("columnheader", { name: "message" }),
    ).toBeVisible();
    await expect(page.getByText("loaded 10 features")).toBeVisible();
  });

  test("event 없음 — empty state", async ({ page }) => {
    await mockImportJob(page, { initialStatus: "running", events: [] });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(page.getByText("event가 없습니다.")).toBeVisible();
  });

  test("cancel 가능 — queued/running에서 cancel 버튼 활성", async ({ page }) => {
    await mockImportJob(page, { initialStatus: "queued" });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(
      page.getByRole("button", { name: "cancel" }),
    ).toBeEnabled();
  });

  test("terminal(done) — cancel 버튼 비활성", async ({ page }) => {
    await mockImportJob(page, { initialStatus: "done" });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(
      page.getByRole("button", { name: "cancel" }),
    ).toBeDisabled();
  });

  test("cancel 액션 → cancel 요청됨 알림", async ({ page }) => {
    const calls = await mockImportJob(page, { initialStatus: "running" });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await page.getByPlaceholder("reason").fill("e2e cancel");
    await page.getByRole("button", { name: "cancel" }).click();
    await expect(page.getByText("cancel 요청됨")).toBeVisible();
    expect(calls.cancel).toBe(1);
  });

  test("404 — import job 조회 실패 alert", async ({ page }) => {
    await mockImportJob(page, { detailStatus: 404 });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(page.getByText("import job 조회 실패")).toBeVisible();
  });
});
