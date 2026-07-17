import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "./client";
import {
  OPS_DATASET_LIVE_TOPICS,
  buildDatasetRefreshNowRequest,
  createDatasetRefreshNow,
  datasetRefreshExecutionQueryKey,
  datasetRefreshConflict,
  fetchOpsDataset,
  fetchDatasetRefreshExecution,
  hasActiveDatasetDetailExecution,
  hasActiveDatasetExecution,
  opsDatasetCatalogOptions,
  opsDatasetLiveBadgeLabel,
  previewOpsDataset,
  resolveDatasetRefreshScope,
  resolveOpsDatasetRefetchInterval,
  upsertOpsDatasetRefreshPolicy,
  type OpsDatasetGridRow,
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

describe("ops datasets current REST contract", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("canonical grid만 provider/dataset 입력 보조 목록으로 중복 없이 축약한다", () => {
    const row = (
      provider: string,
      datasetKey: string,
      catalogState: OpsDatasetGridRow["catalog_state"] = "canonical",
    ) =>
      ({
        provider,
        dataset_key: datasetKey,
        catalog_state: catalogState,
      }) as OpsDatasetGridRow;

    expect(
      opsDatasetCatalogOptions([
        row("z-provider", "dataset-b"),
        row("a-provider", "dataset-c"),
        row("a-provider", "dataset-a"),
        row("a-provider", "dataset-a"),
        row("legacy-provider", "orphan", "orphan"),
      ]),
    ).toEqual([
      { provider: "a-provider", datasets: ["dataset-a", "dataset-c"] },
      { provider: "z-provider", datasets: ["dataset-b"] },
    ]);
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
        "dataset_wide",
      ),
    ).toEqual({ allowed: true, syncScope: null });
    expect(
      resolveDatasetRefreshScope(
        TARGET_CAPABILITY,
        "external_system:concierge",
      ),
    ).toEqual({
      allowed: true,
      syncScope: "external_system:concierge",
    });
    expect(
      resolveDatasetRefreshScope(
        TARGET_CAPABILITY,
        "external_system:deleted",
      ),
    ).toMatchObject({ allowed: false });
  });

  it("누락되거나 모순된 capability는 fail-closed한다", () => {
    expect(
      resolveDatasetRefreshScope(null, "target_grids"),
    ).toMatchObject({ allowed: false });
    expect(
      resolveDatasetRefreshScope(
        { ...DATASET_WIDE_CAPABILITY, supported: true },
        "dataset_wide",
      ),
    ).toMatchObject({ allowed: false });
    expect(
      resolveDatasetRefreshScope(
        DATASET_WIDE_CAPABILITY,
        "stale_scope",
      ),
    ).toMatchObject({ allowed: false });
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
  function gridWithActiveExecution(active: boolean): OpsDatasetsGridResponse {
    return {
      data: {
        items: [
          {
            active_execution: active ? { status: "running" } : null,
          },
        ],
      },
    } as OpsDatasetsGridResponse;
  }

  it("서버가 exact scope active execution을 투영한 동안만 목록 polling을 유지한다", () => {
    expect(hasActiveDatasetExecution(gridWithActiveExecution(true))).toBe(true);
    expect(hasActiveDatasetExecution(gridWithActiveExecution(false))).toBe(false);
    expect(hasActiveDatasetExecution(undefined)).toBe(false);
  });

  it("서버가 선택 scope active execution을 투영한 동안만 상세 polling을 유지한다", () => {
    const detailWithActiveExecution = (active: boolean) =>
      ({
        data: {
          active_execution: active ? { status: "running" } : null,
        },
      }) as OpsDatasetDetailResponse;

    expect(hasActiveDatasetDetailExecution(detailWithActiveExecution(true))).toBe(
      true,
    );
    expect(hasActiveDatasetDetailExecution(detailWithActiveExecution(false))).toBe(
      false,
    );
    expect(hasActiveDatasetDetailExecution(undefined)).toBe(false);
  });

  it("live fallback에서는 비활성 grid·상세도 REST polling한다", () => {
    expect(resolveOpsDatasetRefetchInterval(true, false)).toBe(2_000);
    expect(resolveOpsDatasetRefetchInterval(true, true)).toBe(2_000);
    expect(resolveOpsDatasetRefetchInterval(false, true)).toBe(5_000);
    expect(resolveOpsDatasetRefetchInterval(false, false)).toBe(false);
  });
});

describe("ops datasets live invalidation adapter", () => {
  it("인증 거절은 일반 disabled와 구분해 로그인 필요로 표시한다", () => {
    expect(
      opsDatasetLiveBadgeLabel({
        state: "unauthorized",
        mode: "disabled",
      }),
    ).toBe("로그인 필요");
    expect(
      opsDatasetLiveBadgeLabel({ state: "disabled", mode: "disabled" }),
    ).toBe("자동 갱신 꺼짐");
  });

  it("projection을 바꾸는 global topic을 active cache 유무와 무관하게 구독한다", () => {
    expect(OPS_DATASET_LIVE_TOPICS).toEqual([
      "provider_sync",
      "dataset_projection",
      "import_jobs",
      "feature_update_requests",
      "dagster_runs",
      "dagster_schedules",
    ]);
    expect(resolveOpsDatasetRefetchInterval(false, false)).toBe(false);
  });

  it("연결 준비와 첫 재연결은 fallback badge를 성급하게 표시하지 않는다", () => {
    expect(
      opsDatasetLiveBadgeLabel({ state: "connecting", mode: "standby" }),
    ).toBe("연결 중");
    expect(
      opsDatasetLiveBadgeLabel({ state: "reconnecting", mode: "standby" }),
    ).toBe("재연결 중");
    expect(
      opsDatasetLiveBadgeLabel({ state: "polling", mode: "polling" }),
    ).toBe("REST 폴링 갱신");
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
