# Heritage bounded evidence reader — 초기 구현

첫 checkpoint는 입력 계약만 구현했다. 다음 checkpoint는 422 migration/정적 SQL reader·private metadata/shape 검사와 Python 응답 검증을 추가한 source 초안이다. 첫 실제 PG 설치 시도는 migration 배선에서 setup ERROR였으며 reader 본문 성공은 없다. 실제 SH collector에 연결하지 않았다. 기존 공개 client/SQL/수집 동작·기본 EX·정책과 운영 설정은 바꾸지 않았다.

## 현재 확인

- source7e에서 별도 worktree/branch로 시작했다. 입력 dataset은 양의 PG bigint, entity key는 exact se_+64hex다.
- iterable은 MAX+1까지만 소비한다. 1..2730 입력과 중복 거부, 보수적 배열 전송 예산을 확인한다. 결과 완결성은 SDK/A1 적격성 또는 apply 권한과 구분한다.
- 순수 단위16 PASS(1.43초), 변경 Python Ruff PASS, strict mypy1파일 PASS, redaction/diffcheck PASS. 첫 Ruff의 StrEnum/raises match 지적3건은 해당 새 파일 안에서 고쳤다. 이 결과는 DB/메모리/새 reader 성공이 아니다.
- 설계r3는 독립 두 리뷰를 받았다. 무근거 N32 제한·요청 외 전체 dataset 필터·datum header 크기 혼동·metadata 이전 문자열 비교 지적을 수정했다.

## 다음 구현과 미완

422의 source에는 STABLE pure-read SD/static SQL/search_path pg_catalog와 typed infra wrapper를 추가했다. private table SELECT를 runtime에 열지 않는다. metadata 이후 payload의 내부 위치는 같은 snapshot의 tableoid/ctid 쌍으로만 사용하고 외부 identity로 내보내지 않는다.

입력 배열 자체 검사, 모든 가변 열 inventory·양측 text JOIN의 metadata CASE, SQLNULL/JSONnull 구분, 전체 binary256KiB·encoded1MiB와 row 상한, 저장 normalizer/core.name header·R1/R2·base24/field별 clock, claim·primary-only 전체 membership·lifecycle/stamp/epoch·dataset retire0 검사의 source 초안을 작성했고 bfed checkpoint의 full source/12관계43가변열 inventory 대조는 독립 두 리뷰를 통과했다. 실제 PG reader 실증은 아직 없다. nonname24가 서로 다른 R1인 과거 상태는 처음에는 명시 EX로 거부한다.

기존 synthetic primitive13 부정 사례와 별도 actual SDK 저장3shape 근거를 새 reader의 성공이나 peak memory 증거로 세지 않는다. full SQL/ACL/volatility/NULL/encoded의 독립 두 source 리뷰는 완료했다. 격리 PG positive·부정·snapshot·memory 시험은 별도 수용이 필요하다. 새 SH wrapper·실제 두 dataset worker·ARM·전국 수집·Geo·child/root seal·운영 전환은 후속 미완이다.

## 실제 SQL source 체크포인트

private metadata 단계는 숫자/bool만 받는 datum 검사와 12관계의 제한된 참조 수집을 수행한다. 전체 예산 후 bulk payload를 같은 STABLE snapshot에서 (tableoid,ctid)로 읽고, 공개 envelope만 반환한다. private 참조는 response/manifest/다음 호출에 내보내지 않는다. name base와 candidate 및 비이름24개 각 revision/clock을 구분하며, 첫 subset의 비이름 base는 단일 R1만 허용한다. Header 전체 fieldset은 core.name만 지원하고 원천값과 operator effective를 혼동하지 않는다.

추가 순수 응답 시험을 포함한 unit32 PASS(0.94초), 변경 Python Ruff/strict mypy2 PASS다. migration role/sidecar/receipt 정적 검사와 graph 재생성은 별도로 확인했다. 이 수치는 SQL 적용/positive/negative/snapshot/memory 수용이 아니다. 첫 정적 검사 명령의 존재하지 않는 sidecar 시험 파일 경로는 시험0으로 안전 종료했고 실제 경로로 재검사했다.

공개 runtime 함수의 canonical ACL/db inventory와 full column inventory 양방향 source 대조는 bfed checkpoint에서 완료했다. 실제 head oracle와 PG reader 시험은 후속 gate다. 첫 PG 실패의 최소 배선 수정도 독립 두 리뷰 전 재실행하지 않는다. source_entity_heads/source_records의 CASE 비교는 전체 history scan이 될 수 있다. LIMIT나 입력2730을 CPU 상한 또는2730 실제 수용으로 주장하지 않으며, unrelated history의 EXPLAIN/CPU/wall/메모리와 실제 positive N을 측정해야 한다. binary256KiB와 25개 base/provenance overhead 때문에 작은 N에서도 전체 EX fallback이 가능하다.

실제 n150 read-only 집계는 Heritage DS28의 source entity4279개, MCST DS41의9494개이며 source_records 추정247898개다(별도 root 감사5e865631…). 이는 historical entity 수이지 최신 active 입력 수가 아니다. 현 reader의 cardinality/실제 byte 예산으로 이들 전체를 수용하거나 운영 동시성이 완성됐다고 주장하지 않는다. 실제 현재 입력 수와 bounded planning chunk→단일 atomic manifest/apply 전체 예산은 후속 설계·실증이다. 임의로 메모리 상한을 올리지 않는다.

## 첫 실제 PG 실패와 최소 배선 수정

bfed checkpoint의 첫 owned PG 실행은 `422_heritage_evidence_reader.py`의 sidecar 실행에서 `cannot insert multiple commands into a prepared statement`로 setup ERROR였다. 함수 생성과 REVOKE가 한 문자열에 묶여 asyncpg 준비문 계약을 위반했고, reader 시험 본문과 head oracle 생성에는 도달하지 않았다. 원 로그/XML/실행 원장을 보존했으며 소유 scalar container 잔여0을 확인했다. 이 결과를 reader PASS로 세지 않는다.

기존 421 배선 방식에 맞춰 shape의 두 CREATE를 각각 별도 파일로 나누고, 모든 REVOKE를 바로 뒤 migration literal로 옮겼다. 여섯 CREATE 본문 bytes와 원래 CREATE→REVOKE 순서는 동일하며 runtime SQL parser를 추가하지 않았다. 공개 함수의 중복 REVOKE도 원래 순서를 보존했다. 최소 수정의 순수·정적48 PASS/기존1 SKIP(1.57초), Ruff/strict mypy1파일 PASS이며, 실제 bootstrap/SDK3shape 재실행은 두 독립 delta 리뷰 뒤 진행한다.
