import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { __testing, opsLiveConnectionLabel } from "./live";

function seedQuery(queryClient: QueryClient, queryKey: QueryKey) {
  queryClient.setQueryData(queryKey, { ok: true });
  expect(queryClient.getQueryState(queryKey)?.isInvalidated).toBe(false);
}

describe("ops live invalidation", () => {
  it("인증 거절을 raw 상태값 대신 로그인 필요로 표시한다", () => {
    expect(opsLiveConnectionLabel("unauthorized")).toBe("로그인 필요");
    expect(opsLiveConnectionLabel("polling")).toBe("REST 폴링");
  });

  it("ticket 401만 로그인 만료로 분류하고 403 origin 오류는 재시도 경로로 보낸다", async () => {
    const abortController = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 401 }))
        .mockResolvedValueOnce(new Response(null, { status: 403 })),
    );

    await expect(
      __testing.fetchOpsLiveTicket(abortController.signal),
    ).rejects.toMatchObject({ unauthorized: true });
    await expect(
      __testing.fetchOpsLiveTicket(abortController.signal),
    ).rejects.toMatchObject({ unauthorized: false });

    vi.unstubAllGlobals();
  });

  it("import_job 단건 topic을 canonical pipeline/datasets cache에만 반영한다", () => {
    const queryClient = new QueryClient();
    const pipelineDetailKey = [
      "pipeline",
      "execution",
      "import_job",
      "job-1",
      {},
    ];
    const pipelineEventsKey = ["pipeline", "events", "live", {}];
    const datasetsKey = ["ops-datasets"];
    const legacyImportJobKey = ["import-job", "job-1"];

    seedQuery(queryClient, pipelineDetailKey);
    seedQuery(queryClient, pipelineEventsKey);
    seedQuery(queryClient, datasetsKey);
    seedQuery(queryClient, legacyImportJobKey);

    __testing.invalidateLiveTopic(queryClient, "import_job:job-1");

    expect(queryClient.getQueryState(pipelineDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineEventsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(legacyImportJobKey)?.isInvalidated).toBe(
      false,
    );
  });

  it("aggregate topic은 live 첫 페이지와 선택 상세만 갱신하고 paged 이력은 보존한다", () => {
    const queryClient = new QueryClient();
    const executionsLiveKey = ["pipeline", "executions", "live", {}];
    const executionsPagedKey = [
      "pipeline",
      "executions",
      "paged",
      {},
      "cursor-1",
    ];
    const eventsLiveKey = ["pipeline", "events", "live", {}];
    const eventsPagedKey = [
      "pipeline",
      "events",
      "paged",
      {},
      "cursor-1",
    ];
    const activeDetailKey = [
      "pipeline",
      "execution",
      "import_job",
      "job-active",
      {},
    ];

    for (const key of [
      executionsLiveKey,
      executionsPagedKey,
      eventsLiveKey,
      eventsPagedKey,
      activeDetailKey,
    ]) {
      seedQuery(queryClient, key);
    }

    __testing.invalidateLiveTopic(queryClient, "import_jobs");

    expect(queryClient.getQueryState(executionsLiveKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(eventsLiveKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(activeDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(executionsPagedKey)?.isInvalidated).toBe(
      false,
    );
    expect(queryClient.getQueryState(eventsPagedKey)?.isInvalidated).toBe(false);
  });

  it("WebSocket URL에 topic, ticket, server secret을 넣지 않는다", () => {
    const url = new URL(__testing.buildOpsLiveUrl(5_000));

    expect(url.pathname).toBe("/v1/ops/live");
    expect(url.searchParams.get("poll_interval_ms")).toBe("5000");
    expect(url.searchParams.has("topics")).toBe(false);
    expect(url.searchParams.has("ticket")).toBe(false);
    expect(url.toString()).not.toContain("secret");
  });

  it("연속 실패 3회부터 polling fallback으로 구분하고 backoff를 30초로 제한한다", () => {
    expect(__testing.connectionStateForFailureCount(1)).toBe("reconnecting");
    expect(__testing.connectionStateForFailureCount(2)).toBe("reconnecting");
    expect(__testing.connectionStateForFailureCount(3)).toBe("polling");
    expect(__testing.reconnectDelayMs(0)).toBe(1_000);
    expect(__testing.reconnectDelayMs(4)).toBe(30_000);
    expect(__testing.reconnectDelayMs(99)).toBe(30_000);
  });

  it("topic dependency를 canonical JSON 배열로 보존해 comma run id를 나누지 않는다", () => {
    const dependency = __testing.canonicalTopicDependency([
      "provider_sync",
      "dagster_run:opaque,run,id",
      "provider_sync",
    ]);

    expect(dependency).toBe(
      JSON.stringify(["dagster_run:opaque,run,id", "provider_sync"]),
    );
    expect(__testing.topicsFromDependency(dependency)).toEqual([
      "dagster_run:opaque,run,id",
      "provider_sync",
    ]);
  });

  it("비 BMP topic도 wire 정렬 순서와 무관하게 exact set ack로 확인한다", () => {
    const requested = ["dagster_run:\uE000", "dagster_run:\u{10000}"];
    const serverOrder = [...requested].reverse();

    expect(__testing.messageTopicsMatch(serverOrder, requested)).toBe(true);
    expect(
      __testing.messageTopicsMatch(
        [requested[0], requested[0]],
        requested,
      ),
    ).toBe(false);
  });

  it("server frame sequence는 safe integer 범위에서만 단조 증가한다", () => {
    const frame = {
      type: "snapshot",
      version: 1,
      sequence: 2,
      sent_at: "2026-07-17T12:00:00.000Z",
    };

    expect(__testing.serverFrameSequence(frame, 1)).toBe(2);
    expect(
      __testing.serverFrameSequence({ ...frame, sequence: 1 }, 1),
    ).toBeNull();
    expect(
      __testing.serverFrameSequence(
        { ...frame, sequence: Number.MAX_SAFE_INTEGER + 1 },
        1,
      ),
    ).toBeNull();
  });

  it("operation/provider/schedule/run event를 page 비종속 adapter로 라우팅한다", () => {
    const queryClient = new QueryClient();
    const invalidateOperation = vi.fn();
    const invalidateProviderDataset = vi.fn();
    const invalidateDagsterRun = vi.fn();
    const invalidateSchedule = vi.fn();
    const adapter = {
      invalidateOperation,
      invalidateProviderDataset,
      invalidateDagsterRun,
      invalidateSchedule,
    };

    __testing.invalidateLiveTopic(
      queryClient,
      "feature_update_requests",
      adapter,
    );
    __testing.invalidateLiveTopic(queryClient, "import_jobs", adapter);
    __testing.invalidateLiveTopic(queryClient, "provider_sync", adapter);
    __testing.invalidateLiveTopic(queryClient, "dataset_projection", adapter);
    __testing.invalidateLiveTopic(queryClient, "dagster_runs", adapter);
    __testing.invalidateLiveTopic(queryClient, "dagster_schedules", adapter);

    expect(invalidateOperation).toHaveBeenCalledTimes(3);
    expect(invalidateProviderDataset).toHaveBeenCalledTimes(3);
    expect(invalidateDagsterRun).toHaveBeenCalledTimes(1);
    expect(invalidateSchedule).toHaveBeenCalledTimes(1);
    expect(invalidateProviderDataset).toHaveBeenCalledWith(
      queryClient,
      { kind: "provider_dataset", topic: "provider_sync" },
    );
    expect(invalidateProviderDataset).toHaveBeenCalledWith(
      queryClient,
      { kind: "provider_dataset", topic: "dataset_projection" },
    );
    expect(invalidateOperation).toHaveBeenCalledWith(queryClient, {
      kind: "operation",
      topic: "import_jobs",
    });
  });

  it("feature_update_requests topic이 feature 지도/상세/admin 목록을 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];
    const adminFeaturesKey = ["admin-features", { page_size: 50 }];
    const pipelineOverviewKey = ["pipeline", "overview", 20];
    const pipelineExecutionsKey = ["pipeline", "executions", "live", {}];
    const datasetsKey = ["ops-datasets"];
    const datasetDetailKey = [
      "ops-dataset",
      "python-kma-api",
      "kma_vilage_fcst",
      "target_grids",
    ];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);
    seedQuery(queryClient, adminFeaturesKey);
    seedQuery(queryClient, pipelineOverviewKey);
    seedQuery(queryClient, pipelineExecutionsKey);
    seedQuery(queryClient, datasetsKey);
    seedQuery(queryClient, datasetDetailKey);

    __testing.invalidateLiveTopic(queryClient, "feature_update_requests");

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(adminFeaturesKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineOverviewKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(pipelineExecutionsKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetDetailKey)?.isInvalidated).toBe(true);
  });

  it("feature_update_request 단건 topic도 feature surface를 갱신 대상으로 만든다", () => {
    const queryClient = new QueryClient();
    const featureMapKey = ["features", "viewport", "6/54/24", "", "summary", 500];
    const featureDetailKey = ["feature", "f_1111011100_p_mock"];
    const pipelineDetailKey = [
      "pipeline",
      "execution",
      "update_request",
      "request-1",
      {},
    ];
    const datasetDetailKey = [
      "ops-dataset",
      "python-kma-api",
      "kma_vilage_fcst",
      "target_grids",
    ];

    seedQuery(queryClient, featureMapKey);
    seedQuery(queryClient, featureDetailKey);
    seedQuery(queryClient, pipelineDetailKey);
    seedQuery(queryClient, datasetDetailKey);

    __testing.invalidateLiveTopic(
      queryClient,
      "feature_update_request:request-1",
    );

    expect(queryClient.getQueryState(featureMapKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(featureDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(pipelineDetailKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(datasetDetailKey)?.isInvalidated).toBe(true);
  });

  it("Dagster run 단건 topic이 pipeline run 상세·목록과 datasets를 무효화한다", () => {
    const queryClient = new QueryClient();
    const runDetailKey = ["pipeline", "dagster-run", "run-1", {}];
    const runListKey = ["pipeline", "dagster-runs", 20];
    const schedulesKey = ["pipeline", "schedules"];
    const datasetsKey = ["ops-datasets"];

    seedQuery(queryClient, runDetailKey);
    seedQuery(queryClient, runListKey);
    seedQuery(queryClient, schedulesKey);
    seedQuery(queryClient, datasetsKey);

    __testing.invalidateLiveTopic(queryClient, "dagster_run:run-1");

    expect(queryClient.getQueryState(runDetailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(runListKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(schedulesKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
  });

  it("Dagster aggregate topic도 선택 run 상세를 무효화한다", () => {
    const queryClient = new QueryClient();
    const runDetailKey = ["pipeline", "dagster-run", "run-active", {}];

    seedQuery(queryClient, runDetailKey);
    __testing.invalidateLiveTopic(queryClient, "dagster_runs");

    expect(queryClient.getQueryState(runDetailKey)?.isInvalidated).toBe(true);
  });

  it("provider/dataset projection과 Dagster schedule topic이 canonical 운영 query를 무효화한다", () => {
    const queryClient = new QueryClient();
    const datasetsKey = ["ops-datasets"];
    const datasetDetailKey = [
      "ops-dataset",
      "python-kma-api",
      "forecast",
      "target_grids",
    ];
    const schedulesKey = ["pipeline", "schedules"];
    const overviewKey = ["pipeline", "overview", 10];

    for (const key of [
      datasetsKey,
      datasetDetailKey,
      schedulesKey,
      overviewKey,
    ]) {
      seedQuery(queryClient, key);
    }

    __testing.invalidateLiveTopic(queryClient, "provider_sync");
    __testing.invalidateLiveTopic(queryClient, "dataset_projection");
    __testing.invalidateLiveTopic(queryClient, "dagster_schedules");

    expect(queryClient.getQueryState(datasetsKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(datasetDetailKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryState(schedulesKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(true);
  });
});
