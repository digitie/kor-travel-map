// Next App Router 런타임 오류 복구 헬퍼 (geo PR #391 / T-278 동일 반영).
// chunk/RSC/network 계열 런타임 오류는 같은 pathname에서 1회 hard reload로 복구를
// 시도한다. sessionStorage flag로 무한 reload를 막는다.

const ERROR_RECOVERY_RELOAD_PREFIX = "kortravelmap.admin.error-reload";

const RECOVERABLE_PATTERNS = [
  "chunkloaderror",
  "loading chunk",
  "loading css chunk",
  "failed to fetch dynamically imported module",
  "importing a module script failed",
  "error loading dynamically imported module",
  "_rsc",
  "server component",
  "rsc payload",
  "networkerror when attempting to fetch resource",
  "load failed",
];

export function errorRecoveryMessage(error: Error & { digest?: string }): string {
  const parts = [error.name, error.message, error.digest, error.stack].filter(Boolean);
  return parts.join("\n");
}

export function isLikelyRecoverableNextRuntimeError(
  error: Error & { digest?: string },
): boolean {
  const message = errorRecoveryMessage(error).toLowerCase();
  return RECOVERABLE_PATTERNS.some((pattern) => message.includes(pattern));
}

export function errorReloadStorageKey(pathname: string): string {
  return `${ERROR_RECOVERY_RELOAD_PREFIX}:${pathname}`;
}
