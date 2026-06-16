import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/features/[featureId]` 상세 — ZERO 커버 페이지 spec
 * (T-AUDIT-0616, `docs/reports/e2e-scenario-coverage-2026-06-16.md` §1.5).
 *
 * 본 페이지는 **admin 상세 라우트** `/v1/admin/features/{id}`를 쓴다(공개 라우트 아님).
 * 임의 featureId는 빈 DB에서 404이므로 admin 상세 GET + nearby + weather를 mock한다.
 * (감사 보고서의 "지도/AddressMatchReport/raw JSON 토글/재검증"은 실제 컴포넌트엔 없다 —
 * 실제 섹션은 Sources/Issues/Overrides/History/Files + Weather/Nearby/Raw(<details>)다.)
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 라이브 실행 검증은 Windows 런 필요.
 */

type AdminFeatureDetailFeatureRecord =
  components["schemas"]["AdminFeatureDetailFeatureRecord"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type FeaturesNearbyResponse = components["schemas"]["FeaturesNearbyResponse"];
type NearbyFeatureSummary = components["schemas"]["NearbyFeatureSummary"];
type FeatureWeatherResponse = components["schemas"]["FeatureWeatherResponse"];

const FEATURE_ID = "f_1156010100_p_e2eabc1234567890";
const DETAIL_PATH = `/v1/admin/features/${FEATURE_ID}`;
const meta = { duration_ms: 1, request_id: "e2e-feature-detail" };

function makeFeature(
  overrides: Partial<AdminFeatureDetailFeatureRecord> = {},
): AdminFeatureDetailFeatureRecord {
  return {
    address: { road: "서울특별시 영등포구 여의공원로 120" },
    category: "01070300",
    created_at: "2026-06-01T00:00:00.000Z",
    data_origin: "provider",
    data_version: 3,
    detail: { place_kind: "park" },
    feature_id: FEATURE_ID,
    kind: "place",
    lat: 37.5263,
    lon: 126.9239,
    marker_color: "P-01",
    marker_icon: "marker",
    name: "여의도공원",
    raw_refs: [],
    sido_code: "11",
    sigungu_code: "11560",
    status: "active",
    updated_at: "2026-06-08T00:00:00.000Z",
    urls: { homepage: "https://example.test" },
    ...overrides,
  };
}

function makeDetailResponse(
  feature: AdminFeatureDetailFeatureRecord,
): AdminFeatureDetailResponse {
  return {
    data: {
      change_requests: [],
      feature,
      files: [],
      issues: [],
      overrides: [],
      sources: [],
      versions: [],
    },
    meta,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockFeatureDetail(
  page: Page,
  options: {
    feature?: AdminFeatureDetailFeatureRecord;
    nearby?: NearbyFeatureSummary[];
    detailStatus?: number;
  } = {},
) {
  const feature = options.feature ?? makeFeature();
  const nearby = options.nearby ?? [];

  await page.route("**/v1/admin/features/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === DETAIL_PATH) {
      if (options.detailStatus && options.detailStatus >= 400) {
        await fulfillJson(route, { detail: "feature 없음" }, options.detailStatus);
        return;
      }
      await fulfillJson(route, makeDetailResponse(feature));
      return;
    }
    await route.continue();
  });

  await page.route("**/v1/features/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/v1/features/nearby") {
      const body: FeaturesNearbyResponse = {
        data: { items: nearby, origin: { lat: 37.5263, lon: 126.9239, radius_m: 3000 } },
        meta,
      };
      await fulfillJson(route, body);
      return;
    }
    if (url.pathname.endsWith("/weather")) {
      const body: FeatureWeatherResponse = {
        data: {
          feature_id: FEATURE_ID,
          is_stale: false,
          metrics: [],
          source_styles: [],
        },
        meta,
      };
      await fulfillJson(route, body);
      return;
    }
    await route.continue();
  });
}

test.describe("/features/[featureId]", () => {
  test("상세 render — 헤더 + Sources/Issues/Overrides/History/Files + Raw", async ({
    page,
  }) => {
    await mockFeatureDetail(page);
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByTestId("feature-detail-view")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "여의도공원" }),
    ).toBeVisible();
    // 헤더 dl 라벨.
    await expect(page.getByText("coord", { exact: true })).toBeVisible();
    // 메인 섹션 타이틀.
    for (const section of ["Sources", "Issues", "Overrides", "History", "Files"]) {
      await expect(page.getByText(section, { exact: true })).toBeVisible();
    }
    // Raw <details> disclosure.
    await expect(page.getByText("raw_refs", { exact: true })).toBeVisible();
    await expect(page.getByTestId("feature-weather-panel")).toBeVisible();
  });

  test("nearby 항목 render", async ({ page }) => {
    await mockFeatureDetail(page, {
      nearby: [
        {
          category: "01070300",
          distance_m: 152.4,
          feature_id: "f_1156010100_p_neighbor00000001",
          kind: "place",
          lat: 37.527,
          lon: 126.924,
          name: "인근 카페",
          status: "active",
        },
      ],
    });
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByText("Nearby", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: /인근 카페/ }),
    ).toBeVisible();
  });

  test("weather metric 없음 — empty state", async ({ page }) => {
    await mockFeatureDetail(page);
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByText("weather metric이 없습니다.")).toBeVisible();
  });

  test("404 — feature 상세 조회 실패 alert", async ({ page }) => {
    await mockFeatureDetail(page, { detailStatus: 404 });
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByText("feature 상세 조회 실패")).toBeVisible();
  });
});
