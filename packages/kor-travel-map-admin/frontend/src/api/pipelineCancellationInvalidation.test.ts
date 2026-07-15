import { describe, expect, it } from "vitest";

import { pipelineCancellationQueryKeys } from "./pipelineCancellationInvalidation";

describe("pipeline cancellation query invalidation", () => {
  it("오류 응답은 알 수 없는 연결 상세와 event를 singular prefix로 무효화한다", () => {
    expect(pipelineCancellationQueryKeys(undefined)).toEqual([
      ["import-jobs"],
      ["feature-update-requests"],
      ["import-job"],
      ["import-job-events"],
      ["feature-update-request"],
    ]);
  });

  it("성공 응답은 folded root의 모든 member 상세를 정확한 key로 무효화한다", () => {
    expect(
      pipelineCancellationQueryKeys(
        [{ job_id: "job-1" }],
        { kind: "update_request", id: "request-1" },
      ),
    ).toEqual([
      ["import-jobs"],
      ["feature-update-requests"],
      ["feature-update-request", "request-1"],
      ["import-job", "job-1"],
      ["import-job-events", "job-1"],
    ]);
  });
});
