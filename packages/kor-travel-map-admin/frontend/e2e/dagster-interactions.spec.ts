import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// 이 파일은 dagster.spec.ts smoke(제목/카드/embed 렌더)에 더해 운영자 상호작용 depth만 보탠다:
//   nux-seen 자동 POST(effect) · empty-state · FAILURE run 자동선택 드릴다운 ·
//   schedule tick 실패→run-id 선택 · webserver unavailable 배너 · summary 503 · run-detail not_found.
type DagsterSummaryData = components["schemas"]["DagsterSummaryData"];
type DagsterSummaryResponse = components["schemas"]["DagsterSummaryResponse"];
type DagsterRunSummary = components["schemas"]["DagsterRunSummary"];
type DagsterRepository = components["schemas"]["DagsterRepository"];
type DagsterSchedule = components["schemas"]["DagsterSchedule"];
type DagsterInstigationTick =
  components["schemas"]["DagsterInstigationTick"];
type DagsterRunEvent = components["schemas"]["DagsterRunEvent"];
type DagsterRunDetailData = components["schemas"]["DagsterRunDetailData"];
type DagsterRunDetailResponse =
  components["schemas"]["DagsterRunDetailResponse"];
type DagsterNuxSeenData = components["schemas"]["DagsterNuxSeenData"];
type DagsterNuxSeenResponse =
  components["schemas"]["DagsterNuxSeenResponse"];
type Meta = components["schemas"]["Meta"];

const MOCK_NOW = "2026-06-16T00:00:00.000Z";
const DAGSTER_URL = "http://127.0.0.1:12702";
const GRAPHQL_URL = "http://127.0.0.1:12702/graphql";

function meta(requestId = "e2e-dagster"): Meta {
  return { duration_ms: 1, request_id: requestId };
}

function makeRunSummary(
  overrides: Partial<DagsterRunSummary> = {},
): DagsterRunSummary {
  return {
    end_time: 1_750_000_100,
    job_name: "kma_weather_job",
    run_id: "dagster-run-success-001",
    start_time: 1_750_000_000,
    status: "SUCCESS",
    tags: {},
    update_time: 1_750_000_100,
    ...overrides,
  };
}

function makeRunEvent(
  overrides: Partial<DagsterRunEvent> = {},
): DagsterRunEvent {
  return {
    dagster_event_type: "STEP_SUCCESS",
    error: null,
    event_type: "ExecutionStepSuccessEvent",
    level: "INFO",
    message: "step ok",
    step_id: "load_features",
    timestamp: "1750000100",
    ...overrides,
  };
}

function makeTick(
  overrides: Partial<DagsterInstigationTick> = {},
): DagsterInstigationTick {
  return {
    cursor: null,
    end_timestamp: 1_750_000_050,
    error: null,
    run_ids: [],
    run_keys: [],
    skip_reason: null,
    status: "SUCCESS",
    tick_id: "tick-1",
    timestamp: 1_750_000_000,
    ...overrides,
  };
}

function makeSchedule(
  overrides: Partial<DagsterSchedule> = {},
): DagsterSchedule {
  return {
    cron_schedule: "0 6 * * *",
    execution_timezone: "Asia/Seoul",
    name: "weather_daily",
    recent_ticks: [],
    status: "running",
    ...overrides,
  };
}

function makeRepository(
  overrides: Partial<DagsterRepository> = {},
): DagsterRepository {
  return {
    asset_count: 3,
    asset_groups: [
      { asset_count: 2, assets: ["kma_weather", "kma_station"], group_name: "weather" },
    ],
    jobs: [{ is_job: true, name: "kma_weather_job" }],
    location_name: "kortravelmap_dagster",
    name: "__repository__",
    schedules: [],
    sensors: [],
    ...overrides,
  };
}

function makeSummary(
  overrides: Partial<DagsterSummaryData> = {},
): DagsterSummaryResponse {
  const recentRuns = overrides.recent_runs ?? [makeRunSummary()];
  const failureCount = recentRuns.filter((run) => run.status === "FAILURE").length;
  const data: DagsterSummaryData = {
    asset_count: 3,
    checked_at: MOCK_NOW,
    dagster_url: DAGSTER_URL,
    errors: [],
    graphql_url: GRAPHQL_URL,
    job_count: 1,
    recent_runs: recentRuns,
    repositories: [makeRepository()],
    repository_count: 1,
    run_counts: { FAILURE: failureCount, SUCCESS: recentRuns.length - failureCount },
    schedule_count: 1,
    sensor_count: 0,
    status: "ok",
    version: "1.7.0",
    ...overrides,
  };
  return { data, meta: meta("e2e-dagster-summary") };
}

function makeNuxSeen(
  overrides: Partial<DagsterNuxSeenData> = {},
): DagsterNuxSeenResponse {
  const data: DagsterNuxSeenData = {
    checked_at: MOCK_NOW,
    dagster_url: DAGSTER_URL,
    errors: [],
    graphql_url: GRAPHQL_URL,
    seen: true,
    status: "ok",
    ...overrides,
  };
  return { data, meta: meta("e2e-dagster-nux-seen") };
}

function makeRunDetail(
  overrides: Partial<DagsterRunDetailData> = {},
): DagsterRunDetailResponse {
  const data: DagsterRunDetailData = {
    checked_at: MOCK_NOW,
    dagster_url: DAGSTER_URL,
    errors: [],
    event_cursor: null,
    event_has_more: false,
    events: [],
    graphql_url: GRAPHQL_URL,
    run: makeRunSummary(),
    status: "ok",
    ...overrides,
  };
  return { data, meta: meta("e2e-dagster-run-detail") };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

interface DagsterRouteOptions {
  summary: () => DagsterSummaryResponse | { body: unknown; status: number };
  // run-detail handler가 등록되면 자동 fetch도 mock된다. 등록 안 하면(빈 목록 등)
  // 그 라우트는 절대 호출되지 않아야 한다(null selection 검증).
  runDetail?: (runId: string, after: string | null) => DagsterRunDetailResponse;
  // nux-seen을 등록하지 않으면 negative control(POST가 절대 안 오는 status≠ok 경로)에서
  // 미등록 그대로 두고 카운터로 0을 검증한다.
  mockNuxSeen?: boolean;
}

interface DagsterRequestCounters {
  nuxSeen: number;
  runDetailUrls: string[];
}

async function mockDagster(
  page: Page,
  options: DagsterRouteOptions,
): Promise<DagsterRequestCounters> {
  const counters: DagsterRequestCounters = { nuxSeen: 0, runDetailUrls: [] };

  await page.route("**/v1/ops/dagster/summary**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname !== "/v1/ops/dagster/summary") {
      await route.continue();
      return;
    }
    const result = options.summary();
    if ("body" in result && "status" in result) {
      await fulfillJson(route, result.body, result.status);
      return;
    }
    await fulfillJson(route, result);
  });

  if (options.mockNuxSeen ?? true) {
    await page.route("**/v1/ops/dagster/nux-seen**", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      const url = new URL(route.request().url());
      if (url.pathname !== "/v1/ops/dagster/nux-seen") {
        await route.continue();
        return;
      }
      counters.nuxSeen += 1;
      // postJson('/v1/ops/dagster/nux-seen')는 body 없이 보낸다(Content-Type 미설정).
      expect(route.request().postData()).toBeNull();
      expect(route.request().headers()["content-type"]).toBeUndefined();
      await fulfillJson(route, makeNuxSeen());
    });
  }

  if (options.runDetail) {
    const runDetail = options.runDetail;
    await page.route("**/v1/ops/dagster/runs/**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/v1/ops/dagster/runs/")) {
        await route.continue();
        return;
      }
      counters.runDetailUrls.push(`${url.pathname}${url.search}`);
      // 컴포넌트는 useDagsterRunDetail(runId, 80, after)로 event_limit=80을 박는다.
      expect(url.searchParams.get("event_limit")).toBe("80");
      const runId = decodeURIComponent(
        url.pathname.replace("/v1/ops/dagster/runs/", ""),
      );
      const after = url.searchParams.get("after");
      await fulfillJson(route, runDetail(runId, after));
    });
  }

  return counters;
}

test.describe("admin dagster interactions (/admin/dagster)", () => {
  test("summary 성공 시 nux-seen POST를 자동 발사한다 (mark-seen effect)", async ({
    page,
  }) => {
    const counters = await mockDagster(page, {
      summary: () => makeSummary(),
      runDetail: () => makeRunDetail(),
    });

    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dagster 운영" }),
    ).toBeVisible();
    await expect(page.getByTestId("dagster-embed")).toBeVisible();

    // status==='ok' && markNuxSeenStatus==='idle' → useEffect가 정확히 1회 POST.
    // (summary는 10s 폴링이지만 mutation은 effect 가드로 1회만 발사된다 — GET count는 단언하지 않음.)
    await expect.poll(() => counters.nuxSeen).toBe(1);
  });

  test("summary가 unavailable이면 nux-seen을 발사하지 않는다 (effect gate 음성대조)", async ({
    page,
  }) => {
    const counters = await mockDagster(page, {
      summary: () =>
        makeSummary({
          errors: ["dagster webserver unreachable: ECONNREFUSED 127.0.0.1:12702"],
          recent_runs: [],
          repositories: [],
          repository_count: 0,
          job_count: 0,
          asset_count: 0,
          schedule_count: 0,
          sensor_count: 0,
          run_counts: {},
          status: "unavailable",
        }),
      // nux-seen 라우트를 등록은 하되 카운터로 0을 검증(status≠ok → effect 비발사).
      mockNuxSeen: true,
    });

    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dagster 운영" }),
    ).toBeVisible();
    // 상단 상태 배지가 'unavailable' (statusVariant→destructive)
    await expect(page.getByText("unavailable", { exact: true })).toBeVisible();
    // status≠'ok'이므로 effect가 markNuxSeen을 호출하지 않는다.
    await expect.poll(() => counters.nuxSeen).toBe(0);
  });

  test("recent runs 빈 목록이면 empty state를 렌더하고 run detail은 placeholder를 보인다", async ({
    page,
  }) => {
    // run-detail 라우트를 의도적으로 미등록 — 빈 목록이면 effectiveSelectedRunId=null이라
    // /runs/ fetch가 절대 일어나지 않아야 한다(일어나면 미등록 라우트로 새어 검증 실패).
    const counters = await mockDagster(page, {
      summary: () =>
        makeSummary({
          recent_runs: [],
          repositories: [],
          repository_count: 0,
          job_count: 0,
          asset_count: 0,
          schedule_count: 0,
          sensor_count: 0,
          run_counts: {},
        }),
    });

    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { name: "Recent runs" }),
    ).toBeVisible();
    // RunsTable DataTable emptyMessage.
    await expect(page.getByText("최근 Dagster run이 없습니다.")).toBeVisible();
    // RepositoryList 빈 분기.
    await expect(page.getByText("등록된 code location이 없습니다.")).toBeVisible();
    // RunDetailCard: runId=null → 점선 placeholder.
    await expect(page.getByRole("heading", { name: "Run detail" })).toBeVisible();
    await expect(
      page.getByText("최근 run을 선택하면 event log와 실패 원인이 표시됩니다."),
    ).toBeVisible();
    // Active/Failed 카드는 0으로 여전히 렌더(설명 문구로 카드 anchor — bare '0' 충돌 회피).
    await expect(page.getByText("non-terminal recent runs")).toBeVisible();
    await expect(page.getByText("recent failure count")).toBeVisible();

    // 빈 목록 → effectiveSelectedRunId=null → /runs/ fetch는 절대 발생하지 않는다
    // (run-detail 라우트 미등록이므로 새면 미처리 라우트로 검증 실패).
    expect(counters.runDetailUrls).toHaveLength(0);
  });

  test("FAILURE run을 자동 선택해 run detail event log에서 실패 원인을 드릴다운한다", async ({
    page,
  }) => {
    const failedRun = makeRunSummary({
      job_name: "kma_weather_job",
      run_id: "dagster-run-failed-001",
      status: "FAILURE",
    });
    const counters = await mockDagster(page, {
      summary: () =>
        makeSummary({
          recent_runs: [makeRunSummary(), failedRun],
          run_counts: { FAILURE: 1, SUCCESS: 1 },
        }),
      runDetail: (runId) =>
        makeRunDetail({
          event_cursor: "cur-2",
          event_has_more: true,
          events: [
            makeRunEvent({
              dagster_event_type: "STEP_FAILURE",
              error: {
                class_name: "DagsterExecutionStepExecutionError",
                message: "boom in load step",
              },
              event_type: "ExecutionStepFailureEvent",
              level: "ERROR",
              step_id: "load_features",
            }),
          ],
          run: makeRunSummary({ run_id: runId, status: "FAILURE" }),
          status: "ok",
        }),
    });

    await page.goto("/admin/dagster");

    const runDetailCard = page
      .locator('div[data-slot="card"]')
      .filter({ has: page.getByRole("heading", { name: "Run detail" }) });

    // fallbackRun = 첫 FAILURE run → 클릭 없이 자동 마운트.
    await expect(page.getByRole("heading", { name: "Run detail" })).toBeVisible();
    await expect(page.getByText("backend GraphQL event log")).toBeVisible();

    // event_limit=80 + after 없음(page 1) — run-detail handler가 단언.
    await expect
      .poll(() => counters.runDetailUrls.length)
      .toBeGreaterThanOrEqual(1);
    expect(counters.runDetailUrls[0]).toContain(
      "/v1/ops/dagster/runs/dagster-run-failed-001",
    );
    expect(counters.runDetailUrls[0]).not.toContain("after=");

    // event log: 컬럼 헤더 + 실패 메시지(graphqlErrorText, destructive) + event-type Badge.
    await expect(page.getByRole("columnheader", { name: "event" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "message" })).toBeVisible();
    await expect(
      page.getByText("DagsterExecutionStepExecutionError: boom in load step"),
    ).toBeVisible();
    await expect(page.getByText("STEP_FAILURE")).toBeVisible();

    // Run detail 카드 내부 status 배지 'FAILURE'(data.status + run.status). RunsTable에도
    // 같은 'FAILURE' 배지가 있으므로 Run detail 카드로 scope해 strict-mode 충돌 회피.
    await expect(runDetailCard.getByText("events more")).toBeVisible();
    await expect(
      runDetailCard.getByText("FAILURE", { exact: true }).first(),
    ).toBeVisible();

    // cursor 페이지네이션: page 1 → '다음 이벤트' enabled(event_has_more), '이전' disabled.
    await expect(
      page.getByRole("button", { name: "다음 이벤트" }),
    ).toBeEnabled();
    await expect(page.getByRole("button", { name: "이전" })).toBeDisabled();
  });

  test("schedule tick 실패를 code location 카드에서 드릴다운하고 run id로 run detail을 선택한다", async ({
    page,
  }) => {
    const tickRunId = "failedrun0001abcdef";
    const counters = await mockDagster(page, {
      summary: () =>
        makeSummary({
          repositories: [
            makeRepository({
              schedules: [
                makeSchedule({
                  cron_schedule: "0 6 * * *",
                  execution_timezone: "Asia/Seoul",
                  name: "weather_daily",
                  recent_ticks: [
                    makeTick({
                      error: {
                        class_name: "DagsterSensorEvaluationError",
                        message: "tick blew up",
                      },
                      run_ids: [tickRunId],
                      status: "FAILURE",
                      tick_id: "tick-1",
                    }),
                  ],
                  status: "error",
                }),
              ],
            }),
          ],
        }),
      runDetail: (runId) =>
        makeRunDetail({
          events: [],
          run: makeRunSummary({ run_id: runId, status: "FAILURE" }),
          status: "ok",
        }),
    });

    await page.goto("/admin/dagster");

    await expect(
      page.getByRole("heading", { name: "Code locations" }),
    ).toBeVisible();
    // 'Schedules'/'Sensors'는 SummaryCard 설명("N jobs / N schedules",
    // "N sensors registered")에도 (소문자) 등장해 getByText 기본 case-insensitive
    // substring 매치가 strict-mode 충돌을 낸다. 드릴다운 대상인 Code locations 카드의
    // InstigationList 소제목으로 scope해 정확히 1개로 좁힌다.
    const codeLocationsCard = page
      .locator('div[data-slot="card"]')
      .filter({ has: page.getByRole("heading", { name: "Code locations" }) });
    await expect(codeLocationsCard.getByText("Schedules")).toBeVisible();
    await expect(codeLocationsCard.getByText("Sensors")).toBeVisible();

    // tick 실패 텍스트(TickRows graphqlErrorText, destructive) + cron/timezone 라인.
    await expect(
      page.getByText("DagsterSensorEvaluationError: tick blew up"),
    ).toBeVisible();
    await expect(page.getByText("0 6 * * *")).toBeVisible();
    await expect(page.getByText("· Asia/Seoul")).toBeVisible();

    // run-id ghost 버튼은 shortRunId(runId.slice(0,12)+'...')로 truncate된 라벨을 쓴다.
    // "failedrun0001abcdef".slice(0,12)="failedrun000" → 라벨은 'failedrun000...'.
    const runIdButton = page.getByRole("button", { name: /failedrun000/ });
    await expect(runIdButton).toBeVisible();
    await runIdButton.click();

    // 클릭 → onSelectRun → RunDetailCard remount → /runs/<full id>?event_limit=80 fetch.
    await expect
      .poll(() =>
        counters.runDetailUrls.some((url) => url.includes(tickRunId)),
      )
      .toBe(true);

    // Run detail 카드에 full run_id(mono)가 보인다(run.run_id 전체 렌더).
    const runDetailCard = page
      .locator('div[data-slot="card"]')
      .filter({ has: page.getByRole("heading", { name: "Run detail" }) });
    await expect(runDetailCard.getByText(tickRunId)).toBeVisible();
  });

  test("summary가 unavailable이면 destructive alert를 띄우고 embed/refresh 표면은 유지된다", async ({
    page,
  }) => {
    // webserver-unreachable 계약 표면은 summary status='unavailable' destructive 배너다.
    // iframe 자체의 load 실패는 Playwright로 관측 불가 — 문서화된 fallback 표면만 단언.
    const counters = await mockDagster(page, {
      summary: () =>
        makeSummary({
          errors: ["dagster webserver unreachable: ECONNREFUSED 127.0.0.1:12702"],
          recent_runs: [],
          repositories: [],
          repository_count: 0,
          job_count: 0,
          asset_count: 0,
          schedule_count: 0,
          sensor_count: 0,
          run_counts: {},
          status: "unavailable",
        }),
    });

    await page.goto("/admin/dagster");

    // status==='unavailable' → errors 배너가 destructive(role=alert).
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "dagster webserver unreachable" }),
    ).toBeVisible();
    await expect(page.getByText("Dagster 상태 확인 필요")).toBeVisible();
    await expect(page.getByText("unavailable", { exact: true })).toBeVisible();

    // 운영자가 webserver UI로 갈 수 있는 표면은 유지된다.
    await expect(page.getByTestId("dagster-embed")).toBeVisible();
    await expect(page.getByRole("link", { name: /Dagster 열기/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "새로고침" })).toBeVisible();

    // status≠'ok' → nux-seen 미발사(effect gate 음성대조).
    await expect.poll(() => counters.nuxSeen).toBe(0);
  });

  test("summary HTTP 503이면 호출 실패 alert에 error.message를 노출한다", async ({
    page,
  }) => {
    // 앱 QueryClient는 retry:1(query-client-provider.tsx) — 503을 매 GET마다 반환해
    // retry 정착 후 error UI를 결정적으로 만든다. GET count는 단언하지 않음.
    await mockDagster(page, {
      summary: () => ({
        body: { detail: "upstream unavailable" },
        status: 503,
      }),
      mockNuxSeen: false,
    });

    await page.goto("/admin/dagster");

    // summary.isError → destructive Alert(role=alert) + error.message.
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "Dagster summary 호출 실패" }),
    ).toBeVisible();
    await expect(page.getByText(/실패 \(HTTP 503\)/)).toBeVisible();
    // data undefined && summary.isError → 상단 배지 'error'.
    await expect(page.getByText("error", { exact: true })).toBeVisible();
  });

  test("run detail 자체가 not_found이면 default(role=status) alert로 안내한다", async ({
    page,
  }) => {
    // summary에 run 1개 → RunDetailCard 자동선택. run-detail은 HTTP 200 + body status='not_found'
    // (retry storm 없음 — app-level not_found). status='not_found' → Alert variant=default → role=status.
    await mockDagster(page, {
      summary: () => makeSummary({ recent_runs: [makeRunSummary()] }),
      runDetail: () =>
        makeRunDetail({
          errors: ["run id not found in dagster storage"],
          events: [],
          event_has_more: false,
          run: null,
          status: "not_found",
        }),
    });

    await page.goto("/admin/dagster");

    await expect(page.getByRole("heading", { name: "Run detail" })).toBeVisible();
    // not_found → role=status(polite), destructive(role=alert) 아님.
    await expect(
      page.getByRole("status").filter({ hasText: "run id not found" }),
    ).toBeVisible();
    await expect(page.getByText("Run detail 상태 확인 필요")).toBeVisible();
    // events:[] → RunEventsTable emptyMessage.
    await expect(page.getByText("표시할 Dagster event가 없습니다.")).toBeVisible();
    // run:null → run id 상세 그리드 미렌더.
    const runDetailCard = page
      .locator('div[data-slot="card"]')
      .filter({ has: page.getByRole("heading", { name: "Run detail" }) });
    await expect(
      runDetailCard.getByText("run id", { exact: true }),
    ).toHaveCount(0);
  });
});
