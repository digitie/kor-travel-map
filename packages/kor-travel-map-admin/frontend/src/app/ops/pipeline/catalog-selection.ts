import type {
  FeatureUpdateScope,
  PipelineDatasetsCatalogResponse,
} from "@/api/pipeline";

export type CatalogRow =
  PipelineDatasetsCatalogResponse["data"]["items"][number];
export type CanonicalCatalogRow = CatalogRow & { provider_dataset_id: number };

export type ProviderDatasetScope = {
  type: "provider_dataset";
  provider_dataset_id: number;
  // membership identity는 triple이다(ADR-088) — 서버 스키마가 셋을 모두 요구한다.
  sync_scope: string;
  operation_key: string;
};

export type RequestScope =
  | Exclude<FeatureUpdateScope, { type: "provider_dataset" }>
  | ProviderDatasetScope;

export function canonicalCatalogRows(
  response: PipelineDatasetsCatalogResponse | undefined,
): CanonicalCatalogRow[] {
  const rows: CanonicalCatalogRow[] = [];
  for (const row of response?.data.items ?? []) {
    const providerDatasetId = (
      row as CatalogRow & { provider_dataset_id?: unknown }
    ).provider_dataset_id;
    if (
      row.catalog_state !== "canonical" ||
      !row.mutable ||
      row.catalog?.is_refreshable !== true ||
      typeof providerDatasetId !== "number" ||
      !Number.isInteger(providerDatasetId) ||
      providerDatasetId < 1
    ) {
      continue;
    }
    rows.push({ ...row, provider_dataset_id: providerDatasetId });
  }
  // **membership마다 한 행**이다. 예전에는 `Map<number, row>`로 dataset당 하나만
  // 남겼는데, 그러면 (a) 남는 행의 `sync_scope`가 임의로 정해지고 (b) 운영자가
  // 기본이 아닌 allowed scope를 고르면 membership 조회가 실패해 "실행 가능한
  // refresh operation이 없습니다"라는 **거짓 사유**로 요청이 막혔다.
  return rows.sort(
    (left, right) =>
      left.provider_dataset_id - right.provider_dataset_id ||
      left.sync_scope.localeCompare(right.sync_scope) ||
      (left.operation_key ?? "").localeCompare(right.operation_key ?? ""),
  );
}

export function validateCatalogSelection(
  scope: RequestScope,
  rows: CanonicalCatalogRow[],
): string | null {
  if (scope.type !== "provider_dataset") {
    return null;
  }
  const row = rows.find(
    (item) => item.provider_dataset_id === scope.provider_dataset_id,
  );
  if (!row) {
    return "현재 canonical catalog에 없는 데이터셋입니다.";
  }
  const capability = row.catalog?.scope_refresh;
  // ``effect="none"``은 "이 capability로는 어떤 sync scope도 제출할 수 없다"는
  // 뜻이다(`api/ops_dataset_service.py::_scope_refresh_capability`). 이 검사가
  // 없으면 refresh operation이 canonical scope(dataset_wide/target_grids)를
  // 하나도 선언하지 않은 dataset이 여기를 통과한다 — 그 상태에서도
  // ``default_sync_scope``는 표시용 ``dataset_wide``로 degrade하므로 아래
  // 비교가 참이 되기 때문이다. `/ops/datasets` 그리드는 같은 필드로 이미 막지만
  // (`frontend/src/api/datasets.ts` `resolveDatasetRefreshScope`), 요청 dialog는
  // 그 게이트를 지나지 않는다.
  if (capability?.effect === "none") {
    return (
      capability.reason ?? "이 dataset에 걸 수 있는 갱신 범위가 없습니다."
    );
  }
  if (
    capability?.default_sync_scope !== scope.sync_scope &&
    !capability?.allowed_sync_scopes.includes(scope.sync_scope)
  ) {
    return "현재 catalog capability가 허용하지 않는 sync_scope입니다.";
  }
  return null;
}
