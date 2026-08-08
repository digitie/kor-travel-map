import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/features/[featureId]` 상세 — 섹션 깊이 spec (T-AUDIT-0616 추가분).
 *
 * 기존 `feature-detail.spec.ts`가 커버하는 항목(기본 헤더+섹션 타이틀, raw_refs 1개,
 * weather 패널 visible, nearby 1건, weather empty, 404 alert)은 **재계획하지 않고**,
 * 행/셀/컬럼헤더/토글/에러 격리/요청 카운터 같은 **깊이**만 추가한다.
 *
 * 본 페이지는 admin 상세/weather 라우트 + 공개 `GET /v1/features/nearby`를 쓴다.
 * 모든 mock body는 생성된 OpenAPI 스키마(`components["schemas"][...]`)에 바인딩해
 * 백엔드 DTO 변경 시 컴파일이 깨지도록 한다(admin-ops.spec 패턴).
 *
 * 라이브 실행 검증은 n150 Linux 환경에서 수행한다.
 */

type AdminFeatureDetailData = components["schemas"]["AdminFeatureDetailData"];
type AdminFeatureDetailFeatureRecord =
  components["schemas"]["AdminFeatureDetailFeatureRecord"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];
type AdminFeatureDetailSourceRecord =
  components["schemas"]["AdminFeatureDetailSourceRecord"];
type AdminFeatureDetailIssueRecord =
  components["schemas"]["AdminFeatureDetailIssueRecord"];
type AdminFeatureDetailOverrideRecord =
  components["schemas"]["AdminFeatureDetailOverrideRecord"];
type AdminFeatureDetailFileRecord =
  components["schemas"]["AdminFeatureDetailFileRecord"];
type AdminFeatureDetailVersionRecord =
  components["schemas"]["AdminFeatureDetailVersionRecord"];
type AdminFeatureChangeRequestRecord =
  components["schemas"]["AdminFeatureChangeRequestRecord"];
type CurationItemView = components["schemas"]["AdminCurationItemView"];
type FeaturesNearbyResponse = components["schemas"]["FeaturesNearbyResponse"];
type NearbyFeatureSummary = components["schemas"]["NearbyFeatureSummary"];
type FeatureWeatherResponse = components["schemas"]["FeatureWeatherResponse"];
type WeatherCardData = components["schemas"]["WeatherCardData"];
type WeatherMetricOut = components["schemas"]["WeatherMetricOut"];

const FEATURE_ID = "f_1156010100_p_sectiondepth00001";
const DETAIL_PATH = `/v1/admin/features/${FEATURE_ID}`;
const NEARBY_PATH = "/v1/features/nearby";
const meta = { duration_ms: 1, request_id: "e2e-feature-detail-sections" };

// 식별 가능한 고정 값 — 셀/JSON 토글에서 그대로 찾을 수 있게 한다.
const SOURCE_PROVIDER = "python-visitkorea-api";
const ISSUE_VIOLATION_TYPE = "missing_address";
const OVERRIDE_FIELD_PATH = "name";
const FILE_OBJECT_KEY = "features/section-depth/image-001.jpg";
const RAW_DETAIL_MARKER = "e2e-detail-marker-value";
const RAW_REFS_MARKER = "e2e-raw-refs-marker-value";
const CURATION_COLLECTION_KEY = "tourism-100-2025-2026";
const CURATION_METADATA_MARKER = "e2e-curation-metadata-marker";

function makeFeature(
  overrides: Partial<AdminFeatureDetailFeatureRecord> = {},
): AdminFeatureDetailFeatureRecord {
  return {
    address: { road: "서울특별시 영등포구 여의공원로 120" },
    category: "01070300",
    created_at: "2026-06-01T00:00:00.000Z",
    data_origin: "provider",
    data_version: 3,
    detail: { place_kind: "park", marker: RAW_DETAIL_MARKER },
    feature_id: FEATURE_ID,
    kind: "place",
    lat: 37.5263,
    lon: 126.9239,
    marker_color: "P-01",
    marker_icon: "marker",
    name: "여의도공원",
    raw_refs: [],
    row_revision: 3,
    sido_code: "11",
    sigungu_code: "11560",
    status: "active",
    updated_at: "2026-06-08T00:00:00.000Z",
    urls: { homepage: "https://example.test" },
    ...overrides,
  };
}

function makeSource(
  overrides: Partial<AdminFeatureDetailSourceRecord> = {},
): AdminFeatureDetailSourceRecord {
  return {
    confidence: 0.92,
    dataset_key: "visitkorea_area_based",
    expires_at: null,
    fetched_at: "2026-06-07T00:00:00.000Z",
    imported_at: "2026-06-07T01:00:00.000Z",
    observed_at: "2026-06-07T02:00:00.000Z",
    linked_at: "2026-06-07T01:30:00.000Z",
    match_method: "exact",
    provider: SOURCE_PROVIDER,
    raw_data: { contentid: "126508", title: "여의도공원" },
    raw_payload_hash: "hash-source-001",
    source_entity_id: "126508",
    source_entity_key: "se-e2e-visitkorea-126508",
    source_entity_type: "area_based_item",
    source_record_key: "python-visitkorea-api::visitkorea_area_based::126508",
    source_role: "primary",
    ...overrides,
  };
}

function makeCuration(
  overrides: Partial<CurationItemView> = {},
): CurationItemView {
  return {
    accepted_link_decision_id: "decision-section-depth-001",
    address: { road: "서울특별시 영등포구 여의공원로 120" },
    address_hint: "서울 영등포구",
    archived_at: null,
    collection_id: "collection-section-depth-001",
    collection_key: CURATION_COLLECTION_KEY,
    created_at: "2026-06-08T00:00:00.000Z",
    created_by: "e2e-admin",
    curation_item_id: "curation-item-section-depth-001",
    curation_relation: "primary_stop",
    current_import_row_id: "import-row-section-depth-001",
    dataset_key: "tourism-100",
    edition_key: "2025-2026",
    external_item_id: "tourism-100-yeouido",
    external_component_id: "primary",
    feature_category: "01070300",
    feature_id: FEATURE_ID,
    feature_kind: "place",
    feature_name: "여의도공원",
    item_summary: "2025~2026 선정지",
    item_title: "여의도공원",
    lat: 37.5263,
    link_actor: "e2e-admin",
    link_decided_at: "2026-06-08T00:00:00.000Z",
    link_evidence: { source: "e2e-explicit" },
    link_match_basis: "csv_explicit_feature_id",
    link_resolver_version: "curation-link-v1",
    lon: 126.9239,
    metadata: { marker: CURATION_METADATA_MARKER },
    place_name: "여의도공원",
    provider: "mcst",
    provider_dataset_id: 701,
    reuse_policy: "manual_review",
    sort_order: 12,
    source_name: "문화체육관광부",
    source_present: true,
    source_record_key: "mcst::tourism-100::yeouido",
    source_url: "https://example.test/tourism-100",
    status: "included",
    theme_group: "관광 선정",
    theme_name: "한국관광 100선",
    theme_slug: "korean-tourism-100",
    title: "2025~2026 한국관광 100선",
    updated_at: "2026-06-09T00:00:00.000Z",
    updated_by: "e2e-admin",
    ...overrides,
  };
}

function makeIssue(
  overrides: Partial<AdminFeatureDetailIssueRecord> = {},
): AdminFeatureDetailIssueRecord {
  return {
    dataset_key: "visitkorea_area_based",
    detected_at: "2026-06-08T02:00:00.000Z",
    issue_id: "issue-section-depth-001",
    message: "주소가 비어있습니다.",
    payload: {},
    provider: SOURCE_PROVIDER,
    resolved_at: null,
    severity: "warning",
    source_record_key: "python-visitkorea-api::visitkorea_area_based::126508",
    status: "open",
    violation_type: ISSUE_VIOLATION_TYPE,
    ...overrides,
  };
}

function makeOverride(
  overrides: Partial<AdminFeatureDetailOverrideRecord> = {},
): AdminFeatureDetailOverrideRecord {
  return {
    created_at: "2026-06-08T03:00:00.000Z",
    created_by: "local-admin",
    field_path: OVERRIDE_FIELD_PATH,
    override_id: "override-section-depth-001",
    override_value: "여의도 한강공원",
    prevent_provider_reactivation: false,
    reason: "운영자 이름 교정",
    source_record_key: "python-visitkorea-api::visitkorea_area_based::126508",
    source_value: "여의도공원",
    status: "active",
    ...overrides,
  };
}

function makeFile(
  overrides: Partial<AdminFeatureDetailFileRecord> = {},
): AdminFeatureDetailFileRecord {
  return {
    alt_text: "여의도공원 전경",
    bucket: "kor-travel-map",
    byte_size: 204_800,
    checksum_sha256: null,
    content_type: "image/jpeg",
    created_at: "2026-06-08T04:00:00.000Z",
    dataset_key: "visitkorea_area_based",
    display_order: 0,
    file_id: "file-section-depth-001",
    file_type: "image",
    height: 1080,
    object_key: FILE_OBJECT_KEY,
    payload: {},
    provider: SOURCE_PROVIDER,
    public_url: null,
    role: "primary_image",
    source_record_key: "python-visitkorea-api::visitkorea_area_based::126508",
    source_url: null,
    storage_backend: "rustfs",
    updated_at: "2026-06-08T04:00:00.000Z",
    width: 1920,
    ...overrides,
  };
}

function makeVersion(
  overrides: Partial<AdminFeatureDetailVersionRecord> = {},
): AdminFeatureDetailVersionRecord {
  return {
    change_kind: "provider_merge",
    created_at: "2026-06-08T05:00:00.000Z",
    created_by: "dagster",
    feature_id: FEATURE_ID,
    origin: "provider",
    payload: { name: "여의도공원" },
    request_id: null,
    version: 3,
    ...overrides,
  };
}

function makeChangeRequest(
  overrides: Partial<AdminFeatureChangeRequestRecord> = {},
): AdminFeatureChangeRequestRecord {
  return {
    action: "update",
    applied_at: "2026-06-08T06:10:00.000Z",
    created_at: "2026-06-08T06:00:00.000Z",
    feature_id: FEATURE_ID,
    payload: { name: "여의도 한강공원" },
    reason: "운영 변경",
    request_id: "creq-section-depth-0001",
    requested_by: "local-admin",
    review_mode: "require_review",
    reviewed_at: "2026-06-08T06:10:00.000Z",
    reviewed_by: "local-admin",
    status: "applied",
    ...overrides,
  };
}

function makeNearby(
  overrides: Partial<NearbyFeatureSummary> = {},
): NearbyFeatureSummary {
  return {
    category: "01070300",
    distance_m: 152.4,
    feature_id: "f_1156010100_p_neighbor00000001",
    kind: "place",
    lat: 37.527,
    lon: 126.924,
    name: "인근 카페",
    status: "active",
    ...overrides,
  };
}

function makeWeatherMetric(
  overrides: Partial<WeatherMetricOut> = {},
): WeatherMetricOut {
  return {
    forecast_style: "short_term",
    issued_at: "2026-06-08T00:00:00.000Z",
    metric_key: "T1H",
    metric_name: "기온",
    observed_at: null,
    severity: "normal",
    timeline_bucket: null,
    unit: "°C",
    valid_at: "2026-06-08T09:00:00.000Z",
    value_number: 21.5,
    value_text: null,
    ...overrides,
  };
}

function makeDetailData(
  partial: Partial<AdminFeatureDetailData> = {},
): AdminFeatureDetailData {
  return {
    change_requests: [],
    curations: [],
    feature: makeFeature(),
    files: [],
    issues: [],
    overrides: [],
    sources: [],
    versions: [],
    ...partial,
  };
}

function makeDetailResponse(
  data: AdminFeatureDetailData,
): AdminFeatureDetailResponse {
  return { data, meta };
}

function makeWeatherResponse(
  data: Partial<WeatherCardData> = {},
): FeatureWeatherResponse {
  return {
    data: {
      asof: null,
      feature_id: FEATURE_ID,
      is_stale: false,
      latest_at: null,
      metrics: [],
      source_styles: [],
      ...data,
    },
    meta,
  };
}

function makeNearbyResponse(
  items: NearbyFeatureSummary[],
): FeaturesNearbyResponse {
  return {
    data: {
      items,
      origin: { lat: 37.5263, lon: 126.9239, radius_m: 3000 },
    },
    meta,
  };
}

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

interface MockOptions {
  data?: AdminFeatureDetailData;
  nearby?: NearbyFeatureSummary[];
  weather?: Partial<WeatherCardData>;
  weatherStatus?: number;
  nearbyStatus?: number;
}

interface MockCounters {
  detail: number;
  nearby: number;
  weather: number;
  /** admin 상세 라우트로 들어온 정확한 pathname 목록(deeplink 검증용). */
  detailPaths: string[];
}

async function mockFeatureDetail(
  page: Page,
  options: MockOptions = {},
): Promise<MockCounters> {
  const data = options.data ?? makeDetailData();
  const nearby = options.nearby ?? [];
  const counters: MockCounters = {
    detail: 0,
    nearby: 0,
    weather: 0,
    detailPaths: [],
  };

  await page.route("**/v1/admin/features/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = apiPath(url);
    if (request.method() === "GET" && pathname.endsWith("/weather")) {
      counters.weather += 1;
      if (options.weatherStatus && options.weatherStatus >= 400) {
        await fulfillJson(route, { detail: "weather 조회 실패" }, options.weatherStatus);
        return;
      }
      await fulfillJson(route, makeWeatherResponse(options.weather));
      return;
    }
    if (request.method() === "GET" && pathname === DETAIL_PATH) {
      counters.detail += 1;
      counters.detailPaths.push(pathname);
      await fulfillJson(route, makeDetailResponse(data));
      return;
    }
    await route.continue();
  });

  await page.route("**/v1/features/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = apiPath(url);
    if (request.method() === "GET" && pathname === NEARBY_PATH) {
      counters.nearby += 1;
      if (options.nearbyStatus && options.nearbyStatus >= 400) {
        await fulfillJson(route, { detail: "nearby 조회 실패" }, options.nearbyStatus);
        return;
      }
      await fulfillJson(route, makeNearbyResponse(nearby));
      return;
    }
    await route.continue();
  });

  return counters;
}

test.describe("/features/[featureId] 섹션 깊이", () => {
  test("섹션 전체 깊이 — Sources/Issues/Overrides/Files 행 + 컬럼헤더 + 카운트", async ({
    page,
  }) => {
    await mockFeatureDetail(page, {
      data: makeDetailData({
        sources: [makeSource()],
        curations: [makeCuration()],
        issues: [makeIssue()],
        overrides: [makeOverride()],
        files: [makeFile()],
        // History의 versions/change_requests 두 테이블도 채워 EMPTY_MESSAGE 0건을 보장
        // (안 채우면 그 둘이 '데이터가 없습니다.'로 렌더돼 toHaveCount(0)가 깨진다).
        versions: [makeVersion()],
        change_requests: [makeChangeRequest()],
      }),
    });
    await page.goto(`/features/${FEATURE_ID}`);

    const detailView = page.getByTestId("feature-detail-view");
    await expect(detailView).toBeVisible();

    const sectionScope = (title: string) =>
      detailView.locator("section").filter({ hasText: title }).first();

    // 섹션 타이틀 — detail-view scope 안에서만(헤더 nav 동명 링크와 분리).
    for (const section of ["Sources", "큐레이션", "Issues", "Overrides", "Files"]) {
      await expect(sectionScope(section)).toBeVisible();
    }

    // 컬럼헤더는 소유 섹션 scope 안에서 검증한다. "provider"는 Sources/Files 두
    // 테이블이 모두 가지므로 detail-view 전체 scope에서는 strict-mode 충돌(2건)이
    // 난다 → 각 헤더를 자기 Section(<section> ancestor)으로 좁힌다(Nearby 카운트
    // 배지 검증과 동일한 house 패턴).
    // [헤더 텍스트, 소유 섹션 타이틀] — 섹션별 unique 헤더로 표가 렌더됐음을 확인.
    const sectionColumns: [string, string][] = [
      ["provider", "Sources"],
      ["entity", "Sources"],
      ["seen", "Sources"],
      ["상세", "큐레이션"],
      ["field", "Overrides"],
      ["provider", "Files"],
      ["object", "Files"],
    ];
    for (const [column, section] of sectionColumns) {
      await expect(
        sectionScope(section).getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }
    // Issues type 컬럼 헤더(violation_type가 아니라 헤더 텍스트 "type").
    await expect(
      sectionScope("Issues").getByRole("columnheader", { name: "type", exact: true }),
    ).toBeVisible();

    // 채운 행의 식별 셀 값.
    await expect(detailView.getByText(SOURCE_PROVIDER).first()).toBeVisible();
    await expect(detailView.getByText(ISSUE_VIOLATION_TYPE)).toBeVisible();
    await expect(
      detailView.getByText(OVERRIDE_FIELD_PATH, { exact: true }).first(),
    ).toBeVisible();
    await expect(detailView.getByText(FILE_OBJECT_KEY)).toBeVisible();
    await expect(
      detailView.getByText("2025~2026 한국관광 100선", { exact: true }),
    ).toBeVisible();

    const curationSection = sectionScope("큐레이션");
    await curationSection.getByText("전체 정보").click();
    await expect(curationSection.getByText(new RegExp(CURATION_COLLECTION_KEY))).toBeVisible();
    await expect(curationSection.getByText(new RegExp(CURATION_METADATA_MARKER))).toBeVisible();
    await expect(curationSection.getByText("manual_review", { exact: true })).toBeVisible();

    const sourcesSection = sectionScope("Sources");
    await sourcesSection.locator("summary").first().click();
    await expect(sourcesSection.getByText(new RegExp("hash-source-001"))).toBeVisible();

    // 모든 표가 비어있지 않으므로 EMPTY_MESSAGE는 0건.
    await expect(detailView.getByText("데이터가 없습니다.")).toHaveCount(0);
  });

  test("History 섹션 — versions + change_requests 두 테이블 동시 render", async ({
    page,
  }) => {
    await mockFeatureDetail(page, {
      data: makeDetailData({
        versions: [makeVersion()],
        change_requests: [makeChangeRequest()],
      }),
    });
    await page.goto(`/features/${FEATURE_ID}`);

    const detailView = page.getByTestId("feature-detail-view");
    await expect(detailView.getByText("History", { exact: true })).toBeVisible();

    // version 테이블 고유 헤더 + change-request 테이블 고유 헤더.
    for (const column of ["version", "origin", "change", "request", "action"]) {
      await expect(
        detailView.getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }

    // version row: version 번호(font-mono) + origin 값.
    await expect(detailView.getByText("3", { exact: true }).first()).toBeVisible();
    await expect(detailView.getByText("provider", { exact: true }).first()).toBeVisible();

    // change_requests row: shortId(request_id, 12) — "creq-section" (12자) + action.
    await expect(detailView.getByText("creq-section")).toBeVisible();
    await expect(detailView.getByText("update", { exact: true }).first()).toBeVisible();

    // Section 카운트 배지 = versions.length(1) + change_requests.length(1) = 2.
    await expect(detailView.getByText("2", { exact: true }).first()).toBeVisible();
  });

  test("Nearby — self 제외 + distance 라벨 km/m 포맷 + 카운트 배지", async ({
    page,
  }) => {
    const neighbors: NearbyFeatureSummary[] = [
      // self — feature_id == FEATURE_ID 이므로 필터되어 렌더 안 됨.
      makeNearby({
        distance_m: 0,
        feature_id: FEATURE_ID,
        name: "여의도공원(자기 자신)",
      }),
      // distance_m >= 1000 → "x.xx km".
      makeNearby({
        distance_m: 1234.5,
        feature_id: "f_1156010100_p_neighbor00000002",
        name: "먼 전망대",
      }),
      // distance_m < 1000 → "NNN m".
      makeNearby({
        distance_m: 152.4,
        feature_id: "f_1156010100_p_neighbor00000003",
        name: "가까운 카페",
      }),
    ];
    await mockFeatureDetail(page, { nearby: neighbors });
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByText("Nearby", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "distance" }),
    ).toBeVisible();

    // self는 link로 렌더되지 않는다.
    await expect(
      page.getByRole("link", { name: /여의도공원\(자기 자신\)/ }),
    ).toHaveCount(0);

    // 두 이웃은 /features/{encoded id} href link로 렌더.
    const farLink = page.getByRole("link", { name: /먼 전망대/ });
    const nearLink = page.getByRole("link", { name: /가까운 카페/ });
    await expect(farLink).toBeVisible();
    await expect(nearLink).toBeVisible();
    await expect(farLink).toHaveAttribute(
      "href",
      "/features/f_1156010100_p_neighbor00000002",
    );

    // distance 포맷: 1234.5m → "1.23 km", 152.4m → "152 m".
    await expect(page.getByText("1.23 km")).toBeVisible();
    await expect(page.getByText("152 m")).toBeVisible();

    // Nearby 카운트 배지 = self 제외 후 항목 수(2).
    await expect(
      page
        .getByTestId("feature-detail-view")
        .getByText("Nearby", { exact: true })
        .locator("xpath=ancestor::section[1]")
        .getByText("2", { exact: true }),
    ).toBeVisible();
  });

  test("Weather 패널 깊이 — metric 행 + styles/asof dl + stale 배지", async ({
    page,
  }) => {
    await mockFeatureDetail(page, {
      data: makeDetailData({ feature: makeFeature({ kind: "weather" }) }),
      weather: {
        asof: "2026-06-08T09:00:00.000Z",
        is_stale: true,
        latest_at: "2026-06-08T08:00:00.000Z",
        metrics: [makeWeatherMetric()],
        source_styles: ["short_term", "mid_term"],
      },
    });
    await page.goto(`/features/${FEATURE_ID}`);

    const panel = page.getByTestId("feature-weather-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Weather")).toBeVisible();
    await expect(panel.getByText("날씨 정보와 최근 업데이트 시간")).toBeVisible();

    // is_stale=true → 배지 텍스트 "stale"(fresh 아님).
    await expect(panel.getByText("stale")).toBeVisible();
    await expect(panel.getByText("fresh")).toHaveCount(0);

    // dl 라벨 + source_styles outline 배지(패널 scope에서 헤더 동명 라벨과 분리).
    await expect(panel.getByText("최근 업데이트", { exact: true })).toBeVisible();
    await expect(panel.getByText("asof", { exact: true })).toBeVisible();
    await expect(panel.getByText("styles", { exact: true })).toBeVisible();
    await expect(panel.getByText("short_term").first()).toBeVisible();
    await expect(panel.getByText("mid_term")).toBeVisible();

    // metric 테이블 헤더(non-compact 경로 — compact prop 미전달).
    for (const column of ["metric", "value", "style", "severity", "valid"]) {
      await expect(
        panel.getByRole("columnheader", { name: column, exact: true }),
      ).toBeVisible();
    }

    // metric 행: metric_name + value_number+unit 합성("21.5 °C").
    await expect(panel.getByText("기온")).toBeVisible();
    await expect(panel.getByText("21.5 °C")).toBeVisible();

    // 비어있지 않으므로 weather empty 메시지 0건.
    await expect(panel.getByText("weather metric이 없습니다.")).toHaveCount(0);
  });

  test("Weather 호출 실패 — 패널 내부 alert + 페이지 잔존", async ({ page }) => {
    await mockFeatureDetail(page, {
      data: makeDetailData({ feature: makeFeature({ kind: "weather" }) }),
      weatherStatus: 500,
    });
    await page.goto(`/features/${FEATURE_ID}`);

    const panel = page.getByTestId("feature-weather-panel");
    await expect(panel.getByText("weather 호출 실패")).toBeVisible();

    // 상세 GET은 성공 → feature-detail-view 루트와 헤더 h2는 계속 보인다.
    await expect(page.getByTestId("feature-detail-view")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "여의도공원" }),
    ).toBeVisible();
  });

  test("Nearby 호출 실패 — 패널 내부 alert + 페이지 잔존", async ({ page }) => {
    await mockFeatureDetail(page, { nearbyStatus: 500 });
    await page.goto(`/features/${FEATURE_ID}`);

    await expect(page.getByText("Nearby", { exact: true })).toBeVisible();
    await expect(page.getByText("nearby 호출 실패")).toBeVisible();
    await expect(page.getByTestId("feature-detail-view")).toBeVisible();
  });

  test("좌표 없는 feature — Nearby '좌표가 없습니다' + nearby GET 미발생", async ({
    page,
  }) => {
    const counters = await mockFeatureDetail(page, {
      data: makeDetailData({ feature: makeFeature({ lat: null, lon: null }) }),
    });
    await page.goto(`/features/${FEATURE_ID}`);

    // Nearby 패널 자리표시.
    await expect(page.getByText("좌표가 없습니다.")).toBeVisible();
    // 헤더 coord dd가 "-"(coordLabel null → "-").
    await expect(page.getByText("coord", { exact: true })).toBeVisible();

    // 상세 GET 1회는 발생했으나(페이지 렌더), nearby는 enabled=false라 0회.
    await expect.poll(() => counters.detail).toBe(1);
    await expect.poll(() => counters.nearby).toBe(0);
  });

  test("Raw 네이티브 <details> 토글 — detail open + raw_refs 토글로 JSON 노출", async ({
    page,
  }) => {
    await mockFeatureDetail(page, {
      data: makeDetailData({
        feature: makeFeature({
          detail: { marker: RAW_DETAIL_MARKER },
          raw_refs: [{ ref: RAW_REFS_MARKER }],
        }),
      }),
    });
    await page.goto(`/features/${FEATURE_ID}`);

    const detailView = page.getByTestId("feature-detail-view");

    // 4개 disclosure summary 텍스트.
    for (const summary of ["detail", "raw_refs", "urls", "address"]) {
      await expect(
        detailView.getByText(summary, { exact: true }),
      ).toBeVisible();
    }

    // detail disclosure는 <details open> — 기본으로 JSON(<pre>) 값이 보인다.
    await expect(detailView.getByText(new RegExp(RAW_DETAIL_MARKER))).toBeVisible();

    // raw_refs는 닫혀 있어 처음엔 값이 숨겨져 있고, summary click 후 보인다.
    const rawRefsValue = detailView.getByText(new RegExp(RAW_REFS_MARKER));
    await expect(rawRefsValue).toBeHidden();
    await detailView.getByText("raw_refs", { exact: true }).click();
    await expect(rawRefsValue).toBeVisible();
  });

  test("feature_id deeplink — admin 상세 GET이 정확한 path로 1회 발사", async ({
    page,
  }) => {
    const counters = await mockFeatureDetail(page);
    await page.goto(`/features/${FEATURE_ID}`);

    const detailView = page.getByTestId("feature-detail-view");
    await expect(detailView).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "여의도공원" }),
    ).toBeVisible();
    // 헤더에 feature_id 원문(font-mono)이 그대로 보인다.
    await expect(detailView.getByText(FEATURE_ID)).toBeVisible();
    await expect(page.getByRole("link", { name: "수정" })).toHaveAttribute(
      "href",
      `/admin/features/change-requests?action=update&feature_id=${encodeURIComponent(FEATURE_ID)}`,
    );

    // GET /v1/admin/features/{FEATURE_ID} 정확히 1회 + 그 path만 수신.
    await expect.poll(() => counters.detail).toBe(1);
    expect(counters.detailPaths).toEqual([DETAIL_PATH]);
  });
});
