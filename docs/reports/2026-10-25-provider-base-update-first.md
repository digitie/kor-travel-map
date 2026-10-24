# Provider base UPDATE-first 후보(425)

기존 provider materializer의 scalar·geometry 두 루프만 기존 행 UPDATE를 먼저 시도한다.
기존 행은 값이 같아도 provider lineage·base_revision·observed_at·updated_at을 갱신한다.
UPDATE가 행을 찾지 못하면 기존 INSERT ON CONFLICT 문장을 그대로 실행한다.
winner projector와 validator·권한·Feature/source 잠금·notice 최초 시작시각·subtype 반영은 바꾸지 않는다.

새 migration은 기존 procedure의 본문 SHA·인자·owner·SECURITY DEFINER·search_path를 대조한다.
기존 effective CREATE 권한이 없을 때만 정본 임시 GRANT/REVOKE window를 쓰며,
짧은 caller GUC를 유지한다. 현재423 위의 후보425이며424가 먼저 합쳐지면 선형 순서를 조정한다.
직접 public SD의 P-prefix 보강은 별도 작업으로 남긴다.

## 수정 전 영향과 현재 검증

새 migration/sidecar이며 public 시그니처는 같다. codegraph-worktree §7의 신규 파일 예외를 적용했다.
기존 base UPSERT 정적 조사와 실제 context 관측은 원인 후보 근거일 뿐 trigger별 비용 귀속이 아니다.
원 두 UPSERT를 그대로 둔 fallback과 새 UPDATE만 역치환하면 기존 procedure 전체 원문이 일치한다.
현재 head-schema는 부모423이며425 공식 oracle은 아직 생성하지 않았다.

migration CREATE·drift·짧은 GUC 단위5 PASS(0.29초), Ruff2파일/mypy1파일을 확인했다.
첫 정적 합집합은 새 unit의 baseline dump 직접 참조 때문에1 FAIL/377 PASS/기존6 skip이었다.
원 로그를 보존하고 fake catalog fixture로 격리해 baseline을 현행 계약으로 쓰지 않도록 고쳤다.
수정 뒤 같은 정적·단위 합집합은378 PASS/기존6 skip(29.76초)다. 앞5개와 중복 합산하지 않는다.
실제 PG·API·비용·전체 CI는 아직 실행하지 않았다. 두 독립 소스 리뷰 뒤
기존/부재·값동일·geometry/null·notice·모든 kind·override 보존·revision/clock·잘못된 source/registry
오류순서·owner concurrent insert fallback·전체 rollback을 검증한다.
현재 Feature lock은 정본 caller를 직렬화하지만 고권한 raw writer의 부재 증명이 아니므로
atomic UPSERT fallback을 제거하지 않는다. source/값 검증이나 deferred guard를 끄지 않는다.

성능 개선이나 SH collector 완료, 운영 활성화는 주장하지 않는다.

## 실제 시험 source 계획(미실행)

전용 owned scalar fixture에서 synthetic SourceRecord/hash/key·실제 source/link·5kind를 심는다.
외부 SDK 실행이나 collector 경로를 검증한 것으로 세지 않는다. 새15개는5kind의 부재 fallback 뒤
동일값 UPDATE·lineage/revision/clock/geometry,5개 오류 전체 rollback, 허용 null, notice first-probe,
operator override 보존, exact owner-first blocker PID와 commit 후 갱신, 실제 catalog/body/ACL이다.
updated_at >= observed_at는 existing UPDATE에만 검사하고, absent INSERT는 원 DEFAULT now()를 보존한다.

경합 시험은 고권한 owner가 먼저 base를 넣어 FK KEY SHARE를 보유하고 provider Feature UPDATE가
그 exact PID에 막힘을 확인한다. owner commit 뒤 existing UPDATE가 실행되며 이를 동시 fallback
성공이라고 부르지 않는다. 늦은 raw owner INSERT의 FK/unique cycle은 옛 UPSERT에도 가능하다.
부재 fallback 실행과 원 UPSERT byte 보존은 증명하되 권한·constraint 우회로 경합을 만들지 않는다.

추가로 기존 명시 EX full-refresh20 회귀를 현재425 bootstrap에서 그대로 실행해 active policy,
epoch 및 deferred projection·부재/기존 base를 대조한다. 새15개와 기존20개의 실제 실행 결과는
두 독립 시험 source 리뷰와 별도 CPU 승인 뒤 기록한다. 원 clock/정책·guard를 끄지 않는다.

허용 geometry null은 SQL NULL과 JSON null을 SQL boolean 두 개로 구분한다.
잘못된 source record와 등록되지 않은 field를 함께 주고 source provenance 오류가 먼저 나며
전체 상태가 rollback되는 반례를 추가했다. 실제 실행은 아직0이다.
