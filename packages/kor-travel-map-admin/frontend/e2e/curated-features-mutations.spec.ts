import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/admin/curated-features` — **route-mocked mutation/depth** spec
 * (T-AUDIT-0616 후속, `docs/reports/e2e-scenario-coverage-2026-06-16.md`).
 *
 * 자매 파일 `curated-features.spec.ts`는 라이브 smoke(렌더/필터/페이지 구조)만 덮는다.
 * 본 spec은 시드 후보가 필요한 select/unselect/patch/archive/source-rule patch·apply/
 * detail-snapshot/pagination/empty/error 흐름을 **모든 backend 호출을 mock해 결정적으로** 덮는다.
 *
 * 이 콘솔은 항상 4개 GET(curated-features/curated-sources/curated-themes/
 * curated-source-rules)을 발사하고, 첫 행이 자동 선택되면 detail-snapshot GET까지 발사한다.
 * `mockCuratedConsole`가 이 5개 route를 단일 핸들러에서 method+pathname으로 분기해 mock한다
 * (admin-ops.spec.ts house 패턴). live :12701 backend 누수 없음.
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. baseURL은 http://127.0.0.1:12705.
 */

type CuratedFeatureView = components["schemas"]["CuratedFeatureView"];
type CuratedFeaturesResponse = components["schemas"]["CuratedFeaturesResponse"];
type CuratedFeatureResponse = components["schemas"]["CuratedFeatureResponse"];
type CuratedSourceView = components["schemas"]["CuratedSourceView"];
type CuratedSourcesResponse = components["schemas"]["CuratedSourcesResponse"];
type CuratedSourceRuleView = components["schemas"]["CuratedSourceRuleView"];
type CuratedSourceRulesResponse =
  components["schemas"]["CuratedSourceRulesResponse"];
type CuratedSourceRuleResponse =
  components["schemas"]["CuratedSourceRuleResponse"];
type CuratedThemeView = components["schemas"]["CuratedThemeView"];
type CuratedThemesResponse = components["schemas"]["CuratedThemesResponse"];
type RuleApplyResponse = components["schemas"]["RuleApplyResponse"];
type CuratedFeatureDetailItemView =
  components["schemas"]["CuratedFeatureDetailItemView"];
type CuratedFeatureDetailSnapshotResponse =
  components["schemas"]["CuratedFeatureDetailSnapshotResponse"];
type CuratedPlaceSearchResponse =
  components["schemas"]["CuratedPlaceSearchResponse"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const FEATURE_A_ID = "curated-feature-aaaa";
const FEATURE_B_ID = "curated-feature-bbbb";
const THEME_ID = "theme-1111";
const SOURCE_ID = "source-1111";
const RULE_ID = "rule-1111";

function apiPath(pathname: string): string {
  return pathname.replace(/^\/api\/proxy/, "");
}

function makeCuratedFeature(
  overrides: Partial<CuratedFeatureView> = {},
): CuratedFeatureView {
  return {
    address: {},
    archived_at: null,
    content_version: 1,
    created_at: MOCK_NOW,
    curated_feature_id: FEATURE_A_ID,
    curation_status: "candidate",
    dataset_key: "visitkorea_areas",
    detail: {},
    display_summary: null,
    display_title: null,
    feature_category: "02020101",
    feature_id: "python-visitkorea-api::visitkorea_areas::feat-1",
    feature_kind: "place",
    feature_name: "경복궁",
    lat: 37.5796,
    legal_dong_code: null,
    lon: 126.977,
    metadata: {},
    provider: "python-visitkorea-api",
    rank_score: 0,
    rejected_at: null,
    rejected_by: null,
    rejection_reason: null,
    selected_at: null,
    selected_by: null,
    selection_origin: "manual",
    sido_code: null,
    sigungu_code: null,
    source_id: SOURCE_ID,
    source_name: "VisitKorea areas",
    source_record_key: null,
    source_url: null,
    theme_group: "culture",
    theme_id: THEME_ID,
    theme_name: "고궁 산책",
    theme_slug: "palace-walk",
    reuse_policy: "manual_review",
    curation_relation: "nearby_option",
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

function makeCuratedSource(
  overrides: Partial<CuratedSourceView> = {},
): CuratedSourceView {
  return {
    created_at: MOCK_NOW,
    dataset_key: "visitkorea_areas",
    freshness_note: null,
    last_checked_at: null,
    last_source_modified_at: null,
    license: null,
    metadata: {},
    next_expected_at: null,
    provider: "python-visitkorea-api",
    provider_status: "active",
    row_count: 100,
    source_id: SOURCE_ID,
    source_kind: "provider",
    source_name: "VisitKorea areas",
    source_url: null,
    update_cycle: "weekly",
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

function makeCuratedSourceRule(
  overrides: Partial<CuratedSourceRuleView> = {},
): CuratedSourceRuleView {
  return {
    category: "02020101",
    created_at: MOCK_NOW,
    dataset_key: "visitkorea_areas",
    default_action: "candidate",
    enabled: true,
    metadata: {},
    place_kind: "place",
    priority: 0,
    provider: "python-visitkorea-api",
    region_scope: {},
    rule_id: RULE_ID,
    source_id: SOURCE_ID,
    theme_id: THEME_ID,
    theme_slug: "palace-walk",
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

function makeCuratedTheme(
  overrides: Partial<CuratedThemeView> = {},
): CuratedThemeView {
  return {
    created_at: MOCK_NOW,
    default_curated: false,
    metadata: {},
    theme_description: "고궁 테마",
    theme_group: "culture",
    theme_id: THEME_ID,
    theme_name: "고궁 산책",
    theme_slug: "palace-walk",
    updated_at: MOCK_NOW,
    visibility: "admin_only",
    ...overrides,
  };
}

function makeDetailItem(
  overrides: Partial<CuratedFeatureDetailItemView> = {},
): CuratedFeatureDetailItemView {
  return {
    curated_feature_item_id: "detail-item-1",
    day_index: null,
    feature_id: "python-visitkorea-api::visitkorea_areas::feat-1",
    feature_snapshot: {},
    memo: "첫 코스",
    relation: "primary_stop",
    sort_order: 1,
    source_record_key: null,
    ...overrides,
  };
}

function featuresResponse(
  items: CuratedFeatureView[],
  nextCursor: string | null = null,
): CuratedFeaturesResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: { page_size: 50, next_cursor: nextCursor, total: null },
      request_id: "e2e-curated-features",
    },
  };
}

function featureResponse(
  feature: CuratedFeatureView,
): CuratedFeatureResponse {
  return {
    data: feature,
    meta: { duration_ms: 1, request_id: "e2e-curated-feature" },
  };
}

function sourcesResponse(
  items: CuratedSourceView[] = [makeCuratedSource()],
): CuratedSourcesResponse {
  return {
    data: { items },
    meta: { duration_ms: 1, request_id: "e2e-curated-sources" },
  };
}

function themesResponse(
  items: CuratedThemeView[] = [makeCuratedTheme()],
): CuratedThemesResponse {
  return {
    data: { items },
    meta: { duration_ms: 1, request_id: "e2e-curated-themes" },
  };
}

function rulesResponse(
  items: CuratedSourceRuleView[] = [],
): CuratedSourceRulesResponse {
  return {
    data: { items },
    meta: { duration_ms: 1, request_id: "e2e-curated-source-rules" },
  };
}

function ruleResponse(
  rule: CuratedSourceRuleView,
): CuratedSourceRuleResponse {
  return {
    data: rule,
    meta: { duration_ms: 1, request_id: "e2e-curated-source-rule" },
  };
}

function ruleApplyResponse(insertedOrUpdated: number): RuleApplyResponse {
  return {
    data: { inserted_or_updated: insertedOrUpdated, rule_id: RULE_ID },
    meta: { duration_ms: 1, request_id: "e2e-rule-apply" },
  };
}

function detailSnapshotResponse(
  items: CuratedFeatureDetailItemView[] = [makeDetailItem()],
): CuratedFeatureDetailSnapshotResponse {
  return {
    data: {
      curated_feature_id: FEATURE_A_ID,
      etag: "etag-0123456789abcdef",
      items,
      content: { title: "plan-1" },
      source: { source_id: SOURCE_ID },
      theme: { theme_id: THEME_ID },
      updated_at: MOCK_NOW,
      version: 3,
    },
    meta: { duration_ms: 1, request_id: "e2e-detail-snapshot" },
  };
}

function placeSearchResponse(query: string): CuratedPlaceSearchResponse {
  return {
    data: {
      errors: {},
      google: [
        {
          address: "서울 종로구",
          category: "tourist_attraction",
          latitude: 37.5796,
          longitude: 126.977,
          name: query,
          provider: "google",
          road_address: null,
        },
      ],
      kakao: [],
      naver: [],
      query,
    },
    meta: { duration_ms: 1, request_id: "e2e-place-search" },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

interface ConsoleOptions {
  /** 초기 후보 목록(빈 배열 = empty 상태). 첫 행이 자동 선택된다. */
  features?: CuratedFeatureView[];
  sources?: CuratedSourceView[];
  themes?: CuratedThemeView[];
  rules?: CuratedSourceRuleView[];
  detailItems?: CuratedFeatureDetailItemView[];
  /** features list GET을 500으로 실패시킨다(에러 배너 검증). */
  featuresError?: boolean;
  /** cursor 분기 — 두번째 페이지 items와 next_cursor를 다르게 반환. */
  cursorPaging?: boolean;
  /** apply mutation이 반영할 후보 수. */
  applyInsertedOrUpdated?: number;
}

interface ConsoleRequests {
  featuresList: number;
  select: number;
  unselect: number;
  patch: number;
  delete: number;
  rulePatch: number;
  ruleApply: number;
  detail: number;
  placeSearch: number;
  featureDetail: number;
  /** features list GET에 마지막으로 캡처된 query 파라미터. */
  lastPageSize: string | null;
  lastCursor: string | null;
  lastPlaceSearchQuery: string | null;
  selectBodies: unknown[];
  unselectBodies: unknown[];
  patchBodies: unknown[];
  deleteBodies: unknown[];
  rulePatchBodies: unknown[];
}

const SECOND_PAGE_FEATURE = makeCuratedFeature({
  curated_feature_id: "curated-feature-page2",
  feature_id: "python-visitkorea-api::visitkorea_areas::feat-page2",
  feature_name: "창덕궁",
});

/**
 * 콘솔의 5개 backend route를 mock한다. mutable state를 들고 있어 select/unselect/
 * archive 이후 list 재조회가 갱신본을 반환한다(react-query invalidate → refetch).
 */
async function mockCuratedConsole(
  page: Page,
  options: ConsoleOptions = {},
): Promise<ConsoleRequests> {
  let features = [...(options.features ?? [])];
  const sources = options.sources ?? [makeCuratedSource()];
  const themes = options.themes ?? [makeCuratedTheme()];
  let rules = [...(options.rules ?? [])];
  const detailItems = options.detailItems ?? [makeDetailItem()];

  const requests: ConsoleRequests = {
    featuresList: 0,
    select: 0,
    unselect: 0,
    patch: 0,
    delete: 0,
    rulePatch: 0,
    ruleApply: 0,
    detail: 0,
    placeSearch: 0,
    featureDetail: 0,
    lastPageSize: null,
    lastCursor: null,
    lastPlaceSearchQuery: null,
    selectBodies: [],
    unselectBodies: [],
    patchBodies: [],
    deleteBodies: [],
    rulePatchBodies: [],
  };

  function updateFeature(
    curatedFeatureId: string,
    patch: Partial<CuratedFeatureView>,
  ): CuratedFeatureView {
    let updated = makeCuratedFeature({ curated_feature_id: curatedFeatureId });
    features = features.map((item) => {
      if (item.curated_feature_id !== curatedFeatureId) return item;
      updated = { ...item, ...patch };
      return updated;
    });
    return updated;
  }

  // curated-features: list(GET) + select/unselect(POST) + patch(PATCH) + archive(DELETE).
  await page.route("**/v1/admin/curated-features**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = apiPath(url.pathname);

    if (method === "GET" && path.endsWith("/detail-snapshot")) {
      requests.detail += 1;
      await fulfillJson(route, detailSnapshotResponse(detailItems));
      return;
    }

    if (method === "GET" && path.endsWith("/place-search")) {
      requests.placeSearch += 1;
      requests.lastPlaceSearchQuery = url.searchParams.get("q");
      await fulfillJson(
        route,
        placeSearchResponse(url.searchParams.get("q") ?? ""),
      );
      return;
    }

    if (method === "GET" && path === "/v1/admin/curated-features") {
      requests.featuresList += 1;
      requests.lastPageSize = url.searchParams.get("page_size");
      requests.lastCursor = url.searchParams.get("cursor");
      if (options.featuresError) {
        await fulfillJson(
          route,
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "curated feature list failed",
            code: "internal_error",
          },
          500,
        );
        return;
      }
      if (options.cursorPaging) {
        if (url.searchParams.get("cursor") === "CURSOR_2") {
          await fulfillJson(route, featuresResponse([SECOND_PAGE_FEATURE], null));
          return;
        }
        await fulfillJson(route, featuresResponse(features, "CURSOR_2"));
        return;
      }
      await fulfillJson(route, featuresResponse(features, null));
      return;
    }

    if (method === "GET" && path.startsWith("/v1/admin/curated-features/")) {
      requests.featureDetail += 1;
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      await fulfillJson(
        route,
        featureResponse(
          features.find((item) => item.curated_feature_id === id) ??
            makeCuratedFeature({ curated_feature_id: id }),
        ),
      );
      return;
    }

    if (method === "POST" && path.endsWith("/select")) {
      requests.select += 1;
      requests.selectBodies.push(request.postDataJSON());
      const id = decodeURIComponent(path.split("/").at(-2) ?? "");
      const updated = updateFeature(id, {
        curation_status: "curated",
        selected_at: MOCK_NOW,
        selected_by: "admin-ui",
      });
      await fulfillJson(route, featureResponse(updated));
      return;
    }

    if (method === "POST" && path.endsWith("/unselect")) {
      requests.unselect += 1;
      requests.unselectBodies.push(request.postDataJSON());
      const id = decodeURIComponent(path.split("/").at(-2) ?? "");
      const updated = updateFeature(id, {
        curation_status: "candidate",
        selected_at: null,
        selected_by: null,
      });
      await fulfillJson(route, featureResponse(updated));
      return;
    }

    if (method === "PATCH" && path.startsWith("/v1/admin/curated-features/")) {
      requests.patch += 1;
      requests.patchBodies.push(request.postDataJSON());
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      const updated = updateFeature(id, {});
      await fulfillJson(route, featureResponse(updated));
      return;
    }

    if (method === "DELETE" && path.startsWith("/v1/admin/curated-features/")) {
      requests.delete += 1;
      requests.deleteBodies.push(request.postDataJSON());
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      const updated = updateFeature(id, {
        curation_status: "archived",
        archived_at: MOCK_NOW,
      });
      features = features.filter((item) => item.curated_feature_id !== id);
      await fulfillJson(route, featureResponse(updated));
      return;
    }

    throw new Error(`Unhandled curated-features route: ${method} ${url.href}`);
  });

  // curated-source-rules: list(GET) + patch(PATCH) + apply(POST .../apply).
  await page.route("**/v1/admin/curated-source-rules**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = apiPath(url.pathname);

    if (method === "GET" && path === "/v1/admin/curated-source-rules") {
      await fulfillJson(route, rulesResponse(rules));
      return;
    }

    if (method === "POST" && path.endsWith("/apply")) {
      requests.ruleApply += 1;
      await fulfillJson(
        route,
        ruleApplyResponse(options.applyInsertedOrUpdated ?? 7),
      );
      return;
    }

    if (
      method === "PATCH" &&
      path.startsWith("/v1/admin/curated-source-rules/")
    ) {
      requests.rulePatch += 1;
      requests.rulePatchBodies.push(request.postDataJSON());
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      const body = request.postDataJSON() as Partial<CuratedSourceRuleView>;
      let patched = makeCuratedSourceRule({ rule_id: id });
      rules = rules.map((item) => {
        if (item.rule_id !== id) return item;
        patched = { ...item, ...body };
        return patched;
      });
      await fulfillJson(route, ruleResponse(patched));
      return;
    }

    throw new Error(
      `Unhandled curated-source-rules route: ${method} ${url.href}`,
    );
  });

  await page.route("**/v1/admin/curated-sources**", async (route) => {
    await fulfillJson(route, sourcesResponse(sources));
  });

  await page.route("**/v1/admin/curated-themes**", async (route) => {
    await fulfillJson(route, themesResponse(themes));
  });

  await page.route(
    "**/v1/admin/curated-features/*/detail-snapshot**",
    async (route) => {
      requests.detail += 1;
      await fulfillJson(route, detailSnapshotResponse(detailItems));
    },
  );

  return requests;
}

test.describe("/admin/curated-features mutations (route-mocked)", () => {
  test("curated detail 링크가 전용 상세 화면으로 이동", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/curated-features");
    await page.getByRole("link", { name: "curated detail" }).first().click();

    await expect(page).toHaveURL(new RegExp(`/admin/curated-features/${FEATURE_A_ID}$`));
    await expect(page.getByText("Curated feature detail")).toBeVisible();
    await expect(page.getByText("Location review")).toBeVisible();
    await expect(page.getByText("Place search")).toBeVisible();
    await expect.poll(() => requests.featureDetail).toBe(1);
  });

  test("후보 select → curated 전환 (POST /select + invalidate refetch)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/curated-features");

    const row = page.getByRole("row", { name: /경복궁/ });
    await expect(row).toBeVisible();
    // candidate 행은 select(체크) 버튼을 노출한다.
    const selectButton = row.getByRole("button", { name: "select" });
    await expect(selectButton).toBeVisible();

    await selectButton.click();
    await expect.poll(() => requests.select).toBe(1);
    expect(requests.selectBodies[0]).toMatchObject({
      actor: "admin-ui",
      reason: "admin curated selection",
    });

    // invalidate → list 재조회로 갱신본을 받아 status Badge=curated, 버튼이 unselect로 전환.
    await expect(row.getByText("curated")).toBeVisible();
    await expect(row.getByRole("button", { name: "unselect" })).toBeVisible();
  });

  test("curated 후보 unselect → candidate 복귀 (POST /unselect)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({
          curation_status: "curated",
          selected_at: MOCK_NOW,
          selected_by: "admin-ui",
        }),
      ],
    });

    await page.goto("/admin/curated-features");
    await page.getByLabel("curation status filter").selectOption("curated");

    const row = page.getByRole("row", { name: /경복궁/ });
    const unselectButton = row.getByRole("button", { name: "unselect" });
    await expect(unselectButton).toBeVisible();

    await unselectButton.click();
    await expect.poll(() => requests.unselect).toBe(1);
    expect(requests.unselectBodies[0]).toMatchObject({
      actor: "admin-ui",
      reason: "admin curated unselect",
    });

    // candidate로 복귀 → select 버튼 재등장.
    await expect(row.getByRole("button", { name: "select" })).toBeVisible();
  });

  test("curated feature display/detail patch 저장 (PATCH curated-features/{id})", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/curated-features");

    // 첫 행이 자동 선택되어 FeatureEditor가 렌더된다.
    await expect(page.getByText("Curated display")).toBeVisible();
    await page.getByLabel("display title").fill("경복궁 야간개장");
    await page.getByLabel("display summary").fill("야간 고궁 산책 추천");
    await page.getByLabel("rank score").fill("4.5");
    await page.getByLabel("reuse policy").selectOption("allowed");
    await page.getByLabel("curation relation").selectOption("primary_stop");

    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      display_title: "경복궁 야간개장",
      display_summary: "야간 고궁 산책 추천",
      rank_score: 4.5,
      reuse_policy: "allowed",
      curation_relation: "primary_stop",
    });
  });

  test("place 검색은 행 선택으로 자동 누적 실행하지 않고 명시 검색만 호출", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({ curated_feature_id: FEATURE_A_ID, feature_name: "경복궁" }),
        makeCuratedFeature({
          curated_feature_id: FEATURE_B_ID,
          feature_id: "python-visitkorea-api::visitkorea_areas::feat-2",
          feature_name: "창덕궁",
        }),
      ],
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Place search")).toBeVisible();
    await expect(page.getByLabel("place search query")).toHaveValue("경복궁");
    await expect.poll(() => requests.placeSearch).toBe(0);

    await page.getByLabel("place search query").fill("경복궁 야간");
    await page.getByRole("button", { name: "검색" }).click();
    await expect.poll(() => requests.placeSearch).toBe(1);
    expect(requests.lastPlaceSearchQuery).toBe("경복궁 야간");
    await expect(page.getByText("경복궁 야간")).toBeVisible();

    await page.getByRole("row", { name: /창덕궁/ }).click();
    await expect(page.getByLabel("place search query")).toHaveValue("창덕궁");
    await expect(page.getByText("검색어를 확인하고 검색을 누르세요.")).toBeVisible();
    await expect.poll(() => requests.placeSearch).toBe(1);
  });

  test("빈 display title/summary는 null로 전송 (trim 후 length 0)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({
          display_title: "기존 제목",
          display_summary: "기존 요약",
          rank_score: 2,
        }),
      ],
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Curated display")).toBeVisible();

    await page.getByLabel("display title").fill("   ");
    await page.getByLabel("display summary").fill("");
    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      display_title: null,
      display_summary: null,
    });
  });

  test("reuse policy / relation select 옵션 전부 + 로컬 state 반영", async ({
    page,
  }) => {
    await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({
          reuse_policy: "manual_review",
          curation_relation: "nearby_option",
        }),
      ],
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Curated display")).toBeVisible();

    const detailPolicy = page.getByLabel("reuse policy");
    for (const option of ["allowed", "blocked", "manual_review"]) {
      await detailPolicy.selectOption(option);
      await expect(detailPolicy).toHaveValue(option);
    }

    const relation = page.getByLabel("curation relation");
    for (const option of [
      "primary_stop",
      "food_stop",
      "cafe_stop",
      "bookstore_stop",
      "nearby_option",
      "accessibility_support",
      "pet_support",
      "family_support",
      "theme_area_anchor",
    ]) {
      await relation.selectOption(option);
      await expect(relation).toHaveValue(option);
    }
  });

  test("후보 archive — confirm 취소→미호출, 확인→DELETE", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/curated-features");
    const row = page.getByRole("row", { name: /경복궁/ });
    const archiveButton = row.getByRole("button", { name: "archive" });
    await expect(archiveButton).toBeVisible();

    // 1) confirm dismiss → DELETE 미발생 + 메시지 검증.
    let dialogMessage = "";
    page.once("dialog", (dialog) => {
      dialogMessage = dialog.message();
      void dialog.dismiss();
    });
    await archiveButton.click();
    await expect.poll(() => dialogMessage).toContain("경복궁 후보를 archive할까요?");
    // 잠깐 기다려도 DELETE가 발생하지 않음을 보장.
    await expect.poll(() => requests.delete).toBe(0);

    // 2) confirm accept → DELETE 1회 + body 검증(deleteJson은 body를 함께 전송).
    page.once("dialog", (dialog) => void dialog.accept());
    await archiveButton.click();
    await expect.poll(() => requests.delete).toBe(1);
    expect(requests.deleteBodies[0]).toMatchObject({
      actor: "admin-ui",
      reason: "admin curated archive",
    });
  });

  test("source rule patch 저장 + JSON object 검증 (PATCH curated-source-rules/{id})", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
    });

    await page.goto("/admin/curated-features");

    // 첫 rule이 자동 선택되어 RuleEditor가 렌더된다.
    await expect(page.getByText("Source rule editor")).toBeVisible();
    await page.getByLabel("action").selectOption("curated");
    await page.getByLabel("priority").fill("5");
    await page.getByLabel("place_kind").fill("place");
    await page.getByLabel("category").fill("02020101");
    await page.getByLabel("region_scope").fill('{"sido_code": "11"}');
    await page.getByLabel("metadata").fill('{"note": "seoul only"}');

    await page.getByRole("button", { name: "Rule 저장" }).click();

    await expect.poll(() => requests.rulePatch).toBe(1);
    expect(requests.rulePatchBodies[0]).toMatchObject({
      default_action: "curated",
      priority: 5,
      place_kind: "place",
      category: "02020101",
      region_scope: { sido_code: "11" },
      metadata: { note: "seoul only" },
    });
  });

  test("source rule metadata 배열 입력 → 클라 검증 throw (네트워크 미호출)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Source rule editor")).toBeVisible();

    // metadata에 JSON 배열 → parseJsonObject가 동기 throw → jsonError 표시, PATCH 미호출.
    await page.getByLabel("metadata").fill("[]");
    await page.getByRole("button", { name: "Rule 저장" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: "source rule 처리 실패" }),
    ).toBeVisible();
    await expect(
      page.getByText("metadata은 JSON object여야 합니다."),
    ).toBeVisible();
    expect(requests.rulePatch).toBe(0);
  });

  test("source rule apply (POST .../apply) → role=status 성공 알림", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
      applyInsertedOrUpdated: 7,
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Source rule editor")).toBeVisible();

    await page.getByRole("button", { name: "Apply" }).click();

    await expect.poll(() => requests.ruleApply).toBe(1);
    // 성공 시 default-variant Alert(role=status)에 formatCount 적용 텍스트 노출.
    await expect(
      page.getByRole("status").filter({ hasText: "source rule apply 완료" }),
    ).toBeVisible();
    await expect(page.getByText("7개 후보를 반영했습니다.")).toBeVisible();
  });

  test("detail snapshot 미리보기 + item 테이블", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      detailItems: [makeDetailItem()],
    });

    await page.goto("/admin/curated-features");

    // 첫 행 자동 선택 → snapshot 쿼리 enabled → detail-snapshot GET 1회.
    await expect(page.getByText("Detail snapshot preview")).toBeVisible();
    await expect.poll(() => requests.detail).toBeGreaterThanOrEqual(1);

    // etag Badge (shortId(etag, 10)).
    await expect(page.getByText(/^etag /)).toBeVisible();
    // detail item 테이블 헤더 + relation Badge. 'feature' 컬럼은 메인 후보 테이블에도
    // 있으므로 snapshot 테이블(고유 'order' 헤더 보유)로 스코프해 strict-mode 충돌 회피.
    const snapshotTable = page.getByRole("table").filter({
      has: page.getByRole("columnheader", { name: "order", exact: true }),
    });
    for (const column of ["order", "relation", "feature", "memo"]) {
      await expect(
        snapshotTable.getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }
    // 'primary_stop'은 detail-policy/relation select의 <option>으로도 존재하므로
    // snapshot 테이블로 스코프해 strict-mode 충돌을 피한다.
    await expect(snapshotTable.getByText("primary_stop")).toBeVisible();
  });

  test("detail snapshot items 0건 → emptyMessage", async ({ page }) => {
    await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      detailItems: [],
    });

    await page.goto("/admin/curated-features");
    await expect(page.getByText("Detail snapshot preview")).toBeVisible();
    await expect(page.getByText("detail item이 없습니다.")).toBeVisible();
  });

  test("cursor 페이지네이션 — 다음/처음 버튼 + cursor 재요청", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      cursorPaging: true,
    });

    await page.goto("/admin/curated-features");

    const firstButton = page.getByRole("button", { name: "처음" });
    const nextButton = page.getByRole("button", { name: "다음" });
    // 초기: 처음 disabled(cursor===null), 다음 enabled(next_cursor!=null).
    await expect(firstButton).toBeDisabled();
    await expect(nextButton).toBeEnabled();

    await nextButton.click();
    // cursor=CURSOR_2로 재요청.
    await expect.poll(() => requests.lastCursor).toBe("CURSOR_2");
    await expect(page.getByRole("row", { name: /창덕궁/ })).toBeVisible();
    // 2번째 응답 next_cursor=null → 다음 disabled, 처음 enabled.
    await expect(nextButton).toBeDisabled();
    await expect(firstButton).toBeEnabled();

    await firstButton.click();
    // "처음"은 cursor를 null로 되돌려 초기 query key와 동일해진다. 초기 페이지 응답은
    // staleTime(30s) 내 fresh 캐시라 react-query가 네트워크 재요청 없이 캐시본을
    // 제공한다 → lastCursor는 갱신되지 않으므로 UI 복원(경복궁 + 버튼 상태)으로 검증.
    await expect(page.getByRole("row", { name: /경복궁/ })).toBeVisible();
    await expect(firstButton).toBeDisabled();
    await expect(nextButton).toBeEnabled();
  });

  test("page size 200 전환이 page_size 쿼리에 반영", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/curated-features");
    await expect.poll(() => requests.featuresList).toBeGreaterThanOrEqual(1);

    await page.getByLabel("page size").selectOption("200");
    await expect.poll(() => requests.lastPageSize).toBe("200");
    // 카운트 라인 갱신.
    await expect(page.getByText(/page size 200/)).toBeVisible();
  });

  test("빈 상태 — 후보/룰 0건이면 안내 문구", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [],
      sources: [],
      themes: [],
    });

    await page.goto("/admin/curated-features");

    await expect(
      page.getByText("조건에 맞는 curated 후보가 없습니다."),
    ).toBeVisible();
    await expect(
      page.getByText("조건에 맞는 source rule이 없습니다."),
    ).toBeVisible();
    await expect(
      page.getByText("후보를 선택하면 상세를 확인할 수 있습니다."),
    ).toBeVisible();
    await expect(
      page.getByText(
        "후보를 선택하면 display text와 공개 재사용 속성을 편집할 수 있습니다.",
      ),
    ).toBeVisible();
    await expect(
      page.getByText("후보를 선택하면 detail snapshot을 조회합니다."),
    ).toBeVisible();

    // selectedFeature null → detail-snapshot 쿼리 disabled → GET 0회.
    await expect.poll(() => requests.featuresList).toBeGreaterThanOrEqual(1);
    expect(requests.detail).toBe(0);
  });

  test("features list 500 → role=alert 배너", async ({ page }) => {
    await mockCuratedConsole(page, {
      features: [],
      featuresError: true,
    });

    await page.goto("/admin/curated-features");

    await expect(
      page.getByRole("alert").filter({ hasText: "curated admin 처리 실패" }),
    ).toBeVisible();
  });

  test("feature detail deep-link href", async ({ page }) => {
    const feature = makeCuratedFeature();
    await mockCuratedConsole(page, { features: [feature] });

    await page.goto("/admin/curated-features");

    const detailLink = page.getByRole("link", { name: "feature detail" });
    await expect(detailLink).toHaveAttribute(
      "href",
      `/features/${encodeURIComponent(feature.feature_id)}`,
    );
  });

  test("bulk 전체 선택 → 선택 채택(POST /select 행 수만큼)", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature(),
        makeCuratedFeature({
          curated_feature_id: FEATURE_B_ID,
          feature_id: "python-visitkorea-api::visitkorea_areas::feat-2",
          feature_name: "창경궁",
        }),
      ],
    });

    await page.goto("/admin/curated-features");

    // 행이 렌더된 뒤에 select-all을 눌러야 토글이 반영된다(이른 클릭 레이스 방지).
    await expect(
      page.getByRole("checkbox", { name: "행 선택" }).first(),
    ).toBeVisible();
    // 선택 동작은 bulk 툴바(N개 선택됨)로 검증한다. select-all의 aria-checked는
    // getIsAllPageRowsSelected()에 묶여 table row-model 설정에 따라 안 켜질 수 있어
    // 의존하지 않는다.
    const selectAll = page.getByRole("checkbox", { name: "전체 선택" });
    await selectAll.click();
    await expect(page.getByText(/개 선택됨/)).toBeVisible();

    await page.getByRole("button", { name: "선택 채택" }).click();
    // 선택 행 수(2)만큼 POST /select.
    await expect.poll(() => requests.select).toBe(2);
  });

  test("bulk 선택 보관 — confirm 1회 후 DELETE 행 수만큼", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature(),
        makeCuratedFeature({
          curated_feature_id: FEATURE_B_ID,
          feature_id: "python-visitkorea-api::visitkorea_areas::feat-2",
          feature_name: "창경궁",
        }),
      ],
    });

    await page.goto("/admin/curated-features");

    // 행이 렌더된 뒤에 select-all을 눌러야 토글이 반영된다(이른 클릭 레이스 방지).
    await expect(
      page.getByRole("checkbox", { name: "행 선택" }).first(),
    ).toBeVisible();
    // 선택은 bulk 툴바로 검증(aria-checked는 getIsAllPageRowsSelected 의존이라 미사용).
    const selectAll = page.getByRole("checkbox", { name: "전체 선택" });
    await selectAll.click();
    await expect(page.getByText(/개 선택됨/)).toBeVisible();

    let dialogMessage = "";
    page.once("dialog", (dialog) => {
      dialogMessage = dialog.message();
      void dialog.accept();
    });
    await page.getByRole("button", { name: "선택 보관" }).click();

    await expect.poll(() => dialogMessage).toContain("선택한 2건을 보관할까요?");
    await expect.poll(() => requests.delete).toBe(2);
  });
});
