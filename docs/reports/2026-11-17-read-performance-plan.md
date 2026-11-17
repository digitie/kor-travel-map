# 읽기 성능 개선 계획 — Map·weather·transport (2026-11-17)

소유자 요청(2026-11-17)으로 세 서비스(`kor-travel-map`·`kor-travel-weather`·`kor-travel-transport`)의
읽기 경로를 코드와 운영 관측으로 검토하고 개선안을 정리한다. 다른 에이전트가 이 문서만 읽고 구현을
시작하므로 마지막 절(§8)이 작업 목록이다.

- 상태: **1차 초안**(적대 리뷰 2회 뒤 고친다). 이 문서를 쓰는 동안 코드·설정·운영을 바꾸지 않았다.
- Map 작업의 원장은 [`docs/tasks.md`](../tasks.md)(`T-READ-01`~`07`)와
  [`docs/tasks-acceptance.md`](../tasks-acceptance.md) §T-READ다. 다른 저장소 작업은 이 문서가 정본이고
  각 저장소 `docs/tasks.md`에는 이 문서를 가리키는 한 줄만 둔다.

## 1. 결론 먼저

1. **측정 창에서 지연의 가장 큰 몫은 SQL 모양이 아니라 호스트 정지였다.** n150의 디스크 압력(PSI io
   `some` avg60 29~76%)이 높았고, 상류 호출도 DB 조회도 없는 PinVi 핸들러가 평균 1.63초였다. Map API
   프로세스는 메모리의 약 92%가 swap에 있었다(§4.1, F-01·F-02).
2. **운영에서 읽기 지연을 볼 방법이 없다.** Map API 지표는 꺼져 있고, 요청 시간이 남는 로그가 없고,
   PostgreSQL 느린 질의 로그와 `pg_stat_statements`도 없다. 그래서 아래 발견 대부분이 "어느 질의가
   얼마나"를 말하지 못한다(F-03).
3. **PinVi `GET /features/in-bounds`의 39%(38건 중 15건)가 503이었다**(측정 창, PinVi 지표). 같은 기간
   bbox 색인 탐색 한 번이 평균 11.7만 색인 행을 읽었다 — 저배율 전국 집계가 읽기 부하의 대부분이다
   (F-04).
4. **읽기 요청에 시간 상한이 없다.** PinVi가 5초에 포기해도 Map의 SQL은 끝까지 돌고 연결을 쥔다.
   연결 풀은 15개이고 대기 상한은 30초(SQLAlchemy 기본값)다(F-05).
5. **PinVi의 여행 지도 교통 조회는 호출 수가 동시 호출 상한을 넘는다**(코드 추론). 기준 장소가 3곳
   이상이면 레이어가 통째로 `unavailable`이 될 수 있다. 한 번에 여러 점을 받는 Map 조회가 없어서다
   (F-06).
6. **검색의 지역 경로("부산 맛집")가 가장 느린 정상 경로다**(소유자 실측 0.6~1.1초). 후보 전부가
   정규식·창 함수 단계를 지나고, 낱말이 둘 이상인 검색마다 전처리 질의 두 개가 더 붙는다(F-07·F-08).
7. **odroid는 측정 시점에 CPU가 포화였고(실행 대기 11~27, idle 0%), PG 데이터가 있는 NVMe에 남은
   공간이 1.9 GB였다.** 뒤쪽은 읽기 속도 이전에 가용성 문제다(F-09·F-10).
8. weather·transport 자체 REST는 **PinVi 사용자 경로에 거의 없다.** 운영 PinVi는 날씨·교통을 Map의
   Valkey 표면으로 읽는다. 두 서비스의 읽기 비용은 Map 적재의 신선도와 odroid 부하, 그리고 각자의
   관리 화면에 걸린다(§3.1). weather는 자체 개선 설계가 이미 있어 그것을 따른다(§3.4).

순서는 **보이게 만들기 → 호스트·프로세스 보호 → 시간 상한 → 호출 수 줄이기 → 측정으로 정하는 SQL
개선**이다(§6).

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
(`/root/cat10.log`에 `CAT10_ALL_DONE` 0건). 그래서 n150에는 카탈로그 조회·`/proc` 읽기·PinVi의
공개 `/metrics` 한 번·`/health` curl만 했다. `EXPLAIN ANALYZE`와 부하 시험은 하지 않았다.

DB는 Map API 컨테이너의 DSN을 그 자리에서 유도해 읽기 전용 transaction(`statement_timeout` 8초)으로 붙었고
DSN·key·token은 출력하지 않았다. n150 `/tmp`에 둔 조사용 임시 파일은 지웠다.

PostgreSQL 누적 통계의 창은 길어야 postmaster 기동(2026-11-13 12:26Z) 이후 3.6일이고,
`pg_stat_bgwriter.stats_reset`이 2026-11-15 05:21Z라 더 짧을 수 있다. 이 창에는 e2e와 배포가 들어 있다.

### 2.5 측정하지 못한 것

- Map 공개 endpoint의 HTTP 지연 분포(지표가 꺼져 있다 — F-03).
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
Map Dagster(n150) ──▶ weather·transport /v1/service/exports/* (odroid) ──▶ Map Valkey 세대 교체
```

- [실측] 운영 PinVi는 `PINVI_KOR_TRAVEL_MAP_TRANSPORT_ENABLED=true`,
  `PINVI_KOR_TRAVEL_MAP_WEATHER_ENABLED=true`다. Map 주소는 `http://127.0.0.1:12701`, weather 직접
  주소는 `http://192.168.1.13:12201`이다.
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
| `POST /v1/features/batch` | PinVi 여행 보기 | `unnest(ids)` 한 문장(`repo:1265-1300`) | 200건 |
| `GET /v1/features/nearby` | PinVi 주변 | `coord_5179` GiST `ST_DWithin`(`repo:8029` 이하) | 500건 |
| `GET /v1/service/transport/{dataset}` | PinVi 교통 레이어·여행 반경 | Valkey 포인터 → `GEOSEARCH` → `HMGET`(`MAP:src/kortravelmap/infra/valkey_state.py:697-760`) | 500건, 반경 50 km |
| `/v1/service/weather/*` | PinVi 날씨 카드·마커 | Valkey `read_many`(왕복 2번, `valkey_state.py:785-830`) | batch 50곳 |

Map의 SQL은 이미 여러 번 고쳐졌다 — bbox 술어는 변환 없이 GiST를 타고(ADR-012), 저배율 집계는 #1455로
두 팔을 나눴고, 검색은 JIT를 껐다(`repo:7783-7786`). 그래서 이 계획은 "색인 하나 더"가 아니라
**구조와 운영 조건**을 먼저 본다.

### 3.3 PinVi가 Map을 부르는 방식

[추론] 전부 `PIN:` 코드에서 읽었다.

- Map client는 프로세스당 `httpx.AsyncClient` 하나, 전체 timeout 5초
  (`app/clients/kor_travel_map.py:1245-1256`, `app/core/config.py:810`). 재시도는 연결 실패·5xx에만
  3번이고 `ReadTimeout`은 다시 보내지 않는다(`kor_travel_map.py:64-73` — 주석이 "#702 운영 기록: 같은
  전국 bbox가 5초 timeout ×3"을 적는다).
- 범위별 동시 호출 상한(대기열 없음, 차면 바로 거부): features 10·viewport 4·transport 2·weather 2·
  festivals 4(`app/core/config.py:825-828`, `kor_travel_map.py:481-488`). [실측] 운영 env에 이 값을
  바꾸는 변수는 없다.
- 회로: 범위마다 연속 3번 실패하면 120초 열린다(`app/clients/_resilience.py:22,52`).
- 지도 이동 한 번(웹, 250 ms debounce)이 PinVi 요청을 최대 4개 낸다 — in-bounds(기본 500건),
  날씨 마커(zoom ≥8), geometry용 in-bounds 한 번 더, 교통 레이어. Map 읽기로는 최대 5번이다
  (`apps/web/components/map/FeatureMapView.tsx:79`, 나머지 재확인 안 함).
- 여행 지도의 교통 반경 조회는 기준 장소(최대 60곳)를 2 km로 묶은 중심마다 Map을 부른다 — 레이어
  2개 × 중심 수, 레이어당 동시 6개(`app/services/transport_layers.py:204-220,249-264`).
- 여행 보기는 Feature batch를 받은 **뒤에** 날씨를 받는다(`app/services/trip_view_builder.py:213,278`).
- 서버 쪽 캐시: Feature batch 60초(`config.py:1024-1026`), 축제 월별 300초, 특보 90초. viewport·검색·
  상세에는 없다.

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
3. 소비자 쪽에서 본 요청(§8.5).

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
| 디스크 압력 | PSI io `some` avg10 66~90%·avg60 29~76%, `full` avg10 63% | `/proc/pressure/io` 3회 |
| CPU·메모리 압력 | cpu `some` avg10 약 5%, memory 0% | `/proc/pressure/*` |
| 메모리 | 15,256 MB 중 used 5,131·buff/cache 7,674, swap 3,493 MB 사용, `swappiness` 10 | `free -m`, `/proc/sys/vm/swappiness` |
| Map API 프로세스 | VmRSS 14 MB, **VmSwap 154 MB**, uvicorn 1개 | `/proc/<pid>/status` |
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
| Map Valkey | 사용 70 MB, `HMGET` 158,629회 평균 77 µs, `HGETALL` 164,209회 평균 45 µs, RDB 저장 2,750회(가동 9.6일), 컨테이너 블록 쓰기 53.8 GB | `INFO`, `docker stats` |

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

탐색 12회 이하인 색인이 574 MB, 0회인 색인이 222 MB다. 통계 창이 3.6일 이하이고 관리 화면 사용이
적었을 수 있으므로 "쓰이지 않는다"의 증거로는 약하다(`T-READ-07`이 창을 늘려 다시 센다).

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
- `/auth/oauth/providers` 핸들러는 설정만 읽는다(`PIN:app/api/v1/oauth.py:142-150`). 미들웨어가 하는
  일은 확인하지 않았다.
- `/search`·`/transport/markers-near`는 이 창에 호출이 없었다. 동시 호출 상한 거부 counter
  (`pinvi_api_outbound_bulkhead_rejections_total`)에도 표본이 없었다.
- PinVi DB pool 대기는 84,758회 합계 5.7초다 — PinVi 쪽 pool은 원인이 아니다.

### 4.3 odroid (2026-11-17 03:38~03:46Z)

| 항목 | 값 | 방법 |
| --- | --- | --- |
| 부하 | load 11.2·11.6·12.8(4코어), `vmstat` 4초: 실행 대기 11~27, user 85~88%·sys 12~15%, **idle 0%, iowait 0%** | `uptime`, `vmstat 1 4` |
| CPU를 쓰는 쪽 | Dagster run 작업 프로세스(`multiprocessing.spawn`) 4개가 29~55%씩, daemon liveness-check, code server | `ps --sort=-pcpu` 한 번 |
| 메모리 | 7,675 MB 중 free 70 MB·buff/cache 3,226 MB, swap 1,843 MB 사용 | `free -m` |
| 저장소 | NVMe `/mnt/media` 938 GB 중 889 GB 사용, **남은 공간 1.9 GB**. PG 데이터가 여기 있다(`/mnt/media/kor-travel/pg/pgdata`). eMMC `/` 58 GB 중 11 GB 사용 | `df -h`, `docker inspect`(mount) |
| weather artifact | docker volume → eMMC(`/var/lib/docker/volumes/…weather-export-artifacts`) | `docker inspect` |
| 프로세스 | weather API uvicorn 1개 RSS 726 MB, transport backend uvicorn 1개 RSS 405 MB(compose 한도 512 MB — `TRN:docker-compose.shared.yml:216`) | `docker top` |
| n150 → weather `/health` | 336 ms·133 ms·9 ms(TCP 연결 187·114·1.6 ms) | curl 3회 |
| n150 → weather `/v1/weather/locations?limit=1` | 371 ms(`x-duration-ms` 176) | curl 1회 |

### 4.4 문서가 적어 둔 수치(다시 재지 않았다)

- Map 검색(소유자 2026-11-16): 일반 55~280 ms, 지역 경로 "부산 맛집" 0.6~1.1초(부하 없음).
- Map 저배율 집계(#1455, 2026-11-07): zoom 7 PinVi 기본 kind 2.9→0.25초, route·area 12~15→1.0~1.3초.
  "22초짜리 느린 요청 중에도 작은 요청은 0.010초"(`MAP:docs/journal.md:441-445`).
- Map 지역 검색(2026-11-09, 순위 2·3단계 이전): "부산 맛집" 0.16초, "경기 관광" 1.3초, "서울 맛집"
  5~6초(`repo:2700-2703`).
- weather export: current 첫 페이지 52.4초·304 재사용 173 ms
  (`WEA:docs/design/weather-performance-use-cases-20261109.md:51-55`).
- PinVi 주석: weather `/markers` p50 2.2초·p95 3.7초(`PIN:app/services/weather_markers_cache.py:3`,
  재확인 안 함).

## 5. 발견

각 항목: 근거 → 영향 → 확신도.

### F-01 측정 창의 지연은 호스트 정지가 지배했다

- [실측] PSI io `full` avg10 63%(§4.1) — 10초 중 6초 넘게 **모든** 작업이 디스크를 기다렸다.
- [실측] 상류도 DB도 부르지 않는 PinVi 핸들러가 평균 1.63초(§4.2).
- [실측] 공용 PG는 `shared_buffers` 1 GB로 Map DB 9.5 GB와 다른 tenant를 받고, 3.6일 동안 버퍼를
  1,060만 번 내보냈다. 같은 기간 컨테이너가 166 GB를 썼다(하루 약 46 GB).
- 영향: 이 조건에서는 어떤 SQL 개선도 묻힌다. 조용할 때의 수치(§4.4)와 측정 창의 수치(§4.2)가
  10배 이상 벌어진다.
- 확신도: "측정 창에 정지가 있었다"는 높다. "평소에도 그렇다"는 모른다 — 2026-11-16 e2e 때도 같은
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
- 영향: 다음 느려짐도 "어느 질의가, 언제부터"를 답하지 못한다. 이 문서의 F-04·F-07·F-08이 시간을
  못 적는 이유가 이것이다.
- 확신도: 높다.

### F-04 in-bounds의 부하는 저배율 전국 집계이고, 실패율이 높았다

- [실측] bbox GiST 탐색 5,166회가 색인 행 6.05억 개를 읽었다 — 탐색당 11.7만. 공개 행은 약 39.7만
  (planner 추정)이므로 평균적인 탐색이 전국의 30%를 읽는다. heap에서 가져온 행도 5.7억이다.
- [추론] zoom ≤13이면 집계 경로다. bbox 안 공개 행을 **전부** 읽어 `GROUP BY` 한다(`repo:1683-1766`).
  PinVi 웹의 기본 화면이 전국이면 이동마다 수십만 행을 읽는다.
- [실측] PinVi `GET /features/in-bounds` 38건 중 15건이 503(평균 3.99초)이었다. 200인 20건은 평균
  0.74초이고 0.1초 안에 끝난 것이 없다.
- [문서 주장] 조용할 때 같은 질의는 0.25초다(§4.4).
- 영향: 지도 첫 화면과 축소 화면. 디스크가 밀리면 5초 timeout → 503 → 연속 3번이면 PinVi 회로가
  120초 열려 viewport 범위 전체(주변·해수욕장·축제 마커 포함)가 멎는다(§3.3).
- 확신도: 부하 형태는 높다. 503의 원인이 Map 지연인지 배포 중 재기동인지는 가르지 못했다([실측] Map 로그의
  최근 20,000줄에 5xx는 없었다. [추론] PinVi가 timeout으로 끊은 요청은 Map 쪽에 200으로 남는다).
- 사전 집계(T-101)는 소유자가 2026-09-07에 제외했다. 이 계획은 그것을 다시 열지 않는다(§7).

### F-05 읽기 요청에 시간 상한이 없다

- [추론] API 엔진은 `jit=off`만 걸고 `statement_timeout`을 걸지 않는다(`MAP:api/db.py:57-62`). 저장소
  전체에서 읽기 경로의 `statement_timeout` 설정은 없다(검색 결과는 삭제 배치와 lock 대기뿐이다).
- [추론] PinVi는 5초에 끊는다. 핸들러는 연결이 끊겨도 취소되지 않으므로(코드에 disconnect 확인이
  없다 — 실행해 확인하지는 않았고 `T-READ-03`의 시험이 확인한다) SQL은 끝까지 돈다. PinVi 주석이 같은 현상을 기록한다("재시도는 같은 무거운 질의를 겹쳐 쌓을 뿐",
  `PIN:app/clients/kor_travel_map.py:66-69`).
- [추론] Map pool은 15개, 대기 상한은 SQLAlchemy 기본 30초다. PinVi의 PG를 쓰는 범위 상한 합은
  features 10 + viewport 4 + festivals 4 = 18이다. 느린 질의가 15개를 쥐면 다음 요청은 PinVi가 이미
  떠난 뒤까지 줄을 선다.
- 영향: 정지 구간에서 버려진 작업이 쌓여 회복을 늦춘다.
- 확신도: 설정은 높다. 운영에서 실제로 쌓였는지는 지표가 없어 모른다.

### F-06 PinVi 여행 교통 조회의 호출 수가 동시 호출 상한을 넘는다

- [추론] `transport` 범위 상한은 2이고 대기열이 없다 — 꽉 차면 호출하지 않고 `BULKHEAD_FULL`을 올린다
  (`PIN:app/clients/kor_travel_map.py:481-488`). 교통 wrapper는 이 범위를 쓴다
  (`PIN:app/clients/kor_travel_map_transport.py:116`).
- [추론] 반경 조회는 레이어마다 중심들을 동시 6개까지 보낸다(`transport_layers.py:216,249-263`).
  하나라도 실패하면 레이어 전체가 `unavailable`이다(`transport_layers.py:306-312`).
- 따라서 두 레이어를 켠 여행에서 2 km 넘게 떨어진 장소가 둘 이상이면 동시 호출이 4개 이상이 되어
  상한 2를 넘는다. 시험은 한 점 또는 가짜 client만 쓴다(`PIN:apps/api/tests/integration/
  test_transport_api.py:228-282`, `tests/unit/test_transport_layers.py:304-393`).
- [실측] 이 route는 측정 창에 호출이 없어 운영에서 확인하지 못했다.
- 영향: 여행 지도의 주유소·돌발 레이어가 비거나, 장소가 많으면 Map 호출이 최대 120번이다.
- 확신도: 중간~높음(코드상 분명하나 실행해 보지 않았다). 첫 작업이 재현 시험이다.

### F-07 낱말이 둘 이상인 검색마다 전처리 질의 두 개가 붙는다

- [추론] 낱말이 둘 이상이면 지역 표본 질의가 돈다 — 시군구 코드마다 색인 탐색으로 주소 이름 최대
  8행을 읽는 재귀 질의다(`repo:7584-7597`, `repo:2720-2755`). 지역으로 해석되면 지역 공개 행 수도 센다
  (`repo:7639-7653`, `repo:2706-2713`).
- [실측] `idx_features_sigungu` 탐색이 309,210회다. [추론] 재귀 질의 한 번이 코드 수(통계상 285)의
  두 배쯤 탐색하므로 검색 약 500번이면 이 수가 된다. 본 질의의 지역 팔과 행 수 세기도 이 색인을 타지만
  요청당 한두 번이다.
- [추론] 주소 JSON은 heap에 있어 검색 한 번에 heap 행을 최대 2,280개 읽는다. all-visible이 58%라 행 수
  세기도 heap을 본다.
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
- 영향: PinVi 통합 검색은 입력마다 Map을 부르고 캐시가 없다(§3.3). 상한은 5초다.
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
- 확신도: 높다. 무엇이 공간을 쓰는지는 보지 않았다(다른 팀 호스트).

### F-11 `feature.features`의 색인이 heap의 두 배이고 HOT 갱신이 0이다

- [실측] heap 379 MB, 색인 720 MB. 갱신 58,813건 중 HOT 0건. 거의 안 쓰인 색인 574 MB(§4.1).
- [추론] `updated_at`이 색인 두 개의 키라서 갱신이 `updated_at`을 바꾸는 한 HOT가 될 수 없다. 갱신마다
  색인 18개에 새 항목이 생긴다.
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

## 6. 개선안과 순위

이득·노력·위험은 상대값이다. "이득"은 근거가 실측인 것을 위에 둔다.

| 순위 | 안 | 이득 | 노력 | 위험 | 작업 |
| --- | --- | --- | --- | --- | --- |
| 1 | 운영 관측 켜기 — Map 지표·느린 요청 로그, PG 느린 질의 로그·`pg_stat_statements`·`track_io_timing`, scrape | 직접 이득 0, 나머지 전부의 전제 | 작음 | 낮음 | `T-READ-02`, `T-READ-MGR-01`·`02`, `T-READ-TRN-01` |
| 2 | 조용한 호스트의 기준선과 재측정 도구 | 전제 | 작음 | 낮음(읽기 전용) | `T-READ-01` |
| 3 | odroid NVMe 공간 확보 | 장애 예방 | 운영 | 낮음 | `T-READ-MGR-05` |
| 4 | API 프로세스를 swap에서 지키기 | 꼬리 지연(크기 미측정) | 작음 | 중간(한도가 작으면 OOM) | `T-READ-MGR-03` |
| 5 | 공개 읽기 시간 상한(문장 timeout·pool 대기 상한) | 정지 구간의 누적 방지 | 작음 | 낮음~중간 | `T-READ-03` |
| 6 | 교통 근처 조회를 한 번에(여러 점) + PinVi 팬아웃 수정 | Map 호출 최대 120 → 2, 레이어 실패 제거 | 중간 | 중간(service 계약 추가) | `T-READ-04`, `T-READ-PIN-01` |
| 7 | PinVi 저배율 집계 응답의 짧은 캐시·동일 요청 합치기 | 전국 집계 반복 제거(F-04) | 작음 | 낮음(60초 묵은 개수) | `T-READ-PIN-02` |
| 8 | PinVi 여행 보기에서 Feature와 날씨를 함께 기다리기 | 여행 보기 지연(평균 9초 중 몫은 미측정) | 작음 | 낮음 | `T-READ-PIN-03` |
| 9 | 공용 PG 메모리·I/O 설정 재산정(n150) | 버퍼 교체 감소(F-01) | 중간(전 tenant 재시작) | 중간 | `T-READ-MGR-04` |
| 10 | 지역 검색 전처리를 작은 표 조회로 | 검색당 색인 탐색 약 570회·heap 최대 2,280행 제거 | 중간(migration) | 낮음 | `T-READ-05` |
| 11 | 검색 비교 키 사전 계산 | 지역 경로 0.6~1.1초의 일부(측정 뒤 확정) | 큼 | 중간 | `T-READ-06` |
| 12 | `features` 색인 정리·HOT 회복 | 적재 I/O 감소 → 간접 | 중간 | 중간 | `T-READ-07` |
| 13 | weather·transport 내부 개선 | odroid 부하·Map 적재 신선도 | 저장소별 | 저장소별 | §8.5·§8.6 |

서비스 사이에 걸친 것.

- **timeout 맞추기**: Map 문장 상한(4.5초)은 PinVi의 5초보다 짧아야 한다. PinVi가 값을 바꾸면 Map
  설정도 따라 바꾼다(`T-READ-03` 본문에 적는다).
- **묶음 조회**: 교통 근처(`T-READ-04`). 날씨는 이미 묶음이다(`/locations/batch`).
- **캐시 헤더**: Map은 데이터 캐시를 두지 않는다(ADR-030). 호출자 캐시는 허용된다
  (`MAP:docs/architecture/performance.md:544-545`) — 그래서 저배율 캐시는 PinVi에 둔다. Map이 집계
  응답에 ETag를 달려면 값싼 데이터 버전이 필요한데 지금은 없다(§7).
- **관측**: 세 서비스 모두 `route·status·시간`을 같은 Prometheus에 모은다(`T-READ-MGR-02`).

## 7. 하지 않는 것·기각한 안

| 안 | 판단 | 이유 |
| --- | --- | --- |
| 저배율 집계 materialized view(T-101) | 다시 열지 않는다 | 소유자가 2026-09-07 제외했다. 재개 조건은 목표 SLO와 exact-viewport vs region-total 택일이다(`MAP:docs/tasks.md:126-130`). 이 계획은 그 판단에 쓸 실측(F-04)과 기준선(`T-READ-01`)만 낸다. |
| Map 안의 응답 캐시(프로세스·Valkey) | 기각 | ADR-030과 ADR-114가 금한다(Valkey는 PG 앞의 캐시가 아니다). 바꾸려면 ADR 개정이 먼저다. 같은 효과를 호출자 캐시(`T-READ-PIN-02`)로 얻는다. |
| Map uvicorn worker 늘리기 | 지금은 하지 않는다 | [실측] API CPU 0.15%, [문서 주장] 느린 요청 중에도 작은 요청은 0.010초다. 병목이 이벤트 루프가 아니다. worker를 늘리면 연결 수(15 → 30+)와 프로세스별 지표·key 캐시가 갈린다. `T-READ-02` 뒤 루프 지연이 보이면 다시 본다. |
| Map pool 늘리기 | 기각 | 느린 질의가 더 많이 동시에 돌 뿐이다. 디스크가 병목일 때 역효과다. 대기 상한을 줄이는 쪽을 택한다(`T-READ-03`). |
| PinVi timeout 늘리기 | 기각 | 실패를 늦출 뿐이고 버려진 질의가 더 오래 돈다. |
| 집계 응답 ETag(Map) | 보류 | 값싼 데이터 버전이 없어 304를 내려면 집계를 다시 해야 한다. 적재가 올리는 세대 번호가 생기면 다시 본다. |
| MVT 타일·범용 batch | 그대로 유예 | `MAP:docs/architecture/performance.md` §8.4의 판정과 조건을 그대로 둔다. |
| 읽기 전용 복제본·호스트 분리 | 범위 밖 | n150 한 대 전제(소유자). 효과는 크겠지만 이 계획의 작업으로 만들지 않는다. |
| 무중단 배포 | 범위 밖 | 배포 중 503은 인스턴스가 하나라 생긴다. PinVi의 짧은 캐시(`T-READ-PIN-02`)가 저배율 화면만 가린다. |
| gzip(Map API) | 지금은 하지 않는다 | 호출자가 loopback이다. 다른 호스트 소비자가 생기면 다시 본다. |
| 지도 행의 속성 하위 질의를 집합 조인으로 | 측정 뒤 | F-12. `T-READ-01` 계획에서 비중이 보이면 작업으로 올린다. |
| weather에 Valkey·새 worker | weather 설계를 따른다 | `WEA:docs/design/weather-performance-use-cases-20261109.md` §6.2가 조건부로 둔다. |

## 8. 작업 목록

### 8.1 순서와 병렬

```
0단계 (서로 독립, 동시에)   T-READ-01  T-READ-02  T-READ-MGR-01  T-READ-MGR-05  T-READ-PIN-01(재현)  T-READ-TRN-01  T-READ-WEA-01
1단계 (동시에)             T-READ-MGR-02(← T-READ-02)  T-READ-MGR-03  T-READ-03  T-READ-04  T-READ-PIN-03
2단계                      T-READ-PIN-01(전환, ← T-READ-04)  T-READ-PIN-02  T-READ-MGR-04(← T-READ-MGR-01)
3단계 (← T-READ-01의 수치)  T-READ-05  T-READ-06  T-READ-07   ·  T-READ-WEA-02~04  ·  T-READ-TRN-02~04
```

- 같은 줄의 작업은 서로 파일이 겹치지 않는다. 예외: `T-READ-02`와 `T-READ-03`은 둘 다
  `api/db.py`를 고친다 — 늦게 여는 PR이 리베이스한다.
- 3단계는 `T-READ-01` 보고서가 머지된 뒤 시작한다. 수치가 기준에 못 미치면 **채택하지 않고 닫는
  것**도 완료다(각 작업의 해제 조건에 적었다).
- 운영 변경(설정·재시작·배포)은 소유자·배포 담당의 일이다. n150은 `~/preflight.sh` PASS 뒤에만,
  odroid는 Codex 담당이다.
- 해제 조건의 문턱(5%·30%·40%·4.5초·2초·한도 512 MB 등)은 **제안값**이다. 리뷰나 `T-READ-01`의 수치로
  바꿀 수 있고, 바꾸면 이 문서와 acceptance를 함께 고친다.

각 작업의 형식: **변경**(파일·함수) / **의존** / **해제 조건**(시험할 수 있는 것) / **검증** / **위험·되돌림**.

### 8.2 Map (`digitie/kor-travel-map`) — 원장 `docs/tasks.md`, 해제 조건 원장 `docs/tasks-acceptance.md` §T-READ

#### T-READ-01 — 조용한 호스트의 읽기 기준선과 재측정 도구

- **변경**: `scripts/perf_tier2_release_harness.py`의 대표 viewport에 (a) 지역 검색 두 개("부산 맛집"
  좁은 지역, "서울 맛집" 넓은 지역 — 전처리 질의 `_SEARCH_ALIAS_LOOKUP_SQL`·`_SEARCH_REGION_ENTRIES_SQL`·
  `_SEARCH_REGION_ROW_COUNT_SQL`을 각각 따로 잰다), (b) 시군구 집계(zoom 10), (c) 개별 행 500건(zoom 14
  서울), (d) 상세 1건을 더한다. 새 스크립트 `scripts/read_path_probe.py`가 운영 Map API에 PinVi와 같은
  모양의 HTTP 요청을 순서대로 보내 `meta.duration_ms`와 전체 시간을 모으고, 묶음마다
  `/proc/pressure/io`를 함께 적는다(스크립트는 호스트에서 돈다). 결과는
  `docs/reports/<날짜>-read-baseline.md`와 `.safe.json`.
- **의존**: 없음. 실행은 `CAT10_ALL_DONE` 뒤, `~/preflight.sh` PASS, 배포·적재가 없는 때.
- **해제 조건**: ① harness가 `--skip-seed`로 운영 DB에서 9개 viewport의 p50·p95·shared read blocks
  p95·응답 bytes를 낸다. ② 지역 검색은 CTE별 시간(`EXPLAIN (ANALYZE, BUFFERS)`의 노드 시간)을 표로
  적는다. ③ HTTP probe가 같은 9개를 30회씩 재고 PSI io `some` avg60을 함께 적는다. ④ 조용할 때
  (PSI io `some` avg60 < 5%)와 적재 중일 때 두 번 잰다. ⑤ 보고서가 F-04·F-07·F-08·F-12의 "모른다"를
  수치로 바꾼다.
- **검증**: 새 viewport의 단위·통합 시험(기존 harness 시험 형식), 보고서의 JSON이 `--check`로 재현된다.
- **위험·되돌림**: 읽기 전용이다. 문장마다 `statement_timeout` 30초를 건다. 전국 집계 30회가 수십 초
  CPU를 쓰므로 적재와 겹치지 않게 한다.

#### T-READ-02 — 요청·DB 지표를 운영에서 쓸 수 있게 하고 느린 요청을 로그에 남긴다

- **변경**: ① `api/prometheus.py`에 연결 풀 지표를 더한다 — 체크아웃 대기 histogram, 사용 중 연결
  gauge(`api/db.py`의 세션 의존성에서 잰다). ② 지표 flag와 **무관한** 느린 요청 로그를 `api/app.py`
  미들웨어에 더한다 — 요청 시간이 `KOR_TRAVEL_MAP_API_SLOW_REQUEST_LOG_MS`(기본 1000) 이상이면 route
  template·status·`duration_ms`·DB 문장 수·DB 시간 합·request id를 한 줄로 남긴다(query string·key·
  좌표는 남기지 않는다). DB 합계는 `api/db.py`의 cursor 이벤트에 요청별 contextvar 누산기를 달아 얻는다.
  ③ `api/settings.py`에 설정 추가, `docs/deploy.md`에 운영 값 안내.
- **의존**: 없음. 운영에서 지표를 켜고 긁는 것은 `T-READ-MGR-02`.
- **해제 조건**: ① 지표가 꺼져 있어도 느린 요청 로그가 남는다(시험: `pg_sleep`을 부르는 시험 전용
  route 또는 주입한 느린 질의). ② 로그 줄에 query string과 header 값이 없다(시험). ③ `/metrics`에 pool
  대기 histogram과 gauge가 나온다. ④ 기본 설정에서 요청당 추가 DB 왕복이 0이다(문장 수 시험).
  ⑤ 배포 뒤 운영 로그에서 1초 넘는 요청 줄을 확인해 journal에 적는다(배포 generation과 함께).
- **검증**: `packages/kor-travel-map-api/tests/`의 단위·통합 시험, OpenAPI drift 없음.
- **위험·되돌림**: 로그 양 — 문턱을 올리거나 0으로 끈다. label은 route template만 써 cardinality가
  늘지 않게 한다.

#### T-READ-03 — 공개 읽기에 시간 상한을 건다

- **변경**: ① `api/db.py`에 공개 읽기용 세션 의존성을 정리한다 — `get_read_snapshot_session`과
  새 `get_public_read_session`(in-bounds·bbox·nearby가 쓰던 `get_session` 자리)이 transaction 첫 문장으로
  `SET LOCAL statement_timeout`을 건다. 값은 `api/settings.py`의
  `public_read_statement_timeout_ms`(기본 4500, 0이면 끔). ② `make_async_engine`
  (`src/kortravelmap/infra/db.py:884`)에 `pool_timeout` 인자를 더하고 API 엔진은 2초를 준다. ③ `api/app.py`
  예외 처리: SQLSTATE `57014`(문장 취소)와 pool 대기 초과를 503 problem(`READ_TIMEOUT`·`POOL_BUSY`,
  `Retry-After: 1`)으로 바꾼다. ④ 적용 범위는 `/v1/features*`·`/v1/public/*`·`/v1/categories` 읽기다.
  admin·ops·쓰기 경로는 건드리지 않는다.
- **의존**: 없음(`T-READ-02`와 `api/db.py` 충돌만 조정).
- **해제 조건**: ① 상한 200 ms에서 `pg_sleep(1)`을 품은 읽기가 503 `READ_TIMEOUT`이고, 그 연결이 풀에
  돌아와 다음 질의가 성공한다(통합 시험). ② pool을 다 쓴 상태의 다음 요청이 약 2초 뒤 503
  `POOL_BUSY`다. ③ admin·ops route의 세션에는 상한이 걸리지 않는다(시험). ④ 상한 0이면 종전 동작과
  같다. ⑤ OpenAPI에 새 응답을 적어야 하면 user spec 변경으로 PinVi 재vendor를 같은 회전에 묶는다 —
  이미 있는 공통 503 problem을 쓰면 계약 변경이 없다(구현 PR이 어느 쪽인지 적는다).
- **검증**: 통합 시험(PostGIS), n150 CI-parity 4세션. 배포 뒤 `T-READ-02`의 로그로 503 `READ_TIMEOUT`
  건수를 일주일 본다.
- **위험·되돌림**: 조용할 때 1.0~1.3초인 route·area 전국 집계가 정지 구간에 4.5초를 넘으면 지금은
  "늦게 성공"하던 것이 "빨리 실패"가 된다 — PinVi는 어차피 5초에 버린다. Map 관리 화면처럼 더 오래
  기다리는 호출자가 있으면 그 경로를 범위에서 뺀다. 되돌림은 env 0.

#### T-READ-04 — 교통 근처 조회를 한 요청으로 받는다

- **변경**: `api/routers/service_transport.py`에 `POST /v1/service/transport/{dataset}/near-batch`
  (dataset은 `fuel-stations`·`highway-incidents`)를 더한다. 본문은 `points[]`(lon·lat, 최대 60)와
  `radius_m`(≤ 50,000)·`limit`(≤ 500)이다. 구현은 현재 세대를 한 번 읽고, 점마다 `GEOSEARCH`를 pipeline
  하나로 보내고(`src/kortravelmap/infra/valkey_state.py`에 `nearby_many` 추가), id 합집합을 `HMGET` 한
  번으로 읽는다. 응답 item은 기존 목록과 같은 모양에 가장 가까운 점까지의 거리를 붙인다. service
  OpenAPI와 ADR-114 "구현 설계 — 1단계" 표에 route를 더한다.
- **의존**: 없음. PinVi 전환은 `T-READ-PIN-01`.
- **해제 조건**: ① 점 60개 요청의 Valkey 왕복이 3번 이하다(가짜 client 계수 시험). ② 결과 집합이 점마다
  기존 `?lon&lat&radius_m` 조회를 부른 합집합과 같다(거리 포함, 통합 시험). ③ 세대 교체 중에도 한
  세대만 읽는다. ④ 상한(점 60·반경 50 km·limit 500)을 넘으면 422다. ⑤ Valkey 장애는 기존 route와 같은
  503이다. ⑥ service OpenAPI drift gate가 통과하고 PinVi 재vendor PR이 열린다.
- **검증**: 단위·통합 시험(Valkey), `scripts/read_path_probe.py`에 점 20개 요청을 더해 시간을 적는다.
- **위험·되돌림**: 추가 route라 기존 소비자에 영향이 없다. 큰 합집합의 응답 크기 — `limit`과
  `truncated`로 막는다. 되돌림은 route 제거(PinVi가 옛 경로로 돌아간 뒤).

#### T-READ-05 — 지역 검색 전처리를 작은 표 조회로 바꾼다

- **변경**: 다음 빈 번호의 migration으로 `feature.search_region_index`(`sigungu_code` PK, `sido_name`,
  `sigungu_name`, `public_rows`, `refreshed_at`)를 만든다. 채우기는 검색 인지도와 같은 자리다 —
  `src/kortravelmap/infra/search_prominence_repo.py`의 refresh 옆에 함수를 두고 Dagster
  `consistency_dedup_refresh` job(`packages/kor-travel-map-dagster/…/maintenance.py`)이 부른다.
  `repo`의 `_resolve_search_region`과 `_search_region_arms`는 표가 채워져 있으면 표를 읽고, 비어 있으면
  지금의 두 질의로 떨어진다. `tests/integration/perf_gate.py`의 `HOT_QUERIES`에 새 조회를 더한다.
- **의존**: `T-READ-01`(전처리 두 질의의 시간). 조용할 때와 적재 중 어느 쪽에서도 두 질의의 합이 검색
  시간의 5% 미만이면 **채택하지 않고 닫는다**.
- **해제 조건**: ① 같은 DB에서 표 경로와 종전 경로의 `split_region_query` 결과·선택되는 팔
  (`_SearchRegionArms`)이 검색어 묶음 전체에서 같다(통합 시험 — 묶음은 `tests/`의 지역 검색 사례를
  쓴다). ② 표 경로의 낱말 둘 검색은 `feature.features`를 전처리에서 읽지 않는다(EXPLAIN 시험).
  ③ 표가 비었을 때 종전과 같다. ④ refresh가 같은 run에서 두 번 돌아도 결과가 같다. ⑤ harness의
  지역 검색 수치를 전후로 보고서에 적는다.
- **검증**: 통합 시험, tier-1 gate, 배포 뒤 `consistency_dedup_refresh` 한 번 뒤 표 행 수(시군구 수)를
  journal에 적는다.
- **위험·되돌림**: 새 시군구 코드는 다음 refresh까지 지역으로 해석되지 않는다(일반 검색으로 동작).
  `public_rows`는 문턱 3만 판정에만 쓰여 하루 묵어도 순위는 같다. 되돌림은 코드 revert(표는 무해).

#### T-READ-06 — 검색 순위의 비교 키를 미리 계산한다 (측정으로 채택 여부를 정한다)

- **변경**: `T-READ-01`이 "이름 정규화 단계(`compacted`·`hits`)가 지역 검색 시간의 30% 이상"임을 보이면
  진행한다. 검색 인지도 표와 같은 방식으로 `feature.feature_search_keys`(`feature_id` PK, 보이는 이름의
  비교 키·tail·끝 괄호 변형 셋·분류 그룹·접기 키)를 두고 같은 refresh가 채운다. `repo`의
  `_feature_search_score_cte`는 표를 LEFT JOIN해 값이 있으면 쓰고 없으면 지금의 식으로 계산한다
  (`COALESCE`). 순위 식·자리·cursor는 바꾸지 않는다.
- **의존**: `T-READ-01`. 30% 미만이면 **채택하지 않고 닫고**, 시간을 쓰는 단계를 보고서에 적어 새
  작업으로 연다(후보: 유사도만 단계의 후보 줄이기 — cursor 계약이 걸려 별도 설계가 필요하다).
- **해제 조건**: ① 검색 평가 묶음(2026-11-12 평가에 쓴 검색어)에서 표 경로와 종전 경로의 결과
  `feature_id` 순서가 첫 3페이지까지 같다. ② 표에 없는 행(새 Feature)이 섞여도 같다. ③ 이름·분류가
  바뀐 행은 refresh 전까지 **옛 키로 순위가 매겨진다** — 이 묵은 값의 허용 여부를 소유자가 정하고
  acceptance에 적는다(허용하지 않으면 키를 `row_revision`과 함께 저장해 다르면 식으로 떨어진다).
  ④ harness의 "부산 맛집" p50이 기준선보다 40% 이상 준다. 못 미치면 revert하고 닫는다.
- **검증**: 통합 시험, tier-1 gate, tier-2 harness 전후.
- **위험·되돌림**: 순위가 조용히 달라지는 것 — ①②가 막는다. 표 하나(약 40만 행)의 쓰기 비용은
  tier-3 측정(`performance.md` §8.3)으로 PR에 붙인다. 되돌림은 코드 revert.

#### T-READ-07 — `feature.features`의 쓰지 않는 색인을 정리하고 HOT 갱신을 되살린다 (측정으로 정한다)

- **변경**: ① 14일 동안 `pg_stat_user_indexes`를 하루 한 번 적는다(`T-READ-MGR-01`의 통계 또는 읽기
  전용 스크립트 — PG 재기동으로 통계가 지워지면 그 사실을 함께 적는다). ② §4.1 표의 색인마다 읽는
  코드 경로를 찾아 적는다(관리자 목록 정렬·검색 `#1475`, 공개 목록 keyset). ③ 14일 동안 탐색 0이고
  읽는 경로가 없거나 다른 색인으로 대체되는 것만 다음 빈 번호의 migration으로 지운다. `updated_at`
  색인 두 개가 대상이 되면 HOT 갱신이 가능해진다 — 지운 뒤 적재 한 번의 `n_tup_hot_upd`를 잰다.
  `infra/prewarm.py`의 `DEFAULT_HOT_RELATIONS`에서 지운 이름을 뺀다.
- **의존**: `T-READ-01`, 관측 14일.
- **해제 조건**: ① 색인별 "읽는 경로 / 14일 탐색 수 / 판정" 표가 보고서에 있다. ② 지운 뒤 관리자
  Feature 목록·검색 e2e(D2)와 tier-1 gate가 통과한다. ③ tier-3 측정 — 같은 provider 재적재의 쓰기
  시간·WAL·색인 크기 전후를 PR에 붙인다. ④ 지울 것이 없으면 그 근거로 닫는다.
- **검증**: 통합 시험, n150 일회용 DB에서 재적재 전후 측정.
- **위험·되돌림**: 드물게 쓰는 관리자 질의가 느려진다 — downgrade가 색인을 다시 만든다(운영에서는
  `CREATE INDEX CONCURRENTLY`, `docs/runbooks/invalid-index-recovery.md`).

### 8.3 PinVi (`digitie/pinvi`) — 외부 추적

#### T-READ-PIN-01 — 여행 교통 반경 조회가 동시 호출 상한에 걸리지 않게 한다

- **변경**: ① 재현 시험 — 진짜 `KorTravelMapClient`(상한 2)에 가짜 transport를 붙이고 2 km 넘게 떨어진
  점 3개로 `fetch_near_layer`를 부르면 레이어가 `unavailable`이 되는지 확인한다
  (`apps/api/tests/unit/test_transport_layers.py`). ② 당장의 수정: `NEAR_CONCURRENCY`
  (`app/services/transport_layers.py:216`)를 범위 상한 이하로 묶고 두 레이어가 같은 상한을 나눠 쓰게 한다
  (거부가 아니라 기다린다). ③ `T-READ-04`가 배포되면 중심 묶음을 `near-batch` 한 번으로 바꾼다
  (`app/clients/kor_travel_map_transport.py`에 메서드 추가, service spec 재vendor).
- **의존**: ①②는 없음. ③은 `T-READ-04` 배포.
- **해제 조건**: ① 재현 시험이 수정 전 빨강, 수정 뒤 초록이다. ② 점 60개·레이어 2개 요청이 Map을
  레이어당 한 번(③ 뒤) 부른다(계수 시험). ③ 결과 집합이 종전과 같다(기존 반경 시험 유지).
  ④ 운영에서 `pinvi_api_outbound_bulkhead_rejections_total{scope="transport"}`가 늘지 않는다.
- **검증**: 단위·통합 시험, live e2e의 여행 지도 교통 레이어.
- **위험·되돌림**: ②는 기다리는 만큼 느려진다(레이어 상한 5초 안). ③은 Map이 옛 버전이면 404 →
  옛 경로로 떨어지게 한다.

#### T-READ-PIN-02 — 저배율 in-bounds 응답을 짧게 캐시하고 같은 요청을 합친다

- **변경**: `app/api/v1/features.py`의 in-bounds에서 Map이 집계 모드로 답한 응답(zoom ≤ 10 — 웹이 bbox를
  소수 2~3자리로 맞추는 구간, `apps/web/lib/featureBounds.ts:51-56`)을 `zoom·맞춘 bbox·kind·category·
  provider·attribute` 키로 60초 둔다. 같은 키의 진행 중 요청은 하나로 합친다(축제 월별 캐시와 같은
  방식, `app/clients/kor_travel_map.py:1022-1049`). 서버가 bbox를 같은 규칙으로 맞춘다.
- **의존**: 없음.
- **해제 조건**: ① 같은 키 두 요청이 Map을 한 번 부른다(동시·연속 모두). ② 60초 뒤 다시 부른다.
  ③ Map 실패는 캐시하지 않는다. ④ 개별 행 모드(zoom ≥ 14)와 geometry 요청은 캐시하지 않는다.
  ⑤ 항목 수·바이트 상한이 있다.
- **검증**: 단위 시험, 운영 Map 로그(`T-READ-02`)에서 전국 집계 건수가 주는지 본다.
- **위험·되돌림**: 적재 직후 60초 동안 묵은 개수. 웹이 이미 60초 캐시를 둔다. 되돌림은 TTL 0.

#### T-READ-PIN-03 — 여행 보기에서 Feature batch와 날씨를 함께 기다린다

- **변경**: `app/services/trip_view_builder.py:213`(Feature batch)과 `:278`(날씨)을 `asyncio.gather`로
  묶는다. 날씨가 Feature 결과에 기대는 값이 있으면(좌표) 저장된 POI 좌표를 먼저 쓴다.
- **의존**: 없음.
- **해제 조건**: ① 두 상류에 각각 지연 1초를 넣은 시험에서 전체가 약 1초다(지금은 약 2초). ② 한쪽이
  실패해도 다른 쪽 결과는 그대로다. ③ 응답 본문이 종전과 같다.
- **검증**: 단위 시험, PinVi `/metrics`의 `/trips/{trip_id}` 분포 전후.
- **위험·되돌림**: 낮다. 평균 9초의 원인이 이것인지는 재지 못했다 — 호스트 정지(F-01)의 몫이 클 수
  있다.

### 8.4 Manager (`digitie/kor-travel-docker-manager`) — 외부 추적

#### T-READ-MGR-01 — 공용 PostgreSQL의 질의 관측을 켠다 (n150·odroid)

- **변경**: tenant DB마다(또는 `postgres` DB에) `CREATE EXTENSION pg_stat_statements`(이미 preload돼
  있다), `log_min_duration_statement=1000`, `track_io_timing=on`, `log_lock_waits=on`,
  `log_temp_files=10MB`. 뒤 네 개는 reload로 반영된다. `docs/shared-postgres-onboarding.md`에 값과
  조회 방법을 적는다.
- **의존**: 없음.
- **해제 조건**: ① `SHOW`로 네 값이 보인다(두 호스트). ② Map DB 역할이 `pg_stat_statements`를 읽거나,
  읽는 관리 역할과 절차가 문서에 있다. ③ 1초 넘는 문장이 PG 로그에 남는다(시험 문장 `pg_sleep(1.1)`).
- **검증**: 반영 전후 `pg_settings`, 로그 한 줄.
- **위험·되돌림**: 로그 양(1초 문턱이면 작다), `track_io_timing`의 시계 비용(`pg_test_timing`으로 확인).
  되돌림은 값 원복 + reload.

#### T-READ-MGR-02 — 세 서비스의 지표를 긁는다

- **변경**: Map API에 `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=true`와 metrics token을 주고,
  Prometheus scrape job을 Map API·PinVi API(`/metrics` 공개)·weather API(bearer)에 건다. route별 p95와
  5xx 비율 패널 하나, in-bounds 503 비율 경보 하나.
- **의존**: `T-READ-02`(pool 지표). 지표 켜기 자체는 지금 코드로도 된다.
- **해제 조건**: ① Prometheus에서 세 서비스의 route별 시간 histogram이 조회된다. ② Map `/metrics`가
  token 없이는 401이다. ③ 패널 주소가 `docs/`에 있다.
- **검증**: scrape target `up`, 질의 한 번.
- **위험·되돌림**: 지표 미들웨어의 요청당 비용(작다). 되돌림은 env false.

#### T-READ-MGR-03 — API 프로세스를 swap에서 지킨다 (n150)

- **변경**: Map API·PinVi API(그리고 두 UI) 컨테이너에 `mem_limit`와 같은 값의 `memswap_limit`를 준다
  (transport와 같은 방식). 한도는 실측 RSS + swap의 3배 이상에서 시작한다(Map API 약 170 MB → 512 MB,
  PinVi API 약 165 MB → 512 MB).
- **의존**: 없음.
- **해제 조건**: ① 재생성 뒤 두 프로세스의 `VmSwap`이 0이다. ② 전체 e2e 한 번 동안 OOM kill이 없다
  (`docker inspect`의 `OOMKilled`, `dmesg`). ③ 한가한 12시간 뒤에도 `VmSwap` 0.
- **검증**: `/proc/<pid>/status`, e2e 결과.
- **위험·되돌림**: 한도가 작으면 OOM — ②가 본다. 되돌림은 두 값 제거.

#### T-READ-MGR-04 — n150 공용 PG의 메모리·I/O 설정을 다시 잡는다

- **변경**: `pg_buffercache`로 무엇이 버퍼를 차지하는지 먼저 본다. 그 결과로 `shared_buffers`(지금
  1 GB), `effective_cache_size`(1.5 GB), `effective_io_concurrency`(1)의 새 값을 정한다. 뒤 둘은 reload로
  되고 `shared_buffers`는 전 tenant 재시작이다.
- **의존**: `T-READ-MGR-01`(전후 비교에 `pg_stat_statements`·I/O 시간이 필요하다), `T-READ-01`.
- **해제 조건**: ① 변경 전후 같은 e2e 구간의 `pg_stat_io` eviction·읽기 수와 `T-READ-01` 수치를 표로
  적는다. ② 호스트 swap 사용이 늘지 않는다. ③ 다른 tenant(PinVi·Dagster·concierge)의 health가 초록이다.
- **검증**: 위 표.
- **위험·되돌림**: 재시작은 전 서비스 순단이다. 메모리를 PG에 더 주면 페이지 캐시와 다른 컨테이너가
  준다 — 한 번에 한 값만 바꾼다.

#### T-READ-MGR-05 — odroid NVMe의 남은 공간을 확보한다 (급함, 소유자·Codex)

- **변경**: `/mnt/media`(PG 데이터가 있는 파일시스템)의 사용처를 확인하고 PG가 쓸 여유를 만든다.
  남은 공간 경보를 건다. weather artifact volume(eMMC)의 위치도 함께 정한다.
- **의존**: 없음.
- **해제 조건**: ① 남은 공간이 PG 데이터 크기의 20% 이상이다. ② 문턱 아래로 내려가면 알린다.
- **검증**: `df -h`.
- **위험·되돌림**: 다른 팀 호스트의 자료를 지우는 일이라 소유자 확인이 먼저다.

### 8.5 weather (`digitie/kor-travel-weather`) — 외부 추적

정본은 weather 자체 설계다(§3.4). 아래는 그 위에서 이 계획이 요청하는 것이다.

#### T-READ-WEA-01 — 공개 읽기 시간 상한과 단계별 지표

- **변경**: 공개 `/v1/weather/*` 읽기 transaction에 `SET LOCAL statement_timeout`(export는 이미 5초,
  `SRC/export_snapshots.py:522`), pool 대기·export 단계별(freeze·artifact 읽기·직렬화) 시간 지표,
  histogram 상한을 30초 위로 늘린다(`SRC/metrics.py:270-274`).
- **의존**: 없음.
- **해제 조건**: ① 상한을 넘긴 공개 읽기가 503이고 연결이 pool에 돌아온다. ② export 요청 하나의
  단계별 시간이 지표에 나온다. ③ 첫 페이지·cursor 페이지·304가 label로 갈린다.
- **검증**: 시험 + `/metrics`.
- **위험·되돌림**: 느린 정상 질의가 실패로 바뀐다 — 상한을 env로 둔다.

#### T-READ-WEA-02 — export가 304를 싸게 내고 페이지 고정 비용을 줄인다 (`W-EXPORT-SLOW-20261108`에 얹는다)

- **변경**: ETag를 페이지를 만들기 전에 비교한다(`API/routers/service_exports.py:311-329`). cursor
  페이지마다 snapshot 행 전체(manifest 포함)를 읽는 것과 health 묶음을 다시 만드는 것을 snapshot당
  60초 재사용한다(재확인 안 함: `SRC/export_snapshots.py:823-829,967-1085`). 서버가 페이지당 읽는 scope
  수에 상한을 둔다(`limit`이 5000이어도 한 요청이 artifact 전부를 읽지 않게).
- **의존**: weather P0-A 설계와 겹치는 부분은 그 설계가 우선한다.
- **해제 조건**: ① 내용이 같은 재요청의 304가 artifact를 읽지 않는다(읽기 계수 시험). ② cursor 페이지의
  고정 비용이 페이지 크기 200과 2000에서 같은 자릿수다. ③ 한 요청이 읽는 artifact 수가 상한 이하다.
- **검증**: `tests/test_export_read_cost.py` 계열에 시험 추가.
- **위험·되돌림**: 예보 ETag의 정의가 출력 기반이라 manifest 기반으로 바꿔야 한다 — 동등성 시험.

#### T-READ-WEA-03 — cursor 페이지를 줄 때 snapshot 만료를 늦춘다

- **변경**: Map PR #1493이 남긴 요청 — snapshot handle의 TTL(15분)을 cursor 페이지 응답 때 연장한다.
- **의존**: 없음.
- **해제 조건**: 15분을 넘는 전량 순회가 410 없이 끝난다(시계 주입 시험). 만료된 handle은 연장하지
  않는다.
- **검증**: 시험. Map 쪽 `weather_state_forecast_short` 전량 run의 재시작 횟수.
- **위험·되돌림**: 오래 사는 snapshot이 artifact GC를 붙잡는다 — 연장 상한을 둔다.

#### T-READ-WEA-04 — 특보 최신성 조회의 색인

- **변경**: `weather_sync_runs(provider, dataset_key, status, finished_at DESC)` 색인(재확인 안 함:
  `alert_event_store.py:159-187`이 이 조건으로 최신 run을 찾고 맞는 색인이 없다).
- **의존**: `T-READ-WEA-01`의 지표로 이 질의가 실제로 느린지 먼저 본다.
- **해제 조건**: EXPLAIN이 새 색인을 타고, 표가 10배 커져도 같은 계획이다(시험).
- **검증**: 계획 시험(`tests/test_location_catalog_index.py`와 같은 형식), 배포 뒤 `/v1/weather/alert-events`의
  지표 전후.
- **위험·되돌림**: 쓰기 비용이 작게 는다. 되돌림은 색인 삭제.

### 8.6 transport (`digitie/kor-travel-transport`) — 외부 추적

#### T-READ-TRN-01 — 요청 시간과 문장 수를 남긴다

- **변경**: `backend/app/main.py`에 요청 시간 미들웨어(느린 요청 로그 + `/metrics` 또는
  `Server-Timing`), SQL 문장 수 누산. Map의 `T-READ-02`와 같은 로그 모양을 쓴다.
- **의존**: 없음.
- **해제 조건**: ① 1초 넘는 요청이 route template·시간·문장 수와 함께 로그에 남는다. ② query string이
  남지 않는다. ③ 지표가 gateway allowlist 밖에서만 보인다.
- **검증**: 시험, `scripts/benchmark-db-reads.py` 전후.
- **위험·되돌림**: 낮다.

#### T-READ-TRN-02 — `features/places`의 왕복을 줄인다

- **변경**: 종류별 `COUNT(*)`를 `limit+1` 또는 창 함수로 바꾸고(`main.py:1655-1660` 계열),
  `include_sources` 기본을 거짓으로 하거나 source 목록을 프로세스에 둔다(`main.py:1787-1791`),
  `raw_item_json`을 뺀 열만 읽는다.
- **의존**: `T-READ-TRN-01`(전후 문장 수).
- **해제 조건**: ① 전 종류 요청의 문장 수가 10개 이하다. ② `kind_totals`·`truncated`의 의미가 같다
  (또는 계약 변경을 관리 화면과 함께 고친다). ③ 응답 본문의 항목이 같다.
- **검증**: 시험, benchmark.
- **위험·되돌림**: `kind_totals`가 정확한 총계가 아니게 될 수 있다 — 계약으로 정한다.

#### T-READ-TRN-03 — 참조 export가 304를 싸게 낸다

- **변경**: snapshot의 내용 digest로 304를 먼저 판정하고, 입력 fingerprint를 head 세대당 한 번만
  계산한다(재확인 안 함: `services/export_references.py:353-404`,
  `services/reference_export_revision.py:44-81`).
- **의존**: 없음.
- **해제 조건**: 내용이 같은 조건부 요청이 페이지를 만들지 않는다(계수 시험). [문서 주장] 4.02초였던
  조건부 조회가 300 ms 안이다(같은 문서의 측정 방법으로).
- **검증**: `backend/tests`의 export 시험에 계수 시험 추가, 같은 보고서의 측정 절차 재실행.
- **위험·되돌림**: 무효화 누락 — 세대가 바뀌면 반드시 다시 계산하는 시험.

#### T-READ-TRN-04 — 주차 이력 캐시 재구성을 읽기 프로세스 밖으로

- **변경**: 30일치 재조회·압축(`services/parking_history_cache.py`)을 수집 쪽(Dagster)이 만들고 API는
  결과만 읽거나, 바뀐 부분만 더한다.
- **의존**: `T-READ-TRN-01`(재구성 중 다른 요청의 지연을 먼저 잰다).
- **해제 조건**: 재구성 중 `/health`와 작은 읽기의 p95가 재구성이 없을 때와 같은 자릿수다.
- **검증**: `T-READ-TRN-01`의 요청 시간 로그로 재구성 구간과 그 밖을 비교, `scripts/benchmark-db-reads.py`.
- **위험·되돌림**: 30초 신선도 계약(`docs/architecture/performance.md`). 메모리 한도 512 MB.

## 9. 확인하지 못한 것

1. 조용한 호스트에서의 모든 지연 수치(§2.5). 이 문서의 시간 수치는 측정 창의 것이거나 문서 주장이다.
2. in-bounds 503 15건의 원인(Map 지연 / 배포 중 재기동 / PinVi 회로).
3. `GET /trips/{trip_id}` 평균 9초와 `/weather/markers-in-bounds` 평균 6.5초의 구성.
4. F-06이 운영에서 실제로 일어나는지(route 호출이 없었다).
5. 운영 컨테이너의 코드가 §2.2의 commit과 같은지.
6. "grid-projection" 보류 변경 — Map·weather의 main 문서, 브랜치 이름, PR 제목·본문 검색에서 그 이름을
   찾지 못했다. 예보 artifact를 위치가 아니라 KMA 격자(약 1,076개) 단위로 읽어 위치에 투영하는 안으로
   짐작하지만 근거 문서가 없다. 아는 사람이 weather `docs/tasks.md`에 적어야 한다.
7. odroid의 PG 설정과 통계(접속하지 않았다), odroid 부하의 지속성, NVMe를 채운 것이 무엇인지.
8. subtype PK 탐색 89만~174만 회와 `features` seq scan 140회(2,380만 행)를 내는 질의가 무엇인지.
9. weather·transport·PinVi 인용 중 "(재확인 안 함)"으로 적은 줄.
10. PinVi 미들웨어(rate limit·geofence)가 요청마다 하는 일.
