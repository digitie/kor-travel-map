# adr045-standalone-plan.md — 독립 프로그램화 실행 계획 (AI agent 실행용)

ADR-045(krtour-map = Docker 독립 프로그램 + 독립 DB/Dagster + TripMate OpenAPI)를
**실제 코드/배포로 구현**하기 위한 세분 실행 계획. 새 AI agent가 이 문서 하나로
순서·범위·차단요소를 파악하고 바로 task 단위로 진행할 수 있게 한다.

> **정본 분담** — 본 문서는 *무엇을 어떤 순서로 만들지*(task 분해)와 *무엇이 빠졌나*
> (gap)·*무엇을 결정해야 하나*(decision)를 모은다. 상세 *계약*은 이미 있는 문서가 정본:
> - admin OpenAPI/스키마/큐 테이블/Docker 서비스: `docs/openapi-admin-contract.md`
> - admin UI 워크플로/엔드포인트 상세: `docs/debug-ui-admin-workflows.md`
> - 외부 POI 캐시 갱신 타깃: `docs/poi-cache-update-targets.md`
> - Dagster 책임 경계: `docs/dagster-boundary.md`
> - TripMate 연계 REST 세부(params/returns): `docs/tripmate-rest-api.md`
> - 의사결정 결과: `docs/adr045-open-decisions.md` (D-1~D-16 전부 결정 완료)
> - 데이터 모델: `docs/data-model.md` / `docs/postgres-schema.md`

## 0. 현황 요약 (2026-06-01)

**이미 명세됨 (codex, 문서 존재)**: admin OpenAPI 엔드포인트 골격(`/admin/feature-
update-requests` CRUD + cancel/run-now, 6 scope, provider runs, POI cache),
`ops.feature_update_requests` DDL(`openapi-admin-contract.md §6.1`), Docker 논리
서비스 6종(§2), 요청/응답 JSON 예시(§5.1), frontend stack + React Doctor 규약.

**아직 코드/배포 없음 (이 계획의 대상)**:
1. `ops.feature_update_requests` 등 신규 테이블이 **alembic/models에 없음**.
2. scope resolver(5~6종) + dry_run count + request→job 브리지 **로직 없음**.
3. FastAPI admin/ops/features 라우터 **대부분 미구현**(현재 admin package는
   health/version/etl/features/mois-detail만).
4. **Dagster 프로그램 자체가 없음** (TripMate에서 복사·구체화 필요).
5. **docker-compose.yml / 배포 매니페스트 없음**.
6. TripMate 연계 REST의 **params/returns 미확정** → `tripmate-rest-api.md`로 분리.
7. **ADR-045 의사결정 D-1~D-16 전부 확정** → `adr045-open-decisions.md`.

**재사용 가능한 기존 자산 (재발명 금지)**: `infra/feature_repo.features_in_bbox`,
`infra/jobs_repo`(`ops.import_jobs` enqueue/claim/finish + advisory lock),
`infra/advisory_lock`, `infra/sync_state_repo`(cursor), `infra/merge_repo`,
`infra/consistency`(F1~F4), `infra/status_repo`, `AsyncKrtourMapClient`(load/
run_*_job/dedup/status), provider 변환기 9종, debug-ui `create_app` + 라우터 패턴.

---

## 1. Phase 1 — DB 스키마 추가 (라이브러리/alembic)

> 관련 결정: D-2(Dagster metadata DB), D-6(큐 실행 모델), D-11(sigungu 경계 소스)
> 모두 확정됨 — `adr045-open-decisions.md`. `feature_update_requests`는 §6.1 DDL
> 그대로 진행한다.

- **T-205a** ✅ `alembic 0008` + `FeatureUpdateRequestRow` — `ops.feature_update_requests`
  생성. 컬럼/CHECK/인덱스는 `openapi-admin-contract.md §6.1` DDL 그대로
  (scope_type/scope JSONB/providers/dataset_keys/update_policy/run_mode/priority/
  state/dry_run/matched_scope/job_id FK/dagster_run_id/operator/reason/error/
  타임스탬프). models.py에 ORM row 추가(ImportJobRow 패턴). T-205a는 schema/ORM/
  DDL 검증까지 완료하고, repo/client/API는 T-206/T-207에서 분리한다.
- **T-205b** ~~`feature.sigungu_boundaries` 테이블~~ **취소** — D-11 결정: 시군구
  경계는 **kraddr-geo가 소유**(`tl_scco_sig`), krtour-map은 REST 호출만(T-206a /
  T-206a-geo). krtour-map에 경계 테이블 신설하지 않는다.
- **T-205c** ✅ (Phase 2) `ops.data_integrity_violations`(F5~F8) / `ops.poi_cache_targets`
  + `ops.poi_cache_target_feature_links`(`poi-cache-update-targets.md` 정본) /
  `ops.provider_refresh_policies` — `alembic 0009` + model + repo + integration test.
- **T-205d** `feature_consistency_reports`/`import_jobs` 기존 테이블에 `load_batch_id`
  /`parent_job_id` 등 batch DAG 컬럼 필요 여부 확인(SPRINT-5 T-200) — D-6 결정
  (request:job=1:1, 큰 scope는 job 내부 배치)를 따른다.

## 2. Phase 2 — 로직 (scope resolver + 큐 브리지)

- **T-206a** ✅ `infra/scope_repo.py` 신규 — scope→feature_id 해석 (읽기):
  - `resolve_feature_ids(session, ids)` — 존재 검증 통과분만.
  - `resolve_center_radius(session, lon, lat, radius_km)` — `coord_5179` +
    `ST_DWithin`(ADR-012, 입력 1회 ST_Transform). `features_in_bbox` 패턴 재사용.
  - `resolve_bbox(session, bounds)` — `features_in_bbox` 위 얇은 래퍼.
  - `resolve_sigungu_by_radius(session, lon, lat, radius_km)` — **kraddr-geo
    `POST /v2/regions/within-radius`(D-11) 호출** → 교차 시군구 `code` 목록 →
    `WHERE sigungu_code = ANY(:codes)` feature 조회. `KraddrGeoRestClient` 재사용.
    sig_cd = sigungu_code 동일 체계(D-11 확인) — 매핑 없이 그대로 사용.
  - `resolve_provider_dataset(session, provider, dataset_key, sync_scope)` —
    `source_links`(primary) JOIN `source_records` 필터.
  - `resolve_cache_target_keys(...)` — `poi-cache-update-targets.md` (Phase 2,
    `ops.poi_cache_targets` 테이블 도입 후).
  - `count_features_matching_scope(session, scope)` — **dry_run/ matched_scope용**
    (write 없이 count + sigungu_codes).
- **T-206a-geo** ✅ (형제 repo `python-kraddr-geo`) — `POST /v2/regions/
  within-radius` 엔드포인트와 optional PostGIS 실데이터 테스트 경로를
  `python-kraddr-geo` main 기준으로 재검증 완료. 요청/응답/구현 정본은
  `docs/regions-within-radius.md` (요약은 `adr045-open-decisions.md` D-11).
  `tl_scco_sig`(+ctprvn/emd) PostGIS 교차. 반환 `code`(sig_cd)는 krtour-map
  `sigungu_code`와 동일 체계(D-11 확인) — 매핑 불필요. 2026-06-03 기준 local
  API `9001` smoke에서 `sigungu` `11650`(서초구) contains 응답을 확인했다.
- **T-206b** ✅ `infra/feature_update_repo.py` 신규 — 요청 생명주기:
  - `enqueue_feature_update_request(session, scope, providers, dataset_keys,
    update_policy, run_mode, priority, dry_run, operator, reason) -> FeatureUpdateRequest`
    — scope 해석(matched_scope 계산) → dry_run이면 거기서 반환, 아니면 row INSERT +
    연결 `ops.import_jobs` 생성(job_id 링크).
  - `claim_next_update_request(session)` — `state='queued'` priority/created 순 +
    `FOR UPDATE SKIP LOCKED` + advisory lock(ADR-039). Dagster sensor가 호출.
  - `start/finish_update_request(session, request_id, state, dagster_run_id, error)`.
  - `get/list_update_requests(...)` — keyset cursor 페이지네이션(D-10).
  - 구현 메모: dry-run은 `FeatureUpdateRequestPreview`로 반환하며 DB row/import job을
    만들지 않는다. 실제 enqueue/claim/start/finish/cancel은 연결 import job 상태를
    같은 transaction 안에서 함께 갱신한다.
- **T-206c** ✅ `AsyncKrtourMapClient` 메서드 — `enqueue_feature_update_request` /
  `get_update_request` / `list_update_requests` / `cancel_update_request` (각 자체
  transaction). 기존 `run_*_job` 패턴 일관. Top-level
  `from krtour.map import AsyncKrtourMapClient` export도 실제 코드와 맞춘다.
- **T-206d** request 실행 본체 — scope 해석된 feature/provider를 실제 적재하는
  worker 로직. provider_dataset scope는 기존 `run_mois_*_job` 류 재사용; geographic
  scope(center/bbox/sigungu)는 "해당 feature를 소유한 provider/dataset을 역추적 →
  해당 dataset refresh" 정책. D-6(1 request:1 job, `run_mode=now` lock 충돌 시
  409)과 D-8(`prevent_provider_reactivation`) 결정을 따른다.

## 3. Phase 3 — FastAPI admin/ops/features 라우터 (debug-ui 패키지)

> 정본: `openapi-admin-contract.md` + `debug-ui-admin-workflows.md`. 라우터 패턴은
> 기존 `routers/features.py`(get_session 의존성) + `mois_detail.py` 참고.

- **T-207a** `/admin/feature-update-requests` 라우터 — POST(생성, dry_run 분기) /
  GET(list) / GET `{id}`(상세) / POST `{id}/cancel` / POST `{id}/run-now`.
  요청/응답은 §5.1. `feature_update_repo` 호출 + Pydantic schema + OpenAPI tag.
- **T-207b** `/admin/providers/{provider}/datasets/{dataset_key}/runs` (provider 직접
  실행, §7) — `ops.import_jobs` enqueue.
- **T-207c** `/admin/feature 검토/병합/override/deactivate` 라우터 —
  `debug-ui-admin-workflows.md` 정본. dedup-merge/override/deactivate(기존
  `merge_repo` + 신규 override 로직). D-8 결정에 따라
  `prevent_provider_reactivation`을 구현한다.
- **T-207d** `/ops/*` — consistency report 조회(F1~F4 기존 + Phase 2 F5~F8),
  import_jobs 모니터, metrics. `status_repo` + `consistency` 재사용.
- **T-207e** `/features/*` 사용자/admin 공용 read 라우터 — in-bounds/{id}/search/
  batch. D-7 결정에 따라 사용자 `/features/*`와 admin `/admin/features/*` 응답을
  분리한다. `tripmate-rest-api.md` 참고.
- **T-207f** `/admin/poi-cache-targets` + `/features/nearby/by-target` (Phase 2,
  `poi-cache-update-targets.md`).
- **T-207g** OpenAPI export 이원화(admin schema + 사용자 schema) + drift gate 갱신
  (ADR-031 amendment, D-3). `scripts/export_openapi.py` 확장.

## 4. Phase 4 — Dagster (TripMate에서 복사 → 구체화)

> 정본 경계: `dagster-boundary.md`(krtour-map-owned로 갱신됨). 복사 원본: TripMate
> `F:\dev\tripmate\apps\etl\` (현재 skeleton — definitions/resources sketch). 상세
> 구조·resources·assets·schedules·sensors·queue 브리지는 §본 절 + agent 리서치.

- **T-208a** `packages/krtour-map-dagster/` 패키지 골격 — `definitions.py`(code
  location) + `pyproject.toml`(dagster + krtour.map + provider libs). import-linter
  계층에 dagster layer 추가(client보다 위).
- **T-208b** `resources.py` — `KrtourMapDatabaseResource`(독립 DSN) +
  `KrtourMapClientResource` + provider resource 9종(키는 env, D-15 주입 정책) +
  `KraddrGeoResource` + 선택 `RustFSResource`.
- **T-208c** provider load asset 9종 — thin wrapper(provider fetch → lib 변환 →
  `client.load_feature_bundles` → `sync_state` 갱신). ADR-034 9단계 순서. 각 asset
  `concurrency_key=provider:dataset`(advisory lock, ADR-039) + RetryPolicy.
- **T-208d** `schedules.py` — provider별 cron(`execution_timezone="Asia/Seoul"`).
  부하 분산(요일/시간 분리).
- **T-208e** `sensors.py` — (1) `feature_update_requests` 폴링 sensor:
  `claim_next_update_request` → RunRequest 또는 `import_jobs` claim 실행
  (cardinality D-6). (2) `run_failure_sensor` → Sentry/알림 + `import_jobs` failed
  반영. polling 주기 D-6.
- **T-208f** consistency/dedup refresh job — `run_consistency_checks`(F1~F4) +
  `sync_dedup_candidates` 정기 실행.
- **T-208g** offline upload load job — admin 업로드 파일(D-14 저장 위치) → 적재
  `import_jobs`.

## 5. Phase 5 — Docker Compose / 배포

> 정본 서비스 목록: `openapi-admin-contract.md §2`. 파일 자체가 없음 → 신규.

- **T-209a** `docker-compose.yml` — 서비스 6종(api/frontend/dagster-webserver/
  dagster-daemon/postgres/선택 rustfs) + 네트워크 + 볼륨 + 포트(`api` 9011,
  `frontend` 9012, Dagster 9013, RustFS API 9003/console 9004, Postgres host 15433) +
  env(`KRTOUR_MAP_PG_DSN`/provider keys/RUSTFS). healthcheck + depends_on(기동 순서:
  postgres → migrate → api/dagster).
- **T-209b** 기동 순서 스크립트 — postgres ready → `alembic upgrade head`(app DB
  `krtour_map`) → `krtour_map_dagster` DB 생성 + Dagster 자체 schema init → api/
  dagster 기동. entrypoint/Makefile.
- **T-209c** Dockerfile 3종(api/frontend/dagster) 또는 멀티스테이지. GDAL/PostGIS
  client lib 포함(WSL libgdal 3.8.4 정합).
- **T-209d** `docs/runbooks/`에 `docker-app.md`(standalone 기동/스모크) +
  `deploy.md` 추가(TripMate runbooks 컨벤션 참고).
- **T-209e** backup/restore를 **독립 krtour_map + krtour_map_dagster + RustFS**
  대상으로 구체화(ADR-040 amendment, D-5 RustFS 배치). `infra/backup.py` + admin 라우터.

## 6. Phase 6 — TripMate 연계 + 문서 정리

- **T-210a** `docs/tripmate-rest-api.md` 확정 — TripMate가 호출하는 사용자/서비스
  API params/returns 구체화(본 PR에서 1차 작성, 구현 시 OpenAPI와 동기).
- **T-210b** TripMate 측 문서 정리(별도 repo `F:\dev\tripmate`) — 직접 import/공유
  DB/TripMate-owned Dagster 기술 문서를 ADR-045 OpenAPI 모델로 supersede. 대상
  목록: `docs/krtour-map-integration.md`(전면), `docs/architecture.md`, `docs/
  runbooks/etl.md`, `docs/architecture/dagster-etl-bridge.md`, `docs/api/features.md`,
  TripMate `docs/decisions.md` ADR-002/003 banner. (TripMate repo PR로 분리.)
- **T-210c** TripMate→krtour-map **이관**: TripMate `apps/etl`의 Dagster 자산/
  resource/schedule(현재 skeleton)을 krtour-map `packages/krtour-map-dagster`로
  이관(T-208). offline upload load·consistency/dedup job도 krtour-map 소유로.
- **T-210d** TripMate **backend(Python)** 신규: 수기 `httpx` wrapper
  `integrations/krtour_map_client.py`(krtour-map의 `KraddrGeoRestClient` 방식, 직접
  import 제거) + `docs/api/krtour-map-openapi-integration.md`. (TripMate repo, D-4.)
- **T-210e** TripMate **frontend(TS)**: krtour-map `openapi.json` →
  `openapi-typescript` codegen(`types/api.gen.ts`) + 수동 Zod mirror + CI diff 게이트
  (kraddr-geo `gen-types.mjs` 패턴, D-4). (TripMate repo.)

---

## 7. 충돌·정리 결과 (현 sprint/task/ADR)

> 리서치(agent D) 종합 결과를 바탕으로 정리한 항목이다. D-1~D-16이 모두 결정된
> 뒤 현재 실행 문서에는 아래 조치를 반영했다.

| 위치 | 충돌/갭 | 조치 |
|------|---------|------|
| SPRINT-5 §2.4 (T-200) | 구 Dagster 소유권 문구가 ADR-045와 충돌 | krtour-map Dagster asset, TripMate는 OpenAPI queue 제어만(ADR-045 §5)으로 정리 완료 |
| SPRINT-5 §2.5~2.11 | "debug-ui" 용어 = admin/ops UI로 확장 모호 | `/debug`(개발) vs `/admin`·`/ops`(운영) prefix 분리 명시 |
| SPRINT-4 §2.9 (backup) | 백업 대상 DB 소유 불명 | 독립 `krtour_map`+`krtour_map_dagster`+RustFS 대상(ADR-040 amendment) |
| tasks.md | T-205~T-210 (Docker/OpenAPI ver/Dagster/admin routes/React Doctor) **없음** | 본 계획의 T-205~210 backlog 등록(완료, tasks.md) |
| ADR-003 §후속 | `AsyncKrtourMapClient` "테스트용 public" 표현 모호 | "krtour-map 내부(api/dagster)+테스트 전용, TripMate import 금지" 명확화 |
| ADR-011 §결과(부정) | "Dagster 큐 중복 가능 — ADR-016에서 분리"(오참조) | "import_jobs가 1차 큐, Dagster sensor가 폴링"(ADR-045 §5) |
| ADR-031 | 단일 OpenAPI 가정 | admin schema + 사용자 schema 이원 drift gate(amendment, D-3) |
| ADR-034 | provider 적재 주체(TripMate vs krtour-map Dagster) 경계 미표기 | Sprint 2~4=CLI/client, Sprint 5+=krtour-map Dagster queue (amendment) |
| ADR-040 | 단일 공유 DB 백업 가정 | 독립 DB 묶음 백업(amendment, D-5) |
| ADR-005 | "코드에 인증 없음"은 유지하나 운영 인증 pass-through 필요 | network/infra 계층 인증 가정 amendment(D-1 auth) |

## 8. 권장 진행 순서 (의존)

1. **의사결정 확인**: D-1~D-16은 모두 확정됨 — `adr045-open-decisions.md`.
2. **Phase 1 T-205a** (feature_update_requests alembic/model) — 완료.
3. **Phase 2 T-206b/c** (feature_update_repo + client) — 완료.
4. **T-206a-geo** (형제 repo `python-kraddr-geo`) — `/v2/regions/within-radius`
   endpoint와 optional PostGIS 실데이터 테스트 경로 재검증 완료.
5. **Phase 2 T-205c** (`provider_refresh_policies`, `poi_cache_targets`,
   `data_integrity_violations`) — 완료.
6. **Phase 2 T-206d** — request 실행 본체.
7. **Phase 3 T-207a/d/e** (admin update-requests + ops + features 라우터) — T-206 후.
8. **Phase 5 T-209a/b** (docker-compose + 기동) — 라우터 동작 후 통합.
9. **Phase 4 T-208** (Dagster) — T-206/T-209 위, TripMate 이관과 병행.
10. **Phase 6** TripMate 정리/이관 — Dagster 이관 시점 동기.
11. OpenAPI client gen은 운영 안정 후.

각 task는 1-PR 단위(`docs/runbooks/agent-workflow.md`), 4 게이트 + 해당 시 alembic/
OpenAPI drift. 새 테이블·라우터마다 통합 테스트 필수(ADR-014).
