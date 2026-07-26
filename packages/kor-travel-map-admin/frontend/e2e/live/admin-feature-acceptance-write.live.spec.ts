import {
  expect,
  test,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";
import { createHash } from "node:crypto";

import type { components } from "../../src/api/types";

type ChangeResponse = components["schemas"]["AdminFeatureChangeResponse"];
type ChangeListResponse =
  components["schemas"]["AdminFeatureChangeListResponse"];
type DetailResponse = components["schemas"]["AdminFeatureDetailResponse"];
type FeatureSearchProblem = components["schemas"]["FeatureSearchProblem"];
type FeatureSearchResponse = components["schemas"]["FeatureSearchResponse"];
type InBoundsResponse = components["schemas"]["AdminFeaturesInBoundsResponse"];
type PublicInBoundsResponse = components["schemas"]["FeaturesInBoundsResponse"];
type PriceResponse = components["schemas"]["FeaturePriceResponse"];
type RevisionResponse = components["schemas"]["AdminFeatureRevisionResponse"];
type WeatherResponse = components["schemas"]["FeatureWeatherResponse"];

type FetchResult<T> = {
  body: T | null;
  contentType: string | null;
  entityTag: string | null;
  status: number;
};

const FLOW_TIMEOUT = 5 * 60 * 1000;
const UI_TIMEOUT = 30_000;
const RUN_ID_PATTERN = /^[a-z0-9][a-z0-9-]{15,79}$/;
const RUN_ID = process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID ?? "";
const EXECUTE = process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE === "1";
const RECOVERY_ONLY =
  process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY === "1";
const LON = 127.5;
const LAT = 36.5;

if (EXECUTE && !RUN_ID_PATTERN.test(RUN_ID)) {
  throw new Error(
    "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID 형식이 올바르지 않습니다 (value redacted)",
  );
}

const PREFIX = `e2e_live_acceptance::${RUN_ID}`;
const STATUS_FIXTURES = ["draft", "inactive", "hidden"] as const;
const STATUS_FEATURES = STATUS_FIXTURES.map((status, index) => ({
  featureId: `${PREFIX}::marker::${status}`,
  lat: LAT + index * 0.001,
  lon: LON + index * 0.001,
  name: `E2E ${status} marker ${RUN_ID}`,
  status,
}));
const CORRECTION_FEATURE = {
  featureId: `${PREFIX}::correction`,
  lat: LAT - 0.002,
  lon: LON,
  name: `E2E correction baseline ${RUN_ID}`,
};
const WEATHER_FEATURE = {
  featureId: `${PREFIX}::weather`,
  lat: LAT,
  lon: LON + 0.002,
  name: `E2E hidden weather ${RUN_ID}`,
};
const PRICE_FEATURE = {
  featureId: `${PREFIX}::price`,
  lat: LAT,
  lon: LON - 0.002,
  name: `E2E hidden price ${RUN_ID}`,
};
// 검색 fixture 전용 토큰은 RUN_ID의 해시 파생값을 쓴다: /v1/features/search는
// pg_trgm similarity(threshold 0.2) 기반이라, 쿼리에 RUN_ID 원문(수십 자)을
// 넣으면 같은 run의 다른 active fixture(correction baseline — 이름에 동일
// RUN_ID 포함)까지 trigram 매칭돼 total=2 단언이 3으로 깨진다(1f34586e live
// 재현으로 확정). 해시 토큰은 run-scoped 유일성은 유지하면서 다른 fixture
// 이름과 긴 공유 substring이 없어 fuzzy 검색과 격리된다. RECOVERY_ONLY도
// 같은 RUN_ID env에서 동일 토큰을 재파생하므로 cleanup 대칭이 유지된다.
const SEARCH_TOKEN = createHash("sha256")
  .update(`acceptance-search:${RUN_ID}`)
  .digest("hex")
  .slice(0, 16);
const SEARCH_QUERY = `e2esrch ${SEARCH_TOKEN}`;
const SEARCH_FEATURES = ["alpha", "beta"].map((suffix, index) => ({
  featureId: `${PREFIX}::search::${suffix}`,
  lat: LAT + 0.004 + index * 0.001,
  lon: LON + 0.004 + index * 0.001,
  name: `${SEARCH_QUERY} ${suffix}`,
  status: "active" as const,
}));
const API_OWNED_FEATURE_IDS = [
  ...STATUS_FEATURES.map(({ featureId }) => featureId),
  CORRECTION_FEATURE.featureId,
  ...SEARCH_FEATURES.map(({ featureId }) => featureId),
];
const REASON = `admin feature live acceptance ${RUN_ID}`;

test.describe.configure({ mode: "serial" });

function adminFeaturePath(featureId: string): string {
  return `/v1/admin/features/${encodeURIComponent(featureId)}`;
}

function revisionPath(featureId: string): string {
  return `${adminFeaturePath(featureId)}/revision`;
}

function publicFeaturePath(featureId: string): string {
  return `/v1/features/${encodeURIComponent(featureId)}`;
}

function changeActionPath(
  requestId: string,
  action: "approve" | "reject",
): string {
  return `/v1/admin/features/change-requests/${encodeURIComponent(
    requestId,
  )}/${action}`;
}

function responseApiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function requestApiPath(request: Request): string {
  const pathname = new URL(request.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: {
    body?: unknown;
    headers?: Record<string, string>;
    method?: "GET" | "POST" | "PATCH" | "DELETE";
  } = {},
): Promise<FetchResult<T>> {
  return page.evaluate(
    async ({ body, headers, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...headers,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        credentials: "same-origin",
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try {
        parsed = text.length > 0 ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      return {
        body: parsed as T | null,
        contentType: response.headers.get("Content-Type"),
        entityTag: response.headers.get("ETag"),
        status: response.status,
      };
    },
    {
      body: options.body,
      headers: options.headers,
      method: options.method ?? "GET",
      path,
    },
  );
}

function requireBody<T>(result: FetchResult<T>, label: string): T {
  if (result.status !== 200 || result.body === null) {
    throw new Error(`${label} 실패: HTTP ${result.status} (response redacted)`);
  }
  return result.body;
}

function requireEntityTag<T>(result: FetchResult<T>, label: string): string {
  requireBody(result, label);
  if (result.entityTag === null || !/^"[1-9][0-9]*"$/.test(result.entityTag)) {
    throw new Error(`${label} raw strong ETag가 없습니다`);
  }
  return result.entityTag;
}

async function approveOrReject(
  page: Page,
  requestId: string,
  action: "approve" | "reject",
  reason: string,
): Promise<ChangeResponse> {
  const result = await browserFetch<ChangeResponse>(
    page,
    changeActionPath(requestId, action),
    { body: { reason }, method: "POST" },
  );
  return requireBody(result, `${action} change request`);
}

async function createOwnedPlace(
  page: Page,
  fixture: {
    featureId: string;
    lat: number;
    lon: number;
    name: string;
    status: "draft" | "active" | "inactive" | "hidden";
  },
): Promise<void> {
  if (RECOVERY_ONLY) {
    throw new Error("recovery-only는 Feature를 생성할 수 없습니다");
  }
  const create = await browserFetch<ChangeResponse>(
    page,
    "/v1/admin/features",
    {
      body: {
        category: "01070300",
        coord: { lat: fixture.lat, lon: fixture.lon },
        feature_id: fixture.featureId,
        idempotency_key: createHash("sha256")
          .update(fixture.featureId, "utf8")
          .digest("hex"),
        kind: "place",
        marker_color: "P-02",
        marker_icon: "marker",
        name: fixture.name,
        reason: `${REASON} create ${fixture.status}`,
        status: fixture.status,
      },
      method: "POST",
    },
  );
  const created = requireBody(create, `create ${fixture.status}`).data.request;
  if (created.status !== "pending") {
    throw new Error("production review mode가 require_review가 아닙니다");
  }
  const approved = await approveOrReject(
    page,
    created.request_id,
    "approve",
    `${REASON} approve ${fixture.status}`,
  );
  if (approved.data.request.status !== "applied") {
    throw new Error(`create ${fixture.status} 승인이 applied가 아닙니다`);
  }
  const detail = requireBody(
    await browserFetch<DetailResponse>(
      page,
      adminFeaturePath(fixture.featureId),
    ),
    `created ${fixture.status} detail`,
  );
  expect(detail.data.feature).toMatchObject({
    feature_id: fixture.featureId,
    name: fixture.name,
    status: fixture.status,
  });
}

async function pendingOwnedRequests(
  page: Page,
): Promise<ChangeListResponse["data"]["items"]> {
  const query = new URLSearchParams({
    page_size: "500",
    q: RUN_ID,
    status: "pending",
  });
  return requireBody(
    await browserFetch<ChangeListResponse>(
      page,
      `/v1/admin/features/change-requests?${query.toString()}`,
    ),
    "pending owned change requests",
  ).data.items.filter((item) =>
    API_OWNED_FEATURE_IDS.includes(item.feature_id),
  );
}

async function cleanupApiOwnedFeatures(page: Page): Promise<void> {
  const firstPending = await pendingOwnedRequests(page);
  for (const request of firstPending) {
    const action = request.action === "delete" ? "approve" : "reject";
    const result = await approveOrReject(
      page,
      request.request_id,
      action,
      `${REASON} recovery ${action}`,
    );
    const expected = action === "approve" ? "applied" : "rejected";
    if (result.data.request.status !== expected) {
      throw new Error(
        `pending ${request.action} recovery가 ${expected}가 아닙니다`,
      );
    }
  }

  for (const featureId of API_OWNED_FEATURE_IDS) {
    const detail = await browserFetch<DetailResponse>(
      page,
      adminFeaturePath(featureId),
    );
    if (detail.status === 404) continue;
    const current = requireBody(detail, "cleanup detail").data.feature;
    if (current.status !== "deleted") {
      const revision = await browserFetch<RevisionResponse>(
        page,
        revisionPath(featureId),
      );
      const entityTag = requireEntityTag(revision, "cleanup revision");
      const deletion = await browserFetch<ChangeResponse>(
        page,
        adminFeaturePath(featureId),
        {
          body: { reason: `${REASON} cleanup delete` },
          headers: { "If-Match": entityTag },
          method: "DELETE",
        },
      );
      const deleteRequest = requireBody(deletion, "cleanup DELETE").data.request;
      if (deleteRequest.status === "pending") {
        const approved = await approveOrReject(
          page,
          deleteRequest.request_id,
          "approve",
          `${REASON} cleanup approve delete`,
        );
        if (approved.data.request.status !== "applied") {
          throw new Error("cleanup delete 승인이 applied가 아닙니다");
        }
      } else if (deleteRequest.status !== "applied") {
        throw new Error("cleanup DELETE가 종결되지 않았습니다");
      }
    }

    await expect
      .poll(
        async () => {
          const latest = await browserFetch<DetailResponse>(
            page,
            adminFeaturePath(featureId),
          );
          return latest.body?.data.feature.status ?? `http:${latest.status}`;
        },
        { timeout: UI_TIMEOUT },
      )
      .toBe("deleted");
    expect(
      (await browserFetch(page, publicFeaturePath(featureId))).status,
    ).toBe(404);
  }

  const remainingPending = await pendingOwnedRequests(page);
  if (remainingPending.length !== 0) {
    throw new Error("owned pending change request가 cleanup 뒤 남았습니다");
  }
  const searchAfterCleanup = requireBody(
    await browserFetch<FeatureSearchResponse>(
      page,
      `/v1/features/search?${new URLSearchParams({
        include_total: "true",
        page_size: "1",
        q: SEARCH_QUERY,
      }).toString()}`,
    ),
    "owned search fixture cleanup",
  );
  expect(searchAfterCleanup.data.items).toEqual([]);
  expect(searchAfterCleanup.meta.page).toBeDefined();
  expect(searchAfterCleanup.meta.page?.total).toBe(0);
  expect(searchAfterCleanup.meta.page?.next_cursor ?? null).toBeNull();
}

async function assertPublicInBoundsExcludes(
  page: Page,
  featureId: string,
  lon: number,
  lat: number,
): Promise<void> {
  const params = new URLSearchParams({
    max_items: "10",
    max_lat: String(lat + 0.00001),
    max_lon: String(lon + 0.00001),
    min_lat: String(lat - 0.00001),
    min_lon: String(lon - 0.00001),
    zoom: "16",
  });
  const result = requireBody(
    await browserFetch<PublicInBoundsResponse>(
      page,
      `/v1/features/in-bounds?${params.toString()}`,
    ),
    "public in-bounds",
  );
  expect(result.data.mode).toBe("items");
  expect(result.data.truncated).toBe(false);
  expect(result.data.coverage.returned).toBeLessThan(
    result.data.coverage.limit,
  );
  expect(result.data.items.map((item) => item.feature_id)).not.toContain(
    featureId,
  );
}

function requiredSearchCursor(
  response: FeatureSearchResponse,
  label: string,
): string {
  const cursor = response.meta.page?.next_cursor;
  if (typeof cursor !== "string" || cursor.length === 0) {
    throw new Error(`${label} cursor가 없습니다 (value redacted)`);
  }
  return cursor;
}

function tamperCursorPayload(cursor: string): string {
  const segments = cursor.split(".");
  if (
    segments.length !== 2 ||
    segments[0].length === 0 ||
    segments[1].length === 0
  ) {
    throw new Error("search cursor wire shape이 올바르지 않습니다 (value redacted)");
  }
  const first = segments[0][0];
  const replacement = first === "A" ? "B" : "A";
  return `${replacement}${segments[0].slice(1)}.${segments[1]}`;
}

async function assertSearchProblem(
  page: Page,
  params: URLSearchParams,
  code: "CURSOR_QUERY_MISMATCH" | "FEATURE_SEARCH_CURSOR_TAMPERED",
  forbiddenCursors: string[],
): Promise<void> {
  const result = await browserFetch<FeatureSearchProblem>(
    page,
    `/v1/features/search?${params.toString()}`,
  );
  expect(result.status).toBe(422);
  expect(result.contentType?.startsWith("application/problem+json")).toBe(true);
  if (result.body === null) {
    throw new Error("feature search problem body가 없습니다 (response redacted)");
  }
  expect(result.body.code).toBe(code);
  const serialized = JSON.stringify(result.body);
  for (const cursor of forbiddenCursors) {
    expect(serialized).not.toContain(cursor);
  }
}

async function assertSearchCursorContract(page: Page): Promise<void> {
  const owned = new Set(SEARCH_FEATURES.map(({ featureId }) => featureId));
  const firstWithoutTotal = requireBody(
    await browserFetch<FeatureSearchResponse>(
      page,
      `/v1/features/search?${new URLSearchParams({
        include_total: "false",
        page_size: "1",
        q: SEARCH_QUERY,
      }).toString()}`,
    ),
    "feature search without total first page",
  );
  expect(firstWithoutTotal.meta.page?.total).toBeNull();
  expect(firstWithoutTotal.data.items).toHaveLength(1);
  const firstWithoutTotalId = firstWithoutTotal.data.items[0].feature_id;
  expect(owned.has(firstWithoutTotalId)).toBe(true);
  const withoutTotalCursor = requiredSearchCursor(
    firstWithoutTotal,
    "without-total first page",
  );

  const secondWithoutTotal = requireBody(
    await browserFetch<FeatureSearchResponse>(
      page,
      `/v1/features/search?${new URLSearchParams({
        cursor: withoutTotalCursor,
        include_total: "false",
        page_size: "1",
        q: SEARCH_QUERY,
      }).toString()}`,
    ),
    "feature search without total continuation",
  );
  expect(secondWithoutTotal.meta.page?.total).toBeNull();
  expect(secondWithoutTotal.data.items).toHaveLength(1);
  expect(owned.has(secondWithoutTotal.data.items[0].feature_id)).toBe(true);
  expect(secondWithoutTotal.data.items[0].feature_id).not.toBe(
    firstWithoutTotalId,
  );

  const firstWithTotal = requireBody(
    await browserFetch<FeatureSearchResponse>(
      page,
      `/v1/features/search?${new URLSearchParams({
        include_total: "true",
        page_size: "1",
        q: SEARCH_QUERY,
      }).toString()}`,
    ),
    "feature search with total first page",
  );
  expect(firstWithTotal.meta.page?.total).toBe(2);
  expect(firstWithTotal.data.items).toHaveLength(1);
  const firstWithTotalId = firstWithTotal.data.items[0].feature_id;
  expect(owned.has(firstWithTotalId)).toBe(true);
  const withTotalCursor = requiredSearchCursor(
    firstWithTotal,
    "with-total first page",
  );

  const secondWithTotal = requireBody(
    await browserFetch<FeatureSearchResponse>(
      page,
      `/v1/features/search?${new URLSearchParams({
        cursor: withTotalCursor,
        include_total: "true",
        page_size: "1",
        q: SEARCH_QUERY,
      }).toString()}`,
    ),
    "feature search with total continuation",
  );
  expect(secondWithTotal.meta.page?.total).toBe(2);
  expect(secondWithTotal.data.items).toHaveLength(1);
  expect(owned.has(secondWithTotal.data.items[0].feature_id)).toBe(true);
  expect(secondWithTotal.data.items[0].feature_id).not.toBe(firstWithTotalId);

  await assertSearchProblem(
    page,
    new URLSearchParams({
      cursor: withoutTotalCursor,
      include_total: "false",
      page_size: "1",
      q: `${SEARCH_QUERY} changed`,
    }),
    "CURSOR_QUERY_MISMATCH",
    [withoutTotalCursor],
  );
  await assertSearchProblem(
    page,
    new URLSearchParams({
      cursor: withoutTotalCursor,
      include_total: "true",
      page_size: "1",
      q: SEARCH_QUERY,
    }),
    "CURSOR_QUERY_MISMATCH",
    [withoutTotalCursor],
  );
  const tamperedCursor = tamperCursorPayload(withoutTotalCursor);
  await assertSearchProblem(
    page,
    new URLSearchParams({
      cursor: tamperedCursor,
      include_total: "false",
      page_size: "1",
      q: SEARCH_QUERY,
    }),
    "FEATURE_SEARCH_CURSOR_TAMPERED",
    [withoutTotalCursor, tamperedCursor],
  );
}

async function assertAdminInBoundsIncludes(
  page: Page,
  fixture: { featureId: string; lat: number; lon: number },
  kind: "price" | "weather",
): Promise<void> {
  const params = new URLSearchParams({
    kind,
    max_items: "100",
    max_lat: String(fixture.lat + 0.0005),
    max_lon: String(fixture.lon + 0.0005),
    min_lat: String(fixture.lat - 0.0005),
    min_lon: String(fixture.lon - 0.0005),
    status: "hidden",
    zoom: "16",
  });
  const result = requireBody(
    await browserFetch<InBoundsResponse>(
      page,
      `/v1/admin/features/in-bounds?${params.toString()}`,
    ),
    "admin in-bounds",
  );
  expect(result.data.items.map((item) => item.feature_id)).toContain(
    fixture.featureId,
  );
}

async function assertStatusMarker(
  page: Page,
  fixture: (typeof STATUS_FEATURES)[number],
): Promise<void> {
  await page.goto("/features");
  await expect(page.getByRole("heading", { name: "Feature 지도" })).toBeVisible(
    {
      timeout: UI_TIMEOUT,
    },
  );
  const placeToggle = page
    .getByTestId("kind-filter")
    .getByRole("button", { exact: true, name: "place" });
  if ((await placeToggle.getAttribute("aria-pressed")) !== "true") {
    await placeToggle.click();
  }
  await page.getByLabel("상태 필터").selectOption(fixture.status);
  const zoomIn = page.locator(".maplibregl-ctrl-zoom-in");
  await expect(zoomIn).toBeVisible({ timeout: UI_TIMEOUT });
  const inBoundsResponsePromise = page.waitForResponse(
    async (response) => {
      if (
        response.request().method() !== "GET" ||
        response.status() !== 200 ||
        responseApiPath(response) !== "/v1/admin/features/in-bounds"
      ) {
        return false;
      }
      const params = new URL(response.url()).searchParams;
      if (
        params.get("status") !== fixture.status ||
        Number(params.get("zoom")) < 14
      ) {
        return false;
      }
      const body = (await response.json()) as InBoundsResponse;
      return body.data.items.some(
        (item) => item.feature_id === fixture.featureId,
      );
    },
    { timeout: FLOW_TIMEOUT },
  );
  for (let index = 0; index < 9; index += 1) {
    await zoomIn.click();
  }
  const inBoundsResponse = await inBoundsResponsePromise;
  expect(inBoundsResponse.status()).toBe(200);

  const marker = page.getByLabel(`${fixture.name} (place)`, { exact: true });
  await expect(marker).toBeVisible({ timeout: UI_TIMEOUT });
  await marker.click();
  const detail = page.getByTestId("feature-detail-panel");
  await expect(detail).toContainText(fixture.name);
  await expect(detail).toContainText(
    fixture.status === "draft"
      ? "초안"
      : fixture.status === "inactive"
        ? "비활성"
        : "숨김",
  );

  expect(
    (await browserFetch(page, publicFeaturePath(fixture.featureId))).status,
  ).toBe(404);
  await assertPublicInBoundsExcludes(
    page,
    fixture.featureId,
    fixture.lon,
    fixture.lat,
  );
}

async function assertNonpublicKindCards(page: Page): Promise<void> {
  await assertAdminInBoundsIncludes(page, WEATHER_FEATURE, "weather");
  const weather = requireBody(
    await browserFetch<WeatherResponse>(
      page,
      `${adminFeaturePath(WEATHER_FEATURE.featureId)}/weather`,
    ),
    "hidden weather admin card",
  );
  expect(weather.data.feature_id).toBe(WEATHER_FEATURE.featureId);
  expect(weather.data.metrics).toHaveLength(1);
  expect(weather.data.metrics[0]).toMatchObject({ metric_key: "TMP" });
  expect(
    (
      await browserFetch(
        page,
        `${publicFeaturePath(WEATHER_FEATURE.featureId)}/weather`,
      )
    ).status,
  ).toBe(404);
  expect(
    (await browserFetch(page, publicFeaturePath(WEATHER_FEATURE.featureId)))
      .status,
  ).toBe(404);
  await assertPublicInBoundsExcludes(
    page,
    WEATHER_FEATURE.featureId,
    WEATHER_FEATURE.lon,
    WEATHER_FEATURE.lat,
  );

  await page.goto(`/features/${encodeURIComponent(WEATHER_FEATURE.featureId)}`);
  const weatherPanel = page.getByTestId("feature-weather-panel");
  await expect(weatherPanel).toBeVisible({ timeout: UI_TIMEOUT });
  await expect(weatherPanel).toContainText("TMP");
  await expect(weatherPanel).toContainText("인수 기온");
  await expect(weatherPanel.getByText("weather 호출 실패")).toHaveCount(0);

  await assertAdminInBoundsIncludes(page, PRICE_FEATURE, "price");
  const price = requireBody(
    await browserFetch<PriceResponse>(
      page,
      `${adminFeaturePath(PRICE_FEATURE.featureId)}/price`,
    ),
    "hidden price admin card",
  );
  expect(price.data.feature_id).toBe(PRICE_FEATURE.featureId);
  expect(price.data.current).toHaveLength(1);
  expect(price.data.history).toHaveLength(1);
  expect(price.data.current[0]).toMatchObject({ product_key: "gasoline" });
  expect(
    (
      await browserFetch(
        page,
        `${publicFeaturePath(PRICE_FEATURE.featureId)}/price`,
      )
    ).status,
  ).toBe(404);
  expect(
    (await browserFetch(page, publicFeaturePath(PRICE_FEATURE.featureId)))
      .status,
  ).toBe(404);
  await assertPublicInBoundsExcludes(
    page,
    PRICE_FEATURE.featureId,
    PRICE_FEATURE.lon,
    PRICE_FEATURE.lat,
  );

  await page.goto(`/features/${encodeURIComponent(PRICE_FEATURE.featureId)}`);
  const pricePanel = page.getByTestId("feature-price-panel");
  await expect(pricePanel).toBeVisible({ timeout: UI_TIMEOUT });
  await expect(pricePanel).toContainText("gasoline");
  await expect(pricePanel).toContainText("1,711");
  await expect(pricePanel.getByText("price 호출 실패")).toHaveCount(0);
}

async function assertStaleCorrection(page: Page): Promise<void> {
  if (RECOVERY_ONLY) {
    throw new Error("recovery-only는 correction write를 실행할 수 없습니다");
  }
  const revisionResponses: Array<{ entityTag: string | null; status: number }> =
    [];
  const uiPatchRequests: Request[] = [];
  page.on("response", (response) => {
    if (
      response.request().method() === "GET" &&
      responseApiPath(response) ===
        decodeURIComponent(revisionPath(CORRECTION_FEATURE.featureId))
    ) {
      revisionResponses.push({
        entityTag: response.headers()["etag"] ?? null,
        status: response.status(),
      });
    }
  });
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      requestApiPath(request) ===
        decodeURIComponent(adminFeaturePath(CORRECTION_FEATURE.featureId))
    ) {
      uiPatchRequests.push(request);
    }
  });

  await page.goto("/admin/features/change-requests");
  await page
    .getByLabel("change action", { exact: true })
    .selectOption("update");
  await page
    .getByLabel("change feature id", { exact: true })
    .fill(CORRECTION_FEATURE.featureId);
  await expect(page.getByText("데이터 로드됨")).toBeVisible({
    timeout: UI_TIMEOUT,
  });
  expect(revisionResponses.length).toBeGreaterThan(0);
  const baselineTag = revisionResponses.at(-1)?.entityTag ?? null;
  expect(baselineTag).toMatch(/^"[1-9][0-9]*"$/);
  const baselineDetail = requireBody(
    await browserFetch<DetailResponse>(
      page,
      adminFeaturePath(CORRECTION_FEATURE.featureId),
    ),
    "correction baseline detail",
  );
  expect(`"${baselineDetail.data.feature.row_revision}"`).toBe(baselineTag);

  const operatorDraft = `E2E operator dirty draft ${RUN_ID}`;
  const operatorReason = `${REASON} stale operator draft`;
  await page.getByLabel("change name", { exact: true }).fill(operatorDraft);
  await page.getByLabel("change reason", { exact: true }).fill(operatorReason);

  const competingName = `E2E approved competing update ${RUN_ID}`;
  const competing = await browserFetch<ChangeResponse>(
    page,
    adminFeaturePath(CORRECTION_FEATURE.featureId),
    {
      body: { name: competingName, reason: `${REASON} competing update` },
      headers: { "If-Match": baselineTag as string },
      method: "PATCH",
    },
  );
  const competingRequest = requireBody(competing, "competing update").data
    .request;
  if (competingRequest.status !== "pending") {
    throw new Error("competing update가 pending review를 거치지 않았습니다");
  }
  const approvedResult = await browserFetch<ChangeResponse>(
    page,
    changeActionPath(competingRequest.request_id, "approve"),
    { body: { reason: `${REASON} approve competing update` }, method: "POST" },
  );
  const approved = requireBody(approvedResult, "approve competing update");
  expect(approved.data.request.status).toBe("applied");
  const competingTag = requireEntityTag(
    approvedResult,
    "approved competing update",
  );
  expect(competingTag).not.toBe(baselineTag);
  const competingDetail = requireBody(
    await browserFetch<DetailResponse>(
      page,
      adminFeaturePath(CORRECTION_FEATURE.featureId),
    ),
    "competing detail",
  );
  expect(competingDetail.data.feature.name).toBe(competingName);
  expect(`"${competingDetail.data.feature.row_revision}"`).toBe(competingTag);

  uiPatchRequests.length = 0;
  const revisionsBeforeSubmit = revisionResponses.length;
  const staleResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      responseApiPath(response) ===
        decodeURIComponent(adminFeaturePath(CORRECTION_FEATURE.featureId)),
    { timeout: FLOW_TIMEOUT },
  );
  await page.getByRole("button", { name: "요청 생성" }).click();
  const staleResponse = await staleResponsePromise;
  expect(staleResponse.status()).toBe(412);
  expect(staleResponse.request().headers()["if-match"]).toBe(baselineTag);
  expect(uiPatchRequests).toHaveLength(1);

  const conflict = page
    .getByRole("status")
    .filter({ hasText: "서버의 Feature가 변경되었습니다" });
  await expect(conflict).toBeVisible({ timeout: UI_TIMEOUT });
  await expect(page.getByLabel("change name", { exact: true })).toHaveValue(
    operatorDraft,
  );
  await expect(page.getByLabel("change reason", { exact: true })).toHaveValue(
    operatorReason,
  );
  await page.waitForTimeout(750);
  expect(revisionResponses).toHaveLength(revisionsBeforeSubmit);
  expect(uiPatchRequests).toHaveLength(1);

  const reload = conflict.getByRole("button", {
    name: "최신값으로 폼 다시 불러오기",
  });
  await reload.click();
  await expect(page.getByLabel("change name", { exact: true })).toHaveValue(
    competingName,
  );
  await expect
    .poll(() => revisionResponses.at(-1)?.entityTag, { timeout: UI_TIMEOUT })
    .toBe(competingTag);

  const reappliedName = `E2E reapplied after reload ${RUN_ID}`;
  await page.getByLabel("change name", { exact: true }).fill(reappliedName);
  await page
    .getByLabel("change reason", { exact: true })
    .fill(`${REASON} reapply after reload`);
  const secondResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      responseApiPath(response) ===
        decodeURIComponent(adminFeaturePath(CORRECTION_FEATURE.featureId)),
    { timeout: FLOW_TIMEOUT },
  );
  await page.getByRole("button", { name: "요청 생성" }).click();
  const secondResponse = await secondResponsePromise;
  expect(secondResponse.status()).toBe(200);
  expect(secondResponse.request().headers()["if-match"]).toBe(competingTag);
  const reapplied = (await secondResponse.json()) as ChangeResponse;
  expect(reapplied.data.request.status).toBe("pending");
  const rejected = await approveOrReject(
    page,
    reapplied.data.request.request_id,
    "reject",
    `${REASON} reject reapply fixture`,
  );
  expect(rejected.data.request.status).toBe("rejected");
}

test("@admin-feature-live-acceptance #741/#785 owned production acceptance", async ({
  page,
}) => {
  test.skip(
    !EXECUTE,
    "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1일 때만 targeted production write lane 실행",
  );
  test.setTimeout(20 * 60 * 1000);
  await page.goto("/");
  if (RECOVERY_ONLY) {
    await cleanupApiOwnedFeatures(page);
    return;
  }

  let primaryError: unknown = null;
  try {
    for (const fixture of STATUS_FEATURES) {
      await createOwnedPlace(page, fixture);
    }
    await createOwnedPlace(page, {
      ...CORRECTION_FEATURE,
      status: "active",
    });
    for (const fixture of SEARCH_FEATURES) {
      await createOwnedPlace(page, fixture);
    }

    for (const fixture of STATUS_FEATURES) {
      await test.step(`${fixture.status} admin marker와 public 음성`, () =>
        assertStatusMarker(page, fixture));
    }
    await test.step("hidden weather/price admin card와 UI panel", () =>
      assertNonpublicKindCards(page));
    await test.step("T-VN-15 search total/cursor/mismatch/tamper", () =>
      assertSearchCursorContract(page));
    await test.step("approved competing update 뒤 stale raw If-Match 412", () =>
      assertStaleCorrection(page));
  } catch (error: unknown) {
    primaryError = error;
  }

  let cleanupError: unknown = null;
  try {
    await cleanupApiOwnedFeatures(page);
  } catch (error: unknown) {
    cleanupError = error;
  }
  if (cleanupError !== null) {
    throw cleanupError;
  }
  if (primaryError !== null) {
    throw primaryError;
  }
});
