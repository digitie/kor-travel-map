/**
 * TanStack Query hooks (ADR-037).
 *
 * 모든 backend GET 라우터는 `useQuery` 래퍼로 노출. mutation(POST/PATCH)은
 * `useMutation` + `queryClient.invalidateQueries`로 캐시 무효화.
 *
 * staleTime / refetchOnWindowFocus 기본은 ``QueryClientProvider``에서 잡고,
 * 라우터별 override는 본 모듈에서.
 */

import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  fetchHealth,
  fetchVersion,
  type HealthResponse,
  type VersionResponse,
} from "./client";

/** queryKey 컨벤션 — 첫 element는 도메인, 나머지는 파라미터. */
export const queryKeys = {
  health: () => ["debug", "health"] as const,
  version: () => ["debug", "version"] as const,
} as const;

type HealthQueryKey = ReturnType<typeof queryKeys.health>;
type VersionQueryKey = ReturnType<typeof queryKeys.version>;

/** `GET /health`. 5초마다 자동 refetch. */
export function useHealth(
  options?: Omit<
    UseQueryOptions<HealthResponse, Error, HealthResponse, HealthQueryKey>,
    "queryKey" | "queryFn"
  >,
) {
  return useQuery<HealthResponse, Error, HealthResponse, HealthQueryKey>({
    queryKey: queryKeys.health(),
    queryFn: ({ signal }) => fetchHealth({ signal }),
    refetchInterval: 5000,
    staleTime: 4000,
    ...options,
  });
}

/** `GET /version`. 버전 정보는 자주 변경되지 않음 — staleTime 1분. */
export function useVersion(
  options?: Omit<
    UseQueryOptions<VersionResponse, Error, VersionResponse, VersionQueryKey>,
    "queryKey" | "queryFn"
  >,
) {
  return useQuery<VersionResponse, Error, VersionResponse, VersionQueryKey>({
    queryKey: queryKeys.version(),
    queryFn: ({ signal }) => fetchVersion({ signal }),
    staleTime: 60_000,
    ...options,
  });
}
