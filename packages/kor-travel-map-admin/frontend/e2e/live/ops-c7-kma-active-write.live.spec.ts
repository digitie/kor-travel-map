import { randomUUID } from "node:crypto";

import {
  expect,
  test,
  type Page,
  type Request,
  type Route,
  type TestInfo,
} from "@playwright/test";

import {
  KMA_DATASET_KEY,
  KMA_PROVIDER,
  assertKmaDagsterWorkerJobDefinition,
  assertExactKmaPreviewResponse,
  assertExactOwnedTargetsAtServer,
  assertKmaOnlyTerminalProviderScopes,
  bootstrapC7SameOriginPage,
  buildKmaRequest,
  buildPoiTargetBody,
  createCleanupState,
  createKmaRequest,
  DATASET_DETAIL_FETCH_TIMEOUT_MS,
  destructiveGateBlocker,
  exactDatasetUiPath,
  getExactDatasetDetail,
  getRequestDetail,
  journalExactUiKmaCreateRequest,
  previewBody,
  putTrackedTarget,
  rediscoverExactActiveOrSettledRequest,
  REQUEST_TERMINAL_TIMEOUT,
  requireBody,
  resolveTrackedUiKmaCreateResponse,
  waitForTerminal,
  withC7Cleanup,
  type BrowserFetchResult,
  type FeatureUpdateRequestCreateRequest,
  type FeatureUpdateRequestCreateResponse,
  type OpsDatasetDetailResponse,
  type PipelineExecutionDetailResponse,
  type TargetRef,
} from "./_ops-c7-admin-api";

const TEST_TIMEOUT = 60 * 60 * 1000;
const ROUTE_TIMEOUT = 30_000;
// 51-req overflow 루프를 제거하고 3-request 시나리오만 남겼으므로 base rollover
// 안전 창을 30분 → 5분으로 축소한다(과거 30분은 51회 루프가 요구하던 값).
const MINIMUM_START_WINDOW_MS = 5 * 60 * 1000;
const LOWERCASE_SHA256_PATTERN = /^[0-9a-f]{64}$/;
const KMA_BASE_DATETIME_PATTERN = /^([0-9]{4})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})$/;
const RUN_ID = `c7-active-${Date.now()}-${Math.random()
  .toString(36)
  .slice(2, 8)}`;

type KmaExecutionMetadata = Record<string, unknown> & {
  base_datetime: string;
  grids_dropped: number;
  grids_fetched: number;
  grids_total: number;
  membership_fingerprint: string;
  skipped: boolean;
};

test.describe.configure({ mode: "serial", retries: 0 });

function requireDestructiveGates(testInfo: TestInfo): void {
  const blocker = destructiveGateBlocker(testInfo);
  test.skip(blocker !== null, blocker ?? "");
}

/** 초단기실황의 다음 사용 가능 base는 KST 매시 40분에 바뀐다. */
function millisecondsUntilNextBaseRollover(now = Date.now()): number {
  const kst = new Date(now + 9 * 60 * 60 * 1000);
  const minute = kst.getUTCMinutes();
  const second = kst.getUTCSeconds();
  const millisecond = kst.getUTCMilliseconds();
  const minutes = minute < 40 ? 40 - minute : 100 - minute;
  return (
    minutes * 60 * 1000 - second * 1000 - millisecond
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isCanonicalKmaBaseDatetime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const matched = KMA_BASE_DATETIME_PATTERN.exec(value);
  if (matched === null) return false;
  const [, year, month, day, hour, minute] = matched;
  const parts = [year, month, day, hour, minute].map(Number);
  const [y, m, d, h, min] = parts;
  if (
    y === undefined ||
    m === undefined ||
    d === undefined ||
    h === undefined ||
    min === undefined
  ) {
    return false;
  }
  const parsed = new Date(Date.UTC(y, m - 1, d, h, min));
  return (
    parsed.getUTCFullYear() === y &&
    parsed.getUTCMonth() === m - 1 &&
    parsed.getUTCDate() === d &&
    parsed.getUTCHours() === h &&
    parsed.getUTCMinutes() === min
  );
}

function executedKmaMetadata(
  detail: PipelineExecutionDetailResponse,
): KmaExecutionMetadata {
  assertKmaOnlyTerminalProviderScopes(detail, { executed: "nonempty" });
  const executed = detail.data.update_request?.matched_scope.executed_provider_scopes;
  expect(Array.isArray(executed)).toBe(true);
  const records = (executed as unknown[]).map(asRecord);
  expect(records).toHaveLength(1);
  const matching = records[0];
  const metadata = asRecord(matching?.metadata);
  expect(metadata).not.toBeNull();
  expect(isCanonicalKmaBaseDatetime(metadata?.base_datetime)).toBe(true);
  expect(typeof metadata?.grids_dropped).toBe("number");
  expect(typeof metadata?.grids_fetched).toBe("number");
  expect(typeof metadata?.grids_total).toBe("number");
  expect(
    typeof metadata?.membership_fingerprint === "string" &&
      LOWERCASE_SHA256_PATTERN.test(metadata.membership_fingerprint),
  ).toBe(true);
  expect(typeof metadata?.skipped).toBe("boolean");
  expect(metadata?.sync_scope).toBe(
    detail.data.update_request?.effective_sync_scope,
  );
  return metadata as KmaExecutionMetadata;
}

function assertSkippedWithoutProviderIo(
  metadata: KmaExecutionMetadata,
  expected: { baseDatetime: string; membershipFingerprint: string },
): void {
  expect(metadata).toMatchObject({
    base_datetime: expected.baseDatetime,
    features_total: 0,
    grids_dropped: 0,
    grids_fetched: 0,
    grids_total: 2,
    membership_fingerprint: expected.membershipFingerprint,
    skipped: true,
    values_loaded: 0,
  });
}

function requestIdentity(response: FeatureUpdateRequestCreateResponse): {
  jobId: string;
  requestId: string;
} {
  return {
    jobId: response.data.job_id,
    requestId: response.data.request_id,
  };
}

async function boundedRouteWait<T>(
  promise: Promise<T>,
  operation: string,
): Promise<T> {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  try {
    return await new Promise<T>((resolve, reject) => {
      timeout = setTimeout(
        () => reject(new Error(`${operation} 제한 시간 초과`)),
        ROUTE_TIMEOUT,
      );
      promise.then(resolve, reject);
    });
  } finally {
    if (timeout !== null) clearTimeout(timeout);
  }
}

async function openAndFillKmaRequestDialog(
  page: Page,
  syncScope: string,
  reason: string,
): Promise<void> {
  await page.goto("/ops/pipeline");
  await expect(
    page.getByRole("heading", { level: 1, name: "파이프라인" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "갱신 요청 생성" }).click();
  const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("provider").fill(KMA_PROVIDER);
  await dialog.getByLabel("dataset_key").fill(KMA_DATASET_KEY);
  await dialog.getByLabel("sync_scope (선택)").fill(syncScope);

  const previewResponse = page.waitForResponse(
    (response) => {
      const url = new URL(response.url());
      return (
        response.request().method() === "POST" &&
        url.pathname === "/api/proxy/v1/ops/pipeline/requests/preview"
      );
    },
    // 명시 상한: live config actionTimeout(60s) 도입 전엔 무제한이었다. bare wait이
    // 전역 default에 조용히 지배되지 않도록 이 preview 대기를 명시적으로 고정한다.
    { timeout: DATASET_DETAIL_FETCH_TIMEOUT_MS },
  );
  await dialog.getByRole("button", { name: "dry-run 실행" }).click();
  const expectedPreview = previewBody(
    buildKmaRequest(
      syncScope.slice("external_system:".length),
      reason,
    ),
  );
  await assertExactKmaPreviewResponse(
    await previewResponse,
    expectedPreview,
  );
  await expect(dialog.getByTestId("request-preview-result")).toContainText(
    syncScope,
  );

  await dialog.getByRole("checkbox", { name: /dry-run/ }).uncheck();
  await dialog.getByLabel("사유").fill(reason);
}

async function uiCreateThenApiActiveReuse(
  page: Page,
  body: FeatureUpdateRequestCreateRequest,
  state: ReturnType<typeof createCleanupState>,
  expectedTargets: readonly TargetRef[],
): Promise<{
  api: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  apiIdempotencyKey: string;
  ui: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  uiBody: FeatureUpdateRequestCreateRequest;
  uiIdempotencyKey: string;
}> {
  const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
  let journaledUiKey: string | null = null;
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
    page.url(),
  ).href;
  const isExactUiCreateRequest = (request: Request): boolean =>
    request.method() === "POST" && request.url() === exactUrl;
  const routeHandler = async (route: Route): Promise<void> => {
    routeSeen = true;
    const request = route.request();
    try {
      if (!isExactUiCreateRequest(request)) {
        throw new Error("active UI create exact origin/path/method 불일치");
      }
      const idempotencyKey = request.headers()["idempotency-key"];
      if (!idempotencyKey) {
        throw new Error("active UI create Idempotency-Key가 없습니다");
      }
      const uiBody = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
      await assertExactOwnedTargetsAtServer(
        page,
        state,
        expectedTargets,
        body.scope.type === "provider_dataset" &&
          body.scope.sync_scope?.startsWith("external_system:")
          ? body.scope.sync_scope.slice("external_system:".length)
          : undefined,
      );
      await journalExactUiKmaCreateRequest(
        state,
        uiBody,
        idempotencyKey,
        body,
        expectedTargets,
      );
      journaledUiKey = idempotencyKey;
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
  const uiRequestPromise = page.waitForRequest(isExactUiCreateRequest);
  let uiRequest: Request;
  let primaryError: unknown;
  try {
    await dialog.getByRole("button", { name: "요청 생성" }).click();
    uiRequest = await boundedRouteWait(
      uiRequestPromise,
      "active UI create request",
    );
    await boundedRouteWait(routeHandled, "active UI create route barrier");
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    void uiRequestPromise.catch(() => undefined);
    const teardownErrors: unknown[] = [];
    if (routeSeen) {
      await boundedRouteWait(
        handlerSettled,
        "active UI create route handler settlement",
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
        "active UI create primary/route cleanup 실패",
      );
    }
  }
  const uiIdempotencyKey = uiRequest.headers()["idempotency-key"];
  if (!uiIdempotencyKey || journaledUiKey !== uiIdempotencyKey) {
    throw new Error("UI create 요청의 Idempotency-Key가 없습니다.");
  }
  const uiBody = uiRequest.postDataJSON() as FeatureUpdateRequestCreateRequest;
  const apiIdempotencyKey = randomUUID();

  const settled = await Promise.allSettled([
    createKmaRequest(page, body, apiIdempotencyKey, state),
    boundedRouteWait(uiRequest.response(), "active UI create response"),
  ]);
  const apiSettled = settled[0];
  const uiSettled = settled[1];
  if (apiSettled.status !== "fulfilled") {
    throw new Error("different-key API active reuse가 완료되지 않았습니다.");
  }
  const ui = (
    await resolveTrackedUiKmaCreateResponse(
      page,
      state,
      uiIdempotencyKey,
      uiBody,
      uiSettled.status === "fulfilled" ? uiSettled.value : null,
      { allowActiveReuse: true },
    )
  ).result;
  await expect(dialog.getByTestId("request-create-result")).toBeVisible();
  return {
    api: apiSettled.value,
    apiIdempotencyKey,
    ui,
    uiBody,
    uiIdempotencyKey,
  };
}

async function assertRunningRequestIdentityFromUi(
  page: Page,
  requestId: string,
  jobId: string,
): Promise<void> {
  // execution-detail 패널은 별도 execution-detail GET가 도착해야 mount된다. bare
  // goto + 즉시 toBeVisible은 그 fetch를 race하므로(datasets 패널과 동일 class —
  // gotoExactDatasetUiSettled 참조) UI 자신의 execution-detail GET를 response-gate한
  // 뒤 assertion을 settled 데이터에 실행한다.
  const executionDetailSettled = page.waitForResponse(
    (response) => {
      const url = new URL(response.url());
      return (
        response.request().method() === "GET" &&
        url.pathname ===
          `/api/proxy/v1/ops/pipeline/executions/update_request/${requestId}` &&
        response.status() === 200
      );
    },
    { timeout: DATASET_DETAIL_FETCH_TIMEOUT_MS },
  );
  await page.goto(`/ops/pipeline?execution=update_request:${requestId}`);
  await executionDetailSettled;
  const executionDetail = page.getByTestId("pipeline-execution-detail");
  await expect(executionDetail).toBeVisible();
  // KMA nowcast refreshes can transition queued→running→done faster than the UI can
  // observe the transient "running" state, so requiring status==="running" here is a
  // race (fast completion → the 30s poll only ever sees "done"). Tolerate fast
  // completion: wait until the request leaves "queued" and verify the canonical
  // identity from whichever non-queued state is observed.
  //
  // The strictly-while-running run-now UI leg is intentionally NOT exercised here: it
  // is race-gated best-effort (skipped on the common fast-completion path, so it
  // guarantees no coverage) and its UI→POST ownership contract is verified
  // deterministically by the mocked ops-pipeline spec. Driving it on the live gate
  // only added flake surface (its ownership barrier requires the job to still be
  // running at POST time), so it is removed from this zero-retry flow.
  await expect
    .poll(
      async () =>
        requireBody(await getRequestDetail(page, requestId), 200).data.execution
          .status,
      { timeout: 30_000 },
    )
    .not.toBe("queued");
  const observedExecution = requireBody(
    await getRequestDetail(page, requestId),
    200,
  ).data.execution;
  expect(observedExecution.kind).toBe("update_request");
  expect(observedExecution.id).toBe(requestId);
  expect(observedExecution.job_id).toBe(jobId);
}

async function assertDatasetTerminalHistoryUi(
  page: Page,
  syncScope: string,
  requestId: string,
): Promise<void> {
  await gotoExactDatasetUiSettled(page, syncScope);
  const region = page.getByRole("region", {
    name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
  });
  await expect(region).toBeVisible();
  await expect(region.getByText("선택 범위 최근 종료 실행")).toBeVisible();
  await expect(
    region.locator(
      `a[href="/ops/pipeline?execution=update_request:${requestId}"]`,
    ),
  ).not.toHaveCount(0);
}

function isExactDatasetDetailResponse(
  response: import("@playwright/test").Response,
  syncScope: string,
): boolean {
  // The per-run external_system sync_scope is unique to this test + dataset, so a
  // 200 GET on the detail endpoint carrying it is unambiguously the UI's own detail
  // fetch for this scope — robust to exact provider/dataset_key param spelling and it
  // ignores the no-param 422 probes the page may also fire.
  const url = new URL(response.url());
  return (
    response.request().method() === "GET" &&
    url.pathname === "/api/proxy/v1/ops/datasets/detail" &&
    url.searchParams.get("sync_scope") === syncScope &&
    response.status() === 200
  );
}

// The dataset-detail drawer renders in two phases: the `상세` region appears as soon
// as the grid query resolves the selection, but the history/status panels (and the
// "선택 범위 최근 종료 실행" header) mount only after a SEPARATE dataset-detail query
// lands. A bare page.goto + immediate DOM assertion races that second fetch under
// late-active load (the region is a premature "data-loaded" signal). Register a wait
// for the UI's OWN detail GET before navigating so the following assertions run
// against settled data — with the same 60s budget the direct probe already gets,
// instead of the implicit 15s expect() ceiling that was flaking.
async function gotoExactDatasetUiSettled(
  page: Page,
  syncScope: string,
): Promise<void> {
  const detailSettled = page.waitForResponse(
    (response) => isExactDatasetDetailResponse(response, syncScope),
    { timeout: DATASET_DETAIL_FETCH_TIMEOUT_MS },
  );
  await page.goto(exactDatasetUiPath(syncScope));
  await detailSettled;
}

function cursorMembershipFingerprint(
  detail: OpsDatasetDetailResponse,
  syncScope: string,
): string {
  const state = detail.data.scopes.find((item) => item.sync_scope === syncScope);
  expect(state, `exact scope state 없음: ${syncScope}`).toBeDefined();
  expect(typeof state?.cursor.membership_fingerprint).toBe("string");
  expect(
    LOWERCASE_SHA256_PATTERN.test(
      state?.cursor.membership_fingerprint as string,
    ),
  ).toBe(true);
  const baseDatetime = state?.cursor.base_datetime;
  expect(typeof baseDatetime).toBe("string");
  expect(isCanonicalKmaBaseDatetime(baseDatetime)).toBe(true);
  return state?.cursor.membership_fingerprint as string;
}

test.describe("C7 KMA active exact scope destructive live E2E", () => {
  test("실제 UI 조작과 canonical API identity를 연결하고 fingerprint·provider-skip을 검증한다", async ({
    page,
  }, testInfo) => {
    requireDestructiveGates(testInfo);
    if (millisecondsUntilNextBaseRollover() < MINIMUM_START_WINDOW_MS) {
      testInfo.annotations.push({
        type: "blocker",
        description:
          "동일 KMA base에서 provider I/O 없는 overflow를 끝낼 30분 안전 창이 없어 active 시나리오 전체를 실행하지 않음",
      });
      throw new Error(
        "KMA base rollover 안전 창 부족: active/overflow 실행 금지",
      );
    }
    test.setTimeout(TEST_TIMEOUT);
    await bootstrapC7SameOriginPage(page, "/ops/pipeline");
    await assertKmaDagsterWorkerJobDefinition();
    const externalSystem = `e2e-${RUN_ID}`;
    const syncScope = `external_system:${externalSystem}`;
    const state = createCleanupState("active", RUN_ID);

    await withC7Cleanup(page, testInfo, state, async () => {
      await putTrackedTarget(
        page,
        state,
        { externalSystem, targetKey: `${RUN_ID}-a` },
        buildPoiTargetBody(126.978, 37.5665, {
          name: `C7 KMA active A ${RUN_ID}`,
          runId: RUN_ID,
        }),
      );

      const reason = `C7 ${RUN_ID} membership first`;
      const firstBody = buildKmaRequest(externalSystem, reason);
      await openAndFillKmaRequestDialog(page, syncScope, reason);
      const firstCreates = await uiCreateThenApiActiveReuse(
        page,
        firstBody,
        state,
        [{ externalSystem, targetKey: `${RUN_ID}-a` }],
      );
      expect([firstCreates.api.status, firstCreates.ui.status].sort()).toEqual([
        200,
        201,
      ]);
      const newCreate =
        firstCreates.api.status === 201 ? firstCreates.api : firstCreates.ui;
      const activeReuse =
        firstCreates.api.status === 200 ? firstCreates.api : firstCreates.ui;
      const created = requireBody(newCreate, 201);
      const reused = requireBody(activeReuse, 200);
      expect(created.idempotent_replay).toBe(false);
      expect(created.reused_active_request).toBe(false);
      expect(reused.idempotent_replay).toBe(false);
      expect(reused.reused_active_request).toBe(true);
      expect(requestIdentity(reused)).toEqual(requestIdentity(created));

      // fast-completion(queued→done)에도 active 또는 settled latest로 identity를
      // 재탐색한다(빠른 KMA job이 active_execution을 null로 만들어도 오탐 없음).
      await rediscoverExactActiveOrSettledRequest(
        page,
        syncScope,
        created.data.request_id,
      );

      // 서버가 보고한 non-queued 상태에서 canonical identity(kind/id/job_id)를 UI
      // 상세로 확인한다(transient running 관측은 요구하지 않음 — 위 함수 주석 참조).
      await assertRunningRequestIdentityFromUi(
        page,
        created.data.request_id,
        created.data.job_id,
      );

      // 같은 key replay는 다른 key의 active reuse와 별도 계약으로 검증한다.
      const newCreateWasApi = firstCreates.api.status === 201;
      const sameKeyReplayResult = await createKmaRequest(
        page,
        newCreateWasApi ? firstBody : firstCreates.uiBody,
        newCreateWasApi
          ? firstCreates.apiIdempotencyKey
          : firstCreates.uiIdempotencyKey,
        state,
      );
      const sameKeyReplay = requireBody(sameKeyReplayResult, 200);
      expect(sameKeyReplay.idempotent_replay).toBe(true);
      expect(sameKeyReplay.reused_active_request).toBe(false);
      expect(requestIdentity(sameKeyReplay)).toEqual(requestIdentity(created));

      const firstTerminal = await waitForTerminal(
        page,
        created.data.request_id,
        undefined,
        state,
      );
      expect(firstTerminal.data.execution.status).toBe("done");
      const firstMetadata = executedKmaMetadata(firstTerminal);
      expect(firstMetadata.skipped).toBe(false);
      expect(firstMetadata).toMatchObject({
        grids_dropped: 0,
        grids_fetched: 1,
        grids_total: 1,
      });

      const firstDatasetDetail = requireBody(
        await getExactDatasetDetail(page, syncScope),
        200,
      );
      expect(firstDatasetDetail.data.active_execution).toBeNull();
      expect(firstDatasetDetail.data.latest_execution?.id).toBe(
        created.data.request_id,
      );
      const firstFingerprint = cursorMembershipFingerprint(
        firstDatasetDetail,
        syncScope,
      );
      state.scopeStateCount = 1;
      expect(firstMetadata.membership_fingerprint).toBe(firstFingerprint);
      await assertDatasetTerminalHistoryUi(page, syncScope, created.data.request_id);

      await putTrackedTarget(
        page,
        state,
        { externalSystem, targetKey: `${RUN_ID}-b` },
        buildPoiTargetBody(129.0756, 35.1796, {
          name: `C7 KMA active B ${RUN_ID}`,
          runId: RUN_ID,
        }),
      );
      const secondResult = await createKmaRequest(
        page,
        buildKmaRequest(
          externalSystem,
          `C7 ${RUN_ID} membership second`,
          "now",
        ),
        randomUUID(),
        state,
      );
      const second = requireBody(secondResult, 201);
      const secondTerminal = await waitForTerminal(
        page,
        second.data.request_id,
        undefined,
        state,
      );
      expect(secondTerminal.data.execution.status).toBe("done");
      const secondMetadata = executedKmaMetadata(secondTerminal);
      expect(secondMetadata.skipped).toBe(false);
      expect(secondMetadata).toMatchObject({
        grids_dropped: 0,
        grids_fetched: 2,
        grids_total: 2,
      });
      expect(secondMetadata.base_datetime).toBe(firstMetadata.base_datetime);
      expect(secondMetadata.membership_fingerprint).not.toBe(firstFingerprint);

      const secondDatasetDetail = requireBody(
        await getExactDatasetDetail(page, syncScope),
        200,
      );
      const secondFingerprint = cursorMembershipFingerprint(
        secondDatasetDetail,
        syncScope,
      );
      expect(secondMetadata.membership_fingerprint).toBe(secondFingerprint);

      // 동일 base·membership인 세 번째 요청 하나로 provider I/O budget 0(skipped)을
      // 결정적으로 증명한다. 과거 49회 overflow 루프(cursor 계약 검증)는 KST :40
      // base rollover를 straddle해 flaky했고, 그 cursor 계약은 seed 통합 테스트
      // (test_external_system_scope_run_history_cursor_pages_past_boundary)로 옮겼다.
      const skippedResult = await createKmaRequest(
        page,
        buildKmaRequest(externalSystem, `C7 ${RUN_ID} skipped budget-0`, "now"),
        randomUUID(),
        state,
      );
      const skipped = requireBody(skippedResult, 201);
      const skippedTerminal = await waitForTerminal(
        page,
        skipped.data.request_id,
        undefined,
        state,
      );
      expect(skippedTerminal.data.execution.status).toBe("done");
      assertSkippedWithoutProviderIo(executedKmaMetadata(skippedTerminal), {
        baseDatetime: secondMetadata.base_datetime,
        membershipFingerprint: secondFingerprint,
      });
    }, { terminalTimeout: REQUEST_TERMINAL_TIMEOUT });
  });
});
