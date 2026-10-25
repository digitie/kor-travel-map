# 제한된 현재 입력집합 capture(428, 구현 중)

## 범위와 상태

기존 `current_provider_curation_input_set`의 네 집계값과 hash/date/정렬 계약을
보존하면서, 전체 현재집합이 작은 안전한 형태인지 먼저 검사하는 내부 함수를 추가한다.
SQL·migration·권한 정본과 시험 코드를 추가하고 427 부모를 상속했다. 두 source 검토 뒤
실제 PostgreSQL 통합37개와 fresh bootstrap 공식 oracle1개가 통과했다. 덤프·문서 두 검토를 확인했고 최신 공항427·main을
상속했다. 최종 CI는 아직 수용 전이다.
새로운 공개 API/DTO나 collector 호출, RC 전환, SH 활성화는 없다.

## 검사 순서와 예산

동일 statement snapshot에서 payload를 읽지 않는 관계 열기, 정확 heap/상속 및
feature_places의10열 catalog 확인, MAX+1 수량, 가변열 storage metadata, 개별 형태,
개별 encoded 행과 전체 encoded 크기, 마지막 동일 정본 formula의 제한 aggregate 순서다. 현재 entity는
1..2730개, 저장 가변열 합256KiB, 행 encoded256KiB, 전체 encoded1MiB를 넘으면
전체 거부한다. 빈 집합이나 일부 membership/lineage 누락도 성공으로 포장하지 않는다.

압축된 가변열은 거부한다. text는256 UTF8바이트, phones는1차원/lower1/32개 이하,
각 원소256바이트, 전체8KiB다. business_hours는SQLNULL만 지원한다. 나머지 세 JSON은
각8KiB 이하의 object이며32키 이하, key와 string 값은각256바이트, 값은 string 또는
JSONnull만 지원한다. 숫자·bool·배열·중첩 object를 text로 확장하지 않는다.

대상은 active place와 단일 primary/all-role link다. 다른 subtype, 공유 Feature,
존재하는 모든 operator override는 거부한다. 실패는 이유와 NULL 집계4개로 돌려준다.
성공값은 검증한 개별 행의 inner sha256을 기존 key/Feature 순서로 접는 동일 formula의 네 값이다.
기존 함수를 다시 호출하지 않으며 본문·권한은 보존한다. key 열의 default collation을
확인하고 비기본 collation은 거부하여 정렬을 임의의 C 순서로 바꾸지 않는다. STABLE의 snapshot 일관성은
외부 수집 EOF, provider 전체성, 입력과 DB의 동등성, P/L 이후 fresh RC 검증 또는
쓰기 권한을 증명하지 않는다. index 비교·실행계획·DB 전체 작업 메모리의 엄격 상한이나
실측 RSS 개선을 이 예산으로 주장하지 않는다.

## 권한과 검증 계획

새 함수는 schema owner의 고정 search_path SD이며 curation command owner만 호출한다.
내부 JSON helper는 runtime/PUBLIC에 공개하지 않는다. metadata helper의 필요한 owner간
EXECUTE만 추가한다. 기존 raw table 권한, 정본 함수 본문과 호출자는 보존한다. 427이 추가하는 세
logical CASE 표현식 인덱스와 정확히 같은 조회 식을 사용한다. seqscan이어도
octet_length의 raw length 검사 후 논리256바이트 이하 key만 비교한다. 실제 history
계획과 비용, 새 인덱스 생성·유지 비용은 실제 PG에서 확인할 항목이다.

설계 r6는 두 독립 검토를 통과했다. migration fake-bind 시험16 PASS/0.42초는
P-first, 의존 함수 지문/속성 확인, 유한 timeout과 원 설정 복원만 검증한 단위 결과다.
추가 통합37개는 수집만 확인하며 실행 전이다. 실제 PG 성공이나 메모리 개선 증거로
합산하지 않는다. 구현 후 정상 네 값 일치,
압축/숫자 확장/형태·수량·예산·catalog·override 거부, 실제 LOGIN 권한과 공식 schema
oracle을 확인하고 두 적대 리뷰 및 정확 head CI를 통과해야 한다.

후속 전체 caller/엄격 SH guard/부모 잠금 순서/내구성 복구와 두 실제 수집기 동시
apply·finish는 아직 미완이며 Common·Weather·Transport 전파도 그 수용 이후다.


## 적대 리뷰의 두 P2와 설계 정정

9506 source 전체를 두 리뷰어가 확인해 저장 key의 metadata 이전 비교와 시험 준비의
identity 변경을 지적했다. 원 source/당시 통합32 collected 결과를 보존한다. 첫 보강안의
전체 CHECK 검증만으로는 과거 index pivot를 제한할 수 없다는 지적, 다음 안의 COLLATE C가
정본 default 정렬과 달라질 수 있다는 지적도 반영했다. 두 설계 검토를 통과한 r3를 따른다.
기존 데이터의 CHECK/값을 변경하거나 재작성하지 않는다.

세 새 인덱스는 생성 시부터 octet_length CASE의 논리256바이트 이하 또는 NULL만 저장한다.
기존 큰 key index를 capture에서 다시 조회하는 경로를 없애고 bounded 행으로 동일 네 값을
계산한다. 원 함수 body fingerprint 의존 검사는 유지한다. 실제 Unicode/대소문자/복수entity,
세 timezone의 정본 동등성과 무관한 이력5000건의 index condition 회귀를 준비했다.
시험 데이터도 처음부터 같은 DS에 생성하며 identity immutable guard를 그대로 지킨다.

현재 보강은 아직 두 코드 리뷰·부모427 상속·실제 PostgreSQL/공식 oracle/CI 전이다.
단위35 PASS/1.35초와 통합37 collected/1.11초이며 실제 통합 실행이나 운영 반영은0이다.


## 427 부모 합성과 권한 실행 역할 정정

검증한 427 최종 source를 상속하여 새 인덱스3와 단일428 graph를 함께 고정한다.
부모의 source/함수·native 구현과 문서 전체를 보존한다. 실제 schema dump는 아직426이며
새 head의 공식 oracle 전이므로 이를 실제428 schema라고 바꾸지 않는다.

합성 과정에서 root가 별도 P2를 발견했다. bounded 함수2개는 schema owner 소유인데
권한 조정 정본의 state procedure owner 창에 REVOKE/GRANT가 있었다. 두 역할의 역방향
membership이 없어 실제 reconciliation에서 소유권 오류가 날 수 있었다. 새 owner-window
회귀의 수정 전1 FAIL을 보존하고, bounded 함수 ACL만 schema owner 창으로 이동했다.
metadata helper의 owner간 dependency GRANT는 원 소유자인 state procedure owner 창에
남긴다. 새 단위 합집합36 PASS/1.23초다. 앞선 두 source 리뷰의 PASS를 이 새 P2 검증으로
소급하지 않으며, 최종 합성 pin에서 추가 독립 검토와 실제 LOGIN/정본 reconciliation을 확인한다.


현재 최종 합성의 단위·정적 합집합72 PASS/2.33초, mypy2/Ruff 통과 및 통합37 collected를
확인했다. timezone 회귀는 첫 import보다 이틀 뒤17:30 UTC를 명시 입력하여 Seoul 다음날
변환의 예상 날짜도 독립 단언한다. 긴 key fixture는 실제 압축 여부·논리16000바이트와
저장 크기를 단언한 뒤 조회 계획을 확인하도록 했다. 모두 실제 통합 실행 전이다.

## 첫 실제 PostgreSQL 검사와 시험 데이터 정정

39fe source를 PG16.14/default en_US.utf8에서 실제 실행해34 PASS/3 FAIL을 확인했다.
숫자 JSON literal의 colon을 SQLAlchemy가 bind로 인식한 오류, 누락 head를 관찰한
시험 TX가 deferred 무결성 검사 전에 rollback하지 않은 오류, 무관한 이력5000건이
같은 entity/hash unique key를 재사용한 오류다. 숫자 payload는 bind로 전달하고,
누락 상태 관찰 뒤 rollback하며, 이력은 서로 다른 정수 필드를 가진 object raw와 동일 정본 SHA256
방식의 hash로 만든다. 제품 SQL·권한·예산은 변경하지 않는다. 실패 원본과 컨테이너·
volume 정리 성공 기록은 보존한다. 수정 후 재실행·공식 oracle·CI는 아직 미완이다.
그 전 관찰기 r2의 lc_collate 설정 조회는 DB 버전 차이로37개 본문 실행 전 실패했다.
관찰기만 pg_database catalog 조회로 정정했으며 이 실패도 성공 결과에 합산하지 않는다.

2b236의 첫 수정은 이력 raw를 정수 scalar로 만들어 object CHECK를 위반할 수 있다고
두번째 리뷰어가 지적했다. 이 pin으로 재실행하지 않았다. `{"n": n}` object와
공백 없는 정본 JSON의 SHA256 prefix로 정정하고 원 검토의 누락도 보존한다.

## 실제 674 수용 결과

PG16.14, glibc en_US.utf8에서37개 통합 시험이 모두 통과했다. 이는 Unicode/default
정렬·세 timezone·정본 네 집계값, JSON 숫자의 text 확장 전 거부, metadata/shape/수량/
binary·encoded 전체 예산, source membership/override/LOGIN 권한, 무관한 이력5000건과
큰 압축 key가 있어도 새 CASE index condition 사용을 확인한다. 앞선 실패는 별도로
보존하며 통과 수에 합산하지 않는다.

같은 source의 공식300 fresh bootstrap은 runtime 권한 재조정 없이 head428까지 설치됐다.
공식 schema dump/반복 dump 비교1개가22.897초에 통과했고 덤프 SHA256은
`110440832b264ec5ea9fd56cf0b3130ba21cfaeb19a27bcbfb974eb051c08ad5`다.
부모426과 비교해 새 함수5/각 ACL5/index3만 추가되고, 기존 metadata helper의
schema owner EXEC와 schema receipt CHECK만 달라진다. 기존 객체 제거는 없다.
부모 덤프를 새 스키마의 의미적 정답으로 간주하지 않고 생성·반복 비교 증거로 구분한다.
두 실행 모두 source2419파일/SDK53파일 전후와 실제 import9개를 확인했고, 정확 시험
컨테이너·volume이 제거되어 owned 컨테이너0을 확인했다.

이는 synthetic x86 격리 시험이다. 실제 공항15·수집 HTTP·ARM CPU/RSS 저감·RC/SH
쓰기·전체 writer closure·내구성 복구·운영 배포·Common/Weather/Transport 전파 수용은
아직 미완이다. 공항427 준비 함수의 의미 보강과 최신 main 상속을 마쳤으며 정확 head CI를 마쳐야 한다.

## 최종 공항427과 최신 main 상속

427의 R2/currentR3 비이름 의미 보강과 실제 synthetic1→15 재검증을 마친70cb를
상속했다. 최신 main의 가격 이력 API 후속 변경도 그대로 포함한다. 428의 SQL/권한/
시험과 검증된428 공식 dump는 변경하지 않는다. 부모427의 세 SQL body가 그대로이므로
427 dump로428 golden을 덮어쓰지 않는다. 최종 합성은 별도 두 리뷰와 CI로 확인하며,
실제37/공식1 증거를 새 실행으로 부풀리지 않는다.


## 최종 CI의 인벤토리 규약 위반 정정

c98 CI의 Python3.12/3.13에서 각3815 PASS·7 SKIP 뒤 동일 lint1개가 실패했다.
권한 조정의 DO 문에 함수 인자 타입 리터럴2개가 남아 있었으며 원 실패·로그를 보존했다.
존재 검사는 schema/name의 pg_catalog 조회로, GRANT는 기존 `(...)` 인벤토리의
카탈로그 치환으로 바꾼다. 300에서는 optional metadata helper 부재로 생략하고,
422~427에서는 capture가 없으므로 추가 EXEC를 주지 않는다. 428부터만 기존 owner간
EXEC를 복구하며 역할·runtime 권한·제품 SQL·공식 dump는 바꾸지 않는다.
검사 완화 없이 rendering·signature lint와 후속 정확 CI를 다시 확인한다. 이 수정 이후의
실제 PG 검증은 최종 CI 결과로 구분하며 이전37/oracle1 실행을 새 결과로 합산하지 않는다.

정정 후 권한 단위·migration 단위·signature lint46 PASS/3.58초, Ruff와 strict mypy1파일 및 redaction/차이 검사를 통과했다. 새 PG 실행은0이며 정확 CI와 두 후속 리뷰는 별도다.
