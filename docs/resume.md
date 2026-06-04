# resume.md — 현재 진척도와 다음 한 작업

## 2026-06-04 Codex 작업 메모 — T-RV-10 keyset cursor 정밀도

T-RV-10을 처리한다. `/features/search`는 q 검색 cursor에 DB에서 받은
`score::text`를 저장하고, 다음 페이지 predicate를 `(-score, feature_id) >
(-cursor_score, cursor_feature_id)`로 바꿔 `ORDER BY score DESC, feature_id ASC`와
같은 정렬축을 사용한다. 사용자 응답의 `score`는 계속 float로 내려가지만 cursor
비교는 DB score text 기반이다.

`/admin/dedup-review`는 `total_score` `NUMERIC` cursor를 float가 아니라 문자열로
운반하고, predicate와 `ORDER BY` 모두 `review_key::text`를 사용하도록 통일했다. 같은
score/total_score 여러 행을 `page_size=1`로 끝까지 넘기는 PostGIS integration test를
추가했다.

다음 한 작업은 **T-RV-04b(provider public client live fetch wiring)** 또는
**T-RV MED 묶음 중 운영 영향이 큰 항목(T-RV-12/13/14 등)** 이다. **T-RV-27은
production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-05/11 run-now/claim lock

T-RV-05/11을 처리한다. `run_mode=now` feature update request 생성과 기존 request
`run-now` 재큐잉은 동일 scope advisory lock이 이미 점유되어 있으면 queued fallback
없이 `409 LOCK_BUSY`로 거절한다. 응답은 공통 error envelope의
`error.code="LOCK_BUSY"`, `details.retry_after_seconds=15`, HTTP `Retry-After: 15`
헤더를 포함한다.

`feature_update_scope_advisory_key(...)`는 scope/provider/dataset filter를 canonical
JSON으로 정규화해 같은 scope key를 만들고, executor는 실제 실행 중 이 scope lock을
보유한다. `claim_next_update_request`는 queue claim advisory lock 경합 시 더 이상
`None`을 반환하지 않고 `FeatureUpdateQueueLockBusy`를 올려 빈 큐와 구분한다.

다음 한 작업은 **T-RV-10(keyset cursor float/decimal 정밀도·정렬축 보강)** 또는
**T-RV-04b(provider public client live fetch wiring)** 이다. **T-RV-27은 production
레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-04a Dagster provider resource guard

T-RV-04의 1차 guard를 처리한다. provider record resource key 9개에 대해 기본
`defs`가 generic `_missing_resource`를 등록하던 상태를 제거하고, provider package,
dataset, `KRTOUR_MAP_*` credential env, source env를 설명하는 guard resource를
등록한다. guard는 resource materialize 시 명확한 `RuntimeError`를 내며, secret 값은
메시지에 포함하지 않는다.

`KrtourMapSettings`에는 `data_go_kr_service_key`, `opinet_api_key`,
`krex_ex_api_key`, `krex_go_api_key`를 추가했다. `.env.example`, `scripts/load-env.sh`,
`docker-compose.yml`은 기존 provider repo env(`DATA_GO_KR_SERVICE_KEY`,
`OPINET_API_KEY`, `KEX_GO_API_KEY` 등)를 main settings env로 전달한다. 다음 한 작업은
**T-RV-04b(provider public client live fetch wiring)** 또는 **T-RV-05/11(D-6
run-now/claim lock)** 이다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-03 Dagster resource lifecycle

T-RV-03을 처리한다. `krtour_map_client_resource`를 일반 return resource에서
generator resource로 전환해 Dagster run/tick 종료 후 `AsyncEngine.dispose()`가
반드시 호출되게 했다. Dagster resource teardown은 sync generator 경로이므로,
teardown 지점에 이미 running event loop가 있으면 별도 thread에서 `asyncio.run()`으로
`engine.dispose()`를 실행하고 예외를 호출자에게 다시 올린다.

`packages/krtour-map-dagster/tests/test_resources.py`가 fake engine/fake client로
DB 없이 lifecycle만 검증한다. 다음 한 작업은 **T-RV-04(Dagster provider public
client/service key resource wiring)** 또는 **T-RV-05/11(D-6 run-now/claim lock)** 이다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-01/02 Dagster 운영 형상

T-RV-01/02를 처리한다. Docker compose의 `dagster` 서비스는
`dagster-webserver`로 명시하고, 별도 `dagster-daemon` 서비스를 추가했다.
`dagster-db-init` 서비스는 같은 Postgres container 안에 `krtour_map_dagster` DB가
없으면 생성한다. `docker/dagster.yaml`은 `KRTOUR_MAP_DAGSTER_PG_URL` 기반
`storage.postgres`를 설정하고, `krtour-map-dagster` 패키지에 `dagster-postgres`
의존성을 추가했다.

`tests/unit/test_docker_dagster_runtime.py`가 compose split, Postgres storage 설정,
`dagster-postgres` dependency를 회귀 테스트한다. 다음 한 작업은 **T-RV-03/04(Dagster
resource engine lifecycle + provider service key resource)** 또는 **T-RV-05/11(D-6
run-now/claim lock)** 이다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-08 public response field hardening

T-RV-08을 처리한다. public `FeatureDetailResponse`에서 `coord_5179_srid`,
`parent_feature_id`, `sibling_group_id`를 제거했고, `/features/nearby/by-target`의
target summary는 `external_system`, `target_key`, `lon`, `lat`만 남겼다. 주변 feature
item에서도 `primary_provider`, `primary_dataset_key`를 제거했다. admin 전용
`/admin/poi-cache-targets*` 응답은 운영 필드를 그대로 제공한다.

`openapi.user.json`을 재생성했고, `test_export_openapi.py`가 user spec schema에 내부
필드가 남지 않는지 직접 검사한다. 다음 한 작업은 **T-RV-01/02(Dagster metadata DB/
webserver/daemon 운영 형상)** 또는 **T-RV-05/11(run-now lock/claim 락경합)** 중 HIGH
운영 형상 보강이다. **T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-07 admin/ops router gate

T-RV-07을 처리한다. `AdminSettings`에 `admin_routes_enabled`와
`ops_routes_enabled`를 추가했고, 값이 `None`이면 기존 `features_routes_enabled`를
따르게 했다. 기본 운영 동작은 유지하지만, DB 없는 부팅 검증에서
`features_routes_enabled=False`를 주면 `/features/*`와 함께 DB 의존 `/admin/*`,
`/ops/*`, `/ops/dagster/*` 라우터도 mount하지 않는다. 특수 검증에서 admin/ops만
열어야 할 때는 새 flag로 명시 opt-in한다.

`test_routers.py`에 OpenAPI path와 404 회귀 테스트를 추가했다. 사용자 결정에 따라
**T-RV-27 admin API bind 노출 정정은 production 레벨 hardening 전까지 구현하지 않고
deferred/skip으로 문서 추적만 유지**한다. 다음 한 작업은 **T-RV-08(public response
field leak)** 이다.

## 2026-06-04 Codex 작업 메모 — T-RV-06 error envelope

T-RV-06을 처리한다. `packages/krtour-map-admin/src/krtour/map_admin/app.py`에
app-level `StarletteHTTPException`/`RequestValidationError` handler를 추가해 admin API
에러 응답을 `{error:{code,message,details,request_id}}`로 통일했다.
`X-Request-ID` 요청 헤더가 있으면 같은 값을 응답 헤더와 envelope에 되돌리고, 없으면
UUID를 생성한다. FastAPI 기본 422도 `VALIDATION_ERROR` envelope와 validation
`details.errors`로 내려간다.

기존 admin router 테스트의 `detail` 직접 기대를 envelope `error.message`로 교정했고,
`test_error_envelope.py`로 HTTPException/validation error 공통 shape를 잠갔다. 다음
한 작업은 사용자 결정으로 deferred 된 T-RV-27을 건너뛰고 **T-RV-07(admin/ops router
gate)** 또는 **T-RV-08(public response field leak)** 중 하나다.

## 2026-06-04 Codex 작업 메모 — T-RV-09 offline upload 크기 상한

PR#153~#179 리뷰 후속 HIGH 선반영 순서에 따라 T-RV-09를 처리한다.
`KrtourMapSettings.offline_upload_max_bytes`/`KRTOUR_MAP_OFFLINE_UPLOAD_MAX_BYTES`를
추가했고 기본값은 `104857600` bytes(100 MiB)다. `POST /admin/offline-uploads`는
`Content-Length`로 명백히 큰 multipart 요청을 `413`으로 선차단하고, 실제 파일 read도
`max_bytes + 1`까지만 수행해 무제한 메모리 read를 막는다.

환경 전파는 `.env.example`, `scripts/load-env.sh`, `docker-compose.yml`에 반영했다.
문서는 OpenAPI/admin workflow/RustFS/tasks/journal/changelog를 갱신했다. 이번 범위는
무제한 read/OOM surface 차단이며, S3 multipart streaming·object orphan 보상·store
client 재사용은 T-RV-22/23/25에서 별도 처리한다. PR#185로 main에 머지했다.
사용자 결정에 따라
**T-RV-27 admin API bind 노출 정정은 production 레벨 외부 노출 전까지 구현하지
않고 deferred로 문서 추적만 유지**한다.

## 2026-06-04 Codex 작업 메모 — T-200 Batch DAG + 정합성 게이트

T-205d의 `load_batch_id`/`parent_job_id` 컬럼 위에 T-200 batch gate를 연결했다.
`src/krtour/map/infra/batch_dag.py`는 기존 provider/offline 적재가 만든 실제
`ops.import_jobs.job_id`를 `child_job_ids`로 받아 root `full_load_batch` 아래 묶고,
child가 모두 `done`일 때만 `consistency_check`를 실행한다. `severity_max=ERROR`이면
root/gate job을 `failed`로 닫고 `mv_refresh`를 만들지 않는다. `OK/WARN`이면
`mv_refresh` 추적 job을 만들며, 현재 운영 MV 카탈로그가 없으면
`skipped:no_materialized_views`로 명확히 기록한다.

Dagster package에는 `full_load_batch_consistency_gate` job을 추가했고,
`AsyncKrtourMapClient.run_batch_dag_consistency_gate(...)`로 DB transaction을 소유한다.
검증은 unit coverage 재현 `800 passed` / `80.59%`, Dagster package `17 passed`,
PostGIS integration `tests/integration/test_batch_dag.py tests/integration/test_jobs_repo.py`
`14 passed`, targeted `ruff`, targeted `mypy`, import-linter로 확인했다. 다음 한 작업은
**T-201b 정합성 Phase 2 범위 재정의/구현**이며, ADR-045 잔여가 닫히면 T-212
전체점검으로 넘어간다.

## 2026-06-04 Codex 작업 메모 — T-209b run-admin-stack 안정화

PR#182 머지 후 서버를 재기동하는 과정에서 `scripts/run-admin-stack.sh`가 Next ready
로그를 남긴 뒤에도 wrapper PID/readiness 판단 때문에 실패하고, shell 종료와 함께
background 프로세스가 내려가는 문제가 재현됐다. 스크립트를 시작 전
`alembic upgrade head` 실행, `setsid` detached background 실행, URL 기준 readiness
판단으로 보정했다.

이 PR은 venv/로컬 admin stack runner 안정화 범위다. T-209b의 남은 부분인 Dagster
metadata DB 분리/init와 daemon/schedule 운영은 후속으로 유지한다. 다음 한 작업은
T-200 Batch DAG + 정합성 게이트다. 검증은 `bash -n`, 수정된
`scripts/run-admin-stack.sh` 실제 실행(API `9011`, Web `9012`, Dagster `9013`
readiness 통과), API/Web/Dagster smoke HTTP 200, `git diff --check`로 확인했다.

## 2026-06-04 Codex 작업 메모 — T-205d import_jobs batch 컬럼

T-200 Batch DAG 선행 조건으로 `ops.import_jobs`에 `load_batch_id`와 `parent_job_id`
self-FK를 추가했다. `alembic 0012_import_jobs_batch_columns`, `ImportJobRow`,
`infra.jobs_repo`, `infra.ops_repo`, admin `/ops/import-jobs` 라우터와 frontend 목록
화면이 같은 계약을 사용한다.

새 동작은 다음과 같다.

- root job은 `load_batch_id=UUID`, `parent_job_id=NULL`로 생성할 수 있다.
- child/provider/gate job은 같은 `load_batch_id`와 root `parent_job_id`를 저장한다.
- `/ops/import-jobs`는 `load_batch_id`/`parent_job_id` UUID query filter를 받으며,
  목록/상세 응답에도 두 필드를 포함한다.
- admin UI `/ops/import-jobs`는 batch/parent 필터와 축약 id 컬럼을 표시한다.

검증은 unit coverage 재현 `792 passed` / `80.56%`, admin package `132 passed`,
Dagster package `15 passed`, targeted migrated PostGIS integration `13 passed`와 mixed
unit/integration `22 passed`, repo-wide `ruff`, `mypy`, import-linter, OpenAPI
`--profile all --check`, frontend `type-check`/`lint`/`build`, React Doctor full scan
(기존 optional warning 7개)로 확인했다. 다음 한 작업은 **T-200 Batch DAG + 정합성
게이트**다. T-200에서 root/child job 생성과 consistency gate, 이후 T-201b Phase 2
report/gate를 이어서 구현한다.

## 2026-06-04 Codex 작업 메모 — T-208i offline CSV/TSV validation

T-208h가 닫은 `/admin/offline-uploads*` 기본 업로드 경로를 CSV/TSV tabular 원본까지
확장했다. JSON/JSONL은 기존처럼 `FeatureBundle` dump를 바로 load할 수 있고, CSV/TSV는
preview → column mapping validation → Dagster `offline_upload_load` 순서로 적재한다.

새로 추가한 구성은 다음과 같다.

- `krtour.map.offline_upload`: CSV/TSV preview, validation result/issue DTO, validation
  import job, validation payload 재사용 load parser. CSV/TSV load는 `validation_job_id`가
  있는 `validated` 상태만 허용한다.
- `infra.jobs_repo`/`infra.offline_upload_repo`: validation job payload 조회/갱신과
  `validating`/`validated`/`validation_failed` 상태 전이.
- `krtour.map.geocoding`: `AddressResolver`, geocode response → `Address` 변환,
  kraddr-geo REST v2 address resolver, cached resolver. `bjd_code`가 없으면 주소
  geocode, 필요 시 좌표 reverse로 법정동코드를 보강한다.
- provider 변환기: datagokr 표준데이터, MOIS, OpiNet, KREX, krheritage 변환 경로에
  `address_resolver`를 주입할 수 있게 했다. 원천 `bjd_code`/좌표 reverse가 없거나
  실패해도 주소가 있으면 kraddr-geo geocode 결과로 feature_id 계산 전 보강한다.
- admin backend: `GET /admin/offline-uploads/{upload_id}/preview`,
  `POST /admin/offline-uploads/{upload_id}/validate`,
  `GET /admin/offline-uploads/{upload_id}/validation`.
- admin frontend: `/admin/offline-uploads` 화면에 CSV/TSV mapping form, preview table,
  validation issue table, validation 전 load 비활성화를 추가했다.
- Dagster: `offline_upload_load` op가 `KRTOUR_MAP_KRADDR_GEO_BASE_URL`이 있으면
  kraddr-geo REST v2 resolver/reverse geocoder를 열고 CSV/TSV load에도 주입한다.

검증은 unit-only coverage `792 passed` / `80.54%`, integration/admin/dagster 묶음
`293 passed`, targeted backend/provider/router unit `114 passed`, offline upload PostGIS
integration `4 passed`, repo-wide `ruff`, `mypy`, import-linter, frontend
`npm run type-check`, `npm run lint`, `npm run build`, React Doctor full scan(기존
optional warning 7개), Windows Next dev server + WSL API 조합의 admin/ops Playwright
e2e `6 passed`, OpenAPI admin/user drift check로 확인했다. 전체 integration 실행 중 기존
fixture가 PostGIS extension을 `DROP ... CASCADE`하면서 geometry 컬럼을 지우는 CI RED
원인도 `tests/integration/conftest.py`에서 함께 보정했다. PR 생성 후에는 GitHub Actions
결과를 확인하고 실패가 있으면 같은 브랜치에서 수정한다.

사용자 추가 지시에 따라 ADR-045 관련 잔여 task 완료 후 수행할 전체점검은
`docs/reports/adr-045-overall-audit-plan-2026-06-04.md`에 `T-212a`~`T-212e`로
분리했다. 전체점검은 admin UI 완결성, DB/API/frontend 성능, endpoint shape,
Dagster/log 모니터링, 실데이터 offline upload, DB 초기화 후 full reload까지 포함한다.

다음 한 작업은 T-205d였고, 2026-06-04 Codex 후속 작업에서 완료했다. 이후 T-200
Batch DAG + T-201b Phase 2 consistency gate를 이어서 진행하고, ADR-045 잔여 task가
닫히면 T-212 전체점검 묶음으로 넘어간다.

## 2026-06-03 Codex 작업 메모 — T-208h offline uploads API/UI

admin UI #9의 offline upload 경로를 실제 API/UI로 연결했다. T-208g의
`ops.offline_uploads` 메타데이터와 Dagster `offline_upload_load` job, T-208b 후속의
RustFS/S3 `offline_upload_store` resource를 바탕으로 기본 JSON/JSONL 업로드부터
Dagster load 실행까지 한 흐름으로 닫았다.

새로 추가한 구성은 다음과 같다.

- `GET/POST /admin/offline-uploads`, `GET /admin/offline-uploads/{upload_id}`,
  `POST /admin/offline-uploads/{upload_id}/load`: multipart JSON/JSONL 업로드,
  keyset 목록, 상세, Dagster GraphQL `launchRun` 기반 load 실행.
- `infra.offline_upload_repo.list_offline_uploads`: `created_at DESC, upload_id DESC`
  keyset cursor. `create_offline_upload()`은 API가 먼저 만든 UUID를 받아 RustFS object
  key와 DB row를 같은 id로 묶을 수 있다.
- admin frontend `/admin/offline-uploads`: 파일 선택, provider/dataset/scope 입력,
  업로드 결과 표시, 목록 필터, 상세 panel, load 실행 버튼.
- frontend `src/api/offlineUploads.ts`와 `postFormData()` helper: upload/list/detail/load
  mutation과 query cache invalidation.

검증은 backend/admin/Dagster/offline upload focused pytest `21 passed`, targeted
`ruff`, 전체 strict `mypy`, `lint-imports`, OpenAPI admin/user drift check, frontend
`type-check`, `lint`, `build`, React Doctor full scan으로 확인했다. React Doctor
optional warning 7개는 기존 shadcn/ui primitive와 Dagster iframe rule이며 새 offline
uploads 화면에는 해당하지 않는다. WSL 실제 서버(API `9011`, web `9012`, Dagster
`9013`)에서는 multipart upload → RustFS `krtour-uploads` 저장 → Dagster
`offline_upload_load` run `SUCCESS` → DB `upload_state=loaded`, `job_state=done`,
`progress=100`까지 확인했다. Windows Playwright는 WSL IP fallback으로
`admin-ops.spec.ts` 6/6 통과했고, `/admin/offline-uploads` route smoke를 추가했다.

다음 한 작업은 **T-208i CSV/TSV validation + column mapping wizard**다. 사용자 지시에
따라 9번 admin UI 최신화 우선순위를 최상위로 올렸으므로, T-208h PR 머지 직후에는
9번을 막는 선행 task부터 처리한다. 현재 순서는 T-208i → provider refresh
policy/provider 상태 REST/UI → 수동 feature 생성 audit log/API → error log/import job
event API다.

## 2026-06-03 Codex 작업 메모 — T-208b RustFS offline upload store wiring

admin UI #9의 offline upload 화면을 실제 데이터 경로에 붙이기 위한 선행조건으로
T-208b 잔여 RustFS/S3 resource wiring을 먼저 닫았다. T-208g에서 만든
`ops.offline_uploads` + Dagster `offline_upload_load` job은 이제 테스트 double뿐 아니라
환경변수 기반 기본 `offline_upload_store` resource로 RustFS/S3 호환 bucket을 읽을 수
있다.

새로 추가한 구성은 다음과 같다.

- `krtour.map.infra.file_store.S3ObjectStore`: boto3 호환 S3 client wrapper.
  `read_bytes(storage_key)`가 `OfflineUploadObjectStore` protocol을 만족하고,
  `write_bytes()`는 다음 admin multipart upload API에서 재사용할 수 있다.
- `KrtourMapSettings`: `.env.example`과 실제 field명을 맞췄다.
  `KRTOUR_MAP_OBJECT_STORE_*`는 feature file bucket(`krtour-map`)에 쓰고,
  `KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET` 기본값은 ADR-045 D-14 기준 `krtour-uploads`다.
- `krtour.map_dagster.resources`: `offline_upload_store_resource`가
  `KrtourMapSettings` → boto3 client → `S3ObjectStore(bucket=krtour-uploads)`를 만든다.
- `docker-compose.yml`: RustFS service를 추가했다. host port는 API `9003`, console
  `9004`이며, `rustfs-init`가 `krtour-map`/`krtour-uploads` bucket을 생성한다.
- `scripts/load-env.sh`, `scripts/docker-up.sh`, `scripts/stop-fixed-ports.sh`:
  RustFS 포트와 object store env default를 포함하도록 정리했다.

검증은 `S3ObjectStore`/Dagster resource/definitions/offline upload Dagster unit
`8 passed`, targeted `ruff`, targeted `mypy`, `docker compose config --quiet`로
확인했다. 추가로 Docker RustFS를 실제 기동해 `rustfs-init`가 `krtour-map`과
`krtour-uploads` bucket을 만들고, `S3ObjectStore.write_bytes/read_bytes`로
`offline-uploads/smoke/codex-t208b.jsonl` put/get이 성공함을 확인했다.

다음 한 작업은 **admin UI #9 선행 `/admin/offline-uploads*` API + upload 화면**이다.
CSV/TSV column mapping wizard는 API/UI 기본 업로드 경로가 닫힌 뒤 진행한다.

## 2026-06-03 Codex 작업 메모 — T-208g offline upload load job

T-208g는 admin API/UI가 올린 오프라인 파일을 krtour-map 독립 Dagster가 적재할 수
있도록 선행 DB/job 계약을 구현하는 작업이다. 이번 범위에서는 업로드 UI와 multipart
API가 아니라, 이미 객체 저장소에 저장된 원본 파일 메타데이터(`ops.offline_uploads`)
를 기준으로 Dagster load job이 PostGIS 적재까지 수행하는 경로를 닫았다.

새로 추가한 구성은 다음과 같다.

- `alembic/versions/0011_offline_uploads.py`: `ops.offline_uploads` 테이블. provider,
  dataset_key, sync_scope, storage_backend/key, byte_size, checksum, detected format,
  validation/load `import_jobs` FK, state를 저장한다.
- `krtour.map.infra.offline_upload_repo`: 업로드 메타 생성/조회, load 시작/종료 상태
  전이 raw SQL repository.
- `krtour.map.offline_upload`: JSON/JSONL `FeatureBundle` parser, checksum/size 검증,
  provider/dataset/scope advisory lock, `import_jobs` running/done/failed 전이,
  `load_bundles` 적재 orchestration.
- `AsyncKrtourMapClient.run_offline_upload_load_job`: Dagster/admin 내부에서 쓰는
  client 진입점.
- `packages/krtour-map-dagster`: `offline_upload_load` job + `offline_upload_store`
  resource key 등록.

지원 포맷은 첫 단계로 JSON/JSONL `FeatureBundle` dump다. 기본
`/admin/offline-uploads*` API/UI는 T-208h에서 구현했고, CSV/TSV column mapping과
validation wizard는 후속이다. parser는
`Feature.detail` dict 금지(ADR-018)를 우회하지 않고, kind별 detail
모델로 hydrate한 뒤 DTO 검증을 수행한다.

검증은 parser/Dagster definitions unit `8 passed`, migrated PostGIS integration
`2 passed`로 확인했다. 통합 테스트는 성공 적재와 checksum mismatch 실패 시
`ops.import_jobs.state='failed'`, `ops.offline_uploads.state='load_failed'` 전이를
검증한다.

다음 한 작업은 **T-208b 잔여 RustFS/provider 실제 resource wiring**이다.

## 2026-06-03 Codex 작업 메모 — T-208f consistency/dedup refresh job

T-211b admin UI 최신화가 PR#175로 머지된 뒤, 독립 Dagster 운영 완성 선행 task인
T-208f를 진행했다. 새 `krtour.map.infra.dedup_refresh_repo`는 DB에 적재된 활성
feature를 provider/dataset scope 기준으로 읽어 `core.dedup.DedupInput` 형태로
제공한다. `AsyncKrtourMapClient`에는 다음 운영 메서드를 추가했다.

- `refresh_dedup_candidates_for_scope_pair`: 두 provider/dataset scope를 cross-score해
  `ops.dedup_review_queue`를 upsert한다.
- `refresh_sibling_dedup_candidates`: 단일 scope 내부 sibling 후보를 재계산한다.
- `run_consistency_report`: F1~F4 consistency report를 실행하고 필요 시
  `ops.feature_consistency_reports`에 저장한다.

Dagster package에는 `consistency_dedup_refresh` job을 추가했다. 첫 op
`refresh_dedup_candidates`는 `pairs`와 `sibling_scopes` config를 받고, 두 번째 op
`run_consistency_check`는 dedup refresh 이후 실행되어 report metadata를 남긴다.
`consistency_dedup_refresh_daily_schedule`은 `Asia/Seoul` 기준 `45 5 * * *`이며, 외부
운영자가 명시적으로 켜기 전까지 `STOPPED`다. 이 작업은 ADR-033 Phase 2 gate/swap
차단이 아니라 관측/refresh job이다.

검증은 Dagster definitions/unit `5 passed`, PostGIS client 경로 integration
`5 passed`로 확인했다. 다음 한 작업은 **T-208g offline upload load job**이다.

## 2026-06-03 Codex 작업 메모 — T-211b admin UI 최신화 구현

사용자 지시로 admin UI 최신화 우선순위를 최상위로 올린 뒤, T-211a 선행 API/gap
정리를 바탕으로 T-211b 화면 구현을 진행했다. frontend에는 공통 `AdminShell`,
`StatusBadge`, format helper를 추가하고 홈(`/`)을 운영 dashboard로 교체했다.

새 화면은 다음 최신 계약을 직접 소비한다.

- `/ops/import-jobs`: `ops.import_jobs` read-only 목록, state/kind filter.
- `/ops/consistency`: `/ops/metrics`, consistency reports, integrity issues 조회.
- `/admin/dedup-review`: pending/accepted/rejected/ignored/merged 필터와 결정 버튼.
- `/admin/feature-update-requests`: center radius 기반 request 생성, dry-run, cancel,
  run-now, request 상태 목록.
- `/admin/poi-cache-targets`: `external_system + target_key` upsert/delete와
  `/features/nearby/by-target` 주변 feature 조회.
- `/admin/dagster`: Dagster summary 자체 UI에 schedules/sensors 상태를 추가하고
  Dagster webserver iframe embed를 유지.

`/features`는 기존 지도/테이블 workflow를 유지하면서 운영 화면 링크를 헤더에 추가했다.
Playwright e2e는 새 home dashboard와 신규 admin/ops route smoke 기준으로 갱신했다.
검증 중 WSL root listener 또는 Windows `node.exe`/`wslrelay.exe`가 9012를 점유하면
새 WSL 서버 대신 stale UI를 보는 문제가 확인되어, `scripts/stop-fixed-ports.sh`가 WSL
root/Windows listener도 정리하도록 보강했다. Windows localhost relay가 내려간 경우를
위해 `scripts/load-env.sh` 기본 CORS origin에는 WSL IP 기반 `http://<WSL-IP>:9012`도
포함했고, admin FastAPI가 설정된 origin에 대해 CORS 응답/preflight 헤더를 보강한다.
검증 범위는 source/WSL frontend `npm run type-check`, `npm run lint`, `npm test`,
`npm run build`, `npm run doctor`, Windows Playwright e2e 16/16, CORS/ETL targeted unit
25개, Python `ruff`/`mypy`/`lint-imports`/OpenAPI drift check다. React Doctor는 exit
code 0이며 남은 optional warning은 기존 shadcn/ui primitive 구조와 Dagster iframe
sandbox rule false positive다.

다음 한 작업은 **T-208f consistency/dedup refresh job**이다. T-208g offline upload
load job은 그 다음 순서로 진행한다.

## 2026-06-03 Codex 작업 메모 — T-211a admin UI 선행 gap audit/API 계약

사용자 지시로 admin UI 최신화(기존 9번)를 최우선으로 올리고, T-211b 화면 구현 전에
필요한 선행 작업을 T-211a로 분리했다. 새 문서
`docs/admin-ui-modernization-gap-audit.md`는 최신 workflow 문서, OpenAPI 계약, 실제
backend/frontend 구현을 대조해 route별 구현 가능성과 backend gap을 정리한다.

frontend API layer에는 다음 typed hook module을 추가했다.

- `src/api/importJobs.ts`: `/ops/import-jobs`, `/ops/import-jobs/{job_id}`
- `src/api/ops.ts`: `/ops/metrics`, `/ops/consistency/reports`,
  `/ops/consistency/issues`
- `src/api/dedup.ts`: `/admin/dedup-review`
- `src/api/updateRequests.ts`: `/admin/feature-update-requests`
- `src/api/poiCacheTargets.ts`: `/admin/poi-cache-targets`,
  `/features/nearby/by-target`
- `src/api/features.ts`: `/admin/features` 목록과 deactivate mutation 보강

`client.ts`는 공통 `getJson`/`postJson`/`putJson`/`patchJson`/`deleteJson`과
`pathWithQuery`를 제공하도록 정리했다. 문서의 과거 `/admin/import-jobs` 표기는 현재
정본인 `/ops/import-jobs`로 정리했고, 일반 좌표 기준 `/features/nearby`는 아직
backend가 없으므로 T-211b에서는 target 기반 `/features/nearby/by-target`만 사용한다.
frontend `npm test`는 Vitest가 Playwright e2e spec을 수집하지 않도록 `e2e/**`를
제외했다.

검증 범위는 frontend `npm run type-check`, `npm run lint`, `npm test`, `npm run build`,
Python `ruff`/`mypy`/`lint-imports`, OpenAPI drift check다. 같은 gate를 WSL mirror에서도
확인했다. React Doctor는 exit code 0이나 optional warning을 보고했다. 경고는 기존
shadcn/ui primitive 구조와 기존 Dagster iframe sandbox 항목으로, T-211b 화면
재작업에서 함께 정리한다. 다음 한 작업은 **T-211b admin UI 최신화 구현**이다.

## 2026-06-03 Codex 작업 메모 — T-208d Dagster schedules

ADR-045 T-208d로 `packages/krtour-map-dagster`에 Feature 적재 asset 9개에 대한
provider별 KST schedule과 asset job을 등록했다. 새 모듈
`krtour.map_dagster.schedules`는 `FEATURE_LOAD_SCHEDULE_SPECS`,
`FEATURE_LOAD_JOBS`, `FEATURE_LOAD_SCHEDULES`를 제공하고,
`definitions.py`는 이를 `Definitions(jobs=..., schedules=...)`에 포함한다.

모든 schedule은 `execution_timezone="Asia/Seoul"`이고, 외부 API 호출이 같은 시각에
몰리지 않도록 분/요일을 분산한다. 기본 status는 `STOPPED`다. 운영 배포에서 필요한
schedule만 enable하고, queue 기반 targeted update는 기존
`feature_update_request_queue_sensor`가 계속 담당한다.

검증 범위는 Dagster definitions smoke, schedule cron/timezone/tag 등록 테스트,
targeted ruff/mypy다. 사용자 지시에 따라 다음 한 작업은 **T-211a admin UI 최신화
선행 gap audit/API 계약 보강**이다. T-208f/T-208g는 admin UI 선행 작업 뒤로 미룬다.

## 2026-06-03 Codex 작업 메모 — T-207g OpenAPI admin/user 이원화

ADR-045 T-207g로 `packages/krtour-map-admin/scripts/export_openapi.py`를 admin/user
profile 기반 export로 확장했다. 기본 `--profile admin`은 기존
`packages/krtour-map-admin/openapi.json` 전체 admin spec을 유지하고,
`--profile user`는 TripMate/user-facing API subset을
`packages/krtour-map-admin/openapi.user.json`으로 생성한다. `--profile all`은 두
산출물을 함께 생성/검증한다.

user spec에는 `GET /features/in-bounds`, `GET /features/{feature_id}`,
`GET /features/search`, `GET /features/nearby/by-target`,
`POST /tripmate/features/batch`, `POST /admin/feature-update-requests`,
`GET /admin/feature-update-requests/{request_id}`만 포함한다. `/debug/*`,
`/ops/*`, `/admin/features*`와 내부 provider/admin 조회 API는 제외하고, 사용되는
schema만 재귀적으로 남기도록 `components.schemas`를 prune한다.

CI OpenAPI workflow는 `--profile all --check`로 admin/user 산출물 drift를 같이 막는다.
검증 범위는 export script unit, admin/user drift check, ruff다. 다음 한 작업은
**T-208d Dagster schedules(KST cron, 부하 분산)**다.

## 2026-06-03 Codex 작업 메모 — T-207e TripMate/public feature read API

ADR-045 T-207e로 TripMate와 사용자-facing 지도/상세/검색이 사용할 public feature
read API를 `krtour-map-admin`에 연결했다. 새 endpoint는
`GET /features/in-bounds`, `GET /features/search`,
`POST /tripmate/features/batch`다.

기존 `GET /features` bbox raw 응답은 admin frontend 호환용으로 유지했다. 대신
TripMate/public bbox는 `GET /features/in-bounds`에서 `{data, meta}` envelope를
반환한다. `GET /features/{feature_id}`는 `{data, meta.duration_ms}` envelope로 전환하고
`updated_at`을 포함하도록 갱신했으며, admin frontend 상세 fetch는 `body.data`를 읽는다.

`infra.feature_repo`에는 `get_feature_rows_by_ids`와 `search_features`를 추가했다.
검색은 `q` 또는 `bbox` 중 하나를 필수 scope로 요구하고, `q` 검색은 `pg_trgm` `%`
연산자와 transaction-local `pg_trgm.similarity_threshold`를 사용한다. bbox 술어는
stored `coord` 컬럼의 `&& ST_MakeEnvelope` 형태만 사용한다.

검증 범위는 feature router/repo unit, PostGIS feature repo 통합 테스트, OpenAPI export
갱신, frontend ESLint/type-check다. 다음 한 작업은 **T-207g OpenAPI export 이원화
(admin/user) + drift gate 갱신**이다.

## 2026-06-03 Codex 작업 메모 — T-207d ops consistency/jobs/metrics API

ADR-045 T-207d로 `krtour-map-admin`에 운영 조회용 `/ops/*` 라우터를 추가했다.
새 endpoint는 `GET /ops/metrics`, `GET /ops/import-jobs`,
`GET /ops/import-jobs/{job_id}`, `GET /ops/consistency/reports`,
`GET /ops/consistency/issues`다.

`infra.ops_repo`는 `ops.import_jobs`, `ops.feature_consistency_reports`,
`ops.data_integrity_violations`를 read-only raw SQL로 조회한다. 목록은 각각
`created_at`, `started_at`, `detected_at` 내림차순 keyset cursor를 사용하며, 기존
`jobs_repo`의 lifecycle 전이 함수는 건드리지 않는다.

`/ops/metrics`는 `status_repo.gather_status_counts`, dedup FP 통계, 열린
data integrity issue 집계, 최근 consistency report를 한 번에 반환한다. `/ops/import-jobs`
는 Dagster worker/feature update request가 남긴 `ops.import_jobs` 진행 상태를
운영 UI가 직접 조회하는 표면이고, `/ops/consistency/*`는 기존 batch report(F1~F4)와
Phase 2 issue 큐를 조회한다.

검증 범위는 `/ops` 라우터 unit test, PostGIS ops repository 통합 테스트, OpenAPI export
갱신이다. 다음 한 작업은 **T-207e `/features/*` + `/tripmate/features/batch`**다.

## 2026-06-03 Codex 작업 메모 — T-207c admin features/dedup backend

ADR-045 T-207c로 `krtour-map-admin`에 `/admin/features` 운영 목록과
`POST /admin/features/{feature_id}/deactivate`를 추가했다. 목록은
name/updated_at/created_at/kind/status/provider/issue_count sort, 반복 filter,
keyset cursor를 지원하고 primary source와 열린 data integrity issue summary를 함께
반환한다.

비활성화는 `feature.features.status='inactive'`만 전환하고 `deleted_at`은 건드리지
않는다. `prevent_provider_reactivation=true`이면 `ops.feature_overrides`에 active
`field_path='status'` override를 남기며, provider `upsert_feature`는 이 override가
있는 feature의 status/deleted_at을 덮어쓰지 않는다. 실제 PostGIS 통합 테스트에서
deactivate 후 provider가 같은 feature를 active로 재적재해도 inactive가 유지됨을 검증했다.

중복 검토 backend로 `/admin/dedup-review` 목록과 `PATCH /admin/dedup-review/{review_key}`를
추가했다. accepted/rejected/ignored 전이는 queue status만 갱신하고, merged는
ADR-039 `dedup-merge:{review_key}` advisory lock 안에서 `feature_merge_history`를 남기는
기존 merge path를 호출한다. 요청 body의 `master_feature_id`가 있으면 그 feature를
master로 사용하고, 없으면 기존 자동 master 선정 규칙을 따른다.

수동 feature 생성(`POST /admin/features`)과 영구 삭제(`DELETE /admin/features/{id}`)는
`ops.admin_audit_log` 설계가 선행되어야 하므로 이번 PR에서 구현하지 않았다. 다음 한
작업은 **T-207d `/ops/*` consistency/jobs/metrics**다.

## 2026-06-03 Codex 작업 메모 — T-208e Dagster feature update sensor

ADR-045 T-208e로 `packages/krtour-map-dagster`에 feature update request 큐 실행
sensor/job을 추가한다. `feature_update_request_queue_sensor`는 15초 간격으로
`AsyncKrtourMapClient.peek_next_update_request()`를 호출해 queued/now request 후보를
상태 변경 없이 확인하고, request id를 Dagster `RunRequest` run config/tag에 실어
`feature_update_request_worker` job을 생성한다.

worker job의 `execute_feature_update_request` op는 기존
`AsyncKrtourMapClient.execute_feature_update_request()`를 호출한다. 실제 provider 호출은
`feature_update_runner` resource가 맡고, 메인 라이브러리는 Dagster를 import하지 않는다.
executor가 request를 `failed`로 닫은 경우에도 op가 Dagster `Failure`를 발생시켜
Dagster run 상태와 `ops.feature_update_requests` 상태가 같이 관측된다.

`feature_update_request_failure_sensor`는 worker run 실패 시 run tag의 request id를 읽어
`AsyncKrtourMapClient.fail_update_request()`로 request/import job 실패 전이를 보강하고,
선택 resource `feature_update_failure_notifier`가 있으면 알림 payload를 전달한다.
T-207b는 사용자 결정에 따라 구현하지 않는다. 다음 한 작업은 **T-207c**다.

## 2026-06-03 Codex 작업 메모 — T-207f POI/cache target API

ADR-045 T-207f로 `krtour-map-admin`에 `/admin/poi-cache-targets`와
`/features/nearby/by-target` API를 추가한다. 외부 앱 POI는 좌표만으로 식별하지 않고
`external_system + target_key`를 정본 키로 삼는다. target upsert/list/detail/delete는
`infra.poi_cache_target_repo`를 호출하고, 같은 key + 다른 normalized 좌표는 기본 409로
막으며 `on_conflict='move'`에서만 이동한다.

주변 feature 조회는 `feature_repo.features_nearby_poi_cache_target`를 통해 target의
stored `coord_5179`와 feature의 stored `coord_5179`에 직접 `ST_DWithin`/`ST_Distance`를
적용한다. query filter는 `radius_km`, `kind`, `category`, `status`, `provider`,
`page_size`, `cursor`, `sort(distance/name/last_updated_at)`다. 목록 응답은 summary만
반환하고 `feature.detail` JSONB/raw payload는 포함하지 않는다.

검증 범위는 admin router unit test, PostGIS 주변 feature/cursor 통합 테스트,
OpenAPI export drift check다. 다음 한 작업은 **T-208e**다. Dagster sensor가
`ops.feature_update_requests` queued/now request를 `infra.feature_update_executor`로
실행하도록 연결한다.

## 2026-06-03 Codex 작업 메모 — T-207a admin update-requests 라우터

ADR-045 T-207a로 `krtour-map-admin`에 `/admin/feature-update-requests` 라우터를
추가했다. 구현 범위는 POST 생성(dry-run/actual), GET 목록, GET 단건, POST cancel,
POST run-now다. 생성/취소는 `ops.import_jobs`와 연결된 `infra.feature_update_repo`를
직접 호출하고, OpenAPI schema는 `packages/krtour-map-admin/openapi.json`에 export한다.

목록 필터는 `state`, `scope_type`, `provider`, `dataset_key`, `created_from`,
`created_to`, `page_size`, `cursor`다. 이를 위해 `infra.feature_update_repo`와
`AsyncKrtourMapClient.list_update_requests`도 optional filter를 받도록 확장했다.

`run-now`는 현재 API 레이어가 provider runner/Dagster를 직접 실행하지 않고, 기존
request payload를 `run_mode='now'` 새 request로 재큐잉한다. 실제 Dagster run 즉시
생성과 queued request polling은 T-208e sensor 연결에서 구현한다.

## 2026-06-03 Codex 작업 메모 — T-206d request 실행 본체

ADR-045 T-206d로 `infra.feature_update_executor`를 추가한다. 실행기는 queued
`feature_update_requests`를 claim한 뒤 실행 시점 scope를 다시 해석하고, provider/dataset
단위 refresh 계획을 만든다. 실제 provider 호출은 `ProviderDatasetRefreshRunner`로
주입받으므로 메인 라이브러리는 Dagster/provider client를 직접 import하지 않는다.

이번 범위에서 `scope.type='cache_target_keys'`도 구현한다. active
`ops.poi_cache_targets`를 `external_system + target_key`로 읽고, PostGIS
`coord_5179`로 주변 feature를 계산한다. missing/deleted/disabled key는
`matched_scope`에 남긴다. 실행 성공 후 target-feature link를 재계산하고 target
refresh 타임스탬프를 갱신한다.

검증 범위: runner가 실제 `FeatureBundle`을 DB에 적재하는 PostGIS 통합 테스트,
request/import job `done` 전이, `ops.poi_cache_target_feature_links` 재계산,
`provider_refresh_policies.targeted_policy='follow_system'` skip을 확인한다.

T-207a에서 이 실행기를 직접 호출하지는 않고, admin API는 request 생성/재큐잉 표면을
연결한다. 실행기 호출은 T-208e Dagster sensor가 담당한다.

## 2026-06-03 Codex 작업 메모 — T-205c Phase 2 ops 스키마

ADR-045 T-205c로 `alembic 0009_phase2_ops_tables`를 추가한다. 범위는
`ops.data_integrity_violations`, `ops.poi_cache_targets`,
`ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies`다. 각 테이블은
SQLAlchemy ORM row와 raw SQL repo를 같이 제공한다.

검증 범위: PostGIS migrated DB에서 table/index/check constraint, POI target
generated `coord_5179` + active key, provider refresh policy upsert/list, POI target
idempotent upsert/move/delete/link 비활성화, data integrity violation 생성/status/FK
동작을 `tests/integration/test_phase2_ops_schema.py`와
`tests/integration/test_phase2_ops_repos.py`로 확인한다.

다음 한 작업은 **T-206d**다. `feature_update_requests`의 queued request를 실제
provider/dataset refresh 실행으로 연결하고, 이번 PR의 `provider_refresh_policies`와
`poi_cache_targets`를 사용해 `cache_target_keys` scope와 rate-limit 정책 적용 경계를
구현한다.

## 2026-06-03 Codex 작업 메모 — T-206a-geo 검증 완료

형제 repo `python-kraddr-geo` main 기준으로 T-206a-geo를 재검증했다.
`POST /v2/regions/within-radius`와 `AsyncAddressClient.regions_within_radius()`는 이미
PR #114/#115 계열로 main에 포함되어 있고, `tests/integration/
test_optional_real_postgres_regions.py`는 `KRADDR_GEO_TEST_PG_DSN`이 있을 때 실제
`tl_scco_*`/`region_radius_parts` PostGIS 테이블을 조회하는 optional 테스트로 존재한다.

검증 결과: WSL mirror에서 `tests/unit/test_v2_api.py` +
`tests/integration/test_optional_real_postgres_regions.py` targeted pytest는
`15 passed, 1 skipped`였다. skip은 현재 shell에 `KRADDR_GEO_TEST_PG_DSN`이 없어서
발생했다. 대신 현재 로컬 API `http://127.0.0.1:9001`에
`POST /v2/regions/within-radius`를 직접 호출해 `sigungu` `11650`(서초구) contains
응답을 확인했다.

이후 T-205c Phase 2 ops 스키마 작업에 착수했다.

## 2026-06-03 Codex 작업 메모 — feature update client 표면

ADR-045 T-206c로 `AsyncKrtourMapClient`에 feature update request 메서드 4종을
추가한다. `enqueue_feature_update_request`는 `infra.feature_update_repo`를 감싸되,
`dry_run=True`일 때는 DB write 없이 preview만 반환하고 실제 enqueue는
`ops.feature_update_requests`와 연결 `ops.import_jobs` 생성을 한 transaction으로
묶는다. `get_update_request`, `list_update_requests`, `cancel_update_request`도 같은
client 표면으로 노출해 T-207a admin router와 T-208e Dagster sensor가 공유할
오케스트레이션 경계를 마련한다.

동시에 `from krtour.map import AsyncKrtourMapClient` top-level import를 실제 public
export로 맞추고, client/module 문서의 TripMate 직접 import 설명을 ADR-045 OpenAPI
운영 모델 기준으로 정정한다. 통합 테스트는 dry-run preview, enqueue, get/list,
cancel lifecycle을 PostGIS migrated DB에서 확인한다.

이후 T-206a-geo 검증을 완료했으므로 다음 한 작업은 T-205c다.

## 2026-06-03 Codex 작업 메모 — feature update request 큐 repository

ADR-045 T-206b로 `infra/feature_update_repo.py`를 추가한다. 이 repo는
`ops.feature_update_requests`와 `ops.import_jobs`를 같은 transaction에서 연결해
admin API와 Dagster sensor가 공유할 request lifecycle을 제공한다.

구현 범위는 dry-run preview(쓰기 없음), enqueue(request + import job 생성),
priority 기반 claim(`FOR UPDATE SKIP LOCKED` + advisory lock), start/finish/cancel,
get/list다. 목록은 D-10 결정대로 `created_at DESC, request_id DESC` keyset cursor를
base64 opaque cursor로 제공한다. `cache_target_keys` scope는 아직
`ops.poi_cache_targets`가 없으므로 Phase 2에 남긴다.

다음 한 작업은 T-206c다. `AsyncKrtourMapClient`에
`enqueue_feature_update_request` / `get_update_request` / `list_update_requests` /
`cancel_update_request`를 transaction 경계와 함께 노출하고, T-207a admin router가
그 client 메서드를 사용하게 준비한다.

## 2026-06-03 Codex 작업 메모 — feature update scope resolver

ADR-045 T-206a로 `infra/scope_repo.py`를 추가한다. resolver는
`feature_ids`, `center_radius`, `bbox`, `sigungu_by_radius`, `provider_dataset` scope를
read-only raw SQL로 해석하고, dry-run/queue 저장에 쓸 `matched_scope` payload를
만든다. `center_radius`는 입력 좌표를 CTE에서 한 번만 EPSG:5179로 변환하고
`feature.features.coord_5179`에 `ST_DWithin`을 직접 적용한다(ADR-012).

`sigungu_by_radius`는 kraddr-geo REST v2 `/v2/regions/within-radius`를 직접 import하지
않고, 호출자가 주입한 async resolver가 반환한 5자리 `sigungu_code`를 그대로 DB 조회에
사용한다. 이로써 `infra` → `geocoding` 레이어 역방향 import를 만들지 않는다.
`cache_target_keys`는 `ops.poi_cache_targets` 테이블이 필요한 Phase 2로 남긴다.

## 2026-06-03 Codex 작업 메모 — feature update request 스키마

ADR-045 T-205a로 `ops.feature_update_requests`를 Alembic `0008`과
`FeatureUpdateRequestRow` ORM 매핑에 추가한다. 이 테이블은 OpenAPI/admin UI가 만든
feature update request를 `ops.import_jobs`/Dagster run과 연결하기 위한 기반이다.

이번 범위는 **스키마/매핑/DDL 검증**이다. `scope_type` 6종(`feature_ids`,
`center_radius`, `sigungu_by_radius`, `bbox`, `provider_dataset`,
`cache_target_keys`), `run_mode`(`queued`/`now`), 상태 전이
(`queued`/`running`/`done`/`failed`/`cancelled`) CHECK, JSONB 기본값,
`job_id ON DELETE SET NULL`, claim/list용 인덱스를 검증한다. scope resolver,
enqueue/claim repository, admin API, Dagster sensor는 T-206/T-207/T-208 후속 PR로
분리한다.

## 2026-06-02 Codex 작업 메모 — admin UI Dagster 운영 화면

admin UI에 `/admin/dagster`를 추가했다. backend `GET /ops/dagster/summary`는
Dagster GraphQL을 호출해 version, code location, asset group, schedule/sensor, 최근
run 상태를 admin UI용 DTO로 정규화한다. frontend는 같은 화면에서 자체 요약 UI와
Dagster webserver iframe embed를 제공한다. 홈 화면에도 Dagster 상태 요약과 진입
링크를 추가했다. embedded Dagster webserver의 로컬 첫 실행 커뮤니티 모달은
`/ops/dagster/summary`가 `setNuxSeen`을 best-effort 호출해 접는다.

이번 범위는 Dagster **관측/관리 화면 1차 수직 슬라이스**다. feature update request
queue, import job progress, Dagster sensor/worker 연결은 기존 문서의 후속 구현 순서에
따라 별도 PR에서 진행한다.

## 2026-06-02 Codex 작업 메모 — Docker/포트 표준화

ADR-047로 krtour-map standalone 로컬 포트를 API `9011`, admin UI `9012`, Dagster
`9013`으로 고정했다. `AdminSettings`, frontend scripts, Playwright 기본 baseURL,
`.env.example`, runbook 문서를 같은 기준으로 맞추고, `scripts/stop-fixed-ports.sh`,
`scripts/load-env.sh`, `scripts/run-admin-stack.sh`, `scripts/docker-build.sh`,
`scripts/docker-up.sh`를 추가했다.

Docker 1차는 `postgres`, `api`, `frontend`, `dagster` 서비스로 구성한다. API는
Postgres health 이후 `alembic upgrade head`를 실행하고, `.env`의 provider service key는
`KRTOUR_MAP_ADMIN_*`/`NEXT_PUBLIC_*` 환경변수로 매핑한다.

## 2026-06-02 Codex 작업 메모 — krtour-map Dagster Feature ETL 1차 구현

TripMate 구현을 참고하지 않고 krtour-map 자체 Dagster code location
`packages/krtour-map-dagster/`를 추가했다. 메인 라이브러리 `krtour.map`은 계속
Dagster를 import하지 않으며, Dagster 패키지가 provider record resource를 받아 기존
provider 변환 함수 9종을 호출하고 `FeatureBundle` 주소/좌표 검증 후
`AsyncKrtourMapClient.load_feature_bundles`로 PostGIS에 적재한다.

1차 asset: datagokr 문화축제, OpiNet 주유소, KREX 휴게소/교통공지, krheritage
유산/행사, MOIS 인허가, KNPS point/geometry. 통합 테스트는 Dagster context를 통해
9개 asset runner를 실행하고 `feature.features`/`provider_sync.source_records`
커밋과 `coord_5179`/행정코드 적재를 검증한다.

## 2026-06-02 Codex 작업 메모 — kraddr-geo 반경 endpoint 재정합

kraddr-geo `origin/main` 기준 `POST /v2/regions/within-radius`가 구현되어 있음을
다시 확인하고, krtour-map `KraddrGeoRestClient`/helper/parser를 최신 REST v2 계약에
맞췄다. 공개 relation 값은 `contains`/`overlaps`이고, `sigungu.code`는 5자리,
`emd.code`는 8자리 행정구역 코드다. 추가로 `RegionV2.sig_cd`/`eup_myeon_dong`을
파싱해 bjd 없는 reverse 응답에서도 `sigungu_code`/`sido_code`/admin 이름을 보존한다.

실데이터 확인은 로컬 kraddr-geo REST `http://127.0.0.1:9001` + T-027 최종 적재
PostGIS DB(`tl_scco_ctprvn=17`, `tl_scco_sig=255`, `tl_scco_emd=5067`)로 수행했다.
샘플 `(lon=126.978, lat=37.5665, radius_km=3.0, levels=sigungu+emd)`에서 HTTP 200,
`sigungu` 6건, `emd` 190건을 확인했고, `resolve_sigungu_by_radius`는
`("11140", "11110", "11170", "11290", "11410", "11440")`를 반환했다.

## 2026-06-02 Codex 작업 메모

Codex는 admin frontend를 문서화된 stack(Next.js 16 + React 19 + TanStack Query +
Zustand + Zod + React Hook Form + shadcn/ui + maplibre-vworld) 기준으로 전환했다.
geocoding 전용 디버그 화면/라우터는 kraddr-geo 프로젝트에서만 본다는 사용자 결정에
따라 krtour-map-admin에서 제거했다. krtour-map에는 provider 주소 보강에 필요한
`krtour.map.geocoding` client만 남긴다. 검증은 frontend lint/type/build,
React Doctor, admin OpenAPI drift check, admin pytest, Windows Playwright e2e를
통과했다.

## 현재 상태

**Sprint 4 (4a+4b) ✅ 완료 → Sprint 5 + ADR-045 독립 프로그램화 🟡 진행 중**
(2026-06-03 기준). main 최신: `PR#159`. Sprint 4a
(MOIS Step A bulk + Step B incremental cursor + `krtour-map dedup-merge` +
`feature_merge_history` alembic 0007 + dedup FP 측정/운영 통계) + Sprint 4b
(MOIS Step C/D + ADR-033 F4 + Place phone enrichment + coverage 75→80 + 에이전트
runbook)를 PR#133~#142로 완료했다. PR#143~#149에서 ADR-045 admin/OpenAPI/cache
명세, 실행 계획, 모든 D-1~D-16 의사결정, `krtour-map-admin` rename을 완료했다.
그 전 PR#96~#114에서 Sprint 4 prep,
`/features` UX, geocoding v2 전환, Windows Git + NTFS 정책을 반영했다.
2026-06-01 추가 결정: **ADR-045**로 운영 모델을 Docker 독립 프로그램 + 독립
PostgreSQL/PostGIS DB + 독립 Dagster + TripMate OpenAPI 연동으로 전환했다. Admin
OpenAPI 기준 문서(`docs/openapi-admin-contract.md`), admin UI 상세 사양
(`docs/debug-ui-admin-workflows.md`), 외부 POI key 기반 캐시 갱신 타깃
(`docs/poi-cache-update-targets.md`)을 추가했다. TripMate 직접 import/공유 DB 모델은
legacy 참고로만 본다. **ADR-046**으로 ADR-045 이행 시 구 패키지명/env/import,
TripMate 직접 import, 공유 DB, TripMate-owned Dagster 호환 shim을 만들지 않는
정책을 확정했다.
테스트 최신 기준: full pytest **~835 passed** (coverage 실측 94.12%, gate
`fail_under=80`) + debug-ui non-live 117 + Windows Playwright e2e / GitHub Actions
(lint + pytest 3.11/3.12/3.13 + openapi-drift) 전체 green.

에이전트 공용 runbook은 `docs/runbooks/`(인덱스 README + `agent-workflow.md` 표준
1-PR 흐름 + `agent-failure-patterns.md` 반복 실패 회피) — 작업 전 후자 둘을 훑는다.

개발 환경 문서는 Windows Git(`git.exe`) + NTFS worktree
(`F:\dev\python-krtour-map*`)를 Git 원본으로 명시한다. WSL ext4는
테스트/실행 전용 샌드박스이며, 필요 시 NTFS 소스를 `rsync`해서 사용한다.
`python-kraddr-geo` 최신 로컬 포트 정책도 재확인하여 geocoding REST live
기본값은 FastAPI backend `http://127.0.0.1:9001`로 맞췄다.

Sprint 1 scaffolding (PR#17~#27) 종료 후 Sprint 2 (PR#28~#59)에서
ADR-034 9단계 중 ①~④ provider + 디버그 UI + ETL live 11/11 dataset을 구현했다.
Sprint 3(PR#60~#95)에서는 DB 적재/조회, consistency report, dedup queue,
client orchestration, KNPS/krheritage provider, `/features` debug UI까지 완료했다.

ADR **001~047 모두 accepted**. 029→043, 003·035 일부→045로 supersede.
ADR-044 = 관련 라이브러리 `F:\dev\` 로컬 우선 조회 + 데이터 정합성 책임은 각
provider 라이브러리. ADR-045 = krtour-map Docker 독립 프로그램 + 독립 DB/Dagster +
TripMate OpenAPI 연동(ADR-003 함수 직접 호출 모델 supersede). ADR-046 = 호환 shim
없이 정본 방향으로 이행. 다음 후보 번호 = ADR-048.

**Sprint 2 주요 산출물**:
- Provider ① 축제: `providers/standard_data.py` (datagokr 표준데이터,
  ADR-042) — `cultural_festivals_to_bundles`
- Provider ② 날씨: `providers/kma.py` (단기/초단기실황/초단기예보/특보 4종)
  + `dto/weather.py` (`WeatherValue` + 3 enum) + `core/weather.py` (5 pure helper)
- Provider ③ 유가: `providers/opinet.py` (`prices_to_values` +
  `stations_to_bundles`) + `dto/price.py` (`PriceValue` + `PriceDomain`)
- Provider ④ 휴게소: `providers/krex.py` (4 dataset multi-kind 통합)
- 디버그 UI backend: `create_app` factory + health/version + ETL preview
  (`?source=fixture` + `?source=live` KMA 3종) + OpenAPI drift gate
- 디버그 UI frontend: Next.js 16 + TanStack Query + Zustand skeleton +
  ETL preview 페이지
- Infra: `models.py` (SQLAlchemy 2 + GeoAlchemy2) + Alembic 2 revision
- Core: `scoring.py` (ADR-016 Record Linkage) + `providers.py` (canonical 18종)
  + `address.py` (bjd/phone/한글 정규화, ADR-041 kraddr-base 흡수)

**스택** (ADR-007):
- PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
- GeoPandas + Shapely 2 + GDAL
- Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic

TripMate 연계 (**ADR-045**, ADR-003 supersede): krtour-map은 Docker 독립 프로그램
이고 TripMate는 **OpenAPI(HTTP)** 로 feature 조회/상세/업데이트를 호출한다(직접
import·공유 DB 없음). admin/API는 `krtour-map-admin` 패키지(ADR-020, 내부망·
인증 없음 ADR-005)가 제공하며, 메인 라이브러리(`krtour.map`)는 그 api/dagster가
내부에서 쓰는 핵심 엔진이다.

## 다음 한 작업

### Sprint 2 잔여 — **전부 완료** (`sprints/SPRINT-2.md §7`)

- [x] visitkorea enrichment — PR#51 (`festival_to_enrichment_links`, 8 test).
- [x] KMA mid_forecast — PR#52 (`mid_land_forecast_to_weather_values` +
  `mid_temperature_to_weather_values`, 11 test).
- [x] ETL live 11/11 dataset — krex 4 (PR#55) / opinet 2 (PR#56) / datagokr 1
  (PR#57) / kma_weather_alerts apihub (PR#58).
- [x] Coverage bar 50→65 + Sprint 2 종료 회고 + Sprint 3 진입 (PR#59).

### 통합 검증 (사용자 지시 2026-05-28 — Sprint 2 종료 직후)

ETL 로직을 실데이터로 끝까지 검증하고 상세 리포트를 남긴다. (`tasks #114~#118`)

1. **weather_alerts data.go.kr fallback** (PR) — apihub authKey가 로컬에 없어
   `getWthrWrnList`(기존 `DATA_GO_KR_SERVICE_KEY`) fallback loader 추가 → 11/11
   전부 지금 live 검증 가능.
2. **ETL live 실데이터 + 정합성** — provider .env 키를 debug-ui `.env`(gitignore,
   커밋 금지)로 매핑 복사 후 11 dataset live 호출 → 유입/정합성 검증 + 리포트.
3. **DB 적재 통합 테스트** — FeatureBundle→`infra/models` ORM→testcontainer
   PostGIS 적재·재조회 검증 (docker는 WSL).
4. **Debug UI e2e** — WSL에 node 설치 → backend+frontend 기동, Windows Playwright로
   검증 + 스크린샷/리포트.
5. **종합 리포트** — `docs/reports/`에 테스트 케이스·결과·발견 이슈 정리.

> ⚠️ **키 이름 drift 발견**: provider repo .env의 실제 키 이름이 debug-ui
> settings 가정과 다름 — data.go.kr 게이트웨이는 공통 `DATA_GO_KR_SERVICE_KEY`
> (kma 동네예보/datagokr/krex/visitkorea), opinet=`OPINET_API_KEY`,
> krex(data.ex.co.kr)=`KEX_GO_API_KEY`. apihub authKey는 부재. → 통합 검증 시
> 매핑 + settings 문서 정정.

### Sprint 3 본작업 (통합 검증 후)

- **Provider ⑤ KNPS** 14 dataset (`providers/knps.py`) — Point/place 5건 +
  geometry(route/area) 5건 ✅ 구현. `knps_point_records_to_bundles` +
  `knps_geometry_records_to_bundles`(WKT 입력) + `core/geometry.py`(shapely) +
  `Feature.geom` 필드 + `feature_repo` geom 적재 (ADR-028/034/012). +
  **knps-api `CsvPreview` 브리지**(`knps_csv_preview_to_{point,geometry}_bundles`,
  best-guess 컬럼맵 override 가능). **본 lib KNPS 변환 완료** — SHP→WKT 디코딩은
  **knps-api 책임**(ADR-028 Amendment I / ADR-044). ⚠️ CSV 컬럼명 best-guess —
  live `CsvPreview.headers`로 확정 필요(현재 환경 data.go.kr 차단). `06da125f`.
  (통계 3건은 feature 본문 X.)
- **geocoding (kraddr-geo REST v2 연동)** (`krtour.map.geocoding`) ✅ — 좌표↔주소
  보강. **PR#90/#123**: in-process python client 후보(`reverse_v2`/`geocode_v2`)를
  쓰지 않고 **REST v2 `POST /v2/reverse`, `POST /v2/geocode`**로 전환.
  실제 `ReverseResponse`/`GeocodeResponse`/`AddressStructure`
  structural Protocol + 순수 변환 `reverse_response_to_address`/
  `geocode_response_to_coordinate` + `KraddrGeoRestClient`(httpx **주입**,
  TYPE_CHECKING-only — 메인 패키지 런타임 httpx 의존 X) + 팩토리
  `kraddr_geo_{reverse,address}_geocoder` + `cached_reverse_geocoder`(좌표 메모이즈).
  설정: `KRTOUR_MAP_KRADDR_GEO_BASE_URL` (로컬 기본 예:
  `http://127.0.0.1:9001`).
- **provider 변환기 전면 async + geocoder 자동 보강** ✅ — festival/opinet/krex/
  knps 변환 함수가 모두 `async` + `reverse_geocoder` 인자. feature_id 계산 전에
  await해 bjd_code 보강(ADR-009 — 'global' bucket 탈출). standard_data sync
  Protocol 제거 → geocoding async `ReverseGeocoder`로 통일. debug-ui etl 경로도
  async. **남은 것**: kraddr-geo client 수명·실 DB 적재 오케스트레이션은 호출자.
- **Provider ⑥ krheritage** (`providers/krheritage.py`) ✅ — 국가유산 place +
  area + event. `heritage_items_to_bundles`(place/area, ccba_kdcd로 kind 분기 +
  키워드 category) / `heritage_events_to_bundles`(EventDetail heritage_event).
  모두 async + reverse_geocoder. area는 GIS WKT(있으면) → geom + centroid.
  structural Protocol 입력(KrHeritageItem/KrHeritageEvent), krheritage import 안 함.
  **후속 ✅ 완료**: PR#85(#119) `FeatureFileSource` DTO + krheritage 미디어
  primary file_source / PR#86(#120) `geometry_area_square_meters` 측지 면적 +
  krheritage AREA 보강 / PR#87(#121) `find_dedup_candidates`(knps 사찰↔krheritage
  temple cross-score) / PR#88(#122) `ops.dedup_review_queue` 적재.
- ~~ADR-033 Phase 1 — `feature_consistency_reports` (F1~F3)~~ ✅ 완료
  (alembic 0003 + `infra/consistency.py` + 단위/통합 테스트)
- ~~`AsyncKrtourMapClient` 적재/dedup 오케스트레이션~~ ✅ 완료 (PR#89/#122 —
  `load_feature_bundles`/`sync_dedup_candidates`/읽기 메서드 + integration 3건).
- ~~Debug UI WSL 기동 + Windows Playwright e2e~~ ✅ 완료 (PR#91/#92/#93/#102/#114, #117 —
  workspace 루트 + 초기 e2e 7/7 + `/features` 9/9 + geocoding 포함 최신 14/14 +
  검출한 잠복 빌드 버그 fix + frontend CI 게이트).
- ~~`/features/*` 라우터 + frontend 지도 wiring (maplibre-vworld)~~ ✅ 완료
  (PR#95 — `/features` 지도 페이지: maplibre-gl + react-query + zustand viewport
  + bbox refetch + 단순 marker, e2e 2건 추가하여 9/9 통과).
- ~~Sprint 3 종료 회고 + Sprint 4 진입 준비~~ ✅ 완료 (본 prep PR —
  coverage bar 75 / SPRINT-3 §6 일괄 체크 / SPRINT-4 §1 진입 조건 + §3 **4a/4b
  분할 채택** / sprints/README.md + journal 회고 entry).

## 다음 한 작업 — **ADR-045 독립 프로그램화 / Sprint 5 진입**

Sprint 4(4a+4b)는 아래 체크리스트대로 **전부 완료**(PR#133~#142). ADR-045
의사결정은 PR#146~#149에서 **전부 확정**됐다. 다음 한 작업은
**ADR-045 독립 프로그램화** — 세분 실행 계획이 문서화됨:

- **실행 계획(정본, AI agent 실행용)**: `docs/adr045-standalone-plan.md` —
  Phase 1~6 + T-205~T-210 fine-grained task + 권장 순서 §8.
- **의사결정 결과**: `docs/adr045-open-decisions.md` — D-1~D-16 전부 결정 완료.
  구현은 이 결정을 그대로 따른다.
- **TripMate 연계 REST 계약**: `docs/tripmate-rest-api.md` (params/returns 1차).
- 기존 명세 정본: `docs/openapi-admin-contract.md`(admin API/큐 DDL/Docker 서비스),
  `docs/debug-ui-admin-workflows.md`, `docs/poi-cache-update-targets.md`,
  `docs/dagster-boundary.md`.

**1차 진입 task**(권장): T-205a(`feature_update_requests`
alembic 0008, 완료) → T-206a(scope resolver, 완료) → T-206b(feature update repo,
완료) → T-206c(client, 완료) → T-206a-geo(형제 repo endpoint 검증 완료) →
T-205c(Phase 2 스키마, 완료) → T-206d(request 실행 본체, 완료) →
T-207a(admin update-requests 라우터, 완료) → T-207f(POI/cache target API, 완료) →
T-208e(Dagster sensor, 완료) → **T-207c(admin features 검토/병합/override/deactivate)** →
T-207d/e(ops + 사용자 features 라우터) → T-208d(Dagster schedule). 그 다음
Sprint 5 provider(MOIS-sibling) + Phase 2 정합성.
세부는 `docs/sprints/SPRINT-5.md`.

### Sprint 4 (4a+4b) 완료 체크리스트 (PR#133~#142, 2026-06-01)

`docs/sprints/SPRINT-4.md §2.1` Step A(bulk):
- [x] `providers/mois.py` 변환 코어 — structural Protocol `MoisLicensePlaceRecord`
  + `license_record_to_bundle` / `license_records_to_bundles`(async +
  reverse_geocoder) + PROMOTED 42 category/place_kind 매핑 + EXCLUDED skip +
  facility_info. (자연키 `::` / marker P-01 / mypy·22 unit·ruff·import-linter green.)
- [x] `krtour.map.mois.load_mois_license_features_bulk` loader — `license_records_to_bundles`
  → `infra.load_bundles` 얇은 오케스트레이션 + `AsyncKrtourMapClient` 메서드 +
  PostGIS 통합 테스트 3건(적재/skip/idempotent/empty). (mypy 51 / 702 passed.)
- [x] Step A snapshot soft-delete — `infra.soft_delete_features_not_in_snapshot` +
  `krtour.map.mois.{delete_mois_license_features_not_in,sync_mois_license_features_bulk}`
  + `AsyncKrtourMapClient.sync_mois_license_features_bulk` + PostGIS 통합 3건.
  status='inactive'+deleted_at(ADR-017). (mypy 51 / 705 passed.)
- [x] advisory lock helper(ADR-011 기초) — `infra/advisory_lock.py`
  (`advisory_lock`/`try_advisory_lock` async ctx + `advisory_lock_key`) + unit 3 +
  PostGIS 통합 3건. conftest `pg_engine` search_path role 방어 보강. (mypy 52 / 711 passed.)
- [x] `ops.import_jobs` 작업 큐(ADR-011) — alembic 0006 + `ImportJobRow` +
  `infra/jobs_repo.py`(enqueue/claim advisory+SKIP LOCKED/heartbeat/finish/
  recover_stale) + `ImportJob` + integration 9. (mypy 53 / 720 passed.)
- [x] MOIS Step A 작업 통합 — `jobs_repo.start_import_job` + `krtour.map.mois.run_mois_license_bulk_job`
  (advisory lock 단일 워커 직렬화 + import_jobs 추적 + sync) + `AsyncKrtourMapClient`
  메서드 + `MoisBulkJobResult` + integration 2. (mypy 53 / 722 passed.)
- [x] MOIS Step A streaming 배치 적재 — `_batched` + `DEFAULT_BATCH_SIZE` +
  `batch_size` 인자(sync/run/client) + `FeatureLoadResult.merge`. `records`로
  `iter_open_place_records(...)` 주입 시 Step A 완성(ADR-006 호출자 주입). unit 7 +
  integration 1. (mypy 53 / 730 passed.)
- [x] CLI mutex(SPRINT-4 §2.8) — `src/krtour/map/cli/` layer 신설 + `cli/mutex.py`
  (`mutex_lock`/`try_mutex_lock` + lock key 헬퍼) + import-linter layers cli 최상위
  추가. unit 4 + integration 3. (mypy 55 / 737 passed.)
- [x] krtour-map CLI 골격 + status — `cli/main.py`(argparse + status) +
  `infra/status_repo.gather_status_counts` + `AsyncKrtourMapClient.status_counts` +
  `[project.scripts] krtour-map`. unit 5 + integration 2. (mypy 57 / 744 passed,
  `krtour-map --help` 실동작.)
- [x] dedup MOIS self-sibling — `core/dedup.find_sibling_candidates`(within-set
  pairwise) + `AsyncKrtourMapClient.sync_sibling_candidates`. unit 6 + integration 1.
  (mypy 57 / 751 passed.)
- [x] geocoder 보강 라이브 재검증 — kraddr-geo REST(`127.0.0.1:9001`) 실연동으로
  MOIS 좌표 → bjd_code 보강 200/200(100%) 확인. `docs/reports/mois-live-test-2026-06-01.md`
  §5. 코드 변경 없음.
- [x] CLI mutate 명령 ①  `krtour-map import mois <records-file>` — NDJSON snapshot
  record source(`cli/records.py`, ADR-006 provider 미import) → `run_mois_license_bulk_job`
  (advisory lock self-serialize + import_jobs 추적, lock 미획득 시 exit 3).
  `--geocoder-url` 선택 보강. unit 17 + integration 2. (ruff/mypy 58/import-linter 4 /
  776 passed.)
- [x] CLI mutate 명령 ② `krtour-map dedup-merge <review_key>` — 수동 병합(ADR-016).
  merge primitive 신규: `core.scoring.select_master`(좌표→updated_at→원천우선순위) +
  `infra.merge_repo`(source_link 재지정+충돌drop / loser soft-delete / 큐 merged 전이)
  + alembic 0007 `ops.feature_merge_history` + `client.merge_dedup_review`. lock은 CLI
  소유(`dedup-merge:{review_key}`), skip exit 3 / 미존재·이미검토 exit 2. unit 9 +
  integration 9. (ruff/mypy 59/import-linter 4 / 794 passed.)
- [x] Step B incremental + cursor. `infra/sync_state_repo`(get/record_success/failure,
  UPSERT) + `mois.run_mois_license_incremental_job`(prune 없음 + cursor 전진) +
  `client.run_mois_license_incremental_job` + `import mois --mode incremental --cursor
  <값> [--sync-scope]`. `provider_sync_state` 기존 테이블 활용(마이그레이션 없음).
  unit 3 + integration 9. (ruff/mypy 60/import-linter 4 / 806 passed.)
- [x] dedup false-positive 측정 + ADR-016 검토. 대표 평가셋 14쌍 채점 — 오토머지 FP
  **0** / true-dup recall **100%** / manual precision 63.6%. **가중치·임계값 변경 없음**
  (안전성 검증; 접미사 stripping은 접두사 충돌 FP 위험으로 보류). `docs/reports/
  dedup-fp-measurement-2026-06-01.md` + 회귀 가드 `tests/unit/test_dedup_fp_measurement.py`.
  (810 passed.)
- [x] (Sprint 4b) Step C 폐업/취소 — `infra.inactivate_features_by_source_entity_ids`
  + `mois.close_mois_license_features`/`run_mois_license_closed_job` + `import mois
  --mode closed --cursor`. feature `status='inactive'`(ADR-017). unit 3 + integration 7.
  (818 passed.)
- [x] (Sprint 4b) Step D on-demand 상세 — `infra.get_primary_source_detail` +
  debug-ui `GET /debug/mois-license/{license_id}`(TTL 캐시, **적재 없음**). 적재된
  raw_data 재사용(ADR-006). debug-ui unit 4 + integration 1. (819 + 117 passed.)
- [x] (Sprint 4b) dedup 운영 FP 측정 도구 — `infra.status_repo.dedup_fp_stats`
  (confirmed=merged+accepted / FP=rejected / precision / fp_rate) + `krtour-map status`
  `dedup FP(운영)` 라인. 운영자 결정 누적분으로 실 FP율 자동 집계(검토 완료 0이면
  "후보 없음"). dedup-fp 리포트 §6 운영 측정 경로 연결. unit 7. (826 passed.)
- [x] (Sprint 4b) ADR-033 F4 — dedup_review_queue 미해소 백로그 baseline 초과 → WARN
  (observe-only). `infra.consistency._check_f4_dedup_backlog` +
  `DEDUP_PENDING_WARN_THRESHOLD`(provisional 1000) + `dedup_pending_threshold` 인자.
  integration 3. (829 passed.)
- [x] (Sprint 4b) Place 전화번호 보강 백그라운드 시작 — `krtour.map.enrichment`
  (`find_place_phone_candidates` + `apply_place_phone_enrichment`: 정규화·dedup·max3 +
  enrichment source_link) + `infra.feature_repo.{find_place_features_without_phone,
  set_feature_phones}` + client 2 메서드. 외부 API는 호출자 주입(ADR-006). integration 6.
  (835 passed.)
- [x] (Sprint 4b) Coverage 80% 완전 달성 — `fail_under` 75→80(ADR-032 Sprint 4 목표).
  실측 **94.12%**(모든 tier 상회). **Sprint 4(4a+4b) 종료.**

## Open PR

(없음 — main 기준 모든 PR merged. 다음 작업은 새 feature branch로.)

## 완료 PR 요약

### 개발 정책 NTFS 전환 및 에이전트 워크트리 재설정 (PR#110, 2026-05-31)

- PR#110 `AGENTS.md` + `docs/dev-environment.md` + `docs/codegraph-worktree.md` 정책 문서 수정 (NTFS를 메인레포로 잡고 테스트 시 WSL 내 ext4로 카피하는 정책 정립, 에이전트별 worktree 프리픽스를 `python-krtour-map-`으로 개정하고 NTFS F:\dev\ 상에 신설 및 .env 로컬 키 복사, MCP 설정의 `codegraph.cwd` 를 각 에이전트 워크트리 경로로 동기화)

### maplibre-vworld-js 스타일 및 MCP 설정 동기화 (PR#107, 2026-05-31)

- PR#107 `react-doctor.config.json` + `.gemini/mcp.json` + `antigravity.json` + `claude.json` + `.codex/config.toml` (maplibre-vworld-js 프로젝트 스타일 및 에이전트별 MCP 설정을 가져와서 각 에이전트 worktree 경로에 맞게 보정하여 동기화)

### 에이전트 설정 형상관리 (PR#105, 2026-05-31)

- PR#105 `claude.json` + `antigravity.json` + `.codex/config.toml` (각 에이전트별 Playwright, Sequential Thinking MCP 설정 파일 생성 및 형상관리 등록)

### Sprint 1 (PR#17~#27, 2026-05-25 종료)

- PR#17 `src/krtour/map/` PEP 420 scaffolding + settings + smoke tests
- PR#18 `category/` 144건 (kraddr-base → krtour.map.category, ADR-023/027)
- PR#19 `dto/` Feature + 5 detail + Coordinate + Address + KST + 27 tests
- PR#20 `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests
- PR#21 `infra/` crs.py + db.py + testcontainers PostGIS + 31 tests
- PR#22 CI workflows + import-linter 4 계약 (Sprint 1 scaffolding 종료)
- PR#23 PR#1~#21 리뷰 리포트 (`docs/reports/pr-1-21-review.md`)
- PR#24 DTO strictness P0 해소 (detail dict 거부 + datetime aware)
- PR#25 python-knps-api keyless sync + ADR-028 amendment §H
- PR#26 `make_source_record_key` + `make_payload_hash` + SourceRecord/Link/Bundle
- PR#27 review P1 docs drift sweep

### Sprint 2 Prep (PR#28~#29, 2026-05-26)

- PR#28 `infra/models.py` SQLAlchemy 2 + GeoAlchemy2 + Alembic 2 revision
- PR#29 `core/scoring.py` (ADR-016) + `core/providers.py` (canonical 18종)

### Sprint 2 본격 (PR#30~#48, 2026-05-27~28)

- PR#30~31 agent worktree + codegraph 룰 + MCP snippet
- PR#32~33 거버넌스 보강 + ADR-035~043 proposed→accepted
- PR#34 Sprint 2 §2.1 datagokr 축제 1차 (`cultural_festivals_to_bundles`)
- PR#35 디버그 UI backend 첫 라우터 (health/version + openapi drift gate)
- PR#36 frontend skeleton (Next.js 15 + TanStack Query + Zustand)
- PR#37 ADR-041 kraddr-base 흡수 — Address DTO 보강 + `core/address.py`
- PR#38 `WeatherValue` DTO + 3 enum + KMA 단기예보 1차
- PR#39 KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종
- PR#40 `python-*-api` 라이브러리 status sweep
- PR#41 KMA 초단기예보 (`getUltraSrtFcst`) + LGT(낙뢰)
- PR#42 `PriceValue` DTO + `PriceDomain` + opinet `prices_to_values`
- PR#43 opinet `stations_to_bundles` (gas station Feature)
- PR#44 디버그 UI ETL preview 라우터 (fixture dry-run)
- PR#45 Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind
- PR#46 KMA weather_alerts → notice + krex category fix + ETL 11 dataset
- PR#47 ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소
  (httpx dep / Alembic 1.18 path_separator + async commit / coord_5179 assert)
- PR#48 agent worktree `geo-*` → `krtour-map-*` rename + tasks.md 최신화
- PR#49 maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment)
- PR#114 maplibre-vworld v0.1.2 + Next.js 16 최신화 (git URL+tag, ESLint CLI flat config)
- PR#50 Sprint/task/resume 문서 일관성 재정비
- PR#51 Sprint 2 §2.1 끝물 — VisitKorea TourAPI enrichment (`festival_to_enrichment_links`)
- PR#52 Sprint 2 §2.2 마무리 — KMA 중기예보 (`mid_land_forecast`/`mid_temperature`)
- PR#53 fix: OpiNet product code map C004/K015 정정 (kerosene/lpg)
- PR#54 ADR-044 — 관련 라이브러리 로컬(`F:\dev\`) 우선 조회 + 데이터 정합성 책임 분계
- PR#55 ETL live — krex 4 dataset loader (EX OpenAPI, 14 단위 test)
- PR#56 ETL live — opinet 2 dataset loader (detailById.do, KATEC→WGS84, 10 단위 test)
- PR#57 ETL live — datagokr 전국문화축제표준데이터 loader (7 단위 test)
- PR#58 ETL live — kma_weather_alerts (apihub `wrn_now_data`, 8 단위 test) → 11/11 live
- PR#59 Sprint 2 종료 — coverage 50→65 + 회고 + Sprint 3 진입 (본 PR)

### 문서/거버넌스 (PR#1~#16, 2026-05-24~25)

- PR#1 ADR-021/022/023 (PR-only + namespace + category 이전)
- PR#2 T-002~T-011 (v1→v2 docs 14건 이전)
- PR#3~4 ADR-024 + mois-feature-etl.md
- PR#5 forest rename + category Tier 1~4 + KNPS 카탈로그
- PR#6 ADR-025/026 (maplibre-vworld + TripMate UI 통일)
- PR#7 tasks.md 백로그
- PR#8 ADR-030/031/032/033 proposed
- PR#9 ADR-027 (forest category 확장)
- PR#10 ADR-029 + T-012~018 codify + 명명 일치화
- PR#11 ADR-025 2차 (Vite → Next.js)
- PR#12 ADR-028 + knps-feature-etl.md
- PR#13 tasks.md 갱신
- PR#14 ADR-034 provider 9단계 + Sprint 2~5 plan
- PR#15 governance sweep
- PR#16 T-014 Sprint 1 진입 (ADR 027~034 accepted + fail_under=50)

## 진척도

### 핵심 governance / 결정

- [x] `AGENTS.md` / `README.md` / `SKILL.md` / `CLAUDE.md`
- [x] `LICENSE` (GPL-3.0-or-later)
- [x] `.gitignore`, `.gitattributes`, `.env.example`
- [x] `pyproject.toml` (스택 + import-linter 계약)
- [x] `docs/architecture.md` (의존 방향 + 데이터 흐름)
- [x] `docs/decisions.md` (ADR-001 ~ ADR-043, 전부 accepted)
- [x] `docs/data-model.md` / `docs/performance.md` / `docs/test-strategy.md`
- [x] `docs/backend-package.md` / `docs/agent-guide.md`
- [x] `docs/dev-environment.md` / `docs/windows-reinstall-recovery.md`
- [x] `docs/feature-model.md` / `docs/provider-contract.md` / `docs/external-apis.md`
- [x] `docs/debug-ui-package.md` / `docs/codegraph-worktree.md`
- [x] `docs/tasks.md` / `docs/resume.md` / `docs/journal.md`
- [x] ADR-021 (PR-only) + ADR-022 (krtour namespace) + ADR-023 (category 이전)
- [x] Sprint 1~5 계획 (`docs/sprints/SPRINT-1.md` ~ `SPRINT-5.md`)

### 코드 산출물

- [x] `src/krtour/map/category/` — 144건 PlaceCategory
- [x] `src/krtour/map/dto/` — Feature + 5 detail + Coordinate + Address +
      WeatherValue + PriceValue + SourceRecord/Link/FeatureBundle
- [x] `src/krtour/map/core/` — exceptions 7종 + `make_feature_id` +
      `make_source_record_key` + `make_payload_hash` + `make_weather_value_key` +
      `make_price_value_key` + scoring (Record Linkage) + providers (canonical 18종)
      + weather (5 helper) + address (bjd/phone/한글 정규화) + types (KST)
- [x] `src/krtour/map/infra/` — models.py (ORM, +FeatureConsistencyReportRow) +
      crs.py (pyproj) + db.py (async engine) + consistency.py (ADR-033 Phase 1
      F1~F3) + Alembic 3 revision (0003 = ops.feature_consistency_reports)
- [x] `src/krtour/map/providers/` — standard_data / kma / opinet / krex /
      visitkorea (enrichment, PR#51) / knps (Point/place 5 + geometry route/area
      5) — 6 provider. `core/geometry.py`(shapely WKT) + `Feature.geom` 추가.
- [ ] `src/krtour/map/providers/` — knps SHP bytes→WKT 디코딩(park_boundaries) /
      krheritage (Sprint 3) / mois (Sprint 4)
- [x] `src/krtour/map/infra/feature_repo.py` — raw SQL load 경로 (Sprint 3 —
      FeatureBundle upsert features/source_records/source_links + get_feature_row,
      ADR-004; bulk COPY + /features 라우터는 후속)
- [ ] `src/krtour/map/client/` — `AsyncKrtourMapClient` (Sprint 3~4)
- [x] `packages/krtour-map-admin/` — create_app + routers (health/version/etl)
      + settings (8 provider key) + etl_fixtures + etl_live + openapi.json
- [x] `packages/krtour-map-admin/frontend/` — Next.js 16 + TanStack + Zustand
      + ETL preview page
- [x] `packages/map-marker-react/` — skeleton (`private: true`, ADR-043)
- [x] `.github/workflows/{ci,lint,openapi}.yml` + import-linter 4 계약
- [x] `tests/` — 469+ pytest (unit + integration + lint)
- [x] 에이전트별 MCP 설정 파일 (`claude.json`, `antigravity.json`, `.codex/config.toml`)

### 미완료 (Sprint 순서)

- [x] visitkorea enrichment (Sprint 2 잔여 1/4 — PR#51)
- [x] KMA 중기예보 (`mid_forecast`, Sprint 2 잔여 2/4 — PR#52)
- [x] ETL live 11/11 dataset (Sprint 2 잔여 3/4 — PR#55~#58)
- [x] Coverage 65% (Sprint 2 DoD — PR#59)
- [ ] 통합 검증 (ETL live 실데이터/정합성/DB 적재/Playwright e2e + 리포트, tasks #114~#118)
- [ ] KNPS 14 dataset + krforest trails (Sprint 3)
- [ ] krheritage 국가유산 (Sprint 3)
- [x] ADR-033 Phase 1 F1~F3 (Sprint 3 — alembic 0003 + `infra/consistency.py`)
- [x] `infra/feature_repo.py` raw SQL load 경로 (Sprint 3 — upsert/load_bundles/
      get_feature_row, ADR-004)
- [x] `/features/*` 조회 라우터 (debug-ui — bbox + 단건, `features_in_bbox`,
      Sprint 3). frontend 지도 wiring(#117)은 후속.
- [x] MOIS Step A~D 4단계 (Sprint 4 — bulk/incremental/closed/detail)
- [x] dedup_review_queue 운영 + dedup-merge + feature_merge_history (Sprint 4)
- [x] ADR-033 F4 (dedup 백로그 WARN, Sprint 4b)
- [x] Place phone enrichment (Sprint 4b — `krtour.map.enrichment`)
- [ ] 휴양림/수목원 + 박물관/미술관 (Sprint 5)
- [ ] Phase 2 F5~F8 + Dagster 게이트 (Sprint 5)
- [ ] ADR-045 Docker 독립 프로그램화 (compose + admin OpenAPI + 독립 Dagster)
- [ ] T-101 MV / T-102 pg_prewarm / T-103 streaming (운영 후)

## 다음 ADR

**accepted (text on main)**: ADR-001 ~ ADR-047 전부.
029→043 supersede, 044 (로컬 우선 조회 + 정합성 책임), 045 (krtour-map Docker 독립
+ OpenAPI, ADR-003 supersede), 046 (호환 shim 금지), 047 (고정 포트
API 9011/admin UI 9012/Dagster 9013). 다음 후보 번호 = ADR-048.

**후보 (미작성)**:
- ADR-048+ — 신규 provider 추가 절차 표준 (체크리스트)
- (필요 시) Sprint 5 MV / pg_prewarm 도입 ADR (T-101/102)

## 차단 사유 / 결정 대기

- **Sprint 2 → 3 전환**: (visitkorea enrichment ✅ PR#51) mid_forecast + ETL
  live 8종 + coverage 상향 후 Sprint 2 종료 회고 → Sprint 3 진입 PR.
- ~~**SHP/GeoJSON parser 위치**~~: ✅ 결정됨 (2026-05-29) — **knps-api 책임**
  (ADR-028 Amendment I / ADR-044). 본 lib는 record(좌표·WKT) Protocol 소비만.
- **ADR-033 Phase 1 시점**: Sprint 3 진입 후 `feature_consistency_reports` F1~F3
  도입 — Sprint 2 provider 적재가 선행 조건.

## v1 산출물 reference

코드 작성 단계에서 v1을 참고할 때:

```bash
git checkout v1                          # v1 브랜치로
ls src/krtour/map/                       # 기존 모듈 구조
cat docs/event-feature-etl.md            # provider 문서 예시
git checkout main                        # 복귀
```

또는 GitHub UI:
- https://github.com/digitie/python-krtour-map/tree/v1

저장소 루트의 `python-krtour-map-spec.docx` (약 80쪽)는 v1 산출물 + SPEC V8
정합 + kraddr-geo 디시플린을 종합한 reference.

## 핵심 메시지

Sprint 2 완료 — provider ①~④(축제·날씨·유가·휴게소) + visitkorea enrichment +
KMA mid_forecast + 디버그 UI backend + **ETL live 11/11 dataset** + coverage 65.
다음은 사용자 지시(2026-05-28)에 따른 **통합 검증**: ETL live 실데이터로 유입·
정합성·DB 적재·debug UI(Playwright)를 끝까지 검증하고 상세 리포트를 남긴다.
그 후 Sprint 3 (KNPS/krheritage + 정합성 Phase 1 + `feature_repo.py` 실 적재)
진입. 현재 적재(DB write)는 아직 없고 provider → DTO 변환 + 디버그 preview까지
완성된 상태다.
