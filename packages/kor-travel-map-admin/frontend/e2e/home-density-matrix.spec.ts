import { expect, type Locator, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";

type Meta = components["schemas"]["Meta"];
type PageMeta = components["schemas"]["PageMeta"];
type PublicHealthResponse = components["schemas"]["PublicHealthResponse"];
type PublicVersionResponse = components["schemas"]["PublicVersionResponse"];
type OpsMetricsResponse = components["schemas"]["OpsMetricsResponse"];
type OpsMetricsData = components["schemas"]["OpsMetricsData"];
type PipelineOverviewResponse =
  components["schemas"]["PipelineOverviewResponse"];
type OpsImportJobsListResponse =
  components["schemas"]["OpsImportJobsListResponse"];
type OpsImportJobRecord = components["schemas"]["OpsImportJobRecord"];
type DedupReviewListResponse =
  components["schemas"]["DedupReviewListResponse"];
type DedupReviewListMeta = DedupReviewListResponse["meta"];
type DedupReviewRecord = components["schemas"]["DedupReviewRecord"];
type DedupFeatureRecord = components["schemas"]["DedupFeatureRecord"];
type DagsterSummaryResponse = components["schemas"]["DagsterSummaryResponse"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const IMPORT_JOB_ID = "import-job-0123456789abcdef-density";
const DEDUP_REVIEW_ID = "dedup-review-0123456789abcdef-density";

// admin-shell.tsx NAV_GROUPS 평탄화 순서와 동일 (home-nav.spec.ts와 같은 정본).
const NAV_ITEMS = [
  { label: "홈", href: "/" },
  { label: "Feature 지도", href: "/features" },
  { label: "Feature 목록", href: "/admin/features" },
  { label: "Feature 검수", href: "/admin/features/change-reviews" },
  { label: "중복 검토", href: "/admin/features/dedup-reviews" },
  { label: "보강 검토", href: "/admin/features/enrichment-reviews" },
  { label: "이슈", href: "/admin/issues" },
  { label: "큐레이션 관리", href: "/admin/features/curated" },
  { label: "큐레이션 지도", href: "/curated-features" },
  { label: "파이프라인", href: "/ops/pipeline" },
  { label: "Provider 상태", href: "/ops/providers" },
  { label: "적재 작업", href: "/ops/import-jobs" },
  { label: "갱신 요청", href: "/admin/features/update-requests" },
  { label: "오프라인 업로드", href: "/admin/offline-uploads" },
  { label: "작업 자동화", href: "/admin/dagster" },
  { label: "ETL 미리보기", href: "/etl" },
  { label: "POI 캐시 대상", href: "/admin/poi-cache-targets" },
  { label: "운영 로그", href: "/ops/logs" },
  { label: "정합성 점검", href: "/ops/consistency" },
  { label: "백업", href: "/admin/backups" },
  { label: "설정", href: "/admin/settings" },
] as const;

type HomeEndpoint =
  | "health"
  | "version"
  | "metrics"
  | "pipeline"
  | "importJobs"
  | "dedup"
  | "dagster";

type CallCounts = Record<HomeEndpoint, number>;

interface HomeMockOptions {
  health?: PublicHealthResponse;
  version?: PublicVersionResponse;
  metrics?: OpsMetricsResponse;
  pipeline?: PipelineOverviewResponse;
  importJobs?: OpsImportJobRecord[];
  dedup?: DedupReviewRecord[];
  dagster?: DagsterSummaryResponse;
  fail?: Partial<Record<HomeEndpoint, number>>;
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function cursorListMeta(pageSize: number, requestId: string): Meta {
  const page: PageMeta = { next_cursor: null, page_size: pageSize, total: null };
  return { duration_ms: 1, page, request_id: requestId };
}

function offsetListMeta(pageSize: number, requestId: string): DedupReviewListMeta {
  return {
    duration_ms: 1,
    page: { page_size: pageSize, total: null },
    request_id: requestId,
  };
}

function simpleMeta(requestId: string): Meta {
  return { duration_ms: 1, request_id: requestId };
}

function makeHealth(
  overrides: Partial<components["schemas"]["HealthData"]> = {},
): PublicHealthResponse {
  return {
    data: { service: "kor-travel-map-api", status: "ok", ...overrides },
    meta: simpleMeta("e2e-density-health"),
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
    meta: simpleMeta("e2e-density-version"),
  };
}

function makeMetrics(overrides: Partial<OpsMetricsData> = {}): OpsMetricsResponse {
  const data: OpsMetricsData = {
    checked_at: MOCK_NOW,
    data_integrity_issues: {
      by_severity: { critical: 3, warning: 4 },
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
    features_by_kind: { event: 2, place: 40 },
    features_inactive: 12,
    features_total: 42,
    import_jobs_by_status: { queued: 1, running: 2 },
    latest_consistency_report: null,
    source_records_by_provider: { "python-kma-api": 100 },
    ...overrides,
  };
  return { data, meta: simpleMeta("e2e-density-metrics") };
}

function makePipelineOverview(
  overrides: Partial<components["schemas"]["PipelineOverviewData"]> = {},
): PipelineOverviewResponse {
  return {
    data: {
      active_operations: 3,
      checked_at: MOCK_NOW,
      dagster: {
        dagster_url: "http://127.0.0.1:12702",
        graphql_url: "http://127.0.0.1:12702/graphql",
        schedule_count: 1,
        sensor_count: 0,
        status: "ok",
      },
      failed_operations_24h: 1,
      operations_by_status: { queued: 1, running: 2 },
      ...overrides,
    },
    meta: simpleMeta("e2e-density-pipeline"),
  };
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
  return { data: { items }, meta: cursorListMeta(8, "e2e-density-import-jobs") };
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
  return { data: { items }, meta: offsetListMeta(6, "e2e-density-dedup") };
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
    meta: simpleMeta("e2e-density-dagster"),
  };
}

function emptyCounts(): CallCounts {
  return {
    dedup: 0,
    dagster: 0,
    health: 0,
    importJobs: 0,
    metrics: 0,
    pipeline: 0,
    version: 0,
  };
}

async function routeEndpoint(
  page: Page,
  glob: string,
  pathname: string,
  endpoint: HomeEndpoint,
  counts: CallCounts,
  options: HomeMockOptions,
  body: () => unknown,
) {
  await page.route(glob, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.resourceType() === "document" ||
      url.pathname.startsWith("/_next/") ||
      url.pathname === "/favicon.ico" ||
      url.searchParams.has("_rsc")
    ) {
      await route.continue();
      return;
    }
    const apiPath = bffApiPath(request.url());
    if (request.method() !== "GET" || apiPath !== pathname) {
      throw new Error(
        `Unhandled home ${endpoint} route: ${request.method()} ${apiPath}`,
      );
    }
    counts[endpoint] += 1;
    const status = options.fail?.[endpoint];
    if (status) {
      await route.fulfill({
        body: `${endpoint} density mock failure`,
        contentType: "text/plain",
        status,
      });
      return;
    }
    await fulfillJson(route, body());
  });
}

async function setupHomeMocks(
  page: Page,
  options: HomeMockOptions = {},
): Promise<CallCounts> {
  const counts = emptyCounts();
  await routeEndpoint(page, "**/health**", "/health", "health", counts, options, () =>
    options.health ?? makeHealth(),
  );
  await routeEndpoint(
    page,
    "**/version**",
    "/version",
    "version",
    counts,
    options,
    () => options.version ?? makeVersion(),
  );
  await routeEndpoint(
    page,
    "**/v1/ops/metrics**",
    "/v1/ops/metrics",
    "metrics",
    counts,
    options,
    () => options.metrics ?? makeMetrics(),
  );
  await routeEndpoint(
    page,
    "**/v1/ops/pipeline/overview**",
    "/v1/ops/pipeline/overview",
    "pipeline",
    counts,
    options,
    () => options.pipeline ?? makePipelineOverview(),
  );
  await routeEndpoint(
    page,
    "**/v1/ops/import-jobs**",
    "/v1/ops/import-jobs",
    "importJobs",
    counts,
    options,
    () => makeImportJobsList(options.importJobs ?? [makeImportJob()]),
  );
  await routeEndpoint(
    page,
    "**/v1/admin/features/dedup-reviews**",
    "/v1/admin/features/dedup-reviews",
    "dedup",
    counts,
    options,
    () => makeDedupList(options.dedup ?? [makeDedupReview()]),
  );
  await routeEndpoint(
    page,
    "**/v1/ops/dagster/summary**",
    "/v1/ops/dagster/summary",
    "dagster",
    counts,
    options,
    () => options.dagster ?? makeDagster(),
  );
  return counts;
}

async function gotoHome(page: Page, options: HomeMockOptions = {}) {
  const counts = await setupHomeMocks(page, options);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "운영 홈" })).toBeVisible();
  return counts;
}

function nav(page: Page): Locator {
  return page.locator("nav");
}

function navLink(page: Page, label: string): Locator {
  return nav(page).getByRole("link", { exact: true, name: label });
}

function card(page: Page, title: string): Locator {
  if (title === "Backend") {
    return page.getByTestId("service-backend");
  }
  if (title === "Dagster") {
    return page.getByTestId("service-dagster");
  }
  return page
    .locator('[data-slot="card"]')
    .filter({ has: page.getByRole("heading", { exact: true, name: title }) })
    .first();
}

test.describe("home/shell dense matrix", () => {
  for (const item of NAV_ITEMS) {
    test(`nav visible: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label)).toBeVisible();
    });

    test(`nav href exact: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label)).toHaveAttribute("href", item.href);
    });

    test(`nav icon present: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label).locator('[data-icon="inline-start"]')).toHaveCount(1);
    });

    test(`nav same-tab target: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label)).not.toHaveAttribute("target", /.+/);
    });

    test(`nav no external rel: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label)).not.toHaveAttribute("rel", /noreferrer|noopener/);
    });

    test(`nav accessible name unique: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(nav(page).getByRole("link", { exact: true, name: item.label })).toHaveCount(1);
    });

    test(`nav text exact: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      await expect(navLink(page, item.label)).toHaveText(item.label);
    });

    test(`nav path is internal: ${item.label}`, async ({ page }) => {
      await gotoHome(page);
      const href = await navLink(page, item.label).getAttribute("href");
      expect(href).toBe(item.href);
      expect(href?.startsWith("/")).toBe(true);
      expect(href).not.toContain("://");
    });

    test(`nav mobile visible: ${item.label}`, async ({ page }) => {
      await page.setViewportSize({ height: 844, width: 390 });
      await gotoHome(page);
      await expect(navLink(page, item.label)).toBeVisible();
    });

    test(`nav mobile href exact: ${item.label}`, async ({ page }) => {
      await page.setViewportSize({ height: 844, width: 390 });
      await gotoHome(page);
      await expect(navLink(page, item.label)).toHaveAttribute("href", item.href);
    });
  }

  for (const viewport of [
    { name: "mobile-390", width: 390, height: 844 },
    { name: "tablet-768", width: 768, height: 1024 },
    { name: "desktop-1440", width: 1440, height: 900 },
  ] as const) {
    for (const item of NAV_ITEMS) {
      test(`viewport ${viewport.name}: nav ${item.label} remains in shell`, async ({
        page,
      }) => {
        await page.setViewportSize({ height: viewport.height, width: viewport.width });
        await gotoHome(page);
        await expect(navLink(page, item.label)).toHaveAttribute("href", item.href);
      });
    }
  }

  for (const shellCase of [
    { text: "kor-travel-map", role: "link" },
    { text: "/", role: "text" },
    { text: "개요", role: "text" },
    {
      text: "운영 상태를 한 화면에서 확인합니다.",
      role: "text",
    },
    { text: "새로고침", role: "button" },
    { text: "Dagster", role: "link" },
    { text: "최근 적재 작업", role: "heading" },
    { text: "서비스 상태", role: "heading" },
    { text: "Backend", role: "panel" },
    { text: "중복 검수 대기", role: "heading" },
    { text: "Dagster", role: "panel" },
  ] as const) {
    test(`home shell surface: ${shellCase.role} ${shellCase.text}`, async ({
      page,
    }) => {
      await gotoHome(page);
      if (shellCase.role === "button") {
        await expect(page.getByRole("button", { name: shellCase.text })).toBeVisible();
      } else if (shellCase.role === "heading") {
        await expect(page.getByRole("heading", { name: shellCase.text })).toBeVisible();
      } else if (shellCase.role === "panel") {
        await expect(card(page, shellCase.text)).toBeVisible();
      } else if (shellCase.role === "link") {
        const link =
          shellCase.text === "Dagster"
            ? page.locator("header").getByRole("link", {
                exact: true,
                name: shellCase.text,
              })
            : page.getByRole("link", { exact: true, name: shellCase.text });
        await expect(link).toBeVisible();
      } else {
        await expect(page.getByText(shellCase.text, { exact: true })).toBeVisible();
      }
    });
  }
});

test.describe("home metrics dense matrix", () => {
  for (const item of [
    { total: 0, active: 0, inactive: 0, value: "0", desc: "활성 0 / 비활성 0" },
    { total: 1, active: 1, inactive: 0, value: "1", desc: "활성 1 / 비활성 0" },
    { total: 42, active: 30, inactive: 12, value: "42", desc: "활성 30 / 비활성 12" },
    { total: 1000, active: 998, inactive: 2, value: "1,000", desc: "활성 998 / 비활성 2" },
    { total: 12001, active: 11000, inactive: 1001, value: "12,001", desc: "활성 11,000 / 비활성 1,001" },
    { total: 2000000, active: 1500000, inactive: 500000, value: "2,000,000", desc: "활성 1,500,000 / 비활성 500,000" },
    { total: 7, active: 0, inactive: 7, value: "7", desc: "활성 0 / 비활성 7" },
    { total: 8, active: 8, inactive: 0, value: "8", desc: "활성 8 / 비활성 0" },
  ]) {
    test(`features metric value: total ${item.total}`, async ({ page }) => {
      await gotoHome(page, {
        metrics: makeMetrics({
          features_active: item.active,
          features_inactive: item.inactive,
          features_total: item.total,
        }),
      });
      await expect(card(page, "Feature").getByText(item.value, { exact: true })).toBeVisible();
    });

    test(`features metric description: total ${item.total}`, async ({ page }) => {
      await gotoHome(page, {
        metrics: makeMetrics({
          features_active: item.active,
          features_inactive: item.inactive,
          features_total: item.total,
        }),
      });
      await expect(card(page, "Feature").getByText(item.desc, { exact: true })).toBeVisible();
    });
  }

  for (const item of [
    { counts: {}, value: "0" },
    { counts: { queued: 1 }, value: "1" },
    { counts: { running: 2, queued: 1 }, value: "3" },
    { counts: { done: 9, failed: 1 }, value: "10" },
    { counts: { cancelled: 3, done: 97 }, value: "100" },
    { counts: { done: 1000, failed: 1 }, value: "1,001" },
    { counts: { queued: 12, running: 34, done: 56, failed: 7 }, value: "109" },
    { counts: { done: 1000000 }, value: "1,000,000" },
  ] satisfies Array<{ counts: Record<string, number>; value: string }>) {
    test(`pipeline operations metric value: ${item.value}`, async ({ page }) => {
      await gotoHome(page, {
        pipeline: makePipelineOverview({
          active_operations:
            (item.counts.queued ?? 0) + (item.counts.running ?? 0),
          operations_by_status: item.counts as Record<string, number>,
        }),
      });
      await expect(
        card(page, "파이프라인 작업").getByText(item.value, { exact: true }),
      ).toBeVisible();
    });

    test(`pipeline operations metric description remains stable: ${item.value}`, async ({
      page,
    }) => {
      const activeJobs = (item.counts.queued ?? 0) + (item.counts.running ?? 0);
      const expectedDescription =
        activeJobs > 0
          ? `${activeJobs.toLocaleString("ko-KR")}건 진행 중`
          : "대기 중인 작업 없음";
      await gotoHome(page, {
        pipeline: makePipelineOverview({
          active_operations: activeJobs,
          operations_by_status: item.counts as Record<string, number>,
        }),
      });
      await expect(
        card(page, "파이프라인 작업").getByText(expectedDescription, {
          exact: true,
        }),
      ).toBeVisible();
    });
  }

  for (const [index, item] of [
    { queue: {}, pending: 0, value: "0", desc: "대기 0건" },
    { queue: { pending: 1 }, pending: 1, value: "1", desc: "대기 1건" },
    { queue: { pending: 6, resolved: 3 }, pending: 6, value: "9", desc: "대기 6건" },
    { queue: { accepted: 5, pending: 12, rejected: 3 }, pending: 12, value: "20", desc: "대기 12건" },
    { queue: { ignored: 99, pending: 1 }, pending: 1, value: "100", desc: "대기 1건" },
    { queue: { pending: 1000, resolved: 1 }, pending: 1000, value: "1,001", desc: "대기 1,000건" },
    { queue: { pending: 0, resolved: 7 }, pending: 0, value: "7", desc: "대기 0건" },
    { queue: { pending: 500000, resolved: 500000 }, pending: 500000, value: "1,000,000", desc: "대기 500,000건" },
  ].entries() as IterableIterator<
    [number, { queue: Record<string, number>; pending: number; value: string; desc: string }]
  >) {
    test(`dedup queue metric value ${index}: ${item.value}`, async ({ page }) => {
      await gotoHome(page, {
        metrics: makeMetrics({
          dedup_fp_stats: {
            confirmed: 0,
            fp_rate: 0,
            ignored: 0,
            pending: item.pending,
            precision: 0,
            rejected: 0,
            resolved: 0,
          },
          dedup_queue_by_status: item.queue,
        }),
      });
      await expect(card(page, "중복 검수").getByText(item.value, { exact: true })).toBeVisible();
    });

    test(`dedup queue metric description ${index}: ${item.desc}`, async ({ page }) => {
      await gotoHome(page, {
        metrics: makeMetrics({
          dedup_fp_stats: {
            confirmed: 0,
            fp_rate: 0,
            ignored: 0,
            pending: item.pending,
            precision: 0,
            rejected: 0,
            resolved: 0,
          },
          dedup_queue_by_status: item.queue,
        }),
      });
      await expect(card(page, "중복 검수").getByText(item.desc, { exact: true })).toBeVisible();
    });
  }

  for (const item of [
    { open: 0, value: "0" },
    { open: 1, value: "1" },
    { open: 7, value: "7" },
    { open: 99, value: "99" },
    { open: 100, value: "100" },
    { open: 1000, value: "1,000" },
    { open: 1000000, value: "1,000,000" },
    { open: 2500001, value: "2,500,001" },
  ]) {
    test(`issues metric value: ${item.value}`, async ({ page }) => {
      await gotoHome(page, {
        metrics: makeMetrics({
          data_integrity_issues: {
            by_severity: { warning: item.open },
            by_status: { open: item.open },
            by_type: { missing_address: item.open },
            open_total: item.open,
          },
        }),
      });
      await expect(card(page, "이슈").getByText(item.value, { exact: true })).toBeVisible();
    });

    test(`issues metric description stable: ${item.value}`, async ({ page }) => {
      const expectedDescription = item.open > 0 ? "조치 필요" : "열린 이슈 없음";
      await gotoHome(page, {
        metrics: makeMetrics({
          data_integrity_issues: {
            by_severity: { warning: item.open },
            by_status: { open: item.open },
            by_type: { missing_address: item.open },
            open_total: item.open,
          },
        }),
      });
      await expect(
        card(page, "이슈").getByText(expectedDescription, {
          exact: true,
        }),
      ).toBeVisible();
    });
  }
});

test.describe("home import job and dedup dense matrix", () => {
  for (const item of [
    { status: "queued", statusLabel: "대기", progress: 0, kind: "festival_sync" },
    { status: "running", statusLabel: "실행중", progress: 7, kind: "weather_sync" },
    { status: "done", statusLabel: "완료", progress: 100, kind: "rest_area_sync" },
    { status: "failed", statusLabel: "실패", progress: 66, kind: "oil_price_sync" },
    { status: "cancelled", statusLabel: "취소됨", progress: 13, kind: "manual_upload" },
    { status: "blocked", statusLabel: "blocked", progress: 50, kind: "consistency_check" },
  ]) {
    test(`import job row status badge: ${item.status}`, async ({ page }) => {
      await gotoHome(page, {
        importJobs: [makeImportJob(item)],
      });
      await expect(
        card(page, "최근 적재 작업").getByText(item.statusLabel, { exact: true }),
      ).toBeVisible();
    });

    test(`import job row progress: ${item.status}`, async ({ page }) => {
      await gotoHome(page, {
        importJobs: [makeImportJob(item)],
      });
      await expect(card(page, "최근 적재 작업").getByText(`${item.progress}%`, { exact: true })).toBeVisible();
    });

    test(`import job row kind: ${item.status}`, async ({ page }) => {
      await gotoHome(page, {
        importJobs: [makeImportJob(item)],
      });
      await expect(card(page, "최근 적재 작업").getByText(item.kind, { exact: true })).toBeVisible();
    });

    test(`import job table keeps status column: ${item.status}`, async ({
      page,
    }) => {
      await gotoHome(page, {
        importJobs: [makeImportJob(item)],
      });
      await expect(card(page, "최근 적재 작업").getByRole("columnheader", { name: "status" })).toBeVisible();
    });

    test(`import job table keeps progress column: ${item.status}`, async ({
      page,
    }) => {
      await gotoHome(page, {
        importJobs: [makeImportJob(item)],
      });
      await expect(card(page, "최근 적재 작업").getByRole("columnheader", { name: "progress" })).toBeVisible();
    });
  }

  for (const item of [
    { a: "서울숲", b: "서울숲 공원", score: 2.7, expectedScore: "2.7" },
    { a: "부산역", b: "부산역 광장", score: 0, expectedScore: "0.0" },
    { a: "한라산", b: "한라산 국립공원", score: 1.05, expectedScore: "1.1" },
    { a: "경복궁", b: "경복궁 매표소", score: 3.99, expectedScore: "4.0" },
    { a: "대전역", b: "대전역 동광장", score: 10, expectedScore: "10.0" },
    { a: "춘천 명동", b: "춘천명동거리", score: 7.25, expectedScore: "7.3" },
  ]) {
    test(`dedup pending renders pair: ${item.a}`, async ({ page }) => {
      await gotoHome(page, {
        dedup: [
          makeDedupReview({
            feature_a: makeDedupFeature({ name: item.a }),
            feature_b: makeDedupFeature({ name: item.b }),
            total_score: item.score,
          }),
        ],
      });
      await expect(page.getByRole("link", { name: new RegExp(`${item.a} / ${item.b}`) })).toBeVisible();
    });

    test(`dedup pending score rounds: ${item.a}`, async ({ page }) => {
      await gotoHome(page, {
        dedup: [
          makeDedupReview({
            feature_a: makeDedupFeature({ name: item.a }),
            feature_b: makeDedupFeature({ name: item.b }),
            total_score: item.score,
          }),
        ],
      });
      await expect(card(page, "중복 검수 대기").getByText(`score ${item.expectedScore}`, { exact: false })).toBeVisible();
    });

    test(`dedup pending link target: ${item.a}`, async ({ page }) => {
      await gotoHome(page, {
        dedup: [
          makeDedupReview({
            feature_a: makeDedupFeature({ name: item.a }),
            feature_b: makeDedupFeature({ name: item.b }),
            total_score: item.score,
          }),
        ],
      });
      await expect(card(page, "중복 검수 대기").getByRole("link").first()).toHaveAttribute("href", "/admin/features/dedup-reviews");
    });
  }

  test("dedup pending empty state", async ({ page }) => {
    await gotoHome(page, { dedup: [] });
    await expect(page.getByText("pending dedup review가 없습니다.")).toBeVisible();
  });
});

test.describe("home backend/dagster/error dense matrix", () => {
  for (const [index, item] of [
    { admin: "0.0.1", map: "2.0.0" },
    { admin: "1.2.3", map: "2.0.0" },
    { admin: "2026.6.21", map: "2.1.0" },
    { admin: "local-dev", map: "editable" },
    { admin: "rc.1", map: "rc.2" },
    { admin: "prod", map: "prod-map" },
    { admin: "sha-deadbeef", map: "sha-cafebabe" },
    { admin: "admin-ui", map: "kortravelmap" },
  ].entries()) {
    test(`backend admin version badge ${index}: ${item.admin}`, async ({ page }) => {
      await gotoHome(page, {
        version: makeVersion({
          kor_travel_map_version: item.map,
          version: item.admin,
        }),
      });
      await expect(card(page, "Backend").getByText(`admin ${item.admin}`, { exact: true })).toBeVisible();
    });

    test(`backend map version badge ${index}: ${item.map}`, async ({ page }) => {
      await gotoHome(page, {
        version: makeVersion({
          kor_travel_map_version: item.map,
          version: item.admin,
        }),
      });
      await expect(card(page, "Backend").getByText(`map ${item.map}`, { exact: true })).toBeVisible();
    });
  }

  for (const [index, item] of ([
    { status: "ok", statusLabel: "정상", assets: 0, schedules: 0 },
    { status: "ok", statusLabel: "정상", assets: 2, schedules: 1 },
    { status: "unavailable", statusLabel: "사용불가", assets: 0, schedules: 0 },
    { status: "error", statusLabel: "오류", assets: 99, schedules: 12 },
    { status: "ok", statusLabel: "정상", assets: 1000, schedules: 100 },
    { status: "unavailable", statusLabel: "사용불가", assets: 5, schedules: 0 },
    { status: "error", statusLabel: "오류", assets: 1, schedules: 1 },
    { status: "unavailable", statusLabel: "사용불가", assets: 42, schedules: 6 },
    { status: "ok", statusLabel: "정상", assets: 8, schedules: 8 },
  ] satisfies Array<{
    status: components["schemas"]["DagsterSummaryData"]["status"];
    statusLabel: string;
    assets: number;
    schedules: number;
  }>).entries()) {
    test(`dagster status badge ${index}: ${item.status}`, async ({ page }) => {
      await gotoHome(page, {
        dagster: makeDagster({
          asset_count: item.assets,
          schedule_count: item.schedules,
          status: item.status,
        }),
      });
      await expect(
        card(page, "Dagster").getByText(item.statusLabel, { exact: true }),
      ).toBeVisible();
    });

    test(`dagster asset count badge ${index}: ${item.assets}`, async ({ page }) => {
      await gotoHome(page, {
        dagster: makeDagster({
          asset_count: item.assets,
          schedule_count: item.schedules,
          status: item.status,
        }),
      });
      await expect(card(page, "Dagster").getByText(`${item.assets.toLocaleString("ko-KR")} assets`, { exact: true })).toBeVisible();
    });

    test(`dagster schedule count badge ${index}: ${item.schedules}`, async ({ page }) => {
      await gotoHome(page, {
        dagster: makeDagster({
          asset_count: item.assets,
          schedule_count: item.schedules,
          status: item.status,
        }),
      });
      await expect(card(page, "Dagster").getByText(`${item.schedules.toLocaleString("ko-KR")} schedules`, { exact: true })).toBeVisible();
    });
  }

  for (const item of [
    { endpoint: "health", status: 503, surface: "Backend", statusTextVisible: true },
    { endpoint: "metrics", status: 500, surface: "Feature", statusTextVisible: true },
    {
      endpoint: "pipeline",
      status: 503,
      surface: "파이프라인 작업",
      statusTextVisible: true,
    },
    { endpoint: "dagster", status: 503, surface: "Dagster", statusTextVisible: true },
    { endpoint: "importJobs", status: 502, surface: "최근 적재 작업", statusTextVisible: true },
    { endpoint: "dedup", status: 500, surface: "중복 검수 대기", statusTextVisible: false },
    { endpoint: "version", status: 503, surface: "Backend", statusTextVisible: false },
  ] as const) {
    test(`endpoint failure keeps shell: ${item.endpoint}`, async ({ page }) => {
      await gotoHome(page, {
        fail: { [item.endpoint]: item.status },
      });
      await expect(page.getByRole("heading", { name: "운영 홈" })).toBeVisible();
      await expect(card(page, item.surface)).toBeVisible();
    });

    test(`endpoint failure status text policy: ${item.endpoint}`, async ({
      page,
    }) => {
      await gotoHome(page, {
        fail: { [item.endpoint]: item.status },
      });
      if (item.statusTextVisible) {
        await expect(page.getByText(`HTTP ${item.status}`, { exact: false }).first()).toBeVisible();
      } else {
        await expect(page.getByText(`HTTP ${item.status}`, { exact: false })).toHaveCount(0);
      }
    });
  }
});

test.describe("home refresh dense matrix", () => {
  for (const endpoint of [
    "health",
    "version",
    "metrics",
    "pipeline",
    "importJobs",
    "dedup",
    "dagster",
  ] as const) {
    test(`refresh re-fetches ${endpoint}`, async ({ page }) => {
      const counts = await gotoHome(page);
      const before = counts[endpoint];
      await page.getByRole("button", { name: "새로고침" }).click();
      await expect.poll(() => counts[endpoint]).toBeGreaterThan(before);
    });
  }

  // 헤더 Dagster 링크는 NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL(빌드타임 인라인)을 가리킨다.
  // dev 빌드=localhost:12702, prod 빌드=설정된 도메인. 같은 spec이 어떤 배포에도 통과하도록
  // E2E_DAGSTER_URL로 기대값을 명시 override할 수 있게 한다(미설정 시 dev localhost).
  const expectedDagsterHref: string | RegExp =
    process.env.E2E_DAGSTER_URL ?? /^http:\/\/127\.0\.0\.1:127(?:02|12)$/;

  for (const item of [
    {
      name: "header Dagster link",
      label: "Dagster",
      href: expectedDagsterHref,
      scope: "header",
    },
    {
      name: "card Dagster management link",
      label: "작업 자동화",
      href: "/admin/dagster",
      scope: "page",
    },
    {
      name: "import jobs all link",
      label: "전체",
      href: "/ops/import-jobs",
      scope: "page",
    },
  ]) {
    test(`home action href: ${item.name}`, async ({ page }) => {
      await gotoHome(page);
      const link =
        item.scope === "header"
          ? page.locator("header").getByRole("link", {
              exact: true,
              name: item.label,
            })
          : page.getByRole("link", { exact: true, name: item.label }).first();
      await expect(link).toHaveAttribute("href", item.href);
      if (item.name === "header Dagster link") {
        await expect(link).toHaveAttribute("target", "_blank");
        await expect(link).toHaveAttribute("rel", "noreferrer");
      }
    });
  }
});
