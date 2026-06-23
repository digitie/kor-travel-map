import { test, expect } from "@playwright/test";

import * as F from "./_fixtures";

// LIVE (non-mock) e2e for /ops/logs against prod 실데이터 (1.09M features).
// Read-only only: page.goto, read assertions, and clicks restricted to
// tabs / page-size select / level filter selects / pagination 다음·이전 /
// nav. Typing into search/filter inputs is GET-only (allowed).
//
// Selectors are reused verbatim from e2e/logs-streams.spec.ts and verified
// against src/app/ops/logs/logs-client.tsx — none are invented:
//   - main heading: getByRole("heading", { level: 1, name: "Logs" })
//   - tabs (role=tab): "System logs" | "API call logs" | "Job events"
//   - page size: getByLabel("log page size") -> 25|50|100|200
//   - level selects: getByLabel("system log level"|"job event level")
//   - filter inputs: getByLabel("system log search"|"system log source"|
//       "api log method"|"api log path"|"api log min status"|
//       "job event job id"|"job event provider"|"job event dataset key")
//   - pagination buttons: 다음 | 첫 페이지
//   - empty messages: "system log가 없습니다." / "API call log가 없습니다." /
//       "job event가 없습니다."
//   - summary badges: "system N" / "api N" / "job events N"

const ROUTE = "/ops/logs";
const TIMEOUT = { timeout: 15000 };

// Stable, robust visibility check for the page shell. The h1 is rendered by
// AdminShell(title="Logs"); the live badge / summary row are always mounted.
async function expectLogsPageLoaded(page: import("@playwright/test").Page) {
  await expect(
    page.getByRole("heading", { level: 1, name: "Logs" }),
  ).toBeVisible(TIMEOUT);
}

// Per-tab stable assertion: each panel's emptyMessage OR its column headers
// are robust signals that the active panel mounted. We assert the tab itself
// is selected plus the page-size control (always mounted) is visible — this
// stays robust whether or not the live backend returned rows.
const TAB_NAMES = ["System logs", "API call logs", "Job events"] as const;
const TAB_EMPTY: Record<(typeof TAB_NAMES)[number], string> = {
  "System logs": "system log가 없습니다.",
  "API call logs": "API call log가 없습니다.",
  "Job events": "job event가 없습니다.",
};
// First (always-visible, sortable) column header per tab — used as a robust
// "panel mounted" signal that does not depend on row data.
const TAB_FIRST_COLUMN: Record<(typeof TAB_NAMES)[number], string> = {
  "System logs": "created",
  "API call logs": "created",
  "Job events": "occurred",
};

async function selectTab(
  page: import("@playwright/test").Page,
  name: (typeof TAB_NAMES)[number],
) {
  await page.getByRole("tab", { name }).click();
  await expect(page.getByRole("tab", { name })).toHaveAttribute(
    "aria-selected",
    "true",
    TIMEOUT,
  );
}

// Robust "panel content present" check: either the empty-state message OR the
// column header is visible. PRESENCE for logs is unknown live, so we never
// assert exact counts.
async function expectPanelRobust(
  page: import("@playwright/test").Page,
  tab: (typeof TAB_NAMES)[number],
) {
  const empty = page.getByText(TAB_EMPTY[tab]);
  const header = page.getByRole("columnheader", { name: TAB_FIRST_COLUMN[tab] });
  await expect(empty.or(header).first()).toBeVisible(TIMEOUT);
}

const LEVEL_OPTIONS = [
  "critical",
  "error",
  "warning",
  "info",
  "debug",
  "all",
] as const;

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
] as const;

// Deep-link query strings. The logs page keeps filter state in local useState
// (not URL params), so these query strings do not mutate UI state — they are
// simply non-destructive GET loads that must render the shell robustly.
const DEEP_LINK_QUERIES = [
  "?tab=system",
  "?tab=api",
  "?tab=events",
  "?level=error",
  "?provider=python-kma-api",
  "?dataset_key=kma_weather_values",
  "?q=load",
  "?method=GET",
] as const;

test.describe("/ops/logs live — page load + shell", () => {
  test("loads /ops/logs and shows main heading", async ({ page }) => {
    await page.goto(ROUTE);
    await expectLogsPageLoaded(page);
  });

  test("loads /ops/logs and shows page size control", async ({ page }) => {
    await page.goto(ROUTE);
    await expectLogsPageLoaded(page);
    await expect(page.getByLabel("log page size")).toBeVisible(TIMEOUT);
  });

  test("loads /ops/logs and shows all three tabs", async ({ page }) => {
    await page.goto(ROUTE);
    await expectLogsPageLoaded(page);
    for (const name of TAB_NAMES) {
      await expect(page.getByRole("tab", { name })).toBeVisible(TIMEOUT);
    }
  });

  test("loads /ops/logs and shows summary badge row", async ({ page }) => {
    await page.goto(ROUTE);
    await expectLogsPageLoaded(page);
    await expect(page.getByText(/^system \d+$/)).toBeVisible(TIMEOUT);
    await expect(page.getByText(/^api \d+$/)).toBeVisible(TIMEOUT);
    await expect(page.getByText(/^job events \d+$/)).toBeVisible(TIMEOUT);
  });

  test("loads /ops/logs and default tab panel is robustly present", async ({
    page,
  }) => {
    await page.goto(ROUTE);
    await expectLogsPageLoaded(page);
    await expectPanelRobust(page, "System logs");
  });
});

test.describe("/ops/logs live — tab switching", () => {
  for (const tab of TAB_NAMES) {
    test(`tab "${tab}" selects + panel robustly present`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, tab);
      await expectPanelRobust(page, tab);
    });
  }

  for (const tab of TAB_NAMES) {
    test(`tab "${tab}" keeps page-size control visible`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, tab);
      await expect(page.getByLabel("log page size")).toBeVisible(TIMEOUT);
    });
  }
});

test.describe("/ops/logs live — page size x tab", () => {
  for (const size of F.PAGE_SIZES) {
    for (const tab of TAB_NAMES) {
      test(`page size ${size} on tab "${tab}"`, async ({ page }) => {
        await page.goto(ROUTE);
        await expectLogsPageLoaded(page);
        await selectTab(page, tab);
        await page.getByLabel("log page size").selectOption(String(size));
        await expect(page.getByLabel("log page size")).toHaveValue(
          String(size),
          TIMEOUT,
        );
        await expectPanelRobust(page, tab);
      });
    }
  }
});

test.describe("/ops/logs live — system log level filter", () => {
  for (const level of LEVEL_OPTIONS) {
    test(`system log level "${level}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "System logs");
      await page.getByLabel("system log level").selectOption(level);
      await expect(page.getByLabel("system log level")).toHaveValue(
        level,
        TIMEOUT,
      );
      await expectPanelRobust(page, "System logs");
    });
  }
});

test.describe("/ops/logs live — job event level filter", () => {
  for (const level of LEVEL_OPTIONS) {
    test(`job event level "${level}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "Job events");
      await page.getByLabel("job event level").selectOption(level);
      await expect(page.getByLabel("job event level")).toHaveValue(
        level,
        TIMEOUT,
      );
      await expectPanelRobust(page, "Job events");
    });
  }
});

test.describe("/ops/logs live — system log search (GET-only typing)", () => {
  for (const term of F.SEARCH_TERMS.slice(0, 16)) {
    test(`system search "${term}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "System logs");
      await page.getByLabel("system log search").fill(term);
      await expect(page.getByLabel("system log search")).toHaveValue(
        term,
        TIMEOUT,
      );
      // panel stays robust whether the query matched rows or not.
      await expectPanelRobust(page, "System logs");
    });
  }
});

test.describe("/ops/logs live — job event id filter (GET-only typing)", () => {
  for (const jobId of F.IMPORT_JOB_IDS.slice(0, 3)) {
    test(`job event job_id "${jobId}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "Job events");
      await page.getByLabel("job event job id").fill(jobId);
      await expect(page.getByLabel("job event job id")).toHaveValue(
        jobId,
        TIMEOUT,
      );
      await expectPanelRobust(page, "Job events");
    });
  }
});

test.describe("/ops/logs live — job event kind-as-dataset filter", () => {
  // IMPORT_JOB_KINDS doubles as a stable, non-row-data set of dataset_key-ish
  // tokens to exercise the job event dataset filter input (GET-only typing).
  for (const kind of F.IMPORT_JOB_KINDS.slice(0, 7)) {
    test(`job event dataset key "${kind}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "Job events");
      await page.getByLabel("job event dataset key").fill(kind);
      await expect(page.getByLabel("job event dataset key")).toHaveValue(
        kind,
        TIMEOUT,
      );
      await expectPanelRobust(page, "Job events");
    });
  }
});

test.describe("/ops/logs live — api call log filters (GET-only typing)", () => {
  for (const method of ["GET", "POST", "PUT", "PATCH", "DELETE"]) {
    test(`api log method "${method}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "API call logs");
      await page.getByLabel("api log method").fill(method);
      await expect(page.getByLabel("api log method")).toHaveValue(
        method,
        TIMEOUT,
      );
      await expectPanelRobust(page, "API call logs");
    });
  }

  for (const minStatus of ["200", "400", "500"]) {
    test(`api log min status "${minStatus}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "API call logs");
      await page.getByLabel("api log min status").fill(minStatus);
      await expect(page.getByLabel("api log min status")).toHaveValue(
        minStatus,
        TIMEOUT,
      );
      await expectPanelRobust(page, "API call logs");
    });
  }

  for (const pathFrag of ["/v1/features", "/v1/ops", "/v1/curated"]) {
    test(`api log path "${pathFrag}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "API call logs");
      await page.getByLabel("api log path").fill(pathFrag);
      await expect(page.getByLabel("api log path")).toHaveValue(
        pathFrag,
        TIMEOUT,
      );
      await expectPanelRobust(page, "API call logs");
    });
  }
});

test.describe("/ops/logs live — system log source filter (GET-only)", () => {
  for (const source of [
    "api",
    "dagster",
    "core",
    "geocoding",
    "providers",
    "cli",
  ]) {
    test(`system log source "${source}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "System logs");
      await page.getByLabel("system log source").fill(source);
      await expect(page.getByLabel("system log source")).toHaveValue(
        source,
        TIMEOUT,
      );
      await expectPanelRobust(page, "System logs");
    });
  }
});

test.describe("/ops/logs live — provider filter on job events", () => {
  // PROVIDERS may be empty live; fall back to stable provider-ish tokens so
  // the suite always generates these scenarios.
  const providerTokens =
    F.PROVIDERS.length > 0
      ? F.PROVIDERS.slice(0, 6)
      : ["python-kma-api", "python-festival-api", "python-opinet-api"];
  for (const provider of providerTokens) {
    test(`job event provider "${provider}"`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, "Job events");
      await page.getByLabel("job event provider").fill(provider);
      await expect(page.getByLabel("job event provider")).toHaveValue(
        provider,
        TIMEOUT,
      );
      await expectPanelRobust(page, "Job events");
    });
  }
});

test.describe("/ops/logs live — pagination controls (read-only nav)", () => {
  for (const tab of TAB_NAMES) {
    test(`tab "${tab}" pagination buttons present + guarded`, async ({
      page,
    }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, tab);
      // On first page (cursor null) the "첫 페이지" button is always disabled.
      await expect(
        page.getByRole("button", { name: "첫 페이지" }),
      ).toBeDisabled(TIMEOUT);
      // "다음" is enabled only when next_cursor exists; assert presence, not
      // enabled-state (live data dependent).
      await expect(
        page.getByRole("button", { name: "다음" }),
      ).toBeVisible(TIMEOUT);
    });
  }

  for (const tab of TAB_NAMES) {
    test(`tab "${tab}" next page when next_cursor exists`, async ({ page }) => {
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      await selectTab(page, tab);
      const next = page.getByRole("button", { name: "다음" });
      await expect(next).toBeVisible(TIMEOUT);
      // Read-only forward pagination: only click when enabled, then assert the
      // "첫 페이지" guard flips to enabled. If 다음 is disabled (no more pages
      // live), the panel simply stays robust.
      if (await next.isEnabled()) {
        await next.click();
        await expect(
          page.getByRole("button", { name: "첫 페이지" }),
        ).toBeEnabled(TIMEOUT);
        await expectPanelRobust(page, tab);
      } else {
        await expectPanelRobust(page, tab);
      }
    });
  }
});

test.describe("/ops/logs live — deep-link query loads", () => {
  for (const query of DEEP_LINK_QUERIES) {
    test(`deep-link ${query} loads shell robustly`, async ({ page }) => {
      await page.goto(`${ROUTE}${query}`);
      await expectLogsPageLoaded(page);
      await expect(page.getByLabel("log page size")).toBeVisible(TIMEOUT);
    });
  }

  for (const query of DEEP_LINK_QUERIES) {
    test(`deep-link ${query} keeps tabs visible`, async ({ page }) => {
      await page.goto(`${ROUTE}${query}`);
      await expectLogsPageLoaded(page);
      for (const name of TAB_NAMES) {
        await expect(page.getByRole("tab", { name })).toBeVisible(TIMEOUT);
      }
    });
  }
});

test.describe("/ops/logs live — responsive viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`viewport ${vp.name} ${vp.width}x${vp.height} loads heading`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`viewport ${vp.name} ${vp.width}x${vp.height} shows tabs`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(ROUTE);
      await expectLogsPageLoaded(page);
      for (const name of TAB_NAMES) {
        await expect(page.getByRole("tab", { name })).toBeVisible(TIMEOUT);
      }
    });
  }

  for (const vp of VIEWPORTS) {
    for (const tab of TAB_NAMES) {
      test(`viewport ${vp.name} tab "${tab}" panel robust`, async ({
        page,
      }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectLogsPageLoaded(page);
        await selectTab(page, tab);
        await expectPanelRobust(page, tab);
      });
    }
  }

  for (const vp of VIEWPORTS) {
    for (const size of F.PAGE_SIZES) {
      test(`viewport ${vp.name} page size ${size}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(ROUTE);
        await expectLogsPageLoaded(page);
        await page.getByLabel("log page size").selectOption(String(size));
        await expect(page.getByLabel("log page size")).toHaveValue(
          String(size),
          TIMEOUT,
        );
      });
    }
  }
});

test.describe("/ops/logs live — viewport x deep-link cross", () => {
  for (const vp of VIEWPORTS) {
    for (const query of DEEP_LINK_QUERIES.slice(0, 4)) {
      test(`viewport ${vp.name} deep-link ${query} loads`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(`${ROUTE}${query}`);
        await expectLogsPageLoaded(page);
      });
    }
  }
});
