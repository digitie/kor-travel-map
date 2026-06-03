/**
 * Backend API client (fetch wrapper).
 *
 * `NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API` base URL을 사용해 FastAPI(9011)에
 * 접근. 응답 schema는 backend Pydantic 모델(`HealthResponse`, `VersionResponse`)
 * 과 일치. PR#36에서는 수동 type 정의 — 향후 `npm run gen:types`로
 * openapi.json에서 자동 생성된 `src/api/types.ts`로 대체 예정.
 *
 * 인증/세션 헤더 없음 (ADR-005 + ADR-035 — 네트워크 계층 책임).
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API ?? "http://127.0.0.1:9011";

export interface HealthResponse {
  status: string;
  service: string;
}

export interface VersionResponse {
  debug_ui: string;
  krtour_map: string;
}

class DebugUiApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public path: string,
  ) {
    super(message);
    this.name = "DebugUiApiError";
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
    throw new DebugUiApiError(
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

export function putJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PUT", body });
}

export function patchJson<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PATCH", body });
}

export function deleteJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { method: "DELETE" });
}

/** `GET /debug/health` — backend liveness probe (PR#35). */
export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/debug/health");
}

/** `GET /debug/version` — backend + lib version 정보 (PR#35). */
export function fetchVersion(): Promise<VersionResponse> {
  return getJson<VersionResponse>("/debug/version");
}

export { BASE_URL, DebugUiApiError };
