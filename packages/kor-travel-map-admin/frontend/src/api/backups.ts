/**
 * `/v1/admin/backups/*` cold-backup hooks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearDomainCreateCommandSlot,
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
