import {
  expect,
  test,
  type Page,
  type TestInfo,
} from "@playwright/test";

import {
  KMA_DATASET_KEY,
  KMA_PROVIDER,
  assertExactKmaPreviewResponse,
  assertKmaOnlyTerminalProviderScopes,
  bootstrapC7SameOriginPage,
  buildKmaRequest,
  buildPoiTargetBody,
  createCleanupState,
  destructiveGateBlocker,
  exactDatasetUiPath,
  getExactDatasetDetail,
  putTrackedTarget,
  previewBody,
  requireBody,
  runCreateDeleteCanary,
  submitTrackedUiKmaCreate,
  waitForTerminal,
  withC7Cleanup,
  type FeatureUpdateRequestCreateResponse,
  type OpsDatasetDetailResponse,
  type TargetRef,
} from "./_ops-c7-admin-api";

const CAP_TEST_TIMEOUT = 75 * 60 * 1000;
const CAP_CLEANUP_TERMINAL_TIMEOUT = 4 * 60 * 1000;
const TARGET_CREATE_BATCH_SIZE = 3;
const RUN_ID = `c7-cap-${Date.now()}-${Math.random()
  .toString(36)
  .slice(2, 8)}`;

type ScopeStateSnapshot = {
  consecutiveFailures: number;
  cursor: Record<string, unknown>;
  lastFailureAt: string | null;
  lastSuccessAt: string | null;
};

test.describe.configure({ mode: "serial", retries: 0 });

async function createCapRequestFromUi(
  page: Page,
  syncScope: string,
  reason: string,
  state: ReturnType<typeof createCleanupState>,
  targets: readonly TargetRef[],
): Promise<FeatureUpdateRequestCreateResponse> {
  await page.goto("/ops/pipeline");
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
  const previewResponsePromise = page.waitForResponse((response) => {
    return (
      response.request().method() === "POST" &&
      new URL(response.url()).pathname ===
        "/api/proxy/v1/ops/pipeline/requests/preview"
    );
  });
  await dialog
    .getByRole("button", { name: "dry-run 실행", exact: true })
    .click();
  const expectedPreview = previewBody(
    buildKmaRequest(
      syncScope.slice("external_system:".length),
      reason,
    ),
  );
  await assertExactKmaPreviewResponse(
    await previewResponsePromise,
    expectedPreview,
  );
  await expect(dialog.getByTestId("request-preview-result")).toContainText(
    syncScope,
  );

  await dialog.getByRole("checkbox", { name: /dry-run/ }).uncheck();
  await dialog.getByLabel("사유", { exact: true }).fill(reason);
  const externalSystem = syncScope.slice("external_system:".length);
  const expectedBody = buildKmaRequest(externalSystem, reason);
  const { created, recovered } = await submitTrackedUiKmaCreate(
    page,
    state,
    expectedBody,
    targets,
    () =>
      dialog
        .getByRole("button", { name: "요청 생성", exact: true })
        .click(),
  );
  if (recovered) {
    await page.goto(
      `/ops/pipeline?execution=update_request:${created.data.request_id}`,
    );
  } else {
    await expect(
      dialog
        .getByTestId("request-create-result")
        .getByText("요청 생성됨", { exact: true }),
    ).toHaveCount(1);
    await dialog
      .getByRole("button", { name: "타임라인에서 보기", exact: true })
      .click();
  }

  const detail = page.getByTestId("pipeline-execution-detail");
  await expect(detail).toBeVisible();
  await expect(detail).toContainText(created.data.request_id.slice(0, 12));
  return created;
}

async function assertCapFailureFromUi(
  page: Page,
  syncScope: string,
  requestId: string,
): Promise<void> {
  await page.goto(exactDatasetUiPath(syncScope));
  const region = page.getByRole("region", {
    name: `${KMA_PROVIDER}/${KMA_DATASET_KEY} 상세`,
    exact: true,
  });
  const latest = region
    .getByText("선택 범위 최근 종료 실행", { exact: true })
    .locator("..");
  await expect(latest.getByText("실패", { exact: true })).toHaveCount(1);
  const detailLink = latest.locator(
    `a[href="/ops/pipeline?execution=update_request:${requestId}"]`,
  );
  await expect(detailLink).toHaveCount(1);
  await detailLink.click();
  const detail = page.getByTestId("pipeline-execution-detail");
  await expect(detail).toContainText("KmaWeatherGridLimitExceeded");
}

function hasSha256Attestation(value: string | undefined): boolean {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

function requireCapGates(testInfo: TestInfo): number {
  const blocker = destructiveGateBlocker(testInfo);
  test.skip(blocker !== null, blocker ?? "");
  test.skip(
    process.env.E2E_KMA_GRID_CAP_FROM_RUNTIME !== "1",
    "host orchestrator가 prod web+daemon의 동일 runtime cap을 확인해 E2E_KMA_GRID_CAP_FROM_RUNTIME=1을 전달하지 않아 cap 시나리오 전체를 실행하지 않습니다.",
  );
  test.skip(
    !hasSha256Attestation(process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256) ||
      !hasSha256Attestation(process.env.E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256),
    "host orchestrator의 UI/API·WS origin hash attestation이 없어 cap 시나리오 전체를 실행하지 않습니다.",
  );
  test.skip(
    !process.env.E2E_C7_ORCHESTRATOR_STATE_FILE,
    "durable restore/residue state file을 소유한 host orchestrator가 없어 cap 시나리오 전체를 실행하지 않습니다.",
  );
  const cap = Number(process.env.E2E_KMA_GRID_CAP);
  if (!Number.isInteger(cap) || cap < 1 || cap > 500) {
    throw new Error("E2E_KMA_GRID_CAP은 runtime에서 읽은 1~500 정수여야 합니다.");
  }
  return cap;
}

function capCoordinate(index: number): { lat: number; lon: number } {
  // DFS cell보다 충분히 큰 간격을 사용하면서 최대 501개를 국내 bbox 안에 둔다.
  const columns = 30;
  return {
    lon: Number((126 + (index % columns) * 0.12).toFixed(6)),
    lat: Number((34 + Math.floor(index / columns) * 0.12).toFixed(6)),
  };
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

test.describe("C7 KMA grid cap destructive live E2E", () => {
  test("runtime cap+1은 exact error로 fail-closed하고 durable failure만 남긴다", async ({
    page,
  }, testInfo) => {
    const cap = requireCapGates(testInfo);
    test.setTimeout(CAP_TEST_TIMEOUT);
    testInfo.annotations.push({
      type: "destructive-load",
      description: `runtime KMA cap+1인 POI target ${cap + 1}개 생성`,
    });

    const externalSystem = `e2e-${RUN_ID}`;
    const syncScope = `external_system:${externalSystem}`;
    const state = createCleanupState("cap", RUN_ID);
    await bootstrapC7SameOriginPage(page, "/ops/pipeline");

    await withC7Cleanup(
      page,
      testInfo,
      state,
      async () => {
        // 대량 target 생성 전에 같은 API 경계의 create/read/delete를 먼저 증명한다.
        await runCreateDeleteCanary(
          page,
          state,
          { externalSystem, targetKey: `${RUN_ID}-canary` },
          buildPoiTargetBody(127.0276, 37.4979, {
            name: `C7 KMA cap canary ${RUN_ID}`,
            runId: RUN_ID,
          }),
        );

        const beforeResult = await getExactDatasetDetail(page, syncScope);
        expect([200, 404]).toContain(beforeResult.status);
        const before = scopeStateSnapshot(
          beforeResult.status === 200 ? beforeResult.body : null,
          syncScope,
        );

        const targets: TargetRef[] = Array.from(
          { length: cap + 1 },
          (_, index) => ({
            externalSystem,
            targetKey: `${RUN_ID}-grid-${String(index).padStart(3, "0")}`,
          }),
        );
        for (
          let offset = 0;
          offset < targets.length;
          offset += TARGET_CREATE_BATCH_SIZE
        ) {
          const batch = targets.slice(offset, offset + TARGET_CREATE_BATCH_SIZE);
          const settled = await Promise.allSettled(
            batch.map((target, batchIndex) => {
              const index = offset + batchIndex;
              const coordinate = capCoordinate(index);
              return putTrackedTarget(
                page,
                state,
                target,
                buildPoiTargetBody(coordinate.lon, coordinate.lat, {
                  name: `C7 KMA cap ${RUN_ID} ${index}`,
                  runId: RUN_ID,
                }),
              );
            }),
          );
          expect(settled.every((item) => item.status === "fulfilled")).toBe(true);
          for (const item of settled) {
            if (item.status !== "fulfilled") {
              throw new Error("cap target batch 생성 중 예외가 발생했습니다.");
            }
            expect(item.value.data.external_system).toBe(externalSystem);
          }
        }

        const created = await createCapRequestFromUi(
          page,
          syncScope,
          `C7 ${RUN_ID} runtime cap ${cap}`,
          state,
          targets,
        );

        const terminal = await waitForTerminal(
          page,
          created.data.request_id,
          undefined,
          state,
        );
        expect(terminal.data.execution.status).toBe("failed");
        assertKmaOnlyTerminalProviderScopes(terminal, { executed: "empty" });
        expect(terminal.data.execution.error_message).toContain(
          "KmaWeatherGridLimitExceeded",
        );
        const capPairs =
          terminal.data.execution.error_message?.match(
            /total=\d+, max_grids=\d+/g,
          ) ?? [];
        expect(capPairs).toEqual([
          `total=${cap + 1}, max_grids=${cap}`,
        ]);
        expect(
          terminal.data.events.some(
            (event) => event.code === "kma.target_scope_empty",
          ),
        ).toBe(false);
        const executed =
          terminal.data.update_request?.matched_scope.executed_provider_scopes;
        expect(
          executed === undefined ||
            (Array.isArray(executed) && executed.length === 0),
        ).toBe(true);
        await assertCapFailureFromUi(page, syncScope, created.data.request_id);

        const after = requireBody(
          await getExactDatasetDetail(page, syncScope),
          200,
        );
        const afterState = scopeStateSnapshot(after, syncScope);
        expect(afterState).not.toBeNull();
        state.scopeStateCount = 1;
        expect(afterState?.consecutiveFailures).toBe(
          (before?.consecutiveFailures ?? 0) + 1,
        );
        expect(afterState?.lastFailureAt).not.toBeNull();
        expect(afterState?.lastSuccessAt).toBe(before?.lastSuccessAt ?? null);
        expect(afterState?.cursor).toEqual(before?.cursor ?? {});
        expect(after.data.latest_execution?.id).toBe(created.data.request_id);
        expect(
          after.data.run_history.items.some(
            (item) =>
              item.id === created.data.request_id &&
              item.status === "failed" &&
              item.sync_scope === syncScope,
          ),
        ).toBe(true);
      },
      { terminalTimeout: CAP_CLEANUP_TERMINAL_TIMEOUT },
    );
  });
});
