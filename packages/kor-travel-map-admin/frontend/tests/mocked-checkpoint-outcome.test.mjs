import { describe, expect, it } from "vitest";

import { classifyMockedCheckpointOutcome } from "../e2e/mocked-checkpoint-outcome.mjs";

const passedReporter = {
  discoveredTests: 276,
  gatePassed: true,
  originalStatus: "passed",
};

describe("mocked checkpoint outcome", () => {
  it("manifest가 일치해도 Playwright child nonzero를 설명 가능한 실패로 남긴다", () => {
    const outcome = classifyMockedCheckpointOutcome({
      child: { signal: null, spawnError: false, status: 1 },
      reporter: passedReporter,
    });

    expect(outcome).toMatchObject({
      classification: "test_failed",
      exitCode: 1,
      issues: ["playwright_child_nonzero"],
      playwright: {
        childExitStatus: 1,
        discoveredTests: 276,
        originalStatus: "passed",
        reporterGatePassed: true,
      },
    });
  });

  it("child signal과 reporter gate 불일치를 각각 보존한다", () => {
    const outcome = classifyMockedCheckpointOutcome({
      child: { signal: "SIGTERM", spawnError: false, status: 1 },
      reporter: { ...passedReporter, gatePassed: false },
    });

    expect(outcome.classification).toBe("infrastructure_failed");
    expect(outcome.exitCode).toBe(2);
    expect(outcome.issues).toEqual([
      "playwright_child_signaled",
      "reporter_gate_failed",
    ]);
  });

  it("postcondition과 cleanup 실패를 test 실패보다 우선한다", () => {
    const outcome = classifyMockedCheckpointOutcome({
      child: { signal: null, spawnError: false, status: 1 },
      cleanupFailures: ["cleanup_container_remaining"],
      postconditionFailures: ["postcondition_worktree_changed"],
      reporter: passedReporter,
    });

    expect(outcome.classification).toBe("infrastructure_failed");
    expect(outcome.exitCode).toBe(2);
    expect(outcome.issues).toEqual([
      "cleanup_container_remaining",
      "postcondition_worktree_changed",
      "playwright_child_nonzero",
    ]);
  });

  it("child와 reporter, postcondition, cleanup이 모두 정상일 때만 통과한다", () => {
    const outcome = classifyMockedCheckpointOutcome({
      child: { signal: null, spawnError: false, status: 0 },
      reporter: passedReporter,
    });

    expect(outcome).toMatchObject({
      classification: "passed",
      exitCode: 0,
      issues: [],
    });
  });
});
