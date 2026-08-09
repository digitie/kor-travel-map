import { DAGSTER_UI_URL } from "@/api/pipeline";

export type EntityKind =
  | "feature"
  | "importJob"
  | "updateRequest"
  | "providerDataset"
  | "issue"
  | "dagsterRun"
  | "loadBatch"
  | "schedule"
  | "changeRequest";

export type EntityParams = Record<string, string | null | undefined>;

function withQuery(path: string, params?: EntityParams): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, value);
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export function hrefFor(
  kind: EntityKind,
  id: string | number,
  params?: EntityParams,
): string | null {
  switch (kind) {
    case "feature":
      return `/features/${encodeURIComponent(id)}`;
    case "importJob":
      return `/ops/pipeline?execution=import_job:${encodeURIComponent(id)}`;
    case "updateRequest":
      return `/ops/pipeline?execution=update_request:${encodeURIComponent(id)}`;
    case "providerDataset": {
      const syncScope = params?.sync_scope;
      const operationKey = params?.operation_key;
      if (
        typeof id !== "number" ||
        !Number.isSafeInteger(id) ||
        id < 1 ||
        !syncScope
      ) {
        return null;
      }
      return withQuery("/ops/datasets", {
        provider_dataset_id: String(id),
        sync_scope: syncScope,
        // 빈 ``operation_key``는 "실행 가능한 refresh operation이 없는 catalog 전용
        // 행"이라는 **유효한 값**이다. 예전에는 `!operationKey`가 그것까지 걸러
        // 링크 자체를 null로 만들어, 실측 74개 중 17~18개 dataset이 어떤 entity
        // 링크로도 도달 불가였다. `withQuery`가 빈 값을 빼면 대상 페이지가
        // (id, scope)로 유일하게 결정한다 — 둘 이상이면 그쪽이 명시 거부한다.
        operation_key: operationKey,
      });
    }
    case "issue":
      return withQuery("/admin/issues", { ...params });
    case "loadBatch": {
      const rest = { ...params };
      delete rest.kind;
      delete rest.load_batch_id;
      return withQuery("/ops/pipeline", {
        ...rest,
        load_batch_id: String(id),
      });
    }
    case "schedule":
      return withQuery("/ops/pipeline", {
        ...params,
        tab: "schedules",
        schedule: String(id),
      });
    case "changeRequest":
      return withQuery("/admin/features/change-requests", {
        ...params,
        request_id: String(id),
      });
    case "dagsterRun":
      return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(id)}`;
  }
}
