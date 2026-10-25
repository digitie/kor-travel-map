# 공항 현재집합 evidence reader(427, 부분 구현)

## 현재 checkpoint

1404의 순수 복원·적격성 진단 위에 별도 reader를 준비한다. 현재 구현은 고정 Geo
비교 계약과 순수 경계 시험뿐이다. migration/SD/decoder/DB 호출·reader·collector·SH
활성화는 아직 없다. `427_transport_airport_reader` 번호만 예약한다. 기존 converter,
1404 함수, API/DTO/OpenAPI, 수집과 기본 EX는 바꾸지 않는다.

새 파일만 추가하고 기존 심볼의 signature를 바꾸지 않아 AGENTS.md의 영향도 검사
예외에 해당한다. 실제 import는 stdlib뿐이며 provider 역방향 import가 없다. DB
조회/decoder는 infra, pure native와 연결하는 준비 단계는 상위 providers에 둔다.
Heritage private Python helper를 가져오거나 provider HTTP facade를 만들지 않는다.

## Geo digest v1의 고정 domain

`AirportGeoFacts`는 DB 출처를 증명하는 객체가 아니다. 후속 SD/decoder가 실제 DB
행을 결박한 뒤 사용하는 값이며 임의 호출자가 만든 지문만으로 적격성을 승인하지
않는다. domain은 UTF-8 ASCII
`kor-travel-map:transport-airport-geo-evidence:v1` 뒤 NUL 한 바이트다.

각 원소는 NULL이면 `00`, 문자열이면 `01 || UTF8길이의 8바이트 big-endian || UTF8`로
frame하고 순서대로 SHA256에 넣는다. NULL/빈 문자열/구분자/Unicode 및 JSON 공백이나
키 순서가 경계를 바꾸지 않는다. 고정 순서는 다음과 같다.

1. dataset bigint의 십진 문자열, `se_`64hex, 이전 R1의 `sr_`20hex, R1 payload SHA256,
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

후속 공개 SD signature는
`feature.read_transport_airport_snapshot_evidence(p_dataset bigint) RETURNS jsonb`다.
STABLE/SECURITY DEFINER/search_path=pg_catalog, owner는 기존 state procedure owner다.
정확 public signature만 canonical allowlist에 추가하며 private table SELECT grant는
없다. private helper는 PUBLIC/runtime EXECUTE를 거부한다. 이 signature는 아직
설치되지 않았고 fake complete를 반환하는 placeholder도 없다.

응답 top-level은 version=1, dataset_id, evidence_complete, db_scope_eof, reason,
policy_epoch, items의 정확7키다. 성공은 complete/eof=true, reason=NULL, epoch 정수,
items 1..2730개다. 알려진 거부는 complete/eof=false, epoch=NULL, items=[]다. 거부는
전체 단위이며 일부 항목만 성공으로 돌려주지 않는다. 내부 SQLSTATE/장애는 전파한다.

items는 source_entity, source_head, current_source_record, non_name_source_record,
feature, claim, membership, active_policy, shadow_policy, name_candidate,
non_name_base, geocode_stamp의 정확12키다. 각 row의 구체 키·NULL/geometry type과
12관계/전가변열 inventory는 다음 SQL checkpoint에서 기계 계약으로 고정한다.
그 전까지 decoder/fullSQL ready로 세지 않는다. 양 source record의 raw7을 각각
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
