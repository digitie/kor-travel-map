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
  opsDatasetScopeEffectSentence,
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

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

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

/**
 * 서버가 "제출할 수 있는 sync scope가 없다"고 판정한 dataset의 payload.
 *
 * `ops_dataset_service._scope_refresh_capability`의 `not is_refreshable` 분기가
 * 내는 값과 같다(enabled refresh operation은 있는데 `provider_dataset_operation_scopes`
 * 행이 0개인 상태 — 스키마가 허용한다).
 */
const NO_SUBMITTABLE_SCOPE_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "none",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: [],
  reason: "이 dataset의 refresh operation에 sync scope 선언이 없어 걸 대상이 없습니다.",
};

/**
 * 같은 판정이지만 **선언된 scope 목록이 비어 있지 않은** 경우.
 *
 * 서버의 `not is_refreshable` 분기가 잔존 선언을 그대로 실어 내는 모양이다 — 비활성
 * dataset이나 실행 가능한 refresh runner가 없는 dataset이 여기 해당한다. 목록이 비지
 * 않았다고 제출 가능해지지는 않는다는 것이 이 fixture가 지키는 축이다.
 *
 * (`external_system:*`만 선언한 **활성** dataset은 이 모양이 아니다 — 그쪽은
 * `effect="sync_scope"` + `selector="none"`으로 내려오고 제출할 수 있다. 그 축은
 * 아래 "POI target selector가 없어도 …" 케이스가 따로 본다.)
 */
const EXTERNAL_ONLY_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "none",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: ["external_system:pinvi"],
  reason: "이 dataset에는 실행 가능한 refresh runner가 없습니다.",
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

  it("detail/preview는 exact triple, refresh-policy는 canonical dataset ID만 사용한다", async () => {
    const fetchMock = stubFetch();

    await fetchOpsDataset(
      101,
      "external_system:concierge",
      "refresh_targeted",
    );
    await previewOpsDataset(101, "external_system:concierge", "refresh_targeted", {
      source: "fixture",
      max_items: 3,
    });
    await upsertOpsDatasetRefreshPolicy(
      101,
      {} as ProviderRefreshPolicyUpsertRequest,
    );

    expect(fetchMock.mock.calls.map(([input]) => input)).toEqual([
      "/api/proxy/v1/ops/datasets/101?sync_scope=external_system%3Aconcierge&operation_key=refresh_targeted",
      "/api/proxy/v1/ops/datasets/101/preview?sync_scope=external_system%3Aconcierge&operation_key=refresh_targeted",
      "/api/proxy/v1/ops/datasets/refresh-policy?provider_dataset_id=101",
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
        providerDatasetId: 101,
        syncScope: "external_system:concierge",
        operationKey: "refresh_targeted",
      }),
    ).toEqual({
      scope: {
        type: "provider_dataset",
        provider_dataset_id: 101,
        sync_scope: "external_system:concierge",
        operation_key: "refresh_targeted",
      },
      run_mode: "now",
      priority: 75,
      reason: "dataset refresh from ops/datasets",
    });
    expect(
      buildDatasetRefreshNowRequest({
        providerDatasetId: 202,
        syncScope: "dataset_wide",
        operationKey: "refresh_full",
      }),
    ).toEqual({
      scope: {
        type: "provider_dataset",
        provider_dataset_id: 202,
        sync_scope: "dataset_wide",
        operation_key: "refresh_full",
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
        providerDatasetId: 101,
        syncScope: "target_grids",
        operationKey: "refresh_targeted",
      }),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/proxy/v1/ops/pipeline/requests",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(
          buildDatasetRefreshNowRequest({
          providerDatasetId: 101,
          syncScope: "target_grids",
          operationKey: "refresh_targeted",
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
  it("dataset-wide와 target scope 모두 canonical scope를 명시한다", () => {
    expect(
      resolveDatasetRefreshScope(DATASET_WIDE_CAPABILITY, "dataset_wide"),
    ).toEqual({ allowed: true, syncScope: "dataset_wide" });
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
      resolveDatasetRefreshScope(TARGET_CAPABILITY, "external_system:deleted"),
    ).toMatchObject({ allowed: false });
  });
  it("POI target selector가 없어도 선언된 scope는 제출할 수 있다", () => {
    // `target_grids`를 선언하지 않은 dataset — 서버는 `selector:"none"`을 낸다
    // (`api/ops_dataset_service.py::_scope_refresh_capability`: selector는 "scope 안의
    // **대상**을 무엇이 고르는가"이고, POI target 목록은 `target_grids`에만 있다).
    // 앞 판은 이 게이트가 `selector === "poi_cache_targets"`를 요구해서, scope는 고를 수
    // 있는데 POI selector만 없는 dataset을 "선택 scope 갱신을 지원하지 않습니다"로 막았다.
    const externalOnly: OpsDatasetScopeRefreshCapability = {
      supported: true,
      selector: "none",
      effect: "sync_scope",
      default_sync_scope: "external_system:pinvi",
      allowed_sync_scopes: ["external_system:pinvi"],
      reason: null,
    };

    expect(
      resolveDatasetRefreshScope(externalOnly, "external_system:pinvi"),
    ).toEqual({ allowed: true, syncScope: "external_system:pinvi" });
    // 선언 밖 scope는 여전히 막고, 사유는 POI target이 아니라 **카탈로그 선언**을 든다.
    expect(
      resolveDatasetRefreshScope(externalOnly, "target_grids"),
    ).toEqual({
      allowed: false,
      reason: "카탈로그가 선언하지 않은 sync scope입니다.",
    });
  });
  it("누락되거나 모순된 capability는 fail-closed한다", () => {
    expect(resolveDatasetRefreshScope(null, "target_grids")).toMatchObject({
      allowed: false,
    });
    expect(
      resolveDatasetRefreshScope(
        { ...DATASET_WIDE_CAPABILITY, supported: true },
        "dataset_wide",
      ),
    ).toMatchObject({ allowed: false });
    expect(
      resolveDatasetRefreshScope(DATASET_WIDE_CAPABILITY, "stale_scope"),
    ).toMatchObject({ allowed: false });
  });
  it("제출 가능한 scope가 없는 dataset은 갱신을 허용하지 않는다", () => {
    // 반환값 전체를 단언한다 — `reason` 문자열이 어딘가에 존재하는지가 아니라,
    // **이 함수가 무엇을 돌려주는지**가 버튼 활성화를 결정한다.
    expect(
      resolveDatasetRefreshScope(NO_SUBMITTABLE_SCOPE_CAPABILITY, "dataset_wide"),
    ).toEqual({
      allowed: false,
      reason: NO_SUBMITTABLE_SCOPE_CAPABILITY.reason,
    });
    expect(
      resolveDatasetRefreshScope(EXTERNAL_ONLY_CAPABILITY, "external_system:pinvi"),
    ).toEqual({ allowed: false, reason: EXTERNAL_ONLY_CAPABILITY.reason });
    // scope를 무엇으로 고르든 결과가 같다 — 고를 수 있는 것이 없기 때문이다.
    expect(
      resolveDatasetRefreshScope(NO_SUBMITTABLE_SCOPE_CAPABILITY, "target_grids"),
    ).toMatchObject({ allowed: false });
    // `supported: true`가 함께 와도 fail-closed다(모순 payload).
    expect(
      resolveDatasetRefreshScope(
        { ...NO_SUBMITTABLE_SCOPE_CAPABILITY, supported: true },
        "dataset_wide",
      ),
    ).toMatchObject({ allowed: false });
    // reason이 없으면 이 함수가 사유를 채운다 — 화면이 사유 없는 비활성 버튼을
    // 보이지 않게 한다.
    expect(
      resolveDatasetRefreshScope(
        { ...NO_SUBMITTABLE_SCOPE_CAPABILITY, reason: null },
        "dataset_wide",
      ),
    ).toEqual({
      allowed: false,
      reason: "이 dataset에 걸 수 있는 갱신 범위가 없습니다.",
    });
  });
  it("effect 축이 없으면 갱신 불가 상태를 구분할 수단이 없다", () => {
    // `effect`를 뺀 나머지 필드는 정상 dataset-wide 계약과 **완전히 같다**. 서버가
    // `is_refreshable=false`만 내려도 이 함수는 그것을 읽지 않으므로 허용으로
    // 판정한다 — 아래가 그 사실의 실측이고, `effect: "none"`을 계약에 넣은 이유다.
    const withoutEffectAxis: OpsDatasetScopeRefreshCapability = {
      ...NO_SUBMITTABLE_SCOPE_CAPABILITY,
      effect: "dataset_wide",
    };
    expect(resolveDatasetRefreshScope(withoutEffectAxis, "dataset_wide")).toEqual({
      allowed: true,
      syncScope: "dataset_wide",
    });
    // 이 함수가 허용 판정에 읽는 필드는 `effect`를 빼면 네 개다. 두 상태가 그 네 개를
    // 모두 같은 값으로 낸다는 것이 위 판정의 원인이다.
    const gateInputsWithoutEffect = (
      capability: OpsDatasetScopeRefreshCapability,
    ) => ({
      supported: capability.supported,
      selector: capability.selector,
      default_sync_scope: capability.default_sync_scope,
      allowed_sync_scopes: capability.allowed_sync_scopes,
    });
    expect(gateInputsWithoutEffect(NO_SUBMITTABLE_SCOPE_CAPABILITY)).toEqual(
      gateInputsWithoutEffect(DATASET_WIDE_CAPABILITY),
    );
  });
});

describe("ops datasets scope contract sentence", () => {
  // 이 문장은 `/ops/datasets` 상세의 "범위 계약" 줄에 `·`로 이어 붙는다
  // (`datasets-client.tsx`의 `RefreshNowSection`). 판정 축(`resolveDatasetRefreshScope`)에는
  // 회귀가 있었지만 **표시 문자열 축에는 없었고**, 그 사각에서 `effect: "none"`이
  // "dataset 전체"로 그려졌다.
  it("effect 세 값을 각각 다른 문장으로 그린다", () => {
    expect(opsDatasetScopeEffectSentence("sync_scope")).toBe(
      "효과 선택 scope 갱신",
    );
    expect(opsDatasetScopeEffectSentence("dataset_wide")).toBe(
      "효과 dataset 전체 갱신",
    );
    expect(opsDatasetScopeEffectSentence("none")).toBe(
      "효과 없음(제출 가능한 갱신 범위 없음)",
    );
    const sentences = (
      ["sync_scope", "dataset_wide", "none"] as const
    ).map((effect) => opsDatasetScopeEffectSentence(effect));
    expect(new Set(sentences).size).toBe(sentences.length);
  });

  it("차단된 계약은 실행 가능한 계약과 같은 문장을 쓰지 않는다", () => {
    // 한 패널이 이 문장과 `resolveDatasetRefreshScope`의 차단 사유를 **동시에** 그린다.
    // 두 문장이 반대되면(효과 "dataset 전체" + 사유 "걸 대상이 없습니다") 운영자는
    // 어느 쪽을 믿을지 알 수 없다.
    const executableSentences = [
      DATASET_WIDE_CAPABILITY,
      TARGET_CAPABILITY,
    ].map((capability) => opsDatasetScopeEffectSentence(capability.effect));

    for (const capability of [
      NO_SUBMITTABLE_SCOPE_CAPABILITY,
      EXTERNAL_ONLY_CAPABILITY,
    ]) {
      expect(
        resolveDatasetRefreshScope(capability, capability.default_sync_scope)
          .allowed,
      ).toBe(false);
      expect(executableSentences).not.toContain(
        opsDatasetScopeEffectSentence(capability.effect),
      );
    }
  });
});

describe("dataset refresh status query identity", () => {
  it("갱신 상태가 canonical pipeline execution detail key를 사용한다", async () => {
    const queryClient = new QueryClient();
    const requestId = "request-1";
    const pipelineKey = datasetRefreshExecutionQueryKey(requestId);
    const pipelineShape = {
      data: {
        execution: { id: requestId, kind: "update_request", status: "running" },
      },
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
    expect(hasActiveDatasetExecution(gridWithActiveExecution(false))).toBe(
      false,
    );
    expect(hasActiveDatasetExecution(undefined)).toBe(false);
  });

  it("서버가 선택 scope active execution을 투영한 동안만 상세 polling을 유지한다", () => {
    const detailWithActiveExecution = (active: boolean) =>
      ({
        data: {
          active_execution: active ? { status: "running" } : null,
        },
      }) as OpsDatasetDetailResponse;

    expect(
      hasActiveDatasetDetailExecution(detailWithActiveExecution(true)),
    ).toBe(true);
    expect(
      hasActiveDatasetDetailExecution(detailWithActiveExecution(false)),
    ).toBe(false);
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
    const error = new ApiClientError(
      "conflict",
      409,
      "/v1/ops/pipeline/requests",
      {
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
      },
    );

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
    const error = new ApiClientError(
      "conflict",
      409,
      "/v1/ops/pipeline/requests",
      {
        code: "SOME_OTHER_CONFLICT",
        detail: "다른 충돌",
        request_id: "trace-1",
        status: 409,
        title: "Conflict",
        type: "https://kor-travel-map/errors/some-other-conflict",
        details: { request_id: "request-1" },
      },
    );

    expect(datasetRefreshConflict(error)).toBeNull();
  });
});
