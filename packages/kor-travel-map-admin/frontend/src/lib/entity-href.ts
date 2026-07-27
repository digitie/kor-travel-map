import { DAGSTER_UI_URL } from "@/api/pipeline";

export type EntityKind =
  | "feature"
  | "importJob"
  | "updateRequest"
  | "provider"
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
  id: string,
  params?: EntityParams,
): string | null {
  switch (kind) {
    case "feature":
      return `/features/${encodeURIComponent(id)}`;
    case "importJob":
      return `/ops/pipeline?execution=import_job:${encodeURIComponent(id)}`;
    case "updateRequest":
      return `/ops/pipeline?execution=update_request:${encodeURIComponent(id)}`;
    case "provider": {
      const { dataset_key: dataset, sync_scope, ...rest } = params ?? {};
      return withQuery("/ops/datasets", {
        ...rest,
        provider: id,
        dataset,
        sync_scope,
      });
    }
    case "issue":
      return withQuery("/admin/issues", { ...params });
    case "loadBatch": {
      const rest = { ...params };
      delete rest.kind;
      delete rest.load_batch_id;
      return withQuery("/ops/pipeline", { ...rest, load_batch_id: id });
    }
    case "schedule":
      return withQuery("/ops/pipeline", {
        ...params,
        tab: "schedules",
        schedule: id,
      });
    case "changeRequest":
      return withQuery("/admin/features/change-requests", {
        ...params,
        request_id: id,
      });
    case "dagsterRun":
      return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(id)}`;
  }
}
