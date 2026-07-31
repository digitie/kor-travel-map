/**
 * Backend API client (fetch wrapper).
 *
 * Next.js `/api/proxy` BFF를 통해 FastAPI(12701)에 접근한다. API 모듈의 DTO는 가능한 한 `npm run gen:types`로 생성한
 * `src/api/types.ts`의 OpenAPI 타입에서 파생한다.
 */

import { subscribeAdminLogout } from "@/lib/admin-auth-events";

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

const idempotencyFallback = new Map<string, string>();
const DOMAIN_IDEMPOTENCY_OPERATION_PREFIX = "admin.";

let subscribedDomainIdempotencyAuthBoundary = false;

function idempotencyStorageKey(operationKey: string): string {
  return `kor-travel-map:idempotency:${operationKey}`;
}

function readIdempotencyKey(operationKey: string): string | null {
  const storageKey = idempotencyStorageKey(operationKey);
  try {
    return (
      window.sessionStorage.getItem(storageKey) ??
      idempotencyFallback.get(storageKey) ??
      null
    );
  } catch {
    return idempotencyFallback.get(storageKey) ?? null;
  }
}

function writeIdempotencyKey(operationKey: string, value: string | null): void {
  const storageKey = idempotencyStorageKey(operationKey);
  if (value === null) {
    idempotencyFallback.delete(storageKey);
  } else {
    idempotencyFallback.set(storageKey, value);
  }
  try {
    if (value === null) {
      window.sessionStorage.removeItem(storageKey);
    } else {
      window.sessionStorage.setItem(storageKey, value);
    }
  } catch {
    // storage 차단 환경은 탭 수명 in-memory key로 동일 재시도를 보호한다.
  }
}

export interface FrozenIdempotencySubmission<T> {
  idempotencyKey: string;
  submission: T;
}

interface StoredFrozenIdempotencySubmission {
  version: 1;
  idempotency_key: string;
  submission: unknown;
}

function frozenIdempotencyStorageKey(operationKey: string): string {
  return idempotencyStorageKey(`${operationKey}:frozen-submission`);
}

function readFrozenIdempotencyValue(operationKey: string): string | null {
  const storageKey = frozenIdempotencyStorageKey(operationKey);
  try {
    return (
      window.sessionStorage.getItem(storageKey) ??
      idempotencyFallback.get(storageKey) ??
      null
    );
  } catch {
    return idempotencyFallback.get(storageKey) ?? null;
  }
}

function writeFrozenIdempotencyValue(
  operationKey: string,
  value: string | null,
): void {
  const storageKey = frozenIdempotencyStorageKey(operationKey);
  if (value === null) {
    idempotencyFallback.delete(storageKey);
  } else {
    idempotencyFallback.set(storageKey, value);
  }
  try {
    if (value === null) {
      window.sessionStorage.removeItem(storageKey);
    } else {
      window.sessionStorage.setItem(storageKey, value);
    }
  } catch {
    // storage 차단 환경은 탭 수명 in-memory submission으로 동일 재시도를 보호한다.
  }
}

export function readFrozenIdempotencySubmission<T>(
  operationKey: string,
): FrozenIdempotencySubmission<T> | null {
  const raw = readFrozenIdempotencyValue(operationKey);
  if (raw === null) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("저장된 idempotency 요청을 해석할 수 없습니다.");
  }
  if (
    typeof parsed !== "object" ||
    parsed === null ||
    (parsed as Partial<StoredFrozenIdempotencySubmission>).version !== 1 ||
    typeof (parsed as Partial<StoredFrozenIdempotencySubmission>)
      .idempotency_key !== "string" ||
    !("submission" in parsed)
  ) {
    throw new Error("저장된 idempotency 요청 형식이 올바르지 않습니다.");
  }
  const stored = parsed as StoredFrozenIdempotencySubmission;
  return {
    idempotencyKey: stored.idempotency_key,
    submission: stored.submission as T,
  };
}

export function clearIdempotencyKeys(operationPrefix: string): void {
  const storagePrefix = idempotencyStorageKey(operationPrefix);
  for (const key of idempotencyFallback.keys()) {
    if (key.startsWith(storagePrefix)) {
      idempotencyFallback.delete(key);
    }
  }
  try {
    for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = window.sessionStorage.key(index);
      if (key?.startsWith(storagePrefix)) {
        window.sessionStorage.removeItem(key);
      }
    }
  } catch {
    // storage 차단 환경은 위 in-memory key 제거만으로 충분하다.
  }
}

export function domainCommandSlot(
  operation: string,
  ...parts: Array<number | string>
): string {
  return [operation, ...parts.map((part) => encodeURIComponent(String(part)))].join(
    ":",
  );
}

function domainDraftSlotKey(operation: string): string {
  return `${operation}:draft-slot`;
}

export function domainCreateCommandSlot(operation: string): string {
  const draftSlotKey = domainDraftSlotKey(operation);
  const draftId = readIdempotencyKey(draftSlotKey) ?? globalThis.crypto.randomUUID();
  writeIdempotencyKey(draftSlotKey, draftId);
  return domainCommandSlot(operation, "draft", draftId);
}

export function clearDomainCreateCommandSlot(operation: string): void {
  writeIdempotencyKey(domainDraftSlotKey(operation), null);
}

function canonicalIdempotencyValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalIdempotencyValue);
  }
  if (typeof value !== "object" || value === null) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalIdempotencyValue(item)]),
  );
}

async function sha256Hex(value: BufferSource): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", value);
  return Array.from(new Uint8Array(digest), (item) =>
    item.toString(16).padStart(2, "0"),
  ).join("");
}

function blobArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") {
    return blob.arrayBuffer();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("error", () => {
      reject(reader.error ?? new Error("파일 내용을 읽을 수 없습니다."));
    });
    reader.addEventListener("load", () => {
      if (reader.result instanceof ArrayBuffer) {
        resolve(reader.result);
      } else {
        reject(new Error("파일 내용을 ArrayBuffer로 읽지 못했습니다."));
      }
    });
    reader.readAsArrayBuffer(blob);
  });
}

/** 민감한 request body를 storage key에 노출하지 않는 deterministic SHA-256 key. */
export async function idempotencyOperationKey(
  namespace: string,
  body: unknown,
): Promise<string> {
  const canonical = JSON.stringify(canonicalIdempotencyValue(body));
  return `${namespace}:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}

export interface FileIdempotencyFingerprint {
  filename: string;
  contentType: string | null;
  byteSize: number;
  contentSha256: string;
}

export async function fileIdempotencyFingerprint(
  file: File,
): Promise<FileIdempotencyFingerprint> {
  const content = await blobArrayBuffer(file);
  return {
    filename: file.name,
    contentType: file.type.trim().toLowerCase() || null,
    byteSize: file.size,
    contentSha256: await sha256Hex(new Uint8Array(content)),
  };
}

const UNCERTAIN_IDEMPOTENCY_ERROR_CODES = [
  "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
  "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN",
  "IDEMPOTENCY_RESULT_PENDING",
] as const;

function shouldClearIdempotencyKeyOnError(error: unknown): boolean {
  const problemDetails =
    error instanceof ApiClientError &&
    typeof error.problem?.details === "object" &&
    error.problem.details !== null
      ? (error.problem.details as Record<string, unknown>)
      : null;
  const confirmedRecordedFailure =
    problemDetails?.outcome_certainty === "confirmed" &&
    problemDetails.audit_status === "recorded";
  const explicitPreMutationFailure =
    error instanceof ApiClientError &&
    [
      "DAGSTER_SCHEDULE_STORAGE_UNAVAILABLE",
      "INVALID_SCHEDULE_COMMAND",
    ].includes(error.problem?.code ?? "");
  const uncertainConflict =
    error instanceof ApiClientError &&
    UNCERTAIN_IDEMPOTENCY_ERROR_CODES.includes(
      error.problem?.code as (typeof UNCERTAIN_IDEMPOTENCY_ERROR_CODES)[number],
    );
  const uncertainTransport =
    error instanceof ApiClientError &&
    (error.status >= 500 ||
      error.status === 408 ||
      error.status === 425 ||
      error.status === 429 ||
      error.status === 499);
  return (
    error instanceof ApiClientError &&
    (explicitPreMutationFailure ||
      (!uncertainConflict && (confirmedRecordedFailure || !uncertainTransport)))
  );
}

export async function withIdempotencyKey<T>(
  operationKey: string,
  operation: (idempotencyKey: string) => Promise<T>,
  options: {
    onRelease?: () => void;
    retainOnSuccess?: (result: T) => boolean;
  } = {},
): Promise<T> {
  const idempotencyKey =
    readIdempotencyKey(operationKey) ?? globalThis.crypto.randomUUID();
  writeIdempotencyKey(operationKey, idempotencyKey);
  try {
    const result = await operation(idempotencyKey);
    if (!options.retainOnSuccess?.(result)) {
      writeIdempotencyKey(operationKey, null);
      options.onRelease?.();
    }
    return result;
  } catch (error) {
    if (shouldClearIdempotencyKeyOnError(error)) {
      writeIdempotencyKey(operationKey, null);
      options.onRelease?.();
    }
    throw error;
  }
}

export class DomainIdempotencySubmissionMismatchError extends Error {
  constructor(slot: string) {
    super(
      `불명확한 ${slot} 요청과 다른 내용을 같은 command slot으로 재시도할 수 없습니다.`,
    );
    this.name = "DomainIdempotencySubmissionMismatchError";
  }
}

export async function withDomainIdempotencySubmission<TSubmission, TResult>(
  slot: string,
  requestedSubmission: TSubmission,
  operation: (
    submission: TSubmission,
    idempotencyKey: string,
  ) => Promise<TResult>,
  options: {
    onRelease?: () => void;
    retainOnSuccess?: (result: TResult) => boolean;
  } = {},
): Promise<TResult> {
  const fingerprint = await idempotencyOperationKey(
    `${slot}:submission`,
    requestedSubmission,
  );
  return withFrozenIdempotencySubmission(
    slot,
    fingerprint,
    (storedFingerprint, idempotencyKey) => {
      if (storedFingerprint !== fingerprint) {
        throw new DomainIdempotencySubmissionMismatchError(slot);
      }
      return operation(requestedSubmission, idempotencyKey);
    },
    options,
  );
}

export async function withDomainIdempotencyFingerprint<TResult>(
  slot: string,
  fingerprintPayload: unknown,
  request: (idempotencyKey: string) => Promise<TResult>,
  options: {
    onRelease?: () => void;
    retainOnSuccess?: (result: TResult) => boolean;
  } = {},
): Promise<TResult> {
  const fingerprint = await idempotencyOperationKey(
    `${slot}:submission`,
    fingerprintPayload,
  );
  return withFrozenIdempotencySubmission(
    slot,
    fingerprint,
    (storedFingerprint, idempotencyKey) => {
      if (storedFingerprint !== fingerprint) {
        throw new DomainIdempotencySubmissionMismatchError(slot);
      }
      return request(idempotencyKey);
    },
    options,
  );
}

export function clearDomainIdempotencyKeys(): void {
  clearIdempotencyKeys(DOMAIN_IDEMPOTENCY_OPERATION_PREFIX);
}

/**
 * 결과가 불명인 mutation의 UUID와 canonical 요청 전체를 한 원자적 storage 값으로
 * 고정한다. 다음 호출은 caller가 새 body를 넘겨도 저장된 endpoint/body를 그대로
 * 재전송하므로 response-loss 뒤 다른 schedule 조작으로 넘어갈 수 없다.
 */
export async function withFrozenIdempotencySubmission<TSubmission, TResult>(
  operationKey: string,
  requestedSubmission: TSubmission,
  operation: (
    submission: TSubmission,
    idempotencyKey: string,
  ) => Promise<TResult>,
  options: {
    onRelease?: () => void;
    retainOnSuccess?: (result: TResult) => boolean;
  } = {},
): Promise<TResult> {
  const frozen = readFrozenIdempotencySubmission<TSubmission>(operationKey) ?? {
    idempotencyKey: globalThis.crypto.randomUUID(),
    submission: requestedSubmission,
  };
  const stored: StoredFrozenIdempotencySubmission = {
    version: 1,
    idempotency_key: frozen.idempotencyKey,
    submission: frozen.submission,
  };
  writeFrozenIdempotencyValue(operationKey, JSON.stringify(stored));
  try {
    const result = await operation(frozen.submission, frozen.idempotencyKey);
    if (!options.retainOnSuccess?.(result)) {
      writeFrozenIdempotencyValue(operationKey, null);
      options.onRelease?.();
    }
    return result;
  } catch (error) {
    if (shouldClearIdempotencyKeyOnError(error)) {
      writeFrozenIdempotencyValue(operationKey, null);
      options.onRelease?.();
    }
    throw error;
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

export type QueryParamValue =
  string | number | boolean | Date | null | undefined;
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
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

async function requestJson<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    body?: unknown;
    cache?: RequestCache;
    headers?: Record<string, string>;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    method,
    headers: {
      Accept: "application/json",
      ...(options.body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
    credentials: "same-origin",
    cache: options.cache ?? "no-store",
    signal: options.signal,
    ...(options.body !== undefined
      ? { body: JSON.stringify(options.body) }
      : {}),
  });
  if (!response.ok) {
    redirectToLoginOnAuthRequired(response.status);
    throw await apiClientErrorFromResponse(method, path, response);
  }
  return (await response.json()) as T;
}

export function getJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, {
    headers: options.headers,
    signal: options.signal,
  });
}

export async function getJsonWithResponse<T>(
  path: string,
  options: RequestOptions = {},
): Promise<{ body: T; response: Response }> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "GET",
    headers: { Accept: "application/json", ...options.headers },
    credentials: "same-origin",
    cache: "no-store",
    signal: options.signal,
  });
  if (!response.ok) {
    redirectToLoginOnAuthRequired(response.status);
    throw await apiClientErrorFromResponse("GET", path, response);
  }
  return { body: (await response.json()) as T, response };
}

export function postJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    body,
    headers: options.headers,
    signal: options.signal,
  });
}

export async function postFormData<T>(
  path: string,
  body: FormData,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", ...options.headers },
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
  return requestJson<T>(path, {
    method: "PUT",
    body,
    headers: options.headers,
    signal: options.signal,
  });
}

export function patchJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, {
    method: "PATCH",
    body,
    headers: options.headers,
    signal: options.signal,
  });
}

export function deleteJson<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return requestJson<T>(path, {
    method: "DELETE",
    body,
    headers: options.headers,
    signal: options.signal,
  });
}

/** `GET /health` — backend liveness probe. */
export function fetchHealth(
  options: RequestOptions = {},
): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health", options);
}

/** `GET /version` — backend + lib version 정보. */
export function fetchVersion(
  options: RequestOptions = {},
): Promise<VersionResponse> {
  return getJson<VersionResponse>("/version", options);
}

function redirectToLoginOnAuthRequired(status: number): void {
  if (status !== 401 || typeof window === "undefined") {
    return;
  }
  clearDomainIdempotencyKeys();
  const current = `${window.location.pathname}${window.location.search}`;
  if (window.location.pathname === "/login") {
    return;
  }
  window.location.assign(`/login?next=${encodeURIComponent(current)}`);
}

function subscribeDomainIdempotencyAuthBoundary(): void {
  if (subscribedDomainIdempotencyAuthBoundary || typeof window === "undefined") {
    return;
  }
  subscribedDomainIdempotencyAuthBoundary = true;
  subscribeAdminLogout(clearDomainIdempotencyKeys);
}

subscribeDomainIdempotencyAuthBoundary();

export { ApiClientError, BASE_URL };
