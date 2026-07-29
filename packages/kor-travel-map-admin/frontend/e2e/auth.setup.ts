import { test as setup } from "@playwright/test";

import { MOCKED_STORAGE_STATE } from "./_auth-state";
import { authenticateAdmin } from "./auth-session";

setup("authenticate admin (mocked)", async ({ page }) => {
  await page.route("**/api/proxy/**", (route) => {
    const request = route.request();
    throw new Error(
      `mocked auth setup에서 REST 호출 금지: ${request.method()} ${
        new URL(request.url()).pathname
      }`,
    );
  });
  await authenticateAdmin(page, MOCKED_STORAGE_STATE);
});
