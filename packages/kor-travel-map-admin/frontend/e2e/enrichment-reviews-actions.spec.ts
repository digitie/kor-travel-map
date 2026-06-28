import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type EnrichmentReviewRecord = components["schemas"]["EnrichmentReviewRecord"];
type EnrichmentReviewListResponse =
  components["schemas"]["EnrichmentReviewListResponse"];
type EnrichmentReviewDetailResponse =
  components["schemas"]["EnrichmentReviewDetailResponse"];
type EnrichmentReviewDecisionRequest =
  components["schemas"]["EnrichmentReviewDecisionRequest"];
type EnrichmentReviewDecisionResponse =
  components["schemas"]["EnrichmentReviewDecisionResponse"];
type EnrichmentReviewDecisionData =
  components["schemas"]["EnrichmentReviewDecisionData"];
type ReviewFeatureDetailRecord =
  components["schemas"]["ReviewFeatureDetailRecord"];
type ReviewSourceDetailRecord =
  components["schemas"]["ReviewSourceDetailRecord"];
type Meta = components["schemas"]["Meta"];
type PageMeta = components["schemas"]["PageMeta"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const ENRICHMENT_GLOB = "**/v1/admin/enrichment-reviews**";

function apiPathname(url: URL): string {
  return url.pathname.replace(/^\/api\/proxy/, "");
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeReview(
  overrides: Partial<EnrichmentReviewRecord> = {},
): EnrichmentReviewRecord {
  return {
    created_at: MOCK_NOW,
    name_score: 7.2,
    review_id: "enrich-review-0001",
    source_dataset_key: "visitkorea_festivals",
    source_entity_id: "vk-entity-0001",
    source_name: "Source POI",
    source_provider: "python-visitkorea-api",
    source_lat: 37.526,
    source_lon: 126.9245,
    source_start_date: "20260405",
    source_end_date: "20260412",
    spatial_score: 74.2,
    status: "pending",
    target_feature_id: "datagokr::festivals::target-0001",
    target_lat: 37.5261,
    target_lon: 126.9244,
    target_name: "Target POI",
    target_start_date: "2026-04-05",
    target_end_date: "2026-04-12",
    distance_m: 14.2,
    ...overrides,
  };
}

function makeMeta(page?: PageMeta | null): Meta {
  return {
    duration_ms: 1,
    page: page ?? null,
    request_id: "e2e-enrichment-review",
  };
}

function makePageMeta(overrides: Partial<PageMeta> = {}): PageMeta {
  return {
    page_size: 50,
    next_cursor: null,
    total: null,
    ...overrides,
  };
}

function listResponse(
  items: EnrichmentReviewRecord[],
  page?: PageMeta | null,
): EnrichmentReviewListResponse {
  return {
    data: { items },
    meta: makeMeta(page ?? makePageMeta({ total: items.length })),
  };
}

function decisionResponse(
  review: EnrichmentReviewRecord,
  decision: EnrichmentReviewDecisionData["decision"],
): EnrichmentReviewDecisionResponse {
  return {
    data: {
      applied: decision === "accepted",
      changed: true,
      decision,
      review_id: review.review_id,
      source_links_inserted: decision === "accepted" ? 1 : 0,
      source_links_updated: 0,
    },
    meta: makeMeta(),
  };
}

function makeTargetDetail(
  review: EnrichmentReviewRecord,
  detail: Record<string, unknown> = {
    organizer: "datagokr organizer",
    starts_on: "2026-04-05",
  },
): ReviewFeatureDetailRecord {
  return {
    address: { label: "datagokr address" },
    category: review.target_category ?? "A02080100",
    created_at: MOCK_NOW,
    data_origin: "provider",
    data_version: 1,
    detail,
    feature_id: review.target_feature_id,
    kind: review.target_kind ?? "event",
    lat: review.target_lat,
    lon: review.target_lon,
    marker_color: null,
    marker_icon: null,
    name: review.target_name,
    raw_refs: [],
    sources: [],
    status: "active",
    updated_at: MOCK_NOW,
    urls: { homepage: "https://datagokr.example.invalid" },
  };
}

function makeVisitkoreaSource(review: EnrichmentReviewRecord): ReviewSourceDetailRecord {
  return {
    confidence: null,
    dataset_key: review.source_dataset_key,
    expires_at: null,
    fetched_at: MOCK_NOW,
    imported_at: MOCK_NOW,
    is_primary_source: null,
    linked_at: null,
    match_method: null,
    provider: review.source_provider,
    raw_address: "visitkorea address",
    raw_data: {
      eventenddate: review.source_end_date,
      eventstartdate: review.source_start_date,
      mapx: review.source_lon,
      mapy: review.source_lat,
      title: review.source_name,
    },
    raw_latitude: review.source_lat,
    raw_longitude: review.source_lon,
    raw_name: review.source_name,
    raw_payload_hash: `${review.source_entity_id}-hash`,
    source_entity_id: review.source_entity_id,
    source_entity_type: "festival",
    source_record_key: `${review.source_entity_id}-source`,
    source_role: null,
    source_version: null,
  };
}

function detailResponse(
  review: EnrichmentReviewRecord,
  options: { targetDetail?: Record<string, unknown> } = {},
): EnrichmentReviewDetailResponse {
  const targetDetail = options.targetDetail ?? {
    organizer: "datagokr organizer",
    starts_on: "2026-04-05",
  };
  const targetDetailAvailable = Object.keys(targetDetail).length > 0;
  return {
    data: {
      created_at: review.created_at,
      decision_reason: review.decision_reason,
      default_detail_source: targetDetailAvailable ? "target" : "visitkorea",
      distance_m: review.distance_m,
      name_score: review.name_score,
      review_id: review.review_id,
      reviewed_at: review.reviewed_at,
      reviewed_by: review.reviewed_by,
      source: makeVisitkoreaSource(review),
      source_dataset_key: review.source_dataset_key,
      source_end_date: review.source_end_date,
      source_entity_id: review.source_entity_id,
      source_name: review.source_name,
      source_provider: review.source_provider,
      source_start_date: review.source_start_date,
      spatial_score: review.spatial_score,
      status: review.status,
      target: makeTargetDetail(review, targetDetail),
      target_detail_available: targetDetailAvailable,
      target_end_date: review.target_end_date,
      target_feature_id: review.target_feature_id,
      target_name: review.target_name,
      target_start_date: review.target_start_date,
    },
    meta: makeMeta(),
  };
}

/**
 * Stateful list + PATCH decision mock.
 *
 * GET은 `status` 쿼리(반복 파라미터)로 필터한다. status='all'이면 클라이언트가
 * status 파라미터를 아예 보내지 않으므로(enrichment.ts L39) getAll('status')가 비고,
 * 그 경우 저장된 모든 record를 unfiltered로 반환한다. PATCH는 저장된 record의
 * status를 decision에 맞춰 mutate하고, body를 capture한다.
 */
async function mockEnrichmentReviews(
  page: Page,
  options: {
    detailTargetDetails?: Record<string, Record<string, unknown>>;
    initial: EnrichmentReviewRecord[];
  },
) {
  const records = [...options.initial];
  const requests = {
    list: 0,
    patch: 0,
    listStatuses: [] as string[][],
    listUrls: [] as URL[],
    patchBodies: [] as EnrichmentReviewDecisionRequest[],
    patchPathnames: [] as string[],
  };

  await page.route(ENRICHMENT_GLOB, async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === "GET") {
      const path = apiPathname(url);
      if (path.startsWith("/v1/admin/enrichment-reviews/")) {
        const reviewId = decodeURIComponent(
          path.slice("/v1/admin/enrichment-reviews/".length),
        );
        const review =
          records.find((item) => item.review_id === reviewId) ??
          makeReview({ review_id: reviewId });
        await fulfillJson(
          route,
          detailResponse(review, {
            targetDetail: options.detailTargetDetails?.[reviewId],
          }),
        );
        return;
      }
      requests.list += 1;
      const wanted = url.searchParams.getAll("status");
      requests.listStatuses.push(wanted);
      requests.listUrls.push(url);
      const q = url.searchParams.get("q")?.toLowerCase();
      const providers = url.searchParams.getAll("provider");
      const minScore = Number(url.searchParams.get("min_score") ?? Number.NaN);
      const maxScore = Number(url.searchParams.get("max_score") ?? Number.NaN);
      const byStatus =
        wanted.length === 0
          ? records
          : records.filter((item) => wanted.includes(item.status));
      const items = byStatus.filter((item) => {
        const text = [
          item.review_id,
          item.target_feature_id,
          item.target_name,
          item.source_name,
          item.source_entity_id,
        ]
          .join(" ")
          .toLowerCase();
        return (
          (!q || text.includes(q)) &&
          (providers.length === 0 || providers.includes(item.source_provider)) &&
          (Number.isNaN(minScore) || item.name_score >= minScore) &&
          (Number.isNaN(maxScore) || item.name_score <= maxScore)
        );
      });
      await fulfillJson(route, listResponse(items));
      return;
    }

    if (request.method() === "PATCH") {
      requests.patch += 1;
      const path = apiPathname(url);
      requests.patchPathnames.push(path);
      const body = request.postDataJSON() as EnrichmentReviewDecisionRequest;
      requests.patchBodies.push(body);
      const reviewId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const target = records.find((item) => item.review_id === reviewId);
      if (!target) {
        await fulfillJson(route, { detail: "not found" }, 404);
        return;
      }
      target.status = body.decision;
      target.decision_reason = body.decision_reason ?? null;
      target.reviewed_by = body.reviewed_by ?? null;
      await fulfillJson(route, decisionResponse(target, body.decision));
      return;
    }

    throw new Error(`Unhandled enrichment-review route: ${request.method()} ${url}`);
  });

  return requests;
}

/**
 * Page-number 페이지네이션 mock.
 *
 * page=1 GET → page-1, page=2 GET → page-2(소진).
 */
async function mockPageNumberPages(
  page: Page,
  pages: { one: EnrichmentReviewRecord[]; two: EnrichmentReviewRecord[] },
) {
  const listPages: number[] = [];

  await page.route(ENRICHMENT_GLOB, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET") {
      throw new Error(`Unexpected method for page mock: ${request.method()}`);
    }
    const pageIndex = Number(url.searchParams.get("page") ?? "1");
    listPages.push(pageIndex);
    if (pageIndex >= 2) {
      await fulfillJson(
        route,
        listResponse(pages.two, makePageMeta({ next_cursor: null, total: 51 })),
      );
      return;
    }
    await fulfillJson(
      route,
      listResponse(
        pages.one,
        makePageMeta({ next_cursor: "cursor-page-2", total: 51 }),
      ),
    );
  });

  return listPages;
}

/**
 * admin-ops smoke(`/v1/admin/enrichment-reviews`)는 헤더·컬럼·페이저 가시성만 본다.
 * 이 spec은 그 위에 **결정(accept/reject/ignore) mutation·payload·page 전진·
 * compare cell 렌더·empty·error** 동작 depth를 추가한다(중복 smoke 금지).
 */
test.describe("admin/enrichment-reviews actions", () => {
  test("row click opens detail dialog and falls back to visitkorea when target detail is empty", async ({
    page,
  }) => {
    const review = makeReview({
      review_id: "enrich-detail-fallback-1",
      source_name: "Visitkorea Detail Festival",
      target_name: "Datagokr Detail Festival",
    });
    const requests = await mockEnrichmentReviews(page, {
      detailTargetDetails: { [review.review_id]: {} },
      initial: [review],
    });

    await page.goto("/admin/enrichment-reviews");
    const row = page.getByRole("row", { name: /Datagokr Detail Festival/ });
    await expect(row).toBeVisible();

    await row.click();

    const dialog = page.getByRole("dialog", {
      name: "enrichment review detail",
    });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("1차 datagokr")).toBeVisible();
    await expect(dialog.getByText("2차 visitkorea")).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Visitkorea Detail Festival" }),
    ).toBeVisible();
    await expect(page.getByTestId("enrichment-detail-map")).toBeVisible();
    await expect(page.getByLabel("enrichment detail source")).toHaveValue(
      "visitkorea",
    );

    await dialog.getByRole("button", { name: "accept" }).click();

    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      decision: "accepted",
      selected_detail_source: "visitkorea",
    } satisfies Partial<EnrichmentReviewDecisionRequest>);
  });

  test("accept fires PATCH decision and row flips to 완료", async ({ page }) => {
    const review = makeReview({
      review_id: "enrich-accept-1",
      target_name: "Accept Target POI",
      source_name: "Accept Source POI",
      source_entity_id: "vk-entity-accept",
    });
    const requests = await mockEnrichmentReviews(page, { initial: [review] });

    await page.goto("/admin/enrichment-reviews");

    // 결정 후 refetch에서도 행이 유지되도록 status 필터를 'all'로 먼저 바꾼다
    // (기본 'pending' 필터면 accepted record가 목록에서 빠져 '완료'를 못 본다).
    await page.getByLabel("enrichment status").selectOption("all");

    const row = page.getByRole("row", { name: /Accept Target POI/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "accept" }).click();

    await expect.poll(() => requests.patch).toBe(1);
    // decision_reason은 버튼 라벨('accept')이 아니라 EnrichmentDecision 값('accepted').
    expect(requests.patchBodies[0]).toMatchObject({
      decision: "accepted",
      decision_reason: "admin-ui accepted",
      reviewed_by: "local-admin",
    } satisfies EnrichmentReviewDecisionRequest);
    expect(requests.patchPathnames[0]).toBe(
      `/v1/admin/enrichment-reviews/${encodeURIComponent("enrich-accept-1")}`,
    );

    // refetch 후 accepted 행이 유지되고 actions cell이 '완료'로 바뀐다.
    await expect(row.getByText("완료")).toBeVisible();
    await expect(row.getByRole("button", { name: "accept" })).toHaveCount(0);
    await expect(row.getByRole("button", { name: "reject" })).toHaveCount(0);
    await expect(row.getByRole("button", { name: "ignore" })).toHaveCount(0);
  });

  test("reject and ignore send correct decision payloads", async ({ page }) => {
    const rejectReview = makeReview({
      review_id: "enrich-reject-1",
      target_name: "Reject Target POI",
      source_name: "Reject Source POI",
      source_entity_id: "vk-entity-reject",
    });
    const ignoreReview = makeReview({
      review_id: "enrich-ignore-1",
      target_name: "Ignore Target POI",
      source_name: "Ignore Source POI",
      source_entity_id: "vk-entity-ignore",
    });
    const requests = await mockEnrichmentReviews(page, {
      initial: [rejectReview, ignoreReview],
    });

    await page.goto("/admin/enrichment-reviews");
    // 각 mutation 후 refetch에서 두 행이 모두 유지되도록 'all'로 전환.
    await page.getByLabel("enrichment status").selectOption("all");

    const rejectRow = page.getByRole("row", { name: /Reject Target POI/ });
    const ignoreRow = page.getByRole("row", { name: /Ignore Target POI/ });
    await expect(rejectRow).toBeVisible();
    await expect(ignoreRow).toBeVisible();

    await rejectRow.getByRole("button", { name: "reject" }).click();
    await expect.poll(() => requests.patch).toBe(1);
    expect(requests.patchBodies[0]).toMatchObject({
      decision: "rejected",
      decision_reason: "admin-ui rejected",
      reviewed_by: "local-admin",
    } satisfies EnrichmentReviewDecisionRequest);
    // 다음 버튼은 첫 mutation이 settle된 뒤(행이 '완료'로 전환된 뒤) 누른다.
    // 모든 결정 버튼이 decision.isPending 동안 disabled라 transient-disable race를 피한다.
    await expect(rejectRow.getByText("완료")).toBeVisible();

    await ignoreRow.getByRole("button", { name: "ignore" }).click();
    await expect.poll(() => requests.patch).toBe(2);
    expect(requests.patchBodies[1]).toMatchObject({
      decision: "ignored",
      decision_reason: "admin-ui ignored",
      reviewed_by: "local-admin",
    } satisfies EnrichmentReviewDecisionRequest);
    await expect(ignoreRow.getByText("완료")).toBeVisible();

    // 각 PATCH가 자기 review_id를 URL path에 담는다.
    expect(requests.patchPathnames).toContain(
      `/v1/admin/enrichment-reviews/${encodeURIComponent("enrich-reject-1")}`,
    );
    expect(requests.patchPathnames).toContain(
      `/v1/admin/enrichment-reviews/${encodeURIComponent("enrich-ignore-1")}`,
    );
  });

  test("page pagination advances and disables next/last when exhausted", async ({
    page,
  }) => {
    const page1 = makeReview({
      review_id: "enrich-page1-1",
      target_name: "Page1 Review",
      source_name: "Page1 Source",
      source_entity_id: "vk-entity-page1",
    });
    const page2 = makeReview({
      review_id: "enrich-page2-1",
      target_name: "Page2 Review",
      source_name: "Page2 Source",
      source_entity_id: "vk-entity-page2",
    });
    const listPages = await mockPageNumberPages(page, {
      one: [page1],
      two: [page2],
    });

    await page.goto("/admin/enrichment-reviews");

    // 1페이지: 상/하단 페이지바 2벌, 이전 disabled, 다음/마지막 enabled.
    await expect(page.getByLabel("이전 페이지")).toHaveCount(2);
    await expect(page.getByLabel("다음 페이지")).toHaveCount(2);
    await expect(page.getByLabel("마지막 페이지")).toHaveCount(2);
    await expect(
      page.getByText(/페이지 1 \/ 2 · 총 51건 · 현재 1건/),
    ).toHaveCount(2);
    await expect(page.getByRole("row", { name: /Page1 Review/ })).toBeVisible();
    await expect(page.getByLabel("이전 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("다음 페이지").first()).toBeEnabled();
    await expect(page.getByLabel("마지막 페이지").first()).toBeEnabled();

    await page.getByLabel("다음 페이지").first().click();

    // 새 GET이 page=2로 실제 발사됐는지로 페이지 전진을 증명.
    await expect.poll(() => listPages.includes(2)).toBe(true);

    await expect(
      page.getByText(/페이지 2 \/ 2 · 총 51건 · 현재 1건/),
    ).toHaveCount(2);
    await expect(page.getByRole("row", { name: /Page2 Review/ })).toBeVisible();
    await expect(page.getByLabel("다음 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("마지막 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("이전 페이지").first()).toBeEnabled();

    // 뒤로가기는 staleTime(15s) 캐시로 재요청이 없을 수 있어 UI 상태로만 단언한다.
    await page.getByLabel("이전 페이지").first().click();
    await expect(
      page.getByText(/페이지 1 \/ 2 · 총 51건 · 현재 1건/),
    ).toHaveCount(2);
    await expect(page.getByRole("row", { name: /Page1 Review/ })).toBeVisible();
  });

  test("search, provider, score and page-size controls are sent as GET filters", async ({
    page,
  }) => {
    const requests = await mockEnrichmentReviews(page, {
      initial: [
        makeReview({
          review_id: "enrich-filter-1",
          name_score: 92,
          target_name: "Filter Target",
          source_name: "Filter Source",
          source_provider: "python-visitkorea-api",
        }),
        makeReview({
          review_id: "enrich-filter-2",
          name_score: 65,
          target_name: "Other Target",
          source_name: "Other Source",
          source_provider: "python-other-api",
        }),
      ],
    });

    await page.goto("/admin/enrichment-reviews");
    await page.getByLabel("enrichment search").fill("Filter");
    await page.getByLabel("enrichment provider").fill("python-visitkorea-api");
    await page.getByLabel("enrichment score filter").selectOption("high");
    await page.getByLabel("enrichment page size").selectOption("25");

    await expect(page.getByRole("row", { name: /Filter Target/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /Other Target/ })).toHaveCount(0);
    await expect
      .poll(() => requests.listUrls.at(-1)?.searchParams.get("q"))
      .toBe("Filter");
    const last = requests.listUrls.at(-1);
    expect(last?.searchParams.getAll("provider")).toEqual([
      "python-visitkorea-api",
    ]);
    expect(last?.searchParams.get("min_score")).toBe("90");
    expect(last?.searchParams.get("page_size")).toBe("25");
    expect(last?.searchParams.get("page")).toBe("1");
  });

  test("map button opens one VWorld map with datagokr and visitkorea labels", async ({
    page,
  }) => {
    const review = makeReview({
      review_id: "enrich-map-1",
      target_name: "Datagokr Map Festival",
      source_name: "Visitkorea Map Festival",
      target_lon: 126.9244,
      target_lat: 37.5261,
      source_lon: 126.9245,
      source_lat: 37.526,
      distance_m: 14.2,
    });
    await mockEnrichmentReviews(page, { initial: [review] });

    await page.goto("/admin/enrichment-reviews");
    const row = page.getByRole("row", { name: /Datagokr Map Festival/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "지도" }).click();

    const map = page.getByLabel("enrichment coordinate map");
    await expect(map).toBeVisible();
    await expect(map.getByText("Datagokr Map Festival")).toBeVisible();
    await expect(map.getByText("Visitkorea Map Festival")).toBeVisible();
    await expect(map.getByText(/14\.2m/)).toBeVisible();
    await expect(page.getByTestId("enrichment-review-map")).toBeVisible();
  });

  test("compare cells render 1차 datagokr target vs 2차 visitkorea source", async ({
    page,
  }) => {
    const review = makeReview({
      review_id: "enrich-compare-1",
      name_score: 8.5,
      target_name: "Datagokr Festival",
      target_category: "A02080100",
      target_feature_id: "datagokr::festivals::compare-target",
      source_name: "Visitkorea Festival",
      source_provider: "python-visitkorea-api",
      source_entity_id: "vk-entity-12345",
    });
    await mockEnrichmentReviews(page, { initial: [review] });

    await page.goto("/admin/enrichment-reviews");

    const row = page.getByRole("row", { name: /Datagokr Festival/ });
    await expect(row).toBeVisible();

    // 1차 컬럼: target_name + target_category.
    await expect(row.getByText("Datagokr Festival")).toBeVisible();
    await expect(row.getByText(/A02080100/)).toBeVisible();
    // 2차 컬럼: source_name + source_provider · source_entity_id.
    await expect(row.getByText("Visitkorea Festival")).toBeVisible();
    await expect(row.getByText(/python-visitkorea-api/)).toBeVisible();
    await expect(row.getByText(/vk-entity-12345/)).toBeVisible();
    // name_score: toFixed(1).
    await expect(row.getByText("name 8.5")).toBeVisible();
    await expect(row.getByText("distance 74.2")).toBeVisible();
    await expect(row.getByText("2026-04-05 ~ 2026-04-12").first()).toBeVisible();
  });

  test("empty list shows placeholder and disables both pager buttons", async ({
    page,
  }) => {
    await page.route(ENRICHMENT_GLOB, async (route) => {
      if (route.request().method() !== "GET") {
        throw new Error("empty mock only serves GET");
      }
      await fulfillJson(
        route,
        listResponse([], makePageMeta({ next_cursor: null, total: 0 })),
      );
    });

    await page.goto("/admin/enrichment-reviews");

    await expect(page.getByText("enrichment review가 없습니다.")).toBeVisible();
    await expect(page.getByLabel("이전 페이지")).toHaveCount(2);
    await expect(page.getByLabel("다음 페이지")).toHaveCount(2);
    await expect(page.getByLabel("마지막 페이지")).toHaveCount(2);
    await expect(page.getByLabel("이전 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("다음 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("마지막 페이지").first()).toBeDisabled();
    await expect(
      page.getByText(/페이지 1 \/ 1 · 총 0건 · 현재 0건/),
    ).toHaveCount(2);
  });

  test("list error surfaces destructive alert", async ({ page }) => {
    await page.route(ENRICHMENT_GLOB, async (route) => {
      // 500 본문은 components 스키마가 아닌 RFC7807 problem+json — 일부러 literal로 둔다.
      await fulfillJson(route, { detail: "boom" }, 500);
    });

    await page.goto("/admin/enrichment-reviews");

    // destructive Alert만 role=alert (alert.tsx L32); 성공 Alert는 role=status.
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(page.getByText("enrichment review 처리 실패")).toBeVisible();
    // 메시지에는 client.ts가 HTTP status/path를 붙이므로 정확 텍스트 대신 존재만 단언.
  });
});
