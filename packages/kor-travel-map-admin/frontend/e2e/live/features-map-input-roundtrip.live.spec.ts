import { expect, test, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";
import { MAP_VIEWS } from "./_fixtures";

/**
 * LIVE (non-mock) e2e for `/features` (Feature 지도) — *입력 라운드트립* 깊이.
 *
 * features-map.live.spec.ts(스모크: 로드/탭/칩 노출/딥링크/마커 존재/클러스터 줌)와
 * features-map-interactions.spec.ts(route-mock 깊이)가 다루지 않는 **실 API 계약
 * 라운드트립**만 더한다 — 전부 READ-ONLY(GET only, 백엔드 변경 없음)이므로 게이팅하지
 * 않는다(읽기 전용 input 라운드트립은 비게이트 규약):
 *   A. 지도 뷰포트 이동(MAP_VIEWS) → `GET /v1/features`가 새 bbox 파라미터로 호출 →
 *      응답 본문이 요청 bbox 안 feature만 → DOM viewport 텍스트/카운트/마커가 반영.
 *   B. kind 칩 토글 → 요청에 `kind=` 파라미터 → 서버가 해당 kind만 반환 → 카운트/마커 반영.
 *   C. 점 마커 클릭 → `GET /v1/features/{id}` → 상세 패널이 실제 backend feature를 반영.
 *
 * 셀렉터/파라미터는 소스에서 검증한 것만 사용한다:
 *   - bbox 파라미터 이름: src/api/features.ts fetchFeaturesInBbox (min_lon/min_lat/
 *     max_lon/max_lat/page_size/kind/include_geometry). zoom은 전송하지 않는다.
 *   - 지도 인스턴스 e2e 훅: components/vworld-map-view.tsx (`container._maplibreMap`).
 *   - 클러스터/점 마커 aria-label·role=button, 상세 패널 testId/닫기: 동 컴포넌트 +
 *     app/features/features-client.tsx FeatureDetailPanel.
 */

type FeaturesInBboxResponse = components["schemas"]["FeaturesInBboxResponse"];
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

const FEATURES_LIST_PATH = "/v1/features";
const MAP_CONTAINER = '[data-testid="map-canvas-container"]';
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

interface ListBbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
  pageSize: number | null;
  kinds: string[];
}

function isFeaturesList(response: Response): boolean {
  return (
    response.request().method() === "GET" &&
    apiPath(response) === FEATURES_LIST_PATH
  );
}

function listBbox(response: Response): ListBbox {
  const sp = new URL(response.url()).searchParams;
  const pageSizeRaw = sp.get("page_size");
  return {
    minLon: Number(sp.get("min_lon")),
    minLat: Number(sp.get("min_lat")),
    maxLon: Number(sp.get("max_lon")),
    maxLat: Number(sp.get("max_lat")),
    pageSize: pageSizeRaw === null ? null : Number(pageSizeRaw),
    kinds: sp.getAll("kind"),
  };
}

/** 응답이 `(lon,lat)`를 bbox로 감싸는 `/v1/features` tile 호출인가. */
function tileContains(response: Response, lon: number, lat: number): boolean {
  if (!isFeaturesList(response)) return false;
  const b = listBbox(response);
  if (
    [b.minLon, b.minLat, b.maxLon, b.maxLat].some((value) => Number.isNaN(value))
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

// MAP_VIEWS에서 dense city + 광역(전국)을 골라 카운트/마커 단언이 의미를 갖게 한다.
const A_VIEWS = MAP_VIEWS.filter(([name]) =>
  ["서울", "부산", "전국"].includes(name as string),
);

test.describe("/features live — map input round-trip (read-only)", () => {
  // 라이브 지도 + 타일 fetch는 타이밍 의존 → flaky 제한용 retries=1.
  test.describe.configure({ retries: 1 });

  for (const [name, lon, lat, zoom] of A_VIEWS) {
    test(`뷰포트를 ${name}로 이동 → bbox API가 새 좌표 파라미터로 호출되고 카운트/마커가 반영`, async ({
      page,
    }) => {
      test.setTimeout(FLOW_TIMEOUT);
      const targetLon = lon as number;
      const targetLat = lat as number;
      const targetZoom = zoom as number;

      await gotoFeaturesReady(page);

      // 멀리 떨어진 기준점으로 먼저 점프(초기 뷰가 타깃과 같아 moveend 누락되는 경우 방지).
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);

      // 타깃 좌표를 bbox로 감싸는 tile의 GET /v1/features를 기다린다(입력 → API 파라미터).
      const responsePromise = page.waitForResponse(
        (response) => tileContains(response, targetLon, targetLat),
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, targetLon, targetLat, targetZoom);
      const response = await responsePromise;

      // (1) API 파라미터: 요청 URL에 bbox 4개 + page_size(1..500)가 실리고 타깃을 bracket.
      expect(response.status()).toBe(200);
      const requested = listBbox(response);
      expect(requested.minLon).toBeLessThanOrEqual(targetLon);
      expect(requested.maxLon).toBeGreaterThanOrEqual(targetLon);
      expect(requested.minLat).toBeLessThanOrEqual(targetLat);
      expect(requested.maxLat).toBeGreaterThanOrEqual(targetLat);
      expect(requested.pageSize).not.toBeNull();
      expect(requested.pageSize as number).toBeGreaterThan(0);
      expect(requested.pageSize as number).toBeLessThanOrEqual(500);

      // (2) API 응답 본문 = 요청 bbox 안 feature만(서버 공간 필터 계약, ADR-012).
      const body = (await response.json()) as FeaturesInBboxResponse;
      expect(Array.isArray(body.data.items)).toBe(true);
      for (const item of body.data.items) {
        if (typeof item.lon === "number" && typeof item.lat === "number") {
          expect(item.lon).toBeGreaterThanOrEqual(requested.minLon - EPS);
          expect(item.lon).toBeLessThanOrEqual(requested.maxLon + EPS);
          expect(item.lat).toBeGreaterThanOrEqual(requested.minLat - EPS);
          expect(item.lat).toBeLessThanOrEqual(requested.maxLat + EPS);
        }
      }

      // (3) 백엔드 read 라운드트립: 현재 지도 bounds로 직접 조회 → 같은 지역에 feature 존재.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      const direct = await browserFetch<FeaturesInBboxResponse>(
        page,
        `/v1/features?min_lon=${bounds!.w}&min_lat=${bounds!.s}&max_lon=${bounds!.e}&max_lat=${bounds!.n}&page_size=500`,
      );
      expect(direct.status).toBe(200);
      expect(direct.body).not.toBeNull();
      expect(direct.body!.data.items.length).toBeGreaterThan(0);
      for (const item of direct.body!.data.items) {
        if (typeof item.lon === "number" && typeof item.lat === "number") {
          expect(item.lon).toBeGreaterThanOrEqual(bounds!.w - EPS);
          expect(item.lon).toBeLessThanOrEqual(bounds!.e + EPS);
          expect(item.lat).toBeGreaterThanOrEqual(bounds!.s - EPS);
          expect(item.lat).toBeLessThanOrEqual(bounds!.n + EPS);
        }
      }

      // (4) UI 반영: DOM viewport 텍스트가 타깃 center/zoom으로 갱신(moveend → Zustand).
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

      // (5) UI 반영: 헤더 카운트 배지 "{N}건 표시"가 반환 feature 집합 크기를 표시.
      await expect(page.getByText(/\d+건 표시/).first()).toBeVisible(T);
      await expect.poll(async () => readFeatureCount(page), T).toBeGreaterThan(0);

      // (6) UI 반영: 지도에 마커(점/클러스터)가 렌더.
      await expect(page.locator(".maplibregl-marker").first()).toBeVisible({
        timeout: 30_000,
      });
      expect(await page.locator(".maplibregl-marker").count()).toBeGreaterThan(0);
    });
  }

  test("kind 필터 토글 → API kind 파라미터 + 서버 필터 결과가 카운트/마커에 반영", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    const SEOUL = { lon: 126.978, lat: 37.566, zoom: 12 } as const;

    await gotoFeaturesReady(page);
    const filter = page.getByTestId("kind-filter");
    const placeChip = filter.getByRole("button", { name: "place", exact: true });

    try {
      // place feature가 풍부한 서울로 이동(초기 데이터 확보).
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      const seoulLoad = page.waitForResponse(
        (response) => tileContains(response, SEOUL.lon, SEOUL.lat),
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, SEOUL.lon, SEOUL.lat, SEOUL.zoom);
      await seoulLoad;

      await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);

      // kind=place가 실린 GET /v1/features를 기다린다(토글 → queryKey 변경 → refetch).
      const kindResponsePromise = page.waitForResponse(
        (response) =>
          isFeaturesList(response) && listBbox(response).kinds.includes("place"),
        { timeout: FLOW_TIMEOUT },
      );
      await placeChip.click();
      await expect(placeChip).toHaveAttribute("aria-pressed", "true", T);
      const response = await kindResponsePromise;

      // (1) API 파라미터: 요청에 kind=place. 본문: 반환 feature는 모두 kind=place(서버 필터).
      expect(response.status()).toBe(200);
      expect(listBbox(response).kinds).toContain("place");
      const body = (await response.json()) as FeaturesInBboxResponse;
      for (const item of body.data.items) {
        expect(item.kind).toBe("place");
      }

      // (2) 백엔드 라운드트립: 같은 bounds에 kind=place 직접 조회 → place만, 1건 이상.
      const bounds = await readMapBounds(page);
      expect(bounds).not.toBeNull();
      const bbox = `min_lon=${bounds!.w}&min_lat=${bounds!.s}&max_lon=${bounds!.e}&max_lat=${bounds!.n}&page_size=500`;
      const placeOnly = await browserFetch<FeaturesInBboxResponse>(
        page,
        `/v1/features?${bbox}&kind=place`,
      );
      expect(placeOnly.status).toBe(200);
      expect(placeOnly.body).not.toBeNull();
      expect(placeOnly.body!.data.items.length).toBeGreaterThan(0);
      for (const item of placeOnly.body!.data.items) {
        expect(item.kind).toBe("place");
      }
      // 필터 없는 조회는 place-필터 결과의 상위집합(>=) — kind 파라미터가 결과를 좁힘.
      const unfiltered = await browserFetch<FeaturesInBboxResponse>(
        page,
        `/v1/features?${bbox}`,
      );
      expect(unfiltered.status).toBe(200);
      expect(unfiltered.body).not.toBeNull();
      expect(unfiltered.body!.data.items.length).toBeGreaterThanOrEqual(
        placeOnly.body!.data.items.length,
      );

      // (3) UI 반영: 초기화 버튼 활성화(kind 선택 시) + 카운트 배지(>0) + 마커 존재.
      // 초기화 버튼은 항상 렌더되고 `disabled={kind 0건}`이라, kind 선택 시 enabled가
      // 의미 있는 단언이다(과거의 노출/숨김 토글은 #600에서 disabled 토글로 바뀜).
      await expect(filter.getByRole("button", { name: "초기화" })).toBeEnabled(T);
      await expect.poll(async () => readFeatureCount(page), T).toBeGreaterThan(0);
      await expect(page.locator(".maplibregl-marker").first()).toBeVisible({
        timeout: 30_000,
      });
    } finally {
      // 읽기 전용 — 백엔드 변경 없음. UI 필터만 초기화해 깨끗한 상태로 둔다.
      // 초기화 버튼은 항상 렌더되므로(disabled로 제어), enabled일 때만 클릭한다
      // (disabled 버튼 click은 actionability 대기로 멈출 수 있다).
      const reset = filter.getByRole("button", { name: "초기화" });
      if (await reset.isEnabled().catch(() => false)) {
        await reset.click().catch(() => {});
      }
    }

    // 초기화 후 chip 비활성 + 초기화 버튼 disabled(동일 byte 쿼리는 staleTime 캐시로
    // 네트워크 호출이 없을 수 있어 refetch가 아니라 UI 상태로 단언 — interactions.spec과
    // 동일 idiom). 버튼은 항상 렌더되고 kind 0건이면 `disabled`다(#600).
    await expect(placeChip).toHaveAttribute("aria-pressed", "false", T);
    await expect(filter.getByRole("button", { name: "초기화" })).toBeDisabled(T);
  });

  test("점 마커 클릭 → 상세 패널이 실제 backend feature를 반영", async ({
    page,
  }) => {
    test.setTimeout(FLOW_TIMEOUT);
    await gotoFeaturesReady(page);
    const panel = page.getByTestId("feature-detail-panel");

    try {
      // 서울 도심 작은 bbox를 직접 조회해 좌표가 있는 실제 feature를 확인(데이터 존재 시드).
      const seed = await browserFetch<FeaturesInBboxResponse>(
        page,
        "/v1/features?min_lon=126.96&min_lat=37.55&max_lon=127.02&max_lat=37.59&page_size=100",
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

      // 타깃 좌표로 고배율(zoom 16 > clusterMaxZoom 14) 점프 → 클러스터 없이 점 마커만 렌더.
      await jumpMap(page, ANCHOR.lon, ANCHOR.lat, ANCHOR.zoom);
      const tileLoad = page.waitForResponse(
        (response) => tileContains(response, targetLon, targetLat),
        { timeout: FLOW_TIMEOUT },
      );
      await jumpMap(page, targetLon, targetLat, 16);
      await tileLoad;

      // 점 마커(role=button, 클러스터 aria-label 제외) 렌더 대기.
      const pointMarker = page.locator(
        '.maplibregl-marker[role="button"]:not([aria-label^="feature 클러스터"])',
      );
      await expect(pointMarker.first()).toBeVisible({ timeout: 30_000 });

      // 마커 클릭 → useFeatureDetail이 GET /v1/features/{id} 호출. 응답 대기 설정 후 클릭.
      const detailPromise = page.waitForResponse(isFeatureDetail, {
        timeout: FLOW_TIMEOUT,
      });
      await pointMarker.first().click();
      const detailResponse = await detailPromise;
      expect(detailResponse.status()).toBe(200);
      const detail = (await detailResponse.json()) as FeatureDetailEnvelopeResponse;
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
