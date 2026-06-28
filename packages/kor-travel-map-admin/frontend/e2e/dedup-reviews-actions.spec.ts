import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(#308 리뷰).
// 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약 drift 감지.
type DedupFeatureRecord = components["schemas"]["DedupFeatureRecord"];
type DedupReviewRecord = components["schemas"]["DedupReviewRecord"];
type DedupReviewListResponse =
  components["schemas"]["DedupReviewListResponse"];
type DedupReviewDetailResponse =
  components["schemas"]["DedupReviewDetailResponse"];
type DedupReviewDecisionRequest =
  components["schemas"]["DedupReviewDecisionRequest"];
type DedupReviewDecisionResponse =
  components["schemas"]["DedupReviewDecisionResponse"];
type DedupReviewDecisionData =
  components["schemas"]["DedupReviewDecisionData"];
type ReviewFeatureDetailRecord =
  components["schemas"]["ReviewFeatureDetailRecord"];
type ReviewSourceDetailRecord =
  components["schemas"]["ReviewSourceDetailRecord"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";

// 행 accessible name(셀 텍스트 concat)에서 strict-mode 충돌을 피하려고 구분되는 이름을 쓴다.
const REVIEW_ID_1 = "dedup-review-0001-aaaa-bbbb-cccc-000000000001";
const REVIEW_ID_2 = "dedup-review-0002-aaaa-bbbb-cccc-000000000002";
const FEATURE_A_ID = "python-mois-api::mois_license::DEDUP_A_alpha";
const FEATURE_B_ID = "python-visitkorea-api::vk_place::DEDUP_B_beta";

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

function makeDedupFeature(
  overrides: Partial<DedupFeatureRecord> = {},
): DedupFeatureRecord {
  return {
    category: "02020101",
    dataset_key: "mois_license",
    feature_id: FEATURE_A_ID,
    kind: "place",
    lat: null,
    lon: null,
    name: "DEDUP_A_alpha",
    provider: "python-mois-api",
    ...overrides,
  };
}

function makeDedupReview(
  overrides: Partial<DedupReviewRecord> = {},
): DedupReviewRecord {
  return {
    category_score: 1,
    created_at: MOCK_NOW,
    decision_reason: null,
    distance_m: 12.5,
    feature_a: makeDedupFeature(),
    // feature_b에 좌표를 줘서 master 버튼 라벨이 'B: {name} · 좌표✓'가 되게 한다.
    feature_b: makeDedupFeature({
      category: "02020101",
      dataset_key: "vk_place",
      feature_id: FEATURE_B_ID,
      lat: 37.5665,
      lon: 126.978,
      name: "DEDUP_B_beta",
      provider: "python-visitkorea-api",
    }),
    name_score: 0.92,
    review_id: REVIEW_ID_1,
    reviewed_at: null,
    reviewed_by: null,
    spatial_score: 0.88,
    status: "pending",
    total_score: 2.8,
    ...overrides,
  };
}

function listResponse(
  items: DedupReviewRecord[],
  options: { nextCursor?: string | null; pageSize?: number; total?: number } = {},
): DedupReviewListResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: {
        page_size: options.pageSize ?? 100,
        next_cursor: options.nextCursor ?? null,
        total: options.total ?? items.length,
      },
      request_id: "e2e-dedup-list",
    },
  };
}

function decisionResponse(
  review: DedupReviewRecord,
  body: DedupReviewDecisionRequest,
): DedupReviewDecisionResponse {
  const data: DedupReviewDecisionData = {
    changed: true,
    decision: body.decision,
    loser_feature_id:
      body.decision === "merged"
        ? body.master_feature_id === review.feature_b.feature_id
          ? review.feature_a.feature_id
          : review.feature_b.feature_id
        : null,
    master_feature_id:
      body.decision === "merged"
        ? (body.master_feature_id ?? review.feature_a.feature_id)
        : null,
    merge_id: body.decision === "merged" ? "merge-0001" : null,
    review_id: review.review_id,
    source_links_dropped: 0,
    source_links_moved: body.decision === "merged" ? 1 : null,
  };
  return {
    data,
    meta: { duration_ms: 1, request_id: "e2e-dedup-decision" },
  };
}

function makeReviewSource(
  feature: DedupFeatureRecord,
): ReviewSourceDetailRecord {
  return {
    confidence: 100,
    dataset_key: feature.dataset_key ?? "dataset",
    expires_at: null,
    fetched_at: MOCK_NOW,
    imported_at: MOCK_NOW,
    is_primary_source: true,
    linked_at: MOCK_NOW,
    match_method: "natural_key",
    provider: feature.provider ?? "provider",
    raw_address: `${feature.name} address`,
    raw_data: {
      address: `${feature.name} address`,
      name: feature.name,
      phone: "02-0000-0000",
    },
    raw_latitude: feature.lat,
    raw_longitude: feature.lon,
    raw_name: feature.name,
    raw_payload_hash: `${feature.feature_id}-hash`,
    source_entity_id: `${feature.feature_id}-entity`,
    source_entity_type: feature.kind,
    source_record_key: `${feature.feature_id}-source`,
    source_role: "primary",
    source_version: null,
  };
}

function makeReviewFeatureDetail(
  feature: DedupFeatureRecord,
): ReviewFeatureDetailRecord {
  return {
    address: { label: `${feature.name} address` },
    category: feature.category,
    created_at: MOCK_NOW,
    data_origin: "provider",
    data_version: 1,
    detail: {
      memo: `${feature.name} detail`,
      phone: "02-0000-0000",
    },
    feature_id: feature.feature_id,
    kind: feature.kind,
    lat: feature.lat,
    lon: feature.lon,
    marker_color: null,
    marker_icon: null,
    name: feature.name,
    raw_refs: [],
    sources: [makeReviewSource(feature)],
    status: "active",
    updated_at: MOCK_NOW,
    urls: { homepage: "https://example.invalid" },
  };
}

function detailResponse(review: DedupReviewRecord): DedupReviewDetailResponse {
  return {
    data: {
      category_score: review.category_score,
      created_at: review.created_at,
      decision_reason: review.decision_reason,
      distance_m: review.distance_m,
      feature_a: makeReviewFeatureDetail(review.feature_a),
      feature_b: makeReviewFeatureDetail(review.feature_b),
      name_score: review.name_score,
      review_id: review.review_id,
      reviewed_at: review.reviewed_at,
      reviewed_by: review.reviewed_by,
      spatial_score: review.spatial_score,
      status: review.status,
      total_score: review.total_score,
    },
    meta: { duration_ms: 1, request_id: "e2e-dedup-detail" },
  };
}

// PATCH decision → review.status로 매핑 (refetch가 '완료' 상태를 반영하도록).
const DECISION_TO_STATUS: Record<DedupReviewDecisionRequest["decision"], string> =
  {
    accepted: "accepted",
    rejected: "rejected",
    merged: "merged",
    ignored: "ignored",
  };

interface DedupMockHandle {
  requests: {
    list: number;
    patch: number;
    bodies: DedupReviewDecisionRequest[];
    paths: string[];
    lastListUrl: URL | null;
    listUrls: URL[];
  };
  /** mutex 시나리오용 — PATCH 라우트를 직접 열어둘 때 호출해 보류 중인 응답을 풀어준다. */
  releasePatch: () => void;
}

/**
 * 상태있는(stateful) dedup 목록/결정 mock. PATCH가 in-memory record의 status를
 * 바꾸므로 invalidateQueries(['dedup-reviews']) 후 refetch가 '완료' 상태를 반영한다
 * (admin-ops storeChange 패턴). `/v1/admin/dedup-reviews`만 가로채 Next.js 문서/RSC
 * 네비게이션('/admin/dedup-reviews')은 건드리지 않는다.
 */
async function mockDedupReviews(
  page: Page,
  options: {
    /** status별 행 집합. status absent/'pending' 기본 행을 'pending' 키로 둔다. */
    byStatus?: Record<string, DedupReviewRecord[]>;
    /** PATCH 응답을 수동 해제할 때까지 보류(mutex 시나리오). */
    holdPatch?: boolean;
  } = {},
): Promise<DedupMockHandle> {
  const handle: DedupMockHandle = {
    requests: {
      list: 0,
      patch: 0,
      bodies: [],
      paths: [],
      lastListUrl: null,
      listUrls: [],
    },
    releasePatch: () => {},
  };

  // review_id → 현재 status (PATCH로 변형). 기본 pending 행들을 시드한다.
  const pending = options.byStatus?.pending ?? [makeDedupReview()];
  const statusById = new Map<string, string>();
  for (const review of pending) statusById.set(review.review_id, review.status);

  function rowsForStatus(status: string | null): DedupReviewRecord[] {
    // 'all'(=status param 없음) 또는 'pending'이면 기본 pending 행 집합을 status로 덧씌워 반환.
    if (options.byStatus && status && options.byStatus[status]) {
      return options.byStatus[status];
    }
    const base = pending.map((review) => ({
      ...review,
      status: statusById.get(review.review_id) ?? review.status,
    }));
    if (!status) return base; // 'all' 센티넬: status param 없음
    return base.filter((review) => review.status === status);
  }

  function filteredRows(url: URL): DedupReviewRecord[] {
    const statuses = url.searchParams.getAll("status");
    const status = statuses.length > 0 ? statuses[0] : null;
    const q = url.searchParams.get("q")?.toLowerCase();
    const providers = url.searchParams.getAll("provider");
    const datasets = url.searchParams.getAll("dataset_key");
    const kinds = url.searchParams.getAll("kind");
    const categories = url.searchParams.getAll("category");
    const minScore = Number(url.searchParams.get("min_score") ?? Number.NaN);
    const maxScore = Number(url.searchParams.get("max_score") ?? Number.NaN);
    return rowsForStatus(status).filter((review) => {
      const features = [review.feature_a, review.feature_b];
      const text = [
        review.review_id,
        ...features.flatMap((feature) => [feature.feature_id, feature.name]),
      ]
        .join(" ")
        .toLowerCase();
      return (
        (!q || text.includes(q)) &&
        (providers.length === 0 ||
          features.some((feature) => providers.includes(feature.provider ?? ""))) &&
        (datasets.length === 0 ||
          features.some((feature) => datasets.includes(feature.dataset_key ?? ""))) &&
        (kinds.length === 0 ||
          features.some((feature) => kinds.includes(feature.kind))) &&
        (categories.length === 0 ||
          features.some((feature) => categories.includes(feature.category))) &&
        (Number.isNaN(minScore) || review.total_score >= minScore) &&
        (Number.isNaN(maxScore) || review.total_score <= maxScore)
      );
    });
  }

  await page.route("**/v1/admin/dedup-reviews**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = apiPathname(url);

    if (
      request.method() === "GET" &&
      path === "/v1/admin/dedup-reviews"
    ) {
      handle.requests.list += 1;
      handle.requests.lastListUrl = url;
      handle.requests.listUrls.push(url);
      const pageSize = Number(url.searchParams.get("page_size") ?? 100);
      const rows = filteredRows(url);
      const pageIndex = Math.max(1, Number(url.searchParams.get("page") ?? 1));
      const start = (pageIndex - 1) * pageSize;
      const nextCursor =
        rows.length > start + pageSize ? `cursor-page-${pageIndex + 1}` : null;
      await fulfillJson(
        route,
        listResponse(rows.slice(start, start + pageSize), {
          nextCursor,
          pageSize,
          total: rows.length,
        }),
      );
      return;
    }

    if (
      request.method() === "GET" &&
      path.startsWith("/v1/admin/dedup-reviews/")
    ) {
      const reviewId = decodeURIComponent(
        path.slice("/v1/admin/dedup-reviews/".length),
      );
      const review =
        pending.find((item) => item.review_id === reviewId) ??
        makeDedupReview({ review_id: reviewId });
      await fulfillJson(route, detailResponse(review));
      return;
    }

    if (
      request.method() === "PATCH" &&
      path.startsWith("/v1/admin/dedup-reviews/")
    ) {
      handle.requests.patch += 1;
      const body = request.postDataJSON() as DedupReviewDecisionRequest;
      handle.requests.bodies.push(body);
      const reviewId = decodeURIComponent(
        path.slice("/v1/admin/dedup-reviews/".length),
      );
      handle.requests.paths.push(reviewId);
      const review =
        pending.find((item) => item.review_id === reviewId) ??
        makeDedupReview({ review_id: reviewId });

      const respond = async () => {
        statusById.set(reviewId, DECISION_TO_STATUS[body.decision]);
        await fulfillJson(route, decisionResponse(review, body));
      };

      if (options.holdPatch) {
        // mutex 시나리오: 수동 해제까지 decision.isPending을 유지한다.
        await new Promise<void>((resolve) => {
          handle.releasePatch = () => resolve();
        });
      }
      await respond();
      return;
    }

    throw new Error(`Unhandled dedup-reviews route: ${request.method()} ${url}`);
  });

  return handle;
}

/**
 * /admin/dedup-reviews 액션 depth (admin-ops smoke 위 추가분).
 * accept/reject/ignore/merge(수동·자동)·취소·mutex·status filter·empty·error·bulk.
 */
test.describe("admin/dedup-reviews actions", () => {
  test("row click opens detail compare dialog with map and raw fields", async ({
    page,
  }) => {
    const review = makeDedupReview({
      feature_a: makeDedupFeature({
        lat: 37.5664,
        lon: 126.9781,
        name: "DEDUP_A_detail",
      }),
      feature_b: makeDedupFeature({
        lat: 37.5665,
        lon: 126.978,
        name: "DEDUP_B_detail",
        provider: "python-visitkorea-api",
      }),
      review_id: "dedup-review-detail-aaaa-bbbb-cccc-000000000020",
    });
    await mockDedupReviews(page, { byStatus: { pending: [review] } });

    await page.goto("/admin/dedup-reviews");
    const row = page.getByRole("row", { name: /DEDUP_A_detail/ });
    await expect(row).toBeVisible();

    await row.click();

    const dialog = page.getByRole("dialog", { name: "dedup review detail" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Feature A")).toBeVisible();
    await expect(dialog.getByText("Feature B")).toBeVisible();
    await expect(dialog).toContainText("DEDUP_A_detail detail");
    await expect(dialog).toContainText("DEDUP_B_detail detail");
    await expect(page.getByTestId("dedup-detail-map")).toBeVisible();
  });

  test("accept decision PATCHes decision=accepted and collapses to 완료", async ({
    page,
  }) => {
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();

    await expect(
      page.getByRole("row", { name: /DEDUP_A_alpha/ }),
    ).toBeVisible();

    // 기본 목록 쿼리: page_size=100, page=1, cursor 없음, status='pending'.
    const firstList = handle.requests.lastListUrl;
    expect(firstList?.searchParams.get("page_size")).toBe("100");
    expect(firstList?.searchParams.get("page")).toBe("1");
    expect(firstList?.searchParams.has("cursor")).toBe(false);
    expect(firstList?.searchParams.getAll("status")).toEqual(["pending"]);

    // 결정 후 refetch에서도 행이 유지되도록 status 필터를 'all'로 바꾼다(enrichment-reviews
    // 패턴) — 기본 'pending' 필터면 accepted record가 목록에서 빠져 '완료'를 못 본다.
    await page.getByLabel("dedup status").selectOption("all");

    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "accept" }).click();

    await expect.poll(() => handle.requests.patch).toBe(1);
    expect(handle.requests.paths[0]).toBe(REVIEW_ID_1);
    expect(handle.requests.bodies[0]).toMatchObject({
      decision: "accepted",
      decision_reason: "admin-ui accepted",
      reviewed_by: "local-admin",
    });

    // onSuccess invalidate → refetch가 status='accepted'를 반영, actions 셀이 '완료'로 collapse.
    await expect(row.getByText("완료")).toBeVisible();
    await expect(row.getByRole("button", { name: "accept" })).toHaveCount(0);
  });

  test("reject decision PATCHes decision=rejected without master_feature_id", async ({
    page,
  }) => {
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    // 결정 후 refetch에서도 행이 유지되도록 'all'로 전환(기본 'pending' 필터면 rejected
    // record가 목록에서 빠져 '완료'를 못 본다).
    await page.getByLabel("dedup status").selectOption("all");
    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "reject" }).click();

    await expect.poll(() => handle.requests.patch).toBe(1);
    expect(handle.requests.bodies[0]).toMatchObject({
      decision: "rejected",
      decision_reason: "admin-ui rejected",
      reviewed_by: "local-admin",
    });
    // reject 본문에는 master_feature_id 키가 없다(merge만 전송).
    expect(handle.requests.bodies[0].master_feature_id).toBeUndefined();

    // status-filter의 'rejected' option 텍스트와 충돌하지 않도록 행 범위로 '완료'만 단언.
    await expect(row.getByText("완료")).toBeVisible();
  });

  test("ignore decision PATCHes decision=ignored", async ({ page }) => {
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "ignore" }).click();

    await expect.poll(() => handle.requests.patch).toBe(1);
    expect(handle.requests.bodies[0]).toMatchObject({
      decision: "ignored",
      decision_reason: "admin-ui ignored",
      reviewed_by: "local-admin",
    });
  });

  test("merge with explicit master (B) sends master_feature_id=feature_b", async ({
    page,
  }) => {
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    // 병합 후 refetch에서도 행이 유지되도록 'all'로 전환(기본 'pending' 필터면 merged
    // record가 목록에서 빠져 '완료'를 못 본다).
    await page.getByLabel("dedup status").selectOption("all");
    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "merge" }).click();

    // inline master 선택 패널(mergeKey === review_id 분기)이 뜨고 bare accept/reject는 사라진다.
    await expect(
      row.getByText("master 선택 (병합 시 나머지는 master로 흡수)"),
    ).toBeVisible();
    await expect(row.getByRole("button", { name: "accept" })).toHaveCount(0);
    // feature_b는 좌표 보유 → 'B: DEDUP_B_beta · 좌표✓'; /^B:/로 좌표✓ suffix에 견고하게 매칭.
    await expect(row.getByRole("button", { name: /^B:/ })).toBeVisible();
    await expect(row.getByRole("button", { name: /^A:/ })).toBeVisible();

    await row.getByRole("button", { name: /^B:/ }).click();

    await expect.poll(() => handle.requests.patch).toBe(1);
    expect(handle.requests.bodies[0]).toMatchObject({
      decision: "merged",
      master_feature_id: FEATURE_B_ID,
      decision_reason: "admin-ui merge (master 수동 선택)",
      reviewed_by: "local-admin",
    });

    // onSettled → setMergeKey(null), refetch는 status='merged' → '완료', 패널 사라짐.
    await expect(row.getByText("완료")).toBeVisible();
    await expect(
      page.getByText("master 선택 (병합 시 나머지는 master로 흡수)"),
    ).toHaveCount(0);
  });

  test("merge with automatic master (자동 선정) omits master_feature_id", async ({
    page,
  }) => {
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "merge" }).click();
    await row.getByRole("button", { name: "자동 선정" }).click();

    await expect.poll(() => handle.requests.patch).toBe(1);
    expect(handle.requests.bodies[0]).toMatchObject({
      decision: "merged",
      decision_reason: "admin-ui merge (master 자동 선정)",
      reviewed_by: "local-admin",
    });
    // 자동 경로는 masterFeatureId === undefined → JSON.stringify가 키를 drop.
    expect(handle.requests.bodies[0].master_feature_id).toBeUndefined();
  });

  test("merge 취소 closes the master panel without a mutation", async ({
    page,
  }) => {
    // PATCH 라우트를 등록하지 않는다 — '취소'가 decision.mutate를 호출하면 mock이 throw하며 fail.
    const handle = await mockDedupReviews(page);

    await page.goto("/admin/dedup-reviews");
    const row = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "merge" }).click();
    await expect(
      row.getByText("master 선택 (병합 시 나머지는 master로 흡수)"),
    ).toBeVisible();

    await row.getByRole("button", { name: "취소" }).click();

    // 패널이 닫히고 기본 actions 분기(bare 'accept')로 복귀.
    await expect(
      page.getByText("master 선택 (병합 시 나머지는 master로 흡수)"),
    ).toHaveCount(0);
    await expect(row.getByRole("button", { name: "accept" })).toBeVisible();
    expect(handle.requests.patch).toBe(0);
  });

  test("ADR-039 mutex — while a decision is pending every action button is disabled", async ({
    page,
  }) => {
    // 두 pending 행 시드. PATCH를 열어둔 채(holdPatch) decision.isPending=true를 유지해
    // disabled={decision.isPending} 가드(서버측 dedup-merge advisory lock의 client 반영)를 관찰.
    const reviewA = makeDedupReview();
    const reviewB = makeDedupReview({
      feature_a: makeDedupFeature({
        feature_id: "python-mois-api::mois_license::DEDUP_A_gamma",
        name: "DEDUP_A_gamma",
      }),
      feature_b: makeDedupFeature({
        feature_id: "python-visitkorea-api::vk_place::DEDUP_B_delta",
        lat: 37.5,
        lon: 127.0,
        name: "DEDUP_B_delta",
        provider: "python-visitkorea-api",
      }),
      review_id: REVIEW_ID_2,
    });
    const handle = await mockDedupReviews(page, {
      byStatus: { pending: [reviewA, reviewB] },
      holdPatch: true,
    });

    await page.goto("/admin/dedup-reviews");
    // 병합 settle 후 refetch에서도 row1이 유지되도록 'all'로 전환(기본 'pending' 필터면
    // merged record가 목록에서 빠져 '완료'를 못 본다). 'all'은 byStatus.pending 행 집합을
    // status param 없이 그대로 반환한다(rowsForStatus(null) → base).
    await page.getByLabel("dedup status").selectOption("all");
    const row1 = page.getByRole("row", { name: /DEDUP_A_alpha/ });
    const row2 = page.getByRole("row", { name: /DEDUP_A_gamma/ });
    await expect(row1).toBeVisible();
    await expect(row2).toBeVisible();

    // row1 master 패널 열고 '자동 선정'으로 in-flight mutation 시작.
    await row1.getByRole("button", { name: "merge" }).click();
    await row1.getByRole("button", { name: "자동 선정" }).click();

    // pending 동안 다른 행의 accept 버튼이 disabled.
    await expect(row2.getByRole("button", { name: "accept" })).toBeDisabled();
    await expect(row2.getByRole("button", { name: "reject" })).toBeDisabled();

    // 보류된 PATCH 해제 → 정확히 1회, refetch 후 row1은 '완료'로 collapse.
    handle.releasePatch();
    await expect.poll(() => handle.requests.patch).toBe(1);
    await expect(row1.getByText("완료")).toBeVisible();
    await expect(row2.getByRole("button", { name: "accept" })).toBeEnabled();
  });

  test("status filter sends the selected status param; 'all' omits it", async ({
    page,
  }) => {
    const mergedReview = makeDedupReview({
      feature_a: makeDedupFeature({
        feature_id: "python-mois-api::mois_license::DEDUP_A_merged",
        name: "DEDUP_A_merged",
      }),
      review_id: "dedup-review-0003-merged-0000-0000-000000000003",
      status: "merged",
    });
    const handle = await mockDedupReviews(page, {
      byStatus: {
        pending: [makeDedupReview()],
        merged: [mergedReview],
      },
    });

    await page.goto("/admin/dedup-reviews");
    await expect(page.getByRole("row", { name: /DEDUP_A_alpha/ })).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "feature A" }),
    ).toBeVisible();

    // 'merged' 선택 → queryKey 변경 → 마지막 GET의 status=['merged'].
    await page.getByLabel("dedup status").selectOption("merged");
    await expect(page.getByText("DEDUP_A_merged")).toBeVisible();
    await expect
      .poll(() => handle.requests.lastListUrl?.searchParams.getAll("status"))
      .toEqual(["merged"]);

    // 'all' → status: undefined → 마지막 GET에 status param 없음(센티넬은 param 미전송).
    await page.getByLabel("dedup status").selectOption("all");
    await expect(page.getByRole("row", { name: /DEDUP_A_alpha/ })).toBeVisible();
    await expect
      .poll(() => handle.requests.lastListUrl?.searchParams.has("status"))
      .toBe(false);
  });

  test("search and dedup-specific filters are sent as GET params", async ({
    page,
  }) => {
    const filterReview = makeDedupReview({
      total_score: 95,
      feature_a: makeDedupFeature({
        category: "02020101",
        dataset_key: "mois_license",
        feature_id: "python-mois-api::mois_license::DEDUP_A_filter",
        kind: "place",
        name: "DEDUP_A_filter",
        provider: "python-mois-api",
      }),
      review_id: "dedup-review-filter-aaaa-bbbb-cccc-000000000010",
    });
    const otherReview = makeDedupReview({
      total_score: 40,
      feature_a: makeDedupFeature({
        category: "01010100",
        dataset_key: "vk_event",
        feature_id: "python-visitkorea-api::vk_event::DEDUP_A_other",
        kind: "event",
        name: "DEDUP_A_other",
        provider: "python-visitkorea-api",
      }),
      review_id: "dedup-review-filter-aaaa-bbbb-cccc-000000000011",
    });
    const handle = await mockDedupReviews(page, {
      byStatus: { pending: [filterReview, otherReview] },
    });

    await page.goto("/admin/dedup-reviews");
    await page.getByLabel("dedup search").fill("filter");
    await page.getByLabel("dedup kind").selectOption("place");
    await page.getByLabel("dedup provider").fill("python-mois-api");
    await page.getByLabel("dedup dataset").fill("mois_license");
    await page.getByLabel("dedup category").fill("02020101");
    await page.getByLabel("dedup score filter").selectOption("high");
    await page.getByLabel("dedup page size").selectOption("25");

    await expect(page.getByRole("row", { name: /DEDUP_A_filter/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /DEDUP_A_other/ })).toHaveCount(0);

    await expect
      .poll(() => handle.requests.lastListUrl?.searchParams.get("q"))
      .toBe("filter");
    const last = handle.requests.lastListUrl;
    expect(last?.searchParams.getAll("kind")).toEqual(["place"]);
    expect(last?.searchParams.getAll("provider")).toEqual(["python-mois-api"]);
    expect(last?.searchParams.getAll("dataset_key")).toEqual(["mois_license"]);
    await expect
      .poll(() => handle.requests.lastListUrl?.searchParams.getAll("category"))
      .toEqual(["02020101"]);
    expect(last?.searchParams.get("min_score")).toBe("90");
    expect(last?.searchParams.get("page_size")).toBe("25");
  });

  test("page-size select drives page pagination controls", async ({ page }) => {
    const rows = Array.from({ length: 26 }, (_value, index) =>
      makeDedupReview({
        feature_a: makeDedupFeature({
          feature_id: `python-mois-api::mois_license::DEDUP_A_page_${index}`,
          name: `DEDUP_A_page_${index}`,
        }),
        review_id: `dedup-review-page-${String(index).padStart(4, "0")}-aaaa-bbbb-cccc`,
      }),
    );
    const handle = await mockDedupReviews(page, {
      byStatus: { pending: rows },
    });

    await page.goto("/admin/dedup-reviews");
    await page.getByLabel("dedup page size").selectOption("25");

    await expect(
      page.getByText(/페이지 1 \/ 2 · 총 26건 · 현재 25건/),
    ).toHaveCount(2);
    await expect(page.getByLabel("dedup 이전 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 다음 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 마지막 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 이전 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("dedup 다음 페이지").first()).toBeEnabled();
    await expect(page.getByLabel("dedup 마지막 페이지").first()).toBeEnabled();

    await page.getByLabel("dedup 다음 페이지").first().click();
    await expect
      .poll(() => handle.requests.lastListUrl?.searchParams.get("page"))
      .toBe("2");
    await expect(
      page.getByText(/페이지 2 \/ 2 · 총 26건 · 현재 1건/),
    ).toHaveCount(2);
    await expect(page.getByRole("row", { name: /DEDUP_A_page_25/ })).toBeVisible();
    await expect(page.getByLabel("dedup 다음 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("dedup 마지막 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("dedup 이전 페이지").first()).toBeEnabled();

    await page.getByLabel("dedup 첫 페이지").first().click();
    await expect(
      page.getByText(/페이지 1 \/ 2 · 총 26건 · 현재 25건/),
    ).toHaveCount(2);
  });

  test("empty list renders the dedup empty message", async ({ page }) => {
    await mockDedupReviews(page, { byStatus: { pending: [] } });

    await page.goto("/admin/dedup-reviews");

    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();
    await expect(page.getByText("dedup review가 없습니다.")).toBeVisible();
    await expect(page.getByLabel("dedup 이전 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 다음 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 마지막 페이지")).toHaveCount(2);
    await expect(page.getByLabel("dedup 이전 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("dedup 다음 페이지").first()).toBeDisabled();
    await expect(page.getByLabel("dedup 마지막 페이지").first()).toBeDisabled();
    await expect(
      page.getByText(/페이지 1 \/ 1 · 총 0건 · 현재 0건/),
    ).toHaveCount(2);
    for (const column of ["review", "score", "feature A", "feature B", "actions"]) {
      await expect(
        page.getByRole("columnheader", { name: column }),
      ).toBeVisible();
    }
  });

  test("list error renders the destructive alert (role=alert)", async ({
    page,
  }) => {
    await page.route("**/v1/admin/dedup-reviews**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = apiPathname(url);
      if (
        request.method() === "GET" &&
        path === "/v1/admin/dedup-reviews"
      ) {
        await route.fulfill({ status: 500, body: "" });
        return;
      }
      await route.continue();
    });

    await page.goto("/admin/dedup-reviews");

    // variant='destructive' Alert => role=alert (Wave-1 gotcha).
    await expect(
      page.getByRole("alert").filter({ hasText: "dedup review 처리 실패" }),
    ).toBeVisible();
    // AlertDescription = reviews.error.message; 전체 로컬라이즈 메시지 결합을 피해 부분 매칭.
    await expect(page.getByText(/실패 \(HTTP 500\)/)).toBeVisible();
    // 헤딩 + AdminShell 새로고침 버튼은 그대로 남는다.
    await expect(
      page.getByRole("heading", { level: 1, name: "Dedup review" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "새로고침" }),
    ).toBeVisible();
  });

  test("bulk accept on selected pending rows fires one PATCH per row", async ({
    page,
  }) => {
    const reviewA = makeDedupReview();
    const reviewB = makeDedupReview({
      feature_a: makeDedupFeature({
        feature_id: "python-mois-api::mois_license::DEDUP_A_gamma",
        name: "DEDUP_A_gamma",
      }),
      feature_b: makeDedupFeature({
        feature_id: "python-visitkorea-api::vk_place::DEDUP_B_delta",
        lat: 37.5,
        lon: 127.0,
        name: "DEDUP_B_delta",
        provider: "python-visitkorea-api",
      }),
      review_id: REVIEW_ID_2,
    });
    const handle = await mockDedupReviews(page, {
      byStatus: { pending: [reviewA, reviewB] },
    });

    await page.goto("/admin/dedup-reviews");

    // 행-준비 대기(Wave-1 early-click race guard): 첫 select 체크박스가 보일 때까지.
    const rowSelect = page.getByRole("checkbox", { name: "행 선택" });
    await expect(rowSelect.first()).toBeVisible();

    // 전체 선택: base-ui checkbox aria-checked가 신뢰 불가하므로 bulk toolbar 텍스트로 단언.
    await page.getByRole("checkbox", { name: "전체 선택" }).click();
    await expect(page.getByText("2개 선택됨")).toBeVisible();

    await page.getByRole("button", { name: "선택 accept" }).click();

    // decideBulk가 pending 행마다 decide(...,'accepted') → PATCH 2회.
    await expect.poll(() => handle.requests.patch).toBe(2);
    for (const body of handle.requests.bodies) {
      expect(body).toMatchObject({
        decision: "accepted",
        decision_reason: "admin-ui accepted",
        reviewed_by: "local-admin",
      });
    }
    // invalidation refetch 후 setRowSelection({}) → toolbar 사라짐.
    await expect(page.getByText(/개 선택됨/)).toHaveCount(0);
  });
});
