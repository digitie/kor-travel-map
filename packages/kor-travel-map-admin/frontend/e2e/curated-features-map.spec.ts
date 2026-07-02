import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

type CuratedFeature = components["schemas"]["CuratedFeatureView"];
type CuratedFeaturesResponse = components["schemas"]["CuratedFeaturesResponse"];
type CuratedThemesResponse = components["schemas"]["CuratedThemesResponse"];
type CuratedSourcesResponse = components["schemas"]["CuratedSourcesResponse"];
type CuratedFeatureResponse = components["schemas"]["CuratedFeatureResponse"];
type Meta = components["schemas"]["Meta"];

const CURATED_ID = "11111111-1111-1111-1111-111111111111";
const FEATURE_ID = "f_global_p_mock_curated_poi";
const THEME_ID = "22222222-2222-2222-2222-222222222222";
const SOURCE_ID = "33333333-3333-3333-3333-333333333333";

function makeMeta(overrides: Partial<Meta> = {}): Meta {
  return {
    cluster: null,
    duration_ms: 1,
    page: null,
    request_id: "e2e-curated-map",
    ...overrides,
  };
}

function makeCuratedFeature(
  overrides: Partial<CuratedFeature> = {},
): CuratedFeature {
  return {
    address: {},
    archived_at: null,
    content_version: 1,
    created_at: "2026-07-02T00:00:00.000Z",
    curated_feature_id: CURATED_ID,
    curation_relation: "primary_stop",
    curation_status: "curated",
    dataset_key: "youtube_place_candidates",
    detail: {
      phones: ["02-0000-0000"],
      place_kind: "cafe",
    },
    display_summary: "묶음 설명",
    display_title: "여름 성수 카페 묶음",
    feature_category: "01070300",
    feature_id: FEATURE_ID,
    feature_kind: "place",
    feature_name: "성수 모크 카페",
    lat: 37.5446,
    legal_dong_code: null,
    lon: 127.0557,
    metadata: {},
    provider: "kor-travel-concierge-youtube",
    rank_score: 10,
    rejected_at: null,
    rejected_by: null,
    rejection_reason: null,
    reuse_policy: "allowed",
    selected_at: "2026-07-02T00:00:00.000Z",
    selected_by: "e2e",
    selection_origin: "source_rule",
    sido_code: "11",
    sigungu_code: "11200",
    source_id: SOURCE_ID,
    source_name: "concierge youtube",
    source_record_key: "sr_curated_mock",
    source_url: null,
    theme_group: "seasonal",
    theme_id: THEME_ID,
    theme_name: "여름 여행지",
    theme_slug: "summer-destinations",
    updated_at: "2026-07-02T00:00:00.000Z",
    ...overrides,
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status: 200,
  });
}

async function mockCuratedMapRoutes(page: Page) {
  const feature = makeCuratedFeature();
  const listResponse: CuratedFeaturesResponse = {
    data: { items: [feature] },
    meta: makeMeta(),
  };
  const detailResponse: CuratedFeatureResponse = {
    data: feature,
    meta: makeMeta({ request_id: "e2e-curated-map-detail" }),
  };
  const themesResponse: CuratedThemesResponse = {
    data: {
      items: [
        {
          created_at: "2026-07-02T00:00:00.000Z",
          default_curated: true,
          metadata: {},
          theme_description: "여름 여행지",
          theme_group: "seasonal",
          theme_id: THEME_ID,
          theme_name: "여름 여행지",
          theme_slug: "summer-destinations",
          updated_at: "2026-07-02T00:00:00.000Z",
          visibility: "public",
        },
      ],
    },
    meta: makeMeta({ request_id: "e2e-curated-map-themes" }),
  };
  const sourcesResponse: CuratedSourcesResponse = {
    data: {
      items: [
        {
          created_at: "2026-07-02T00:00:00.000Z",
          dataset_key: "youtube_place_candidates",
          freshness_note: null,
          last_checked_at: null,
          last_source_modified_at: null,
          license: null,
          metadata: {},
          next_expected_at: null,
          provider: "kor-travel-concierge-youtube",
          provider_status: "implemented",
          row_count: 1,
          source_id: SOURCE_ID,
          source_kind: "internal",
          source_name: "concierge youtube",
          source_url: null,
          update_cycle: "daily",
          updated_at: "2026-07-02T00:00:00.000Z",
        },
      ],
    },
    meta: makeMeta({ request_id: "e2e-curated-map-sources" }),
  };

  await page.route("**/v1/admin/features/curated**", async (route) => {
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
    if (url.pathname.endsWith(`/${CURATED_ID}`)) {
      await fulfillJson(route, detailResponse);
      return;
    }
    await fulfillJson(route, listResponse);
  });
  await page.route("**/v1/admin/curated-themes**", async (route) => {
    await fulfillJson(route, themesResponse);
  });
  await page.route("**/v1/admin/curated-sources**", async (route) => {
    await fulfillJson(route, sourcesResponse);
  });
}

test.describe("/curated-features", () => {
  test("지도/테이블/상세가 feature 이름 중심으로 렌더된다", async ({ page }) => {
    await mockCuratedMapRoutes(page);

    await page.goto("/curated-features");

    await expect(
      page.getByRole("heading", { level: 1, name: "Curated Feature 지도" }),
    ).toBeVisible();
    await expect(page.getByLabel("POI명 필터")).toBeVisible();
    await expect(page.getByLabel("테마 필터")).toBeVisible();
    await expect(page.getByLabel("제목 필터")).toBeVisible();
    await expect(page.getByLabel("데이터소스 필터")).toBeVisible();

    await page.getByRole("tab", { name: "테이블" }).click();
    await expect(page.getByText("성수 모크 카페")).toBeVisible();
    await expect(page.getByText("여름 성수 카페 묶음")).toBeVisible();

    await page.getByText("여름 성수 카페 묶음").click();
    await page.getByRole("tab", { name: "지도" }).click();
    await expect(page.getByText("선택 Curated Feature")).toBeVisible();
    await expect(page.getByText("성수 모크 카페").first()).toBeVisible();
  });
});
