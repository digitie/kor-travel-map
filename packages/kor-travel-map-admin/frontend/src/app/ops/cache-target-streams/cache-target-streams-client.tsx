"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list + inspector rail) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";

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
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

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

const REPLAY_REASON_HINT = "사유를 입력하면 replay 요청이 활성화됩니다.";
const RECONCILE_REASON_HINT = "사유를 입력하면 reconciliation 요청이 활성화됩니다.";

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
    // replay는 되돌릴 수 있는 재시도(동일 identity만 pending으로 복귀)라 destructive 톤을 쓰지 않는다(m11).
    const ok = await confirm({
      title: `${shortId(selectedDeadLetter.eventId, 18)} event를 replay할까요?`,
      description:
        "동일 event identity와 delivery fingerprint만 pending으로 되돌립니다. 412 응답은 최신 ETag로 자동 재시도하지 않습니다.",
      confirmLabel: "replay 요청",
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

const streamColumns: ColumnDef<CacheTargetStreamStatus, unknown>[] = [
  {
    accessorKey: "externalSystem",
    header: "스트림",
    enableSorting: false,
    cell: ({ row }) => (
      <>
        <div className="font-medium">{row.original.externalSystem}</div>
        <div className="text-2xs text-text-secondary tabular-nums">
          epoch {formatCount(row.original.restoreEpoch)} · control{" "}
          {formatCount(row.original.controlVersion)}
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
    header: "relay backlog",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="text-xs tabular-nums">
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
    meta: { align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => formatCount(row.original.deadCount),
  },
  {
    accessorKey: "supersededCount",
    header: "superseded",
    enableSorting: false,
    meta: { align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => formatCount(row.original.supersededCount),
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
];

const deadLetterColumns: ColumnDef<CacheTargetDeadLetter, unknown>[] = [
  {
    id: "event",
    header: "event",
    enableSorting: false,
    cell: ({ row }) => (
      <>
        <div className="font-medium">{row.original.eventType}</div>
        <div className="font-mono text-2xs text-text-secondary slashed-zero">
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
      <span className="text-xs tabular-nums">
        relay {formatCount(row.original.relayOrder)} · seq{" "}
        {formatCount(row.original.targetSequence)}
      </span>
    ),
  },
  {
    accessorKey: "attemptCount",
    header: "시도",
    enableSorting: false,
    meta: { align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => formatCount(row.original.attemptCount),
  },
  {
    id: "error",
    header: "오류",
    enableSorting: false,
    cell: ({ row }) => {
      const code = row.original.errorCode ?? row.original.errorClass;
      return code ? (
        <span className="font-mono text-xs text-text-secondary">{code}</span>
      ) : (
        <span className="text-text-tertiary">{NULL_GLYPH}</span>
      );
    },
  },
];

function StreamSummary({
  isLoading,
  selectedStream,
  streams,
}: {
  isLoading: boolean;
  selectedStream: CacheTargetStreamStatus | null;
  streams: CacheTargetStreamStatus[];
}) {
  const totalBacklog = streams.reduce(
    (sum, item) => sum + item.pendingCount + item.leasedCount + item.retryCount,
    0,
  );
  const totalDead = streams.reduce((sum, item) => sum + item.deadCount, 0);
  const blockedStreams = streams.filter(
    (item) => item.blockedEventId !== null || item.deadCount > 0,
  ).length;
  const snapshot = selectedStream?.lastSnapshot ?? null;

  return (
    <StatStrip
      ariaLabel="cache target stream 요약"
      isLoading={isLoading}
      items={[
        {
          key: "streams",
          label: "stream",
          value: streams.length,
          unit: "개",
          caption: selectedStream
            ? `선택: ${selectedStream.externalSystem}`
            : "선택된 stream 없음",
        },
        {
          key: "backlog",
          label: "relay backlog",
          value: totalBacklog,
          unit: "건",
          caption: "pending + lease + retry",
        },
        {
          key: "dead",
          label: "dead / blocked",
          value: totalDead,
          unit: "건",
          tone: totalDead > 0 || blockedStreams > 0 ? "destructive" : "success",
          caption: `blocked stream ${formatCount(blockedStreams)}개`,
        },
        {
          key: "checksum",
          label: "snapshot checksum",
          value: snapshot ? (
            <span className="font-mono text-sm slashed-zero">
              {shortId(snapshot.merkleRoot, 18)}
            </span>
          ) : null,
          caption: snapshot
            ? `${formatCount(snapshot.count)} rows`
            : "snapshot 없음",
        },
      ]}
    />
  );
}

function StreamStatusSection({
  isLoading,
  onSelect,
  selectedStream,
  streams,
}: {
  isLoading: boolean;
  onSelect: (value: string) => void;
  selectedStream: CacheTargetStreamStatus | null;
  streams: CacheTargetStreamStatus[];
}) {
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
      <SectionCard
        description="epoch, fence/control revision, relay backlog과 checksum 상태입니다."
        title="Source stream 상태"
      >
        <DataTable
          ariaLabel="cache target source stream 상태"
          columns={streamColumns}
          data={streams}
          emptyState={{
            title: "stream 상태가 없습니다.",
            description: "cache target source stream이 등록되면 여기에 표시됩니다.",
          }}
          getRowId={(row) => row.externalSystem}
          isLoading={isLoading}
          isRowActive={(row) =>
            row.externalSystem === selectedStream?.externalSystem
          }
          skeletonRowCount={3}
          onRowClick={(row) => onSelect(row.externalSystem)}
        />
      </SectionCard>
      <SectionCard
        description="consumer enable, blocked event, fixed snapshot watermark입니다."
        headingLevel={3}
        title="선택 stream"
      >
        {selectedStream ? (
          <DetailList
            items={[
              {
                label: "external_system",
                value: selectedStream.externalSystem,
                mono: true,
              },
              {
                label: "consumer",
                value: (
                  <StatusBadge
                    status={selectedStream.consumerEnabled ? "active" : "disabled"}
                  />
                ),
              },
              {
                label: "blocked_event",
                value: selectedStream.blockedEventId
                  ? shortId(selectedStream.blockedEventId, 24)
                  : null,
                mono: true,
              },
              {
                label: "snapshot",
                value: selectedStream.lastSnapshot?.snapshotId ?? null,
                mono: true,
              },
              {
                label: "high_watermark",
                value: selectedStream.lastSnapshot?.highWatermarkCursor ?? null,
                mono: true,
              },
              {
                label: "Merkle root",
                value: selectedStream.lastSnapshot?.merkleRoot ?? null,
                mono: true,
                copyable: true,
              },
            ]}
            layout="inline"
          />
        ) : (
          <EmptyState
            description="epoch와 checksum 상세가 여기에 표시됩니다."
            size="sm"
            title="stream을 선택하세요."
          />
        )}
      </SectionCard>
    </div>
  );
}

function RecoveryReceipt({
  result,
}: {
  result: RecoveryOperationReceipt | null;
}) {
  // 접수 결과는 트리거 옆에 한 줄로(M39) — role=status 하나만 두어 live 알림이 겹치지 않게 한다.
  return (
    <p
      aria-live="polite"
      className="min-h-[1lh] text-xs text-text-secondary tabular-nums"
      data-testid="recovery-receipt"
      role="status"
    >
      {result ? (
        <>
          접수됨 · <span className="font-mono">{result.operationId}</span> ·{" "}
          {statusLabel(result.status)}
        </>
      ) : null}
    </p>
  );
}

function DeadLetterRecoverySection({
  deadLetters,
  isLoading,
  onReconciliationRequest,
  onReplayRequest,
  onSelectEvent,
  receipt,
  reconcilePending,
  reconcileReason,
  replayPending,
  replayReason,
  selectedDeadLetter,
  selectedStream,
  setReconcileReason,
  setReplayReason,
}: {
  deadLetters: CacheTargetDeadLetter[];
  isLoading: boolean;
  onReconciliationRequest: () => void;
  onReplayRequest: () => void;
  onSelectEvent: (value: string) => void;
  receipt: RecoveryOperationReceipt | null;
  reconcilePending: boolean;
  reconcileReason: string;
  replayPending: boolean;
  replayReason: string;
  selectedDeadLetter: CacheTargetDeadLetter | null;
  selectedStream: CacheTargetStreamStatus | null;
  setReconcileReason: (value: string) => void;
  setReplayReason: (value: string) => void;
}) {
  const replayDisabledReason =
    selectedDeadLetter === null
      ? "replay할 dead letter를 먼저 선택하세요."
      : replayReason.trim().length === 0
        ? REPLAY_REASON_HINT
        : undefined;
  const reconcileDisabledReason =
    selectedStream === null
      ? "reconciliation을 요청할 stream을 먼저 선택하세요."
      : reconcileReason.trim().length === 0
        ? RECONCILE_REASON_HINT
        : undefined;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
      <SectionCard
        description="poison event와 replay 전 확인해야 할 delivery fingerprint입니다."
        title="Dead letter"
      >
        <DataTable
          ariaLabel="cache target dead letter"
          columns={deadLetterColumns}
          data={deadLetters}
          emptyState={{
            title: "dead letter가 없습니다.",
            description: "전달에 실패한 event가 생기면 여기에 쌓입니다.",
          }}
          getRowId={(row) => row.eventId}
          isLoading={isLoading}
          isRowActive={(row) => row.eventId === selectedDeadLetter?.eventId}
          skeletonRowCount={3}
          onRowClick={(row) => onSelectEvent(row.eventId)}
        />
      </SectionCard>
      <SectionCard
        contentClassName="space-y-0 divide-y divide-border"
        description="replay와 reconciliation은 operator API에서 접수됩니다."
        headingLevel={3}
        title="복구 작업"
      >
        <section aria-labelledby="cache-recovery-replay" className="space-y-3 pb-4">
          <h4
            className="text-xs font-semibold text-text-primary"
            id="cache-recovery-replay"
          >
            Dead replay
          </h4>
          {selectedDeadLetter ? (
            <DetailList
              items={[
                {
                  label: "event_id",
                  value: selectedDeadLetter.eventId,
                  mono: true,
                  copyable: true,
                },
                {
                  label: "If-Match",
                  value: selectedDeadLetter.entityTag,
                  mono: true,
                },
                {
                  label: "fingerprint",
                  value: shortId(selectedDeadLetter.payloadFingerprint, 24),
                  mono: true,
                },
              ]}
              layout="inline"
            />
          ) : (
            <p className="text-xs text-text-secondary">
              dead letter 목록에서 행을 선택하면 event identity가 표시됩니다.
            </p>
          )}
          {/* 힌트는 아직 사유가 비어 있을 때만 — 채우고 나면 같은 문장이 노이즈가 된다. */}
          <FormField
            hint={
              replayReason.trim().length === 0 ? REPLAY_REASON_HINT : undefined
            }
            label="사유"
            value={replayReason}
            onChange={(event) => setReplayReason(event.target.value)}
          />
          <Button
            disabled={replayDisabledReason !== undefined}
            disabledReason={replayDisabledReason}
            loading={replayPending}
            type="button"
            onClick={onReplayRequest}
          >
            replay 요청
          </Button>
        </section>
        <section
          aria-labelledby="cache-recovery-reconcile"
          className="space-y-3 pt-4"
        >
          <h4
            className="text-xs font-semibold text-text-primary"
            id="cache-recovery-reconcile"
          >
            Reconciliation
          </h4>
          <p className="text-xs text-text-secondary">
            {selectedStream
              ? `대상 stream: ${selectedStream.externalSystem}`
              : "stream 목록에서 행을 선택하세요."}
          </p>
          <FormField
            hint={
              reconcileReason.trim().length === 0
                ? RECONCILE_REASON_HINT
                : undefined
            }
            label="사유"
            value={reconcileReason}
            onChange={(event) => setReconcileReason(event.target.value)}
          />
          <Button
            disabled={reconcileDisabledReason !== undefined}
            disabledReason={reconcileDisabledReason}
            loading={reconcilePending}
            type="button"
            variant="outline"
            onClick={onReconciliationRequest}
          >
            reconciliation 요청
          </Button>
        </section>
        <div className="pt-4">
          <RecoveryReceipt result={receipt} />
        </div>
      </SectionCard>
    </div>
  );
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
  return (
    <AdminShell
      actions={
        <Button
          loading={model.isRefreshing}
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
            <AlertTitle>stream 상태를 불러오지 못했습니다</AlertTitle>
            <AlertDescription>{model.statusError}</AlertDescription>
          </Alert>
        ) : null}
        {model.mutationError ? (
          <Alert variant="destructive">
            <AlertTitle>복구 명령 실패</AlertTitle>
            <AlertDescription>{model.mutationError}</AlertDescription>
          </Alert>
        ) : null}

        <StreamSummary
          isLoading={model.isLoading}
          selectedStream={selectedStream}
          streams={model.streams}
        />
        <StreamStatusSection
          isLoading={model.isLoading}
          onSelect={setSelectedExternalSystem}
          selectedStream={selectedStream}
          streams={model.streams}
        />
        <DeadLetterRecoverySection
          deadLetters={model.deadLetters}
          isLoading={model.isLoading}
          onReconciliationRequest={onReconciliationRequest}
          onReplayRequest={onReplayRequest}
          onSelectEvent={setSelectedEventId}
          receipt={model.replayResult ?? model.reconcileResult}
          reconcilePending={reconcilePending}
          reconcileReason={reconcileReason}
          replayPending={replayPending}
          replayReason={replayReason}
          selectedDeadLetter={selectedDeadLetter}
          selectedStream={selectedStream}
          setReconcileReason={setReconcileReason}
          setReplayReason={setReplayReason}
        />
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
