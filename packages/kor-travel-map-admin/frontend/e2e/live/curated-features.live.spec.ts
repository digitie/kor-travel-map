import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

/**
 * LIVE (non-mock) Playwright e2e — /admin/curated-features against prod data
 * (1.09M features). NON-DESTRUCTIVE only: page.goto, read assertions, and clicks
 * limited to nav links / status & enabled filter selects / page-size select /
 * search typing (GET). No select/unselect/archive/patch/apply/save mutations.
 *
 * Selectors are reused verbatim from the verified reference spec
 * (e2e/curated-features.spec.ts) and the page source:
 *   - heading: getByRole("heading", { level: 1, name: "Curated features" })
 *   - filters: getByLabel("curated feature search" | "theme filter" |
 *     "provider filter" | "dataset filter" | "curation status filter" |
 *     "page size" | "rule enabled filter")
 *   - column headers: status / feature / source / theme / reuse / updated / actions
 *   - count line: /개 표시/ ; source rules: getByText("Source rules")
 *
 * The route has no /{id} detail page — candidate selection is an in-page surface
 * and the detail external link targets /features/{id}. We therefore exercise the
 * curated-features list route read-only and assert on stable landmarks.
 */

const TIMEOUT = { timeout: 15000 } as const;
const ROUTE = "/admin/curated-features";
const STATUS_FILTERS = ["all", "candidate", "curated", "rejected", "archived"] as const;
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
] as const;

// Stable selector helpers — assert the curated-features console rendered.
async function expectConsoleLoaded(page: import("@playwright/test").Page) {
  await expect(
    page.getByRole("heading", { level: 1, name: "Curated features" }),
  ).toBeVisible(TIMEOUT);
}

async function expectFilterControls(page: import("@playwright/test").Page) {
  await expect(page.getByLabel("curated feature search")).toBeVisible(TIMEOUT);
  await expect(page.getByLabel("curation status filter")).toBeVisible(TIMEOUT);
  await expect(page.getByLabel("page size")).toBeVisible(TIMEOUT);
}

// ---------------------------------------------------------------------------
// Core page-load + control scenarios (always present regardless of fixtures).
// ---------------------------------------------------------------------------
test.describe("curated-features live: page load + controls", () => {
  test("page load: heading + main filter controls visible", async ({ page }) => {
    await page.goto(ROUTE);
    await expectConsoleLoaded(page);
    await expectFilterControls(page);
  });

  test("page load: all filter selects + search visible", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByLabel("curated feature search")).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("theme filter")).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("provider filter")).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("dataset filter")).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("curation status filter")).toBeVisible(TIMEOUT);
    await expect(page.getByLabel("page size")).toBeVisible(TIMEOUT);
  });

  test("page load: candidate table column headers", async ({ page }) => {
    await page.goto(ROUTE);
    await expectConsoleLoaded(page);
    for (const col of [
      "status",
      "feature",
      "source",
      "theme",
      "reuse",
      "updated",
      "actions",
    ]) {
      await expect(
        page.getByRole("columnheader", { name: col, exact: true }).first(),
      ).toBeVisible(TIMEOUT);
    }
  });

  test("page load: count line renders (0 or N candidates)", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
  });

  test("page load: source rules panel + enabled filter", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByText("Source rules", { exact: true })).toBeVisible(
      TIMEOUT,
    );
    await expect(page.getByLabel("rule enabled filter")).toBeVisible(TIMEOUT);
  });

  test("page load: empty selection detail hint visible", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(
      page.getByText("후보를 선택하면 상세를 확인할 수 있습니다."),
    ).toBeVisible(TIMEOUT);
  });

  test("page load: refresh action button present (no click)", async ({ page }) => {
    await page.goto(ROUTE);
    await expectConsoleLoaded(page);
    await expect(
      page.getByRole("button", { name: "새로고침" }),
    ).toBeVisible(TIMEOUT);
  });

  test("status filter default value is candidate", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByLabel("curation status filter")).toHaveValue(
      "candidate",
      TIMEOUT,
    );
  });

  test("page size default value is 50", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByLabel("page size")).toHaveValue("50", TIMEOUT);
  });

  test("rule enabled filter default value is all", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByLabel("rule enabled filter")).toHaveValue(
      "all",
      TIMEOUT,
    );
  });

  test("nav link to Curated features is present", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(
      page.getByRole("link", { name: "Curated features" }),
    ).toBeVisible(TIMEOUT);
  });

  test("pagination next/prev controls render", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page.getByRole("button", { name: "처음" })).toBeVisible(
      TIMEOUT,
    );
    await expect(page.getByRole("button", { name: "다음" })).toBeVisible(
      TIMEOUT,
    );
  });
});

// ---------------------------------------------------------------------------
// Status filter chips (select options) — read-only GET re-query per value.
// ---------------------------------------------------------------------------
test.describe("curated-features live: status filter", () => {
  for (const value of STATUS_FILTERS) {
    test(`status filter selectOption=${value} re-queries`, async ({ page }) => {
      await page.goto(ROUTE);
      const status = page.getByLabel("curation status filter");
      await status.selectOption(value);
      await expect(status).toHaveValue(value, TIMEOUT);
      await expectConsoleLoaded(page);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// Page-size select — every PAGE_SIZES value, read-only.
// ---------------------------------------------------------------------------
test.describe("curated-features live: page size", () => {
  for (const size of F.PAGE_SIZES) {
    test(`page size selectOption=${size}`, async ({ page }) => {
      await page.goto(ROUTE);
      const pageSize = page.getByLabel("page size");
      await pageSize.selectOption(String(size));
      await expect(pageSize).toHaveValue(String(size), TIMEOUT);
      await expectConsoleLoaded(page);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// rule enabled filter — all / enabled / disabled, read-only.
// ---------------------------------------------------------------------------
test.describe("curated-features live: rule enabled filter", () => {
  for (const value of ["all", "enabled", "disabled"] as const) {
    test(`rule enabled filter selectOption=${value}`, async ({ page }) => {
      await page.goto(ROUTE);
      const enabled = page.getByLabel("rule enabled filter");
      await enabled.selectOption(value);
      await expect(enabled).toHaveValue(value, TIMEOUT);
      await expect(
        page.getByText("Source rules", { exact: true }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// Search typing (GET client-side filter) — SEARCH_TERMS fixture.
// Typing is allowed (read-only); we assert the console stays mounted.
// ---------------------------------------------------------------------------
test.describe("curated-features live: search typing", () => {
  for (const term of F.SEARCH_TERMS.slice(0, 16)) {
    test(`search term="${term}" keeps console mounted`, async ({ page }) => {
      await page.goto(ROUTE);
      const search = page.getByLabel("curated feature search");
      await search.fill(term);
      await expect(search).toHaveValue(term, TIMEOUT);
      await expectConsoleLoaded(page);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// CURATED_IDS — search the in-page table by curated id (read-only GET filter).
// Capped to keep total runtime bounded; asserts robust landmarks only.
// ---------------------------------------------------------------------------
test.describe("curated-features live: search by curated id", () => {
  for (const id of F.CURATED_IDS.slice(0, 40)) {
    test(`search curated id=${id}`, async ({ page }) => {
      await page.goto(ROUTE);
      const search = page.getByLabel("curated feature search");
      await search.fill(id);
      await expect(search).toHaveValue(id, TIMEOUT);
      await expectConsoleLoaded(page);
      // empty result -> empty-state OR populated table; both keep count line.
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// Feature-id substrings as search terms (read-only). Exercises the client-side
// filter path over feature_id matching with realistic prod identifiers.
// ---------------------------------------------------------------------------
test.describe("curated-features live: search by feature id", () => {
  for (const fid of F.FEATURE_IDS.slice(0, 24)) {
    test(`search feature id=${fid}`, async ({ page }) => {
      await page.goto(ROUTE);
      const search = page.getByLabel("curated feature search");
      await search.fill(fid);
      await expect(search).toHaveValue(fid, TIMEOUT);
      await expectConsoleLoaded(page);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// Deep-link query params — the page ignores unknown query params, so navigating
// with them is a harmless read-only GET that must still render the console.
// ---------------------------------------------------------------------------
test.describe("curated-features live: deep-link query params", () => {
  for (const status of STATUS_FILTERS) {
    test(`deep-link ?status=${status} loads console`, async ({ page }) => {
      await page.goto(`${ROUTE}?status=${status}`);
      await expectConsoleLoaded(page);
      await expect(page).toHaveURL(new RegExp(`status=${status}`), TIMEOUT);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }

  for (const size of F.PAGE_SIZES) {
    test(`deep-link ?page_size=${size} loads console`, async ({ page }) => {
      await page.goto(`${ROUTE}?page_size=${size}`);
      await expectConsoleLoaded(page);
      await expect(page).toHaveURL(new RegExp(`page_size=${size}`), TIMEOUT);
      await expectFilterControls(page);
    });
  }

  for (const term of F.SEARCH_TERMS.slice(0, 12)) {
    test(`deep-link ?q=${term} loads console`, async ({ page }) => {
      await page.goto(`${ROUTE}?q=${encodeURIComponent(term)}`);
      await expectConsoleLoaded(page);
      await expect(page.getByLabel("curated feature search")).toBeVisible(
        TIMEOUT,
      );
    });
  }
});

// ---------------------------------------------------------------------------
// Combined status filter x page-size — cross-dimension read-only matrix.
// ---------------------------------------------------------------------------
test.describe("curated-features live: status x page-size matrix", () => {
  for (const status of STATUS_FILTERS) {
    for (const size of F.PAGE_SIZES) {
      test(`status=${status} + page_size=${size}`, async ({ page }) => {
        await page.goto(ROUTE);
        const statusSel = page.getByLabel("curation status filter");
        const pageSizeSel = page.getByLabel("page size");
        await statusSel.selectOption(status);
        await pageSizeSel.selectOption(String(size));
        await expect(statusSel).toHaveValue(status, TIMEOUT);
        await expect(pageSizeSel).toHaveValue(String(size), TIMEOUT);
        await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
      });
    }
  }
});

// ---------------------------------------------------------------------------
// Responsive viewport scenarios — setViewportSize then goto, assert console.
// ---------------------------------------------------------------------------
test.describe("curated-features live: responsive viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`viewport ${vp.name} ${vp.width}x${vp.height}: console + heading`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectConsoleLoaded(page);
    });

    test(`viewport ${vp.name} ${vp.width}x${vp.height}: filter controls`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectFilterControls(page);
    });

    test(`viewport ${vp.name} ${vp.width}x${vp.height}: count line`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });

    test(`viewport ${vp.name} ${vp.width}x${vp.height}: source rules panel`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expect(
        page.getByText("Source rules", { exact: true }),
      ).toBeVisible(TIMEOUT);
    });
  }
});

// ---------------------------------------------------------------------------
// Category-code search terms — CATEGORY_CODES fixture as read-only filter input.
// Codes are unlikely to match curated rows, exercising the empty-state path.
// ---------------------------------------------------------------------------
test.describe("curated-features live: search by category code", () => {
  for (const code of F.CATEGORY_CODES.slice(0, 20)) {
    test(`search category code=${code}`, async ({ page }) => {
      await page.goto(ROUTE);
      const search = page.getByLabel("curated feature search");
      await search.fill(code);
      await expect(search).toHaveValue(code, TIMEOUT);
      await expectConsoleLoaded(page);
      await expect(page.getByText(/개 표시/).first()).toBeVisible(TIMEOUT);
    });
  }
});
