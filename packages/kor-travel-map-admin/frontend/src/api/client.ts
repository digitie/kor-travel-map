/**
 * Backend API client (fetch wrapper).
 *
 * `NEXT_PUBLIC_KOR_TRAVEL_MAP_ADMIN_API` base URL을 사용해 FastAPI(12301)에
 * 접근. API 모듈의 DTO는 가능한 한 `npm run gen:types`로 생성한
 * `src/api/types.ts`의 OpenAPI 타입에서 파생한다.
 *
 * 인증/세션 헤더 없음 (ADR-005 + ADR-035 — 네트워크 계층 책임).
 */

import type { components } from "./types";
import { publicUrlEnv } from "./env";

const BASE_URL = publicUrlEnv(
  process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_ADMIN_API,
  "NEXT_PUBLIC_KOR_TRAVEL_MAP_ADMIN_API",
  "http://127.0.0.1:12301",
);

type ClientSchemas = components["schemas"];

export type HealthResponse = ClientSchemas["PublicHealthResponse"];
export type VersionResponse = ClientSchemas["PublicVersionResponse"];

class AdminApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public path: string,
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

export type QueryParamValue = string | number | boolean | Date | null | undefined;
export type QueryParams = Record<
  string,
  QueryParamValue | readonly QueryParamValue[]
>;

function buildQueryString(params: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, rawValue] of Object.entries(params)) {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      if (value === null || value === undefined) {
        continue;
      }
      search.append(
        key,
        value instanceof Date ? value.toISOString() : String(value),
      );
    }
  }
  return search.toString();
}

export function pathWithQuery(path: string, params: QueryParams): string {
  const query = buildQueryString(params);
  return query.length > 0 ? `${path}?${query}` : path;
}

async function requestJson<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    body?: unknown;
    cache?: RequestCache;
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    method,
    headers: {
      Accept: "application/json",
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    // ADR-005: 내부망 전용 — credentials 미포함.
    credentials: "omit",
    cache: options.cache ?? "no-store",
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new AdminApiError(
      `${method} ${path} 실패 (HTTP ${response.status})${detail ? ` ${detail}` : ""}`,
      response.status,
      path,
    );
  }
  return (await response.json()) as T;
}

export function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path);
}

export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "POST", body });
}

export async function postFormData<T>(
  path: string,
  body: FormData,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "omit",
    cache: "no-store",
    body,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new AdminApiError(
      `POST ${path} 실패 (HTTP ${response.status})${detail ? ` ${detail}` : ""}`,
      response.status,
      path,
    );
  }
  return (await response.json()) as T;
}

export function putJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PUT", body });
}

export function patchJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PATCH", body });
}

export function deleteJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "DELETE", body });
}

/** `GET /health` — backend liveness probe. */
export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}

/** `GET /version` — backend + lib version 정보. */
export function fetchVersion(): Promise<VersionResponse> {
  return getJson<VersionResponse>("/version");
}

export { AdminApiError, BASE_URL };
