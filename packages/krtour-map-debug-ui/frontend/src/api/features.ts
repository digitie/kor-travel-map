/**
 * `GET /features` — bbox 안 feature 경량 표현 (FastAPI features 라우터, PR#94).
 *
 * 응답 schema는 `FeaturesInBboxResponse` (backend Pydantic 모델과 1:1).
 * 좌표는 WGS84 (ADR-012). `kind`는 반복 파라미터로 다중 필터.
 */

import { useQuery } from "@tanstack/react-query";

import { BASE_URL, DebugUiApiError } from "./client";

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

export async function fetchFeaturesInBbox(
  params: FeaturesInBboxParams,
): Promise<FeaturesInBboxResponse> {
  const search = new URLSearchParams();
  search.set("min_lon", String(params.min_lon));
  search.set("min_lat", String(params.min_lat));
  search.set("max_lon", String(params.max_lon));
  search.set("max_lat", String(params.max_lat));
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  if (params.kinds) {
    for (const kind of params.kinds) {
      search.append("kind", kind);
    }
  }
  const url = `${BASE_URL}/features?${search.toString()}`;
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new DebugUiApiError(
      `GET /features 실패 (HTTP ${response.status})`,
      response.status,
      "/features",
    );
  }
  return (await response.json()) as FeaturesInBboxResponse;
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
}

export async function fetchFeatureDetail(featureId: string): Promise<FeatureDetail> {
  const url = `${BASE_URL}/features/${encodeURIComponent(featureId)}`;
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new DebugUiApiError(
      `GET /features/{id} 실패 (HTTP ${response.status})`,
      response.status,
      `/features/${featureId}`,
    );
  }
  return (await response.json()) as FeatureDetail;
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
