# 수집 검증의 Next 보안·OpenAPI 타입 CI 게이트 복구

## 변경 범위

수집 동시성 PR #1358의 frontend CI를 막은 Next 16.3.8 배포 의존성 취약점을
제거한다. Next와 직접 사용하는 `@next/eslint-plugin-next`를 `16.4.1`로 정확히
고정하고 npm `12.0.1`로 lockfile을 갱신했다. 기존 정본 OpenAPI에 뒤처진 admin
타입 산출물도 기존 생성기로 정합화했다. 화면·수집·API 구현·DB·운영 설정 변경은 없다.

Vercel 공식 권고 세 건의 최초 수정 버전은 모두 16.4.1이다. 자동 audit가
추천한 16.4.3 전체 갱신 대신 이 범위의 최소 수정 버전을 사용했다.

- [GHSA-2464-fhr4-w9xw](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw)
- [GHSA-p3m5-59mp-jv5r](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r)
- [GHSA-673q-mjm6-r5xr](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr)

`sharp`는 기존 정확 핀 0.35.5를 유지한다. 루트의 직접 `@next/env`도
16.4.1로 맞춘다. 최초 Next만 갱신한 검사에서는 CI와 같은 `npm ci --workspaces`가
루트의 옛 env를 설치하지 않아 tree 검사가 실패했다. 같은 버전으로 통합해 이 설치
회귀도 제거한다. Next16.4의 내부 이미지 모듈 분리에 따라 기존 sharp 검사기의
함수 import 경로만 맞췄다. SVG를 실제 WebP로 바꾸고 크기를 확인하는 단언은 유지한다.
옛 재export를 호출한 최초 smoke의 TypeError는 성공으로 계산하지 않는다.
`npm --force`와 무관 의존성 버전 갱신은 사용하지 않았다.

## 검증과 남은 게이트

- WSL Node 22.22.2 / npm 12.0.1에서 baseline 배포 audit: critical 1건.
- 수정 후 배포 audit(`--omit=dev`): 취약점 0건, exit 0.
- dev 포함 audit: 기존 moderate 2건/high 6건은 그대로이고 critical만 1→0이다.
  개발 도구 전체 보안 정리는 이번 수집 CI 필수 복구의 범위 밖이다.
- `npm ci --workspaces --include=optional`: PASS. `verify:npm-tree`: problems 0.
- ESLint effective config / full lint 0 warnings / 3개 tsconfig type-check: PASS.
- Next16.4.1 / Sharp0.35.5 실제 SVG→WebP·2×2 크기 smoke: PASS.
- admin 단위 47파일/395건 PASS, map-marker-react 4건 및 타입 검사 PASS.
- admin/user-client `gen:types:check`와 user-client 타입 검사: PASS.
- React Doctor 설정 계약 및 cache 없는 fresh 검사: 313파일/경고0 PASS.
- 최종 타입 생성 후 production build: PASS. Next config·compile·타입·정적 페이지 생성 완료.
- `e2e:list`: 기본 격리 Chromium 시나리오1개 수집만 확인했으며 브라우저 실행은 아니다.

### 기존 타입 drift와 검사 순서

최초 `gen:types:check`는 main `974e2d0`의 기존 drift 때문에 실패했다. 정본
`packages/kor-travel-map-api/openapi.json`과 admin `src/api/types.ts`는 당시 main과
blob이 각각 동일했다. 기존 명세의 `/v1/service/transport/*` 등이 생성물에서 빠져
있었다. 기존 `openapi-typescript` 7.13.0의 공식 `gen:types` 명령 결과만 반영했다.
명세·API 구현·생성기 버전은 그대로다.

build 뒤 실행한 최초 React Doctor는 prebuild가 복사한 gitignored
`public/maplibre/maplibre-gl-shared.mjs`에서 보안 경고1건을 냈다. CI의
Doctor→prebuild 순서와 달랐다. 이 clone이 생성한 worker 두 파일만 잠시 분리하고
`REACT_DOCTOR_NO_CACHE=1`로 fresh 입력을 검사해 경고0을 확인한 뒤 파일을 복원했다.
설정·예외 목록·제품 코드를 바꾸지 않았다. 최초 경고와 교차 파일시스템 이동을
잘못 가정한 검사 준비 실패는 PASS에 포함하지 않는다.

최종 CI·리뷰 수용은 다음 단계다.

두 독립 리뷰와 정확 HEAD CI는 미완이다. 운영 배포·브라우저 E2E는 수행하지 않았다.

원본 dirty worktree와 #1358 수집 구현 파일은 변경하지 않았다. 모든 개발 명령과
편집은 독립 Linux clone에서 수행한다. 로컬 버전·audit 확인은 운영 취약점 악용
가능성 전체나 실제 운영 배포 완료를 증명하지 않는다.
