import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

// LIVE (비-mock) e2e — /ops/consistency 읽기 라운드트립.
//
// 이 표면(consistency-client.tsx)은 read-only다: 변경 가능한 컨트롤은 issue
// status NativeSelect 하나뿐이고, DataTable에 onRowClick이 전달되지 않으며
// (row-click 상세 pane 없음) issue/report 컬럼에 outbound link/anchor도 없다.
// 따라서 "drilldown link 네비게이션"은 이 라우트에 존재하지 않는다 — 대신
// 이 표면이 실제로 지원하는 두 종류의 드릴다운만 라운드트립으로 검증한다:
//   (1) issue status 필터 → /consistency/issues 의 status 쿼리 파라미터 변경 →
//       backend가 해당 status 행만 반환 → issues 표가 그 행을 반영.
//   (2) 집계 카드(Open issues / Latest severity / Reports count)가
//       상세 endpoint(/consistency/issues, /consistency/reports, /metrics)
//       응답과 정합(집계→상세 드릴다운).
// 추가로 router가 지원하지만 UI에 노출되지 않는 provider 드릴다운 파라미터를
// API 레벨에서 검증한다(UI 반영 주장 없음 — 컨트롤이 없으므로).
//
// 셀렉터/파라미터는 모두 소스에서 직접 확인했다(요약의 인용 라인 참조).
// 모든 시나리오는 read-only(GET) — 생성/변경 entity 없음, cleanup 불필요.

type OpsMetricsResponse = components["schemas"]["OpsMetricsResponse"];
type OpsConsistencyReportsListResponse =
  components["schemas"]["OpsConsistencyReportsListResponse"];
type OpsIntegrityIssuesListResponse =
  components["schemas"]["OpsIntegrityIssuesListResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

// consistency-client.tsx: `issueStatuses` 배열과 동일.
type IssueStatusFilter =
  | "open"
  | "acknowledged"
  | "resolved"
  | "ignored"
  | "all";

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const ROUTE = "/ops/consistency";
const ISSUES_PATH = "/v1/ops/consistency/issues";
const REPORTS_PATH = "/v1/ops/consistency/reports";
const METRICS_PATH = "/v1/ops/metrics";
// consistency-client.tsx: useIntegrityIssues({ ..., page_size: 100 }).
const ISSUES_PAGE_SIZE = 100;
// consistency-client.tsx: useConsistencyReports({ page_size: 20 }).
const REPORTS_PAGE_SIZE = 20;

const EMPTY_MESSAGE = "데이터가 없습니다."; // consistency-client.tsx: emptyMessage prop.

test.describe.configure({ mode: "serial" });

// src/lib/format.ts shortId(value, size=12): 길이>12면 앞 12자 + "...".
function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

// status-badge.tsx: <StatusBadge>가 표시 텍스트를 statusLabel(status)로 한글화한다.
// "Latest severity" 카드는 <StatusBadge status={severity_max ?? "none"}>를 렌더하므로
// 화면 텍스트는 한글이다. severity_max ∈ ConsistencySeverity("OK"|"WARN"|"ERROR"),
// 카드 fallback "none". statusLabel: OK→정상 · ERROR→오류 · none→없음;
// STATUS_LABELS에 없는 값(WARN 등)은 원문 유지. (data/API status·severity 단언은
// 화면이 아니라 응답 계약이므로 영문 그대로 둔다.)
const SEVERITY_LABELS: Record<string, string> = {
  ok: "정상",
  error: "오류",
  none: "없음",
};
function severityLabel(value: string): string {
  return SEVERITY_LABELS[value.toLowerCase().replace(/-/g, "_")] ?? value;
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function statusParam(response: Response): string | null {
  return new URL(response.url()).searchParams.get("status");
}

// /consistency/issues GET 응답을 기다리되 status 쿼리 파라미터가 기대값과
// 일치하는지까지 확인한다("all"이면 status 파라미터가 아예 없어야 함 — 컴포넌트가
// status==='all'일 때 undefined로 보내고 client가 undefined param을 생략).
async function waitForIssuesResponse(
  page: Page,
  expected: IssueStatusFilter,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET") {
        return false;
      }
      if (apiPath(response) !== ISSUES_PATH) {
        return false;
      }
      const status = statusParam(response);
      return expected === "all" ? status === null : status === expected;
    },
    { timeout: FLOW_TIMEOUT },
  );
}

// gold-standard(admin-features-change-requests-write.live.spec.ts)에서 verbatim 차용.
async function browserFetch<T>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" | "PATCH" | "DELETE" } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed as T | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

// consistency-drilldown.spec.ts(route-mocked depth)의 검증된 scoping 헬퍼와 동일:
// 카드/표에 같은 텍스트가 중복 등장하므로 값 단언은 항상 소유 카드로 scope한다.
function metricsCard(page: Page, heading: string): Locator {
  return page.locator("div.rounded-lg").filter({ has: page.getByText(heading) });
}

async function gotoConsistency(page: Page): Promise<void> {
  await page.goto(ROUTE);
  // AdminShell(title="Consistency") h1.
  await expect(
    page.getByRole("heading", { level: 1, name: "Consistency" }),
  ).toBeVisible(T);
  // issue status NativeSelect (aria-label="issue status").
  await expect(page.getByLabel("issue status")).toBeVisible(T);
}

test.describe("/ops/consistency 읽기 드릴다운 라운드트립 (live)", () => {
  test("issue status 필터가 status 쿼리 파라미터를 바꾸고 backend가 해당 status만 반환하며 issues 표가 이를 반영한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);

    const issuesCard = metricsCard(page, "Integrity issues");
    const statusSelect = page.getByLabel("issue status");

    await test.step("mount 시 default 'open' → status=open 쿼리가 나가고 backend는 open 행만 반환한다", async () => {
      // status useState('open') → 마운트 쿼리에 status=open 동반.
      const initialPromise = waitForIssuesResponse(page, "open");
      await gotoConsistency(page);
      await expect(statusSelect).toHaveValue("open", T);
      const initialResponse = await initialPromise;
      expect(initialResponse.status()).toBe(200);
      const openBody =
        (await initialResponse.json()) as OpsIntegrityIssuesListResponse;
      // 명시적 status=open 필터 → 반환 행은 모두 open.
      for (const item of openBody.data.items) {
        expect(item.status).toBe("open");
      }
    });

    await test.step("'all' 선택 → status 파라미터가 wire에서 사라진다(컨트롤이 파라미터를 토글)", async () => {
      const allPromise = waitForIssuesResponse(page, "all");
      await statusSelect.selectOption("all");
      await expect(statusSelect).toHaveValue("all", T);
      // waiter가 status 파라미터 부재(null)를 이미 강제 — 200만 추가 확인.
      const allResponse = await allPromise;
      expect(allResponse.status()).toBe(200);
    });

    await test.step("'resolved' 선택 → status=resolved 쿼리 → backend가 resolved 행만 반환하고 issues 표가 반영한다", async () => {
      const resolvedPromise = waitForIssuesResponse(page, "resolved");
      await statusSelect.selectOption("resolved");
      await expect(statusSelect).toHaveValue("resolved", T);
      const resolvedResponse = await resolvedPromise;
      expect(resolvedResponse.status()).toBe(200);
      const resolvedBody =
        (await resolvedResponse.json()) as OpsIntegrityIssuesListResponse;
      for (const item of resolvedBody.data.items) {
        expect(item.status).toBe("resolved");
      }

      // 독립 backend read(proxy GET)로 동일 status 계약 재확인.
      const resolvedRead = await browserFetch<OpsIntegrityIssuesListResponse>(
        page,
        `${ISSUES_PATH}?status=resolved&page_size=${ISSUES_PAGE_SIZE}`,
      );
      expect(resolvedRead.status).toBe(200);
      const resolvedReadBody = resolvedRead.body;
      expect(resolvedReadBody).not.toBeNull();
      if (resolvedReadBody) {
        for (const item of resolvedReadBody.data.items) {
          expect(item.status).toBe("resolved");
        }
      }

      // UI 반영: resolved 행이 있으면 첫 issue의 shortId(issue_id)가 issues
      // 카드에 보이고(issue 컬럼 = shortId(issue_id)), 없으면 emptyMessage.
      const firstResolved = resolvedBody.data.items[0];
      if (firstResolved) {
        await expect(
          issuesCard.getByText(shortId(firstResolved.issue_id)).first(),
        ).toBeVisible(T);
      } else {
        await expect(issuesCard.getByText(EMPTY_MESSAGE)).toBeVisible(T);
      }
    });
  });

  test("Open issues 집계 카드가 open issues 상세 목록 행 수와 정합한다(집계→상세 드릴다운)", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoConsistency(page);

    // 카드 집계의 정본은 /metrics open_total이다(카드 본문 =
    // formatCount(data_integrity_issues.open_total)). 카드는 로딩 중
    // formatCount(undefined)="0"을 보였다가 응답 후 실제값으로 갱신되며 별도
    // 로딩 표시가 없으므로, 화면 innerText를 한 번만 읽으면 stale "0"을 집을 수
    // 있다. 따라서 (a) /metrics를 직접 읽어 open_total을 정본으로 잡고,
    // (b) 카드가 그 값을 렌더할 때까지 poll로 대기해 로딩 레이스를 제거한다.
    const metricsRead = await browserFetch<OpsMetricsResponse>(page, METRICS_PATH);
    expect(metricsRead.status).toBe(200);
    const openTotal = metricsRead.body?.data.data_integrity_issues.open_total;
    expect(typeof openTotal).toBe("number");
    const displayedOpen = openTotal ?? 0;
    expect(Number.isInteger(displayedOpen)).toBe(true);
    expect(displayedOpen).toBeGreaterThanOrEqual(0);

    // 카드가 /metrics open_total을 반영할 때까지 대기(로케일 무관 — 콤마 제거 후
    // 정수 파싱이 open_total과 같아질 때까지 retry).
    const openCard = metricsCard(page, "Open issues");
    await expect
      .poll(
        async () =>
          Number(
            (await openCard.locator("div.text-2xl").innerText())
              .trim()
              .replace(/,/g, ""),
          ),
        T,
      )
      .toBe(displayedOpen);

    // 드릴다운: open issues 상세 endpoint를 직접 읽어 집계 숫자와 정합 확인.
    const openRead = await browserFetch<OpsIntegrityIssuesListResponse>(
      page,
      `${ISSUES_PATH}?status=open&page_size=${ISSUES_PAGE_SIZE}`,
    );
    expect(openRead.status).toBe(200);
    const openReadBody = openRead.body;
    expect(openReadBody).not.toBeNull();
    if (openReadBody) {
      const rows = openReadBody.data.items;
      for (const item of rows) {
        expect(item.status).toBe("open");
      }
      // 화면 집계 <= page_size면 상세 목록이 전수 → 행 수 == 집계.
      // (open_total은 전체 카운트, 상세는 page_size로 cap.)
      if (displayedOpen <= ISSUES_PAGE_SIZE) {
        expect(rows.length).toBe(displayedOpen);
      } else {
        expect(rows.length).toBe(ISSUES_PAGE_SIZE);
      }

      // UI 반영: open 행이 있으면 첫 issue의 shortId가 issues 카드에 보임.
      const issuesCard = metricsCard(page, "Integrity issues");
      const firstOpen = rows[0];
      if (firstOpen) {
        await expect(
          issuesCard.getByText(shortId(firstOpen.issue_id)).first(),
        ).toBeVisible(T);
      } else {
        await expect(issuesCard.getByText(EMPTY_MESSAGE)).toBeVisible(T);
      }
    }
  });

  test("Reports 카드 count/첫 행과 Latest severity 카드가 /consistency/reports·/metrics 응답을 반영한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoConsistency(page);

    const reportsCard = metricsCard(page, "Reports");

    // 컴포넌트와 동일 파라미터(page_size=20)로 /consistency/reports 직접 read.
    const reportsRead = await browserFetch<OpsConsistencyReportsListResponse>(
      page,
      `${REPORTS_PATH}?page_size=${REPORTS_PAGE_SIZE}`,
    );
    expect(reportsRead.status).toBe(200);
    const reportsBody = reportsRead.body;
    expect(reportsBody).not.toBeNull();

    // /metrics 직접 read → latest_consistency_report.
    const metricsRead = await browserFetch<OpsMetricsResponse>(page, METRICS_PATH);
    expect(metricsRead.status).toBe(200);
    const metricsBody = metricsRead.body;
    expect(metricsBody).not.toBeNull();

    if (reportsBody && metricsBody) {
      const reportItems = reportsBody.data.items;

      // Reports 헤더 count Badge = items.length(consistency-client.tsx).
      await expect(
        reportsCard.getByText(String(reportItems.length), { exact: true }),
      ).toBeVisible(T);

      // 첫 report 행: shortId(report_id) + shortId(batch_id) 반영(없으면 empty).
      const firstReport = reportItems[0];
      if (firstReport) {
        await expect(
          reportsCard.getByText(shortId(firstReport.report_id)).first(),
        ).toBeVisible(T);
        await expect(
          reportsCard.getByText(shortId(firstReport.batch_id)).first(),
        ).toBeVisible(T);
      } else {
        await expect(reportsCard.getByText(EMPTY_MESSAGE)).toBeVisible(T);
      }

      // Latest severity 카드 = <StatusBadge status={severity_max ?? 'none'}> →
      // 화면엔 statusLabel 한글 텍스트가 렌더되므로 기대값도 동일 매핑을 통과시킨다.
      const latest = metricsBody.data.latest_consistency_report ?? null;
      const latestSeverityCard = metricsCard(page, "Latest severity");
      const expectedSeverity = severityLabel(latest ? latest.severity_max : "none");
      await expect(
        latestSeverityCard.getByText(expectedSeverity).first(),
      ).toBeVisible(T);

      // 교차 정합(순서 가정 없음): 최신 report가 존재하고 목록이 page 상한 미만이면
      // (= 전수 반환), 최신 report_id는 반드시 목록에 포함된다.
      if (latest && reportItems.length < REPORTS_PAGE_SIZE) {
        expect(
          reportItems.some((report) => report.report_id === latest.report_id),
        ).toBe(true);
      }
    }
  });

  test("provider 드릴다운 파라미터가 issues endpoint에서 동작한다(API 레벨 — UI 미노출 필터)", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoConsistency(page);

    // open 집합에서 provider가 채워진 행을 찾는다(status=open 컨텍스트로 고정 —
    // router는 status 파라미터 부재 시 'open'을 default로 적용한다).
    const openRead = await browserFetch<OpsIntegrityIssuesListResponse>(
      page,
      `${ISSUES_PATH}?status=open&page_size=${ISSUES_PAGE_SIZE}`,
    );
    expect(openRead.status).toBe(200);
    const openBody = openRead.body;
    expect(openBody).not.toBeNull();
    if (!openBody) {
      return;
    }

    const withProvider = openBody.data.items.find(
      (item) => typeof item.provider === "string" && item.provider.length > 0,
    );
    test.skip(
      withProvider === undefined,
      "open issues에 provider가 채워진 행이 없어 provider 드릴다운을 검증할 수 없음(prod 데이터 의존)",
    );
    if (!withProvider || !withProvider.provider) {
      return;
    }
    const provider = withProvider.provider;

    // 같은 status=open 컨텍스트에서 provider로 드릴다운 → 해당 provider 행만,
    // 그리고 시드 issue가 반드시 포함되므로 최소 1건.
    const providerRead = await browserFetch<OpsIntegrityIssuesListResponse>(
      page,
      `${ISSUES_PATH}?status=open&provider=${encodeURIComponent(
        provider,
      )}&page_size=${ISSUES_PAGE_SIZE}`,
    );
    expect(providerRead.status).toBe(200);
    const providerBody = providerRead.body;
    expect(providerBody).not.toBeNull();
    if (providerBody) {
      expect(providerBody.data.items.length).toBeGreaterThan(0);
      for (const item of providerBody.data.items) {
        expect(item.provider).toBe(provider);
        expect(item.status).toBe("open");
      }
    }
  });
});
