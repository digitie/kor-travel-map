import { afterEach, describe, expect, it, vi } from "vitest";

const ENV_NAMES = [
  "E2E_BASE_URL",
  "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256",
  "E2E_C7_EXPECTED_UI_ORIGIN_SHA256",
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

    await expect(loadConfig()).rejects.toThrow("로컬 격리 대상만 허용");
  });

  it("격리 evidence opt-in은 exact 1만 허용한다", async () => {
    process.env.E2E_BASE_URL = "http://127.0.0.1:18705";
    process.env.E2E_ISOLATED_LIVE_EVIDENCE = "true";

    await expect(loadConfig()).rejects.toThrow(
      "E2E_ISOLATED_LIVE_EVIDENCE=1만 허용",
    );
  });
});
