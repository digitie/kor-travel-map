/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { deleteJson, getJson, patchJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FeatureSchemas = components["schemas"];

export type FeatureSummary = FeatureSchemas["FeatureSummary"];
export type FeaturesInBboxResponse = FeatureSchemas["FeaturesInBboxResponse"];

/**
 * tiled fetch가 merged 응답에 덧붙이는 비계약 메타. 생성된 OpenAPI 타입(`Meta`)에는
 * 없는 클라이언트 전용 필드라 별도 타입으로 합성한다(types.ts는 codegen 산출물이라
 * 손대지 않는다). `partial`은 일부 tile이 perTilePageSize까지 채워졌거나(잘림 의심)
 * next_cursor가 있어 dropped feature가 있을 수 있음을, `failedTiles`는
 * allSettled에서 reject된 tile 수를 알린다(전부 실패 시에만 throw).
 */
export interface TiledFeaturesMetaExtras {
  partial?: boolean;
  failedTiles?: number;
  totalTiles?: number;
}

export type TiledFeaturesResponse = Omit<FeaturesInBboxResponse, "meta"> & {
  meta: FeaturesInBboxResponse["meta"] & TiledFeaturesMetaExtras;
};

export interface FeaturesInBboxParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  kinds?: string[];
  includeGeometry?: boolean;
  page_size?: number;
  zoom?: number;
  cursor?: string;
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
const MAX_GEOMETRY_LIGHT_TILE_PAGES = 10;
const MIN_FEATURE_TILE_ZOOM = 5;
const MAX_FEATURE_TILE_ZOOM = 12;
const MERCATOR_LAT_LIMIT = 85.05112878;
const GEOMETRY_LIGHT_KINDS = new Set(["area", "route"]);

function isGeometryLightOnly(kinds: readonly string[] | undefined): boolean {
  return (
    kinds !== undefined &&
    kinds.length > 0 &&
    kinds.every((kind) => GEOMETRY_LIGHT_KINDS.has(kind))
  );
}

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
  const rawZoom = typeof params.zoom === "number" ? params.zoom : 8;
  // area/route 단독 필터는 summary payload가 작지만 특정 tile에 500건이 몰려
  // false partial이 뜨기 쉽다. 한 단계 더 잘게 나눠 누락/재시도 체감을 줄인다.
  const tileZoomBias = isGeometryLightOnly(params.kinds) ? 1 : 0;
  const desiredZoom = clampNumber(
    Math.floor(rawZoom) + tileZoomBias,
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
      cursor: params.cursor,
    }),
    { signal },
  );
}

async function fetchFeaturesInBboxPages(
  params: FeaturesInBboxParams,
  signal?: AbortSignal,
): Promise<FeaturesInBboxResponse> {
  const items = new Map<string, FeatureSummary>();
  let cursor: string | null = null;
  let response: FeaturesInBboxResponse | null = null;

  for (let page = 0; page < MAX_GEOMETRY_LIGHT_TILE_PAGES; page += 1) {
    response = await fetchFeaturesInBbox(
      { ...params, cursor: cursor ?? undefined },
      signal,
    );
    for (const item of response.data.items) {
      items.set(item.feature_id, item);
    }
    cursor = response.meta.page?.next_cursor ?? null;
    if (cursor === null) break;
  }

  if (response === null) {
    return fetchFeaturesInBbox(params, signal);
  }

  return {
    data: { items: Array.from(items.values()) },
    meta: {
      ...response.meta,
      page: response.meta.page
        ? {
            ...response.meta.page,
            next_cursor: cursor,
          }
        : response.meta.page,
    },
  };
}

async function fetchFeaturesInTiles(
  queryClient: ReturnType<typeof useQueryClient>,
  params: FeaturesInBboxParams,
  tiles: FeatureTile[],
  signal?: AbortSignal,
): Promise<TiledFeaturesResponse> {
  if (tiles.length === 0) {
    return fetchFeaturesInBbox(params, signal);
  }

  const requestedPageSize = params.page_size ?? 500;
  const geometryLightOnly = isGeometryLightOnly(params.kinds);
  const perTilePageSize = geometryLightOnly
    ? requestedPageSize
    : Math.min(
        requestedPageSize,
        Math.max(50, Math.ceil(requestedPageSize / tiles.length)),
      );

  // 바깥 viewport AbortSignal을 tile fetch에 그대로 넘기면 한 tile의 react-query
  // 취소(예: staleTime 만료 refetch dedupe)가 viewport 전체를 죽일 수 있다. 대신
  // tile별 child controller를 두고, viewport가 abort되면 모두 abort한다 — 그러면
  // allSettled가 reject를 모아 부분 성공을 유지할 수 있다.
  const controllers: AbortController[] = [];
  const onOuterAbort = () => {
    for (const controller of controllers) controller.abort();
  };

  // tiles.map은 동기 실행이라, 아래 listener 등록 시점에 controllers가 모두 채워져 있다.
  const tilePromises = tiles.map((tile) => {
    const controller = new AbortController();
    controllers.push(controller);
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
      queryFn: () =>
        geometryLightOnly
          ? fetchFeaturesInBboxPages(tileParams, controller.signal)
          : fetchFeaturesInBbox(tileParams, controller.signal),
      // 바깥 useQuery staleTime(30s)과 맞춘다 — 같은 viewport 키 캐시 수명과 tile
      // 캐시 수명이 어긋나면 한쪽만 만료돼 불필요한 부분 refetch가 난다.
      staleTime: 30_000,
    });
  });

  // viewport가 await 중 abort되면 in-flight tile fetch를 실제로 취소하도록 listener를
  // await *전에* 등록한다(#519 리뷰 S1: 이전엔 await 뒤라 child controller가 dead code였고
  // 단일 bbox 호출 대비 취소 회귀였다).
  if (signal) {
    if (signal.aborted) onOuterAbort();
    else signal.addEventListener("abort", onOuterAbort, { once: true });
  }

  const settled = await Promise.allSettled(tilePromises);
  if (signal) signal.removeEventListener("abort", onOuterAbort);

  const fulfilled = settled.filter(
    (result): result is PromiseFulfilledResult<FeaturesInBboxResponse> =>
      result.status === "fulfilled",
  );
  const failedTiles = settled.length - fulfilled.length;

  // 전부 실패면 의미 있는 빈 결과 대신 에러를 던져 호출부(react-query)가 isError로
  // 표면화하게 한다. 일부라도 성공하면 fulfilled tile만 병합해 결과를 유지한다.
  if (fulfilled.length === 0) {
    const firstRejected = settled.find(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    );
    throw firstRejected?.reason instanceof Error
      ? firstRejected.reason
      : new Error("모든 tile feature 조회에 실패했습니다.");
  }

  const items = new Map<string, FeatureSummary>();
  let truncated = false;
  for (const { value: response } of fulfilled) {
    for (const item of response.data.items) {
      items.set(item.feature_id, item);
    }
    // next_cursor가 남아 있으면 그 tile은 잘렸을(=일부 feature 누락) 가능성이 있다.
    // geometry-light 필터는 fetchFeaturesInBboxPages가 cursor를 이어 받아 완주한다.
    if ((response.meta.page?.next_cursor ?? null) !== null) {
      truncated = true;
    }
  }

  const partial = truncated || failedTiles > 0;
  const first = fulfilled[0]?.value;
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
      partial,
      failedTiles,
      totalTiles: tiles.length,
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
  // tile 분할은 한 번만 계산해 queryKey와 fetch에 함께 쓴다(이전엔 hook과 fetcher가
  // 각각 buildFeatureTiles를 호출해 동일 계산을 두 번 했다).
  const tiles = buildFeatureTiles(queryParams);
  const key = [
    "features",
    "viewport",
    tiles.map((tile) => tile.key).join("|"),
    params.kinds?.join(",") ?? "",
    params.includeGeometry ? "geometry" : "summary",
    params.page_size ?? 500,
  ] as const;
  return useQuery<TiledFeaturesResponse, Error>({
    queryKey: key,
    queryFn: ({ signal }) =>
      fetchFeaturesInTiles(queryClient, queryParams, tiles, signal),
    enabled: options?.enabled ?? true,
    placeholderData: keepPreviousData,
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
