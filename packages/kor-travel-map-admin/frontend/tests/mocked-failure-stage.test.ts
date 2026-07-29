import type { TestStep } from "@playwright/test/reporter";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { firstFailureStageMatches } from "../e2e/mocked-failure-reporter";

function step(category: string, title: string): TestStep {
  return { category, title } as TestStep;
}

describe("mocked failure stage provenance", () => {
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

describe("mocked checkpoint isolation", () => {
  const runnerSource = readFileSync(
    new URL("../e2e/run-mocked-checkpoint.mjs", import.meta.url),
    "utf8",
  );
  const configSource = readFileSync(
    new URL("../playwright.config.ts", import.meta.url),
    "utf8",
  );
  const ownedResourcePhase = runnerSource.slice(
    runnerSource.indexOf("let exitCode = 2;"),
  );

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

  it("host public env를 빌드에 상속하지 않고 non-self HTTP/WS를 전역 차단한다", () => {
    expect(runnerSource).toContain(
      'NEXT_PUBLIC_KOR_TRAVEL_MAP_API: "http://127.0.0.1:9"',
    );
    expect(runnerSource).toContain("frontendBuildInputs(isolatedBuildEnvironment)");
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
