import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
// 본 spec은 admin-ops.spec.ts의 `/v1/ops/consistency` 스모크가 라우트 mock 없이
// 검증하는 표면(heading/카드 라벨/필터 라벨) **이후의 data-loaded depth**만 더한다.
type OpsMetricsResponse = components["schemas"]["OpsMetricsResponse"];
type OpsMetricsData = components["schemas"]["OpsMetricsData"];
type OpsIntegrityIssueCountsRecord =
  components["schemas"]["OpsIntegrityIssueCountsRecord"];
type OpsDedupFpStatsRecord = components["schemas"]["OpsDedupFpStatsRecord"];
type OpsConsistencyReportRecord =
  components["schemas"]["OpsConsistencyReportRecord"];
type OpsConsistencyReportsListResponse =
  components["schemas"]["OpsConsistencyReportsListResponse"];
type OpsIntegrityIssueRecord =
  components["schemas"]["OpsIntegrityIssueRecord"];
type OpsIntegrityIssuesListResponse =
  components["schemas"]["OpsIntegrityIssuesListResponse"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const MOCK_FINISHED = "2026-06-08T00:05:00.000Z";

// shortId(value, 12)는 길이 > 12일 때 앞 12자 + "..."로 자른다(src/lib/format.ts).
// report_id/batch_id를 12자 초과로 두어 truncate가 결정적으로 동작하게 한다.
const REPORT_A_ID = "report-aaaaaaaa-0001";
const REPORT_B_ID = "report-bbbbbbbb-0002";
const BATCH_A_ID = "batch-aaaaaaaa-0001";
const BATCH_B_ID = "batch-bbbbbbbb-0002";

function makeDedupFpStats(
  overrides: Partial<OpsDedupFpStatsRecord> = {},
): OpsDedupFpStatsRecord {
  return {
    confirmed: 0,
    fp_rate: null,
    ignored: 0,
    pending: 0,
    precision: null,
    rejected: 0,
    resolved: 0,
    ...overrides,
  };
}

function makeIssueCounts(
  overrides: Partial<OpsIntegrityIssueCountsRecord> = {},
): OpsIntegrityIssueCountsRecord {
  return {
    by_severity: {},
    by_status: {},
    by_type: {},
    open_total: 0,
    ...overrides,
  };
}

function makeOpsMetrics(
  overrides: Partial<OpsMetricsData> = {},
): OpsMetricsResponse {
  const data: OpsMetricsData = {
    checked_at: MOCK_NOW,
    data_integrity_issues: makeIssueCounts(),
    dedup_fp_stats: makeDedupFpStats(),
    dedup_queue_by_status: {},
    features_active: 0,
    features_by_kind: {},
    features_inactive: 0,
    features_total: 0,
    import_jobs_by_status: {},
    latest_consistency_report: null,
    source_records_by_provider: {},
    ...overrides,
  };
  return {
    data,
    meta: { duration_ms: 1, request_id: "e2e-ops-metrics" },
  };
}

function makeConsistencyReport(
  overrides: Partial<OpsConsistencyReportRecord> = {},
): OpsConsistencyReportRecord {
  return {
    batch_id: BATCH_A_ID,
    cases: [],
    finished_at: MOCK_FINISHED,
    report_id: REPORT_A_ID,
    severity_max: "warn",
    started_at: MOCK_NOW,
    summary: {},
    ...overrides,
  };
}

function makeIntegrityIssue(
  overrides: Partial<OpsIntegrityIssueRecord> = {},
): OpsIntegrityIssueRecord {
  return {
    dataset_key: null,
    detected_at: MOCK_NOW,
    feature_id: null,
    issue_id: "issue-aaaaaaaa-0001",
    message: "default issue message",
    payload: {},
    provider: null,
    resolved_at: null,
    severity: "warn",
    source_record_key: null,
    status: "open",
    violation_type: "duplicate_source_key",
    ...overrides,
  };
}

function reportsList(
  items: OpsConsistencyReportRecord[],
): OpsConsistencyReportsListResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: { page_size: 20, next_cursor: null, total: null },
      request_id: "e2e-consistency-reports",
    },
  };
}

function issuesList(
  items: OpsIntegrityIssueRecord[],
): OpsIntegrityIssuesListResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: { page_size: 100, next_cursor: null, total: null },
      request_id: "e2e-consistency-issues",
    },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

// 카드/테이블에 같은 텍스트가 중복 등장(예: 'severity' columnheader가 두 표 모두에,
// StatusBadge 값이 metric 카드 + 표에 동시에)하므로, 값 단언은 항상 소유 카드로
// scope한다. 컴포넌트에 data-testid가 전혀 없어 role/text 기반 scoping만 가능.
function metricsCard(page: Page, heading: string) {
  return page.locator("div.rounded-lg").filter({ has: page.getByText(heading) });
}

test.describe("admin/ops consistency drilldown (route-mocked depth)", () => {
  test("renders metrics cards + report rows + issue rows", async ({ page }) => {
    await page.route("**/v1/ops/metrics**", async (route) => {
      await fulfillJson(
        route,
        makeOpsMetrics({
          data_integrity_issues: makeIssueCounts({ open_total: 7 }),
          latest_consistency_report: makeConsistencyReport({
            severity_max: "critical",
          }),
        }),
      );
    });
    await page.route("**/v1/ops/consistency/reports**", async (route) => {
      await fulfillJson(
        route,
        reportsList([
          makeConsistencyReport({
            report_id: REPORT_A_ID,
            batch_id: BATCH_A_ID,
            severity_max: "warn",
          }),
          makeConsistencyReport({
            report_id: REPORT_B_ID,
            batch_id: BATCH_B_ID,
            severity_max: "critical",
          }),
        ]),
      );
    });
    await page.route("**/v1/ops/consistency/issues**", async (route) => {
      await fulfillJson(
        route,
        issuesList([
          makeIntegrityIssue({
            issue_id: "issue-render-0001",
            severity: "critical",
            status: "open",
            provider: "python-mois-api",
            message: "mois permit duplicate source key detected",
          }),
        ]),
      );
    });

    await page.goto("/ops/consistency");

    await expect(
      page.getByRole("heading", { level: 1, name: "Consistency" }),
    ).toBeVisible();

    // metrics cards — scope each value to its owning bordered card.
    const openIssuesCard = metricsCard(page, "Open issues");
    await expect(openIssuesCard.getByText("7", { exact: true })).toBeVisible();

    // latest_consistency_report.severity_max='critical' → 'Latest severity' 카드
    // StatusBadge가 verbatim 'critical'을 렌더. severity columnheader와 충돌하지
    // 않도록 카드로 scope.
    const latestSeverityCard = metricsCard(page, "Latest severity");
    await expect(latestSeverityCard.getByText("critical")).toBeVisible();

    // reports 카드 — count Badge '2' + 두 report 행 모두 가시.
    const reportsCard = metricsCard(page, "Reports");
    await expect(reportsCard.getByText("2", { exact: true })).toBeVisible();
    // shortId(REPORT_A_ID) = 앞 12자 + '...' (둘 다 12자 초과).
    await expect(
      reportsCard.getByText(REPORT_A_ID.slice(0, 12) + "..."),
    ).toBeVisible();
    await expect(
      reportsCard.getByText(REPORT_B_ID.slice(0, 12) + "..."),
    ).toBeVisible();
    // 두 번째 report 행의 severity 셀이 verbatim 'critical' StatusBadge를 렌더.
    // 행은 short batch_id로 scope.
    const reportBRow = reportsCard.getByRole("row", {
      name: new RegExp(BATCH_B_ID.slice(0, 12)),
    });
    await expect(reportBRow.getByText("critical")).toBeVisible();

    // issues 카드 — unique message + severity 'critical' + provider cell.
    const issuesCard = metricsCard(page, "Integrity issues");
    await expect(
      issuesCard.getByText("mois permit duplicate source key detected"),
    ).toBeVisible();
    await expect(issuesCard.getByText("critical")).toBeVisible();
    await expect(issuesCard.getByText("python-mois-api")).toBeVisible();

    // columnheaders for both tables.
    for (const name of ["report", "batch", "finished"]) {
      await expect(
        page.getByRole("columnheader", { name, exact: true }),
      ).toBeVisible();
    }
    for (const name of ["issue", "message", "detected", "provider"]) {
      await expect(
        page.getByRole("columnheader", { name, exact: true }),
      ).toBeVisible();
    }
    // 'severity' columnheader는 두 표 모두에 존재 → 2개.
    await expect(
      page.getByRole("columnheader", { name: "severity", exact: true }),
    ).toHaveCount(2);

    // 이 페이지는 row-click 상세 pane이 없다(DataTable에 onRowClick 미전달, source 확인).
    // 행 클릭/detail aside 단언을 하지 않는다.
  });

  test("issue status filter re-queries issues endpoint with status param", async ({
    page,
  }) => {
    const calls = { open: 0, resolved: 0, all: 0 };

    await page.route("**/v1/ops/metrics**", async (route) => {
      await fulfillJson(route, makeOpsMetrics());
    });
    await page.route("**/v1/ops/consistency/reports**", async (route) => {
      await fulfillJson(route, reportsList([makeConsistencyReport()]));
    });
    await page.route("**/v1/ops/consistency/issues**", async (route) => {
      // 컴포넌트 default status='open' → status=open 쿼리 동반.
      // status==='all'일 때만 param 생략(component: status==='all' ? undefined : status).
      const url = new URL(route.request().url());
      const statusParam = url.searchParams.get("status");
      if (statusParam === "open") {
        calls.open += 1;
        await fulfillJson(
          route,
          issuesList([
            makeIntegrityIssue({
              issue_id: "issue-open-0001",
              status: "open",
              message: "open-only integrity violation",
            }),
          ]),
        );
        return;
      }
      if (statusParam === "resolved") {
        calls.resolved += 1;
        await fulfillJson(
          route,
          issuesList([
            makeIntegrityIssue({
              issue_id: "issue-resolved-0001",
              status: "resolved",
              severity: "warn",
              message: "resolved integrity violation",
            }),
          ]),
        );
        return;
      }
      // status param 부재 → 'all' 선택.
      calls.all += 1;
      await fulfillJson(
        route,
        issuesList([
          makeIntegrityIssue({
            issue_id: "issue-open-0001",
            status: "open",
            message: "open-only integrity violation",
          }),
          makeIntegrityIssue({
            issue_id: "issue-resolved-0001",
            status: "resolved",
            severity: "warn",
            message: "resolved integrity violation",
          }),
        ]),
      );
    });

    await page.goto("/ops/consistency");

    const issuesCard = metricsCard(page, "Integrity issues");
    const statusSelect = page.getByLabel("issue status");

    // 초기 mount: default 'open' → open 분기.
    await expect(
      issuesCard.getByText("open-only integrity violation"),
    ).toBeVisible();
    await expect.poll(() => calls.open).toBeGreaterThanOrEqual(1);

    // 'resolved' 선택 → 새 query key → status=resolved GET.
    await statusSelect.selectOption("resolved");
    await expect(
      issuesCard.getByText("resolved integrity violation"),
    ).toBeVisible();
    await expect(
      issuesCard.getByText("open-only integrity violation"),
    ).toHaveCount(0);
    await expect.poll(() => calls.resolved).toBe(1);

    // 'all' 선택 → status: undefined → param 부재 GET.
    await statusSelect.selectOption("all");
    await expect.poll(() => calls.all).toBe(1);
    await expect(
      issuesCard.getByText("open-only integrity violation"),
    ).toBeVisible();
    await expect(
      issuesCard.getByText("resolved integrity violation"),
    ).toBeVisible();

    // status NativeSelect는 실제 <select>이므로 selectOption 정상 동작
    // (base-ui aria-checked workaround 불필요).
  });

  test("empty state shows DataTable emptyMessage and zero count badge", async ({
    page,
  }) => {
    await page.route("**/v1/ops/metrics**", async (route) => {
      await fulfillJson(
        route,
        // open_total=0 → 'Open issues' 카드 '0'; latest_consistency_report: null
        // → 'Latest severity' StatusBadge가 default 'none'을 렌더.
        makeOpsMetrics({
          data_integrity_issues: makeIssueCounts({ open_total: 0 }),
          latest_consistency_report: null,
        }),
      );
    });
    await page.route("**/v1/ops/consistency/reports**", async (route) => {
      await fulfillJson(route, reportsList([]));
    });
    await page.route("**/v1/ops/consistency/issues**", async (route) => {
      await fulfillJson(route, issuesList([]));
    });

    await page.goto("/ops/consistency");

    await expect(
      page.getByRole("heading", { level: 1, name: "Consistency" }),
    ).toBeVisible();

    const reportsCard = metricsCard(page, "Reports");
    const issuesCard = metricsCard(page, "Integrity issues");

    // reports count Badge '0'.
    await expect(reportsCard.getByText("0", { exact: true })).toBeVisible();

    // DataTable default emptyMessage(컴포넌트가 명시 전달) — 두 표 모두에 등장.
    await expect(page.getByText("데이터가 없습니다.")).toHaveCount(2);
    await expect(reportsCard.getByText("데이터가 없습니다.")).toBeVisible();
    await expect(issuesCard.getByText("데이터가 없습니다.")).toBeVisible();

    // metrics 카드.
    await expect(
      metricsCard(page, "Open issues").getByText("0", { exact: true }),
    ).toBeVisible();
    // latest_consistency_report null → StatusBadge 'none'.
    await expect(
      metricsCard(page, "Latest severity").getByText("none"),
    ).toBeVisible();
  });

  test("error alert (destructive role=alert) when issues query fails", async ({
    page,
  }) => {
    // issues endpoint만 500으로 실패시키고 metrics/reports는 200 유지 → 단일 쿼리만 에러.
    // retry:1(query-client-provider)이므로 mount 시 1차 + 재시도 1차 모두 500이어야 한다
    // → 라우트를 등록 상태로 두어 매 hit마다 500을 응답.
    await page.route("**/v1/ops/metrics**", async (route) => {
      await fulfillJson(route, makeOpsMetrics());
    });
    await page.route("**/v1/ops/consistency/reports**", async (route) => {
      await fulfillJson(
        route,
        reportsList([
          makeConsistencyReport({
            report_id: REPORT_A_ID,
            batch_id: BATCH_A_ID,
          }),
        ]),
      );
    });
    await page.route("**/v1/ops/consistency/issues**", async (route) => {
      await fulfillJson(route, { detail: "integrity issues unavailable" }, 500);
    });

    await page.goto("/ops/consistency");

    // 컴포넌트는 variant='destructive' Alert → role=alert
    // (default Alert는 role=status; destructive만 role=alert — Wave gotcha).
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert.getByText("consistency 조회 실패")).toBeVisible();
    // AlertDescription = 실패 쿼리 error.message.
    // ApiClientError: `GET /v1/ops/consistency/issues?status=open 실패 (HTTP 500) ...`.
    // 전체 한국어+detail 문자열을 하드코딩하지 않고 'HTTP 500' 부분만 단언.
    await expect(alert.getByText(/HTTP 500/)).toBeVisible();

    // issues 영역은 crash하지 않는다(issues.data undefined → issueItems=[]); reports는
    // 여전히 자기 data를 렌더 → OR-guard 정상 동작 확인.
    const reportsCard = metricsCard(page, "Reports");
    await expect(
      reportsCard.getByText(REPORT_A_ID.slice(0, 12) + "..."),
    ).toBeVisible();
  });

  test("refresh button re-triggers reports query", async ({ page }) => {
    const calls = { reports: 0 };
    // mutable server state: refresh 직전 flag를 flip해 새 batch를 시뮬레이션.
    let serveListB = false;

    await page.route("**/v1/ops/metrics**", async (route) => {
      await fulfillJson(route, makeOpsMetrics());
    });
    await page.route("**/v1/ops/consistency/reports**", async (route) => {
      calls.reports += 1;
      await fulfillJson(
        route,
        reportsList([
          serveListB
            ? makeConsistencyReport({
                report_id: REPORT_B_ID,
                batch_id: BATCH_B_ID,
                severity_max: "critical",
              })
            : makeConsistencyReport({
                report_id: REPORT_A_ID,
                batch_id: BATCH_A_ID,
                severity_max: "warn",
              }),
        ]),
      );
    });
    await page.route("**/v1/ops/consistency/issues**", async (route) => {
      await fulfillJson(route, issuesList([makeIntegrityIssue()]));
    });

    await page.goto("/ops/consistency");

    const reportsCard = metricsCard(page, "Reports");
    // list A 렌더 확인(mount).
    await expect(
      reportsCard.getByText(REPORT_A_ID.slice(0, 12) + "..."),
    ).toBeVisible();
    await expect.poll(() => calls.reports).toBeGreaterThanOrEqual(1);

    // 새 batch 도착 시뮬레이션 후 새로고침.
    serveListB = true;
    // RefreshCwIcon은 aria-hidden(장식 lucide) → 버튼 accessible name은 visible
    // 텍스트 '새로고침'. refetch()는 staleTime을 우회하므로 새 GET 발생.
    await page.getByRole("button", { name: "새로고침" }).click();

    // 1 mount + 1 refetch 이상.
    await expect.poll(() => calls.reports).toBeGreaterThanOrEqual(2);
    // post-refresh list B(unique short report_id)가 렌더 → refetch 결과 반영 확인.
    await expect(
      reportsCard.getByText(REPORT_B_ID.slice(0, 12) + "..."),
    ).toBeVisible();
    // metrics는 10s마다 polling → 정확한 등가 count 단언은 하지 않는다.
  });
});
