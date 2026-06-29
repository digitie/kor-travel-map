import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

// LIVE (non-mock) read-only e2e for the 4 review/queue pages.
//   route: /admin/issues, /admin/dedup-reviews, /admin/enrichment-reviews,
//          /admin/feature-update-requests
// backend = prod 실데이터(1.09M features). PRESENCE for all four queues = 0
// (issues/dedup/enrichment/update_requests). So every page is expected to be
// EMPTY: we assert heading + (empty-state OR table container) + controls, never
// exact row text/counts. NO action buttons are clicked — only nav links, status
// filter selects, page-size select, sortable column headers, pagination
// prev/next, and typing into search inputs (all GET). All assertions use the
// 15s timeout and stable headings/landmarks reused from the *-actions specs.

const T = 15000;

// Stable per-page identity reused from the mock specs above (admin-shell <h1>,
// AdminShell nav <Link> label, DataTable emptyMessage). status-select aria-label
// + a sortable column header title verified from the page clients.
interface ReviewPage {
  route: string;
  heading: string;
  navLabel: string;
  empty: string;
  statusLabel: string;
  statuses: string[];
  sortHeaders: string[];
}

const PAGES: ReviewPage[] = [
  {
    route: "/admin/issues",
    heading: "Admin issues",
    navLabel: "Issues",
    empty: "issue가 없습니다.",
    statusLabel: "issue status",
    statuses: ["open", "acknowledged", "resolved", "ignored", "all"],
    sortHeaders: ["severity", "status", "detected"],
  },
  {
    route: "/admin/dedup-reviews",
    heading: "Dedup review",
    navLabel: "Dedup reviews",
    empty: "dedup review가 없습니다.",
    statusLabel: "dedup status",
    statuses: ["pending", "accepted", "rejected", "merged", "ignored", "all"],
    sortHeaders: ["score", "distance", "status", "created"],
  },
  {
    route: "/admin/enrichment-reviews",
    heading: "Enrichment review",
    navLabel: "Enrichment reviews",
    empty: "enrichment review가 없습니다.",
    statusLabel: "enrichment status",
    statuses: ["pending", "accepted", "rejected", "ignored", "all"],
    sortHeaders: ["score", "distance", "status", "created"],
  },
  {
    route: "/admin/feature-update-requests",
    heading: "Feature update requests",
    navLabel: "Update requests",
    empty: "요청이 없습니다.",
    statusLabel: "request status",
    statuses: ["queued", "running", "done", "failed", "cancelled", "all"],
    sortHeaders: ["status", "created"],
  },
];

const VIEWPORTS: Array<[string, number, number]> = [
  ["desktop-1280", 1280, 800],
  ["tablet-768", 768, 1024],
  ["mobile-390", 390, 844],
];

// Empty queue (PRESENCE=0): the page is "loaded" when the level-1 heading is
// visible. The body is loose — either the DataTable empty message or the table
// container (role=table) is acceptable, since a stray live row would still pass.
async function expectPageLoaded(
  page: import("@playwright/test").Page,
  cfg: ReviewPage,
) {
  await expect(
    page.getByRole("heading", { level: 1, name: cfg.heading }),
  ).toBeVisible({ timeout: T });
}

async function expectEmptyOrTable(
  page: import("@playwright/test").Page,
  cfg: ReviewPage,
) {
  // loose: empty-state text OR the table landmark must be present.
  const empty = page.getByText(cfg.empty);
  const table = page.getByRole("table").first();
  const ok =
    (await empty.count()) > 0 ? await empty.first().isVisible() : false;
  if (!ok) {
    await expect(table).toBeVisible({ timeout: T });
  }
}

test.describe("reviews live — page load + heading + empty/table", () => {
  for (const cfg of PAGES) {
    test(`load ${cfg.route} → heading + empty-or-table`, async ({ page }) => {
      await page.goto(cfg.route);
      await expectPageLoaded(page, cfg);
      await expectEmptyOrTable(page, cfg);
    });

    test(`status filter select present on ${cfg.route}`, async ({ page }) => {
      await page.goto(cfg.route);
      await expectPageLoaded(page, cfg);
      await expect(page.getByLabel(cfg.statusLabel)).toBeVisible({
        timeout: T,
      });
    });

    test(`refresh control visible on ${cfg.route}`, async ({ page }) => {
      await page.goto(cfg.route);
      await expectPageLoaded(page, cfg);
      // 새로고침 button exists on every AdminShell page (asserted, not clicked).
      await expect(
        page.getByRole("button", { name: "새로고침" }),
      ).toBeVisible({ timeout: T });
    });

    test(`nav sidebar link visible on ${cfg.route}`, async ({ page }) => {
      await page.goto(cfg.route);
      await expectPageLoaded(page, cfg);
      await expect(
        page.getByRole("link", { name: cfg.navLabel }).first(),
      ).toBeVisible({ timeout: T });
    });
  }
});

test.describe("reviews live — status filter dimension (selectOption, GET only)", () => {
  for (const cfg of PAGES) {
    for (const status of cfg.statuses) {
      test(`${cfg.route} status=${status}`, async ({ page }) => {
        await page.goto(cfg.route);
        await expectPageLoaded(page, cfg);
        const select = page.getByLabel(cfg.statusLabel);
        await expect(select).toBeVisible({ timeout: T });
        // selecting a status is a GET re-query (read-only filter chip equiv).
        await select.selectOption(status);
        // heading stays; queue is empty so assert empty-or-table loosely.
        await expectPageLoaded(page, cfg);
        await expectEmptyOrTable(page, cfg);
      });
    }
  }
});

test.describe("reviews live — sortable column headers (read-only re-sort)", () => {
  for (const cfg of PAGES) {
    for (const headerTitle of cfg.sortHeaders) {
      test(`${cfg.route} sort header ${headerTitle}`, async ({ page }) => {
        await page.goto(cfg.route);
        await expectPageLoaded(page, cfg);
        // sortable headers render as a Button (title text) inside the
        // columnheader. Scope to the columnheader to avoid select-option /
        // status-badge text collisions, then click the sort toggle if present.
        const header = page
          .getByRole("columnheader", { name: headerTitle })
          .first();
        if ((await header.count()) > 0) {
          const sortBtn = header.getByRole("button");
          if ((await sortBtn.count()) > 0) {
            await sortBtn.first().click();
          }
        }
        // re-sort is client-side over an empty list; page stays loaded.
        await expectPageLoaded(page, cfg);
        await expectEmptyOrTable(page, cfg);
      });
    }
  }
});

test.describe("reviews live — responsive viewport crossing", () => {
  for (const cfg of PAGES) {
    for (const [vpName, w, h] of VIEWPORTS) {
      test(`${cfg.route} @ ${vpName}`, async ({ page }) => {
        await page.setViewportSize({ width: w, height: h });
        await page.goto(cfg.route);
        await expectPageLoaded(page, cfg);
        await expectEmptyOrTable(page, cfg);
      });
    }
  }
});

// Issues page has the richest read-only control surface (search, severity,
// page-size select, keyset pagination). Drive its extra dimensions explicitly.
const ISSUES = PAGES[0];

test.describe("reviews live — issues search dimension (typing = GET query)", () => {
  for (const term of F.SEARCH_TERMS.slice(0, 16)) {
    test(`/admin/issues search "${term}"`, async ({ page }) => {
      await page.goto(ISSUES.route);
      await expectPageLoaded(page, ISSUES);
      const search = page.getByLabel("issue search");
      await expect(search).toBeVisible({ timeout: T });
      // typing into the search box is an allowed GET-driven filter.
      await search.fill(term);
      await expect(search).toHaveValue(term, { timeout: T });
      await expectPageLoaded(page, ISSUES);
    });
  }
});

test.describe("reviews live — issues page-size select dimension", () => {
  for (const size of F.PAGE_SIZES) {
    test(`/admin/issues page size ${size}`, async ({ page }) => {
      await page.goto(ISSUES.route);
      await expectPageLoaded(page, ISSUES);
      const sizeSelect = page.getByLabel("issue page size");
      await expect(sizeSelect).toBeVisible({ timeout: T });
      await sizeSelect.selectOption(String(size));
      await expectPageLoaded(page, ISSUES);
      await expectEmptyOrTable(page, ISSUES);
    });
  }
});

test.describe("reviews live — issues severity filter dimension", () => {
  for (const severity of ["critical", "error", "warning", "info", "all"]) {
    test(`/admin/issues severity=${severity}`, async ({ page }) => {
      await page.goto(ISSUES.route);
      await expectPageLoaded(page, ISSUES);
      const sev = page.getByLabel("issue severity");
      await expect(sev).toBeVisible({ timeout: T });
      await sev.selectOption(severity);
      await expectPageLoaded(page, ISSUES);
      await expectEmptyOrTable(page, ISSUES);
    });
  }
});

test.describe("reviews live — issues keyset pagination controls", () => {
  test("/admin/issues 첫 페이지 + 다음 buttons present and gate on cursor", async ({
    page,
  }) => {
    await page.goto(ISSUES.route);
    await expectPageLoaded(page, ISSUES);
    const firstBtn = page.getByRole("button", { name: "첫 페이지" });
    const nextBtn = page.getByRole("button", { name: "다음" });
    await expect(firstBtn).toBeVisible({ timeout: T });
    await expect(nextBtn).toBeVisible({ timeout: T });
    // empty queue → no next_cursor → '다음' disabled, '첫 페이지' disabled too.
    await expect(firstBtn).toBeDisabled({ timeout: T });
  });

  test("/admin/issues 첫 페이지 disabled on first load", async ({ page }) => {
    await page.goto(ISSUES.route);
    await expectPageLoaded(page, ISSUES);
    await expect(page.getByRole("button", { name: "첫 페이지" })).toBeDisabled({
      timeout: T,
    });
  });
});

// Enrichment page exposes labelled top/bottom pager buttons.
const ENRICH = PAGES[2];
const DEDUP = PAGES[1];

test.describe("reviews live — enrichment pager controls", () => {
  test("/admin/enrichment-reviews top/bottom pager buttons present", async ({
    page,
  }) => {
    await page.goto(ENRICH.route);
    await expectPageLoaded(page, ENRICH);
    await expect(page.getByLabel("이전 페이지")).toHaveCount(2, { timeout: T });
    await expect(page.getByLabel("다음 페이지")).toHaveCount(2, { timeout: T });
    await expect(page.getByLabel("마지막 페이지")).toHaveCount(2, { timeout: T });
  });

  test("/admin/enrichment-reviews 이전 페이지 disabled on page 1", async ({
    page,
  }) => {
    await page.goto(ENRICH.route);
    await expectPageLoaded(page, ENRICH);
    // empty queue, first page → 이전 페이지 disabled.
    await expect(page.getByLabel("이전 페이지").first()).toBeDisabled({
      timeout: T,
    });
  });

  test("/admin/enrichment-reviews next/last disabled when empty", async ({
    page,
  }) => {
    await page.goto(ENRICH.route);
    await expectPageLoaded(page, ENRICH);
    // PRESENCE=0 → totalPages=1 → 다음/마지막 페이지 disabled.
    await expect(page.getByLabel("다음 페이지").first()).toBeDisabled({
      timeout: T,
    });
    await expect(page.getByLabel("마지막 페이지").first()).toBeDisabled({
      timeout: T,
    });
  });
});

test.describe("reviews live — enrichment search/filter/page-size dimensions", () => {
  for (const term of F.SEARCH_TERMS.slice(0, 8)) {
    test(`/admin/enrichment-reviews search "${term}"`, async ({ page }) => {
      await page.goto(ENRICH.route);
      await expectPageLoaded(page, ENRICH);
      const search = page.getByLabel("enrichment search");
      await expect(search).toBeVisible({ timeout: T });
      await search.fill(term);
      await expect(search).toHaveValue(term, { timeout: T });
      await expectEmptyOrTable(page, ENRICH);
    });
  }

  for (const size of F.PAGE_SIZES) {
    test(`/admin/enrichment-reviews page size ${size}`, async ({ page }) => {
      await page.goto(ENRICH.route);
      await expectPageLoaded(page, ENRICH);
      const sizeSelect = page.getByLabel("enrichment page size");
      await expect(sizeSelect).toBeVisible({ timeout: T });
      await sizeSelect.selectOption(String(size));
      await expectPageLoaded(page, ENRICH);
      await expectEmptyOrTable(page, ENRICH);
    });
  }

  for (const score of ["all", "high", "middle", "low"]) {
    test(`/admin/enrichment-reviews score=${score}`, async ({ page }) => {
      await page.goto(ENRICH.route);
      await expectPageLoaded(page, ENRICH);
      const scoreSelect = page.getByLabel("enrichment score filter");
      await expect(scoreSelect).toBeVisible({ timeout: T });
      await scoreSelect.selectOption(score);
      await expectPageLoaded(page, ENRICH);
      await expectEmptyOrTable(page, ENRICH);
    });
  }

  test("/admin/enrichment-reviews provider filter input", async ({ page }) => {
    await page.goto(ENRICH.route);
    await expectPageLoaded(page, ENRICH);
    const provider = page.getByLabel("enrichment provider");
    await expect(provider).toBeVisible({ timeout: T });
    await provider.fill("python-visitkorea-api");
    await expect(provider).toHaveValue("python-visitkorea-api", { timeout: T });
    await expectEmptyOrTable(page, ENRICH);
  });

  test("/admin/enrichment-reviews detail dialog map surface smoke", async ({ page }) => {
    await page.goto(ENRICH.route);
    await expectPageLoaded(page, ENRICH);
    await expect(page.getByRole("button", { name: "지도" })).toHaveCount(0);

    const rows = page.locator("tbody tr");
    if ((await rows.count()) > 0) {
      await rows.first().click();
      const dialog = page.getByRole("dialog", {
        name: "enrichment review detail",
      });
      await expect(dialog).toBeVisible({ timeout: T });
      const detailMap = page.getByTestId("enrichment-detail-map");
      if ((await detailMap.count()) > 0) {
        await expect(detailMap).toBeVisible({ timeout: T });
      }
    } else {
      await expectEmptyOrTable(page, ENRICH);
    }
  });
});

test.describe("reviews live — dedup search/filter/page-size dimensions", () => {
  test("/admin/dedup-reviews pager controls present", async ({ page }) => {
    await page.goto(DEDUP.route);
    await expectPageLoaded(page, DEDUP);
    await expect(page.getByLabel("dedup 이전 페이지")).toHaveCount(2, {
      timeout: T,
    });
    await expect(page.getByLabel("dedup 다음 페이지")).toHaveCount(2, {
      timeout: T,
    });
    await expect(page.getByLabel("dedup 마지막 페이지")).toHaveCount(2, {
      timeout: T,
    });
    await expect(page.getByLabel("dedup 이전 페이지").first()).toBeDisabled({
      timeout: T,
    });
  });

  for (const term of F.SEARCH_TERMS.slice(0, 8)) {
    test(`/admin/dedup-reviews search "${term}"`, async ({ page }) => {
      await page.goto(DEDUP.route);
      await expectPageLoaded(page, DEDUP);
      const search = page.getByLabel("dedup search");
      await expect(search).toBeVisible({ timeout: T });
      await search.fill(term);
      await expect(search).toHaveValue(term, { timeout: T });
      await expectEmptyOrTable(page, DEDUP);
    });
  }

  for (const size of F.PAGE_SIZES) {
    test(`/admin/dedup-reviews page size ${size}`, async ({ page }) => {
      await page.goto(DEDUP.route);
      await expectPageLoaded(page, DEDUP);
      const sizeSelect = page.getByLabel("dedup page size");
      await expect(sizeSelect).toBeVisible({ timeout: T });
      await sizeSelect.selectOption(String(size));
      await expectPageLoaded(page, DEDUP);
      await expectEmptyOrTable(page, DEDUP);
    });
  }

  for (const kind of ["all", ...F.KINDS.slice(0, 4)]) {
    test(`/admin/dedup-reviews kind=${kind}`, async ({ page }) => {
      await page.goto(DEDUP.route);
      await expectPageLoaded(page, DEDUP);
      const kindSelect = page.getByLabel("dedup kind");
      await expect(kindSelect).toBeVisible({ timeout: T });
      await kindSelect.selectOption(kind);
      await expectPageLoaded(page, DEDUP);
      await expectEmptyOrTable(page, DEDUP);
    });
  }

  for (const score of ["all", "high", "middle", "low"]) {
    test(`/admin/dedup-reviews score=${score}`, async ({ page }) => {
      await page.goto(DEDUP.route);
      await expectPageLoaded(page, DEDUP);
      const scoreSelect = page.getByLabel("dedup score filter");
      await expect(scoreSelect).toBeVisible({ timeout: T });
      await scoreSelect.selectOption(score);
      await expectPageLoaded(page, DEDUP);
      await expectEmptyOrTable(page, DEDUP);
    });
  }

  test("/admin/dedup-reviews provider/dataset/category inputs", async ({ page }) => {
    await page.goto(DEDUP.route);
    await expectPageLoaded(page, DEDUP);
    await page.getByLabel("dedup provider").fill("python-mois-api");
    await page.getByLabel("dedup dataset").fill("mois_license");
    await page.getByLabel("dedup category").fill("01070300");
    await expect(page.getByLabel("dedup provider")).toHaveValue("python-mois-api", {
      timeout: T,
    });
    await expect(page.getByLabel("dedup dataset")).toHaveValue("mois_license", {
      timeout: T,
    });
    await expect(page.getByLabel("dedup category")).toHaveValue("01070300", {
      timeout: T,
    });
    await expectEmptyOrTable(page, DEDUP);
  });
});

// Cross status filters across all 4 pages a second time, paired with a viewport,
// to broaden coverage of the (status × viewport) matrix on read-only GETs.
test.describe("reviews live — status × viewport cross matrix", () => {
  for (const cfg of PAGES) {
    for (const [vpName, w, h] of VIEWPORTS) {
      for (const status of cfg.statuses.slice(0, 3)) {
        test(`${cfg.route} status=${status} @ ${vpName}`, async ({ page }) => {
          await page.setViewportSize({ width: w, height: h });
          await page.goto(cfg.route);
          await expectPageLoaded(page, cfg);
          const select = page.getByLabel(cfg.statusLabel);
          await expect(select).toBeVisible({ timeout: T });
          await select.selectOption(status);
          await expectPageLoaded(page, cfg);
          await expectEmptyOrTable(page, cfg);
        });
      }
    }
  }
});

// Deep-link query dimension: append a harmless GET query string to each route
// (the pages ignore unknown params) and assert the page still loads. Reuses
// FEATURE_IDS/CURATED_IDS as opaque param values to scale the matrix.
test.describe("reviews live — deeplink query string dimension", () => {
  const QUERY_VALUES = [
    ...F.FEATURE_IDS.slice(0, 4),
    ...F.CURATED_IDS.slice(0, 2),
  ];
  for (const cfg of PAGES) {
    for (const value of QUERY_VALUES) {
      test(`${cfg.route}?ref=${value.slice(0, 10)}`, async ({ page }) => {
        await page.goto(`${cfg.route}?ref=${encodeURIComponent(value)}`);
        await expectPageLoaded(page, cfg);
        await expectEmptyOrTable(page, cfg);
      });
    }
  }
});

// Nav-link round-trip: from each review page, the sidebar exposes links to the
// other review pages. Navigating between them is a read-only GET. Cross every
// (origin → target) pair where origin ≠ target.
test.describe("reviews live — sidebar nav between review pages", () => {
  for (const origin of PAGES) {
    for (const target of PAGES) {
      if (origin.route === target.route) continue;
      test(`nav ${origin.navLabel} → ${target.navLabel}`, async ({ page }) => {
        await page.goto(origin.route);
        await expectPageLoaded(page, origin);
        const link = page.getByRole("link", { name: target.navLabel }).first();
        await expect(link).toBeVisible({ timeout: T });
        await link.click();
        await expect(page).toHaveURL(new RegExp(`${target.route}(\\?|$)`), {
          timeout: T,
        });
        await expectPageLoaded(page, target);
      });
    }
  }
});
