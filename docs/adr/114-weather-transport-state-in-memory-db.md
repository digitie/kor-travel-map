# ADR-114 — weather·transport의 현재·예보 상태는 Map이 메모리 DB(Valkey)에 들고, PinVi는 Map REST로 읽는다

- 상태: proposed (소유자 결정 2026-10-23 — 방향 확정, 구현 전. 이행 단계마다 이 문서를 갱신하고 마지막 단계가
  배포되면 accepted로 올린다)
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

접두사 `ktm:state:v1:`(값 스키마 버전 포함). 값 모양이 바뀌면 `v2`로 올린다 — 새 버전의 적재가 교체에 성공할 때마다
다른 버전 접두사(`ktm:state:*` 중 `ktm:state:v2:`가 아닌 것)의 만료 없는 키에 grace TTL을 건다. `current`와
교체된 세대는 만료가 없으므로 이 정리가 없으면 `noeviction` 아래 옛 버전 한 벌이 영구히 남는다.

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

1. `lock`을 `SET NX EX`(build TTL)로 잡는다. 이미 있으면 다른 적재가 도는 것이라 이번 run은 받지 않고 끝낸다(실패
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
- 가격 추이: Valkey의 현재가와 함께 transport `GET /v1/service/exports/fuel-stations/{uni_id}/price-history`
  (transport ADR-013 2026-10-23 추가)를 요청 시 그대로 전한다. `uni_id`는 Valkey 값에서 꺼낸다. 설정 플래그
  `KOR_TRAVEL_MAP_TRANSPORT_PRICE_HISTORY_ENABLED`(기본 꺼짐 — transport에 경로가 배포된 뒤 켠다)가 꺼졌거나,
  transport 주소·토큰이 없거나, transport가 404(옛 버전·토큰·fence)·5xx·timeout·계약 위반이면 200으로 현재가를
  주고 `history.status=unavailable`과 이유를 싣는다. 404는 설정 문제일 수 있어 경고 로그를 남긴다. API 프로세스도
  transport 토큰을 갖게 되므로 그 비밀이 놓이는 자리가 하나 는다.
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

### 설계 리뷰(적대 1회, 2026-10-23)

HIGH 4 — 같은 id 행이 `HLEN` 검사를 영구 실패시킴(→ 고유 id 기준·첫 행·`duplicates`), BYBOX 폭을 중심 위도에서
재면 남쪽 모서리가 빠짐(→ 적도 쪽 위도 폭·크기 상한), 스키마 버전 교체 뒤 옛 키가 남음(→ 다른 버전 접두사 정리),
개수 검사가 교체 밖에 있고 `meta`만 존재 검사(→ Lua 안에서 `meta` 개수와 대조, `meta`가 유일한 존재 표지). MED —
직전 하나와의 비율은 여러 번 나눠 줄면 뚫림(→ 최근 6번 최대·절대 하한), 범위 밖 좌표가 GEO 쓰기를 통째로 깸(→ 범위
검사), 주유소 값의 id 모호(→ place id 명시), private 함수 의존(→ `krex` 공개 이름), 동시 적재(→ 잠금·실패 시 정리·
실패 분류), 지속성 비용(→ Manager에 의견). LOW — cursor 세대 위조(→ `current`/`previous`만), lookup 덮어쓰기(→ 첫
행), client 재시도(→ 끔), 신선도 혼합(→ 이른 쪽). 가격 추이 플래그 제거 의견은 받지 않았다 — transport 경로가 배포되기
전에 켜지지 않게 하는 스위치가 필요하다(소유자 요구).

## 열린 결정

- weather에서 Map이 들고 있을 provider·항목의 범위(2단계)
- 기존 PG transport feature 퇴역 시점과 방법
- 결정 6의 VWorld 블록이 export에 실릴 때 bjd를 값 주소에 넣는 일(id는 D1대로 바뀌지 않는다)
