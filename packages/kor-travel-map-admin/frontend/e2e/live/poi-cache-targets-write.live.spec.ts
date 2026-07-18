import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import type { components } from "../../src/api/types";

type PoiCacheTargetUpsertRequest =
  components["schemas"]["PoiCacheTargetUpsertRequest"];
type PoiCacheTargetResponse = components["schemas"]["PoiCacheTargetResponse"];
type PoiCacheTargetMutationResponse =
  components["schemas"]["PoiCacheTargetMutationResponse"];
type PoiCacheTargetListResponse =
  components["schemas"]["PoiCacheTargetListResponse"];

type BrowserFetchResult<T> = {
  body: T | null;
  etag: string | null;
  status: number;
  text: string;
};

const UI_TIMEOUT = 15_000;
const FLOW_TIMEOUT = 5 * 60 * 1000;
const T = { timeout: UI_TIMEOUT } as const;

const RUN_ID = `live-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

// external_system + target_key는 RUN_ID로 묶어 병렬/재실행 충돌을 막는다.
const EXTERNAL_SYSTEM = `e2e-poi-${RUN_ID}`;
const TARGET_KEY = `target-${RUN_ID}`;
// 두 이름은 서로 substring이 아니어야 한다(row 매칭 regex가 substring이라
// 갱신 이름이 원본 이름을 포함하면 이전 ROW의 toHaveCount(0) 단언이 깨진다).
const CREATE_NAME = `E2E POI Target ${RUN_ID} created`;
const UPDATED_NAME = `E2E POI Target ${RUN_ID} renamed`;
const POI_ID_A = `${RUN_ID}-poi-a`;
const POI_ID_B = `${RUN_ID}-poi-b`;
// 서울시청(WGS84 lon/lat) — 한국 경계 안. update 시에도 좌표는 고정해 coord conflict를 피한다.
const LON = 126.978;
const LAT = 37.5665;

const EXECUTE_POI_CACHE_WRITE =
  process.env.E2E_ADMIN_WRITE === "1" || process.env.E2E_POI_CACHE_WRITE === "1";
const LIVE_API_BASE =
  process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_API ?? "http://127.0.0.1:12701";

const POI_HEADING = "POI cache targets";

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function apiPath(response: Response): string {
  const pathname = new URL(response.url()).pathname;
  const path = pathname.startsWith("/api/proxy/")
    ? pathname.slice("/api/proxy".length)
    : pathname;
  return decodeURIComponent(path);
}

function isApiResponse(
  response: Response,
  method: string,
  path: string,
): boolean {
  return response.request().method() === method && apiPath(response) === path;
}

async function waitForApiResponse(
  page: Page,
  method: string,
  path: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) => isApiResponse(response, method, decodeURIComponent(path)),
    { timeout: FLOW_TIMEOUT },
  );
}

async function browserFetch<T>(
  page: Page,
  path: string,
  options: {
    body?: unknown;
    headers?: Record<string, string>;
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  } = {},
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(
    async ({ body, headers, method, path }) => {
      const response = await fetch(`/api/proxy${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...headers,
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
        etag: response.headers.get("etag"),
        status: response.status,
        text,
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

const LIST_PATH = "/v1/admin/poi-cache-targets";

function poiTargetPath(externalSystem: string, targetKey: string): string {
  return `${LIST_PATH}/${encodeURIComponent(externalSystem)}/${encodeURIComponent(
    targetKey,
  )}`;
}

function poiTargetListBySystemPath(externalSystem: string): string {
  return `${LIST_PATH}?external_system=${encodeURIComponent(externalSystem)}&include_deleted=false`;
}

function upsertBody(
  name: string,
  externalPoiId: string,
): PoiCacheTargetUpsertRequest {
  return {
    coord: { lon: LON, lat: LAT },
    coord_precision_digits: 6,
    radius_km: 5,
    name,
    scope_mode: "center_radius",
    update_enabled: true,
    refresh_policy: "provider_default",
    on_conflict: "move",
    metadata: { external_poi_id: externalPoiId, note: `e2e ${RUN_ID}` },
  };
}

async function fetchTarget(
  page: Page,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  return browserFetch<PoiCacheTargetResponse>(
    page,
    poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
  );
}

async function gotoPoiTargets(page: Page): Promise<void> {
  await page.goto("/admin/poi-cache-targets");
  await expect(
    page.getByRole("heading", { level: 1, name: POI_HEADING }),
  ).toBeVisible(T);
  await expect(page.getByRole("table").first()).toBeVisible(T);
}

async function refreshList(page: Page): Promise<void> {
  const refreshButton = page.getByRole("button", { name: "새로고침" });
  await expect(refreshButton).toBeEnabled(T);
  const listResponse = waitForApiResponse(page, "GET", LIST_PATH);
  await refreshButton.click();
  await listResponse;
}

function rowContaining(page: Page, text: string): Locator {
  return page.getByRole("row", { name: new RegExp(escapeRegExp(text)) });
}

async function deleteTargetByApi(
  page: Page,
  entityTag: string,
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  return browserFetch<PoiCacheTargetMutationResponse>(
    page,
    poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
    { method: "DELETE", headers: { "If-Match": entityTag } },
  );
}

function causalRevision(
  response: BrowserFetchResult<PoiCacheTargetMutationResponse>,
): number {
  const revision = response.body?.meta.dataset_projection_revision;
  if (typeof revision !== "number") {
    throw new Error("mutation response is missing dataset_projection_revision");
  }
  return revision;
}

async function openDatasetProjectionSocket(page: Page): Promise<void> {
  await page.evaluate(async ({ liveApiBase }) => {
    const ticketResponse = await fetch("/api/auth/live-ticket", {
      method: "POST",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!ticketResponse.ok) {
      throw new Error(`live ticket failed: ${ticketResponse.status}`);
    }
    const ticket = (await ticketResponse.json()) as { subprotocol: string };
    const url = new URL(liveApiBase);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = `${url.pathname.replace(/\/+$/, "")}/v1/ops/live`;
    url.search = "?poll_interval_ms=1000";
    const state = globalThis as typeof globalThis & {
      __c7cLive?: { frames: unknown[]; socket: WebSocket };
    };
    const frames: unknown[] = [];
    const socket = new WebSocket(url, ticket.subprotocol);
    state.__c7cLive = { frames, socket };
    socket.addEventListener("message", (event) => {
      try {
        frames.push(JSON.parse(String(event.data)));
      } catch {
        frames.push({ type: "malformed" });
      }
    });
    await new Promise<void>((resolve, reject) => {
      socket.addEventListener("open", () => resolve(), { once: true });
      socket.addEventListener(
        "error",
        () => reject(new Error("dataset_projection socket open failed")),
        { once: true },
      );
    });
    socket.send(
      JSON.stringify({ type: "replace", topics: ["dataset_projection"] }),
    );
  }, { liveApiBase: LIVE_API_BASE });
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const state = globalThis as typeof globalThis & {
            __c7cLive?: { frames: unknown[] };
          };
          return state.__c7cLive?.frames.some((frame) => {
            const value = frame as { topic?: unknown; type?: unknown };
            return value.type === "snapshot" && value.topic === "dataset_projection";
          }) ?? false;
        }),
      T,
    )
    .toBe(true);
}

async function expectCausalDatasetProjectionUpdate(
  page: Page,
  receipt: number,
  frameCursor: number,
): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(({ frameCursor, receipt }) => {
          const state = globalThis as typeof globalThis & {
            __c7cLive?: { frames: unknown[]; socket: WebSocket };
          };
          if (state.__c7cLive?.socket.readyState !== WebSocket.OPEN) return false;
          return state.__c7cLive.frames.slice(frameCursor).some((frame) => {
            const value = frame as {
              data?: { live_revision?: unknown };
              topic?: unknown;
              type?: unknown;
            };
            return (
              value.type === "update" &&
              value.topic === "dataset_projection" &&
              typeof value.data?.live_revision === "number" &&
              value.data.live_revision >= receipt
            );
          });
        }, { frameCursor, receipt }),
      { timeout: FLOW_TIMEOUT },
    )
    .toBe(true);
}

async function datasetProjectionFrameCursor(page: Page): Promise<number> {
  return page.evaluate(() => {
    const state = globalThis as typeof globalThis & {
      __c7cLive?: { frames: unknown[]; socket: WebSocket };
    };
    if (state.__c7cLive?.socket.readyState !== WebSocket.OPEN) {
      throw new Error("dataset_projection socket is not open");
    }
    return state.__c7cLive.frames.length;
  });
}

async function closeDatasetProjectionSocket(page: Page): Promise<void> {
  await page.evaluate(() => {
    const state = globalThis as typeof globalThis & {
      __c7cLive?: { socket: WebSocket };
    };
    state.__c7cLive?.socket.close(1000, "c7c complete");
    delete state.__c7cLive;
  });
}

// ---- DEEPEN(#574 후속): 추가 시나리오용 파라미터화 helper ----
// browserFetch / waitForApiResponse / poiTargetPath / LIST_PATH 등 기존 helper를 재사용한다.

// FastAPI 422(Pydantic 검증 실패) 응답은 {detail:[...]} 형태 — 성공 스키마와 다르다.
type ValidationErrorBody = { detail?: unknown };

interface ScenarioKeys {
  externalSystem: string;
  targetKey: string;
  name: string;
}

// 시나리오별 고유 external_system/target_key — RUN_ID + suffix로 교차 간섭/중복을 막는다.
function scenarioKeys(suffix: string): ScenarioKeys {
  return {
    externalSystem: `e2e-poi-${RUN_ID}-${suffix}`,
    targetKey: `target-${RUN_ID}-${suffix}`,
    name: `E2E POI ${RUN_ID} ${suffix}`,
  };
}

// upsert body builder — 기본값 위에 override를 얹는다(기존 upsertBody는 그대로 둔다).
function buildUpsert(
  overrides: Partial<PoiCacheTargetUpsertRequest> = {},
): PoiCacheTargetUpsertRequest {
  return {
    coord: { lon: LON, lat: LAT },
    coord_precision_digits: 6,
    radius_km: 5,
    name: null,
    scope_mode: "center_radius",
    update_enabled: true,
    refresh_policy: "provider_default",
    on_conflict: "reject",
    metadata: {},
    provider_overrides: {},
    ...overrides,
  };
}

function listBySystemPath(
  externalSystem: string,
  includeDeleted: boolean,
): string {
  return `${LIST_PATH}?external_system=${encodeURIComponent(
    externalSystem,
  )}&include_deleted=${includeDeleted}`;
}

function targetPathWithDeleted(
  externalSystem: string,
  targetKey: string,
  includeDeleted: boolean,
): string {
  return `${poiTargetPath(
    externalSystem,
    targetKey,
  )}?include_deleted=${includeDeleted}`;
}

async function putTarget(
  page: Page,
  externalSystem: string,
  targetKey: string,
  body: PoiCacheTargetUpsertRequest,
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  return browserFetch<PoiCacheTargetMutationResponse>(
    page,
    poiTargetPath(externalSystem, targetKey),
    { method: "PUT", body },
  );
}

async function getTargetByKey(
  page: Page,
  externalSystem: string,
  targetKey: string,
  includeDeleted = false,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  const path = includeDeleted
    ? targetPathWithDeleted(externalSystem, targetKey, true)
    : poiTargetPath(externalSystem, targetKey);
  return browserFetch<PoiCacheTargetResponse>(page, path);
}

async function listTargetsBySystem(
  page: Page,
  externalSystem: string,
  includeDeleted: boolean,
): Promise<BrowserFetchResult<PoiCacheTargetListResponse>> {
  return browserFetch<PoiCacheTargetListResponse>(
    page,
    listBySystemPath(externalSystem, includeDeleted),
  );
}

async function softDeleteByKey(
  page: Page,
  externalSystem: string,
  targetKey: string,
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  const current = await getTargetByKey(page, externalSystem, targetKey);
  if (current.status !== 200 || current.etag === null) {
    return { ...current, body: null };
  }
  return browserFetch<PoiCacheTargetMutationResponse>(
    page,
    poiTargetPath(externalSystem, targetKey),
    { method: "DELETE", headers: { "If-Match": current.etag } },
  );
}

test.describe("/admin/poi-cache-targets POI cache target write round-trip (live)", () => {
  test("API PUT로 target을 생성/수정/삭제하면 백엔드와 admin 목록·상세에 모두 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    let created = false;
    let removed = false;
    let liveSocketOpened = false;
    let latestEntityTag: string | null = null;

    try {
      await test.step("admin POI cache targets 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
        await openDatasetProjectionSocket(page);
        liveSocketOpened = true;
      });

      await test.step("API PUT로 고유 target을 생성하고 GET으로 영속화를 확인한다", async () => {
        const frameCursor = await datasetProjectionFrameCursor(page);
        const createResponse = await browserFetch<PoiCacheTargetMutationResponse>(
          page,
          poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
          { method: "PUT", body: upsertBody(CREATE_NAME, POI_ID_A) },
        );
        expect(createResponse.status).toBe(200);
        created = true;
        expect(createResponse.etag).toBe(createResponse.body?.data.entity_tag);
        latestEntityTag = createResponse.body?.data.entity_tag ?? null;
        expect(latestEntityTag).not.toBeNull();
        const receipt = causalRevision(createResponse);
        expect(receipt).toEqual(expect.any(Number));
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
        );
        expect(createResponse.body?.data).toMatchObject({
          external_system: EXTERNAL_SYSTEM,
          target_key: TARGET_KEY,
          name: CREATE_NAME,
          scope_mode: "center_radius",
          refresh_policy: "provider_default",
          update_enabled: true,
        });
        expect(createResponse.body?.data.coord).toMatchObject({
          lon: LON,
          lat: LAT,
        });

        // 단건 GET이 방금 보낸 body로 영속화될 때까지 polling(최종 일관성).
        await expect
          .poll(async () => {
            const detail = await fetchTarget(page);
            return detail.body?.data.name ?? `http:${detail.status}`;
          }, T)
          .toBe(CREATE_NAME);

        const detail = await fetchTarget(page);
        expect(detail.status).toBe(200);
        expect(detail.etag).toBe(detail.body?.data.entity_tag);
        expect(detail.body?.data).toMatchObject({
          external_system: EXTERNAL_SYSTEM,
          target_key: TARGET_KEY,
          name: CREATE_NAME,
          radius_km: 5,
          scope_mode: "center_radius",
          refresh_policy: "provider_default",
        });
        expect(detail.body?.data.metadata.external_poi_id).toBe(POI_ID_A);

        // external_system 필터 목록에도 정확히 1건 노출.
        await expect
          .poll(async () => {
            const list = await browserFetch<PoiCacheTargetListResponse>(
              page,
              poiTargetListBySystemPath(EXTERNAL_SYSTEM),
            );
            return list.body?.data.items.map((item) => item.target_key) ?? [];
          }, T)
          .toEqual([TARGET_KEY]);
      });

      await test.step("admin 목록을 다시 열면 새 target ROW가 필드와 함께 보이고, 선택 시 Nearby 상세에 key가 노출된다", async () => {
        await refreshList(page);

        const row = rowContaining(page, CREATE_NAME);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("center_radius");
        await expect(row).toContainText("provider_default");
        // enabled 컬럼은 StatusBadge(update_enabled→"active") → statusLabel로 "활성" 렌더.
        await expect(row).toContainText("활성");

        // row 클릭 → selectedTarget → Nearby features 헤더에 external_system/target_key 노출.
        await expect(page.getByText("target을 선택하세요")).toBeVisible(T);
        await row.click();
        await expect(
          page.getByText(`${EXTERNAL_SYSTEM}/${TARGET_KEY}`),
        ).toBeVisible(T);
      });

      await test.step("API PUT로 name/metadata를 수정하면 GET과 admin 목록이 갱신값으로 바뀐다", async () => {
        const frameCursor = await datasetProjectionFrameCursor(page);
        const updateResponse = await browserFetch<PoiCacheTargetMutationResponse>(
          page,
          poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
          { method: "PUT", body: upsertBody(UPDATED_NAME, POI_ID_B) },
        );
        expect(updateResponse.status).toBe(200);
        expect(updateResponse.etag).toBe(updateResponse.body?.data.entity_tag);
        latestEntityTag = updateResponse.body?.data.entity_tag ?? null;
        expect(latestEntityTag).not.toBeNull();
        const receipt = causalRevision(updateResponse);
        expect(receipt).toEqual(expect.any(Number));
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
        );
        expect(updateResponse.body?.data.name).toBe(UPDATED_NAME);

        await expect
          .poll(async () => {
            const detail = await fetchTarget(page);
            return detail.body?.data.metadata.external_poi_id ?? `http:${detail.status}`;
          }, T)
          .toBe(POI_ID_B);

        const detail = await fetchTarget(page);
        expect(detail.body?.data.name).toBe(UPDATED_NAME);
        expect(detail.body?.data.metadata.external_poi_id).toBe(POI_ID_B);

        // 같은 페이지에서 새로고침(목록 GET refetch) → 갱신된 name으로 ROW가 재렌더되고
        // 이전 name ROW는 사라진다.
        await refreshList(page);
        await expect(rowContaining(page, UPDATED_NAME)).toBeVisible(T);
        await expect(rowContaining(page, CREATE_NAME)).toHaveCount(0, T);
      });

      await test.step("API DELETE 후 GET은 404, admin 목록에서도 ROW가 사라진다", async () => {
        const frameCursor = await datasetProjectionFrameCursor(page);
        if (latestEntityTag === null) {
          throw new Error("latest server entity_tag is missing before DELETE");
        }
        const deleted = await deleteTargetByApi(page, latestEntityTag);
        expect(deleted.status).toBe(200);
        expect(deleted.etag).toBe(deleted.body?.data.entity_tag);
        latestEntityTag = deleted.body?.data.entity_tag ?? null;
        const receipt = causalRevision(deleted);
        expect(receipt).toEqual(expect.any(Number));
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
        );
        removed = true;

        await expect
          .poll(async () => {
            const detail = await fetchTarget(page);
            return detail.status;
          }, T)
          .toBe(404);

        // external_system 필터 목록도 빈다(soft delete + deleted_at 필터).
        await expect
          .poll(async () => {
            const list = await browserFetch<PoiCacheTargetListResponse>(
              page,
              poiTargetListBySystemPath(EXTERNAL_SYSTEM),
            );
            return list.body?.data.items.length ?? -1;
          }, T)
          .toBe(0);

        await refreshList(page);
        await expect(rowContaining(page, UPDATED_NAME)).toHaveCount(0, T);
        await expect(rowContaining(page, CREATE_NAME)).toHaveCount(0, T);
      });
    } finally {
      if (liveSocketOpened) {
        await closeDatasetProjectionSocket(page);
      }
      // 생성됐고 아직 살아있으면 정리. 이미 삭제됐거나(404) destructive kill-switch(403)면 무시.
      if (created && !removed && latestEntityTag !== null) {
        try {
          await deleteTargetByApi(page, latestEntityTag);
        } catch {
          // best-effort cleanup
        }
      }
    }
  });

  test("DELETE는 UUID+version strong If-Match를 요구하고 stale version으로 active target을 지우지 않는다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("if-match");
    let created = false;

    try {
      await gotoPoiTargets(page);
      const createdResponse = await putTarget(
        page,
        externalSystem,
        targetKey,
        buildUpsert({ name }),
      );
      expect(createdResponse.status).toBe(200);
      created = true;
      const staleEntityTag = createdResponse.body?.data.entity_tag;
      expect(staleEntityTag).toEqual(expect.any(String));
      expect(createdResponse.etag).toBe(staleEntityTag);

      const missing = await browserFetch<PoiCacheTargetMutationResponse>(
        page,
        poiTargetPath(externalSystem, targetKey),
        { method: "DELETE" },
      );
      expect(missing.status).toBe(428);

      const updatedResponse = await putTarget(
        page,
        externalSystem,
        targetKey,
        buildUpsert({ name: `${name} updated` }),
      );
      expect(updatedResponse.status).toBe(200);
      expect(updatedResponse.body?.data.target_id).toBe(
        createdResponse.body?.data.target_id,
      );
      const currentEntityTag = updatedResponse.body?.data.entity_tag;
      expect(currentEntityTag).toEqual(expect.any(String));
      expect(updatedResponse.etag).toBe(currentEntityTag);
      expect(currentEntityTag).not.toBe(staleEntityTag);

      const stale = await browserFetch<PoiCacheTargetMutationResponse>(
        page,
        poiTargetPath(externalSystem, targetKey),
        {
          method: "DELETE",
          headers: { "If-Match": staleEntityTag ?? "" },
        },
      );
      expect(stale.status).toBe(412);
      const surviving = await getTargetByKey(page, externalSystem, targetKey);
      expect(surviving.status).toBe(200);
      expect(surviving.etag).toBe(currentEntityTag);

      const deleted = await browserFetch<PoiCacheTargetMutationResponse>(
        page,
        poiTargetPath(externalSystem, targetKey),
        {
          method: "DELETE",
          headers: { "If-Match": currentEntityTag ?? "" },
        },
      );
      expect(deleted.status).toBe(200);
      expect(deleted.etag).toBe(deleted.body?.data.entity_tag);
      expect(deleted.etag).not.toBe(currentEntityTag);
      expect(causalRevision(deleted)).toEqual(expect.any(Number));
      created = false;
    } finally {
      if (created) {
        try {
          await softDeleteByKey(page, externalSystem, targetKey);
        } catch {
          // best-effort cleanup
        }
      }
    }
  });

  test("동일 external_system/target_key로 PUT을 두 번 보내도 on_conflict=move 없이 같은 row를 갱신할 뿐 중복이 생기지 않는다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("idem");
    let created = false;
    let firstTargetId = "";
    let firstCreatedAt = "";
    let firstUpdatedAt = "";

    try {
      await test.step("admin 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
      });

      await test.step("첫 PUT으로 target을 생성하고 target_id/created_at을 기록한다", async () => {
        const first = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({ name }),
        );
        expect(first.status).toBe(200);
        created = true;
        expect(first.body?.data).toMatchObject({
          external_system: externalSystem,
          target_key: targetKey,
          name,
        });
        firstTargetId = first.body?.data.target_id ?? "";
        firstCreatedAt = first.body?.data.created_at ?? "";
        firstUpdatedAt = first.body?.data.updated_at ?? "";
        expect(firstTargetId).not.toBe("");
      });

      await test.step("같은 key/좌표로 다시 PUT하면 on_conflict 충돌 없이 target_id·created_at은 유지되고 updated_at만 갱신된다", async () => {
        const second = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({ name }),
        );
        expect(second.status).toBe(200);
        expect(second.body?.data.target_id).toBe(firstTargetId);
        expect(second.body?.data.created_at).toBe(firstCreatedAt);
        expect(
          new Date(second.body?.data.updated_at ?? 0).getTime(),
        ).toBeGreaterThanOrEqual(new Date(firstUpdatedAt).getTime());
      });

      await test.step("external_system 필터 목록·단건 GET 모두 정확히 1건만 존재한다(중복 row 없음)", async () => {
        await expect
          .poll(async () => {
            const list = await listTargetsBySystem(page, externalSystem, false);
            return list.body?.data.items.map((item) => item.target_id) ?? [];
          }, T)
          .toEqual([firstTargetId]);

        const detail = await getTargetByKey(page, externalSystem, targetKey);
        expect(detail.status).toBe(200);
        expect(detail.body?.data.target_id).toBe(firstTargetId);
      });

      await test.step("admin 목록에도 같은 name ROW가 1개만 렌더된다", async () => {
        await gotoPoiTargets(page);
        await expect(rowContaining(page, name)).toHaveCount(1, T);
      });
    } finally {
      if (created) {
        try {
          await softDeleteByKey(page, externalSystem, targetKey);
        } catch {
          // best-effort cleanup
        }
      }
    }
  });

  test("좌표/반경이 범위를 벗어나면 API가 422로 거절하고 백엔드·admin 목록에 아무 것도 생기지 않는다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("invalid");

    try {
      await test.step("admin 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
      });

      await test.step("한국 경계를 벗어난 lon은 422 detail로 거절된다", async () => {
        const res = await browserFetch<ValidationErrorBody>(
          page,
          poiTargetPath(externalSystem, targetKey),
          { method: "PUT", body: buildUpsert({ name, coord: { lon: 200, lat: LAT } }) },
        );
        expect(res.status).toBe(422);
        expect(res.body?.detail).toBeTruthy();
      });

      await test.step("radius_km<=0 / radius_km>100 모두 422로 거절된다", async () => {
        const tooSmall = await browserFetch<ValidationErrorBody>(
          page,
          poiTargetPath(externalSystem, targetKey),
          { method: "PUT", body: buildUpsert({ name, radius_km: 0 }) },
        );
        expect(tooSmall.status).toBe(422);

        const tooLarge = await browserFetch<ValidationErrorBody>(
          page,
          poiTargetPath(externalSystem, targetKey),
          { method: "PUT", body: buildUpsert({ name, radius_km: 200 }) },
        );
        expect(tooLarge.status).toBe(422);
      });

      await test.step("거절된 입력은 단건 GET 404 / 목록 0건으로 백엔드에 남지 않는다", async () => {
        const detail = await getTargetByKey(page, externalSystem, targetKey);
        expect(detail.status).toBe(404);

        // include_deleted=true로도 흔적이 없어야 한다(아예 INSERT되지 않음).
        const list = await listTargetsBySystem(page, externalSystem, true);
        expect(list.body?.data.items.length ?? -1).toBe(0);
      });

      await test.step("admin 폼이 서버 검증(lat 39.5 초과)에서 422를 받으면 오류 Alert가 노출되고 ROW는 생기지 않는다", async () => {
        await gotoPoiTargets(page);
        await page.getByLabel("외부 시스템").fill(externalSystem);
        await page.getByLabel("대상 키").fill(targetKey);
        await page.getByLabel("이름").fill(name);
        await page.getByLabel("경도", { exact: true }).fill(String(LON));
        // client 검증(33~43)은 통과하지만 서버 CoordinateBody(lat<=39.5)는 거절한다.
        await page.getByLabel("위도", { exact: true }).fill("41");
        await page.getByLabel("반경(km)").fill("5");

        const putResponse = waitForApiResponse(
          page,
          "PUT",
          decodeURIComponent(poiTargetPath(externalSystem, targetKey)),
        );
        await page.getByRole("button", { name: "저장" }).click();
        const response = await putResponse;
        expect(response.status()).toBe(422);

        await expect(page.getByText("target 처리 실패")).toBeVisible(T);
        await expect(rowContaining(page, name)).toHaveCount(0, T);

        const after = await getTargetByKey(page, externalSystem, targetKey);
        expect(after.status).toBe(404);
      });
    } finally {
      try {
        await softDeleteByKey(page, externalSystem, targetKey);
      } catch {
        // best-effort cleanup (보통 아무 것도 생성되지 않아 404)
      }
    }
  });

  test("soft-delete 후 include_deleted=true는 row를 보여주고 false는 숨긴다(단건·목록·admin)", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("deleted");
    let created = false;

    try {
      await test.step("target을 생성하고 admin 목록에 노출되는지 확인한다", async () => {
        await gotoPoiTargets(page);
        const res = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({ name }),
        );
        expect(res.status).toBe(200);
        created = true;

        await gotoPoiTargets(page);
        await expect(rowContaining(page, name)).toBeVisible(T);
      });

      await test.step("API DELETE로 soft-delete한다", async () => {
        const deleted = await softDeleteByKey(page, externalSystem, targetKey);
        expect(deleted.status).toBe(200);
        expect(causalRevision(deleted)).toEqual(expect.any(Number));
      });

      await test.step("단건 GET: 기본(include_deleted=false)은 404, include_deleted=true는 200+deleted_at", async () => {
        await expect
          .poll(async () => {
            const live = await getTargetByKey(page, externalSystem, targetKey, false);
            return live.status;
          }, T)
          .toBe(404);

        const withDeleted = await getTargetByKey(
          page,
          externalSystem,
          targetKey,
          true,
        );
        expect(withDeleted.status).toBe(200);
        expect(withDeleted.body?.data.deleted_at).toBeTruthy();
        expect(withDeleted.body?.data.update_enabled).toBe(false);
      });

      await test.step("목록 GET: include_deleted=true는 노출, false는 숨김", async () => {
        const included = await listTargetsBySystem(page, externalSystem, true);
        expect(included.body?.data.items.map((item) => item.target_key)).toEqual([
          targetKey,
        ]);

        const excluded = await listTargetsBySystem(page, externalSystem, false);
        expect(excluded.body?.data.items.length).toBe(0);
      });

      await test.step("admin 목록(기본 include_deleted=false)에서도 ROW가 사라진다", async () => {
        await refreshList(page);
        await expect(rowContaining(page, name)).toHaveCount(0, T);
      });
    } finally {
      if (created) {
        try {
          await softDeleteByKey(page, externalSystem, targetKey);
        } catch {
          // best-effort cleanup (이미 삭제됨)
        }
      }
    }
  });

  test("scope_mode를 sigungu_by_radius로 생성한 뒤 center_radius로 갱신하면 GET·admin scope 컬럼이 따라 바뀐다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("scope");
    let created = false;

    try {
      await test.step("admin 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
      });

      await test.step("sigungu_by_radius로 생성하고 GET이 반영하는지 확인한다", async () => {
        const res = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({ name, scope_mode: "sigungu_by_radius" }),
        );
        expect(res.status).toBe(200);
        created = true;
        expect(res.body?.data.scope_mode).toBe("sigungu_by_radius");

        await expect
          .poll(async () => {
            const detail = await getTargetByKey(page, externalSystem, targetKey);
            return detail.body?.data.scope_mode ?? `http:${detail.status}`;
          }, T)
          .toBe("sigungu_by_radius");
      });

      await test.step("admin 목록 scope 컬럼에 sigungu_by_radius가 보인다", async () => {
        await gotoPoiTargets(page);
        const row = rowContaining(page, name);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("sigungu_by_radius");
      });

      await test.step("center_radius로 갱신하면 GET·admin이 center_radius로 바뀌고 이전 값은 사라진다", async () => {
        const res = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({ name, scope_mode: "center_radius" }),
        );
        expect(res.status).toBe(200);
        expect(res.body?.data.scope_mode).toBe("center_radius");

        await expect
          .poll(async () => {
            const detail = await getTargetByKey(page, externalSystem, targetKey);
            return detail.body?.data.scope_mode ?? `http:${detail.status}`;
          }, T)
          .toBe("center_radius");

        await refreshList(page);
        const row = rowContaining(page, name);
        await expect(row).toContainText("center_radius");
        await expect(row).not.toContainText("sigungu_by_radius");
      });
    } finally {
      if (created) {
        try {
          await softDeleteByKey(page, externalSystem, targetKey);
        } catch {
          // best-effort cleanup
        }
      }
    }
  });

  test("metadata·provider_overrides를 설정하면 GET에 그대로 persisted되고, override 갱신도 반영된다", async ({
    page,
  }) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);

    const { externalSystem, targetKey, name } = scenarioKeys("meta");
    const OVERRIDE_KEY = "kma-mcst";
    const metadata: PoiCacheTargetUpsertRequest["metadata"] = {
      external_poi_id: `${RUN_ID}-poi`,
      external_ref: `${RUN_ID}-ref`,
      source_url: "https://example.invalid/e2e-meta",
      labels: ["e2e-label", "poi-cache"],
      note: `e2e meta ${RUN_ID}`,
    };
    let created = false;

    try {
      await test.step("admin 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
      });

      await test.step("metadata+provider_overrides+refresh_policy(allow_targeted)/disabled로 생성한다", async () => {
        const res = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({
            name,
            update_enabled: false,
            refresh_policy: "allow_targeted",
            metadata,
            provider_overrides: {
              [OVERRIDE_KEY]: {
                targeted_policy: "allow_targeted",
                min_interval_seconds: 600,
                max_requests_per_day: 1000,
                note: "e2e override",
              },
            },
          }),
        );
        expect(res.status).toBe(200);
        created = true;
        expect(res.body?.data.metadata).toMatchObject({
          external_poi_id: `${RUN_ID}-poi`,
          external_ref: `${RUN_ID}-ref`,
          source_url: "https://example.invalid/e2e-meta",
          labels: ["e2e-label", "poi-cache"],
          note: `e2e meta ${RUN_ID}`,
        });
        expect(res.body?.data.provider_overrides[OVERRIDE_KEY]).toMatchObject({
          targeted_policy: "allow_targeted",
          min_interval_seconds: 600,
          max_requests_per_day: 1000,
          note: "e2e override",
        });
      });

      await test.step("단건 GET이 metadata·provider_overrides를 그대로 영속화한다", async () => {
        await expect
          .poll(async () => {
            const detail = await getTargetByKey(page, externalSystem, targetKey);
            const meta = detail.body?.data.metadata as
              | { external_ref?: string }
              | undefined;
            return meta?.external_ref ?? `http:${detail.status}`;
          }, T)
          .toBe(`${RUN_ID}-ref`);

        const detail = await getTargetByKey(page, externalSystem, targetKey);
        expect(detail.body?.data.metadata).toMatchObject({
          external_poi_id: `${RUN_ID}-poi`,
          labels: ["e2e-label", "poi-cache"],
        });
        expect(detail.body?.data.provider_overrides[OVERRIDE_KEY]).toMatchObject({
          min_interval_seconds: 600,
          max_requests_per_day: 1000,
        });
      });

      await test.step("admin 목록 refresh/enabled 컬럼이 allow_targeted·disabled로 반영된다", async () => {
        await gotoPoiTargets(page);
        const row = rowContaining(page, name);
        await expect(row).toBeVisible(T);
        await expect(row).toContainText("allow_targeted");
        // enabled 컬럼은 StatusBadge(update_enabled=false→"disabled") → statusLabel로 "비활성화" 렌더.
        await expect(row).toContainText("비활성화");
      });

      await test.step("provider_overrides min_interval_seconds를 갱신하면 GET이 새 값으로 바뀐다", async () => {
        const res = await putTarget(
          page,
          externalSystem,
          targetKey,
          buildUpsert({
            name,
            update_enabled: false,
            refresh_policy: "allow_targeted",
            metadata,
            provider_overrides: {
              [OVERRIDE_KEY]: {
                targeted_policy: "allow_targeted",
                min_interval_seconds: 1200,
                max_requests_per_day: 1000,
                note: "e2e override",
              },
            },
          }),
        );
        expect(res.status).toBe(200);

        await expect
          .poll(async () => {
            const detail = await getTargetByKey(page, externalSystem, targetKey);
            const override = detail.body?.data.provider_overrides[OVERRIDE_KEY] as
              | { min_interval_seconds?: number }
              | undefined;
            return override?.min_interval_seconds ?? -1;
          }, T)
          .toBe(1200);
      });
    } finally {
      if (created) {
        try {
          await softDeleteByKey(page, externalSystem, targetKey);
        } catch {
          // best-effort cleanup
        }
      }
    }
  });
});
