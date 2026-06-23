/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, patchJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FeatureSchemas = components["schemas"];

export type FeatureSummary = FeatureSchemas["FeatureSummary"];
export type FeaturesInBboxResponse = FeatureSchemas["FeaturesInBboxResponse"];

export interface FeaturesInBboxParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  kinds?: string[];
  includeGeometry?: boolean;
  page_size?: number;
  zoom?: number;
}

interface FeatureTile {
  key: string;
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  x: number;
  y: number;
  z: number;
}

const MAX_FEATURE_TILES = 24;
const MIN_FEATURE_TILE_ZOOM = 5;
const MAX_FEATURE_TILE_ZOOM = 12;
const MERCATOR_LAT_LIMIT = 85.05112878;

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function lonToTileX(lon: number, zoom: number): number {
  const n = 2 ** zoom;
  return clampNumber(Math.floor(((lon + 180) / 360) * n), 0, n - 1);
}

function latToTileY(lat: number, zoom: number): number {
  const clampedLat = clampNumber(lat, -MERCATOR_LAT_LIMIT, MERCATOR_LAT_LIMIT);
  const latRad = (clampedLat * Math.PI) / 180;
  const n = 2 ** zoom;
  return clampNumber(
    Math.floor(
      ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) *
        n,
    ),
    0,
    n - 1,
  );
}

function tileXToLon(x: number, zoom: number): number {
  return (x / 2 ** zoom) * 360 - 180;
}

function tileYToLat(y: number, zoom: number): number {
  const n = Math.PI - (2 * Math.PI * y) / 2 ** zoom;
  return (180 / Math.PI) * Math.atan(Math.sinh(n));
}

function buildFeatureTiles(params: FeaturesInBboxParams): FeatureTile[] {
  const desiredZoom = clampNumber(
    Math.floor(typeof params.zoom === "number" ? params.zoom : 8),
    MIN_FEATURE_TILE_ZOOM,
    MAX_FEATURE_TILE_ZOOM,
  );
  const minLon = Math.min(params.min_lon, params.max_lon);
  const maxLon = Math.max(params.min_lon, params.max_lon);
  const minLat = Math.min(params.min_lat, params.max_lat);
  const maxLat = Math.max(params.min_lat, params.max_lat);

  for (
    let tileZoom = desiredZoom;
    tileZoom >= MIN_FEATURE_TILE_ZOOM;
    tileZoom -= 1
  ) {
    const minX = lonToTileX(minLon, tileZoom);
    const maxX = lonToTileX(maxLon, tileZoom);
    const minY = latToTileY(maxLat, tileZoom);
    const maxY = latToTileY(minLat, tileZoom);
    const count = (maxX - minX + 1) * (maxY - minY + 1);
    if (count > MAX_FEATURE_TILES && tileZoom > MIN_FEATURE_TILE_ZOOM) {
      continue;
    }

    const tiles: FeatureTile[] = [];
    for (let x = minX; x <= maxX; x += 1) {
      for (let y = minY; y <= maxY; y += 1) {
        tiles.push({
          key: `${tileZoom}/${x}/${y}`,
          max_lat: tileYToLat(y, tileZoom),
          max_lon: tileXToLon(x + 1, tileZoom),
          min_lat: tileYToLat(y + 1, tileZoom),
          min_lon: tileXToLon(x, tileZoom),
          x,
          y,
          z: tileZoom,
        });
      }
    }
    return tiles;
  }

  return [];
}

async function fetchFeaturesInBbox(
  params: FeaturesInBboxParams,
  signal?: AbortSignal,
): Promise<FeaturesInBboxResponse> {
  return getJson<FeaturesInBboxResponse>(
    pathWithQuery("/v1/features", {
      min_lon: params.min_lon,
      min_lat: params.min_lat,
      max_lon: params.max_lon,
      max_lat: params.max_lat,
      page_size: params.page_size,
      kind: params.kinds,
      include_geometry: params.includeGeometry,
    }),
    { signal },
  );
}

async function fetchFeaturesInTiles(
  queryClient: ReturnType<typeof useQueryClient>,
  params: FeaturesInBboxParams,
  signal?: AbortSignal,
): Promise<FeaturesInBboxResponse> {
  const tiles = buildFeatureTiles(params);
  if (tiles.length === 0) {
    return fetchFeaturesInBbox(params, signal);
  }

  const requestedPageSize = params.page_size ?? 500;
  const perTilePageSize = Math.min(
    requestedPageSize,
    Math.max(50, Math.ceil(requestedPageSize / tiles.length)),
  );

  const responses = await Promise.all(
    tiles.map((tile) => {
      const tileParams = {
        ...params,
        max_lat: tile.max_lat,
        max_lon: tile.max_lon,
        min_lat: tile.min_lat,
        min_lon: tile.min_lon,
        page_size: perTilePageSize,
      };
      return queryClient.fetchQuery({
        queryKey: [
          "features",
          "tile",
          tile.z,
          tile.x,
          tile.y,
          params.kinds?.join(",") ?? "",
          params.includeGeometry ? "geometry" : "summary",
          perTilePageSize,
        ],
        queryFn: () => fetchFeaturesInBbox(tileParams, signal),
        staleTime: 60_000,
      });
    }),
  );

  const items = new Map<string, FeatureSummary>();
  for (const response of responses) {
    for (const item of response.data.items) {
      items.set(item.feature_id, item);
    }
  }

  const first = responses[0];
  return {
    data: { items: Array.from(items.values()) },
    meta: {
      ...(first?.meta ?? {
        cluster: null,
        duration_ms: 0,
        page: null,
        request_id: "features-tiled",
      }),
      request_id: `features-tiled:${tiles.map((tile) => tile.key).join(",")}`,
    },
  };
}

/**
 * react-query hook — bbox를 WebMercator tile bbox들로 나눠 fetch한다. 각 tile은
 * 별도 queryKey로 캐시되어 작은 pan/zoom 이동에서 이미 받은 tile을 재사용한다.
 */
export function useFeaturesInBbox(
  params: FeaturesInBboxParams,
  options?: { enabled?: boolean },
) {
  const queryClient = useQueryClient();
  const queryParams = {
    ...params,
  };
  const tiles = buildFeatureTiles(queryParams);
  const key = [
    "features",
    "viewport",
    tiles.map((tile) => tile.key).join("|"),
    params.kinds?.join(",") ?? "",
    params.includeGeometry ? "geometry" : "summary",
    params.page_size ?? 500,
  ] as const;
  return useQuery({
    queryKey: key,
    queryFn: ({ signal }) => fetchFeaturesInTiles(queryClient, queryParams, signal),
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
  });
}

// ── feature 단건 상세 (`GET /v1/features/{feature_id}`) ────────────────────────

export type FeatureDetail = FeatureSchemas["FeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  FeatureSchemas["FeatureDetailEnvelopeResponse"];
export type FeatureWeatherResponse = FeatureSchemas["FeatureWeatherResponse"];
export type WeatherCardData = FeatureSchemas["WeatherCardData"];
export type WeatherMetric = FeatureSchemas["WeatherMetricOut"];
export type FeaturesNearbyResponse = FeatureSchemas["FeaturesNearbyResponse"];
export type NearbyFeatureSummary = FeatureSchemas["NearbyFeatureSummary"];

type FeaturesNearbyQuery = NonNullable<
  paths["/v1/features/nearby"]["get"]["parameters"]["query"]
>;
export type FeaturesNearbySort = NonNullable<FeaturesNearbyQuery["sort"]>;
export type FeaturesNearbyParams = Omit<
  FeaturesNearbyQuery,
  "category" | "kind" | "provider" | "status"
> & {
  category?: string[];
  kind?: string[];
  provider?: string[];
  status?: string[];
};

async function fetchFeatureDetail(
  featureId: string,
  signal?: AbortSignal,
): Promise<FeatureDetail> {
  const body = await getJson<FeatureDetailEnvelopeResponse>(
    `/v1/features/${encodeURIComponent(featureId)}`,
    { signal },
  );
  return body.data;
}

/** react-query hook — `selectedFeatureId` 변경 시 자동 fetch. */
export function useFeatureDetail(featureId: string | null) {
  return useQuery({
    queryKey: ["feature", featureId] as const,
    queryFn: ({ signal }) => fetchFeatureDetail(featureId as string, signal),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

async function fetchFeatureWeather(
  featureId: string,
  params: { asof?: string | Date | null } = {},
  signal?: AbortSignal,
): Promise<FeatureWeatherResponse> {
  return getJson<FeatureWeatherResponse>(
    pathWithQuery(`/v1/features/${encodeURIComponent(featureId)}/weather`, {
      asof: params.asof,
    }),
    { signal },
  );
}

export function useFeatureWeather(
  featureId: string | null,
  params: { asof?: string | Date | null } = {},
) {
  return useQuery<FeatureWeatherResponse, Error>({
    queryKey: ["feature", featureId, "weather", params.asof ?? null] as const,
    queryFn: ({ signal }) =>
      fetchFeatureWeather(featureId as string, params, signal),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

async function fetchNearbyFeatures(
  params: FeaturesNearbyParams,
  signal?: AbortSignal,
): Promise<FeaturesNearbyResponse> {
  return getJson<FeaturesNearbyResponse>(
    pathWithQuery("/v1/features/nearby", {
      lon: params.lon,
      lat: params.lat,
      radius_m: params.radius_m,
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

export function useNearbyFeatures(
  params: FeaturesNearbyParams | null,
  options?: { enabled?: boolean },
) {
  return useQuery<FeaturesNearbyResponse, Error>({
    queryKey: ["features-nearby", params] as const,
    queryFn: ({ signal }) =>
      fetchNearbyFeatures(params as FeaturesNearbyParams, signal),
    enabled:
      (options?.enabled ?? true) &&
      params !== null &&
      typeof params.lon === "number" &&
      typeof params.lat === "number",
    staleTime: 60_000,
  });
}

// ── kind 필터 — backend가 받는 7종 (data-model.md §1 FeatureKind) ───────────

export const FEATURE_KINDS = [
  "place",
  "event",
  "notice",
  "price",
  "weather",
  "route",
  "area",
] as const;
export type FeatureKind = (typeof FEATURE_KINDS)[number];

// ── admin feature 목록/비활성화 (`/v1/admin/features`) ───────────────────────

type AdminFeaturesListQuery = NonNullable<
  paths["/v1/admin/features"]["get"]["parameters"]["query"]
>;

export type AdminFeatureSort = NonNullable<AdminFeaturesListQuery["sort"]>;
export type SortOrder = Exclude<
  AdminFeaturesListQuery["order"],
  null | undefined
>;
export type AdminFeatureIssue = FeatureSchemas["AdminFeatureIssueRecord"];
export type AdminFeatureRecord = FeatureSchemas["AdminFeatureRecord"];
export type AdminFeaturesListResponse =
  FeatureSchemas["AdminFeaturesListResponse"];
export type AdminFeatureDetailResponse =
  FeatureSchemas["AdminFeatureDetailResponse"];
export type AdminFeatureDetailData = FeatureSchemas["AdminFeatureDetailData"];
export type AdminFeaturesListParams = Omit<
  AdminFeaturesListQuery,
  "cursor" | "updated_from" | "updated_to"
> & {
  cursor?: string;
  updated_from?: string | Date;
  updated_to?: string | Date;
};
export type AdminFeatureDeactivateRequest =
  FeatureSchemas["AdminFeatureDeactivateRequest"];
export type AdminFeatureOverride = FeatureSchemas["AdminFeatureOverrideRecord"];
export type AdminFeatureDeactivateResponse =
  FeatureSchemas["AdminFeatureDeactivateResponse"];

type AdminFeatureChangeListQuery = NonNullable<
  paths["/v1/admin/features/change-requests"]["get"]["parameters"]["query"]
>;

export type AdminFeatureChangeStatus = Exclude<
  NonNullable<AdminFeatureChangeListQuery["status"]>[number],
  null | undefined
>;
export type AdminFeatureChangeAction = Exclude<
  NonNullable<AdminFeatureChangeListQuery["action"]>[number],
  null | undefined
>;
export type AdminFeatureChangeRecord =
  FeatureSchemas["AdminFeatureChangeRequestRecord"];
export type AdminFeatureChangeListResponse =
  FeatureSchemas["AdminFeatureChangeListResponse"];
export type AdminFeatureChangeResponse =
  FeatureSchemas["AdminFeatureChangeResponse"];
export type AdminFeatureCreateRequest =
  FeatureSchemas["AdminFeatureCreateRequest"];
export type AdminFeaturePatchRequest =
  FeatureSchemas["AdminFeaturePatchRequest"];
export type AdminFeatureDeleteRequest =
  FeatureSchemas["AdminFeatureDeleteRequest"];
export type AdminFeatureReviewActionRequest =
  FeatureSchemas["AdminFeatureReviewActionRequest"];
export type AdminFeatureChangeListParams = Omit<
  AdminFeatureChangeListQuery,
  "action" | "q" | "status"
> & {
  action?: AdminFeatureChangeAction[];
  q?: string;
  status?: AdminFeatureChangeStatus[];
};

function fetchAdminFeatureDetail(
  featureId: string,
  signal?: AbortSignal,
): Promise<AdminFeatureDetailResponse> {
  return getJson<AdminFeatureDetailResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}`,
    { signal },
  );
}

export function useAdminFeatureDetail(featureId: string | null) {
  return useQuery<AdminFeatureDetailResponse, Error>({
    queryKey: ["admin-feature-detail", featureId] as const,
    queryFn: ({ signal }) =>
      fetchAdminFeatureDetail(featureId as string, signal),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 30_000,
  });
}

function fetchAdminFeatures(
  params: AdminFeaturesListParams = {},
  signal?: AbortSignal,
): Promise<AdminFeaturesListResponse> {
  return getJson<AdminFeaturesListResponse>(
    pathWithQuery("/v1/admin/features", {
      q: params.q,
      kind: params.kind,
      category: params.category,
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      has_coord: params.has_coord,
      has_issue: params.has_issue,
      issue_type: params.issue_type,
      updated_from: params.updated_from,
      updated_to: params.updated_to,
      page_size: params.page_size,
      cursor: params.cursor,
      sort: params.sort,
      order: params.order,
    }),
    { signal },
  );
}

function deactivateAdminFeature(
  featureId: string,
  body: AdminFeatureDeactivateRequest,
): Promise<AdminFeatureDeactivateResponse> {
  return postJson<AdminFeatureDeactivateResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}/deactivate`,
    body,
  );
}

function fetchAdminFeatureChangeRequests(
  params: AdminFeatureChangeListParams = {},
  signal?: AbortSignal,
): Promise<AdminFeatureChangeListResponse> {
  return getJson<AdminFeatureChangeListResponse>(
    pathWithQuery("/v1/admin/features/change-requests", {
      status: params.status,
      action: params.action,
      q: params.q,
      page_size: params.page_size,
    }),
    { signal },
  );
}

function createAdminFeature(
  body: AdminFeatureCreateRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>("/v1/admin/features", body);
}

function patchAdminFeature(
  featureId: string,
  body: AdminFeaturePatchRequest,
): Promise<AdminFeatureChangeResponse> {
  return patchJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}`,
    body,
  );
}

function deleteAdminFeature(
  featureId: string,
  body: AdminFeatureDeleteRequest,
): Promise<AdminFeatureChangeResponse> {
  return deleteJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/${encodeURIComponent(featureId)}`,
    body,
  );
}

function approveAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/change-requests/${encodeURIComponent(requestId)}/approve`,
    body,
  );
}

function rejectAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return postJson<AdminFeatureChangeResponse>(
    `/v1/admin/features/change-requests/${encodeURIComponent(requestId)}/reject`,
    body,
  );
}

export function useAdminFeatures(params: AdminFeaturesListParams = {}) {
  return useQuery<AdminFeaturesListResponse, Error>({
    queryKey: ["admin-features", params],
    queryFn: ({ signal }) => fetchAdminFeatures(params, signal),
    staleTime: 30_000,
  });
}

export function useDeactivateAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureDeactivateResponse,
    Error,
    { featureId: string; body: AdminFeatureDeactivateRequest }
  >({
    mutationFn: ({ featureId, body }) => deactivateAdminFeature(featureId, body),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["features"] });
      void queryClient.invalidateQueries({
        queryKey: ["feature", variables.featureId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["admin-feature-detail", variables.featureId],
      });
    },
  });
}

export function useAdminFeatureChangeRequests(
  params: AdminFeatureChangeListParams = {},
) {
  return useQuery<AdminFeatureChangeListResponse, Error>({
    queryKey: ["admin-feature-changes", params],
    queryFn: ({ signal }) => fetchAdminFeatureChangeRequests(params, signal),
    staleTime: 15_000,
  });
}

function invalidateFeatureChangeQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  featureId?: string,
) {
  void queryClient.invalidateQueries({ queryKey: ["admin-feature-changes"] });
  void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
  void queryClient.invalidateQueries({ queryKey: ["features"] });
  if (featureId) {
    void queryClient.invalidateQueries({ queryKey: ["feature", featureId] });
    void queryClient.invalidateQueries({
      queryKey: ["admin-feature-detail", featureId],
    });
  }
}

export function useCreateAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<AdminFeatureChangeResponse, Error, AdminFeatureCreateRequest>({
    mutationFn: createAdminFeature,
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}

export function usePatchAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { featureId: string; body: AdminFeaturePatchRequest }
  >({
    mutationFn: ({ featureId, body }) => patchAdminFeature(featureId, body),
    onSuccess: (data, variables) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id || variables.featureId,
      ),
  });
}

export function useDeleteAdminFeatureMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { featureId: string; body: AdminFeatureDeleteRequest }
  >({
    mutationFn: ({ featureId, body }) => deleteAdminFeature(featureId, body),
    onSuccess: (data, variables) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id || variables.featureId,
      ),
  });
}

export function useApproveAdminFeatureChangeMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { requestId: string; body: AdminFeatureReviewActionRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      approveAdminFeatureChangeRequest(requestId, body),
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}

export function useRejectAdminFeatureChangeMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminFeatureChangeResponse,
    Error,
    { requestId: string; body: AdminFeatureReviewActionRequest }
  >({
    mutationFn: ({ requestId, body }) =>
      rejectAdminFeatureChangeRequest(requestId, body),
    onSuccess: (data) =>
      invalidateFeatureChangeQueries(
        queryClient,
        data.data.request.feature_id,
      ),
  });
}
