import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const artifactRoot =
  process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
  path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend");

/**
 * Playwright e2e — kor-travel-map debug UI frontend (#117).
 *
 * 실행 모델 (사용자 지시): **debug UI는 WSL에서 기동, Playwright는 Windows에서 실행**.
 *   - WSL: backend `uvicorn kortravelmap.api.app:app --port 12701`
 *           + frontend `npm run dev` (next dev :12705).
 *   - Windows: `npm run e2e` (본 config). 브라우저(Windows)의 localhost는 WSL2
 *           localhost-forwarding으로 WSL :12705/:12701에 도달한다.
 *
 * 서버는 외부(WSL)에서 떠 있다고 가정하므로 `webServer`를 두지 않는다.
 * baseURL은 `E2E_BASE_URL` env로 override 가능 (기본 http://127.0.0.1:12705 —
 * backend CORS allow-origin과 일치).
 *
 * MOCKED ↔ LIVE 경계 (#503): 본 config(`e2e/**`, `npm run e2e` = `e2e:mocked`)는
 * **mock suite**다. 모든 REST는 `page.route`로 가로채고, 라이브 백엔드에 의존해서는
 * 안 된다. 특히 ops-live WebSocket(`useOpsLiveInvalidation` → `/v1/ops/live`)은
 * 라이브 화면을 mount하는 spec에서 `e2e/ws-isolation.ts`의 `installInertOpsLiveWebSocket`
 * (`addInitScript` no-op 스텁)로 inert로 만들어, 라이브 백엔드 snapshot/update가
 * 타이밍 민감 단언을 흔들지 않게 한다. 실데이터 대상 라이브 시나리오는 `npm run e2e:live`
 * (`playwright.live.config.ts`).
 */
export default defineConfig({
  testDir: "./e2e",
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
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
