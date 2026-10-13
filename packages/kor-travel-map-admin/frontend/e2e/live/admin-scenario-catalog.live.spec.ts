import { expect, test } from "@playwright/test";

import type { components } from "../../src/api/types";
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

    const overviewResponse = page.waitForResponse(
      (response) =>
        apiContract(response.url(), response.request().method()) ===
        "GET /v1/ops/pipeline/overview",
      { timeout: 60_000 },
    );
    await page.goto("/ops/pipeline");
    await expect(
      page.getByRole("heading", { level: 1, name: "파이프라인" }),
    ).toBeVisible(READY);
    // 전제 1: overview 자체가 성공해야 한다. 실패하면 화면은 비활성 버튼만 남겨
    // 아래 단언이 원인 없는 15초 timeout이 된다 — 여기서 상태 코드로 끝낸다.
    const overview = await overviewResponse;
    if (!overview.ok()) {
      throw new Error(
        `전제 미충족: GET /v1/ops/pipeline/overview가 HTTP ${overview.status()}로 실패했다`,
      );
    }
    // 전제 2: 갱신 요청 dialog(= `/v1/ops/datasets` 호출)는 큐 sensor가 RUNNING으로
    // 확인될 때만 렌더된다. overview가 도착하면 둘 중 하나가 반드시 보이므로 먼저
    // 그것을 기다리고, 차단 alert면 datasets 관측 timeout 대신 원인을 그대로 낸다.
    const queueAlert = page.getByTestId("queue-sensor-alert");
    const createButton = page.getByRole("button", {
      name: "갱신 요청 생성",
      exact: true,
    });
    await expect(queueAlert.or(createButton)).toBeVisible(READY);
    if (await queueAlert.isVisible()) {
      throw new Error(
        `전제 미충족: 큐 sensor 차단 alert가 떠 있어 갱신 요청 dialog가 렌더되지 않는다 — ${(
          await queueAlert.innerText()
        ).replace(/\s+/g, " ")}`,
      );
    }
    await expect
      .poll(() => observed.has("GET /v1/ops/datasets"), READY)
      .toBe(true);

    await page.getByRole("button", { name: "갱신 요청 생성" }).click();
    const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
    const catalog = await page.evaluate(async () => {
      const response = await fetch("/api/proxy/v1/ops/datasets", {
        credentials: "same-origin",
        cache: "no-store",
      });
      return (await response.json()) as components["schemas"]["OpsDatasetsGridResponse"];
    });
    const moisRow = catalog.data.items.find(
      (row) =>
        row.catalog_state === "canonical" &&
        row.mutable &&
        row.catalog?.is_refreshable === true &&
        row.provider.toLowerCase().includes("mois"),
    );
    expect(moisRow, "live canonical MOIS refresh dataset is required").toBeDefined();
    if (!moisRow) {
      throw new Error("live canonical MOIS refresh dataset is required");
    }
    // T-VN-33/ADR-088: the dialog accepts the canonical provider_dataset_id
    // selected from /v1/ops/datasets; provider and dataset_key are projections.
    await dialog
      .getByLabel("대상 데이터셋")
      .selectOption(String(moisRow.provider_dataset_id));

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
