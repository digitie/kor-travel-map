# A3 제한 EX authoritative refresh — 구현 checkpoint

## 범위와 아직 남은 수용

기준은 A2 f138과 main1390의 제품 합집합이다. 기존 active primary place의 비활성
Geo/분류·typed base/effective 의미는 legacy EX로 유지하고, 활성 name/phones는 SH와
동일한 후보·winner로 닫는 명시 경로다. 운영 선택/정책 seed는 0이다. 전체 provider의
5000건 수집·내구 artifact·실제 worker 전수 수용을 완료했다고 표시하지 않는다.

최종 집중 실행은 `/tmp/map419-final-focused.log`의140PASS90.70초와 별도 기존
converter `/tmp/map419-provider-converter-regression.log`의50PASS0.92초, 중복 없는
합계190건이다. 부모146건과 A3 PG18/단위4·J tracking4·resource18을 포함한다.
SDK는 정본 pin을 설치한 전용 target에서 실제 실행했고 기본 CI의 optional skip과 구분한다.
root/W의6de 제품 delta 승인은 받았지만 아래 최종 시험·문서·main 합성 pin 재대조,
이 문서 고정 시점의 정확 CI와 fresh UI는 대기다. 최종 정확 SHA별 CI·두 리뷰·UI 수용은
PR 본문과 감사 원장을 참조한다. 초기/중간 수치는 합산하지 않는다.

## 실제 전후 증거

- `/tmp/map-exclusive-full-refresh-before.log`: 실제 legacy loader가 canonical claim을
  만든 두 place를 lab에서만 활성화한 뒤 재수집해 source_links UPSERT의23514로
  **1FAIL14.34초**. 이 원본 실패를 유지한다.
- `/tmp/map-exclusive-full-refresh-first.log`: 최초 수정1PASS/1FAIL14.26초. 기존 생성
  wrapper의 INSERT BEFORE guard를 지나려다 active target에서 거부됐다. 명시 active
  existing 경로만 create wrapper를 건너뛰고 계획에서 검증된 canonical ID의 정본
  field patch를 사용하도록 고쳤다. 신규 identity를 이 예외로 생성하지 않는다.
- `/tmp/map-exclusive-full-refresh-second.log`: 기본 legacy23514 유지와 명시 source→
  candidate/winner→capture→finish 및 completed 동등 replay **2PASS14.39초**.
- `/tmp/map-exclusive-full-refresh-third.log`: 실제 Geo stamp/분류 변경을 동적 client로
  적용, A완료→B완료→옛A stale 거부, 두번째 실제 source DML 실패의 전체 rollback과
  자기 plan cancel 뒤 같은 입력 fresh 재시도까지 **5PASS16.19초**. synthetic typed
  fixture이며 실제 SDK HTTP/전체 asset 실행으로 세지 않는다.
- `/tmp/map419-unit-first.log`: 순서/Geo/retire 지문, MAX+1 중단, 전체 byte 예산의
  개별 raw hash 선행, 중복 entity 거부 **4PASS1.00초**.

모든 PG는 소유 fixture의2CPU/1536MiB/PID256 container를 사용하고 finally에서 정리한다.
초기 oracle 명령은 `/tmp` 수집에서 repo pytest 설정을 빠뜨려 async fixture setup 오류가
났다. `-c pyproject.toml`로 재실행한 기록 모드는1skip13.70초이며 PASS로 합산하지 않는다.
최종 canonical oracle 비교·metadata는 `/tmp/map419-final-oracle-metadata.log`의
2PASS22.16초다. SQL sidecar4개와 생성 head 내용은 초기 checkpoint와 같다.

## 명시 선택과 private 증거

`AsyncKorTravelMapClient(..., exclusive_provider_snapshot=ExclusiveProviderSnapshotOptions(...))`
가 선택된 provider/dataset의 실제 최종 snapshot_bundles·Geo·retire 옵션을 받는 시점에
plan을 만든다. Options는 `kortravelmap.infra.exclusive_provider_refresh`에 있다.
미래 converter clock을 미리 만든 정적 plan이나 fakeclient 치환이 아니다. 기본 None과
다른 scope는 기존 load 분기를 사용하며 추가 planning SQL이 없다. 상위 transaction에
묶인 client는 선택 경로에서 명시 거부한다. 실제 Dagster resource 설정 연결과 실제
tracked asset 시험은 아래 별도 저자 합성 항목이다.

새 table이나 ops raw SELECT/DML grant를 추가하지 않는다. 기존 applying+sameTX+EX
attempt, 활성 Feature의 완전 member/source-head manifest, epoch/owner 검증을 재사용한다.
전용 idempotency key는 `native-full-refresh-v1:<inputdigest>:<attemptnonce>`다. marker는
용도 구분이고 독립 권한 증거가 아니다. 같은 지문도 실패 뒤 새 attempt로 계획할 수 있다.

동일 primary link의 role/match_method/confidence를 잠금 아래 확인한 경우만 불필요
UPSERT를 생략한다. shared entity는 상대 Feature가 퇴역 area여도 첫 source DML 전에
거부한다. active kind·parent/sibling·identity/membership/lifecycle 변경은 계속 지원 밖이다.
SQL guarded context는 같은 Feature/dataset의 manifest를 검증하고, 비활성 base는 기존
canonical current source+registry typed 검증을 사용한다. 활성 필드의 winner/clock 검증은
그대로다. 활성 필드는 legacy LWW base patch에서 제외하고 shadow OFF에도 정본 scoped
capture/recompute를 필수 실행한다. 임의 EX 보유만으로 guard를 해제하지 않는다.

## 전체 입력·완료·실패

전체 domain은 입력 원순서, dataset/정책 선택, 모든 bundle과 실제 Geo 사용/current
reference/관측 token 집합, retire 옵션을 바인딩한다. active lock 순서만 정렬한다.
MAX+1에서 즉시 중단하며2730개/전체1MiB/depth64/manifest8192를 유지한다. 입력은
caller가 planning부터 apply await 종료까지 독점 소유하고 수정하지 않는다. 상한을 넘는
입력을 분할 commit하거나 scalar subset receipt를 전체 snapshot 성공으로 꾸미지 않는다.

쓰기 TX는 RC에서 load→별도 entity의 비활성 area retire→전체 count/hash capture→제한
attempt finish 순서다. result digest는 full input·manifest/정책 subset·당시 capture를
결합한다. target 결과는 canonical UUID·core row_revision·Geo stamp의 DB 해시다.
정본 force_features_row_revision BEFORE UPDATE trigger는 모든 core UPDATE에서 OLD+1을
강제하고, 기존 capture는 detail·override lineage도 포함한다. 전체 core JSON을 다시
직렬화하지 않으면서 stamp-only와 core 변경을 각각 구분한다. completed는 현재 readonly capture와 target을 재구성해 저장 지문과 같을 때만
source/candidate/winner/finish DML0으로 반환한다. 기존 kernel begin 자체의
scope INSERT ON CONFLICT까지 모든 SQL DML0이라고 부르지는 않는다. 다르면 stale/replan이고 새 current capture를 옛 성공에
붙이지 않는다. 과거 insert/update 숫자는 저장되지 않아 복원하지 않으며 replay 카운트는0,
retired는 불명(None)으로 표시한다. client의 새 호출은 항상 새 plan이고 완료 plan을 새 run
성공으로 전달하는 경로는 거부한다.

apply 실패/취소는 전체 rollback 뒤 자기 ready plan을 fresh TX에서1회만 cancel한다.
정리 budget은 협력적2초/문장1초/lock250ms이며 원예외를 덮지 않고 background cleanup
태스크를 남기지 않는다. 정리 불가시60초 lease는 **apply TX가 종료되어 잠금을 놓은 뒤**
남은 owner 예약의 복구 상한이다. 살아 있는 PG backend/idle TX의 rowlock까지 lease만으로
제거하지 않는다. 완료 commit이 불확실해도 기존 cancel은 completed를 변경하지 않는다.
planning과 apply는 각각30초의 협력적 호출 예산이다. claim/membership은 target당 왕복하지
않고 정렬된 bulk SELECT1회로 읽는다. 두 단계 사이 commit/DB 정리 시간은 별도이며
단일60초 hard cap으로 부르지 않는다. 전체 apply의30초는 협력적 호출 상한이며 동기 CPU 선점/commit의 hard cap이 아니다.

기존 count/hash capture는 SELECT다. 영속 child snapshot receipt는 후속 별도
SERIALIZABLE TX에서 exact root/child/member와 현재 집합을 다시 대조한다. scoped begin의
fresh RC 요구와 합쳐 한 TX로 바꾸지 않는다. 기존 root receipt/취소 검증은 대체하지 않는다.

## 지원 밖과 남은 gate

`FeatureBundle.file_sources`는 현재 DTO에만 보존되고 실제 client/legacy loader가
업로드/등록을 수행하지 않는다(client 모듈의 후속 TODO). 기존 DTO 설명을 실행 사실로
세지 않는다. 이번 변경은 업로더를 구현하지 않는다. 파일 적재 원자 성공/실제 전송 증거는0이다.

- [ ] 최종 고정 pin의 두 독립 제품·문서 재대조/정확 CI·fresh 실제 UI
- [ ] 5000건/큰 artifact·내구 worker 인계·ARM 비용·운영 opt-in 별도 수용

모든 T-CWRITE 전체 완료 체크박스는 계속 미완이다. EX 경로는 SH 병렬 처리 성과가 아니며
같은 dataset은 기존 단일 owner/dataset 잠금으로 직렬화한다.


## 별도 저자 합성과 확장 시험 경계

root의 bd87 resource commit과 4d77 Compose/example commit을 합성했다. 새 국가유산 전용
flag는 기본 false이고 code-server에만 명시 전달한다. root의 정확 커밋 대상18PASS2.44초는
초기18건과 합산하지 않는다. T/W가 별도 소유권으로 독립 검토한 변경이며 실제 운영 env는0이다.

J의 e599 baseline과 e9a033 실제 asset EX 시험을 신규 전용 파일로 합성했다. 실제 pinned
public SDK HTTP대역→converter/Geo→실제 client/정본 tracking wrapper를 사용하며 fakeclient
메서드 치환이 아니다. J의4PASS16.91초는 legacy 정상·후속 seal drift 및 EX 성공·두 번째
실제 source DML rollback/cancel을 구분한다. RC capture와 별도 SERIALIZABLE child seal,
뒤의 root completion을 관측한다. 실제 Dagster worker·운영 수집으로 세지 않는다.
최종 A3 소스와 결합한 재실행은 별도 gate다.

17건 확장 시험은 혼합 active2/비활성 existing1·신규1/별도 entity area retire, stamp-only
stale, bulk planning1회와 planning 전체 취소 rollback, 잘못된 owner/mode/target의 preDML
거부, 반복 취소/짧은 lease 후 takeover와 old owner fencing, SH/EX 동일 활성 projection,
실제 bound client 거부, 닫힌 ACL을 포함한다.
이전 `/tmp/map419-all-contract-pg.log`의14PASS3FAIL은 시험 fixture 실패로 보존한다.
하나는 공유 fixture의 전역 attempt 수를0으로 가정했고 dataset 범위로 수정했다. 두 개는
historical area의 immutable source ownership을 재바인딩하려다가 기존23514로 차단됐다.
guard를 끄거나 active cutover를 위조하지 않았다. live/retired area 모두 재바인딩이
거부되고 정책 미활성임을 확인하는 회귀로 수정했다. 따라서 이 두 건은 이미 공유된
active place+area에 대한 새 full entry 분기 실행 증거가 아니다. 별도 entity retire 성공과
정적 validator의 shared entity 거부는 구분한다.


## 최종 경계 반증과 정적 게이트

새 회귀 `test_fresh_old_input_after_new_head_is_not_false_success`는 A 계획 cancel→새 B 성공
뒤 옛 A를 **새 plan**으로 호출한다. 실제 upsert의 became_current=False를 관측한 뒤 정본
current-source 검증23514로 전체 rollback/cancel되고 B head와 capture가 유지된다.
completed 재사용 시험과 별개이며 이 반증에는 제품 변경이 없다.
단독 원장 `/tmp/map419-fresh-old-input.log`는1PASS13.99초이고 최종18PG에 포함되어 중복 합산하지 않는다.

최종 `/tmp/map419-final-lint-docs-r2.log`는377PASS/기존6skip29.91초다.
첫 원장 `/tmp/map419-final-lint-docs.log`의376PASS6skip1FAIL은 late 조립 sidecar 이름을
정적 배선 검사가 읽지 못한 실패다. 네 full filename 리터럴과 같은 read 순서로 바꿨고
ordered DDL bytes/SHA는 같으며 검사기를 완화하지 않았다. 실제 fresh upgrade/oracle2건도
통과했다. Ruff12경로, strict mypy5파일, import4계약을 통과했다. 최종 문서 편집 뒤
archive 링크/크기4건은 다시 확인한다.

새 opt-in 자원 wiring은 future worker 실행의 선택 seam이며 이번 실제 asset 시험이
Dagster resource를 기동한 worker라는 뜻은 아니다. public SDK HTTP는 fixture transport,
Geo는 고정 계약이며 실제 외부 API 네트워크는0이다. 같은 dataset은 단일 owner/범위 잠금으로
직렬 처리된다. EX whole refresh의 실제 수용은 SH 운영 병렬화나 전체 writer 폐포의 완료가 아니다.
