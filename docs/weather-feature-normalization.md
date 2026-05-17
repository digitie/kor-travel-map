# Weather feature normalization

Weather feature는 KMA의 시간축을 기준으로 여러 provider의 날씨성 데이터를 `python-krtour-map`의 `WeatherValue` 계약과 feature DB에 저장한다. TripMate는 별도 feature DB를 만들지 않고 이 라이브러리의 DB schema와 함수를 import해 사용한다. provider 호출은 각 `python-*-api`의 안정된 public client와 typed model을 직접 사용하고, TripMate나 `python-krtour-map` 안에 provider별 wrapper/adapter/gateway를 새로 만들지 않는다.

## 기준 축

`forecast_style`은 원천값의 성격을 보존한다.

- `nowcast`: KMA 초단기실황처럼 관측 기반의 실황 row
- `ultra_short`, `short`, `mid`: KMA 예보 row
- `observed`: KREX 휴게소 날씨, KRForest 산악기상, KRAirport 세계날씨처럼 provider가 현재/관측값으로 주는 row
- `index`: 산불위험, 산사태, 해양지수, 체감온도처럼 날씨를 가공한 지수
- `advisory`: 특보, 경보, 안전 알림 성격의 row

`timeline_bucket`은 앱 조회와 저장 분류를 위한 KMA식 시간축이다.

- `ultra_short`: 현재/관측, 초단기실황, 초단기예보, 0-6시간 주변 context
- `short`: 오늘-모레 수준의 단기예보, 당일/익일 위험지수, 운항/도로/산림 안전 context
- `mid`: KMA 중기예보처럼 3-10일 전망을 공식적으로 제공하는 데이터

관측값을 억지로 예보로 바꾸지 않는다. 예를 들어 KREX 휴게소 최신 날씨는 `forecast_style='observed'`, `timeline_bucket='ultra_short'`로 저장한다.

## Provider별 1차 매핑

| provider library | source model | domain | forecast_style | timeline_bucket | 검토 포인트 |
| --- | --- | --- | --- | --- | --- |
| `python-kma-api` | `ForecastItem`, `ForecastTimepoint`, `MidForecastItem` | `kma_ultra_short_nowcast`, `kma_ultra_short_forecast`, `kma_short_forecast`, `kma_mid_forecast` | `nowcast`, `ultra_short`, `short`, `mid` | KMA endpoint에 맞춤 | `base_at`, `forecast_at`, DFS `nx/ny`, `regId/stnId`, category code와 단위 보존 |
| `python-krforest-api` | `MountainWeather` | `forest_mountain_weather` | `observed` | `ultra_short` | 산악 관측소 좌표/고도, 관측시각 raw key, 강수/풍속/기압 단위, feature와 관측소 거리 |
| `python-krforest-api` | wildfire/landslide risk rows | `forest_fire_risk`, `forest_landslide_risk` | `index` 또는 `advisory` | `short` | 예측/분석 시각, 행정구역 granularity, 위험단계 code/name, 여행 안전 알림으로의 표현 |
| `python-krex-api` | `RestAreaWeather` | `rest_area_weather` | `observed` | `ultra_short` | `observed_at`, 휴게소 `unit_code`, 노선/방향, 측정소명, `-99` sentinel, 좌표계 |
| `python-krairport-api` | `WorldWeather` | `airport_weather` | `observed` | `ultra_short` | 도착/출발 상대 공항의 도시 날씨인지 국내 공항 자체 날씨인지 구분, 항공편 시간과 날씨 관측시각 분리 |

## Canonical metric key

KMA category code를 우선 canonical metric으로 사용한다.

| canonical metric_key | 의미 | 단위 예시 | source examples |
| --- | --- | --- | --- |
| `T1H` | 현재 기온 | `deg_c` | KMA 초단기실황, KREX `temperature`, KRAirport `temperature`, KRForest 온도 |
| `TMP` | 예보 기온 | `deg_c` | KMA 단기예보 |
| `REH` | 습도 | `%` | KMA, KREX, KRAirport, KRForest |
| `WSD` | 풍속 | `m/s` | KMA, KREX, KRAirport, KRForest |
| `VEC` | 풍향 | `deg` 또는 provider code | KMA, KREX wind direction code |
| `RN1` | 1시간 강수량 | `mm` | KMA 초단기실황, KREX `rainfall`, KRForest 강수 |
| `PTY` | 강수형태 | provider code/text | KMA, provider weather text 보조 |
| `SKY` | 하늘상태 | provider code/text | KMA, KRAirport/KREX weather text 보조 |
| `FIRE_RISK` | 산불위험 | grade/code | KRForest 산불위험 |
| `LANDSLIDE_RISK` | 산사태 위험 | grade/code | KRForest 산사태 예측 |

provider 원래 필드는 `source_metric_key`, `source_metric_name`, `payload`에 보존한다. canonical metric으로 확정하기 애매한 값은 `metric_key`를 provider domain 안에서만 안정적인 snake/code로 두고, mapping을 문서화한 뒤 올린다.

## DB schema

`python-krtour-map`이 소유하는 `feature_weather_values` table은 아래 weather normalization 컬럼을 가진다. TripMate 문서와 코드에는 이 table의 복제본이나 별도 feature weather table을 만들지 않는다.

- `timeline_bucket text null`: `ultra_short`, `short`, `mid`. 신규 write는 반드시 채운다.
- `valid_from timestamptz null`, `valid_until timestamptz null`: 특보, 중기 일 단위, 지수처럼 구간 유효성이 있는 row를 보존한다. 단일 시점 row는 `valid_at`을 계속 대표 시각으로 쓴다.
- `source_metric_key text null`, `source_metric_name text null`: provider 원천 필드명을 추적한다.
- `normalization_version text null`: provider별 mapping 규칙 버전. 예: `weather-feature-v1`.

권장 index:

- `(feature_id, timeline_bucket, valid_at)`
- `brin(valid_from)`
- `brin(valid_until)`

Unique key는 `feature_id + provider + weather_domain + forecast_style + metric_key + issued_at + valid_at + observed_at`이다. `timeline_bucket`은 분류 결과라서 중복 판정의 1차 기준에 넣지 않는다.

## Provider 검토 체크리스트

- public client와 typed model이 있는지 먼저 확인하고, 없으면 해당 `python-*-api`에 보강한다.
- provider의 발표시각, 관측시각, 유효시각을 분리한다.
- KST timezone-aware datetime으로 저장한다.
- feature 위치와 provider 관측소/지점의 매칭 방법을 `payload.match` 또는 source link metadata에 남긴다.
- sentinel, 결측, 문자열 단위, provider code table을 serving row로 승격하기 전에 정리한다.
- 관측값을 단기/중기 예보처럼 보이게 표시하지 않는다.
- raw payload와 response hash를 `SourceRecord`에 남기고 feature link는 `weather_context`로 연결한다.

## 추가 검토할 정부기관 데이터

우선순위가 높은 후보:

- 산림청 국립산림과학원 산악기상정보: 주요 산악지역의 풍향, 풍속, 온도, 습도, 기압, 지면온도, 강수량 관측. 산/휴양림/트레일 feature에 적합하다. [data.go.kr](https://www.data.go.kr/data/15084696/openapi.do)
- 산림청 산사태예측정보: 시도/시군구 단위 위험단계. 집중호우 후 산행/계곡/휴양림 알림에 적합하다. [data.go.kr](https://www.data.go.kr/data/15074800/openapi.do)
- 한국도로공사 휴게소별 날씨 정보: 휴게소 feature에는 KMA 격자보다 직접성이 높다. 이미 `python-krex-api`의 핵심 weather source로 둔다. [data.go.kr](https://www.data.go.kr/data/15076661/openapi.do)
- 인천국제공항공사 기상 정보: 인천공항 항공편 상대 도시 날씨. 항공편 context에는 유용하지만 국내 공항 자체 날씨와 혼동하지 않는다. [data.go.kr](https://www.data.go.kr/data/15095086/openapi.do)
- 기상청 국내 공항기상정보: 국내 공항 자체의 요약, 기온, 강수량, 위험 기상예보, 경보현황. 국내 공항 feature에는 KRAirport 세계날씨보다 우선 검토한다. [data.go.kr](https://www.data.go.kr/data/15110052/openapi.do)
- 해양수산부 국립해양조사원 조위관측소 실측 수온/기온/기압: 해수욕장, 항구, 섬 여행 feature의 초단기 관측 보강에 적합하다. [data.go.kr](https://www.data.go.kr/data/15142506/openapi.do)
- 해양수산부 국립해양측위정보원 해양기상 정보: 풍향, 풍속, 수온, 기온, 습도, 기압, 유향, 유속 등 항로표지 관측. 섬/항구/해양 안전 context 후보. [data.go.kr](https://www.data.go.kr/data/15033708/openapi.do)
- 한국환경공단 AirKorea 대기오염정보: PM10, PM2.5, O3 예보/측정. weather feature와 같은 카드에 붙이되 domain은 `air_quality`로 분리한다. [data.go.kr](https://www.data.go.kr/data/15073861/openapi.do)
- 농촌진흥청 국립농업과학원 농업기상 관측지점: 농촌/농장/로컬푸드/체험마을 주변 미기상 후보. 트래픽이 작으므로 초기에는 후보군으로 둔다. [data.go.kr](https://www.data.go.kr/data/15073274/openapi.do)
- 한국수자원공사 수문 운영 정보: 댐/보 강우량, 수위, 유입량, 방류량. 계곡, 강변, 댐 전망대 여행 안전 context 후보이며 weather보다는 hydro/weather-adjacent domain으로 분리한다. [data.go.kr](https://www.data.go.kr/data/15099110/openapi.do)
