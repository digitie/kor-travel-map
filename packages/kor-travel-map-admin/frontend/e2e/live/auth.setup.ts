import { test as setup } from "@playwright/test";

import { LIVE_STORAGE_STATE } from "../_auth-state";
import { authenticateAdmin } from "../auth-session";

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
  await authenticateAdmin(page, LIVE_STORAGE_STATE);
});
