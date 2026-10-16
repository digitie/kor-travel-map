import { expect, test, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

const TIMEOUT = 30_000;
const ROUTE = "/admin/ops/geo-releases";
type ListResponse = components["schemas"]["GeoReleaseListResponse"];

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  return pathname.startsWith("/api/proxy/") ? pathname.slice("/api/proxy".length) : pathname;
}

function waitFor(page: Page, method: string, path: string): Promise<Response> {
  return page.waitForResponse(
    (response) => response.request().method() === method && apiPath(response) === path,
    { timeout: TIMEOUT },
  );
}

/**
 * geo 릴리스 화면을 실제 API 응답으로 렌더한다(T-GR-06) — 격리 스택용. 화면이 보이는 현재 상태·
 * 계획 행이 같은 응답의 값과 같은지만 본다(데이터 스냅샷에 기대지 않는다).
 */
test.describe("geo 릴리스 live surface", () => {
  test("목록 응답의 현재 상태와 계획 행을 그대로 그린다", async ({ page }) => {
    const listResponse = waitFor(page, "GET", "/v1/ops/geo-releases");
    await page.goto(ROUTE);
    const response = await listResponse;
    expect(response.ok(), `GET /v1/ops/geo-releases HTTP ${response.status()}`).toBe(true);
    const body = (await response.json()) as ListResponse;

    await expect(
      page.getByRole("heading", { level: 1, name: "geo 릴리스" }),
    ).toBeVisible({ timeout: TIMEOUT });
    const badge = {
      ok: "정상",
      no_token: "data_token 없음",
      unavailable: "응답 없음",
    }[body.data.current_status];
    await expect(page.getByText(badge, { exact: true })).toBeVisible({ timeout: TIMEOUT });
    if (body.data.current_status === "no_token") {
      await expect(page.getByTestId("geo-release-skip-reason")).toContainText(
        "geo data_token 없음",
      );
    }
    if (body.data.plans.length === 0) {
      await expect(page.getByText("계획이 없습니다.")).toBeVisible({ timeout: TIMEOUT });
    }
    for (const plan of body.data.plans) {
      await expect(page.getByTestId(`geo-release-plan-${plan.plan_id}`)).toBeVisible({
        timeout: TIMEOUT,
      });
    }
  });

  test("지금 감지는 API 결과(계획 또는 거부)를 화면에 그대로 보인다", async ({ page }) => {
    test.skip(
      process.env.E2E_GEO_RELEASE_DETECT !== "1",
      "detect는 계획을 쓸 수 있다 — 격리 스택에서만 E2E_GEO_RELEASE_DETECT=1로 켠다",
    );
    await page.goto(ROUTE);
    await expect(
      page.getByRole("heading", { level: 1, name: "geo 릴리스" }),
    ).toBeVisible({ timeout: TIMEOUT });
    const detect = waitFor(page, "POST", "/v1/ops/geo-releases/detect");
    await page.getByRole("button", { name: "지금 감지" }).click();
    const response = await detect;
    if (response.ok()) {
      await expect(page.getByTestId("geo-release-detect-outcome")).toBeVisible({
        timeout: TIMEOUT,
      });
    } else {
      expect(response.status()).toBe(503);
      await expect(
        page.getByRole("alert").filter({ hasText: "지금 감지" }),
      ).toBeVisible({ timeout: TIMEOUT });
    }
  });
});
