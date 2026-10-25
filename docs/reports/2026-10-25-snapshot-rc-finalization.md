# Snapshot finalization의 RC·fresh capture 미호출 조각

## 소유 범위

Root D source `23797789537745aa7c21bc0ffdfd6e04a96dc831`에서 별도 worktree를 만들었다.
신규 `_430_snapshot_finalization.sql`, 관련 unit·paired integration source, 이 보고서와
client의 두 isolation 설정만 소유한다. 기존 schema/head/ACL/models, shared430 wrapper,
API의 세 번째 SER 설정, Root dispatcher/typed member seal 및 J 등록은 편집하지 않는다.
기존 Python signature/DTO를 바꾸지 않았고 core 모델·ID·provider 변환은 그대로다.
직접 client→repository 경로와 기존 transaction-limit 시험을 대조했다.

이 단계는 미호출430 source다. 단독 migration/PR/활성화를 만들지 않는다. 기존430의
A/B/C, Root의 5인자 dispatcher·private marker·원자 seal wrapper와 권한/설치·RC 경계를
같은 단위로 합성해야 한다. PG·운영 실행은0이다.

## 정확한 변경

현재 정본 head-schema에서 tracking helper, child seal, root finalize, manual purge의
네 정의를 가져와 기존 signature/config와 후속 본문을 보존한다. CREATE OR REPLACE로
정의하며 실제 설치 owner/ACL은 Root wrapper가 담당한다.

- tracking helper의 null mode 검사는 유지하고 finalizing=True이면 P/L을 조회·취득하기
  전에 READ COMMITTED만 허용한다. false leaf 경로의 기존 isolation 의미는 보존한다.
- child seal과 root finalize의 기존 SERIALIZABLE 검사를 READ COMMITTED로 바꾸고 원
  SQLSTATE25001은 유지한다. 두 old current aggregate call site만
  `feature._member_provider_curation_input_set(root,dataset,scope,operation,stage)`로 바꾼다.
  stage는 각각 child/root다. legacy non-place aggregate의 의미는 Root dispatcher가
  member의 artifact 부재에서 보존한다. 이 부재 판정은 mandatory 등록/GC 계약과 함께
  수용해야 하며 현재 fragment만으로 EX 권위를 추정하지 않는다.
- child stage는 postprocessed 및 같은 TX private marker를, root stage는 child_sealed를
  요구하는 Root 계약을 전제로 한다. 이 public seal은 marker를 발급하지 않는다.
  applied만으로 child 완료를 허용하지 않는다. typed wrapper의 token 검증→old seal→
  member done→control sealed 단일 CALL은 별도 Root 소유다.
- purge는 기존 입력 검증 뒤, command/claim/Feature 행을 선점하기 전에 P EX를 명시한다.
  이후의 원 validation/replay/capture/identity 처리와 오류 순서는 유지한다.
- client의 authoritative membership finish 및 SUCCESS reconcile 두 지점만 명시 RC로
  바꾼다. repository의 기존 P EX→L→행 잠금 순서는 보존한다. FAILURE/일반 leaf 분기에
  isolation 문을 추가하지 않는다. API의 _record_terminal_run은 T 소유이며 편집0이다.

## 시험과 원문 보존

신규 unit8과 기존 transaction-limit13을 함께 실행해21 PASS/2.48초였다. 네 SQL 정의는
허용된 prefix/isolation/두 dispatcher 치환만 역변환하면 기존 canonical 정의 전체와
정확히 같아야 한다. client unit은 실제 두 메서드의 branch별 첫 isolation 문을 확인한다.
기존 transaction-limit의 SUCCESS 기대값도 RC로 갱신해 limits가 isolation 다음이라는
주장을 유지했다. 첫 Ruff 형식6개와 후속 integration 형식3개는 원로그로 보존하고 own
파일에서 고쳤다. 최종 Ruff4파일과 client strict mypy1파일 통과다.

paired integration source는5개를 수집했으며 아직 실행하지 않았다. 직접 SER의 helper/
child seal/root finalize가 lock 전에25001로 거부되는3개, SER leaf의 기존 L 유지1개,
실제 P 대기 뒤 root capture가 새 commit을 보는1개다. 마지막 시험은 서비스 LOGIN이
대기 전 old aggregate0을 관측한 뒤 public root finalize를 호출한다. 별도 EX writer를
pg_locks/pg_blocking_pids의 정확한 P key와 PID로 관측하고 entity1 commit 뒤 해제한다.
새 current input과 기존 receipt가 다르므로 o_stale_input=True여야 한다. 서로 다른
holder/waiter/observer 물리PID3개, 유한 SQL/async 대기, rollback/task cleanup을 확인한다.

seed는 고유 owned DB에서 기존 canonical dataset/root helper로 만든 synthetic legacy
EX fixture다. 실제 원천 EOF/공항15, bounded profile의 marker lifecycle 또는 두 SH
worker 동시 성공을 증명하는 시험으로 확대하지 않는다. source는 whole430 설치를
전제로 하며 임의 inline 함수/ACL 설치나 guard 우회는 없다.

## 아직 미완

두 독립 source 검토, 실제 설치/owner ACL·원문 hash·head oracle, paired PG 실행,
기존 finalization 호출자의 전체 RC 합성 회귀 및 CI는 미완이다. historical424의 SER
입력 fixture와 body hash 기대는 새430 의미를 반영해 전체 합성 단계에서 별도 검토해야
한다. strict activation/등록 quota/GC/전체 same-TX apply/SDK0 후속 복구/운영 수용은
이 조각의 성공으로 표시하지 않는다. source와 실행기 두 gate·CPU 승인 전 PG0을 유지한다.
