import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/ops/import-jobs/[jobId]` 상세 — 깊이(mutation/filter/relation) 보강 spec.
 *
 * 기본 render/cancel-fired/404 smoke는 `import-job-detail.spec.ts`가 이미 커버한다.
 * 본 파일은 그 위에 (1) cancel POST payload(operator/reason) 검증, (2) event
 * timeline 멀티-컬럼 render, (3) level 필터 refetch, (4) terminal(failed)
 * error_message Alert + 입력 비활성, (5) terminal 폴링 중단, (6) relation link
 * rel별 분기, (7) link empty state — 7개 시나리오를 추가한다(중복 없음).
 *
 * 임의 jobId는 빈 DB에서 404이므로 mocked-route로 상세 GET / events GET /
 * cancel POST만 가로챈다(`**​/v1/ops/import-jobs/**`). RSC/document/WS는 통과시킨다.
 * 모든 mock body는 생성 OpenAPI 타입(`components["schemas"][...]`)에 바인딩해
 * 계약 drift를 tsc가 잡게 한다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 라이브 검증은 Windows 런 필요.
 */

type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type OpsImportJobLink = components["schemas"]["OpsImportJobLink"];
type OpsImportJobEventRecord =
  components["schemas"]["OpsImportJobEventRecord"];
type OpsImportJobResponse = components["schemas"]["OpsImportJobResponse"];
type OpsImportJobEventsListResponse =
  components["schemas"]["OpsImportJobEventsListResponse"];
type OpsImportJobCancelRequest =
  components["schemas"]["OpsImportJobCancelRequest"];

const JOB_ID = "99999999-9999-4999-8999-999999999999";
const PARENT_JOB_ID = "77777777-7777-4777-8777-777777777777";
const DETAIL_PATH = `/v1/ops/import-jobs/${JOB_ID}`;
const meta = { duration_ms: 1, request_id: "e2e-import-job-detail-actions" };

// import-job-detail-client.tsx의 DAGSTER_UI_URL 기본값. env override 시 호스트가
// 다를 수 있어 href 단언은 정확 문자열 대신 `/runs/<id>` 부분일치를 쓴다(risks 참조).
const DAGSTER_RUN_ID = "run-xyz";

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
    links: [{ href: DETAIL_PATH, label: null, rel: "self" }],
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

/**
 * 상세/events/cancel을 한 핸들러로 묶는다. events는 옵션 함수로 받아 level 필터
 * 분기를 시나리오별로 주입한다(미지정 시 고정 목록). cancel POST는 body를 capture해
 * operator/reason 검증을 가능하게 한다.
 */
async function mockImportJob(
  page: Page,
  options: {
    initialStatus?: string;
    job?: Partial<OpsImportJobRecord>;
    events?: OpsImportJobEventRecord[];
    eventsForLevel?: (level: string | null) => OpsImportJobEventRecord[];
  } = {},
) {
  const calls = { detail: 0, events: 0, cancel: 0 };
  const cancelBodies: OpsImportJobCancelRequest[] = [];
  const eventsLevels: Array<string | null> = [];
  let status = options.initialStatus ?? "running";
  const baseEvents = options.events ?? [makeEvent()];

  await page.route("**/v1/ops/import-jobs/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();

    if (method === "POST" && url.pathname === `${DETAIL_PATH}/cancel`) {
      calls.cancel += 1;
      cancelBodies.push(
        (request.postDataJSON() ?? {}) as OpsImportJobCancelRequest,
      );
      status = "cancelled";
      const body: OpsImportJobResponse = {
        data: makeJob({
          ...options.job,
          status,
          finished_at: "2026-06-08T00:02:00.000Z",
        }),
        meta,
      };
      await fulfillJson(route, body);
      return;
    }

    if (method === "GET" && url.pathname === `${DETAIL_PATH}/events`) {
      calls.events += 1;
      const level = url.searchParams.get("level");
      eventsLevels.push(level);
      const items = options.eventsForLevel
        ? options.eventsForLevel(level)
        : baseEvents;
      const body: OpsImportJobEventsListResponse = {
        data: { items },
        meta,
      };
      await fulfillJson(route, body);
      return;
    }

    if (method === "GET" && url.pathname === DETAIL_PATH) {
      calls.detail += 1;
      const body: OpsImportJobResponse = {
        data: makeJob({ ...options.job, status }),
        meta,
      };
      await fulfillJson(route, body);
      return;
    }

    await route.continue();
  });

  return { calls, cancelBodies, eventsLevels };
}

test.describe("/ops/import-jobs/[jobId] — actions/depth", () => {
  test("cancel 폼 — running에서 reason 전송 + POST body 검증 + 성공 Alert", async ({
    page,
  }) => {
    const { calls, cancelBodies } = await mockImportJob(page, {
      initialStatus: "running",
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await page.getByPlaceholder("reason").fill("e2e cancel");
    await page.getByRole("button", { name: "cancel" }).click();

    await expect.poll(() => calls.cancel).toBe(1);
    // handleCancel은 operator="admin-ui", reason=cancelReason.trim()||undefined로 보낸다.
    expect(cancelBodies[0]).toMatchObject({
      operator: "admin-ui",
      reason: "e2e cancel",
    });

    // 성공 Alert: title "cancel 요청됨" + 본문 `${status} · ${shortId(job_id)}`.
    // 성공(default variant) Alert는 role=status(polite)다 — destructive만 role=alert.
    await expect(page.getByText("cancel 요청됨")).toBeVisible();
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "cancel 요청됨" });
    await expect(successAlert).toContainText("cancelled");
    await expect(successAlert).toContainText(JOB_ID.slice(0, 12));

    // cancel 후 detail이 cancelled로 바뀌어 cancel 버튼이 다시 비활성(부수 검증).
    await expect(page.getByRole("button", { name: "cancel" })).toBeDisabled();
  });

  test("cancel 폼 — reason 공란이면 reason 미포함으로 전송", async ({ page }) => {
    const { calls, cancelBodies } = await mockImportJob(page, {
      initialStatus: "running",
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    // reason 입력 없이 바로 cancel → cancelReason.trim()||undefined === undefined.
    await page.getByRole("button", { name: "cancel" }).click();

    await expect.poll(() => calls.cancel).toBe(1);
    expect(cancelBodies[0]).toMatchObject({ operator: "admin-ui" });
    expect(cancelBodies[0]?.reason ?? undefined).toBeUndefined();
  });

  test("event timeline — 다건이 time/level/stage/code/message/payload 컬럼으로 렌더", async ({
    page,
  }) => {
    const events: OpsImportJobEventRecord[] = [
      makeEvent({
        code: "extract_begin",
        event_id: "evt-extract",
        level: "info",
        message: "extract started",
        stage: "extract",
      }),
      makeEvent({
        code: "load_done",
        event_id: "evt-load",
        level: "warning",
        message: "loaded 10 features",
        stage: "load",
      }),
      makeEvent({
        code: "load_fail",
        event_id: "evt-error",
        level: "error",
        message: "row rejected",
        payload: { reason: "bad geometry" },
        stage: null,
      }),
    ];
    await mockImportJob(page, { initialStatus: "running", events });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    // 6개 컬럼헤더가 모두 렌더(기존 spec은 message 1개만 확인).
    for (const column of ["time", "level", "stage", "code", "message", "payload"]) {
      await expect(
        page.getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }

    // 각 event message 가시.
    await expect(page.getByText("extract started")).toBeVisible();
    await expect(page.getByText("loaded 10 features")).toBeVisible();
    await expect(page.getByText("row rejected")).toBeVisible();

    // error level event는 StatusBadge(destructive)로 "error" 텍스트 노출.
    const errorRow = page.getByRole("row", { name: /row rejected/ });
    await expect(errorRow.getByText("error", { exact: true })).toBeVisible();
    // stage=null event row는 셀에 "-" 렌더.
    await expect(errorRow.getByText("-", { exact: true })).toBeVisible();

    // Events 카드 CardDescription의 row 카운트가 mock 건수와 일치.
    await expect(page.getByText("3 rows · idle")).toBeVisible();
  });

  test("event level 필터 — error 선택 시 ?level=error로 refetch", async ({
    page,
  }) => {
    const errorEvent = makeEvent({
      code: "load_fail",
      event_id: "evt-error",
      level: "error",
      message: "row rejected",
      stage: "load",
    });
    const infoEvent = makeEvent({
      code: "load_done",
      event_id: "evt-info",
      level: "info",
      message: "loaded 10 features",
      stage: "load",
    });
    const { eventsLevels } = await mockImportJob(page, {
      initialStatus: "running",
      eventsForLevel: (level) =>
        level === "error" ? [errorEvent] : [errorEvent, infoEvent],
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    // 초기(all)에는 level 파라미터가 없다(useImportJobEvents level===undefined).
    await expect(page.getByText("loaded 10 features")).toBeVisible();
    await expect.poll(() => eventsLevels.includes(null)).toBe(true);

    await page.getByLabel("event level").selectOption("error");

    // level=error 쿼리로 재호출되고 error 이벤트만 남는다.
    await expect.poll(() => eventsLevels.includes("error")).toBe(true);
    await expect(page.getByText("row rejected")).toBeVisible();
    await expect(page.getByText("loaded 10 features")).toHaveCount(0);
  });

  test("terminal(failed) — cancel 비활성 + error_message Alert", async ({
    page,
  }) => {
    await mockImportJob(page, {
      initialStatus: "failed",
      job: {
        error_message: "provider timeout",
        finished_at: "2026-06-08T00:05:00.000Z",
      },
      events: [],
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    // canCancel=false → cancel 버튼 + reason 입력 모두 비활성.
    await expect(page.getByRole("button", { name: "cancel" })).toBeDisabled();
    await expect(page.getByPlaceholder("reason")).toBeDisabled();

    // Cancel 카드 CardDescription이 "terminal".
    await expect(page.getByText("terminal", { exact: true })).toBeVisible();

    // Payload 카드 하단 error_message Alert: title "error" + description.
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "provider timeout" });
    await expect(errorAlert).toContainText("error");
    await expect(errorAlert).toContainText("provider timeout");
  });

  test("terminal(done) — detail GET 폴링 중단(1회 유지)", async ({ page }) => {
    // useImportJob refetchInterval는 queued/running이 아니면 false → done이면 폴링 없음.
    // events는 refetchInterval=5_000로 terminal 무관 폴링하므로 detail 카운트만 단언.
    const { calls } = await mockImportJob(page, {
      initialStatus: "done",
      events: [],
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(page.getByRole("button", { name: "cancel" })).toBeDisabled();
    await expect.poll(() => calls.detail).toBeGreaterThanOrEqual(1);

    // 안정 윈도우 동안 detail이 추가 폴링되지 않음을 확인(refetchInterval=false).
    // RISK: 시간 기반이라 flaky 가능 — running 대조군 없이 detail 카운트만 본다.
    const baseline = calls.detail;
    await expect
      .poll(() => calls.detail, { intervals: [500, 500, 500, 500], timeout: 4_000 })
      .toBe(baseline);
  });

  test("relation links — rel별 internal/external/plain 분기", async ({ page }) => {
    const links: OpsImportJobLink[] = [
      { href: DETAIL_PATH, label: null, rel: "self" },
      {
        href: `/v1/ops/import-jobs/${PARENT_JOB_ID}`,
        label: null,
        rel: "parent_job",
      },
      {
        href: "/v1/admin/load-batches/batch-001",
        label: null,
        rel: "load_batch",
      },
      {
        href: `/v1/ops/dagster/runs/${DAGSTER_RUN_ID}`,
        label: null,
        rel: "dagster_run",
      },
      { href: `${DETAIL_PATH}/events`, label: null, rel: "events" },
      {
        href: "/v1/admin/feature-update-requests",
        label: "update request",
        rel: "feature_update_request",
      },
    ];
    await mockImportJob(page, {
      initialStatus: "running",
      job: { links, load_batch_id: "batch-001", parent_job_id: PARENT_JOB_ID },
      events: [],
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(page.getByText("Links", { exact: true })).toBeVisible();
    // relation 링크는 Links 카드 안에서만 본다. label "update request"는 admin-shell
    // top-nav "Update requests"와 접근명이 겹치므로(STRICT-MODE) 카드로 범위를 좁힌다.
    const linksCard = page
      .locator('[data-slot="card"]')
      .filter({ has: page.getByRole("heading", { name: "Links", exact: true }) });
    // self rel은 visibleLinks에서 제외 → 링크/카드 없음.
    await expect(
      linksCard.getByRole("link", { name: "self", exact: true }),
    ).toHaveCount(0);

    // parent_job: internal Link, href에 /ops/import-jobs/ 포함.
    const parentLink = linksCard.getByRole("link", { name: /parent_job/ });
    await expect(parentLink).toHaveAttribute("href", /\/ops\/import-jobs\//);

    // load_batch: internal Link, /v1 stripped → /admin/load-batches/batch-001.
    const loadBatchLink = linksCard.getByRole("link", { name: /load_batch/ });
    await expect(loadBatchLink).toHaveAttribute(
      "href",
      "/admin/load-batches/batch-001",
    );

    // dagster_run: external anchor(target=_blank, rel=noreferrer), href에 /runs/run-xyz.
    const dagsterLink = linksCard.getByRole("link", { name: /dagster_run/ });
    await expect(dagsterLink).toHaveAttribute("target", "_blank");
    await expect(dagsterLink).toHaveAttribute("rel", "noreferrer");
    await expect(dagsterLink).toHaveAttribute(
      "href",
      new RegExp(`/runs/${DAGSTER_RUN_ID}$`),
    );

    // feature_update_request: label "update request"가 곧 anchor 접근명.
    const updateLink = linksCard.getByRole("link", { name: "update request" });
    await expect(updateLink).toHaveAttribute(
      "href",
      "/admin/feature-update-requests",
    );

    // events rel은 plain div(링크 아님) — rel 텍스트는 보이지만 link role 부재.
    await expect(linksCard.getByText("events", { exact: true })).toBeVisible();
    await expect(
      linksCard.getByRole("link", { name: /events/ }),
    ).toHaveCount(0);

    // Links CardDescription `${visibleLinks.length} related` = self 제외 5건.
    await expect(page.getByText("5 related")).toBeVisible();
  });

  test("links 없음 — self만 있으면 empty state", async ({ page }) => {
    await mockImportJob(page, {
      initialStatus: "running",
      job: { links: [{ href: DETAIL_PATH, label: null, rel: "self" }] },
      events: [],
    });
    await page.goto(`/ops/import-jobs/${JOB_ID}`);

    await expect(page.getByText("Links", { exact: true })).toBeVisible();
    await expect(page.getByText("연결 링크가 없습니다.")).toBeVisible();
    await expect(page.getByText("0 related")).toBeVisible();
  });
});
