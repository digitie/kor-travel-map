import { defineConfig, devices } from "@playwright/test";

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
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
