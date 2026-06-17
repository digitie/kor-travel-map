import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// 이 파일은 /v1/ops/logs(LogsClient)의 admin-ops.spec.ts 스모크(lines 1087-1122,
// System+API 헤더/필터)를 **중복하지 않고**, Job events 탭·cursor 페이지네이션·
// 적용 필터·job deeplink·빈 상태·에러 alert의 깊이만 추가한다.
type SystemLogRecord = components["schemas"]["SystemLogRecord"];
type SystemLogsResponse = components["schemas"]["SystemLogsResponse"];
type ApiCallLogRecord = components["schemas"]["ApiCallLogRecord"];
type ApiCallLogsResponse = components["schemas"]["ApiCallLogsResponse"];
type OpsImportJobEventRecord =
  components["schemas"]["OpsImportJobEventRecord"];
type OpsImportJobEventsListResponse =
  components["schemas"]["OpsImportJobEventsListResponse"];
type Meta = components["schemas"]["Meta"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeMeta(nextCursor: string | null, pageSize = 100): Meta {
  return {
    duration_ms: 1,
    page: { page_size: pageSize, next_cursor: nextCursor, total: null },
    request_id: "e2e-ops-logs",
  };
}

function makeJobEvent(
  overrides: Partial<OpsImportJobEventRecord> = {},
): OpsImportJobEventRecord {
  return {
    code: "EVT-001",
    dataset_key: "kma_weather_values",
    event_id: "event-1",
    feature_id: null,
    job_id: "job-evt-1",
    level: "info",
    message: "first page event",
    occurred_at: MOCK_NOW,
    payload: {},
    provider: "python-kma-api",
    stage: "fetch",
    ...overrides,
  };
}

function systemLogsResponse(
  items: SystemLogRecord[],
  nextCursor: string | null = null,
): SystemLogsResponse {
  return { data: { items }, meta: makeMeta(nextCursor) };
}

function apiLogsResponse(
  items: ApiCallLogRecord[],
  nextCursor: string | null = null,
): ApiCallLogsResponse {
  return { data: { items }, meta: makeMeta(nextCursor) };
}

function jobEventsResponse(
  items: OpsImportJobEventRecord[],
  nextCursor: string | null = null,
): OpsImportJobEventsListResponse {
  return { data: { items }, meta: makeMeta(nextCursor) };
}

/**
 * 연결 불가한 실 WebSocket(ws://127.0.0.1:12701/v1/ops/live) 소음을 제거한다.
 * live 배지(connecting/reconnecting/unavailable) 상태는 절대 단언하지 않는다 —
 * WS 타이밍은 테스트 신호가 아니다(recon risks).
 */
async function abortLiveSocket(page: Page) {
  await page.route("**/v1/ops/live**", (route) => route.abort());
}

test.describe("admin/ops logs streams (Job events depth)", () => {
  test("/v1/ops/logs job events tab + applied filters + cursor pagination", async ({
    page,
  }) => {
    await abortLiveSocket(page);

    const eventQueries: URL[] = [];

    // import-job-events: page 1(커서 없음) → next_cursor=cursor-events-2,
    // page 2(cursor=cursor-events-2) → 다른 item + next_cursor=null.
    await page.route("**/v1/ops/import-job-events**", async (route) => {
      const url = new URL(route.request().url());
      eventQueries.push(url);
      const cursor = url.searchParams.get("cursor");
      if (cursor === "cursor-events-2") {
        await fulfillJson(
          route,
          jobEventsResponse(
            [
              makeJobEvent({
                event_id: "event-2",
                job_id: "job-evt-page2",
                message: "second page event",
              }),
            ],
            null,
          ),
        );
        return;
      }
      await fulfillJson(
        route,
        jobEventsResponse([makeJobEvent()], "cursor-events-2"),
      );
    });

    // system/api는 빈 목록 + next_cursor=null로 고정(배지/탭 결정성 확보).
    await page.route("**/v1/ops/system-logs**", async (route) => {
      await fulfillJson(route, systemLogsResponse([], null));
    });
    await page.route("**/v1/ops/api-call-logs**", async (route) => {
      await fulfillJson(route, apiLogsResponse([], null));
    });

    await page.goto("/ops/logs");

    await expect(
      page.getByRole("heading", { level: 1, name: "Logs" }),
    ).toBeVisible();

    // 기본 탭은 system(defaultValue="system"); events 패널은 탭 클릭 전까지 unmount.
    await page.getByRole("tab", { name: "Job events" }).click();

    // events DataTable 8개 컬럼(only 활성 패널만 mount → 헤더 충돌 없음).
    for (const column of [
      "occurred",
      "level",
      "provider",
      "dataset",
      "stage",
      "message",
      "job",
      "code",
    ]) {
      await expect(
        page.getByRole("columnheader", { name: column }),
      ).toBeVisible();
    }

    // useImportJobEvents는 refetchInterval로 POLL → GET 횟수가 아닌 query PARAMS를
    // 단언한다(recon KNOWN GOTCHA). 첫 events GET은 page_size=100, cursor 없음.
    await expect.poll(() => eventQueries.length).toBeGreaterThanOrEqual(1);
    expect(eventQueries[0].searchParams.get("page_size")).toBe("100");
    expect(eventQueries[0].searchParams.get("cursor")).toBeNull();

    // 적용 필터: 각 변경은 eventCursor를 null로 리셋(lines 511/520/536/544).
    // eventParams useMemo는 빈 값 drop, level="all" 생략 / "error" 전송(lines 94-115).
    await page.getByLabel("job event provider").fill("python-kma-api");
    await page.getByLabel("job event dataset key").fill("kma_weather_values");
    await page.getByLabel("job event job id").fill("job-evt-1");
    await page.getByLabel("job event level").selectOption("error");

    await expect
      .poll(() =>
        eventQueries.some(
          (url) =>
            url.searchParams.get("provider") === "python-kma-api" &&
            url.searchParams.get("dataset_key") === "kma_weather_values" &&
            url.searchParams.get("job_id") === "job-evt-1" &&
            url.searchParams.get("level") === "error",
        ),
      )
      .toBe(true);

    // cursor 페이지네이션: page 1에 next_cursor 있으니 "다음" enabled, eventCursor null
    // 이므로 "첫 페이지" disabled.
    await expect(page.getByRole("button", { name: "다음" })).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();

    await page.getByRole("button", { name: "다음" }).click();

    await expect
      .poll(() =>
        eventQueries.some(
          (url) => url.searchParams.get("cursor") === "cursor-events-2",
        ),
      )
      .toBe(true);
    await expect(page.getByText("second page event")).toBeVisible();

    // page 2로 이동하면 "첫 페이지" enabled. 클릭 → cursor 리셋(UI 상태로 단언;
    // 동일 query key 재방문은 staleTime 캐시로 새 GET이 안 날 수 있음 — recon risk).
    await page.getByRole("button", { name: "첫 페이지" }).click();
    await expect(page.getByText("first page event")).toBeVisible();
    await expect(page.getByRole("button", { name: "다음" })).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();

    // page_size 변경은 세 cursor 모두 null로 리셋(lines 340-345). 이후 events GET은
    // page_size=50 + cursor 없음.
    await page.getByLabel("log page size").selectOption("50");
    await expect
      .poll(() =>
        eventQueries.some(
          (url) =>
            url.searchParams.get("page_size") === "50" &&
            url.searchParams.get("cursor") === null,
        ),
      )
      .toBe(true);
  });

  test("/v1/ops/logs job event row → import-job deeplink", async ({ page }) => {
    await abortLiveSocket(page);

    await page.route("**/v1/ops/import-job-events**", async (route) => {
      await fulfillJson(
        route,
        jobEventsResponse(
          [
            makeJobEvent({
              event_id: "event-deeplink",
              job_id: "job-evt-deeplink-1",
              message: "deeplink event",
            }),
          ],
          null,
        ),
      );
    });
    await page.route("**/v1/ops/system-logs**", async (route) => {
      await fulfillJson(route, systemLogsResponse([], null));
    });
    await page.route("**/v1/ops/api-call-logs**", async (route) => {
      await fulfillJson(route, apiLogsResponse([], null));
    });

    await page.goto("/ops/logs");
    await page.getByRole("tab", { name: "Job events" }).click();

    // job 컬럼 셀은 <Link href={`/ops/import-jobs/${job_id}`}>. 가시 텍스트는
    // shortId(job_id)로 잘리므로(12자 초과), 잘리지 않은 href를 단언한다.
    // 다른 링크와 충돌하지 않도록 소유 event row로 스코프한다.
    const row = page.getByRole("row", { name: /deeplink event/ });
    await expect(row).toBeVisible();
    await expect(row.getByRole("link")).toHaveAttribute(
      "href",
      "/ops/import-jobs/job-evt-deeplink-1",
    );
  });

  test("/v1/ops/logs empty state across all three tabs", async ({ page }) => {
    await abortLiveSocket(page);

    await page.route("**/v1/ops/system-logs**", async (route) => {
      await fulfillJson(route, systemLogsResponse([], null));
    });
    await page.route("**/v1/ops/api-call-logs**", async (route) => {
      await fulfillJson(route, apiLogsResponse([], null));
    });
    await page.route("**/v1/ops/import-job-events**", async (route) => {
      await fulfillJson(route, jobEventsResponse([], null));
    });

    await page.goto("/ops/logs");

    // system 탭(기본) 빈 행 + 항상 mount된 summary 배지 0.
    await expect(page.getByText("system log가 없습니다.")).toBeVisible();
    await expect(page.getByText("system 0")).toBeVisible();
    await expect(page.getByText("api 0")).toBeVisible();
    await expect(page.getByText("job events 0")).toBeVisible();

    // system 탭 페이지네이션 가드: next_cursor=null → "다음" disabled, cursor null →
    // "첫 페이지" disabled (활성 패널의 버튼만 DOM에 있음).
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();

    // API 탭으로 전환 → 빈 메시지 + 가드.
    await page.getByRole("tab", { name: "API call logs" }).click();
    await expect(page.getByText("API call log가 없습니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();

    // Job events 탭으로 전환 → 빈 메시지 + 가드.
    await page.getByRole("tab", { name: "Job events" }).click();
    await expect(page.getByText("job event가 없습니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();
  });

  test("/v1/ops/logs error alert (destructive role=alert)", async ({ page }) => {
    await abortLiveSocket(page);

    // system-logs만 500으로 실패시키고 나머지는 빈 200 → system 쿼리만 에러.
    // ApiClientError message: `GET /v1/ops/system-logs 실패 (HTTP 500) {...}`.
    await page.route("**/v1/ops/system-logs**", async (route) => {
      await fulfillJson(route, { detail: "system log query failed" }, 500);
    });
    await page.route("**/v1/ops/api-call-logs**", async (route) => {
      await fulfillJson(route, apiLogsResponse([], null));
    });
    await page.route("**/v1/ops/import-job-events**", async (route) => {
      await fulfillJson(route, jobEventsResponse([], null));
    });

    await page.goto("/ops/logs");

    // QueryClient는 retry:1 → 1회 재시도 후 에러 표면. count가 아닌 가시성으로 단언.
    // destructive Alert만 role=alert(기본 Alert=role=status) — recon KNOWN GOTCHA.
    // 페이지에 role=alert가 둘 이상일 수 있으므로(예: DataTable 내부 에러 Alert)
    // page-level 에러 surface의 제목 "로그 조회 실패"로 좁혀 STRICT-MODE 충돌을 막는다.
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "로그 조회 실패" });
    await expect(alert).toBeVisible();
    await expect(page.getByText("로그 조회 실패")).toBeVisible();
    // description은 ApiClientError가 조립 — 정확 문자열 대신 substring 단언.
    await expect(alert).toContainText("/v1/ops/system-logs");
    await expect(alert).toContainText("HTTP 500");

    // 페이지가 crash하지 않고 heading은 계속 렌더. (isFetching 의존 새로고침 버튼
    // disabled 상태는 타이밍 의존이라 단언하지 않는다.)
    await expect(
      page.getByRole("heading", { level: 1, name: "Logs" }),
    ).toBeVisible();
  });
});
