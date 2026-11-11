# 2026-11-11 관리자 공통 UI 통합 기록


## 현재 상태 — integration-9-review

검증 source는 e3ea216c128c3e7ef5346b17db6d4ec3fd5272a0이다.
공통 원천2c1182e765bb2bc53e01e0962cf2a73683891e1d의 c9 원장을 사용하고,
지도9a7a348b02d61969b394c681b024d5851eef836b와 Lightning CSS fix.4 bytes를 유지한다.
원천·정확 버전·SHA512는 [출처](../third-party-common.md)와 frontend 원장이 정본이다.

- UI/tokens/core/web/CSS 사용5개 vendor와 lock·중앙 원장을 대조했다. RN은 미사용이다.
  c8과 다른 UI/tokens member는 검사기 하나씩뿐이며 runtime/CSS는 동일하다.
- 명시 npm install exit0 뒤에도 설치된 검사기가 이전 bytes인 사실을 발견했다.
  본인 preflight/D supervisor만 중단하고 전용 checkout의 해당 두 생성 package만 제거했다.
  재설치 뒤 실제 installed checker/vendor byte 일치 gate까지 통과했다.
- n150 c9 전체 unit432/432, reporter/cleanup37/37, lint/type,
  Doctor full blocking warning324files 진단0, guard/canonical, npm tree/NextSharp/CSS 공개 API 통과.
- c8 기본 병렬 unit431통과/1실패 로그는 보존했다. 같은 문제 파일11개가 재통과했고,
  c9 전체는 worker2로 통과했다. 단언·시간 제한·실패/skip 허용은 완화하지 않았다.
- 정식 D 새 production 이미지 빌드와286/286 PASS, flake0/skip0, strict manifest 일치.
  전체 runner는 cleanup·사후 조건을 포함해 classification passed/exit0/issues[]다.
  별도 exact 조회도 소유 container/network/image 잔존0이다. 아래 후보6 exit2는 원시 이력으로 보존한다.
- 부모 소유 중앙 workflow는 보존·커밋 제외한다. exact 재사용 코드2c1182e765bb2bc53e01e0962cf2a73683891e1d와
  최신 main data의 원격 CI는 부모가 확인한다.
- 운영 배포는 독립 리뷰2개·CI·merge·부모 go 뒤 진행한다. 후보는 배포하지 않았다.

## 범위와 결과

Map 전용 ext4 clone의 `agent/codex-common-unification-20261111`에서 작업했다.
기준 commit은 `32668d003ea6a259468e03970bd167359c19ecdb`다.
원본 /mnt/f/dev worktree는 수정하지 않았고 Weather는 담당자에게 인계했다.
공통 VirtualTable과 전용 테스트는 shared common branch에 반영했으며 부모가 전체 common을 통합한다.

모든 admin 표는 common VirtualTable에 연결했다. 로컬 DataTable은 reexport이며
ColumnDef/Row/Cell/SortingState import도 common facade를 사용한다.
큐레이션 목록·미리보기·격리 목록의 native table을 이관했다.
Dialog/AlertDialog/Popover/Tooltip/Tabs/Button/Checkbox/Field 등은 common Radix를 사용한다.
검색 combobox/행정구역 후보 팝업도 common Popover로 위치·해제·포커스를 처리한다.
기존 테마와 variant는 얇은 앱 wrapper/CSS에서 보존한다.

지도 생성/해제/style은 web/core public API로 위임한다. Map의 마커·클러스터·geometry·long press
정책과 worker 배포 계약은 보존한다. common LoginForm은 RHF+Zod+Zustand를 실제 사용하고,
HelpTip도 인스턴스별 Zustand를 사용한다. Pretendard font와 Radix bridge를 실제 CSS로 로드한다.

## 의존성과 CI

현재 산출물은 `integration-9-review` 검증 후보이며 최종 통합 상태는 부모 원장이 정본이다.
[출처와 SHA512](../third-party-common.md), [원장](../../packages/kor-travel-map-admin/frontend/common-artifacts.json)에
부모와 동일한 5개 tgz의 정보를 기록했다. 이전 vendor는 제거했다.
ESLint 10.14.0 / Doctor 0.9.22 / exact 최신 targets를 적용했다.
TypeScript 5.9.3은 최신 major의 openapi-typescript/ts-eslint peer 호환 예외이며,
Node 타입은 runtime 22에 맞춘 22.20.5다. root ajv 8.20.0 직접 개발 의존성은
RHF resolver의 optional peer 8과 ESLint의 nested 6이 분리되도록 해 npm tree 충돌을 해소한다.
강제 설치·legacy peer 옵션·추가 lint/Doctor suppressions는 쓰지 않았다.

CI는 frontend cwd에서 `check:dependencies --source src`를 실행해 AST 기반 중복 Table·Base UI,
exact policy 및 vendor/원장/lock integrity를 확인한다. Doctor는 full/warning gate다.
기존 local Table v8 compiler 예외 검사는 common v9 reexport 경계 검사로 바꿨다.
공식 Playwright 1.65.0 noble 이미지 digest는 4개 runner/build 파일에 동일하게 고정했다.

## candidate5 검증 이력

- install script를 허용한 npm 12.0.1 clean ci 통과(candidate4), candidate5 명시 재설치 통과.
- candidate5 lint/type-check/production build(33 routes)/AST artifact guard 통과.
- Doctor full / blocking warning: 321 files, 진단 0.
- 전체 unit: 421개 중 419 통과, common LoginForm 자동완성 계약 2개 실패.
  change 이벤트 없이 DOM password.value가 채워진 뒤 submit하면 최신 FormData 대신
  RHF 내부 빈 값이 검증되어 fetch가 호출되지 않는다. 기존 회귀 테스트는 유지했고 부모 수정 요청.
- candidate5 Dagster 실행 선택 toggle/DOM 포커스 보존 회귀 통과.
- npm tree, ESLint config, Doctor config, Next/Sharp smoke 통과.
- production audit 취약점 0, dev high gate 통과(최신 lint 체인의 moderate 10건은 강제 하향하지 않음).
- 변경된 frontend 의존성/Playwright 이미지 Python 계약 검사 7개 통과.
- 공통 VirtualTable 전용 테스트 12개 통과(가상 스크롤·정렬·선택·Geo SSE 셀 수명·접근성 포함).
- 공통 font.css 경유 후 production build도 통과. 첫 재빌드는 standalone 복사에서 ENOSPC였으나
  Map 소유 .next/전송 pack만 정리한 뒤 재검증 통과했다. WSL 여유 약 11MB로 추가 대형 작업 제약이 있다.
- OpenAPI 생성 타입 검사와 Playwright 로딩 검사(격리 mock 286개 / live 1143개 / stream live 1개) 통과.
- 격리 n150 mocked e2e와 독립 리뷰 2개는 후속 gate다. 운영 live 쓰기 검증은 실행하지 않았다.

## 추가 공통화 후보

로컬 Button의 loading/disabledReason, ReviewDialogHeading/ReviewErrorAlert/ReviewMapLegend,
단일·복수 검색 combobox의 키보드 상호작용, FormField의 설명/오류 연결을 후보로 제안한다.
Map 도메인 API와 상태는 common으로 이동하지 않는다. 공통 소유 부모의 API 합의 뒤 별도 이관한다.
복잡한 feature/provider 편집기는 기존 검증을 보존하며 개별 RHF+Zod 이관이 남아 있다.

## 배포 계획과 실제 컨텍스트

로컬 비밀 런북을 읽고 gitignore 경로에만 보존했다. n150의 실제 배포 project는
`kor-travel-docker-manager`, 대상 service는 `kor-travel-map-ui`,
현재 container는 `kor-travel-map-ui-latest`다. 이번 변경의 배포 범위는 UI다.
실제 container의 compose working_dir는 `/opt/kor-travel-docker-manager`, config_files label은
`-`(stdin으로 전달된 frozen render)다. 일반 checkout compose를 정본으로 간주할 수 없다.
Manager의 pin/revision 계약과 실제 frozen render에서 UI 단독 교체 경로를 부모가 확정해야 한다.
현재 UI image ID는 `sha256:0ec4e9bf0ec31ecf43926ba00680afa133e5ae2e5d15392b1a7a4741d40eb317`,
revision은 `fd1d770162e8253020a936ec552a4395500f444e`로 확인했다.
현재 container의 Config.Image도 위 sha256 ID 자체다. 운영 컨테이너가 mutable 태그를
직접 참조한다고 가정하지 않는다. 배포 시 Manager가 선언한 image repository에
merge SHA 앞12자 태그를 추가하고, 실제 교체·복구 판단은 resolved image ID와 receipt로 기록한다.
이 읽기 전용 확인에서 compose 경로와 stdin render도 다시 일치했다.


1. 부모 final freeze의 공통/upstream immutable SHA·tgz·원장을 동일하게 다시 설치하고 모든 gate를 통과한다.
2. 독립 리뷰 2개·CI·PR merge 뒤 부모 go를 확인한다. merge exact SHA를 빌드 revision으로 기록한다.
3. n150에 merge SHA의 clean 소스를 준비한다. 기존 .env*·override·런타임 비밀은 보존하며
   node_modules/.next/.venv/.git을 소스 동기화에 섞지 않는다.
4. 부모가 Manager의 배포 lock·현재 pin/receipt·frozen render와 UI 단독 교체 허용 여부를 확인한다.
   로컬 런북의 옛 `ktdctl map --build`나 일반 checkout compose로 우회하지 않는다.
   확정된 render의 `kor-travel-map-ui` build context에서 exact source를 로컬 빌드한다.
   최종 이미지에 exact revision label을 확인하고 이전 image ID를 복구용으로 기록한다.
   이미지 태그는 Manager compose의 실제 image 이름을 확인해 merge SHA 12자로 추가 추적한다.
5. 부모가 확정한 Manager 배포 경로에서 `--no-deps`에 해당하는 UI 단독 재생성을 실행한다.
   전체 `rebuild-pinned`는 DB/API/Dagster까지 범위가 확장될 수 있어 이번 변경만으로 실행하지 않는다.
   DB/RustFS/API/Dagster 수명주기와 migration을 건드리지 않는다.
6. container healthy, revision, frontend 응답 및 기존 API health를 확인한다.
   비밀값 출력 없이 auth hash 존재 여부를 검사하고 로그인 POST의 200/Set-Cookie를 확인한다.
   브라우저에서 로그인·운영 요약·대형 목록 정렬/선택/스크롤·Dialog 포커스·지도 초기화 화면을 확인한다.
7. 실패하면 배포를 중단하고 부모가 승인한 Manager 복구 경로에서 UI를 복구한 뒤 동일 로그인/health를 검증한다.

후보 배포는 실행하지 않았다. common LoginForm과 키 없는 지도 회귀는 후보6에서 해결했다.
최종 산출물 freeze·Docker 정리 gate 재확인·독립 리뷰/CI/merge/부모 go가 남아 있다.


## candidate5 지도 호환성 이력

최신 upstream은 키가 비면 MapLibre를 생성하지 않는다. 기존 Map과 격리 e2e는 빈 배경 위에
도메인 마커/geometry를 렌더링한다. 부모에게 explicit mapStyle public API와 명시 style의
missing-key gate 예외를 요청했다. 앱에서 가짜 키나 자체 Map 생성자로 우회하지 않는다.
n150의 exact commit checkpoint로 영향 범위를 재현 중이다.


## candidate5 격리 브라우저 재현 및 Map 호환 복구

n150 exact bcf2a3745 checkpoint A(286 mock tests)는 첫 Chromium revision1254 누락을
정확 1.65.0 브라우저 설치로 해결한 뒤 실행했다. 실행 중 확인한 실제 회귀:

- CardTitle의 heading 누락, 일반 Alert의 status→alert 변경으로 backups e2e가 실패했다.
  Map wrapper에서 기존 heading level2와 기본 polite/status·destructive assertive/alert를 복구했다.
  관련 회귀 unit2개 통과.
- Enrichment dialog의 accept 클릭이 element outside viewport로 시간 초과했다.
  긴 내용이 viewport 안에서 스크롤하도록 Map DialogContent를 제한하고 넓은 비교 창의
  sm breakpoint 폭을 명시했다. 자동 닫기 버튼 중복도 기존 Map 계약에 맞춰 기본 비표시로 조정했다.
- 키 없는 upstream 지도는 _maplibreMap을 생성하지 않아 features-map-interactions의
  초기화 predicate true 기대가 false로 시간 초과했고 큐레이션 bbox 요청도 0이었다.
  이는 source 분석만이 아니라 브라우저에서 재현됐다. 부모 mapStyle public API 수정이 필요하다.

이 브라우저 실행은 후속 Map wrapper/common 리뷰수정을 포함하지 않아 최종 통과 근거가 아니다.
부모 freshpack/freeze 뒤 exact 최종 SHA로 checkpoint를 다시 실행해야 한다.

후속 Map 호환 복구 소스 기준 lint/type/build33routes/Doctor321files0 재통과.
전체 unit421개 중419통과, 남은 LoginForm2개는 부모 공통 수정/후보 재설치를 기다린다.
구후보 n150 checkpoint는 81개 통과 관측 후 실제 회귀(재시도 포함29실패 항목)를 수집하고
freshpack 재검증을 위해 본인 runner만 SIGTERM 종료했다. 완료 통과 합계가 아니다.
own container/network/image 잔존0 확인. 원시 회귀 요약은 작업 루트 map-c5-e2e-failures.json에 보존.


## 후보6 첫 checkpoint와 후속 수정

exact517071481의 286개 checkpoint는230통과/56실패/flake0으로 완료했다.
로그와 실패 trace/screenshot은 n150 taskroot validation/map의 commit별 경로에 보존했으며
전체 실행 로그도 WSL validation/map/c6-first-n150-checkpoint.log로 복사했다.

- 지도 초기화·geometry·bbox와 기존 Dialog/heading/status 회귀는 실제 브라우저에서 통과했다.
- 도움말의 옛 Base UI data-open 검사를 Radix 공개 data-state=open 검사로 갱신했다.
- 지도와 URL 기반 데이터셋 탭은 수동 활성화를 명시했다. Radix 포커스 자동 활성화가
  지도 탭의 상세 진입 포커스를 다시 가져가거나, 같은 URL history를 두 번 쌓는 것을 막는다.
  데이터셋 선택은 동일 목적지에 History push를 반복하지 않는다.
- Map Alert wrapper의 기존 data-variant 계약을 복구했다.
- 기존 e2e fixture의 transport 제공자 수를 현재 canonical provider2개에 맞추고
  검색은 퇴역한 krex 이름 대신 실제 dataset key를 쓴다. 두 transport dataset의 데이터와 행 수3은 유지한다.
- pipeline fixture에서 누락됐던 기존 공개 GET /v1/ops/pipeline/dagster-summary를
  OpenAPI 타입에 맞게 명시 mock했다. 큐 센서 fail-closed 판정은 기존 overview fixture를 유지한다.
  임의 route fallback이나 실패 예외 허용을 추가하지 않았다.
- 수정 후 unit427/427, lint/type/Doctor0/guard 재통과. exact 후속 commit checkpoint 재검증이 필요하다.

공유 WSL ENOSPC 때문에 일부 검사가 실행되지 못했다. 삭제한 것은 Map 소유 .next와
본인이 만든 validation/map/c6-source-517071481d9d.pack 전송 파일뿐이다.
다른 agent 파일이나 공유 /tmp 경로는 삭제하지 않았다. 공간 확보 뒤 검사 재실행은 통과했다.


## 두 번째 checkpoint와 orphan fixture 정합성

exact7fbfd3cac 전체286개는285통과/1실패/flake0으로 완료했다.
지도·도움말·탭 포커스/History·정책 초안 복원 회귀는 모두 통과했다.
남은1개는 새 summary mock을 빈 목록으로 둬 기존 run-orphan 실패 가시성 기대가 깨진 경우다.
Dagster summary/list/detail fixture에서 같은 OpenAPI형식 ORPHAN_DAGSTER_RUN을 공유하도록 고쳤고
상세 열기는 공통의 현재 접근성 이름을 사용한다. 실패 원인 본문 검사는 그대로 유지한다.
n150의 기존 의존성에서 수정된 e2e 타입·lint·전체 spec로딩이 통과했다.
애플리케이션 runtime source는7fbfd3cac와 동일하다.

WSL공간확보를위해 종료된 Map .next210MB/rootnode_modules906MB/frontendnode_modules23MB를 정리했다.
기존사용자cache·타agent파일·공유/tmp는건드리지않았고 n150의진행검증은보존했다.
이후로컬재설치는시작하지않았다. 현재중앙checker는 --policy 최신생성policy + --canonical 원장으로통과한다.
부모소유신규common-frontend-policy.yml은보존하며본인commit에포함하지않는다.


## 성공 checkpoint와 inventory 정산

exact1ce5a1148에서 브라우저286개가 모두 통과했지만 runner exit는2였다.
회귀 재현용 A 단계는 과거 실패 상태를 기대하고, 기존 manifest는284개/옛 identity hash에 머물러 있었다.
실패·skip 허용 목록은 빈 상태로 유지하면서 관측286개 identity의
SHA256 dc85a2c127f1ddb68fef6ae55dc71a04ddb2005bfeb784c94249aaf535d939a5를 재고정했다.
성공 검증은 D 단계로 실행한다. A 결과를 runner 전체 통과로 보고하지 않는다.

Docker 정리 CLI의1초 제한으로 container 제거 잔존/이미지 확인 오류도 분류됐다.
사후 exact 소유 자원 검사에서 container/network 잔존0을 확인하고,
해당 실행 image tag와 ID가 기록과 일치함을 검증한 뒤 그것만 제거했다.
cleanup 명령의 대기를30초로 늘렸고 소유권·ID 일치·잔존 검사는 유지했다.
이에 따라9d187a61d에서 lint/기존 reporter 단위32개/Doctor322files0이 재통과했다.
정식D 전체286개와 manifest도 통과했지만, 위와 같이 실제 Docker 삭제 지연은 인프라 실패로 보존했다.
애플리케이션 src·의존성·lock·vendor는7fbfd3cac와 동일하다.


## 후보6 소스 검증 및 인계 이력

- 소스 검증 기준:9d187a61d464c55713f91979ed0c5f07eea33d2a.
  앱 runtime source/의존성/lock/vendor는 전체unit427개 통과본7fbfd3cac와 동일하다.
- 정식D:286/286 PASS, flake0, skip0, manifest inventory 일치, Playwright child exit0.
  전체 runner exit2의 유일 사유는 cleanup_container_remaining이다.
  n150 부하 중 Docker가 removing/PID0 상태를 유지한 실제 인프라 지연이었다.
  후행 exact 조회는 container/network/image 잔존0, worker2055942/runner2059958 종료를 확인했다.
- 최신 lint/type/build33routes/Doctor full warning gate 진단0, reporter 단위32개,
  local canonical source·원장 검사 통과. 검사별 raw log는 taskroot validation/map에 보존했다.
- 원시D 로그 c6-final-D-checkpoint.log, 상태 c6-final-D-state.json,
  후행 정리 증거 c6-final-cleanup-postcondition.json, 요약 c6-validation-summary.json.
- 마지막 문서 commit은 이 결과·배포 컨텍스트·재개 위치만 기록한다. 테스트 입력 변경은 없다.
- 부모 소유 신규 .github/workflows/common-frontend-policy.yml은 보존하며 본인 commit에서 제외했다.
  원격 canonical CI는 foundation main 정책 병합 뒤에 통과할 수 있다.
- 남은 gate: 최종 공통 pack/policy 동기화, Docker 정리 포함 CI 재확인,
  독립2리뷰 recheck, PR merge, 부모 go. 후보 이미지는 운영에 배포하지 않았다.

인계 파일은 taskroot AGENT-HANDOFF-codex-map-weather.md와 MAP-REVIEW-PACKET.md다.
WSL Map node_modules는 종료된 본인 생성물 정리로 없으며, n150 검증 checkout 의존성은 보존했다.
종료된 경로 외 공유 /tmp glob·타 agent·기존 사용자 cache는 정리하지 않았다.


## c8 채택과 Docker 지연 삭제 후조건

부모 단일 후보 integration-8-review의 common670a753, upstream9a7a348 및 CSSfix.4 원장을 채택했다.
UI0.2.0/tokens0.1.1/core1.0.1/web1.0.3/LightningCSS1.33.0+nativecss.fix.4의 동일파일을 사용한다.
CSS는 frontend와root 직접 개발 의존성이고 root override는 $lightningcss를 참조한다.
이전 공통 Dialog 수정 인계는 taskroot COMMON-DIALOG-HANDOFF-codex-map.md에 보존했다.

기존 정리 확인은 rm의30초 제한 뒤 약2초만 재조회했다. 실제 removing/PID0 지연보다 짧았다.
최대5분의 wall-time 예산 안에서 반복 조회하고, 성공한 빈 stdout만 부재로 인정하도록 보완했다.
각 CLI 조회도 남은 시간으로 제한한다. stdout이 모두 닫힌 close 이후 결과를 판정하며,
기존 소유 label·정확 ID·이름 확인과 영구 잔존 실패 분류는 유지한다.
지연 삭제/영구 잔존/조회 실패/예산 초과의 회귀 단위5개를 추가했다.
실제 c8 설치와 정식286D의 종료코드·정리 gate를 n150에서 재검증한다.


## c9 최종 D와 정리 gate

검증 source e3ea216c128c3e7ef5346b17db6d4ec3fd5272a0의 새 production 이미지를 빌드했다.
n150 정식 D --workers=2에서286개가6.4분에 모두 통과했다.
strict inventory dc85a2c127f1ddb68fef6ae55dc71a04ddb2005bfeb784c94249aaf535d939a5가 일치하며
expected/actual failure0, flake0, skip0, global error0이다.
전체 runner outcome은 passed/exit0/issues[]이고 Playwright child도exit0이다.
cleanup 뒤 독립 조회에서 정확한 소유 container/network/image가 모두 부재였다.

원시 증거는 작업 루트 validation/map/c9b-e3ea216c128c-checkpoint.log,
-state.json, -preserved-reporter.json, -owned-runtime-identity.json,
-independent-postconditions.json과 c9-validation-summary.json에 보존했다.
본인 worker/runner/observer 종료와 runtime 내부 파일 제거도 별도로 확인한다.
후속 문서 commit은 출처·검증·인계만 바꾸며 제품/lock/vendor 입력은 검증 source와 동일하게 유지한다.
부모 중앙 workflow·CI/독립 리뷰·merge·배포 go는 부모가 처리한다.
