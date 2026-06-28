import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

import { STORAGE_STATE } from "./e2e/live/_auth-state";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend-live");

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";

/**
 * prod-target 가드 (#501): live config은 baseURL을 `E2E_BASE_URL`로 자유롭게
 * override할 수 있어, 실수로 prod(map.<domain>) 같은 비-로컬 호스트를 가리킨 채
 * 10,000+ admin UI/API 시나리오 카탈로그와 실제 write flow를 돌릴 위험이 있다.
 * 비-로컬 대상은 의도 확인을 위해 `E2E_LIVE_ALLOW_PROD=1` 명시 opt-in 없이는
 * config 평가 시점에 throw해 실행을 막는다.
 */
function isLocalHost(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "0.0.0.0" ||
    hostname.endsWith(".localhost")
  );
}

(function assertNotProdUnlessOptedIn() {
  let hostname: string;
  try {
    hostname = new URL(baseURL).hostname;
  } catch {
    throw new Error(
      `[playwright.live] E2E_BASE_URL이 유효한 URL이 아닙니다: ${JSON.stringify(
        baseURL,
      )}`,
    );
  }
  if (!isLocalHost(hostname) && process.env.E2E_LIVE_ALLOW_PROD !== "1") {
    throw new Error(
      `[playwright.live] E2E_BASE_URL host "${hostname}"가 비-로컬(prod 등)입니다. ` +
        `라이브 e2e는 비파괴 시나리오지만 실수 방지를 위해 비-로컬 대상은 명시 opt-in이 ` +
        `필요합니다. 의도한 실행이면 E2E_LIVE_ALLOW_PROD=1을 설정하세요.`,
    );
  }
})();

/**
 * Playwright e2e — **LIVE(비-mock) 시나리오 전용** config (`e2e/live/**`).
 *
 * 기본 config(playwright.config.ts)는 mock suite로 `e2e/live/**`를 testIgnore한다.
 * 본 config는 라이브 배포 대상(prod 등)에 실데이터로 admin UI/API 시나리오를
 * 돌린다. `admin-scenario-catalog.ts`는 10,000+ 논리 케이스를 생성하고,
 * write spec은 생성/승인/폐기처럼 되돌릴 수 있는 실제 mutation을 포함한다.
 * 백업/restore처럼 blast radius가 큰 실행은 별도 `E2E_BACKUP_RESTORE_EXECUTE*`
 * opt-in으로 제한한다. 데이터/뷰는 `e2e/live/_fixtures.ts`(prod 스냅샷)에서 온다 —
 * fixtures는 배포의 실 API에서 재생성 가능(원본 스크립트는 PR 설명 참조).
 *
 * 실행(로컬 기본 — http://127.0.0.1:12705):
 *   npm run e2e:live
 *
 * worker 수는 `E2E_LIVE_WORKERS`(기본 4)로 조정한다. 비-로컬(prod 등) 대상은 실수
 * 방지를 위해 `E2E_LIVE_ALLOW_PROD=1` 명시 opt-in이 필요하다(아래 가드 참고):
 *   E2E_LIVE_ALLOW_PROD=1 E2E_LIVE_WORKERS=4 E2E_ADMIN_PASSWORD=<admin-pw> \
 *     E2E_BASE_URL=https://map.<domain> E2E_DAGSTER_URL=https://map-dagster.<domain> \
 *     npm run e2e:live -- --retries=1
 *
 * #520 인증 게이트: `E2E_ADMIN_PASSWORD`(+ 선택 `E2E_ADMIN_USERNAME`, 기본 admin)를 주면
 * auth.setup이 로그인 세션을 만들어 모든 spec이 인증 상태로 돈다(미설정 시 인증 미적용 대상으로 간주).
 *
 * CI에서는 돌리지 않는다(라이브 배포 + 실데이터 필요 — admin e2e는 CI job 없음).
 */
export default defineConfig({
  testDir: "./e2e/live",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(artifactRoot, "test-results"),
  fullyParallel: true,
  // worker 상한(#501): 캡이 없으면 fullyParallel이 머신 코어 수만큼 worker를 띄워
  // 라이브 백엔드에 과한 동시성을 건다(flaky·부하). 기본 4, `E2E_LIVE_WORKERS`로 조정.
  workers: Number(process.env.E2E_LIVE_WORKERS ?? 4),
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
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // #520 인증 게이트 대응: chromium 전에 로그인 세션을 1회 만들어 STORAGE_STATE에 저장.
    // 세션은 user-agent fingerprint에 묶이므로, 셋업도 chromium과 동일 디바이스(=동일 UA)로
    // 로그인해야 chromium 테스트에서 세션이 유효하다.
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      testIgnore: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"],
    },
  ],
});
