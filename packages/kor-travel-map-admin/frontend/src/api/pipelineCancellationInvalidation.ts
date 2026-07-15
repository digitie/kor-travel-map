import type { components } from "./types";

type PipelineCancellationMember =
  components["schemas"]["PipelineCancellationMemberRecord"];
type PipelineCancellationMemberIdentity = Pick<
  PipelineCancellationMember,
  "job_id"
>;
type PipelineCancellationRoot =
  components["schemas"]["PipelineCancellationRootRecord"];

export function pipelineCancellationQueryKeys(
  members: readonly PipelineCancellationMemberIdentity[] | undefined,
  root?: PipelineCancellationRoot,
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
  if (root?.kind === "update_request") {
    queryKeys.push(["feature-update-request", root.id]);
  }
  for (const member of members) {
    queryKeys.push(["import-job", member.job_id]);
    queryKeys.push(["import-job-events", member.job_id]);
  }
  return queryKeys;
}
