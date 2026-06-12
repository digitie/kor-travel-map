/**
 * `/v1/admin/offline-uploads/*` 오프라인 업로드 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, pathWithQuery, postFormData, postJson } from "./client";
import type { components, paths } from "./types";

type OfflineUploadSchemas = components["schemas"];
type OfflineUploadListQuery = NonNullable<
  paths["/v1/admin/offline-uploads"]["get"]["parameters"]["query"]
>;

export type OfflineUploadStatus = Exclude<
  OfflineUploadListQuery["status"],
  null | undefined
>;
export type OfflineUploadRecord = OfflineUploadSchemas["OfflineUploadRecord"];
export type OfflineUploadListParams = Omit<OfflineUploadListQuery, "cursor"> & {
  cursor?: string;
};
export type OfflineUploadListResponse =
  OfflineUploadSchemas["OfflineUploadListResponse"];
export type OfflineUploadDetailResponse =
  OfflineUploadSchemas["OfflineUploadDetailResponse"];

export interface OfflineUploadCreateRequest {
  file: File;
  provider: string;
  datasetKey: string;
  syncScope?: string;
  createdBy?: string;
}

export type OfflineUploadWriteResponse =
  OfflineUploadSchemas["OfflineUploadWriteResponse"];
export type OfflineUploadColumnMapping =
  OfflineUploadSchemas["OfflineUploadColumnMappingRecord"];
export type OfflineUploadPreviewMeta =
  OfflineUploadSchemas["OfflineUploadPreviewMeta"];
export type OfflineUploadPreviewResponse =
  OfflineUploadSchemas["OfflineUploadPreviewResponse"];
export type OfflineUploadValidationIssue =
  OfflineUploadSchemas["OfflineUploadValidationIssueRecord"];
export type OfflineUploadValidationMeta =
  OfflineUploadSchemas["OfflineUploadValidationMeta"];
export type OfflineUploadValidationResponse =
  OfflineUploadSchemas["OfflineUploadValidationResponse"];

export interface OfflineUploadValidateRequest {
  uploadId: string;
  sampleSize?: number;
  columnMapping: OfflineUploadColumnMapping;
  operator?: string;
}

export type OfflineUploadLaunchResponse =
  OfflineUploadSchemas["OfflineUploadLaunchResponse"];
export type OfflineUploadDeleteResponse =
  OfflineUploadSchemas["OfflineUploadDeleteResponse"];

function fetchOfflineUploads(
  params: OfflineUploadListParams = {},
): Promise<OfflineUploadListResponse> {
  return getJson<OfflineUploadListResponse>(
    pathWithQuery("/v1/admin/offline-uploads", {
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
  );
}

function fetchOfflineUpload(
  uploadId: string,
): Promise<OfflineUploadDetailResponse> {
  return getJson<OfflineUploadDetailResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}`,
  );
}

function fetchOfflineUploadPreview(
  uploadId: string,
  sampleSize: number,
): Promise<OfflineUploadPreviewResponse> {
  return getJson<OfflineUploadPreviewResponse>(
    pathWithQuery(`/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}/preview`, {
      sample_size: sampleSize,
    }),
  );
}

function fetchOfflineUploadValidation(
  uploadId: string,
): Promise<OfflineUploadValidationResponse> {
  return getJson<OfflineUploadValidationResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}/validation`,
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
  return postFormData<OfflineUploadWriteResponse>("/v1/admin/offline-uploads", form);
}

function validateOfflineUpload(
  body: OfflineUploadValidateRequest,
): Promise<OfflineUploadValidationResponse> {
  return postJson<OfflineUploadValidationResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(body.uploadId)}/validate`,
    {
      sample_size: body.sampleSize ?? 1000,
      operator: body.operator,
      column_mapping: body.columnMapping,
    },
  );
}

function launchOfflineUploadLoad(
  uploadId: string,
): Promise<OfflineUploadLaunchResponse> {
  return postJson<OfflineUploadLaunchResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}/load`,
    {},
  );
}

function deleteOfflineUpload(
  uploadId: string,
): Promise<OfflineUploadDeleteResponse> {
  return deleteJson<OfflineUploadDeleteResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}`,
  );
}

export function useOfflineUploads(params: OfflineUploadListParams = {}) {
  return useQuery<OfflineUploadListResponse, Error>({
    queryKey: ["offline-uploads", params],
    queryFn: () => fetchOfflineUploads(params),
    refetchInterval: (query) => {
      const hasActiveUpload = query.state.data?.data.items.some((item) =>
        ["validating", "loading"].includes(item.status),
      );
      return hasActiveUpload ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useOfflineUpload(uploadId: string | null) {
  return useQuery<OfflineUploadDetailResponse, Error>({
    queryKey: ["offline-upload", uploadId],
    queryFn: () => fetchOfflineUpload(uploadId as string),
    enabled: uploadId !== null && uploadId.length > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.data.status;
      return status === "validating" || status === "loading" ? 2_000 : false;
    },
    staleTime: 2_000,
  });
}

export function useOfflineUploadPreview(
  uploadId: string | null,
  sampleSize = 20,
  enabled = true,
) {
  return useQuery<OfflineUploadPreviewResponse, Error>({
    queryKey: ["offline-upload-preview", uploadId, sampleSize],
    queryFn: () => fetchOfflineUploadPreview(uploadId as string, sampleSize),
    enabled: enabled && uploadId !== null && uploadId.length > 0,
    staleTime: 10_000,
  });
}

export function useOfflineUploadValidation(uploadId: string | null, enabled = true) {
  return useQuery<OfflineUploadValidationResponse, Error>({
    queryKey: ["offline-upload-validation", uploadId],
    queryFn: () => fetchOfflineUploadValidation(uploadId as string),
    enabled: enabled && uploadId !== null && uploadId.length > 0,
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

export function useValidateOfflineUploadMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    OfflineUploadValidationResponse,
    Error,
    OfflineUploadValidateRequest
  >({
    mutationFn: validateOfflineUpload,
    onSuccess: (data, request) => {
      void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
      void queryClient.invalidateQueries({
        queryKey: ["offline-upload", request.uploadId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["offline-upload-validation", request.uploadId],
      });
      void queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
      if (data.meta.job_id) {
        void queryClient.invalidateQueries({
          queryKey: ["import-job", data.meta.job_id],
        });
      }
    },
  });
}

export function useDeleteOfflineUploadMutation() {
  const queryClient = useQueryClient();
  return useMutation<OfflineUploadDeleteResponse, Error, string>({
    mutationFn: deleteOfflineUpload,
    onSuccess: (_data, uploadId) => {
      void queryClient.invalidateQueries({ queryKey: ["offline-uploads"] });
      void queryClient.removeQueries({ queryKey: ["offline-upload", uploadId] });
      void queryClient.removeQueries({
        queryKey: ["offline-upload-preview", uploadId],
      });
      void queryClient.removeQueries({
        queryKey: ["offline-upload-validation", uploadId],
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
