# 읽기 성능 개선 계획 — Map·weather·transport (2026-11-17)

소유자 요청(2026-11-17)으로 세 서비스(`kor-travel-map`·`kor-travel-weather`·`kor-travel-transport`)의
읽기 경로를 코드와 운영 관측으로 검토하고 개선안을 정리한다. 다른 에이전트가 이 문서만 읽고 구현을
시작하므로 마지막 절(§8)이 작업 목록이다.

- 상태: **3차(적대 리뷰 2회 반영)**. 이 문서를 쓰는 동안 코드·설정·운영을 바꾸지 않았다.
- Map 작업(`T-READ-01`~`08`)의 **해제 조건은 [`docs/tasks-acceptance.md`](../tasks-acceptance.md)의 같은 ID
  절이 소유한다**(저장소 규약). 이 문서는 변경 내용·의존·검증·위험을 적는다. 목록은
  [`docs/tasks.md`](../tasks.md)다.
- 다른 저장소 작업(PinVi·Manager·weather·transport)은 이 문서가 해제 조건까지 소유하고, 각 저장소
  `docs/tasks.md`에는 이 문서를 가리키는 한 줄만 둔다.

## 1. 결론 먼저

1. **측정 창에서 가장 큰 지연은 Map의 SQL이 아니라 PinVi가 요청마다 하는 일과 디스크 대기였다.** PinVi는
   모든 요청에서 rate-limit 행을 쓰고 COMMIT하고, 사용자를 조회하고, 좌표가 있는 route는 위치 감사 행을
   쓴다. **상류를 전혀 부르지 않는 route 둘이 평균 1.63초와 6.53초였다**(§4.2, F-13). 같은 시각 n150의
   디스크 압력(PSI io `some`)은 avg60 29~90%였고 PG checkpointer는 버퍼 하나를 쓰는 데 평균 48 ms를 썼다
   (F-01·F-15).
2. **운영에서 Map 쪽 읽기 지연을 볼 방법이 없다** — Map 지표는 꺼져 있고 느린 질의 로그와
   `pg_stat_statements`가 없다(F-03). **그런데 PinVi는 Map·weather·geo 호출을 전부 `app.api_call_log`에
   이미 남기고 있다**(13만 행, 9월 말부터). 배포 없이 읽기만 하면 이 문서의 "모른다" 여럿이 풀린다 —
   그것이 첫 작업이다(`T-READ-PIN-06`).
3. **PinVi `GET /features/in-bounds`의 39%(38건 중 15건)가 503이었다**(측정 창). 같은 기간 bbox 색인 탐색 한
   번이 평균 11.7만 색인 행을 읽었다. 그 부하가 저배율 전국 집계인지, **PinVi 기본 화면(서울시청 zoom 12 →
   읍면동 집계, 서울의 공개 행 약 12.7만)**인지는 모른다(F-04).
4. **PinVi의 교통·날씨 조회는 한 요청의 호출 수가 자기 동시 호출 상한(각 2, 대기열 없음)을 넘는다**(코드
   추론). 여행 지도의 교통 레이어와 여행 보기의 날씨가 `unavailable`이 될 수 있다. 가장 싼 수정은 env 값
   둘이다(F-06).
5. **읽기 요청에 시간 상한이 없고, PinVi는 Map의 5xx를 세 번까지 다시 보낸다.** Map에 요청 마감을
   넣으려면 PinVi의 재시도 규칙을 **먼저** 고쳐야 한다(F-05).
6. **Map과 PinVi는 OpenAPI hash가 같아야 함께 회전한다.** Map의 spec을 바꾸는 작업은 Map 머지 → PinVi
   재vendor 머지 → 한 번의 pair 회전으로만 나갈 수 있다. 이 계획에서는 `T-READ-04` 하나다(§8.1).
7. **검색의 지역 경로("부산 맛집")가 가장 느린 정상 경로다**(소유자 실측 0.6~1.1초, F-07·F-08). PinVi의
   통합 검색은 여기에 geo(odroid)와 Kakao·Naver 순차 호출을 더한다(F-17).
8. **`feature.features`는 autovacuum이 한 번도 돌지 않았고(all-visible 58%), 색인이 heap의 두 배이고, HOT
   갱신이 0이다**(F-11·F-14). 표 단위 autovacuum 설정이 가장 싼 손잡이다.
9. **odroid는 측정 시점에 CPU가 포화였고, PG 데이터가 있는 NVMe에 남은 공간이 1.9 GB였다**(F-09·F-10,
   소유자에게 전달됨).
10. weather·transport 자체 REST는 **PinVi 사용자 경로에 거의 없다.** 운영 PinVi는 날씨·교통을 Map의
    Valkey 표면으로 읽는다(§3.1). 두 저장소에는 이 주제의 자체 작업이 이미 있어 그것을 따른다(§3.4·§3.5).

순서는 **이미 있는 기록부터 읽기 → PinVi의 요청당 비용과 동시 호출 상한 → 호스트·프로세스 보호 → 시간
상한(PinVi 재시도 규칙 먼저) → 호출 수 줄이기 → 측정으로 정하는 SQL 개선**이다(§6).

## 2. 범위·방법·증거 등급

### 2.1 범위

사용자 또는 서비스 사이의 읽기 경로다 — 공개·service GET(조회용 POST 포함), 그 SQL과 색인, 연결 풀과
프로세스 모델, 캐시(프로세스 안·Valkey·HTTP 헤더), 직렬화와 응답 크기, 팬아웃, 페이지, 기동 직후
비용, 서비스 사이 timeout·재시도, PinVi의 호출 방식. 쓰기·적재는 읽기를 느리게 하는 곳만 본다.

### 2.2 기준 commit

경로 인용은 아래 commit의 `경로:줄`이다. 접두 `MAP:`·`PIN:`·`WEA:`·`TRN:`·`MGR:`로 저장소를 적는다.

| 접두 | 저장소 | commit (`origin/main`, 2026-11-17 03:26Z clone) |
| --- | --- | --- |
| `MAP:` | `digitie/kor-travel-map` | `f1788da922c118650fc93e05aae42b3d0f5159f3` |
| `WEA:` | `digitie/kor-travel-weather` | `e68f16a75b033ecb2ceaf83b6d87a3d73bb614f4` |
| `TRN:` | `digitie/kor-travel-transport` | `6009537986d59bd8b401e165f5d81a1007e5ba29` |
| `PIN:` | `digitie/pinvi` | `b160594972dafe9458f220499552ff539c4c70d7` |
| `MGR:` | `digitie/kor-travel-docker-manager` | `31d56e4e6c43b14258cad93495c94630f4b82035` (문서만 참조) |

Map 경로의 약칭: `repo` = `src/kortravelmap/infra/feature_repo.py`, `api/` =
`packages/kor-travel-map-api/src/kortravelmap/api/`. weather: `API/` =
`packages/kor-travel-weather-api/src/kortravelweather_api/`, `SRC/` = `src/kortravelweather/`.
PinVi: `app/` = `apps/api/app/`.

운영 컨테이너가 이 commit과 같은 코드인지는 확인하지 않았다(측정 시점에 배포가 진행 중이었다).

### 2.3 증거 등급

- **[실측]** — 이 조사에서 읽기 전용으로 잰 값. 시각·방법을 §4에 적는다.
- **[추론]** — 코드에서 읽은 것. 실행해 확인하지 않았다.
- **[문서 주장]** — 저장소 문서·주석·PR 본문이 적은 수치. 이 조사에서 다시 재지 않았다.
- weather·transport·PinVi 코드는 보조 에이전트가 읽었고, 작업 근거로 쓰는 줄은 내가 다시 열어
  확인했다. 다시 열지 않은 인용에는 "(재확인 안 함)"을 붙인다.

### 2.4 측정 조건 — 이 수치는 조용한 호스트의 수치가 아니다

2026-11-17 03:31~03:46Z(KST 12:31~12:46)에 쟀다. n150에서는 배포와 전체 e2e가 진행 중이었다
(그 e2e 묶음의 완료 표식이 아직 없었다). 그래서 n150에는 카탈로그 조회·`/proc` 읽기·PinVi의
공개 `/metrics` 한 번·`/health` curl만 했다. `EXPLAIN ANALYZE`와 부하 시험은 하지 않았다. 04:32Z에 다시 봤을 때도 e2e는 끝나지 않았고 디스크 압력은
더 높았다(PSI io `some` avg60 90%·avg300 85%, load 10) — 그래서 **조용한 호스트의 기준선은 리뷰 1회차
뒤에도 재지 못했다**(`T-READ-01`).

DB는 Map API 컨테이너의 DSN을 그 자리에서 유도해 읽기 전용 transaction(`statement_timeout` 8초)으로 붙었고
DSN·key·token은 출력하지 않았다. n150 `/tmp`에 둔 조사용 임시 파일은 지웠다.

PostgreSQL 누적 통계의 창은 길어야 postmaster 기동(2026-11-13 12:26Z) 이후 3.6일이고,
`pg_stat_bgwriter.stats_reset`이 2026-11-15 05:21Z라 더 짧을 수 있다. 이 창에는 e2e와 배포가 들어 있다.

### 2.5 측정하지 못한 것

- Map 공개 endpoint의 HTTP 지연 분포. Map 지표는 꺼져 있다(F-03). PinVi의 `app.api_call_log`에는 호출마다
  시간이 남아 있으나, e2e가 도는 동안이라 그 표를 집계하지 않았다 — planner 통계 표본만 읽었다(§4.2).
- 질의별 시간·호출 수(`pg_stat_statements`가 DB에 없다).
- 조용한 호스트에서의 기준선. `T-READ-01`이 한다.
- weather·transport endpoint의 지연(odroid에는 `/health`와 목록 1건 curl만 했다).

## 3. 지금의 읽기 구조

### 3.1 호출 방향

```
브라우저·앱 ──▶ PinVi API (n150, uvicorn 1) ──▶ Map API (n150 127.0.0.1:12701, uvicorn 1)
                                                   ├─ Feature 읽기 ─▶ 공용 PostgreSQL(n150) DB kor_travel_map
                                                   ├─ /v1/service/transport/* ─▶ Map Valkey(n150)
                                                   ├─ /v1/service/weather/*   ─▶ Map Valkey(n150)
                                                   └─ 유가 추이 프록시 ─▶ transport(odroid)
                 PinVi ──▶ weather(odroid) /v1/weather/markers   (특보만, 90초 캐시)
                 PinVi ──▶ geo(odroid) /v2/search               (통합 검색의 주소, 3초 예산)
                 PinVi ──▶ Kakao · Naver                        (통합 검색, 내부 결과가 적을 때)
Map Dagster(n150) ──▶ weather·transport /v1/service/exports/* (odroid) ──▶ Map Valkey 세대 교체
```

- [실측] 운영 PinVi는 `PINVI_KOR_TRAVEL_MAP_TRANSPORT_ENABLED=true`,
  `PINVI_KOR_TRAVEL_MAP_WEATHER_ENABLED=true`다. Map 주소는 `http://127.0.0.1:12701`, weather 직접
  주소는 `http://<prod-host-ip>:12201`이다.
- [추론] PinVi에는 transport 직접 client가 없다 — 교통은 Map `/v1/service/transport/*`로만 읽는다
  (`PIN:app/api/v1/transport.py:3`). transport 저장소에는 Valkey도 `markers-near`도
  없다(`TRN:backend/pyproject.toml`에 redis·valkey 의존성 없음). "Valkey 반경 검색
  (최대 50 km)"은 Map의 표면이다(`MAP:api/routers/service_transport.py:88`).
- 따라서 사용자 요청의 지연은 대부분 **n150 안**에서 정해진다. odroid는 (a) Map 적재가 받아 가는
  export, (b) PinVi의 특보 조회, (c) 유가 추이 프록시, (d) 두 서비스의 관리 화면에서 걸린다.

### 3.2 Map

| 항목 | 지금 | 근거 |
| --- | --- | --- |
| 프로세스 | uvicorn 1개, `--workers` 없음 | [추론] `MAP:docker/api-entrypoint.sh:468`; [실측] 컨테이너에 uvicorn 1개·thread 9 |
| DB 연결 | asyncpg, pool 5 + overflow 10, `pool_pre_ping`, `pool_timeout` 미지정(기본 30초), 연결마다 `jit=off` | [추론] `MAP:src/kortravelmap/infra/db.py:884-928`, `MAP:api/db.py:46-63` |
| 읽기 세션 | 검색·상세·batch는 read-only REPEATABLE READ(`get_read_snapshot_session`), in-bounds·bbox·nearby는 일반 세션(`get_session`) | [추론] `MAP:api/db.py:94-134`, `MAP:api/routers/features.py:1003,1090,1295` |
| 인증 | PinVi는 service token(DB 조회 없음). 공개 key는 해시 목록을 프로세스에 30초 둔다 | [추론] `MAP:api/auth.py:921-959`, `MAP:api/settings.py:985` |
| 캐시 | 데이터 캐시 없음(ADR-030). Valkey는 날씨·교통 상태의 저장소이지 PG 앞의 캐시가 아니다 | [추론] `MAP:docs/architecture/performance.md:537`, `MAP:docs/adr/114-weather-transport-state-in-memory-db.md:313` |
| 압축·캐시 헤더 | gzip 미들웨어 없음. ETag는 상세(`/features/{id}`)에만 있다 | [추론] `MAP:api/app.py`(미들웨어는 Dagster client·request-id·호출 로그·지표·CORS뿐), `MAP:api/routers/features.py:1456-1535` |
| 관측 | 지표 코드는 있으나 운영에서 꺼짐. 호출 로그 기본 꺼짐. access log에 시간 없음 | F-03 |

**요청이 지나는 길(뜨거운 endpoint).**

| endpoint | 부르는 쪽 | SQL·저장소 | 상한 |
| --- | --- | --- | --- |
| `GET /v1/features/in-bounds` | PinVi 지도(이동마다), Map 관리 화면 | zoom ≤7 시도·≤10 시군구·≤13 읍면동 집계(`repo:1683-1766`, `api/routers/features.py:785-799`), zoom ≥14 개별 행(`repo:1578-1607`) | `max_items` 기본 1000·최대 2000 (`features.py:1115`) |
| `GET /v1/features/search` | PinVi 통합 검색(입력마다), MCP | 별칭 조회 → 지역 표본 → 지역 행 수 → 순위 CTE(`repo:7718-7860`, `repo:2213-2602`) | `page_size` 기본 50·최대 200 |
| `GET /v1/features/{id}` | PinVi 상세 카드·날씨·장소 상세 | 참조 해석 → 공개 행 → 속성 → curation, 문장 4개 안팎(`features.py:1489-1535`) | ETag·304 |
| `POST /v1/features/batch` | PinVi 여행 보기 | 참조 해석 + `unnest(ids)` 두 문장(`features.py:1780-1795`, `repo:1265-1300`). route가 `SQLAlchemyError`를 잡아 503 `FEATURE_BATCH_UNAVAILABLE`로 바꾼다 | 200건 |
| `GET /v1/features/nearby` | PinVi 주변 | `coord_5179` GiST `ST_DWithin`(`repo:8029` 이하) | 500건 |
| `GET /v1/service/transport/{dataset}` | PinVi 교통 레이어·여행 반경 | Valkey 왕복 4번 — 포인터 `GET` → meta `HGETALL` → `GEOSEARCH` → `HMGET`(`api/routers/service_transport.py:589-616`, `MAP:src/kortravelmap/infra/valkey_state.py:575-640,697-760`) | 500건, 반경 50 km |
| `/v1/service/weather/*` | PinVi 날씨 카드·마커 | Valkey `read_many`(왕복 2번, `valkey_state.py:785-830`) | batch 50곳 |

Map의 SQL은 이미 여러 번 고쳐졌다 — bbox 술어는 변환 없이 GiST를 타고(ADR-012), 저배율 집계는 #1455로
두 팔을 나눴고, 검색은 JIT를 껐다(`repo:7783-7786`). 그래서 이 계획은 "색인 하나 더"가 아니라
**구조와 운영 조건**을 먼저 본다.

### 3.3 PinVi가 Map을 부르는 방식

[추론] 전부 `PIN:` 코드에서 읽었다.

- Map client는 프로세스당 `httpx.AsyncClient` 하나다. timeout 5초는 **단계별**(연결·읽기·쓰기·pool 각각)
  이고 요청 전체의 상한이 아니다(`app/clients/kor_travel_map.py:1245-1256`, `app/core/config.py:810`).
  공개 월별 축제만 읽기 15초다(`kor_travel_map.py:58,1096-1105` — 주석이 "#714: 처음 조회하는 월은
  5.9~6.2초"를 적는다).
- 재시도는 3번이다(`config.py:815`). **연결 실패와 5xx는 다시 보내고**(`kor_travel_map.py:590-599`),
  `ReadTimeout`은 다시 보내지 않는다(`kor_travel_map.py:64-73` — 주석이 "#702 운영 기록: 같은 전국
  bbox가 5초 timeout ×3"을 적는다). in-bounds·검색·상세·batch가 모두 이 기본값을 쓴다. `Retry-After`는
  429·409에서만 읽는다(`kor_travel_map.py:631-634`). 교통·날씨 wrapper는 `retry=False`다.
- 범위별 동시 호출 상한(대기열 없음, 차면 바로 거부): features 10·viewport 4·transport 2·weather 2·
  festivals 4(`app/core/config.py:825-828`, `kor_travel_map.py:481-488`). [실측] 운영 env에 이 값을
  바꾸는 변수는 없다.
- 회로: 범위마다 연속 3번 실패하면 120초 열린다(`app/clients/_resilience.py:22,52`).
- **요청마다 rate-limit 쓰기**: 우회 경로가 아닌 모든 요청이 handler 앞에서 `app.rate_limit_buckets`에
  upsert하고 COMMIT한다(`app/middleware/rate_limit.py:203-237,270-317`). backend는 운영·staging에서
  PostgreSQL이다(`rate_limit.py:392-397`; [실측] `PINVI_ENVIRONMENT=production`).
- 지도 이동 한 번(웹, 250 ms debounce)이 PinVi 요청을 최대 4개 낸다 — in-bounds(기본 500건),
  날씨 마커(zoom ≥8), geometry용 in-bounds 한 번 더, 교통 레이어. Map 읽기로는 최대 5번이다
  (`apps/web/components/map/FeatureMapView.tsx:79`, 나머지 재확인 안 함).
- 여행 지도의 교통 반경 조회는 기준 장소(최대 60곳)를 2 km로 묶은 중심마다 Map을 부른다 — 레이어
  2개 × 중심 수, 레이어당 동시 6개(`app/services/transport_layers.py:204-220,249-264`).
- 여행 보기는 Feature batch를 받은 **뒤에** 날씨를 받는다(`app/services/trip_view_builder.py:213,278`).
  두 가지가 같은 요청 세션(`db`)을 쓴다.
- 서버 쪽 캐시: Feature batch 60초(`config.py:1024-1026`), 축제 월별 300초, 특보 90초. viewport·검색·
  상세에는 없다.
- **기본 화면**: 웹과 모바일 모두 서울시청 중심 zoom 12로 열고 자동 센터링은 zoom 13이다
  (`PIN:packages/domain/src/mapCenter.ts:15-20`). Map에서 zoom ≤ 13은 읍면동 집계다. 웹의 화면별 캐시는
  60초지만 zoom 10 위에서는 bbox를 소수 5자리로 맞추므로(`apps/web/lib/featureBounds.ts:51-56`) 사실상
  사용자마다 다른 키다.
- **날씨도 팬아웃한다**: 여행 보기는 캐시에 없는 날씨 위치를 동시 4개로 해석하고
  (`app/services/weather_map_resolver.py:72`) 값 묶음도 동시 4개로 받는다
  (`app/services/weather_map_state.py:596`). 모두 `weather` 범위(상한 2)를 쓴다
  (`app/clients/kor_travel_map_weather.py:275-286`). 여행 보기의 날씨 전체는 1.5초 예산이다
  (`config.py:973-975`).
- **호출 기록**: Map client는 호출마다 `app.api_call_log`에 provider·URL·status·시간·오류 종류·request
  id를 남긴다(`kor_travel_map.py:1245-1256`, `app/models/api_call_log.py:14-28`). 요청 경로 밖에서 묶어
  쓰므로 지연의 원인은 아니다. 상한·회로로 **보내지 않은** 호출은 행이 없다.
- **통합 검색**: Map 검색과 geo 주소 검색(odroid, 3초)을 함께 기다린 뒤, 내부 결과가 적으면 Kakao를
  부르고 그 다음에 Naver를 부른다(`app/api/v1/search.py:53,234,244-290`).

### 3.4 weather (odroid)

[추론] 프로세스는 uvicorn 1개(`WEA:compose.yaml:155`), DB는 동기 SQLAlchemy + threadpool, pool 10+10
(`WEA:SRC/repository.py:1406-1414`). 캐시는 모두 프로세스 안이다. 공개 읽기에는 `statement_timeout`이
없다. export는 `limit` 최대 5000이고(`WEA:API/routers/service_exports.py:194`), ETag 비교는 페이지를 다
만든 뒤에 한다(`service_exports.py:311-329`).

**weather에는 이 주제의 자체 설계가 이미 있다** —
`WEA:docs/design/weather-performance-use-cases-20261109.md`(P0-A 완료 페이지 사전 구성, P1-B~E)와 열린
작업 `W-EXPORT-SLOW-20261108`·`W-MARKER-01`(`WEA:docs/tasks.md:12,127`). 그 문서가 weather 내부 개선의
정본이고, 이 계획은 그것을 다시 쓰지 않는다. 이 계획이 더하는 것은 세 가지다.

1. 운영 PinVi의 사용자 경로에서 weather를 직접 부르는 곳은 특보(`/v1/weather/markers`)뿐이라는 사실
   (§3.1) — weather 쪽 우선순위는 "사용자 지연"이 아니라 "Map 적재가 끝까지 가는가"와 "odroid 부하"다.
2. 호스트 조건(F-09·F-10)과 artifact가 eMMC에 있다는 실측(§4.3).
3. 소비자 쪽에서 본 요청(§8의 `T-READ-WEA-*`).

2026-11-11의 예보 읽기 사고는 Map PR #1493 본문이 기록한다([문서 주장]) — 단기 위치 약 1,450곳이
`limit` 2,000 페이지 하나에 들어 요청 하나가 artifact 1,168개·1.15 GB를 읽다(cold 약 1,174초) 300초
timeout에 걸렸고, Map이 예보 page size를 200으로 나눴다(`MAP:src/kortravelmap/settings.py:749`).
"grid-projection"이라는 이름의 보류 변경은 두 저장소의 main 문서·브랜치 이름에서 찾지 못했다(§9).

### 3.5 transport (odroid)

[추론] 프로세스는 uvicorn 1개, `mem_limit`·`memswap_limit` 512 MB(`TRN:docker-compose.shared.yml:214-224`),
DB 엔진은 서버 측 `statement_timeout` 120초(`TRN:backend/app/db/session.py:29-33`, pool 크기는 재확인 안 함). 모든 읽기가
PostgreSQL이다. 앱 지표·요청 시간 로그가 없다(`backend/app`에서 `prometheus`·`/metrics`·`Server-Timing`
검색 0건 — 다시 확인했다).

읽는 쪽은 transport 관리 화면·주차 화면(브라우저 → nginx gateway)과 Map 적재(`/v1/service/exports/*`)다.

**transport에도 이 주제의 자체 작업이 있다** — 5,000곳 지도의 profile과 개선(`T-READ-MAX-01`~`03`, 완료,
`TRN:docs/reports/2026-11-07-read-max-optimization.md`), 유가 한 종류 지도의 단일 JSON 질의
(`TRN:docs/reports/2026-11-08-large-fuel-map.md`), 열린 backlog의 "저장 데이터 API 1초 목표"
(`TRN:docs/tasks.md:428`). [문서 주장] 그 profile에서 SQL은 5회 약 2.18초였고 Pydantic 생성이 4.79초,
UTC 보정이 1.78초였다 — **ARM에서는 SQL보다 Python이 더 썼다.** 이 계획의 transport 작업은 그 위에
얹는다(§8).

- `GET /v1/transport/features/places`는 종류마다 `COUNT(*)` 뒤 `SELECT … LIMIT`을 순서대로 돌리고
  (`TRN:backend/app/main.py:1655-1660`), `include_sources`(기본 참)면 종류마다 `SELECT DISTINCT source`를
  더한다(`main.py:1787-1791`). 전 종류 요청은 문장 26~28개다(개수는 재확인 안 함). [문서 주장] 5,000곳
  응답이 첫 요청 12.09초·이후 3.53·3.33초, 본문 7.36 MB(`TRN:docs/reports/2026-11-08-large-fuel-map.md:17,36`).
- 주차 이력 캐시는 API 프로세스 안에서 5초마다 확인하고, 바뀌면 30일치를 다시 읽어 brotli 6·gzip 9로
  압축한다(`TRN:backend/app/services/parking_history_cache.py:27,273,308-310`).
- 참조 export는 304를 낼 때도 페이지를 다 만든 뒤 비교한다. [문서 주장] 조건부 조회가 4.02초다
  (`TRN:docs/reports/2026-11-10-reference-artifact-improvement.md:75`).

## 4. 실측

### 4.1 n150 (2026-11-17 03:31~03:46Z, 배포·e2e 진행 중)

| 항목 | 값 | 방법 |
| --- | --- | --- |
| 디스크 압력 | 03:31~03:36Z: PSI io `some` avg10 66~90%·avg60 29~76%, `full` avg10 63%. 04:32Z: `some` avg10 84%·avg60 90%·avg300 85%, load 10 | `/proc/pressure/io` 4회, `uptime` |
| CPU·메모리 압력 | cpu `some` avg10 약 5%, memory 0% | `/proc/pressure/*` |
| 메모리 | 15,256 MB 중 used 5,131·buff/cache 7,674, swap 3,493 MB 사용, `swappiness` 10 | `free -m`, `/proc/sys/vm/swappiness` |
| Map API 프로세스 | VmRSS 14 MB, **VmSwap 154 MB**, uvicorn 1개, CPU 0.15% | `/proc/<pid>/status`, `docker stats` 한 번 |
| PinVi API 프로세스 | VmRSS 149 MB, VmSwap 15 MB, `--workers 1` | 같음, `docker top` |
| Map API 지표 | `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=false` | 컨테이너 env(값이 비밀이 아닌 항목만) |
| Map API 로그 | `"GET /health HTTP/1.1" 200 OK` 꼴(시간 없음), 최근 20,000줄에 5xx 0건 | `docker logs --tail` |
| PG 설정 | `shared_buffers` 1 GB, `effective_cache_size` 1.5 GB, `work_mem` 64 MB, `effective_io_concurrency` 1, `random_page_cost` 1.1, `max_connections` 100 | `pg_settings` |
| PG 관측 설정 | `log_min_duration_statement` -1, `track_io_timing` off, `log_lock_waits` off. preload에 `pg_stat_statements`가 있으나 DB `kor_travel_map`에는 확장이 없다 | `pg_settings`, `pg_extension`, `pg_available_extensions` |
| Map DB 크기 | 9,495 MB — schema `feature` 7,446 MB(`feature_base_field_values` 4,597 MB), `provider_sync` 1,955 MB | `pg_database_size`, `pg_total_relation_size` |
| `feature.features` | 약 44.2만 행, heap 379 MB, **색인 18개 720 MB** | `pg_class`, `pg_stat_user_indexes` |
| 같은 표의 갱신 | `n_tup_upd` 58,813, **`n_tup_hot_upd` 0**, dead 63,428, autovacuum 0회, all-visible 58% | `pg_stat_user_tables`, `pg_class` |
| 공용 PG 버퍼 | client backend 읽기 9,008,253회(86.6 GB), **eviction 10,615,464회** | `pg_stat_io`(클러스터 전체) |
| 공용 PG 컨테이너 | 블록 읽기 160 GB·쓰기 166 GB(기동 뒤 3.6일) | `docker stats` |
| 공용 PG 쓰기(약 46시간 창 — `pg_stat_bgwriter.stats_reset` 2026-11-15 05:21Z 기준) | checkpoint 552회(시간 주기)·요청 2회. checkpointer 버퍼 1,227,560개(9.4 GB), **write 시간 59,010초(버퍼당 약 48 ms)**, sync 947초. bgwriter 1,239,265개(`maxwritten_clean` 7,382). WAL 17 GB·FPI 2,665,374건·`wal_buffers_full` 47,690회. backend 쓰기 341,755·autovacuum 413,386 버퍼 | `pg_stat_checkpointer`, `pg_stat_bgwriter`, `pg_stat_wal`, `pg_stat_io` |
| 공용 PG 쓰기 설정 | `checkpoint_timeout` 300초, `max_wal_size` 2 GB, `wal_compression` off | `pg_settings` |
| Map Valkey | 사용 70 MB, `HMGET` 158,629회 평균 77 µs, `HGETALL` 164,209회 평균 45 µs. `save` 설정은 `900 1`인데 **fork 2,757회(가동 837,887초 — 약 304초마다)**이고 `SAVE`·`BGSAVE` 명령 기록은 없다. 컨테이너 블록 쓰기 53.8 GB | `INFO`, `CONFIG GET save`, `docker stats` |

색인 사용(같은 통계 창).

| 색인 | 크기 | 탐색 수 | 읽은 색인 행 | 탐색당 |
| --- | --- | --- | --- | --- |
| `idx_features_coord_gist` (공개 bbox) | 29 MB | 5,166 | 604,616,053 | **117,037** |
| `idx_features_name_trgm` (공개 검색) | 39 MB | 4,763 | 5,080,114 | 1,067 |
| `idx_features_sigungu` | 7 MB | **309,210** | 7,640,239 | 25 |
| `idx_features_admin_address_trgm` | 166 MB | 12 | 0 | — |
| `idx_features_admin_feature_id_trgm` | 75 MB | 12 | 0 | — |
| `idx_features_updated_keyset` | 72 MB | 0 | 0 | — |
| `idx_features_admin_updated_keyset` | 70 MB | 0 | 0 | — |
| `idx_features_admin_lower_name_trgm` | 46 MB | 12 | 45 | — |
| `idx_features_admin_created_keyset` | 43 MB | 0 | 0 | — |
| `idx_features_admin_lower_name_keyset` | 38 MB | 12 | 159,453 | — |
| `idx_features_lower_name_keyset` | 37 MB | 0 | 0 | — |

탐색 12회 이하인 색인이 574 MB다 — 위 표의 여덟 개 547 MB에 `idx_features_coord_5179_gist`(27 MB, 탐색
5회 — 반경 검색용이라 정리 대상이 아니다)를 더한 값이다. 0회인 색인은 222 MB다. 통계 창이 3.6일
이하이고 관리 화면 사용이 적었을 수 있으므로 "쓰이지 않는다"의 증거로는 약하다(`T-READ-07`이 창을
늘려 다시 센다).

### 4.2 PinVi가 본 지연 (PinVi `/metrics`, 프로세스 기동 2026-11-16 13:06Z → 2026-11-17 03:44Z)

| route (status) | 건수 | 평균 | 분포 |
| --- | --- | --- | --- |
| `GET /features/in-bounds` (200) | 20 | 0.74초 | ≤0.1초 0건, ≤0.5초 14건, ≤1초 16건, ≤2.5초 19건, ≤5초 20건 |
| `GET /features/in-bounds` (503) | **15** | 3.99초 | — (그 밖에 401이 3건) |
| `GET /trips/{trip_id}` (200) | 27 | **8.98초** | 중앙값 ≤2.5초, 상위 10%는 10초 초과 |
| `GET /weather/markers-in-bounds` (200) | 6 | 6.53초 | — |
| `GET /features/{feature_id}/weather` (200) | 2 | 2.92초 | — |
| `GET /transport/markers-in-bounds` (200) | 6 | 0.16초 | — |
| `GET /transport/status` (전체 status) | 11 | 0.60초 | — |
| `GET /auth/oauth/providers` (200) | 25 | 1.63초 | 중앙값 ≤0.5초, 상위 10%는 ≤5초 |

- 건수가 적고 e2e·배포 창이다. 정상 상태의 분포로 읽으면 안 된다. histogram 상한이 10초라 그 위는 구분되지 않는다.
- `/auth/oauth/providers` 핸들러 본문은 설정만 읽는다(`PIN:app/api/v1/oauth.py:142-150`). 다만 이 route는
  rate-limit 대상이라(`PIN:app/middleware/rate_limit.py:76-78`) 요청마다 PostgreSQL upsert와 COMMIT을
  한다. 지표 미들웨어가 그 바깥이므로(`PIN:app/main.py:97-101`) 1.63초에는 그 COMMIT이 들어 있다(F-13).
- `/search`·`/transport/markers-near`는 이 창에 호출이 없었다. 동시 호출 상한 거부 counter
  (`pinvi_api_outbound_bulkhead_rejections_total`)에도 표본이 없었다.
- PinVi DB pool 대기는 84,758회 합계 5.7초다 — PinVi 쪽 pool은 원인이 아니다.
- **`/weather/markers-in-bounds`는 운영에서 상류를 부르지 않는다.** [실측] 운영 env에
  `PINVI_KOR_TRAVEL_WEATHER_MAP_MARKERS_ENABLED`가 없다. [추론] 기본값은 꺼짐이고 그때 handler는 빈
  목록을 바로 돌려준다(`PIN:app/api/v1/weather_markers.py:66-67`). 그런데 200 응답 6건이 평균 6.53초였다 —
  그 시간은 전부 미들웨어·의존성에서 나왔다(F-13).

PinVi `app.api_call_log`의 planner 통계(읽기 전용 카탈로그 조회, 2026-11-17 05:14Z. 표본 통계이지 전수
집계가 아니다 — 마지막 autoanalyze 2026-11-16 05:28Z).

| 항목 | 값 |
| --- | --- |
| 크기 | 약 131,240행, 41 MB, 가장 이른 행 2026-09-26 |
| provider | `kor_travel_map` 73.0%, `kor_travel_weather` 14.6%, `kor_travel_geo` 9.9% |
| status | 200 99.0%, 403 0.42%, 404 0.09%, 응답 없음(NULL) 0.43%. 5xx는 상위 값에 없다 |
| 오류 종류 | 없음 99.2%, `HTTPStatusError` 0.34%, `ReadTimeout` 0.22%, `CancelledError` 0.19%, `ConnectError` 0.01% |
| 관련 표 | `app.rate_limit_buckets` 15행 — 갱신 25,958건 중 HOT 4건, logged 표. `app.location_audit_outbox` 184행 |

### 4.3 odroid (2026-11-17 03:38~03:46Z)

| 항목 | 값 | 방법 |
| --- | --- | --- |
| 부하 | load 11.2·11.6·12.8(4코어), `vmstat` 4초: 실행 대기 11~27, user 85~88%·sys 12~15%, **idle 0%, iowait 0%** | `uptime`, `vmstat 1 4` |
| CPU를 쓰는 쪽 | Dagster run 작업 프로세스(`multiprocessing.spawn`) 4개가 29~55%씩, daemon liveness-check, code server | `ps --sort=-pcpu` 한 번 |
| 메모리 | 7,675 MB 중 free 70 MB·buff/cache 3,226 MB, swap 1,843 MB 사용 | `free -m` |
| 저장소 | NVMe 데이터 파일시스템 938 GB 중 889 GB 사용, **남은 공간 1.9 GB**. 공용 PG의 데이터 디렉터리가 여기 있다. 루트 eMMC는 58 GB 중 11 GB 사용 | `df -h`, `docker inspect`(mount) |
| weather artifact | docker named volume — 루트 eMMC 위에 있다 | `docker inspect` |
| 프로세스 | weather API uvicorn 1개 RSS 726 MB, transport backend uvicorn 1개 RSS 405 MB(compose 한도 512 MB — `TRN:docker-compose.shared.yml:216`) | `docker top` |
| n150 → weather `/health` | 336 ms·133 ms·9 ms(TCP 연결 187·114·1.6 ms) | curl 3회 |
| n150 → weather `/v1/weather/locations?limit=1` | 371 ms(`x-duration-ms` 176) | curl 1회 |

### 4.4 문서가 적어 둔 수치(다시 재지 않았다)

- Map 검색(소유자 2026-11-16): 일반 55~280 ms, 지역 경로 "부산 맛집" 0.6~1.1초(부하 없음).
- Map 저배율 집계(#1455, 2026-11-07): zoom 7 PinVi 기본 kind 2.9→0.25초, route·area 12~15→1.0~1.3초.
  "22초짜리 느린 요청 중에도 작은 요청은 0.010초"(`MAP:docs/journal.md:441-445`).
- Map 지역 검색(2026-11-09, 순위 2·3단계 이전): "부산 맛집" 0.16초, "경기 관광" 1.3초, "서울 맛집"
  5~6초(`repo:2700-2703`). 뒤의 두 값은 **지역 행 수 문턱 3만(`repo:2703`)을 넣게 만든 측정**이다 — 문턱이
  생긴 뒤의 수치가 아니다.
- weather export: current 첫 페이지 52.4초·304 재사용 173 ms
  (`WEA:docs/design/weather-performance-use-cases-20261109.md:51-55`).
- PinVi 주석: weather `/markers` p50 2.2초·p95 3.7초(`PIN:app/services/weather_markers_cache.py:3`,
  재확인 안 함).

## 5. 발견

각 항목: 근거 → 영향 → 확신도.

### F-01 측정 창에서는 디스크 대기가 모든 요청에 깔려 있었다

- [실측] PSI io `full` avg10 63%(03:31Z) — 10초 중 6초 넘게 **모든** 작업이 디스크를 기다렸다. 한 시간 뒤
  (04:32Z)에는 `some` avg300이 85%였다(§4.1).
- [실측] 공용 PG는 `shared_buffers` 1 GB로 Map DB 9.5 GB와 다른 tenant를 받고, 3.6일 동안 버퍼를
  1,060만 번 내보냈다. 같은 기간 컨테이너가 166 GB를 썼다(하루 약 46 GB).
- [실측] checkpointer가 버퍼 하나를 쓰는 데 평균 약 48 ms가 걸렸다(§4.1) — 쓰기가 디스크에서 밀렸다는
  직접 증거다. 누가 쓰는지는 F-15다.
- [실측] PinVi `/auth/oauth/providers`가 평균 1.63초였다(25건, 중앙값은 0.5초 이하). 이 요청이 하는 I/O는
  rate-limit upsert와 COMMIT 하나뿐이다(§4.2). [추론] 작은 COMMIT 하나가 초 단위로 걸렸다는 것은 공용
  PG의 WAL flush가 밀렸다는 것과 맞는다 — "I/O 없는 요청도 느렸다"의 증거는 아니다.
- 영향: 이 조건에서는 어떤 SQL 개선도 묻힌다. 조용할 때의 수치(§4.4)와 측정 창의 수치(§4.2)가
  10배 이상 벌어진다.
- 확신도: "측정 창에 디스크 압력이 높았다"는 높다(실측). "그것이 PinVi 지연의 주원인이다"는 중간이다
  (rate-limit 구간만 따로 잰 지표가 없다). "평소에도 그렇다"는 모른다 — 2026-11-16 e2e 때도 같은
  현상이 보고됐다는 것이 전부다.

### F-02 Map API 프로세스가 swap에 나가 있다

- [실측] VmRSS 14 MB, VmSwap 154 MB(§4.1). 같은 시각 PinVi API는 149 MB·15 MB였다. Map API 로그의
  최근 400줄은 `/health`뿐이었다 — 한가한 사이에 밀려났다.
- [추론] 다음 실제 요청은 필요한 페이지를 같은 디스크에서 다시 읽어야 한다. 디스크가 밀려 있으면
  요청 하나가 수백 ms~수 초 늦는다. "배포 직후·한가한 뒤 첫 요청이 느리다"의 한 원인일 수 있다.
- [실측] Map API 컨테이너에는 메모리 한도가 없다(`HostConfig.Memory` 0). PinVi API는 확인하지 않았다.
  transport는 `memswap_limit = mem_limit`로 swap을 막아 두었다(`TRN:docker-compose.shared.yml:216-217`).
- 영향: 간헐적 꼬리 지연. 크기는 재지 못했다.
- 확신도: 상태는 실측, 지연 기여는 추론(중간).

### F-03 읽기 지연을 볼 수단이 운영에 없다

- [실측] Map API 지표가 꺼져 있다. 코드 기본값은 켜짐이다(`MAP:api/settings.py:477-478`) — 운영 env가
  끈다. 지표 코드는 route별 요청 시간·DB 질의 시간을 이미 낸다(`MAP:api/prometheus.py:98-140`,
  `MAP:api/db.py:150-210`).
- [실측] 호출 로그는 기본 꺼짐이고(`MAP:api/settings.py:471-472`) 운영 env에 켜는 변수가 없다. uvicorn
  access log에는 시간이 없다.
- [실측] `log_min_duration_statement` -1, `pg_stat_statements` 확장 없음, `track_io_timing` off.
  `MAP:docs/architecture/performance.md:810-813`은 둘 다 켠다고 적는다 — 문서와 운영이 다르다.
- [추론] transport에는 앱 지표가 아예 없다(§3.5). weather는 지표가 있으나 histogram 상한이 30초라 cold
  export가 `+Inf`에 들고, route template만 label이라 첫 페이지·cursor 페이지·304가 섞인다
  (`WEA:SRC/metrics.py:270-274`).
- [추론] 예외가 하나 있다 — PinVi의 `app.api_call_log`가 Map 호출마다 URL·status·시간을 남긴다(§3.3,
  §4.2). Map 쪽 지표 없이도 경로별 지연과 실패의 종류를 몇 주 치로 볼 수 있다. 이 계획은 그것을 아직
  집계하지 못했다(`T-READ-PIN-06`).
- 영향: 다음 느려짐도 "어느 질의가, 언제부터"를 답하지 못한다. 이 문서의 F-04·F-07·F-08이 시간을
  못 적는 이유가 이것이다.
- 확신도: 높다.

### F-04 in-bounds는 실패율이 높았고, 그 부하가 무엇인지는 모른다

- [실측] bbox GiST 탐색 5,166회가 색인 행 6.05억 개를 읽었다 — 탐색당 11.7만. 공개 행은 약 39.7만
  (planner 추정)이므로 평균적인 탐색이 전국의 30%를 읽는다. heap에서 가져온 행도 5.7억이다.
- [추론] zoom ≤13이면 집계 경로다. bbox 안 공개 행을 **전부** 읽어 `GROUP BY` 한다(`repo:1683-1766`).
- 이 평균을 만드는 후보는 둘이고 **어느 쪽인지 모른다.**
  - 저배율(zoom ≤ 10) 전국·광역 집계.
  - **PinVi 기본 화면.** 서울시청 zoom 12는 읍면동 집계이고(§3.3) 그 화면은 서울 전체를 덮는다. [실측]
    통계상 서울(`sido_code` 11)이 Feature의 31.9%다 — 공개 행 약 12.7만으로, 탐색당 평균 11.7만과 같은
    크기다. 기본 화면만으로도 이 평균이 나올 수 있다.
  - 같은 색인을 관리·ops·공개 뷰 질의도 타고 통계 창에 e2e가 들어 있다.
  - `T-READ-PIN-06`이 `app.api_call_log`의 `zoom` 분포로 가른다.
- [실측] PinVi `GET /features/in-bounds` 38건 중 15건이 503(평균 3.99초)이었다. 200인 20건은 평균
  0.74초이고 0.1초 안에 끝난 것이 없다.
- [문서 주장] 조용할 때 전국 zoom 7 집계는 0.25초다(§4.4). 서울 zoom 12 읍면동 집계의 수치는 없다.
- 영향: 지도 첫 화면과 축소 화면. 디스크가 밀리면 5초 timeout → 503 → 연속 3번이면 PinVi 회로가
  120초 열려 viewport 범위 전체(주변·해수욕장·축제 마커 포함)가 멎는다(§3.3).
- 확신도: 탐색당 행 수와 실패율은 실측이다. 부하의 정체와 503의 원인(Map 지연 / 배포 중 재기동 / PinVi의
  상한·회로)은 모른다([실측] Map 로그의 최근 20,000줄에 5xx는 없었다. [실측] `api_call_log` 통계 표본에도
  5xx는 드물고 `ReadTimeout`이 0.22%다 — Map이 5xx를 낸 것이 아니라 PinVi가 끊었거나 보내지 않았을
  가능성이 높다).
- 사전 집계(T-101)는 소유자가 2026-09-07에 제외했다. 이 계획은 그것을 다시 열지 않는다(§7).

### F-05 읽기 요청에 시간 상한이 없고 PinVi는 5xx를 세 번 다시 보낸다

- [추론] API 엔진은 `jit=off`만 걸고 `statement_timeout`을 걸지 않는다(`MAP:api/db.py:57-62`). 저장소에
  `statement_timeout`을 거는 곳은 여럿 있다 — ADR-112의 마감 예산(`MAP:src/kortravelmap/infra/
  transaction_limits.py`: 남은 시간 − 3초를 transaction마다 `set_config`), 삭제 배치
  (`src/kortravelmap/client/__init__.py:754-814`), lock 대기(`infra/lock_wait.py`), 검색 인지도 refresh
  (`infra/search_prominence_repo.py:214`), cache-target reconciliation
  (`infra/cache_target_reconciliation_repo.py:319`). **공개 읽기 handler에 걸리는 것은 없다** —
  `apply_transaction_limits`는 마감이 없으면 아무것도 보내지 않고(`transaction_limits.py:120-146`)
  호출자는 client 계층뿐이다.
- [추론] 문장 상한은 **문장마다** 따로 센다. 검색 한 번은 문장이 7~8개다(`SET LOCAL` 둘, 별칭, 지역
  표본, 지역 행 수, 본 질의, 선택 개수 — `repo:7782-7849`). 문장당 4.5초로는 요청이 5초 안에 끝난다는
  보장이 없다. 요청 마감에서 남은 시간을 문장에 넘겨야 한다.
- [추론] PinVi는 단계별 5초에 끊는다. 핸들러는 연결이 끊겨도 취소되지 않으므로(코드에 disconnect 확인이
  없다 — 실행해 확인하지는 않았고 `T-READ-03`의 시험이 확인한다) SQL은 끝까지 돈다.
- [추론] PinVi는 `ReadTimeout`은 다시 보내지 않지만 **5xx는 세 번까지 다시 보낸다**(§3.3). 지금도 Map의
  503 `LOCK_TIMEOUT`(`MAP:api/app.py:1066-1085`)·`FEATURE_BATCH_UNAVAILABLE`은 그렇게 재시도된다. Map이
  느린 읽기를 503으로 바꾸기만 하면 멈춘 요청 하나가 무거운 질의 세 번(약 4.5+0.2+4.5+0.4+4.5초)이 된다.
- [추론] Map pool은 15개, 대기 상한은 SQLAlchemy 기본 30초다. API 엔진은 하나라(`MAP:api/db.py:46-71`)
  `pool_timeout`을 줄이면 admin·ops·쓰기까지 같이 걸린다. PinVi의 PG를 쓰는 범위 상한 합은 features 10 +
  viewport 4 + festivals 4 = 18이다. 느린 질의가 15개를 쥐면 다음 요청은 PinVi가 이미 떠난 뒤까지
  줄을 선다.
- 영향: 정지 구간에서 버려진 작업이 쌓여 회복을 늦춘다.
- 확신도: 설정은 높다. 운영에서 실제로 쌓였는지는 지표가 없어 모른다.

### F-06 PinVi의 교통·날씨 조회는 호출 수가 동시 호출 상한을 넘는다

- [추론] `transport`와 `weather` 범위의 상한은 각각 2이고 대기열이 없다 — 꽉 차면 호출하지 않고
  `BULKHEAD_FULL`을 올린다(`PIN:app/clients/kor_travel_map.py:481-488`, `app/core/config.py:827-828`).
- **교통** [추론]: wrapper가 `transport` 범위를 쓴다(`PIN:app/clients/kor_travel_map_transport.py:116`).
  반경 조회는 레이어마다 중심들을 동시 6개까지 보내고(`transport_layers.py:216,249-263`) 하나라도 실패하면
  레이어 전체가 `unavailable`이다(`transport_layers.py:306-312`). 두 레이어를 켠 여행(웹은
  `fuel_station`·`highway_incident`를 함께 보낸다)에서 2 km 넘게 떨어진 장소가 2곳 이상이면 동시 호출이
  4개 이상이다. 레이어가 하나면 3곳 이상부터다.
- **날씨** [추론]: 여행 보기는 캐시에 없는 위치를 동시 4개로 해석한다(`weather_map_resolver.py:72`).
  해석 하나는 `/nearest`를 반경 20·50·100 km로 최대 세 번 차례로 부르고 `/locations?near`를 한 번 부른다
  (`weather_map_resolver.py:132-160`). 값 묶음도 동시 4개다(`weather_map_state.py:596`). 모두 상한 2인
  `weather` 범위다. 거부는 즉시 돌아오므로 다음 위치가 곧바로 여전히 찬 상한에 들어간다 — 처음 여는
  여행에서는 앞의 둘을 뺀 위치 대부분이 `unavailable`이 되고, 저장되지 않으므로 다음에도 같다.
- 상한은 PinVi 프로세스 전체가 나눠 쓰므로 다른 사용자의 요청과 겹쳐도 같은 일이 난다.
- [추론] 두 상한은 env 설정이다(범위 1~64). 두 범위는 Map에서 Valkey 읽기라([실측] 명령당 45~77 µs)
  상한을 둔 이유(#621 — 느린 표면이 자리를 차지하는 것)가 거의 해당하지 않는다.
- 시험은 한 점 또는 가짜 client만 쓴다(`PIN:apps/api/tests/integration/test_transport_api.py:228-282`,
  `tests/unit/test_transport_layers.py:304-393`).
- [실측] 교통 반경 route는 측정 창에 호출이 없어 운영에서 확인하지 못했다. 상한 거부 counter에도 표본이
  없었다.
- 영향: 여행 지도의 주유소·돌발 레이어와 여행 보기의 날씨 카드가 비거나, 장소가 많으면 Map 호출이 최대
  120번이다.
- 확신도: 중간~높음(코드상 분명하나 실행해 보지 않았다). 첫 작업이 재현 시험이다(`T-READ-PIN-01`).

### F-07 낱말이 둘 이상인 검색마다 전처리 질의 두 개가 붙는다

- [추론] 낱말이 둘 이상이면 지역 표본 질의가 돈다 — 시군구 코드마다 색인 탐색으로 주소 이름 최대
  8행을 읽는 재귀 질의다(`repo:7584-7597`, `repo:2720-2755`). 지역으로 해석되면 지역 공개 행 수도 센다
  (`repo:7639-7653`, `repo:2706-2713`).
- [실측] `idx_features_sigungu` 탐색이 309,210회다. [추론] 재귀 질의 한 번이 코드 수(통계상 285)의
  두 배쯤 탐색하므로 검색 약 500번이면 이 수가 된다. 본 질의의 지역 팔과 행 수 세기도 이 색인을 타지만
  요청당 한두 번이다.
- [추론] 주소 JSON은 heap에 있어 검색 한 번에 heap 행을 최대 2,280개 읽는다. all-visible이 58%라 행 수
  세기도 heap을 본다. 표본은 `ORDER BY` 없는 `LIMIT 8`이라(`repo:2752` 부근) 같은 DB에서도 계획이
  바뀌면 다른 행을 고를 수 있다.
- 영향: 따뜻할 때는 작다(추정 수 ms). 디스크가 밀릴 때는 무작위 읽기 수천 번이 된다. 실제 시간은
  재지 못했다.
- 확신도: 구조는 높다, 이득 크기는 낮다(`T-READ-01`이 잰다).

### F-08 검색 순위는 후보 전부를 무거운 단계에 통과시킨다

- [추론] trigram 유사도 0.2 이상인 행·별칭·끝 괄호·지역 팔의 후보를 모두 모은 뒤
  (`repo:2327-2360`), 행마다 이름을 정규화해 비교 키 여섯 개를 만들고(`repo:2373-2400`), 접기 키별
  `ST_ClusterDBSCAN`과 창 함수 세 번을 돈다(`repo:2515-2580`). 페이지 크기와 무관하게 후보 수에 비례한다.
- [실측] trigram 색인 탐색당 평균 1,067행이다. 지역 분류 팔이 붙으면 지역 행 수(상한 3만)만큼 는다.
- [문서 주장] "부산 맛집"이 2026-11-09에 0.16초였고(순위 2·3단계 이전), 2026-11-16에 0.6~1.1초다.
  2·3단계(2026-11-12)가 그 사이에 들어갔다.
- 영향: PinVi 통합 검색은 입력마다 Map을 부르고 캐시가 없다(§3.3). 상한은 5초다. 검색 한 번의 전체
  시간에는 geo와 외부 검색도 든다(F-17).
- 확신도: 구조는 높다. 어느 단계가 시간을 쓰는지는 `EXPLAIN ANALYZE` 없이는 모른다.

### F-09 odroid는 측정 시점에 CPU가 포화였다

- [실측] §4.3 — idle 0%, 실행 대기 11~27. 쓰는 쪽은 Dagster run 작업이다. iowait는 0%다(n150과 반대).
- [실측] 그 시각 n150 → weather `/health`의 TCP 연결에 114~187 ms가 걸린 표본이 있다.
- 영향: odroid의 읽기(export·특보·관리 화면)는 수집과 같은 4코어를 다툰다. weather export의 cold
  구성(§4.4)과 Map 적재의 timeout(§3.4)이 여기서 길어진다.
- 확신도: 한 시점의 표본이다(중간). 지속 여부는 cAdvisor·node-exporter 기록을 봐야 한다.

### F-10 odroid NVMe에 남은 공간이 1.9 GB다 (가용성)

- [실측] §4.3. 공용 PG의 데이터 디렉터리가 그 파일시스템에 있다.
- 영향: WAL·임시 파일·테이블 증가로 가득 차면 PG가 멎는다 — weather·transport·geo의 모든 읽기가
  함께 멎는다. 읽기 속도 문제가 아니라 그 전제다.
- 확신도: 높다. 무엇이 공간을 쓰는지는 보지 않았다(다른 팀 호스트). 2026-11-17에 소유자에게 전달됐다.
  운영 작업은 `T-READ-MGR-05`다.

### F-11 `feature.features`의 색인이 heap의 두 배이고 HOT 갱신이 0이다

- [실측] heap 379 MB, 색인 720 MB. 갱신 58,813건 중 HOT 0건. 거의 안 쓰인 색인 574 MB(§4.1).
- [추론] `updated_at`이 색인 두 개의 키라서 갱신이 `updated_at`을 바꾸는 한 HOT가 될 수 없다. 갱신마다
  색인 18개에 새 항목이 생긴다. 그중 `idx_features_updated_keyset`(72 MB, 탐색 0회)은 prewarm 목록에도
  들어 있다(`MAP:src/kortravelmap/infra/prewarm.py:33-41`).
- 영향: 적재가 쓰는 I/O와 버퍼 압력이 읽기와 같은 1 GB를 다툰다(F-01). 직접 지연이 아니라 간접이다.
- 확신도: 수치는 실측, "지워도 된다"는 낮다(통계 창이 짧다).

### F-12 그 밖에 확인한 것(작업으로 올리지 않는다)

- 지도 행마다 도는 장소 속성 하위 질의(`repo:1432-1457`)는 행당 색인 탐색 몇 번이다. 500행 페이지에서
  큰 비용으로 보이지 않는다 — `T-READ-01`의 계획에서 다시 본다.
- 공개 뷰의 subtype LEFT JOIN 6개는 쓰지 않는 열이면 planner가 지운다. subtype PK 탐색이 종류와 무관하게
  89만~174만 회인 것은 상세·geometry를 조립하는 경로가 있다는 뜻인데, 읽기인지 적재인지 가르지
  못했다(`pg_stat_statements`가 필요하다).
- Map Valkey 읽기는 µs 단위다. 교통·날씨 표면의 지연은 Valkey가 아니라 호출 수(F-06)와 호스트(F-01)다.
- Map API는 gzip을 하지 않는다. PinVi와 같은 호스트(loopback)라 지금은 이득이 작다.

### F-13 PinVi는 요청마다 쓰기와 조회를 먼저 하고, 측정 창에서 그것이 초 단위였다

- [추론] 우회 경로와 `OPTIONS`가 아닌 모든 요청이 handler보다 먼저 `app.rate_limit_buckets`에 upsert하고
  COMMIT한다(`PIN:app/middleware/rate_limit.py:203-237,270-317`). 별도 세션이라 pool 연결도 한 번 더 쓴다.
- [실측] 운영은 `PINVI_ENVIRONMENT=production`이고 backend 설정을 바꾸는 env가 없다 — `auto`는 운영에서
  PostgreSQL이다(`rate_limit.py:392-397`). [실측] 그 표는 logged 표이고, 갱신 25,958건 중 HOT가 4건이다 —
  갱신마다 heap과 색인과 WAL을 쓴다.
- [추론] 인증된 route는 사용자를 조회한다(`PIN:app/core/deps.py:79-85`). 좌표를 받는 route는 handler 뒤에
  위치 감사 outbox에 INSERT하고 COMMIT한다(`PIN:app/middleware/location_audit.py:129-140`).
- [실측] **상류를 부르지 않는 route 둘이 느렸다.** `/auth/oauth/providers`(rate-limit COMMIT만) 평균 1.63초,
  `/weather/markers-in-bounds`(운영에서는 빈 목록을 바로 돌려준다 — §4.2) 평균 6.53초. 뒤의 것은 rate-limit
  COMMIT + 사용자 조회 + 위치 감사 COMMIT을 모두 거친다.
- 영향: in-bounds·검색·여행 보기를 포함한 모든 PinVi 읽기가 이 비용을 먼저 낸다. n150처럼 디스크가
  밀리는 호스트에서는 읽기 지연의 바닥이 된다. Map을 아무리 고쳐도 이 바닥은 남는다.
- 확신도: 구조는 높다. "상류 없는 route가 초 단위였다"는 실측(표본 6건·25건). 세 구간 가운데 무엇이
  얼마를 쓰는지는 재지 못했다 — `T-READ-PIN-05`가 먼저 잰다. PinVi의 이벤트 루프가 다른 일로 막혀
  있었을 가능성도 배제하지 못했다.

### F-14 `feature.features`는 autovacuum이 돌지 않아 visibility map이 낡았다

- [실측] 이 표는 통계 창(3.6일 이하) 동안 autovacuum이 0회였다. dead 6.3만 행, all-visible page 58%(§4.1).
- [추론] 표에 reloptions가 없다(`MAP:alembic/head-schema.sql:16371`). 기본 문턱은 50 + 20% dead — 약
  8.8만 행이다. dead가 그 아래에 머무는 한 돌지 않는다.
- [추론] all-visible이 아닌 page에서는 index-only scan이 heap을 읽는다. 지역 행 수 질의는 "index-only
  count"로 설계됐고(`repo:2705`) 집계·bbox 탐색도 같은 영향을 받는다.
- [추론] HOT 갱신은 page에 빈 자리가 있어야 한다. 표는 fillfactor 100이라 `updated_at` 색인을 지워도
  (F-11) 꽉 찬 page에서는 HOT가 나오지 않는다.
- 영향: 읽기마다 불필요한 heap 접근 — 디스크가 밀릴 때 커진다. 크기는 재지 못했다.
- 확신도: 통계는 실측, 영향 크기는 낮음(`T-READ-08`이 `Heap Fetches`로 잰다).

### F-15 디스크에 누가 쓰는지 가려지지 않았다

- [실측, 약 46시간 창] checkpoint는 552회 모두 시간 주기(5분)였다. checkpointer가 9.4 GB, bgwriter가
  9.5 GB, backend가 약 2.7 GB, autovacuum이 약 3.2 GB를 썼고 WAL이 17 GB였다 — 합쳐 하루 약 22 GB다.
  같은 컨테이너의 블록 쓰기는 하루 약 46 GB였다(§4.1). 차이는 가르지 못했다.
- [실측] 설정은 `checkpoint_timeout` 5분, `max_wal_size` 2 GB, `wal_compression` off다. [추론] 5분
  주기는 full-page write를 가장 자주 일으킨다. WAL 레코드 2,560만 건 중 FPI가 267만 건이다.
- [실측] Map Valkey는 `save 900 1`인데 약 304초마다 fork했다. `900 1`만으로는 최대 931번인데 2,757번이다.
  `SAVE`·`BGSAVE` 명령은 기록에 없다. 원인은 모른다. 컨테이너 쓰기는 9.7일에 53.8 GB다.
- [실측] 어느 tenant DB가, 어느 문장이 쓰는지는 볼 수 없다(`pg_stat_statements` 없음).
- 영향: F-01의 디스크 압력은 읽기가 아니라 쓰기가 만든다. 쓰는 쪽을 모르면 줄일 수 없다.
- 확신도: 수치는 실측, 원인 배분은 모른다(`T-READ-MGR-06`).

### F-16 여행 보기 평균 9초의 구성은 모른다 — 날씨의 몫은 많아야 1.5초다

- [실측] `GET /trips/{trip_id}` 200 응답 27건이 평균 8.98초였다(§4.2).
- [추론] 날씨는 해석을 포함해 1.5초 예산에 묶여 있다(`PIN:app/core/config.py:973-975`,
  `trip_weather_batch.py:506-561`). Feature batch는 5초 timeout에 5xx 재시도 세 번이면 약 15.6초까지 간다.
  그 앞에 DB 질의 5~6개가 순서대로 돌고(`trip_view_builder.py:100-170`) 요청당 비용(F-13)이 붙는다.
- 영향: "Feature와 날씨를 함께 기다리기"로 줄일 수 있는 시간은 최대 약 1.5초다. 9초의 대부분은 다른 곳이다.
- 확신도: 예산은 코드, 구성은 모른다(`T-READ-PIN-06`의 request id 묶음과 `T-READ-PIN-03` ①의 단계별
  지표가 가른다).

### F-17 PinVi 통합 검색은 Map 말고도 세 곳을 부른다

- [추론] Map 검색과 geo 주소 검색(odroid, 3초 예산)을 함께 기다린다(`PIN:app/api/v1/search.py:53,234`).
  odroid는 측정 시점에 CPU가 포화였다(F-09). 그 뒤 내 POI DB 질의, 그리고 내부 결과가 문턱 아래면 Kakao를
  부르고 **이어서** Naver를 부른다(`search.py:244-290`).
- 영향: 검색 한 번의 시간 = max(Map, geo ≤ 3초) + DB + (Kakao + Naver). Map의 검색을 고쳐도 뒤의 두
  항이 남는다.
- 확신도: 구조는 높다. 각 항의 실제 시간은 `app.api_call_log`에 있다(`T-READ-PIN-06`).

## 6. 개선안과 순위

이득·노력·위험은 상대값이다. "이득"은 근거가 실측인 것을 위에 둔다. 리뷰 2회차에서 순위를 다시 매겼다 —
PinVi의 요청당 비용과 동시 호출 상한이 위로, PinVi 집계 캐시와 여행 보기 병렬 대기가 아래로 갔다.

| 순위 | 안 | 이득 | 노력 | 위험 | 작업 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이미 있는 PinVi 호출 기록을 집계한다 | 직접 이득 0. F-04·F-06·F-16·F-17의 "모른다"를 배포 없이 푼다 | 작음 | 낮음(집계만 낸다) | `T-READ-PIN-06` |
| 2 | PinVi 요청당 비용(rate-limit COMMIT·사용자 조회·위치 감사)을 재고 줄인다 | 상류 없는 route가 1.6~6.5초였다(실측) — 모든 PinVi 읽기의 바닥 | 작음 | 낮음~중간 | `T-READ-PIN-05` |
| 3 | 교통·날씨 동시 호출 상한을 팬아웃에 맞춘다(env 두 값이 가장 싸다) | 레이어·날씨 카드의 `unavailable` 제거(코드 추론) | 매우 작음 | 낮음 | `T-READ-PIN-01` ②, `T-READ-MGR-07` |
| 4 | 운영 관측 켜기 — Map 느린 요청 로그·지표, PG 느린 질의 로그·`pg_stat_statements`, scrape | 나머지 전부의 전제 | 작음~중간(PG 재생성 창) | 낮음 | `T-READ-02`, `T-READ-MGR-01`·`02`·`03`, `T-READ-TRN-01`, `T-READ-WEA-01` |
| 5 | 기준선과 재측정 도구 | 전제 | 작음 | 낮음(읽기 전용) | `T-READ-01` |
| 6 | odroid NVMe 공간 확보 | 장애 예방 | 운영 | 낮음 | `T-READ-MGR-05` |
| 7 | API 프로세스를 swap에서 지키기 | 꼬리 지연(크기 미측정) | 작음 | 중간(한도가 작으면 OOM) | `T-READ-MGR-03` |
| 8 | `feature.features` autovacuum 문턱을 표에 맞추기 | heap 접근 감소(크기 미측정), migration 한 줄 | 작음 | 낮음 | `T-READ-08` |
| 9 | 디스크에 쓰는 쪽을 가려 checkpoint·WAL·Valkey 저장을 조정 | F-01의 원인 쪽 | 중간(PG 재생성 창) | 중간 | `T-READ-MGR-06` |
| 10 | PinVi가 Map의 시간 초과 503을 다시 보내지 않게 하고, 그 뒤 Map 공개 읽기에 요청 마감을 건다 | 정지 구간의 누적 방지 | 중간 | 중간(순서를 어기면 부하가 3배) | `T-READ-PIN-04` → `T-READ-03` |
| 11 | 교통 근처 조회를 한 번에(여러 점) | Map 호출 최대 120 → 2 | 중간 | 중간(Map+PinVi 한 회전) | `T-READ-04` + `T-READ-PIN-01` ③ |
| 12 | 공용 PG 메모리·I/O 설정 재산정(n150) | 버퍼 교체 감소(F-01) | 중간(전 tenant 재생성) | 중간 | `T-READ-MGR-04` |
| 13 | PinVi 통합 검색의 Kakao·Naver를 함께 기다리기 | 외부 호출 구간이 절반(해당 검색에서만) | 작음 | 낮음 | `T-READ-PIN-07` |
| 14 | PinVi 집계 응답의 짧은 캐시 | **zoom ≤ 10의 반복 요청만** — 기본 화면(zoom 12)에는 거의 듣지 않는다 | 작음 | 낮음 | `T-READ-PIN-02` |
| 15 | PinVi 여행 보기에서 Feature와 날씨를 함께 기다리기 | **최대 약 1.5초**(날씨 예산) — 평균 9초의 대부분은 다른 곳이다 | 중간 | 중간(세션 분리) | `T-READ-PIN-03` |
| 16 | 지역 검색 전처리를 작은 표 조회로 | 검색당 색인 탐색 약 570회·heap 최대 2,280행 제거(`T-READ-08` 뒤에는 더 작다) | 중간(migration) | 낮음 | `T-READ-05` |
| 17 | 검색 비교 키 사전 계산 | 지역 경로 0.6~1.1초의 일부(측정 뒤 확정) | 큼 | 중간 | `T-READ-06` |
| 18 | `features` 색인 정리·fillfactor·HOT 회복 | 적재 I/O 감소 → 간접 | 중간 | 중간 | `T-READ-07` |
| 19 | weather·transport 내부 개선 | odroid 부하·Map 적재 신선도 | 저장소별 | 저장소별 | `T-READ-WEA-*`, `T-READ-TRN-*` |

서비스 사이에 걸친 것.

- **배포 순서**: Map의 OpenAPI가 바뀌면 PinVi의 재vendor가 머지된 뒤 한 번의 pair 회전으로 나간다(§8.1).
  `T-READ-04`만 해당한다. `T-READ-03`은 spec을 바꾸지 않는다.
- **시간 상한과 재시도는 한 묶음이다.** Map의 요청 마감(기본 4.5초)은 PinVi의 읽기 timeout 5초보다 짧아야
  하고, PinVi는 그 503(`READ_TIMEOUT`·`POOL_BUSY`)을 다시 보내지 않아야 한다. PinVi가 먼저다. 공개 월별
  축제는 PinVi가 15초를 기다리므로 Map 쪽도 따로 14초를 준다.
- **묶음 조회**: 교통 근처(`T-READ-04`). 날씨는 이미 묶음이다(`/locations/batch`).
- **캐시 헤더**: Map은 데이터 캐시를 두지 않는다(ADR-030). 호출자 캐시는 허용된다
  (`MAP:docs/architecture/performance.md:544-545`). Map이 집계 응답에 ETag를 달려면 값싼 데이터 버전이
  필요한데 지금은 없다(§7).
- **관측**: 세 서비스 모두 `route·status·시간`을 같은 Prometheus에 모은다(`T-READ-MGR-02`). 그 전에는
  PinVi의 호출 기록이 유일한 다주 단위 자료다.

## 7. 하지 않는 것·기각한 안

| 안 | 판단 | 이유 |
| --- | --- | --- |
| 저배율 집계 materialized view(T-101) | 다시 열지 않는다 | 소유자가 2026-09-07 제외했다. 재개 조건은 목표 SLO와 exact-viewport vs region-total 택일이다(`MAP:docs/tasks.md:126-130`). 이 계획은 그 판단에 쓸 실측(F-04)과 기준선(`T-READ-01`)만 낸다. |
| Map 안의 응답 캐시(프로세스·Valkey) | 기각 | ADR-030이 프로세스 안 데이터 캐시를 금한다. ADR-114는 Valkey를 "이 데이터의 저장소이지 PG 앞의 캐시가 아니다"라고 정의할 뿐 금지 조항은 아니다 — 그래도 PG 결과를 Valkey에 캐시하면 그 정의를 벗어나므로 ADR 개정이 먼저다. 같은 효과를 호출자 캐시(`T-READ-PIN-02`)로 얻는다. |
| Map uvicorn worker 늘리기 | 지금은 하지 않는다 | [실측] API CPU 0.15%(§4.1, 한 시점), [문서 주장] 느린 요청 중에도 작은 요청은 0.010초다. 병목이 이벤트 루프가 아니다. worker를 늘리면 연결 수(15 → 30+)와 프로세스별 지표·key 캐시가 갈린다. `T-READ-02` 뒤 루프 지연이 보이면 다시 본다. |
| Map pool 늘리기 | 기각 | 느린 질의가 더 많이 동시에 돌 뿐이다. 디스크가 병목일 때 역효과다. 공개 읽기의 대기 상한을 줄이는 쪽을 택한다(`T-READ-03`). |
| 엔진 `pool_timeout`을 2초로 | 기각 | API 엔진이 하나라 admin·ops·쓰기까지 같이 걸린다(F-05). 공개 읽기 의존성 안에서만 체크아웃 대기를 자른다(`T-READ-03`). |
| 문장마다 고정 `statement_timeout` | 기각 | 문장마다 따로 세므로 요청을 묶지 못한다(F-05). 요청 마감에서 남은 시간을 넘긴다. |
| 공용 PG 설정을 `ALTER SYSTEM`·reload로 | 기각 | Manager의 정본은 compose `command:` 값이고 `postgresql.auto.conf`는 비어 있어야 한다. env 값 + 재생성으로만 바꾼다(`T-READ-MGR-01`). |
| `prometheus.yml`을 손으로 고치기 | 기각 | registry에서 만드는 파생 파일이고 시험이 대조한다. 생성기를 고친다(`T-READ-MGR-02`). |
| 위치 감사 outbox의 COMMIT을 느슨하게 | 기각 | 위치정보법 확인자료 기록이다. `synchronous_commit = off`·`UNLOGGED`는 rate-limit 표에만 검토한다(`T-READ-PIN-05`). |
| Map의 spec 변경을 Map만 먼저 배포 | 불가 | pair gate가 Map과 PinVi vendor 사본의 OpenAPI hash 차이를 거부한다(§8.1). |
| PinVi timeout 늘리기 | 기각 | 실패를 늦출 뿐이고 버려진 질의가 더 오래 돈다. |
| 집계 응답 ETag(Map) | 보류 | 값싼 데이터 버전이 없어 304를 내려면 집계를 다시 해야 한다. 적재가 올리는 세대 번호가 생기면 다시 본다. |
| MVT 타일·범용 batch | 그대로 유예 | `MAP:docs/architecture/performance.md` §8.4의 판정과 조건을 그대로 둔다. |
| 읽기 전용 복제본·호스트 분리 | 범위 밖 | n150 한 대 전제(소유자). 효과는 크겠지만 이 계획의 작업으로 만들지 않는다. |
| 무중단 배포 | 범위 밖 | 배포 중 503은 인스턴스가 하나라 생긴다. PinVi의 짧은 캐시(`T-READ-PIN-02`)가 저배율 화면만 가린다. |
| gzip(Map API) | 지금은 하지 않는다 | 호출자가 loopback이다. 다른 호스트 소비자가 생기면 다시 본다. |
| 지도 행의 속성 하위 질의를 집합 조인으로 | 측정 뒤 | F-12. `T-READ-01` 계획에서 비중이 보이면 작업으로 올린다. |
| weather에 Valkey·새 worker | weather 설계를 따른다 | `WEA:docs/design/weather-performance-use-cases-20261109.md` §6.2가 조건부로 둔다. |

## 8. 작업 목록

작업 30개다 — Map 8, PinVi 7, Manager 7, weather 4, transport 4. **단계 순으로** 적는다. 각 작업의 형식은
**저장소 / 변경**(파일·함수) **/ 의존 / 배포 단위 / 해제 조건 / 검증 / 위험·되돌림**이다. Map 작업의 해제
조건은 `docs/tasks-acceptance.md`의 같은 ID 절이 소유하므로 여기에는 그 절을 가리키는 줄만 둔다.

### 8.1 공통 규칙

**배포 단위.** Map과 PinVi는 한 쌍으로 회전한다. Manager의 pair gate는 Map의 full OpenAPI hash와 PinVi가
vendor한 hash가 다르면 그 쌍을 거부한다(`MGR:backend/src/kor_travel_docker_manager/services/
m05_isolated_harness.py:174-193` — "full OpenAPI hashes differ"; PinVi의 vendor 사본은
`PIN:apps/api/tests/contract/kor-travel-map-openapi-{service,user,admin}.json`). 그래서 —

| 배포 단위 | 뜻 |
| --- | --- |
| **Map 회전(spec 불변)** | Map만 바뀐 pair 회전. Map의 OpenAPI 세 파일이 바뀌지 않아야 한다(`export_openapi.py --check`). |
| **Map+PinVi 한 회전** | Map의 OpenAPI가 바뀌는 작업. ① Map PR 머지 → ② PinVi가 재vendor한 spec을 담은 PR 머지 → ③ **한 번의 pair 회전**으로 둘을 함께 낸다. Map을 먼저 "배포"하고 PinVi를 기다리는 순서는 성립하지 않는다(2026-10-12 t1013b preflight 거부와 같은 실패). |
| **PinVi 회전** | PinVi만 바뀐 pair 회전(Map spec 불변). |
| **Manager 설치 + 재생성** | Manager 릴리스 설치 뒤 대상 컨테이너 재생성. 공용 PG 재생성은 전 tenant가 약 30초 끊기므로 소유자가 승인한 창에서만 한다. |
| **없음** | 스크립트·측정·보고서. 운영에 반영되는 코드가 없다. |

이 계획에서 Map의 OpenAPI를 바꾸는 작업은 **`T-READ-04` 하나**다. `T-READ-03`은 spec을 바꾸지 않는 것이
요구 사항이다.

**조용한 창.** 기준선과 설정 전후 비교는 "조용한 호스트"에서 잰다. 조용한 창은 저절로 오지 않는다 —
Map 적재는 schedule이 멈춰 있어도 큐에서 돈다. 절차는 Manager T-MGR-03r이 쓴 것과 같다
(`MGR:docs/tasks-done.md:85`).

1. 소유자가 창을 승인한다.
2. Map 적재 큐를 멈춘다(`DISABLED_FEATURE_LOAD_SCHEDULES`, 진행 중 operation 0 확인).
3. e2e·배포가 없다(`~/preflight.sh`·`~/io-guard.sh` PASS).
4. 공용 Dagster에 다른 tenant의 STARTED run이 0이다.
5. 30분 동안 PSI io `some` avg60 < 5%이면 그 창에서 잰다. 끝나면 큐를 되돌린다.

7일 동안 시도해도 그런 창이 없으면 **관측된 가장 낮은 PSI에서 재고 그 값을 적는다.** 그 수치로 뒤 작업
(`T-READ-05`~`07`, `T-READ-MGR-04`·`06`)을 진행할지는 소유자가 정해 journal에 적는다.

**문턱과 판정자.** 채택 문턱은 조용한 창과 적재 중 각각 30회의 p50으로 판정한다(DB 연결은 `jit=off`).
두 조건의 판정이 갈리면 소유자가 정한다. 이 문서의 문턱 숫자는 제안값이다 — 바꾸려면 소유자 승인을
받아 journal과 acceptance에 적는다.

**운영 변경.** 설정·재시작·배포는 소유자·배포 담당의 일이다. odroid는 Codex 담당이다.

### 8.2 순서 색인

| 단계 | ID | 저장소 | 의존 | 배포 단위 |
| --- | --- | --- | --- | --- |
| 0 | `T-READ-PIN-06` | PinVi | 없음 | 없음(읽기 전용 실행) |
| 0 | `T-READ-PIN-05` ① | PinVi | 없음 | PinVi 회전 |
| 0 | `T-READ-PIN-04` | PinVi | 없음 | PinVi 회전 |
| 0 | `T-READ-PIN-01` ①② | PinVi | 없음 | PinVi 회전 |
| 0 | `T-READ-MGR-07` | Manager | `T-READ-PIN-01` ②가 (가)를 고르면 | Manager 설치 + pinvi-api 재생성 |
| 0 | `T-READ-01` | Map | 없음 | 없음 |
| 0 | `T-READ-02` | Map | 없음 | Map 회전(spec 불변) |
| 0 | `T-READ-08` | Map | 없음 | Map 회전(spec 불변, migration) |
| 0 | `T-READ-MGR-03` | Manager | 없음 | Manager 설치 + Map·PinVi API 재생성 |
| 0 | `T-READ-MGR-01` | Manager | 없음 | Manager 설치 + 공용 PG 재생성(창) |
| 0 | `T-READ-MGR-06` ① | Manager | 없음 | 없음(측정) |
| 0 | `T-READ-MGR-05` | Manager·운영 | 없음 | 운영 |
| 0 | `T-READ-WEA-01`·`03`, `T-READ-TRN-01`·`03` | weather·transport | 없음 | 각 저장소 배포(odroid) |
| 1 | `T-READ-03` | Map | `T-READ-02` 머지, `T-READ-PIN-04` 운영 반영 | Map 회전(spec 불변) |
| 1 | `T-READ-04` + `T-READ-PIN-01` ③ | Map + PinVi | 서로 | **Map+PinVi 한 회전** |
| 1 | `T-READ-PIN-05` ② | PinVi | ①의 수치 | PinVi 회전 |
| 1 | `T-READ-PIN-03` | PinVi | 단계별 지표(같은 작업 ①) | PinVi 회전 |
| 1 | `T-READ-PIN-02`, `T-READ-PIN-07` | PinVi | `T-READ-PIN-06` 수치 | PinVi 회전 |
| 1 | `T-READ-MGR-02` | Manager | `T-READ-02` 운영 반영, `T-READ-MGR-03` | Manager 설치 + Prometheus 재생성 |
| 2 | `T-READ-MGR-04`, `T-READ-MGR-06` ② | Manager | `T-READ-MGR-01`, `T-READ-01` | 공용 PG 재생성(창) |
| 2 | `T-READ-WEA-02`·`04`, `T-READ-TRN-02`·`04` | weather·transport | 각자의 `-01` | 각 저장소 배포 |
| 3 | `T-READ-05` → `T-READ-06`, `T-READ-07` | Map | `T-READ-01` 보고서 | Map 회전(spec 불변, migration) |

같은 단계 안에서 파일이 겹치는 것 —

- `T-READ-02` → `T-READ-03`: 둘 다 `api/db.py`·`api/app.py`·`api/settings.py`. 02가 먼저다.
- `T-READ-05` → `T-READ-06`: 둘 다 `feature_repo.py`의 검색 경로.
- `T-READ-03`·`T-READ-04`: 03이 spec을 바꾸지 않으므로 생성 파일(`openapi*.json`)은 04만 건드린다.
- `T-READ-MGR-03`·`T-READ-MGR-07`·`T-READ-MGR-02`: 모두 `docker-compose.yml`. 03과 07은 0단계의 한 PR로
  묶어도 된다(블록이 다르다 — Map API `:1650` 이하, pinvi-api `:2111` 이하). 02는 그 뒤다.
- `T-READ-PIN-04`(`clients/kor_travel_map.py`의 `_send_with_retries`)와 `T-READ-PIN-01` ②(나·다는 같은
  파일의 `_send`)는 같은 파일이다 — 한 사람이 이어서 한다.

### 8.3 0단계 — 지금 시작할 수 있는 것

#### T-READ-PIN-06 — 이미 쌓여 있는 `app.api_call_log`를 집계한다 (PinVi)

- **변경**: PinVi는 Map·weather·geo 호출을 전부 `app.api_call_log`에 남긴다 — `provider`, `endpoint`(query
  string을 포함한 URL), `status_code`, `latency_ms`, `error_class`, `request_id`, `occurred_at`
  (`PIN:apps/api/app/models/api_call_log.py:14-28`, 기록은 요청 경로 밖의 묶음 쓰기). [실측, planner 통계
  표본 2026-11-16 05:28Z] 약 13.1만 행·41 MB, 2026-09-26부터, Map 73%·weather 15%·geo 10%, 응답 없음
  (status NULL) 0.43%, `ReadTimeout` 0.22%, `CancelledError` 0.19%. 이 표를 **읽기 전용으로 집계하는
  스크립트**(`apps/api/scripts/api_call_log_report.py`)를 더한다 — 최근 7일 이상에 대해 (provider, 경로
  틀, status, error_class)별 건수·p50·p95, 시간대별 건수, Map in-bounds는 URL의 `zoom`·`cluster_unit`별
  건수·p50·p95, `request_id`로 묶은 `/trips/{trip_id}`의 Map batch·날씨 호출 시간 합, 교통 반경 호출의
  건수와 실패. **출력은 집계뿐이다** — URL·bbox·좌표·request id·사용자를 내지 않는다(URL에 위치 정보가
  있다). sink가 버린 행 수(`pinvi_api_call_log_rows_total{outcome!="persisted"}`)를 함께 적는다.
- **의존**: 없음.
- **배포 단위**: 없음. 운영 PinVi DB에 읽기 전용 transaction·`statement_timeout` 30초로 한 번 실행한다
  (`~/io-guard.sh` PASS일 때).
- **해제 조건**: ① 집계 표가 보고서(`docs/reports/<날짜>-api-call-log-read-profile.md`)에 있다. ② 다음 넷을
  그 표로 답하거나 "여전히 모른다"와 이유를 적는다 — in-bounds의 zoom 분포(F-04), in-bounds 실패가 Map
  timeout·5xx(행이 있다)인지 PinVi의 상한·회로 거부(행이 없다)인지, 여행 보기 시간의 구성(F-16), 교통
  반경 호출이 실제로 있고 실패하는지(F-06). ③ 보고서에 URL·좌표·request id가 없다(검색으로 확인).
  ④ 버린 행 수를 적었다.
- **검증**: 스크립트 단위 시험(집계 함수, 경로 틀 변환), 보고서.
- **위험·되돌림**: 위치 정보가 든 URL — 집계만 내는 것으로 막는다. 조회는 `ix_api_call_log_provider_time`을
  탄다([실측] 탐색 1,682회로 이미 쓰이는 색인). 되돌림 없음.

#### T-READ-PIN-05 — 요청마다 붙는 비용을 재고 가볍게 한다 (PinVi)

- **변경**: ① **먼저 잰다(0단계).** 세 구간에 시간 histogram을 단다 — rate-limit 저장소 호출
  (`app/middleware/rate_limit.py:300-320`), 인증 사용자 조회(`app/core/deps.py:79-85`), 위치 감사 outbox
  쓰기(`app/middleware/location_audit.py:129-140`). PinVi `/metrics`는 공개라 Prometheus 없이도 읽을 수
  있다. ② **수치를 보고 가볍게 한다(1단계).** rate-limit 구간의 p95가 문턱(제안: 조용할 때 20 ms 초과
  또는 디스크 압력 중 200 ms 초과)을 넘으면 둘 중 하나를 고른다 — (가) rate-limit transaction에만
  `SET LOCAL synchronous_commit = off`(`_POSTGRES_BACKEND.check`, `rate_limit.py:203-237`), (나)
  `app.rate_limit_buckets`를 `UNLOGGED`로(WAL이 없어지고 crash 때 개수가 비워진다). 둘 다 잃는 것은
  "crash 직전의 개수"로 같다.
  **위치 감사 outbox에는 어느 것도 적용하지 않는다** — 위치정보법 확인자료 기록이라 동기 COMMIT을 유지한다.
- **의존**: ①은 없음. ②는 ①의 수치.
- **배포 단위**: PinVi 회전(①과 ②는 따로).
- **해제 조건**: ① 세 구간 histogram이 `/metrics`에 나온다. ② 조용할 때와 적재 중의 구간별 p50·p95를
  적었다. ③ 문턱을 넘어 ②를 적용했으면 전후 p95를 적고, 한도 초과 요청이 여전히 429인지 시험한다.
  문턱 아래면 적용하지 않고 근거로 닫는다. ④ 위치 감사 outbox의 transaction 설정이 바뀌지 않았다(시험).
- **검증**: 단위 시험(429 판정 불변, outbox 경로 불변), 운영 `/metrics` 전후.
- **위험·되돌림**: `synchronous_commit = off`와 `UNLOGGED` 모두 crash 직전 개수를 잃는다 — rate-limit에만
  걸리게 한다. 사용자 조회와 outbox 구간이 크게 나오면 이 작업 안에서 고치지 않고 새 작업으로 연다.

#### T-READ-PIN-04 — Map의 시간 초과 503을 다시 보내지 않는다 (PinVi, `T-READ-03`보다 먼저)

- **변경**: `app/clients/kor_travel_map.py`의 `_send_with_retries`(`:529-614`)에서 `resp.status_code >= 500
  and retry` 분기(`:590-595`)가 응답의 problem `code`를 읽는다(`_error_code`, `:1227-1241`).
  `READ_TIMEOUT`·`POOL_BUSY`면 `last = KorTravelMapUnavailable(…, code=그 값)`으로 두고 `break`한다. 회로에는
  실패로 센다(`ReadTimeout`과 같은 취급 — `:505-523`). 다른 5xx(`LOCK_TIMEOUT` 포함)의 재시도는 그대로 둔다.
  spec을 읽지 않고 `code` 문자열만 보므로 재vendor가 필요 없다.
- **의존**: 없음. Map에 이 코드가 아직 없어도 해가 없다.
- **배포 단위**: PinVi 회전. `T-READ-03`보다 먼저 단독으로 낸다.
- **해제 조건**: ① 가짜 Map이 503 `READ_TIMEOUT`을 내면 요청이 한 번만 나간다(계수 시험). `POOL_BUSY`도
  같다. ② 503 `LOCK_TIMEOUT`과 code 없는 500은 종전처럼 세 번이다. ③ 그 실패가 회로 실패 수에 한 번
  잡힌다. ④ 운영 반영 확인 — 운영 PinVi 이미지의 commit이 이 작업의 머지 commit을 포함한다(Manager pin
  또는 `/version`). **기록은 한 곳, Map `docs/journal.md`다**(`T-READ-03`의 배포 조건으로 쓴다).
- **검증**: `apps/api/tests/unit/`의 client 시험.
- **위험·되돌림**: 낮다. 재시도로 우연히 성공하던 요청이 한 번에 실패로 끝난다 — 그 코드는 Map이 "이미
  예산을 다 썼다"고 말한 경우뿐이다.

#### T-READ-PIN-01 — 교통·날씨 조회가 동시 호출 상한에 걸리지 않게 한다 (PinVi)

- **변경**:
  1. **재현 시험.** 진짜 `KorTravelMapClient`에 가짜 HTTP transport를 붙인다. (교통) 레이어 2개·2 km 넘게
     떨어진 점 2개로 반경 조회를 부르면 레이어가 `unavailable`이 된다. (날씨) 캐시에 없는 날씨 POI 4개가
     있는 여행 보기에서 뒤쪽 POI가 `unavailable`이 된다 — 해석 동시 4(`app/services/weather_map_resolver.py:72`)
     와 묶음 동시 4(`app/services/weather_map_state.py:596`)가 모두 `weather` 상한 2를 쓴다
     (`app/clients/kor_travel_map_weather.py:275-286`).
  2. **당장의 수정 — 셋 중 고르고 이유를 적는다.**
     (가) 코드 없이 상한을 올린다 — `PINVI_KOR_TRAVEL_MAP_TRANSPORT_MAX_CONCURRENCY`·
     `…_WEATHER_MAX_CONCURRENCY`(`app/core/config.py:827-828`, 범위 1~64). 두 범위는 Map에서 Valkey 읽기
     (명령당 µs — §4.1)라 상한의 원래 이유(#621, 느린 표면이 자리를 차지하는 것)가 거의 해당하지 않는다.
     한 요청의 최대 팬아웃(교통 6×2 = 12, 날씨 4+4 = 8)보다 커야 하므로 제안값은 16·16이다. 운영 env
     배선은 `T-READ-MGR-07`이다.
     (나) 한 요청의 동시 호출을 상한 이하로 묶는다(`NEAR_CONCURRENCY`, `RESOLVE_CONCURRENCY`,
     `_BATCH_CONCURRENCY`).
     (다) 상한이 찼을 때 바로 거부하지 않고 잠깐 기다린다(`_send`의 `slots.locked()` 검사를
     `wait_for(slots.acquire(), 0.5)`로 — `app/clients/kor_travel_map.py:481-488`).
     (가)는 가장 싸고 즉시 듣는다. (나)만으로는 다른 사용자의 요청과 겹칠 때의 거부가 남고, 60곳 ×
     2레이어를 2개씩 줄 세우면 레이어 상한 5초(`transport_layers.py:218`)를 넘긴다. (다)는 원인(대기열
     없는 상한 + 내부 팬아웃)을 고친다. 권고는 (가)를 먼저 내고 (다)를 뒤따르게 하는 것이다.
  3. **`near-batch` 전환(1단계, `T-READ-04`와 한 회전).** Map `T-READ-04`가 **머지되면** PinVi PR 하나에
     재vendor한 service spec, `app/clients/kor_travel_map_transport.py`의 `near-batch` 메서드, 405 fallback을
     함께 넣는다. 옛 Map은 이 `POST`에 405를 내고 PinVi는 그것을 `KorTravelMapBadRequest`로 바꾸므로
     (`kor_travel_map_transport.py:105-106`), 405를 "route 없음"으로 보고 옛 경로로 떨어지게 한다.
- **의존**: 1·2는 없음. 3은 `T-READ-04` **머지**(배포가 아니다).
- **배포 단위**: 1·2는 PinVi 회전. 3은 `T-READ-04`와 **Map+PinVi 한 회전**.
- **해제 조건**: ① 두 재현 시험이 수정 전 빨강, 수정 뒤 초록이다. ② Map 호출마다 30 ms 지연을 넣은
  시험에서 점 60개·레이어 2개 조회의 두 레이어가 상한 5초 안에 `ok`다(즉시 답하는 가짜로는 통과로 보지
  않는다). ③ 캐시에 없는 날씨 POI 20개의 여행 보기 한 번에서 `BULKHEAD_FULL`이 0건이다. ④ `near-batch`
  전환 뒤 같은 교통 요청이 Map을 레이어당 한 번 부른다(계수 시험). ⑤ Map이 405를 내면 옛 경로로 같은
  결과를 낸다(시험). ⑥ 결과 집합이 종전과 같다(기존 반경 시험 유지). ⑦ 고른 수정과 이유를 PR에 적었다.
- **검증**: 단위·통합 시험, live e2e의 여행 지도 교통 레이어와 여행 날씨 카드. 운영의
  `pinvi_api_outbound_bulkhead_rejections_total`은 관찰용이다.
- **위험·되돌림**: (가) 상한을 올리면 Map의 그 표면이 느려졌을 때 PinVi가 더 많은 자리를 쓴다 — 회로
  (3번 실패 → 120초)는 그대로 지킨다. (다) 기다리는 0.5초가 요청 시간에 더해진다. 3은 405 fallback이
  빠지면 옛 Map에서 레이어가 통째로 실패한다 — 해제 조건 ⑤가 막는다.

#### T-READ-MGR-07 — pinvi-api의 동시 호출 상한 env를 배선한다 (Manager, `T-READ-PIN-01` ②가 (가)일 때)

- **변경**: `docker-compose.yml`의 pinvi-api 블록(`:2111` 이하, Map 연동 env는 `:2176-2183`)에
  `PINVI_KOR_TRAVEL_MAP_TRANSPORT_MAX_CONCURRENCY`와 `PINVI_KOR_TRAVEL_MAP_WEATHER_MAX_CONCURRENCY`를
  `${…:-기본값}` 꼴로 더한다(compose에 없는 key는 root `.env`로 넣어도 컨테이너에 닿지 않는다).
  `.env.example`에 설명을 적는다.
- **의존**: `T-READ-PIN-01` ②가 (가)를 골랐을 때만 한다. 코드 변경이 필요 없다(설정은 이미 있다).
- **배포 단위**: Manager 설치 + pinvi-api 재생성.
- **해제 조건**: ① 운영 pinvi-api 컨테이너의 env에 두 값이 있다. ② `T-READ-PIN-01`의 재현 시나리오(여행
  지도 교통 레이어·날씨 카드)가 운영에서 `unavailable` 없이 뜬다(live e2e 또는 수동 확인을 journal에).
- **검증**: compose 모델 시험, `docker inspect`(값이 비밀이 아닌 항목).
- **위험·되돌림**: 낮다. 되돌림은 두 줄 제거 + 재생성.

#### T-READ-01 — 읽기 기준선과 재측정 도구 (Map)

- **변경**:
  1. `scripts/perf_tier2_release_harness.py`의 엔진(`:339`)을 운영 API처럼 `jit=off`로 만든다
     (`make_async_engine(..., server_settings={"jit": "off"})` — 운영은 `api/db.py:61`). JIT를 켠 수치는
     운영이 보지 않는 수치다(2026-11-12 "부산 맛집" 7.6초 중 7.2초가 JIT — `repo:7783-7785`). 같은 자리에서
     `statement_timeout` 30초를 건다(`server_settings` 또는 `Viewport.pre`). 지금 harness는 timeout을 걸지
     않는다.
  2. harness 인자는 지금 `--rows`·`--iterations`·`--skip-seed`·`--dsn`이고 결과는 stdout뿐이다(`:445-461`).
     `--output <파일>`을 더해 `.safe.json`을 쓴다.
  3. 대표 viewport를 6개(`:196-262`)에서 **13개**로 늘린다 — 지역 검색 둘("부산 맛집" 좁은 지역, "서울
     맛집" 넓은 지역), 시군구 집계(zoom 10), **서울시청 zoom 12 읍면동 집계**(bbox 약
     126.758,37.456,127.198,37.677)와 **zoom 13 변형**(PinVi의 기본 화면 — F-04), 개별 행 500건(zoom 14
     서울), 상세 1건. zoom 12·13은 PinVi 기본 kind(`place`·`event`·`notice`·`price`)와 `max_items` 500으로 잰다.
  4. 지역 검색 SQL은 고정 문자열이 아니다 — 요청 때 `_resolve_search_region` → `_search_region_arms` →
     `_search_region_params` → `_search_score_sql`로 만들어진다. harness의 `Viewport`는 고정 SQL 하나만 받으므로
     (`:160-170`) 지역 검색 viewport는 이 네 함수를 불러 SQL과 인자를 만든다. 전처리 질의 셋
     (`_SEARCH_ALIAS_LOOKUP_SQL`·`_SEARCH_REGION_ENTRIES_SQL`·`_SEARCH_REGION_ROW_COUNT_SQL`)은 각각 따로 잰다.
  5. **단계별 비중은 EXPLAIN 노드로 잴 수 없다.** `compacted`·`hits`는 한 번만 참조되는 일반 CTE라 PostgreSQL이
     inline한다 — 노드가 따로 나오지 않는다(`name_candidates`만 `MATERIALIZED`다, `repo:2327`). 그래서
     **빼고 재는 방식**으로 잰다: (i) 지역 검색 본 질의 전체, (ii) 같은 질의에서 `compacted`·`hits`의 식을
     상수로 바꾼 변형. 비중 = (i − ii) / i, 30회의 p50. harness 안에만 두는 변형이고 운영 SQL은 바꾸지 않는다.
  6. 새 스크립트 `scripts/read_path_probe.py`가 운영 Map API에 PinVi와 같은 모양의 HTTP 요청을 보내
     `meta.duration_ms`와 전체 시간을 모으고 묶음마다 `/proc/pressure/io`를 적는다(호스트에서 돈다). 인증은
     실행할 때 Map API 컨테이너의 service token을 읽어 쓰고(공개 route도 그 token을 받는다 — `api/auth.py:940`)
     **출력하거나 파일에 쓰지 않는다.** probe에는 DB 연결이 없다.
  7. 결과는 `docs/reports/<날짜>-read-baseline.md`와 `.safe.json`.
- **의존**: 없음. 실행은 §8.1의 조용한 창 절차를 따른다.
- **배포 단위**: 없음.
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-01` 절(원장이 소유한다).
- **검증**: 새 viewport·`jit=off`·`--output`의 단위 시험, harness를 두 번 돌려 같은 schema의 JSON이
  나오는지 확인.
- **위험·되돌림**: 읽기 전용이다. 전국·서울 집계 30회가 수십 초 CPU를 쓰므로 적재와 겹치지 않게 한다.

#### T-READ-02 — 요청·DB 지표와 느린 요청 로그 (Map)

- **변경**: ① 요청 도착 시각을 미들웨어가 `request.state.started_monotonic`에 적는다(`T-READ-03`이 이
  값에서 마감을 센다). ② 지표 flag와 **무관한** 느린 요청 로그를 `api/app.py` 미들웨어에 더한다 — 요청
  시간이 `KOR_TRAVEL_MAP_API_SLOW_REQUEST_LOG_MS`(기본 1000) 이상이면 route template·status·
  `duration_ms`·DB 문장 수·DB 시간 합·request id를 한 줄로 남긴다(query string·key·좌표는 남기지 않는다).
  DB 합계는 `api/db.py`의 cursor 이벤트에 요청별 contextvar 누산기를 달아 얻는다. ③ 연결 풀 지표 —
  **세션을 미리 여는 방식으로 재지 않는다.** 세션은 첫 문장에서야 연결을 꺼내고(`api/db.py:93-133`) 인증
  세션은 그 지연에 기대고 있다(`:109-118`). 사용 중 연결 수는 scrape 때 `engine.pool.checkedout()`·
  `overflow()`에서 읽고, 대기 시간은 `AsyncAdaptedQueuePool`의 작은 하위 클래스가 `_do_get`을 감싸 잰다.
  그러려면 `make_async_engine`(`src/kortravelmap/infra/db.py:884-892`)에 `poolclass` 인자를 더한다(기본값은
  지금 동작 그대로). ④ `api/settings.py`에 설정 추가, `docs/deploy.md`에 운영 값 안내.
- **의존**: 없음. 운영에서 지표를 켜는 것은 `T-READ-MGR-03`, 긁는 것은 `T-READ-MGR-02`.
- **배포 단위**: Map 회전(spec 불변).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-02` 절(원장이 소유한다).
- **검증**: `packages/kor-travel-map-api/tests/`의 단위·통합 시험, OpenAPI drift 없음.
- **위험·되돌림**: 로그 양 — 문턱을 올리거나 0으로 끈다. label은 route template만 쓴다. pool 하위 클래스가
  체크아웃 동작을 바꾸지 않는지 시험한다.

#### T-READ-08 — `feature.features`의 autovacuum 문턱을 표에 맞춘다 (Map)

- **변경**: ① **먼저 잰다.** `feature.features`와 읽기 경로 표(`provider_sync.source_links`·
  `source_entities`)의 `relallvisible/relpages`, dead 행, 마지막 autovacuum을 적재 전·직후·24시간 뒤에
  적는다(읽기 전용). 지역 행 수 질의(`_SEARCH_REGION_ROW_COUNT_SQL`, `repo:2706`)의 `EXPLAIN (ANALYZE,
  BUFFERS)`에서 `Heap Fetches`를 적는다. ② **표 단위 설정을 migration으로 넣는다.** `feature.features`에는
  reloptions가 없어(`alembic/head-schema.sql:16371`) autovacuum이 50 + 20% dead(약 8.8만 행)에서야 돈다 —
  [실측] dead 6.3만으로 3.6일 동안 한 번도 돌지 않았고 all-visible은 58%였다.
  `autovacuum_vacuum_scale_factor`·`autovacuum_vacuum_insert_scale_factor`·`autovacuum_analyze_scale_factor`를
  표에 건다(제안 0.02·0.05·0.02 — ①의 수치로 확정). ③ 큰 적재 job 끝의 `VACUUM (ANALYZE) feature.features`는
  ②로 부족할 때만 더한다.
- **의존**: 없음.
- **배포 단위**: Map 회전(spec 불변, migration). `ALTER TABLE … SET (…)`은 표를 다시 쓰지 않는다.
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-08` 절(원장이 소유한다).
- **검증**: migration 시험, 운영 적재 한 번 전후의 통계.
- **위험·되돌림**: autovacuum이 더 자주 돈다 — 적재 중 I/O가 조금 는다(F-15의 디스크 압력). 되돌림은
  reloptions 제거 migration.

#### T-READ-MGR-03 — API 프로세스를 swap에서 지키고 Map 지표를 켠다 (Manager)

- **변경**: ① Map API(`docker-compose.yml:1650` 이하)·PinVi API(`:2111` 이하) 블록에 Manager의 기존 규칙대로
  `mem_limit: ${KTDM_…_MEM_LIMIT:-값}`와 **같은 변수의** `memswap_limit`를 둔다(공용 PG가 쓰는 꼴 —
  `docker-compose.yml:258-261`). 그 규칙을 검사하는 시험(`backend/tests/test_postgres_host_tuning.py` 계열)에
  두 서비스를 더한다. 한도는 실측 RSS + swap의 3배에서 시작한다(Map API 약 170 MB → 512 MB, PinVi API 약
  165 MB → 512 MB). 두 UI(Map UI `:1750`, PinVi web `:2244`)는 RSS를 먼저 재고 같은 규칙으로 넣는다 — 재지
  않은 값을 넣지 않는다. ② Map API 블록의 `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED`를
  `'false'`(`:1689`)에서 켜고, metrics token secret을 `KOR_TRAVEL_MAP_API_METRICS_TOKEN`으로 넣는다(운영
  profile은 지표를 켜면 token이 필수다 — `MAP:api/settings.py:1263-1275`).
- **의존**: 없음. 지표 켜기는 지금 Map 코드로 된다.
- **배포 단위**: Manager 설치 + Map·PinVi API 재생성.
- **해제 조건**: ① 재생성 뒤 두 API 프로세스의 `VmSwap`이 0이다. ② 전체 e2e 한 번 동안 OOM kill이 없다
  (`docker inspect`의 `OOMKilled`, `dmesg`). ③ 한가한 12시간 뒤에도 `VmSwap` 0. ④ Map `/metrics`가 token
  없이는 401이고 token으로는 200이다.
- **검증**: `/proc/<pid>/status`, e2e 결과, compose 모델 시험.
- **위험·되돌림**: 한도가 작으면 OOM — ②가 본다. 되돌림은 한도 변수 0(상한 없음)과 지표 flag 원복.

#### T-READ-MGR-01 — 공용 PostgreSQL의 질의 관측을 켠다 (Manager, n150·odroid)

- **변경**: 공용 PG의 설정 정본은 compose `command:`의 `-c` 값이고(`docker-compose.yml:284-330`,
  `docs/shared-postgres-onboarding.md:17-23`) `postgresql.auto.conf`는 비어 있어야 한다(T-MGR-03r이
  확인하는 항목 — `docs/tasks-done.md:85`). 그래서 **`ALTER SYSTEM`·reload로 넣지 않는다.**
  ① `-c log_min_duration_statement=${KTDM_PG_LOG_MIN_DURATION_STATEMENT:-…}`·`track_io_timing`·
  `log_lock_waits`·`log_temp_files`를 같은 꼴로 더하고, `backend/tests/test_postgres_host_tuning.py`와
  `.env.example`을 고친다. ② `pg_stat_statements` 확장은 tenant 역할이 만들 수 없다(NOSUPERUSER). 관리
  권한의 init 단계가 만든다 — geo의 one-shot(`kor-travel-shared-db-init-geo`, `docker-compose.yml:447-501`)이
  `x_extension`에 확장을 만드는 방식을 따른다. Map DB에는 그런 one-shot이 없으므로 새로 두거나, 관리 역할로
  한 번 실행하는 절차를 `docs/shared-postgres-onboarding.md`에 적는다. ③ 호스트별 PG major를 작업에 적는다
  ([실측] n150은 PostgreSQL 18.6. odroid는 확인하지 않았다).
- **의존**: 없음.
- **배포 단위**: Manager 설치 + 공용 PG **재생성**(T-MGR-03r 절차 — preflight, Map 큐 정지,
  `up -d --no-deps kor-travel-shared-postgres`, 전 tenant 약 30초 순단). 소유자가 승인한 창에서 하고,
  `T-READ-MGR-04`가 `shared_buffers`를 바꾸기로 정해졌다면 같은 창에 묶는다.
- **해제 조건**: ① `SHOW`로 네 값이 보이고 `postgresql.auto.conf`에 override가 없다(두 호스트). ②
  `pg_stat_statements`를 읽는 역할과 절차가 문서에 있다. ③ 1초 넘는 문장이 PG 로그에 남는다(시험 문장
  `pg_sleep(1.1)`). ④ 켠 뒤 24시간의 느린 질의 로그 줄 수와 크기를 적었다 — **하루 200 MB 또는 5만 줄을
  넘으면** 문턱을 3초로 올린다(문턱이 클러스터 전체라 모든 tenant의 Dagster 배치 문장도 잡힌다).
- **검증**: 재생성 전후 `pg_settings`, 로그 한 줄, compose 모델 시험.
- **위험·되돌림**: 재생성은 전 서비스 순단이다. `track_io_timing`의 시계 비용은 `pg_test_timing`으로 먼저
  확인한다. 되돌림은 env 값 원복 + 재생성.

#### T-READ-MGR-06 — 디스크에 쓰는 쪽을 가려내고 줄인다 (Manager, n150)

- **변경**: ① **먼저 잰다(0단계, 읽기 전용).** `pg_stat_wal`(WAL bytes·FPI), `pg_stat_checkpointer`
  (timed/requested, write·sync 시간), `pg_stat_bgwriter`, `pg_stat_io`(backend_type별 쓰기),
  `pg_stat_database`(DB별), `T-READ-MGR-01` 뒤에는 `pg_stat_statements`의 `wal_bytes` 상위 문장. 하루 간격
  두 번의 차이로 "하루에 누가 얼마를 쓰는지"를 표로 만든다. [실측, 약 46시간 창] checkpoint 552회가 모두
  시간 주기였고(요청 2회), checkpointer가 버퍼 123만 개(9.4 GB)를 쓰는 데 write 시간 59,010초를 썼다
  (버퍼당 약 48 ms). bgwriter 124만 개, WAL 17 GB(FPI 267만 건), `wal_buffers_full` 47,690회. ② Valkey:
  [실측] `CONFIG GET save`는 `900 1`인데(`docker-compose.yml:1536`) fork가 837,887초 동안 2,757번이었다
  (약 304초마다) — `900 1`만으로는 최대 931번이다. `SAVE`·`BGSAVE` 명령 기록은 없다. 무엇이 저장을
  일으키는지 찾는다. ③ **수치를 보고 한 번에 하나씩 바꾼다(2단계).** 후보: `checkpoint_timeout` 5분 → 15분,
  `max_wal_size` 2 GB → 4~8 GB, `wal_compression` off → `lz4`/`zstd`. 셋 다 이미 `${KTDM_PG_…}` 변수라
  (`docker-compose.yml:308-326`) n150의 root `.env`만 바꾸면 된다. 값은 소유자가 승인한다.
- **의존**: ①②는 없음. ③은 `T-READ-MGR-01`(전후 비교)과 소유자 승인.
- **배포 단위**: ①②는 없음. ③은 공용 PG 재생성(창) — `T-READ-MGR-01`·`04`와 같은 창에 묶을 수 있으나
  값은 창마다 하나만 바꾼다.
- **해제 조건**: ① "하루 쓰기량 — 주체별(checkpointer·bgwriter·backend·autovacuum·WAL), DB별" 표가
  보고서에 있다. ② Valkey 저장 주기의 원인을 적었다(또는 "모른다"와 다음 확인). ③ 값을 바꿨으면 같은
  길이의 전후 구간에서 하루 WAL bytes·checkpointer write 시간·PSI io avg300을 적었다. 나아지지 않으면
  되돌린다.
- **검증**: 위 표.
- **위험·되돌림**: `checkpoint_timeout`을 늘리면 crash 복구 시간이 는다. `wal_compression`은 CPU를 쓴다.
  되돌림은 `.env` 원복 + 재생성.

#### T-READ-MGR-05 — odroid NVMe의 남은 공간을 확보한다 (Manager·운영, 급함)

F-10의 운영 작업이다. 2026-11-17에 소유자에게 전달됐다.

- **변경**: 공용 PG의 데이터 디렉터리가 있는 NVMe 파일시스템의 사용처를 확인하고 PG가 쓸 여유를 만든다. 남은
  공간 경보를 건다. weather artifact volume(eMMC)의 위치도 함께 정한다.
- **의존**: 없음.
- **배포 단위**: 운영(odroid, 소유자·Codex).
- **해제 조건**: ① 남은 공간이 PG 데이터 크기의 20% 이상이다. ② 문턱 아래로 내려가면 알린다.
- **검증**: `df -h`.
- **위험·되돌림**: 다른 팀 호스트의 자료를 지우는 일이라 소유자 확인이 먼저다.

#### T-READ-WEA-01 — 공개 읽기 시간 상한과 단계별 지표 (weather)

- **변경**: 공개 `/v1/weather/*` 읽기 transaction에 `SET LOCAL statement_timeout`(export는 이미 5초,
  `SRC/export_snapshots.py:522`), pool 대기·export 단계별(freeze·artifact 읽기·직렬화) 시간 지표,
  histogram 상한을 30초 위로 늘린다(`SRC/metrics.py:270-274`).
- **의존**: 없음.
- **배포 단위**: weather 배포(odroid).
- **해제 조건**: ① 상한을 넘긴 공개 읽기가 503이고 연결이 pool에 돌아온다. ② export 요청 하나의
  단계별 시간이 지표에 나온다. ③ 첫 페이지·cursor 페이지·304가 label로 갈린다.
- **검증**: 시험 + `/metrics`.
- **위험·되돌림**: 느린 정상 질의가 실패로 바뀐다 — 상한을 env로 둔다.

#### T-READ-WEA-03 — cursor 페이지를 줄 때 snapshot 만료를 늦춘다 (weather)

- **변경**: Map PR #1493이 남긴 요청 — snapshot handle의 TTL(15분)을 cursor 페이지 응답 때 연장한다
  (지금은 첫 페이지 재사용 때만 갱신한다 — `SRC/export_snapshots.py:752-786`, 재확인 안 함).
- **의존**: 없음.
- **배포 단위**: weather 배포.
- **해제 조건**: 15분을 넘는 전량 순회가 410 없이 끝난다(시계 주입 시험). 만료된 handle은 연장하지 않는다.
- **검증**: 시험. Map 쪽 `weather_state_forecast_short` 전량 run의 재시작 횟수.
- **위험·되돌림**: 오래 사는 snapshot이 artifact GC를 붙잡는다 — 연장 상한을 둔다.

#### T-READ-TRN-01 — 요청 시간과 문장 수를 남긴다 (transport)

- **변경**: `backend/app/main.py`에 요청 시간 미들웨어(느린 요청 로그 + `/metrics` 또는
  `Server-Timing`), SQL 문장 수 누산, **요청당 프로세스 CPU 시간**. Map의 `T-READ-02`와 같은 로그 모양을
  쓴다. transport의 5,000곳 지도는 SQL보다 Python이 더 썼다([문서 주장] SQL 5회 약 2.18초, Pydantic 생성
  4.79초, UTC 보정 1.78초 — `TRN:docs/reports/2026-11-07-read-max-optimization.md:25`).
- **의존**: 없음.
- **배포 단위**: transport 배포(odroid).
- **해제 조건**: ① 1초 넘는 요청이 route template·시간·문장 수·CPU 시간과 함께 로그에 남는다. ② query
  string이 남지 않는다. ③ 지표가 gateway allowlist 밖에서만 보인다.
- **검증**: 시험, `scripts/benchmark-db-reads.py` 전후.
- **위험·되돌림**: 낮다.

#### T-READ-TRN-03 — 참조 export가 304를 싸게 낸다 (transport)

- **변경**: snapshot의 내용 digest로 304를 먼저 판정하고, 입력 fingerprint를 head 세대당 한 번만
  계산한다(재확인 안 함: `services/export_references.py:353-404`,
  `services/reference_export_revision.py:44-81`).
- **의존**: 없음.
- **배포 단위**: transport 배포.
- **해제 조건**: 내용이 같은 조건부 요청이 페이지를 만들지 않는다(계수 시험). [문서 주장] 4.02초였던
  조건부 조회가 300 ms 안이다(같은 문서의 측정 방법으로).
- **검증**: `backend/tests`의 export 시험에 계수 시험 추가, 같은 보고서의 측정 절차 재실행.
- **위험·되돌림**: 무효화 누락 — 세대가 바뀌면 반드시 다시 계산하는 시험.

### 8.4 1단계

#### T-READ-03 — 공개 읽기에 요청 마감을 건다 (Map)

- **변경**:
  1. **새 의존성만 만든다.** `api/db.py`에 `get_public_read_snapshot_session`(read-only REPEATABLE READ)과
     `get_public_read_session`(지금의 `get_session`과 같은 격리)을 더한다. 바꾸는 규칙은 하나다 — 범위
     안의 route에서 `get_session` → `get_public_read_session`, `get_read_snapshot_session` →
     `get_public_read_snapshot_session`. **격리 수준은 route마다 지금 그대로다.**
     `get_read_snapshot_session`과 `get_session` 자체는 건드리지 않는다(앞의 것은 admin·ops·`/service`
     cache-target 스트림 등 13개 router가 함께 쓴다).
  2. **마감은 세션에 싣는다.** 새 의존성이 `session.info["public_read_deadline"]`에 monotonic 마감을
     적는다. 시계는 요청 도착에서 시작한다 — `T-READ-02`의 `request.state.started_monotonic`을 쓰고 없으면
     의존성 자신의 시각을 쓴다. ContextVar는 쓰지 않는다 — ADR-112의 `_DEADLINE`
     (`src/kortravelmap/infra/transaction_limits.py:58-75`)을 재사용하면 공개 요청 안의 client 호출에
     ADR-112의 여유 3초·바닥 1초가 걸린다(`src/kortravelmap/client/__init__.py:925-1175`).
  3. **남은 시간을 문장에 넘긴다.** 같은 모듈에 `apply_public_read_budget(session)`을 더한다 —
     `statement_timeout` = 남은 시간 − 0.3초(바닥 250 ms), 남은 시간이 여유 이하면 SQL을 보내지 않고
     `ReadBudgetExceeded`를 올린다. `session.info`에 마감이 없으면 아무것도 하지 않는다(Dagster·CLI
     호출자는 그대로다). ADR-112의 `apply_transaction_limits`와 그 상수는 바꾸지 않는다.
  4. **문장이 여럿인 경로는 무거운 문장 앞에서 다시 건다.** `repo`의 `search_features`는 본 질의와 개수
     질의 직전에 다시 부른다. 지금의 `SET LOCAL` 두 줄(`repo:7782-7786`)은 따로 보내는 두 문장이다 —
     `;`로 이은 한 문자열은 asyncpg의 prepared statement에서 실패하므로, **`SELECT set_config(…),
     set_config(…), set_config('statement_timeout', :ms, true)` 한 문장**으로 묶는다(왕복이 늘지 않는다).
     다른 공개 경로는 무거운 문장이 하나라 transaction 시작 때 한 번으로 충분하다.
  5. **예산 값**: `api/settings.py`에 `public_read_budget_ms`(기본 4500 — PinVi의 읽기 timeout 5초보다
     짧게)와 `public_read_slow_budget_ms`(기본 14000)를 둔다. 뒤의 것은
     `GET /v1/public/festivals/monthly`에만 쓴다 — PinVi가 이 route만 15초를 기다린다(§3.3). 0이면 끈다.
  6. **pool 대기는 의존성 안에서만 자른다.** 엔진의 `pool_timeout`은 바꾸지 않는다(엔진이 하나라 전
     경로에 걸린다). 새 의존성이 첫 연결 획득(`await session.connection()`)을
     `asyncio.timeout(public_read_pool_wait_ms, 기본 2000)`으로 감싸고, 넘으면 `PoolBusy`를 올린다. 대기
     시간은 요청 예산에서 빠진다. 취소된 체크아웃이 연결을 흘리지 않는지 시험한다. 흘리면 공개 읽기 전용
     엔진으로 바꾼다 — 그때는 `make_async_engine`에 `pool_timeout: float | None = None` 인자를 더하고,
     **지금의 15개를 나눠** 쓴다(예: 주 엔진 4+8, 공개 읽기 3 — 공용 PG의 `max_connections`는 100이다).
     어느 쪽을 택했는지 PR에 적는다.
  7. **오류 변환은 기존 handler를 넓힌다.** `api/app.py:1066-1085`의 `DBAPIError` handler(55P03 → 503
     `LOCK_TIMEOUT`)에 "요청이 공개 읽기 예산 아래였고 SQLSTATE가 57014면 503 `READ_TIMEOUT`"을 더한다.
     예산 표시는 의존성이 `request.state`에 남긴다 — 표시가 없는 요청의 57014는 지금처럼 500으로 간다.
     `ReadBudgetExceeded`도 503 `READ_TIMEOUT`, `PoolBusy`는 503 `POOL_BUSY`다. batch route의
     `except SQLAlchemyError`(`features.py:1786-1795`)는 57014를 다시 던진다.
  8. **OpenAPI를 바꾸지 않는다(요구 사항).** 모든 route에는 공통 problem 응답이 이미 주입돼 있다
     (`_augment_problem_responses`, `api/app.py:1425-1437`). 새 응답 선언·새 schema·`code` enum을 더하지
     않는다. spec이 바뀌면 PinVi가 재vendor해야 하는데, 새 spec을 든 PinVi는 옛 Map과 hash가 달라 회전할
     수 없다 — "`T-READ-PIN-04`가 먼저 운영에 있다"는 조건을 지킬 수 없게 된다.
  9. **적용 범위**: `routers/features.py`의 공개 route(in-bounds·bbox·search·nearby·nearby/by-target·상세·
     contained-features·price·price/snapshot·batch), `routers/categories.py`, `routers/public_providers.py`,
     `routers/public_views.py`(해수욕장·축제의 목록·상세·map-markers — 지금 `get_session`인 것과 snapshot인
     것이 섞여 있다), `routers/curations.py`의 **공개** GET 넷(`""`·`/collections`·
     `/collections/{collection_id}`·`/features/{feature_id}`, `:2628-2733` — PinVi가 `GET /v1/curations`를
     부른다), `routers/place_attributes.py`. `admin_router`의 route, `features.py` 안의
     `require_admin_frontend` route, 그 밖의 모든 router는 범위 밖이다.
- **의존**: `T-READ-02` 머지(같은 파일, `started_monotonic`, 느린 요청 로그). **운영 반영은
  `T-READ-PIN-04`가 운영에 있은 뒤** — 그 전에는 PinVi가 이 503을 세 번 다시 보낸다.
- **배포 단위**: Map 회전(spec 불변).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-03` 절(원장이 소유한다).
- **검증**: 통합 시험(PostGIS), n150 CI-parity 4세션, `export_openapi.py --check`. 배포 뒤 `T-READ-02`의
  로그로 503 `READ_TIMEOUT`·`POOL_BUSY` 건수를 일주일 본다.
- **위험·되돌림**: ① PinVi가 먼저 고쳐지지 않으면 멈춘 요청 하나가 무거운 질의 세 번(약 14초)이 된다 —
  의존 순서가 막는다. ② 조용할 때 1.0~1.3초인 route·area 전국 집계가 정지 구간에 예산을 넘으면 "늦게
  성공"하던 것이 "빨리 실패"가 된다. ③ Map 관리 화면이 공개 route를 더 긴 timeout으로 부르면 그
  호출자도 4.5초에 끊긴다 — 구현 PR이 관리 화면의 timeout을 확인해 적는다. ④ 취소된 pool 체크아웃의
  연결 누수(변경 6의 시험). 되돌림은 예산 env 0.

#### T-READ-04 — 교통 근처 조회를 한 요청으로 받는다 (Map, `T-READ-PIN-01` ③과 한 회전)

- **변경**: `api/routers/service_transport.py`에 `POST /v1/service/transport/{dataset}/near-batch`
  (dataset은 `fuel-stations`·`highway-incidents`)를 더한다. 본문은 `points[]`(lon·lat, 최대 60)와
  `radius_m`(≤ 50,000)·`limit`(≤ 500)이다. 지금의 목록 조회는 Valkey 왕복이 4번이다(포인터 → meta →
  `GEOSEARCH` → `HMGET`, `service_transport.py:589-616`). 새 route는 포인터를 읽고, meta와 점마다의
  `GEOSEARCH … WITHDIST`를 pipeline 하나로 보낸다(`src/kortravelmap/infra/valkey_state.py`에 `nearby_many`
  추가). 점 60개 × (limit+1)이면 id가 3만 개까지 나올 수 있으므로 **값을 읽기 전에 줄인다** — id마다 가장
  가까운 거리를 남기고, 거리순으로 정렬해 limit+1개만 `HMGET` 한 번으로 읽는다. 왕복은 점 수와 무관하게
  3번이다. 응답 item은 기존 목록과 같은 모양에 가장 가까운 점까지의 거리를 붙인다. service OpenAPI와
  ADR-114 "구현 설계 — 1단계" 표에 route를 더한다.
- **의존**: 없음(머지까지). 운영 반영은 `T-READ-PIN-01` ③의 PR이 머지된 뒤다.
- **배포 단위**: **Map+PinVi 한 회전.** ① 이 PR 머지 → ② PinVi PR(재vendor한 service spec + `near-batch`
  client + 405 fallback) 머지 → ③ 한 pair 회전. Map만 먼저 회전할 수 없다(§8.1).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-04` 절(원장이 소유한다).
- **검증**: 단위·통합 시험(Valkey), `scripts/read_path_probe.py`에 점 20개 요청을 더해 시간을 적는다.
- **위험·되돌림**: 추가 route라 기존 소비자에 영향이 없다. 이 route가 없는 옛 Map은 같은 경로의
  `POST`에 405를 낸다(`GET /{dataset}/{feature_id}`가 경로를 잡는다). 되돌림은 PinVi가 옛 경로로 돌아간
  뒤 route 제거 — 그것도 spec 변경이라 한 회전으로 한다.

#### T-READ-PIN-03 — 여행 보기의 단계별 시간을 재고, 날씨가 크면 함께 기다린다 (PinVi)

- **변경**: ① **먼저 잰다.** `pinvi_trip_view_phase_seconds{phase=db|features|weather}` histogram을
  `app/services/trip_view_builder.py`에 단다. 여행 보기에서 날씨는 해석을 포함해 1.5초 예산에 묶여 있다
  (`pinvi_trip_view_weather_budget_seconds`, `app/core/config.py:973-975`) — **함께 기다려서 줄일 수 있는
  시간은 최대 약 1.5초다.** 평균 9초의 나머지는 Map batch(5xx를 세 번 다시 보내면 약 15.6초까지), 순서대로
  도는 DB 질의 5~6개(`trip_view_builder.py:100-170`), 요청당 비용(F-13)에서 온다. ② **운영에서 weather 단계의
  p50이 0.5초 이상일 때만** 다음을 한다. 지금 두 가지는 같은 `AsyncSession`(`db`)을 쓴다 — Feature 쪽은
  `cache_generation_observer.observe(db, …)`(`:192`)와 `release_read_connection(db)`(`:211`), 날씨 쪽은
  `db`를 받아(`:278`) 조회·commit·link 저장을 한다(`app/services/weather_map_resolver.py:265,270,299`).
  `AsyncSession`은 동시에 쓸 수 없으므로 그냥 `asyncio.gather`로 묶으면 안 된다. 둘 중 하나로 한다 —
  (가) 날씨 쪽에 `async_session_factory()`로 만든 자기 세션을 준다(link 저장의 commit이 요청 세션과
  분리된다 — link는 7일짜리 조회 캐시다, `weather_map_resolver.py:68`). (나) 두 쪽의 DB 읽기를 먼저
  순서대로 끝내고 HTTP 호출만 함께 기다린 뒤 쓰기는 다시 순서대로 한다.
- **의존**: ①은 없음. ②는 ①의 운영 수치.
- **배포 단위**: PinVi 회전(①과 ②는 따로).
- **해제 조건**: ① 단계별 histogram이 `/metrics`에 나오고 운영 p50·p95를 적었다. ② weather p50이 0.5초
  미만이면 ②를 하지 않고 그 수치로 닫는다. ③ ②를 했으면 — 진짜 `AsyncSession`(PostgreSQL)으로 두 쪽이
  모두 DB를 건드리는 통합 시험에서 세션 동시 사용 오류가 없고, 한쪽이 실패해도 다른 쪽 결과가 그대로이고,
  응답 본문이 종전과 같고, (가)를 택했으면 요청당 pool 연결 수의 최댓값을 적었다.
- **검증**: 통합 시험, `/metrics`의 `/trips/{trip_id}` 분포와 `pinvi_api_db_pool_wait_seconds` 전후.
- **위험·되돌림**: ②는 **중간**이다. 세션을 잘못 나누면 간헐적인 `InvalidRequestError`나 반쯤 저장된
  link가 생긴다. (가)는 요청당 pool 연결을 하나 더 쓴다. 이득의 상한이 1.5초이므로 작으면 되돌린다.

#### T-READ-PIN-02 — in-bounds 집계 응답을 짧게 캐시하고 같은 요청을 합친다 (PinVi)

- **변경**: `app/api/v1/features.py:401-470`의 in-bounds에서 Map이 **집계 모드로 답한 응답**
  (`mode == "clusters"`)만 60초 둔다. 캐시 여부를 zoom 숫자로 정하지 않는다. 키는 이 endpoint가 받는
  **모든** 인자다 — 맞춘 bbox, `zoom`, `kinds`, `category`, `cluster_unit`, `limit`, `include_geometry`.
  bbox는 웹과 같은 규칙으로 서버가 맞춘다(`apps/web/lib/featureBounds.ts` — zoom ≤7 소수 2자리, ≤10
  3자리, 그 위 5자리). 같은 키의 진행 중 요청은 하나로 합친다(축제 월별 캐시와 같은 방식,
  `app/clients/kor_travel_map.py:1022-1049`). `cluster_unit`별 hit·miss counter를 `/metrics`에 낸다.
  **이득은 zoom ≤ 10의 반복 요청에 한정된다** — zoom 11~13은 bbox가 5자리라 사실상 사용자마다 다른
  키이고, PinVi의 기본 화면(zoom 12)이 여기에 든다(F-04).
- **의존**: `T-READ-PIN-06`의 zoom 분포. zoom ≤ 10 요청이 in-bounds의 10% 미만이면 하지 않고 닫는다.
- **배포 단위**: PinVi 회전.
- **해제 조건**: ① 같은 키 두 요청이 Map을 한 번 부른다(동시·연속 모두). ② 인자 일곱 가지 중 하나라도
  다르면 다른 키다(인자마다 시험). ③ 60초 뒤 다시 부른다. ④ Map 실패와 `mode == "items"` 응답은
  캐시하지 않는다. ⑤ 항목 수·바이트 상한이 있다. ⑥ 배포 7일 뒤 hit 비율이 **모든 `cluster_unit`에서 20%
  미만이면 TTL을 0으로 두고 닫는다.**
- **검증**: 단위 시험, 운영 counter.
- **위험·되돌림**: 적재 직후 60초 동안 묵은 개수. bbox를 서버가 맞추면 가장자리 군집의 개수가 요청한
  bbox와 조금 달라진다. 되돌림은 TTL 0.

#### T-READ-PIN-07 — 통합 검색의 바깥 호출을 함께 기다린다 (PinVi)

- **변경**: 통합 검색은 Map 검색과 geo 주소 검색(odroid, 3초 예산)을 함께 기다린 뒤
  (`app/api/v1/search.py:53,234`), 내부 결과가 문턱 아래면 Kakao를 부르고 **그 다음에** Naver를 부른다
  (`search.py:244-290`). Kakao와 Naver를 `asyncio.gather`로 함께 기다린다(둘은 서로 독립이다).
  `T-READ-PIN-06`의 집계에서 검색 한 번에서 geo가 차지하는 시간을 따로 적는다.
- **의존**: `T-READ-PIN-06`(geo·외부 호출의 몫). 두 외부 호출이 함께 나가는 검색이 드물면 하지 않고 닫는다.
- **배포 단위**: PinVi 회전.
- **해제 조건**: ① 두 외부 호출에 각각 지연 1초를 넣은 시험에서 그 구간이 약 1초다(지금은 약 2초).
  ② 한쪽 실패가 다른 쪽 결과를 지우지 않는다(`degraded` 표시는 종전과 같다). ③ 결과 순서가 종전과 같다.
- **검증**: 단위 시험.
- **위험·되돌림**: 낮다. 외부 API 호출 수는 같다(순서만 바뀐다).

#### T-READ-MGR-02 — 세 서비스의 지표를 긁는다 (Manager)

- **변경**: `config/prometheus/prometheus.yml`은 **손으로 고치지 않는 파생 파일**이다 —
  `config/docker-targets.yml`의 `metrics_path`에서 `backend/src/kor_travel_docker_manager/services/
  prometheus_targets.py`가 만들고 `backend/tests/test_prometheus_targets_are_derived.py`가 대조한다.
  ① `config/docker-targets.yml`의 `kor-travel-map-api`·`pinvi-api` 항목에 `metrics_path`를 더한다. ② Map의
  운영 `/metrics`는 bearer token이 필요한데(`MAP:api/auth.py:962-1003`) 생성기는 인증을 낼 줄 모른다.
  registry와 생성기에 **일반적인 선택 필드** `metrics_auth: {type: bearer, credentials_file: …}`를 더한다
  (Map 전용 분기를 두지 않는다). token secret을 Prometheus 컨테이너에 mount한다(`T-READ-MGR-03`이 Map에
  넣은 것과 같은 값). ③ weather는 이미 자기 Prometheus가 있다(`docker-compose.yml:3435`) — 그것을 쓰거나
  같은 `metrics_auth`로 중앙에 더한다(고른 쪽을 적는다). ④ 파생 파일을 다시 만들고 시험을 돌린다.
  ⑤ route별 p95·5xx 비율 패널과 in-bounds 503 비율 경보를 `config/grafana/provisioning` 아래에 둔다.
- **의존**: `T-READ-02` 운영 반영(pool 지표), `T-READ-MGR-03`(지표 켜기·token).
- **배포 단위**: Manager 설치 + Prometheus·Grafana 재생성.
- **해제 조건**: ① Prometheus에서 Map·PinVi(·weather)의 route별 시간 histogram이 조회된다. ② 파생 파일
  시험이 초록이다. ③ token이 `prometheus.yml`·repo·로그에 평문으로 없다. ④ 패널 주소가 `docs/`에 있다.
- **검증**: scrape target `up`, 질의 한 번, 시험.
- **위험·되돌림**: 생성기 변경이 다른 job의 출력을 바꾸지 않는지 파생 시험이 본다. 되돌림은 registry
  항목 제거 + 재생성.

### 8.5 2단계

#### T-READ-MGR-04 — n150 공용 PG의 메모리·I/O 설정을 다시 잡는다 (Manager)

- **변경**: ① `pg_buffercache`로 무엇이 버퍼를 차지하는지 먼저 본다(확장은 `T-READ-MGR-01`과 같은 init
  경로로 만든다). ② 그 결과로 `shared_buffers`(지금 1 GB), `effective_cache_size`(1.5 GB),
  `effective_io_concurrency`(1)의 새 값을 제안한다. 셋 다 이미 `${KTDM_PG_…}` 변수라
  (`docker-compose.yml:300-322`) n150의 root `.env`만 바꾼다 — compose는 고치지 않는다. [실측] n150은
  PostgreSQL 18.6이고 `io_method`는 `worker`(3개)다 — PG18에서는 `effective_io_concurrency`의 뜻과 기본값이
  16까지와 다르므로 PG18 문서 기준으로 값을 고른다. **값은 소유자가 승인하고, 재생성 한 번에 값 하나만
  바꾼다.**
- **의존**: `T-READ-MGR-01`(전후 비교에 `pg_stat_statements`·I/O 시간이 필요하다), `T-READ-01`.
- **배포 단위**: 공용 PG 재생성(창). `T-READ-MGR-01`과 같은 창에 묶을 수 있다.
- **해제 조건**: ① 변경 전후 같은 길이 구간의 `pg_stat_io` eviction·읽기 수와 `T-READ-01` 수치를 표로
  적는다. ② 호스트 swap 사용이 늘지 않는다. ③ 다른 tenant(PinVi·Dagster·concierge)의 health가 초록이다.
  ④ 나아지지 않은 값은 되돌렸다.
- **검증**: 위 표.
- **위험·되돌림**: 재생성은 전 서비스 순단이다. 메모리를 PG에 더 주면 페이지 캐시와 다른 컨테이너가 준다.
  되돌림은 `.env` 원복 + 재생성.

#### T-READ-WEA-02 — export가 304를 싸게 내고 페이지 고정 비용을 줄인다 (weather, `W-EXPORT-SLOW-20261108`에 얹는다)

- **변경**: ETag를 페이지를 만들기 전에 비교한다(`API/routers/service_exports.py:311-329`). cursor
  페이지마다 snapshot 행 전체(manifest 포함)를 읽는 것과 health 묶음을 다시 만드는 것을 snapshot당
  60초 재사용한다(재확인 안 함: `SRC/export_snapshots.py:823-829,967-1085`). 서버가 페이지당 읽는 scope
  수에 상한을 둔다(`limit`이 5000이어도 한 요청이 artifact 전부를 읽지 않게).
- **의존**: `T-READ-WEA-01`(단계별 지표). weather P0-A 설계와 겹치는 부분은 그 설계가 우선한다.
- **배포 단위**: weather 배포.
- **해제 조건**: ① 내용이 같은 재요청의 304가 artifact를 읽지 않는다(읽기 계수 시험). ② cursor 페이지의
  고정 비용이 페이지 크기 200과 2000에서 같은 자릿수다. ③ 한 요청이 읽는 artifact 수가 상한 이하다.
- **검증**: `tests/test_export_read_cost.py` 계열에 시험 추가.
- **위험·되돌림**: 예보 ETag의 정의가 출력 기반이라 manifest 기반으로 바꿔야 한다 — 동등성 시험.

#### T-READ-WEA-04 — 특보 최신성 조회가 표 크기와 함께 느려지지 않게 한다 (weather)

- **변경**: `read_alert_events`는 `weather_sync_runs`에 문장 세 개를 보낸다
  (`src/kortravelweather/alert_event_store.py:160-187`) — 최신 run(`started_at DESC`), 최신 성공
  (`finished_at DESC`), 성공들의 `min(started_at)`. 지금 있는 색인은 `ix_weather_sync_runs_started`뿐이다.
  세 문장을 모두 받으려면 색인 셋이 필요하다 — 색인을 더할지, 세 값을 run 종료 때 작은 상태 행에 적어
  두고 읽을지를 측정으로 정한다.
- **의존**: `T-READ-WEA-01`의 지표. **`/v1/weather/alert-events`의 p95가 300 ms를 넘거나 세 문장 중 하나라도
  `weather_sync_runs`를 Seq Scan할 때만** 진행한다. 아니면 그 수치로 닫는다.
- **배포 단위**: weather 배포(migration).
- **해제 조건**: 세 문장 모두 EXPLAIN에서 표 전체를 훑지 않고, 표가 10배 커져도 같은 계획이다(시험).
- **검증**: 계획 시험(`tests/test_location_catalog_index.py`와 같은 형식), 배포 뒤 지표 전후.
- **위험·되돌림**: 색인 셋은 run마다의 쓰기 비용을 늘린다. 되돌림은 색인 삭제.

#### T-READ-TRN-02 — 여러 종류를 함께 받는 `features/places`의 비용을 줄인다 (transport)

- **변경**: transport는 이 주제를 이미 두 번 돌았다 — 5,000곳 지도의 profile(`T-READ-MAX-01`~`03`, 완료)과
  유가 한 종류 지도의 단일 JSON 질의(`docs/reports/2026-11-08-large-fuel-map.md`). 그 범위 밖에 남은 것이
  **여러 종류를 함께 받는 요청**이다 — 종류마다 `COUNT(*)` 뒤 `SELECT`(`main.py:1655-1660` 계열),
  `include_sources`(기본 참)의 종류별 `SELECT DISTINCT source`(`main.py:1787-1791`), `raw_item_json` 전체를
  ORM 행으로 읽는 것. `COUNT(*)`를 `limit+1` 또는 창 함수로, source 목록을 프로세스에 두거나 기본을
  거짓으로, **응답이 쓰는 JSON 키만 SQL에서 뽑는다** — 철도역 `facilities`(`main.py:1667`), 항구·
  버스터미널의 `_manual_location.revision`(`main.py:1691,1763`). 열을 통째로 빼면 이 필드들이 사라진다.
  열린 backlog의 "저장 데이터 API 1초 목표"(`docs/tasks.md:428`)와 **한 작업으로 합친다.**
- **의존**: `T-READ-TRN-01`(전후 문장 수·CPU).
- **배포 단위**: transport 배포.
- **해제 조건**: ① 전 종류 요청의 문장 수가 10개 이하다. ② **요청당 프로세스 CPU 시간**을 전후로 적었다
  (SQL 문장 수만 줄고 CPU가 그대로면 이득이 없다). ③ `kind_totals`·`truncated`의 의미가 같다(또는 계약
  변경을 관리 화면과 함께 고친다). ④ 응답 본문의 항목이 같다.
- **검증**: 시험, benchmark.
- **위험·되돌림**: `kind_totals`가 정확한 총계가 아니게 될 수 있다 — 계약으로 정한다.

#### T-READ-TRN-04 — 주차 이력 캐시 재구성을 읽기 프로세스 밖으로 (transport)

- **변경**: 30일치 재조회·압축(`services/parking_history_cache.py`)을 수집 쪽(Dagster)이 만들고 API는
  결과만 읽거나, 바뀐 부분만 더한다.
- **의존**: `T-READ-TRN-01`(재구성 중 다른 요청의 지연을 먼저 잰다). 재구성 중 작은 읽기의 p95가
  재구성이 없을 때의 2배 미만이면 하지 않고 닫는다.
- **배포 단위**: transport 배포.
- **해제 조건**: 재구성 중 `/health`와 작은 읽기의 p95가 재구성이 없을 때와 같은 자릿수다.
- **검증**: `T-READ-TRN-01`의 요청 시간 로그로 재구성 구간과 그 밖을 비교, `scripts/benchmark-db-reads.py`.
- **위험·되돌림**: 30초 신선도 계약(`docs/architecture/performance.md`). 메모리 한도 512 MB.

### 8.6 3단계 — `T-READ-01` 보고서 뒤

#### T-READ-05 — 지역 검색 전처리를 작은 표 조회로 바꾼다 (Map)

- **변경**: 다음 빈 번호의 migration으로 `feature.search_region_index`(`sigungu_code` PK, `sido_name`,
  `sigungu_name`, `public_rows`, `refreshed_at`)를 만든다. 이름은 **표본 8행이 아니라 그 시군구 공개 행
  전체의 최빈값**으로 정한다(지금의 표본은 `ORDER BY` 없는 `LIMIT 8`이라 결정적이지 않다 — F-07).
  채우기는 검색 인지도와 같은 층을 따른다 — infra 함수는 `src/kortravelmap/infra/search_prominence_repo.py`
  옆에, client 메서드는 `refresh_search_prominence` 옆에(`src/kortravelmap/client/__init__.py:1777-1784`),
  Dagster `consistency_dedup_refresh` job이 그 client 메서드를 부른다
  (`packages/kor-travel-map-dagster/…/maintenance.py:624`). `repo`의 `_resolve_search_region`과
  `_search_region_arms`는 표가 채워져 있고 `refreshed_at`이 7일 안이면 표를 읽고, 아니면 지금의 두 질의로
  떨어진다. `tests/integration/perf_gate.py`의 `HOT_QUERIES`에 새 조회를 더한다.
- **의존**: `T-READ-01`(전처리 두 질의의 시간), `T-READ-08`(all-visible이 오르면 행 수 세기의 heap 읽기가
  줄어 이 작업의 이득이 준다 — 08 뒤의 수치로 판정한다). 전처리 두 질의의 합이 검색 시간의 5% 미만이면
  **채택하지 않고 닫는다**(판정 방식은 §8.1).
- **배포 단위**: Map 회전(spec 불변, migration).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-05` 절(원장이 소유한다).
- **검증**: 통합 시험, tier-1 gate, 배포 뒤 `consistency_dedup_refresh` 한 번 뒤 표 행 수를 journal에 적는다.
- **위험·되돌림**: ① 새 시군구 코드는 다음 refresh까지 지역으로 해석되지 않는다. ② refresh는 하루 한 번
  schedule(`consistency_dedup_refresh_daily_schedule`, `maintenance.py:934-940`)에 달려 있다 — 운영에서 그
  job이 실제로 도는지는 확인하지 않았다. 돌지 않으면 표가 묵는다(7일 fallback이 막는다). ③ `public_rows`가
  하루 묵으면 문턱 3만 근처의 지역은 좁음/넓음 판정이 달라져 후보 팔이 바뀔 수 있다(`repo:7653-7670`).
  ④ 이름을 최빈값으로 바꾸면 표본 8행이 고르던 이름과 다를 수 있다. 되돌림은 코드 revert(표는 무해).

#### T-READ-06 — 검색 순위의 비교 키를 미리 계산한다 (Map, 측정으로 채택 여부를 정한다)

- **변경**: `T-READ-01`의 "빼고 재는" 측정에서 이름 정규화 단계(`compacted`·`hits`의 식)가 지역 검색 본
  질의 시간의 30% 이상이면 진행한다. 검색 인지도 표와 같은 방식으로 `feature.feature_search_keys`
  (`feature_id` PK, 보이는 이름의 비교 키·tail·끝 괄호 변형 셋·분류 그룹·접기 키)를 두고 같은 refresh가
  채운다. `repo`의 `_feature_search_score_cte`는 표를 LEFT JOIN해 값이 있으면 쓰고 없으면 지금의 식으로
  계산한다(`COALESCE`). 순위 식·자리·cursor는 바꾸지 않는다. **검색 평가 묶음을 파일로 고정한다** —
  2026-11-12 평가에 쓴 검색어는 저장소에 파일로 남아 있지 않다(journal은 작업만 적는다).
  `tests/integration/data/search_eval_queries.txt`에 40개 이상(#1459 목록, 순위 회귀 시험의 검색어, 지역
  검색 10개 이상)을 둔다.
- **의존**: `T-READ-01`, `T-READ-05`(같은 파일). 30% 미만이면 **채택하지 않고 닫고**, 시간을 쓰는 단계를
  보고서에 적어 새 작업으로 연다.
- **배포 단위**: Map 회전(spec 불변, migration).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-06` 절(원장이 소유한다).
- **검증**: 통합 시험, tier-1 gate, tier-2 harness 전후(`jit=off`).
- **위험·되돌림**: 순위가 조용히 달라지는 것 — 해제 조건의 순서 비교가 막는다. 이름·분류가 바뀐 행은
  refresh 전까지 옛 키로 순위가 매겨진다(소유자 결정 사항). 표 하나(약 40만 행)의 쓰기 비용은 tier-3
  측정(`performance.md` §8.3)으로 PR에 붙인다. 되돌림은 코드 revert.

#### T-READ-07 — `feature.features`의 쓰지 않는 색인을 정리하고 HOT 갱신을 되살린다 (Map, 측정으로 정한다)

- **변경**: ① 읽기 전용 `scripts/index_usage_snapshot.py`를 더한다 — `pg_stat_user_indexes`의
  `idx_scan`·`idx_tup_read`를 `pg_postmaster_start_time()`·`pg_stat_database.stats_reset`과 함께 JSON으로
  낸다. **두 번 찍는다**(첫날과 14일 뒤). 둘 사이에 기동 시각이나 reset이 바뀌었으면 그 차이는 버리고
  창을 다시 시작한다(매일 도는 장치는 없다). ② §4.1 표의 색인마다 읽는 코드 경로를 찾아 적는다(관리자
  목록 정렬·검색 `#1475`, 공개 목록 keyset). ③ 14일 동안 탐색 0이고 읽는 경로가 없거나 다른 색인으로
  대체되는 것만 다음 빈 번호의 migration으로 지운다. `idx_features_updated_keyset`은
  `infra/prewarm.py:33-41`의 `DEFAULT_HOT_RELATIONS`에 들어 있으므로 지우면 그 목록에서도 뺀다.
  `idx_features_coord_5179_gist`는 대상이 아니다. ④ HOT 갱신에는 색인 정리만으로 부족하다 — page에 빈
  자리가 있어야 한다. 표는 fillfactor 100이다. `ALTER TABLE … SET (fillfactor = 90)`(새 page에만 적용)을
  함께 넣고, 적재 한 번 뒤 `n_tup_hot_upd`를 잰다.
- **의존**: `T-READ-01`, `T-READ-08`, 관측 14일.
- **배포 단위**: Map 회전(spec 불변, migration).
- **해제 조건**: `docs/tasks-acceptance.md`의 `T-READ-07` 절(원장이 소유한다).
- **검증**: 통합 시험, n150 일회용 DB에서 재적재 전후 측정.
- **위험·되돌림**: 드물게 쓰는 관리자 질의가 느려진다 — downgrade가 색인을 다시 만든다(운영에서는
  `CREATE INDEX CONCURRENTLY`, `docs/runbooks/invalid-index-recovery.md`). fillfactor 90은 표를 약 10%
  키운다.

## 9. 확인하지 못한 것

1. 조용한 호스트에서의 모든 지연 수치(§2.5). 이 문서의 시간 수치는 측정 창의 것이거나 문서 주장이다.
   2026-11-17 05:14Z까지 e2e가 끝나지 않아 기준선과 `app.api_call_log` 전수 집계를 하지 않았다(그 표는
   planner 통계 표본만 읽었다).
2. in-bounds 503 15건의 원인(Map 지연 / 배포 중 재기동 / PinVi의 상한·회로) — `T-READ-PIN-06`.
3. in-bounds 부하의 정체(저배율 전국 집계 / 기본 화면의 읍면동 집계) — `T-READ-PIN-06`.
4. `GET /trips/{trip_id}` 평균 9초의 구성, PinVi 요청당 비용의 구간별 시간 — `T-READ-PIN-05`·`06`,
   `T-READ-PIN-03` ①.
5. F-06이 운영에서 실제로 일어나는지(교통 반경 route는 측정 창에 호출이 없었다).
6. 운영 컨테이너의 코드가 §2.2의 commit과 같은지.
7. "grid-projection" 보류 변경 — Map·weather의 main 문서, 브랜치 이름, PR 제목·본문 검색에서 그 이름을
   찾지 못했다. 예보 artifact를 위치가 아니라 KMA 격자(약 1,076개) 단위로 읽어 위치에 투영하는 안으로
   짐작하지만 근거 문서가 없다. 아는 사람이 weather `docs/tasks.md`에 적어야 한다.
8. odroid의 PG 설정·major·통계(접속하지 않았다), odroid 부하의 지속성, NVMe를 채운 것이 무엇인지.
9. subtype PK 탐색 89만~174만 회와 `features` seq scan 140회(2,380만 행)를 내는 질의가 무엇인지.
10. 디스크 쓰기의 주체별·DB별 배분, Valkey가 약 304초마다 저장하는 이유 — `T-READ-MGR-06`.
11. 운영에서 `consistency_dedup_refresh`가 실제로 도는지(`T-READ-05`·`06`의 표가 그 job에 달려 있다).
12. 실행해 봐야 아는 것 — 취소된 pool 체크아웃이 연결을 흘리는지, 연결이 끊긴 요청의 handler가 계속
    도는지. `T-READ-03`의 시험이 확인한다.
13. weather·transport·PinVi 인용 중 "(재확인 안 함)"으로 적은 줄.
14. PinVi → 브라우저·앱 구간의 압축·캐시(Cloudflare·nginx), 두 Next.js UI의 메모리와 SSR 읽기 경로.
