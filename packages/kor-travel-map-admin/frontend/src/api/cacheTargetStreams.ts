/**
 * cache target generation/outbox 운영 화면 API.
 *
 * ADR-081 service route는 브라우저에서 직접 호출하지 않는다. 이 모듈은 operator용
 * `/ops/*` read와 `/admin/*` recovery command만 BFF(`/api/proxy`)를 통해 호출한다.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  domainCommandSlot,
  getJson,
  postJson,
  withDomainIdempotencySubmission,
} from "./client";

interface ApiMeta {
  duration_ms?: number;
  request_id?: string;
  page?: {
    page_size?: number;
    next_cursor?: string | null;
    total?: number | null;
  };
}

interface RawSnapshotStatus {
  snapshot_id: string;
  count: number;
  merkle_root: string;
  high_watermark_cursor: string;
  created_at: string;
}

interface RawCacheTargetStreamStatus {
  external_system: string;
  restore_epoch: number;
  control_version: number;
  consumer_enabled: boolean;
  state: string;
  pending_count: number;
  leased_count: number;
  retry_count: number;
  dead_count: number;
  delivered_count: number;
  superseded_count: number;
  blocked_event_id: string | null;
  last_snapshot: RawSnapshotStatus | null;
  updated_at: string;
}

interface RawCacheTargetDeadLetter {
  event_id: string;
  event_type: string;
  external_system?: string | null;
  relay_order: number;
  target_key: string;
  restore_epoch: number;
  source_generation: number;
  target_sequence: number;
  attempt_count: number;
  error_class: string | null;
  error_code: string | null;
  payload_fingerprint: string;
  delivery_version: number;
  entity_tag: string;
  occurred_at: string;
  updated_at: string;
}

interface RawRecoveryOperationReceipt {
  operation_id: string;
  status: "accepted" | string;
  status_url: string | null;
}

interface RawStreamStatusResponse {
  data: { items: RawCacheTargetStreamStatus[] };
  meta: ApiMeta;
}

interface RawDeadLetterListResponse {
  data: { items: RawCacheTargetDeadLetter[] };
  meta: ApiMeta;
}

interface RawDeadLetterDetailResponse {
  data: RawCacheTargetDeadLetter;
  meta: ApiMeta;
}

interface RawRecoveryOperationResponse {
  data: RawRecoveryOperationReceipt;
  meta: ApiMeta;
}

export interface SnapshotStatus {
  snapshotId: string;
  count: number;
  merkleRoot: string;
  highWatermarkCursor: string;
  createdAt: string;
}

export interface CacheTargetStreamStatus {
  externalSystem: string;
  restoreEpoch: number;
  controlVersion: number;
  consumerEnabled: boolean;
  state: string;
  pendingCount: number;
  leasedCount: number;
  retryCount: number;
  deadCount: number;
  deliveredCount: number;
  supersededCount: number;
  blockedEventId: string | null;
  lastSnapshot: SnapshotStatus | null;
  updatedAt: string;
}

export interface CacheTargetDeadLetter {
  eventId: string;
  eventType: string;
  externalSystem: string | null;
  relayOrder: number;
  targetKey: string;
  restoreEpoch: number;
  sourceGeneration: number;
  targetSequence: number;
  attemptCount: number;
  errorClass: string | null;
  errorCode: string | null;
  payloadFingerprint: string;
  deliveryVersion: number;
  entityTag: string;
  occurredAt: string;
  updatedAt: string;
}

export interface RecoveryOperationReceipt {
  operationId: string;
  status: string;
  statusUrl: string | null;
}

export interface CacheTargetStreamStatusResponse {
  data: { items: CacheTargetStreamStatus[] };
  meta: ApiMeta;
}

export interface CacheTargetDeadLetterListResponse {
  data: { items: CacheTargetDeadLetter[] };
  meta: ApiMeta;
}

export interface CacheTargetDeadLetterDetailResponse {
  data: CacheTargetDeadLetter;
  meta: ApiMeta;
}

export interface RecoveryOperationResponse {
  data: RecoveryOperationReceipt;
  meta: ApiMeta;
}

export interface ReplayCacheTargetDeadLetterRequest {
  eventId: string;
  entityTag: string;
  reason: string;
}

export interface RequestCacheTargetReconciliationRequest {
  externalSystem: string;
  reason: string;
}

function mapSnapshot(item: RawSnapshotStatus): SnapshotStatus {
  return {
    count: item.count,
    createdAt: item.created_at,
    highWatermarkCursor: item.high_watermark_cursor,
    merkleRoot: item.merkle_root,
    snapshotId: item.snapshot_id,
  };
}

function mapStreamStatus(
  item: RawCacheTargetStreamStatus,
): CacheTargetStreamStatus {
  return {
    blockedEventId: item.blocked_event_id,
    consumerEnabled: item.consumer_enabled,
    controlVersion: item.control_version,
    deadCount: item.dead_count,
    deliveredCount: item.delivered_count,
    externalSystem: item.external_system,
    lastSnapshot: item.last_snapshot ? mapSnapshot(item.last_snapshot) : null,
    leasedCount: item.leased_count,
    pendingCount: item.pending_count,
    restoreEpoch: item.restore_epoch,
    retryCount: item.retry_count,
    state: item.state,
    supersededCount: item.superseded_count,
    updatedAt: item.updated_at,
  };
}

function mapDeadLetter(item: RawCacheTargetDeadLetter): CacheTargetDeadLetter {
  return {
    attemptCount: item.attempt_count,
    deliveryVersion: item.delivery_version,
    entityTag: item.entity_tag,
    errorClass: item.error_class,
    errorCode: item.error_code,
    eventId: item.event_id,
    eventType: item.event_type,
    externalSystem: item.external_system ?? null,
    occurredAt: item.occurred_at,
    payloadFingerprint: item.payload_fingerprint,
    relayOrder: item.relay_order,
    restoreEpoch: item.restore_epoch,
    sourceGeneration: item.source_generation,
    targetKey: item.target_key,
    targetSequence: item.target_sequence,
    updatedAt: item.updated_at,
  };
}

function mapRecoveryOperation(
  item: RawRecoveryOperationReceipt,
): RecoveryOperationReceipt {
  return {
    operationId: item.operation_id,
    status: item.status,
    statusUrl: item.status_url,
  };
}

function mapStreamStatusResponse(
  response: RawStreamStatusResponse,
): CacheTargetStreamStatusResponse {
  return {
    data: { items: response.data.items.map(mapStreamStatus) },
    meta: response.meta,
  };
}

function mapDeadLetterListResponse(
  response: RawDeadLetterListResponse,
): CacheTargetDeadLetterListResponse {
  return {
    data: { items: response.data.items.map(mapDeadLetter) },
    meta: response.meta,
  };
}

function mapDeadLetterDetailResponse(
  response: RawDeadLetterDetailResponse,
): CacheTargetDeadLetterDetailResponse {
  return {
    data: mapDeadLetter(response.data),
    meta: response.meta,
  };
}

function mapRecoveryOperationResponse(
  response: RawRecoveryOperationResponse,
): RecoveryOperationResponse {
  return {
    data: mapRecoveryOperation(response.data),
    meta: response.meta,
  };
}

function streamQueriesToInvalidate() {
  return [
    ["cache-target-streams"] as const,
    ["cache-target-dead-letters"] as const,
  ];
}

export function fetchCacheTargetStreamStatus(
  signal?: AbortSignal,
): Promise<CacheTargetStreamStatusResponse> {
  return getJson<RawStreamStatusResponse>("/v1/ops/cache-target-streams", {
    signal,
  }).then(mapStreamStatusResponse);
}

export function fetchCacheTargetDeadLetters(
  signal?: AbortSignal,
): Promise<CacheTargetDeadLetterListResponse> {
  return getJson<RawDeadLetterListResponse>(
    "/v1/ops/cache-target-event-dead-letters",
    { signal },
  ).then(mapDeadLetterListResponse);
}

export function fetchCacheTargetDeadLetter(
  eventId: string,
  signal?: AbortSignal,
): Promise<CacheTargetDeadLetterDetailResponse> {
  return getJson<RawDeadLetterDetailResponse>(
    `/v1/ops/cache-target-event-dead-letters/${encodeURIComponent(eventId)}`,
    { signal },
  ).then(mapDeadLetterDetailResponse);
}

export function replayCacheTargetDeadLetter(
  request: ReplayCacheTargetDeadLetterRequest,
): Promise<RecoveryOperationResponse> {
  const body = { reason: request.reason };
  return withDomainIdempotencySubmission(
    domainCommandSlot("admin.cache-target-dead-letter.replay", request.eventId),
    { body, entityTag: request.entityTag, eventId: request.eventId },
    (submission, idempotencyKey) =>
      postJson<RawRecoveryOperationResponse>(
        `/v1/admin/cache-target-event-dead-letters/${encodeURIComponent(
          submission.eventId,
        )}/replays`,
        submission.body,
        {
          headers: {
            "Idempotency-Key": idempotencyKey,
            "If-Match": submission.entityTag,
          },
        },
      ).then(mapRecoveryOperationResponse),
  );
}

export function requestCacheTargetReconciliation(
  request: RequestCacheTargetReconciliationRequest,
): Promise<RecoveryOperationResponse> {
  const body = {
    external_system: request.externalSystem,
    reason: request.reason,
  };
  return withDomainIdempotencySubmission(
    domainCommandSlot(
      "admin.cache-target-reconciliation.request",
      request.externalSystem,
    ),
    body,
    (submission, idempotencyKey) =>
      postJson<RawRecoveryOperationResponse>(
        "/v1/admin/cache-target-reconciliations",
        submission,
        { headers: { "Idempotency-Key": idempotencyKey } },
      ).then(mapRecoveryOperationResponse),
  );
}

export function useCacheTargetStreamStatus() {
  return useQuery<CacheTargetStreamStatusResponse, Error>({
    queryKey: ["cache-target-streams"],
    queryFn: ({ signal }) => fetchCacheTargetStreamStatus(signal),
    staleTime: 15_000,
  });
}

export function useCacheTargetDeadLetters() {
  return useQuery<CacheTargetDeadLetterListResponse, Error>({
    queryKey: ["cache-target-dead-letters"],
    queryFn: ({ signal }) => fetchCacheTargetDeadLetters(signal),
    staleTime: 15_000,
  });
}

export function useCacheTargetDeadLetter(eventId: string | null) {
  return useQuery<CacheTargetDeadLetterDetailResponse, Error>({
    queryKey: ["cache-target-dead-letter", eventId],
    queryFn: ({ signal }) =>
      fetchCacheTargetDeadLetter(eventId as string, signal),
    enabled: eventId !== null,
    staleTime: 15_000,
  });
}

export function useReplayCacheTargetDeadLetterMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    RecoveryOperationResponse,
    Error,
    ReplayCacheTargetDeadLetterRequest
  >({
    mutationFn: replayCacheTargetDeadLetter,
    onSuccess: async (_data, variables) => {
      await Promise.all([
        ...streamQueriesToInvalidate().map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
        queryClient.invalidateQueries({
          queryKey: ["cache-target-dead-letter", variables.eventId],
        }),
      ]);
    },
  });
}

export function useRequestCacheTargetReconciliationMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    RecoveryOperationResponse,
    Error,
    RequestCacheTargetReconciliationRequest
  >({
    mutationFn: requestCacheTargetReconciliation,
    onSuccess: async () => {
      await Promise.all(
        streamQueriesToInvalidate().map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
    },
  });
}
