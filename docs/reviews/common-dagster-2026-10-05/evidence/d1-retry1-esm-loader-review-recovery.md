# D1 retry1 실제 실패와 Playwright ESM loader 경계 독립 진단

판정: **실제 D1 FAIL — test collection의 CJS/ESM 계약 불일치**. 보존된 실패 container와 전체 로그, 설치된 package·Playwright loader 소스를 읽기 전용으로 확인했다. 운영 로그인·브라우저 assertion·D2 실패로 확대하지 않으며 Common의 공개 ESM API 결함으로 판정하지 않는다.

## 실제 관찰

- 전체 stdout: 673 bytes, 14줄, root 소유 0600. SHA256 `baac47875ecab4cabacaa5dec18a550dfff092af31c9f05b034eebff646419bb`.
- 첫 오류: `Package subpath './navigation' is not defined by "exports"` — Common UI package.
- 호출 경계: `e2e/live/auth.setup.ts:4:1`.
- container ID: `0055b960fd1c0b92bf0fa26ca5084c915ec1bd3833273cd4c3d67c191598b30d`.
- image ID: `sha256:60b8e10a0b0790d22024fcaf653a0a279d09f4595064f284097f6d18a6eb41ff`.
- 실제 source label: Map `1a3c4673790f51daa1a2f5ccf803d4e31673bad6`.
- 실제 상태 exited / exit code 1 / running false / OOM false. 시작 `2026-10-05T20:03:42.697402169Z`, 종료 `2026-10-05T20:03:44.110732524Z`.
- image 내부 Playwright CLI를 사용했고 evidence 전용 mount만 있다. D1 여섯 환경 이름 및 worker/artifact 설정 두 개를 확인했으며 다른 E2E 환경 이름은 없었다. 환경 값은 출력하지 않았다.
- 오류는 약 1.4초 안에 발생했다. 로그에는 timeout, missing browser, MODULE_NOT_FOUND, connection refused, assertion 실패 신호가 없었다. 이전 host dependency 부재와 이번 package export 조건 오류를 구분한다.

## 설치된 계약

실제 정지 container에서 `docker cp <container>:<known-file> -`의 tar stream을 제한 크기로 읽었다. 설치·실행·파일 수정은 하지 않았다.

| 실제 파일 | SHA256 |
| --- | --- |
| Common UI package.json | 7134485d261d9f94849c56b26f9f80ca1442a9f87d53f916b2b175bf971a148b |
| frontend package.json | 493836767291ac8c77515eb3820aa3a55068b39144e7ad0fca9489c408733cff |
| Playwright lib/common/index.js | 3d90db5e5823c18827bce6bb5e05531511d6e0a31efe8c0188eeb07900539cfe |
| Playwright lib/util.js | f7734786062157d60ed0388f1f9fcf3507d811327fb3b287576dfdfd9670f083 |
| frontend src/lib/auth.ts | 4aaab8148064770058ccf9ba9914729b0681575886af7362916ea380ca39a30e |
| e2e/live/auth.setup.ts | 9c98960776288f5f644f6f9731f926d83b5a84a9bde3c1f471bd6aba0b3eb6d3 |
| e2e/auth-session.ts | fd86394f7a9b1be42aa7cdf2c01732adbf501dfe70f16e1fde1fea011c254086 |

Common UI는 dev.6, type module이며 navigation export가 `types`와 `import`만 제공한다. frontend package에는 type이 없다. auth.ts가 Common navigation을 import하고 auth.setup이 auth-session을 가져온다.

실제 Playwright `requireOrImport`는 `fileIsModule`이 true이면 dynamic import, false이면 require(file)를 선택한다. `getPackageJsonPath`는 가장 가까운 package.json을 상위로 탐색하며 `folderIsModule`이 그 package의 type===module을 검사한다. 실제 image의 e2e/e2e-live/src/src-lib에는 더 가까운 package.json이 없었다. 따라서 현재 TS setup과 auth.ts는 CJS 경로로 해석되고 import-only export와 충돌한다.

config, auth setup, auth-session, auth lib, auth-state 및 선택된 네 spec에서 require 호출·__dirname·__filename·module.exports·exports 대입이 있는지 정적으로 확인했으며 발견하지 않았다. 이 검사는 모든 transitive dependency의 성공 증명은 아니다.

## 최소 하니스 조정 판단

fresh own C7 container의 COW filesystem에서 frontend/package.json의 type만 module로 설정하고 같은 네 spec/config를 실행하는 제안은 실제 설치된 Playwright loader 분기를 ESM으로 전환하는 최소 조정으로 타당하다. Common navigation/auth를 stub하거나 검증 정책을 비활성화하는 변경이 아니다. 현재 근거만으로 frozen 제품 image/source archive를 수정하거나 재빌드할 필요가 있다고 판단하지 않는다.

별도 실행 receipt는 원본 package hash, 변경 후 package hash, type 외 모든 key/value 동일, 나머지 source bytes 불변, 실제 image/source label과 새 container/evidence identity를 기록해야 한다. 기존 실패 container·전체 로그·실패 receipt는 유지해야 한다. 실제 새 D1/D2 성공 여부는 새 실행 후 검증해야 한다.

## 수행 경계

직접 수행: read-only SSH의 파일 stat/hash·Docker inspect·정지 container의 알려진 파일 tar-stream 읽기, 실제 loader 소스 정적 검토.

**NOT_RUN:** 새 container 생성, COW package 수정, Playwright 재실행, 로그인, browser assertion, D2, 운영 서비스·DB 변경. 마지막 문서 검토는 이 구체적 D1 실패 진단을 우선하면서 중단했다. 현재 제품 FULL113 판정과 기존 재구축/UI/native 증거를 이번 실패와 합산하거나 소급 수정하지 않았다.
