import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  mkdir,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

import type { Page, Response, Route, TestInfo } from "@playwright/test";

import type { components } from "../../src/api/types";

export type BrowserFetchResult<T> = {
  body: T | null;
  status: number;
};

export type PoiCacheTargetUpsertRequest =
  components["schemas"]["PoiCacheTargetUpsertRequest"];
export type PoiCacheTargetResponse =
  components["schemas"]["PoiCacheTargetResponse"];
export type PoiCacheTargetListResponse =
  components["schemas"]["PoiCacheTargetListResponse"];
export type FeatureUpdateRequestCreateRequest =
  components["schemas"]["FeatureUpdateRequestCreateRequest"];
export type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
export type FeatureUpdateRequestPreviewRequest =
  components["schemas"]["FeatureUpdateRequestPreviewRequest"];
export type FeatureUpdateRequestPreviewResponse =
  components["schemas"]["FeatureUpdateRequestPreviewResponse"];
export type FeatureUpdateRequestMutationResponse =
  components["schemas"]["FeatureUpdateRequestMutationResponse"];
export type PipelineExecutionDetailResponse =
  components["schemas"]["PipelineExecutionDetailResponse"];
export type PipelineOverviewResponse =
  components["schemas"]["PipelineOverviewResponse"];
export type PipelineExecutionsListResponse =
  components["schemas"]["PipelineExecutionsListResponse"];
export type OpsDatasetDetailResponse =
  components["schemas"]["OpsDatasetDetailResponse"];
export type PipelineCancellationResponse =
  components["schemas"]["PipelineCancellationResponse"];

export type TargetRef = { externalSystem: string; targetKey: string };
export type CleanupResult = {
  allRequestsTerminal: boolean;
  preservedForManualCleanup: boolean;
  restored: boolean;
};
export type CleanupScenario = "active" | "empty" | "cap" | "invalidation";
export type CleanupState = {
  cleanupResult: CleanupResult | null;
  completedScenarios: Set<CleanupScenario>;
  externalSystems: Set<string>;
  idempotencyEntries: Map<
    string,
    {
      body: FeatureUpdateRequestCreateRequest;
      requestId: string | null;
      status: string;
    }
  >;
  journalWrite: Promise<void>;
  requestIds: Set<string>;
  requestTerminalStatuses: Map<string, string>;
  runId: string;
  scenario: CleanupScenario;
  scopeStateCount: number;
  stateFile: string;
  targetStatuses: Map<string, string>;
  targets: TargetRef[];
};

type CleanupIssue = {
  http_status?: number;
  kind:
    | "request_detail"
    | "request_cancel"
    | "request_terminal_timeout"
    | "target_delete"
    | "target_residue"
    | "unexpected_exception";
  resource: string;
};

type CleanupManifest = {
  active_target_counts: Record<string, number | null>;
  durable_residue_counts: {
    observed_event_rows: number;
    scope_states: number;
    update_requests: number;
  };
  issues: CleanupIssue[];
  preserved_for_manual_cleanup: boolean;
  request_ids: string[];
  request_terminal_statuses: Record<string, string>;
  run_id: string;
  scenario: CleanupScenario;
  target_refs: TargetRef[];
  version: 1;
};

type CleanupExecution = {
  issues: CleanupIssue[];
  manifest: CleanupManifest;
  result: CleanupResult;
};

// src/kortravelmap/providers/kma.py와 schedules.py의 canonical identity.
export const KMA_PROVIDER = "python-kma-api" as const;
export const KMA_DATASET_KEY = "kma_ultra_short_nowcast" as const;
export const KMA_SAFE_DAGSTER_JOB =
  "feature_weather_kma_ultra_short_nowcast_job" as const;
export const QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor" as const;

export const REQUEST_TERMINAL_TIMEOUT = 8 * 60 * 1000;
export const CLEANUP_TERMINAL_TIMEOUT = 90 * 1000;
export const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"]);

const POI_TARGETS_PATH = "/v1/admin/poi-cache-targets";
const PIPELINE_REQUESTS_PATH = "/v1/ops/pipeline/requests";
const FORBIDDEN_PROVIDER_PATTERN = /opinet/i;
const BROWSER_FETCH_TIMEOUT_MS = 30_000;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const bootstrappedPages = new WeakSet<Page>();

type DurableCleanupJournal = {
  cleanup_result: CleanupResult | null;
  completed_scenarios: CleanupScenario[];
  idempotency_entries: Array<{
    body: FeatureUpdateRequestCreateRequest;
    idempotency_key: string;
    request_id: string | null;
    status: string;
  }>;
  phase: string;
  request_ids: string[];
  request_terminal_statuses: Record<string, string>;
  run_id: string;
  scenario: CleanupScenario;
  scope_state_count: number;
  target_refs: Array<TargetRef & { status: string }>;
  updated_at: string;
  version: 1;
};

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function expectedUiOrigin(): string {
  const rawBase = process.env.E2E_BASE_URL;
  const expectedHash = process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256;
  if (!rawBase || !expectedHash || !SHA256_PATTERN.test(expectedHash)) {
    throw new Error("C7 UI origin/hash attestation이 필요합니다 (values redacted)");
  }
  try {
    const url = new URL(rawBase);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      sha256(url.origin) !== expectedHash
    ) {
      throw new Error("invalid origin");
    }
    return url.origin;
  } catch {
    throw new Error("C7 UI origin/hash attestation 불일치 (values redacted)");
  }
}

function assertBootstrappedPage(page: Page): void {
  if (!bootstrappedPages.has(page)) {
    throw new Error("C7 same-origin bootstrap이 mutation보다 먼저 필요합니다");
  }
  try {
    const actual = new URL(page.url());
    if (
      actual.protocol !== "https:" ||
      actual.origin !== expectedUiOrigin() ||
      sha256(actual.origin) !==
        process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256
    ) {
      throw new Error("origin mismatch");
    }
  } catch {
    throw new Error("C7 browser origin guard 실패 (values redacted)");
  }
}

/** 실제 인증 페이지를 먼저 열어 relative same-origin BFF 호출의 기준을 고정한다. */
export async function bootstrapC7SameOriginPage(
  page: Page,
  destination = "/ops/pipeline",
): Promise<void> {
  let response;
  try {
    response = await page.goto(destination);
  } catch {
    throw new Error("C7 same-origin bootstrap navigation 실패 (values redacted)");
  }
  if (!response?.ok()) {
    throw new Error("C7 same-origin bootstrap HTTP 실패 (values redacted)");
  }
  const url = new URL(page.url());
  if (
    url.origin !== expectedUiOrigin() ||
    url.pathname === "/login" ||
    sha256(url.origin) !== process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256
  ) {
    throw new Error("C7 same-origin/auth bootstrap guard 실패 (values redacted)");
  }
  bootstrappedPages.add(page);
}

function cleanupStateFile(): string {
  const value = process.env.E2E_C7_KMA_STATE_FILE;
  if (!value || !path.isAbsolute(value)) {
    throw new Error(
      "E2E_C7_KMA_STATE_FILE은 host orchestrator가 지정한 절대 경로여야 합니다",
    );
  }
  return value;
}

function targetJournalKey(target: TargetRef): string {
  return `${target.externalSystem}\u0000${target.targetKey}`;
}

function durableJournal(
  state: CleanupState,
  phase: string,
): DurableCleanupJournal {
  const completedScenarios = new Set(state.completedScenarios);
  if (phase === "restored" && state.cleanupResult?.restored === true) {
    completedScenarios.add(state.scenario);
  }
  return {
    cleanup_result: state.cleanupResult,
    completed_scenarios: [...completedScenarios].sort(),
    idempotency_entries: [...state.idempotencyEntries.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([idempotencyKey, entry]) => ({
        body: entry.body,
        idempotency_key: idempotencyKey,
        request_id: entry.requestId,
        status: entry.status,
      })),
    phase,
    request_ids: [...state.requestIds].sort(),
    request_terminal_statuses: Object.fromEntries(
      [...state.requestTerminalStatuses.entries()].sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ),
    run_id: state.runId,
    scenario: state.scenario,
    scope_state_count: state.scopeStateCount,
    target_refs: state.targets.map((target) => ({
      ...target,
      status: state.targetStatuses.get(targetJournalKey(target)) ?? "pending",
    })),
    updated_at: new Date().toISOString(),
    version: 1,
  };
}

function isCleanupScenario(value: unknown): value is CleanupScenario {
  return ["active", "empty", "cap", "invalidation"].includes(String(value));
}

async function mergePreviousJournal(state: CleanupState): Promise<void> {
  try {
    const previous = JSON.parse(await readFile(state.stateFile, "utf8")) as {
      completed_scenarios?: unknown;
      phase?: unknown;
      run_id?: unknown;
    };
    if (previous.phase !== "restored" && previous.run_id !== state.runId) {
      throw new Error("unrestored residue");
    }
    const completedScenarios = previous.completed_scenarios;
    if (
      completedScenarios !== undefined &&
      (!Array.isArray(completedScenarios) ||
        !completedScenarios.every(isCleanupScenario))
    ) {
      throw new Error("invalid completed scenarios");
    }
    if (Array.isArray(completedScenarios)) {
      for (const scenario of completedScenarios) {
        state.completedScenarios.add(scenario as CleanupScenario);
      }
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    if (error instanceof SyntaxError) {
      throw new Error("C7 durable cleanup journal이 손상되었습니다");
    }
    if (error instanceof Error && error.message === "unrestored residue") {
      throw new Error(
        "이전 C7 durable cleanup journal이 미복원 상태입니다; audited recovery가 필요합니다",
      );
    }
    if (error instanceof Error && error.message === "invalid completed scenarios") {
      throw new Error(
        "C7 durable cleanup journal의 completed_scenarios가 손상되었습니다",
      );
    }
    throw error;
  }
}

async function writeDurableJournal(
  state: CleanupState,
  phase: string,
): Promise<void> {
  const write = async (): Promise<void> => {
    const directory = path.dirname(state.stateFile);
    const temporary = `${state.stateFile}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await mergePreviousJournal(state);
      await mkdir(directory, { mode: 0o700, recursive: true });
      await writeFile(
        temporary,
        `${JSON.stringify(durableJournal(state, phase))}\n`,
        { encoding: "utf8", flag: "wx", mode: 0o600 },
      );
      await chmod(temporary, 0o600);
      await rename(temporary, state.stateFile);
      await chmod(state.stateFile, 0o600);
      if (phase === "restored" && state.cleanupResult?.restored === true) {
        state.completedScenarios.add(state.scenario);
      }
    } catch {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw new Error("C7 durable cleanup journal 기록 실패 (values redacted)");
    }
  };
  state.journalWrite = state.journalWrite.then(write, write);
  return state.journalWrite;
}

/**
 * 브라우저 인증 세션으로 same-origin API를 호출한다.
 *
 * 실패 본문은 raw text로 반환하지 않는다. JSON body도 assertion에 자동 출력하지
 * 않으며, 진단은 status와 allowlist된 problem 필드만 사용한다.
 */
export async function browserFetch<T>(
  page: Page,
  path: string,
  options: {
    body?: unknown;
    headers?: Record<string, string>;
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  } = {},
): Promise<BrowserFetchResult<T>> {
  assertBootstrappedPage(page);
  try {
    return await page.evaluate(
      async ({ body, headers, method, path, timeoutMs }) => {
        const response = await fetch(`/api/proxy${path}`, {
          method,
          headers: {
            Accept: "application/json",
            ...(body === undefined
              ? {}
              : { "Content-Type": "application/json" }),
            ...headers,
          },
          credentials: "same-origin",
          cache: "no-store",
          signal: AbortSignal.timeout(timeoutMs),
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        });
        const contentType = response.headers.get("content-type") ?? "";
        let parsed: unknown = null;
        if (contentType.includes("json")) {
          try {
            parsed = await response.json();
          } catch {
            parsed = null;
          }
        }
        return { body: parsed as T | null, status: response.status };
      },
      {
        body: options.body,
        headers: options.headers ?? {},
        method: options.method ?? "GET",
        path,
        timeoutMs: BROWSER_FETCH_TIMEOUT_MS,
      },
    );
  } catch {
    throw new Error("C7 API transport/timeout 실패 (values redacted)");
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** raw body 대신 status와 RFC7807 allowlist만 노출한다. */
export function safeHttpDiagnostic<T>(result: BrowserFetchResult<T>): string {
  const body = asRecord(result.body);
  const problem = body
    ? Object.fromEntries(
        ["type", "title", "code", "request_id"]
          .filter((key) => typeof body[key] === "string")
          .map((key) => [key, body[key]]),
      )
    : {};
  return JSON.stringify({ problem, status: result.status });
}

export function requireBody<T>(
  result: BrowserFetchResult<T>,
  expectedStatus: number,
): T {
  if (result.status !== expectedStatus || result.body === null) {
    throw new Error(
      `C7 API 응답 계약 불일치: expected=${expectedStatus}, ${safeHttpDiagnostic(
        result,
      )}`,
    );
  }
  return result.body;
}

export function requireCreatedOrReplayedKmaRequest(
  result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>,
  options: { allowActiveReuse?: boolean } = {},
): FeatureUpdateRequestCreateResponse {
  if (![200, 201].includes(result.status) || result.body === null) {
    throw new Error(
      `KMA create/replay 응답 계약 불일치: ${safeHttpDiagnostic(result)}`,
    );
  }
  if (
    result.status === 200 &&
    result.body.idempotent_replay !== true &&
    options.allowActiveReuse !== true
  ) {
    throw new Error("KMA HTTP 200은 same-key idempotent replay여야 합니다");
  }
  return result.body;
}

export function destructiveGateBlocker(testInfo: TestInfo): string | null {
  const required: Array<[string, string | undefined]> = [
    ["E2E_LIVE_ALLOW_PROD", process.env.E2E_LIVE_ALLOW_PROD],
    ["E2E_ADMIN_WRITE", process.env.E2E_ADMIN_WRITE],
    ["E2E_KMA_SCOPE_WRITE", process.env.E2E_KMA_SCOPE_WRITE],
    ["E2E_DAGSTER_WRITE", process.env.E2E_DAGSTER_WRITE],
    ["E2E_DAGSTER_RUN", process.env.E2E_DAGSTER_RUN],
  ];
  const missing = required.filter(([, value]) => value !== "1").map(([name]) => name);
  if (missing.length > 0) {
    return `${missing.join(", ")}=1이 없어서 KMA destructive 시나리오 전체를 실행하지 않습니다.`;
  }
  if (process.env.E2E_DAGSTER_JOB !== KMA_SAFE_DAGSTER_JOB) {
    return `E2E_DAGSTER_JOB은 정확히 ${KMA_SAFE_DAGSTER_JOB}이어야 합니다.`;
  }
  if (testInfo.config.workers !== 1) {
    return "KMA destructive live E2E는 실제 workers=1에서만 실행합니다.";
  }
  if (testInfo.project.retries !== 0) {
    return "KMA destructive live E2E는 실제 retries=0에서만 실행합니다.";
  }
  try {
    cleanupStateFile();
    expectedUiOrigin();
  } catch {
    return "KMA destructive live E2E durable state/UI origin attestation이 없습니다.";
  }
  return null;
}

function targetPath(externalSystem: string, targetKey: string): string {
  return `${POI_TARGETS_PATH}/${encodeURIComponent(
    externalSystem,
  )}/${encodeURIComponent(targetKey)}`;
}

export function buildPoiTargetBody(
  lon: number,
  lat: number,
  options: { name: string; runId: string },
): PoiCacheTargetUpsertRequest {
  return {
    coord: { lon, lat },
    coord_precision_digits: 6,
    radius_km: 5,
    name: options.name,
    scope_mode: "center_radius",
    update_enabled: true,
    refresh_policy: "provider_default",
    provider_overrides: {},
    metadata: { note: `C7 KMA live E2E ${options.runId}` },
    on_conflict: "reject",
  };
}

export async function putPoiTarget(
  page: Page,
  externalSystem: string,
  targetKey: string,
  body: PoiCacheTargetUpsertRequest,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  const providerOverrides = Object.keys(body.provider_overrides ?? {});
  if (providerOverrides.some((provider) => FORBIDDEN_PROVIDER_PATTERN.test(provider))) {
    throw new Error("C7 live E2E에서는 OpiNet target override를 사용할 수 없습니다.");
  }
  return browserFetch<PoiCacheTargetResponse>(
    page,
    targetPath(externalSystem, targetKey),
    { method: "PUT", body },
  );
}

export async function getPoiTarget(
  page: Page,
  externalSystem: string,
  targetKey: string,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  return browserFetch<PoiCacheTargetResponse>(
    page,
    targetPath(externalSystem, targetKey),
  );
}

export async function deletePoiTarget(
  page: Page,
  externalSystem: string,
  targetKey: string,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  return browserFetch<PoiCacheTargetResponse>(
    page,
    targetPath(externalSystem, targetKey),
    { method: "DELETE" },
  );
}

export async function listActivePoiTargets(
  page: Page,
  externalSystem: string,
): Promise<BrowserFetchResult<PoiCacheTargetListResponse>> {
  const query = new URLSearchParams({
    external_system: externalSystem,
    include_deleted: "false",
    page_size: "500",
    update_enabled: "true",
  });
  return browserFetch<PoiCacheTargetListResponse>(
    page,
    `${POI_TARGETS_PATH}?${query.toString()}`,
  );
}

async function listAllActivePoiTargets(
  page: Page,
  externalSystem: string,
): Promise<BrowserFetchResult<PoiCacheTargetListResponse>> {
  const query = new URLSearchParams({
    external_system: externalSystem,
    include_deleted: "false",
    page_size: "500",
  });
  return browserFetch<PoiCacheTargetListResponse>(
    page,
    `${POI_TARGETS_PATH}?${query.toString()}`,
  );
}

export function buildKmaRequest(
  externalSystem: string,
  reason: string,
  runMode: "queued" | "now" = "queued",
): FeatureUpdateRequestCreateRequest {
  const body: FeatureUpdateRequestCreateRequest = {
    scope: {
      type: "provider_dataset",
      provider: KMA_PROVIDER,
      dataset_key: KMA_DATASET_KEY,
      sync_scope: `external_system:${externalSystem}`,
    },
    providers: [],
    dataset_keys: [],
    update_policy: {},
    run_mode: runMode,
    priority: 50,
    reason,
  };
  assertKmaOnlyPlan(body);
  return body;
}

export function previewBody(
  body: FeatureUpdateRequestCreateRequest,
): FeatureUpdateRequestPreviewRequest {
  const preview: FeatureUpdateRequestPreviewRequest = {
    scope: body.scope,
    providers: body.providers,
    dataset_keys: body.dataset_keys,
    update_policy: body.update_policy,
    run_mode: body.run_mode,
    priority: body.priority,
  };
  assertKmaOnlyPlan(preview);
  return preview;
}

function assertKmaOnlyPlan(
  body: FeatureUpdateRequestCreateRequest | FeatureUpdateRequestPreviewRequest,
): void {
  const serialized = JSON.stringify(body);
  if (FORBIDDEN_PROVIDER_PATTERN.test(serialized)) {
    throw new Error("C7 live E2E에서는 OpiNet provider를 호출할 수 없습니다.");
  }
  const scope = body.scope;
  if (
    scope.type !== "provider_dataset" ||
    scope.provider !== KMA_PROVIDER ||
    scope.dataset_key !== KMA_DATASET_KEY ||
    !scope.sync_scope?.startsWith("external_system:")
  ) {
    throw new Error(
      "C7 live E2E mutation은 canonical KMA external_system scope만 허용합니다.",
    );
  }
  if ((body.providers?.length ?? 0) > 0 || (body.dataset_keys?.length ?? 0) > 0) {
    throw new Error("provider_dataset scope에 providers/dataset_keys 필터를 중복할 수 없습니다.");
  }
}

export async function previewKmaRequest(
  page: Page,
  body: FeatureUpdateRequestPreviewRequest,
): Promise<BrowserFetchResult<FeatureUpdateRequestPreviewResponse>> {
  assertKmaOnlyPlan(body);
  return browserFetch<FeatureUpdateRequestPreviewResponse>(
    page,
    `${PIPELINE_REQUESTS_PATH}/preview`,
    { method: "POST", body },
  );
}

export async function createKmaRequest(
  page: Page,
  body: FeatureUpdateRequestCreateRequest,
  idempotencyKey: string,
  state?: CleanupState,
): Promise<BrowserFetchResult<FeatureUpdateRequestCreateResponse>> {
  assertKmaOnlyPlan(body);
  if (state) {
    await journalPendingRequest(state, body, idempotencyKey);
  }
  const submit = () =>
    browserFetch<FeatureUpdateRequestCreateResponse>(
      page,
      PIPELINE_REQUESTS_PATH,
      {
        method: "POST",
        body,
        headers: { "Idempotency-Key": idempotencyKey },
      },
    );
  let result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  try {
    result = await submit();
  } catch (error) {
    if (!state) throw error;
    const pending = state.idempotencyEntries.get(idempotencyKey);
    if (pending) pending.status = "response_lost_replaying";
    await writeDurableJournal(state, "request_response_lost");
    result = await submit();
  }
  if (state) {
    await trackRequestResult(state, result, idempotencyKey);
  }
  return result;
}

export type TrackedUiKmaCreateResult = {
  created: FeatureUpdateRequestCreateResponse;
  recovered: boolean;
  result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
};

export async function resolveTrackedUiKmaCreateResponse(
  page: Page,
  state: CleanupState,
  idempotencyKey: string,
  body: FeatureUpdateRequestCreateRequest,
  response: Response | null,
  options: { allowActiveReuse?: boolean } = {},
): Promise<TrackedUiKmaCreateResult> {
  let parsed: FeatureUpdateRequestCreateResponse | null = null;
  if (response !== null) {
    try {
      parsed = (await response.json()) as FeatureUpdateRequestCreateResponse;
    } catch {
      parsed = null;
    }
  }

  const recovered = response === null || parsed === null;
  let result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  if (recovered) {
    const entry = state.idempotencyEntries.get(idempotencyKey);
    if (!entry) {
      throw new Error("UI KMA create recovery journal identity가 없습니다");
    }
    entry.status = "response_lost_replaying";
    await writeDurableJournal(state, "request_response_lost");
    result = await createKmaRequest(page, body, idempotencyKey, state);
  } else {
    if (response === null || parsed === null) {
      throw new Error("UI KMA create response 분기 불변식이 깨졌습니다");
    }
    result = { body: parsed, status: response.status() };
    await trackRequestResult(state, result, idempotencyKey);
  }

  return {
    created: requireCreatedOrReplayedKmaRequest(result, options),
    recovered,
    result,
  };
}

export async function submitTrackedUiKmaCreate(
  page: Page,
  state: CleanupState,
  submit: () => Promise<void>,
): Promise<TrackedUiKmaCreateResult> {
  let idempotencyKey: string | null = null;
  let journaledBody: FeatureUpdateRequestCreateRequest | null = null;
  const routeHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    let pathname: string;
    try {
      pathname = new URL(request.url()).pathname;
    } catch {
      await route.fallback();
      return;
    }
    if (
      request.method() !== "POST" ||
      pathname !== "/api/proxy/v1/ops/pipeline/requests"
    ) {
      await route.fallback();
      return;
    }
    const candidateKey = request.headers()["idempotency-key"];
    if (!candidateKey) {
      await route.abort("failed");
      return;
    }
    const body = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
    await journalPendingRequest(state, body, candidateKey);
    idempotencyKey = candidateKey;
    journaledBody = body;
    await route.continue();
  };

  await page.route("**/api/proxy/v1/ops/pipeline/requests", routeHandler);
  const responsePromise = page.waitForResponse((candidate) => {
    try {
      return (
        candidate.request().method() === "POST" &&
        new URL(candidate.url()).pathname ===
          "/api/proxy/v1/ops/pipeline/requests"
      );
    } catch {
      return false;
    }
  });
  let response: Response | null = null;
  try {
    await submit();
    response = await responsePromise.catch(() => null);
  } finally {
    await page.unroute("**/api/proxy/v1/ops/pipeline/requests", routeHandler);
  }
  if (!idempotencyKey || !journaledBody) {
    throw new Error("UI KMA create durable journal identity가 없습니다");
  }
  return resolveTrackedUiKmaCreateResponse(
    page,
    state,
    idempotencyKey,
    journaledBody,
    response,
  );
}

export async function runTrackedRequestNowFromUi(
  page: Page,
  state: CleanupState,
  requestId: string,
  jobId: string,
  submit: () => Promise<void>,
): Promise<FeatureUpdateRequestMutationResponse> {
  const responsePromise = page.waitForResponse((candidate) => {
    try {
      return (
        candidate.request().method() === "POST" &&
        new URL(candidate.url()).pathname ===
          `/api/proxy/v1/ops/pipeline/requests/${requestId}/run-now`
      );
    } catch {
      return false;
    }
  });
  await journalRunNowMutation(state, requestId, "pending");
  await submit();
  const response = await responsePromise;
  let body: FeatureUpdateRequestMutationResponse | null = null;
  if (response.status() === 200) {
    try {
      body = (await response.json()) as FeatureUpdateRequestMutationResponse;
    } catch {
      body = null;
    }
  }
  if (
    body === null ||
    body.data.request_id !== requestId ||
    body.data.job_id !== jobId
  ) {
    throw new Error("UI KMA run-now 응답 계약이 request/job identity와 다릅니다");
  }
  await journalRunNowMutation(state, requestId, "observed");
  return body;
}

export async function runRequestNow(
  page: Page,
  requestId: string,
  state?: CleanupState,
): Promise<BrowserFetchResult<FeatureUpdateRequestMutationResponse>> {
  if (state) await writeDurableJournal(state, "run_now_pending");
  const result = await browserFetch<FeatureUpdateRequestMutationResponse>(
    page,
    `${PIPELINE_REQUESTS_PATH}/${encodeURIComponent(requestId)}/run-now`,
    { method: "POST", body: {} },
  );
  if (state) await writeDurableJournal(state, "run_now_observed");
  return result;
}

export async function journalRunNowMutation(
  state: CleanupState,
  requestId: string,
  phase: "pending" | "observed",
): Promise<void> {
  if (!state.requestIds.has(requestId)) {
    throw new Error("run-now journal request identity가 cleanup state에 없습니다");
  }
  await writeDurableJournal(state, `run_now_${phase}`);
}

export async function getRequestDetail(
  page: Page,
  requestId: string,
): Promise<BrowserFetchResult<PipelineExecutionDetailResponse>> {
  return browserFetch<PipelineExecutionDetailResponse>(
    page,
    `/v1/ops/pipeline/executions/update_request/${encodeURIComponent(requestId)}`,
  );
}

function exactScopeQuery(syncScope: string): string {
  return new URLSearchParams({
    provider: KMA_PROVIDER,
    dataset_key: KMA_DATASET_KEY,
    sync_scope: syncScope,
  }).toString();
}

export function exactDatasetUiPath(syncScope: string): string {
  const query = new URLSearchParams({
    provider: KMA_PROVIDER,
    dataset: KMA_DATASET_KEY,
    sync_scope: syncScope,
    panel: "history",
  });
  return `/ops/datasets?${query.toString()}`;
}

export async function getExactDatasetDetail(
  page: Page,
  syncScope: string,
): Promise<BrowserFetchResult<OpsDatasetDetailResponse>> {
  return browserFetch<OpsDatasetDetailResponse>(
    page,
    `/v1/ops/datasets/detail?${exactScopeQuery(syncScope)}`,
  );
}

export async function getPipelineOverview(
  page: Page,
): Promise<BrowserFetchResult<PipelineOverviewResponse>> {
  return browserFetch<PipelineOverviewResponse>(
    page,
    "/v1/ops/pipeline/overview?run_limit=1",
  );
}

export type NonTerminalFeatureUpdateRequest = {
  id: string;
  status: "queued" | "running";
};

async function listExactFeatureUpdateRequestsByStatus(
  page: Page,
  status: NonTerminalFeatureUpdateRequest["status"],
): Promise<NonTerminalFeatureUpdateRequest[]> {
  const query = new URLSearchParams({
    kind: "update_request",
    page_size: "200",
    status,
  });
  const response = requireBody(
    await browserFetch<PipelineExecutionsListResponse>(
      page,
      `/v1/ops/pipeline/executions?${query.toString()}`,
    ),
    200,
  );
  if (response.meta.page?.next_cursor !== null) {
    throw new Error(
      `global ${status} feature update request 목록이 한 페이지를 초과해 안전 검증을 중단했습니다`,
    );
  }
  if (
    response.data.items.some(
      (item) => item.kind !== "update_request" || item.status !== status,
    )
  ) {
    throw new Error(`global ${status} feature update request 필터 계약이 깨졌습니다`);
  }
  return response.data.items.map((item) => ({ id: item.id, status }));
}

export async function assertExactNonTerminalFeatureUpdateRequests(
  page: Page,
  expected: readonly NonTerminalFeatureUpdateRequest[],
  checkpoint: string,
): Promise<void> {
  // queued를 먼저 읽으면 RUNNING sensor 아래 상태 전이가 일어나도 두 조회 사이에서
  // non-terminal request를 놓치지 않는다. sensor STOPPED 이후에는 queued가 고정된다.
  const queued = await listExactFeatureUpdateRequestsByStatus(page, "queued");
  const running = await listExactFeatureUpdateRequestsByStatus(page, "running");
  const identity = (item: NonTerminalFeatureUpdateRequest): string =>
    `${item.status}:${item.id}`;
  const observedIdentities = [...queued, ...running].map(identity).sort();
  const expectedIdentities = expected.map(identity).sort();
  if (JSON.stringify(observedIdentities) !== JSON.stringify(expectedIdentities)) {
    throw new Error(
      `${checkpoint}: global non-terminal feature update request 집합 불일치(expected=${expectedIdentities.length}, observed=${observedIdentities.length})`,
    );
  }
}

export function queueSensorOperational(response: PipelineOverviewResponse): boolean {
  if (response.data.dagster.status !== "ok") return false;
  return (
    response.data.dagster.sensors?.find((sensor) => sensor.name === QUEUE_SENSOR_NAME)
      ?.status === "RUNNING"
  );
}

export async function cancelRequest(
  page: Page,
  requestId: string,
  reason: string,
): Promise<BrowserFetchResult<PipelineCancellationResponse>> {
  return browserFetch<PipelineCancellationResponse>(
    page,
    `/v1/ops/pipeline/executions/update_request/${encodeURIComponent(
      requestId,
    )}/cancel`,
    { method: "POST", body: { reason } },
  );
}

export function createCleanupState(
  scenario: CleanupScenario,
  runId: string,
): CleanupState {
  return {
    cleanupResult: null,
    completedScenarios: new Set(),
    externalSystems: new Set(),
    idempotencyEntries: new Map(),
    journalWrite: Promise.resolve(),
    requestIds: new Set(),
    requestTerminalStatuses: new Map(),
    runId,
    scenario,
    scopeStateCount: 0,
    stateFile: cleanupStateFile(),
    targetStatuses: new Map(),
    targets: [],
  };
}

export function trackTarget(state: CleanupState, target: TargetRef): void {
  if (
    !state.targets.some(
      (item) =>
        item.externalSystem === target.externalSystem &&
        item.targetKey === target.targetKey,
    )
  ) {
    state.targets.push(target);
  }
  state.externalSystems.add(target.externalSystem);
  state.targetStatuses.set(targetJournalKey(target), "pending");
}

export async function journalPendingRequest(
  state: CleanupState,
  body: FeatureUpdateRequestCreateRequest,
  idempotencyKey: string,
): Promise<void> {
  assertKmaOnlyPlan(body);
  const existing = state.idempotencyEntries.get(idempotencyKey);
  if (existing && JSON.stringify(existing.body) !== JSON.stringify(body)) {
    throw new Error("동일 Idempotency-Key의 KMA request body가 변경되었습니다");
  }
  if (existing) {
    existing.status = existing.requestId === null ? "pending" : "replay_pending";
  } else {
    state.idempotencyEntries.set(idempotencyKey, {
      body,
      requestId: null,
      status: "pending",
    });
  }
  await writeDurableJournal(state, "request_pending");
}

export async function trackRequestResult(
  state: CleanupState,
  result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>,
  idempotencyKey?: string,
): Promise<void> {
  const data = asRecord(asRecord(result.body)?.data);
  const requestId =
    typeof data?.request_id === "string" ? data.request_id : undefined;
  if (requestId) state.requestIds.add(requestId);
  if (idempotencyKey) {
    const entry = state.idempotencyEntries.get(idempotencyKey);
    if (entry) {
      entry.requestId = requestId ?? null;
      entry.status = requestId ? `response_${result.status}` : `http_${result.status}`;
    }
  }
  await writeDurableJournal(state, "request_observed");
}

export async function putTrackedTarget(
  page: Page,
  state: CleanupState,
  target: TargetRef,
  body: PoiCacheTargetUpsertRequest,
): Promise<PoiCacheTargetResponse> {
  trackTarget(state, target);
  await writeDurableJournal(state, "target_pending");
  const result = await putPoiTarget(
    page,
    target.externalSystem,
    target.targetKey,
    body,
  );
  const response = requireBody(result, 200);
  state.targetStatuses.set(targetJournalKey(target), "active");
  await writeDurableJournal(state, "target_active");
  return response;
}

export async function deleteTrackedTarget(
  page: Page,
  state: CleanupState,
  target: TargetRef,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  trackTarget(state, target);
  state.targetStatuses.set(targetJournalKey(target), "delete_pending");
  await writeDurableJournal(state, "target_delete_pending");
  const result = await deletePoiTarget(
    page,
    target.externalSystem,
    target.targetKey,
  );
  if ([200, 404].includes(result.status)) {
    state.targetStatuses.set(targetJournalKey(target), "deleted");
  }
  await writeDurableJournal(state, "target_delete_observed");
  return result;
}

export async function pollTerminal(
  page: Page,
  requestId: string,
  timeout = REQUEST_TERMINAL_TIMEOUT,
): Promise<string | null> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await getRequestDetail(page, requestId);
    const status = result.body?.data.execution.status;
    if (status && TERMINAL_STATUSES.has(status)) return status;
    if (result.status === 404) return "not_found";
    await page.waitForTimeout(1_000);
  }
  return null;
}

export async function waitForTerminal(
  page: Page,
  requestId: string,
  timeout = REQUEST_TERMINAL_TIMEOUT,
  state?: CleanupState,
): Promise<PipelineExecutionDetailResponse> {
  const terminal = await pollTerminal(page, requestId, timeout);
  if (!terminal || !TERMINAL_STATUSES.has(terminal)) {
    throw new Error(`request ${requestId} terminal 대기 실패: ${terminal ?? "timeout"}`);
  }
  const detail = requireBody(await getRequestDetail(page, requestId), 200);
  if (state) {
    state.requestTerminalStatuses.set(
      requestId,
      detail.data.execution.status,
    );
    for (const entry of state.idempotencyEntries.values()) {
      if (entry.requestId === requestId) {
        entry.status = `terminal_${detail.data.execution.status}`;
      }
    }
    await writeDurableJournal(state, "request_terminal");
  }
  return detail;
}

export async function rediscoverExactActiveRequest(
  page: Page,
  syncScope: string,
): Promise<NonNullable<OpsDatasetDetailResponse["data"]["active_execution"]>> {
  const detail = requireBody(await getExactDatasetDetail(page, syncScope), 200);
  const active = detail.data.active_execution;
  if (
    active === null ||
    active.kind !== "update_request" ||
    active.sync_scope !== syncScope
  ) {
    throw new Error(`exact scope active request 재탐색 실패: ${syncScope}`);
  }
  return active;
}

export async function runCreateDeleteCanary(
  page: Page,
  state: CleanupState,
  target: TargetRef,
  body: PoiCacheTargetUpsertRequest,
): Promise<void> {
  const created = await putTrackedTarget(page, state, target, body);
  const read = requireBody(
    await getPoiTarget(page, target.externalSystem, target.targetKey),
    200,
  );
  if (read.data.target_id !== created.data.target_id) {
    throw new Error("POI target canary read identity 불일치");
  }
  requireBody(
    await deleteTrackedTarget(page, state, target),
    200,
  );
  const active = requireBody(
    await listActivePoiTargets(page, target.externalSystem),
    200,
  );
  if (active.data.items.length !== 0) {
    throw new Error("POI target canary 삭제 뒤 active target이 남았습니다.");
  }
}

async function targetCount(
  page: Page,
  externalSystem: string,
): Promise<number | null> {
  const result = await listAllActivePoiTargets(page, externalSystem);
  return result.status === 200 && result.body !== null
    ? result.body.data.items.length
    : null;
}

async function attachManifest(
  testInfo: TestInfo,
  manifest: CleanupManifest,
): Promise<void> {
  await testInfo.attach("c7-cleanup-manifest.json", {
    body: JSON.stringify(manifest, null, 2),
    contentType: "application/json",
  });
}

async function cleanupResources(
  page: Page,
  testInfo: TestInfo,
  state: CleanupState,
  terminalTimeout: number,
): Promise<CleanupExecution> {
  const issues: CleanupIssue[] = [];
  const statuses: Record<string, string> = {};
  let observedEventRows = 0;
  let exactScopeDiscoveryComplete = true;

  // 응답 유실 뒤 서버에는 request가 생긴 경우도 target보다 먼저 회수한다.
  const activeDiscoveries = await Promise.allSettled(
    [...state.externalSystems].sort().map(async (externalSystem) => ({
      externalSystem,
      result: await getExactDatasetDetail(
        page,
        `external_system:${externalSystem}`,
      ),
    })),
  );
  for (const settled of activeDiscoveries) {
    if (settled.status === "rejected") {
      exactScopeDiscoveryComplete = false;
      issues.push({
        kind: "unexpected_exception",
        resource: "exact_scope_active_discovery",
      });
      continue;
    }
    const { externalSystem, result } = settled.value;
    if (result.status === 404) continue;
    if (result.status !== 200 || result.body === null) {
      exactScopeDiscoveryComplete = false;
      issues.push({
        http_status: result.status,
        kind: "request_detail",
        resource: `external_system:${externalSystem}`,
      });
      continue;
    }
    const active = result.body.data.active_execution;
    if (active?.kind === "update_request") {
      state.requestIds.add(active.id);
    } else if (active !== null) {
      exactScopeDiscoveryComplete = false;
      issues.push({
        kind: "request_detail",
        resource: `external_system:${externalSystem}`,
      });
    }
  }
  await writeDurableJournal(state, "cleanup_discovered");
  const requestIds = [...state.requestIds].sort();

  const initialDetails = await Promise.allSettled(
    requestIds.map(async (requestId) => ({
      requestId,
      result: await getRequestDetail(page, requestId),
    })),
  );
  const cancelIds: string[] = [];
  for (const settled of initialDetails) {
    if (settled.status === "rejected") {
      issues.push({ kind: "unexpected_exception", resource: "request_detail" });
      continue;
    }
    const { requestId, result } = settled.value;
    if (result.status !== 200 || result.body === null) {
      issues.push({
        http_status: result.status,
        kind: "request_detail",
        resource: requestId,
      });
      continue;
    }
    const status = result.body.data.execution.status;
    statuses[requestId] = status;
    observedEventRows += result.body.data.events.length;
    if (!TERMINAL_STATUSES.has(status)) cancelIds.push(requestId);
  }

  if (cancelIds.length > 0) {
    await writeDurableJournal(state, "cleanup_cancel_pending");
  }
  const cancellations = await Promise.allSettled(
    cancelIds.map(async (requestId) => ({
      requestId,
      result: await cancelRequest(
        page,
        requestId,
        `C7 ${state.scenario} ${state.runId} cleanup`,
      ),
    })),
  );
  for (const settled of cancellations) {
    if (settled.status === "rejected") {
      issues.push({ kind: "unexpected_exception", resource: "request_cancel" });
      continue;
    }
    const { requestId, result } = settled.value;
    if (![200, 404, 409].includes(result.status)) {
      issues.push({
        http_status: result.status,
        kind: "request_cancel",
        resource: requestId,
      });
    }
  }
  await writeDurableJournal(state, "cleanup_cancelled");

  const terminalResults = await Promise.allSettled(
    requestIds.map(async (requestId) => ({
      requestId,
      status: await pollTerminal(page, requestId, terminalTimeout),
    })),
  );
  let everyRequestTerminal = true;
  for (const settled of terminalResults) {
    if (settled.status === "rejected") {
      everyRequestTerminal = false;
      issues.push({ kind: "unexpected_exception", resource: "request_terminal" });
      continue;
    }
    const { requestId, status } = settled.value;
    if (status && TERMINAL_STATUSES.has(status)) {
      statuses[requestId] = status;
      state.requestTerminalStatuses.set(requestId, status);
    } else {
      everyRequestTerminal = false;
      issues.push({ kind: "request_terminal_timeout", resource: requestId });
    }
  }
  await writeDurableJournal(state, "cleanup_terminal_checked");

  // 하나라도 terminal을 증명하지 못하면 어떤 target도 삭제하지 않는다.
  const canDeleteTargets = everyRequestTerminal && exactScopeDiscoveryComplete;
  if (canDeleteTargets) {
    const targets = [...state.targets].reverse();
    const batchSize = 3;
    for (let offset = 0; offset < targets.length; offset += batchSize) {
      const batch = targets.slice(offset, offset + batchSize);
      for (const target of batch) {
        state.targetStatuses.set(targetJournalKey(target), "delete_pending");
      }
      await writeDurableJournal(state, "cleanup_target_batch_pending");
      const deletions = await Promise.allSettled(
        batch.map(async (target) => ({
          result: await deletePoiTarget(
            page,
            target.externalSystem,
            target.targetKey,
          ),
          target,
        })),
      );
      for (const settled of deletions) {
        if (settled.status === "rejected") {
          issues.push({ kind: "unexpected_exception", resource: "target_delete" });
          continue;
        }
        const { result, target } = settled.value;
        if (![200, 404].includes(result.status)) {
          issues.push({
            http_status: result.status,
            kind: "target_delete",
            resource: `${target.externalSystem}/${target.targetKey}`,
          });
        } else {
          state.targetStatuses.set(targetJournalKey(target), "deleted");
        }
      }
      await writeDurableJournal(state, "cleanup_target_batch_deleted");
    }
  }

  const activeTargetCounts: Record<string, number | null> = {};
  const countResults = await Promise.allSettled(
    [...state.externalSystems].sort().map(async (externalSystem) => ({
      count: await targetCount(page, externalSystem),
      externalSystem,
    })),
  );
  for (const settled of countResults) {
    if (settled.status === "rejected") {
      issues.push({
        kind: "unexpected_exception",
        resource: "active_target_count",
      });
      continue;
    }
    const { count, externalSystem } = settled.value;
    activeTargetCounts[externalSystem] = count;
    if (canDeleteTargets && count !== 0) {
      issues.push({
        kind: "target_residue",
        resource: externalSystem,
      });
    }
  }

  const hasTargetResidue = Object.values(activeTargetCounts).some(
    (count) => count === null || count > 0,
  );
  const preservedForManualCleanup =
    !canDeleteTargets || hasTargetResidue || issues.length > 0;
  const result: CleanupResult = {
    allRequestsTerminal: everyRequestTerminal && exactScopeDiscoveryComplete,
    preservedForManualCleanup,
    restored: !preservedForManualCleanup,
  };
  state.cleanupResult = result;
  const manifest: CleanupManifest = {
    active_target_counts: activeTargetCounts,
    durable_residue_counts: {
      observed_event_rows: observedEventRows,
      scope_states: state.scopeStateCount,
      update_requests: requestIds.length,
    },
    issues,
    preserved_for_manual_cleanup: preservedForManualCleanup,
    request_ids: requestIds,
    request_terminal_statuses: statuses,
    run_id: state.runId,
    scenario: state.scenario,
    target_refs: [...state.targets],
    version: 1,
  };
  await writeDurableJournal(
    state,
    result.restored ? "restored" : "cleanup_blocked",
  );
  await attachManifest(testInfo, manifest);
  return { issues, manifest, result };
}

export async function withC7Cleanup(
  page: Page,
  testInfo: TestInfo,
  state: CleanupState,
  body: () => Promise<void>,
  options: { terminalTimeout?: number } = {},
): Promise<CleanupResult> {
  let primaryError: unknown;
  let cleanup: CleanupExecution | null = null;
  try {
    await body();
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    try {
      cleanup = await cleanupResources(
        page,
        testInfo,
        state,
        options.terminalTimeout ?? CLEANUP_TERMINAL_TIMEOUT,
      );
    } catch {
      const issues: CleanupIssue[] = [
        { kind: "unexpected_exception", resource: "cleanup_boundary" },
      ];
      state.cleanupResult = {
        allRequestsTerminal: false,
        preservedForManualCleanup: true,
        restored: false,
      };
      const fallbackManifest: CleanupManifest = {
        active_target_counts: Object.fromEntries(
          [...state.externalSystems].sort().map((value) => [value, null]),
        ),
        durable_residue_counts: {
          observed_event_rows: 0,
          scope_states: state.scopeStateCount,
          update_requests: state.requestIds.size,
        },
        issues,
        preserved_for_manual_cleanup: true,
        request_ids: [...state.requestIds].sort(),
        request_terminal_statuses: {},
        run_id: state.runId,
        scenario: state.scenario,
        target_refs: [...state.targets],
        version: 1,
      };
      await writeDurableJournal(state, "cleanup_boundary_failed").catch(
        () => undefined,
      );
      await attachManifest(testInfo, fallbackManifest).catch(() => undefined);
      cleanup = {
        issues,
        manifest: fallbackManifest,
        result: state.cleanupResult,
      };
    }
    if (cleanup === null) {
      throw new Error("C7 cleanup 결과가 생성되지 않았습니다");
    }
    if (cleanup.issues.length > 0) {
      testInfo.annotations.push({
        type: "cleanup-error",
        description: `C7 cleanup issue ${cleanup.issues.length}건; sanitized manifest 확인`,
      });
      if (primaryError === undefined) {
        throw new Error(
          `C7 cleanup 실패 ${cleanup.issues.length}건; target 보존 여부는 sanitized manifest 확인`,
        );
      }
    }
  }
  return cleanup?.result ?? {
    allRequestsTerminal: false,
    preservedForManualCleanup: true,
    restored: false,
  };
}
