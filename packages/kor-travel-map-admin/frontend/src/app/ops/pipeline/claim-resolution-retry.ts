import { ApiClientError } from "@/api/client";

const OUTCOME_UNCERTAIN_CODES = new Set([
  "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN",
]);
const OUTCOME_UNCERTAIN_HTTP_STATUSES = new Set([408, 425, 429, 499]);

/** 응답 결과를 확정할 수 없는 오류에서만 동일 claim resolution body를 유지한다. */
export function shouldRetainClaimResolutionSubmission(error: unknown): boolean {
  if (!(error instanceof ApiClientError)) {
    return true;
  }
  if (error.status >= 500) {
    return true;
  }
  if (OUTCOME_UNCERTAIN_HTTP_STATUSES.has(error.status)) {
    return true;
  }
  return (
    error.status === 409 &&
    OUTCOME_UNCERTAIN_CODES.has(error.problem?.code ?? "")
  );
}
