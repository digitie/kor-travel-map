# 공항 현재집합 evidence reader(427, 부분 구현)

## 현재 checkpoint

1404의 순수 복원·적격성 진단 위에 별도 reader를 구현한다. 현재 checkpoint는
Geo 비교 계약, 실제 DB 전체 집합을 읽는 STABLE SQL 세 함수, 엄격 decoder와
caller 소유 RR/read-only 배선까지다. 실제 DB 설치·조회·공식 oracle는 미실행이며
상위 provider 준비 단계/기존 native 연결·collector·SH 활성화는 아직 없다.
기존 converter/native 함수, API/DTO/OpenAPI와 기본 EX 수집은 바꾸지 않는다.

`427_transport_airport_reader`는 정본426 다음 선형 revision이다. 부모80c의
제품·기존 시험·공식426 oracle를 상속하고 162a의 Geo/1404 순수 소스를 보존했다.
공통 journal/resume은 own427 prefix 뒤 부모80c 전체 원문을 유지했다.

새 파일과 기존 signature 불변의 canonical 권한 인벤토리 배선이므로 영향도 검사
예외를 적용한다. runtime_privileges/db.py는 public SD 정확 signature 하나와
private 두 함수의 EXECUTE 거부/optional 목록만 추가한다. 새 table SELECT grant는
없고 기존 preflight 검사 함수는 바꾸지 않는다. DB/decoder는 infra이며 provider를
역방향 import하지 않는다. 상위 providers의 기존 native/원 iterator와 연결하는
준비 단계는 후속 미완이다. Heritage private Python helper는 가져오지 않는다.
기존 SQL의 순수 metadata/string-object 검사만 같은 procedure owner에서 재사용한다.

## Geo digest v1의 고정 domain

`AirportGeoFacts`는 DB 출처를 증명하는 객체가 아니다. 후속 SD/decoder가 실제 DB
행을 결박한 뒤 사용하는 값이며 임의 호출자가 만든 지문만으로 적격성을 승인하지
않는다. domain은 UTF-8 ASCII
`kor-travel-map:transport-airport-geo-evidence:v1` 뒤 NUL 한 바이트다.

각 원소는 NULL이면 `00`, 문자열이면 `01 || UTF8길이의 8바이트 big-endian || UTF8`로
frame하고 순서대로 SHA256에 넣는다. NULL/빈 문자열/구분자/Unicode 및 JSON 공백이나
키 순서가 경계를 바꾸지 않는다. 고정 순서는 다음과 같다.

1. dataset bigint의 십진 문자열, `se_`64hex, 이전 R1의 `sr_`20hex, R1 payload SHA256의 정본32hex prefix,
   Feature UUID 소문자 표준 문자열, base 좌표의 NDR/2D/POINT/SRID4326 EWKB 소문자 hex.
2. Address의 정확12개 순서: road, legal, admin, bjd_code, admin_dong_code,
   sigungu_code, sido_code, road_name_code, road_address_management_no, zipcode,
   sido_name, sigungu_name. 각 값은 문자열 또는 NULL이다.
3. 실제 stamp version/data token, reverse_outcome, stamped_at의 UTC 마이크로초 ISO형식
   (`YYYY-MM-DDTHH:MM:SS.ffffffZ`).

첫 범위는 기존 ADR-116의 좌표 reverse 재사용처럼 outcome=`called`만 허용한다.
`resolved`를 `geocoded` outcome의 자동 허가로 해석하지 않는다. coord가 SQLNULL인
`not_requested` 분기는 별도이며 없는 stamp/digest를 만들어 채우지 않는다. 지문은
같은 raw/hash·좌표·저장 주소·실제 stamp의 비교값이다. 현재 토큰에 대한 외부 주장이나
raw7/normalizer label만으로 Geo 재사용 권한을 얻지 않는다. 후속 decoder는 같은
Feature/claim/base R1 및 주소 코드의 대응과 모든24필드 clock을 따로 검증해야 한다.

좌표는 정확25바이트 EWKB이며 두 float8의 finite/범위를 binary에서 검사한다. token은
각256 UTF8바이트, 주소 문자열은 각각8192 UTF8바이트 이하, Geo frame 합은128KiB
이하다. 이 Python 검사는 호출자가 이미 만든 객체의 메모리나 PG detoast를 제한하지
않는다. 서버 metadata pass와 전체256KiB/encoded1MiB 상한이 별도로 필요하다.

## 고정할 SQL/decoder I/O

공개 SD source signature는
`feature.read_transport_airport_snapshot_evidence(p_dataset bigint) RETURNS jsonb`다.
STABLE/SECURITY DEFINER/search_path=pg_catalog, owner는 기존 state procedure owner다.
정확 public signature만 canonical allowlist에 추가하며 private table SELECT grant는
없다. private helper는 PUBLIC/runtime EXECUTE를 거부한다. 이 signature는 실제
설치하지 않았고 fake complete를 반환하는 placeholder도 없다.

응답 top-level은 version=1, dataset_id, evidence_complete, db_scope_eof, reason,
policy_epoch, items의 정확7키다. 성공은 complete/eof=true, reason=NULL, epoch 정수,
items 1..2730개다. 알려진 거부는 complete/eof=false, epoch=NULL, items=[]다. 거부는
전체 단위이며 일부 항목만 성공으로 돌려주지 않는다. 내부 SQLSTATE/장애는 전파한다.

items는 source_entity, source_head, feature, claim, membership, active_policy, policy,
name_candidate, name_base, non_name_base, base_record, name_value_record, current_record,
geocode_stamp의 정확14키다. name base clock과 current/name/non-name 원천을 따로 남긴다. 각 row의 구체 키·NULL/geometry type과
12관계51가변열 inventory는 별도 JSON으로 고정하고 SQL 양방향 대조를 시험한다.
이는 작성자 source 검사이며 독립 fullSQL/실제 DB 수용과 다르다. 양 source record의 raw7을 각각
반환하고 단일 non-name R1을 지원한다. mixed R1은 전체 EX다. core.name의 R1/R2와
24개 non-name 값·base_revision·observed_at·lineage를 합치거나 생략하지 않는다.

DB 전체 dataset 현재 entity를 LIMIT2731 metadata부터 조사하여 DB EOF를 증명한다.
requested subset을 전체로 포장하지 않는다. 반면 DB EOF와 입력 iterator EOF는
upstream provider EOF가 아니다. provider의 신규 항목 누락과 수집 완료는 별도다.
first15가 실제256KiB/1MiB에 들어간다는 주장도 하지 않는다.

준비 단계는 원 iterator의 MAX+1/전체 artifact 예산 검사와 exact keyset을 확인한다.
호출자가 fresh READ ONLY REPEATABLE READ transaction을 소유하며 hidden commit이나
격리수준 변경은 없다. DB 읽기 후 incoming bundle의 Geo claim이 위 actual DB facts의
지문·token·주소와 같은지 검증해야 한다. claim은 이전 read로 얻었을 수 있지만 그
경우도 snapshot/입력의 재검증을 생략하지 않는다. 준비 결과의 collector_ready는
항상 false다. P/L 뒤 fresh RC guard와 실제 apply/finish 재검증은 이 단위 밖 미완이다.

## 실제 확인과 남은 항목

새 Geo 계약 순수26 PASS 1.54초, Ruff와 mypy1 PASS다. 첫 mypy의 loop 변수 재사용
오류1개는 address 변수명을 분리하여 닫았다. DB/SDK 실행이나 서버 메모리 증거는
없다. 기존 converter/native 함수의 실행을 새 시험 결과로 합산하지 않는다.

다음은 위 I/O의 전체 row schema·metadata-before-detoast SQL·NULL/압축/geometry와
EOF·권한 inventory를 구현하고 두 독립 source gate를 받는다. 실제 소유 PG의
positive/negative/RR·statement snapshot/큰 무관 history EXPLAIN·peak와 공식 oracle은
그 뒤 별도 승인으로 진행한다. 휴게소215/실제 두 worker/whole closure·durable 복구와
운영 활성화는 전부 미완이다.

## 원천 hash 길이 P2 정정

첫 Geo 계약은 raw_payload_hash를64hex로 잘못 고정했다. 정본 `make_payload_hash`의
기본값은32hex prefix이며 실제 Transport converter가 이를 그대로 쓴다. 최종 Geo
SHA256 digest64hex와 원천 hash32hex를 혼동한 입력 계약 오류다. 초기 f887과 당시
순수26 성공은 보존하며 이 P2를 닫은 결과로 재해석하지 않는다.

정본 factory 기반 decoder positive에서 원3 FAIL/26 PASS를 확인했고, 공개
TransportAirport→기존 converter→실제 SourceRecord/hash/key를 사용하는 회귀도
수정 전1 FAIL/1.49초로 재현했다. source32hex만 받도록 고정하고64hex 입력은
명시 거부한다. 공개 경로의32hex positive와 Geo 최종 digest64hex 구분을 시험했다.
수정 후 합집합104 PASS/1.55초는 Geo 계약28+작업 중 decoder29+기존 native47이다.
이 checkpoint 소유 소스는 Geo 계약28까지이며, 아직 미추적 decoder/SQL의 완성이나
DB 수용으로 합산하지 않는다. 다음 decoder/SQL checkpoint는 별도 source gate다.


## 전체 SQL/decoder source checkpoint

공개 함수는 dataset bigint 하나만 받는다. 입력은 DB dataset의 전체 entity이며
첫 key도 압축/physical128B/global256KiB 검사를 통과한 뒤에만 정렬·형식 비교한다.
각 관계의 양측 가변 key 비교는 CASE 안의 metadata guard 뒤에 둔다.
모든 payload는 전체 metadata 성공 뒤 (tableoid,ctid) 내부 위치로 다시 읽는다.
동일 STABLE snapshot 안에서만 위치를 쓰고 상속/partition은 거부한다.

[열 목록](2026-10-25-airport-reader-column-inventory.json)은 12관계51가변열의
physical cap/SQLNULL/압축 금지를 고정한다. epoch와 UUID-only override/area 존재
검사도 별도 명시한다. 실제 features의 coord/address/6개 코드8가변열을 추가 검사해
provider base와 materialized Geo를 비교한다. 어떤 사람 override도 첫 범위에서는
전체 거부한다. name policy/core.name 정확 한 필드, 단일 primary/all-role closure,
current/value/non-name 단일 R1과 24개 clock을 유지한다. 혼합 R1/legacy normalizer는
알려진 전체 거부이며 일부 성공을 반환하지 않는다.

reader는 caller의 기존 READ ONLY REPEATABLE READ transaction만 허용한다.
mode 확인과 SD 실행 전체에 협력적3초 상한을 두고 commit/rollback/GUC 변경은 하지
않는다. SQLSTATE/timeout/취소는 전파하며 generic EX fallback으로 바꾸지 않는다.
DB EOF는 upstream EOF가 아니며 response의 evidence_complete는 구조·저장 증거의
완결성만 뜻한다. SDK 의미 적격성·새 입력과의 동등성·Geo 현재 token 승인·쓰기 권한은
주지 않는다. `collector_ready`는 항상 false다. incoming iterator MAX+1/whole artifact와
기존 native를 연결하는 provider 준비 seam은 아직 없으며 다음 별도 단계다.

순수 합집합108 PASS/1.68초 = Geo28 + synthetic decoder29 + migration/열목록4 +
기존 Transport native47이다. decoder fixture는 실제 SD가 만든 응답이나 실제 SDK
저장 shape의 positive 증거가 아니다. 첫 잘못된 시험 경로로 수집0, 다음 migration
시험의 SQL 선행 주석을 CREATE로 세지 못한2 FAIL/106 PASS를 보존했다. SQL 명령을
삭제하지 않고 시험의 첫 유효 줄 판별만 보강한 뒤108을 확인했다. mypy4 PASS다.
기존426 `head-schema.sql`은 그대로이며 427 공식 oracle는 아직 생성하지 않았다.
full head static oracle/권한·실제 positive/negative/RR snapshot/큰 history plan·CPU·peak,
실제15 fit/전체 upstream·SH closure·2 worker·운영은 전부 미완이다.

정확 SD startup allowlist의 bigint 허용/누락 및 text overload 거부를 포함한 DB unit24
PASS/1.62초, migration/receipt/role/sidecar/SQL/문서 정적36 PASS/2.44초, import4
PASS를 별도로 확인했다. 첫 import 검사 명령은 실행 entrypoint를 잘못 지정해 실패했고
정본 lint-imports entrypoint로4개 계약을 확인했다. 기존 head426 oracle를427로
바꿔 성공을 꾸미지 않으며 공식 fresh bootstrap까지 oracle 관련 최종 gate는 보류한다.


## 논리 key 인덱스·서버 상한과 provenance 보강

1191 source를 보존하고 두 독립 FULL 뒤 후속 설계 r3를 반영한다. source heads/records/
links에 새 CASE expression index를 하나씩 추가한다. 표현식은 정확히
`CASE WHEN pg_catalog.octet_length(key::text)<=256 THEN key::text ELSE NULL::text END`다.
pg_catalog의 immutable 논리 길이 검사이며 긴 key는 본문을 펼치지 않고 NULL로 넣는다.
기존 index를 재작성하거나 긴 데이터를 삭제하지 않는다. 새 인덱스는 생성부터 live/dead/
pivot의 text key가256바이트 이하이므로 기존 index의 과거 긴 pivot를 재사용하지 않는다.
COLLATE를 추가하지 않고 원 열의 collation을 유지한다. 세 index는 schema owner의
P EX/유한 caller lock1초·statement30초 안에서 생성한다. 이름 충돌은 실패하며
IF NOT EXISTS로 다른 정의를 묵인하지 않는다.

네 key lookup도 동일 CASE를 사용한다. seqscan이라도 raw length 검사 전 text 비교를
하지 않으며, 통과한 대상의 compression/physical metadata 검사는 그대로 둔다.
이 식은 인덱스 사용 가능성을 보존하는 설계이지 실제 사용·CPU 개선의 증거가 아니다.
큰 무관 history/긴 압축 key가 있는 실제 EXPLAIN의 Index Cond·heap buffers와 index 빌드/
일반 writer 유지비·IO·시간은 별도 미완이다. pg_column_size/compression의 STABLE 속성을
IMMUTABLE wrapper로 속이지 않는다. validated CHECK만 추가하면 과거 B-tree pivot까지
제한하지 못한다는 별도 설계 finding을 반영했다. 기존 canonical capture와 428의 새 fold는
이 PR에서 수정하지 않는다.

RR/read-only wrapper는 caller가 설정한 statement_timeout이1..3000ms, lock_timeout이
1..1000ms인지 기존 mode 조회에서 확인한 뒤에만 SD를 호출한다. 0/초과/잘못된 값은
호출 전에 거부하고 GUC를 설정하거나 더 긴 값으로 바꾸지 않는다. mode+SD 전체의
협력적 asyncio3초도 유지한다. PostgreSQL 장애/취소의 원예외는 그대로 전파한다.

J 독립 FULL은 inventory JSON 말미에 Heritage422의 실제 checkpoint/관측이 provider
구분 없이 남은 provenance P2를 찾았다. 해당 원본1191을 보존하고 이를 명시적인
Heritage primitive 역사 참고 안에 분리했다. Airport427 실제 PG/oracle/positive/API는
모두 false다. 문서가 UUID-only area 존재검사를 주장했지만 원 SQL에는 관계 catalog
검사만 있던 P2도 수용했다. 이번에는 실제 feature_areas UUID EXISTS를 payload 이전에
추가하며 존재하면 unsupported_membership으로 전체 거부한다. 기존 kind/FK 추론을
직접 관찰한 EXISTS라고 포장하지 않는다.

새 순수 합집합143 PASS/2.01초는 Geo28+decoder39+migration5+native47+DBunit24다.
서버 상한의0/초과/형식8거부·최소/최대2허용과 새index/role/동일CASE source 검사를
추가했다. 실제 index 설치/사용, area 분기 실제도달, SD/RR/메모리/collector 수용은
아니다. 새 고정 source는 다시 root/J 독립 delta 검토를 받은 뒤에만 실제 PG로 간다.


## 실제 준비 경계와 공항1→15 시험 소스 (미실행)

`providers.kor_travel_transport_evidence`는 최종 입력을 기존 EX snapshot의 MAX+1/전체
artifact 예산으로 먼저 제한한 뒤 caller 소유 RR/read-only snapshot에서 공개 SD를 읽는다.
입력 entity 집합이 DB 전체 EOF 집합과 정확히 같아야 하며 입력 EOF를 upstream EOF로
바꾸지 않는다. 반환 성공은 `collector_ready=False`이며 kernel 잠금 뒤 DB 재검증이 여전히
필수다. 새 DB 쓰기/attempt/collector 선택은 없다.

저장 R1 raw는 기존 Transport dataclass 복원과 기존 converter로 재생성한다. 정본
provider patch payload로 24개 비이름 값/geometry/null을 비교하고 이름의 R2 record와
후보·base 값을 별도로 결박한다. 좌표가 있으면 실제 snapshot stamp의 `called`/현재
Geo token/주소/좌표와 versioned GeoFacts를 결합한다. 좌표 없는 `not_requested`는 별도다.
현재 raw 변경은 EX 진단을 유지한다. SQL 오류·취소·timeout은 fallback으로 감추지 않는다.
거부된 준비 진단이 보유하는 DB evidence도 apply 허가가 아니다.

새 순수12시험은 정본 converter+synthetic wire를 사용한 무좌표/Geo positive, R1/R2
분리, bool이 아닌 Geo model_copy flag 거부, base/변경raw/scope/Geo 부정, 알려진 SD 거부와 원 SQL 예외 전파,2731개 소비 뒤
첫 SQL 이전 중단이다. 실제 DB 저장 shape 증명은 아니다. 첫 순수 fixture는 DTO에 없는
`Feature.legal_dong_code` 접근으로9FAIL했고 보존했다. 정본 patch payload의 코드 값을
사용하도록 fixture만 고친 뒤9PASS, R1/R2 시험 추가 후10PASS1.20s, 잘못된 Geo bool
경계2개를 추가한 최종12PASS1.19s다.

새 integration testcase는 같은 소유 DS에 정본 loader+Geo context→shadow capture→명시
lab cutover로1개를 만들고, EX sealed scalar apply로 이름 R2/비이름 R1과 stamp 보존을
검사하도록 작성했다. 이후 같은 DS에14개를 정본 추가한다. 실제15개 positive 또는
정확 `budget_exceeded`/전체 items[] 거부를 기록하며15fit를 전제하지 않는다.
운영 공항15/실 Geo HTTP/whole upstream EOF/SH 적용 수용이 아니다. 현재 collect1뿐이며
실제 PG 실행, 공식427 oracle, 새 인덱스의 대규모 history EXPLAIN/메모리는 미완이다.


## 첫 실제427 검사와 EX fixture 진입점 정정

source195의 한 소유 fixture는1FAIL14.880s였다. 실제 head427/서비스 역할/import16을
확인하고 N1 reader/준비 진단 positive 단언을 통과했지만 전체 testcase PASS는 아니다.
이후 이름 R2 fixture가 `exclusive=True`로 EX plan을 만들고 SH 전용
`refresh_scoped_provider_scalars_batch`를 호출해 `23514 protocol share to exclusive
upgrade requires replan`에서 중단됐다.15개 단계에는 도달하지 않았다.

시험 호출1곳만 기존 `refresh_exclusive_provider_scalars_batch`로 정정한다. 두 공개
함수는 같은 `_refresh_batch`에 각각 명시 False/True를 전달하며, EX 함수가 기존
EX/global fence를 먼저 획득한다. plan/manifest/기존assert/제품 SQL·권한·예산은
변경하지 않는다. 원FAIL과 CID/UUID/global label0·volume1 부재 정리를 보존했다.
실패 runner는 SDK/Git post 검사 전에 중단됐으므로, 별도 offline observer로 원Git
2416 blob/mode·SDK53 전후 불변을 확인한 범위를 구분한다. 새 source/binding 두
리뷰와 CPU 승인 전 재실행0이며 공식427 oracle/15fit/collector/SH/운영은 미완이다.


## b3b 실제 결과와 공식427 oracle

원 r1 FAIL은 그대로 보존하고 새 소유 r2에서 단일 testcase1 PASS(XML15.228s,
whole23.910s/skip0)를 확인했다. 전부 유좌표·called Geo context를 쓰는 작은 synthetic
공항1→EX 이름 R2/비이름24 R1·stamp 보존→같은 DS 추가14개까지 완료했고
`airport15_outcome=complete15`였다. actual head427/서비스 역할/import16·Git2416/SDK53
전후와 CID/UUID/global label0·volume1 부재를 검증했다. 이는 운영 공항15fit, 무좌표
실제 PG branch, upstream EOF, 실제 Geo HTTP, collector/SH 적용의 증명이 아니다.

같은 b3b source의 공식 canonical300 fresh bootstrap은 별도1 PASS(XML14.205s,
suite21.872s/whole29.662s)다. runtime reconcile 없이 공식 dump/repeat 비교를 수행했고
원 dump `c0effcbcab7b7c86aee57afb176aa6aaf7cad702f8550fb336f446626d1e64b4`를
그대로 head-schema에 반영했다. 부모426의1643블록 중1642개와 기존405 ACL이 byte동일하며,
변경은 receipt CHECK의427 literal1개와 신규 함수3/ACL3/CASE index3뿐이다. 추가9개를
제거하고 receipt literal을 역변환하면 부모 전체 원문과 정확히 같다. 새3함수의 dollar
body도 source sidecar와 byte동일하다. 부모 독립 비교와 공식 자기 repeat를 구분한다.

## R2/R3 비이름 의미 P2 보강과 c63 재검증

b3b 준비 함수는 R1의 nonname24만 재생성과 비교해, 이름 R2 또는 현재 R3의 raw와
정본 bundle에 ICAO를 추가했어도 저장 R1 facility가 예전 값인 경우 eligible로 잘못
진단할 수 있었다. `collector_ready=False`였으며 잘못된 apply 수용/실 DB 반례는 아니다.
기존 root/T FULL 리뷰 기록과 b3b 실제 fixture의 제한 범위를 보존하고 의미 검토를 HOLD로
정정했다. 서로 독립된 public 준비 함수 반례2개는 수정 전2FAIL1.23s였다.

이름 R2와 현재 R3를 각각 기존 converter로 재생성하고 같은 저장 R1 nonname24와
비교하는 조건만 추가했다. 현재 raw와 입력 raw가 같아도 저장 의미가 다르면
`stored_nonname_history_mismatch`로 EX 진단한다. 기존 raw/hash/key·정규화·Geo·name
검사와 SQL 오류 전파는 유지한다. 보강 후 순수157 PASS2.10s/mypy1/Ruff PASS이며,
SQL/마이그레이션/권한/실제 fixture 본문은 b3b 그대로다. root/T의 독립 source 리뷰와
root/J의 실행기 binding 리뷰 뒤 c63 고정 source를 새 소유 r3에서 한 번 재검증했다.
단일 testcase1 PASS(XML15.246s, whole24.403s/skip0), `airport15_outcome=complete15`다.
actual head427/서비스 역할/import16·Git2416/SDK53 전후와 CID/UUID/global label0·volume1
부재를 검증했다. 원 r1 FAIL·r2 positive·공식 b3b DDL oracle는 각각 보존한다. 공식oracle는
준비 함수를 호출하지 않으므로 b3b SQL의 증거와 새 Python 검증을 별도로 정산한다.
운영15fit·무좌표 실제 branch·upstream EOF·collector/SH·대형 history EXPLAIN·hard peak와
최종 CI는 여전히 미완이다. 원 결과의 사적 감사는 `map427-owned-airport-r3-actual-facts.json`
(SHA256 `47fce66d526a26f335818cdb5ca9a7e4eb4e31563016130d08dbc78f96dc9fcf`)에 고정했다.
