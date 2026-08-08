import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { bffApiPath } from "./bff-api-path";

// T-VN-H22C — 0065 quarantine 재분류 패널 (`/admin/features/curated` 하단).
// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 관용).
// ops-live WebSocket은 이 화면에서 mount되지 않으므로(`useOpsLiveInvalidation`
// 사용처: features/datasets/pipeline) `installInertOpsLiveWebSocket`이 필요 없다.
type QuarantineCollectionView =
  components["schemas"]["AdminCurationQuarantineCollectionView"];
type QuarantineItemView =
  components["schemas"]["AdminCurationQuarantineItemView"];
type QuarantineItemsData =
  components["schemas"]["AdminCurationQuarantineItemsData"];
type QuarantineReclassifyRequest =
  components["schemas"]["AdminCurationQuarantineReclassifyRequest"];
type QuarantineReclassifyResponse =
  components["schemas"]["AdminCurationQuarantineReclassifyResponse"];
type AdminCollectionView =
  components["schemas"]["AdminCurationCollectionView"];

const MOCK_NOW = "2026-08-04T00:00:00.000Z";
const QUARANTINE_ID = "11111111-1111-4111-8111-111111111111";
const ORIGINAL_ID = "22222222-2222-4222-8222-222222222222";
const OTHER_ID = "33333333-3333-4333-8333-333333333333";
const ITEM_MOVABLE_ID = "44444444-4444-4444-8444-444444444444";
const ITEM_CONFLICT_ID = "55555555-5555-4555-8555-555555555555";
const CONFLICT_TARGET_ITEM_ID = "66666666-6666-4666-8666-666666666666";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function meta(requestId: string) {
  return { duration_ms: 1, request_id: requestId };
}

function pagedMeta(requestId: string, nextCursor: string | null = null) {
  return {
    duration_ms: 1,
    page: { next_cursor: nextCursor, page_size: 200, total: null },
    request_id: requestId,
  };
}

function makeQuarantineCollection(
  overrides: Partial<QuarantineCollectionView> = {},
): QuarantineCollectionView {
  return {
    collection_id: QUARANTINE_ID,
    collection_key: "quarantine-lighthouse-2026",
    created_by: "migration:0065",
    edition_key: "2026",
    item_count: 2,
    marker_intact: true,
    original_collection: {
      collection_id: ORIGINAL_ID,
      exists: true,
      source: {
        dataset_key: "lighthouse_places",
        provider: "python-khoa-api",
        provider_dataset_id: 601,
        source_id: "77777777-7777-4777-8777-777777777777",
        source_name: "국립해양조사원",
      },
      status: "published",
      theme: {
        theme_group: "테마 시설",
        theme_id: "88888888-8888-4888-8888-888888888888",
        theme_name: "등대 스탬프투어",
        theme_slug: "lighthouse-stamp-tour",
        visibility: "public",
      },
      title: "등대 스탬프투어",
      visibility: "public",
    },
    quarantine_source: {
      dataset_key: "lighthouse_places_legacy",
      provider: "python-khoa-api",
      provider_dataset_id: 602,
      source_id: "99999999-9999-4999-8999-999999999999",
      source_name: "구 등대 출처",
    },
    quarantine_theme: {
      theme_group: "격리 보관",
      theme_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      theme_name: "격리 등대 테마",
      theme_slug: "quarantine-lighthouse",
      visibility: "admin_only",
    },
    status: "draft",
    title: "격리: 등대 스탬프투어",
    visibility: "admin_only",
    ...overrides,
  };
}

function makeQuarantineItems(): QuarantineItemView[] {
  return [
    {
      archived_at: null,
      conflict_item_id: null,
      conflict_kind: "movable",
      curation_item_id: ITEM_MOVABLE_ID,
      external_component_id: "primary",
      external_item_id: "lighthouse-ganjeolgot",
      feature_id: "python-khoa-api::lighthouse_places::ganjeolgot",
      place_name: "간절곶 등대",
      source_present: true,
      status: "included",
    },
    {
      archived_at: null,
      conflict_item_id: CONFLICT_TARGET_ITEM_ID,
      conflict_kind: "component_identity_conflict",
      curation_item_id: ITEM_CONFLICT_ID,
      external_component_id: "primary",
      external_item_id: "lighthouse-homigot",
      feature_id: null,
      place_name: "호미곶 등대",
      source_present: false,
      status: "candidate",
    },
  ];
}

function itemsData(
  items: QuarantineItemView[],
  targetCollectionId: string | null,
): QuarantineItemsData {
  return {
    items,
    target_archived: false,
    target_collection_id: targetCollectionId,
    target_missing: false,
  };
}

function makeAdminCollection(
  overrides: Partial<AdminCollectionView> = {},
): AdminCollectionView {
  return {
    archived_at: null,
    collection_id: ORIGINAL_ID,
    collection_key: "lighthouse-stamp-tour",
    created_at: MOCK_NOW,
    created_by: "admin",
    dataset_key: "lighthouse_places",
    description: null,
    edition_key: "2026",
    item_count: 3,
    metadata: {},
    provider: "python-khoa-api",
    provider_dataset_id: 601,
    public_item_count: 3,
    source_id: "77777777-7777-4777-8777-777777777777",
    source_name: "국립해양조사원",
    source_url: null,
    status: "published",
    theme_group: "테마 시설",
    theme_id: "88888888-8888-4888-8888-888888888888",
    theme_name: "등대 스탬프투어",
    theme_slug: "lighthouse-stamp-tour",
    title: "등대 스탬프투어",
    updated_at: MOCK_NOW,
    updated_by: null,
    visibility: "public",
    ...overrides,
  };
}

function moveConflictProblem() {
  return {
    type: "https://kor-travel-map/errors/curation-quarantine-move-conflict",
    title: "curation quarantine move가 unique 제약과 충돌합니다.",
    status: 409,
    detail: "curation quarantine move가 unique 제약과 충돌합니다.",
    code: "CURATION_QUARANTINE_MOVE_CONFLICT",
    request_id: "e2e-quarantine-409",
    errors: [],
    details: {
      conflicts: [
        {
          conflict_item_id: CONFLICT_TARGET_ITEM_ID,
          conflict_kind: "component_identity_conflict",
          curation_item_id: ITEM_CONFLICT_ID,
        },
      ],
    },
  };
}

interface QuarantineMockOptions {
  quarantineCollections?: QuarantineCollectionView[];
  adminCollections?: AdminCollectionView[];
  reclassify?: (body: QuarantineReclassifyRequest) => {
    body: unknown;
    status: number;
  };
}

interface QuarantineMockState {
  itemsRequests: Array<{ collectionId: string; targetCollectionId: string | null }>;
  quarantineListRequests: number;
  reclassifyRequests: Array<{
    body: QuarantineReclassifyRequest;
    collectionId: string;
    idempotencyKey: string;
  }>;
}

async function mockQuarantineRoutes(
  page: Page,
  options: QuarantineMockOptions = {},
): Promise<QuarantineMockState> {
  const state: QuarantineMockState = {
    itemsRequests: [],
    quarantineListRequests: 0,
    reclassifyRequests: [],
  };
  const quarantineCollections = options.quarantineCollections ?? [];
  const adminCollections = options.adminCollections ?? [];

  await page.route("**/api/proxy/v1/admin/curated-themes**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: meta("e2e-themes") }),
  );
  await page.route("**/api/proxy/v1/admin/curated-sources**", (route) =>
    fulfillJson(route, { data: { items: [] }, meta: meta("e2e-sources") }),
  );
  await page.route("**/api/proxy/v1/admin/curations**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const apiPath = bffApiPath(request.url());

    if (request.method() === "GET" && apiPath === "/v1/admin/curations") {
      await fulfillJson(route, {
        data: { items: adminCollections },
        meta: pagedMeta("e2e-collections"),
      });
      return;
    }
    if (
      request.method() === "GET" &&
      apiPath === "/v1/admin/curations/quarantine"
    ) {
      state.quarantineListRequests += 1;
      await fulfillJson(route, {
        data: { items: quarantineCollections },
        meta: pagedMeta("e2e-quarantine-list"),
      });
      return;
    }
    const itemsMatch = /^\/v1\/admin\/curations\/quarantine\/([^/]+)\/items$/.exec(
      apiPath,
    );
    if (request.method() === "GET" && itemsMatch) {
      const targetCollectionId = url.searchParams.get("target_collection_id");
      state.itemsRequests.push({
        collectionId: decodeURIComponent(itemsMatch[1]),
        targetCollectionId,
      });
      await fulfillJson(route, {
        data: itemsData(
          makeQuarantineItems(),
          targetCollectionId ?? ORIGINAL_ID,
        ),
        meta: pagedMeta("e2e-quarantine-items"),
      });
      return;
    }
    const reclassifyMatch =
      /^\/v1\/admin\/curations\/quarantine\/([^/]+)\/reclassify$/.exec(apiPath);
    if (request.method() === "POST" && reclassifyMatch) {
      const body = request.postDataJSON() as QuarantineReclassifyRequest;
      state.reclassifyRequests.push({
        body,
        collectionId: decodeURIComponent(reclassifyMatch[1]),
        idempotencyKey: request.headers()["idempotency-key"] ?? "",
      });
      const outcome = options.reclassify?.(body) ?? {
        body: {
          data: {
            action: body.action,
            collection_id: null,
            collection_key: null,
            moved_item_ids: body.item_ids ?? [ITEM_MOVABLE_ID, ITEM_CONFLICT_ID],
            quarantine_collection_deleted: true,
          },
          meta: meta("e2e-quarantine-reclassify"),
        } satisfies QuarantineReclassifyResponse,
        status: 200,
      };
      await fulfillJson(route, outcome.body, outcome.status);
      return;
    }
    const detailMatch = /^\/v1\/admin\/curations\/([^/]+)$/.exec(apiPath);
    if (request.method() === "GET" && detailMatch) {
      const collectionId = decodeURIComponent(detailMatch[1]);
      const collection =
        adminCollections.find(
          (candidate) => candidate.collection_id === collectionId,
        ) ?? makeAdminCollection({ collection_id: collectionId });
      await fulfillJson(route, {
        data: { collection, items: [] },
        meta: meta("e2e-collection-detail"),
      });
      return;
    }
    throw new Error(
      `Unhandled curations route: ${request.method()} ${apiPath}`,
    );
  });

  return state;
}

const quarantinePanel = (page: Page) =>
  page.getByTestId("quarantine-workspace");

test.describe("큐레이션 quarantine 재분류 패널", () => {
  test("격리 collection이 없으면 빈 상태를 1급으로 안내한다", async ({
    page,
  }) => {
    const state = await mockQuarantineRoutes(page);
    await page.goto("/admin/features/curated");

    await expect(page.getByText("격리된 collection 없음")).toBeVisible();
    await expect(
      page.getByText(
        "0065 마이그레이션이 격리한 큐레이션 collection이 없는 정상 상태입니다.",
      ),
    ).toBeVisible();
    await expect.poll(() => state.quarantineListRequests).toBeGreaterThan(0);
    expect(state.itemsRequests).toHaveLength(0);
  });

  test("격리 목록과 theme/source 병렬 표시 + conflict 배지를 렌더한다", async ({
    page,
  }) => {
    await mockQuarantineRoutes(page, {
      adminCollections: [makeAdminCollection()],
      quarantineCollections: [makeQuarantineCollection()],
    });
    await page.goto("/admin/features/curated");

    const list = page.getByTestId("quarantine-collection-list");
    await expect(list.getByText("격리: 등대 스탬프투어")).toBeVisible();
    await expect(list.getByText(/marker 정상/)).toBeVisible();

    const comparison = page.getByTestId("quarantine-comparison");
    await expect(comparison.getByText("격리 보관 theme/source")).toBeVisible();
    await expect(
      comparison.getByText(/격리 등대 테마 · quarantine-lighthouse · 격리 보관/),
    ).toBeVisible();
    await expect(
      comparison.getByText("원본 collection 현재 상태 — 등대 스탬프투어"),
    ).toBeVisible();
    await expect(
      comparison.getByText(/등대 스탬프투어 · lighthouse-stamp-tour · 테마 시설/),
    ).toBeVisible();

    const table = page.getByTestId("quarantine-items-table");
    await expect(table.getByText("간절곶 등대")).toBeVisible();
    await expect(table.getByText("이동 가능")).toBeVisible();
    await expect(table.getByText("구성요소 identity 충돌")).toBeVisible();
    await expect(table.getByText("원천 누락")).toBeVisible();
  });

  test("target collection 변경 시 conflict preview를 재조회한다", async ({
    page,
  }) => {
    const state = await mockQuarantineRoutes(page, {
      adminCollections: [
        makeAdminCollection(),
        makeAdminCollection({
          collection_id: OTHER_ID,
          collection_key: "other-collection",
          title: "다른 컬렉션",
        }),
      ],
      quarantineCollections: [makeQuarantineCollection()],
    });
    await page.goto("/admin/features/curated");

    await expect(page.getByTestId("quarantine-items-table")).toBeVisible();
    expect(state.itemsRequests[0]).toEqual({
      collectionId: QUARANTINE_ID,
      targetCollectionId: null,
    });

    await page
      .getByLabel("이동 target collection")
      .selectOption(OTHER_ID);
    await expect
      .poll(() =>
        state.itemsRequests.some(
          (request) => request.targetCollectionId === OTHER_ID,
        ),
      )
      .toBe(true);
  });

  test("move 성공 흐름 — Idempotency-Key 헤더와 body를 단언한다", async ({
    page,
  }) => {
    const state = await mockQuarantineRoutes(page, {
      adminCollections: [makeAdminCollection()],
      quarantineCollections: [makeQuarantineCollection()],
    });
    await page.goto("/admin/features/curated");
    await expect(page.getByTestId("quarantine-items-table")).toBeVisible();

    await quarantinePanel(page)
      .getByRole("button", { name: "이동", exact: true })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog.getByText("격리 항목 이동")).toBeVisible();
    await dialog.getByRole("button", { name: "이동", exact: true }).click();

    await expect.poll(() => state.reclassifyRequests.length).toBe(1);
    const observed = state.reclassifyRequests[0];
    expect(observed.collectionId).toBe(QUARANTINE_ID);
    expect(observed.body).toEqual({
      action: "move",
      item_ids: null,
      target_collection_id: ORIGINAL_ID,
    });
    expect(observed.idempotencyKey).toMatch(UUID_PATTERN);

    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "2개 항목을 이동했고, 빈 격리 collection을 삭제했습니다." }),
    ).toBeVisible();
  });

  test("move 409 충돌 응답을 충돌 목록으로 렌더한다", async ({ page }) => {
    await mockQuarantineRoutes(page, {
      adminCollections: [makeAdminCollection()],
      quarantineCollections: [makeQuarantineCollection()],
      reclassify: () => ({ body: moveConflictProblem(), status: 409 }),
    });
    await page.goto("/admin/features/curated");
    await expect(page.getByTestId("quarantine-items-table")).toBeVisible();

    await quarantinePanel(page)
      .getByRole("button", { name: "이동", exact: true })
      .click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: "이동", exact: true }).click();

    const conflicts = page.getByTestId("quarantine-move-conflicts");
    await expect(
      conflicts.getByText("이동 충돌 1건 — 전체가 거부되었습니다"),
    ).toBeVisible();
    await expect(
      conflicts.getByText(/구성요소 identity 충돌/),
    ).toBeVisible();
    await expect(page.getByText("재분류 실패")).toBeVisible();
  });

  test("confirm_standalone 흐름 — key/제목 입력과 확정 요청을 단언한다", async ({
    page,
  }) => {
    const state = await mockQuarantineRoutes(page, {
      adminCollections: [makeAdminCollection()],
      quarantineCollections: [makeQuarantineCollection()],
      reclassify: (body) => ({
        body: {
          data: {
            action: "confirm_standalone",
            collection_id: QUARANTINE_ID,
            collection_key: body.collection_key ?? null,
            moved_item_ids: null,
            quarantine_collection_deleted: null,
          },
          meta: meta("e2e-quarantine-standalone"),
        } satisfies QuarantineReclassifyResponse,
        status: 200,
      }),
    });
    await page.goto("/admin/features/curated");
    await expect(page.getByTestId("quarantine-items-table")).toBeVisible();

    await page
      .getByLabel("확정 collection key")
      .fill("legacy-lighthouse-2024");
    await page.getByLabel("확정 제목").fill("2024 구 등대 스탬프투어");
    await quarantinePanel(page)
      .getByRole("button", { name: "별도 collection 확정" })
      .click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog.getByText("별도 collection 확정")).toBeVisible();
    await dialog.getByRole("button", { name: "확정", exact: true }).click();

    await expect.poll(() => state.reclassifyRequests.length).toBe(1);
    const observed = state.reclassifyRequests[0];
    expect(observed.collectionId).toBe(QUARANTINE_ID);
    expect(observed.body).toEqual({
      action: "confirm_standalone",
      collection_key: "legacy-lighthouse-2024",
      title: "2024 구 등대 스탬프투어",
    });
    expect(observed.idempotencyKey).toMatch(UUID_PATTERN);

    await expect(
      page
        .getByRole("status")
        .filter({
          hasText:
            "“legacy-lighthouse-2024” 별도 collection으로 확정했습니다.",
        }),
    ).toBeVisible();
  });
});
