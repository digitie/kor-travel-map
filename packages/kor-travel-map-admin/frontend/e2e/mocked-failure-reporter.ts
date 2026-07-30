import type {
  FullConfig,
  FullResult,
  Reporter,
  Suite,
  TestCase,
  TestError,
  TestResult,
  TestStep,
} from "@playwright/test/reporter";
import { createHash } from "node:crypto";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { stripVTControlCharacters } from "node:util";

type Checkpoint = "A" | "B" | "C" | "D";
export type FailureStage =
  | "beforeEach.auth"
  | "interaction"
  | "mock.install"
  | "render.assertion"
  | "request.assertion";

interface ManifestTest {
  line: number;
  title: string;
}

interface ManifestGroup {
  difference: string;
  determinism: "deterministic" | "flaky";
  errorPattern: string;
  firstFailureStage: FailureStage;
  fixedIn: Exclude<Checkpoint, "A">;
  spec: string;
  tests: ManifestTest[];
}

interface FailureManifest {
  allowedSkipped: Array<{
    spec: string;
    title: string;
  }>;
  baselineMainRevision: string;
  baselineRevision: string;
  discoveredTests: number;
  groups: ManifestGroup[];
  schemaVersion: 3;
  testInventorySha256: string;
}

interface TestIdentity {
  key: string;
  spec: string;
  title: string;
}

const CHECKPOINT_ORDER: Record<Checkpoint, number> = {
  A: 0,
  B: 1,
  C: 2,
  D: 3,
};

function sortedDifference(left: Set<string>, right: Set<string>): string[] {
  return [...left].filter((value) => !right.has(value)).sort();
}

function identityKey(spec: string, title: string): string {
  return `${spec}::${title}`;
}

export function testInventorySha256(identities: Iterable<string>): string {
  const canonical = [...identities].sort().join("\n");
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

function testIdentity(test: TestCase): TestIdentity {
  const spec = path
    .relative(process.cwd(), test.location.file)
    .split(path.sep)
    .join("/");
  const titlePath = test.titlePath();
  const fileIndex = titlePath.findIndex(
    (part) => part === path.basename(test.location.file),
  );
  if (fileIndex < 0) {
    throw new Error(`test title path에 spec이 없습니다: ${spec}`);
  }
  const title = titlePath.slice(fileIndex + 1).join(" › ");
  return { key: identityKey(spec, title), spec, title };
}

function parseCheckpoint(value: string | undefined): Checkpoint {
  if (value === "A" || value === "B" || value === "C" || value === "D") {
    return value;
  }
  throw new Error("MOCKED_E2E_CHECKPOINT는 A, B, C, D 중 하나여야 합니다.");
}

function validateManifest(manifest: FailureManifest): void {
  if (manifest.schemaVersion !== 3) {
    throw new Error(
      `지원하지 않는 failure manifest schema: ${manifest.schemaVersion}`,
    );
  }
  for (const [name, revision] of [
    ["baselineMainRevision", manifest.baselineMainRevision],
    ["baselineRevision", manifest.baselineRevision],
  ]) {
    if (!/^[0-9a-f]{40}$/.test(revision)) {
      throw new Error(`${name}에 exact 40자 SHA가 필요합니다.`);
    }
  }
  if (
    !Number.isInteger(manifest.discoveredTests) ||
    manifest.discoveredTests < 1
  ) {
    throw new Error("discoveredTests는 양의 정수여야 합니다.");
  }
  if (!/^[0-9a-f]{64}$/u.test(manifest.testInventorySha256)) {
    throw new Error("testInventorySha256에 exact SHA-256이 필요합니다.");
  }
  for (const group of manifest.groups) {
    if (
      !group.spec.startsWith("e2e/") ||
      !group.spec.endsWith(".spec.ts") ||
      !(
        group.fixedIn === "B" ||
        group.fixedIn === "C" ||
        group.fixedIn === "D"
      ) ||
      !(
        group.determinism === "deterministic" || group.determinism === "flaky"
      ) ||
      ![
        "beforeEach.auth",
        "interaction",
        "mock.install",
        "render.assertion",
        "request.assertion",
      ].includes(group.firstFailureStage) ||
      !group.difference ||
      !group.errorPattern ||
      group.tests.length === 0
    ) {
      throw new Error(`잘못된 failure group: ${group.spec}`);
    }
    for (const test of group.tests) {
      if (!Number.isInteger(test.line) || test.line < 1 || !test.title) {
        throw new Error(`잘못된 failure test: ${group.spec}`);
      }
    }
    try {
      new RegExp(group.errorPattern, "u");
    } catch {
      throw new Error(`잘못된 failure errorPattern: ${group.spec}`);
    }
  }
}

interface FailureEvidence {
  errorIndex: number;
  retry: number;
  status: TestResult["status"];
  stepPath: TestStep[];
  text: string;
}

interface FailedStepPath {
  hasFailedDescendant: boolean;
  stepPath: TestStep[];
}

function failureErrorText(error: TestError | undefined): string {
  return [error?.message, error?.stack, error?.value]
    .filter((value): value is string => Boolean(value))
    .join("\n");
}

function failedStepPaths(
  steps: TestStep[],
  parents: TestStep[] = [],
): FailedStepPath[] {
  const paths: FailedStepPath[] = [];
  for (const step of steps) {
    const currentPath = [...parents, step];
    const childPaths = failedStepPaths(step.steps, currentPath);
    if (step.error) {
      paths.push({
        hasFailedDescendant: childPaths.length > 0,
        stepPath: currentPath,
      });
    }
    paths.push(...childPaths);
  }
  return paths;
}

function isStrictStepAncestor(
  ancestor: TestStep[],
  descendant: TestStep[],
): boolean {
  return (
    ancestor.length < descendant.length &&
    ancestor.every((step, index) => descendant[index] === step)
  );
}

function diagnosticStepPath(
  failure: FailedStepPath | undefined,
  failures: FailedStepPath[],
): TestStep[] {
  if (!failure) return [];
  if (!failure.hasFailedDescendant) return failure.stepPath;
  const deepestLeaf = failures
    .filter(
      (candidate) =>
        !candidate.hasFailedDescendant &&
        isStrictStepAncestor(failure.stepPath, candidate.stepPath),
    )
    .sort(
      (left, right) => right.stepPath.length - left.stepPath.length,
    )
    .at(0);
  return deepestLeaf?.stepPath ?? failure.stepPath;
}

function isPlaywrightTimeoutEnvelope(error: TestError): boolean {
  return /^Test timeout of \d+ms exceeded(?: while running "(?:beforeAll|beforeEach|afterEach|afterAll)" hook)?\.$/u.test(
    stripVTControlCharacters(error.message ?? ""),
  );
}

function failureEvidence(results: readonly TestResult[]): FailureEvidence[] {
  return results.flatMap((result) => {
    if (result.status === "passed") {
      return [];
    }

    const stepPaths = failedStepPaths(result.steps);
    const unmatchedStepPaths = new Set(stepPaths);
    const matchingStepPaths = result.errors.map((error) => {
      const text = failureErrorText(error);
      const matchingStepPath = stepPaths
        .filter(
          ({ stepPath }) =>
            failureErrorText(stepPath.at(-1)?.error) === text,
        )
        .sort(
          (left, right) =>
            right.stepPath.length - left.stepPath.length,
        )
        .find((stepPath) => unmatchedStepPaths.has(stepPath));
      if (matchingStepPath) {
        unmatchedStepPaths.delete(matchingStepPath);
      }
      return matchingStepPath;
    });
    const matchedLeafErrorIndexes = new Set(
      matchingStepPaths.flatMap((matchingStepPath, errorIndex) =>
        matchingStepPath && !matchingStepPath.hasFailedDescendant
          ? [errorIndex]
          : [],
      ),
    );
    const excludedEnvelopeTexts = new Set<string>();
    const evidence = result.errors.flatMap((error, errorIndex) => {
      const matchingStepPath = matchingStepPaths[errorIndex];
      if (
        result.status === "timedOut" &&
        isPlaywrightTimeoutEnvelope(error) &&
        [...matchedLeafErrorIndexes].some(
          (leafErrorIndex) => leafErrorIndex !== errorIndex,
        )
      ) {
        excludedEnvelopeTexts.add(failureErrorText(error));
        return [];
      }
      return [{
        errorIndex,
        retry: result.retry,
        status: result.status,
        stepPath: diagnosticStepPath(matchingStepPath, stepPaths),
        text: failureErrorText(error),
      }];
    });

    let nextStepOnlyErrorIndex = result.errors.length;
    for (const failedStepPath of unmatchedStepPaths) {
      const text = failureErrorText(
        failedStepPath.stepPath.at(-1)?.error,
      );
      const duplicatesMatchedResult = result.errors.some(
        (resultError, resultErrorIndex) => {
          const matchingStepPath =
            matchingStepPaths[resultErrorIndex]?.stepPath;
          return (
            matchingStepPath !== undefined &&
            failureErrorText(resultError) === text &&
            isStrictStepAncestor(
              failedStepPath.stepPath,
              matchingStepPath,
            )
          );
        },
      );
      if (duplicatesMatchedResult) continue;
      if (
        isPlaywrightTimeoutEnvelope(
          failedStepPath.stepPath.at(-1)?.error ?? {},
        ) &&
        excludedEnvelopeTexts.has(text)
      ) {
        continue;
      }
      evidence.push({
        errorIndex: nextStepOnlyErrorIndex,
        retry: result.retry,
        status: result.status,
        stepPath: diagnosticStepPath(failedStepPath, stepPaths),
        text,
      });
      nextStepOnlyErrorIndex += 1;
    }
    if (evidence.length === 0) {
      evidence.push({
        errorIndex: 0,
        retry: result.retry,
        status: result.status,
        stepPath: [],
        text: "",
      });
    }
    return evidence;
  });
}

function isHookStep(step: TestStep): boolean {
  return step.category === "hook";
}

function isRequestAssertionStep(step: TestStep): boolean {
  return (
    step.category === "expect" &&
    /^Expect "(?:toMatchObject|poll toBeGreaterThanOrEqual)"/u.test(step.title)
  );
}

function serializedStepPath(stepPath: TestStep[]) {
  return stepPath.map((step) => ({
    category: step.category,
    location: step.location
      ? {
          file: path.basename(step.location.file),
          line: step.location.line,
        }
      : null,
  }));
}

export function firstFailureStageMatches(
  stage: FailureStage,
  stepPath: TestStep[],
): boolean {
  const leaf = stepPath.at(-1);
  const hasHook = stepPath.some(isHookStep);
  switch (stage) {
    case "beforeEach.auth":
      return (
        stepPath.at(0)?.category === "hook" &&
        stepPath.at(0)?.title === "Before Hooks" &&
        stepPath.at(1)?.category === "hook" &&
        stepPath.at(1)?.title === "beforeEach hook" &&
        leaf?.category === "pw:api"
      );
    case "interaction":
      return !hasHook && leaf?.category === "pw:api";
    case "mock.install":
      return stepPath.length === 0;
    case "render.assertion":
      return (
        !hasHook &&
        leaf?.category === "expect" &&
        !stepPath.some(isRequestAssertionStep)
      );
    case "request.assertion":
      return !hasHook && stepPath.some(isRequestAssertionStep);
  }
}

export function expectedFailureEvidenceMismatches(
  results: readonly TestResult[],
  errorPattern: string,
  failureStage: FailureStage,
) {
  const expectedCause = new RegExp(errorPattern, "u");
  const evidence = failureEvidence(results);
  if (evidence.length === 0) {
    const lastResult = results.at(-1);
    return [
      {
        causeMatched: false,
        errorIndex: -1,
        failureStepPath: [],
        retry: lastResult?.retry ?? -1,
        stageMatched: false,
        status: lastResult?.status ?? "missing",
        statusMatched: false,
      },
    ];
  }
  return evidence
    .map(({ errorIndex, retry, status, stepPath, text }) => ({
      causeMatched: text.length > 0 && expectedCause.test(text),
      errorIndex,
      failureStepPath: serializedStepPath(stepPath),
      retry,
      stageMatched: firstFailureStageMatches(failureStage, stepPath),
      status,
      statusMatched: status === "failed" || status === "timedOut",
    }))
    .filter(
      ({ causeMatched, stageMatched, statusMatched }) =>
        !causeMatched || !stageMatched || !statusMatched,
    );
}

class MockedFailureReporter implements Reporter {
  private globalErrors = 0;
  private tests: TestCase[] = [];

  onBegin(_config: FullConfig, suite: Suite): void {
    this.tests = suite.allTests();
  }

  onError(): void {
    this.globalErrors += 1;
  }

  async onEnd(result: FullResult): Promise<{ status?: FullResult["status"] }> {
    let gatePassed = false;
    try {
      const checkpoint = parseCheckpoint(process.env.MOCKED_E2E_CHECKPOINT);
      const observedRevision =
        process.env.MOCKED_E2E_REVISION ?? process.env.GITHUB_SHA;
      if (!observedRevision || !/^[0-9a-f]{40}$/.test(observedRevision)) {
        throw new Error(
          "MOCKED_E2E_REVISION 또는 GITHUB_SHA에 exact 40자 SHA가 필요합니다.",
        );
      }
      const verifiedRevision = process.env.MOCKED_E2E_VERIFIED_REVISION;
      if (verifiedRevision !== observedRevision) {
        throw new Error(
          "runner가 검증한 Git HEAD와 observed revision이 일치해야 합니다.",
        );
      }
      const verifiedFrontendRevision =
        process.env.MOCKED_E2E_VERIFIED_FRONTEND_REVISION;
      if (verifiedFrontendRevision !== observedRevision) {
        throw new Error(
          "runner가 검증한 실제 frontend와 observed revision이 일치해야 합니다.",
        );
      }
      const verifiedFrontendSourceDigest =
        process.env.MOCKED_E2E_VERIFIED_FRONTEND_SOURCE_DIGEST;
      if (
        !verifiedFrontendSourceDigest ||
        !/^[0-9a-f]{64}$/.test(verifiedFrontendSourceDigest)
      ) {
        throw new Error(
          "runner가 검증한 실제 frontend source digest가 필요합니다.",
        );
      }
      const verifiedFrontendImageId =
        process.env.MOCKED_E2E_VERIFIED_FRONTEND_IMAGE_ID;
      const verifiedFrontendContainerId =
        process.env.MOCKED_E2E_VERIFIED_FRONTEND_CONTAINER_ID;
      if (
        !verifiedFrontendImageId ||
        !/^sha256:[0-9a-f]{64}$/.test(verifiedFrontendImageId) ||
        !verifiedFrontendContainerId ||
        !/^[0-9a-f]{64}$/.test(verifiedFrontendContainerId)
      ) {
        throw new Error(
          "runner가 검증한 immutable frontend image/container identity가 필요합니다.",
        );
      }

      const manifestPath = path.join(
        process.cwd(),
        "e2e",
        "mocked-failure-manifest.json",
      );
      const manifest = JSON.parse(
        await readFile(manifestPath, "utf8"),
      ) as FailureManifest;
      validateManifest(manifest);

      const identities = this.tests.map(testIdentity);
      const discovered = new Set(identities.map(({ key }) => key));
      if (discovered.size !== identities.length) {
        throw new Error("mocked suite에 중복 spec/title identity가 있습니다.");
      }
      const observedTestInventorySha256 = testInventorySha256(discovered);

      const manifestTests = manifest.groups.flatMap((group) =>
        group.tests.map((test) => ({
          key: identityKey(group.spec, test.title),
          determinism: group.determinism,
          difference: group.difference,
          errorPattern: group.errorPattern,
          fixedIn: group.fixedIn,
          firstFailureStage: group.firstFailureStage,
        })),
      );
      const manifestKeys = new Set(manifestTests.map(({ key }) => key));
      if (manifestKeys.size !== manifestTests.length) {
        throw new Error(
          "failure manifest에 중복 spec/title identity가 있습니다.",
        );
      }

      const missingManifestTests = sortedDifference(manifestKeys, discovered);
      const expectedFailures = new Set(
        manifestTests
          .filter(
            ({ determinism, fixedIn }) =>
              determinism === "deterministic" &&
              CHECKPOINT_ORDER[fixedIn] > CHECKPOINT_ORDER[checkpoint],
          )
          .map(({ key }) => key),
      );
      const expectedFlakes = new Set(
        manifestTests
          .filter(
            ({ determinism, fixedIn }) =>
              determinism === "flaky" &&
              CHECKPOINT_ORDER[fixedIn] > CHECKPOINT_ORDER[checkpoint],
          )
          .map(({ key }) => key),
      );
      const expectedFailureFingerprints = new Set([
        ...expectedFailures,
        ...expectedFlakes,
      ]);
      const unexpectedFailures = new Set(
        this.tests
          .filter((test) => test.outcome() === "unexpected")
          .map((test) => testIdentity(test).key),
      );
      const flakyTests = new Set(
        this.tests
          .filter((test) => test.outcome() === "flaky")
          .map((test) => testIdentity(test).key),
      );
      const skippedTests = new Set(
        this.tests
          .filter((test) => test.outcome() === "skipped")
          .map((test) => testIdentity(test).key),
      );
      const allowedSkipped = new Set(
        manifest.allowedSkipped.map(({ spec, title }) =>
          identityKey(spec, title),
        ),
      );
      const testByIdentity = new Map(
        this.tests.map((test) => [testIdentity(test).key, test]),
      );
      const mismatchedExpectedFailureEvidence = manifestTests
        .filter(({ key }) => expectedFailureFingerprints.has(key))
        .flatMap(({ difference, errorPattern, firstFailureStage, key }) => {
          const test = testByIdentity.get(key);
          return expectedFailureEvidenceMismatches(
            test?.results ?? [],
            errorPattern,
            firstFailureStage,
          ).map((mismatch) => ({
            ...mismatch,
            difference,
            firstFailureStage,
            key,
          }));
        })
        .sort(
          (left, right) =>
            left.key.localeCompare(right.key) ||
            left.retry - right.retry ||
            left.errorIndex - right.errorIndex,
        );

      const report = {
        schemaVersion: 3,
        checkpoint,
        observedRevision,
        observedFrontendSourceDigest: verifiedFrontendSourceDigest,
        observedFrontendImageId: verifiedFrontendImageId,
        observedFrontendContainerId: verifiedFrontendContainerId,
        baselineMainRevision: manifest.baselineMainRevision,
        baselineRevision: manifest.baselineRevision,
        discoveredTests: identities.length,
        observedTestInventorySha256,
        expectedTestInventorySha256: manifest.testInventorySha256,
        expectedFailures: [...expectedFailures].sort(),
        expectedFlakes: [...expectedFlakes].sort(),
        unexpectedFailures: [...unexpectedFailures].sort(),
        flakyTests: [...flakyTests].sort(),
        skippedTests: [...skippedTests].sort(),
        missingExpectedFailures: sortedDifference(
          expectedFailures,
          unexpectedFailures,
        ),
        newUnexpectedFailures: sortedDifference(
          unexpectedFailures,
          expectedFailures,
        ),
        missingExpectedFlakes: sortedDifference(expectedFlakes, flakyTests),
        newFlakyTests: sortedDifference(flakyTests, expectedFlakes),
        missingManifestTests,
        missingAllowedSkipped: sortedDifference(allowedSkipped, skippedTests),
        newSkippedTests: sortedDifference(skippedTests, allowedSkipped),
        mismatchedExpectedFailureEvidence,
        globalErrors: this.globalErrors,
        originalStatus: result.status,
        gatePassed: false,
      };

      gatePassed =
        identities.length === manifest.discoveredTests &&
        observedTestInventorySha256 === manifest.testInventorySha256 &&
        result.status === (checkpoint === "D" ? "passed" : "failed") &&
        report.missingExpectedFailures.length === 0 &&
        report.newUnexpectedFailures.length === 0 &&
        report.missingExpectedFlakes.length === 0 &&
        report.newFlakyTests.length === 0 &&
        report.missingManifestTests.length === 0 &&
        report.missingAllowedSkipped.length === 0 &&
        report.newSkippedTests.length === 0 &&
        report.mismatchedExpectedFailureEvidence.length === 0 &&
        report.globalErrors === 0;
      report.gatePassed = gatePassed;

      const artifactRoot =
        process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
        path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend");
      const outputPath =
        process.env.MOCKED_E2E_FAILURE_OUTPUT ??
        path.join(artifactRoot, "mocked-failure-report.json");
      await mkdir(path.dirname(outputPath), { recursive: true });
      await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, {
        mode: 0o600,
      });
      await chmod(outputPath, 0o600);

      const summary = gatePassed ? "일치" : "불일치";
      console.log(
        `[mocked-checkpoint ${checkpoint}] manifest ${summary}: ` +
          `tests=${identities.length}, expected-failures=${expectedFailures.size}, ` +
          `actual-failures=${unexpectedFailures.size}, flakes=${flakyTests.size}, ` +
          `inventory=${observedTestInventorySha256}`,
      );
      if (!gatePassed) {
        console.error(
          `[mocked-checkpoint ${checkpoint}] redacted report: ${outputPath}`,
        );
      }
    } catch (error) {
      console.error(
        `[mocked-checkpoint] ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    return { status: gatePassed ? "passed" : "failed" };
  }

  printsToStdio(): boolean {
    return false;
  }
}

export default MockedFailureReporter;
