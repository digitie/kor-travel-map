import { expect, test } from "@playwright/test";

import {
  cancellationCandidateForScenarioOwnedActiveRequest,
  hasExactC7RequestOwnershipBinding,
  isC7OrchestratorBootstrapPlaceholder,
  type FeatureUpdateRequestCreateRequest,
  KMA_DATASET_KEY,
  KMA_NOWCAST_OPERATION_KEY,
  KMA_PROVIDER,
  type KmaRequestOwnership,
  type OpsDatasetDetailResponse,
  type PipelineExecutionDetailResponse,
} from "./live/_ops-c7-admin-api";

const OWNED_REQUEST_ID = "11111111-1111-4111-8111-111111111111";
const FOREIGN_REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const IDEMPOTENCY_KEY = "33333333-3333-4333-8333-333333333333";
const PROVIDER_DATASET_ID = 42;
const SYNC_SCOPE = "external_system:c7-cleanup-ownership";

function datasetDetail(requestId: string): OpsDatasetDetailResponse {
  return {
    data: {
      active_execution: {
        id: requestId,
        kind: "update_request",
        operation_key: KMA_NOWCAST_OPERATION_KEY,
        provider_datasets: [
          {
            dataset_key: KMA_DATASET_KEY,
            provider: KMA_PROVIDER,
            provider_dataset_id: PROVIDER_DATASET_ID,
            sync_scope: SYNC_SCOPE,
          },
        ],
        sync_scope: SYNC_SCOPE,
      },
      dataset_key: KMA_DATASET_KEY,
      provider: KMA_PROVIDER,
      scopes: [{ sync_scope: SYNC_SCOPE }],
    },
  } as OpsDatasetDetailResponse;
}

function requestDetail(requestId: string): PipelineExecutionDetailResponse {
  return {
    data: {
      execution: { id: requestId, kind: "update_request" },
      update_request: {
        dataset_memberships: [
          {
            operation_key: KMA_NOWCAST_OPERATION_KEY,
            provider_dataset_id: PROVIDER_DATASET_ID,
            sync_scope: SYNC_SCOPE,
          },
        ],
        request_id: requestId,
        scope: {
          operation_key: KMA_NOWCAST_OPERATION_KEY,
          provider_dataset_id: PROVIDER_DATASET_ID,
          sync_scope: SYNC_SCOPE,
          type: "provider_dataset",
        },
      },
    },
  } as PipelineExecutionDetailResponse;
}

const ownership: KmaRequestOwnership = {
  idempotencyKey: IDEMPOTENCY_KEY,
  operationKey: KMA_NOWCAST_OPERATION_KEY,
  providerDatasetId: PROVIDER_DATASET_ID,
  syncScope: SYNC_SCOPE,
};
const idempotencyEntry: {
  body: FeatureUpdateRequestCreateRequest;
  requestId: string;
} = {
  // 이 unit fixture는 browser bootstrap을 거치지 않는다. canonical live helper를
  // 호출하지 않고 검증 대상인 KMA triple을 body에 명시한다.
  body: {
    priority: 50,
    reason: "C7 cleanup ownership regression",
    run_mode: "queued",
    scope: {
      operation_key: KMA_NOWCAST_OPERATION_KEY,
      provider_dataset_id: PROVIDER_DATASET_ID,
      sync_scope: SYNC_SCOPE,
      type: "provider_dataset",
    },
  },
  requestId: OWNED_REQUEST_ID,
};

function durableV4Journal(): object {
  return {
    cleanup_result: null,
    completed_scenarios: [],
    external_systems: [],
    idempotency_entries: [
      {
        body: idempotencyEntry.body,
        idempotency_key: IDEMPOTENCY_KEY,
        request_id: OWNED_REQUEST_ID,
        status: "response_201",
      },
    ],
    phase: "request_observed",
    request_ids: [OWNED_REQUEST_ID],
    request_ownership: [
      {
        idempotency_key: IDEMPOTENCY_KEY,
        operation_key: KMA_NOWCAST_OPERATION_KEY,
        provider_dataset_id: PROVIDER_DATASET_ID,
        request_id: OWNED_REQUEST_ID,
        sync_scope: SYNC_SCOPE,
      },
    ],
    request_terminal_statuses: {},
    run_id: "c7-cleanup-ownership-run",
    scenario: "active",
    scope_state_count: 0,
    target_history: [],
    target_refs: [],
    updated_at: "2026-08-07T00:00:00.000Z",
    version: 4,
  };
}

test("C7 cleanup selects the durably owned active request for cancellation", () => {
  expect(
    cancellationCandidateForScenarioOwnedActiveRequest(
      datasetDetail(OWNED_REQUEST_ID),
      requestDetail(OWNED_REQUEST_ID),
      ownership,
      idempotencyEntry,
    ),
  ).toBe(OWNED_REQUEST_ID);
});

test("C7 cleanup never selects a foreign active request in the same scope", () => {
  expect(
    cancellationCandidateForScenarioOwnedActiveRequest(
      datasetDetail(FOREIGN_REQUEST_ID),
      requestDetail(FOREIGN_REQUEST_ID),
      ownership,
      idempotencyEntry,
    ),
  ).toBeNull();
});

test("C7 cleanup never selects an operation-mismatched active, detail, or membership", () => {
  const foreignOperation = "feature_weather_kma_short_forecast_job";
  const cases = [
    () => {
      const detail = datasetDetail(OWNED_REQUEST_ID);
      detail.data.active_execution!.operation_key = foreignOperation;
      return [detail, requestDetail(OWNED_REQUEST_ID)] as const;
    },
    () => {
      const detail = requestDetail(OWNED_REQUEST_ID);
      const scope = detail.data.update_request!.scope;
      if (scope.type !== "provider_dataset") {
        throw new Error("C7 fixture provider_dataset scope가 아닙니다");
      }
      scope.operation_key = foreignOperation;
      return [datasetDetail(OWNED_REQUEST_ID), detail] as const;
    },
    () => {
      const detail = requestDetail(OWNED_REQUEST_ID);
      detail.data.update_request!.dataset_memberships[0]!.operation_key =
        foreignOperation;
      return [datasetDetail(OWNED_REQUEST_ID), detail] as const;
    },
  ];

  for (const makeDetails of cases) {
    const [dataset, request] = makeDetails();
    expect(
      cancellationCandidateForScenarioOwnedActiveRequest(
        dataset,
        request,
        ownership,
        idempotencyEntry,
      ),
    ).toBeNull();
  }
});

test("C7 v4 journal requires one-to-one request/idempotency/scope/operation ownership", () => {
  const journal = durableV4Journal() as {
    idempotency_entries: Array<{
      body: { scope: { provider_dataset_id: number; type: string } };
    }>;
    request_ownership: unknown[];
  };
  expect(hasExactC7RequestOwnershipBinding(journal)).toBe(true);

  journal.request_ownership = [];
  expect(hasExactC7RequestOwnershipBinding(journal)).toBe(false);

  journal.request_ownership = [
    {
      idempotency_key: IDEMPOTENCY_KEY,
      operation_key: KMA_NOWCAST_OPERATION_KEY,
      provider_dataset_id: PROVIDER_DATASET_ID,
      request_id: OWNED_REQUEST_ID,
      sync_scope: SYNC_SCOPE,
    },
  ];
  const journalScope = journal.idempotency_entries[0]!.body.scope;
  if (journalScope.type !== "provider_dataset") {
    throw new Error("C7 journal fixture provider_dataset scope가 아닙니다");
  }
  journalScope.provider_dataset_id += 1;
  expect(hasExactC7RequestOwnershipBinding(journal)).toBe(false);

  const missingOperation = durableV4Journal() as {
    request_ownership: Array<Record<string, unknown>>;
  };
  delete missingOperation.request_ownership[0]!.operation_key;
  expect(hasExactC7RequestOwnershipBinding(missingOperation)).toBe(false);

  const foreignOperation = durableV4Journal() as {
    request_ownership: Array<Record<string, unknown>>;
  };
  foreignOperation.request_ownership[0]!.operation_key =
    "feature_weather_kma_short_forecast_job";
  expect(hasExactC7RequestOwnershipBinding(foreignOperation)).toBe(false);
});

test("C7 v3는 bootstrap placeholder 전용이고 최종 journal이 될 수 없다", () => {
  const bootstrap = {
    cleanup_result: null,
    completed_scenarios: [],
    external_systems: [],
    idempotency_entries: [],
    phase: "restored",
    request_ids: [],
    request_terminal_statuses: {},
    run_id: "__orchestrator_pending__",
    target_history: [],
    target_refs: [],
    version: 3,
  };
  expect(isC7OrchestratorBootstrapPlaceholder(bootstrap)).toBe(true);
  expect(hasExactC7RequestOwnershipBinding(bootstrap)).toBe(false);

  const legacyFinal = { ...durableV4Journal(), version: 3 };
  expect(isC7OrchestratorBootstrapPlaceholder(legacyFinal)).toBe(false);
  expect(hasExactC7RequestOwnershipBinding(legacyFinal)).toBe(false);

  // 미지 version은 앞뒤 어느 쪽도 소유권을 말할 수 없다. v3는 placeholder 전용이고
  // v5는 아직 없는 계약이다 — 둘 다 최종 journal로 해석하면 검사를 건너뛰게 된다.
  const futureFinal = { ...durableV4Journal(), version: 5 };
  expect(isC7OrchestratorBootstrapPlaceholder(futureFinal)).toBe(false);
  expect(hasExactC7RequestOwnershipBinding(futureFinal)).toBe(false);
});
