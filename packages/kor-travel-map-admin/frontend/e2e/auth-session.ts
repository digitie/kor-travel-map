import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** 대상 UI에 로그인하고 후속 project가 사용할 browser storage state를 저장한다. */
export async function authenticateAdmin(
  page: Page,
  storageState: string,
): Promise<void> {
  const password = process.env.E2E_ADMIN_PASSWORD;
  const username = process.env.E2E_ADMIN_USERNAME ?? "admin";
  fs.mkdirSync(path.dirname(storageState), { recursive: true });

  if (!password) {
    await page.context().storageState({ path: storageState });
    return;
  }

  await page.goto("/login");
  await page.locator("#admin-username").fill(username);
  await page.locator("#admin-password").fill(password);
  await page.getByRole("button", { name: "로그인" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 15_000,
  });
  await expect(page).toHaveURL((url) => !url.pathname.startsWith("/login"));

  // SameSite=Strict cookie는 storageState를 처음 적용한 top-level navigation에서
  // 보류될 수 있다. 테스트 browser state만 Lax로 완화하고 실제 cookie 정책은 유지한다.
  const state = await page.context().storageState();
  for (const cookie of state.cookies) {
    if (cookie.sameSite === "Strict") {
      cookie.sameSite = "Lax";
    }
  }
  fs.writeFileSync(storageState, JSON.stringify(state, null, 2));
}
