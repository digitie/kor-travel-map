# ADR-127 — 휴게소 먹거리는 transport가 모은 한국도로공사 데이터를 Valkey 상태로 내고, 휴게소 연결·주유소 짝은 Map 규칙이 정한다

- 상태: accepted(소유자 승인 2026-11-27 — 조사 보고서의 권장안 "transport 수집 → Map 휴게소 상세", LLM 요약 없음).
- 범위: kor-travel-transport export `rest-area-food`(transport 2026-11-27), Map Valkey 데이터셋
  `transport.rest_area_food`, `/v1/service/transport/{rest-areas,fuel-stations}/{feature_id}` 상세, 관리자
  `/v1/ops/rest-area-food/review`, PG 휴게소 place의 `facility_info`. migration 없음.
- 관련: ADR-106(transport 데이터는 transport export에서 받는다), ADR-114(transport 현재 상태는 Valkey),
  ADR-120(휴게소 표시 이름), python-krex-api PR #21(0502 경로 정정, 0615·0124 추가).

## 맥락

PinVi 휴게소·고속도로 주유소 상세에 음식 정보가 없다. 한국도로공사 공공데이터 포털(data.ex.co.kr)의 0502 "휴게소
푸드메뉴현황"(`restBestfoodList`, 2026-11-27 7,291행)이 메뉴명·가격·대표(`bestfoodyn`)·프리미엄·추천·계절 표시를
준다. 휴게소 표준 코드(`stdRestCd`)는 0615 "휴게소코드정보"(`hiwaySvarInfoList`, 583행: 휴게소·주유소·상하행)와
같다. 문제는 세 가지였다.

1. Map 휴게소(transport `rest-areas` = data.go.kr 표준데이터)에는 KREX 코드가 없고 노선·방향이 비어 있다. 자연키는
   이름뿐이다("남성주참외(창원)::::").
2. 오피넷 고속도로 주유소에는 KREX 코드가 없다. 같은 휴게소라도 휴게소(`A…`)와 주유소(`B…`)는 별개 레코드다.
3. 메뉴는 천천히 바뀌지만 "현재 값"이다. ADR-114는 transport 현재 값을 PG feature가 아니라 Valkey 세대로 낸다.

## 결정

1. **수집 소유는 transport다(ADR-106).** transport가 0615와 0502를 하루 한 번 한 transaction으로 모으고
   `GET /v1/service/exports/rest-area-food`로 낸다(표준 코드 한 행에 메뉴 목록). Map은 data.ex.co.kr을 부르지 않는다.
2. **휴게소 ↔ KREX 코드 연결은 Map 규칙(`providers.rest_area_food.link_rest_areas`)이 정한다.** 두 원천이 모두
   한국도로공사 표기 `<이름>(<행선지>)`를 쓰므로 공백·"휴게소"·"방향"을 걷은 `(이름, 행선지)`가 KREX 휴게소 하나와만
   같으면 잇는다(신뢰도 1.0). 0615 코드 하나와 0502에만 있는 옛 코드가 겹치면 0615 코드로 잇고 메뉴를 합친다(0.95).
   이름이 둘 이상과 같거나 한 코드에 휴게소 둘이 붙으면 잇지 않는다. **실측(2026-11-27 운영 215곳): 215곳 모두 연결
   (정확 213 + 합침 2 — 함양 상하행), 메뉴가 붙는 곳 213곳.** 좌표는 쓰지 않는다 — 0124 좌표는 같은 이름 휴게소가
   290 km 어긋난 행이 있다.
3. **메뉴 요약은 결정적이다(LLM 없음).** 대표 → 프리미엄 → 추천 순 최대 12개, 0보다 큰 가격의 최저·중앙(짝수 개면
   낮은 쪽)·최고, 여름·겨울 메뉴 최대 10개, 원천 메뉴 수정일 최댓값, transport 수집 시각(화면의 기준일), 출처
   "한국도로공사".
4. **저장 위치.**
   - 메뉴 요약·연결 결과는 Valkey 새 데이터셋 `transport.rest_area_food`(값 모델 `RestAreaFoodState`, id = 휴게소
     상태의 `feature_id`, GEO = 휴게소 좌표)다. job `transport_state_rest_area_food`(매일 05:07 KST, 다른 상태 job처럼
     코드 기본 STOPPED)가 `rest-areas`·`rest-area-food` 두 export를 받아 교체한다. 기존 `RestAreaState` 모양은 바꾸지
     않는다 — 바꾸면 Valkey 키 스키마 버전(`ktm:state:v1`)을 올려 모든 transport·weather 세대를 다시 채워야 한다.
   - PG 휴게소 place에는 바뀌지 않는 정체만 둔다: `facility_info.ex_link`(`std_rest_code`·`route_code`·`route_name`·
     `direction_code`·`method`·`confidence`), 비어 있던 `highway_name`(KREX 노선명)·`direction`(원천 이름의 행선지,
     "부산방향"). 자연키·feature id는 그대로다. 첫 적재에서 215곳의 payload hash가 바뀌어 한 번 다시 쓰인다.
   - PG 휴게소 적재는 먹거리 export를 함께 받고, 그것이 503·404·0건·stale·세대 혼합·계약 위반이면 **실패한다**
     (코드가 사라졌다 돌아오는 출렁임을 만들지 않는다 — 실패한 run은 아무것도 바꾸지 않는다). 즉 먹거리 export가
     멈추면 주간 휴게소 place 적재(`feature_place_transport_rest_areas_weekly_schedule`)도 빨갛다 — 운영 경보는
     그 run 실패와 상태 job 나이 경고로 본다. export는 정상인데 이름이 바뀌어 연결이 모호해진 주에는 `ex_link`가
     빠진다(남은 출렁임, 검토 목록의 `unlinked_rest_areas`로 보인다).
   - 정본은 하나다: 원천 데이터는 transport, 연결·요약 규칙은 Map 코드. PG와 Valkey는 같은 규칙의 산출물이다.
     PinVi는 Map만 부른다(transport를 직접 부르지 않는다).
5. **주유소 ↔ 휴게소 짝은 적재 job이 전체를 한 번에 정한다(`pair_stations`).** job은 transport 주유소 export도 받아
   주유소마다 400 m 안 먹거리 휴게소 후보에 이름 근거로 신뢰도를 매기고, 결과를 휴게소 먹거리 값의 `stations`에
   싣는다. 자동 짝 주유소의 feature_id는 세대의 lookup 키다 — 주유소 상세(`/v1/service/transport/fuel-stations/{id}`)는
   lookup 한 번으로 찾고, 관리자 검토 목록도 같은 값을 읽어 두 표면의 판정이 같다.
   - 휴게소 이름 + 행선지(괄호·"…방향"·이름 바로 뒤, 부분 문자열 아님 — "안산주유소(강릉방향)" ↔ "안산(강릉)",
     "홍천서울주유소") 0.95, 휴게소 이름 + 양방향 휴게소 0.9.
   - (상)/(하)는 노선마다 기준이 KREX 상하행과 다를 수 있다(2026-11-27 중부내륙선: 오피넷 "영산(하)"가 KREX 상행).
     KREX 상하행과 같고 **그 후보가 같은 이름의 반대 방향 후보보다 가까울 때만** 0.85, 아니면 검토.
   - 휴게소 이름만 있고 방향 표기가 없으면 그 이름 후보가 하나일 때 0.85(`name_single`). 방향 표기가 있는데 후보와
     어긋나면 검토(`name_conflict`). 이름 근거가 없으면 0.3(`distance_only`). 빈 휴게소 이름은 근거가 아니다.
   - **일대일 다듬기**: 한 휴게소에 자동 짝이 여럿이면 가장 강한 근거만 남기고 더 약한 근거의 짝은 검토로 내린다
     (`…_weaker`). 휴게소 지명이 든 근처 일반 주유소("경산I.C주유소", "신탄진충전소")가 약한 근거로 붙는 오짝을
     막는다. 같은 근거끼리(주유소·충전소 따로 등록, 양방향 휴게소의 상하행 주유소)는 둘 다 둔다.
   - **0.8 이상만 자동으로 보인다.** 나머지는 관리자 `GET /v1/ops/rest-area-food/review`(operator)에만 나온다.
     사람이 값을 덮어쓰는 저장소는 두지 않는다 — 고치는 길은 규칙이다("decide simply").
   - **실측(2026-11-27 운영, 휴게소 400 m 안 주유소 242곳): 자동 204(84.3%), 검토 38.** 1차 규칙(자동 216)에서
     적대 리뷰가 찾은 오짝 6건(중부내륙선 (상)/(하) 2, 근처 일반 주유소 4)은 모두 검토로 내려갔다. 자동 짝이 둘 이상인
     휴게소 10곳은 모두 양방향 휴게소의 상하행 주유소이거나 한 방향에 주유소·충전소가 따로 등록된 경우다.
6. **메뉴가 없는 휴게소는 먹거리 상태를 내지 않는다.** 데이터셋 건수가 "메뉴 있는 휴게소 수"가 되어, 0502만
   비거나 일부만 와도 Valkey 교체 거부(ShrinkGuard 90%)가 막는다. 0원 행은 대표·계절 목록에서 빼고, 합친 메뉴의
   같은 (이름, 가격)은 한 번만 둔다.

## 대안 검토

- **PinVi가 transport를 직접 부른다**: PinVi는 Map 서비스 API만 쓰고(ADR-106·114) transport export는 Map 토큰·접속
  주소로 닫혀 있다. 연결 규칙도 두 곳에 생긴다. 기각.
- **transport가 data.go.kr 휴게소와 KREX 코드를 잇는다**: 두 원천이 다 transport에 있어 가능하지만, Map이 같은
  휴게소 이름 규칙(ADR-120 표시 이름)과 오피넷 주유소 짝을 함께 판단한다. 짝은 Map Valkey의 주유소·휴게소 GEO가
  필요하다. 연결만 transport로 옮기면 규칙이 두 저장소로 갈린다. 기각.
- **메뉴 요약을 PG `facility_info`에 둔다**: 매일 payload hash가 바뀌어 PG place 적재·reconcile이 돈다. 현재 값은
  Valkey라는 ADR-114와도 어긋난다. 기각(정체만 PG).
- **`RestAreaState`에 필드를 더한다**: 키 스키마 버전을 올려야 한다(위 4). 기각.
- **LLM 한 줄 요약**: 소유자 결정으로 하지 않는다(데이터만).

## 결과

- 배포 순서: transport(odroid, migration `0051`, 먹거리 수집 1회 수동 실행) → Map(API·Dagster, 새 schedule
  `transport_state_rest_area_food_schedule` RUNNING으로 켜고 한 번 실행) → PinVi.
- 먹거리 상태 job은 매일 transport 주유소 export(약 1.2만 행)를 한 번 더 받는다(짝 계산용).
- 관리자 화면 UI는 아직 없다. 검토 목록은 operator API로 본다(후속: 관리자 화면 표).
- 데이터 출처 표기: "출처: 한국도로공사 · 기준일 YYYY-MM-DD"(`source_collected_at`의 KST 날짜).
- data.ex.co.kr의 트래픽 한도·공공누리 유형·`bestfoodyn`/`recommendyn`의 공식 정의는 미확인이다.
