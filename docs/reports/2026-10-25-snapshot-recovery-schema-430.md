# Airport 영속 snapshot의 430 스키마 배선 체크포인트

## 현재 범위

검토된 A/B/C, 등록 b0eb, RC finalization 34c, reset 8d4와 Root backend/GC 26c2e5f를 하나의 forward migration에 연결했다. 이 보고서는 **소스 배선 체크포인트**다. 실제 PostgreSQL parse·설치·권한·ORM reflection·공식 golden430 및 caller 전체 수용은 아직 수행하지 않았다. 기존 head-schema.sql은 실제로 수용된 429 그대로 두었다. 운영 설치, quota 설정 적용, RC·SH collector 활성화는 실행하지 않았다.

430 migration은 고정 sidecar의 CREATE 경계와 명시 signature/owner 목록만 사용한다. 원 SQL 본문을 재작성하지 않고 owner별 문장으로 나누며 전체 bytes 재결합을 검증한다. 기존 routine의 owner도 429 oracle과 대조한다. 실행하는 실제 문장 tuple에 receipt CHECK가 포함된다. P EX를 먼저 얻고 lock/statement timeout을 기존 값과 1s/30s 중 작은 값으로 제한한다. SchemaOwner가 관측한 StateOwner/CommandOwner의 기존 schema CREATE 권한은 유지하고 새로 준 권한만 회수한다.

## 권한과 재시작 검사

immutable artifact·control·quota limit·reservation 네 표는 일반 runtime/PUBLIC raw 권한이 없다. 등록/claim/read/plan/apply/reset/postprocess/GC는 CommandOwner의 typed 명령이다. 공개 typed 함수 11개와 member seal procedure만 provider executor에 부여한다. receipt validator와 executor lock helper는 직접 runtime EXEC가 없다. canonical bounded capture와 kernel 명령의 dependent EXEC도 실제 소유자 창에서 부여한다.

CommandOwner는 private 표에 필요한 SELECT/INSERT/UPDATE/DELETE만 받는다. immutable artifact UPDATE는 받지 않는다. reset attempt FOR UPDATE에는 UPDATE(attempt_id), 후처리 sync cursor FOR UPDATE에는 실제 `provider_sync.provider_sync_state`의 UPDATE(provider_dataset_id)를 추가한다. integrity scope/run SELECT·UPDATE와 finding observations SELECT를 명시한다. GC는 terminal 입력 삭제와 quota 반환에 필요한 private DELETE만 사용한다. baseline300~429에는 새 표·루틴이 없으면 기존 optional 규약으로 건너뛰며 head430에서는 누락을 오류로 다룬다.

새 `feature._assert_strict_sh_data_guard_inventory(boolean DEFAULT true)`는 SchemaOwner의 STABLE 검증 함수다. 429 installer의 25관계/8 shared target, 총33개 trigger 검증 tail을 그대로 재사용하고 설치/DDL/행잠금은 수행하지 않는다. 함수·행/문장 유형·enabled·args·조건·열 목록과 전체 관계 집합을 대조한다. 실제 apply의 기본 true는 언제나 exact33을 요구한다. startup의 false는 active policy가 없고 strict trigger도0일 때만 정의만 있는 상태를 허용한다. 나머지는33개 전부를 검증하며 partial/disabled/drift는 실패한다. NULL mode도 거부한다.

이 검증 함수의 EXEC는 CommandOwner와 startup service만 갖는다. service에 active-policy 표 SELECT를 새로 열지 않는다. 시작 검사는 정확 head 확인 후에만 이 함수를 호출하며, private snapshot 표에 table/column 단위 권한이 새면 거부한다. 기존 allowlist를 넓은 wildcard로 바꾸지 않고 새 signature를 정확히 추가했다.

## 저장·quota

ORM은 SQL의 네 표, generated SHA, FK/UNIQUE와 상태 CHECK를 대응한다. postprocess TX와 intent SHA는 둘 다 NULL이거나 applied 상태의 양수 TX+64hex SHA로 결박한다. begin(A)/finish(B)를 막는 receipt SHA 저장/검증과 완료 시 두 marker 해제는 Root SQL의 수정 그대로 유지한다. 실제 metadata reflection 비교는 아직 미수행이다.

SchemaOwner의 최초 정책은 global key0 16MiB/256행, 실제 active `kor-travel-transport` / `transport_airports` DS만 4MiB/64행이다. 다른 DS 기본값이나 ON CONFLICT를 통한 상한 확대는 없다. 등록의 논리 예약량은 입력 payload≤1MiB, context≤8KiB, 결과·후속 receipt 각4KiB 예약을 포함한다. 이는 WAL/RSS/CPU 상한이나 실제 운영 적합성 증거가 아니다. 실제 active Airport가 없으면 해당 DS quota row도 생기지 않는다.

## 검증 기록과 남은 작업

- 최초 공유 source unit/db/ACL 합집합 57 PASS 3.32s, 뒤 확장본63 PASS 2.18s. 각 시점의 파일 차이가 있으므로 최종 source 수용으로 합산하지 않는다.
- 전체 tests/lint 포함 실행은 436 PASS / 3 FAIL / 6 SKIP 38.51s다. 두 실패는 아직 실제430 golden이 없는 새 signature/ACL oracle 검사이며 검사를 완화하거나 dump를 손으로 만들지 않았다. 나머지는 상속된 provider apply 모듈의 docstring 목록 누락으로 Root에 전달했다. 원 로그를 보존한다.
- 같은 검증 세대 mypy4 PASS. 초기 tuple type 추론 오류와 스타일 오류는 수정 이력을 보존했다. 최종 소스 집중 합집합은66 PASS1.66s이며 ruff6·graphcheck·redaction도 통과했다. 로그는 map430-schema-checkpoint-static-r4.log(SHA c6aea5f077f766f3b8a5b01382f39d9aa8d019a7f21e378354649976bf9f7c36)에 보존한다.
- 기존 models 실제 Codegraph impact와 finalization 원장을 재사용했다. 현재 기존 심볼 signature는 바꾸지 않는다. 최신 graph 전체 closure를 증명한 것은 아니며, db checker는 실제 source/callsite와 순수 startup 경로 시험으로 대조했다.
- WSL 진입이 한 번 연결 timeout으로 실패했다. 해당 Python 배치는 실행되지 않았음을 파일 상태로 확인하고, 서비스 재시작·다른 작업 중지 없이 연결 복구 후 계속했다.

다음은 고정 source 두 검토 뒤 owned fresh bootstrap에서 SQL 문법·owner dependency·ACL·startup·ORM reflection을 실제로 확인하는 것이다. postprocess intent mismatch/rollback/replay, newer-applied supersession, GC ledger/retention/active 거부, 전체 A/B/C·등록·reset paired 시험과 최종 caller 원자성도 남아 있다. 최종 공식430 oracle는 그 실제 실행 결과로만 채택한다. cancellation/pool 및 큰 DS 전체 protocol 수용을 이 배선 완료로 대체하지 않는다.


## 첫 실제 bootstrap 실패와 수정

source56854a의 bounded owned postprocess3 실행은 setup3 ERROR16.81s로 끝났다. migration 첫 storage chunk가 두 CREATE TABLE을 한 asyncpg prepared statement로 전달해 거부됐다. 시험 본체와 실제430 head 관측은 실행되지 않았다. 정확 CID/UUID/global label0 및 anonymous volume1 부재를 확인했으며 원 raw/XML을 보존했다. pytest 실패 뒤 runner의 SDK/source post 검사는 도달하지 않아 별도 offline 보충으로만 정산한다.

수정은 정본 과거0202의 문자열/식별자 quote·dollar tag 인식 경계 탐색을 revision-local로 재사용해, owner chunk마다 최상위 SQL 하나씩 보내는 것이다. 기존 routine body·owner/ACL/GUC/순서와 `_sections`의 원문 bytes 재결합은 유지한다. SQL 없는 trailing comment만 실행에서 제외한다. RootSQL 본문이나 시험 기대값을 바꾸지 않는다. 새 고정 source의 실제 설치 수용은 별도 실행 결과가 있어야 한다.

수정 후 집중67 PASS1.77s·mypy1·Ruff2 PASS다. 최종 source는 다음 bounded bootstrap으로만 실제 설치 여부를 판정한다.


## 두 번째 설치 관측과 다음 실제 범위

source7827의 같은3 대상은 실제300→430 migration 및 runtime LOGIN/head 관측에 도달했고 GUC1 PASS/fixture2 FAIL로 끝났다. 첫 실패는 Geo artifact와 `geo_stats=None`의 정본 context 계약 불일치, 둘째는 첫 case가 active policy를 커밋한 동일 Airport identity를 재seed한 조건이었다. SQL guard를 완화하지 않았다. 원 결과/XML과 정확 CID/UUID/global0·volume1 부재를 보존한다. 실패 뒤 runner post 검사는 도달하지 않았음을 유지한다.

Root는6006486에서 실제 GeoStats/builtin set 및 module 초기 seed1회로 fixture를 정정했다. 이 정정을 포함한1c9c6f 부모를 상속했다. 새 전용 시험은 fresh startup boundary/private4표 table·column 권한0/CommandOwner artifact UPDATE0·GC DELETE1/미설치 inactive 검증 모드를 확인한다. metadata 원 검사 함수는 같은 canonical fresh bootstrap DB를 재사용해 command.check와 CHECK 대조를 그대로 수행한다. 실제 결과 전까지 수용으로 세지 않는다.


## startup 실제 통과와 ORM 이름 정정

sourceac822의 한 owned DB5 대상은 startup/privateACL 및 GUC2 PASS, metadata/후처리3 FAIL이었다. 실제 startup service의 새 SD exact allowlist, private4표 raw table/column0, CommandOwner artifact UPDATE0/DELETE1과 inactive inventory 모드는 통과했다. metadata 원 CHECK 대조는 quota cross-column CHECK의 실제 자동명 `_check`/`_check1`과 ORM의 열명 기반 추정 두 곳 차이를 검출했다. SQL 식이나 실제 CHECK를 바꾸지 않고 ORM 이름 두 곳만 실제 catalog에 맞춘다.

Root 실제 apply는 일반runtime에서 private bounded capture를 직접 호출한 지점에서 EXEC 거부로 멈췄다. private 함수 권한을 무조건 넓히지 않고 Root가 typed capture 경계를 수정한다. 뒤 marker case의 active owner는 앞 apply 실패가 남긴 ready plan과 같은 DS를 재사용한 연쇄 실패다. 원 결과/XML·정확 정리 결과와 별도 offline source2494/SDK53 post 동일성 관측을 보존했다. 본래 runner는 pytest FAIL 뒤 post 단계에 도달하지 않았으므로 이 보충을 runner PASS로 재해석하지 않는다. 실제 후처리 완료·재개·전체430 수용은 아직 미완이다.
