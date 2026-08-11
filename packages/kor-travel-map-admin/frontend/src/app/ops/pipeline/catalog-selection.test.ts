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

/** refresh operation이 canonical scope를 하나도 선언하지 않은 상태. 서버는 이
 *  상태에서도 `default_sync_scope`를 표시용 `dataset_wide`로 degrade한다
 *  (`api/ops_dataset_service.py::_scope_refresh_capability`) — 그래서 `effect`를
 *  읽지 않으면 정상 dataset-wide capability와 구분되지 않는다. */
const EXTERNAL_ONLY_CAPABILITY: OpsDatasetScopeRefreshCapability = {
  supported: false,
  selector: "none",
  effect: "none",
  default_sync_scope: "dataset_wide",
  allowed_sync_scopes: ["external_system:pinvi"],
  reason:
    "이 dataset의 refresh operation에 canonical sync scope(dataset_wide/target_grids) 선언이 없습니다.",
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
    const rows = [row(6, "dataset_wide", EXTERNAL_ONLY_CAPABILITY)];

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
    ).toBe(EXTERNAL_ONLY_CAPABILITY.reason);
  });

  it("선언된 external scope 자체도 제출 대상이 아니다", () => {
    const rows = [row(6, "external_system:pinvi", EXTERNAL_ONLY_CAPABILITY)];

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
    ).toBe(EXTERNAL_ONLY_CAPABILITY.reason);
  });

  it("진짜 dataset-wide 전용 capability는 계속 통과한다", () => {
    const rows = [row(7, "dataset_wide", DATASET_WIDE_CAPABILITY)];

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
    const rows = [row(8, "target_grids", TARGETED_CAPABILITY)];
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
    expect(scope("external_system:concierge")).toBe(
      "현재 catalog capability가 허용하지 않는 sync_scope입니다.",
    );
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
