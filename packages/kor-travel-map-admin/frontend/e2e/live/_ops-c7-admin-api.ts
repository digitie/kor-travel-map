import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  mkdir,
  open,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

import type { Page, TestInfo } from "@playwright/test";

import type { components } from "../../src/api/types";

// C7 live spec 공용 helper. same-origin BFF 호출과, C7 spec이 만드는 POI/cache target의
// crash-safe 소유·복원 journal(`E2E_C7_TARGET_STATE_FILE`)을 맡는다.
//
// 2026-10-01: Map은 weather를 더 적재하지 않는다(ADR-104/105). 이 helper가 들고 있던
// KMA exact-scope 갱신 요청(`external_system:c7-e2e` × `kma_ultra_short_nowcast`)의
// 제출·소유·취소·Dagster run 결박은 그 spec 넷과 함께 지웠다. journal에 남은 것은
// target 소유권뿐이다 — 이 helper로는 feature update request를 만들지 않는다. queue sensor →
// worker run 기준(옛 기준 5)은 upstream 0인 krairport dataset으로
// `ops-c7-update-request-write.live.spec.ts`가 자기 journal(`requests.json`)과 함께 맡는다.

export type BrowserFetchResult<T> = {
  body: T | null;
  entityTag: string | null;
  status: number;
};

export type PoiCacheTargetUpsertRequest =
  components["schemas"]["PoiCacheTargetUpsertRequest"];
export type PoiCacheTargetResponse =
  components["schemas"]["PoiCacheTargetResponse"];
export type PoiCacheTargetListResponse =
  components["schemas"]["PoiCacheTargetListResponse"];

export type TargetRef = { externalSystem: string; targetKey: string };
type OwnedTarget = TargetRef & {
  body: PoiCacheTargetUpsertRequest;
  entityTag: string;
  lockVersion: number;
  targetId: string;
};
export type CleanupResult = {
  preservedForManualCleanup: boolean;
  restored: boolean;
};
/** journal을 쓰는 C7 시나리오. 러너는 최종 journal에서 이 집합 전부의 완료를 요구한다. */
export type CleanupScenario = "invalidation";
const CLEANUP_SCENARIOS: readonly CleanupScenario[] = ["invalidation"];
export type CleanupState = {
  allExternalSystems: Set<string>;
  allTargetRefs: Map<string, TargetJournalRef>;
  cleanupResult: CleanupResult | null;
  completedScenarios: Set<CleanupScenario>;
  externalSystems: Set<string>;
  journalWrite: Promise<void>;
  runId: string;
  scenario: CleanupScenario;
  stateFile: string;
  targetHistory: TargetJournalRef[];
  targetStatuses: Map<string, string>;
  targets: OwnedTarget[];
};

type TargetJournalRef = TargetRef & {
  body: PoiCacheTargetUpsertRequest;
  entityTag: string | null;
  lockVersion: number | null;
  status: string;
  targetId: string | null;
};

type CleanupIssue = {
  http_status?: number;
  kind:
    | "target_delete"
    | "target_intent_recovery"
    | "target_residue"
    | "unexpected_exception";
  resource: string;
};

type CleanupExecution = {
  issues: CleanupIssue[];
  result: CleanupResult;
};

/** host orchestrator가 첫 durable write 전에 깔아 두는 placeholder(`poi.json`과 같은 꼴). */
const ORCHESTRATOR_PLACEHOLDER = { phase: "orchestrator_pending", version: 1 };

type DurableCleanupJournal = {
  cleanup_result: CleanupResult | null;
  completed_scenarios: CleanupScenario[];
  external_systems: string[];
  phase: string;
  run_id: string;
  scenario: CleanupScenario;
  target_refs: TargetJournalRef[];
  target_history: TargetJournalRef[];
  updated_at: string;
  version: 1;
};

const POI_TARGETS_PATH = "/v1/admin/poi-cache-targets";
const FORBIDDEN_PROVIDER_PATTERN = /opinet/i;
const BROWSER_FETCH_TIMEOUT_MS = 30_000;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const bootstrappedPages = new WeakSet<Page>();

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STRONG_ENTITY_TAG_PATTERN =
  /^"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):([1-9][0-9]*)"$/;

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
  const value = process.env.E2E_C7_TARGET_STATE_FILE;
  if (!value || !path.isAbsolute(value)) {
    throw new Error(
      "E2E_C7_TARGET_STATE_FILE은 host orchestrator가 지정한 절대 경로여야 합니다",
    );
  }
  return value;
}

function targetJournalKey(target: TargetRef): string {
  return `${target.externalSystem}\u0000${target.targetKey}`;
}

function targetRefWithStatus(
  target: OwnedTarget,
  status: string,
): TargetJournalRef {
  return {
    body: target.body,
    entityTag: target.entityTag,
    externalSystem: target.externalSystem,
    lockVersion: target.lockVersion,
    status,
    targetId: target.targetId,
    targetKey: target.targetKey,
  };
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
    external_systems: [...state.allExternalSystems].sort(),
    phase,
    run_id: state.runId,
    scenario: state.scenario,
    target_refs: [...state.allTargetRefs.values()].sort((left, right) =>
      targetJournalKey(left).localeCompare(targetJournalKey(right)),
    ),
    target_history: [...state.targetHistory].sort((left, right) => {
      const keyOrder = targetJournalKey(left).localeCompare(
        targetJournalKey(right),
      );
      if (keyOrder !== 0) return keyOrder;
      return (left.targetId ?? "").localeCompare(right.targetId ?? "");
    }),
    updated_at: new Date().toISOString(),
    version: 1,
  };
}

function isCleanupScenario(value: unknown): value is CleanupScenario {
  return (CLEANUP_SCENARIOS as readonly string[]).includes(String(value));
}

function isOrchestratorPlaceholder(value: unknown): boolean {
  const record = asRecord(value);
  return (
    record !== null &&
    exactJson(record, ORCHESTRATOR_PLACEHOLDER)
  );
}

async function mergePreviousJournal(state: CleanupState): Promise<void> {
  try {
    const raw = JSON.parse(await readFile(state.stateFile, "utf8")) as unknown;
    if (isOrchestratorPlaceholder(raw)) return;
    const previous = (asRecord(raw) ?? {}) as {
      cleanup_result?: unknown;
      completed_scenarios?: unknown;
      external_systems?: unknown;
      phase?: unknown;
      run_id?: unknown;
      scenario?: unknown;
      target_refs?: unknown;
      target_history?: unknown;
      version?: unknown;
    };
    const isCurrentScenario =
      previous.run_id === state.runId && previous.scenario === state.scenario;
    if (
      previous.version !== 1 ||
      typeof previous.run_id !== "string" ||
      previous.run_id.length === 0 ||
      !isCleanupScenario(previous.scenario) ||
      !Array.isArray(previous.completed_scenarios) ||
      !Array.isArray(previous.external_systems) ||
      !Array.isArray(previous.target_refs) ||
      !Array.isArray(previous.target_history)
    ) {
      throw new Error("invalid target history");
    }
    if (previous.phase !== "restored" && !isCurrentScenario) {
      throw new Error("unrestored residue");
    }
    const completedScenarios = previous.completed_scenarios;
    if (!completedScenarios.every(isCleanupScenario)) {
      throw new Error("invalid completed scenarios");
    }
    const externalSystems = previous.external_systems;
    if (
      !externalSystems.every(
        (value): value is string => typeof value === "string" && value.length > 0,
      )
    ) {
      throw new Error("invalid target history");
    }
    const targetRefs = previous.target_refs;
    if (
      !targetRefs.every((value) => {
        const item = asRecord(value);
        const body = asRecord(item?.body);
        const pendingIdentity =
          item?.targetId === null &&
          item?.entityTag === null &&
          item?.lockVersion === null;
        const durableIdentity =
          typeof item?.targetId === "string" &&
          UUID_PATTERN.test(item.targetId) &&
          typeof item?.entityTag === "string" &&
          typeof item?.lockVersion === "number" &&
          Number.isSafeInteger(item.lockVersion) &&
          item.lockVersion > 0 &&
          parseStrongEntityTag(item.entityTag, item.targetId) ===
            item.lockVersion;
        return (
          item !== null &&
          body !== null &&
          typeof item.externalSystem === "string" &&
          item.externalSystem.length > 0 &&
          typeof item.targetKey === "string" &&
          item.targetKey.length > 0 &&
          typeof item.status === "string" &&
          item.status.length > 0 &&
          (pendingIdentity || durableIdentity)
        );
      })
    ) {
      throw new Error("invalid target history");
    }
    const seenTargetKeys = new Set<string>();
    for (const value of targetRefs) {
      const key = targetJournalKey(value as TargetJournalRef);
      if (seenTargetKeys.has(key)) {
        throw new Error("invalid target history");
      }
      seenTargetKeys.add(key);
    }
    const targetHistory = previous.target_history;
    if (
      !targetHistory.every((value) => {
        const item = asRecord(value);
        return (
          item !== null &&
          asRecord(item.body) !== null &&
          typeof item.externalSystem === "string" &&
          item.externalSystem.length > 0 &&
          typeof item.targetKey === "string" &&
          item.targetKey.length > 0 &&
          typeof item.targetId === "string" &&
          UUID_PATTERN.test(item.targetId) &&
          typeof item.entityTag === "string" &&
          typeof item.lockVersion === "number" &&
          Number.isSafeInteger(item.lockVersion) &&
          item.lockVersion > 0 &&
          parseStrongEntityTag(item.entityTag, item.targetId) ===
            item.lockVersion &&
          typeof item.status === "string" &&
          item.status.length > 0
        );
      })
    ) {
      throw new Error("invalid target history");
    }
    if (
      new Set(
        targetHistory.map((value) => {
          const item = value as TargetJournalRef;
          return `${targetJournalKey(item)}\u0000${item.targetId}`;
        }),
      ).size !== targetHistory.length
    ) {
      throw new Error("invalid target history");
    }
    const targetExternalSystems = new Set(
      (targetRefs as TargetJournalRef[]).map((item) => item.externalSystem),
    );
    if (
      externalSystems.length !== targetExternalSystems.size ||
      externalSystems.some(
        (externalSystem) => !targetExternalSystems.has(externalSystem),
      )
    ) {
      throw new Error("invalid target history");
    }

    if (!isCurrentScenario) {
      const cleanupResult = asRecord(previous.cleanup_result);
      if (
        previous.phase !== "restored" ||
        cleanupResult === null ||
        cleanupResult.preservedForManualCleanup !== false ||
        cleanupResult.restored !== true ||
        !completedScenarios.includes(previous.scenario) ||
        (targetRefs as TargetJournalRef[]).some(
          (target) => target.status !== "deleted",
        ) ||
        (targetHistory as TargetJournalRef[]).some(
          (target) => target.status !== "deleted",
        )
      ) {
        throw new Error("unrestored residue");
      }
    }

    // previous payload 자체가 완전한 restored 상태임을 먼저 판정한 뒤에만
    // 누적 이력을 합친다. 현재 scenario가 이미 보유한 key/status는 절대 되감지 않는다.
    for (const scenario of completedScenarios) {
      state.completedScenarios.add(scenario);
    }
    for (const externalSystem of externalSystems) {
      state.allExternalSystems.add(externalSystem);
    }
    for (const item of targetRefs as TargetJournalRef[]) {
      const key = targetJournalKey(item);
      const existing = state.allTargetRefs.get(key);
      const currentReplacementIntent =
        existing?.targetId === null &&
        ["put_intent", "put_replay_pending", "put_response_lost"].includes(
          existing.status,
        );
      if (
        existing !== undefined &&
        !currentReplacementIntent &&
        (!exactJson(existing.body, item.body) ||
          (existing.targetId !== null &&
            item.targetId !== null &&
            existing.targetId !== item.targetId))
      ) {
        throw new Error("invalid target history");
      }
      if (existing === undefined) state.allTargetRefs.set(key, item);
    }
    const knownHistory = new Set(
      state.targetHistory.map(
        (item) => `${targetJournalKey(item)}\u0000${item.targetId}`,
      ),
    );
    for (const item of targetHistory as TargetJournalRef[]) {
      const identity = `${targetJournalKey(item)}\u0000${item.targetId}`;
      if (!knownHistory.has(identity)) {
        knownHistory.add(identity);
        state.targetHistory.push(item);
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
    if (error instanceof Error && error.message === "invalid target history") {
      throw new Error("C7 durable cleanup journal의 target history가 손상되었습니다");
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
      const temporaryHandle = await open(temporary, "r");
      try {
        await temporaryHandle.sync();
      } finally {
        await temporaryHandle.close();
      }
      await rename(temporary, state.stateFile);
      await chmod(state.stateFile, 0o600);
      const stateHandle = await open(state.stateFile, "r");
      try {
        await stateHandle.sync();
      } finally {
        await stateHandle.close();
      }
      const directoryHandle = await open(directory, "r");
      try {
        await directoryHandle.sync();
      } finally {
        await directoryHandle.close();
      }
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
    timeoutMs?: number;
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
        return {
          body: parsed as T | null,
          entityTag: response.headers.get("etag"),
          status: response.status,
        };
      },
      {
        body: options.body,
        headers: options.headers ?? {},
        method: options.method ?? "GET",
        path,
        timeoutMs: options.timeoutMs ?? BROWSER_FETCH_TIMEOUT_MS,
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

function parseStrongEntityTag(
  entityTag: string,
  expectedTargetId?: string,
): number {
  const matched = STRONG_ENTITY_TAG_PATTERN.exec(entityTag);
  if (
    matched === null ||
    (expectedTargetId !== undefined && matched[1] !== expectedTargetId)
  ) {
    throw new Error("POI target strong entity_tag 계약 불일치");
  }
  const lockVersion = Number(matched[2]);
  if (!Number.isSafeInteger(lockVersion) || lockVersion <= 0) {
    throw new Error("POI target lock version 계약 불일치");
  }
  return lockVersion;
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
    metadata: { note: `C7 live E2E ${options.runId}` },
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
  entityTag: string,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  parseStrongEntityTag(entityTag);
  return browserFetch<PoiCacheTargetResponse>(
    page,
    targetPath(externalSystem, targetKey),
    { headers: { "If-Match": entityTag }, method: "DELETE" },
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

export function createCleanupState(
  scenario: CleanupScenario,
  runId: string,
): CleanupState {
  return {
    allExternalSystems: new Set(),
    allTargetRefs: new Map(),
    cleanupResult: null,
    completedScenarios: new Set(),
    externalSystems: new Set(),
    journalWrite: Promise.resolve(),
    runId,
    scenario,
    stateFile: cleanupStateFile(),
    targetHistory: [],
    targetStatuses: new Map(),
    targets: [],
  };
}

function preserveTargetHistory(
  state: CleanupState,
  target: TargetJournalRef,
): void {
  if (target.targetId === null) return;
  const identity = `${targetJournalKey(target)}\u0000${target.targetId}`;
  if (
    state.targetHistory.some(
      (item) =>
        `${targetJournalKey(item)}\u0000${item.targetId}` === identity,
    )
  ) {
    return;
  }
  state.targetHistory.push({ ...target });
}

function trackOwnedTarget(state: CleanupState, target: OwnedTarget): void {
  const index = state.targets.findIndex(
    (item) =>
      item.externalSystem === target.externalSystem &&
      item.targetKey === target.targetKey,
  );
  if (index >= 0) {
    const existing = state.targets[index];
    if (existing && existing.targetId !== target.targetId) {
      preserveTargetHistory(
        state,
        targetRefWithStatus(
          existing,
          state.targetStatuses.get(targetJournalKey(existing)) ?? "unknown",
        ),
      );
    }
    state.targets[index] = target;
  } else {
    state.targets.push(target);
  }
  state.externalSystems.add(target.externalSystem);
  state.allExternalSystems.add(target.externalSystem);
  setTargetStatus(state, target, "active");
}

function setTargetStatus(
  state: CleanupState,
  target: OwnedTarget,
  status: string,
): void {
  const key = targetJournalKey(target);
  state.targetStatuses.set(key, status);
  state.allTargetRefs.set(key, targetRefWithStatus(target, status));
}

function exactJson(left: unknown, right: unknown): boolean {
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical);
    const record = asRecord(value);
    if (record === null) return value;
    return Object.fromEntries(
      Object.entries(record)
        .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
        .map(([key, item]) => [key, canonical(item)]),
    );
  };
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function assertOwnedTargetRecord(
  response: PoiCacheTargetResponse,
  target: TargetRef,
  body: PoiCacheTargetUpsertRequest,
  expectedTargetId?: string,
): string {
  const record = response.data;
  if (
    !UUID_PATTERN.test(record.target_id) ||
    (expectedTargetId !== undefined && record.target_id !== expectedTargetId) ||
    record.external_system !== target.externalSystem ||
    record.target_key !== target.targetKey ||
    record.deleted_at !== null && record.deleted_at !== undefined ||
    record.coord.lon !== body.coord.lon ||
    record.coord.lat !== body.coord.lat ||
    record.coord_precision_digits !== body.coord_precision_digits ||
    record.radius_km !== body.radius_km ||
    record.name !== (body.name ?? null) ||
    record.scope_mode !== body.scope_mode ||
    record.update_enabled !== body.update_enabled ||
    record.refresh_policy !== body.refresh_policy ||
    !exactJson(record.provider_overrides, body.provider_overrides ?? {}) ||
    !exactJson(record.metadata, body.metadata ?? {})
  ) {
    throw new Error("POI target ownership/body identity 불일치 (values redacted)");
  }
  return record.target_id;
}

function requireOwnedTarget(
  state: CleanupState,
  target: TargetRef,
): OwnedTarget {
  const owned = state.targets.find(
    (item) =>
      item.externalSystem === target.externalSystem &&
      item.targetKey === target.targetKey,
  );
  if (!owned) {
    throw new Error("소유권이 증명되지 않은 POI target 조작을 차단했습니다");
  }
  return owned;
}

function requireResponseEntityIdentity(
  result: BrowserFetchResult<PoiCacheTargetResponse>,
  response: PoiCacheTargetResponse,
  expectedTargetId: string,
): { entityTag: string; lockVersion: number } {
  const entityTag = response.data.entity_tag;
  if (result.entityTag !== entityTag) {
    throw new Error("POI target ETag header/body 불일치");
  }
  return {
    entityTag,
    lockVersion: parseStrongEntityTag(entityTag, expectedTargetId),
  };
}

async function verifyOwnedTargetStillExact(
  page: Page,
  owned: OwnedTarget,
): Promise<
  | { status: "active"; entityTag: string; lockVersion: number }
  | { status: "deleted" }
> {
  const result = await getPoiTarget(
    page,
    owned.externalSystem,
    owned.targetKey,
  );
  if (result.status === 404) return { status: "deleted" };
  const current = requireBody(result, 200);
  assertOwnedTargetRecord(current, owned, owned.body, owned.targetId);
  const identity = requireResponseEntityIdentity(
    result,
    current,
    owned.targetId,
  );
  if (
    identity.entityTag !== owned.entityTag ||
    identity.lockVersion !== owned.lockVersion
  ) {
    throw new Error(
      "POI target가 소유권 획득 뒤 변경되어 삭제를 차단했습니다",
    );
  }
  return { status: "active", ...identity };
}

export async function putTrackedTarget(
  page: Page,
  state: CleanupState,
  target: TargetRef,
  body: PoiCacheTargetUpsertRequest,
): Promise<PoiCacheTargetResponse> {
  const before = await getPoiTarget(page, target.externalSystem, target.targetKey);
  if (before.status !== 404) {
    throw new Error(
      `POI target natural key가 이미 존재해 소유권 획득을 차단했습니다(status=${before.status})`,
    );
  }
  const key = targetJournalKey(target);
  const previousTarget = state.allTargetRefs.get(key);
  if (previousTarget?.targetId !== null && previousTarget?.targetId !== undefined) {
    if (previousTarget.status !== "deleted") {
      throw new Error(
        "POI target recreate는 삭제가 증명된 이전 identity만 교체할 수 있습니다",
      );
    }
    preserveTargetHistory(state, previousTarget);
  }
  state.externalSystems.add(target.externalSystem);
  state.allExternalSystems.add(target.externalSystem);
  state.allTargetRefs.set(key, {
    body,
    entityTag: null,
    externalSystem: target.externalSystem,
    lockVersion: null,
    status: "put_intent",
    targetId: null,
    targetKey: target.targetKey,
  });
  await writeDurableJournal(state, "target_put_intent");
  let result: BrowserFetchResult<PoiCacheTargetResponse>;
  try {
    result = await putPoiTarget(
      page,
      target.externalSystem,
      target.targetKey,
      body,
    );
  } catch {
    state.allTargetRefs.set(key, {
      ...state.allTargetRefs.get(key)!,
      status: "put_response_lost",
    });
    await writeDurableJournal(state, "target_put_response_lost");
    result = await getPoiTarget(page, target.externalSystem, target.targetKey);
    if (result.status === 404) {
      state.allTargetRefs.set(key, {
        ...state.allTargetRefs.get(key)!,
        status: "put_replay_pending",
      });
      await writeDurableJournal(state, "target_put_replay_pending");
      try {
        result = await putPoiTarget(
          page,
          target.externalSystem,
          target.targetKey,
          body,
        );
      } catch {
        state.allTargetRefs.set(key, {
          ...state.allTargetRefs.get(key)!,
          status: "put_response_lost",
        });
        await writeDurableJournal(state, "target_put_replay_response_lost");
        result = await getPoiTarget(
          page,
          target.externalSystem,
          target.targetKey,
        );
      }
    }
  }
  const response = requireBody(result, 200);
  const targetId = assertOwnedTargetRecord(response, target, body);
  const identity = requireResponseEntityIdentity(result, response, targetId);
  if (
    previousTarget?.targetId !== null &&
    previousTarget?.targetId !== undefined &&
    (targetId === previousTarget.targetId ||
      identity.entityTag === previousTarget.entityTag ||
      identity.lockVersion !== 1 ||
      !state.targetHistory.some(
        (item) =>
          targetJournalKey(item) === key &&
          item.targetId === previousTarget.targetId &&
          item.status === "deleted",
      ))
  ) {
    throw new Error(
      "POI target recreate의 새 UUID/strong ETag/version/history 계약 불일치",
    );
  }
  const owned: OwnedTarget = {
    ...target,
    body,
    entityTag: identity.entityTag,
    lockVersion: identity.lockVersion,
    targetId,
  };
  trackOwnedTarget(state, owned);
  await writeDurableJournal(state, "target_put_observed");
  if (response.data.created_at !== response.data.updated_at) {
    throw new Error("POI target가 신규 insert가 아니어서 소유권 획득을 차단했습니다");
  }
  const exactResult = await getPoiTarget(
    page,
    target.externalSystem,
    target.targetKey,
  );
  const exactRead = requireBody(exactResult, 200);
  assertOwnedTargetRecord(exactRead, target, body, targetId);
  const exactIdentity = requireResponseEntityIdentity(
    exactResult,
    exactRead,
    targetId,
  );
  if (
    exactIdentity.entityTag !== owned.entityTag ||
    exactIdentity.lockVersion !== owned.lockVersion
  ) {
    throw new Error("POI target PUT 직후 GET version이 변경되었습니다");
  }
  await writeDurableJournal(state, "target_active");
  return response;
}

export async function deleteTrackedTarget(
  page: Page,
  state: CleanupState,
  target: TargetRef,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  const owned = requireOwnedTarget(state, target);
  const before = await verifyOwnedTargetStillExact(page, owned);
  if (before.status === "deleted") {
    setTargetStatus(state, owned, "deleted");
    await writeDurableJournal(state, "target_delete_observed");
    return { body: null, entityTag: null, status: 404 };
  }
  setTargetStatus(state, owned, "delete_pending");
  await writeDurableJournal(state, "target_delete_pending");
  const result = await deletePoiTarget(
    page,
    target.externalSystem,
    target.targetKey,
    before.entityTag,
  );
  if (result.status === 200 && result.body !== null) {
    if (result.body.data.target_id !== owned.targetId) {
      throw new Error("POI target delete 응답 UUID ownership 불일치");
    }
    const deletedIdentity = requireResponseEntityIdentity(
      result,
      result.body,
      owned.targetId,
    );
    if (deletedIdentity.lockVersion <= before.lockVersion) {
      throw new Error("POI target delete lock version이 전진하지 않았습니다");
    }
    owned.entityTag = deletedIdentity.entityTag;
    owned.lockVersion = deletedIdentity.lockVersion;
    setTargetStatus(state, owned, "deleted");
  } else if (result.status === 404) {
    setTargetStatus(state, owned, "deleted");
  } else if (result.status === 412) {
    setTargetStatus(state, owned, "delete_conflict");
    await writeDurableJournal(state, "target_delete_conflict");
    throw new Error(
      "POI target DELETE가 412를 반환해 concurrent update 삭제를 차단했습니다",
    );
  }
  await writeDurableJournal(state, "target_delete_observed");
  return result;
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

async function recoverUnresolvedTargetIntents(
  page: Page,
  state: CleanupState,
): Promise<{ complete: boolean; issues: CleanupIssue[] }> {
  const issues: CleanupIssue[] = [];
  const unresolved = [...state.allTargetRefs.values()].filter(
    (target) =>
      state.externalSystems.has(target.externalSystem) &&
      ["put_intent", "put_replay_pending", "put_response_lost"].includes(
        target.status,
      ),
  );
  for (const intent of unresolved) {
    try {
      const result = await getPoiTarget(
        page,
        intent.externalSystem,
        intent.targetKey,
      );
      if (result.status === 404) {
        state.allTargetRefs.set(targetJournalKey(intent), {
          ...intent,
          status: "absent_unowned",
        });
        await writeDurableJournal(state, "target_intent_absent_unowned");
        issues.push({
          http_status: 404,
          kind: "target_intent_recovery",
          resource: `${intent.externalSystem}/${intent.targetKey}`,
        });
        continue;
      }
      const response = requireBody(result, 200);
      const targetId = assertOwnedTargetRecord(response, intent, intent.body);
      const identity = requireResponseEntityIdentity(result, response, targetId);
      if (response.data.created_at !== response.data.updated_at) {
        throw new Error(
          "response-lost POI target가 신규 insert identity가 아닙니다",
        );
      }
      trackOwnedTarget(state, {
        ...intent,
        body: intent.body,
        entityTag: identity.entityTag,
        lockVersion: identity.lockVersion,
        targetId,
      });
      await writeDurableJournal(state, "target_intent_rediscovered");
    } catch {
      issues.push({
        kind: "target_intent_recovery",
        resource: `${intent.externalSystem}/${intent.targetKey}`,
      });
    }
  }
  return { complete: issues.length === 0, issues };
}

async function cleanupResources(
  page: Page,
  state: CleanupState,
): Promise<CleanupExecution> {
  const issues: CleanupIssue[] = [];
  const targetRecovery = await recoverUnresolvedTargetIntents(page, state);
  issues.push(...targetRecovery.issues);

  // 응답 유실 intent 중 하나라도 정체를 증명하지 못하면 어떤 target도 삭제하지 않는다.
  const canDeleteTargets = targetRecovery.complete;
  if (canDeleteTargets) {
    const targets = [...state.targets].reverse();
    const batchSize = 3;
    for (let offset = 0; offset < targets.length; offset += batchSize) {
      const batch = targets.slice(offset, offset + batchSize);
      for (const target of batch) {
        setTargetStatus(state, target, "ownership_recheck_pending");
      }
      await writeDurableJournal(state, "cleanup_target_ownership_recheck");
      const deletions = await Promise.allSettled(
        batch.map(async (target) => {
          const ownership = await verifyOwnedTargetStillExact(page, target);
          if (ownership.status === "deleted") {
            return {
              result: { body: null, entityTag: null, status: 404 },
              target,
            };
          }
          setTargetStatus(state, target, "delete_pending");
          const result = await deletePoiTarget(
            page,
            target.externalSystem,
            target.targetKey,
            ownership.entityTag,
          );
          if (
            result.status === 200 &&
            result.body !== null &&
            result.body.data.target_id !== target.targetId
          ) {
            throw new Error("cleanup target delete UUID ownership 불일치");
          }
          if (result.status === 200 && result.body !== null) {
            const deletedIdentity = requireResponseEntityIdentity(
              result,
              result.body,
              target.targetId,
            );
            if (deletedIdentity.lockVersion <= ownership.lockVersion) {
              throw new Error(
                "cleanup target delete lock version이 전진하지 않았습니다",
              );
            }
            target.entityTag = deletedIdentity.entityTag;
            target.lockVersion = deletedIdentity.lockVersion;
          }
          if (result.status === 412) {
            setTargetStatus(state, target, "delete_conflict");
            await writeDurableJournal(state, "cleanup_target_delete_conflict");
            throw new Error(
              "cleanup target DELETE가 412를 반환해 concurrent update 삭제를 차단했습니다",
            );
          }
          return { result, target };
        }),
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
          setTargetStatus(state, target, "deleted");
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
    preservedForManualCleanup,
    restored: !preservedForManualCleanup,
  };
  state.cleanupResult = result;
  await writeDurableJournal(
    state,
    result.restored ? "restored" : "cleanup_blocked",
  );
  return { issues, result };
}

export async function withC7Cleanup(
  page: Page,
  testInfo: TestInfo,
  state: CleanupState,
  body: () => Promise<void>,
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
      cleanup = await cleanupResources(page, state);
    } catch {
      const issues: CleanupIssue[] = [
        { kind: "unexpected_exception", resource: "cleanup_boundary" },
      ];
      state.cleanupResult = {
        preservedForManualCleanup: true,
        restored: false,
      };
      await writeDurableJournal(state, "cleanup_boundary_failed").catch(
        () => undefined,
      );
      cleanup = {
        issues,
        result: state.cleanupResult,
      };
    }
    if (cleanup === null) {
      throw new Error("C7 cleanup 결과가 생성되지 않았습니다");
    }
    if (cleanup.issues.length > 0) {
      testInfo.annotations.push({
        type: "cleanup-error",
        description: `C7 cleanup issue ${cleanup.issues.length}건; root-owned journal 확인`,
      });
      if (primaryError === undefined) {
        throw new Error(
          `C7 cleanup 실패 ${cleanup.issues.length}건; target 보존 여부는 root-owned journal 확인`,
        );
      }
    }
  }
  return cleanup?.result ?? {
    preservedForManualCleanup: true,
    restored: false,
  };
}
