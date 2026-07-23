import { randomUUID } from "node:crypto";

import {
  expect,
  test,
  type Locator,
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
  destructiveGateBlocker,
  exactDatasetUiPath,
  getExactDatasetDetail,
  getRequestDetail,
  journalExactUiKmaCreateRequest,
  previewBody,
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
  type TargetRef,
} from "./_ops-c7-admin-api";

const TEST_TIMEOUT = 60 * 60 * 1000;
const ROUTE_TIMEOUT = 30_000;
const PIPELINE_UI_PAGE_LIMIT = 50;
const OVERFLOW_TOTAL_REQUESTS = PIPELINE_UI_PAGE_LIMIT + 1;
const MINIMUM_START_WINDOW_MS = 30 * 60 * 1000;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const LOWERCASE_SHA256_PATTERN = /^[0-9a-f]{64}$/;
const KMA_BASE_DATETIME_PATTERN = /^([0-9]{4})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})$/;
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

  const previewResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.request().method() === "POST" &&
      url.pathname === "/api/proxy/v1/ops/pipeline/requests/preview"
    );
  });
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
  syncScope: string,
  state: ReturnType<typeof createCleanupState>,
): Promise<void> {
  await page.goto(`/ops/pipeline?execution=update_request:${requestId}`);
  const executionDetail = page.getByTestId("pipeline-execution-detail");
  await expect(executionDetail).toBeVisible();
  // KMA nowcast refreshes can transition queued→running→done faster than the UI can
  // observe the transient "running" state, so requiring status==="running" here is a
  // race (fast completion → the 30s poll only ever sees "done"). Tolerate fast
  // completion: wait until the request leaves "queued", verify the canonical identity
  // from whichever non-queued state is observed, and only exercise the strictly-
  // while-running run-now UI leg when the request is still observably running (its
  // ownership barrier in runTrackedRequestNowFromUi requires status==="running").
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
  if (observedExecution.status === "running") {
    const runningRunNow = executionDetail.getByRole("button", {
      name: "실행 중 요청 확인 (run-now)",
      exact: true,
    });
    if (await runningRunNow.isVisible().catch(() => false)) {
      await runTrackedRequestNowFromUi(
        page,
        state,
        requestId,
        jobId,
        syncScope,
        () => runningRunNow.click(),
      );
      await expect(
        executionDetail.getByText("우선 dispatch 요청됨"),
      ).toBeVisible();
    }
  }
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

  const firstRunResponsePromise = page.waitForResponse((response) =>
    isExactHistoryPageResponse(response, "executions", syncScope, null),
  );
  await region
    .getByRole("link", { name: "선택 범위 실행 전체 보기", exact: true })
    .click();
  const firstRunResponse = await firstRunResponsePromise;
  expect(firstRunResponse.status()).toBe(200);
  const firstRunBody = await firstRunResponse.json();
  const firstRunTuples = orderedHistoryIdentityTuples(
    firstRunBody,
    "executions",
    "execution first page",
    syncScope,
  );
  const runCursor = responseNextCursor(
    firstRunBody,
    "execution first page",
  );
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
  await expect
    .poll(() => domOrderedIdentityKeys(runTable))
    .toEqual(firstRunTuples.map(identityKey));
  const runNext = page.getByRole("button", {
    name: "실행 타임라인 다음 페이지",
    exact: true,
  });
  await expect(runNext).toBeEnabled();
  const runPageResponse = page.waitForResponse((response) =>
    isExactHistoryPageResponse(
      response,
      "executions",
      syncScope,
      runCursor,
    ),
  );
  await runNext.click();
  const runResponse = await runPageResponse;
  expect(runResponse.status()).toBe(200);
  const runPageBody = await runResponse.json();
  const runPageTuples = orderedHistoryIdentityTuples(
    runPageBody,
    "executions",
    "execution cursor page",
    syncScope,
  );
  assertDisjointOrderedContinuation(
    firstRunTuples,
    runPageTuples,
    "execution",
  );
  const nextRunCursor = responseNextCursorOrNull(
    runPageBody,
    "execution cursor page",
  );
  expect(nextRunCursor).not.toBe(runCursor);
  await expect
    .poll(() => domOrderedIdentityKeys(runTable))
    .toEqual(runPageTuples.map(identityKey));
  await expect(
    page.getByRole("navigation", {
      name: "실행 타임라인 pagination",
      exact: true,
    }),
  ).toContainText("page 2");
  await expect(page.getByText("실행 목록 호출 실패", { exact: true })).toHaveCount(
    0,
  );

  await page.goto(exactDatasetUiPath(syncScope));
  const eventLink = page
    .getByRole("region", {
      name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
    })
    .getByRole("link", { name: "선택 범위 이벤트 전체 보기", exact: true });
  const firstEventResponsePromise = page.waitForResponse((response) =>
    isExactHistoryPageResponse(response, "events", syncScope, null),
  );
  await eventLink.click();
  const firstEventResponse = await firstEventResponsePromise;
  expect(firstEventResponse.status()).toBe(200);
  const firstEventBody = await firstEventResponse.json();
  const firstEventTuples = orderedHistoryIdentityTuples(
    firstEventBody,
    "events",
    "event first page",
    syncScope,
  );
  const eventCursor = responseNextCursor(firstEventBody, "event first page");
  const eventTable = page.getByRole("table", {
    name: "전역 job 이벤트",
    exact: true,
  });
  await expect
    .poll(() => domOrderedIdentityKeys(eventTable))
    .toEqual(firstEventTuples.map(identityKey));
  const eventNext = page.getByRole("button", {
    name: "job 이벤트 다음 페이지",
    exact: true,
  });
  await expect(eventNext).toBeEnabled();
  const eventPageResponse = page.waitForResponse((response) =>
    isExactHistoryPageResponse(
      response,
      "events",
      syncScope,
      eventCursor,
    ),
  );
  await eventNext.click();
  const eventResponse = await eventPageResponse;
  expect(eventResponse.status()).toBe(200);
  const eventPageBody = await eventResponse.json();
  const eventPageTuples = orderedHistoryIdentityTuples(
    eventPageBody,
    "events",
    "event cursor page",
    syncScope,
  );
  assertDisjointOrderedContinuation(
    firstEventTuples,
    eventPageTuples,
    "event",
  );
  const nextEventCursor = responseNextCursorOrNull(
    eventPageBody,
    "event cursor page",
  );
  expect(nextEventCursor).not.toBe(eventCursor);
  await expect
    .poll(() => domOrderedIdentityKeys(eventTable))
    .toEqual(eventPageTuples.map(identityKey));
  await expect(
    page.getByRole("navigation", {
      name: "job 이벤트 pagination",
      exact: true,
    }),
  ).toContainText("page 2");
  await expect(page.getByText("이벤트 목록 호출 실패", { exact: true })).toHaveCount(
    0,
  );
}

function isExactHistoryPageResponse(
  response: import("@playwright/test").Response,
  resource: "events" | "executions",
  syncScope: string,
  cursor: string | null,
): boolean {
  const url = new URL(response.url());
  const expected = new URLSearchParams({
    dataset_key: KMA_DATASET_KEY,
    page_size: String(PIPELINE_UI_PAGE_LIMIT),
    provider: KMA_PROVIDER,
    sync_scope: syncScope,
  });
  if (cursor !== null) expected.set("cursor", cursor);
  return (
    response.request().method() === "GET" &&
    url.pathname === `/api/proxy/v1/ops/pipeline/${resource}` &&
    [...url.searchParams.entries()].sort().toString() ===
      [...expected.entries()].sort().toString()
  );
}

function responseNextCursorOrNull(value: unknown, context: string): string | null {
  const envelope = asRecord(value);
  const meta = asRecord(envelope?.meta);
  const page = asRecord(meta?.page);
  const cursor = page?.next_cursor;
  if (cursor !== null && (typeof cursor !== "string" || cursor.length === 0)) {
    throw new Error(`${context} next_cursor 계약 위반`);
  }
  return cursor;
}

function responseNextCursor(value: unknown, context: string): string {
  const cursor = responseNextCursorOrNull(value, context);
  if (cursor === null) {
    throw new Error(`${context} continuation cursor가 없습니다`);
  }
  return cursor;
}

type OrderedIdentityTuple = readonly string[];

function identityKey(tuple: OrderedIdentityTuple): string {
  return JSON.stringify(tuple);
}

function exactStringArray(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function compareOrderedIdentity(
  left: OrderedIdentityTuple,
  right: OrderedIdentityTuple,
): number {
  if (left.length !== right.length) {
    throw new Error("history ordered identity tuple 길이 불일치");
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];
    if (leftValue === undefined || rightValue === undefined) {
      throw new Error("history ordered identity tuple 값 누락");
    }
    if (leftValue !== rightValue) return leftValue > rightValue ? -1 : 1;
  }
  return 0;
}

function orderedHistoryIdentityTuples(
  value: unknown,
  resource: "events" | "executions",
  context: string,
  syncScope: string,
): OrderedIdentityTuple[] {
  const envelope = asRecord(value);
  const data = asRecord(envelope?.data);
  if (
    !Array.isArray(data?.items) ||
    data.items.length === 0 ||
    data.items.length > PIPELINE_UI_PAGE_LIMIT
  ) {
    throw new Error(`${context} items 계약 위반`);
  }
  const tuples: OrderedIdentityTuple[] = [];
  for (const value of data.items) {
    const item = asRecord(value);
    if (item === null) throw new Error(`${context} item object 계약 위반`);
    if (resource === "events") {
      if (
        item.provider !== KMA_PROVIDER ||
        item.dataset_key !== KMA_DATASET_KEY ||
        item.sync_scope !== syncScope ||
        typeof item.occurred_at !== "string" ||
        Number.isNaN(Date.parse(item.occurred_at)) ||
        typeof item.event_id !== "string" ||
        !UUID_PATTERN.test(item.event_id)
      ) {
        throw new Error(`${context} event scope/identity tuple 불일치`);
      }
      tuples.push([item.occurred_at, item.event_id]);
      continue;
    }
    const pairs = item.provider_datasets;
    const pair = Array.isArray(pairs) ? asRecord(pairs[0]) : null;
    if (
      !exactStringArray(item.providers, [KMA_PROVIDER]) ||
      !exactStringArray(item.dataset_keys, [KMA_DATASET_KEY]) ||
      !Array.isArray(pairs) ||
      pairs.length !== 1 ||
      pair === null ||
      pair.provider !== KMA_PROVIDER ||
      pair.dataset_key !== KMA_DATASET_KEY ||
      pair.sync_scope !== syncScope ||
      typeof item.created_at !== "string" ||
      Number.isNaN(Date.parse(item.created_at)) ||
      typeof item.id !== "string" ||
      !UUID_PATTERN.test(item.id) ||
      !["import_job", "update_request"].includes(String(item.kind))
    ) {
      throw new Error(`${context} execution scope/identity tuple 불일치`);
    }
    tuples.push([item.created_at, item.id, String(item.kind)]);
  }
  const keys = tuples.map(identityKey);
  if (new Set(keys).size !== keys.length) {
    throw new Error(`${context} ordered identity tuple 중복`);
  }
  for (let index = 1; index < tuples.length; index += 1) {
    const previous = tuples[index - 1];
    const current = tuples[index];
    if (
      previous === undefined ||
      current === undefined ||
      compareOrderedIdentity(previous, current) !== -1
    ) {
      throw new Error(`${context} ordered identity tuple 순서 불일치`);
    }
  }
  responseNextCursorOrNull(value, context);
  return tuples;
}

function assertDisjointOrderedContinuation(
  firstPage: readonly OrderedIdentityTuple[],
  secondPage: readonly OrderedIdentityTuple[],
  context: string,
): void {
  const firstKeys = new Set(firstPage.map(identityKey));
  if (secondPage.some((tuple) => firstKeys.has(identityKey(tuple)))) {
    throw new Error(`${context} page1/page2 ordered identity가 중복됩니다`);
  }
  const firstLast = firstPage.at(-1);
  const secondFirst = secondPage[0];
  if (
    firstLast === undefined ||
    secondFirst === undefined ||
    compareOrderedIdentity(firstLast, secondFirst) !== -1
  ) {
    throw new Error(`${context} cursor page 경계 순서 불일치`);
  }
}

async function domOrderedIdentityKeys(table: Locator): Promise<string[]> {
  return table.locator("tbody tr[data-row-identity]").evaluateAll((nodes) =>
    nodes.map((node) => {
      const identity = node.getAttribute("data-row-identity");
      if (identity === null) throw new Error("DOM row identity 누락");
      const parsed = JSON.parse(identity) as unknown;
      if (
        !Array.isArray(parsed) ||
        parsed.length < 2 ||
        !parsed.every((value) => typeof value === "string" && value.length > 0)
      ) {
        throw new Error("DOM row ordered identity tuple 형식 불일치");
      }
      return identity;
    }),
  );
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
        syncScope,
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
