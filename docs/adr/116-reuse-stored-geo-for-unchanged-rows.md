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

1. **payload 그대로** — 그 source entity의 head 현재 record key가 이 bundle의 `source_record_key`와 같다(키에 payload hash가
   들어 있다). 거짓이면 `became_current`다.
2. **스탬프가 현재** — 스탬프가 `reverse_outcome='called'`이고 `geo_data_token`이 run의 현재 토큰과 같다. 거짓이면 stale이다
   (ADR-109). 현재 토큰이 없으면(geo 지문 없음·조회 실패) 재사용 자체를 하지 않는다 — 비교할 기준이 없다.
3. **좌표 그대로** — 저장된 `features.coord`의 경도·위도가 bundle 좌표와 **정확히** 같다.

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
   변환한다(최대 두 번 더; 두 번째도 어긋나면 표 없이 — 오늘과 같은 경로).

결과 bundle은 재사용 행에서 저장된 주소 열과 같은 값을 갖는다 — `load_bundle`은 그 행을 쓰지 않고(값·`row_revision` 불변),
스탬프는 이미 현재 토큰이라 그대로다. 같은 토큰의 geo는 같은 좌표에 같은 답을 내므로 이것은 전량 지오코딩의 결과와 같다.

**안전망 — pass 0의 요청 좌표가 bundle 좌표 집합 밖이면**(provider가 행 좌표가 아닌 점을 역지오코딩하면) 그 변환은 재사용하지
않는다. 오늘의 provider는 모두 행 좌표(`feature.coord`)를 부른다(knps route는 centroid = `coord`).

### 3. 쓰기 경로·ADR-109 의미는 바뀌지 않는다

- stale 행(스탬프 없음·옛 토큰)은 조건 2로 빠져 반드시 geo를 부른다 — 릴리스 재지오코딩·센서 계획은 그대로다.
- 빈 답 가드(행·run, ADR-109 결정 4)는 실제 geo 답에만 걸린다. run 비율의 분모·분자 모두 실제 호출이다(재사용 행은 답을
  새로 받지 않았으므로 들어가지 않는다).
- 받기와 쓰기 사이에 다른 run이 head·스탬프를 바꿔도 안전하다: 재사용 값은 "그 payload·그 토큰"에 대한 저장 답이고, 쓰기
  단계의 `became_current`·stale 판정은 쓰기 transaction에서 다시 한다. 그 행이 쓰이면 (payload, 토큰)이 맞는 값이 쓰이고
  스탬프도 그 토큰이다 — ADR-109의 불변식("스탬프 T면 값은 T로 해석된 것")이 유지된다.
- 스탬프 표·마이그레이션·OpenAPI 변경 없음.

### 4. 범위

공통 helper를 쓰는 곳: `assets.py`의 reverse를 넘기는 비-MOIS asset 전부와 `mcst_features.py`. **빼는 곳**: MOIS(ADR-108의
자기 경로), concierge(변환이 격리 목록을 채우는 부수효과가 있고 `observe()`의 후보 시군구 증거를 admin evidence로 싣는다 —
저장값으로 재현할 수 없다), 고속도로 돌발(reverse None). `admin_evidence`·`geo_attempt`가 있는 bundle은 재사용하지 않는다.

### 5. 계수 — run마다 로그로 남긴다

`GeoCallStats`에 `reuse` 계수(`skipped`·`geocoded`·`fallback`, 행 단위)를 더한다. `skipped` = 저장값을 받은 행,
`geocoded` = 실제 geo 답을 받은 좌표 있는 행, `fallback` = DB가 재사용 가능이라 했는데 공유 좌표·사후 확인·안전망 때문에 geo를
부른 행. resource teardown의 run 요약 WARNING 로그와 output metadata(`geo_reuse_*`)에 실린다. 실제 HTTP 수는 기존
`geo_calls_*`다.

## 결과

- 기대 감소(실측의 환산, 첫 성공 적재 뒤 run부터): 주차장 reverse 약 17.6k → 바뀐 행(약 5%) + 공유 좌표 중 저장값이 갈리는
  것(최대 1,176행) ≈ 1~2k(약 90%↓). MCST 세계음식점 9.5k → 수백, 국가유산 2.9k → 공유 좌표분(최대 920), 박물관·축제·관광지는
  90%↓. 아직 한 번도 성공하지 않은 dataset(MCST 나머지 12개·등산로)은 **첫 성공 run이 전량** 지오코딩하고 그 다음 run부터
  준다.
- 비용: 변환 CPU가 2배(pass 0 + pass 1; 사후 확인이 어긋나면 3~4배). 변환은 순수 함수라 geo 왕복(행당 ~86ms)보다 훨씬 싸다.
  batch당 DB 읽기 1문장(1,000행 단위).
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
