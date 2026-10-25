# 휴게소 snapshot profile 431 — 실측·구현 순서와 미완 수용 조건

[상위 공항·휴게소 설계](2026-10-25-transport-small-native-pair-design.md)와
[T-CWRITE-04](../tasks-acceptance.md#t-cwrite-04--독립-데이터셋-동시-쓰기)의 후속이다.

상태: **문서·설계 초안**. 제품·상한·flag·스키마 변경0, 이번 조사에서 새 운영조회0/PG실험0. 첫431은 전체 동시 worker가 아닌 **명시 RestArea typed profile/reader와 fit 측정** 단위로 분리한다. Airport profile/동작/한도는 유지한다. 원 r2 순수 실험 JSON의 source는 `b2d05ec2599c6e8d546307e50ee577966658246e`다. 조사 보고에 인용한 동등 revision은 `7fcf7bdef04e114e1ddefccab09905f63d75f091`, 이 문서의 부모는 `1093dd3e7e3432e79824a9f445a89fd640609434`(#1411)다. 계량·설계 판단에 사용한 아래 8개 source 파일은 세 revision에서 바이트가 같다. 원실험을 나중 revision에서 재실행했다는 뜻은 아니다. 430의 최종 CI·배포 수용과 별도이며, 431은 후속 번호 계획이지 이 PR의 migration 추가가 아니다.

## 실제 관측과 이번 순수 측정의 경계

기존 승인 RO `map-small-operating-pair-readonly-r1.json`에서 DS101 휴게소의 entity/head/current record/active primary place/stamp가 각각215, all-role link215, override0, current raw 최대 physical204B, 압축0, Geo token 쌍1종이었다(당시 조회0.1973초). 따라서 당시 current raw datum 합계는 최대43,860B라는 상한만 계산할 수 있다. 전체 subtype/주소/base/history byte, 새 upstream EOF, normalizer 권위, 현재 적격성이나 1MiB artifact fit의 증거는 아니다. 이 조사에서는 운영 원문을 새로 읽거나 출력하지 않았다.

순수 실험은 **synthetic215** `TransportRestArea`를 기존 정본 converter/native adapter로 실제 생성했다. 모든 raw/주소/전화가 실제215와 동일하다는 주장은 없다. Geo는 고정 전달 사실이며 네트워크0이다.

| 지표 | 관측 | 의미 |
| --- | ---: | --- |
| 기존 common typed budget 성공 prefix | 1..46 | 47부터 거부; 정확 primitive Geo projection 사용 |
| 기존 codec exact source preflight 성공 prefix | 1..35 | 36부터 거부; 외부 hook/fieldset 검사 포함 |
| exact source preflight의 counter-only 전체 순회 | 49,262 typed nodes / 보수 source byte 모델1,020,894B | 원 cap에서 성공했다는 뜻이 아니다 |
| 기존 wire primitive의 각 행 합 | 732,505B | 각 행은 source 검사 뒤 하나씩 직렬화; 전체 artifact 아님 |
| Rest 전용 후보 envelope의 framing 크기 | 733,671B | 동일 schema framing과64hex digest 자리만 계량; 의미·roundtrip 수용 아님 |
| 후보 wire 토큰 | 67,573 (행314×215+envelope63) | typed nodes와 별도. 65,536으로도 모자람 |
| 위 wire/converter 순수 계량 CPU/wall | 0.361 / 0.394초 | tracemalloc 없는 단일 synthetic 프로세스, DB/동시 worker 아님 |
| 해당 프로세스 RSS high-water | 115,564KiB | import/프로세스 전체 포함; incremental 입력·PG·전체서비스 peak 아님 |
| 별도 tracemalloc 계량 구간 peak | 2,835,647B | Python 추적 할당만. prefix 반복/계수 실험 CPU11.85초는 실제 한 번의 수집 시간 아님 |

정본 순수 결과는 `map-restarea215-pure-fit-w-r2.json`, wire 계량은 `map-rest215-wire-profile-w-r1.json`이다. r1 common probe는 production과 달리 Geo DTO를 common whitelist에 직접 넘긴 측정 오류로1행부터 거부했다. 원 r1을 보존하고 r2에서 codec의 실제 primitive Geo projection으로 고쳤다. 이를 제품 결함이나 실제 적격성 실패로 세지 않는다.

## 현재 구현을 label만 바꿀 수 없는 이유

- `provider_snapshot_artifact.py`는 airport kind/raw7/name-only presence와 airport domain을 명시 고정한다. 현재 public codec는 휴게소를 지원하지 않는다. 8192는 여기서 whole typed/JSON 복잡도 한도이며 kernel manifest8192와 같은 개념이 아니다. 휴게소215의3N manifest는645, 후보 최대256의3N은768이라 그 kernel 한도는 현재 병목이 아니다.
- 427 SD/decoder/assessment는 Airport domain, name 활성 정책1개와 non-name24를 요구한다. 휴게소는 name+phones 정책2개와 다른 raw7·normalizer가 필요하다. 이름과 전화의 value/validated record가 다를 수 있으므로 각각의 lineage/clock을 보존하고, 다른23필드 의미와 독립 비교해야 한다. 초기 profile은 mixed scalar history를 명시 EX로 거부해도 된다.
- 427 inventory는 base row마다 고정256B 여유부터 누적한다. base25×215×256=1,376,000B로 value·다른 관계 없이도256KiB를 넘는다. 현재 header/normalizer를 그대로 둔 전행 휴게소 SD는 성공할 수 없다. 2730이라는 수량 cap 자체가215 fit의 근거가 아니다.
- 430 등록 SQL도 Airport dataset/entity/domain을 고정하고 postprocess는 Airport domain/asset key를 요구한다. reader나 codec만 추가한 뒤 generic 등록으로 우회하면 안 된다. Geo 재사용/현재 정책·claim·strict closure/capture/atomic apply와 원 관측 후처리 계약도 그대로 필요하다.
- old409 저장 projection은 새 normalizer/base가 검증됐다는 뜻이 아니다. 별도 EX bootstrap의 실제 current head·정본 raw roundtrip·모든 저장 의미·Geo 사실을 검증해 활성화해야 한다. 최초 새 worker는 unchanged raw만 지원하며 변경 raw/identity·시설/주소·Geo drift는 EX다.

정본 입력은 `TransportRestArea`와 기존 `rest_area_natural_key`/converter를 직접 재사용한다.
raw7은 `natural_key`, `name`, `route_name`, `direction`, `lon`, `lat`,
`phone_number`이고 normalizer는 `transport-rest-area-name-phones-v1`이다.
presence는 `core.name`과 `place.phones`를 명시하며 null/공백 전화는 공급자의 명시 `[]`로
해석한다. natural key에 들어가는 정규화 이름·노선·방향이 바뀌면 다른 identity이므로
scalar SH 갱신으로 숨기지 않는다. 빈 이름 skip도 upstream 전체 관측/삭제 권위와 구분한다.

## 첫431의 작은 범위와 비교할 유한 후보

첫 checkpoint는 **신규 RestArea profile codec/decoder·SD/순수 assessment 및 소유 측정 fixture**까지만 둔다. Rest collector 분기/등록 확대/운영 활성화는 다음 단위로 남긴다. 공통 primitive를 추출한다면 기존 Airport 함수 signature/기본 cap은 그대로인 wrapper로 유지하고 exact DTO whitelist/외부 hook 선거부도 유지한다. 임의 provider parameter나 SDK façade를 추가하지 않는다.

비교 후보 A는 간단한 whole RR reader다. 최대 item256, typed source node65,536, wire token131,072, source byte 모델2MiB를 **Rest 명시 profile에 한정한 실험 후보**로 둔다. durable artifact wire는 우선 기존1MiB, depth64, apply30초/reader3초·lock1초를 유지한다. source2MiB는 payload2MiB 보관 허용이 아니다. 이 synthetic의 기본 wire token은256행에서도80,447이므로131,072 후보에는 근거가 있지만 실제 전화/주소/fieldset·depth/byte의 전체 관측 전 확정하지 않는다. 한도가 넘으면 전행 거부하며 일부 성공을 반환하지 않는다.

reader A의 metadata/encoded 총량은 각각4MiB를 초기 **측정 후보**로 두고215가 거부되면 실제 어느 budget이 얼마에서 넘었는지 먼저 기록한다. descriptor 하한만1.376MB인 상황에서 최소한 무의미한256KiB 반복을 피하는 후보이며, 실제 peak/정본 동등성·server deadline 측정 없이 운영 cap으로 채택하지 않는다. 기존428/430 capture 지문/한도를 reader cap과 혼동해 자동 증대하지 않는다.

비교 후보 B는 256KiB metadata/1MiB encoded **각 chunk**를 유지하는 requested-target≤16 RR reader다. 전체 key 집합의 metadata-first MAX+1/EOF를 먼저 검증하고 모든 chunk를 **같은 RR planning snapshot**에서 읽는다. 전체 metadata/encoded 합계에도 A와 같은 유한 whole budget을 적용하고 모두 검증한 뒤 하나의 apply만 허용한다. chunk는 authoritative partial success나 분할 commit 경계가 아니다. apply 잠금 뒤 RC에서는 chunk별 statement snapshot 차이를 숨기지 않는다. 모든 fresh chunk를 한 SQL statement의 STABLE 호출로 읽거나, 획득한 전체 P/parent/target 잠금 아래 authorized writer가 배제된다는 별도 증거가 필요하다. 첫 DML 전에 모든 fresh chunk의 검증을 마친다.

A는 코드/왕복/감사 경계가 단순하고, B는 일시 JSON/배열 peak를 낮출 여지가 있지만 전체 normalized evidence를 보관하면 최종 heap은 저절로 줄지 않는다. 먼저 A의 실제 RSS/CPU가 충분한지 측정하고, B가 유의미하게 낮춘다는 수치가 있을 때 선택한다. 이번 단계에서 compact proof/digest 아키텍처를 새로 만들 이유는 없다.

## 아직 없는 PG 수치와 첫 측정 fixture

현재 **휴게소215 PG reader CPU/RSS/plan 수치는 없다**. 위 pure RSS를 PG 비용으로 대체하지 않는다. 첫431 소유 lab에서 정본 loader+EX bootstrap으로 synthetic R1을 만들고 N1/15/64/128/215 및 limit+1을 비교한다. 새 source/DDL는 정확 reviewer pin으로 고정하고 cached2CPU/1536MiB/PID256/고유CID·volume 정리와 prep deadline을 유지한다. 임의 운영 DDL·runtime raw SELECT/GRANT는 없다.

A/B 같은 dataset/기록/clock/Geo·완전한25base/2scalar lineage에서 reader를 각각3회 측정한다. 원4집계 동등성, 실제 compressed/physical·encoded/typed nodes·wire tokens, wall/PG CPU, Python/PG backend RSS와 cgroup memory high-water(bootstrap 포함 범위 분리), 정상/실패 budget reason, unrelated history 존재 시 CASE index 접근을 보존한다. FunctionScan/미러 EXPLAIN을 실제 내부 SPI 비용이라고 부르지 않는다. 전체 fixture 준비 비용과 읽기 비용을 분리한다. 이 수치·실제 승인 RO projection fit 이전에 값 확정이나215 운영 fit/두 worker 가능을 주장하지 않는다.

## 주기·7일 보관·quota 계산

정본 schedule은 **휴게소 주간 월요일04:20 KST(`20 4 * * 1`)**, **공항 월간4일05:05 KST(`5 5 4 * *`)**다. 둘 다 월간이라고 가정하지 않는다. GC는 terminal root+child, 정상 Dagster terminal, 미격리, 만료 lease, 관련 시각 중 최신값이 **엄격히7일보다 오래된 경우**만 삭제하고 최대16행이다. running/unsettled/quarantined는 안전하게 보존한다.

등록 예약은 `payload_bytes + context_bytes +8192`다. durable payload≤1,048,576B/context≤8192B를 유지하면 snapshot당 최악 예약은1,064,960B다. reader 임시4MiB나 source 예산2MiB를 durable payload 비용으로 잘못 계산하지 않는다.

휴게소 새 runner도 **SDK0 부재+verified runtime일 때 fetch 전 GC16을 주간마다1회** 연결한다는 조건에서, 정상 주간 run은 다음 주 같은 시각에 이전 완료가 아직7일보다 오래되지 않았을 수 있어 **2개 settled slot**이 필요하다. 공항은 다음 월간 run 전 정상 완료 artifact가 오래되어 수집되므로 nominal1개다. 두 dataset 최소 nominal은3행/최악3,194,880B(약3.047MiB), 휴게소 DS는2행/2,129,920B다. 현재 fixture의4MiB/16rows는 운영 설정의 근거가 아니다.

휴게소에 GC 호출을 연결하지 않고 현재 공항의 월간 호출만 이용하면 한 달 사이 주간 artifact가 쌓이므로 위2행 계산은 성립하지 않는다. 더구나 같은 run의 SDK0 retry는 추가 예약0이지만 새 root로 재실행하면 별도 예약을 소비한다. 운영 DS/global row/byte quota는 `nominal retained + 허용 new-root burst + 이미 존재하는 protected unsettled reservations`를 둘 다 커버해야 한다. 예를 들어 추가 burst1개를 각 dataset에 허용하면 nominal3+burst2=5slot/최악5,324,800B이며 **이것은 설명용 산식이지 자동 확대 설정이 아니다**. global은 두 DS 합계와 기존 사용량을 함께 감당해야 한다.

unsettled/격리 root가 무제한 남으면 어떤 유한 quota도 영구 가용성을 보장할 수 없다. 정본 terminal 정산·quota 사용량 관측·명시 운영 한도를 activation 수용 조건으로 남긴다. quota 부족을 EX/refetch 성공이나 무한 GC drain/retry로 바꾸지 않는다. 월간/주간 nominal 유입은 GC16보다 적지만 장기 burst/backlog가 있으면 별도 관리 경계가 필요하다.

## 권장 다음 순서

1. 430을 먼저 닫고 첫431을 Rest 전용 codec/reader/fit lab로 작게 연다. 값은 위 후보로 비교하며 실제 한계는 미확정이다.
2. synthetic215의 A/B PG 메모리·CPU/한계와 실제 승인 RO projection의 typed/wire fit를 확인한다. old normalizer baseline은 EX bootstrap으로만 만든다.
3. 결과가 성립할 때만 Rest 도메인 등록·observation/postprocess·runtime receipt·weekly SDK0 runner와 GC 연결을 다음 작은 단위로 추가한다. 기존 Airport 경로는 그대로 둔다.
4. 최종 실제 두 worker의 독립 DS 적용 구간 overlap/PID/TX/DML, 같은 Feature 충돌/EX 충돌, 원 side effect·취소·unknown commit·동일 run 재개와 공개 읽기까지 별도 수용한다. 이번 후보 크기 측정이나 Airport caller2 PASS로 완료 처리하지 않는다.

## 구현 단위와 파일 소유 경계

현재 PR은 이 보고서·T-CWRITE-04 추가절·journal/resume prefix 네 문서만 소유한다.
두 독립 설계 리뷰 뒤 다음 순서로 작은 source checkpoint를 만든다. 아래 경로는
**다음 구현의 제안 경계**이며 아직 파일·migration·설정을 만들지 않았다.

| 단위 | 제안 소유 파일/변경 | 완료 증거와 남겨 둘 경계 |
| --- | --- | --- |
| R431-1 측정용 typed profile | 신규 `src/kortravelmap/infra/rest_area_snapshot_artifact.py`, `tests/unit/test_rest_area_snapshot_artifact.py` | 정본 Rest DTO/raw7/name+phones·fieldset/default clock·Geo None/empty·Any exact-type 선검사·명시 pins/domain 보존. 215 lossless roundtrip과 byte/node/token 초과 전행 거부. Airport codec 공개 API·기본 상한 불변; 불가 타입은 EX 진단. |
| R431-2 최소 PG reader/lab | 신규 `alembic/versions/431_transport_rest_reader.py` 및 `_431_transport_rest_evidence_*.sql`, 신규 `src/kortravelmap/infra/transport_rest_evidence_reader.py`·`transport_rest_evidence.py`, `tests/integration/test_transport_rest_evidence_reader.py`·전용 unit | 430 위 설치·정확 signature/owner/ACL·원 공식 oracle/metadata 절차, 전행 EOF/MAX+1·2scalar/나머지23 의미·Geo/lineage 검증. 먼저 아래 A/B 비용 비교를 수행하고 cap을 결정한다. 새 SQL은 이 단계 source 두 리뷰 전 실행0; 번호/이름은 그때 최종 예약 확인. |
| R431-3 실측 선택 | 전용 lab harness·이 보고서의 결과절 | 같은 입력의 A/B 3표본, 실제 plan/CPU/RSS·서버 deadline·원4집계 동등성·거부경계. 운영 원문은 repo에 저장하지 않는다. A가 충분하면 chunk 복잡도를 추가하지 않는다. |
| R431-4 도메인 연결 | 후속 별도 소유 배정: 명시 Rest 등록/관측/후처리/runtime·client transaction 함수·scheduled asset 분기 | Rest-only domain과 실제 설치 pins, weekly 신규 입력 GC1회, SDK0 same-run 재개·unknown commit·supersession·원 clock/발견사항/cursor. 기존 Airport SQL/profile·queue legacy는 그대로. 431 reader 성공만으로 이 단위를 완료하지 않는다. |
| R431-5 운영 수용 | 후속 두 worker/공개 읽기·복구 시험과 배포 기록 | 아래 해제 조건 전부. 운영 flag·quota 변경은 실제 입력 크기와 자원 계량 뒤 명시 검토한다. |

공통화를 하더라도 `core/feature_projection.py`/기존 codec/기존427·428·430
SQL을 각 작업자가 동시에 수정하지 않는다. 중복 없는 최소 primitive 추출이 필요하면
기존 소유자와 별도 delta로 배정하고 Airport 전체 의미 동등성과 공개 signature를 검증한다.
기존 provider SDK/converter를 재구현하거나 raw table runtime SELECT 권한을 넓히지 않는다.

## 실패·원자성·운영 해제 조건

다음은 T-CWRITE-04의 세부 후속이며 모두 미완이다. 이 문서의 설계 리뷰나
synthetic215 크기 계량으로 상위 체크박스를 완료하지 않는다.

- [ ] 원 입력의 전체 EOF를 증명한 뒤 immutable artifact/context를 정확 root/member/
  dataset·normalizer·code/SDK/Geo/clock pins에 묶는다. DB current-head EOF와 upstream
  EOF는 구분하며, 215라는 과거 행 수를 새 upstream 완전성으로 쓰지 않는다.
- [ ] EX bootstrap으로 old409 저장 의미·R1/R2별 name/phones lineage·나머지23 의미·
  Geo claim/token/좌표/address와 활성 정책/epoch를 검증한다. 최초 unchanged raw만 지원하고
  changed raw·identity·시설/주소/Geo 변경은 등록 전 같은 입력의 EX로 보낸다.
- [ ] 계획은 RR read-only, fresh 재검증은 실제 잠금 뒤 하나의 일관된 capture 경계다.
  현재430에서 한 commit인 범위는 apply·retire·kernel finish/result receipt다.
  이어지는 postprocess와 child seal/root finalize는 별도 transaction이다. 상위
  T-CWRITE-04의 일반 snapshot 적재·retire·최종 seal 한 commit 조건은 여전히 OPEN이며,
  현재 분리 TX의 구현/재개 성공으로 닫지 않는다. chunk commit/부분 완료도 허용하지 않는다.
  모든 대상/parent/strict closure·manifest/epoch를 DML 전에 재검증하고 stale이면 전체
  bounded 재계획한다. 여러 RC SELECT를 같은 transaction이라는 이유로 같은 snapshot이라 부르지 않는다.
- [ ] 두 실제 worker의 서로 다른 DS source/head/lineage/finish DML 중첩을 PID/TX와
  관측된 blocker로 증명한다. unchanged raw도 실제 apply를 실행하며 skip으로 겹침을 만들지 않는다.
  공유 Feature 충돌은 정확 대상에서 직렬화하고 역순·동일 identity 최초 생성·redirect/link
  변경·EX writer와의 경합에서도 공개값/Geo/lineage가 같다.
- [ ] 고유 fence/generation/attempt/owner와 부모 우선 잠금 순서를 보존한다.
  worker 사망·취소·lease 만료·unknown commit 뒤 같은 run은 SDK0 원 artifact/결과로
  복구하고, 새 run은 별도 identity다. stale fence/이미 superseded 관측은 원 오류 또는
  공식 실패로 정산한다. 등록 후 implicit EX/refetch, 원 counter 재계산, 무한 retry는 없다.
- [ ] 원 validation/GeoStats/clock·idempotent finding/sync/stale close와 완료 receipt를
  같은 fenced 후처리 transaction으로 증명하고 재개가 중복 occurrence/옛 cursor 덮어쓰기를 만들지 않는다.
  보호된 unsettled/격리 row를 GC하거나 quota 초과를 성공으로 바꾸지 않는다.
- [ ] 주간/월간 schedule, 7일 strict retention·GC16 호출과 DS/global row/byte quota를
  실제 사용량·허용 new-root burst·terminal 정산으로 검증한다. 실제 artifact ≤1MiB fit,
  PG/Python 전체 peak·CPU·deadline, schema 설치/권한/metadata/공식 oracle·CI,
  실제 서비스/UI 공개 읽기와 배포 generation을 확인한 뒤에만 Rest opt-in을 별도 승인한다.

## 증거와 재현 출처

아래 JSON은 비공개 감사 디렉터리의 고정 원장이다. 원천 payload는 포함해 출력하거나
repo에 복사하지 않았으며, 경로 이름과 SHA는 사실 대조용이다. 수치의 source 세대는
본문처럼 분리한다. 순수 wire 후보 framing은 유효한 등록 artifact가 아니다.

| 원장 | SHA-256 |
| --- | --- |
| `map-small-operating-pair-readonly-r1.json` | `c225fd05794c659f492f58a186a667dc1d3668a35698ba757d19aae8d530a6f1` |
| `map-restarea215-pure-fit-w-r1.json` | `6286c1cfb3e97bf2400dbe9d6931611bae5e4521e53c91729512fe6c71454c74` |
| `map-restarea215-pure-fit-w-r2.json` | `0b9b42cbdc13a93b994ec250325fdce0adbe44bd72ad725f2662cee2ad967987` |
| `map-rest215-wire-profile-w-r1.json` | `2c7cfc2df71c1421098dfae227ee7de4ef64e61ecb97114470cd1a46e95d0cca` |
| `map-restarea431-followup-w-r1-source-investigation.json` | `f1e93f7d726742330d17a83de064e07b894200a19776dfc69463e16fa20b56db` |

원실험 b2d05ec2·조사 인용7fcf·부모1093에서 동일함을 대조한 파일:

- `src/kortravelmap/infra/provider_snapshot_artifact.py`
- `src/kortravelmap/core/feature_projection.py`
- `src/kortravelmap/providers/kor_travel_transport_native.py`
- `src/kortravelmap/providers/kor_travel_transport_evidence.py`
- `alembic/versions/_427_transport_airport_evidence_inventory.sql`
- `alembic/versions/_430_snapshot_registration.sql`
- `alembic/versions/_430_snapshot_terminal_gc.sql`
- `packages/kor-travel-map-dagster/src/kortravelmap/dagster/schedules.py`
