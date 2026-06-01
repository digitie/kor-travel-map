/**
 * `/debug/geocoding/*` — kraddr-geo REST API v2 라우터 클라이언트 (PR#101).
 *
 * backend(/debug/geocoding/{health,reverse,reverse/raw,geocode,geocode/raw})를
 * 호출해 결과 Address/Coordinate를 표시한다. base_url 미설정/upstream 오류는
 * backend가 503/502로 매핑하므로 본 모듈은 status 코드별 에러 메시지만 정리.
 */

import { BASE_URL, DebugUiApiError } from "./client";

export interface GeocodingHealthResponse {
  base_url: string;
  reachable: boolean;
  upstream_status: number | null;
  detail: string | null;
}

/** `Address` DTO와 정합 (krtour.map.dto.Address). */
export interface AddressPayload {
  road: string | null;
  legal: string | null;
  admin: string | null;
  bjd_code: string | null;
  admin_dong_code: string | null;
  sigungu_code: string | null;
  sido_code: string | null;
  road_name_code: string | null;
  road_address_management_no: string | null;
  zipcode: string | null;
  sido_name: string | null;
  sigungu_name: string | null;
}

export interface CoordinatePayload {
  lon: string;
  lat: string;
}

export interface ReverseGeocodingResult {
  address: AddressPayload | null;
}

export interface GeocodeResult {
  coord: CoordinatePayload | null;
}

export type RegionLevel = "sido" | "sigungu" | "emd";

export interface RegionWithinRadiusItem {
  code: string;
  name: string | null;
  relation: string;
}

export interface RegionsWithinRadiusResult {
  center: {
    lon: number;
    lat: number;
  };
  radius_km: number;
  sido: RegionWithinRadiusItem[];
  sigungu: RegionWithinRadiusItem[];
  emd: RegionWithinRadiusItem[];
}

export interface ReverseGeocodingParams {
  lon: number;
  lat: number;
  type?: "both" | "road" | "parcel";
  zipcode?: boolean;
  radius_m?: number;
  max_distance_m?: number;
}

export interface GeocodeParams {
  address: string;
  type?: "road" | "parcel";
  refine?: boolean;
  fallback?: "off" | "local_only" | "api";
  min_confidence?: number;
}

export interface RegionsWithinRadiusParams {
  lon: number;
  lat: number;
  radius_km: number;
  levels?: RegionLevel[];
}

async function getJson<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    // 503(base_url 미설정), 502(upstream 오류) 등을 그대로 메시지화.
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? "";
    } catch {
      // ignore parse error.
    }
    throw new DebugUiApiError(
      `GET ${path} 실패 (HTTP ${response.status}${detail ? `: ${detail}` : ""})`,
      response.status,
      path,
    );
  }
  return (await response.json()) as T;
}

export function fetchGeocodingHealth(): Promise<GeocodingHealthResponse> {
  return getJson<GeocodingHealthResponse>("/debug/geocoding/health");
}

function _buildReverseQuery(p: ReverseGeocodingParams): string {
  const q = new URLSearchParams();
  q.set("lon", String(p.lon));
  q.set("lat", String(p.lat));
  if (p.type) q.set("type", p.type);
  if (p.zipcode !== undefined) q.set("zipcode", String(p.zipcode));
  if (p.radius_m !== undefined) q.set("radius_m", String(p.radius_m));
  if (p.max_distance_m !== undefined) q.set("max_distance_m", String(p.max_distance_m));
  return q.toString();
}

export function fetchReverse(p: ReverseGeocodingParams): Promise<ReverseGeocodingResult> {
  return getJson<ReverseGeocodingResult>(`/debug/geocoding/reverse?${_buildReverseQuery(p)}`);
}

export function fetchReverseRaw(p: ReverseGeocodingParams): Promise<Record<string, unknown>> {
  return getJson<Record<string, unknown>>(
    `/debug/geocoding/reverse/raw?${_buildReverseQuery(p)}`,
  );
}

function _buildGeocodeQuery(p: GeocodeParams): string {
  const q = new URLSearchParams();
  q.set("address", p.address);
  if (p.type) q.set("type", p.type);
  if (p.refine !== undefined) q.set("refine", String(p.refine));
  if (p.fallback) q.set("fallback", p.fallback);
  if (p.min_confidence !== undefined) q.set("min_confidence", String(p.min_confidence));
  return q.toString();
}

export function fetchGeocode(p: GeocodeParams): Promise<GeocodeResult> {
  return getJson<GeocodeResult>(`/debug/geocoding/geocode?${_buildGeocodeQuery(p)}`);
}

export function fetchGeocodeRaw(p: GeocodeParams): Promise<Record<string, unknown>> {
  return getJson<Record<string, unknown>>(
    `/debug/geocoding/geocode/raw?${_buildGeocodeQuery(p)}`,
  );
}

function _buildRegionsWithinRadiusQuery(p: RegionsWithinRadiusParams): string {
  const q = new URLSearchParams();
  q.set("lon", String(p.lon));
  q.set("lat", String(p.lat));
  q.set("radius_km", String(p.radius_km));
  if (p.levels) {
    for (const level of p.levels) {
      q.append("level", level);
    }
  }
  return q.toString();
}

export function fetchRegionsWithinRadius(
  p: RegionsWithinRadiusParams,
): Promise<RegionsWithinRadiusResult> {
  return getJson<RegionsWithinRadiusResult>(
    `/debug/geocoding/regions/within-radius?${_buildRegionsWithinRadiusQuery(p)}`,
  );
}

export function fetchRegionsWithinRadiusRaw(
  p: RegionsWithinRadiusParams,
): Promise<Record<string, unknown>> {
  return getJson<Record<string, unknown>>(
    `/debug/geocoding/regions/within-radius/raw?${_buildRegionsWithinRadiusQuery(p)}`,
  );
}
