# UI live e2e 재실행

## 범위

- 대상 stack:
  - API: `http://127.0.0.1:12701`
  - admin/user UI: `http://127.0.0.1:12705`
  - Dagster: `http://127.0.0.1:12702`
- Playwright 실행 위치: Windows host
- 전체 suite: 631 tests / 32 files(리베이스 후 최종 기준)

## 1차 실행

- 명령: `npx playwright test --workers=1 --reporter=list`
- 결과: 629 passed / 1 failed
- 실패:
  - `home-density-matrix.spec.ts`
  - `home import job and dedup dense matrix › dedup pending link target: 경복궁`
  - 증상: `page.goto("/")`가 `load` 이벤트를 기다리다 30초 timeout

## 조치

- 작업 항목: `T-UI-E2E-LIVE-20260621`
- 원인 판단:
  - 제품 기능 실패가 아니라 live Next/static asset load 지연에 새 dense matrix helper가 과하게 민감했다.
  - 테스트는 홈 shell과 mocked API 응답을 검증하므로 full `load` 이벤트까지 기다릴 필요가 없다.
- 수정:
  - `home-density-matrix.spec.ts`의 공통 `gotoHome()`에서
    `page.goto("/", { waitUntil: "domcontentloaded" })`를 사용한다.

## 재검증

- `npm run type-check:e2e` → passed
- 실패 케이스 단독:
  - `npx playwright test e2e/home-density-matrix.spec.ts -g "dedup pending link target: 경복궁" --workers=1 --reporter=list`
  - 결과: 1 passed
- 전체 live UI e2e:
  - `npx playwright test --workers=1 --reporter=list`
  - 결과: **630 passed**
  - 실행 시간: 13.3m

## 리베이스 후 최종 재검증

PR 리베이스 후 prod worktree 스택(`:12701/:12705/:12702`)은 보존하고, codex worktree를
별도 포트(`api :12711`, `admin/user UI :12715`, `dagster :12712`)로 기동해 현재 브랜치 기준
전체 suite를 다시 실행했다.

- `npm run type-check:e2e` → passed
- `npx playwright test e2e/home-density-matrix.spec.ts --workers=1 --reporter=line`
  → 422 passed
- `E2E_BASE_URL=http://127.0.0.1:12715 npx playwright test --workers=1 --reporter=dot`
  → **631 passed** (19.5m)
