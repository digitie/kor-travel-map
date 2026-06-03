/**
 * POI/cache target 관리와 target 기준 주변 feature 조회 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, pathWithQuery, putJson } from "./client";

export type PoiCacheTargetScopeMode = "center_radius" | "sigungu_by_radius";
export type PoiCacheTargetRefreshPolicy =
  | "provider_default"
  | "follow_system"
  | "allow_targeted"
  | "disabled";
export type PoiCacheTargetConflictMode = "reject" | "move";
export type NearbySort = "distance" | "name" | "last_updated_at";

export interface CoordinateBody {
  lon: number;
  lat: number;
}

export interface PoiCacheTargetUpsertRequest {
  coord: CoordinateBody;
  coord_precision_digits?: number;
  radius_km?: number;
  name?: string | null;
  scope_mode?: PoiCacheTargetScopeMode;
  update_enabled?: boolean;
  refresh_policy?: PoiCacheTargetRefreshPolicy;
  provider_overrides?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  on_conflict?: PoiCacheTargetConflictMode;
}

export interface PoiCacheTargetRecord {
  target_id: string;
  external_system: string;
  target_key: string;
  name: string | null;
  coord: CoordinateBody;
  coord_precision_digits: number;
  coord_key: string;
  radius_km: number;
  scope_mode: string;
  update_enabled: boolean;
  refresh_policy: string;
  provider_overrides: Record<string, unknown>;
  metadata: Record<string, unknown>;
  last_seen_at: string;
  last_requested_at: string | null;
  last_refreshed_at: string | null;
  last_failed_at: string | null;
  next_eligible_refresh_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  status_url: string;
  nearby_url: string;
}

export interface PoiCacheTargetResponse {
  data: PoiCacheTargetRecord;
  meta: {
    duration_ms: number;
  };
}

export interface PoiCacheTargetListResponse {
  count: number;
  items: PoiCacheTargetRecord[];
}

export interface PoiCacheTargetListParams {
  external_system?: string;
  update_enabled?: boolean;
  include_deleted?: boolean;
  page_size?: number;
}

export interface NearbyTargetSummary {
  target_id: string;
  external_system: string;
  target_key: string;
  name: string | null;
  lon: number;
  lat: number;
  radius_km: number;
  scope_mode: string;
  update_enabled: boolean;
  refresh_policy: string;
  last_updated_at: string;
  last_refreshed_at: string | null;
  next_eligible_refresh_at: string | null;
}

export interface NearbyFeatureSummary {
  feature_id: string;
  kind: string;
  name: string;
  category: string;
  status: string;
  lon: number;
  lat: number;
  distance_m: number;
  primary_provider: string | null;
  primary_dataset_key: string | null;
  last_updated_at: string;
}

export interface FeaturesNearbyByTargetResponse {
  data: {
    target: NearbyTargetSummary;
    items: NearbyFeatureSummary[];
    next_cursor: string | null;
  };
  meta: {
    count: number;
    duration_ms: number;
  };
}

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
): Promise<PoiCacheTargetListResponse> {
  return getJson<PoiCacheTargetListResponse>(
    pathWithQuery("/admin/poi-cache-targets", {
      external_system: params.external_system,
      update_enabled: params.update_enabled,
      include_deleted: params.include_deleted,
      page_size: params.page_size,
    }),
  );
}

function fetchPoiCacheTarget(
  externalSystem: string,
  targetKey: string,
  includeDeleted = false,
): Promise<PoiCacheTargetRecord> {
  return getJson<PoiCacheTargetRecord>(
    pathWithQuery(
      `/admin/poi-cache-targets/${encodeURIComponent(
        externalSystem,
      )}/${encodeURIComponent(targetKey)}`,
      { include_deleted: includeDeleted },
    ),
  );
}

function upsertPoiCacheTarget(
  externalSystem: string,
  targetKey: string,
  body: PoiCacheTargetUpsertRequest,
): Promise<PoiCacheTargetResponse> {
  return putJson<PoiCacheTargetResponse>(
    `/admin/poi-cache-targets/${encodeURIComponent(
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
    `/admin/poi-cache-targets/${encodeURIComponent(
      externalSystem,
    )}/${encodeURIComponent(targetKey)}`,
  );
}

function fetchNearbyFeaturesByTarget(
  params: NearbyByTargetParams,
): Promise<FeaturesNearbyByTargetResponse> {
  return getJson<FeaturesNearbyByTargetResponse>(
    pathWithQuery("/features/nearby/by-target", {
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
  );
}

export function usePoiCacheTargets(params: PoiCacheTargetListParams = {}) {
  return useQuery<PoiCacheTargetListResponse, Error>({
    queryKey: ["poi-cache-targets", params],
    queryFn: () => fetchPoiCacheTargets(params),
    staleTime: 30_000,
  });
}

export function usePoiCacheTarget(
  externalSystem: string | null,
  targetKey: string | null,
  includeDeleted = false,
) {
  return useQuery<PoiCacheTargetRecord, Error>({
    queryKey: ["poi-cache-target", externalSystem, targetKey, includeDeleted],
    queryFn: () =>
      fetchPoiCacheTarget(externalSystem as string, targetKey as string, includeDeleted),
    enabled:
      externalSystem !== null &&
      externalSystem.length > 0 &&
      targetKey !== null &&
      targetKey.length > 0,
    staleTime: 30_000,
  });
}

export function useNearbyFeaturesByTarget(params: NearbyByTargetParams | null) {
  return useQuery<FeaturesNearbyByTargetResponse, Error>({
    queryKey: ["nearby-features-by-target", params],
    queryFn: () => fetchNearbyFeaturesByTarget(params as NearbyByTargetParams),
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
