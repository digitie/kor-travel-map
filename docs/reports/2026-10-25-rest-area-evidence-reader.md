# Rest431 명시 reader의 첫 source 경계

## 현재 범위

승인된 [431 설계](2026-10-25-rest-area-snapshot-profile.md)를 최종430 후보7f40 위에
상속했다. 새 `RestAreaGeoFacts`, 전용 migration431/SD3개와 strict decoder·caller RR/read-only
경계까지 source로 준비했다. 신규 typed SD의 최소 ACL/optional/startup signature만 연결했고
SQL 실제 설치·호출/등록·collector·운영 flag는0이다. 공식 golden은 실제430을 보존한다.
기존 Airport427/430 코드·공통 projection·SDK converter는 변경하지 않았다.

Geo pins domain은 `transport-rest-area-geo-v1`, 지문 framing domain은
`kor-travel-map:transport-rest-area-geo-evidence:v1` 뒤 NUL로 고정한다.
address12개 원필드 순서·dataset/source/record/hash/Feature·정확 NDR 2D POINT4326·
Geo version/data token·called outcome·원 aware clock을 길이 구분 SHA256에 결박한다.
동일 필드라도 Airport 지문과 같지 않다. 지문 자체는 DB 출처/현재 token 권한이 아니다.

원 payload hash는32hex, 최종 Geo digest는64hex다. 정본 Rest dataclass→기존 public
native builder→실 SourceRecord/hash/key로 양성 계약을 확인했다. 외부 tzinfo는
utcoffset hook 전에 거부하고 UTC/fixed offset/정확 Asia/Seoul clock만 지원한다.
기존 Airport API/한도/Geo 모델의 의미는 그대로다.

순수 Geo 새31개+기존 Airport28+Transport native47 합집합106PASS1.61s,
strict mypy1 PASS다. 첫 import 정렬2건의 Ruff 실패는 수정 전 로그로 보존했다.
이 결과는 reader 실행·215 fit·기존 저장 projection 적격성 증거가 아니다.

## 후보 A source와 남은 실제 수용

후보 A whole RR의 미호출 source를 먼저 고정했다. 신규 Rest 전용 reader는 item256, metadata/encoded
각4MiB를 실험 후보로만 고정하고 statement3초/lock1초 및 전행 거부/EOF를 유지한다.
두 scalar(name/phones)와 나머지23개 원 의미/lineage/clock을 검증하며, 최초 mixed scalar
history는 명시 EX 진단으로 거부한다. raw7은 정본 Rest normalizer와 converter로 복원한다.
새 public SD는 `feature.read_transport_rest_snapshot_evidence(bigint)`이고
StateProcedureOwner/SECURITY DEFINER/search_path=pg_catalog로 고정한다. private shape/inventory
2개는 PUBLIC/runtime EXEC를 거부하고 public reader만 runtime에 EXEC를 준다. 기존427/430
함수·권한·인덱스는 수정하지 않고427의 bounded CASE index3개를 재사용한다.
feature/rawtable 권한 확대0이다.

W는 신규 Rest codec 및 좁은 private codec primitive만 소유한다. J는431SQL·명시
reader/evidence·전용 시험과 필요한 typed signature metadata를 소유하며 서로 파일을
되돌리지 않는다. SQL 두 source 리뷰 전 실행0이다. 실제 계량에서 A의 문제가 확인되기
전에는 chunk 후보 B를 구현하지 않는다. 등록/수집/후처리·운영 연결은 다음 단위다.

최종 source 검증 로그는 `map431-rest-geo-first-source-r2.log`
(SHAc9b0f04f2225b526f17ff795698ac164ac570c9e646c1396263ec831cccf64e9)이며
Ruff/check-format·strict mypy1·문서13PASS도 확인했다.

## decoder/SQL 검증의 현재 범위

응답 top7/item17/직접 datum51개 명세는
[열 inventory](2026-10-25-rest-reader-column-inventory.json)에 고정했다.
전체 dataset의 DB entity를 metadata부터 세고257번째부터 전행 거부한다. 각 행의
name/phones candidate·base·value source와 현재 source를 구분하며 비scalar23개는 한
원 source에 결박한다. 이번 subset은 두 scalar의 값 이력이 다르면
`mixed_scalar_lineage`로 명시 전행 거부한다. 값/시간/field provenance를 합쳐 추정하지 않는다.

SQL metadata/encoded 각4MiB, item128KiB, decoder524288 node/depth64는 실험 상한이다.
DB evidence와 W codec의1MiB durable wire/131072 token/65536 typed source node는 서로
다른 표현의 한도다. 한도를 늘렸다는 사실은 운영215 fit/CPU/RSS 수용이 아니다.
RR/read-only 및 caller statement1..3000ms/lock1..1000ms를 조회로 확인하고, decoder는
원 API 오류/취소를 알려진 EX 진단으로 숨기지 않는다.

정적 decoder+Geo와 기존 Airport 대응 합집합144PASS2.07초, 신규 migration/기존 startup·
runtime ACL52PASS2.37초, Ruff4 PASS다. 최초 clone 시험의22FAIL55PASS는 기존 Airport
문구/24개 field 기대값을 새 Rest 계약으로 고치기 전의 source 시험이며 보존했다.
SQL parser/실DB 설치·ACL/catalog/EXPLAIN·지연/heap·RSS는 아직 검증하지 않았다.
신규 migration graph는 source로 재생성했으며 실제431 schema dump를 만들어 기록하지 않았다.

남은 구현은 공개 Rest converter를 쓰는 준비/assessment와 실제 owned lab fixture다.
W codec public encode/decode를 연결할 때 native digest 재계산/입력 예산 비용도 실제 계량에
포함한다. source 두 리뷰 전 SQL 실행0이며1/15/64/128/215 및 MAX+1 whole rejection과
원 EX projection/unchanged raw·두 scalar/비scalar23·Geo의 정합 검증은 미완이다.
후보 B chunk는 A 측정으로 필요성이 확인된 다음에만 검토한다.

전체 lint+관련 정적 시험은 **504PASS/2FAIL/6SKIP·62.94초**다. 두 실패는 새3함수가
실제430 golden에 아직 없음을 검출한 정본 signature/inventory 검사다. 이 단계에서
431 dump를 꾸며 채우거나 검사를 완화하지 않았다. 두 source 리뷰 뒤 실제 fresh431
공식 oracle를 생성해 동일 검사를 다시 검증해야 한다. 원 실패 로그 SHA는
`a67edfc106a9eb4d20c1f600d534f1c3ee21f90b47bed74784c27dc867edb55d`다.
