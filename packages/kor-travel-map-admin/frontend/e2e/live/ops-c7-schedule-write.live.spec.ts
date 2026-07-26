import { createHash, randomUUID } from "node:crypto";
import { chmod, open, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  expect,
  test,
  type Locator,
  type Page,
  type Request,
  type Response,
  type Route,
  type TestInfo,
} from "@playwright/test";

import type { components } from "../../src/api/types";

import {
  bootstrapC7SameOriginPage,
  browserFetch,
  requireBody,
} from "./_ops-c7-admin-api";

type PipelineSchedule = components["schemas"]["DagsterSchedule"];
type PipelineSchedulesResponse =
  components["schemas"]["PipelineSchedulesResponse"];
type PipelineScheduleCommandResponse =
  components["schemas"]["PipelineScheduleCommandResponse"];

type StableScheduleStatus = "RUNNING" | "STOPPED";
type ScheduleSnapshot = {
  canReset: boolean;
  defaultCronSchedule: string;
  defaultStatus: StableScheduleStatus;
  effectiveCronSchedule: string;
  name: string;
  overrideCronSchedule: string | null;
  overrideEffective: boolean | null;
  overrideSaved: boolean;
  repositoryLocationName: string;
  repositoryName: string;
  selectorId: string;
  stateId: string;
  status: StableScheduleStatus;
};
type ScheduleCommand = "start" | "stop" | "reset";
type ScheduleMutationBody =
  | { command: ScheduleCommand; reason: string | null }
  | { cron_schedule: string | null; reason: string | null };
type ScheduleResponseCommand =
  | ScheduleCommand
  | "update"
  | "clear_override";
type ScheduleMutationIntent = {
  before: ScheduleSnapshot;
  expectedCommand: ScheduleResponseCommand;
  idempotencyKey: string;
  intendedAfter: ScheduleSnapshot;
  operation: string;
  requestBody: ScheduleMutationBody;
  requestMethod: "PATCH" | "POST";
  requestPath: string;
  scheduleName: string;
};
type ScheduleRecoveryState = {
  current: ScheduleSnapshot | null;
  dagsterGraphqlEndpointSha256: string;
  expectedDagsterGraphqlEndpointSha256: string;
  initial: ScheduleSnapshot;
  mutationIntent: ScheduleMutationIntent | null;
  ownedExpected: ScheduleSnapshot;
  phase:
    | "snapshotted"
    | "mutating"
    | "restoring"
    | "restored"
    | "restore_failed";
  updatedAt: string;
  version: 4;
};
type DagsterAttestation = {
  actual: string;
  expected: string;
};

const SAFE_SCHEDULE =
  "feature_weather_kma_short_forecast_hourly_schedule" as const;
const SCHEDULES_PATH = "/v1/ops/pipeline/schedules";
const TEST_TIMEOUT = 12 * 60 * 1000;
const STATE_WAIT_TIMEOUT = 2 * 60 * 1000;
const UI_MUTATION_TIMEOUT = 45_000;

test.describe.configure({ mode: "serial", retries: 0 });

function schedulePath(scheduleName: string): string {
  return `${SCHEDULES_PATH}/${encodeURIComponent(scheduleName)}`;
}

function stateFile(): string {
  const configured = process.env.E2E_C7_SCHEDULE_STATE_FILE;
  if (!configured || !path.isAbsolute(configured)) {
    throw new Error(
      "E2E_C7_SCHEDULE_STATE_FILE은 host orchestrator가 지정한 절대 경로여야 합니다.",
    );
  }
  return configured;
}

function lowercaseSha256(value: string | undefined, name: string): string {
  if (!value || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${name}은 lowercase SHA-256이어야 합니다.`);
  }
  return value;
}

function canonicalGraphqlSha256(raw: string | undefined): string {
  if (!raw) throw new Error("Dagster GraphQL URL이 없습니다.");
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Dagster GraphQL URL 형식이 올바르지 않습니다.");
  }
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new Error("Dagster URL은 credential/query/hash 없는 HTTPS여야 합니다.");
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  url.pathname = pathname.endsWith("/graphql")
    ? pathname
    : `${pathname}/graphql`;
  return createHash("sha256").update(url.href).digest("hex");
}

function dagsterAttestation(): DagsterAttestation {
  const actual = canonicalGraphqlSha256(process.env.E2E_DAGSTER_URL);
  const expected = lowercaseSha256(
    process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256,
    "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256",
  );
  if (actual !== expected) {
    throw new Error("Dagster GraphQL endpoint origin attestation이 불일치합니다.");
  }
  return { actual, expected };
}

function requireScheduleGates(testInfo: TestInfo): void {
  const missing = ["E2E_ADMIN_WRITE", "E2E_DAGSTER_WRITE"].filter(
    (name) => process.env[name] !== "1",
  );
  test.skip(
    missing.length > 0,
    `${missing.join(", ")}=1이 없어서 schedule destructive 시나리오 전체를 실행하지 않습니다.`,
  );
  test.skip(
    process.env.E2E_C7_SCHEDULE !== SAFE_SCHEDULE,
    `E2E_C7_SCHEDULE은 exact allowlist ${SAFE_SCHEDULE}이어야 합니다.`,
  );
  for (const name of [
    "E2E_C7_EXPECTED_UI_ORIGIN_SHA256",
    "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256",
    "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256",
  ]) {
    lowercaseSha256(process.env[name], name);
  }
  dagsterAttestation();
  if (testInfo.config.workers !== 1) {
    throw new Error("schedule destructive live E2E는 실제 workers=1이어야 합니다.");
  }
  if (testInfo.project.retries !== 0) {
    throw new Error("schedule destructive live E2E는 실제 retries=0이어야 합니다.");
  }
  stateFile();
}

function stableStatus(
  value: string | null | undefined,
  field: string,
): StableScheduleStatus {
  if (value !== "RUNNING" && value !== "STOPPED") {
    throw new Error(`${field}가 RUNNING/STOPPED가 아닙니다.`);
  }
  return value;
}

function requiredString(
  value: string | null | undefined,
  field: string,
): string {
  if (!value) throw new Error(`${field}가 비어 있습니다.`);
  return value;
}

function snapshotOf(schedule: PipelineSchedule): ScheduleSnapshot {
  const overrideCronSchedule = schedule.override_cron_schedule ?? null;
  const overrideEffective = schedule.override_effective;
  if (
    overrideCronSchedule === null
      ? overrideEffective !== null || schedule.override_saved
      : typeof overrideEffective !== "boolean" || !schedule.override_saved
  ) {
    throw new Error("schedule override 저장/실제 반영 계약이 일치하지 않습니다.");
  }
  return {
    canReset: schedule.can_reset,
    defaultCronSchedule: requiredString(
      schedule.default_cron_schedule,
      "default_cron_schedule",
    ),
    defaultStatus: stableStatus(schedule.default_status, "default_status"),
    effectiveCronSchedule: requiredString(
      schedule.effective_cron_schedule,
      "effective_cron_schedule",
    ),
    name: schedule.name,
    overrideCronSchedule,
    overrideEffective,
    overrideSaved: schedule.override_saved,
    repositoryLocationName: requiredString(
      schedule.repository_location_name,
      "repository_location_name",
    ),
    repositoryName: requiredString(
      schedule.repository_name,
      "repository_name",
    ),
    selectorId: requiredString(schedule.selector_id, "selector_id"),
    stateId: requiredString(schedule.state_id, "state_id"),
    status: stableStatus(schedule.status, "status"),
  };
}

function sameSnapshot(
  left: ScheduleSnapshot,
  right: ScheduleSnapshot,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  return (
    JSON.stringify(Object.keys(value).sort()) ===
    JSON.stringify([...expected].sort())
  );
}

function isScheduleSnapshot(value: unknown): value is ScheduleSnapshot {
  if (!isRecord(value)) return false;
  const requiredStrings = [
    "defaultCronSchedule",
    "effectiveCronSchedule",
    "name",
    "repositoryLocationName",
    "repositoryName",
    "selectorId",
    "stateId",
  ] as const;
  return (
    hasExactKeys(value, [
      "canReset",
      "defaultCronSchedule",
      "defaultStatus",
      "effectiveCronSchedule",
      "name",
      "overrideCronSchedule",
      "overrideEffective",
      "overrideSaved",
      "repositoryLocationName",
      "repositoryName",
      "selectorId",
      "stateId",
      "status",
    ]) &&
    typeof value.canReset === "boolean" &&
    requiredStrings.every(
      (field) =>
        typeof value[field] === "string" && value[field].length > 0,
    ) &&
    ["RUNNING", "STOPPED"].includes(String(value.defaultStatus)) &&
    (value.overrideCronSchedule === null ||
      (typeof value.overrideCronSchedule === "string" &&
        value.overrideCronSchedule.length > 0)) &&
    (value.overrideEffective === null ||
      typeof value.overrideEffective === "boolean") &&
    typeof value.overrideSaved === "boolean" &&
    ["RUNNING", "STOPPED"].includes(String(value.status))
  );
}

async function assertScheduleStateFileClaimable(): Promise<void> {
  const destination = stateFile();
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(destination, "utf8"));
  } catch {
    throw new Error(
      "schedule recovery journal placeholder를 읽을 수 없습니다; audited recovery가 필요합니다.",
    );
  }
  if (!isRecord(parsed)) {
    throw new Error("schedule recovery journal 형식이 올바르지 않습니다.");
  }
  const attestation = dagsterAttestation();
  if (
    parsed.phase === "schedule_snapshot_pending" &&
    parsed.version === 2 &&
    parsed.dagsterGraphqlEndpointSha256 === attestation.actual &&
    hasExactKeys(parsed, [
      "dagsterGraphqlEndpointSha256",
      "phase",
      "version",
    ])
  ) {
    return;
  }
  const initial = parsed.initial;
  const current = parsed.current;
  const ownedExpected = parsed.ownedExpected;
  if (
    parsed.phase === "restored" &&
    parsed.version === 4 &&
    parsed.dagsterGraphqlEndpointSha256 === attestation.actual &&
    parsed.expectedDagsterGraphqlEndpointSha256 === attestation.expected &&
    parsed.mutationIntent === null &&
    typeof parsed.updatedAt === "string" &&
    parsed.updatedAt.length > 0 &&
    isScheduleSnapshot(initial) &&
    isScheduleSnapshot(current) &&
    isScheduleSnapshot(ownedExpected) &&
    sameSnapshot(initial, current) &&
    sameSnapshot(initial, ownedExpected) &&
    hasExactKeys(parsed, [
      "current",
      "dagsterGraphqlEndpointSha256",
      "expectedDagsterGraphqlEndpointSha256",
      "initial",
      "mutationIntent",
      "ownedExpected",
      "phase",
      "updatedAt",
      "version",
    ])
  ) {
    return;
  }
  throw new Error(
    "미복원 schedule recovery journal이 있어 새 실행이 덮어쓸 수 없습니다.",
  );
}

async function persistRecoveryState(
  phase: ScheduleRecoveryState["phase"],
  initial: ScheduleSnapshot,
  current: ScheduleSnapshot | null,
  ownedExpected: ScheduleSnapshot,
  mutationIntent: ScheduleMutationIntent | null = null,
): Promise<void> {
  const destination = stateFile();
  const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
  const attestation = dagsterAttestation();
  const payload: ScheduleRecoveryState = {
    current,
    dagsterGraphqlEndpointSha256: attestation.actual,
    expectedDagsterGraphqlEndpointSha256: attestation.expected,
    initial,
    mutationIntent,
    ownedExpected,
    phase,
    updatedAt: new Date().toISOString(),
    version: 4,
  };
  try {
    await writeFile(temporary, `${JSON.stringify(payload)}\n`, {
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
    await rename(temporary, destination);
    await chmod(destination, 0o600);
    const stateHandle = await open(destination, "r");
    try {
      await stateHandle.sync();
    } finally {
      await stateHandle.close();
    }
    const directoryHandle = await open(path.dirname(destination), "r");
    try {
      await directoryHandle.sync();
    } finally {
      await directoryHandle.close();
    }
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}

async function persistMutationState(
  initial: ScheduleSnapshot,
  current: ScheduleSnapshot,
): Promise<void> {
  await persistRecoveryState("mutating", initial, current, current);
}

function scheduleAfterCommand(
  before: ScheduleSnapshot,
  command: ScheduleCommand,
): ScheduleSnapshot {
  const status =
    command === "reset"
      ? before.defaultStatus
      : command === "start"
        ? "RUNNING"
        : "STOPPED";
  return {
    ...before,
    // dagster는 명시적 start/stop마다 override를 만들어 status==defaultStatus여도
    // canReset=true다(파생 override 플래그, operational 아님). 모델은 reset만 false.
    canReset: command === "reset" ? false : true,
    status,
  };
}

function scheduleAfterCron(
  before: ScheduleSnapshot,
  cronSchedule: string | null,
): ScheduleSnapshot {
  return {
    ...before,
    effectiveCronSchedule: cronSchedule ?? before.defaultCronSchedule,
    overrideCronSchedule: cronSchedule,
    overrideEffective: cronSchedule === null ? null : true,
    overrideSaved: cronSchedule !== null,
  };
}

class ScheduleMutationRecoveryError extends Error {
  readonly blockingIntent: ScheduleMutationIntent | null;
  readonly ownedSnapshot: ScheduleSnapshot;

  constructor(
    ownedSnapshot: ScheduleSnapshot,
    blockingIntent: ScheduleMutationIntent | null,
    message = "schedule mutation 결과가 확정되지 않아 자동 복원을 차단합니다.",
  ) {
    super(message);
    this.name = "ScheduleMutationRecoveryError";
    this.blockingIntent = blockingIntent;
    this.ownedSnapshot = ownedSnapshot;
  }
}

async function getSchedule(page: Page): Promise<PipelineSchedule> {
  const response = requireBody(
    await browserFetch<PipelineSchedulesResponse>(page, SCHEDULES_PATH),
    200,
  );
  if (response.data.status !== "ok") {
    throw new Error("Dagster schedule 목록이 ok 상태가 아닙니다.");
  }
  if (
    canonicalGraphqlSha256(response.data.graphql_url) !==
    dagsterAttestation().expected
  ) {
    throw new Error("admin API Dagster GraphQL endpoint attestation이 불일치합니다.");
  }
  const matches = (response.data.schedules ?? []).filter(
    (schedule) => schedule.name === SAFE_SCHEDULE,
  );
  if (matches.length !== 1) {
    throw new Error("exact allowlist schedule이 목록에 정확히 한 건이어야 합니다.");
  }
  return matches[0]!;
}

async function getScheduleSnapshot(page: Page): Promise<ScheduleSnapshot> {
  return snapshotOf(await getSchedule(page));
}

async function assertOwnedSnapshot(
  page: Page,
  ownedExpected: ScheduleSnapshot,
  operation: string,
): Promise<void> {
  dagsterAttestation();
  const observed = await getScheduleSnapshot(page);
  if (!sameSnapshot(observed, ownedExpected)) {
    throw new Error(
      `${operation} 전 concurrent schedule drift를 감지해 mutation을 차단했습니다.`,
    );
  }
}

async function waitForSchedule(
  page: Page,
  expected: Partial<ScheduleSnapshot>,
): Promise<ScheduleSnapshot> {
  const deadline = Date.now() + STATE_WAIT_TIMEOUT;
  while (Date.now() < deadline) {
    const snapshot = await getScheduleSnapshot(page);
    if (
      Object.entries(expected).every(
        ([key, value]) =>
          // canReset은 파생 override 플래그(operational 상태 아님)라 수렴 비교에서 제외.
          key === "canReset" ||
          JSON.stringify(snapshot[key as keyof ScheduleSnapshot]) ===
            JSON.stringify(value),
      )
    ) {
      return snapshot;
    }
    await page.waitForTimeout(1_000);
  }
  throw new Error("schedule 상태가 제한 시간 안에 기대값으로 수렴하지 않았습니다.");
}

// churn-tolerant click: enabled 대기 후 dispatchEvent로 위치 무관하게 onClick 발화.
// force-click은 위치를 한 번만 계산해 re-render로 이동한 컨트롤을 빗맞히지만,
// dispatchEvent는 위치와 무관하게 React onClick을 발화한다. 창 안에서 재시도한다.
async function robustClick(locator: Locator, label: string): Promise<void> {
  const page = locator.page();
  const deadline = Date.now() + UI_MUTATION_TIMEOUT;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      await expect(locator).toBeEnabled({ timeout: 2_000 });
      await locator.dispatchEvent("click");
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(250);
    }
  }
  throw new Error(
    `robustClick(${label})이 ${UI_MUTATION_TIMEOUT}ms 안에 실패했습니다: ${String(lastError)}`,
  );
}

// recovery-settle gate. 다음 UI 조작 전에 SAFE_SCHEDULE start/stop 토글이 조작 가능한지
// 대기한다: 직전 mutation(특히 cron 수정 + frozen-idempotency 복구)의 dialog가 닫혀
// 페이지가 비-inert가 되고 토글이 enabled·안정된 상태인지 확인한다.
async function waitForScheduleControlsSettled(
  page: Page,
  operation: string,
): Promise<void> {
  const row = page.getByTestId(`pipeline-schedule-row-${SAFE_SCHEDULE}`);
  const toggle = row.getByRole("button", {
    name: new RegExp(`${SAFE_SCHEDULE} 스케줄 (시작|중지)$`),
  });
  const started = Date.now();
  const deadline = started + UI_MUTATION_TIMEOUT;
  let stableSince: number | null = null;
  let lastObs = "";
  while (Date.now() < deadline) {
    // 열린 dialog(예: cron 수정)는 Base UI가 배경을 inert로 만들어 SAFE_SCHEDULE 토글을
    // getByRole/click에서 가린다. dialog가 닫히고 토글이 enabled·안정될 때까지 대기해
    // frozen-idempotency 복구 후 dialog가 열린 채 남는 회귀를 방어한다.
    const dialogOpen =
      (await page.getByRole("dialog").count().catch(() => 0)) > 0;
    const enabled =
      !dialogOpen &&
      (await toggle.isEnabled({ timeout: 1_000 }).catch(() => false));
    const obs = `dialogOpen=${dialogOpen} toggleEnabled=${enabled}`;
    if (obs !== lastObs) {
      // eslint-disable-next-line no-console
      console.log(`[C7SETTLE ${operation}] ${obs}`);
      lastObs = obs;
    }
    if (enabled) {
      if (stableSince === null) stableSince = Date.now();
      if (Date.now() - stableSince >= 500) return;
    } else {
      stableSince = null;
    }
    await page.waitForTimeout(200);
  }
  throw new Error(
    `[C7SETTLE ${operation}] schedule 컨트롤이 ${UI_MUTATION_TIMEOUT}ms 안에 조작 가능해지지 않았습니다 (last=${lastObs}).`,
  );
}

function requireConfirmedMutation(
  response: PipelineScheduleCommandResponse,
  intent: ScheduleMutationIntent,
): void {
  const result = response.data;
  if (
    canonicalGraphqlSha256(result.graphql_url) !==
    dagsterAttestation().expected
  ) {
    throw new Error("schedule mutation Dagster endpoint attestation이 불일치합니다.");
  }
  if (
    result.status !== "ok" ||
    result.outcome_certainty !== "confirmed" ||
    result.audit_status !== "recorded" ||
    result.audit_command_id !== intent.idempotencyKey ||
    result.command !== intent.expectedCommand ||
    result.schedule_name !== intent.scheduleName ||
    (result.errors ?? []).length !== 0
  ) {
    throw new Error(
      "schedule mutation 결과의 certainty/audit/command/schedule identity가 일치하지 않습니다.",
    );
  }
  if (
    intent.requestMethod === "PATCH" &&
    (result.reload_status !== "succeeded" ||
      result.save_status !==
        (intent.expectedCommand === "update" ? "saved" : "cleared"))
  ) {
    throw new Error("schedule cron mutation의 저장/reload 결과가 성공이 아닙니다.");
  }
  if (
    intent.requestMethod === "POST" &&
    (result.reload_status !== "not_requested" ||
      result.save_status !== "not_applicable" ||
      result.effective_status !== "confirmed")
  ) {
    throw new Error("schedule 상태 mutation 결과가 confirmed가 아닙니다.");
  }
}

async function responseBody(
  response: Pick<Response, "json" | "status">,
): Promise<PipelineScheduleCommandResponse> {
  if (response.status() !== 200) {
    throw new Error("schedule UI mutation HTTP status가 200이 아닙니다.");
  }
  return (await response.json()) as PipelineScheduleCommandResponse;
}

async function bounded<T>(
  promise: Promise<T>,
  operation: string,
): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  try {
    return await new Promise<T>((resolve, reject) => {
      timeout = setTimeout(
        () => reject(new Error(`${operation} 제한 시간 초과`)),
        UI_MUTATION_TIMEOUT,
      );
      promise.then(resolve, reject);
    });
  } finally {
    if (timeout !== null) clearTimeout(timeout);
  }
}

function requireIdempotencyKey(value: string | undefined): string {
  if (
    !value ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  ) {
    throw new Error("schedule mutation Idempotency-Key가 UUID가 아닙니다.");
  }
  return value;
}

function exactMutationBody(
  actual: unknown,
  expected: ScheduleMutationBody,
): ScheduleMutationBody {
  if (typeof actual !== "object" || actual === null || Array.isArray(actual)) {
    throw new Error("schedule mutation request body가 JSON object가 아닙니다.");
  }
  const record = actual as Record<string, unknown>;
  const expectedRecord = expected as unknown as Record<string, unknown>;
  const actualKeys = Object.keys(record).sort();
  const expectedKeys = Object.keys(expectedRecord).sort();
  if (
    JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys) ||
    expectedKeys.some((key) => record[key] !== expectedRecord[key])
  ) {
    throw new Error("schedule mutation request body가 예상값과 일치하지 않습니다.");
  }
  return actual as ScheduleMutationBody;
}

function mutationIntent(
  before: ScheduleSnapshot,
  kind: "command" | "patch",
  requestBody: ScheduleMutationBody,
  idempotencyKey: string,
  operation: string,
): ScheduleMutationIntent {
  const requestPath =
    kind === "command"
      ? `${schedulePath(SAFE_SCHEDULE)}/commands`
      : schedulePath(SAFE_SCHEDULE);
  return {
    before,
    expectedCommand:
      "command" in requestBody
        ? requestBody.command
        : requestBody.cron_schedule === null
          ? "clear_override"
          : "update",
    idempotencyKey: requireIdempotencyKey(idempotencyKey),
    intendedAfter:
      "command" in requestBody
        ? scheduleAfterCommand(before, requestBody.command)
        : scheduleAfterCron(before, requestBody.cron_schedule),
    operation,
    requestBody,
    requestMethod: kind === "command" ? "POST" : "PATCH",
    requestPath,
    scheduleName: SAFE_SCHEDULE,
  };
}

async function sendRecordedMutation(
  page: Page,
  intent: ScheduleMutationIntent,
): Promise<void> {
  const result = requireBody(
    await browserFetch<PipelineScheduleCommandResponse>(
      page,
      intent.requestPath,
      {
        body: intent.requestBody,
        headers: { "Idempotency-Key": intent.idempotencyKey },
        method: intent.requestMethod,
      },
    ),
    200,
  );
  requireConfirmedMutation(result, intent);
}

async function replayRecordedMutation(
  page: Page,
  intent: ScheduleMutationIntent,
): Promise<void> {
  const deadline = Date.now() + STATE_WAIT_TIMEOUT;
  let lastError: unknown = new Error("schedule mutation 결과를 확인하지 못했습니다.");
  while (Date.now() < deadline) {
    try {
      await sendRecordedMutation(page, intent);
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(1_000);
    }
  }
  throw lastError;
}

async function observeUnresolvedMutation(
  page: Page,
  initial: ScheduleSnapshot,
  intent: ScheduleMutationIntent,
): Promise<ScheduleSnapshot> {
  let observed = intent.before;
  try {
    observed = await getScheduleSnapshot(page);
  } catch {
    try {
      await persistRecoveryState(
        "restore_failed",
        initial,
        null,
        intent.before,
        intent,
      );
    } catch {
      throw new ScheduleMutationRecoveryError(
        intent.before,
        intent,
        "schedule mutation 결과와 복구 journal을 모두 확인할 수 없습니다.",
      );
    }
    return intent.before;
  }
  try {
    await persistRecoveryState(
      "restore_failed",
      initial,
      observed,
      observed,
      intent,
    );
  } catch {
    throw new ScheduleMutationRecoveryError(
      observed,
      intent,
      "schedule mutation 결과 불명 상태를 journal에 기록하지 못했습니다.",
    );
  }
  return observed;
}

async function directScheduleMutation(
  page: Page,
  initial: ScheduleSnapshot,
  ownedExpected: ScheduleSnapshot,
  kind: "command" | "patch",
  body: { command: ScheduleCommand } | { cron_schedule: string | null },
): Promise<ScheduleSnapshot> {
  await assertOwnedSnapshot(page, ownedExpected, `schedule ${kind}`);
  dagsterAttestation();
  const requestBody: ScheduleMutationBody = {
    ...body,
    reason: "C7 schedule live E2E exact restore",
  };
  const intent = mutationIntent(
    ownedExpected,
    kind,
    requestBody,
    randomUUID(),
    `schedule_${kind}`,
  );
  await persistRecoveryState(
    "restoring",
    initial,
    ownedExpected,
    ownedExpected,
    intent,
  );
  try {
    await sendRecordedMutation(page, intent);
  } catch {
    try {
      await replayRecordedMutation(page, intent);
    } catch {
      const observed = await observeUnresolvedMutation(page, initial, intent);
      throw new ScheduleMutationRecoveryError(observed, intent);
    }
  }
  try {
    const observed = await waitForSchedule(page, intent.intendedAfter);
    await persistRecoveryState("restoring", initial, observed, observed);
    return observed;
  } catch {
    const observed = await observeUnresolvedMutation(page, initial, intent);
    throw new ScheduleMutationRecoveryError(observed, intent);
  }
}

function scheduleUiOrigin(): string {
  const raw = process.env.E2E_BASE_URL;
  if (!raw) throw new Error("E2E_BASE_URL이 없습니다.");
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("E2E_BASE_URL 형식이 올바르지 않습니다.");
  }
  const expectedHash = lowercaseSha256(
    process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256,
    "E2E_C7_EXPECTED_UI_ORIGIN_SHA256",
  );
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash ||
    createHash("sha256").update(url.origin).digest("hex") !== expectedHash
  ) {
    throw new Error("schedule UI origin attestation이 불일치합니다.");
  }
  return url.origin;
}

function isExactScheduleMutationUrl(
  rawUrl: string,
  uiOrigin: string,
  requestPath: string,
): boolean {
  try {
    const url = new URL(rawUrl);
    return (
      url.origin === uiOrigin &&
      url.pathname === `/api/proxy${requestPath}` &&
      url.search === "" &&
      url.hash === ""
    );
  } catch {
    return false;
  }
}

function assertExactScheduleMutationRequest(
  request: Request,
  uiOrigin: string,
  method: "PATCH" | "POST",
  requestPath: string,
): void {
  if (
    request.method() !== method ||
    !isExactScheduleMutationUrl(request.url(), uiOrigin, requestPath)
  ) {
    throw new Error("schedule UI mutation origin/path/method가 일치하지 않습니다.");
  }
}

function isScheduleMutationResponse(
  response: Response,
  uiOrigin: string,
  method: "PATCH" | "POST",
  requestPath: string,
): boolean {
  return (
    response.request().method() === method &&
    isExactScheduleMutationUrl(response.url(), uiOrigin, requestPath)
  );
}

async function submitUiMutation(
  page: Page,
  initial: ScheduleSnapshot,
  ownedExpected: ScheduleSnapshot,
  kind: "command" | "patch",
  expectedBody: ScheduleMutationBody,
  operation: string,
  action: () => Promise<void>,
  assertUiResult: () => Promise<void>,
): Promise<ScheduleSnapshot> {
  await assertOwnedSnapshot(page, ownedExpected, operation);
  dagsterAttestation();
  const requestMethod = kind === "command" ? "POST" : "PATCH";
  const requestPath =
    kind === "command"
      ? `${schedulePath(SAFE_SCHEDULE)}/commands`
      : schedulePath(SAFE_SCHEDULE);
  const uiOrigin = scheduleUiOrigin();
  let interceptionStarted = false;
  let capturedIntent: ScheduleMutationIntent | null = null;
  let captureOpen = true;
  let initialAttemptCount = 0;
  let postCommitConfirmed = false;
  let replayAttemptCount = 0;
  let replayHandlerError: unknown = null;
  let resolveIntent!: (intent: ScheduleMutationIntent) => void;
  let rejectIntent!: (error: unknown) => void;
  const intentPromise = new Promise<ScheduleMutationIntent>((resolve, reject) => {
    resolveIntent = resolve;
    rejectIntent = reject;
  });
  void intentPromise.catch(() => undefined);
  let resolveResponseLoss!: () => void;
  let rejectResponseLoss!: (error: unknown) => void;
  const responseLossPromise = new Promise<void>((resolve, reject) => {
    resolveResponseLoss = resolve;
    rejectResponseLoss = reject;
  });
  void responseLossPromise.catch(() => undefined);
  let activeRouteHandlers = 0;
  const routeHandlerWaiters = new Set<() => void>();
  const waitForRouteHandlers = (): Promise<void> => {
    if (activeRouteHandlers === 0) return Promise.resolve();
    return new Promise<void>((resolve) => routeHandlerWaiters.add(resolve));
  };
  const routeMatcher = (url: URL): boolean =>
    isExactScheduleMutationUrl(url.href, uiOrigin, requestPath);
  const handleRoute = async (route: Route): Promise<void> => {
    const request = route.request();
    if (capturedIntent) {
      try {
        assertExactScheduleMutationRequest(
          request,
          uiOrigin,
          requestMethod,
          requestPath,
        );
        exactMutationBody(request.postDataJSON(), capturedIntent.requestBody);
        if (
          requireIdempotencyKey(request.headers()["idempotency-key"]) !==
          capturedIntent.idempotencyKey
        ) {
          throw new Error("schedule replay가 journal key와 일치하지 않습니다.");
        }
        replayAttemptCount += 1;
        if (replayAttemptCount !== 1) {
          throw new Error("schedule frozen UI replay가 정확히 한 번이 아닙니다.");
        }
        await route.continue();
      } catch (error) {
        replayHandlerError = error;
        await route.abort("failed").catch(() => undefined);
      }
      return;
    }
    interceptionStarted = true;
    try {
      assertExactScheduleMutationRequest(
        request,
        uiOrigin,
        requestMethod,
        requestPath,
      );
      initialAttemptCount += 1;
      if (initialAttemptCount !== 1) {
        throw new Error("schedule 최초 UI mutation이 정확히 한 번이 아닙니다.");
      }
      const actualBody = exactMutationBody(
        request.postDataJSON(),
        expectedBody,
      );
      const intent = mutationIntent(
        ownedExpected,
        kind,
        actualBody,
        request.headers()["idempotency-key"],
        operation,
      );
      await persistRecoveryState(
        "mutating",
        initial,
        ownedExpected,
        ownedExpected,
        intent,
      );
      if (!captureOpen) {
        rejectIntent(new Error("schedule intent capture가 이미 종료됐습니다."));
        rejectResponseLoss(
          new Error("schedule intent capture 종료 뒤 요청을 차단했습니다."),
        );
        await route.abort("failed").catch(() => undefined);
        return;
      }
      capturedIntent = intent;
      resolveIntent(intent);
      const upstreamResponse = await route.fetch();
      if (
        !isExactScheduleMutationUrl(
          upstreamResponse.url(),
          uiOrigin,
          requestPath,
        )
      ) {
        throw new Error("schedule post-commit response origin/path가 다릅니다.");
      }
      requireConfirmedMutation(
        await responseBody(upstreamResponse),
        intent,
      );
      postCommitConfirmed = true;
      await route.abort("failed");
      resolveResponseLoss();
    } catch (error) {
      rejectIntent(error);
      rejectResponseLoss(error);
      await route.abort("failed").catch(() => undefined);
    }
  };
  const routeHandler = async (route: Route): Promise<void> => {
    activeRouteHandlers += 1;
    try {
      await handleRoute(route);
    } finally {
      activeRouteHandlers -= 1;
      if (activeRouteHandlers === 0) {
        for (const resolve of routeHandlerWaiters) resolve();
        routeHandlerWaiters.clear();
      }
    }
  };
  await page.route(routeMatcher, routeHandler);
  let responseConfirmed = false;
  let primaryError: unknown;
  try {
    try {
      await action();
      const intent = await bounded(intentPromise, `${operation} intent capture`);
      await bounded(
        responseLossPromise,
        `${operation} post-commit browser response loss`,
      );
      if (!postCommitConfirmed || initialAttemptCount !== 1) {
        throw new Error(`${operation} post-commit response-loss 증거가 없습니다.`);
      }
      const frozenSubmission = page.getByTestId("schedule-frozen-submission");
      await expect(frozenSubmission).toBeVisible({
        timeout: UI_MUTATION_TIMEOUT,
      });
      await expect(frozenSubmission).toContainText(SAFE_SCHEDULE);
      await expect(frozenSubmission).toContainText(intent.idempotencyKey);
      const replayResponsePromise = page.waitForResponse(
        (response) =>
          isScheduleMutationResponse(
            response,
            uiOrigin,
            requestMethod,
            requestPath,
          ),
        { timeout: UI_MUTATION_TIMEOUT },
      );
      await robustClick(
        frozenSubmission.getByRole("button", {
          name: "동일 요청 재확인",
          exact: true,
        }),
        `${operation} frozen replay`,
      );
      requireConfirmedMutation(
        await responseBody(await replayResponsePromise),
        intent,
      );
      if (replayHandlerError !== null || replayAttemptCount !== 1) {
        throw new Error(`${operation} frozen UI same-key replay 증거가 없습니다.`);
      }
      await expect(frozenSubmission).toHaveCount(0, {
        timeout: UI_MUTATION_TIMEOUT,
      });
      responseConfirmed = true;
    } catch (error) {
      captureOpen = false;
      const recoveryIntent = capturedIntent as ScheduleMutationIntent | null;
      if (capturedIntent && !postCommitConfirmed) {
        await bounded(
          responseLossPromise,
          `${operation} in-flight post-commit 확인`,
        ).catch(() => undefined);
      }
      if (!recoveryIntent) {
        await persistMutationState(initial, ownedExpected);
        throw new Error(
          `${operation} 요청이 서버로 전송되기 전에 실패했습니다(interception=${interceptionStarted}).`,
          { cause: error },
        );
      }
      if (postCommitConfirmed) {
        let observed: ScheduleSnapshot;
        try {
          observed = await waitForSchedule(
            page,
            recoveryIntent.intendedAfter,
          );
        } catch {
          const drifted = await getScheduleSnapshot(page);
          await persistRecoveryState(
            "restore_failed",
            initial,
            drifted,
            drifted,
            recoveryIntent,
          );
          throw new ScheduleMutationRecoveryError(
            drifted,
            recoveryIntent,
            `${operation}은 confirmed됐지만 intended state와 concurrent drift를 구분할 수 없습니다.`,
          );
        }
        await persistMutationState(initial, observed);
        throw new ScheduleMutationRecoveryError(
          observed,
          null,
          `${operation}은 confirmed됐지만 exact frozen UI same-key recovery에 실패했습니다.`,
        );
      }
      const observed = await observeUnresolvedMutation(
        page,
        initial,
        recoveryIntent,
      );
      throw new ScheduleMutationRecoveryError(observed, recoveryIntent);
    }
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    captureOpen = false;
    const teardownErrors: unknown[] = [];
    await bounded(
      waitForRouteHandlers(),
      `${operation} route handler settlement`,
    ).catch((error: unknown) => teardownErrors.push(error));
    await page
      .unroute(routeMatcher, routeHandler)
      .catch((error: unknown) => teardownErrors.push(error));
    if (teardownErrors.length > 0) {
      throw new AggregateError(
        primaryError === undefined
          ? teardownErrors
          : [primaryError, ...teardownErrors],
        `${operation} primary/route cleanup 실패`,
      );
    }
  }

  const intent = capturedIntent as ScheduleMutationIntent | null;
  if (!responseConfirmed || !intent) {
    throw new Error(`${operation} 결과가 confirmed 상태가 아닙니다.`);
  }
  let observed: ScheduleSnapshot;
  try {
    observed = await waitForSchedule(page, intent.intendedAfter);
  } catch {
    const unresolved = await observeUnresolvedMutation(page, initial, intent);
    throw new ScheduleMutationRecoveryError(unresolved, intent);
  }
  await persistMutationState(initial, observed);
  try {
    await assertUiResult();
  } catch {
    throw new ScheduleMutationRecoveryError(
      observed,
      null,
      `${operation}은 confirmed됐지만 UI 결과 표시 검증에 실패했습니다.`,
    );
  }
  return observed;
}

async function submitUiCommand(
  page: Page,
  initial: ScheduleSnapshot,
  ownedExpected: ScheduleSnapshot,
  command: "start" | "stop",
): Promise<ScheduleSnapshot> {
  const reason = `C7 schedule ${command} live E2E`;
  return submitUiMutation(
    page,
    initial,
    ownedExpected,
    "command",
    { command, reason },
    `UI schedule ${command}`,
    async () => {
      await waitForScheduleControlsSettled(page, `pre-${command}`);
      const row = page.getByTestId(`pipeline-schedule-row-${SAFE_SCHEDULE}`);
      await row.getByLabel("명령 사유 (선택)").fill(reason);
      await robustClick(
        row.getByRole("button", {
          name: `${SAFE_SCHEDULE} 스케줄 ${command === "start" ? "시작" : "중지"}`,
        }),
        `${command} toggle`,
      );
      if (command === "start") {
        // 시작 확인은 AlertDialog(role=alertdialog)라 getByRole("dialog")로는 안 잡힌다.
        await robustClick(
          page
            .getByRole("alertdialog")
            .getByRole("button", { name: "스케줄 시작", exact: true }),
          "start confirm dialog",
        );
      }
    },
    async () => {
      await expect(page.getByTestId("schedule-command-result")).toContainText(
        `${command === "start" ? "스케줄 시작" : "스케줄 중지"} · 성공`,
      );
    },
  );
}

async function submitUiCron(
  page: Page,
  initial: ScheduleSnapshot,
  ownedExpected: ScheduleSnapshot,
  cron: string,
): Promise<ScheduleSnapshot> {
  const reason = "C7 schedule cron live E2E exact restore";
  return submitUiMutation(
    page,
    initial,
    ownedExpected,
    "patch",
    { cron_schedule: cron, reason },
    "UI schedule cron",
    async () => {
      await waitForScheduleControlsSettled(page, "pre-cron");
      const row = page.getByTestId(`pipeline-schedule-row-${SAFE_SCHEDULE}`);
      await robustClick(
        row.getByRole("button", { name: `${SAFE_SCHEDULE} cron 수정` }),
        "cron open",
      );
      const dialog = page.getByRole("dialog", { name: "스케줄 cron 수정" });
      await dialog.getByLabel("수정 사유").fill(reason);
      await dialog
        .getByRole("textbox", { name: "cron", exact: true })
        .fill(cron);
      await robustClick(
        dialog.getByRole("button", { name: "저장", exact: true }),
        "cron save",
      );
    },
    async () => {
      await expect(page.getByTestId("schedule-command-result")).toContainText(
        "cron 수정 · 성공",
      );
      // 복구 후에도 cron dialog가 열린 채 남으면 페이지가 inert가 되는 회귀를 직접
      // 검증한다(다음 op의 settle-gate에 의존하지 않는 순서-독립 체크).
      await expect(page.getByRole("dialog")).toHaveCount(0);
    },
  );
}

function safeFutureCron(initial: ScheduleSnapshot): string {
  const now = new Date();
  const month = ((now.getUTCMonth() + 6) % 12) + 1;
  const alternativeMonth = (month % 12) + 1;
  const candidate = `17 3 15 ${month} *`;
  return candidate === initial.overrideCronSchedule
    ? `23 4 16 ${alternativeMonth} *`
    : candidate;
}

async function restoreExactSchedule(
  page: Page,
  initial: ScheduleSnapshot,
  ownedExpected: ScheduleSnapshot,
  blockingIntent: ScheduleMutationIntent | null = null,
): Promise<ScheduleSnapshot> {
  const failures: unknown[] = [];
  if (blockingIntent) {
    await persistRecoveryState(
      "restore_failed",
      initial,
      ownedExpected,
      ownedExpected,
      blockingIntent,
    );
    throw new Error(
      "결과가 확정되지 않은 schedule mutation이 있어 새 key 복원과 restored 기록을 차단했습니다.",
    );
  }
  await persistRecoveryState(
    "restoring",
    initial,
    ownedExpected,
    ownedExpected,
  ).catch((error: unknown) => failures.push(error));

  let current = ownedExpected;
  let unresolvedIntent: ScheduleMutationIntent | null = null;
  let remoteRestoreAllowed = failures.length === 0;
  try {
    dagsterAttestation();
    await assertOwnedSnapshot(page, ownedExpected, "schedule restore");
    current = await getScheduleSnapshot(page);
  } catch (error) {
    failures.push(error);
    remoteRestoreAllowed = false;
  }

  if (remoteRestoreAllowed) {
    try {
      if (sameSnapshot(current, initial)) {
        await persistRecoveryState("restored", initial, current, current);
        return current;
      }
      if (
        current.defaultStatus !== initial.defaultStatus ||
        current.defaultCronSchedule !== initial.defaultCronSchedule ||
        current.name !== initial.name ||
        current.repositoryLocationName !== initial.repositoryLocationName ||
        current.repositoryName !== initial.repositoryName ||
        current.selectorId !== initial.selectorId ||
        current.stateId !== initial.stateId
      ) {
        throw new Error("schedule의 비가변 identity/default drift를 감지했습니다.");
      }

      const stateNeedsRestore =
        current.status !== initial.status || current.canReset !== initial.canReset;
      if (stateNeedsRestore) {
        const safeCron = safeFutureCron(initial);
        if (
          current.overrideCronSchedule !== safeCron ||
          current.effectiveCronSchedule !== safeCron ||
          current.overrideEffective !== true ||
          !current.overrideSaved
        ) {
          current = await directScheduleMutation(
            page,
            initial,
            current,
            "patch",
            { cron_schedule: safeCron },
          );
        }
        current = await directScheduleMutation(
          page,
          initial,
          current,
          "command",
          {
            command: initial.canReset
              ? initial.status === "RUNNING"
                ? "start"
                : "stop"
              : "reset",
          },
        );
      }

      // 상태 복원은 미래 cron에서 끝내고, 운영 cron은 항상 마지막 mutation으로 복원한다.
      if (
        current.overrideCronSchedule !== initial.overrideCronSchedule ||
        current.effectiveCronSchedule !== initial.effectiveCronSchedule ||
        current.overrideEffective !== initial.overrideEffective ||
        current.overrideSaved !== initial.overrideSaved
      ) {
        current = await directScheduleMutation(
          page,
          initial,
          current,
          "patch",
          { cron_schedule: initial.overrideCronSchedule },
        );
      }
    } catch (error) {
      failures.push(error);
      if (error instanceof ScheduleMutationRecoveryError) {
        current = error.ownedSnapshot;
        unresolvedIntent = error.blockingIntent;
      }
    }
  }

  let restored: ScheduleSnapshot | null = null;
  if (failures.length === 0 && !unresolvedIntent) {
    try {
      restored = await getScheduleSnapshot(page);
      if (!sameSnapshot(restored, initial)) {
        throw new Error("schedule 최초 상태가 exact restore되지 않았습니다.");
      }
    } catch (error) {
      failures.push(error);
    }
  }

  if (restored && failures.length === 0) {
    await persistRecoveryState("restored", initial, restored, restored).catch(
      (error: unknown) => failures.push(error),
    );
  }
  if (failures.length > 0 || !restored) {
    await persistRecoveryState(
      "restore_failed",
      initial,
      restored,
      current,
      unresolvedIntent,
    ).catch((error: unknown) => failures.push(error));
    throw new Error(
      `schedule restore가 fail-closed 처리되었습니다(failures=${failures.length}).`,
    );
  }
  return restored;
}

test.describe("C7 schedule destructive live E2E", () => {
  test("실제 UI start/stop·cron 조작을 검증하고 최초 상태로 정확히 복원한다", async ({
    page,
  }, testInfo) => {
    requireScheduleGates(testInfo);
    test.setTimeout(TEST_TIMEOUT);
    await assertScheduleStateFileClaimable();
    await bootstrapC7SameOriginPage(
      page,
      `/ops/pipeline?tab=schedules&schedule=${SAFE_SCHEDULE}`,
    );
    page.setDefaultTimeout(UI_MUTATION_TIMEOUT);
    await expect(page.getByRole("heading", { name: "파이프라인" })).toBeVisible();

    const initialSchedule = await getSchedule(page);
    if (
      (initialSchedule.recent_ticks ?? []).some(
        (tick) => tick.status === "STARTED",
      )
    ) {
      throw new Error(
        "schedule에 진행 중인 Dagster tick이 있어 destructive 조작을 차단했습니다.",
      );
    }
    const initial = snapshotOf(initialSchedule);
    if (initial.overrideEffective === false) {
      throw new Error(
        "schedule cron override가 아직 실제 반영되지 않아 destructive 조작을 차단했습니다.",
      );
    }
    let ownedExpected = initial;
    let blockingIntent: ScheduleMutationIntent | null = null;
    await persistRecoveryState("snapshotted", initial, initial, ownedExpected);
    const temporaryCron = safeFutureCron(initial);
    let primaryError: unknown;

    try {
      await persistRecoveryState("mutating", initial, initial, ownedExpected);
      if (initial.status === "RUNNING") {
        ownedExpected = await submitUiCommand(
          page,
          initial,
          ownedExpected,
          "stop",
        );
        await persistMutationState(initial, ownedExpected);
      }

      // STOPPED 상태에서 충분히 먼 미래 cron을 먼저 적용해야 start/stop 사이에
      // provider schedule tick이 새로 생기지 않는다.
      ownedExpected = await submitUiCron(
        page,
        initial,
        ownedExpected,
        temporaryCron,
      );
      await persistMutationState(initial, ownedExpected);
      ownedExpected = await submitUiCommand(
        page,
        initial,
        ownedExpected,
        "start",
      );
      await persistMutationState(initial, ownedExpected);
      ownedExpected = await submitUiCommand(
        page,
        initial,
        ownedExpected,
        "stop",
      );
      await persistMutationState(initial, ownedExpected);

      expect(ownedExpected.status).toBe("STOPPED");
      expect(ownedExpected.effectiveCronSchedule).toBe(temporaryCron);
      expect(ownedExpected.overrideCronSchedule).toBe(temporaryCron);
      expect(ownedExpected.overrideEffective).toBe(true);
    } catch (error) {
      if (error instanceof ScheduleMutationRecoveryError) {
        ownedExpected = error.ownedSnapshot;
        blockingIntent = error.blockingIntent;
      }
      primaryError = error;
      throw error;
    } finally {
      try {
        const restored = await restoreExactSchedule(
          page,
          initial,
          ownedExpected,
          blockingIntent,
        );
        expect(restored).toEqual(initial);
      } catch (restoreError) {
        if (primaryError !== undefined) {
          throw new AggregateError(
            [primaryError, restoreError],
            "schedule primary/restore 실패",
          );
        }
        throw restoreError;
      }
    }
  });
});
