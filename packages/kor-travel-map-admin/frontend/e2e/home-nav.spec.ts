import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(admin-ops.spec 패턴).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type Meta = components["schemas"]["Meta"];
type PageMeta = components["schemas"]["PageMeta"];
type PublicHealthResponse = components["schemas"]["PublicHealthResponse"];
type PublicVersionResponse = components["schemas"]["PublicVersionResponse"];
type OpsMetricsResponse = components["schemas"]["OpsMetricsResponse"];
type OpsMetricsData = components["schemas"]["OpsMetricsData"];
type OpsImportJobsListResponse =
  components["schemas"]["OpsImportJobsListResponse"];
type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type DedupReviewListResponse =
  components["schemas"]["DedupReviewListResponse"];
type DedupReviewRecord = components["schemas"]["DedupReviewRecord"];
type DedupFeatureRecord = components["schemas"]["DedupFeatureRecord"];
type DagsterSummaryResponse = components["schemas"]["DagsterSummaryResponse"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const IMPORT_JOB_ID = "import-job-0123456789abcdef-home";
const DEDUP_REVIEW_ID = "dedup-review-0123456789abcdef-home";

// ── 공용 헬퍼 ────────────────────────────────────────────────────────────────

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function listMeta(pageSize: number, requestId: string): Meta {
  // docs/architecture/rest-api.md §1.4/§3.3 — cursor 목록의 next_cursor는 항상 존재, null=소진.
  const page: PageMeta = { next_cursor: null, page_size: pageSize, total: null };
  return { duration_ms: 1, page, request_id: requestId };
}

function simpleMeta(requestId: string): Meta {
  return { duration_ms: 1, request_id: requestId };
}

// ── 스키마 바인딩 factory ─────────────────────────────────────────────────────

function makeHealth(
  overrides: Partial<components["schemas"]["HealthData"]> = {},
): PublicHealthResponse {
  return {
    data: { service: "kor-travel-map-api", status: "ok", ...overrides },
    meta: simpleMeta("e2e-home-health"),
  };
}

function makeVersion(
  overrides: Partial<components["schemas"]["VersionData"]> = {},
): PublicVersionResponse {
  return {
    data: {
      commit: "deadbeef",
      kor_travel_map_version: "2.0.0",
      openapi_version: "1.0.0",
      version: "1.2.3",
      ...overrides,
    },
    meta: simpleMeta("e2e-home-version"),
  };
}

function makeMetrics(overrides: Partial<OpsMetricsData> = {}): OpsMetricsResponse {
  const data: OpsMetricsData = {
    checked_at: MOCK_NOW,
    data_integrity_issues: {
      by_severity: { warning: 4, critical: 3 },
      by_status: { open: 7 },
      by_type: { missing_address: 7 },
      open_total: 7,
    },
    dedup_fp_stats: {
      confirmed: 5,
      fp_rate: 0.1,
      ignored: 1,
      pending: 6,
      precision: 0.9,
      rejected: 2,
      resolved: 8,
    },
    dedup_queue_by_status: { pending: 6, resolved: 3 },
    features_active: 30,
    features_by_kind: { place: 40, event: 2 },
    features_inactive: 12,
    features_total: 42,
    import_jobs_by_status: { queued: 1, running: 2 },
    latest_consistency_report: null,
    source_records_by_provider: { "python-kma-api": 100 },
    ...overrides,
  };
  return { data, meta: simpleMeta("e2e-home-metrics") };
}

function makeImportJob(
  overrides: Partial<OpsImportJobRecord> = {},
): OpsImportJobRecord {
  return {
    created_at: MOCK_NOW,
    current_stage: "load",
    error_message: null,
    finished_at: null,
    heartbeat_at: MOCK_NOW,
    job_id: IMPORT_JOB_ID,
    kind: "festival_sync",
    links: [],
    load_batch_id: null,
    parent_job_id: null,
    payload: {},
    progress: 50,
    source_checksum: null,
    started_at: MOCK_NOW,
    status: "running",
    status_url: `/v1/ops/import-jobs/${IMPORT_JOB_ID}`,
    ...overrides,
  };
}

function makeImportJobsList(
  items: OpsImportJobRecord[],
): OpsImportJobsListResponse {
  return { data: { items }, meta: listMeta(8, "e2e-home-import-jobs") };
}

function makeDedupFeature(
  overrides: Partial<DedupFeatureRecord> = {},
): DedupFeatureRecord {
  return {
    category: "02020101",
    dataset_key: "mock_dataset",
    feature_id: "mock-provider::mock-dataset::dedup-a",
    kind: "place",
    lat: 37.5665,
    lon: 126.978,
    name: "Feature A",
    provider: "python-kma-api",
    ...overrides,
  };
}

function makeDedupReview(
  overrides: Partial<DedupReviewRecord> = {},
): DedupReviewRecord {
  return {
    category_score: 1,
    created_at: MOCK_NOW,
    decision_reason: null,
    distance_m: 12.3,
    feature_a: makeDedupFeature({ name: "Feature A" }),
    feature_b: makeDedupFeature({
      feature_id: "mock-provider::mock-dataset::dedup-b",
      name: "Feature B",
    }),
    name_score: 0.95,
    review_id: DEDUP_REVIEW_ID,
    reviewed_at: null,
    reviewed_by: null,
    spatial_score: 0.88,
    status: "pending",
    total_score: 2.7,
    ...overrides,
  };
}

function makeDedupList(items: DedupReviewRecord[]): DedupReviewListResponse {
  return { data: { items }, meta: listMeta(6, "e2e-home-dedup") };
}

function makeDagster(
  overrides: Partial<components["schemas"]["DagsterSummaryData"]> = {},
): DagsterSummaryResponse {
  return {
    data: {
      asset_count: 2,
      checked_at: MOCK_NOW,
      dagster_url: "http://127.0.0.1:12702",
      errors: [],
      graphql_url: "http://127.0.0.1:12702/graphql",
      job_count: 1,
      recent_runs: [],
      repositories: [],
      repository_count: 1,
      run_counts: { SUCCESS: 3 },
      schedule_count: 1,
      sensor_count: 0,
      status: "ok",
      version: "1.7.0",
      ...overrides,
    },
    meta: simpleMeta("e2e-home-dagster"),
  };
}

// ── 라우트 mock 설치 ─────────────────────────────────────────────────────────
//
// 홈은 health/version/metrics/import-jobs/dedup-reviews/dagster-summary 6개를
// GET으로 호출한다. method + pathname을 가드해 다른 sub-request를 오배달하지 않는다.

async function routeHealth(page: Page, handler: (route: Route) => Promise<void>) {
  await page.route("**/health**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname !== "/health") {
      await route.continue();
      return;
    }
    await handler(route);
  });
}

async function routeVersion(page: Page, handler: (route: Route) => Promise<void>) {
  await page.route("**/version**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname !== "/version") {
      await route.continue();
      return;
    }
    await handler(route);
  });
}

async function routeMetrics(page: Page, handler: (route: Route) => Promise<void>) {
  await page.route("**/v1/ops/metrics**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname !== "/v1/ops/metrics") {
      await route.continue();
      return;
    }
    await handler(route);
  });
}

async function routeImportJobs(
  page: Page,
  handler: (route: Route) => Promise<void>,
) {
  await page.route("**/v1/ops/import-jobs**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    // 홈은 목록(list)만 호출한다 — `/{job_id}` 상세/events는 오지 않지만 방어한다.
    if (url.pathname !== "/v1/ops/import-jobs") {
      await route.continue();
      return;
    }
    await handler(route);
  });
}

async function routeDedup(page: Page, handler: (route: Route) => Promise<void>) {
  await page.route("**/v1/admin/dedup-reviews**", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname !== "/v1/admin/dedup-reviews") {
      await route.continue();
      return;
    }
    await handler(route);
  });
}

async function routeDagster(page: Page, handler: (route: Route) => Promise<void>) {
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
    await handler(route);
  });
}

// admin-shell.tsx navItems와 정확히 1:1로 거울처럼 박는다(18행). nav item이
// 추가/삭제되면 이 표와 toHaveCount(18)가 함께 깨져 테스트가 drift를 잡는다.
const NAV_ITEMS: ReadonlyArray<{ label: string; href: string }> = [
  { label: "홈", href: "/" },
  { label: "Features", href: "/features" },
  { label: "Admin features", href: "/admin/features" },
  { label: "Feature changes", href: "/admin/features/change-requests" },
  { label: "Curated features", href: "/admin/curated-features" },
  { label: "Issues", href: "/admin/issues" },
  { label: "Import jobs", href: "/ops/import-jobs" },
  { label: "Providers", href: "/ops/providers" },
  { label: "Consistency", href: "/ops/consistency" },
  { label: "Logs", href: "/ops/logs" },
  { label: "Dedup reviews", href: "/admin/dedup-reviews" },
  { label: "Enrichment reviews", href: "/admin/enrichment-reviews" },
  { label: "Update requests", href: "/admin/feature-update-requests" },
  { label: "POI targets", href: "/admin/poi-cache-targets" },
  { label: "Offline uploads", href: "/admin/offline-uploads" },
  { label: "Backups", href: "/admin/backups" },
  { label: "Dagster", href: "/admin/dagster" },
  { label: "ETL preview", href: "/etl" },
];

test.describe("home page (/) — nav + metric/status depth", () => {
  test("admin shell: 18개 nav 링크가 정확한 href로 렌더(audit gap 보강)", async ({
    page,
  }) => {
    // shell 구조 단언 — 모든 query가 실패/빈 응답이어도 AdminShell은 query 상태와
    // 독립적으로 렌더되므로 route mock이 필요 없다.
    await page.goto("/");

    const navigation = page.getByRole("navigation");
    await expect(navigation).toBeVisible();

    for (const { label, href } of NAV_ITEMS) {
      // nav로 scope — 로고 Link(text "kor-travel-map", href="/")와 body의
      // /ops/import-jobs("전체")·/admin/dagster·/admin/dedup-reviews Link 충돌 회피.
      const link = navigation.getByRole("link", { name: label, exact: true });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", href);
    }

    // nav 링크는 정확히 18개 — audit의 17→18 기대치를 잠근다(source navItems 기준).
    await expect(navigation.getByRole("link")).toHaveCount(18);
  });

  test("metric/status 카드가 happy-path payload에서 렌더", async ({ page }) => {
    // 6개 라우트 모두 page.goto 전에 mock.
    await routeHealth(page, (route) => fulfillJson(route, makeHealth()));
    await routeVersion(page, (route) => fulfillJson(route, makeVersion()));
    await routeMetrics(page, (route) => fulfillJson(route, makeMetrics()));
    await routeImportJobs(page, (route) =>
      fulfillJson(route, makeImportJobsList([makeImportJob()])),
    );
    await routeDedup(page, (route) =>
      fulfillJson(route, makeDedupList([makeDedupReview()])),
    );
    await routeDagster(page, (route) => fulfillJson(route, makeDagster()));

    await page.goto("/");

    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible();

    // ── metric 카드 (CardTitle = heading) ──
    const cards = page.locator('[data-slot="card"]');
    const featuresCard = cards.filter({
      has: page.getByRole("heading", { name: "Features", exact: true }),
    });
    await expect(
      featuresCard.getByRole("heading", { name: "Features", exact: true }),
    ).toBeVisible();
    // features_total=42 → value cell "42"
    await expect(featuresCard.getByText("42", { exact: true })).toBeVisible();
    // description: 30 active / 12 inactive
    await expect(
      featuresCard.getByText("30 active / 12 inactive"),
    ).toBeVisible();

    // Import jobs MetricCard: import_jobs_by_status 합(1+2=3)을 reduce한다.
    const importJobsCard = cards.filter({
      has: page.getByRole("heading", { name: "Import jobs", exact: true }),
    });
    await expect(
      importJobsCard.getByText("3", { exact: true }),
    ).toBeVisible();

    // Dedup queue MetricCard: dedup_queue_by_status 합(6+3=9) + pending desc.
    const dedupQueueCard = cards.filter({
      has: page.getByRole("heading", { name: "Dedup queue", exact: true }),
    });
    await expect(dedupQueueCard.getByText("9", { exact: true })).toBeVisible();
    await expect(
      dedupQueueCard.getByText("pending review 6건"),
    ).toBeVisible();

    // Issues MetricCard: data_integrity_issues.open_total = 7.
    const issuesCard = cards.filter({
      has: page.getByRole("heading", { name: "Issues", exact: true }),
    });
    await expect(issuesCard.getByText("7", { exact: true })).toBeVisible();

    // ── 최근 import jobs 테이블 ──
    await expect(
      page.getByRole("heading", { name: "최근 import jobs" }),
    ).toBeVisible();
    for (const column of ["job", "kind", "status", "progress", "updated"]) {
      await expect(
        page.getByRole("columnheader", { name: column }),
      ).toBeVisible();
    }
    const jobRow = page.getByRole("row", { name: /festival_sync/ });
    await expect(jobRow).toBeVisible();
    await expect(jobRow.getByText("running")).toBeVisible();
    // shortId(job_id) — font-mono 텍스트.
    await expect(jobRow.getByText("import-job-0", { exact: false })).toBeVisible();

    // ── Backend status 카드 (Backend Card로 scope — Dagster StatusBadge 충돌 회피) ──
    const backendCard = page.getByTestId("service-backend");
    await expect(backendCard.getByText("ok", { exact: true })).toBeVisible();
    await expect(backendCard.getByText("admin 1.2.3")).toBeVisible();
    await expect(backendCard.getByText("map 2.0.0")).toBeVisible();

    // ── Dagster status 카드 ──
    const dagsterCard = page.getByTestId("service-dagster");
    await expect(dagsterCard.getByText("2 assets")).toBeVisible();
    await expect(dagsterCard.getByText("1 schedules")).toBeVisible();
    await expect(
      dagsterCard.getByRole("link", { name: "Dagster 관리" }),
    ).toHaveAttribute("href", "/admin/dagster");

    // ── Dedup pending 카드 ──
    const dedupPendingCard = cards.filter({
      has: page.getByRole("heading", { name: "Dedup pending", exact: true }),
    });
    const dedupLink = dedupPendingCard.getByRole("link", {
      name: /Feature A \/ Feature B/,
    });
    await expect(dedupLink).toBeVisible();
    await expect(dedupLink).toHaveAttribute("href", "/admin/dedup-reviews");
  });

  test("health/metrics/dagster 5xx → destructive alert + 카드 degrade, shell 생존", async ({
    page,
  }) => {
    await routeHealth(page, (route) =>
      fulfillJson(route, { detail: "boom" }, 500),
    );
    await routeMetrics(page, (route) =>
      fulfillJson(route, { detail: "boom" }, 500),
    );
    await routeDagster(page, (route) =>
      fulfillJson(route, { detail: "unavailable" }, 503),
    );
    // version은 200 — partial failure 회복력 증명.
    await routeVersion(page, (route) => fulfillJson(route, makeVersion()));
    await routeImportJobs(page, (route) =>
      fulfillJson(route, { detail: "boom" }, 500),
    );
    await routeDedup(page, (route) => fulfillJson(route, makeDedupList([])));

    await page.goto("/");

    // destructive Alert만 role=alert (default Alert는 role=status) — house gotcha.
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(
      alert.filter({ hasText: "운영 summary 확인 필요" }),
    ).toBeVisible();

    // shell 생존: heading level1 + nav가 4/6 query 실패에도 렌더.
    await expect(
      page.getByRole("heading", { level: 1, name: "운영 홈" }),
    ).toBeVisible();
    await expect(page.getByRole("navigation")).toBeVisible();

    const cards = page.locator('[data-slot="card"]');

    // metric value cells → formatCount(undefined)="0". Features 카드로 scope.
    const featuresCard = cards.filter({
      has: page.getByRole("heading", { name: "Features", exact: true }),
    });
    await expect(featuresCard.getByText("0", { exact: true })).toBeVisible();

    // Backend StatusBadge "error" (health.isError) — Backend Card로 scope.
    const backendCard = page.getByTestId("service-backend");
    await expect(backendCard.getByText("error", { exact: true })).toBeVisible();
    // version 200 → admin/map 배지는 여전히 렌더.
    await expect(backendCard.getByText("admin 1.2.3")).toBeVisible();
    await expect(backendCard.getByText("map 2.0.0")).toBeVisible();

    // Dagster StatusBadge "error".
    const dagsterCard = page.getByTestId("service-dagster");
    await expect(dagsterCard.getByText("error", { exact: true })).toBeVisible();

    // 최근 import jobs: error.message <p>(text-destructive) + 빈 테이블 emptyMessage.
    const importCard = cards.filter({
      has: page.getByRole("heading", { name: "최근 import jobs", exact: true }),
    });
    await expect(
      importCard.getByText(/실패 \(HTTP 500\)/),
    ).toBeVisible();
    await expect(importCard.getByText("import job이 없습니다.")).toBeVisible();

    // Dedup pending 빈 상태.
    await expect(
      page.getByText("pending dedup review가 없습니다."),
    ).toBeVisible();
  });

  test("metrics 로딩 → skeleton, resolve → metric 카드", async ({ page }) => {
    // metrics 라우트만 gate로 잡아 isLoading을 결정적으로 유지(임의 sleep 없음).
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    await routeHealth(page, (route) => fulfillJson(route, makeHealth()));
    await routeVersion(page, (route) => fulfillJson(route, makeVersion()));
    await routeImportJobs(page, (route) =>
      fulfillJson(route, makeImportJobsList([])),
    );
    await routeDedup(page, (route) => fulfillJson(route, makeDedupList([])));
    await routeDagster(page, (route) => fulfillJson(route, makeDagster()));
    await routeMetrics(page, async (route) => {
      await gate;
      await fulfillJson(route, makeMetrics());
    });

    await page.goto("/");

    // metrics section: isLoading 동안 정확히 4개 MetricCardSkeleton.
    // import-jobs 테이블은 위에서 즉시 resolve(빈 목록)되므로 DataTable skeleton과
    // 충돌하지 않지만, data-testid="metric-skeleton"으로 metrics skeleton만 한정한다.
    const metricSkeletons = page.getByTestId("metric-skeleton");
    await expect(metricSkeletons).toHaveCount(4);
    // gate 동안 Features metric heading은 아직 없다.
    await expect(
      page.getByRole("heading", { name: "Features", exact: true }),
    ).toHaveCount(0);

    release();

    await expect(
      page.getByRole("heading", { name: "Features", exact: true }),
    ).toBeVisible();
    await expect(metricSkeletons).toHaveCount(0);
  });

  test("각 nav target 딥링크가 올바른 route+H1로 해석(full coverage)", async ({
    page,
  }) => {
    // 라이브/빈 backend를 직격하지만 각 목적지는 query 상태와 무관하게 shell+H1을
    // 렌더한다(home.spec docstring 회복력 계약). data 행이 아닌 URL+H1만 단언한다.
    // 기존 home.spec이 이미 다루는 Import jobs / Update requests는 중복하지 않는다.
    // H1이 admin-ops.spec에서 확인된 목적지만 H1 단언 — 나머지는 URL-only.
    const targetsWithH1: ReadonlyArray<{
      label: string;
      urlRe: RegExp;
      h1: string;
    }> = [
      { label: "Admin features", urlRe: /\/admin\/features$/, h1: "Admin features" },
      {
        label: "Feature changes",
        urlRe: /\/admin\/features\/change-requests$/,
        h1: "Feature change requests",
      },
      { label: "Issues", urlRe: /\/admin\/issues$/, h1: "Admin issues" },
      { label: "Providers", urlRe: /\/ops\/providers$/, h1: "Providers" },
      { label: "Consistency", urlRe: /\/ops\/consistency$/, h1: "Consistency" },
      { label: "Logs", urlRe: /\/ops\/logs$/, h1: "Logs" },
      {
        label: "Dedup reviews",
        urlRe: /\/admin\/dedup-reviews$/,
        h1: "Dedup review",
      },
      {
        label: "Enrichment reviews",
        urlRe: /\/admin\/enrichment-reviews$/,
        h1: "Enrichment review",
      },
      {
        label: "POI targets",
        urlRe: /\/admin\/poi-cache-targets$/,
        h1: "POI cache targets",
      },
      {
        label: "Offline uploads",
        urlRe: /\/admin\/offline-uploads$/,
        h1: "Offline uploads",
      },
      { label: "Backups", urlRe: /\/admin\/backups$/, h1: "Backups" },
    ];

    for (const { label, urlRe, h1 } of targetsWithH1) {
      await page.goto("/");
      const navigation = page.getByRole("navigation");
      await navigation
        .getByRole("link", { name: label, exact: true })
        .click();
      await expect(page).toHaveURL(urlRe);
      await expect(
        page.getByRole("heading", { level: 1, name: h1 }),
      ).toBeVisible();
    }

    // H1 미검증 목적지 — URL만 단언(grounding 유지).
    const urlOnlyTargets: ReadonlyArray<{ label: string; urlRe: RegExp }> = [
      { label: "Features", urlRe: /\/features$/ },
      { label: "Curated features", urlRe: /\/admin\/curated-features$/ },
      { label: "Dagster", urlRe: /\/admin\/dagster$/ },
      { label: "ETL preview", urlRe: /\/etl$/ },
    ];

    for (const { label, urlRe } of urlOnlyTargets) {
      await page.goto("/");
      const navigation = page.getByRole("navigation");
      await navigation
        .getByRole("link", { name: label, exact: true })
        .click();
      await expect(page).toHaveURL(urlRe);
    }
  });
});
