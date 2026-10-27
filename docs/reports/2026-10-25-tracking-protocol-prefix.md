# Tracking P→L 진입 순서 고정(424, prefix 단계)

> **정오표(2026-10-27).**
> - 머리말의 "기존 SERIALIZABLE 요구 … 보존한다"와 source144 절의 "이 단계는 기존 SER를
>   유지하며"는 424 시점 서술이다. 430부터 provider finalization·snapshot seal·curation root는
>   SERIALIZABLE이 아니라 **READ COMMITTED**를 요구하고(`_430_snapshot_finalization.sql`),
>   P EX → L과 legacy fence 아래에서 입력을 읽는다. 현재 격리·경합 의미의 정본은 ADR-112다.
> - 마지막 절의 "(미실행)"은 작성 시점 상태다. 그 절의 시험 seed·task 정리 보강은 PR #1401 head
>   `76d2daf6e`에 들어갔고, 정확 CI 10개(Python 3.11/3.12/3.13·fixture replay·PostGIS
>   alpine/glibc·lint·OpenAPI·frontend·production image)가 모두 통과한 뒤 2026-10-25에 병합됐다.
> - 이 prefix는 취소 생성·queued 취소·fill-starts·FAILURE/CANCELED 종결·비권위 finish 같은 장부
>   작업도 P EX를 먼저 잡게 만들었다. 큐레이션 데이터를 확정하는 작업만 P EX → L을 잡도록 줄이는
>   변경은 2026-10-27 Codex PR 통합 리뷰 PR(WI-1)에 있다.

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
계속 거부한다. 당시 실제 API startup/catalog 검증은 별도 PG 수용 대상으로 남겼다.

## 단계별 검증과 남은 범위

실제 prefix 대기·L 미선점·입력 거부·role/ACL·GUC는 아래 source728의 직접25에서,
정본 oracle와 정상 tracking은 별도 실행에서 확인했다. 일반 queued 취소의 ASGI
503 후 새 요청 재개와 triple 추가 회귀는 source144에서 아래와 같이 확인했다.
provider SUCCESS 취소의 실제 API 분기와 Uvicorn process 기동은 아직 미검증이다.

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
assert를 바꾸지 않았다. oracle 채택 후 source lint+graph는391 PASS/기존6skip(32.36초)으로
초기 oracle미존재1실패를 닫았다. source728 이후 oracle/시험·문서 변경을
source728의 실제 실행으로 혼합하지 않는다.

## source144의 ASGI 취소와 triple 격리 회귀

- 실제 서비스 catalog preflight를 호출한 ASGI 취소1 PASS20.445초. P SH 경합에서
  503/Retry-After5 뒤 새 요청200과 같은 결과 재요청200을 확인했다. 실패 뒤 취소
  시도0, 복구·재요청 뒤1개이며 현재/이전 backend 잠금0·pool 반환0·외부HTTP0이었다.
  일반 queued job 경로이며 provider SUCCESS 취소나 Uvicorn 기동 증거는 아니다.
- 기존 client4와 triple7을 같은 module DB로 묶은 통합11은9 PASS/2 FAIL이었다
  (XML22.416초/콘솔23.14초). 앞 exclusive asset의 영속 cutover 정책이 뒤 triple
  catalog raw UPDATE/INSERT를 정상23514로 거부한 private fixture 격리 오류다.
  원실패·로그·XML과 정리 증거를 보존했다. 이 실행을 전체 PASS로 바꾸지 않는다.
- 새 fresh DB에서 기존 triple 함수 본문과 canonical session fixture를 유지한
  별도7 PASS20.062초. 기존 ensure→finish 두 시험의 실제 typed prefix도 통과했다.
  앞 통합 실행의 client4 부분 PASS와 source728의 별도4를 구분하며9+7을16 PASS로
  합산하거나 하나의11 PASS로 정산하지 않는다. guard·공통 fixture·제품 변경은 없다.
- source144의 두 실행과 원실패 실행은 source2384·SDK53 전후 및 실제 import13 Git
  SHA를 기록했다. 성공한 ASGI/별도7은 각 artifact SHA를 재계산했으며 세 실행 모두
  exact CID/UUID/global label0·anonymous volume1 부재를 확인했다.

정확 CI·최종 부모 합성과 실제 운영 수용은 별도다. 이 단계는 기존 SER를 유지하며
SER snapshot-before-wait·whole capture 폐포·전체 retire/seal 한 commit·자동복구·
대형 protocol·SH collector 활성화가 완료됐다는 주장을 하지 않는다.
## exact ab696 CI의 직접 seed 계약과 task 정리 보강(미실행)

최초 exact ab696 CI의 PostGIS glibc lane은28 FAIL/1659 PASS/23 SKIP/1 ERROR
(839.09초), alpine lane은28 FAIL/1653 PASS/29 SKIP/1 ERROR(970.64초)였다.
양 lane의 실패28 node 집합은 정확히 같았다. Python3개·fixture replay와 다른4workflow의
SUCCESS를 CI 전체 통과로 표시하지 않는다. 원로그 둘을 보존하며 이를 재시도나 부분
PASS로 대체하지 않는다. 실패28개 중26개는
전용 시험 seed가 같은 transaction에서 leaf ensure 뒤 finish/reconcile/cancel을 호출해
P→L 순서를 위반했다. 실제 client의 ensure와 finish/reconcile는 각각 새 transaction이며,
repository final과 취소 public entry는 이미 첫 행 선점 전에 typed P→L을 취득한다.
이번 관측 경로에서 확정된 production caller 누락은 없고, 그 밖의 경로 전체가
안전하다는 증명으로 확대하지 않는다.

나머지2개는 batch 경합 시험이 L만 먼저 선점하고 public 취소 entry를 호출해23514를
받았다. 실패 뒤 phase task를 회수하지 않아 fixture의 DELETE와 행 잠금이 경합한
teardown deadlock1도 보존한다. 이 시험의 명시적 barrier만 typed final prefix로 맞추고,
생성한 task를 finally에서 cancel/await해 fixture 정리 전에 반환한다.

5개 시험 module의 알려진 terminal seed에만 실제 executor 역할의 typed prefix를
추가했다. 공통 fixture·leaf 구현·제품·SQL·SER/SH 거부·timeout·기존 assert는 바꾸지
않았다. 추가 setup/cleanup만 제거하면 기존 각 함수 AST와 assert 순서가 같음을
확인한다. 소스 두 리뷰와 별도 실제 PG gate 전에는 이 수정본의 통과를 주장하지 않는다.
