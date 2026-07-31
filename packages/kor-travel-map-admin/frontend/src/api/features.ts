/**
 * admin Feature 지도·상세·변경 요청용 query/mutation 계약.
 * 좌표는 WGS84(ADR-012), 반복 필터는 OpenAPI 배열 계약을 그대로 사용한다.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  clearDomainCreateCommandSlot,
  deleteJson,
  domainCommandSlot,
  domainCreateCommandSlot,
  getJson,
  getJsonWithResponse,
  patchJson,
  pathWithQuery,
  postJson,
  withDomainIdempotencySubmission,
} from "./client";
import type { components, paths } from "./types";

type FeatureSchemas = components["schemas"];

export type FeatureSummary = FeatureSchemas["FeatureSummary"];
export type AdminFeatureMapItem = FeatureSchemas["AdminFeatureMapItem"];
type AdminFeaturesInBoundsResponse =
  FeatureSchemas["AdminFeaturesInBoundsResponse"];

export const FEATURE_CLUSTER_MAX_ZOOM = 13;



// ── 저zoom region 클러스터 (`GET /v1/features/in-bounds`, zoom 유도) ─────────────
//
// zoom ≤13에선 개별 feature를 tile로 대량 조회(4코어 박스 포화)하지 않고, 서버가
// 행정구역 단위로 rollup한 클러스터(region code별 count + 평균 좌표) 몇 행만 받는다.
// bbox GIST 인덱스만 쓰는 집계라 전국 뷰가 1M feature fetch 없이 즉시 로드된다(#649).
// include_geometry는 클러스터 응답에서 무시되므로 보내지 않는다.
export interface FeatureClustersParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  kinds?: string[];
  provider?: string[];
  zoom: number;
}

export const ADMIN_FEATURE_STATUSES = [
  "draft",
  "active",
  "inactive",
  "hidden",
  "broken",
] as const satisfies readonly AdminFeatureMapItem["status"][];
export type AdminFeatureStatus = AdminFeatureMapItem["status"];

export interface AdminFeaturesInBoundsParams extends FeatureClustersParams {
  statuses?: AdminFeatureStatus[];
  includeGeometry?: boolean;
}

export function adminFeatureRequestZoom(zoom: number): number {
  return Math.floor(zoom);
}

export function isAdminFeatureClusterZoom(zoom: number): boolean {
  return adminFeatureRequestZoom(zoom) <= FEATURE_CLUSTER_MAX_ZOOM;
}

export function adminFeaturesInBoundsPath(
  params: AdminFeaturesInBoundsParams,
  options: { clustered: boolean },
) {
  return pathWithQuery("/v1/admin/features/in-bounds", {
    min_lon: params.min_lon,
    min_lat: params.min_lat,
    max_lon: params.max_lon,
    max_lat: params.max_lat,
    kind: params.kinds,
    provider: params.provider,
    status: params.statuses,
    // zoom은 cluster/items 모드 공통으로 항상 전송한다(계약 대칭 + 서버 관측).
    // items 모드에서 zoom을 생략하면 소비자(예: live acceptance의 in-bounds
    // predicate)가 요청의 zoom 문맥을 알 수 없다 — cluster 모드에서만 보내던
    // 기존 비대칭은 #779의 잔재(리뷰 확인: 서버는 items에서도 zoom 수용).
    zoom: adminFeatureRequestZoom(params.zoom),
    max_items: 2000,
    include_geometry: options.clustered ? undefined : params.includeGeometry,
  });
}

async function fetchAdminFeaturesInBounds(
  params: AdminFeaturesInBoundsParams,
  options: { clustered: boolean },
  signal?: AbortSignal,
): Promise<AdminFeaturesInBoundsResponse> {
  return getJson<AdminFeaturesInBoundsResponse>(
    adminFeaturesInBoundsPath(params, options),
    { signal },
  );
}

export function adminFeaturesInBboxQueryKey(
  params: AdminFeaturesInBoundsParams,
  options: { clustered: boolean },
) {
  return [
    "admin-features",
    options.clustered ? "clusters" : "items",
    params.min_lon,
    params.min_lat,
    params.max_lon,
    params.max_lat,
    adminFeatureRequestZoom(params.zoom),
    params.kinds ?? [],
    params.provider ?? [],
    params.statuses ?? [],
    options.clustered ? false : (params.includeGeometry ?? false),
  ] as const;
}

export function useAdminFeaturesInBbox(
  params: AdminFeaturesInBoundsParams,
  options?: { enabled?: boolean },
) {
  const key = adminFeaturesInBboxQueryKey(params, { clustered: false });
  return useQuery<AdminFeaturesInBoundsResponse, Error>({
    queryKey: key,
    queryFn: ({ signal }) =>
      fetchAdminFeaturesInBounds(params, { clustered: false }, signal),
    enabled: options?.enabled ?? true,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useAdminFeatureClustersInBbox(
  params: AdminFeaturesInBoundsParams,
  options?: { enabled?: boolean },
) {
  const key = adminFeaturesInBboxQueryKey(params, { clustered: true });
  return useQuery<AdminFeaturesInBoundsResponse, Error>({
    queryKey: key,
    queryFn: ({ signal }) =>
      fetchAdminFeaturesInBounds(params, { clustered: true }, signal),
    enabled: options?.enabled ?? true,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}


// ── feature 단건 상세 (`GET /v1/features/{feature_id}`) ────────────────────────

export type FeatureDetail = FeatureSchemas["FeatureDetailResponse"];
export type FeatureWeatherResponse = FeatureSchemas["FeatureWeatherResponse"];
export type WeatherCardData = FeatureSchemas["WeatherCardData"];
export type WeatherMetric = FeatureSchemas["WeatherMetricOut"];
export type FeaturePriceResponse = FeatureSchemas["FeaturePriceResponse"];
export type PriceCardData = FeatureSchemas["PriceCardData"];
export type PricePoint = FeatureSchemas["PricePointOut"];
export type AreaContainedFeaturesResponse =
  FeatureSchemas["AreaContainedFeaturesResponse"];
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


async function fetchAdminFeatureWeather(
  featureId: string,
  params: { asof?: string | Date | null } = {},
  signal?: AbortSignal,
): Promise<FeatureWeatherResponse> {
  return getJson<FeatureWeatherResponse>(
    pathWithQuery(`/v1/admin/features/${encodeURIComponent(featureId)}/weather`, {
      asof: params.asof,
    }),
    { signal },
  );
}

export function useAdminFeatureWeather(
  featureId: string | null,
  params: { asof?: string | Date | null } = {},
) {
  return useQuery<FeatureWeatherResponse, Error>({
    queryKey: ["admin-feature-card", featureId, "weather", params.asof ?? null] as const,
    queryFn: ({ signal }) =>
      fetchAdminFeatureWeather(featureId as string, params, signal),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

async function fetchAdminFeaturePrice(
  featureId: string,
  params: { asof?: string | Date | null; historyLimit?: number } = {},
  signal?: AbortSignal,
): Promise<FeaturePriceResponse> {
  return getJson<FeaturePriceResponse>(
    pathWithQuery(`/v1/admin/features/${encodeURIComponent(featureId)}/price`, {
      asof: params.asof,
      history_limit: params.historyLimit,
    }),
    { signal },
  );
}

export function useAdminFeaturePrice(
  featureId: string | null,
  params: { asof?: string | Date | null; historyLimit?: number } = {},
) {
  return useQuery<FeaturePriceResponse, Error>({
    queryKey: [
      "admin-feature-card",
      featureId,
      "price",
      params.asof ?? null,
      params.historyLimit ?? null,
    ] as const,
    queryFn: ({ signal }) =>
      fetchAdminFeaturePrice(featureId as string, params, signal),
    enabled: featureId !== null && featureId.length > 0,
    staleTime: 60_000,
  });
}

async function fetchAreaContainedFeatures(
  featureId: string,
  params: { pageSize?: number; kinds?: string[] } = {},
  signal?: AbortSignal,
): Promise<AreaContainedFeaturesResponse> {
  return getJson<AreaContainedFeaturesResponse>(
    pathWithQuery(
      `/v1/features/${encodeURIComponent(featureId)}/contained-features`,
      {
        page_size: params.pageSize,
        kind: params.kinds,
      },
    ),
    { signal },
  );
}

export function useAreaContainedFeatures(
  featureId: string | null,
  params: { pageSize?: number; kinds?: string[] } = {},
  options?: { enabled?: boolean },
) {
  return useQuery<AreaContainedFeaturesResponse, Error>({
    queryKey: [
      "feature",
      featureId,
      "contained-features",
      params.pageSize ?? null,
      params.kinds?.join(",") ?? "",
    ] as const,
    queryFn: ({ signal }) =>
      fetchAreaContainedFeatures(featureId as string, params, signal),
    enabled:
      (options?.enabled ?? true) &&
      featureId !== null &&
      featureId.length > 0,
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
export interface CorrectionBasis {
  detail: AdminFeatureDetailResponse;
  entityTag: string;
  featureId: string;
  rowRevision: number;
}
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

const CORRECTION_BASIS_FETCH_ATTEMPTS = 3;

export async function fetchAdminFeatureCorrectionBasis(
  featureId: string,
  signal?: AbortSignal,
): Promise<CorrectionBasis> {
  const revisionPath =
    `/v1/admin/features/${encodeURIComponent(featureId)}/revision`;
  for (let attempt = 0; attempt < CORRECTION_BASIS_FETCH_ATTEMPTS; attempt += 1) {
    const { body: revision, response } = await getJsonWithResponse<
      FeatureSchemas["AdminFeatureRevisionResponse"]
    >(revisionPath, { signal });
    const entityTag = response.headers.get("ETag");
    if (entityTag === null) {
      throw new Error(`GET ${revisionPath} 응답에 ETag가 없습니다.`);
    }
    if (revision.data.feature_id !== featureId) {
      throw new Error(`GET ${revisionPath} 응답의 feature_id가 다릅니다.`);
    }

    const detail = await fetchAdminFeatureDetail(featureId, signal);
    const feature = detail.data.feature;
    if (
      feature.feature_id === featureId &&
      feature.row_revision === revision.data.row_revision
    ) {
      return {
        detail,
        entityTag,
        featureId,
        rowRevision: revision.data.row_revision,
      };
    }
  }
  throw new Error(
    `${featureId}의 revision과 상세가 ${CORRECTION_BASIS_FETCH_ATTEMPTS}회 연속 일치하지 않았습니다.`,
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

export function useAdminFeatureCorrectionBasis(featureId: string | null) {
  return useQuery<CorrectionBasis, Error>({
    queryKey: ["admin-feature-correction-basis", featureId] as const,
    queryFn: ({ signal }) =>
      fetchAdminFeatureCorrectionBasis(featureId as string, signal),
    enabled: featureId !== null && featureId.length > 0,
    gcTime: 0,
    retry: false,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
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
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.feature.deactivate", featureId),
    { featureId, body },
    (submission, idempotencyKey) =>
      postJson<AdminFeatureDeactivateResponse>(
        `/v1/admin/features/${encodeURIComponent(
          submission.featureId,
        )}/deactivate`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
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
  const operation = "admin.feature.create";
  return withDomainIdempotencySubmission(
    domainCreateCommandSlot(operation),
    body,
    (submission, idempotencyKey) =>
      postJson<AdminFeatureChangeResponse>("/v1/admin/features", submission, {
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    { onRelease: () => clearDomainCreateCommandSlot(operation) },
  );
}

export function patchAdminFeature(
  featureId: string,
  entityTag: string,
  body: AdminFeaturePatchRequest,
): Promise<AdminFeatureChangeResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.feature.patch", featureId),
    { featureId, entityTag, body },
    (submission, idempotencyKey) =>
      patchJson<AdminFeatureChangeResponse>(
        `/v1/admin/features/${encodeURIComponent(submission.featureId)}`,
        submission.body,
        {
          headers: {
            "Idempotency-Key": idempotencyKey,
            "If-Match": submission.entityTag,
          },
        },
      ),
  );
}

export function deleteAdminFeature(
  featureId: string,
  entityTag: string,
  body: AdminFeatureDeleteRequest,
): Promise<AdminFeatureChangeResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.feature.delete", featureId),
    { featureId, entityTag, body },
    (submission, idempotencyKey) =>
      deleteJson<AdminFeatureChangeResponse>(
        `/v1/admin/features/${encodeURIComponent(submission.featureId)}`,
        submission.body,
        {
          headers: {
            "Idempotency-Key": idempotencyKey,
            "If-Match": submission.entityTag,
          },
        },
      ),
  );
}

function approveAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.feature-change.approve", requestId),
    { requestId, body },
    (submission, idempotencyKey) =>
      postJson<AdminFeatureChangeResponse>(
        `/v1/admin/features/change-requests/${encodeURIComponent(
          submission.requestId,
        )}/approve`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
  );
}

function rejectAdminFeatureChangeRequest(
  requestId: string,
  body: AdminFeatureReviewActionRequest,
): Promise<AdminFeatureChangeResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.feature-change.reject", requestId),
    { requestId, body },
    (submission, idempotencyKey) =>
      postJson<AdminFeatureChangeResponse>(
        `/v1/admin/features/change-requests/${encodeURIComponent(
          submission.requestId,
        )}/reject`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
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
    {
      featureId: string;
      entityTag: string;
      body: AdminFeaturePatchRequest;
    }
  >({
    mutationFn: ({ featureId, entityTag, body }) =>
      patchAdminFeature(featureId, entityTag, body),
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
    {
      featureId: string;
      entityTag: string;
      body: AdminFeatureDeleteRequest;
    }
  >({
    mutationFn: ({ featureId, entityTag, body }) =>
      deleteAdminFeature(featureId, entityTag, body),
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
