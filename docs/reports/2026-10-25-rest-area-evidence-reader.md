# Rest431 명시 reader의 첫 source 경계

## 현재 범위

승인된 [431 설계](2026-10-25-rest-area-snapshot-profile.md)·codec1413와 명시 reader를
실제 머지된 main `5f3506a60c9289d5947d9d80be76ac044eb36dfe` 위에 합성했다.
원 WT9514의 더티4파일은 변경하지 않고 bytes 보존 사본으로만 통합했다. 새 `RestAreaGeoFacts`, 전용 migration431/SD3개와 strict decoder·caller RR/read-only
경계까지 source로 준비했다. 신규 typed SD의 최소 ACL/optional/startup signature만 연결했고
공개 converter 기반 preparation/assessment와 전용 실제 lab fixture도 source로 준비했다.
SQL 실제 설치·호출/등록·collector·운영 flag는0이며 공식 golden은 실제430을 보존한다.
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

공개 Rest converter를 쓰는 준비/assessment와 실제 owned lab fixture는 source로 추가했으며
실제 실행 수용은 아직 미완이다.
W codec public encode/decode를 연결할 때 native digest 재계산/입력 예산 비용도 실제 계량에
포함한다. source 두 리뷰 전 SQL 실행0이며1/15/64/128/215 및 MAX+1 whole rejection과
원 EX projection/unchanged raw·두 scalar/비scalar23·Geo의 정합 검증은 미완이다.
후보 B chunk는 A 측정으로 필요성이 확인된 다음에만 검토한다.

전체 lint+관련 정적 시험은 **504PASS/2FAIL/6SKIP·62.94초**다. 두 실패는 새3함수가
실제430 golden에 아직 없음을 검출한 정본 signature/inventory 검사다. 이 단계에서
431 dump를 꾸며 채우거나 검사를 완화하지 않았다. 두 source 리뷰 뒤 실제 fresh431
공식 oracle를 생성해 동일 검사를 다시 검증해야 한다. 원 실패 로그 SHA는
`a67edfc106a9eb4d20c1f600d534f1c3ee21f90b47bed74784c27dc867edb55d`다.

## 최신 source 수용과 선행 P2

T의9514 FULL은14파일과 원3 untracked를 읽고 direct assessment의 name base SQLNULL/geometry
불일치 P2로 HOLD했다(`561505b8`). 그 밖의 확정 finding은0이었다. 같은 경계의 generic row
표현 대응·name base 필수flag를 고친 reader5c78ca07와 공개 부정시험15bd1f54는
Root `dc7386b6`/T `6b012925`가 독립 수용했다. SQL 자체는 원래 해당 불일치를 거부했으므로
실제DB 우회 수정이라고 주장하지 않는다. 합법 JSON null(False+None)은 그대로 허용한다.

codec78f6는 Root `9691be5b`/J `574afce5` FULL을 carry한다. 이번 통합은 W의 새 FULL,
T의9514 FULL+후속 P2 closure의 wholebytes 보존 carry, Root의 기존 codec FULL/P2와
새 composition 검산으로 독립 적대 리뷰 범위를 정산한다. Root가 전체 reader를 새 FULL로
검토했다고 표현하지 않으며, 기존 컴포넌트 검토를 전체 repo 의미 보증으로 확장하지 않는다.

관련 순수6모듈은 **242PASS9.94초**다(`map431-before-integration-focused-unit.log/XML`).
이는 보존된 원 WT에서 실행한 결과이며 새 통합 checkpoint의 재실행 결과와 구분한다.

## 다음 owned PG 단계와 비용 분리

- 고정 source 두 리뷰와 Root 슬롯 허용 후 기존 owned scalar donor를 재사용한다.
  CPU2/RAM1536MiB/swap=RAM/PID256, exact image/earlyCID/UUID label, source·SDK·실제 import
  전후검사, phase150/parent160/cleanup15초를 기본으로 한다. 실패 원본을 보존하고
  수량/SQL/guard/시간을 근거 없이 완화하지 않는다.
- canonical fresh300→431에서 함수3 owner/SD·STABLE/search_path와 private2 EXEC 거부,
  public reader runtime EXEC만·rawtable 권한 확대0을 실제 role로 검증한다. 짧은 caller
  GUC/CREATE ACL 보존, startup/reconcile, ORM metadata-clean도 같은 bootstrap에서 확인한다.
- synthetic1/15/64/128/215를 정본 converter/loader/Geo/policy로 늘려 whole RR를 읽는다.
  complete면 전체EOF·2scalar+23non-scalar와 R1/R2/R3/clock/Geo를 대조한다. 예산 거부는
  빈 items/EOFFalse의 전체 거부로만 수용하며215 fit 성공으로 표현하지 않는다.
  실제257행(MAX256+1), 혼합scalar 이력과 잘못된GUC/권한/표현도 따로 검증한다.
- 현재 lab의 client wall/process CPU는 codec선검사·native digest·SD2회·decode/정본
  converter 비교를 포함한다. 단일SD/decoder/codec+assessment를 따로 계량하고 backend의
  정확 PID CPU tick/RSS와 cgroup memory/peak를 분리한다. 외부 SD EXPLAIN만으로 내부
  SPI 비용을 주장하지 않는다. 원래 SQL guard3초/lock1초는 유지한다.
- 마지막SQL 동결 뒤 공식430 donor를 source/head431로 결박해 fresh300→431의 실제dump를
  반복 비교한다. 예상 함수3+ACL/receipt CHECK 외 삭제/변경0을 block 대조하고 실제dump만
  golden으로 기록한다. 그 전에는 현재430 dump와 정적실패2건을 숨기지 않는다.

Rest durable 등록/claim/apply/postprocess/seal/GC·SDK0 replay·upstream 운영215 EOF·
collector 전체연결은 다음 단위이며 이번 준비 성공은 쓰기 권한이 아니다. A 실측 문제가
확인되기 전 chunk 후보B를 구현하지 않는다. 기존1412/1413 draft는 새431 main흡수 증명
전에는 닫지 않는다.

새 main 합성 후에도 같은6모듈 **242PASS10.08초**, strict mypy5소스 PASS, import4계약
PASS, 변경Python Ruff PASS, graph/check 및 docs redaction을 확인했다. 전체 tests/lint의
첫 결과370PASS/3FAIL/6SKIP 중 새 provider 문서목록 누락1건은 정본 표1줄로 수정했다.
최종은 **371PASS/2FAIL/6SKIP·34.36초**이며 남은2개는 실제431 golden 미생성에 따른
정본 signature/inventory 실패다. 검사를 완화하거나 dump를 꾸며 채우지 않았다.
