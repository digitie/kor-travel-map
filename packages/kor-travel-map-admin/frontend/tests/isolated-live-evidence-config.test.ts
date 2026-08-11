import { readFileSync } from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";

const ENV_NAMES = [
  "E2E_BASE_URL",
  "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256",
  "E2E_C7_EXPECTED_UI_ORIGIN_SHA256",
  "E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY",
  "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID",
  "E2E_ISOLATED_LIVE_DOCKER_NETWORK",
  "E2E_ISOLATED_LIVE_EVIDENCE",
] as const;

afterEach(() => {
  for (const name of ENV_NAMES) {
    delete process.env[name];
  }
});

async function loadConfig() {
  vi.resetModules();
  return (await import("../playwright.live.config")).default;
}

async function loadCacheTargetStreamsConfig() {
  vi.resetModules();
  return (await import("../playwright.cache-target-streams.live.config"))
    .default;
}

const loopbackProxySource = readFileSync(
  new URL("../../../../scripts/c7-loopback-ui-proxy.mjs", import.meta.url),
  "utf8",
);

describe("isolated Live evidence config", () => {
  it("loopback 격리 실행은 redacted reporter를 쓰고 raw artifact를 끈다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18705";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "1";

    const config = await loadConfig();

    expect(config.reporter).toEqual([
      ["./e2e/c7-redacted-reporter.ts", { outputFolder: expect.any(String) }],
    ]);
    expect(config.use?.trace).toBe("off");
    expect(config.use?.screenshot).toBe("off");
    expect(config.outputDir).toMatch(
      /^\/tmp\/kor-travel-map-c7-test-results-[0-9]+$/,
    );
  });

  it("격리 evidence 모드는 비로컬 origin을 거부한다", async () => {
    process.env.E2E_BASE_URL = "https://non-local.invalid";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "1";

    await expect(loadConfig()).rejects.toThrow("검증된 격리 대상만 허용");
  });

  it("격리 evidence opt-in은 exact 1만 허용한다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18705";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "true";

    await expect(loadConfig()).rejects.toThrow(
      "E2E_ISOLATED_LIVE_EVIDENCE=1만 허용",
    );
  });

  it("격리 Docker executor는 loopback proxy origin만 허용한다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18706";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "1";
    process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK = "1";

    const config = await loadConfig();

    expect(config.use?.baseURL).toBe("http://127.0.0.1:18706");
    expect(config.use?.trace).toBe("off");
    expect(config.use?.launchOptions).toBeUndefined();
  });

  it("격리 Docker opt-in도 direct candidate HTTP origin은 거부한다", async () => {
    process.env.E2E_BASE_URL = "http://candidate-ui:18705";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "1";
    process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK = "1";

    await expect(loadConfig()).rejects.toThrow("검증된 격리 대상만 허용");
  });

  it("cache-target 격리 config도 insecure-origin secure 우회 옵션을 주지 않는다", async () => {
    process.env.E2E_BASE_URL = "http://candidate-ui:18705";
    process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK = "1";

    const config = await loadCacheTargetStreamsConfig();

    expect(config.use?.baseURL).toBe("http://candidate-ui:18705");
    expect(config.use?.launchOptions).toBeUndefined();
  });

  it("loopback proxy는 transport target과 browser same-origin을 분리한다", () => {
    expect(loopbackProxySource).toContain("host: target.host");
    expect(loopbackProxySource).toContain('"x-forwarded-host": loopbackHost');
    expect(loopbackProxySource).not.toContain('"x-forwarded-host": target.host');
  });

  it("Docker 격리 opt-in은 evidence mode 없이 사용할 수 없다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18706";
    process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK = "1";

    await expect(loadConfig()).rejects.toThrow(
      "E2E_ISOLATED_LIVE_EVIDENCE=1이 필요",
    );
  });

  it("격리 Admin Feature 인증 감사를 run과 phase에 결합한다", async () => {
    const runId = "clone-20260729000000-abcdef123456";
    process.env.E2E_BASE_URL = "http://127.0.0.1:18706";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "1";
    process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK = "1";
    process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID = runId;
    process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY = "1";

    const config = await loadConfig();
    const setup = config.projects?.find((project) => project.name === "setup");

    expect(setup?.use?.extraHTTPHeaders).toEqual({
      "x-request-id": `e2e_live_acceptance::${runId}::auth::recovery`,
    });
  });

  it("Admin Feature run ID는 일반 Live에서 사용할 수 없다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18705";
    process.env.E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID =
      "clone-20260729000000-abcdef123456";

    await expect(loadConfig()).rejects.toThrow("검증된 격리 실행의 run ID");
  });
});
