import { test as setup, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { STORAGE_STATE } from "./_auth-state";

/**
 * Live admin 로그인 셋업 (#520 인증 게이트 대응). chromium 프로젝트의 dependency로
 * 가장 먼저 1회 실행되어, 로그인 세션을 STORAGE_STATE에 저장한다.
 *
 * - `E2E_ADMIN_PASSWORD` 설정 시: /login에서 `admin`(또는 `E2E_ADMIN_USERNAME`)으로
 *   로그인하고 세션 쿠키를 저장한다. 공개 도메인(https)에서 로그인 POST가 403
 *   INVALID_ORIGIN이면(= origin fix 미배포/`KOR_TRAVEL_MAP_UI_PUBLIC_ORIGINS` 미설정)
 *   "허용되지 않은 요청입니다" 오류로 /login에 남아 이 셋업이 실패한다.
 * - 미설정 시: 인증이 꺼진 대상(로컬 dev 등)으로 간주하고 빈 storageState만 저장한다.
 */
setup("authenticate admin (live)", async ({ page }) => {
  const password = process.env.E2E_ADMIN_PASSWORD;
  const username = process.env.E2E_ADMIN_USERNAME ?? "admin";
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });

  if (!password) {
    // E2E_ADMIN_PASSWORD 미설정 → 인증 미적용 대상으로 보고 빈 상태만 저장.
    await page.context().storageState({ path: STORAGE_STATE });
    return;
  }

  await page.goto("/login");
  await page.locator("#admin-username").fill(username);
  await page.locator("#admin-password").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();

  // 성공 시 next(또는 /)로 이동 — /login을 벗어나야 한다. 실패 시(403/401) /login에
  // 남으므로 명확한 오류로 끝난다.
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 15_000,
  });
  await expect(page).toHaveURL((url) => !url.pathname.startsWith("/login"));

  // SameSite=Strict 세션 쿠키는 storageState의 최초 top-level 내비게이션(same-site referrer
  // 없음)에서 Chromium이 보류해 /login으로 리다이렉트된다. 테스트 브라우저 jar에서만 Lax로
  // 완화해 인증 상태가 유지되게 한다(실제 prod 쿠키 정책은 불변 — 저장 파일의 sameSite만 조정).
  const state = await page.context().storageState();
  for (const cookie of state.cookies) {
    if (cookie.sameSite === "Strict") {
      cookie.sameSite = "Lax";
    }
  }
  fs.writeFileSync(STORAGE_STATE, JSON.stringify(state, null, 2));
});
