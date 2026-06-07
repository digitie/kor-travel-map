/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
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

export type FeatureDetail = FeatureSchemas["FeatureDetailResponse"];
type FeatureDetailEnvelopeResponse =
  FeatureSchemas["FeatureDetailEnvelopeResponse"];
export type FeatureWeatherResponse = FeatureSchemas["FeatureWeatherResponse"];
export type WeatherCardData = FeatureSchemas["WeatherCardData"];
export type WeatherMetric = FeatureSchemas["WeatherMetricOut"];

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

async function fetchFeatureWeather(
  featureId: string,
  params: { asof?: string | Date | null } = {},
): Promise<FeatureWeatherResponse> {
  return getJson<FeatureWeatherResponse>(
    pathWithQuery(`/features/${encodeURIComponent(featureId)}/weather`, {
      asof: params.asof,
    }),
  );
}

export function useFeatureWeather(
  featureId: string | null,
  params: { asof?: string | Date | null } = {},
) {
  return useQuery<FeatureWeatherResponse, Error>({
    queryKey: ["feature", featureId, "weather", params.asof ?? null] as const,
    queryFn: () => fetchFeatureWeather(featureId as string, params),
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

type AdminFeaturesListQuery = NonNullable<
  paths["/admin/features"]["get"]["parameters"]["query"]
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
