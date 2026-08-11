"use client";

import { PlayIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ApiClientError } from "@/api/client";
import {
  type ExecutionKind,
  type JobEventLevel,
  useCancelExecutionMutation,
  usePipelineExecutionDetail,
  useRunNowUpdateRequestMutation,
} from "@/api/pipeline";
import { EntityLink } from "@/components/entity-link";
import { StatusBadge } from "@/components/status-badge";
import { statusLabel } from "@/lib/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { JsonViewer } from "@/components/json-viewer";
import { DetailList } from "@/components/detail-list";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { useConfirm } from "@/components/confirm-dialog";
import { formatDateTime, shortId } from "@/lib/format";

import {
  executionKindLabel,
  providerDatasetIdentityLabel,
} from "./pipeline-shared";

const EVENT_LEVELS: Array<JobEventLevel | "all"> = [
  "all",
  "critical",
  "error",
  "warning",
  "info",
  "debug",
];

function useExecutionDetailPanelController({
  kind,
  executionId,
  queueOperational,
  onClose,
  onSelectExecution,
}: {
  kind: ExecutionKind;
  executionId: string;
  queueOperational: boolean;
  onClose: () => void;
  onSelectExecution: (kind: ExecutionKind, id: string) => void;
}) {
  const [level, setLevel] = useState<JobEventLevel | "all">("all");
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [cancelReason, setCancelReason] = useState("");
  const confirm = useConfirm();
  const cancelExecution = useCancelExecutionMutation();
  const runNow = useRunNowUpdateRequestMutation();

  const cursor = cursorStack.at(-1) ?? null;
  const detail = usePipelineExecutionDetail(kind, executionId, {
    level: level === "all" ? undefined : level,
    page_size: 50,
    cursor,
  });

  const data = detail.data?.data;
  const execution = data?.execution;
  const root = data?.root;
  const importJob = data?.import_job ?? null;
  const updateRequest = data?.update_request ?? null;
  const cancellation = data?.cancellation ?? cancelExecution.data?.data ?? null;
  const events = data?.events ?? [];
  const eventsNextCursor = data?.events_next_cursor ?? null;
  const cancellationInProgress = cancellation?.status === "in_progress";

  const canCancel =
    execution !== undefined &&
    ["queued", "running"].includes(execution.status) &&
    (cancellation === null || cancellation.retryable);
  const canRunNow =
    execution !== undefined &&
    execution.kind === "update_request" &&
    cancellation === null &&
    (execution.status === "running" ||
      (execution.status === "queued" && queueOperational));
  const cancelProblem =
    cancelExecution.error instanceof ApiClientError
      ? cancelExecution.error.problem
      : null;
  const cancelProblemDetails = cancelProblem?.details;
  const cancellationFailures = cancellation
    ? {
        members: cancellation.members.filter(
          (member) => member.result === "cancel_failed" || member.error,
        ),
        dagster_runs: cancellation.dagster_runs.filter(
          (run) => run.result === "cancel_failed" || run.error,
        ),
      }
    : null;
  const hasCancellationFailures = Boolean(
    cancellationFailures &&
      (cancellationFailures.members.length > 0 ||
        cancellationFailures.dagster_runs.length > 0),
  );

  const submitCancel = async () => {
    if (!execution) {
      return;
    }
    const confirmed = await confirm({
      title: `${executionKindLabel(execution.kind)} 취소`,
      description:
        "실행 중인 외부 프로세스는 즉시 종료되지 않을 수 있습니다(best-effort).",
      confirmLabel: "취소 요청",
      destructive: true,
    });
    if (!confirmed) {
      return;
    }
    cancelExecution.mutate({
      kind: execution.kind,
      executionId: execution.id,
      body: {
        reason: cancelReason.trim() ? cancelReason.trim() : null,
      },
    });
  };

  const submitRunNow = () => {
    if (!execution) {
      return;
    }
    runNow.mutate({
      requestId: execution.id,
    });
  };

  return {
    canCancel,
    canRunNow,
    cancelExecution,
    cancelProblem,
    cancelProblemDetails,
    cancelReason,
    cancellation,
    cancellationFailures,
    cancellationInProgress,
    cursorStack,
    detail,
    events,
    eventsNextCursor,
    execution,
    executionId,
    hasCancellationFailures,
    importJob,
    kind,
    level,
    onClose,
    onSelectExecution,
    queueOperational,
    root,
    runNow,
    setCancelReason,
    setCursorStack,
    setLevel,
    submitCancel,
    submitRunNow,
    updateRequest,
  };
}

function ExecutionRunSummary({
  cancellation,
  cancellationFailures,
  detail,
  execution,
  hasCancellationFailures,
  importJob,
  onSelectExecution,
  root,
  updateRequest,
}: Pick<
  ReturnType<typeof useExecutionDetailPanelController>,
  | "cancellation"
  | "cancellationFailures"
  | "detail"
  | "execution"
  | "hasCancellationFailures"
  | "importJob"
  | "onSelectExecution"
  | "root"
  | "updateRequest"
>) {
  return (
    <>
      {detail.isLoading ? (
        <p className="text-sm text-muted-foreground">상세를 불러오는 중…</p>
      ) : null}
      {detail.isError ? (
        <Alert variant="destructive">
          <AlertTitle>실행 상세 호출 실패</AlertTitle>
          <AlertDescription>{detail.error.message}</AlertDescription>
        </Alert>
      ) : null}

      {execution?.error_message ? (
        <Alert variant="destructive">
          <AlertTitle>실패 원인</AlertTitle>
          <AlertDescription className="break-all">
            {execution.error_message}
          </AlertDescription>
        </Alert>
      ) : null}

      {cancellation ? (
        <Alert
          variant={
            cancellation.status === "failed" ||
            cancellation.status === "retryable"
              ? "destructive"
              : "default"
          }
        >
          <AlertTitle>취소 작업 {cancellation.status}</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>
              {cancellation.reason ?? "취소 사유 없음"} · 미해결 member{" "}
              {cancellation.unresolved_member_count}개
              {cancellation.retryable ? " · 재시도 가능" : ""}
            </p>
            {cancellation.error ? (
              <JsonViewer
                aria-label="영속 취소 오류 근거"
                maxHeight="sm"
                value={cancellation.error}
              />
            ) : null}
            {hasCancellationFailures ? (
              <JsonViewer
                aria-label="영속 취소 member 실패 근거"
                maxHeight="sm"
                value={cancellationFailures}
              />
            ) : null}
            {(cancellation.warnings ?? []).length > 0 ? (
              <ul className="list-disc pl-5">
                {(cancellation.warnings ?? []).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {execution ? (
        <DetailList
          items={[
            { label: "상태", value: statusLabel(execution.status) },
            {
              label: "진행",
              value:
                execution.kind === "update_request" && root
                  ? `${root.projected_job.progress}% · ${root.projected_job.current_stage ?? "-"}`
                  : `${execution.progress ?? 0}% · ${execution.current_stage ?? "-"}`,
            },
            {
              label: "provider datasets",
              value:
                execution.provider_datasets
                  .map(providerDatasetIdentityLabel)
                  .join(", ") || "-",
              mono: true,
            },
            {
              label: "scope",
              value: execution.scope_type ?? execution.job_kind ?? "-",
              mono: true,
            },
            {
              label: "우선순위/모드",
              value:
                execution.kind === "update_request"
                  ? `${execution.priority ?? "-"} / ${execution.run_mode ?? "-"}`
                  : "-",
            },
            { label: "operator", value: execution.operator ?? "-" },
            { label: "생성", value: formatDateTime(execution.created_at) },
            {
              label: "시작/완료",
              value: `${formatDateTime(execution.started_at) ?? "-"} → ${
                formatDateTime(execution.finished_at) ?? "-"
              }`,
            },
          ]}
        />
      ) : null}

      {execution ? (
        <section aria-label="연결 개체" className="space-y-2">
          <h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
            연결 개체
          </h3>
          <ul className="space-y-1 text-sm">
            {root ? (
              <li>
                대표 작업:{" "}
                <Button
                  data-detail-url={root.projected_job.detail_url}
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    onSelectExecution("import_job", root.projected_job.id)
                  }
                >
                  <span className="font-mono">
                    {shortId(root.projected_job.id)}
                  </span>
                  <StatusBadge status={root.projected_job.status} />
                </Button>
              </li>
            ) : null}
            {execution.kind === "update_request" && execution.job_id ? (
              <li>
                요청 연결 작업:{" "}
                <Button
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    onSelectExecution("import_job", execution.job_id as string)
                  }
                >
                  <span className="font-mono">{shortId(execution.job_id)}</span>
                </Button>
              </li>
            ) : null}
            {execution.kind === "import_job" && execution.request_id ? (
              <li>
                갱신 요청:{" "}
                <Button
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    onSelectExecution(
                      "update_request",
                      execution.request_id as string,
                    )
                  }
                >
                  <span className="font-mono">
                    {shortId(execution.request_id)}
                  </span>
                </Button>
              </li>
            ) : null}
            {execution.parent_job_id ? (
              <li>
                상위 작업:{" "}
                <Button
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    onSelectExecution(
                      "import_job",
                      execution.parent_job_id as string,
                    )
                  }
                >
                  <span className="font-mono">
                    {shortId(execution.parent_job_id)}
                  </span>
                </Button>
              </li>
            ) : null}
            {execution.load_batch_id ? (
              <li>
                배치:{" "}
                <Link
                  className="font-mono text-brand underline-offset-2 hover:underline"
                  href={`/ops/pipeline?load_batch_id=${encodeURIComponent(execution.load_batch_id)}`}
                >
                  {shortId(execution.load_batch_id)}
                </Link>
              </li>
            ) : null}
            {execution.dagster_run_id ? (
              <li>
                Dagster run:{" "}
                <EntityLink
                  id={execution.dagster_run_id}
                  kind="dagsterRun"
                  newTab
                />
              </li>
            ) : null}
          </ul>
        </section>
      ) : null}

      {updateRequest ? (
        <section aria-label="요청 payload" className="space-y-2">
          <h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
            요청 payload
          </h3>
          <JsonViewer
            aria-label="요청 scope payload"
            copyable
            maxHeight="sm"
            value={{
              scope: updateRequest.scope,
              dataset_memberships: updateRequest.dataset_memberships,
              update_policy: updateRequest.update_policy,
              matched_scope: updateRequest.matched_scope,
            }}
          />
        </section>
      ) : null}
      {!updateRequest && importJob ? (
        <section aria-label="작업 payload" className="space-y-2">
          <h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
            작업 payload
          </h3>
          <JsonViewer
            aria-label="작업 payload"
            copyable
            maxHeight="sm"
            value={importJob.payload}
          />
        </section>
      ) : null}
    </>
  );
}

function ExecutionClaimResolution({
  cursorStack,
  detail,
  events,
  eventsNextCursor,
  level,
  setCursorStack,
  setLevel,
}: Pick<
  ReturnType<typeof useExecutionDetailPanelController>,
  | "cursorStack"
  | "detail"
  | "events"
  | "eventsNextCursor"
  | "level"
  | "setCursorStack"
  | "setLevel"
>) {
  return (
    <>
      <section aria-label="이벤트 로그" className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
            이벤트 로그
          </h3>
          <NativeSelect
            aria-label="이벤트 레벨"
            value={level}
            onChange={(event) => {
              setLevel(event.target.value as JobEventLevel | "all");
              setCursorStack([]);
            }}
          >
            {EVENT_LEVELS.map((value) => (
              <NativeSelectOption key={value} value={value}>
                {value === "all" ? "전체 레벨" : value}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        {events.length === 0 && !detail.isLoading ? (
          <p className="text-sm text-muted-foreground">
            표시할 이벤트가 없습니다.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {events.map((event) => (
              <li
                className="rounded-md bg-surface-subtle p-2 text-sm"
                key={event.event_id}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={event.level} />
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(event.occurred_at)}
                  </span>
                  {event.stage ? (
                    <Badge variant="outline">{event.stage}</Badge>
                  ) : null}
                  {event.code ? (
                    <span className="font-mono text-xs">{event.code}</span>
                  ) : null}
                </div>
                <p className="mt-1 break-all">{event.message}</p>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-2">
          <Button
            aria-label="이벤트 처음"
            disabled={cursorStack.length === 0}
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setCursorStack([])}
          >
            처음
          </Button>
          <Button
            aria-label="이전 이벤트 더 보기"
            disabled={!eventsNextCursor || detail.isFetching}
            size="sm"
            type="button"
            variant="outline"
            onClick={() =>
              eventsNextCursor
                ? setCursorStack((stack) => [...stack, eventsNextCursor])
                : undefined
            }
          >
            이전 이벤트 더 보기
          </Button>
        </div>
      </section>
    </>
  );
}

function ExecutionRunLogs({
  canCancel,
  canRunNow,
  cancelExecution,
  cancelProblem,
  cancelProblemDetails,
  cancelReason,
  cancellation,
  cancellationInProgress,
  execution,
  onSelectExecution,
  queueOperational,
  runNow,
  setCancelReason,
  submitCancel,
  submitRunNow,
}: Pick<
  ReturnType<typeof useExecutionDetailPanelController>,
  | "canCancel"
  | "canRunNow"
  | "cancelExecution"
  | "cancelProblem"
  | "cancelProblemDetails"
  | "cancelReason"
  | "cancellation"
  | "cancellationInProgress"
  | "execution"
  | "onSelectExecution"
  | "queueOperational"
  | "runNow"
  | "setCancelReason"
  | "submitCancel"
  | "submitRunNow"
>) {
  return (
    <>
      <section aria-label="실행 조작" className="space-y-2">
        <h3 className="text-xs font-bold tracking-[0.05em] text-muted-foreground uppercase">
          조작
        </h3>
        {canCancel ? (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-0 grow flex-col gap-1 text-xs font-medium text-muted-foreground">
              취소 사유
              <Input
                aria-label="취소 사유"
                placeholder="예: 잘못된 scope"
                value={cancelReason}
                onChange={(event) => setCancelReason(event.target.value)}
              />
            </label>
            <Button
              disabled={cancelExecution.isPending || runNow.isPending}
              type="button"
              variant="destructive"
              onClick={() => void submitCancel()}
            >
              <XIcon data-icon="inline-start" />
              {cancellation?.retryable ? "취소 재시도" : "취소 요청"}
            </Button>
          </div>
        ) : null}
        {canRunNow ? (
          <div className="space-y-1">
            <Button
              disabled={runNow.isPending || cancelExecution.isPending}
              type="button"
              variant="outline"
              onClick={submitRunNow}
            >
              <PlayIcon data-icon="inline-start" />
              {execution?.status === "running"
                ? "실행 중 요청 확인 (run-now)"
                : "즉시 재큐잉 (run-now)"}
            </Button>
            <p className="text-xs text-muted-foreground">
              새 요청을 만들지 않고 같은 canonical request/job을 사용합니다.
              queued는 우선 dispatch를 요청하고 running 재호출은 현재 요청을
              200으로 멱등 반환합니다.
            </p>
          </div>
        ) : null}
        {execution?.kind === "update_request" &&
        execution.status === "queued" &&
        !queueOperational ? (
          <Alert variant="destructive">
            <AlertTitle>run-now 차단됨</AlertTitle>
            <AlertDescription>
              큐 sensor가 RUNNING으로 확인될 때까지 dispatch 요청을 만들지
              않습니다.
            </AlertDescription>
          </Alert>
        ) : null}
        {cancellationInProgress ? (
          <Alert>
            <AlertTitle>취소 진행 중</AlertTitle>
            <AlertDescription>
              취소 coordinator가 완료될 때까지 run-now와 중복 취소를 차단합니다.
            </AlertDescription>
          </Alert>
        ) : null}
        {!canCancel && !canRunNow && cancellation === null ? (
          <p className="text-sm text-muted-foreground">
            terminal 상태 실행은 조작할 수 없습니다.
          </p>
        ) : null}
        {cancelExecution.isError ? (
          <Alert variant="destructive">
            <AlertTitle>취소 실패</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>{cancelExecution.error.message}</p>
              {cancelProblem ? (
                <p>
                  오류 코드{" "}
                  <span className="font-mono">{cancelProblem.code}</span>
                  {cancelExecution.error.retryAfterSeconds !== null
                    ? ` · ${cancelExecution.error.retryAfterSeconds}초 후 재시도 가능`
                    : ""}
                </p>
              ) : null}
              {cancelProblemDetails !== undefined ? (
                <JsonViewer
                  aria-label="취소 실패 상세 근거"
                  maxHeight="sm"
                  value={cancelProblemDetails}
                />
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}
        {runNow.isError ? (
          <Alert variant="destructive">
            <AlertTitle>run-now 실패</AlertTitle>
            <AlertDescription>{runNow.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {runNow.isSuccess && runNow.data.data.request_id ? (
          <Alert>
            <AlertTitle>우선 dispatch 요청됨</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center gap-2">
              <span className="font-mono">
                {shortId(runNow.data.data.request_id)}
              </span>
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() =>
                  onSelectExecution(
                    "update_request",
                    runNow.data.data.request_id as string,
                  )
                }
              >
                같은 요청 다시 열기
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}
      </section>
    </>
  );
}

function ExecutionDetailPanelView({
  canCancel,
  canRunNow,
  cancelExecution,
  cancelProblem,
  cancelProblemDetails,
  cancelReason,
  cancellation,
  cancellationFailures,
  cancellationInProgress,
  cursorStack,
  detail,
  events,
  eventsNextCursor,
  execution,
  executionId,
  hasCancellationFailures,
  importJob,
  kind,
  level,
  onClose,
  onSelectExecution,
  queueOperational,
  root,
  runNow,
  setCancelReason,
  setCursorStack,
  setLevel,
  submitCancel,
  submitRunNow,
  updateRequest,
}: ReturnType<typeof useExecutionDetailPanelController>) {
  return (
    <Card aria-label="실행 상세" data-testid="pipeline-execution-detail">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">
                {execution
                  ? executionKindLabel(execution.kind)
                  : executionKindLabel(kind)}
              </Badge>
              <span className="font-mono text-sm">{shortId(executionId)}</span>
              {execution ? <StatusBadge status={execution.status} /> : null}
            </CardTitle>
            <CardDescription>
              실행 상세 — 이벤트 로그·연결 개체·요청 payload
            </CardDescription>
          </div>
          <Button
            aria-label="실행 상세 닫기"
            size="icon"
            type="button"
            variant="ghost"
            onClick={onClose}
          >
            <XIcon />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ExecutionRunSummary
          cancellation={cancellation}
          cancellationFailures={cancellationFailures}
          detail={detail}
          execution={execution}
          hasCancellationFailures={hasCancellationFailures}
          importJob={importJob}
          onSelectExecution={onSelectExecution}
          root={root}
          updateRequest={updateRequest}
        />

        <ExecutionClaimResolution
          cursorStack={cursorStack}
          detail={detail}
          events={events}
          eventsNextCursor={eventsNextCursor}
          level={level}
          setCursorStack={setCursorStack}
          setLevel={setLevel}
        />

        <ExecutionRunLogs
          canCancel={canCancel}
          canRunNow={canRunNow}
          cancelExecution={cancelExecution}
          cancelProblem={cancelProblem}
          cancelProblemDetails={cancelProblemDetails}
          cancelReason={cancelReason}
          cancellation={cancellation}
          cancellationInProgress={cancellationInProgress}
          execution={execution}
          onSelectExecution={onSelectExecution}
          queueOperational={queueOperational}
          runNow={runNow}
          setCancelReason={setCancelReason}
          submitCancel={submitCancel}
          submitRunNow={submitRunNow}
        />
      </CardContent>
    </Card>
  );
}

export function ExecutionDetailPanel({
  kind,
  executionId,
  queueOperational,
  onClose,
  onSelectExecution,
}: {
  kind: ExecutionKind;
  executionId: string;
  queueOperational: boolean;
  onClose: () => void;
  onSelectExecution: (kind: ExecutionKind, id: string) => void;
}) {
  const controller = useExecutionDetailPanelController({
    kind,
    executionId,
    queueOperational,
    onClose,
    onSelectExecution,
  });
  return <ExecutionDetailPanelView {...controller} />;
}
