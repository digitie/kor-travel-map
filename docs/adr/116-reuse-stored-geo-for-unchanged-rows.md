# ADR-116 — 비-MOIS 적재도 payload·좌표·geo 토큰이 그대로인 행은 역지오코딩하지 않고 저장값을 다시 쓴다

- 상태: proposed (2026-10-23, 소유자 결정 "geo 부하 줄이기 계획 0단계")
- 날짜: 2026-10-23
- 결정자: human(방향 결정), Claude(설계·구현)
- 관계: **ADR-108** §1(MOIS의 "payload가 같은 행은 지오코딩하지 않는다"를 비-MOIS로 넓힌다 — MOIS 경로는 바꾸지 않는다),
  **ADR-109**(스탬프·stale 분기·빈 답 가드는 그대로 두고 그 위에 얹는다; 컨텍스트 1의 "비-MOIS는 unchanged에도 reverse를
  부른다"를 고친다), **ADR-110**(geo가 odroid로 옮겨 CPU가 작아졌다 — ReadTimeout의 원인), **ADR-113**(spool: 받기·변환은
  쓰기 transaction 밖)

## 컨텍스트

비-MOIS feature 적재는 run마다 **모든** 좌표를 역지오코딩한다 — payload가 지난 run과 같아도. 그런데 그 답은 거의 다
버려진다: `load_bundle`은 `became_current or feature_missing or stale`일 때만 주소 열을 쓴다(ADR-109 결정 4). payload가
같고 스탬프가 현재 토큰이면 셋 다 거짓이라 새 답은 주소 검증에만 쓰이고 사라진다.

prod 읽기 전용 실측(2026-10-23, n150 공용 PG `kor_travel_map`):

| dataset | 좌표 있는 active | 스탬프 `called`·현재 토큰 | 같은 좌표(6자리)를 나눠 쓰는 행 | 직전 적재들에서 payload가 바뀐 기존 행 |
|---|---:|---:|---:|---:|
| 표준데이터 주차장 | 17,045 | 17,045 | 1,176 | 878 |
| MCST 세계음식점(13개 중 적재된 1개) | 9,494 | 9,494 | 504 | 8 |
| 국가유산 | 2,941 | 2,941 | 920 | 0 |
| 표준데이터 박물관 | 1,045 | 1,045 | 84 | 24 |
| 문화축제 | 1,056 | 1,056 | 445 | 51 |

주차장 한 run이 reverse 약 17,638회(region fallback 포함), MCST 22~28k, 등산로 약 57k다(ADR-109 컨텍스트 1·소유자
보고). odroid geo는 그 부하에서 ReadTimeout을 낸다.

## 결정

### 1. 건너뛰는 조건 — 셋 다 참일 때만

행(bundle) 하나가 "저장값 재사용"이 되는 조건은 `load_bundle`이 그 행의 주소 열을 **쓰지 않을** 조건과 같다.

1. **payload 그대로** — 그 source entity의 head 현재 record가 이 bundle과 같은 `raw_payload_hash`다. 거짓이면
   `became_current`다(비교는 hash로 한다 — `became_current`는 DB가 확정한 canonical record key로 판정하고 conflict 경로의
   DTO key는 그것과 다를 수 있다).
2. **스탬프가 현재** — 스탬프가 `reverse_outcome='called'`이고 `geo_data_token`이 run의 현재 토큰과 같다. 거짓이면 stale이다
   (ADR-109). 현재 토큰이 없으면(geo 지문 없음·조회 실패) 재사용 자체를 하지 않는다 — 비교할 기준이 없다.
3. **좌표 그대로** — 저장된 `features.coord`의 경도·위도가 bundle 좌표와 **정확히** 같다. 비교는 SQL에서 float8로,
   적재가 쓰는 값(`float(coord.lon)`, `feature_repo._feature_params`) 그대로 한다 — `Coordinate`는 `Decimal`이라 Python에서
   float과 비교하면 영영 같지 않아 재사용이 조용히 꺼진다.

덧붙여 Feature가 claim으로 풀리고 `active`이며, 주소 유도 열(`address`·코드 6개)에 active override가 없어야 한다(override가
있으면 저장값이 사람 값이다). 하나라도 빠지면 그 행은 평소처럼 geo를 부른다.

### 2. 어떻게 — 변환을 두 번 돌리고, 두 번째에 저장값을 역지오코더의 답으로 준다

역지오코더는 좌표만 받는다. 어느 record의 호출인지 모르므로 조건 1을 호출 시점에 판정할 수 없다. 그래서 공통 helper가 변환을
감싼다(asset마다의 코드가 아니다 — `dagster/geo_reuse.py` 한 곳, asset은 변환 호출을 그 helper로 넘길 뿐이다):

1. **pass 0(빈 답)** — geo를 부르지 않는 대역(항상 빈 답)으로 변환한다. 얻는 것은 행의 identity·payload key·좌표뿐이다.
2. **DB 한 번(받기 단계, fence 없음)** — 위 조건을 만족하는 행과 그 저장 주소 열을 읽는다(읽기 전용 짧은 transaction,
   `lock_feature_curation_write`를 잡지 않는다 — ADR-113 받기 단계와 큐 경로의 결합 transaction 모두에서 안전하다).
3. **재사용 좌표 표** — 좌표(6자리, provider 캐시와 같은 키) 하나를 쓰는 행이 **전부** 조건을 만족하고 저장 주소 열이 **모두
   같을 때만** 그 좌표의 답을 저장 `address`로 정한다. 하나라도 조건 밖이면(payload가 바뀐 이웃·새 행) 그 좌표는 geo를 부른다.
4. **pass 1** — 표의 좌표는 저장 `Address`를, 나머지는 실제 geo를 답하는 역지오코더로 다시 변환한다.
5. **사후 확인** — 저장값을 받은 bundle의 주소 유도 열이 저장값과 **정확히 같고**(provider 병합이 저장값에 대해 멱등인지),
   주소 검증의 차단 issue(`reverse_geocode_failed`·`missing_address`)가 없어야 한다. 어긋난 좌표는 표에서 빼고 다시
   변환한다(최대 두 번 더; 두 번째도 어긋나면 표 없이 — 오늘과 같은 경로). 다시 변환해도 실제 geo를 다시 부르지 않는다 —
   helper 호출 동안 실제 답을 기억한다(provider 캐시는 변환마다 새로 생기므로 그것만으로는 재시도가 같은 좌표를 다시
   묻는다; 빈 답 가드의 분모·분자도 두 번 세지 않는다). 지금의 `Address`가 받지 않는 옛 저장값(검증 실패)은 재사용하지
   않고 geo에 묻는다.

결과 bundle은 재사용 행에서 저장된 주소 열과 같은 값을 갖는다 — `load_bundle`은 그 행을 쓰지 않거나(값·`row_revision`
불변), 받기와 쓰기 사이의 경합으로 쓰더라도 그 (payload, 토큰)에 맞는 값을 쓴다(결정 3). 스탬프는 이미 현재 토큰이라
그대로다. 같은 데이터 토큰·같은 Map 설정(`radius_m`·`max_distance_m`·`region_fallback_radius_km`)의 geo는 같은 좌표에 같은
답을 내므로 이것은 전량 지오코딩의 결과와 같다. 스탬프는 `geo_version_token`을 비교하지 않는다 — 그것은 데이터의 함수가
아니라(ADR-109 컨텍스트 3) 비교하면 같은 데이터의 재빌드마다 전량을 다시 부른다. Map 설정이 바뀐 배포 뒤 unchanged 행의
검증은 옛 설정의 답(저장값)으로 한다 — 그 행은 오늘도 다시 쓰이지 않는다.

**안전망 — pass 0의 요청 좌표가 bundle 좌표 집합 밖이면**(provider가 행 좌표가 아닌 점을 역지오코딩하면) 그 변환은 재사용하지
않는다. 오늘의 provider는 모두 행 좌표(`feature.coord`)를 부른다(knps route는 centroid = `coord`).

### 3. 쓰기 경로·ADR-109 의미는 바뀌지 않는다

- stale 행(스탬프 없음·옛 토큰)은 조건 2로 빠져 반드시 geo를 부른다 — 릴리스 재지오코딩·센서 계획은 그대로다.
- 빈 답 가드(행·run, ADR-109 결정 4)는 실제 geo 답에만 걸린다. run 비율의 분모·분자 모두 실제 호출이다(재사용 행은 답을
  새로 받지 않았으므로 들어가지 않는다). 그래서 작은 dataset(박물관·축제·국가유산·MCST)은 실제 호출이 표본 하한
  (`GEOCODE_RATIO_MIN_SAMPLE`=50) 아래로 내려가 run 가드가 대개 무장되지 않는다. 기존 행은 행 가드가 지키고(저장값이
  있는데 새 답이 비면 덮지 않는다), 새 행의 빈 답은 `reverse_geocode_failed`로 drop되며 소실 하한(50%)이 마지막 방어다 —
  받아들인다.
- 받기와 쓰기 사이에 다른 run이 head·스탬프를 바꿔도 안전하다: 재사용 값은 "그 payload·그 토큰"에 대한 저장 답이고, 쓰기
  단계의 `became_current`·stale 판정은 쓰기 transaction에서 다시 한다. 그 행이 쓰이면 (payload, 토큰)이 맞는 값이 쓰이고
  스탬프도 그 토큰이다 — ADR-109의 불변식("스탬프 T면 값은 T로 해석된 것")이 유지된다.
- 스탬프 표·마이그레이션·OpenAPI 변경 없음.

### 4. 범위

공통 helper를 쓰는 곳: `assets.py`의 reverse를 넘기는 비-MOIS asset 전부와 `mcst_features.py`. **빼는 곳**: MOIS(ADR-108의
자기 경로), concierge(변환이 격리 목록을 채우는 부수효과가 있고 `observe()`의 후보 시군구 증거를 admin evidence로 싣는다 —
저장값으로 재현할 수 없다), 고속도로 돌발(reverse None). `admin_evidence`·`geo_attempt`가 있는 bundle은 재사용하지 않는다.

### 5. 계수 — run마다 로그로 남긴다

`GeoCallStats`에 `reuse` 계수(행 단위)를 더한다. `skipped` = 저장값을 받은 행, `geocoded` = 실제 geo 답을 받은 좌표 있는 행,
`fallback` = DB가 재사용 가능이라 했는데 공유 좌표·사후 확인·옛 저장값 때문에 geo를 부른 행(`geocoded`의 부분집합),
`disabled` = 안전망(행 좌표 밖 요청·빈 답을 견디지 못한 변환)이 재사용을 끈 변환의 좌표 있는 행 — 조회조차 하지 않았으므로
"재사용할 것이 없었다"(fallback 0)와 구별된다. resource teardown의 run 요약 WARNING 로그와 output metadata
(`geo_reuse_*`)에 실린다. 실제 HTTP 수는 기존 `geo_calls_*`다.

asset이 helper를 거치는지는 lint(`tests/lint/test_reverse_geocoding_assets_reuse_stored_geo.py`)가 고정한다 — helper 없이
`reverse_geocoder=`로 변환을 직접 부르면(예외 목록: MOIS·concierge) 빨갛다. 거치지 않아도 기능은 그대로라 다른 검사는 모른다.

## 결과

- 기대 감소(실측의 환산, 첫 성공 적재 뒤 run부터): 주차장 reverse 약 17.6k → 바뀐 행(약 5%) + 공유 좌표 중 저장값이 갈리는
  것(최대 1,176행) ≈ 1~2k(약 90%↓). MCST 세계음식점 9.5k → 수백, 국가유산 2.9k → 공유 좌표분(최대 920), 박물관·축제·관광지는
  90%↓. 아직 한 번도 성공하지 않은 dataset(MCST 나머지 12개·등산로)은 **첫 성공 run이 전량** 지오코딩하고 그 다음 run부터
  준다.
- 비용: 변환 CPU가 2배(pass 0 + pass 1; 사후 확인이 어긋나면 3~4배, 실제 geo는 다시 부르지 않는다). 변환은 순수 함수라
  geo 왕복(행당 ~86ms)보다 훨씬 싸다. 등산로(5.7만 건)는 pass 0이 geometry 정규화·WKT hash를 한 번 더 한다 — 그 dataset은
  아직 첫 성공 적재 전이라(seal 천장) 그때까지 얻는 것이 없다. batch당 DB 읽기 1문장(1,000행 단위). admin evidence를 늘
  싣는 asset(수목원·krex 휴게소)은 pass 0만 더 하고 재사용은 없다.
- 잃는 것: payload가 같은 행의 주소 검증은 저장값으로 한다(오늘은 새 답으로 했지만 그 답은 쓰이지 않았다). 같은 토큰의
  geo가 결정적이면 둘은 같다. 주소 유도 **코드**가 바뀐 배포 뒤에도 unchanged 행은 재해석되지 않는다 — 오늘도 쓰이지 않았으므로
  같다(재해석이 필요하면 geo 릴리스처럼 스탬프를 무효화하는 별도 결정).
- 되돌리기: 코드만(helper 호출을 원래 변환 호출로). 데이터·스키마 변경 없음.

## 기각한 대안

- **좌표 키 영속 캐시(원 답 저장)**: 스탬프 표에 원 reverse 답을 더하면 payload와 무관하게 좌표·토큰으로 정확히 재사용할 수
  있다. 마이그레이션과 롤아웃 1회 전량 기록이 필요하고, 소유자 조건 "payload가 바뀐 행은 geo를 부른다"보다 넓다. 지금은
  저장 주소 열로 충분하다.
- **좌표만으로 저장값 재사용(pass 0 없이)**: payload가 바뀐 행도 옛 병합 주소를 받는다(provider 병합이 `geo or provider`
  꼴이면 틀린 값). 기각.
- **MOIS처럼 unchanged 행을 적재에서 빼고 관측만 전진**: 주소 검증 finding의 관측이 빠져 stale-close가 그 finding을 닫는다.
  MOIS는 그것을 위해 별도 장치를 가졌다. 행을 그대로 적재 경로에 태우는 편이 단순하다.

## 설계 리뷰 반영(2026-10-23, 적대 리뷰 1회)

- MED-1(재시도가 실제 geo를 다시 부르고 빈 답 계수를 부풀린다): helper 호출 동안 실제 답을 기억한다(결정 2-5).
- MED-2(옛 저장 jsonb가 `Address` 검증에 실패하면 run이 죽는다): 그 좌표는 재사용하지 않고 fallback으로 센다.
- MED-3(좌표 비교 규칙 미정): 결정 1-3에 SQL float8 비교를 적고, 통합 검사는 적재가 실제로 쓴 좌표로 본다.
- MED-4(재사용이 조용히 꺼지는 두 경우): 안전망은 `disabled` 계수로 드러내고, payload 비교를 DTO key가 아니라 hash로 바꿨다.
- LOW-5(run 빈 답 가드가 작은 dataset에서 무장되지 않는다)·LOW-6(같은 답의 조건)·LOW-8(경합 시 쓰기 문구): 결정 2·3에 적었다.
- LOW-7·9(쓸모없는 pass 0·메모리·batch마다 경고): pass 0 목록은 표를 만든 뒤 버리고, 토큰 resource가 없으면 helper가
  조용히 원래 경로로 간다(경고는 적재 wrapper가 run에 한 번). 늘 evidence를 싣는 asset의 pass 0은 비용으로 받아들인다.
- LOW-10(helper 우회를 아무도 모른다): lint를 더했다(결정 5).
- 대안 "어긋나도 pass 1 bundle을 그대로 쓴다"는 택하지 않았다 — 결과가 전량 지오코딩과 같다는 보장을 버리고, 재시도 비용은
  답 기억으로 이미 geo 0회다.

## 코드 리뷰 반영(2026-10-23, 적대 리뷰 2회)

- B MED-1(조회 실패가 적재를 죽이고, 큐 경로에서는 executor transaction까지 되감는다): 조회는 savepoint 안에서 하고
  `SQLAlchemyError`는 그 안에서 끝내 `None`을 돌려준다 — 그 변환은 전량 지오코딩하고 `lookup_failed`로 센다.
- B MED-2(generic plan이 스탬프 토큰 인덱스에서 출발할 수 있다): 입력 CTE를 `MATERIALIZED`로 묶어 입력 행에서 출발하게
  했다.
- A MED-1(저장값만으로 끝난 변환은 run 도중의 geo 릴리스를 관측하지 못해, 그 사이 릴리스 run이 새 값으로 고친 행을 stale
  분기가 옛 값으로 되돌릴 수 있다): 저장값으로 답한 행이 있으면 helper가 geo의 현재 데이터셋을 다시 읽어(`GeoDatasetHandle.
  recheck`) run 관측 집합에 더한다 — 전환이 있었으면 `effective_token()`이 None이라 stale 분기·스탬프가 없다. 남는 창은
  마지막 batch의 재확인과 쓰기 사이(spool 쓰기 시작까지)이고, 재확인이 실패(geo 장애)하면 관측하지 못한다.
- A LOW-3(pass 1에서만 생긴 evidence): 사후 확인이 `_reusable_shape`도 본다.
- B LOW-4(메타 키 불일치): 메타는 `GeoCallStats.as_metadata`의 `geo_reuse_*`를 그대로 쓴다. B LOW-5(lint 범위): dagster
  패키지 전 모듈을 보고 MOIS chunk 적재·offline upload를 이유와 함께 예외로 둔다.
- A LOW-6(계수 의미): `fallback`·`disabled`·`lookup_failed`는 `geocoded`의 부분집합이라고 적었다.
- 받아들인 것: A LOW-2(빈 답 가드가 지킨 옛 주소는 그 뒤 재사용 행의 검증에 그대로 쓰인다 — DB 값은 전량 지오코딩과 같고,
  그 값은 ADR-109 행 가드가 의도해 남긴 것이다), A LOW-4(주소 유도 코드 변경은 스탬프가 모른다 — 결과 절), A LOW-5·B LOW-3
  (pass 0 예외는 모듈 경고 + `disabled` 계수; 진짜 버그는 pass 1이 다시 올린다), A LOW-7(asyncpg 오류는 SQLAlchemy가
  `DBAPIError`로 감싼다), B LOW-6(asset 결선 통합 검사 — 단위 검사가 결선을 대역으로 본다), B LOW-7·8(결과 절).

## 개정 2026-10-23 — 선조회 동시성·적재 geo 일시 장애 재시도(브랜치 `fix/mcst-geo-stall`)

- **배경.** MCST 첫 적재(13개 dataset, 104,301행)는 저장값이 없어 전량을 순차로 물었다 — 실측 초당 약 4.6건, 6시간 상한
  초과. 같은 날 run 하나는 3.5시간 동안 이벤트 0건·프로세스 I/O 0으로 멈췄고(원인 미규명), 재현은 odroid 과부하 중
  `/v2/regions/within-radius` 504 한 번으로 변환 전체가 끝났다.
- **선조회.** 재사용 helper는 pass 1 전에 저장값 표에 없는 좌표를 `KOR_TRAVEL_MAP_REVERSE_GEOCODE_CONCURRENCY`(기본 2,
  1이면 종전 순차)만큼 동시에 미리 묻는다(ADR-108 `PrefetchingReverseGeocoder` — MOIS 전용에서 공용으로). 캐시는 변환이 물을
  좌표 전부를 담는다. 결과는 순차 경로와 같다(같은 6자리 좌표 키·`observe` 경로). 토큰이 없는 run 등 helper가 원래 변환으로
  가는 경로는 여전히 순차다.
- **재시도(소유자 승인 2026-10-23, ADR-109 열린 결정 6·ADR-108 §2 "건별 재시도 없음"을 이 범위에서 개정).** Dagster
  `reverse_geocoder` resource의 geo client만 502/503/504·read timeout·연결 중 끊김에 총 3회(2초·4초 뒤)까지 다시 보낸다.
  연결 실패(호스트 다운)·4xx·500은 다시 보내지 않는다. API 기동 검증·admin route·offline upload·현재 데이터셋 조회는
  기본값 1(재시도 없음)이라 종전과 같다. 계수는 논리 요청당 한 번(최종 결과) — 빈 답 run 가드의 분모가 부풀지 않는다.
- **멈춤 진단.** 적재 step(`run_tracked_feature_asset`·MCST asset)이 900초 동안 프로세스 I/O(`rchar+wchar`, 관측 자신의
  읽기는 뺀다)가 그대로면 asyncio task 스택을 WARNING으로 한 번 남긴다. run은 건드리지 않는다.
- **받아들인 위험.** 동시 geo 요청 상한이 run당 1에서 2로 오른다 — 큐 경로는 pool을 claim하지 않아 worker run 수만큼
  곱해진다. 과부하 중 재시도는 서버 일을 최대 3배로 늘릴 수 있다(재시도는 행당 상한·선조회는 첫 소진 실패에서 멈춤).
  odroid 부하가 문제가 되면 env로 동시성 1로 되돌린다.
- **멈춤 진단 정정(2026-10-24).** 첫 판은 파일 I/O(`rchar+wchar`)만 진척으로 봤는데 소켓 `recv`/`send`는 거기 잡히지
  않는다 — 배포 뒤 MCST run(성공, 2시간 40분)이 geo를 수만 번 부르는 동안 15분마다 오탐했다. 진척 신호에
  `kortravelmap.core.activity` 표시(geo 왕복·상류 요청·SQLAlchemy 문장)를 더하고, 경고는 run당 한 번으로 줄였다.
