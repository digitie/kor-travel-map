/**
 * `/v1/admin/backups/*` backup/restore hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearDomainCreateCommandSlot,
  domainCommandSlot,
  domainCreateCommandSlot,
  getJson,
  postJson,
  withDomainIdempotencySubmission,
} from "./client";
import type { components } from "./types";

type BackupSchemas = components["schemas"];

export type BackupRecord = BackupSchemas["BackupRecord"];
export type BackupListResponse = BackupSchemas["BackupListResponse"];
export type BackupOperationResponse = BackupSchemas["BackupOperationResponse"];
export type BackupRunRequest = BackupSchemas["BackupRunRequest"];
export type RestoreRunRequest = BackupSchemas["RestoreRunRequest"];
export type RestoreSwapRequest = BackupSchemas["RestoreSwapRequest"];

function fetchBackups(signal?: AbortSignal): Promise<BackupListResponse> {
  return getJson<BackupListResponse>("/v1/admin/backups", { signal });
}

function createBackup(body: BackupRunRequest): Promise<BackupOperationResponse> {
  const operation = "admin.backup.create";
  return withDomainIdempotencySubmission(
    domainCreateCommandSlot(operation),
    body,
    (submission, idempotencyKey) =>
      postJson<BackupOperationResponse>("/v1/admin/backups", submission, {
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    { onRelease: () => clearDomainCreateCommandSlot(operation) },
  );
}


function restoreBackup({
  backupId,
  body,
}: {
  backupId: string;
  body: RestoreRunRequest;
}): Promise<BackupOperationResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.backup.restore", backupId),
    { backupId, body },
    (submission, idempotencyKey) =>
      postJson<BackupOperationResponse>(
        `/v1/admin/restore/${encodeURIComponent(submission.backupId)}`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
  );
}

function planRestoreSwap({
  backupId,
  body,
}: {
  backupId: string;
  body: RestoreSwapRequest;
}): Promise<BackupOperationResponse> {
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.backup.swap", backupId),
    { backupId, body },
    (submission, idempotencyKey) =>
      postJson<BackupOperationResponse>(
        `/v1/admin/restore/${encodeURIComponent(submission.backupId)}/swap`,
        submission.body,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ),
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


export function useRestoreBackupMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    BackupOperationResponse,
    Error,
    { backupId: string; body: RestoreRunRequest }
  >({
    mutationFn: restoreBackup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "backups"] });
    },
  });
}

export function useRestoreSwapMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    BackupOperationResponse,
    Error,
    { backupId: string; body: RestoreSwapRequest }
  >({
    mutationFn: planRestoreSwap,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "backups"] });
    },
  });
}
