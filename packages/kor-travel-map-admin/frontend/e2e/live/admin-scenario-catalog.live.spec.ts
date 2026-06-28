import { expect, test } from "@playwright/test";

import {
  ADMIN_SURFACES,
  EXPECTED_MIN_ADMIN_LIVE_SCENARIOS,
  buildAdminLiveScenarioCatalog,
  summarizeAdminLiveScenarioCatalog,
} from "./admin-scenario-catalog";
import * as F from "./_fixtures";

const READY = { timeout: 15_000 } as const;

function smokeRoute(route: string): string | null {
  if (route.includes("{feature_id}")) {
    const featureId = F.FEATURE_IDS[0];
    return featureId ? route.replace("{feature_id}", encodeURIComponent(featureId)) : null;
  }
  if (route.includes("{curated_feature_id}")) {
    const curatedId = F.CURATED_IDS[0];
    return curatedId
      ? route.replace("{curated_feature_id}", encodeURIComponent(curatedId))
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

test.describe("admin live scenario catalog", () => {
  test("catalog enumerates at least 10,000 admin UI/API scenarios", () => {
    const scenarios = buildAdminLiveScenarioCatalog();
    const summary = summarizeAdminLiveScenarioCatalog(scenarios);

    expect(summary.total).toBeGreaterThanOrEqual(
      EXPECTED_MIN_ADMIN_LIVE_SCENARIOS,
    );
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

  test("representative live route smoke follows the scenario catalog", async ({
    page,
  }) => {
    test.setTimeout(90_000);

    for (const surface of ADMIN_SURFACES) {
      const route = smokeRoute(surface.route);
      if (!route) {
        continue;
      }
      await page.goto(route);
      await expect(
        page.getByRole("heading", { level: 1, name: surface.readyHeading }),
        `${surface.id} should render ${surface.readyHeading}`,
      ).toBeVisible(READY);
    }
  });
});
