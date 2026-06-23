import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

/**
 * LIVE (비-mock) e2e — `/ops/import-jobs` 목록 + `/ops/import-jobs/{jobId}` 상세.
 *
 * 백엔드는 prod 실데이터(1.09M features)이고 route mocking이 없다. 따라서 변동 큰
 * 행 텍스트/정확한 카운트는 단언하지 않고, 페이지 main heading(h1) · 안정적
 * landmark(columnheader/role=table/empty-state) · URL · 컨트롤 상호작용(read-only
 * GET만)을 단언한다.
 *
 * 비파괴 규칙: page.goto + 읽기 assertion + click은 [status 필터 select / 검색
 * 인풋 타이핑(GET 조회) / 정렬 헤더 / 내비 링크]에만. cancel/refetch 버튼 등
 * mutation·POST 유발 동작은 절대 클릭하지 않는다.
 *
 * selector는 import-jobs-list.spec.ts / import-job-detail.spec.ts 및 실제
 * client 컴포넌트(import-jobs-client.tsx / import-job-detail-client.tsx)에서
 * 검증된 것만 재사용한다 — 새 selector를 짓지 않는다.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. E2E_BASE_URL이 host를 채운다.
 */

const LIST_ROUTE = "/ops/import-jobs";

// import-jobs-client.tsx statuses union (all 포함). 'all'은 status 파라미터 생략.
const STATUS_OPTIONS = [
  "all",
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
] as const;

// 반응형 viewport 교차 (desktop / tablet / mobile).
const VIEWPORTS = [
  { name: "desktop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
] as const;

// fixture 상한 — 대량 생성하되 런타임 폭발 방지.
const JOB_IDS = F.IMPORT_JOB_IDS.slice(0, 3);
const JOB_KINDS = F.IMPORT_JOB_KINDS.slice(0, 6);
const SEARCH = F.SEARCH_TERMS.slice(0, 12);
const SIZES = F.PAGE_SIZES.slice(0, 4);

/** 목록 페이지가 로드되고 안정적 landmark가 보이는지 확인하는 공용 어서션. */
async function expectListReady(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Import jobs" }),
  ).toBeVisible({ timeout: 15000 });
  // DataTable은 비어도 thead를 렌더하므로 PRESENCE 무관하게 안정적이다.
  await expect(
    page.getByRole("columnheader", { name: "job" }),
  ).toBeVisible({ timeout: 15000 });
}

/** 상세 페이지가 로드되었는지 확인 (h1 "Import job"은 데이터 유무와 무관하게 렌더). */
async function expectDetailReady(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Import job" }),
  ).toBeVisible({ timeout: 15000 });
}

test.describe("import-jobs live · list base", () => {
  test("list page loads — heading + job columnheader", async ({ page }) => {
    await page.goto(LIST_ROUTE);
    await expectListReady(page);
    await expect(page).toHaveURL(/\/ops\/import-jobs$/, { timeout: 15000 });
  });

  test("list page — filter controls present (status/kind/batch/parent)", async ({
    page,
  }) => {
    await page.goto(LIST_ROUTE);
    await expectListReady(page);
    await expect(page.getByLabel("status")).toBeVisible({ timeout: 15000 });
    await expect(page.getByPlaceholder("kind filter")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByPlaceholder("load_batch_id")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByPlaceholder("parent_job_id")).toBeVisible({
      timeout: 15000,
    });
  });

  test("list page — table landmark visible (empty or rows, loose)", async ({
    page,
  }) => {
    await page.goto(LIST_ROUTE);
    await expectListReady(page);
    // PRESENCE가 0이어도 DataTable role=table은 항상 존재한다(empty 포함).
    await expect(page.getByRole("table")).toBeVisible({ timeout: 15000 });
  });

  test("list page — status select defaults to 'all'", async ({ page }) => {
    await page.goto(LIST_ROUTE);
    await expectListReady(page);
    await expect(page.getByLabel("status")).toHaveValue("all", {
      timeout: 15000,
    });
  });
});

test.describe("import-jobs live · status filter", () => {
  for (const status of STATUS_OPTIONS) {
    test(`status filter '${status}' — select stays loaded`, async ({
      page,
    }) => {
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      // status select 변경은 GET 조회(queryKey 변경)만 유발 — read-only.
      await page.getByLabel("status").selectOption(status);
      await expect(page.getByLabel("status")).toHaveValue(status, {
        timeout: 15000,
      });
      await expectListReady(page);
    });
  }
});

test.describe("import-jobs live · status via URL deeplink", () => {
  for (const status of STATUS_OPTIONS) {
    test(`URL ?status=${status} seeds control`, async ({ page }) => {
      await page.goto(`${LIST_ROUTE}?status=${status}`);
      await expectListReady(page);
      // 'all' 및 union 멤버는 그대로 시드, union 밖이면 'all' 폴백(여긴 전부 union).
      await expect(page.getByLabel("status")).toHaveValue(status, {
        timeout: 15000,
      });
    });
  }

  test("URL ?status=bogus falls back to 'all'", async ({ page }) => {
    await page.goto(`${LIST_ROUTE}?status=bogus`);
    await expectListReady(page);
    await expect(page.getByLabel("status")).toHaveValue("all", {
      timeout: 15000,
    });
  });
});

test.describe("import-jobs live · kind filter typing (GET only)", () => {
  // IMPORT_JOB_KINDS를 kind filter input에 타이핑 — GET 조회만 유발(비파괴).
  for (const kind of JOB_KINDS.length > 0 ? JOB_KINDS : ["provider_sync"]) {
    test(`kind filter typing '${kind}' reflects in input`, async ({ page }) => {
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      const input = page.getByPlaceholder("kind filter");
      await input.fill(kind);
      await expect(input).toHaveValue(kind, { timeout: 15000 });
      // 타이핑 후에도 목록 landmark 유지.
      await expectListReady(page);
    });
  }

  for (const kind of JOB_KINDS.length > 0 ? JOB_KINDS : ["provider_sync"]) {
    test(`URL ?kind=${kind} seeds kind filter input`, async ({ page }) => {
      await page.goto(`${LIST_ROUTE}?kind=${encodeURIComponent(kind)}`);
      await expectListReady(page);
      await expect(page.getByPlaceholder("kind filter")).toHaveValue(kind, {
        timeout: 15000,
      });
    });
  }
});

test.describe("import-jobs live · search term typing (GET only)", () => {
  // SEARCH_TERMS를 kind filter input에 타이핑 — 검색창 타이핑은 GET 조회 허용.
  for (const term of SEARCH) {
    test(`search typing '${term}' reflects + list stays ready`, async ({
      page,
    }) => {
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      const input = page.getByPlaceholder("kind filter");
      await input.fill(term);
      await expect(input).toHaveValue(term, { timeout: 15000 });
      await expectListReady(page);
    });
  }
});

test.describe("import-jobs live · load_batch_id / parent_job_id deeplinks", () => {
  for (const jobId of JOB_IDS) {
    test(`URL ?load_batch_id=${jobId} seeds batch input`, async ({ page }) => {
      await page.goto(
        `${LIST_ROUTE}?load_batch_id=${encodeURIComponent(jobId)}`,
      );
      await expectListReady(page);
      await expect(page.getByPlaceholder("load_batch_id")).toHaveValue(jobId, {
        timeout: 15000,
      });
    });
  }

  for (const jobId of JOB_IDS) {
    test(`URL ?parent_job_id=${jobId} seeds parent input`, async ({ page }) => {
      await page.goto(
        `${LIST_ROUTE}?parent_job_id=${encodeURIComponent(jobId)}`,
      );
      await expectListReady(page);
      await expect(page.getByPlaceholder("parent_job_id")).toHaveValue(jobId, {
        timeout: 15000,
      });
    });
  }

  for (const jobId of JOB_IDS) {
    test(`load_batch_id input typing '${jobId.slice(0, 8)}' (GET)`, async ({
      page,
    }) => {
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      const input = page.getByPlaceholder("load_batch_id");
      await input.fill(jobId);
      await expect(input).toHaveValue(jobId, { timeout: 15000 });
      await expectListReady(page);
    });
  }

  for (const jobId of JOB_IDS) {
    test(`parent_job_id input typing '${jobId.slice(0, 8)}' (GET)`, async ({
      page,
    }) => {
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      const input = page.getByPlaceholder("parent_job_id");
      await input.fill(jobId);
      await expect(input).toHaveValue(jobId, { timeout: 15000 });
      await expectListReady(page);
    });
  }
});

test.describe("import-jobs live · combined URL filters", () => {
  for (const status of STATUS_OPTIONS) {
    test(`URL status=${status} + kind seeds both controls`, async ({
      page,
    }) => {
      const kind = JOB_KINDS[0] ?? "provider_sync";
      await page.goto(
        `${LIST_ROUTE}?status=${status}&kind=${encodeURIComponent(kind)}`,
      );
      await expectListReady(page);
      await expect(page.getByLabel("status")).toHaveValue(status, {
        timeout: 15000,
      });
      await expect(page.getByPlaceholder("kind filter")).toHaveValue(kind, {
        timeout: 15000,
      });
    });
  }

  for (const jobId of JOB_IDS) {
    test(`URL all-4 filters seed with job ${jobId.slice(0, 8)}`, async ({
      page,
    }) => {
      const kind = JOB_KINDS[0] ?? "provider_sync";
      await page.goto(
        `${LIST_ROUTE}?status=done&kind=${encodeURIComponent(kind)}` +
          `&load_batch_id=${encodeURIComponent(jobId)}` +
          `&parent_job_id=${encodeURIComponent(jobId)}`,
      );
      await expectListReady(page);
      await expect(page.getByLabel("status")).toHaveValue("done", {
        timeout: 15000,
      });
      await expect(page.getByPlaceholder("load_batch_id")).toHaveValue(jobId, {
        timeout: 15000,
      });
      await expect(page.getByPlaceholder("parent_job_id")).toHaveValue(jobId, {
        timeout: 15000,
      });
    });
  }
});

test.describe("import-jobs live · page_size dimension (URL passthrough)", () => {
  // 목록 UI에는 page_size select가 없으나(useImportJobs page_size:100 고정),
  // PAGE_SIZES 차원으로 URL 쿼리를 교차해 페이지가 임의 무시 쿼리에도 안정적으로
  // 로드되는지 본다(read-only goto). 컨트롤 클릭 없음.
  for (const size of SIZES) {
    test(`list loads with ?page_size=${size} ignored gracefully`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}?page_size=${size}`);
      await expectListReady(page);
    });
  }

  for (const size of SIZES) {
    test(`list loads with status=running&page_size=${size}`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}?status=running&page_size=${size}`);
      await expectListReady(page);
      await expect(page.getByLabel("status")).toHaveValue("running", {
        timeout: 15000,
      });
    });
  }
});

test.describe("import-jobs live · responsive viewports (list)", () => {
  for (const vp of VIEWPORTS) {
    test(`list renders at ${vp.name} (${vp.width}x${vp.height})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`list status select usable at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(LIST_ROUTE);
      await expectListReady(page);
      await expect(page.getByLabel("status")).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("import-jobs live · detail by job id", () => {
  for (const jobId of JOB_IDS) {
    test(`detail loads for ${jobId.slice(0, 8)} — Import job heading`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      await expect(page).toHaveURL(
        new RegExp(`/ops/import-jobs/${jobId}$`),
        { timeout: 15000 },
      );
    });
  }

  for (const jobId of JOB_IDS) {
    test(`detail '목록' back link href for ${jobId.slice(0, 8)}`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      // import-job-detail-client.tsx: 목록 back link → /ops/import-jobs.
      await expect(page.getByRole("link", { name: "목록" })).toHaveAttribute(
        "href",
        "/ops/import-jobs",
        { timeout: 15000 },
      );
    });
  }

  for (const jobId of JOB_IDS) {
    test(`detail Events/Payload sections for ${jobId.slice(0, 8)}`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      // 데이터가 있을 때만 Events/Payload 카드가 렌더되므로 둘 중 하나라도
      // 보이거나, 없으면(빈 DB → isError alert) 조회 실패 alert가 보인다 —
      // PRESENCE 불확실성에 맞춰 느슨하게 OR 단언.
      const eventsOrError = page
        .getByText("Events", { exact: true })
        .or(page.getByText("import job 조회 실패"));
      await expect(eventsOrError.first()).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("import-jobs live · detail event level filter (read-only)", () => {
  for (const jobId of JOB_IDS) {
    test(`detail event level select present or error for ${jobId.slice(
      0,
      8,
    )}`, async ({ page }) => {
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      // event level select는 jobData가 있을 때만 렌더. 없으면 조회 실패 alert.
      const levelOrError = page
        .getByLabel("event level")
        .or(page.getByText("import job 조회 실패"));
      await expect(levelOrError.first()).toBeVisible({ timeout: 15000 });
    });
  }
});

test.describe("import-jobs live · detail responsive viewports", () => {
  for (const vp of VIEWPORTS) {
    const jobId = JOB_IDS[0] ?? "00000000-0000-0000-0000-000000000000";
    test(`detail renders at ${vp.name} for ${jobId.slice(0, 8)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
    });
  }

  for (const vp of VIEWPORTS) {
    const jobId = JOB_IDS[1] ?? JOB_IDS[0] ?? "00000000-0000-0000-0000-000000000000";
    test(`detail back link href at ${vp.name} for ${jobId.slice(
      0,
      8,
    )}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      await expect(page.getByRole("link", { name: "목록" })).toHaveAttribute(
        "href",
        "/ops/import-jobs",
        { timeout: 15000 },
      );
    });
  }
});

test.describe("import-jobs live · list↔detail nav round-trip (read-only)", () => {
  for (const jobId of JOB_IDS) {
    test(`detail → 목록 link navigates back for ${jobId.slice(0, 8)}`, async ({
      page,
    }) => {
      await page.goto(`${LIST_ROUTE}/${encodeURIComponent(jobId)}`);
      await expectDetailReady(page);
      // 내비 링크 클릭은 허용(GET navigation, 비파괴).
      await page.getByRole("link", { name: "목록" }).click();
      await expectListReady(page);
      await expect(page).toHaveURL(/\/ops\/import-jobs$/, { timeout: 15000 });
    });
  }
});

test.describe("import-jobs live · status×viewport cross matrix", () => {
  for (const status of STATUS_OPTIONS) {
    for (const vp of VIEWPORTS) {
      test(`status=${status} at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(`${LIST_ROUTE}?status=${status}`);
        await expectListReady(page);
        await expect(page.getByLabel("status")).toHaveValue(status, {
          timeout: 15000,
        });
      });
    }
  }
});
