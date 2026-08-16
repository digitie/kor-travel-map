import { expect, type Page, type Route, test } from "@playwright/test";
import type { components } from "../src/api/types";

type AdminCollection = components["schemas"]["AdminCurationCollectionView"];
type AdminItem = components["schemas"]["AdminCurationItemView"];

const COLLECTION_ID = "collection-lighthouse";
const FEATURE_ID = "python-visitkorea-api::visitkorea-areas::palace-1";
const NOW = "2026-07-13T00:00:00.000Z";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status: 200,
  });
}

function collection(): AdminCollection {
  return {
    collection_id: COLLECTION_ID,
    collection_key: "official-place-sample",
    theme_id: "theme-official-place",
    theme_slug: "official-place",
    theme_name: "공식 관광지",
    theme_group: "공식 캠페인",
    source_id: "source-official",
    provider_dataset_id: 1,
    provider: "mcst",
    dataset_key: "official-place-sample",
    source_name: "공식 목록",
    source_url: "https://example.test/official",
    title: "공식 관광지 샘플",
    edition_key: "2026",
    description: "연결·미연결 항목을 함께 관리하는 컬렉션",
    status: "published",
    visibility: "public",
    metadata: {},
    item_count: 2,
    public_item_count: 2,
    row_revision: "1",
    command_etag: '"1"',
    created_by: "admin:test",
    updated_by: "admin:test",
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
  };
}

function item(overrides: Partial<AdminItem>): AdminItem {
  return {
    curation_item_id: "item-linked",
    collection_id: COLLECTION_ID,
    collection_key: "official-place-sample",
    title: "공식 관광지 샘플",
    edition_key: "2026",
    theme_slug: "official-place",
    theme_name: "공식 관광지",
    theme_group: "공식 캠페인",
    provider_dataset_id: 1,
    provider: "mcst",
    dataset_key: "official-place-sample",
    source_name: "공식 목록",
    source_url: "https://example.test/official",
    feature_id: FEATURE_ID,
    feature_name: "경복궁",
    feature_kind: "place",
    feature_category: "01060100",
    lon: 126.977,
    lat: 37.5796,
    address: { road_address: "서울 종로구 사직로 161" },
    source_record_key: null,
    external_item_id: "official-palace",
    external_component_id: "main",
    place_name: "경복궁",
    address_hint: "서울 종로구",
    source_present: true,
    status: "included",
    sort_order: 1,
    item_title: "경복궁",
    item_summary: "기존 Feature 연결 항목",
    curation_relation: "primary_stop",
    reuse_policy: "allowed",
    metadata: {},
    current_import_row_id: null,
    accepted_link_decision_id: null,
    link_match_basis: null,
    link_resolver_version: null,
    link_evidence: {},
    link_actor: null,
    link_decided_at: null,
    row_revision: "1",
    command_etag: '"1"',
    created_by: "admin:test",
    updated_by: "admin:test",
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
    ...overrides,
  };
}

async function mockAdminCurationRoutes(page: Page) {
  const mutations = {
    archived: 0,
    archiveIdempotencyKey: null as string | null,
    archiveIfMatch: null as string | null,
    patchIdempotencyKey: null as string | null,
    patchedFeatureId: null as string | null,
    patchIfMatch: null as string | null,
  };
  await page.route("**/api/proxy/v1/admin/curated-themes**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: {} }),
  );
  await page.route("**/api/proxy/v1/admin/curated-sources**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: {} }),
  );
  await page.route("**/api/proxy/v1/admin/curations**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/items/item-unresolved")) {
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON() as { feature_id?: string };
        mutations.patchedFeatureId = body.feature_id ?? null;
        mutations.patchIfMatch = route.request().headers()["if-match"] ?? null;
        mutations.patchIdempotencyKey =
          route.request().headers()["idempotency-key"] ?? null;
      } else if (route.request().method() === "DELETE") {
        mutations.archived += 1;
        mutations.archiveIfMatch = route.request().headers()["if-match"] ?? null;
        mutations.archiveIdempotencyKey =
          route.request().headers()["idempotency-key"] ?? null;
      }
      await fulfillJson(route, {
        data: item({
          curation_item_id: "item-unresolved",
          feature_id: mutations.patchedFeatureId,
          status: mutations.archived ? "archived" : "included",
        }),
        meta: {},
      });
      return;
    }
    if (url.pathname.endsWith(`/${COLLECTION_ID}`)) {
      await fulfillJson(route, {
        data: {
          collection: collection(),
          items: [
            item({}),
            item({
              curation_item_id: "item-unresolved",
              feature_id: null,
              feature_name: null,
              feature_kind: null,
              feature_category: null,
              lon: null,
              lat: null,
              address: {},
              external_item_id: "lighthouse-ganjeolgot",
              place_name: "간절곶 등대",
              address_hint: "울산 울주군",
              sort_order: 2,
              item_title: "간절곶 등대",
              item_summary: "Feature 매칭 대기",
            }),
          ],
        },
        meta: {},
      });
      return;
    }
    await fulfillJson(route, { data: { items: [collection()] }, meta: {} });
  });
  return mutations;
}

test.describe("/admin/features/curated", () => {
  test("수동 입력 필드와 CSV 양식 링크를 제공한다", async ({ page }) => {
    await mockAdminCurationRoutes(page);

    await page.goto("/admin/features/curated");

    await expect(
      page.getByRole("heading", { level: 1, name: "큐레이션 관리" }),
    ).toBeVisible();
    await expect(page.getByText("컬렉션 수동 생성")).toBeVisible();
    for (const label of [
      "컬렉션 키",
      "테마",
      "제목",
      "회차/년도",
      "출처",
      "상태",
      "공개 범위",
      "설명",
    ]) {
      await expect(page.getByLabel(label, { exact: true })).toBeVisible();
    }

    const templateLink = page.getByRole("link", { name: "CSV 양식 다운로드" });
    await expect(templateLink).toHaveAttribute(
      "href",
      "/api/proxy/v1/admin/curations/import-template.csv",
    );
    await expect(templateLink).toHaveAttribute("download", "");
  });

  test("컬렉션 상세에 기존 Feature 연결 항목과 미연결 항목을 모두 표시한다", async ({
    page,
  }) => {
    await mockAdminCurationRoutes(page);

    await page.goto("/admin/features/curated");

    const detail = page.getByTestId("curation-collection-detail");
    await expect(detail).toBeVisible();
    await expect(detail.getByText("경복궁", { exact: true }).first()).toBeVisible();
    await expect(detail.getByText("기존 Feature 연결 항목")).toBeVisible();
    await expect(
      detail.getByText("간절곶 등대", { exact: true }).first(),
    ).toBeVisible();
    await expect(detail.getByText("Feature 미연결")).toBeVisible();
    await expect(detail.getByText("Feature 매칭 대기")).toBeVisible();
    await expect(detail.getByText("official-palace")).toBeVisible();
    await expect(detail.getByText("lighthouse-ganjeolgot")).toBeVisible();
    await expect(detail.getByText("주소 힌트 울산 울주군")).toBeVisible();
    await expect(detail.getByText(/mcst\/official-place-sample/).first()).toBeVisible();
  });

  test("미연결 항목을 Feature에 연결하고 항목을 보관 처리한다", async ({ page }) => {
    const mutations = await mockAdminCurationRoutes(page);
    await page.goto("/admin/features/curated");

    await page
      .getByLabel("간절곶 등대 Feature 연결")
      .fill("feature-lighthouse-ganjeolgot");
    await page.getByRole("button", { name: "Feature 연결" }).click();
    await expect(page.getByText(/Feature feature-lighthouse-ganjeolgot/)).toBeVisible();
    expect(mutations.patchedFeatureId).toBe("feature-lighthouse-ganjeolgot");
    expect(mutations.patchIfMatch).toBe('"1"');
    expect(mutations.patchIdempotencyKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );

    page.once("dialog", async (dialog) => dialog.accept());
    await page.getByRole("button", { name: "항목 보관" }).last().click();
    await expect(page.getByText(/항목을 보관 처리했습니다/)).toBeVisible();
    expect(mutations.archived).toBe(1);
    expect(mutations.archiveIfMatch).toBe('"1"');
    expect(mutations.archiveIdempotencyKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });
});
