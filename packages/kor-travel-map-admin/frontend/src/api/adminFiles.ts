/**
 * `/v1/admin/files/*` 관리 파일 레지스트리 hooks (개편 D).
 *
 * provider 다운로드·백업·offline 업로드·MOIS 소스 등 시스템 적재 파일을 추적하는
 * 읽기 위주 API. 목록/요약/상세(+provenance links·events)/재스캔/purge.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postJson } from "./client";
import type { components, paths } from "./types";

type FileSchemas = components["schemas"];
type ManagedFileListQuery = NonNullable<
  paths["/v1/admin/files"]["get"]["parameters"]["query"]
>;

export type ManagedFile = FileSchemas["ManagedFileModel"];
export type ManagedFileEvent = FileSchemas["ManagedFileEventModel"];
export type ManagedFileLink = FileSchemas["ManagedFileLink"];
export type ManagedFileListResponse = FileSchemas["ManagedFileListResponse"];
export type ManagedFileDetailResponse = FileSchemas["ManagedFileDetailResponse"];
export type ManagedFileEventsResponse = FileSchemas["ManagedFileEventsResponse"];
export type ManagedFileSummaryResponse = FileSchemas["ManagedFileSummaryResponse"];
export type ManagedFileRescanResponse = FileSchemas["ManagedFileRescanResponse"];
export type ManagedFilePurgeResponse = FileSchemas["ManagedFilePurgeResponse"];
export type ManagedFileSortField = NonNullable<ManagedFileListQuery["sort"]>;

export type ManagedFileListParams = {
  kind?: string[];
  status?: string[];
  provider?: string | null;
  location?: string | null;
  registered_by?: string | null;
  q?: string | null;
  min_age_days?: number | null;
  max_age_days?: number | null;
  sort?: ManagedFileSortField;
  limit?: number;
  offset?: number;
};

function fetchManagedFiles(
  params: ManagedFileListParams = {},
  signal?: AbortSignal,
): Promise<ManagedFileListResponse> {
  return getJson<ManagedFileListResponse>(
    pathWithQuery("/v1/admin/files", {
      kind: params.kind,
      status: params.status,
      provider: params.provider,
      location: params.location,
      registered_by: params.registered_by,
      q: params.q,
      min_age_days: params.min_age_days,
      max_age_days: params.max_age_days,
      sort: params.sort,
      limit: params.limit,
      offset: params.offset,
    }),
    { signal },
  );
}

function fetchManagedFileSummary(
  signal?: AbortSignal,
): Promise<ManagedFileSummaryResponse> {
  return getJson<ManagedFileSummaryResponse>("/v1/admin/files/summary", { signal });
}

function fetchManagedFile(
  fileId: number,
  signal?: AbortSignal,
): Promise<ManagedFileDetailResponse> {
  return getJson<ManagedFileDetailResponse>(
    `/v1/admin/files/${encodeURIComponent(String(fileId))}`,
    { signal },
  );
}

function rescanManagedFiles(
  locations: string[] | null,
): Promise<ManagedFileRescanResponse> {
  return postJson<ManagedFileRescanResponse>("/v1/admin/files/rescan", {
    locations,
  });
}

function purgeManagedFile(fileId: number): Promise<ManagedFilePurgeResponse> {
  return postJson<ManagedFilePurgeResponse>(
    `/v1/admin/files/${encodeURIComponent(String(fileId))}/purge`,
    {},
  );
}

export function useManagedFiles(params: ManagedFileListParams = {}) {
  return useQuery<ManagedFileListResponse, Error>({
    queryKey: ["managed-files", params],
    queryFn: ({ signal }) => fetchManagedFiles(params, signal),
    staleTime: 10_000,
  });
}

export function useManagedFileSummary() {
  return useQuery<ManagedFileSummaryResponse, Error>({
    queryKey: ["managed-files", "summary"],
    queryFn: ({ signal }) => fetchManagedFileSummary(signal),
    staleTime: 30_000,
  });
}

export function useManagedFile(fileId: number | null) {
  return useQuery<ManagedFileDetailResponse, Error>({
    queryKey: ["managed-file", fileId],
    queryFn: ({ signal }) => fetchManagedFile(fileId as number, signal),
    enabled: fileId !== null,
    staleTime: 5_000,
  });
}

export function useRescanManagedFilesMutation() {
  const queryClient = useQueryClient();
  return useMutation<ManagedFileRescanResponse, Error, string[] | null>({
    mutationFn: rescanManagedFiles,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["managed-files"] });
    },
  });
}

export function usePurgeManagedFileMutation() {
  const queryClient = useQueryClient();
  return useMutation<ManagedFilePurgeResponse, Error, number>({
    mutationFn: purgeManagedFile,
    onSuccess: (_data, fileId) => {
      void queryClient.invalidateQueries({ queryKey: ["managed-files"] });
      void queryClient.invalidateQueries({ queryKey: ["managed-file", fileId] });
    },
  });
}
