import { createHash, randomUUID } from "node:crypto";
import { chmod, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  expect,
  test,
  type Page,
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
type ScheduleTickIdentity = {
  cursor: string | null;
  endTimestamp: number | null;
  errorClass: string | null;
  errorMessage: string | null;
  runIds: string[];
  runKeys: string[];
  skipReason: string | null;
  status: string;
  tickId: string;
  timestamp: number;
};
type ScheduleSnapshot = {
  canReset: boolean;
  defaultCronSchedule: string;
  defaultStatus: StableScheduleStatus;
  effectiveCronSchedule: string;
  name: string;
  overrideCronSchedule: string | null;
  overrideEffective: boolean | null;
  overrideSaved: boolean;
  recentTicks: ScheduleTickIdentity[];
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

function tickIdentity(
  tick: components["schemas"]["DagsterInstigationTick"],
): ScheduleTickIdentity {
  return {
    cursor: tick.cursor ?? null,
    endTimestamp: tick.end_timestamp ?? null,
    errorClass: tick.error?.class_name ?? null,
    errorMessage: tick.error?.message ?? null,
    runIds: [...(tick.run_ids ?? [])],
    runKeys: [...(tick.run_keys ?? [])],
    skipReason: tick.skip_reason ?? null,
    status: tick.status,
    tickId: tick.tick_id,
    timestamp: tick.timestamp,
  };
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
    recentTicks: (schedule.recent_ticks ?? []).map(tickIdentity),
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
    await rename(temporary, destination);
    await chmod(destination, 0o600);
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
    canReset: command === "reset" ? false : status !== before.defaultStatus,
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
  response: Response,
): Promise<PipelineScheduleCommandResponse> {
  if (response.status() !== 200) {
    throw new Error("schedule UI mutation HTTP status가 200이 아닙니다.");
  }
  return (await response.json()) as PipelineScheduleCommandResponse;
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

function isScheduleMutationResponse(
  response: Response,
  method: "PATCH" | "POST",
  suffix: string,
): boolean {
  let pathname: string;
  try {
    pathname = new URL(response.url()).pathname;
  } catch {
    return false;
  }
  return response.request().method() === method && pathname.endsWith(suffix);
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
  let interceptionStarted = false;
  let capturedIntent: ScheduleMutationIntent | null = null;
  let resolveIntent!: (intent: ScheduleMutationIntent) => void;
  let rejectIntent!: (error: unknown) => void;
  const intentPromise = new Promise<ScheduleMutationIntent>((resolve, reject) => {
    resolveIntent = resolve;
    rejectIntent = reject;
  });
  const routeMatcher = (url: URL): boolean =>
    url.pathname.endsWith(requestPath);
  const routeHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.method() !== requestMethod) {
      await route.continue();
      return;
    }
    if (capturedIntent) {
      try {
        exactMutationBody(request.postDataJSON(), capturedIntent.requestBody);
        if (
          requireIdempotencyKey(request.headers()["idempotency-key"]) !==
          capturedIntent.idempotencyKey
        ) {
          throw new Error("schedule replay가 journal key와 일치하지 않습니다.");
        }
        await route.continue();
      } catch {
        await route.abort("failed").catch(() => undefined);
      }
      return;
    }
    interceptionStarted = true;
    try {
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
      capturedIntent = intent;
      resolveIntent(intent);
      await route.continue();
    } catch (error) {
      rejectIntent(error);
      await route.abort("failed").catch(() => undefined);
    }
  };
  await page.route(routeMatcher, routeHandler);
  const responsePromise = page.waitForResponse((response) =>
    isScheduleMutationResponse(response, requestMethod, requestPath),
  );
  let responseConfirmed = false;
  try {
    await action();
    const intent = await intentPromise;
    requireConfirmedMutation(await responseBody(await responsePromise), intent);
    responseConfirmed = true;
  } catch {
    void responsePromise.catch(() => undefined);
    if (!capturedIntent && interceptionStarted) {
      await intentPromise.catch(() => undefined);
    }
    if (!capturedIntent) {
      await persistMutationState(initial, ownedExpected);
      throw new Error(`${operation} 요청이 서버로 전송되기 전에 실패했습니다.`);
    }
    let replayConfirmed = false;
    try {
      await replayRecordedMutation(page, capturedIntent);
      replayConfirmed = true;
      const frozenSubmission = page.getByTestId("schedule-frozen-submission");
      if (await frozenSubmission.isVisible()) {
        const frozenReplayResponse = page.waitForResponse((response) =>
          isScheduleMutationResponse(response, requestMethod, requestPath),
        );
        await frozenSubmission
          .getByRole("button", { name: "동일 요청 재확인", exact: true })
          .click();
        requireConfirmedMutation(
          await responseBody(await frozenReplayResponse),
          capturedIntent,
        );
      }
      responseConfirmed = true;
    } catch {
      if (replayConfirmed) {
        const observed = await waitForSchedule(
          page,
          capturedIntent.intendedAfter,
        );
        await persistMutationState(initial, observed);
        throw new ScheduleMutationRecoveryError(
          observed,
          null,
          `${operation} same-key replay는 confirmed됐지만 UI frozen 요청 해제에 실패했습니다.`,
        );
      }
      const observed = await observeUnresolvedMutation(
        page,
        initial,
        capturedIntent,
      );
      throw new ScheduleMutationRecoveryError(observed, capturedIntent);
    }
  } finally {
    await page.unroute(routeMatcher, routeHandler);
  }

  const intent = capturedIntent;
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
      const row = page.getByTestId(`pipeline-schedule-row-${SAFE_SCHEDULE}`);
      await row.getByLabel("명령 사유 (선택)").fill(reason);
      await row
        .getByRole("button", {
          name: `${SAFE_SCHEDULE} 스케줄 ${command === "start" ? "시작" : "중지"}`,
        })
        .click();
      if (command === "start") {
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "스케줄 시작", exact: true })
          .click();
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
      const row = page.getByTestId(`pipeline-schedule-row-${SAFE_SCHEDULE}`);
      await row
        .getByRole("button", { name: `${SAFE_SCHEDULE} cron 수정` })
        .click();
      const dialog = page.getByRole("dialog", { name: "스케줄 cron 수정" });
      await dialog.getByLabel("수정 사유").fill(reason);
      await dialog
        .getByRole("textbox", { name: "cron", exact: true })
        .fill(cron);
      await dialog.getByRole("button", { name: "저장", exact: true }).click();
    },
    async () => {
      await expect(page.getByTestId("schedule-command-result")).toContainText(
        "cron 수정 · 성공",
      );
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
    await bootstrapC7SameOriginPage(
      page,
      `/ops/pipeline?tab=schedules&schedule=${SAFE_SCHEDULE}`,
    );
    await expect(page.getByRole("heading", { name: "파이프라인" })).toBeVisible();

    const initial = await getScheduleSnapshot(page);
    if (initial.recentTicks.some((tick) => tick.status === "STARTED")) {
      throw new Error(
        "schedule에 진행 중인 Dagster tick이 있어 destructive 조작을 차단했습니다.",
      );
    }
    if (initial.overrideEffective === false) {
      throw new Error(
        "schedule cron override가 아직 실제 반영되지 않아 destructive 조작을 차단했습니다.",
      );
    }
    let ownedExpected = initial;
    let blockingIntent: ScheduleMutationIntent | null = null;
    await persistRecoveryState("snapshotted", initial, initial, ownedExpected);
    const temporaryCron = safeFutureCron(initial);

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
      const tickBaseline = ownedExpected.recentTicks;
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
      expect(ownedExpected.recentTicks).toEqual(tickBaseline);

      expect(ownedExpected.status).toBe("STOPPED");
      expect(ownedExpected.effectiveCronSchedule).toBe(temporaryCron);
      expect(ownedExpected.overrideCronSchedule).toBe(temporaryCron);
      expect(ownedExpected.overrideEffective).toBe(true);
    } catch (error) {
      if (error instanceof ScheduleMutationRecoveryError) {
        ownedExpected = error.ownedSnapshot;
        blockingIntent = error.blockingIntent;
      }
      throw error;
    } finally {
      const restored = await restoreExactSchedule(
        page,
        initial,
        ownedExpected,
        blockingIntent,
      );
      expect(restored).toEqual(initial);
    }
  });
});
