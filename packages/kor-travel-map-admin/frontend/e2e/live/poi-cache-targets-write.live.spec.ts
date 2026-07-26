import { randomUUID } from "node:crypto";
import { chmod, open, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

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
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STRONG_ENTITY_TAG_PATTERN =
  /^"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):([1-9][0-9]*)"$/;

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

// 개편 B(d8818994, "헤딩 정본")에서 admin h1이 한국어 정본으로 통일됐다.
// page.tsx metadata의 영문 <title>과는 별개다 — 실제 <h1>은 "POI 캐시 대상".
const POI_HEADING = "POI 캐시 대상";

type PoiMutationJournal = {
  entity_tag: string | null;
  intended_body: PoiCacheTargetUpsertRequest;
  lock_version: number | null;
  natural_key: { external_system: string; target_key: string };
  phase: string;
  run_id: string;
  same_socket_receipts: number[];
  target_id: string | null;
  updated_at: string;
  version: 1;
};

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseStrongEntityTag(
  entityTag: string,
  expectedTargetId?: string,
): number {
  const match = STRONG_ENTITY_TAG_PATTERN.exec(entityTag);
  if (
    match === null ||
    (expectedTargetId !== undefined && match[1] !== expectedTargetId)
  ) {
    throw new Error("POI target UUID+version strong entity_tag 계약 불일치");
  }
  const version = Number(match[2]);
  if (!Number.isSafeInteger(version) || version <= 0) {
    throw new Error("POI target lock version 계약 불일치");
  }
  return version;
}

function requireTargetIdentity(
  result: BrowserFetchResult<PoiCacheTargetResponse | PoiCacheTargetMutationResponse>,
  expectedTargetId?: string,
): { entityTag: string; lockVersion: number; targetId: string } {
  const targetId = result.body?.data.target_id;
  const entityTag = result.body?.data.entity_tag;
  if (
    result.status !== 200 ||
    typeof targetId !== "string" ||
    !UUID_PATTERN.test(targetId) ||
    typeof entityTag !== "string" ||
    result.etag !== entityTag ||
    (expectedTargetId !== undefined && targetId !== expectedTargetId)
  ) {
    throw new Error("POI target response UUID/ETag identity 계약 불일치");
  }
  return {
    entityTag,
    lockVersion: parseStrongEntityTag(entityTag, targetId),
    targetId,
  };
}

function poiStateFile(): string {
  const configured = process.env.E2E_C7_POI_STATE_FILE;
  if (!configured || !path.isAbsolute(configured)) {
    throw new Error(
      "E2E_C7_POI_STATE_FILE은 host orchestrator가 지정한 절대 경로여야 합니다.",
    );
  }
  return configured;
}

async function claimPoiStateFile(): Promise<void> {
  const raw = JSON.parse(await readFile(poiStateFile(), "utf8")) as unknown;
  if (
    typeof raw !== "object" ||
    raw === null ||
    Array.isArray(raw) ||
    (raw as { phase?: unknown }).phase !== "orchestrator_pending" ||
    (raw as { version?: unknown }).version !== 1
  ) {
    throw new Error(
      "C7 POI mutation journal이 신규 orchestrator sentinel이 아닙니다.",
    );
  }
}

async function writePoiJournal(
  phase: string,
  intendedBody: PoiCacheTargetUpsertRequest,
  identity: {
    entityTag: string | null;
    lockVersion: number | null;
    targetId: string | null;
  },
  sameSocketReceipts: readonly number[],
): Promise<void> {
  const stateFile = poiStateFile();
  const temporary = `${stateFile}.${process.pid}.${randomUUID()}.tmp`;
  const journal: PoiMutationJournal = {
    entity_tag: identity.entityTag,
    intended_body: intendedBody,
    lock_version: identity.lockVersion,
    natural_key: {
      external_system: EXTERNAL_SYSTEM,
      target_key: TARGET_KEY,
    },
    phase,
    run_id: RUN_ID,
    same_socket_receipts: [...sameSocketReceipts],
    target_id: identity.targetId,
    updated_at: new Date().toISOString(),
    version: 1,
  };
  await writeFile(temporary, `${JSON.stringify(journal)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  await chmod(temporary, 0o600);
  const temporaryHandle = await open(temporary, "r");
  try {
    await temporaryHandle.sync();
  } finally {
    await temporaryHandle.close();
  }
  await rename(temporary, stateFile);
  await chmod(stateFile, 0o600);
  const stateHandle = await open(stateFile, "r");
  try {
    await stateHandle.sync();
  } finally {
    await stateHandle.close();
  }
  const directoryHandle = await open(path.dirname(stateFile), "r");
  try {
    await directoryHandle.sync();
  } finally {
    await directoryHandle.close();
  }
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
  expected: { entityTag: string; lockVersion: number; targetId: string },
  expectedBody: PoiCacheTargetUpsertRequest,
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  const current = await fetchTarget(page);
  const identity = requireTargetIdentity(current, expected.targetId);
  assertExactIntendedTarget(current, expectedBody, expected.targetId);
  if (
    identity.entityTag !== expected.entityTag ||
    identity.lockVersion !== expected.lockVersion
  ) {
    throw new Error(
      "POI target가 마지막 관찰 뒤 변경되어 cleanup/delete를 차단했습니다",
    );
  }
  return browserFetch<PoiCacheTargetMutationResponse>(
    page,
    poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
    { method: "DELETE", headers: { "If-Match": identity.entityTag } },
  );
}

function canonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJson(item)]),
  );
}

function exactJson(left: unknown, right: unknown): boolean {
  return (
    JSON.stringify(canonicalJson(left)) ===
    JSON.stringify(canonicalJson(right))
  );
}

function assertExactIntendedTarget(
  result: BrowserFetchResult<PoiCacheTargetResponse | PoiCacheTargetMutationResponse>,
  intendedBody: PoiCacheTargetUpsertRequest,
  expectedTargetId?: string,
): { entityTag: string; lockVersion: number; targetId: string } {
  const identity = requireTargetIdentity(result, expectedTargetId);
  const record = result.body?.data;
  if (
    record === undefined ||
    record.external_system !== EXTERNAL_SYSTEM ||
    record.target_key !== TARGET_KEY ||
    (record.deleted_at !== null && record.deleted_at !== undefined) ||
    !exactJson(record.coord, intendedBody.coord) ||
    record.coord_precision_digits !== intendedBody.coord_precision_digits ||
    record.radius_km !== intendedBody.radius_km ||
    record.name !== (intendedBody.name ?? null) ||
    record.scope_mode !== intendedBody.scope_mode ||
    record.update_enabled !== intendedBody.update_enabled ||
    record.refresh_policy !== intendedBody.refresh_policy ||
    !exactJson(
      record.provider_overrides,
      intendedBody.provider_overrides ?? {},
    ) ||
    !exactJson(record.metadata, intendedBody.metadata ?? {})
  ) {
    throw new Error("POI target intended body exact ownership 계약 불일치");
  }
  return identity;
}

async function putWithCausalResponseRecovery(
  page: Page,
  intendedBody: PoiCacheTargetUpsertRequest,
  priorIdentity: {
    entityTag: string;
    lockVersion: number;
    targetId: string;
  } | null,
  sameSocketReceipts: readonly number[],
  phase: "create" | "update",
  committedResponseEvidence?: () => BrowserFetchResult<PoiCacheTargetMutationResponse> | null,
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  const put = () =>
    browserFetch<PoiCacheTargetMutationResponse>(
      page,
      poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY),
      { method: "PUT", body: intendedBody },
    );
  let result: BrowserFetchResult<PoiCacheTargetMutationResponse>;
  try {
    result = await put();
  } catch {
    await writePoiJournal(
      `${phase}_put_response_lost`,
      intendedBody,
      priorIdentity ?? { entityTag: null, lockVersion: null, targetId: null },
      sameSocketReceipts,
    );
    const rediscovered = await fetchTarget(page);
    if (rediscovered.status === 200) {
      const identity = assertExactIntendedTarget(
        rediscovered,
        intendedBody,
        priorIdentity?.targetId,
      );
      if (
        priorIdentity !== null &&
        identity.lockVersion <= priorIdentity.lockVersion
      ) {
        throw new Error("POI PUT response-loss update version이 전진하지 않았습니다");
      }
      await writePoiJournal(
        `${phase}_put_response_lost_rediscovered`,
        intendedBody,
        identity,
        sameSocketReceipts,
      );
      const committed = committedResponseEvidence?.() ?? null;
      if (committed === null) {
        throw new Error(
          "POI PUT commit은 재탐색됐지만 causal receipt가 유실되어 BLOCKED합니다",
        );
      }
      const committedIdentity = assertExactIntendedTarget(
        committed,
        intendedBody,
        identity.targetId,
      );
      if (
        committedIdentity.entityTag !== identity.entityTag ||
        committedIdentity.lockVersion !== identity.lockVersion ||
        causalRevision(committed) <= 0
      ) {
        throw new Error("POI PUT committed response/rediscovery identity 불일치");
      }
      await writePoiJournal(
        `${phase}_put_response_lost_causal_receipt_recovered`,
        intendedBody,
        identity,
        sameSocketReceipts,
      );
      result = committed;
    } else if (rediscovered.status !== 404) {
      throw new Error(
        `POI PUT response-loss 재탐색 실패(status=${rediscovered.status})`,
      );
    } else {
      await writePoiJournal(
        `${phase}_put_replay_intent`,
        intendedBody,
        priorIdentity ?? { entityTag: null, lockVersion: null, targetId: null },
        sameSocketReceipts,
      );
      try {
        result = await put();
      } catch {
        const afterReplay = await fetchTarget(page);
        if (afterReplay.status === 200) {
          const identity = assertExactIntendedTarget(
            afterReplay,
            intendedBody,
            priorIdentity?.targetId,
          );
          await writePoiJournal(
            `${phase}_put_replay_response_lost`,
            intendedBody,
            identity,
            sameSocketReceipts,
          );
        } else {
          await writePoiJournal(
            `${phase}_put_replay_uncertain`,
            intendedBody,
            priorIdentity ?? {
              entityTag: null,
              lockVersion: null,
              targetId: null,
            },
            sameSocketReceipts,
          );
        }
        throw new Error("POI PUT replay 응답도 유실되어 BLOCKED합니다");
      }
    }
  }

  const identity = assertExactIntendedTarget(
    result,
    intendedBody,
    priorIdentity?.targetId,
  );
  if (
    priorIdentity !== null &&
    identity.lockVersion <= priorIdentity.lockVersion
  ) {
    throw new Error("POI target update lock version이 전진하지 않았습니다");
  }
  const exactRead = await fetchTarget(page);
  const exactIdentity = assertExactIntendedTarget(
    exactRead,
    intendedBody,
    identity.targetId,
  );
  if (
    exactIdentity.entityTag !== identity.entityTag ||
    exactIdentity.lockVersion !== identity.lockVersion
  ) {
    throw new Error("POI PUT 직후 exact GET identity/version 불일치");
  }
  return result;
}

async function putWithDeterministicCommittedResponseLoss(
  page: Page,
  intendedBody: PoiCacheTargetUpsertRequest,
  sameSocketReceipts: readonly number[],
): Promise<BrowserFetchResult<PoiCacheTargetMutationResponse>> {
  const exactUrl = new URL(
    `/api/proxy${poiTargetPath(EXTERNAL_SYSTEM, TARGET_KEY)}`,
    page.url(),
  ).href;
  let activeRouteHandlers = 0;
  let committed: BrowserFetchResult<PoiCacheTargetMutationResponse> | null = null;
  let handlerError: unknown = null;
  let putAttempts = 0;
  const settlementWaiters = new Set<() => void>();
  const waitForSettlement = (): Promise<void> => {
    if (activeRouteHandlers === 0) return Promise.resolve();
    return new Promise<void>((resolve) => settlementWaiters.add(resolve));
  };
  const routeHandler = async (
    route: import("@playwright/test").Route,
  ): Promise<void> => {
    activeRouteHandlers += 1;
    try {
      const request = route.request();
      if (request.method() !== "PUT") {
        await route.fallback();
        return;
      }
      putAttempts += 1;
      if (
        putAttempts !== 1 ||
        request.url() !== exactUrl ||
        !exactJson(request.postDataJSON(), intendedBody)
      ) {
        throw new Error("deterministic PUT response-loss request 계약 불일치");
      }
      const upstream = await route.fetch();
      const text = await upstream.text();
      let body: PoiCacheTargetMutationResponse | null = null;
      try {
        body = JSON.parse(text) as PoiCacheTargetMutationResponse;
      } catch {
        body = null;
      }
      const evidence: BrowserFetchResult<PoiCacheTargetMutationResponse> = {
        body,
        etag: upstream.headers()["etag"] ?? null,
        status: upstream.status(),
        text,
      };
      assertExactIntendedTarget(evidence, intendedBody);
      causalRevision(evidence);
      committed = evidence;
      await route.abort("failed");
    } catch (error) {
      handlerError = error;
      await route.abort("failed").catch(() => undefined);
    } finally {
      activeRouteHandlers -= 1;
      if (activeRouteHandlers === 0) {
        for (const resolve of settlementWaiters) resolve();
        settlementWaiters.clear();
      }
    }
  };
  await page.route(exactUrl, routeHandler);
  let primaryError: unknown;
  try {
    const result = await putWithCausalResponseRecovery(
      page,
      intendedBody,
      null,
      sameSocketReceipts,
      "create",
      () => committed,
    );
    if (putAttempts !== 1 || committed === null || handlerError !== null) {
      throw new Error("deterministic committed PUT response-loss 증거 불완전");
    }
    return result;
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    const teardownErrors: unknown[] = [];
    await Promise.race([
      waitForSettlement(),
      new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error("POI PUT route settlement timeout")),
          UI_TIMEOUT,
        ),
      ),
    ]).catch((error: unknown) => teardownErrors.push(error));
    await page
      .unroute(exactUrl, routeHandler)
      .catch((error: unknown) => teardownErrors.push(error));
    if (teardownErrors.length > 0) {
      throw new AggregateError(
        primaryError === undefined
          ? teardownErrors
          : [primaryError, ...teardownErrors],
        "POI committed response-loss primary/route cleanup 실패",
      );
    }
  }
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
      __c7cLive?: {
        closed: boolean;
        connectionId: string;
        frames: unknown[];
        socket: WebSocket;
      };
    };
    const frames: unknown[] = [];
    const socket = new WebSocket(url, ticket.subprotocol);
    state.__c7cLive = {
      closed: false,
      connectionId: crypto.randomUUID(),
      frames,
      socket,
    };
    socket.addEventListener("close", () => {
      if (state.__c7cLive?.socket === socket) state.__c7cLive.closed = true;
    });
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
  connectionId: string,
): Promise<void> {
  if (!Number.isSafeInteger(receipt) || receipt <= 0) {
    throw new Error("dataset_projection receipt는 positive safe integer여야 합니다");
  }
  await expect
    .poll(
      () =>
        page.evaluate(({ connectionId, frameCursor, receipt }) => {
          const state = globalThis as typeof globalThis & {
            __c7cLive?: {
              closed: boolean;
              connectionId: string;
              frames: unknown[];
              socket: WebSocket;
            };
          };
          if (
            state.__c7cLive?.socket.readyState !== WebSocket.OPEN ||
            state.__c7cLive.closed ||
            state.__c7cLive.connectionId !== connectionId
          ) {
            return false;
          }
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
        }, { connectionId, frameCursor, receipt }),
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

async function datasetProjectionConnectionId(page: Page): Promise<string> {
  return page.evaluate(() => {
    const state = globalThis as typeof globalThis & {
      __c7cLive?: {
        closed: boolean;
        connectionId: string;
        socket: WebSocket;
      };
    };
    if (
      state.__c7cLive?.socket.readyState !== WebSocket.OPEN ||
      state.__c7cLive.closed
    ) {
      throw new Error("dataset_projection original socket is not open");
    }
    return state.__c7cLive.connectionId;
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
  const identity = requireTargetIdentity(current);
  const deleted = await browserFetch<PoiCacheTargetMutationResponse>(
    page,
    poiTargetPath(externalSystem, targetKey),
    { method: "DELETE", headers: { "If-Match": identity.entityTag } },
  );
  if (deleted.status === 412) {
    throw new Error(
      "POI cleanup DELETE가 412를 반환해 concurrent update 삭제를 차단했습니다",
    );
  }
  return deleted;
}

test.describe("/admin/poi-cache-targets POI cache target write round-trip (live)", () => {
  // `@c7-causal`은 C7 prod runner(scripts/run-c7-prod-live-e2e.sh)가 grep하는
  // 안정 tag다 — 한글 제목 문구가 바뀌어도 runner 계약이 깨지지 않는다.
  test("API PUT로 target을 생성/수정/삭제하면 백엔드와 admin 목록·상세에 모두 반영된다 @c7-causal", async ({
    page,
  }, testInfo) => {
    test.skip(
      !EXECUTE_POI_CACHE_WRITE,
      "E2E_POI_CACHE_WRITE=1 또는 E2E_ADMIN_WRITE=1일 때만 실제 POI cache target write flow를 실행",
    );
    test.setTimeout(FLOW_TIMEOUT);
    if (
      process.env.E2E_LIVE_ALLOW_PROD !== "1" ||
      process.env.E2E_ADMIN_WRITE !== "1" ||
      testInfo.config.workers !== 1 ||
      testInfo.project.retries !== 0
    ) {
      throw new Error(
        "C7 POI prod causal test는 orchestrator opt-in/workers=1/retries=0이 필요합니다.",
      );
    }
    await claimPoiStateFile();

    let mutationIntentWritten = false;
    let removed = false;
    let liveSocketOpened = false;
    let connectionId: string | null = null;
    let latestIdentity: {
      entityTag: string;
      lockVersion: number;
      targetId: string;
    } | null = null;
    let intendedBody = upsertBody(CREATE_NAME, POI_ID_A);
    const sameSocketReceipts: number[] = [];
    let primaryError: unknown;

    try {
      await test.step("admin POI cache targets 화면을 열어 same-origin 컨텍스트를 확보한다", async () => {
        await gotoPoiTargets(page);
        await openDatasetProjectionSocket(page);
        liveSocketOpened = true;
        connectionId = await datasetProjectionConnectionId(page);
      });

      await test.step("API PUT로 고유 target을 생성하고 GET으로 영속화를 확인한다", async () => {
        await writePoiJournal(
          "create_put_intent",
          intendedBody,
          { entityTag: null, lockVersion: null, targetId: null },
          sameSocketReceipts,
        );
        mutationIntentWritten = true;
        const frameCursor = await datasetProjectionFrameCursor(page);
        const createResponse = await putWithDeterministicCommittedResponseLoss(
          page,
          intendedBody,
          sameSocketReceipts,
        );
        expect(createResponse.status).toBe(200);
        latestIdentity = requireTargetIdentity(createResponse);
        await writePoiJournal(
          "created",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
        );
        const receipt = causalRevision(createResponse);
        sameSocketReceipts.push(receipt);
        if (connectionId === null) {
          throw new Error("original dataset_projection socket identity 없음");
        }
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
          connectionId,
        );
        await writePoiJournal(
          "created_same_socket_observed",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
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
        expect(requireTargetIdentity(detail, latestIdentity.targetId)).toEqual(
          latestIdentity,
        );
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
        intendedBody = upsertBody(UPDATED_NAME, POI_ID_B);
        await writePoiJournal(
          "update_put_intent",
          intendedBody,
          latestIdentity ?? {
            entityTag: null,
            lockVersion: null,
            targetId: null,
          },
          sameSocketReceipts,
        );
        const frameCursor = await datasetProjectionFrameCursor(page);
        const priorIdentity = latestIdentity;
        if (priorIdentity === null) {
          throw new Error("create identity 없이 update를 수행할 수 없습니다");
        }
        const updateResponse = await putWithCausalResponseRecovery(
          page,
          intendedBody,
          priorIdentity,
          sameSocketReceipts,
          "update",
        );
        expect(updateResponse.status).toBe(200);
        latestIdentity = requireTargetIdentity(
          updateResponse,
          priorIdentity.targetId,
        );
        if (latestIdentity.lockVersion <= priorIdentity.lockVersion) {
          throw new Error("POI target update lock version이 전진하지 않았습니다");
        }
        await writePoiJournal(
          "updated",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
        );
        const receipt = causalRevision(updateResponse);
        sameSocketReceipts.push(receipt);
        if (connectionId === null) {
          throw new Error("original dataset_projection socket identity 없음");
        }
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
          connectionId,
        );
        await writePoiJournal(
          "updated_same_socket_observed",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
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
        if (latestIdentity === null) {
          throw new Error("latest server identity is missing before DELETE");
        }
        await writePoiJournal(
          "delete_intent",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
        );
        const beforeDelete = latestIdentity;
        const deleted = await deleteTargetByApi(
          page,
          beforeDelete,
          intendedBody,
        );
        expect(deleted.status).toBe(200);
        latestIdentity = requireTargetIdentity(deleted, beforeDelete.targetId);
        if (latestIdentity.lockVersion <= beforeDelete.lockVersion) {
          throw new Error("POI target delete lock version이 전진하지 않았습니다");
        }
        const receipt = causalRevision(deleted);
        sameSocketReceipts.push(receipt);
        if (connectionId === null) {
          throw new Error("original dataset_projection socket identity 없음");
        }
        await expectCausalDatasetProjectionUpdate(
          page,
          receipt,
          frameCursor,
          connectionId,
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
        await writePoiJournal(
          "restored",
          intendedBody,
          latestIdentity,
          sameSocketReceipts,
        );
      });
    } catch (error) {
      primaryError = error;
      throw error;
    } finally {
      const cleanupErrors: unknown[] = [];
      if (mutationIntentWritten && !removed) {
        try {
          const trackedIdentity = latestIdentity as {
            entityTag: string;
            lockVersion: number;
            targetId: string;
          } | null;
          const current = await fetchTarget(page);
          if (current.status === 200) {
            assertExactIntendedTarget(
              current,
              intendedBody,
              trackedIdentity?.targetId,
            );
            const currentIdentity = requireTargetIdentity(
              current,
              trackedIdentity?.targetId,
            );
            if (
              trackedIdentity !== null &&
              (currentIdentity.entityTag !== trackedIdentity.entityTag ||
                currentIdentity.lockVersion !== trackedIdentity.lockVersion)
            ) {
              throw new Error(
                "cleanup 전 concurrent target update가 확인되어 삭제를 차단했습니다",
              );
            }
            latestIdentity = currentIdentity;
            await writePoiJournal(
              "cleanup_delete_intent",
              intendedBody,
              latestIdentity,
              sameSocketReceipts,
            );
            const deleted = await deleteTargetByApi(
              page,
              latestIdentity,
              intendedBody,
            );
            if (deleted.status !== 200) {
              throw new Error(`cleanup DELETE 실패(status=${deleted.status})`);
            }
            latestIdentity = requireTargetIdentity(
              deleted,
              latestIdentity.targetId,
            );
          } else if (current.status !== 404) {
            throw new Error(`cleanup GET 실패(status=${current.status})`);
          }
          const absent = await fetchTarget(page);
          if (absent.status !== 404 || latestIdentity === null) {
            throw new Error("cleanup 후 exact 404 복원 증거가 없습니다");
          }
          removed = true;
          await writePoiJournal(
            "restored",
            intendedBody,
            latestIdentity,
            sameSocketReceipts,
          );
        } catch (error) {
          cleanupErrors.push(error);
        }
      }
      if (liveSocketOpened) {
        await closeDatasetProjectionSocket(page).catch((error: unknown) =>
          cleanupErrors.push(error),
        );
      }
      if (cleanupErrors.length > 0) {
        throw new AggregateError(
          primaryError === undefined
            ? cleanupErrors
            : [primaryError, ...cleanupErrors],
          "C7 POI primary/deterministic cleanup 실패",
        );
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
