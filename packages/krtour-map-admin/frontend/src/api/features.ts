/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";

export interface FeatureSummary {
  feature_id: string;
  kind: string;
  name: string;
  category: string;
  lon: number | null;
  lat: number | null;
  marker_icon: string | null;
  marker_color: string | null;
  status: string;
}

export interface FeaturesInBboxResponse {
  count: number;
  items: FeatureSummary[];
}

export interface FeaturesInBboxParams {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  kinds?: string[];
  limit?: number;
}

async function fetchFeaturesInBbox(
  params: FeaturesInBboxParams,
): Promise<FeaturesInBboxResponse> {
  return getJson<FeaturesInBboxResponse>(
    pathWithQuery("/features", {
      min_lon: params.min_lon,
      min_lat: params.min_lat,
      max_lon: params.max_lon,
      max_lat: params.max_lat,
      limit: params.limit,
      kind: params.kinds,
    }),
  );
}

/**
 * react-query hook — bbox 변화에 따라 자동 refetch. 좌표는 소수 4자리로 양자화해
 * (~11m) 미세 viewport 변동에 의한 과도한 호출을 방지.
 */
export function useFeaturesInBbox(
  params: FeaturesInBboxParams,
  options?: { enabled?: boolean },
) {
  const q4 = (n: number) => Number(n.toFixed(4));
  const key = [
    "features",
    q4(params.min_lon),
    q4(params.min_lat),
    q4(params.max_lon),
    q4(params.max_lat),
    params.kinds?.join(",") ?? "",
    params.limit ?? 1000,
  ] as const;
  return useQuery({
    queryKey: key,
    queryFn: () => fetchFeaturesInBbox(params),
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
  });
}

// ── feature 단건 상세 (`GET /features/{feature_id}`) ────────────────────────

export interface FeatureDetail {
  feature_id: string;
  kind: string;
  name: string;
  category: string;
  lon: number | null;
  lat: number | null;
  coord_5179_srid: number | null;
  address: Record<string, unknown>;
  detail: Record<string, unknown>;
  urls: Record<string, unknown>;
  legal_dong_code: string | null;
  sido_code: string | null;
  sigungu_code: string | null;
  marker_icon: string | null;
  marker_color: string | null;
  status: string;
  parent_feature_id: string | null;
  sibling_group_id: string | null;
  updated_at: string;
}

interface FeatureDetailEnvelopeResponse {
  data: FeatureDetail;
  meta: {
    duration_ms: number;
  };
}

async function fetchFeatureDetail(featureId: string): Promise<FeatureDetail> {
  const body = await getJson<FeatureDetailEnvelopeResponse>(
    `/features/${encodeURIComponent(featureId)}`,
  );
  return body.data;
}

/** react-query hook — `selectedFeatureId` 변경 시 자동 fetch. */
export function useFeatureDetail(featureId: string | null) {
  return useQuery({
    queryKey: ["feature", featureId] as const,
    queryFn: () => fetchFeatureDetail(featureId as string),
    enabled: featureId !== null && featureId.length > 0,
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

// ── admin feature 목록/비활성화 (`/admin/features`) ───────────────────────

export type AdminFeatureSort =
  | "name"
  | "updated_at"
  | "created_at"
  | "kind"
  | "status"
  | "provider"
  | "issue_count";

export type SortOrder = "asc" | "desc";

export interface AdminFeatureIssue {
  violation_key?: string | null;
  violation_type?: string | null;
  severity?: string | null;
  message?: string | null;
  detected_at?: string | null;
}

export interface AdminFeatureRecord {
  feature_id: string;
  kind: string;
  name: string;
  category: string;
  status: string;
  lon: number | null;
  lat: number | null;
  address_label: string;
  primary_provider: string | null;
  primary_dataset_key: string | null;
  issue_count: number;
  issues: AdminFeatureIssue[];
  created_at: string;
  updated_at: string;
}

export interface AdminFeaturesListResponse {
  data: {
    items: AdminFeatureRecord[];
    next_cursor: string | null;
  };
  meta: {
    count: number;
    page_size: number;
    sort: AdminFeatureSort;
    order: SortOrder;
    duration_ms: number;
  };
}

export interface AdminFeaturesListParams {
  q?: string;
  kind?: string[];
  category?: string[];
  status?: string[];
  provider?: string[];
  dataset_key?: string[];
  has_coord?: boolean;
  has_issue?: boolean;
  issue_type?: string[];
  updated_from?: string | Date;
  updated_to?: string | Date;
  page_size?: number;
  cursor?: string;
  sort?: AdminFeatureSort;
  order?: SortOrder;
}

export interface AdminFeatureDeactivateRequest {
  reason: string;
  operator?: string | null;
  prevent_provider_reactivation?: boolean;
}

export interface AdminFeatureOverride {
  override_key: string;
  feature_id: string;
  field_path: string;
  override_value: unknown;
  prevent_provider_reactivation: boolean;
  reason: string | null;
  created_by: string | null;
  created_at: string;
}

export interface AdminFeatureDeactivateResponse {
  data: {
    feature_id: string;
    previous_status: string;
    status: string;
    override_created: boolean;
    override: AdminFeatureOverride | null;
  };
  meta: {
    duration_ms: number;
  };
}

function fetchAdminFeatures(
  params: AdminFeaturesListParams = {},
): Promise<AdminFeaturesListResponse> {
  return getJson<AdminFeaturesListResponse>(
    pathWithQuery("/admin/features", {
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
  );
}

function deactivateAdminFeature(
  featureId: string,
  body: AdminFeatureDeactivateRequest,
): Promise<AdminFeatureDeactivateResponse> {
  return postJson<AdminFeatureDeactivateResponse>(
    `/admin/features/${encodeURIComponent(featureId)}/deactivate`,
    body,
  );
}

export function useAdminFeatures(params: AdminFeaturesListParams = {}) {
  return useQuery<AdminFeaturesListResponse, Error>({
    queryKey: ["admin-features", params],
    queryFn: () => fetchAdminFeatures(params),
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
    },
  });
}
