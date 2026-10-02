import { randomUUID } from "node:crypto";
import { chmod, open, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import type { components } from "../../src/api/types";

import {
  bootstrapC7SameOriginPage,
  browserFetch,
  requireBody,
  safeHttpDiagnostic,
  type BrowserFetchResult,
} from "./_ops-c7-admin-api";
import {
  QUEUE_SENSOR_NAME,
  assertQueueWorkerOperational,
  dagsterGraphqlEndpoint,
  readQueueWorkerRun,
} from "./_ops-c7-dagster";

// C7 기준 5(2026-10-01 KMA lane과 함께 사라졌던 것)의 복원: exact-scope feature update
// request 하나 → Map queue sensor(`feature_update_request_queue_sensor`)가 집음 → 공유 plane의
// `feature_update_request_worker` run → API terminal `done` + Dagster run `SUCCESS`.
//
// 대상은 **upstream 호출이 0인** dataset 하나로 고정한다: `kor-travel-transport` /
// `transport_airports`, operation `feature_place_transport_airports_job`. fetcher
// (`provider_fetchers.py::fetch_transport_airports`)는 krairport의 번들 정적 공항 목록만
// 읽는다(keyless, network 없음 — `tests/unit/test_c7_prod_live_runner_contract.py`가 결박).
//
// **이것은 실제 prod 쓰기다.** worker가 번들 공항(2026-10 기준 활성 15곳)을 place feature로
// 적재한다 — 같은 번들이면 같은 feature로 수렴하는 idempotent upsert이고(authoritative
// snapshot), 주소는 kor-travel-geo reverse geocode로 채운다(내부 서비스, data.go.kr 쿼터 0).
// 지울 것이 없으므로 "복원"은 소유 request가 terminal이고 그 run이 증명됐다는 뜻이다.
//
// scope는 `provider_dataset` × `dataset_wide`다 — 이 dataset이 선언한 유일한 scope라 정확히
// 한 membership만 고정된다. 같은 membership에 다른 활성 request가 있으면 API가 409
// (`ACTIVE_SCOPE_CONFLICT`)로 거절하므로, 만들기 전에 그 dataset의 active execution이 없음을
// 확인하고, 그래도 409면 남의 실행을 건드리지 않고 멈춘다. reason에 run id를 넣어 계획이
// 매 실행 달라지게 한다 — 남의 활성 request를 조용히 재사용(200)하는 길을 막는다.

type FeatureUpdateRequestCreateRequest =
  components["schemas"]["FeatureUpdateRequestCreateRequest"];
type FeatureUpdateRequestCreateResponse =
  components["schemas"]["FeatureUpdateRequestCreateResponse"];
type PipelineExecutionDetailResponse =
  components["schemas"]["PipelineExecutionDetailResponse"];
type OpsDatasetsGridResponse = components["schemas"]["OpsDatasetsGridResponse"];
type OpsDatasetGridRow = components["schemas"]["OpsDatasetGridRow"];
type PipelineCancellationResponse =
  components["schemas"]["PipelineCancellationResponse"];

/** 러너가 `E2E_C7_UPDATE_REQUEST_OPERATION`으로 같은 값을 선언해야 실행한다. */
const SAFE_UPDATE_OPERATION = "feature_place_transport_airports_job" as const;
const SAFE_PROVIDER = "kor-travel-transport" as const;
const SAFE_DATASET_KEY = "transport_airports" as const;
const DATASET_WIDE_SYNC_SCOPE = "dataset_wide" as const;

const PIPELINE_REQUESTS_PATH = "/v1/ops/pipeline/requests";
const TEST_TIMEOUT = 30 * 60 * 1000;
const DATASET_GRID_TIMEOUT_MS = 60_000;
/** sensor 간격은 15초다. worker pool 대기까지 넉넉히 둔다. */
const DISPATCH_TIMEOUT_MS = 10 * 60 * 1000;
const TERMINAL_TIMEOUT_MS = 15 * 60 * 1000;
const DAGSTER_SETTLEMENT_TIMEOUT_MS = 2 * 60 * 1000;
const CLEANUP_TERMINAL_TIMEOUT_MS = 10 * 60 * 1000;
const POLL_INTERVAL_MS = 1_000;
const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"]);
const DAGSTER_TERMINAL_STATUSES = new Set(["SUCCESS", "FAILURE", "CANCELED"]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RUN_ID = `c7-update-request-${Date.now()}-${Math.random()
  .toString(36)
  .slice(2, 8)}`;

/** host orchestrator가 첫 durable write 전에 깔아 두는 placeholder. */
const ORCHESTRATOR_PLACEHOLDER = { phase: "orchestrator_pending", version: 1 };

type RequestJournalPhase =
  | "create_intent"
  | "create_response_lost"
  | "create_rejected"
  | "submitted"
  | "dispatched"
  | "restored"
  | "restore_failed";

/** `requests.json` v1. 러너의 `state_is_exact_restored requests`가 같은 키 집합을 요구한다. */
type RequestJournal = {
  dagster_run_id: string | null;
  dagster_run_status: string | null;
  generation: number | null;
  idempotency_key: string;
  job_id: string | null;
  operation_key: string;
  phase: RequestJournalPhase;
  provider_dataset_id: number;
  request_id: string | null;
  run_id: string;
  sensor_name: string | null;
  terminal_status: string | null;
  updated_at: string;
  version: 1;
};

test.describe.configure({ mode: "serial", retries: 0 });

function stateFile(): string {
  const configured = process.env.E2E_C7_REQUEST_STATE_FILE;
  if (!configured || !path.isAbsolute(configured)) {
    throw new Error(
      "E2E_C7_REQUEST_STATE_FILE은 host orchestrator가 지정한 절대 경로여야 합니다.",
    );
  }
  return configured;
}

function requireUpdateRequestGates(testInfo: TestInfo): void {
  test.skip(
    process.env.E2E_C7_UPDATE_REQUEST_WRITE !== "1",
    "E2E_C7_UPDATE_REQUEST_WRITE=1이 없어 prod feature update request를 만들지 않습니다.",
  );
  // opt-in이 있으면 나머지 전제는 skip이 아니라 실패다 — 러너 아래에서 조용히 건너뛰면
  // 기준 5가 증명 없이 초록이 된다(러너는 journal `restored`도 따로 요구한다).
  const missing = ["E2E_LIVE_ALLOW_PROD", "E2E_ADMIN_WRITE"].filter(
    (name) => process.env[name] !== "1",
  );
  if (missing.length > 0) {
    throw new Error(`${missing.join(", ")}=1이 필요합니다.`);
  }
  if (process.env.E2E_C7_UPDATE_REQUEST_OPERATION !== SAFE_UPDATE_OPERATION) {
    throw new Error(
      `E2E_C7_UPDATE_REQUEST_OPERATION은 exact allowlist ${SAFE_UPDATE_OPERATION}이어야 합니다.`,
    );
  }
  if (testInfo.config.workers !== 1) {
    throw new Error("update request live E2E는 실제 workers=1이어야 합니다.");
  }
  if (testInfo.project.retries !== 0) {
    throw new Error("update request live E2E는 실제 retries=0이어야 합니다.");
  }
  dagsterGraphqlEndpoint();
  stateFile();
}

function exactJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

async function assertJournalClaimable(): Promise<void> {
  let raw: string;
  try {
    raw = await readFile(stateFile(), "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw new Error("C7 request journal을 읽지 못했습니다 (values redacted)");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("C7 request journal이 손상되었습니다");
  }
  if (!exactJson(parsed, ORCHESTRATOR_PLACEHOLDER)) {
    throw new Error(
      "이전 C7 request journal이 남아 있습니다; audited recovery가 필요합니다",
    );
  }
}

async function writeRequestJournal(journal: RequestJournal): Promise<void> {
  const target = stateFile();
  const directory = path.dirname(target);
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  const payload: RequestJournal = { ...journal, updated_at: new Date().toISOString() };
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
    await rename(temporary, target);
    await chmod(target, 0o600);
    const stateHandle = await open(target, "r");
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
  } catch {
    await rm(temporary, { force: true }).catch(() => undefined);
    throw new Error("C7 request journal 기록 실패 (values redacted)");
  }
}

/**
 * `/v1/ops/datasets` 그리드에서 allowlist operation의 행을 찾는다. operation 하나에
 * 행이 정확히 하나이고 그것이 krairport `dataset_wide`여야 한다 — 다른 scope가 선언되면
 * "exact" 전제가 깨진 것이니 멈춘다.
 */
async function readSafeDatasetRow(page: Page): Promise<OpsDatasetGridRow> {
  const grid = requireBody(
    await browserFetch<OpsDatasetsGridResponse>(page, "/v1/ops/datasets", {
      timeoutMs: DATASET_GRID_TIMEOUT_MS,
    }),
    200,
  );
  const rows = grid.data.items.filter(
    (row) => row.operation_key === SAFE_UPDATE_OPERATION,
  );
  if (rows.length !== 1) {
    throw new Error(
      `allowlist operation의 dataset 행이 정확히 하나가 아니다(observed=${rows.length})`,
    );
  }
  const row = rows[0] as OpsDatasetGridRow;
  if (
    row.provider !== SAFE_PROVIDER ||
    row.dataset_key !== SAFE_DATASET_KEY ||
    row.sync_scope !== DATASET_WIDE_SYNC_SCOPE ||
    row.catalog_state !== "canonical" ||
    !Number.isSafeInteger(row.provider_dataset_id) ||
    row.provider_dataset_id <= 0
  ) {
    throw new Error("allowlist operation의 dataset identity가 krairport dataset_wide가 아니다");
  }
  return row;
}

function buildRequest(providerDatasetId: number): FeatureUpdateRequestCreateRequest {
  return {
    scope: {
      type: "provider_dataset",
      provider_dataset_id: providerDatasetId,
      sync_scope: DATASET_WIDE_SYNC_SCOPE,
      operation_key: SAFE_UPDATE_OPERATION,
    },
    run_mode: "queued",
    priority: 50,
    reason: `C7 ${RUN_ID} queue sensor barrier (krairport bundled, zero upstream)`,
  };
}

async function getRequestDetail(
  page: Page,
  requestId: string,
): Promise<BrowserFetchResult<PipelineExecutionDetailResponse>> {
  return browserFetch<PipelineExecutionDetailResponse>(
    page,
    `/v1/ops/pipeline/executions/update_request/${encodeURIComponent(requestId)}`,
  );
}

async function createOwnedRequest(
  page: Page,
  body: FeatureUpdateRequestCreateRequest,
  journal: RequestJournal,
): Promise<FeatureUpdateRequestCreateResponse> {
  const submit = () =>
    browserFetch<FeatureUpdateRequestCreateResponse>(page, PIPELINE_REQUESTS_PATH, {
      method: "POST",
      body,
      headers: { "Idempotency-Key": journal.idempotency_key },
    });
  let result: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  let replayed = false;
  try {
    result = await submit();
  } catch {
    // 응답 유실: 같은 key의 재전송은 같은 request를 돌려준다(새로 만들지 않는다).
    journal.phase = "create_response_lost";
    await writeRequestJournal(journal);
    replayed = true;
    result = await submit();
  }
  if (result.status === 409) {
    journal.phase = "create_rejected";
    await writeRequestJournal(journal);
    throw new Error(
      `같은 krairport membership에 다른 활성 request가 있어 409로 거절됐다 — 남의 실행은 건드리지 않는다: ${safeHttpDiagnostic(
        result,
      )}`,
    );
  }
  const accepted =
    result.status === 201 ||
    (replayed && result.status === 200 && result.body?.idempotent_replay === true);
  if (!accepted || result.body === null) {
    throw new Error(`C7 request 생성 응답 계약 불일치: ${safeHttpDiagnostic(result)}`);
  }
  const created = result.body;
  expect(created.reused_active_request).toBe(false);
  return created;
}

async function waitForDispatch(
  page: Page,
  requestId: string,
): Promise<{ detail: PipelineExecutionDetailResponse }> {
  const deadline = Date.now() + DISPATCH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const detail = requireBody(await getRequestDetail(page, requestId), 200);
    const status = detail.data.execution.status;
    if (detail.data.execution.dagster_run_id) return { detail };
    if (TERMINAL_STATUSES.has(status)) {
      throw new Error(`request가 Dagster run 없이 ${status}로 끝났다`);
    }
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  throw new Error("queue sensor가 제한 시간 안에 request를 집지 않았다");
}

async function waitForTerminal(
  page: Page,
  requestId: string,
  timeoutMs: number,
): Promise<PipelineExecutionDetailResponse | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const detail = requireBody(await getRequestDetail(page, requestId), 200);
    if (TERMINAL_STATUSES.has(detail.data.execution.status)) return detail;
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  return null;
}

async function waitForDagsterTerminal(
  page: Page,
  identity: { generation: number; requestId: string; runId: string },
): Promise<{ sensorName: string; status: string }> {
  const deadline = Date.now() + DAGSTER_SETTLEMENT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const run = await readQueueWorkerRun(identity);
    if (run !== null && DAGSTER_TERMINAL_STATUSES.has(run.status)) return run;
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  throw new Error("Dagster worker run이 제한 시간 안에 terminal이 되지 않았다");
}

/**
 * 실패 경로 정리: 소유 request를 terminal로 보낸다. queued로 남으면 취소하고, running이면
 * 끝나기를 기다린다(worker는 번들 데이터만 읽어 짧다). 성공 증명이 아니므로 journal은
 * `restored`가 아니다 — 러너가 BLOCKED를 남기고 운영자가 확인한다.
 */
async function settleOwnedRequestAfterFailure(
  page: Page,
  journal: RequestJournal,
): Promise<void> {
  if (journal.request_id === null) return;
  let detail = await waitForTerminal(
    page,
    journal.request_id,
    CLEANUP_TERMINAL_TIMEOUT_MS,
  ).catch(() => null);
  if (detail === null) {
    const current = await getRequestDetail(page, journal.request_id).catch(() => null);
    if (current?.body?.data.execution.status === "queued") {
      await browserFetch<PipelineCancellationResponse>(
        page,
        `/v1/ops/pipeline/executions/update_request/${encodeURIComponent(
          journal.request_id,
        )}/cancel`,
        { method: "POST", body: { reason: `C7 ${RUN_ID} cleanup` } },
      ).catch(() => null);
      detail = await waitForTerminal(
        page,
        journal.request_id,
        CLEANUP_TERMINAL_TIMEOUT_MS,
      ).catch(() => null);
    }
  }
  journal.terminal_status = detail?.data.execution.status ?? null;
  journal.phase = "restore_failed";
  await writeRequestJournal(journal);
}

test.describe("C7 feature update request → queue sensor → worker run live E2E", () => {
  test("krairport exact scope request를 queue sensor가 집어 worker run이 SUCCESS로 끝난다", async ({
    page,
  }, testInfo) => {
    requireUpdateRequestGates(testInfo);
    test.setTimeout(TEST_TIMEOUT);
    await assertJournalClaimable();
    await bootstrapC7SameOriginPage(page, "/ops/pipeline");

    // 1. 읽기 전용 preflight: worker job 정의·sensor RUNNING, 대상 dataset identity, 활성 실행 0.
    await assertQueueWorkerOperational();
    const before = await readSafeDatasetRow(page);
    if (before.active_execution !== null) {
      throw new Error(
        "krairport dataset_wide에 활성 실행이 있다 — 끝난 뒤 다시 실행한다(409 회피, 남의 실행 불간섭)",
      );
    }

    const body = buildRequest(before.provider_dataset_id);
    const journal: RequestJournal = {
      dagster_run_id: null,
      dagster_run_status: null,
      generation: null,
      idempotency_key: randomUUID(),
      job_id: null,
      operation_key: SAFE_UPDATE_OPERATION,
      phase: "create_intent",
      provider_dataset_id: before.provider_dataset_id,
      request_id: null,
      run_id: RUN_ID,
      sensor_name: null,
      terminal_status: null,
      updated_at: "",
      version: 1,
    };
    await writeRequestJournal(journal);

    let succeeded = false;
    try {
      // 2. 생성: queued, Dagster run 없음, membership은 정확히 한 행.
      const created = await createOwnedRequest(page, body, journal);
      const record = created.data;
      expect(UUID_PATTERN.test(record.request_id)).toBe(true);
      journal.request_id = record.request_id;
      journal.job_id = record.job_id;
      journal.generation = record.generation;
      journal.phase = "submitted";
      await writeRequestJournal(journal);
      expect(record.run_mode).toBe("queued");
      expect(record.reason).toBe(body.reason);
      expect(record.scope).toEqual(body.scope);
      expect(record.dataset_memberships).toEqual([
        {
          operation_key: SAFE_UPDATE_OPERATION,
          provider_dataset_id: before.provider_dataset_id,
          sync_scope: DATASET_WIDE_SYNC_SCOPE,
        },
      ]);
      if (created.idempotent_replay !== true) {
        // 생성 transaction이 돌려준 원본 상태: API는 dispatch하지 않는다.
        expect(record.status).toBe("queued");
        expect(record.dagster_run_id).toBeNull();
      }

      // 3. barrier: queued → (running) + Dagster run id. 그 run이 Map location의 queue
      //    sensor가 띄운 worker run이고 이 request·generation을 실행한다.
      //    queued 관측은 위 생성 응답이 맡는다 — 빠른 worker는 첫 poll 전에 done까지 간다.
      const { detail: dispatched } = await waitForDispatch(page, record.request_id);
      const runId = dispatched.data.execution.dagster_run_id as string;
      expect(dispatched.data.execution.kind).toBe("update_request");
      expect(dispatched.data.execution.id).toBe(record.request_id);
      expect(dispatched.data.execution.job_id).toBe(record.job_id);
      const identity = {
        generation: record.generation,
        requestId: record.request_id,
        runId,
      };
      const firstSeen = await readQueueWorkerRun(identity);
      journal.dagster_run_id = runId;
      journal.sensor_name = firstSeen?.sensorName ?? null;
      journal.phase = "dispatched";
      await writeRequestJournal(journal);

      // 4. API terminal `done`, 같은 run, 같은 generation.
      const terminal = await waitForTerminal(page, record.request_id, TERMINAL_TIMEOUT_MS);
      if (terminal === null) {
        throw new Error("request가 제한 시간 안에 terminal이 되지 않았다");
      }
      journal.terminal_status = terminal.data.execution.status;
      expect(terminal.data.execution.status).toBe("done");
      expect(terminal.data.execution.dagster_run_id).toBe(runId);
      const updateRequest = terminal.data.update_request;
      expect(updateRequest?.request_id).toBe(record.request_id);
      expect(updateRequest?.dagster_run_id).toBe(runId);
      expect(updateRequest?.generation).toBe(record.generation);

      // 5. Dagster run SUCCESS (C7 Dagster client, 읽기 전용).
      const run = await waitForDagsterTerminal(page, identity);
      journal.sensor_name = run.sensorName;
      journal.dagster_run_status = run.status;
      expect(run.sensorName).toBe(QUEUE_SENSOR_NAME);
      expect(run.status).toBe("SUCCESS");

      // 6. 대상 dataset에 남은 활성 실행이 없고 최신 실행이 이 request다.
      const after = await readSafeDatasetRow(page);
      expect(after.provider_dataset_id).toBe(before.provider_dataset_id);
      expect(after.active_execution).toBeNull();
      expect(after.latest_execution?.id).toBe(record.request_id);
      expect(after.latest_execution?.status).toBe("done");

      journal.phase = "restored";
      await writeRequestJournal(journal);
      succeeded = true;
    } finally {
      if (!succeeded) {
        // 정리 실패가 원래 실패를 가리지 않게 삼킨다 — journal이 `restored`가 아니므로
        // 러너는 어느 쪽이든 BLOCKED를 남긴다.
        await settleOwnedRequestAfterFailure(page, journal).catch(() => undefined);
      }
    }
  });
});
