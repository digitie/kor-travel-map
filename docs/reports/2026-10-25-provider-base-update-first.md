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
