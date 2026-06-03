/**
 * `/admin/offline-uploads/*` 오프라인 업로드 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, pathWithQuery, postFormData, postJson } from "./client";

export type OfflineUploadState =
  | "uploaded"
  | "validating"
  | "validated"
  | "validation_failed"
  | "loading"
  | "loaded"
  | "load_failed"
  | "cancelled";

export interface OfflineUploadRecord {
  upload_id: string;
  provider: string;
  dataset_key: string;
  sync_scope: string;
  original_filename: string;
  storage_backend: string;
  storage_key: string;
  byte_size: number;
  checksum_sha256: string;
  detected_format: string | null;
  detected_encoding: string | null;
  state: string;
  validation_job_id: string | null;
  load_job_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  status_url: string;
  load_url: string;
}

export interface OfflineUploadListParams {
  state?: OfflineUploadState;
  provider?: string;
  dataset_key?: string;
  page_size?: number;
  cursor?: string;
}

export interface OfflineUploadListResponse {
  count: number;
  items: OfflineUploadRecord[];
  next_cursor: string | null;
}

export interface OfflineUploadCreateRequest {
  file: File;
  provider: string;
  datasetKey: string;
  syncScope?: string;
  createdBy?: string;
}

export interface OfflineUploadWriteResponse {
  data: OfflineUploadRecord;
  meta: {
    duration_ms: number;
    bucket: string;
    object_key: string;
    content_type: string;
  };
}

export interface OfflineUploadLaunchResponse {
  data: OfflineUploadRecord;
  meta: {
    duration_ms: number;
    dagster_run_id: string;
    dagster_status: string;
  };
}

function fetchOfflineUploads(
  params: OfflineUploadListParams = {},
): Promise<OfflineUploadListResponse> {
  return getJson<OfflineUploadListResponse>(
    pathWithQuery("/admin/offline-uploads", {
      state: params.state,
      provider: params.provider,
      dataset_key: params.dataset_key,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchOfflineUpload(uploadId: string): Promise<OfflineUploadRecord> {
  return getJson<OfflineUploadRecord>(
    `/admin/offline-uploads/${encodeURIComponent(uploadId)}`,
  );
}

function createOfflineUpload(
  body: OfflineUploadCreateRequest,
): Promise<OfflineUploadWriteResponse> {
  const form = new FormData();
  form.append("file", body.file);
  form.append("provider", body.provider);
  form.append("dataset_key", body.datasetKey);
  form.append("sync_scope", body.syncScope ?? "default");
  if (body.createdBy) {
    form.append("created_by", body.createdBy);
  }
  return postFormData<OfflineUploadWriteResponse>("/admin/offline-uploads", form);
}

function launchOfflineUploadLoad(
  uploadId: string,
): Promise<OfflineUploadLaunchResponse> {
  return postJson<OfflineUploadLaunchResponse>(
    `/admin/offline-uploads/${encodeURIComponent(uploadId)}/load`,
    {},
  );
}

export function useOfflineUploads(params: OfflineUploadListParams = {}) {
  return useQuery<OfflineUploadListResponse, Error>({
    queryKey: ["offline-uploads", params],
    queryFn: () => fetchOfflineUploads(params),
    refetchInterval: (query) => {
      const hasActiveUpload = query.state.data?.items.some((item) =>
        ["validating", "loading"].includes(item.state),
      );
      return hasActiveUpload ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useOfflineUpload(uploadId: string | null) {
  return useQuery<OfflineUploadRecord, Error>({
    queryKey: ["offline-upload", uploadId],
    queryFn: () => fetchOfflineUpload(uploadId as string),
    enabled: uploadId !== null && uploadId.length > 0,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "validating" || state === "loading" ? 2_000 : false;
    },
    staleTime: 2_000,
  });
}

export function useCreateOfflineUploadMutation() {
  const queryClient = useQueryClient();
  return useMutation<OfflineUploadWriteResponse, Error, OfflineUploadCreateRequest>({
    mutationFn: createOfflineUpload,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
      void queryClient.invalidateQueries({
        queryKey: ["offline-upload", data.data.upload_id],
      });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
    },
  });
}

export function useLaunchOfflineUploadLoadMutation() {
  const queryClient = useQueryClient();
  return useMutation<OfflineUploadLaunchResponse, Error, string>({
    mutationFn: launchOfflineUploadLoad,
    onSuccess: (data, uploadId) => {
      void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
      void queryClient.invalidateQueries({ queryKey: ["offline-upload", uploadId] });
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "dagster"] });
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      if (data.data.load_job_id) {
        void queryClient.invalidateQueries({
          queryKey: ["import-job", data.data.load_job_id],
        });
      }
    },
  });
}
