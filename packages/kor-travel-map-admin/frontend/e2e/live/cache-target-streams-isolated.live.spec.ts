import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type Response,
} from "@playwright/test";

import { LIVE_STORAGE_STATE, removeStorageState } from "../_auth-state";
import { SESSION_COOKIE_NAME } from "../../src/lib/auth";

type CacheTargetStreamStatus = {
  blocked_event_id: string | null;
  consumer_enabled: boolean;
  control_version: number;
  dead_count: number;
  delivered_count: number;
  superseded_count: number;
  external_system: string;
  last_snapshot: {
    count: number;
    created_at: string;
    high_watermark_cursor: string;
    merkle_root: string;
    snapshot_id: string;
  } | null;
  leased_count: number;
  pending_count: number;
  restore_epoch: number;
  retry_count: number;
  state: string;
  updated_at: string;
};

type CacheTargetStreamStatusResponse = {
  data: { items: CacheTargetStreamStatus[] };
};

type CacheTargetDeadLetter = {
  delivery_version: number;
  entity_tag: string;
  event_id: string;
  event_scope: string;
  event_type: string;
  external_system: string | null;
  payload_fingerprint: string;
  relay_order: number;
  target_key: string | null;
};

type CacheTargetDeadLetterListResponse = {
  data: { items: CacheTargetDeadLetter[] };
};

type CacheTargetDeadLetterDetailResponse = {
  data: CacheTargetDeadLetter;
};

type CacheTargetOperationResponse = {
  data: {
    entity_tag?: string | null;
    operation_id: string;
    snapshot_id?: string | null;
    status: string;
    status_url: string | null;
    stream_entity_tag?: string | null;
  };
};

type BrowserJsonResponse<T> = {
  body: T | null;
  status: number;
};

type EvidenceConfig = {
  baseURL: string;
  deadEventId: string;
  expectedCount: number;
  expectedMerkleRoot: string;
  expectedRestoreEpoch: number;
  expectedSnapshotId: string;
  externalSystem: string;
  pollTimeoutMs: number;
};

const STREAMS_PATH = "/v1/ops/cache-target-streams";
const DEAD_LIST_PATH = "/v1/ops/cache-target-event-dead-letters";
const RECOVERY_WRITE_ENV = "E2E_CACHE_TARGET_STREAM_RECOVERY_WRITE";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MERKLE_ROOT_PATTERN = /^[0-9a-f]{64}$/;
const SERVICE_TOKEN_MARKERS = [
  /ServiceToken/i,
  /X-Kor-Travel-Map-Service-Token/i,
  /service[_-]?token/i,
  /cache-target-token/i,
];
const FORBIDDEN_BROWSER_HEADER_NAMES = new Set([
  "authorization",
  "x-kor-travel-map-ops-token",
  "x-kor-travel-map-service-token",
]);

const configResult = readEvidenceConfig();

test.describe("/ops/cache-target-streams isolated live recovery", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(configResult.skipReason !== null, configResult.skipReason ?? "");

  test.afterAll(() => {
    removeStorageState(LIVE_STORAGE_STATE);
  });

  test.afterEach(async ({ context, page }) => {
    await clearBrowserState(page, context);
  });

  test("isolated BFF-only stream recovery reaches ready checksum state", async ({
    context,
    page,
  }, testInfo) => {
    const config = requireEvidenceConfig(configResult);
    expect(testInfo.config.workers).toBe(1);
    expect(testInfo.project.retries).toBe(0);

    const observed = installBrowserBoundaryAssertions(page);

    await loginWithRealUiPassword(page, context);
    await assertNoServiceTokenInBrowserState(page, context);

    await page.goto("/ops/cache-target-streams");
    await expect(
      page.getByRole("heading", { level: 1, name: "캐시 전파 스트림" }),
    ).toBeVisible();

    const initialStreams = await fetchBffJson<CacheTargetStreamStatusResponse>(
      page,
      STREAMS_PATH,
    );
    expect(initialStreams.status).toBe(200);
    const initialStream = requireStream(initialStreams.body, config);
    expect(initialStream.state).toBe("blocked");
    expect(initialStream.blocked_event_id).toBe(config.deadEventId);
    expect(backlogCount(initialStream)).toBeGreaterThan(0);
    expect(initialStream.dead_count).toBeGreaterThan(0);

    const deadList = await fetchBffJson<CacheTargetDeadLetterListResponse>(
      page,
      DEAD_LIST_PATH,
    );
    expect(deadList.status).toBe(200);
    expect(
      deadList.body?.data.items.some(
        (item) => item.event_id === config.deadEventId,
      ),
    ).toBe(true);
    const deadDetail = await fetchBffJson<CacheTargetDeadLetterDetailResponse>(
      page,
      `${DEAD_LIST_PATH}/${config.deadEventId}`,
    );
    expect(deadDetail.status).toBe(200);
    const deadLetter = requireDeadLetter(deadDetail.body, config);

    await assertInitialUiState(page, initialStream, deadLetter, config);

    const replayResponsePromise = waitForBffResponse(
      page,
      "POST",
      `/v1/admin/cache-target-event-dead-letters/${config.deadEventId}/replays`,
    );
    const replayReason = "isolated live ETag replay recovery";
    await page.getByLabel("사유").first().fill(replayReason);
    await page.getByRole("button", { name: "replay 요청" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "replay 요청" })
      .click();
    const replayResponse = await replayResponsePromise;
    await assertOperationReceipt(replayResponse, {
      expectedBody: { reason: replayReason },
      expectedIfMatch: deadLetter.entity_tag,
      expectedStatus: 202,
    });
    await expect(page.getByRole("status")).toContainText("복구 명령 접수");

    const reconciliationResponsePromise = waitForBffResponse(
      page,
      "POST",
      "/v1/admin/cache-target-reconciliations",
    );
    const reconciliationReason =
      "isolated live Merkle reconciliation verification";
    await page.getByLabel("사유").nth(1).fill(reconciliationReason);
    await page.getByRole("button", { name: "reconciliation 요청" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "reconciliation 요청" })
      .click();
    const reconciliationResponse = await reconciliationResponsePromise;
    const reconciliationReceipt = await assertOperationReceipt(
      reconciliationResponse,
      {
        expectedBody: {
          external_system: config.externalSystem,
          reason: reconciliationReason,
        },
        expectedStatus: 202,
      },
    );
    const reconciliationSnapshotId = reconciliationReceipt.data.snapshot_id;
    if (typeof reconciliationSnapshotId !== "string") {
      throw new Error("reconciliation receipt snapshot_id가 없습니다.");
    }
    expect(reconciliationSnapshotId).toMatch(UUID_PATTERN);
    expect(reconciliationSnapshotId).not.toBe(config.expectedSnapshotId);
    await expect(page.getByRole("status")).toContainText("복구 명령 접수");

    await expect
      .poll(() => finalReadiness(page, config, reconciliationSnapshotId), {
        intervals: [1_000, 2_000, 5_000],
        timeout: config.pollTimeoutMs,
      })
      .toEqual({
        backlog: 0,
        blockedEventId: null,
        count: config.expectedCount,
        dead: 0,
        merkleRoot: config.expectedMerkleRoot,
        snapshotId: reconciliationSnapshotId,
        state: "ready",
      });

    await assertNoServiceTokenInBrowserState(page, context);
    expect(observed.bffApiPaths.length).toBeGreaterThan(0);
    expect(observed.violations).toEqual([]);
  });
});

function readEvidenceConfig():
  | { config: EvidenceConfig; skipReason: null }
  | { config: null; skipReason: string } {
  const explicitlyRequested = [
    "E2E_ISOLATED_LIVE_EVIDENCE",
    "E2E_ISOLATED_LIVE_DOCKER_NETWORK",
    RECOVERY_WRITE_ENV,
    "E2E_CACHE_TARGET_STREAM_EXTERNAL_SYSTEM",
    "E2E_CACHE_TARGET_STREAM_EXPECTED_SNAPSHOT_ID",
    "E2E_CACHE_TARGET_STREAM_DEAD_EVENT_ID",
    "E2E_CACHE_TARGET_STREAM_EXPECTED_COUNT",
    "E2E_CACHE_TARGET_STREAM_EXPECTED_RESTORE_EPOCH",
    "E2E_CACHE_TARGET_STREAM_EXPECTED_MERKLE_ROOT",
  ].some((name) => process.env[name] !== undefined);
  const missing: string[] = [];
  const requireExactOne = (name: string) => {
    if (process.env[name] !== "1") missing.push(`${name}=1`);
  };
  requireExactOne("E2E_ISOLATED_LIVE_EVIDENCE");
  requireExactOne("E2E_ISOLATED_LIVE_DOCKER_NETWORK");
  requireExactOne(RECOVERY_WRITE_ENV);
  requireNonEmpty("E2E_ADMIN_PASSWORD", missing);

  const baseURL = requireNonEmpty("E2E_BASE_URL", missing);
  const externalSystem = requireNonEmpty(
    "E2E_CACHE_TARGET_STREAM_EXTERNAL_SYSTEM",
    missing,
  );
  const expectedSnapshotId = requireNonEmpty(
    "E2E_CACHE_TARGET_STREAM_EXPECTED_SNAPSHOT_ID",
    missing,
  );
  const deadEventId = requireNonEmpty(
    "E2E_CACHE_TARGET_STREAM_DEAD_EVENT_ID",
    missing,
  );
  const expectedCount = requireInteger(
    "E2E_CACHE_TARGET_STREAM_EXPECTED_COUNT",
    missing,
  );
  const expectedRestoreEpoch = requireInteger(
    "E2E_CACHE_TARGET_STREAM_EXPECTED_RESTORE_EPOCH",
    missing,
  );
  const expectedMerkleRoot = requirePattern(
    "E2E_CACHE_TARGET_STREAM_EXPECTED_MERKLE_ROOT",
    MERKLE_ROOT_PATTERN,
    missing,
  );
  const pollTimeoutMs =
    optionalInteger("E2E_CACHE_TARGET_STREAM_POLL_TIMEOUT_MS", missing) ??
    300_000;

  if (baseURL !== null && !isExplicitLoopbackOrPrivateCandidate(baseURL)) {
    missing.push("explicit-private E2E_BASE_URL");
  }
  if (deadEventId !== null && !UUID_PATTERN.test(deadEventId)) {
    missing.push("valid E2E_CACHE_TARGET_STREAM_DEAD_EVENT_ID");
  }
  if (expectedCount !== null && expectedCount < 0) {
    missing.push("non-negative E2E_CACHE_TARGET_STREAM_EXPECTED_COUNT");
  }
  if (expectedRestoreEpoch !== null && expectedRestoreEpoch < 1) {
    missing.push("positive E2E_CACHE_TARGET_STREAM_EXPECTED_RESTORE_EPOCH");
  }

  if (
    missing.length > 0 ||
    baseURL === null ||
    externalSystem === null ||
    expectedSnapshotId === null ||
    deadEventId === null ||
    expectedCount === null ||
    expectedRestoreEpoch === null ||
    expectedMerkleRoot === null
  ) {
    const reason = `isolated cache-target stream live evidence env required: ${missing.join(
      ", ",
    )}`;
    if (explicitlyRequested) {
      throw new Error(reason);
    }
    return {
      config: null,
      skipReason: reason,
    };
  }

  return {
    config: {
      baseURL,
      deadEventId,
      expectedCount,
      expectedMerkleRoot,
      expectedRestoreEpoch,
      expectedSnapshotId,
      externalSystem,
      pollTimeoutMs,
    },
    skipReason: null,
  };
}

function requireEvidenceConfig(
  result: ReturnType<typeof readEvidenceConfig>,
): EvidenceConfig {
  if (result.config === null) {
    throw new Error("isolated live evidence config unavailable");
  }
  return result.config;
}

function requireNonEmpty(name: string, missing: string[]): string | null {
  const value = process.env[name]?.trim();
  if (!value) {
    missing.push(name);
    return null;
  }
  return value;
}

function requireInteger(name: string, missing: string[]): number | null {
  const value = requireNonEmpty(name, missing);
  if (value === null) return null;
  if (!/^[0-9]+$/.test(value)) {
    missing.push(`integer ${name}`);
    return null;
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    missing.push(`safe integer ${name}`);
    return null;
  }
  return parsed;
}

function optionalInteger(name: string, missing: string[]): number | null {
  const value = process.env[name]?.trim();
  if (!value) return null;
  const parsed = Number(value);
  if (!/^[0-9]+$/.test(value) || !Number.isSafeInteger(parsed) || parsed < 1) {
    missing.push(`positive integer ${name}`);
    return null;
  }
  return parsed;
}

function requirePattern(
  name: string,
  pattern: RegExp,
  missing: string[],
): string | null {
  const value = requireNonEmpty(name, missing);
  if (value === null) return null;
  if (!pattern.test(value)) {
    missing.push(`valid ${name}`);
    return null;
  }
  return value;
}

function isExplicitLoopbackOrPrivateCandidate(raw: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return false;
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    return false;
  }
  const host = parsed.hostname.toLowerCase();
  return (
    host === "candidate-ui" ||
    host === "localhost" ||
    host === "0.0.0.0" ||
    host === "127.0.0.1" ||
    host === "::1" ||
    host.endsWith(".localhost") ||
    isPrivateIpv4(host)
  );
}

function isPrivateIpv4(host: string): boolean {
  const parts = host.split(".");
  if (parts.length !== 4) return false;
  const octets = parts.map((part) => Number(part));
  if (
    octets.some(
      (octet, index) =>
        !/^[0-9]+$/.test(parts[index]) ||
        !Number.isInteger(octet) ||
        octet < 0 ||
        octet > 255,
    )
  ) {
    return false;
  }
  return (
    octets[0] === 10 ||
    octets[0] === 127 ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 169 && octets[1] === 254) ||
    (octets[0] === 192 && octets[1] === 168)
  );
}

async function loginWithRealUiPassword(
  page: Page,
  context: BrowserContext,
): Promise<void> {
  const password = process.env.E2E_ADMIN_PASSWORD;
  const username = process.env.E2E_ADMIN_USERNAME ?? "admin";
  expect(password).toEqual(expect.any(String));
  await page.goto("/login");
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  const browserStatus = await page.evaluate(
    async ({ password, username }) => {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ next: "/", password, username }),
      });
      return response.status;
    },
    { password: password as string, username },
  );
  const response = await responsePromise;
  expect(browserStatus).toBe(200);
  expect(response.status()).toBe(200);
  const setCookieHeaders = await response.headerValues("set-cookie");
  expect(
    setCookieHeaders.some((header) => header.includes(SESSION_COOKIE_NAME)),
  ).toBe(true);
  const cookies = await context.cookies();
  expect(
    cookies.some(
      (cookie) =>
        cookie.name === SESSION_COOKIE_NAME && cookie.value.length > 0,
    ),
  ).toBe(true);
}

function installBrowserBoundaryAssertions(page: Page): {
  bffApiPaths: string[];
  violations: string[];
} {
  const observed = { bffApiPaths: [] as string[], violations: [] as string[] };
  page.on("request", (request) => {
    const path = decodedPath(request.url());
    assertRequestDoesNotCarryServiceToken(
      request.headers(),
      observed.violations,
    );
    if (path.startsWith("/v1/")) {
      observed.violations.push(`direct backend API call: ${path}`);
      return;
    }
    if (!path.startsWith("/api/proxy/")) {
      return;
    }
    const apiPath = path.slice("/api/proxy".length);
    observed.bffApiPaths.push(apiPath);
    if (apiPath.startsWith("/v1/service/")) {
      observed.violations.push(`service API via browser BFF: ${apiPath}`);
      return;
    }
    if (!apiPath.startsWith("/v1/ops/") && !apiPath.startsWith("/v1/admin/")) {
      observed.violations.push(`non-ops-admin BFF API call: ${apiPath}`);
    }
  });
  return observed;
}

function assertRequestDoesNotCarryServiceToken(
  headers: Record<string, string>,
  violations: string[],
): void {
  for (const [name, value] of Object.entries(headers)) {
    const lowerName = name.toLowerCase();
    if (
      FORBIDDEN_BROWSER_HEADER_NAMES.has(lowerName) ||
      valueHasServiceTokenMarker(value)
    ) {
      violations.push(`forbidden browser credential header: ${lowerName}`);
    }
  }
}

async function assertNoServiceTokenInBrowserState(
  page: Page,
  context: BrowserContext,
): Promise<void> {
  const storageFindings = await page.evaluate(
    (markers) => {
      const expressions = markers.map((source) => new RegExp(source, "i"));
      const findings: string[] = [];
      const inspect = (scope: Storage, scopeName: string) => {
        for (let index = 0; index < scope.length; index += 1) {
          const key = scope.key(index) ?? "";
          const value = scope.getItem(key) ?? "";
          if (
            expressions.some(
              (expression) => expression.test(key) || expression.test(value),
            )
          ) {
            findings.push(scopeName);
          }
        }
      };
      inspect(window.localStorage, "localStorage");
      inspect(window.sessionStorage, "sessionStorage");
      return findings;
    },
    SERVICE_TOKEN_MARKERS.map((marker) => marker.source),
  );
  expect(storageFindings).toEqual([]);

  const cookies = await context.cookies();
  const cookieFindings = cookies
    .filter(
      (cookie) =>
        valueHasServiceTokenMarker(cookie.name) ||
        valueHasServiceTokenMarker(cookie.value),
    )
    .map((cookie) => cookie.name);
  expect(cookieFindings).toEqual([]);
}

function valueHasServiceTokenMarker(value: string): boolean {
  return SERVICE_TOKEN_MARKERS.some((marker) => marker.test(value));
}

async function fetchBffJson<T>(
  page: Page,
  path: string,
): Promise<BrowserJsonResponse<T>> {
  return page.evaluate(async (path) => {
    const response = await fetch(`/api/proxy${path}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { body: body as T | null, status: response.status };
  }, path);
}

function requireStream(
  response: CacheTargetStreamStatusResponse | null,
  config: EvidenceConfig,
): CacheTargetStreamStatus {
  const stream = response?.data.items.find(
    (item) => item.external_system === config.externalSystem,
  );
  if (!stream) {
    throw new Error("expected cache target stream evidence fixture is missing");
  }
  expect(stream.restore_epoch).toBe(config.expectedRestoreEpoch);
  expect(stream.last_snapshot?.snapshot_id).toBe(config.expectedSnapshotId);
  expect(stream.last_snapshot?.count).toBe(config.expectedCount);
  expect(stream.last_snapshot?.merkle_root).toBe(config.expectedMerkleRoot);
  return stream;
}

function requireDeadLetter(
  response: CacheTargetDeadLetterDetailResponse | null,
  config: EvidenceConfig,
): CacheTargetDeadLetter {
  const item = response?.data;
  if (!item || item.event_id !== config.deadEventId) {
    throw new Error(
      "expected cache target dead-letter evidence fixture is missing",
    );
  }
  expect(item.external_system).toBe(config.externalSystem);
  expect(item.entity_tag).toBe(
    `"${config.deadEventId}:${item.delivery_version}"`,
  );
  return item;
}

async function assertInitialUiState(
  page: Page,
  stream: CacheTargetStreamStatus,
  deadLetter: CacheTargetDeadLetter,
  config: EvidenceConfig,
): Promise<void> {
  const streamRow = page.getByRole("row", {
    name: new RegExp(escapeRegExp(config.externalSystem)),
  });
  await expect(
    page.getByRole("table", { name: "cache target source stream 상태" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "cache target dead letter" }),
  ).toBeVisible();
  await expect(streamRow).toContainText(`epoch ${config.expectedRestoreEpoch}`);
  await expect(streamRow).toContainText(relayBacklogLabel(stream));
  await expect(streamRow).toContainText(formatCount(stream.dead_count));
  await expect(
    page.getByText(config.expectedMerkleRoot, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(`${formatCount(config.expectedCount)} rows`),
  ).toBeVisible();
  await expect(
    page.getByText(config.expectedSnapshotId, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(stream.last_snapshot?.high_watermark_cursor ?? "", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(config.deadEventId, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(deadLetter.entity_tag, { exact: true }),
  ).toBeVisible();
}

async function assertOperationReceipt(
  response: Response,
  options: {
    expectedBody: Record<string, string>;
    expectedIfMatch?: string;
    expectedStatus: number;
  },
): Promise<CacheTargetOperationResponse> {
  expect(response.status()).toBe(options.expectedStatus);
  const requestHeaders = response.request().headers();
  expect(requestHeaders["idempotency-key"]).toMatch(UUID_PATTERN);
  if (options.expectedIfMatch !== undefined) {
    expect(requestHeaders["if-match"]).toBe(options.expectedIfMatch);
  }
  expect(response.request().postDataJSON()).toEqual(options.expectedBody);
  const receipt = (await response.json()) as CacheTargetOperationResponse;
  expect(receipt.data.operation_id).toEqual(expect.any(String));
  expect(receipt.data.status).toEqual(expect.any(String));
  expect(receipt.data.status_url).toMatch(
    /^\/v1\/ops\/cache-target-operations\//,
  );
  expect(response.headers()["retry-after"]).toMatch(/^[0-9]+$/);
  return receipt;
}

function waitForBffResponse(
  page: Page,
  method: string,
  apiPath: string,
): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      response.request().method() === method &&
      apiPathFromBffUrl(response.url()) === apiPath,
  );
}

async function finalReadiness(
  page: Page,
  config: EvidenceConfig,
  expectedSnapshotId: string,
): Promise<{
  backlog: number;
  blockedEventId: string | null;
  count: number | null;
  dead: number;
  merkleRoot: string | null;
  snapshotId: string | null;
  state: string;
}> {
  const response = await fetchBffJson<CacheTargetStreamStatusResponse>(
    page,
    STREAMS_PATH,
  );
  if (response.status !== 200 || response.body === null) {
    return {
      backlog: -1,
      blockedEventId: "unavailable",
      count: null,
      dead: -1,
      merkleRoot: null,
      snapshotId: null,
      state: "unavailable",
    };
  }
  const stream =
    response.body.data.items.find(
      (item) => item.external_system === config.externalSystem,
    ) ?? null;
  if (stream === null) {
    return {
      backlog: -1,
      blockedEventId: "missing",
      count: null,
      dead: -1,
      merkleRoot: null,
      snapshotId: null,
      state: "missing",
    };
  }
  const snapshotId = stream.last_snapshot?.snapshot_id ?? null;
  return {
    backlog: backlogCount(stream),
    blockedEventId: stream.blocked_event_id,
    count: stream.last_snapshot?.count ?? null,
    dead: stream.dead_count,
    merkleRoot: stream.last_snapshot?.merkle_root ?? null,
    snapshotId,
    state: snapshotId === expectedSnapshotId ? stream.state : "snapshot_mismatch",
  };
}

function apiPathFromBffUrl(raw: string): string | null {
  const path = decodedPath(raw);
  return path.startsWith("/api/proxy/")
    ? path.slice("/api/proxy".length)
    : null;
}

function decodedPath(raw: string): string {
  return decodeURIComponent(new URL(raw).pathname);
}

function backlogCount(stream: CacheTargetStreamStatus): number {
  return stream.pending_count + stream.leased_count + stream.retry_count;
}

function relayBacklogLabel(stream: CacheTargetStreamStatus): string {
  return `${formatCount(stream.pending_count)} pending / ${formatCount(
    stream.leased_count,
  )} lease / ${formatCount(stream.retry_count)} retry`;
}

function formatCount(value: number): string {
  return value.toLocaleString("ko-KR");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function clearBrowserState(
  page: Page,
  context: BrowserContext,
): Promise<void> {
  await page
    .evaluate(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    })
    .catch(() => undefined);
  await context.clearCookies();
}
