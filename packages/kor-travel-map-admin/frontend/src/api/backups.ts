/**
 * `/v1/admin/backups/*` backup/restore hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteJson, getJson, postJson } from "./client";
import type { components } from "./types";

type BackupSchemas = components["schemas"];

export type BackupRecord = BackupSchemas["BackupRecord"];
export type BackupListResponse = BackupSchemas["BackupListResponse"];
export type BackupDeleteResponse = BackupSchemas["BackupDeleteResponse"];
export type BackupOperationResponse = BackupSchemas["BackupOperationResponse"];
export type BackupRunRequest = BackupSchemas["BackupRunRequest"];
export type RestoreRunRequest = BackupSchemas["RestoreRunRequest"];
export type RestoreSwapRequest = BackupSchemas["RestoreSwapRequest"];

function fetchBackups(signal?: AbortSignal): Promise<BackupListResponse> {
  return getJson<BackupListResponse>("/v1/admin/backups", { signal });
}

function createBackup(body: BackupRunRequest): Promise<BackupOperationResponse> {
  return postJson<BackupOperationResponse>("/v1/admin/backups", body);
}

function deleteBackup(backupId: string): Promise<BackupDeleteResponse> {
  return deleteJson<BackupDeleteResponse>(
    `/v1/admin/backups/${encodeURIComponent(backupId)}`,
  );
}

function restoreBackup({
  backupId,
  body,
}: {
  backupId: string;
  body: RestoreRunRequest;
}): Promise<BackupOperationResponse> {
  return postJson<BackupOperationResponse>(
    `/v1/admin/restore/${encodeURIComponent(backupId)}`,
    body,
  );
}

function planRestoreSwap({
  backupId,
  body,
}: {
  backupId: string;
  body: RestoreSwapRequest;
}): Promise<BackupOperationResponse> {
  return postJson<BackupOperationResponse>(
    `/v1/admin/restore/${encodeURIComponent(backupId)}/swap`,
    body,
  );
}

export function useBackups() {
  return useQuery<BackupListResponse, Error>({
    queryKey: ["admin", "backups"],
    queryFn: ({ signal }) => fetchBackups(signal),
    staleTime: 10_000,
  });
}

export function useCreateBackupMutation() {
  const queryClient = useQueryClient();
  return useMutation<BackupOperationResponse, Error, BackupRunRequest>({
    mutationFn: createBackup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "backups"] });
    },
  });
}

export function useDeleteBackupMutation() {
  const queryClient = useQueryClient();
  return useMutation<BackupDeleteResponse, Error, string>({
    mutationFn: deleteBackup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "backups"] });
    },
  });
}

export function useRestoreBackupMutation() {
  return useMutation<
    BackupOperationResponse,
    Error,
    { backupId: string; body: RestoreRunRequest }
  >({
    mutationFn: restoreBackup,
  });
}

export function useRestoreSwapMutation() {
  return useMutation<
    BackupOperationResponse,
    Error,
    { backupId: string; body: RestoreSwapRequest }
  >({
    mutationFn: planRestoreSwap,
  });
}
