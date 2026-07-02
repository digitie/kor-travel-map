import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/admin/features/curated` — **route-mocked mutation/depth** spec
 * (T-AUDIT-0616 후속, `docs/reports/e2e-scenario-coverage-2026-06-16.md`).
 *
 * 자매 파일 `curated-features.spec.ts`는 라이브 smoke(렌더/필터/탭 구조)만 덮는다.
 * 본 spec은 시드 후보가 필요한 select/unselect/patch/archive/source-rule patch·apply/
 * detail-snapshot/pagination/empty/error 흐름과 UX 개편 동작(상태 전환 토스트+필터
 * 점프, bulk 부분 실패 집계, 서버 검색 q, editor dirty 가드, 재사용 정책 opt-out,
 * 규칙 적용 confirm)을 **모든 backend 호출을 mock해 결정적으로** 덮는다.
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
const THEME_B_ID = "theme-2222";
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
  /** 이 id들의 POST /select는 500 — bulk 부분 실패 검증. */
  selectErrorIds?: string[];
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
  lastQ: string | null;
  lastCurationStatus: string | null;
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
  const selectErrorIds = new Set(options.selectErrorIds ?? []);
  let mutationCounter = 0;

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
    lastQ: null,
    lastCurationStatus: null,
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
      mutationCounter += 1;
      updated = {
        ...item,
        ...patch,
        content_version: item.content_version + 1,
        updated_at: `2026-06-08T00:00:${String(mutationCounter).padStart(
          2,
          "0",
        )}.000Z`,
      };
      return updated;
    });
    return updated;
  }

  // curated-features: list(GET) + select/unselect(POST) + patch(PATCH) + archive(DELETE).
  await page.route("**/v1/admin/features/curated**", async (route) => {
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

    if (method === "GET" && path === "/v1/admin/features/curated") {
      requests.featuresList += 1;
      requests.lastPageSize = url.searchParams.get("page_size");
      requests.lastCursor = url.searchParams.get("cursor");
      requests.lastQ = url.searchParams.get("q");
      requests.lastCurationStatus = url.searchParams.get("curation_status");
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

    if (method === "GET" && path.startsWith("/v1/admin/features/curated/")) {
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
      if (selectErrorIds.has(id)) {
        await fulfillJson(
          route,
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "select failed",
            code: "internal_error",
          },
          500,
        );
        return;
      }
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

    if (method === "PATCH" && path.startsWith("/v1/admin/features/curated/")) {
      requests.patch += 1;
      const body = request.postDataJSON() as Partial<CuratedFeatureView>;
      requests.patchBodies.push(body);
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      const updated = updateFeature(id, body);
      await fulfillJson(route, featureResponse(updated));
      return;
    }

    if (method === "DELETE" && path.startsWith("/v1/admin/features/curated/")) {
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
    "**/v1/admin/features/curated/*/detail-snapshot**",
    async (route) => {
      requests.detail += 1;
      await fulfillJson(route, detailSnapshotResponse(detailItems));
    },
  );

  return requests;
}

/** '소스 규칙' 탭을 연다 — UX 개편으로 rule 패널은 탭 뒤에 있다. */
async function openRulesTab(page: Page) {
  await page.getByRole("tab", { name: "소스 규칙" }).click();
  await expect(page.getByText("소스 규칙 편집")).toBeVisible();
}

test.describe("/admin/features/curated mutations (route-mocked)", () => {
  test("상세 링크와 전용 상세 화면 렌더", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");
    await expect(
      page
        .getByTestId("curated-feature-row")
        .first()
        .getByRole("link", { name: "상세" }),
    ).toHaveAttribute("href", `/admin/features/curated/${FEATURE_A_ID}`);

    await page.goto(`/admin/features/curated/${FEATURE_A_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page).toHaveURL(
      new RegExp(`/admin/features/curated/${FEATURE_A_ID}$`),
    );
    await expect(
      page.getByRole("heading", { name: "큐레이션 상세" }),
    ).toBeVisible();
    await expect(page.getByText("위치 확인")).toBeVisible();
    await expect(page.getByText("장소 대조 검색")).toBeVisible();
    await expect.poll(() => requests.featureDetail).toBeGreaterThanOrEqual(1);
  });

  test("후보 채택 → 상태 전환 토스트 + '큐레이션됨 보기' 필터 점프", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");

    const row = page.getByRole("row", { name: /경복궁/ });
    await expect(row).toBeVisible();
    // candidate 행은 채택 버튼을 노출한다.
    const selectButton = row.getByRole("button", { name: "채택", exact: true });
    await expect(selectButton).toBeVisible();

    await selectButton.click();
    await expect.poll(() => requests.select).toBe(1);
    expect(requests.selectBodies[0]).toMatchObject({
      actor: "admin-ui",
      reason: "admin curated selection",
    });

    // 상태 전환 토스트 — 어디로 갔는지 알려주고 필터 점프 액션을 제공한다.
    await expect(
      page.getByText("채택 완료 — 후보 → 큐레이션됨"),
    ).toBeVisible();
    await page.getByRole("button", { name: "큐레이션됨 보기" }).click();
    await expect(page.getByLabel("curation status filter")).toHaveValue(
      "curated",
    );
    // 점프 후 목록 재조회는 curation_status=curated로 나간다.
    await expect.poll(() => requests.lastCurationStatus).toBe("curated");
    // invalidate → list 재조회 갱신본: status Badge=큐레이션됨 + 채택 해제 버튼.
    await expect(row.getByText("큐레이션됨")).toBeVisible();
    await expect(
      row.getByRole("button", { name: "채택 해제" }),
    ).toBeVisible();
  });

  test("큐레이션됨 채택 해제 → 토스트 + candidate 복귀 (POST /unselect)", async ({
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

    await page.goto("/admin/features/curated");
    await page.getByLabel("curation status filter").selectOption("curated");

    const row = page.getByRole("row", { name: /경복궁/ });
    const unselectButton = row.getByRole("button", { name: "채택 해제" });
    await expect(unselectButton).toBeVisible();

    await unselectButton.click();
    await expect.poll(() => requests.unselect).toBe(1);
    expect(requests.unselectBodies[0]).toMatchObject({
      actor: "admin-ui",
      reason: "admin curated unselect",
    });

    await expect(
      page.getByText("채택 해제 완료 — 큐레이션됨 → 거절됨"),
    ).toBeVisible();
    // mock은 candidate로 복귀시킨다 → 채택 버튼 재등장.
    await expect(
      row.getByRole("button", { name: "채택", exact: true }),
    ).toBeVisible();
  });

  test("노출 정보 patch 저장 (PATCH curated-features/{id})", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      themes: [
        makeCuratedTheme(),
        makeCuratedTheme({
          theme_group: "media",
          theme_id: THEME_B_ID,
          theme_name: "영상 여행",
          theme_slug: "media-places",
        }),
      ],
    });

    await page.goto("/admin/features/curated");

    // 첫 행이 자동 선택되어 FeatureEditor가 렌더된다.
    await expect(page.getByText("노출 정보 편집")).toBeVisible();
    await page.getByLabel("테마", { exact: true }).selectOption(THEME_B_ID);
    await page.getByLabel("표시 제목").fill("경복궁 야간개장");
    await page.getByLabel("표시 요약").fill("야간 고궁 산책 추천");
    await page.getByLabel("노출 순위").fill("4.5");
    await page.getByLabel("재사용 정책").selectOption("allowed");
    await page.getByLabel("큐레이션 관계").selectOption("primary_stop");

    await page.getByRole("button", { name: "저장", exact: true }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      theme_id: THEME_B_ID,
      display_title: "경복궁 야간개장",
      display_summary: "야간 고궁 산책 추천",
      rank_score: 4.5,
      reuse_policy: "allowed",
      curation_relation: "primary_stop",
    });
  });

  test("노출 순위 잘못된 값 → 에러 표시 + PATCH 미발생", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");
    await expect(page.getByText("노출 정보 편집")).toBeVisible();

    await page.getByLabel("노출 순위").fill("abc");
    await expect(page.getByText("숫자를 입력하세요")).toBeVisible();
    // 저장 버튼이 비활성화되어 PATCH가 나가지 않는다.
    await expect(
      page.getByRole("button", { name: "저장", exact: true }),
    ).toBeDisabled();
    expect(requests.patch).toBe(0);
  });

  test("editor dirty 가드 — 다른 작업 수정 감지 + 최신 값 불러오기", async ({
    page,
  }) => {
    await mockCuratedConsole(page, {
      features: [makeCuratedFeature({ feature_name: "경복궁" })],
    });

    await page.goto("/admin/features/curated");
    await expect(page.getByText("노출 정보 편집")).toBeVisible();

    // 1) editor에 입력(dirty) → 수정됨 배지.
    await page.getByLabel("표시 요약").fill("검토 중 임시 메모");
    await expect(page.getByText("수정됨")).toBeVisible();

    // 2) 같은 항목을 place-search '결과 적용'이 patch → updated_at 전진.
    await page.getByLabel("place search query").fill("경복궁");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    await page.getByRole("button", { name: "결과 적용" }).first().click();

    // 3) dirty 입력은 유지되고, 서버 변경 Alert가 뜬다.
    await expect(page.getByLabel("표시 요약")).toHaveValue("검토 중 임시 메모");
    await expect(
      page.getByText("다른 작업이 이 항목을 수정했습니다."),
    ).toBeVisible();

    // 4) '최신 값 불러오기' → 입력이 서버 값으로 교체된다(서버 summary는 null).
    await page.getByRole("button", { name: "최신 값 불러오기" }).click();
    await expect(page.getByLabel("표시 요약")).toHaveValue("");
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

    await page.goto("/admin/features/curated");
    await expect(page.getByText("장소 대조 검색")).toBeVisible();
    await expect(page.getByLabel("place search query")).toHaveValue("경복궁");
    await expect.poll(() => requests.placeSearch).toBe(0);

    await page.getByLabel("place search query").fill("경복궁 야간");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    await expect.poll(() => requests.placeSearch).toBe(1);
    expect(requests.lastPlaceSearchQuery).toBe("경복궁 야간");
    await expect(page.getByText("경복궁 야간").first()).toBeVisible();

    await page.getByRole("row", { name: /창덕궁/ }).click();
    await expect(page.getByLabel("place search query")).toHaveValue("창덕궁");
    await expect(page.getByText("검색어를 확인하고 검색을 누르세요.")).toBeVisible();
    await expect.poll(() => requests.placeSearch).toBe(1);
  });

  test("결과 적용 — 기본 체크 상태면 reuse policy를 allowed로 전환", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({
          reuse_policy: "manual_review",
          feature_name: "경복궁",
        }),
      ],
    });

    await page.goto("/admin/features/curated");
    await expect(page.getByText("장소 대조 검색")).toBeVisible();

    await page.getByLabel("place search query").fill("경복궁");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    await expect.poll(() => requests.placeSearch).toBe(1);

    await page.getByRole("button", { name: "결과 적용" }).first().click();
    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      display_title: "경복궁",
      reuse_policy: "allowed",
      metadata: {
        place_search_review: {
          provider: "google",
          query: "경복궁",
          name: "경복궁",
          address: "서울 종로구",
          latitude: 37.5796,
          longitude: 126.977,
          category: "tourist_attraction",
        },
      },
    });
    await expect(page.getByText("적용 완료")).toBeVisible();
    await expect(
      page.getByText("재사용 정책: 재사용 허용으로 설정됨"),
    ).toBeVisible();
    await expect(
      page.getByRole("row", { name: /경복궁/ }).getByText("재사용 허용"),
    ).toBeVisible();
    await expect(page.getByLabel("재사용 정책")).toHaveValue("allowed");
  });

  test("결과 적용 — 체크 해제 시 PATCH body에 reuse_policy 없음", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature({
          reuse_policy: "manual_review",
          feature_name: "경복궁",
        }),
      ],
    });

    await page.goto("/admin/features/curated");
    await expect(page.getByText("장소 대조 검색")).toBeVisible();

    await page
      .getByLabel("적용 시 재사용 정책을 '재사용 허용'으로 변경")
      .uncheck();
    await page.getByLabel("place search query").fill("경복궁");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    await expect.poll(() => requests.placeSearch).toBe(1);

    await page.getByRole("button", { name: "결과 적용" }).first().click();
    await expect.poll(() => requests.patch).toBe(1);
    const body = requests.patchBodies[0] as Record<string, unknown>;
    expect(body).toMatchObject({ display_title: "경복궁" });
    expect(Object.prototype.hasOwnProperty.call(body, "reuse_policy")).toBe(
      false,
    );
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

    await page.goto("/admin/features/curated");
    await expect(page.getByText("노출 정보 편집")).toBeVisible();

    await page.getByLabel("표시 제목").fill("   ");
    await page.getByLabel("표시 요약").fill("");
    await page.getByRole("button", { name: "저장", exact: true }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      display_title: null,
      display_summary: null,
    });
  });

  test("재사용 정책 / 큐레이션 관계 select 옵션 전부 + 로컬 state 반영", async ({
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

    await page.goto("/admin/features/curated");
    await expect(page.getByText("노출 정보 편집")).toBeVisible();

    const detailPolicy = page.getByLabel("재사용 정책");
    for (const option of ["allowed", "blocked", "manual_review"]) {
      await detailPolicy.selectOption(option);
      await expect(detailPolicy).toHaveValue(option);
    }

    const relation = page.getByLabel("큐레이션 관계");
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

  test("후보 보관 — confirm 취소→미호출, 확인→DELETE + 토스트", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");
    const row = page.getByRole("row", { name: /경복궁/ });
    const archiveButton = row.getByRole("button", { name: "보관", exact: true });
    await expect(archiveButton).toBeVisible();

    // 1) confirm dismiss → DELETE 미발생 + 결과를 설명하는 메시지 검증.
    let dialogMessage = "";
    page.once("dialog", (dialog) => {
      dialogMessage = dialog.message();
      void dialog.dismiss();
    });
    await archiveButton.click();
    await expect.poll(() => dialogMessage).toContain("보관할까요");
    expect(dialogMessage).toContain("규칙 재적용으로 되살아나지 않으며");
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
    await expect(page.getByText("보관 완료")).toBeVisible();
  });

  test("서버 검색 — 입력이 디바운스 후 q 파라미터로 나간다 (client 필터 제거)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");
    await expect.poll(() => requests.featuresList).toBeGreaterThanOrEqual(1);

    await page.getByLabel("curated feature search").fill("zzz-no-client-match");
    // 서버 검색: q가 그대로 목록 GET에 실려 나간다.
    await expect.poll(() => requests.lastQ).toBe("zzz-no-client-match");
    // mock 서버는 여전히 경복궁을 반환 → client 필터가 사라졌으므로 행이 보인다.
    await expect(page.getByRole("row", { name: /경복궁/ })).toBeVisible();
  });

  test("source rule patch 저장 + JSON object 검증 (PATCH curated-source-rules/{id})", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
    });

    await page.goto("/admin/features/curated");
    await openRulesTab(page);
    await page.getByLabel("기본 동작").selectOption("curated");
    await page.getByLabel("우선순위").fill("5");
    await page.getByLabel("장소 종류").selectOption("place");
    await page.getByLabel("카테고리").fill("02020101");
    await page.getByLabel("region_scope").fill('{"sido_code": "11"}');
    await page.getByLabel("metadata").fill('{"note": "seoul only"}');

    await page.getByRole("button", { name: "규칙 저장" }).click();

    await expect.poll(() => requests.rulePatch).toBe(1);
    expect(requests.rulePatchBodies[0]).toMatchObject({
      default_action: "curated",
      priority: 5,
      place_kind: "place",
      category: "02020101",
      region_scope: { sido_code: "11" },
      metadata: { note: "seoul only" },
    });
    await expect(page.getByText("규칙 저장 완료")).toBeVisible();
  });

  test("source rule metadata 배열 입력 → 클라 검증 throw (네트워크 미호출)", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
    });

    await page.goto("/admin/features/curated");
    await openRulesTab(page);

    // metadata에 JSON 배열 → parseJsonObject가 동기 throw → jsonError 표시, PATCH 미호출.
    await page.getByLabel("metadata").fill("[]");
    await page.getByRole("button", { name: "규칙 저장" }).click();

    await expect(
      page.getByRole("alert").filter({ hasText: "소스 규칙 처리 실패" }),
    ).toBeVisible();
    await expect(
      page.getByText("metadata은 JSON object여야 합니다."),
    ).toBeVisible();
    expect(requests.rulePatch).toBe(0);
  });

  test("규칙 적용 — confirm 취소→미호출, 확인→apply + 건수 토스트", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [makeCuratedSourceRule()],
      applyInsertedOrUpdated: 7,
    });

    await page.goto("/admin/features/curated");
    await openRulesTab(page);

    const applyButton = page.getByRole("button", {
      name: "규칙 적용 (후보 생성)",
    });

    // 1) confirm dismiss → apply 미발생. 메시지에 동작·비되살림 규칙 설명.
    let dialogMessage = "";
    page.once("dialog", (dialog) => {
      dialogMessage = dialog.message();
      void dialog.dismiss();
    });
    await applyButton.click();
    await expect.poll(() => dialogMessage).toContain("후보 등록");
    expect(dialogMessage).toContain("거절·보관된 항목은 되살아나지 않습니다");
    await expect.poll(() => requests.ruleApply).toBe(0);

    // 2) confirm accept → apply 1회 + 건수 토스트.
    page.once("dialog", (dialog) => void dialog.accept());
    await applyButton.click();
    await expect.poll(() => requests.ruleApply).toBe(1);
    await expect(page.getByText("규칙 적용 완료")).toBeVisible();
    await expect(
      page.getByText(/7개 후보를 생성\/갱신했습니다/),
    ).toBeVisible();
  });

  test("배포 스냅샷 미리보기 + item 테이블", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      detailItems: [makeDetailItem()],
    });

    await page.goto("/admin/features/curated");

    // 첫 행 자동 선택 → snapshot 쿼리 enabled → detail-snapshot GET 1회.
    await expect(page.getByText("배포 스냅샷 미리보기")).toBeVisible();
    await expect.poll(() => requests.detail).toBeGreaterThanOrEqual(1);

    // etag Badge (shortId(etag, 10)).
    await expect(page.getByText(/^etag /)).toBeVisible();
    // detail item 테이블 헤더 + relation Badge. 'feature' 컬럼은 메인 후보 테이블에도
    // 있으므로 snapshot 테이블(고유 '순서' 헤더 보유)로 스코프해 strict-mode 충돌 회피.
    const snapshotTable = page.getByRole("table").filter({
      has: page.getByRole("columnheader", { name: "순서", exact: true }),
    });
    for (const column of ["순서", "관계", "feature", "메모"]) {
      await expect(
        snapshotTable.getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }
    // 'primary_stop'은 relation select의 <option>으로도 존재하므로
    // snapshot 테이블로 스코프해 strict-mode 충돌을 피한다.
    await expect(snapshotTable.getByText("primary_stop")).toBeVisible();
  });

  test("배포 스냅샷 items 0건 → emptyMessage", async ({ page }) => {
    await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      detailItems: [],
    });

    await page.goto("/admin/features/curated");
    await expect(page.getByText("배포 스냅샷 미리보기")).toBeVisible();
    await expect(page.getByText("detail item이 없습니다.")).toBeVisible();
  });

  test("cursor 페이지네이션 — 다음/처음 버튼 + cursor 재요청", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
      cursorPaging: true,
    });

    await page.goto("/admin/features/curated");

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

    await page.goto("/admin/features/curated");
    await expect.poll(() => requests.featuresList).toBeGreaterThanOrEqual(1);

    await page.getByLabel("page size").selectOption("200");
    await expect.poll(() => requests.lastPageSize).toBe("200");
    // 카운트 라인 갱신.
    await expect(page.getByText(/페이지 크기 200/)).toBeVisible();
  });

  test("빈 상태 — 후보/룰 0건이면 상태별 안내 + 다음 행동 제안", async ({ page }) => {
    const requests = await mockCuratedConsole(page, {
      features: [],
      rules: [],
      sources: [],
      themes: [],
    });

    await page.goto("/admin/features/curated");

    await expect(
      page.getByText(
        "조건에 맞는 후보가 없습니다. 후보는 '소스 규칙' 적용 또는 새로고침 job 실행으로 만들어집니다.",
      ),
    ).toBeVisible();
    // 빈 목록 아래 다음 행동 제안 — 소스 규칙 탭 열기 / 새로고침 job 실행.
    await expect(
      page.getByRole("button", { name: "소스 규칙 탭 열기" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "새로고침 job 실행" }),
    ).toHaveAttribute(
      "href",
      "/admin/dagster?schedule=curated_features_refresh_daily_schedule",
    );
    await expect(
      page.getByText("후보를 선택하면 상세를 확인할 수 있습니다."),
    ).toBeVisible();
    await expect(
      page.getByText("후보를 선택하면 노출 정보를 편집할 수 있습니다."),
    ).toBeVisible();
    await expect(
      page.getByText("후보를 선택하면 배포 스냅샷을 조회합니다."),
    ).toBeVisible();

    // '소스 규칙 탭 열기'가 실제로 탭을 전환한다.
    await page.getByRole("button", { name: "소스 규칙 탭 열기" }).click();
    await expect(
      page.getByText("조건에 맞는 소스 규칙이 없습니다."),
    ).toBeVisible();
    await expect(
      page.getByText("소스 규칙을 선택하면 조건과 기본 동작을 편집할 수 있습니다."),
    ).toBeVisible();

    // selectedFeature null → detail-snapshot 쿼리 disabled → GET 0회.
    await expect.poll(() => requests.featuresList).toBeGreaterThanOrEqual(1);
    expect(requests.detail).toBe(0);
  });

  test("상태별 emptyMessage — curated 0건이면 채택 안내", async ({ page }) => {
    await mockCuratedConsole(page, { features: [] });

    await page.goto("/admin/features/curated");
    await page.getByLabel("curation status filter").selectOption("curated");
    await expect(
      page.getByText(
        "채택된 항목이 없습니다. '후보' 상태에서 채택하면 여기에 표시됩니다.",
      ),
    ).toBeVisible();
  });

  test("features list 500 → role=alert 배너 (조회 실패만 배너, mutation은 토스트)", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await mockCuratedConsole(page, {
      features: [],
      featuresError: true,
    });

    await page.goto("/admin/features/curated");

    await expect(
      page.getByRole("alert").filter({ hasText: "큐레이션 데이터 조회 실패" }),
    ).toBeVisible({ timeout: 45_000 });
  });

  test("원본 feature 열기 링크 href", async ({ page }) => {
    const feature = makeCuratedFeature();
    await mockCuratedConsole(page, { features: [feature] });

    await page.goto("/admin/features/curated");

    const featureLink = page.getByRole("link", { name: "원본 feature 열기" });
    await expect(featureLink).toHaveAttribute(
      "href",
      `/features/${encodeURIComponent(feature.feature_id)}`,
    );
  });

  test("라이프사이클 칩 — 큐레이션됨 클릭 시 필터 동기화 + GET 파라미터", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto("/admin/features/curated");
    const strip = page.getByTestId("curated-lifecycle-strip");
    const chip = strip.getByRole("button", { name: "큐레이션됨", exact: true });
    await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("curation status filter")).toHaveValue(
      "curated",
    );
    await expect.poll(() => requests.lastCurationStatus).toBe("curated");
  });

  test("DETAIL 화면 — 헤더 채택 버튼이 POST /select + 토스트", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [makeCuratedFeature()],
    });

    await page.goto(`/admin/features/curated/${FEATURE_A_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(
      page.getByRole("heading", { name: "큐레이션 상세" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "채택", exact: true }).click();
    await expect.poll(() => requests.select).toBe(1);
    await expect(
      page.getByText("채택 완료 — 후보 → 큐레이션됨"),
    ).toBeVisible();
  });

  test("bulk 전체 선택 → 체크한 N건 채택(POST /select 행 수만큼) + 집계 토스트", async ({
    page,
  }) => {
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

    await page.goto("/admin/features/curated");

    // 행이 렌더된 뒤에 select-all을 눌러야 토글이 반영된다(이른 클릭 레이스 방지).
    await expect(
      page.getByRole("checkbox", { name: "행 선택" }).first(),
    ).toBeVisible();
    const selectAll = page.getByRole("checkbox", { name: "전체 선택" });
    await selectAll.click();
    await expect(page.getByText(/개 선택됨/)).toBeVisible();

    await page.getByRole("button", { name: "체크한 2건 채택" }).click();
    // 선택 행 수(2)만큼 POST /select.
    await expect.poll(() => requests.select).toBe(2);
    await expect(page.getByText("일괄 처리 완료")).toBeVisible();
    await expect(page.getByText("성공 2건 · 실패 0건")).toBeVisible();
  });

  test("bulk 부분 실패 — 성공/실패 집계 + 실패 행만 체크 유지", async ({
    page,
  }) => {
    const requests = await mockCuratedConsole(page, {
      features: [
        makeCuratedFeature(),
        makeCuratedFeature({
          curated_feature_id: FEATURE_B_ID,
          feature_id: "python-visitkorea-api::visitkorea_areas::feat-2",
          feature_name: "창경궁",
        }),
      ],
      selectErrorIds: [FEATURE_B_ID],
    });

    await page.goto("/admin/features/curated");

    await expect(
      page.getByRole("checkbox", { name: "행 선택" }).first(),
    ).toBeVisible();
    const selectAll = page.getByRole("checkbox", { name: "전체 선택" });
    await selectAll.click();
    await expect(page.getByText(/개 선택됨/)).toBeVisible();

    await page.getByRole("button", { name: "체크한 2건 채택" }).click();
    await expect.poll(() => requests.select).toBe(2);
    await expect(page.getByText("일괄 처리 일부 실패")).toBeVisible();
    await expect(page.getByText(/성공 1건 · 실패 1건/)).toBeVisible();
    // 실패한 1건만 체크가 남아 재시도가 쉽다.
    await expect(page.getByText("1개 선택됨")).toBeVisible();
  });

  test("bulk 체크한 N건 보관 — confirm 1회 후 DELETE 행 수만큼", async ({ page }) => {
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

    await page.goto("/admin/features/curated");

    // 행이 렌더된 뒤에 select-all을 눌러야 토글이 반영된다(이른 클릭 레이스 방지).
    await expect(
      page.getByRole("checkbox", { name: "행 선택" }).first(),
    ).toBeVisible();
    const selectAll = page.getByRole("checkbox", { name: "전체 선택" });
    await selectAll.click();
    await expect(page.getByText(/개 선택됨/)).toBeVisible();

    let dialogMessage = "";
    page.once("dialog", (dialog) => {
      dialogMessage = dialog.message();
      void dialog.accept();
    });
    await page.getByRole("button", { name: "체크한 2건 보관" }).click();

    await expect.poll(() => dialogMessage).toContain("체크한 2건을 보관할까요?");
    await expect.poll(() => requests.delete).toBe(2);
  });
});
