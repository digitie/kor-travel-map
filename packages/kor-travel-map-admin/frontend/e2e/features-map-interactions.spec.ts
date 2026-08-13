import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";
import { expectDetailPanelAboveScaleControl } from "./map-control-assertions";
import { mockOpsDatasetCatalog } from "./ops-dataset-catalog-mock";
import { installInertOpsLiveWebSocket } from "./ws-isolation";

// 손으로 쓴 record shape 대신 **생성된 OpenAPI 스키마**에 바인딩한다(admin-ops.spec
// idiom). 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로 컴파일 실패 → mock-실계약
// drift 감지. 본 spec은 features.spec(스모크)이 다루지 않는 *route-mocked 깊이*만 추가한다:
//   - map<->table 탭 토글 + 두 뷰가 동일 bbox 데이터를 공유(featureViewMode Zustand)
//   - table row 클릭 선택 → 지도 탭에서 상세 패널(marker-click 대체 경로)
//   - bbox list 쿼리 5xx → destructive Alert(role=alert) + 상태 배지
//   - count=0 명시 empty 상태(헤더 배지 + 테이블 빈 메시지)
//   - 초기 bbox fetch 1회 + kind 필터 토글 시 kind= 파라미터로 결정적 refetch
type AdminFeatureMapItem = components["schemas"]["AdminFeatureMapItem"];
type AdminFeaturesInBoundsResponse =
  components["schemas"]["AdminFeaturesInBoundsResponse"];
type Meta = components["schemas"]["Meta"];
type FeatureWeatherResponse = components["schemas"]["FeatureWeatherResponse"];
type FeaturePriceResponse = components["schemas"]["FeaturePriceResponse"];
type AdminFeatureDetailFeatureRecord =
  components["schemas"]["AdminFeatureDetailFeatureRecord"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type AdminFeatureDetailSourceRecord =
  components["schemas"]["AdminFeatureDetailSourceRecord"];
type CurationItemView = components["schemas"]["AdminCurationItemView"];

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

function makeAdminFeatureMapItem(
  overrides: Partial<AdminFeatureMapItem> = {},
): AdminFeatureMapItem {
  return {
    category: "01070300",
    feature_id: FEATURE_ID,
    kind: "place",
    lat: 37.5665,
    lon: 126.978,
    marker_color: "P-01",
    marker_icon: "marker",
    name: MOCK_NAME,
    lifecycle_state: "active",
    publication_state: "published",
    quality_state: "valid",
    ...overrides,
  };
}

function makeAdminFeaturesInBoundsResponse(
  items: AdminFeatureMapItem[],
  clustered = false,
): AdminFeaturesInBoundsResponse {
  return {
    data: {
      clusters:
        clustered && items.length > 0
          ? [
              {
                cluster_key: "1100000000",
                feature_count: items.length,
                lat: items[0]?.lat ?? 37.5665,
                lon: items[0]?.lon ?? 126.978,
              },
            ]
          : [],
      coverage: {
        limit: 2000,
        returned: clustered && items.length > 0 ? 1 : items.length,
      },
      items: clustered ? [] : items,
      mode: clustered ? "clusters" : "items",
      truncated: false,
    },
    meta: makeMeta({
      cluster: { cluster_unit: "sido", drill_down_unit: "sigungu" },
    }),
  };
}

async function setMapZoom(page: Page, zoom: number, center?: [number, number]) {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const container = document.querySelector(
            '[data-testid="map-canvas-container"]',
          ) as
            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
            | null;
          return Boolean(container?._maplibreMap);
        }),
      { timeout: 20_000 },
    )
    .toBe(true);
  await page.evaluate(
    ({ nextZoom, nextCenter }) => {
      const container = document.querySelector(
        '[data-testid="map-canvas-container"]',
      ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
      container?._maplibreMap?.jumpTo({
        ...(nextCenter ? { center: nextCenter } : {}),
        zoom: nextZoom,
      });
    },
    { nextCenter: center, nextZoom: zoom },
  );
}

function makeAdminSource(
  overrides: Partial<AdminFeatureDetailSourceRecord> = {},
): AdminFeatureDetailSourceRecord {
  return {
    confidence: 0.97,
    dataset_key: "admin-dataset",
    expires_at: null,
    fetched_at: MOCK_UPDATED_AT,
    imported_at: MOCK_UPDATED_AT,
    observed_at: MOCK_UPDATED_AT,
    linked_at: MOCK_UPDATED_AT,
    match_method: "natural_key",
    provider: "admin-provider",
    raw_data: { admin_source_marker: "admin-source-visible" },
    raw_payload_hash: "admin-map-source-hash",
    source_entity_id: "admin-map-entity",
    source_entity_key: "admin-provider::admin-dataset::admin-map-entity",
    source_entity_type: "place",
    source_record_key: "admin-provider::admin-dataset::admin-map-record",
    source_role: "enrichment",
    ...overrides,
  };
}

function makeAdminCuration(
  overrides: Partial<CurationItemView> = {},
): CurationItemView {
  return {
    accepted_link_decision_id: "admin-map-decision-id",
    address: { road: "세종대로 110" },
    address_hint: "서울 중구",
    archived_at: null,
    collection_id: "admin-map-collection-id",
    collection_key: "admin-map-only-collection",
    created_at: MOCK_UPDATED_AT,
    created_by: "e2e-admin",
    curation_item_id: "admin-map-curation-item",
    curation_relation: "primary_stop",
    current_import_row_id: "admin-map-import-row-id",
    dataset_key: "admin-dataset",
    edition_key: "2026",
    external_item_id: "admin-map-official-item",
    external_component_id: "primary",
    feature_category: "01070300",
    feature_id: FEATURE_ID,
    feature_kind: "place",
    feature_name: MOCK_NAME,
    item_summary: "admin-only map membership summary",
    item_title: "Admin-only map membership",
    lat: 37.5665,
    link_actor: "e2e-admin",
    link_decided_at: MOCK_UPDATED_AT,
    link_evidence: { source: "e2e-explicit" },
    link_match_basis: "csv_explicit_feature_id",
    link_resolver_version: "curation-link-v1",
    lon: 126.978,
    metadata: { visibility: "admin_only" },
    place_name: MOCK_NAME,
    provider: "admin-provider",
    provider_dataset_id: 703,
    reuse_policy: "manual_review",
    sort_order: 9,
    source_name: "Admin map source",
    source_present: true,
    source_record_key: "admin-provider::admin-dataset::admin-map-record",
    source_url: "https://example.test/admin-map-source",
    status: "candidate",
    theme_group: "admin map group",
    theme_name: "Admin map theme",
    theme_slug: "admin-map-theme",
    title: "Admin-only map collection",
    updated_at: MOCK_UPDATED_AT,
    updated_by: "e2e-admin",
    ...overrides,
  };
}

function makeAdminFeatureDetailResponse(
  featureOverrides: Partial<AdminFeatureDetailFeatureRecord> = {},
): AdminFeatureDetailResponse {
  return {
    data: {
      change_requests: [],
      curations: [makeAdminCuration()],
      feature: {
        address: { road: "세종대로 110" },
        category: "01070300",
        created_at: MOCK_UPDATED_AT,
        data_origin: "provider",
        data_version: 1,
        detail: { source: "e2e-admin-mock" },
        feature_id: FEATURE_ID,
        kind: "place",
        lat: 37.5665,
        lon: 126.978,
        name: MOCK_NAME,
        raw_refs: [],
        row_revision: 1,
        lifecycle_state: "active",
        publication_state: "published",
        quality_state: "valid",
        updated_at: MOCK_UPDATED_AT,
        urls: {},
        ...featureOverrides,
      },
      files: [],
      issues: [],
      overrides: [],
      sources: [makeAdminSource()],
      state_transitions: [],
      versions: [],
    },
    meta: makeMeta({ request_id: "e2e-admin-feature-detail" }),
  };
}

function makeFeatureWeatherResponse(): FeatureWeatherResponse {
  return {
    data: {
      feature_id: FEATURE_ID,
      is_stale: false,
      latest_at: null,
      metrics: [],
      refresh_after: null,
      selected_at: null,
      source_styles: [],
    },
    meta: makeMeta({ request_id: "e2e-feature-weather" }),
  };
}

function makeFeaturePriceResponse(): FeaturePriceResponse {
  const point = {
    dataset_display_name: "OpiNet 유가",
    dataset_key: "opinet_gas_station",
    known_at: "2026-06-26T06:23:00.000Z",
    observed_at: "2026-06-26T06:18:00.000Z",
    price_domain: "opinet_gas_station",
    product_key: "gasoline",
    product_name: "휘발유",
    provider: "python-opinet-api",
    provider_dataset_id: 201,
    source_product_key: "B027",
    source_product_name: "휘발유",
    unit: "KRW/L",
    value_number: 1820,
  };
  return {
    data: {
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
  items?: AdminFeatureMapItem[];
  /** price card 응답 override. */
  price?: FeaturePriceResponse;
  /** list 쿼리에 강제할 HTTP status (500 등 에러 표면 검증용). */
  listStatus?: number;
  /** 5xx 본문은 envelope이 아니라 plain text(ApiClientError가 response.text() 사용). */
  listErrorBody?: string;
  /** admin 단건 상세 응답 override. */
  adminDetail?: AdminFeatureDetailResponse;
  /** admin 단건 상세 실패 상태. */
  adminDetailStatus?: number;
}

/**
 * Admin 지도·상세·weather·price가 쓰는 `**​/v1/admin/features/**` 요청을 단일
 * 핸들러에서 pathname으로 분기한다. RSC/document 요청은 route.continue()
 * (admin-ops idiom).
 * 반환된 카운터로 요청 shape를 expect.poll 단언한다.
 */
async function mockFeatureRoutes(
  page: Page,
  options: FeaturesRouteOptions = {},
) {
  await mockOpsDatasetCatalog(page);
  const items = options.items ?? [makeAdminFeatureMapItem()];
  const requests = {
    list: 0,
    cluster: 0,
    adminDetail: 0,
    price: 0,
    weather: 0,
    /** list 쿼리마다 url.searchParams.getAll("kind") 기록 — 마지막 요청 shape 검증용. */
    listKinds: [] as string[][],
    /** cluster 쿼리마다 url.searchParams.getAll("kind") 기록 — 저zoom shape 검증용. */
    clusterKinds: [] as string[][],
    /** route/area geometry 요청 여부 기록. */
    listIncludeGeometry: [] as string[],
    /** 직교 상태 축 필터 요청 shape. */
    listLifecycleStates: [] as string[][],
    listPublicationStates: [] as string[][],
    listQualityStates: [] as string[][],
    clusterLifecycleStates: [] as string[][],
    clusterPublicationStates: [] as string[][],
    clusterQualityStates: [] as string[][],
  };

  await page.route("**/v1/admin/features/**", async (route) => {
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

    // price: `/v1/admin/features/{id}/price`
    if (url.pathname.endsWith("/price")) {
      requests.price += 1;
      await fulfillJson(route, options.price ?? makeFeaturePriceResponse());
      return;
    }

    // weather: `/v1/admin/features/{id}/weather`
    if (url.pathname.endsWith("/weather")) {
      requests.weather += 1;
      await fulfillJson(route, makeFeatureWeatherResponse());
      return;
    }

    // item/cluster: `/v1/admin/features/in-bounds` 또는 BFF proxy.
    if (
      url.pathname === "/v1/admin/features/in-bounds" ||
      url.pathname === "/api/proxy/v1/admin/features/in-bounds"
    ) {
      // 서버 규칙 미러(_resolve_admin_cluster_unit): zoom 부재 또는 >=14 → items,
      // zoom<=13 → cluster. (client가 zoom을 items 모드에서도 항상 보내므로
      // 존재 여부만으로는 더 이상 구분할 수 없다.)
      const zoomParam = url.searchParams.get("zoom");
      const clustered = zoomParam !== null && Number(zoomParam) <= 13;
      if (clustered) {
        requests.cluster += 1;
        requests.clusterKinds.push(url.searchParams.getAll("kind"));
        requests.clusterLifecycleStates.push(
          url.searchParams.getAll("lifecycle_state"),
        );
        requests.clusterPublicationStates.push(
          url.searchParams.getAll("publication_state"),
        );
        requests.clusterQualityStates.push(
          url.searchParams.getAll("quality_state"),
        );
      } else {
        requests.list += 1;
        requests.listKinds.push(url.searchParams.getAll("kind"));
        requests.listLifecycleStates.push(
          url.searchParams.getAll("lifecycle_state"),
        );
        requests.listPublicationStates.push(
          url.searchParams.getAll("publication_state"),
        );
        requests.listQualityStates.push(
          url.searchParams.getAll("quality_state"),
        );
        requests.listIncludeGeometry.push(
          url.searchParams.get("include_geometry") ?? "",
        );
      }
      if (options.listStatus && options.listStatus >= 400) {
        await route.fulfill({
          body: options.listErrorBody ?? "internal error",
          contentType: "text/plain",
          status: options.listStatus,
        });
        return;
      }
      await fulfillJson(
        route,
        makeAdminFeaturesInBoundsResponse(items, clustered),
      );
      return;
    }

    // detail: `/v1/admin/features/{id}`
    if (
      url.pathname.startsWith("/v1/admin/features/") ||
      url.pathname.startsWith("/api/proxy/v1/admin/features/")
    ) {
      requests.adminDetail += 1;
      if (options.adminDetailStatus && options.adminDetailStatus >= 400) {
        await fulfillJson(
          route,
          { detail: "admin feature 상세 실패" },
          options.adminDetailStatus,
        );
        return;
      }
      await fulfillJson(
        route,
        options.adminDetail ?? makeAdminFeatureDetailResponse(),
      );
      return;
    }

    throw new Error(
      `Unhandled admin features route: ${request.method()} ${url}`,
    );
  });

  return requests;
}

test.describe("/features map interactions", () => {
  test.beforeEach(async ({ page }) => {
    await installInertOpsLiveWebSocket(page);
  });

  test("map<->table 탭 토글 — 두 뷰가 같은 bbox 데이터를 공유", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible();
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await setMapZoom(page, 14, [126.978, 37.5665]);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);

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
    for (const column of ["이름", "종류", "상태", "좌표"]) {
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

  test("고zoom 기본 weather/notice 조회는 geometry SQL을 요청하지 않는다", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");
    await setMapZoom(page, 14);

    await expect.poll(() => requests.listIncludeGeometry.at(-1)).toBe("false");

    // 빈 kind set은 API에서 "전체 kind"이므로 route/area geometry도 다시 포함한다.
    const kindFilter = page.getByTestId("kind-filter");
    await kindFilter
      .getByRole("button", { name: "weather", exact: true })
      .click();
    await kindFilter
      .getByRole("button", { name: "notice", exact: true })
      .click();
    await expect.poll(() => requests.listIncludeGeometry.at(-1)).toBe("true");
  });

  test("VWorld raster sourcedata를 무시하고 source tile 중복도 marker 전에 제거한다", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");
    await setMapZoom(page, 16, [126.978, 37.5665]);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);

    const sourceId = "kor-feature-clusters";
    await expect
      .poll(() =>
        page.evaluate((id) => {
          const container = document.querySelector(
            '[data-testid="map-canvas-container"]',
          ) as
            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
            | null;
          const map = container?._maplibreMap;
          return Boolean(map?.getSource(id) && map.isSourceLoaded(id));
        }, sourceId),
      )
      .toBe(true);
    // isSourceLoaded는 빈 이전 source에도 true일 수 있다. 실제 worker tile에 현재
    // feature가 반영되고 idle fallback이 DOM marker까지 만든 뒤 이벤트 계측을 시작한다.
    await expect
      .poll(() =>
        page.evaluate((id) => {
          const container = document.querySelector(
            '[data-testid="map-canvas-container"]',
          ) as
            | (HTMLElement & {
                _maplibreMap?: import("maplibre-gl").Map;
              })
            | null;
          return container?._maplibreMap?.querySourceFeatures(id).length ?? 0;
        }, sourceId),
      )
      .toBeGreaterThan(0);
    await expect(
      page.getByRole("button", { name: new RegExp(MOCK_NAME) }),
    ).toBeVisible();
    // production build의 VWorld raster worker는 feature marker가 보인 뒤에도 타일을
    // 마저 읽을 수 있다. 이때 늦은 map idle updater가 아래 인위적 sourcedata 계측
    // 창에 섞이지 않도록 실제 tile 안정화를 기다린다.
    await expect
      .poll(() =>
        page.evaluate(() => {
          const container = document.querySelector(
            '[data-testid="map-canvas-container"]',
          ) as
            | (HTMLElement & {
                _maplibreMap?: import("maplibre-gl").Map;
              })
            | null;
          const map = container?._maplibreMap;
          return Boolean(map?.areTilesLoaded() && !map.isMoving());
        }),
      )
      .toBe(true);

    const calls = await page.evaluate(async (id) => {
      const container = document.querySelector(
        '[data-testid="map-canvas-container"]',
      ) as (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map }) | null;
      if (!container?._maplibreMap)
        throw new Error("maplibre map is not ready");
      const map = container._maplibreMap;

      type InstrumentedMap = {
        fire: (type: string, properties: Record<string, unknown>) => unknown;
        querySourceFeatures: (
          sourceId: string,
        ) => ReturnType<typeof map.querySourceFeatures>;
      };
      const instrumentedMap = map as unknown as InstrumentedMap;
      const nextFrame = () =>
        new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      // areTilesLoaded()는 true가 된 직후의 실제 idle event보다 먼저 관측될 수 있다.
      // repaint로 idle cycle을 하나 확정하고 그 handler의 rAF까지 비운 뒤 계측한다.
      await new Promise<void>((resolve, reject) => {
        const onIdle = () => {
          window.clearTimeout(timeout);
          resolve();
        };
        const timeout = window.setTimeout(() => {
          map.off("idle", onIdle);
          reject(new Error("map idle cycle did not settle"));
        }, 5_000);
        map.once("idle", onIdle);
        map.triggerRepaint();
      });
      await nextFrame();
      await nextFrame();
      const originalQuery = instrumentedMap.querySourceFeatures.bind(map);
      let queryCalls = 0;
      let sourceFeatureCount = 0;
      let forceEmptyFeatureSource = false;
      instrumentedMap.querySourceFeatures = (nextSourceId: string) => {
        if (nextSourceId === id) queryCalls += 1;
        const features = originalQuery(nextSourceId);
        if (nextSourceId === id) sourceFeatureCount = features.length;
        if (nextSourceId !== id) return features;
        return forceEmptyFeatureSource ? [] : [...features, ...features];
      };
      const fireSourceData = (
        nextSourceId: string,
        isSourceLoaded: boolean,
      ) => {
        instrumentedMap.fire("sourcedata", {
          dataType: "source",
          isSourceLoaded,
          sourceDataType: "content",
          sourceId: nextSourceId,
        });
      };

      try {
        fireSourceData("vworld-raster-test", true);
        await nextFrame();
        const afterRaster = queryCalls;

        fireSourceData(id, false);
        await nextFrame();
        const afterUnloadedFeatureSource = queryCalls;

        fireSourceData(id, true);
        await nextFrame();
        const duplicateBadgeCount = Array.from(
          container.querySelectorAll('.maplibregl-marker [aria-hidden="true"]'),
        ).filter((element) => element.textContent === "2").length;

        // source worker 교체 중 일시적으로 빈 결과가 보이는 운영 race를 결정적으로
        // 재현한다. loaded sourcedata의 rAF가 marker를 지운 뒤, 안정된 idle에서 실제
        // source를 다시 읽어 DOM marker를 복구해야 한다.
        forceEmptyFeatureSource = true;
        fireSourceData(id, true);
        await nextFrame();
        const afterForcedEmpty = queryCalls;
        const markerCountAfterForcedEmpty = container.querySelectorAll(
          '.maplibregl-marker[role="button"]',
        ).length;

        forceEmptyFeatureSource = false;
        const beforeIdle = queryCalls;
        instrumentedMap.fire("idle", {});
        await nextFrame();
        const afterIdle = queryCalls;
        const markerCountAfterIdle = container.querySelectorAll(
          '.maplibregl-marker[role="button"]',
        ).length;
        return {
          afterForcedEmpty,
          afterIdle,
          afterRaster,
          afterUnloadedFeatureSource,
          beforeIdle,
          duplicateBadgeCount,
          markerCountAfterForcedEmpty,
          markerCountAfterIdle,
          sourceFeatureCount,
        };
      } finally {
        instrumentedMap.querySourceFeatures = originalQuery;
      }
    }, sourceId);

    expect(calls.afterRaster).toBe(0);
    expect(calls.afterUnloadedFeatureSource).toBe(0);
    expect(calls.afterForcedEmpty).toBe(2);
    expect(calls.markerCountAfterForcedEmpty).toBe(0);
    expect(calls.afterIdle - calls.beforeIdle).toBe(1);
    expect(calls.markerCountAfterIdle).toBe(1);
    expect(calls.sourceFeatureCount).toBeGreaterThan(0);
    expect(calls.duplicateBadgeCount).toBe(0);
  });

  test("route/area geometry — 선·면과 이름 라벨을 지도에 표시", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page, {
      items: [
        makeAdminFeatureMapItem({
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
        makeAdminFeatureMapItem({
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
    const kindFilter = page.getByTestId("kind-filter");
    await kindFilter
      .getByRole("button", { name: "route", exact: true })
      .click();
    await kindFilter.getByRole("button", { name: "area", exact: true }).click();

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
          ) as
            | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
            | null;
          const map = container?._maplibreMap;
          if (!map) return null;
          const source = map.getSource(sourceId) as
            | import("maplibre-gl").GeoJSONSource
            | undefined;
          const serializedData = source?.serialize().data;
          const featureCount =
            typeof serializedData === "object" &&
            serializedData !== null &&
            "features" in serializedData &&
            Array.isArray(serializedData.features)
              ? serializedData.features.length
              : map.querySourceFeatures(sourceId).length;
          return {
            hasRouteLayer: Boolean(map.getLayer(routeLayerId)),
            hasAreaLayer: Boolean(map.getLayer(areaLayerId)),
            sourceLoaded: Boolean(source),
            featureCount,
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
        makeAdminFeatureMapItem({
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

    await expect.poll(() => requests.cluster).toBeGreaterThanOrEqual(1);
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
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await setMapZoom(page, 14);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);

    // FeatureDetailPanel은 TabsContent value='map' 안에서만 렌더된다 → 테이블에서 선택한 뒤
    // '지도' 탭으로 전환해야 패널이 보인다(이 순서를 그대로 따른다).
    await page.getByRole("tab", { name: "테이블" }).click();
    const table = page.getByRole("table", { name: "이름순 feature" });
    const row = table.getByRole("row", { name: new RegExp(MOCK_NAME) });
    await expect(row).toBeVisible();

    // name 셀의 Link는 stopPropagation이라 row onRowClick을 막는다 → 비-Link 영역(상태 축 셀)을
    // 클릭해 setSelectedFeatureId를 발화시킨다.
    await row.getByRole("cell", { name: /active/ }).click();

    // '지도' 탭으로 전환 → 상세 패널 노출. CardDescription에 선택 feature_id(mono) 표시.
    await page.getByRole("tab", { name: "지도" }).click();
    const panel = page.getByTestId("feature-detail-panel");
    await expect(panel).toBeVisible();
    await expectDetailPanelAboveScaleControl(page, "feature-detail-panel");
    await expect(panel.getByText("선택 Feature")).toBeVisible();
    await expect(panel.getByText(FEATURE_ID)).toBeVisible();

    // admin 상세 응답으로 name/badge kind·세 상태 축·category를 렌더한다.
    await expect(
      panel.getByRole("heading", { level: 2, name: MOCK_NAME }),
    ).toBeVisible();
    await expect(
      panel
        .locator('[data-slot="badge"]')
        .filter({ hasText: /^place$/ })
        .first(),
    ).toBeVisible();
    await expect(
      panel
        .locator('[data-slot="badge"]')
        .filter({ hasText: /^active$/ })
        .first(),
    ).toBeVisible();
    await expect(panel.getByRole("link", { name: "상세 열기" })).toBeVisible();
    await expect.poll(() => requests.adminDetail).toBeGreaterThanOrEqual(1);
    const associations = panel.getByTestId("feature-associations");
    await expect(
      associations.getByText("Admin-only map collection"),
    ).toBeVisible();
    await expect(
      associations.getByText("admin-provider").first(),
    ).toBeVisible();
    await associations.getByText("membership 전체 정보").click();
    await expect(
      associations.getByText("admin-map-only-collection"),
    ).toBeVisible();

    // '닫기' → setSelectedFeatureId(null) → 패널 hidden.
    // (NOTE: marker(WebGL canvas) 클릭 기반 선택은 의도적으로 out-of-scope — uncertainties.)
    await panel.getByRole("button", { name: "닫기" }).click();
    await expect(page.getByTestId("feature-detail-panel")).toBeHidden();
  });

  test("admin 상세 실패를 source 없음으로 숨기지 않고 오류로 표시", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page, { adminDetailStatus: 500 });

    await page.goto("/features");
    await setMapZoom(page, 14);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);
    await page.getByRole("tab", { name: "테이블" }).click();
    const row = page
      .getByRole("table", { name: "이름순 feature" })
      .getByRole("row", { name: new RegExp(MOCK_NAME) });
    await row.getByRole("cell", { name: "활성" }).click();
    await page.getByRole("tab", { name: "지도" }).click();

    const panel = page.getByTestId("feature-detail-panel");
    await expect(panel.getByText("상세 호출 실패")).toBeVisible();
    await expect(panel).toContainText("HTTP 500");
    await expect(panel.getByText("연결된 큐레이션이 없습니다.")).toHaveCount(0);
  });

  test("price feature — 마커 현재 가격과 우측 price 패널 표시", async ({
    page,
  }) => {
    await page.clock.setFixedTime(new Date("2026-06-26T15:01:00.000Z"));
    const observedToday = "2026-06-26T15:00:00.000Z"; // 6/27 00:00 KST
    const priceSummary = [
      {
        dataset_display_name: "OpiNet 유가",
        dataset_key: "opinet_gas_station",
        known_at: "2026-06-26T06:23:00.000Z",
        observed_at: "2026-06-26T06:18:00.000Z",
        price_domain: "opinet_gas_station",
        product_key: "gasoline",
        product_name: "휘발유",
        provider: "python-opinet-api",
        provider_dataset_id: 201,
        source_product_key: "B027",
        source_product_name: "휘발유",
        unit: "KRW/L",
        value_number: 1820,
      },
      {
        dataset_display_name: "OpiNet 유가",
        dataset_key: "opinet_gas_station",
        known_at: "2026-06-26T15:05:00.000Z",
        observed_at: observedToday,
        price_domain: "opinet_gas_station",
        product_key: "diesel",
        product_name: "경유",
        provider: "python-opinet-api",
        provider_dataset_id: 201,
        source_product_key: "D047",
        source_product_name: "경유",
        unit: "KRW/L",
        value_number: 1650,
      },
      {
        dataset_display_name: "OpiNet 유가",
        dataset_key: "opinet_gas_station",
        known_at: "2026-06-26T06:23:00.000Z",
        observed_at: "2026-06-26T06:18:00.000Z",
        price_domain: "opinet_gas_station",
        product_key: "premium_gasoline",
        product_name: "고급휘발유",
        provider: "python-opinet-api",
        provider_dataset_id: 201,
        source_product_key: "B034",
        source_product_name: "고급휘발유",
        unit: "KRW/L",
        value_number: 2050,
      },
    ];
    const requests = await mockFeatureRoutes(page, {
      adminDetail: makeAdminFeatureDetailResponse({
        kind: "price",
        name: "서울주유소 유가",
      }),
      items: [
        makeAdminFeatureMapItem({
          kind: "price",
          marker_icon: "fuel",
          name: "서울주유소 유가",
          price_summary: priceSummary,
        }),
      ],
      price: {
        data: {
          current: priceSummary,
          feature_id: FEATURE_ID,
          history: priceSummary,
          is_stale: false,
          latest_at: observedToday,
        },
        meta: makeMeta({ request_id: "e2e-feature-price-multi-product" }),
      },
    });

    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await page
      .getByTestId("kind-filter")
      .getByRole("button", { name: "price", exact: true })
      .click();
    await setMapZoom(page, 14, [126.978, 37.5665]);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);

    await expect(page.getByText("휘 1,820")).toBeVisible();
    await expect(page.getByText("경 1,650")).toBeVisible();
    await expect(page.getByText("고 2,050")).toBeVisible();
    const priceMarker = page.getByRole("button", { name: /서울주유소 유가/ });
    await expect(priceMarker).toContainText("휘 1,820 · 과거 6/26");
    await expect(priceMarker).toContainText("경 1,650");
    await expect(priceMarker).not.toContainText("경 1,650 · 과거");
    await expect(priceMarker).toContainText("고 2,050 · 과거 6/26");

    await page
      .getByRole("button", { name: /서울주유소 유가.*휘 1,820/ })
      .click();
    const panel = page.getByTestId("feature-detail-panel");
    await expect(panel).toBeVisible();
    await expect.poll(() => requests.price).toBeGreaterThanOrEqual(1);
    await expect(panel.getByTestId("feature-price-panel")).toBeVisible();
    await expect(
      panel
        .getByTestId("feature-price-panel")
        .getByText("휘발유 · python-opinet-api/opinet_gas_station 1,820", {
          exact: true,
        }),
    ).toBeVisible();
    await expect(panel.getByText("History")).toBeVisible();
    const graph = panel.getByRole("img", { name: "price history graph" });
    await expect(graph).toBeVisible();
    await expect(graph.locator("circle")).toHaveCount(3);
    await expect(graph.locator("polyline")).toHaveCount(0);
  });

  test("bbox list 5xx → destructive Alert(role=alert) error surface", async ({
    page,
  }) => {
    await mockFeatureRoutes(page, {
      listStatus: 500,
      listErrorBody: "internal error",
    });

    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await setMapZoom(page, 14);

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
      page
        .locator(
          "text=/건 표시|feature 로딩 중|지도 로딩 중|feature 호출 실패|클러스터 로딩 중|개 지역/",
        )
        .first(),
    ).toBeVisible();
  });

  test("count=0 — 헤더 '0건 표시' + 테이블 빈 메시지", async ({ page }) => {
    const requests = await mockFeatureRoutes(page, { items: [] });

    await page.goto("/features");
    await expect(page.getByTestId("map-canvas-container")).toBeVisible();
    await setMapZoom(page, 14);
    await expect.poll(() => requests.list).toBeGreaterThanOrEqual(1);

    // list가 items=[]로 200 → 헤더 status Badge가 '0건 표시'(items.length ?? 0).
    await expect(page.getByText("0건 표시").first()).toBeVisible();

    // '테이블' 탭 → DataTable이 emptyMessage='표시할 feature가 없습니다.' 렌더.
    await page.getByRole("tab", { name: "테이블" }).click();
    await expect(
      page.getByRole("table", { name: "이름순 feature" }),
    ).toBeVisible();
    await expect(page.getByText("표시할 feature가 없습니다.")).toBeVisible();
  });

  test("비공개 운영 상태 축 필터 — retired/suppressed 쿼리와 테이블 축을 함께 반영", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page, {
      items: [
        makeAdminFeatureMapItem({
          lifecycle_state: "retired",
          publication_state: "suppressed",
          quality_state: "valid",
        }),
      ],
    });

    await page.goto("/features");
    await page.getByLabel("수명주기 필터").selectOption("retired");
    await page.getByLabel("공개 상태 필터").selectOption("suppressed");
    await setMapZoom(page, 14);

    await expect
      .poll(() => requests.listLifecycleStates.at(-1))
      .toEqual(["retired"]);
    await expect
      .poll(() => requests.listPublicationStates.at(-1))
      .toEqual(["suppressed"]);
    await page.getByRole("tab", { name: "테이블" }).click();
    const row = page
      .getByRole("table", { name: "이름순 feature" })
      .getByRole("row", { name: new RegExp(MOCK_NAME) });
    await expect(row.getByRole("cell", { name: /retired/ })).toBeVisible();
  });

  test("초기 저zoom bbox fetch 1회 + 기본 kind 필터가 cluster 요청에 적용", async ({
    page,
  }) => {
    const requests = await mockFeatureRoutes(page);

    await page.goto("/features");

    // 기본 zoom 6.5는 clusterMode → admin in-bounds 요청이 최소 1회 발생.
    await expect.poll(() => requests.cluster).toBeGreaterThanOrEqual(1);
    // 기본 kind 필터는 weather + notice.
    expect(requests.clusterKinds[0]).toEqual(["weather", "notice"]);

    const filter = page.getByTestId("kind-filter");
    const weatherBtn = filter.getByRole("button", {
      name: "weather",
      exact: true,
    });
    const noticeBtn = filter.getByRole("button", {
      name: "notice",
      exact: true,
    });
    const placeBtn = filter.getByRole("button", { name: "place", exact: true });
    const reset = filter.getByRole("button", { name: "초기화" });
    await expect(weatherBtn).toHaveAttribute("aria-pressed", "true");
    await expect(noticeBtn).toHaveAttribute("aria-pressed", "true");
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");
    await expect(reset).toBeDisabled();

    // 'place' 토글 → activeFeatureKinds 변경 → cluster queryKey 변경.
    await placeBtn.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(() => requests.clusterKinds.at(-1))
      .toEqual(["weather", "notice", "place"]);
    await expect(reset).toBeEnabled();

    // '초기화' → 기본 kind(weather/notice) 복원. 동일 byte 쿼리는 react-query 캐시로
    // 새 네트워크 호출이 없을 수 있으므로 UI 상태로 단언한다.
    await reset.click();
    await expect(placeBtn).toHaveAttribute("aria-pressed", "false");
    await expect(weatherBtn).toHaveAttribute("aria-pressed", "true");
    await expect(noticeBtn).toHaveAttribute("aria-pressed", "true");
    await expect(reset).toBeDisabled();
  });
});
