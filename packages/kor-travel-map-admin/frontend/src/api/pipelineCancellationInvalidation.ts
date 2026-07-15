import type { components } from "./types";

type PipelineCancellationMember =
  components["schemas"]["PipelineCancellationMemberRecord"];
type PipelineCancellationMemberIdentity = Pick<
  PipelineCancellationMember,
  "member_id" | "member_kind"
>;

export function pipelineCancellationQueryKeys(
  members: readonly PipelineCancellationMemberIdentity[] | undefined,
): ReadonlyArray<readonly unknown[]> {
  const queryKeys: Array<readonly unknown[]> = [
    ["import-jobs"],
    ["feature-update-requests"],
  ];
  if (members === undefined) {
    return [
      ...queryKeys,
      ["import-job"],
      ["import-job-events"],
      ["feature-update-request"],
    ];
  }
  for (const member of members) {
    if (member.member_kind === "import_job") {
      queryKeys.push(["import-job", member.member_id]);
      queryKeys.push(["import-job-events", member.member_id]);
    } else {
      queryKeys.push(["feature-update-request", member.member_id]);
    }
  }
  return queryKeys;
}
