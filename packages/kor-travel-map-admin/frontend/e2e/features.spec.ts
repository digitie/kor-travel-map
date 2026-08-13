import { expect, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";
import { mockOpsDatasetCatalog } from "./ops-dataset-catalog-mock";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

type AdminFeatureMapItem = components["schemas"]["AdminFeatureMapItem"];
type AdminFeaturesInBoundsResponse =
  components["schemas"]["AdminFeaturesInBoundsResponse"];
type Meta = components["schemas"]["Meta"];
type ProblemDetail = components["schemas"]["ProblemDetail"];

const FEATURE: AdminFeatureMapItem = {
  category: "01070300",
  feature_id: "mock-provider::mock-dataset::features-smoke",
  kind: "place",
  lat: 37.5665,
  lon: 126.978,
  marker_color: "P-01",
  marker_icon: "marker",
  name: "Feature smoke",
  lifecycle_state: "active",
  publication_state: "published",
  quality_state: "valid",
};
const META: Meta = {
  cluster: null,
  duration_ms: 1,
  page: null,
  request_id: "e2e-features-smoke",
};
const BACKEND_UNAVAILABLE: ProblemDetail = {
  code: "SERVICE_UNAVAILABLE",
  detail: "mocked backend unavailable",
  request_id: "e2e-features-shell-backend-unavailable",
  status: 503,
  title: "mocked backend unavailable",
  type: "https://kor-travel-map/errors/service-unavailable",
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function featuresResponse(clustered: boolean): AdminFeaturesInBoundsResponse {
  return {
    data: {
      clusters: clustered
        ? [
            {
              cluster_key: "1100000000",
              feature_count: 1,
              lat: 37.5665,
              lon: 126.978,
            },
          ]
        : [],
      coverage: { limit: 2000, returned: 1 },
      items: clustered ? [] : [FEATURE],
      mode: clustered ? "clusters" : "items",
      truncated: false,
    },
    meta: {
      ...META,
      cluster: { cluster_unit: "sido", drill_down_unit: "sigungu" },
    },
  };
}

/**
 * `/features` — 지도 페이지 smoke. backend `/features` 호출은 DB가 비어 있어도
 * (count=0) 정상 200을 반환하므로 페이지 렌더 + 캔버스 + 헤더 상태가 보이는지만
 * 검증한다. 실 마커 렌더는 DB에 feature가 적재된 환경에서 별도 검증.
 */
test.describe("/features", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
    // 구체 mock보다 먼저 등록해 Playwright 역등록 우선순위에서 마지막 fail-close가 된다.
    await page.route("**/api/proxy/**", async (route) => {
      const request = route.request();
      if (request.method() !== "GET") {
        throw new Error(
          `features smoke에서 예상하지 않은 BFF 요청: ${request.method()} ${bffApiPath(
            request.url(),
          )}`,
        );
      }
      await route.fulfill({
        body: JSON.stringify(BACKEND_UNAVAILABLE),
        contentType: "application/problem+json",
        status: 503,
      });
    });
    await mockOpsDatasetCatalog(page);
    await page.route("**/v1/admin/features/in-bounds**", async (route) => {
      const request = route.request();
      const apiPath = bffApiPath(request.url());
      if (
        request.method() !== "GET" ||
        apiPath !== "/v1/admin/features/in-bounds"
      ) {
        throw new Error(
          `features smoke route 불일치: ${request.method()} ${apiPath}`,
        );
      }
      const zoom = Number(new URL(request.url()).searchParams.get("zoom"));
      await fulfillJson(
        route,
        featuresResponse(Number.isFinite(zoom) && zoom <= 13),
      );
    });
  });

  test("페이지 렌더 + 지도 컨테이너 + 헤더 상태", async ({ page }) => {
    await page.goto("/features");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();
    await expect(page.getByTestId("map-canvas-container")).toBeAttached();
    await expect(page.getByRole("tab", { name: "지도" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("link", { name: /홈/ })).toBeVisible();
    // exact in-bounds mock의 성공 상태까지 도달해야 한다.
    await expect(
      page.locator('[data-slot="badge"]').filter({
        hasText:
          /^(\d+개 지역 · [\d,]+건 집계(?: · 갱신 중)?|\d+건 표시(?: · 갱신 중)?)$/,
      }),
    ).toBeVisible();
  });

  test("홈에서 → Feature 지도 링크로 이동", async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("navigation")
      .getByRole("link", { name: "Feature 지도", exact: true })
      .click();
    await expect(page).toHaveURL(/\/features$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();
  });

  test("kind 필터 — 칩 7종 + 토글 + 초기화", async ({ page }) => {
    await page.goto("/features");
    const filter = page.getByTestId("kind-filter");
    await expect(filter).toBeVisible();
    await expect(
      page.locator('[data-slot="badge"]').filter({
        hasText:
          /^(\d+개 지역 · [\d,]+건 집계(?: · 갱신 중)?|\d+건 표시(?: · 갱신 중)?)$/,
      }),
    ).toBeVisible();
    for (const k of [
      "place",
      "event",
      "notice",
      "price",
      "weather",
      "route",
      "area",
    ]) {
      await expect(
        filter.getByRole("button", { name: k, exact: true }),
      ).toBeVisible();
    }
    const weatherBtn = filter.getByRole("button", {
      name: "weather",
      exact: true,
    });
    const noticeBtn = filter.getByRole("button", {
      name: "notice",
      exact: true,
    });
    const placeBtn = filter.getByRole("button", { name: "place", exact: true });
    const reset = filter.getByRole("button", { name: "초기화" });
    await expect(weatherBtn).toHaveAttribute("aria-pressed", "true");
    await expect(noticeBtn).toHaveAttribute("aria-pressed", "true");
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");
    await expect(reset).toBeVisible();
    await expect(reset).toBeDisabled();
    await placeBtn.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "true");
    await expect(reset).toBeEnabled();
    await reset.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");
    await expect(weatherBtn).toHaveAttribute("aria-pressed", "true");
    await expect(noticeBtn).toHaveAttribute("aria-pressed", "true");
    await expect(reset).toBeDisabled();
  });

  test("선택 안 했을 때 상세 패널은 안 보임", async ({ page }) => {
    await page.goto("/features");
    await expect(page.getByTestId("feature-detail-panel")).toBeHidden();
  });
});
