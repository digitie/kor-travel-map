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

import type { Page, Response, Route, TestInfo } from "@playwright/test";

import type { components } from "../../src/api/types";

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
export type OpsDatasetsGridResponse =
  components["schemas"]["OpsDatasetsGridResponse"];
export type PipelineCancellationResponse =
  components["schemas"]["PipelineCancellationResponse"];

export type TargetRef = { externalSystem: string; targetKey: string };
type OwnedTarget = TargetRef & {
  body: PoiCacheTargetUpsertRequest;
  entityTag: string;
  lockVersion: number;
  targetId: string;
};
export type CleanupResult = {
  allRequestsTerminal: boolean;
  preservedForManualCleanup: boolean;
  restored: boolean;
};
export type CleanupScenario = "active" | "empty" | "cap" | "invalidation";
type TrackedIdempotencyEntries = Map<
  string,
  {
    body: FeatureUpdateRequestCreateRequest;
    requestId: string | null;
    status: string;
  }
>;
export type CleanupState = {
  allIdempotencyEntries: TrackedIdempotencyEntries;
  allRequestIds: Set<string>;
  allRequestTerminalStatuses: Map<string, string>;
  cleanupResult: CleanupResult | null;
  completedScenarios: Set<CleanupScenario>;
  externalSystems: Set<string>;
  allExternalSystems: Set<string>;
  idempotencyEntries: TrackedIdempotencyEntries;
  journalWrite: Promise<void>;
  requestIds: Set<string>;
  requestTerminalStatuses: Map<string, string>;
  runId: string;
  scenario: CleanupScenario;
  scopeStateCount: number;
  stateFile: string;
  targetStatuses: Map<string, string>;
  targetHistory: TargetJournalRef[];
  targets: OwnedTarget[];
  allTargetRefs: Map<string, TargetJournalRef>;
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
    | "request_detail"
    | "request_cancel"
    | "request_terminal_timeout"
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

// src/kortravelmap/providers/kma.py와 schedules.py의 canonical identity.
export const KMA_PROVIDER = "python-kma-api" as const;
export const KMA_DATASET_KEY = "kma_ultra_short_nowcast" as const;
export const KMA_SAFE_DAGSTER_JOB =
  "feature_update_request_worker" as const;
export const QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor" as const;

export const REQUEST_TERMINAL_TIMEOUT = 8 * 60 * 1000;
export const CLEANUP_TERMINAL_TIMEOUT = 90 * 1000;
export const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"]);

const POI_TARGETS_PATH = "/v1/admin/poi-cache-targets";
const PIPELINE_REQUESTS_PATH = "/v1/ops/pipeline/requests";
const FORBIDDEN_PROVIDER_PATTERN = /opinet/i;
const BROWSER_FETCH_TIMEOUT_MS = 30_000;
// dataset detail은 per-scope 실행/이벤트 이력을 집계하므로 대량 이력 상황에서
// 기본 timeout보다 여유가 필요하다(서버측 scoped 쿼리 최적화의 안전 마진).
export const DATASET_DETAIL_FETCH_TIMEOUT_MS = 60_000;
const DAGSTER_GRAPHQL_TIMEOUT_MS = 15_000;
const DAGSTER_RUN_SETTLEMENT_TIMEOUT_MS = 60_000;
const OWNED_TARGET_PAGE_SIZE = 500;
const OWNED_TARGET_SET_LIMIT = 501;
const OWNED_TARGET_PAGE_LIMIT = 2;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const bootstrappedPages = new WeakSet<Page>();

const KMA_DAGSTER_JOB_DISCOVERY_QUERY = `
query C7KmaWorkerJobDiscovery {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        pipelines { name isJob }
      }
    }
  }
}
`;

const KMA_DAGSTER_RUN_IDENTITY_QUERY = `
query C7KmaWorkerRunIdentity($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
      runId
      jobName
      status
      tags { key value }
    }
  }
}
`;

const FEATURE_UPDATE_REQUEST_ID_TAG =
  "kor_travel_map.feature_update_request_id";
const FEATURE_UPDATE_REQUEST_GENERATION_TAG =
  "kor_travel_map.feature_update_request_generation";
const FEATURE_UPDATE_SCOPE_TYPE_TAG =
  "kor_travel_map.feature_update_scope_type";
const DAGSTER_SENSOR_NAME_TAG = "dagster/sensor_name";
const DAGSTER_TERMINAL_STATUSES = new Set([
  "SUCCESS",
  "FAILURE",
  "CANCELED",
]);

type GraphqlEnvelope = {
  data?: unknown;
  errors?: unknown;
};

type DurableCleanupJournal = {
  cleanup_result: CleanupResult | null;
  completed_scenarios: CleanupScenario[];
  external_systems: string[];
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
  target_refs: TargetJournalRef[];
  target_history: TargetJournalRef[];
  updated_at: string;
  version: 3;
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STRONG_ENTITY_TAG_PATTERN =
  /^"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):([1-9][0-9]*)"$/;

async function boundedWait<T>(
  promise: Promise<T>,
  operation: string,
  timeoutMs = BROWSER_FETCH_TIMEOUT_MS,
): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  try {
    return await new Promise<T>((resolve, reject) => {
      timeout = setTimeout(
        () => reject(new Error(`${operation} 제한 시간 초과`)),
        timeoutMs,
      );
      promise.then(resolve, reject);
    });
  } finally {
    if (timeout !== null) clearTimeout(timeout);
  }
}

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
  // ADR-088 triple identity는 카탈로그가 발급하는 런타임 값이라 상수로 박을 수 없다.
  // KMA mutation plan을 동기적으로 조립하는 헬퍼들이 쓸 수 있도록 bootstrap에서
  // 미리 푼다. 여기서 실패해도 bootstrap 자체는 막지 않는다 — KMA identity를
  // 실제로 요구하는 헬퍼가 requireKmaDatasetIdentity()로 명시적으로 실패한다
  // (KMA를 쓰지 않는 C7 read/schedule spec 보호).
  await resolveKmaDatasetIdentity(page).catch(() => undefined);
}

/** ADR-088 exact membership triple 중 dataset이 발급하는 두 값. */
export type KmaDatasetIdentity = {
  operationKey: string;
  providerDatasetId: number;
};

let resolvedKmaDatasetIdentity: KmaDatasetIdentity | null = null;

/**
 * `/v1/ops/datasets` 그리드에서 canonical KMA 행을 찾아 `provider_dataset_id`와
 * `operation_key`를 푼다.
 *
 * 그리드 1행의 identity는 `provider_dataset_id × sync_scope × operation_key`라
 * external_system scope마다 행이 늘어난다. dataset identity는
 * `(provider_dataset_id, operation_key)`로 접고, 형제 operation이 둘 이상이면
 * C7 mutation이 어느 operation을 실행하는지 단정할 수 없으므로 실패시킨다.
 */
export async function resolveKmaDatasetIdentity(
  page: Page,
): Promise<KmaDatasetIdentity> {
  if (resolvedKmaDatasetIdentity !== null) return resolvedKmaDatasetIdentity;
  const grid = requireBody(
    await browserFetch<OpsDatasetsGridResponse>(page, "/v1/ops/datasets", {
      timeoutMs: DATASET_DETAIL_FETCH_TIMEOUT_MS,
    }),
    200,
  );
  const unique = new Map<string, KmaDatasetIdentity>();
  for (const row of grid.data.items) {
    if (
      row.provider !== KMA_PROVIDER ||
      row.dataset_key !== KMA_DATASET_KEY ||
      row.operation_key === null
    ) {
      continue;
    }
    unique.set(`${row.provider_dataset_id}\u0000${row.operation_key}`, {
      operationKey: row.operation_key,
      providerDatasetId: row.provider_dataset_id,
    });
  }
  const identities = [...unique.values()];
  if (identities.length !== 1) {
    throw new Error(
      "C7 live E2E는 KMA dataset의 단일 canonical (provider_dataset_id, operation_key) identity를 요구합니다",
    );
  }
  resolvedKmaDatasetIdentity = identities[0];
  return identities[0];
}

/** 이미 해석된 KMA triple identity를 동기 plan 조립/가드에서 읽는다. */
function requireKmaDatasetIdentity(): KmaDatasetIdentity {
  if (resolvedKmaDatasetIdentity === null) {
    throw new Error(
      "KMA provider_dataset_id/operation_key가 아직 해석되지 않았습니다 — bootstrapC7SameOriginPage 또는 resolveKmaDatasetIdentity를 먼저 호출하세요",
    );
  }
  return resolvedKmaDatasetIdentity;
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
  const allTargetRefs = new Map(state.allTargetRefs);
  const allIdempotencyEntries = new Map(state.allIdempotencyEntries);
  for (const [idempotencyKey, entry] of state.idempotencyEntries) {
    allIdempotencyEntries.set(idempotencyKey, entry);
  }
  const allRequestIds = new Set([
    ...state.allRequestIds,
    ...state.requestIds,
  ]);
  const allRequestTerminalStatuses = new Map(
    state.allRequestTerminalStatuses,
  );
  for (const [requestId, status] of state.requestTerminalStatuses) {
    allRequestTerminalStatuses.set(requestId, status);
  }
  return {
    cleanup_result: state.cleanupResult,
    completed_scenarios: [...completedScenarios].sort(),
    external_systems: [...state.allExternalSystems].sort(),
    idempotency_entries: [...allIdempotencyEntries.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([idempotencyKey, entry]) => ({
        body: entry.body,
        idempotency_key: idempotencyKey,
        request_id: entry.requestId,
        status: entry.status,
      })),
    phase,
    request_ids: [...allRequestIds].sort(),
    request_terminal_statuses: Object.fromEntries(
      [...allRequestTerminalStatuses.entries()].sort(
        ([left], [right]) => left.localeCompare(right),
      ),
    ),
    run_id: state.runId,
    scenario: state.scenario,
    scope_state_count: state.scopeStateCount,
    target_refs: [...allTargetRefs.values()].sort((left, right) =>
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
    version: 3,
  };
}

function isCleanupScenario(value: unknown): value is CleanupScenario {
  return ["active", "empty", "cap", "invalidation"].includes(String(value));
}

async function mergePreviousJournal(state: CleanupState): Promise<void> {
  try {
    const previous = JSON.parse(await readFile(state.stateFile, "utf8")) as {
      cleanup_result?: unknown;
      completed_scenarios?: unknown;
      external_systems?: unknown;
      idempotency_entries?: unknown;
      phase?: unknown;
      request_ids?: unknown;
      request_terminal_statuses?: unknown;
      run_id?: unknown;
      scenario?: unknown;
      target_refs?: unknown;
      target_history?: unknown;
      version?: unknown;
    };
    const isOrchestratorPlaceholder =
      previous.phase === "restored" &&
      previous.run_id === "__orchestrator_pending__" &&
      previous.version === 3;
    const isCurrentScenario =
      previous.run_id === state.runId && previous.scenario === state.scenario;
    if (
      !isOrchestratorPlaceholder &&
      (previous.version !== 3 ||
        typeof previous.run_id !== "string" ||
        previous.run_id.length === 0 ||
        !isCleanupScenario(previous.scenario) ||
        !Array.isArray(previous.completed_scenarios) ||
        !Array.isArray(previous.external_systems) ||
        !Array.isArray(previous.idempotency_entries) ||
        !Array.isArray(previous.request_ids) ||
        asRecord(previous.request_terminal_statuses) === null ||
        !Array.isArray(previous.target_refs) ||
        !Array.isArray(previous.target_history))
    ) {
      throw new Error("invalid target history");
    }
    if (
      !isOrchestratorPlaceholder &&
      previous.phase !== "restored" &&
      !isCurrentScenario
    ) {
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
    const externalSystems = previous.external_systems;
    if (
      externalSystems !== undefined &&
      (!Array.isArray(externalSystems) ||
        !externalSystems.every(
          (value): value is string => typeof value === "string" && value.length > 0,
        ))
    ) {
      throw new Error("invalid target history");
    }
    const targetRefs = previous.target_refs;
    if (
      targetRefs !== undefined &&
      (!Array.isArray(targetRefs) ||
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
        }))
    ) {
      throw new Error("invalid target history");
    }
    if (Array.isArray(targetRefs)) {
      const seenTargetKeys = new Set<string>();
      for (const value of targetRefs) {
        const item = value as TargetJournalRef;
        const key = targetJournalKey(item);
        if (seenTargetKeys.has(key)) {
          throw new Error("invalid target history");
        }
        seenTargetKeys.add(key);
      }
    }
    const targetHistory = previous.target_history;
    if (
      targetHistory !== undefined &&
      (!Array.isArray(targetHistory) ||
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
        }))
    ) {
      throw new Error("invalid target history");
    }
    if (
      Array.isArray(targetHistory) &&
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
      (targetRefs as TargetJournalRef[] | undefined)?.map(
        (item) => item.externalSystem,
      ) ?? [],
    );
    if (
      Array.isArray(externalSystems) &&
      (externalSystems.length !== targetExternalSystems.size ||
        externalSystems.some(
          (externalSystem) => !targetExternalSystems.has(externalSystem),
        ))
    ) {
      throw new Error("invalid target history");
    }

    const requestIds = previous.request_ids;
    if (
      requestIds !== undefined &&
      (!Array.isArray(requestIds) ||
        !requestIds.every(
          (value): value is string =>
            typeof value === "string" && UUID_PATTERN.test(value),
        ) ||
        new Set(requestIds).size !== requestIds.length)
    ) {
      throw new Error("invalid request history");
    }
    const terminalStatuses = asRecord(previous.request_terminal_statuses);
    if (
      previous.request_terminal_statuses !== undefined &&
      (terminalStatuses === null ||
        Object.entries(terminalStatuses).some(
          ([requestId, status]) =>
            !UUID_PATTERN.test(requestId) || typeof status !== "string",
        ))
    ) {
      throw new Error("invalid request history");
    }
    if (terminalStatuses !== null) {
      for (const requestId of Object.keys(terminalStatuses)) {
        if (!(requestIds as string[] | undefined)?.includes(requestId)) {
          throw new Error("invalid request history");
        }
      }
    }

    const idempotencyEntries = previous.idempotency_entries;
    if (
      idempotencyEntries !== undefined &&
      (!Array.isArray(idempotencyEntries) ||
        !idempotencyEntries.every((value) => {
          const item = asRecord(value);
          return (
            item !== null &&
            typeof item.idempotency_key === "string" &&
            UUID_PATTERN.test(item.idempotency_key) &&
            asRecord(item.body) !== null &&
            (item.request_id === null ||
              (typeof item.request_id === "string" &&
                UUID_PATTERN.test(item.request_id))) &&
            typeof item.status === "string" &&
            item.status.length > 0
          );
        }))
    ) {
      throw new Error("invalid request history");
    }
    if (Array.isArray(idempotencyEntries)) {
      const seenIdempotencyKeys = new Set<string>();
      for (const value of idempotencyEntries) {
        const item = value as DurableCleanupJournal["idempotency_entries"][number];
        if (
          seenIdempotencyKeys.has(item.idempotency_key) ||
          (item.request_id !== null &&
            !(requestIds as string[] | undefined)?.includes(item.request_id))
        ) {
          throw new Error("invalid request history");
        }
        seenIdempotencyKeys.add(item.idempotency_key);
      }
    }

    if (!isOrchestratorPlaceholder && !isCurrentScenario) {
      const cleanupResult = asRecord(previous.cleanup_result);
      const scenario = previous.scenario as CleanupScenario;
      const previousRequestIds = requestIds as string[];
      const previousTerminalStatuses = terminalStatuses as Record<
        string,
        unknown
      >;
      if (
        previous.phase !== "restored" ||
        cleanupResult === null ||
        cleanupResult.allRequestsTerminal !== true ||
        cleanupResult.preservedForManualCleanup !== false ||
        cleanupResult.restored !== true ||
        !(completedScenarios as CleanupScenario[]).includes(scenario) ||
        (targetRefs as TargetJournalRef[]).some(
          (target) => target.status !== "deleted",
        ) ||
        (targetHistory as TargetJournalRef[]).some(
          (target) => target.status !== "deleted",
        ) ||
        previousRequestIds.some(
          (requestId) =>
            !TERMINAL_STATUSES.has(
              String(previousTerminalStatuses[requestId] ?? ""),
            ),
        )
      ) {
        throw new Error("unrestored residue");
      }
    }

    // previous payload 자체가 완전한 restored 상태임을 먼저 판정한 뒤에만
    // 누적 이력을 합친다. 현재 scenario가 이미 보유한 key/status는 절대 되감지 않는다.
    for (const scenario of
      (completedScenarios as CleanupScenario[] | undefined) ?? []) {
      state.completedScenarios.add(scenario);
    }
    for (const externalSystem of
      (externalSystems as string[] | undefined) ?? []) {
      state.allExternalSystems.add(externalSystem);
    }
    for (const item of (targetRefs as TargetJournalRef[] | undefined) ?? []) {
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
    for (const item of (targetHistory as TargetJournalRef[] | undefined) ?? []) {
      const identity = `${targetJournalKey(item)}\u0000${item.targetId}`;
      if (!knownHistory.has(identity)) {
        knownHistory.add(identity);
        state.targetHistory.push(item);
      }
    }
    for (const requestId of (requestIds as string[] | undefined) ?? []) {
      state.allRequestIds.add(requestId);
    }
    for (const [requestId, status] of Object.entries(terminalStatuses ?? {})) {
      const current = state.requestTerminalStatuses.get(requestId);
      if (
        current === undefined &&
        !state.allRequestTerminalStatuses.has(requestId)
      ) {
        state.allRequestTerminalStatuses.set(requestId, String(status));
      }
    }
    for (const value of (idempotencyEntries as
      | DurableCleanupJournal["idempotency_entries"]
      | undefined) ?? []) {
      const existing =
        state.idempotencyEntries.get(value.idempotency_key) ??
        state.allIdempotencyEntries.get(value.idempotency_key);
      if (
        existing !== undefined &&
        (!exactJson(existing.body, value.body) ||
          (existing.requestId !== null &&
            value.request_id !== null &&
            existing.requestId !== value.request_id))
      ) {
        throw new Error("invalid request history");
      }
      if (
        !state.idempotencyEntries.has(value.idempotency_key) &&
        !state.allIdempotencyEntries.has(value.idempotency_key)
      ) {
        state.allIdempotencyEntries.set(value.idempotency_key, {
          body: value.body,
          requestId: value.request_id,
          status: value.status,
        });
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
    if (error instanceof Error && error.message === "invalid request history") {
      throw new Error("C7 durable cleanup journal의 request history가 손상되었습니다");
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

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function dagsterGraphqlEndpoint(): URL {
  const raw = process.env.E2E_DAGSTER_URL;
  const expectedHash = process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256;
  if (!raw || !expectedHash || !SHA256_PATTERN.test(expectedHash)) {
    throw new Error(
      "C7 Dagster GraphQL endpoint/hash attestation이 필요합니다 (values redacted)",
    );
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("C7 Dagster GraphQL endpoint가 안전하지 않습니다");
  }
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error("C7 Dagster GraphQL endpoint가 안전하지 않습니다");
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  url.pathname = pathname.endsWith("/graphql")
    ? pathname
    : `${pathname}/graphql`;
  if (sha256(url.href) !== expectedHash) {
    throw new Error(
      "C7 Dagster GraphQL endpoint attestation이 불일치합니다 (values redacted)",
    );
  }
  return url;
}

async function postDagsterGraphql(
  query: string,
  variables: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  let response: globalThis.Response;
  try {
    response = await fetch(dagsterGraphqlEndpoint(), {
      body: JSON.stringify({ query, variables }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
      redirect: "error",
      signal: AbortSignal.timeout(DAGSTER_GRAPHQL_TIMEOUT_MS),
    });
  } catch {
    throw new Error("C7 Dagster GraphQL transport가 실패했습니다 (values redacted)");
  }
  if (!response.ok) {
    throw new Error("C7 Dagster GraphQL HTTP 계약이 실패했습니다 (values redacted)");
  }
  let envelope: GraphqlEnvelope;
  try {
    envelope = (await response.json()) as GraphqlEnvelope;
  } catch {
    throw new Error("C7 Dagster GraphQL JSON 계약이 실패했습니다 (values redacted)");
  }
  if (Array.isArray(envelope.errors) && envelope.errors.length > 0) {
    throw new Error("C7 Dagster GraphQL 응답에 오류가 있습니다 (values redacted)");
  }
  const data = asRecord(envelope.data);
  if (data === null) {
    throw new Error("C7 Dagster GraphQL data 계약이 실패했습니다 (values redacted)");
  }
  return data;
}

/** KMA destructive mutation 전에 실제 queue worker job 정의를 단 하나로 결박한다. */
export async function assertKmaDagsterWorkerJobDefinition(): Promise<void> {
  const data = await postDagsterGraphql(KMA_DAGSTER_JOB_DISCOVERY_QUERY, {});
  const root = asRecord(data.repositoriesOrError);
  if (root?.__typename !== "RepositoryConnection") {
    throw new Error("C7 Dagster repository 조회 계약이 실패했습니다 (values redacted)");
  }
  const matches = asArray(root.nodes).flatMap((nodeValue) => {
    const node = asRecord(nodeValue);
    return asArray(node?.pipelines)
      .map(asRecord)
      .filter((pipeline) => pipeline?.name === KMA_SAFE_DAGSTER_JOB);
  });
  if (matches.length !== 1 || matches[0]?.isJob !== true) {
    throw new Error(
      "C7 Dagster queue worker job cardinality/isJob 계약이 실패했습니다 (values redacted)",
    );
  }
}

function dagsterRunTags(value: unknown): Map<string, string> {
  const tags = new Map<string, string>();
  for (const rawTag of asArray(value)) {
    const tag = asRecord(rawTag);
    if (
      typeof tag?.key !== "string" ||
      !tag.key ||
      typeof tag.value !== "string" ||
      tags.has(tag.key)
    ) {
      throw new Error("C7 Dagster run tag 계약이 실패했습니다 (values redacted)");
    }
    tags.set(tag.key, tag.value);
  }
  return tags;
}

function expectedDagsterTerminalStatus(status: string): string {
  if (status === "done") return "SUCCESS";
  if (status === "failed") return "FAILURE";
  if (status === "cancelled") return "CANCELED";
  throw new Error("C7 request terminal status 계약이 실패했습니다");
}

async function assertTerminalDagsterRunIdentity(
  page: Page,
  detail: PipelineExecutionDetailResponse,
): Promise<void> {
  const identity = requireKmaDatasetIdentity();
  const execution = detail.data.execution;
  const updateRequest = detail.data.update_request;
  const runId = execution.dagster_run_id;
  if (
    !runId ||
    updateRequest === null ||
    updateRequest.request_id !== execution.id ||
    updateRequest.dagster_run_id !== runId ||
    !Number.isSafeInteger(updateRequest.generation) ||
    updateRequest.generation <= 0 ||
    updateRequest.scope.type !== "provider_dataset" ||
    updateRequest.scope.provider_dataset_id !== identity.providerDatasetId ||
    updateRequest.scope.operation_key !== identity.operationKey
  ) {
    throw new Error(
      "C7 terminal request/Dagster owner identity 계약이 실패했습니다 (values redacted)",
    );
  }
  const expectedStatus = expectedDagsterTerminalStatus(execution.status);
  const deadline = Date.now() + DAGSTER_RUN_SETTLEMENT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const data = await postDagsterGraphql(KMA_DAGSTER_RUN_IDENTITY_QUERY, {
      runId,
    });
    const run = asRecord(data.runOrError);
    if (run?.__typename !== "Run") {
      await page.waitForTimeout(1_000);
      continue;
    }
    const tags = dagsterRunTags(run.tags);
    const sensorName = tags.get(DAGSTER_SENSOR_NAME_TAG);
    if (
      run.runId !== runId ||
      run.jobName !== KMA_SAFE_DAGSTER_JOB ||
      tags.get(FEATURE_UPDATE_REQUEST_ID_TAG) !== updateRequest.request_id ||
      tags.get(FEATURE_UPDATE_REQUEST_GENERATION_TAG) !==
        String(updateRequest.generation) ||
      tags.get(FEATURE_UPDATE_SCOPE_TYPE_TAG) !== "provider_dataset" ||
      sensorName !== QUEUE_SENSOR_NAME
    ) {
      throw new Error(
        "C7 Dagster run job/tag identity 계약이 실패했습니다 (values redacted)",
      );
    }
    if (run.status === expectedStatus) return;
    if (
      typeof run.status !== "string" ||
      DAGSTER_TERMINAL_STATUSES.has(run.status)
    ) {
      throw new Error(
        "C7 Dagster run terminal status 계약이 실패했습니다 (values redacted)",
      );
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error(
    "C7 Dagster run terminal settlement 제한 시간을 초과했습니다 (values redacted)",
  );
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
  entityTag: string,
): Promise<BrowserFetchResult<PoiCacheTargetResponse>> {
  parseStrongEntityTag(entityTag);
  return browserFetch<PoiCacheTargetResponse>(
    page,
    targetPath(externalSystem, targetKey),
    { headers: { "If-Match": entityTag }, method: "DELETE" },
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
  const identity = requireKmaDatasetIdentity();
  const body: FeatureUpdateRequestCreateRequest = {
    scope: {
      type: "provider_dataset",
      provider_dataset_id: identity.providerDatasetId,
      operation_key: identity.operationKey,
      sync_scope: `external_system:${externalSystem}`,
    },
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
  const identity = requireKmaDatasetIdentity();
  const scope = body.scope;
  if (
    scope.type !== "provider_dataset" ||
    scope.provider_dataset_id !== identity.providerDatasetId ||
    scope.operation_key !== identity.operationKey ||
    !scope.sync_scope.startsWith("external_system:")
  ) {
    throw new Error(
      "C7 live E2E mutation은 canonical KMA external_system scope만 허용합니다.",
    );
  }
}

function kmaExternalSystem(
  body: FeatureUpdateRequestCreateRequest | FeatureUpdateRequestPreviewRequest,
): string {
  assertKmaOnlyPlan(body);
  const syncScope =
    "sync_scope" in body.scope ? body.scope.sync_scope : undefined;
  if (!syncScope?.startsWith("external_system:")) {
    throw new Error("KMA request external_system scope가 없습니다");
  }
  const externalSystem = syncScope.slice("external_system:".length);
  if (!externalSystem) {
    throw new Error("KMA request external_system이 비어 있습니다");
  }
  return externalSystem;
}

export async function previewKmaRequest(
  page: Page,
  body: FeatureUpdateRequestPreviewRequest,
): Promise<BrowserFetchResult<FeatureUpdateRequestPreviewResponse>> {
  assertKmaOnlyPlan(body);
  const result = await browserFetch<FeatureUpdateRequestPreviewResponse>(
    page,
    `${PIPELINE_REQUESTS_PATH}/preview`,
    { method: "POST", body },
  );
  const response = requireBody(result, 200);
  assertExactKmaPreviewBody(response, body);
  return result;
}

function assertOnlyKmaProviderObjects(value: unknown, context: string): void {
  if (Array.isArray(value)) {
    for (const item of value) assertOnlyKmaProviderObjects(item, context);
    return;
  }
  const record = asRecord(value);
  if (record === null) return;
  if (
    "provider" in record &&
    (record.provider !== KMA_PROVIDER ||
      ("dataset_key" in record && record.dataset_key !== KMA_DATASET_KEY))
  ) {
    throw new Error(`${context}에 KMA 외 provider/dataset이 포함되었습니다`);
  }
  for (const item of Object.values(record)) {
    assertOnlyKmaProviderObjects(item, context);
  }
}

function assertExactKmaPreviewBody(
  response: FeatureUpdateRequestPreviewResponse,
  expected: FeatureUpdateRequestPreviewRequest,
): void {
  const data = response.data;
  assertKmaOnlyPlan(expected);
  const identity = requireKmaDatasetIdentity();
  const expectedEffectiveSyncScope =
    expected.scope.type === "provider_dataset"
      ? expected.scope.sync_scope
      : undefined;
  const responseScope = data.scope;
  const matchedScope = asRecord(data.matched_scope);
  if (
    data.result_kind !== "preview" ||
    data.scope_type !== "provider_dataset" ||
    !exactJson(data.scope, expected.scope) ||
    responseScope.type !== "provider_dataset" ||
    responseScope.provider_dataset_id !== identity.providerDatasetId ||
    responseScope.operation_key !== identity.operationKey ||
    responseScope.sync_scope !== expectedEffectiveSyncScope ||
    !expectedEffectiveSyncScope?.startsWith("external_system:") ||
    // providers[]/dataset_keys[] plan echo는 삭제됐다 — membership 정본은
    // dataset_memberships[{provider_dataset_id, sync_scope, operation_key}]다.
    !exactJson(data.dataset_memberships, [
      {
        operation_key: identity.operationKey,
        provider_dataset_id: identity.providerDatasetId,
        sync_scope: expectedEffectiveSyncScope,
      },
    ]) ||
    data.run_mode !== expected.run_mode ||
    data.priority !== expected.priority ||
    !exactJson(data.update_policy, expected.update_policy ?? {}) ||
    matchedScope === null
  ) {
    throw new Error("KMA preview response plan/resolved scope 계약 불일치");
  }
  const providerDatasets = matchedScope.provider_datasets;
  if (
    !Array.isArray(providerDatasets) ||
    providerDatasets.length !== 1
  ) {
    throw new Error("KMA preview matched_scope exact provider pair가 없습니다");
  }
  const pair = asRecord(providerDatasets[0]);
  if (
    pair === null ||
    pair.provider !== KMA_PROVIDER ||
    pair.dataset_key !== KMA_DATASET_KEY ||
    typeof pair.feature_count !== "number" ||
    !Number.isSafeInteger(pair.feature_count) ||
    pair.feature_count < 0 ||
    ("sync_scope" in pair && pair.sync_scope !== expectedEffectiveSyncScope) ||
    ("effective_sync_scope" in matchedScope &&
      matchedScope.effective_sync_scope !== expectedEffectiveSyncScope)
  ) {
    throw new Error("KMA preview matched_scope provider/effective scope identity 불일치");
  }
  if (FORBIDDEN_PROVIDER_PATTERN.test(JSON.stringify(data))) {
    throw new Error("KMA preview response에 금지 provider가 포함되었습니다");
  }
  assertOnlyKmaProviderObjects(data.matched_scope, "KMA preview matched_scope");
}

export async function assertExactKmaPreviewResponse(
  response: Response,
  expected: FeatureUpdateRequestPreviewRequest,
): Promise<FeatureUpdateRequestPreviewResponse> {
  const contentType = response.headers()["content-type"] ?? "";
  if (response.status() !== 200 || !contentType.toLowerCase().includes("json")) {
    throw new Error("KMA preview HTTP/content-type 계약 불일치");
  }
  let body: FeatureUpdateRequestPreviewResponse;
  try {
    body = (await response.json()) as FeatureUpdateRequestPreviewResponse;
  } catch {
    throw new Error("KMA preview JSON 응답 계약 불일치");
  }
  assertExactKmaPreviewBody(body, expected);
  return body;
}

export function assertKmaOnlyTerminalProviderScopes(
  detail: PipelineExecutionDetailResponse,
  options: { executed: "empty" | "nonempty" },
): void {
  const identity = requireKmaDatasetIdentity();
  const updateRequest = detail.data.update_request;
  const membership = updateRequest?.dataset_memberships[0];
  if (
    updateRequest === null ||
    updateRequest.scope.type !== "provider_dataset" ||
    updateRequest.scope.provider_dataset_id !== identity.providerDatasetId ||
    updateRequest.scope.operation_key !== identity.operationKey ||
    !updateRequest.scope.sync_scope.startsWith("external_system:") ||
    // effective_sync_scope와 providers[]/dataset_keys[]는 삭제됐다. 실행 membership
    // 정본은 dataset_memberships이며 scope와 정확히 같은 triple 하나여야 한다.
    updateRequest.dataset_memberships.length !== 1 ||
    membership?.provider_dataset_id !== identity.providerDatasetId ||
    membership.operation_key !== identity.operationKey ||
    membership.sync_scope !== updateRequest.scope.sync_scope
  ) {
    throw new Error("terminal update request KMA-only plan 계약 불일치");
  }
  const matched = asRecord(updateRequest.matched_scope);
  if (matched === null) {
    throw new Error("terminal matched_scope 계약 불일치");
  }
  const keys = [
    "eligible_provider_scopes",
    "skipped_provider_scopes",
    "executed_provider_scopes",
  ] as const;
  if (
    !Array.isArray(matched.eligible_provider_scopes) ||
    !Array.isArray(matched.skipped_provider_scopes)
  ) {
    throw new Error("terminal provider scope 전체 집합 계약 불일치");
  }
  const providerIdentities = new Set<string>();
  for (const key of keys) {
    const raw = matched[key];
    if (raw === undefined) continue;
    if (!Array.isArray(raw)) {
      throw new Error(`terminal ${key} 배열 계약 불일치`);
    }
    for (const value of raw) {
      const item = asRecord(value);
      if (
        item?.provider !== KMA_PROVIDER ||
        item.dataset_key !== KMA_DATASET_KEY
      ) {
        throw new Error(`terminal ${key} KMA-only 집합 불일치`);
      }
      providerIdentities.add(`${item.provider}\u0000${item.dataset_key}`);
    }
  }
  const executed = matched.executed_provider_scopes;
  if (
    (options.executed === "empty" &&
      executed !== undefined &&
      (!Array.isArray(executed) || executed.length !== 0)) ||
    (options.executed === "nonempty" &&
      (!Array.isArray(executed) || executed.length !== 1)) ||
    providerIdentities.size !== 1 ||
    !providerIdentities.has(`${KMA_PROVIDER}\u0000${KMA_DATASET_KEY}`) ||
    FORBIDDEN_PROVIDER_PATTERN.test(JSON.stringify(matched))
  ) {
    throw new Error("terminal 전체 provider scope 집합이 exact KMA-only가 아닙니다");
  }
  assertOnlyKmaProviderObjects(matched, "terminal matched_scope");
}

export async function createKmaRequest(
  page: Page,
  body: FeatureUpdateRequestCreateRequest,
  idempotencyKey: string,
  state: CleanupState,
): Promise<BrowserFetchResult<FeatureUpdateRequestCreateResponse>> {
  assertKmaOnlyPlan(body);
  const externalSystem = kmaExternalSystem(body);
  const expectedTargets = state.targets.filter(
    (target) =>
      target.externalSystem === externalSystem &&
      state.targetStatuses.get(targetJournalKey(target)) === "active",
  );
  await assertExactOwnedTargetsAtServer(
    page,
    state,
    expectedTargets,
    externalSystem,
  );
  await journalPendingRequest(state, body, idempotencyKey);
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
  } catch {
    const pending = state.idempotencyEntries.get(idempotencyKey);
    if (pending) pending.status = "response_lost_replaying";
    await writeDurableJournal(state, "request_response_lost");
    result = await submit();
  }
  await trackRequestResult(state, result, idempotencyKey);
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
    result = {
      body: parsed,
      entityTag: response.headers()["etag"] ?? null,
      status: response.status(),
    };
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
  expectedBody: FeatureUpdateRequestCreateRequest,
  expectedTargets: readonly TargetRef[],
  submit: () => Promise<void>,
): Promise<TrackedUiKmaCreateResult> {
  let idempotencyKey: string | null = null;
  let journaledBody: FeatureUpdateRequestCreateRequest | null = null;
  let routeSeen = false;
  let resolveRouteHandled!: () => void;
  let rejectRouteHandled!: (error: unknown) => void;
  const routeHandled = new Promise<void>((resolve, reject) => {
    resolveRouteHandled = resolve;
    rejectRouteHandled = reject;
  });
  void routeHandled.catch(() => undefined);
  let resolveHandlerSettled!: () => void;
  const handlerSettled = new Promise<void>((resolve) => {
    resolveHandlerSettled = resolve;
  });
  const exactUrl = new URL(
    "/api/proxy/v1/ops/pipeline/requests",
    expectedUiOrigin(),
  ).href;
  const routeHandler = async (route: Route): Promise<void> => {
    routeSeen = true;
    const request = route.request();
    try {
      if (request.method() !== "POST" || request.url() !== exactUrl) {
        throw new Error("UI KMA create exact origin/path/method 불일치");
      }
      const candidateKey = request.headers()["idempotency-key"];
      if (!candidateKey || !UUID_PATTERN.test(candidateKey)) {
        throw new Error("UI KMA create Idempotency-Key 계약 불일치");
      }
      const body = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
      await assertExactOwnedTargetsAtServer(
        page,
        state,
        expectedTargets,
        kmaExternalSystem(expectedBody),
      );
      await journalExactUiKmaCreateRequest(
        state,
        body,
        candidateKey,
        expectedBody,
        expectedTargets,
      );
      idempotencyKey = candidateKey;
      journaledBody = body;
      await route.continue();
      resolveRouteHandled();
    } catch (error) {
      rejectRouteHandled(error);
      await route.abort("failed").catch(() => undefined);
    } finally {
      resolveHandlerSettled();
    }
  };

  await page.route(exactUrl, routeHandler);
  const responsePromise = page.waitForResponse((candidate) => {
    return (
      candidate.request().method() === "POST" && candidate.url() === exactUrl
    );
  });
  let response: Response | null = null;
  let primaryError: unknown;
  try {
    await submit();
    await boundedWait(routeHandled, "UI KMA create route barrier");
    response = await boundedWait(
      responsePromise,
      "UI KMA create response",
    ).catch(() => null);
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    void responsePromise.catch(() => undefined);
    const teardownErrors: unknown[] = [];
    if (routeSeen) {
      await boundedWait(
        handlerSettled,
        "UI KMA create route handler settlement",
      ).catch((error: unknown) => teardownErrors.push(error));
    }
    await page
      .unroute(exactUrl, routeHandler)
      .catch((error: unknown) => teardownErrors.push(error));
    if (teardownErrors.length > 0) {
      throw new AggregateError(
        primaryError === undefined
          ? teardownErrors
          : [primaryError, ...teardownErrors],
        "UI KMA create primary/route cleanup 실패",
      );
    }
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
  syncScope: string,
  submit: () => Promise<void>,
): Promise<FeatureUpdateRequestMutationResponse> {
  const runNowIdentity = requireKmaDatasetIdentity();
  const exactPath = `/api/proxy/v1/ops/pipeline/requests/${encodeURIComponent(
    requestId,
  )}/run-now`;
  const exactUrl = new URL(exactPath, expectedUiOrigin()).href;
  let routeSeen = false;
  let resolveBarrier!: () => void;
  let rejectBarrier!: (error: unknown) => void;
  const barrier = new Promise<void>((resolve, reject) => {
    resolveBarrier = resolve;
    rejectBarrier = reject;
  });
  void barrier.catch(() => undefined);
  let resolveHandlerSettled!: () => void;
  const handlerSettled = new Promise<void>((resolve) => {
    resolveHandlerSettled = resolve;
  });
  const routeHandler = async (route: Route): Promise<void> => {
    routeSeen = true;
    const request = route.request();
    try {
      if (
        request.method() !== "POST" ||
        request.url() !== exactUrl ||
        request.postData() !== null
      ) {
        throw new Error("run-now exact origin/path/method/body 계약 불일치");
      }
      const detailResponse = await page.request.get(
        new URL(
          `/api/proxy/v1/ops/pipeline/executions/update_request/${encodeURIComponent(
            requestId,
          )}`,
          expectedUiOrigin(),
        ).href,
        { headers: { Accept: "application/json" }, timeout: BROWSER_FETCH_TIMEOUT_MS },
      );
      const detail = detailResponse.ok()
        ? ((await detailResponse.json()) as PipelineExecutionDetailResponse)
        : null;
      const updateRequest = detail?.data.update_request;
      const scope = updateRequest?.scope;
      if (
        detailResponse.status() !== 200 ||
        detail === null ||
        detail.data.execution.kind !== "update_request" ||
        detail.data.execution.id !== requestId ||
        detail.data.execution.status !== "running" ||
        detail.data.execution.job_id !== jobId ||
        updateRequest == null ||
        updateRequest.request_id !== requestId ||
        updateRequest.job_id !== jobId ||
        updateRequest.status !== "running" ||
        scope?.type !== "provider_dataset" ||
        scope.provider_dataset_id !== runNowIdentity.providerDatasetId ||
        scope.operation_key !== runNowIdentity.operationKey ||
        scope.sync_scope !== syncScope ||
        detail.data.cancellation !== null ||
        detail.data.root.cancellation !== null
      ) {
        throw new Error(
          "run-now mutation 직전 exact running KMA ownership barrier 실패",
        );
      }
      const externalSystemPrefix = "external_system:";
      const externalSystem = syncScope.startsWith(externalSystemPrefix)
        ? syncScope.slice(externalSystemPrefix.length)
        : "";
      if (!externalSystem) {
        throw new Error("run-now external_system scope identity가 없습니다");
      }
      const expectedTargets = state.targets.filter(
        (target) =>
          target.externalSystem === externalSystem &&
          state.targetStatuses.get(targetJournalKey(target)) === "active",
      );
      await assertExactOwnedTargetsAtServer(
        page,
        state,
        expectedTargets,
        externalSystem,
      );
      await journalRunNowMutation(state, requestId, "pending");
      await route.continue();
      resolveBarrier();
    } catch (error) {
      rejectBarrier(error);
      await route.abort("failed").catch(() => undefined);
    } finally {
      resolveHandlerSettled();
    }
  };
  await page.route(exactUrl, routeHandler);
  const responsePromise = page.waitForResponse((candidate) => {
    return candidate.request().method() === "POST" && candidate.url() === exactUrl;
  });
  let response: Response;
  let primaryError: unknown;
  try {
    await submit();
    await boundedWait(barrier, "UI KMA run-now ownership barrier");
    response = await boundedWait(responsePromise, "UI KMA run-now response");
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    void responsePromise.catch(() => undefined);
    const teardownErrors: unknown[] = [];
    if (routeSeen) {
      await boundedWait(
        handlerSettled,
        "UI KMA run-now route handler settlement",
      ).catch((error: unknown) => teardownErrors.push(error));
    }
    await page
      .unroute(exactUrl, routeHandler)
      .catch((error: unknown) => teardownErrors.push(error));
    if (teardownErrors.length > 0) {
      throw new AggregateError(
        primaryError === undefined
          ? teardownErrors
          : [primaryError, ...teardownErrors],
        "UI KMA run-now primary/route cleanup 실패",
      );
    }
  }
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
  if (!state) {
    throw new Error("run-now direct dispatch에는 cleanup ownership state가 필요합니다");
  }
  const identity = requireKmaDatasetIdentity();
  const detail = requireBody(await getRequestDetail(page, requestId), 200);
  const updateRequest = detail.data.update_request;
  const scope = updateRequest?.scope;
  if (
    detail.data.execution.id !== requestId ||
    updateRequest === null ||
    updateRequest.request_id !== requestId ||
    scope?.type !== "provider_dataset" ||
    scope.provider_dataset_id !== identity.providerDatasetId ||
    scope.operation_key !== identity.operationKey ||
    !scope.sync_scope.startsWith("external_system:")
  ) {
    throw new Error("run-now direct KMA request identity barrier 실패");
  }
  const externalSystem = scope.sync_scope.slice("external_system:".length);
  const expectedTargets = state.targets.filter(
    (target) =>
      target.externalSystem === externalSystem &&
      state.targetStatuses.get(targetJournalKey(target)) === "active",
  );
  await assertExactOwnedTargetsAtServer(
    page,
    state,
    expectedTargets,
    externalSystem,
  );
  await writeDurableJournal(state, "run_now_pending");
  const result = await browserFetch<FeatureUpdateRequestMutationResponse>(
    page,
    `${PIPELINE_REQUESTS_PATH}/${encodeURIComponent(requestId)}/run-now`,
    { method: "POST", body: {} },
  );
  await writeDurableJournal(state, "run_now_observed");
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
  const identity = requireKmaDatasetIdentity();
  return new URLSearchParams({
    sync_scope: syncScope,
    operation_key: identity.operationKey,
  }).toString();
}

export function exactDatasetUiPath(syncScope: string): string {
  const identity = requireKmaDatasetIdentity();
  const query = new URLSearchParams({
    provider_dataset_id: String(identity.providerDatasetId),
    sync_scope: syncScope,
    operation_key: identity.operationKey,
    panel: "history",
  });
  return `/ops/datasets?${query.toString()}`;
}

export async function getExactDatasetDetail(
  page: Page,
  syncScope: string,
): Promise<BrowserFetchResult<OpsDatasetDetailResponse>> {
  const identity = requireKmaDatasetIdentity();
  return browserFetch<OpsDatasetDetailResponse>(
    page,
    `/v1/ops/datasets/${identity.providerDatasetId}?${exactScopeQuery(
      syncScope,
    )}`,
    { timeoutMs: DATASET_DETAIL_FETCH_TIMEOUT_MS },
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
    allExternalSystems: new Set(),
    allIdempotencyEntries: new Map(),
    allRequestIds: new Set(),
    allRequestTerminalStatuses: new Map(),
    allTargetRefs: new Map(),
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
    targetHistory: [],
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

export async function assertExactOwnedTargetsAtServer(
  page: Page,
  state: CleanupState,
  expectedTargets: readonly TargetRef[],
  expectedExternalSystem?: string,
): Promise<void> {
  assertBootstrappedPage(page);
  const ownedTargets = expectedTargets.map((target) => {
    const owned = requireOwnedTarget(state, target);
    if (state.targetStatuses.get(targetJournalKey(owned)) !== "active") {
      throw new Error("UI KMA create expected target가 active owned 상태가 아닙니다");
    }
    return owned;
  });
  for (let offset = 0; offset < ownedTargets.length; offset += 25) {
    const batch = ownedTargets.slice(offset, offset + 25);
    await Promise.all(
      batch.map(async (owned) => {
        const response = await page.request.get(
          new URL(
            `/api/proxy${targetPath(owned.externalSystem, owned.targetKey)}`,
            expectedUiOrigin(),
          ).href,
          {
            headers: { Accept: "application/json" },
            timeout: BROWSER_FETCH_TIMEOUT_MS,
          },
        );
        if (response.status() !== 200) {
          throw new Error(
            `UI KMA create target server ownership barrier 실패(status=${response.status()})`,
          );
        }
        const body = (await response.json()) as PoiCacheTargetResponse;
        assertOwnedTargetRecord(body, owned, owned.body, owned.targetId);
        const entityTag = response.headers()["etag"] ?? null;
        if (
          entityTag !== owned.entityTag ||
          parseStrongEntityTag(entityTag ?? "", owned.targetId) !==
            owned.lockVersion
        ) {
          throw new Error("UI KMA create target GET strong ETag 불일치");
        }
      }),
    );
  }
  if (
    expectedExternalSystem !== undefined &&
    (expectedExternalSystem.length === 0 ||
      ownedTargets.some(
        (target) => target.externalSystem !== expectedExternalSystem,
      ))
  ) {
    throw new Error("UI KMA create expected external_system 집합 불일치");
  }
  const externalSystems = [
    ...new Set([
      ...ownedTargets.map((target) => target.externalSystem),
      ...(expectedExternalSystem === undefined
        ? []
        : [expectedExternalSystem]),
    ]),
  ].sort();
  for (const externalSystem of externalSystems) {
    const expected = ownedTargets
      .filter((target) => target.externalSystem === externalSystem)
      .map((target) => ({
        entityTag: target.entityTag,
        targetId: target.targetId,
        targetKey: target.targetKey,
      }))
      .sort((left, right) => left.targetKey.localeCompare(right.targetKey));
    if (expected.length > OWNED_TARGET_SET_LIMIT) {
      throw new Error("UI KMA create owned target set limit(501)을 초과했습니다");
    }
    const observed: Array<{
      entityTag: string;
      targetId: string;
      targetKey: string;
    }> = [];
    const seenCursors = new Set<string>();
    let cursor: string | null = null;
    let completed = false;
    for (let pageIndex = 0; pageIndex < OWNED_TARGET_PAGE_LIMIT; pageIndex += 1) {
      const query = new URLSearchParams({
        external_system: externalSystem,
        include_deleted: "false",
        page_size: String(OWNED_TARGET_PAGE_SIZE),
      });
      if (cursor !== null) query.set("cursor", cursor);
      const response = await page.request.get(
        new URL(
          `/api/proxy${POI_TARGETS_PATH}?${query.toString()}`,
          expectedUiOrigin(),
        ).href,
        {
          headers: { Accept: "application/json" },
          timeout: BROWSER_FETCH_TIMEOUT_MS,
        },
      );
      if (response.status() !== 200) {
        throw new Error(
          `UI KMA create external_system full-list barrier 실패(status=${response.status()})`,
        );
      }
      const envelope = (await response.json()) as PoiCacheTargetListResponse;
      const items = envelope.data.items;
      if (
        items.length > OWNED_TARGET_PAGE_SIZE ||
        (cursor !== null && items.length === 0)
      ) {
        throw new Error("UI KMA create target cursor page 크기 계약 불일치");
      }
      for (const item of items) {
        if (item.external_system !== externalSystem) {
          throw new Error("UI KMA create target cursor page scope 누출");
        }
        observed.push({
          entityTag: item.entity_tag,
          targetId: item.target_id,
          targetKey: item.target_key,
        });
      }
      if (observed.length > OWNED_TARGET_SET_LIMIT) {
        throw new Error("UI KMA create server active target set limit(501) 초과");
      }
      const nextCursor = envelope.meta.page?.next_cursor;
      if (nextCursor === null) {
        completed = true;
        break;
      }
      if (
        typeof nextCursor !== "string" ||
        nextCursor.length === 0 ||
        nextCursor === cursor ||
        seenCursors.has(nextCursor)
      ) {
        throw new Error("UI KMA create target cursor 반복/형식 계약 불일치");
      }
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    }
    if (!completed) {
      throw new Error("UI KMA create target cursor page limit(2) 초과");
    }
    observed.sort((left, right) => left.targetKey.localeCompare(right.targetKey));
    if (!exactJson(observed, expected)) {
      throw new Error(
        "UI KMA create owned external_system key/UUID/entity_tag 전체 집합 불일치",
      );
    }
  }
}

export async function journalPendingRequest(
  state: CleanupState,
  body: FeatureUpdateRequestCreateRequest,
  idempotencyKey: string,
): Promise<void> {
  assertKmaOnlyPlan(body);
  const existing = state.idempotencyEntries.get(idempotencyKey);
  if (existing && !exactJson(existing.body, body)) {
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

export async function journalExactUiKmaCreateRequest(
  state: CleanupState,
  actualBody: FeatureUpdateRequestCreateRequest,
  idempotencyKey: string,
  expectedBody: FeatureUpdateRequestCreateRequest,
  expectedTargets: readonly TargetRef[],
): Promise<void> {
  if (!UUID_PATTERN.test(idempotencyKey)) {
    throw new Error("UI KMA create Idempotency-Key UUID 계약 불일치");
  }
  assertKmaOnlyPlan(actualBody);
  assertKmaOnlyPlan(expectedBody);
  if (!exactJson(actualBody, expectedBody)) {
    throw new Error("UI KMA create body가 exact expected body와 다릅니다");
  }
  const syncScope =
    "sync_scope" in expectedBody.scope
      ? expectedBody.scope.sync_scope
      : null;
  const expectedExternalSystem = syncScope?.startsWith("external_system:")
    ? syncScope.slice("external_system:".length)
    : "";
  if (!expectedExternalSystem || expectedTargets.length === 0) {
    throw new Error("UI KMA create expected target scope가 비어 있습니다");
  }
  const expectedKeys = expectedTargets
    .map(targetJournalKey)
    .sort();
  if (new Set(expectedKeys).size !== expectedKeys.length) {
    throw new Error("UI KMA create expected target identity가 중복되었습니다");
  }
  const activeOwned = state.targets.filter(
    (target) => state.targetStatuses.get(targetJournalKey(target)) === "active",
  );
  const activeKeys = activeOwned.map(targetJournalKey).sort();
  if (!exactJson(activeKeys, expectedKeys)) {
    throw new Error("UI KMA create active owned target 집합이 exact scope와 다릅니다");
  }
  for (const target of activeOwned) {
    if (
      target.externalSystem !== expectedExternalSystem ||
      !UUID_PATTERN.test(target.targetId) ||
      !Number.isFinite(target.body.coord.lon) ||
      !Number.isFinite(target.body.coord.lat) ||
      !Number.isFinite(target.body.radius_km) ||
      target.body.radius_km <= 0
    ) {
      throw new Error(
        "UI KMA create target key/UUID/coord/radius/scope ownership 불일치",
      );
    }
  }
  await journalPendingRequest(state, actualBody, idempotencyKey);
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
  await assertTerminalDagsterRunIdentity(page, detail);
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

/**
 * fast-completion tolerant 재탐색. queued 요청이 sensor tick 전에 done까지 가면
 * active_execution이 null이 되어 rediscoverExactActiveRequest가 오탐(재탐색 실패)한다.
 * active면 active identity를, 아니면 latest_execution(=방금 종료된 우리 요청)을 검증한다.
 */
export async function rediscoverExactActiveOrSettledRequest(
  page: Page,
  syncScope: string,
  expectedRequestId: string,
): Promise<void> {
  const detail = requireBody(await getExactDatasetDetail(page, syncScope), 200);
  const active = detail.data.active_execution;
  if (active !== null) {
    if (
      active.kind !== "update_request" ||
      active.sync_scope !== syncScope ||
      active.id !== expectedRequestId
    ) {
      throw new Error(
        `exact scope active request 재탐색 identity 불일치: ${syncScope}`,
      );
    }
    return;
  }
  const latest = detail.data.latest_execution;
  if (latest === null || latest.id !== expectedRequestId) {
    throw new Error(
      `exact scope active/settled request 재탐색 실패: ${syncScope}`,
    );
  }
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
  terminalTimeout: number,
): Promise<CleanupExecution> {
  const issues: CleanupIssue[] = [];
  let exactScopeDiscoveryComplete = true;
  const targetRecovery = await recoverUnresolvedTargetIntents(page, state);
  issues.push(...targetRecovery.issues);
  const exactTargetDiscoveryComplete = targetRecovery.complete;

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
      state.requestTerminalStatuses.set(requestId, status);
    } else {
      everyRequestTerminal = false;
      issues.push({ kind: "request_terminal_timeout", resource: requestId });
    }
  }
  await writeDurableJournal(state, "cleanup_terminal_checked");

  // 하나라도 terminal을 증명하지 못하면 어떤 target도 삭제하지 않는다.
  const canDeleteTargets =
    everyRequestTerminal &&
    exactScopeDiscoveryComplete &&
    exactTargetDiscoveryComplete;
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
    allRequestsTerminal: everyRequestTerminal && exactScopeDiscoveryComplete,
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
    allRequestsTerminal: false,
    preservedForManualCleanup: true,
    restored: false,
  };
}
