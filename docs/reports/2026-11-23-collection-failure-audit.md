# 수집 작업 실패·재시도·Dagster 구조 감사 (2026-11-23)

> 범위: 두 공용 Dagster plane — **n150**(Map·PinVi·concierge)과 **odroid**(transport·weather·geo).
> 방식: 전부 읽기 전용(Dagster storage·앱 DB SELECT, `docker inspect`/`logs`, journal, 코드 열람). 실행·tick·재시작·설정 변경 없음.
> 창: 14일 = 2026-11-09 10:1xZ ~ 11-23 10:1xZ, 48시간 = 11-21 10:1xZ부터. 시각은 UTC, cron 표기는 KST.
> 기준 코드: Map `e3dfed59`(prod), PinVi `3b83bbe8`, Manager `03a8a6be`(n150 설치본)·`db78d1a`(odroid 설치본), common `05d7f91`, transport `d4bb920`, weather `2b269b0`, concierge `3413ed2`. Dagster 1.13.24.
> 표기: [확인] 질의·로그로 직접 확인, [코드] 소스 확인(배포본과 다를 수 있음), [추정] 직접 확인 못 함.

## 0. 요약

| plane | 14일 run | 실패 | 실패율 | 실패의 주 원인 |
|---|---|---|---|---|
| n150 | 31,038 | 2,314 | 7.5% | **82%가 code-server fd 고갈(`[Errno 24] Too many open files`)로 run launch 실패** — 빼면 1.4% |
| odroid | 약 11,870 | 3,633 | 약 30% | **94%가 재시도로 못 고치는 같은 결정적 오류의 반복**(특보 이벤트 중복, 공항·고속도로 부분 실패) |

1. 공공 API로 feature를 적재하는 작업 자체는 건강하다(n150 14일 4건 실패). 일일 쿼터·429 실패, Dagster OOM은 두 plane 모두 관측되지 않았다.
2. **실패가 보이지 않는다.** 두 plane 모두 경보가 없다. PinVi는 11-13~16, concierge는 11-14~18에 run이 전부 실패했고, odroid weather 특보 이벤트는 11-18 07:05Z부터 지금까지 100% 실패 중인데 아무도 몰랐다.
3. **재시도 층은 많지만 맞는 곳에 없다.** 결정적 오류는 5분마다 무한 반복하고, 일시 오류(DB lock timeout·DNS·launch 실패)는 가까운 재시도가 없거나 3분 안에 포기한다. odroid의 `dagster/max_retries` tag는 instance에 `run_retries`가 없어 전부 무효다.
4. **상류 신호가 엇갈린다.** weather가 stale이면 Map은 SUCCESS(오래된 자료 교체), transport가 stale이면 Map은 FAILURE로 쌓인다.
5. **날씨 공백(11-22 08:4x~)은 수집 정지가 아니다.** KMA·AirKorea는 계속 성공했다. odroid `regional_weather_job`이 DNS 오류 한 번으로 실패했고, 재시도가 없고 승격이 run SUCCESS에 묶여 있어 지역 자료가 24시간 승격되지 못했다.
6. **odroid daemon `unhealthy`는 원인이 아니다.** healthcheck가 60초 안에 끝나지 못하는 것이고 daemon heartbeat 일곱 개는 정상이다. 다만 location 단위로 schedule·sensor가 기록 없이 몇 시간씩 멈추는 현상(최장 3시간 5분)이 있고 원인은 미규명이다.
7. **호스트가 바닥이다.** odroid는 CPU 포화(run worker 기동 p50 30초, 대기열 p95 10~50분), n150은 디스크 IO 정체(가동의 16.5%)와 디스크 83%. 두 호스트 모두 11월에 디스크가 한 번씩 가득 찼다(n150 11-15, odroid 11-17).

## 1. n150 plane

### 1.1 Map 수집·적재 인벤토리

모든 Map job은 run 큐 dequeue 재시도(3회·60초)를 공통으로 받고 run 단위 재시도는 0이다.

**PG feature 적재**

| job | 원천 | prod 트리거 | 마지막 성공 | 14일 성공/실패 | 상태 |
|---|---|---|---|---|---|
| feature_event_visitkorea_festivals_job | TourAPI 축제 | schedule 매일 04:35 | 11-22 | 14/0 | 정상 |
| feature_place_visitkorea_tourist_attractions_job | TourAPI 관광지 | **schedule 미기동** | 11-10(수동) | 1/0 | stale 13일 |
| feature_notice_krforest_landslide_forecast_issues_job | 산림청 산사태 | 하루 6회 | 11-23 | 76/1 | 정상 |
| feature_place_krforest_recreation_forests / arboretums / dulle_trails | 산림청 | 매월 4일 | 11-03 | 0/0 | 정상(월간) |
| feature_route_krforest_mountain_trails_job | 산림청 등산로 | 매월 4일 | **10-26** | 0/0 | 저하(11-03 정기 run 6시간 뒤 실패, 다음 12-04) |
| feature_place_standard_{museums, tourist_attractions, parking_lots}_job | 표준데이터 | 매월 4일 | 11-11 | 5/1 | 정상 |
| feature_place_standard_{special_streets, traditional_markets}_job | 표준데이터 | **미기동** | 11-10(수동) | 2/0 | 미기동 |
| feature_place_datagokr_seoul_bookstores_job | 서울 열린데이터 | 매월 4일 | 11-03 | 0/0 | 정상 |
| feature_place_datagokr_{ansan_world, gyeonggi_muslim_friendly, jeju_local}_restaurants_job | data.go.kr | 의도적 비활성(활용신청 미완) | - | - | 꺼짐 |
| feature_place_khoa_beaches_job | KHOA | 매월 4일 | 11-03 | 0/0 | 정상 |
| feature_place_knps_points / feature_geometry_knps_records | 국립공원 | 매월 3일 | 11-11 / 11-06 | 3/0 | 정상 |
| feature_place_krheritage_items_job | 국가유산청 | **미기동** | 11-10(수동) | 1/0 | 미기동 |
| feature_event_krheritage_events_job | 국가유산청 행사 | 매월 2일 | 11-10 | 1/0 | 정상 |
| feature_place_mois_licenses_job | 행안부 LOCALDATA | schedule RUNNING, continuation sensor **의도적 STOPPED** | 11-11 | 4/1 | 정상 |
| mois_localdata_source_sync | 행안부 원천 파일 | 매주 월 | 11-22 | 1/1 | 정상(11-15는 디스크 full) |
| feature_place_mcst_culture_job | MCST | 매월 3일 | 11-16 | 3/0 | 정상 |
| feature_place_kor_travel_concierge_youtube_job | concierge | **미기동** | 11-10(수동) | 1/0 | 미기동 |
| feature_place_transport_fuel_stations_job | transport export | **미기동** | **10-12** | 0/0 | stale 6주 |
| feature_place_transport_{rest_areas, rail_stations, ferry_ports, airports}_job | transport | 매주·매월 | 11-20~22 | 11/0 | 정상 |

- **미기동 6개**(TourAPI 관광지, 표준 특화거리·전통시장, 국가유산 항목, concierge youtube, transport 주유소)는 instigator 행이 없어 한 번도 켠 적이 없다. `DISABLED_FEATURE_LOAD_SCHEDULES`에도 없어 의도인지 누락인지 기록이 없다 → **소유자 결정 필요**.
- "Map prod는 update-request 큐로 돈다"는 전제는 더 이상 사실이 아니다. schedule 43개가 RUNNING이고 큐 요청은 14일 2건뿐이다.

**상류 상태를 Valkey로 옮기는 state job**

| job | 주기 | 14일 성공/실패(율) | 48h | 상태 |
|---|---|---|---|---|
| transport_state_highway_incidents | 10분 | 1,871/123 (6.2%) | 267/20 | 저하: 503 80, 0건 집합 교체 거부 33 |
| transport_state_fuel_stations | 매시 | 315/18 (5.4%) | 46/2 | 저하: 11-23 08:17Z부터 매시 503 |
| transport_state_rest_area_fuel_prices | 매시 | 332/2 | 48/0 | 정상 |
| weather_state_current | 매시 2회 | 549/110 (16.7%) | 91/5 | 저하: **상한 480초 초과 99건**(성공 p95 419초) |
| weather_state_forecast_ultra_short | 매시 | 285/44 (13.4%) | 46/2 | 저하: 교체 거부 28, 상한 초과 13 |
| weather_state_forecast_short | 3시간 | 55/56 (50.5%) | 16/0 | 회복(11-09~11, 11-14~17 거의 전부 실패) |
| weather_state_{forecast_external, forecast_mid, daily_summaries, locations} | - | 492/18 | 73/1 | 정상(stale 표시) |

### 1.2 실패 원인 순위 (n150, 14일 2,314건)

| # | 원인 | 건수 | 비중 |
|---|---|---|---|
| 1 | code-server fd 고갈로 launch 실패(nofile soft 1024) | 1,888 | 81.6% |
| 2 | 상류(odroid) stale·미준비·무응답으로 step 재시도 소진 | 152 | 6.6% |
| 3 | run 상한 초과 | 131 | 5.7% |
| 4 | 상류의 빈/축소 집합 교체 거부 | 64 | 2.8% |
| 5 | 배포·code-server 재시작(실행 중 소실 17 등) | 약 53 | 2.3% |
| 6 | PinVi → weather 10초 ReadTimeout | 10 | 0.4% |
| 7 | 디스크 full(11-15 02:00~05:13) | 약 9 | 0.4% |
| 8 | 공공 API·geo·도메인 오류 | 약 7 | 0.3% |

tenant별: Map 4,987 run 중 380 실패(7.6%), PinVi 19,006 중 800(4.2%), concierge 7,042 중 1,131(16.1%). PinVi 알림 planner가 매분 run을 만들어 전체 run의 51%다.

Map update-request 큐: 전 기간 24건 중 failed 14(10-22에 한꺼번에 넣은 13건이 lock timeout으로 실패). 실패 원인이 Map DB에 남지 않는다(`{"kind":"dagster_run_terminal","status":"FAILURE"}` 한 줄).

### 1.3 n150 재시도 결함

**P0**
- **launch 실패가 3분 만에 영구 실패가 된다.** `run_queue.max_user_code_failure_retries: 3`(60초 간격) 소진 뒤 메시지 없이 실패 처리되고, 이어받을 run 재시도는 대부분 0이다(Manager `config/dagster-shared/dagster.yaml`). fd 고갈 1,888건의 직접 원인.
- **launch RPC 60초 timeout과 늦은 기동이 겹치면 살아 있는 run이 실패로 기록된다**(Manager `docker-compose.yml`의 `DAGSTER_GRPC_TIMEOUT_SECONDS=60`; 관측 run `6167d3a0`).
- **다건 호출 provider에 Map 2차 재시도가 없다.** `upstream_retry.py`의 설명과 달리 적용처는 KHOA 하나뿐이고, 나머지는 5xx 한 번에 asset 전체를 처음부터 다시 돈다.

**P1**
- `weather_state_current` 상한 480초가 성공 p95(419초)와 붙어 있다(`weather_state.py:825`).
- 상한으로 죽은 step에 재시도를 요청한다(84회, 실행 안 됨).
- 몇 시간짜리 상류 stale을 30·60초 뒤 재시도한다(`kor_travel_transport.py:175-183`). Map에서 재시도가 붙은 run 344건 중 성공으로 끝난 것은 54건(16%).
- 큐 요청은 일시 DB 오류에도 한 번에 종결된다(`feature_update_executor.py:1403-1425`). 시작 전 실패 재발행에는 상한·backoff가 없다.
- provider lib 절반(datagokr·krheritage·mois)은 쿼터 분류 속성이 없어 쿼터 판정이 발화하지 않는다(`quota_exhaustion.py:120`). 14일 관측 사례는 없음.
- PinVi `pinvi_weather_retention_horizon_job`: weather timeout 10초에 op 3회라 15회 중 14회 실패.

**P2**: backoff에 jitter 없음, lock busy가 SUCCESS로 끝나고 15초 뒤 새 run, `dagster/max_runtime` 없는 Map job 5개, concierge claim 전 실패 backoff 없음.

### 1.4 n150 Dagster 구조

- 구성: daemon·webserver·gateway + code-server 3개(run worker는 code-server 안). 동시성 전역 6, location 상한 map·pinvi 10(전역보다 커서 무의미)·concierge 2. run monitoring start 600초·상한 6시간.
- 저장소 연결: code-server NullPool, webserver pool 1·**pre-ping 없음**, daemon QueuePool 2+2·대기 1초 → 기동 4.8시간 동안 풀 부족 경고 574건, sensor/scheduler 반복 실패 4회.
- 모든 Dagster 컨테이너 nofile soft 1024.
- Manager 렌더와 실제 사이 drift 없음.
- **freeze 도구가 PG writer 대부분을 멈추지 않는다.** 산사태 schedule과 큐 sensor만 멈추고 나머지 약 42개(MOIS schedule 2, consistency, GC, file scan, feature schedule)는 계속 돈다. R4 창 절차에서 전수 정지·복원으로 보정했다.
- event_logs 1.98 GB, job_ticks 1.08 GB 무기한 증가.

## 2. odroid plane

### 2.1 구성 [확인]

- `kor-travel-dagster-daemon`·`-webserver`·`-gateway`, code server 3개(transport, weather, geo). 전부 host network.
- `DefaultRunLauncher`, `max_concurrent_runs` 5, location 상한 transport 3·weather 3·geo 1, run_group 상한 각 1.
- storage는 공용 PG의 `dagster_shared`(1.18 GB). 메모리 제한은 weather code server 2.5 GB, PG 3 GB, 나머지 없음.
- 설치된 Manager는 `db78d1a`(11-20)로 main과 drift가 있다(§2.5).

### 2.2 수집 인벤토리 요약

**transport**

| job | 원천 | trigger | 14일 성공/실패 | 48h | 상태 | Map 소비 |
|---|---|---|---|---|---|---|
| airport_collection_job | 공항 주차 | 5분 | 1648/866 | 342/9 | 정상(11-13까지 장기 실패) | 예 |
| highway_collection_job | KEX 교통량·돌발 | 5분 | 1875/873 | 364/7 | 정상(11-15까지 장기 실패), 실효 주기 약 9분 | 예 |
| fuel_collection_job | OpiNet 브라우저 | 8시간 | 24/16 | **1/5** | **저하: 3회 연속 실패** | 예 |
| rest_area_fuel_price_collection_job | KEX 휴게소 유가 | 4시간 | 68/12 | 8/4 | **저하**(lock timeout) | 예 |
| rest_area_reference_collection_job | KEX 휴게소 | 매일 | 13/0 | 2/0 | 정상 | 예 |
| bus_reference_collection_job | TAGO+VWorld | 매일 | 9/4 | 1/1 | 저하(VWorld 보강 실패가 run 실패) | 아니오 |
| 그 밖(kric, ferry, general_rail, rail_ref, maritime, vadahub, place_location, kakao, public_parking) | - | - | 정상 | - | 정상 | 아니오 |
| parking_statistics_archive_job | DB | 수동 | 0 | 0 | **코드에 있으나 40일간 실행 0** | 아니오 |

**weather**

| job | trigger | 14일 성공/실패 | 48h | 상태 |
|---|---|---|---|---|
| kma_ultra_short_nowcast / forecast, kma_mid, kma_weather_alerts | 매시·하루 2회 | 953/14 | 정상 |
| kma_short_forecast_job | 3시간 | 77/10(+취소 10) | **빠듯함**: 중앙값 8,166초, 상한 10,800초 |
| **kma_regional_alert_events_job** | 5분(coalescing 없음) | 2058/1757 | **0/575 — 11-18 07:05Z부터 100% 실패** |
| airkorea_weather_job | 매시 | 302/2 | **초록이지만 매 run 13개 측정소 실패** |
| openweathermap / weatherapi | 3시간 | 380/10 | 정상 |
| open_meteo | STOPPED | - | 11-10 이후 정지(의도된 것으로 보임 [추정]) |
| visual_crossing·tomorrow_io·weatherbit·weatherstack·accuweather·wttr_in | 3시간 | 각 104~108/0 | **빈 실행**: 키 없이 3~4초 skip, 14일 약 635 run 낭비 |
| regional_weather_job | 하루 2회 | 26/1 | 정상(11-22 20:30Z 실패가 24시간 공백을 만듦) |

**geo**: backup_retention_janitor 정상. `scheduled_backup`·`backup_restore_drill_daily`는 **STOPPED**이고 마지막 `db_backup` 성공은 10-29.

### 2.3 실패 원인 순위 (odroid, 14일 3,633건)

| # | 원인 | 건수 | 비중 | 기간 |
|---|---|---|---|---|
| 1 | 특보 이벤트: `ALERT_PAGE_DUPLICATE` 1,600 · `ALERT_PAGE_METADATA` 152 · 기타 5 | 1,757 | 48.4% | **11-18 07:05~현재** |
| 2 | 공항: 부분 실패를 run FAILURE로(IIAC 관측시각 malformed) | 835 | 23.0% | 11-09~11-13 |
| 3 | 고속도로: `traffic flow response contains invalid records` | 830 | 22.8% | 11-09~11-15 |
| 4 | 밖에서 실패 처리된 run | 47 | 1.3% | 상시 |
| 5 | 단기예보 정리 "진척 없음" | 33 | 0.9% | 상시 |
| 6 | `transport_collection_states` lock timeout(airport 20·rest_area_fuel 9·fuel 2) | 31 | 0.9% | **11-18 23:58~현재** |
| 7 | DNS 실패 | 20 | 0.6% | 상시 |
| 8 | fuel: OpiNet `resource policy failed command=Fetch.failRequest` | 14 | 0.4% | 상시 |
| 9 | 최대 실행시간 초과 | 11 | 0.3% | 상시 |
| 10 | 11-17 디스크 가득(PG PANIC) | 12 | 0.3% | 11-17 |

op 재시도 이벤트(`STEP_UP_FOR_RETRY`)는 14일 0건이다.

### 2.4 타임라인

**날씨 공백**

| 시각 | 일 |
|---|---|
| 11-22 08:30 | `regional_weather_job` 성공 |
| 11-22 20:30 | `krex_restarea_sync`가 DNS 오류(`No address associated with hostname`) → run FAILURE |
| ~11-23 08:30 | 재시도 없음, 다음 tick은 12시간 뒤. `current` snapshot 14개 전부 `source_collected_at` = 11-22 08:43 |
| 11-23 09:07 | 정기 실행 성공 |
| 11-23 09:26 | `current` 전진. 지금도 약 10시간 지연(export head 5,678개 중 6시간 초과 1,754, 24시간 초과 403) |

Map 쪽에서는 이 기간 `weather_state_current` 성공 90건 중 89건이 stale 자료로 교체됐고 run은 SUCCESS였다.

**유가 실패**

| run 생성 | 결과 | 소요 | 사유 |
|---|---|---|---|
| 11-21 07:00 | 성공 | 103분 | |
| 11-21 15:00 | 실패 | 61분 | 수집을 마친 뒤 `last_error` UPDATE에서 lock timeout |
| 11-21 23:00 | 실패 | 2분 | resource policy failed |
| 11-22 07:00 | **성공** | 76분 | 마지막 성공 |
| 11-22 15:00 | 실패 | 62분 | resource policy failed |
| 11-22 23:00 | 실패 | 31분 | resource policy failed |
| 11-23 07:00 | 실패 | 3분 | claim UPDATE에서 lock timeout |

실패는 15:00Z(00:00 KST) 실행에 몰려 있다(14회 중 8회). 통계 정리는 성공한 저장 뒤에만 돌아 실패가 이어지면 정리도 멈춘다. lock 보유자는 표본 25분 동안 찾지 못했다.

**그 밖의 경계**

| 시각 | 일 |
|---|---|
| 11-13 09:18~11:31 | SchedulerDaemon 로그 무음 2시간 12분, 전 location tick 0. 재시작 없이 재개 |
| 11-17 07:51~08:16 | NVMe 가득 → PG PANIC, crash recovery |
| 11-18 07:05 | 특보 이벤트 100% 실패 시작 |
| 11-18 23:58 | `transport_collection_states` lock timeout 시작 |
| 11-19 17:25~20:20 | weather location의 schedule·sensor **전부** 정지(실패 tick 0, code server healthy) |
| 11-20 03:16~04:16 | transport location 정지 |

### 2.5 odroid 재시도 결함

**P0**
1. **[weather] 결정적 오류를 5분마다 무한 재실행.** `alert_events.py:200-205`가 KMA 응답의 `event_id` 중복 하나로 수집 전체를 버리고, schedule에 coalescing도 차단기도 없다. 11-18부터 1,366회 연속 실패, 하루 288 run 낭비.
2. **[transport] `transport_collection_states` UPDATE의 5초 lock timeout을 재시도하지 않음**(`transport_collection.py:1397-1414`, `collection.py:439-455`). fuel은 61분 수집을 마치고 오류 기록 단계에서 죽었다.
3. **[weather] step 하나의 실패가 run 전체의 승격을 12시간 막음**(`definitions.py:1620-1661`, 승격 조건 `813-817`).

**P1**
4. [transport] 부분 성공을 run FAILURE로 올림 → 공항 835·고속도로 830건.
5. [transport] fuel 실패 뒤 가까운 재시도 없음(다음 시도 8시간 뒤).
6. [common] infra 재시도 sensor가 자기 10초 deadline으로 실패(`kortravelcommon/dagster.py:680`, 실패 run 100건을 매 tick 다시 훑음) → 실패 tick 338건.
7. [배포] `dagster/max_retries` tag 전부 무효 — odroid `dagster.yaml`에 `run_retries` 없음(Manager #610 미반영).
8. [common] 밖에서 죽은 run은 사유가 없어 infra sensor가 건너뜀 → 47건.
9. [common] coalescing이 QUEUED·STARTED 동안 tick을 버리는데, 5분 job에 `max_runtime` 14,400초, 외부 예보에 57,600초가 붙어 있다.
10. [weather] AirKorea 측정소 실패를 SUCCESS로 끝냄(302회 중 301회).
11. [transport] highway `next_due_at`에 여유가 없어 498건이 run을 띄우고 `skipped`.
12. [weather] 외부 provider 429를 그대로 4회 재시도.

**P2**: 키 없는 외부 job 6개, krairport 429 즉시 재시도, highway 결정적 파싱 오류에도 재호출, prune 실패 비가시.

### 2.6 odroid Dagster 구조 문제

1. **CPU 포화 위에 프로세스를 너무 많이 띄운다.** 하루 약 1,000 run, run worker 기동 p50 30초. 줄일 수 있는 run 약 370개/일(특보 실패 288, 빈 외부 job 45, highway skipped 35).
2. **location 단위 무기록 정지**(§2.4). 두 번 모두 code server 내부 gRPC가 다시 뜬 뒤 약 30분 지나 재개. 원인 미규명 — 다음 발생 때 daemon 스택 덤프 필요.
3. **code server 내부 gRPC 단절**: 14일 transport 22회(74분), weather 25회(91분).
4. **healthcheck가 제 기능을 못 한다.** daemon probe(Python 기동 + code server 3개 gRPC health + liveness, timeout 60초)가 매번 timeout이지만 출력은 `Daemon live`. unhealthy에 반응하는 것도 없다.
5. **sensor 안의 무거운 일**: `weather_export_publisher`가 60초 tick에 평균 36초·최대 49초, 오류를 skip 사유로 삼킴.
6. **단일 장애점**: PG 한 대가 세 테넌트 앱 DB와 Dagster storage를 담고 PGDATA가 미디어 라이브러리와 같은 NVMe(82%). DNS resolver 한 대.
7. **Manager drift**: `run_retries` 없음(#610), 로그 레벨 WARNING(#550), `job_ticks` Manager 인덱스 없음(#631), weather·geo code server는 옛 경로의 `dagster.yaml`을 마운트(정본 둘).
8. daemon docker 로그 14일 592 MB, 회전 설정 없음.
9. `dagster/priority` 없음, 서버 `idle_in_transaction_session_timeout` 없음(highway에서 4분 넘는 트랜잭션 관측).

n150에서 본 "재생성 뒤 죽은 DB 연결" 계열은 odroid에서 재현되지 않았다(11-17 PG crash recovery 뒤 daemon·webserver 정상 동작).

## 3. Map이 보는 상류 상태

| 상류 상태 | Map 결과 | 문제 |
|---|---|---|
| weather stale(HTTP 200 + `source_status=stale`) | 교체, run SUCCESS | 오래된 자료가 초록으로 보임 |
| weather 503·timeout | step 재시도 뒤 FAILURE | |
| transport 503 | step 3회 뒤 FAILURE, Valkey는 마지막 세대 유지 | 몇 시간짜리 장애를 30·60초 뒤 재시도 |
| transport 0건 집합 | 교체 거부 FAILURE | 낮 시간 0건은 상류 수집 이상 [추정] |

같은 "상류가 오래됨"이 weather는 초록, transport는 빨강이다. Map 실패의 57%(216건)가 이 상류 신호다.

## 4. 조치 목록 (우선순위)

| # | 조치 | 소속 | 배포 |
|---|---|---|---|
| 1 | 경보: location별 "N분간 tick 없음", job별 "k주기 동안 SUCCESS 없음", launch 실패, 디스크 여유, IO PSI — Dagster plane 밖 경로로 발송 | Manager + 운영 | 양 호스트 |
| 2 | weather 특보 이벤트: 중복 행 격리 후 진행, 연속 실패 차단기, coalescing | weather | Codex |
| 3 | code-server·daemon·webserver `nofile` 상향, fd 지표화로 누수 추적 | Manager + common | n150·odroid |
| 4 | run 큐 `max_user_code_failure_retries` 상향, gRPC timeout 60 → 180초 안팎 | Manager | n150·odroid |
| 5 | transport `transport_collection_states` lock timeout 재시도 + 보유자 로그 | transport | Codex |
| 6 | weather `regional_weather_job` 자산별 승격 또는 네트워크 오류 재시도 | weather | Codex |
| 7 | odroid plane을 Manager main으로 수렴(#610 run_retries, #631 tick 인덱스, #550 로그) + code server `dagster.yaml` 정본 통일 | Manager | Codex(odroid) |
| 8 | daemon 저장소 풀 확대·대기 10초 이상, webserver pre-ping | common + Manager | 양 호스트 |
| 9 | Map: `weather_state_current` 상한 상향, 상류 503은 재시도 대신 tick 건너뜀 + stale 나이 지표, weather/transport 의미 통일 | Map | n150 회전 |
| 10 | freeze 도구가 PG를 쓰는 RUNNING instigator 전부를 멈추고 복원하도록 | 운영 스크립트 + Map | - |
| 11 | Map 미기동 schedule 6개: 켜거나 사유와 함께 비활성 기록 | Map + **소유자 결정** | n150 |
| 12 | run 수 줄이기: 키 없는 외부 job 6개 차단, highway `next_due_at` 여유, PinVi planner 매분 run 축소 | weather·transport·PinVi | Codex·n150 |
| 13 | transport 부분 성공 판정, 5분 job `max_runtime`, `dagster/priority`, fuel 실패 뒤 짧은 재시도 | transport | Codex |
| 14 | common infra 재시도 sensor cursor·deadline, coalescing QUEUED 나이 상한, 밖에서 죽은 run 사유 보고 | common → 각 저장소 재핀 | 전부 |
| 15 | Map 다건 호출 provider 호출 단위 재시도, 큐 일시 오류 유한 재시도·원인 보존 | Map | n150 |
| 16 | 호스트: DNS 이중화·캐시, docker 로그 회전, PG `idle_in_transaction_session_timeout`, 디스크 정리·여유 경보, 테스트 게이트 IO 격리 | 운영 | 양 호스트 |
| 17 | AirKorea 13개 측정소 실패 원인, 상태 partial | weather | Codex |
| 18 | geo 백업 schedule 정지(10-29 이후 백업 없음) 확인 | geo + 소유자 확인 | Codex |
| 19 | location 정지 원인 규명(다음 발생 때 daemon 스택 덤프) | 운영 조사 | - |

## 5. 확인하지 못한 것

- n150 code-server fd 고갈의 누수 지점(조사 시점에는 fd 13~24개로 정상).
- odroid `transport_collection_states` lock 보유자.
- odroid location 무기록 정지의 원인, daemon unhealthy 시작 시각.
- odroid tick 정리 DELETE 비용(`pg_stat_statements` extension 없음).
- 두 호스트의 디스크를 채운 주체.
- fuel `resource policy failed`의 OpiNet 측 원인 — 별도 작업에서 조사·수정 중.
