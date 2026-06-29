import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

// 이번 세션 features 지도 작업의 live UI e2e (route-mock 깊이; live n150에서 실행):
//   - #603: KMA 격자 예보가 airkorea와 별개인 독립 weather feature(P-01, "기상청 …")로 표시
//   - #604: 같은 격자 좌표에 겹친 마커(초단기·단기) 클릭 시 "겹친 지점 N개" 팝업 → 행 선택
// features-map-interactions.spec.ts idiom을 따른다(OpenAPI 스키마 바인딩 mock factory).

type FeatureSummary = components["schemas"]["FeatureSummary"];
type FeaturesInBboxResponse = components["schemas"]["FeaturesInBboxResponse"];
type Meta = components["schemas"]["Meta"];
type FeatureDetailResponse = components["schemas"]["FeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  components["schemas"]["FeatureDetailEnvelopeResponse"];
type FeatureWeatherResponse = components["schemas"]["FeatureWeatherResponse"];

// 기본 viewport(서울) 안 좌표 — 마커가 화면에 뜨도록.
const SEOUL_LON = 126.978;
const SEOUL_LAT = 37.5665;

function makeMeta(overrides: Partial<Meta> = {}): Meta {
  return {
    cluster: null,
    duration_ms: 1,
    page: null,
    request_id: "e2e-session-kma",
    ...overrides,
  };
}

function makeWeatherFeature(
  overrides: Partial<FeatureSummary> = {},
): FeatureSummary {
  return {
    category: "99000000",
    feature_id: "kma::ultra::seoul",
    kind: "weather",
    lat: SEOUL_LAT,
    lon: SEOUL_LON,
    marker_color: "P-01",
    marker_icon: "marker",
    name: "기상청 초단기 서울",
    status: "active",
    ...overrides,
  };
}

function makeFeaturesInBboxResponse(
  items: FeatureSummary[],
): FeaturesInBboxResponse {
  return { data: { items }, meta: makeMeta() };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeFeatureDetail(
  overrides: Partial<FeatureDetailResponse> = {},
): FeatureDetailResponse {
  return {
    address: { road: "서울 중구 세종대로" },
    category: "99000000",
    detail: {},
    feature_id: "kma::ultra::seoul",
    kind: "weather",
    lat: SEOUL_LAT,
    lon: SEOUL_LON,
    name: "기상청 초단기 서울",
    status: "active",
    updated_at: "2026-06-29T00:00:00.000Z",
    urls: {},
    ...overrides,
  };
}

function makeFeatureDetailEnvelope(
  detail: FeatureDetailResponse,
): FeatureDetailEnvelopeResponse {
  return {
    data: detail,
    meta: makeMeta({ request_id: "e2e-session-kma-detail" }),
  };
}

function makeFeatureWeatherResponse(featureId: string): FeatureWeatherResponse {
  return {
    data: {
      asof: null,
      feature_id: featureId,
      is_stale: false,
      latest_at: null,
      metrics: [],
      source_styles: [],
    },
    meta: makeMeta({ request_id: "e2e-session-kma-weather" }),
  };
}

async function setMapZoom(page: Page, zoom: number) {
  await page.evaluate((nextZoom) => {
    const container = document.querySelector(
      '[data-testid="map-canvas-container"]',
    ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
    container?._maplibreMap?.jumpTo({ zoom: nextZoom });
  }, zoom);
}

async function mockFeatureRoutes(
  page: Page,
  items: FeatureSummary[],
  detailById: Record<string, FeatureDetailResponse> = {},
) {
  await page.route("**/v1/features**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    if (url.searchParams.has("_rsc")) {
      await route.continue();
      return;
    }
    if (url.pathname.endsWith("/weather")) {
      const id = url.pathname.split("/").slice(-2)[0] ?? "";
      await fulfillJson(route, makeFeatureWeatherResponse(id));
      return;
    }
    if (url.pathname.endsWith("/price")) {
      await fulfillJson(route, { data: null, meta: makeMeta() });
      return;
    }
    if (
      url.pathname === "/v1/features" ||
      url.pathname === "/api/proxy/v1/features"
    ) {
      await fulfillJson(route, makeFeaturesInBboxResponse(items));
      return;
    }
    if (
      url.pathname.startsWith("/v1/features/") ||
      url.pathname.startsWith("/api/proxy/v1/features/")
    ) {
      const id = url.pathname.split("/").pop() ?? "";
      const detail = detailById[id] ?? makeFeatureDetail({ feature_id: id });
      await fulfillJson(route, makeFeatureDetailEnvelope(detail));
      return;
    }
    await route.continue();
  });
}

test.describe("/features — KMA 격자 weather 마커 (#603/#604)", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
  });

  test("KMA 격자 weather feature가 '기상청' 이름·P-01 독립 feature로 존재(airkorea와 별개)", async ({
    page,
  }) => {
    const items = [
      makeWeatherFeature({
        feature_id: "kma::ultra::seoul",
        name: "기상청 초단기 서울",
        lon: SEOUL_LON,
        lat: SEOUL_LAT,
      }),
      makeWeatherFeature({
        feature_id: "kma::short::seoul",
        name: "기상청 단기 서울",
        lon: SEOUL_LON + 0.012,
        lat: SEOUL_LAT,
      }),
      makeWeatherFeature({
        feature_id: "air::seoul",
        name: "서울 대기질 측정소",
        marker_color: "P-16",
        lon: SEOUL_LON,
        lat: SEOUL_LAT + 0.012,
      }),
    ];
    await mockFeatureRoutes(page, items);
    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();

    // 테이블 뷰: KMA 초단기·단기가 각각 독립 weather feature로 존재(#603).
    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table");
    await expect(
      table.getByRole("cell", { name: "기상청 초단기 서울" }),
    ).toBeVisible();
    await expect(
      table.getByRole("cell", { name: "기상청 단기 서울" }),
    ).toBeVisible();
    await expect(
      table.getByRole("cell", { name: "서울 대기질 측정소" }),
    ).toBeVisible();

    // 지도 뷰: 분리된 좌표에서 KMA 마커가 개별 렌더(aria-label = 이름).
    await page.getByRole("tab", { name: "지도" }).click();
    await setMapZoom(page, 15);
    await expect(
      page.getByRole("button", { name: /기상청 초단기 서울/ }),
    ).toBeVisible();
  });

  test("같은 격자 좌표 초단기·단기 마커 겹침 → '겹친 지점' 팝업으로 선택 (#604)", async ({
    page,
  }) => {
    const ultra = makeWeatherFeature({
      feature_id: "kma::ultra::seoul",
      name: "기상청 초단기 서울",
      lon: SEOUL_LON,
      lat: SEOUL_LAT,
    });
    const short = makeWeatherFeature({
      feature_id: "kma::short::seoul",
      name: "기상청 단기 서울",
      lon: SEOUL_LON,
      lat: SEOUL_LAT,
    });
    await mockFeatureRoutes(page, [ultra, short], {
      "kma::ultra::seoul": makeFeatureDetail({
        feature_id: "kma::ultra::seoul",
        name: "기상청 초단기 서울",
      }),
      "kma::short::seoul": makeFeatureDetail({
        feature_id: "kma::short::seoul",
        name: "기상청 단기 서울",
      }),
    });
    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    // clusterMaxZoom 초과 → 격자 위 개별 점, 동일 좌표라 픽셀-겹침 그룹이 된다.
    await setMapZoom(page, 16);

    // 상단 마커 클릭(겹쳐 가려질 수 있어 force) → 겹침 선택 팝업.
    await page
      .getByRole("button", { name: /기상청 (초단기|단기) 서울/ })
      .first()
      .click({ force: true });

    const popup = page.locator(".maplibregl-popup");
    await expect(popup).toBeVisible();
    await expect(popup).toContainText("겹친 지점 2개");
    await expect(popup.getByText("기상청 초단기 서울")).toBeVisible();
    await expect(popup.getByText("기상청 단기 서울")).toBeVisible();

    // 팝업 행 클릭 → 해당 feature 선택(상세 패널) + 팝업 닫힘.
    await popup.getByText("기상청 단기 서울").click();
    await expect(page.locator(".maplibregl-popup")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: /기상청 단기 서울/ }),
    ).toBeVisible();
  });
});
