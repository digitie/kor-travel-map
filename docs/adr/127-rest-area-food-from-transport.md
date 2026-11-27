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
     "부산방향"). 자연키·feature id는 그대로다. PG 적재는 먹거리 export가 503·404면 실패한다(코드가 사라졌다
     돌아오는 출렁임을 만들지 않는다 — 실패한 run은 아무것도 바꾸지 않는다).
   - 정본은 하나다: 원천 데이터는 transport, 연결·요약 규칙은 Map 코드. PG와 Valkey는 같은 규칙의 산출물이다.
     PinVi는 Map만 부른다(transport를 직접 부르지 않는다).
5. **주유소 ↔ 휴게소 짝은 읽을 때 정한다(`pair_station`).** 주유소 상세(`/v1/service/transport/fuel-stations/{id}`)가
   주유소 400 m 안 먹거리 휴게소를 GEO로 찾고, 후보마다 이름 근거로 신뢰도를 매긴다.
   - 휴게소 이름 + 행선지("안산주유소(강릉방향)" ↔ "안산(강릉)") 0.95, 휴게소 이름 + 양방향 0.9,
     휴게소 이름 + (상)/(하)가 KREX 상하행과 같음 0.9, 휴게소 이름뿐이고 그 이름 후보가 하나 0.85,
     휴게소 이름뿐이고 후보가 둘 이상 0.6, 이름 근거 없음 0.3~0.5. 같은 근거로 둘이 맞으면 0.6.
   - **0.8 이상만 자동으로 보인다.** 나머지는 관리자 `GET /v1/ops/rest-area-food/review`(operator)에만 나온다.
     사람이 값을 덮어쓰는 저장소는 두지 않는다 — 고치는 길은 규칙이다("decide simply").
   - 이름 근거가 거리보다 앞선다. 운영 표본에서 같은 휴게소 상하행 주유소 좌표가 서로 바뀐 사례가 있다("밀양(함양방향)"
     주유소가 울산방향 휴게소 쪽에 더 가깝다).
   - **실측(2026-11-27 운영): 휴게소 400 m 안 주유소 242곳 중 자동 216곳(89.3%), 검토 26곳.** 검토 26곳 중 약 15곳은
     휴게소 주유소가 아닌 근처 일반 주유소(이름 근거 없음)이고, 8곳은 오피넷 이름의 행선지가 KREX와 달라("괴산(마산)" ↔
     괴산(창원)·괴산(양평)) 방향을 못 가리는 경우다.

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
- 관리자 화면 UI는 아직 없다. 검토 목록은 operator API로 본다(후속: 관리자 화면 표).
- 데이터 출처 표기: "출처: 한국도로공사 · 기준일 YYYY-MM-DD"(`source_collected_at`의 KST 날짜).
- data.ex.co.kr의 트래픽 한도·공공누리 유형·`bestfoodyn`/`recommendyn`의 공식 정의는 미확인이다.
