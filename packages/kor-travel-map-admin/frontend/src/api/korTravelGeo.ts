import { publicUrlEnv } from "./env";

const KOR_TRAVEL_GEO_BASE_URL = publicUrlEnv(
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL,
  "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL",
  "http://127.0.0.1:12501",
);
const KOR_TRAVEL_GEO_API_KEY =
  process.env.NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY?.trim() ||
  process.env.NEXT_PUBLIC_VWORLD_API_KEY?.trim() ||
  "";

export interface KorTravelGeoPoint {
  x?: number | null;
  y?: number | null;
  lon?: number | null;
  lat?: number | null;
}

export interface KorTravelGeoAddress {
  admin_dong_code?: string | null;
  full?: string | null;
  legal_dong_code?: string | null;
  parcel_address?: string | null;
  postal_code?: string | null;
  road_address?: string | null;
  road_name?: string | null;
  road_name_code?: string | null;
}

export interface KorTravelGeoRegion {
  admin_dong?: string | null;
  bjd_cd?: string | null;
  eup_myeon_dong?: string | null;
  legal_dong?: string | null;
  sig_cd?: string | null;
  sido?: string | null;
  sigungu?: string | null;
}

export interface KorTravelGeoCandidate {
  address?: KorTravelGeoAddress | null;
  confidence?: number | null;
  distance_m?: number | null;
  match_kind?: string | null;
  point?: KorTravelGeoPoint | null;
  region?: KorTravelGeoRegion | null;
}

export interface KorTravelGeoResponse {
  candidates: KorTravelGeoCandidate[];
  status: string;
}

export interface KorTravelGeoCoord {
  lat: number;
  lon: number;
}

export interface KorTravelGeoCodes {
  admin_dong_code?: string;
  legal_dong_code?: string;
  road_name_code?: string;
  sido_code?: string;
  sigungu_code?: string;
}

async function postKorTravelGeo<T>(
  path: "/v2/geocode" | "/v2/reverse",
  body: Record<string, unknown>,
): Promise<T> {
  const url = new URL(path, KOR_TRAVEL_GEO_BASE_URL);
  if (KOR_TRAVEL_GEO_API_KEY) {
    url.searchParams.set("key", KOR_TRAVEL_GEO_API_KEY);
  }
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    credentials: "omit",
    cache: "no-store",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `kor-travel-geo ${path} 실패 (HTTP ${response.status})${detail ? ` ${detail}` : ""}`,
    );
  }
  return (await response.json()) as T;
}

export function reverseGeocode(
  coord: KorTravelGeoCoord,
): Promise<KorTravelGeoResponse> {
  return postKorTravelGeo<KorTravelGeoResponse>("/v2/reverse", {
    lon: coord.lon,
    lat: coord.lat,
    include_region: true,
    include_zipcode: true,
    radius_m: 100,
  });
}

export function geocodeAddress(
  address: string,
  type: "parcel" | "road" = "road",
): Promise<KorTravelGeoResponse> {
  return postKorTravelGeo<KorTravelGeoResponse>("/v2/geocode", {
    fallback: "api",
    ...(type === "road"
      ? { road_address: address }
      : { jibun_address: address }),
  });
}

export function korTravelGeoCandidateToCoord(
  candidate: KorTravelGeoCandidate | null | undefined,
): KorTravelGeoCoord | null {
  const point = candidate?.point;
  const lon = point?.lon ?? point?.x;
  const lat = point?.lat ?? point?.y;
  if (typeof lon !== "number" || typeof lat !== "number") {
    return null;
  }
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return null;
  }
  return { lon, lat };
}

export function korTravelGeoCodesFromCandidate(
  candidate: KorTravelGeoCandidate | null | undefined,
): KorTravelGeoCodes {
  const address = candidate?.address;
  const region = candidate?.region;
  const legalDongCode = normalizeCode(
    address?.legal_dong_code ?? region?.bjd_cd,
  );
  const sigunguCode = normalizeCode(
    region?.sig_cd ?? legalDongCode?.slice(0, 5),
  );
  const sidoCode = normalizeCode(sigunguCode?.slice(0, 2));
  return compactRecord({
    admin_dong_code: normalizeCode(address?.admin_dong_code),
    legal_dong_code: legalDongCode,
    road_name_code: normalizeCode(address?.road_name_code),
    sido_code: sidoCode,
    sigungu_code: sigunguCode,
  });
}

export function korTravelGeoCandidateToAddressRecord(
  candidate: KorTravelGeoCandidate | null | undefined,
): Record<string, unknown> {
  const address = candidate?.address;
  const region = candidate?.region;
  return compactRecord({
    admin: firstText(region?.admin_dong, region?.eup_myeon_dong),
    bjd_code: normalizeCode(address?.legal_dong_code ?? region?.bjd_cd),
    legal: firstText(address?.parcel_address, regionName(region)),
    road: firstText(address?.road_address, address?.road_name),
    road_address_management_no: undefined,
    road_name_code: normalizeCode(address?.road_name_code),
    sigungu_code: normalizeCode(
      region?.sig_cd ?? address?.legal_dong_code?.slice(0, 5),
    ),
    sido_code: normalizeCode(region?.sig_cd?.slice(0, 2)),
    sido_name: textOrUndefined(region?.sido),
    sigungu_name: textOrUndefined(region?.sigungu),
    postal_code: normalizeCode(address?.postal_code),
  });
}

function compactRecord<T extends Record<string, unknown>>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => {
      if (item === null || item === undefined) return false;
      if (typeof item === "string" && item.trim().length === 0) return false;
      return true;
    }),
  ) as Partial<T>;
}

function firstText(
  ...values: Array<string | null | undefined>
): string | undefined {
  return values.map(textOrUndefined).find((value) => value !== undefined);
}

function normalizeCode(value: string | null | undefined): string | undefined {
  const text = textOrUndefined(value);
  return text?.replace(/\D/g, "") || undefined;
}

function regionName(region: KorTravelGeoRegion | null | undefined): string | undefined {
  return firstText(
    [region?.sido, region?.sigungu, region?.legal_dong]
      .map(textOrUndefined)
      .filter((value) => value !== undefined)
      .join(" "),
  );
}

function textOrUndefined(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : undefined;
}

export { KOR_TRAVEL_GEO_BASE_URL };
