import {
  expect,
  test,
  type Locator,
  type Page,
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
 *   C. 점 마커 클릭 → `GET /v1/features/{id}` → 상세 패널이 실제 backend feature를 반영.
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
type AdminFeaturesInBoundsResponse =
  components["schemas"]["AdminFeaturesInBoundsResponse"];
type FeatureDetailEnvelopeResponse =
  components["schemas"]["FeatureDetailEnvelopeResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const ADMIN_FEATURES_IN_BOUNDS_PATH = "/v1/admin/features/in-bounds";
const MAP_CONTAINER = '[data-testid="map-canvas-container"]';
const POINT_MARKER =
  '.maplibregl-marker[role="button"]:not([aria-label^="feature 클러스터"])';
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

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
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

function inBoundsBbox(response: Response): InBoundsBbox {
  const sp = new URL(response.url()).searchParams;
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

// `/v1/features/{id}` 단건 상세만(목록/검색/주변/배치/하위카드는 제외).
const DETAIL_NON_IDS = new Set(["nearby", "search", "in-bounds", "batch"]);
function isFeatureDetail(response: Response): boolean {
  if (response.request().method() !== "GET") return false;
  const match = /^\/v1\/features\/([^/]+)$/.exec(apiPath(response));
  return match !== null && !DETAIL_NON_IDS.has(match[1]);
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

/**
 * action 중 생긴 admin in-bounds 응답을 관찰한다. React Query cache hit이면 null이며,
 * action 자체의 map idle/실제 marker 수렴을 성공 조건으로 사용한다.
 */
async function captureAdminResponseDuring(
  page: Page,
  predicate: (response: Response) => boolean,
  action: () => Promise<void>,
): Promise<Response | null> {
  let observed: Response | null = null;
  const onResponse = (response: Response) => {
    if (observed === null && predicate(response)) observed = response;
  };
  page.on("response", onResponse);
  try {
    await action();
    await page.waitForTimeout(0);
    return observed;
  } finally {
    page.off("response", onResponse);
  }
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 실제 admin 응답 item과 name/kind identity가 일치하는 화면 point marker를 찾는다. */
async function waitForMatchingPointMarker(
  page: Page,
  items: readonly AdminFeatureMapItem[],
): Promise<{ item: AdminFeatureMapItem; marker: Locator }> {
  let matchedIndex = -1;
  const markers = page.locator(POINT_MARKER);
  await expect
    .poll(
      async () => {
        const labels = await markers.evaluateAll((elements) =>
          elements.map((element) => element.getAttribute("aria-label") ?? ""),
        );
        matchedIndex = items.findIndex((item) => {
          const prefix = `${item.name} (${item.kind})`;
          return labels.some(
            (label) => label === prefix || label.startsWith(`${prefix} `),
          );
        });
        return matchedIndex;
      },
      { timeout: 30_000 },
    )
    .toBeGreaterThanOrEqual(0);

  const item = items[matchedIndex];
  const accessibleName = new RegExp(
    `^${escapeRegex(item.name)} \\(${escapeRegex(item.kind)}\\)(?: |$)`,
  );
  return {
    item,
    marker: page
      .getByRole("button", { name: accessibleName })
      .and(markers)
      .first(),
  };
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
    await expect(reset).toBeEnabled(T);

    await reset.click();
    await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
    await expect(reset).toBeDisabled(T);
  });

  for (const [name, lon, lat, zoom] of A_VIEWS) {
    test(`뷰포트를 ${name}로 이동 → admin bbox 요청/cache hit가 카운트/마커에 반영`, async ({
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

      // 새 HTTP 응답이 있으면 관찰하되 React Query cache hit도 정상이다. 성공 조건은
      // target moveend→idle 뒤 실제 point marker가 렌더된 상태다.
      const response = await captureAdminResponseDuring(
        page,
        (response) => adminItemsContains(response, targetLon, targetLat),
        async () => {
          await jumpMap(page, targetLon, targetLat, targetZoom);
          await waitForMapIdle(page);
          await expect(page.locator(POINT_MARKER).first()).toBeVisible({
            timeout: 30_000,
          });
        },
      );

      // 네트워크 miss 경로에서는 UI가 보낸 exact endpoint/파라미터/응답도 검증한다.
      if (response !== null) {
        expect(response.status()).toBe(200);
        const requested = inBoundsBbox(response);
        expect(requested.minLon).toBeLessThanOrEqual(targetLon);
        expect(requested.maxLon).toBeGreaterThanOrEqual(targetLon);
        expect(requested.minLat).toBeLessThanOrEqual(targetLat);
        expect(requested.maxLat).toBeGreaterThanOrEqual(targetLat);
        expect(requested.zoom).not.toBeNull();
        expect(requested.zoom as number).toBeGreaterThan(13);
        expect(requested.maxItems).not.toBeNull();
        expect(requested.maxItems as number).toBeGreaterThan(0);
        expect(requested.maxItems as number).toBeLessThanOrEqual(2000);

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
      }

      // 백엔드 read 라운드트립: UI와 같은 admin items 계약을 현재 bounds로 직접 조회.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      const direct = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, targetZoom, ["weather", "notice"]),
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      expect(direct.body!.data.mode).toBe("items");
      expect(direct.body!.data.items.length).toBeGreaterThan(0);
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
      const matching = await waitForMatchingPointMarker(
        page,
        direct.body!.data.items,
      );
      await expect(matching.marker).toBeVisible(T);
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
      await captureAdminResponseDuring(
        page,
        (response) => adminItemsContains(response, SEOUL.lon, SEOUL.lat),
        async () => {
          await jumpMap(page, SEOUL.lon, SEOUL.lat, SEOUL.zoom);
          await waitForMapIdle(page);
          await expect(page.locator(POINT_MARKER).first()).toBeVisible({
            timeout: 30_000,
          });
        },
      );

      await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
      await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
      await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);

      // 토글 뒤 새 응답이 없더라도(cache hit) map idle + 실제 place marker로 수렴한다.
      const response = await captureAdminResponseDuring(
        page,
        (response) =>
          isAdminFeaturesInBounds(response) &&
          inBoundsBbox(response).zoom !== null &&
          (inBoundsBbox(response).zoom as number) > 13 &&
          inBoundsBbox(response).kinds.includes("place"),
        async () => {
          await placeChip.click();
          await expect(placeChip).toHaveAttribute("aria-pressed", "true", T);
          await waitForMapIdle(page);
          await expect(page.locator(POINT_MARKER).first()).toBeVisible({
            timeout: 30_000,
          });
        },
      );

      // 네트워크 miss 경로에서는 UI의 exact kind request를 검증한다.
      if (response !== null) {
        expect(response.status()).toBe(200);
        expect(inBoundsBbox(response).kinds).toEqual([
          "weather",
          "notice",
          "place",
        ]);
        const body = (await response.json()) as AdminFeaturesInBoundsResponse;
        expect(body.data.mode).toBe("items");
        for (const item of body.data.items) {
          expect(["weather", "notice", "place"]).toContain(item.kind);
        }
      }

      // 백엔드 라운드트립: UI와 같은 admin endpoint에서 place-only/combined/all 비교.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
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
      const unfiltered = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, SEOUL.zoom, []),
      );
      expect(unfiltered.status).toBe(200);
      expect(unfiltered.body).not.toBeNull();
      expect(unfiltered.body!.data.items.length).toBeGreaterThanOrEqual(
        placeOnly.body!.data.items.length,
      );

      // UI 반영: exact combined count와 실제 place marker identity가 응답에 수렴.
      await expect(filter.getByRole("button", { name: "초기화" })).toBeEnabled(
        T,
      );
      await expect
        .poll(async () => readFeatureCount(page), T)
        .toBe(combined.body!.data.items.length);
      const matching = await waitForMatchingPointMarker(
        page,
        placeOnly.body!.data.items,
      );
      await expect(matching.marker).toBeVisible(T);
    } finally {
      // 읽기 전용 — 백엔드 변경 없음. UI 필터만 초기화해 깨끗한 상태로 둔다.
      // 초기화 버튼은 항상 렌더되므로(disabled로 제어), enabled일 때만 클릭한다
      // (disabled 버튼 click은 actionability 대기로 멈출 수 있다).
      const reset = filter.getByRole("button", { name: "초기화" });
      if (await reset.isEnabled().catch(() => false)) {
        await reset.click().catch(() => {});
      }
    }

    // 초기화 후 기본 weather/notice만 활성 + 초기화 버튼 disabled(동일 byte 쿼리는
    // staleTime 캐시로 네트워크 호출이 없을 수 있어 UI 상태로 단언).
    await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
    await expect(weatherChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(noticeChip).toHaveAttribute("aria-pressed", "true", T);
    await expect(filter.getByRole("button", { name: "초기화" })).toBeDisabled(
      T,
    );
    await waitForMapIdle(page);
    const resetBounds = await readMapBounds(page);
    expect(resetBounds).not.toBeNull();
    const resetDirect = await browserFetch<AdminFeaturesInBoundsResponse>(
      page,
      adminInBoundsPath(resetBounds!, SEOUL.zoom, ["weather", "notice"]),
    );
    expect(resetDirect.status).toBe(200);
    expect(resetDirect.body).not.toBeNull();
    expect(resetDirect.body!.data.mode).toBe("items");
    await expect
      .poll(async () => readFeatureCount(page), T)
      .toBe(resetDirect.body!.data.items.length);
    await waitForMatchingPointMarker(page, resetDirect.body!.data.items);
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

      // 타깃 좌표로 고배율 점프. network miss/cache hit 어느 쪽이든 idle 뒤 실제 point marker가
      // 렌더되면 수렴한 것으로 본다.
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      await waitForMapIdle(page);
      const mapResponse = await captureAdminResponseDuring(
        page,
        (response) => adminItemsContains(response, targetLon, targetLat),
        async () => {
          await jumpMap(page, targetLon, targetLat, 16);
          await waitForMapIdle(page);
          await expect(page.locator(POINT_MARKER).first()).toBeVisible({
            timeout: 30_000,
          });
        },
      );

      if (mapResponse !== null) {
        expect(mapResponse.status()).toBe(200);
        const mapBody =
          (await mapResponse.json()) as AdminFeaturesInBoundsResponse;
        expect(mapBody.data.mode).toBe("items");
        expect(
          mapBody.data.items.some(
            (item) => item.feature_id === target!.feature_id,
          ),
        ).toBe(true);
      }

      // 현재 bounds를 같은 admin items 계약으로 직접 읽고 public seed와 동일한 marker를 찾는다.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      const direct = await browserFetch<AdminFeaturesInBoundsResponse>(
        page,
        adminInBoundsPath(bounds!, 16, ["weather", "notice"]),
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      expect(direct.body!.data.mode).toBe("items");
      const adminTarget = direct.body!.data.items.find(
        (item) => item.feature_id === target!.feature_id,
      );
      expect(
        adminTarget,
        "public seed와 같은 admin map item이 있어야 함",
      ).toBeTruthy();
      const pointMarker = await waitForMatchingPointMarker(page, [
        adminTarget!,
      ]);

      // 마커 클릭 → useFeatureDetail이 GET /v1/features/{id} 호출. 응답 대기 설정 후 클릭.
      const detailPromise = page.waitForResponse(isFeatureDetail, {
        timeout: FLOW_TIMEOUT,
      });
      await pointMarker.marker.click();
      const detailResponse = await detailPromise;
      expect(detailResponse.status()).toBe(200);
      const detail =
        (await detailResponse.json()) as FeatureDetailEnvelopeResponse;
      const picked = detail.data;

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
      await expect(
        panel.getByText(statusLabel(picked.status), { exact: true }).first(),
      ).toBeVisible(T);

      // (2) 백엔드 라운드트립: 패널이 가리키는 feature_id를 직접 조회 → 동일 feature.
      const confirm = await browserFetch<FeatureDetailEnvelopeResponse>(
        page,
        `/v1/features/${encodeURIComponent(picked.feature_id)}`,
      );
      expect(confirm.status).toBe(200);
      expect(confirm.body).not.toBeNull();
      expect(confirm.body!.data.feature_id).toBe(picked.feature_id);
      expect(confirm.body!.data.name).toBe(picked.name);
      expect(confirm.body!.data.kind).toBe(picked.kind);

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
