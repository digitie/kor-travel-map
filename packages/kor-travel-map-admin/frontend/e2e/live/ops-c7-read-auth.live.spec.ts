import { randomUUID } from "node:crypto";

import {
  expect,
  test,
  type Locator,
  type Page,
  type Request,
  type Response,
  type Route,
  type WebSocket as PlaywrightWebSocket,
} from "@playwright/test";

import {
  OPS_LIVE_EXPIRED_CLOSE_CODE,
  OPS_LIVE_TICKET_TTL_SECONDS,
  OPS_LIVE_UNAUTHORIZED_CLOSE_CODE,
} from "../../src/lib/ops-live-contract";
import {
  bootstrapC7SameOriginPage,
  buildPoiTargetBody,
  createCleanupState,
  deleteTrackedTarget,
  getPoiTarget,
  putTrackedTarget,
  requireBody,
  withC7Cleanup,
} from "./_ops-c7-admin-api";
import {
  EXPECTED_DATASETS_APP_TOPICS,
  assertC7ReadAuthLiveEnvironment,
  exerciseExpiredTicketRecoveryThroughDatasetsHook,
  exerciseHealthyLeaseRotationThroughDatasetsHook,
  gotoDatasetsAndTraceOpsLiveUrl,
  installAppSocketObserver,
  observedAppSockets,
  probeRejectedOpsLiveSockets,
  waitForObservedAppSocketClose,
  waitForObservedAppSocketData,
  type AppSocketObservation,
  type ObservedAppServerFrame,
} from "./_ops-live-browser";

const READY = { timeout: 20_000 } as const;
const REJECTION_TEST_TIMEOUT_MS = 90_000;
const TTL_TEST_TIMEOUT_MS = 150_000;
const NATURAL_ROTATION_TEST_TIMEOUT_MS = 180_000;
const IMMEDIATE_ROTATION_MAX_MS = 2_000;
const LOGOUT_SETTLE_MS = 31_000;
const LOGOUT_TEST_TIMEOUT_MS = 75_000;
const DATASETS_PATH = "/v1/ops/datasets";
const PIPELINE_OVERVIEW_PATH = "/v1/ops/pipeline/overview";
const COUNT_FORMATTER = new Intl.NumberFormat("ko-KR");

type CanonicalDatasetRow = {
  datasetKey: string;
  // 행 identity는 triple이다(ADR-088). 접근성 이름·딥링크·URL 복원이 모두 같은 축을
  // 쓴다. provider/dataset_key는 표시용 projection이고 딥링크 축이 아니다 —
  // `provider=`/`dataset=` 형태는 이제 legacy로 **거부**된다.
  operationKey: string;
  provider: string;
  providerDatasetId: number;
  syncScope: string;
};

type LiveDatasetRow = {
  catalog: Record<string, unknown> | null;
  catalogState: string;
  consecutiveFailures: number;
  datasetKey: string;
  datasetOpenIssues: number;
  freshnessState: string;
  operationKey: string;
  provider: string;
  providerDatasetId: number;
  providerOpenIssues: number;
  status: string;
  syncScope: string;
};

type PipelineOverview = {
  activeOperations: number;
  dagsterStatus: "ok" | "unavailable" | "error";
  failedOperations24h: number;
  queued: number;
  running: number;
};

type DatasetProjectionEvidence = {
  revision: number;
  sentAtMs: number;
  sequence: number;
  socketIndex: number;
};

type TimedGridResponse = {
  observedAtMs: number;
  response: Response;
  startedAtMs: number;
};

/**
 * 최종 n150 공개 UI에서만 파일 단위·실제 1 worker로 실행한다.
 *
 * E2E_LIVE_ALLOW_PROD=1 E2E_LIVE_WORKERS=1 E2E_BASE_URL=<redacted> \
 * E2E_C7_EXPECTED_UI_ORIGIN_SHA256=<redacted> \
 * E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256=<redacted> \
 * E2E_ADMIN_PASSWORD=<redacted> E2E_ADMIN_WRITE=1 \
 * E2E_C7_READ_AUTH_WRITE=1 E2E_C7_KMA_STATE_FILE=<absolute-0600-path> \
 * npm run e2e:live -- \
 * e2e/live/ops-c7-read-auth.live.spec.ts --workers=1 --retries=0
 *
 * origin/ticket/subprotocol/actual host는 assertion message나 attachment로 출력하지 않는다.
 */
test.describe("C7 datasets read + ops live auth (actual browser, live)", () => {
  test.describe.configure({ mode: "serial", retries: 0 });

  test.beforeAll(({}, testInfo) => {
    assertC7ReadAuthLiveEnvironment(testInfo.config.workers);
  });

  test("실 API count/state를 두 운영 페이지에 반영하고 invalid exact scope는 fail-closed한다", async ({
    page,
  }) => {
    await gotoDatasetsAndTraceOpsLiveUrl(page);
    await expect(
      page.getByRole("heading", { level: 1, name: "데이터셋", exact: true }),
    ).toBeVisible(READY);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );

    const datasetsRefresh = page.getByRole("button", {
      name: "새로고침",
      exact: true,
    });
    await expect(datasetsRefresh).toBeEnabled(READY);
    const gridResponsePromise = page.waitForResponse(
      isDatasetsGridResponse,
      READY,
    );
    await datasetsRefresh.click();
    const gridResponse = await gridResponsePromise;
    if (!gridResponse.ok()) {
      throw new Error(`datasets grid 조회 실패 (HTTP ${gridResponse.status()})`);
    }
    const gridPayload = await gridResponse.json();
    const rows = datasetRows(gridPayload);
    await expectDatasetSummary(page, rows);
    const canonical = canonicalRepresentative(rows);

    // 존재하지 않는 scope로 진입해도 canonical 행으로 **대체되지 않는다**(명시 실패).
    // 아래에서 정상 triple 딥링크로 다시 들어가 그 행이 열리는지 본다.
    const staleProviderOnlyScope = `external_system:c7-stale-${Date.now()}`;
    await page.goto(
      `/ops/datasets?provider_dataset_id=${canonical.providerDatasetId}` +
        `&sync_scope=${encodeURIComponent(staleProviderOnlyScope)}` +
        `&operation_key=${encodeURIComponent(canonical.operationKey)}`,
    );
    await expect(page.getByTestId("invalid-dataset-deep-link")).toBeVisible(READY);

    await page.goto(
      `/ops/datasets?provider_dataset_id=${canonical.providerDatasetId}` +
        `&sync_scope=${encodeURIComponent(canonical.syncScope)}` +
        `&operation_key=${encodeURIComponent(canonical.operationKey)}`,
    );

    await expect.poll(() => selectedTupleFromUrl(page), READY).toEqual({
      operationKey: canonical.operationKey,
      providerDatasetId: canonical.providerDatasetId,
      syncScope: canonical.syncScope,
    });
    await expect(
      page.getByText("데이터셋 상세", { exact: true }),
    ).toBeVisible(READY);
    await expect(page.getByTestId("invalid-dataset-deep-link")).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name:
          `${canonical.provider} ${canonical.datasetKey} ` +
          `${canonical.syncScope} ` +
          `${canonical.operationKey || "operation 없음"} 상세 열기`,
        exact: true,
      }),
    ).toHaveAttribute("aria-expanded", "true");

    const invalidScope = `external_system:c7-missing-${Date.now()}`;
    expect(rows.some((row) => row.syncScope === invalidScope)).toBe(false);
    await page.goto(
      `/ops/datasets?provider_dataset_id=${canonical.providerDatasetId}` +
        `&sync_scope=${encodeURIComponent(invalidScope)}` +
        `&operation_key=${encodeURIComponent(canonical.operationKey)}`,
    );

    await expect(page.getByTestId("invalid-dataset-deep-link")).toBeVisible(READY);
    await expect(page.getByText("데이터셋 상세", { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "지금 갱신", exact: true }),
    ).toHaveCount(0);
    await expect
      .poll(() => new URL(page.url()).searchParams.get("sync_scope"), READY)
      .toBe(invalidScope);

    await page.goto("/ops/pipeline");
    await expect(
      page.getByRole("heading", { level: 1, name: "파이프라인", exact: true }),
    ).toBeVisible(READY);
    const pipelineRefresh = page.getByRole("button", {
      name: "새로고침",
      exact: true,
    });
    await expect(pipelineRefresh).toBeEnabled(READY);
    const overviewResponsePromise = page.waitForResponse(
      isPipelineOverviewResponse,
      READY,
    );
    await pipelineRefresh.click();
    const overviewResponse = await overviewResponsePromise;
    if (!overviewResponse.ok()) {
      throw new Error(
        `pipeline overview 조회 실패 (HTTP ${overviewResponse.status()})`,
      );
    }
    await expectPipelineOverview(
      page,
      parsePipelineOverview(await overviewResponse.json()),
    );
  });

  test("ticket 없음과 서명 변조는 data frame 없이 4401로 닫힌다", async ({
    page,
  }) => {
    test.setTimeout(REJECTION_TEST_TIMEOUT_MS);
    await gotoDatasetsAndTraceOpsLiveUrl(page);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );

    const probes = await probeRejectedOpsLiveSockets(page);
    expect(probes.missing).toEqual({
      closeCode: OPS_LIVE_UNAUTHORIZED_CLOSE_CODE,
      dataFrames: 0,
    });
    expect(probes.tampered).toEqual({
      closeCode: OPS_LIVE_UNAUTHORIZED_CLOSE_CODE,
      dataFrames: 0,
    });
  });

  test("expired signed ticket을 받은 실제 app hook은 4408 뒤 fresh BFF ticket으로 live 복구한다", async ({
    page,
  }) => {
    test.setTimeout(TTL_TEST_TIMEOUT_MS);
    const probe = await exerciseExpiredTicketRecoveryThroughDatasetsHook(page);

    expect(probe.bffTicketRequests).toBe(2);
    expect(probe.expired).toEqual({
      closeCode: OPS_LIVE_EXPIRED_CLOSE_CODE,
      dataFrames: 0,
    });
    expect(probe.fresh.closeCode).toBeNull();
    assertExactAppSocketWireContract(probe.fresh);
    const helloIndex = probe.fresh.serverFrames.findIndex(
      (frame) => frame.type === "hello",
    );
    const subscribedIndex = probe.fresh.serverFrames.findIndex(
      (frame) => frame.type === "subscribed",
    );
    const datasetProjectionIndex = probe.fresh.serverFrames.findIndex(
      (frame) =>
        frame.topic === "dataset_projection" &&
        (frame.type === "snapshot" || frame.type === "update"),
    );
    expect(helloIndex).toBeGreaterThanOrEqual(0);
    expect(subscribedIndex).toBeGreaterThan(helloIndex);
    expect(datasetProjectionIndex).toBeGreaterThan(subscribedIndex);
    expect(probe.fresh.serverFrames[helloIndex]?.sequence).toBe(1);
    expect(probe.fresh.serverFrames[helloIndex]?.topics).toEqual([]);
    expect(probe.fresh.serverFrames[subscribedIndex]?.sequence).toBe(2);
    expect(probe.fresh.serverFrames[subscribedIndex]?.topics).toEqual([
      ...EXPECTED_DATASETS_APP_TOPICS,
    ]);

    const datasetProjection = probe.fresh.serverFrames[datasetProjectionIndex];
    expect(datasetProjection?.version).toBe(1);
    expect(datasetProjection?.topic).toBe("dataset_projection");
    expect(["snapshot", "update"]).toContain(datasetProjection?.type);
    expect(typeof datasetProjection?.revision).toBe("string");
    expect(datasetProjection?.revision?.trim().length).toBeGreaterThan(0);
    expect(datasetProjection?.data).toEqual({ live_revision: expect.any(Number) });

    await expect(
      page.getByRole("heading", { level: 1, name: "데이터셋", exact: true }),
    ).toBeVisible(READY);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );
  });

  test("healthy app socket은 data 뒤 자연 4408에서 backoff 없이 fresh lease로 rotation한다", async ({
    page,
  }) => {
    test.setTimeout(NATURAL_ROTATION_TEST_TIMEOUT_MS);
    const probe = await exerciseHealthyLeaseRotationThroughDatasetsHook(page);

    expect(probe.bffTicketRequests).toBe(2);
    expect(probe.first.closeCode).toBe(OPS_LIVE_EXPIRED_CLOSE_CODE);
    expect(probe.first.closedAt).not.toBeNull();
    assertExactAppSocketWireContract(probe.first);
    expect(probe.firstCloseToFreshTicketMs).toBeGreaterThanOrEqual(0);
    expect(probe.firstCloseToFreshTicketMs).toBeLessThanOrEqual(
      IMMEDIATE_ROTATION_MAX_MS,
    );
    expect(probe.firstCloseToFreshSocketMs).toBeGreaterThanOrEqual(0);
    expect(probe.firstCloseToFreshSocketMs).toBeLessThanOrEqual(
      IMMEDIATE_ROTATION_MAX_MS,
    );

    expect(probe.fresh.closeCode).toBeNull();
    assertExactAppSocketWireContract(probe.fresh);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );
  });

  test("외부 dataset_projection mutation은 열린 datasets 화면을 navigation/refresh 없이 갱신하고 복원한다", async ({
    page,
  }, testInfo) => {
    const runId = randomUUID();
    const state = createCleanupState("invalidation", runId);
    const target = {
      externalSystem: `c7-invalidation-${runId}`,
      targetKey: "disabled-live-projection",
    };
    await installAppSocketObserver(page);
    await bootstrapC7SameOriginPage(page, "/ops/datasets");
    await gotoDatasetsAndTraceOpsLiveUrl(page);
    await waitForObservedAppSocketData(page, 0);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );

    const refreshButton = page.getByRole("button", {
      name: "새로고침",
      exact: true,
    });
    const baselineResponsePromise = page.waitForResponse(
      isDatasetsGridResponse,
      READY,
    );
    await refreshButton.click();
    const baselineResponse = await baselineResponsePromise;
    if (!baselineResponse.ok()) {
      throw new Error(
        `dataset projection baseline 조회 실패 (HTTP ${baselineResponse.status()})`,
      );
    }
    const baselineRows = datasetRows(await baselineResponse.json());
    await expectDatasetSummary(page, baselineRows);
    const baselineEvidence = latestDatasetProjectionEvidence(
      await observedAppSockets(page),
    );
    if (baselineEvidence === null) {
      throw new Error("dataset_projection baseline ordering 관측 실패");
    }

    const gridResponses: TimedGridResponse[] = [];
    let documentNavigations = 0;
    const responseListener = (response: Response) => {
      if (isDatasetsGridResponse(response)) {
        gridResponses.push({
          observedAtMs: Date.now(),
          response,
          startedAtMs: response.request().timing().startTime,
        });
      }
    };
    const requestListener = (request: Request) => {
      if (
        request.isNavigationRequest() &&
        request.resourceType() === "document"
      ) {
        documentNavigations += 1;
      }
    };
    page.on("response", responseListener);
    page.on("request", requestListener);
    const stablePath = await page.evaluate(
      () => window.location.pathname + window.location.search,
    );
    try {
      const cleanup = await withC7Cleanup(page, testInfo, state, async () => {
        const body = {
          ...buildPoiTargetBody(126.978, 37.5665, {
            name: "C7 disabled projection invalidation",
            runId,
          }),
          metadata: { note: `C7 invalidation ${runId}` },
          refresh_policy: "disabled" as const,
          update_enabled: false,
        };
        const createBaseline = latestDatasetProjectionEvidence(
          await observedAppSockets(page),
        );
        if (createBaseline === null) {
          throw new Error("dataset_projection create 직전 baseline 소실");
        }
        const createdTarget = await putTrackedTarget(page, state, target, body);
        const createTargetRevisionAtMs = targetRevisionAtMs(
          createdTarget.data.updated_at,
        );
        const exactCreatedTarget = requireBody(
          await getPoiTarget(page, target.externalSystem, target.targetKey),
          200,
        );
        expect(exactCreatedTarget.data).toMatchObject({
          deleted_at: null,
          external_system: target.externalSystem,
          target_id: createdTarget.data.target_id,
          target_key: target.targetKey,
          update_enabled: false,
        });

        await expect
          .poll(
            async () =>
              datasetProjectionEvidenceAfter(
                await observedAppSockets(page),
                createBaseline,
                createTargetRevisionAtMs,
              ) !== null,
            READY,
          )
          .toBe(true);
        const createEvidence = datasetProjectionEvidenceAfter(
          await observedAppSockets(page),
          createBaseline,
          createTargetRevisionAtMs,
        );
        if (createEvidence === null) {
          throw new Error("dataset_projection create ordering evidence 소실");
        }
        expect(createEvidence.revision).toBeGreaterThan(
          createBaseline.revision,
        );
        await expect
          .poll(
            () =>
              gridResponsesAfterEvidence(
                gridResponses,
                createEvidence,
                createTargetRevisionAtMs,
              ).length,
            READY,
          )
          .toBeGreaterThan(0);
        const createdGridResponse = gridResponsesAfterEvidence(
          gridResponses,
          createEvidence,
          createTargetRevisionAtMs,
        ).at(-1)?.response;
        if (!createdGridResponse?.ok()) {
          throw new Error("dataset_projection create refetch 실패 (body redacted)");
        }
        const createdRows = datasetRows(await createdGridResponse.json());
        expect(sameDatasetRows(createdRows, baselineRows)).toBe(true);
        await expectDatasetSummary(page, createdRows);
        expect(documentNavigations).toBe(0);
        expect(
          await page.evaluate(
            () => window.location.pathname + window.location.search,
          ),
        ).toBe(stablePath);

        const deleteBaseline = latestDatasetProjectionEvidence(
          await observedAppSockets(page),
        );
        if (deleteBaseline === null) {
          throw new Error("dataset_projection delete 직전 baseline 소실");
        }
        const deletedTarget = requireBody(
          await deleteTrackedTarget(page, state, target),
          200,
        );
        const deleteTargetRevisionAtMs = targetRevisionAtMs(
          deletedTarget.data.updated_at,
        );
        expect(deletedTarget.data).toMatchObject({
          external_system: target.externalSystem,
          target_id: createdTarget.data.target_id,
          target_key: target.targetKey,
        });
        expect(deletedTarget.data.deleted_at).not.toBeNull();
        expect(
          (await getPoiTarget(page, target.externalSystem, target.targetKey))
            .status,
        ).toBe(404);

        await expect
          .poll(
            async () =>
              datasetProjectionEvidenceAfter(
                await observedAppSockets(page),
                deleteBaseline,
                deleteTargetRevisionAtMs,
              ) !== null,
            READY,
          )
          .toBe(true);
        const deleteEvidence = datasetProjectionEvidenceAfter(
          await observedAppSockets(page),
          deleteBaseline,
          deleteTargetRevisionAtMs,
        );
        if (deleteEvidence === null) {
          throw new Error("dataset_projection delete ordering evidence 소실");
        }
        expect(deleteEvidence.revision).toBeGreaterThan(
          deleteBaseline.revision,
        );
        await expect
          .poll(
            () =>
              gridResponsesAfterEvidence(
                gridResponses,
                deleteEvidence,
                deleteTargetRevisionAtMs,
              ).length,
            READY,
          )
          .toBeGreaterThan(0);
        const restoredGridResponse = gridResponsesAfterEvidence(
          gridResponses,
          deleteEvidence,
          deleteTargetRevisionAtMs,
        ).at(-1)?.response;
        if (!restoredGridResponse?.ok()) {
          throw new Error("dataset_projection restore refetch 실패 (body redacted)");
        }
        const restoredRows = datasetRows(await restoredGridResponse.json());
        expect(sameDatasetRows(restoredRows, baselineRows)).toBe(true);
        await expectDatasetSummary(page, restoredRows);
        expect(documentNavigations).toBe(0);
        expect(
          await page.evaluate(
            () => window.location.pathname + window.location.search,
          ),
        ).toBe(stablePath);
      });

      expect(cleanup).toEqual({
        allRequestsTerminal: true,
        preservedForManualCleanup: false,
        restored: true,
      });
      expect(state.requestIds.size).toBe(0);
      expect(state.cleanupResult).toEqual(cleanup);
      expect(
        (await getPoiTarget(page, target.externalSystem, target.targetKey))
          .status,
      ).toBe(404);
    } finally {
      page.off("response", responseListener);
      page.off("request", requestListener);
    }
  });

  // 이 테스트는 shared storageState의 서버 session을 실제로 무효화한다. serial
  // describe의 마지막 등록으로 고정하며, 이 아래에는 인증이 필요한 test를 두지 않는다.
  test("LAST: 실제 로그아웃 UI는 현재 socket을 즉시 닫고 ticket/socket을 재생성하지 않는다", async ({
    page,
  }) => {
    test.setTimeout(LOGOUT_TEST_TIMEOUT_MS);
    const probe = await exerciseActualUiLogout(page);

    assertExactAppSocketWireContract(probe.healthySocket);
    expect(probe.closeCodeBeforeLogoutResponse).toBe(1000);
    expect(probe.closeLatencyMs).toBeGreaterThanOrEqual(0);
    expect(probe.closeLatencyMs).toBeLessThanOrEqual(
      IMMEDIATE_ROTATION_MAX_MS,
    );
    expect(probe.ticketRequestsBeforeLogout).toBe(1);
    expect(probe.ticketRequestsAtRedirect).toBe(
      probe.ticketRequestsBeforeLogout,
    );
    expect(probe.ticketRequestsAfterSettle).toBe(
      probe.ticketRequestsBeforeLogout,
    );
    expect(probe.socketsBeforeLogout).toBe(1);
    expect(probe.socketsAfterSettle).toBe(probe.socketsBeforeLogout);
    expect(probe.redirectPath).toBe("/login");
  });
});

type ActualUiLogoutProbe = {
  closeCodeBeforeLogoutResponse: number;
  closeLatencyMs: number;
  healthySocket: AppSocketObservation;
  redirectPath: string;
  socketsAfterSettle: number;
  socketsBeforeLogout: number;
  ticketRequestsAfterSettle: number;
  ticketRequestsAtRedirect: number;
  ticketRequestsBeforeLogout: number;
};

async function exerciseActualUiLogout(page: Page): Promise<ActualUiLogoutProbe> {
  await installAppSocketObserver(page);
  let ticketRequests = 0;
  const sockets: PlaywrightWebSocket[] = [];
  const requestListener = (request: Request) => {
    let pathname = "";
    try {
      pathname = new URL(request.url()).pathname;
    } catch {
      return;
    }
    if (request.method() === "POST" && pathname === "/api/auth/live-ticket") {
      ticketRequests += 1;
    }
  };
  const socketListener = (socket: PlaywrightWebSocket) => {
    let pathname = "";
    try {
      pathname = new URL(socket.url()).pathname;
    } catch {
      return;
    }
    if (pathname === "/v1/ops/live") sockets.push(socket);
  };
  page.on("request", requestListener);
  page.on("websocket", socketListener);
  try {
    await gotoDatasetsAndTraceOpsLiveUrl(page);
    await waitForObservedAppSocketData(page, 0);
    await expect(page.getByTestId("datasets-live-mode")).toHaveText(
      "실시간 갱신",
      READY,
    );
    const healthySocket = (await observedAppSockets(page))[0];
    const activeSocket = sockets[0];
    if (!healthySocket || !activeSocket) {
      throw new Error("logout 전 actual app socket 관측이 불완전합니다");
    }
    const ticketRequestsBeforeLogout = ticketRequests;
    const socketsBeforeLogout = sockets.length;
    let closeAt: number | null = null;
    const closePromise = new Promise<void>((resolve) => {
      activeSocket.once("close", () => {
        closeAt = Date.now();
        resolve();
      });
    });
    let closeCodeBeforeLogoutResponse: number | null = null;
    let logoutRouteSeen = false;
    let resolveLogoutRouteSettled!: () => void;
    const logoutRouteSettled = new Promise<void>((resolve) => {
      resolveLogoutRouteSettled = resolve;
    });
    const logoutRoute = async (route: Route) => {
      logoutRouteSeen = true;
      try {
        const response = await route.fetch();
        await waitForObservedAppSocketClose(page, 0, 1000, 5_000);
        closeCodeBeforeLogoutResponse =
          (await observedAppSockets(page))[0]?.closeCode ?? 0;
        await route.fulfill({
          body: await response.body(),
          headers: response.headers(),
          status: response.status(),
        });
      } catch {
        await route.abort("failed");
        throw new Error("logout 응답 전 socket close 관측 실패 (values redacted)");
      } finally {
        resolveLogoutRouteSettled();
      }
    };
    await page.route("**/api/auth/logout", logoutRoute);
    const logoutStartedAt = Date.now();
    let logoutPrimaryError: unknown;
    try {
      await Promise.all([
        closePromise,
        page.getByRole("button", { name: "로그아웃", exact: true }).click(),
      ]);
      await page.waitForFunction(
        () => window.location.pathname === "/login",
        undefined,
        { timeout: READY.timeout },
      );
    } catch (error) {
      logoutPrimaryError = error;
      throw new Error("실제 logout UI 종료/redirect 확인 실패 (values redacted)");
    } finally {
      const teardownErrors: unknown[] = [];
      if (logoutRouteSeen) {
        await Promise.race([
          logoutRouteSettled,
          new Promise<never>((_, reject) =>
            setTimeout(
              () => reject(new Error("logout route handler settlement timeout")),
              READY.timeout,
            ),
          ),
        ]).catch((error: unknown) => teardownErrors.push(error));
      }
      await page
        .unroute("**/api/auth/logout", logoutRoute)
        .catch((error: unknown) => teardownErrors.push(error));
      if (teardownErrors.length > 0) {
        throw new AggregateError(
          logoutPrimaryError === undefined
            ? teardownErrors
            : [logoutPrimaryError, ...teardownErrors],
          "logout primary/route cleanup 실패",
        );
      }
    }
    const redirectPath = await page.evaluate(() => window.location.pathname);
    const ticketRequestsAtRedirect = ticketRequests;
    await page.waitForTimeout(LOGOUT_SETTLE_MS);
    if (closeAt === null || closeCodeBeforeLogoutResponse === null) {
      throw new Error("logout socket close timing 관측이 불완전합니다");
    }
    return {
      closeCodeBeforeLogoutResponse,
      closeLatencyMs: closeAt - logoutStartedAt,
      healthySocket,
      redirectPath,
      socketsAfterSettle: sockets.length,
      socketsBeforeLogout,
      ticketRequestsAfterSettle: ticketRequests,
      ticketRequestsAtRedirect,
      ticketRequestsBeforeLogout,
    };
  } finally {
    page.off("request", requestListener);
    page.off("websocket", socketListener);
  }
}

function proxyPath(response: Response): string {
  return new URL(response.url()).pathname.replace(/^\/api\/proxy/, "");
}

function isDatasetsGridResponse(response: Response): boolean {
  return (
    response.request().method() === "GET" &&
    proxyPath(response) === DATASETS_PATH
  );
}

function isPipelineOverviewResponse(response: Response): boolean {
  return (
    response.request().method() === "GET" &&
    proxyPath(response) === PIPELINE_OVERVIEW_PATH
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function datasetRows(payload: unknown): LiveDatasetRow[] {
  if (
    !isRecord(payload) ||
    !isRecord(payload.data) ||
    !Array.isArray(payload.data.items)
  ) {
    throw new Error("datasets grid 응답 envelope가 올바르지 않습니다");
  }
  return payload.data.items.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.provider !== "string" ||
      typeof item.dataset_key !== "string" ||
      typeof item.provider_dataset_id !== "number" ||
      typeof item.sync_scope !== "string" ||
      typeof item.catalog_state !== "string" ||
      typeof item.consecutive_failures !== "number" ||
      !isRecord(item.dataset_issues) ||
      typeof item.dataset_issues.open_count !== "number" ||
      typeof item.provider_dataset_id !== "number" ||
      typeof item.status !== "string" ||
      !isRecord(item.freshness) ||
      typeof item.freshness.state !== "string" ||
      !isRecord(item.provider_issues) ||
      typeof item.provider_issues.open_count !== "number" ||
      !(item.catalog === null || isRecord(item.catalog))
    ) {
      throw new Error("datasets grid row 계약이 올바르지 않습니다");
    }
    return {
      catalog: item.catalog,
      catalogState: item.catalog_state,
      consecutiveFailures: item.consecutive_failures,
      datasetKey: item.dataset_key,
      datasetOpenIssues: item.dataset_issues.open_count,
      freshnessState: item.freshness.state,
      operationKey:
        typeof item.operation_key === "string" ? item.operation_key : "",
      provider: item.provider,
      providerDatasetId: item.provider_dataset_id,
      providerOpenIssues: item.provider_issues.open_count,
      status: item.status,
      syncScope: item.sync_scope,
    };
  });
}

function canonicalRepresentative(
  rows: readonly LiveDatasetRow[],
): CanonicalDatasetRow {
  const representatives: CanonicalDatasetRow[] = [];
  const seenProviders = new Set<string>();
  for (const item of rows) {
    const scopeRefresh = isRecord(item.catalog?.scope_refresh)
      ? item.catalog.scope_refresh
      : null;
    if (
      item.catalogState !== "canonical" ||
      scopeRefresh?.default_sync_scope !== item.syncScope ||
      seenProviders.has(item.provider)
    ) {
      continue;
    }
    seenProviders.add(item.provider);
    representatives.push({
      datasetKey: item.datasetKey,
      operationKey: item.operationKey,
      provider: item.provider,
      providerDatasetId: item.providerDatasetId,
      syncScope: item.syncScope,
    });
  }

  const representative =
    representatives.find((row) => row.syncScope === "dataset_wide") ??
    representatives[0];
  if (!representative) {
    throw new Error("canonical provider 대표 dataset row가 없습니다");
  }
  return representative;
}

async function expectDatasetSummary(
  page: Page,
  rows: readonly LiveDatasetRow[],
): Promise<void> {
  const summary = page.getByTestId("datasets-status-summary");
  await expect(summary).toHaveAttribute("aria-label", "데이터셋 상태 요약");
  const values = [
    `제공자 ${formatCount(new Set(rows.map((row) => row.provider)).size)}`,
    `행 ${formatCount(rows.length)}`,
    `실패 ${formatCount(
      rows.filter((row) => row.consecutiveFailures > 0).length,
    )}`,
    `오래됨(SLA 초과) ${formatCount(
      rows.filter((row) => row.freshnessState === "overdue").length,
    )}`,
    `미실행 ${formatCount(
      rows.filter((row) => row.status === "never_run").length,
    )}`,
    `이슈 ${formatCount(datasetGridOpenIssueCount(rows))}`,
  ];
  for (const value of values) {
    await expect(summary.getByText(value, { exact: true })).toHaveCount(1);
  }
}

/** UI의 dataset-issues.ts와 같은 provider_dataset_id max dedupe 계약. */
function datasetGridOpenIssueCount(rows: readonly LiveDatasetRow[]): number {
  const countsByProviderDatasetId = new Map<number, number>();
  for (const row of rows) {
    countsByProviderDatasetId.set(
      row.providerDatasetId,
      Math.max(
        countsByProviderDatasetId.get(row.providerDatasetId) ?? 0,
        row.datasetOpenIssues,
      ),
    );
  }
  return [...countsByProviderDatasetId.values()].reduce(
    (sum, count) => sum + count,
    0,
  );
}

function sameDatasetRows(
  left: readonly LiveDatasetRow[],
  right: readonly LiveDatasetRow[],
): boolean {
  const identity = (row: LiveDatasetRow) =>
    JSON.stringify([
      row.provider,
      row.datasetKey,
      row.syncScope,
      row.catalogState,
      row.consecutiveFailures,
      row.datasetOpenIssues,
      row.providerDatasetId,
      row.freshnessState,
      row.status,
    ]);
  return (
    left.length === right.length &&
    left.every((row, index) => identity(row) === identity(right[index]!))
  );
}

function parsePipelineOverview(payload: unknown): PipelineOverview {
  if (
    !isRecord(payload) ||
    !isRecord(payload.data) ||
    typeof payload.data.active_operations !== "number" ||
    typeof payload.data.failed_operations_24h !== "number" ||
    !isRecord(payload.data.operations_by_status) ||
    !isRecord(payload.data.dagster) ||
    !["ok", "unavailable", "error"].includes(
      String(payload.data.dagster.status),
    )
  ) {
    throw new Error("pipeline overview 응답 계약이 올바르지 않습니다");
  }
  const byStatus = payload.data.operations_by_status;
  const statusCount = (status: string): number => {
    const value = byStatus[status] ?? 0;
    if (typeof value !== "number") {
      throw new Error("pipeline overview status count 계약이 올바르지 않습니다");
    }
    return value;
  };
  return {
    activeOperations: payload.data.active_operations,
    dagsterStatus: payload.data.dagster
      .status as PipelineOverview["dagsterStatus"],
    failedOperations24h: payload.data.failed_operations_24h,
    queued: statusCount("queued"),
    running: statusCount("running"),
  };
}

async function expectPipelineOverview(
  page: Page,
  overview: PipelineOverview,
): Promise<void> {
  const strip = page.getByRole("region", {
    name: "파이프라인 상태 스트립",
    exact: true,
  });
  await expect(strip).toBeVisible(READY);
  await expectKpiValue(strip, "활성 작업", overview.activeOperations);
  await expectKpiValue(strip, "대기", overview.queued);
  await expectKpiValue(strip, "실행 중", overview.running);
  await expectKpiValue(strip, "최근 24시간 실패", overview.failedOperations24h);

  const dagsterLabel = {
    error: "오류",
    ok: "정상",
    unavailable: "사용불가",
  }[overview.dagsterStatus];
  await expect(
    strip.getByTestId("dagster-status-card").getByText(dagsterLabel, {
      exact: true,
    }),
  ).toHaveCount(1);
}

async function expectKpiValue(
  strip: Locator,
  label: string,
  value: number,
): Promise<void> {
  const labelNode = strip.getByText(label, { exact: true });
  await expect(labelNode).toHaveCount(1);
  await expect(
    labelNode.locator("..").getByText(formatCount(value), { exact: true }),
  ).toHaveCount(1);
}

function assertStrictServerEnvelope(
  frames: readonly ObservedAppServerFrame[],
): void {
  expect(frames.length).toBeGreaterThanOrEqual(3);
  let previousSequence = 0;
  for (const frame of frames) {
    expect(frame.payloadKind).toBe("string-json-record");
    expect(frame.version).toBe(1);
    expect(Number.isSafeInteger(frame.sequence)).toBe(true);
    expect(frame.sequence).toBeGreaterThan(previousSequence);
    expect(typeof frame.sentAt).toBe("string");
    expect(Number.isNaN(Date.parse(frame.sentAt ?? ""))).toBe(false);
    if (frame.type === "hello") {
      expect(frame.rawKeys).toEqual([
        "actor",
        "poll_interval_ms",
        "sent_at",
        "sequence",
        "ticket_expires_at",
        "topics",
        "type",
        "version",
      ]);
      expect(frame.actor).toBe(process.env.E2E_ADMIN_USERNAME ?? "admin");
      expect(frame.pollIntervalMs).toBe(2_000);
      expect(frame.topics).toEqual([]);
      expect(typeof frame.ticketExpiresAt).toBe("string");
      const sentAt = Date.parse(frame.sentAt ?? "");
      const ticketExpiresAt = Date.parse(frame.ticketExpiresAt ?? "");
      expect(Number.isNaN(ticketExpiresAt)).toBe(false);
      expect(ticketExpiresAt).toBeGreaterThan(sentAt);
      expect(ticketExpiresAt - sentAt).toBeLessThanOrEqual(
        OPS_LIVE_TICKET_TTL_SECONDS * 1_000,
      );
    } else if (frame.type === "subscribed") {
      expect(frame.rawKeys).toEqual([
        "sent_at",
        "sequence",
        "topics",
        "type",
        "version",
      ]);
      expect(frame.topics).toEqual([...EXPECTED_DATASETS_APP_TOPICS]);
    } else if (frame.type === "snapshot" || frame.type === "update") {
      expect(frame.rawKeys).toEqual([
        "data",
        "revision",
        "sent_at",
        "sequence",
        "topic",
        "type",
        "version",
      ]);
      expect([...EXPECTED_DATASETS_APP_TOPICS]).toContain(frame.topic);
      expect(frame.data).not.toBeNull();
    } else if (frame.type === "heartbeat") {
      expect(frame.rawKeys).toEqual([
        "sent_at",
        "sequence",
        "topics",
        "type",
        "version",
      ]);
      expect(frame.topics).toEqual([...EXPECTED_DATASETS_APP_TOPICS]);
    } else {
      throw new Error("actual app socket에 예상하지 않은 server frame type이 있습니다");
    }
    previousSequence = frame.sequence ?? previousSequence;
  }
}

function assertExactAppSocketWireContract(
  observation: AppSocketObservation,
): void {
  expect(observation.dataFrames).toBe(observation.serverFrames.length);
  expect(observation.sentCommands).toEqual([
    {
      payloadKind: "string-json-record",
      rawKeys: ["topics", "type"],
      topics: [...EXPECTED_DATASETS_APP_TOPICS],
      type: "replace",
    },
  ]);
  assertStrictServerEnvelope(observation.serverFrames);
  const helloIndex = observation.serverFrames.findIndex(
    (frame) => frame.type === "hello",
  );
  const subscribedIndex = observation.serverFrames.findIndex(
    (frame) => frame.type === "subscribed",
  );
  const datasetProjectionIndex = observation.serverFrames.findIndex(
    (frame) =>
      frame.topic === "dataset_projection" &&
      (frame.type === "snapshot" || frame.type === "update"),
  );
  expect(
    observation.serverFrames.filter((frame) => frame.type === "hello"),
  ).toHaveLength(1);
  expect(
    observation.serverFrames.filter((frame) => frame.type === "subscribed"),
  ).toHaveLength(1);
  expect(helloIndex).toBe(0);
  expect(subscribedIndex).toBeGreaterThan(helloIndex);
  expect(datasetProjectionIndex).toBeGreaterThan(subscribedIndex);
}

function latestDatasetProjectionEvidence(
  observations: readonly AppSocketObservation[],
): DatasetProjectionEvidence | null {
  let latest: DatasetProjectionEvidence | null = null;
  for (const [socketIndex, observation] of observations.entries()) {
    for (const frame of observation.serverFrames) {
      if (
        frame.topic !== "dataset_projection" ||
        (frame.type !== "snapshot" && frame.type !== "update")
      ) {
        continue;
      }
      const revision = frame.data?.live_revision;
      if (typeof revision !== "number" || !Number.isSafeInteger(revision)) {
        throw new Error("dataset_projection live_revision 계약 위반");
      }
      if (
        frame.sequence === null ||
        !Number.isSafeInteger(frame.sequence) ||
        frame.sentAt === null ||
        Number.isNaN(Date.parse(frame.sentAt))
      ) {
        throw new Error("dataset_projection ordering 계약 위반");
      }
      latest = {
        revision,
        sentAtMs: Date.parse(frame.sentAt),
        sequence: frame.sequence,
        socketIndex,
      };
    }
  }
  return latest;
}

function targetRevisionAtMs(updatedAt: string): number {
  const value = Date.parse(updatedAt);
  if (Number.isNaN(value)) {
    throw new Error("POI target updated_at revision 계약 위반");
  }
  return value;
}

function datasetProjectionEvidenceAfter(
  observations: readonly AppSocketObservation[],
  baseline: DatasetProjectionEvidence,
  targetRevisionAtMs: number,
): DatasetProjectionEvidence | null {
  for (const [socketIndex, observation] of observations.entries()) {
    if (socketIndex < baseline.socketIndex) continue;
    for (const frame of observation.serverFrames) {
      if (
        frame.topic !== "dataset_projection" ||
        (frame.type !== "snapshot" && frame.type !== "update") ||
        frame.sequence === null ||
        frame.sentAt === null
      ) {
        continue;
      }
      const revision = frame.data?.live_revision;
      const sentAtMs = Date.parse(frame.sentAt);
      const orderedAfterBaseline =
        socketIndex > baseline.socketIndex ||
        frame.sequence > baseline.sequence;
      if (
        typeof revision === "number" &&
        Number.isSafeInteger(revision) &&
        orderedAfterBaseline &&
        revision > baseline.revision &&
        !Number.isNaN(sentAtMs) &&
        sentAtMs >= targetRevisionAtMs
      ) {
        return {
          revision,
          sentAtMs,
          sequence: frame.sequence,
          socketIndex,
        };
      }
    }
  }
  return null;
}

function gridResponsesAfterEvidence(
  responses: readonly TimedGridResponse[],
  evidence: DatasetProjectionEvidence,
  targetRevisionAtMs: number,
): TimedGridResponse[] {
  return responses.filter(
    (item) =>
      item.observedAtMs >= targetRevisionAtMs &&
      item.startedAtMs >= evidence.sentAtMs,
  );
}

function formatCount(value: number): string {
  return COUNT_FORMATTER.format(value);
}

function selectedTupleFromUrl(page: Page): {
  operationKey: string;
  providerDatasetId: number;
  syncScope: string;
} {
  const url = new URL(page.url());
  return {
    operationKey: url.searchParams.get("operation_key") ?? "",
    providerDatasetId: Number(url.searchParams.get("provider_dataset_id") ?? 0),
    syncScope: url.searchParams.get("sync_scope") ?? "",
  };
}
