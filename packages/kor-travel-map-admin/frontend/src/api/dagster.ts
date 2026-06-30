/**
 * 작업 자동화 요약 API hooks.
 *
 * `/v1/ops/dagster/summary`는 backend가 Dagster GraphQL을 읽어 admin UI용 DTO로
 * 정규화한 응답이다. iframe embed에는 public Dagster URL을 직접 사용한다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery, postJson } from "./client";
import { publicUrlEnv } from "./env";
import type { components } from "./types";

export const DAGSTER_UI_URL = publicUrlEnv(
  process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL,
  "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL",
  "http://127.0.0.1:12702",
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
export type DagsterScheduleCommandResponse =
  DagsterSchemas["DagsterScheduleCommandResponse"];
export type DagsterSummaryResponse = DagsterSchemas["DagsterSummaryResponse"];
export type DagsterNuxSeenResponse = DagsterSchemas["DagsterNuxSeenResponse"];

function fetchDagsterSummary(
  runLimit = 10,
  signal?: AbortSignal,
): Promise<DagsterSummaryResponse> {
  return getJson<DagsterSummaryResponse>(
    pathWithQuery("/v1/ops/dagster/summary", { run_limit: runLimit }),
    { signal },
  );
}

function markDagsterNuxSeen(): Promise<DagsterNuxSeenResponse> {
  return postJson<DagsterNuxSeenResponse>("/v1/ops/dagster/nux-seen");
}

function patchDagsterSchedule(
  scheduleName: string,
  body: { cron_schedule: string; operator?: string; reason?: string },
): Promise<DagsterScheduleCommandResponse> {
  return patchJson<DagsterScheduleCommandResponse>(
    `/v1/ops/dagster/schedules/${encodeURIComponent(scheduleName)}`,
    body,
  );
}

function postDagsterScheduleCommand(
  scheduleName: string,
  command: "default" | "reset" | "run" | "start" | "stop",
  body: { operator?: string; reason?: string } = {},
): Promise<DagsterScheduleCommandResponse> {
  return postJson<DagsterScheduleCommandResponse>(
    `/v1/ops/dagster/schedules/${encodeURIComponent(scheduleName)}/${command}`,
    body,
  );
}

function fetchDagsterRunDetail(
  runId: string,
  eventLimit = 50,
  after: string | null = null,
  signal?: AbortSignal,
): Promise<DagsterRunDetailResponse> {
  return getJson<DagsterRunDetailResponse>(
    pathWithQuery(`/v1/ops/dagster/runs/${encodeURIComponent(runId)}`, {
      event_limit: eventLimit,
      after: after ?? undefined,
    }),
    { signal },
  );
}

// SUCCESS/FAILURE/CANCELED 등 종료 run은 상세가 더 변하지 않으므로 폴링을 멈춘다.
const _TERMINAL_RUN_STATUS = new Set(["SUCCESS", "FAILURE", "CANCELED"]);

export function useDagsterSummary(runLimit = 10) {
  return useQuery<DagsterSummaryResponse, Error>({
    queryKey: ["ops", "dagster", "summary", runLimit],
    queryFn: ({ signal }) => fetchDagsterSummary(runLimit, signal),
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}

export function useMarkDagsterNuxSeen() {
  return useMutation<DagsterNuxSeenResponse, Error>({
    mutationFn: markDagsterNuxSeen,
  });
}

export function usePatchDagsterSchedule() {
  const queryClient = useQueryClient();
  return useMutation<
    DagsterScheduleCommandResponse,
    Error,
    { cronSchedule: string; reason?: string; scheduleName: string }
  >({
    mutationFn: ({ cronSchedule, reason, scheduleName }) =>
      patchDagsterSchedule(scheduleName, {
        cron_schedule: cronSchedule,
        operator: "admin-ui",
        reason,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ops", "dagster"] });
    },
  });
}

export function useDagsterScheduleCommand() {
  const queryClient = useQueryClient();
  return useMutation<
    DagsterScheduleCommandResponse,
    Error,
    {
      command: "default" | "reset" | "run" | "start" | "stop";
      reason?: string;
      scheduleName: string;
    }
  >({
    mutationFn: ({ command, reason, scheduleName }) =>
      postDagsterScheduleCommand(scheduleName, command, {
        operator: "admin-ui",
        reason,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ops", "dagster"] });
    },
  });
}

export function useDagsterRunDetail(
  runId: string | null,
  eventLimit = 50,
  after: string | null = null,
) {
  return useQuery<DagsterRunDetailResponse, Error>({
    queryKey: ["ops", "dagster", "runs", runId, eventLimit, after],
    queryFn: ({ signal }) =>
      fetchDagsterRunDetail(runId ?? "", eventLimit, after, signal),
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
