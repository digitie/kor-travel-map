import { describe, expect, it } from "vitest";

import type {
  OpsDatasetGridRow,
  OpsDatasetScopeRefreshCapability,
} from "@/api/datasets";

import {
  type CanonicalCatalogRow,
  canonicalCatalogRows,
  validateCatalogSelection,
} from "./catalog-selection";

/** 제출 가능한 scope가 하나도 없는데 **선언된 scope 목록은 비어 있지 않은** 상태.
 *  서버의 `if not entry.is_refreshable` 분기가 낸다
 *  (`api/ops_dataset_service.py::_scope_refresh_capability`) — 비활성 dataset이나
 *  실행 가능한 refresh operation이 없는 dataset이 여기 해당하고, 운영자가 "왜 막혔나"를
 *  판단하도록 잔존 선언을 그대로 보여 준다. `default_sync_scope`는 그 상태에서도
 *  표시용 `dataset_wide`로 내려오므로, `effect`를 읽지 않으면 정상 dataset-wide
 *  capability와 구분되지 않는다. 그것이 이 fixture가 지키는 축이다. */
const UNSUBMITTABLE_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "none",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: ["external_system:pinvi"],
  reason: "이 dataset에는 실행 가능한 refresh runner가 없습니다.",
};

/** 위와 다섯 필드 중 넷이 같다. 다른 것은 `effect`뿐이고, 이쪽은 **실제로
 *  실행 가능한** 전체 dataset 갱신이다. 두 상태를 가르는 대조군이다. */
const DATASET_WIDE_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "dataset_wide",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: [],
  reason: "이 dataset은 전체 dataset 단위로만 갱신합니다.",
};

const TARGETED_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: true,
  selector: "poi_cache_targets",
  effect: "sync_scope",
  default_sync_scope: "target_grids",
  allowed_sync_scopes: ["target_grids", "dataset_wide"],
  reason: null,
};

function row(
  providerDatasetId: number,
  syncScope: string,
  capability: OpsDatasetScopeRefreshCapability,
  overrides: Partial<OpsDatasetGridRow> = {},
): CanonicalCatalogRow {
  return {
    provider: "python-kma-api",
    dataset_key: "kma_short_forecast",
    provider_dataset_id: providerDatasetId,
    sync_scope: syncScope,
    operation_key: "feature_weather_kma_short_forecast_job",
    catalog_state: "canonical",
    mutable: true,
    catalog: {
      is_refreshable: true,
      scope_refresh: capability,
    },
    ...overrides,
  } as unknown as CanonicalCatalogRow;
}

describe("validateCatalogSelection", () => {
  it("실행 가능한 scope 선언이 없는 dataset은 degrade된 기본값으로도 제출되지 않는다", () => {
    const rows = [row(6, "dataset_wide", UNSUBMITTABLE_CAPABILITY)];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 6,
          // 서버가 degrade해 내려준 바로 그 값이다. `effect`를 안 보면 아래
          // `default_sync_scope` 비교가 참이 되어 그대로 통과했다.
          sync_scope: "dataset_wide",
          operation_key: "feature_weather_kma_short_forecast_job",
        },
        rows,
      ),
    ).toBe(UNSUBMITTABLE_CAPABILITY.reason);
  });

  it("선언된 external scope 자체도 제출 대상이 아니다", () => {
    const rows = [row(6, "external_system:pinvi", UNSUBMITTABLE_CAPABILITY)];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 6,
          sync_scope: "external_system:pinvi",
          operation_key: "feature_weather_kma_short_forecast_job",
        },
        rows,
      ),
    ).toBe(UNSUBMITTABLE_CAPABILITY.reason);
  });

  it("진짜 dataset-wide 전용 capability는 계속 통과한다", () => {
    const rows = [
      row(7, "dataset_wide", DATASET_WIDE_CAPABILITY, {
        operation_key: "feature_event_datagokr_cultural_festivals_job",
      }),
    ];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 7,
          sync_scope: "dataset_wide",
          operation_key: "feature_event_datagokr_cultural_festivals_job",
        },
        rows,
      ),
    ).toBeNull();
  });

  it("targeted capability는 선언된 scope만 받는다", () => {
    // 두 scope 모두 membership 행이 있다 — `_catalog_state_memberships`가
    // 선언된 `(sync_scope, operation_key)`마다 한 행을 내므로,
    // `allowed_sync_scopes`에 있는 scope에는 행도 함께 있다.
    const rows = [
      row(8, "target_grids", TARGETED_CAPABILITY),
      row(8, "dataset_wide", TARGETED_CAPABILITY),
    ];
    const scope = (syncScope: string) =>
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 8,
          sync_scope: syncScope,
          operation_key: "feature_weather_kma_short_forecast_job",
        },
        rows,
      );

    expect(scope("target_grids")).toBeNull();
    expect(scope("dataset_wide")).toBeNull();
  });

  it("행은 있는데 capability가 선언하지 않은 scope는 capability 축에서 막는다", () => {
    // **지금 서버는 이 모양을 만들지 않는다.** `effect="dataset_wide"` 분기는
    // `entry.refresh_scopes == ("dataset_wide",)`일 때만 도는데
    // (`api/ops_dataset_service.py::_scope_refresh_capability`), 그때는 membership 행도
    // `dataset_wide` 하나뿐이다. `allowed_sync_scopes`와 membership 행이 같은
    // `refresh_scopes`에서 나오므로 두 축은 서로 어긋날 수 없다.
    //
    // 그 불변식이 깨지는 순간을 잡으라고 이 단언을 남긴다. 앞 판에서는 실제로 깨져
    // 있었다 — `not supports_targeted_refresh`로 접던 분기가 `external_system:*`를
    // 함께 선언한 dataset에도 `allowed_sync_scopes=[]`를 냈고, 그 dataset의 external
    // membership 행은 그리드에 그대로 나왔다. 서버가 다시 그 모양이 되면 여기서 막는다.
    const rows = [
      row(9, "dataset_wide", DATASET_WIDE_CAPABILITY),
      row(9, "external_system:concierge", DATASET_WIDE_CAPABILITY),
    ];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 9,
          sync_scope: "external_system:concierge",
          operation_key: "feature_weather_kma_short_forecast_job",
        },
        rows,
      ),
    ).toBe("현재 catalog capability가 허용하지 않는 sync_scope입니다.");
  });

  it("dialog를 연 뒤 operation만 사라져도 제출 직전에 막고 그 축을 지목한다", () => {
    // dataset과 scope는 그대로고 **형제 operation 하나만** 사라진 모양이다
    // (operation disable 또는 그 scope 행 삭제). dataset 하나로 행을 찾으면
    // `a_job` 행이 남아 있으므로 `b_job` 제출이 그대로 통과했다.
    const staleSelection = {
      type: "provider_dataset",
      provider_dataset_id: 8,
      sync_scope: "target_grids",
      operation_key: "b_job",
    } as const;
    const before = [
      row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "a_job" }),
      row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "b_job" }),
    ];
    const after = [
      row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "a_job" }),
    ];

    expect(validateCatalogSelection(staleSelection, before)).toBeNull();
    expect(validateCatalogSelection(staleSelection, after)).toBe(
      '이 데이터셋의 "target_grids" scope에 operation_key "b_job" membership이 더 이상 없습니다. operation을 다시 고르세요.',
    );
  });

  it("선언되지 않은 exact target은 target_grids membership으로 통과한다", () => {
    // 이름이 선언이 아니라 데이터인 경우다. 제출 직전 가드가 그 사실을 모르면
    // dialog가 만든 canonical scope를 자기 화면이 막는다. 선언된 external scope는
    // 위 두 단언이 그대로 지킨다 — 그 행이 있으면 그 축으로 본다.
    const rows = [
      row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "a_job" }),
    ];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 8,
          sync_scope: "external_system:pinvi",
          operation_key: "a_job",
        },
        rows,
      ),
    ).toBeNull();
  });

  it("exact target도 target_grids membership이 없으면 그 축을 사유로 막는다", () => {
    const rows = [
      row(8, "dataset_wide", DATASET_WIDE_CAPABILITY, {
        operation_key: "a_job",
      }),
    ];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 8,
          sync_scope: "external_system:pinvi",
          operation_key: "a_job",
        },
        rows,
      ),
    ).toBe(
      '이 데이터셋에 sync_scope "target_grids" membership이 더 이상 없습니다. 갱신 범위를 다시 고르세요.',
    );
  });

  it("scope만 사라진 경우와 operation만 사라진 경우를 다른 사유로 구분한다", () => {
    const rows = [
      row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "a_job" }),
    ];

    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 8,
          // capability가 허용하는 scope지만 그 membership 행이 사라졌다.
          sync_scope: "dataset_wide",
          operation_key: "a_job",
        },
        rows,
      ),
    ).toBe(
      '이 데이터셋에 sync_scope "dataset_wide" membership이 더 이상 없습니다. 갱신 범위를 다시 고르세요.',
    );
  });

  it("operation_key가 비면 서버 검증(NonEmptyString) 전에 막는다", () => {
    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 8,
          sync_scope: "target_grids",
          operation_key: "",
        },
        [row(8, "target_grids", TARGETED_CAPABILITY, { operation_key: "a_job" })],
      ),
    ).toBe("operation_key가 비어 있어 실행할 membership을 확정할 수 없습니다.");
  });

  it("canonical 목록에 없는 dataset과 provider_dataset 아닌 scope를 가른다", () => {
    expect(
      validateCatalogSelection(
        {
          type: "provider_dataset",
          provider_dataset_id: 999,
          sync_scope: "dataset_wide",
          operation_key: "x",
        },
        [row(8, "target_grids", TARGETED_CAPABILITY)],
      ),
    ).toBe("현재 canonical catalog에 없는 데이터셋입니다.");

    expect(
      validateCatalogSelection(
        {
          type: "center_radius",
          center: { lon: 127, lat: 37 },
          radius_km: 5,
        },
        [],
      ),
    ).toBeNull();
  });
});

describe("canonicalCatalogRows", () => {
  it("갱신 불가 dataset은 요청 후보에서 빠진다", () => {
    const items = [
      row(6, "dataset_wide", DATASET_WIDE_CAPABILITY),
      row(7, "dataset_wide", DATASET_WIDE_CAPABILITY, {
        // scope 행이 하나도 없는 상태 — 서버가 `is_refreshable=false`로 낸다.
        catalog: {
          is_refreshable: false,
          scope_refresh: DATASET_WIDE_CAPABILITY,
        },
      } as unknown as Partial<OpsDatasetGridRow>),
      row(8, "dataset_wide", DATASET_WIDE_CAPABILITY, { mutable: false }),
      row(9, "dataset_wide", DATASET_WIDE_CAPABILITY, {
        catalog_state: "orphan",
      }),
    ];

    expect(
      canonicalCatalogRows({
        data: { items },
      } as unknown as Parameters<typeof canonicalCatalogRows>[0]).map(
        (item) => item.provider_dataset_id,
      ),
    ).toEqual([6]);
  });

  it("membership마다 한 행이고 triple 순서로 정렬한다", () => {
    const items = [
      row(6, "target_grids", TARGETED_CAPABILITY, {
        operation_key: "b_job",
      }),
      row(6, "dataset_wide", TARGETED_CAPABILITY, { operation_key: "z_job" }),
      row(6, "target_grids", TARGETED_CAPABILITY, {
        operation_key: "a_job",
      }),
    ];

    expect(
      canonicalCatalogRows({
        data: { items },
      } as unknown as Parameters<typeof canonicalCatalogRows>[0]).map(
        (item) => `${item.sync_scope}:${item.operation_key}`,
      ),
    ).toEqual(["dataset_wide:z_job", "target_grids:a_job", "target_grids:b_job"]);
  });
});
