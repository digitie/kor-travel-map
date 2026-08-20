import { expect, test } from "@playwright/test";

import {
  ADMIN_SURFACES,
  type AdminLiveScenario,
  buildAdminLiveScenarioCatalog,
  summarizeAdminLiveScenarioCatalog,
} from "./admin-scenario-catalog";
import * as F from "./_fixtures";

const READY = { timeout: 15_000 } as const;

function smokeRoute(route: string): string | null {
  if (route.includes("{feature_id}")) {
    const featureId = F.FEATURE_IDS[0];
    return featureId
      ? route.replace("{feature_id}", encodeURIComponent(featureId))
      : null;
  }
  if (route.includes("{job_id}")) {
    const jobId = F.IMPORT_JOB_IDS[0];
    return jobId ? route.replace("{job_id}", encodeURIComponent(jobId)) : null;
  }
  if (route.includes("{request_id}")) {
    return null;
  }
  return route;
}

function firstLiveSmokeScenarioPerSurface(
  scenarios: readonly AdminLiveScenario[],
): AdminLiveScenario[] {
  const seen = new Set<string>();
  return scenarios.filter((scenario) => {
    if (scenario.mode !== "live_smoke" || seen.has(scenario.surface)) {
      return false;
    }
    seen.add(scenario.surface);
    return true;
  });
}

function apiContract(url: string, method: string): string {
  const pathname = new URL(url).pathname.replace(/^\/api\/proxy/, "");
  return `${method} ${pathname}`;
}

test.describe("admin live scenario catalog", () => {
  test("catalog taxonomy has route, API, reflection, and risk metadata", () => {
    const scenarios = buildAdminLiveScenarioCatalog();
    const summary = summarizeAdminLiveScenarioCatalog(scenarios);
    const ids = new Set(scenarios.map((scenario) => scenario.id));

    expect(ids.size).toBe(scenarios.length);
    expect(summary.byRisk.read).toBeGreaterThan(0);
    expect(summary.byRisk.write).toBeGreaterThan(0);
    expect(summary.byRisk.destructive).toBeGreaterThan(0);
    expect(summary.byRisk.cross_surface).toBeGreaterThan(0);
    expect(Object.keys(summary.bySurface)).toHaveLength(ADMIN_SURFACES.length);
    for (const [surface, count] of Object.entries(summary.bySurface)) {
      expect(count, `${surface} should have scenarios`).toBeGreaterThan(0);
    }
  });

  test("each admin surface has route, API, and reflection metadata", () => {
    for (const surface of ADMIN_SURFACES) {
      expect(surface.id).toMatch(/^[a-z0-9-]+$/);
      expect(surface.route).toMatch(/^\//);
      expect(surface.readyHeading.length).toBeGreaterThan(0);
      expect(surface.readApis.length, surface.id).toBeGreaterThan(0);
      expect(surface.reflectedSurfaces.length, surface.id).toBeGreaterThan(0);
    }
  });

  test("pipeline live UI calls datasets catalog and conditional MOIS precheck", async ({
    page,
  }) => {
    const observed = new Set<string>();
    page.on("request", (request) => {
      observed.add(apiContract(request.url(), request.method()));
    });

    await page.goto("/ops/pipeline");
    await expect(
      page.getByRole("heading", { level: 1, name: "파이프라인" }),
    ).toBeVisible(READY);
    await expect
      .poll(() => observed.has("GET /v1/ops/datasets"), READY)
      .toBe(true);

    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    await dialog.getByLabel("provider").first().fill("python-mois-api");
    await dialog.getByLabel("dataset_key").fill("mois_licenses");

    await expect
      .poll(
        () =>
          observed.has(
            "GET /v1/ops/pipeline/prechecks/mois-source-sync",
          ),
        READY,
      )
      .toBe(true);
  });

  test("representative live route smoke follows the scenario catalog", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const scenarios = firstLiveSmokeScenarioPerSurface(
      buildAdminLiveScenarioCatalog(),
    );
    const headingBySurface = new Map(
      ADMIN_SURFACES.map((surface) => [surface.id, surface.readyHeading]),
    );

    for (const scenario of scenarios) {
      const route = smokeRoute(scenario.route);
      if (!route) {
        continue;
      }
      const heading = headingBySurface.get(scenario.surface);
      expect(heading, `${scenario.surface} should have a heading`).toBeDefined();
      if (!heading) {
        continue;
      }
      await page.goto(route);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: heading,
        }),
        `${scenario.id} should render ${scenario.surface}`,
      ).toBeVisible(READY);
    }
  });
});
