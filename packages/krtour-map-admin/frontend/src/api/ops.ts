/**
 * `/ops/*` 운영 summary/consistency 조회 hooks.
 */

import { useQuery } from "@tanstack/react-query";

import { getJson, pathWithQuery } from "./client";

export type ConsistencySeverity = "OK" | "WARN" | "ERROR";
export type IntegrityIssueStatus = "open" | "acknowledged" | "resolved" | "ignored";
export type IntegrityIssueSeverity = "info" | "warning" | "error" | "critical";

export interface OpsListMeta {
  count: number;
  page_size: number;
  duration_ms: number;
}

export interface OpsConsistencyReportRecord {
  report_id: string;
  batch_id: string;
  started_at: string;
  finished_at: string | null;
  severity_max: string;
  cases: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
}

export interface OpsConsistencyReportsListResponse {
  data: {
    items: OpsConsistencyReportRecord[];
    next_cursor: string | null;
  };
  meta: OpsListMeta;
}

export interface OpsIntegrityIssueRecord {
  violation_key: string;
  provider: string | null;
  dataset_key: string | null;
  source_record_key: string | null;
  feature_id: string | null;
  violation_type: string;
  severity: string;
  message: string;
  payload: Record<string, unknown>;
  status: string;
  detected_at: string;
  resolved_at: string | null;
}

export interface OpsIntegrityIssuesListResponse {
  data: {
    items: OpsIntegrityIssueRecord[];
    next_cursor: string | null;
  };
  meta: OpsListMeta;
}

export interface OpsDedupFpStatsRecord {
  resolved: number;
  confirmed: number;
  rejected: number;
  ignored: number;
  pending: number;
  precision: number | null;
  fp_rate: number | null;
}

export interface OpsIntegrityIssueCountsRecord {
  open_total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
}

export interface OpsMetricsResponse {
  checked_at: string;
  features_total: number;
  features_active: number;
  features_inactive: number;
  features_by_kind: Record<string, number>;
  source_records_by_provider: Record<string, number>;
  import_jobs_by_state: Record<string, number>;
  dedup_queue_by_status: Record<string, number>;
  dedup_fp_stats: OpsDedupFpStatsRecord;
  data_integrity_issues: OpsIntegrityIssueCountsRecord;
  latest_consistency_report: OpsConsistencyReportRecord | null;
}

export interface ConsistencyReportsListParams {
  severity_max?: ConsistencySeverity;
  page_size?: number;
  cursor?: string;
}

export interface IntegrityIssuesListParams {
  status?: IntegrityIssueStatus;
  severity?: IntegrityIssueSeverity;
  violation_type?: string;
  provider?: string;
  dataset_key?: string;
  feature_id?: string;
  page_size?: number;
  cursor?: string;
}

export function fetchOpsMetrics(): Promise<OpsMetricsResponse> {
  return getJson<OpsMetricsResponse>("/ops/metrics");
}

export function fetchConsistencyReports(
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

export function fetchIntegrityIssues(
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
