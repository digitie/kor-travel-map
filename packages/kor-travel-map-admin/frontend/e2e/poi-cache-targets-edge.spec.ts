import { expect, type Page, type Route, test } from "@playwright/test";

import type { components } from "../src/api/types";

/**
 * `/admin/poi-cache-targets` (`poi-cache-targets-client.tsx`) — route-mocked
 * **edge/depth** spec. 기존 `admin-ops.spec.ts`의 smoke(렌더 표면 + upsert→row→
 * nearby→delete mutation flow + target_key 검증)와 **중복하지 않고**, 그 smoke가
 * 건드리지 않는 분기만 더한다:
 *   1. cursor 페이지네이션: '다음'이 keyset cursor를 실어 page를 전진시키고
 *      next_cursor=null에서 소진(버튼 enabled/disabled 전이 포함).
 *   2. 빈 목록 placeholder('데이터가 없습니다.') + 'page 1 · 0 rows'.
 *   3. 목록 로드 실패: destructive Alert(role=alert) 'target 처리 실패'.
 *   4. nearby 조회 실패: 별도 destructive Alert '주변 feature 조회 실패'.
 *   5. upsert body가 scope_mode='sigungu_by_radius' 선택을 싣고 on_conflict='move'
 *      (하드코딩)·coord 기본값을 함께 보낸다.
 *
 * HOUSE PATTERN(`admin-ops.spec.ts`): 모든 mock body는 생성 OpenAPI 스키마
 * (`components["schemas"][...]`)에 바인딩한 typed factory로만 만든다 — 백엔드 DTO가
 * 바뀌면 e2e tsconfig type-check가 깨져 mock-실계약 drift를 컴파일 타임에 잡는다.
 *
 * 에러 응답 본문(500)은 components 스키마가 아니다(`docs/architecture/rest-api.md` §1.5: 런타임은
 * RFC7807 problem+json이지만 생성 openapi는 422만 선언). 따라서 literal `{ detail }`을
 * 쓰고, UI가 표면화하는 `client.ts` ApiClientError 메시지의 안정 substring('HTTP 500')과
 * Alert 제목만 단언한다(전체 한국어 메시지를 하드코딩하지 않음).
 */

type PoiCacheTargetRecord = components["schemas"]["PoiCacheTargetRecord"];
type PoiCacheTargetListResponse =
  components["schemas"]["PoiCacheTargetListResponse"];
type PoiCacheTargetResponse = components["schemas"]["PoiCacheTargetResponse"];

const MOCK_NOW = "2026-06-08T00:00:00.000Z";
const TARGET_ID_A = "44444444-4444-4444-8444-44444444aaaa";
const TARGET_ID_B = "44444444-4444-4444-8444-44444444bbbb";
const TARGET_ID_SIGUNGU = "44444444-4444-4444-8444-44444444cccc";
const LIST_PATH = "/v1/admin/poi-cache-targets";
const UPSERT_PATH = "/v1/admin/poi-cache-targets/tripmate/mock-target-1";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function makePoiTarget(
  overrides: Partial<PoiCacheTargetRecord> = {},
): PoiCacheTargetRecord {
  return {
    coord: { lon: 126.978, lat: 37.5665 },
    coord_key: "126.978000:37.566500",
    coord_precision_digits: 6,
    created_at: MOCK_NOW,
    deleted_at: null,
    external_system: "tripmate",
    last_failed_at: null,
    last_refreshed_at: null,
    last_requested_at: null,
    last_seen_at: MOCK_NOW,
    metadata: {},
    name: "Mock target",
    nearby_url:
      "/features/nearby/by-target?external_system=tripmate&target_key=mock-target-1",
    next_eligible_refresh_at: null,
    provider_overrides: {},
    radius_km: 5,
    refresh_policy: "provider_default",
    scope_mode: "center_radius",
    status_url: UPSERT_PATH,
    target_id: "44444444-4444-4444-8444-444444444444",
    target_key: "mock-target-1",
    update_enabled: true,
    updated_at: MOCK_NOW,
    ...overrides,
  };
}

function makeListResponse(
  items: PoiCacheTargetRecord[],
  nextCursor: string | null = null,
): PoiCacheTargetListResponse {
  return {
    data: { items },
    meta: {
      duration_ms: 1,
      page: { page_size: 100, next_cursor: nextCursor, total: null },
      request_id: "e2e-poi-target-list",
    },
  };
}

function makeUpsertResponse(
  record: PoiCacheTargetRecord,
): PoiCacheTargetResponse {
  // PoiCacheTargetResponse.meta는 PoiCacheTargetMeta { duration_ms, request_id } —
  // pageable Meta가 아니다.
  return {
    data: record,
    meta: { duration_ms: 1, request_id: "e2e-poi-target-upsert" },
  };
}

// admin/poi-cache-targets glob은 Next.js document/_rsc 요청과 API를 모두 잡는다 →
// admin-ops smoke와 동일하게 document/`/admin/...` pathname/`_rsc`는 route.continue()로
// 통과시키고 `/v1/admin/poi-cache-targets`만 처리한다. GET vs PUT은 method()로 분기.
async function routeListAndUpsert(
  page: Page,
  handlers: {
    onGet: (route: Route, url: URL) => Promise<void>;
    onPut?: (route: Route, url: URL) => Promise<void>;
  },
) {
  await page.route("**/admin/poi-cache-targets**", async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    if (
      url.pathname.startsWith("/_next/") ||
      url.pathname === "/favicon.ico" ||
      url.pathname === "/admin/poi-cache-targets" ||
      url.searchParams.has("_rsc")
    ) {
      await route.continue();
      return;
    }
    if (request.method() === "GET" && url.pathname === LIST_PATH) {
      await handlers.onGet(route, url);
      return;
    }
    if (request.method() === "PUT" && url.pathname === UPSERT_PATH) {
      if (handlers.onPut) {
        await handlers.onPut(route, url);
        return;
      }
    }
    throw new Error(
      `Unhandled POI cache target route: ${request.method()} ${url.pathname}`,
    );
  });
}

test.describe("/admin/poi-cache-targets (edge/depth)", () => {
  test("cursor pagination: 다음 전진 + cursor 전달, next_cursor=null 소진", async ({
    page,
  }) => {
    const seenCursors: (string | null)[] = [];

    await routeListAndUpsert(page, {
      onGet: async (route, url) => {
        const cursor = url.searchParams.get("cursor");
        seenCursors.push(cursor);
        if (cursor === "cursor-page-2") {
          // 2페이지: next_cursor=null → 소진.
          await fulfillJson(
            route,
            makeListResponse(
              [
                makePoiTarget({
                  target_id: TARGET_ID_B,
                  target_key: "page-2",
                  name: "Page2 target",
                }),
              ],
              null,
            ),
          );
          return;
        }
        // 1페이지(cursor 없음, page_size=100): next_cursor 제공.
        expect(url.searchParams.get("page_size")).toBe("100");
        await fulfillJson(
          route,
          makeListResponse(
            [
              makePoiTarget({
                target_id: TARGET_ID_A,
                target_key: "page-1",
                name: "Page1 target",
              }),
            ],
            "cursor-page-2",
          ),
        );
      },
    });

    await page.goto("/admin/poi-cache-targets");

    await expect(
      page.getByRole("heading", { level: 1, name: "POI cache targets" }),
    ).toBeVisible();

    // 로드: 1페이지 행 + 'page 1 ·' 지시자.
    await expect(page.getByRole("row", { name: /Page1 target/ })).toBeVisible();
    await expect(page.getByText("page 1 ·")).toBeVisible();

    const next = page.getByRole("button", { name: "다음" });
    const prev = page.getByRole("button", { name: "이전" });
    // next_cursor 존재 → '다음' enabled, cursorStack 비어있음 → '이전' disabled.
    await expect(next).toBeEnabled();
    await expect(prev).toBeDisabled();

    await next.click();

    // 2페이지로 전진.
    await expect(page.getByRole("row", { name: /Page2 target/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /Page1 target/ })).toHaveCount(0);
    await expect(page.getByText("page 2 ·")).toBeVisible();

    // 두 번째 GET이 keyset cursor='cursor-page-2'를 실었는지(docs/architecture/rest-api.md §1.6
    // page_size+cursor) — 캡처한 cursor 배열을 poll.
    await expect
      .poll(() => seenCursors.includes("cursor-page-2"))
      .toBe(true);

    // 소진: next_cursor=null → '다음' disabled, cursorStack 비어있지 않음 → '이전' enabled.
    await expect(next).toBeDisabled();
    await expect(prev).toBeEnabled();

    // '이전' → 1페이지로 복귀. no-cursor key는 react-query staleTime(30_000) 캐시에서
    // 서빙될 수 있으므로 refetch/GET 카운트가 아니라 UI 상태(행 + 지시자)만 단언.
    await prev.click();
    await expect(page.getByRole("row", { name: /Page1 target/ })).toBeVisible();
    await expect(page.getByText("page 1 ·")).toBeVisible();
  });

  test("empty state: 항목 0건이면 '데이터가 없습니다.' placeholder", async ({
    page,
  }) => {
    await routeListAndUpsert(page, {
      onGet: async (route) => {
        await fulfillJson(route, makeListResponse([], null));
      },
    });

    await page.goto("/admin/poi-cache-targets");

    await expect(
      page.getByRole("heading", { level: 1, name: "POI cache targets" }),
    ).toBeVisible();

    // Targets와 Nearby 두 DataTable이 동일 emptyMessage를 쓴다(line 399 & 428) →
    // getByText('데이터가 없습니다.')는 2개 노드와 매치(Nearby는 target 미선택이라 비어있음).
    await expect(page.getByText("데이터가 없습니다.")).toHaveCount(2);

    // Targets 카드 지시자: 'page 1 · 0 rows'.
    await expect(page.getByText("page 1 · 0 rows")).toBeVisible();

    // next_cursor=null → '다음' disabled, cursorStack 비어있음 → '이전' disabled.
    await expect(page.getByRole("button", { name: "다음" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "이전" })).toBeDisabled();

    // Nearby 카드: target 미선택 placeholder.
    await expect(page.getByText("target을 선택하세요")).toBeVisible();
  });

  test("list error: GET 실패 시 destructive Alert 'target 처리 실패'", async ({
    page,
  }) => {
    await routeListAndUpsert(page, {
      onGet: async (route) => {
        // 에러 본문은 components 스키마가 아님(RFC7807). literal { detail }.
        await fulfillJson(route, { detail: "boom" }, 500);
      },
    });

    await page.goto("/admin/poi-cache-targets");

    await expect(
      page.getByRole("heading", { level: 1, name: "POI cache targets" }),
    ).toBeVisible();

    // variant='destructive' → role='alert' (alert.tsx). 제목 'target 처리 실패'로 scope.
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "target 처리 실패" });
    await expect(alert).toBeVisible();

    // AlertDescription은 ApiClientError 메시지(안정 substring 'HTTP 500' 포함).
    await expect(alert.getByText(/HTTP 500/)).toBeVisible();
  });

  test("nearby error: by-target GET 실패 시 별도 Alert '주변 feature 조회 실패'", async ({
    page,
  }) => {
    await routeListAndUpsert(page, {
      onGet: async (route) => {
        await fulfillJson(
          route,
          makeListResponse(
            [
              makePoiTarget({
                name: "Mock target",
                target_key: "mock-target-1",
                external_system: "tripmate",
              }),
            ],
            null,
          ),
        );
      },
    });

    let nearbyExternal: string | null = null;
    let nearbyTargetKey: string | null = null;
    await page.route("**/v1/features/nearby/by-target**", async (route) => {
      const url = new URL(route.request().url());
      nearbyExternal = url.searchParams.get("external_system");
      nearbyTargetKey = url.searchParams.get("target_key");
      await fulfillJson(route, { detail: "nope" }, 500);
    });

    await page.goto("/admin/poi-cache-targets");

    // 행 클릭으로 selectedTarget 설정 → nearby query enabled(external_system/target_key 비어있지 않음).
    const targetRow = page.getByRole("row", { name: /Mock target/ });
    await expect(targetRow).toBeVisible();
    await targetRow.click();

    // nearby.isError → Nearby features 카드 안에 destructive Alert(role=alert) 렌더.
    // 목록 GET은 성공했으므로 이 페이지에는 nearby Alert 하나만 존재.
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "주변 feature 조회 실패" });
    await expect(alert).toBeVisible();
    await expect(page.getByText("Nearby features")).toBeVisible();

    // by-target 요청이 external_system=tripmate & target_key=mock-target-1을 실었는지.
    await expect.poll(() => nearbyExternal).toBe("tripmate");
    await expect.poll(() => nearbyTargetKey).toBe("mock-target-1");
  });

  test("upsert body가 scope_mode=sigungu_by_radius + on_conflict=move를 싣는다", async ({
    page,
  }) => {
    let upsertCount = 0;
    let upserted = false;

    await routeListAndUpsert(page, {
      onGet: async (route) => {
        // upsert 성공 후(invalidate) 새 target이 목록에 보이도록.
        await fulfillJson(
          route,
          makeListResponse(
            upserted
              ? [
                  makePoiTarget({
                    target_id: TARGET_ID_SIGUNGU,
                    target_key: "mock-target-1",
                    name: "Sigungu target",
                    scope_mode: "sigungu_by_radius",
                  }),
                ]
              : [],
            null,
          ),
        );
      },
      onPut: async (route, url) => {
        upsertCount += 1;
        // external_system 기본 'tripmate', target_key path-encoded.
        expect(url.pathname).toBe(UPSERT_PATH);
        // scope_mode select가 sigungu_by_radius로 전달 + on_conflict는 하드코딩 'move'.
        expect(route.request().postDataJSON()).toMatchObject({
          coord: { lon: 126.978, lat: 37.5665 },
          name: "Sigungu target",
          radius_km: 5,
          scope_mode: "sigungu_by_radius",
          on_conflict: "move",
        });
        upserted = true;
        await fulfillJson(
          route,
          makeUpsertResponse(
            makePoiTarget({
              target_id: TARGET_ID_SIGUNGU,
              name: "Sigungu target",
              scope_mode: "sigungu_by_radius",
            }),
          ),
        );
      },
    });

    await page.goto("/admin/poi-cache-targets");

    await page.getByLabel("target key").fill("mock-target-1");
    await page.getByLabel("target name").fill("Sigungu target");
    // lon/lat/radius km는 기본값(126.9780 / 37.5665 / 5) 유지.
    // FormSelect(NativeSelect)에서 'sigungu_by_radius' 옵션 선택.
    await page.getByLabel("scope mode").selectOption("sigungu_by_radius");

    await page.getByRole("button", { name: "저장" }).click();

    await expect.poll(() => upsertCount).toBe(1);

    // onSuccess가 cursorStack=[] 리셋 → 무효화된 GET이 새 target 반환.
    await expect(
      page.getByRole("row", { name: /Sigungu target/ }),
    ).toBeVisible();
  });
});
