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

async function getJson<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    // ADR-005: 내부망 전용 — credentials 미포함.
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new DebugUiApiError(
      `GET ${path} 실패 (HTTP ${response.status})`,
      response.status,
      path,
    );
  }
  return (await response.json()) as T;
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
