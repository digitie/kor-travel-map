# journal-2026-08a.md — journal.md 아카이브 (2026-08-14 ~ 2026-08-27)

> `docs/journal.md`에서 2026-08-31 분리(규약 §8). 읽기 전용 이력.

## 2026-08-27 — M05 external membership terminal의 불변성 보존

`c6c73cdf…` candidate는 n150에서 정확히 한 번 실행되어 `map_runtime_ready` 뒤
`role_catalog_reset_failed/foreign_membership` terminal로 보존됐다. raw stderr·membership row·catalog 값은 열지 않았고
같은 candidate를 재실행하지 않는다. PostgreSQL `DROP ROLE`는 membership을 자동 철회하지만 target 밖 role이 얽히면
외부 principal의 authorization 관계가 바뀐다. 따라서 target 네 role 내부 edge만 수용하고 외부 membership은
계속 fail-close한다. 두 전문 적대 리뷰에서 이 판단을 재확인했으며, 운영 권한 결정 전에는 새 candidate를 만들지 않는다.
## 2026-08-27 — M05 target 내부 membership grantor terminal 보정

`b22bfb8c…` n150 candidate는 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/foreign_membership` terminal로 보존됐다. raw membership row·catalog 값·stderr는 열지
않았고 같은 candidate를 재시도하지 않는다. 원인은 reset이 target 네 role 내부 membership edge도 grantor가
bootstrap owner가 아니면 외부 의존으로 오판한 조건이었다.

PinVi [#500](https://github.com/digitie/pinvi/pull/500)의 `a619d037…`은 roleid/member가 모두 target 네 role인 edge만
수용하고, 어느 하나라도 target 밖이면 계속 fail-close한다. Manager [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)의
`fd75950…`은 이를 Map `9c64e862…`와 새 pinset `89330403…`으로 결박한다. PinVi unit 19건·PostGIS integration
1건과 Manager focused 회귀 179건, 두 전문 적대 리뷰가 모두 통과했다. 새 source CI·n150 committed/live E2E가
성공하기 전에는 두 코드 PR을 merge하지 않는다.
## 2026-08-27 — M05 reset isolation terminal의 고정 원인 영수증

`31fe73ad…` n150 candidate는 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/target_not_isolated` terminal로 보존됐다. 같은 pinset의 journal·DB·permit·result는
재사용하거나 수정하지 않았다. 진단은 허용된 durable journal 필드만 사용했으며 raw stdout/stderr와 DB catalog
값은 열지 않았다.

PinVi [#500](https://github.com/digitie/pinvi/pull/500)의 `9e438611…`은 identity, namespace, extension, object,
role dependency를 고정 enum 하나로만 영수증에 쓴다. Manager [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)는
transaction·pinset·inode 결박을 통과한 enum만 terminal journal에 보존한다. PinVi unit 19건 및 PostGIS integration
1건, Manager focused 회귀 179건을 통과했다. Map `9c64e862…`·PinVi `9e438611…`의 `b22bfb8c…`만 다음 official
candidate이며, CI·두 전문 적대 재리뷰·n150 committed/live E2E가 모두 성공하기 전에는 두 코드 PR을 merge하지 않는다.
## 2026-08-27 — M05 identity DTO terminal을 새 pinset으로 분리

`37932169…` n150 candidate는 정확히 한 번 실행되어 `map_runtime_ready` reset intent 뒤
`role_catalog_reset_failed/unclassified` terminal로 보존됐다. result receipt가 없으므로 PinVi reset one-shot은
실행되지 않았으며, candidate·journal·DB·permit을 재시도하거나 수정하지 않는다. 원인은 Manager가 live
`PinnedDatabaseIdentity`와 journal `PinnedRuntimeDatabaseIdentity`를 직접 비교해 equality가 항상 false가 된
경계 오류였다.

Manager [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)은 live identity를 journal DTO로
변환한 뒤 비교하도록 보정했다. PinVi [#500](https://github.com/digitie/pinvi/pull/500)의 immutable
`28ca250d…`과 Map `9c64e862…`의 새 pinset `31fe73ad…`만 이후 trusted n150 candidate가 될 수 있다.
## 2026-08-27 — M05 result receipt source·pinset 재회전

PinVi [#500](https://github.com/digitie/pinvi/pull/500)의 immutable `fc01e5d6…`은 Manager-owned `0600`
result file에 transaction/pinset-bound fixed JSON만 기록하며, disposable PostGIS Compose에서 strict
target isolation 거부와 성공 영수증을 모두 확인했다. Manager [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)는
그 파일의 owner-only metadata와 최초 inode를 확인한 뒤 fixed JSON을 strict parse한다. stdout/stderr는
진단 입력이 아니다.

Map `9c64e862…`·PinVi `fc01e5d6…`의 새 pinset은 `37932169…`이다. historical `cbb`·`52`·`06045`·
`68d99705`·`285618c0` candidate는 모두 재시도하지 않는다. 두 코드 PR의 CI·전문 적대 리뷰·trusted Manager
release가 모두 준비된 뒤 이 새 pinset을 n150에서 정확히 한 번 실행하고, committed live E2E가 통과하기 전에는
merge하지 않는다.
## 2026-08-27 — M05 `template0` fresh candidate로 재결박

n150에서 `68d99705…` pinset의 approved `rebuild-pinned --confirm --json`을 정확히 한 번 실행한 결과는
`map_runtime_ready` 뒤 PinVi role-catalog reset terminal이었다. journal·tombstone·DB·permit을 보존하며 해당
pinset을 재시도하지 않는다. 두 전문 적대 리뷰는 Manager가 PinVi DB를 기본 `template1`에서 만들지만 PinVi reset이
`template0` 수준의 empty catalog만 허용한 P1 계약 불일치를 확인했다.

Manager [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)은 PinVi create에만
`--template template0`을 적용했고, PinVi [#500](https://github.com/digitie/pinvi/pull/500)은 같은 source
precondition을 immutable `0b903701…`에 기록했다. Map `9c64e862…`·PinVi `0b903701…`의 새 pinset
`285618c0…`은 old terminal namespace와 분리된다. PinVi CI, trusted Manager release, 새 pinset candidate 1회,
committed evidence와 n150 live E2E가 모두 성공하기 전에는 두 코드 PR을 merge하지 않는다.
## 2026-08-27 — M05 fresh candidate의 immutable base image fail-close 원인 확정

Map `cf65e973…`·PinVi `97d2f924…` v5 pinset `872e3262…`의 trusted 공식 candidate는 API receipt 발행 전
generic paired builder 오류로 fail-close했다. 이후 안전 진단은 output을 파싱하지 않고 private receipt 존재만으로
API receipt 부재를 fixed class로 분류할 수 있지만, 이를 당시 실행 원문으로 소급하지 않는다. 동일 pinset의
자동·수동 재시도, raw builder 로그·credential·path의 기록은 하지 않았다.

같은 exact Map source의 sealed API candidate builder는 로컬 Docker에서 receipt와 immutable image를 정상
발행했다. n150 read-only 확인에서는 API Dockerfile의 exact `python@sha256:…` base가 Docker image store에
없었다. candidate script가 `--pull=false`와 exact base inspect를 강제하므로 Docker/Compose/DB/journal mutation
전에 닫힌 것이다. 다음 변경은 manual pull이 아니라 trusted Manager preflight가 digest-pinned base를 provision·
재관측하도록 하는 별도 PR이며, fresh source pinset에서만 다시 실행한다.
## 2026-08-27 — PinVi M05가 소비하는 Admin provenance identity 계약 정정

PinVi M05 paired attestation의 실제 reader는 `GET /v1/admin/features/{feature_id}/creation-provenance`다.
M05 reconciliation event/evidence의 `feature_id: string`/`feature_uuid: uuid` 계약은 이미 맞았지만,
이 Admin provenance 응답만 최상위 `feature_id`를 UUID로 치환해 opaque ID와 UUID 축을 구분하지 못했다.
이는 storage reader가 아니라 HTTP projection의 `UUID(provenance.feature_id)` 변환 문제다.

resolver가 canonical opaque ID와 UUID를 같은 identity로 반환하고 reader가 UUID로 evidence를 결박하는 현재
구조를 유지한 채, 응답은 opaque `feature_id`와 별도 `feature_uuid`를 필수로 반환하도록 정정한다. reader UUID와
immutable claim UUID도 응답 UUID와 각각 대조해 불일치면 fail-close한다. claim/origin UUID 저장 계약·DB schema·과거
revision 복구는 변경하지 않는다.

PinVi PR487은 새 Admin artifact만 vendor해서는 충분하지 않다. attestation이 `provenance.feature_uuid`를 필수
canonical UUID로 파싱해 M05 map-case의 manual/old UUID와 각각 비교하고, 검증된 provenance UUID를 receipt에
기록하는 별도 consumer 수정이 선행돼야 한다. 그 전에는 paired live gate가 fail-close로 유지된다. 생성 OpenAPI와
source SHA-256은 `256b4e668bae8e5d3f81ec1a45d401a79d0a2f5a`의 full/admin artifact
`0a1548a94c80bab1af6ab79c10b6f07eba32450adccd8ec2751a8c5256144c1d`로 확정했다. user/service bytes는
각각 `489b05d3e62e3531233e3e7eb8c97f9ddf92aa1ecf1573b7557a5951e7f6a61b`/
`99ba6c178bf55401d3e1bb638a01b96f66bbac38d604534aa126a70f4be53d3d`로 변하지 않았다.

독립 적대 리뷰 두 건은 Map 내부 P0/P1이 없음을 재확인했다. 한 리뷰 지적으로 reader UUID 또는 immutable claim
UUID 불일치가 helper에서만 아니라 실제 GET 경계에서도 partial evidence 없이 민감 정보를 뺀 RFC7807 500으로 닫히는
회귀를 추가했다. PinVi의 기존 UUID-only consumer/vendored artifact는 그대로 P0 release blocker이며 Map PR의
병합 SHA에서 재-vendor한 뒤에만 consumer/live 작업을 진행한다.
## 2026-08-27 — T-VN-H34A MOIS 인허가 분류 책임 경계 조사

MOIS 인허가 업종과 실제 시설 성격이 다르게 보이는 H34A를 위해 Map source·문서와 로컬
`python-mois-api` catalog를 read-only로 대조했다. `rest_cafes`는 `식품_휴게음식점 데이터 조회`,
`museums_and_art_galleries`는 `문화_박물관 및 미술관 데이터 조회`라는 서로 다른 인허가 service다.
Map의 `PROMOTED_CATEGORY_BY_SLUG`도 이 service slug를 하나의 source category로 보존하며,
시설명·주소·curation 이름으로 원천 의미를 재해석하지 않는다.

따라서 `진해보타닉뮤지엄`처럼 curation link는 맞지만 `02020100`으로 보이는 사례는, 현재 증거만으로
provider bug가 아니다. Map에서 source category를 keyword 또는 사례별로 덮어쓰지 않고, raw record를
포함한 후보 전수 조사 뒤 provider 정합성 PR과 별도 표시/큐레이션 정책 ADR 중 하나로 소유를
결정한다. 운영 DB·CSV·Feature·curation link는 읽거나 쓰지 않았으며 H34B import와도 합치지 않았다.
상세 판단과 다음 read-only 산출물은
[H34A 책임 경계 조사](../reports/t-vn-h34a-category-ownership-audit-2026-08-27.md)에 기록했다.
## 2026-08-26 — Manager #229 신뢰된 release installer의 오프라인 wheelhouse fail-close

Manager [#229](https://github.com/digitie/kor-travel-docker-manager/pull/229)는 fresh PinVi DB role 여섯 값을
신뢰된 root `.env`에만 원자 초기화하고, write 전 lifecycle/C6c/journal admission, 원문 environment snapshot,
`map_runtime_ready` 한정 단 한 번의 rebind receipt를 결선했다. 전체 backend 657건·Ruff·strict Mypy와 보안/Manager
계약 전문 적대 리뷰 2건의 GO 뒤 병합했다.

병합 commit의 깨끗한 checkout만을 source로 공식 신뢰 installer를 실행했으나, root 소유 오프라인 wheelhouse에
`poetry-core` build dependency wheel이 없어 활성화 전에 fail-close했다. installer가 만든 staging/rollback tree는
정리됐고, 활성 Manager release·canonical `.env`·Docker/Compose·candidate/journal·runtime·세 DB를 바꾸지 않았다.
네트워크 의존 설치, 임의 wheel 생성, raw Docker/Compose/SQL, journal/DB 조작은 하지 않았다.

따라서 현재 선행 조건은 검증된 root 소유 오프라인 wheelhouse의 공급 절차다. 그 절차를 별도로 확정하기 전에는
installer나 승인된 `rebuild-pinned --confirm`을 재시도하지 않으며, 새 pinset의 D1/D2/41C acceptance도 재개하지 않는다.
## 2026-08-26 — trusted/runtime boundary follow-up PR #224 대기

새 PinVi #477 pinset의 승인된 Manager rebuild가 DB reset 전 single-file Compose boundary에서 멈춘 뒤,
읽기 전용 topology 확인으로 legacy `docker-compose.override.yml`가 Geo backup 값을 덮고 Concierge UI에
전체 source `.env`를 전달한다는 사실을 확정했다. Docker Manager
[#223](https://github.com/digitie/kor-travel-docker-manager/pull/223)은 병합·trusted `/opt` deployment까지
완료했지만, installed shim의 project root를 retirement가 blanket 거부해 공식 명령은 Docker/DB/runtime 변경
전에 fail-close했다. home Compose YAML과 parent가 user-writable이므로 home root 허용·자동 병합은 P0가 된다.
후속 [#224](https://github.com/digitie/kor-travel-docker-manager/pull/224)는 `/opt` canonical Compose execution
root를 유지하고, legacy override와 고정 Concierge source를 `O_NOFOLLOW`/`fstat` protected C6c stage에 one-way
snapshot한 뒤 그 staged pair만 candidate `.env` write·실제 raw/resolved C6c 검증·owner-only archive·Concierge
API/MCP/scheduler/UI 정확한 네 service 재생성의 입력으로 쓴다.

UI는 더 이상 전체 source `.env`를 받지 않고 exact allowlist, same-origin BFF와 production command만 받는다.
API/UI host network, API loopback command/`12601`, UI auth guard와 build/start command/`12605`도 raw/resolved
계약으로 fail-close한다. pending stage가 있으면 activation도 거부하고 archive 뒤 재생성만 실패하면 candidate와
archive를 유지하며 root-only official retry를 사용한다. #224는 전문 적대 리뷰와 전체 backend gate 뒤 병합됐다.
n150 trusted deployment와 stage/retire 증적 전까지 legacy override 수동 삭제, raw Docker/Compose/SQL, 새
`rebuild-pinned` 재시도는 하지 않았고 application row·건수·업무상 무결성이나 이전 revision 복구도 범위에 넣지 않았다.
## 2026-08-26 — T-FE-MOCK-FLAKE mocked checkpoint inventory 재고정 (Draft)

PR [#1077](https://github.com/digitie/kor-travel-map/pull/1077)는 기준선 경계 정리 뒤
285개로 남아 있던 모의 failure manifest를 현재 suite의 284개와 관측 inventory SHA-256으로
재고정한다. 이 값은 임의로 수를 맞춘 것이 아니다. 변경 전 exact clean checkout에서 전수
mocked checkpoint D를 실행해 284개 브라우저 시나리오가 모두 통과했지만, 이전 285개 manifest와
불일치해 reporter gate가 fail-closed 되는 것을 재현했다.

구현 commit `b2eafbd3`의 새 clean checkout에서 exact npm 12.0.1 install·dependency tree 검증 뒤
자기 소유 frontend image/container/internal network만 사용한 checkpoint D를 단일 worker로 다시
실행했다. 결과는 **284/284 passed**, manifest 일치, expected/actual failure·flake 0,
reporter gate true와 runner exit 0이다. 실행 뒤 owned container·network·image와 임시 runtime
디렉터리가 모두 0임도 확인했다. 운영 UI·기존 runtime·n150 application DB·source pinset과
rebuild journal은 읽거나 쓰지 않았다.

따라서 `T-FE-MOCK-FLAKE`의 mocked 부분은 현재 source에서도 green이지만, 승인된 읽기 전용
자격증명과 허용 origin이 없어 중단된 n150 실제 `/ops/logs` GET-only acceptance는 별도
blocker로 남긴다. 이 PR은 그 live blocker를 우회하거나 완료로 바꾸지 않는다.

전문 적대 리뷰 두 건은 P0/P1/P3 0으로 GO를 판정했다. source/provenance 검토가 발견한
`tasks-done.md`의 285개 기록이 현행 값처럼 읽힐 수 있다는 P2는, 그 값이 PR #1038 당시의
역사적 baseline이고 현행 284개 재고정과 별개임을 같은 PR에서 명시해 해소했다.
## 2026-08-26 — PinVi #477 새 pinset rebuild 미종결 인시던트 기록

Docker-manager PR #219가 회전한 정규 pinset
`cb8d15591480111d7f4cd70398ad46b129e814ad3b9375dfa0fc83562b366752`으로 신뢰된 n150
Manager의 승인된 `ktdctl pinvi-pair rebuild-pinned --confirm`을 실행했다. 최초 실행 뒤
동일한 공식 재개를 한 번만 추가로 실행했으나, 두 경우 모두 0이 아닌 종료로 끝났다. 새 pinset의
v8 journal은 `phase=map_runtime_ready`, `journal_generation=20`이며 `committed` generation을
만들지 못했다. journal의 Map SHA `cc81081ff2e540a6ad9c428a296515e1d79bc316`와 PinVi #477
squash SHA `10efb21ad84b23db2eeb6d09856cda16d3337822`는 expected source authority와 일치한다.

두 전문 적대 리뷰어가 독립적으로 재검토했다. 현 journal에는 bootstrap 실패·schema 확인 실패·Map
runtime 기동 실패를 구분할 비밀 비포함 durable failure receipt가 없으므로, raw 출력 폐기 뒤에는
원인을 안전하게 특정할 수 없다는 결론이다. 추가 `rebuild-pinned` 재시도, raw Docker/Compose/SQL
조작, DB/journal/permit 삭제·수정은 모두 하지 않는다. 읽기 전용 상태에서 두 PostgreSQL만
healthy/running이고 seven runtime은 fail-closed 정리 뒤 종료된 것, OOM과 Docker
`State.Error`가 없는 것만 확인했다.

기존 H300 committed generation은 이전 pinset의 immutable 이력으로 보존하며 새 후보 acceptance에
소급 사용하지 않는다. 새 v6/v8 evidence가 committed되기 전 `T-VN-FINAL-REBUILD`,
`T-VN-41F1D-D1/D2`, `T-VN-41C`, `T-FE-MOCK-FLAKE`의 새 후보 기반 live acceptance는 진행하지
않는다. 이번 incident에서 application row·건수·업무상 무결성은 조회·대조하지 않았고, 이전
revision 또는 DB restore도 수행하지 않았다.
## 2026-08-26 — PinVi #477 다음 후보 source authority 회전 기록

Docker-manager PR #219가 PinVi #477의 squash merge commit
`10efb21ad84b23db2eeb6d09856cda16d3337822`을 다음 v5 candidate의 source authority로 고정하고
canonical pinset을 `cb8d15591480111d7f4cd70398ad46b129e814ad3b9375dfa0fc83562b366752`로
회전했다. Map source `cc81081ff2e540a6ad9c428a296515e1d79bc316`는 유지한다.

이 source 회전은 n150 runtime, H300 committed generation, 기존 v8 journal이나 그 acceptance
근거를 변경하지 않는다. 새 pinset은 detached exact source build, seven-image/three-schema
attestation, 새 v6/v8 evidence와 승인된 rebuild가 `committed`가 되기 전에는 runtime 반영 또는
live acceptance 완료로 주장하지 않는다. 일반 application row·건수·업무상 무결성 검증은 이
후보 전환의 gate가 아니다.
## 2026-08-26 — T-FE-MOCK-FLAKE n150 logs live 인증 blocker 재확인

n150의 현재 Map source에서 `logs.live.spec.ts` 하나를 실제 공개 UI 대상으로 단일 워커,
재시도 없이 실행했다. 이 spec은 로그인 뒤 `/v1/ops/system-logs`와
`/v1/ops/api-call-logs`를 `GET`으로만 조회하고 UI 필터도 `GET` 전용 상태만 바꾼다.
그러나 local-only 런북의 현 자격증명으로 auth setup 로그인 응답이 다시 `401`이어서 두
본문 시나리오는 시작하지 않았다.

이는 mocked `/v1/ops/logs` 6/6 checkpoint나 H46H의 data-independent 실제 UI 11개 통과를
무효화하지 않지만, 실제 logs acceptance를 완료로 승격할 근거도 아니다. 현 배포 runtime과
일치하는 승인된 읽기 전용 자격증명·허용 origin을 별도 승인 근거가 제공할 때만 재개한다.
자격증명 추측·회전·우회 및 기존 스모크 자격증명 재사용은 하지 않았다. 전용 임시 경로의
브라우저 storage state·screenshot·error context는 실행 종료와 함께 폐기했고 application row나
업무 데이터는 쓰거나 대조하지 않았다.
## 2026-08-26 — H46H 후속 PinVi protected-route 재차단 교차 기록

Manager PR #213 merge `0fb41f9c626fb2bdd82b818b62da25f87c3de057`의 n150 PinVi exact runtime
검증 결과를 교차 기록한다. 현재 admin live credential로 `/admin`에 로그인한 뒤 브라우저
context의 `/auth/logout` 응답 `204`를 확인하고, 같은 context에서 `/admin/features`에
재진입했을 때 최종 경로가 `/admin/login`으로 유지됐다. 이 검증은 인증·세션 상태만 확인하고
application row나 PinVi 업무 데이터를 쓰지 않았다.

PinVi WebSocket/mutating loop와 consumer reconciliation은 `T-VN-41C`·
`T-VN-41F1D-D2` 및 Manager `MAP-LIVE-FOLLOWUP`의 남은 active 조건이다. 300 이후 일반
application row의 내용·건수·업무상 무결성 검증은 수행하지 않으며, 필요하면 fresh schema에
source/ETL을 처음부터 재적재한다.
## 2026-08-26 — H46H 후속 Map protected-route 재차단 확인

n150 Map UI에서 현재 Manager smoke credential로 login한 뒤 `/ops/datasets`를 열고 logout을
실행했다. login 응답은 `200`, logout 응답은 `200`이었고, 같은 session으로 protected
`/ops/datasets`를 다시 열었을 때 최종 경로가 `/login`으로 유지됐다. 이 수동 browser check는
session/auth 상태만 확인하고 application row나 PinVi 데이터를 쓰지 않았다.

PinVi equivalent reblock, PinVi WebSocket/mutating loop와 consumer reconciliation은
Manager의 `MAP-LIVE-FOLLOWUP` 및 이 저장소의 `T-VN-41C`·`T-VN-41F1D-D2` 후속 조건으로
남긴다. 300 이후 일반 application row의 내용·건수·업무상 무결성 검증은 수행하지 않으며,
필요하면 fresh schema에 source/ETL을 처음부터 재적재한다.
## 2026-08-26 — T-VN-H46H `300` baseline·n150 fresh rebuild 최종 수락

Map PR #1066 exact head `cc81081ff2e540a6ad9c428a296515e1d79bc316`와 Docker-manager PR #207
merge `ecfbddb7b3d1afbd74646abbaa4082dd70b53a42`를 고정한 paired candidate를 n150 trusted
Manager 설치본에 반영했다. PinVi `27fe2043b7b8e747fbb42d91e461ea462f930bb7`를 포함한
canonical pinset digest는 `14a9a512836a48489146dc2bb0a04de309cf451b274b934d79805d171f83a193`다.

승인된 `ktdctl pinvi-pair rebuild-pinned --confirm`은 세 DB를 fresh하게 재생성하고 runtime을
재기동한 뒤 durable journal `version=8`, generation `32`, transaction
`5121a6d2-692d-4bd9-a5b0-d572d58c0f8f`, 최종 `phase=committed`로 끝났다. Map·PinVi runtime과
DB identity/provenance/readiness를 확인했으며, 일반 application row의 내용·건수·업무상
무결성은 조회·대조하지 않았다. 이전 revision/기존 DB 복구도 수행하지 않았고, 필요하면
fresh `300` schema에 source/ETL을 처음부터 재적재한다.

n150 실제 브라우저 login setup과 data-independent live UI를 실행해 scenario catalog,
backup-only 정책(`execute=false`), 운영 홈, 운영 로그 **11개 테스트를 모두 통과**했다. Features의
초기 목록·검색·필터·정렬·반응형·딥링크도 통과했지만, 고정 ID·컬렉션·두 번째 페이지를 요구하는
테스트는 빈 fresh schema의 데이터 의존 항목이므로 이 baseline 수락 게이트에서 제외했다.

후속 범위 확인으로 `ops-c7-read-auth.live.spec.ts`의 실제 logout UI 단일 시나리오도 n150에서
통과했다. 현재 socket이 logout 응답 전에 닫히고 `/login`으로 이동하는 것만 확인했으며, 이
실행은 application row를 쓰지 않았다. PinVi WebSocket/mutating loop·consumer reconciliation과
data-dependent D2는 별도 순서의 active acceptance로 남긴다.

같은 파일에서 행 쓰기 없이 ticket 없는/서명 변조 `4401`, expired ticket `4408` 뒤 fresh BFF
lease 복구, healthy socket의 자연 `4408` rotation 세 시나리오도 n150에서 통과했다. 이 결과는
Map ops-live WebSocket wire/재연결 계약만 증명하며, PinVi mutating loop·consumer reconciliation과
data-dependent D2의 완료를 의미하지 않는다.

이 기록으로 H46H의 schema/bootstrap·runtime provenance·data-independent UI 조건은 완료한다.
전체 운영 순서는 `T-VN-FINAL-REBUILD` 후속 barrier → `T-VN-41F1D-D1`/`T-VN-41F1D-E`
→ `T-VN-41F1D-D2` → `T-VN-41C`이며, logout/re-block·PinVi paired/WebSocket·consumer
reconciliation과 M01~M05·T-VN-39 cutover 조건은 계속 열린 task로 유지한다.
## 2026-08-25 — T-VN-H46H paired builder 실행 모드 고정 (Draft)

n150의 exact Map `dd2ee61f…` sealed source에서 paired builder를 실행할 때 내부
`scripts/build-application-300-candidate.sh`가 Git 모드 `0644`로 materialize되어
`Permission denied`가 발생했다. outer paired builder가 이 파일을 직접 실행하므로
파일 모드를 `100755`로 정본에 고정하고 실행 가능 회귀 테스트를 추가한다. 이는 source
bytes·application contract·300 schema semantics를 바꾸지 않으며, application row
무결성 검증을 release gate에 추가하지 않는다.

- 변경: `scripts/build-application-300-candidate.sh` 실행 모드 `100755`
- 검증: paired candidate unit static contract와 `git diff --check`
- 후속: 새 exact Map SHA를 Manager v5 release pinset으로 회전한 뒤 n150 rebuild 재개
- 두 `uv.lock`은 열람·수정·stage하지 않음
## 2026-08-25 — T-VN-H46H full integration cluster 격리 보강 (Draft)

PR #1064의 unit matrix는 통과했지만 full PostGIS integration에서 role-bootstrap 6건이
실패했다. 원인은 application row가 아니라 session `pg_engine`·`migrated_engine`이 cluster 전역
`ALTER ROLE CURRENT_USER SET search_path`를 남겨 fresh `template0` target의 database/role
setting precondition을 오염시킨 것이었다. 두 fixture 모두 fixture 전용 database-level setting으로
전환했다.

role·membership·password·default ACL은 database가 아니라 cluster 전역이므로, bootstrap guard
테스트는 shared integration cluster에서 분리한 동일 digest PostGIS module fixture를 사용한다.
target DB를 먼저 `DROP DATABASE ... WITH (FORCE)`한 뒤 disposable role만 `DROP ROLE`하며, shared
admin DB에서 `DROP OWNED`를 실행하지 않는다. 그 명령은 다른 fixture의 feature/ops/x_extension
schema와 extension dependency를 건드릴 수 있다.

- migrated_engine 선행 후 role-bootstrap 회귀: `20 passed`
- 변경 파일 Ruff·`git diff --check`: 통과
- 두 `uv.lock`은 열람·수정·stage하지 않음
- 일반 application row 무결성은 여전히 release gate가 아니며, 필요하면 fresh `300` schema에
  source/ETL을 처음부터 재적재한다.
## 2026-08-25 — T-VN-H46H PostGIS CI image drift·teardown 재현 및 수정 (Draft)

PR #1064의 최신 PostGIS 게이트는 단위 테스트는 통과했지만 통합 단계에서만 실패했다.
원인은 행 데이터 검증이 아니라 `postgis/postgis:16-3.5-alpine` 부동 태그가 기준
receipt를 만든 image와 달라져 catalog receipt·role setting precondition이 함께 달라진
것이었다. 통합 fixture image를 기준 source image digest
`sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c`로 고정해
schema/bootstrap receipt가 동일한 PostgreSQL/PostGIS 입력에서 실행되도록 했다.

성공적인 role bootstrap 뒤 extension이 `x_extension`에 남아 있는 상태에서 `DROP OWNED`
를 먼저 실행하면 teardown이 의존성 오류를 냈다. fixture cleanup은 fresh database를
먼저 강제 삭제한 뒤 cluster role을 정리하도록 순서를 고쳤다. 로컬 검증은
role-bootstrap `19 passed`, fresh-300/Alembic `3 passed`다. 전체 integration은 로컬
환경에 Dagster 패키지가 없어 collection 단계에서 중단됐고, Dagster가 설치되는 CI에서
재실행한다.

이번 수정은 사용자가 정한 대로 `300` 이후 application row의 무결성 검증을 추가하지
않는다. immutable receipt는 image가 고정된 schema·role·ACL·extension·필수 고정 seed와
operation replay 경계만 확인한다. 필요 시 새 schema에 원천 데이터를 처음부터 재적재한다.
## 2026-08-25 — T-VN-H46H PostGIS fixture와 locale canonicalization CI 복구 (Draft)

PR #1064의 PostGIS 실패를 조사해 공통 원인을 재현했다. `postgis/postgis:16-3.5-alpine`의
image-created `test` DB는 `template_postgis`의 public/topology extension을 포함해
ADR-008 `x_extension` precondition을 깨고, role-bootstrap 테스트는 새 preflight helper를
컨테이너에 복사하지 않아 credential 검증 전에 중단됐다. session fixture가 `template0` fresh
DB를 만들고 root credential을 URI-unreserved 길이로 교체하며, bootstrap과 preflight 파일을
동시에 설치하도록 수정했다.

glibc image는 baseline의 alpine PostGIS 3.5.6과 다른 3.5.2라 catalog receipt를 공유할 수
없음을 확인했다. 해당 테스트는 baseline migration을 호출하지 않고 alias-map 최소 표면만
생성해 실제 `COLLATE "C"` keyset·checksum을 검증한다. immutable catalog/seed sidecar의
locale-sensitive ACL·text ordering은 `COLLATE "C"`로 고정하고 artifact/manifest hash를
갱신했으며, alpine source receipt는 정본 `5d39…`를 유지했다. handoff 오류 문구 assertion도
현재 보안 문구와 정합시켰다.

- role-bootstrap 18개, fresh root/Alembic 3개, glibc alias 2개, handoff executable 27개,
  관련 unit contract 86개 통과
- Ruff와 `git diff --check` 통과
- untracked `uv.lock`은 열람·수정·stage하지 않음

사용자 결정에 따라 `300` 이후 기존 application row의 무결성 검증은 범위에서 제외한다.
필요하면 새 schema에 원천 데이터를 재적재한다. immutable catalog/seed receipt는 데이터
정합성 증명이 아니라 schema·role·ACL·extension·필수 고정 seed 및 operation replay 경계만
확인하는 bootstrap 증명으로 유지한다.

적대 Compose/security 리뷰의 P2를 반영해 통합 fixture의 credential-bearing 환경 파일은
`docker exec` argv가 아닌 stdin으로 container에 설치하고, bootstrap 종료 시 삭제하도록
보강했다.
또한 role-bootstrap target을 `template0`으로 맞추고, large-object residue를 첫 mutation
전에 거부하는 guard와 전후 snapshot 회귀를 추가했다.
## 2026-08-25 — T-VN-H46H fresh-root missing-receipt typed proof (Draft)

fresh root migration이 DB transaction과 operation receipt를 커밋한 뒤 stdout 또는 host artifact만
유실되고 recover가 일시 실패하는 경우, bootstrap 상태만 보고 새 fence로 root를 재실행할 수 있던
경계를 제거했다. production 전용 read-only `probe-missing --operation-id`가 동일 advisory lock
snapshot에서 receipt 부재와 exact pre-root 상태를 확인하고, operation·writer fence·journal·DB
identity·candidate/image·source catalog·seed·destination Alembic 기대값을 canonical wire에 결박한다.
expired fence는 이 read-only 판정에만 허용하며, receipt가 있거나 role/schema/ACL/object/DB 설정이
조금이라도 다르면 fail-close한다. Manager가 이 typed proof를 strict parse한 경우에만 fence 갱신과
root 재실행을 허용하도록 다음 Manager 커밋에서 연결한다.

- fresh-root unit/실제 disposable PostgreSQL 회귀: `23 passed`
- 변경 파일 Ruff, strict mypy, `git diff --check`: 통과
- 범위 밖 untracked `uv.lock`: 열람·수정·stage하지 않음
## 2026-08-25 — T-VN-41F1D-E 최종 DB identity·role residue 결박 (Draft)

전문 DB 적대 리뷰의 잔여 finding을 반영해 Dagster metadata LOGIN role의 권한 잔여 검사를
`rolconnlimit=-1`, password expiry 부재, role-level/database-role setting 0까지 확장했다. compose의
permit producer와 `dagster-storage-migrate.py` consumer가 동일 exact payload를 사용하며 한 필드라도
다르면 writer 실행 전에 중단한다.

C7 journal v8 parser에는 PinVi DB의 system identifier, name/OID, owner와 login role identity를 추가해
Map application·Dagster metadata와 함께 세 DB 모두 고정되도록 했다. Manager canonical parser가
허용하는 동일 transaction/operation UUID를 C7만 별도로 거부하던 과잉 제약은 제거했다.

- Dagster runtime + C7 회귀: `305 passed`
- 변경 파일 Ruff·`git diff --check`: 통과
- 완료된 `T-VN-40` 잔여 task: `docs/tasks.md`에 없음
- 범위 밖 untracked `uv.lock`: 열람·수정·stage하지 않음
## 2026-08-25 — T-VN-41F1D-E v6/v8 live attestation 정렬 (Draft)

두 번째 전문 적대 리뷰에서 Map C7 verifier가 구 manifest v5/journal v7만 허용해 Manager의
canonical v6/v8 generation을 mutation 전에 무조건 거부하는 P1을 확인했다.

- generation에 application `300` paired candidate evidence exact schema 추가
- journal v8의 candidate evidence 중복 결박과 committed generation 전체 동등 확인
- application create/final DB identity 및 canonical digest 검증
- root/finalize operation ID·fence·result와 application final permit digest 검증
- Dagster metadata DB·LOGIN role identity 및 metadata permit digest 검증
- 구 manifest/journal version과 누락·추가 field를 compatibility shim 없이 거부
- integration-map, Admin live runbook, backup policy, H46H 설계 보고서와 tasks 정본을
  fresh-only/v6/v8로 정렬하고 backup/복구점 release gate 삭제

실행형 C7 attestation 양·음수 회귀 `76 passed`와 Ruff를 통과했다. 실제 n150 실행은 고정
release candidate와 Manager 최종 commit pair를 만든 뒤 수행한다.
## 2026-08-25 — T-VN-H46H 퇴역 in-place production capability 제거 (Draft)

두 번째 전문 적대 리뷰에서 fresh-only 결정 뒤에도 API image가 실제
`ktm-application-schema-handoff` executable을 설치하고 builder가 이를 필수 artifact로 봉인하며,
fresh root/finalize까지 그 mutation module을 import하는 P1을 확인했다.

- API Dockerfile과 candidate/fresh-oracle executable manifest에서 handoff writer 제거
- image에 퇴역 handoff 경로가 존재하면 candidate build를 fail-close
- exact `0236` startup은 in-place 명령 없이 destructive fresh rebuild만 안내
- final permit transition allow-list를 `map-fresh-300-finalize` 하나로 축소
- catalog digest/runtime invariant를 root-owned `0444` 비실행 DB contract module로 분리
- fresh root/finalize는 새 module의 read-only 함수만 호출하고 transition source를 import하지 않음
- mutable checkout의 옛 handoff rehearsal/source-oracle/build-baseline을 candidate proof-tool
  authority에서 제거

검증은 final permit/catalog/squash `55 passed`, paired builder `16 passed`, API startup contract
`9 passed`, 실제 PostgreSQL fresh root `2 passed`와 finalize/probe `1 passed`, Ruff·compile·shell
syntax·`git diff --check`를 통과했다. 아직 active 운영 문서와 C7 live verifier의 v5/v7 drift는
별도 P1으로 남아 있어 PR #1064는 Draft를 유지한다.
## 2026-08-25 — T-VN-H46H Dagster 부분 초기화 성공 승격 제거 (Draft)

전문 DB 적대 리뷰에서 Dagster run/event/schedule storage가 순차 초기화되는 도중 죽으면 일부
table만 존재하는데 공유 `public.alembic_version`은 이미 final head일 수 있고, 기존 wrapper가
이를 receipt로 승격하는 P1을 확인했다. 다음 경계를 적용했다.

- receipt 없는 final head도 writer를 재실행하며, 같은 operation intent와 pre-state가 아니면 거부
- session advisory lock을 prepare부터 외부 migrate+reindex와 receipt commit까지 유지
- fresh 세 storage metadata와 head stamp를 한 transaction으로 생성
- `should_autocreate_tables: false`로 장기 runtime의 암묵 수리 차단
- 설치된 Dagster package 기반 exact public table·column nullability·index·required migration
  postcondition과 catalog SHA-256을 migration result v3에 결박
- `verify-identity`/explicit recover도 committed receipt와 현재 exact catalog를 같은 read-only
  snapshot에서 검증

일회용 PostgreSQL에서 receipt 직전 의도적 실패 후 intent 1개·receipt 0개·final head 상태를
만들었다. 같은 operation의 실제 `dagster instance migrate`+`reindex`가 v3 receipt로 수렴했고,
그 뒤 resume은 writer를 호출하지 않았다. 마지막으로 required index 하나를 제거하자 recover가
`dagster_catalog_postcondition_mismatch`로 중단됨을 확인하고 테스트 컨테이너를 제거했다.

- Dagster command 회귀: `9 passed`
- Dagster runtime storage 회귀: `29 passed`
- paired candidate 회귀: `16 passed`
- 변경 파일 Ruff·compile·`git diff --check`: 통과
- 범위 밖 untracked `uv.lock`: 열람·수정·stage하지 않음
## 2026-08-25 — T-VN-H46H finalize missing-receipt typed proof (Draft)

적대 리뷰에서 finalize container가 DB commit 뒤 응답만 유실했는데 `recover`가 일시 실패하면,
Manager가 raw `300` head만 보고 만료 fence를 새 fence로 바꿔 영구적인 receipt/journal 불일치를
만들 수 있는 P1을 확인했다. Map one-shot에 read-only `probe-missing --operation-id`를 추가했다.
probe는 finalize와 같은 advisory lock 뒤에서 기존 finalize receipt가 없음을 확인하고, prior root
receipt의 canonical payload와 operation·writer fence·journal·database identity, 고정 candidate와
PostgreSQL image, source catalog·seed·Alembic facet이 모두 일치할 때만 typed
`receipt-missing-exact-prestate` 결과를 반환한다. 만료 fence는 이 read-only 판정에만 허용한다.

- 실제 PostgreSQL finalize/probe/recovery 통합 회귀: `1 passed`
- probe parser/runtime permit unit 및 변경 파일 Ruff: 통과
- 범위 밖 untracked `uv.lock`: 열람·수정·stage하지 않음

Manager 쪽 strict parser와 recover-failure 결선, 외부 prerequisite 선행 gate의 unit 회귀도 통과했지만
Map의 Dagster 부분복구 P1을 먼저 해결한 최종 SHA로 pinset을 회전하기 위해 아직 별도 커밋하지
않았다. PR #1064와 Manager PR #197은 Draft를 유지한다.
## 2026-08-25 — T-VN-H46H application `300` crash-resume outbox 보강 (Draft)

PR #1065 merge `af719112` 위로 PR #1064의 19개 커밋을 rebase하고, Dagster storage
identity preflight 때문에 Python 3.12에서 먼저 중단되던 오래된 테스트 fixture를 actual
identity 경계에 맞췄다. 이어 적대 리뷰에서 API candidate receipt 발행 뒤 paired receipt 전에
중단되면 같은 pinset을 재개할 수 없는 P1을 확인했다. paired builder는 이제 API-only partial
상태를 strict `O_NOFOLLOW`·owner `0600`·`nlink=1`·stable inode/metadata·canonical JSON
snapshot으로 검증한 뒤 Dagster 단계부터 재개한다. paired receipt 발행도 operator-only `0700`
parent에서 atomic no-replace하고 post-publish bytes를 다시 대조한다. 수정 checkpoint
`3547431a`는 원격에 push했고, 원 리뷰어 재검토는 P0/P1 없이 GO였다.

DB mutation 응답 유실은 stdout만으로 복구하지 않는다. fresh root result v2와 finalize result
v4는 Manager plan의 별도 `operation_id`를 기본키로 삼아 application DB transaction과 같은
transaction에서 `ops.application_schema_operation_receipts` append-only row를 확정한다. 두
operation은 같은 advisory lock namespace를 쓰며, `recover --operation-id`는 candidate/image,
writer fence, journal, DB identity, full catalog·seed·Alembic facet을 read-only로 다시 대조한 뒤
원 canonical result만 돌려준다. finalize는 prior root operation ID도 결박한다.

Dagster storage permit/result는 v2로 올렸다. dedicated metadata DB의 immutable intent와 receipt가
missing/old/final head를 구분하므로 실행 전 crash는 같은 migration을 재개하고, final head commit
뒤 응답 유실은 writer 재호출 없이 receipt를 완성한다. permit은 canonical operation UUID,
`LOGIN NOINHERIT`, exact DB identity와 paired candidate/config digest를 결박하며 foreign lookalike
outbox catalog는 거부한다.

- paired builder 회귀: `16 passed`, 원 적대 재리뷰 GO
- Dagster command package 회귀: `8 passed`
- Dagster/Compose targeted unit: `30 passed`
- 실제 PostgreSQL: root receipt/recover/immutability, finalize rollback·success·recover,
  baseline structural contract 통과
- 관련 Ruff, shell syntax, baseline digest, `git diff --check`: 통과

Docker Manager PR #197은 새 root/finalize·Dagster wire 소비, recover-first 재개, receipt가 없는
exact pre-state에서만 허용하는 fence renewal까지 로컬 결선했다. Manager backend 전체
`694 passed, 3 skipped`와 변경 source strict mypy가 통과했다.

Map checkpoint `6b60fee0`의 원격 CI는 lint·OpenAPI·fixture·frontend가 통과했지만 Python 3개
버전이 모두 `test_settings_default_values` 한 건에서 실패했다. 원인은 fresh root helper가 테스트
프로세스에 내부 `KOR_TRAVEL_MAP_PG_DSN`과 schema-owner flag를 남긴 것이었다. helper는 이제
성공·실패·engine 생성 실패 모두에서 두 임시 환경값을 원상복구한다. 오염 재현 순서 21건과 실제
PostgreSQL root/finalize 3건을 다시 통과했다. 이 수정 원격 push와 새 SHA 기준 Manager pin 회전,
paired image 실제 build, 누적 전문 적대 재리뷰, CI green, n150 배포와 live UI E2E가 남아 있으므로
PR은 Draft로 유지한다.

사용자 지시에 따라 범용 feature-update/cache-target 경계의 PinVi 전용 Python 식별자도 제거했다.
일반 writer guard는 `service_owned`, relay protocol은 `cache_target_refresh_protocol` 용어를 쓰며,
실제 외부 시스템 값과 PinVi 전용 인증·curation 계약은 바꾸지 않았다. codegraph 영향도 명령은
기존 Alembic file index schema 오류로 실패해 `rg` 호출자 전수 대조로 대체했다. API guard 회귀,
변경 source strict mypy와 Ruff는 통과했고 DB 통합 두 건은 로컬 재사용 PostGIS container가
`public` extension residue를 가져 fixture bootstrap 전에 중단돼 CI의 fresh PostGIS gate로 다시 확인한다.
## 2026-08-25 — T-VN-M04 Admin BFF 결정 자격 결선 보완 (Draft)

격리된 PinVi→Map M04 실제 브라우저 승인에서 PinVi의 queue receipt는 정상으로
보존됐지만, Map Admin BFF의 최종 승인 요청은 `403`으로 끝났다. 원인은 BFF가
server-only manual Feature create token을 `POST /v1/admin/features`에만 주입하고,
동일한 `require_admin_manual_feature_create` 경계를 쓰는
`/v1/admin/feature-requests/{request_id}/approve|reject`에는 주입하지 않은 것이었다.

프록시는 이제 canonical UUID 형태의 두 M04 결정 경로에만 같은 token을 붙인다. browser가
보낸 동명 header는 계속 폐기하며, 인접하지만 허용되지 않은 경로로 token이 넓어지지 않도록
회귀 테스트를 추가했다. OpenAPI·DB 계약은 바꾸지 않는다.

- proxy 회귀: `16 passed`
- frontend lint·type-check: 통과
- CI와 같은 공개 build-time URL로 Next production build: 통과

아직 candidate frontend 이미지의 격리 Map BFF live 재검증과 적대 리뷰·원격 CI가 남아 있어
PR은 Draft로 유지한다.
## 2026-08-25 — T-VN-H46H paired candidate와 v6 handoff 연속성

API application-300 candidate receipt를 입력으로 받아 같은 commit·Git tree의 Dagster
webserver/daemon image를 봉인하는 paired builder를 추가했다. Dagster image의 static
application contract, provenance/RootFS/config/runtime manifest, proof tool, SBOM과 실제 image
ID를 API 후보와 함께 재검증한다. webserver와 daemon은 같은 image ID를 쓰며 final permit
consumer로 명시하고, Dagster metadata storage migration은 동일 image의 fixed argv를 쓰되
application permit 범위에서는 제외했다.

handoff rehearsal은 API receipt만 받지 않고 paired receipt도 필수로 받아 builder `--verify`를
다시 실행한다. paired receipt 원문 SHA-256, Dagster image ID, candidate Git tree를 terminal
receipt v6에 기록하고 `build-baseline.sh`가 API candidate provenance와 다시 결박한다. launch
contract의 webserver port 정책·default argv·daemon argv·storage argv도 exact 값으로 검사한다.

적대 리뷰에서 metadata-only 선언만으로는 DSN 오지정을 막지 못하며 alternate
`DAGSTER_HOME`으로 storage target을 바꿀 수 있는 P0를 확인했다. 별도 root-owned metadata DB
identity permit을 도입해 storage migration은 쓰기 전에, webserver/daemon은 기동 전에 canonical
config와 같은 DSN의 system ID/name/OID/owner/login을 대조한다. application DB identity, raw
`300`, application schema를 관측하면 중단한다. production permit은 Manager authority와 exact
Dagster image ID·paired receipt SHA-256·`dagster.yaml` SHA-256을 결박한다. local-dev DB-init도
bootstrap login이 아니라 dedicated metadata DSN으로 최종 login identity를 관측해 permit을 쓴다.
후속 적대 리뷰 지적에 따라 metadata login은 DB owner와 같고 bootstrap과 다른 최소권한
role이어야 한다. superuser/DB 생성/role 생성/replication/RLS 우회 권한과 role membership을
모두 거부하고 `session_user=current_user`를 요구하며, permit과 실제 관측값을 exact 대조한다.
Dagster config는 기존 `storage`뿐 아니라 alternate top-level storage key도 허용하지 않고,
`/opt`부터 config까지 root-owned·비쓰기 가능 경로를 확인한다. Alembic version row가 여러
개여도 raw `300`이 하나라도 있으면 metadata writer 전에 중단한다.
기존 role/DB를 bootstrap 권한으로 자동 정상화하던 경로도 제거했다. 둘 다 새것일 때만
최소권한 role과 owner DB를 만들며, 둘 다 기존이면 root-owned prior permit과 현재 identity가
byte-exact로 같을 때 무변경 종료한다. 예약 application/system identity, role/DB partial state,
permit 누락·drift는 어떤 `CREATE`/`ALTER`/`REVOKE`보다 먼저 거부한다.

첫 실제 paired build는 API image 생성 뒤 sealed temp tree의 0444/0555 mode 때문에 cleanup이
실패해 receipt 생성 전에 중단됐다. 실패 산출물을 성공으로 사용하지 않았고, 두 builder의
cleanup이 mode를 복구하고 원래 실패 status를 보존하도록 수정했다. production Dagster 두
service에는 누락됐던 geo URL, MOIS source path, object/offline prefix를 명시하고 root `.env`나
application privileged credential은 허용하지 않는다. 실제 일회용 Postgres에서 전용 metadata
role 생성·두 번째 실행의 idempotency·비슈퍼유저 `pg_control_system()` 조회·bootstrap login
거부를 확인했다. 이때 공식 Postgres image의 초기화 임시 서버가 조기에 healthy로 보이는
Compose 경합도 재현해, PID 1이 최종 Postgres가 된 뒤에만 healthcheck가 성공하도록 고쳤다.
fresh live acceptance는 run별 고유 application/metadata permit volume을 쓰고 Dagster daemon도
기동한다. storage migration/webserver/daemon의 same-image, 종료·running 상태, absolute argv,
metadata/runtime DSN 일치와 read-only permit mount를 실컨테이너 형상에서 검사한다. 외부
DB/인프라 standalone launcher는 production permit producer가 없어 fail-closed하고 Manager
flow만 허용한다. metadata role이 다른 role을 받는 방향과 다른 member에게 부여되는 방향을
각각 0으로 결박하며, metadata/application DB owner 재사용도 거부한다. local launcher는 다섯
DB password를 32..256 URI-unreserved·상호 distinct로 제한하고 bootstrap/migrator/API/
Dagster runtime/metadata DSN의 scheme/login/password/database를 선언값에 exact 결박한다.
metadata storage one-shot에는 application runtime DSN·final permit env/mount를 전달하지 않는다.
관련 targeted 신규 회귀 `18 passed`와 shell syntax·ruff가 통과했다. 전체 묶음 재실행과 n150
Manager-shaped 배포·live UI E2E는 아직 남아 있다.

후속 P0/P1 적대 검토에서는 virgin application DB가 PostGIS image의 자동 extension 대상과
겹쳐 fresh preflight가 항상 실패하는 deadlock을 확인했다. base container는 maintenance DB
`postgres`만 초기화하고 application DB는 `template0`에서 별도 생성하도록 분리했다. creator도
exact database confirmation과 공통 credential preflight를 어떤 `psql`/`createdb`보다 먼저
수행한다. 다섯 application/metadata DSN은 login/password/database뿐 아니라 canonical
authority와 실제 init host까지 하나로 묶었으며, host topology의 creator/bootstrap/fresh metadata/
schema migration 네 service는 모두 host network와 같은 metadata DSN을 받는다. 실제 disposable
PostGIS에서 DB 생성→role bootstrap→metadata DB/permit이 모두 exit 0이었고, permit directory/file
소유권·mode/link count `0:555`, `0:444:1`을 읽기 전용 컨테이너에서 확인한 뒤 고유 프로젝트와
volume을 제거했다.

controlled handoff는 첫 SQL에서 `session_user`, `current_user`, `rolsuper`를 함께 읽어 exact
non-superuser migrator가 아니면 writer fence/lock 전에 거부한다. 로컬 `admin:stack`의 generic
`alembic upgrade head`와 bare metadata `CREATE DATABASE`는 제거했으며, strict local-dev·loopback의
사전 준비된 application single `300`, dedicated metadata owner/login/effective role·양방향
membership 0·same system ID/distinct owner·migrated storage를 읽기 전용으로 검증하는 smoke만
남겼다. source oracle의 read-only sealed tree cleanup은 permission 복구·failure 누적·원 exit status
보존으로 고쳤고, candidate receipt 대상 `resources/curations`는 root-owned 0555/0444와 appuser
touch/rename negative로 봉인했다. 최종 application-300/Dagster/candidate 계약 단일 묶음은
`288 passed`였다. 두 전문
리뷰는 Map 내부 P0/P1 없음, Docker Manager 동반 계약 구현 전 release NO-GO로 최종 판정했다.
## 2026-08-24 — T-VN-H46H `300` runtime transition checkpoint

old staged bootstrap/M01/M05 runtime helper를 제거하고 normal Compose를
`baseline-300` fresh bootstrap 하나로 축소했다. API image에는 exact raw
`0236_tvn41s_compaction_drained` source만 받는 controlled handoff executable을 넣었다.
이 executable은 writer-fence receipt와 명시적 confirm을 요구하고, Alembic connection을
caller outer transaction에 고정해 source/version/semantic closure 및 final role·ACL·extension·
catalog fingerprint를 전후 대조한 뒤에만 `300` stamp를 수행한다. generic startup은 source를
자동 stamp하거나 archive를 replay하지 않으며, 알려지지 않은 active-graph revision도 중단한다.

backup restore는 기존 revision으로 돌아가는 경로를 제공하지 않는다. 현재 version `3` recovery
artifact는 fence 획득 전 거부하며, 향후 `300` baseline recovery artifact 형식은 별도 설계가
필요하다. 이는 이전 Alembic revision으로의 복구 계획이 없다는 운영 정책을 runtime에
명시한 것이다.

검증은 runtime/archive/backup targeted unit `199 passed`, executable handoff PostGIS
integration `1 passed`, metadata consistency PostGIS integration `11 passed`였다. 또 격리된
일회성 local PostGIS container에서 실제 role-bootstrap shell을 실행해 fresh DB가 application
role 21개와 `x_extension` extension schema만 만들고 Alembic table을 만들지 않는 것을 확인한
뒤 container를 제거했다. 이 local evidence는 n150 transition 또는 live UI E2E 증거가 아니며,
Map PR은 두 전문 적대 재검토, Docker Manager typed transition/journal, fixed candidate n150
deploy와 로그인·browser live E2E 전까지 Draft로 유지한다.
## 2026-08-24 — T-VN-H46H active integration을 `300` fresh/handoff gate로 전환

과거 `0200`~`0236` migration을 실행하던 shared integration bootstrap을 final `300`
fresh bootstrap으로 교체했다. retired cohort는 active graph·runtime·test module import
경로 어디에서도 실행하지 않으며, M01~M05 fixture 이름은 final role graph가 이미 존재하는
호환 fixture로만 남긴다. 과거 0235 preview 재정의 검증도 제거하고, final catalog의
manual-provider reader owner와 schema ACL을 직접 검증한다.

새 Alembic gate는 fresh `300` upgrade 뒤 metadata drift와 ORM CHECK 정의를 PostgreSQL이
재파싱한 catalog 정의로 함께 대조한다. logical raw `0236` fixture에 대해서는 authorized
exact handoff만 raw version을 `300`으로 전진시키고, generic upgrade/stamp, 다른 source,
downgrade, commit-time failure가 모두 source row를 보존하는지 실제 PostGIS에서 검증했다.
`test_alembic_squash_boundary.py`·`test_migration_forward_only.py` 26건과 metadata/handoff
integration 11건이 통과했다. runtime image·entrypoint·Compose 및 Docker Manager의 비파기
transition은 아직 남아 있으므로 PR은 계속 Draft다.
## 2026-08-24 — T-VN-H46H `300` fresh bootstrap·exact handoff 첫 구현 checkpoint

clean isolated `0236` reference에서 `schema.sql`과 9-table `seed.sql` sidecar를
생성했다. digest는 각각 `01b5c870…53d2c`, `1872473b…bd80f`이며, source의 `0236`
compaction semantic closure 세 query는 모두 0이었다. active `alembic/versions/`에는
single root `300`만 두고 `0200`~`0236` source는 byte manifest가 있는 retired cohort로
분리했다.

새 `baseline-300` bootstrap은 version table이나 application object가 있으면 role 변경 전에
거부하고, final 21-role/PG16 membership/DB·schema owner/extension 및 x_extension direct
ACL을 한 번에 확정한다. 실제 fresh target에 restricted migrator → schema owner로 `300`을
적용했으며, reference와 core catalog 9,901행 SHA
`45e391eb0c6f4e136995fdd1d95b72cde09a0da3d743235fb3af880280100ec7`가 일치했다.

`alembic/env.py`는 generic upgrade/stamp/downgrade를 막고, private Config authorization,
explicit tag, online `purge`, exact raw `0236` row, unique active `300` head가 모두 맞을 때만
retired revision을 script graph에 재해석하지 않는 one-shot stamp callback을 설치한다. local
clone에서 normal upgrade는 무변경 거부했고, sanctioned handoff는 catalog/data를 바꾸지 않고
raw version row만 `300`으로 전진시켰다. 아직 regression test·runtime/Compose·Docker Manager
transition·n150 candidate/live UI E2E가 남았으므로 task와 PR은 Draft를 유지한다.
## 2026-08-24 — T-VN-H46H `0236 → 300` baseline 전환 draft 착수

Map [PR #1063](https://github.com/digitie/kor-travel-map/pull/1063)은 fixture writer의
DB/login/head preflight, 최소 procedure-owner role 전환, exact future role graph를 포함해
squash `01d65b2ad4ee265a3ef6b01448f6abf573a906a8`로 병합했다. Python 3.11/3.12/3.13,
fixture replay, PostGIS integration, lint, OpenAPI drift, frontend type-check/build가 모두
green이었고 두 독립 적대 리뷰도 GO였다.

그 병합을 기준으로 `T-VN-H46H`를 새 열린 task로 추가했다. `0236` 이후의 현재
application schema는 `300` 단일 root baseline으로 새 DB에 재현하고, 운영 DB는
`0236_tvn41s_compaction_drained` exact single-row 상태에서만 controlled
`alembic stamp --purge 300`을 허용한다. active graph 밖 archive, final 21-role
bootstrap, full routine ACL grantee matrix, same-transaction pre/post catalog assertion,
candidate source/image/head attestation을 모두 전환 계약으로 고정한다.

baseline source는 n150, n150 backup clone, live acceptance DB에서 생성하지 않는다.
provider 적재와 fixture가 전혀 없는 isolated fresh `0236` reference DB를 만들었고,
head와 `0236` data semantic closure 세 query가 모두 0임을 확인했다. Docker Manager의
기존 `rebuild-pinned`는 Map application·Dagster·PinVi DB를 재생성하므로 이번 경로에서
금지한다. 별도 비파기 in-place transition과 truthful typed journal이 필요하다.
## 2026-08-24 — PR #1063 writer fixture preflight·procedure role·future role edge 보강

Draft [PR #1063](https://github.com/digitie/kor-travel-map/pull/1063)의 두 전문 적대 리뷰에서
live weather/price fixture의 P1 두 건을 확인했다. root-only writer DSN이 API/browser target과
같은 DB인지 확인하지 않았고, schema owner가 M01 이후 `feature.create_feature_with_initial_state`
procedure의 `EXECUTE` 권한을 상속하지 않아 실제 seed가 실패할 수 있었다.

helper는 DB명·LOGIN role·Alembic revision의 supplied confirmation과 실제 연결을 mutation 전에
exact 대조하며, mismatch면 `SET ROLE` 전에도 중단한다. schema owner 확인 뒤 generic provider
procedure 호출 하나에만 `ktm_manual_feature_procedure_owner`로 `SET LOCAL ROLE`하고 즉시 schema
owner로 돌아온다. application runtime에는 별도 write privilege를 추가하지 않았다.

또한 shared PostgreSQL cluster의 M01~M05 future membership을 base graph에서 허용하는 로직을
role 이름 전체 제외에서 **정확한 granted/member/admin/inherit/set edge** allowlist로 바꿨다.
option drift, 미등록 application edge, known future NOLOGIN role의 unsafe attribute가 모두
fail-closed한다. 동일 계약을 `0200`, `0202`, role bootstrap에 맞췄다.

- fixture·squash-role unit: `68 passed`
- PostGIS Alembic metadata consistency: `15 passed`

아직 commit/push/재리뷰/원격 CI 전이므로 PR은 Draft로 유지한다.
## 2026-08-22 — T-FE-MOCK-FLAKE mocked logs 응답 고정

`admin/ops pages › /v1/ops/logs`에서 self-owned mock backend가 system/API logs 응답을
주지 않아 `aria-busy`가 15초 유지되던 경계를 PR [#1059](https://github.com/digitie/kor-travel-map/pull/1059)로
수정했다. 생성 OpenAPI `SystemLogsResponse`·`ApiCallLogsResponse` 타입 기반 BFF mock을
추가했고 targeted Playwright 1회와 5회 반복을 모두 통과했다(총 6/6).

mocked checkpoint는 해소됐지만 n150 live GET-only logs는 local-only 자격증명과 prod
credential 불일치로 auth setup 401에서 중단되어 `[~]` 상태를 유지한다. 실데이터·운영
권한 없이 live acceptance나 receipt 승격을 실행하지 않는다.

두 전문 적대 리뷰에서 P0~P3 이슈는 0건이었고, lint·OpenAPI drift·Python 3.11/3.12/3.13·
fixture replay·PostGIS·type-check/Next build 전체 CI가 green인 것을 확인한 뒤 squash
`813a8a76ffa84f281ad46c9fb0e9bd2462fe5e21`로 병합했다.
## 2026-08-22 — Map #1057 병합 및 Docker-manager v5 pinset 정합화

Map [PR #1057](https://github.com/digitie/kor-travel-map/pull/1057)을 squash
`02341eaeed2fddfc191a7ef3551bc03385a54433`로 병합했다. 두 전문 적대 리뷰에서 P0~P3는
0건이었고, lint·OpenAPI drift·Python 3.11/3.12/3.13·fixture replay·PostGIS·
type-check/Next build가 모두 green이었다. contract artifact SHA freeze와 PinVi #465
exact pair를 문서·테스트에 고정했다.

Docker-manager [PR #189](https://github.com/digitie/kor-travel-docker-manager/pull/189)는
Map `e420c89e…`·PinVi `27fe2043…`를 v5 source pinset으로 재고정해 squash
`28b121d07d6906f4b41294476d9add9e8023f9f9`, canonical digest `de5206dc…`로 병합됐다.
이로써 release authority 정합성은 확보됐지만, isolated paired live acceptance,
receipt 승격, production consumer enable과 M01~M05 활성화는 `pending`으로 유지한다.

다음은 `T-VN-41F1D-D1`/`D2`의 비파괴 증거와 isolated acceptance 실행 가능성 대조다.
실데이터·n150 권한 없이 receipt 승격이나 `T-VN-FINAL-REBUILD`를 실행하지 않는다.
## 2026-08-22 — PinVi #465 service/admin 계약 재vendor 병합

PinVi [PR #465](https://github.com/digitie/pinvi/pull/465)를 squash
`27fe2043b7b8e747fbb42d91e461ea462f930bb7`로 병합했다. Map #1051 service와 #1054
full/admin artifact를 각각 `99ba6c17…`/`2c02ecfe…`로 byte-exact 재고정했고 user
`489b05d3…` pin은 유지했다. 두 전문 적대 리뷰에서 P0~P2는 0건이었고 contract-pin,
provenance, lint/typecheck/test 전체 CI가 green이었다.

이로써 T-VN-41C의 consumer 계약 pair는 정합하지만, isolated paired live acceptance와
receipt 승격·production consumer enable은 아직 `pending`이다. Docker-manager v5 source
pinset 재핀은 후속 PR #189에서 병합됐다.
## 2026-08-22 — #1055 문서 병합 및 migration baseline 표현 고정

문서 전용 [PR #1055](https://github.com/digitie/kor-travel-map/pull/1055)를 병합했다
(squash `d92bd44da5dc91721abb4e6b0c3d8c0d8e3d1a00`). 두 전문 적대 리뷰에서 P0~P3는
모두 0건이었고, 문서/redaction gate를 통과했다. 이 PR은 code/migration을 바꾸지 않으므로
`0236_tvn41s_compaction_drained`와 #1054 code baseline `fadc029c`를 그대로 유지한다.

`tasks.md`의 기준 문구를 docs-only merge 뒤에도 반복해서 stale되지 않도록
`origin/main` 대신 migration/code baseline으로 바꿨다. PinVi service re-vendor PR #465는
이후 병합됐으며 paired receipt는 아직 `pending`이다.
## 2026-08-22 — #1054 병합 및 backlog 기준 SHA 갱신

`fix/ops-dataset-rollup-contract`의 [PR #1054](https://github.com/digitie/kor-travel-map/pull/1054)를
CI green과 두 전문 적대 리뷰(P0~P3 각 0건) 확인 후 squash merge
`fadc029ce2b0cd730c604697e04d1fccdff02ce9`로 병합했다. `tasks.md`의 migration 기준을
현재 `origin/main=fadc029c`로 맞췄으며 단일 migration head
`0236_tvn41s_compaction_drained`는 유지된다.

full/admin OpenAPI, 생성 admin 타입, frozen baseline과 T-VN-40 pending receipt의
SHA는 현재 Map tree와 일치한다. 그러나 T-VN-40/T-VN-41은 PinVi re-vendor와 paired
acceptance 증적이 필요하므로 `pending` 상태를 유지한다. 다음은 PinVi service artifact
byte 대조 및 필요 시 별도 re-vendor PR이며, M01~M05·FINAL-REBUILD·live 운영 항목은
실제 증적 없이는 완료 처리하지 않는다.
## 2026-08-22 — #1054 OpenAPI baseline·T-VN-40 pending receipt 재고정

T-VN-41S에서 갱신한 `packages/kor-travel-map-api/openapi.json`의 admin SHA를
`contracts/vnext/openapi-diff-v1.json`에 반영하고, 같은 현재 full spec SHA를
`contracts/vnext/consumer-rollout-v1.json`의 T-VN-40 pending receipt에 재고정했다.
user/service SHA와 PinVi service vendor SHA는 바꾸지 않았다. 따라서 T-VN-40의
교차 저장소 paired acceptance는 여전히 `pending`이며, 이 변경은 receipt가 현재
Map tree를 기술하도록 만드는 정합성 수정이다. OpenAPI 생성 변경에 맞춰 admin
`src/api/types.ts`도 재생성했고, `tasks.md`의 migration 기준을 #1053 병합
`d068552a`로 맞췄다.
## 2026-08-22 — #922 후속 PR #1051 병합 및 task 정합성 대조

T-VN-41S/#922 후속 계약·migration gate를 [PR #1051](https://github.com/digitie/kor-travel-map/pull/1051),
merge `db319a4798229098d04e68e3ac64338183ad547f`로 병합했다. 원격 CI 8/8과 두 전문 적대
리뷰의 P0/P1=0을 확인했으며, P2 메모는 raw DELETE/parent CASCADE, reverse multi-material
delete deadlock, planner 관찰 및 migration lock 실측의 후속 운영 보강으로 남겼다.

병합 직후 `tasks.md`·`tasks-done.md`·`resume.md`를 대조했다. #1029의 M01~M05 구현과
PinVi #458을 완료 이력으로 기록하고, route 활성화·restore/purge·paired acceptance만
부분완료로 유지했다. 완료된 T-VN-37D 상세 블록을 진행 백로그에서 제거했으며, T-VN-40의
독립 잔여 task가 없음을 명시했다.
## 2026-08-22 — T-VN-H27/#819 OPNsense HAProxy 설정 완료

운영자 확인으로 OPNsense HAProxy의 Map·Geo·PinVi 등 외부 노출 API backend에
`timeout tunnel 1h`를 적용했다. H27은 저장소 코드/PR 변경이 아닌 edge 설정 task이므로
`tasks-done.md`로 이관하고 GitHub issue #819를 닫았다. OPNsense effective config와 quiet
WebSocket 관찰 로그는 이 저장소 세션에서 직접 읽지 못했으므로 완료 근거는 운영자 확인이다.
## 2026-08-22 — #990 planner false-fail 회귀 단언 추가

`test_t212d_dedup_refresh_and_consistency_checks_are_index_compatible`의 실제 planner gate
수정은 이미 [PR #1036](https://github.com/digitie/kor-travel-map/pull/1036)에서 병합됐다. 해당
수정은 전역 인덱스 이름 OR 비교를 relation별 semantic allowlist로 바꾸고, provider/dataset
선택성이 20%인 작은 `source_entities`의 기본 Seq Scan을 정상 비용 선택으로 분리했다.

이번 closure PR에는 두 회귀 단언을 추가했다. 작은 dimension Seq Scan은 통과하지만 대량
`features` Seq Scan은 계속 거부한다. 따라서 planner cost 경계가 바뀌어도 문서 전용 PR을
막지 않으면서, 실제 대량 scan 회귀는 놓치지 않는다. 순수 helper 테스트는 `2 passed`, 대상
파일 ruff도 통과했다.
## 2026-08-22 — #922 live material item DELETE 우회 차단

DB 적대 리뷰가 runtime 역할의 `DELETE` 권한과 기존 UPDATE/TRUNCATE-only fence 사이의
틈을 찾아냈다. compaction 표시 전 live item을 직접 지우면 `item_count`·`merkle_root`와
실제 item 집합이 달라질 수 있었다. `0236`에 부모 material을 `FOR UPDATE`로 잠그고
`compacted_at IS NOT NULL`일 때만 DELETE를 허용하는 trigger를 추가했다. compactor의
ordered·bounded batch는 계속 허용되며, live DELETE 거부와 표시 후 DELETE 허용을
integration fence 테스트로 고정했다.

- `test_tvn41s_material_fences.py`: 5 passed
- `test_tvn41s_compaction_drained.py`: 10 passed
## 2026-08-22 — T-VN-41S / #922 orphan GC 갈래를 상태 partial index로 종결

두 번째 적대 리뷰가 지적한 마지막 비용 경계를 실제 상태 전이로 닫았다. receipt 삭제 trigger가
마지막 receipt를 확인한 뒤 `orphaned_at`을 한 번만 기록하고, material fence는 그 상태를
되돌리거나 직접 쓰지 못하게 한다. orphan material에는 새 receipt를 붙일 수 없으므로
`_GET_REUSABLE_MATERIAL_SQL`도 부분 배출/재사용 창을 만들지 않는다.

`_SELECT_EXPIRED_SNAPSHOT_GC_SYSTEM_SQL`과 `_HAS_EXPIRED_SNAPSHOT_GC_BACKLOG_SQL`은
`orphaned_at` partial index를 사용해 audit material마다 receipt anti-join을 반복하지 않는다.
material migration 0236, ORM metadata, orphan fence/trigger, EXPLAIN 및 integration gate를
함께 갱신했다. generic snapshot route에도 실제 runtime `410`을 선언하고 item 500,000 /
material 56 MiB 상한을 service/full spec과 admin 타입에 반영했다. 교차 저장소 PinVi
re-vendor와 paired acceptance 전까지 관련 receipt는 `pending`으로 fail-closed한다.

- compaction-drained integration: 10 passed
- cache-target stream integration: 40 passed
- snapshot-material EXPLAIN: 1 passed
- migration metadata: 8 passed; snapshot unit/migration boundary: 44 passed
## 2026-08-21 — T-VN-41S 잔여를 처리하다 절반만 고친 것을 리뷰가 잡았다

41S의 후속 종료선에 남아 있던 것은 셋이었다.

**① `ops` fail-closed ACL의 탈출구.** fence를 열지 않기로 했다. 조정기가 관장하는 것은
`feature`/`provider_sync`/`ops` 셋뿐이므로 운영자의 임시·백업 표는 `public`에 두면 애초에
걸리지 않는다. 정작 없던 것은 탈출구가 아니라 **안내**였다 — 실패 메시지가 관계 이름만
나열해서, 새벽에 그것만 보면 코드를 고쳐 재배포하는 길밖에 없어 보였다. 메시지가 두 갈래
조치를 직접 말하게 하고, 메시지와 관장 schema 집합을 테스트로 묶었다(집합이 넓어지면
"public에 두면 된다"는 안내가 거짓이 되므로 함께 red가 되어야 한다). env allowlist는
채택하지 않았다 — fence를 약하게 만들고, 한 번 열면 닫혔는지 아무도 확인하지 않는다.

**② compacted material의 무한 누적 스캔 — 절반만 고쳤다.** `0236`이 `compaction_drained_at`과
partial index를 더한다. "표시됐고 item이 남은 material"을 item 존재 probe로 재면 compacted material 하나마다
index probe 한 번이고, audit material은 영구 보존이라 그 수가 단조 증가한다. 비용이 가장 큰
때가 하필 한가할 때다 — backlog가 있으면 첫 hit에서 멈추지만 없으면 전부 훑고 false를 낸다.

그런데 적대 리뷰가 **같은 판정의 orphan 갈래는 그대로**라는 것을 잡았다. 그 갈래는
`compacted_at` 필터가 없어 영구 보존되는 audit material까지 전부 anti-join하고, 네 갈래가
`OR`로 묶여 backlog가 없을 때 전부 평가된다. 즉 지목한 비용 구조가 절반 남았다. 문서 세 곳의
"판정 비용이 커지지 않는다"를 실제 성질로 고치고 잔여를 열린 항목으로 남겼다 — **닫으면서
남은 것을 지우면 다음 사람은 같은 벽에 두 배 크기로 부딪힌다.**

리뷰가 하나 더 잡았다. 내가 고친 것은 두 backlog 질의 중 **하나뿐**이었고, 고치지 않은 쪽이
매 batch에서 먼저 돈다. `UNION` 뒤에 `LIMIT 1`이 걸려 갈래마다 전량 평가되므로 짧게 끊기지도
않는다 — 그대로 뒀다면 열과 인덱스만 늘고 비용은 그대로였다. 두 질의가 같은 술어를 쓰는지
테스트로 묶었다(동작 테스트는 둘이 우연히 같은 답을 낼 때 통과하므로 술어를 본다).

**③ service spec의 `410` 선언 → T-VN-41C로 이월.** 선언하면 spec 두 개가 함께 바뀌고 PinVi
re-vendor가 같은 호흡으로 필요하다. 41C가 어차피 re-vendor를 요구하므로 거기서 함께 한다.
**오늘 깨진 것은 없다** — PinVi는 이미 그 410을 런타임에서 처리한다. 다만 조사에서 새 차단
요인이 나왔다: `tvn40-live-acceptance-v1.json`이 T-VN-40 receipt의 커밋 쌍과 `pending` 가드
없이 결박돼 있어, spec을 바꾸면 그 receipt가 거짓이 된다. 실행 절차와 두 선택지를 41C 항목에
적어 뒀다 — 조사를 버리면 다음 사람이 처음부터 다시 판다.

**게이트가 잡은 것 넷.** (1) main이 M lane의 `0233`~`0235`를 가져가 내 migration이 두 번째
head를 만들고 있었다. (2) `0231`의 fence 이름을 `_append_only`로 잘못 적어 migration이
`NoResultFound`로 죽었다(실제 이름은 `_compaction_only`). (3) M05 부트스트랩이 alembic head를
리터럴로 고정해 두어, M05와 무관한 migration이 붙는 순간 통합 테스트 49건이 fixture 단계에서
죽었다 — 그 검사의 실제 전제는 관계 6개 존재이고 바로 위에서 이미 세고 있어 과다 명세를
걷어냈다. (4) 배출 표시를 `now()`로 찍었는데 그것은 **transaction 시작 시각**이라, 같은
transaction에서 `clock_timestamp()`로 찍힌 `compacted_at`보다 이른 시각이 기록돼 방금 세운
CHECK가 스스로를 막았다. CHECK가 없었다면 시간 순서가 뒤집힌 감사 기록이 조용히 쌓였을 것이다.

**fence는 검사 순서가 곧 계약이다.** 불변성 검사를 맨 앞에 두니 "표시가 아예 아닌 UPDATE"와
"표시를 구실로 내용도 바꾸는 UPDATE"가 같은 이유로 거부됐다. `0231` 테스트가 그 구분을 지키고
있었다 — 구분이 사라지면 운영자가 어느 규칙에 걸렸는지 알 수 없다.

그리고 게이트 실행 자체에도 결함이 있었다. n150 워크트리에 이전 실행이 남긴 미커밋 변경 때문에
`checkout`이 조용히 실패해 **옛 커밋을 계속 테스트**하면서 같은 7건이 반복 실패했다. 매 실행마다
`reset --hard`로 초기화하게 고쳤다.
## 2026-08-21 — live E2E의 provider/dataset 계약 drift 수정

머지된 T-FE-MOCK-FLAKE 이후 n150 live suite를 확장 실행하면서, `admin/issues` 테스트가
이미 퇴역한 문자열 `provider`/`dataset_key` 필드를 입력해 `input[type=number]`에 문자열을
넣는 오류와, 파이프라인 시나리오가 제거된 문자열 provider/dataset 입력을 찾는 오류를
재현했다. 정본 frontend/API가 사용하는 `provider_dataset_id`와 canonical catalog 선택으로
두 live 시나리오를 갱신했다. 운영 UI/API 코드는 변경하지 않았다.

frontend e2e type-check와 lint가 통과했고, n150에서 대상 두 spec을 읽기 전용 게이트로
실행해 `7 passed, 1 skipped`를 확인했다. 임시 checkout과 인증 산출물은 실행 후 제거했다.
## 2026-08-21 (codex) — T-VN-40 paired receipt 재봉인

M04 이후 갱신된 Map/PinVi 계약을 다시 대조하고 n150 격리 스택에서 canonical curation
collection import/refresh를 실행했다. 검증에 사용한 source pair는 Map
`81835cf9d31df61169bd522fc16437d51d90fc35`·PinVi
`5f1c0a0a5568c236e32e6f6bd4c14ba23191817b`이며, user/service/full OpenAPI와 PinVi
user/service vendor bytes는 각각 `489b05d3…`·`e1152a05…`·`697a08c4…`로 일치했다.

- Map detail snapshot 첫 페이지 1건과 동일 ETag 조건부 요청 `304`를 확인했다.
- PinVi import는 plan 1건·POI 1건을 만들었고, 같은 idempotency key replay는 terminal
  create receipt를 반환했다. refresh는 `200 not_modified=true`였다.
- 격리 Pinvi DB에는 canonical plan 1건·POI 1건·완료 receipt 2건·legacy source plan 0건이
  남았다. 운영 DB에는 쓰지 않았으며, 이 증거는 API-level isolated acceptance다.

세부 fixture 식별자·응답 상태·격리 DB postcondition·정리 결과는
`contracts/vnext/tvn40-live-acceptance-v1.json`에 secret-free로 봉인했다. 별도로 실행한
T-VN-34C UI runner는 `tvn36-direct-state-cutover`에서 browser fetch `503`으로
`1 passed / 1 failed`에 그쳤다. 이 runner는 TVN40 canonical import/refresh gate가 아니므로
TVN40 receipt의 성공 근거로 세지 않았고, 실패 상태와 run digest만 같은 증거 파일에 남겼다.

이에 `contracts/vnext/consumer-rollout-v1.json`의 T-VN-40 receipt를 API-level paired
acceptance 범위에서 `complete`로 승격하고, exact artifact hash를 갱신했다. T-VN-40C의
PinVi legacy column 물리 삭제 gate는 이 receipt와 분리된 후속 작업으로 유지한다.
## 2026-08-21 — T-FE-MOCK-FLAKE 표 준비 단언 보강

PR #1045에서 `admin-ops.spec.ts`의 `/v1/ops/logs` smoke를 표별 accessible name으로
scope하고, system/API 각 표의 body row가 나타난 뒤 `aria-busy=true`가 해제될 때 header를
단언하도록 고쳤다. retry나 timeout 증가는 하지 않았다. 첫 checkpoint `09d47cf7`를 원격에
올린 뒤 전문 리뷰어 2명의 적대 리뷰를 받았고, skeleton row가 fetch 미완료를 통과할 수 있다는
P2를 `d208b76a`에서 반영했다. 최종 재리뷰는 두 명 모두 P0/P1/P2 0건이었다.

정적 게이트는 npm tree/Next-Sharp/type-check가 통과했고 Vitest는 354/356 통과였다. 나머지
2건은 NTFS에서 Unix mode `0700/0600`을 보존하지 못하는 기존 `auth-session-security`
테스트다. n150 mocked checkpoint A는 281/285 passed였으며 대상 spec은 self-owned mock
backend의 응답 부재를 감지해 `aria-busy=true` timeout으로 실패했다. n150 live GET-only
logs 스펙은 prod auth setup 401로 본 스펙 실행 전에 중단됐다. 이후 n150에서 같은 스펙을
재시도했지만 동일한 401이었다. PR head의 GitHub CI 4개는 모두 green이며, 최신 운영
자격증명 확인과 live 재실행이 남아 있어 PR은 draft로 유지한다.
## 2026-08-21 (codex) — 완료된 T-VN-40·C7 잔재를 task archive로 정리

- `tasks.md`에 중복으로 남은 T-VN-40B/C·인수 ①~⑤와 완료된 C7 증거 task의 상태 서술을
  `tasks-done.md`의 정본 근거로 이관했다. 진행 백로그에는 `T-VN-39`, Lane M/41과
  `T-FE-MOCK-FLAKE`만 남긴다.
- migration 정본도 당시 main `0232`와 draft #1029의 M01~M05 직렬 `0226`~`0235`를 명시해,
  완료된 T-VN-40 revision을 활성 migration 계획처럼 읽지 않게 했다. 이후 #1029/#1051
  병합으로 현재 정본은 `0236_tvn41s_compaction_drained`이며, 현행 표기는
  `tasks.md` 상단 규율과 최신 resume 엔트리가 소유한다.
## 2026-08-21 — build 예산 vs 상한 결정을 닫고, 그 옆의 도달 가능한 장애를 고쳤다

`_SNAPSHOT_ITEM_LIMIT = 1_000_000`과 `_SNAPSHOT_BUILD_TIMEOUT_SECONDS = 300`이 같은 사실을
두 번 말하면서 서로 달랐다. 결정: **예산 유지, 상한 500,000, 유도식 기각.**

렌즈 넷 중 셋이 "상한을 예산에서 유도한다"를 골랐고 나도 그쪽으로 기울었다. 반증이
뒤집었다 — `limit = budget × rate / safety`로 정의하면 `limit / rate × safety ≡ budget`
이라 불변식이 **항등식**이 된다. 예산을 절반으로 내리는 한 줄 변경에서 CI가 green인 채
client가 보는 413 문턱이 반토막 나고, PinVi는 `Retry-After` 없는 terminal 413을 받아
reconciliation이 영구 정지하는데 서버는 build가 아예 안 돌아 지표까지 조용해진다.
**유도식은 drift를 없앤 것이 아니라 drift 경보를 없앤다.** 변이로 확인했다: 예산을 120초로
내리면 지금 설계는 불변식 3건이 동시에 red다.

**전제가 재현되지 않았다.** 앞선 보고서는 1M이 예산을 68~248초 넘는다고 적었으나, 오늘
같은 코드·더 넓은 키로 235.7초다. 처리량이 250k/500k/1M에서 4,225~4,242로 선형이다.
그래도 1M을 두지 않은 것은 예산의 79%를 쓰는 값이 상한일 수 없기 때문이다.

**측정이 왜 낙관적이었나.** 예전 fixture는 13자 ASCII를 삽입 순서대로 심었는데, build의
정렬 키가 인덱스 없는 표현식(`convert_to(normalize(target_key,NFC),'UTF8')`)이라 그것은
heap correlation 1.0인 **최선 조건**이었다 — 잰 처리량이 하한이 아니라 상한이었다.
prod 실측 키 폭(평균 35.1자)에 맞추고 삽입/정렬 순서 상관을 끊었다.

**내가 넣은 회귀 셋을 리뷰가 잡았다.** ① `set_config(..., is_local)`은 transaction 범위인데
되돌리지 않아 이후 모든 lock 대기가 handler 없는 상한을 물려받아 500이 됐다. ② 고친 경로가
하나뿐이라 `cache_target_event_repo`의 `FOR UPDATE OF stream`으로 같은 pool 고갈이 그대로
남았고, 하필 그쪽이 PinVi refresh-request 경로라 더 유력했다. ③ 새 통합 테스트가 수정을
지웠을 때 실패가 아니라 **hang**했다(변이 exit=124). 그리고 게이트가 넷째를 잡았다 —
`finally`의 reset이 abort된 transaction에서 `InFailedSQLTransactionError`가 되어 원래
`stream_busy`를 가렸다.

**내 보고서도 거짓을 적고 있었다.** soak이 측정 동안 예산을 3,600초로 덮고 있는데 보고서는
"배포 예산 그대로"라고 썼다. 우회를 제거했다.

마지막으로 상한에서 배포 예산 그대로 soak을 돌려 확정했다 — build 123.0초(4,065 item/s,
예산의 41%), 상한+1 typed 거부, partial row 0, compaction 500,000행 7.2초. CI 불변식이 쓰는
상수는 이 확정 측정이고, 탐색 단계의 4,225(예산을 덮은 실행)는 쓰지 않는다.

byte 상한 512 MiB도 손봤다. `material_bytes`는 heap이 아니라 leaf 인코딩 합이고, 실측
재료 처리량 439,600 B/s에서 512 MiB는 **1,221초 = 예산의 4.1배**였다. 게다가 상한을
500,000으로 낮춘 뒤로는 계약 최대 폭(512자)에서도 325.7 MiB라 ASCII stream에서 발화조차
하지 않는 죽은 코드였다. `target_key`가 512자까지 허용돼 같은 item 수에서도 재료량이 16배
흔들리므로 item 상한만으로는 폭 축을 못 묶는다. 56 MiB(139초)로 조였다.
## 2026-08-21 — M01~M05 cluster-wide role 순서 의존과 dedup planner gate 보정

C05 frozen-legacy migration 검증은 별도 database에서 실행되지만 PostgreSQL role/membership은
cluster 전체에 남는다. 그 bootstrap이 M01/M04/M05의 post-legacy membership을 의도적으로
해제한 뒤 공유 migrated DB를 쓰는 다음 lane test가 실행되어, CI에서 procedure grant·runtime
role 검증이 연쇄 실패했다. M01/M04/M05 lane별 fixture가 완료된 M05 head에서 role graph만
멱등적으로 복구하게 하고, pristine `0233` choreography bootstrap과 post-head restore 경로를
분리했다. 적대적 role 리뷰의 P1을 반영해 운영 bootstrap과 동일하게 금지된 실행자 간
membership을 `REVOKE`하고, role 속성·membership option·중첩을 정확히 확인하는 단언으로
즉시 중단하게 정규화했다. 정확한 C05 → M01/M04/M05 순서 표적 integration은 `18 passed`다.

같은 CI의 dedup EXPLAIN은 `source_entities` 3,200행 중 provider/dataset 하나가 정확히 20%를
고르는 fixture에서 기본 planner의 정상 Seq Scan을 회귀로 오판했다. 이 20% 선택성은 seed
관례가 아니라 실행 시 단언으로 고정했다. forced-index gate는
provider/dataset index 호환성을 그대로 검증하고, 기본 planner gate는 나머지 고선택성 대량
relation의 index path만 강제하도록 분리했다. 표적 dedup EXPLAIN은 `1 passed`다.

로컬 CI 구성 전체 integration은 `1037 passed, 12 skipped`까지 진행했다. NTFS 임시 디렉터리가
mode `0700`을 보존하지 않아 domain command marker trust test 두 건만 실패했으며, 이는 Linux
CI와 변경 코드의 실패가 아니다.
## 2026-08-21 — main `0232` 재베이스 뒤 M04/M05 migration ID 충돌 해소

`origin/main`이 `0232_tvn37d_notice_empty_range`까지 전진한 상태에서 unmerged M04/M05가 동일한
`0230`~`0232` revision ID를 선언했다. 그 결과 fresh PostGIS CI가 main chain을 우회해 M01/M04/M05
procedure와 role grant가 없는 head를 만들었다. main의 적용 revision은 불변으로 두고 M04/M05를
`0233_m04_feature_request_queue` → `0234_m05_manual_provider_dedup` →
`0235_m05_reconciliation_delivery`로 재번호화했다. two-phase bootstrap, restore boundary, generated
application graph, integration head assertion까지 함께 바꿔 migration graph 하나만 정본으로 남겼다.
## 2026-08-21 — catalog 대리키 lint 범위를 provider catalog로 한정

`OVERRIDING SYSTEM VALUE` 탐지는 provider catalog의 identity 대리키 하드코딩만 막아야 한다.
M05 reconciliation event의 독립 sequence를 procedure 안에서 명시하는 합법 SQL까지 전역적으로
거부해 Python CI가 실패하던 것을, catalog INSERT가 확인된 SQL 상수에만 검사하도록 고쳤다.
## 2026-08-21 — `0229`~`0232` 묶음 prod 배포 완료, admin 500 해소

PR #1042(자연키 C05 catalog)가 CI 8/8로 머지돼 main이 `e47a389f`가 됐고, 그 위에서
`0229`·`0230`·`0231`·`0232`를 한 배포로 올렸다. prod DB head는
`0225_tvn40c_physical_removal` → `0232_tvn37d_notice_empty_range`.

리베이스로 main에서 `0232`(T-VN-37D notice empty range, #1041)가 함께 들어왔는데, 그것은
prod 데이터로 검증된 적이 없었다. notice 표에 `lock_timeout=30s`를 거는 migration이라
그냥 넘기지 않고, `0231`에 서 있던 리허설 DB에서 이어 돌려 확인한 뒤 배포했다.
리베이스가 잡아 준 것이 하나 더 있다 — ADR 번호가 겹쳤다(#1041이 095를 가져갔다).
내 ADR을 096으로 옮겼다.

**배포 실측이 리허설 예측과 한 항목도 어긋나지 않았다.**

| 축 | 결과 |
|---|---|
| `curated_source_rules` | 53행 전부 `candidate` (`curated` 35 → 0) |
| `GET /v1/admin/curated-source-rules` | **500 → 200** (53항목 전부 `candidate`) |
| C05 `provider_dataset_id` | **104~108** — baseline seed의 70~74와 다르다(환경 지역값) |
| `provider_dataset_id 73` | `python-datagokr-api/standard_special_streets` 그대로, 자식 0 |
| identity sequence | 103 → 108 (전진만) |
| ops relation | 71 → 72, fail-closed ACL 조정 exit 0 |
| `features` / `source_records` | 1,008,852 / 1,009,164 무손실 |

배포 뒤 문서를 전역으로 훑어 **낡은 서술 31건**을 고쳤다. 이 세션에서 "prod 적용 완료"라는
거짓 서술을 이미 세 번 발견했기 때문에 손으로만 보지 않았다. 나온 것 중 절반은 내 변경
밖이었다 — `AGENTS.md`가 "다음 ADR 후보 = ADR-079"라고 적고 있었는데 079는 이미 존재하는
번호였고(그대로 뒀다면 다음 ADR이 충돌한다), `notice-feature-etl.md`는 C05D를 "계획/미구현"
으로 두고 코드에 없는 폐기 dataset_key(`krforest_landslide_forecast_notices`)를 6곳에서
쓰고 있었다. `data-model.md`는 material/receipt 분리를 아직 "`0226+`가 소유할 미래"로
적고 있었다.

번호·개수처럼 잘 바뀌는 값을 진입 문서에 박아 두면 반드시 낡는다. `AGENTS.md`와
`README.md`의 ADR 번호 서술은 값을 지우고 `docs/adr/README.md`를 가리키게 바꿨다.
## 2026-08-21 — prod 배포가 `0230`에서 멈췄다: 대리키를 계약으로 착각한 catalog migration

`0229`+`0230`+`0231` 묶음 배포가 `0230_tvn_c05_krforest_datasets`에서 중단됐다.

```
TVN-C05 provider_dataset_id 73 is already assigned to
python-datagokr-api/standard_special_streets;
expected python-krforest-api/krforest_wildfire_risk_forecast
```

`alembic/env.py`는 `run_migrations()` 전체를 한 transaction으로 감싸므로 30회 재시도가
매번 전량 롤백됐고 API는 끝내 뜨지 않았다. 롤백해 prod를 `0225`로 되돌렸다 — head·
`curated` 35행·container health 모두 배포 전 그대로였다.

원인은 catalog identity를 대리키로 적은 것이다. `provider_dataset_id`는
`Identity(always=True)` 대리키이고 정본은 자연키 `uq_provider_datasets_identity
(provider, dataset_key)`다. 번호는 환경마다 다르며 실제로 달랐다 — baseline seed는
`python-datagokr-api/standard_special_streets`를 69번으로 매기는데 prod는 73번을 배정해
뒀다. `0230`이 그 73번을 자기 것으로 적어 뒀으므로 가드가 정확히 발동한 것이고, 잘못된
쪽은 migration이다. 가드가 없었다면 dataset은 건너뛰고 operation만 같은 숫자로 들어가
**남의 dataset에 C05 operation이 달라붙었을** 것이다.

CI가 늘 초록이었던 이유도 같은 자리에 있다. 통합 테스트 DB는 `0200`이 `seed.sql`을
실행하므로 C05가 이미 70~74로 서 있는 DB만 봤다 — 그 DB에서 이 migration은 순수
no-op이라 prod 조건을 한 번도 보지 못했다.

고친 내용(`fix/tvn-c05-natural-key-catalog`):

- dataset은 identity sequence가 번호를 매기게 두고, operation·scope는 자연키 JOIN으로
  그 번호를 되찾는다. 숫자를 다시 적지 않으므로 남의 dataset에 붙는 경로가 사라진다.
- `_SEQUENCE_SQL`을 dataset INSERT **앞**으로 옮겼다. 뒤처진 sequence를 고치는 것이
  존재 이유인데 뒤에 두면 정작 그 상황에서 INSERT가 먼저 죽는다 — nextval이 이미 쓰이는
  번호를 돌려주고 자연키 arbiter는 대리키 충돌을 잡지 못한다. 적대적 리뷰어 두 명이
  독립적으로 같은 지점을 짚었다.
- 사후 단언 블록: dataset/operation/scope 존재, 기존 dataset의 계약 일치, operation
  `is_enabled`. "선언됐다"와 "돌 수 있다"는 다르다.
- gate는 대리키 70~74를 전부 남이 선점한 DB를 만들고, 세 catalog 테이블을 자연키로
  정규화해 통째로 스냅숏해 delta를 단언한다. 73 하나만 보면 "73만 피해 가는" 구현이
  통과한다. `pytest.raises(match=)`도 버렸다 — SQLAlchemy가 실행 SQL 원문을 예외
  문자열에 붙이는데 그 SQL 안에 단언용 메시지가 그대로 있어 무엇으로 죽든 맞는다.
  sqlstate와 SQL에 없는 payload로 결합한다.
- 재발 방지 lint: `alembic/versions/*.py`가 `provider_sync` catalog에 대리키를
  하드코딩하지 못하게 막는다. 이 사건 회귀 테스트는 `0230` 하나에만 붙어 다음
  migration에는 아무것도 강제하지 못했다.

prod 덤프(587M)를 별도 DB로 복원해 실제 migrator 자격으로 리허설했다. features
1,008,852 / source_records 1,009,164까지 prod와 완전 일치하는 사본에서
`0225→0229→0230→0231`이 30초에 통과했고 fail-closed runtime ACL 조정도 exit 0이었다.
C05는 sequence가 매긴 **104~108**을 받았고 73번 선점자는 자식 0으로 무사하다. sequence는
103→108로 전진만 했다. `0229`가 `curated` 35행을 `candidate`로 정규화하므로 미해결이던
admin `/v1/admin/curated-source-rules` 500도 이 배포로 풀릴 전망이다.
## 2026-08-21 — M04 role marker가 있는 shared cluster legacy bootstrap 보정

PostGIS CI의 기존-object bootstrap 검증에서, 다른 database가 만든 M04 Feature request
전용 NOLOGIN role의 membership이 legacy base graph에 섞여 exact-graph assertion이 실패했다.
이 역할들은 M01/M05 전용 role과 마찬가지로 cluster 범위 객체이므로 legacy 비교에서는 제외하고,
각각의 M01 repair/M04 전용 phase에서 별도로 exact ACL·membership을 검증한다. 대상 기존-object
integration과 Docker runtime unit은 `159 passed`로 다시 확인했다.
## 2026-08-21 — M05 이후 기존 PostGIS migration fixture 격리

M01~M05 role choreography가 적용된 뒤에도 기존 통합 테스트가 shared default DB의 head와
partial bootstrap을 섞어 사용해 CI에서 순서 의존적으로 실패했다. Alembic fixture는 UUID 전용
database를 만들고 제거하며, legacy M01 backfill은 정확히 `0226`까지만 검증하도록 경계를
명확히 했다. T-VN34/T-VN34C provider 초기 생성은 executor group을 직접 `SET ROLE`하지 않고,
실제 Dagster runtime login의 상속 권한으로 실행한다. 다른 DB에만 존재하는 M01 role marker는
fresh legacy database의 bootstrap을 막지 않되, 이 database가 `0226` 이후인데 relation marker가
없으면 계속 fail-closed한다.

표적 PostGIS 묶음은 24 passed, executor/feature-update 묶음은 21 passed·6 skipped로 확인했다.
## 2026-08-21 — M05 paired service contract와 fresh bootstrap 정합화

M05 service surface가 바뀐 뒤 Map의 `openapi-diff-v1` baseline과 pending consumer receipt가 이전
service/admin SHA를 가리켜 Python CI가 실패했다. PinVi의 현재 exact vendor bytes와 같은
user/service/admin SHA로 Map contract freeze를 재결박하고 artifact fingerprint gate를 통과시켰다.

격리 fresh start에서는 PostgreSQL healthcheck가 Unix socket을 먼저 통과해 role bootstrap의 첫
TCP probe가 connection refused로 끝나는 경쟁도 재현했다. bootstrap은 권한 변경 전 30초 bounded
probe를 수행하도록 해 Compose start 순서가 network accept보다 빠른 경우에도 fail-closed하면서
재시도한다.
## 2026-08-21 — T-VN-37D 두 번째 리뷰 P2 반영

두 번째 독립 reviewer가 curation candidate의 `to_jsonb(notice)` timestamp가 DB 세션
timezone에 따라 달라져 representation ETag가 흔들릴 수 있음을 P2로 지적했다. notice
candidate SQL은 `valid_start_time`/`valid_end_time`을 KST 고정 문자열로 다시 써서
`feature_projection.py`와 같은 표현을 사용하게 했고, UTC·Asia/Seoul 세션 결과가 같은지
integration 회귀를 추가했다. 두 reviewer의 최종 판정은 P0/P1 없음, GO였다.
## 2026-08-21 — T-VN-37D 전문 리뷰 findings 반영

두 독립 reviewer는 P0 없이 range 표현의 운영 잠금과 경계 회귀 공백, admin curation
candidate의 `to_jsonb(notice)`에 내부 generated column이 누출되는 P1을 찾았다. migration
0232에 transaction-local `lock_timeout=30s`와 writer fence/maintenance 전제를 기록하고,
candidate SQL은 `valid_during`을 response JSON에서 제외하도록 수정했다. NULL·one-sided·
equal range, public/admin active predicate와 notice candidate detail 회귀를 추가했으며,
수정 후 targeted integration 2건을 통과했다.
## 2026-08-21 — T-VN-M05 `0235` forward repair 재심 보정

두 전문 적대 리뷰에서 `0234` preview DB의 v1 admin 실행권이 repair 뒤에도 남는 ACL 우회와,
전용 owner가 이미 소유한 reader를 schema owner가 `CREATE OR REPLACE`할 수 없어 forward
upgrade가 중단되는 문제를 재현했다. runtime reconciler와 bootstrap은 v1을 admin executor에서도
명시 회수하고, `0235`는 reader 재선언에만 owner의 임시 schema `CREATE`를 부여한 뒤 즉시
회수한다. fresh migration과 preview owner 재정의 모두 실제 migrator login으로 검증했다.

subscription 최초 생성은 row가 없을 때 `FOR UPDATE`가 경쟁을 막지 못하므로 transaction advisory
lock으로 직렬화했다. 두 domain command의 동시 provision은 한 쪽만 `provisioned`, 다른 쪽은
500 대신 durable `already_provisioned`가 된다. terminal 409 receipt도 저장한
`application/problem+json` media type을 replay하도록 고정했다. 이 변경은 다시 리베이스·푸시한
뒤 같은 두 리뷰어에게 재심한다. PinVi consumer, isolated live UI E2E, no-owner restore drill 전에는
M05 activation receipt를 계속 만들지 않는다.

HTTP 재심에서 subscription 409의 top-level `request_id`와 replay `X-Request-ID`가 달라지는
경계를 추가로 닫았다. replay handler는 성공 envelope의 `meta.request_id`를 우선하고, RFC 7807
problem의 top-level `request_id`를 fallback으로 사용해 stored body와 header가 같은 최초 요청 ID를
보존한다.

후속 DB 재심은 no-owner restore의 legacy sweep이 reader를 schema owner로 바꾸는 상태와, M05
membership이 legacy exact-graph oracle에 섞이는 두 P0를 확인했다. `0235`는 reader 부재·전용
owner·schema owner 세 상태를 명시 처리하고 임시 `USAGE, CREATE`를 모두 회수한다. legacy
oracle은 M05의 네 membership을 기존 M01 경계처럼 제외한 뒤 M05 repair가 재확정한다. restored
schema-owner reader를 restricted migrator로 실제 재정의하는 integration과 restore choreography의
순서 계약을 추가했다.
## 2026-08-21 — T-VN-M05 forward-only delivery·subscription activation 보정

적대 리뷰에서 이미 배포 가능한 `0234` migration을 고치면 기존 DB가 reader/ACK lock routine을
잃는다는 문제를 확인했다. 해당 revision은 evidence base로 복원하고, 새
`0235_m05_reconciliation_delivery`에 ACK common lease lock, admin case reader, typed delivery audit,
그리고 fixed principal·cursor-zero만 허용하는 AdminBFF subscription provisioning procedure를 두었다.
이 immutable activation receipt가 없으면 모든 M05 case decision은 503으로 멈춘다. 기존 `0234`에
이미 들어간 reader function은 `CREATE OR REPLACE`로 안전하게 재선언하고, legacy lease/ACK/decision
procedure의 runtime EXECUTE는 회수해 v2 경로만 허용했다. restore는 M05 pre role phase 뒤 0235까지
migrate한 뒤에만 ownership/ACL repair를 실행한다. fresh PostGIS migration integration과 API
route/registry/policy test를 다시 고정했다. PinVi paired consumer와 격리 live UI E2E가 끝날 때까지
activation receipt는 운영에서 만들지 않는다.
## 2026-08-21 — T-VN-M05 admin 판정과 service delivery 경쟁 경계

`GET /v1/admin/manual-provider-dedup-cases`, 상세 조회와
`POST /v1/admin/manual-provider-dedup-cases/{case_id}/decisions`를 추가했다. 목록은
`(created_at, case_id)` keyset과 pending/terminal filter만 지원하며, 상세는 immutable
case·resolution·event와 subscription별 delivery 상태를 procedure-only로 읽는다. decision은
`kept`에는 AdminBFF만, `merged`/`manual_retired`에는 body를 해석한 뒤 DB session보다 먼저
destructive kill-switch까지 요구한다. stale evidence의 409은 domain command terminal result로
기록하고 정상 return하므로 resolution 없이도 exact replay가 가능하다.

service ACK은 동일 Idempotency-Key의 claim/replay를 먼저 잠그고, principal lease row도
preflight와 writer가 공통 `FOR UPDATE`로 잠근다. 따라서 새 key 동시 요청이 모두 absent를
읽어 뒤늦게 빈 domain command를 만드는 경쟁을 막는다. lease는 empty=204, 다른 worker=409으로
명시하고, event는 재조립하지 않은 stored canonical envelope와 SHA-256을 그대로 반환한다.
read/ACK digest는 함께만 설정되며 OpenAPI full/service와 command·route policy inventory를
동기화했다. route/registry 40건, domain command 13건, fresh M05 PostGIS migration을 표적으로
검증했다. 다음은 두 전문 적대 리뷰의 재검토와 PinVi paired consumer/UI contract 구현이다.
## 2026-08-21 — T-VN-M05 backup v3 evidence root와 restore lease 재구축

backup manifest를 v3로 올려 case·resolution·reconciliation event·ACK·immutable subscription을 같은 exported
snapshot의 canonical JSONL count/SHA-256 root에 포함했다. restore verifier는 root 재계산 뒤
ACK의 stored event hash와 subscription cursor 이후의 실제 event prefix를 검사한다. event hash는
UTC `occurred_at`까지 포함한 canonical envelope 전체이며 verifier는 관계형 행과 다시 조립해 대조한다.
불연속 ACK이나 hash 불일치는 fail-loud이며, 통과하면 live worker/expiry를 지우고 prefix에서 cursor를
재구축한다.
이미 무효화된 lease에는 epoch를 재증가시키지 않아 verifier 재실행도 안정적이다.

v3 staging restore는 root 검증 전에 base/M01/M05 ownership·ACL repair를 다시 실행하고, 두 runtime
LOGIN의 catalog preflight까지 통과해야 한다. M05 pre/migrate phase는 `0233/role-ready` 재시도와
`0234` 완료 재기동을 구분해 허용하고 partial marker는 계속 중단한다.

운영 verifier의 SQL을 integration에서 그대로 실행해 ACK cursor 보존, worker fence 무효화와
idempotent 재실행을 확인했다. backup runbook unit 13건과 M05 integration, ruff, Bash syntax가
통과했다. 다음 tranche는 Map admin/service HTTP contract와 first consumer durable receipt/rebind다.
## 2026-08-21 — T-VN-M05 strict-prefix service delivery writer

`0234_m05_manual_provider_dedup`에 service 전용 event lease·ack writer를 추가했다.
subscription의 현재 ack cursor 뒤에서 실제 최소 `event_sequence`만 lease하고, worker·epoch·만료
시각을 검증한 뒤 정확히 그 event의 hash와 local receipt hash를 append-only ack로 결박한다.
따라서 sequence의 commit 가시 순서가 달라도 누락 번호를 가정하지 않으며, 경쟁 worker는
`lease_conflict`로 멈춘다. ack 뒤에는 strict-prefix cursor만 전진하고 같은 receipt는 replay로
읽힌다.

trigger function의 PostgreSQL 기본 `PUBLIC EXECUTE`도 migration·bootstrap·startup ACL
reconciler에서 모두 회수했다. M05 integration은 API/Dagster runtime catalog preflight와 함께
candidate·decision·event lease·경쟁 lease·ack·replay를 검증했고, fresh Alembic metadata check,
ruff, shell syntax도 통과했다. 다음 tranche는 Map admin/service HTTP와 backup v3 root, 첫
consumer의 durable receipt/rebind다.
## 2026-08-21 — T-VN-M05 dedicated candidate·admin decision writer

`0234_m05_manual_provider_dedup`에 Dagster-only candidate writer와 admin-only
decision writer를 추가했다. candidate는 immutable manual origin/claim, 정확히 하나인
provider primary source/head/record를 현재 row revision과 함께 freeze하며, 같은
fingerprint만 idempotent로 돌린다. 새 source head/row revision은 종전 미종결 case에
`superseded` resolution을 append하고 새 episode로 분리한다.

admin 판단은 global curation fence와 UUID 정렬 Feature lock 뒤 모든 proof를 다시
대조한다. `kept`는 evidence만 남기고, `merged`는 명시한 provider survivor를 유지한 채
manual만 canonical retire하고 `rebind` event를, `manual_retired`는 `detach` event를
같은 transaction에 남긴다. stale은 evidence·Feature·event를 쓰지 않는 terminal outcome이다.
generic dedup queue/auto-master/source link 이동은 어느 writer도 호출하지 않는다.

M05 SECURITY DEFINER owner의 cross-owner ACL은 bootstrap과 startup reconciler 모두에서
복원하도록 고정했다. 실제 API/Dagster LOGIN integration은 candidate executor 거부,
candidate exact replay, merged state/event, provider source 보존을 검증했다. 다음 tranche는
strict-prefix service lease/ack와 backup v3 evidence root다.
## 2026-08-21 — T-VN-M05 증적 스키마와 ACL 기본 경계 착수

두 전문 적대 리뷰의 P0를 ADR-097과 설계 보고서에 반영했고, 두 reviewer가 모두 GO를
재확인했다. `0234_m05_manual_provider_dedup`는 범용 dedup queue와 분리된 불변
case·resolution·event·ack와 principal subscription, strict-prefix lease를 만든다. case는
manual origin/claim 및 provider source record를 `RESTRICT` FK로 결박하고, evidence와
subscription은 UPDATE/DELETE/TRUNCATE trigger로 막는다.

runtime ACL inventory와 startup catalog preflight도 M05 여섯 relation의 raw SELECT/DML을
금지하도록 먼저 닫았다. fresh DB migration과 Alembic metadata check 1건, ruff·strict mypy가
통과했다. 이어 `0233 → M05 role 전용 → 0234 → 사후 복구` compose choreography와 disposable
DB helper를 만들었다. 사전 phase에는 M05 object grant가 없고, 사후 복구가 trigger function
owner와 schema usage/create를 확정한다. 같은 fresh migration/Alembic check와 shell·compose
회귀도 통과했다. 다음 tranche는 dedicated writer/lease procedure와 backup v3 root다.
## 2026-08-21 — 완료 task를 `tasks-done.md`로 이관

최신 `origin/main`의 머지 상태를 대조해 H50 planner gate(#1036), 산림청 C05A~D
dataset(#1037), C7 browser evidence·scope registry·live serial·mock manifest(#1038)를
완료 원장으로 옮겼다. `tasks.md`의 완료 인덱스·상세 블록을 제거하고, 실제로 남은
`T-VN-40B` 잔여와 `T-FE-MOCK-FLAKE`는 열린 task로 유지했다. `resume.md`의 현재 진척도도
같은 기준으로 갱신했다.
## 2026-08-21 — T-VN-37D notice empty range 구현 착수

제품 결정을 명시했다. notice 유형과 무관하게 미래 발효 공지는 기존처럼 공개하고,
provider 철회로 `valid_end_time < valid_start_time`이 된 notice는
`feature.feature_notices.valid_during` generated `tstzrange`의 `empty`로 표현한다.
공개·admin active 술어는 `@> now()`로 바꾸지 않고 기존 `valid_end_time` 비교를 유지해
사전 경고를 숨기지 않는다. migration `0232_tvn37d_notice_empty_range`, ADR-095,
ORM metadata와 empty/bounded range integration regression을 추가했다.
## 2026-08-21 — T-VN-M05 paired cutover 설계 착수

사용자는 M05의 consumer 처리를 단순 Map-only merge가 아니라 **paired cutover**로 선택했다.
기존 generic dedup을 그대로 쓰면 manual origin이 후보 입력에서 빠지고, 높은 점수의 자동
master·source link 이동까지 열리므로 사용할 수 없다.

ADR-097과 M05 설계 보고서는 manual/provider case, terminal resolution, reconciliation event,
principal별 ack를 append-only evidence로 분리했다. merge는 admin이 명시한 provider survivor만
허용하고 manual만 retire하며, manual-retire는 detach event를 낸다. generic merge·auto action·
source link 재배치는 모두 금지다.

첫 consumer는 event를 local transaction의 immutable receipt와 exact reference impacts로 먼저
처리하고 ack한다. Map은 consumer 이름을 소유하지 않는 generic service contract만 제공한다.
현재 DB/HTTP 전문 적대 리뷰어 두 명에게 stale/supersede, restore/ACL, event/ack, UI/consumer
delivery를 독립 재검토하도록 요청했다.
## 2026-08-20 — map CI catalog 회귀값 갱신

원격 Python 3.11~3.13 CI가 API unit 1,198건을 실행한 뒤 기존
`test_handler_registry_is_key_to_handler_only`의 `33` 고정값에서 실패했다. C05A route 2종과
C05B~D 3종의 정식 handler binding이 추가되어 실제 registry는 38개였으며, 테스트 기대값을
38로 갱신했다. 해당 테스트 5건과 ruff는 로컬에서 통과했고, 새 SHA로 CI를 재실행한다.
## 2026-08-20 — T-VN-C05A~D provider 머지 및 map pin 고정

두 전문 리뷰어의 적대 검토를 반영한 `python-krforest-api` PR #9를 merge commit
`4681bc7892239adc28aeeab19dba707aefb1dbde`로 머지하고, map의 provider dependency와
provider-contract를 같은 SHA로 고정했다. provider 로컬 gate는 ruff·strict mypy·pytest
42건을 통과했고, n150에 배선된 기존 data.go.kr 키를 출력하지 않고 live API를 실행해 9건을
통과시켰다. 산림안전·산사태 endpoint 2건은 현재 키의 권한 범위를 서버가 거부해 xfail로
기록했으며, n150 Playwright에서 provider debug UI의 API key 없는 오류 표면도 확인했다.

운영 map live UI는 n150 Playwright에서 인증 후 `/admin/features`의 heading/table, 검색·kind
필터를 확인했다. 인증 POST 이후 non-GET 요청은 0건으로, 읽기 전용 live UI E2E를 통과했다.
자격증명 값은 출력·커밋하지 않았다.
## 2026-08-20 — T-VN-C05A~D: 산림청 route·weather·risk·notice 순차 연결

`python-krforest-api`의 C05A nested SHP route, C05B 산악기상 typed 관측, C05C 산불위험
V2 예보, C05D 산사태 예보발령 typed 모델을 upstream에서 안정화하고 `kor-travel-map`이
각 public model을 직접 `FeatureBundle`·`WeatherValue`·notice로 변환하도록 연결했다. C05A는
월 1회, C05B~D는 하루 6회(`01/05/09/13/17/21시`, 분산 offset)를 사용한다. provider
dataset 72~74, fixture preview, Dagster record resource/fetcher/asset, operation scope,
fallback schedule까지 추가했다.

원격 Python 3.12 CI와 rebase에서 최신 main의 `0229`가 이미 머지된 사실을 확인했다. 기존
`0229`를 다시 쓰지 않고 C05 catalog를 새 forward-only `0230`으로 `0229` 뒤에 연결했다.
새 migration은 asyncpg가 허용하는 단일 statement 단위로 실행하고 identity key에는
`OVERRIDING SYSTEM VALUE`를 사용하며, graph artifact·경계 회귀값을 재생성했다.
`test_alembic_metadata_consistency.py` 7건과 관련 ruff 검사를 통과했다.

두 전문 리뷰어의 적대 검토에서 발견한 strict mypy 오류, sigungu 공식 코드 우선순위,
이름만 있는 route의 source identity 충돌, HTTP 200 error body의 키 노출을 provider에서
수정했다. map 쪽에서는 source record·raw lineage와 산사태 발령→해제 snapshot을 보존한다.
provider PR 병합과 SHA pin은 완료했고, 다음은 map PR의 CI green 및 인증 가능한 운영 map
읽기 전용 UI E2E 증거를 확인하는 단계다.
## 2026-08-20 — T-VN-C05A: 산림청 등산로·둘레길 route 연결

`python-krforest-api`의 `ForestSpatialFeature`를 직접 소비하는 순수 변환을 추가했다.
이름·유효 geometry·source identity가 있는 선형 데이터만 `FeatureKind.ROUTE`로 승격하고,
원천 geometry WKT와 archive lineage를 `SourceRecord`에 보존한다. C05A 두 asset은
`features_route` 그룹과 월 1회 schedule에 등록했고, API fixture/operation registry와
baseline provider dataset·operation scope를 함께 갱신했다. C05B~D는 provider typed
client가 먼저 병합된 뒤 순차 연결한다.

가장 위가 가장 최근. 새 엔트리는 위에 append.
## 2026-08-20 — snapshot을 material과 receipt로 가르고, 내가 만든 두 개의 공허를 잡혔다

`T-VN-41S`의 후속 종료선 대부분을 닫았다. `ops.poi_cache_target_snapshots` 한 표가 **무엇을
고정했는가**(material)와 **누가 언제 받아갔는가**(receipt)를 겸하고 있었고, 그래서 두 가지가
표현 불가능했다 — material 양방향 공유와 terminal item compaction. 이제 material 표가 membership을
소유하고 receipt는 `material_id`만 가리킨다.

**단방향 공유는 설계가 아니라 표가 하나여서였다.** reconciliation seal은 generic snapshot을
물려받을 수 있었지만 반대는 막혀 있었다(`NOT EXISTS (... requests ...)`). 물려받으면 만료 시각까지
함께 물려받기 때문이다. 각자 receipt를 만들게 되자 재사용 질의 둘이 하나로 합쳐졌고, "잔여 TTL이
75분 넘는 material만 재사용한다"는 문턱도 함께 사라졌다 — 새 receipt는 언제나 full TTL이다.

**빈 DB로는 이 migration을 검증할 수 없다.** backfill/dedupe 문장을 한 줄도 타지 않기 때문이다.
심은 경로에서만 세 개가 드러났다: PostgreSQL에 `min(uuid)` aggregate가 없다, receipt에 append-only
trigger가 걸려 backfill UPDATE가 막힌다, legacy item의 FK가 지우려는 UNIQUE 인덱스에 걸려 있다.
그 사실을 게이트 스크립트 docstring에 적어 다음 사람이 빈 DB 결과를 통과로 읽지 않게 했다.

**내가 만든 공허 두 개를 다른 것이 잡았다.**

하나. `ops` runtime ACL을 fail-closed로 대칭화하면서, 목록이 실제와 맞는지 보는 게이트를
`Base.metadata` 기준으로 썼다. reconcile이 순회하는 것은 metadata가 아니라 DB다. 모델에 없는 ops
표가 17개 있었고 그 게이트는 green인 채 아무 것도 보지 못했다 — n150 격리 DB 리허설에서
`reconcile_runtime_privileges`가 17개를 들고 배포를 막고서야 드러났다. 그중 9개는 내가 "0225가
물리 삭제했다"고 잘못 판단해 선언을 지운 `curation_*`이다. 0225는 그 표들을 지우지 않았다.

둘. `410 SNAPSHOT_MATERIAL_COMPACTED`가 **도달 불가능**했다. compaction 후보는 정의상 미만료
receipt가 없으므로, 만료를 먼저 판정하면 언제나 `snapshot_expired`가 이긴다. end-to-end 통합
테스트를 쓰고 나서야 알았다. 판정 순서를 바꿨다 — 둘 다 참일 때 더 구체적인 쪽을 답한다.

**그리고 기존 테스트가 내 오판을 하나 잡았다.** 초안의 `safe_high_watermark_relay_order`를
"재사용 시점의 더 높은 cursor가 더 정확하다"며 뺐는데, 그러면 material HWM과 전역 HWM 사이에 낀
비-membership event를 consumer가 건너뛴다. membership은 안 바뀌지만 그 event들은 consumer가 아직
처리하지 않은 것이다. `test_generic_snapshot_reuse_ignores_nonmaterial_outbox_tail`이 그 자리를
지키고 있었다. 초안이 옳았고 되돌렸다.

compactor는 별도 job/schedule을 만들지 않고 hourly GC batch의 한 단계로 넣었다. 같은 표를 같은
잠금 아래 bounded로 훑는 일이고, 나누면 lock·drain loop·timeout·no-progress 판정·backlog 관측을
통째로 복제하게 된다. 표시가 곧 reader의 410 전환 시점이고, 먼저 표시한 뒤 나중에 비운다 —
반대로 하면 1,000,000행을 한 transaction에 지우거나 부분적으로 비운 material이 표시되지 않은 채
남는다.

**그리고 실측이 계약 불일치를 하나 내놓았다.** 1M soak 첫 실행이 배포 기본 build 예산
300초에서 잘렸다. 예산을 측정용으로 늘려 재니 조용한 호스트에서 368.4초다(첫 측정은
동시 부하 아래 547.9초였다) — 즉 지금 계약에서 1,000,000 item
snapshot은 **admission은 통과하고 build deadline에서 실패한다**. 예산을 올리면 그 시간만큼
stream share barrier가 유지되고 그 값은 hung writer의 최대 정지 시간이기도 해서, 내가
임의로 고를 일이 아니다. 선택지 셋과 각각의 비용을 적어 결정 항목으로 세웠다.

나머지 수치는 설계 주장을 그대로 확인해 줬다. 상한과 같은 크기에서 Python peak 2.02 MiB,
상한 + 1은 typed `413`에 partial row 0, compaction이 1,000,000행을 39.5초에 비우고 VACUUM이
157.6 MB를 되찾는 동안 material/receipt 증거는 남았다.

EXPLAIN 게이트는 fixture를 다섯 번 고쳐 쓰게 했다. material이 하나면 partial index 둘의 비용이
같고, compaction 후보가 0개면 planner 선택이 무의미하고, material당 item이 1행이면 정렬이
공짜다 — 셋 다 "인덱스를 탄다"는 통과를 만들면서 아무 것도 재지 않는다. 그 과정에서 내가
추가했던 인덱스 하나가 planner에게 선택되는 것을 끝내 보이지 못해 지웠다. 근거를 못 만든
인덱스는 쓰기 비용만 남는다.
## 2026-08-20 — T-VN-H50 planner gate의 마지막 false-fail 경로 제거

H50 적대적 리뷰어 2명이 최신 구현에서 동일한 P1을 독립 재현했다. `source_entities`가
`source_entity_key` 동등 join을 PK(`source_entities_pkey`)로 읽는 것은 유효한 canonical
경로인데 allowlist에서 빠져 있어, source-links-driven plan이 그 경로를 택하면 다시
false-fail할 수 있었다. `source_entities_pkey`를 추가하고, 실제 SQL의 선두 조건과 맞지
않는 `source_records` 복합 unique index는 제거했다.

동시에 relation별로 수집한 모든 index scan이 role allowlist에 포함되는지 검사하도록 gate를
강화했다. forced/default EXPLAIN의 `Settings`·planner mode·전체 plan 진단은 유지하고,
`provider_datasets`의 Seq Scan 예외는 seed cardinality 100 이하로 제한한다. 대상 테스트
6회 연속 및 모듈 전체 8건은 통과했으며, GitHub Actions는 Python 3.11·3.13/fixture replay가
통과하고 3.12 API unit을 실행 중이다.
## 2026-08-20 — 중복 착수, 그리고 cleanup이 남의 요청을 취소할 수 있었다

열린 PR을 훑다가 `#995`(codex, 8/18 draft)가 **내가 오늘 #1032에서 만든 v5/v7 attestation
전환을 이미 구현해 두었다**는 것을 발견했다. role→image field 매핑 일곱 개가 이름까지
같았다. 착수 전에 열린 PR을 확인하지 않은 내 잘못이다. 사용자가 `#1028`(CI 8/8 green인데
내가 머지를 놓친 것)을 짚어 주지 않았다면 더 늦게 알았을 것이다.

파일별로 대조해 보니 **공유 파일은 예외 없이 main이 앞서 있었다** — nav 19개(#995는 18),
ADR-088 triple identity, 3축 상태 라벨, `provider_issues` 축 제거, `fillKmaRequestDialogScope`
helper 추출. #995가 지우려던 `admin-ops.spec.ts` 1,028줄은 main에서 이미 정리돼 **통과
중**이라, 그 삭제를 받았으면 살아 있는 커버리지를 잃었다. 그래서 정본은 #1032로 두고
#995는 supersede했다.

**남은 고유 가치는 접어넣었다.** 그리고 그 과정에서 이 이식의 진짜 값이 드러났다.

main의 C7 cleanup 발견 루프는 dataset에 붙은 active execution을 **무조건**
`state.requestIds`에 넣고, 이후 non-terminal이면 취소했다. C7 dataset에 외부 운영 요청이
활성이면 **그것을 취소했다**는 뜻이다. 이제 request id ↔ idempotency entry ↔ provider
dataset/sync scope/operation 삼중이 정확히 맞는 것만 채택하고, 하나라도 소유를 말할 수
없으면 그 run의 cancel 자체를 포기한다(남은 것은 수동 정리로 넘긴다 — 남의 요청을
취소하는 것보다 낫다). journal은 v3 → **v4**로 올려 `request_ownership`을 싣는다.

#995를 통째로 가져오지 않은 이유가 여기서도 나온다 — 그 helper는 3,844줄 재작성이라
main의 ADR-088 작업을 지운다. 소유권 기능만 발췌해 main 위에 얹었다.

**이식 중 교차 경계 파손을 하나 잡았다.** `run-c7-prod-live-e2e.sh`가 최종 journal을
`version != 3`으로 거부한다. 브라우저 lane만 v4로 올렸으면 러너가 자기 journal을 거부했을
것이다 — 오늘 적대 리뷰가 attestation에서 지적한 "한쪽만 올린 version"과 정확히 같은
모양이다. shell을 v4 + `request_ownership` 요구로 올리고, 이 버전을 고정하는 계약 단언이
아예 없었기에 drift 게이트도 함께 넣었다.

**그리고 오늘 두 번째로 mocked e2e를 운영 admin UI에 겨눴다.** mocked config는 `webServer`가
없어 이미 떠 있는 `127.0.0.1:12705`(= 운영 admin UI)를 그대로 친다. 25분을 태우고 알아챘다.
prod DB를 확인해 90분 내 write 0건으로 무해를 확인했지만(모든 REST가 `page.route`로
가로채진다), 같은 실수를 세 번째로 하지 않도록 실행 스크립트가 전용 포트에 자체 서버를
띄우고 빌드 env를 checkpoint runner와 같은 discard 포트(`127.0.0.1:9`)로 고정하게 했다.

함께 닫은 두 항목:

- **T-C7-LIVE-SERIAL** — live config이 `fullyParallel: true` + worker 4인데 고정
  `external_system:c7-e2e`를 쓰는 spec들이 `provider_sync_state` 한 행과
  `membership_fingerprint`를 공유한다. **파일 병합 대신 cross-worker 잠금**을 택했다.
  `describe.serial`은 한 파일 안에서만 순서를 강제하고, 1,575줄을 상수 충돌과 함께 합치면
  회귀 위험이 크며 scope를 쓰는 spec이 늘 때마다 다시 합쳐야 한다. 원자적 `mkdir` 잠금에
  소유자 pid 생존·나이 상한을 얹어 crash가 이후 실행을 영구 차단하지 않게 했다. 취득
  찰나(mkdir은 됐고 owner.json은 아직인 상태)를 빼앗지 않는 것까지 테스트로 고정했다.
- **T-C7-SCOPE-REGISTRY** — `external_system:*` scope의 선언 주체·근거·조회 표면이
  migration `0224`의 docstring 안에만 있어 저장소 밖에서 발견되지 않았다.
  `integration-map.md` §3.7과 ADR-088 결과로 올렸다.
## 2026-08-20 — T-VN-M04: consumer 한 곳이 아니라 범용 Feature 요청 큐

외부 service가 Feature relation을 직접 쓰지 않고 immutable 요청만 제출하며, Map admin이
별도 command로 승인 또는 거절하는 M04 queue를 추가했다. 이름·경로·역할·origin은 모두
`feature_request`/`manual_request`로 일반화했고, PinVi는 최초 consumer일 뿐 정본 식별자가
아니다.

승인은 M01 identity claim과 canonical Feature·origin·queue terminal 상태를 한
READ COMMITTED transaction으로 묶는다. exact duplicate도 예외로 rollback하지 않고
`exact_conflict` terminal receipt로 commit하므로 재시도가 pending을 되살리지 않는다.
제출과 승인 command의 두 causal edge는 각각 unique FK로 보존한다.

적대 리뷰에서 확인된 복원 경계도 닫았다. `pg_restore --no-owner --no-privileges` 뒤
bootstrap/reconciler가 세 owner에 걸친 identity-key·core-create·claim/origin·queue·command
grant를 다시 만들며, 실제 revoke 뒤 submit+approve smoke로 복구를 검증했다. runtime의
raw queue SELECT/DML은 catalog preflight와 실제 integration에서 함께 거부한다.

M04가 바꾼 admin/service OpenAPI baseline과 active consumer receipt도 함께 재동결했다. 새
Map/PinVi 격리 paired live UI E2E 전에는 receipt를 `pending`으로 유지해 이전 live 증거를
현재 queue 계약의 completion으로 재사용하지 않는다.
## 2026-08-20 — T-VN-M03: 수동 curation Feature 생성 원자 writer

M03는 curation item과 수동 Feature를 하나의 serialized writer로 생성하고 provenance를
`manual_curation`으로 남긴다. M01 writer의 READ COMMITTED 계약을 import batch의
SERIALIZABLE 경로와 섞지 않도록 별도 command/transaction 경계로 만들었다.
## 2026-08-20 — T-VN-41F1D-E: 세대가 자라도 검사는 자라지 않던 계약

live runner 두 개(`run-c7-prod-live-e2e.sh`, `run-admin-feature-live-acceptance.sh`)가
요구하던 v4 `E2E_C7_COMPATIBLE_PAIR_MANIFEST`를 없애고 v5 pinned runtime manifest +
v7 rebuild journal로 옮겼다. 저장소측(unit·script contract)은 완료이고, n150
data-dependent 실행은 F1D-D 순서를 따른다.

**왜 문서를 둘로 나눴나.** manifest만 보면 "어떤 세대가 active인가"는 알아도 "그 세대가
파괴적 rebuild를 끝까지 통과했는가"는 알 수 없다. 그건 journal만 안다. 그래서 journal의
phase가 `committed`이고 candidate가 manifest의 active generation과 **글자 그대로 같아야**
한다 — 부분 비교로는 두 문서가 같은 transaction의 앞뒤라는 것이 증명되지 않는다. cancel
probe `finalized`까지 요구해 F1J fixture 수명주기가 끝난 세대만 통과시킨다.

**가장 중요한 발견은 v4가 다섯만 보고 있었다는 것이다.** compatible pair는 Map API/UI/
Dagster web/daemon과 PinVi API, 다섯 image만 담았다. PinVi web과 PinVi dagster는 세대
밖이라, 그 둘이 어떤 image로 떠 있든 attestation이 통과했다. v5 generation은 일곱을 함께
고정하므로 compose service env를 둘 추가해 일곱 전부를 실측 대조한다.

같은 병이 테스트에도 있었다. image field 목록을 손으로 나열한 자리가 세 군데였고, 그래서
세대가 자라도 검사는 자라지 않았다. 셋 다 모듈 상수에서 파생시켰다 — 다음에 runtime이
늘면 테스트가 저절로 늘어난다.

**v4 아카이브는 건드리지 않았다.** `t-vn-41-candidate-*` 세 artifact는 freeze 상수가
"detached 이력으로 불변"이라고 이미 정해 둔 것이다. 현행 계약이 v5로 갔다고 과거 증거의
모양을 바꿔 쓰면 그것은 이력이 아니라 위조다. 그래서 전방 계약(receipt)은 v5 generation
일곱 role로 옮기되, 아카이브 검증에는 분리된 5-role 상수를 남겼다.

변이 8종을 실측했다 — phase, candidate 동등성, cancel probe, schema head, journal digest,
pinset, image 실측 대조, manifest version 고정. 전부 red. 첫 배터리는 bash heredoc 인용이
깨져 **변이가 적용되지 않은 채 green을 보고**했는데, 그 green을 증거로 삼지 않고 스크립트를
순수 Python으로 다시 써서 치환 여부를 `assert`로 확인한 뒤에만 판정하게 고쳤다.


**적대 리뷰 2명이 둘 다 NO_GO를 냈고, 둘 다 옳았다.**

가장 큰 것은 내가 한쪽만 올린 version이다. host attestation을 3에서 4로 올리면서
`admin_feature_live_state.py`의 bootstrap 검증은 3을 계속 요구하도록 남겨 뒀다. v4 문서를
깔면 bootstrap에서, v3를 유지하면 검증 모듈에서 막혀 **admin lane이 어느 쪽으로도 실행되지
않는** 상태였다. C7 runner는 자체 bootstrap heredoc을 쓰므로 C7만 돌려서는 보이지 않는다.
그리고 그 결함을 **내 테스트가 고정하고 있었다** — `assert 'attestation.get("version") != 3'
in state`가 v4/v5/v7로 이름까지 바꾼 테스트 안에 그대로 남아 CI는 green이었다.

두 번째는 내가 이 세션 내내 남에게 지적해온 그 병을 내가 새로 만든 것이다. image field
목록을 모듈 상수에서 파생시켜 "모듈이 스스로를 만족하는" 항등식을 만들었다. 리뷰어가 직접
`pinvi_web`을 지우고 돌려 보니 전체 스위트가 green이었다. 원래 하드코딩 목록의 존재 이유가
"세대가 **줄면** 잡는다"였는데, 파생은 정확히 그 방향을 잃는다. 기대 목록을 테스트가 다시
적고, 모듈 상수가 그것과 정확히 같은지 양방향으로 본다.

세 번째는 운영 차단이다. evidence manifest의 key 집합을 바꿔 놓고 `version`을 1로 뒀다.
기존 evidence archive가 있는 host에서는 첫 실행이 audit preflight의 `unsafe_entries > 0`로
죽는다 — 그리고 그 host가 바로 이 acceptance를 돌릴 n150이다. version을 2로 올리고, audit은
v1을 legacy로 인정하되 **그 시절 계약으로 그대로 검사**한다. 과거 증거를 지우게 만들지
않으면서 "옛것은 무조건 통과"도 아니게 하는 유일한 지점이다.

리뷰어가 준 것 중 가장 값진 지적은 **무료로 얻을 수 있던 실측 결박**이었다. runner는 이미
Map DB의 실제 Alembic head를 측정해 evidence에만 적고 있었다. image 일곱은 `docker inspect`로
실측 대조하면서 head 셋만 두 root 문서가 서로 같은지만 봤다. 배포 코드와 DB head 불일치는
2026-07-27 사고가 지목한 실패 모드다. 이제 측정값과 generation을 대조한다.

그밖에 `_validate_utc_timestamp`가 UTC를 보지 않던 것(tz-aware면 `+09:00`도 통과), journal
`transaction_id`가 아무것과도 결박되지 않아 장식이던 것, cancel probe만 exact shape 검증에서
빠져 손으로 적은 `{"stage":"finalized"}`가 통과하던 것, `match=`가 없어 세 guard를 지워도
green이던 것, 전방 receipt 블록이 `pending` 동안 한 줄도 실행되지 않던 것을 모두 닫았다.
ADR-094를 추가하고 ADR-076/079를 superseded로 표시했다 — v4 유지를 결정한 ADR을 근거 없이
뒤집으면 다음 사람이 그 ADR을 들고 되돌리러 온다.

변이 배터리는 세 차례 돌렸다(8종 → 4종 → 7종, 전부 red). 그 중 두 번은 "게이트만 넣고
검증은 안 붙인" 상태를 배터리가 잡아냈다 — cancel probe exact shape와 evidence v1 legacy 경로다.

실행 전제 하나를 기록해 둔다 — v5/v7은 `require_rebuildable_mode`가 걸려 rehearsal/
rebuildable에서만 만들어진다. n150은 `rehearsal`/`rebuildable`이라 해당되지만, **아직 두
파일이 없다**. D1의 파괴적 rebuild가 처음 만든다.
**(2026-08-20 정정 — 이 실측은 틀렸다.** `digitie` 홈만 봤고 실제로는 root 홈에
두 문서가 root:root `0600`으로 실재한다. 2026-08-06 리허설 세대라 현 head와 대조에서
red일 뿐 없는 것이 아니다. 소유권 요구는 이미 만족한다.) 또 ktdm의 state root는 Manager owner
소유 `0700`이라 verifier의 root-owned 0600 요구를 그대로는 만족하지 않는다 — v4도 같은
구조였고 운영자가 root 소유 사본을 건네는 것이 기존 절차다. runbook에 명시했다.
## 2026-08-20 — T-VN-34C fresh-live runner를 M01 필수 자격증명과 동기화

최신 main의 PR [#1028](https://github.com/digitie/kor-travel-map/pull/1028), merge
`021b20fc`를 코드·테스트와 대조했다. 같은 날 반영된 M01 foundation이 compose에서 요구하는
manual-create raw token(UI 전용)과 API digest를 격리 runner가 만들지 않으면 Postgres나
애플리케이션 검증에 도달하기 전에 compose가 종료되는 결함이 있었다.

이번 보강은 runner가 raw token에서 digest를 파생하고 manual-create flag를 명시적으로 `false`로
두도록 했으며, `docker-compose.yml`의 `${VAR:?}` 필수 키 집합과 runner `map.env` 키 집합의
차이를 테스트한다. 따라서 M01이 새 필수 환경변수를 추가해도 isolated fresh-live가 조용히
기동 실패하지 않고 preflight에서 원인을 드러낸다.

전수 대조 결과 이것은 M01의 runner preflight만 닫는다. `0225_tvn40c_physical_removal` 뒤의
`0226_m01_manual_feature_create` DB/ACL/backup tranche, route 활성화와 실제 live 인수는
열린 task로 유지한다. 관련 백로그 상태는 [`tasks.md`](../tasks.md)의 T-VN-M01·
T-VN-FINAL-REBUILD 항목에 반영했다.
## 2026-08-20 — T-VN-41C GC 실측: 통과 자체보다 "통과가 무엇을 뜻하는가"

cache-target snapshot GC의 백로그 AC(migration → 수동 GC → schedule ON → 다음 tick,
처리량 > 유입률, remaining backlog 0, referenced 증가율·보존 임계치 alert)를 n150 격리
DB에서 전부 실측했다. 6개 축 모두 PASS.
기록 `docs/reports/t-vn-41c-cache-target-gc-verification-2026-08-20.md`.

숫자는 여유가 크다 — 유입 12,951 items/s에 GC 65,214 items/s, tick은 schedule을 켠 지
21초 만에 run을 만들고 26초에 SUCCESS, backlog 42/2,100 → 0/0. 하지만 이 숫자들은
**대조군이 있어야만 의미가 있다.** 그래서 이번 실측의 설계는 전부 "통과가 공허하지 않은가"를
겨눴다.

- **시딩에 보존 대조군 2종을 못박았다.** 만료+참조됨(B)과 미만료(C)가 없으면 "만료된 것을
  전부 지운다"는 잘못된 구현도 통과한다. 실제로 단언은 "적격이 0이 됐다"가 아니라
  "적격만 사라지고 대조군 24는 그대로"다.
- **tick을 우연과 분리했다.** 코드 기본 cron은 `15 * * * *`라 정시를 우연히 맞은 것과
  구별되지 않는다. `ops.dagster_schedule_overrides`에 `* * * * *`를 넣고 **새 프로세스가
  그 값을 집는지 먼저 단언**한 뒤에 daemon을 띄웠다. override 경로가 죽어 있으면 거기서 멈춘다.
- **alert를 양방향으로 봤다.** 조인 임계치에서 켜지는 것만 보면 상수를 반환하는 alert와
  구별되지 않는다. 같은 데이터에서 기본 임계치일 때 꺼지는 것까지 단언하고, 증가율은 개수
  ceiling을 기본값으로 둔 채 따로 터뜨려 발화 사유를 분리했다.
- **code location은 실물을 import한다.** 정의를 복제하면 `cron_for_schedule`의 import-time
  해석과 `default_status=STOPPED`라는 검증 대상 자체가 사본이 된다.

과정에서 두 가지를 배웠다. 하나, **Dagster storage DB는 애플리케이션 DB와 분리해야 한다** —
storage가 자기 alembic 계보를 같은 `public.alembic_version`에 stamp해서 우리 head를
`Can't locate revision '0225_tvn40c_physical_removal'`로 못 찾고 죽는다. 운영이 이미
`kor_travel_map` / `kor_travel_map_dagster`로 나뉘어 있는 이유가 이것이었다. 둘,
**growth baseline에는 1초 debounce가 있다.** backlog가 0인 상태에서 job을 연속 실행하면
각 run이 0.1초라 직전 관측이 baseline 자격을 잃고 증가율이 "관측 불가"로 빠진다 — 처음에
증가율 alert가 안 켜진 원인이 결함이 아니라 이것이었다.

절차를 일회성으로 흘려보내지 않고 `scripts/verify-tvn41c-cache-target-gc.sh`로 고정했다.
스키마나 GC 예산이 바뀌면 다시 돌려야 하는 게이트를 사람 기억에 두면 안 된다. 게이트는
`DROP DATABASE`로 시작하므로 운영 DB 이름이 들어오면 그 전에 거부한다.
## 2026-08-20 — T-VN-41C relay 종결성: 테스트가 결함을 보호하고 있었다

`#975` 적대 재리뷰 P2의 (a)~(d)를 닫았다(PR #1026, merge `b2e9c43a`). 착수 전 서브시스템
매핑을 돌려 보니 **넷 다 미구현**이었고, (c)는 백로그가 "향후 위험"으로 적어 둔 것과 달리
이미 현재 위험이었다.

구조는 단순하다. `CacheTargetRefreshProtocolViolation` **하나가 네 원인**(epoch 이동 /
generation 전진 / fingerprint 변경 / head 소멸)에서 올라오는데, 호출자가 예외 클래스만 보고
분기했다. 억제 근거를 가진 것은 restore fence 이동뿐인데(그때만 옛 epoch event가 설계상
거부된다 — runbook §5-5) 나머지 셋까지 함께 삼켜졌고, 그러면 PinVi는 요청의 **끝을 보지
못한 채 매달린다**. 이제 typed reason으로 분기하고, 억제·삼킴을 `epoch_moved`에만 한정한다.

**가장 중요한 발견: 저장소가 그 결함을 계약으로 못박아 두고 있었다.**
`test_source_generation_change_fails_before_final_link_and_freshness`가 generation 변경 실패
뒤 relay event를 `queued → running`(failed 없음)으로 단언하고 있었다. 즉 P2-a가 지적한 바로
그 억제 동작이 테스트로 보호받고 있었다. 이 PR이 그 단언을 `queued → running → failed`로
바꾼다 — 회귀가 아니라 계약 전환이고, 이제 그 테스트가 (a)를 실제 DB에서 지키는 가장 강한
증거다.

(b)는 더 단순했다. running member 취소 전이에 relay status event가 **아예 없었다**. queued
경로에만 있어서, Dagster terminate + ledger 전이로 봉인되는 경로에서는 종결 event가 생기지
않았다. 두 경로가 같은 규칙(savepoint + epoch만 삼킴)을 쓰도록 헬퍼로 뽑았다.

**그리고 내가 같은 실수를 새로 저질렀다.** 적대 리뷰 2명이 NO_GO를 냈고 둘 다 실측을 들고
왔다.

- 검증을 통과한 P1은 **내 변경이 만든 결함**이었다. (b)를
  `status="cancelled" if target_status == "cancelled" else "failed"`로 썼는데,
  `_terminal_mapping`이 주는 값은 `{cancelled, done, failed}` 셋이다. 삼항식이 `done`을
  `failed`로 접어, Dagster SUCCESS로 ledger가 `done`을 커밋한 **같은 transaction**에서
  PinVi에 `failed`를 보낼 수 있었다. relay 종결성을 고치겠다는 변경이 종결 상태 자체를
  틀리게 만들 뻔했다.
- 내가 새로 쓴 회귀 테스트가 **공허했다**. 판정을 소스 문자열로 확인해서, 규칙을 완전히
  되돌려도 `5 passed`였다 — 리뷰어가 직접 되돌려 돌려 보고 왔다. 이번 세션 내내 내가 다른
  코드에서 지적해온 "검사한다고 주장하는 것을 실제로는 안 보는" 패턴을, 내가 새 테스트로
  만들어 넣은 것이다.

고친 방식이 교훈이다. 판정을 순수 함수 `suppresses_relay_finalization`으로 뽑아 **값으로**
검사하게 했고(EPOCH_MOVED만 True, 나머지 세 reason과 `.reason`을 가진 남의 예외·무관 예외는
False), 더 나아가 `_terminal_mapping`의 반환 타입을 `CacheTargetRefreshStatus`로 좁혀
**테스트가 단언하던 불변식을 타입으로 올렸다** — 이제 `done`을 `failed`로 접는 코드는 mypy가
먼저 막는다. 규칙을 값으로 검사할 수 있게 만드는 것과, 그 규칙을 타입으로 올리는 것은 같은
방향의 두 단계다.

그 외 반영: `getattr(exc, "reason", None)` duck typing → `isinstance` 좁히기, pickle/copy 왕복
복구(실측 실패였다), (d) truncate 목록에 빠져 있던 `feature.features`·`provider_sync.source_*`
추가(피해자는 `test_mois_loader`의 전역 count 단언).

반증된 지적도 남긴다 — (a)의 전제가 ADR-081과 반대라는 P1은 인용 문서가 Map 자신의 head
projection 규칙이지 Map→PinVi outbox 소비 규칙이 아니어서, 비-epoch 재raise가 `#975 P1`을
되살린다는 P1은 그 경로의 violation이 구조적으로 `EPOCH_MOVED` 하나뿐이라 도달 불가여서
각각 반증됐다.

**게이트**: ruff / mypy `--strict` ×2 / import-linter 4 contracts green, pytest **145 passed**,
CI 8/8. (d)는 전체 실행이 알파벳 순서 덕에 늘 초록이므로 **두 모듈만 골라 실행해** 순서 의존을
실제로 재현하는 방식으로 확인했다.
## 2026-08-20 — T-VN-40C prod 배포: 0225 적용과 M01이 만든 기동 게이트

`0225`를 prod에 올렸다. 최종 상태는 head `0225_tvn40c_physical_removal`, legacy
relation·컬럼·`pg_proc.prosrc` 본문 전부 0, 보존 대상은 mapping 4,424 / item 4,424 /
collection 59 / theme 52 / source 19 / rule 53, curation command procedure는
`ktm_curation_command_owner` 소유 SECDEF 13 + helper 1, rekey FK는 전부 `ON UPDATE` 없음,
API 표면은 제거 라우트 404 · `/v1/curations` 401(public key 필요) · health/version 200,
4개 컨테이너 healthy.

**되돌릴 수 없는 migration이라 실데이터 리허설을 먼저 했다.** prod 백업(615MB, sha256
검증, TOC 1,587항)을 같은 서버의 별도 database로 복원해 `0225`를 실제로 돌렸다. 첫
복원은 `--no-owner`를 써서 procedure 소유자가 전부 `kor_travel_map`이 됐는데, prod는
`ktm_curation_command_owner` 20 / `ktm_feature_schema_owner` 4 / `ktm_curation_audit_writer` 1로
나뉜다. D4가 `SET ROLE ktm_curation_command_owner` 아래에서 procedure를 `CREATE OR REPLACE`
하므로 그 상태로는 D4를 검증할 수 없어 소유권을 보존해 다시 복원했다. 리허설 결과는
rc=0 · **4초** · 사후 zero 3항 · 보존 3항 · D4/D8 통과였고, 이 4초가 prod 다운타임 예측이
됐다. 대상 표가 전부 소형(2.7MB·40KB·5MB·3.4MB)이라 D8의 FK 재검증 스캔도 짧다.

**배포는 두 번 막혔고 둘 다 게이트가 제 몫을 했다.**

첫 번째는 내가 쓴 배포 스크립트의 가드였다. 스냅샷이 `0225`를 담았는지 보려고
`grep 'down_revision = "0224…"'`를 썼는데 실제 줄은
`down_revision: str | Sequence[str] | None = "0224…"`라 어노테이션 때문에 매칭되지 않았다.
`.env`나 컨테이너를 건드리기 전 단계라 부작용은 없었다. 패턴을 고치면서 revision id
검증도 함께 넣었다.

두 번째가 본질적이다. 같은 날 머지된 **T-VN-M01(#1016)이 production에서
`KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256`을 flag가 `false`여도 필수**로
만들었는데, prod `.env`에도 docker-manager compose에도 그 키가 없었다. API가 재시작
루프에 빠졌다. 중요한 건 **DB head가 `0224` 그대로였다는 것** — M01의 launcher preflight가
설계대로 alembic보다 앞서 죽어 부분 상태가 생기지 않았다. 2026-08-03 사고 이후 "schema
변경이 컨테이너 기동의 부수효과로 일어나는 것"을 막으려고 넣은 구조가 정확히 그 자리에서
작동했다.

복구는 전진으로 했다. 이전 API 이미지는 `latest-main` 태그가 덮여 롤백해도 재빌드가
필요했고, 그 시간이면 배선이 끝난다. raw 44자를 만들어 UI(Next server)에만 주고 API에는
sha256 digest만 주도록 `.env`와 compose를 배선했다(API/Dagster entrypoint는 raw 유입을
거부한다). 기존 secret과 digest가 겹치지 않는지도 확인했다. 재기동 뒤 API는 5회 폴링만에
healthy가 됐고 alembic이 `0224 → 0225`를 올렸다.

**이 배포에서 내가 잘못한 것 하나.** compose 배선을 확인하려고
`docker compose config | grep …ADMIN_PROXY_SECRET`을 돌렸는데, `config`는 값을 전개하므로
평문 secret 3개가 로그에 찍혔다. 키 이름만 보려면 원문 파일을 읽었어야 했다. 이후
확인은 값이 전개되지 않는 방식(원문 grep + `${VAR:-}` 우변 마스킹)으로만 했고, 노출된
값의 회전은 운영자 판단으로 넘겼다.

**남은 것**: docker-manager의 compose·`.env` 변경은 호스트에서 직접 했다(그 저장소는
git 관리 대상이 아니다). `.env.bak-m01cred-*`·`docker-compose.yml.bak-m01cred-*` 백업을
남겼다.
## 2026-08-20 — T-VN-40C: legacy curation overlay 물리 제거

40A의 write fence와 40B의 consumer 선전환 뒤 남아 있던 legacy overlay를 DB·코드·계약·
문서에서 한 release로 지웠다. migration `0225`가 `feature.curated_features`와
`curated_feature_detail_snapshots`, 단방향 동기화 trigger, `curation_items`의
`legacy_projection_id` 컬럼·partial unique index, `0074`의 rekey 예외, legacy ACL을
삭제한다. `ops.curation_cutover_identity_mappings`는 PinVi가 예전 참조를 canonical로
옮기는 불변 증거라 남긴다. fresh PostGIS에서 `0200 → 0225`를 실제로 돌려 확인했다.

이 작업에서 반복해서 드러난 것은 **삭제가 lint를 통과한다고 해서 끝난 게 아니라는
점**이었다. 제거 자체는 manifest가 지시한 대로 기계적이지만, 그 뒤에 남는 잔해는
manifest에 없다.

- `main` 대비 차등 dead-symbol 스캔으로 40C가 새로 죽인 심볼 20개를 찾았다. 그중
  `_FEATURE_COLUMNS`는 드롭된 표의 컬럼(`cf.curation_status`, `cf.rank_score` …)을
  그대로 projection하는 SQL 상수였고, 정적 zero gate의 식별자 목록에는 걸리지 않는
  이름이었다. ast `end_lineno` 기반 제거가 주석을 남긴 자리도 넷 있었다.
- 삭제한 테스트 파일 7개를 함수 단위로 훑어 **legacy 식별자를 전혀 참조하지 않는**
  검사 9개를 찾아 새 모듈로 복구했다. `test_tvn40a_legacy_write_fence_acl.py`에는
  fence와 무관한 ACL phantom 검출이 섞여 있었고, `test_curated_routes.py`에는 40C
  이후에도 살아 있는 catalog 명령의 strong ETag·CAS 계약 검사가 있었다. 파일 이름만
  보고 지웠으면 그 커버리지는 조용히 사라졌을 것이다.

정적 zero gate는 처음에 45건이 남았는데, 문서를 고치고 나니 10건이 남았고 그 10건은
전부 "이건 40C에서 지웠다"고 말하는 문장이었다. 이 구분을 스크립트가 아니라 저장소 안
테스트로 옮겼다 — `tests/lint/test_tvn40c_static_zero_gate.py`가 manifest의 식별자
목록을 읽어 살아 있는 참조 0을 요구하고, 제거 고지 문장은 (경로, 식별자, 사유) 10건으로
열거한다. 등록되지 않은 새 언급과 더 이상 등장하지 않는 죽은 예외를 양쪽 다 실패로
잡는다. 스크립트로만 존재하는 gate는 아무도 돌리지 않으면 아무 것도 지키지 않는다.

runtime 검증도 같은 이유로 통합 테스트로 박았다
(`tests/integration/test_tvn40c_post_removal_runtime.py`). 여기서 내 단언이 세 번
틀렸고, 세 번 다 코드가 아니라 검사 쪽 문제였다.

1. 라우트 검사를 `create_app(최소 ApiSettings)`로 만든 앱에서 했더니 admin/service
   라우터가 아예 mount되지 않아 잔존 표면 13개가 전부 "사라진" 것으로 보였다.
2. module-level `app`으로 바꿔도 여전히 red였다. 이 앱은 라우터를 `_IncludedRouter`
   37개로 감싸 top-level route 객체에 `path`가 없다. 즉 **제거 표면 검사 쪽은 아무
   것도 안 보면서 초록이었다** — 이 저장소가 반복해서 겪은 "검사한다고 주장하는 것을
   실제로는 안 보는" 형태 그대로다. `app.openapi()["paths"]`로 바꾸고, 표면 크기와
   대표 경로 존재를 별도 단언으로 함께 막았다.
3. ACL 검사의 declared 집합을 표 2개로 잡아 column-level `_CORE_FEATURE_GRANTS`로
   권한을 받는 protected 표 4개가 미선언으로 잡혔다. dagster 경계도 "canonical 표
   DELETE 금지"로 잘못 짚었다 — 실제 불변식은 curation typed command가 command owner
   소유 SECURITY DEFINER이고 dagster runtime EXECUTE가 false라는 것이고, prod에서
   14개 procedure로 확인했다.

두 gate 모두 변이를 주입해 red를 확인했다. 코드에 live reference 주입, tombstone 예외
삭제, 죽은 예외 추가, 잔존 목록에 없는 경로 넣기, legacy 이름 표 생성, procedure 본문에
식별자 심기 — 여섯 변이가 모두 각각의 검사를 red로 만들고 원복 시 green이었다.

문서는 `docs/curated-features.md`를 catalog + collection/item 정본으로 다시 쓰고, 40C
이전 overlay 설계(컬럼·인덱스·enum·PinVi copy 계약 원문)는
`docs/archive/curated-features-legacy-overlay.md`로 동결했다. data-model·rest-api·
openapi-admin-contract·postgres-schema·backup-restore도 같이 갱신했다. `docs/deploy.md`의
2026-08-18 실행 기록은 당시 사실이라 손대지 않았다.

frontend는 legacy 라우트 2개와 read hook 2개, 상태 어휘 모듈을 지웠다. React Doctor의
`deslop/unused-file`이 `src/lib/curated-labels.ts`가 도달 불가능해진 것을 잡아줬다 —
소비자를 지우면 그 어휘도 죽는다는 걸 게이트가 먼저 말해줬다. live e2e fixture의
`CURATED_IDS`(legacy UUID 40개)는 prod `feature.curation_items` 4,424행에서
`CURATION_ITEM_IDS`로 재표집했다.

**게이트 결과**: ruff / mypy `--strict` ×3(144+67+24 files) / import-linter 4 contracts
green. pytest unit+lint+api **3,436 passed**, integration **999 passed**. 남은 실패
6건은 전부 n150 환경(`KOR_TRAVEL_MAP_PG_DSN` 설정, geo API 키 미설정)이고 `main`에서도
같다. frontend CI-parity 게이트 13단계(npm-tree · eslint 0 warnings · React Doctor ·
vitest · gen:types:check ×2 · type-check ×2 · next build 등) 전부 green. mocked e2e는
자기 소유 컨테이너를 exact HEAD에서 빌드해 돌리는 checkpoint runner로 **276/276
passed**(7.2분, flake 0)다.

mocked checkpoint를 처음 돌렸을 때는 baseURL 기본값이 `127.0.0.1:12705`, 즉 n150에서
**실제로 LISTEN 중인 prod admin UI**를 가리켜 프로덕션 화면을 테스트하고 있었다.
`E2E_BASE_URL`을 빈 포트로 옮겨 self-owned 빌드를 보게 고쳤다. 그 상태의 gate는 여전히
red인데, manifest가 고정한 `discoveredTests: 284`가 실측 276과 다르기 때문이다.
`origin/main`(`82b4d1da`)에서도 276이 나오므로 40C가 만든 drift가 아니다 — 백로그
`T-FE-MOCK-MANIFEST`로 분리했다. 숫자만 맞추면 그 gate가 지키던 expected-failure
인벤토리의 의미를 잃으므로 여기서 손대지 않는다.

**남은 것**: `contracts/vnext/consumer-rollout-v1.json`의 T-VN-40
`pinvi_snapshot_receipt.state`는 `pending`이다. PinVi 재-vendor는 Map pin이 **머지된
commit**이어야 성립한다 — `contract-pin-consistency`가 그 SHA를 체크아웃해 vendored
스냅샷과 비교하기 때문이다. 40C 머지 뒤에 수행한다. 사전 확인은 마쳤다: user spec
delta는 path 4·schema 29 **순수 제거**이고 남은 path의 본문 변경이 없으며, service
spec sha(`8019e36f`)는 PinVi가 이미 vendor한 값과 같다. PinVi의 Map curation client는
`/v1/service/curation-collections/{id}/detail-snapshot`과
`/v1/service/curation-cutover/identity-mappings`만 호출하므로 제거 표면을 소비하지
않는다(추적 코드 기준 0건).
## 2026-08-19 — T-VN-H45: Alembic 1.19 named CHECK 373개 정렬

Alembic 1.18.5 기준으로 잠가 둔 천장을 1.19.1로 올리고 fresh PostGIS
`upgrade head → alembic check`를 재현했다. 1.19 named CHECK by-name plugin이
DB removed 208건 / ORM added 167건을 보고했다. 원인은 semantic 이름, 이미 `ck_*`인
이름에 naming convention이 다시 붙은 경우, `conv()`로 고정된 과거 이름,
PostgreSQL 63-byte 절단 이름이 한 metadata 안에 섞인 것이었다.

실제 fresh DB의 schema/table/식과 1:1로 대응해 CHECK 373개의 catalog 이름을
`conv()`로 고정했다. raw SQL migration이 만들었지만 ORM에 없던 43개는 별도
metadata 목록으로 보완했고, DB에 없는 metadata-only 2개는 제거했다. 단순 이름
일치로 끝내지 않고 ORM 식을 같은 column type의 PostgreSQL 임시 table에 설치한 뒤
양쪽 `pg_get_constraintdef`를 비교했다. 이 gate가
`ck_curation_rule_reconcile_operation_revision_shape`의 실제 drift(`>`가 아니라
`>=`이면서 input hash 변경 필수)를 찾아 후속 migration 정본대로 고쳤다. varchar
cast와 `IN` 집합 순서처럼 의미가 같은 표기만 정규화한다.

CHECK comparator 전역 비활성화와 `include_object` 전체 제외는 사용하지 않았다.
의존성은 column-bound fix가 포함된 `alembic>=1.19.1,<1.20`으로 전환했다. 검증은
H45 metadata 통합 6 passed, ruff clean, mypy strict 145 files, import-linter 4/4,
Linux `/tmp` 기준 전체 pytest **3,369 passed / 12 skipped**. Windows Temp가 POSIX
mode/owner 규칙을 보존하지 않아 처음 전체 suite의 domain marker 계열 25건이 실패한
것은 Linux `/tmp` 재실행 85/85와 전체 suite로 환경 원인임을 확인했다.
PR [#1019](https://github.com/digitie/kor-travel-map/pull/1019)은 CI 8/8 green 뒤
merge `82fbe2f6`로 완료했다.
## 2026-08-19 — T-VN-C03: 보조 dataset 5종을 실제 source 기준으로 재분기

로컬 exact pin `python-krforest-api@f9254e6`의 public client/model/catalog와
`python-khoa-api@20c7207`의 46개 KHOA ODMI catalog를 다시 읽고, 공공데이터포털의
현행 산악기상 `15084696`, 산불위험 `15084817`, 산사태 예보발령 `15074798` 계약을
대조했다. 과거의 단일 `krforest_trails`·광범위한 `krforest_safety_notices` 이름은 실제
source 경계를 감췄고, `khoa_coastal_notices`는 authoritative event source가 없었다.

등산로 `PBD0000041`과 둘레길 `PBD0000031`은 route 2종으로 구현한다. 산악기상과
산불위험은 각각 typed 관측·V2 예보 model을 upstream에서 먼저 안정화한 뒤
`WeatherValue`로 구현한다. 산림 notice는 통계·위험지수·시설 목록을 제외하고 실제
발령/해제인 산사태 예보발령만 채택했다. KHOA 계획은 파생 threshold 공지를 만들지 않고
폐기했다. C03은 완료 이관하고 네 구현 단위를 `T-VN-C05A`~`C05D`로 열었다.
## 2026-08-19 — tasks 전면 감사: 완료·폐기·외부 상태 재라우팅

`docs/tasks.md` 전체의 상위 인덱스·상세 블록·체크박스를 `docs/tasks-rule.md`와
재대조했다. 원격에서 #975·#994·#996·#999 병합/CI green, PinVi #215 closed,
manager #148 open, #177 closed, Map #819·#922·#990 open을 확인했다. 그 결과 #975를
여전히 rebase 중으로 쓴 인덱스, #177이 닫혔는데도 잔여 소유자로 쓴 백업 문구,
완료한 40A/mapping/①/②을 "미구현"으로 남겨둔 T-VN-40 이력을 현행에 맞게
정리했다.

H44는 백업 restore 가능성이 독립 DB에서 반복 실증됐으므로 완료했다.
재적재 replay는 24시간 이상의 전량 transaction 또는 필드 손실 부분 replay 밖에 없어
복구 경로가 아님을 확정했고, 주기 트리거는 H43/#148의 실 production 전환
조건으로 남겼다. H45 후속 ①~④·C03 표 drift·40A·mapping·인수 ①/②·41A/B·
닫힌 PinVi #215도 완료 아카이브로 옮겼다. C02·H18은 사용자 지시대로
실행 성공이 아닌 **미구현 폐기**로 명시했다.

H45 1.19.1은 fresh migration에서 named CHECK removed 208/added 167을 재현했다.
전역 comparator 비활성화는 실제 drift를 숨기므로 제외했다. C03은 로컬
provider exact pin을 1차 근거로 보아 trail·weather/fire·safety notice·KHOA notice를 서로
다른 결정/implementation task로 분해해야 함을 활성 원장에 기록했다.
## 2026-08-19 — T-VN-M01 수동 Feature 생성 foundation 구현 시작

PR #1012 merge `ac77a7d1`을 exact base로 `feat/tvn-m01-manual-feature-create`를 열었다. API
foundation은 기존 `POST /v1/admin/features`를 `admin.feature.create.manual-v1` command로 clean
cutover하고, caller identity/state/origin 입력을 제거했다. 서버가 UUIDv7 후보를 한 번 발급해 current
opaque legacy bridge를 만들며, 전용 wrapper의 exact loser와 winner OUT shape, core identity,
override command receipt를 typed invariant로 검증한다. allow-list된 request/identity constraint만 안전한
422/409로 내리고 unknown DB 진단과 trusted generator/wrapper fault는 중앙 500으로 보낸다.

생성은 기본 비활성 flag, 실제 AdminBFF secret과 별도 SHA-256 create credential의 AND gate, 필수 strict
대한민국 좌표, 201 UUID-only response + strong ETag/Location, READ COMMITTED domain-command 경계로
묶었다. exact claim과 `manual_admin` origin ORM은 모든 필수 열을 명시적 NOT NULL로 선언하고 command
unique/FK 및 origin→claim composite FK를 `ON DELETE RESTRICT`로 고정했다. 두 독립 전문 리뷰는 P0
0건이었고 공통 P1인 DB 오류 오분류/raw driver message 노출과 trusted OUT 4xx 오분류는 전용
mapper/invariant와 rollback 관측 테스트로 닫았다. API 입력 오류는 stable `errors[].field`만 공개하며
raw Pydantic input이나 driver message는 응답에 싣지 않는다.

PinVi direct `new_place` caller는 paired draft PR
[#458](https://github.com/digitie/pinvi/pull/458)에서 먼저 제거했다. queue cutover 전 승인은 outbound,
status/ref/reviewer/audit, 연결 POI를 바꾸지 않고 503으로 fail-close하며 correction/closure는 유지한다.
targeted unit/integration 127건과 Ruff/mypy가 통과했다.

DB migration은 만들지 않았다. active head는 `0224_c7_external_system_scope`이고 T-VN-40C가 `0225`를
예약했으므로, 실제 `0225`가 main에 착지한 뒤에만 M01을 `0226_tvn_m01_manual_feature_create`로 잇는다.
`0226→0224` 임시 head나 byte-frozen `0200` baseline 수정은 금지한다.

foundation 뒤 배포 역조사에서 설계의 두 drift를 추가로 찾았다. 긴 revision literal은 PostgreSQL의
32자 `alembic_version` gate를 넘으므로 30자 ID로 줄였다. 또한 갱신 role membership을 fresh DB의
0200/0202보다 먼저 bootstrap하면 historical exact graph 검사가 실패한다. 따라서 기존 graph로
`0225`까지 upgrade한 뒤 M01 bootstrap을 재실행하고 `0226`을 적용하는 2단계 provisioning이 필수다.
production digest 상시 필수 fail-close는 유지하며, UI raw/API digest를 flag=false 배포보다 먼저 secret
store에서 provision하도록 설계 순서를 교정했다.
## 2026-08-19 — T-VN-M00 수동 Feature 생성 설계·전문 리뷰 완료

T-VN-H34 잔여의 "없는 것은 Feature로 추가" 요구를 M lane으로 분리한 뒤, M01 구현 전에 닫아야 할
설계 2차 초안을 작성했다. 핵심 결정은 네 가지다. 첫째, 현재 admin BFF와 PinVi를 서버가 구분할
수 없으므로 admin BFF 전용 credential로 PinVi 직접 경로를 차단한 뒤 M01 origin은
`manual_admin` 하나만 발급한다. 둘째, HTTP `Idempotency-Key`와 body identity를 canonical ID에
쓰지 않고 서버 UUIDv7을 먼저 발급하며 text PK는 `manual::<uuid>` opaque alias로만 남긴다. 셋째,
exact duplicate claim과 verified origin을 별도 불변 relation으로 두고 DB unique 제약으로 동시
요청의 단일 승자를 정한다. fuzzy/provider 중복은 M05로 남겨 자동 병합하지 않는다. 넷째, 새
constraint를 409/422로 명시 매핑하고 current migration과 `contracts/vnext` 7축 freeze artifact를
같은 PR에서 갱신한다.

API 계약과 DB/동시성 전문 리뷰어 두 명이 네 차례에 걸쳐 각 라운드의 동일 SHA를 검토했다. 1차의
API P0 2·P1 3·P2 1,
DB P1 5·P2 6을 시작으로 201 replay, 전용 transport principal, loser UUID 회수, command causation,
append-only ACL·restore를 보완했다. 후속 재심에서 드러난 legacy `f_*` golden bridge, 실제 override 열
backfill, 전체 procedure owner ACL, 명시적 READ COMMITTED, 무조건 forward-only backout, byte-frozen
`0200` baseline, 전 필수 열 NOT NULL·NULL rejection fixture도 모두 닫았다.

최종 exact checkpoint `2aa17c27d4f09701a9639ea0ea449abbfefc0be2`에서 두 리뷰어가 각각
`API FINAL GO`, `DB FINAL GO`와 P0~P3 0건을 선언했다. Markdown/archive link unit 3개, vNext contract
artifact unit 11개, diff/redaction/비밀 가드를 통과했다. ADR-093은 proposed로 유지하고 M00은
`tasks-done.md`로 이관했다. 다음 작업은 M01 clean cutover 구현이며 이 draft PR에는 섞지 않는다.
## 2026-08-19 — C7 prod live 6-spec GREEN, T-VN-40 receipt 봉인

`f00e7f48`에서 strict runner가 `RESULT: GREEN`으로 끝났다 — rc=0,
`orchestrator_verified=true`, BLOCKED 없음, 6 spec 17 case 전부 passed
(read-auth 7 · kma-active 2 · kma-cap 2 · kma-empty 2 · schedule 2 · poi-causal 2).
실행 뒤 audit rc=0, runtime/journal 잔여 0.

**여기까지 걷어낸 결함 7건.** 전부 "CI는 green인데 prod 실행에서만 죽는" 계급이었다.

1. `provider_issues` 축 (#1010) — ADR-088이 지운 축을 스펙이 요구
2. dialog 자유입력 → canonical select + `external_system:c7-e2e` 선언 (#1011)
3. `matched_scope` 자연키 단언 (#1013) — 생산자가 strip하는 필드를 단언
4. 삭제된 `/v1/ops/datasets/detail` 경로 대기 (#1013)
5. refetch 취소 경합 + 부족한 테스트 예산 (#1015)
6. 이월 cursor 가드가 runner 자기 순서를 막음 (#1018) — 내가 만든 결함
7. raw enum 단언 (#1020) — 화면은 `design.md` §Copy대로 한글 라벨을 렌더

**드러난 구조적 문제 셋.**
- `assertOnlyKmaProviderObjects`가 `"provider" in record` 가드 때문에 **공허**해져
  "KMA 외 provider 배제" 보장이 조용히 사라져 있었다.
- `test_c7_prod_live_runner_contract`가 계약이 아니라 **소비자 쪽 문자열을 고정**해,
  드리프트를 잡는 대신 stale 단언을 얼려두고 있었다.
- 진단 attach가 redacted reporter에서 버려져 증적이 도달하지 못했다.

셋 다 정본을 한쪽에 두는 방식으로 고쳤다 — canonical triple, 생산자 상수
(`_NATURAL_IDENTITY_RESPONSE_KEYS`), fail-closed 화이트리스트, 공유 라벨 표.

receipt는 `contracts/vnext/consumer-rollout-v1.json`의 T-VN-40을 `complete`로
봉인했다(9키). pair는 Map `f00e7f48` · PinVi `5cad141a`이고 vendored user/service
바이트가 Map 트리와 정확히 일치함을 확인했다.
## 2026-08-19 — C7 read-auth의 지점 없는 timeout: refetch 취소와 부족한 예산

`dbba2ab6` strict runner에서 `ops-c7-read-auth` 첫 테스트가 지점 정보 없는 30s
"Test timeout"으로 죽었다(직전 두 실행은 7/7). trace를 뜯어야 원인이 보였다 —
미완료 액션은 `waitForResponse` 하나뿐, 그 앞 refresh click은 정상 종료했고,
`/v1/ops/pipeline/overview` 두 건 중 **두 번째가 `status=-1` `time_ms=-1`**(취소)였다.
prod 실측 응답 시간은 overview 0.75~1.02s, datasets 1.39s로 느리지 않다.

이 화면들은 ops-live 알림으로 query를 invalidate하고, TanStack v5는 invalidate 시
in-flight fetch를 취소한다(`cancelRefetch` 기본 true). 특정 응답 하나를 기다리는 코드는
그때 상한까지 매달린다. 같은 상호작용의 선례가 `ops-c7-kma-empty-write` 코드 주석에
있었다(앱 fix + 테스트 단순화로 해소).

**적대 리뷰가 첫 수정의 두 결함을 잡았다.**
- `response.ok()`를 predicate에 넣어 4xx/5xx가 "응답 없음"으로 뭉개졌다. read/auth
  게이트에서 간헐 5xx와 인증 회귀(401/403)를 **틀린 사유**로 보고하게 된다.
- 응답 창(8s)을 click의 actionability 상한(60s) **앞에** 열어, 진행 중
  (`aria-disabled`) 버튼을 기다리는 동안 창이 만료되는 구조였다. 재시도가 자기 응답을
  구조적으로 못 보는 모양이다.

고친 형태: attempt마다 `toBeEnabled`를 선행하고, 응답 창을 click 상한 이상(60s)으로
맞추고, "응답을 못 봤다"(재시도)와 "응답이 틀렸다"(즉시 실패)를 가른다. 시도 기록은
evidence로 attach해 조용한 열화가 통과했는지 나중에 읽을 수 있게 했다.

예산은 자기 worst case 위로 올리고(#2 180s, #6 240s) 구간을 `test.step`으로 감쌌다 —
예산을 올려도 실패가 스스로 이름을 대야 이번 같은 trace 발굴을 반복하지 않는다.
리뷰가 지적한 대로, "#6이 28.4s로 완주했다"는 1표본은 제품 지연을 배제하지 못한다.
#6의 예산 근거는 그 표본이 아니라 **구조**다 — 명시 `READY` 대기만 6개(합 120s)에
ops-live poll 간격 2s가 더해진다.
## 2026-08-19 — C7 KMA live 3종이 ADR-088 계약과 어긋나 있었다 (0224 선언)

`025be0e6`로 prod를 올려 strict runner를 돌리자 `ops-c7-read-auth`는 7/7 통과(#1010이 실제로
고쳤다)했고 실패가 `ops-c7-kma-active-write`로 옮겨갔다. §4 recovery로 BLOCKED을 풀고(audit rc=0;
잔여는 이 실행이 만든 cache target 2건, 둘 다 API의 종료 상태인 soft delete) 비-redact 하네스로
재현해 `getByLabel('provider')` 60s timeout을 확인했다.

**첫 판단이 틀렸다.** dialog에 `external_system:<name>` 자유입력을 되살리려 했는데, 적대 리뷰 2인이
같은 P0을 잡았고 코드로 확인됐다 — ADR-088(#966)은 제출 가능한 `sync_scope`의 정본을
`provider_dataset_operation_scopes` 선언으로 못 박았다(`_ACTIVE_DATASET_MEMBERSHIPS_SQL`의 exact
join + `feature_update_request_datasets`/`import_job_datasets`/`provider_sync_state`/
`offline_uploads` 4종 exact FK). 즉 UI는 제출 가능 집합을 이미 정확히 표현하고 있었고, 내 수정은
실패 지점을 label timeout에서 서버 422로 옮기며 제출 직전 fail-closed 가드까지 약화시켰을 것이다.
제품 변경 4파일을 전량 revert했다.

**실제 결함은 스펙이 stale한 것**이다. C7이 마지막으로 full green이던 `d5693269`(07-26)는
ADR-088(08-11) 이전이라 스펙이 여전히 run마다 `external_system:e2e-<run-id>`를 만들고 있었다.
`target_grids`로 바꾸지 않은 이유는 그 scope가 "모든 활성 cache target + extra points"라 (a) PinVi가
target을 등록하는 순간 인수가 운영 대상에 provider I/O를 내고 `membership_fingerprint`가
비결정적이 되며 (b) `provider_sync_state`의 정본 cursor 행을 스케줄 job과 공유하기 때문이다.
오늘 prod가 비어 있어(활성 target 0, extra points 미설정) 우연히 동등해 보일 뿐이다.

migration `0224_c7_external_system_scope`가 `external_system:c7-e2e`를 선언하고 스펙 3종이 그 값을
쓴다. run 격리는 기존 `target_key`. **T-VN-40C 예약 revision은 `0224`→`0225`로 재배정했다** — 40C의
선행조건 P1이 T-VN-40 receipt complete이라 이 인수 뒤에야 참이 되고, 40C가 먼저 착지할 수 없다.

실행으로만 잡힌 결함 2건: revision id 40자가 `alembic_version.version_num varchar(32)`를 넘어
unit/ruff/mypy는 전부 green인 채 DB에 닿아서야 죽었다(29자로 줄이고 상한을 unit 게이트로 잠갔다).
선언이 사라지면 prod에서만 422로 죽는 문제는 seed 기반 integration 테스트로 잠갔고 migration을
no-op으로 만들면 RED가 되는 것까지 확인했다.
## 2026-08-19 — C7 live `ops-c7-read-auth` 첫 테스트 실패 2건 수정

러너 증거가 redact라 세부가 없어서, attestation의 executor 이미지로 컨테이너를 직접 띄워
(orchestrator 우회 — BLOCKED.json 없음) 그 spec만 `--max-failures=1`로 돌려 비-redact 오류를 얻었다.
두 실패는 서로 다른 커밋에서 왔고 한쪽만 프론트 회귀였다.

- **실패 1 (계약 노후 — 프론트 무관)**: live 스펙이 grid row마다 `provider_issues.open_count`를
  요구했는데 prod 응답 67/67 행에 그 키가 없다. `9bbb74d9`(ADR-088 · #966)가 provider dataset
  identity를 triple로 바꾸면서 grid/detail 계약에서 provider 단위 이슈 축을 없앴고, 같은 커밋이
  스펙의 딥링크 축·aria-label은 갱신했지만 이 검사는 놓쳤다(해당 줄은 스펙 최초 생성 `f4c8c16b`
  이후 불변). 정본이 API·OpenAPI·UI(`dataset-issues.ts`)이므로 **스펙을** 현행 계약으로 맞췄다 —
  이슈 축은 `dataset_issues` 하나, 그리드 요약은 `provider_dataset_id` 단위 max dedupe 합.
  UI 모듈을 import하지 않고 미러를 유지한 것은 그래야 UI가 UI를 검증하지 않기 때문이다.
- **실패 2 (Hallmark 리디자인 #1003 회귀 — 프론트 수정)**: prod overview는
  `operations_by_status={"done":6,"failed":2}`처럼 0건 버킷을 아예 빼고 온다(GROUP BY 집계 ·
  OpenAPI에도 required 키 없음). 리디자인 전에는 `?? 0`으로 0을 그렸는데 KpiCard → StatStrip
  전환(`da2c740a`)에서 그 coalesce가 빠져 `—`가 떴다(단위 `건`도 함께 사라진다). 응답이 온 뒤의
  키 부재는 **알려진 0**이므로 `operationCount()` 한 곳으로 읽기를 좁혀 0을 돌려주고, `—`는 응답
  자체가 없는 로딩·에러에만 남긴다(M36 유지). 생성 타입의 index signature가 키 부재를 표현하지
  못해(`noUncheckedIndexedAccess` 미사용) tsc가 못 잡은 자리다.
- mock e2e(275)가 못 잡은 이유는 fixture 두 곳이 늘 다섯 축을 채워 빈 버킷 경로를 밟지 않아서다.
  `makeOverview()`에 sparse 옵션을 열고 회귀 테스트를 추가했다(276).

**재검증(prod 읽기 전용)**: 같은 harness로 스펙 수정본을 prod에 다시 돌렸다. datasets 구간
(row 계약 · 요약 "이슈" 카운트 · 딥링크 · 상세 · invalid scope)이 전부 통과하고 실패가
`expectKpiValue("실행 대기")` 하나로 좁혀졌다 — prod가 아직 수정 전 번들을 서빙하므로 예상된
결과다. 그 두 단언만 진단 사본에서 비활성화하니 test #1이 **완전히 통과**(2 passed)했다. 즉
프론트 수정의 live 확인은 Map prod 재배포 이후에 완결된다. 두 실행 모두 실행 전후 잔여 0
(POI target 0, update_request 5상태 전부 0)이고 write 단계에는 도달하지 않았다. strict runner는
실행하지 않았고 audit rc=0 · BLOCKED 없음.

n150 게이트: tsc(src/e2e/tooling) · eslint · vitest 324 · react-doctor · 금지패턴 0 · next build,
mocked e2e **276 passed**.
## 2026-08-19 — T-VN-H46G buildx source revision 결박

`scripts/docker-buildx.sh`가 exact HEAD를 frontend에만 넘기고 API·Dagster web·daemon에는
넘기지 않아 세 image의 OCI revision이 Dockerfile 기본값 `development`로 남을 수 있었다.
공통 `build_one` 경계가 모든 runtime image에 동일한 40자 SHA를 build arg와
`org.opencontainers.image.revision` label로 강제하도록 바꿨다. caller별 arg 추가 방식은 다음
image가 생길 때 다시 빠질 수 있어 쓰지 않았다.

전문 적대 리뷰어 2명의 1차 검토에서 `git status` 오류 fail-open과 clean 검사 뒤 context 변경,
별도 build가 한 OCI 경로를 덮어쓰는 문제가 확인됐다. 상태 확인 실패와 dirty worktree는 builder
mutation 전에 exit 2로 중단하고, exact commit의 tracked bytes를 한 번 `git archive`로 만든
불변 context에서 세 build를 실행하도록 보완했다. OCI 출력도 API·admin·Dagster별 파일로
분리했다. 재심에서 확인된 구 `KOR_TRAVEL_MAP_BUILDX_OCI_PATH` silent-ignore는 명시적 migration
오류로 바꾸고, archive 생성 중 TERM에는 writer를 종료·회수한 뒤 단일 임시 tar를 unlink하도록
보완했다. 배포 뒤 실제 container 검증은 ADR-076의 C6c/C7가 네 immutable image ID와 revision
label을 `map_source_revision`에 대조하는 기존 정본을 유지하며 새 manifest나 digest 정본은
만들지 않는다. 두 전문 리뷰어는 exact head `84349b4c`에 P0~P3 잔여 없이 GO했고, 실제
32.7 MB tar-stdin BuildKit 3종·Dagster 두 tag 동일 OCI digest·signal cleanup을 독립 재현했다.
로컬 root unit 2,300개와 전체 Ruff·strict mypy 3패키지·import-linter도 통과했다. H46G는
`tasks-done.md`로 이관하고 draft PR #1007의 완료 이관 commit CI 뒤 병합한다.
## 2026-08-19 — T-VN-40 인수 ② 완료: PinVi cutover 봉인 + canonical collection 59개 import

- **pair commit 확정**: Map `817cfeae`(prod 배포·검증 완료 — 4 서비스 healthy, head `0223`, export root 불변),
  PinVi `5cad141a`(#455까지 머지). PinVi vendor: user `6a2ee0f9…` · service `8019e36f…`,
  provenance `map_release_revision=f637f3ad`.
- **S3** — 복구점(`pinvi_0049_pre-tvn40-2_20260819T000601Z.dump` + sha256, TOC 52) → exact-commit 스냅샷
  (`--no-checkout` + `fetch --depth 1` + `rev-parse` 검증) → 롤백 태그 → **3 이미지 빌드**(revision 계약) →
  bootstrap one-shot으로 alembic `20260804_0049 → 20260814_0059`(10개) → `--no-deps --force-recreate`.
  bootstrap 출력이 `action=unchanged`라 **prod admin 비밀번호 회전·세션 폐기가 없었다**(credential을 `.env`의
  C6C 값 그대로 쓴 결과). raw token 2개가 각 64자로 주입됐고(이전엔 빈 값) curation-cutover 라우트가 떴다.
- **S4 봉인(불가역)** — `201` · `receipt_id=46627435-f9a2-44cc-ab3e-329d4255695c` · `status=completed` ·
  `replayed=false` · `mapping_root=69eb85ecb178569bc87665ee1100b0a34ade4274512e5492e358c50a19140710` ·
  `mapping_root_version=ktm-curation-cutover-mapping-v1` · `mapping_count=4424` ·
  `map_release_revision=f637f3ad…`. DB `ktm_curation_cutover_mapping_receipt_items` **4,424행**.
  봉인된 `map_release_revision`은 **서빙 커밋이 아니라 vendored service 계약의 release identity**다
  (`config.py`가 cache-target expected source revision과 대조하는 값 — 계약 렌즈 검증 결론).
- **S5** — `ready=true`, `issues=[]`, `legacy_plan_count=0`. backfill은 prod no-op이라 호출하지 않았다.
- **S6** — canonical collection **59/59** import 성공(전부 `201`, `copied_poi_count`가 각 collection의 item 수와
  정확히 일치). PinVi `curated_trip_plans` 59건 · `curated_plan_pois` **4,424행** = Map canonical item 수와 일치.
- 실행 절차와 그 근거는 `docs/runbooks/tvn40-pinvi-cutover.md`(적대 검증 2명이 초안에서 P1 14건을 잡은 수정본).
  실제 실행에서 그 수정들이 전부 값을 했다 — 특히 credential file 없이는 alembic이 한 줄도 돌지 않았을 것이고,
  `/api/v1` prefix로는 404였을 것이며, `--no-deps` 없이는 prod Map API까지 재생성됐을 것이다.
## 2026-08-19 — T-VN-H46F admin UI geo credential fail-close

Next.js `/api/geo` BFF가 공개 build alias나 browser `key` query를 credential source로
받지 않도록 server-only `KOR_TRAVEL_GEO_API_KEY` 단일 provenance로 좁혔다. 키는 URL이
아닌 `X-KTG-API-Key` header로만 보내며, geo의 401과 400 `E0100 field=key`는
`503 GEO_API_KEY_REJECTED`로 정규화해 입력 오류처럼 보이는 실패를 막는다. missing/invalid
설정, public/VWorld fallback 차단, query override 차단, header 전송, 두 rejection 형태와
비자격증명 400 passthrough를 frontend 단위 테스트로 고정했다.

route만 고치면 credential은 더 이상 읽지 않아도 이미지에는 계속 남는다. 그래서 root
Compose의 API/Dagster source fallback을 canonical server key 하나로 좁히고, frontend
build args·Dockerfile `ARG/ENV`·source digest input·buildx·live/mocked E2E·`load-env.sh`의
양방향 public alias를 함께 제거했다. UI key는 Compose/Manager service 경계에서만
`KOR_TRAVEL_GEO_API_KEY`로 별칭 결선되며 browser bundle에는 들어가지 않는다.

Manager PR #183이 충돌한 #173의 의도를 최신 C6c protected-value 계약과 compose에
재배치해 merge SHA `4f5cbb44`로 흡수했고 #173은 superseded로 닫았다. Map 변경은 admin
redesign PR #1003 merge SHA 위로 재배치했다.

전문 적대 리뷰어 2명이 Map BFF·browser/build/runtime 노출과 Manager C6c 결선을 독립
재검토해 모두 GO를 냈다. frontend unit 336개, Map 집중 37개, BFF route 14개와 원격 CI
8개를 모두 통과한 뒤 PR #1004를 merge `817cfeae`로 병합했고, 완료 항목은
`tasks-done.md`로 이관했다. H46 계열의 열린 후속은 `T-VN-H46G` buildx OCI commit
provenance label뿐이다.
## 2026-08-18 — 인수 ②의 범위가 조사로 바뀌었다: Map은 mutation 없음, 관문은 PinVi 재배포

- ② 문구("admin API preview→commit으로 import")를 그대로 실행하면 **틀린 일을 한다.** prod legacy
  4,424는 전부 `curated`(bucket B)이고 canonical item도 import row 0 / operator 0이라 설계 §6.3의
  official·manual membership 분기에 해당하는 행이 하나도 없다. 여기에 CSV import를 돌리면
  `current_import_row_id`·operator 필드가 붙어 **0223이 immutable로 동결한 `legacy_projection` 전제가
  사후에 깨진다.** → Map 쪽 ②는 데이터 mutation 없음으로 정정.
- **PinVi 실태**: 소비자 코드(`kor_travel_map_curation.py`의 cutover mapping client, receipt/backfill
  service, admin route 3개, alembic 0051~0059)는 `main` `dc8a683f`(#444, 오늘)에 이미 있다. 그런데
  **prod 런타임에는 없다** — `pinvi-api-latest`가 image revision `3b87c19c`(#434, 12커밋 뒤)이고 컨테이너
  안에 client 모듈이 없으며 OpenAPI에 curation route가 0개, DB head는 `20260804_0049`(0050~0059 미적용).
  raw token pair는 오늘 manager `.env`에 넣었고 Map digest와 일치하지만, **토큰만으로는 아무 일도
  일어나지 않는다**(재빌드 + bootstrap one-shot alembic + 재생성이 선행).
- **cutover backfill은 prod no-op**: PinVi `curated_trip_plans`/`curated_plan_pois`가 0행이라 전환할
  legacy plan이 없다. ②를 실제로 이행하는 동작은 **mapping receipt 봉인** 하나이고, 그것은 append-only +
  unique + advisory lock이라 되돌릴 수 없다(백업이 유일한 복구 수단).
- 부수 확인: `ktdctl pinvi-pair`의 하위는 `rebuild-pinned` 하나뿐이고 **3 DB 파기형**이다 — ②~③에서
  쓰지 않는다. 런북 §2.1 step 8이 부르는 `pinvi-pair capture --verified-compatible --build`는
  docker-manager `main`에도 **존재하지 않는다**(런북 수정 또는 명령 신설 결정 필요).
- ④ 선행: PinVi가 vendor한 Map user spec은 `73a9a246`(08-05) 시절 바이트다. Map user spec은
  `4672aa96`~`main` 전 구간 불변이라 재-vendor는 순수 refresh이며, 이 불일치를 잡는 것은 Map의
  `test_vnext_contract_artifacts`뿐이다(PinVi CI는 못 잡는다).
## 2026-08-18 — T-VN-41S snapshot streaming 1차와 migration 보류

- list 기반 capture를 PostgreSQL server cursor 두 번 순회로 바꿨다. 첫 scan은 incremental Merkle
  level stack으로 root/count/canonical bytes를 계산하고 admission을 header INSERT 전에 닫는다. 두 번째
  scan은 1,000행씩 INSERT하고 첫 page만 메모리에 두며, 끝에서 첫 scan checksum을 다시 검증한다.
- item 1,000,000/512 MiB의 독립 typed 413, 유효 generic→reconciliation 동일 snapshot material 공유,
  table/index bytes·dead tuple·vacuum lag Dagster metadata/threshold와 future compacted page 410을 추가했다.
- 독립 적대 리뷰 2명이 per-FETCH `statement_timeout`의 누적 제한 부재, seal 첫 lock의 무제한 대기,
  vacuum 관측불능 warning 누락, generic 410/413 schema와 2-pass 주석 drift를 찾았다. generic 첫 barrier와
  seal/request 첫 `FOR UPDATE`부터 단일 5분 deadline을 적용하고 첫 lock은 5초로 별도 제한했다. 413은
  code discriminator의 item/byte 두 Problem branch, 410은 필수 receipt details로 OpenAPI에 고정했다.
- 집중 테스트 231개와 PostGIS stream repository 37개가 통과했다. 실제 1,005행 1,000+5 INSERT,
  두 번째 scan에서 1,000 item INSERT 뒤 timeout 전량 rollback과 대기 writer 회복을 포함한다. 변경 source
  strict mypy와 Ruff도 통과했다. 1,000,001 synthetic leaf는 약 15.45초/64.7k leaf/s, traced peak 약
  0.003 MiB였으며 accumulator 근거일 뿐 n150 DB 처리량 증거는 아니다.
- 새 typed error로 service OpenAPI bytes가 바뀌어 PinVi exact vendor도 같은 bytes로 갱신했다. 다만 기존
  `77821001`/`e8e0fec` 후보 증거는 이전 계약의 이력일 뿐이므로 T-VN-41 receipt를 `pending`으로 되돌렸다.
  새 source pair의 isolated Live UI acceptance 없이는 `candidate_verified`를 다시 선언하지 않는다.
- terminal audit item compaction과 true receipt/material 분리는 schema 변경 없이는 안전하지 않다.
  T-VN-40C가 `0224`를 예약했으므로 migration 번호를 만들지 않았고, `0225+`용 번호 없는 DDL·downgrade
  fail-close 설계만 `docs/reports/tvn41s/`에 남겼다.
## 2026-08-18 — T-VN-H45 후속: 다건 재시도 예산·provider quota/TLS 정본화

- KMA·DataGoKr·AirKorea·KHOA 다건 호출에 예상 경계 수 5% 올림(최소 8·최대 32)의 공유
  `RetryBudget`을 적용했다. timeout과 내부 재시도 정산을 모든 client 생성 경계에 전달하고,
  provider logger WARNING을 Dagster event stream에 결선했다. 경고에는 예외 본문을 넣지 않고
  label 개행도 escape해 인증키·log injection 경로를 닫았다.
- provider 정본을 먼저 수정했다. python-kma-api #24(`0868b76`)는 `resultCode=22`를
  비재시도 quota로 분류하고 strict XML envelope에서 `03`을 빈 결과로 통일했다. python-khoa-api
  #8(`20c7207`)은 `serviceKey`를 보내는 ODMI·해수욕장정보 기본 URL을 HTTPS로 전환했다.
  Map은 두 merge SHA를 exact pin했다.
- 독립 적대 리뷰 2명은 최초 P1/P2(로그 비밀 노출, XML 03/임의 XML 오분류, KHOA 평문 HTTP,
  CHECK drift 은폐)를 발견했고 반영 후 신규 P0~P3 없음으로 재심했다. Alembic 1.19 CHECK
  comparator 전역 제외는 실제 `provider_sync.source_entities` CHECK drift를 숨겨 완전히 철회했다.
  따라서 ①~③은 완료하지만 ⑤ Alembic 1.19 적응은 열린 barrier로 유지한다.
- 로컬 검증: python-kma-api `149 passed, 12 skipped` + Ruff/mypy, python-khoa-api
  `44 passed, 2 skipped` + compileall/Ruff/mypy, Map 변경 집중 `350 passed` + Ruff/strict mypy.
## 2026-08-18 — T-VN-40 인수 ① 실행: prod가 `0223`으로 올라갔다 (4,424 mapping)

- 순서: read-only precheck(전부 0, `4424|4424`) → `pg_dump -Fc` 복구점(614MB, `.sha256`) + `.env` 백업 →
  소스 스냅샷 `~/ktm-src-14ec2368…` → `.env` 3키(REPO_DIR/GIT_COMMIT/EXPECTED_HEAD=0223) → 이미지 4개 빌드
  → api 재생성(entrypoint의 `alembic upgrade head`) → ui/dagster/daemon.
- **배포 경로**: manager의 `ensure_target`은 production을 거부한다("manage this service directly on the
  host instead"). 그래서 manager의 compose 파일+`.env`로 host에서 직접 `docker compose`를 돌렸다.
  `pinvi-pair rebuild-pinned`는 파괴적이라 쓰지 않았다.
- 결과: `0104 → 0202 … 0223` 단일 트랜잭션 성공, manifest `total=4424 by_kind={'legacy_projection': 4424}`.
  사후 확인 — legacy 4424 = mapping 4424, `source_row_hash` 재계산 불일치 0, dangling 0,
  `legacy_projection_id` 포인터 불일치 0, 0222 procedure 5개 owner=command_owner/SECDEF·dagster EXECUTE=false,
  legacy 표 runtime 권한 SELECT only, temp 잔존 0. 4 컨테이너 healthy(restart 0), traceback 0, 5xx 0.
- **배포 중 API가 두 번 내려갔다(데이터 무손상, 둘 다 문서화).**
  (1) `0202`가 요구하는 `ktm_curation_*` NOLOGIN role 4개가 prod에 없어 42501 재시도 루프 →
  bootstrap profile one-shot(`docker/postgres-role-bootstrap.sh`, idempotent)을 먼저 돌려 해소.
  (2) **Map 결함** — manager compose가 `KOR_TRAVEL_MAP_API_PINVI_CURATION_*_TOKEN_SHA256`을 `${NAME:-}`로
  항상 주입하는데 `min_length=64`가 빈 문자열을 `string_too_short`로 거부해 API 기동 자체가 막혔다.
  manager 계약대로 PinVi raw pair+digest를 `.env`에 넣어 즉시 복구했고, Map 쪽은 ""를 unset으로
  정규화하는 hotfix(`fix/api-settings-empty-pinvi-digest`)로 고쳤다.
- 교훈: "prod 배포 = 이미지 교체"가 아니다. migration이 새로 요구하는 **DB role**과 compose가 항상
  주입하는 **빈 env**가 각각 기동 게이트다. `docs/deploy.md`에 두 선행조건과 실행 절차를 박았다.
## 2026-08-18 — T-VN-40-mapping: 0223 identity mapping loader (설계 → 리뷰 → 구현 → 리뷰)

- 설계 문서를 먼저 쓰고 적대 리뷰 2명(data/PinVi · migration/ACL)을 통과시킨 뒤 구현했다. 리뷰가 바꾼 것:
  `RAISE NOTICE`는 asyncpg 경로에서 버려진다(manifest는 표 재조회로 logging) · prod ①의 `upgrade head`는
  0104→0223 **한 트랜잭션**이라 0223 실패 = 전체 롤백 · fence ACL은 upgrade **뒤** reconcile되므로 loader가
  스스로 `LOCK TABLE … SHARE`(+`lock_timeout 30s`) · `source_row_hash`는 소비자가 대조하는 값이 아니라 적재
  시점 스냅샷 digest · 새 FK가 merge의 detach rekey를 막는 불변식(merge_repo가 명시 MergeConflictError).
- prod 실측(read-only): legacy 4,424 전부 bucket B(projection 1:1), 중단 bucket 전부 0. `scripts/
  tvn40_identity_mapping_precheck.sql`로 ① 직전에 같은 검사를 반복한다.
- 코드 적대 리뷰 2명 hold. P2로 `api-entrypoint.sh`가 loader 중단 문장을 보면 30회 재시도 없이 즉시 종료하게
  했고(테스트로 고정), 0104에서 seed된 중단 형태가 0202~0223 전체를 롤백함을 dedicated DB로 실측했다.
- 남은 것: #996 CI → 머지 → 40C-manifest → ① 실행(precheck → EXPECTED_HEAD 0223 → migration).
## 2026-08-18 — T-VN-40A fence PR #994: 적대 리뷰 P1 — merge가 runtime role로 돈 적이 없었다

- fence 적대 리뷰(2명) 둘 다 `holds=False`. P1: `apply_feature_merge`가 legacy 표를 `FOR
  UPDATE`+UPDATE 3문으로 mirror하는데 fence가 그 권한을 뺐다 → 42501. runtime role로 merge를
  실행하는 통합 테스트(`test_merge_under_runtime_role.py`, `as_api_runtime`)를 새로 써서 red를
  확인했다.
- **그 테스트가 하나 더 드러냈다.** legacy 다음으로 canonical `curation_collections` `FOR UPDATE`
  에서 42501 — fence와 무관한 **기존 결함**(20fa752d). 모든 merge 테스트가 superuser 세션이라
  CI가 못 잡았고, prod의 dedup 병합(`PATCH /v1/admin/dedup-reviews/{id}`·`ktmctl dedup-merge`)은
  이미 깨져 있었다. `0222_tvn40a_merge_runtime_role`: 0204/0214 패턴대로 runtime에 표 권한을
  주지 않고 command_owner 소유 SECURITY DEFINER procedure 5개(legacy lock/archive/sync/move +
  canonical collections lock)를 CALL. 행 잠금은 트랜잭션 범위라 procedure 반환 뒤에도 유지된다.
- P2 4건 반영: infra 전체 legacy write inventory(SQL 문자열 수준, allowlist는 runtime 미도달을
  별도 테스트로 고정) · snapshot 표 SELECT-only + **ACL 표 phantom 2개** 삭제(`curated_tripmate_
  copy_snapshots`·`weather_metric_series` — DB에 없는 표라 reconcile이 건너뛰어 아무 것도 안
  지키고 있었다; "선언된 relation이 실재한다" 통합 테스트 추가) · canonical item write의
  provenance spoof 422 테스트 · admin legacy detail 화면의 write 컨트롤 제거(410 대신 fence 안내).
- 교훈: "runtime role로 통합 테스트가 하나도 없다"는 것 자체가 결함이었다. superuser 세션은 ACL을
  안 보므로 ACL을 건드리는 PR은 반드시 `as_api_runtime`으로 한 번 돌려야 한다.
- **2차 리뷰(수정분)**가 P1을 둘 더 잡았다. (1) `infra/db.py` runtime preflight allowlist에 0222
  procedure가 없어 API/Dagster가 **기동을 거부** — 1차 통합 선택에 `test_tvn34_runtime_privilege_
  preflight`가 빠져 있었다. (2) EXECUTE를 공유 그룹 `ktm_feature_runtime`에 줘 dagster(provider ETL)
  까지 legacy row를 옮길 수 있었다 — 0214 패턴의 절반만 따른 것. 0214 형태 전체(admin executor에만
  EXECUTE, REVOKE runtime 로그인, 본문 `session_user` 게이트)로 고치고 dagster 음성 테스트를 넣었다.
  그 게이트 때문에 `test_merge_repo.py` 21곳이 superuser로는 못 돌게 됐고 전부 `as_api_runtime`으로
  감쌌다 — 이제 merge 통합 테스트 전체가 실제 role로 돈다.
- 배포 선행: orchestrator `.env` `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`→`0222_tvn40a_merge_runtime_role`.
## 2026-08-18 — T-VN-41 #975 rebase pair의 dead-letter recovery 증명 보강

- 적대 런타임 재리뷰의 P2를 반영해, dead-letter를 replay한 직후에도 stream은 여전히
  `blocked`이고 consumer는 disable되어 claim이 `consumer_disabled`로 거부됨을 두 integration
  경로에서 고정했다. consumer 재개는 checksum reconciliation 성공 뒤에만 가능하다.
- mid-claim recovery는 poison event와 뒤따르는 `cache_target.reconciled`를 같은 claim에서 끝까지
  ack하고 다음 claim이 비었음을 확인한다. 따라서 prefix-ack 불변식과 relay 순서의 회복을 끝까지
  검증한다.
- 기존 `77821001`/`e8e0fec` 후보 E2E 증거는 당시 pair의 이력 증거로만 보존한다. 현재 rebase
  head와 새 PinVi pin에는 재사용할 수 없으므로, 원격 CI가 녹색이 된 뒤 새 immutable image·n150
  isolated Live UI E2E·artifact digest로 후보 증거를 다시 만든다. #975는 계속 draft·미병합이다.
- **(2026-08-18 후속, 이어받음)** #975를 `main` `3e0732b3`(#994 fence 포함) 위로 다시 rebase했다(head
  `a78f55dc`; 충돌은 journal/resume 2개뿐). 사용자 결정으로 머지 게이트는 **CI green + 적대 재리뷰 2명**이고,
  새 pair의 n150 isolated Live UI 증거 재생성은 final C7으로 미룬다(격리 pair 러너가 저장소에 없다; 머지는
  candidate 경계라 prod enable 없음). 위 두 항목의 "`ff25c397` 위로 rebase"는 그 시점의 base였고 지금 base는
  `3e0732b3`다.
## 2026-08-18 — T-VN-41 #975 rebase 뒤 stream recovery 회귀 정렬

- #975 후보 브랜치를 `main` `ff25c397` 위로 rebase했다. permanent NACK가 consumer를
  fail-closed로 disable하는 현재 계약 때문에 기존 PostGIS integration test 두 건이 직접 claim을
  시도하며 깨진 것을 확인했다.
- dead-letter replay 뒤에는 checksum reconciliation을 성공시켜 `cache_target.reconciled` outbox
  event까지 정확히 전달·ack한 다음 빈 stream을 단언하도록 고쳤다. 재생만으로 consumer를 직접
  enable하는 우회는 만들지 않았다.
- `tests/integration/test_cache_target_stream_repo.py` 33건과 변경 파일 Ruff가 통과했다. 새 Map
  source를 PinVi에 다시 pin하고 원격 CI·n150 isolated Live UI E2E를 통과하기 전까지 #975는
  draft·미병합 상태다.
## 2026-08-18 — #993 rebase 뒤 tasks ledger 전면 정리

- 문서 PR을 `main` `142a1c12`에 rebase하고, 인덱스를 열린 실행 단위만 남도록 다시 정렬했다.
  H25B·H46B~E·H47/H48·C01·C04 완료 요약은 `tasks-done.md`로 이관했고, H46F/G·H34A/B·M00을
  명시 task로 만들었다. H49는 Map baseline 완료와 docker-manager #177 외부 주기화 잔여를 분리했다.
- #975의 n150 후보 증거는 당시 `0e26a232` 기반 exact pair에 한정됨을 명시했다. 현재 main에
  rebase한 새 Map/PinVi 쌍은 CI·isolated Live UI E2E를 다시 통과해야 하며, closed #967은
  재배치 대상이 아니라 새 후속 PR/reopen 판단 대상이다.
- T-VN-40은 사전 fence/mapping/manifest 구현·병합 → prod migration·import/backfill → live/receipt
  → physical removal 실행 순서로 고쳐, 기존 표의 순서 모순을 제거했다.
## 2026-08-18 — T-VN-41 #975 후보 증거 task ledger 정리

- 열린 작업 목록은 T-VN-41A/B/C를 `[~]`로 정렬했다. 정확한 source 쌍의 격리 Live UI 복구와
  증거 결박·적대 재리뷰는 통과했다. 이후 #975 PostGIS CI에서 기존 integration test 2건이
  permanent NACK의 새 consumer disable 계약과 충돌한 것을 확인해, 실제 reconciliation 재개
  경로를 검증하도록 수정 중이다. 후보 E2E 증거는 당시 exact pair에만 유효한 이력이며, rebase된
  새 pair의 머지 근거로는 사용할 수 없다. #975는 미병합 상태다.
- `tasks-done.md`는 완료·폐기·병합 이력 전용이므로, 아직 열린 T-VN-41 항목을 이관하지 않았다.
  후보 receipt는 final main C7이나 production consumer enable을 뜻하지 않는다.
## 2026-08-17 — prod PostgreSQL 4분할(12x00 대역) + 적대 리뷰 반영

- n150 prod의 PostgreSQL을 프로젝트별 전용 instance로 나누고 포트를 각 대역의 `x00`에
  맞췄다: geo `12500`(33GB, 제자리) · concierge `12600`(79MB 이관) · map `12700`(제자리) ·
  pinvi `12800`(11MB 이관). 넷 다 `listen_addresses=127.0.0.1`이고 **`5432`를 듣는 것은
  없다**. 근거는 docker-manager **ADR-37**(이번에 신설 — 그전까지 4분할에 ADR이 없었다).
- **DB만 나누는 것으로 부족했던 이유**: role·ACL·확장은 DB가 아니라 **cluster 전역**이다.
  08-15에 map을 전용 인스턴스로 뺀 뒤에도 통합 인스턴스에 `ktm_` 역할 7개가 남았고 map
  migrator 자격증명으로 `kor_travel_geo`(33GB)에 실제로 접속됐다. 지금 geo 인스턴스의
  LOGIN role은 자기 superuser `addr` 하나뿐이다.
- 이관 검증은 카탈로그 대조가 아니라 **기능**으로 했다 — concierge 28테이블/39,515행,
  pinvi 52테이블/265인덱스 일치에 더해 map ETL `feature_place_knps_points_job`을 실제로
  돌려 SUCCESS(run `591f5e69`)를 받았다. 08-15 이관 때 카탈로그 2,486행이 "전부 일치"였는데
  schema ACL과 membership option 결함 2건이 살아남아 cutover 뒤 ETL에서야 드러난 적이 있다.
- **적대 리뷰가 P1 9건 + P2 4건을 찾았고 전부 반영했다.** 실질적이었던 셋:
  - `c6c_deployment.py`가 `12703`을 하드코딩해 **다음 sanctioned 배포를 fail-close로 막을
    상태**였다. 테스트 픽스처도 12703이라 테스트는 초록이면서 배포만 막힌다.
  - `.env.example`가 옛 포트 그대로였다. 이번 사고의 원인이 `.env` override인데 그 `.env`를
    만드는 템플릿을 안 고쳤으니 다음 사람이 같은 사고를 재현할 상태였다.
  - `backup-restore.md`의 드리프트 점검 명령이 `:5432/`를 찾고 있었다. 찾아야 할 옛 포트는
    12703이고 5432는 애초에 없다 — **항상 초록인 거짓 안심**이었다. 현재 배치 4개와
    대조하는 형태로 바꿨다.
- ktm 쪽 문서 결함도 함께: `KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT`는 `load-env.sh`가
  export하고 문서 3곳이 "override한다"고 설명했지만 **읽는 곳이 하나도 없었다**. 포트를
  12700으로 고쳐도 접속 대상이 안 바뀐다 — 죽은 포트를 가리키는 것보다 효과 없는 손잡이가
  더 나쁘므로 변수를 제거하고 "포트는 DSN 안에 있다"로 정정했다.

### 사고 1건 (자책 아니라 재발 방지용 기록)

`docker-targets.yml`을 바꾼 뒤 manager backend(config를 `lru_cache`로 붙든다)를
재시작하면서 환경변수를 `/proc/PID/environ`으로 옮기려 했다. 그 스크립트가 `sh`에서
`read -d ''`(bash 전용)를 써서 조용히 실패했고, `env -i`와 겹쳐 manager가 **KTDM_* 0개**로
약 2분간 떠 있었다. `health`는 200이라 겉으로는 정상이었고 admin 로그인만 죽는 상태였다.
`.env`를 직접 `source`해 다시 띄워 32개 복구, 인증 강제(무세션 401)·web 200 확인.

교훈은 늘 같은 것이다 — **health 200은 "동작한다"의 증거가 아니다.** 무엇이 죽었는지
알려면 죽었을 때 달라지는 것을 봐야 한다(여기서는 KTDM_* 개수).
## 2026-08-17 — T-VN-41A-C current-main 재배치와 stale writer/cancellation outbox 봉합

- PR [#975](https://github.com/digitie/kor-travel-map/pull/975)를 현재 `main` 위에
  재배치했다. refresh finalization은 캡처한 모든 member의 restore epoch·source
  generation·payload fingerprint를 stream→head canonical lock 순서로 다시 확인한
  같은 transaction에서만 link·freshness·done을 확정한다. source writer가 그 사이
  한 member라도 바꾸면 terminal success와 stale link/freshness가 전부 rollback된다.
- queued service refresh 취소는 job의 `cancelled` 전이와 exact captured tuple
  `(restore_epoch, source_generation, source_payload_fingerprint)`의 outbox status를
  한 transaction으로 기록하게 했다. queued/running/cancelled의 과거 tuple 사실과
  final target mutation의 current-tuple fence는 의도적으로 분리한다.
- 두 적대적 재리뷰에서 DB/동시성 P0/P1은 없었다. Map service OpenAPI는 현재
  SHA로 재생성했고 PinVi 수동 PUT의 409 설명도 좌표 conflict와 source protocol
  위반을 모두 명시했다. PinVi service vendor 재고정과 paired contract CI는 완료했으며,
  T-VN-41 receipt는 `pending → candidate_verified → complete`를 fail-closed로 구분한다.
  n150 후보 검증은 exact archive·C7 runtime 다섯 immutable image·attestation·evidence digest를
  남겨도 final main C7 이전에는 `complete`/consumer enable을 선언할 수 없다. candidate와
  final receipt는 source commit·다섯 image·attestation/evidence digest를 별도 필드로 강제한다.
## 2026-08-17 — 완료된 Wave 2 task 이력 아카이브 정리

- `tasks.md`에서 완료된 T-VN-34/35/36 배포·인수 블록을 제거하고
  `tasks-done.md`에 2026-08-13 prod cutover 요약으로 이관했다. 열린 Wave 2 백로그는
  T-VN-37D, T-VN-40 release 수용, T-VN-39만 유지한다.
- 인덱스와 상세의 비표준 `[/]` 표기를 `[~]`로 정규화했다. 이 변경은 문서 상태 정리만이며
  코드·DB·runtime·배포 변경은 없다.
## 2026-08-16 — T-VN-40 구현·연동 소비자 PR 병합 상태 정리

- Map 구현 PR [#974](https://github.com/digitie/kor-travel-map/pull/974)는
  `170ddf57`로 병합됐고 Python 3.11/3.12/3.13, fixture replay, lint, OpenAPI, frontend,
  PostGIS integration CI가 모두 녹색이다.
- 연동 소비자 PinVi [#445](https://github.com/digitie/pinvi/pull/445)와 Docker Manager
  [#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)도 병합됐다. 현재
  T-VN-40 receipt는 의도적으로 `pending`이며, 다음 실행은 n150 canonical import/backfill 실운영
  인수다. 그 증거 전에는 receipt complete·legacy 물리 삭제를 수행하지 않는다.
## 2026-08-16 — T-VN-40 PostGIS typed runtime CI 수리

- provider operation과 provider cancellation terminal 통합 회귀를 실제 Dagster/API
  LOGIN으로 실행하게 정렬했다. root/migrator session이 executor ACL을 우회하던 테스트
  경계를 없애고, API cancellation의 transaction-local finalizer 위임과 queued root의
  heartbeat·tracking invariant 수렴을 함께 검증한다.
- SECURITY DEFINER attempt event writer가 사용하는 `ops.import_job_event_clock` 권한을
  command owner에만 보완했다. 격리 collection marker는 SQL NULL 비교를
  `IS DISTINCT FROM`으로 fail-close해 제거된 marker를 다시 확정할 수 없게 했다.
- committed operation projection test는 seed 전에도 동일한 committed-row 정리를 실행하고,
  candidate runtime test는 dispose한 Dagster engine을 재사용하지 않도록 고쳤다. focused
  PostGIS 회귀 100건과 변경 파일 Ruff 검사를 통과했다. runtime privilege 음성 test도
  두 LOGIN engine을 정확히 한 번씩 dispose해 Python 3.13의 ResourceWarning 없이 끝낸다.
## 2026-08-15 — T-VN-40 PostGIS CI runtime 격리 정렬

- runtime privilege preflight가 T-VN-40 migration bootstrap과 다른 disposable LOGIN
  비밀번호를 재설정해 뒤 candidate command 연결을 실패시키던 순서 의존성을 제거했다.
  모든 runtime LOGIN fixture는 bootstrap의 T-VN-40 test-only password를 사용한다.
- public collection은 trusted public Feature에 연결된 item만 반환한다. 미연결 item은
  public projection에서 제외하고 admin projection에 보존한다는 현재 정책을 integration
  fixture와 count assertion에 명시했다.
## 2026-08-15 — T-VN-40 Dagster CI 테스트 경계 정렬

- authoritative snapshot 경로로 전환된 concierge asset의 fake client에 적재·retirement를 한
  causal 결과로 돌려주는 구현을 추가했다. upsert와 tombstone 양쪽 asset 경로가 같은 production
  호출 계약을 계속 검증한다.
- OpiNet test double은 authoritative curation dataset keyword를, feature-operation terminal test는
  nullable curation input proof 두 필드를 명시한다. production 함수의 새 proof 인자를 누락한
  테스트 double 때문에 Python matrix CI가 막히지 않게 했다.
## 2026-08-15 — T-VN-40 service OpenAPI contract test 정렬

- restore-fence는 최초 terminal `201`과 exact `Idempotency-Key` replay `200`을 모두 선언한다.
  registry test는 replay response를 별도 성공 상태로 허용하되 상태 코드와 ETag header를
  정책과 정확히 대조하도록 했다.
- canonical cutover identity mapping export를 service OpenAPI exact route inventory에 넣어
  기존 route policy·생성 artifact와 같은 표면을 검사한다.
## 2026-08-15 — T-VN-40 admin OpenAPI 생성형 타입 동기화

- canonical cutover identity mapping service export를 admin frontend의 `src/api/types.ts`에
  재생성했다. CI의 OpenAPI type drift gate가 현재 Map API artifact를 기준으로 검사한다.
- backend contract를 바꾸지 않는 생성물 정렬이며, `gen:types:check`로 같은 artifact를
  다시 확인한다.
## 2026-08-15 — T-VN-40 branch CI 경계 정렬

- Geo BFF는 요청 시점의 전용 Geo key만 읽고, 앞선 테스트의 module cache가 다음 요청의 credential
  판정을 오염시키지 않게 했다. 키가 없으면 `GEO_API_KEY_NOT_CONFIGURED` 사유로 fail-close하며,
  VWorld provider key fallback은 계속 금지한다.
- clone live runner는 candidate geo를 실제로 띄우지 않으므로 UI build의 Geo key를 빈 값으로 명시한다.
  stale test expectation을 현재 fail-close 동작에 맞췄다.
- H35 wheel contract가 호출하는 `uv`를 Python matrix CI에 명시 설치했다. CI lint와 focused Python·UI
  test를 재실행했다.
## 2026-08-15 — T-VN-40 Manager canonical curation principal 결선 대기

- Docker Manager PR [#174](https://github.com/digitie/kor-travel-docker-manager/pull/174)가 PinVi canonical
  snapshot·cutover mapping 원문 token pair에서 Map API 전용 SHA-256 digest를 frozen C6c environment 안에서
  파생하도록 구현했다. Map API는 digest만 받고 원문은 ordinary PinVi API에만 남으며, UI·Dagster·bootstrap
  및 PinVi Web·Dagster로의 이름·값 누출은 raw/resolved Compose gate가 container mutation 전에 거부한다.
- 이 PR은 아직 draft이며 T-VN-40 rollout receipt도 `pending`이다. n150에 token을 설치하거나 receipt를
  complete로 전이하지 않았다. 병합 뒤 canonical import/backfill live acceptance와 paired artifact receipt를
  같이 확인하는 것이 다음 release gate다.
## 2026-08-15 — T-VN-40 n150 canonical curation principal 격리

- isolated n150 runner가 매 실행마다 서로 다른 canonical snapshot·cutover mapping token을
  만들고, Map API에는 두 SHA-256 digest만, PinVi API에는 두 원문 token만 전달하게 했다.
- Map compose도 두 digest를 API service에만 선언한다. Dagster·daemon·frontend와 Map의
  어느 runtime도 canonical curation token 원문을 받지 않는다.
- 다음 production/Manager 결선에서도 이 네 값과 scope 분리를 유지해야 하며, paired
  receipt complete는 그 live acceptance 뒤에만 허용한다.
## 2026-08-15 — T-VN-40 paired service receipt 배포 gate 강화

- installer와 n150 runner가 active complete receipt의 정확한 key set을 요구한다. Map의
  `openapi.user.json`·`openapi.service.json`·`openapi.json`, PinVi의 user/service vendored
  OpenAPI를 같은 immutable source archive에서 각각 해시하고, Map↔PinVi user/service digest
  동치와 canonical importer·live acceptance 검증 문구도 확인한다.
- legacy admin detail vendor는 T-VN-40 active receipt/runner에서 제거했다. 완결 receipt가
  그것을 다시 포함하거나 service vendor를 빼면 install 전에 fail-close한다.
- install manifest format을 version 4로 올렸다. pending receipt는 기존처럼 source archive와
  remote 접속 전에 거부한다.
## 2026-08-14 — dagster-daemon 이미지 누락 + prod DSN 경계 실측 (T-VN-H46D/#51)

### `docker-buildx.sh`가 daemon 이미지를 굽지 않았다

`scripts/docker-build.sh:12`는 네 서비스(api/frontend/dagster/dagster-daemon)를
빌드하는데 `scripts/docker-buildx.sh`는 셋만 구웠다. 두 파일이 서로 모순인 채로 오래
있었고, 저장소가 "map 이미지는 3개"라는 틀린 모델을 성문화하고 있었다.

2026-08-13 prod 재빌드에서 그 누락이 났다. daemon은 자기 이미지 안의 패키지를
in-process 로드하므로 옆의 code server가 최신이어도 소용이 없다. TVN33 커토버가
`ops.feature_update_requests.providers`를 지운 뒤 daemon만 8일 묵은 코드로 남아
`feature_update_request_queue_sensor`가 30초마다 죽었다(실측
`consecutive_failure_count=2020`). 큐가 비어 있어 운영자에겐 무반응으로만 보였다.

**한 번 빌드에 태그 두 개로 고쳤다.** `build_one`을 두 번 부르면 두 이미지가 같은
코드라는 보장이 없는데(캐시 미스·비결정적 레이어), 그 "같음"이 바로 여기서의
요구사항이다. 그래서 `build_one`의 첫 인자를 이미지 목록으로 바꿨다.

가드도 두 층이다. Dockerfile 다중집합 비교와, 그 둘이 **같은 build 호출**에서
나오는지. 변이로 확인했다 — daemon 태그를 빼면 3개 전부 실패하고, 한 번 빌드를 두 번
호출로 되돌리면 후자만 실패한다. 후자가 없으면 그 회귀는 조용히 지나간다.

수리된 prod가 그 형태를 그대로 보여 준다. `kor-travel-map-dagster:latest-main`과
`kor-travel-map-dagster-daemon:latest-main`이 **같은 digest**(`443cd970c09a8b40`)를
가리킨다 — 이름이 둘, 이미지가 하나. 두 컨테이너는 2026-08-14 00:13/00:27 UTC에
떴고, 1분 주기 `current_weather_summary_refresh`가 그 직후부터 463회 연속 성공했다.
그 전에는 `feature_update_request_queue_sensor`가 30초마다 죽고 있었다.

### prod DSN 경계 — 조사 중 정본 DB를 착각했다

먼저 적어 둔다. 이 조사에서 한참을 `ktm-tvn36-db` 컨테이너를 정본으로 보고 결론을
냈고, 그게 틀렸다. **prod 호스트 5432는 `kor-travel-geo-postgres`다** — map이 geo와
인스턴스를 공유한다(#46이 떼어내려는 대상). `ktm-tvn36-db`는 18736에 있는 잔여물이고
`feature.features`가 1행이다. 그 잘못된 DB에서 "runtime 역할이 쓰기 권한 0"이라는
겁나는 수치가 나왔는데, 정본에서는 읽기 94 / 삽입 84 / 갱신 82로 정상이다.
`127.0.0.1:5432`라는 DSN만 보고 어느 인스턴스인지 확인하지 않은 것이 원인이다.

정본 실측 — features 1,004,975행, alembic `0104_tvn36_final_fence`. 그 리비전 id는
`0201_squash_bridge.py`가 선언한 값이고, prod가 squash된 baseline 위에서 정확히
resolve된다는 뜻이다. 브리지 설계가 prod에서 실증됐다.

경계 위반은 두 가지다. prod compose는 git 체크아웃이 아니라 `origin/main` +
**손으로 넣은 6줄**이고, 그 6줄이 api/dagster/daemon 셋 모두에 migrator와
api_runtime DSN을 준다. `api-entrypoint.sh`가 두 값을 폴백 없이 요구하니 api를
띄우려고 넣은 줄을 나머지 둘에도 붙인 것으로 보인다. 그 두 이름을 읽는 코드는
저장소에 `api-entrypoint.sh` 하나뿐이라 dagster/daemon에서는 순수한 노출이다.
두 번째로, prod의 `KOR_TRAVEL_MAP_PG_DSN`이 세 서비스 모두 **dagster runtime**
역할이다 — 저장소는 api의 같은 자리를 API_RUNTIME에서 채운다. 두 역할의 권한이
동일해서 오늘 깨지는 것은 없고, 깨지는 것은 감사 추적과 한쪽만 조이는 능력이다.

수정은 이미 docker-manager의 `agent/issue-171-map-dedicated-postgres`에 있다.
별도 PR을 만들지 않고 #46 배포에 실린다.

### admin UI만 geo 소비자 키를 못 받고 있었다

정본 키는 api/dagster/daemon 셋에만 갔다. UI 프록시는
`KOR_TRAVEL_GEO_API_KEY` → `NEXT_PUBLIC_…` 순으로 읽는데 둘 다 없어서 키 없이 상류에
붙었고, geo의 `400 E0100 field=key`가 화면에는 "invalid request data"로 보인다 —
자격증명 누락이 아니라 요청 형식 오류처럼 읽힌다. docker-manager
`fix/map-ui-geo-consumer-key`에 런타임 이름 한 줄로 넣었다(재빌드 불필요).

그리고 prod `.env`의 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`는 **VWorld 키 그 자체다.**
값의 sha8이 `KOR_TRAVEL_GEO_VWORLD_API_KEY`·`NEXT_PUBLIC_VWORLD_API_KEY`·
`PINVI_VWORLD_API_KEY`·`KOR_TRAVEL_MAP_API_VWORLD_API_KEY`와 같은 그룹이고, geo에
걸면 `401 E0401 "VWorld 호환 인증키가 유효하지 않습니다"`가 그대로 난다. 8/13 사고를
만든 값이 이름만 바꿔 아직 거기 있다. 지금은 어느 compose도 이 이름을 참조하지 않아
당장 깨지는 것은 없지만, 다음 운영자가 집어 쓰면 사고가 재현된다.

PR #979의 정적 가드가 "운영자 `.env`는 못 본다"고 적어 둔 바로 그 축이고, 실제로
오염돼 있었다. 가드는 저장소가 잘못된 값을 권하지 않게 할 뿐이다.

확인하다 두 번 헛짚었고 둘 다 적어 둔다. geo `/v2/reverse`는 키를 **query
파라미터**로 받는데 본문에 넣어서 인증 이전에 `400`으로 떨어졌고, 하마터면 유효한
키를 무효로 판정할 뻔했다. 그 전에는 셸에서 `tr -d`로 따옴표를 지우다 값이 오염돼
sha8이 실행마다 달라졌고, 그 오염된 해시를 근거로 "세 값이 전부 다르다"고 판정했다 —
실제로는 둘이 같은 값이었다. `.env` 파싱은 파이썬으로 옮기고 나서야 안정됐다.
