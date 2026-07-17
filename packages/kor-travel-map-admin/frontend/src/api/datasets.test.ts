import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "./client";
import {
  buildDatasetRefreshNowRequest,
  createDatasetRefreshNow,
  datasetRefreshExecutionQueryKey,
  datasetRefreshConflict,
  fetchOpsDataset,
  fetchDatasetRefreshExecution,
  filterDatasetRecentRuns,
  hasActiveDatasetDetailExecution,
  hasActiveDatasetExecution,
  previewOpsDataset,
  resolveDatasetRefreshScope,
  upsertOpsDatasetRefreshPolicy,
  type OpsDatasetLatestExecution,
  type OpsDatasetDetailResponse,
  type OpsDatasetScopeRefreshCapability,
  type OpsDatasetsGridResponse,
  type ProviderRefreshPolicyUpsertRequest,
} from "./datasets";

type FetchMock = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function stubFetch() {
  const fetchMock = vi.fn<FetchMock>(() =>
    Promise.resolve(
      new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const DATASET_WIDE_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "dataset_wide",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: [],
  reason: "전체 dataset 단위 갱신",
};

const TARGET_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: true,
  selector: "poi_cache_targets",
  effect: "sync_scope",
  default_sync_scope: "target_grids",
  allowed_sync_scopes: ["target_grids", "external_system:concierge"],
  reason: null,
};

function execution(syncScope: string | null): OpsDatasetLatestExecution {
  return { id: syncScope ?? "unscoped", sync_scope: syncScope } as OpsDatasetLatestExecution;
}

describe("ops datasets current REST contract", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("detail/preview/refresh-policy가 고정 경로와 query 식별자를 사용한다", async () => {
    const fetchMock = stubFetch();

    await fetchOpsDataset("kma grid", "short term", "external_system:concierge");
    await previewOpsDataset("kma grid", "short term", {
      source: "fixture",
      max_items: 3,
    });
    await upsertOpsDatasetRefreshPolicy(
      "kma grid",
      "short term",
      {} as ProviderRefreshPolicyUpsertRequest,
    );

    expect(fetchMock.mock.calls.map(([input]) => input)).toEqual([
      "/api/proxy/v1/ops/datasets/detail?provider=kma+grid&dataset_key=short+term&sync_scope=external_system%3Aconcierge",
      "/api/proxy/v1/ops/datasets/preview?provider=kma+grid&dataset_key=short+term",
      "/api/proxy/v1/ops/datasets/refresh-policy?provider=kma+grid&dataset_key=short+term",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method)).toEqual([
      "GET",
      "POST",
      "PUT",
    ]);
  });

  it("지금 갱신 body는 중복 filter 없이 run_mode=now를 고정한다", () => {
    expect(
      buildDatasetRefreshNowRequest({
        provider: "kma",
        datasetKey: "short_term",
        syncScope: "external_system:concierge",
      }),
    ).toEqual({
      scope: {
        type: "provider_dataset",
        provider: "kma",
        dataset_key: "short_term",
        sync_scope: "external_system:concierge",
      },
      run_mode: "now",
      priority: 75,
      reason: "dataset refresh from ops/datasets",
    });
    expect(
      buildDatasetRefreshNowRequest({
        provider: "tourapi",
        datasetKey: "area_based_list",
        syncScope: null,
      }),
    ).toEqual({
      scope: {
        type: "provider_dataset",
        provider: "tourapi",
        dataset_key: "area_based_list",
      },
      run_mode: "now",
      priority: 75,
      reason: "dataset refresh from ops/datasets",
    });
  });

  it("생성 응답의 active request 재사용 판별자를 변형 없이 보존한다", async () => {
    const response = {
      data: { request_id: "request-1" },
      meta: {},
      idempotent_replay: false,
      reused_active_request: true,
    };
    const fetchMock = vi.fn<FetchMock>(() =>
      Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createDatasetRefreshNow({
        provider: "kma",
        datasetKey: "short_term",
        syncScope: "target_grids",
      }),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/proxy/v1/ops/pipeline/requests",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(
          buildDatasetRefreshNowRequest({
            provider: "kma",
            datasetKey: "short_term",
            syncScope: "target_grids",
          }),
        ),
      }),
    );
  });

  it("실행 상태 조회는 typed query builder와 encoded id를 사용한다", async () => {
    const fetchMock = stubFetch();

    await fetchDatasetRefreshExecution("request/id ?");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/proxy/v1/ops/pipeline/executions/update_request/request%2Fid%20%3F?page_size=1",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("ops datasets scope capability", () => {
  it("dataset-wide는 nullable scope로 정규화하고 target scope는 allow-list만 허용한다", () => {
    expect(
      resolveDatasetRefreshScope(
        DATASET_WIDE_CAPABILITY,
        "default",
        "default",
      ),
    ).toEqual({ allowed: true, syncScope: null });
    expect(
      resolveDatasetRefreshScope(
        TARGET_CAPABILITY,
        "external_system:concierge",
        "target_grids",
      ),
    ).toEqual({
      allowed: true,
      syncScope: "external_system:concierge",
    });
    expect(
      resolveDatasetRefreshScope(
        TARGET_CAPABILITY,
        "external_system:deleted",
        "target_grids",
      ),
    ).toMatchObject({ allowed: false });
  });

  it("누락되거나 모순된 capability는 fail-closed한다", () => {
    expect(
      resolveDatasetRefreshScope(null, "target_grids", "target_grids"),
    ).toMatchObject({ allowed: false });
    expect(
      resolveDatasetRefreshScope(
        { ...DATASET_WIDE_CAPABILITY, supported: true },
        "default",
        "default",
      ),
    ).toMatchObject({ allowed: false });
    expect(
      resolveDatasetRefreshScope(
        DATASET_WIDE_CAPABILITY,
        "stale_scope",
        "default",
      ),
    ).toMatchObject({ allowed: false });
  });

  it("최근 실행은 선택 scope만 남기고 dataset-wide에는 unscoped fallback을 포함한다", () => {
    const runs = [
      execution("target_grids"),
      execution("external_system:concierge"),
      execution("external_system:other"),
      execution("default"),
      execution("dataset_wide"),
      execution(null),
    ];

    expect(
      filterDatasetRecentRuns(
        runs,
        "external_system:concierge",
        TARGET_CAPABILITY,
        "target_grids",
      ).map((run) => run.sync_scope),
    ).toEqual(["external_system:concierge"]);
    expect(
      filterDatasetRecentRuns(
        runs,
        "default",
        DATASET_WIDE_CAPABILITY,
        "default",
      ).map((run) => run.sync_scope),
    ).toEqual(["default", "dataset_wide", null]);
  });

  it("mutation allow-list에서 빠진 stale scope와 orphan scope의 이력을 숨기지 않는다", () => {
    const runs = [
      execution("target_grids"),
      execution("external_system:deleted"),
      execution("orphan_scope"),
    ];

    expect(
      filterDatasetRecentRuns(
        runs,
        "external_system:deleted",
        TARGET_CAPABILITY,
        "target_grids",
      ).map((run) => run.sync_scope),
    ).toEqual(["external_system:deleted"]);
    expect(
      filterDatasetRecentRuns(runs, "orphan_scope", null, undefined).map(
        (run) => run.sync_scope,
      ),
    ).toEqual(["orphan_scope"]);
    expect(
      filterDatasetRecentRuns(
        [execution("default"), execution("dataset_wide"), execution(null)],
        "default",
        null,
        undefined,
      ).map((run) => run.sync_scope),
    ).toEqual(["default", "dataset_wide", null]);
  });
});

describe("dataset refresh status query identity", () => {
  it("갱신 상태가 canonical pipeline execution detail key를 사용한다", async () => {
    const queryClient = new QueryClient();
    const requestId = "request-1";
    const pipelineKey = datasetRefreshExecutionQueryKey(requestId);
    const pipelineShape = {
      data: { execution: { id: requestId, kind: "update_request", status: "running" } },
    };
    queryClient.setQueryData(pipelineKey, pipelineShape);

    expect(pipelineKey).toEqual([
      "pipeline",
      "execution",
      "update_request",
      requestId,
      { page_size: 1 },
    ]);
    expect(queryClient.getQueryData(pipelineKey)).toBe(pipelineShape);

    await queryClient.invalidateQueries({
      queryKey: ["pipeline", "execution", "update_request", requestId],
    });

    expect(queryClient.getQueryState(pipelineKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryData(pipelineKey)).toBe(pipelineShape);
  });
});

describe("ops datasets active polling gate", () => {
  function responseWithStatuses(
    status: OpsDatasetLatestExecution["status"],
    pairStatus: OpsDatasetLatestExecution["pair_status"],
  ): OpsDatasetsGridResponse {
    return {
      data: {
        items: [
          {
            latest_execution: { status, pair_status: pairStatus },
          },
        ],
      },
    } as OpsDatasetsGridResponse;
  }

  it("root 또는 pair가 active인 동안만 목록 polling을 유지한다", () => {
    expect(hasActiveDatasetExecution(responseWithStatuses("running", "done"))).toBe(
      true,
    );
    expect(hasActiveDatasetExecution(responseWithStatuses("done", "queued"))).toBe(
      true,
    );
    expect(hasActiveDatasetExecution(responseWithStatuses("done", "done"))).toBe(
      false,
    );
    expect(hasActiveDatasetExecution(undefined)).toBe(false);
  });

  it("선택 scope 상세의 root 또는 pair가 active인 동안만 상세 polling을 유지한다", () => {
    const detailWithStatuses = (
      status: OpsDatasetLatestExecution["status"],
      pairStatus: OpsDatasetLatestExecution["pair_status"],
    ) =>
      ({
        data: {
          recent_runs: [{ status, pair_status: pairStatus }],
        },
      }) as OpsDatasetDetailResponse;

    expect(
      hasActiveDatasetDetailExecution(detailWithStatuses("running", "done")),
    ).toBe(true);
    expect(
      hasActiveDatasetDetailExecution(detailWithStatuses("done", "queued")),
    ).toBe(true);
    expect(
      hasActiveDatasetDetailExecution(detailWithStatuses("done", "done")),
    ).toBe(false);
    expect(hasActiveDatasetDetailExecution(undefined)).toBe(false);
  });
});

describe("ops datasets refresh conflict", () => {
  it("409 ProblemDetail의 기존 request 정보를 typed 값으로 보존한다", () => {
    const error = new ApiClientError("conflict", 409, "/v1/ops/pipeline/requests", {
      code: "ACTIVE_SCOPE_CONFLICT",
      detail: "다른 계획의 활성 요청이 있습니다.",
      request_id: "trace-1",
      status: 409,
      title: "Conflict",
      type: "https://kor-travel-map/errors/active-scope-conflict",
      details: {
        request_id: "request-1",
        status: "running",
        detail_url: "/v1/ops/pipeline/executions/update_request/request-1",
      },
    });

    expect(datasetRefreshConflict(error)).toEqual({
      code: "ACTIVE_SCOPE_CONFLICT",
      requestId: "request-1",
      status: "running",
      detailUrl: "/v1/ops/pipeline/executions/update_request/request-1",
    });
  });

  it("request_id가 없는 409와 409가 아닌 오류는 기존 요청으로 오인하지 않는다", () => {
    expect(
      datasetRefreshConflict(
        new ApiClientError("lock busy", 409, "/v1/ops/pipeline/requests"),
      ),
    ).toBeNull();
    expect(
      datasetRefreshConflict(
        new ApiClientError("validation", 422, "/v1/ops/pipeline/requests"),
      ),
    ).toBeNull();
  });

  it("request_id가 있어도 허용하지 않은 409 code는 충돌 링크로 오인하지 않는다", () => {
    const error = new ApiClientError("conflict", 409, "/v1/ops/pipeline/requests", {
      code: "SOME_OTHER_CONFLICT",
      detail: "다른 충돌",
      request_id: "trace-1",
      status: 409,
      title: "Conflict",
      type: "https://kor-travel-map/errors/some-other-conflict",
      details: { request_id: "request-1" },
    });

    expect(datasetRefreshConflict(error)).toBeNull();
  });
});
