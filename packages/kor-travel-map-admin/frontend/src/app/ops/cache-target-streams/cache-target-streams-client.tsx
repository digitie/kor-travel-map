"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  RefreshCwIcon,
  RotateCcwIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  type CacheTargetDeadLetter,
  type CacheTargetStreamStatus,
  type RecoveryOperationReceipt,
  useCacheTargetDeadLetter,
  useCacheTargetDeadLetters,
  useCacheTargetStreamStatus,
  useReplayCacheTargetDeadLetterMutation,
  useRequestCacheTargetReconciliationMutation,
} from "@/api/cacheTargetStreams";
import { ApiClientError } from "@/api/client";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field";
import { formatDateTime, shortId } from "@/lib/format";

type CacheTargetStreamsViewModel = {
  streams: CacheTargetStreamStatus[];
  deadLetters: CacheTargetDeadLetter[];
  isLoading: boolean;
  isRefreshing: boolean;
  statusError: string | null;
  mutationError: string | null;
  replayResult: RecoveryOperationReceipt | null;
  reconcileResult: RecoveryOperationReceipt | null;
};

function formatCount(value: number) {
  return value.toLocaleString("ko-KR");
}

function selectedOrFirst<T extends { externalSystem: string }>(
  items: T[],
  externalSystem: string | null,
): T | null {
  return (
    items.find((item) => item.externalSystem === externalSystem) ??
    items[0] ??
    null
  );
}

function errorMessage(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null;
  }
  if (error instanceof ApiClientError && error.problem) {
    const code = error.problem.code ? `${error.problem.code}: ` : "";
    return `${code}${error.problem.detail}`;
  }
  return error instanceof Error ? error.message : String(error);
}

function useCacheTargetStreamsController() {
  const streams = useCacheTargetStreamStatus();
  const deadLetters = useCacheTargetDeadLetters();
  const replay = useReplayCacheTargetDeadLetterMutation();
  const reconcile = useRequestCacheTargetReconciliationMutation();
  const [selectedExternalSystem, setSelectedExternalSystem] = useState<string | null>(
    null,
  );
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [replayReason, setReplayReason] = useState("");
  const [reconcileReason, setReconcileReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const confirm = useConfirm();

  const streamItems = streams.data?.data.items ?? [];
  const deadLetterItems = deadLetters.data?.data.items ?? [];
  const selectedStream = selectedOrFirst(streamItems, selectedExternalSystem);
  const defaultEventId = selectedStream?.blockedEventId ?? deadLetterItems[0]?.eventId ?? null;
  const effectiveSelectedEventId =
    deadLetterItems.some((item) => item.eventId === selectedEventId)
      ? selectedEventId
      : defaultEventId;
  const deadLetterDetail = useCacheTargetDeadLetter(effectiveSelectedEventId);
  const selectedDeadLetter =
    deadLetterDetail.data?.data ??
    deadLetterItems.find((item) => item.eventId === effectiveSelectedEventId) ??
    null;
  const replayResult = replay.data?.data ?? null;
  const reconcileResult = reconcile.data?.data ?? null;
  const mutationError =
    errorMessage(replay.error) ?? errorMessage(reconcile.error) ?? reasonError;
  const model: CacheTargetStreamsViewModel = {
    deadLetters: deadLetterItems,
    isLoading: streams.isLoading || deadLetters.isLoading,
    isRefreshing:
      streams.isFetching ||
      deadLetters.isFetching ||
      deadLetterDetail.isFetching,
    mutationError,
    reconcileResult,
    replayResult,
    statusError:
      errorMessage(streams.error) ??
      errorMessage(deadLetters.error) ??
      errorMessage(deadLetterDetail.error),
    streams: streamItems,
  };

  const refresh = () => {
    void streams.refetch();
    void deadLetters.refetch();
    if (effectiveSelectedEventId) {
      void deadLetterDetail.refetch();
    }
  };

  const requestReplay = async () => {
    setReasonError(null);
    const reason = replayReason.trim();
    if (!selectedDeadLetter) {
      setReasonError("replay할 dead letter를 선택하세요.");
      return;
    }
    if (reason.length === 0) {
      setReasonError("replay 사유를 입력하세요.");
      return;
    }
    const ok = await confirm({
      title: `${shortId(selectedDeadLetter.eventId, 18)} event를 replay할까요?`,
      description:
        "동일 event identity와 delivery fingerprint만 pending으로 되돌립니다. 412 응답은 최신 ETag로 자동 재시도하지 않습니다.",
      confirmLabel: "replay 요청",
      destructive: true,
    });
    if (!ok) return;
    reconcile.reset();
    replay.mutate({
      entityTag: selectedDeadLetter.entityTag,
      eventId: selectedDeadLetter.eventId,
      reason,
    });
  };

  const requestReconciliation = async () => {
    setReasonError(null);
    const reason = reconcileReason.trim();
    if (!selectedStream) {
      setReasonError("reconciliation을 요청할 stream을 선택하세요.");
      return;
    }
    if (reason.length === 0) {
      setReasonError("reconciliation 사유를 입력하세요.");
      return;
    }
    const ok = await confirm({
      title: `${selectedStream.externalSystem} stream reconciliation을 요청할까요?`,
      description:
        "full snapshot checksum을 다시 맞추기 위한 operator 작업을 생성합니다.",
      confirmLabel: "reconciliation 요청",
    });
    if (!ok) return;
    replay.reset();
    reconcile.mutate({
      externalSystem: selectedStream.externalSystem,
      reason,
    });
  };

  return {
    model,
    reconcile,
    reconcileReason,
    refresh,
    replay,
    replayReason,
    requestReconciliation,
    requestReplay,
    selectedDeadLetter,
    selectedStream,
    setReconcileReason,
    setReplayReason,
    setSelectedEventId,
    setSelectedExternalSystem,
  };
}

function CacheTargetStreamsClientView({
  model,
  onRefresh,
  onReconciliationRequest,
  onReplayRequest,
  reconcilePending,
  reconcileReason,
  replayPending,
  replayReason,
  selectedDeadLetter,
  selectedStream,
  setReconcileReason,
  setReplayReason,
  setSelectedEventId,
  setSelectedExternalSystem,
}: {
  model: CacheTargetStreamsViewModel;
  onRefresh: () => void;
  onReconciliationRequest: () => void;
  onReplayRequest: () => void;
  reconcilePending: boolean;
  reconcileReason: string;
  replayPending: boolean;
  replayReason: string;
  selectedDeadLetter: CacheTargetDeadLetter | null;
  selectedStream: CacheTargetStreamStatus | null;
  setReconcileReason: (value: string) => void;
  setReplayReason: (value: string) => void;
  setSelectedEventId: (value: string) => void;
  setSelectedExternalSystem: (value: string) => void;
}) {
  const streamColumns = useMemo<
    ColumnDef<CacheTargetStreamStatus, unknown>[]
  >(
    () => [
      {
        accessorKey: "externalSystem",
        header: "stream",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.externalSystem}</div>
            <div className="font-mono text-xs text-text-tertiary">
              epoch {row.original.restoreEpoch} · control{" "}
              {row.original.controlVersion}
            </div>
          </>
        ),
      },
      {
        accessorKey: "state",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.state} />,
      },
      {
        id: "relay",
        header: "relay",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {formatCount(row.original.pendingCount)} pending /{" "}
            {formatCount(row.original.leasedCount)} lease /{" "}
            {formatCount(row.original.retryCount)} retry
          </span>
        ),
      },
      {
        accessorKey: "deadCount",
        header: "dead",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">{formatCount(row.original.deadCount)}</span>
        ),
      },
      {
        accessorKey: "updatedAt",
        header: "갱신",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.updatedAt)}
          </span>
        ),
      },
    ],
    [],
  );

  const deadLetterColumns = useMemo<
    ColumnDef<CacheTargetDeadLetter, unknown>[]
  >(
    () => [
      {
        id: "event",
        header: "event",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.eventType}</div>
            <div className="font-mono text-xs text-text-tertiary">
              {shortId(row.original.eventId, 18)}
            </div>
          </>
        ),
      },
      {
        accessorKey: "targetKey",
        header: "target",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.targetKey}</span>
        ),
      },
      {
        id: "order",
        header: "순서",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            relay {row.original.relayOrder} · seq {row.original.targetSequence}
          </span>
        ),
      },
      {
        accessorKey: "attemptCount",
        header: "시도",
        enableSorting: false,
      },
      {
        id: "error",
        header: "오류",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {row.original.errorCode ?? row.original.errorClass ?? "-"}
          </span>
        ),
      },
    ],
    [],
  );

  const totalBacklog = model.streams.reduce(
    (sum, item) => sum + item.pendingCount + item.leasedCount + item.retryCount,
    0,
  );
  const totalDead = model.streams.reduce((sum, item) => sum + item.deadCount, 0);
  const blockedStreams = model.streams.filter(
    (item) => item.blockedEventId !== null || item.deadCount > 0,
  ).length;
  const checksumLabel = selectedStream?.lastSnapshot
    ? shortId(selectedStream.lastSnapshot.merkleRoot, 18)
    : "-";
  const replayDisabled =
    selectedDeadLetter === null ||
    replayReason.trim().length === 0 ||
    replayPending;
  const reconcileDisabled =
    selectedStream === null ||
    reconcileReason.trim().length === 0 ||
    reconcilePending;

  return (
    <AdminShell
      actions={
        <Button
          disabled={model.isRefreshing}
          type="button"
          variant="outline"
          onClick={onRefresh}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="cache target source stream, relay backlog, dead letter, reconciliation과 fixed snapshot checksum을 한 화면에서 확인합니다."
      title="캐시 전파 스트림"
    >
      <div className="space-y-6">
        {model.statusError ? (
          <Alert variant="destructive">
            <AlertTitle>stream 상태 조회 실패</AlertTitle>
            <AlertDescription>{model.statusError}</AlertDescription>
          </Alert>
        ) : null}
        {model.mutationError ? (
          <Alert variant="destructive">
            <AlertTitle>복구 명령 실패</AlertTitle>
            <AlertDescription>{model.mutationError}</AlertDescription>
          </Alert>
        ) : null}
        {model.replayResult || model.reconcileResult ? (
          <Alert>
            <CheckCircle2Icon data-icon="inline-start" />
            <AlertTitle>복구 명령 접수</AlertTitle>
            <AlertDescription>
              {(model.replayResult ?? model.reconcileResult)?.operationId} ·{" "}
              {(model.replayResult ?? model.reconcileResult)?.status}
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-4">
          <Card size="sm">
            <CardHeader>
              <CardDescription>stream</CardDescription>
              <CardTitle>{formatCount(model.streams.length)} 개</CardTitle>
            </CardHeader>
            <CardContent className="text-[13px] text-text-secondary">
              {selectedStream?.externalSystem ?? "선택된 stream 없음"}
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader>
              <CardDescription>relay backlog</CardDescription>
              <CardTitle>{formatCount(totalBacklog)} 건</CardTitle>
            </CardHeader>
            <CardContent className="text-[13px] text-text-secondary">
              pending + lease + retry
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader>
              <CardDescription>dead / blocked</CardDescription>
              <CardTitle>{formatCount(totalDead)} 건</CardTitle>
            </CardHeader>
            <CardContent className="text-[13px] text-text-secondary">
              blocked stream {formatCount(blockedStreams)} 개
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader>
              <CardDescription>snapshot checksum</CardDescription>
              <CardTitle className="break-all font-mono text-[14px]">
                {checksumLabel}
              </CardTitle>
            </CardHeader>
            <CardContent className="text-[13px] text-text-secondary">
              {selectedStream?.lastSnapshot
                ? `${formatCount(selectedStream.lastSnapshot.count)} rows`
                : "snapshot 없음"}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <Card>
            <CardHeader>
              <CardTitle>Source stream 상태</CardTitle>
              <CardDescription>
                epoch, fence/control revision, relay backlog과 checksum 상태입니다.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DataTable
                ariaLabel="cache target source stream 상태"
                columns={streamColumns}
                data={model.streams}
                emptyMessage="stream 상태가 없습니다."
                getRowId={(row) => row.externalSystem}
                isLoading={model.isLoading}
                isRowActive={(row) =>
                  row.externalSystem === selectedStream?.externalSystem
                }
                onRowClick={(row) => setSelectedExternalSystem(row.externalSystem)}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>선택 stream</CardTitle>
              <CardDescription>
                consumer enable, blocked event, fixed snapshot watermark입니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {selectedStream ? (
                <>
                  <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2 text-[13px]">
                    <dt className="text-text-tertiary">external_system</dt>
                    <dd className="font-mono">{selectedStream.externalSystem}</dd>
                    <dt className="text-text-tertiary">consumer</dt>
                    <dd>
                      <StatusBadge
                        status={
                          selectedStream.consumerEnabled ? "enabled" : "disabled"
                        }
                      />
                    </dd>
                    <dt className="text-text-tertiary">blocked_event</dt>
                    <dd className="break-all font-mono">
                      {selectedStream.blockedEventId
                        ? shortId(selectedStream.blockedEventId, 24)
                        : "-"}
                    </dd>
                    <dt className="text-text-tertiary">snapshot</dt>
                    <dd className="break-all font-mono">
                      {selectedStream.lastSnapshot?.snapshotId ?? "-"}
                    </dd>
                    <dt className="text-text-tertiary">high_watermark</dt>
                    <dd className="break-all font-mono">
                      {selectedStream.lastSnapshot?.highWatermarkCursor ?? "-"}
                    </dd>
                  </dl>
                  {selectedStream.lastSnapshot ? (
                    <div className="rounded-xl bg-surface-subtle p-3 text-[13px]">
                      <div className="mb-1 font-semibold">Merkle root</div>
                      <div className="break-all font-mono text-text-secondary">
                        {selectedStream.lastSnapshot.merkleRoot}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="rounded-xl bg-surface-subtle p-4 text-[13px] text-text-secondary">
                  stream을 선택하면 epoch와 checksum 상세가 표시됩니다.
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <Card>
            <CardHeader>
              <CardTitle>Dead letter</CardTitle>
              <CardDescription>
                poison event와 replay 전 확인해야 할 delivery fingerprint입니다.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DataTable
                ariaLabel="cache target dead letter"
                columns={deadLetterColumns}
                data={model.deadLetters}
                emptyMessage="dead letter가 없습니다."
                getRowId={(row) => row.eventId}
                isLoading={model.isLoading}
                isRowActive={(row) => row.eventId === selectedDeadLetter?.eventId}
                onRowClick={(row) => setSelectedEventId(row.eventId)}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recovery action</CardTitle>
              <CardDescription>
                replay와 reconciliation은 operator API에서 접수됩니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-3 rounded-xl bg-surface-subtle p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <RotateCcwIcon className="size-4" />
                  Dead replay
                </div>
                <FormField
                  label="사유"
                  value={replayReason}
                  onChange={(event) => setReplayReason(event.target.value)}
                />
                {selectedDeadLetter ? (
                  <dl className="grid grid-cols-[7rem_1fr] gap-x-2 gap-y-1 text-[12px]">
                    <dt className="text-text-tertiary">event_id</dt>
                    <dd className="break-all font-mono">
                      {selectedDeadLetter.eventId}
                    </dd>
                    <dt className="text-text-tertiary">If-Match</dt>
                    <dd className="break-all font-mono">
                      {selectedDeadLetter.entityTag}
                    </dd>
                    <dt className="text-text-tertiary">fingerprint</dt>
                    <dd className="break-all font-mono">
                      {shortId(selectedDeadLetter.payloadFingerprint, 24)}
                    </dd>
                  </dl>
                ) : null}
                <Button
                  disabled={replayDisabled}
                  type="button"
                  onClick={onReplayRequest}
                >
                  {replayPending ? "replay 접수 중" : "replay 요청"}
                </Button>
              </div>

              <div className="space-y-3 rounded-xl bg-surface-subtle p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <AlertTriangleIcon className="size-4" />
                  Reconciliation
                </div>
                <FormField
                  label="사유"
                  value={reconcileReason}
                  onChange={(event) => setReconcileReason(event.target.value)}
                />
                <Button
                  disabled={reconcileDisabled}
                  type="button"
                  onClick={onReconciliationRequest}
                >
                  {reconcilePending
                    ? "reconciliation 접수 중"
                    : "reconciliation 요청"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </AdminShell>
  );
}

export function CacheTargetStreamsClient() {
  const controller = useCacheTargetStreamsController();
  return (
    <CacheTargetStreamsClientView
      model={controller.model}
      onRefresh={controller.refresh}
      onReconciliationRequest={() => void controller.requestReconciliation()}
      onReplayRequest={() => void controller.requestReplay()}
      reconcilePending={controller.reconcile.isPending}
      reconcileReason={controller.reconcileReason}
      replayPending={controller.replay.isPending}
      replayReason={controller.replayReason}
      selectedDeadLetter={controller.selectedDeadLetter}
      selectedStream={controller.selectedStream}
      setReconcileReason={controller.setReconcileReason}
      setReplayReason={controller.setReplayReason}
      setSelectedEventId={controller.setSelectedEventId}
      setSelectedExternalSystem={controller.setSelectedExternalSystem}
    />
  );
}
