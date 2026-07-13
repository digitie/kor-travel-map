import { expect, type Page, type Route, test } from "@playwright/test";

const FEATURE_ID = "python-visitkorea-api::visitkorea_areas::palace-1";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status: 200,
  });
}

function membership(overrides: Record<string, unknown>) {
  return {
    curation_item_id: "item-2023",
    collection_id: "collection-2023",
    collection_key: "tourism-100-2023-2024",
    title: "2023~2024 한국관광 100선",
    edition_key: "2023-2024",
    theme_slug: "korean-tourism-100",
    theme_name: "한국관광 100선",
    theme_group: "관광 선정",
    provider: "mcst",
    dataset_key: "korean-tourism-100",
    source_name: "문화체육관광부",
    source_url: "https://example.test/mcst/2023",
    feature_id: FEATURE_ID,
    feature_name: "경복궁",
    feature_kind: "place",
    feature_category: "01060100",
    lon: 126.977,
    lat: 37.5796,
    address: { road_address: "서울 종로구 사직로 161" },
    source_record_key: "mcst::tourism-100::2023-palace",
    external_item_id: "tourism-100-2023-palace",
    place_name: "경복궁",
    address_hint: "서울 종로구",
    status: "included",
    sort_order: 1,
    item_title: "경복궁",
    item_summary: "2023~2024 선정지",
    curation_relation: "primary_stop",
    reuse_policy: "allowed",
    metadata: { official_source: "e2e-membership-metadata" },
    created_at: "2026-07-13T00:00:00.000Z",
    updated_at: "2026-07-13T00:00:00.000Z",
    archived_at: null,
    ...overrides,
  };
}

async function mockPublicCurationRoutes(
  page: Page,
  options: { collectionsStatus?: number } = {},
) {
  const groupUrls: URL[] = [];
  const curations = [
    membership({}),
    membership({
      curation_item_id: "item-2025",
      collection_id: "collection-2025",
      collection_key: "tourism-100-2025-2026",
      title: "2025~2026 한국관광 100선",
      edition_key: "2025-2026",
      source_url: "https://example.test/mcst/2025",
      external_item_id: "tourism-100-2025-palace",
      item_summary: "2025~2026 재선정지",
    }),
  ];

  await page.route("**/api/proxy/v1/curations**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/collections")) {
      if (options.collectionsStatus && options.collectionsStatus >= 400) {
        await route.fulfill({
          body: JSON.stringify({ detail: "collection filter failed" }),
          contentType: "application/json",
          status: options.collectionsStatus,
        });
        return;
      }
      await fulfillJson(route, {
        data: {
          items: curations.map((item) => ({
            collection_id: item.collection_id,
            collection_key: item.collection_key,
            theme_id: "theme-tourism-100",
            theme_slug: item.theme_slug,
            theme_name: item.theme_name,
            theme_group: item.theme_group,
            source_id: "source-mcst",
            provider: item.provider,
            dataset_key: item.dataset_key,
            source_name: item.source_name,
            source_url: item.source_url,
            title: item.title,
            edition_key: item.edition_key,
            description: null,
            status: "published",
            visibility: "public",
            metadata: {},
            item_count: 1,
            created_at: item.created_at,
            updated_at: item.updated_at,
            archived_at: null,
          })),
        },
        meta: { request_id: "e2e-public-curation-collections" },
      });
      return;
    }

    groupUrls.push(url);
    await fulfillJson(route, {
      data: {
        items: [
          {
            feature: {
              feature_id: FEATURE_ID,
              name: "경복궁",
              kind: "place",
              category: "01060100",
              lon: 126.977,
              lat: 37.5796,
              address: { road_address: "서울 종로구 사직로 161" },
              status: "active",
            },
            curations,
            curation_count: 2,
          },
        ],
      },
      meta: {
        page: { next_cursor: null, page_size: 500, total: 1 },
        request_id: "e2e-public-curation-groups",
      },
    });
  });
  return { groupUrls };
}

test.describe("/curated-features", () => {
  test("같은 Feature의 여러 연도 큐레이션을 한 행과 상세 패널에 모두 표시한다", async ({
    page,
  }) => {
    const mocks = await mockPublicCurationRoutes(page);

    await page.goto("/curated-features");

    await expect(
      page.getByRole("heading", { level: 1, name: "큐레이션 지도" }),
    ).toBeVisible();
    await expect(page.getByLabel("POI명 또는 큐레이션 제목 필터")).toBeVisible();
    await expect(page.getByLabel("테마 필터")).toContainText("한국관광 100선");
    await expect(page.getByLabel("연도 필터")).toContainText("2023-2024");
    await expect(page.getByLabel("연도 필터")).toContainText("2025-2026");
    await expect.poll(() => mocks.groupUrls.length).toBeGreaterThan(0);
    expect(
      mocks.groupUrls.every((url) =>
        ["min_lon", "min_lat", "max_lon", "max_lat"].every((key) =>
          url.searchParams.has(key),
        ),
      ),
    ).toBe(true);

    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table", { name: "큐레이션 Feature 그룹" });
    await expect(table.getByText("경복궁")).toHaveCount(1);
    await expect(table.getByText("2건")).toBeVisible();
    await expect(table.getByText("2023~2024 한국관광 100선 · 2023-2024")).toBeVisible();
    await expect(table.getByText("2025~2026 한국관광 100선 · 2025-2026")).toBeVisible();

    await table.getByRole("row", { name: /경복궁/ }).click();
    const detail = page.getByTestId("curation-group-detail");
    await expect(detail.getByText("큐레이션 소속 2건")).toBeVisible();
    await expect(detail.getByTestId("curation-membership")).toHaveCount(2);
    await expect(detail.getByText("2023-2024", { exact: true })).toBeVisible();
    await expect(detail.getByText("2025-2026", { exact: true })).toBeVisible();
    await expect(detail.getByText("2023~2024 선정지")).toBeVisible();
    await expect(detail.getByText("2025~2026 재선정지")).toBeVisible();
    await expect(detail.getByText("문화체육관광부 · mcst · korean-tourism-100")).toHaveCount(2);
    const membership = detail.getByTestId("curation-membership").first();
    await membership.getByText("membership 전체 정보").click();
    await expect(membership.getByText("tourism-100-2023-2024")).toBeVisible();
    await expect(membership.getByText("mcst::tourism-100::2023-palace")).toBeVisible();
    await expect(membership.getByText("서울 종로구")).toBeVisible();
    await expect(membership.getByText("allowed", { exact: true })).toBeVisible();
    await expect(membership.getByText(/e2e-membership-metadata/)).toBeVisible();
  });

  test("collection 필터 조회 실패를 빈 필터처럼 숨기지 않는다", async ({ page }) => {
    await mockPublicCurationRoutes(page, { collectionsStatus: 500 });

    await page.goto("/curated-features");

    await expect(page.getByText("큐레이션 필터 조회 실패")).toBeVisible();
    await expect(page.getByText(/collection filter failed/)).toBeVisible();
  });
});
