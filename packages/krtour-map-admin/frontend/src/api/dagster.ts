/**
 * Dagster 운영 요약 API hooks.
 *
 * `/ops/dagster/summary`는 backend가 Dagster GraphQL을 읽어 admin UI용 DTO로
 * 정규화한 응답이다. iframe embed에는 public Dagster URL을 직접 사용한다.
 */

import { useQuery } from "@tanstack/react-query";

import { BASE_URL, DebugUiApiError } from "./client";

export const DAGSTER_UI_URL =
  process.env.NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL ?? "http://127.0.0.1:9013";

export interface DagsterAssetGroup {
  group_name: string;
  asset_count: number;
  assets: string[];
}

export interface DagsterJob {
  name: string;
  is_job: boolean;
}

export interface DagsterSchedule {
  name: string;
  cron_schedule: string | null;
  execution_timezone: string | null;
  status: string | null;
}

export interface DagsterSensor {
  name: string;
  status: string | null;
}

export interface DagsterRepository {
  name: string;
  location_name: string;
  jobs: DagsterJob[];
  schedules: DagsterSchedule[];
  sensors: DagsterSensor[];
  asset_count: number;
  asset_groups: DagsterAssetGroup[];
}

export interface DagsterRunSummary {
  run_id: string;
  job_name: string | null;
  status: string;
  start_time: number | null;
  end_time: number | null;
  update_time: number | null;
  tags: Record<string, string>;
}

export interface DagsterSummaryResponse {
  status: "ok" | "unavailable" | "error";
  dagster_url: string;
  graphql_url: string;
  version: string | null;
  checked_at: string;
  repository_count: number;
  job_count: number;
  asset_count: number;
  schedule_count: number;
  sensor_count: number;
  run_counts: Record<string, number>;
  repositories: DagsterRepository[];
  recent_runs: DagsterRunSummary[];
  errors: string[];
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
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

function fetchDagsterSummary(runLimit = 10): Promise<DagsterSummaryResponse> {
  const search = new URLSearchParams({ run_limit: String(runLimit) });
  return getJson<DagsterSummaryResponse>(`/ops/dagster/summary?${search}`);
}

export function useDagsterSummary(runLimit = 10) {
  return useQuery<DagsterSummaryResponse, Error>({
    queryKey: ["ops", "dagster", "summary", runLimit],
    queryFn: () => fetchDagsterSummary(runLimit),
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}
