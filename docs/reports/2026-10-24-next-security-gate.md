# Next 보안 CI 게이트 복구

## 변경 범위

수집 동시성 PR #1358의 frontend CI를 막은 Next 16.3.8 배포 의존성 취약점을
제거한다. Next와 직접 사용하는 `@next/eslint-plugin-next`를 `16.4.1`로 정확히
고정하고 npm `12.0.1`로 lockfile을 갱신했다. 화면·수집·DB·운영 설정 변경은 없다.

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
- 실제 frontend 설치·타입·단위 검사·lint·production build는 진행 중이다.
- 두 독립 리뷰와 정확 HEAD CI는 미완이다. 운영 배포·브라우저 E2E는 수행하지 않았다.

원본 dirty worktree와 #1358 수집 구현 파일은 변경하지 않았다. 모든 개발 명령과
편집은 독립 Linux clone에서 수행한다. 로컬 버전·audit 확인은 운영 취약점 악용
가능성 전체나 실제 운영 배포 완료를 증명하지 않는다.
