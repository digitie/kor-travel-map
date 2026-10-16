/**
 * `/v1/ops/geo-releases/*` — geo 릴리스 재지오코딩 계획(ADR-109 결정 8, T-GR-06).
 *
 * 감지(`detect`)는 Dagster 센서와 같은 core 함수라 멱등이고, skip은 대기·실패 항목만 전이한다
 * (재시도해도 409로 끝난다). replan은 호출마다 새 계획을 만들므로 UI가 확인을 받는다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, postJson } from "./client";
import type { components } from "./types";

type Schemas = components["schemas"];

export type GeoReleaseListResponse = Schemas["GeoReleaseListResponse"];
export type GeoReleaseDetailResponse = Schemas["GeoReleaseDetailResponse"];
export type GeoReleaseDetectResponse = Schemas["GeoReleaseDetectResponse"];
export type GeoReleasePlanRecord = Schemas["GeoReleasePlanRecord"];
export type GeoReleaseItemRecord = Schemas["GeoReleaseItemRecord"];
export type GeoCoverageRecord = Schemas["GeoCoverageRecord"];
export type GeoDatasetRecord = Schemas["GeoDatasetRecord"];

const ROOT = "/v1/ops/geo-releases";
const KEY = ["ops", "geo-releases"] as const;

export function useGeoReleases() {
  return useQuery<GeoReleaseListResponse, Error>({
    queryKey: [...KEY, "list"],
    queryFn: ({ signal }) => getJson<GeoReleaseListResponse>(ROOT, { signal }),
    staleTime: 10_000,
  });
}

export function useGeoRelease(planId: number | null) {
  return useQuery<GeoReleaseDetailResponse, Error>({
    queryKey: [...KEY, "detail", planId],
    queryFn: ({ signal }) =>
      getJson<GeoReleaseDetailResponse>(`${ROOT}/${planId}`, { signal }),
    enabled: planId !== null,
    staleTime: 10_000,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: KEY });
}

export function useDetectGeoReleaseMutation() {
  const invalidate = useInvalidate();
  return useMutation<GeoReleaseDetectResponse, Error, void>({
    mutationFn: () => postJson<GeoReleaseDetectResponse>(`${ROOT}/detect`),
    onSuccess: () => void invalidate(),
  });
}

export function useSkipGeoReleaseItemMutation() {
  const invalidate = useInvalidate();
  return useMutation<
    GeoReleaseDetailResponse,
    Error,
    { planId: number; position: number }
  >({
    mutationFn: ({ planId, position }) =>
      postJson<GeoReleaseDetailResponse>(`${ROOT}/${planId}/items/${position}/skip`),
    onSuccess: () => void invalidate(),
  });
}

export function useReplanGeoReleaseMutation() {
  const invalidate = useInvalidate();
  return useMutation<GeoReleaseDetailResponse, Error, number>({
    mutationFn: (planId) =>
      postJson<GeoReleaseDetailResponse>(`${ROOT}/${planId}/replan`),
    onSuccess: () => void invalidate(),
  });
}

/**
 * 센서가 자동으로 내지 않고 운영자가 수동 실행한 뒤 skip해야 하는 operation(core
 * `SENSOR_MANUAL_OPERATION_KEYS`와 같은 값, #1333 리뷰 R2). API는 이 항목에 기존 사유 값
 * `replay_not_launchable_before_t_gr_08`을 재사용한다(OpenAPI enum 불변 — PinVi 재vendor 회피) —
 * 화면은 operation key로 구분해 정확한 안내를 보인다.
 */
export const MANUAL_OPERATION_KEYS: ReadonlySet<string> = new Set([
  "feature_place_mois_licenses_job",
]);

export type LaunchNote = { tone: "warning" | "neutral"; label: string; detail: string };

/** 항목이 센서로 나가지 못하는 이유 — 화면 문구(없으면 null). */
export function launchNote(item: GeoReleaseItemRecord): LaunchNote | null {
  if (item.launch_blocked_reason === null) {
    return null;
  }
  if (MANUAL_OPERATION_KEYS.has(item.operation_key)) {
    return {
      tone: "warning",
      label: "수동 실행 후 skip 필요",
      detail:
        "센서가 자동으로 내지 않는다 — 이 job을 수동 실행하고 끝나면 이 항목을 건너뛰어야 계획이 끝난다.",
    };
  }
  return {
    tone: "neutral",
    label: "replay 미지원",
    detail: "records resource가 replay를 받지 않아 센서가 내지 않는다.",
  };
}

/** skip 가능한 항목 — 활성 계획(planned·running)의 대기·실패 항목(API `skip_item`과 같은 조건). */
export function canSkip(plan: GeoReleasePlanRecord, item: GeoReleaseItemRecord): boolean {
  return (
    (plan.state === "planned" || plan.state === "running") &&
    (item.state === "pending" || item.state === "failed")
  );
}

/** replan 가능한 계획 — 기준선이 아닌 계획(최신 토큰 여부는 서버가 409로 판정한다). */
export function canReplan(plan: GeoReleasePlanRecord): boolean {
  return plan.state !== "baseline";
}

/** 커버리지 게이지 — 현재 토큰 스탬프 비율(분모 0이면 null). */
export function coverageRatio(coverage: GeoCoverageRecord): number | null {
  if (coverage.total_provider_with_coord <= 0) {
    return null;
  }
  return coverage.stamped_current / coverage.total_provider_with_coord;
}

export function notCalledTotal(coverage: GeoCoverageRecord): number {
  return Object.values(coverage.not_called_by_kind).reduce((sum, value) => sum + value, 0);
}
