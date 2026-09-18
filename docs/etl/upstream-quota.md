# upstream 일일 한도 — 실측 분모와 하한 분자

> 이 문서는 "우리가 얼마나 부르는가"(분자)와 "얼마까지 부를 수 있는가"(분모)를
> 한자리에 모은다. **분모는 2026-09-13에 data.go.kr에서 실측했고, 분자는 같은 날
> 진입점 40개 중 35개에서 하한으로 나가기 시작했다.** 남은 비대칭 둘을 숨기지
> 않는 것이 이 문서의 요점이다 — data.go.kr 포털에 없는 provider 넷
> (`krheritage`·`opinet`·`krex`·`mois`)은 **분모가 아직 없고**, 분자도 §4에
> 열거한 자리에서는 부분값이거나 없다. **`krex`는 2026-09-14에 분모를 기다리는 대신
> 축을 바꿨다 — 일일 한도가 아니라 TPS 5로 막는다(§2). 프로세스당 보증은 라이브러리가,
> 프로세스 사이는 `provider_rate_gate`가 맡는다.** 관리자 UI가 오래 "rate limit의 약 90%
> 이하를 목표로" 한다고 말했는데, 그 90%의 분모를 아무도 갖고 있지 않았다.

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

**기상청·에어코리아 행은 평가 대상이 아니다**(2026-09-14 지시).

> **다만 KMA 분자의 성질이 바뀐 것은 적어 둔다**(2026-09-16). `python-kma-api`
> `4ac9a325`가 `getVilageFcst`/`getUltraSrtFcst`/`getUltraSrtNcst`를 페이지네이션
> 하도록 고쳤다 — 종전에는 두 번째 페이지가 오면 `KmaParseError`로 **실패**했고
> (하류 소비자가 저녁 KST 시간대 연속 실패를 관측했다), 지금은 끝까지 돌며 상한이
> `_MAX_FETCH_PAGES = 20`이다. **격자 하나 = 호출 하나가 더 이상 참이 아니다** —
> 격자 하나가 최대 20요청이 될 수 있고 `kma_weather.py`의 계수기는 그 안을 보지
> 못한다. 그 수가 여전히 **하한**인 이유다. 평가를 재개하면 이 배수를 먼저 재라. 둘 다 2026-09-09에
자동 적재가 꺼졌고 계속 꺼져 있다 — 표에는 실측 기록으로 남기되, 아래 어느 산수에도
넣지 않는다. 그래서 지금 **살아 있는 provider 중 가장 좁은 자리는 1,000**이다
(전국표준데이터 전부, visitkorea 전부, 산불위험, 인천공항 주차). 인천공항 운항의
500은 Map이 부르지 않는다.

### 실측 분자 — 한 sweep이 분모의 몇 %인가 (2026-09-16)

분모만으로는 판단이 안 된다. **한 번 도는 데 몇 건을 쓰는지**를 코드에서 세고,
전국표준데이터는 `totalCount`를 실제로 읽었다(op당 1건, 총 4건 — 분모 대비 0.1%).

| op | 분모 | 총건수 실측 | 정상 sweep | 최악 sweep | 최악 % |
|---|---:|---:|---:|---:|---:|
| `parking` | 1,000 | **18,883** | 19 | 600 | **60%** |
| `festival` | 1,000 | 1,320 | 2 | 600 | 60% |
| `museum_art` | 1,000 | 1,076 | 2 | 600 | 60% |
| `tourist_attraction` | 1,000 | 897 | 1 | 600 | 60% |
| `special_street` | 1,000 | **403** — 평가 대상 아님(아래) | — | — | — |
| visitkorea 축제 | 1,000 | — | ≤50 | 50 | 5% |
| 산불위험예보 | 1,000 | — | 10 | 60 | 6% |
| 산악기상·산사태 | 10,000 | — | 10 | 60 | 0.6% |
| khoa 해수욕장 | 10,000 | — | ~70 | (아래) | — |
| krairport | 1,000 | — | **0** | 0 | 0% |

**최악 sweep 600은 페이지 상한(200) × 전송 재시도(3)다.** 그 상한이 선언 총건수에서
`2·⌈D/1000⌉+1`로 올라갈 수 있는데, 하루를 넘으려면 **D > 166,000**이 필요하다.
실측 최대가 18,883이므로 **한 자릿수 아래다** — 전국표준데이터는 안전하다.

`krairport`가 0인 것은 라이브러리가 **번들 데이터**를 쓰기 때문이다(HTTP 없음).
`special_street`는 prod 키로 **403**이다 — fetcher는 있는데 그 오퍼레이션은 활용신청이
안 돼 있다. **평가 대상에서 제외한다**(2026-09-16 지시) — 기록으로만 남기고 이 문서의
어느 산수에도 넣지 않는다. 403이므로 요청은 나가도 데이터는 오지 않는다.

**가장 좁은 자리는 `opinet`이다.** 무료키 300/일을 두 job이 나눠 쓰고, 기본 설정의
무사고 하루가 **280 = 93%**다(여유 20건). 호출 하나가 재시도되면(×3) 그 여유가
사라진다. 그래서 여기만 이미 run당 예산(`opinet_run_call_budget`)이 있다.

### 이 표에 없는 provider

`krheritage`(국가유산청) · `opinet`(한국석유공사) · `krex`(한국도로공사) ·
`mois`/`localdata`(지방행정 인허가)는 **data.go.kr 활용신청이 아니다.** 각자
포털에서 따로 봐야 하고, 아직 보지 않았다. 이 저장소가 krheritage에 대해 적어 둔
"~3,950 요청/sweep"은 분자이고, 그 분모는 여전히 없다.

| provider | 일일 한도 | 출처 | 확인 |
|---|---|---|---|
| `opinet` | 무료키 **300/일** | 오피넷 이용안내 > 유가정보 API — 일반 API 19종 `300call/일`(프리미엄 3종이 1,500) | **2026-09-14 확인** |
| `krheritage` | **존재하지 않는다** — 인증키가 없다 | provider 소스: `serviceKey`는 `apis.data.go.kr` 호스트에만 주입되고 heritage는 `www.khs.go.kr/cha`다 | **2026-09-14 확인** |
| `krex` | **일일 한도는 미공개 — 제약은 TPS다.** 라이브러리가 프로세스당, `provider_rate_gate`가 프로세스 사이를 막아 **합계 5 TPS** | OpenAPI 소개·목록·인증키 발급·이용안내 **네 페이지 모두**에 일일 수치가 없다(키는 즉시 발급) | **2026-09-14 확인(없음을 확인) → TPS로 전환** |
| `mois`/`localdata` | **존재하지 않는다** — 기관 자체 다운로드라 키·활용신청이 없다 | data.go.kr 파일데이터 `15045016`·`15044967`의 제공형태가 "기관자체에서 다운로드(제공데이터URL기재)"이고 그 URL이 `file.localdata.go.kr/file/<slug>/info`다 | **2026-09-14 확인** |
| `seoul-open-data` | **아직 보지 않았다** | 서울 열린데이터광장은 data.go.kr과 별개 포털이고 인증키도 별개다. 현재 사용량은 **월 1회 × 1요청** (서울 책방 606건이 1000행 한 페이지에 들어온다)이라 어떤 한도라도 여유가 크다 — 분모를 세기 전에 분자가 이미 무시할 수준이다 | 2026-09-19 라이브 확인 |

**"분모가 없다"가 셋 다 다른 뜻이다.**

- `krheritage`는 **키가 없으므로 per-key 한도라는 개념이 없다.** 그래서 sweep당
  ~3,950요청에 대해 "몇 %"를 물을 대상이 애초에 없다 — 위험은 쿼터 소진이 아니라
  **과도 호출로 인한 차단**이고, 그것은 분모가 아니라 예의(간격·동시성)의 문제다.
- `krex`는 키가 있는데 **일일 한도를 공개하지 않는다.** 그래서 **분모를 기다리지 않고
  다른 축으로 옮겼다 — 초당 건수다.** 없는 분모에 예산을 짜는 것은 없는 분모를 지어내는
  일이고, 이 provider에서 실제로 조일 수 있는 것은 간격이다. 자세한 것은 아래.

#### krex는 분모가 아니라 **TPS 5**로 막는다 (2026-09-14)

`python-krex-api`의 `KrexHttp`가 token bucket으로 **초당 5건**을 넘기지 않는다
(`max_rps`, 기본 `5.0`). 일일 한도를 알아내면 그때 예산을 더할 수 있지만, 그 전에도
**지금 지켜지는 상한이 하나는 있다.**

읽는 사람이 알아야 할 성질 넷:

| 성질 | 값 | 왜 그렇게 했나 |
|---|---|---|
| 버스트 | **없음**(capacity=1) | capacity가 `max_rps`면 가득 찬 버킷에서 5건이 즉시 나가고 그 초에 지속분이 더해져 **첫 1초에 10건**이다. 요구사항은 평균이 아니라 상한이다 |
| 재시도 | **요청으로 센다** | 버킷이 재시도 루프 **안**에 있다. 밖에 두면 시도 수만 세고 나가는 건수가 상한을 넘는다 |
| 범위 | **클라이언트당**(포털당 아님) | `data.ex.co.kr`·`data.go.kr` 호출이 같은 버킷을 지난다. 반대로 **클라이언트를 여러 개 만들면 버킷도 여러 개다** |
| 동시성 | **스레드 안전** | 동기 API는 호출마다 새 이벤트 루프를 쓰고, 러닝 루프가 있으면 별도 스레드에서 돈다 — 락이 루프가 아니라 스레드를 막아야 한다 |

#### Map 합계는 아직 5 TPS가 아니다 — 열려 있는 구멍 (2026-09-14)

> 이 문단은 한 번 **틀리게 적혔다가** 적대 리뷰에서 뒤집혔다. 원래 "큐 러너가 순차
> 처리하므로 합계 5 TPS"라고 적었는데, 그 순차성은 **run 하나 안에서**의 이야기이고
> run 자체는 동시에 여러 개가 뜬다. 닫혔다고 적은 구멍이 **현재 설정으로 열려 있다.**

참인 부분:

- krex fetcher 넷(`fetch_krex_rest_areas`·`fetch_krex_traffic_notices`·
  `fetch_krex_rest_area_fuel_prices`·`fetch_krex_rest_area_weather`)은 각자
  `KrexClient`를 **하나** 열고 그 안에서 페이지네이션한다 — 한 fetcher 실행 = 버킷 하나.
- prod에 feature cron schedule은 전부 꺼져 있다(`default_status=STOPPED`).
- `feature_update_executor`는 한 run 안에서 scope를 **순차** 처리한다.

거짓인 부분 — **run은 동시에 뜬다:**

| 자리 | 값 |
|---|---:|
| `FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS` (`sensors.py`) | 틱당 **10** RunRequest |
| 큐 센서 `default_status` | **RUNNING** (15초 틱) |
| `docker/dagster.yaml` `max_concurrent_runs` | **10** |
| `tag_concurrency_limits[kor_travel_map.feature_update_request_id]` | **4** |

request마다 run_key가 다르므로 **worker run 넷이 동시에** 실행될 수 있고, 각 run이
자기 프로세스에서 자기 `KrexClient`를 연다 → **버킷 넷 → 최대 20 TPS.**

krex를 직렬화하는 것은 아무것도 없다:

- 실행 시점 advisory lock은 **request id**와 **scope key**에 걸린다. scope가 다르면
  키가 달라 둘 다 진행한다.
- Dagster pool `KREX_NOTICE_SNAPSHOT_POOL`은 **asset**에 선언돼 있는데, 큐 경로는
  asset wrapper를 **우회한다**(`feature_update_runner.py`가 원본 run 함수를 부른다).
- `ops.provider_refresh_policies`는 **기록이지 집행이 아니다.** `max_concurrent`는
  plan payload에 실리기만 하고(`feature_update_executor.py` `_rate_limit()`),
  `max_requests_per_day`는 upsert 시 간격 정합성 검증에만
  (`provider_refresh_schema.py`), `min_interval_seconds`는 consistency 리포트의 SLA
  판정에만 쓰인다. **셋 다 아무도 그 값을 보고 멈추지 않는다.**

  **그리고 그 테이블은 prod에서 0행이다**(2026-09-16 실측, seed도 0). 행이 없으면
  `_skip_reason()`이 `"allow_targeted"`로 **fail-open**하므로, gate가 이 테이블을 읽게
  만들면 읽을 값이 없어 통과시킨다 — 언제나 적용되는 코드 상수(`PROVIDER_RATE_GATES`)
  보다 **나빠진다.** 상한을 DB로 옮기는 것은 그 테이블이 채워지고 fail-**close**가 된
  뒤의 일이다.

**그래서 프로세스당 상한만으로는 부족하다.** `feature_update_runner`의
`provider_rate_gate`(Postgres advisory lock + 교대 간격)가 그것을 닫는다 — 자세한
것은 `T-VN-KREX-TPS-FANOUT`.

#### 라이브러리가 async-only가 되면서 생긴 것 (2026-09-15)

형제 `python-*-api` 13개가 **native async only + 공유 TPS 제어**로 재작성됐다. krex는
기본값을 유지한다(`max_rps=5.0`, 버킷 `capacity=1` — 버스트 없음). 실측으로 확인했다:
8건 동시 요청의 최소 간격 0.2004초, 최악 1초 창 5건, `NaN`/`inf`/0/음수/`bool` 거절.

새로 생긴 것은 **`rate_limiter=` 주입**이다 — 여러 client가 버킷 하나를 공유해 예산을
합산한다. 다만 그것은 **한 이벤트 루프 안에서**만 성립한다(`AsyncTokenBucket`은 다른
루프에서 쓰이면 `RuntimeError`). 그래서:

| 층 | 무엇을 막나 | 도구 |
|---|---|---|
| 한 client | 초당 5건 | 라이브러리 버킷(기본값) |
| 한 프로세스의 여러 client | 합산 예산 | `rate_limiter=` 주입 *(Map은 아직 안 쓴다 — 한 run에서 krex fetcher가 동시에 돌지 않는다)* |
| **프로세스 사이** | 합계 5 TPS | **`provider_rate_gate`** (advisory lock + 교대 간격) |

**두 수가 같은 곳에서 나와야 한다.** gate의 교대 간격(`1/5`초)과 라이브러리의
`DEFAULT_MAX_RPS`(5)는 서로를 모른 채 각자 `5`를 들고 있었다 — 라이브러리가 3이나
10으로 바뀌면 gate가 조용히 틀린 값이 된다. `tests/lint/
test_rate_gated_providers_declare_the_gate.py`가 형제 소스의 `DEFAULT_MAX_RPS`를
AST로 읽어 그 둘을 결박한다(형제 체크아웃이 없으면 skip).
- `mois`/`localdata`도 **없는 것이 정상이다.** 키가 없기 때문이다 — 아래 참고.

### MOIS는 data.go.kr로 이관됐는데 **파일 경로는 그대로다** (2026-09-14)

data.go.kr 파일데이터 상세가 제공형태를 "**기관자체에서 다운로드(제공데이터URL기재)**"로
적고, 그 URL 필드가 **`https://file.localdata.go.kr/file/<slug>/info`** 다 — 지금
`mois.LocalDataFileClient`가 쓰는 바로 그 주소다. 두 건으로 확인했다:

| data.go.kr 데이터셋 | 제공데이터 URL | 전체 행 |
|---|---|---:|
| `행정안전부_식품_일반음식점`(15045016) | `/file/general_restaurants/info` | 2,129,830 |
| `행정안전부_문화_관광숙박업`(15044967) | `/file/tourist_accommodations/info` | 3,439 |

**그래서 옮길 것이 없다.** 그리고 이 경로는 무료·이용허락 제한 없음·**활용신청 불필요**
이므로 per-key 일일 한도라는 개념이 없다.

MOIS에는 오픈API 표면(`apis.data.go.kr/1741000/<slug>/info`)도 있고 그쪽은 **개발계정
10,000/일**(오퍼레이션당)이다. 다만 Map은 그것을 쓰지 않고, 쓰려면 slug마다 활용신청이
필요하다(prod 키로는 403). 같은 데이터를 오픈API로 받으면 `general_restaurants` 한
slug만 2,129,830행 → 페이지 수천 개다. 지금 방식은 slug당 3요청(info·validate·download),
**42 slug = 126요청**으로 전체 스냅샷을 받는다.

**깨졌을 때 볼 곳은 data.go.kr 파일데이터 페이지의 URL 필드다.** 그것이 정본이고,
`file.localdata.go.kr`는 그 필드가 가리키는 현재 값일 뿐이다. 2026-09-14 기준 그 호스트는
**Referer를 요구한다**(없으면 302 → `/error.html` → 403). 라이브러리는 이미 유효한
Referer를 보내므로 동작한다(info·validate 모두 200 실측). 사람용 포털
`www.localdata.go.kr`는 같은 날 20초 타임아웃으로 죽어 있었다 — 파일 호스트와 별개다.

### OpiNet — 저장소가 5배 잘못 알고 있었다 (2026-09-14)

이 저장소는 무료키 한도를 **1,500**으로 알고 그 위에 예산 전체를 세웠다. 실제로는
**300**이고, 1,500은 **유료 프리미엄 3종**의 값이다. Map이 부르는 네 오퍼레이션
(`lowTop10` · 반경 내 주유소 검색 · 주유소 상세 · 지역코드)은 전부 일반 API 목록에
있다.

| 자리 | 종전 | 실제 300 대비 | 지금 |
|---|---:|---|---:|
| `opinet_run_call_budget` 기본 | 600 | **하루 한도의 2배** (place job과 겹치면 4배) | **140** |
| 같은 필드 `le` 상한 | 700 | 설정 한 줄로 하루의 2.3배 | **300** |
| `opinet_low_top_max_calls` 기본 | 180 | `get_area_codes`(~19)와 합쳐 하루의 66% | **90** |

**켜져 있었다면 첫날에 막혔을 값이다.** prod는 `opinet_scope_mode=disabled`라 실제로
쓰이지는 않았다 — 잠복 결함이었다. 그리고 이것을 찾은 것은 계측이 아니라 **공식
자료를 한 번 본 것**이다.

대가는 커버리지다. lowTop 상한이 180 → 90이면 시군 윈도가 60 → 30으로 줄어 전국
1주기가 ≈4일 → ≈8일이 된다. run당 cap으로는 "하루 2 run"을 표현할 수 없기 때문에
생기는 손해이고, **하루 예산**이 있으면 같은 안전성에서 더 쓸 수 있다
(`T-VN-QUEUE-QUOTA`). `tests/lint/test_opinet_budget_fits_the_daily_limit.py`가
이 산수를 결박한다.

## 3. 산수 — KMA (기록, 평가 대상 아님)

> **2026-09-14 지시로 KMA·에어코리아는 쿼터 평가 대상에서 빠졌다.** 둘 다
> 2026-09-09부터 자동 적재가 꺼져 있고(`DISABLED_FEATURE_LOAD_SCHEDULES`),
> 큐 경계가 그 결정을 강제한다. 이 절은 **분모를 어떻게 얻었는지의 기록**으로
> 남긴다 — 여기 숫자로 운영 판단을 하지 않는다. 재활성화는 그 지시를 되돌리는
> 일이고 이 문서의 일이 아니다.


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

> **주의**: KMA·AirKorea 자동 적재는 2026-09-09부터 꺼져 있다
> (`DISABLED_FEATURE_LOAD_SCHEDULES`). 위 산수는 **다시 켰을 때**의 것이다.
>
> 2026-09-14까지 그 목록은 **시계만** 껐다. 이 저장소의 prod는 cron이 아니라
> **feature update queue**로 돈다 — schedule은 전부 `default_status=STOPPED`이고
> 켜진 적이 없는 반면 `feature_update_request_queue_sensor`는 기본 RUNNING이다.
> 그 큐 runner에 꺼진 operation의 spec이 그대로 있었고 정책 게이트는 row가 없으면
> fail-open이라, **사용자가 끈 provider가 살아 있는 경로로 나가고 있었다.**
> 지금은 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 큐 경계가 읽어 typed skip
> (`provider_auto_load_disabled`)을 낸다. 사람이 Dagster UI에서 job을 직접 돌리는
> 백필은 그대로다 — 끄는 것은 시계이지 능력이 아니다.

## 4. 분자 — 진입점 40개 중 35개가 전부 센다

- **격자 순회형**(KMA 3종): 요청 수 = 격자 수. 격자 루프가 호출마다 계수한다.
  `grids_fetched`(성공한 격자 수)와 **다른 수**임에 주의 — 실패해 중단된 격자도
  요청은 나갔다. 처음에 그 둘을 같은 이름으로 실었다가 정본을 하나로 모았다.
- **bulk/표준데이터·페이지네이션형**: sweep당 요청 수 = 페이지 수. 2026-09-13부터
  같은 `upstream_requests_min`으로 나간다.

**배선은 실행 문맥이 대신한다.** fetcher가 generator라 "세는 자리(페이지 루프)"와
"내보내는 자리(asset output metadata)" 사이에 값을 흘릴 인자가 없었다. 그래서
`kortravelmap.dagster.upstream_requests`가 `ContextVar`로 계수기를 들고, **실행
경계 넷**이 그것을 연다 — asset wrapper 둘(`run_tracked_feature_asset`,
`feature_place_mcst_culture`), feature-update queue의 `FeatureUpdateAssetRunner`,
그리고 MOIS Phase A op(`mois_localdata_source_sync_op`). provider fetcher 32개의
시그니처는 하나도 바꾸지 않는다.

합치는 자리는 `etl._add_output_metadata`다 — **asset 경로의 주 초크포인트이고,
유일한 자리는 아니다.** 이 패키지에는 `context.add_output_metadata`를 직접 부르는
자리가 더 있다(op/sensor/maintenance 쪽). feature asset이 그 길로 새면 센 값이
버려지므로, `tests/lint`가 feature asset 모듈에서 그것을 막는다.

**`_min`이 뜻하는 것.** 페이지 하나 = 요청 **적어도** 하나다. 콜백이 안에서
재시도하면(외부 `upstream_retry` attempts, provider client 내부 retries) 그것은 이
층에서 보이지 않고, provider lib이 한 번의 호출 안에서 여러 요청을 보내는 자리도
있다(krex `latest_weather`의 lookback 루프 — 그래서 그쪽은 상한을 따로 선언한다).
즉 "적어도 이만큼은 썼다"이고, 한도와 비교할 때 그 방향으로만 안전하다.

**"세지 않았다"는 값을 내지 않는다.** 계수기가 열려 있어도 **한 번도 기록되지
않았으면** key 자체가 실리지 않는다.

이 구분이 첫 판에는 없었고 적대 리뷰가 blocker로 잡았다 — 계수기는 asset 35개
전부에서 열리는데 세는 자리는 셋뿐이라 **OpiNet이 수천 건을 쓰면서 0을 냈다.**
하필 그것이 저장소가 유일하게 **한도 대비 run 예산을 코드에 박아 둔** provider다(`_OPINET_RUN_CALL_BUDGET = 600`
vs 무료키 1,500/일, #545). **예산을 짜 둔 자리의 분자가 0이었다** — 그리고 그
예산기(`_OpinetCallBudget.spend()`)는 호출마다 정확히 1을 차감하고 있었다.
한 줄이면 됐다.
틀린 0은 읽는 사람을 멈추게 하지
못하고, 없는 값은 멈추게 한다.

### 커버리지 — 진입점 40개 중 35개가 전부 센다

`tests/lint/test_every_fetcher_counts_or_declares_why_not.py`가 **명시 목록**
(`_EXPECTED_FETCHERS`)의 진입점마다 **세거나, 왜 못 세는지 선언하거나**를 요구한다.
목록에는 fetcher 30개 + MOIS Phase A(`sync_mois_source_db`) + krex 스냅샷 헬퍼 1개가
들어 있다 — 접두사로 유도하던 종전 판은 개명 한 번으로 선언 없이 빠질 수 있었고,
MOIS의 slug별 LOCALDATA 다운로드는 통째로 게이트 밖이었다. 목록 크기 자체에도
래칫이 걸려 있어 **조용히 줄일 수 없다**.

**KMA·에어코리아는 목록에 없다**(2026-09-14 지시) — 게이트의
`_EXCLUDED_FROM_EVALUATION`에 이유와 함께 적혀 있다. 계수 호출은 코드에 그대로
있으므로 그 asset이 돌면 값은 나온다. 빠진 것은 **평가**이지 계측이 아니다.

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

| 진입점 | 세는 부분 | 못 세는 부분 | 그래서 metadata는 |
|---|---|---|---|
| `fetch_opinet_stations` | `low_top_area` 모드(`_OpinetCallBudget.spend()`) | `bbox`/`poi_cache_target` 모드의 enumerate | bbox 모드에서는 **key가 없다** |
| `fetch_opinet_station_price_details` | `low_top_area`는 예산기가 정확히 셈 / `bbox`·`poi_cache_target`은 `get_station_detail`(uni_id당 1건) | `bbox`·`poi_cache_target`의 enumerate | `low_top_area`는 정확, 나머지는 **key는 실리되 과소계수** |
| `sync_mois_source_db` | 큐 runner 경로 · Phase A op | asset 경로(resource init이 계수 범위보다 앞) | asset 경로에서는 key가 없다 |

`iter_stations_in_bbox`는 bbox를 격자로 덮으며 셀마다 `aroundAll`을 부르는데, 셀 수
계산이 provider private이다. bbox 하나를 1로 세면 1과 20,000을 같게 만든다 — 그래서
**세지 않는다.**

**"기록이 없으면 key가 없다"는 보증이 세 행에 똑같이 적용되지는 않는다.**
`fetch_opinet_stations`는 bbox 모드에서 아무것도 세지 않으므로 값이 안 나간다(정직한
침묵). 그러나 `price_details`는 상세 조회를 세므로 **값이 나가되 실제보다 작다** —
이 행만은 "없는 값"이 아니라 "작은 값"이다. 한도 대비 비율을 볼 때 그 방향을 기억해라.

그 목록은 검사기의 `_PARTIALLY_COUNTED`에 이유와 함께 박혀 있고, `_UNCOUNTABLE`과
겹치지 못하며, **계측된 쪽으로 세어 주지도 않는다** — 완전 계측을 부분 계측으로
강등하는 것이 공짜면 그것이 값싼 도피로가 된다. 총량을 실제로 묶는 것은 §3의
하루 한 번 coalescing이다.

### 계수기는 어디서 열리나 — 경계가 넷이다

`note_upstream_request()`는 계수기가 열려 있을 때만 기록한다. 여는 자리는 넷이다:

| 경계 | 왜 따로 필요한가 |
|---|---|
| `run_tracked_feature_asset` | single-member asset wrapper |
| `feature_place_mcst_culture` | 이 asset만 multi-member라 wrapper를 안 지난다 |
| `FeatureUpdateAssetRunner` | 큐 경로는 wrapper가 아니라 **원본 run 함수**를 직접 부른다 |
| `mois_localdata_source_sync_op` | Phase A는 asset이 아니라 plain `@op`이다 |

뒤 둘을 빠뜨린 것이 2·3차 리뷰의 blocker였다. **계수기가 안 열리면
`note_upstream_request()`는 조용한 no-op이고, 정적 검사는 그것을 보지 못한다** —
호출 자리가 있기만 하면 초록이기 때문이다.

큐 runner에서는 계수기를 `spec.resources()` **앞**에서 연다. resources 구성이
I/O를 할 수 있기 때문이다 — MOIS Phase A가 거기서 전국 파일을 받는다.

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

## 5. 큐 경로에는 아직 예산이 없다 (T-VN-QUEUE-QUOTA)

§3의 산수는 **cron 기준**이다. 그런데 이 저장소의 prod는 cron이 아니라 **feature
update queue**로 돈다 — feature schedule은 전부 `default_status=STOPPED`이고 켜진 적이
없는 반면 `feature_update_request_queue_sensor`는 기본 RUNNING이다(2026-09-14 prod
실측: instigator state 11개가 전부 센서 + 분당 job 하나, feature asset
materialization 0건).

**그 경로에 일일 예산이 없다.** 상한은 센서 tick당 10 run(15초 간격)뿐이고 하루
총량은 어디에도 없다. 사실상의 가드는 둘뿐이다:

**KMA·에어코리아는 여기서도 평가 대상이 아니다** — 꺼져 있고, 큐 경계가 그것을
강제한다. 남는 provider 중 일일 가드가 있는 것은 **하나뿐**이다:

| provider | 가드 | 효과 |
|---|---|---|
| OpiNet | `already_succeeded_today_kst` | 하루 한 번 성공하면 그날 skip |

나머지 — `krheritage` · `krex` · 전국표준데이터 · `krforest` · `knps` · `mcst` ·
`visitkorea` · `khoa` · concierge — 에는 **아무것도 없다.** 큐 요청이 반복되면 그만큼
나간다. 그리고 data.go.kr 쪽 다수가 **1,000/op/일**이다.

**단, 필요한 조치가 provider마다 다르다**(2026-09-14 분모 조회 결과):

| provider | 분모 | 필요한 것 |
|---|---|---|
| data.go.kr 계열(표준데이터·visitkorea·krforest·knps·khoa…) | 있다(§2) | **일일 예산** — 한도 대비 비율을 지킬 수 있다 |
| `krheritage` | **없다 — 인증키가 없다** | **예산이 아니라 rate limit**(간격·동시성). sweep당 ~3,950요청에 "몇 %"를 물을 대상이 없고, 위험은 소진이 아니라 **차단**이다 |
| `krex` | 미공개 | **문의** — 모르는 것이지 없는 것이 아니다 |
| `mois`/localdata | 미확인 | **재시도** |

즉 "큐 경로에 provider별 일일 예산을 만든다"는 처방은 **분모가 있는 쪽에만 맞는다.**
krheritage에 예산을 짜는 것은 없는 분모를 지어내는 일이다.

**정책의 rate limit은 기록만 된다.** `provider_refresh_policies`의 rate limit 필드는
metadata payload로 실릴 뿐 한 번도 강제되지 않는다 — §4 조문 5가 admin UI에서 지운
"근거 없는 보증"과 같은 종류다.

**targeted refresh가 필요 없는 scope까지 깨운다.** 반경/bbox membership SQL이 요청과
`operation_scope.sync_scope`를 대조하지 않아, 한 dataset의 **선언된 모든** sync_scope가
함께 잡힌다. 평가 대상 provider에서는 전량 순회 scope가 targeted 요청에 딸려 오는
형태로 나타난다.

**이미 고친 것 하나.** `DISABLED_FEATURE_LOAD_SCHEDULES`는 시계만 껐고 큐는 꺼진
provider를 그대로 불렀다(정책 게이트는 row가 없으면 fail-open이고 baseline seed에
row가 0건이다). 2026-09-14부터 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 큐 경계가
읽어 `provider_auto_load_disabled`로 건너뛴다. 이 절의 나머지는 **끄지 않은
provider의 총량** 문제다.

**분자는 어디서 읽나.** asset 경로는 output metadata의 `upstream_requests_min`이고,
큐 경로는 `ProviderDatasetRefreshResult.metadata`의 같은 key다.

## 6. 이 문서를 고쳐야 하는 때

- data.go.kr에서 운영계정으로 승격하거나 활용신청을 추가/변경했을 때
- 격자 상한(`kma_weather_max_grids_per_run`)이나 schedule cron을 바꿀 때
- 분자 계측의 커버리지나 면제 목록이 바뀔 때 — `tests/lint/test_every_fetcher_counts_or_declares_why_not.py`의 상수(`_EXPECTED_FETCHERS`
  ·`_EXPECTED_FULLY_COUNTED`·`_UNCOUNTABLE`·`_PARTIALLY_COUNTED`)와 §4를 **함께** 고친다.
  그 상수가 결박이고 §4가 서술이다 — 한쪽만 고치면 게이트가 빨개진다

분모는 마이페이지의 값이 정본이다. 여기 적힌 것은 **2026-09-13 시점의 사본**이고,
사본은 늙는다.
