# 2026-10-24 npm 보안 갱신과 버전 정합

소유자 요청 범위는 PinVi·Transport·Map·Geo·Weather·Manager의 npm 직접/전이 의존성 갱신과 CI 확인 후 머지다. Python 의존성과 운영 배포는 이번 변경에 포함하지 않는다.

| 공통 항목 | 버전 |
| --- | --- |
| Next.js / 사용하는 Next ESLint 패키지 | 16.4.3 |
| React / React DOM | 19.3.1 |
| TypeScript | 5.9.3 |
| Vitest / Vite | 5.0.5 / 8.3.5 |
| Playwright | 1.64.1 |
| Zod 직접 의존성 | 4.6.7 |
| CI Node / npm | 22.23.1 / 12.0.1 |

호환성에 필요한 차이는 유지한다. `eslint-config-next`는 React ESLint 플러그인의 peer 범위에 맞춰 ESLint 9.39.5를 사용하고, 별도 플러그인 조합을 검증하는 Map은 ESLint 10.13.0을 유지한다. TypeScript 6/7 대신 타입 생성기와 린터가 함께 지원하는 5.9.3을 쓴다. TanStack Table은 현재 사용 API의 8.21.3, react-hook-form은 안정 7.91.0, resolvers는 peer 충돌 없는 5.9.2다. 공개 라이브러리의 peer 범위는 앱의 정확한 핀과 별도로 보존한다.

PinVi 모바일은 Expo SDK 57.0.31과 React Native 0.86.3을 기준으로 SDK 모듈 패치를 정합화했다. NativeWind 4의 Tailwind 3.4.19와 웹의 Tailwind 4.3.3은 서로 다른 컴파일러 계약이다. 웹과 모바일에 같은 Tailwind major를 강제하지 않는다. Expo CLI의 Zod와 URI 디코더, Tailwind 하위 선택자 파서는 별도 보안 패치를 소비한다. PinVi의 React 타입은 SDK 허용 범위의 `@types/react` 19.2.18·`@types/react-dom` 19.2.7을 사용한다. 웹의 React 실행 버전은 19.3.1을 공유한다.

Geo는 다른 소비 앱과 동일한 Common UI dev.6 아티팩트를 사용하며 출처와 SHA256은 `kor-travel-geo-ui/vendor/PROVENANCE.md`에 남긴다. 다른 로컬·Git·vendored 제공자 패키지는 registry 최신 버전으로 치환하지 않는다.

Map은 보안 패치된 `@redocly/openapi-core` 1.34.22가 자체 호환 minimatch를 사용하므로 이전 강제 override와 vendor 보정 스크립트를 제거했다. 실제 OpenAPI 산출물 비교와 npm 트리 검증은 유지한다. Next 16.4의 optimizer 모듈 이동에 맞춰 Sharp ABI 검증의 import만 변경했으며 이미지 변환은 계속 실행한다. Playwright Docker 이미지는 테스트 패키지와 같은 1.64.1과 검증된 manifest digest를 사용한다.

Map의 React Doctor는 기존 CI 계약인 0.9.1로 정확히 고정한다. 0.9.18은 새 진단 44건(복잡도·중복·ref·hydration·생성 파일)을 추가한다. 이번 보안 패치를 위해 소스 규칙을 무력화하거나 넓은 UI 리팩터링을 섞지 않으며, 생성된 MapLibre 배포 파일만 검사에서 제외한다. 새 Doctor 규칙 도입은 별도 작업이다.

## 남은 상류 취약점

PinVi의 Expo 개발 CLI 경로에는 `node-forge`의 [GHSA-86w9-cpqp-85rv](https://github.com/advisories/GHSA-86w9-cpqp-85rv)가 남는다. 2026-10-24 조회 시 최신 1.4.0도 영향 범위이며 수정 릴리스가 없다. Expo의 코드 서명 인증서 처리에 사용된다. 이 항목을 숨기는 audit 제외나 강제 SDK 하향은 하지 않는다. 앱 웹 요청 처리 경로와 CLI 서명 작업을 구분하며, 이 변경을 전체 취약점 0건으로 보고하지 않는다. 수정 릴리스가 나오면 SDK 호환성을 확인해 다시 갱신한다.

## 검증 상태

WSL의 신규 설치·audit·빌드·타입·린트·회귀 테스트를 수행하고 있다. 정확한 최종 결과와 후보 커밋 CI·독립 리뷰·N150 UI 결과는 journal에 기록한다. 수행 중인 검증을 통과로 세지 않는다. 머지는 그 결과를 확인한 뒤 진행한다.
