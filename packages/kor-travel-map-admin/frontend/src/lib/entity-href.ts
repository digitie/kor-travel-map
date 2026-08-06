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
        !syncScope ||
        !operationKey
      ) {
        return null;
      }
      return withQuery("/ops/datasets", {
        provider_dataset_id: String(id),
        sync_scope: syncScope,
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
