import os from "node:os";
import path from "node:path";

/**
 * Live admin 인증 storageState 파일 경로. `auth.setup.ts`가 여기에 로그인 세션을
 * 저장하고, `playwright.live.config.ts`의 chromium 프로젝트가 이를 사용한다.
 * repo 밖(tmp)에 두어 커밋되지 않는다. `E2E_STORAGE_STATE`로 override 가능.
 */
export const STORAGE_STATE =
  process.env.E2E_STORAGE_STATE ??
  path.join(
    process.env.PLAYWRIGHT_ARTIFACT_ROOT ??
      path.join(os.tmpdir(), "kor-travel-map-playwright", "admin-frontend-live"),
    "live-admin-state.json",
  );
