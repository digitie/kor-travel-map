# T-212e — 실데이터 full reload 최종 리포트 (2026-06-12)

> 상태: **완료** — 전 트랙 종결(적재 1,095,665 features · consistency OK ·
> offline upload 3포맷+DELETE lifecycle · e2e 33/33 · API smoke 17/17 ·
> backup/restore smoke OK · P99 수집). 관련 이슈 #397/#407/#409 close.

## 0. 전제 — WSL 재설치로 인한 환경 재구축

2026-06-12 WSL 재설치(Ubuntu-26.04 신규 distro)로 라이브 스택 전체가 소실되어
T-212e를 **빈 DB에서 처음부터** 재실행한다(과제 정의의 "DB를 비운 뒤 처음부터
다시 로드" 전제를 자연 충족). 재구축 내역:

- WSL Ubuntu-26.04: OOBE 미완료로 비-root exec hang → root로 사용자
  `digitie`(UID 1000, docker/sudo group) 생성 + `/etc/wsl.conf` `[user]
  default=digitie`. **docker는 WSL native docker-ce 29.5.3**(사용자 지시).
- krtour 이미지 4종(api/frontend/dagster/dagster-daemon) 재빌드.
  `python-datagokr-api` 등 private provider pin 때문에 **`GITHUB_TOKEN` env가
  compose build secret으로 필수**(없으면 dagster/api 빌드 실패).
- 공유 RustFS(tripmate-manager `tripmate-rustfs`, :9003/9004): 데이터 디렉토리
  (`/home/digitie/kraddr-geo-data/rustfs`)가 ext4라 소실 → 재기동 +
  `rustfs-init`이 버킷 4종(krtour-map/krtour-uploads/kraddr-geo/tripmate-media)
  재생성. **기존 feature file/offline upload 원본 객체는 소실** — 본 reload가
  처음부터 다시 만든다.
- kraddr-geo(:9001 REST + :15434 PostGIS): 주소 DB pgdata가 ext4라 소실. **다른
  agent가 별도 세션에서 재구축 진행**(사용자 지시로 본 세션 범위 제외). 본
  reload의 place 배치는 kraddr-geo가 **실제 reverse 응답을 줄 때까지 대기**
  (빈 DB 상태에서 적재하면 bjd 보강이 오염되므로 :9001 응답 + reverse 실결과
  검증을 게이트로 사용).
- krtour 스택은 `restart: unless-stopped` 로컬 오버레이로 기동 — 같은 WSL에서
  다른 agent의 docker 데몬 재시작이 반복 발생(06:08/06:17/06:20/06:24 KST,
  4회)해 in-flight run 보호는 불가하지만 서비스는 자동 복귀.

### 0.1 중간 rebase — #391 포트 표준화 반영 (2026-06-12 09:4x KST)

reload 진행 중 main에 **#391(로컬 서비스 포트 표준화)**가 머지되어 사용자 지시로
rebase 후 속행했다. 새 표준: Postgres 공유 `5432` · RustFS `12101/12105` ·
kraddr-geo `12201/12205` · krtour-map `12301/12302/12305` · tripmate-agent `12401`.

본 T-212e claude 스택의 정렬 내역:

- kraddr-geo base URL `:9001` → **`:12201`** (.env 2변수).
- RustFS: 구 공유 인스턴스(`tripmate-rustfs` :9003)가 새 tripmate-app 스택
  (:12101)으로 교체되며 자격증명도 변경 — 공유 자격증명은 타 agent 워크스페이스
  소유라 본 스택은 **자체 rustfs(:9203/9204 remap, dev 기본 자격증명)**로 전환
  (#391 기본값도 자체 rustfs, 공유는 opt-in). ⚠ 구 공유 rustfs에 올렸던 offline
  upload 객체 2건은 인스턴스 교체로 소실 → kraddr 복구 후 재업로드로 진행.
- API/UI/Dagster 포트: 새 표준 `12301/12305/12302`는 **codex 스택이 점유** 중이라
  본 스택은 기존 `9011/9012/9013` + Postgres `15433`을 .env로 명시 고정(충돌 회피,
  편차로 기록).
- kraddr-geo 게이트: API 가용 직후 1차 게이트에서 **reverse `NOT_FOUND`(주소 DB
  미적재)**를 검출해 place 배치를 의도적으로 보류했고, 타 agent의 적재 완료 후
  reverse `OK`(인사동 좌표 → `서울특별시 종로구 인사동길 30-12`, confidence 0.977)
  확인 뒤 속행.

## 1. 스택 기동 smoke (2026-06-12 06:22 KST)

| 항목 | 결과 |
|------|------|
| `GET :9011/health` | ok (envelope `request_id` 포함) |
| `GET :9011/v1/ops/health-deep` | ok — database ok / postgis 3.5.6 / prewarm extension=present, autoprewarm=on |
| `GET :9012/` (frontend) | 200 |
| `GET :9013/` (Dagster webserver) | 200 |
| alembic head | `0023_t216f_rest_names` |
| `feature.features` count | 0 (빈 DB 확인) |
| Dagster repository 로드 | `__repository__` @ `krtour.map_dagster.definitions` 정상 (#384 회귀 없음) |

Dagster job 목록(23종) 확인: feature job 16 + `__ASSET_JOB` +
`consistency_dedup_refresh` + `feature_update_request_worker` +
`full_load_batch_consistency_gate` + `mois_localdata_source_sync` +
`offline_upload_load`.

## 2. Provider 적재 결과 (배치별)

실행 방식: dagster 컨테이너 내 `dagster asset materialize -m
krtour.map_dagster.definitions --select <key>` (run은 Postgres storage에 기록).

### Phase 0 — kraddr-geo 불필요

| asset/job | 결과 | run id | duration | 비고 |
|-----------|------|--------|----------|------|
| `feature_notice_kma_weather_alerts` | ✅ RUN_SUCCESS | `9f08f41f` | 8s | 평시 특보 0건 — datagokr 03 NO_DATA 빈 결과 정규화(#383) 경로 정상 |
| `mois_localdata_source_sync` (Phase A) | ✅ RUN_SUCCESS | `334c9e29` | 1447s | LOCALDATA 다운로드 → dagster 컨테이너 `/tmp/mois_source.db` 5.14GB, `mois_place_master` 3,134,613행 (⚠ 컨테이너 재생성 시 소실 — Phase B 전 재확인) |
| `feature_place_tripmate_agent_youtube` | ⏸ SKIP (guard) | — | — | resource `tripmate_agent_youtube_features` 기본 비활성 — `KRTOUR_MAP_TRIPMATE_AGENT_BASE_URL`/`..._API_KEY` 미설정. TripMate-agent export API(해당 repo T-066) 가동 후 live 가능 — 설계대로의 guard 동작 |

### Phase 1 — place 계열 (kraddr-geo reverse 필요, 2026-06-12 09:54~11:18 KST)

10/14 성공, 4 실패(아래 별도 처리).

| asset | 결과 | duration | 비고 |
|-------|------|----------|------|
| `feature_place_standard_museums` | ✅ | 47s | |
| `feature_place_standard_tourist_attractions` | ✅ | 30s | |
| `feature_place_standard_parking_lots` | ❌ | 2726s | provider `PublicParkingLot.addUnitCharge` int 파싱 — live 값 `'200+400'`(자유 표기 요금). → `python-datagokr-api` 이슈+PR(관용 파싱, 비숫자→None) 후 핀 범프·재실행 |
| `feature_place_khoa_beaches` | ✅ | 27s | |
| `feature_place_krairport_airports` | ✅ | 8s | |
| `feature_place_krforest_recreation_forests` | ✅ | 11s | |
| `feature_place_krforest_arboretums` | ✅ | 13s | |
| `feature_place_knps_points` | ✅ | 9s | |
| `feature_geometry_knps_records` | ⚠ | 95s | RUN_SUCCESS이나 **적재 0건** — provider가 vertex 단위 POINT를 반환해 route 변환이 전 행 skip(#407). 수정·재실행은 Phase 4 이후 표 참조 |
| `feature_place_krheritage_items` | ❌ | 681s | live 목록에 key 3요소(ccbaKdcd/Asno/Ctcd) None row 실존 → `iter_all_details`가 None으로 detail 조회 → `HeritageDetail` 검증 실패. → `python-krheritage-api` 이슈+PR(결측 key row skip) 후 핀 범프·재실행 |
| `feature_place_krex_rest_areas` | ✅ | 12s | |
| `feature_place_opinet_stations` | ✅ | 17s | bbox scope(서울 강남 일대) |
| `feature_place_mcst_culture` | ❌ BLOCKED | 676s | KCISA `HTTP 403 API Key is not valid` — **인증키 문제가 아니라 경로 자체가 막힘**: `python-mcst-api`가 2026-06-11 #6/#7로 재편 중(api.kcisa.kr은 공인 DNS 미해석+KCISA 전용 키 필요 → CSV 파일 다운로드가 새 주경로). 로컬 체크아웃 `feat/file-download-catalog`에서 타 agent 작업 진행 중(미머지). → provider 재편 머지 후 krtour T-220 재배선 follow-up |
| `feature_place_mcst_libraries` | ❌ BLOCKED | 674s | ODCloud `HTTP 401 유효하지 않은 인증키` — 위와 동일 재편 범위 |

도중 docker 데몬 churn(11:19~11:21 4회 재시작)은 Phase 1 종료 직후라 피해 없음
(스택은 restart 정책으로 자동 복귀, MOIS 소스 DB 보존 확인).

### Phase 2 — event/notice 계열 (11:23~11:36 KST)

| asset | 결과 | duration | 비고 |
|-------|------|----------|------|
| `feature_event_datagokr_cultural_festivals` | ✅ | 30s | #374/#386 수정 경로 live 확인 |
| `feature_event_visitkorea_enrichment` | ❌→수정 | 697s | `SourceRecord.source_version`에 datetime — provider 실모델 `TourItem.modified_time: datetime` vs Protocol str 가정(run `cff6a853`). → krtour #392(머지)로 재정렬, 재실행 별도 기록 |
| `feature_event_krheritage_events` | ✅ | 62s | #380/#382 수정 경로 live 확인 |
| `feature_notice_krex_traffic_notices` | ✅ | 9s | #378 realTimeSms 경로 live 확인 |

### Phase 3 — weather/측정 (11:37~11:50 KST)

| asset | 결과 | duration | 비고 |
|-------|------|----------|------|
| `feature_weather_kma_ultra_short_nowcast` | ✅ | 10s | |
| `feature_weather_kma_ultra_short_forecast` | ✅ | 12s | |
| `feature_weather_kma_short_forecast` | ✅ | 21s | |
| `feature_weather_kma_mid_forecast` | ❌→수정 | 679s | `tm_fc='' (12자리 필요)`(run `f044b091`) — 중기 응답이 요청 `tmFc` 미에코인데 provider가 응답에서만 읽음. → `python-kma-api` #20/PR#21(머지, `2592b740`) 요청값 폴백 + krtour 핀 범프(#393), 재실행 별도 기록 |
| `feature_weather_airkorea_air_quality` | ✅ | 52s | 측정소 weather feature + WeatherValue |

### Phase 1·2·3 실패분 재실행 + Phase 4 — MOIS bulk (#392/#393 머지·리빌드 후)

| asset | 결과 | duration | 비고 |
|-------|------|----------|------|
| `feature_place_krheritage_items` (재) | ✅ | 1313s | provider `6076b52`(result 레벨 key 병합) 유효 — kind 5종 detail 크롤 완주, 4,187건 |
| `feature_event_visitkorea_enrichment` (재) | ✅ | 18s | #392(modified_time datetime 재정렬) 유효 — enrichment link 136건 |
| `feature_weather_kma_mid_forecast` (재) | ✅ | 7s | kma `2592b740`(요청 tmFc 폴백) 유효 |
| `feature_place_mois_licenses` (Phase 4) | ✅ | **10079s (2.8h)** | PROMOTED open rows bulk — source_records **980,970** |
| `feature_place_standard_parking_lots` (재²) | ❌→재³ | 2769s | **2차 실패**: live `lat=26.128492`(한국 경계 밖 오타) → `Coordinate` 검증이 dataset 차단. **#400**(좌표 격리 — 검증 실패 좌표 None, row는 주소 단서 적재) 머지 후 3차 ✅ **768s** |
| `feature_place_mcst_culture` (T-220 재배선 후) | ✅ | dataset별 | KCISA/ODCloud API 경로 폐기 → **CSV 카탈로그 13종 완주, source_records 102,121** (`python-mcst-api` `c011f6e`, T-223b 13종). 도중 `lat=42.64`(경계 밖) 1행이 dataset을 차단해 **#413**(mcst 좌표 격리 — `_coord_or_none`) 머지 후 완주. dataset별 카운트는 §6.1 |
| `feature_geometry_knps_records` (knps `16e3954` 핀 후 재) | ❌→재² | 867s | **provider LINESTRING 조립(#420)은 유효**(910,110 vertex → 코스 조립 진입)하나 이름 없는 코스 1건이 `Feature.name=None` ValidationError로 **배치 전체 실패** — krtour Protocol(`name: str`)이 knps-api 실모델(`str | None`)보다 엄격했던 ADR-044 위반. → krtour **#424**(Protocol `str | None` 정렬 + 이름 없는 행만 skip, mcst/datagokr 동일 규칙) |
| `feature_geometry_knps_records` (재², #424 후) | ✅ | 74s | run `d540d2f0` RUN_SUCCESS — `knps_trails` source_records/route feature **618건** 적재(이름 없는·조립 불가 코스 skip 제외). **#407 종결** |

도중 정밀화: 포트 표준(#391 — Windows 동적 포트 제외 범위 8981~9080이 legacy
9011~9013을 점유, wslrelay 바인드 불가)이 실측으로 검증되어 본 스택도
12301/12302/12305로 이전. frontend Docker 빌드 불능(main, T-221b의 빌드타임
필수 env 누락)도 적발·수정(**#408**).

## 3. 정합성/게이트

`full_load_batch_consistency_gate` job 2회 — 1차(trails 제외 시점) + 최종
(trails 포함, 백업/복원 후). 둘 다 **RUN_SUCCESS / severity_max OK**.

- 1차 report: `9848a2fd-e44a-4d18-b154-0a30a0d6600b`(batch `d2e6c5e9`,
  2026-06-12 19:00 KST, 1,095,047 features 기준)
- **최종 report: `99159eea-6539-493f-9194-28043a282c0a`**(batch `2ac677eb`,
  2026-06-12 21:39 KST, **1,095,665 features** — trails 618 포함)
- F-체크 전 케이스 **count 0 / OK**: F1(고아 source_record) · F2(detail 누락) ·
  F3(CRS drift coord↔coord_5179) · F4(dedup pending 백로그, threshold 1000
  대비 0) · F5(provider cursor SLA) · F6(opening_hours 모순) 등
- `ops.data_integrity_violations` 0건 (address validation `drop` 모드 격리
  row는 run 메타데이터 `address_validation_dropped_*`로만 카운트 — 위반 적재
  없음)

## 4. offline upload 실데이터 검증

실데이터: **MOIS LOCALDATA 실 row 추출**(Phase A 산출 소스 DB에서 서울
일반음식점 50행 CSV + 카페 30행 TSV — 상호/경위도/도로명주소/관리번호).

| 단계 | CSV (`6f516902`) | TSV (`9c1d1121`) | 비고 |
|------|------------------|------------------|------|
| `POST /v1/admin/offline-uploads` | ✅ 201 (rustfs `krtour-uploads` 기록) | ✅ 201 | checksum/storage_key/meta 정상 |
| `GET /{id}/preview` | ✅ | — | header/sample 정상 |
| `POST /{id}/validate` (1차, kraddr 다운 중) | ❌ `validation_failed` — 50행 전부 `dto_validation_failed: All connection attempts failed` | ❌ 동일 (30행) | **validate가 row별 kraddr reverse 보강을 수행** → geocoder 미가용 시 전 행 실패(fail-closed). 사후 검토 후보: infra 장애를 행 단위 `dto_validation_failed`로 보고하는 것은 코드 구분이 거칢(`geocoder_unavailable` 등 분리 여지) |
| 재업로드 (RustFS 인스턴스 교체 후) | ⚠ 1차 409 → 신규 id `e73f42fa` | ⚠ 1차 409 → 신규 id `c7bb9903` | 구 업로드의 객체가 인스턴스 교체로 소실됐는데 **checksum 멱등 가드가 동일 파일 재업로드를 409로 차단** + **`DELETE /{id}`가 문서(rest-api.md)에만 있고 미구현(405)** → 좀비 정리 불가. **이슈 #397** 등록. 내용 변형(60/40행, dataset_key `_v2`)으로 우회 |
| validate (2차, kraddr 가용) | ⚠ 59/60 | ⚠ 39/40 | 실패 각 1행 원인 격리: 로컬 주소 DB `NOT_FOUND` 주소만 `fallback="api"`(kraddr→VWorld 프록시) 경로를 타는데 **kraddr-api 배포에 VWorld 키 미주입**(`PARAM_REQUIRED` → E0501 → 502). probe로 재현 확정 → 운영자가 `KRADDR_GEO_VWORLD_API_KEY` 주입 |
| validate (3차, VWorld 키 주입 후) | ✅ 60/60 `validated` | ✅ 40/40 `validated` | |
| `POST /{id}/load` (`offline_upload_load` job) | ✅ `loaded` (job `c6afbc44`) | ✅ `loaded` (job `5ccb33c2`) | **#384 수정 경로 live 재검증 완료** — 구 502 `PipelineNotFoundError` 재발 없음 |
| JSONL FeatureBundle 업로드→load | ✅ `loaded` 60건 (upload `2a8c4c48`, job `e2b31e2b`) | — | 실데이터 CSV를 lib 자체 `parse_offline_tabular_feature_bundles`로 FeatureBundle JSONL화해 사용 |

DB 반영: `provider_sync.source_records` — `t212e_smoke_restaurants_csv_v2=60` /
`t212e_smoke_cafes_tsv_v2=40` / `t212e_smoke_jsonl=60`.

### 4.1 좀비 업로드 정리 — `DELETE /{id}` live 검증 (#397 종결)

#397로 등록한 갭(checksum 멱등 가드 + DELETE 미구현 405 → 객체 소실 좀비
정리 불가)은 **#417**(offline-uploads DELETE lifecycle)로 구현·머지됐고, 본
reload의 실좀비 2건으로 live 검증 완료:

| 단계 | 결과 |
|------|------|
| `DELETE /v1/admin/offline-uploads/6f516902`(좀비 1, RustFS 객체 소실) | ✅ 200 — row purge + checksum 가드 해제 |
| `DELETE /v1/admin/offline-uploads/9c1d1121`(좀비 2) | ✅ 200 |
| 동일 checksum 원본 CSV 재업로드 | ✅ **201** (구 409 멱등 차단 해제 확인, 신규 id `fa4c5c44`) |

## 5. e2e / API smoke / backup-restore smoke

### 5.1 Windows Playwright e2e — 1차 (reload 진행 중, docker 스택 직결)

`E2E_BASE_URL=http://127.0.0.1:19012`(socat 프록시 경유)로 32개 중 **25 passed /
7 failed**. 실패 7건은 전부 환경 요인으로 격리:

- **etl 3건 + admin/issues 1건**: 이 스펙들만 브라우저가 실 API(`127.0.0.1:9011`)에
  직접 fetch하는데, **WSL localhostForwarding은 0.0.0.0 바인드만 포워딩**
  (docker-ce `127.0.0.1` publish는 Windows에서 미도달, 12201(0.0.0.0)은 도달 —
  실측). 라이브 API에 `python-krex-api` 등 provider 목록 실재 확인 — 데이터
  문제 아님. 기존 "32 passed" 실행은 WSL 네이티브 프로세스 토폴로지(포워딩
  됨)였고, docker 스택 직결은 처음.
- **change-requests workflow 3건**: Next RSC prefetch(`/admin/features?_rsc=`)가
  비표준 origin(:19012)에서 route mock의 unhandled 가드에 걸림 — 테스트 하네스
  특성.

조치: `.env`에 `KRTOUR_MAP_DOCKER_BIND_HOST=0.0.0.0` 추가(다음 재기동 시 적용,
opt-in 문서 규정 준수 — WSL NAT 내부라 LAN 직노출 아님). 전 배치 종료 후
mcst 리빌드와 함께 재기동하고 e2e 최종 재실행 예정.

추가 발견(0.0.0.0 적용 후에도 9011~9013 미도달): **Windows 동적 포트 제외
범위(`netsh int ipv4 show excludedportrange` — 8981~9080 등)가 legacy
9011/9012/9013을 점유**해 wslrelay가 Windows 측 바인드 자체를 못 함 —
ADR-047 #391 포트 표준화(12xxx)의 실증적 근거. codex 스택 종료로 표준 포트가
비어 본 스택을 **12301/12302/12305 표준으로 이전**(레거시 9xxx 핀 제거).

### 5.1.1 Windows Playwright e2e — 최종 (표준 포트 직결, 2026-06-12 17:0x)

**30/32 passed** (기본 base `http://127.0.0.1:12305`, 프록시/override 불요).

- 1차 실패 7건 중 5건 해소: change-requests 3건은 spec의 frontend 포트
  하드코딩(12305) 제거 — `FRONTEND_PORT`를 `E2E_BASE_URL`에서 도출(#408에
  포함), etl 2건+α는 표준 포트 이전으로 브라우저→API 직결 해소.
- 잔여 2건은 환경이 아니라 **spec drift** → **이슈 #409** (T-221 후속):
  (a) providers freshness — T-221d가 추가한 두 번째 테이블과 strict-mode
  충돌('last success' 헤더 2개), (b) admin/issues — 라이브 첫 issue 행 클릭
  시 manual-override 폼 가시성 단언이 issue type 의존(약 1M행 라이브
  데이터에서 실측).

### 5.1.2 Windows Playwright e2e — 종결 (2026-06-12 21:4x)

**33/33 passed** (#417이 offline-uploads delete flow spec을 추가해 32→33).

- #409의 spec drift 2건은 **#416**(providers freshness 테이블 strict-mode /
  admin issues manual-override 단언) 머지로 해소 — live 재실행으로 검증.
- offline-uploads mutation/delete flow 2건은 frontend **컨테이너가 #417 이전
  이미지**라 실패했던 것 — 이미지 재빌드·재배포 후 통과(스택 운영 시 코드
  머지 후 frontend 이미지 갱신 누락 주의).

### 5.2 API smoke (2026-06-12 18:4x, 표준 포트 12301)

**17/17 통과** — health / ops/health-deep / openapi.json / categories /
providers / features/search·in-bounds·nearby·{id} / admin/features·issues /
ops/import-jobs·dagster/summary / admin/offline-uploads / public/beaches /
public/festivals/monthly(T-222b 신규 표면 포함) / 404 계약(problem+json).

### 5.3 backup-restore smoke (2026-06-12 21:34~, 전 적재 완료 후)

runbook §8 절차: write path 정지(api/frontend/dagster/daemon/rustfs — postgres
유지) → cold backup → **staging** restore(운영 DB 비파괴 — `docker-restore.sh`는
production DB명 거부 가드) → 서비스 재기동.

- **cold backup `20260612T123458Z`** ✅ — `krtour_map.dump` **554MB** +
  `krtour_map_dagster.dump` 2.6MB + `rustfs-data.tar.gz`, manifest +
  SHA256SUMS(restore 시 checksum 검증 통과).
- **staging restore** ✅ — `krtour_map_restore`/`krtour_map_dagster_restore` DB +
  `krtour-map-rustfs-restore` volume 재생성(`KRTOUR_MAP_RESTORE_RECREATE=1`),
  `docker-restore-verify.sh` 검증 포함. **복원 검증값 = 운영과 정확 일치**:
  `krtour_map_restore.feature.features` **1,095,665** / weather_values
  **92,923** / dagster runs·rustfs objects ok. 재기동 후 `/health` ok.
- 절차 결함 2건 발견(스크립트 자체가 아니라 실행 환경):
  (a) `with-pg-advisory-lock.py`가 WSL에서 venv 미선택 시 시스템 python으로
  폴백해 `psycopg` 부재로 실패 — `PYTHON_BIN`으로 mirror venv 지정 필요
  (NTFS 체크아웃엔 Linux venv가 없는 하이브리드 토폴로지 특성).
  (b) 1차 실행이 호출 측 프로세스 종료로 pg_restore가 **SIGPIPE로 중단**
  (staging DB 0행) — 장시간 maintenance 스크립트는 호출 세션과 분리(nohup +
  파일 로그)해 실행해야 함. 재실행으로 완료, 운영 DB는 양쪽 모두 무손상
  (1,095,665 유지 확인).

## 6. 운영 지표 (row 수 / P99)

### 6.1 적재 규모 (2026-06-12 21:30 최종 — knps_trails 포함 전 트랙 완료)

- `feature.features` **1,095,665** (중간 시점 990,637 → 주차장·MCST·trails 추가)
- `provider_sync.source_records` 주요: mois bulk **980,970** /
  **mcst 13종 합계 ≈102,121**(leisure_activity 23,797 · pet_friendly 23,091 ·
  media_famous 14,659 · barrier_free 12,317 · world_restaurants 9,206 ·
  family_infant 8,426 · leisure_classes 5,075 · camping 2,467 · cafe_bookstores
  1,042 · children_bookstores 772 · golf 541 · used_bookstores 406(T-223b) ·
  independent_bookstores 322) / **주차장 18,294**(좌표 격리 #400 후 완주) /
  krheritage 4,187 / festivals 1,279 / museums 1,062 / tourist 851 / airkorea
  673 / opinet 442 / khoa 268 / krex 210 / arboretums 205 / forests 183 /
  visitkorea enrichment 136 / knps visitor centers 112 / krex notices 99 /
  offline upload smoke 160 / airports 15
- `feature.feature_weather_values` **92,923**
- `knps_trails` **618**(route) — provider 코스 LINESTRING 조립(knps #9/PR#10,
  krtour #420) + 이름 없는 record skip(#424) 후 적재 완료(#407 종결). vertex 행
  910,110개 → 코스 단위 조립.

### 6.2 P99 측정에서 발견한 live 결함 2건 (수정 완료)

P99 측정이 `/features/search`·`/features/in-bounds` **500**을 적발 — PostGIS/
pg_trgm이 `x_extension` 스키마인데 live docker DB search_path는 postgis 이미지
기본값이라 **연산자**(`&&`/`<->`/trigram `%`)가 미해석(함수는 기존에 명시
qualify, 연산자만 누락; 통합 테스트 conftest가 search_path를 세팅해 CI에서
가려짐). **#410**(공간 연산자 12곳) + **#411**(trigram 2곳) `OPERATOR(
x_extension.<op>)` qualify로 수정·머지, live 검증(서울 bbox 94,431건 /
'박물관' trigram 1,646건).

### 6.3 대표 read P99 (n=60, WSL host → api 컨테이너, MCST 적재 병행 중 — 보수적)

| 엔드포인트 | p50 | p95 | p99 | max |
|------------|-----|-----|-----|-----|
| `GET /v1/features/search?q=박물관&page_size=20` | 48.4ms | 64.3ms | **85.6ms** | 232.9ms |
| `GET /v1/features/in-bounds`(서울 도심 bbox, 1000행 응답) | 334.6ms | 414.8ms | **441.7ms** | 546.9ms |
| `GET /v1/features/nearby`(시청 1km, 20행) | 78.1ms | 98.9ms | **102.0ms** | 151.3ms |
| `GET /v1/categories` | 2.4ms | 5.1ms | **8.8ms** | 12.7ms |

T-212d 클러스터 MV 재판단 입력: ~1M place 규모에서 exact-viewport in-bounds
p99 ≈ 440ms(대량 응답 직렬화 포함). 클러스터 rollup MV 도입 여부는 이 수치
기준으로 별도 ADR에서 판단(목표 SLO 대비).
