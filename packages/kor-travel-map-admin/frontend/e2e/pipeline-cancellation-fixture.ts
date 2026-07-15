import type { components } from "../src/api/types";

type PipelineCancellationResponse =
  components["schemas"]["PipelineCancellationResponse"];
type PipelineCancellationMemberKind =
  components["schemas"]["PipelineCancellationRootRecord"]["kind"];

type CancellationFixtureMember = {
  memberKind: PipelineCancellationMemberKind;
  memberId: string;
  initialStatus?: string;
  dagsterRunId?: string | null;
  operationKind?: string | null;
  terminalStatus?: string | null;
};

type CancellationFixtureOptions = {
  rootKind: PipelineCancellationMemberKind;
  rootId: string;
  initialStatus?: string;
  dagsterRunId?: string | null;
  reason?: string | null;
  members?: readonly CancellationFixtureMember[];
};

/** 공개 cancel operation 세 곳이 공유하는 원자적 계층 취소 응답 fixture. */
export function makePipelineCancellationResponse({
  rootKind,
  rootId,
  initialStatus = "queued",
  dagsterRunId = null,
  reason = null,
  members,
}: CancellationFixtureOptions): PipelineCancellationResponse {
  const now = "2026-07-14T00:00:00.000Z";
  const memberFixtures = members ?? [
    {
      memberId: rootId,
      memberKind: rootKind,
    },
  ];
  const memberInitialStatus = (member: CancellationFixtureMember): string =>
    member.initialStatus ?? initialStatus;
  const memberRunId = (member: CancellationFixtureMember): string | null =>
    member.dagsterRunId === undefined ? dagsterRunId : member.dagsterRunId;
  const memberOperationKind = (
    member: CancellationFixtureMember,
  ): string | null => member.operationKind ?? null;
  const requiresRunTermination = (
    member: CancellationFixtureMember,
  ): boolean => {
    const status = memberInitialStatus(member);
    const operationKind = memberOperationKind(member);
    return (
      memberRunId(member) !== null &&
      (status === "running" ||
        (status === "queued" &&
          (operationKind === "provider_feature_load_run" ||
            operationKind === "provider_feature_load")))
    );
  };
  for (const member of memberFixtures) {
    const status = memberInitialStatus(member);
    const runId = memberRunId(member);
    if (status === "running" && runId === null) {
      throw new Error("running cancellation fixture member requires a Dagster run");
    }
    if (status === "queued" && runId !== null && !requiresRunTermination(member)) {
      throw new Error(
        "queued cancellation fixture run requires a reserved feature operation kind",
      );
    }
    if (status !== "queued" && status !== "running") {
      throw new Error(
        `completed cancellation fixture does not support initial status: ${status}`,
      );
    }
  }
  const runIds = [
    ...new Set(
      memberFixtures
        .filter(requiresRunTermination)
        .map(memberRunId)
        .filter((runId): runId is string => runId !== null),
    ),
  ];
  return {
    data: {
      cancellation_id: `e2e-cancel-${rootId}`,
      committed_data_rolled_back: false,
      dagster_runs: runIds.map((runId) => ({
        dagster_run_id: runId,
        error: null,
        engine_started_at: now,
        engine_finished_at: now,
        initial_status: "STARTED",
        result: "cancelled",
        terminal_status: "CANCELED",
        termination_reserved_at: now,
        updated_at: now,
      })),
      error: null,
      finished_at: now,
      members: memberFixtures.map((member) => ({
        dagster_run_id: memberRunId(member),
        error: null,
        initial_status: memberInitialStatus(member),
        member_id: member.memberId,
        member_kind: member.memberKind,
        operation_kind: memberOperationKind(member),
        requires_run_termination: requiresRunTermination(member),
        result: "cancelled",
        terminal_status:
          member.terminalStatus === undefined
            ? "cancelled"
            : member.terminalStatus,
        updated_at: now,
      })),
      previous_cancellation_id: null,
      reason,
      requested_at: now,
      requested_by: "e2e-admin",
      retryable: false,
      root: { id: rootId, kind: rootKind },
      status: "completed",
      unresolved_member_count: 0,
      updated_at: now,
    },
    meta: { duration_ms: 1, request_id: "e2e-pipeline-cancel" },
  };
}
