/**
 * `/v1/admin/issues` 운영 이슈 검토/조치 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, patchJson, pathWithQuery } from "./client";
import type { components, paths } from "./types";

type IssueSchemas = components["schemas"];
type AdminIssuesListQuery = NonNullable<
  paths["/v1/admin/issues"]["get"]["parameters"]["query"]
>;

export type AdminIssueStatus = Exclude<
  AdminIssuesListQuery["status"],
  null | undefined
>;
export type AdminIssueSeverity = Exclude<
  AdminIssuesListQuery["severity"],
  null | undefined
>;
export type AdminIssueRecord = IssueSchemas["AdminIssueRecord"];
export type AdminIssueListResponse = IssueSchemas["AdminIssueListResponse"];
export type AdminIssueDetailResponse = IssueSchemas["AdminIssueDetailResponse"];
export type AdminIssuePatchRequest = IssueSchemas["AdminIssuePatchRequest"];
export type AdminIssueActionResponse = IssueSchemas["AdminIssueActionResponse"];
export type AdminIssueAction = AdminIssuePatchRequest["action"];
export type AdminIssueListParams = Omit<AdminIssuesListQuery, "cursor"> & {
  cursor?: string;
};

function fetchAdminIssues(
  params: AdminIssueListParams = {},
): Promise<AdminIssueListResponse> {
  return getJson<AdminIssueListResponse>(
    pathWithQuery("/v1/admin/issues", {
      status: params.status,
      issue_type: params.issue_type,
      provider: params.provider,
      dataset_key: params.dataset_key,
      severity: params.severity,
      feature_id: params.feature_id,
      q: params.q,
      min_lon: params.min_lon,
      min_lat: params.min_lat,
      max_lon: params.max_lon,
      max_lat: params.max_lat,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchAdminIssueDetail(
  issueId: string,
): Promise<AdminIssueDetailResponse> {
  return getJson<AdminIssueDetailResponse>(
    `/v1/admin/issues/${encodeURIComponent(issueId)}`,
  );
}

function patchAdminIssue(
  issueId: string,
  body: AdminIssuePatchRequest,
): Promise<AdminIssueActionResponse> {
  return patchJson<AdminIssueActionResponse>(
    `/v1/admin/issues/${encodeURIComponent(issueId)}`,
    body,
  );
}

export function useAdminIssues(params: AdminIssueListParams = {}) {
  return useQuery<AdminIssueListResponse, Error>({
    queryKey: ["admin-issues", params],
    queryFn: () => fetchAdminIssues(params),
    staleTime: 15_000,
  });
}

export function useAdminIssueDetail(issueId: string | null) {
  return useQuery<AdminIssueDetailResponse, Error>({
    queryKey: ["admin-issue", issueId] as const,
    queryFn: () => fetchAdminIssueDetail(issueId as string),
    enabled: issueId !== null && issueId.length > 0,
    staleTime: 15_000,
  });
}

export function useAdminIssueActionMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    AdminIssueActionResponse,
    Error,
    { issueId: string; body: AdminIssuePatchRequest }
  >({
    mutationFn: ({ issueId, body }) => patchAdminIssue(issueId, body),
    onSuccess: (data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-issues"] });
      void queryClient.invalidateQueries({
        queryKey: ["admin-issue", variables.issueId],
      });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      void queryClient.invalidateQueries({
        queryKey: ["ops", "consistency", "issues"],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      const featureId = data.data.feature?.feature_id;
      if (featureId) {
        void queryClient.invalidateQueries({ queryKey: ["feature", featureId] });
      }
    },
  });
}
