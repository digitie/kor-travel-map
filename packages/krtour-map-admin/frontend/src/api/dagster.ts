/**
 * Dagster 운영 요약 API hooks.
 *
 * `/ops/dagster/summary`는 backend가 Dagster GraphQL을 읽어 admin UI용 DTO로
 * 정규화한 응답이다. iframe embed에는 public Dagster URL을 직접 사용한다.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
import { publicUrlEnv } from "./env";
import type { components } from "./types";

export const DAGSTER_UI_URL = publicUrlEnv(
  process.env.NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL,
  "NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL",
  "http://127.0.0.1:9013",
);

type DagsterSchemas = components["schemas"];

export type DagsterAssetGroup = DagsterSchemas["DagsterAssetGroup"];
export type DagsterJob = DagsterSchemas["DagsterJob"];
export type DagsterSchedule = DagsterSchemas["DagsterSchedule"];
export type DagsterSensor = DagsterSchemas["DagsterSensor"];
export type DagsterRepository = DagsterSchemas["DagsterRepository"];
export type DagsterGraphqlError = DagsterSchemas["DagsterGraphqlError"];
export type DagsterInstigationTick = DagsterSchemas["DagsterInstigationTick"];
export type DagsterRunSummary = DagsterSchemas["DagsterRunSummary"];
export type DagsterRunEvent = DagsterSchemas["DagsterRunEvent"];
export type DagsterRunDetailResponse =
  DagsterSchemas["DagsterRunDetailResponse"];
export type DagsterSummaryResponse = DagsterSchemas["DagsterSummaryResponse"];
export type DagsterNuxSeenResponse = DagsterSchemas["DagsterNuxSeenResponse"];

function fetchDagsterSummary(runLimit = 10): Promise<DagsterSummaryResponse> {
  return getJson<DagsterSummaryResponse>(
    pathWithQuery("/ops/dagster/summary", { run_limit: runLimit }),
  );
}

function markDagsterNuxSeen(): Promise<DagsterNuxSeenResponse> {
  return postJson<DagsterNuxSeenResponse>("/ops/dagster/nux-seen");
}

function fetchDagsterRunDetail(
  runId: string,
  eventLimit = 50,
  after: string | null = null,
): Promise<DagsterRunDetailResponse> {
  return getJson<DagsterRunDetailResponse>(
    pathWithQuery(`/ops/dagster/runs/${encodeURIComponent(runId)}`, {
      event_limit: eventLimit,
      after: after ?? undefined,
    }),
  );
}

// SUCCESS/FAILURE/CANCELED 등 종료 run은 상세가 더 변하지 않으므로 폴링을 멈춘다.
const _TERMINAL_RUN_STATUS = new Set(["SUCCESS", "FAILURE", "CANCELED"]);

export function useDagsterSummary(runLimit = 10) {
  return useQuery<DagsterSummaryResponse, Error>({
    queryKey: ["ops", "dagster", "summary", runLimit],
    queryFn: () => fetchDagsterSummary(runLimit),
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}

export function useMarkDagsterNuxSeen() {
  return useMutation<DagsterNuxSeenResponse, Error>({
    mutationFn: markDagsterNuxSeen,
  });
}

export function useDagsterRunDetail(
  runId: string | null,
  eventLimit = 50,
  after: string | null = null,
) {
  return useQuery<DagsterRunDetailResponse, Error>({
    queryKey: ["ops", "dagster", "runs", runId, eventLimit, after],
    queryFn: () => fetchDagsterRunDetail(runId ?? "", eventLimit, after),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      if (!runId) return false;
      const status = query.state.data?.data.run?.status;
      if (status && _TERMINAL_RUN_STATUS.has(status)) return false;
      return 10_000;
    },
    staleTime: 8_000,
  });
}
