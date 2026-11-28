# ADR-128 — 등산로는 원천 구간이 아니라 구간을 이은 "등산 코스"를 Feature로 싣는다

- 상태: proposed (2026-11-27, 구현 PR과 함께. prod 재적재 뒤 코스 수·길이 분포·PinVi 일정 추가를 실측하면 accepted)
- 날짜: 2026-11-27
- 결정자: Claude(설계·구현), 소유자 지시("숲길 구간을 코스로 묶고 PinVi에서 코스를 일정에 추가하게 하라",
  "원천에 거리·소요시간·난이도·시작점이 있으면 반드시 싣는다")
- 관계: C05A(산림청 route 적재)·ADR-028(KNPS)의 route 변환을 바꾼다. Feature DTO·`make_feature_id`·DB 스키마는
  바꾸지 않는다(migration 없음). `feature_routes`의 기존 열(`total_distance_meters`·`expected_duration_minutes`·
  `difficulty`·`begin_name`·`end_name`)을 처음으로 채운다.

## 컨텍스트 (2026-11-27 prod 읽기 전용 실측)

- Map route 57,690건 = 산림청 등산로 57,047(`krforest_mountain_trails`) + KNPS 탐방로 617(`knps_trails`) +
  산림청 둘레길 26(`krforest_dulle_trails`). 거리·소요시간·난이도·시종점 이름이 **전부 0%** 채워져 있었다.
- 한 행은 코스가 아니라 **구간**이다. 산림청 길이 중앙값 233 m(1 km 이상 16%), KNPS 760 m("노고단고개 ~ 천왕봉"의
  한 구간이 506 m). 대표점이 선 시작점 50 m 안인 것은 31%뿐이다(대표점 = 무게중심).
- 그런데 **원천에는 값이 있었다** — Map 정규화가 버렸을 뿐이다. 원문은 `provider_sync.source_records.raw_data`에
  그대로 남아 있다.

### 원천 데이터셋 → 필드 → 적재 여부

| 원천(dataset_key) | 원천 필드(실측 채움률) | 이전 Map | 이 ADR 이후 |
|---|---|---|---|
| 산림청 등산로 `PBD0000041` (`krforest_mountain_trails`) | `MNTN_CODE`·`MNTN_NM` 산 식별(100%) · `PMNTN_NM` 노선명(60%) · `PMNTN_SN` 구간 순번(100%) · `PMNTN_LT` 거리 km(100%, geometry 길이와 중앙 비율 1.000) · `PMNTN_UPPL`/`PMNTN_GODN` 상행/하행 분(100%, 상행 중앙 17.8분/km) · `PMNTN_DFFL` 난이도 쉬움/중간/어려움(99.9%) · `PMNTN_MTRQ` 노면(16%) · `PMNTN_RISK` 위험(6%) · `PMNTN_MAIN` 주요지점(1.6%) · `DATA_STDR_` 기준일 | 이름(`MNTN_NM PMNTN_NM`)·geometry만. 나머지는 raw에만 | **코스**: 거리(측지)·소요시간(상행 합, `source`)·난이도(가장 어려운 구간)·하행 합·난이도별 거리·노면·위험·주요지점·기준일. **구간**: 거리·상행·난이도·하행을 정규 열/ payload에(구간 route 변환 경로) |
| KNPS 탐방로 `15003467` (`knps_trails`) | `공원사무소코드`+`탐방코스(한글)` 코스 키 · `일련번호` · `시작점_ID`→`종점_ID` 노드 그래프 · `지리정보시스템 상 거리(m)` · `가는시간(분)`/`오는시간(분)` · `난이도`(0~3.47, 0이 130/617, **척도 문서 없음**) · `상세구간` · `탐방로 통제여부`(1이 197/617) · `통제구간 설명` · `코스일정`(1/2/3) | 코스명 이름·geometry만 | **코스**: 거리(측지)·소요시간(가는시간 합, `source`)·출발/도착 이름(코스명 `A ~ B`)·오는시간 합·원천 난이도 최댓값(원값 보존, 등급 미변환)·통제 구간 수·통제 설명·코스일정 코드 |
| 산림청 둘레길 `PBD0000031` (`krforest_dulle_trails`) | `Name`(1~26)·`ID`·`path`/`layer`(구간 코드 1011~1211 + 구간명) | 이름 = 숫자 "1"~"26" | **변경 없음**. DBF가 원천 자체에서 이중 인코딩(UTF-8 한글을 CP949로 읽어 다시 UTF-8)되며 바이트가 잘려 구간명 복구 불가(예: `二쇱쿇_대큺` → `주천_?봉`). 거리·소요시간 필드는 원천 파일에 없다 |
| 산림청 등산로(산림문화·휴양정보) `3034022`, 숲길 `3034163`, 숲나들e 숲길 `15113562`, 국가숲길 이용등급 `15110618`, 100대명산 `15112801`/`15098177`, 백두대간 API `15002731`, 숲길·둘레길 API `15002725` | 카탈로그 설명상 노선·거리·소요시간·난이도 | **적재하지 않는 dataset**(python-krforest-api 카탈로그에만 있음) | 이 ADR 범위 밖 — 새 dataset 적재는 후속 과제(`docs/tasks.md`) |

## 결정

1. **코스가 Feature다.** route_type `hiking_course`(새 상수)인 route Feature를 원천 구간을 이어 만든다. 원천
   구간 Feature는 코스가 대신하므로 **provider lifecycle로 은퇴**시킨다 — 단 **코스가 계보로 가진 구간만**
   (`retired_source_entity_ids` = 코스 payload `segment_source_ids`의 합, `provider_tombstone` 전이 기록, 재실행해도
   같다). 코스를 만들지 못한 구간(산 코드·코스명 없음, geometry 결함 구간뿐인 묶음)은 손대지 않는다. 코스가 덮은
   구간이 원천의 50% 미만이면 원천 모양이 바뀐 것으로 보고 **아무것도 싣지 않고** run을 실패시킨다. 코스 적재와 구간
   은퇴는 **한 transaction**이고 curation seal은 은퇴 뒤에 잡는다(2026-11-28 개정 — 아래 "개정" 절). 구간 원문은 코스 SourceRecord의
   `raw_data.segments`에 그대로 남는다 — 코스의 계보이자 구간 단위 속성의 보존처다. 코스 payload의
   `segment_source_ids`가 코스→구간을 잇는다.
   - 왜 구간을 공개로 두지 않는가: 구간은 여행 단위가 아니다(233 m 토막, 이름은 "OO동구간"). 은퇴하는 구간은 모두
     어느 코스의 계보에 들어 있고 그 코스 선이 그 구간을 그린다(원천 거리와 모순되는 결함 구간만 선에서 빠진다). 구간을 남기면 검색·주변·
     지도에 같은 길이 두 번(구간 + 코스) 뜬다. "비공개 draft로 남기기"는 provider 적재가 기존 Feature의 공개 축을
     바꾸지 않아(재적재는 lifecycle만 전이) 별도 상태 전이 도구가 필요하다 — 은퇴가 이미 있는 정규 경로다.
2. **무엇을 한 코스로 묶는가.**
   - 산림청: 같은 산(`MNTN_CODE`)·같은 노선명(`PMNTN_NM`, 없으면 이름 없는 묶음 "OO산 등산로") 구간 중 약 10 m
     (0.0001도) 안에서 서로 닿는 **연결 성분**. 같은 노선명이 떨어진 성분 여럿이면 이름 뒤에 순번을 붙인다.
   - KNPS: 같은 `공원사무소코드`·`탐방코스(한글)`의 구간 **전부**(원천이 정한 코스 — 성분으로 쪼개지 않는다).
3. **조립**(`kortravelmap.core.route_course`, 순수 함수): 끝점 10 m snap → 다른 선 **중간** 10 m 안에 멈춘 막다른
   끝점을 그 선 위로 옮겨 정점으로 잇기(T자 갈림길 틈) → `unary_union`+`linemerge` → 분기점에
   매달린 50 m 미만 막다른 토막(시설 진입로·디지타이징 잔가지) 반복 제거 → 모양 판정 `path`/`loop`/`network`.
   `network`이면 출발 말단에서 망을 따라 가장 먼 말단까지의 최단 경로를 **본선**으로 골라 첫 선으로 둔다. 출발
   말단은 (출발 규칙 순위, 속한 연결 조각이 긴 순, 출발 규칙 거리)로 고른다 — 끊긴 작은 조각의 끝이 이기지 않는다.
   **저장 geometry의 첫 선 = 본선, 정점 순서 = 진행 방향**이라 출발/도착 좌표를 별도 열 없이 geometry에서
   유도한다(정본 1개). `ST_Multi`는 순서를 보존한다(통합 시험으로 확인).
4. **출발점.** 코스 Feature의 `coord` = 출발점(선 무게중심 아님 — 산 한가운데라 찾아갈 수 없다).
   - KNPS: 원천 노드 그래프에서 들어오는 구간이 없는 노드(`시작점_ID`이면서 어느 `종점_ID`도 아닌 것)가 후보이고,
     원천 `일련번호` 순으로 **순위**를 매긴다. 30 m 안에 맞는 후보 중 순위가 가장 높은 후보의 말단에서 출발한다
     (지선 토막 끝 후보는 지선이 먼저 떼어져 맞지 않는다). 원천 구간은 `시작점→종점` 방향으로 디지타이징돼 있다
     (노고단고개~천왕봉 35구간 전부 확인). 출발이 어느 후보와도 맞지 않으면 방향을 원천 근거로 정하지 못한 것이라
     코스명 `A ~ B`의 출발·도착 이름을 **붙이지 않는다**(엉뚱한 좌표에 "노고단고개"가 붙지 않게).
   - 산림청: 원천에 시종점·고도가 없다. **산 전체 구간망의 중심(정상부 대용점)에서 가장 먼 말단**을 들머리로
     추정한다(`start_rule='far_from_mountain_network_centroid'`). 추정 규칙임을 payload에 적는다. 입력 행 순서와
     무관하도록 구간을 원천 순번 순으로 다루고, 산 이름은 산 코드 안 최빈 표기, 중심은 `fsum`으로 낸다.
   - 주소: 출발점으로 역지오하고, 법정동을 못 얻으면(해안·경계선 위 들머리) 본선 중간점으로 다시 묻는다(좌표는
     출발점 그대로).
5. **거리·소요시간·난이도**(원천 우선):
   - 거리 = 그린 선 전체의 WGS84 측지 길이(겹침 1회). 원천 합은 `payload.source_distance_m`(검증값).
   - 소요시간 = 원천 합(산림청 상행 `PMNTN_UPPL`, KNPS `가는시간(분)`), `duration_basis='source'`,
     `payload.duration_method`(`sum_of_ascent_minutes`·`sum_of_go_minutes`)로 합산 방식을 적는다 — 넘어가는 코스나 갈래
     망에서는 모든 구간을 오르막 방향으로 더한 값이라 실제보다 길 수 있다. 구간 하나라도
     비면 **추정**: 18분/km(산림청 원천 상행 중앙값 17.8분/km에서 잡았다; 고도 자료가 없어 오르막 가산은 하지
     않는다), `duration_basis='estimated'` — 소비자는 "추정"을 표시해야 한다.
   - 난이도 = 산림청은 구간 중 가장 어려운 등급(`easy`/`moderate`/`hard`, 보수적 — 짧은 급경사 하나도 코스
     난이도다). 난이도별 거리는 payload에. KNPS는 원천 척도가 공개 문서에 없어 **등급으로 옮기지 않는다**
     (`difficulty=null`, 원값 최댓값만 `payload.source_difficulty_max`) — 임의 등급은 정확성 위반이다.
6. **원천 geometry 결함 가드.** 구간 geometry 측지 길이가 원천 거리의 3배와 +500 m를 **모두** 넘으면 그 구간은
   코스 선에서 뺀다(`excluded_segment_ids`, 계보에는 남음). 실측 KNPS 8구간이 원천 거리 0.4~12 km인데 공원
   전체를 지그재그로 훑는 단일 선(9~383 km, 정점 5천~1.8만)이다. 결함 구간이 다른 정상 구간과 한 코스면
   그 코스 계보에 남고(선에서는 빠짐) 함께 은퇴한다. 결함 구간뿐인 KNPS 코스 8개는 코스가 만들어지지 않으므로 그
   구간 route는 **종전대로 남는다**(원인 규명은 `T-KNPS-TRAIL-GEOM`).
7. **식별자.** 코스 natural key = 산림청 `course::{MNTN_CODE}::{PMNTN_NM|-}::{성분 첫 PMNTN_SN}`, KNPS
   `course::{공원사무소코드}::{탐방코스(한글)}`. `make_feature_id(bjd_code=None, kind=route, …)` — 역지오 결과와
   무관하게 같은 코스는 같은 id다(산림청 구간 route와 같은 규칙). source_entity_type은 `mountain_trail_course`·
   `knps_trail_course`로 구간(`mountain_trail_segment`·`knps_facility`)과 나눠 snapshot·은퇴 범위를 분리한다.
8. **적재 경로.** 새 자산을 만들지 않는다. 기존 `feature_route_krforest_mountain_trails`·
   `feature_geometry_knps_records`(dataset `knps_trails`)가 같은 원천 snapshot에서 코스를 만들어 싣고
   (`retire_absent_from_snapshot`, 코스 type 범위) 같은 transaction에서 구간을 은퇴시킨다
   (`load_authoritative_feature_snapshot(superseded=SupersededSourceEntities(구간 type, 덮은 id))`). 같은 원천이면 같은 코스·같은 id·같은
   payload hash다(결정적·멱등).
9. **공개 API.** `FeatureSummary`(bbox·in-bounds·search·area contained)·`NearbyFeatureSummary`(nearby·by-target)·
   `FeatureDetailResponse`에 `route: RouteSummaryOut | null`을 더한다 — `route_type`·`length_m`·`duration_minutes`·
   `duration_basis`(`source`|`estimated`)·`difficulty`·`shape`·`start`/`end`(`lon`·`lat`·`name`). 페이지당 1회
   `feature.public_features`에서 읽는다(공개 판정 재사용). 출발/도착은 `hiking_course`에만 낸다 — 다른 route는
   원천 디지타이징 방향이라 진행 방향이 정의되지 않는다. payload 전체는 계속 공개에서 벗긴다(T-VN-05);
   `duration_basis`·`course_shape`만 Map이 만든 해석이라 요약으로 올린다.

## 실측 (prod 원천 전량 읽기 전용 추출 → 이 구현의 provider 함수, 2026-11-27)

| | 원천 구간 | 코스 | path / loop / network | 길이 p10 / p50 / p90 / p99 | ≥1 km | <200 m | 소요시간 p50 |
|---|---|---|---|---|---|---|---|
| 산림청 등산로 | 57,047 | 14,252 | 11,278 / 218 / 2,756 | 145 m / 1.0 km / 5.1 km / 21.0 km | 7,155 (50%) | 2,065 | 19분 |
| KNPS 탐방로 | 617 | 186 | 129 / 2 / 55 | 705 m / 3.3 km / 9.3 km / 23.1 km | 158 (85%) | 1 | 114분 |

- 소요시간 출처: 두 원천 모두 전 코스 `source`(추정 0). 산림청 난이도: easy 13,476 / moderate 709 / hard 21 / 없음 46.
  KNPS 출발·도착 이름: 186 중 154 — 나머지 32는 출발이 원천 노드 후보와 맞지 않아(갈래·원형 노드) 이름을 붙이지 않았다.
- KNPS 8코스는 구성 구간이 모두 원천 geometry 결함(결정 6)이라 만들지 않는다(194 → 186).
- 예: "노고단고개 ~ 천왕봉" 35구간 → `network`(샛길 포함), 선 전체 23.05 km(본선 22.96 km), 노고단고개
  (127.5296, 35.2968)에서 출발, 가는시간 합 775분. "관악산 등산로"(이름 없는 묶음) 31.6 km·560분은 갈래망 전체다.
- 변환 시간: 산림청 57k구간 100~144초, KNPS 4~6초(로컬 1코어, 역지오 제외).
- 공개 route 수: 57,690 → 약 14,464(코스) + 둘레길 26.

## 결과

- 구간 은퇴 전이의 reason code는 기존 `retired_source_entity_ids` 경로의 `provider_tombstone`이다. 여기서의 뜻은 "원천이
  지웠다"가 아니라 "코스가 대신한다"이다 — 감사 기록을 읽을 때 이 ADR을 근거로 본다(전용 reason code는 후속 후보).
- 코스가 덮지 못한 구간(산 코드 없음 등)은 은퇴도 갱신도 되지 않는다. 원천에서 그 행이 사라져도 남는다 — 덮은/원천
  구간 수는 sync cursor(`course_segments_covered`·`course_segments_source`)에 남으므로 차이를 운영에서 본다(후속:
  덮지 못한 구간 id로 absent 은퇴를 한 번 더).
- KNPS 출발·도착 이름은 "순위 후보 중 어느 하나와 맞았을 때" 붙는다. 1순위 후보가 지선 제거로 사라져 2순위(샛길 끝)에서
  출발하면 이름이 샛길 끝에 붙을 수 있다 — 노고단고개~천왕봉처럼 1순위가 지선 토막인 정상 사례를 살리려는 선택이다.

- 산림청 ↔ KNPS 선형 겹침 dedup(`dagster/maintenance.py`의 `route_overlap` 규칙)은 이제 코스 단위로 짝을 짓는다.
  재적재 뒤 그 maintenance를 한 번 다시 돌려야 옛 구간 짝(은퇴한 Feature)이 코스 짝으로 바뀐다.
- 코스 natural key는 성분의 첫 원천 순번이다. 원천이 구간을 다시 번호 매기거나 성분이 갈라·합쳐지면 feature_id가
  바뀐다(옛 코스는 snapshot 부재로 은퇴). 원천이 2016년 정적 파일이라 받아들인다.

- 공개 route가 구간 → 코스로 바뀐다. 구간 feature_id를 이미 가진 소비자(PinVi 일정 POI 등)는 상세 404를 받는다
  — POI는 자기 `feature_snapshot`으로 계속 그려진다. 구간이 일정에 들어간 사례는 2026-11-27 현재 PinVi가 route를
  일정에 넣는 UI가 없어 0으로 본다(PinVi #805 이전에도 지도 토글뿐).
- 산림청 코스의 들머리는 추정이다. 고도(DEM)나 등산로 입구 POI가 들어오면 그 규칙으로 바꾼다(`start_rule`).
- 산림청 이름 없는 묶음(구간의 40%)은 대개 분기 많은 망이라 코스 이름이 "OO산 등산로"다. 원천에 노선명이
  없어서이며 다른 원천(100대명산 GPX 등) 적재가 해결책이다.
- `network` 코스의 거리·소요시간은 **모든 갈래를 한 번씩 걷는 합**이다(원천이 정한 코스/노선 전체). 본선만의
  값은 `payload.main_length_m`에 있다. 소비자 화면은 `shape='network'`이면 "갈래 포함"을 표시하는 것이 맞다 —
  본선 비례 환산으로 바꿀지는 열린 결정이다.

## 배포·재적재

migration 없음. 이미지 배포 뒤 `feature_route_krforest_mountain_trails_job`과 `feature_geometry_knps_records`
(dataset `knps_trails`)를 한 번씩 돌린다. 원천 다운로드(mountain.zip)·코스 조립(로컬 실측 57k구간 ≈ 2분)·역지오
(코스 출발점 약 14.4k건, 저장값 재사용 대상 아님 — 새 entity) · 적재(코스 14.4k insert) · 구간 은퇴(57k 상태 전이).

## 개정 (2026-11-28) — 코스 적재와 구간 은퇴를 한 transaction으로

처음 구현(#1569)은 코스 적재(seal 기대값을 그 transaction 끝에서 잡음)와 구간 은퇴를 **두 transaction**으로 돌리고,
첫 transaction의 seal 값을 run 결과로 넘겼다. child 완료 seal(`feature.seal_provider_curation_snapshot_receipt`)은
완료 시점의 입력 집합 해시(lifecycle·publication·row_revision 포함)를 다시 계산하므로, 은퇴가 1건이라도 있으면
기대값(은퇴 전)과 어긋나 `provider load input changed before child completion`으로 실패했다(prod: krforest 57,033건
은퇴 run, knps 609건 은퇴 run 모두 첫 시도 실패, 은퇴 0건인 재시도만 통과).

수정: 은퇴를 `load_authoritative_feature_snapshot`의 `superseded` 인자로 옮겨 코스 적재·코스 부재 은퇴·구간 은퇴·seal
캡처를 한 transaction으로 닫는다. seal 기대값이 최종 상태를 가리키고, 은퇴가 실패하면 코스 적재도 함께 rollback돼
"코스와 구간이 함께 공개된" 중간 상태가 commit되지 않는다. 은퇴 수는 결과의 `superseded_retired`(sync cursor
`segment_routes_retired`)다. sync 성공 기록은 다른 적재 asset과 같이 child 완료 seal 전에 남는다 — load commit
사실의 기록이고, seal 실패가 load commit을 되돌리지 않는다는 기존 계약(`tests/integration/test_heritage_collector_tracking.py`)을
따른다.
