# Tracking P→L 진입 순서 고정(424, 부분 체크포인트)

종결·취소 경로가 lineage L 또는 행을 선점한 뒤 데이터 protocol P EX를
늦게 요청하는 순서를 앞당긴다. 기존 SERIALIZABLE 요구, capture/hash,
parent/kernel 잠금과 수집 flag 기본 OFF는 보존한다. RC 전환이나 전체
snapshot 동시 쓰기 완성으로 세지 않는다.

## 구현 범위

- 새 `ops.lock_provider_feature_tracking_protocol(boolean)` SD는 정확한 현재
  backend/database/key/subid/mode를 관측한다. final 진입은 L-only 선점을
  23514로 거부한 뒤 P EX→xact L 순서로 취득한다.
- leaf ensure/append는 P가 없으면 L만 취득한다. P가 이미 있으면 P EX와 L을
  모두 보유한 재진입만 허용하며 SH-only/EX-only에서 새 L을 요청하지 않는다.
- seal/root/finish/terminal/cancellation SD 6개와 leaf SD 2개의 첫 BEGIN에
  prefix를 추가한다. 부모 본문 SHA·signature·owner/type/config를 검증하고
  교체 후 OID/ACL/default/속성을 대조한다. 기존 본문·검증 순서는 보존한다.
- Python tracking/cancellation의 첫 행 조회 전에 같은 typed entry를 호출한다.
  API SUCCESS는 기존 격리 설정 뒤 prefix를 거친다. 공통 L helper는 바꾸지 않는다.
- helper owner는 기존 curation command owner, search_path는 pg_catalog이며
  PUBLIC EXEC를 회수하고 기존 runtime에 EXEC만 추가한다. 임시 schema CREATE는
  원래 없던 경우에만 부여하고 회수한다. raw table 권한은 추가하지 않는다.

## 초기 source checkpoint 검증(oracle 채택 전)

부모는 `a8cb6e567f879de41c4d5a404770f11dc847c308`이다. 기존 정상 Linux
Codegraph index를 재사용한 실제 caller/callee/impact 조회를 소스 추적의 보조
근거로 썼다. 고정 index는 SQL SD/trigger를 해석하지 않으며 이름 alias의
가짜 edge가 있어 Python/SQL 본문을 따로 읽었다. 원 index 재생성·수정은 없다.

- 집중 순수 시험 72 PASS/1.21초(신규 prefix 8개 포함).
- 초기 1 FAIL/71 PASS는 quarantined fixture의 SQL 3개 고정 기대값이었다.
  새 prefix를 첫 SQL로 단언하고 기존 ensure/quarantine 검증을 유지한 뒤 통과했다.
  실패 로그 `/tmp/map424-unit-r1.log`와 후속 로그는 별도 보존한다.
- API 취소 기존 순수 시험은 별도20 PASS/1.33초였다.
- 신규 integration25개는 수집만 통과했으며 실제 DB 결과로 세지 않는다.
- 변경 Python 6파일 strict mypy 및 Ruff 통과.
- source lint+graph는390 PASS/6기존 skip/1 FAIL(29.06초)이었다. 실패는 새 helper의
  공식 head-schema 미생성으로 ACL 이름이 부모 oracle에 없다는 검사이며, 생략하거나
  기대값을 완화하지 않는다. 실제 bootstrap/oracle 후 다시 확인해야 한다.
- 실제 PostgreSQL bootstrap/경합/role·ACL 및 공식 head oracle 재생성은 아직
  실행하지 않았다. 당시 head-schema는 부모423 원문이었으며 최종 수용 증거로 세지 않았다.
- 원격 운영·HTTP·UI 실행0, 공유 venv 변경0. CI와 독립 소스 리뷰도 아직 미완이다.

## Startup 허용 목록 P1 정정

독립 리뷰에서 새 helper의 runtime EXEC와 기동 preflight SD 목록이 어긋난
문제를 찾았다. 최초 체크포인트는 정상 catalog도 unexpected SD로 거부한다.
정확한 boolean signature 1개를 서비스 allowlist에 추가했고 검사 함수는 바꾸지 않았다.
수정 전 literal catalog fixture 1 FAIL을 보존했으며, 수정 후 DB/prefix 순수31
PASS(1.59초)·mypy1/Ruff를 확인했다. 같은 시험에서 권한 누락과 text overload는
계속 거부한다. 실제 API startup/catalog 검증은 여전히 별도 PG 수용 대상이다.

## 다음 검증과 미완

실제 두 backend에서 P가 먼저 대기하고 L/root/member는 아직 선점하지 않은지,
L-only final 및 P SH/EX-only leaf가 즉시23514인지, timeout/rollback/role GUC,
기존 SER와 capture 결과·owner/ACL·임시 CREATE 회수가 유지되는지 검증해야 한다.
공식 fresh oracle는 아래 별도 세대로 수용했다. 기존 tracking/cancellation 추가 회귀는 다음 source에서 수행해야 한다.

관측된 session/xact advisory lock만으로 과거 전체 취득 순서를 증명하지 않는다.
first-party fresh transaction 계약과 DB가 검사하는 prefix subset을 구분한다.
SER snapshot-before-wait, 전체 capture의 payload/phantom 폐포, 전체 retire/seal 한 commit,
저장 result 기반 자동복구와 대형 streaming protocol은 여전히 미완이다.
`apply_provider_feature_field_patch`와 materializer 최적화는 이번 범위 밖이다.

## source728 실제 수용과 oracle 채택

서로 다른 고유 fresh PG 실행을 합산하지 않고 각각 기록한다.

- 직접 prefix/catalog25 PASS20.590초: bare P/typed NULL negative·실제 blocker와 L
  미선점 관측이며 전체 collector나 API 재개 성공이 아니다.
- 공식 fresh300 oracle1 PASS26.436초: runtime reconcile 없이 정본 생성과 재덤프 비교를
  통과했다. 부모423의1640→1642 object 중1631개와 기존 ACL404개가 전체 bytes 동일하다.
  변경8루틴은 prefix1줄 역변환 시 부모와 같고 receipt는424항목만 추가했다.
  새 helper·ACL2개만 추가되며 새 덤프 SHA는
  `866abaf3a87fa5af9f21d3261c18a7d4ecadca6f9de49905be433026c9d35429`다.
- 기존 real client/Heritage asset4 PASS17.213초: HTTP 원천과 Geo 고정 대역·실제
  converter/loader/tracking을 유지했다. 정상2는 별도 SER child seal과 completion
  sweep root done, 나머지2는 기존 drift/rollback 경계를 검증한다. 실제 daemon은 아니다.
- 세 실행 모두 실제 service 역할, source2384·SDK53 전후, 실제 import9/9/13 Git SHA,
  exact CID/UUID/global label0·각 anonymous volume1 부재를 확인했다. 원장과 실패 세대는
  별도로 보존한다. 운영 HTTP/UI 변경0이다.

같은 seed TX에 ensure→finish를 넣는 기존 identity-triple 시험2개는 첫 행 조회 전에
실제 runtime의 typed finalprefix를 취득하도록 보강한다. 공통 fixture와 기존 실패/성공
assert를 바꾸지 않으며 아직 새 source에서 실제 재실행하지 않았다. oracle 채택 후 source lint+graph는391 PASS/기존6skip(32.36초)으로 초기
oracle미존재1실패를 닫았다. API startup 실제 preflight·503 후 새 요청 재개와
정확 CI는 아직 미완이다. source728 이후 oracle/시험·문서
변경을 source728의 실제 실행으로 혼합하지 않는다.
