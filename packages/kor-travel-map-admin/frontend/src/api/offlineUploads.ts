/**
 * `/v1/admin/offline-uploads/*` 오프라인 업로드 hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearDomainCreateCommandSlot,
  deleteJson,
  domainCommandSlot,
  domainCreateCommandSlot,
  fileIdempotencyFingerprint,
  getJson,
  pathWithQuery,
  postFormData,
  postJson,
  withDomainIdempotencyFingerprint,
  withDomainIdempotencySubmission,
} from "./client";
import { invalidateOpsDatasetQueries } from "./datasets";
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
}

export type OfflineUploadLaunchResponse =
  OfflineUploadSchemas["OfflineUploadLaunchResponse"];
export type OfflineUploadDeleteResponse =
  OfflineUploadSchemas["OfflineUploadDeleteResponse"];

function fetchOfflineUploads(
  params: OfflineUploadListParams = {},
  signal?: AbortSignal,
): Promise<OfflineUploadListResponse> {
  return getJson<OfflineUploadListResponse>(
    pathWithQuery("/v1/admin/offline-uploads", {
      status: params.status,
      provider: params.provider,
      dataset_key: params.dataset_key,
      page_size: params.page_size,
      cursor: params.cursor,
    }),
    { signal },
  );
}

function fetchOfflineUpload(
  uploadId: string,
  signal?: AbortSignal,
): Promise<OfflineUploadDetailResponse> {
  return getJson<OfflineUploadDetailResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}`,
    { signal },
  );
}

function fetchOfflineUploadPreview(
  uploadId: string,
  sampleSize: number,
  signal?: AbortSignal,
): Promise<OfflineUploadPreviewResponse> {
  return getJson<OfflineUploadPreviewResponse>(
    pathWithQuery(`/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}/preview`, {
      sample_size: sampleSize,
    }),
    { signal },
  );
}

function fetchOfflineUploadValidation(
  uploadId: string,
  signal?: AbortSignal,
): Promise<OfflineUploadValidationResponse> {
  return getJson<OfflineUploadValidationResponse>(
    `/v1/admin/offline-uploads/${encodeURIComponent(uploadId)}/validation`,
    { signal },
  );
}

async function createOfflineUpload(
  body: OfflineUploadCreateRequest,
): Promise<OfflineUploadWriteResponse> {
  const provider = body.provider.trim();
  const datasetKey = body.datasetKey.trim();
  const syncScope = body.syncScope?.trim() || "default";
  const fileIdentity = await fileIdempotencyFingerprint(body.file);
  const form = new FormData();
  form.append("file", body.file);
  form.append("provider", provider);
  form.append("dataset_key", datasetKey);
  form.append("sync_scope", syncScope);
  const operation = "admin.offline-upload.create";
  return withDomainIdempotencyFingerprint(
    domainCreateCommandSlot(operation),
    {
      provider,
      dataset_key: datasetKey,
      sync_scope: syncScope,
      filename: fileIdentity.filename,
      content_type: fileIdentity.contentType,
      byte_size: fileIdentity.byteSize,
      content_sha256: fileIdentity.contentSha256,
    },
    (idempotencyKey) =>
      postFormData<OfflineUploadWriteResponse>("/v1/admin/offline-uploads", form, {
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    { onRelease: () => clearDomainCreateCommandSlot(operation) },
  );
}

function validateOfflineUpload(
  body: OfflineUploadValidateRequest,
): Promise<OfflineUploadValidationResponse> {
  const requestBody = {
    sample_size: body.sampleSize ?? 1000,
    column_mapping: body.columnMapping,
  };
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.offline-upload.validate", body.uploadId),
    { uploadId: body.uploadId, body: requestBody },
    (submission, idempotencyKey) =>
      postJson<OfflineUploadValidationResponse>(
        `/v1/admin/offline-uploads/${encodeURIComponent(
          submission.uploadId,
        )}/validate`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
  );
}

function launchOfflineUploadLoad(
  uploadId: string,
): Promise<OfflineUploadLaunchResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.offline-upload.load", uploadId),
    { uploadId },
    (submission, idempotencyKey) =>
      postJson<OfflineUploadLaunchResponse>(
        `/v1/admin/offline-uploads/${encodeURIComponent(
          submission.uploadId,
        )}/load`,
        {},
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
  );
}

function deleteOfflineUpload(
  uploadId: string,
): Promise<OfflineUploadDeleteResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.offline-upload.delete", uploadId),
    { uploadId },
    (submission, idempotencyKey) =>
      deleteJson<OfflineUploadDeleteResponse>(
        `/v1/admin/offline-uploads/${encodeURIComponent(submission.uploadId)}`,
        undefined,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
  );
}

export function useOfflineUploads(params: OfflineUploadListParams = {}) {
  return useQuery<OfflineUploadListResponse, Error>({
    queryKey: ["offline-uploads", params],
    queryFn: ({ signal }) => fetchOfflineUploads(params, signal),
    refetchInterval: (query) => {
      const hasActiveUpload = query.state.data?.data.items.some((item) =>
        ["uploading", "validating", "loading"].includes(item.status),
      );
      return hasActiveUpload ? 2_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useOfflineUpload(uploadId: string | null) {
  return useQuery<OfflineUploadDetailResponse, Error>({
    queryKey: ["offline-upload", uploadId],
    queryFn: ({ signal }) => fetchOfflineUpload(uploadId as string, signal),
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
    queryFn: ({ signal }) =>
      fetchOfflineUploadPreview(uploadId as string, sampleSize, signal),
    enabled: enabled && uploadId !== null && uploadId.length > 0,
    staleTime: 10_000,
  });
}

export function useOfflineUploadValidation(uploadId: string | null, enabled = true) {
  return useQuery<OfflineUploadValidationResponse, Error>({
    queryKey: ["offline-upload-validation", uploadId],
    queryFn: ({ signal }) =>
      fetchOfflineUploadValidation(uploadId as string, signal),
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
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
      invalidateOpsDatasetQueries(queryClient);
      if (data.meta.job_id) {
        void queryClient.invalidateQueries({
          queryKey: ["pipeline", "execution", "import_job", data.meta.job_id],
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
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "executions"],
      });
      void queryClient.invalidateQueries({ queryKey: ["pipeline", "overview"] });
      void queryClient.invalidateQueries({
        queryKey: ["pipeline", "dagster-runs"],
      });
      invalidateOpsDatasetQueries(queryClient);
      void queryClient.invalidateQueries({ queryKey: ["ops", "metrics"] });
      if (data.data.load_job_id) {
        void queryClient.invalidateQueries({
          queryKey: [
            "pipeline",
            "execution",
            "import_job",
            data.data.load_job_id,
          ],
        });
      }
    },
  });
}
