import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { mockOpsDatasetCatalog } from "./ops-dataset-catalog-mock";

// admin-ops.spec.ts house pattern: 손으로 쓴 record shape 대신 생성된 OpenAPI
// 스키마(components["schemas"])에 mock factory를 바인딩한다(#308). 백엔드 DTO가
// 바뀌면 factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift를 tsc가 잡는다.
//
// 이 파일은 /admin/features 목록 페이지의 "깊이" 검증(검색 deferred 반영, 서버
// 정렬 미러링, cursor 페이지네이션, empty/error, deactivate kill-switch, deeplink,
// has_issue 필터)을 담당한다. admin-ops.spec.ts의 `/v1/admin/features` smoke는
// 헤더/필터 표면만 보므로 중복하지 않는다.

type Meta = components["schemas"]["Meta"];
type PageMeta = components["schemas"]["PageMeta"];
type AdminFeatureRecord = components["schemas"]["AdminFeatureRecord"];
type AdminFeatureIssueRecord =
  components["schemas"]["AdminFeatureIssueRecord"];
type AdminFeaturesListResponse =
  components["schemas"]["AdminFeaturesListResponse"];
type AdminFeatureDeactivateData =
  components["schemas"]["AdminFeatureDeactivateData"];
type AdminFeatureDeactivateResponse =
  components["schemas"]["AdminFeatureDeactivateResponse"];
type AdminFeatureDetailData = components["schemas"]["AdminFeatureDetailData"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type AdminFeatureDetailSourceRecord =
  components["schemas"]["AdminFeatureDetailSourceRecord"];
type CurationItemView = components["schemas"]["AdminCurationItemView"];

const MOCK_NOW = "2026-06-16T00:00:00.000Z";
const LIST_PATH = "/v1/admin/features";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function apiPath(url: URL): string {
  return url.pathname.startsWith("/api/proxy/")
    ? url.pathname.slice("/api/proxy".length)
    : url.pathname;
}

function makeMeta(page: PageMeta, overrides: Partial<Meta> = {}): Meta {
  return {
    duration_ms: 1,
    page,
    request_id: "e2e-admin-features-list",
    ...overrides,
  };
}

function makePageMeta(overrides: Partial<PageMeta> = {}): PageMeta {
  return {
    next_cursor: null,
    page_size: 50,
    total: null,
    ...overrides,
  };
}

function makeAdminIssue(
  overrides: Partial<AdminFeatureIssueRecord> = {},
): AdminFeatureIssueRecord {
  return {
    detected_at: MOCK_NOW,
    issue_id: "issue-1",
    message: "주소 누락",
    severity: "warning",
    violation_type: "missing_address",
    ...overrides,
  };
}

function makeAdminFeature(
  overrides: Partial<AdminFeatureRecord> = {},
): AdminFeatureRecord {
  return {
    address_label: "서울 마포구 와우산로",
    category: "01070300",
    created_at: MOCK_NOW,
    feature_id: "mock-provider::mock-dataset::active-1",
    issue_count: 0,
    issues: [],
    kind: "place",
    lat: 37.5665,
    lon: 126.978,
    name: "Mock active feature",
    primary_dataset_key: "mock_dataset",
    primary_provider: "python-kma-api",
    status: "active",
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

function listResponse(
  items: AdminFeatureRecord[],
  page: PageMeta = makePageMeta(),
): AdminFeaturesListResponse {
  return { data: { items }, meta: makeMeta(page) };
}

function makeDeactivateResponse(
  feature: AdminFeatureRecord,
): AdminFeatureDeactivateResponse {
  const data: AdminFeatureDeactivateData = {
    feature_id: feature.feature_id,
    override: null,
    override_created: true,
    previous_status: feature.status,
    status: "inactive",
  };
  return {
    data,
    meta: { duration_ms: 1, page: null, request_id: "e2e-deactivate" },
  };
}

function makeAdminSource(
  overrides: Partial<AdminFeatureDetailSourceRecord> = {},
): AdminFeatureDetailSourceRecord {
  return {
    confidence: 1,
    dataset_key: "admin-dataset",
    expires_at: null,
    fetched_at: MOCK_NOW,
    imported_at: MOCK_NOW,
    is_primary_source: true,
    last_seen_at: MOCK_NOW,
    linked_at: MOCK_NOW,
    match_method: "natural_key",
    provider: "admin-provider",
    raw_address: "서울 마포구 와우산로",
    raw_data: { admin_source_marker: "admin-source-visible" },
    raw_latitude: 37.5665,
    raw_longitude: 126.978,
    raw_name: "Admin source place",
    raw_payload_hash: "admin-source-hash",
    source_entity_id: "admin-entity-1",
    source_entity_key: "admin-provider::admin-dataset::admin-entity-1",
    source_entity_type: "place",
    source_record_key: "admin-provider::admin-dataset::admin-record-1",
    source_role: "primary",
    source_version: "v1",
    ...overrides,
  };
}

function makeCuration(
  feature: AdminFeatureRecord,
  overrides: Partial<CurationItemView> = {},
): CurationItemView {
  return {
    address: { road: feature.address_label },
    address_hint: "서울 마포구",
    archived_at: null,
    collection_id: "admin-collection-id",
    collection_key: "admin-only-collection",
    created_at: MOCK_NOW,
    created_by: "e2e-admin",
    curation_item_id: "admin-curation-item",
    curation_relation: "primary_stop",
    dataset_key: "admin-dataset",
    edition_key: "2026",
    external_item_id: "admin-official-item",
    feature_category: feature.category,
    feature_id: feature.feature_id,
    feature_kind: feature.kind,
    feature_name: feature.name,
    item_summary: "admin-only membership summary",
    item_title: "Admin only membership",
    lat: feature.lat ?? null,
    lon: feature.lon ?? null,
    metadata: { visibility: "admin_only" },
    place_name: feature.name,
    provider: "admin-provider",
    reuse_policy: "manual_review",
    sort_order: 7,
    source_name: "Admin source",
    source_record_key: "admin-provider::admin-dataset::admin-record-1",
    source_url: "https://example.test/admin-source",
    status: "candidate",
    theme_group: "admin group",
    theme_name: "Admin theme",
    theme_slug: "admin-theme",
    title: "Admin-only collection",
    updated_at: MOCK_NOW,
    updated_by: "e2e-admin",
    ...overrides,
  };
}

function makeAdminFeatureDetailResponse(
  feature: AdminFeatureRecord,
  overrides: Partial<AdminFeatureDetailData> = {},
): AdminFeatureDetailResponse {
  return {
    data: {
      change_requests: [],
      curations: [makeCuration(feature)],
      feature: {
        address: { road: feature.address_label },
        category: feature.category,
        created_at: feature.created_at,
        data_origin: "provider",
        data_version: 1,
        detail: {},
        feature_id: feature.feature_id,
        kind: feature.kind,
        lat: feature.lat ?? null,
        lon: feature.lon ?? null,
        name: feature.name,
        raw_refs: [],
        row_revision: 1,
        status: feature.status,
        updated_at: feature.updated_at,
        urls: {},
      },
      files: [],
      issues: [],
      overrides: [],
      sources: [makeAdminSource()],
      versions: [],
      ...overrides,
    },
    meta: { duration_ms: 1, page: null, request_id: "e2e-admin-feature-detail" },
  };
}

/**
 * `**\/v1/admin/features**`를 단일 route로 잡되 분기는 most-specific-first.
 * 이 페이지는 GET list + POST .../deactivate만 발생시키지만 glob은 change-request
 * 등도 매칭하므로 정확한 pathname으로 가드한다(admin-ops.spec.ts risk note).
 *
 * 모든 GET list URL의 searchParams를 기록한다(deferred q / sort / cursor 검증용).
 */
async function mockFeaturesList(
  page: Page,
  options: {
    handler: (url: URL) => AdminFeaturesListResponse;
    detail?: AdminFeatureDetailResponse;
  },
) {
  await mockOpsDatasetCatalog(page);
  const listSearches: URLSearchParams[] = [];
  const deactivateBodies: Record<string, unknown>[] = [];
  const deactivateUrls: string[] = [];

  await page.route("**/v1/admin/features**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = apiPath(url);

    // most-specific: deactivate kill-switch.
    if (request.method() === "POST" && pathname.endsWith("/deactivate")) {
      deactivateUrls.push(pathname);
      deactivateBodies.push(request.postDataJSON() as Record<string, unknown>);
      const featureId = decodeURIComponent(
        pathname.replace(/^\/v1\/admin\/features\//, "").replace(
          /\/deactivate$/,
          "",
        ),
      );
      await fulfillJson(route, makeDeactivateResponse(makeAdminFeature({
        feature_id: featureId,
      })));
      return;
    }

    // GET list (정확한 pathname). change-requests 등은 매칭하지 않음.
    if (request.method() === "GET" && pathname === LIST_PATH) {
      listSearches.push(url.searchParams);
      await fulfillJson(route, options.handler(url));
      return;
    }

    if (
      request.method() === "GET" &&
      pathname.startsWith(`${LIST_PATH}/`) &&
      options.detail
    ) {
      await fulfillJson(route, options.detail);
      return;
    }

    throw new Error(
      `Unhandled admin features route: ${request.method()} ${pathname}`,
    );
  });

  const lastSearch = () => listSearches.at(-1);
  return { listSearches, lastSearch, deactivateBodies, deactivateUrls };
}

test.describe("admin/features list depth", () => {
  test("q search reflected in list query param + cursor reset", async ({
    page,
  }) => {
    const seeded = makeAdminFeature({ name: "Hongdae mock feature" });
    const mocks = await mockFeaturesList(page, {
      handler: () => listResponse([seeded]),
    });

    await page.goto("/admin/features");
    await expect(page.getByText("Hongdae mock feature")).toBeVisible();

    // 초기(active) 목록이 정착하면 q 파라미터는 없어야 한다(빈 q => undefined).
    await expect
      .poll(() => mocks.lastSearch()?.has("q") ?? true)
      .toBe(false);

    await page.getByLabel("feature search").fill("hongdae");

    // useDeferredValue로 q가 한 틱 늦게 쿼리에 도달하므로 expect.poll로 대기.
    await expect
      .poll(() => mocks.lastSearch()?.get("q"))
      .toBe("hongdae");

    const last = mocks.lastSearch();
    expect(last?.has("cursor")).toBe(false); // resetCursor()로 cursor 제거.
    expect(last?.get("sort")).toBe("name"); // 기본 정렬 유지.
    expect(last?.get("order")).toBe("asc");
  });

  test("sort/order controls drive server sort + order query params", async ({
    page,
  }) => {
    const mocks = await mockFeaturesList(page, {
      handler: () => listResponse([makeAdminFeature()]),
    });

    await page.goto("/admin/features");
    await expect(page.getByText("Mock active feature")).toBeVisible();

    // 정렬 표면은 NativeSelect("feature sort") + asc/desc Button이다. table 컬럼은
    // 전부 display 컬럼(accessorKey 없음)이라 manualSorting 하에서 getCanSort()가
    // false → 헤더에 sort 버튼/aria-sort가 렌더되지 않는다(react-table v8). 따라서
    // 정렬 동기화는 dropdown + order 버튼 ↔ list query param으로만 검증한다.
    const sortSelect = page.getByLabel("feature sort");
    const ascButton = page.getByRole("button", { name: "asc" });
    const descButton = page.getByRole("button", { name: "desc" });

    // 기본 상태: sort=name, order=asc. asc 버튼이 default variant(bg-brand).
    await expect(sortSelect).toHaveValue("name");
    await expect(ascButton).toHaveClass(/bg-brand/);
    await expect
      .poll(() => mocks.lastSearch()?.get("sort"))
      .toBe("name");
    expect(mocks.lastSearch()?.get("order")).toBe("asc");

    // dropdown으로 updated_at 선택 → setSort("updated_at") + resetCursor().
    // order(asc) 상태는 보존된다.
    await sortSelect.selectOption("updated_at");
    await expect(sortSelect).toHaveValue("updated_at");
    await expect
      .poll(() => mocks.lastSearch()?.get("sort"))
      .toBe("updated_at");
    expect(mocks.lastSearch()?.get("order")).toBe("asc");
    expect(mocks.lastSearch()?.has("cursor")).toBe(false); // resetCursor().

    // desc 버튼 클릭 → setOrder("desc") + resetCursor(). sort(updated_at) 보존.
    await descButton.click();
    await expect(descButton).toHaveClass(/bg-brand/);
    await expect
      .poll(() => mocks.lastSearch()?.get("order"))
      .toBe("desc");
    expect(mocks.lastSearch()?.get("sort")).toBe("updated_at");

    // dropdown으로 provider 선택 → order 상태(desc) 보존 + sort=provider.
    await sortSelect.selectOption("provider");
    await expect(sortSelect).toHaveValue("provider");
    await expect
      .poll(() => mocks.lastSearch()?.get("sort"))
      .toBe("provider");
    expect(mocks.lastSearch()?.get("order")).toBe("desc");
  });

  test("cursor pagination advances on 다음 and exhausts when next_cursor=null", async ({
    page,
  }) => {
    await mockFeaturesList(page, {
      handler: (url) => {
        const cursor = url.searchParams.get("cursor");
        if (cursor === "cursor-page-2") {
          return listResponse(
            [makeAdminFeature({
              feature_id: "mock::page::2",
              name: "Feature page 2",
            })],
            makePageMeta({ next_cursor: null }),
          );
        }
        return listResponse(
          [makeAdminFeature({
            feature_id: "mock::page::1",
            name: "Feature page 1",
          })],
          makePageMeta({ next_cursor: "cursor-page-2" }),
        );
      },
    });

    await page.goto("/admin/features");
    await expect(page.getByText("Feature page 1")).toBeVisible();

    const next = page.getByRole("button", { name: "다음" });
    const first = page.getByRole("button", { name: "첫 페이지" });
    await expect(next).toBeEnabled(); // next_cursor 존재.
    await expect(first).toBeDisabled(); // cursor === null.

    await next.click();
    await expect(page.getByText("Feature page 2")).toBeVisible();
    await expect(page.getByText("Feature page 1")).toHaveCount(0);

    // 마지막 페이지: next 비활성, 첫 페이지 활성.
    await expect(next).toBeDisabled();
    await expect(first).toBeEnabled();

    // 첫 페이지 복귀 — cursor 없는 byte-identical 쿼리는 react-query staleTime
    // 캐시를 탈 수 있으므로 request count가 아닌 UI 상태로 검증한다(Wave-1 gotcha).
    await first.click();
    await expect(page.getByText("Feature page 1")).toBeVisible();
    await expect(first).toBeDisabled();
  });

  test("empty state shows feature가 없습니다.", async ({ page }) => {
    await mockFeaturesList(page, {
      handler: () => listResponse([], makePageMeta({ next_cursor: null })),
    });

    await page.goto("/admin/features");

    await expect(page.getByText("feature가 없습니다.")).toBeVisible();
    await expect(page.getByText("0 rows")).toBeVisible();
    await expect(page.getByText("table에서 feature를 선택하면")).toBeVisible();
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "첫 페이지" })).toBeDisabled();
  });

  test("list error renders destructive alert (problem+json)", async ({
    page,
  }) => {
    // 에러 본문은 RFC7807 problem+json — 생성 스키마에 이름이 없으므로 literal로
    // 둔다. 성공 본문만 schema 바인딩(admin-ops.spec.ts risk note).
    await page.route("**/v1/admin/features**", async (route) => {
      const url = new URL(route.request().url());
      const pathname = apiPath(url);
      if (
        route.request().method() === "GET" &&
        pathname === LIST_PATH
      ) {
        await fulfillJson(
          route,
          {
            detail: "boom",
            status: 500,
            title: "Internal Server Error",
            type: "about:blank",
          },
          500,
        );
        return;
      }
      throw new Error(`Unexpected route in error test: ${pathname}`);
    });

    await page.goto("/admin/features");

    // variant="destructive" Alert => role=alert (Wave-1 gotcha).
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(page.getByText("admin feature 처리 실패")).toBeVisible();
    // 클라이언트가 빌드한 실패 메시지(HTTP 500 prefix)가 AlertDescription에 노출.
    await expect(alert.getByText(/HTTP 500/)).toBeVisible();
  });

  test("deactivate kill-switch fires mutation with correct body", async ({
    page,
  }) => {
    const activeFeature = makeAdminFeature({
      feature_id: "mock::active::deactivate-1",
      name: "Mock active feature",
      status: "active",
    });
    const inactiveFeature = makeAdminFeature({
      feature_id: "mock::inactive::guard-1",
      name: "Mock inactive feature",
      status: "inactive",
    });
    const mocks = await mockFeaturesList(page, {
      handler: () => listResponse([activeFeature, inactiveFeature]),
    });

    await page.goto("/admin/features");

    const activeRow = page.getByRole("row", { name: /Mock active feature/ });
    await expect(activeRow).toBeVisible();

    // 음성 가드: inactive row의 deactivate 버튼은 비활성.
    const inactiveRow = page.getByRole("row", { name: /Mock inactive feature/ });
    await expect(
      inactiveRow.getByRole("button", { name: "deactivate" }),
    ).toBeDisabled();

    await activeRow.getByRole("button", { name: "deactivate" }).click();
    // deactivate는 이제 AlertDialog 확인 — 다이얼로그의 '비활성화' 버튼 클릭.
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "비활성화" })
      .click();

    await expect.poll(() => mocks.deactivateBodies.length).toBe(1);
    expect(mocks.deactivateBodies[0]).toMatchObject({
      operator: "local-admin",
      prevent_provider_reactivation: true,
      reason: "admin-ui deactivate",
    });
    expect(mocks.deactivateUrls[0]).toBe(
      `/v1/admin/features/${encodeURIComponent(activeFeature.feature_id)}/deactivate`,
    );
  });

  test("row deeplink href points to /features/[id]", async ({ page }) => {
    const featureId = "user_request::e2e::deeplink id";
    const feature = makeAdminFeature({
      feature_id: featureId,
      name: "Mock active feature",
    });
    await mockFeaturesList(page, {
      handler: () => listResponse([feature]),
      detail: makeAdminFeatureDetailResponse(feature),
    });

    await page.goto("/admin/features");

    const row = page.getByRole("row", { name: /Mock active feature/ });
    await expect(row).toBeVisible();

    const expectedHref = `/features/${encodeURIComponent(featureId)}`;
    await expect(row.getByRole("link", { name: "detail" })).toHaveAttribute(
      "href",
      expectedHref,
    );

    // row 본문 클릭으로 선택 → 우측 preview가 렌더되되 전체 상세 링크는 노출하지 않는다.
    await row.click();
    const associations = page.getByTestId("feature-associations");
    await expect(associations).toBeVisible();
    await expect(associations.getByText("Admin-only collection")).toBeVisible();
    await expect(associations.getByText("admin-provider").first()).toBeVisible();
    await associations.getByText("membership 전체 정보").click();
    await expect(associations.getByText("admin-only-collection")).toBeVisible();
    await expect(page.getByRole("link", { name: "전체 상세" })).toHaveCount(0);
  });

  test("has_issue filter forwarded as boolean query param", async ({
    page,
  }) => {
    const issueFeature = makeAdminFeature({
      feature_id: "mock::issue::1",
      issue_count: 2,
      issues: [
        makeAdminIssue({ issue_id: "issue-a", message: "주소 누락" }),
        makeAdminIssue({
          issue_id: "issue-b",
          message: "좌표 없음",
          violation_type: "missing_coord",
        }),
      ],
      name: "Issue feature",
    });
    const mocks = await mockFeaturesList(page, {
      handler: (url) =>
        url.searchParams.get("has_issue") === "true"
          ? listResponse([issueFeature])
          : listResponse([makeAdminFeature()]),
    });

    await page.goto("/admin/features");
    await expect(page.getByText("Mock active feature")).toBeVisible();

    // 기본 hasIssue="all" => has_issue 파라미터 없음.
    await expect
      .poll(() => mocks.lastSearch()?.has("has_issue") ?? true)
      .toBe(false);

    const hasIssueSelect = page.getByLabel("has issue");
    await hasIssueSelect.selectOption("yes"); // "yes" => has_issue=true.

    // hasIssue 변경은 setHasIssue + resetCursor()를 호출한다. 마지막 list 쿼리가
    // has_issue=true이면서 cursor가 없어야 한다 — 둘을 같은 search 스냅샷에서
    // 함께 poll해 request 진행 중 race를 피한다(passing q-search 테스트 패턴).
    await expect
      .poll(() => {
        const search = mocks.lastSearch();
        return search?.get("has_issue") === "true" && !search.has("cursor");
      })
      .toBe(true);

    // has_issue=yes 분기가 end-to-end로 연결됐는지 — issue count + violation 라인.
    const issueRow = page.getByRole("row", { name: /Issue feature/ });
    await expect(issueRow.getByText("2", { exact: true })).toBeVisible();
    await expect(issueRow.getByText(/missing_address · 주소 누락/)).toBeVisible();

    await hasIssueSelect.selectOption("no"); // "no" => has_issue=false.
    await expect
      .poll(() => mocks.lastSearch()?.get("has_issue"))
      .toBe("false");

    await hasIssueSelect.selectOption("all");
    // "all"은 초기 쿼리 키와 동일 → staleTime 캐시 적중으로 새 GET이 없을 수 있어
    // 파라미터 부재는 위 초기 로드 단언으로 이미 검증됨. 여기선 필터 복귀로 비-이슈
    // feature가 다시 보이는지(라운드트립 완료)만 확인한다.
    await expect(page.getByText("Mock active feature")).toBeVisible();
  });
});
