import type {
  FullConfig,
  FullResult,
  Reporter,
  Suite,
  TestCase,
} from "@playwright/test/reporter";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

type Checkpoint = "A" | "B" | "C" | "D";

interface ManifestTest {
  line: number;
  title: string;
}

interface ManifestGroup {
  difference: string;
  determinism: "deterministic" | "flaky";
  firstFailureStage: string;
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
  schemaVersion: 1;
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
  if (manifest.schemaVersion !== 1) {
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
  for (const group of manifest.groups) {
    if (
      !group.spec.startsWith("e2e/") ||
      !group.spec.endsWith(".spec.ts") ||
      !(group.fixedIn === "B" || group.fixedIn === "C" || group.fixedIn === "D") ||
      !(group.determinism === "deterministic" || group.determinism === "flaky") ||
      !group.firstFailureStage ||
      !group.difference ||
      group.tests.length === 0
    ) {
      throw new Error(`잘못된 failure group: ${group.spec}`);
    }
    for (const test of group.tests) {
      if (!Number.isInteger(test.line) || test.line < 1 || !test.title) {
        throw new Error(`잘못된 failure test: ${group.spec}`);
      }
    }
  }
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

  async onEnd(
    result: FullResult,
  ): Promise<{ status?: FullResult["status"] }> {
    let gatePassed = false;
    try {
      const checkpoint = parseCheckpoint(
        process.env.MOCKED_E2E_CHECKPOINT,
      );
      const observedRevision =
        process.env.MOCKED_E2E_REVISION ?? process.env.GITHUB_SHA;
      if (!observedRevision || !/^[0-9a-f]{40}$/.test(observedRevision)) {
        throw new Error(
          "MOCKED_E2E_REVISION 또는 GITHUB_SHA에 exact 40자 SHA가 필요합니다.",
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

      const manifestTests = manifest.groups.flatMap((group) =>
        group.tests.map((test) => ({
          key: identityKey(group.spec, test.title),
          determinism: group.determinism,
          fixedIn: group.fixedIn,
        })),
      );
      const manifestKeys = new Set(manifestTests.map(({ key }) => key));
      if (manifestKeys.size !== manifestTests.length) {
        throw new Error("failure manifest에 중복 spec/title identity가 있습니다.");
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

      const report = {
        schemaVersion: 1,
        checkpoint,
        observedRevision,
        baselineMainRevision: manifest.baselineMainRevision,
        baselineRevision: manifest.baselineRevision,
        discoveredTests: identities.length,
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
        globalErrors: this.globalErrors,
        originalStatus: result.status,
      };

      const artifactRoot =
        process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
        path.join(
          os.tmpdir(),
          "kor-travel-map-playwright",
          "admin-frontend",
        );
      const outputPath =
        process.env.MOCKED_E2E_FAILURE_OUTPUT ??
        path.join(artifactRoot, "mocked-failure-report.json");
      await mkdir(path.dirname(outputPath), { recursive: true });
      await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, {
        mode: 0o600,
      });
      await chmod(outputPath, 0o600);

      gatePassed =
        identities.length === manifest.discoveredTests &&
        report.missingExpectedFailures.length === 0 &&
        report.newUnexpectedFailures.length === 0 &&
        report.missingExpectedFlakes.length === 0 &&
        report.newFlakyTests.length === 0 &&
        report.missingManifestTests.length === 0 &&
        report.missingAllowedSkipped.length === 0 &&
        report.newSkippedTests.length === 0 &&
        report.globalErrors === 0;

      const summary = gatePassed ? "일치" : "불일치";
      console.log(
        `[mocked-checkpoint ${checkpoint}] manifest ${summary}: ` +
          `tests=${identities.length}, expected-failures=${expectedFailures.size}, ` +
          `actual-failures=${unexpectedFailures.size}, flakes=${flakyTests.size}`,
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
