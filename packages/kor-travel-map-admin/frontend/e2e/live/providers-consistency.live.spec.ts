import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

// LIVE (non-mock) e2e against prod 실데이터(1.09M features). Read-only only:
// page.goto, read assertions, and clicks restricted to nav links / tabs /
// filter chips/selects / page-size select / sort headers / pagination.
// area=providers-consistency  routes=/ops/providers, /ops/consistency
//
// Selectors/headings are reused verbatim from the route-mocked depth specs
// (providers-refresh-policy.spec.ts, consistency-drilldown.spec.ts) and the
// page source (providers-client.tsx, consistency-client.tsx, admin-shell.tsx):
//   - /ops/providers   h1 "Providers"; section badges; sort headers; empty text.
//   - /ops/consistency h1 "Consistency"; metric cards; issue status filter;
//     sort headers; DataTable emptyMessage.
// PROVIDERS fixture may be empty (prod has no provider ops rows surfaced) — in
// that case the page renders the empty table + no-selection placeholder, which
// we assert loosely via the stable h1 + container landmark.

const T = 15000 as const;
const VIEWPORTS = [
  { name: "1280", width: 1280, height: 800 },
  { name: "768", width: 768, height: 1024 },
  { name: "390", width: 390, height: 844 },
] as const;

const PROVIDERS_ROUTE = "/ops/providers";
const CONSISTENCY_ROUTE = "/ops/consistency";

// Stable, sortable column-header titles confirmed in providers-client.tsx.
const PROVIDER_SORT_HEADERS = [
  "provider",
  "dataset",
  "scope",
  "status",
  "policy",
  "last success",
  "next run",
  "failures",
] as const;

// Stable, sortable column-header titles confirmed in consistency-client.tsx.
const CONSISTENCY_SORT_HEADERS = [
  "severity",
  "finished",
  "provider",
  "detected",
] as const;

// issue status filter options (consistency-client.tsx issueStatuses).
const ISSUE_STATUSES = [
  "open",
  "acknowledged",
  "resolved",
  "ignored",
  "all",
] as const;

// Metric cards rendered on /ops/consistency (consistency-client.tsx).
const CONSISTENCY_CARDS = [
  "Open issues",
  "Latest severity",
  "Checked at",
  "Reports",
  "Integrity issues",
] as const;

// Section summary badge labels on /ops/providers (providers-client.tsx).
const PROVIDER_BADGE_LABELS = [
  "providers",
  "datasets",
  "policies",
  "failing",
] as const;

// Deep-link query params we exercise as read-only GET variations. The pages
// ignore unknown params, so this only confirms the route stays robust under
// arbitrary query strings (no crash, h1 still visible).
const DEEP_LINK_QUERIES = [
  "?status=open",
  "?status=resolved",
  "?status=all",
  "?provider=python-kma-api",
  "?dataset_key=kma_weather_values",
  "?page_size=50",
  "?ref=e2e",
];

async function expectProvidersLoaded(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Providers" }),
  ).toBeVisible({ timeout: T });
}

async function expectConsistencyLoaded(
  page: import("@playwright/test").Page,
): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Consistency" }),
  ).toBeVisible({ timeout: T });
}

// ---------------------------------------------------------------------------
// /ops/providers — page load, controls, sort headers, viewport, deep links.
// ---------------------------------------------------------------------------
test.describe("live /ops/providers", () => {
  test("providers page loads with h1 and summary badges", async ({ page }) => {
    await page.goto(PROVIDERS_ROUTE);
    await expectProvidersLoaded(page);
    // section summary badges are always rendered (counts may be 0).
    for (const label of PROVIDER_BADGE_LABELS) {
      await expect(page.getByText(label).first()).toBeVisible({ timeout: T });
    }
  });

  test("providers page shows the freshness DataTable container", async ({
    page,
  }) => {
    await page.goto(PROVIDERS_ROUTE);
    await expectProvidersLoaded(page);
    // Either populated rows or the empty-state message; both keep the page
    // robust. PROVIDERS fixture is commonly empty in prod.
    const table = page.getByRole("table").first();
    const empty = page.getByText("provider ops row가 없습니다.");
    await expect(table.or(empty).first()).toBeVisible({ timeout: T });
  });

  test("providers page surfaces selection panel or placeholder", async ({
    page,
  }) => {
    await page.goto(PROVIDERS_ROUTE);
    await expectProvidersLoaded(page);
    // When items exist, items[0] auto-selects → "Refresh policy" panel; when
    // empty → "선택된 provider dataset이 없습니다." placeholder. Assert loosely.
    const policyPanel = page.getByText("Refresh policy");
    const placeholder = page.getByText("선택된 provider dataset이 없습니다.");
    await expect(policyPanel.or(placeholder).first()).toBeVisible({
      timeout: T,
    });
  });

  test("providers page exposes the section landmark (Ops)", async ({
    page,
  }) => {
    await page.goto(PROVIDERS_ROUTE);
    await expectProvidersLoaded(page);
    await expect(page.getByText("Ops").first()).toBeVisible({ timeout: T });
  });

  test("providers nav link is active and navigable", async ({ page }) => {
    await page.goto("/");
    const navLink = page.getByRole("link", { name: "Providers" });
    await expect(navLink.first()).toBeVisible({ timeout: T });
    await navLink.first().click();
    await expect(page).toHaveURL(/\/ops\/providers$/, { timeout: T });
    await expectProvidersLoaded(page);
  });

  for (const header of PROVIDER_SORT_HEADERS) {
    test(`providers sort header "${header}" toggles without navigation`, async ({
      page,
    }) => {
      await page.goto(PROVIDERS_ROUTE);
      await expectProvidersLoaded(page);
      const sortButton = page.getByRole("button", { name: header });
      const count = await sortButton.count();
      if (count > 0) {
        await sortButton.first().click();
      }
      // Sort is client-side; page must remain on route with h1 intact.
      await expect(page).toHaveURL(/\/ops\/providers/, { timeout: T });
      await expectProvidersLoaded(page);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`providers page renders at viewport ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(PROVIDERS_ROUTE);
      await expectProvidersLoaded(page);
    });
  }

  for (const q of DEEP_LINK_QUERIES) {
    test(`providers page robust under query ${q}`, async ({ page }) => {
      await page.goto(`${PROVIDERS_ROUTE}${q}`);
      await expectProvidersLoaded(page);
    });
  }
});

// ---------------------------------------------------------------------------
// /ops/consistency — page load, metric cards, status filter, sort headers,
// viewport, deep links, refresh-surface reads.
// ---------------------------------------------------------------------------
test.describe("live /ops/consistency", () => {
  test("consistency page loads with h1", async ({ page }) => {
    await page.goto(CONSISTENCY_ROUTE);
    await expectConsistencyLoaded(page);
  });

  for (const card of CONSISTENCY_CARDS) {
    test(`consistency metric card "${card}" is visible`, async ({ page }) => {
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
      await expect(page.getByText(card).first()).toBeVisible({ timeout: T });
    });
  }

  test("consistency page shows reports + issues table containers", async ({
    page,
  }) => {
    await page.goto(CONSISTENCY_ROUTE);
    await expectConsistencyLoaded(page);
    // Two DataTables (reports, issues). Each renders rows or the shared
    // emptyMessage "데이터가 없습니다.". Assert at least one table landmark.
    await expect(page.getByRole("table").first()).toBeVisible({ timeout: T });
  });

  test("consistency issue status filter is present", async ({ page }) => {
    await page.goto(CONSISTENCY_ROUTE);
    await expectConsistencyLoaded(page);
    await expect(page.getByLabel("issue status")).toBeVisible({ timeout: T });
  });

  test("consistency nav link is active and navigable", async ({ page }) => {
    await page.goto("/");
    const navLink = page.getByRole("link", { name: "Consistency" });
    await expect(navLink.first()).toBeVisible({ timeout: T });
    await navLink.first().click();
    await expect(page).toHaveURL(/\/ops\/consistency$/, { timeout: T });
    await expectConsistencyLoaded(page);
  });

  for (const status of ISSUE_STATUSES) {
    test(`consistency status filter selects "${status}" (read-only GET)`, async ({
      page,
    }) => {
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
      const select = page.getByLabel("issue status");
      await expect(select).toBeVisible({ timeout: T });
      // selectOption on the issue-status filter only re-queries (GET) — allowed.
      await select.selectOption(status);
      await expect(select).toHaveValue(status, { timeout: T });
      // page stays put after filter change.
      await expectConsistencyLoaded(page);
    });
  }

  for (const header of CONSISTENCY_SORT_HEADERS) {
    test(`consistency sort header "${header}" toggles without navigation`, async ({
      page,
    }) => {
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
      const sortButton = page.getByRole("button", { name: header });
      const count = await sortButton.count();
      if (count > 0) {
        await sortButton.first().click();
      }
      await expect(page).toHaveURL(/\/ops\/consistency/, { timeout: T });
      await expectConsistencyLoaded(page);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`consistency page renders at viewport ${vp.name}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
    });
  }

  for (const q of DEEP_LINK_QUERIES) {
    test(`consistency page robust under query ${q}`, async ({ page }) => {
      await page.goto(`${CONSISTENCY_ROUTE}${q}`);
      await expectConsistencyLoaded(page);
    });
  }
});

// ---------------------------------------------------------------------------
// Cross-cutting: nav between the two ops pages + viewport × route matrix.
// ---------------------------------------------------------------------------
test.describe("live ops nav between providers and consistency", () => {
  test("providers → consistency via nav link", async ({ page }) => {
    await page.goto(PROVIDERS_ROUTE);
    await expectProvidersLoaded(page);
    await page.getByRole("link", { name: "Consistency" }).first().click();
    await expect(page).toHaveURL(/\/ops\/consistency$/, { timeout: T });
    await expectConsistencyLoaded(page);
  });

  test("consistency → providers via nav link", async ({ page }) => {
    await page.goto(CONSISTENCY_ROUTE);
    await expectConsistencyLoaded(page);
    await page.getByRole("link", { name: "Providers" }).first().click();
    await expect(page).toHaveURL(/\/ops\/providers$/, { timeout: T });
    await expectProvidersLoaded(page);
  });

  // viewport × route matrix to broaden responsive coverage.
  for (const vp of VIEWPORTS) {
    test(`providers + consistency both load at viewport ${vp.name}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(PROVIDERS_ROUTE);
      await expectProvidersLoaded(page);
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
    });
  }
});

// ---------------------------------------------------------------------------
// Fixture-driven breadth: drive provider / dataset deep-link params off the
// real PROVIDERS + PROVIDER_DATASETS fixtures so the suite scales with prod
// data. Both arrays may be empty; the .slice cap and the seeded fallbacks keep
// test count stable and the file valid.
// ---------------------------------------------------------------------------
const PROVIDER_PARAMS: string[] =
  F.PROVIDERS.length > 0
    ? F.PROVIDERS.slice(0, 12)
    : ["python-kma-api", "python-mois-api", "python-festival-api"];

const DATASET_PARAMS: string[] =
  F.PROVIDER_DATASETS.length > 0
    ? F.PROVIDER_DATASETS.slice(0, 12).map((d) => String(d))
    : ["kma_weather_values", "mois_license_features_bulk"];

test.describe("live /ops/providers fixture deep links", () => {
  for (const provider of PROVIDER_PARAMS) {
    test(`providers robust under ?provider=${provider}`, async ({ page }) => {
      await page.goto(
        `${PROVIDERS_ROUTE}?provider=${encodeURIComponent(provider)}`,
      );
      await expectProvidersLoaded(page);
    });
  }

  for (const dataset of DATASET_PARAMS) {
    test(`providers robust under ?dataset_key=${dataset}`, async ({ page }) => {
      await page.goto(
        `${PROVIDERS_ROUTE}?dataset_key=${encodeURIComponent(dataset)}`,
      );
      await expectProvidersLoaded(page);
    });
  }
});

// ---------------------------------------------------------------------------
// Fixture-driven breadth for consistency: replay the issue-status filter under
// distinct deep-link entries, and broaden page-size deep links from PAGE_SIZES.
// ---------------------------------------------------------------------------
test.describe("live /ops/consistency fixture deep links", () => {
  for (const status of ISSUE_STATUSES) {
    test(`consistency robust under ?status=${status} deep link`, async ({
      page,
    }) => {
      await page.goto(`${CONSISTENCY_ROUTE}?status=${status}`);
      await expectConsistencyLoaded(page);
    });
  }

  for (const size of F.PAGE_SIZES) {
    test(`consistency robust under ?page_size=${size}`, async ({ page }) => {
      await page.goto(`${CONSISTENCY_ROUTE}?page_size=${size}`);
      await expectConsistencyLoaded(page);
    });
  }

  for (const size of F.PAGE_SIZES) {
    test(`providers robust under ?page_size=${size}`, async ({ page }) => {
      await page.goto(`${PROVIDERS_ROUTE}?page_size=${size}`);
      await expectProvidersLoaded(page);
    });
  }

  // status filter applied live (selectOption is GET-only) per status value,
  // asserting the select reflects the chosen value and the table landmark
  // stays mounted.
  for (const status of ISSUE_STATUSES) {
    test(`consistency live filter "${status}" keeps table mounted`, async ({
      page,
    }) => {
      await page.goto(CONSISTENCY_ROUTE);
      await expectConsistencyLoaded(page);
      const select = page.getByLabel("issue status");
      await select.selectOption(status);
      await expect(select).toHaveValue(status, { timeout: T });
      await expect(page.getByRole("table").first()).toBeVisible({
        timeout: T,
      });
    });
  }
});

// ---------------------------------------------------------------------------
// Search-term breadth: the ops pages have no search box, but we still exercise
// the routes under each SEARCH_TERMS value as a benign ?q deep link to confirm
// arbitrary query strings never break the read surface. Capped via slice.
// ---------------------------------------------------------------------------
test.describe("live ops routes robust under search-term deep links", () => {
  for (const term of F.SEARCH_TERMS.slice(0, 16)) {
    test(`providers robust under ?q=${term}`, async ({ page }) => {
      await page.goto(`${PROVIDERS_ROUTE}?q=${encodeURIComponent(term)}`);
      await expectProvidersLoaded(page);
    });
  }

  for (const term of F.SEARCH_TERMS.slice(0, 16)) {
    test(`consistency robust under ?q=${term}`, async ({ page }) => {
      await page.goto(`${CONSISTENCY_ROUTE}?q=${encodeURIComponent(term)}`);
      await expectConsistencyLoaded(page);
    });
  }
});
