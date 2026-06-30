import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import type { KorTravelGeoResponse } from "../src/api/korTravelGeo";

/**
 * `/admin/features/new` — route-mocked depth specs (T-AUDIT-0616 후속).
 *
 * `e2e/features-new.spec.ts`는 라이브 smoke 렌더 + 동기 클라이언트 검증만 덮는다.
 * 본 spec은 백엔드/지오코더 호출이 필요한 **결정적 mutation·조회 경로**를 route mock으로
 * 분리한다:
 *   - POST /v1/admin/features 성공 → 변경 요청 생성 알림 + 생성 요청 섹션
 *   - GET /v1/features/nearby 자동 조회(유효 좌표) → 중복 후보 렌더 / 빈 응답 / 재조회
 *   - POST /v1/admin/features 422·409 → 'feature 작성 실패' 알림
 *   - POST :12501/v2/geocode, /v2/reverse → 후보 적용으로 좌표·주소 채움 / 실패 알림
 *
 * 모든 backend mock body는 생성 OpenAPI 스키마(`components["schemas"]`)에 바인딩해
 * mock-실계약 drift를 컴파일 타임에 잡는다. kor-travel-geo 응답은 손으로 정의한
 * `KorTravelGeoResponse`(components 스키마 아님)에 바인딩한다. 422/409 error body는
 * RFC7807 problem+json(rest-api.md §1.5)이라 충실한 components 스키마가 없어 LITERAL로
 * 둔다 — 단언은 클라이언트가 만든 메시지 substring('(HTTP nnn)')에 건다(결정적).
 *
 * NOTE: Playwright는 Windows 호스트에서만 실행된다. 지도(maplibre)는 VWorld key 없이
 * 회색 fallback으로 뜨므로 좌표는 지도 클릭이 아니라 lon/lat 입력 채우기로 설정한다
 * (updateCoord가 쓰는 동일 state 경로). 검증은 폼/알림 상태 중심.
 */

type AdminFeatureChangeRecord =
  components["schemas"]["AdminFeatureChangeRequestRecord"];
type AdminFeatureChangeResponse =
  components["schemas"]["AdminFeatureChangeResponse"];
type AdminFeatureCreateRequest =
  components["schemas"]["AdminFeatureCreateRequest"];
type FeaturesNearbyResponse = components["schemas"]["FeaturesNearbyResponse"];
type NearbyFeatureSummary = components["schemas"]["NearbyFeatureSummary"];
type NearbyOriginSummary = components["schemas"]["NearbyOriginSummary"];
type Meta = components["schemas"]["Meta"];

const MOCK_NOW = "2026-06-16T00:00:00.000Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makeChangeRecord(
  overrides: Partial<AdminFeatureChangeRecord> = {},
): AdminFeatureChangeRecord {
  return {
    action: "add",
    applied_at: null,
    created_at: MOCK_NOW,
    feature_id: "user_request::e2e::created",
    payload: {
      category: "01070300",
      kind: "place",
      name: "새 장소",
    },
    reason: "e2e 수동 생성",
    // <=18자로 둬 success-alert의 shortId(request_id, 18) 링크 텍스트가 전체 id와 일치.
    request_id: "change-create-001",
    requested_by: "local-admin",
    review_mode: "require_review",
    reviewed_at: null,
    reviewed_by: null,
    status: "pending",
    ...overrides,
  };
}

function makeChangeResponse(
  request: AdminFeatureChangeRecord,
): AdminFeatureChangeResponse {
  return {
    data: { request },
    meta: { duration_ms: 1, request_id: "e2e-feature-change" },
  };
}

function makeNearby(
  overrides: Partial<NearbyFeatureSummary> = {},
): NearbyFeatureSummary {
  return {
    category: "01070300",
    distance_m: 42.5,
    feature_id: "visitkorea::poi::dup-1",
    kind: "place",
    lat: 37.5667,
    lon: 126.9782,
    name: "인근 중복 후보",
    status: "active",
    ...overrides,
  };
}

function makeNearbyMeta(): Meta {
  return {
    duration_ms: 1,
    page: { page_size: 8, next_cursor: null, total: null },
    request_id: "e2e-nearby",
  };
}

function makeNearbyResponse(
  items: NearbyFeatureSummary[],
  origin: NearbyOriginSummary = { lon: 126.978, lat: 37.5665, radius_m: 150 },
): FeaturesNearbyResponse {
  return {
    data: { items, origin },
    meta: makeNearbyMeta(),
  };
}

/**
 * `v1/admin/features` glob은 페이지의 RSC document/navigation 요청과도 매칭된다.
 * admin-ops.spec의 가드를 그대로 미러해 document/_rsc는 continue하고, mutation만
 * method+pathname으로 분기한다.
 */
async function mockCreateRoute(
  page: Page,
  handler: (route: Route, body: AdminFeatureCreateRequest) => Promise<void>,
) {
  const state = { count: 0, bodies: [] as AdminFeatureCreateRequest[] };
  await page.route("**/v1/admin/features**", async (route) => {
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
    if (request.method() === "POST" && url.pathname === "/v1/admin/features") {
      state.count += 1;
      const body = request.postDataJSON() as AdminFeatureCreateRequest;
      state.bodies.push(body);
      await handler(route, body);
      return;
    }
    await route.continue();
  });
  return state;
}

/** 유효 좌표 입력 시 자동 발화하는 nearby GET을 mock한다(빈 items로 격리하거나 후보 반환). */
async function mockNearbyRoute(
  page: Page,
  response: (url: URL) => FeaturesNearbyResponse,
) {
  const state = { count: 0, urls: [] as URL[] };
  await page.route("**/v1/features/nearby**", async (route) => {
    const request = route.request();
    if (request.method() !== "GET") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    state.count += 1;
    state.urls.push(url);
    await fulfillJson(route, response(url));
  });
  return state;
}

async function mockGeoRoute(
  page: Page,
  path: "/v2/geocode" | "/v2/reverse",
  body: KorTravelGeoResponse | Record<string, unknown>,
  status = 200,
) {
  const state = { count: 0, bodies: [] as Record<string, unknown>[] };
  await page.route(`**${path}**`, async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    state.count += 1;
    state.bodies.push(request.postDataJSON() as Record<string, unknown>);
    await fulfillJson(route, body, status);
  });
  return state;
}

/** 좌표 입력으로 coord 활성화(지도 클릭 대신 — risk 항목 참고). */
async function fillCoord(page: Page, lon = "126.978", lat = "37.5665") {
  await page.getByLabel("lon", { exact: true }).fill(lon);
  await page.getByLabel("lat", { exact: true }).fill(lat);
}

test.describe("/admin/features/new (mocked routes)", () => {
  test("제출 성공 — POST /v1/admin/features → 변경 요청 생성 알림 + 생성 요청 섹션", async ({
    page,
  }) => {
    const nearby = await mockNearbyRoute(page, () => makeNearbyResponse([]));
    const create = await mockCreateRoute(page, async (route, body) => {
      await fulfillJson(
        route,
        makeChangeResponse(
          makeChangeRecord({
            action: "add",
            status: "pending",
            review_mode: "require_review",
            feature_id: body.feature_id ?? "user_request::e2e::created",
            payload: { ...body },
            reason: body.reason,
            request_id: "change-create-001",
          }),
        ),
      );
    });

    await page.goto("/admin/features/new");

    await page.getByLabel("name", { exact: true }).fill("새 장소");
    await page.getByLabel("reason", { exact: true }).fill("e2e 수동 생성");
    // category 기본값 '01070300' 그대로 유효. 유효 좌표 입력 → nearby 자동 발화.
    await fillCoord(page);
    await expect.poll(() => nearby.count).toBeGreaterThanOrEqual(1);

    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => create.count).toBe(1);
    expect(create.bodies[0]).toMatchObject({
      kind: "place",
      name: "새 장소",
      category: "01070300",
      coord: { lon: 126.978, lat: 37.5665 },
      reason: "e2e 수동 생성",
      status: "active",
      marker_icon: "marker",
      marker_color: "P-01",
      operator: "local-admin",
    });

    // 성공 Alert(role=status) + 라벨 텍스트.
    const successAlert = page
      .getByRole("status")
      .filter({ hasText: "변경 요청 생성됨" });
    await expect(successAlert).toBeVisible();
    await expect(page.getByText("add/pending")).toBeVisible();
    // 짧은 request_id(<18자)는 shortId가 그대로 노출 → 알림 링크.
    await expect(
      successAlert.getByRole("link", { name: "change-create-001" }),
    ).toBeVisible();

    // '생성 요청' 섹션 + 전체 request_id 노출.
    await expect(
      page.getByRole("heading", { level: 2, name: "생성 요청" }),
    ).toBeVisible();
    await expect(page.getByText("change-create-001").last()).toBeVisible();
  });

  test("중복 후보 — 유효 좌표 입력 시 GET /v1/features/nearby 자동 조회 + 후보 행 렌더", async ({
    page,
  }) => {
    const nearby = await mockNearbyRoute(page, () =>
      makeNearbyResponse([makeNearby()]),
    );

    await page.goto("/admin/features/new");
    await fillCoord(page);

    await expect.poll(() => nearby.count).toBeGreaterThanOrEqual(1);

    // 캡처한 쿼리 파라미터 검증.
    const firstUrl = nearby.urls[0];
    expect(firstUrl.searchParams.get("radius_m")).toBe("150");
    expect(firstUrl.searchParams.get("page_size")).toBe("8");
    expect(firstUrl.searchParams.get("sort")).toBe("distance");
    const statuses = firstUrl.searchParams.getAll("status");
    expect(statuses).toContain("active");
    expect(statuses).toContain("inactive");
    expect(statuses).toContain("hidden");

    // 후보 행: feature cell의 Link + distance .toFixed(1)+'m'.
    await expect(
      page.getByRole("link", { name: "인근 중복 후보" }),
    ).toBeVisible();
    await expect(page.getByText("42.5m")).toBeVisible();

    // 재조회 버튼 → 추가 GET 발화.
    await page.getByRole("button", { name: "재조회" }).click();
    await expect.poll(() => nearby.count).toBeGreaterThanOrEqual(2);
  });

  test("중복 후보 — items 빈 응답이면 '후보 없음' 표시", async ({ page }) => {
    const nearby = await mockNearbyRoute(page, () => makeNearbyResponse([]));

    await page.goto("/admin/features/new");
    await fillCoord(page);

    await expect.poll(() => nearby.count).toBeGreaterThanOrEqual(1);
    await expect(page.getByText("후보 없음")).toBeVisible();
  });

  test("422 검증 오류 — 서버 422 응답이 'feature 작성 실패' 알림으로 노출", async ({
    page,
  }) => {
    await mockNearbyRoute(page, () => makeNearbyResponse([]));
    const create = await mockCreateRoute(page, async (route) => {
      // LITERAL problem+json (rest-api.md §1.5) — 충실한 components 스키마 없음.
      await fulfillJson(
        route,
        {
          type: "https://kor-travel-map/errors/validation",
          title: "Validation error",
          status: 422,
          detail: "category invalid",
          code: "VALIDATION_ERROR",
          request_id: "e2e-422",
          errors: [{ field: "category", message: "category invalid" }],
        },
        422,
      );
    });

    await page.goto("/admin/features/new");
    await page.getByLabel("name", { exact: true }).fill("새 장소");
    await page.getByLabel("reason", { exact: true }).fill("e2e 수동 생성");
    await fillCoord(page);

    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => create.count).toBe(1);
    await expect(page.getByText("feature 작성 실패")).toBeVisible();
    // 클라이언트가 만든 메시지: `POST /v1/admin/features 실패 (HTTP 422) <body>`.
    // 422는 detail("category invalid")이 필드 에러도 트리거하므로 role=alert가
    // 두 개(상단 페이지 알림 + 필드 에러) 렌더된다. 상단 알림(AlertTitle
    // "feature 작성 실패")으로 한정해 strict-mode 위반을 피한다.
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "feature 작성 실패" })
        .filter({ hasText: "(HTTP 422)" }),
    ).toBeVisible();
    // 성공 섹션은 렌더되지 않음.
    await expect(page.getByText("변경 요청 생성됨")).toHaveCount(0);
  });

  test("409 충돌 — 서버 409 응답이 'feature 작성 실패' 알림으로 노출", async ({
    page,
  }) => {
    await mockNearbyRoute(page, () => makeNearbyResponse([]));
    const create = await mockCreateRoute(page, async (route) => {
      await fulfillJson(
        route,
        {
          type: "https://kor-travel-map/errors/lock-busy",
          title: "Conflict",
          status: 409,
          detail: "feature already exists",
          code: "LOCK_BUSY",
          request_id: "e2e-409",
        },
        409,
      );
    });

    await page.goto("/admin/features/new");
    await page.getByLabel("name", { exact: true }).fill("새 장소");
    await page.getByLabel("reason", { exact: true }).fill("e2e 수동 생성");
    await fillCoord(page);

    await page.getByRole("button", { name: "요청 생성" }).click();

    await expect.poll(() => create.count).toBe(1);
    await expect(page.getByText("feature 작성 실패")).toBeVisible();
    await expect(
      page.getByRole("alert").filter({ hasText: "(HTTP 409)" }),
    ).toBeVisible();
    await expect(page.getByText("변경 요청 생성됨")).toHaveCount(0);
  });

  test("정지오코딩 — POST :12501/v2/geocode 후보 적용으로 좌표·주소 채움", async ({
    page,
  }) => {
    const geoBody: KorTravelGeoResponse = {
      status: "ok",
      candidates: [
        {
          match_kind: "road",
          confidence: 0.95,
          address: {
            road_address: "서울특별시 중구 세종대로 110",
            parcel_address: "태평로1가 31",
            legal_dong_code: "1114010300",
            road_name_code: "111404166007",
            admin_dong_code: "1114055000",
          },
          region: {
            sido: "서울특별시",
            sigungu: "중구",
            sig_cd: "11140",
            bjd_cd: "1114010300",
          },
          point: { lon: 126.9784, lat: 37.5665 },
        },
      ],
    };
    const geocode = await mockGeoRoute(page, "/v2/geocode", geoBody);
    // geocode가 좌표를 채우면 nearby가 자동 발화 → 격리용 빈 응답 mock.
    await mockNearbyRoute(page, () => makeNearbyResponse([]));

    await page.goto("/admin/features/new");
    await page.getByLabel("주소 검색", { exact: true }).fill("세종대로 110");
    await page.getByRole("button", { name: "정지오코딩" }).click();

    await expect.poll(() => geocode.count).toBe(1);
    expect(geocode.bodies[0]).toMatchObject({
      road_address: "세종대로 110",
      fallback: "api",
    });

    // applyCandidate가 첫 후보 자동 적용: updateCoord(toFixed(6)).
    await expect(page.getByLabel("lon", { exact: true })).toHaveValue(
      "126.978400",
    );
    await expect(page.getByLabel("lat", { exact: true })).toHaveValue(
      "37.566500",
    );
    await expect(page.getByLabel("road", { exact: true })).toHaveValue(
      "서울특별시 중구 세종대로 110",
    );

    // 후보 버튼 리스트 + 배지 카운트.
    await expect(
      page.getByRole("button", { name: /세종대로/ }),
    ).toBeVisible();
    await expect(page.getByText("1건")).toBeVisible();
  });

  test("역지오코딩 — 유효 좌표에서 POST :12501/v2/reverse 후보 적용", async ({
    page,
  }) => {
    const geoBody: KorTravelGeoResponse = {
      status: "ok",
      candidates: [
        {
          match_kind: "reverse",
          distance_m: 5.0,
          address: {
            road_address: "서울특별시 중구 세종대로 110",
            legal_dong_code: "1114010300",
            road_name_code: "111404166007",
          },
          region: {
            sido: "서울특별시",
            sigungu: "중구",
            sig_cd: "11140",
          },
          point: { lon: 126.978, lat: 37.5665 },
        },
      ],
    };
    const reverse = await mockGeoRoute(page, "/v2/reverse", geoBody);
    await mockNearbyRoute(page, () => makeNearbyResponse([]));

    await page.goto("/admin/features/new");
    // 유효 좌표 입력 → coord 유효 → 역지오코딩 버튼 enabled(disabled={!coord||pending}).
    await fillCoord(page);
    await page.getByRole("button", { name: "역지오코딩" }).click();

    await expect.poll(() => reverse.count).toBe(1);
    expect(reverse.bodies[0]).toMatchObject({
      lon: 126.978,
      lat: 37.5665,
      include_region: true,
      include_zipcode: true,
      radius_m: 100,
    });

    await expect(page.getByLabel("road", { exact: true })).toHaveValue(
      "서울특별시 중구 세종대로 110",
    );
    await expect(
      page.getByRole("button", { name: /세종대로/ }),
    ).toBeVisible();
  });

  test("정지오코딩 실패 — :12501 5xx 응답이 'feature 작성 실패' 알림으로 노출", async ({
    page,
  }) => {
    const geocode = await mockGeoRoute(
      page,
      "/v2/geocode",
      { detail: "upstream down" },
      502,
    );

    await page.goto("/admin/features/new");
    await page.getByLabel("주소 검색", { exact: true }).fill("세종대로 110");
    await page.getByRole("button", { name: "정지오코딩" }).click();

    await expect.poll(() => geocode.count).toBe(1);
    // 동일 destructive Alert; formError가 null이면 AlertDescription = korTravelGeoError.
    await expect(page.getByText("feature 작성 실패")).toBeVisible();
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: "/v2/geocode 실패 (HTTP 502)" }),
    ).toBeVisible();
  });
});
