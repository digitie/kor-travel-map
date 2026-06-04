/**
 * Import job 운영 조회 hooks.
 *
 * 화면 route는 `/ops/import-jobs` 또는 admin navigation 안의 job 화면이지만,
 * backend 계약은 ADR-045 T-207d 기준 `/ops/import-jobs/*`다.
 */

import { useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery } from "./client";

export type ImportJobState =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export interface OpsImportJobRecord {
  job_id: string;
  kind: string;
  load_batch_id: string | null;
  parent_job_id: string | null;
  payload: Record<string, unknown>;
  state: string;
  progress: number;
  current_stage: string | null;
  source_checksum: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  status_url: string;
}

export interface OpsImportJobsListResponse {
  data: {
    items: OpsImportJobRecord[];
    next_cursor: string | null;
  };
  meta: {
    count: number;
    page_size: number;
    duration_ms: number;
  };
}

export interface OpsImportJobResponse {
  data: OpsImportJobRecord;
}

export interface ImportJobsListParams {
  state?: ImportJobState;
  kind?: string;
  load_batch_id?: string;
  parent_job_id?: string;
  page_size?: number;
  cursor?: string;
}

function fetchImportJobs(
  params: ImportJobsListParams = {},
): Promise<OpsImportJobsListResponse> {
  return getJson<OpsImportJobsListResponse>(
    pathWithQuery("/ops/import-jobs", {
      state: params.state,
      kind: params.kind,
      load_batch_id: params.load_batch_id,
      parent_job_id: params.parent_job_id,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchImportJob(jobId: string): Promise<OpsImportJobResponse> {
  return getJson<OpsImportJobResponse>(
    `/ops/import-jobs/${encodeURIComponent(jobId)}`,
  );
}

export function useImportJobs(params: ImportJobsListParams = {}) {
  return useQuery<OpsImportJobsListResponse, Error>({
    queryKey: ["import-jobs", params],
    queryFn: () => fetchImportJobs(params),
    refetchInterval: (query) => {
      const hasRunningJob = query.state.data?.data.items.some((item) =>
        ["queued", "running"].includes(item.state),
      );
      return hasRunningJob ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useImportJob(jobId: string | null) {
  return useQuery<OpsImportJobResponse, Error>({
    queryKey: ["import-job", jobId],
    queryFn: () => fetchImportJob(jobId as string),
    enabled: jobId !== null && jobId.length > 0,
    refetchInterval: (query) => {
      const state = query.state.data?.data.state;
      return state === "queued" || state === "running" ? 2_000 : false;
    },
    staleTime: 2_000,
  });
}
