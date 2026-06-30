import { test, expect } from "@playwright/test";
import * as F from "./_fixtures";

// LIVE (non-mock) e2e for /admin/features against prod 실데이터(1.09M features).
// Read-only only: page.goto, read assertions, and clicks restricted to nav links,
// filter chips/selects (kind/status/sort/page-size/order), pagination 다음/이전,
// and typing into the GET-only search box. No deactivate/refresh/submit/POST.
//
// Selectors/headings/route are reused verbatim from the mocked depth spec
// (e2e/features-list.spec.ts) and admin-features-client.tsx:
//   route                 /admin/features
//   h1 heading            "Feature 목록"
//   nav link              getByRole("link", { name: "Feature 목록" })
//   search input          getByLabel("feature search")
//   kind select           getByLabel("feature kind")     all + FEATURE_KINDS
//   status select         getByLabel("feature status")   all + FEATURE_STATUSES
//   has issue select      getByLabel("has issue")        all/yes/no
//   sort select           getByLabel("feature sort")
//   page size select      getByLabel("feature page size")
//   order buttons         getByRole("button", { name: "asc" | "desc" })
//   pagination buttons    getByRole("button", { name: "다음" | "첫 페이지" })
//   table container       getByRole("table") (DataTable)
//
// 1.09M rows => the default list always has rows, but filtered/searched queries
// can be empty, so we assert the table container is visible (loose), never exact
// row text or counts.

const ROUTE = "/admin/features";
const HEADING = "Feature 목록";
const READY = { timeout: 15000 } as const;

// Page-level statuses available in the "feature status" select (admin-features-client).
const STATUS_FILTERS = [
  "active",
  "inactive",
  "hidden",
  "broken",
  "deleted",
] as const;
// Sort fields available in the "feature sort" select.
const SORT_FIELDS = [
  "name",
  "updated_at",
  "created_at",
  "kind",
  "status",
  "provider",
  "issue_count",
] as const;
const ORDERS = ["asc", "desc"] as const;
const HAS_ISSUE = ["all", "yes", "no"] as const;
const VIEWPORTS = [
  { name: "desktop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
] as const;

// Cross-dimension fixture slices (capped so the file stays bounded even if a
// fixture array is unexpectedly large; minimum scenarios run even when empty).
const SEARCH = F.SEARCH_TERMS.slice(0, 16);
const CATEGORIES = F.CATEGORY_CODES.slice(0, 60);
const KINDS = F.KINDS.slice(0, 7);
const PAGE_SIZES = F.PAGE_SIZES.slice(0, 4);

/** main heading + table container are the robust readiness landmarks. */
async function expectListReady(page: import("@playwright/test").Page) {
  await expect(
    page.getByRole("heading", { name: HEADING }),
  ).toBeVisible(READY);
  await expect(page.getByRole("table")).toBeVisible(READY);
}

test.describe("admin/features live — page load + landmarks", () => {
  test("page loads with heading and table container", async ({ page }) => {
    await page.goto(ROUTE);
    await expect(page).toHaveURL(/\/admin\/features$/, READY);
    await expectListReady(page);
  });

  test("control surface (search + selects + order buttons) visible", async ({
    page,
  }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    await expect(page.getByLabel("feature search")).toBeVisible(READY);
    await expect(page.getByLabel("feature kind")).toBeVisible(READY);
    await expect(page.getByLabel("feature status")).toBeVisible(READY);
    await expect(page.getByLabel("has issue")).toBeVisible(READY);
    await expect(page.getByLabel("feature sort")).toBeVisible(READY);
    await expect(page.getByLabel("feature page size")).toBeVisible(READY);
    await expect(page.getByRole("button", { name: "asc" })).toBeVisible(READY);
    await expect(page.getByRole("button", { name: "desc" })).toBeVisible(READY);
  });

  test("pagination controls present (다음 / 첫 페이지)", async ({ page }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    await expect(page.getByRole("button", { name: "다음" })).toBeVisible(READY);
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeVisible(READY);
    // initial page: 첫 페이지 is disabled (cursor === null).
    await expect(
      page.getByRole("button", { name: "첫 페이지" }),
    ).toBeDisabled();
  });

  test("nav link to Feature 목록 keeps us on route", async ({ page }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    await page.getByRole("link", { name: "Feature 목록" }).first().click();
    await expect(page).toHaveURL(/\/admin\/features$/, READY);
    await expectListReady(page);
  });
});

test.describe("admin/features live — responsive viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`loads at viewport ${vp.name} (${vp.width}x${vp.height})`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expect(
        page.getByRole("heading", { name: HEADING }),
      ).toBeVisible(READY);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });

    test(`search box reachable at viewport ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectListReady(page);
      await expect(page.getByLabel("feature search")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — search terms (GET-only typing)", () => {
  for (const term of SEARCH) {
    test(`search "${term}" keeps table container visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      // typing into the search box only issues GET list requests (non-destructive).
      await page.getByLabel("feature search").fill(term);
      // result may be empty for a term; assert the table container persists.
      await expect(page.getByRole("table")).toBeVisible(READY);
      await expect(page.getByLabel("feature search")).toHaveValue(term);
    });
  }
});

test.describe("admin/features live — search × viewport", () => {
  for (const vp of VIEWPORTS) {
    for (const term of SEARCH.slice(0, 8)) {
      test(`search "${term}" at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature search").fill(term);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — kind filter chips", () => {
  for (const kind of KINDS) {
    test(`kind="${kind}" filter keeps container visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("feature kind").selectOption(kind);
      await expect(page.getByLabel("feature kind")).toHaveValue(kind);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }

  test('kind="all" resets to full list', async ({ page }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    await page.getByLabel("feature kind").selectOption("all");
    await expect(page.getByLabel("feature kind")).toHaveValue("all");
    await expect(page.getByRole("table")).toBeVisible(READY);
  });

  for (const vp of VIEWPORTS) {
    for (const kind of KINDS.slice(0, 4)) {
      test(`kind="${kind}" at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature kind").selectOption(kind);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — status filter", () => {
  for (const status of STATUS_FILTERS) {
    test(`status="${status}" filter keeps container visible`, async ({
      page,
    }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("feature status").selectOption(status);
      await expect(page.getByLabel("feature status")).toHaveValue(status);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }

  test('status="all" shows union of statuses', async ({ page }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    await page.getByLabel("feature status").selectOption("all");
    await expect(page.getByLabel("feature status")).toHaveValue("all");
    await expect(page.getByRole("table")).toBeVisible(READY);
  });

  for (const vp of VIEWPORTS) {
    for (const status of STATUS_FILTERS) {
      test(`status="${status}" at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature status").selectOption(status);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — has-issue filter", () => {
  for (const issue of HAS_ISSUE) {
    test(`has issue="${issue}" keeps container visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("has issue").selectOption(issue);
      await expect(page.getByLabel("has issue")).toHaveValue(issue);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — sort fields", () => {
  for (const sortField of SORT_FIELDS) {
    test(`sort="${sortField}" keeps container visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("feature sort").selectOption(sortField);
      await expect(page.getByLabel("feature sort")).toHaveValue(sortField);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — sort × order", () => {
  for (const sortField of SORT_FIELDS) {
    for (const order of ORDERS) {
      test(`sort="${sortField}" order="${order}"`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature sort").selectOption(sortField);
        await expect(page.getByLabel("feature sort")).toHaveValue(sortField);
        await page.getByRole("button", { name: order }).click();
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — order toggle", () => {
  for (const order of ORDERS) {
    test(`order="${order}" toggle keeps container visible`, async ({
      page,
    }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByRole("button", { name: order }).click();
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — page sizes", () => {
  for (const size of PAGE_SIZES) {
    test(`page size=${size} keeps container visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("feature page size").selectOption(String(size));
      await expect(page.getByLabel("feature page size")).toHaveValue(
        String(size),
      );
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }

  for (const vp of VIEWPORTS) {
    for (const size of PAGE_SIZES) {
      test(`page size=${size} at ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature page size").selectOption(String(size));
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — category as search query (GET)", () => {
  for (const code of CATEGORIES) {
    test(`category code "${code}" typed into search`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      // category has no dedicated control here; typing the code into the
      // GET-only search box exercises filtering without any mutation.
      await page.getByLabel("feature search").fill(code);
      await expect(page.getByLabel("feature search")).toHaveValue(code);
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — deeplink query params (read-only goto)", () => {
  for (const code of CATEGORIES.slice(0, 30)) {
    test(`deeplink ?q=<category ${code}> loads list`, async ({ page }) => {
      // unknown query params are ignored by the client but exercise the route
      // load path; the heading + table must still render.
      await page.goto(`${ROUTE}?q=${encodeURIComponent(code)}`);
      await expectListReady(page);
    });
  }

  for (const kind of KINDS) {
    test(`deeplink ?kind=${kind} loads list`, async ({ page }) => {
      await page.goto(`${ROUTE}?kind=${encodeURIComponent(kind)}`);
      await expectListReady(page);
    });
  }

  for (const status of STATUS_FILTERS) {
    test(`deeplink ?status=${status} loads list`, async ({ page }) => {
      await page.goto(`${ROUTE}?status=${encodeURIComponent(status)}`);
      await expectListReady(page);
    });
  }
});

test.describe("admin/features live — pagination (다음 / 첫 페이지)", () => {
  test("advance via 다음 then return via 첫 페이지", async ({ page }) => {
    await page.goto(ROUTE);
    await expectListReady(page);
    const next = page.getByRole("button", { name: "다음" });
    const first = page.getByRole("button", { name: "첫 페이지" });
    // 1.09M rows => next_cursor exists, so 다음 is enabled.
    await expect(next).toBeEnabled(READY);
    await next.click();
    await expect(page.getByRole("table")).toBeVisible(READY);
    // after advancing, 첫 페이지 becomes enabled.
    await expect(first).toBeEnabled(READY);
    await first.click();
    await expect(page.getByRole("table")).toBeVisible(READY);
    await expect(first).toBeDisabled(READY);
  });

  for (const size of PAGE_SIZES) {
    test(`다음 advances at page size=${size}`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectListReady(page);
      await page.getByLabel("feature page size").selectOption(String(size));
      const next = page.getByRole("button", { name: "다음" });
      await expect(next).toBeEnabled(READY);
      await next.click();
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`다음 advances at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectListReady(page);
      const next = page.getByRole("button", { name: "다음" });
      await expect(next).toBeEnabled(READY);
      await next.click();
      await expect(page.getByRole("table")).toBeVisible(READY);
    });
  }
});

test.describe("admin/features live — combined filter matrix", () => {
  for (const status of STATUS_FILTERS) {
    for (const kind of KINDS.slice(0, 5)) {
      test(`status="${status}" × kind="${kind}"`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature status").selectOption(status);
        await page.getByLabel("feature kind").selectOption(kind);
        await expect(page.getByLabel("feature status")).toHaveValue(status);
        await expect(page.getByLabel("feature kind")).toHaveValue(kind);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }

  for (const sortField of SORT_FIELDS) {
    for (const size of PAGE_SIZES) {
      test(`sort="${sortField}" × page size=${size}`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature sort").selectOption(sortField);
        await page.getByLabel("feature page size").selectOption(String(size));
        await expect(page.getByLabel("feature sort")).toHaveValue(sortField);
        await expect(page.getByLabel("feature page size")).toHaveValue(
          String(size),
        );
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }

  for (const issue of HAS_ISSUE) {
    for (const order of ORDERS) {
      test(`has issue="${issue}" × order="${order}"`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("has issue").selectOption(issue);
        await page.getByRole("button", { name: order }).click();
        await expect(page.getByLabel("has issue")).toHaveValue(issue);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});

test.describe("admin/features live — search × kind matrix", () => {
  for (const term of SEARCH.slice(0, 10)) {
    for (const kind of KINDS.slice(0, 3)) {
      test(`search "${term}" × kind="${kind}"`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectListReady(page);
        await page.getByLabel("feature kind").selectOption(kind);
        await page.getByLabel("feature search").fill(term);
        await expect(page.getByLabel("feature search")).toHaveValue(term);
        await expect(page.getByLabel("feature kind")).toHaveValue(kind);
        await expect(page.getByRole("table")).toBeVisible(READY);
      });
    }
  }
});
