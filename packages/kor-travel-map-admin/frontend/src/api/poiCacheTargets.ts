/**
 * POI/cache target 관리와 target 기준 주변 feature 조회 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, pathWithQuery, putJson } from "./client";
import type { components, paths } from "./types";

type PoiCacheTargetSchemas = components["schemas"];
type GeneratedPoiCacheTargetUpsertRequest =
  paths["/v1/admin/poi-cache-targets/{external_system}/{target_key}"]["put"]["requestBody"]["content"]["application/json"];

export type PoiCacheTargetScopeMode =
  PoiCacheTargetSchemas["PoiCacheTargetUpsertRequest"]["scope_mode"];
export type PoiCacheTargetRefreshPolicy =
  PoiCacheTargetSchemas["PoiCacheTargetUpsertRequest"]["refresh_policy"];
export type PoiCacheTargetTargetedPolicy =
  | "follow_system"
  | "allow_targeted"
  | "disabled";
export type PoiCacheTargetConflictMode =
  PoiCacheTargetSchemas["PoiCacheTargetUpsertRequest"]["on_conflict"];
export type NearbySort =
  paths["/v1/features/nearby/by-target"]["get"]["parameters"]["query"]["sort"];

export type CoordinateBody = PoiCacheTargetSchemas["CoordinateBody"];
export type PoiCacheTargetProviderOverride =
  PoiCacheTargetSchemas["PoiCacheTargetProviderOverride-Input"];
export type PoiCacheTargetMetadata =
  PoiCacheTargetSchemas["PoiCacheTargetMetadata-Input"];
export type PoiCacheTargetUpsertRequest = Omit<
  GeneratedPoiCacheTargetUpsertRequest,
  | "coord_precision_digits"
  | "on_conflict"
  | "radius_km"
  | "refresh_policy"
  | "scope_mode"
  | "update_enabled"
> &
  Partial<
    Pick<
      GeneratedPoiCacheTargetUpsertRequest,
      | "coord_precision_digits"
      | "on_conflict"
      | "radius_km"
      | "refresh_policy"
      | "scope_mode"
      | "update_enabled"
    >
  >;
export type PoiCacheTargetRecord =
  PoiCacheTargetSchemas["PoiCacheTargetRecord"];
export type PoiCacheTargetResponse =
  PoiCacheTargetSchemas["PoiCacheTargetResponse"];
export type PoiCacheTargetListResponse =
  PoiCacheTargetSchemas["PoiCacheTargetListResponse"];

export interface PoiCacheTargetListParams {
  external_system?: string;
  update_enabled?: boolean;
  include_deleted?: boolean;
  page_size?: number;
  cursor?: string;
}

export type NearbyTargetSummary = PoiCacheTargetSchemas["NearbyTargetSummary"];
export type NearbyFeatureSummary =
  PoiCacheTargetSchemas["NearbyFeatureSummary"];
export type FeaturesNearbyByTargetResponse =
  PoiCacheTargetSchemas["FeaturesNearbyByTargetResponse"];

export interface NearbyByTargetParams {
  external_system: string;
  target_key: string;
  radius_km?: number;
  kind?: string[];
  category?: string[];
  status?: string[];
  provider?: string[];
  page_size?: number;
  cursor?: string;
  sort?: NearbySort;
}

function fetchPoiCacheTargets(
  params: PoiCacheTargetListParams = {},
  signal?: AbortSignal,
): Promise<PoiCacheTargetListResponse> {
  return getJson<PoiCacheTargetListResponse>(
    pathWithQuery("/v1/admin/poi-cache-targets", {
      external_system: params.external_system,
      update_enabled: params.update_enabled,
      include_deleted: params.include_deleted,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

function upsertPoiCacheTarget(
  externalSystem: string,
  targetKey: string,
  body: PoiCacheTargetUpsertRequest,
): Promise<PoiCacheTargetResponse> {
  return putJson<PoiCacheTargetResponse>(
    `/v1/admin/poi-cache-targets/${encodeURIComponent(
      externalSystem,
    )}/${encodeURIComponent(targetKey)}`,
    body,
  );
}

function deletePoiCacheTarget(
  externalSystem: string,
  targetKey: string,
): Promise<PoiCacheTargetResponse> {
  return deleteJson<PoiCacheTargetResponse>(
    `/v1/admin/poi-cache-targets/${encodeURIComponent(
      externalSystem,
    )}/${encodeURIComponent(targetKey)}`,
  );
}

function fetchNearbyFeaturesByTarget(
  params: NearbyByTargetParams,
  signal?: AbortSignal,
): Promise<FeaturesNearbyByTargetResponse> {
  return getJson<FeaturesNearbyByTargetResponse>(
    pathWithQuery("/v1/features/nearby/by-target", {
      external_system: params.external_system,
      target_key: params.target_key,
      radius_km: params.radius_km,
      kind: params.kind,
      category: params.category,
      status: params.status,
      provider: params.provider,
      page_size: params.page_size,
      cursor: params.cursor,
      sort: params.sort,
    }),
    { signal },
  );
}

export function usePoiCacheTargets(params: PoiCacheTargetListParams = {}) {
  return useQuery<PoiCacheTargetListResponse, Error>({
    queryKey: ["poi-cache-targets", params],
    queryFn: ({ signal }) => fetchPoiCacheTargets(params, signal),
    staleTime: 30_000,
  });
}

export function useNearbyFeaturesByTarget(params: NearbyByTargetParams | null) {
  return useQuery<FeaturesNearbyByTargetResponse, Error>({
    queryKey: ["nearby-features-by-target", params],
    queryFn: ({ signal }) =>
      fetchNearbyFeaturesByTarget(params as NearbyByTargetParams, signal),
    enabled:
      params !== null &&
      params.external_system.length > 0 &&
      params.target_key.length > 0,
    staleTime: 30_000,
  });
}

export function useUpsertPoiCacheTargetMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PoiCacheTargetResponse,
    Error,
    {
      externalSystem: string;
      targetKey: string;
      body: PoiCacheTargetUpsertRequest;
    }
  >({
    mutationFn: ({ externalSystem, targetKey, body }) =>
      upsertPoiCacheTarget(externalSystem, targetKey, body),
    onSuccess: (data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["poi-cache-targets"] });
      void queryClient.invalidateQueries({
        queryKey: [
          "poi-cache-target",
          variables.externalSystem,
          variables.targetKey,
        ],
      });
      void queryClient.invalidateQueries({
        queryKey: ["nearby-features-by-target"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
      if (data.data.nearby_url) {
        void queryClient.invalidateQueries({ queryKey: ["features"] });
      }
    },
  });
}

export function useDeletePoiCacheTargetMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    PoiCacheTargetResponse,
    Error,
    { externalSystem: string; targetKey: string }
  >({
    mutationFn: ({ externalSystem, targetKey }) =>
      deletePoiCacheTarget(externalSystem, targetKey),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["poi-cache-targets"] });
      void queryClient.invalidateQueries({
        queryKey: [
          "poi-cache-target",
          variables.externalSystem,
          variables.targetKey,
        ],
      });
      void queryClient.invalidateQueries({
        queryKey: ["nearby-features-by-target"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["feature-update-requests"],
      });
    },
  });
}
