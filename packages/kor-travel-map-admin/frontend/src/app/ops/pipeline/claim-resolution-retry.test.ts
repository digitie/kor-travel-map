import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/api/client";

import { shouldRetainClaimResolutionSubmission } from "./claim-resolution-retry";

function apiError(status: number, code: string): ApiClientError {
  return new ApiClientError("failed", status, "/claim/resolve", {
    type: "https://kor-travel-map/errors/test",
    title: "failed",
    status,
    detail: "failed",
    code,
    request_id: "test-request",
    errors: [],
  });
}

describe("shouldRetainClaimResolutionSubmission", () => {
  it("네트워크와 5xx는 동일 body retry를 위해 유지한다", () => {
    expect(
      shouldRetainClaimResolutionSubmission(new TypeError("offline")),
    ).toBe(true);
    expect(
      shouldRetainClaimResolutionSubmission(
        apiError(503, "STORAGE_UNAVAILABLE"),
      ),
    ).toBe(true);
  });

  it.each([408, 425, 429, 499])(
    "HTTP %s 결과 불명 상태도 유지한다",
    (status) => {
      expect(
        shouldRetainClaimResolutionSubmission(
          apiError(status, "TRANSPORT_UNCERTAIN"),
        ),
      ).toBe(true);
    },
  );

  it("outcome-uncertain 409만 유지한다", () => {
    expect(
      shouldRetainClaimResolutionSubmission(
        apiError(409, "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN"),
      ),
    ).toBe(true);
    expect(
      shouldRetainClaimResolutionSubmission(
        apiError(409, "DAGSTER_SCHEDULE_CLAIM_RESOLUTION_CONFLICT"),
      ),
    ).toBe(false);
    expect(
      shouldRetainClaimResolutionSubmission(
        apiError(409, "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT"),
      ),
    ).toBe(false);
  });

  it("422 등 확정 4xx는 입력 수정을 위해 해제한다", () => {
    expect(
      shouldRetainClaimResolutionSubmission(apiError(422, "VALIDATION_ERROR")),
    ).toBe(false);
  });
});
