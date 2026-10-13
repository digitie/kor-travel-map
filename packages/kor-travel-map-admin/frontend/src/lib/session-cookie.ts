/**
 * 세션 쿠키 상수 — **의존성 없는 모듈**로 둔다.
 *
 * Playwright e2e 헬퍼(`e2e/auth-session.ts` 등)가 이 이름을 공유한다. e2e는
 * Playwright가 CommonJS로 변환해 `require()`로 읽는데, `src/lib/auth.ts`는 ESM 전용
 * 패키지(`@kor-travel/ui`, `exports`에 `import` 조건만 있음)를 import하므로 e2e가
 * auth.ts를 import하면 모든 spec이 로드 단계에서 죽는다(2026-10-06 acde3726 이후
 * live·mocked e2e 전체가 그랬다). 그래서 e2e가 필요한 값은 여기서만 가져가고,
 * 이 파일에는 import를 두지 않는다. 회귀는 CI의 `e2e:list` 단계가 잡는다.
 */
export const SESSION_COOKIE_NAME = "ktm_admin_session";
