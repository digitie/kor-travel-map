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
  bootstrapC7SameOriginPage,
  buildKmaRequest,
  buildPoiTargetBody,
  createCleanupState,
  createKmaRequest,
  destructiveGateBlocker,
  exactDatasetUiPath,
  getExactDatasetDetail,
  getRequestDetail,
  journalPendingRequest,
  putTrackedTarget,
  rediscoverExactActiveRequest,
  requireBody,
  resolveTrackedUiKmaCreateResponse,
  runTrackedRequestNowFromUi,
  waitForTerminal,
  withC7Cleanup,
  type BrowserFetchResult,
  type FeatureUpdateRequestCreateRequest,
  type FeatureUpdateRequestCreateResponse,
  type OpsDatasetDetailResponse,
  type PipelineExecutionDetailResponse,
} from "./_ops-c7-admin-api";

const TEST_TIMEOUT = 60 * 60 * 1000;
const PIPELINE_UI_PAGE_LIMIT = 50;
const OVERFLOW_TOTAL_REQUESTS = PIPELINE_UI_PAGE_LIMIT + 1;
const MINIMUM_START_WINDOW_MS = 30 * 60 * 1000;
const MINIMUM_NEXT_SKIP_WINDOW_MS = 5 * 60 * 1000;
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

function executedKmaMetadata(
  detail: PipelineExecutionDetailResponse,
): KmaExecutionMetadata {
  const executed = detail.data.update_request?.matched_scope.executed_provider_scopes;
  expect(Array.isArray(executed)).toBe(true);
  const matching = (executed as unknown[])
    .map(asRecord)
    .find(
      (item) =>
        item?.provider === KMA_PROVIDER && item.dataset_key === KMA_DATASET_KEY,
    );
  const metadata = asRecord(matching?.metadata);
  expect(metadata).not.toBeNull();
  expect(typeof metadata?.base_datetime).toBe("string");
  expect(typeof metadata?.grids_dropped).toBe("number");
  expect(typeof metadata?.grids_fetched).toBe("number");
  expect(typeof metadata?.grids_total).toBe("number");
  expect(typeof metadata?.membership_fingerprint).toBe("string");
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

function isUiCreateRequest(request: Request): boolean {
  const url = new URL(request.url());
  return (
    request.method() === "POST" &&
    url.pathname === "/api/proxy/v1/ops/pipeline/requests"
  );
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

  const previewResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.request().method() === "POST" &&
      url.pathname === "/api/proxy/v1/ops/pipeline/requests/preview"
    );
  });
  await dialog.getByRole("button", { name: "dry-run 실행" }).click();
  expect((await previewResponse).status()).toBe(200);
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
): Promise<{
  api: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  apiIdempotencyKey: string;
  ui: BrowserFetchResult<FeatureUpdateRequestCreateResponse>;
  uiBody: FeatureUpdateRequestCreateRequest;
  uiIdempotencyKey: string;
}> {
  const dialog = page.getByRole("dialog", { name: "갱신 요청 생성" });
  let journaledUiKey: string | null = null;
  const routeHandler = async (route: Route): Promise<void> => {
    const request = route.request();
    if (!isUiCreateRequest(request)) {
      await route.fallback();
      return;
    }
    const idempotencyKey = request.headers()["idempotency-key"];
    if (!idempotencyKey) {
      await route.abort("failed");
      return;
    }
    const uiBody = request.postDataJSON() as FeatureUpdateRequestCreateRequest;
    await journalPendingRequest(state, uiBody, idempotencyKey);
    journaledUiKey = idempotencyKey;
    await route.continue();
  };
  await page.route("**/api/proxy/v1/ops/pipeline/requests", routeHandler);
  const uiRequestPromise = page.waitForRequest(isUiCreateRequest);
  let uiRequest: Request;
  try {
    await dialog.getByRole("button", { name: "요청 생성" }).click();
    uiRequest = await uiRequestPromise;
  } finally {
    await page.unroute("**/api/proxy/v1/ops/pipeline/requests", routeHandler);
  }
  const uiIdempotencyKey = uiRequest.headers()["idempotency-key"];
  if (!uiIdempotencyKey || journaledUiKey !== uiIdempotencyKey) {
    throw new Error("UI create 요청의 Idempotency-Key가 없습니다.");
  }
  const uiBody = uiRequest.postDataJSON() as FeatureUpdateRequestCreateRequest;
  const apiIdempotencyKey = randomUUID();

  const settled = await Promise.allSettled([
    createKmaRequest(page, body, apiIdempotencyKey, state),
    uiRequest.response(),
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
  state: ReturnType<typeof createCleanupState>,
): Promise<void> {
  await page.goto(`/ops/pipeline?execution=update_request:${requestId}`);
  const executionDetail = page.getByTestId("pipeline-execution-detail");
  await expect(executionDetail).toBeVisible();
  await expect
    .poll(
      async () =>
        requireBody(await getRequestDetail(page, requestId), 200).data.execution
          .status,
      { timeout: 30_000 },
    )
    .toBe("running");
  const runningRunNow = executionDetail.getByRole("button", {
    name: "실행 중 요청 확인 (run-now)",
    exact: true,
  });
  await expect(runningRunNow).toBeVisible();
  expect(
    requireBody(await getRequestDetail(page, requestId), 200).data.execution
      .status,
  ).toBe("running");
  await runTrackedRequestNowFromUi(
    page,
    state,
    requestId,
    jobId,
    () => runningRunNow.click(),
  );
  await expect(executionDetail.getByText("우선 dispatch 요청됨")).toBeVisible();
}

async function assertDatasetTerminalHistoryUi(
  page: Page,
  syncScope: string,
  requestId: string,
): Promise<void> {
  await page.goto(exactDatasetUiPath(syncScope));
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

async function assertHistoryContinuationFromUi(
  page: Page,
  syncScope: string,
): Promise<void> {
  await page.goto(exactDatasetUiPath(syncScope));
  const region = page.getByRole("region", {
    name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
  });
  await expect(region).toContainText("더 오래된 실행이 있습니다.");
  await expect(region).toContainText("더 오래된 이벤트가 있습니다.");

  await region
    .getByRole("link", { name: "선택 범위 실행 전체 보기", exact: true })
    .click();
  await expect(page.getByLabel("provider 필터", { exact: true })).toHaveValue(
    KMA_PROVIDER,
  );
  await expect(page.getByLabel("데이터셋 필터", { exact: true })).toHaveValue(
    KMA_DATASET_KEY,
  );
  await expect(page.getByLabel("sync scope 필터", { exact: true })).toHaveValue(
    syncScope,
  );
  const runTable = page.getByRole("table", {
    name: "실행 타임라인",
    exact: true,
  });
  const runRows = runTable.locator('[data-testid^="pipeline-execution-row-"]');
  await expect(runRows).toHaveCount(PIPELINE_UI_PAGE_LIMIT);
  const firstPageRunIds = await runRows.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-testid") ?? ""),
  );
  const runNext = page.getByRole("button", {
    name: "실행 타임라인 다음 페이지",
    exact: true,
  });
  await expect(runNext).toBeEnabled();
  const runPageResponse = page.waitForResponse(isCursorExecutionResponse);
  await runNext.click();
  const runResponse = await runPageResponse;
  expect(runResponse.status()).toBe(200);
  const runPageIds = responseItemStringField(
    await runResponse.json(),
    "id",
    "execution cursor page",
  );
  expect(runPageIds.length).toBeGreaterThan(0);
  expect(
    runPageIds.some(
      (id) => !firstPageRunIds.includes(`pipeline-execution-row-${id}`),
    ),
  ).toBe(true);
  await expect(
    page.getByRole("navigation", {
      name: "실행 타임라인 pagination",
      exact: true,
    }),
  ).toContainText("page 2");
  await expect(
    runTable.getByTestId(`pipeline-execution-row-${runPageIds[0]}`),
  ).toBeVisible();
  await expect(page.getByText("실행 목록 호출 실패", { exact: true })).toHaveCount(
    0,
  );

  await page.goto(exactDatasetUiPath(syncScope));
  const eventLink = page
    .getByRole("region", {
      name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
    })
    .getByRole("link", { name: "선택 범위 이벤트 전체 보기", exact: true });
  await eventLink.click();
  const eventTable = page.getByRole("table", {
    name: "전역 job 이벤트",
    exact: true,
  });
  const firstEventPageText = await eventTable.innerText();
  const eventNext = page.getByRole("button", {
    name: "job 이벤트 다음 페이지",
    exact: true,
  });
  await expect(eventNext).toBeEnabled();
  const eventPageResponse = page.waitForResponse(isCursorEventResponse);
  await eventNext.click();
  const eventResponse = await eventPageResponse;
  expect(eventResponse.status()).toBe(200);
  const eventPageIds = responseItemStringField(
    await eventResponse.json(),
    "event_id",
    "event cursor page",
  );
  expect(eventPageIds.length).toBeGreaterThan(0);
  await expect(
    page.getByRole("navigation", {
      name: "job 이벤트 pagination",
      exact: true,
    }),
  ).toContainText("page 2");
  await expect.poll(() => eventTable.innerText()).not.toBe(firstEventPageText);
  await expect(page.getByText("이벤트 목록 호출 실패", { exact: true })).toHaveCount(
    0,
  );
}

function isCursorExecutionResponse(response: import("@playwright/test").Response): boolean {
  const url = new URL(response.url());
  return (
    response.request().method() === "GET" &&
    url.pathname === "/api/proxy/v1/ops/pipeline/executions" &&
    url.searchParams.has("cursor")
  );
}

function isCursorEventResponse(response: import("@playwright/test").Response): boolean {
  const url = new URL(response.url());
  return (
    response.request().method() === "GET" &&
    url.pathname === "/api/proxy/v1/ops/pipeline/events" &&
    url.searchParams.has("cursor")
  );
}

function responseItemStringField(
  value: unknown,
  field: string,
  context: string,
): string[] {
  const envelope = asRecord(value);
  const data = asRecord(envelope?.data);
  if (!Array.isArray(data?.items)) {
    throw new Error(`${context} 응답 items 계약 위반`);
  }
  const fields = data.items.map((item) => asRecord(item)?.[field]);
  if (!fields.every((item): item is string => typeof item === "string")) {
    throw new Error(`${context} 응답 ${field} 계약 위반`);
  }
  return fields;
}

function cursorMembershipFingerprint(
  detail: OpsDatasetDetailResponse,
  syncScope: string,
): string {
  const state = detail.data.scopes.find((item) => item.sync_scope === syncScope);
  expect(state, `exact scope state 없음: ${syncScope}`).toBeDefined();
  expect(typeof state?.cursor.membership_fingerprint).toBe("string");
  return state?.cursor.membership_fingerprint as string;
}

test.describe("C7 KMA active exact scope destructive live E2E", () => {
  test("실제 UI 조작과 canonical API identity를 연결하고 fingerprint·cursor overflow를 검증한다", async ({
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

      const rediscovered = await Promise.allSettled([
        rediscoverExactActiveRequest(page, syncScope),
      ]);
      expect(rediscovered[0].status).toBe("fulfilled");
      if (rediscovered[0].status !== "fulfilled") {
        throw new Error("exact scope active request 재탐색 실패");
      }
      expect(rediscovered[0].value.id).toBe(created.data.request_id);

      // queued 버튼을 경쟁적으로 누르지 않는다. 서버가 실제 running을 보고한 뒤
      // UI도 running 전용 문구를 렌더한 경우에만 동일 identity run-now를 호출한다.
      await assertRunningRequestIdentityFromUi(
        page,
        created.data.request_id,
        created.data.job_id,
        state,
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

      // 총 51개 exact-scope terminal root를 만든다. 이후 요청은 동일 base와
      // membership이므로 canonical skipped metadata가 provider I/O budget 0을 증명한다.
      for (let index = 2; index < OVERFLOW_TOTAL_REQUESTS; index += 1) {
        if (
          millisecondsUntilNextBaseRollover() < MINIMUM_NEXT_SKIP_WINDOW_MS
        ) {
          testInfo.annotations.push({
            type: "blocker",
            description:
              "KMA base rollover가 임박해 provider-call budget 0을 증명할 수 없으므로 history overflow를 중단함",
          });
          throw new Error(
            "KMA base rollover 임박: provider I/O 없는 skipped overflow 실행 금지",
          );
        }
        const overflowResult = await createKmaRequest(
          page,
          buildKmaRequest(
            externalSystem,
            `C7 ${RUN_ID} skipped overflow ${index + 1}`,
            "now",
          ),
          randomUUID(),
          state,
        );
        const overflow = requireBody(overflowResult, 201);
        const terminal = await waitForTerminal(
          page,
          overflow.data.request_id,
          undefined,
          state,
        );
        expect(terminal.data.execution.status).toBe("done");
        assertSkippedWithoutProviderIo(executedKmaMetadata(terminal), {
          baseDatetime: secondMetadata.base_datetime,
          membershipFingerprint: secondFingerprint,
        });
      }

      expect(state.requestIds.size).toBe(OVERFLOW_TOTAL_REQUESTS);
      const overflowDetail = requireBody(
        await getExactDatasetDetail(page, syncScope),
        200,
      );
      expect(overflowDetail.data.run_history.next_cursor).not.toBeNull();
      expect(overflowDetail.data.event_history.next_cursor).not.toBeNull();
      await assertHistoryContinuationFromUi(page, syncScope);
    });
  });
});
