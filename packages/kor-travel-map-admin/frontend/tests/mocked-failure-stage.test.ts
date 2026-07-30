import type {
  TestError,
  TestResult,
  TestStep,
} from "@playwright/test/reporter";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  expectedFailureEvidenceMismatches,
  firstFailureStageMatches,
  testInventorySha256,
} from "../e2e/mocked-failure-reporter";

function step(
  category: string,
  title: string,
  error?: TestError,
  steps: TestStep[] = [],
): TestStep {
  return { category, error, steps, title } as TestStep;
}

function result(
  retry: number,
  errors: TestError[],
  steps: TestStep[],
  status: TestResult["status"] = "failed",
): TestResult {
  return { errors, retry, status, steps } as TestResult;
}

describe("mocked failure stage provenance", () => {
  it("동일 개수의 test rename/delete 대체도 inventory hash를 바꾼다", () => {
    const baseline = ["e2e/a.spec.ts::A", "e2e/b.spec.ts::B"];
    const replaced = ["e2e/a.spec.ts::A", "e2e/c.spec.ts::C"];

    expect(replaced).toHaveLength(baseline.length);
    expect(testInventorySha256(replaced)).not.toBe(
      testInventorySha256(baseline),
    );
    expect(testInventorySha256([...baseline].reverse())).toBe(
      testInventorySha256(baseline),
    );
  });

  it("같은 auth locator라도 beforeEach hook 밖이면 auth로 분류하지 않는다", () => {
    const authHook = [
      step("hook", "Before Hooks"),
      step("hook", "beforeEach hook"),
      step("pw:api", "Fill \"admin\" locator('#admin-username')"),
    ];
    const testBody = [authHook.at(-1)!];

    expect(firstFailureStageMatches("beforeEach.auth", authHook)).toBe(true);
    expect(firstFailureStageMatches("interaction", authHook)).toBe(false);
    expect(firstFailureStageMatches("beforeEach.auth", testBody)).toBe(false);
    expect(firstFailureStageMatches("interaction", testBody)).toBe(true);
  });

  it("render와 request assertion step title을 배타적으로 분류한다", () => {
    const render = [
      step(
        "expect",
        "Expect \"toBeVisible\" getByRole('heading', { name: '운영 홈' })",
      ),
    ];
    const request = [step("expect", 'Expect "toMatchObject"')];

    expect(firstFailureStageMatches("render.assertion", render)).toBe(true);
    expect(firstFailureStageMatches("request.assertion", render)).toBe(false);
    expect(firstFailureStageMatches("render.assertion", request)).toBe(false);
    expect(firstFailureStageMatches("request.assertion", request)).toBe(true);
  });

  it("Playwright step이 없는 route mock 예외만 mock.install로 분류한다", () => {
    expect(firstFailureStageMatches("mock.install", [])).toBe(true);
    expect(
      firstFailureStageMatches("mock.install", [
        step("pw:api", "Navigate to /ops/datasets"),
      ]),
    ).toBe(false);
  });
});

describe("mocked failure retry/error provenance", () => {
  const expectedError = { message: "expected render failure" };
  const unrelatedError = { message: "unrelated interaction failure" };

  it("첫 attempt만 예상 원인이어도 이후 retry의 다른 원인을 거부한다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(0, [expectedError], [
          step("expect", 'Expect "toBeVisible"', expectedError),
        ]),
        result(1, [unrelatedError], [
          step("pw:api", "Click unrelated control", unrelatedError),
        ]),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 0,
        retry: 1,
        stageMatched: false,
        statusMatched: true,
      }),
    ]);
  });

  it("첫 error만 예상 원인이어도 이후 soft error의 다른 원인을 거부한다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [expectedError, unrelatedError],
          [
            step("expect", 'Expect "toBeVisible"', expectedError),
            step("expect", 'Expect "toHaveText"', unrelatedError),
          ],
        ),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 1,
        retry: 0,
        stageMatched: true,
      }),
    ]);
  });

  it("top-level wrapper가 예상 원인이어도 중첩 cause의 다른 원인을 거부한다", () => {
    const deepCause = {
      message: "unrelated database regression",
    };
    const expectedCause = {
      cause: deepCause,
      message: "expected render failure in service",
    };
    const expectedWrapper = {
      cause: expectedCause,
      message: "expected render failure",
    };
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [expectedWrapper],
          [
            step(
              "expect",
              'Expect "toBeVisible"',
              expectedWrapper,
            ),
          ],
        ),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 2,
        retry: 0,
        stageMatched: true,
      }),
    ]);
  });

  it("result.errors에 없는 추가 step error도 독립적으로 거부한다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [expectedError],
          [
            step("expect", 'Expect "toBeVisible"', expectedError),
            step("pw:api", "Click unrelated control", unrelatedError),
          ],
        ),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
      }),
    ]);
  });

  it("expected-looking error라도 interrupted attempt는 실패로 인정하지 않는다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          2,
          [expectedError],
          [step("expect", 'Expect "toBeVisible"', expectedError)],
          "interrupted",
        ),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: true,
        errorIndex: 0,
        retry: 2,
        stageMatched: true,
        status: "interrupted",
        statusMatched: false,
      }),
    ]);
  });

  it("첫 실패 뒤 skipped retry도 non-passed attempt로 거부한다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(0, [expectedError], [
          step("expect", 'Expect "toBeVisible"', expectedError),
        ]),
        result(1, [], [], "skipped"),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 0,
        retry: 1,
        stageMatched: false,
        status: "skipped",
        statusMatched: false,
      }),
    ]);
  });

  it("expected failure가 passed-only 결과면 원인 증거 누락으로 거부한다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [], [], "passed")],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: -1,
        retry: 0,
        stageMatched: false,
        status: "passed",
        statusMatched: false,
      }),
    ]);
  });

  it("timedOut beforeEach wrapper는 제외하고 실제 locator 오류를 검증한다", () => {
    const hookTimeout = {
      message:
        '\u001b[31mTest timeout of 1200ms exceeded while running "beforeEach" hook.\u001b[39m',
    };
    const locatorTimeout = {
      message:
        "locator.fill: Test timeout of 1200ms exceeded. waiting for locator('#admin-username')",
    };
    const hookPath = step(
      "hook",
      "Before Hooks",
      hookTimeout,
      [
        step("hook", "beforeEach hook", hookTimeout, [
          step(
            "pw:api",
            "Fill <redacted> locator('#admin-username')",
            locatorTimeout,
          ),
        ]),
      ],
    );

    expect(
      expectedFailureEvidenceMismatches(
        [result(0, [hookTimeout, locatorTimeout], [hookPath], "timedOut")],
        "#admin-username",
        "beforeEach.auth",
      ),
    ).toEqual([]);
  });

  it("caught locator 오류 뒤 독립 timeout은 hook wrapper로 숨기지 않는다", () => {
    const hookTimeout = {
      message:
        'Test timeout of 1200ms exceeded while running "beforeEach" hook.',
    };
    const caughtLocatorTimeout = {
      message:
        "locator.fill: Timeout 100ms exceeded. waiting for locator('#admin-username')",
    };
    const hookPath = step(
      "hook",
      "Before Hooks",
      hookTimeout,
      [
        step("hook", "beforeEach hook", hookTimeout, [
          step(
            "pw:api",
            "Fill <redacted> locator('#admin-username')",
            caughtLocatorTimeout,
          ),
        ]),
      ],
    );
    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [hookTimeout], [hookPath], "timedOut")],
      "#admin-username",
      "beforeEach.auth",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 0,
        retry: 0,
        stageMatched: false,
        statusMatched: true,
      }),
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
        statusMatched: true,
      }),
    ]);
  });

  it("test body timeout wrapper도 실제 interaction leaf가 보고될 때만 제외한다", () => {
    const bodyTimeout = {
      message: "\u001b[31mTest timeout of 1200ms exceeded.\u001b[39m",
    };
    const clickTimeout = {
      message:
        "locator.click: Test timeout of 1200ms exceeded. waiting for getByRole('button', { name: '요청 생성' })",
    };
    const clickStep = step(
      "pw:api",
      "Click getByRole('button')",
      clickTimeout,
    );

    expect(
      expectedFailureEvidenceMismatches(
        [
          result(
            0,
            [bodyTimeout, clickTimeout],
            [clickStep],
            "timedOut",
          ),
        ],
        "요청 생성",
        "interaction",
      ),
    ).toEqual([]);
  });

  it("beforeEach leaf가 별도 afterEach timeout envelope를 숨기지 않는다", () => {
    const beforeEachTimeout = {
      message:
        'Test timeout of 1200ms exceeded while running "beforeEach" hook.',
    };
    const locatorTimeout = {
      message:
        "locator.fill: Test timeout of 1200ms exceeded. waiting for locator('#admin-username')",
    };
    const afterEachTimeout = {
      message:
        'Test timeout of 1200ms exceeded while running "afterEach" hook.',
    };
    const beforeHooks = step(
      "hook",
      "Before Hooks",
      beforeEachTimeout,
      [
        step("hook", "beforeEach hook", beforeEachTimeout, [
          step(
            "pw:api",
            "Fill <redacted> locator('#admin-username')",
            locatorTimeout,
          ),
        ]),
      ],
    );
    const afterHooks = step(
      "hook",
      "After Hooks",
      afterEachTimeout,
      [step("hook", "afterEach hook", afterEachTimeout)],
    );
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [beforeEachTimeout, locatorTimeout, afterEachTimeout],
          [beforeHooks, afterHooks],
          "timedOut",
        ),
      ],
      "#admin-username",
      "beforeEach.auth",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 2,
        retry: 0,
        stageMatched: false,
        statusMatched: true,
      }),
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 3,
        retry: 0,
        stageMatched: false,
        statusMatched: true,
      }),
    ]);
  });

  it("soft assertion 뒤 독립 body timeout을 같은 attempt leaf로 숨기지 않는다", () => {
    const bodyTimeout = {
      message: "Test timeout of 1200ms exceeded.",
    };
    const softAssertion = {
      message: "expected render failure",
    };
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [bodyTimeout, softAssertion],
          [
            step(
              "expect",
              'Expect "toBeVisible"',
              softAssertion,
            ),
          ],
          "timedOut",
        ),
      ],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 0,
        retry: 0,
        stageMatched: false,
        statusMatched: true,
      }),
    ]);
  });

  it("오류 증거가 없는 failed attempt는 permissive regex로도 인정하지 않는다", () => {
    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [], [])],
      ".*",
      "mock.install",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 0,
        retry: 0,
        stageMatched: true,
        statusMatched: true,
      }),
    ]);
  });

  it("result에 없는 same-message parent는 독립 오류일 수 있어 자체 stage로 거부한다", () => {
    const ambiguousParent = step(
      "test.step",
      "render wrapper",
      expectedError,
      [step("expect", 'Expect "toBeVisible"', expectedError)],
    );

    expect(
      expectedFailureEvidenceMismatches(
        [
          result(0, [expectedError], [ambiguousParent]),
        ],
        "expected render failure",
        "render.assertion",
      ),
    ).toEqual([
      expect.objectContaining({
        causeMatched: true,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
      }),
    ]);
  });

  it("stack이 다른 step-only parent도 자체 stage로 거부한다", () => {
    const childError = {
      message: "expected render failure",
      stack: "at assertion.ts:10:2",
    };
    const parentError = {
      message: "expected render failure",
      stack: "at boxed-step.ts:20:4",
    };
    const nested = step(
      "test.step",
      "render wrapper",
      parentError,
      [step("expect", 'Expect "toBeVisible"', childError)],
    );

    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [childError], [nested])],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: true,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
      }),
    ]);
  });

  it("실패 leaf가 있어도 unrelated parent step 오류를 버리지 않는다", () => {
    const unrelatedParent = {
      message: "unrelated parent regression",
    };
    const nested = step(
      "test.step",
      "render wrapper",
      unrelatedParent,
      [step("expect", 'Expect "toBeVisible"', expectedError)],
    );
    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [expectedError], [nested])],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: false,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
      }),
    ]);
  });

  it("같은 regex를 공유하는 독립 parent result에는 leaf stage를 빌려주지 않는다", () => {
    const childError = {
      message: "expected render failure at assertion",
    };
    const parentError = {
      message: "expected render failure during wrapper cleanup",
    };
    const nested = step(
      "test.step",
      "render wrapper",
      parentError,
      [step("expect", 'Expect "toBeVisible"', childError)],
    );
    const mismatches = expectedFailureEvidenceMismatches(
      [result(0, [childError, parentError], [nested])],
      "expected render failure",
      "render.assertion",
    );

    expect(mismatches).toEqual([
      expect.objectContaining({
        causeMatched: true,
        errorIndex: 1,
        retry: 0,
        stageMatched: false,
      }),
    ]);
  });

  it("redacted mismatch에는 실제 error와 step payload를 남기지 않는다", () => {
    const sensitiveValue = "real-sensitive-input";
    const mismatches = expectedFailureEvidenceMismatches(
      [
        result(
          0,
          [{ message: sensitiveValue }],
          [
            step(
              "pw:api",
              `Fill "${sensitiveValue}" locator('#credential-field')`,
              { message: sensitiveValue },
            ),
          ],
        ),
      ],
      "allowed manifest cause",
      "beforeEach.auth",
    );

    expect(JSON.stringify(mismatches)).not.toContain(sensitiveValue);
    expect(mismatches).toEqual([
      expect.objectContaining({
        errorIndex: 0,
        failureStepPath: [
          expect.objectContaining({
            category: "pw:api",
          }),
        ],
        retry: 0,
      }),
    ]);
  });
});

describe("mocked checkpoint isolation", () => {
  const runnerSource = readFileSync(
    new URL("../e2e/run-mocked-checkpoint.mjs", import.meta.url),
    "utf8",
  );
  const reporterSource = readFileSync(
    new URL("../e2e/mocked-failure-reporter.ts", import.meta.url),
    "utf8",
  );
  const configSource = readFileSync(
    new URL("../playwright.config.ts", import.meta.url),
    "utf8",
  );
  const ownedResourcePhase = runnerSource.slice(
    runnerSource.indexOf("let playwrightChild;"),
  );

  it("deterministic failure와 expected flaky의 모든 실패 증거를 함께 검증한다", () => {
    expect(reporterSource).toContain(
      "const expectedFailureFingerprints = new Set([",
    );
    expect(reporterSource).toContain("...expectedFailures,");
    expect(reporterSource).toContain("...expectedFlakes,");
    expect(reporterSource).toContain(
      ".filter(({ key }) => expectedFailureFingerprints.has(key))",
    );
  });

  it("소유 resource 생성 뒤에는 signal handler를 우회하는 spawnSync를 쓰지 않는다", () => {
    expect(ownedResourcePhase).not.toContain("spawnSync(");
    expect(ownedResourcePhase).toContain(
      "const archiveResult = await runManagedChild(",
    );
    expect(ownedResourcePhase).toContain(
      "const postStatusResult = await runManagedChild(",
    );
  });

  it("self-owned UI와 session artifact를 loopback/private runtime으로 제한한다", () => {
    expect(runnerSource).toContain('"HOSTNAME=0.0.0.0"');
    expect(runnerSource).toContain('"network",\n      "create",\n      "--internal"');
    expect(runnerSource).not.toContain('"--network",\n      "host"');
    expect(runnerSource).not.toContain('"--publish"');
    expect(runnerSource).toContain(
      'server.listen(basePort, "127.0.0.1"',
    );
    expect(runnerSource).toContain(
      "await startFrontendProxy(frontendContainerIp)",
    );
    expect(runnerSource).toContain("E2E_STORAGE_STATE: storageStatePath");
    expect(runnerSource).toContain(
      "PLAYWRIGHT_ARTIFACT_ROOT: playwrightArtifactRoot",
    );
    expect(runnerSource).toContain(
      "const diagnostic = await frontendReadinessDiagnostic()",
    );
    expect(runnerSource).toContain(
      '["logs", "--tail", "40", ownedContainerId]',
    );
  });

  it("network create 응답 전 signal도 이름과 ownership label로 정리한다", () => {
    const createAttempt = runnerSource.indexOf("networkCreateAttempted = true");
    const createSpawn = runnerSource.indexOf(
      'const networkResult = await runManagedChild(',
    );
    const cleanupNetwork = runnerSource.slice(
      runnerSource.indexOf("async function cleanupOwnedNetwork()"),
      runnerSource.indexOf("function closeDenyProxy()"),
    );

    expect(createAttempt).toBeGreaterThan(0);
    expect(createAttempt).toBeLessThan(createSpawn);
    expect(cleanupNetwork).toContain("if (!networkCreateAttempted) return");
    expect(cleanupNetwork).toContain('"network",\n    "inspect"');
    expect(cleanupNetwork).toContain(
      "io.kortravelmap.mocked-e2e-owned",
    );
    expect(cleanupNetwork).toContain(
      "ownedNetworkId !== undefined && observedId !== ownedNetworkId",
    );
    expect(cleanupNetwork).toContain(
      'await runCleanupCommand(["network", "rm", ownedNetworkName])',
    );
  });

  it("cleanup 명령 exit보다 exact resource 부재를 종료 판정으로 사용한다", () => {
    const cleanupPhase = runnerSource.slice(
      runnerSource.indexOf("async function waitForResourceAbsence("),
      runnerSource.indexOf("function closeDenyProxy()"),
    );

    expect(cleanupPhase).toContain("await waitForResourceAbsence(listArgs)");
    expect(cleanupPhase).not.toContain("removed.status");
    expect(cleanupPhase).toContain("cleanup_container_remaining");
    expect(cleanupPhase).toContain("cleanup_network_remaining");
    expect(cleanupPhase).toContain("cleanup_image_remaining");
    expect(runnerSource).toContain("cleanup_filesystem_failed");
  });

  it("host public env를 빌드에 상속하지 않고 non-self HTTP/WS를 전역 차단한다", () => {
    expect(runnerSource).toContain(
      'NEXT_PUBLIC_KOR_TRAVEL_MAP_API: "http://127.0.0.1:9"',
    );
    expect(runnerSource).toContain("frontendBuildInputs(isolatedBuildEnvironment)");
    expect(runnerSource).toContain("...isolatedBuildEnvironment");
    expect(runnerSource).toContain("const denyProxyUrl = await startDenyProxy()");
    expect(runnerSource).toContain("if (deniedNetworkAttempts !== 0)");
    expect(runnerSource).not.toContain("...process.env");
    expect(runnerSource).not.toContain(
      "PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK",
    );
    expect(runnerSource).toContain(
      "E2E_BASE_URL: parsedBaseUrl.origin",
    );
    expect(runnerSource).toContain("E2E_ADMIN_USERNAME: adminUsername");
    expect(runnerSource).toContain("E2E_ADMIN_PASSWORD: adminPassword");
    expect(configSource).toContain("proxy: mockedProxy()");
    expect(configSource).toContain(
      "bypass: `<-loopback>,${allowedUrl.host}`",
    );
  });
});
