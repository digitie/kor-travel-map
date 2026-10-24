# field override SQL·상위 caller의 protocol-first 보강(416)

## 범위와 잠금 순서

기준은415 `ae97a92bb971b55e80d7d73d3fa8d0c80a84f3e2`다. SQL author/revoke2개는
정본 signature/prosrc·owner/SD/PLpgSQL을 검사하고 첫 BEGIN에 protocol EX만 삽입한다.
같은 owner라 새 EXECUTE grant는 없다. 원래 본문·config·ACL과 기존 짧은 GUC·CREATE
이전값·receipt/graph/forward-only를 유지한다.

Python admin patch는 `_state_for_conflict`의 첫 Feature FOR UPDATE 전에, manual create는
command FOR UPDATE·공유 exact claim·core/subtype보다 먼저 기존 EX helper를 확보한다.
새 Python 캐시나 추가 재시도는 만들지 않으며 helper의 실제 TX/savepoint/abort 수명 계약을
그대로 쓴다. phone/address는1380에서 이미 조기 gate를 확보했다.

HTTP의 command ledger/isolation/공통 decorator는 바꾸지 않는다. operation별 domain key는
Feature·공유 manual claim보다 먼저일 수 있으며 모든 advisory까지 protocol-first라는
주장은 하지 않는다. SQL-only manual/core create·curation import 역순 정적 후보는 별도
미지원 후속이다. 새 identity·전체 writer·지역·Geo의 공유 쓰기를 지원한 것이 아니다.
curation helper 전체에 새 함수를 넣으면 frozen h35 DB를 깨뜨릴 수 있어 그 경계도 섞지 않았다.

## 실제 오류 회귀와 최소 API 수정

실제 ASGI/PG에서 author/revoke/patch는55P03이 전역 handler의 LOCK_TIMEOUT503/
Retry-After5로 전달됐으나 manualcreate는 기존 광범위 DBAPIError catch가 이를500으로
감췄다. 첫 확장20 PASS/1 FAIL(22.59초)의 실제500 원문을 보존했다. 승인된 추가 범위는
create route의 **정확 DBAPIError.orig.sqlstate55P03만 re-raise하는2줄**이다. 다른 DB 오류,
validation/invariant의 기존 비식별500·권한·DTO·전역 handler·timeout은 바꾸지 않았다.

최종4경로 모두503 뒤 caller TX/claim이 rollback되고 같은 Idempotency-Key로 정상 재시도·
terminal replay가 가능하다. 실제 owned PG가23514/40001/XX000을 내는3개 추가 회귀에서는
기존500/비식별 응답·terminal 미발행·같은 key 재호출 성공을 확인했다. HTTP200이나 unit fake로
실제 lock timeout을 대체하지 않았다. ASGI는 실제 TCP/browser 수용과 별도다.

## 검증 결과와 한계

- 최종 **실제 PG/ASGI29 + 순수5 = 34 passed(26.85초)**. bounded owned PostGIS를 fresh
  full bootstrap하고 정본 runtime ACL reconcile 뒤 실제 runtime으로 실행했다.
- native begin/finish의 SH/source/head/Feature에 대해 exact2int key `(1369104691,115)`/
  ExclusiveLock/blocker PID 대기를 확인했다. 동일/독립 Feature 경합과 독립 행 NOWAIT를
  검증했다. manualcreate는 MVCC count0만 보지 않고 같은 unique manual claim을 실제로
  INSERT/rollback하여 대기 중 미커밋 선점이 없음을 확인했다.
- valid author/revoke/patch/manualcreate, SH 승격23514·caller rollback·새 TX 재호출,
  원문 SHA/owner/config/기존 EXECUTE·PUBLIC 폐쇄·비인가 owner42501을 검증했다.
- active name/phones의 operator override를 쓴 뒤 실제 scoped SQL source/head→후보/winner
  재투영에도
  effective 값이 유지되고, revoke 뒤 최신 provider base 값·record/hash lineage로 복원된다.
  category/address 등 미지원 path는 기존23514와 값·override·감사의 전체 rollback을 유지한다.
  이 사례의 `_refresh`는 실제 PG에서 source/head SQL·kernel/capture/recompute를 직접 실행한다.
  production `refresh_scoped_provider_scalars` Python helper·일반 collector 배선 호출은 포함하지
  않으며 그 별도 native 테스트 증거와 합산하지 않는다.
- oracle 기록은 **1 skipped(13.77초)**이며 비교 성공으로 세지 않는다. 별도 정본 head oracle
  비교·fresh300 metadata는 **2 passed(27.68초)**다. head oracle diff는 SQL2개 첫EX와
  receipt의416 추가뿐이며 수동 편집하지 않았다.
- 전체 정적 규약 **373 passed/기존6 skipped(31.82초)**. 변경 Ruff·strict mypy3 source·
  import-linter4계약 PASS, 공유 venv/index 변경0이다.
- 관련 기존 repo/router unit은 **110 passed(29.30초)**다. payload/receipt fake는
  새 gate SQL을 미리 준비한 결과로 소비하지 않도록 해당 unit 모듈에만 명시 seam을 넣었다.
  원래 business assert를 바꾸지 않았고 실제 잠금/SQL 수용은 전용 PG29가 담당한다.
- 실제 container2CPU·memory=swap1536MiB·PID256을 inspect했다. 최종 정확 ID의 SDK NotFound와
  같은 UUID label 잔존0, oracle fixture의 정확 ID 제거를 확인했다. 원천 HTTP/운영 DB·배포0이다.

## 원본 실패와 후속 gate

초기 bootstrap은 신규 oracle 추출이 prosrc 마지막 개행을 제외한 해시를 고정해 fail-closed
중단됐다(순수5 PASS/14 setup ERROR). 마지막 개행을 포함한 정본415 방식으로 해시를 고쳤고
검사를 완화하지 않았다. 다음16 PASS/3 FAIL은 manualcreate fixture의 필수 marker 필드
누락이며 canonical payload를 보완했다. 이 오류들과 실제 manual500 제품 회귀는 구분한다.

관련 기존 unit은 fake queue가 새 gate SQL을 소비해13 FAIL/97 PASS였다. 명시 fake seam 뒤
110 PASS가 됐으나 같은 명령의 별도 CALL 정적 검사1개가 실패했다. 이는 literal JSON의 쉼표를
정적 parser가 추가 CALL 인자로 센 경계이며 실제 PG CALL은 정상10개였다. JSON을 bind하여
검사 약화 없이 고쳤고 전체 lint373 PASS를 다시 확인했다. 전용34 PASS의 최종26.85초는
binding 보완 뒤 실행이며 앞선24.64초/중간29 PASS와 합산하지 않는다.

원본·중간·최종 로그/cleanup 증거는 감사 보관소 `map416-*`에 별도 보존한다. 설계2리뷰 PASS는
코드2리뷰 완료가 아니다. 정확 CI·독립2코드리뷰·최신 부모 합집합·실제 TCP/UI는 미완 gate다.
기본OFF·seed0·운영0이며 mixed binary/drain 확인 전 설치·활성화하지 않는다. 기존1379 reader/
kernel UI 수용을 이 새 mutation의 UI 수용으로 세지 않는다. 전체 T-CWRITE는 미완이다.
