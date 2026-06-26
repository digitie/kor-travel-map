import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(admin-ops.spec
// idiom). 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약
// drift 감지. 본 spec은 features.spec(스모크)이 다루지 않는 *route-mocked 깊이*만 추가한다:
//   - map<->table 탭 토글 + 두 뷰가 동일 bbox 데이터를 공유(featureViewMode Zustand)
//   - table row 클릭 선택 → 지도 탭에서 상세 패널(marker-click 대체 경로)
//   - bbox list 쿼리 5xx → destructive Alert(role=alert) + 상태 배지
//   - count=0 명시 empty 상태(헤더 배지 + 테이블 빈 메시지)
//   - 초기 bbox fetch 1회 + kind 필터 토글 시 kind= 파라미터로 결정적 refetch
type FeatureSummary = components["schemas"]["FeatureSummary"];
type FeaturesInBboxResponse = components["schemas"]["FeaturesInBboxResponse"];
type Meta = components["schemas"]["Meta"];
type FeatureDetailResponse = components["schemas"]["FeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  components["schemas"]["FeatureDetailEnvelopeResponse"];
type FeatureWeatherResponse = components["schemas"]["FeatureWeatherResponse"];
type FeaturePriceResponse = components["schemas"]["FeaturePriceResponse"];

const FEATURE_ID = "mock-provider::mock-dataset::seoul-place-1";
const MOCK_NAME = "Seoul Mock Place";
const MOCK_UPDATED_AT = "2026-06-16T00:00:00.000Z";

function makeMeta(overrides: Partial<Meta> = {}): Meta {
  return {
    cluster: null,
    duration_ms: 1,
    page: null,
    request_id: "e2e-features-map",
    ...overrides,
  };
}

function makeFeatureSummary(
  overrides: Partial<FeatureSummary> = {},
): FeatureSummary {
  return {
    category: "01070300",
    feature_id: FEATURE_ID,
    kind: "place",
    lat: 37.5665,
    lon: 126.978,
    marker_color: "P-01",
    marker_icon: "marker",
    name: MOCK_NAME,
    status: "active",
    ...overrides,
  };
}

function makeFeaturesInBboxResponse(
  items: FeatureSummary[],
): FeaturesInBboxResponse {
  return { data: { items }, meta: makeMeta() };
}

async function setMapZoom(page: Page, zoom: number) {
  await page.evaluate((nextZoom) => {
    const container = document.querySelector(
      '[data-testid="map-canvas-container"]',
    ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
    container?._maplibreMap?.jumpTo({ zoom: nextZoom });
  }, zoom);
}

function makeFeatureDetail(
  overrides: Partial<FeatureDetailResponse> = {},
): FeatureDetailResponse {
  return {
    address: { road: "세종대로 110" },
    category: "01070300",
    detail: { source: "e2e-mock" },
    feature_id: FEATURE_ID,
    kind: "place",
    lat: 37.5665,
    lon: 126.978,
    name: MOCK_NAME,
    status: "active",
    updated_at: MOCK_UPDATED_AT,
    urls: {},
    ...overrides,
  };
}

function makeFeatureDetailEnvelope(
  detail: FeatureDetailResponse = makeFeatureDetail(),
): FeatureDetailEnvelopeResponse {
  return { data: detail, meta: makeMeta({ request_id: "e2e-feature-detail" }) };
}

function makeFeatureWeatherResponse(): FeatureWeatherResponse {
  return {
    data: {
      asof: null,
      feature_id: FEATURE_ID,
      is_stale: false,
      latest_at: null,
      metrics: [],
      source_styles: [],
    },
    meta: makeMeta({ request_id: "e2e-feature-weather" }),
  };
}

function makeFeaturePriceResponse(): FeaturePriceResponse {
  const point = {
    observed_at: "2026-06-26T06:18:00.000Z",
    price_domain: "opinet_gas_station",
    product_key: "gasoline",
    product_name: "휘발유",
    provider: "python-opinet-api",
    source_product_key: "B027",
    source_product_name: "휘발유",
    unit: "KRW/L",
    value_number: 1820,
  };
  return {
    data: {
      asof: null,
      current: [point],
      feature_id: FEATURE_ID,
      history: [point],
      is_stale: false,
      latest_at: "2026-06-26T06:18:00.000Z",
    },
    meta: makeMeta({ request_id: "e2e-feature-price" }),
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

interface FeaturesRouteOptions {
  /** 200 list 응답으로 돌려줄 feature 목록. */
  items?: FeatureSummary[];
  /** detail 응답 override. price feature 선택 등 상세 kind가 list와 달라지지 않게 한다. */
  detail?: FeatureDetailResponse;
  /** price card 응답 override. */
  price?: FeaturePriceResponse;
  /** list 쿼리에 강제할 HTTP status (500 등 에러 표면 검증용). */
  listStatus?: number;
  /** 5xx 본문은 envelope이 아니라 plain text(ApiClientError가 response.text() 사용). */
  listErrorBody?: string;
}

/**
 * `**​/v1/features**` 글로브는 list(`/v1/features`), detail(`/v1/features/{id}`),
 * weather(`/v1/features/{id}/weather`)를 모두 잡는다 — 단일 핸들러에서 pathname으로
 * 분기한다. RSC/document 요청은 route.continue()(admin-ops idiom).
 * 반환된 카운터로 요청 shape를 expect.poll 단언한다.
 */
async function mockFeatureRoutes(page: Page, options: FeaturesRouteOptions = {}) {
  const items = options.items ?? [makeFeatureSummary()];
  const requests = {
    list: 0,
    detail: 0,
    price: 0,
    weather: 0,
    /** list 쿼리마다 url.searchParams.getAll("kind") 기록 — 마지막 요청 shape 검증용. */
    listKinds: [] as string[][],
    /** route/area geometry 요청 여부 기록. */
    listIncludeGeometry: [] as string[],
  };

  await page.route("**/v1/features**", async (route) => {
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

    // price: `/v1/features/{id}/price`
    if (url.pathname.endsWith("/price")) {
      requests.price += 1;
      await fulfillJson(route, options.price ?? makeFeaturePriceResponse());
      return;
    }

    // weather: `/v1/features/{id}/weather`
    if (url.pathname.endsWith("/weather")) {
      requests.weather += 1;
      await fulfillJson(route, makeFeatureWeatherResponse());
      return;
    }

    // list: `/v1/features` 또는 BFF `/api/proxy/v1/features` (정확히)
    if (
      url.pathname === "/v1/features" ||
      url.pathname === "/api/proxy/v1/features"
    ) {
      requests.list += 1;
      requests.listKinds.push(url.searchParams.getAll("kind"));
      requests.listIncludeGeometry.push(
        url.searchParams.get("include_geometry") ?? "",
      );
      if (options.listStatus && options.listStatus >= 400) {
        await route.fulfill({
          body: options.listErrorBody ?? "internal error",
          contentType: "text/plain",
          status: options.listStatus,
        });
        return;
      }
      await fulfillJson(route, makeFeaturesInBboxResponse(items));
      return;
    }

    // detail: `/v1/features/{id}`
    if (
      url.pathname.startsWith("/v1/features/") ||
      url.pathname.startsWith("/api/proxy/v1/features/")
    ) {
      requests.detail += 1;
      await fulfillJson(
        route,
        makeFeatureDetailEnvelope(options.detail ?? makeFeatureDetail()),
      );
      return;
    }

    throw new Error(`Unhandled features route: ${request.method()} ${url}`);
  });

  return requests;
}

test.describe("/features map interactions", () => {
  test("map<->table 탭 토글 — 두 뷰가 같은 bbox 데이터를 공유", async ({ page }) => {
    await mockFeatureRoutes(page);

    await page.goto("/features");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();

    const mapTab = page.getByRole("tab", { name: "지도" });
    const tableTab = page.getByRole("tab", { name: "테이블" });

    // 기본 진입은 '지도'(featureViewMode 기본값 'map'). features.spec가 map=selected를
    // 단언하므로 여기서는 table 탭이 아직 비선택인 것만 확인 후 토글로 진입한다.
    await expect(tableTab).toHaveAttribute("aria-selected", "false");

    // '테이블' 탭으로 전환 → base-ui Tabs aria-selected 토글(setFeatureViewMode 반영).
    await tableTab.click();
    await expect(tableTab).toHaveAttribute("aria-selected", "true");
    await expect(mapTab).toHaveAttribute("aria-selected", "false");

    // 가상화 테이블 → 명시 role=table + aria-label로 한정(native role 죽음). 4종 columnheader.
    const table = page.getByRole("table", { name: "이름순 feature" });
    for (const column of ["name", "kind", "status", "coord"]) {
      await expect(
        table.getByRole("columnheader", { name: column }),
      ).toBeVisible();
    }
    // map 뷰와 동일 queryKey(list 쿼리)가 table에도 동일 데이터를 공급함을 확인.
    await expect(table.getByRole("cell", { name: MOCK_NAME })).toBeVisible();

    // 다시 '지도' 탭 → aria-selected 토글 복귀 + map-canvas-container attached.
    // (NOTE: URL ?view= 동기화는 소스에 없음 — featureViewMode는 Zustand 전용.)
    await mapTab.click();
    await expect(mapTab).toHaveAttribute("aria-selected", "true");
    await expect(tableTab).toHaveAttribute("aria-selected", "false");
    await expect(page.getByTestId("map-canvas-container")).toBeAttached();
  });

  test("route/area geometry — 선·면과 이름 라벨을 지도에 표시", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page, {
      items: [
        makeFeatureSummary({
          feature_id: "mock-route-1",
          kind: "route",
          name: "Seoul Trail",
          geometry: {
            type: "LineString",
            coordinates: [
              [126.97, 37.56],
              [126.99, 37.58],
            ],
          },
          marker_color: "P-06",
        }),
        makeFeatureSummary({
          area_square_meters: 1_234_567,
          feature_id: "mock-area-1",
          kind: "area",
          name: "Mock Park Area",
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [126.96, 37.55],
                [127.0, 37.55],
                [127.0, 37.59],
                [126.96, 37.59],
                [126.96, 37.55],
              ],
            ],
          },
          marker_color: "P-12",
        }),
      ],
    });

    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);
    expect(requests.listIncludeGeometry[0]).toBe("false");

    await setMapZoom(page, 14);
    await expect.poll(() => requests.listIncludeGeometry).toContain("true");
    await expect(page.getByText("Seoul Trail")).toBeVisible();
    await expect(page.getByText("Mock Park Area - 1.2 km2")).toBeVisible();

    // 라벨 텍스트만이 아니라 실제 GL 렌더 상태를 단언한다(#502 M5): geometry source가
    // route+area 2개 feature를 보유하고, route-line/area-fill 레이어가 존재하는지
    // map 인스턴스(컨테이너 DOM에 매달린 e2e 훅)로 확인한다.
    const GEOMETRY_SOURCE_ID = "kor-feature-geometries";
    const ROUTE_LINE_LAYER_ID = `${GEOMETRY_SOURCE_ID}-route-line`;
    const AREA_FILL_LAYER_ID = `${GEOMETRY_SOURCE_ID}-area-fill`;

    const evalArgs = {
      sourceId: GEOMETRY_SOURCE_ID,
      routeLayerId: ROUTE_LINE_LAYER_ID,
      areaLayerId: AREA_FILL_LAYER_ID,
    };

    await expect
      .poll(async () =>
        page.evaluate(({ sourceId, routeLayerId, areaLayerId }) => {
          const container = document.querySelector(
            '[data-testid="map-canvas-container"]',
          ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
          const map = container?._maplibreMap;
          if (!map) return null;
          const sourceFeatures = map.querySourceFeatures(sourceId);
          return {
            hasRouteLayer: Boolean(map.getLayer(routeLayerId)),
            hasAreaLayer: Boolean(map.getLayer(areaLayerId)),
            sourceLoaded: Boolean(map.getSource(sourceId)),
            featureCount: sourceFeatures.length,
          };
        }, evalArgs),
      )
      .toEqual({
        hasRouteLayer: true,
        hasAreaLayer: true,
        sourceLoaded: true,
        featureCount: 2,
      });
  });

  test("area geometry — 낮은 줌에서는 centroid marker를 cluster로 표시", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page, {
      items: Array.from({ length: 4 }, (_, index) =>
        makeFeatureSummary({
          area_square_meters: 1_234_567 + index,
          feature_id: `mock-area-${index + 1}`,
          kind: "area",
          lat: 37.5665 + index * 0.001,
          lon: 126.978 + index * 0.001,
          name: `Mock Park Area ${index + 1}`,
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [126.96 + index * 0.001, 37.55],
                [127.0 + index * 0.001, 37.55],
                [127.0 + index * 0.001, 37.59],
                [126.96 + index * 0.001, 37.59],
                [126.96 + index * 0.001, 37.55],
              ],
            ],
          },
          marker_color: "P-12",
        }),
      ),
    });

    await page.goto("/features");

    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);
    expect(requests.listIncludeGeometry[0]).toBe("false");
    await expect(
      page.getByRole("button", { name: /feature 클러스터 4건/ }),
    ).toBeVisible();
    await expect(page.getByText("Mock Park Area 1 - 1.2 km2")).toBeHidden();
  });

  test("table row 선택 → 지도 탭 상세 패널(marker-click 대체 경로)", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");

    // FeatureDetailPanel은 TabsContent value='map' 안에서만 렌더된다 → 테이블에서 선택한 뒤
    // '지도' 탭으로 전환해야 패널이 보인다(이 순서를 그대로 따른다).
    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table", { name: "이름순 feature" });
    const row = table.getByRole("row", { name: new RegExp(MOCK_NAME) });
    await expect(row).toBeVisible();

    // name 셀의 Link는 stopPropagation이라 row onRowClick을 막는다 → 비-Link 영역(status 셀)을
    // 클릭해 setSelectedFeatureId를 발화시킨다.
    await row.getByRole("cell", { name: "active" }).click();

    // '지도' 탭으로 전환 → 상세 패널 노출. CardDescription에 선택 feature_id(mono) 표시.
    await page.getByRole("tab", { name: "지도" }).click();
    const panel = page.getByTestId("feature-detail-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("선택 Feature")).toBeVisible();
    await expect(panel.getByText(FEATURE_ID)).toBeVisible();

    // useFeatureDetail → /v1/features/{id} mock 반영(상세 data name/badge kind·status·category).
    await expect.poll(() => requests.detail).toBeGreaterThanOrEqual(1);
    await expect(
      panel.getByRole("heading", { level: 2, name: MOCK_NAME }),
    ).toBeVisible();
    await expect(panel.getByText("place", { exact: true })).toBeVisible();
    await expect(panel.getByText("active", { exact: true })).toBeVisible();
    await expect(panel.getByRole("link", { name: "상세 열기" })).toBeVisible();

    // '닫기' → setSelectedFeatureId(null) → 패널 hidden.
    // (NOTE: marker(WebGL canvas) 클릭 기반 선택은 의도적으로 out-of-scope — uncertainties.)
    await panel.getByRole("button", { name: "닫기" }).click();
    await expect(page.getByTestId("feature-detail-panel")).toBeHidden();
  });

  test("price feature — 마커 현재 가격과 우측 price 패널 표시", async ({
    page,
  }) => {
    const priceSummary = [
      {
        observed_at: "2026-06-26T06:18:00.000Z",
        price_domain: "opinet_gas_station",
        product_key: "gasoline",
        product_name: "휘발유",
        provider: "python-opinet-api",
        source_product_key: "B027",
        source_product_name: "휘발유",
        unit: "KRW/L",
        value_number: 1820,
      },
      {
        observed_at: "2026-06-26T06:18:00.000Z",
        price_domain: "opinet_gas_station",
        product_key: "diesel",
        product_name: "경유",
        provider: "python-opinet-api",
        source_product_key: "D047",
        source_product_name: "경유",
        unit: "KRW/L",
        value_number: 1650,
      },
      {
        observed_at: "2026-06-26T06:18:00.000Z",
        price_domain: "opinet_gas_station",
        product_key: "premium_gasoline",
        product_name: "고급휘발유",
        provider: "python-opinet-api",
        source_product_key: "B034",
        source_product_name: "고급휘발유",
        unit: "KRW/L",
        value_number: 2050,
      },
    ];
    const requests = await mockFeatureRoutes(page, {
      detail: makeFeatureDetail({
        kind: "price",
        name: "서울주유소 유가",
      }),
      items: [
        makeFeatureSummary({
          kind: "price",
          marker_icon: "fuel",
          name: "서울주유소 유가",
          price_summary: priceSummary,
        }),
      ],
    });

    await page.goto("/features");

    await expect(page.getByText("휘 1,820")).toBeVisible();
    await expect(page.getByText("경 1,650")).toBeVisible();
    await expect(page.getByText("고 2,050")).toBeVisible();

    await page.getByRole("button", { name: /서울주유소 유가.*휘 1,820/ }).click();
    const panel = page.getByTestId("feature-detail-panel");
    await expect(panel).toBeVisible();
    await expect.poll(() => requests.price).toBeGreaterThanOrEqual(1);
    await expect(panel.getByTestId("feature-price-panel")).toBeVisible();
    await expect(panel.getByText("휘발유 1,820")).toBeVisible();
    await expect(panel.getByText("History")).toBeVisible();
  });

  test("bbox list 5xx → destructive Alert(role=alert) error surface", async ({
    page,
  }) => {
    await mockFeatureRoutes(page, {
      listStatus: 500,
      listErrorBody: "internal error",
    });

    await page.goto("/features");

    // list 500 → featuresQuery.isError → 헤더 위 variant='destructive' Alert(role=alert).
    // (KNOWN GOTCHA: destructive만 role=alert; default Alert는 role=status.)
    // '지도 호출 실패' 텍스트는 헤더 status Badge에도 나오므로 alert는 filter로 한정한다.
    const errorAlert = page
      .getByRole("alert")
      .filter({ hasText: "feature 호출 실패" });
    await expect(errorAlert).toBeVisible();
    // AlertDescription = error.message(HTTP 500 텍스트 포함).
    await expect(errorAlert).toContainText("HTTP 500");

    // 헤더 status 영역에도 동일 문구가 표기됨을 상태 텍스트 locator로 확인(스모크 idiom).
    await expect(
      page.locator(
        "text=/건 표시|feature 로딩 중|지도 로딩 중|feature 호출 실패/",
      ).first(),
    ).toBeVisible();
  });

  test("count=0 — 헤더 '0건 표시' + 테이블 빈 메시지", async ({ page }) => {
    await mockFeatureRoutes(page, { items: [] });

    await page.goto("/features");

    // list가 items=[]로 200 → 헤더 status Badge가 '0건 표시'(items.length ?? 0).
    await expect(page.getByText("0건 표시")).toBeVisible();

    // '테이블' 탭 → DataTable이 emptyMessage='표시할 feature가 없습니다.' 렌더.
    await page.getByRole("tab", { name: "테이블" }).click();
    await expect(
      page.getByRole("table", { name: "이름순 feature" }),
    ).toBeVisible();
    await expect(page.getByText("표시할 feature가 없습니다.")).toBeVisible();
  });

  test("초기 bbox fetch 1회 + kind 필터 토글 시 kind= 파라미터로 refetch", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");

    // map 'load' 이벤트가 bbox를 세팅 → /v1/features 요청이 최소 1회 발생.
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);
    // 첫 요청에는 bbox 좌표가 있고 kind 파라미터는 없음.
    expect(requests.listKinds[0]).toEqual([]);

    const filter = page.getByTestId("kind-filter");
    const placeBtn = filter.getByRole("button", { name: "place", exact: true });
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");

    // 'place' 토글 → activeFeatureKinds 변경 → queryKey 변경 → 새 요청에 kind=place 포함.
    await placeBtn.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(() => requests.listKinds.at(-1))
      .toEqual(["place"]);

    // '초기화' → clearFeatureKinds. KNOWN GOTCHA: 동일 byte 쿼리("")는 react-query
    // staleTime(30s) 캐시로 새 네트워크 호출이 없을 수 있으므로 refetch count가 아니라
    // aria-pressed='false' + 초기화 버튼 hidden(UI 상태)으로 단언한다.
    const reset = filter.getByRole("button", { name: "초기화" });
    await reset.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");
    await expect(reset).toBeHidden();
  });
});
