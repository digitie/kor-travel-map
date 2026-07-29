"use client";

import { PencilIcon, PlayIcon, RotateCcwIcon, SquareIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { ApiClientError } from "@/api/client";
import {
  type PipelineSchedule,
  type PipelineScheduleCommand,
  type PipelineScheduleCommandResponse,
  type PipelineScheduleClaimResolutionRequest,
  readPipelineFrozenScheduleClaimResolution,
  readPipelineFrozenScheduleMutation,
  usePatchScheduleMutation,
  usePipelineSchedules,
  useResolveScheduleClaimMutation,
  useScheduleCommandMutation,
} from "@/api/pipeline";
import { HelpTip } from "@/components/help-tip";
import { StatusBadge } from "@/components/status-badge";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { useConfirm } from "@/components/confirm-dialog";

import { shouldRetainClaimResolutionSubmission } from "./claim-resolution-retry";
import { describeCron } from "./pipeline-shared";

const MAX_CLAIM_RESOLUTION_REASON_LENGTH = 500;
const EMPTY_SCHEDULES: PipelineSchedule[] = [];

const COMMAND_LABELS: Record<PipelineScheduleCommand, string> = {
  run: "즉시 실행",
  start: "스케줄 시작",
  stop: "스케줄 중지",
  reset: "상태 기본값 복귀",
};

function commandResultLabel(
  command: PipelineScheduleCommandResponse["data"]["command"],
): string {
  if (command === "update") {
    return "cron 수정";
  }
  if (command === "clear_override") {
    return "기본값 복귀(override 삭제)";
  }
  return COMMAND_LABELS[command];
}

function ScheduleCommandResultAlert({
  result,
}: {
  result: PipelineScheduleCommandResponse["data"];
}) {
  return (
    <Alert
      data-testid="schedule-command-result"
      variant={
        result.status === "ok" && result.audit_status === "recorded"
          ? "default"
          : "destructive"
      }
    >
      <AlertTitle>스케줄 명령 결과</AlertTitle>
      <AlertDescription className="space-y-1">
        <p>
          <span className="font-mono">{result.schedule_name}</span> ·{" "}
          {commandResultLabel(result.command)} ·{" "}
          {result.status === "ok" ? "성공" : `실패(${result.status})`}
        </p>
        {result.cron_schedule ? (
          <p>
            적용 cron: <span className="font-mono">{result.cron_schedule}</span>
          </p>
        ) : null}
        <p>
          저장 {result.save_status} · reload {result.reload_status} · 실제 반영{" "}
          {result.effective_status}
        </p>
        {result.audit_command_id ? (
          <p>
            감사 명령 ID:{" "}
            <span className="font-mono">{result.audit_command_id}</span>
          </p>
        ) : null}
        {result.audit_status === "terminal_record_failed" ? (
          <p className="font-medium text-destructive">
            원격 명령 결과는 반환됐지만 terminal 감사 기록에 실패했습니다. 같은
            명령을 새 키로 다시 실행하지 말고 명령 ID로 운영자 확인이
            필요합니다.
          </p>
        ) : null}
        {result.effective_cron_schedule ? (
          <p>
            실제 cron:{" "}
            <span className="font-mono">{result.effective_cron_schedule}</span>
          </p>
        ) : null}
        {result.run_id ? (
          <p>
            실행: <span className="font-mono">{result.run_id}</span> (
            {result.run_status ?? "-"})
          </p>
        ) : null}
        {result.reload_status === "succeeded" ? (
          <p className="flex items-center gap-1">
            코드 위치 새로고침 요청됨
            <HelpTip label="코드 위치 새로고침">
              스케줄러 daemon은 자체 code location reload 후 새 cron을
              반영합니다 — 즉시 적용은 아닙니다.
            </HelpTip>
          </p>
        ) : null}
        {(result.errors ?? []).length > 0 ? (
          <p className="break-all">{(result.errors ?? []).join(" / ")}</p>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

function commandResultFromError(
  error: Error | null,
): PipelineScheduleCommandResponse["data"] | null {
  if (!(error instanceof ApiClientError)) {
    return null;
  }
  const details = error.problem?.details;
  if (
    typeof details !== "object" ||
    details === null ||
    typeof (details as Record<string, unknown>).status !== "string" ||
    typeof (details as Record<string, unknown>).schedule_name !== "string" ||
    typeof (details as Record<string, unknown>).command !== "string" ||
    !Array.isArray((details as Record<string, unknown>).errors)
  ) {
    return null;
  }
  return details as unknown as PipelineScheduleCommandResponse["data"];
}

interface ScheduleClaimRecovery {
  scheduleName: string;
  commandId: string;
}

interface ScheduleClaimResolutionSubmission extends ScheduleClaimRecovery {
  body: PipelineScheduleClaimResolutionRequest;
}

function claimRecoveryFromResult(
  result: PipelineScheduleCommandResponse["data"] | null,
): ScheduleClaimRecovery | null {
  if (
    !result?.audit_command_id ||
    (result.outcome_certainty !== "uncertain" &&
      result.audit_status !== "terminal_record_failed")
  ) {
    return null;
  }
  return {
    scheduleName: result.schedule_name,
    commandId: result.audit_command_id,
  };
}

function claimRecoveryFromConflict(
  error: Error | null,
  scheduleName: string | undefined,
): ScheduleClaimRecovery | null {
  if (
    !(error instanceof ApiClientError) ||
    !scheduleName ||
    ![
      "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN",
      "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
    ].includes(error.problem?.code ?? "")
  ) {
    return null;
  }
  const details = error.problem?.details;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const record = details as Record<string, unknown>;
  const commandId = record.active_command_id;
  if (typeof commandId !== "string" || commandId.trim().length === 0) {
    return null;
  }
  return { scheduleName, commandId: commandId.trim() };
}

function useSchedulePanelController({
  highlightSchedule,
  onHighlightSchedule,
}: {
  highlightSchedule?: string;
  onHighlightSchedule: (scheduleName: string) => void;
}) {
  const schedules = usePipelineSchedules();
  const patchSchedule = usePatchScheduleMutation();
  const commandSchedule = useScheduleCommandMutation();
  const resolveClaim = useResolveScheduleClaimMutation();
  const confirm = useConfirm();

  const [editing, setEditing] = useState<PipelineSchedule | null>(null);
  const [cronDraft, setCronDraft] = useState("");
  const [editReason, setEditReason] = useState("");
  const [commandReasons, setCommandReasons] = useState<Record<string, string>>(
    {},
  );
  const [lastResult, setLastResult] = useState<
    PipelineScheduleCommandResponse["data"] | null
  >(null);
  const [claimResolution, setClaimResolution] = useState<
    PipelineScheduleClaimResolutionRequest["resolution"]
  >("confirmed_not_applied");
  const [claimResolutionReason, setClaimResolutionReason] = useState("");
  const [claimResolutionSubmission, setClaimResolutionSubmission] =
    useState<ScheduleClaimResolutionSubmission | null>(null);
  const [frozenState, setFrozenState] = useState<{
    claimResolutionSubmission: ScheduleClaimResolutionSubmission | null;
    mutation: ReturnType<typeof readPipelineFrozenScheduleMutation>;
    scannedScheduleKey: string | null;
  }>({
    claimResolutionSubmission: null,
    mutation: null,
    scannedScheduleKey: null,
  });
  const highlightRef = useRef<HTMLDivElement | null>(null);

  const data = schedules.data?.data;
  const scheduleItems = data?.schedules ?? EMPTY_SCHEDULES;
  const scheduleScanKey = data
    ? JSON.stringify(scheduleItems.map((schedule) => schedule.name).sort())
    : null;
  const refreshFrozenState = useCallback(() => {
    let mutation: ReturnType<typeof readPipelineFrozenScheduleMutation> = null;
    let claim: ReturnType<typeof readPipelineFrozenScheduleClaimResolution> =
      null;
    for (const schedule of scheduleItems) {
      mutation ??= readPipelineFrozenScheduleMutation(schedule.name);
      claim ??= readPipelineFrozenScheduleClaimResolution(schedule.name);
      if (mutation && claim) {
        break;
      }
    }
    setFrozenState({
      claimResolutionSubmission: claim?.submission ?? null,
      mutation,
      scannedScheduleKey: scheduleScanKey,
    });
  }, [scheduleItems, scheduleScanKey]);
  const latestRefreshFrozenStateRef = useRef(refreshFrozenState);
  useLayoutEffect(() => {
    latestRefreshFrozenStateRef.current = refreshFrozenState;
  }, [refreshFrozenState]);
  const refreshLatestFrozenState = useCallback(() => {
    latestRefreshFrozenStateRef.current();
  }, []);

  useEffect(() => {
    if (scheduleScanKey === null) return;
    const animationFrame = window.requestAnimationFrame(refreshFrozenState);
    return () => {
      window.cancelAnimationFrame(animationFrame);
    };
  }, [refreshFrozenState, scheduleScanKey]);
  const frozenScheduleMutation = frozenState.mutation;
  const storedClaimResolutionSubmission = frozenState.claimResolutionSubmission;
  const effectiveClaimResolutionSubmission =
    claimResolutionSubmission ?? storedClaimResolutionSubmission;
  const sensors = data?.sensors ?? [];
  const scheduleMutationPending =
    patchSchedule.isPending ||
    commandSchedule.isPending ||
    resolveClaim.isPending;
  const failedResult =
    commandResultFromError(patchSchedule.error) ??
    commandResultFromError(commandSchedule.error);
  const recoveryClaim =
    claimRecoveryFromResult(lastResult) ??
    claimRecoveryFromResult(failedResult) ??
    claimRecoveryFromConflict(
      patchSchedule.error,
      patchSchedule.variables?.scheduleName,
    ) ??
    claimRecoveryFromConflict(
      commandSchedule.error,
      commandSchedule.variables?.scheduleName,
    ) ??
    (effectiveClaimResolutionSubmission
      ? {
          scheduleName: effectiveClaimResolutionSubmission.scheduleName,
          commandId: effectiveClaimResolutionSubmission.commandId,
        }
      : null);
  const frozenClaimResolution =
    recoveryClaim &&
    effectiveClaimResolutionSubmission?.scheduleName ===
      recoveryClaim.scheduleName &&
    effectiveClaimResolutionSubmission.commandId === recoveryClaim.commandId
      ? effectiveClaimResolutionSubmission
      : null;
  const scheduleStateScanned =
    scheduleScanKey !== null &&
    frozenState.scannedScheduleKey === scheduleScanKey;
  const scheduleStateScannedRef = useRef(false);
  const recoveryClaimScheduleName = recoveryClaim?.scheduleName ?? null;
  const recoveryClaimCommandId = recoveryClaim?.commandId ?? null;
  const recoveryClaimRef = useRef<{
    scheduleName: string;
    commandId: string;
  } | null>(null);
  useLayoutEffect(() => {
    scheduleStateScannedRef.current = scheduleStateScanned;
    recoveryClaimRef.current =
      recoveryClaimScheduleName !== null && recoveryClaimCommandId !== null
        ? {
            scheduleName: recoveryClaimScheduleName,
            commandId: recoveryClaimCommandId,
          }
        : null;
  }, [recoveryClaimCommandId, recoveryClaimScheduleName, scheduleStateScanned]);

  const scheduleRecoveryLocked = Boolean(
    !scheduleStateScanned ||
    recoveryClaim ||
    effectiveClaimResolutionSubmission ||
    frozenScheduleMutation,
  );
  const scheduleControlsDisabled =
    scheduleMutationPending || scheduleRecoveryLocked;
  const scheduleControlsGuardRef = useRef(true);
  useEffect(() => {
    scheduleControlsGuardRef.current = scheduleControlsDisabled;
  }, [scheduleControlsDisabled]);

  useEffect(() => {
    if (highlightSchedule && highlightRef.current) {
      highlightRef.current.scrollIntoView({ block: "center" });
    }
  }, [highlightSchedule, scheduleItems.length]);

  const submitCommand = async (
    schedule: PipelineSchedule,
    command: PipelineScheduleCommand,
  ) => {
    if (scheduleControlsGuardRef.current) {
      return;
    }
    onHighlightSchedule(schedule.name);
    if (command === "run" || command === "start") {
      const confirmed = await confirm({
        title: `${schedule.name} ${COMMAND_LABELS[command]}`,
        description:
          command === "run"
            ? "provider 호출을 동반하는 적재가 즉시 1회 실행됩니다."
            : "스케줄이 켜지면 주기 실행이 재개됩니다.",
        confirmLabel: COMMAND_LABELS[command],
      });
      if (!confirmed) {
        return;
      }
      if (scheduleControlsGuardRef.current) {
        return;
      }
    }
    patchSchedule.reset();
    commandSchedule.reset();
    resolveClaim.reset();
    setLastResult(null);
    scheduleControlsGuardRef.current = true;
    commandSchedule.mutate(
      {
        scheduleName: schedule.name,
        body: {
          command,
          reason: commandReasons[schedule.name]?.trim() || null,
        },
      },
      {
        onSuccess: (response) => {
          setLastResult(response.data);
          if (response.data.audit_status === "recorded") {
            setCommandReasons((current) => ({
              ...current,
              [schedule.name]: "",
            }));
          }
        },
        onSettled: refreshLatestFrozenState,
      },
    );
  };

  const openEdit = (schedule: PipelineSchedule) => {
    if (scheduleControlsGuardRef.current) {
      return;
    }
    onHighlightSchedule(schedule.name);
    setEditing(schedule);
    setCronDraft(
      schedule.override_cron_schedule ??
        schedule.cron_schedule ??
        schedule.default_cron_schedule ??
        "",
    );
    setEditReason("");
  };

  const submitCronPatch = (cronSchedule: string | null) => {
    if (!editing || scheduleControlsGuardRef.current) {
      return;
    }
    const editedScheduleName = editing.name;
    patchSchedule.reset();
    commandSchedule.reset();
    resolveClaim.reset();
    setLastResult(null);
    scheduleControlsGuardRef.current = true;
    patchSchedule.mutate(
      {
        scheduleName: editedScheduleName,
        body: {
          cron_schedule: cronSchedule,
          reason: editReason.trim() || null,
        },
      },
      {
        onSuccess: (response) => {
          setLastResult(response.data);
          if (
            response.data.status === "ok" &&
            response.data.audit_status === "recorded"
          ) {
            setEditing(null);
          }
        },
        onSettled: (response, error) => {
          refreshLatestFrozenState();
          const result = response?.data ?? commandResultFromError(error);
          if (
            claimRecoveryFromResult(result) ||
            claimRecoveryFromConflict(error, editedScheduleName) ||
            readPipelineFrozenScheduleMutation(editedScheduleName)
          ) {
            // Base UI dialog는 배경을 inert로 만든다. 결과 불명 복구 UI가 생기면
            // mutation 경계에서 즉시 닫아 동일 요청 재확인/claim 해제를 노출한다.
            setEditing(null);
          }
        },
      },
    );
  };

  const submitClaimResolution = async () => {
    if (!recoveryClaim || !scheduleStateScanned) {
      return;
    }
    const submission: ScheduleClaimResolutionSubmission =
      frozenClaimResolution ?? {
        scheduleName: recoveryClaim.scheduleName,
        commandId: recoveryClaim.commandId,
        body: {
          resolution: claimResolution,
          reason: claimResolutionReason.trim(),
        },
      };
    if (
      !submission.body.reason ||
      submission.body.reason.length > MAX_CLAIM_RESOLUTION_REASON_LENGTH
    ) {
      return;
    }
    const confirmed = await confirm({
      title: `${submission.scheduleName} 결과 불명 claim 해제`,
      description:
        "Dagster 실행·스케줄 상태를 직접 확인한 경우에만 진행하세요. 해제 후 같은 조작은 새 명령으로 실행됩니다.",
      confirmLabel: "확인 결과 기록 후 해제",
      destructive: true,
    });
    const latestRecoveryClaim = recoveryClaimRef.current;
    if (
      !confirmed ||
      !scheduleStateScannedRef.current ||
      latestRecoveryClaim?.scheduleName !== submission.scheduleName ||
      latestRecoveryClaim?.commandId !== submission.commandId
    ) {
      return;
    }
    setClaimResolutionSubmission(submission);
    resolveClaim.mutate(
      {
        scheduleName: submission.scheduleName,
        commandId: submission.commandId,
        body: submission.body,
      },
      {
        onSuccess: () => {
          patchSchedule.reset();
          commandSchedule.reset();
          setLastResult(null);
          setClaimResolutionReason("");
          setClaimResolutionSubmission(null);
        },
        onError: (error) => {
          if (!shouldRetainClaimResolutionSubmission(error)) {
            setClaimResolutionSubmission(null);
          }
        },
        onSettled: refreshLatestFrozenState,
      },
    );
  };

  const retryFrozenScheduleMutation = () => {
    if (
      !scheduleStateScanned ||
      !frozenScheduleMutation ||
      recoveryClaim ||
      patchSchedule.isPending ||
      commandSchedule.isPending
    ) {
      return;
    }
    patchSchedule.reset();
    commandSchedule.reset();
    resolveClaim.reset();
    setLastResult(null);
    scheduleControlsGuardRef.current = true;
    const onSuccess = (response: PipelineScheduleCommandResponse) => {
      setLastResult(response.data);
    };
    if (frozenScheduleMutation.submission.kind === "patch") {
      patchSchedule.mutate(
        {
          scheduleName: frozenScheduleMutation.scheduleName,
          body: frozenScheduleMutation.submission.body,
        },
        { onSettled: refreshLatestFrozenState, onSuccess },
      );
      return;
    }
    commandSchedule.mutate(
      {
        scheduleName: frozenScheduleMutation.scheduleName,
        body: frozenScheduleMutation.submission.body,
      },
      { onSettled: refreshLatestFrozenState, onSuccess },
    );
  };

  return {
    claimResolution,
    claimResolutionReason,
    commandReasons,
    commandSchedule,
    cronDraft,
    data,
    editReason,
    editing,
    failedResult,
    frozenClaimResolution,
    frozenScheduleMutation,
    highlightRef,
    highlightSchedule,
    lastResult,
    openEdit,
    patchSchedule,
    recoveryClaim,
    resolveClaim,
    retryFrozenScheduleMutation,
    scheduleControlsDisabled,
    scheduleItems,
    scheduleStateScanned,
    schedules,
    sensors,
    setClaimResolution,
    setClaimResolutionReason,
    setCommandReasons,
    setCronDraft,
    setEditReason,
    setEditing,
    submitClaimResolution,
    submitCommand,
    submitCronPatch,
  };
}

function ScheduleEditor({
  claimResolution,
  claimResolutionReason,
  commandSchedule,
  data,
  failedResult,
  frozenClaimResolution,
  frozenScheduleMutation,
  lastResult,
  patchSchedule,
  recoveryClaim,
  resolveClaim,
  retryFrozenScheduleMutation,
  scheduleStateScanned,
  schedules,
  setClaimResolution,
  setClaimResolutionReason,
  submitClaimResolution,
}: Pick<ReturnType<typeof useSchedulePanelController>, "claimResolution" | "claimResolutionReason" | "commandSchedule" | "data" | "failedResult" | "frozenClaimResolution" | "frozenScheduleMutation" | "lastResult" | "patchSchedule" | "recoveryClaim" | "resolveClaim" | "retryFrozenScheduleMutation" | "scheduleStateScanned" | "schedules" | "setClaimResolution" | "setClaimResolutionReason" | "submitClaimResolution">) {
  return (
    <>
{schedules.isError ? (
        <Alert variant="destructive">
          <AlertTitle>스케줄 목록 호출 실패</AlertTitle>
          <AlertDescription>{schedules.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data && data.status !== "ok" ? (
        <Alert
          variant={data.status === "unavailable" ? "destructive" : "default"}
        >
          <AlertTitle>스케줄 상태 확인 필요</AlertTitle>
          <AlertDescription>
            {(data.errors ?? []).length > 0
              ? (data.errors ?? []).join(" / ")
              : "Dagster 응답을 확인하세요."}
          </AlertDescription>
        </Alert>
      ) : null}
      {lastResult ? <ScheduleCommandResultAlert result={lastResult} /> : null}
      {failedResult ? (
        <ScheduleCommandResultAlert result={failedResult} />
      ) : null}
      {patchSchedule.isError ? (
        <Alert variant="destructive">
          <AlertTitle>cron 수정 호출 실패</AlertTitle>
          <AlertDescription>{patchSchedule.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {commandSchedule.isError ? (
        <Alert variant="destructive">
          <AlertTitle>스케줄 명령 호출 실패</AlertTitle>
          <AlertDescription>{commandSchedule.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {frozenScheduleMutation ? (
        <Alert data-testid="schedule-frozen-submission" variant="destructive">
          <AlertTitle>결과 확인 전 schedule 요청 고정됨</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              응답 유실 가능성이 있어 UUID, endpoint, 요청 본문을 탭에
              보존했습니다. 다른 cron·명령으로 바꾸지 않고 이 요청만 같은
              Idempotency-Key로 재확인합니다.
            </p>
            <p>
              schedule{" "}
              <span className="font-mono">
                {frozenScheduleMutation.scheduleName}
              </span>
              {" · "}
              {frozenScheduleMutation.submission.kind === "patch"
                ? "cron 변경"
                : COMMAND_LABELS[
                    frozenScheduleMutation.submission.body.command
                  ]}
              {" · key "}
              <span className="font-mono">
                {frozenScheduleMutation.idempotencyKey}
              </span>
            </p>
            {recoveryClaim ? (
              <p>Dagster 실제 상태 확인 후 아래 claim 해제를 진행하세요.</p>
            ) : (
              <Button
                disabled={
                  !scheduleStateScanned ||
                  patchSchedule.isPending ||
                  commandSchedule.isPending
                }
                type="button"
                variant="destructive"
                onClick={retryFrozenScheduleMutation}
              >
                동일 요청 재확인
              </Button>
            )}
          </AlertDescription>
        </Alert>
      ) : null}
      {recoveryClaim ? (
        <Alert data-testid="schedule-claim-recovery" variant="destructive">
          <AlertTitle>Dagster 실제 결과 확인 필요</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              응답 유실 또는 terminal 감사 기록 실패로 명령 반영 여부를 자동
              확정할 수 없습니다. Dagster 실행 목록과 스케줄 상태를 직접
              확인하기 전에는 같은 schedule 명령을 다시 보내지 마세요.
            </p>
            <p>
              schedule{" "}
              <span className="font-mono">{recoveryClaim.scheduleName}</span>
              {" · claim "}
              <span className="font-mono">{recoveryClaim.commandId}</span>
            </p>
            <div className="grid gap-3 md:grid-cols-[14rem_minmax(0,1fr)_auto] md:items-end">
              <label className="flex flex-col gap-1 text-xs font-medium">
                실제 반영 확인 결과
                <NativeSelect
                  aria-label="schedule claim 실제 반영 확인 결과"
                  disabled={
                    resolveClaim.isPending || frozenClaimResolution !== null
                  }
                  value={
                    frozenClaimResolution?.body.resolution ?? claimResolution
                  }
                  onChange={(event) =>
                    setClaimResolution(
                      event.target
                        .value as PipelineScheduleClaimResolutionRequest["resolution"],
                    )
                  }
                >
                  <NativeSelectOption value="confirmed_not_applied">
                    미반영 확인
                  </NativeSelectOption>
                  <NativeSelectOption value="confirmed_applied">
                    반영 확인
                  </NativeSelectOption>
                </NativeSelect>
              </label>
              <FormField
                disabled={
                  resolveClaim.isPending || frozenClaimResolution !== null
                }
                label="확인 근거·해제 사유 (필수)"
                maxLength={MAX_CLAIM_RESOLUTION_REASON_LENGTH}
                placeholder="예: Dagster run 목록에서 해당 run이 없음을 확인"
                value={
                  frozenClaimResolution?.body.reason ?? claimResolutionReason
                }
                onChange={(event) =>
                  setClaimResolutionReason(event.target.value)
                }
              />
              <Button
                disabled={
                  !scheduleStateScanned ||
                  resolveClaim.isPending ||
                  !(
                    frozenClaimResolution?.body.reason ??
                    claimResolutionReason.trim()
                  ) ||
                  (
                    frozenClaimResolution?.body.reason ??
                    claimResolutionReason.trim()
                  ).length > MAX_CLAIM_RESOLUTION_REASON_LENGTH
                }
                type="button"
                variant="destructive"
                onClick={() => void submitClaimResolution()}
              >
                claim 해제
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ) : null}
      {resolveClaim.isSuccess ? (
        <Alert data-testid="schedule-claim-resolution-result">
          <AlertTitle>claim 해제 완료</AlertTitle>
          <AlertDescription>
            {resolveClaim.data.data.resolution === "confirmed_applied"
              ? "Dagster 반영 확인"
              : "Dagster 미반영 확인"}
            {" · 감사 이력 "}
            <span className="font-mono">
              {resolveClaim.data.data.resolution_id}
            </span>
          </AlertDescription>
        </Alert>
      ) : null}
      {resolveClaim.isError ? (
        <Alert variant="destructive">
          <AlertTitle>claim 해제 실패</AlertTitle>
          <AlertDescription>{resolveClaim.error.message}</AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

function ScheduleSummary({
  schedules,
  sensors,
}: Pick<ReturnType<typeof useSchedulePanelController>, "schedules" | "sensors">) {
  return (
    <>
<Card>
        <CardHeader>
          <CardTitle>센서</CardTitle>
          <CardDescription>
            큐 sensor가 꺼지면 갱신 요청 큐가 조용히 멈춥니다 — 상태를 항상
            확인하세요.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sensors.length === 0 && !schedules.isLoading ? (
            <p className="text-sm text-muted-foreground">
              표시할 sensor가 없습니다.
            </p>
          ) : (
            <ul className="space-y-2">
              {sensors.map((sensor) => (
                <li
                  className="flex flex-wrap items-center gap-2"
                  data-testid={`pipeline-sensor-${sensor.name}`}
                  key={sensor.name}
                >
                  <span className="font-mono text-sm">{sensor.name}</span>
                  <StatusBadge status={sensor.status ?? "unknown"} />
                  {sensor.recent_ticks?.[0]?.error ? (
                    <span className="text-xs text-destructive">
                      최근 tick 오류: {sensor.recent_ticks[0].error.message}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function ScheduleTable({
  commandReasons,
  highlightRef,
  highlightSchedule,
  openEdit,
  scheduleControlsDisabled,
  scheduleItems,
  schedules,
  setCommandReasons,
  submitCommand,
}: Pick<ReturnType<typeof useSchedulePanelController>, "commandReasons" | "highlightRef" | "highlightSchedule" | "openEdit" | "scheduleControlsDisabled" | "scheduleItems" | "schedules" | "setCommandReasons" | "submitCommand">) {
  return (
    <>
<Card>
        <CardHeader>
          <CardTitle>스케줄</CardTitle>
          <CardDescription>
            cron은 override가 있으면 override, 없으면 코드 기본값이 표시됩니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {schedules.isLoading ? (
            <p className="text-sm text-muted-foreground">
              스케줄을 불러오는 중…
            </p>
          ) : null}
          {scheduleItems.map((schedule) => {
            const highlighted = schedule.name === highlightSchedule;
            const effectiveCron = schedule.effective_cron_schedule;
            return (
              <div
                className={`rounded-xl bg-surface-subtle p-4 ${
                  highlighted ? "ring-2 ring-brand" : ""
                }`}
                data-testid={`pipeline-schedule-row-${schedule.name}`}
                key={schedule.name}
                ref={highlighted ? highlightRef : undefined}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm font-medium">
                      {schedule.name}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      <span className="font-mono">{effectiveCron ?? "-"}</span>
                      {describeCron(effectiveCron)
                        ? ` — ${describeCron(effectiveCron)}`
                        : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={schedule.status ?? "unknown"} />
                    {schedule.override_saved ? (
                      <Badge variant="secondary">override 저장됨</Badge>
                    ) : null}
                    {schedule.override_effective === true ? (
                      <Badge variant="default">실제 반영됨</Badge>
                    ) : null}
                    {schedule.override_effective === false ? (
                      <Badge variant="destructive">저장/실제 불일치</Badge>
                    ) : null}
                  </div>
                </div>
                {schedule.schedule_note ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {schedule.schedule_note}
                  </p>
                ) : null}
                {schedule.disabled_reason ? (
                  <p className="mt-1 text-xs text-destructive">
                    즉시 실행 불가: {schedule.disabled_reason}
                  </p>
                ) : null}
                <div className="mt-2">
                  <FormField
                    disabled={scheduleControlsDisabled}
                    label="명령 사유 (선택)"
                    placeholder="시작·중지·reset·즉시 실행 감사 로그에 기록"
                    value={commandReasons[schedule.name] ?? ""}
                    onChange={(event) =>
                      setCommandReasons((current) => ({
                        ...current,
                        [schedule.name]: event.target.value,
                      }))
                    }
                  />
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Button
                    aria-label={`${schedule.name} 즉시 실행`}
                    disabled={scheduleControlsDisabled || !schedule.can_run_now}
                    size="sm"
                    type="button"
                    variant="outline"
                    title={schedule.disabled_reason ?? undefined}
                    onClick={() => void submitCommand(schedule, "run")}
                  >
                    <PlayIcon data-icon="inline-start" />
                    즉시 실행
                  </Button>
                  {schedule.status === "RUNNING" ? (
                    <Button
                      aria-label={`${schedule.name} 스케줄 중지`}
                      disabled={scheduleControlsDisabled}
                      size="sm"
                      type="button"
                      variant="destructive"
                      onClick={() => void submitCommand(schedule, "stop")}
                    >
                      <SquareIcon data-icon="inline-start" />
                      중지
                    </Button>
                  ) : (
                    <Button
                      aria-label={`${schedule.name} 스케줄 시작`}
                      disabled={scheduleControlsDisabled}
                      size="sm"
                      type="button"
                      variant="outline"
                      onClick={() => void submitCommand(schedule, "start")}
                    >
                      <PlayIcon data-icon="inline-start" />
                      시작
                    </Button>
                  )}
                  <Button
                    aria-label={`${schedule.name} 상태 기본값 복귀`}
                    disabled={scheduleControlsDisabled || !schedule.can_reset}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => void submitCommand(schedule, "reset")}
                  >
                    <RotateCcwIcon data-icon="inline-start" />
                    상태 reset
                  </Button>
                  <Button
                    aria-label={`${schedule.name} cron 수정`}
                    disabled={scheduleControlsDisabled}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => openEdit(schedule)}
                  >
                    <PencilIcon data-icon="inline-start" />
                    cron 수정
                  </Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </>
  );
}

function ScheduleDeleteDialog({
  cronDraft,
  editReason,
  editing,
  scheduleControlsDisabled,
  setCronDraft,
  setEditReason,
  setEditing,
  submitCronPatch,
}: Pick<ReturnType<typeof useSchedulePanelController>, "cronDraft" | "editReason" | "editing" | "scheduleControlsDisabled" | "setCronDraft" | "setEditReason" | "setEditing" | "submitCronPatch">) {
  return (
    <>
<Dialog
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) {
            setEditing(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>스케줄 cron 수정</DialogTitle>
            <DialogDescription>
              {editing ? (
                <span className="font-mono">{editing.name}</span>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <FormField
              disabled={scheduleControlsDisabled}
              hint="분 시 일 월 요일 5필드. 분은 0~59 단일 값 또는 */N(N≥10)만 허용됩니다."
              label="cron"
              value={cronDraft}
              onChange={(event) => setCronDraft(event.target.value)}
            />
            {describeCron(cronDraft) ? (
              <p className="text-xs text-muted-foreground">
                {describeCron(cronDraft)}
              </p>
            ) : null}
            <FormField
              disabled={scheduleControlsDisabled}
              label="수정 사유"
              placeholder="감사 로그에 남는 사유"
              value={editReason}
              onChange={(event) => setEditReason(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              기본값:{" "}
              <span className="font-mono">
                {editing?.default_cron_schedule ?? "-"}
              </span>
              {editing?.override_cron_schedule ? (
                <>
                  {" · 현재 override: "}
                  <span className="font-mono">
                    {editing.override_cron_schedule}
                  </span>
                </>
              ) : null}
            </p>
            <p className="text-xs text-muted-foreground">
              저장 후 코드 위치 새로고침이 반영될 때까지 지연이 있을 수
              있습니다.
            </p>
          </div>
          <DialogFooter>
            <Button
              aria-label="기본값으로 되돌리기"
              disabled={scheduleControlsDisabled}
              type="button"
              variant="outline"
              onClick={() => submitCronPatch(null)}
            >
              <RotateCcwIcon data-icon="inline-start" />
              기본값으로 되돌리기
            </Button>
            <Button
              disabled={scheduleControlsDisabled || !cronDraft.trim()}
              type="button"
              onClick={() => submitCronPatch(cronDraft.trim())}
            >
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function SchedulePanelView({
  claimResolution,
  claimResolutionReason,
  commandReasons,
  commandSchedule,
  cronDraft,
  data,
  editReason,
  editing,
  failedResult,
  frozenClaimResolution,
  frozenScheduleMutation,
  highlightRef,
  highlightSchedule,
  lastResult,
  openEdit,
  patchSchedule,
  recoveryClaim,
  resolveClaim,
  retryFrozenScheduleMutation,
  scheduleControlsDisabled,
  scheduleItems,
  scheduleStateScanned,
  schedules,
  sensors,
  setClaimResolution,
  setClaimResolutionReason,
  setCommandReasons,
  setCronDraft,
  setEditReason,
  setEditing,
  submitClaimResolution,
  submitCommand,
  submitCronPatch,
}: ReturnType<typeof useSchedulePanelController>) {
  return (
    <div
      className="space-y-4"
      data-schedule-state-scanned={scheduleStateScanned ? "true" : "false"}
      data-testid="pipeline-schedule-panel"
    >
      <ScheduleEditor claimResolution={claimResolution} claimResolutionReason={claimResolutionReason} commandSchedule={commandSchedule} data={data} failedResult={failedResult} frozenClaimResolution={frozenClaimResolution} frozenScheduleMutation={frozenScheduleMutation} lastResult={lastResult} patchSchedule={patchSchedule} recoveryClaim={recoveryClaim} resolveClaim={resolveClaim} retryFrozenScheduleMutation={retryFrozenScheduleMutation} scheduleStateScanned={scheduleStateScanned} schedules={schedules} setClaimResolution={setClaimResolution} setClaimResolutionReason={setClaimResolutionReason} submitClaimResolution={submitClaimResolution} />

      <ScheduleSummary schedules={schedules} sensors={sensors} />

      <ScheduleTable commandReasons={commandReasons} highlightRef={highlightRef} highlightSchedule={highlightSchedule} openEdit={openEdit} scheduleControlsDisabled={scheduleControlsDisabled} scheduleItems={scheduleItems} schedules={schedules} setCommandReasons={setCommandReasons} submitCommand={submitCommand} />

      <ScheduleDeleteDialog cronDraft={cronDraft} editReason={editReason} editing={editing} scheduleControlsDisabled={scheduleControlsDisabled} setCronDraft={setCronDraft} setEditReason={setEditReason} setEditing={setEditing} submitCronPatch={submitCronPatch} />
    </div>
  );
}

export function SchedulePanel({
  highlightSchedule,
  onHighlightSchedule,
}: {
  highlightSchedule?: string;
  onHighlightSchedule: (scheduleName: string) => void;
}) {
  const controller = useSchedulePanelController({ highlightSchedule, onHighlightSchedule });
  return <SchedulePanelView {...controller} />;
}
