import { randomUUID } from "node:crypto";

import {
  expect,
  test,
  type Page,
  type TestInfo,
} from "@playwright/test";

import {
  createQueueSensorController,
  restoreQueueSensor,
  snapshotQueueSensor,
  startQueueSensor,
  stopQueueSensorAndWaitForQuiescence,
} from "./_ops-c7-dagster-sensor";
import {
  KMA_DATASET_KEY,
  KMA_PROVIDER,
  assertExactKmaPreviewResponse,
  assertExactNonTerminalFeatureUpdateRequests,
  assertKmaOnlyTerminalProviderScopes,
  bootstrapC7SameOriginPage,
  buildKmaRequest,
  buildPoiTargetBody,
  createCleanupState,
  createKmaRequest,
  deleteTrackedTarget,
  destructiveGateBlocker,
  exactDatasetUiPath,
  getExactDatasetDetail,
  getRequestDetail,
  listActivePoiTargets,
  previewBody,
  putTrackedTarget,
  requireBody,
  waitForTerminal,
  withC7Cleanup,
  type FeatureUpdateRequestCreateResponse,
  type OpsDatasetDetailResponse,
} from "./_ops-c7-admin-api";

const TEST_TIMEOUT = 30 * 60 * 1000;
const RUN_ID = `c7-empty-${Date.now()}-${Math.random()
  .toString(36)
  .slice(2, 8)}`;

type ScopeStateSnapshot = {
  consecutiveFailures: number;
  cursor: Record<string, unknown>;
  lastFailureAt: string | null;
  lastSuccessAt: string | null;
};

test.describe.configure({ mode: "serial", retries: 0 });

async function previewEmptyRequestFromUi(
  page: Page,
  syncScope: string,
  reason: string,
): Promise<void> {
  await page
    .getByRole("button", { name: "갱신 요청 생성", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "갱신 요청 생성",
    exact: true,
  });
  await dialog.getByLabel("provider", { exact: true }).fill(KMA_PROVIDER);
  await dialog
    .getByLabel("dataset_key", { exact: true })
    .fill(KMA_DATASET_KEY);
  await dialog
    .getByLabel("sync_scope (선택)", { exact: true })
    .fill(syncScope);
  const responsePromise = page.waitForResponse((response) => {
    return (
      response.request().method() === "POST" &&
      new URL(response.url()).pathname ===
        "/api/proxy/v1/ops/pipeline/requests/preview"
    );
  });
  await dialog
    .getByRole("button", { name: "dry-run 실행", exact: true })
    .click();
  await assertExactKmaPreviewResponse(
    await responsePromise,
    previewBody(
      buildKmaRequest(
        syncScope.slice("external_system:".length),
        reason,
      ),
    ),
  );
  await expect(dialog.getByTestId("request-preview-result")).toContainText(
    syncScope,
  );
  await dialog.getByRole("checkbox", { name: /dry-run/ }).uncheck();
  await dialog.getByLabel("사유", { exact: true }).fill(reason);
}

async function createEmptyRequestWhileSensorStopped(
  page: Page,
  externalSystem: string,
  state: ReturnType<typeof createCleanupState>,
): Promise<FeatureUpdateRequestCreateResponse> {
  const created = requireBody(
    await createKmaRequest(
      page,
      buildKmaRequest(externalSystem, `C7 ${RUN_ID} empty scope`),
      randomUUID(),
      state,
    ),
    201,
  );
  expect(
    requireBody(await getRequestDetail(page, created.data.request_id), 200).data
      .execution,
  ).toMatchObject({ dagster_run_id: null, status: "queued" });
  expect(
    requireBody(await getRequestDetail(page, created.data.request_id), 200).data
      .root.projected_job.dagster_run_id,
  ).toBeNull();
  return created;
}

async function assertQueuedRunNowBlockedFromUi(
  page: Page,
  requestId: string,
): Promise<void> {
  await page.goto(`/ops/pipeline?execution=update_request:${requestId}`);
  const detail = page.getByTestId("pipeline-execution-detail");
  await expect(detail).toBeVisible();
  await expect(
    detail.getByText("run-now 차단됨", { exact: true }),
  ).toBeVisible();
  await expect(
    detail.getByRole("button", { name: /run-now/ }),
  ).toHaveCount(0);
  await expect(
    detail.getByText(
      "큐 sensor가 RUNNING으로 확인될 때까지 dispatch 요청을 만들지 않습니다.",
      { exact: true },
    ),
  ).toBeVisible();
}

async function assertEmptyFailureFromUi(
  page: Page,
  syncScope: string,
  requestId: string,
): Promise<void> {
  await page.goto(exactDatasetUiPath(syncScope));
  const region = page.getByRole("region", {
    name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
    exact: true,
  });
  await expect(region).toBeVisible();
  const latest = region
    .getByText("선택 범위 최근 종료 실행", { exact: true })
    .locator("..");
  await expect(latest.getByText("실패", { exact: true })).toHaveCount(1);
  await expect(
    latest.locator(
      `a[href="/ops/pipeline?execution=update_request:${requestId}"]`,
    ),
  ).toHaveCount(1);
  await expect(region.getByText("최근 실행", { exact: true })).toBeVisible();
}

function hasSha256Attestation(value: string | undefined): boolean {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

function requireBarrierGates(testInfo: TestInfo): void {
  const blocker = destructiveGateBlocker(testInfo);
  test.skip(blocker !== null, blocker ?? "");
  test.skip(
    process.env.E2E_QUEUE_SENSOR_BARRIER !== "1",
    "GraphQL queue sensor snapshot/stop/quiescence/start/restore orchestrator가 E2E_QUEUE_SENSOR_BARRIER=1을 attestation하지 않아 empty 시나리오 전체를 실행하지 않습니다.",
  );
  test.skip(
    !hasSha256Attestation(process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256) ||
      !hasSha256Attestation(process.env.E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256),
    "host orchestrator의 UI/API·WS origin hash attestation이 없어 empty 시나리오 전체를 실행하지 않습니다.",
  );
  test.skip(
    !process.env.E2E_DAGSTER_URL ||
      !process.env.E2E_C7_ORCHESTRATOR_STATE_FILE,
    "Dagster URL과 durable restore state file을 소유한 host orchestrator가 없어 empty 시나리오 전체를 실행하지 않습니다.",
  );
}

function scopeStateSnapshot(
  detail: OpsDatasetDetailResponse | null,
  syncScope: string,
): ScopeStateSnapshot | null {
  const state = detail?.data.scopes.find((item) => item.sync_scope === syncScope);
  if (!state) return null;
  return {
    consecutiveFailures: state.consecutive_failures,
    cursor: state.cursor,
    lastFailureAt: state.last_failure_at,
    lastSuccessAt: state.last_success_at,
  };
}

test.describe("C7 KMA empty exact scope destructive live E2E", () => {
  test("sensor quiescence에서 target을 제거한 owned request만 canonical empty failure가 된다", async ({
    page,
  }, testInfo) => {
    requireBarrierGates(testInfo);
    test.setTimeout(TEST_TIMEOUT);
    const externalSystem = `e2e-${RUN_ID}`;
    const syncScope = `external_system:${externalSystem}`;
    const reason = `C7 ${RUN_ID} empty scope`;
    const target = { externalSystem, targetKey: `${RUN_ID}-target` };
    const targetBody = buildPoiTargetBody(126.978, 37.5665, {
      name: `C7 KMA empty ${RUN_ID}`,
      runId: RUN_ID,
    });
    const state = createCleanupState("empty", RUN_ID);
    await bootstrapC7SameOriginPage(page, "/ops/pipeline");
    await previewEmptyRequestFromUi(page, syncScope, reason);
    const controller = await createQueueSensorController();
    const sensorSnapshot = await snapshotQueueSensor(controller);
    if (sensorSnapshot.status !== "RUNNING") {
      throw new Error(
        "empty live UI preview는 최초 queue sensor RUNNING 상태에서만 안전하게 실행합니다.",
      );
    }
    await assertExactNonTerminalFeatureUpdateRequests(
      page,
      [],
      "queue sensor stop 전 preflight",
    );
    try {
      await withC7Cleanup(page, testInfo, state, async () => {
        await stopQueueSensorAndWaitForQuiescence(controller, sensorSnapshot);
        await assertExactNonTerminalFeatureUpdateRequests(
          page,
          [],
          "queue sensor stop/quiescence 후 preflight",
        );

        await putTrackedTarget(page, state, target, targetBody);
        const before = scopeStateSnapshot(
          requireBody(await getExactDatasetDetail(page, syncScope), 200),
          syncScope,
        );

        const created = await createEmptyRequestWhileSensorStopped(
          page,
          externalSystem,
          state,
        );

        const queuedBeforeDelete = requireBody(
          await getRequestDetail(page, created.data.request_id),
          200,
        );
        expect(queuedBeforeDelete.data.execution.status).toBe("queued");
        expect(queuedBeforeDelete.data.execution.dagster_run_id).toBeNull();
        expect(
          queuedBeforeDelete.data.root.projected_job.dagster_run_id,
        ).toBeNull();

        requireBody(
          await deleteTrackedTarget(page, state, target),
          200,
        );
        // sensor를 다시 시작하기 전에 owned request가 아직 미소유 queued이고,
        // 의도한 external_system active target이 0인지 함께 증명한다.
        const isolated = requireBody(
          await getRequestDetail(page, created.data.request_id),
          200,
        );
        expect(isolated.data.execution.status).toBe("queued");
        expect(isolated.data.execution.dagster_run_id).toBeNull();
        expect(isolated.data.root.projected_job.dagster_run_id).toBeNull();
        expect(
          requireBody(await listActivePoiTargets(page, externalSystem), 200).data
            .items,
        ).toHaveLength(0);
        await assertQueuedRunNowBlockedFromUi(
          page,
          created.data.request_id,
        );

        await assertExactNonTerminalFeatureUpdateRequests(
          page,
          [{ id: created.data.request_id, status: "queued" }],
          "queue sensor start 직전 owned request isolation",
        );
        await startQueueSensor(controller);
        const terminal = await waitForTerminal(
          page,
          created.data.request_id,
          undefined,
          state,
        );
        expect(terminal.data.execution.status).toBe("failed");
        assertKmaOnlyTerminalProviderScopes(terminal, { executed: "empty" });
        expect(terminal.data.execution.error_message).toContain(
          "KmaWeatherTargetScopeEmptyError",
        );
        const emptyEvents = terminal.data.events.filter(
          (event) =>
            event.code === "kma.target_scope_empty" &&
            event.sync_scope === syncScope &&
            event.job_id === created.data.job_id,
        );
        expect(emptyEvents).toHaveLength(1);
        expect(emptyEvents[0]?.payload).toMatchObject({
          failure_code: "kma.target_scope_empty",
          status: "failed",
        });

        // 삭제된 scope를 다시 노출해 state와 canonical history를 검사한다.
        await putTrackedTarget(page, state, target, targetBody);
        const after = requireBody(
          await getExactDatasetDetail(page, syncScope),
          200,
        );
        expect(after.data.latest_execution?.id).toBe(created.data.request_id);
        expect(
          after.data.run_history.items.some(
            (item) =>
              item.id === created.data.request_id &&
              item.status === "failed" &&
              item.sync_scope === syncScope,
          ),
        ).toBe(true);
        expect(
          after.data.event_history.items.filter(
            (event) =>
              event.job_id === created.data.job_id &&
              event.code === "kma.target_scope_empty" &&
              event.sync_scope === syncScope,
          ),
        ).toHaveLength(1);
        expect(scopeStateSnapshot(after, syncScope)).toEqual(before);
        await assertEmptyFailureFromUi(
          page,
          syncScope,
          created.data.request_id,
        );
      });
    } finally {
      // 실패 경로도 queued request cancel/terminal 확인과 target cleanup이 끝난
      // 뒤에만 최초 sensor 상태를 복원한다. 복원이 cleanup보다 앞서면 request를
      // 의도하지 않게 실행시킬 수 있다.
      if (
        state.cleanupResult?.allRequestsTerminal !== true ||
        state.cleanupResult.restored !== true
      ) {
        throw new Error(
          "empty cleanup이 모든 request terminal을 증명하지 못해 queue sensor 자동 복원을 차단했습니다.",
        );
      }
      await restoreQueueSensor(controller, sensorSnapshot);
    }
  });
});
