# ADR-114 — weather·transport의 현재·예보 상태는 Map이 메모리 DB(Valkey)에 들고, PinVi는 Map REST로 읽는다

- 상태: proposed (소유자 결정 2026-10-23 — 방향 확정. 2026-10-23 1단계(transport) 구현 PR — 아래 "구현 설계 —
  1단계". 2026-10-24 2단계(weather) 구현 PR — 아래 "구현 설계 — 2단계". 2026-10-24 결정 7 퇴역 1단계(PG 유가·돌발) PR —
  아래 "결정 7 이행 — PG transport 퇴역". 이행 단계마다 이 문서를 갱신하고 마지막 단계가 배포되면 accepted로 올린다)
- 날짜: 2026-10-23
- 결정자: 소유자(방향), Claude(문서)
- 관계: **ADR-105를 부분 대체**(weather가 Map에 다시 들어온다 — 단 DB 스키마가 아니라 메모리 DB로), ADR-110(odroid
  피호출자를 Map이 REST로만 쓴다 — 그대로 유지, 이 ADR은 그 위에 "PinVi는 Map을 거친다"를 더한다), ADR-106(transport
  가격 `observed_at`), ADR-109(geo 토큰 규칙), ADR-113(스냅샷 적재 spool)

## 소유자 결정(원문 요지)

- "transport는 map에서 메모리 저장, weather는 과거처럼 다시 map feature로 가져오고 map에서 메모리 저장. pinvi는
  weather/transport feature를 map에서 rest api로 불러오게."
- 과거 데이터는 Map에 남기지 않는다. transport 자체 기능(이력·통계)은 바꾸지 않는다.
- (2026-10-23 추가) "weather는 과거 날씨를 오전·오후 정도의 시간 간격으로 저장. 여행 기간 중 어제보다 추운지
  더운지, 습한지 아닌지 등 비교할 수 있게." → 같은 날 정정 "아침, 점심, 저녁 정도로 저장" — weather만 예외로
  하루 세 구간 요약을 보관한다(결정 1).
- 가격 추이는 Map DB가 아니라 transport에서 직접 읽는다.
- 저장소는 선택지 ②(메모리 DB, Valkey).
- transport가 이미 VWorld로 구한 법정동코드는 Map에서 geo를 다시 부르지 않고 그대로 쓴다(ADR-109 예외 — 아래 결정 6).

## 컨텍스트

- transport 출처 데이터를 PG feature로 적재하면, 가격이 그대로여도 주유소 11.8천 곳 전부에 새 source_record와 가격
  fact가 매일 쌓인다(추정 하루 45~50 MB, 연 17 GB). Map은 transport의 과거 데이터를 쓰지 않는다.
- weather는 ADR-105로 Map에서 빠졌고, PinVi가 odroid weather를 직접 부른다. 이제 PinVi의 날씨·교통 진입점을 Map
  하나로 모은다.
- odroid 실측(2026-10-22): 현재·예보만 세면 weather 약 188만 값(단기예보 약 179만, 초단기·중기 약 6만, 최신 관측·실황
  약 3.2만), transport 약 9만 건(교통량 구간 8,319, 주유소 11,838 / 최신 유가 59,190, 돌발 370, 주차 44, 참조 약
  5천).
- n150 실측(2026-10-22): Intel N150 4코어, 메모리 15.3 GB 중 여유 약 9.5 GB, 디스크 105 GB 남음. Map API는 uvicorn
  1 프로세스이고 적재는 Dagster run 프로세스에서 한다 — **쓰는 프로세스와 읽는 프로세스가 다르다.** 그래서 API 프로세스
  내부 메모리(dict·numpy)는 안 되고, 두 프로세스가 같이 보는 저장소가 필요하다.

## 결정

### 1. 범위

- weather: 현재 관측·실황(최신 1건)과 예보(초단기·단기·중기·외부 provider 예보, **지금 이후 시각만**).
- transport: 주유소·휴게소(위치·최신 유가), 공항, 고속도로 돌발(활성 집합), 고속도로 교통량(구간별 최신), 주차장(최신),
  역·버스터미널·항구 참조.
- 과거 시점 값은 저장하지 않는다. 예보는 시각이 지나면 지운다.
- **예외 — weather 하루 세 구간 요약.** 지점마다 아침(05~11시)·점심(11~17시)·저녁(17~23시) 구간 단위로 기온(최저·최고·평균), 습도(평균),
  강수(합계·유무), 하늘상태·풍속(대표값) 요약을 **최근 14일** 보관한다. 여행 중 "어제보다 춥다/덥다/습하다" 비교용이다.
  요약은 weather가 계산해 내보내고(관측 기준), Map은 받아서 보관만 한다. 14일이 지난 요약은 지운다. 규모는 약
  1,450곳 × 3 × 14일 ≈ 6만 항목으로 메모리 수 MB 수준이다. 보관 기간은 소유자가 바꿀 수 있는 설정값으로 둔다.

### 2. 저장소 — Valkey 단일 인스턴스

- BSD 라이선스인 Valkey(Redis 호환)를 n150에 Manager 관리 컨테이너로 하나 둔다. 외부 포트는 열지 않고 Map API·Map
  Dagster만 접근한다.
- `maxmemory` 1 GB, `maxmemory-policy noeviction`(조용히 지우지 않고 쓰기를 실패시킨다). 예상 사용량은 0.2~0.5 GB.
- 지속성: RDB 스냅샷과 AOF(`everysec`). 재시작하면 디스크에서 복원한다. 백업 대상은 아니다 — 원천(weather·transport)에서
  다시 받을 수 있다.
- 키는 값마다가 아니라 묶음 단위로 둔다(예: 지점×provider 하나에 예보 배열 하나, 주유소 하나에 위치+최신 유가). 근처
  검색은 Valkey GEO 인덱스로 한다. 세부 키 설계는 아래 "구현 설계 — 1단계" D2가 정본이다.

### 3. 쓰기 — Map Dagster 적재 job

- weather·transport의 service API에서 받아 Valkey에 **세대 단위로 원자 교체**한다(새 세대 키를 다 쓴 뒤 포인터를 바꾼다).
  도중에 실패하면 이전 세대가 그대로 보인다.
- 원천이 빈 목록이나 비정상적으로 작은 집합을 주면 교체하지 않는다(2026-10-23 KREX 빈 응답으로 돌발 106건이 한 번에
  닫힌 사례).
- 각 세대에 원천의 수집 시각·Map 반영 시각을 함께 둔다(신선도).

### 4. 읽기 — Map REST

- Map API가 Valkey에서 읽어 weather·transport feature를 REST로 제공한다. 식별자는 기존 `make_feature_id` 규칙을 그대로
  써서 안정적으로 유지한다.
- 가격 추이(이력)는 Map이 저장하지 않고, 요청 시 transport에서 직접 읽어 전달한다. transport가 응답하지 않으면 현재가는
  그대로 주고 추이만 "없음"으로 준다.
- Valkey가 응답하지 않으면 해당 엔드포인트만 503이고 나머지 Map 기능에는 영향이 없다.

### 5. PinVi

- PinVi는 weather·transport 데이터를 Map REST로만 읽는다. odroid weather를 직접 부르던 경로는 이행이 끝나면 지운다.
- Map admin OpenAPI가 바뀌면 PinVi 재vendor가 필요하다.

### 6. transport의 VWorld 법정동코드 사용 (ADR-109 예외)

- transport export에 실린 VWorld 기반 법정동코드·주소를 Map이 그대로 쓰고, 이 데이터에 대해 geo를 다시 부르지 않는다.
  ADR-109의 "geo 데이터 토큰이 같을 때만 payload 행정코드를 믿는다"는 규칙의 예외다.
- 적용 전에 VWorld 코드와 geo 코드의 일치율과 feature_id가 바뀌는 건수를 재서 이 문서에 적는다.

### 7. 기존 PG의 transport feature

- 지금 PG에 있는 transport 출처 feature(주유소·휴게소·유가·돌발·공항 dataset)는 Valkey 경로가 배포되면 퇴역한다.
  퇴역 방법과 시점은 이행 PR에서 정한다. 그 전까지는 현재 적재를 유지한다.
- (2026-10-24) 방법·순서는 아래 "결정 7 이행 — PG transport 퇴역"이 정본이다. 소비자 확인 결과 장소(주유소·휴게소·
  공항 place)는 아직 기대는 곳이 있어 세 단계로 나눴다: ① 유가·돌발 적재 종료 + Feature 퇴역(soft-delete, migration
  411) → ② 장소 적재 종료 + 퇴역 → ③ 물리 삭제.

## 결과 — 잃는 것

- Map에서 transport의 과거 시점 조회는 할 수 없다(가격 추이만 transport를 통해 제공한다). weather는 하루 세 구간(아침·점심·저녁) 요약
  14일만 있고 그보다 세밀하거나 오래된 과거는 없다.
- Map 장애가 PinVi의 날씨·교통 표시까지 멈춘다(지금 같은 n150에 있어 위험 증가는 작다).
- 운영할 구성요소가 하나(Valkey) 는다.

## 기각한 대안

- **API 프로세스 내부 메모리**: 적재 프로세스와 읽기 프로세스가 달라 공유가 안 되고, 재시작 때마다 예보를 39~90분 다시
  모아야 한다.
- **PG 최신 상태 표**: 단순하지만 소유자가 메모리 DB를 택했다.
- **DuckDB·SQLite 메모리 모드**: 프로세스별이라 내부 메모리와 같은 문제.
- **transport 출처 데이터를 PG feature로 두고 최신만 남기기(정리 방식)**: 2026-10-23 착수했다가 이 결정으로 중단했다
  (브랜치 `feat/transport-latest-only`, 참고용). 그 설계 리뷰에서 나온 두 함정 — seal 직전이 아닌 곳에서 정리하면 seal
  대조가 깨진다, runtime 역할은 증거 표를 읽지 못한다 — 은 이 ADR의 구현에서도 피할 것.

## 이행 순서

1. weather·transport 저장소에 Map용 API 추가(별도 작업, codex)
2. Manager: Valkey 서비스 추가(n150)
3. Map: Valkey 적재 job·REST·가격 추이 프록시
4. PinVi: Map REST로 전환, odroid weather 직접 호출 제거
5. Map: 기존 PG transport feature 퇴역

## 구현 설계 — 1단계: transport (2026-10-23, 이행 순서 3의 transport 부분)

weather는 weather 저장소의 Map용 API가 생긴 뒤 2단계로 같은 틀에 얹는다. 1단계는 Map이 **지금 이미 쓰는**
transport export(`/v1/service/exports/{fuel-stations,rest-areas,rest-area-fuel-prices,highway-incidents/active,
airports}`)만 쓰고, 기존 PG transport 적재는 그대로 둔다(결정 7).

### D1. 데이터셋과 식별자

| 데이터셋(`{ds}`) | 원천 export | 값 하나 | GEO | 교체 거부 기준(D4: 절대 하한 · 최근 최대 대비 비율 · 비율 적용 기준) |
| --- | --- | --- | --- | --- |
| `transport.fuel_stations` | fuel-stations | 주유소 1곳 + 유종별 최신가 | 좌표 있는 것 | 10,000곳 · 90% · 100곳 |
| `transport.rest_areas` | rest-areas | 휴게소 1곳 | 좌표 있는 것 | 100곳 · 90% · 20곳 |
| `transport.rest_area_fuel_prices` | rest-area-fuel-prices | 휴게소 주유소 1곳의 최신가 | 없음(휴게소에 붙여 읽는다) | 80곳 · 80% · 20곳 |
| `transport.highway_incidents` | highway-incidents/active | 활성 돌발 1건 | 좌표 있는 것 | 없음 · 25% · 20건(기준 미만이면 0건 허용) |
| `transport.airports` | airports | 공항 1곳 | 좌표 있는 것 | 10곳 · 80% · 5곳 |

- `feature_id`는 PG 변환과 **같은 입력**으로 `make_feature_id`를 부르되 `bjd_code=None`(`f_global_…`)으로 고정한다.
  kind·category·`source_type`(`kor-travel-transport:{dataset_key}`)·자연키는 `providers/opinet.py`·`krex.py`·
  `krairport.py`와 같다. 주유소 값 하나는 위치와 가격을 함께 담지만 id는 **place** id(`transport_fuel_stations`
  source_type)다 — PG는 같은 주유소를 place와 price 두 feature로 나눴다. 휴게소 유가 값의 id는 PG의 휴게소 유가
  price feature와 같은 입력(`transport_rest_area_fuel_prices`, 원래 `bjd_code=None`)이다. 돌발도 PG에서 이미
  `bjd_code=None`이다. 주유소·휴게소·공항 place는 PG가 역지오코딩한 bjd를 id에 넣지만 여기서는 넣지 않는다 — 결정
  6의 VWorld 블록이 export에 실려도 id가 바뀌지 않게 하려는 것이다(bjd는 값의 주소 속성으로만 둔다). 1단계는 geo를
  부르지 않으므로 bjd는 비어 있다. PG feature는 rev 309 이후 UUID가 정본이라 어차피 같은 문자열이 아니다 — PinVi는
  이 표면의 id를 별도 네임스페이스로 다룬다. 같은 id 계산은 단위 검사가 PG 변환(`bjd_code=None` 경로)과 대조한다.
- 같은 id가 한 집합에 둘 이상 나오면(돌발 단서가 같은 두 행, 이름·노선·방향이 같은 휴게소) **원천 순서의 첫 행**을
  남기고 나머지 수를 `meta.duplicates`에 적는다. 기대 개수는 고유 id 수다.
- 휴게소의 transport `natural_key`가 Map 규칙(`name::route::direction`, strip→lower)과 다르면 계약 위반으로 적재를
  실패시킨다(PG 경로와 같은 검사).
- 좌표는 한국 주변 범위(경도 120~135, 위도 30~45) 밖이거나 (0, 0)이면 좌표 없음으로 둔다 — GEO 쓰기 하나가 범위
  밖 좌표 하나로 통째로 실패하지 않게 한다.
- 휴게소 유가는 휴게소에 `name::route::direction` 정규화 키(`krex.fuel_price_match_key`)로 **읽을 때** 붙인다. 그
  보조 키 표는 휴게소 유가 데이터셋의 세대에 있다(`lookup`, 같은 키는 원천 순서 첫 행). 두 export의 세대는 따로
  돈다(유가 export가 죽어도 휴게소 위치는 갱신된다).

### D2. 키

접두사 `ktm:state:v1:`(값 스키마 버전 포함). 값 모양이 바뀌면 `v2`로 올린다 — 새 버전으로 **어떤 데이터셋의**
교체가 성공하면 **그 데이터셋의 더 옛 버전**(`ktm:state:v{n<2}:{ds}:*`) 만료 없는 키에 grace TTL을 건다. `current`와
교체된 세대는 만료가 없으므로 이 정리가 없으면 `noeviction` 아래 옛 버전 한 벌이 영구히 남는다. 더 새 버전은 건드리지
않고(롤링·롤백 중 서로 만료시키지 않게), 다른 데이터셋은 자기 교체 때 거둔다(아직 새 버전으로 적재되지 않은
데이터셋이 비어 보이지 않게). 버전을 올리면 job 다섯을 한 번씩 수동 실행한 뒤 API를 배포한다.

| 키 | 형 | 내용 |
| --- | --- | --- |
| `…:{ds}:current` | STRING | 지금 읽을 세대 id. 만료 없음. 바꾸는 자리는 교체 스크립트 하나 |
| `…:{ds}:previous` | STRING | 직전 세대 id(교체 스크립트가 함께 바꾼다). cursor 검증용 |
| `…:{ds}:recent_counts` | LIST | 최근 교체 6번의 개수(최신이 앞). D4 기준 |
| `…:{ds}:lock` | STRING(NX, TTL) | 적재 하나만 돌게 하는 잠금. 토큰 비교 후 해제 |
| `…:{ds}:{gen}:meta` | HASH | `count`·`geo_count`·`lookup_count`·`duplicates`·`source_collected_at`·`loaded_at`·`run_id`·`guard_override` |
| `…:{ds}:{gen}:items` | HASH | `feature_id` → 값 JSON(엔티티 하나 = 필드 하나, "묶음 단위") |
| `…:{ds}:{gen}:ids` | ZSET(score 0) | `feature_id` 사전순 — 목록 keyset 페이지(`ZRANGE … BYLEX`) |
| `…:{ds}:{gen}:geo` | GEO | 좌표 있는 `feature_id` — 근처·bbox 검색 |
| `…:{ds}:{gen}:lookup` | HASH | 보조 키 → `feature_id`(휴게소 유가 매칭 키) |

- `{gen}` = `YYYYMMDDTHHMMSSZ-{난수 8 hex}`. 세대 키는 쓰고 나면 바꾸지 않는다(불변).
- **세대가 있다는 표지는 `meta` 하나다.** 0건 세대(돌발 0건)·좌표 없는 세대에는 `items`·`geo`가 없다 — 읽는 쪽은
  `meta`가 있으면 빠진 키를 빈 것으로 읽는다.
- 값은 Pydantic 모델(`kortravelmap.dto.transport_state`)의 JSON이고 REST 응답이 같은 모델을 쓴다(정본 하나).

### D3. 쓰기 — 세대 교체 순서

1. `lock`을 `SET NX EX`(그 job의 run 상한 + 취소 유예 600초 + 60초)로 잡는다. 이미 있으면 다른 적재가 도는 것이라 이번 run은 받지 않고 끝낸다(실패
   아님). 끝나면 자기 토큰일 때만 지운다.
2. 원천을 끝까지 받는다(기존 fetcher 그대로 — 수집 이력 없음·실패·stale·계약 위반·0건 페이지 export는 여기서
   실패하고 Valkey에는 아무것도 쓰지 않는다).
3. `current`와 그 세대 `meta`, `recent_counts`를 읽는다. `current`가 있는데 `meta`가 없으면 저장소가 깨진 것이라
   실패한다(첫 적재로 취급하지 않는다). 교체 거부 검사(D4). 거부면 쓰지 않고 실패한다.
4. 새 세대 키를 pipeline으로 나눠 쓴다. **쓰는 동안 새 키마다 build TTL(기본 2시간)을 건다** — 적재가 도중에
   죽으면 아무도 가리키지 않는 키가 TTL로 사라진다(`noeviction`이라 스스로 지워야 한다). 실패하면 그 자리에서
   새 키를 지우고(최선), TTL은 그 뒤의 안전망이다.
5. Lua 스크립트 하나로 검사와 교체를 원자적으로 한다: `current`가 3에서 읽은 값과 같고(compare-and-set, 첫 적재는
   "없음"과 비교), 새 `meta`가 있고, `HLEN items`·`ZCARD ids`·`ZCARD geo`·`HLEN lookup`이 `meta`에 적힌 개수와 같을
   때만 새 키의 TTL을 지우고(`PERSIST`) `current`·`previous`·`recent_counts`를 바꾸고 직전 세대 키에 grace
   TTL(기본 15분)을 건다. 하나라도 어긋나면 아무것도 바꾸지 않고 실패한다(동시 교체·build TTL 초과·부분 쓰기).

읽는 쪽은 `current` → 그 세대 키 순서로 읽는다. 교체 전에는 옛 세대, 교체 후에는 새 세대 전체가 보이며 섞인
상태는 없다. 옛 세대는 grace 동안 살아 있어 진행 중인 페이지 순회가 같은 세대로 끝난다.

### D4. 비정상 집합 거부

- 새 집합이 데이터셋의 **절대 하한** 미만이면 거부한다(첫 적재·Valkey 볼륨 유실 뒤에도 기준이 있다).
- 기준 = `recent_counts`(최근 교체 6번) 중 **최대값**. 기준이 비율 적용 기준 이상이고 새 집합이
  `ceil(기준 × 비율)` 미만이거나 0건이면 거부한다. 직전 하나와만 비교하면 106 → 27 → 7 → 0처럼 여러 번에
  나눠 줄어드는 것을 막지 못한다.
- 돌발만 0건이 정상일 수 있다: 기준이 20건 미만이면 0건도 받는다.
- 거부는 run 실패(`failure_kind=state_swap_refused`, step 재시도 없음)다. 다음 schedule tick이 다시 본다. 거부가
  이어지면 옛 세대가 남고 나이가 늘어 읽기 응답의 `stale`이 드러낸다(D5) — Dagster run 실패가 경보 자리다.
- 진짜로 줄었으면 운영자가 run config `allow_shrink: true`로 한 번 통과시킨다(`meta.guard_override=1`로 남는다).

### D5. 신선도

- `meta.source_collected_at` = 원천 수집 시각(페이지 export는 페이지들의 `collection.last_success_at` 중 가장 이른
  값 — 순회 도중 transport 수집이 끝나 두 수집본이 섞이면 이른 쪽으로 보수적으로 잡는다. 돌발은 집합의
  `collected_at`, 공항은 원천 수집 시각이 없어 비어 있다). `meta.loaded_at` = Map 교체 시각.
- 응답마다 `freshness{dataset, generation, source_collected_at, loaded_at, age_seconds, max_age_seconds, stale,
  item_count}`를 싣는다. `age`는 `source_collected_at`(없으면 `loaded_at`) 기준이다. 상한: 주유소·휴게소 유가
  48시간, 돌발 30분(`INCIDENT_SET_MAX_AGE`와 같다), 휴게소·공항 8일.
- 응답은 stale이어도 값을 준다(판단은 소비자). 다만 돌발은 소비자가 `stale=true`면 표시하지 않는 것을 권한다.

### D6. 읽기 — Map REST(service 표면)

`/v1/service/transport/…`, `X-Kor-Travel-Map-Service-Token`(기존 `require_service_token`). 목록은
`fuel-stations`·`rest-areas`·`highway-incidents`·`airports` 넷이고 각각 `/{feature_id}` 상세가 있다. 그 밖에
`fuel-stations/{feature_id}/price-history`와 `status`(데이터셋별 신선도 + Valkey 연결).

- 목록: 조건 없으면 `feature_id` 사전순 keyset(`cursor`, `limit` ≤ 500). cursor에 세대가 들어 있어 순회 도중
  교체돼도 같은 세대로 끝난다. cursor의 세대는 `current`나 `previous`일 때만 받는다(아무 세대나 읽히지 않게).
  그 세대가 grace를 넘겨 사라졌으면 409 `TRANSPORT_STATE_GENERATION_EXPIRED`(처음부터 다시).
- 근처: `lon`·`lat`·`radius_m`(≤ 50 km) → 가까운 순 `limit`건(`GEOSEARCH … BYRADIUS … ASC COUNT`).
- bbox: `min_lon,min_lat,max_lon,max_lat`(min ≤ max, 한 변 ≤ 1,000 km) → 중심 기준 `BYBOX`. 상자 폭은 적도에
  가장 가까운 bbox 위도에서 잰 동서 거리(그 위도에서 경도 1도가 가장 넓다) + 여유 2%, 높이는 위도 차 + 여유
  2%로 잡아 요청 bbox를 덮게 하고, 값의 좌표로 정확한 bbox를 다시 거른다. 중심에서 가까운 순으로 `limit`건까지라
  같은 요청은 같은 부분집합을 준다.
- 근처·bbox는 cursor 없이 `truncated`로 상한 도달을 알린다. 좌표 없는 돌발은 근처·bbox에 나오지 않는다(목록에는
  나온다).
- 휴게소 응답은 `fuel_prices`(매칭된 휴게소 유가, 없으면 null)와 그 데이터셋의 신선도를 함께 싣는다. 휴게소 유가
  데이터셋이 아직 없으면 `fuel_prices`는 null이고 신선도도 null이다(휴게소 응답은 막지 않는다).
- Valkey 미설정·연결 실패·timeout → 이 표면만 503 `TRANSPORT_STATE_UNAVAILABLE`. 아직 한 번도 적재되지 않은
  데이터셋 → 503 `TRANSPORT_STATE_NOT_LOADED`. 다른 Map 기능과 `/ops/health-deep`은 Valkey를 보지 않는다.
  client는 재시도하지 않는다(redis-py 기본 재시도는 1초 연결 상한을 몇 배로 늘린다).
- 가격 추이: Valkey의 현재가와 함께 transport T4 `GET /v1/service/exports/fuel-stations/{station_key}/price-history`
  (transport ADR-013, 세부 계약 transport `docs/map-service-price-history.md`)를 요청 시 한 페이지씩 전한다.
  `station_key`는 Valkey 주유소 값의 `natural_key`(오피넷 uni_id)다. 설정 플래그
  `KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_ENABLED`(기본 꺼짐)가 꺼졌거나 transport 주소·토큰이 없으면 transport를
  부르지 않는다. 이력 실패는 200으로 현재가를 주고 `history.status=unavailable`과 이유를 싣는다(예외는 cursor를 보낸
  요청의 409 — 아래). 404는
  설정 문제일 수 있어 경고 로그를 남긴다. API 프로세스도 transport 토큰을 갖게 되므로 그 비밀이 놓이는 자리가 하나
  는다. 2026-10-24 T4 정렬(T-STATE-01-T4, 적대 리뷰 2회 반영):
  - 질의 변환: Map `product_code`·`since`·`until`(timezone 필수) → transport `product`·`from`·`to`. `limit`은 **한
    페이지 전체 행 수(유종 합계)** — Map 기본 200·최대 1000(transport 기본 1000·최대 5000). 창 기본값(종료=지금,
    시작=종료 30일 전)·최대 366일·미래 금지는 transport가 정한다.
  - cursor: Map `cursor`는 transport `next_cursor`를 **불투명하게 그대로** 주고받는다(Map이 해석·서명하지 않는다).
    응답 `history.has_more`·`history.next_cursor`(+ `meta.page.next_cursor` 미러), `history.truncated`는 `has_more`와
    같은 호환값(deprecated). transport cursor는 station·product·창·수집 revision·발급 시각을 품는다 — 다음 페이지는
    `product_code`를 첫 페이지와 **똑같이** 보내야 하고(빼거나 바꾸면 422 → `request_rejected`), `since`·`until`은
    빼거나(창은 cursor에서 온다) 첫 페이지와 같은 시각으로 보낸다. cursor는 첫 페이지 발급부터 15분, 그리고 transport
    유가 수집 revision이 그대로인 동안만 유효하다.
  - **409 재시작**: cursor를 보냈는데 transport가 409(수집 revision 변경·cursor 만료)면 Map은 **HTTP 409
    `TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED`**를 준다(목록 표면 `TRANSPORT_STATE_GENERATION_EXPIRED`와 같은 꼴). 소비자는
    이미 누적한 이력 페이지를 버리고 cursor 없이 첫 페이지부터 다시 읽는다 — 다른 revision의 페이지를 이어 붙이면 중복·
    누락이 생긴다. 첫 페이지(cursor 없음)는 이 오류를 내지 않고 늘 200 + 현재가다. cursor 없이 받은 409는
    `upstream_rejected`다. (처음 설계는 200 + `reason=cursor_expired`였으나 페이지를 잇는 소비자가 그 신호를 놓치기
    쉬워 소유자 승인으로 바꿨다.)
  - **`history.status=unavailable`은 이력의 끝이 아니다** — 그때 `has_more=false`는 "이 페이지를 못 읽었다"는 뜻이다.
    페이지를 잇는 소비자는 매 페이지 `status`를 확인하고, unavailable이면 누적분을 완전한 이력으로 쓰지 않는다.
  - unavailable 이유(값 하나에 원인 하나): `disabled`·`not_configured`(부르지 않음), `upstream_not_found`(404),
    `upstream_unsupported`(501), `request_rejected`(422 — 366일 초과·미래 `until`·변조/다른 조건의 cursor),
    `upstream_no_collection`(503 problem의 `meta.source_status=failed` — 성공한 유가 수집 근거 없음), `upstream_timeout`
    (연결·읽기 timeout), `upstream_unavailable`(그 밖의 5xx·연결 실패), `upstream_rejected`(그 밖의 비-200),
    `upstream_contract`(200 본문이 계약과 다름).
  - 계약 검사(`upstream_contract`): 요청과 다른 `station_key`, `meta.item_count`≠행 수, `has_more`/`next_cursor`
    어긋남, `observed_at` 내림차순 위반, timezone 없는 시각, 가격이 JSON number/null이 아니거나 유한하지 않음
    (NaN·Infinity·`1e400`), 보낸 `product`와 다른 유종의 행, 보낸 `from`/`to`(양끝 포함) 밖의 행(보내지 않은 끝은
    transport 기본 창을 추측하지 않고 검사하지 않는다), JSON이 아니거나 너무 깊은 본문, 2 MiB 초과 본문, 깨진·잘린
    gzip·모르는 Content-Encoding, 200 본문의 `source_status=failed`(transport는 failed를 503 problem에만 싣는다 —
    공개 `history.source_status`도 `ok`/`stale`뿐이다).
  - 본문 읽기: 요청은 `Accept-Encoding: identity`(한 페이지 약 100 KB)다. httpx `aiter_bytes`는 받은 gzip 조각을 통째로
    풀어(64 KiB 조각 → 67 MB) 상한을 무력화하므로, 원문을 `aiter_raw`로 붙이기 **전에** 상한을 재고, 그래도 gzip이 오면
    출력 상한을 건 `zlib.decompressobj`로 푼다. 상태 코드를 먼저 본다 — 200만 본문 전체를, 503만 problem의 `meta`를
    64 KiB까지 읽고, 그 밖의 비-200은 본문을 읽지 않고 상태로 분류한다(큰 오류 본문도 cursor 409 신호를 지운다).
  - 응답 필드: `history.generated_at`·`source_collected_at`·`source_status`(`ok`/`stale` — stale이어도 이력을 준다)는
    transport `meta`에서 온다. 행은 `product_code`·`observed_at`·`price`(null 그대로)만 원천이 준다 — 행별
    `collected_at`·`provider_updated_at`은 nullable이고 지금은 항상 null이다(응답 생성 시각으로 채우지 않는다).
  - 휴게소 유가 이력: transport가 저장하지 않아 `…/rest-area-fuel-prices/{station_key}/price-history`는 501이다. Map은
    그 경로를 노출·호출하지 않고 새 표를 만들지 않는다(transport가 501을 주면 `upstream_unsupported`).
  - **운영에서 켜기**: env 값만으로는 안 된다. Manager `docker-compose.yml`의 `kor-travel-map-api` 서비스(origin/main
    `72ee710` 기준 1659~1749행 근처)에는 transport 변수가 없다(Dagster code-server에만 있다) — Manager PR로
    `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL`·`KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN`·
    `KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_ENABLED`를 그 서비스 `environment`에 더해야 한다.
  - **배포 순서**: Manager pair 회전 preflight(`scripts/m05_isolated_e2e.py` `_PAIR_SURFACE_PATHS`)는 admin·full·
    service·user OpenAPI digest를 PinVi vendor와 대조해 다르면 회전을 **거부**한다. 따라서 Map 머지 → PinVi 재vendor
    PR 머지 → 회전 순서다.
  - **PinVi 재vendor 체크리스트**: (1) `apps/api/tests/contract/kor-travel-map-openapi-{service,admin}.json` exact
    재vendor, (2) `apps/api/tests/unit/test_kor_travel_map_transport_contract.py::_EXPECTED_QUERY`의 price-history에
    `cursor`, (3) `apps/api/app/schemas/transport.py::PriceHistoryUnavailableReason`·`PRICE_HISTORY_REASONS`에
    `upstream_unsupported`·`request_rejected`·`upstream_no_collection`·`upstream_timeout`(없으면 `upstream_contract`로
    접힌다), (4) `apps/api/tests/transport_map_fixtures.py::history_body`에 새 필수 필드 `source_collected_at`·
    `source_status`·`has_more`·`next_cursor`(+ `fx.meta`의 `meta.page`), (5) 페이지를 이으면 `product_code` 동일·
    `since`/`until` 생략 또는 동일, 409 `TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED` 처리, unavailable 페이지에서 멈춤.
- Map **admin** OpenAPI(`openapi.json`)에는 모든 표면이 들어가므로 이 route가 추가되면 PinVi 재vendor가 필요하다.

### D7. 운영 값

- env: `KOR_TRAVEL_MAP_VALKEY_URL`(`redis://:password@host:port/0`, 비밀 — 로그·오류 메시지에 싣지 않는다),
  `KOR_TRAVEL_MAP_VALKEY_CONNECT_TIMEOUT_SECONDS`(기본 1), `KOR_TRAVEL_MAP_VALKEY_SOCKET_TIMEOUT_SECONDS`(기본 2),
  `KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_ENABLED`, `KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_TIMEOUT_SECONDS`(기본 5).
  API는 가격 추이 때문에 transport 주소·토큰(`KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_{BASE_URL,SERVICE_TOKEN}`)도
  받아야 한다.
- 클라이언트 라이브러리: `redis`(redis-py 7.x, `redis.asyncio`, `py.typed` 포함, MIT). Valkey는 RESP 호환이다.
  `valkey`(valkey-py) 포크도 같은 타입 정보를 갖지만 유지 인력이 더 큰 쪽을 골랐다. ADR-030(라이브러리 프로세스
  내부 캐시 금지)과는 부딪히지 않는다 — Valkey는 이 데이터의 저장소이지 PG 앞의 캐시가 아니다.
- Valkey OOM(`noeviction`의 쓰기 거부)은 재시도로 풀리지 않는 실패(`state_store_oom`)로, 연결·timeout은 재시도
  가능한 실패(`state_store_unavailable`)로, 동시 교체는 `state_swap_conflict`로 나눠 기록한다.
- 지속성(결정 2의 RDB+AOF)은 Manager 서비스 설정이다. 설계 리뷰 의견: 이 데이터는 원천에서 다시 받을 수 있으므로
  RDB만으로 충분하고 AOF `everysec`의 상시 fsync는 디스크 대기가 부하인 n150에 비용이다. RDB는 TTL을 절대 시각으로
  담아 복원 뒤 grace·build 키가 제때 사라진다. fork 복사분을 위해 컨테이너 메모리 상한을 1 GB보다 넉넉히 둔다.
  최종 선택은 Manager PR이 한다.
- Dagster job 5개(`transport_state_*`)와 schedule 5개는 **기본 STOPPED**다. 켜는 법: Valkey가 배포된 뒤 Dagster UI의
  Schedules에서 켜거나 `dagster schedule start transport_state_<ds>_schedule`. 첫 적재 전에는 REST가 503
  `TRANSPORT_STATE_NOT_LOADED`다.

### 코드 리뷰(적대 2회, 2026-10-23) 반영

1차: HIGH — `allow_shrink` 한 번이 거부를 끝내지 못함(최근 최대가 남음 → 교체 스크립트가 `recent_counts`를 새 개수로
초기화). MED — 죽은 run의 잠금이 2시간 막음(→ run 상한 기반 TTL), ±90 위도가 GEO 오류로 503(→ GEO 범위로 422), grace
만료와 겹친 페이지가 조용히 끝남(→ 값을 풀기 전 세대 재확인, 409), 포인터 두 번 읽기(→ MGET). LOW — 재시도할 수 없는
응답 오류 분류, 동시 첫 요청의 pool 누수(→ async 의존성), 버전 정리가 새 버전까지 거둠(→ 옛 버전만), cursor를
데이터셋에 결박, 한 데이터셋 고장이 `status`·휴게소를 막음.
2차: HIGH 없음. MED — 한 데이터셋의 첫 새 버전 교체가 다른 데이터셋의 옛 키까지 거둠(→ 데이터셋별), 형식이 틀린 Valkey
URL이 500과 비밀번호 조각을 남김(→ 미설정 503, 원 예외 끊음), 1차 수정 일부가 검사되지 않음(→ 통합 검사 추가), 가격
추이의 잘못된 transport 주소가 500(→ `not_configured`). LOW — cursor 경로의 값 누락 503→409, 깨진 메타·바이트, 검증
순서(422가 store보다 먼저), 잠금 TTL에 취소 유예, admin 기본 cron 표, `.`/`..` 경로 키, 문서 불일치.
**남긴 것**: 절대 하한(휴게소 100·휴게소 유가 80·공항 10)은 실측 전 추정이다 — schedule을 켜기 전에 live 개수와
대조한다(acceptance §T-STATE-01). 하한은 영구 기준이라 진짜 규모가 그 아래면 매 tick 거부된다(`allow_shrink`는 한 번만).

### 설계 리뷰(적대 1회, 2026-10-23)

HIGH 4 — 같은 id 행이 `HLEN` 검사를 영구 실패시킴(→ 고유 id 기준·첫 행·`duplicates`), BYBOX 폭을 중심 위도에서
재면 남쪽 모서리가 빠짐(→ 적도 쪽 위도 폭·크기 상한), 스키마 버전 교체 뒤 옛 키가 남음(→ 다른 버전 접두사 정리),
개수 검사가 교체 밖에 있고 `meta`만 존재 검사(→ Lua 안에서 `meta` 개수와 대조, `meta`가 유일한 존재 표지). MED —
직전 하나와의 비율은 여러 번 나눠 줄면 뚫림(→ 최근 6번 최대·절대 하한), 범위 밖 좌표가 GEO 쓰기를 통째로 깸(→ 범위
검사), 주유소 값의 id 모호(→ place id 명시), private 함수 의존(→ `krex` 공개 이름), 동시 적재(→ 잠금·실패 시 정리·
실패 분류), 지속성 비용(→ Manager에 의견). LOW — cursor 세대 위조(→ `current`/`previous`만), lookup 덮어쓰기(→ 첫
행), client 재시도(→ 끔), 신선도 혼합(→ 이른 쪽). 가격 추이 플래그 제거 의견은 받지 않았다 — transport 경로가 배포되기
전에 켜지지 않게 하는 스위치가 필요하다(소유자 요구).

## 구현 설계 — 2단계: weather (2026-10-24, 이행 순서 3의 weather 부분)

1단계의 세대 교체 store(`infra/valkey_state.py`)·키 규약(D2)·교체 순서(D3)·거부 기준(D4)을 **그대로** 쓴다. 바뀌는 것은
원천(kor-travel-weather의 Map용 export W1~W5)·데이터셋·값 모양·REST다. 1단계와 다른 점만 W-번호로 적는다.

### W0. 원천 계약(weather main `7aa7e70`, W1~W5 producer 머지 완료 — 운영 활성화는 별도)

weather `GET /v1/service/exports/{locations,current,forecasts,daily-summaries,status}`. 인증은 weather의 기존 관리자
header `X-Admin-Token`(값 = weather `KOR_TRAVEL_WEATHER_ADMIN_TOKEN`)이고 실패는 **401**이다(transport의 404 은닉과 다르다).
응답은 `{items, meta}`이고 `meta`는 `generated_at`·`source_collected_at`(null 가능)·`source_status`(`ok|stale|failed`)·
`item_count`(페이지 항목 수)·`snapshot_id`·`next_cursor`·`has_more`·`next_since`다. 페이지는 `limit` ≤ 5,000(기본 500)과
본문 4 MiB 중 먼저 닿는 쪽까지이고, cursor는 서명된 불투명 값(TTL 15분)이다. 오류: 503 = 완결된 성공 export 없음
(`EXPORT_NOT_READY` — 빈 정상 집합이 아니다), 410 = snapshot 만료(첫 페이지부터 다시), 422 = cursor 위조·도중 필터 변경.
gzip·약한 ETag/304를 지원한다(Map은 첫 페이지에만 `If-None-Match`를 보낸다 — 아래 W3).

| export | 항목 하나 | 주요 필드 |
| --- | --- | --- |
| W1 `locations` | 위치 1곳 | `location_id`·`name`·`latitude`·`longitude`(null 가능)·`legal_dong_code`(10자리, null 가능)·`sido_name`·`sigungu_name`. `source_collected_at`은 언제나 null·`source_status=stale`(카탈로그 수집 시각을 알 수 없다 — weather가 꾸미지 않는다) |
| W2 `current` | 위치×provider×metric 최신 관측 1값 | `location_id`·`provider`·`metric_key`·`value`(수·문자열·null)·`unit`·`target_at`·`known_at`·`forecast_style`(`observed`·`nowcast`) |
| W3 `forecasts?style=` | 위치×provider 예보 묶음 1개 | `location_id`·`provider`·`forecast_style`(`ultra_short`·`short`·`mid`·`external`)·`known_at`·`published_at`·`target_at[]`(오름차순, **응답 시각 이후만**)·`metrics{metric: 값[]}`(target_at과 같은 길이, null 정렬) |
| W5 `daily-summaries?days=` | 위치×날짜×구간 1개 | `location_id`·`date`·`slot`(`morning` [05,11)·`noon` [11,17)·`evening` [17,23) KST)·`temp_min/max/avg`·`humidity_avg`·`precip_sum_mm`·`precip_occurred`·`sky_code`·`wind_speed_avg`·`sample_count`(0~6, 관측 시간 bucket 수)·`source_providers[]`·`partial`. `days` 기본 14, 최대 31 |
| W4 `status` | provider×dataset×style 수집 상태 | Map은 적재에 쓰지 않는다(운영 진단용) |

2026-10-24 live 확인: odroid weather API는 `3a0ae398`(W1~W5 이전)이라 `/v1/service/exports/*`가 404다 — 이 계약은 소스·
OpenAPI·weather 저장소의 실제 HTTP 예시(`docs/examples/map-service/`)로 맞췄고, live 대조는 weather 배포·
`KOR_TRAVEL_WEATHER_SERVICE_EXPORTS_ENABLED=true` 뒤 schedule을 켜기 전에 한다(acceptance §T-STATE-02).

### W1. 데이터셋과 식별자

| 데이터셋(`{ds}`) | 원천 | 값 하나(= 위치 하나) | GEO | 교체 거부(절대 하한 · 비율 · 비율 적용 기준) | 신선도 상한 | schedule(KST) |
| --- | --- | --- | --- | --- | --- | --- |
| `weather.locations` | W1 | 위치 + 주소(시도·시군구·법정동) | 좌표 있는 것 | 1,000곳 · 90% · 100 | 8일(`loaded_at` 기준) | 매일 04:37 |
| `weather.current` | W2 | 그 위치의 최신 관측 값 목록 | 없음 | 500곳 · 80% · 50 | 3시간 | 매시 :25·:40 |
| `weather.forecast_ultra_short` | W3 `ultra_short` | 그 위치의 provider별 예보 묶음 | 없음 | 500곳 · 80% · 50 | 3시간 | 매시 :48 |
| `weather.forecast_short` | W3 `short` | 〃 | 없음 | 1,000곳 · 90% · 100 | 12시간 | 하루 8회 02·05·…·23시 :30 |
| `weather.forecast_mid` | W3 `mid` | 〃 | 없음 | 300곳 · 80% · 50 | 36시간 | 06·07·18·19시 :40 |
| `weather.forecast_external` | W3 `external` | 〃 | 없음 | 없음 · 80% · 50(기준 미만이면 0곳 허용) | 12시간 | 3시간마다 :55 |
| `weather.daily_summaries` | W5 `days=N` | 그 위치의 (날짜, 구간) 요약 목록 | 없음 | 1,000곳 · 90% · 100 | 6시간 | 매시 :41 |

- **항목 단위는 위치**다(D2 "묶음 단위"). 한 위치의 관측·예보·요약은 각 데이터셋에서 필드 하나(`HGET` 하나)다. provider가
  여럿이면 값 안에 묶음 배열로 든다(외부 예보). 그래서 데이터셋 일곱 개가 **같은 `feature_id`**를 키로 쓴다.
- `feature_id` = `make_feature_id(bjd_code=None, kind="weather", category="99000000", source_type=
  "kor-travel-weather:locations", source_natural_key=location_id)`. category·marker(`weather`·`P-01`)는 ADR-105 전
  KMA 격자 weather feature의 sentinel과 같다(정의는 ADR-105가 남겼다). `bjd_code=None`인 이유는 1단계 D1과 같다 —
  결정 6에 따라 weather가 준 법정동은 **값의 주소 속성**(`address.bjd_code`)으로만 그대로 쓰고 geo를 다시 부르지 않으며,
  id는 바뀌지 않는다. PG feature가 아니므로 identity claim·seal이 없다.
- GEO는 `weather.locations` 하나다. 근처·영역 검색은 그 GEO로 위치를 찾고 다른 데이터셋은 같은 id로 `HMGET`한다
  (1단계 휴게소 유가와 같은 읽기 결합). 데이터셋마다 세대가 따로 돈다 — 예보 export가 죽어도 위치·관측은 갱신된다.
- 한 집합에 같은 위치가 두 번 오면(묶음 경계·재시도) 위치 단위로 합친다: 관측은 (provider, metric) 첫 행, 예보는
  (provider) 첫 묶음, 요약은 (date, slot) 첫 행을 남기고 버린 수를 op metadata `row_duplicates`에 적는다(세대 `meta.duplicates`는
  1단계처럼 같은 위치 id가 두 번 온 수다 — 위치 단위로 묶은 뒤라 0이다). 위치 W1에 없는 id가
  W2/W3/W5에 와도 그대로 담는다(카탈로그 갱신 순서가 다를 수 있다) — 읽기는 W1에 있는 위치만 찾을 수 있다.
- 묶음의 `target_at`과 metric 배열 길이가 다르거나, `target_at`이 오름차순이 아니거나, 묶음의 style이 요청 style과
  다르거나, 시각에 timezone이 없으면 계약 위반으로 적재를 실패시킨다(Valkey에 쓰지 않는다).
- 좌표 범위는 D1과 같다(한국 주변 밖·(0, 0)이면 좌표 없음 — 그 위치는 근처·영역에 나오지 않는다).
- `location_id`에 `|`나 제어 문자가 있으면(`make_feature_id`가 받지 않는다) 그 페이지 전체가 계약 위반이고 run은 재시도
  없이 실패한다 — 그 행만 빼고 교체하면 위치 하나가 조용히 사라지기 때문이다(코드 리뷰 2026-10-24).
- schedule은 weather 공개 시각 뒤에 맞췄다(운영 리뷰 2026-10-24): 관측은 weather 승격(매시 :20·:35 무렵) 뒤 :25·:40,
  초단기는 매시 발표 뒤 :48, 단기는 발표(02·05·…·23시) 뒤 :30에 하루 8회, 중기는 발표(06·18시) 뒤 :40과 한 시간 뒤 한 번
  더, 외부는 3시간마다. 공개 시각은 운영 실측으로 다시 맞춘다(acceptance §T-STATE-02).

### W2. 키·값

D2 키 표를 그대로 쓴다(`ktm:state:v1:weather.<…>:…`). `weather.locations`의 `lookup`은 weather `location_id` →
`feature_id`다(PinVi가 이미 가진 weather 위치 id로 찾는 배치 route용, W7). 메타에 `source_status`(W4)·`source_etag`·
`checked_at`(W3)를 더한다 — 1단계 세대에는 이 필드가 없고 읽는 쪽은 없으면 null로 본다(키 버전을 올리지 않는다: 값
모양이 아니라 메타 hash에 필드가 느는 것이다). 값은 `kortravelmap.dto.weather_state` Pydantic 모델의 JSON이고 REST가 같은 모델을 쓴다.

### W3. 쓰기

D3 그대로(잠금 → 원천 끝까지 → 거부 검사 → build TTL로 쓰기 → Lua CAS 교체). weather 쪽 차이:

- 받을 때는 **전량**이다. W3의 `since` 증분(`meta.next_since`)은 쓰지 않는다 — 세대 교체는 전체 집합이 있어야 하고,
  증분을 쌓으려면 Map이 직전 세대와 병합해야 해서 원자 교체·거부 검사의 단순성을 잃는다. 비용이 문제로 드러나면 그때
  증분을 따로 설계한다.
- **ETag**: 교체한 세대 meta에 첫 페이지 ETag(`source_etag`)를 적고, 다음 run은 첫 페이지에 `If-None-Match`로 보낸다.
  304면 받지도 교체하지도 않고 지금 세대 meta의 `checked_at`만 Lua로 적는다(포인터가 그 세대일 때만). weather 코드
  확인(main `7aa7e70`): ETag는 `snapshot_id`·manifest digest·페이지·상태(예보는 본문까지)의 digest이고, 같은 승인 집합이면
  같은 snapshot을 **TTL 15분 동안만** 재사용한다 — 그 뒤에는 내용이 같아도 새 `snapshot_id`가 되어 ETag가 바뀐다. 그래서
  304는 직전 확인과 15분 안에 같은 집합을 다시 볼 때만 난다(관측 :25→:40처럼). 그보다 긴 주기에서는 거의 매번 전량을
  받는다 — 운영 비용은 schedule 주기(위 W1)로 줄인다. `allow_shrink` run은 ETag를 보내지 않는다(강제 재적재).
- 페이지 내내 `snapshot_id`가 같아야 한다(다르면 계약 위반). **410**(snapshot 만료)이나 **둘째 페이지 이후의 422**(순회
  도중 weather가 재배포돼 provider 선택·cursor 서명이 바뀐 경우)면 첫 페이지부터 **한 번** 다시 받는다 — 두 번째도
  410이면 재시도 가능한 실패, 두 번째도 422면 재시도 없는 계약 위반이다. 첫 페이지 422는 질의 계약 위반(재시도 없음).
  503은 재시도 가능한 실패(`weather_not_ready` — weather의 다음 성공 승격에서 풀린다), 401·404·그 밖의 4xx·JSON 아님·
  계약 위반·조건 없는 304는 step 재시도를 끄는 실패다(401 = 토큰, 404 = W1~W5가 없는 weather 버전). 429와 503을 뺀
  5xx(500 포함)·연결 오류는 HTTP 층에서 유한 재시도하고, 다 쓰면 step 재시도 대상이다(1단계 transport fetcher와 같은
  예산·계수 규약).
- 요청 수는 시도마다 센다(`note_upstream_request`, ADR-097 분자).

### W4. 신선도

- `meta.source_collected_at` = 페이지들의 `source_collected_at` 중 가장 이른 값. 한 페이지라도 null이면 null(weather 규약:
  하나라도 미확정이면 집계도 null). `meta.source_status` = 페이지들 중 가장 나쁜 값(`stale` > `ok`). `failed`는 weather가
  503으로 주므로 성공 페이지에 나오면 계약 위반이다.
- `stale` 응답(마지막 성공 집합을 그대로 준 것)도 교체한다 — 내용은 직전 성공 집합이고 `source_collected_at`이 옛
  시각이라 Map 신선도의 `stale`이 그대로 드러난다. 교체를 거부하면 Map 쪽 나이만 늘 뿐 정보가 없다.
- 응답 신선도는 1단계 필드에 `source_status`·`checked_at`을 더한다. `stale = age_seconds > max_age_seconds`이고 age는
  `source_collected_at`(없으면 `checked_at`, 그것도 없으면 `loaded_at`) 기준이다 — W1 위치는 원천이 시각을 주지 않아 304
  확인 시각이나 교체 시각 기준이다.
- **위치 roster의 `source_status`는 null(해당 없음)이다.** weather W1은 카탈로그 수집 시각을 알 수 없어 언제나 `stale`·
  `source_collected_at=null`을 보낸다 — 그대로 내보내면 PinVi가 모든 위치를 stale로 표시한다. 그래서 Map은 그 데이터셋의
  값을 싣지 않고(데이터셋 정의 `reports_source_status=False`), 세대 meta에는 원값을 남긴다(운영 진단용).

### W5. 지난 예보 시각 제거

W3 export는 응답 시각 이후 `target_at`만 주지만 Map 세대는 다음 교체까지 늙는다. **읽을 때** 지금보다 이른 `target_at`과
그 자리의 metric 값을 떼고, 남는 시각이 없는 묶음은 뺀다(결정 1 "예보는 시각이 지나면 지운다"). 요청이 `from`·`to`
(aware 시각)를 주면 그 창 밖도 뗀다(`from`이 지금보다 이르면 지금). 세대 값 자체는 불변이고
다음 교체가 지난 시각 없는 집합으로 바꾼다. 단기예보 상한 12시간이면 최악 12시간 치를 읽을 때 걸러 낸다.

### W6. 메모리 추정(n150 Valkey `maxmemory 1gb`·`noeviction`)

odroid 실측 값 수(컨텍스트 절)에 JSON 크기를 곱한 **추정**이다(배포 뒤 `MEMORY USAGE`·`INFO memory`로 journal에 실측을 적는다).

| 데이터셋 | 원천 값 수 | 세대 하나 추정 |
| --- | --- | --- |
| locations | 약 1,450곳 | 0.5 MB(GEO 포함) |
| current | 약 3.2만 값 | 4 MB(값마다 provider·metric·시각 문자열) |
| forecast_short | 약 179만 값 | 15 MB(배열 값 약 6 B + 시각 배열) |
| forecast_ultra_short + mid | 약 6만 값 | 1 MB |
| forecast_external | 미측정(W1 위치 중 외부 provider 지점) | 상한 가정 15 MB |
| daily_summaries | 1,450 × 3 × 14 ≈ 6.1만 항목 | 12 MB |
| **합계** | | **약 48 MB**(외부 예보 상한 가정 포함) |

벌 수(운영 리뷰 2026-10-24 정정): 지금 세대 + grace(15분) 중인 직전 세대 + 쓰는 중인 새 세대 = 데이터셋마다 **최대 세
벌**이다. 15분보다 짧은 주기(관측 :25→:40)에서는 grace가 끝나기 전에 다음 교체가 와서 직전 세대가 둘 남을 수도 있다
(교체마다 그 직전 하나만 grace를 받으므로 네 벌 상한). 그 위에 죽은 run의 build 키가 build TTL(2시간) 동안 남는다 —
잠금이 데이터셋마다 하나라 그 사이 다른 build는 잠금 TTL 뒤에만 시작한다. 최악을 단순 합으로 잡으면 일곱 데이터셋 ×
네 벌 ≈ 190 MB, 죽은 build 키 한 벌씩 더해 약 240 MB다. 1단계 transport의 같은 최악(약 60 MB)과 합쳐 300 MB 남짓으로
1 GB의 30% 아래다. `noeviction` 쓰기 거부는 `state_store_oom`(재시도 없음)으로 드러난다(D7). 실측(`INFO memory`)은
schedule을 켠 뒤 journal에 적는다.

### W7. 읽기 — Map REST(service 표면, PinVi용)

`/v1/service/weather/…`, `X-Kor-Travel-Map-Service-Token`(1단계와 같은 `require_service_token`). PinVi가 장소 하나에 날씨를
붙이는 흐름(좌표 → 가까운 위치 → 관측·예보·요약)을 요청 하나로 끝내게 한다.

| route | 내용 |
| --- | --- |
| `GET /locations` | 위치 목록·근처(`lon`·`lat`·`radius_m` ≤ 100 km)·영역(bbox) — D6과 같은 keyset cursor·`truncated`. `include_current=true`면 각 위치에 최신 관측을 붙인다(지도 마커용) |
| `GET /locations/{feature_id}` | 위치 하나의 **묶음**: 위치 + 관측 + 예보(style별, 지난 시각 제거, 선택 `from`·`to`) + 세 구간 요약(전날 같은 구간 대비 차이 포함) |
| `POST /locations/batch` | `feature_ids`·weather `location_ids`(둘 다 써도 된다, 합 ≤ 50 — id마다 경로 `feature_id`와 같은 모양·weather `location_id`와 같은 길이·문자 검사)의 묶음 목록과 `missing`. 같은 `sections`·`forecast_styles`·`forecast_from`·`forecast_to` |
| `GET /nearest` | `lon`·`lat`·`radius_m`(기본 20 km, ≤ 100 km — PinVi는 20 → 50 → 100 km로 넓힌다) 근처 위치를 가까운 순으로 보고(관측·요약은 **최대 10곳**, 예보는 **최대 50곳** — 예보 없는 측정소가 KMA 격자보다 가까이 여럿 몰린 도심 대비), **부분마다** 그 데이터셋 값이 실제로 있는 가장 가까운 위치를 고른다. 위치가 없으면 404 |
| `GET /status` | Valkey 연결과 데이터셋 일곱 개의 신선도(실패한 데이터셋은 원 메시지 대신 `failure_kind` 코드) |

- **부분마다 위치를 고르는 이유**(운영 리뷰 HIGH, 2026-10-24): 가장 가까운 weather 위치가 대기질 측정소처럼 예보가 없는
  지점인 경우가 흔하다 — 위치 하나만 고르면 KMA 예보가 조용히 빠진다(PinVi는 그래서 지금 위치 id를 모두 모아 합친다).
  각 부분은 `source{feature_id, location_id, distance_m}`로 값이 온 위치를 알린다. 깨진 후보는 건너뛰되 끝내 값이 없고
  깨진 후보가 있었으면 `unavailable`이다. `/locations/{feature_id}`·배치는 그 위치 하나만 본다.
- 묶음의 데이터셋 읽기는 후보·배치 위치를 모두 합쳐 Valkey 왕복 두 번이다(포인터 `MGET` → meta·값 pipeline,
  `ValkeyStateStore.read_many`).

- 묶음의 각 부분(`current`·`forecasts.<style>`·`daily_summaries`)은 `{status, freshness, …}`이고 `status`는
  `ok`·`not_loaded`(아직 한 번도 적재 전)·`unavailable`(그 데이터셋만 읽지 못했거나 **저장 값이 모델과 맞지 않음** —
  위치 값이 깨지면 503인 것과 같은 판정, 빈 데이터로 꾸미지 않는다)·`no_data`(데이터셋은 있으나 후보 위치에 항목이 없음)다 — 한 데이터셋 장애가 묶음 전체를 막지 않는다(1단계 휴게소 유가와 같다). `sections`·`forecast_styles`로
  필요한 부분만 고를 수 있다.
- 세 구간 요약의 `partial`은 **읽는 시각으로 다시 계산한다**: KST 구간 끝(`dto.weather_state.daily_slot_bounds` —
  아침 [05,11)·점심 [11,17)·저녁 [17,23)) 전이면 언제나 partial이고, 끝났어도 weather가 적재 때 partial로 줬으면 partial로
  남긴다(그 세대 요약은 구간 도중에 계산된 값이라 다음 교체 전까지 실제로 덜 모였다).
- 각 항목은 `vs_previous_day{previous_date, temp_min_delta, temp_max_delta, temp_avg_delta, humidity_avg_delta}`를 싣는다 —
  전날 같은 구간과의 차이(이쪽 − 전날). 전날 구간이 없거나, 둘 중 하나가 `sample_count=0`이거나, **둘 중 하나가 partial이면
  null**이다 — 06:30의 아침(1시간 반 치)을 끝난 어제 아침(6시간 치)과 비교하면 "어제보다 춥다"가 거짓이 될 수 있다.
  판단(문턱값·문구)은 소비자가 한다. **보관 일수 `KOR_TRAVEL_MAP_WEATHER_DAILY_SUMMARY_DAYS=1`이면 전날 구간이 없으므로
  `vs_previous_day`는 언제나 null이다** — 비교가 필요하면 2 이상(기본 14)으로 둔다.
- 예보 `to`(배치는 `forecast_to`)가 이미 지난 시각이면 422다 — 조용한 `no_data` 대신 요청 오류로 알린다.
- weather 특보(`weather_alert`)는 범위 밖이다 — PinVi는 특보를 계속 weather에서 직접 읽는다.
- 위치 데이터셋이 없거나 Valkey가 죽었으면 503(`WEATHER_STATE_NOT_LOADED`·`WEATHER_STATE_UNAVAILABLE`), cursor 세대가
  사라졌으면 409 `WEATHER_STATE_GENERATION_EXPIRED`, 지금 세대에 그 위치가 없으면 404 — 1단계 D6과 같은 규칙.
- 이 route들은 ADR-105의 "Map은 weather를 서빙하지 않는다" 검사(`test_api_serves_no_weather.py`)에 걸린다. 이 ADR이
  ADR-105를 부분 대체하므로 검사는 **이 표면 하나만** 예외로 둔다: `/v1/service/weather/` 아래 경로와 거기서만 닿는
  스키마. PG feature 표면(공개·admin·feature 응답)은 그대로 weather를 내보내지 못한다.
- admin OpenAPI(`openapi.json`)와 service OpenAPI가 바뀐다 → **PinVi 재vendor**(1단계와 같은 receipt에 덧붙인다).

### W8. 운영 값

- env(Dagster code-server만 — API는 weather를 부르지 않는다): `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_BASE_URL`(odroid
  weather API, 기본 `http://<prod-host-ip>:12201`), `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_SERVICE_TOKEN`(비밀 — weather
  `KOR_TRAVEL_WEATHER_ADMIN_TOKEN`과 같은 값), 선택 `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_AUTH_HEADER`(기본 `X-Admin-Token`),
  `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_{TIMEOUT,CONNECT_TIMEOUT}_SECONDS`(기본 60·4), `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_PAGE_SIZE`
  (기본 2,000, ≤ 5,000), `KOR_TRAVEL_MAP_WEATHER_DAILY_SUMMARY_DAYS`(기본 14, 1~31 — 결정 1의 "소유자가 바꿀 수 있는 보관
  기간"). Map API는 Valkey URL만 있으면 된다(1단계에서 이미 받는다).
- **Manager 변경(이 PR 밖, 정확히)**: Map Dagster code-server 서비스 environment에
  `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_BASE_URL: ${KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_BASE_URL:-http://<prod-host-ip>:12201}`와
  `KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_SERVICE_TOKEN: ${KOR_TRAVEL_WEATHER_ADMIN_TOKEN:?…}`(같은 `.env` 값 재사용)를 더하고,
  Manager `.env.example`과 계약 검사 `backend/tests/test_consumer_origin_defaults.py`(consumer origin 기본값 표)·
  `backend/tests/test_docker_service_config.py`(서비스별 env 렌더 대조)를 함께 고친다. Map API 서비스에는 넣지 않는다.
- **받아들인 위험 — weather 관리자 토큰**: Map은 weather의 `X-Admin-Token`을 쓴다. 그 토큰은 weather 관리자 **쓰기**
  권한도 주고 weather export cursor의 HMAC 서명 키도 겸한다 — Map code-server가 털리면 weather 관리 표면까지 열린다.
  weather가 읽기 전용 export 토큰을 낼 때까지의 받아들인 위험이다. header 이름을 설정(`…_AUTH_HEADER`)으로 뺐으므로
  범위가 좁은 토큰으로 바꿀 때 Map 코드 변경은 없다(env 두 개만 바꾼다).
- Valkey 지속성: Manager 설정(RDB `save 3600 1 300 100 60 10000` + AOF `everysec`)에서 weather 데이터셋이 더해지면 쓰기량이
  는다(단기예보 15 MB 세대 하루 8번 등) — `save 60 10000` 조건이 자주 걸려 n150 디스크 대기가 늘 수 있다. schedule을 켠 뒤
  `INFO persistence`(`rdb_changes_since_last_save`·`aof_rewrites`)와 n150 iowait를 재서 journal에 적고, 필요하면 Manager에서
  AOF를 끄거나 save 조건을 늦춘다(D7 설계 리뷰 의견과 같다).
- **회전 순서**: #1365(transport 가격 추이 T4)와 이 PR이 **둘 다** 머지된 뒤의 정확한 Map commit에서 PinVi가 admin·service
  스냅샷을 **한 번** 재vendor한다(1단계 transport 재vendor 대기분을 함께 접는다) → 그다음 Manager pair 핀.
- weather 쪽 선행: W1~W5가 든 weather 배포와 `KOR_TRAVEL_WEATHER_SERVICE_EXPORTS_ENABLED=true`(API·code-server 함께),
  artifact root 공유 — weather 저장소의 운영 수용 항목이다.
- Dagster job 7개(`weather_state_*`)와 schedule 7개는 **기본 STOPPED**다. 켜기 전에 W1 표의 절대 하한(전부 실측 전
  추정)을 weather live 개수와 대조한다.
- 범위 밖: PinVi 전환(이행 순서 4, odroid weather 직접 호출 제거), weather W4 `status`의 Map 노출, W3 증분, weather 특보.

### 코드·운영 리뷰(2026-10-24) 반영

정확성 리뷰(차단 없음): 깨진 저장 값 → `unavailable`, `partial` 읽기 시각 재계산(KST 경계), partial 구간의 전날 비교 null,
429·5xx 재시도, `|` location_id는 재시도 없는 계약 위반, 순회 도중 422 한 번 재시작, roster `source_status` null. 운영·
소비자 리뷰: 부분별 nearest(HIGH)·100 km 반경(weather 전용 상수 — transport 모듈을 import하지 않는다)·배치 route와
pipeline 읽기·예보 시간 창·`location_id` lookup·ETag 304와 schedule 정렬·`/status` 오류 코드화·벌 수 정정·토큰 위험과
header 설정·지속성·회전 순서·Manager env.

### 기존 PG weather feature

ADR-105가 Map의 weather feature 적재·스키마·데이터를 이미 지웠다(2026-10-01, prod 0행). 그래서 2단계에는 퇴역할 PG
weather 적재가 **없다** — 결정 7(퇴역)은 transport에만 남는다. ADR-105의 재도입 방지 검사는 PG feature 경로(카탈로그
weather operation·client 쓰기·KMA provider import·API 이름)를 계속 지키고, 이 Valkey 표면만 위 W7대로 예외다.

## 결정 7 이행 — PG transport 퇴역 (2026-10-24, T-STATE-03)

### 소비자 확인 (2026-10-24, 읽기 전용 실측)

- **prod Map DB**(alembic `409`): transport 출처 Feature 26,293건 — 주유소 place 11,820·주유소 유가 price 11,822·
  휴게소 place 215·휴게소 유가 price 219·돌발 notice 2,202(그중 원천 종료 시각 없는 활성 320)·공항 place 15. 전부
  `active`/`published`. 다른 provider와 병합된 것 0, curation item·theme 후보·override·merge 이력·POI cache 링크·
  reference reconciliation event 0. 가격 fact 30,983·source record 37,483. 마지막 적재: 돌발 매 10분(그날 08:00Z),
  휴게소 유가 10-22, 주유소 유가·장소 10-12, 공항 10-03.
- **prod Valkey**: `/v1/service/transport/status` 다섯 데이터셋 모두 `loaded=true`·`stale=false`(주유소 11,833·
  휴게소 215·휴게소 유가 226·돌발 330·공항 15).
- **PinVi**(GitHub main `ff64b65`, 읽기 전용): 교통 레이어는 Map `/v1/service/transport/*`만 읽는다(ADR-076,
  `transport_layers.py`). 그러나 **일반 지도·검색·근처**가 Map `/v1/features/{in-bounds,search,nearby}`를 부르고 in-bounds
  기본 kind가 `place·event·notice·price`다(`api/v1/features.py::_DEFAULT_INBOUNDS_KINDS`) — PG transport Feature가 교통
  레이어와 **중복으로** 그려지고, 공항·휴게소·주유소 이름 검색·근처는 PG place에서만 나온다(Valkey 표면에는 이름 검색이
  없다). PinVi DB의 Map feature 참조(`trip_day_pois`·`curated_plan_pois`·`weather_location_links`·reference
  reconciliation)는 **0행**이다(transport 출처만이 아니라 전체가 0).
- **Map 내부**: C7 운영 게이트가 `feature_place_transport_airports_monthly_schedule`·`feature_place_transport_airports_job`
  을 "외부 호출 0"의 안전한 schedule·갱신 요청 대상으로 고정한다(`scripts/run-c7-prod-live-e2e.sh`, `e2e/live/ops-c7-*`).
  admin UI의 price 패널·마커는 price kind 일반 기능이다(남는다 — 정의).

### 세 단계

| 단계 | 무엇 | 해제 조건 |
| --- | --- | --- |
| ① (이 PR, migration `411_retire_pg_transport_prices_incidents`) | 유가 둘·돌발 하나의 PG 적재(asset·job·schedule·큐 runner spec·handler binding·preview fixture)를 지우고, 그 dataset의 operation을 종류 불문 끄고, 그 Feature를 퇴역한다 | Valkey 다섯 데이터셋 적재 중(충족) |
| ② | 장소 셋(주유소·휴게소·공항)의 PG 적재 종료 + 퇴역 | PinVi가 일반 in-bounds 기본 kind에서 transport 중복을 빼고 장소 이름 검색 대체를 정함(또는 소유자가 손실을 받아들임), C7 안전 대상을 공항 job 밖으로 옮김 |
| ③ | 물리 삭제(402와 같은 모양 — Feature·source lineage·가격 fact·notice 계보), dataset 비활성, 남은 PG 변환 코드(`providers/opinet.py`·`krex.py` 유가·돌발·`krairport.py`의 PG 경로)와 notice 계보 함수의 돌발 분기 정리 | ②가 배포되고 관찰 기간(1주 이상)에 되돌릴 일이 없었음, 소유자 확인(비가역) |

①이 시간에 민감한 값부터 하는 이유: 적재를 멈추고 남겨 두면 **틀린 값**을 보여 준다 — 지도 API는 오래된 유가도 날짜와 함께
그리고, 종료 시각 없는 돌발은 다음 적재가 닫아 주지 않으면 영원히 진행 중이다. 장소는 천천히 바뀌고 아직 소비자가 있다.

### ①의 방법 — 무엇이 실행되는가

- **퇴역 = soft-delete**: `feature.transition_feature_state`(감사·불변 trail의 정본 상태 전이)를 `transition_kind='system'`,
  `reason_code='adr114_transport_state_moved_to_valkey'`, `principal='system/alembic-411_retire_pg_transport_prices_incidents'`,
  `causation_ref='ADR-114 decision 7 phase 1'`로 부른다 → `lifecycle_state='retired'`·`publication_state='suppressed'`. 프로시저가
  같은 전이에 lifecycle override(`prevent_provider_reactivation=true`)를 붙인다 — provider 부재가 아니라 결정이므로 provider
  tombstone으로 위장하지 않고, 적재가 실수로 되살아나도 다시 켜지지 않는다. 프로시저는 advisory lock을 잡지 않는다(행 잠금만,
  ADR-111 lock table 문제 없음).
- **대상은 정체성으로**: provider `kor-travel-transport` + `capabilities.produces`에 price·notice인 dataset, 그 entity에 `primary`
  link로 묶인 `active` Feature(prod 약 14,240건).
- **남기는 것**: Feature 행·source lineage·가격 fact·notice 계보·alias·상태 전이 감사·카탈로그 행. **dataset은 활성으로 둔다**
  (401과 같다 — 비활성은 물리 삭제 단계의 일이고, 활성 가드가 그때 DELETE까지 막는다).
- **seal**(기각 대안의 첫 함정): 전이는 `current_provider_curation_input_set` 입력을 바꾼다. 진행 중인 대상 적재가 있으면 그 root가
  `stale_input`으로 실패하므로 preflight가 queued/running job을 막는다. 이미 실패로 끝난 root의 미완 영수증(prod 돌발 3건)은 다시
  대조되지 않는다. 두 번째 함정(runtime 역할의 증거 표 읽기)은 해당이 없다 — 퇴역은 migration 안에서 schema owner·state procedure
  owner 창으로 한다.
- **preflight**(하나라도 있으면 아무것도 바꾸지 않음): 대상 operation member의 queued/running job, 대상 밖 dataset에도 primary
  출처가 있는 대상 Feature, 활성 lifecycle override가 있는 대상 Feature. **사후 조건**: 켜진 대상 operation 0, active 대상 Feature 0,
  퇴역 전이 수 = preflight 대상 수.

### ①의 운영 runbook

1. 배포 전: Dagster에서 `feature_price_transport_fuel_stations_daily_schedule`·`feature_price_transport_rest_areas_twice_daily_schedule`·
   `feature_notice_transport_highway_incidents_ten_minute_schedule`를 멈춘다(`dagster schedule stop …` 또는 UI). prod는 큐로도
   돈다(`feature_update_request_queue_sensor` — PinVi cache-target 요청이 targeted run을 낸다). 옛 코드에서 큐까지 닫는 런타임
   스위치는 없으므로(`DISABLED_FEATURE_LOAD_SCHEDULES`는 코드 상수다) admin `/ops/datasets`에서 그 세 dataset의 갱신 정책을
   거부로 두거나, 큐가 비는 순간에 배포한다. 진행 중 run이 끝나기를 기다린다. 확인: `ops.import_jobs`에 그 dataset member의
   queued/running이 0. migration preflight가 같은 것을 다시 잰다 — 남아 있으면 배포가 실패하고 DB는 410 그대로다(그 뒤 다시 배포).
2. 배포(Map API·Dagster code location 같은 pair): 마이그레이션 전진이 411을 실행한다. 한 트랜잭션 — 전부 되거나 전부 안 된다. 예상
   소요는 퇴역 약 1.4만 건의 프로시저 호출(수십 초~수 분, 행 잠금만).
3. 확인: `SELECT reason_code, count(*) FROM feature.feature_state_transitions WHERE reason_code='adr114_transport_state_moved_to_valkey'
   GROUP BY 1` ≈ 14,240, 대상 dataset의 enabled operation 0, `/v1/features/in-bounds?kinds=price`가 transport 유가를 내지 않는다,
   Valkey `/v1/service/transport/status`는 그대로.
4. 배포 뒤 Dagster의 사라진 schedule 셋은 code location에서 빠진다(공용 plane, 다음 pinned pair부터).
5. **되돌리기**: 데이터는 지우지 않았다. 개별 Feature는 admin 재활성화(`reactivation_evidence` 필요 — override 때문에 provider 재적재로는
  켜지지 않는다), 일괄은 새 revision. 코드는 git revert + operation 재활성 revision. transport 자체의 이력(transport 저장소)은 무관하다.
6. API 표면 변화 없음(OpenAPI 재생성 없음, PinVi 재vendor 불필요). PinVi의 일반 지도에서 transport 유가·돌발 중복 마커가 사라진다
   (교통 레이어는 그대로).

## 열린 결정

- weather 범위는 "구현 설계 — 2단계" W1이 정했다(W1~W5 export 전부, W4 status 제외). W3 증분(`since`)·ETag 사용은 비용이
  드러나면 따로 정한다.
- PG transport 퇴역 ②·③단계의 시점(위 "결정 7 이행"의 해제 조건)
- 결정 6의 VWorld 블록이 export에 실릴 때 bjd를 값 주소에 넣는 일(id는 D1대로 바뀌지 않는다)
