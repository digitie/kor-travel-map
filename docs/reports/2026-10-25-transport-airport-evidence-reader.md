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
