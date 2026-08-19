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

/** canonical `sync_scope` 정규형(`kortravelmap.core.sync_scope`). */
export const TARGET_GRIDS_SYNC_SCOPE = "target_grids";
export const EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX = "external_system:";
/** `kortravelmap.core.sync_scope.MAX_EXTERNAL_SYSTEM_NAME_LENGTH`와 같은 값. */
export const MAX_EXTERNAL_SYSTEM_NAME_LENGTH = 112;

/** 이 dataset에서 `syncScope`의 membership을 찾을 때 쓸 scope.
 *
 *  `external_system:<name>`은 두 가지 모양으로 존재한다.
 *
 *  1. **선언된 scope** — `provider_dataset_operation_scopes`에 그 행이 있으면
 *     `allowed_sync_scopes`에도 나오고 그리드에도 membership 행이 있다. 이때는
 *     그 축 그대로 본다(capability가 `effect="none"`이면 여기서 막힌다).
 *  2. **exact target** — 이름이 선언이 아니라 데이터인 경우다. 운영자가 특정
 *     external system의 cache target만 좁혀 갱신하는 것이고, 실행 경로는
 *     `target_grids` 집합을 좁힌 것이므로(`dagster/kma_weather.py`가 두 kind를
 *     같은 grid 경로로 처리한다) membership도 `target_grids` 행에서 읽는다.
 *
 *  이 사상을 한 곳에 두지 않으면 dialog는 통과시키고 제출 직전 가드가 막는 식으로
 *  갈린다.
 */
export function membershipSyncScope(
  syncScope: string,
  datasetRows: readonly { sync_scope: string }[],
): string {
  if (datasetRows.some((row) => row.sync_scope === syncScope)) {
    return syncScope;
  }
  return syncScope.startsWith(EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX)
    ? TARGET_GRIDS_SYNC_SCOPE
    : syncScope;
}

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

/**
 * 제출 직전 fail-closed 가드.
 *
 * 조회는 **triple 전체**로 한다. dialog는 열릴 때 받은 rows로 scope를 만들고
 * (`request-dialog.tsx`의 `buildScope()`는 `catalogQuery.refetch()`보다 **먼저**
 * 실행된다), 그 뒤 refetch한 rows로 여기를 부른다 — 그 사이에 사라진 축을 잡는 것이
 * 이 함수의 존재 이유다. `provider_dataset_id` 하나로 찾으면 dataset만 남아 있으면
 * 통과하므로, 고른 operation이 disable되거나 그 (dataset, scope, operation) 행이
 * 지워진 경우를 그대로 흘려보낸다.
 *
 * 그리드 행은 membership 단위다 — `api/ops_dataset_service.py::_catalog_state_memberships`가
 * enabled refresh operation의 `(sync_scope, operation_key)` 조합마다 한 행을 낸다.
 * 그래서 "행이 없다"는 곧 "그 triple을 서버가 더 이상 선언하지 않는다"이다.
 * 요청 스키마(`feature_update_schema.ProviderDatasetScope`)도 `sync_scope`와
 * `operation_key`를 `NonEmptyString`으로 받는다.
 *
 * 사유 문구는 **어느 축이 사라졌는지** 구분한다. 세 축을 한 문장으로 뭉치면
 * 운영자가 dataset을 다시 고를지, scope를 바꿀지, 형제 operation을 고를지 알 수 없다.
 */
export function validateCatalogSelection(
  scope: RequestScope,
  rows: CanonicalCatalogRow[],
): string | null {
  if (scope.type !== "provider_dataset") {
    return null;
  }
  const datasetRows = rows.filter(
    (item) => item.provider_dataset_id === scope.provider_dataset_id,
  );
  if (datasetRows.length === 0) {
    return "현재 canonical catalog에 없는 데이터셋입니다.";
  }
  const lookupScope = membershipSyncScope(scope.sync_scope, datasetRows);
  const scopeRows = datasetRows.filter(
    (item) => item.sync_scope === lookupScope,
  );
  if (scopeRows.length === 0) {
    return `이 데이터셋에 sync_scope "${lookupScope}" membership이 더 이상 없습니다. 갱신 범위를 다시 고르세요.`;
  }
  const operationKey = scope.operation_key.trim();
  if (!operationKey) {
    // 서버 스키마가 `NonEmptyString`이라 빈 값은 422다. 여기서 막지 않으면 어느 축이
    // 문제인지 모르는 채로 서버 검증 오류를 받는다.
    return "operation_key가 비어 있어 실행할 membership을 확정할 수 없습니다.";
  }
  const row = scopeRows.find((item) => item.operation_key === operationKey);
  if (!row) {
    return `이 데이터셋의 "${lookupScope}" scope에 operation_key "${operationKey}" membership이 더 이상 없습니다. operation을 다시 고르세요.`;
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
    capability?.default_sync_scope !== lookupScope &&
    !capability?.allowed_sync_scopes.includes(lookupScope)
  ) {
    return "현재 catalog capability가 허용하지 않는 sync_scope입니다.";
  }
  return null;
}
