# Transport 장소 두 dataset의 첫 SH 수집 후보

상태: 설계 초안, 구현·운영 활성화 수용 아님. 기존 T-CWRITE-04/06/07 해제 조건을 줄이지 않는다.

## 확인한 작은 후보와 선택 이유

n150의 기존 schema409를 read-only/statement3초/lock1초/동일 CID·image 전후 확인 아래 읽었다. 2026-10-25 관측은 `map-small-operating-pair-readonly-r1.json` SHA c225fd05794c659f492f58a186a667dc1d3668a35698ba757d19aae8d530a6f1 이다. 운영 접속값·원문 장소 자료는 문서에 싣지 않는다.

| dataset | entity/head/record/primary active place/stamp | 모든 역할 link행 | any override | 최대 current raw binary | 압축 raw |
| --- | ---: | ---: | ---: | ---: | ---: |
| transport_airports | 각각15 | 15 | 0 | 215B | 0 |
| transport_rest_areas | 각각215 | 215 | 0 | 204B | 0 |
| knps_visitor_centers(대안) | 각각71 | 71 | 0 | 686B | 0 |

각 dataset의 stamp Geo token 쌍은 한 종류였다. 위 수치는 source 물리 경로/원문 전체 합·DTO1MiB·reader256KiB 예산 통과, 최신 upstream EOF, old normalizer 권위를 증명하지 않는다. 별도 전체 입력 실측이 필요하다. knps_shelters는0으로 제외한다. Heritage4,279/MCST9,494의 대용량 지원은 그대로 후속이며 작은 pair를 전 국민 데이터 완료라고 부르지 않는다.

첫 pair는 공항+휴게소가 유리하다. 두 converter와 typed input은 이미 Map에 있고 Transport service REST를 쓴다. 공항 자연키는 IATA, 휴게소는 기존 name/route_name/direction 정규화 합성키다. 새역할/원천adapter/Geo API client를 만들지 않는다. 휴게소 이름 변경으로 key가 바뀌면 SH 이름 수정으로 다루지 않고 EX에서 새 identity/retire를 처리한다.

## 가장 작은 provider 계약

1. Map의 `airports_to_bundles`/`rest_areas_to_bundles`를 그대로 정본으로 쓴다. HTTP는 기존 fetcher를 재사용한다. 공항은 단일 응답 items 전체와 nonempty를 검사하지만 collection/freshness 원장은 읽지 않는다. 휴게소는 cursor EOF·cycle/페이지 상한·각 페이지 collection의 current를 검사하지만 페이지 사이 같은 upstream snapshot 세대를 고정하지 않는다. 현재 두 계약을 동일한 freshness/전체세대 증명이라고 부르지 않는다. 완전성 관측과 sealed artifact의 권위를 각각 명시하며 누락·세대혼합을 배제하지 못하면 SH 운영 수용은 OPEN이다.
2. 새 순수 저장 projection 복원은 기존 `TransportAirport`/`TransportRestArea` dataclass 입력을 복원해 위 converter를 다시 호출한다. 허용 raw key는 converter가 실제 저장하는 각7개 고정 집합, 값은 bounded string/null뿐이다. 알 수 없는 key·타입·부정확한 좌표·hash/key/domain/identity roundtrip 차이는 unsupported/EX이다. parser가 잃어버린 원천 필드를 임의 보완하지 않는다.
3. 새 normalizer revision의 presence는 공항 `core.name`, 휴게소 `core.name`·`place.phones`만 명시한다. 휴게소 converter가 받은 모든 적격 행에서 phone_number의 null/빈값/정규화 결과 없는 값은 phones=[]로 명시 공급된다. 필드가 공급되지 않은 입력과 구분한다. coordinate/address/facility/기타 필드는 SH 갱신 권위가 없으며 전체 의미 비교에서 동일해야 한다. 기존 `_provider_field_patch_payload`/원field registry를 재정의하지 않는다.
4. R1 Geo evidence는 실제 저장 stamp의 data/version token·주소·좌표·stamped_at 지문에 결박한다. R2의 token/address/coord가 같고 기존 Geo reuse가 실제 reverse 결과를 재사용했다고 증명된 경우만 SH다. 현재 reuse SQL은 current source record의 raw_payload_hash도 입력과 같아야 한다. 따라서 최초 worker 경로는 unchanged raw 재관측으로 한정한다. 이름/전화 변경은 raw hash를 바꾸므로 같은 좌표/token만으로 기존 reuse를 통과한 것처럼 처리하지 않고 EX로 남긴다. 변경 raw의 Geo 재사용 권위 확대는 별도 계약·반증·리뷰가 필요하다. token 변경/누락/stamp 불일치/주소·좌표 변경은 EX이다. 조용히 Geo를 생략하거나 같은 token을 현재 전역 GUC에 캐시하지 않는다.
5. 과거 normalizer는 기존409 데이터에 새 revision이 기록되어 있다고 가정하지 않는다. 최초 baseline은 **새 정본 converter로 R1을 재구성해 모든 저장 의미와 비교한 EX bootstrap**으로만 만든다. 검증된 current source/head/Feature/base/policy/Geo epoch를 같은 EX transaction에서 seed하고 new revision을 기록한다. old row가 있다는 이유만으로 stamp/revision을 만들어 SH 적격으로 승격하지 않는다.
6. 현재 bundle도 같은 converter로 roundtrip하고 full typed projection을 비교한다. 실제 공급 scalar 외 의미·행/역할·claim/Geo/file/admin evidence/side effect가 바뀌면 EX로 재계획한다. known alias는 기존 canonical identity claim을 통해 같은 기존 Feature로 결박할 때만 처리한다. 단순히 Feature ID를 지우고 비교했다고 alias를 승인하지 않는다.

## 메모리·SQL reader와 whole snapshot

- 기존 전체 typed1MiB/최대2730/manifest8192/30초 적용 한도를 유지한다. MAX+1 순회·세부 node/depth/byte 검사 후 직렬화, mutable raw의 단독 입력 소유, subtype/metadata-first/압축·특수 numeric 거부 등 기존 reader와 동등한 한계를 사용한다.
- 국가유산 public reader의 provider/normalizer/raw/policy 검사를 넓혀 다른 provider를 몰래 통과시키지 않는다. 실제 공통 metadata/shape 도우미를 재사용하는 명시 Transport reader를 별도로 두고, provider·dataset·normalizer·field set·전체 EOF 계약을 엄격히 묶는다. 최초 baseline(정책 없음)용 evidence와 정책 활성 후 evidence의 권위를 구분한다.
- reader256KiB 합계나 final evidence1MiB가 넘으면 bounded location/key chunk + 하나의 RR planning snapshot에서 수집할 수 있지만, 이 자체가 whole input 적격이나 마지막 apply 분할 commit 허용은 아니다. 실제 fit 관측 전 코드가 전체 성공을 가정하지 않는다.
- 원 canonical capture hash는 바꾸지 않는다. 전체 dataset의 현재 entity/head/record/all-role link/Feature/subtype/override를 먼저 metadata/shape/encoded budget으로 검사하고 동일 hash를 계산한다. 대상 key만 맞고 남은 entity를 무시하는 retire0 판정은 금지한다.

## collector와 복구의 해제 조건

새 eligibility·reader만으로 기존 asset에 SH를 켜지 않는다. 초기 flag OFF다. 실제 연결은 다음 조건을 함께 충족한다.

- 424의 P→L tracking prefix는 SER 유지 선행 단계다. 이것만으로 gate 대기 뒤 fresh capture를 얻었다고 하지 않는다. RC finalization은 strict SH target/phantom/raw/typed/publicSD closure와 whole capture guard가 함께 수용된 뒤 전환한다.
- 실제 source/head/Feature target 밖 DML, 새 entity/link, missing/bareSH, catalog/override mutation을 DB가 거부한다. all-participant parent SHARE와 own ops scope 잠금은 해당 guard와 한 변경집합이다.
- plan은 immutable 최종 입력 + 실제 provider EOF + 정책/Geo/claim epoch에 결박한다. apply는 같은 전체 입력 한 transaction에 source/head/candidate/winner/retire0/capture/finish와 durable load result14·원 ETL findings/observation/sync 의무를 원자 저장한다.
- child seal/root terminal은 각 자기 fresh bounded capture와 동일 P→L 순서다. load/child/root가 별도 transaction인 사실은 별도 명시하고, T-CWRITE04의 최종1commit 요구를 임의 완료 처리하지 않는다.
- 불확실 commit/worker death는 같은 frozen member/artifact domain을 먼저 조회해 과거 성공을 복원한다. finished면 재수집/SDK/DML0이며 generation/executor fence·outer ETL/sync 재개까지 검증한다. 현재 Dagster started_at을 executor lease로 부르지 않는다.

## 구현·시험 단위

A. 작은 pair 전체 binary/shape/typed input 크기와 source roundtrip을 read-only로 조사, 원문은 git에 저장하지 않고 요약만 기록.
B. 공유 typed-budget/의미 비교가 실제 동일할 때만 작은 공통 helper로 추출하고 국가유산 기존 동작을 전수 회귀. Transport pure projection/presence/eligibility를 단독 시험하고 reader는 별도 owner/ACL/head migration·실제 PG로 수용.
C. strict writer/capture/RC coordinator/recovery를 닫고 EX bootstrap을 격리 DB에서 재현. 실제 provider snapshot 두 개의 same-input EX/SH 결과·모든 side effect 동등을 확인.
D. 두 실제 worker의 적용 구간이 겹치는 PID/transaction/시간 증거, 같은 Feature 충돌 직렬화, 서로 다른 dataset 비차단, 취소·lock timeout·죽은 connection·unknown commit·같은 run 재개, pool1/GUC/P/L/role 복원, 실제 UI/서비스 읽기를 수용 후 운영 배포.
E. 공항·휴게소의 운영 결과를 충분히 관측한 뒤 domain SQL은 Map에 남기고 bounded wait/retry/lease/generation/pointer publication 중 다중 소비자 공통점만 Common→Weather/Transport로 전파한다. 취소된 별도 상태 export 운영 활성화는 재개하지 않는다.

본 초안은 큰 원자 transaction/복구를 작은 scalar patch로 대체하지 않는다. 작은 pair가 모든 gate를 통과하면 첫 운영 검증을 시작할 수 있다는 후보 설계다.


## 실제 source 대조와 초기 구현 경계

검토 기준은 C1 최종 `4fe449ab30217b4edd8dd57dc92810de0fd5400a`의 converter·fetcher·asset·ADR-115와 현재 task다. 이 설계 검토는 repository 제품 변경·PG·HTTP·운영 변경 없이 작성했다. raw7 복원은 upstream export DTO 전체를 복원한다는 뜻이 아니다.

| 실제 source | 확인한 의미와 구현 제한 |
| --- | --- |
| `providers/krairport.py::_airport_to_bundle` | raw7=`code,name_korean,name_english,icao_code,municipality,latitude,longitude`. 이름은 한국어 normalize→영문 원문→code 순서다. facility_info에는 non-null ICAO·영문명이 남으므로 영문 변경을 단순 name 변화로 무조건 허용하지 않는다. 좌표 reverse가 UUID의 bjd_code와 address에 영향을 준다. |
| `providers/krex.py::_rest_area_item_to_bundle`, `_rest_area_natural_key` | raw7=`natural_key,name,route_name,direction,lon,lat,phone_number`. 키는 각 성분 strip/lower 후 `::` 결합이며 공급 natural_key와 일치해야 한다. 공백뿐인 name은 converter가 skip한다. skip·중복·동일키 충돌은 EOF row 수와 별도 감사하고 그대로 성공 seal하지 않는다. facility_info의 direction/highway_name도 비교 대상이다. |
| `providers/kor_travel_transport.py` | dataclass는 converter raw7보다 넓다. RestArea의 시설 bool3와 raw, Airport.raw는 converter가 쓰지 않는다. R1 복원 시 이 미사용 필드는 명시 None/빈 mapping으로 채운 projection-only 입력이며 upstream 원본·freshness·outer ETL 관측을 재구성한 것으로 세지 않는다. raw 좌표 문자열→float→converter raw 문자열/hash의 정확한 roundtrip을 입증하고 손실이면 EX다. |
| `dagster/assets.py::run_feature_place_transport_rest_areas` | 현재 전체 `_record_list`→Geo 변환→`_load(authoritative_snapshot_complete=True)`다. 새 SH 분기는 MAX+1·총 byte/node/depth 제한을 입력 전체에 먼저 적용해야 하며 기존 무제한 list를 bounded라고 부르지 않는다. |
| `dagster/assets.py::run_feature_place_transport_airports` | 현재 batch_size100 변환을 `_load_snapshot_batches`로 소진한다. batch 경계는 commit 경계가 아니다. 하나의 전체 immutable artifact/EOF/예산/claim을 만든 뒤 한 apply TX로 유지한다. |
| `infra/feature_geocode_reuse.py::_READ_REUSABLE_SQL`, `dagster/geo_reuse.py` | 현재 raw hash 동일, active canonical claim, 같은 float8 좌표, stamp called/current data token, 주소 관련 active override 없음이 모두 필요하다. 같은 좌표를 공유하는 모든 행이 같은 저장 address를 내야 재사용한다. 저장값만 썼어도 run Geo recheck와 관측 통계는 유지한다. 최적화 reader 오류의 None fallback을 새 권한 evidence로 인정하지 않는다. |

공항은 name-only presence, 휴게소는 name+phones presence의 새 명시 revision을 분리한다. rest-area key에 포함된 name/route/direction 변경은 새 identity/retire 후보이며 최초 SH 범위가 아니다. 같은 strip/lower 키를 유지하는 표시만의 변화도 raw가 바뀌면 현재 Geo reuse 제한으로 EX다. 공항 영문 fallback·ICAO/도시명·좌표·facility/주소 변화도 전체 typed 비교를 거쳐야 한다.

정본 UUID, detail.feature_id, source link.feature_id, source record key, provider/dataset/entity type/id, current canonical head와 hash를 각각 확인한다. alias는 실제 claim으로 해석한 동일 target에만 결박한다. Feature ID나 source_record_key를 비교에서 무조건 지우지 않는다. current head가 입력 key와 다르면 기존 scalar helper의 older-input 성공 반환을 전체 SH 성공으로 승격하지 않고 전체 rollback/EX 재계획한다.

R1은 저장 provider projection·필드별 source/clock/revision 증거다. 현재 effective Feature에 operator override가 숨어 있으면 그것을 provider R1로 채택하지 않는다. 초기 관측 override0은 미래 권한이 아니다. 예상 밖 정책 fieldset/다른 참여자/secondary·inactive link, candidate/header 변화는 전수 closure를 증명하거나 전체 EX로 거부한다. initial single-source subset으로 닫아도 all-role 검사를 생략하지 않는다.

## 최소 구현 순서와 go/no-go

1. **순수 기반과 입력 실측부터**: 기존 bounded FeatureBundle 검사·canonical meaning 비교 중 계약이 같은 부분만 작은 공통 helper로 추출한다. Heritage의 exact DTO identity/Enum/iterator 예산과 이전 반례를 전부 보존하며, Transport dataclass 임의 serializer 허용으로 whitelist를 넓히지 않는다. 실제 source raw7·typed snapshot·현재 전 필드 clock/lineage evidence·envelope를 별개로 계량한다. 공항15/휴게소215가 모두 1MiB typed artifact와 manifest8192 안이라는 증거는 아직 없다.
2. **Transport 순수 native 계약**: 기존 두 converter 재호출/R1 복원/presence/known-ineligible reason만 추가한다. serializer 전에 raw7 string/null·좌표 ASCII/길이/유한·범위·쌍/키·hash를 제한하고 전체 DTO 예산을 지킨다. 빈값 전화의 명시 제거, fallback 이름, facility 변경, identity/key 위조, 빈 이름 skip, duplicate key, mutable input 소유, older input 반례가 필요하다. 여기까지는 새 DB 권한·worker·운영 SH가 없다.
3. **읽기 evidence와 EX baseline**: explicit Transport SD는 provider/dataset/revision/fieldsets를 분리하고 기존 안전한 metadata-first helper를 재사용한다. 전 가변열의 compression/physical/encoded/row/total cap을 검사하며 STABLE snapshot에서 양측 join-key CASE guard와 내부 (tableoid,ctid)만 쓴다. 현재 Heritage reader의 synthetic fixture는 N17만 성공한 적이 있으므로 같은 전체 evidence를 215개까지 한 번에 담을 수 있다고 가정하지 않는다. EX bootstrap은 실제 target head schema 배포 뒤, canonical EX·global·epoch와 입력 전체 guard 아래 fresh capture와 정본 stored projection 검증을 수행한다. old409/unknown normalizer를 label-only UPDATE로 승격하지 않는다.
4. **크기 미달 시 멈추는 계획 경계**: evidence256KiB/encoded1MiB를 넘으면 현재 foundation으로는 전체 EX다. bounded RR reader chunk를 검토할 수 있지만 부분 적격/부분 DML/부분 commit은 금지한다. 전체 입력·manifest·retire0·closure·정책/Geo/claim epoch를 먼저 묶고, 잠금 뒤 RC 새 statement에서 모두 재검증해야 한다. 중간 evidence를 고정폭 digest로 접어 메모리를 줄이는 표현은 typed artifact 제한과 별개 설계·반증·두 리뷰가 필요하다. 아직 없는 compact proof를 구현된 것으로 가정하지 않는다. fit 실증 또는 이 설계 수용 전에 휴게소 SH wrapper를 바로 붙이지 않는다.
5. **strict write/coordinator·복구 후 두 worker**: 현재 424 prefix나 scalar batch만으로는 whole snapshot SH를 수행할 수 없다. target 밖 raw I/U/D·새 phantom link/entity·catalog/override·missing/bare SH를 막는 전체 DB closure, own-scope/participant locks, RC fresh full capture, durable load14와 outer ETL findings/observation/sync, frozen member artifact/epoch generation recovery를 같은 명시 gate로 닫는다. load/child/root 각 TX의 차이를 남긴다. Manager 웹·API와 CLI는 모두 유지하며 어느 진입도 이 gate를 우회하지 않는다.
6. **격리 실제 두 worker 수용**: 최초 unchanged raw 재관측도 completed receipt replay나 local no-op으로 apply를 건너뛰지 않는다. 새 유효 attempt에서 source/currenthead/lineage/candidate/winner/stamp/finish의 실제 수행 SQL·물리 PID·TX·DML 구간을 각각 기록하고 독립 dataset 두 적용 구간이 겹침을 관측한다. 같은 Feature는 직렬화되고 EX writer는 둘 다와 충돌해야 한다. 두 독립 pool1, bounded deadline/fresh retry/rollback, connection kill·cancel·unknown commit·새 generation·동일 frozen artifact 복구까지 확인한다. durable completed replay만 별도로 DML 생략을 검증한다. 동일 입력 EX/SH 결과와 모든 side effect·공개 읽기 일치 후에만 운영 opt-in을 검토한다.

현재 go/no-go는 **후보 선택·순수 계약 설계 진행 가능**, **실제 두 dataset SH 활성화 불가**다. 첫 두worker의 unchanged raw 범위를 이름/전화 변경 성공으로 보고하지 않는다. ADR-115 §2/6/7/8/9와 T-CWRITE-04/06/07의 whole snapshot 원자성·전수 writer 전환·복구·총 CPU/RAM/실 worker 해제 조건은 계속 OPEN이다. counts·최대 raw 한 행·작은 metadata 조회의 성공은 eligibility나 whole capture/RC/durable 완성을 대신하지 않는다.
