# ADR-124 — 프론트 workspace는 정확한 Node 26.13.1(최신 LTS)과 npm 12.0.1로 고정한다

- 상태: accepted(소유자 결정 2026-11-17). Common T-416의 Map 쪽 결정 기록이다.
- 범위: 루트 npm workspace(관리자 frontend·`map-marker-react`·user client), CI의 Node 선택, frontend·live e2e 실행 이미지. Python·DB·REST 변경 없음.
- 근거: kor-travel-common [T-416](https://github.com/digitie/kor-travel-common/blob/main/docs/tasks/T-416-map-exact-node-npm-pin-decision.md), Common ADR-018(정확 Node/npm 선택)·ADR-019(guard가 호출자의 common ref에서 정책·도구 축을 읽는다), Common 공통화 계획 2026-11-17 §4.1·K-78.

## 맥락

Map 루트와 관리자 frontend의 `engines.node`는 범위(`^22.22.2 || ^24.15.0 || >=26.0.0`)였고 `.nvmrc`가 없었다. CI는 Node 22.23.1을 따로 적었다. 2026-11-17 재vendor PR(#1504)이 common guard 호출 SHA를 올리자 Common ADR-018의 정확 도구 규칙(루트 `.nvmrc`, 정확 `engines`)에 걸려 `55a921b`로 되돌렸다. Common은 정확 핀 채택 여부를 소유자에게 물었다(T-416, 질의 당시 값 22.23.1).

소유자 답(2026-11-17): "Map의 Node 버전 고정 (T-416): .nvmrc와 engines를 22.23.1로 고정할지입니다 … 이것들은 추천안 대로 node는 최신버전으로".

## 결정

1. **채택한다.** 정확 Node의 정본은 루트 `.nvmrc` 한 줄이고, 루트·관리자 frontend `engines.node`, CI `node-version`, Node Docker 이미지 tag가 같은 값이다.
2. **값은 Node 26.13.1이다.** '최신 버전'을 nodejs.org 공식 릴리스 색인(`https://nodejs.org/dist/index.json`, 2026-11-17 조회)에서 가장 새 LTS 줄의 최신 patch로 읽었다. 26(Lithium)이 가장 새 LTS 줄이고 그 최신 patch는 26.13.1(2026-11-10, 보안 릴리스)이다. 색인의 가장 새 항목 `v27.0.0-alpha.0.1.1`(2026-11-16)은 alpha라 운영 핀 대상이 아니다.
3. **npm은 12.0.1 그대로다.** `packageManager`·`engines.npm`·모든 `npx --yes npm@12.0.1` 호출이 이미 Common 공통 축(12.0.1)과 같다. npm 12.0.1의 `engines.node`(`^22.22.2 || ^24.15.0 || >=26.0.0`)는 Node 26을 받는다. Node 26.13.1 동봉 npm(11.20.0)으로 내리면 공통 축과 어긋나고 lock을 다시 쓸 이유가 생긴다.
4. **이미지.** frontend 이미지는 `node:26.13.1-bookworm-slim`을 digest로 고정한다(배포판 bookworm 유지). live e2e 실행 이미지(`docker/c7-playwright.Dockerfile`)는 Playwright base의 Node가 major만 고정된 apt 판이라 `.npmrc`의 `engine-strict`와 정확 `engines`에서 설치가 거절된다. 같은 digest의 공식 이미지에서 `node` 바이너리만 `/usr/local/bin`(PATH 앞)으로 복사한다. 브라우저와 Playwright 의존성은 base 그대로다.
5. **guard 호출은 지금 바꾸지 않는다.** Common 공통 축은 아직 22.23.1이다. Map이 새 guard로 옮기면 그 ref의 축이 Map의 값과 같아야 하므로, 축을 26.13.1로 올리는 Common T-029의 병합 커밋으로 옮긴다(Common T-417). 그 전까지 Map은 `55a921b`를 호출한다. 그 판에는 도구 단계가 없고 `check_frontend_dependencies.mjs`가 `engines`를 읽지 않으므로 이 핀이 guard를 깨지 않는다.

## 대안 검토

- **22.23.1로 고정(질의 당시 값)**: 공통 축과 바로 같아 T-417이 T-029를 기다리지 않는다. 소유자가 최신 버전을 골라 기각했다.
- **Node 27 alpha 또는 Current 줄**: 운영 핀으로 쓰지 않는다. 기각.
- **범위 선언 유지(미채택)**: Map이 옛 guard에 묶여 Common main 정책이 바뀌는 날마다 당일 재vendor한다. 기각.

## 결과

- WSL 개발 환경은 `nvm install && nvm use`로 `.nvmrc`를 따른다. Node 26.13.1이 아닌 Node로 `npm ci`하면 `engine-strict`로 거절된다(의도).
- `@types/node`는 22대 그대로다. 타입이 runtime보다 낮아도 빌드는 깨지지 않는다. 올리는 것은 별도 의존성 PR이다.
- 운영 반영은 다음 정상 배포(frontend 이미지 재빌드)와 다음 live e2e 실행 이미지 빌드에서 일어난다. 이 ADR의 PR은 운영 호스트에서 무엇도 바꾸지 않는다.

## 후속

- Common T-029(공통 Node 축 26.13.1) 병합 뒤 Common T-417: guard 호출 SHA·`common-ref`를 그 커밋으로, 남은 도구 규칙 입력(`toolchain-manifests`·`node-dockerfiles`).
- Common T-025 릴리스 날 Map이 옛 guard에 있으면 Common T-419(ui·tokens 재vendor).
