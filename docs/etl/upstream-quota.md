# upstream 일일 한도 — 실측 분모와 아직 없는 분자

> 이 문서는 "우리가 얼마나 부르는가"(분자)와 "얼마까지 부를 수 있는가"(분모)를
> 한자리에 모은다. **분모는 2026-09-13에 실측했고, 분자는 대부분 아직 없다.**
> 그 비대칭을 숨기지 않는 것이 이 문서의 요점이다 — 관리자 UI가 오래
> "rate limit의 약 90% 이하를 목표로" 한다고 말했는데, 그 90%의 분모를 아무도
> 갖고 있지 않았다.

## 1. 분모는 서비스가 아니라 **오퍼레이션**마다 걸린다

data.go.kr 마이페이지 → 활용신청 현황 → 각 신청의 **상세기능** 표에 "일일 트래픽"
열이 있다. 그 값은 오퍼레이션마다 따로다.

```
기상청_단기예보 조회서비스 (VilageFcstInfoService_2.0)
  getUltraSrtNcst   10,000/일
  getUltraSrtFcst   10,000/일
  getVilageFcst     10,000/일
  getFcstVersion    10,000/일
```

**셋이 한 쿼터를 나눠 쓰지 않는다.** 이 문서를 쓰기 전 이 저장소의 추정은 반대
가능성을 열어 두고 있었고, 그 차이는 KMA 산수를 3배 갈라놓는다.

## 2. 실측 분모 (2026-09-13, 개발계정 63건 중 Map이 부르는 것)

| provider / 서비스 | op 수 | op당 일일 트래픽 |
|---|---:|---:|
| 기상청 단기예보 조회서비스 | 4 | 10,000 |
| 기상청 중기예보 조회서비스 | 4 | 10,000 |
| 기상청 기상특보 조회서비스 | 10 | 10,000 |
| 기상청 전국 해수욕장 날씨 | 6 | 10,000 |
| 한국환경공단 에어코리아 대기오염정보 | 5 | **500** |
| 한국환경공단 에어코리아 측정소정보 | 3 | **500** |
| 전국\*표준데이터 (박물관미술관·문화축제·관광지·주차장·휴양림·시티투어·관광안내소) | 각 1 | **1,000** |
| 한국관광공사 국문 관광정보 서비스 (visitkorea) | 15 | 1,000 |
| 산림청 산악기상정보 | 1 | 10,000 |
| 산림청 산불위험예보정보 | 3 | 1,000 |
| 산림청 산사태 예보발령 정보 | 1 | 10,000 |
| 산림청 국립자연휴양림 예약정보 | 1 | 1,000 |
| 해양수산부 해수욕장정보 / 수질적합 | 각 1 | 10,000 |
| 국립해양조사원 갯벌·바다갈라짐·해수욕지수 | 각 1 | 10,000 |
| 인천국제공항공사 여객기 운항 현황 | 2 | **500** |
| 인천국제공항공사 주차 정보 / 주차장별 요금 | 각 1 | 1,000 |
| 한국천문연구원 출몰 / 음양력 / 특일 | 2 / 4 / 5 | 10,000 |

가장 좁은 자리는 **500**(에어코리아, 인천공항 운항)이고, 그다음이
**1,000**(전국표준데이터 전부, visitkorea 전부, 산불위험).

### 이 표에 없는 provider

`krheritage`(국가유산청) · `opinet`(한국석유공사) · `krex`(한국도로공사) ·
`mois`/`localdata`(지방행정 인허가)는 **data.go.kr 활용신청이 아니다.** 각자
포털에서 따로 봐야 하고, 아직 보지 않았다. 이 저장소가 krheritage에 대해 적어 둔
"~3,950 요청/sweep"은 분자이고, 그 분모는 여전히 없다.

## 3. 바로 따라오는 산수 — KMA

격자 순회 job 하나는 오퍼레이션 **하나**를 격자 수 G만큼 부른다. 세 격자
dataset(초단기실황·초단기예보·단기예보)은 **서로 다른 오퍼레이션**을 쓰므로 각자
자기 10,000을 갖는다 — 합산으로 터지는 그림이 아니다.

### G는 상한이 아니라 실측값이다 (2026-09-13 prod)

`kma_weather_max_grids_per_run = 300`은 **상한**이지 대상 수가 아니다. 실제 G는
활성 POI cache target + 설정 extra point를 DFS 격자로 dedupe한 수다. prod 실측:

```
ops.poi_cache_targets            0행 (표 자체가 비어 있다 — 파괴적 rebuild 직후)
KMA_WEATHER_EXTRA_POINTS        60점
DFS 격자로 dedupe               → G = 59   (한 쌍이 같은 격자로 겹친다)
```

| schedule | 오퍼레이션 | 요청/일 | 한도 | 비율 |
|---|---|---:|---:|---:|
| 초단기실황 (`45 * * * *`) | `getUltraSrtNcst` | 24 × 59 = 1,416 | 10,000 | **14%** |
| 초단기예보 (`50 * * * *`) | `getUltraSrtFcst` | 24 × 59 = 1,416 | 10,000 | **14%** |
| 단기예보 (`20 * * * *`, 3시간 발표라 cursor가 skip) | `getVilageFcst` | 8 × 59 = 472 | 10,000 | 5% |

**즉 오늘 KMA를 다시 켜는 것은 쿼터 관점에서 넉넉하다.** 4배 재시도 배수를 전부
얹어도 5,664(57%)다.

### 그러나 G는 자란다 — 그리고 상한에서 절벽이다

`ops.poi_cache_targets`가 비어 있는 것은 PinVi가 아직 이 세대에 target을 등록하지
않았기 때문이다. 등록이 늘면 G가 300을 향해 자라고, 그때 비율은 이렇게 된다.

| schedule | 발표 주기 | G=300일 때 호출 경계/일 | 한도 대비 |
|---|---|---:|---:|
| 초단기실황 | 매시 | 24 × 300 = 7,200 | 72% |
| 초단기예보 | 매시 | 24 × 300 = 7,200 | 72% |
| 단기예보 | **3시간(하루 8회)** — cursor가 나머지 16 tick을 skip | 8 × 300 = 2,400 | 24% |

**셋을 한 숫자로 묶으면 안 된다.** `VILAGE_PUBLISH_HOURS`는 여덟 개뿐이고
(`kma/time_utils.py`) asset이 그 base를 cursor로 써서 같은 base면 호출 없이
끝낸다. 세 dataset에 같은 결론을 적용하면 하나에 대해 3배 과대평가한다.

### 그리고 "격자 하나 = 요청 하나"는 **전부 성공할 때만** 참이다

위 표의 수는 요청 수가 아니라 **호출 경계 수**다. 이 저장소의 재시도 정산은
경계당 최대 4 HTTP 시도다 — client에 주입하는 `PROVIDER_CLIENT_INNER_RETRIES=1`이
lib 안에서 2회가 되고(`kma/_http.py`: `attempts = max(1, retries + 1)`), 그 위에
`DEFAULT_UPSTREAM_ATTEMPTS=2`가 더 붙는다(`upstream_retry` 모듈 docstring이 직접
"경계당 2×2=4"라고 적는다).

**바깥 재시도만 예산으로 묶인다**(`RetryBudget`). 안쪽 lib 재시도는 예산이 없고
격자마다 독립적으로 2회까지 간다. 그래서 게이트웨이가 열화해 격자마다 첫 시도가
죽고 두 번째에 성공하는 구간에서는 run이 **성공**하면서도 요청이 2배가 된다 —
G=300이면 600/run, 하루 14,400으로 한도를 44% 넘는다. Map 로그에는 경고도 남지
않는다(안쪽 재시도는 lib 내부라 `on_retry`를 타지 않는다).

G=59인 오늘은 그 최악이 118/run · 2,832/일(28%)이라 여유가 있다. **결론이
G에 민감하다**는 것이 요점이다.

(타임아웃된 요청이 upstream에서 카운트되는지는 실측하지 않았다.)

### G가 상한을 넘으면 절벽이다

**G가 300을 넘는 순간 run이 통째로 실패한다** —
`KmaWeatherGridLimitExceeded`("partial execution is forbidden"). 초과분이 다음
run으로 이월되지 않는다. 상한을 넘긴 날 수집은 줄어드는 것이 아니라 **멈춘다**.

그래서 쿼터성 실패는 step 재시도를 **끈다**(`kortravelmap.dagster.quota_exhaustion`).
`python-kma-api`가 `resultCode 22`를 `failure_kind="quota"`로 분류하며 적어 둔
그대로 — 한도는 자정에 리셋되므로 같은 날 재시도는 성공할 수 없다.

> **주의**: KMA·AirKorea schedule은 2026-09-09부터 꺼져 있다
> (`DISABLED_FEATURE_LOAD_SCHEDULES`). 위 산수는 **다시 켰을 때**의 것이다.

## 4. 분자 — 진입점 33개 중 29개가 전부 센다

- **격자 순회형**(KMA 3종): 요청 수 = 격자 수. 격자 루프가 호출마다 계수한다.
  `grids_fetched`(성공한 격자 수)와 **다른 수**임에 주의 — 실패해 중단된 격자도
  요청은 나갔다. 처음에 그 둘을 같은 이름으로 실었다가 정본을 하나로 모았다.
- **bulk/표준데이터·페이지네이션형**: sweep당 요청 수 = 페이지 수. 2026-09-13부터
  같은 `upstream_requests_min`으로 나간다.

**배선은 실행 문맥이 대신한다.** fetcher가 generator라 "세는 자리(페이지 루프)"와
"내보내는 자리(asset output metadata)" 사이에 값을 흘릴 인자가 없었다. 그래서
`kortravelmap.dagster.upstream_requests`가 `ContextVar`로 계수기를 들고, asset
경계(`run_tracked_feature_asset`·`feature_place_mcst_culture`)가 그것을 연다 —
provider fetcher 19곳의 시그니처를 하나도 바꾸지 않는다. 합치는 자리는
`etl._add_output_metadata` 하나뿐이라(이 패키지에서 metadata를 내보내는 유일한
초크포인트) **실패 경로의 metadata에도 함께 실린다** — 실패한 run이 쿼터를 얼마나
썼는지가 사후 판독의 값이다.

**`_min`이 뜻하는 것.** 페이지 하나 = 요청 **적어도** 하나다. 콜백이 안에서
재시도하면(외부 `upstream_retry` attempts, provider client 내부 retries) 그것은 이
층에서 보이지 않고, provider lib이 한 번의 호출 안에서 여러 요청을 보내는 자리도
있다(krex `latest_weather`의 lookback 루프 — 그래서 그쪽은 상한을 따로 선언한다).
즉 "적어도 이만큼은 썼다"이고, 한도와 비교할 때 그 방향으로만 안전하다.

**"세지 않았다"는 값을 내지 않는다.** 계수기가 열려 있어도 **한 번도 기록되지
않았으면** key 자체가 실리지 않는다.

이 구분이 첫 판에는 없었고 적대 리뷰가 blocker로 잡았다 — 계수기는 asset 35개
전부에서 열리는데 세는 자리는 셋뿐이라 **OpiNet이 수천 건을 쓰면서 0을 냈다.**
하필 그것이 분모를 실측한 유일한 provider다. 틀린 0은 읽는 사람을 멈추게 하지
못하고, 없는 값은 멈추게 한다.

### 커버리지 — 진입점 33개 중 29개가 전부 센다

`tests/lint/test_every_fetcher_counts_or_declares_why_not.py`가 **명시 목록**
(`_EXPECTED_FETCHERS`)의 진입점마다 **세거나, 왜 못 세는지 선언하거나**를 요구한다.
목록에는 fetcher 32개 + MOIS Phase A(`sync_mois_source_db`)가 들어 있다 — 접두사로
유도하던 종전 판은 개명 한 번으로 선언 없이 빠질 수 있었고, MOIS의 slug별 LOCALDATA
다운로드는 통째로 게이트 밖이었다.

선언된 비계측은 **둘뿐**이고 둘 다 upstream 요청이 아예 없다:

| 진입점 | 이유 |
|---|---|
| `fetch_krairport_airports` | 번들 정적 데이터 — upstream 요청이 없다 |
| `fetch_mois_license_records` | 로컬 sqlite를 읽는다 |

2차 적대 리뷰가 이 목록을 넷에서 둘로 줄였다. **나머지 둘의 사유가 provider 소스와
어긋났다** — `file_data.iter_pages`는 public이고 `iter_all`이 그것을 감싼 것뿐이었고,
행사 창은 14개월로 알 수 있었다(비어 있는 달도 요청 1건이라 record 수로는 역산되지
않는다). 지금은 둘 다 Map이 루프를 소유하고 정확히 센다. 못 센다는 선언은 값싸고,
값싼 선언은 계측을 대체하기 시작한다.

종전 구조 검사는 "asset이 계수 범위 안에서 도는가"를 물었는데 wrapper가 항상 열어
**항진명제였다.** 요청을 보내는 것은 asset이 아니라 fetcher다.

#### 정적 검사가 볼 수 없는 것 — 그리고 그것을 덮는 층

이 검사는 "계수 호출 자리가 있는가"만 본다. **도달 불가 분기·죽은 중첩 함수·루프
밖 1회는 전부 초록이다.** 2차 리뷰가 바로 그 구멍으로 실제 blocker를 통과시켰다:
`fetch_krheritage_items`가 목록 페이지만 세고 record당 1 HTTP인 detail을 세지 않았는데,
목록 계수만으로 "센다"로 판정됐다 — 실린 수가 실제의 **약 1%**였다(목록 ~45 vs
detail ~4,000).

그래서 손으로 박은 자리마다 **가짜 client로 N번 부르게 하고 계수가 N인지 재는**
런타임 테스트를 둔다(`packages/kor-travel-map-dagster/tests/test_upstream_request_numerator.py`).
그쪽이 효과를 보는 층이고, 정적 검사는 "빠진 fetcher가 없는가"만 지킨다.

#### "센다"가 "모든 모드에서 센다"는 아니다 — OpiNet 부분 계측

유도는 *이 fetcher가 세는 함수를 부르는가*만 본다. 그래서 **실행 모드에 따라 계수
경로를 타지 않는** fetcher도 초록으로 나온다. 실제로 둘이 그렇다:

| fetcher | 세는 모드 | 못 세는 모드 |
|---|---|---|
| `fetch_opinet_stations` | `low_top_area` (`_OpinetCallBudget.spend()`) | `bbox` / `poi_cache_target` |
| `fetch_opinet_station_price_details` | 〃 | 〃 |

`iter_stations_in_bbox`는 bbox를 격자로 덮으며 셀마다 `aroundAll`을 부르는데, 셀 수
계산이 provider private이다. bbox 하나를 1로 세면 1과 20,000을 같게 만든다 — 그래서
**세지 않는다.** 계약상 기록이 없으면 key가 실리지 않으므로 0으로 위장하지는 않는다.

그 목록은 검사기의 `_PARTIALLY_COUNTED`에 이유와 함께 박혀 있고, `_UNCOUNTABLE`과
겹치지 못하며, **계측된 쪽으로 세어 주지도 않는다** — 완전 계측을 부분 계측으로
강등하는 것이 공짜면 그것이 값싼 도피로가 된다. 총량을 실제로 묶는 것은 §3의
하루 한 번 coalescing이다.

### 계수기는 어디서 열리나 — 경계가 둘이다

`note_upstream_request()`는 계수기가 열려 있을 때만 기록한다. 여는 자리는 **asset
경계**(`run_tracked_feature_asset`, `feature_place_mcst_culture`)와 **feature-update
queue runner**(`FeatureUpdateAssetRunner`) 둘이다.

runner를 빠뜨린 것이 2차 리뷰의 두 번째 blocker였다. 그 경로는 asset wrapper가 아니라
**원본 run 함수**를 직접 부르므로, 계수기를 따로 열지 않으면 계측된 fetcher가 큐로
돌 때 모든 계수가 no-op이 된다 — 조용히 값 없이 나간다.

### 실패로 끝난 run은 어디에 남나

**실패한 step은 output을 내지 않는다.** 그래서 `add_output_metadata`로 실은 분자는
실패하면 사라진다. 남는 자리는 둘이다:

| 실패 | 어디에 남나 |
|---|---|
| 일일 쿼터 소진 | `Failure` metadata의 `upstream_requests_min` (실패 이벤트에 붙는다) |
| 그 밖의 실패 | 경고 로그 `실패로 끝났지만 upstream 요청은 나갔다 (...)` |

세지 않은 경로는 둘 다 아무것도 남기지 않는다 — "0건 쓰고 죽었다"로 보이지 않게.

### "호출 한 번"이 요청 한 번이 아닌 자리 — 2026-09-13에 셋을 선언했다

| 자리 | 선언 전 | 지금 |
|---|---|---|
| krex `latest_weather()` | `lookback_hours` 기본 48 → **최악 49 요청**. 저장소 문서는 "페이지네이션 불필요"라고만 적었다 | `_KREX_WEATHER_LOOKBACK_HOURS = 6` → 최악 7. 6시간을 못 찾으면 upstream이 멈춘 것이므로 48시간 전 관측을 "최신"으로 적재하지 않고 실패한다 |
| krforest `client.iter_pages` ×4 | `max_pages` 미지정 → `totalCount`가 없으면 lib이 `total_count = len(items)`로 채워 상한이 **1페이지**가 되고 **조용히 `return`** — 행 누락이 성공으로 보인다 | 저장소 공통 `aiter_paginated_items`(`absolute_max_pages=10`) → 짧은 페이지를 마지막으로 읽지 않고, 넘으면 `ProviderPaginationOverrun` |
| visitkorea `search_festival` | `iter_paginated_pages`는 `max_pages`가 없으면 **상한이 없다** | `absolute_max_pages=50`(100행 × 50 = 5,000건) |

**`max_pages`가 아니라 `absolute_max_pages`인 이유.** 처음에는 `max_pages`로
줬다. 그것이 틀렸다 — 저장소 헬퍼에서 `max_pages`는 천장이 아니라 **바닥**이다.
`_PageState.absorb`가 선언 건수에 맞춰 `ceiling = max(ceiling, ...)`으로 올리기
때문이다. 그 설계 자체는 옳지만(선언 건수가 상한을 정한다) 그 위에 아무것도 없으면
**upstream이 말한 숫자가 곧 우리의 요청 수**가 된다. 선언 건수를 10억으로 둔
테스트가 `max_pages=10`을 무시하고 1,000페이지를 전부 걷는 것을 보고 알았고,
`absolute_max_pages`를 더해 닫았다(기본값 10,000 — 닫는 것은 "무한"이지 "많음"이
아니다).

**OpiNet bbox 모드는 "무제한"이 아니었다.** 라이브러리가 격자 셀 수를 세어
20,000을 넘으면 **호출 전에** `OpinetInvalidParameterError`를 던진다
(`_MAX_BBOX_GRID_CELLS`). 다만 (1) 20,000은 bbox **하나당** 상한이고
`_opinet_iter_stations`는 여러 bbox를 순회하므로 총량은 그 합이며, (2) Map 쪽에는
자체 예산이 선언돼 있지 않다. 실제로 총량을 묶고 있는 것은 쿼터 설정이 아니라
`_skip_opinet_if_already_succeeded_today` — **하루 한 번 성공하면 그날은 건너뛴다**는
coalescing이다. 셀 수 계산은 provider private이라 Map이 복제하면 drift가 나므로
(이 저장소가 이미 그 이유로 복제를 거부했다), 여기서는 숫자를 새로 짓지 않고
사실만 적는다. OpiNet 일일 한도 실측이 그다음 단계다.

### `ops.api_call_log`는 여기가 아니다

이름 때문에 분자를 찾는 사람이 멈추는 자리다. 그 표는 **Map API로 들어오는
요청**을 기록한다(`app.py`의 opt-in 미들웨어, 설정 `api_call_log_enabled`). upstream
요청과 무관하다. 오래 있던 `settings.log_api_calls`는 "provider 호출 횟수를 기록"
한다고 적었지만 **읽는 코드가 없었고**, 2026-09-13에 지웠다.

## 5. 이 문서를 고쳐야 하는 때

- data.go.kr에서 운영계정으로 승격하거나 활용신청을 추가/변경했을 때
- 격자 상한(`kma_weather_max_grids_per_run`)이나 schedule cron을 바꿀 때
- 분자 계측이 생겼을 때 — 그때 이 문서의 §4가 표로 바뀐다

분모는 마이페이지의 값이 정본이다. 여기 적힌 것은 **2026-09-13 시점의 사본**이고,
사본은 늙는다.
