import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

// LIVE (non-mock) e2e against the real deployed admin stack. 운영 홈(`/`)을
// data↔UI round-trip으로 검증한다: 홈을 띄우고 ops/metrics·/health·/version·
// dagster summary·import-jobs API를 직접 읽어, metric 카드 수치 / Backend·Dagster
// 상태 배지 / 최근 import jobs 테이블이 **실제 backend 응답값**과 일치하는지 단언한다.
// 모든 시나리오는 read-only(GET) round-trip이라 write gate 없이 실행된다.
//
// helper(browserFetch / apiPath / isApiResponse / waitForApiResponse)와 컨벤션은
// gold-standard(admin-features-change-requests-write.live.spec.ts)에서 그대로 옮겼다.

type OpsMetricsResponse = components["schemas"]["OpsMetricsResponse"];
type OpsMetricsData = components["schemas"]["OpsMetricsData"];
type PublicHealthResponse = components["schemas"]["PublicHealthResponse"];
type PublicVersionResponse = components["schemas"]["PublicVersionResponse"];
type DagsterSummaryResponse = components["schemas"]["DagsterSummaryResponse"];
type OpsImportJobsListResponse =
  components["schemas"]["OpsImportJobsListResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

// API paths (proxy-stripped) — apiPath()는 pathname만 비교하므로 query는 무시된다.
const METRICS_PATH = "/v1/ops/metrics";
const HEALTH_PATH = "/health";
const VERSION_PATH = "/version";
const IMPORT_JOBS_PATH = "/v1/ops/import-jobs";
const DAGSTER_SUMMARY_QUERY = "/v1/ops/dagster/summary?run_limit=8";

test.describe.configure({ mode: "serial" });

// ── gold-standard helpers (verbatim) ────────────────────────────────────────

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function isApiResponse(
  response: Response,
  method: string,
  path: string,
): boolean {
  return response.request().method() === method && apiPath(response) === path;
}

async function waitForApiResponse(
  page: Page,
  method: string,
  path: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => isApiResponse(response, method, decodeURIComponent(path)),
    { timeout: FLOW_TIMEOUT },
  );
}

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

// ── home-surface helpers (selectors verified against source) ─────────────────

// formatCount mirrors src/lib/format.ts: `new Intl.NumberFormat("ko-KR").format(value ?? 0)`.
const numberFormatter = new Intl.NumberFormat("ko-KR");
function formatCount(value: number | null | undefined): string {
  return numberFormatter.format(value ?? 0);
}

// shortId mirrors src/lib/format.ts (size=12): table의 job 셀이 이 값을 렌더한다.
function shortId(value: string, size = 12): string {
  return value.length > size ? `${value.slice(0, size)}...` : value;
}

function sumValues(map: Record<string, number>): number {
  return Object.values(map).reduce((sum, count) => sum + count, 0);
}

// statusLabel mirrors src/components/status-badge.tsx STATUS_LABELS: StatusBadge가
// status enum을 한글로 렌더한다(영어→한글, 미매핑 값은 원문 유지, null→""). #585
// 이후 상태 배지가 한글화되어, 배지 텍스트를 단언할 땐 이 변환을 거쳐 비교한다.
const STATUS_LABELS: Record<string, string> = {
  ok: "정상",
  normal: "정상",
  success: "성공",
  succeeded: "성공",
  done: "완료",
  completed: "완료",
  active: "활성",
  accepted: "수락됨",
  merged: "병합됨",
  resolved: "해결됨",
  started: "시작됨",
  applied: "반영됨",
  curated: "큐레이션됨",
  validated: "검증됨",
  loaded: "적재됨",
  implemented: "구현됨",
  fresh: "최신",
  queued: "대기",
  pending: "대기",
  loading: "로딩중",
  running: "실행중",
  starting: "시작중",
  dry_run: "모의실행",
  validating: "검증중",
  in_progress: "진행중",
  materializing: "구체화중",
  scheduled: "예정됨",
  planned: "예정됨",
  ongoing: "진행중",
  managed: "관리됨",
  acknowledged: "확인됨",
  open: "열림",
  candidate: "후보",
  uploaded: "업로드됨",
  canceling: "취소중",
  paused: "일시정지",
  connecting: "연결중",
  reconnecting: "재연결중",
  error: "오류",
  failed: "실패",
  failure: "실패",
  cancelled: "취소됨",
  canceled: "취소됨",
  unavailable: "사용불가",
  critical: "심각",
  rejected: "거절됨",
  denied: "거부됨",
  inactive: "비활성",
  deleted: "삭제됨",
  disabled: "비활성화",
  expired: "만료됨",
  archived: "보관됨",
  deprecated: "지원중단",
  revoked: "폐기됨",
  skipped: "건너뜀",
  validation_failed: "검증실패",
  load_failed: "적재실패",
  not_found: "없음",
  degraded: "저하됨",
  manual_required: "수동 필요",
  provider_needed: "공급자 필요",
  manual_only: "수동 전용",
  ended: "종료됨",
  stopped: "중지됨",
  ignored: "무시됨",
  hidden: "숨김",
  not_started: "시작 전",
  stale: "오래됨",
  draft: "초안",
  unknown: "알수없음",
  none: "없음",
  info: "정보",
  warning: "경고",
  debug: "디버그",
};
function statusLabel(status: string | null | undefined): string {
  if (status == null) return "";
  const normalized = status.toLowerCase().replace(/-/g, "_");
  return STATUS_LABELS[normalized] ?? status;
}

// card.tsx: Card는 data-slot="card", CardTitle은 role="heading"(aria-level 2).
function cardByTitle(page: Page, title: string): Locator {
  return page.locator('[data-slot="card"]').filter({
    has: page.getByRole("heading", { name: title, exact: true }),
  });
}

async function gotoHome(page: Page): Promise<void> {
  await page.goto("/");
  // admin-shell.tsx: <h1>{title}</h1>, HomePageClient title="운영 홈".
  await expect(
    page.getByRole("heading", { level: 1, name: "운영 홈" }),
  ).toBeVisible(T);
  // metrics 로딩이 끝나면 skeleton → MetricCard("Features") heading으로 교체된다.
  await expect(
    page.getByRole("heading", { name: "Features", exact: true }),
  ).toBeVisible({ timeout: FLOW_TIMEOUT });
}

// metrics를 재조회하며 4개 카드/서브텍스트가 응답값과 수렴하는지 폴링한다.
async function pollMetricCards(
  page: Page,
  check: (data: OpsMetricsData) => Promise<boolean>,
): Promise<void> {
  await expect
    .poll(
      async () => {
        const res = await browserFetch<OpsMetricsResponse>(page, METRICS_PATH);
        if (res.status !== 200 || !res.body) {
          return `http:${res.status}`;
        }
        return (await check(res.body.data)) ? "match" : "mismatch";
      },
      { timeout: UI_TIMEOUT, intervals: [400, 800, 1500, 3000] },
    )
    .toBe("match");
}

test.describe("운영 홈(/) 라이브 data↔UI round-trip", () => {
  test("metric 카드 4종이 ops/metrics 응답값과 일치한다", async ({ page }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoHome(page);

    const featuresCard = cardByTitle(page, "Features");
    const importJobsCard = cardByTitle(page, "Import jobs");
    const dedupQueueCard = cardByTitle(page, "Dedup queue");
    const issuesCard = cardByTitle(page, "Issues");

    await test.step("ops/metrics를 직접 읽어 카드 수치를 교차검증한다", async () => {
      await pollMetricCards(page, async (d) => {
        const checks = await Promise.all([
          // home-client.tsx: value={formatCount(totalFeatures)} (features_total).
          featuresCard
            .getByText(formatCount(d.features_total), { exact: true })
            .first()
            .isVisible(),
          // value={formatCount(importJobTotal)} = Σ import_jobs_by_status.
          importJobsCard
            .getByText(formatCount(sumValues(d.import_jobs_by_status)), {
              exact: true,
            })
            .first()
            .isVisible(),
          // value={formatCount(dedupQueueTotal)} = Σ dedup_queue_by_status.
          dedupQueueCard
            .getByText(formatCount(sumValues(d.dedup_queue_by_status)), {
              exact: true,
            })
            .first()
            .isVisible(),
          // value={formatCount(openIssueCount)} = data_integrity_issues.open_total.
          issuesCard
            .getByText(formatCount(d.data_integrity_issues.open_total), {
              exact: true,
            })
            .first()
            .isVisible(),
          // Features 서브텍스트: `{active} active / {inactive} inactive`.
          featuresCard
            .getByText(
              `${formatCount(d.features_active)} active / ${formatCount(
                d.features_inactive,
              )} inactive`,
            )
            .first()
            .isVisible(),
          // Dedup queue 서브텍스트: `pending review {dedup_fp_stats.pending}건`.
          dedupQueueCard
            .getByText(`pending review ${formatCount(d.dedup_fp_stats.pending)}건`)
            .first()
            .isVisible(),
        ]);
        return checks.every(Boolean);
      });
    });
  });

  test("Backend/Dagster 상태 배지가 health/version/dagster API와 일치한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoHome(page);

    const backendCard = page.getByTestId("service-backend");
    const dagsterCard = page.getByTestId("service-dagster");

    await test.step("Backend 배지가 /health status, 버전 배지가 /version과 일치한다", async () => {
      const health = await browserFetch<PublicHealthResponse>(page, HEALTH_PATH);
      expect(health.status).toBe(200);
      expect(health.body).not.toBeNull();
      const healthStatus = (health.body as PublicHealthResponse).data.status;
      // status-badge.tsx: StatusBadge가 statusLabel(status)를 렌더 → 한글
      // (예: "ok"→"정상"). 미매핑 값은 원문 유지하므로 statusLabel로 변환해 비교한다.
      await expect(
        backendCard.getByText(statusLabel(healthStatus), { exact: true }),
      ).toBeVisible(T);

      const version = await browserFetch<PublicVersionResponse>(
        page,
        VERSION_PATH,
      );
      expect(version.status).toBe(200);
      expect(version.body).not.toBeNull();
      const versionData = (version.body as PublicVersionResponse).data;
      // home-client.tsx: <Badge>admin {version}</Badge> / <Badge>map {kor_travel_map_version}</Badge>.
      await expect(
        backendCard.getByText(`admin ${versionData.version}`),
      ).toBeVisible(T);
      await expect(
        backendCard.getByText(`map ${versionData.kor_travel_map_version}`),
      ).toBeVisible(T);
    });

    await test.step("Dagster 배지가 dagster summary status와 일치한다(불가용 시 error로 폴백)", async () => {
      // home-client.tsx: status={dagsterData?.status ?? (dagster.isError ? "error" : "loading")}.
      // dagster가 degrade되면 summary가 200이라도 data.status="error/unavailable",
      // 하드 실패면 query.isError → "error". StatusBadge가 statusLabel(...)로 한글
      // 렌더하므로(ok→정상·unavailable→사용불가·error→오류) statusLabel로 변환해 단언한다.
      await expect
        .poll(async () => {
          const res = await browserFetch<DagsterSummaryResponse>(
            page,
            DAGSTER_SUMMARY_QUERY,
          );
          const expected = statusLabel(
            res.status === 200 && res.body ? res.body.data.status : "error",
          );
          const visible = await dagsterCard
            .getByText(expected, { exact: true })
            .first()
            .isVisible();
          return visible ? "match" : `mismatch:${expected}`;
        }, T)
        .toBe("match");

      const dagster = await browserFetch<DagsterSummaryResponse>(
        page,
        DAGSTER_SUMMARY_QUERY,
      );
      if (dagster.status === 200 && dagster.body) {
        const d = dagster.body.data;
        // home-client.tsx: <Badge>{formatCount(asset_count)} assets</Badge> / schedules.
        await expect(
          dagsterCard.getByText(`${formatCount(d.asset_count)} assets`),
        ).toBeVisible(T);
        await expect(
          dagsterCard.getByText(`${formatCount(d.schedule_count)} schedules`),
        ).toBeVisible(T);
      }
    });
  });

  test("새로고침 버튼이 metrics/import-jobs refetch를 트리거하고 카드·테이블이 응답값을 반영한다", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoHome(page);

    // home-client.tsx: <Button onClick={refreshAll}>…새로고침</Button> →
    // metrics.refetch()/importJobs.refetch()/health… 6개 query 동시 refetch.
    const metricsPromise = waitForApiResponse(page, "GET", METRICS_PATH);
    const importJobsPromise = waitForApiResponse(page, "GET", IMPORT_JOBS_PATH);
    await page.getByRole("button", { name: "새로고침" }).click();
    const [metricsResp, importJobsResp] = await Promise.all([
      metricsPromise,
      importJobsPromise,
    ]);
    expect(metricsResp.status()).toBe(200);
    expect(importJobsResp.status()).toBe(200);

    const metricsBody = (await metricsResp.json()) as OpsMetricsResponse;
    const importJobsBody =
      (await importJobsResp.json()) as OpsImportJobsListResponse;

    await test.step("refetch된 metrics 값이 Features 카드에 반영된다", async () => {
      const featuresCard = cardByTitle(page, "Features");
      await expect(
        featuresCard
          .getByText(formatCount(metricsBody.data.features_total), {
            exact: true,
          })
          .first(),
      ).toBeVisible(T);
    });

    await test.step("refetch된 import-jobs 응답이 '최근 import jobs' 테이블에 반영된다", async () => {
      // page도 page_size=8로 같은 목록을 부르므로, 방금 잡은 응답이 곧 테이블 소스다.
      const card = cardByTitle(page, "최근 import jobs");
      const items = importJobsBody.data.items;
      if (items.length > 0) {
        const top = items[0];
        // data-table 행: job 셀=shortId(job_id), kind 셀=kind. running job은 status/
        // progress가 변하므로 안정 필드(shortId+kind)만 단언한다.
        const row = card.getByRole("row", {
          name: new RegExp(escapeRegExp(shortId(top.job_id))),
        });
        await expect(row).toBeVisible(T);
        await expect(row).toContainText(top.kind);
      } else {
        // home-client.tsx DataTable emptyMessage="import job이 없습니다.".
        await expect(card.getByText("import job이 없습니다.")).toBeVisible(T);
      }
    });
  });

  test("운영 내비/카드 링크가 실제 화면으로 resolve된다", async ({ page }) => {
    test.setTimeout(FLOW_TIMEOUT);

    await test.step("nav 'Import jobs' → /ops/import-jobs (H1 'Import jobs')", async () => {
      await gotoHome(page);
      // admin-shell.tsx nav는 단일 <nav> 랜드마크. metric 카드 heading과 충돌 회피 위해 스코프.
      await page
        .getByRole("navigation")
        .getByRole("link", { name: "Import jobs", exact: true })
        .click();
      await expect(page).toHaveURL(/\/ops\/import-jobs$/, T);
      await expect(
        page.getByRole("heading", { level: 1, name: "Import jobs" }),
      ).toBeVisible(T);
    });

    await test.step("nav 'Consistency' → /ops/consistency (H1 'Consistency')", async () => {
      await gotoHome(page);
      await page
        .getByRole("navigation")
        .getByRole("link", { name: "Consistency", exact: true })
        .click();
      await expect(page).toHaveURL(/\/ops\/consistency$/, T);
      await expect(
        page.getByRole("heading", { level: 1, name: "Consistency" }),
      ).toBeVisible(T);
    });

    await test.step("서비스 상태 카드의 'Dagster 관리' 카드 링크 → /admin/dagster", async () => {
      await gotoHome(page);
      const dagsterCard = page.getByTestId("service-dagster");
      const manageLink = dagsterCard.getByRole("link", { name: "Dagster 관리" });
      // home-client.tsx: <Link href="/admin/dagster">…Dagster 관리</Link>.
      await expect(manageLink).toHaveAttribute("href", "/admin/dagster");
      await manageLink.click();
      await expect(page).toHaveURL(/\/admin\/dagster$/, T);
    });
  });
});
