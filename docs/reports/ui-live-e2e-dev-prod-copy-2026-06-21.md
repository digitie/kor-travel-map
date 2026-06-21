# 사용자/admin UI live e2e — dev 평가 및 prod 복사/검증

## 범위

- dev worktree: `F:\dev\kor-travel-map-codex`
- prod 복사 대상 worktree: `F:\dev\kor-travel-map`
- live dev stack:
  - API: `http://127.0.0.1:12701`
  - Dagster: `http://127.0.0.1:12702`
  - admin/user UI: `http://127.0.0.1:12705`
- Playwright는 저장소 정책대로 Windows 호스트에서 실행했다. 서버는 WSL에서 기동했다.

## 조정 사항

- `scripts/run-admin-stack.sh`
  - `.venv/bin/dagster-webserver` / `dagster-daemon`의 shebang이 옛 경로를 가리키면
    현재 venv Python entrypoint로 fallback 하게 했다.
  - Next 16 dev server는 Turbopack panic(`Failed to write app endpoint /etl/page`)을 피하기 위해
    e2e 스택에서 `next dev --webpack`으로 기동한다.
- `playwright.config.ts`
  - Playwright `test-results`/HTML report를 repo 내부가 아닌 OS temp
    `kor-travel-map-playwright/admin-frontend` 아래로 보낸다. repo 내부 산출물이 Next watcher를
    흔드는 문제를 피한다.
- e2e route-mock 하네스
  - `admin-ops`, `offline-uploads-edge`, `poi-cache-targets-edge` catch-all mock에서
    `/_next/` 정적 자산과 `favicon.ico`는 실제 frontend로 passthrough 한다.
  - `home-nav`의 전 route deep-link 검증은 이미 별도 테스트에서 href를 전수 확인하므로,
    click loop 대신 direct deep-link 진입으로 검증한다.
  - `feature-update-request-detail-actions`의 running→done 폴링 mock은 초기 running UI 단언 전까지
    전환을 gate로 막아 race를 제거했다.

## dev live 검증

- `scripts/run-admin-stack.sh` → API, web, Dagster 모두 ready.
- unmocked live spec:
  - `home.spec.ts`
  - `features.spec.ts`
  - `features-new.spec.ts`
  - `curated-features.spec.ts`
  - `dagster.spec.ts`
  - `etl.spec.ts`
  - 결과: **19 passed**
- 전체 admin e2e:
  - 명령: `npx playwright test --workers=1 --reporter=list`
  - 결과: **209 passed**
- 추가 검증:
  - `npm run type-check:e2e` → passed
  - `bash -n scripts/run-admin-stack.sh` → passed
  - `git diff --check` → passed

## prod 복사 계획

dev 검증이 끝났으므로 다음 파일과 `.env` 계열 설정을 prod worktree로 복사했다.

- 코드/테스트/스크립트:
  - `src/kortravelmap/geocoding.py`
  - `tests/unit/test_geocoding.py`
  - `packages/kor-travel-map-admin/frontend/playwright.config.ts`
  - `packages/kor-travel-map-admin/frontend/e2e/*.spec.ts` 중 이번 수정 5개
  - `scripts/run-admin-stack.sh`
- 문서:
  - `docs/architecture/address-geocoding.md`
  - `docs/reports/prod-api-live-contract-check-2026-06-21.md`
  - `docs/reports/ui-live-e2e-dev-prod-copy-2026-06-21.md`
  - `docs/journal.md`
  - `docs/resume.md`
- 설정:
  - `.env`
  - `packages/krtour-map-debug-ui/.env` (존재 시)

복사 전 prod의 기존 `.env` 파일은 timestamp backup을 남긴 뒤 덮어쓴다.

## prod 복사 및 검증 결과

- prod worktree는 `F:\dev\kor-travel-map`이며, git branch는 `main`이다.
- 기존 `.env` 백업:
  - `.env.backup-20260621-115048`
  - `packages/krtour-map-debug-ui/.env.backup-20260621-115048`
- 최종 설정 재확인 과정에서 prod 루트 `.env`를 dev 기준으로 다시 덮어썼고, 덮어쓰기 전
  추가 백업을 남겼다:
  - `.env.backup-20260621-122939`
  - `packages/krtour-map-debug-ui/.env.backup-20260621-122939`
- dev `.env`와 prod `.env`는 복사 후 byte-for-byte 일치 확인했다.
- prod `.venv`는 dependency가 없는 placeholder 상태여서 `uv venv --clear` 후
  main/API/Dagster editable 기본 의존성을 설치했다. provider git extra는 GitHub 인증이 필요해
  설치하지 않았고, UI live e2e에 필요한 API/Dagster import와 fixture preview는 정상 동작했다.
- prod `node_modules`는 `@tailwindcss/postcss`가 누락되어 `npm install`로 lockfile 기준 복구했다.
  `npm install`은 `ini@7.0.0` engine 경고와 npm audit 취약점 보고를 냈지만 install은 완료됐다.
- prod stack:
  - API: ready
  - web: ready
  - Dagster webserver/daemon: ready
- prod 대상 Playwright는 Windows 실행 조건 때문에 codex worktree의 runner를 사용했다. e2e spec 파일은
  prod로 복사된 파일과 동일 내용이다.
- prod unmocked live spec 6개/19 tests → **19 passed**
- prod 전체 admin e2e → **209 passed**
- 최종 `.env` 재복사 후 prod stack을 재기동했고, 재기동된 prod stack 기준으로 전체 admin e2e를
  다시 실행해 **209 passed**를 확인했다.
