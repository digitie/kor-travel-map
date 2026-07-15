/**
 * Backend API client (fetch wrapper).
 *
 * Next.js `/api/proxy` BFF를 통해 FastAPI(12701)에 접근한다. API 모듈의 DTO는 가능한 한 `npm run gen:types`로 생성한
 * `src/api/types.ts`의 OpenAPI 타입에서 파생한다.
 */

import type { components } from "./types";

const BASE_URL = "/api/proxy";

type ClientSchemas = components["schemas"];

export type HealthResponse = ClientSchemas["PublicHealthResponse"];
export type VersionResponse = ClientSchemas["PublicVersionResponse"];
export type ProblemDetail = ClientSchemas["ProblemDetail"];

class ApiClientError extends Error {
  constructor(
    message: string,
    public status: number,
    public path: string,
    public problem: ProblemDetail | null = null,
    public retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

function parseRetryAfterSeconds(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (value === null || !/^\d+$/.test(value)) {
    return null;
  }
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) ? seconds : null;
}

function parseProblemDetail(value: string): ProblemDetail | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "code" in parsed &&
      "detail" in parsed &&
      "status" in parsed &&
      typeof parsed.code === "string" &&
      typeof parsed.detail === "string" &&
      typeof parsed.status === "number"
    ) {
      return parsed as ProblemDetail;
    }
  } catch {
    // JSON이 아닌 upstream 오류는 원문을 일반 메시지로 보존한다.
  }
  return null;
}

async function apiClientErrorFromResponse(
  method: string,
  path: string,
  response: Response,
): Promise<ApiClientError> {
  const rawDetail = await response.text().catch(() => "");
  const problem = parseProblemDetail(rawDetail);
  const retryAfterSeconds = parseRetryAfterSeconds(response);
  const detail = problem?.detail ?? rawDetail;
  const retry =
    retryAfterSeconds === null ? "" : ` 재시도: ${retryAfterSeconds}초 후`;
  return new ApiClientError(
    `${method} ${path} 실패 (HTTP ${response.status})${detail ? ` ${detail}` : ""}${retry}`,
    response.status,
    path,
    problem,
    retryAfterSeconds,
  );
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

/**
 * 요청 옵션. `signal`은 react-query queryFn context의 `AbortSignal`을 받아 fetch에
 * 전달한다 — 후보 전환·필터 churn·언마운트로 query가 취소되면 in-flight 브라우저
 * fetch도 함께 중단해 host당 커넥션(브라우저 ~6) 포화로 인한 지연/무응답을 막는다
 * (kor-travel-concierge #111과 동일 계열).
 */
export interface RequestOptions {
  signal?: AbortSignal;
}

async function requestJson<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    body?: unknown;
    cache?: RequestCache;
    signal?: AbortSignal;
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
    credentials: "same-origin",
    cache: options.cache ?? "no-store",
    signal: options.signal,
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
  });
  if (!response.ok) {
    redirectToLoginOnAuthRequired(response.status);
    throw await apiClientErrorFromResponse(method, path, response);
  }
  return (await response.json()) as T;
}

export function getJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestJson<T>(path, { signal: options.signal });
}

export function postJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, { method: "POST", body, signal: options.signal });
}

export async function postFormData<T>(
  path: string,
  body: FormData,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store",
    signal: options.signal,
    body,
  });
  if (!response.ok) {
    redirectToLoginOnAuthRequired(response.status);
    throw await apiClientErrorFromResponse("POST", path, response);
  }
  return (await response.json()) as T;
}

export function putJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, { method: "PUT", body, signal: options.signal });
}

export function patchJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, { method: "PATCH", body, signal: options.signal });
}

export function deleteJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, { method: "DELETE", body, signal: options.signal });
}

/** `GET /health` — backend liveness probe. */
export function fetchHealth(options: RequestOptions = {}): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health", options);
}

/** `GET /version` — backend + lib version 정보. */
export function fetchVersion(options: RequestOptions = {}): Promise<VersionResponse> {
  return getJson<VersionResponse>("/version", options);
}

function redirectToLoginOnAuthRequired(status: number): void {
  if (status !== 401 || typeof window === "undefined") {
    return;
  }
  const current = `${window.location.pathname}${window.location.search}`;
  if (window.location.pathname === "/login") {
    return;
  }
  window.location.assign(`/login?next=${encodeURIComponent(current)}`);
}

export { ApiClientError, BASE_URL };
