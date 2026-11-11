# 2026-11-11 관리자 공통 UI 통합 기록

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

현재 산출물은 `integration-5-review` 후보이며 최종 freeze 전이다.
[출처와 SHA512](../third-party-common.md), [원장](../../packages/kor-travel-map-admin/frontend/common-artifacts.json)에
부모와 동일한 4개 tgz의 정보를 기록했다. 이전 vendor는 제거했다.
ESLint 10.14.0 / Doctor 0.9.22 / exact 최신 targets를 적용했다.
TypeScript 5.9.3은 최신 major의 openapi-typescript/ts-eslint peer 호환 예외이며,
Node 타입은 runtime 22에 맞춘 22.20.5다. root ajv 8.20.0 직접 개발 의존성은
RHF resolver의 optional peer 8과 ESLint의 nested 6이 분리되도록 해 npm tree 충돌을 해소한다.
강제 설치·legacy peer 옵션·추가 lint/Doctor suppressions는 쓰지 않았다.

CI는 frontend cwd에서 `check:dependencies --source src`를 실행해 AST 기반 중복 Table·Base UI,
exact policy 및 vendor/원장/lock integrity를 확인한다. Doctor는 full/warning gate다.
기존 local Table v8 compiler 예외 검사는 common v9 reexport 경계 검사로 바꿨다.
공식 Playwright 1.65.0 noble 이미지 digest는 4개 runner/build 파일에 동일하게 고정했다.

## 현재 검증

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

후보 배포는 실행하지 않았다. 남은 실제 blocker는 common LoginForm 수정·최종 산출물 freeze와
격리 e2e/독립 리뷰/CI/merge/부모 go다.


## 추가 지도 호환성 확인

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
