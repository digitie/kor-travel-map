const INFRASTRUCTURE_EXIT_CODE = 2;
const TEST_EXIT_CODE = 1;

function childStatusIssue(child) {
  if (!child) return "playwright_not_started";
  if (child.spawnError) return "playwright_spawn_failed";
  if (child.status !== 0) return "playwright_child_nonzero";
  return undefined;
}

export function classifyMockedCheckpointOutcome({
  child,
  cleanupFailures = [],
  postconditionFailures = [],
  reporter,
  runnerFailure,
}) {
  const infrastructureIssues = [];
  const testIssues = [];

  if (runnerFailure) infrastructureIssues.push(runnerFailure);
  if (!reporter) {
    infrastructureIssues.push("reporter_outcome_missing");
  }
  if (!child) {
    infrastructureIssues.push("playwright_not_started");
  } else if (child.spawnError) {
    infrastructureIssues.push("playwright_spawn_failed");
  } else if (child.signal) {
    infrastructureIssues.push("playwright_child_signaled");
  } else {
    const issue = childStatusIssue(child);
    if (issue) testIssues.push(issue);
  }
  if (reporter && reporter.gatePassed !== true) {
    testIssues.push("reporter_gate_failed");
  }
  infrastructureIssues.push(...postconditionFailures);
  infrastructureIssues.push(...cleanupFailures);

  const uniqueInfrastructureIssues = [...new Set(infrastructureIssues)].sort();
  const uniqueTestIssues = [...new Set(testIssues)].sort();
  const exitCode =
    uniqueInfrastructureIssues.length > 0
      ? INFRASTRUCTURE_EXIT_CODE
      : uniqueTestIssues.length > 0
        ? TEST_EXIT_CODE
        : 0;

  return {
    schemaVersion: 1,
    classification:
      exitCode === 0
        ? "passed"
        : exitCode === TEST_EXIT_CODE
          ? "test_failed"
          : "infrastructure_failed",
    exitCode,
    issues: [...uniqueInfrastructureIssues, ...uniqueTestIssues],
    playwright: {
      childExitStatus: child?.status ?? null,
      childSignal: child?.signal ?? null,
      discoveredTests: reporter?.discoveredTests ?? null,
      originalStatus: reporter?.originalStatus ?? null,
      reporterGatePassed: reporter?.gatePassed ?? null,
    },
  };
}
