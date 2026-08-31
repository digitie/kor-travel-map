# resume-2026-08a.md — resume.md 아카이브 (2026-08-04 ~ 2026-08-27)

> `docs/resume.md`에서 2026-08-31 분리(규약 §8). 읽기 전용 이력.

## 2026-08-27 — M05 external membership terminal 보존

`c6c73cdf…` candidate는 n150에서 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/foreign_membership` terminal로 보존됐다. raw membership row·catalog 값·stderr는 읽지 않았다.
PostgreSQL이 target role의 membership을 자동 철회하더라도 target 밖 role이 얽히면 외부 principal의 권한 관계가
변하므로, PinVi와 Manager는 이를 계속 fail-close한다. 두 전문 적대 리뷰는 이 결론에 동의했다.

### 이 변경의 다음 한 작업

target 밖 membership을 보존할지 permit-bound reset으로 철회할지 운영 권한 결정을 받는다. 결정 전에는 새 pinset이나
n150 rebuild를 만들지 않는다.
## 2026-08-27 — M05 target 내부 membership grantor 과잉 차단 보정

`b22bfb8c…` candidate는 n150에서 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/foreign_membership` terminal로 보존됐다. raw membership 값은 읽지 않았다. PinVi
`a619d037…`은 target 네 role 내부 edge의 grantor provenance를 external dependency로 보지 않고, roleid/member
중 하나라도 target 밖에 닿는 edge는 계속 fail-close한다. Manager `fd75950…`과 Map `9c64e862…`의 새 pinset은
`89330403…`이다. 두 전문 적대 리뷰는 P0/P1 없이 GO를 냈다.

### 이 변경의 다음 한 작업

새 source CI가 성공한 뒤 trusted Manager release를 n150에 설치한다. 새 pinset의 official
`rebuild-pinned --confirm --json`은 정확히 한 번만 실행하며, committed 증적과 isolated M04/M05 live mutating
E2E가 모두 성공하기 전에는 코드를 merge하지 않는다.
## 2026-08-27 — M05 reset isolation refusal의 안전한 세분화

`31fe73ad…` candidate는 n150에서 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/target_not_isolated` terminal로 보존됐다. raw database 값·psql 출력·stderr는 읽지 않았다.
PinVi `9e438611…`은 같은 transaction lock 안에서 fixed enum 하나만 root-owned receipt에 기록하고,
Manager `541fa41…`은 그 enum과 inode·transaction·pinset binding을 strict parse한다. Map `9c64e862…`과의
새 pinset은 `b22bfb8c…`이다.

### 이 변경의 다음 한 작업

두 전문 적대 재리뷰와 최신 CI가 성공한 뒤에만 trusted Manager release를 n150에 설치한다. 새 pinset의 official
`rebuild-pinned --confirm --json`은 정확히 한 번만 실행하며, committed 증적과 isolated M04/M05 live mutating
E2E가 모두 성공하기 전에는 코드를 merge하지 않는다.
## 2026-08-27 — M05 identity DTO 후보 준비

`37932169…` candidate는 PinVi one-shot 전 identity admission에서 terminal 처리됐으며 재시도하지 않는다.
Manager는 live `PinnedDatabaseIdentity`를 journal DTO로 변환해 비교하도록 보정했고, PinVi `28ca250d…`·
Map `9c64e862…`의 새 pinset은 `31fe73ad…`이다.

### 이 변경의 다음 한 작업

두 코드 PR의 최신 CI·전문 적대 재리뷰를 확인한 뒤 Manager trusted release를 n150에 설치한다. 새 pinset의
official `rebuild-pinned --confirm --json`은 정확히 한 번만 실행하며, committed 증적과 isolated M04/M05
live mutating E2E가 모두 성공하기 전에는 코드를 merge하지 않는다.
## 2026-08-27 — M05 result receipt candidate 준비

PinVi `fc01e5d6…`은 fresh reset의 result receipt를 transaction/pinset-bound fixed JSON으로 발행하고,
Manager는 root-owned `0600` file의 inode 보존과 strict parse를 확인한다. Map `9c64e862…`와의 새 pinset은
`37932169…`이며, 과거 후보를 재사용하지 않는다.

### 이 변경의 다음 한 작업

PinVi/Manager CI와 두 전문 적대 리뷰를 완료한 뒤 Manager trusted release를 n150에 설치한다. 이 pinset으로만
official `rebuild-pinned --confirm --json`을 정확히 한 번 실행한다. committed 증적과 isolated M04/M05 live
mutating E2E가 모두 성공하기 전에는 코드 PR을 merge하지 않는다.
## 2026-08-27 — M05 template0 candidate 준비

`68d99705…` candidate는 n150에서 정확히 한 번 실행되어 PinVi role-catalog reset terminal로 끝났고 재시도하지
않는다. Manager `dd42a150…`은 PinVi target만 `template0`으로 생성하며, PinVi `0b903701…`과 Map `9c64e862…`의
새 pinset은 `285618c0…`이다. 두 전문 적대 리뷰는 최종 Manager source/pin rotation에 P0/P1 없음을 확인했다.

### 이 변경의 다음 한 작업

PinVi #500의 새 CI를 완료한 뒤 Manager #243의 trusted release를 n150에 설치한다. 새 `285618c0…` pinset에서만
official `rebuild-pinned --confirm --json`을 정확히 한 번 실행한다. `committed` 증적이 생기기 전에는 M04/M05
live mutating E2E나 코드 PR merge를 시작하지 않는다.
## 2026-08-27 — M05 fresh candidate의 immutable Python base 선행 조건 확인

Map `cf65e973…`와 PinVi `97d2f924…`의 fresh pinset `872e3262…`를 Manager trusted
release에서 공식 `rebuild-pinned --confirm`으로 정확히 한 번 실행했다. candidate journal·DB/runtime
mutation 전에 generic paired builder 오류로 fail-close했고, 동일 pinset은 재시도하지 않는다. 원문 builder
출력·credential·path는 저장하거나 출력하지 않았다. 이후 안전 진단은 API receipt 부재를 fixed class로만
분류할 수 있으나, 이를 당시 실행의 원문 오류로 소급하지 않는다.

동일 sealed Map API candidate builder는 로컬 Docker에서 receipt까지 정상 발행했다. n150에서는 API
Dockerfile이 요구하는 immutable Python base image가 local cache에 없어 첫 `docker image inspect`가 실패함을
read-only로 확인했다. 따라서 source/receipt 계약이나 PinVi evidence를 우회하지 않고, Manager가 exact digest
base를 trusted candidate preflight에서 provision하도록 별도 PR로 보강한다.

### 이 변경의 다음 한 작업

Manager preflight가 Map API·Dagster Dockerfile의 immutable Python base를 exact digest로 확보하고
재관측하도록 구현·검증한다. 이 변경과 Map execution journal의 merge 뒤 새 source pinset으로만 fresh candidate를
한 번 실행하며, `committed` evidence가 생기기 전에는 M05 PinVi live E2E를 시작하지 않는다.
## 2026-08-27 — PinVi M05 Admin provenance identity 계약 정정 진행

PinVi M05 attestation이 실제로 읽는 Map Admin `GET /v1/admin/features/{feature_id}/creation-provenance`는
M05 event/evidence schema와 달리 최상위 `data.feature_id`를 UUID로 치환하고 `feature_uuid`를 주지
않았다. repository reader는 이미 UUID 축을 읽고 있고 `FeatureIdentity` resolver도 opaque ID와 UUID를
모두 보유하므로, DB/claim 스키마를 바꾸지 않고 HTTP 경계에서 opaque `feature_id`와 별도 UUID
`feature_uuid`를 함께 반환하도록 정정한다. UUID claim 내부 값은 immutable evidence 저장 계약으로
유지하며, reader UUID·claim UUID·응답 UUID가 다르면 fail-close한다.

artifact-code commit `256b4e668bae8e5d3f81ec1a45d401a79d0a2f5a`의 generated full/admin OpenAPI
SHA-256은 `0a1548a94c80bab1af6ab79c10b6f07eba32450adccd8ec2751a8c5256144c1d`다. user/service artifact는
각각 `489b05d3e62e3531233e3e7eb8c97f9ddf92aa1ecf1573b7557a5951e7f6a61b`/
`99ba6c178bf55401d3e1bb638a01b96f66bbac38d604534aa126a70f4be53d3d`로 불변이다. Map source/contract
전문 적대 리뷰 두 건은 GO를 판정했지만, PinVi consumer UUID binding이 아직 없다.

### 이 변경의 다음 한 작업

Map draft PR을 원격 checkpoint로 올리고 CI를 확인한다. PinVi는 위 exact Admin artifact와 artifact-code source
commit을 re-vendor하고, provenance `feature_uuid`를 M05 case의 manual/old UUID와 각각 대조하도록 consumer를
고친 뒤에만 M04/M05 live gate에 사용한다. 두 독립 적대 리뷰의 Map 내부 P0/P1은 0건이고, UUID 불일치가 GET
경계에서 partial evidence 없이 RFC7807 500으로 닫히는 회귀도 추가했다. 현 candidate의 이전 evidence는 재사용하지
않는다.
## 2026-08-27 — T-VN-H34A 분류 책임 경계 조사 완료, 후보 전수 조사 대기

MOIS 인허가 업종과 여행자용 시설 성격이 다르게 보이는 H34A를 source·문서만 읽어
재평가했다. [조사 보고서](../reports/t-vn-h34a-category-ownership-audit-2026-08-27.md)는
`rest_cafes`가 인허가 service slug이고 Map 변환이 이를 의도적으로 `02020100`으로 보존한다는
점을 확인했다. 따라서 공식 curation link가 맞는 `진해보타닉뮤지엄` 같은 사례만으로 provider
오류나 Map source category overwrite를 주장할 수 없다.

### 이 변경의 다음 한 작업

H34A는 승인된 read-only source snapshot 또는 n150 read-only 경계에서 후보를 전수화한 뒤에만
계속한다. 원천 해석 오류는 `python-mois-api` PR, 원천은 정상이나 별도 여행 표시 의미가 필요한
경우는 ADR과 별도 Map 정책 PR로 분리한다. 운영 DB·CSV·curation link를 수정하거나 H34B import를
앞당기지 않는다. 전역 최우선 작업은 여전히 Manager의 검증된 offline wheelhouse 공급 절차다.
## 2026-08-26 — Manager #229 병합 뒤 신뢰된 설치기 wheelhouse 선행 조건 대기

Concierge legacy boundary는 Manager [#228](https://github.com/digitie/kor-travel-docker-manager/pull/228)에서
신뢰된 배포·승인된 stage/retire·공개 HTTP와 실제 브라우저 로그인 → 인증된 BFF → 로그아웃 → 재차단까지
완료됐다. 이어 승인된 `rebuild-pinned --confirm`이 여섯 PinVi DB role 값 미선언에서 fail-close한 경계를
Manager [#229](https://github.com/digitie/kor-travel-docker-manager/pull/229)로 보정했다. #229는 서로 독립적인
보안·Manager 계약 적대 리뷰의 GO, 전체 backend 657건, Ruff·strict Mypy를 통과해 병합됐다. 이 변경은 trusted
`/opt` root pair만 사용하고, lifecycle/C6c admission 전에 role 값을 쓰지 않으며, 호출자 environment와 dotenv
보간을 차단한 원문 snapshot 및 `map_runtime_ready` 한정 단 한 번의 rebind receipt를 사용한다.

병합 commit의 깨끗한 checkout과 기존 root 소유 오프라인 wheelhouse로 공식 installer를 실행했으나,
활성화 전에 build dependency `poetry-core` wheel 부재로 중단됐다. installer의 staging/rollback tree는 정리됐고,
활성 release·canonical `.env`·Docker/Compose·candidate/journal·runtime·세 DB는 바꾸지 않았다. 네트워크 다운로드,
수동 wheel 생성, Docker/Compose/SQL, journal/DB 복구는 실행하지 않았다.

### 이 변경의 다음 한 작업

검증된 root 소유 오프라인 wheelhouse에 build dependency를 공급하는 별도 신뢰 운영 절차를 확정한 뒤에만 #229
깨끗한 release 설치를 다시 시도한다. 설치가 성공하면 이미 승인된 단일
`ktdctl pinvi-pair rebuild-pinned --confirm`만 실행하고, 새 v6/v8 candidate의 비밀 비포함 `committed` 증적을
확보하기 전에는 `T-VN-FINAL-REBUILD`/D1/D2/41C를 재개하지 않는다.
## 2026-08-26 — Docker Manager trusted/runtime boundary 후속 대기

n150에서 새 PinVi #477 pinset의 승인된 rebuild가 DB reset 전에 멈춘 직접 선행 원인은 legacy
`docker-compose.override.yml`였다. 이 파일은 Geo backup의 알려진 값을 덮고 Concierge UI에 전체
source `.env`를 주입해 single-file Compose contract를 위반했다. Docker Manager
[#223](https://github.com/digitie/kor-travel-docker-manager/pull/223)은 병합·trusted 배포됐지만, 설치 shim의
`/opt` project root를 retirement가 blanket 거부해 공식 명령은 mutation 전에 멈췄다. 이는 fail-close라 P0
incident는 아니지만 sanctioned rebuild 선행 경로를 막는 P1이다. 후속
[#224](https://github.com/digitie/kor-travel-docker-manager/pull/224)는 전문 적대 리뷰·전체 backend 검증 뒤 병합됐다.
이 변경은 `/opt`를 canonical Compose root로 계속 사용하고 legacy home source는 descriptor-safe protected stage로
one-way snapshot한 뒤에만 retire하도록 한다. raw/resolved Compose, UI/API host network, API loopback command/port,
UI auth guard·production command 검증은 유지한다.

### 이 변경의 다음 한 작업

Manager 공식 배포 절차로 #224를 trusted release에 설치하고, 수동 Docker/Compose/SQL 없이 legacy source
stage·retire·Concierge 로그인/BFF/로그아웃 live acceptance를 실행한다. 그 결과와 새 v6/v8 candidate의 비밀
비포함 failure stage 또는 committed 증적을 확보하기 전에는 `rebuild-pinned`를 추가 실행하지 않고,
`T-VN-FINAL-REBUILD`/D1/D2/41C를 재개하지 않는다.
## 2026-08-26 — T-FE-MOCK-FLAKE mocked checkpoint 재고정 (Draft)

PR [#1077](https://github.com/digitie/kor-travel-map/pull/1077)는 과거 285개 mocked failure
manifest를 실제 suite 284개와 관측 inventory SHA-256으로 갱신한다. exact clean checkout과
npm 12.0.1 dependency tree에서 self-owned checkpoint D를 단일 worker로 재실행해 **284/284
passed**, manifest 일치, reporter gate true, runner exit 0을 확인했다. 실행이 만든
container·network·image·임시 runtime은 모두 제거됐으며, 운영 UI·DB·source pinset·rebuild
journal은 건드리지 않았다.

### 이 변경의 다음 한 작업

모의 gate는 현재 source에서 다시 green이지만 `T-FE-MOCK-FLAKE`는 `[~]`를 유지한다. 현 배포
runtime과 일치하는 승인된 읽기 전용 logs credential 및 허용 origin을 값 비노출으로 확보한 뒤에만
`logs.live.spec.ts`를 재실행한다. credential을 추측·회전·우회하거나 기존 스모크 credential을
재사용하지 않는다. 이 조건은 새 pinset의 D1/D2/41C acceptance와도 별개다.
## 2026-08-26 — PinVi #477 새 pinset rebuild 미종결 인시던트

Docker-manager PR #219의 PinVi #477 source 회전 뒤 신뢰된 n150 Manager에서 새 정규
pinset `cb8d15591480111d7f4cd70398ad46b129e814ad3b9375dfa0fc83562b366752`에 대해 승인된
`ktdctl pinvi-pair rebuild-pinned --confirm`을 최초 실행과 같은 공식 재개로 두 번 실행했다.
두 실행 모두 0이 아닌 종료로 끝났고, 새 pinset별 v8 journal은
`phase=map_runtime_ready`, `journal_generation=20`에 남았다. Map source
`cc81081ff2e540a6ad9c428a296515e1d79bc316`와 PinVi #477 squash SHA
`10efb21ad84b23db2eeb6d09856cda16d3337822`의 결박은 journal에서 확인했지만, 새 generation은
`committed`되지 않았다.

두 전문 적대 리뷰는 세 번째 재시도, raw Docker/Compose/SQL 조작, journal·permit·DB 변경을
모두 금지했다. 현 v8 형식에는 실패 단계의 비밀 비포함 durable receipt가 없어, 폐기한 raw
출력 없이 Map runtime startup·PinVi bootstrap one-shot·PinVi schema 확인 중 어느 지점인지를
구별할 수 없다. 두 PostgreSQL만 healthy/running이고 일반 runtime은 fail-closed 정리로
종료된 상태는 확인했으나, 이것만으로 원인을 단정하지 않는다.

### 이 변경의 다음 한 작업

새 후보의 `T-VN-FINAL-REBUILD`/D1/D2/41C acceptance는 중단한다. 기존 H300 committed
generation은 이전 pinset의 immutable 이력일 뿐 새 후보의 증거로 재사용하지 않는다. 외부 운영
인시던트 절차에서 값·로그 원문이 아닌 허용목록 failure stage 또는 service-level 상태 증적을
확보한 뒤에만 원인별 후속 조치를 결정한다. 이 판단 전에는 재시도·수동 복구·이전 revision 복구를
수행하지 않으며, 300 이후 application row·건수·업무상 무결성 검증도 범위 밖으로 유지한다.
## 2026-08-26 — PinVi #477 source 회전 뒤 다음 후보 preflight

Docker-manager PR #219가 PinVi #477 squash merge
`10efb21ad84b23db2eeb6d09856cda16d3337822`와 canonical pinset
`cb8d15591480111d7f4cd70398ad46b129e814ad3b9375dfa0fc83562b366752`를 다음 후보의 source
authority로 병합했다. Map source는 H46H에서 수락한
`cc81081ff2e540a6ad9c428a296515e1d79bc316`를 유지한다. 기존 H300 v6/v8 generation은 이전
pinset의 immutable history이며 새 source를 입증하거나 재개하는 receipt가 아니다.

### 이 변경의 다음 한 작업

Manager local runbook 기준의 read-only preflight로 새 source pinset의 detached checkout,
candidate build 입력, H300과의 journal namespace 분리, 세 DB·image·schema attestation 경계를
확인한다. 새 candidate가 v6/v8으로 `committed`되기 전에는 `T-VN-41F1D-D2`·`T-VN-41C` 또는
logs live acceptance를 이전 H300 evidence로 재개하지 않는다. 승인된 읽기 전용 logs 자격증명과
허용 origin은 별도의 계속된 blocker다.
## 2026-08-26 — T-FE-MOCK-FLAKE n150 실제 logs는 인증 승인 근거 대기

n150의 배포된 Map source에서 `/ops/logs` `GET` 전용 실제 spec을 단일 워커·무재시도로
실행했다. local-only 런북 자격증명은 auth setup에서 `401`으로 거부돼 로그 본문 두
시나리오는 시작하지 않았다. 브라우저 세션·실패 산출물은 즉시 폐기했고 application row,
건수, 업무상 무결성을 읽거나 쓰지 않았다.

### 이 변경의 다음 한 작업

배포 runtime과 일치하는 승인된 읽기 전용 자격증명과 허용 origin을 값 비노출으로 확보한 뒤
`logs.live.spec.ts`만 재실행한다. 자격증명을 추측·회전·우회하거나 기존 스모크 자격증명을
재사용하지 않는다. 이 인증 승인 근거와 별개로 D2/41C는 최종 고정 pair와 일회용 고정
픽스처가 있어야 하며, off-box backup은 별도 외부 목적지·보존 승인 근거가 필요하다.
## 2026-08-26 — T-VN-H46H `300` baseline·n150 fresh rebuild 완료

Map PR #1066 exact head `cc81081ff2e540a6ad9c428a296515e1d79bc316`와 Docker-manager PR #207
merge `ecfbddb7b3d1afbd74646abbaa4082dd70b53a42`를 고정한 paired candidate를 trusted n150
설치본에 반영했다. 승인된 `ktdctl pinvi-pair rebuild-pinned --confirm`은 durable journal
`version=8`, generation `32`, transaction `5121a6d2-692d-4bd9-a5b0-d572d58c0f8f`,
`phase=committed`로 완료됐다. Map·PinVi runtime, 세 DB identity/provenance/readiness와
브라우저 login을 확인했고, data-independent live UI 11개 테스트가 모두 통과했다.

사용자 결정에 따라 `300` 이후 application row/건수/업무상 무결성 비교는 하지 않았으며,
이전 revision/기존 DB restore도 수행하지 않았다. 필요하면 fresh schema에 원천/ETL을 처음부터
재적재한다. Features의 고정 ID·컬렉션·두 번째 페이지를 요구하는 data-dependent E2E는 별도
데이터 적재 이후의 운영 검증으로 남긴다.

### 이 변경의 다음 한 작업

`T-VN-FINAL-REBUILD`의 남은 주요 개발 barrier를 먼저 정리한 뒤
`T-VN-41F1D-D1`/`T-VN-41F1D-E` → `T-VN-41F1D-D2` → `T-VN-41C` 순서로
전체 logout/re-block·PinVi paired/WebSocket·consumer reconciliation acceptance를 진행한다.
H46H baseline 완료와 무관한 데이터 적재·이전 revision 복구는 수행하지 않는다.
## 2026-08-25 — T-VN-H46H paired builder 실행 모드 고정 (Draft)

n150에서 exact `dd2ee61f…` source를 sealed한 뒤 outer paired builder가 내부 API
candidate builder를 직접 실행하는 경로가 Git 모드 `0644`에서 막혔다. 내부 builder를
`100755`로 정본에 고정하고 회귀 테스트를 추가한다. 변경은 실행 모드뿐이며, 사용자가
정한 대로 `300` 이후 application row/건수 무결성 비교는 하지 않는다. 새 schema가
필요한 데이터는 원천/ETL을 처음부터 재적재한다.

### 이 변경의 다음 한 작업

원격 CI와 두 전문 적대 리뷰어의 exact head 확인 후 새 Map SHA를 Docker Manager v5
release pinset으로 회전하고, n150에서 승인된 `rebuild-pinned --confirm`을 재개한다.
## 2026-08-25 — T-VN-H46H full integration cluster 격리 보강 (Draft)

PostGIS full integration에서 role-bootstrap만 먼저 실패한 원인을 재현했다. `pg_engine`와
`migrated_engine`의 cluster 전역 role-level `search_path`가 `template0` fresh DB에도 보이는
설정 잔여를 만들어 bootstrap precondition을 먼저 발동시켰고, shared base DB에서 실행한
`DROP OWNED`가 다른 fixture의 application schema/extension dependency를 삭제하려 했다.

두 공용 fixture는 database-level setting으로 바꾸고, role-bootstrap 모듈은 같은 immutable
PostGIS image의 별도 cluster fixture를 사용하도록 격리했다. target DB 삭제 뒤에는 disposable
role만 직접 삭제해 shared DB 객체를 건드리지 않는다. migrated_engine을 선행하는 로컬 순서에서
role-bootstrap 회귀 `20 passed`, Ruff와 diff check를 통과했다.

### 이 PR의 다음 한 작업

최신 Map 커밋을 원격 CI에서 다시 검증한다. CI green 뒤 Manager release source/pinset을 해당
exact Map SHA로 회전하고, 두 전문 적대 리뷰어의 exact pair P0/P1=0을 다시 확인한다.
## 2026-08-25 — T-VN-H46H PostGIS CI image drift·teardown 수정 (Draft)

PR #1064 최신 CI에서 단위 게이트는 모두 통과했으나 PostGIS 통합 fixture가 부동
`postgis/postgis:16-3.5-alpine` 태그를 사용해 source receipt와 다른 catalog·role setting을
받는 문제가 드러났다. fixture를 기준 source image digest
`sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c`로 고정했고,
성공 bootstrap의 extension 의존성 때문에 `DROP OWNED`가 실패하던 teardown 순서도
database 삭제 후 role 정리로 교정했다.

로컬 role-bootstrap `19 passed`, fresh-300/Alembic `3 passed`. 전체 integration은 현재
환경에 Dagster 패키지가 없어 collection에서 중단됐으므로, 변경을 push한 뒤 CI 통합
재실행 결과를 확인한다.

이번 PR의 row-level application 데이터 무결성은 release gate가 아니다. immutable receipt는
고정 image에서의 schema·role·ACL·extension·필수 고정 seed 및 operation replay 경계만
검증하며, 데이터가 필요하면 새 `300` schema로 원천 재적재한다.

### 이 PR의 다음 한 작업

변경을 보안 감사 후 원격에 커밋·푸시하고, PR #1064의 전체 CI가 green인지 확인한다. 두
전문 적대 리뷰어의 exact-commit P0/P1=0을 다시 확인한 뒤 Draft를 해제하고 머지한다.
## 2026-08-25 — T-VN-H46H PostGIS 통합 fixture·locale 계약 정렬 (Draft)

PR #1064 PostGIS 게이트의 실제 실패를 fixture/environment로 숨기지 않고 고쳤다. 공식 PostGIS
image가 만든 `test` DB 대신 `template0` 기반 session DB를 사용하고, testcontainers 기본
superuser credential을 credential-preflight 길이·형식 계약에 맞춘 뒤 bootstrap 스크립트와
`database-credential-preflight.sh`를 함께 주입한다. fresh root/role-bootstrap의 ACL·catalog·seed
정렬은 `COLLATE "C"`로 고정하고 변경된 sidecar/manifest digest를 동기화했다. 다른 PostGIS
patch level의 glibc 이미지는 immutable 300 receipt를 검증하지 않고 alias-map 최소 표면만
검증하도록 분리했다.

role-bootstrap `18 passed`, fresh-300/Alembic `3 passed`, glibc alias `2 passed`, handoff
executable `27 passed`, 관련 unit contract `86 passed`, Ruff와 `git diff --check`를 통과했다.

이번 cutover는 기존 application row의 데이터 무결성을 검증하는 작업이 아니다. 필요하면
새 `300` schema에 원천 데이터를 처음부터 재적재한다. immutable catalog/seed receipt는
schema·role·ACL·extension·필수 고정 seed와 operation replay의 bootstrap 계약만 확인한다.
통합 fixture가 만드는 credential-bearing 환경 파일은 `docker exec` 명령행이 아니라
container stdin으로 설치하고 실행 뒤 삭제한다.
role-bootstrap도 `template0` target을 사용하고 large-object residue를 첫 mutation 전에
거부하도록 보강했다.

### 이 PR의 다음 한 작업

변경을 보안 감사 후 원격에 커밋·푸시하고, Map/Manager SHA exact pair를 두 전문 적대 리뷰어에게
재검토시킨다. PR #1064 PostGIS CI가 green인지 확인한 뒤에만 Draft 해제·머지를 진행한다.
## 2026-08-25 — T-VN-H46H fresh-root 응답 유실 재실행 경계 보강 (Draft)

fresh root가 operation receipt까지 커밋했지만 응답만 유실된 뒤 recover가 일시 실패하는 경우를
bootstrap 상태 문자열로 판정하던 경계를 제거했다. Map의 production-only read-only
`probe-missing`은 같은 PostgreSQL advisory lock 아래에서 receipt 부재와 exact pre-root role·
membership·schema·ACL·extension·DB 설정·object 상태를 확인하고, 기존 fence·journal·DB identity와
candidate/contract 기대 digest를 typed `receipt-missing-exact-prestate` 결과로 반환한다. receipt가
존재하거나 foreign/partial drift가 있으면 중단하며 expired fence는 probe 판정에만 허용한다.

실제 disposable PostgreSQL 및 관련 unit 회귀 `23 passed`, 변경 파일 Ruff·strict mypy를 통과했다.

### 이 PR의 다음 한 작업

Manager에서 root `recover` 실패 뒤 typed probe를 strict parse·plan 결박한 경우에만 fence 갱신과
root 재실행을 허용하도록 연결하고, 새 Map SHA를 Manager pinset에 반영한 뒤 두 전문리뷰어의
exact-commit P0/P1=0을 확인한다.
## 2026-08-25 — T-VN-41F1D-E 세 DB·Dagster role residue attestation 보강 (Draft)

Manager journal v8의 최종 계약에 맞춰 C7 verifier가 PinVi DB의 PostgreSQL system identifier,
DB name/OID, owner-login identity까지 exact 검증한다. Dagster metadata LOGIN role은 기존 privilege와
membership뿐 아니라 connection limit, password expiry 부재, role/database-local setting 잔여가 모두
canonical한지도 permit producer·migration consumer·C7에서 같은 field set으로 대조한다. Manager가
허용하는 operation UUID 계약보다 C7이 임의로 강했던 transaction/operation 불일치 제한도 제거했다.

Dagster runtime과 C7 관련 회귀 `305 passed`, 변경 파일 Ruff를 통과했다. 완료된 `T-VN-40`은
`tasks-done.md`에만 남고, 현재 저장소측 잔여는 Manager 최종 SHA pin과 exact-pair 재검토다.

### 이 PR의 다음 한 작업

Manager의 세 DB committed-resume 재검증과 journal v8 PinVi identity를 커밋한 뒤 새 Map SHA를 pinset에
고정하고 두 전문리뷰어의 exact-commit P0/P1=0을 확인한다.
## 2026-08-25 — T-VN-41F1D-E manifest v6/journal v8 exact attestation (Draft)

C7 live verifier를 구 manifest v5/journal v7에서 Manager의 canonical v6/v8로 올렸다. generation의
application `300` paired candidate evidence와 journal의 중복 결박, application create/final DB
identity와 canonical digest, root/finalize operation result, application/metadata permit, Dagster
metadata DB·LOGIN role identity를 exact field set으로 검사한다. 누락·추가 필드와 구 version은
호환 변환 없이 mutation 전에 거부한다.

실행형 양·음수 회귀 `76 passed`와 관련 runner contract를 통과했다. integration-map, Admin live
runbook, backup policy, H46H 설계 정본과 tasks의 중복 final rebuild 설명도 fresh-only/v6/v8로
정렬했다.

### 이 PR의 다음 한 작업

Manager의 orphan bootstrap credential, stale candidate tag, committed resume DB/image 재검증을
결선하고 새 Map SHA를 pinset에 고정한다.
## 2026-08-25 — T-VN-H46H production in-place writer 제거 checkpoint (Draft)

fresh-only 정책과 충돌하던 `0236→300` production mutation surface를 제거했다. API candidate
image는 더 이상 `ktm-application-schema-handoff`를 복사·실행·attest하지 않으며, exact `0236`
startup도 in-place transition 대신 승인된 destructive fresh rebuild만 안내하고 중단한다. final
permit은 이제 `map-fresh-300-finalize` lineage만 허용해 이전 handoff permit을 호환하지 않는다.

fresh root/finalize가 공유하던 catalog digest와 runtime invariant는 CLI/main·Alembic·DB engine·
write statement가 없는 root-owned `0444` 비실행 module로 분리했다. candidate/fresh-oracle builder는
이 module을 `/app/docker` 읽기 전용 contract tree에 byte-exact 결박하고 퇴역 handoff binary가 image에
존재하면 거부한다. 실제 PostgreSQL fresh root/finalize 회귀를 다시 통과했다.

### 이 PR의 다음 한 작업

live attestation parser와 운영 문서를 Manager manifest v6/journal v8 및 fresh-only 정본으로
정렬한다. 이후 Manager의 orphan credential·candidate tag·committed DB/image 재검증을 닫는다.
## 2026-08-25 — T-VN-H46H Dagster crash-safe exact catalog checkpoint (Draft)

Dagster metadata storage는 더 이상 receipt 없는 final head를 성공으로 승격하지 않는다. wrapper가
session-level PostgreSQL advisory lock을 intent 생성부터 외부 `dagster instance migrate`와
`reindex`, exact postcondition, receipt commit까지 유지한다. fresh 세 storage metadata와 head는 한
transaction으로 생성하며, 응답 유실이나 프로세스 종료 뒤 receipt가 없으면 같은 candidate
operation을 다시 실행한다. runtime의 implicit table autocreate는 비활성화했고 webserver/daemon
preflight도 committed operation receipt와 exact catalog를 요구한다.

postcondition은 설치된 Dagster package에서 생성한 run/event/schedule table·column nullability·index
계약, 단일 head, 필수 data migration marker를 대조해 catalog digest를 v3 receipt에 결박한다.
일회용 PostgreSQL에서 receipt 직전 강제 실패 → final-head/no-receipt 재실행 → committed
writer-free resume → index 손상 거부를 실제로 확인했다.

### 이 PR의 다음 한 작업

fresh-only 정책과 충돌하는 퇴역 `0236→300` 실행 표면을 candidate image에서 제거하고, live
attestation을 Manager manifest v6/journal v8 exact 계약으로 올린다. 이어 Manager의 orphan
bootstrap credential·candidate tag·committed DB/image 재검증 finding을 닫는다.
## 2026-08-25 — T-VN-H46H finalize 응답 유실 재실행 증명 checkpoint (Draft)

application fresh finalize의 응답 유실 뒤 단순 실패 문자열이나 raw `300` head만 보고 새 fence로
재실행하던 경계를 제거했다. 새 `probe-missing`은 같은 PostgreSQL advisory lock 뒤의 read-only
snapshot에서 finalize receipt 부재, prior root receipt의 operation·fence·journal·DB identity,
candidate commit/image, source catalog·seed·Alembic facet을 모두 exact 대조하고 typed
`receipt-missing-exact-prestate`만 반환한다. Manager는 이 증명을 strict parse·plan 결박한 경우에만
fence를 갱신하고 finalize를 재실행하도록 결선 중이다. 실제 PostgreSQL finalize 통합 회귀와 관련
unit·Ruff를 통과했으며 PR #1064는 계속 Draft다.

### 이 PR의 다음 한 작업

Dagster storage의 부분 초기화·receipt 없는 final-head 오인과 session lock 공백을 제거하고,
runtime autocreate를 닫은 뒤 full catalog/required migration postcondition을 receipt에 결박한다.
이후 새 Map SHA로 Manager pinset을 회전하고 전문 적대 리뷰 두 건의 P0/P1=0을 확인한다.
## 2026-08-25 — T-VN-H46H DB-atomic operation receipt·CI 환경 격리 checkpoint (Draft)

PR #1065 merge 위 rebase와 CI fixture 보정을 완료했고, API-only partial paired candidate는
원본 receipt 삭제·재빌드 없이 strict exact verify 뒤 재개하도록 원격 checkpoint `3547431a`에
올렸다. application fresh root/finalize와 Dagster storage는 DB transaction에 결박된 immutable
intent/result outbox 및 explicit read-only recovery로 전환했다. root/finalize는 Manager plan의
별도 operation UUID를 쓰며 writer-fence transaction ID와 혼용하지 않는다. Dagster metadata
identity는 canonical operation UUID와 `LOGIN NOINHERIT`까지 exact하게 검증한다.

outbox·문서 정리는 `6b60fee0`으로 원격 push했고 Manager의 새 wire·fence renewal 소비도 로컬
결선했다. 이 Map SHA의 Python CI 공통 실패는 fresh root helper가 임시 Alembic 환경을 테스트
프로세스에 남긴 것이 원인이었다. helper가 모든 종료 경로에서 원상복구하도록 고쳤으며 오염 재현
순서와 실제 PostgreSQL root/finalize를 다시 통과했다.

범용 feature-update/cache-target 함수·상수·SQL 이름의 `pinvi`도 `service_owned`/`relay_owned`
용어로 정리했다. 실제 외부 시스템 값과 PinVi 전용 auth/curation contract는 변경하지 않았다.

### 이 PR의 다음 한 작업

CI 환경 격리 수정을 커밋·push하고 새 Map SHA로 Manager pinset을 다시 회전한다. 그 뒤
API+Dagster paired candidate를 실제 빌드하고 두 전문 리뷰어의 누적 GO와 CI green을 받은 후 n150
배포·login POST+cookie·protected route·logout·PinVi paired live UI E2E를 수행한다.
## 2026-08-25 — T-VN-M04 Admin BFF 결정 자격 결선 보완 (Draft)

PinVi의 격리 M04 실제 UI 승인 뒤 Map pending receipt까지는 정상으로 확인했다. 다만
Map BFF가 feature request approve/reject 경로에 manual Feature create 전용 token을
주입하지 않아 API가 의도대로 `403`을 반환했다. BFF의 token 주입 범위를 canonical UUID
approve/reject 두 경로까지 정확히 넓히고, 그 밖의 경로에는 여전히 주입하지 않는 회귀를
추가했다. OpenAPI·DB migration 변경은 없다.

### 이 PR의 다음 한 작업

candidate frontend 이미지를 격리 Map 스택에 적용해 정상 BFF 승인과 이어지는 M05 paired
reconciliation을 실제 UI로 재검증한다. 그 뒤 적대 리뷰와 원격 CI green 전에는 머지하지
않는다.
## 2026-08-25 — T-VN-H46H paired candidate·인계 영수증 연속성 보강

Map draft PR #1064의 API candidate와 Dagster webserver/daemon candidate를 같은 commit·Git
tree에 결박하는 paired builder를 추가했다. 두 image의 immutable application contract와
실제 image ID를 다시 검증하고, Dagster metadata migration은 application final permit
consumer에서 분리한다. API와 두 Dagster runtime만 final permit을 소비하며, production
Compose의 장기 실행 Dagster service에는 root `.env`와 application privileged credential을
전달하지 않는다.

별도 metadata DB 경계는 root-owned identity permit으로 보강했다. storage migration은 쓰기
전에, webserver/daemon은 기동 전에 canonical `DAGSTER_HOME`/root-owned `dagster.yaml`, 같은
DSN의 system ID/name/OID/owner/login과 최소권한 role 속성을 확인한다. metadata login은 DB
owner와 같고 bootstrap과 다른 `NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/
NOBYPASSRLS`, membership 0개여야 하며 `session_user=current_user`도 요구한다. application DB
identity·여러 version row 중 하나라도 raw `300`·application schema를 가리키면 중단한다.
production permit은 Docker Manager authority, exact Dagster image,
paired receipt와 `dagster.yaml` digest를 결박하고, local-dev permit은 dedicated metadata DSN으로
관측한 identity만 별도 local authority로 기록한다.
local DB-init은 role과 DB가 모두 새것일 때만 생성하며, 기존 pair는 root-owned prior permit과
현재 identity의 byte-exact 일치만 무변경 재사용한다. 예약 application/system identity,
role/DB partial state, permit 누락·drift를 자동 `ALTER`/`REVOKE`로 수리하지 않는다.

로컬 virgin 경로는 PostGIS 자동 확장이 들어간 maintenance DB `postgres`와 application DB를
분리하고, `template0`에서 application DB 생성 → role/bootstrap → dedicated metadata DB/permit →
restricted `300` migration 순으로 같은 Compose snapshot에서 실행한다. Docker Manager production
finalization은 fixed `fresh-300 migrate`가 restricted root migration과 source receipt를 남긴 뒤,
외부 durable journal과 writer fence 아래 fixed `fresh-300-finalize`가 ACL 재조정과 destination
catalog 확인을 한 DB transaction으로 완료하는 두 단계다. raw `300` 중간 상태에는 permit을
발급하거나 runtime을 기동하지 않는다. exact `0236` 경로는 별도 controlled handoff만 허용하며
downgrade·old restore는 없다.

첫 실제 paired build는 sealed source를 0444/0555로 만든 뒤 임시 디렉터리를 원래 mode로
복구하지 못해 cleanup에서 중단됐다. 해당 실패는 image/receipt 성공으로 승격하지 않았고,
cleanup이 원래 exit status를 보존하면서 mode 복구 후 제거하도록 고쳤다. alternate top-level
Dagster storage key, appuser 쓰기 가능 config 상위 경로, bootstrap/superuser metadata login,
다중 version row의 raw `300`을 모두 negative gate로 고정했다. 초기화 중 임시 Postgres가
healthy로 보이던 Compose 경합도 최종 PID 1 확인으로 제거했다. 격리된 실제 Postgres에서 전용 role 생성·sealed permit
재실행·identity 조회, bootstrap login 거부, role만 남은 partial state의 mutation 전 거부를
확인했다. fresh live acceptance에는 고유 permit volume과 Dagster daemon을 포함하고 세
process의 same-image/state/absolute argv/DSN/read-only mount를 검사한다. n150 배포나 live UI
E2E 증거는 아직 아니다.
추가 적대 리뷰에 따라 external DB/infra standalone launcher는 Manager permit producer가 없어
즉시 중단한다. metadata role의 양방향 membership, metadata/application owner 분리, storage
one-shot의 application runtime/final-permit 입력 부재를 결박했다. local launcher는 다섯 DB
password를 URI-unreserved·상호 distinct로 제한하고 각 application/metadata DSN의 실제
login/password/database를 선언값과 exact 대조한다. 다섯 DSN authority와 실제 writer init
host도 한 canonical PostgreSQL endpoint로 결박해 target 분산을 mutation 전에 거부한다.
host/bridge fresh topology의 네 one-shot도 각각 같은 network/DSN을 받는다.

추가 P0/P1 재검토로 controlled handoff의 첫 SQL을 exact non-superuser migrator
`session_user=current_user` 검증으로 강화했다. `admin:stack`의 generic Alembic/metadata DB 생성은
제거하고, strict local-dev·loopback의 사전 준비된 application `300`/dedicated metadata identity와
migrated storage를 읽기 전용으로 확인하는 smoke 경로로 축소했다. source oracle과 API candidate의
봉인된 tree cleanup은 원 exit status를 보존하며, receipt 대상 `resources/curations`는
root-owned 0555/0444와 appuser mutation-negative로 고정했다. 실제 disposable PostGIS에서
application DB 생성·role bootstrap·metadata DB/permit 세 one-shot이 모두 exit 0이고 permit
directory/file이 `0:555`/`0:444:1`임을 확인한 뒤 정확한 프로젝트/volume을 제거했다. 이는 n150
production 증거가 아니다. 최종 application-300/Dagster/candidate 계약 단일 묶음은
`288 passed`이고 ruff·shell syntax·Python compile·`git diff --check`가 통과했다.

### 다음 한 작업

두 전문 적대 리뷰는 Map 내부 P0/P1 없음으로 판정했고 Docker Manager 동반 변경 전 release는
NO-GO다. checkpoint를 push한 뒤 새 commit으로 API+Dagster paired candidate를 실제 재빌드하고
receipt를 검증한다. 이어 Docker Manager의 Map-only
transition/journal과 v6 handoff rehearsal을 같은 candidate pair에 결박한다. n150 exact
deploy, 로그인 POST+cookie, browser live UI E2E와 CI green 전에는 PR #1064를 병합하지 않는다.
## 2026-08-24 — T-VN-H46H `300` runtime checkpoint 완료, 배포 전 적대 검토 진행

active integration fixture와 runtime은 retired `0200`~`0236` chain을 replay하지 않는 final
`300` 경로로 전환했다. normal Compose는 fresh bootstrap을 자동 실행하지 않으며, 빈
dedicated DB는 `fresh-init` profile을 명시해 한 번 준비한다. exact raw
`0236_tvn41s_compaction_drained` DB는 candidate image 안의 explicit controlled
handoff executable만 같은 transaction에서 catalog를 전후 대조한 뒤 `300`으로 stamp할 수
있다. normal API/Dagster startup, archive replay, raw version-table 편집, 기존 migration
helper, pre-`300` restore는 fail-closed한다.

현재 local evidence는 runtime/archive/backup unit 199건, executable handoff PostGIS
integration 1건, metadata consistency integration 11건의 통과다. 또한 격리된 일회성 local
PostGIS container에서 실제 `docker/postgres-role-bootstrap.sh`를 실행해 fresh target에
application role 21개와 `x_extension` PostGIS schema만 생성되고 Alembic table은 만들지
않음을 확인한 뒤 container를 제거했다. 이는 n150 검증이나 배포 증거가 아니다.

### 다음 한 작업

Docker Manager에 별도 비파기 transition/journal PR을 만들고, Map candidate의 정확한 commit과
stable PinVi revision을 고정한다. 현재 diff를 대상으로 진행 중인 두 전문 적대 검토를 반영한
뒤 n150에서 typed handoff → candidate deploy → login POST/cookie/invalid-auth 및 browser live
UI E2E를 실행한다. 이 증거와 CI가 갖춰지기 전에는 Map baseline PR을 merge하지 않는다.
## 2026-08-24 — T-VN-H46H Alembic `300` baseline·n150 live UI E2E 준비

Map [PR #1063](https://github.com/digitie/kor-travel-map/pull/1063)의 admin live fixture
권한 경계를 squash `01d65b2ad4ee265a3ef6b01448f6abf573a906a8`로 병합했다. Python
3.11/3.12/3.13, fixture replay, PostGIS integration, lint, OpenAPI drift, frontend
type-check/build가 모두 green이었고, 누적 변경은 독립 적대 검토 두 건에서 GO였다.

이후 작업은 새 열린 `T-VN-H46H`가 소유한다. active graph는 local branch에서 `300` 단일
root로 전환했고, source sidecar는 data-free isolated `0236` reference에서 생성했다.
fresh target의 final bootstrap 뒤 fixed root migration으로 raw `300`과 source catalog를
만들고, 별도 finalization에서 ACL+destination catalog를 같은 transaction으로 확정해 core
catalog fingerprint 동등성까지 확인했다. n150의 exact
`0236_tvn41s_compaction_drained` DB는 controlled `stamp --purge 300` handoff만 허용한다.
`rebuild-pinned`, raw production Compose, 수동 `alembic_version` 편집, archive replay는 이
경로의 대안이 아니다.

두 전문 설계·배포 적대 검토는 동일하게 다음을 P0로 판정했다: final 21-role
membership/ACL bootstrap, exact handoff tag·단일 version row·동일 transaction
pre/post catalog assertion, candidate image/head/source attestation, 그리고 destructive
rebuild journal과 혼동하지 않는 Docker Manager typed transition journal. PinVi의 진행 중
Alembic WIP는 이 candidate에 입력하지 않고 stable immutable revision만 유지한다.

### 다음 한 작업

첫 draft checkpoint에는 active/archive graph, immutable `300` sidecar, fresh final bootstrap과
generic operation을 막는 exact handoff guard까지 반영했다. 다음은 fresh/handoff regression
test, runtime image·entrypoint·Compose wiring, Docker Manager의 별도 in-place transition/journal
PR이다. 두 저장소의 누적 delta를 전문 적대 리뷰 두 건으로 다시 확인하고, n150 exact candidate
배포와 login POST를 포함한 live UI E2E가 통과하기 전에는 Map baseline PR을 병합하지 않는다.
## 2026-08-24 — PR #1063 fixture writer DB 경계·role graph 보강 (재리뷰 대기)

Draft [PR #1063](https://github.com/digitie/kor-travel-map/pull/1063)의 두 전문 적대 리뷰가
weather/price live fixture helper에서 두 P1을 찾았다. 별도 writer DSN이 API/browser와 다른
DB를 가리켜도 쓰기를 시작할 수 있던 경계와, M01 이후 generic provider state procedure의
`EXECUTE` 권한이 schema owner에는 없던 경계다.

helper는 이제 `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE`,
`E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE`,
`E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION`을 실제 DB·LOGIN role·Alembic head와
mutation 전에 대조한다. 일치할 때만 schema owner를 설정하며, provider state procedure의
한 `CALL`만 dedicated manual procedure owner로 `SET LOCAL ROLE`한다. API runtime에 write
grant를 추가하지 않는다. M01~M05 shared-cluster role residue를 위해 넣었던 base graph 예외도
이름 전체 제외가 아니라 exact membership edge와 PG16 option만 허용하도록 고쳤고 unsafe
future role 속성도 거부한다.

현재 로컬 검증은 fixture/role-contract unit 68건과 actual PostGIS Alembic metadata gate 15건이
통과했다. PR은 아직 Draft이며, 수정 commit push 뒤 두 전문 리뷰어의 재검토와 원격 CI green
전에는 Ready/merge하지 않는다.

### 다음 한 작업

PR #1063의 P1 보완을 commit·push하고 재리뷰·CI를 통과시켜 병합한다. 병합 뒤 clean `main`에서
`0236_tvn41s_compaction_drained` schema의 새 `300` Alembic baseline을 정확한 catalog snapshot과
forward-only stamp choreography로 별도 draft PR에 착수한다.
## 2026-08-22 — T-FE-MOCK-FLAKE 로그 mock 경계 고정

`T-FE-MOCK-FLAKE`의 self-owned mocked checkpoint에서 `/v1/ops/system-logs`와
`/v1/ops/api-call-logs`가 응답되지 않아 표가 `aria-busy` 상태로 남던 경계를
[PR #1059](https://github.com/digitie/kor-travel-map/pull/1059)에서 고쳤다. 생성된
OpenAPI `SystemLogsResponse`·`ApiCallLogsResponse` 타입으로 BFF mock payload를 고정했고,
targeted Playwright 1회 및 `--repeat-each=5`(총 6/6)가 통과했다.

두 전문 적대 리뷰에서 P0~P3 이슈는 0건이었고, lint·OpenAPI drift·Python 3.11/3.12/3.13·
fixture replay·PostGIS·type-check/Next build 전체 CI가 green인 것을 확인한 뒤 squash
`813a8a76ffa84f281ad46c9fb0e9bd2462fe5e21`로 병합했다.

따라서 mocked checkpoint 부분은 해소됐지만 `T-FE-MOCK-FLAKE`는 `[~]`로 유지한다.
n150 live GET-only 로그 검증은 local-only 자격증명과 prod credential 불일치로 auth setup
401에서 중단됐으므로, 최신 자격증명과 읽기 전용 실행 증거가 확보될 때까지 완료 처리하지 않는다.

### 다음 한 작업

이제 live credential 경계를 제외한 `T-VN-41F1D-D1`/`D2`의 비파괴 증거와 isolated
acceptance 실행 가능성을 재대조한다. n150 live GET-only 로그 검증은 최신 읽기 전용
자격증명과 실행 증거가 확보될 때까지 보류한다.
## 2026-08-22 — Map #1057 계약 pair 기록 및 Docker-manager v5 pinset 병합

Map [PR #1057](https://github.com/digitie/kor-travel-map/pull/1057)을 두 전문 적대 리뷰
(P0~P3 0건)와 lint·OpenAPI drift·Python 3.11/3.12/3.13·fixture replay·PostGIS·
type-check/Next build 전체 green 확인 후 squash `02341eaeed2fddfc191a7ef3551bc03385a54433`로
병합했다. 계약 artifact SHA freeze와 PinVi #465 exact pair 상태를 문서·테스트에 고정했다.

Docker-manager [PR #189](https://github.com/digitie/kor-travel-docker-manager/pull/189)도
Map `e420c89e…`·PinVi `27fe2043…`를 v5 source pinset으로 재고정해 squash
`28b121d07d6906f4b41294476d9add9e8023f9f9`, canonical digest `de5206dc…`로 병합됐다.
따라서 T-VN-41C의 계약·release authority 정합성은 확보됐지만, isolated paired live
acceptance·receipt 승격·production consumer enable과 M01~M05 활성화는 여전히
`pending`이다.

### 다음 한 작업

`T-VN-41F1D-D1`/`D2`의 비파괴 증거와 isolated paired acceptance 실행 가능 여부를
재대조한다. n150 권한·실데이터 증거 없이 `T-VN-41C` receipt 승격, M01~M05 활성화,
`T-VN-FINAL-REBUILD`는 실행하지 않는다.
## 2026-08-22 — PinVi #465 service/admin 계약 재vendor 병합

PinVi [PR #465](https://github.com/digitie/pinvi/pull/465)가 두 전문 적대 리뷰(P0~P2 0건)와
전체 CI green을 통과해 squash `27fe2043b7b8e747fbb42d91e461ea462f930bb7`로 병합됐다.
Map #1051 service(`db319a47` / SHA `99ba6c17…`)와 #1054 full/admin
(`fadc029c` / SHA `2c02ecfe…`)을 PinVi에 byte-exact로 재고정했고 user pin
(`037e2469` / SHA `489b05d3…`)은 유지했다. 따라서 T-VN-41C의 계약·provenance pair는
정합하지만, paired live acceptance·receipt 승격·production consumer enable은 여전히
`pending`이다.
## 2026-08-22 — #1055 문서 병합 및 code baseline 표현 고정

문서 전용 [PR #1055](https://github.com/digitie/kor-travel-map/pull/1055)를 두 전문 적대 리뷰
P0~P3 0건과 로컬 문서/redaction gate 확인 후 병합했다. squash merge는
`d92bd44da5dc91721abb4e6b0c3d8c0d8e3d1a00`이며 migration head와 code baseline은 #1054의
`fadc029c`로 변하지 않았다. `tasks.md`는 docs-only merge마다 stale해지는
`origin/main` 표현 대신 migration/code baseline을 명시한다.

PinVi service vendor는 별도 PR #465로 병합됐지만, T-VN-40/T-VN-41 receipt와
M01~M05·FINAL-REBUILD·live 운영 잔여는 계속 `pending`/미완료로 유지한다.
## 2026-08-22 — #1054 병합 및 다음 실행 단위 재정렬

`fix/ops-dataset-rollup-contract`의 [PR #1054](https://github.com/digitie/kor-travel-map/pull/1054)를
CI green과 두 전문 적대 리뷰(P0~P3 각 0건) 확인 후 병합했다. squash merge는
`fadc029ce2b0cd730c604697e04d1fccdff02ce9`이며, `tasks.md`의 현재 `origin/main` 기준도
`fadc029c`로 갱신했다. full/admin OpenAPI와 생성 타입·baseline SHA는 현재 tree와
일치하지만 T-VN-40/T-VN-41 receipt는 교차 저장소 paired acceptance 전까지 `pending`이다.

### 다음 한 작업

PinVi가 보유한 Map service `410` 계약을 현재 Map artifact와 byte 단위로 대조해
PR #465에서 재vendor·병합했다. 다음은 Docker-manager v5 source pinset 재핀과
T-VN-41C·M01~M05의 남은 consumer/live acceptance 대조다. FINAL-REBUILD와 live
운영 항목은 증적·권한 없이 완료로 승격하지 않는다.
## 2026-08-22 — #1054 OpenAPI baseline·consumer receipt 정합성 수정

T-VN-41S의 generic snapshot `410`/admission 계약으로 재생성된 full/admin OpenAPI와
`openapi-diff-v1.json`·T-VN-40 pending receipt의 SHA를 일치시켰다. user/service
표면과 PinVi vendor는 변하지 않았고, 교차 저장소 paired acceptance가 끝날 때까지
T-VN-40 receipt는 `pending`으로 유지한다. `tasks.md`의 T-VN-41C·FINAL-REBUILD
배리어와 M01~M05 활성화/paired 잔여 상태는 그대로다. admin 생성 타입과
`tasks.md`의 #1053 기준 SHA도 현재 tree에 맞췄다.
## 2026-08-22 — #922 후속 PR #1051 병합 및 백로그 정합성 감사

T-VN-41S/#922 후속 무결성 게이트를 [PR #1051](https://github.com/digitie/kor-travel-map/pull/1051)로
병합했다. merge commit은 `db319a4798229098d04e68e3ac64338183ad547f`이며 원격 CI 8/8이
green이었다. 두 전문 적대 리뷰에서 P0/P1은 0건이었고, 남은 P2는 raw DELETE/parent
CASCADE·reverse multi-material delete deadlock·planner 관찰과 migration lock 실측 같은
운영 보강 메모로 분류했다.

같은 기준으로 `tasks.md`와 `tasks-done.md`를 대조해 T-VN-M01~M05의 #1029 구현 병합분을
완료 이력으로 옮기고, route 활성화·restore/purge·교차 저장소 re-vendor·격리 live acceptance만
부분완료로 남겼다. T-VN-40 자체의 독립 잔여 task는 없으며 후속 검증은 T-VN-41C와 각 M lane이
소유한다.

### 다음 한 작업

`T-VN-41C`에서 Map `410` service spec을 PinVi에 re-vendor하고, PinVi generic Feature request와
M05 reconciliation을 포함한 격리 paired acceptance를 실행한다. 이 작업과 병행해 PinVi
식별자 정렬 PR 및 docker-manager C6c 대체 PR의 CI·적대 리뷰를 마무리한다.
## 2026-08-22 — T-VN-H27/#819 완료

운영자 확인으로 OPNsense HAProxy의 Map·Geo·PinVi 등 외부 노출 API backend에
`timeout tunnel 1h` 적용이 완료됐다. H27은 저장소 코드/PR 변경이 없는 edge 설정 task라
`tasks-done.md`로 이관했고 GitHub issue #819를 닫았다. 라우터의 effective config와 quiet
WebSocket 관찰 로그는 이 세션에서 직접 읽지 못했으므로 완료 근거는 운영자 확인이다.
## 2026-08-22 — #990 planner false-fail 종결 (#1049 병합)

H50 dedup EXPLAIN의 실제 수정은 [PR #1036](https://github.com/digitie/kor-travel-map/pull/1036)에서
이미 병합됐다. relation별 semantic gate와 작은 `source_entities` dimension의 정상 Seq Scan
예외가 비용 경계에서 인덱스 이름을 잘못 단언하지 않도록 고정한다. 후속 회귀 단언 PR
[#1049](https://github.com/digitie/kor-travel-map/pull/1049)은 `5dee44a3`으로 병합됐고,
문서 전용 변경이 같은 false-fail을 되살리지 않도록 작은 dimension Seq Scan 허용과 대량
`features` Seq Scan 거부를 함께 고정했다.

- planner helper 회귀 단언: 2 passed
- 대상 `test_t212d_perf_explain.py` ruff: 통과

### 당시 다음 한 작업

이 시점의 #1051 CI·리뷰 대기는 상단 엔트리에서 병합으로 갱신했다. 현행 다음 작업은
`T-VN-41C`의 final exact-pair·prod consumer enable이다.
## 2026-08-22 — T-VN-41S / #922 후속 무결성 게이트 보강

마지막으로 남아 있던 GC orphan 갈래를 닫았고, 적대 DB 리뷰가 찾은 live item DELETE
우회도 막았다. receipt가 마지막으로 삭제될 때
DB trigger가 material의 `orphaned_at`을 단방향으로 기록하고, 새 receipt가 orphan material을
되살리지 못하게 막는다. `_SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL`과
`_HAS_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL`은 이제 receipt anti-join 대신 orphan partial index를
사용한다. live material item은 `compacted_at` 이후에만 삭제할 수 있게 부모 row lock 기반
trigger를 추가했고, 실제 batch 크기·순서는 repository의 ordered `SKIP LOCKED` 경로가
보장한다. 완료 항목은 `docs/tasks-done.md`로
이관했다.

- `tests/integration/test_tvn41s_compaction_drained.py`: 10 passed
- `tests/integration/test_tvn41s_material_fences.py`: 5 passed
- `tests/integration/test_cache_target_stream_repo.py`: 40 passed
- `tests/integration/test_tvn41s_snapshot_material_explain.py`: 1 passed
- migration metadata gate: 8 passed, snapshot unit/migration boundary: 44 passed

다음 한 작업은 `T-VN-41C`에서 이번에 갱신한 service spec을 PinVi에 re-vendor하고 paired
acceptance를 다시 실행해 pending receipt를 승격하는 것이다. Map 쪽 runtime 410 선언과
OpenAPI/admin 타입 갱신은 이번 PR에서 닫았다.
## 2026-08-21 — T-VN-41S 잔여 셋 중 둘 처리, 하나는 이월 (task는 아직 열림)

후속 종료선에 남아 있던 셋 중 둘을 고치고 하나는 lane을 옮겼다. **다만 적대 리뷰가
둘 중 하나(GC 스캔)를 절반만 고쳤다는 것을 잡아, task는 닫지 않았다.**

| 항목 | 결과 |
|---|---|
| `ops` fail-closed ACL 탈출구 | fence는 그대로. 관장 밖(`public`)을 정본 경로로 하고 **실패 메시지가 직접 안내**한다. 메시지와 관장 schema 집합을 테스트로 묶었다 |
| compacted material 무한 누적 스캔 | `0236` — `compaction_drained_at` + partial index. **"아직 배출 중" 갈래**가 상수로 떨어진다. 같은 두 질의의 **orphan 갈래는 여전히 선형**이다(아래 잔여) |
| service spec `410` 선언 | **T-VN-41C로 이월.** 교차 저장소 re-vendor가 필요하고 41C가 어차피 그것을 요구한다. 오늘 깨진 것은 없다 — PinVi가 이미 그 410을 런타임에서 처리한다 |

게이트: ruff / mypy `--strict` ×2 / lint-imports / migration graph `--check` clean.
관련 통합·단위 스위트는 n150에서 통과했다(선택 목록은 `docs/tasks.md`의 41S 항목).

### 다음 한 작업

**GC backlog의 orphan 갈래를 마저 처리한다** — 그것이 `T-VN-41S`의 마지막 잔여다.
그 다음이 **`T-VN-41C`에서 `410` 선언 + PinVi re-vendor를 함께 한다.** 실행 절차와 막는 요인(하나)은
`docs/tasks.md`의 `T-VN-41C` 항목에 적어 뒀다 — `tvn40-live-acceptance-v1.json`이 T-VN-40
receipt의 커밋 쌍과 `pending` 가드 없이 결박돼 있어, **paired acceptance 재실행**과
**가드 추가 + receipt를 `pending`으로** 중 하나를 사용자가 골라야 한다.

그 밖에 41S가 남긴 잔여는 둘이다.

- **GC backlog 판정의 orphan 갈래가 아직 선형이다.** `0236`은 "아직 배출 중" 갈래만 상수로
  만들었다. orphan 갈래는 `compacted_at` 필터가 없어 영구 보존되는 audit material까지 전부
  anti-join하며, 네 갈래가 `OR`로 묶여 backlog가 **없을 때** 전부 평가된다 — 원래 지목된
  "한가할 때가 가장 비싸다"가 그 갈래에는 그대로 남아 있다(적대 리뷰 지적).
- **부하 아래 재측정** — 안전계수 2가 유일한 부하 관측 2.32배에 거의 소진된다.
## 2026-08-21 — live E2E 계약 drift 수정 및 운영 재검증

머지된 T-FE-MOCK-FLAKE 뒤 확장 live 실행에서 발견한 두 계약 오류를 `fix/live-contract-inputs`
브랜치에서 수정했다. `admin/issues`는 `provider_dataset_id` numeric 필터를 사용하도록
갱신했고, 파이프라인 갱신 요청 시나리오는 `/v1/ops/datasets`의 canonical MOIS row를
선택해 `provider_dataset_id` 기반 precheck를 확인하도록 갱신했다. 운영 frontend/API는
변경하지 않았다.

- frontend e2e type-check: 통과
- frontend lint: 통과
- n150 대상 live spec: `7 passed, 1 skipped` (읽기 전용 게이트)
- 임시 n150 checkout·인증 산출물: 정리 완료

### 다음 한 작업

변경을 커밋·push하고 draft PR을 만든 뒤 CI와 전문 리뷰를 확인한다. 별도 merge 지시 전에는
main에 merge하지 않는다.
## 2026-08-21 (codex) — T-VN-40 paired receipt 재봉인

n150 격리 Map/PinVi에서 canonical collection import/refresh 수용을 완료했다. Map
`81835cf9d31df61169bd522fc16437d51d90fc35`·PinVi
`5f1c0a0a5568c236e32e6f6bd4c14ba23191817b` source pair의 계약 bytes가 PinVi vendor와
정확히 일치하고, snapshot `304`, create replay, refresh `200 not_modified=true`, canonical
plan/POI 생성 및 legacy source plan 0건을 확인했다. 운영 DB 변경은 없었다.

T-VN-40 receipt를 `complete`로 봉인했으며, 현재 PR은 계약 hash·증거 기록만 변경한다.
세부 secret-free 증거는 `contracts/vnext/tvn40-live-acceptance-v1.json`에 기록했다.
별도 T-VN-34C UI runner는 `tvn36-direct-state-cutover` browser fetch `503`으로
`1 passed / 1 failed`였으며 TVN40 canonical import/refresh 근거로 사용하지 않았다.
당시 별도 후속으로 적었던 T-VN-40C PinVi legacy column 물리 삭제 gate도 완료 이력에
포함됐다. 현재 `tasks.md`에는 독립적인 T-VN-40 잔여를 두지 않고, 후속 cross-repo 검증은
T-VN-41C가 소유한다.
## 2026-08-21 — T-FE-MOCK-FLAKE 진행: 표 준비 대기 보강, live auth 재개 필요

PR [#1045](https://github.com/digitie/kor-travel-map/pull/1045)의 `admin-ops.spec.ts`
`/v1/ops/logs` smoke에 system/API 표별 locator scope, body row 준비 대기, `aria-busy` 해제
대기를 넣었다. 커밋은 `09d47cf7`과 `d208b76a`이고 draft PR을 원격에 유지 중이다.

- 전문 리뷰어 2명: 최종 누적 diff P0/P1/P2 모두 0건
- frontend type-check/lint: 통과
- npm tree / Next-Sharp ABI: 통과
- Vitest: 354/356 통과; 기존 NTFS Unix mode 테스트 2건 실패
- n150 mocked checkpoint A: 281/285 통과; 대상 로그 표는 mock backend 응답 부재로
  `aria-busy=true` timeout, 나머지 3건은 기존 실패 표면
- n150 live GET-only logs: prod auth setup 401, 2개 본 스펙 미실행
- GitHub CI 4개(`ci`, `lint`, `frontend`, `openapi`): 모두 green

### 다음 한 작업

리베이스 후 최신 CI를 확인하고 PR #1045를 merge한다. n150 live GET-only logs 스펙은
prod auth setup 401로 본 스펙 실행 전에 중단됐으므로, 최신 운영 자격증명 확인 전에는
재실행하지 않는다. credential을 추측하거나 회전하지 않는다.
## 2026-08-21 (codex) — T-VN-40 완료 항목 archive 정리

완료된 T-VN-40B/C·인수와 C7 evidence task를 `tasks-done.md`로 이관해 `tasks.md`에는 열린
작업만 남겼다. 당시 기준으로는 `origin/main`의 migration head가 `0232`였고 #1029가
M01~M05의 `0226`~`0235`를 그 위에 직렬로 두는 draft였다. 이후 #1029와 #1051이 병합되어
현재 head·활성 잔여는 상단 최신 엔트리와 `tasks.md`가 소유한다.

### 당시 다음 한 작업

이 기록 시점의 “#1029/PinVi M05 rebase” 지시는 완료됐다. 현재는 `T-VN-41C`의 exact-pair
re-vendor와 paired acceptance를 진행한다.
## 2026-08-21 — M01~M05 role isolation 및 dedup default planner CI 보정

C05 legacy migration test가 별도 database에서 M01/M04/M05 membership을 해제하면 PostgreSQL
cluster 전역 role graph가 바뀌어, 뒤따르는 shared migrated DB lane test가 순서 의존적으로
실패했다. 완료 head의 role graph만 다시 확정하는 lane fixture를 두고 M05 pristine-0233
bootstrap과 restore를 분리했다. 금지된 실행자 간 membership revoke와 role 속성·membership
option·중첩을 정확히 확인하는 단언으로 fixture가 즉시 중단하게 했다. C05 → M01/M04/M05 표적
integration은 `18 passed`다.

provider/dataset 하나가 `source_entities` fixture의 20%를 선택하는 dedup default EXPLAIN은
PostgreSQL 비용 경계에서 정상 Seq Scan일 수 있다. 이 선택성은 실행 시 단언으로 검증한다.
forced-index gate로 해당 index 호환성은
그대로 유지하고, default gate는 나머지 고선택성 대량 relation의 index path를 검증한다.
표적 dedup EXPLAIN은 `1 passed`다.

### 다음 한 작업

변경을 최신 `origin/main`에 rebase·push해 draft PR #1029 CI를 다시 확인한다. 모든 CI가
green이 된 뒤에만 N150 격리 mutating browser E2E를 시작한다.
## 2026-08-21 — main `0232` 재베이스 뒤 M04/M05 migration graph 재연결

`origin/main`이 `0232_tvn37d_notice_empty_range`까지 전진한 뒤, 아직 머지되지 않은 M04/M05가
같은 `0230`~`0232` revision ID를 선언해 fresh PostGIS CI에서 M01/M04/M05 procedure와 ACL이
누락됐다. main의 적용 이력은 바꾸지 않고 M04/M05를 `0233`→`0234`→`0235`로 재번호화해
`0232`→M01→M02→M03→M04→M05 dependency graph를 단일 head로 복구했다. bootstrap·restore
boundary·migration graph artifact·integration expectation도 같은 revision ID로 결박했다.

### 다음 한 작업

이 graph 재연결을 표적 Alembic/role-bootstrap integration과 lint로 다시 검증하고, draft PR CI가
green이 된 뒤에만 N150 격리 mutating browser E2E를 시작한다.
## 2026-08-21 — M05 event sequence가 catalog 대리키 lint에 오인되던 CI 보정

`OVERRIDING SYSTEM VALUE` lint를 provider catalog INSERT 범위로 한정했다. M05 reconciliation event의
독립 sequence write는 catalog identity가 아니므로 허용하고, 실제 catalog 대리키 고정 회귀는 계속 막는다.

### 다음 한 작업

보정 커밋을 푸시해 Map CI를 다시 확인한다. CI green 뒤에만 N150 격리 mutating browser E2E를 시작한다.
## 2026-08-21 — `0229`~`0232` 묶음 prod 배포 완료, admin 500 해소

| 축 | 배포 전 | 배포 후 |
|---|---|---|
| prod DB head | `0225_tvn40c_physical_removal` | **`0232_tvn37d_notice_empty_range`** |
| 적용 migration | — | `0229`·`0230`·`0231`·`0232` |
| image / `.env` | `294db534` / EXPECTED_HEAD `0225` | `e47a389f` / EXPECTED_HEAD `0232_tvn37d_notice_empty_range` |
| `curated_source_rules` | `candidate` 18 + `curated` 35 | **53행 전부 `candidate`**(`curated` 0) |
| `GET /v1/admin/curated-source-rules` | **500** | **200** (53항목 전부 `candidate`) |
| C05 `provider_dataset_id` | 없음 | **104~108** (baseline seed는 70~74 — 환경 지역값이라 다른 것이 정상) |
| `provider_dataset_id 73` | `python-datagokr-api/standard_special_streets` | 그대로, 자식 0건 |
| identity sequence | 103 | 108 (전진만) |
| ops relation | 71 | 72 |
| `features` / `source_records` | 1,008,852 / 1,009,164 | 동일 (무손실) |

배포 전 587M prod 덤프를 별도 DB로 복원해 실제 migrator 자격으로 전 구간을 리허설했고
(fail-closed runtime ACL 조정 포함 exit 0), **실배포 실측이 리허설 예측과 한 항목도
어긋나지 않았다.** 복구점(`kor_travel_map_0225_pre-tvn41s_20260820T234727Z.dump` +
`manager.env_pre-tvn41s_...bak`)은 보존돼 있다.

`T-VN-40B`(source rule `curated` 퇴역)와 `T-VN-C05-CATALOG-KEY`(대리키 → 자연키, ADR-096)가
이 배포로 닫혔다.

### 다음 한 작업

**T-VN-41S build 예산/상한 결정은 닫혔다** — 예산 300초 유지, item 상한 500,000, 재료 상한
56 MiB(`docs/reports/t-vn-41s-budget-ceiling-2026-08-21.md`). 같은 조사에서 나온 도달 가능한
장애 둘(writer 무한 대기 → pool 고갈, build timeout의 1초 재시도 → duty-cycle wedge)도 함께
고쳤다.

**남은 숙제는 부하 아래 재측정이다.** 지금 수치는 전부 조용한 호스트 값이고, 이 저장소가
가진 유일한 동시 부하 관측(2.32배)을 적용하면 상한 크기 build가 예산의 91.5%를 쓴다.
안전계수 2가 그 한 점에 거의 정확히 소진되므로, 부하를 건 재측정으로 계수를 다시 판단해야
한다. 그 전까지는 byte 축을 따로 조여 폭 축 여유를 확보해 뒀다.
## 2026-08-21 — `0230` 대리키 하드코딩으로 prod 배포 중단 → 자연키로 수정

`0229`+`0230`+`0231` 묶음 배포가 `0230_tvn_c05_krforest_datasets`에서 멈췄다.
`provider_dataset_id 73`을 prod가 이미 `python-datagokr-api/standard_special_streets`에
배정해 뒀는데 migration이 그 번호를 `krforest_wildfire_risk_forecast`로 적어 뒀다.
alembic이 전체를 한 transaction으로 감싸므로 30회 재시도가 매번 전량 롤백됐다.
그 시점 prod는 `0225`로 롤백돼 배포 전 상태 그대로였다(head·`curated` 35행·container
health 확인). **재배포는 2026-08-21에 끝났다 — 아래 최상단 항목 참조.**

`provider_dataset_id`는 `Identity(always=True)` 대리키이고 catalog identity의 정본은
자연키 `(provider, dataset_key)`다. baseline seed(69번)와 prod(73번)의 번호 배치가 애초에
갈려 있었으므로 대리키를 계약에 적은 것 자체가 결함이다. CI가 늘 초록이었던 이유도
같다 — 통합 테스트 DB는 `0200`이 `seed.sql`을 실행해 C05가 이미 70~74로 서 있는 DB만
봤고, 거기서 이 migration은 순수 no-op이다.

`fix/tvn-c05-natural-key-catalog`에서 자연키 기준으로 다시 썼고(dataset은 sequence가
번호를 매기고 operation·scope는 자연키 JOIN으로 되찾는다), `_SEQUENCE_SQL`을 INSERT 앞으로
옮겼으며(적대적 리뷰어 2명이 독립 지적), 사후 단언 4가지와 재발 방지 lint를 세웠다.

prod 덤프 사본(features 1,008,852까지 완전 일치)에서 `0225→0229→0230→0231`이 30초에
통과했고 fail-closed runtime ACL 조정도 exit 0이었다. C05는 **104~108**을 받았고 73번
선점자는 자식 0으로 무사, sequence는 103→108로 전진만 했다.

**끝났다.** PR #1042가 머지돼 main HEAD = `e47a389f`이고, `0229`·`0230`·`0231`·`0232`가
2026-08-21 한 배포로 prod에 올라갔다(prod head = `0232_tvn37d_notice_empty_range`).
상세는 이 문서 최상단 배포 항목에 있다.
## 2026-08-21 — M04 shared-cluster role graph CI 보정

다른 database의 M04 request role이 legacy DB bootstrap의 base-role exact graph에 섞이던
PostGIS CI 실패를 고쳤다. M04 role은 M01/M05 role과 같이 legacy 비교에서 제외하고 전용
role phase에서만 검증한다. Docker runtime unit과 existing-object bootstrap integration은
`159 passed`다.

### 다음 한 작업

이 보정을 최신 `origin/main`에 rebase·push한 뒤 Map PostGIS CI를 다시 확인한다. Map과 PinVi
CI가 모두 green이고 N150 격리 mutating browser E2E가 끝나기 전에는 M05 activation receipt와
Hallmark 작업을 시작하지 않는다.
## 2026-08-21 — M05 이후 통합 migration CI fixture 정합화

M01~M05 배포 choreography를 반영해 기존 PostGIS 통합 fixture의 shared-database 순서 결합을
제거했다. Alembic test는 전용 database에서 실행하고, T-VN34/T-VN34C provider 초기 생성은
직접 executor role 전환 대신 deployable Dagster runtime의 inherited executor 권한을 쓴다.
M01 role이 같은 cluster의 다른 database에만 남은 정상 재시작도 bootstrap이 legacy base sweep을
완료하며, 이 database가 0226 이후 partial 상태인 경우는 여전히 중단한다. 표적 integration은
24 passed 및 21 passed·6 skipped다.

### 다음 한 작업

이 test-only 보정을 최신 `origin/main`에 다시 rebase·push하고 Map CI를 확인한다. 그 뒤 CI
green과 N150 격리 mutating browser E2E가 모두 확인되기 전에는 M05 activation receipt와 Hallmark
작업을 시작하지 않는다.
## 2026-08-21 — M05 contract receipt와 fresh bootstrap 보정

Map service/admin OpenAPI의 M05 변경을 PinVi가 이미 vendor한 exact bytes와 재결박해 contract
freeze CI를 복구했다. 또한 fresh Compose에서 role bootstrap의 PostgreSQL TCP accept 경쟁을 30초
bounded probe로 흡수한다. Map/PinVi의 표적 unit·integration은 통과했지만, N150 격리 host의 SSH가
응답하지 않아 실제 mutating browser evidence는 아직 생성하지 않았다.

### 다음 한 작업

N150 접근이 회복되면 현재 Map/PinVi draft head로 격리 stack을 다시 기동하고 M04 request 승인 →
M05 subscription/decision → PinVi reference rebind 및 ACK를 browser E2E로 증명한다. 이 증거와
CI green 전에는 M05 activation receipt와 Hallmark 작업을 시작하지 않는다.
## 2026-08-21 — T-VN-M05 `0235` forward repair 재심 보정

M05는 아직 activation하지 않는다. `0234` preview의 reader owner와 v1 admin EXECUTE가 남는 실제
forward-upgrade/ACL 결함을 `0235`와 runtime/bootstrap repair에서 닫았다. reader를 기존 dedicated
owner로 재선언할 때만 임시 schema `CREATE`를 주고 곧 회수하므로 fresh DB와 post-0234 preview가
같은 forward path를 쓴다. subscription 최초 생성은 absence race를 transaction advisory lock으로
직렬화해 두 동시 command가 각각 `provisioned`/`already_provisioned`로 종료한다. stale 및 existing
subscription 409은 terminal receipt의 `application/problem+json`을 replay에도 보존한다.
Problem receipt는 top-level `request_id`를 replay header의 fallback source로 사용하므로 최초 body와
`X-Request-ID`가 동일하게 남는다.

### 다음 한 작업

이 exact Map commit을 최신 `origin/main` 위로 rebase·push하고 DB/HTTP 전문 적대 리뷰어 두 명의
최종 판정을 받는다. 이후 PinVi exact OpenAPI vendor·consumer/UI, isolated mutating UI E2E와
`pg_restore --no-owner --no-privileges` drill을 모두 통과하기 전까지 activation receipt는 만들지
않는다.

DB 재심의 추가 P0도 반영했다. no-owner restore의 legacy ownership sweep이 schema owner로
되돌린 reader는 `0235`가 dedicated owner로 정규화한 후 재정의하고, reader가 아직 없는 fresh
0234와 이미 dedicated owner인 preview도 그대로 통과한다. temporary schema 권한은 `USAGE`와
`CREATE`를 함께 회수한다. legacy membership oracle은 M05 전용 네 edge를 별도 phase로 취급해
rebootstrap이 migration 전에 실패하지 않게 했다.
## 2026-08-21 — T-VN-M05 Map admin 판단·service delivery contract

M05 Map 쪽 admin case 목록/상세/판정과 reconciliation service lease/ACK contract를 완성했다.
이미 적용 가능한 `0234` evidence revision은 바꾸지 않고, reader·subscription provisioning·ACK common
lease lock은 forward-only `0235_m05_reconciliation_delivery`로 분리했다. subscription은 AdminBFF
domain-command receipt의 fixed principal·immutable `initial_event_sequence=0`으로만 만들 수 있다.
이 activation receipt가 없으면 어떤 M05 decision도 확정하지 않고 503으로 멈춘다.
admin은 raw evidence relation을 읽지 않고 전용 SECURITY DEFINER reader만 호출한다. list는 stable
keyset page, detail은 immutable evidence와 subscription별 unacked 상태, decision은 provider-only
survivor·expected fingerprint/revision·reason을 모두 다시 대조한다. `kept`는 AdminBFF만,
`merged`/`manual_retired`는 DB session 생성 전 body-based destructive flag까지 통과해야 한다.
stale 409도 domain command terminal receipt로 commit해 같은 key를 안전하게 replay한다.

service event는 stored canonical envelope와 hash를 live Feature join 없이 그대로 돌려주며, event가
없으면 204, 다른 worker의 live lease면 409이다. ACK은 idempotency key lock과 principal lease
row lock을 함께 보유해 new-key semantic replay 경쟁에서도 claim-only command를 남기지 않는다.
read/ACK digest는 all-or-nothing으로 설정되고 executor/ACL/catalog marker에 각각 결박됐다.
full/service OpenAPI export와 route/command policy, API unit 및 fresh PostGIS migration을 확인했다.

### 다음 한 작업

동일 Map commit을 두 전문 적대 리뷰어에게 재검토시키고 결과를 반영한다. 이어 PinVi가 exact
service OpenAPI를 vendor하여 durable delivery receipt/blocked impact/UI를 구현하고, isolated
Map+PinVi mutating UI E2E와 restore/ACL drill을 통과하기 전에는 M05 activation receipt를 계속
만들지 않는다.
## 2026-08-21 — T-VN-M05 Map service lease/ACK 경계

M05 service 정본의 `GET /v1/service/feature-reference-reconciliations`와
`POST /v1/service/feature-reference-reconciliations/{event_id}/acks`를 구현했다.
read/ACK token digest와 DB executor를 분리했고, runtime은 M05 evidence table을 직접
읽거나 쓰지 않는다. ACK은 기존 receipt의 exact hash를 SECURITY DEFINER preflight로
**domain command claim 전에** 확인한다. 따라서 응답 유실 뒤 다른 `Idempotency-Key`로
같은 ACK을 보내도 새 claim-only command가 생기지 않으며, 200 replay receipt만 돌려준다.
fresh M05 migration integration, route policy/OpenAPI/command registry, strict mypy와 ruff를
표적으로 확인했다.

### 다음 한 작업

Map admin case 목록·상세·결정 contract와 destructive decision preclaim gate를 만든 뒤,
정확한 Map OpenAPI SHA를 PinVi consumer/UI vendor에 결박한다. M05 활성화와 mutating live
E2E는 그 paired 구현이 모두 끝날 때까지 금지한다.
## 2026-08-21 — T-VN-M05 paired manual/provider dedup 설계

사용자가 paired cutover를 선택했다. M05는 generic dedup 큐나 auto master/merge를 확장하지
않고, 수동 origin과 provider source head를 함께 freeze한 append-only case/resolution/effect
evidence로 구현한다. Map decision은 provider survivor만 명시적으로 허용하며, external reference
rebind/detach는 generic service event와 principal ack로 전파한다.

ADR-097 및 [M05 설계](../reports/t-vn-m05-manual-provider-dedup-design-2026-08-21.md)를 accepted로
확정했고, DB/HTTP 전문 적대 리뷰어 둘이 P0 보완본을 GO로 재검토했다. `0234`의 불변
증적·subscription·lease model/migration과 runtime raw-access deny inventory까지 구현했으며,
fresh migration Alembic check 1건과 ruff/strict mypy가 green이다. `0233 → role 전용 → 0234 →
사후 복구` compose/DB helper도 연결해 frozen baseline을 건드리지 않은 role choreography를
고정했다. Dagster-only candidate writer는 manual origin/claim과 정확히 하나인 provider
primary source head를 freeze하고, admin-only writer는 `kept`/manual retire+`rebind`/manual
retire+`detach`를 global fence 안에서 append-only resolution/event로 만든다. service writer는
cursor 다음의 실제 최소 sequence를 worker lease/epoch으로 독점하고 exact event hash와 local
receipt hash를 strict-prefix ack로 결박한다. 실제 runtime login integration에서 executor 차단,
candidate replay, merged lifecycle/event·source link 보존, 경쟁 lease, ack/replay와 API/Dagster
catalog preflight를 검증했다. event hash는 UTC `occurred_at`까지 포함한 canonical envelope 전체를
고정한다. backup manifest v3는 case·resolution·event·ack·subscription root를 같은 snapshot에
고정하며, restore verifier는 envelope/관계형 행 hash와 연속 prefix를 다시 대조한 뒤 worker lease를 무효화하고 cursor를
재구성한다. v3 staging restore는 root 전에 base/M01/M05 ownership·ACL repair와 API/Dagster catalog
preflight까지 실행한다.

### 다음 한 작업

Map admin/service contract와 첫 consumer의 durable reference receipt/rebind, exact vendor를
같은 paired release로 구현한다.
## 2026-08-21 — T-VN-37D 두 번째 리뷰 P2 반영

두 번째 전문 reviewer가 발견한 curation candidate timestamp의 세션 timezone 의존성을
해소했다. notice detail의 `valid_start_time`/`valid_end_time`을 KST 고정 JSON으로
직렬화하고 UTC·Asia/Seoul 세션 동일성 회귀를 추가했으며, targeted integration 2건이
통과했다. 두 reviewer 모두 P0/P1 없음, GO로 최종 재검토를 완료했다.

### 다음 한 작업

최신 수정본을 리베이스·보안 감사 후 push하고 PR #1041의 Python matrix와 필요한 live UI
인수 증거를 확인한다. 모든 required check와 review가 green일 때만 merge한다.
## 2026-08-21 — T-VN-37D 적대 리뷰 findings 반영

전문 reviewer 2명 모두 P0 없이 검토를 완료했다. `valid_during`의 stored-column 잠금
위험에는 migration-local 30초 `lock_timeout`과 writer fence/maintenance 전제를 추가했고,
admin curation candidate의 `to_jsonb(notice)` 내부 필드 누출 P1은 SQL에서 `valid_during`을
제외하도록 수정했다. NULL·one-sided·equal range, public/admin active read, candidate
detail shape 회귀를 추가했으며 수정 후 targeted integration 2건이 통과했다.
## 2026-08-21 — T-VN-37D notice empty range 구현

`feature.feature_notices.valid_during`을 `valid_start_time`/`valid_end_time`에서
파생하는 stored `tstzrange`로 추가했다. 정상 범위는 `[start, end)`, 미래 발효 전
철회(`end < start`)는 PostgreSQL `empty`로 표현하며, 두 시각이 모두 없으면 NULL이다.
미래 경고를 숨기지 않도록 공개·admin active read는 기존 `valid_end_time` 비교를
유지하고, `NoticeDetail`/OpenAPI 응답 계약은 바꾸지 않았다. ADR-095와 migration
`0232_tvn37d_notice_empty_range`를 추가했으며 integration regression을 작성했다.
## 2026-08-21 — 완료 task를 정본 원장으로 이관

`T-VN-H50`(PR #1036), `T-VN-C05A`~`C05D`(PR #1037),
`T-C7-BROWSER-EVIDENCE`·`T-C7-SCOPE-REGISTRY`·`T-C7-LIVE-SERIAL`·
`T-FE-MOCK-MANIFEST`(PR #1038)는 모두 머지되어 `tasks-done.md`로 이관했다.
`tasks.md`에는 `T-VN-40B` 잔여와 `T-FE-MOCK-FLAKE`를 포함한 미완료 실행 단위만 남겼다.
## 2026-08-20 — T-VN-41S material/receipt 분리 착지 (`0231`)

`T-VN-41S`의 후속 종료선에서 **EXPLAIN·1M soak을 뺀 전부**가 닫혔다.

| 바뀐 것 | 내용 |
|---|---|
| DB | `ops.poi_cache_target_snapshot_materials` / `..._material_items` 신설, `poi_cache_target_snapshots`는 receipt로 축소, legacy item 표 삭제 |
| identity | `(external_system, restore_epoch, material_high_watermark_relay_order)` · partial unique `WHERE compacted_at IS NULL` |
| 공유 | 재사용 질의 둘 → 하나. generic/reconciliation이 **양방향**으로 material을 공유하고 각자 receipt를 만든다 |
| service API | 재사용 시 `snapshot_id`가 달라진다(root/count/cursor는 같다). 만료를 물려받지 않아 매번 full TTL |
| compactor | hourly GC batch의 4단계 중 2·3단계. 보존 기본 30일. receipt/material row는 남긴다 |
| 410 | 도달 불가였던 것을 고쳤다 — compaction 판정이 만료 판정보다 앞선다 |
| ACL | `ops`를 `feature`와 같은 강도로. 침묵 full CRUD 경로 제거(표 57개 중 48개가 그 경로였다) |

**잡힌 것 셋.** (1) ACL 목록 게이트를 `Base.metadata`로 재서 green인 채 아무 것도 못 봤다 —
모델에 없는 ops 표가 17개 있었고 n150 리허설이 잡았다. (2) `410`이 도달 불가능했다 —
end-to-end 테스트를 쓰고서야 알았다. (3) 초안의 `safe_high_watermark_relay_order`를 뺀 것이
오판이었다 — 기존 테스트가 잡았고 되돌렸다.

**n150 1M soak 실측**(`docs/reports/t-vn-41s-1m-soak-2026-08-21.md`):

| 축 | 실측 |
|---|---|
| 1,000,000 admitted | **368.4초** (2,714 item/s; 동시 부하 아래 547.9초) |
| Python peak | **2.02 MiB** — `O(log N)` 주장이 상한에서 성립 |
| item 표 / 인덱스 | 157.6 MB (157.6 B/item) / 90.5 MB |
| 상한 + 1 | typed `413`, partial row **0** |
| compaction drain | 1,000,000행 / 39.5초 / 100 round |
| VACUUM 회수 | 157.6 MB → 57 KB (증거 material·receipt는 보존) |

게이트: ruff / mypy `--strict` ×3 / import-linter green, unit 2,387 · api 1,199 ·
dagster 548 passed, PostGIS 통합 49 + EXPLAIN, 격리 DB 리허설 12절 PASS,
ACL 변이 배터리 6종 전부 red.

### 다음 한 작업

**결정 하나가 남았다 — build 예산 300초 vs item 상한 1,000,000.** 상한과 같은 크기의
snapshot은 배포 기본 예산에 들지 않는다(실측 368.4초 > 300초). 지금 계약에서 그런 snapshot은
admission을 통과하고 build deadline에서 실패한다. 예산을 올리면 그 시간만큼 stream share
barrier가 유지되고 그 값은 hung writer 최대 정지 시간이기도 하므로, 코드가 아니라 정책
결정이다. 선택지 셋과 비용은 soak 보고서 §"열린 결정"과 `docs/tasks.md`에 있다.

그 결정 뒤에 #922와 T-VN-41S를 완료로 표시한다.
## 2026-08-20 — T-VN-C05A~D provider 머지 후 map 최종 게이트

`python-krforest-api` PR #9를 `4681bc7892239adc28aeeab19dba707aefb1dbde`로 머지했고,
map의 provider pin도 같은 SHA로 갱신했다. map 브랜치는 최신 `origin/main`에 재베이스했으며
현재 Alembic head 뒤에 C05 catalog migration `0230`을 두어 기존 `0229` 경로를 보존한다.
provider n150 debug UI 스모크와 data.go.kr live API 9건은 통과했고, 산림안전·산사태 2건은
현재 키 권한 범위의 서버 거부를 xfail로 확인했다. map 운영 UI도 n150 Playwright에서 인증 후
`/admin/features` heading/table과 검색·kind 필터를 확인했으며, 인증 후 non-GET 요청 0건으로
읽기 전용 live UI E2E를 통과했다.
첫 원격 Python matrix는 C05A~D 신규 handler 5개를 반영하지 않은 기존 registry count 33에서
실패했으며, 기대값을 38로 갱신해 재실행한다.

### 다음 한 작업

map CI 전체 green과 required review를 확인한 뒤 map PR을 merge한다.
## 2026-08-20 — T-VN-H50 마지막 planner 경로 보강

H50의 두 적대 리뷰어가 공통으로 재현한 `source_entities_pkey` false-fail을 수정했다.
`source_records`의 근거 약한 복합 unique 허용도 제거하고, relation별 모든 index scan이
allowlist 안에 있는지 검사하도록 gate를 좁혔다. forced/default plan, `Settings`, 작은
`provider_datasets` 예외의 cardinality bound는 유지한다. 로컬 대상 테스트 6회 연속과
모듈 전체 8건은 통과했고 GitHub Actions의 남은 3.12 job 완료를 기다린다.

### 당시 다음 한 작업

두 전문 리뷰어에게 H50 최종 재검토를 요청하고, GitHub Actions 전체 green 확인 후 H50
문서·PR을 갱신하고 merge한다.
## 2026-08-20 — T-VN-C05A~D 산림청 데이터 연결 완료

`python-krforest-api`에 C05A 중첩 SHP route와 C05B 산악기상, C05C 산불위험 V2,
C05D 산사태 예보발령 typed 모델을 구현하고, `kor-travel-map`에 순차적으로 직접 연결했다.
등산로·둘레길은 월 1회, 산악기상·산불위험·산사태는 KST 기준 하루 6회 schedule을 사용한다.
각 데이터셋은 Dagster resource/fetcher/asset, operation registry, fixture preview, baseline
provider dataset·scope까지 등록했다. 두 전문 리뷰어의 P1 지적을 반영해 typed API strict
mypy, 시군구 코드, source identity 충돌, body-level API key redaction을 보강했다.
최신 main의 기존 `0229`를 보존하면서 C05 catalog를 `0230`으로 `0229` 뒤에 연결했고,
asyncpg/identity 호환을 포함한 Alembic metadata integration 7건을 통과시켰다.

### 당시 다음 한 작업

두 PR의 CI·live UI E2E와 provider 병합을 확인한 뒤, 병합 SHA로 map provider pin을 갱신하고
map PR을 병합한다.
## 2026-08-20 — T-VN-M04 범용 Feature 요청 큐 구현·검증 완료

`0233_m04_feature_request_queue`가 service submit과 Map admin approve/reject를 generic
queue로 분리했다. `ops.feature_requests`는 immutable submit payload와 submission/resolution
command FK를 보존하고, approved Feature의 origin은 `manual_request`다. PinVi 고유 이름은
Map의 M04 식별자·경로·역할·환경변수에서 제거했다.

DB/HTTP 적대 리뷰에서 나온 P0/P1을 모두 반영했다: no-owner/no-privileges restore ACL
repair, raw queue access preflight, direct procedure payload validation, terminal 409·missing
404, OpenAPI response 선언, REST catalog 정본. M04 통합 3건과 관련 단위 195건은 green이다.
M04가 바꾼 admin/service OpenAPI baseline과 active consumer receipt는 새 source pair의
격리 paired live UI E2E 전까지 `pending`으로 유지한다.

### 당시 다음 한 작업

Map의 exact OpenAPI commit을 PinVi 최초 consumer branch에 vendor하고 direct Feature create를
generic request submit으로 cutover하는 구현은 #458과 #1029에서 병합됐다. 남은 paired request→approval
receipt와 M05 reconciliation activation은 `T-VN-41C`에서 진행한다.
## 2026-08-20 — T-VN-41F1D-E 저장소측 완료 (v4 퇴역 → v5/v7)

live runner 두 개의 신뢰 경계를 v4 compatible-pair manifest에서 v5 pinned runtime
manifest + v7 rebuild journal로 옮겼다. host attestation version 3 → 4.

| 바뀐 것 | 내용 |
|---|---|
| env | `E2E_C7_COMPATIBLE_PAIR_MANIFEST` → `E2E_C7_PINNED_RUNTIME_MANIFEST` + `E2E_C7_REBUILD_JOURNAL` |
| runtime role | 5 → **7** (PinVi web/dagster 추가, compose service env 2개 신설) |
| 추가 대조 | 세 schema head, pinset digest, journal phase/candidate/cancel probe |
| evidence | `pinned-runtime-generation.json` + `pinned-runtime-rebuild.json` 각각 digest 결박 |

적대 리뷰 2명이 둘 다 NO_GO를 냈고 전부 반영했다. 주요 지적:
host attestation version을 한쪽만 올려 admin lane이 실행 불가였던 것(그 결함을 내 테스트가
고정하고 있었다), image field 목록을 모듈 상수에서 파생시켜 항등식을 만든 것,
evidence manifest version을 안 올려 기존 archive가 있는 host에서 preflight가 죽는 것,
runner가 이미 측정하던 실제 Alembic head를 generation과 대조하지 않던 것.
ADR-094 추가 + ADR-076/079 superseded.

게이트: ruff / mypy ×3 / lint-imports green, n150 unit+lint **2,394 passed**
(남은 10건은 main에서도 같은 `test_docker_dagster_runtime` 환경 실패). 변이 배터리
3회(8종·4종·7종) 전부 red — 그 중 두 번은 "게이트만 넣고 검증은 안 붙인" 상태를 잡았다.

### 다음 한 작업

`T-VN-FINAL-REBUILD` 배리어 앞의 개발을 계속한다. F1D-E의 n150 실행은 v5/v7 문서가
생겨야 가능하다(root 홈에 2026-08-06 리허설 세대가 남아 있으나 head가 달라
재사용할 수 없다 — 현 세대 문서는 파괴적 rebuild가 만든다).

주의: v5/v7은 `require_rebuildable_mode` 아래에서만 생성되고(n150은 rehearsal/
rebuildable로 해당), runner에는 **root 소유 0600 사본**을 건네야 한다.
## 2026-08-20 — #995 접어넣기 + C7 두 항목 종결

`#995`가 v5/v7 attestation을 이미 구현하고 있었다(내 중복 착수). 정본은 #1032(ADR-094)로
두고 supersede했으며, 남은 고유 가치를 main 위에 이식했다.

| 무엇 | 결과 |
|---|---|
| C7 cleanup 소유권 결박 | journal v3 → **v4**(`request_ownership`). 발견 루프가 dataset의 active를 무조건 채택하던 것을 소유 삼중이 맞을 때만 채택하도록, 취소는 소유를 말할 수 없으면 포기하도록 |
| 교차 경계 파손 | `run-c7-prod-live-e2e.sh`가 최종 journal을 `version != 3`으로 거부 → v4 + `request_ownership` 요구로, 계약 단언도 신설 |
| `T-C7-LIVE-SERIAL` | cross-worker `mkdir` 잠금(`_ops-c7-exact-scope-lock.ts`) + write 3종 결선. read-only preflight는 근거를 남기고 제외 |
| `T-C7-SCOPE-REGISTRY` | `integration-map.md` §3.7 + ADR-088 결과 |

### 다음 한 작업

`T-VN-41S` 후속 — `0227+` 정규화 migration, 양방향 material 공유, terminal compactor,
repository 410, n150 1M soak. 이것이 migration head를 올리므로 `T-VN-FINAL-REBUILD`
배리어보다 반드시 먼저 온다.
## 2026-08-20 — T-VN-34C fresh-live runner와 M01 credential 계약 정렬

최신 `origin/main`의 PR [#1028](https://github.com/digitie/kor-travel-map/pull/1028), merge
`021b20fc`가 T-VN-M01 foundation과 T-VN-34C 격리 fresh-live runner의 환경변수 계약을
맞췄다. runner가 raw token(UI 전용), API digest, manual-create off flag를 함께 생성하고,
`docker-compose.yml`의 모든 `:?` 필수 환경변수와 runner `map.env`의 집합 차이를 정적 테스트로
검사한다. raw/digest가 서로 다른 값으로 배선되거나 새 compose 필수값이 runner에서 빠지면
컨테이너 기동 전에 실패하도록 경계를 고정했다.

이는 runner preflight 보강이지 M01 완료나 route 활성화가 아니다. 현재 application migration
head는 `0225_tvn40c_physical_removal`이고, M01의 `0226_m01_manual_feature_create` DB/ACL/
backup tranche와 실제 route 활성화는 아직 남아 있다.

### 다음 한 작업

`T-VN-M01`의 `0226` forward-only migration·ACL·backup tranche를 구현·검증한다. 그 뒤에도
`T-VN-41S`·C05 provider dataset·H34 잔여가 `T-VN-FINAL-REBUILD` 배리어를 유지하며,
파괴적 rebuild와 D1/D2/final C7 live는 주요 개발 완료 뒤에만 실행한다.
## 2026-08-20 — 파괴적 재구축을 배리어로 분리 (`T-VN-FINAL-REBUILD` 신설)

사용자 결정: `T-VN-41F1D-D1`의 파괴적 rebuild(`ktdctl pinvi-pair rebuild-pinned --confirm` —
Map application·Map Dagster·PinVi 세 DB 재생성 + 일곱 runtime 재기동 + 전량 ETL 재적재)는
**모든 주요 개발이 끝난 뒤에** 실행한다. 실행 시점과 선행조건을 새 task
`T-VN-FINAL-REBUILD`가 소유하고, D1 → D2 → `T-VN-41C` receipt 승격을 그 뒤에 매단다.

배리어 해제 조건은 사람 판단이 아니라 **"세대를 낡게 만드는 변경이 남았는가"** 셋으로 판정한다 —
migration head를 올리는 열린 task(B1), service/user OpenAPI 정본을 바꾸는 열린 task(B2),
일곱 image 중 하나라도 바꾸는 열린 task(B3). v5 generation이 Map/PinVi source revision과
일곱 image ID에 결박되므로, 개발이 남은 채 실행하면 다음 머지 즉시 증거가 무효가 되고
전량 재적재 비용만 반복된다.

### 다음 한 작업

배리어 앞에 남은 개발을 진행한다. 우선순위 후보:
`T-VN-41S`(ACL 방침 결정 후 `0227+` migration/compactor·n150 1M 검증),
`T-VN-M01`~`M05`(수동 Feature 생성 lane), `T-VN-C05A`~`C05D`(provider dataset),
`T-VN-H34` 잔여. 진행 중인 `T-VN-41F1D-E`(v5/v7 attestation 전환)는 저장소측이 끝났고
live 실행만 배리어 뒤에 남는다.
## 2026-08-20 — T-VN-41C GC 축 종결

cache-target snapshot GC의 실측 AC를 n150 격리 DB에서 6개 축 전부 통과시켰다
(`docs/reports/t-vn-41c-cache-target-gc-verification-2026-08-20.md`). 절차는
`scripts/verify-tvn41c-cache-target-gc.sh`로 재실행 가능하게 고정했다.

| 축 | 결과 |
|---|---|
| migration | fresh DB → head `0225_tvn40c_physical_removal` |
| 수동 GC | 적격 56/2,800 전부 삭제, 보존 대조군 24 불변, remaining 0 |
| 처리량 | 65,214 items/s vs 유입 12,951 items/s |
| schedule ON → tick | t+21초 run 생성 · t+26초 SUCCESS · backlog 0/0 |
| alert | 보존 ceiling·증가율 독립 발화, 기본값에서 침묵 |

### 다음 한 작업

T-VN-41C에 남은 것은 GC와 독립인 두 항목이다 — PinVi exact-pair receipt 전환
(`pending` → `candidate_verified` → `complete`)과 최종 prod gate·production consumer
enable. 앞의 것이 PinVi vendor PR 병합에 물려 있으므로 먼저 그 상태를 확인한다.

병행 가능: `T-VN-41S` ACL 방침 결정 후 `0227+`, `T-FE-MOCK-MANIFEST`,
`T-C7-SCOPE-REGISTRY`, `T-C7-LIVE-SERIAL`.
## 2026-08-20 — T-VN-40C 완료: 머지 4건 + prod 0225 적용

T-VN-40C가 코드·계약·문서·prod DB까지 모두 닫혔다.

| 대상 | 커밋 |
|------|------|
| ktm#1023 T-VN-40C 물리 제거(`0225`) | `4c50fe86` |
| pinvi#459 P7 user spec 재-vendor | `07340d9e` |
| ktm#1016 T-VN-M01 foundation | `14792385` |
| ktm#1024 receipt `complete` 봉인 | `294db534` |

removal manifest의 `verification` 9항이 모두 닫혔고, prod는 head
`0225_tvn40c_physical_removal`로 올라가 legacy zero 3항·보존 6항·API 표면 smoke를
통과했다. 복구점은 `~/backups/kor_travel_map_0224_c7_external_system_scope_pre0225_*.dump`
(615MB, sha256 검증).

### 다음 한 작업

`T-VN-M01` 후속 — `0226_m01_manual_feature_create`로 DB/ACL/backup tranche와 route 활성화를
진행한다. prod에는 이미 manual-create 자격증명이 배선돼 있고 flag는 `false`다
(raw는 UI만, digest는 API만; digest sha8 `dba1d833`).

병행 가능: 백로그 `T-FE-MOCK-MANIFEST`(mocked e2e checkpoint manifest의 `discoveredTests`가
실측 276과 어긋남 — 40C가 만든 drift 아님), `T-C7-SCOPE-REGISTRY`, `T-C7-LIVE-SERIAL`,
T-VN-41 최종 C7 인수.
## 2026-08-20 — T-VN-40C legacy overlay 물리 제거 (당시 머지 대기 → 완료)

`0225`가 legacy `curated_features` overlay·snapshot 표·trigger·`legacy_projection_id`·
rekey 예외·legacy ACL을 지운다. API 라우트 13개, admin UI 라우트 2개와 read hook,
dead symbol 20개를 함께 제거했고, 삭제한 테스트에 섞여 있던 legacy와 무관한 검사 9개는
새 모듈로 복구했다. 정적 zero gate와 post-removal runtime 검증을 저장소 안 테스트로
고정하고 변이 6종으로 red를 확인했다.

게이트: ruff / mypy ×3 / import-linter green, pytest **4,435 passed**(unit+lint+api
3,436 · integration 999), frontend CI-parity 13단계 green, mocked e2e **276/276
passed**(7.2분, flake 0). 남은 실패 6건은 n150 환경(PG_DSN·geo 키)이고 main에서도 같다.
mocked checkpoint gate는 manifest의 `discoveredTests: 284`가 실측 276과 어긋나 red인데,
`origin/main`에서도 276이라 40C가 만든 drift가 아니다(백로그 `T-FE-MOCK-MANIFEST`).

### 당시 다음 한 작업

PR [#1023](https://github.com/digitie/kor-travel-map/pull/1023)의 CI green 확인 후
머지. 머지 순서에 **의존이 있다**:

1. **#1023(40C, `0225`) 먼저.** `0226`을 쓰는 #1016은 그 뒤이며, 40C가
   `map_full_openapi_sha256`/`map_user_openapi_sha256`를 바꿨으므로 #1016은 재-pin이
   필요하다.
2. **머지 직후 P7 PinVi lockstep.** `apps/api/tests/contract/kor-travel-map-openapi-user.json`을
   재-vendor하고(sha `6a2ee0f9…` → `489b05d3…`), `test_kor_travel_map_contract.py`의
   `_UPSTREAM_COMMIT`과 `contracts/kor-travel-map-service-provenance-v1.json`의
   `map_release_revision`을 40C 머지 SHA로 올린 뒤 paired receipt를 돌린다. 그 다음
   Map 쪽 `consumer-rollout-v1.json`의 T-VN-40 `pinvi_snapshot_receipt.state`를
   `complete`로 바꾼다. service spec은 무변경이라 재-vendor 대상이 아니다.
3. PR #1022(T-VN-40 receipt)는 merge `82b4d1da`로 이미 들어갔다. 이 branch는 그 위로
   리베이스했고, 40C가 spec을 바꿨으므로 receipt를 `pending`으로 되돌렸다 — 2번이
   그것을 다시 `complete`로 만드는 단계다.
## 2026-08-20 — T-VN-40 인수 ③ 완료, receipt 봉인 (pair: Map `f00e7f48` · PinVi `5cad141a`)

C7 prod live가 `f00e7f48`에서 `RESULT: GREEN`(6 spec 17 case, orchestrator_verified,
BLOCKED 없음, 실행 뒤 audit rc=0)으로 끝났고, T-VN-40 receipt를 `complete`로 봉인했다.

> **후속(2026-08-20)**: 여기서 봉인한 `complete`는 T-VN-40C가 `openapi.user.json`을
> 바꾸면서 이 트리의 spec을 더 이상 서술하지 않게 됐다. 40C branch가 receipt를
> `pending`으로 되돌리고 세 sha를 재핀했다 — 위 §"T-VN-40C" 항목의 P7 lockstep 참조.
> 이 항목이 예고한 ⑤는 그 branch에서 실행됐다.

병행 가능한 것: T-VN-41 최종 C7 인수(receipt가 `candidate_verified`이고 candidate
증적이 non-ancestor 커밋에 묶여 있다), 백로그 `T-C7-SCOPE-REGISTRY`(external_system
선언 규약 정본화)·`T-C7-LIVE-SERIAL`(직렬 실행을 코드로 보장).
## 2026-08-19 — T-VN-H45 Alembic 1.19 CHECK 비교 적응 완료

Alembic 1.19.1 fresh DB에서 named CHECK removed 208건 / added 167건을 재현한 뒤,
plugin을 끄지 않고 DB catalog와 ORM CHECK 373개의 이름을 정확히 맞췄다. 혼합 naming
convention, PostgreSQL 63-byte 절단 이름, raw SQL migration에만 있던 43개 CHECK를
metadata에 반영했다. 이 대조 과정에서 `curation_rule_reconcile` revision CHECK가
후속 migration보다 뒤처진 실제 식 drift 1건도 찾아 DB 정본에 맞췄다.

Alembic은 `>=1.19.1,<1.20`으로 올렸다. fresh `upgrade head → alembic check`와 함께,
ORM CHECK를 PostgreSQL 임시 table에 설치해 `pg_get_constraintdef` 기준으로 live 식과
비교하는 의미 gate를 추가했다. 로컬 게이트는 ruff, mypy 145 files, import-linter
4 contracts와 전체 pytest **3,369 passed / 12 skipped**가 green이다.

### 다음 한 작업

PR [#1019](https://github.com/digitie/kor-travel-map/pull/1019)은 CI 8/8 green 뒤
merge `82fbe2f6`로 완료됐다. 다음 작업은 `T-VN-C05A` 산림청 등산로·둘레길 route
구현이다.
## 2026-08-19 — T-VN-C03 보조 dataset 제품·source 결정 완료

provider exact pin과 공공데이터포털 현행 계약을 대조해 C03을 닫았다. 산림청 route는
`PBD0000041` 등산로와 `PBD0000031` 둘레길을 서로 다른 dataset으로 구현한다. 산악기상은
`15084696`, 산불위험은 현행 V2 `15084817`을 `WeatherValue` source로 채택했다. 광범위한
`krforest_safety_notices` 대신 발령·해제가 명시된 `15074798` 산사태 예보발령만 notice로
채택했다. 구현은 `T-VN-C05A`~`C05D`로 분리했다.

KHOA exact pin의 46개 ODMI catalog에는 공지 사건 API나 typed notice model이 없다.
해양 지수·관측값을 임의 threshold로 notice화하지 않으며 `khoa_coastal_notices` 계획을
미구현 폐기했다.

### 다음 한 작업

`T-VN-C05A`를 먼저 구현한다. 두 forest.go.kr ZIP의 live census로 geometry 유형·안정
자연키·중복을 봉인한 뒤 route 변환, Dagster dataset operation, fixture와 통합 적재를 잇는다.
## 2026-08-19 — tasks 전면 감사·H44 종결·C02/H18 폐기

`tasks-rule.md`의 블록 단위 라우팅과 `origin/main`, 연결된 PR·이슈 상태를
재대조했다. H44는 `0083`·`0104` 복원 실증으로 핵심 AC를 충족했으며,
월 1회 트리거는 현 n150 정책상 H43/manager #148의 실 production 전환 조건이므로
H44를 더 이상 열어두지 않고 완료 이관했다. 닫힌 PinVi #215, T-VN-40A·mapping·
인수 ①/②, #975에서 완료한 41A/41B, H45 후속 ①~④, C03 provider 표 drift도
`tasks-done.md`로 이관했다. C02 arm64 실배포 검증과 H18 approval provenance 자동
강제는 2026-08-19 사용자 결정에 따라 미구현 폐기로 아카이브했다.

H45의 유일 잔여는 Alembic 1.19 CHECK 비교 적응이다. 1.19.1 fresh DB에서
removed 208/added 167을 재현했으므로 즉시 착수는 가능하지만, ORM/DB CHECK 이름
전수 정렬과 의미 drift 가드 보존이 필요한 독립 PR 규모다. C03은 trail만 typed
geometry upstream이 명확하고, mountain weather/fire risk는 승인·RawRecord 계약,
safety notice는 source semantics, KHOA coastal notice는 upstream 부재 결정이 먼저다.

### 다음 한 작업

이 문서 전용 PR을 원격에 열고 CI가 모두 green인지 확인한 뒤 병합하지 않고
사용자 지시를 기다린다. 이 PR에 H45 코드 적응이나 C03 dataset 구현을 섞지 않는다.
## 2026-08-19 — T-VN-M01 구현 진행: API/ORM foundation + PinVi fail-close

M01을 PR #1012 merge `ac77a7d1` 위에서 시작했다. Map에는 생성 전용 이중 인증·기본 off flag,
`admin.feature.create.manual-v1`, READ COMMITTED, caller identity/state 제거, UUIDv7 server identity,
exact duplicate typed result, 201 UUID/ETag/Location/replay foundation과 claim/origin ORM을 구현 중이다.
전문 리뷰 2인은 P0 0건으로 판정했고, 공통 P1인 DB 오류 422/409/500 분류와 raw 진단 비노출,
trusted wrapper/receipt 불변 검증을 반영했다. API 경계의 local-dev 인증 우회 차단, 안정
`errors[].field`, POST 전용 strict coord, literal replay bytes도 첫 checkpoint 테스트로 고정했다.

PinVi paired draft PR [#458](https://github.com/digitie/pinvi/pull/458)은 direct `new_place` create를
제거하고 queue 준비 전 503/pending fail-close를 고정했다(대상 테스트 127건, Ruff/mypy 통과).

### 다음 한 작업

첫 Map foundation checkpoint를 draft PR로 push한 뒤 Admin UI BFF/form을 같은 PR의 후속 commit으로 붙인다.
(2026-08-20 후속: `0225`는 착지·prod 적용 완료로 이 barrier는 풀렸다. M01 후속은 `0226`,
T-VN-41S 후속은 `0227+`다.) 당시 기준으로는 — 실제 `0225` T-VN-40C migration이 main에
착지하기 전에는 `0226` DB/ACL/backup/vNext tranche를 만들지
않는다. ADR-093 accepted 전환과 T-VN-M01 완료 이관은 그 migration 및 실제 PostgreSQL concurrency/restore
검증 뒤에만 수행한다.
## 2026-08-19 — T-VN-M00 수동 Feature 생성 설계·전문 리뷰 완료

provider가 만들지 않는 장소를 admin/API로 생성하기 위한 M00 2차 설계를 완료했다. M01은 admin BFF
생성 전용 credential, 서버 UUIDv7, exact identity claim과 `manual_admin` origin의 별도 append-only
relation, 고정 `active/published/valid`, 명시적 READ COMMITTED, current→target bridge,
forward-only migration·backup/restore·ACL·오류/freeze gate를 한 clean cutover로 구현해야 한다.
fuzzy/provider 중복은 M05로 남기며 과거 PinVi/admin 공용 경계의 origin은 추정하지 않는다.

API 계약과 DB/동시성 전문 리뷰어는 네 차례 검토 끝에 같은 exact checkpoint
`2aa17c27d4f09701a9639ea0ea449abbfefc0be2`에 모두 P0~P3 0건 최종 GO를 선언했다. M00은
`tasks-done.md`로 이관했고 draft PR #1012를 유지한다. ADR-093은 M01 구현·계약 검증 전까지
proposed 상태다.

### 다음 한 작업

T-VN-M01을 별도 구현 작업으로 연다. migration/API/admin UI/OpenAPI/PinVi paired fence와 vNext
freeze를 설계 보고서의 단일 cutover 순서로 구현하고, ADR-093의 accepted 전환은 그 구현·계약 검증과
함께 한다. 이 M00 PR에는 M01 코드를 섞지 않는다.
## 2026-08-19 — C7 인수 ③ 진행: 계약 드리프트 4건 + 하네스 경합 1건

`025be0e6` → `db866351` → `dbba2ab6`로 prod를 올리며 strict runner를 돌렸고, 매번
다음 결함이 드러났다. 전부 **prod 실행에서만** 보이는 계급이다.

1. `provider_issues` 축 (#1010) — ADR-088 드리프트
2. dialog 자유입력 → canonical select + `external_system:c7-e2e` 선언 (#1011)
3. `matched_scope` 자연키 단언 (#1013) — 계약이 strip하는 필드를 단언하고 있었다
4. 삭제된 `/v1/ops/datasets/detail` 경로 대기 (#1013)
5. refetch 취소 경합 + 부족한 테스트 예산 (#1015)

부수적으로 드러난 둘이 더 중요하다. `assertOnlyKmaProviderObjects`가
`"provider" in record` 가드 때문에 **공허**해져 "KMA 외 provider 배제" 보장이 사라져
있었고, `test_c7_prod_live_runner_contract`가 계약이 아니라 **소비자 쪽 문자열을
고정**해 드리프트를 잡는 대신 얼려두고 있었다. 각각 canonical triple과 생산자 상수
기준으로 다시 세웠다.

### 다음 한 작업

#1015 머지 → prod 재배포 → capture/rebind → strict runner. `ops-c7-read-auth`는
prod 비-redact 재현에서 7/7이고, `ops-c7-kma-active-write`는 terminal history UI
직전까지 확인했다. 남은 미확인 구간은 그 이후와 kma-cap · kma-empty · schedule ·
poi-cache-targets 4개 spec이다.
## 2026-08-19 — C7 인수 재개: KMA live 3종이 ADR-088 계약과 어긋나 있었다

`025be0e6`(PR #1010)로 prod를 올려 strict runner를 돌리자 `ops-c7-read-auth`가 7/7로 통과했고
(#1010이 실제로 고쳤다), 실패가 `ops-c7-kma-active-write`로 옮겨갔다. 비-redact 재현 하네스로
근본원인을 확정했다 — dialog의 `provider` 자유입력을 60초 기다리다 죽는다.

원인은 UI가 아니라 **스펙이 stale**한 것이다. C7이 마지막으로 full green이던 `d5693269`(07-26)는
ADR-088(#966, 08-11) **이전**이고, ADR-088은 제출 가능한 `sync_scope`의 정본을
`provider_dataset_operation_scopes` 선언으로 못 박았다(`feature_update_repo`의 exact join +
request/job/sync-state/upload 4종 exact FK). 스펙은 여전히 run마다
`external_system:e2e-<run-id>`를 만들고 있었고 그건 선언될 수 없는 값이다.

`target_grids`로 바꾸지 않았다 — 그 scope는 "모든 활성 cache target + extra points"라 PinVi가
target을 등록하는 순간 인수가 운영 대상에 provider I/O를 내고 fingerprint가 비결정적이 되며,
`provider_sync_state`의 정본 cursor 행을 스케줄 job과 공유한다. 대신 migration
`0224_c7_external_system_scope`로 KMA 초단기실황에 `external_system:c7-e2e`를 선언하고, 스펙 3종이
그 값을 쓰되 run 격리는 기존 `target_key`가 맡는다. **T-VN-40C 예약 revision은 `0224`→`0225`로
재배정했다** — 40C의 선행조건 P1이 T-VN-40 receipt complete이고 그건 이 C7 인수 뒤에야 참이 되므로,
40C가 먼저 착지할 수 없다.

### 다음 한 작업

이 PR의 CI green → 머지 → prod 재배포(manager `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
`0224_c7_external_system_scope`로 올리고 소스 스냅샷 재취득 — 안 올리면 API entrypoint가 head
불일치로 fail-closed 정지한다) → `ktdctl pinvi-pair capture` → rebind → strict runner로 ③ 마무리.
## 2026-08-19 — T-VN-H46G buildx provenance 구현·전문 리뷰 완료

buildx 공통 경계에서 API·admin·Dagster web·daemon image 모두에 clean HEAD의 exact 40자 SHA를
build arg와 OCI `org.opencontainers.image.revision` label로 강제했다. 전문 적대 리뷰어 2명이
독립적으로 찾은 status 오류 fail-open과 context TOCTOU는 상태 검증 fail-close + exact commit
`git archive` context로 닫았다. 세 build가 같은 OCI 경로를 덮어쓰던 문제도 target별 archive로
분리했다. 재심에서 나온 구 OCI 단일 경로 변수 silent-ignore와 archive 생성 중 취소 누수는
각각 명시적 migration 오류와 signal-safe 단일 tar cleanup으로 닫았다. C6c/C7 runtime inspect
정본은 그대로 유지한다. 두 전문 리뷰어는 exact head `84349b4c`에 P0~P3 잔여 없이 GO했다.
로컬 root unit 2,300개, focused 15개, 실제 BuildKit tar-stdin 3종, Ruff·strict mypy 3패키지,
import-linter를 통과했고 열린 H46G는 `tasks-done.md`로 이관했다.

### 다음 한 작업

완료 이관 문서 commit의 GitHub 필수 CI가 모두 green인지 확인한 뒤 draft PR #1007을 ready로 바꾸고
병합한다. H46G 범위 밖의 prod rebuild/deploy는 이 PR에서 실행하지 않는다.
## 2026-08-19 — T-VN-40 인수 ② 완료 (pair: Map `817cfeae` · PinVi `5cad141a`)

S3(PinVi 재배포, alembic `0049→0059`) → S4(mapping receipt 봉인: root `69eb85ec…`, count 4424, items 4424)
→ S5(`ready=true`, backfill no-op) → S6(collection 59/59 import, POI 4,424) 전부 완료.
Map prod는 `817cfeae`, PinVi prod는 `5cad141a`로 정렬됐다.

### 다음 한 작업

**③ live/soak** — `docs/runbooks/c7-prod-live-e2e.md` 6개 완료 경계. 선행 2건:
(a) manager `ktdctl pinvi-pair capture`(런북 §2.1 step 8) — 브랜치 `feat/pinvi-pair-capture`가 리베이스·재검토를
    마쳤고 blocking 2건(frozen env 읽기가 핸들러 밖이라 fence 안내 없는 traceback / n150 state root 사실관계 오류)
    수정이 남았다. (b) 그 명령이 읽을 세 키(`E2E_C7_COMPATIBLE_PAIR_MANIFEST` 또는
    `KTDM_C6C_COMPATIBLE_PAIR_MANIFEST`, `KTDM_C7_MAP_SOURCE_CHECKOUT`, `KTDM_C7_PINVI_SOURCE_CHECKOUT`)를
    frozen `.env`에 넣는 프로비저닝(manifest 경로는 pinned-runtime state root 밖이어야 한다).
그 뒤 **④ receipt complete**(9키 exact + `blocking_reason` 삭제 + freeze 상수 갱신) → **⑤ 40C**.
## 2026-08-19 — T-VN-H46F admin UI geo proxy 완료·병합

- `/api/geo`는 server-only `KOR_TRAVEL_GEO_API_KEY`의 ASCII 영숫자 32자 발급 형식만
  신뢰하고 browser query key를 제거한 뒤 `X-KTG-API-Key` header로 전달한다.
- geo가 401 또는 400 `E0100 field=key`로 거부하면 원문 응답 대신
  `503 GEO_API_KEY_REJECTED`로 fail-close한다. public/VWorld alias는 proxy credential
  provenance에 참여하지 않는다.
- root Compose·frontend Dockerfile/build fingerprint·buildx·load-env·live/mocked E2E에서
  browser-global geo credential alias를 제거했다. root source → backend 동일 이름 / UI
  server-only alias의 service wiring만 남는다.
- Docker Manager PR #183이 충돌한 #173을 최신 C6c 구조에서 supersede해
  `4f5cbb44`로 병합됐다. Map은 admin redesign PR #1003 merge SHA 위로 재배치했으며
  독립 전문 적대 리뷰어 2명 GO, frontend unit 336개·Map 집중 37개·BFF route 14개와
  원격 CI 8개를 모두 통과한 뒤 PR #1004를 merge `817cfeae`로 병합했다.
- 완료 이력은 `tasks-done.md`로 이관했다. 남은 H46 계열 작업은 별도
  `T-VN-H46G`(buildx OCI commit provenance label)뿐이다.
## 2026-08-18 — T-VN-41S bounded snapshot 1차 구현, migration barrier

#922의 server cursor 2-pass capture, incremental Merkle v1, 1,000행 INSERT, item 1,000,000/512 MiB
admission, generic→reconciliation material 재사용과 relation/index/dead tuple/vacuum 관측을
`feat/tvn41s-snapshot-streaming`에 구현했다. 적대 리뷰에서 server cursor의 per-FETCH timeout이 전체
작업을 제한하지 않는 결함을 찾아 두 scan/모든 INSERT에 누적 5분 deadline을 추가했고, vacuum 관측불능
warning과 codegen 가능한 typed 410/413 details schema도 보강했다. 실제 PostgreSQL 1,005행 batch와 두 번째
scan timeout의 전량 rollback·동시 writer 회복 회귀를 추가했다.
새 service OpenAPI는 PinVi에 exact 재-vendor했지만 기존 후보 Live UI 증거와 source pair가 다르므로
T-VN-41 receipt는 `pending`이다. 과거 후보 artifact는 이력으로 보존하며 새 pair 검증에 재사용하지 않는다.

### 다음 한 작업

T-VN-40C가 예약한 Alembic `0225`(2026-08-19 재배정 — 아래 C7 항목)가 main에 착지할 때까지 migration은
만들지 않는다. 그 뒤 `0226+`로
receipt/material/item 정규화와 terminal retention compactor를 구현하고 실제 repository 410,
upgrade/downgrade·ACL/catalog·EXPLAIN, n150 1M DB streaming/concurrent mutation/compaction-vacuum soak를
통과한다. 번호 없는 DDL과 수용 matrix는
`docs/reports/t-vn-41s-snapshot-streaming-design-2026-08-18.md`가 잇는다.
## 2026-08-18 — T-VN-H45 후속 ①~③ 구현·provider 정본 병합

KHOA 시도×페이지와 KMA/DataGoKr/AirKorea 다건 호출에 비례형 공유 `RetryBudget`을 적용하고
WARNING을 Dagster event stream에 결선했다. 예외 본문은 로그에서 제거했다. upstream 정본은
python-kma-api #24(`0868b76`, quota/XML 계약)와 python-khoa-api #8(`20c7207`, HTTPS
`serviceKey`)로 병합했고 Map provider pin도 exact merge SHA로 올렸다. 독립 적대 재리뷰 2명은
신규 P0~P3 없음으로 provider GO, Map ①~③ 조건부 GO를 판정했다. Alembic 1.19 comparator를
전역 제외하는 초안은 실제 CHECK drift를 숨겨 철회했으므로 ⑤는 열린 barrier다.

### 다음 한 작업

H45 Map PR의 전체 게이트·CI를 통과시켜 머지한 뒤 T-VN-41S/#922 구현 커밋을 최신 main에
재배치하고 독립 적대 리뷰 2명·전체 테스트·PR 병합을 진행한다. H45 전체 완료 표시는 ⑤를
안전한 migration/check gate로 해결하기 전까지 금지한다.
## 2026-08-18 — T-VN-40 인수 ① 완료: prod head `0223`, mapping 4,424

precheck 전부 0 → 백업(`kor_travel_map_0104_pre-tvn40-1_20260818T082752Z.dump` + `.sha256`) →
`14ec2368` 스냅샷 배포 → `0104→0223` 단일 트랜잭션 성공(`total=4424 by_kind={'legacy_projection': 4424}`).
사후 확인 전부 통과, 4 서비스 healthy. 절차·선행조건 2개(DB role bootstrap, PinVi token pair)는
`docs/deploy.md` §T-VN-40 prod 배포에 있다. 배포 중 드러난 Map 결함(빈 digest env → 기동 거부)은
`fix/api-settings-empty-pinvi-digest`로 수정 중(적대 리뷰 2명 진행).

### 다음 한 작업

**② mapping 소비 — Map은 mutation 없음, PinVi 재배포가 관문이다**(2026-08-18 조사로 범위 정정).
prod legacy 4,424가 전부 `curated`/bucket B라 Map 쪽 import·archive 대상이 0건이고, admin CSV import를
돌리면 오히려 0223이 동결한 전제가 깨진다. 실제로 남은 것은 (1) PinVi prod 재배포(현재 image `3b87c19c`는
T-VN-40 소비자 코드가 없고 DB head가 `20260804_0049`) → (2) mapping receipt 봉인(root `69eb85ec…`,
count 4424) → (3) legacy-preflight `ready=true` 기록(backfill은 plan 0행이라 no-op) → (4) canonical collection 59개를
PinVi notice plan으로 import(2026-08-18 사용자 결정). 그다음 ③ soak/live e2e → ④ receipt complete
(선행: PinVi user spec 재-vendor = PinVi PR #451) → ⑤ 40C 구현 PR + `0225`.

③ 착수 전 결정 하나가 남아 있다: 런북 `c7-prod-live-e2e.md` §2.1 step 8이 부르는
`ktdctl pinvi-pair capture --verified-compatible --build`가 **docker-manager CLI에 없다**(문서에만 남아 있고
실체는 `rebuild-pinned` 하나뿐 — 그건 3 DB 파기형). manager에 capture를 되살리거나, 런북을 현행 sanctioned
경로(host `docker compose` 빌드 + image digest/revision 기록으로 compatible-pair manifest 동등물)로 고쳐 쓴다.
## 2026-08-18 — T-VN-40A fence(#994) 머지 → 다음은 40-mapping

#994는 main `3e0732b3`로 머지됐다(적대 리뷰 3라운드·2명 hold, CI 4 workflow green, n150 전체 통합
931 passed). 배포 선행 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`→ 그때의 head(0223 뒤로는 `0223_tvn40_identity_mappings`).

### 다음 한 작업

**T-VN-40-mapping 머지됨(#996 → `fbc31f2f`). 40C-manifest v2.2 초안·리뷰 완료(draft PR).** 다음은(physical removal
manifest·migration 사전 작성 — mapping 표는 삭제 대상 제외 + FK 처리) → ① 실행(precheck 스크립트 전부 0 →
`KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`=0223 → prod migration 0202~0223) → canonical import → soak/live e2e →
receipt → 40C 물리 삭제.
## 2026-08-18 — (이전) T-VN-40A fence(#994) 적대 리뷰 반영 완료, 머지 대기

fence 3층(ACL·static·route)에 더해 리뷰 P1이 드러낸 **merge의 runtime-role 결함**(fence 이전부터
`curation_collections` FOR UPDATE가 42501 — superuser 테스트만 있어 아무도 몰랐다)을 0222로 고쳤다.
P2 4건(inventory 전수·snapshot ACL+phantom 2개·spoof 422·admin write UI 제거) 반영. n150 게이트
전부 초록(ruff·mypy·lint 10·router 74·merge+runtime+ACL 통합 40·admin tsc/eslint/vitest 269).

### 다음 한 작업

#994를 draft 해제하고 CI 초록 뒤 머지한다. 머지 뒤 T-VN-40 인수 순서대로 **40-mapping**
(`ops.curation_cutover_identity_mappings` 적재 migration) → prod migration 0202~0222 → canonical
import(admin API preview→commit) → soak/live e2e(`docs/runbooks/c7-prod-live-e2e.md`, 백업/PITR
먼저) → receipt complete → 40C manifest. H34/37D는 설계 v2 P2 정리 → ADR → 다음 PR.
## 2026-08-18 — T-VN-41 #975 rebase 후 recovery fail-closed 검증 보강

#975 후보를 현재 `main` `ff25c397` 위로 rebase하고 permanent NACK의 consumer disable 계약에 맞춰
dead-letter replay → checksum reconciliation → `cache_target.reconciled` 전달·ack 순서를 통합 테스트에
고정했다. replay 뒤에도 `blocked`·consumer disable·claim 거부가 유지되고, mid-claim recovery가
모든 relay event를 ack해 빈 stream으로 끝남까지 검증한다. 직접 replay로 consumer를 여는 경로는 없다.

### 다음 한 작업

(2026-08-18 갱신) #975는 `main` `3e0732b3` 위로 rebase됐고(head `a78f55dc`) 사용자 결정으로 **CI green +
적대 재리뷰 2명 뒤 머지**한다. 새 exact pair의 n150 isolated Live UI 증거와 PinVi #444 재pin은 final C7
인수 때 한다(격리 pair 러너 재구성 필요·candidate 경계라 prod enable 없음). 기존 `77821001`/`e8e0fec`
증거는 이력이다(`t-vn-41-candidate-map` tag). F1D 후속은 별도 draft #995에서 진행한다.
## 2026-08-18 — T-VN-41 task ledger를 후보 검증 상태로 정렬

`tasks.md`는 #975의 정확한 source 쌍 후보 Live UI 복구·증거 결박·적대 재리뷰 통과를 `[~]`로
기록한다. 이는 final main C7, production consumer enable 또는 `complete` receipt가 아니다.

### 다음 한 작업

Map #975를 최신 `main`에 rebase한 뒤 permanent NACK 후 consumer disable 계약에 맞춰 integration
test 2건을 reconciliation 재개 경로로 갱신한다. 정확한 새 Map/PinVi 쌍을 다시 pin해 원격 CI와
n150 isolated Live UI E2E를 새로 통과시킨다. #975는 사용자 머지 지시 전까지 미병합으로 둔다.
닫힌 #967은 재배치 대상이 아니므로 #975 후 현재 `main` 기준의 F1D 후속 PR을 새로 열지 또는
reopen할지를 결정한다.
## 2026-08-17 — prod DB를 프로젝트별 전용 인스턴스 4개로 분리 (12x00 대역)

n150 prod의 PostgreSQL을 넷으로 나누고 포트를 각 대역의 `x00`으로 맞췄다.
**`5432`를 듣는 것은 이제 없다.**

    geo        5432  -> 12500   (33GB, 제자리 — 포트만)
    concierge  (신규)   12600   (79MB 이관, 28테이블 39,515행 일치)
    map       12703  -> 12700   (제자리 — 포트만)
    pinvi      (신규)   12800   (11MB 이관, 52테이블·265인덱스 일치)

**왜 DB만 나누는 것으로 부족했나.** role·ACL·확장은 DB가 아니라 cluster 전역이다.
08-15에 map을 전용 인스턴스로 뺀 뒤에도 통합 인스턴스에 `ktm_` 역할 7개가 남았고
map migrator 자격증명으로 `kor_travel_geo`(33GB)에 실제로 접속됐다. 근거는
docker-manager **ADR-37**(이번에 신설 — 그전까지 4분할에는 ADR이 없었다).

geo 33GB는 옮기지 않았다. 통합 인스턴스가 이미 그 데이터를 갖고 있으므로 얹혀 있던
것만 빼내고 포트를 바꿨다 — 총 이동량 692MB.

**적대 리뷰가 P1 9건을 찾았고 전부 반영했다.** 특히 세 가지가 실질적이었다.

- `c6c_deployment.py`가 12703을 하드코딩해 **다음 sanctioned 배포를 fail-close로
  막고 있었다.** 테스트 픽스처도 12703이라 테스트는 초록이면서 prod가 막히는 상태.
- `.env.example`가 옛 포트 그대로였다. 이번 사고의 원인이 `.env` override인데 그
  `.env`를 만드는 템플릿을 안 고쳤으니 다음 사람이 같은 사고를 재현할 상태였다.
- geo만 `listen_addresses=*`로 LAN에 열려 있었고, `kor_travel_map`·`krtour_map`·
  `pinvi` login role이 `kor_travel_geo`에 CONNECT+USAGE를 가진 채 남아 있었다.
  지금은 넷 다 loopback이고 geo에는 자기 superuser `addr`만 있다.

### 다음 한 작업

PR 2건 머지 — kor-travel-map [#985](https://github.com/digitie/kor-travel-map/pull/985)
(문서), kor-travel-docker-manager
[#176](https://github.com/digitie/kor-travel-docker-manager/pull/176)(compose·ADR-37).
그 뒤 남은 것은 **geo·concierge·pinvi 인스턴스의 백업 주체**다 — map만 절차가 있고
나머지 셋은 없다(docker-manager 소관, `docs/backup-restore.md` §1 참조).
## 2026-08-17 — T-VN-41A-C PR #975 current-main 재배치

PR [#975](https://github.com/digitie/kor-travel-map/pull/975)의 stale refresh
finalization fence와 queued cancellation outbox를 보완하고, 현재 `main` OpenAPI
artifact를 재생성했다. 두 적대적 재리뷰에서 Map DB/동시성 P0/P1은 없었다. PinVi #444는
동일 service bytes를 재vendor했고 paired contract CI를 통과했다. T-VN-41 receipt는
`pending → candidate_verified → complete`를 구분하며, 후보 증거는 final main C7을 대체하지 않는다.

**다음 한 작업**: Map/PinVi 후보 commit·C7 runtime 다섯 immutable image·attestation을 고정한 뒤 n150
isolated Live UI E2E를 실행한다. 성공 시 `candidate_verified` receipt와 evidence digest를
같은 PR에 기록하고 CI를 다시 통과시킨다. 그 뒤 #975를 병합하고, #967은 #975 병합 뒤의
`main` 위에서 재배치·동일 gate를 적용한다. final main C7은 별도 후속 gate다.
## 2026-08-17 — 완료된 Wave 2 task 이력 아카이브 정리

`T-VN-34`·`T-VN-35/34/36-deploy`·`T-VN-36`과 격리 clone 인수는 2026-08-13
prod cutover로 완료돼 [`tasks-done.md`](../tasks-done.md)로 이관했다. `tasks.md`에는
열린 `T-VN-37D`, T-VN-40 release 수용, T-VN-39만 남겼고 비표준 상태 표기도
규약의 `[~]`로 바로잡았다. 코드·스키마·운영 환경 변경은 없다.

**다음 한 작업**: 기존과 같이 T-VN-40 canonical import/backfill 실운영 인수와
paired receipt complete를 진행한다.
## 2026-08-16 — T-VN-40 구현·연동 소비자 병합 완료

Map 구현 PR [#974](https://github.com/digitie/kor-travel-map/pull/974)는
`170ddf57`로 병합됐고 CI 8개가 모두 녹색이다. PinVi canonical 소비자
[#445](https://github.com/digitie/pinvi/pull/445)와 Docker Manager C6c principal 결선
[#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)도 병합됐다. 이는 source와
연동 release artifact의 준비 완료이지 n150 cutover 완료가 아니다.

**다음 한 작업**: 전용 canonical principal을 사용해 n150에서 canonical import/backfill 실운영
인수를 실행하고, Map·PinVi exact commit/service vendor hash와 legacy-zero 결과를 receipt에
남긴다. 그 결과가 모두 있을 때만 T-VN-40 receipt를 complete로 전이하고 final legacy 물리 삭제를
수행한다.
## 2026-08-16 — T-VN-40 PostGIS typed runtime CI 수리

실제 Dagster/API LOGIN으로 provider·cancellation typed command를 실행하도록 integration
fixture를 분리했다. command owner가 append-only event clock을 갱신하는 최소 권한도 정렬했고,
queued provider root의 terminal heartbeat 및 tracking-invariant 종결을 실제 cancellation
coordinator 흐름으로 고정했다. quarantine marker NULL 비교와 committed-row test isolation,
candidate engine dispose 순서도 fail-close로 수리했다. runtime privilege 음성 test의 API·Dagster
engine 수명도 정확히 닫아 Python 3.13 CI가 ResourceWarning으로 실패하지 않게 했다.

**다음 한 작업**: PR #974 브랜치를 푸시한 뒤 GitHub Integration/PostGIS check가 focused
회귀와 같은 실제 runtime identity에서 녹색으로 끝나는지 확인한다. 그 전에는 rollout receipt
completion이나 n150 live acceptance를 수행하지 않는다.
## 2026-08-15 — T-VN-40 PostGIS CI runtime 격리 정렬

runtime privilege preflight가 disposable LOGIN 비밀번호를 오래된 T-VN-34 값으로
재설정해, 뒤이어 실행되는 T-VN-40 candidate command 테스트의 연결을 깨던 순서 의존성을
제거했다. 모든 runtime LOGIN fixture는 migration bootstrap과 같은 T-VN-40 test-only 값으로
통일했다. 공개 collection reader도 신뢰된 공개 Feature 연결 item만 반환하는 현재 정책에
맞춰 미연결 item은 admin read에서만 보존함을 통합 회귀로 고정했다.

**다음 한 작업**: 원격 PostGIS CI를 다시 녹색으로 만든 뒤, Map PR의 독립 승인과 병합
순서를 확인한다. 승인·병합 전에는 n150 live acceptance, rollout receipt completion, legacy
물리 삭제를 수행하지 않는다.
## 2026-08-15 — T-VN-40 Dagster CI 테스트 경계 정렬

authoritative snapshot 적재와 curation input proof 전달을 production asset이 사용하도록 바뀐 뒤,
Dagster asset 테스트 double과 terminal payload 기대값이 이전 호출 계약에 남아 있던 문제를 정렬했다.
Concierge는 authoritative load·retirement를 같은 causal 경계로 모사하고, OpiNet은
`curation_dataset` keyword를, single-member terminal은 nullable proof 필드를 명시적으로 검증한다.

**다음 한 작업**: 원격 Map CI를 다시 녹색으로 만든 뒤, 세 PR의 독립 승인과 병합 순서를
확인한다. 승인·병합 전에는 n150 live acceptance, rollout receipt completion, legacy 물리 삭제를
수행하지 않는다.
## 2026-08-15 — T-VN-40 service OpenAPI contract test 정렬

service restore-fence command는 최초 `201`과 exact `Idempotency-Key` terminal replay `200`을
함께 계약으로 둔다. registry test가 이 명시적 replay response를 잘못 거절하던 문제를 고쳤고,
canonical cutover identity mapping export도 service OpenAPI의 exact route inventory에 추가했다.

**다음 한 작업**: Map과 PinVi 원격 CI를 다시 확인한다. Manager principal 결선의 병합과 n150
paired live acceptance 전에는 rollout receipt completion 및 legacy source의 물리 삭제를 수행하지
않는다.
## 2026-08-15 — T-VN-40 admin OpenAPI 생성형 타입 동기화

canonical cutover identity mapping service export가 admin OpenAPI에 추가된 뒤에도 frontend의
생성형 타입이 이전 정본을 가리켜 GitHub `openapi-typescript --check`가 실패하던 상태를
동기화했다. frontend가 API artifact의 mapping cursor·root·member DTO를 현재 service 정본과
같이 검증한다.

**다음 한 작업**: Map/PinVi 원격 CI를 끝까지 확인한다. Manager principal 결선의 병합과
n150 paired live acceptance 전에는 rollout receipt completion 및 legacy source의 물리 삭제를
수행하지 않는다.
## 2026-08-15 — T-VN-40 n150 canonical curation principal 격리

isolated n150 runner는 Map API에 PinVi canonical snapshot·cutover mapping principal의
SHA-256 digest만 주고, 서로 다른 두 원문 token은 PinVi API에만 전달하도록 고정했다.
compose도 같은 Map API 전용 digest 경계를 선언해 원문 token이 Map API·Dagster·frontend로
퍼지지 않는다.

Docker Manager는 PR [#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)에서
같은 네 값을 frozen C6c transaction으로 결선했다. PinVi API 원문 pair를 Manager가 받아 Map API에는
digest만 파생하며, Map UI·Dagster·bootstrap과 PinVi Web·Dagster에는 어떤 형태도 전달하지 않는다.
PR이 병합되기 전에는 이 경계를 배포 완료로 취급하지 않는다.

현재 branch CI의 Geo BFF credential guard·clone runner contract·H35 wheel build 전제도 함께
정렬했다. CI는 `uv`를 명시 설치하고, clone runner는 candidate geo를 띄우지 않는 동안 전용 Geo key를
빈 값으로 유지한다. Geo BFF는 요청 시점 key를 읽되, 누락 때 `GEO_API_KEY_NOT_CONFIGURED` 사유로
명시적으로 fail-close한다.

**다음 한 작업**: #174 병합 뒤 canonical import/backfill n150 live acceptance와 paired release
receipt의 exact Map/PinVi commit·service vendor hash를 확인하고, 그 증거가 모두 있을 때만
T-VN-40 receipt를 complete로 전이한다.
## 2026-08-15 — T-VN-40 paired service receipt 배포 gate 강화

active `deployment_receipt_task=T-VN-40`가 complete가 되려면 installer와 n150 runner가 Map의
user/service/full OpenAPI와 PinVi의 user/service vendor를 모두 archive에서 다시 해시하도록
고정했다. 이미 제거한 admin detail snapshot vendor는 더 이상 active receipt에 허용하지 않는다.
receipt key set·검증 문구·두 vendor의 Map hash 동치를 fail-close하고, immutable install manifest도
version 4로 올려 이전 receipt 해석과 섞이지 않게 했다.

**다음 한 작업**: Map/PinVi exact commits와 두 vendor digest, canonical importer legacy-zero
검증, n150 canonical snapshot live acceptance가 갖춰진 뒤에만 T-VN-40 receipt를 complete로
서명한다. 그 전에는 pending 유지와 installer 거부가 정답이다.
## 2026-08-14 — 빌드 파이프라인 결손 봉합 + prod 경계 실측

**`scripts/docker-buildx.sh`가 `dagster-daemon` 이미지를 굽지 않았다.** 2026-08-13
daemon 사고의 저장소 쪽 뿌리다 — `docker-build.sh`는 네 서비스를, buildx는 셋을
빌드해 두 파일이 오래 모순이었다. 한 번 빌드에 태그 두 개로 고치고(두 번 부르면 두
이미지가 같다는 보장이 없다), 가드를 두 층 세웠다. 브랜치
`fix/build-script-daemon-image`(커밋 `0e5f3521`), 로컬 게이트 1360 passed.

**prod 경계 실측 두 건.** api/dagster/daemon 셋 다 migrator·api_runtime DSN을 들고
있고 셋의 `KOR_TRAVEL_MAP_PG_DSN`이 전부 dagster runtime 역할이다 — prod compose가
git 체크아웃이 아니라 손으로 6줄 덧댄 사본이기 때문이다. 수정은 docker-manager
`agent/issue-171-map-dedicated-postgres`에 이미 있으므로 #46 배포에 실린다(task #51).
admin UI만 geo 소비자 키를 못 받던 것은 docker-manager
`fix/map-ui-geo-consumer-key`로 끊었다(task #52).

조사 중 한 번 크게 헛짚었다 — `127.0.0.1:5432`만 보고 `ktm-tvn36-db`를 정본으로
착각했다. prod 호스트 5432는 `kor-travel-geo-postgres`다. 잘못된 DB에서 "runtime
쓰기 권한 0"이라는 수치가 나왔고 정본에서는 정상이다. 정본 alembic 리비전은
`0104_tvn36_final_fence`로, `0201_squash_bridge`가 선언한 값과 일치한다.

### 다음 한 작업

PR [#979](https://github.com/digitie/kor-travel-map/pull/979) integration green을
확인하고 머지한다. 그 다음 `fix/build-script-daemon-image`를 리베이스해 PR을 연다.
docker-manager 두 브랜치(`fix/map-ui-geo-consumer-key`, issue-171)는 prod 배포가
필요하므로 승인된 배포 경로로만 나간다.
## 2026-08-14 — T-VN-40C Map cutover identity mapping export

PinVi가 legacy `curated_feature_id`를 canonical collection/item UUID로 옮길 때 Map DB에
직접 접근하지 않도록, maintenance fence 전용
`GET /v1/service/curation-cutover/identity-mappings`를 추가했다. 이 표면은 별도
ServiceToken digest, signed keyset cursor, immutable row hash와 전체 Merkle root/count를
함께 반환하며 runtime은 해당 mapping relation을 읽기만 할 수 있다.

**다음 한 작업**: PinVi가 이 service OpenAPI를 vendor하고 mapping root/count를 receipt에
결박한 뒤 기존 plan/POI provenance를 backfill한다. mapping의 누락·중복·checksum 불일치는
cutover를 즉시 fail-close해야 하며, 그 후에만 legacy import route/컬럼을 물리 제거한다.
## 2026-08-14 — prod 지오코딩 복구 + 재발 통로 제거 (T-VN-H46B/C)

prod의 dagster/daemon 두 컨테이너가 geo가 401로 거절하는 VWorld 키를 들고 있었다.
재생성으로 복구했고 세 컨테이너 전부 `POST /v2/reverse` HTTP 200이다. 저장소 쪽
재발 통로 **7곳**(첫 판이 센 5곳 + 적대 리뷰가 찾은 2곳)을 끊고 정적 가드를 세웠다.
PR [#979](https://github.com/digitie/kor-travel-map/pull/979).

**다음 한 작업**: #979 CI green 확인 후 머지.

그 다음 셋:

1. **prod admin UI 지오코딩은 아직 죽어 있다.** `kor-travel-map-ui` 컨테이너에 geo
   소비자 키가 **한 개도** 들어가 있지 않다(적대 리뷰 실측). `NEXT_PUBLIC_*`은 빌드
   시점에 번들에 박히므로 이미 구운 이미지에 키를 넣는 유일한 경로는 런타임 env
   `KOR_TRAVEL_GEO_API_KEY`이고, 이 PR이 저장소 compose에 그 배선을 넣었다.
   **남은 절반은 cross-repo다** — `kor-travel-docker-manager`의
   `docker-compose.yml` `kor-travel-map-ui` 서비스에 같은 env를 추가해야 한다.
   그래야 재빌드 없이 켤 수 있다.
2. daemon 이미지만 재빌드에서 빠지는 파이프라인 원인(별건).
3. 기동 시 "자기 코드 세대 vs DB alembic head" 대조 fence.
## 2026-08-14 — alembic squash 완료(검증까지), prod 지오코딩 복구

**다음 한 작업**: PR #977 head 위 bootstrap과 0105 expand DB spine을 구현하고,
T-VN-40 final schema/API/cutover를 서로 다르게 승인하던
`target-schema-v1.sql`·`recovery-preflight-v1.json`·`openapi-diff-v1.json`을 최종 정본으로
원자 재동결하고 SERIALIZABLE domain-command transaction policy까지 구현했다. candidate
reject와 promotion은 실제 API LOGIN만 실행 가능한 named SECURITY DEFINER procedure로
전환했다. promotion은 current source proof와 T-VN-36 typed detail/override lineage를 다시
해시해 stale 후보를 원자 거부하고, canonical item·trusted accepted decision·candidate transition을
한 transaction으로 결박한다. `rule_reconcile` set-based generation도 caller 후보 입력 없이
DB-derived expected set/scope hash, immutable receipt-first, observation completeness와 exact replay로
구현했다. provider full-snapshot generation도 Dagster terminal receipt에 결선했다. authoritative
child import job의 exact dataset membership을 DB가 재검증하고, 해당 dataset의 rule별 generation과
정렬 receipt hash를 같은 SERIALIZABLE transaction에 기록한다. single-member와 MCST multi-member
wrapper 모두 실제 observation receipt에서 authoritative 축을 전달한다. 다음은 retained catalog와
collection/item의 typed CAS command 경계를 구현한다. bootstrap은
populated DB에서 2회, 0105는 fresh 0001→head와 실제 ROLE ACL/append-only gate로 검증했다.
frozen artifact unit 10개와 target SQL/violation/head-equivalence integration 11개도 통과했다.
SERIALIZABLE 정책 unit 22개와 실제 PostgreSQL transaction integration 1개도 통과했다.
공개 canonical reader의 미연결 included item 우회도 닫아 public count/detail은 linked public
Feature와 trusted accepted decision을 공통으로 요구한다. PostgreSQL 통합 회귀가 공개 0건과
admin 보존을 함께 확인했다.
candidate reject/promotion actual-LOGIN/CAS/typed-detail-stale/교차-role 통합과 receipt gate
8개도 통과했다. rule reconcile materialize/replay/scope omission/교차-role을 포함한 candidate
통합 테스트 7개도 fresh 0108 head에서 통과했다. routine 소유권 이전 뒤 남던
기본 `PUBLIC EXECUTE`는 audit owner·command owner 역할로 직접 전환한 exact ACL 재설정으로
0105/0106 guard·helper·procedure 전체에서 제거했다.
admin candidate 목록/detail/timeline과 reject/promote API도 연결했다. raw candidate CAS ETag와
typed detail을 포함한 representation ETag를 분리하고, BIGINT는 decimal string으로 고정했다.
API/route-policy/domain-command/OpenAPI focused gate 96개가 통과했으며 admin OpenAPI를
재생성했다.
provider full-snapshot/비권위 거부와 feature operation repo를 합친 DB 15개, Dagster wrapper·
MCST unit 41개도 통과했고 관련 Python source의 ruff/mypy가 통과했다.
candidate snapshot과 generation의 rule hash도 DB helper 하나로 수렴시켜 referenced theme/source
archive·owner/provider 의미를 canonical input version 3에 포함하고 display/CAS revision은 제외했다.
retained rule create/patch/archive도 actual API LOGIN 전용 typed command로 전환했다. 각 명령은
domain command·strong revision·SERIALIZABLE을 검증하고 sorted Feature prelock 뒤 catalog CAS와
immutable reconcile receipt, set-based generation을 같은 transaction에 결박한다. fresh 0109 head의
rule command와 기존 candidate 회귀 9개가 통과했다. admin repository/API도 단건 GET·archive,
decimal revision, create/patch/archive strong ETag와 If-Match/replay 경계로 연결했다. admin OpenAPI와
generated TypeScript를 7.13.0으로 재생성했고 Linux ext4 격리 환경의 generation check와 전체
frontend type-check가 통과했다. 적대 리뷰의 N:M receipt 중복, metadata-only generation, create 201,
UUID/null 422, SERIALIZABLE retry 우회와 applied OpenAPI freeze도 수정했다. retained theme catalog도
actual API LOGIN 전용 create/patch/archive command, 단건 GET, strong ETag로
전환했다. archive는 dependent rule generation을 같은 SERIALIZABLE transaction에서 끝내고,
metadata-only catalog revision과 candidate semantic proof를 분리해 정상 후보 promotion이 stale로
오인되지 않게 했다. retained source catalog도 operator CAS revision과 provider observation revision을
분리하고 API create/patch/archive와 Dagster exact import-job observation을 서로 다른 executor의 named
command로 결선했다. theme/source/rule 공통 append-only effect claim은 terminal/open command의 다중
resource 재사용을 차단하며 provider-owned/NULL-owner theme/rule은 admin command로 수정할 수 없다.
source observation은 authoritative full-snapshot child job당 immutable receipt 한 건으로 제한했고,
caller-driven admin rule apply와 독립 `curated_features_refresh` Dagster job/client export를 제거했다.
provider child 완료 직전 exact source-head identity/payload 집합을 append-only receipt로 봉인하고,
root `done/SUCCESS` SERIALIZABLE transaction은 전체 child receipt와 영향 Feature 합집합을 한 번에 검증·
정렬 선잠금한 뒤 typed source observation과 candidate rule generation 전체를 만든다. root generation 집합도
별도 append-only receipt로 봉인한다. Dagster LOGIN의 per-rule materializer·observation 직접 EXECUTE와 두
receipt relation의 raw DML은 회수했다. child 완료 뒤 source head가 변하면 `40001`로 root transaction 전체를
재시도하므로 과거 job에 다른 load의 현재 head를 귀속할 수 없다. archived theme/source는 legacy와 canonical
public projection 전 경로에서 즉시 제외한다.
삭제된 curated schedule/UI를 전제하던 stale live Playwright spec도 제거했다. provider child seal은
source head뿐 아니라 link identity·role·match method·confidence까지 load transaction 안에서 봉인하며,
root 전 검증에서 committed drift가 발견되면 `stale_input` terminal로 수렴한다. provider-owned concierge
theme/rule도 terminal observation trigger가 잠긴 DB set에서 도출하고 operator-owned slug 충돌은
fail-close한다. `ops.import_jobs`/membership의 provider root 생성·member 완료·terminal 전이는 named
command로 전환했고 Dagster LOGIN의 raw 증거 DML은 `42501`로 닫았다. provider load·retirement·notice·
merge와 root finalizer는 첫 relation lock 전에 동일한 global transaction fence를 잡는다. MOIS의
chunk별 commit 뒤 boolean 승격을 제거하고, concierge·국가유산 lifecycle 변경은 load+seal과 같은
transaction에 넣었으며, MCST empty member도 authoritative receipt를 남긴다. 다음은 retained
theme/source/rule relation의 runtime raw DML 권한과 남은 provider catalog writer를 전수 회수해 named
command만 남겼다. collection create/import는 existing catalog exact match만 참조하고 API·Dagster
LOGIN의 catalog INSERT/UPDATE/DELETE는 모두 `42501`이다. 다음은 collection/item/import/quarantine/
merge의 raw writer를 revision CAS·domain command receipt가 있는 typed command로 전환하는 것이다.
T-VN-40 paired consumer receipt는 현재 `pending`이며 Map user/
service/full spec hash를 고정하고 n150 installer가 complete 전에는 fail-close한다.
fresh 0001→0114 actual-login candidate/source 통합 15개, 관련 unit 147개와 격리 Dagster MCST
16개를 통과했다.
A/B/C는 하나의 forward-only PR/release로 유지하며, 누적 구현은 DB/동시성과
API·consumer/ACL 관점의 독립 적대 리뷰어 2명이 같은 고정 SHA에서 검증한다.
상세 계약은
[`t-vn-40-curation-write-model-detailed-design-2026-08-11.md`](../reports/t-vn-40-curation-write-model-detailed-design-2026-08-11.md)가 정본이다.
PinVi legacy curated detail snapshot도 canonical `curation_item_id` 기반 projection으로
같은 release에서 이관한다.
## 2026-08-13 — T-VN-36 prod cutover 완료

**prod가 `0104_tvn36_final_fence`다.** 백업 없는 in-place 마이그레이션(사용자 지시),
`0087` → `0104` 1시간 32분, feature 1,008,852 손실 0, 런타임 4/4 healthy.
상세는 `docs/tasks.md` `T-VN-35/34/36-deploy`.

**다음 한 작업**: 공개 API 키 발급 — `ops.public_api_keys`가 0행이라 공개 표면이
401이다(마이그레이션 이전에도 0이었다). 그 다음이 전용 PostgreSQL 이행
(docker-manager #172)이고, 그건 **데이터 이동이 선행**돼야 한다 — 저장소 형상은
DSN이 `:12703`을 가리키는 전제인데 prod 데이터는 공유 `:5432`에 있다.

> 이 문단은 **2026-08-17 항목(맨 위)이 대체했다.** 전용 인스턴스 이행은 끝났고
> map의 포트는 `12703`이 아니라 **`12700`**이며 `5432`를 듣는 것은 없다.

배포에서 배운 것 둘:

- 마이그레이션은 **독립 컨테이너**로 돌려야 한다. `0095` 3축 backfill 하나가 58분이고
  api healthcheck 창은 3.5분이라 entrypoint 인라인으로는 구조적으로 완주 불가다.
- `dagster`/`daemon`은 api와 달리 entrypoint의 runtime DSN 교체 경로가 없어
  `KOR_TRAVEL_MAP_PG_DSN`을 그대로 쓴다. bootstrap 이후 `krtour_map`이 권한을 잃으므로
  이걸 안 바꾸면 조용히 못 읽는다.
## 2026-08-13 — T-VN-34·T-VN-36 머지 + live 인수 완주

**이전 다음 작업**: PR #977을 머지한 뒤 alembic squash를 별도 PR로 잡는다. prod
cutover가 폐기·재생성으로 확정됐으므로 `0001→0104` 체인은 앞으로 어떤 DB에서도
실행되지 않는다 — 그 체인이 지고 있는 sha 상호 고정과 fence/replay/backfill이
통째로 죽은 코드가 된다. `contracts/vnext/target-schema-fingerprints-v1.json`이
빈 PostGIS DB 기준 실측을 이미 byte-freeze하므로 "체인으로 만든 카탈로그 ==
squash로 만든 카탈로그"를 **증명**할 수 있다. squash하면 prod(`0087`)가 앞으로
나아갈 경로는 완전히 사라진다 — 오늘 결정과 일관되지만 명시해둔다.

**live 인수 완주** (source `cd5b7470`): `phase: passed`, Playwright main 2/2 +
recovery 2/2, API-owned 감사가 유도값과 정확히 일치(features 1 / overrides 7 /
transitions 3 / commands 3). 상세와 아홉 건의 발견은 `docs/tasks.md`
`T-VN-36-live` 참조.

- PR #972(T-VN-34) `2026-08-13`, PR #973(T-VN-36) `c76ceb7a` 머지. main head는
  `0104_tvn36_final_fence`.
- **prod 실측 정정**: prod 적용 head는 `0083`이 아니라 **`0087_route_area_subtypes`**
  이고 feature는 1,008,852행, `0097` fence가 보는 `user_request` receipt는 **0건**
  이다. 문서가 오래 `0083`이라고 적고 있었다.
- **데이터가 있는 DB에 ADR-090 bootstrap 실행 성공** — T-VN-34에서 고친 두 P0
  (identity 시퀀스 sweep 제외 / `public.alembic_version` 이전)를 실환경에서 검증했다.
  exit 0, 7 role 생성, `alembic_version` 소유권 이전, 비소유 relation 0.
  docker-manager 쪽에는 이 결과를 catalog assertion으로 검증하는 축을 추가했다
  (`f975668`, PR #172 코멘트).
- 기존 `ktm-tvn38-db`는 전량 `user_request` fixture(feature 30 / version 64)라
  `0097` fence가 막는다 — clone 재사용 불가. 세대 전환이므로 기존 checkpoint는
  `archive-0104-*`로 보존했다.
- 러너가 alembic을 직접 부르면 `SET ROLE`이 빠져 `alembic_version` 42501이 난다.
  배포 경로는 `KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true`가 켠다
  (`docker/api-entrypoint.sh:262`).
## 2026-08-13 — T-VN-34 머지 대기: 적대 검토 3라운드 반영 완료
## 2026-08-13 — T-VN-36: 새 T-VN-34 base 재배치 완료, 영향성 gate 재실행

**다음 한 작업**: `feat/tvn36-abcd-field-overrides`를 이 재배치 head로 force-push한 뒤,
사용자 판단이 필요한 두 건(아래)을 정리하고 T-VN-40/T-VN-41 재base와 PinVi pair 재고정을
잇는다. PR은 아직 열지 않는다.

- base는 `feat/tvn34-state-model` `693c5355`이고 T-VN-36 고유 24 commit만 다시 얹었다.
  alembic은 `0104_tvn36_final_fence` 단일 head, migration graph/OpenAPI/contract SHA는
  재생성했다.
- T-VN-34에서 확립한 결함 부류를 전수로 걸어 notice reconcile SQL의 죽은 projection,
  override procedure arity 미추종, 죽은 오류 매핑, ledger operation 이름 붕괴, 정적
  차단선의 세대 누락, frontend type-check/lint red를 닫았다. 상세는 journal 2026-08-13.
- ~~**남은 판단 2건**: ① 하네스가 whole-row 모델 위에 있어 `0104`에서 실행 불가~~
  → **해소됨(`90e24872`)**. 하네스는 typed state 모델로 재작성됐다. 이 항목을 지우지
  않고 남기는 이유는 §2 진입 순서로 들어온 독자가 아래 옛 항목만 읽고 "실행 불가"로
  오해하기 때문이다 — 최신 항목(맨 위)이 정본이다.
  ② `0027` re-key 정리의 `data_origin='user_request'` 제외 가드는 head 동등 술어가
  없어 재현하지 않기로 했다(유효).
- ~~PinVi pair 재고정~~ → 재고정 완료(`e25ff376`). n150 live는 위 최신 항목 참조.
## 2026-08-12 — T-VN-38 머지 완료·백로그 정본 정리 진행

**다음 한 작업**: 완료 task 이관 문서 PR을 CI green 후 머지하고, 이미 머지되어 더 이상
사용하지 않는 로컬·n150 브랜치를 작업트리/열린 PR과 대조해 정리한다. 활성
`T-VN-34`·`T-VN-36`·`T-VN-41` 브랜치는 삭제 대상이 아니다.

PR [#971](https://github.com/digitie/kor-travel-map/pull/971)은 `8dc2b24a`로 머지됐다.
최종 source `bef509d`의 CI 8개가 green이었고, n150 전용
`ktm-tvn38-db:18732` clone Live UI E2E는 main/recovery 각각 2/2, `phase=passed`,
BLOCKED 없음으로 완료했다. 적대 리뷰 2인은 P0/P1=0을 확인했다.

`T-VN-33`(#966), `T-VN-37`(#968), `T-VN-38`(#971)의 완료 이력은
`tasks-done.md`로 옮기고, 아직 열린 배포·후속 task만 `tasks.md`에 남긴다.
## 2026-08-11 — T-VN-33: 라운드11~12, CI 경로 red BLOCKER 2건 해소

**다음 한 작업**: `T-VN-33` #966 — **머지**. 적대 리뷰 3렌즈 전원 APPROVE(P0/P1 0건),
로컬 게이트 25/25 GREEN, 33-E의 fresh 재적재·API/admin live 확인 완료. 남은 절차는
PR ready 전환 → GitHub CI green → merge다. 머지 뒤 T-VN-41 F1D-D를 재개한다.

33-E의 **fresh 재적재 + API/admin live 확인은 2026-08-11에 끝났다**(n150 격리
컨테이너, prod 스택 무접촉): 빈 PostGIS → 0092 head, `alembic check` drift 0 →
API live 12/12 → n150 브라우저 admin UI live 10/10 + 라운드12 수정 live 확인.
남은 33-E 잔여는 Dagster 축(격리 환경에 Dagster가 없다)과 머지 절차다.
상세는 `docs/journal.md` 2026-08-11 (2).

- **CI 경로에서 red였던 BLOCKER 2건을 닫았다.** (1) catalog exact-set 게이트가
  공유 `migrated_engine`의 전역 성질을 단언해 `pytest tests/integration` 통째
  실행에서만 4건 실패했다(단독 실행은 green) — 전용 DB로 옮겨 순서 독립으로
  만들고 오염 면역 + 진짜 drift 검출을 함께 단언한다. (2) 0092의 downgrade가
  "되돌릴 수 있다"는 거짓 진술과 함께 실제로 실패했다 — forward-only로 되돌리고
  `tests/unit/test_migration_forward_only.py`로 게이트를 세웠다(저장소에 downgrade
  경로 테스트가 0건이었다).
- **비활성 dataset 정리 경로**: DELETE는 새 실행이 아니라 정리이므로 활성 검사에서
  면제했고(FK RESTRICT는 유지), `ops.managed_files`는 활성 가드 대신 소유권
  immutable 전용 가드로 갈랐다 — 감사 기록이 조용히 누락되던 원인이 NEW쪽
  assert였다.
- **계약↔head 대조 게이트가 `CREATE OR REPLACE` 본문 변경을 못 잡았다.** 닫았고
  fail-open 하한을 실측값(제약 76 · 트리거 23 · 함수 22)으로 올렸다.
- **실행 가능한 scope가 없는 dataset의 '지금 갱신'이 활성이었고 눌러도 아무 일도
  일어나지 않았다.** 계약에 `effect: "none"`을 추가해 그리드·요청 dialog 양쪽에서
  막는다.
- 무방비 축 회귀: MOIS precheck fail-open(실 DB 7건), `_advisory_key` sync_scope,
  주소 clue 우선순위, MCST slug — 전부 변이로 KILLED 실증.
- 경과는 `docs/journal.md` 2026-08-11.
## 2026-08-11 — T-VN-34: 최신 T-VN-33/T-VN-38 rebase 반영

**다음 한 작업**: T-VN-36을 이 T-VN-34 rebase head 위로 재base하고, migration/OpenAPI/
consumer receipt 영향도를 다시 확인한다. 새 T-VN-34 consumer pair는 Map
`901939bf` ↔ PinVi `197bcee`로 고정했다.

- T-VN-34A `down_revision`은 upstream
  `0095_tvn33_tvn38_head_merge`를 가리킨다. 따라서 fresh Alembic head는 T-VN-33
  cleanup과 T-VN-38 current summaries를 누락하지 않는다.
- target catalog/OpenAPI artifact 및 state/runtime/post-cutover contract gate를 현재
  rebase tree에서 재동결·재실행했다.
- user/admin-detail vendor bytes는 같은 Map source에서 deterministic 재추출·PinVi contract
  pin-consistency로 검증했고, full admin OpenAPI digest만 receipt에서 갱신했다.
## 2026-08-11 — T-VN-36: T-VN-34 rebase 반영

**다음 한 작업**: T-VN-40·T-VN-41을 이 rebase head 위로 각각 재base하고, schema/OpenAPI/
PinVi pair와 Docker manager contract 영향도를 점검한다. T-VN-36 paired receipt는 Map
`c1fa5a4d` ↔ PinVi `8f7fef1`로 갱신했다.

- Alembic graph는 T-VN-33/T-VN-38 merge revision 뒤 T-VN-34 `0095`~~`0097`, T-VN-36
  `0098`~~`0104` 순으로 단일 head다.
- target catalog와 admin OpenAPI freeze는 current final-fence schema에서 다시 계산했고,
  final-fence 통합·target freeze·PinVi user/admin-detail contract gate를 재실행했다.
## 2026-08-10 — T-VN-34C: fresh live gate 실행 대기

**다음 한 작업**: PR #972를 CI green 후 merge commit으로 머지한다. 그 뒤 T-VN-36을 새
main으로 재리베이스하되 alembic revision 번호 충돌을 먼저 푼다 — T-VN-34가
`0098_admin_scope_indexes`를 추가했고 T-VN-36 체인도 `0098`부터 시작하므로 `0099~0105`로
재번호 + `down_revision` 재배선이 필요하다.

- 적대 검토 3라운드에서 28건을 받아 전부 반영했고 각각 변이로 증명했다. 3라운드는 실제
  prod 리허설(0087 + 100만 행)로 배포 P0 2건을 꺼냈다 — bootstrap이 데이터 있는 DB에서
  exit 3(identity 시퀀스), `public.alembic_version` 소유권 미이전. 둘 다 하네스가 fresh
  DB만 써서 보이지 않던 것이고, prod 이행이 **실데이터 이관**이라 필수 경로다.
- live E2E 러너가 T-VN-34C 자신 때문에 깨져 있었다(`user_change_reason` 조회). 이식했고
  스크립트도 정적 차단선에 넣었다.
- live 검증은 T-VN-36까지 머지한 뒤 한 번에 한다 — `0104`가 change-request 모델을 지우므로
  clone-live 러너를 두 번 재작성하지 않는다.
- 배포 결선은 docker-manager #171/#172가 Map 전용 PostgreSQL `:12703` 분리로 진행 중이며
  bootstrap 스크립트를 Map 저장소에서 마운트하므로 위 P0 수정이 그대로 실린다.
## 2026-08-10 — T-VN-36 A–D 단일 PR: field override 설계 착수

**다음 한 작업**: provider/admin/user/address/phone/notice normal writer와 admin typed
field override HTTP command를 registry receipt로 전환했다. 이제 detail/read/frontend를
effective override provenance로 교체하고 whole-row request/version bridge를 물리 제거한다.
## 2026-08-10 — T-VN-36 A–D 단일 PR: final destructive fence 구현·n150 gate 준비
## 2026-08-10 — T-VN-36 A–D 단일 PR: final destructive fence·n150 fresh live 완료

**다음 한 작업**: T-VN-36 A–D의 destructive completion gate와 요청된
`T-VN-33 → T-VN-38 → T-VN-34 → T-VN-36` rebase chain을 완료했다. 현재 체인은
T-VN-33 `5f2e1c85` → T-VN-38 `acfb6ed2` → T-VN-34 `73ced83a` → T-VN-36
`48cb08ac`(functional Map source)이며, n150 실행 source `f7e2e04e`와
`48cb08ac`은 동일 patch-id다. PinVi `6ab4eaf`와 새 Map SHA를 receipt에 재고정했고,
fixed-base integration은 TVN34C bridge를 전용 `0096→0097` gate로, TVN36D final fence를
head gate로 분리해 검증한다.

- `0104_tvn36_final_fence`는 `data_origin`/`data_version`, `feature_versions`,
  `feature_change_requests`, replay/materializer procedure와 request receipt/index를 forward-only로
  삭제한다. provider/admin은 field registry·base lineage·active override만 정본으로 쓴다.
- `contracts/vnext/tvn36-post-cutover-invariants-v1.sql`과 dedicated head integration이 final
  relation/column/catalog zero를 검사한다. 0096→0097 bridge와 혼동하지 않는다.
- n150에서 Playwright가 실행되지 않았던 직접 원인은 browser image가 아니라, isolated runner가
  생성한 ops read/cancel/fixture token을 API container environment에 전달하지 않아 API가 startup
  validation에서 종료된 것이었다. 이후 create request의 `coord` object를 DB procedure allowlist의
  `lon`/`lat`로 평탄화했고, final fresh Playwright는 auth setup과 destructive state scenario 2/2를
  통과했다.
- final live spec은 더 이상 change-request 승인/버전 snapshot에 의존하지 않고 browser BFF를 통해
  Feature 생성 → publication suppress → retire → audit timeline → cleanup을 실제 strong ETag로 검증한다.
- `consumer-rollout-v1.json`의 T-VN-36 receipt는 user vendor와 admin detail subset의 SHA-256을
  source archive와 대조한다. user/service 표면은 무변경이며 admin-detail subset은 재추출했다.

- base는 T-VN-34C 완료 head `b03d5a4f`이다. `data_origin`/`data_version`, `feature_versions`,
  whole-row request receipt는 T-VN-36D가 제거하며 T-VN-34 C head에는 남아 있다.
- logical A–D는 하나의 forward-only Draft PR/release로만 병합한다. base ledger와 typed effective
  storage는 compatibility dual-write가 아니라 하나의 field-level 정본이다.
- `0098_tvn36_override_lineage`는 64 path registry, provider base ledger, override provenance,
  runtime direct-DML deny와 state-owner type/source validation을 구현했다. provider/admin/user
  writer와 destructive legacy 삭제는 아직 이 logical phase에 포함하지 않았다.
- `0099_tvn36_provider_field_patch`는 provider source head/link lock 아래 base ledger와
  effective core/subtype을 한 transaction에서 갱신한다. active field override는 새 base만
  남기고 effective 값을 유지하며, runtime LOGIN에서 raw DML 없이 procedure를 실행하는
  catalog receipt까지 통과했다.
- `0100_tvn36_override_cmds`는 open domain-command claim과 expected revision을 확인하는
  author/revoke command를 추가했다. author는 superseded override를 revoke tombstone으로
  보전하고 operator typed 값을 materialize하며, revoke는 locked provider base로만 복원한다.
  runtime은 두 procedure 실행만 허용되고 direct override/base DML은 계속 금지된다.
- provider writer는 더 이상 raw core/subtype UPDATE나 `data_origin` whole-row CASE를 쓰지
  않는다. 새/기존 bundle 모두 source link와 typed subtype을 확보한 뒤
  `apply_provider_feature_field_patch`가 base/effective 값을 한 transaction에서 물화한다.
  nullable 좌표, area/route multi geometry, first-probe notice 시각도 이 경계에서 검증했다.
- admin/user add·update request도 `user.feature.override.author` claim과
  `author_feature_field_overrides` procedure로만 effective path를 바꾼다. raw core UPDATE와
  legacy user version materializer는 새 쓰기 흐름에서 제거했고, provider-owned detail source
  path는 fail-closed로 거부한다. delete는 ADR-090 lifecycle override만 계속 사용한다.
- `0103_tvn36_freeze_replay`는 retained applied request/version을 정확한 historical
  payload와 request 순서로 override history에 이관한다. preflight manifest가 unmapped 또는
  비정상 row를 발견하면 migration head를 전진시키지 않는다. address/좌표 writer도
  `author_feature_field_overrides`만 호출하며 raw effective UPDATE를 하지 않는다.
- phone enrichment의 `place.phones`도 system domain-command receipt와 typed override로
  author한다. notice lifecycle reconciliation도 `notice.valid_end_time`을 current
  provider source와 Feature revision을 다시 확인한 base patch로만 물화한다. Python
  normal writer의 direct effective core/subtype UPDATE는 0건이다.
- admin field override author/revoke endpoint는 existing HTTP domain-command claim의 exact
  `command_id`를 DB procedure에 전달한다. `If-Match`/ETag, registry validation, operator
  route policy와 idempotent replay를 한 contract로 묶었으며, snapshot retirement·notice
  candidate/purge의 `data_origin` predicate도 source-link/lifecycle semantics로 제거했다.
## 2026-08-10 — T-VN-34C: n150 fresh destructive live gate 통과

**다음 한 작업**: T-VN-34C의 구현 게이트는 완료했다. PR CI와 승인 뒤 forward-only C head를
병합하고, 다음 Lane B 작업인 T-VN-36A를 시작한다.

- T-VN-34 전용 63 commit은 최신 T-VN-33 `21b1758b` → T-VN-38 `2e78d623` 순서의
  체인 위로 재base했고, Map OpenAPI artifact는 현재 spec hash로 재freeze했다. merge는 하지 않았다.
- Map execution source `fe12e8da` ↔ PinVi `e37eda94` consumer pair를 다시 vendor했다. receipt의
  Map commit은 runtime source pin이며, runner를 담는 후속 문서 commit과 의도적으로 다르다.
- 새 installer/runner는 committed pair를 `git archive`로만 가져오며, `features_detailed` 부재,
  `0097_tvn34c_final_cutover`, runtime principal, exact executor label/hash를 fail-closed로 확인한다.
- n150 immutable snapshot에서 fresh `0097` PostGIS·actual Dagster runtime ETL·Noble Playwright
  destructive admin main/recovery(2/2)·PinVi public probe가 모두 통과했다. run과 seed 식별자는
  해시로만 보존했고, `BLOCKED.json`, 해당 compose container, volume은 cleanup 뒤 모두 없다.
## 2026-08-09 (3) — T-VN-33: 적대 리뷰 7·8라운드 REJECT 전건 처리, 변이 배터리 32/32

**다음 한 작업**: `T-VN-33` #966 — 9라운드 적대 리뷰 2명 승인 확보 후 머지.
승인 전 확인할 것은 (a) 전체 게이트 25종(vitest 포함) 재실행 결과, (b) n150
Playwright e2e(로컬·CI 어디에도 없다 — 이번에 그 사실을 명시했다).

- **8라운드는 리뷰어 둘이 독립으로 같은 BLOCKER를 찍었다**: `null === ""`로
  catalog 전용 dataset 17~18개의 상세가 통째로 렌더되지 않았고, 화면이 서버와
  정반대(`canonical`인데 "잔존 행")를 말했다. TypeScript도 e2e 픽스처도 못 잡는
  자리였다 — 픽스처에 `operation_key: null` 축을 넣어 못 박았다.
- **vitest 36파일 285케이스가 어느 게이트에도 없었다.** CI·로컬 둘 다에 넣었고,
  넣자마자 옛 계약을 못 박은 테스트 1건이 잡혔다. Playwright e2e는 여전히
  n150 전용이며 그 사실을 게이트 스크립트 머리말에 명시했다.
- **감사기가 "게이트가 실패할 수 있는가"를 안 봤다.** `|| true` 하나로 어떤
  게이트든 무력화 가능했다. 실패 억제·pytest 경로 축소·면제 밀수·워크플로 탐지
  4부류를 막고 변이 배터리를 20 → **32/32**로 올렸다.
- 제품 수정: 딥링크 3축 강제 완화(유일하면 수용·모호하면 거부), 실행 타임라인
  fail-open 필터, 요청 dialog 형제 operation 임의 선택, MOIS **제출 차단** 복구
  (표시만 복구돼 있었다), 비활성 dataset 정책 PUT 500 → 409, run history 축 확장,
  row id 충돌, offline upload 고정 기본 scope.
- **로컬 게이트 25종 전부 GREEN**(실측): unit+lint 2099 passed · api 1080 passed ·
  dagster 458 passed/3 skipped · integration **913 passed / 0 skipped**(geo live가
  n150 터널로 실제 실행) · vitest 36파일 286 tests · frontend 9종 전부 OK.
  하네스 자체의 거짓 3건도 함께 닫았다 — 루트 파일 미복사(낡은 사본을 읽었다),
  docker CLI 부재, `.next` 끊어진 심링크로 **일부만 복사된 트리** 위에서 실행.
  "환경 노이즈"라 부르며 넘기던 6건은 전부 하네스 결함이었다.
- 근거는 `docs/reports/t-vn-33-live-product-defects-2026-08-08.md` 35~49번,
  경과는 `docs/journal.md` 2026-08-09.
## 2026-08-09 (2) — T-VN-33: Node 22 전환으로 머지 블로커 해소, 게이트 24종 중 22종 GREEN

적대 리뷰 **6라운드 연속 REJECT**를 거쳤다. 여섯 번 다 같은 실패였다 — **변경 범위보다
좁은 집합으로 검증하고 green이라 선언**했다. 4·5·6라운드는 그것을 막으려고 만든
도구 자체가 그 실수를 저질렀다.

**환경을 올려 블로커를 없앴다.** WSL node가 v20이고 저장소가 22+를 요구해
`npm audit fix`가 engine 검사로 거부됐다. 그 상태에서 "환경이 없어 못 고친다"고
블로커로 남길 뻔했는데, Node 22.22.2를 설치하니 도구가 고치고 도구가 검증했다:

- `nanoid 3.3.16 → 3.3.18`(`^3.3.16` 범위 내, advisory 요구 충족)
- `audit:high` exit 1 → **0**, `npm ci --dry-run` **exit 0**

교훈: **읽기 명령(`npm audit`, `npm run`)은 Node 20에서도 통과한다.** 쓰기 명령만
거부되므로 이 문제가 한동안 안 드러나고, 그 자리에 미검증 주장이 쌓인다.
절차는 `docs/dev-environment.md` §10.9.

**게이트 24종 중 22종 통과.** 실패 2종은 pytest 두 갈래이고 그 안의 13건이
전부 환경 노이즈다(docker CLI 부재 7, geo 키 미마운트 5, package.json 미마운트 1).
제품 실패 0건. coverage api 77.53% / dagster 83.82%.

**감사기가 유효한지는 변이로만 확인된다.** 6라운드 리뷰가 변이 11종 중 7종이 이
감사를 통과함을 실증했고, 그중 J·K는 게이트 스크립트가 자기 게이트 24개 중 2개를
지워도 침묵하는 것이었다. 감사기를 다시 쓰고(워크플로를 디렉터리에서 발견·트리거로
차단 판정·이름 없는 스텝·멀티라인 전 명령·workspace 구분·한 줄 내 조각 일치),
변이 배터리를 `scripts/audit-mutation-battery.py`로 저장소에 넣었다 — **11/11 검출**.

**react-doctor는 코드가 아니라 경로 문제였다.** `/mnt/f`(NTFS 마운트)에서 900초
스캔 예산을 넘겨 실패한다. 네이티브 fs 사본에서는 "No issues found!" 2분 3초.
게이트가 로컬에서 늘 red면 무시하게 되므로 스크립트가 네이티브 fs로 복사해 돌린다.

**다음**: 7라운드 리뷰 승인 → #966 머지 → PR #967(T-VN-41 F1D, D1/D2 분리).
후속은 태스크 #42(계약↔head 대조 게이트, offline upload 500).
## 2026-08-09 — T-VN-33: CI 미러 게이트 24종 중 20종 GREEN, 잔여 4는 전부 선재/환경

적대 리뷰 **4라운드 연속 REJECT**를 거쳤다. 네 번 다 같은 실패였다 — **변경 범위보다
좁은 집합으로 검증하고 green이라 선언**했다. 네 번째는 그것을 막으려고 만든
`scripts/verify-all-gates.sh`가 CI 차단 스텝 22개 중 10개만 돌리면서 상단에 "전부
돌린다"고 적은 것이었고, 그 사각에서 branch-caused ESLint 실패가 나왔다.

**스크립트를 CI와 1:1로 재작성**했다(24개). 목록을 추측하지 않고
`.github/workflows/*.yml`의 `run:` 스텝을 옮겼다. 정합성은
`tests/unit/test_gate_script_mirrors_ci.py`가 지킨다 — 워크플로를 파싱해 누락을
잡고, 면제에는 이유 문자열을 강제한다.

**현재: 24종 중 20종 통과.** 실패 4종의 귀속을 전부 실측했다:

- `pytest unit+lint` 6건 / `pytest integration` 7건 = **전부 환경 노이즈**
  (docker CLI 부재 5, package.json 미마운트 1, geo live 키 미마운트 5,
  docker effect 2). 제품 실패 0건. api 1080 passed, dagster 458 passed.
- `audit:high` — nanoid advisory. `origin/main`도 같은 lockfile이라 main도 red다.
- `admin react-doctor` — origin/main 프론트 src를 git archive로 떠서 같은 명령을
  돌리니 **main 10건 / 이 브랜치 7건**이다. 선재이고 이 브랜치가 3건 줄였다.

**게이트 재작성이 실제로 잡은 것**(구 스크립트는 하나도 못 봤다):

- branch-caused ESLint red 2건
- `operation_key=null` 행 상세가 **422**가 되는 신규 회귀(74개 dataset 중 17개).
  직전 커밋이 프론트에서 고친 것을 그 다음 커밋이 서버 `min_length=1`로 다시 깨뜨렸다.
- **기능 손실 하나** — MOIS 사전점검 경고가 통째로 사라져 있었다. 타입체크도
  테스트도 못 잡는다(아무도 안 쓰는 export가 남을 뿐이라 컴파일은 통과한다).
  `react-doctor`만 잡았다.
- 감사 테스트가 **자기가 감시하는 파일의 옛 사본**을 읽던 문제(컨테이너 복사 목록에
  `scripts/`·`.github/`가 없었다).

**결함을 지키던 단언 3건**을 이유와 함께 뒤집었다 — scope 접기, run history 접기,
event 축 부재. 셋 다 "형제 operation을 중복으로 규정"하는 형태였다.

**다음**: 5라운드 리뷰 승인 → #966 머지 → PR #967(T-VN-41 F1D, D1/D2 분리).
후속은 태스크 #42(계약↔head 대조 게이트, offline upload 500).
## 2026-08-08 (3) — T-VN-33: 적대 리뷰 3회 REJECT를 거쳐 게이트 10종 중 9종 GREEN

리뷰어 2명이 **세 라운드 연속 REJECT**했고 지적이 전부 타당했다. 세 번 다 같은
실패였다 — **변경 범위보다 좁은 집합으로 검증하고 green이라 선언**했다.
(1) 파이썬만 돌리고 프론트를 안 봄 (2) 프론트 `tsc`를 돌렸는데 CI가 쓰는
`type-check`는 tsc를 **두 번** 돌리므로 절반만 돌림 (3) 함수 시그니처를 바꾸고 그걸
호출하는 다른 테스트 파일·파생 산출물을 안 돌림. 세 번째는 그 실수를 사과하는
커밋 안에서 났다.

**프로세스를 고쳤다**: `scripts/verify-all-gates.sh`가 CI 게이트 10종을 한 번에
돌린다(ruff / mypy 3타깃 / lint-imports / OpenAPI drift / pytest 3개 루트 /
프론트 gen:types:check · app tsc · **e2e tsc**). 무엇을 돌릴지 매번 판단하지 않는다.
그 스크립트에도 같은 함정이 있었다 — 컨테이너 `sh`에 pipefail이 없어
`pytest | tail`이 늘 통과했다. 만들자마자 거짓 green을 재현할 뻔했고 고쳤다.

현재: **9/10 통과.** 남은 pytest는 13건 실패인데 전부 컨테이너 환경 노이즈다
(docker CLI 부재 5, docker effect 2, geo live 키 미마운트 5, package.json 1).
제품 실패 0건, 4,530 passed.

리뷰가 드러낸 실제 결함(보고서 24~30번) 중 이번에 닫은 것:

- **CI 블로커** — openapi.json을 바꾸고 체크인된 `types.ts`를 재생성하지 않아
  `gen:types:check`가 exit 0 → 1로 뒤집혀 있었다.
- **거짓 409** — active request 조회가 pair인데 상위 비교는 triple이라, operation만
  다른 정당한 요청이 409를 받았다. DB trigger는 triple로 판정하므로 Python 가드가
  자기가 흉내 내는 DB 가드보다 엄격했다.
- **service가 한 층 위에서 도로 pair로 접음** — `_states_by_api_scope`가 형제
  operation의 state를 first-wins로 덮었다. 이건 실수가 아니라 **명시적 결정**이었다:
  테스트 두 개가 "API resource는 하나여야 한다"며 형제의 paused 상태가 버려지는 것을
  단언하고 있었다. 둘 다 뒤집었다.
- **콘솔이 보내는 축을 서버가 버림** — `/v1/ops/datasets/{id}`와 `/preview`가
  `operation_key`를 선언하지 않아 operation만 다른 두 grid 행이 같은 상세를 반환했다.
- **e2e 전량 pair 기반** — `_ops-c7-admin-api.ts`에 런타임 resolver를 심어 40 → 0.
- **한 객체 안의 축 어긋남** — `OpsDatasetExecution`의 `sync_scope`는 member 것인데
  `operation_key`만 root 것이었다. member로 통일.

후속으로 뺀 것은 태스크 #42(계약↔head 대조 게이트 부재, offline upload 500).
근거는 보고서 29·30번에 evidence와 함께 남겼다.

**다음**: 4라운드 리뷰 승인 → #966 머지 → PR #967(T-VN-41 F1D, D1/D2 분리).
## 2026-08-08 (2) — T-VN-33: 기능 게이트 GREEN, 설계 재검토로 결함 4건 추가 해소

전체 스위트 **4,534 passed / 6 failed**로 수렴했다(시작 298 실패). 실패 6건은 전부
컨테이너 환경 노이즈다 — docker CLI 바이너리 부재 5건, 40k INSERT 벽시계 비율을 2%
허용오차로 비교하는 부하 민감 테스트 1건(단독 통과). 내 브랜치는 두 파일 모두 안 건드렸다.

이후 사용자 지시("호환성·최소수정보다 설계적 우수성·확장성·성능·유지보수성")에 따라
설계 재검토를 돌려 결함 4건을 더 찾아 고쳤다. 전부 live 실측 + A/B 증명을 붙였다 —
전수는 [`reports/t-vn-33-live-product-defects-2026-08-08.md`](../reports/t-vn-33-live-product-defects-2026-08-08.md)
21~23번.

- **ORM PK가 DB보다 좁았다**(`provider_dataset_operation_scopes`). 처음 근거로 든
  "identity map이 행을 접는다"는 이 저장소에서 도달 불가였고(raw SQL 전용), 진짜
  이유는 적대 리뷰가 A/B로 밝혔다 — **alembic autogenerate가 PK를 비교하지 않아**
  어떤 게이트도 이 어긋남을 못 봤다. 내 단위 테스트는 틀린 2열 모양을 단언해
  어긋남을 고정하고 있었다 — `test_alembic_head_primary_keys_match_orm_declarations`로
  게이트를 세웠고, 되돌리면 두 모양을 나란히 지목하며 실패한다.
- **dataset snapshot 집계가 pair 키 → 하드 500.** SQL은 triple로 partition하는데
  Python이 pair로 다시 묶어 `RuntimeError`. 스키마 변경 없이 카탈로그에 refresh
  operation 하나 더 등록하면 재현된다(롤백 트랜잭션으로 스키마가 허용함을 확인).
  API 테스트가 못 잡은 이유는 monkeypatch가 그 함수 자체를 스텁으로 갈아끼우기 때문.
- **API 표면이 identity 2/3만 노출**하던 4곳을 이었다. `sync_scope`의 근거 없는
  `| None`도 좁혔다(DB 세 열 모두 NOT NULL). OpenAPI admin 표면만 갱신됐다.
- **정합성 F5 sample id를 pair로 합성**해 중복 식별자를 냈다. `LIMIT` 쿼리의 정렬도
  PK 3열 중 2열뿐이라 비결정적이었다.

**검토했으나 하지 않은 것 2건** — 지시가 "설계 우선"이라도 동작이 안 바뀌는 변경은
밀어붙이지 않았다. offline_uploads 멱등키 4열화(구현까지 했다가 되돌림: 업로드 표면에
operation 입력이 없고 리졸버가 모호하면 실패시켜 죽은 폭), identity guard SQLSTATE
통일(38 대 1로 이것만 예외지만 분기하는 소비자가 없어 freeze 아티팩트를 흔들 값어치 없음).

**다음**: 적대 리뷰어 2명의 승인(사용자 요구 조건) → #966 머지 → PR #967(T-VN-41 F1D,
D1/D2 분리).
## 2026-08-08 — T-VN-33: 통합 라이브 실행이 제품 결함 다수를 드러냄, 머지 금지 유지

통합 스위트를 최종 스키마로 전환해 live로 돌렸다(8 에이전트 병렬). 55개 파일 중 30개가
green이고, 나머지는 대부분 **전환은 끝났으나 src 결함에 막혀** 있다.

이 실행이 제품 결함 33건(중복 제거 약 20개 고유)을 드러냈다 — 전수 목록은
[`reports/t-vn-33-live-product-defects-2026-08-08.md`](../reports/t-vn-33-live-product-defects-2026-08-08.md).
**단위 테스트로는 하나도 잡히지 않는다.** 이미 6건을 고쳤고(커밋 `2f123acb`) 그것만으로
102개 테스트가 살아났다:

- `pipeline_repo` 정렬 열 미투영 + `selected_operation_key` 누락 → pipeline projection 전체
- `consistency` F7 · `dedup_refresh_repo`의 `sr` join 유실 → 정합성 검사·dedup 조회 전체
- `curated_repo.create_curated_theme` f-string 누락 · `admin_feature_repo`의 삭제 열 참조

**남은 P0** (배포 시 즉시 터짐):

- dagster `assets.py` 3곳이 sync-state API에 `operation_key`를 안 넘김 → provider ETL asset 전부 사망.
  설계 판단 필요: asset이 자기 operation을 어디서 얻는가(Dagster job name = operation_key인
  registry가 있다 / client에 `*_for_operation_membership` 변형이 이미 있다).
- `mois.py` `_BULK_JOB_KIND`가 catalog에 없는 operation_key → MOIS bulk 적재 불가.
- `sync_scope="default"` 기본값이 최종 스키마에 없는 scope → MOIS incremental/closed와 CLI가
  데이터는 다 쓰고 cursor 전진에서 rollback.
- `cli/_h35_csv5.py`가 H35 0079 세대에 없는 `provider_datasets`를 조회 → 리허설 실행 불가
  (2026-08-07 자연키 되돌림 때 내가 넣은 것이다).
- `feature_update_executor`가 terminal event를 `import_job_dataset_id` 없이 기록 → heartbeat와
  같은 계열의 결함.

**남은 P1**: integrity violation 불변 트리거가 FK `ON DELETE SET NULL`·recurrence upsert와 모순 ·
동시 create 데드락 · 재적재 idempotency 파손(매 관측마다 feature 재기록) · notice reopened 집계
항상 0 · 0091이 job 형태 불변식 2개를 대체 없이 삭제 · alembic metadata drift.

**다음 한 작업**: 위 P0을 순서대로 고친다. dagster 건이 가장 크고 설계 판단이 필요하다.
그 뒤 통합 전체를 다시 돌린다. **#966은 그 전까지 머지 금지** — 지금 배포하면 ETL·ops UI·
정합성 검사·MOIS 적재가 동시에 죽는다.
## 2026-08-07 — T-VN-33 구현 완결, 적대 리뷰 대기

`feat/tvn33-provider-datasets`(PR #966)의 구현이 끝났다. ADR-088 triple(`provider_dataset_id +
sync_scope + operation_key`)이 scope PK와 참조 FK 4개, pipeline projection, API DTO, OpenAPI와
생성 타입 양쪽까지 관통한다. notice 계보는 `source_entity_heads`에 물화됐고, 0091 guard 본문은
`contracts/vnext/tvn33-reference-ownership-v1.sql`과 **공백 정규화 기준 31/31 동일**하며
freeze fingerprint 7/7이 맞는다. (들여쓰기까지 같지는 않다 — 마이그레이션은 Python 문자열
안이고 계약은 flush-left다.)

적대 리뷰 2건이 P0 4건을 잡았고 모두 고쳤다: 0090 재실행 불가, offline upload writer 파손,
curation 자연키 되돌림의 API 미전파, event 인덱스 keyset 손실.

검증은 prod 복원본(732,678 record) 위 0083 → 0091 완주 + 재시도 시나리오, 단위 2,081 pass,
mypy --strict 두 타깃, ruff, 통합 수집 오류 0이다. 잔여 단위 6건은 환경 노이즈다.
**통합 테스트 본체는 live DB가 필요해 실행하지 않았다 — 머지 전 1회 실행이 남은 위험이다.**

통합 테스트를 live로 돌렸고(testcontainers + docker socket) **P0 하나를 잡았다**:
`ops.import_jobs`와 `ops.feature_update_requests`의 모든 UPDATE가 조용히 버려지고 있었다
(BEFORE UPDATE 트리거가 `RETURN OLD`). job 상태 전이·generation·heartbeat·취소가 전부
무효인 상태였고 단위 테스트로는 잡히지 않는다. 고쳤고 실측으로 확인했다.

live green: freeze 계약 6 + 계약 아티팩트 7 + tvn33 migration contract 4 +
`test_feature_update_repo.py` 41/52.

**다음 한 작업**: `test_feature_update_repo.py` 잔여 11건을 정리한다. 모두 T-VN-33이 바꾼
동작에 맞춰 단언을 갱신하는 일이다(예: `matched_scope`에 `dataset_memberships`가 들어간다,
오류 문구 변경, 배열 필터 제거). 그 뒤 통합 전체를 한 번 돌리고 #966을 머지한다.
그다음 PR #967(T-VN-41 F1D evidence)을 마무리한다. alembic squash는 #966·#967 머지와 prod의
head 배포가 끝난 뒤 독립 PR로 다룬다 — prod가 `0083`이라 지금 접으면 도달 경로가 사라진다.
## 2026-08-06 — 사용자 지시로 T-VN-33 WIP 정리 후 중단

T-VN-33 구현은 중단했다. draft PR #966 뒤의 변경은 미스테이징·미커밋 WIP이며 merge 가능 상태가
아니다. 새 batch audit가 physical triple membership, sync state, pipeline, API/UI, scheduled
runtime, final-schema trigger/fixture P0를 확인했으므로, 재개 때는 작은 pair/scope patch를 이어
붙이지 말고 ADR-088의 non-null triple schema를 먼저 완결한다.

**다음 한 작업**: 사용자가 재개를 지시할 때
[`reports/t-vn-33-hold-snapshot-2026-08-06.md`](../reports/t-vn-33-hold-snapshot-2026-08-06.md)의
P0 순서대로 작업을 다시 분할한다. T-VN-41 F1D-D의 n150 final acceptance는 그 merge와 final
schema ETL 재적재 뒤까지 보류한다.
## 2026-08-06 — T-VN-33 normal-path 적대 리뷰로 P0 재개방, T-VN-41 final acceptance 대기 유지

초기 target-contract gate는 통과했지만, actual 구현의 normal path를 분리 검토한 결과
canonical dataset ID가 UI의 dataset detail/preview, generic geographic scope, Dagster request
snapshot/worker dispatch까지 완결되지 않은 P0와, `0090` 뒤 legacy source column을 읽는
curation trigger P0를 확인했다. 자연키 URL·effective-scope rank·정적 provider worker registry는
호환 경로로 보존하지 않는다. 모든 membership은 정확한
`provider_dataset_id + sync_scope + operation_key`로 request→job snapshot→pipeline projection
→executor→worker까지 전달한다. dataset member에는 nullable/wildcard `operation_key`가 없으며,
operation 없는 generic job은 member 행을 만들지 않는다.
source-rule trigger는 catalog join으로 재작성한다.

**다음 한 작업**: draft PR #966 안에서 backend/core/API·Dagster·frontend를 병렬 보완하고,
최신 schema의 fixture를 일괄 전환한다. 두 독립 적대 리뷰가 P0=0을 다시 확인한 뒤에만
T-VN-33을 merge한다. T-VN-41 F1D-D의 n150 최종 리허설은 merge→provenance pin→파괴적
rebuild→final-schema ETL 재적재 뒤에만 재개한다.
## 2026-08-06 — T-VN-33 contract gate P0=0 통과, 단일 PR actual 구현 착수

스키마 적대 리뷰 5차와 마이그레이션 적대 리뷰 4차가 모두 P0 GO를 냈다. 마지막 P0였던
활성 parent cascade의 indirect owner guard 오판은 non-deferrable FK에서 parent 부재가
referential action일 때만 허용하도록 고쳤고, notice·curation·integrity 3경로 양성 회귀를
추가했다. inactive dataset을 가진 feature update request parent 상태 변경도 독립 음성
fixture로 고정했다. 빈 PostGIS target contract suite와 artifact unit은 13건 통과했다.

**다음 한 작업**: draft PR #966 하나에 T-VN-33A/B/C actual Alembic migration·DB seed·model과
writer/reader/API cutover·legacy fence를 병행 구현한다. 모든 누적 delta는 테스트 전 적대
리뷰를 다시 받는다.
## 2026-08-06 — T-VN-33 3차 P0 보완 계약 검증 완료

T-VN-33의 target DDL·invariant·rejection fixture를 ADR-088에 맞춰 확장한 뒤 두 적대
리뷰어의 3차 NO-GO를 받았다. 이전 history/head completeness, full ownership DDL, removal
manifest P0에 더해 capability/operation 이중 정본, unauthorized scope, inactive 기존/간접/
nullable child의 update/delete/ownership clear, job/request parent lifecycle, membership
cardinality P0를 보완했다. capability는 산출 metadata로 축소하고 operation scope는 정규
child로 분리했으며, 전수 ownership DDL은 old/new guard·parent lock·deferred cardinality를
실행한다. 빈 PostGIS DB에서 rejection fixture, 정상 history, 정상 membership을 검증했다.

**다음 한 작업**: 두 적대 리뷰어의 재리뷰 P0=0 GO를 받은 뒤, T-VN-33A의 actual
migration/model/seed 구현을 같은 단일 PR에 누적한다.
## 2026-08-06 — T-VN-41F1D-C0a·F1J-A 병합, v5 dynamic fixture 결선 대기

Map application schema head artifact(PR #963)와 Map-owned cancel-probe fixture lifecycle(PR #960)가
각각 병합됐다. 후보 image는 application/Dagster storage head를 독립적으로 attest하며, fixture는
Map DB에서 transaction별 `armed → consumed → finalized`와 immutable unsafe outcome을 소유한다.

**다음 한 작업**: Docker Manager `T-VN-41F1D-C3`가 이 fixture lifecycle을 새 v5
`rebuild-pinned` journal에 직접 결선한다. response loss 재개는 immutable Map receipt를 읽고
canonical cancel POST를 재발행하지 않아야 한다.
## 2026-08-06 — T-VN-41F1D-C0 후보 Dagster storage migration artifact 완료

후보 image의 `ktm-dagster-storage head|migrate`가 Dagster 자체 storage graph의 단일
head를 attest하고, 같은 image의 instance config로 migration 뒤
`public.alembic_version` 한 행을 strict 대조한다. Map application Alembic/source SHA로
storage 세대를 추정하던 경로를 제거했고, Compose의 one-shot 성공 후에만 Dagster
webserver/daemon이 기동한다. 빈 격리 PostgreSQL 실측에서 세 값이 모두
`29b539ebc72a`로 일치했다.

**다음 한 작업**: Docker Manager T-VN-41F1D-C2가 후보 image의 이 command를 호출해
storage head를 attest하고 reset 뒤 migration을 증명한다.
## 2026-08-06 (1) — T-VN-35 A-D 병합 (kind별 typed subtype 분해, ADR-086)

`feature.features`의 `detail` JSONB·`geom`을 제거하고 kind별 typed subtype 5종으로
분해했다. 배타 arc(core `UNIQUE(feature_id, kind)` + subtype `kind` 상수 CHECK +
복합 FK)가 "한 feature는 최대 한 subtype"과 "subtype이 있는 동안 core kind 불변"을
구조적으로 강제한다. 응답용 `detail`/`geom`은 `feature.features_detailed` 뷰가
조립한다 — 값이 두 곳에 없으므로 drift라는 개념이 사라진다.

무손실 실증(prod 복원본 731,765행, head→0083→head 왕복): place·event·price·weather
**731,620행 md5 바이트 동일**, notice `valid_start_time` 145/145 동일. 적대 리뷰 2인
P0×2·P1×6·P2×6 전량 반영. alembic `0085`→`0086`→`0087`(main의 `0084_c6c_cancel_probe_
fixtures` 뒤), ADR은 codex와 두 번 겹쳐 084→085→**086**으로 밀렸다.

**다음 한 작업**: 배포 — orchestrator `.env`의
`KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를 **`0087_route_area_subtypes`**로 선행
갱신(안 하면 api가 DB를 건드리기 전에 exit 1이고 dagster/daemon도 뜨지 않는다) →
api → dagster/daemon 재빌드. 그 뒤 Lane A 잔여 `T-VN-37A`(notice `tstzrange` —
35B가 남긴 자리, empty range가 "발효 전 철회"를 정확히 표현한다).
## 2026-08-06 — T-VN-41F1J-A Map fixture 구현·검증·적대 리뷰 완료, PR 게이트 중

`0084_c6c_cancel_probe_fixtures`가 transaction별 fixture/job, canonical cancellation
참조와 `armed → consumed → finalized` 시각 불변식을 영속화한다. Map service API는
`ops:fixture` exact principal으로 ensure/receipt/finalize만 열고, generic
worker·stale recovery·일반 pipeline/ops/live event projection은 fixture kind를
제외한다. 다만 일반 PinVi cancel lineage는 유지하여 canonical unsafe 취소 결과가
같은 transaction에서 fixture receipt로 소비된다. capability generation `2`의
`canonical_unsafe_outcome`은 consumed/finalized canonical result를 immutable receipt로 돌려주므로,
Manager response-loss 재개는 POST 재발송 없이 evidence를 durable write한 뒤 finalize한다. runtime
attestation도 fixture token의 cursor secret 재사용을 명시적으로 거부한다.

**검증**: fixture integration 2건, API auth 103건, event-audit bounded planner target,
OpenAPI export/types drift와 Wave 2 OpenAPI freeze artifact 7건, strict mypy·ruff가 통과했다. 적대적 코드 리뷰 1인이 발견한
event-audit join/직접 event 삽입 누출은 읽기 join이 아니라 DB trigger로 차단해 ordered
partial-index gate를 보존했고, `job_id` filter의 기존 64행 bounded-sort 상한도 회귀로 고정했다.
재리뷰 GO를 받았다. PR CI gate가 남았다.

**다음 한 작업**: Map F1J-A PR #960의 CI gate를 통과·머지한다. 이어
Docker Manager F1J-B의 dynamic ensure→PinVi exact-409→finalize receipt 및 F1J-C
compatible-pair 재결박을 구현한 뒤 n150 격리 리허설과 prod live UI E2E(F1J-D)를
수행한다.
## 2026-08-06 — T-VN-41F1J cancel-probe fixture 설계 착수

F1D의 최초 probe는 `login=200 → etl_summary=200 → provider_sync=200 → cancel=404`로
실패했다. 따라서 PinVi 세션/read route와 Manager runtime은 통과했고, 정적 job UUID에
실행 row가 없다는 Map fixture 수명주기 결손만 남았다. 재시도는 같은 후보의 failure count만
늘리므로 멈춘다.

**다음 한 작업**: T-VN-41F1J-A — Map이 transaction ID별 cancel-probe fixture를 own
DB에 멱등 생성·consume·finalize하고, `ops:fixture` exact service API와 capability
generation을 제공한다. Manager는 이후 dynamic ID와 **정확한** `409
PIPELINE_CANCELLATION_UNSAFE`만 F1D 통과로 수용한다.
## 2026-08-05 (13) — H43 외부 사본·H44 드릴 1회차 (병렬 트랙)

H43 배포 후 기준점 + dev box 외부 사본 반출(sha256 OK), 정기화는 manager
#148. H44 드릴 1회차 완주(복원·manifest 일치·결손 주입/회복 전 단계) —
절차는 backup-restore §10, 주기 실행 트리거만 잔여.

**다음 한 작업**: T-VN-35 A-D 설계·구현(단일 PR) — 4축 조사 중 2축 완료,
서브에이전트 한도로 중단된 상태에서 재개.
## 2026-08-05 (10) — 32C PR-2 prod 배포 완료 (값 전환 라이브)

`8c5bdcf8` 4-이미지 배포(ui 포함)·사후 검증 정상(상세 UUID·batch echo·
trip_card 등식)·curated snapshot 활성 500 전량 재물질화(멱등 확인). dm#128.

⑤ PinVi 재고정 완결(#432 + F1 양성 증명 게이트) · service 재핀은 codex
T-VN-41-F 합류(resume 상단 패키지) · NEW-5 인터록 구현·리뷰 반영(브랜치
feat/t32c-new5-dagster-interlock).

**다음 한 작업**: NEW-5 PR 머지 → ④ live e2e fixture 재생성(새 표면 기준,
생성기 부재 — 축 설계 필요) → T-VN-32C 완전 종결 — 다음 Lane A는 T-VN-35A.
## 2026-08-05 (9) — 32C PR-2 머지 (#952, `8c5bdcf8`)

값 전환 코드 완결 — 적대 리뷰 2인 GO(F1 trip_card echo·H1 scope 해석 500 등
H 2건 포함 전량 반영), CI 8/8(h35 pre-uuid 호환 수정 포함). **배포 미실행.**

**다음 한 작업**: **H30B 재검증(배포 게이트)** → PR-2 배포(api→dagster→ui,
전 표면 원자) → curated snapshot asset 1런 → live fixture 재생성 → PinVi
user 스냅샷 재고정 PR(+CLI --accept-uuid-literals·derivation_enforced 배선·
dagster entrypoint 인터록 유예 동봉).
## 2026-08-05 (8) — 32C PR-2 구현 완료 (응답 값 UUID 전환, 리뷰 대기)

`feat/tvn32c-value-cutover-pr2` — 전 read 표면 치환(cursor legacy 축·echo
보존), write/scope 경계 해석 전수(W1-W8·S1-S13, P0 = 유령 PK·빈 scope·PinVi
missing 오답·sibling 오염 차단), curated snapshot 빌더 UUID화, OpenAPI/types
재생성(service 무변경), ADR-083, 테스트(API 1076 passed·통합 13 신규).

**다음 한 작업**: CI-parity 배터리 → 적대 리뷰 2인 → PR 생성·CI·머지 →
배포(H30B 재검증 게이트 선행, api→dagster→ui, curated asset 1런, live
fixture 재생성, PinVi user 스냅샷 재고정 PR + 유예 ②·NEW-3·NEW-5 동봉).
## 2026-08-05 (7) — 32C PR-1·쌍 PR 머지 + 0083 prod 배포 완주

Map #950(`2a8642bd`)·PinVi #430(`6325d814`) 머지, 0083 게이트 순서대로 prod
배포 완료: PinVi 선배포 → 사전 점검 0/0 → Map api(0083 적용·healthy) →
dagster·daemon → 사후 검증 전부 정상(`derivation_enforced: false`, 731,733).
EXPECTED_HEAD=0083 재핀은 dm#128 기록. 잔여 유예(CLI 플래그·derivation_enforced
배선·service 스냅샷 재추출)는 PR-2 동봉.

**다음 한 작업**: **PR-2(응답 값 전환 — read 표면 단일 원자 릴리스, 설계 §4

- NEW-2/3/5·F5 체크리스트)**. 부수: 신규 ingest 행 v7 확인(배포 직후 행은 구
  dagster 마지막 쓰기라 ver=5 — 다음 ingest부터 v7 기대).
## 2026-08-05 (6) — 32C PR-1(비파생 UUIDv7 generator) 구현·리뷰 반영 완료

0083(파생 CHECK 해제+선언적 사본 일치 CASCADE FK+v7 generator)·app 전환·PinVi
수용(파생 등식 폐기·cutover 리터럴 opt-in)·golden 개정까지 구현, 적대 리뷰
2건(NO-GO) findings 전량 반영. 검증 전부 green(unit 2015·API 1082·통합 배터리).

**다음 한 작업**: 리뷰어 재판정 → PR-1 머지 → PinVi 쌍 PR(golden 재vendor·핀
+검증 완화, branch `feat/tvn32c-nonderived-accept` 준비됨) 머지+배포 → 0083
배포(api→dagster 순서 강제) → **PR-2(응답 값 전환 — read 표면 단일 원자
릴리스, 설계 §4 참조)**.
## 2026-08-05 (5) — H42·H45 판정 완료 (KMA 전 job 전환·값 유입 개시)

근본 원인 2(data.go.kr 평문 HTTP 사멸) 실측 → lib 정본 https 전환(kma#23·airkorea#6)
→ Map 핀 #948(`70c58576`, alembic <1.19 천장 동봉) → dagster 재배포. **KMA 4종 전부
SUCCESS 전환**, weather 값 55,755 유입·grid feature 305 생성 개시. airkorea만 upstream
자체 504(코드 무관, 스케줄 자체 수렴 관찰). **H42 최종 수치 고정: features 731,724 =
public = aliases, 41C 선행 조건 충족.** H42·H45 종결.

**다음 한 작업**: ① **32C 값 전환 tail PR**(feature_id UUID 전환·비파생 generator·
0080 CHECK/0079 트리거 재평가·PinVi user/admin 스냅샷 재추출 — 적대 리뷰 2),
② H44 복원 드릴, ③ 백로그(alembic 1.19 적응·khoa 확대·coalesce·RetryBudget 튜닝).
## 2026-08-05 (4) — prod 배포 완료 + 32C checksum 게이트 통과

Map `c0afaa4e`(0082·UUID backfill 100%·fence dump 선행)·PinVi `3ff54b8b`(0049,
release-export 함정 수리) 배포, cutover dry→real로 **양 저장소 checksum 일치**(root
`8bd9534a…`, 731,600) + trip_day_pois 26행 shadow 채움. CSV5 재import로 미해석
290→270(잔여는 H31 확정 103 + provider 수렴 대기). H45 판정 진행 중(재시도
텔레메트리 실작동 확인, 첫 주기는 upstream 열화 창 — 감시 지속).

**다음 한 작업**: ① H45 판정(스케줄 SUCCESS 전환 관찰) → H42/H45 docs closure,
② **32C 값 전환 tail PR**(Map 응답 feature_id UUID 전환·비파생 generator·0080
CHECK/0079 트리거 재평가·user/admin 스냅샷 재추출 — 적대 리뷰 2), ③ H44 복원 드릴.
## 2026-08-05 (3) — H45 머지·main 수리·H43 기준선 완료

H45 #943 머지(`8c74d911`, 재리뷰 2건 GO) + #940 잠복 결함(user-client types 재생성 누락 —
전 코드 PR type-check 파손) #944 수리. H43 기준선 dump 완료(n150 435MB, sha `717790c0…`,
manifest에 public_api_keys=1 확인, runbook §9 신설). Lane A 배포-비의존 작업은 소진 —
32C tail·H42 KMA axis·H45 판정·41C enable 모두 **다음 이미지 배포(dm#128) 게이트**.

**다음 한 작업**: (사용자/docker-manager) Map 이미지 `8c74d911`+ 배포 → 0080~0082 자동
적용 → H45 스케줄 SUCCESS 판정 + PinVi 배포·cutover(32C tail) → H42 docs closure →
H44 복원 드릴(H43 dump 실복원).
## 2026-08-05 (2) — T-VN-H45: KMA/airkorea 만성 실패 근본 원인 격리·강건화 착지

쿼터 리셋 후 지속 실패 + 컨테이너 내부 4종 upstream 직접 프로브 전부 200 정상의 모순으로
구조 결함 확정: timeout 10s 고정 × 격자 N(187+) all-or-nothing 순차 호출 × step 전량 재시도
= 시도당 생존확률 p^N 붕괴. 단건 호출 경계 유한 재시도(`upstream_retry.py`) + client 3종
timeout 주입(기본 30s)으로 수정 — 부분 실행 금지·원예외·cursor 비전진 불변. dagster 542
passed·mypy strict·적대 리뷰 2명. prod 효과는 다음 배포(dm#128 타이밍) 뒤 스케줄 SUCCESS
전환으로 판정.

**다음 한 작업**: H45 PR 머지 → (배포 대기 중) H43 백업 체계 선행 준비 가능분 →
배포 후 H45/32C tail/H42 KMA axis 일괄 판정.
## 2026-08-05 (1) — H42 중간: MOIS/opinet 수렴 완료, 공개 key 재발급, KMA 스케줄 감시

MOIS 702,955 3중 일치(6h run 한도로 FAILURE 마감이나 데이터 완주)·opinet 934건 공개 smoke까지
실측. 재생성 때 소실된 공개 API key(`ops.public_api_keys` 0행 — 전 표면 401)를 재발급하고 n150
`~/.secrets/kor-travel-map-public-api-key`에 보관. KMA 4종+airkorea는 upstream transport 실패
반복 — KST 자정 쿼터 리셋 후 스케줄 수렴 감시 중.

**다음 한 작업**: KMA/airkorea 스케줄 수렴 판정(리셋 후에도 실패 지속 시 key/계약 재조사) →
H42 docs closure → H43(백업 체계 — `ops.public_api_keys` 스코프 필수 반영).
## 2026-08-04 (9) — T-VN-32 쌍 PR 착지 + ⓪ L7 스캔 0건

Map #940(`e12494bd`, 0080~0082 재부모화 포함)·PinVi #428(`3ff54b8b`, 핀·snapshot
회전 포함) 머지로 32A/B/C 구현·계약 표면이 양 저장소 정본에 착지했다. ⓪ L7
사전 스캔은 prod 467,697행 중 UUID-형태 legacy id 0건으로 클리어. 배포 결선
예고는 docker-manager#128(EXPECTED_HEAD=`0082` + PinVi env 2종, Map 먼저).

**다음 한 작업**: 32C 잔여는 배포 게이트 — Map 이미지 배포(0080~0082 적용) 후
PinVi 배포+`pinvi-feature-uuid-cutover`(dry-run 선행) → checksum 일치 → UUID 값
전환 tail. 그 전까지 Lane A 진행 순서는 H42 수렴 판정(MOIS/opinet 적재 완료
후) → H43(백업 체계) → H44(복원 드릴).
## 2026-08-04 (8) — T-VN-32C 전반부(이관 표면·checksum 계약·write fence) 완료

PinVi alias-map DB-to-DB 이관의 Map 측 표면을 착지했다: service read 2종
(`GET /v1/service/feature-alias-maps`(+`/checksum`) — keyset 페이지 + merkle
root, `require_service_token`/route_policy SERVICE) + `feature-alias-map-v1`
checksum 순수 계약(`core/feature_alias_map.py`) + 양 저장소 공용 golden
(`contracts/feature-alias-map-v1-golden.json`) — PinVi 쌍 branch
`feat/tvn32c-uuid-alias`가 독립 구현(`app/core/feature_alias_contract.py`)으로
같은 vector를 재계산·대조하고, 검증된 이관 실행기
(`pinvi-feature-uuid-cutover` — pull→독립 checksum·파생 검증→3열 rewrite)와
UUID shadow 컬럼 migration을 준비했다. legacy write fence는 alembic
`0082_legacy_write_fence`가 alias map 불변(UPDATE/직접 DELETE 거부, CASCADE만
허용)·identity 불변(feature_id/feature_uuid UPDATE 거부)을 DB 트리거로
fail-close — 0079 트리거 2종은 재평가 후 유지(근거는 0081 docstring·journal).
OpenAPI admin/service 재생성 + diff artifact 재고정.

**다음 한 작업**: T-VN-32C 잔여 — 두 PR 머지 후 ⓪ legacy `feature_id`의
canonical UUID 형태 값 실재 스캔 1회(shadowing 확인, 리뷰 L7) → ① PinVi 배포 +
`pinvi-feature-uuid-cutover`(검증된 이관) → ② 양 저장소 checksum 일치 → ③ Map
응답 `feature_id` 값 UUID 전환·비파생 generator 채택·0080 CHECK/0079 트리거
제거 재평가 → ④ PinVi vendored snapshot 3종 재추출·핀(merge SHA) 갱신
(+ 새 alias-map golden 핀 `_UPSTREAM_MAP_COMMIT` 고정, contract-pin-consistency
diff 단계 추가). legacy 물리 제거는 T-VN-39. 운영 상시:
`count_features_missing_identity` 정기 관측(리뷰 M4).
## 2026-08-04 (7) — T-VN-32B Map consumer-first dual read/write 완료

경계 alias 해석(`infra/feature_identity.resolve_feature_identity` — legacy/UUID
양형식, 형식 오류 422·미해석 404)을 공용 헬퍼(`api.feature_ref`)로 **모든
feature `{feature_id}` 경로**(user detail·sources·observations·weather·price·
contained / admin detail·revision·weather·price·PATCH·DELETE·deactivate)에
연결했다 — 내부 전달은 정본 키로만, 중복 존재 확인 쿼리는 제거. repo 읽기
경로(단건/bbox/search/nearby/service batch/admin 목록·상세)와 notice lineage
(`public_active_notice_feature_identities` — 기존 ids 표면은 제거)가
`feature_uuid`를 additive 병행 노출한다(alembic `0081_uuid_dual_read`로 공개
view 재고정). **dual 기간 정본 generator = uuid5 파생(UUIDv7 미채택) 결정**을
`0080` CHECK 2종으로 DB 층에서 강제(파생 불일치 write는 SQLSTATE 23514
fail-close, 32C에서 제거하는 한정 fence) + writer 명시 INSERT·RETURNING 대조
(`FeatureIdentityInvariantError`), 0079 트리거는 편의 fill로 유지. 응답
`feature_id` 값은 legacy 유지(전환은 32C — consumer-first 규율). OpenAPI 3
spec 재생성 + diff artifact baseline 재고정(`revisions` 기록). 동반 수정:
perf gate tier1 frozen shape 재고정 + H35 cutover 도구 head 등호 고정 →
campaign target(0078) 앵커 수정(32A가 만든 본 branch 잠복 회귀). 검증: unit
1,981 · api 1,069 · 신규 통합 9 · 회귀 통합 green(잔여 실패는 live geo 인증
미결선·lock-poll env·부하 flake — base 재현/단독 green으로 32B 무관 판정) ·
export --check · ruff/mypy --strict/lint-imports clean. 상세는 tasks.md 완료
기록·journal (7).

**다음 한 작업**: `T-VN-32C`(PinVi alias-map cutover·legacy write fence) —
PinVi를 UUID+alias contract로 선전환(검증된 alias map DB-to-DB 이관), 양 저장소
checksum 일치 후 Map 응답 UUID 전환 + legacy write fence. PinVi vendored
snapshot 3종(user/service/admin-detail) 재추출은 32C 쌍 PR에서.
## 2026-08-04 (6) — T-VN-32A UUID identity shadow 완료

Wave 2 Lane A 첫 구현 task. alembic `0080_feature_uuid_shadow`로
`feature.features.feature_uuid`(결정적 backfill → NOT NULL + UNIQUE)와
`feature.feature_aliases`(legacy alias 1:1, freeze §4 제약명 정합)를 추가했다.
freeze 미정 3건을 결정(생성기 uuid5 파생·DB default 없음 / alias_kind 닫힌
CHECK / FK ON DELETE CASCADE — 근거는 0079 docstring·journal). 신규 INSERT는
트리거 2종이 uuid+alias를 원자 생성(32B writer 명시 값 존중). 검증: unit
1,970 · 신규 통합 8 · 회귀 트리오 23 · freeze 3 · alembic check 30 · ruff/
mypy/lint-imports clean.

**다음 한 작업**: `T-VN-32B`(Map consumer-first dual read/write) — UUID 정본
읽기·alias 경계 해석·신규 write의 writer 측 원자 생성(트리거 대체)·정본 신규
행 generator(UUIDv7 여부) 결정.
## 2026-08-04 (5) — T-VN-31A/B/C vNext target freeze 완료

Wave 2 barrier의 freeze 3종을 완료했다. `contracts/vnext/` artifact 8개(목표 DDL·
불변식·fingerprint·OpenAPI diff·consumer rollout·위반 fixture·기대 rejection·복구
preflight)와 fail-close 테스트 2본(`tests/integration/test_vnext_target_freeze.py`,
`tests/unit/test_vnext_contract_artifacts.py` — unit job이 매 PR artifact bytes를
고정). ADR 침묵 세부는 전부 `미정(T-VN-XX 구현 소관)`/`deferred-to-implementation`
표기(발명 금지 원칙, tasks.md T-VN-31 블록 참조). 검증: unit 1,963 passed ·
freeze 통합 3 passed · mypy --strict clean.

**다음 한 작업**: Wave 2 진입 — Lane A `T-VN-32A`(UUID schema·deterministic
backfill). freeze artifact가 머지된 뒤에만 시작한다(barrier 규율). freeze의
`미정` 목록이 각 구현 task의 첫 결정 대상이다.
## 2026-08-04 (4) — 이월 기록: H35·41C prod live 검증 미수행 → H42~H44 배치 (docs-only)

이번 사이클에 수행하지 못한 것 2건을 명시 이월 — **H35 prod live 검증**(공개 표면 DB
실측 4,620까지만, live 스모크·quarantine 0·수렴 후 최종 판정 미수행)과 **T-VN-41C prod
live 검증**(재pin #109 = `2b2dee95` 완료 + 재적재 안정화 뒤로 유예). tasks.md Lane A
**a2(운영 연속성)**로 `T-VN-H42`(재적재 완주·수렴 + H35 live 잔여, 41C 선행 조건) →
`T-VN-H43`(백업 체계 — rollback 기준선 dump) → `T-VN-H44`(복원 드릴 정기화)를
신설·배치했다.

**다음 한 작업**: T-VN-31 PR(#938) 리뷰 반영 진행 중 → 머지 후 `T-VN-32A`.
**병행 트랙**: `T-VN-H42` — provider 일일 스케줄 수렴 감시(MOIS bulk는 dedup 룰 검증
후, opinet은 scope 제한 quota 준수) → CSV 290행 재import → prod live 스모크·공개 표면
최종 수치 고정.
## 2026-08-04 (3) — CSV5 완료(공개 4,620)·H22 머지·H30B 완료

#934(H22 단일 PR) 머지. CSV5 재적재 완료 — 공개 표면 4,620(source_rule 4,424 +
csv_explicit 196), H35 실행 종료(잔여는 provider 일일 스케줄 수렴뿐). H30B 재정의판
전 acceptance 실증 완료(결손 1,481 → 완전 회복·멱등, 상세 tasks.md 완료 기록).

**다음 한 작업**: Lane A a1 소진 — H34 잔여 1항목(H35 대기였던 것) 해제 검토 후,
Wave 2 barrier freeze(T-VN-31A)로 진입. codex 41C prod enable 경계는 재pin(#109) 대기
유지.
## 2026-08-04 (codex) — T-VN-41D의 0079 schema regression 정렬

Map PR #935의 PostGIS CI는 858 passed/5 skipped 뒤, obsolete H35 helper가 저장소 head를
`0078`로 고정한 탓에 preflight를 거부했다. `0079`가 DB에 적용되기 전의 거부였지만 새
migration을 머지할 수 없는 실제 계약 drift였다. prod H35 cutover를 되살리지 않고, helper의
**isolated regression target만** `0079_cache_target_writer_drain`·`schema_0079`로 승격했다.

목표 schema/boundary를 `_h35_schema_version.py`로 단일화하고 receipt chain 전체가 그 값을
공유하게 했다. 적대 리뷰의 P1에 따라 CSV5가 받는 migrate receipt의 시작 schema도 정확히
`0063`으로 고정해 0078→0079 intermediate receipt를 fail-close한다. H35 semantic catalog에는
lease·instigation·run의 relation/column/constraint/FK/index를 포함했고, marker fixture는 전용
collection 한 개만 변이하도록 고쳤다. unit 65건과 isolated PostGIS `0063→0079→CSV5→GC→verify`,
head partial probe, quarantine boundary·preflight 4건(총 69건)이 통과했으며 production/n150에는
접근하지 않았다.

**다음 한 작업**: PR #935의 수정 commit을 적대 리뷰 1건으로 확인하고 CI를 다시 통과시킨다.
