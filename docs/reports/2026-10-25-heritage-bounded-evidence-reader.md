# Heritage bounded evidence reader — 초기 구현

첫 checkpoint는 입력 계약만 구현했다. 다음 checkpoint는 422 migration/정적 SQL reader·private metadata/shape 검사와 Python 응답 검증을 추가한 source 초안이다. 첫 실제 PG 설치는 migration 배선에서 setup ERROR였고, 최소 수정 뒤 실제 SDK3shape reader positive1 PASS를 확보했다. 실제 SH collector에 연결하지 않았다. 기존 공개 client/SQL/수집 동작·기본 EX·정책과 운영 설정은 바꾸지 않았다.

## 현재 확인

- source7e에서 별도 worktree/branch로 시작했다. 입력 dataset은 양의 PG bigint, entity key는 exact se_+64hex다.
- iterable은 MAX+1까지만 소비한다. 1..2730 입력과 중복 거부, 보수적 배열 전송 예산을 확인한다. 결과 완결성은 SDK/A1 적격성 또는 apply 권한과 구분한다.
- 순수 단위16 PASS(1.43초), 변경 Python Ruff PASS, strict mypy1파일 PASS, redaction/diffcheck PASS. 첫 Ruff의 StrEnum/raises match 지적3건은 해당 새 파일 안에서 고쳤다. 이 결과는 DB/메모리/새 reader 성공이 아니다.
- 설계r3는 독립 두 리뷰를 받았다. 무근거 N32 제한·요청 외 전체 dataset 필터·datum header 크기 혼동·metadata 이전 문자열 비교 지적을 수정했다.

## 다음 구현과 미완

422의 source에는 STABLE pure-read SD/static SQL/search_path pg_catalog와 typed infra wrapper를 추가했다. private table SELECT를 runtime에 열지 않는다. metadata 이후 payload의 내부 위치는 같은 snapshot의 tableoid/ctid 쌍으로만 사용하고 외부 identity로 내보내지 않는다.

입력 배열 자체 검사, 모든 가변 열 inventory·양측 text JOIN의 metadata CASE, SQLNULL/JSONnull 구분, 전체 binary256KiB·encoded1MiB와 row 상한, 저장 normalizer/core.name header·R1/R2·base24/field별 clock, claim·primary-only 전체 membership·lifecycle/stamp/epoch·dataset retire0 검사의 source 초안을 작성했고 bfed checkpoint의 full source/12관계43가변열 inventory 대조는 독립 두 리뷰를 통과했다. 실제 SDK3shape positive는 확인했으나 부정·snapshot·메모리 수용은 미완이다. nonname24가 서로 다른 R1인 과거 상태는 처음에는 명시 EX로 거부한다.

기존 synthetic primitive13 부정 사례와 별도 actual SDK 저장3shape 근거를 새 reader의 성공이나 peak memory 증거로 세지 않는다. full SQL/ACL/volatility/NULL/encoded의 독립 두 source 리뷰는 완료했다. 작은 positive 뒤에도 저장 부정·snapshot·memory 시험은 별도 수용이 필요하다. 새 SH wrapper·실제 두 dataset worker·ARM·전국 수집·Geo·child/root seal·운영 전환은 후속 미완이다.

## 실제 SQL source 체크포인트

private metadata 단계는 숫자/bool만 받는 datum 검사와 12관계의 제한된 참조 수집을 수행한다. 전체 예산 후 bulk payload를 같은 STABLE snapshot에서 (tableoid,ctid)로 읽고, 공개 envelope만 반환한다. private 참조는 response/manifest/다음 호출에 내보내지 않는다. name base와 candidate 및 비이름24개 각 revision/clock을 구분하며, 첫 subset의 비이름 base는 단일 R1만 허용한다. Header 전체 fieldset은 core.name만 지원하고 원천값과 operator effective를 혼동하지 않는다.

추가 순수 응답 시험을 포함한 unit32 PASS(0.94초), 변경 Python Ruff/strict mypy2 PASS다. migration role/sidecar/receipt 정적 검사와 graph 재생성은 별도로 확인했다. 이 수치는 SQL 적용/positive/negative/snapshot/memory 수용이 아니다. 첫 정적 검사 명령의 존재하지 않는 sidecar 시험 파일 경로는 시험0으로 안전 종료했고 실제 경로로 재검사했다.

공개 runtime 함수의 canonical ACL/db inventory와 full column inventory 양방향 source 대조는 bfed checkpoint에서 완료했다. 실제 head oracle와 SDK3shape reader positive는 아래 별도 fixture에서 확인했다. 후속 source/test 변경도 독립 두 리뷰 전 PG 실행하지 않는다. source_entity_heads/source_records의 CASE 비교는 전체 history scan이 될 수 있다. LIMIT나 입력2730을 CPU 상한 또는2730 실제 수용으로 주장하지 않으며, unrelated history의 EXPLAIN/CPU/wall/메모리와 실제 positive N을 측정해야 한다. binary256KiB와 25개 base/provenance overhead 때문에 작은 N에서도 전체 EX fallback이 가능하다.

실제 n150 read-only 집계는 Heritage DS28의 source entity4279개, MCST DS41의9494개이며 source_records 추정247898개다(별도 root 감사5e865631…). 이는 historical entity 수이지 최신 active 입력 수가 아니다. 현 reader의 cardinality/실제 byte 예산으로 이들 전체를 수용하거나 운영 동시성이 완성됐다고 주장하지 않는다. 실제 현재 입력 수와 bounded planning chunk→단일 atomic manifest/apply 전체 예산은 후속 설계·실증이다. 임의로 메모리 상한을 올리지 않는다.

## 첫 실제 PG 실패와 최소 배선 수정

bfed checkpoint의 첫 owned PG 실행은 `422_heritage_evidence_reader.py`의 sidecar 실행에서 `cannot insert multiple commands into a prepared statement`로 setup ERROR였다. 함수 생성과 REVOKE가 한 문자열에 묶여 asyncpg 준비문 계약을 위반했고, reader 시험 본문과 head oracle 생성에는 도달하지 않았다. 원 로그/XML/실행 원장을 보존했으며 소유 scalar container 잔여0을 확인했다. 이 결과를 reader PASS로 세지 않는다.

기존 421 배선 방식에 맞춰 shape의 두 CREATE를 각각 별도 파일로 나누고, 모든 REVOKE를 바로 뒤 migration literal로 옮겼다. 여섯 CREATE 본문 bytes와 원래 CREATE→REVOKE 순서는 동일하며 runtime SQL parser를 추가하지 않았다. 공개 함수의 중복 REVOKE도 원래 순서를 보존했다. 최소 수정의 순수·정적48 PASS/기존1 SKIP(1.57초), Ruff/strict mypy1파일 PASS이며, 실제 bootstrap/SDK3shape 재실행은 두 독립 delta 리뷰 뒤 진행하도록 했다. 결과는 아래에 정산했다.

## 실제 초기 positive와 공식 oracle

최소 배선 수정의 두 독립 delta 리뷰 뒤 source `3bfa51bc8d52cf17cd05d49f479bfbc82d9e75af`로 실제 SDK pin53파일을 검증하고 새 owned PG에서 no_coord/coord/coord_geo 세 shape를 함께 확인했다. bootstrap300→422·runtime session/current_user 일치·공개 SD1/private helper5 권한 경계와 reader before/after·nonname24 R1/clock 보존 시험1 PASS(14.70초, skip0)다. 정확 CID 삭제/label0을 별도로 확인했다.

이 scalar fixture는 migration 뒤 정본 runtime reconcile도 실행하므로 그 dump에는 기존 grants 차이가 생긴다. 이를 공식 oracle로 사용하지 않고 원 dump를 보존했다. 별도 bounded fresh fixture에서 기존 `application_300_config`와 정본 dump/비교 함수를 그대로 위임한 공식 oracle1 PASS(14.68초, skip0)를 확인했다. 공식 dump의 변경은 신규 함수6개/ACL6개와 receipt CHECK의422 추가뿐이며 기존 나머지 object block·runtime grant는 byte 동일하다. 두 fixture는 다른 검증이므로 SDK 시험2 PASS나 메모리 수용으로 합산하지 않는다.

공식 dump를 읽는 offline 전체 lint는372 PASS/기존6 SKIP/문서 길이1 FAIL(29.53초)이었다. 초기 reader 링크가 tasks의 기존 본문에 붙어300자를 넘겼기에 우리 링크 한 줄만 제거하고 원 entry를 보존했다. 해당 문서 lint5 PASS(0.10초)로 재확인했으며 전체 lint를 재실행했다고 주장하지 않는다. 실패·수정 원본은 감사 원장에 분리했다. 부정·보안·동일 snapshot·peak/EXPLAIN/지원 N과 실제 SH 수집·운영은 아직 수용하지 않았다.

## 다음 작은 보안·서버 입력 시험 source

공개 SQL 입력의 NULL/차원/중복/형식/2731개와 metadata 배열 예산을 Python validator와 독립해서 검증하는 실제 PG 시험 source를 추가했다. private5 EXECUTE와 private base table SELECT는 runtime42501을 확인하고, 예외 TX 뒤 새 READ ONLY TX의 공개 known-ineligibility 응답을 확인하도록 했다. owner 고권한까지 sandbox한다는 주장은 없다.

이 source 체크포인트에서는 기존 SDK positive1을 포함해18개가 수집됐다(collect-only18, 0.98초). 그 당시 신규17개는 실행 전이었고 source 두 리뷰 전 PG0을 유지했다. 실행 결과는 아래에 별도로 정산했다. Ruff의 초기 raises 범위2건은 실제 한 문장만 예외 검증하고 session 종료로 rollback되도록 수정했다. snapshot·저장 shape/압축·history/peak 시험은 그다음 source/runner gate로 분리한다.

독립 두 리뷰 뒤 source `ca631dc2747afa9e660f5d8979ae8b59028940fc`의 같은 bounded fresh fixture에서 전체18 PASS(14.58초, skip0)를 확인했다. 내역은 기존 SDK3shape1·private 권한6·서버 입력10·배열 metadata 예산1이며, 과거 positive1을 새로운 시험으로 합산하지 않는다. runtime session/current_user·6routine owner/EXEC·resource를 관찰했고 exact CID의 Docker SDK NotFound/label0과 공식 oracle bytes 불변을 확인했다. 저장 shape 부정·snapshot·history/peak·운영 검증은 미완이다.

## Snapshot 다음 시험 source(실행 전)

SDK fixture 생성만 test helper로 추출하고 RR reader→별도 actual batch commit→같은 RR old/fresh RC new를 검증하는 source를 추가했다. 별도 단일 statement는 MATERIALIZED controller barrier의 held 열을 참조하고 실제 pg_blocking_pids에서 정확한 C를 관측한 뒤 B commit/C release/A old를 비교한다. A/B runtime과 C/observer admin은 네 물리 PID가 다른지 확인하며, 기본 pool2를 각각 사용한다. controller 해제와 task 종료에는 명시 timeout을 둔다. 이는 snapshot-before-function 검증이며 metadata/payload 중간 interleave 증거가 아니다.

base24 JSON 배열 순서는 계약이 아니므로 field_path별 map으로 비교하고24개/중복0을 확인한다. 각 entry의 값·R1·revision·clock 전체는 비교하며 제품에 ORDER BY를 추가하지 않는다. 이 source 단계에서 새2case는 PG 실행 전이었고 두 리뷰 뒤에만 실행하도록 했다.

두 snapshot source 리뷰 뒤 source `a2c03cdd93c276b5d1883b75a22534de90b865cd` 전체20 PASS(15.11초, skip0)를 확인했다. 이20개는 기존18개를 포함하며 합산하지 않는다. XML에 RR의 A/B PID와 단일 statement의 A/B/C/observer 네 PID, 정확한 C blocker 관측, B commit-before-release를 기록했다. exact CID 삭제/label0과 공식 oracle 불변도 확인했다. metadata/payload 중간 interleave·peak 증명으로 확장하지 않는다.

## 저장 raw 부정의 다음 source(실행 전)

SDK 기반 bundle에 synthetic extra raw만 추가해 정본 hash/key/link를 새로 계산한 SourceRecord를 legacy EX loader/capture/cutover로 저장하는3case를 추가했다. 작은 extra field는 shape_unsupported, 압축 raw와 압축되지 않은 개별8KiB 초과 raw는 storage_unsupported·전체 items[]를 기대한다. 실제 압축/physical 크기는 별도 observer의 metadata-only SELECT로 확인하도록 했다. 기존 immutable raw UPDATE·trigger 해제·임의 GRANT·normalizer relabel은 없다. 이 raw는 실제 SDK 출력 성공이 아니라 지원 밖 저장 shape의 부정 사례다. 이 source 단계에서 추가3case는 두 리뷰 전 PG 미실행이었다.

저장 raw source의 두 독립 리뷰 뒤 `d3aad3ab3d14486851ce595deb5fffffb52b8961`에서 새3개만3 PASS(14.29초, 기존20 deselected, skip0)를 확인했다. XML metadata는 small370B/압축없음→shape_unsupported,685B/pglz→storage_unsupported,20823B/압축없음→storage_unsupported다. 각각 전체 items[]였으며 exact CID Docker SDK NotFound/label0·공식 oracle 불변을 확인했다. 이전 a2c03의20개와 새로운3개는 중복 없는 별도 fixture 결과이고, 최종 head의 단일23개 실행이라고 부르지 않는다. 별도 공식 oracle1 결과도 합산하지 않는다.

e5 checkpoint 고정 시점에는 precursor의 작은 positive/권한/입력/snapshot/저장 raw 부정 근거를 확보했다. 추가 membership·정책·lineage·retire0 부정 전수, 대형 history의 EXPLAIN·실제 지원 N·peak, 운영 전체 입력/SH worker와 새schema API startup 호환은 후속 gate다. 실제 전체 입력을 수용하는 운영 동시성 해결로 주장하지 않는다.

## 후속 관측: 작은 비용과 schema422 API startup

같은 제품 SQL의 [작은 fixture 비용](2026-10-25-heritage-reader-cost-observation.md)과 정확 e5의 [실제 API startup/READ](2026-10-25-schema422-api-startup-observation.md)를 별도 확인했다. 앞의 후속 gate 중 API startup 호환은 이 범위에서 확인됐지만, 실제 전체 입력·peak·추가 의미 부정·SH worker·운영 활성화는 계속 미완이다. 작은 비용 측정과 새 API 기동을 운영 동시 쓰기 완주로 바꾸어 쓰지 않는다.
