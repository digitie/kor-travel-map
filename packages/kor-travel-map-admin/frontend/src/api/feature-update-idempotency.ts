import { idempotencyOperationKey } from "./client";

type JsonObject = Record<string, unknown>;

function sortedStringArray(value: unknown): unknown {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    return value;
  }
  const strings = value as string[];
  return [...strings].sort((left, right) => left.localeCompare(right));
}

/** backend feature-update fingerprint와 같은 set 의미 배열을 정규화한다. */
export function canonicalFeatureUpdateIdempotencyBody<T>(body: T): T {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return body;
  }
  const source = body as JsonObject;
  const scopeSource = source.scope;
  const scope =
    typeof scopeSource === "object" &&
    scopeSource !== null &&
    !Array.isArray(scopeSource)
      ? (scopeSource as JsonObject)
      : null;
  const canonicalScope = scope
    ? {
        ...scope,
        ...(scope.type === "feature_ids"
          ? { feature_ids: sortedStringArray(scope.feature_ids) }
          : {}),
        ...(scope.type === "cache_target_keys"
          ? { target_keys: sortedStringArray(scope.target_keys) }
          : {}),
      }
    : scopeSource;
  return {
    ...source,
    providers: sortedStringArray(source.providers),
    dataset_keys: sortedStringArray(source.dataset_keys),
    scope: canonicalScope,
  } as T;
}

/** feature-update 생성 세 표면이 공유하는 semantic operation key. */
export function featureUpdateIdempotencyOperationKey<T>(
  namespace: string,
  body: T,
): Promise<string> {
  return idempotencyOperationKey(
    namespace,
    canonicalFeatureUpdateIdempotencyBody(body),
  );
}

export function featureUpdateCreationStatus(result: {
  idempotent_replay: boolean;
  reused_active_request: boolean;
}): string {
  if (result.idempotent_replay) {
    return "동일 요청 결과 재생";
  }
  if (result.reused_active_request) {
    return "기존 활성 요청 재사용";
  }
  return "새 요청 생성";
}
