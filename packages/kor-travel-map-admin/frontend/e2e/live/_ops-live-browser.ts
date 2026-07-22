import { createHash } from "node:crypto";

import type {
  Page,
  Route,
  WebSocket as PlaywrightWebSocket,
} from "@playwright/test";

import {
  OPS_LIVE_EXPIRED_CLOSE_CODE,
  OPS_LIVE_PROTOCOL_PREFIX,
  OPS_LIVE_TICKET_TTL_SECONDS,
} from "../../src/lib/ops-live-contract";

const SOCKET_TIMEOUT_MS = 20_000;
const APP_RECOVERY_TIMEOUT_MS = 45_000;
const EXPIRED_SKEW_MS = 1_500;
const OPS_LIVE_PATH = "/v1/ops/live";
const OPS_LIVE_POLL_INTERVAL = "2000";
const TICKET_PATH = "/api/auth/live-ticket";
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const APP_SOCKET_OBSERVATIONS = "__c7OpsLiveSocketObservations";

export const EXPECTED_DATASETS_APP_TOPICS = [
  "dagster_runs",
  "dagster_schedules",
  "dataset_projection",
  "feature_update_requests",
  "import_jobs",
  "provider_sync",
] as const;

const tracedOpsLiveUrls = new WeakMap<Page, string>();

type LiveTicket = {
  expires_at: string;
  subprotocol: string;
};

function trackedRouteFetchHandler(
  handler: (route: Route) => Promise<void>,
): {
  routeHandler: (route: Route) => Promise<void>;
  waitForSettlement: () => Promise<void>;
} {
  let activeHandlers = 0;
  const waiters = new Set<() => void>();
  const routeHandler = async (route: Route): Promise<void> => {
    activeHandlers += 1;
    try {
      await handler(route);
    } finally {
      activeHandlers -= 1;
      if (activeHandlers === 0) {
        for (const resolve of waiters) resolve();
        waiters.clear();
      }
    }
  };
  const waitForSettlement = async (): Promise<void> => {
    if (activeHandlers === 0) return;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    try {
      await Promise.race([
        new Promise<void>((resolve) => waiters.add(resolve)),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(
            () => reject(new Error("live ticket route handler settlement timeout")),
            APP_RECOVERY_TIMEOUT_MS,
          );
        }),
      ]);
    } finally {
      if (timeout !== null) clearTimeout(timeout);
    }
  };
  return { routeHandler, waitForSettlement };
}

export type ClosedSocketProbe = {
  closeCode: number;
  dataFrames: number;
};

export type RejectedSocketProbes = {
  missing: ClosedSocketProbe;
  tampered: ClosedSocketProbe;
};

export type ObservedAppServerFrame = {
  actor: string | null;
  data: Record<string, unknown> | null;
  payloadKind: ObservedWirePayloadKind;
  pollIntervalMs: number | null;
  rawKeys: string[];
  revision: string | null;
  sentAt: string | null;
  sequence: number | null;
  topic: string | null;
  topics: string[] | null;
  ticketExpiresAt: string | null;
  type: string | null;
  version: number | null;
};

export type ObservedAppCommand = {
  payloadKind: ObservedWirePayloadKind;
  rawKeys: string[];
  topics: string[] | null;
  type: string | null;
};

export type ObservedWirePayloadKind =
  | "string-json-record"
  | "string-json-non-record"
  | "string-malformed"
  | "binary-array-buffer"
  | "binary-array-view"
  | "binary-blob"
  | "other";

export type AppSocketObservation = {
  closeCode: number | null;
  closedAt: number | null;
  dataFrames: number;
  openedAt: number;
  sentCommands: ObservedAppCommand[];
  serverFrames: ObservedAppServerFrame[];
};

export type ExpiredAppRecoveryProbe = {
  bffTicketRequests: number;
  expired: ClosedSocketProbe;
  fresh: AppSocketObservation;
};

export type HealthyLeaseRotationProbe = {
  bffTicketRequests: number;
  first: AppSocketObservation;
  firstCloseToFreshSocketMs: number;
  firstCloseToFreshTicketMs: number;
  fresh: AppSocketObservation;
};

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function requiredOrigin(rawValue: string | undefined, envName: string): string {
  if (!rawValue) {
    throw new Error(`${envName}이 필요합니다 (value redacted)`);
  }
  try {
    const parsed = new URL(rawValue);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    ) {
      throw new Error("not a public HTTPS origin");
    }
    return parsed.origin;
  } catch {
    throw new Error(`${envName}은 공개 HTTPS origin이어야 합니다 (value redacted)`);
  }
}

function expectedOriginHash(envName: string): string {
  const value = process.env[envName];
  if (!value || !SHA256_PATTERN.test(value)) {
    throw new Error(`${envName}은 lowercase SHA256이어야 합니다 (value redacted)`);
  }
  return value;
}

function assertOriginHash(origin: string, expectedEnvName: string): void {
  if (sha256(origin) !== expectedOriginHash(expectedEnvName)) {
    throw new Error(`${expectedEnvName} origin guard 불일치 (values redacted)`);
  }
}

/**
 * C7 prod read/auth spec의 fail-closed 실행 guard.
 *
 * 오류에는 env 이름만 쓰며 URL/password/hash 값은 절대 포함하지 않는다. live config의
 * config-evaluation guard에 더해 CLI override까지 반영된 실제 worker 수도 확인한다.
 */
export function assertC7ReadAuthLiveEnvironment(actualWorkers: number): void {
  const missing: string[] = [];
  if (!process.env.E2E_BASE_URL) missing.push("E2E_BASE_URL");
  if (process.env.E2E_LIVE_ALLOW_PROD !== "1") {
    missing.push("E2E_LIVE_ALLOW_PROD=1");
  }
  if (!process.env.E2E_ADMIN_PASSWORD) missing.push("E2E_ADMIN_PASSWORD");
  if (process.env.E2E_ADMIN_WRITE !== "1") {
    missing.push("E2E_ADMIN_WRITE=1");
  }
  if (process.env.E2E_C7_READ_AUTH_WRITE !== "1") {
    missing.push("E2E_C7_READ_AUTH_WRITE=1");
  }
  if (!process.env.E2E_C7_KMA_STATE_FILE) {
    missing.push("E2E_C7_KMA_STATE_FILE");
  }
  if (!process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256) {
    missing.push("E2E_C7_EXPECTED_UI_ORIGIN_SHA256");
  }
  if (!process.env.E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256) {
    missing.push("E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256");
  }
  if (actualWorkers !== 1) missing.push("actual Playwright workers=1");
  if (missing.length > 0) {
    throw new Error(
      `C7 read/auth live E2E 필수 조건이 없습니다: ${missing.join(", ")} (values redacted)`,
    );
  }

  const uiOrigin = requiredOrigin(process.env.E2E_BASE_URL, "E2E_BASE_URL");
  assertOriginHash(uiOrigin, "E2E_C7_EXPECTED_UI_ORIGIN_SHA256");
  expectedOriginHash("E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256");
}

function looksLikeOpsLiveUrl(rawUrl: string): boolean {
  try {
    const url = new URL(rawUrl);
    return url.pathname.endsWith("/ops/live");
  } catch {
    return false;
  }
}

function validateActualOpsLiveUrl(rawUrl: string): void {
  const url = new URL(rawUrl);
  const queryKeys = [...url.searchParams.keys()];
  if (
    url.protocol !== "wss:" ||
    url.username ||
    url.password ||
    url.pathname !== OPS_LIVE_PATH ||
    url.hash ||
    queryKeys.length !== 1 ||
    queryKeys[0] !== "poll_interval_ms" ||
    url.searchParams.get("poll_interval_ms") !== OPS_LIVE_POLL_INTERVAL
  ) {
    throw new Error(
      "actual ops live WebSocket URL이 exact WSS path/query 계약을 위반했습니다 (value redacted)",
    );
  }
  assertOriginHash(url.origin, "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256");
}

/** 실제 datasets 화면이 만든 exact ops-live URL만 메모리에 보관한다. */
export async function gotoDatasetsAndTraceOpsLiveUrl(page: Page): Promise<void> {
  const socketPromise = page.waitForEvent("websocket", {
    predicate: (socket) => looksLikeOpsLiveUrl(socket.url()),
    timeout: SOCKET_TIMEOUT_MS,
  });
  let rawUrl: string;
  try {
    await page.goto("/ops/datasets");
    rawUrl = (await socketPromise).url();
    validateActualOpsLiveUrl(rawUrl);
  } catch {
    void socketPromise.catch(() => undefined);
    throw new Error(
      "datasets 화면에서 expected-origin exact ops live WebSocket을 확인하지 못했습니다 (values redacted)",
    );
  }
  tracedOpsLiveUrls.set(page, rawUrl);
}

function tracedOpsLiveUrl(page: Page): string {
  const rawUrl = tracedOpsLiveUrls.get(page);
  if (!rawUrl) {
    throw new Error("actual ops live WebSocket URL tracer가 먼저 실행되지 않았습니다");
  }
  return rawUrl;
}

function parseLiveTicket(value: unknown): LiveTicket {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    typeof (value as Partial<LiveTicket>).expires_at !== "string" ||
    Number.isNaN(Date.parse((value as Partial<LiveTicket>).expires_at ?? "")) ||
    typeof (value as Partial<LiveTicket>).subprotocol !== "string" ||
    !(value as Partial<LiveTicket>).subprotocol?.startsWith(
      OPS_LIVE_PROTOCOL_PREFIX,
    )
  ) {
    throw new Error("live ticket 응답 계약 위반 (value redacted)");
  }
  return value as LiveTicket;
}

async function issueLiveTicketThroughBff(page: Page): Promise<LiveTicket> {
  try {
    const value = await page.evaluate(async (ticketPath) => {
      const response = await fetch(ticketPath, {
        method: "POST",
        headers: { Accept: "application/json" },
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(`live ticket 발급 실패 (HTTP ${response.status})`);
      }
      try {
        return (await response.json()) as unknown;
      } catch {
        throw new Error("live ticket JSON 응답 계약 위반");
      }
    }, TICKET_PATH);
    return parseLiveTicket(value);
  } catch {
    throw new Error("live ticket BFF 발급/계약 확인 실패 (values redacted)");
  }
}

/** ticket 없음과 서명 변조를 actual browser WebSocket으로 확인한다. */
export async function probeRejectedOpsLiveSockets(
  page: Page,
): Promise<RejectedSocketProbes> {
  const rawUrl = tracedOpsLiveUrl(page);
  const ticket = await issueLiveTicketThroughBff(page);
  return page.evaluate(
    async ({ protocol, socketTimeoutMs, url }) => {
      type Probe = { closeCode: number; dataFrames: number };

      const waitForSocketClose = (subprotocol?: string): Promise<Probe> =>
        new Promise((resolve, reject) => {
          let socket: WebSocket;
          try {
            socket = subprotocol
              ? new WebSocket(url, subprotocol)
              : new WebSocket(url);
          } catch {
            reject(new Error("ops live WebSocket 생성 실패 (URL redacted)"));
            return;
          }
          let dataFrames = 0;
          const timer = window.setTimeout(() => {
            socket.close(4000, "c7 auth probe timeout");
            reject(new Error("ops live auth close timeout"));
          }, socketTimeoutMs);
          socket.onmessage = () => {
            dataFrames += 1;
          };
          socket.onerror = () => {
            // 인증 거절은 error 뒤 close로 관측될 수 있다. close code가 정본이다.
          };
          socket.onclose = (event) => {
            window.clearTimeout(timer);
            resolve({ closeCode: event.code, dataFrames });
          };
        });

      const missing = await waitForSocketClose();
      const signatureStart = protocol.lastIndexOf(".") + 1;
      if (signatureStart <= 0 || signatureStart >= protocol.length) {
        throw new Error("ops live ticket signature 형식 위반");
      }
      // signature 첫 글자는 6개 유효 비트 전체를 담는다. base64url 마지막 글자의
      // unused padding bit만 바꾸는 비정규 변조를 피하고 decoded bytes를 반드시 바꾼다.
      const original = protocol[signatureStart];
      const tamperedProtocol = `${protocol.slice(0, signatureStart)}${
        original === "A" ? "B" : "A"
      }${protocol.slice(signatureStart + 1)}`;
      const tampered = await waitForSocketClose(tamperedProtocol);
      return { missing, tampered };
    },
    {
      protocol: ticket.subprotocol,
      socketTimeoutMs: SOCKET_TIMEOUT_MS,
      url: rawUrl,
    },
  );
}

export async function installAppSocketObserver(page: Page): Promise<void> {
  await page.addInitScript((observationKey) => {
    type Frame = {
      actor: string | null;
      data: Record<string, unknown> | null;
      payloadKind: ObservedWirePayloadKind;
      pollIntervalMs: number | null;
      rawKeys: string[];
      revision: string | null;
      sentAt: string | null;
      sequence: number | null;
      topic: string | null;
      topics: string[] | null;
      ticketExpiresAt: string | null;
      type: string | null;
      version: number | null;
    };
    type Command = {
      payloadKind: ObservedWirePayloadKind;
      rawKeys: string[];
      topics: string[] | null;
      type: string | null;
    };
    type ObservedWirePayloadKind =
      | "string-json-record"
      | "string-json-non-record"
      | "string-malformed"
      | "binary-array-buffer"
      | "binary-array-view"
      | "binary-blob"
      | "other";
    type Observation = {
      closeCode: number | null;
      closedAt: number | null;
      dataFrames: number;
      openedAt: number;
      sentCommands: Command[];
      serverFrames: Frame[];
    };
    type ObservedWindow = Window & Record<string, Observation[]>;

    const observedWindow = window as unknown as ObservedWindow;
    const observations: Observation[] = [];
    observedWindow[observationKey] = observations;
    const NativeWebSocket = window.WebSocket;

    function asRecord(value: unknown): Record<string, unknown> | null {
      return typeof value === "object" && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
    }

    function stringArray(value: unknown): string[] | null {
      return Array.isArray(value) &&
        value.every((item) => typeof item === "string")
        ? (value as string[])
        : null;
    }

    function inspectWirePayload(raw: unknown): {
      kind: ObservedWirePayloadKind;
      record: Record<string, unknown> | null;
    } {
      if (typeof raw !== "string") {
        if (raw instanceof Blob) return { kind: "binary-blob", record: null };
        if (raw instanceof ArrayBuffer) {
          return { kind: "binary-array-buffer", record: null };
        }
        if (ArrayBuffer.isView(raw)) {
          return { kind: "binary-array-view", record: null };
        }
        return { kind: "other", record: null };
      }
      try {
        const parsed = JSON.parse(raw) as unknown;
        const record = asRecord(parsed);
        return {
          kind: record ? "string-json-record" : "string-json-non-record",
          record,
        };
      } catch {
        return { kind: "string-malformed", record: null };
      }
    }

    class ObservedWebSocket extends NativeWebSocket {
      private readonly c7Observation: Observation | null;

      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols ?? []);
        let observe = false;
        try {
          observe = new URL(String(url)).pathname.endsWith("/ops/live");
        } catch {
          observe = false;
        }
        this.c7Observation = observe
          ? {
              closeCode: null,
              closedAt: null,
              dataFrames: 0,
              openedAt: Date.now(),
              sentCommands: [],
              serverFrames: [],
            }
          : null;
        if (!this.c7Observation) return;
        observations.push(this.c7Observation);
        this.addEventListener("message", (event) => {
          const observation = this.c7Observation;
          if (!observation) return;
          observation.dataFrames += 1;
          const inspected = inspectWirePayload(event.data);
          const parsed = inspected.record;
          observation.serverFrames.push({
            actor: typeof parsed?.actor === "string" ? parsed.actor : null,
            data: asRecord(parsed?.data),
            payloadKind: inspected.kind,
            pollIntervalMs:
              typeof parsed?.poll_interval_ms === "number"
                ? parsed.poll_interval_ms
                : null,
            rawKeys: parsed ? Object.keys(parsed).sort() : [],
            revision:
              typeof parsed?.revision === "string" ? parsed.revision : null,
            sentAt: typeof parsed?.sent_at === "string" ? parsed.sent_at : null,
            sequence:
              typeof parsed?.sequence === "number" ? parsed.sequence : null,
            topic: typeof parsed?.topic === "string" ? parsed.topic : null,
            topics: stringArray(parsed?.topics),
            ticketExpiresAt:
              typeof parsed?.ticket_expires_at === "string"
                ? parsed.ticket_expires_at
                : null,
            type: typeof parsed?.type === "string" ? parsed.type : null,
            version:
              typeof parsed?.version === "number" ? parsed.version : null,
          });
        });
        this.addEventListener("close", (event) => {
          if (this.c7Observation) {
            this.c7Observation.closeCode = event.code;
            this.c7Observation.closedAt = Date.now();
          }
        });
      }

      override send(
        data: string | ArrayBufferLike | Blob | ArrayBufferView,
      ): void {
        const inspected = inspectWirePayload(data);
        const parsed = inspected.record;
        if (this.c7Observation) {
          this.c7Observation.sentCommands.push({
            payloadKind: inspected.kind,
            rawKeys: parsed ? Object.keys(parsed).sort() : [],
            topics: stringArray(parsed?.topics),
            type: typeof parsed?.type === "string" ? parsed.type : null,
          });
        }
        super.send(data);
      }
    }

    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      value: ObservedWebSocket,
      writable: true,
    });
  }, APP_SOCKET_OBSERVATIONS);
}

function appSocketObservationListener(errors: string[]) {
  return (socket: PlaywrightWebSocket): void => {
    if (!looksLikeOpsLiveUrl(socket.url())) return;
    try {
      validateActualOpsLiveUrl(socket.url());
    } catch {
      errors.push("actual app WebSocket URL guard 실패 (values redacted)");
    }
  };
}

export async function observedAppSockets(
  page: Page,
): Promise<AppSocketObservation[]> {
  try {
    return await page.evaluate((observationKey) => {
      const observations = (
        window as unknown as Window &
          Record<string, AppSocketObservation[] | undefined>
      )[observationKey];
      return observations ? structuredClone(observations) : [];
    }, APP_SOCKET_OBSERVATIONS);
  } catch {
    throw new Error("actual app WebSocket 관측값을 읽지 못했습니다 (values redacted)");
  }
}

export async function waitForObservedAppSocketData(
  page: Page,
  socketIndex: number,
): Promise<void> {
  await page.waitForFunction(
    ({ observationKey, socketIndex }) => {
      type Observation = { serverFrames: Array<{ topic: string | null }> };
      const observations = (
        window as unknown as Window & Record<string, Observation[] | undefined>
      )[observationKey];
      return Boolean(
        observations?.[socketIndex]?.serverFrames.some(
          (frame) => frame.topic !== null,
        ),
      );
    },
    { observationKey: APP_SOCKET_OBSERVATIONS, socketIndex },
    { timeout: APP_RECOVERY_TIMEOUT_MS },
  );
}

export async function waitForObservedAppSocketClose(
  page: Page,
  socketIndex: number,
  closeCode: number,
  timeout = APP_RECOVERY_TIMEOUT_MS,
): Promise<void> {
  await page.waitForFunction(
    ({ closeCode, observationKey, socketIndex }) => {
      type Observation = { closeCode: number | null };
      const observations = (
        window as unknown as Window & Record<string, Observation[] | undefined>
      )[observationKey];
      return observations?.[socketIndex]?.closeCode === closeCode;
    },
    { closeCode, observationKey: APP_SOCKET_OBSERVATIONS, socketIndex },
    { timeout },
  );
}

/**
 * 실제 app socket이 정상 data frame을 처리한 뒤 서버의 자연 lease 만료(4408)를
 * 받고, retry backoff 없이 새 BFF ticket/socket으로 rotation하는 경로를 관측한다.
 * ticket/subprotocol/URL 원문은 반환하거나 오류에 포함하지 않는다.
 */
export async function exerciseHealthyLeaseRotationThroughDatasetsHook(
  page: Page,
): Promise<HealthyLeaseRotationProbe> {
  await installAppSocketObserver(page);
  const ticketRequestedAt: number[] = [];
  const handleRoute = async (route: Route): Promise<void> => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    ticketRequestedAt.push(Date.now());
    // 실제 브라우저 요청을 그대로 전달한다. Playwright route.fetch()는 브라우저가 설정한
    // Sec-Fetch-Site를 싣지 않아 BFF origin guard가 403으로 거절한다. route.continue()는
    // Sec-Fetch-Site·Origin·Cookie를 모두 보존하므로 실제 BFF가 fresh rotation ticket을
    // 발급한다. rotation 뒤 socket data 도착을 end-to-end waitForFunction이 검증하므로
    // handler에서 ticket을 reshape/재검증할 필요가 없다.
    await route.continue();
  };
  const { routeHandler, waitForSettlement } =
    trackedRouteFetchHandler(handleRoute);
  const socketUrlErrors: string[] = [];
  const socketListener = appSocketObservationListener(socketUrlErrors);
  await page.route(`**${TICKET_PATH}`, routeHandler);
  page.on("websocket", socketListener);
  try {
    try {
      await page.goto("/ops/datasets");
    } catch {
      throw new Error("natural lease datasets 화면 로드 실패 (values redacted)");
    }
    await page.waitForFunction(
      ({ closeCode, observationKey }) => {
        type Observation = {
          closeCode: number | null;
          serverFrames: Array<{
            topic: string | null;
            type: string | null;
          }>;
        };
        const observations = (
          window as unknown as Window & Record<string, Observation[] | undefined>
        )[observationKey];
        const first = observations?.[0];
        const fresh = observations?.[1];
        return Boolean(
          first?.serverFrames.some(
            (frame) =>
              frame.topic === "dataset_projection" &&
              (frame.type === "snapshot" || frame.type === "update"),
          ) &&
            first.closeCode === closeCode &&
            fresh?.serverFrames.some(
              (frame) =>
                frame.topic === "dataset_projection" &&
                (frame.type === "snapshot" || frame.type === "update"),
            ),
        );
      },
      {
        closeCode: OPS_LIVE_EXPIRED_CLOSE_CODE,
        observationKey: APP_SOCKET_OBSERVATIONS,
      },
      {
        timeout:
          OPS_LIVE_TICKET_TTL_SECONDS * 1_000 + APP_RECOVERY_TIMEOUT_MS,
      },
    );
    if (socketUrlErrors.length > 0) {
      throw new Error(socketUrlErrors[0]);
    }
    const observations = await observedAppSockets(page);
    const first = observations[0];
    const fresh = observations[1];
    const freshTicketAt = ticketRequestedAt[1];
    if (
      !first ||
      !fresh ||
      first.closedAt === null ||
      freshTicketAt === undefined
    ) {
      throw new Error("natural lease rotation 관측이 불완전합니다");
    }
    return {
      bffTicketRequests: ticketRequestedAt.length,
      first,
      firstCloseToFreshSocketMs: fresh.openedAt - first.closedAt,
      firstCloseToFreshTicketMs: freshTicketAt - first.closedAt,
      fresh,
    };
  } finally {
    page.off("websocket", socketListener);
    await waitForSettlement();
    await page.unroute(`**${TICKET_PATH}`, routeHandler);
  }
}

/**
 * 첫 BFF 응답에 실제로 서명됐지만 만료된 protocol과 미래 ``expires_at`` 메타를
 * 주입한다. DatasetsClient의 실제 hook이 4408을 받은 뒤 두 번째 BFF ticket으로
 * 재연결해 exact replace/subscribed와 dataset_projection data frame을 처리해야 한다.
 */
export async function exerciseExpiredTicketRecoveryThroughDatasetsHook(
  page: Page,
): Promise<ExpiredAppRecoveryProbe> {
  try {
    await page.goto("/");
  } catch {
    throw new Error("live ticket 준비용 same-origin 화면 로드 실패 (value redacted)");
  }
  const expiredTicket = await issueLiveTicketThroughBff(page);
  const waitMs =
    Date.parse(expiredTicket.expires_at) - Date.now() + EXPIRED_SKEW_MS;
  if (
    waitMs < 0 ||
    waitMs > OPS_LIVE_TICKET_TTL_SECONDS * 1_000 + EXPIRED_SKEW_MS
  ) {
    throw new Error("live ticket TTL 범위 위반 (timestamps redacted)");
  }
  await page.waitForTimeout(waitMs);
  await installAppSocketObserver(page);

  let bffTicketRequests = 0;
  const handleRoute = async (route: Route): Promise<void> => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    bffTicketRequests += 1;
    if (bffTicketRequests === 1) {
      await route.fulfill({
        body: JSON.stringify({
          expires_at: new Date(
            Date.now() + OPS_LIVE_TICKET_TTL_SECONDS * 1_000,
          ).toISOString(),
          subprotocol: expiredTicket.subprotocol,
        }),
        contentType: "application/json",
        headers: { "Cache-Control": "no-store, max-age=0" },
        status: 200,
      });
      return;
    }
    // 재연결 leg: 실제 브라우저 요청을 그대로 전달한다. Playwright route.fetch()는 브라우저가
    // 설정한 Sec-Fetch-Site를 싣지 않아 BFF origin guard가 403으로 거절한다. route.continue()는
    // Sec-Fetch-Site·Origin·Cookie를 모두 보존하므로 실제 BFF가 genuine fresh ticket을 발급하고,
    // 클라가 socket[1]을 열어 hello->replace->subscribed->dataset_projection까지 복구한다.
    // 복구 수렴은 아래 end-to-end waitForFunction이 검증한다(handler reshape/재검증 불필요).
    await route.continue();
  };
  const { routeHandler, waitForSettlement } =
    trackedRouteFetchHandler(handleRoute);

  const socketUrlErrors: string[] = [];
  const socketListener = appSocketObservationListener(socketUrlErrors);
  await page.route(`**${TICKET_PATH}`, routeHandler);
  page.on("websocket", socketListener);
  try {
    try {
      await page.goto("/ops/datasets");
    } catch {
      throw new Error(
        "datasets app hook 복구 화면을 열지 못했습니다 (values redacted)",
      );
    }
    await page.waitForFunction(
      ({ expiredCloseCode, observationKey, topic }) => {
        type Observation = {
          closeCode: number | null;
          dataFrames: number;
          serverFrames: Array<{ topic: string | null; type: string | null }>;
        };
        const observations = (
          window as unknown as Window & Record<string, Observation[]>
        )[observationKey];
        const expired = observations?.[0];
        const fresh = observations?.[1];
        return Boolean(
          expired?.closeCode === expiredCloseCode &&
            expired.dataFrames === 0 &&
            fresh?.serverFrames.some(
              (frame) =>
                frame.topic === topic &&
                (frame.type === "snapshot" || frame.type === "update"),
            ),
        );
      },
      {
        expiredCloseCode: OPS_LIVE_EXPIRED_CLOSE_CODE,
        observationKey: APP_SOCKET_OBSERVATIONS,
        topic: "dataset_projection",
      },
      { timeout: APP_RECOVERY_TIMEOUT_MS },
    );
    if (socketUrlErrors.length > 0) {
      throw new Error(socketUrlErrors[0]);
    }
    const observations = await page.evaluate((observationKey) => {
      return (
        window as unknown as Window & Record<string, AppSocketObservation[]>
      )[observationKey].slice(0, 2);
    }, APP_SOCKET_OBSERVATIONS);
    const expired = observations[0];
    const fresh = observations[1];
    if (!expired || !fresh) {
      throw new Error("app hook WebSocket 재연결 관측이 불완전합니다");
    }
    return {
      bffTicketRequests,
      expired: {
        closeCode: expired.closeCode ?? 0,
        dataFrames: expired.dataFrames,
      },
      fresh,
    };
  } finally {
    page.off("websocket", socketListener);
    await waitForSettlement();
    await page.unroute(`**${TICKET_PATH}`, routeHandler);
  }
}
