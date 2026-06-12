/**
 * Import job 운영 조회 hooks.
 *
 * 화면 route는 `/v1/ops/import-jobs` 또는 admin navigation 안의 job 화면이지만,
 * backend 계약은 ADR-045 T-207d 기준 `/v1/ops/import-jobs/*`다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type ImportJobSchemas = components["schemas"];
type ImportJobsListQuery = NonNullable<
  paths["/v1/ops/import-jobs"]["get"]["parameters"]["query"]
>;
type ImportJobEventsQuery = NonNullable<
  paths["/v1/ops/import-jobs/{job_id}/events"]["get"]["parameters"]["query"]
>;

export type ImportJobStatus = Exclude<
  ImportJobsListQuery["status"],
  null | undefined
>;
export type ImportJobEventLevel = Exclude<
  ImportJobEventsQuery["level"],
  null | undefined
>;
export type OpsImportJobRecord = ImportJobSchemas["OpsImportJobRecord"];
export type OpsImportJobLink = ImportJobSchemas["OpsImportJobLink"];
export type OpsImportJobEventRecord =
  ImportJobSchemas["OpsImportJobEventRecord"];
export type OpsImportJobsListResponse =
  ImportJobSchemas["OpsImportJobsListResponse"];
export type OpsImportJobResponse = ImportJobSchemas["OpsImportJobResponse"];
export type OpsImportJobEventsListResponse =
  ImportJobSchemas["OpsImportJobEventsListResponse"];
export type OpsImportJobCancelRequest =
  ImportJobSchemas["OpsImportJobCancelRequest"];
export type ImportJobsListParams = Omit<ImportJobsListQuery, "cursor"> & {
  cursor?: string;
};
export type ImportJobEventsParams = Omit<ImportJobEventsQuery, "cursor"> & {
  cursor?: string;
};

function fetchImportJobs(
  params: ImportJobsListParams = {},
): Promise<OpsImportJobsListResponse> {
  return getJson<OpsImportJobsListResponse>(
    pathWithQuery("/v1/ops/import-jobs", {
      status: params.status,
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
    `/v1/ops/import-jobs/${encodeURIComponent(jobId)}`,
  );
}

function fetchImportJobEvents(
  jobId: string,
  params: ImportJobEventsParams = {},
): Promise<OpsImportJobEventsListResponse> {
  return getJson<OpsImportJobEventsListResponse>(
    pathWithQuery(
      `/v1/ops/import-jobs/${encodeURIComponent(jobId)}/events`,
      {
        level: params.level,
        page_size: params.page_size,
        cursor: params.cursor,
      },
    ),
  );
}

function cancelImportJob({
  jobId,
  body = {},
}: {
  jobId: string;
  body?: OpsImportJobCancelRequest;
}): Promise<OpsImportJobResponse> {
  return postJson<OpsImportJobResponse>(
    `/v1/ops/import-jobs/${encodeURIComponent(jobId)}/cancel`,
    body,
  );
}

export function useImportJobs(params: ImportJobsListParams = {}) {
  return useQuery<OpsImportJobsListResponse, Error>({
    queryKey: ["import-jobs", params],
    queryFn: () => fetchImportJobs(params),
    refetchInterval: (query) => {
      const hasRunningJob = query.state.data?.data.items.some((item) =>
        ["queued", "running"].includes(item.status),
      );
      return hasRunningJob ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useImportJob(jobId: string) {
  return useQuery<OpsImportJobResponse, Error>({
    queryKey: ["import-job", jobId],
    queryFn: () => fetchImportJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.data.status;
      return status && ["queued", "running"].includes(status) ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useImportJobEvents(
  jobId: string,
  params: ImportJobEventsParams = {},
) {
  return useQuery<OpsImportJobEventsListResponse, Error>({
    queryKey: ["import-job-events", jobId, params],
    queryFn: () => fetchImportJobEvents(jobId, params),
    refetchInterval: 5_000,
    staleTime: 5_000,
  });
}

export function useCancelImportJobMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    OpsImportJobResponse,
    Error,
    { jobId: string; body?: OpsImportJobCancelRequest }
  >({
    mutationFn: cancelImportJob,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({
        queryKey: ["import-job", variables.jobId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["import-job-events", variables.jobId],
      });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    },
  });
}
