import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(
    os.tmpdir(),
    "kor-travel-map-playwright",
    "admin-frontend-cache-target-streams-live",
  );
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";
const isolatedHttpOrigin =
  process.env.E2E_ISOLATED_LIVE_DOCKER_NETWORK === "1" &&
  new URL(baseURL).protocol === "http:"
    ? new URL(baseURL).origin
    : null;

/**
 * ADR-081 cache-target stream isolated live acceptance.
 *
 * This config is intentionally separate from the broad live suite: the spec
 * performs destructive admin recovery commands against an isolated candidate,
 * so it is opt-in only, one worker, no retries, and no browser artifacts.
 */
export default defineConfig({
  testDir: "./e2e/live",
  testMatch: /cache-target-streams-isolated\.live\.spec\.ts/,
  globalTeardown: "./e2e/live/global-teardown.ts",
  timeout: 6 * 60 * 1000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  outputDir: path.join(artifactRoot, "test-results"),
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    launchOptions:
      isolatedHttpOrigin === null
        ? undefined
        : {
            args: [
              `--unsafely-treat-insecure-origin-as-secure=${isolatedHttpOrigin}`,
            ],
          },
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  projects: [{ name: "chromium" }],
});
