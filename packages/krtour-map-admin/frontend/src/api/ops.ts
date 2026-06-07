/**
 * `/ops/*` 운영 summary/consistency 조회 hooks.
 */

import { useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type OpsSchemas = components["schemas"];
type ConsistencyReportsQuery = NonNullable<
  paths["/ops/consistency/reports"]["get"]["parameters"]["query"]
>;
type IntegrityIssuesQuery = NonNullable<
  paths["/ops/consistency/issues"]["get"]["parameters"]["query"]
>;
type SystemLogsQuery = NonNullable<
  paths["/ops/system-logs"]["get"]["parameters"]["query"]
>;
type ApiCallLogsQuery = NonNullable<
  paths["/ops/api-call-logs"]["get"]["parameters"]["query"]
>;

export type ConsistencySeverity = Exclude<
  ConsistencyReportsQuery["severity_max"],
  null | undefined
>;
export type IntegrityIssueStatus = Exclude<
  IntegrityIssuesQuery["status"],
  null | undefined
>;
export type IntegrityIssueSeverity = Exclude<
  IntegrityIssuesQuery["severity"],
  null | undefined
>;
export type SystemLogLevel = Exclude<
  SystemLogsQuery["level"],
  null | undefined
>;
export type OpsListMeta = OpsSchemas["OpsListMeta"];
export type OpsConsistencyReportRecord =
  OpsSchemas["OpsConsistencyReportRecord"];
export type OpsConsistencyReportsListResponse =
  OpsSchemas["OpsConsistencyReportsListResponse"];
export type OpsIntegrityIssueRecord =
  OpsSchemas["OpsIntegrityIssueRecord"];
export type OpsIntegrityIssuesListResponse =
  OpsSchemas["OpsIntegrityIssuesListResponse"];
export type OpsDedupFpStatsRecord = OpsSchemas["OpsDedupFpStatsRecord"];
export type OpsIntegrityIssueCountsRecord =
  OpsSchemas["OpsIntegrityIssueCountsRecord"];
export type OpsMetricsResponse = OpsSchemas["OpsMetricsResponse"];
export type SystemLogRecord = OpsSchemas["SystemLogRecord"];
export type SystemLogsResponse = OpsSchemas["SystemLogsResponse"];
export type ApiCallLogRecord = OpsSchemas["ApiCallLogRecord"];
export type ApiCallLogsResponse = OpsSchemas["ApiCallLogsResponse"];
export type ConsistencyReportsListParams = Omit<
  ConsistencyReportsQuery,
  "cursor"
> & {
  cursor?: string;
};
export type IntegrityIssuesListParams = Omit<
  IntegrityIssuesQuery,
  "cursor"
> & {
  cursor?: string;
};
export type SystemLogsListParams = Omit<SystemLogsQuery, "cursor"> & {
  cursor?: string;
};
export type ApiCallLogsListParams = Omit<ApiCallLogsQuery, "cursor"> & {
  cursor?: string;
};

function fetchOpsMetrics(): Promise<OpsMetricsResponse> {
  return getJson<OpsMetricsResponse>("/ops/metrics");
}

function fetchConsistencyReports(
  params: ConsistencyReportsListParams = {},
): Promise<OpsConsistencyReportsListResponse> {
  return getJson<OpsConsistencyReportsListResponse>(
    pathWithQuery("/ops/consistency/reports", {
      severity_max: params.severity_max,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchIntegrityIssues(
  params: IntegrityIssuesListParams = {},
): Promise<OpsIntegrityIssuesListResponse> {
  return getJson<OpsIntegrityIssuesListResponse>(
    pathWithQuery("/ops/consistency/issues", {
      status: params.status,
      severity: params.severity,
      violation_type: params.violation_type,
      provider: params.provider,
      dataset_key: params.dataset_key,
      feature_id: params.feature_id,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchSystemLogs(
  params: SystemLogsListParams = {},
): Promise<SystemLogsResponse> {
  return getJson<SystemLogsResponse>(
    pathWithQuery("/ops/system-logs", {
      level: params.level,
      source: params.source,
      q: params.q,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchApiCallLogs(
  params: ApiCallLogsListParams = {},
): Promise<ApiCallLogsResponse> {
  return getJson<ApiCallLogsResponse>(
    pathWithQuery("/ops/api-call-logs", {
      method: params.method,
      min_status: params.min_status,
      path: params.path,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

export function useOpsMetrics() {
  return useQuery<OpsMetricsResponse, Error>({
    queryKey: ["ops", "metrics"],
    queryFn: fetchOpsMetrics,
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}

export function useConsistencyReports(
  params: ConsistencyReportsListParams = {},
) {
  return useQuery<OpsConsistencyReportsListResponse, Error>({
    queryKey: ["ops", "consistency", "reports", params],
    queryFn: () => fetchConsistencyReports(params),
    staleTime: 30_000,
  });
}

export function useIntegrityIssues(params: IntegrityIssuesListParams = {}) {
  return useQuery<OpsIntegrityIssuesListResponse, Error>({
    queryKey: ["ops", "consistency", "issues", params],
    queryFn: () => fetchIntegrityIssues(params),
    staleTime: 15_000,
  });
}

export function useSystemLogs(params: SystemLogsListParams = {}) {
  return useQuery<SystemLogsResponse, Error>({
    queryKey: ["ops", "system-logs", params],
    queryFn: () => fetchSystemLogs(params),
    staleTime: 15_000,
  });
}

export function useApiCallLogs(params: ApiCallLogsListParams = {}) {
  return useQuery<ApiCallLogsResponse, Error>({
    queryKey: ["ops", "api-call-logs", params],
    queryFn: () => fetchApiCallLogs(params),
    staleTime: 15_000,
  });
}
