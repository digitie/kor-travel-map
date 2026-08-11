import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

import { MOCKED_STORAGE_STATE } from "./e2e/_auth-state";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend");
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";

function mockedProxy() {
  const server = process.env.MOCKED_E2E_DENY_PROXY;
  const allowedOrigin = process.env.MOCKED_E2E_ALLOWED_ORIGIN;
  if (!server && !allowedOrigin) return undefined;
  if (!server || !allowedOrigin) {
    throw new Error("mocked network isolation env가 불완전합니다.");
  }
  const proxyUrl = new URL(server);
  const allowedUrl = new URL(allowedOrigin);
  if (
    proxyUrl.protocol !== "http:" ||
    proxyUrl.hostname !== "127.0.0.1" ||
    proxyUrl.pathname !== "/" ||
    proxyUrl.search ||
    proxyUrl.hash ||
    allowedUrl.origin !== new URL(baseURL).origin
  ) {
    throw new Error("mocked network isolation origin/proxy가 안전하지 않습니다.");
  }
  return {
    server: proxyUrl.origin,
    // Chromium proxy bypass는 host:port를 지원한다. self-owned frontend의 exact
    // loopback port만 직접 허용하고 다른 local/external HTTP·WS는 deny proxy로 보낸다.
    bypass: `<-loopback>,${allowedUrl.host}`,
  };
}

/**
 * Playwright e2e — kor-travel-map debug UI frontend (#117).
 *
 * 실행 모델: **debug UI는 Linux/WSL에서 기동, Playwright 브라우저는 WSL에서 실행하지 않음**.
 *   - WSL: backend `uvicorn kortravelmap.api.app:app --port 12701`
 *           + frontend `npm run dev` (next dev :12705).
 *   - n150 Linux: `npm run e2e` (본 config, 1순위).
 *   - Windows fallback: n150에서 실행할 수 없을 때만 `npm run e2e`를 실행한다.
 *           브라우저(Windows)의 localhost는 WSL2 localhost-forwarding으로
 *           WSL :12705/:12701에 도달한다.
 *
 * 서버는 외부(WSL)에서 떠 있다고 가정하므로 `webServer`를 두지 않는다.
 * baseURL은 `E2E_BASE_URL` env로 override 가능 (기본 http://127.0.0.1:12705 —
 * backend CORS allow-origin과 일치).
 *
 * MOCKED ↔ LIVE 경계 (#503): 본 config(`e2e/**`, `npm run e2e` = `e2e:mocked`)는
 * **mock suite**다. checkpoint runner는 self-owned frontend 외 HTTP/WS를 전역 deny하고,
 * 모든 REST는 `page.route`로 가로채므로 라이브 백엔드에 의존해서는 안 된다.
 * 특히 ops-live WebSocket(`useOpsLiveInvalidation` → `/v1/ops/live`)은
 * 라이브 화면을 mount하는 spec에서 `e2e/ws-isolation.ts`의 `installInertOpsLiveWebSocket`
 * (`addInitScript` no-op 스텁)로 inert로 만들어, 라이브 백엔드 snapshot/update가
 * 타이밍 민감 단언을 흔들지 않게 한다. 실데이터 대상 라이브 시나리오는 `npm run e2e:live`
 * (`playwright.live.config.ts`).
 */
export default defineConfig({
  testDir: "./e2e",
  globalTeardown: "./e2e/global-teardown.ts",
  // `e2e/live/**`는 prod 실데이터 스냅샷(feature id 등)에 의존하는 라이브 전용
  // 시나리오라 기본(mock) suite에서 제외한다. 라이브 실행은 `npm run e2e:live`
  // (playwright.live.config.ts, E2E_BASE_URL=배포 URL) 참조.
  testIgnore: ["**/live/**"],
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
    baseURL,
    proxy: mockedProxy(),
    // 타임스탬프 단언들이 UTC 호스트를 **암묵 전제**한다. 박아 두지 않으면 이
    // suite는 Asia/Seoul 같은 머신에서 재현되지 않는다 — 실측: TZ를 로컬로 두면
    // 57 failed, UTC로 두면 54 failed로 결과가 갈렸다(2026-08-10 최초 실행).
    // 재현 불가한 테스트는 통과해도 근거가 되지 못한다.
    timezoneId: "UTC",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      testIgnore: ["**/live/**", /auth\.setup\.ts/],
      use: {
        ...devices["Desktop Chrome"],
        storageState: MOCKED_STORAGE_STATE,
      },
      dependencies: ["setup"],
    },
  ],
});
