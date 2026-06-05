# CHANGELOG

본 라이브러리의 사용자 가시 변경을 기록한다. [Keep a Changelog](https://keepachangelog.com)
형식을 따른다.

## [Unreleased]

### Ops — standalone cold backup runbook (2026-06-05)

- **NEW**: `npm run docker:backup`이 standalone Docker app의 `krtour_map`,
  `krtour_map_dagster`, RustFS volume을 하나의 backup bundle로 저장한다.
- **DOCS**: `docs/backup-restore.md`에 산출물 구조, checksum/restore dry-check,
  수동 cold restore 경계를 문서화했다.
- **TEST**: backup script와 runbook의 3종 백업 대상, 비파괴 범위, npm script 연결을
  정적 회귀 테스트로 고정했다.

### Docker — runtime image hygiene (2026-06-05)

- **CHANGED**: `api`와 `dagster` Docker image를 builder/runtime stage로 분리하고
  runtime stage를 non-root `appuser`로 실행한다.
- **CHANGED**: frontend Docker image는 Next.js standalone server 산출물을 runner stage에
  복사하고 non-root `nextjs` 사용자로 실행한다.
- **TEST**: Dockerfile multi-stage/non-root/standalone 회귀 테스트를 추가했다.

### Infra — ops cursor decode hygiene (2026-06-05)

- **FIXED**: `infra.ops_repo` keyset cursor decode가 broad `Exception` catch 대신
  base64/UTF-8/JSON/schema/datetime 오류를 구체적으로 처리한다.
- **TEST**: import job cursor의 wrong-kind, missing field, invalid datetime,
  non-object payload 회귀 테스트를 추가했다.

### Map Marker React — dependency metadata hygiene (2026-06-05)

- **FIXED**: `@krtour/map-marker-react`의 `maplibre-vworld` peer dependency를
  `0.1.2`로 고정해 workspace devDependency의 git tag pin(`v0.1.2`)과 맞췄다.
- **FIXED**: skeleton 패키지의 `npm run test`가 테스트 파일 없음 상태를 성공으로
  처리하도록 `vitest run --passWithNoTests`를 사용한다.
- **DOCS**: `@krtour/map-marker-react` README의 npm registry 게시 설명을 ADR-043의
  registry 게시 보류 정책에 맞췄다.

### Admin API/UI — Dagster router hardening (2026-06-05)

- **FIXED**: `GET /ops/dagster/summary`가 더 이상 Dagster `setNuxSeen` mutation을
  호출하지 않는다. NUX 처리는 `POST /ops/dagster/nux-seen`으로 분리했다.
- **SECURITY**: `KRTOUR_MAP_ADMIN_DAGSTER_ALLOWED_HOSTS` allowlist와 http/https scheme,
  GraphQL path 검증으로 Dagster GraphQL URL SSRF 위험을 줄였다.
- **CHANGED**: Dagster GraphQL 호출은 FastAPI app state의 공유 `httpx.AsyncClient`를
  사용한다.
- **TEST**: Dagster router unit test와 OpenAPI schema를 새 계약에 맞춰 갱신했다.

### Docs — Dagster purge schedule cleanup (2026-06-05)

- **DOCS**: 실제 구현 없는 `feature_purge_*` asset/job 후보와 `purge notice old`
  schedule 행을 `docs/dagster-boundary.md`에서 제거했다.
- **DOCS**: purge는 TTL·삭제 정책과 실제 Dagster job이 함께 구현되기 전까지 schedule
  표에 추가하지 않는다고 명시했다.

### Docs — shell script execution context (2026-06-05)

- **DOCS**: `scripts/*.sh` 운영 스크립트가 WSL/Git Bash용 Bash script임을
  `docs/dev-environment.md`와 Docker runbook에 명시했다.
- **DOCS**: PowerShell에서는 `.sh`를 직접 실행하지 않고 `wsl bash -lc ...`로
  위임하는 예시를 추가했다.

### Dagster — package dependency hygiene (2026-06-05)

- **FIXED**: `krtour-map-dagster`가 `python-krtour-map==0.2.0-dev`를 명시적으로
  요구해 같은 릴리스의 메인 라이브러리와 함께 설치되도록 했다.
- **FIXED**: Dagster `offline_upload_store` resource가 직접 import하는
  `boto3`/`botocore`를 runtime dependencies에 추가했다.
- **TEST**: Dagster 패키지 로컬 `asyncio_mode="auto"`와 dependency metadata 회귀
  테스트를 추가했다.

### Docker — compose healthcheck/readiness (2026-06-05)

- **FIXED**: Docker compose의 `api`, `frontend`, `dagster` 서비스에 runtime
  healthcheck를 추가했다.
- **FIXED**: `frontend`가 short-form `depends_on` 대신 `api: service_healthy` 이후
  시작하도록 readiness 순서를 명시했다.
- **TEST**: compose healthcheck와 readiness dependency 회귀 테스트를 추가했다.

### Docker — frontend dependency reproducibility (2026-06-05)

- **FIXED**: frontend Docker image가 `npm install`로 floating dependency를 다시
  해석하지 않고, root `package-lock.json` 기반 `npm ci --workspaces --include=optional`
  로 설치한다.
- **DOCS**: Docker runbook과 deploy 메모에 frontend lockfile 갱신/빌드 기준을
  명시했다.

### Admin API — typed error mapping (2026-06-05)

- **FIXED**: feature update request의 kraddr-geo resolver 설정 누락을 substring
  matching이 아니라 `SigunguResolverUnavailable` 타입으로 `503` 매핑한다.
- **FIXED**: dedup review merge의 not found/conflict를
  `MergeNotFoundError`/`MergeConflictError` 타입으로 `404`/`409` 매핑한다.
- **FIXED**: 알 수 없는 enqueue/merge 예외의 내부 메시지를 admin API `500` 응답에
  그대로 노출하지 않는다.
- **TEST**: feature update/dedup review 라우터 unit test와 merge repo integration
  test를 보강했다.

### Infra/Admin API — 상태전이 guard (2026-06-05)

- **FIXED**: admin feature deactivate가 deleted/soft-deleted feature를 inactive로
  되살리지 않고 `409` conflict로 거절한다.
- **FIXED**: data integrity issue의 `resolved`/`ignored` terminal 상태가 다시
  `open`/`acknowledged`로 돌아가거나 `resolved_at`을 잃지 않도록 막았다.
- **FIXED**: offline upload validation/load mark/finish가 source-state guard를 사용해
  잘못된 완료 처리와 `loaded -> loading` 중복 Dagster 실행 경로를 차단한다.
- **TEST**: admin feature repo/router, integrity issue lifecycle, offline upload
  repo/router/load orchestration focused unit/integration test를 추가했다.

### Infra — dedup refresh master 신호와 keyset paging (2026-06-05)

- **NEW**: `Feature`/`feature.features`에 `coord_precision_digits`를 추가하고,
  DB trigger가 좌표 보유 row의 기본 precision을 6으로 보강하며 좌표 제거 시
  precision을 `NULL`로 정리한다.
- **FIXED**: `list_dedup_refresh_features`가 `updated_at DESC, feature_id DESC`
  keyset cursor를 사용해 `LIMIT` 재실행 시 같은 사전식 앞부분만 반복 조회하지 않는다.
- **NEW**: `DedupRefreshFeature`가 `updated_at`, `coord_precision_digits`,
  `as_master_candidate()`를 노출해 ADR-016 master 선정과 admin 검토 UI가 같은 신호를
  사용할 수 있게 했다.
- **MIGRATION**: alembic `0015_feature_coord_precision`이 컬럼, trigger, check
  constraint, dedup refresh keyset partial index를 추가한다.
- **TEST**: DTO validator, migration trigger, feature load round-trip, dedup refresh
  keyset paging, Dagster config cursor parsing을 검증한다.

### Infra — scope resolver count/preview 분리 (2026-06-05)

- **FIXED**: `count_features_matching_scope`가 `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset`, `feature_ids` dry-run에서 전체 feature row를
  materialize하지 않고 `count(*)`/provider 집계/sigungu 집계를 별도 SQL로 계산한다.
- **FIXED**: dry-run matched scope는 기본 1000개 preview만 보존하고,
  `feature_preview_count`, `feature_preview_limit`, `feature_preview_truncated`로
  truncation 여부를 기록한다.
- **TEST**: PostGIS integration test로 preview가 1개로 제한되어도 전체
  `feature_count`와 provider/dataset 집계가 3개를 유지하는지 검증한다.

### Infra — dedup merge review row 잠금 (2026-06-04)

- **FIXED**: `merge_from_review`와 admin `merge_dedup_review`가
  `ops.dedup_review_queue` review row를 `FOR UPDATE`로 잠근 뒤 pending 상태를
  확인하도록 바꿔 동시 merge TOCTOU를 차단했다.
- **TEST**: 자동 master 선정 경로와 수동 master 지정 경로가 기존 row lock을
  기다리는지 Postgres `lock_timeout` 기반 integration test를 추가했다.

### Infra — UUID default schema qualification (2026-06-04)

- **FIXED**: `ops.feature_consistency_reports`, `ops.dedup_review_queue`,
  `ops.import_jobs`, `ops.feature_merge_history`의 UUID default를
  `x_extension.gen_random_uuid()`로 스키마 한정해 search_path 의존을 제거했다.
- **MIGRATION**: alembic `0014_uuid_default_schema`가 기존 DB default를
  schema-qualified expression으로 갱신한다.
- **TEST**: Postgres catalog에서 ops UUID default expression이 모두
  `x_extension.gen_random_uuid()`인지 검증하는 integration test를 추가했다.

### Infra — Dedup pair order invariant (2026-06-04)

- **FIXED**: `ops.dedup_review_queue`가 `feature_id_a < feature_id_b` check와
  canonical upsert를 사용해 `(a,b)`/`(b,a)` 대칭 중복을 DB·repo 양쪽에서 차단한다.
- **FIXED**: self-pair dedup 후보는 검토 큐에 넣지 않고 `skipped`로 처리한다.
- **MIGRATION**: alembic `0013_dedup_pair_order_invariant`가 기존 self-pair를 제거하고,
  unordered duplicate pair는 검토 완료 행 우선으로 정리한 뒤 check constraint를
  추가한다.
- **TEST**: reversed pair upsert, self-pair skip, DB check constraint integration
  test를 추가했다.

### Admin/User API — Keyset cursor hardening (2026-06-04)

- **FIXED**: `/features/search` score cursor가 DB score text를 보존하고,
  `ORDER BY score DESC, feature_id ASC`와 같은 `(-score, feature_id)` 축으로 keyset
  비교하도록 바꿨다.
- **FIXED**: `/admin/dedup-review` cursor가 `NUMERIC` score를 문자열로 운반하고,
  predicate와 `ORDER BY` 모두 `review_key::text`를 사용하도록 정렬축을 통일했다.
- **TEST**: 같은 score/total_score를 가진 여러 행을 `page_size=1`로 끝까지 넘기는
  PostGIS integration test를 추가했다.

### Admin API — Feature update lock handling (2026-06-04)

- **FIXED**: `run_mode=now` feature update request 생성/재큐잉 시 동일 scope
  advisory lock이 이미 점유되어 있으면 `409 LOCK_BUSY`와 `Retry-After` 헤더를
  반환한다.
- **FIXED**: feature update executor가 실행 중 scope lock을 보유해 API preflight가
  실제 실행 경합을 감지할 수 있게 했다.
- **FIXED**: `claim_next_update_request`가 queue lock 경합과 빈 큐를 모두 `None`으로
  반환하던 동작을 분리해, lock 경합은 `FeatureUpdateQueueLockBusy` 예외로 드러낸다.
- **TEST**: admin router unit, PostGIS queue/scope advisory lock integration,
  executor scope lock 보유 integration test를 추가했다.

### Ops — Dagster provider resource guard (2026-06-04)

- **NEW**: feature-load provider record key 9개에 기본 guard resource를 등록했다.
  guard는 provider package, dataset, `KRTOUR_MAP_*` credential env, source env를
  안내하고 secret 값은 노출하지 않는다.
- **NEW**: `KrtourMapSettings`에 Dagster provider resource용
  `KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY`, `KRTOUR_MAP_OPINET_API_KEY`,
  `KRTOUR_MAP_KREX_EX_API_KEY`, `KRTOUR_MAP_KREX_GO_API_KEY` 설정을 추가했다.
- **DOCS**: 실제 provider public client live fetch wiring은 T-RV-04b 후속으로 남기고,
  현재 기본 guard는 비실행 상태임을 `krtour-map-dagster` README에 명시했다.

### Ops — Dagster resource lifecycle (2026-06-04)

- **FIXED**: `krtour_map_client` Dagster resource가 생성한 SQLAlchemy `AsyncEngine`을
  run/tick 종료 후 `dispose()`하도록 generator resource로 전환했다.
- **TEST**: fake engine/fake client 기반 resource teardown unit test를 추가했다.

### Ops — Dagster metadata DB and daemon split (2026-06-04)

- **CHANGED**: Docker Dagster runtime을 단일 `dagster dev`에서 `dagster` webserver와
  `dagster-daemon` 서비스로 분리했다.
- **NEW**: `dagster-db-init` 서비스가 같은 Postgres container 안의
  `krtour_map_dagster` DB 존재를 보장한다.
- **NEW**: `docker/dagster.yaml`을 추가해 Dagster run/event/schedule metadata를
  `KRTOUR_MAP_DAGSTER_PG_URL` 기반 `dagster-postgres` storage에 저장한다.
- **TEST**: compose 서비스 분리, Postgres storage 설정, `dagster-postgres` 의존성을
  고정하는 unit test를 추가했다.

### Public API — Response field hardening (2026-06-04)

- **CHANGED**: public `FeatureDetailResponse`에서 `coord_5179_srid`,
  `parent_feature_id`, `sibling_group_id`를 제거했다.
- **CHANGED**: `GET /features/nearby/by-target` 응답에서 target 내부 id/refresh policy와
  주변 feature의 `primary_provider`, `primary_dataset_key`를 제거했다. user OpenAPI
  profile도 같은 fieldset으로 갱신했다.
- **TEST**: router 응답과 `openapi.user.json` schema에 내부 필드가 남지 않는 회귀
  테스트를 추가했다.

### Admin API — Route gates (2026-06-04)

- **NEW**: `KRTOUR_MAP_ADMIN_ADMIN_ROUTES_ENABLED`와
  `KRTOUR_MAP_ADMIN_OPS_ROUTES_ENABLED` 설정을 추가했다. unset이면 둘 다
  `KRTOUR_MAP_ADMIN_FEATURES_ROUTES_ENABLED`를 따른다.
- **CHANGED**: DB 없는 부팅 검증에서 `features_routes_enabled=False`를 주면
  `/features/*`뿐 아니라 DB 의존 `/admin/*`, `/ops/*`, `/ops/dagster/*` 라우터도 함께
  mount하지 않는다. 필요하면 admin/ops flag를 명시해 별도로 다시 열 수 있다.
- **DOCS**: T-RV-27(admin API bind/노출)은 production 레벨 hardening 전까지 구현하지
  않고 deferred/skip으로 문서 추적한다.

### Admin API — Error envelope (2026-06-04)

- **CHANGED**: admin API의 `HTTPException`과 request validation error 응답을
  `{error:{code,message,details,request_id}}` envelope로 통일했다.
- **CHANGED**: `X-Request-ID` 요청 헤더가 있으면 같은 값을 응답 헤더와 envelope에
  되돌리고, 없으면 UUID를 생성한다.
- **TEST**: 공통 error envelope unit test를 추가하고, 기존 router error assertion을
  `detail`에서 `error.message` 기준으로 교정했다.

### Admin API — Offline upload 크기 상한 (2026-06-04)

- **NEW**: `KRTOUR_MAP_OFFLINE_UPLOAD_MAX_BYTES` 설정을 추가했다. 기본값은
  `104857600` bytes(100 MiB)다.
- **CHANGED**: `POST /admin/offline-uploads`는 설정 상한을 초과한 파일을 `413`으로
  거절한다. `Content-Length` 선차단과 `UploadFile.read(max_bytes + 1)` bounded read를
  함께 적용해 무제한 메모리 read를 막는다.
- **TEST**: oversize upload가 객체 저장소/DB 경로로 내려가지 않는 router unit
  regression test와 settings env override test를 추가했다.

### Ops — Batch DAG + consistency gate (2026-06-04)

- **NEW**: `krtour.map.infra.batch_dag.run_batch_dag_consistency_gate`와
  `AsyncKrtourMapClient.run_batch_dag_consistency_gate(...)`를 추가했다.
- **NEW**: Dagster `full_load_batch_consistency_gate` job을 추가했다. 기존 실제 source
  load import job을 root batch에 연결하고, child `done` 확인 뒤 consistency gate를
  실행한다.
- **CHANGED**: `severity_max=ERROR`이면 `mv_refresh`를 차단하고 root/gate import job을
  `failed`로 기록한다. OK/WARN이면 `mv_refresh` job을 기록하며, 현재 MV 카탈로그가
  없으면 `skipped:no_materialized_views`로 남긴다.
- **TEST**: unit coverage `800 passed` / `80.59%`, Dagster package `17 passed`, PostGIS
  integration `14 passed`, repo-wide `ruff`/`mypy`/import-linter를 확인했다.

### Ops — admin stack runner 안정화 (2026-06-04)

- **FIX**: `scripts/run-admin-stack.sh`가 시작 전 `alembic upgrade head`를 실행하고,
  API/frontend/Dagster를 `setsid` detached process로 기동하도록 수정했다.
- **FIX**: frontend wrapper PID가 먼저 종료되어도 URL readiness가 성공하면 정상 기동으로
  판단하도록 readiness 검사를 보정했다.

### Ops — import_jobs batch DAG 컬럼 (2026-06-04)

- **NEW**: `ops.import_jobs`에 `load_batch_id`와 `parent_job_id` self-FK를 추가했다.
  T-200 full-load root/child/gate job을 같은 batch로 묶기 위한 선행 스키마다.
- **NEW**: `/ops/import-jobs` 목록/상세 응답에 `load_batch_id`와 `parent_job_id`를
  포함하고, 두 UUID query filter를 추가했다.
- **CHANGED**: admin frontend `/ops/import-jobs` 목록에서 batch/parent id를 표시하고
  필터링할 수 있다.
- **TEST**: unit coverage `792 passed` / `80.56%`, admin package `132 passed`, Dagster
  package `15 passed`, migrated PostGIS integration `13 passed`, `ruff`/`mypy`/
  import-linter, OpenAPI drift, frontend `type-check`/`lint`/`build`, React Doctor를
  확인했다.

### Admin UI — Offline CSV/TSV validation + kraddr-geo bjd 보강 (2026-06-04)

- **NEW**: `GET /admin/offline-uploads/{upload_id}/preview`,
  `POST /admin/offline-uploads/{upload_id}/validate`,
  `GET /admin/offline-uploads/{upload_id}/validation`을 추가했다.
- **NEW**: CSV/TSV offline upload column mapping, header/sample preview, validation
  issue, validation job payload 저장, load 전 validation gate를 추가했다.
- **NEW**: admin frontend `/admin/offline-uploads`에 CSV/TSV mapping/preview/validation
  panel을 추가했다.
- **CHANGED**: `bjd_code`가 없는 offline/provider 행은 kraddr-geo REST v2 geocode 또는
  reverse 결과로 법정동코드를 보강한다. resolver가 없거나 결과가 없으면 validation
  issue로 남긴다.
- **CHANGED**: Dagster `offline_upload_load`가 validation job의 column mapping을
  재사용해 CSV/TSV 원본을 PostGIS에 적재한다.
- **FIX**: integration shared testcontainer DB에서 PostGIS extension을 `DROP ... CASCADE`
  해 `feature.features` geometry 컬럼을 지우던 fixture 순서 의존 문제를 수정했다.
- **DOCS**: ADR-045 전체점검 task를 `T-212a`~`T-212e`로 분리하고 실행 계획 문서를
  추가했다.
- **TEST**: unit-only coverage `792 passed` / `80.54%`, integration/admin/dagster
  `293 passed`, targeted backend/provider/router unit `114 passed`, offline upload
  PostGIS integration `4 passed`, repo-wide `ruff`/`mypy`/import-linter, frontend
  `type-check`/`lint`/`build`, React Doctor, admin/ops Playwright e2e `6 passed`,
  OpenAPI drift check를 확인했다.

### Admin UI — Offline uploads API/UI (2026-06-03)

- **NEW**: `POST /admin/offline-uploads`, `GET /admin/offline-uploads`,
  `GET /admin/offline-uploads/{upload_id}`,
  `POST /admin/offline-uploads/{upload_id}/load`를 추가했다.
- **NEW**: admin frontend `/admin/offline-uploads` 화면을 추가했다. JSON/JSONL
  `FeatureBundle` 파일 업로드, state/provider/dataset 필터, 상세 panel, Dagster load
  실행을 지원한다.
- **CHANGED**: `infra.offline_upload_repo`가 API가 생성한 `upload_id`를 받을 수 있고,
  `created_at DESC, upload_id DESC` keyset 목록을 제공한다.
- **CHANGED**: frontend 공통 API client에 `postFormData()`를 추가했다.
- **TEST**: offline upload router unit test, migrated PostGIS list/load integration,
  frontend type-check/lint/build, React Doctor, OpenAPI admin/user drift check를
  수행했다.

### 운영 — RustFS offline upload store wiring (2026-06-03)

- **NEW**: `krtour.map.infra.file_store.S3ObjectStore`를 추가했다. boto3 호환
  S3 client를 async wrapper로 감싸고, 읽기/쓰기 실패는 `FileStoreError`로 표준화한다.
- **NEW**: `krtour.map_dagster.resources.offline_upload_store_resource`를 추가했다.
  Dagster `offline_upload_load` job이 `KRTOUR_MAP_OBJECT_STORE_*`와
  `KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET` 설정으로 RustFS/S3 호환 bucket을 읽는다.
- **CHANGED**: `KrtourMapSettings`와 `.env.example`의 object store field/env 이름을
  정렬했다. offline upload bucket 기본값은 `krtour-uploads`다.
- **CHANGED**: Docker compose stack에 RustFS API `9003`, console `9004`,
  `rustfs-init` bucket 생성 경로를 추가했다.
- **TEST**: S3 store/resource/definitions/offline upload Dagster unit test,
  `docker compose config --quiet`, 실제 Docker RustFS put/get smoke를 추가했다.

### 운영 — Dagster offline upload load job (2026-06-03)

- **NEW**: `ops.offline_uploads` 테이블과 repository를 추가했다. RustFS 등 객체
  저장소의 원본 파일 메타데이터를 보존하고 validation/load `import_jobs`와 연결한다.
- **NEW**: `AsyncKrtourMapClient.run_offline_upload_load_job()`을 추가했다. 업로드
  원본 파일을 store resource에서 읽어 size/checksum을 검증하고 JSON/JSONL
  `FeatureBundle`로 파싱한 뒤 PostGIS에 적재한다.
- **NEW**: `offline_upload_load` Dagster job을 추가했다. `upload_id` config와
  `offline_upload_store` resource를 받아 수동 실행한다.
- **TEST**: parser/Dagster unit test와 migrated PostGIS 통합 테스트를 추가했다.
  통합 테스트는 성공 적재와 checksum 실패 시 `import_jobs=failed` /
  `offline_uploads=load_failed` 전이를 검증한다.

### 운영 — Dagster consistency/dedup refresh job (2026-06-03)

- **NEW**: `consistency_dedup_refresh` Dagster job을 추가했다. DB에 적재된
  provider/dataset scope를 pair/sibling 방식으로 다시 읽어 dedup 후보 큐를 갱신한 뒤
  F1~F4 consistency report를 저장한다.
- **NEW**: `AsyncKrtourMapClient`에 DB 기준 dedup pair/sibling refresh와 consistency
  report 실행 메서드를 추가했다.
- **NEW**: `consistency_dedup_refresh_daily_schedule`을 추가했다. KST `45 5 * * *`,
  기본 status는 `STOPPED`다.
- **TEST**: Dagster job config/metadata unit test와 PostGIS client 경로 integration
  test를 추가했다.

### Admin UI — 최신 운영 화면 구현 (2026-06-03)

- **NEW**: admin frontend에 전역 `AdminShell` navigation, 공통 `StatusBadge`, format
  helper를 추가했다.
- **NEW**: `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets` 화면을 추가했다.
- **CHANGED**: 홈(`/`)을 feature/import job/dedup/integrity issue/Dagster 상태를
  보는 운영 dashboard로 교체했다.
- **CHANGED**: `/admin/dagster`는 Dagster webserver embed와 자체 summary UI를 함께
  제공하며 schedules/sensors 정보를 표시한다.
- **CHANGED**: `/features` header에 jobs/update/target/dedup/Dagster 운영 화면으로
  이동하는 quick link를 추가했다.
- **CHANGED**: `scripts/stop-fixed-ports.sh`가 WSL 일반 PID, WSL root listener,
  Windows `node.exe`/`wslrelay.exe` listener를 감지해 9011/9012/9013 stale 포트를
  정리한다.
- **CHANGED**: `scripts/load-env.sh`의 기본 CORS origin에 WSL IP 기반
  `http://<WSL-IP>:9012`를 포함해, Windows localhost relay가 죽었을 때도
  `E2E_BASE_URL` WSL IP fallback으로 브라우저 검증이 가능하게 했다.
- **CHANGED**: `krtour.map_admin.app`이 설정된 CORS origin에 대해 응답과 preflight
  헤더를 한 번 더 보강해 WSL IP fallback 경로에서도 frontend fetch가 막히지 않게 했다.
- **TEST**: Playwright e2e를 새 home dashboard와 신규 admin/ops route smoke 기준으로
  갱신했다.

### Admin UI — 최신화 선행 API 계약 (2026-06-03)

- **NEW**: `docs/admin-ui-modernization-gap-audit.md`를 추가해 최신 admin UI 요구사항과
  실제 REST/Dagster/frontend 구현 차이를 route별로 정리했다.
- **NEW**: admin frontend에 `/ops/import-jobs`, `/ops/metrics`,
  `/ops/consistency/*`, `/admin/dedup-review`, `/admin/feature-update-requests`,
  `/admin/poi-cache-targets`, `/features/nearby/by-target` typed hook module을
  추가했다.
- **CHANGED**: frontend 공통 API client가 `GET/POST/PUT/PATCH/DELETE` JSON helper와
  query-string builder를 제공한다.
- **CHANGED**: frontend `npm test`가 Playwright e2e spec을 Vitest unit test로
  잘못 수집하지 않도록 `e2e/**`를 제외한다. Playwright는 `npm run e2e`로 실행한다.
- **CHANGED**: 문서의 과거 `/admin/import-jobs` 기본 API 표기를 현재 정본
  `/ops/import-jobs`로 정리했다.

### 운영 — Dagster provider schedules (2026-06-03)

- **NEW**: `packages/krtour-map-dagster`에 Feature 적재 asset 9개의 KST schedule과
  asset job을 등록했다.
- **CHANGED**: 모든 provider schedule은 `execution_timezone="Asia/Seoul"`을 사용하고,
  외부 API 호출이 몰리지 않도록 분/요일을 분산한다. 기본 status는 운영자가 명시적으로
  켜기 전까지 `STOPPED`다.
- **TEST**: Dagster `Definitions`에 schedule/job이 등록되고 cron/timezone/tag가
  일치하는지 검증하는 smoke test를 추가했다.

### 운영 — OpenAPI admin/user 이원화 (2026-06-03)

- **NEW**: `packages/krtour-map-admin/openapi.user.json`을 추가했다. TripMate/user
  client가 사용하는 `/features/*`, `/tripmate/features/batch`,
  `/admin/feature-update-requests` 일부 method만 포함한다.
- **CHANGED**: `packages/krtour-map-admin/scripts/export_openapi.py`에
  `--profile admin|user|all`과 `--user-output`을 추가했다. 기본 admin export는 기존
  `openapi.json` 경로/동작을 유지한다.
- **CHANGED**: `.github/workflows/openapi.yml` drift gate가
  `--profile all --check`로 admin/user OpenAPI 산출물을 함께 검증한다.
- **TEST**: user profile route filtering, method filtering, schema pruning을 검증하는
  export script unit test를 추가했다.

### 운영 — TripMate/public feature read API (2026-06-03)

- **NEW**: `krtour-map-admin`에 `GET /features/in-bounds`,
  `GET /features/search`, `POST /tripmate/features/batch`를 추가했다.
- **CHANGED**: `GET /features/{feature_id}`는 public envelope
  `{data, meta.duration_ms}` 응답으로 전환하고 `updated_at`을 포함한다. 기존
  admin frontend 상세 호출은 envelope를 풀어 읽도록 갱신했다.
- **CHANGED**: `feature_repo.features_in_bbox`에 category filter를 추가하고,
  `get_feature_rows_by_ids`, `search_features`를 추가했다. 검색은 `pg_trgm`
  `%` 연산자와 transaction-local similarity threshold를 사용한다.
- **CHANGED**: `packages/krtour-map-admin/openapi.json`을 T-207e endpoint 기준으로
  갱신했다.
- **TEST**: `/features`/`/tripmate` 라우터 unit test, feature repo cursor/validation
  unit test, PostGIS batch/search/bbox 통합 테스트, frontend lint/type-check를
  추가·갱신했다.

### 운영 — `/ops/*` consistency/jobs/metrics API (2026-06-03)

- **NEW**: `krtour-map-admin`에 `GET /ops/metrics`, `GET /ops/import-jobs`,
  `GET /ops/import-jobs/{job_id}`, `GET /ops/consistency/reports`,
  `GET /ops/consistency/issues`를 추가했다.
- **NEW**: `infra.ops_repo`를 추가했다. `ops.import_jobs`,
  `ops.feature_consistency_reports`, `ops.data_integrity_violations`를 read-only
  keyset cursor로 조회하고, 열린 issue 집계를 제공한다.
- **CHANGED**: `packages/krtour-map-admin/openapi.json`을 T-207d endpoint 기준으로
  갱신했다.
- **TEST**: `/ops` 라우터 unit test와 PostGIS ops repository 통합 테스트를 추가했다.

### 운영 — Admin feature review/deactivate API (2026-06-03)

- **NEW**: `krtour-map-admin`에 `GET /admin/features`,
  `POST /admin/features/{feature_id}/deactivate`, `GET/PATCH /admin/dedup-review`를
  추가했다.
- **NEW**: `alembic 0010`으로 `ops.feature_overrides`를 추가했다. active
  `field_path='status'` override는 `prevent_provider_reactivation` 플래그로 provider
  재적재가 운영자 비활성화를 되살리지 못하게 한다.
- **CHANGED**: `feature_repo.upsert_feature`가 active status override가 있는 feature의
  status/deleted_at을 provider payload로 덮지 않는다.
- **TEST**: admin feature/dedup 라우터 unit test, PostGIS deactivate/override/upsert
  통합 테스트, OpenAPI export를 추가했다.

### 운영 — Dagster feature update sensor (2026-06-03)

- **NEW**: `krtour-map-dagster`에 `feature_update_request_queue_sensor`와
  `feature_update_request_worker` job을 추가했다. sensor는 queued request를 상태 변경
  없이 peek한 뒤 request id를 Dagster `RunRequest` config/tag로 전달한다.
- **NEW**: `feature_update_request_failure_sensor`를 추가했다. worker run 실패 시
  request/import job 실패 전이를 보강하고, 선택 notifier resource로 알림 payload를
  전달한다.
- **CHANGED**: `AsyncKrtourMapClient`와 `infra.feature_update_repo`에
  `peek_next_update_request`를 추가하고, client에 `fail_update_request`를 추가했다.
- **TEST**: Dagster sensor/job unit test와 feature update repo/client PostGIS 통합
  테스트를 추가했다.

### 운영 — POI/cache target admin API (2026-06-03)

- **NEW**: `krtour-map-admin`에 `PUT/GET/DELETE /admin/poi-cache-targets`와
  `GET /features/nearby/by-target`를 추가했다. 외부 앱 POI는
  `external_system + target_key + 좌표 + radius`로 식별한다.
- **NEW**: `feature_repo.features_nearby_poi_cache_target`를 추가했다. target의
  `coord_5179` 기준 `ST_DWithin` 거리 조회, kind/category/status/provider 필터,
  `distance`/`name`/`last_updated_at` keyset cursor를 지원한다.
- **TEST**: admin 라우터 unit test와 PostGIS 주변 feature/cursor 통합 테스트를
  추가하고 OpenAPI export를 갱신했다.

### 운영 — Feature update admin API (2026-06-03)

- **NEW**: `krtour-map-admin`에 `POST/GET /admin/feature-update-requests`,
  `GET /admin/feature-update-requests/{request_id}`,
  `POST /admin/feature-update-requests/{request_id}/cancel`,
  `POST /admin/feature-update-requests/{request_id}/run-now` 라우터를 추가했다.
- **CHANGED**: `list_update_requests`와 `AsyncKrtourMapClient.list_update_requests`가
  `scope_type`, `provider`, `dataset_key`, `created_from`, `created_to` 필터를 받는다.
- **TEST**: admin 라우터 unit test, OpenAPI export 갱신, provider/dataset JSONB 필터
  PostGIS 통합 테스트를 추가했다.

### 운영 — Feature update request 실행 본체 (2026-06-03)

- **NEW**: `infra.feature_update_executor`를 추가했다. queued request claim,
  실행 시점 scope 재해석, provider/dataset 실행 계획, provider refresh policy 필터,
  target link 재계산, request/import job terminal 전이를 한 흐름으로 묶는다.
- **NEW**: `cache_target_keys` scope resolver를 추가했다. active POI/cache target
  주변 feature를 PostGIS로 계산하고 missing/deleted/disabled key를 `matched_scope`에
  기록한다.
- **CHANGED**: `AsyncKrtourMapClient`에
  `execute_next_feature_update_request`와 `execute_feature_update_request`를 추가했다.
  실제 provider 호출은 runner 주입형이며 Dagster sensor 연결은 후속 T-208e에서
  진행한다.
- **TEST**: target 기반 request가 runner를 통해 feature를 DB 적재하고
  `ops.poi_cache_target_feature_links`와 target refresh 타임스탬프를 갱신하는 PostGIS
  통합 테스트를 추가했다.

### 운영 — Phase 2 ops 스키마 (2026-06-03)

- **NEW**: `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies` 테이블을
  `alembic 0009`로 추가했다.
- **NEW**: `infra.integrity_violation_repo`, `infra.poi_cache_target_repo`,
  `infra.provider_refresh_policy_repo`를 추가했다. 후속 admin API/Dagster 실행 본체가
  공유할 raw SQL repository 표면이다.
- **TEST**: Phase 2 ops schema/repository PostGIS 통합 테스트를 추가했다.

### 운영 — Feature update client 표면 (2026-06-03)

- **NEW**: `AsyncKrtourMapClient`에
  `enqueue_feature_update_request`, `get_update_request`, `list_update_requests`,
  `cancel_update_request`를 추가했다. Dry-run은 DB write 없이 preview를 반환하고,
  실제 enqueue/cancel은 client가 transaction 경계를 소유한다.
- **CHANGED**: `from krtour.map import AsyncKrtourMapClient` top-level import를 실제
  public export로 맞추고, TripMate 직접 import 설명을 ADR-045 OpenAPI 운영 모델
  기준으로 정정했다.
- **DOCS**: RustFS 로컬 표준 포트를 S3 API `9003`, console `9004`로 정리했다.

### 운영 — Feature update request 큐 repository (2026-06-03)

- **NEW**: `infra.feature_update_repo`를 추가했다. Dry-run preview, request enqueue,
  priority 기반 claim, start/finish/cancel, 단건 조회, keyset cursor 목록 조회를
  지원한다.
- **CHANGED**: 실제 실행 request 생성 시 `ops.import_jobs` row를 같은 transaction에
  만들고, claim/start/finish/cancel 상태 전이를 request와 import job에 함께 반영한다.
- **DOCS**: kraddr-geo REST API 로컬 포트 기준을 `http://127.0.0.1:9001`로 정정했다.

### 운영 — Feature update scope resolver (2026-06-03)

- **NEW**: `infra.scope_repo`를 추가했다. `feature_ids`, `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset` scope를 feature 집합과 `matched_scope`
  payload로 해석한다.
- **CHANGED**: `sigungu_by_radius` 해석은 `infra`가 kraddr-geo를 직접 import하지 않고
  주입받은 async resolver의 5자리 `sigungu_code` 결과를 사용한다.

### 운영 — Feature update request 큐 스키마 (2026-06-03)

- **NEW**: `ops.feature_update_requests` 테이블과 `FeatureUpdateRequestRow` 매핑을
  추가했다. Admin/OpenAPI feature update request를 `ops.import_jobs`와 Dagster run에
  연결하기 위한 기반 스키마다.
- **DOCS**: `sigungu_by_radius` scope 설명을 kraddr-geo REST v2
  `/v2/regions/within-radius` 기준으로 정리했다. krtour-map 내부에 행정경계 테이블을
  만들지 않는다.

### Admin UI — Dagster 운영 화면 (2026-06-02)

- **NEW**: backend `GET /ops/dagster/summary`를 추가했다. Dagster GraphQL에서
  version, code location, asset group, schedule/sensor, 최근 run 요약을 읽어 admin
  UI용 DTO로 정규화한다.
- **NEW**: frontend `/admin/dagster` 화면을 추가했다. 자체 운영 요약 카드/asset
  group/recent run 표와 Dagster webserver embed를 한 화면에서 제공한다.
- **CHANGED**: 홈 화면에서 Dagster 상태 요약과 `/admin/dagster` 진입 링크를 표시한다.
- **CHANGED**: `GET /ops/dagster/summary`는 성공 시 Dagster `setNuxSeen`을
  best-effort로 호출해 embedded 관리 화면의 로컬 첫 실행 모달을 접는다.
- **CHANGED**: 로컬/Docker Dagster 실행 기본값에 `DAGSTER_DISABLE_TELEMETRY=yes`를
  추가해 embedded 관리 화면의 외부 telemetry 동작을 줄인다.

### 운영 — Docker 이미지 + 고정 포트 (2026-06-02)

- **NEW**: `docker-compose.yml`과 `docker/{api,frontend,dagster}.Dockerfile`을 추가했다.
  독립 PostGIS, API, admin UI, Dagster를 같은 compose에서 기동한다.
- **CHANGED**: Docker API 컨테이너는 `.env`의 로컬 Dagster URL 대신
  `KRTOUR_MAP_DOCKER_ADMIN_DAGSTER_URL` 기본값(`http://dagster:9013`)을 내부
  `KRTOUR_MAP_ADMIN_DAGSTER_URL`로 사용한다.
- **CHANGED**: 로컬/standalone 고정 포트를 API `9011`, admin UI `9012`, Dagster
  `9013`으로 표준화했다.
- **NEW**: `.env`의 provider service key를 `KRTOUR_MAP_ADMIN_*`/`NEXT_PUBLIC_*`
  환경변수로 매핑하는 `scripts/load-env.sh`와 포트 종료/로컬 stack/Docker 기동
  스크립트를 추가했다.

### Admin UI — frontend stack 전환 + geocoding admin 표면 제거 (2026-06-02)

- **CHANGED**: `krtour-map-admin` frontend를 문서화된 stack 기준으로 재정렬했다.
  Next.js 16 + React 19 + TanStack Query + Zustand + Zod + React Hook Form +
  shadcn/ui + `maplibre-vworld-js`를 기준으로 홈/ETL preview/Feature 지도 화면을
  구성한다.
- **REMOVED**: geocoding 전용 admin/debug 라우터, frontend `/geocoding` 화면,
  관련 e2e/router/live 테스트를 제거했다. geocoding 자체 디버깅은
  `python-kraddr-geo` 프로젝트 책임으로 둔다.
- **CHANGED**: `packages/krtour-map-admin/openapi.json`에서 `/debug/geocoding/*` 경로와
  `GeocodingHealthResponse` schema를 제거했다.
- **DOCS**: React Doctor 실행/검토 기준에 맞춰 `doctor` script와
  `doctor.config.json`을 추가하고, 실제 경고를 검토해 앱 metadata, MapLibre cleanup,
  정렬/폼 오류 표시 코드를 개선했다.

### 문서 — ADR-046 정본 전환 + kraddr-geo v2 주소 정책 (2026-06-02)

- ADR-045 이행 시 legacy 호환 shim을 남기지 않고 `krtour-map-admin`, 독립 DB,
  독립 Dagster, OpenAPI 연동을 정본으로 삼는 ADR-046을 추가했다.
- provider 주소/좌표 정본을 kraddr-geo REST v2 `POST /v2/reverse`,
  `POST /v2/geocode` 결과로 통일하고, provider 원문 주소는 provenance로 보존하는
  정책을 문서화했다.
- 주소/좌표 매칭 실패, 결측, reverse/geocode 실패를 admin UI `/admin/issues`에서
  재시도·수동 수정·kraddr-geo 주소 채택·ignore/reopen 할 수 있도록 OpenAPI/UI
  사양을 보강했다.

### 문서 — ADR-045 독립 프로그램/OpenAPI 전환 (2026-06-01)

- krtour-map 운영 모델을 Docker 독립 프로그램 + 독립 PostgreSQL/PostGIS DB + 독립
  Dagster + TripMate OpenAPI 연동으로 전환하는 ADR-045를 추가했다.
- Admin 우선 OpenAPI, Dagster feature update request, POI/cache target 기반 주변
  feature 캐시 갱신, provider refresh policy/rate limit, frontend React Doctor 필수
  검증 사양을 문서화했다.

### Sprint 4 — 운영 CLI (2026-06-01~)

- **CHANGED**: coverage 게이트 `fail_under` 75 → **80** 상향 (ADR-032 Sprint 4 목표
  도달, 실측 94.12%). 모든 tier 충족(core/infra/providers/전체 ≥ 목표). Sprint 4b 종료.
- **NEW**: Place 전화번호 보강(`krtour.map.enrichment`, Sprint 4b 백그라운드 시작) —
  전화번호 없는 MOIS place 후보 발굴(`find_place_phone_candidates`) + 외부 lookup
  결과 보강(`apply_place_phone_enrichment` — `detail.phones` 정규화·dedup·max3 갱신 +
  `source_links(role='enrichment')` 이력). 외부 API(kakao/naver/google) 호출은 호출자
  책임(ADR-006 — 결과 주입). `AsyncKrtourMapClient.find_place_phone_candidates` /
  `enrich_place_phone` + `infra.feature_repo.{find_place_features_without_phone,
  set_feature_phones}`.
- **NEW**: ADR-033 **F4** 정합성 검사 — `infra.consistency`에 dedup 백로그 baseline
  체크 추가. `ops.dedup_review_queue` 미해소(pending) 수가
  `DEDUP_PENDING_WARN_THRESHOLD`(provisional 1000, `run_consistency_checks(...,
  dedup_pending_threshold=N)`로 override) 초과 시 severity=**WARN**(observe-only —
  적재 차단 없음, Phase 1). F1~F3(행별 정적 SQL)과 달리 임계 초과 집계 케이스.
- **NEW**: dedup 운영 FP 측정 — `infra.status_repo.dedup_fp_stats`(dedup_review_queue
  status별 카운트 → confirmed=merged+accepted / FP=rejected / precision / fp_rate;
  ignored·pending 제외) + `krtour-map status` 출력에 `dedup FP(운영)` 라인 추가.
  운영자가 `dedup-merge`/reject로 큐를 해소하면 실 FP율이 자동 집계된다(검토 완료
  후보 0이면 "검토 완료 후보 없음"). ADR-016 dedup-fp 리포트의 후속 운영 측정 도구.
- **NEW**: MOIS Step D on-demand 상세 — debug-ui `GET /debug/mois-license/{license_id}`.
  적재된 MOIS feature의 원본 provider payload(`source_records.raw_data`) + feature
  core를 조립해 반환하고 프로세스 내 TTL 캐시에 담는다(**캐시만, DB write 없음**).
  `license_id` = `source_entity_id`(`{slug}::{mng_no}`). 신규
  `infra.get_primary_source_detail`(읽기 전용 단건 조회) + `routers/mois_detail`.
  미적재 시 404. `features_routes_enabled` + `debug_routes_enabled` gate.
- **NEW**: MOIS Step C 폐업/취소 처리 — `krtour-map import mois <file> --mode closed
  --cursor <값>`. provider가 `closed`/`cancelled`로 통지한 인허가 record의 대응
  feature를 `status='inactive'`+`deleted_at`으로 전환한다(ADR-017 — place는 무기한
  유지, status만 inactive; 새 feature 생성 없음). `infra.inactivate_features_by_
  source_entity_ids`(soft-delete inverse) + `mois.close_mois_license_features` /
  `run_mois_license_closed_job`(advisory lock + import_jobs + closed dataset cursor)
  + `AsyncKrtourMapClient` 메서드. `--cursor` 미지정 시 exit 2.
- **NEW**: MOIS Step B 증분 적재 — `krtour-map import mois <file> --mode incremental
  --cursor <값>`. 변경분만 upsert(snapshot prune 없음)하고 성공 시
  `provider_sync.provider_sync_state`의 cursor(`{"last_modified_date": …}`)를 전진
  시킨다(`--sync-scope`로 scope 분리). 신규 `infra/sync_state_repo`
  (get/record_success/record_failure) + `mois.run_mois_license_incremental_job`
  (advisory lock + import_jobs + cursor) + `AsyncKrtourMapClient` 메서드. `--cursor`
  미지정 시 exit 2. (Step C 폐업 처리는 별도 — 증분은 사라진 record를 비활성화하지
  않는다.)
- **NEW**: `krtour-map dedup-merge <review_key>` — dedup 검토 큐 후보 1쌍 수동 병합
  (ADR-016). master를 `select_master`(좌표 보유 → `updated_at` 최신 → 원천 우선순위
  행안부>TourAPI>사용자)로 자동 선정하고, loser의 `source_links`를 master로 재지정
  (충돌 키는 drop), loser feature를 soft-delete(`status='deleted'`), 신규
  `ops.feature_merge_history`(alembic 0007)에 이력 기록, 큐 행을 `merged` 전이한다.
  `dedup-merge:{review_key}` advisory lock으로 중복 실행 차단(ADR-039), 미획득 시
  skip(exit 3); 미존재/이미 검토된 review_key는 exit 2. `--merged-by`/`--reason`
  옵션. (SPRINT-4 §2.8의 예시 인자 `<feature_id>`는 후보쌍을 유일 식별하는
  `<review_key>`로 구체화.)
- **NEW**: `krtour-map import mois <records-file>` — MOIS 인허가 Step A bulk 적재
  CLI 명령. provider가 export한 provider-neutral **NDJSON snapshot**(한 줄당 JSON
  object)을 record source로 읽어(ADR-006 — provider 라이브러리 미import)
  `run_mois_license_bulk_job`으로 적재한다. `import:python-mois-api:<dataset>`
  advisory lock 단일 워커 직렬화(ADR-039) + `import_jobs` 추적(ADR-011); 다른
  워커가 적재 중이면 skip(exit 3). `--geocoder-url`로 좌표 → bjd_code 역지오코딩
  보강(kraddr-geo REST) 선택. `--dataset-key`/`--batch-size`/`--source-checksum`
  옵션. (`cli/records.py` NDJSON 리더 + `cli/main.py` import 서브명령.)
### Sprint 3 — DB 적재 오케스트레이션 + dedup + geocoding REST + e2e (2026-05-29~30)

- **PR#115 — PR review 누락 보강 + 문서 정합성 sweep**:
  2026-05-28 이후 PR #45~#114를 재조회하고 review submission이 없던 PR에
  한국어 사후 상세 리뷰를 등록. 당시 문서에서는 구 geocoding REST address endpoint와
  서비스 메타 버전 2.0 표현을 분리하고, accepted ADR을 proposed로 부르던 문구와
  `PlaceCoordinate` 잔존 예시, `docs/tasks.md` 현재 상태 drift를 정정.
- **PR#114 — kraddr-geo 최신 로컬 포트 정합 + 라이브 검증 보강**:
  `python-kraddr-geo` 최신 로컬 정책(`docs/ports.md`)에 맞춰 debug-ui
  geocoding 기본 base URL과 live 테스트 기본값을 `http://127.0.0.1:8888`로
  고정. frontend 의존도 로컬 최신 `maplibre-vworld-js#v0.1.2` + Next.js 16
  기준으로 올리고 `next lint` 제거에 맞춰 ESLint CLI flat config를 추가.
  WSL 시스템 `libgdal 3.8.4`와 맞도록 Python `gdal` binding을
  `==3.8.4`로 고정. `.env.example`/README/debug-ui/address-geocoding 문서를
  함께 갱신.
- **PR#93 — frontend CI 게이트** (`.github/workflows/frontend.yml`): Node 20 +
  workspace `npm install` + `tsc --noEmit` + `next build` (paths 필터). PR#92
  회고에 따라 잠복 syntax/타입 오류를 PR 머지 전에 차단.
- **PR#92 — npm workspace 루트 + frontend WSL 기동 + Windows Playwright e2e 7/7** (#117):
  루트 `package.json`(workspaces: map-marker-react + debug-ui/frontend) +
  frontend `workspace:*` → npm 호환 `*`. `npm install`(419 pkgs, github
  `maplibre-vworld#v0.1.0` 포함) 성공. WSL backend(:8087) + frontend(:8610)
  기동 + Windows `npx playwright test` → home 4 + etl 3 = 7/7 통과 (실 backend
  연동). 검출+수정: `etl/page.tsx` JSDoc 주석의 `*/`가 블록 주석을 조기 종료해
  PR#44부터 잠복했던 빌드 버그 (frontend 미컴파일 환경에서 미검출).
- **PR#91 — Playwright e2e 스위트 + backend 라이브 검증 리포트** (#117):
  `frontend/playwright.config.ts` + `e2e/home.spec.ts`/`etl.spec.ts` (실
  backend `/debug/health`·`/debug/version`·`/debug/etl/*` 연동, role/heading
  + native select nth 선택자). `docs/reports/debug-ui-e2e-2026-05-29.md`에
  backend 5경로 실 HTTP 통과 증거 + 사람용 런북.
- **PR#90 — geocoding python API → REST address API 전환** (#123, 이후 v2로 supersede):
  `krtour.map.geocoding`을 in-process `AsyncAddressClient` 가정에서
  **kraddr-geo REST address API**로 재작성. structural Protocol을 실제
  `ReverseResponse`/`GeocodeResponse`/`AddressStructure`(vworld
  `level4LC=bjd_cd` 등)/`GeocodeExtension`으로 교체. 순수 변환
  `reverse_response_to_address` / `geocode_response_to_coordinate` + 새
  `KraddrGeoRestClient`(httpx 주입, TYPE_CHECKING-only import — 메인 패키지
  런타임 httpx 의존 X). 소비자 계약(`ReverseGeocoder` 등) 유지 →
  provider 무영향. `KRTOUR_MAP_KRADDR_GEO_BASE_URL` 설정 추가.
- **PR#89 — `AsyncKrtourMapClient` 적재/dedup 오케스트레이션** (#122):
  placeholder였던 라이브러리 진입점에 transaction 소유 메서드 구현 —
  `load_feature_bundles`(`infra.load_bundles` 래핑), `sync_dedup_candidates`
  (`core.dedup` + `infra.enqueue_dedup_candidates`), 읽기
  (`get_feature`/`features_in_bounds`/`pending_dedup_reviews`). engine 수명은
  호출자 소유. unit 2 + integration 3 (testcontainers, teardown TRUNCATE).
- **PR#88 — `ops.dedup_review_queue` 적재 + `infra/dedup_repo.py`** (#122):
  alembic 0005 (`ops.dedup_review_queue` — UUID PK, FK→features CASCADE,
  `NUMERIC(5,2)` 0~100 score, `ck_dedup_scores`/`ck_dedup_status`,
  `idx_dedup_status_score`). 점수 0.0~1.0 → 0~100 변환,
  검토완료 행 보존 upsert(`DO UPDATE ... WHERE status='pending'`).
- **PR#87 — `core/dedup.py` cross-provider 중복 후보** (#121):
  `find_dedup_candidates(left, right, *, include_auto_merge)` 순수 함수 —
  `score_pair`(ADR-016)로 cross-score, `KEEP_SEPARATE` 제외, score 내림차순.
  `DedupInput` Protocol(`Feature`가 그대로 만족) + `DedupCandidate` frozen
  dataclass. unit 6.
- **PR#86 — `geometry_area_square_meters` 측지 면적 + krheritage AREA 보강** (#120):
  `pyproj.Geod(ellps='WGS84').geometry_area_perimeter` 측지 면적,
  krheritage AREA 변환기가 `AreaDetail.area_square_meters` 채움 + 단위 4건.

### Sprint 2 prep (2026-05-26, PR#28+)

- **PR#29 — `core/scoring.py` (ADR-016 Record Linkage) + `core/providers.py`**:
  Sprint 2 첫 provider 적재 전 dedup scoring + provider 이름 정규화 인프라.
  - `core/providers.py` — `CANONICAL_PROVIDER_NAMES` 18종 (모든 형제 provider
    + data.go.kr-standard + 외부 보강 3종) + `PROVIDER_ALIASES` 24종 (ADR-024
    krmois→mois 포함) + `normalize_provider_name` (raise on unknown, silent
    fallback 금지) + `is_known_provider` (lenient bool).
  - `core/scoring.py` (ADR-016 SPEC V8 D-14):
    - 가중치 상수: `WEIGHT_NAME=0.45`/`WEIGHT_SPATIAL=0.35`/`WEIGHT_CATEGORY=0.20`
    - 임계값 상수: `THRESHOLD_AUTO=0.85`/`THRESHOLD_MANUAL=0.65`/`SPATIAL_DECAY_METERS=50.0`
    - `normalize_kr_place_name` (NFKC + lower + 괄호 제거 + 모든 공백 제거)
    - `name_similarity` (jellyfish.jaro_winkler_similarity 정규화 후)
    - `haversine_meters` + `spatial_similarity(exp(-d/50))`
    - `category_similarity` (Jaccard)
    - `score_pair(*, ...)` (keyword-only) + `classify_decision(score)` →
      `DedupDecision.AUTO_MERGE/MANUAL_REVIEW/KEEP_SEPARATE`
  - `pyproject.toml`: `jellyfish>=1.0` 본 의존 추가.
  - **238 unit pytest passed** (PR#28 199 + 신규 32 + 미세 변동).
    ruff/mypy(31 src)/import-linter all green.
  - **`core/weather.py`는 Sprint 2 KMA PR (PR#31)으로 연기** — WeatherValue
    DTO 의존.
- **PR#28 — `infra/models.py` (SQLAlchemy 2 + GeoAlchemy2) + Alembic 첫 revision**:
  Sprint 2 첫 provider PR (visitkorea 축제)이 의존할 DB schema + ORM 매핑 + Alembic
  인프라 미리 박음.
  - `alembic.ini` + `alembic/env.py` (async-compatible, asyncpg + NullPool +
    SET search_path = public, x_extension) + `alembic/script.py.mako`.
  - `alembic/versions/0001_initial_schemas_and_extensions.py` — 4 schema
    (feature/provider_sync/ops/x_extension) + 3 extension (postgis/pg_trgm/
    pgcrypto) on `x_extension` (ADR-008). postgis는 image 기본 public 설치
    DROP CASCADE 후 재생성.
  - `alembic/versions/0002_features_and_source_tables.py` — features (ADR-012
    `coord_5179` STORED generated column + 10 indexes incl. GiST/GIN partial)
    + source_records (UNIQUE 5-tuple + 4 indexes incl. BRIN) + source_links
    (FK CASCADE/RESTRICT + 3 indexes) + provider_sync_state.
  - `src/krtour/map/infra/models.py` — `Base` (naming convention) + 4 row class
    (FeatureRow / SourceRecordRow / SourceLinkRow / ProviderSyncStateRow).
    Geoalchemy2 Geometry(POINT 4326/5179, GEOMETRY 4326) + CheckConstraint
    kind/status/coord_pair.
  - `tests/integration/test_alembic_upgrade.py` — 6 case: 4 schema / 3
    extension on x_extension / features 컬럼 / coord_5179 STORED / source 3
    tables / 핵심 5 인덱스.
  - `pyproject.toml`: `alembic>=1.13` 본 의존 추가.
  - **199 unit pytest passed** (코드 변경 없음 기존 + 통합 신규는 testcontainers
    필요). ruff/mypy/import-linter all green.

### Sprint 1 scaffolding (2026-05-25, PR#17+)

- **PR#26 — review P0-4 ID helpers + SourceRecord/Link/Bundle DTO**:
  Sprint 2 첫 provider 변환 함수 직전 필수 묶음.
  - `src/krtour/map/core/ids.py` 확장:
    - `make_source_record_key(*, provider, dataset_key, source_entity_type,
      source_entity_id, raw_payload_hash) -> str` — `sr_{sha1[:20]}` 포맷
      (`docs/data-model.md §11`).
    - `make_payload_hash(data, *, length=32) -> str` — canonical JSON 직렬화
      (`sort_keys` + `separators=(",", ":")` + `ensure_ascii=False` +
      `allow_nan=False`) → SHA256 hexdigest prefix. `datetime`/`date`는 ISO
      문자열, `Decimal`은 문자열로 정규화하고 `set`/`bytes`/임의 객체는
      거부한다. 1~64 hex char 길이 조정 가능.
    - `SOURCE_RECORD_KEY_HASH_LENGTH = 20`, `PAYLOAD_HASH_DEFAULT_LENGTH = 32`
      constants.
  - `src/krtour/map/dto/source.py` 신설 — `SourceRecord` (provider raw payload
    추적, 고유성 `(provider, dataset_key, source_entity_type, source_entity_id,
    raw_payload_hash)`) + `SourceLink` (Feature ↔ Source 1:N 매핑,
    `source_role`/`match_method`/`confidence`/`is_primary_source`).
    DB NOT NULL 계약에 맞춰 `source_record_key`/`fetched_at` 필수,
    `raw_data` 기본 `{}`. datetime aware validator (ADR-019).
  - `src/krtour/map/dto/bundle.py` 신설 — `FeatureBundle` (feature +
    source_record + source_link 3개 필수). `source_link.feature_id`와
    `source_link.source_record_key` 교차 검증. weather/price/file_sources 필드는
    Sprint 2 DTO 추가와 함께 enable.
  - **dto는 core를 import하지 않는다** (ADR-001/002 — import-linter 자동
    차단). `SourceRecord.key()` 메서드 두지 않음 — 호출자가
    `make_source_record_key(...)`로 계산해서 박는다.
  - 신규 tests: `test_ids_extended.py` + `test_dto_source_bundle.py`
    (e2e flow: raw_payload → payload_hash → source_record_key → feature_id →
    FeatureBundle, mismatch/unsupported payload negative case 포함).
- **PR#25 — KNPS keyless sync (python-knps-api PR#3+#4 반영)**:
  upstream knps-api commit `06da125f` 변경 본 라이브러리 docs/pyproject 일괄
  반영. **ADR-028 amendment §H** 신설 (keyless + file-only).
  - `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함 (인증 제거).
  - 14 dataset 모두 `kind="file_dataset"`. 신규 4건 (`knps_linear_facilities`,
    `knps_protected_areas`, `knps_basic_statistics`, `knps_lod_table_catalog`),
    제거 4건 (`knps_access_restrictions`, `knps_fire_alerts`,
    `knps_recommended_courses`, `knps_park_photos`).
  - 제거된 notice 2종 (`access_restriction`/`fire_alert`)은 산림청/소방청
    별도 source로 이전 (후속 ADR).
  - 공개 API 정정: `ApiEndpoint`/`Page`/`api_endpoint`/`raw_endpoint` 삭제,
    `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 신규.
  - 변경 docs: `decisions.md` (ADR-028 §H amendment) / `knps-feature-etl.md` /
    `forest-feature-etl.md §11` / `external-apis.md §3.8.1` /
    `provider-contract.md §3`. pyproject git URL 핀 (`@06da125f`) 주석.
  - DTO 정합 보강: `AreaDetail.area_kind='protected_area'`,
    `ROUTE_TYPE_FACILITY_ROAD='facility_road'` 추가. 143 pytest passed.
- **PR#24 — DTO strictness P0 (Sprint 2 진입 전 차단)**:
  Review report (`docs/reports/pr-1-21-review.md`, PR#23 DRAFT) P0-1/2/3 해소.
  - `Feature.detail` `mode="before"` dict 거부 (Pydantic union dict coercion
    차단, ADR-018 진짜 강제)
  - 모든 DTO datetime aware validator 일관 적용:
    - `Feature.created_at/updated_at/deleted_at` (이전 PR#19)
    - `NoticeDetail.valid_start_time/valid_end_time` (신규)
    - `RawDataRef.fetched_at` (신규)
  - `dto/_time.py`에 `check_aware_datetime()` 공용 helper 추가 + 모든 DTO에
    적용. ADR-019 해석 명시: "aware면 OK, naive 거부" (KST 변환은 provider 책임)
  - `Feature.category` `^\d{8}$` 정규식 validator (ADR-023 PlaceCategoryCode
    8자리). strict known-code는 후속 PR (transitional)
  - 신규 tests: `test_dto_time.py` (11 case) + dict reject 3건 split +
    category 8자리 2건 + notice datetime 3건. 141 passed total.
- **PR#22 — CI workflows + import-linter 활성화 (Sprint 1 scaffolding 종료)**:
  - `.github/workflows/ci.yml` — pytest unit + integration (testcontainers
    PostGIS, ADR-007) + coverage XML, Python 3.11/3.12/3.13 matrix +
    `concurrency` group으로 이전 run 자동 cancel.
  - `.github/workflows/lint.yml` — ruff check + mypy --strict
    (`krtour.map` 전체) + import-linter (4 계약).
  - `.github/workflows/openapi.yml` — ADR-031 drift gate. Sprint 1은
    `continue-on-error: true` (앱 모듈 미존재) — Sprint 2 첫 라우터 PR
    에서 제거.
  - `tests/lint/test_import_linter.py` — pyproject.toml의 4 계약 wrap
    (subprocess로 `lint-imports` 실행). 미설치 시 skip.
  - `pyproject.toml`: `include_external_packages = true` (외부 forbidden
    검증 활성화) + `layers`에서 `krtour.map.cli` 제거 (모듈 미존재).
  - **ADR-002 위반 1건 실 해소** — `KST`/`kst_now` 정의를
    `core/types.py` → `dto/_time.py`로 이전 (dto/feature.py가 core를
    역참조하던 위반 해소). 공개 API `from krtour.map.core import kst_now`는
    그대로 (core/types.py shim).
  - `tests/unit/test_dto_*.py` + `test_category.py` —
    `pytest.raises(Exception)` → 구체 예외 type (B017/PT011 해소).
  - **125 passed, 10 skipped** (전체) + ruff/mypy/import-linter all green.
- **PR#21 — `src/krtour/map/infra/` skeleton (crs + db + testcontainers)**:
  - `src/krtour/map/infra/crs.py` — `pyproj.Transformer` singleton
    (`@functools.cache`, ADR-030 narrow 예외): `transformer_4326_to_5179` /
    `transformer_5179_to_4326` + `project_to_5179` / `project_to_4326`
    + `EPSG_WGS84` / `EPSG_UTM_K`. `always_xy=True` 강제.
  - `src/krtour/map/infra/db.py` — `make_async_engine` (SQLAlchemy 2
    AsyncEngine + asyncpg) + `make_async_session_factory` +
    `normalize_async_dsn` (psycopg2/psycopg/postgres → asyncpg 통일).
    `SecretStr` 자동 처리.
  - `tests/integration/__init__.py` + `tests/integration/conftest.py` —
    testcontainers PostGIS 베이스 (`pg_container` session-scope `postgis/
    postgis:16-3.5-alpine`, `pg_engine` 4 schema + 3 extension 자동
    생성, `pg_session` per-test rollback). Docker/testcontainers 미설치
    시 자동 `pytest.skip`.
  - `tests/integration/test_pg_smoke.py` — postgis/pg_trgm/pgcrypto
    `x_extension` 격리 확인 (ADR-008) + 4 schema 존재 + ST_Transform
    4326↔5179이 pyproj와 1m 이내 일치.
  - `tests/unit/test_crs.py` 13 case + `tests/unit/test_db.py` 12 case
    (asyncpg 미설치 환경 4건 자동 skip).
  - `pyproject.toml`: `pyproj>=3.6` 본 의존 추가.
  - **124 passed, 10 skipped** (전체 suite).
- **PR#20 — `src/krtour/map/core/` 예외 계층 + ADR-009 `make_feature_id`**:
  - `src/krtour/map/core/exceptions.py` — `KrtourMapError` 베이스 + 7 도메인
    예외 (`ValidationError`/`FeatureNotFoundError`/`SourceRecordNotFoundError`/
    `DuplicateFeatureError`/`ImportJobConflictError`/`ProviderError`/
    `FileStoreError`). HTTP 매핑은 `docs/debug-ui-package.md §6.4`.
  - `src/krtour/map/core/ids.py` — `make_feature_id(*, bjd_code, kind,
    category, source_type, source_natural_key, content_hash=None)`. 포맷
    `f_{bjd or 'global'}_{kind[0]}_{sha1[:16]}` (ADR-009 SPEC V8 D-2).
    `usedforsecurity=False` 명시. `|` 구분자 / 빈 문자열 검증.
  - dto 의존 회피 — `kind: str` 타입 (PR#19 `FeatureKind` StrEnum은 str
    서브클래스이므로 그대로 호환, 호출 측 코드 변경 0).
  - `core/__init__.py` — PR#19(`KST`/`kst_now`) + PR#20(exceptions 7 + ids
    2) 통합 export, 총 12 공개 식별자.
  - `tests/unit/test_exceptions.py` 7 case + `tests/unit/test_ids.py` 35
    case (parametrize 포함). **72 passed** (전체 suite).
- **PR#19 — `src/krtour/map/dto/` Feature + 5 detail + ADR-027 적용**:
  - `core/types.py` — `KST` / `kst_now()` (ADR-019)
  - `dto/_enums.py` — FeatureKind 7 / FeatureStatus 6 / SourceRole 8
  - `dto/coordinate.py` — Coordinate (Korea bounds, frozen)
  - `dto/address.py` — Address basic
  - `dto/urls.py` — FeatureUrls + RawDataRef
  - `dto/opening_hours.py` — OpeningTime/Period/SpecialDay/FeatureOpeningHours
  - `dto/place.py`/`event.py`/`route.py` — Detail 모델 + ROUTE_TYPES 9종 +
    normalize_route_type
  - **`dto/notice.py`** — NoticeDetail + **NOTICE_TYPES 14건** (ADR-027
    `access_restriction`/`fire_alert` 포함) + normalize_notice_type
  - **`dto/area.py`** — AreaDetail + AREA_KINDS 12종 (ADR-027 `hazard_zone`)
  - `dto/feature.py` — Feature (ADR-018 detail discriminator, ADR-019 KST
    aware enforcement, marker_color P-01~P-16 regex)
  - `dto/__init__.py` — 38 공개 식별자 re-export
  - `tests/unit/test_dto_{notice,area,feature}.py` (27 cases)
  - **62 pytest passed** (전체 test suite)
- **PR#18 — `src/krtour/map/category/` 144건 (ADR-023 이전 + ADR-027)**:
  - `_definitions.py` (~2110줄, kraddr-base 사본 + ADR-027 패치)
  - ADR-027 신규 3건: `LODGING_MOUNTAIN_SHELTER` (Tier 2) +
    `LODGING_MOUNTAIN_SHELTER_KNPS` / `_KFS` (Tier 3) + maki = `shelter`
  - `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["03"]["08"] = "대피소·산장"`
  - `@cache` on `get_category` (ADR-030 narrow 예외, immutable 카탈로그)
  - `category/__init__.py` re-export 14 식별자
  - `tests/unit/test_category.py` (16 cases) — 144 총건/depth/Tier1/
    ADR-027/maki/helper/cache 검증. **30 passed** (전체 test suite)
  - `docs/category.md` §4.3 depth 통계 정정 (원본 Tier 2/4 swap 오류)
- **PR#17 — `src/krtour/map/` PEP 420 scaffolding**:
  - `src/krtour/map/__init__.py` (`__version__ = "0.2.0-dev"`)
  - `src/krtour/map/py.typed` (PEP 561)
  - `src/krtour/map/settings.py` — `KrtourMapSettings(BaseSettings)`
    (pg_dsn / object_store_* / log_*)
  - `src/krtour/map/{category,dto,core,infra,providers,client}/__init__.py`
    (placeholder, 후속 PR에서 채움)
  - `pyproject.toml`: `pydantic-settings>=2.4` 의존 추가
  - `tests/lint/test_no_namespace_init.py` — ADR-022 PEP 420 enforcement
  - `tests/unit/test_smoke_import.py` — `krtour.map` + `KrtourMapSettings`
    smoke (5 cases)

### Sprint 1 진입 (2026-05-25, PR#16)

- **T-014 — 코드 작성 단계 진입**: 사용자 승인. Sprint 1 = **active**.
- **ADR 8건 일괄 proposed → accepted 전환** (ADR-027/028/029/030/031/032/
  033/034). 모두 main에 text on accepted 상태.
- `pyproject.toml` `[tool.coverage.report] fail_under` 0 → **50** (ADR-032
  Sprint 1 bar).
- `docs/sprints/SPRINT-1.md` 상태 → active. SPRINT-2~5.md 상태 → accepted
  (시기 대기).
- 후속 Sprint 1 scaffolding PR sequence (PR#17~#23): `src/krtour/map/`
  PEP 420 + `category/` 144건 + `dto/` (NOTICE_TYPES 14건 + AreaDetail.
  area_kind hazard_zone) + `core/` + `infra/` + CI workflows + 첫 통합
  테스트.

### 결정 (2026-05-25 — PR#6 ~ PR#10 시기)

- **NEW (accepted)**: ADR-024 — canonical provider name `python-krmois-api`
  → `python-mois-api` (PR#3). v1 내부 alias였던 `krmois`/`pykrmois`는 legacy
  alias로만 보존. `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
  (git mv).
- **NEW (accepted)**: ADR-025 — 디버그 UI frontend는 `maplibre-vworld-js` 채택
  (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`). Kakao
  Maps SDK 미사용. `packages/krtour-map-admin/frontend/` skeleton.
  **사용자 보강 (2026-05-25)**: VWorld key는 `KRADDR_GEO_VWORLD_API_KEY`
  공유 / maplibre-vworld-js upstream 직접 PR로 적극 수정.
- **NEW (accepted)**: ADR-026 — TripMate 사용자 UI도 `maplibre-vworld` 채택
  (SPEC V8 v8_3 Kakao Maps 섹션 superseded). 두 UI 단일 stack.
- **NEW (proposed)**: ADR-027 — forest 카테고리/notice_type 확장 (PR#9):
  `LODGING_MOUNTAIN_SHELTER` Tier 2 신설 + `area_kind=hazard_zone` +
  generic `notice_type=access_restriction`/`fire_alert`. 사용자 결정으로
  `forest_` prefix 없는 generic 명명. WEATHER_MOUNTAIN_STATION /
  NATURE_ECOLOGY / Tier 1 `08 SAFETY`는 거부.
- **NEW (proposed)**: ADR-029 — `@krtour/map-marker-react` npm 패키지 추출
  (본 PR#10): 디버그 UI + TripMate 사용자 UI 공통 마커/카테고리 매핑.
  MIT 라이선스 (TripMate proprietary 호환). monorepo
  `packages/map-marker-react/`.
- **NEW (proposed)**: ADR-030 — 라이브러리 in-memory 캐시 금지 (PR#8).
  `functools.cache` 한정 narrow 예외 (PlaceCategoryCode 카탈로그,
  `pyproj.Transformer` singleton). `import-linter` 계약으로 `cachetools` /
  `async_lru` / `aiocache` / `diskcache` 차단.
- **NEW (proposed)**: ADR-031 — 디버그 패키지 OpenAPI export 첫 FastAPI
  라우터 등장 PR부터 즉시 활성화 (PR#8). `openapi.json` 저장소 커밋 +
  CI `--check` drift gate.
- **NEW (proposed, 시기 의존)**: ADR-032 — Coverage 단계적 상향 일정
  (Sprint 1 50% → Sprint 4 80%, PR#8). `dto/`는 Sprint 2부터 100% branch
  항상 강제. T-014 시점에 accepted 전환.
- **NEW (proposed, 시기 의존)**: ADR-033 — `feature_consistency_reports`
  두 단계 분할 도입 (PR#8). Phase 1 (Sprint 3~4) = 스키마 + F1~F3 critical
  (orphan source / detail 누락 / CRS drift, severity=ERROR, 게이트 미적용).
  Phase 2 (Sprint 5) = F4~F8 + Dagster 게이트 + swap 차단. T-014 시점에
  accepted 전환.

### 문서 확장 (2026-05-25)

- `docs/performance.md §9.3/§9.4/§9.5` — T-101 (PostGIS MV) / T-103
  (streaming ETL) / T-102 (pg_prewarm) 상세 분석 inline. 도입 조건, 부작용,
  ROI 평가.
- `docs/sprints/SPRINT-1.md` — 코드 작성 단계 진입 Sprint 1 계획 초안
  (T-014 후속).
- `docs/forest-feature-etl.md §11` — KNPS data.go.kr 통합 plan 7 dataset +
  옵션 A/B/C 비교. PR#5에서 outdoor→forest rename + KNPS dataset 카탈로그
  + 옵션 B (별도 `python-knps-api`) 권고. PR#9 (ADR-027)에서 카테고리/
  notice_type 결정 확정.
- `docs/category.md` §4 — Tier 1~4 전체 141건 카탈로그 (트리/표/maki icon
  분포). ADR-027 적용 후 144건 (`03.08 LODGING_MOUNTAIN_SHELTER` 3건 추가).
- `docs/notice-feature-etl.md` §3/§7 — NOTICE_TYPES 14건 (ADR-027의
  `access_restriction` / `fire_alert` 추가). 마커 스타일 매핑.
- `docs/tripmate-integration.md` §14.5 — TripMate 사용자 UI 지도 stack
  (ADR-026).
- `packages/krtour-map-admin/frontend/` — React + Vite + maplibre-vworld
  skeleton (`package.json` / `.env.example` / `.gitignore` / `README.md`).

### 잔존 명명 일치화 (본 PR#10)

- `docs/forest-feature-etl.md:173` 컨벤션 예시: `python-krmois-api` →
  `python-mois-api`.
- `docs/mois-license-feature-etl.md:115` 예시 payload: `krmois_admin_address`
  → `mois_admin_address`.
- `docs/journal.md:151` 컨벤션 예시: `krmois/krheritage/krforest` →
  `mois/krheritage/krforest`.
- `docs/journal.md:475` 옛 provider 목록: `krmois` → `mois (구 krmois)`.
- ADR-024 migration 본문 / journal ADR-024 narrative / mois-feature-etl.md
  의 v1→v2 마이그레이션 표 등 *역사 기록 컨텍스트*의 `krmois` 표기는 그대로
  유지 (rename 사건 자체를 기록).

### 코드 (본 PR#10)

- `pyproject.toml` — ADR-030 `import-linter` forbidden 계약에
  `cachetools` / `async_lru` / `aiocache` / `diskcache` 추가. ADR-032
  `[tool.coverage.report] fail_under = 50` Sprint 1 bar 설정.
- `packages/krtour-map-admin/scripts/export_openapi.py` — ADR-031
  CLI skeleton (실행은 코드 작성 단계에서).
- `packages/map-marker-react/` — ADR-029 skeleton (`package.json` /
  `README.md` / `.gitignore` / `vite.config.ts`).

### 변경 / 재설계 (v2 design — 초기)

- **NEW**: ADR-021 — main에 직접 push 금지. 모든 변경은 feature branch + PR
  (`gh pr create`). 운영 GitHub branch protection으로 강제.
  `docs/agent-guide.md` §7.5에 PR 워크플로/commit format/PR 본문 표준 박힘.

- **BREAKING**: ADR-022 — Python import 경로 변경.
  - `from krtour_map import ...` → `from krtour.map import ...`
  - `from krtour_map_admin import ...` → `from krtour.map_admin import ...`
  - `src/krtour_map/` → `src/krtour/map/`
  - `src/krtour_map_admin/` → `src/krtour/map_admin/` (디버그 UI 패키지)
  - `krtour` PEP 420 implicit namespace (no `src/krtour/__init__.py`).
  - PyPI distribution 이름(`python-krtour-map`), CLI(`krtour-map`),
    env prefix(`KRTOUR_MAP_*`), DB 이름(`krtour_map`)는 모두 유지.
  - `pyproject.toml` `packages.find` + `namespaces=true` + `import-linter`
    layers 갱신.

- **NEW**: ADR-023 — `python-kraddr-base`의 category 모듈
  (`kraddr.base.categories`, ~2,072줄, 141 enum)을 본 저장소
  `krtour.map.category`로 이전.
  - 공개 식별자 전부 유지 (`PlaceCategory`, `PlaceCategoryCode`, `get_category`,
    `iter_categories`, `mapbox_maki_icon_for_category` 등).
  - 의존 계층 최하단 (`category → dto → core → infra → providers → client → cli`).
  - 라이선스 GPL-3.0-or-later 호환. 실제 코드 이전은 코드 작성 단계에서 별도 PR.
  - 사양: `docs/category.md`.

- **BREAKING**: 디버그 REST API/UI를 별도 Python 패키지 `krtour-map-admin`
  (`packages/krtour-map-admin/`)로 분리 (ADR-020). 메인 라이브러리
  `python-krtour-map`에서 FastAPI/Uvicorn 의존성 제거. `[api]` extra 폐기.
  `krtour.map.api` 모듈 없음. ADR-005의 위치 부분은 ADR-020으로 superseded
  (인증 없음 + 내부망 전용 정책은 유지).
  - 디버그 UI 실행: `uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 8087`
  - 환경변수 prefix: `KRTOUR_MAP_ADMIN_*`
  - `import-linter`에 `메인 패키지는 fastapi/uvicorn/starlette import 금지`
    계약 추가.


- **BREAKING**: v1 코드는 `v1` 브랜치로 이동. main은 orphan으로 v2 사양 시작.
  v1 산출물은 `git checkout v1` 또는 `python-krtour-map-spec.docx` (저장소 루트
  약 80쪽) 참고.
- **BREAKING**: TripMate ↔ 라이브러리 연계는 **함수 직접 호출**로 일원화
  (ADR-003). REST 사용 안 함.
- **BREAKING**: 의존 스택 확정 — PostgreSQL 16 + PostGIS 3.5 + SQLAlchemy 2 async
  + GeoAlchemy2 + GeoPandas + Pydantic v2 + asyncpg + psycopg[binary,pool]>=3.2
  (ADR-007).
- **BREAKING**: schema 분리 — `feature`, `provider_sync`, `ops`, `x_extension`
  (ADR-008).
- **BREAKING**: `Feature.detail`은 자유 dict 금지, `DETAIL_MODELS` 분기 강제
  (ADR-018).
- **BREAKING**: 모든 datetime은 timezone aware (KST 기본). naive 입력은
  ValidationError (ADR-019).
- **NEW**: 디버그 REST API (옵션, 인증 없음, 내부망 전용, ADR-005).
- **NEW**: 의존 계층 강제 (`dto → core → infra → providers → client → api/cli`)
  + import-linter CI (ADR-002).
- **NEW**: 작업 큐 영속화 (`ops.import_jobs` + advisory lock + SKIP LOCKED,
  ADR-011).
- **NEW**: bulk insert 30k 안전 마진 룰 + `psycopg.copy_*` 우선 (ADR-013).
- **NEW**: 공간 쿼리 인덱스 최적화 — `coord_5179`(meter) 컬럼 + CTE 1회 변환
  강제 (ADR-012).
- **NEW**: 4단계 테스트 (unit/integration/e2e/fixture) + Coverage 목표 + EXPLAIN
  검증 의무화 (ADR-014).
- **NEW**: 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap 가능
  (ADR-015).
- **NEW**: Record Linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 박음
  (ADR-016).
- **NEW**: 보관 정책 박음 — place 무기한, event +20y, notice +1y, weather +30d
  (ADR-017).

### 문서

- 새 governance 문서 작성: `AGENTS.md`, `README.md`, `SKILL.md`, `CLAUDE.md`.
- 새 design 문서 작성:
  - `docs/architecture.md`
  - `docs/decisions.md` (ADR-001 ~ ADR-019)
  - `docs/data-model.md`
  - `docs/performance.md`
  - `docs/test-strategy.md`
  - `docs/backend-package.md`
  - `docs/agent-guide.md`
  - `docs/dev-environment.md`
  - `docs/windows-reinstall-recovery.md`
  - `docs/feature-model.md`
  - `docs/provider-contract.md`
  - `docs/external-apis.md`
  - `docs/tasks.md`, `docs/resume.md`, `docs/journal.md`
- `pyproject.toml`에 4단계 스택 의존성 + import-linter 계약 박음.

### 마이그레이션 가이드 (v1 → v2)

v1 사용자는 다음 흐름으로 마이그레이션한다 (코드 작성 단계 진입 후):

1. v1 데이터 dump (현재는 미정 — 코드 작성 단계에서 정의)
2. v2 schema (`feature/provider_sync/ops/x_extension`) 생성
3. detail JSONB 키 매핑 (v1 ↔ v2 차이 — 별도 변환 스크립트)
4. `feature_id` 재계산 (`make_feature_id`의 `bjd_code` 인자가 v2에서 명시적)
5. 보관 정책 적용 → 만료 row 삭제

상세 가이드는 코드 작성 단계 진입 시 별도 문서로 작성.

---

## v1 (역사 보존)

v1은 `v1` 브랜치에 보존. 자세한 v1 변경 이력은 그쪽 `git log`로 확인:

```bash
git checkout v1
git log --oneline
```

v1 마지막 commit: `08205ab Preserve v1 work: docs revamp, providers, debug UI,
spec docx` (2026-05-24).
