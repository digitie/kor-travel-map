import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend-live");

/**
 * Playwright e2e — **LIVE(비-mock) 시나리오 전용** config (`e2e/live/**`).
 *
 * 기본 config(playwright.config.ts)는 mock suite로 `e2e/live/**`를 testIgnore한다.
 * 본 config는 라이브 배포 대상(prod 등)에 실데이터로 1,700+ 비파괴 read-only
 * 시나리오를 돌린다. 데이터/뷰는 `e2e/live/_fixtures.ts`(prod 스냅샷)에서 온다 —
 * fixtures는 배포의 실 API에서 재생성 가능(원본 스크립트는 PR 설명 참조).
 *
 * 실행:
 *   E2E_BASE_URL=https://map.<domain> E2E_DAGSTER_URL=https://map-dagster.<domain> \
 *     npm run e2e:live -- --workers=4 --retries=1
 *
 * CI에서는 돌리지 않는다(라이브 배포 + 실데이터 필요 — admin e2e는 CI job 없음).
 */
export default defineConfig({
  testDir: "./e2e/live",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(artifactRoot, "test-results"),
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    [
      "html",
      {
        open: "never",
        outputFolder: path.join(artifactRoot, "report"),
      },
    ],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
