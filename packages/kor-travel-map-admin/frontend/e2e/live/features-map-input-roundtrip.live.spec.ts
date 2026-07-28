import {
  expect,
  test,
  type Locator,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";

import type { components } from "../../src/api/types";
import { MAP_VIEWS } from "./_fixtures";

/**
 * LIVE (non-mock) e2e for `/features` (Feature 지도) — *입력 라운드트립* 깊이.
 *
 * features-map.live.spec.ts(스모크: 로드/탭/칩 노출/딥링크/마커 존재/클러스터 줌)와
 * features-map-interactions.spec.ts(route-mock 깊이)가 다루지 않는 **실 API 계약
 * 라운드트립**만 더한다 — 전부 READ-ONLY(GET only, 백엔드 변경 없음)이므로 게이팅하지
 * 않는다(읽기 전용 input 라운드트립은 비게이트 규약):
 *   A. 지도 뷰포트 이동(MAP_VIEWS) → `GET /v1/admin/features/in-bounds`가 새 bbox 파라미터로 호출 →
 *      응답 본문이 요청 bbox 안 feature만 → DOM viewport 텍스트/카운트/마커가 반영.
 *   B. kind 칩 토글 → 요청에 `kind=` 파라미터 → 서버가 해당 kind만 반환 → 카운트/마커 반영.
 *   C. 점 마커 클릭 → `GET /v1/admin/features/{id}` → 상세 패널이 실제 backend feature를 반영.
 *
 * 셀렉터/파라미터는 소스에서 검증한 것만 사용한다:
 *   - bbox 파라미터 이름: src/api/features.ts adminFeaturesInBoundsPath (min_lon/min_lat/
 *     max_lon/max_lat/max_items/kind/include_geometry/zoom).
 *   - 지도 인스턴스 e2e 훅: components/vworld-map-view.tsx (`container._maplibreMap`).
 *   - 클러스터/점 마커 aria-label·role=button, 상세 패널 testId/닫기: 동 컴포넌트 +
 *     app/features/features-client.tsx FeatureDetailPanel.
 */

type FeaturesInBboxResponse = components["schemas"]["FeaturesInBboxResponse"];
type AdminFeatureMapItem = components["schemas"]["AdminFeatureMapItem"];
type AdminFeatureMapCluster = components["schemas"]["AdminFeatureCluster"];
type AdminFeaturesInBoundsResponse =
  components["schemas"]["AdminFeaturesInBoundsResponse"];
type AdminFeatureDetailResponse =
  components["schemas"]["AdminFeatureDetailResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;
const REQUEST_BBOX_EPS = 1e-7;

const ADMIN_FEATURES_IN_BOUNDS_PATH = "/v1/admin/features/in-bounds";
const MAP_CONTAINER = '[data-testid="map-canvas-container"]';
const POINT_MARKER =
  '.maplibregl-marker[role="button"]:not([aria-label^="feature 클러스터"])';
const SERVER_CLUSTER_MARKER =
  '.maplibregl-marker[role="button"][aria-label^="feature 클러스터"]';
// 멀리 떨어진 사전 점프 기준점(제주). 초기 뷰가 우연히 타깃과 같아 moveend가 안 떠
// refetch가 누락되는 경우를 막는다. 본 spec의 어떤 타깃(서울/부산/전국)과도 겹치지 않는다.
const ANCHOR = { lon: 126.531, lat: 33.499, zoom: 11 } as const;

// 상세 패널의 status 배지는 영어 enum이 아니라 한글로 렌더된다(features-client.tsx
// FeatureDetailPanel → `statusLabel(...)`). 렌더 텍스트를 단언하려면 같은 매핑이
// 필요하다. 정본은 src/components/status-badge.tsx의 STATUS_LABELS — 동기화 유지.
// (component를 직접 import하지 않는 이유: Playwright 런타임이 `@/` 별칭을 풀지 않아
//  status-badge.tsx의 `@/lib/utils` import가 깨진다. 그래서 순수 매핑만 미러링한다.)
const STATUS_LABELS: Record<string, string> = {
  ok: "정상", normal: "정상", success: "성공", succeeded: "성공", done: "완료",
  completed: "완료", active: "활성", accepted: "수락됨", merged: "병합됨",
  resolved: "해결됨", started: "시작됨", applied: "반영됨", curated: "큐레이션됨",
  validated: "검증됨", loaded: "적재됨", implemented: "구현됨", fresh: "최신",
  queued: "대기", pending: "대기", loading: "로딩중", running: "실행중",
  starting: "시작중", dry_run: "모의실행", validating: "검증중", in_progress: "진행중",
  materializing: "구체화중", scheduled: "예정됨", planned: "예정됨", ongoing: "진행중",
  managed: "관리됨", acknowledged: "확인됨", open: "열림", candidate: "후보",
  uploaded: "업로드됨", canceling: "취소중", paused: "일시정지", connecting: "연결중",
  reconnecting: "재연결중", error: "오류", failed: "실패", failure: "실패",
  cancelled: "취소됨", canceled: "취소됨", unavailable: "사용불가", critical: "심각",
  rejected: "거절됨", denied: "거부됨", inactive: "비활성", deleted: "삭제됨",
  disabled: "비활성화", expired: "만료됨", archived: "보관됨", deprecated: "지원중단",
  revoked: "폐기됨", skipped: "건너뜀", validation_failed: "검증실패",
  load_failed: "적재실패", not_found: "없음", degraded: "저하됨",
  manual_required: "수동 필요", provider_needed: "공급자 필요", manual_only: "수동 전용",
  ended: "종료됨", stopped: "중지됨", ignored: "무시됨", hidden: "숨김",
  not_started: "시작 전", stale: "오래됨", draft: "초안", unknown: "알수없음",
  none: "없음", info: "정보", warning: "경고", debug: "디버그",
};

/** status-badge.tsx statusLabel 미러: 영어 enum → 한글(미지정은 원문 fallback). */
function statusLabel(status: string): string {
  return STATUS_LABELS[status.toLowerCase().replace(/-/g, "_")] ?? status;
}

test.describe.configure({ mode: "serial" });

// ── gold-standard에서 verbatim 복사한 헬퍼 ─────────────────────────────────

function apiPathFromUrl(url: string): string {
  const pathname = new URL(url).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function apiPath(response: Response): string {
  return apiPathFromUrl(response.url());
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: { body?: unknown; method?: "GET" | "POST" | "PATCH" | "DELETE" } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
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
      return { body: parsed as T | null, status: response.status, text };
    },
    {
      body: options.body,
      method: options.method ?? "GET",
      path,
    },
  );
}

// ── features bbox/detail 쿼리 인식(파라미터-aware 술어) ─────────────────────

interface InBoundsBbox {
  maxItems: number | null;
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
  kinds: string[];
  zoom: number | null;
}

function isAdminFeaturesInBounds(response: Response): boolean {
  return (
    response.request().method() === "GET" &&
    apiPath(response) === ADMIN_FEATURES_IN_BOUNDS_PATH
  );
}

function adminInBoundsPath(
  bounds: { e: number; n: number; s: number; w: number },
  zoom: number,
  kinds: readonly string[],
): string {
  const query = new URLSearchParams({
    max_items: "2000",
    max_lat: String(bounds.n),
    max_lon: String(bounds.e),
    min_lat: String(bounds.s),
    min_lon: String(bounds.w),
    zoom: String(Math.floor(zoom)),
  });
  for (const kind of kinds) query.append("kind", kind);
  return `${ADMIN_FEATURES_IN_BOUNDS_PATH}?${query.toString()}`;
}

function inBoundsBboxFromUrl(url: string): InBoundsBbox {
  const sp = new URL(url).searchParams;
  const maxItemsRaw = sp.get("max_items");
  const zoomRaw = sp.get("zoom");
  return {
    maxItems: maxItemsRaw === null ? null : Number(maxItemsRaw),
    minLon: Number(sp.get("min_lon")),
    minLat: Number(sp.get("min_lat")),
    maxLon: Number(sp.get("max_lon")),
    maxLat: Number(sp.get("max_lat")),
    kinds: sp.getAll("kind"),
    zoom: zoomRaw === null ? null : Number(zoomRaw),
  };
}

function inBoundsBbox(response: Response): InBoundsBbox {
  return inBoundsBboxFromUrl(response.url());
}

/** 응답이 `(lon,lat)`를 bbox로 감싸는 admin 개별-item 호출인가. */
function adminItemsContains(
  response: Response,
  lon: number,
  lat: number,
): boolean {
  if (!isAdminFeaturesInBounds(response)) return false;
  const b = inBoundsBbox(response);
  if (
    b.zoom === null ||
    b.zoom <= 13 ||
    [b.minLon, b.minLat, b.maxLon, b.maxLat].some((value) =>
      Number.isNaN(value),
    )
  ) {
    return false;
  }
  return (
    b.minLon <= lon && lon <= b.maxLon && b.minLat <= lat && lat <= b.maxLat
  );
}

// 선택한 feature의 admin 단건 상세만 허용한다. weather/revision 등 하위 요청이나
// 다른 feature의 상세 응답이 먼저 와도 잘못 통과하지 않는다.
function isAdminFeatureDetail(
  response: Response,
  featureId: string,
): boolean {
  return (
    response.request().method() === "GET" &&
    apiPath(response) === `/v1/admin/features/${featureId}`
  );
}

// ── 지도 인스턴스 제어/판독(컨테이너 DOM에 매달린 _maplibreMap 훅) ──────────

async function jumpMap(
  page: Page,
  lon: number,
  lat: number,
  zoom: number,
): Promise<void> {
  await page.evaluate(
    ({ lon, lat, sel, zoom }) => {
      const container = document.querySelector(sel) as
        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
        | null;
      container?._maplibreMap?.jumpTo({ center: [lon, lat], zoom });
    },
    { lon, lat, sel: MAP_CONTAINER, zoom },
  );
}

/** jump/query cache hit 모두에서 MapLibre source→DOM marker 동기화가 끝날 때까지 기다린다. */
async function waitForMapIdle(page: Page): Promise<void> {
  await page.evaluate(async (sel) => {
    const container = document.querySelector(sel) as
      | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
      | null;
    const map = container?._maplibreMap;
    if (!map) throw new Error("MapLibre instance is not attached");

    await new Promise<void>((resolve) => {
      const settleAfterPaint = () => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      };
      if (map.loaded() && !map.isMoving()) {
        settleAfterPaint();
        return;
      }
      map.once("idle", settleAfterPaint);
    });
  }, MAP_CONTAINER);
}

function isFeatureCollectionRequest(request: Request): boolean {
  if (request.method() !== "GET") return false;
  const path = apiPathFromUrl(request.url());
  return (
    path === ADMIN_FEATURES_IN_BOUNDS_PATH ||
    path === "/v1/admin/features" ||
    path === "/v1/features" ||
    path === "/v1/features/in-bounds"
  );
}

/**
 * reset은 cache hit이면 HTTP가 없고, stale/ops-live invalidation이면 refetch한다.
 * 두 경로를 모두 허용하되 reset이 촉발한 collection request가 있다면 응답까지 회수해
 * 호출 계약과 최종 DOM을 그 응답에 맞춰 검증할 수 있게 한다.
 */
async function captureFeatureCollectionResponsesDuring(
  page: Page,
  action: () => Promise<void>,
): Promise<{ requests: Request[]; responses: Response[] }> {
  const observed: Request[] = [];
  const onRequest = (request: Request) => {
    if (isFeatureCollectionRequest(request)) observed.push(request);
  };
  page.on("request", onRequest);
  try {
    await action();
    // React Query의 stale/background refetch effect가 reset render 직후 예약될 수 있다.
    await page.waitForTimeout(1_000);
  } finally {
    page.off("request", onRequest);
  }
  const responses = (
    await Promise.all(
      observed.map(async (request) => {
        const response = await request.response();
        const finishError =
          response === null ? null : await response.finished();
        const failureText =
          request.failure()?.errorText ?? finishError?.message ?? "";
        if (failureText.length === 0 && response !== null) return response;
        expect(
          failureText,
          `취소 사유 없는 feature collection GET: ${request.url()}`,
        ).toMatch(/abort|cancel/i);
        return null;
      }),
    )
  ).filter((response): response is Response => response !== null);
  if (observed.length > 0) {
    expect(
      responses.length,
      "refetch가 발생했으면 취소 요청 뒤 최종 성공 응답이 있어야 함",
    ).toBeGreaterThan(0);
  }
  return { requests: observed, responses };
}

function serverClusterSignature(cluster: AdminFeatureMapCluster): string {
  return JSON.stringify([
    cluster.cluster_key,
    String(cluster.feature_count),
    String(cluster.lon),
    String(cluster.lat),
  ]);
}

async function serverClustersMatchRenderedState(
  page: Page,
  clusters: readonly AdminFeatureMapCluster[],
): Promise<boolean> {
  return page.evaluate(
    ({ clusters, mapSelector, markerSelector, pointMarkerSelector }) => {
      const container = document.querySelector(mapSelector) as
        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
        | null;
      const map = container?._maplibreMap;
      if (!container || !map) return false;
      if (document.querySelectorAll(pointMarkerSelector).length !== 0) {
        return false;
      }

      const elements = Array.from(
        document.querySelectorAll<HTMLElement>(markerSelector),
      );
      if (elements.length !== clusters.length) return false;
      const byKey = new Map<string, HTMLElement>();
      for (const element of elements) {
        const key = element.dataset.clusterKey;
        if (!key || byKey.has(key)) return false;
        byKey.set(key, element);
      }

      const containerRect = container.getBoundingClientRect();
      for (const cluster of clusters) {
        const element = byKey.get(cluster.cluster_key);
        if (!element) return false;
        const label =
          cluster.feature_count >= 1_000_000
            ? `${(cluster.feature_count / 1_000_000).toFixed(1)}M`
            : cluster.feature_count >= 10_000
              ? `${Math.round(cluster.feature_count / 1000)}k`
              : cluster.feature_count >= 1000
                ? `${(cluster.feature_count / 1000).toFixed(1)}k`
                : String(cluster.feature_count);
        if (
          element.getAttribute("aria-label") !==
            `feature 클러스터 ${cluster.feature_count}건` ||
          element.textContent !== label
        ) {
          return false;
        }
        const expected = map.project([cluster.lon, cluster.lat]);
        const rect = element.getBoundingClientRect();
        const actualX = rect.left + rect.width / 2 - containerRect.left;
        const actualY = rect.top + rect.height / 2 - containerRect.top;
        if (
          Math.abs(actualX - expected.x) > 1.5 ||
          Math.abs(actualY - expected.y) > 1.5
        ) {
          return false;
        }
      }
      return true;
    },
    {
      clusters,
      mapSelector: MAP_CONTAINER,
      markerSelector: SERVER_CLUSTER_MARKER,
      pointMarkerSelector: POINT_MARKER,
    },
  );
}

/** 서버 cluster 응답의 key/count/centroid 전체와 DOM marker 집합을 exact 비교한다. */
async function waitForExactServerClusters(
  page: Page,
  clusters: readonly AdminFeatureMapCluster[],
): Promise<void> {
  expect(clusters.length).toBeGreaterThan(0);
  await expect
    .poll(
      async () => serverClustersMatchRenderedState(page, clusters),
      { timeout: 30_000 },
    )
    .toBe(true);
}

function expectedPointFeatureIds(
  items: readonly AdminFeatureMapItem[],
): string[] {
  return Array.from(
    new Set(
      items
        .filter(
          (item) =>
            typeof item.lon === "number" && typeof item.lat === "number",
        )
        .map((item) => item.feature_id),
    ),
  ).sort();
}

async function readPointMarkerFeatureIds(page: Page): Promise<string[]> {
  return page.locator(POINT_MARKER).evaluateAll((elements) =>
    elements
      .map((element) => (element as HTMLElement).dataset.featureId ?? "")
      .sort(),
  );
}

/** 실제 admin 응답의 전체 point Feature ID 집합과 DOM marker 집합을 exact 비교한다. */
async function waitForExactPointMarkers(
  page: Page,
  items: readonly AdminFeatureMapItem[],
): Promise<void> {
  const expected = expectedPointFeatureIds(items);
  await expect
    .poll(
      async () => ({
        pointFeatureIds: await readPointMarkerFeatureIds(page),
        serverClusterCount: await page.locator(SERVER_CLUSTER_MARKER).count(),
      }),
      { timeout: 30_000 },
    )
    .toEqual({
      pointFeatureIds: expected,
      serverClusterCount: 0,
    });
}

async function pointMarkerForFeatureId(
  page: Page,
  featureId: string,
): Promise<Locator> {
  const markers = page.locator(POINT_MARKER);
  const indexes = await markers.evaluateAll((elements, expectedId) => {
    const matches: number[] = [];
    for (const [index, element] of elements.entries()) {
      if ((element as HTMLElement).dataset.featureId === expectedId) {
        matches.push(index);
      }
    }
    return matches;
  }, featureId);
  expect(indexes).toHaveLength(1);
  return markers.nth(indexes[0]);
}

async function coincidentPopupRowForFeatureId(
  page: Page,
  featureId: string,
): Promise<Locator> {
  const rows = page.locator(".maplibregl-popup button");
  const indexes = await rows.evaluateAll((elements, expectedId) => {
    const matches: number[] = [];
    for (const [index, element] of elements.entries()) {
      if ((element as HTMLElement).dataset.featureId === expectedId) {
        matches.push(index);
      }
    }
    return matches;
  }, featureId);
  expect(indexes).toHaveLength(1);
  return rows.nth(indexes[0]);
}

async function expectedCoincidentFeatureIds(
  page: Page,
  items: readonly AdminFeatureMapItem[],
  targetFeatureId: string,
): Promise<string[]> {
  return page.evaluate(
    ({ items, mapSelector, targetFeatureId }) => {
      const container = document.querySelector(mapSelector) as
        | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
        | null;
      const map = container?._maplibreMap;
      if (!map) return [];

      const target = items.find(
        (item) =>
          item.feature_id === targetFeatureId &&
          typeof item.lon === "number" &&
          typeof item.lat === "number",
      );
      if (
        !target ||
        typeof target.lon !== "number" ||
        typeof target.lat !== "number"
      ) {
        return [];
      }

      const targetPoint = map.project([target.lon, target.lat]);
      const targetCell = `${Math.round(targetPoint.x / 24)}:${Math.round(
        targetPoint.y / 24,
      )}`;
      return Array.from(
        new Set(
          items
            .filter((item) => {
              if (
                typeof item.lon !== "number" ||
                typeof item.lat !== "number"
              ) {
                return false;
              }
              const point = map.project([item.lon, item.lat]);
              return (
                `${Math.round(point.x / 24)}:${Math.round(point.y / 24)}` ===
                targetCell
              );
            })
            .map((item) => item.feature_id),
        ),
      ).sort();
    },
    {
      items,
      mapSelector: MAP_CONTAINER,
      targetFeatureId,
    },
  );
}

async function readCoincidentPopupFeatureIds(page: Page): Promise<string[]> {
  return page.locator(".maplibregl-popup button").evaluateAll((elements) =>
    elements
      .map((element) => (element as HTMLElement).dataset.featureId ?? "")
      .sort(),
  );
}

async function readMapBounds(
  page: Page,
): Promise<{ e: number; n: number; s: number; w: number } | null> {
  return page.evaluate((sel) => {
    const container = document.querySelector(sel) as
      | (HTMLElement & { _maplibreMap?: import("maplibre-gl").Map })
      | null;
    const map = container?._maplibreMap;
    if (!map) return null;
    const bounds = map.getBounds();
    return {
      e: bounds.getEast(),
      n: bounds.getNorth(),
      s: bounds.getSouth(),
      w: bounds.getWest(),
    };
  }, MAP_CONTAINER);
}

function expectRequestBoundsToMatchMap(
  requested: InBoundsBbox,
  bounds: { e: number; n: number; s: number; w: number },
): void {
  expect(Math.abs(requested.minLon - bounds.w)).toBeLessThan(
    REQUEST_BBOX_EPS,
  );
  expect(Math.abs(requested.minLat - bounds.s)).toBeLessThan(
    REQUEST_BBOX_EPS,
  );
  expect(Math.abs(requested.maxLon - bounds.e)).toBeLessThan(
    REQUEST_BBOX_EPS,
  );
  expect(Math.abs(requested.maxLat - bounds.n)).toBeLessThan(
    REQUEST_BBOX_EPS,
  );
}

/** DOM의 "center {lon}, {lat} · z {zoom}"에서 viewport를 읽는다(Zustand가 렌더). */
async function readViewport(
  page: Page,
): Promise<{ lon: number; lat: number; zoom: number } | null> {
  const text = await page
    .getByText(/center .*· z\s/)
    .first()
    .textContent();
  const match = text
    ? /center\s*(-?[\d.]+),\s*(-?[\d.]+)\s*·\s*z\s*([\d.]+)/.exec(text)
    : null;
  return match
    ? { lon: Number(match[1]), lat: Number(match[2]), zoom: Number(match[3]) }
    : null;
}

/** 헤더 status 배지 "{N}건 표시"의 N을 읽는다(= featuresQuery items.length). */
async function readFeatureCount(page: Page): Promise<number> {
  const text = await page
    .getByText(/\d+건 표시/)
    .first()
    .textContent();
  const match = text?.match(/(\d+)건 표시/);
  return match ? Number(match[1]) : -1;
}

async function gotoFeaturesReady(page: Page): Promise<void> {
  await page.goto("/features");
  await expect(
    page.getByRole("heading", { level: 1, name: "Feature 지도" }),
  ).toBeVisible(T);
  await expect(page.getByTestId("map-canvas-container")).toBeAttached(T);
  // 마커가 떠야 지도 load + 기본(전국) 데이터 렌더 완료 → _maplibreMap 조작이 안전.
  await expect(page.locator(".maplibregl-marker").first()).toBeVisible({
    timeout: 30_000,
  });
}

const EPS = 0.0005;

// MAP_VIEWS에서 dense city를 골라 고배율 개별 feature fetch 라운드트립을 검증한다.
const A_VIEWS = MAP_VIEWS.filter(([name]) =>
  ["서울", "부산"].includes(name as string),
).map(([name, lon, lat]) => [name, lon, lat, 15] as const);

test.describe("/features live — map input round-trip (read-only)", () => {
  // 라이브 지도 + 타일 fetch는 타이밍 의존 → flaky 제한용 retries=1.
  test.describe.configure({ retries: 1 });

  test("초기 저zoom 클러스터 요청은 기본 kind=weather,notice를 사용하고 토글 선택을 반영", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    const initialCluster = page.waitForResponse(
      (response) =>
        isAdminFeaturesInBounds(response) &&
        inBoundsBbox(response).zoom !== null &&
        (inBoundsBbox(response).zoom as number) <= 13 &&
        inBoundsBbox(response).kinds.join(",") === "weather,notice",
      { timeout: FLOW_TIMEOUT },
    );

    await page.goto("/features");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feature 지도" }),
    ).toBeVisible(T);
    await expect(page.getByTestId("map-canvas-container")).toBeAttached(T);

    const initialResponse = await initialCluster;
    expect(initialResponse.status()).toBe(200);
    const initialRequest = inBoundsBbox(initialResponse);
    expect(initialRequest.zoom).not.toBeNull();
    expect(initialRequest.zoom as number).toBeLessThanOrEqual(13);
    expect(initialRequest.maxItems).not.toBeNull();
    expect(initialRequest.maxItems as number).toBeGreaterThan(0);

    const initialBody =
      (await initialResponse.json()) as AdminFeaturesInBoundsResponse;
    expect(initialBody.data.mode).toBe("clusters");
    expect(Array.isArray(initialBody.data.clusters)).toBe(true);
    expect(initialBody.data.clusters.length).toBeGreaterThan(0);
    await waitForMapIdle(page);
    await waitForExactServerClusters(page, initialBody.data.clusters);

    const filter = page.getByTestId("kind-filter");
    const weatherChip = filter.getByRole("button", {
      name: "weather",
      exact: true,
    });
    const noticeChip = filter.getByRole("button", {
      name: "notice",
      exact: true,
    });
    const placeChip = filter.getByRole("button", {
      name: "place",
      exact: true,
    });
    const reset = filter.getByRole("button", { name: "초기화" });
    await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
    await expect(reset).toBeDisabled(T);

    const placeCluster = page.waitForResponse(
      (response) =>
        isAdminFeaturesInBounds(response) &&
        inBoundsBbox(response).zoom !== null &&
        (inBoundsBbox(response).zoom as number) <= 13 &&
        inBoundsBbox(response).kinds.join(",") === "weather,notice,place",
      { timeout: FLOW_TIMEOUT },
    );
    await placeChip.click();
    await expect(placeChip).toHaveAttribute("aria-pressed", "true", T);
    const placeResponse = await placeCluster;
    expect(placeResponse.status()).toBe(200);
    const placeBody =
      (await placeResponse.json()) as AdminFeaturesInBoundsResponse;
    expect(placeBody.data.mode).toBe("clusters");
    expect(
      placeBody.data.clusters.map(serverClusterSignature).sort(),
      "place 추가 전후 server cluster 집합이 달라야 reset 수렴을 검증할 수 있음",
    ).not.toEqual(
      initialBody.data.clusters.map(serverClusterSignature).sort(),
    );
    await waitForMapIdle(page);
    await waitForExactServerClusters(page, placeBody.data.clusters);
    await expect(reset).toBeEnabled(T);

    const resetCapture = await captureFeatureCollectionResponsesDuring(
      page,
      async () => {
        await reset.click();
        await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
        await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);
        await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
        await expect(reset).toBeDisabled(T);
        await waitForMapIdle(page);
      },
    );
    for (const request of resetCapture.requests) {
      expect(apiPathFromUrl(request.url())).toBe(
        ADMIN_FEATURES_IN_BOUNDS_PATH,
      );
      const bbox = inBoundsBboxFromUrl(request.url());
      expect(bbox.zoom).not.toBeNull();
      expect(bbox.zoom as number).toBeLessThanOrEqual(13);
      expect(bbox.kinds.join(",")).toBe("weather,notice");
    }
    let resetBody = initialBody;
    for (const response of resetCapture.responses) {
      expect(response.status()).toBe(200);
      resetBody = (await response.json()) as AdminFeaturesInBoundsResponse;
      expect(resetBody.data.mode).toBe("clusters");
    }
    const resetBounds = await readMapBounds(page);
    expect(resetBounds).not.toBeNull();
    for (const request of resetCapture.requests) {
      expectRequestBoundsToMatchMap(
        inBoundsBboxFromUrl(request.url()),
        resetBounds!,
      );
    }
    await waitForExactServerClusters(page, resetBody.data.clusters);
  });

  for (const [name, lon, lat, zoom] of A_VIEWS) {
    test(`뷰포트를 ${name}로 이동 → admin bbox 요청이 카운트/마커에 반영`, async ({
      page,
    }) => {
      test.setTimeout(FLOW_TIMEOUT);
      const targetLon = lon as number;
      const targetLat = lat as number;
      const targetZoom = zoom as number;

      await gotoFeaturesReady(page);

      // 멀리 떨어진 기준점으로 먼저 점프(초기 뷰가 타깃과 같아 moveend 누락되는 경우 방지).
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      await waitForMapIdle(page);

      // 새 target은 신규 query key이므로 exact admin response를 반드시 받아야 한다.
      const responsePromise = page.waitForResponse(
        (response) => adminItemsContains(response, targetLon, targetLat),
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, targetLon, targetLat, targetZoom);
      const response = await responsePromise;
      expect(response.status()).toBe(200);
      const requested = inBoundsBbox(response);
      expect(requested.zoom).toBe(Math.floor(targetZoom));
      expect(requested.maxItems).toBe(2000);

      const body = (await response.json()) as AdminFeaturesInBoundsResponse;
      expect(body.data.mode).toBe("items");
      expect(Array.isArray(body.data.items)).toBe(true);
      for (const item of body.data.items) {
        if (typeof item.lon === "number" && typeof item.lat === "number") {
          expect(item.lon).toBeGreaterThanOrEqual(requested.minLon - EPS);
          expect(item.lon).toBeLessThanOrEqual(requested.maxLon + EPS);
          expect(item.lat).toBeGreaterThanOrEqual(requested.minLat - EPS);
          expect(item.lat).toBeLessThanOrEqual(requested.maxLat + EPS);
        }
      }

      // 백엔드 read 라운드트립: UI와 같은 admin items 계약을 현재 bounds로 직접 조회.
      await waitForMapIdle(page);
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      expectRequestBoundsToMatchMap(requested, bounds!);
      const direct = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, targetZoom, ["weather", "notice"]),
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      expect(direct.body!.data.mode).toBe("items");
      expect(
        direct.body!.data.items.map((item) => item.feature_id).sort(),
      ).toEqual(body.data.items.map((item) => item.feature_id).sort());
      for (const item of direct.body!.data.items) {
        if (typeof item.lon === "number" && typeof item.lat === "number") {
          expect(item.lon).toBeGreaterThanOrEqual(bounds!.w - EPS);
          expect(item.lon).toBeLessThanOrEqual(bounds!.e + EPS);
          expect(item.lat).toBeGreaterThanOrEqual(bounds!.s - EPS);
          expect(item.lat).toBeLessThanOrEqual(bounds!.n + EPS);
        }
      }

      // UI 반영: DOM viewport, 카운트와 실제 marker identity가 direct admin 응답에 수렴.
      await expect
        .poll(async () => {
          const view = await readViewport(page);
          return view ? Math.abs(view.lon - targetLon) : 999;
        }, T)
        .toBeLessThan(0.2);
      await expect
        .poll(async () => {
          const view = await readViewport(page);
          return view ? Math.abs(view.zoom - targetZoom) : 999;
        }, T)
        .toBeLessThan(0.5);
      await expect(page.getByText(/\d+건 표시/).first()).toBeVisible(T);
      await expect
        .poll(async () => readFeatureCount(page), T)
        .toBe(direct.body!.data.items.length);
      await waitForExactPointMarkers(page, direct.body!.data.items);
    });
  }

  test("kind 필터 토글 → API kind 파라미터 + 서버 필터 결과가 카운트/마커에 반영", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    const SEOUL = { lon: 126.978, lat: 37.566, zoom: 15 } as const;

    await gotoFeaturesReady(page);
    const filter = page.getByTestId("kind-filter");
    const weatherChip = filter.getByRole("button", {
      name: "weather",
      exact: true,
    });
    const noticeChip = filter.getByRole("button", {
      name: "notice",
      exact: true,
    });
    const placeChip = filter.getByRole("button", {
      name: "place",
      exact: true,
    });

    try {
      // place feature가 풍부한 서울로 이동(초기 데이터 확보).
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      await waitForMapIdle(page);
      const defaultResponsePromise = page.waitForResponse(
        (response) =>
          adminItemsContains(response, SEOUL.lon, SEOUL.lat) &&
          inBoundsBbox(response).kinds.join(",") === "weather,notice",
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, SEOUL.lon, SEOUL.lat, SEOUL.zoom);
      const defaultResponse = await defaultResponsePromise;
      expect(defaultResponse.status()).toBe(200);
      const defaultBody =
        (await defaultResponse.json()) as AdminFeaturesInBoundsResponse;
      expect(defaultBody.data.mode).toBe("items");
      await waitForMapIdle(page);
      await waitForExactPointMarkers(page, defaultBody.data.items);

      await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
      await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
      await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);

      // 새 kind 조합은 신규 query key이므로 exact admin response가 필수다.
      const combinedResponsePromise = page.waitForResponse(
        (response) =>
          isAdminFeaturesInBounds(response) &&
          inBoundsBbox(response).zoom !== null &&
          (inBoundsBbox(response).zoom as number) > 13 &&
          inBoundsBbox(response).kinds.join(",") ===
            "weather,notice,place",
        { timeout: FLOW_TIMEOUT },
      );
      await placeChip.click();
      await expect(placeChip).toHaveAttribute("aria-pressed", "true", T);
      const combinedResponse = await combinedResponsePromise;
      expect(combinedResponse.status()).toBe(200);
      const combinedBody =
        (await combinedResponse.json()) as AdminFeaturesInBoundsResponse;
      expect(combinedBody.data.mode).toBe("items");
      for (const item of combinedBody.data.items) {
        expect(["weather", "notice", "place"]).toContain(item.kind);
      }
      await waitForMapIdle(page);
      await waitForExactPointMarkers(page, combinedBody.data.items);
      await expect
        .poll(async () => readFeatureCount(page), T)
        .toBe(combinedBody.data.items.length);
      await expect(filter.getByRole("button", { name: "초기화" })).toBeEnabled(
        T,
      );
      expect(
        expectedPointFeatureIds(combinedBody.data.items),
        "place 추가 전후 point Feature ID 집합이 달라야 reset 수렴을 검증할 수 있음",
      ).not.toEqual(expectedPointFeatureIds(defaultBody.data.items));

      // cache hit이면 HTTP 없이, stale/ops-live invalidation이면 refetch 뒤 수렴해야 한다.
      const resetCapture = await captureFeatureCollectionResponsesDuring(
        page,
        async () => {
          await filter.getByRole("button", { name: "초기화" }).click();
          await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
          await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
          await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);
          await expect(
            filter.getByRole("button", { name: "초기화" }),
          ).toBeDisabled(T);
          await waitForMapIdle(page);
        },
      );
      for (const request of resetCapture.requests) {
        expect(apiPathFromUrl(request.url())).toBe(
          ADMIN_FEATURES_IN_BOUNDS_PATH,
        );
        const bbox = inBoundsBboxFromUrl(request.url());
        expect(bbox.zoom).not.toBeNull();
        expect(bbox.zoom as number).toBeGreaterThan(13);
        expect(bbox.kinds.join(",")).toBe("weather,notice");
      }
      let resetBody = defaultBody;
      for (const response of resetCapture.responses) {
        expect(response.status()).toBe(200);
        resetBody = (await response.json()) as AdminFeaturesInBoundsResponse;
        expect(resetBody.data.mode).toBe("items");
      }
      await waitForExactPointMarkers(page, resetBody.data.items);
      await expect
        .poll(async () => readFeatureCount(page), T)
        .toBe(resetBody.data.items.length);

      // 백엔드 라운드트립: UI와 같은 bounds에서 place-only/combined/all 비교.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      expectRequestBoundsToMatchMap(inBoundsBbox(defaultResponse), bounds!);
      expectRequestBoundsToMatchMap(inBoundsBbox(combinedResponse), bounds!);
      for (const request of resetCapture.requests) {
        expectRequestBoundsToMatchMap(
          inBoundsBboxFromUrl(request.url()),
          bounds!,
        );
      }
      const placeOnly = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, SEOUL.zoom, ["place"]),
      );
      expect(placeOnly.status).toBe(200);
      expect(placeOnly.body).not.toBeNull();
      expect(placeOnly.body!.data.mode).toBe("items");
      expect(placeOnly.body!.data.items.length).toBeGreaterThan(0);
      for (const item of placeOnly.body!.data.items) {
        expect(item.kind).toBe("place");
      }
      const combined = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, SEOUL.zoom, ["weather", "notice", "place"]),
      );
      expect(combined.status).toBe(200);
      expect(combined.body).not.toBeNull();
      expect(combined.body!.data.mode).toBe("items");
      expect(
        combined.body!.data.items.map((item) => item.feature_id).sort(),
      ).toEqual(combinedBody.data.items.map((item) => item.feature_id).sort());
      const unfiltered = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, SEOUL.zoom, []),
      );
      expect(unfiltered.status).toBe(200);
      expect(unfiltered.body).not.toBeNull();
      expect(unfiltered.body!.data.items.length).toBeGreaterThanOrEqual(
        placeOnly.body!.data.items.length,
      );
    } finally {
      // 읽기 전용 — 백엔드 변경 없음. UI 필터만 초기화해 깨끗한 상태로 둔다.
      // 초기화 버튼은 항상 렌더되므로(disabled로 제어), enabled일 때만 클릭한다
      // (disabled 버튼 click은 actionability 대기로 멈출 수 있다).
      const reset = filter.getByRole("button", { name: "초기화" });
      if (await reset.isEnabled().catch(() => false)) {
        await reset.click().catch(() => {});
      }
    }
  });

  test("점 마커 클릭 → 상세 패널이 실제 backend feature를 반영", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoFeaturesReady(page);
    const panel = page.getByTestId("feature-detail-panel");

    try {
      // 기본 필터(weather/notice)에 포함되는 feature를 직접 조회해 좌표 있는 실제 feature를 확인.
      const seed = await browserFetch<FeaturesInBboxResponse>(
        page,
        "/v1/features?min_lon=126.96&min_lat=37.55&max_lon=127.02&max_lat=37.59&page_size=100&kind=weather&kind=notice",
      );
      expect(seed.status).toBe(200);
      expect(seed.body).not.toBeNull();
      const target = seed.body!.data.items.find(
        (item) => typeof item.lon === "number" && typeof item.lat === "number",
      );
      expect(
        target,
        "서울 도심 bbox에 좌표 있는 feature가 있어야 함",
      ).toBeTruthy();
      const targetLon = target!.lon as number;
      const targetLat = target!.lat as number;

      // 타깃은 신규 query key이므로 admin response를 반드시 받고 전체 marker ID를 맞춘다.
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      await waitForMapIdle(page);
      const mapResponsePromise = page.waitForResponse(
        (response) => adminItemsContains(response, targetLon, targetLat),
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, targetLon, targetLat, 16);
      const mapResponse = await mapResponsePromise;
      expect(mapResponse.status()).toBe(200);
      const mapBody =
        (await mapResponse.json()) as AdminFeaturesInBoundsResponse;
      expect(mapBody.data.mode).toBe("items");
      expect(
        mapBody.data.items.some((item) => item.feature_id === target!.feature_id),
      ).toBe(true);
      await waitForMapIdle(page);
      await waitForExactPointMarkers(page, mapBody.data.items);

      // 현재 bounds를 같은 admin items 계약으로 직접 읽고 public seed와 동일한 marker를 찾는다.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      expectRequestBoundsToMatchMap(inBoundsBbox(mapResponse), bounds!);
      const direct = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, 16, ["weather", "notice"]),
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      expect(direct.body!.data.mode).toBe("items");
      expect(
        direct.body!.data.items.map((item) => item.feature_id).sort(),
      ).toEqual(mapBody.data.items.map((item) => item.feature_id).sort());
      const adminTarget = direct.body!.data.items.find(
        (item) => item.feature_id === target!.feature_id,
      );
      expect(
        adminTarget,
        "public seed와 같은 admin map item이 있어야 함",
      ).toBeTruthy();
      const coincidentFeatureIds = await expectedCoincidentFeatureIds(
        page,
        direct.body!.data.items,
        adminTarget!.feature_id,
      );
      expect(coincidentFeatureIds).toContain(adminTarget!.feature_id);
      const pointMarker = await pointMarkerForFeatureId(
        page,
        adminTarget!.feature_id,
      );

      // 마커 클릭 → useAdminFeatureDetail이 정확한 admin 단건 상세를 호출.
      // 응답 대기 설정 후 클릭해 빠른 응답도 놓치지 않는다.
      const detailPromise = page.waitForResponse(
        (response) =>
          isAdminFeatureDetail(response, adminTarget!.feature_id),
        { timeout: FLOW_TIMEOUT },
      );
      await pointMarker.click();
      if (coincidentFeatureIds.length > 1) {
        await expect
          .poll(async () => readCoincidentPopupFeatureIds(page), T)
          .toEqual(coincidentFeatureIds);
        const popupRow = await coincidentPopupRowForFeatureId(
          page,
          adminTarget!.feature_id,
        );
        await popupRow.click();
      }
      const detailResponse = await detailPromise;
      expect(detailResponse.status()).toBe(200);
      const detail =
        (await detailResponse.json()) as AdminFeatureDetailResponse;
      const picked = detail.data.feature;
      expect(picked.feature_id).toBe(adminTarget!.feature_id);

      // (1) UI 반영: 상세 패널 노출 + 선택 feature_id/이름/badge가 응답과 일치.
      await expect(panel).toBeVisible(T);
      await expect(panel.getByText("선택 Feature")).toBeVisible(T);
      await expect(panel.getByText(picked.feature_id).first()).toBeVisible(T);
      await expect(
        panel.getByRole("heading", { level: 2, name: picked.name }),
      ).toBeVisible(T);
      // kind 배지는 원문 그대로 렌더(`<Badge>{detail.kind}</Badge>`).
      await expect(
        panel.getByText(picked.kind, { exact: true }).first(),
      ).toBeVisible(T);
      // status 배지는 한글로 렌더(`statusLabel(detail.status)`) — 같은 매핑으로 단언.
      const expectedStatusLabel = statusLabel(picked.status);
      const statusBadge = panel
        .locator('[data-slot="badge"]')
        .filter({ hasText: expectedStatusLabel });
      await expect(statusBadge).toHaveCount(1);
      await expect(statusBadge).toHaveText(expectedStatusLabel);

      // (2) 백엔드 라운드트립: 패널이 가리키는 feature_id를 직접 조회 → 동일 feature.
      const confirm = await browserFetch<AdminFeatureDetailResponse>(
        page,
        `/v1/admin/features/${encodeURIComponent(picked.feature_id)}`,
      );
      expect(confirm.status).toBe(200);
      expect(confirm.body).not.toBeNull();
      expect(confirm.body!.data.feature.feature_id).toBe(picked.feature_id);
      expect(confirm.body!.data.feature.name).toBe(picked.name);
      expect(confirm.body!.data.feature.kind).toBe(picked.kind);

      // (3) 닫기 → 패널 숨김(선택 해제).
      await panel.getByRole("button", { name: "닫기" }).click();
      await expect(panel).toBeHidden(T);
    } finally {
      // 읽기 전용 — 백엔드 변경 없음. 선택만 해제 시도(이미 닫혔으면 무시).
      const closeButton = panel.getByRole("button", { name: "닫기" });
      if (await closeButton.isVisible().catch(() => false)) {
        await closeButton.click().catch(() => {});
      }
    }
  });
});
