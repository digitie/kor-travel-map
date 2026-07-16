import { test as setup } from "@playwright/test";

import { MOCKED_STORAGE_STATE } from "./_auth-state";
import { authenticateAdmin } from "./auth-session";

setup("authenticate admin (mocked)", async ({ page }) => {
  await authenticateAdmin(page, MOCKED_STORAGE_STATE);
});
