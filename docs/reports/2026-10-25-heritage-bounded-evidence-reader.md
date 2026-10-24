# Heritage bounded evidence reader — 초기 구현

첫 checkpoint는 읽기 요청의 정본 key/중복/형식/입력 예산과 닫힌 부적격 사유만 구현했다. 새 DB reader/SD/migration422/실제 SH collector는 아직 없다. 기존 공개 client/SQL/수집 동작·기본 EX·정책과 운영 설정은 바꾸지 않았다.

## 현재 확인

- source7e에서 별도 worktree/branch로 시작했다. 입력 dataset은 양의 PG bigint, entity key는 exact se_+64hex다.
- iterable은 MAX+1까지만 소비한다. 1..2730 입력과 중복 거부, 보수적 배열 전송 예산을 확인한다. 결과 완결성은 SDK/A1 적격성 또는 apply 권한과 구분한다.
- 순수 단위16 PASS(1.43초), 변경 Python Ruff PASS, strict mypy1파일 PASS, redaction/diffcheck PASS. 첫 Ruff의 StrEnum/raises match 지적3건은 해당 새 파일 안에서 고쳤다. 이 결과는 DB/메모리/새 reader 성공이 아니다.
- 설계r3는 독립 두 리뷰를 받았다. 무근거 N32 제한·요청 외 전체 dataset 필터·datum header 크기 혼동·metadata 이전 문자열 비교 지적을 수정했다.

## 다음 구현과 미완

422는 STABLE pure-read SD/static SQL/search_path pg_catalog와 typed infra wrapper를 추가할 예정이다. private table SELECT를 runtime에 열지 않는다. metadata 이후 payload의 내부 위치는 같은 snapshot의 tableoid/ctid 쌍으로만 사용하고 외부 identity로 내보내지 않는다.

입력 배열 자체 검사, 모든 가변 열 inventory·양측 text JOIN의 metadata CASE, SQLNULL/JSONnull 구분, 전체 binary256KiB·encoded1MiB와 row 상한, 저장 normalizer/core.name header·R1/R2·base24/field별 clock, claim·primary-only 전체 membership·lifecycle/stamp/epoch·dataset retire0 검사가 아직 구현/실증되지 않았다. nonname24가 서로 다른 R1인 과거 상태는 처음에는 명시 EX로 거부한다.

기존 synthetic primitive13 부정 사례와 별도 actual SDK 저장3shape 근거를 새 reader의 성공이나 peak memory 증거로 세지 않는다. full SQL/ACL/volatility/NULL/encoded 검토 두 명과 격리 PG positive·부정·snapshot·memory 시험이 선행돼야 한다. 새 SH wrapper·실제 두 dataset worker·ARM·전국 수집·Geo·child/root seal·운영 전환은 후속 미완이다.
