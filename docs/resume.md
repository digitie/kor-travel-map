# resume.md — 현재 진척도와 다음 한 작업

## 2026-06-13 Codex 작업 메모 — T-226 runtime 이름 추가 재결정

사용자 추가 결정에 따라 T-226 목표값을 다시 정렬했다.

- CLI 목표명은 `ktmctl`로 둔다.
- PostgreSQL 기본 DB 이름은 `kortravelmap`, Dagster metadata DB 이름은
  `kortravelmap_dagster`로 둔다.
- RustFS bucket/volume 등 사용자 가시 이름은 `kortravelmap*` 계열로 둔다
  (예: offline upload bucket `kortravelmap-uploads`).
- 형제 프로젝트의 GitHub repo/project 표시명은 `kor-travel-geo`,
  `kor-travel-concierge` 기준으로 맞춘다.
- public distribution `kor-travel-map`, Python import root `kortravelmap`, 권장 import
  `import kortravelmap as ktm`, env prefix `KOR_TRAVEL_MAP_*`는 유지한다.

**다음 한 작업**: **T-225** — T-212e closure 재검증. T-226c/d는 위 목표값 기준으로
package/runtime identity clean cut을 이어간다.

## 2026-06-13 Codex 작업 메모 — T-226 import root 재결정 반영

사용자 재결정에 따라 T-226 목표 Python import root를 `kortravelmap`으로, 권장 import
패턴을 `import kortravelmap as ktm`으로 변경했다.

- ADR-054, `docs/package-identity-rename.md`, T-226b 실행계획의 최종 layout을
  `src/kortravelmap`, `kortravelmap.admin`, `kortravelmap.dagster`로 정렬했다.
- README/AGENTS/SKILL/CLAUDE/backend-package/architecture/provider-contract/
  integration-map/tasks/journal의 T-226 note와 작업 설명도 같은 기준으로 맞췄다.
- public distribution `kor-travel-map`, env prefix `KOR_TRAVEL_MAP_*`은 그대로 유지한다.

**다음 한 작업**: **T-225** — T-212e closure 재검증(최신 표면 포함 여부,
live row 수/P99, 리포트 링크 재대조). T-226c Python import/package layout clean cut은
그 다음 큰 package identity 후속이다.

## 2026-06-12 Codex 작업 메모 — T-226b package clean cut 실행계획

T-226b로 `kor-travel-map` / `kortravelmap` 코드 clean cut의 실행 단위를 확정했다.

- 현 main 기준 Python/설정/문서 후보 908개 파일 중 `krtour.map` 참조 파일 368개,
  `KRTOUR_MAP` 참조 파일 86개가 확인됐다.
- 최종 Python layout은 `src/kortravelmap`, `kortravelmap.admin`, `kortravelmap.dagster`로 둔다.
  admin/dagster package path와 distribution도 `kor-travel-map-admin`,
  `kor-travel-map-dagster`로 전환한다.
- 구 `krtour.map` / `krtour.map_admin` / `krtour.map_dagster` /
  `KRTOUR_MAP_*` compatibility shim은 만들지 않는다.
- 실제 구현은 T-226c(Python import/package layout), T-226d(runtime/deployment
  identity), T-226e(소비자 문서/client/migration guide)로 나눈다.

**다음 한 작업**: T-212e는 다른 agent가 병행 진행 중이다. 본 agent가 이어갈 수 있는
다음 작업은 **T-226c** Python import/package layout clean cut이다. PR 시작 전 main
rebase와 T-212e 최종 머지 여부를 다시 확인한다.

## 2026-06-12 claude 작업 메모 — T-212e 완결 (실데이터 full reload)

T-212e를 종결했다. 정본 리포트
`docs/reports/t-212e-live-full-reload-final-2026-06-12.md`.

- 빈 DB에서 전 provider Dagster 적재 **1,095,665 features**(MOIS 980,970 /
  MCST 13종 102,121 / knps_trails 618 등) + weather values 92,923.
- consistency gate 최종 report `99159eea` severity_max OK / offline upload
  3포맷 + DELETE lifecycle live 검증 / e2e 33/33 / API smoke 17/17 /
  backup→staging restore 검증값 운영 정확 일치 / P99 수집(in-bounds 442ms —
  클러스터 MV ADR 재판단 입력).
- 실측 적발 수정: krtour 11 PR + provider 5 repo(이슈→PR→머지 패턴).
  이슈 #397/#407/#409 close.

**다음 한 작업**: **T-225** — T-212e closure 재검증(최신 표면 포함 여부,
live row 수/P99, 리포트 링크 재대조 — 본 리포트가 1차 입력). 그 외 큰 트랙은
T-226b/c package identity clean cut.

## 2026-06-12 Codex 작업 메모 — T-226a package identity ADR

T-226a로 package identity rename 정본을 문서화했다.

- ADR-054를 accepted로 추가했다. public 배포명은 `kor-travel-map`, Python import root는
  `kortravelmap`, 권장 예시는 `import kortravelmap as ktm`다.
- `docs/package-identity-rename.md`를 추가해 현재값(`python-krtour-map`, `krtour.map`,
  `KRTOUR_MAP_*`, `krtour_map`)과 목표값(`kor-travel-map`, `kortravelmap`,
  `KOR_TRAVEL_MAP_*`, `kortravelmap`)을 분리했다.
- README/AGENTS/CLAUDE/backend-package/architecture/provider-contract/integration-map에는
  "현재 표기는 T-226 후속 clean cut 전 코드 기준, 목표 identity는 ADR-054"라는 note를 추가했다.
- clean cut/no-shim 원칙을 확정했다. 구 `krtour.map`/`KRTOUR_MAP_*` compatibility shim은
  만들지 않는다.

**다음 한 작업(당시)**: **T-226b** — 2026-06-12 실행계획 PR로 완료했다.

## 2026-06-12 Codex 작업 메모 — T-223d TripMate import 머지

T-223d 외부 TripMate 연동까지 완료했다.

- TripMate PR #184(`5966628192a1f7b0c359a6435011f3e2f3f04469`)가 머지되어,
  `POST /admin/notice-plans/imports/krtour-curated-features`가 krtour-map
  `/v1/curated-features/{curated_feature_id}/tripmate-copy` snapshot을 소비한다.
- TripMate는 `app.curated_trip_plans` / `app.curated_plan_pois`로 복사하고,
  `source_system`, `source_curated_feature_id`, `source_curated_feature_version`,
  `source_etag`, `source_imported_at`, source item id를 저장한다.
- `create` / `upsert` / `refresh` mode, 기존 feature-backed POI 재사용, 신규 item
  LexoRank append가 검증됐다.
- TripMate 쪽 `TRIPMATE_AGENT_API_BASE_URL` / 12401 잔여 설정도 제거됐다.
  `krtour-ai-agent`는 curated trip plan 생성에 관여하지 않는다.

**다음 한 작업(당시)**: T-212e는 다른 agent가 병행 진행 중이다. 완료 결과가 머지되면
**T-225**로 최신 T-221/T-222/T-223 표면 포함 여부와 live row 수/P99/offline upload 증거를
재대조한다. 그 전까지 본 agent의 다음 큰 후속은 T-226 package identity rename
ADR/문서 정본화였고, T-226a로 완료했다.

## 2026-06-12 Codex 작업 메모 — T-223c-3 curated Admin UI

T-223c-3로 curated overlay 운영 화면을 admin frontend에 연결했다.

- `/admin/curated-features` route를 추가했다. theme/provider/dataset/status/page
  filter와 후보 table을 제공하고, row별 select/unselect/archive mutation을 연결했다.
- 선택 후보 inspector에서 display title/summary, rank score, TripMate copy policy,
  TripMate relation을 편집할 수 있다.
- Source rule 목록과 editor를 붙여 `enabled`, `default_action`, `priority`,
  `place_kind`, `category`, `region_scope`, `metadata`를 수정하고 rule apply를 실행할 수
  있다.
- TripMate copy preview는 `/v1/curated-features/{id}/tripmate-copy` snapshot을 조회해
  plan/source/theme/items를 보여준다.

검증: admin frontend `type-check`, `lint`, React Doctor 통과(Doctor는 필수 error 없음,
optional warning만 남음).

**다음 한 작업(당시)**: **T-223d** — 2026-06-12 TripMate PR #184로 완료했다.
T-212e는 다른 agent가 병행 진행 중이며, 결과는 T-225에서 다시 대조한다.

## 2026-06-12 Codex 작업 메모 — T-223c-2 curated Dagster group

T-223c-2로 curated overlay 운영 배치를 Dagster asset group으로 연결했다.

- Alembic `0026_curated_copy_snapshots`로
  `feature.curated_tripmate_copy_snapshots` cache table을 추가했다.
- `curated_repo`에 source metadata refresh, enabled source rule bulk apply,
  inactive/deleted feature status sweep, TripMate copy snapshot materialize 함수를
  추가하고 `AsyncKrtourMapClient` 표면으로 노출했다.
- Dagster `curated_features` asset group을 추가했다:
  `curated_source_metadata` → `curated_feature_candidates` →
  `curated_feature_status_sweep` → `curated_tripmate_copy_snapshots`.
  `curated_features_refresh` asset job과 `curated_features_refresh_daily_schedule`
  (04:55 KST, 기본 `STOPPED`)도 등록했다.

검증: curated repo unit, Dagster curated/definitions unit, curated repo PostGIS
integration 통과.

**다음 한 작업(당시)**: **T-223c-3** — Admin UI 구현. curated 후보 목록,
select/unselect, source rule 편집/apply, TripMate copy preview를 admin frontend에
연결한다. 이후 T-223d TripMate 복사 연동으로 진행한다. T-212e는 다른 agent가 병행
진행 중이며, 결과는 T-225에서 다시 대조한다.

## 2026-06-12 Codex 작업 메모 — T-223c-1 curated DB/API foundation

T-223c 첫 조각으로 krtour-map의 curated overlay DB/API 기반을 구현했다.

- Alembic `0025_curated_features`로 `feature.curated_themes`,
  `curated_sources`, `curated_source_rules`, `curated_features` 4개 테이블과
  책방/세계음식/무장애/반려동물/가족/미디어/레저/특화거리 seed source/rule을 추가했다.
- `curated_repo`를 추가해 list/detail/create/patch/select/unselect/archive,
  source rule apply, TripMate copy snapshot(`etag`, `copy_version`)을 제공한다.
- `GET /v1/curated-themes`, `/curated-sources`, `/curated-features*`,
  `/tripmate-copy`와 `/v1/admin/curated-*` backend API를 추가했다.
- `openapi.json`/`openapi.user.json`과 `@krtour/map-user-client` 타입을 재생성했다.

검증: curated route unit, curated repo integration, targeted ruff/mypy 통과.

**다음 한 작업**: **T-223c-2** — Dagster `curated_features` group 구현.
`curated_source_metadata`, `curated_feature_candidates`, `curated_feature_status_sweep`,
copy snapshot materialize/cache를 backend repo 함수와 연결한다. 이후 T-223c-3 Admin UI,
T-223d TripMate 복사 연동 순서로 진행한다. T-212e는 다른 agent가 병행 진행 중이며,
결과는 T-225에서 다시 대조한다.

## 2026-06-12 Codex 작업 메모 — T-222b public beaches/festivals API

T-222b로 TripMate T-130 차단 조건이던 공개 해수욕장/축제 사용자 API를 krtour-map
쪽에 구현했다.

- `src/krtour/map/infra/public_views_repo.py`를 추가했다. 해수욕장은
  `kind='place'` + `detail.place_kind='beach'`, 축제는 `kind='event'` +
  `detail.event_kind IN ('festival', 'cultural_festival')`와 기간 겹침으로 조회한다.
- `GET /v1/public/beaches`, `/beaches/map-markers`, `/beaches/{feature_id}`,
  `/festivals/monthly`, `/festivals/map-markers`, `/festivals/{feature_id}`를 추가했다.
- user OpenAPI allowlist와 `@krtour/map-user-client` 생성 타입/alias를 갱신했다.
- category drift는 `place_kind='beach'` 1차 판별로 닫았다. KHOA provider category
  `01020300`은 보조 정보로 유지하고, 예전 문서값 `01050100`은 판별 기준에서 제외한다.
- KHOA 폭/길이/재질은 nullable projection으로 열어 두고, 현재는 `facility_info` 또는
  primary raw payload에 값이 있을 때만 채운다. 수질/index/weather는 null/빈 배열 후속이다.

검증: public view 라우터 단위 테스트 6 passed, repo 통합 테스트 2 passed,
`ruff check .`, targeted mypy, `export_openapi.py --profile all --check`,
`npm -w packages/krtour-map-user-client run type-check` 통과.

**다음 한 작업**: **T-223c** — krtour-map DB/API/Dagster/Admin UI 구현
(`feature.curated_*`, `/v1/curated-features*`, `/v1/admin/curated-*`,
Dagster `curated_features` group, admin 선택/해제 UI). T-222c는 TripMate PR#183으로
완료됐고, T-223b provider 보강은 provider PR#10/#11 + krtour-map 변환 구현으로
완료했다. T-212e는 다른 agent가 병행 진행 중이며, 결과는 T-225에서 다시 대조한다.

## 2026-06-12 Codex 작업 메모 — T-221e ops logs + debug 재판정

T-221 마지막 조각으로 `/ops/logs`를 import job event stream과 연결하고 debug 진단 표면을
정리했다.

- `GET /v1/ops/import-job-events`를 추가했다. `job_id`/`provider`/`dataset_key`/
  `level` 필터와 keyset cursor를 지원하며, 기존 job별
  `/v1/ops/import-jobs/{job_id}/events`는 유지한다.
- admin frontend `/ops/logs`는 System logs / API call logs / Job events 3탭이 됐다.
  Job events 탭은 provider/dataset/job/level 필터와 `/ops/import-jobs/[job_id]` 상세
  링크를 제공한다.
- `/debug/explain` REST/UI는 만들지 않는다. raw SQL 입력 화면 대신 통합 테스트
  EXPLAIN gate와 운영 DB read-only runbook을 기준으로 둔다.
- `/debug/fixtures` REST/UI도 만들지 않는다. fixture 저장·갱신은 파일 기반 helper와
  provider 회귀 테스트, preview는 기존 `/debug/etl`로 분리한다.

**다음 한 작업**: **T-222b** — 공개 해수욕장/축제 뷰 API 백엔드/OpenAPI/user-client 구현.
T-212e는 다른 agent가 병행 진행 중이며, 결과는 T-225에서 다시 대조한다.

## 2026-06-12 Codex 작업 메모 — T-221d provider 상세/refresh policy

T-221d로 provider 운영 상세와 refresh policy 편집 흐름을 연결했다.

- `GET /v1/ops/providers`, `GET /v1/ops/providers/{provider}`를 추가했다. 기존
  `/v1/providers` 사용자 표면은 cursor를 계속 숨기고, ops 상세 표면에서만
  sync cursor, refresh policy, 최근 `provider_dataset` update request를 묶어 보여준다.
- `GET/PUT /v1/admin/provider-refresh-policies*`를 추가했다. policy upsert는
  `system_interval_seconds`/`optimal_interval_seconds`가 `min_interval_seconds`와
  선언된 rate limit floor를 넘지 않도록 검증한다.
- `feature_update_requests` 목록 필터가 `providers`/`dataset_keys` 배열뿐 아니라
  `scope.type='provider_dataset'`의 `scope.provider`/`scope.dataset_key`도 찾도록 보정했다.
- admin frontend `/ops/providers`는 dataset row 선택, sync cursor/detail,
  최근 update request 상세 링크, `provider_dataset` request 생성, refresh policy 편집을
  한 화면에서 처리한다. `/admin/feature-update-requests/[request_id]` 상세 route도
  추가했다.

검증: provider/policy/update request router 단위 테스트 27 passed, Python ruff/mypy
targeted, frontend type-check/ESLint 통과.

**다음 한 작업**: **T-221e** — `/ops/logs`와 job event 연계, `/debug/explain`/
`/debug/fixtures` 필요성 재판정. 이후 T-222 공개 해수욕장/축제 뷰 API로 진행한다.

## 2026-06-12 Codex 작업 메모 — T-221c admin live signal channel

T-221c로 admin 실시간 signal 채널을 추가했다.

- `WS /v1/ops/live`를 추가했다. query `topics`와 client command
  `subscribe`/`unsubscribe`/`replace`/`ping`을 지원한다.
- 지원 topic은 `import_jobs`, `import_job:{job_id}`, `import_job_events:{job_id}`,
  `feature_update_requests`, `feature_update_request:{request_id}`, `offline_uploads`,
  `offline_upload:{upload_id}`, `dagster_runs`, `dagster_run:{run_id}`다.
- 구현은 DB trigger/NOTIFY 없이 시작하는 snapshot revision polling 방식이다. 서버는 변경된
  topic만 `snapshot`/`update` frame으로 보내고, frontend는 payload를 source of truth로
  저장하지 않고 TanStack Query invalidation signal로만 사용한다.
- admin frontend `src/api/live.ts`를 추가하고 `/ops/import-jobs`,
  `/ops/import-jobs/[job_id]`에 live badge와 query invalidation을 붙였다. 기존 query
  polling은 WebSocket이 막힌 환경의 fallback으로 유지한다.

검증: ops WebSocket router 단위 테스트 12 passed, Python ruff/mypy targeted,
frontend type-check/ESLint/React Doctor 통과.

**다음 한 작업**: **T-221d** — provider 상세/refresh policy 보강. `/ops/providers`
행 상세 추적, provider_dataset update request 상세 링크,
`provider_refresh_policies` 편집 UI.

## 2026-06-12 Codex 작업 메모 — T-221b import job 상세/event/cancel

T-221b로 import job 상세 흐름을 구현했다.

- `ops.import_job_events` 테이블을 추가했다. `job_id` FK + level/provider/job time
  인덱스를 두고, `jobs_repo` lifecycle 전이(queued/started/claimed/heartbeat/terminal/
  cancel)가 구조화 event를 기록한다.
- `GET /v1/ops/import-jobs/{job_id}/events`를 추가했다. `occurred_at DESC, event_id DESC`
  keyset cursor와 level filter를 지원한다.
- `POST /v1/ops/import-jobs/{job_id}/cancel`을 추가했다. queued/running job만
  best-effort `cancelled`로 전이하고, 이미 terminal이면 `409`를 반환한다.
- admin frontend `/ops/import-jobs/[jobId]`를 추가했다. job 상태/시각/payload,
  parent/batch/request/upload/Dagster 관련 링크, event timeline, cancel form을 한 화면에
  묶었다. `/ops/import-jobs` 목록의 job id는 상세 route로 이동한다.
- admin OpenAPI와 frontend generated type을 갱신했다. user OpenAPI 표면은 변하지 않는다.

검증: ops repo/router 단위 테스트 19 passed, jobs/ops repo 통합 테스트 17 passed,
Python ruff targeted, frontend type-check/ESLint, admin OpenAPI check 통과.

**다음 한 작업**: **T-221c** — admin 실시간 전송. `WS /v1/ops/live` 다중화 topic과
job/request/upload/run별 WebSocket 또는 SSE 대체 경로 설계·구현.

## 2026-06-12 Codex 작업 메모 — T-221a-2 수동 feature 작성 흐름

T-221a의 두 번째 조각으로 `/admin/features/new` 전용 수동 작성 화면을 추가했다.

- 지도 좌표 선택: MapLibre/VWorld fallback 지도에서 좌표를 선택하거나 중심 좌표를
  적용할 수 있다. 기존 `/features` 지도와 새 작성 화면 모두 MapLibre가 붙이는
  `maplibregl-map` CSS와 Tailwind `absolute` 충돌을 피하도록 inline sizing을 보정했다.
- kraddr-geo 연동: `NEXT_PUBLIC_KRADDR_GEO_BASE_URL` 기반 브라우저 helper를 추가해
  REST v2 `POST /v2/geocode`, `POST /v2/reverse` 후보를 주소/code 필드로 적용한다.
- 중복 후보: 좌표와 `radius_m`이 유효하면 기존 `/v1/features/nearby`로 active/
  inactive/hidden 후보를 보여주고, feature detail 링크로 바로 이동할 수 있다.
- kind별 detail form: `place`와 `event` 생성에 맞춘 구조화 필드와 extra JSON 병합
  지점을 제공하고, 최종 제출은 기존 `POST /v1/admin/features` change-request
  mutation만 호출한다.
- 진입점: `/admin/features`, `/admin/features/change-requests`에서 새 작성 화면으로
  이동할 수 있다.

검증: frontend type-check, ESLint, Vitest 15 passed, React Doctor no issues,
Next production build, in-app Browser DOM/canvas/좌표 상호작용 확인 통과.

**다음 한 작업**: **T-221b** — `/ops/import-jobs/[job_id]` 상세와
`ops.import_job_events` 스키마/API/event timeline/cancel 연결.

## 2026-06-12 Codex 작업 메모 — T-221a-1 feature detail route 1차

T-221a의 feature 상세 경로 1차를 구현했다. `/features/[featureId]`가 새 first-class
상세 화면이 되었고, inline 지도/admin 목록에서는 해당 상세 URL로 이동할 수 있다.

- 백엔드: `GET /v1/admin/features/{feature_id}`를 추가했다. `feature.features`
  core snapshot과 `source_records/source_links`, `data_integrity_violations`,
  `feature_overrides`, `feature_versions`, `feature_change_requests`, 선택적
  `feature_files` metadata를 한 응답으로 묶는다. `feature.feature_files` 테이블이 아직
  없는 DB head에서는 빈 배열을 반환한다.
- 프론트엔드: `FeatureDetailView` 공통 컴포넌트를 추가해 source raw payload, issue,
  override, history, files, nearby, weather를 한 화면에 묶었다. `/features` 지도 패널과
  `/admin/features` 목록/inspector에서 새 상세 경로로 링크한다.
- OpenAPI/admin frontend type을 재생성했다. user OpenAPI 표면은 변하지 않는다.

검증: admin feature router/repo 단위 테스트 20 passed, frontend type-check, ESLint,
ruff, mypy, OpenAPI drift check, openapi-typescript check 통과.

**다음 한 작업**: **T-221a-2** — `/admin/features/new` 전용 수동 작성 흐름. 지도 좌표
선택, kraddr-geo geocode/reverse, kind별 detail form, duplicate 후보 확인을
change-request 생성 앞단에 연결한다.

## 2026-06-12 claude 작업 메모 — T-220 재배선 (#395, MCST CSV 파일 다운로드)

`python-mcst-api` 재편(provider #6/#7/#9 — KCISA OpenAPI 폐기, CSV 파일 다운로드
주경로)에 맞춰 krtour MCST 배선 전체를 keyless `FileDataClient` 표면으로
재작성했다(이슈 #395). T-223b에서 중고서점 CSV를 추가해 적재 13 dataset
(`mcst_<slug>` 클린 컷, 방언 4종) + 제외
3 dataset(기사형/통계 — 사유 보존). asset은 `feature_place_mcst_culture` 1종으로
통합(도서관 계열 제거 — 디렉토리 경로 소멸, 후속 과제). 상세는
`docs/mcst-feature-etl.md` + `docs/journal.md` 최신 엔트리.

T-212e full reload 시 MCST 13 dataset의 실 fetch/적재 검증을 새 경로 기준으로
본다(구 `mcst_culture_records` 스키마와 다름 — CSV dict row). 다음 한 작업은
아래 T-224 메모 기준 그대로(T-221).

## 2026-06-12 Codex 작업 메모 — T-224 krtour-ai-agent provider clean cut

T-224를 완료했다. 기존 `tripmate-agent` identity는 `krtour-ai-agent`로 바뀌었고,
TripMate와의 직접 관계는 끊었다. YouTube/AI 후보 provider 관계는
**krtour-map ↔ krtour-ai-agent** 사이에만 둔다.

- ADR-053을 추가해 ADR-049/050의 provider 명칭·관계 설명을 supersede했다.
- canonical provider는 `krtour-ai-agent-youtube`, 변환 모듈은
  `krtour.map.providers.krtour_ai_agent`, raw payload key는
  `detail.payload.krtour_ai_agent`다.
- settings/env/Dagster resource/asset/schedule/test는 `krtour_ai_agent_*` /
  `KRTOUR_MAP_KRTOUR_AI_AGENT_*` 기준으로 clean cut했다. 구 `TRIPMATE_AGENT`
  env/provider alias는 두지 않는다.
- TripMate `curated_trip_plans` 생성 flow에는 `krtour-ai-agent`가 관여하지 않는다는
  경계를 `docs/integration-map.md`, `docs/curated-features.md`,
  `docs/tripmate-rest-api.md`에 반영했다.
- 사용자 신규 결정: 배포명 `kor-travel-map`, Python import root `kortravelmap`,
  권장 예시 `import kortravelmap as ktm`는 T-226 package identity rename task로 등록했다.

검증: targeted pytest 87 passed/1 skipped(`mois.db` 선택 의존성 부재), ruff, mypy,
import-linter, `git diff --check` 통과.

**다음 한 작업**: **T-221** — admin UI/UX 시나리오 연결성 + 실시간성 보강.
T-212e는 다른 agent가 병행 진행 중이며, 완료 결과는 T-225에서 한 번 더 대조한다.

## 2026-06-12 Codex 작업 메모 — T-221~T-223 순서 재정렬 + krtour-ai-agent 선행

사용자 지시로 `docs/tasks.md`/`docs/tasks-done.md`의 진행/완료 상태를 먼저 정리했다.

- 완료된 T-219(KMA weather Dagster)와 T-220(MCST provider 풀스택)은
  `docs/tasks-done.md`로 이동하고, 열린 작업 인덱스에서 제거했다.
- T-212e는 다른 agent가 병행 진행 중인 작업으로 열린 인덱스에 유지한다. 본 agent는
  T-224/T-221/T-222/T-223 진행 중 main rebase 충돌을 계속 확인한다.
- 사용자 결정 반영: `tripmate-agent`는 `krtour-ai-agent`로 이름을 바꾸고 TripMate와의
  직접 관계를 끊는다. TripMate의 `curated_trip_plans` 생성에는 `krtour-ai-agent`가
  관여하지 않으며, AI 후보 provider 관계는 krtour-map ↔ krtour-ai-agent 사이에만 둔다.
- 새 선행 작업 T-224를 추가했다. T-221 진입 전 `krtour-ai-agent` provider 경계/명명/
  상세 구현을 마감한다.
- T-221 → T-222 → T-223 순서 뒤에는 T-225로 T-212e closure 재검증을 한 번 더 둔다.
- 사용자 결정 반영: 배포명은 `kor-travel-map`, Python import root는 `kortravelmap`,
  권장 예시는 `import kortravelmap as ktm`로 바꿀 예정이다. 구현 범위가 커서 T-226
  별도 clean cut task로 등록했다.

**다음 한 작업**: **T-224** — `krtour-ai-agent` provider 경계 재정의 + 상세 구현.
T-212e는 병행 진행 중이며, 완료 결과는 T-225 closure 재검증에서 다시 대조한다.
T-226은 package identity rename 전용 후속 작업이다.

## 2026-06-12 Codex 작업 메모 — local/Docker 포트 재고정

사용자 지시로 local/Docker 포트 기준을 새 고정값으로 정렬했다.

- Postgres host port: `5432`
- RustFS S3 API: `12101`(console host `12105` 유지)
- kraddr-geo: API `12201`, Web UI `12205`
- krtour-map: API `12301`, 관리 보조(Dagster) `12302`, Web UI `12305`
- krtour-ai-agent: API `12401`
- 반영 범위: `.env.example`, `scripts/load-env.sh`, `docker-compose.yml`, Dockerfile expose,
  `AdminSettings`, main settings, frontend fallback/Playwright 설정, 테스트 기대값, ADR-047과
  운영 문서/runbook.
- 공유 `tripmate-manager` 인프라를 재사용하는 `docker-compose.external-infra.yml` overlay와
  `KRTOUR_MAP_INFRA_EXTERNAL=true` 경로를 추가했다.
- 순수 `git`을 제외한 작업은 WSL에서 실행하고, Playwright e2e만 Windows 호스트에서
  수행하도록 개발 환경/runbook 문서를 보강했다.
- `/admin/issues` Playwright e2e는 issue 0건 빈 행을 정상 empty state로 처리하도록
  보정했다.

**다음 한 작업**: 기존 우선순위인 **T-212e**는 그대로 유지. 병렬/후속 후보는
**T-223b~d**, **T-221a~c**, **T-222b**.

## 2026-06-12 Codex 작업 메모 — curated_features 문서 계약 + TripMate 명명 정리

사용자 지시로 테마형 데이터 소스와 TripMate curated plan import 방향을 문서화했다. 코드 변경은
없고 DB/API/Admin UI/Dagster 구현 전 계약만 정리했다.

- 새 정본 후보 `docs/curated-features.md`를 추가했다. 기존 MCST 16종 중 세계음식점,
  독립서점, 카페가 있는 서점, 도서관 계열을 1차 curated 후보로 두고, 중고서점·아동서점·
  서울 책방·무슬림 친화 음식점·안산 세계맛집·제주 향토음식점·전국지역특화거리표준데이터를
  provider 보강 후보로 분리했다.
- `curated_features`는 `feature.features`를 복제하지 않는 `feature.curated_*` overlay로
  관리한다. 테마명, 데이터 소스 URL, 수정일, 갱신주기, row_count, freshness note 같은
  source metadata를 공용으로 뽑을 수 있게 설계했다.
- TripMate 정본명은 `app.curated_trip_plans` / `app.curated_plan_pois`다.
  `notice_plans`는 TripMate 호환 API alias일 뿐 신규 DB/ORM/문서 정본으로 쓰지 않는다.
- TripMate는 krtour-map REST `GET /v1/curated-features*` 후보 표면을 호출해
  `curated_features` 1건을 `curated_trip_plans` 1건으로 복사한다. DB 직접 접근은 없다.
- 백로그 T-223을 추가했다. T-223a(문서 계약)는 완료, provider 보강/DB·API·Dagster·Admin UI/
  TripMate import 구현은 열린 후속으로 남겼다.

**다음 한 작업**: 기존 우선순위인 **T-212e**는 그대로 유지. 병렬/후속 후보는
**T-223b~d**(provider 보강 → krtour 구현 → TripMate import)와 **T-221a~c** /
**T-222b**.

## 2026-06-11 Codex 작업 메모 — admin UI/UX 시나리오 재점검 + T-130 공개 뷰 사양

사용자 지시로 admin UI/UX 계획 문서와 실제 프론트엔드/백엔드/OpenAPI, TripMate T-130
문서를 다시 대조했다. 코드 변경은 없고 문서/백로그 보강만 수행했다.

- 실제 admin 프론트엔드는 17개 경로가 구현되어 있고 T-218 이후 a11y/e2e 기본 커버는 충분하다.
  남은 간극은 목록 화면 추가보다 `/features/[feature_id]` 상세, 수동 feature 작성 흐름,
  import job 상세/event 타임라인, provider 상세/policy, job/log 실시간 스트림 같은 **연결부**다.
- 현재 실시간성은 2초/10초 폴링 중심이다. T-212e 전체 재적재, offline upload 적재,
  feature update request run-now, Dagster 실패 상세 추적은 `ops.import_job_events`와
  `WS /v1/ops/live` + job/request/upload/run별 WebSocket 또는 SSE 대체 경로가 필요하다.
- TripMate T-130(`/public/*`) 차단 원인은 krtour-map 사용자 OpenAPI에 해수욕장/축제
  전용 뷰와 닫힌 detail 스키마가 없다는 점이다. 제안 사양
  `docs/public-views-api.md`를 추가했다.
- 해수욕장 category drift 확인: 문서 정본은 `01050100`, 현재 provider 코드는
  `01020300 + detail.place_kind="beach"`다. T-222 구현 전에 정리해야 한다.
- 백로그: T-221(admin UI 연결/실시간), T-222(TripMate T-130 공개 뷰)를 추가했다.

**다음 한 작업**: 기존 우선순위인 **T-212e**는 그대로 유지. 병렬/후속 후보는
**T-221a~c**(feature 상세·job 상세·실시간 전송)와 **T-222b**(공개 뷰 OpenAPI 구현).

## 2026-06-11 claude 작업 메모 — T-219/T-220 완결 (KMA Dagster + MCST 신규 provider)

사용자 지시 "kma, mcst provider 빠짐없이 상세구현(Dagster 포함)"을 PR 6개로 종결
(T-219a #356 / T-219b #360 / T-219c #361 / T-220a #363 / T-220b #364 / T-220c).

- **KMA**: Dagster asset 5종 완비 — 실황/초단기/단기(옵션 B 대상 한정 — poi
  target+extra 좌표 격자, run당 상한) + 중기(설정 주입 region 매핑) + 특보
  (record resource→notice, region명=raw_address 위치 단서). cursor
  `base_datetime` skip / 실패 시 미전진. `python-kma-api@ab1a0b8` 핀.
- **MCST**: 신규 provider 풀스택 — slug 메타표 16종(KCISA 14 + 도서관 2, 전부
  기존 category), `(slug, record)` 튜플 스트림 → slug별 분리 적재 asset 2종,
  ETL preview fixture, `docs/mcst-feature-etl.md`. `python-mcst-api@d06e8d2` 핀.
  dedup pair는 실데이터 확인 후 등록 검토.

**다음 한 작업**: **T-212e** — 실데이터 full reload + offline upload 실데이터
검증 + 최종 리포트(백로그 인덱스에 남은 유일한 열린 항목). KMA/MCST 신규
asset의 실 fetch 검증도 T-212e 범위에서 함께 본다(credential/스키마 drift).

## 2026-06-10 Codex 작업 메모 — T-212d read-heavy 재측정

PR #332 머지 후 `origin/main`에서 새 브랜치를 만들고 T-212d를 다시 실행했다. 기존
seeded PostGIS baseline은 유지하면서 read-heavy 전제의 누락 hot path를 보강했다.

- `tests/integration/test_t212d_perf_explain.py`에 bbox 클러스터(`sido`/`sigungu`/
  `eupmyeondong`) EXPLAIN 회귀를 추가했다. 현재 exact-viewport 클러스터 쿼리는
  `idx_features_coord_gist`를 사용하고, 대표 `sigungu` 경로는 seqscan hint 없이도
  base table `Seq Scan`을 피한다.
- `mv_feature_cluster_counts`는 이번 PR에서 도입하지 않았다. 후보 MV는 region-total
  count/centroid 의미라 현재 API의 exact-viewport count/avg(coord)와 달라진다.
  실제 row 수/P99가 나오는 T-212e 이후 별도 ADR/PR에서 판단한다.
- enrichment review 목록은 단일 `status + provider` 필터일 때 scalar equality fast path를
  사용해 `idx_enrichment_review_provider_status_score`를 안정적으로 타게 했다. 후보 CTE 안에
  `LIMIT`을 넣어 feature join 전에 page 크기로 줄였다.
- 검증: ext4 mirror에서 `compileall` + `pytest -s tests/integration/test_t212d_perf_explain.py -q`
  통과(`6 passed`). 상세 리포트는
  `docs/reports/t-212d-read-heavy-rerun-2026-06-10.md`.

**다음 한 작업 후보**: **T-212e** — 실데이터 full reload + offline upload 실데이터 검증 +
최종 리포트. 여기서 live row 수/P99를 확보한 뒤 클러스터 MV ADR 여부를 다시 판단한다.

## 2026-06-10 Codex 작업 메모 — T-216f/g + 재적재 충돌 + TripMate-agent provider

T-216f/g를 한 PR 범위로 닫았다. REST 표면에서 이미 정리한 surrogate/lifecycle 명명을
DB/ORM/repo/API/OpenAPI/frontend type까지 전파했다.

- `review_key` 계열은 `review_id`, `violation_key`는 `issue_id`, ops 로그/override/step
  내부 surrogate는 `*_id`로 정리했다. 자연키/복합키(`cluster_key`, `target_key`,
  `dataset_key`, `source_record_key`, `feature_id`)는 유지했다.
- `ops.import_jobs`, `ops.offline_uploads`, `ops.feature_update_requests`의 lifecycle 컬럼은
  `state`에서 `status`로 수렴했다. Alembic `0023_t216f_rest_names`가 rename과
  인덱스/constraint 재생성을 담당한다.
- `openapi.json`과 frontend `src/api/types.ts`를 재생성했고, `docs/rest-api.md`를 전 표면
  단일 계약 정본으로, `docs/tripmate-rest-api.md`를 TripMate 소비 매핑 view로 유지했다.
- `origin/main`의 재적재 안전성 리포트(#330)와 MV 재검토(#331)를 최신 base로 반영했다.
- 재적재 안전성 F-2/F-1도 이어서 해결했다. 사용자 변경은 `feature_versions.MAX(version)+1`
  단조 row로 보존하고, dedup merge loser는 status override로 provider 재적재 부활을 차단한다.
- TripMate-agent 후속은 krtour-map 쪽 `tripmate-agent-youtube` provider로 구현했다.
  `providers.tripmate_agent` 순수 변환, Dagster REST fetch/resource/asset/schedule,
  canonical provider/ADR-049와 문서 반영까지 완료했다. 실제 TripMate-agent export API는
  해당 repo `T-066` 구현 후 live smoke 가능하다.
- 다음 작업으로 넘어가기 전에 문서 정합성 sweep을 다시 수행해 README/SKILL/architecture/
  decisions/tasks/provider-contract/external-apis/Dagster 문서의 provider·MV·다음 작업
  상태를 맞췄다.

**후속 반영**: T-212d 재측정 pass는 위 2026-06-10 Codex 메모에서 완료했다. 현 기준
다음 한 작업은 T-212e live full reload다.

## 2026-06-10 claude 작업 메모 — 데이터 재적재 안전성 검증

재적재 충돌·결측·엎어쓰기 검증 → `docs/reports/data-reload-safety-2026-06-10.md`. 기본 안전망
OK(v0/v1 가드·soft-delete·advisory lock). 보강 2건: T-215d(버전 단조화 v0,v1,v2,v3+디폴트=최신,
F-2), T-104(dedup merge 영속화, F-1).

## 2026-06-09 Codex 작업 메모 — T-216a~e REST 계약 표면 정리

T-216의 표면 계약 묶음(a~e)을 한 PR 범위로 구현했다. admin/ops/debug까지 `/v1`
mount로 clean cut하고, 성공 envelope를 공유 `Meta`(`request_id`, `meta.page`,
`meta.cluster`)로 통일했다. `limit` 계열은 `page_size`로, 상태 query/body 표면은
`status`로, 이슈/리뷰 surrogate 식별자는 `issue_id`/`review_id`로 맞췄다. 에러는
`application/problem+json` top-level `code`/`request_id`/`errors` 확장으로 정리했다.
OpenAPI(admin/user)와 frontend generated type, API hook, 화면 route, Playwright mock을
같이 갱신했다.

**다음 한 작업 후보**: **T-216f** 물리 DB/ORM/repo surrogate 명명 전파
(`review_id`→`review_id`, `issue_id`→`issue_id`, `state`→`status`)를 테이블별
migration 포함 별도 PR로 진행한다. T-216g 문서/버전 거버넌스 잔여도 그 뒤 정리한다.

## 2026-06-09 claude 작업 메모 — T-210 정리

T-210a 닫기(ADR-048/문서 재정비로 흡수), b/c/d는 TripMate repo 외부 태그, e만 본 저장소
actionable(T-212e 후). 인덱스 설명 누락 defect 수정.

## 2026-06-09 Codex 작업 메모 — T-215c feature change e2e workflow

T-215b에서 만든 `/admin/features/change-requests` 화면의 workflow e2e를 보강했다.

- OpenAPI generated schema 타입에 묶인 feature change route mock을 추가했다.
- `require_review`: pending row 선택 → approve → applied 표시와 approve button 제거를 검증한다.
- `immediate`: create form 제출 후 즉시 applied row가 보이는지 검증한다.
- update/delete 요청 생성, delete approve 이후 soft delete 완료 표시, action delete 필터를 검증한다.
- Next RSC prefetch(`/admin/features?_rsc=...`)는 backend mock에서 제외했다.

**다음 한 작업 후보**: **T-216a** admin/ops/debug `/v1` clean cut.

## 2026-06-09 claude 작업 메모 — T-102 pg_prewarm warm-up (mechanism)

보류 항목이지만 메커니즘 구현: migration 0022 + infra/prewarm.py + docker autoprewarm +
health-deep prewarm. 효과는 P99 SLO+shared_buffers fit 조건 충족 시. 인덱스 18건.

## 2026-06-09 claude 작업 메모 — T-017(maki drift) + T-018(KNPS) 완료

T-017: map-marker-react 패키지는 추출돼 있었고 drift gate 테스트만 누락 → 추가(+maki 46종
글리프 보강). T-018: KNPS provider/dagster는 PR#77/#78 구현 완료 → close. 인덱스 19건.

## 2026-06-09 claude 작업 메모 — T-RV-53/54 close-out

krforest·standard_data provider 풀스택은 sub-task a~d 머지 완료(2026-06-07). 부모 [x] 처리
(회귀 green). 실데이터 fetch는 T-212e.

## 2026-06-09 Codex 작업 메모 — T-215b feature change queue UI

T-215a의 `/admin/features/change-requests*` API를 admin UI에 연결했다. 새 REST 표면은 만들지
않고 기존 정본 endpoint만 사용한다.

- `/admin/features/change-requests`: 요청 목록, 상태/action/q/limit 필터, payload 상세, approve/reject.
- 같은 화면에서 add/update/delete 요청 form을 제공한다. `DELETE /admin/features/{feature_id}`는
  JSON body가 필요해 frontend `deleteJson`이 optional body를 받을 수 있게 확장했다.
- `GET /admin/features/change-requests` meta에 `review_mode`를 추가해
  `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE`를 빈 큐에서도 표시한다.
- OpenAPI와 frontend generated type을 재생성했다.

**다음 한 작업 후보**: **T-215c** feature change e2e workflow 보강(typed route mock,
pending→approve→applied, immediate mode, soft delete 표시/필터), 또는 T-216a admin/ops/debug
`/v1` mount.

## 2026-06-09 claude 작업 메모 — T-214 tail 완료 (e/f/g/h)

T-214e(search bbox 4-float·page_size) + T-214f(POI write=admin only 결정) + T-214g(헤더/에러
규약 표) + T-214h(`/debug/health|version` 제거 + frontend repoint) 한 PR. gates green.
**→ Phase 6.6(T-214) 전부 완료.** 남은 REST 정합성 심화는 Phase 6.8(T-216a~g).

**다음 한 작업 후보**: (1) **T-216a** admin/ops/debug `/v1` mount, (2) T-215b/c feature change
UI/e2e, (3) T-212e 실데이터 reload.

## 2026-06-09 claude 작업 메모 — tasks.md 분리(진행/완료)

tasks.md(1567줄)를 **진행/예정 = `tasks.md`(상단 열린항목 인덱스) + 완료·아카이브 =
`tasks-done.md`**로 분리. entry 문서(CLAUDE/AGENTS/SKILL/agent-guide/README) 포인터 갱신.

## 2026-06-09 claude 작업 메모 — T-214b 완료 (사용자/서비스 `/v1` prefix)

`features`/`categories`/`providers` → `/v1` clean cut. 백엔드(include prefix)+USER_OPERATIONS+
OpenAPI+frontend 호출부/타입+e2e+테스트 갱신, gates green(next build의 /admin/dagster
prerender 실패는 기존 Windows 로컬 이슈, CI Linux 통과). PR→머지.

**다음 한 작업 후보**: (1) **T-214d**(이미 완료) 외 **T-216a** admin/ops/debug `/v1` mount,
(2) T-215b/c 사용자 feature change UI/e2e, (3) T-212e 실데이터 reload.

## 2026-06-09 claude 작업 메모 — `/tripmate/*` namespace 제거 (T-214d 완료)

사용자 지시로 `/tripmate/` endpoint 제거: `POST /tripmate/features/batch` →
`POST /features/batch`(service read, ServiceToken route-level 유지). 코드+OpenAPI+frontend+
테스트+모든 live 문서 갱신, gates green. PR→머지 진행.

## 2026-06-09 claude 작업 메모 — ADR-048(REST versioning admin/ops 확장 + 정합성 표준)

#317(T-214/T-215)의 `/v1` 1차 위에 사용자 지시(admin도 versioning + 정합성 심화)를 반영.
PR #316을 #317 머지본 위로 재작성했다(문서 전용).

- **ADR-048** + **`docs/rest-api.md`**(전 표면 단일 계약 정본). `docs/tripmate-rest-api.md`는
  TripMate 소비 매핑 view로 축소했다.
- 실행 **Phase 6.8 / T-216a~g**(admin `/v1` mount → pagination 단일화 → envelope 공유모델 →
  parameter/error → 명명 → 코드/DB 전파).
- PR #316 3차/4차 리뷰 반영: batch 응답 `data.found`, in-bounds `meta.cluster.cluster_unit`,
  base URL host-root/path `/v1` 분리, `cluster_key` 자연키 유지, `feature_id` 값 불변식.

**다음 한 작업 후보**: (1) **T-216a** admin/ops `/v1` mount, 또는 (2) #317 후속 **T-215b/c**
(admin UI feature change queue + frontend types/e2e), 또는 (3) T-212e 실데이터 reload.

## 2026-06-08 Codex 작업 메모 — REST API v1 계약 정리

`docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate repo
`docs/integrations/krtour-map-rest-api.md`를 대조해 krtour-map REST API 정본 문서를
재작성했다. 핵심 결정은 사용자 지시대로 **`/tripmate/feature-update-requests*`를
admin 영역으로 이동**하는 것이고, 이어서 place/event feature 사용자 요청
추가·수정·삭제 API를 admin 영역에 구현했다.

- `docs/tripmate-rest-api.md`: 목표 `/v1` 사용자/서비스 계약, envelope/error/parameter 규약,
  endpoint naming, 중복 제거, 누락 API, 현재 구현 gap을 한 문서로 정리했다.
- `docs/openapi-admin-contract.md`/`docs/tripmate-integration.md`/
  `docs/poi-cache-update-targets.md`/`docs/architecture.md`: feature update request는
  `/admin/feature-update-requests*`만 정본이고, TripMate 사용자 제안 큐는 TripMate app DB가
  소유한다고 정리했다.
- 코드: `/tripmate/feature-update-requests*` alias를 제거하고
  `/admin/feature-update-requests*`만 남겼다. `/admin/features`에 `POST`,
  `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다.
- DB: provider 적재는 version 0, 사용자 요청 추가·수정·삭제는 version 1로 보존하도록
  `feature.features` metadata, `feature.feature_versions`,
  `ops.feature_change_requests`를 추가했다. provider 재적재는 사용자 version 1 effective
  row를 덮지 않고, 사용자 요청 soft delete는 되살리지 않는다.
- `docs/tasks.md`: REST API 정리 후속 `T-214a~h`와 feature CRUD 후속 `T-215a~c`를
  정리했다. `T-214a`, `T-214c`, `T-215a`는 완료했고, 남은 큰 후속은 `/v1` prefix와
  admin UI feature change queue 화면이다.

**다음 한 작업 후보**: **T-214b REST API `/v1` prefix 도입** 또는 **T-215b admin UI feature change queue 화면**.

## 2026-06-08 Codex 작업 메모 — T-212d 사후 리뷰 반영

PR #313 머지 후 달린 사후 상세리뷰를 확인하고 T-212d 후속 보강을 진행했다. GitHub
review thread는 없었지만 PR issue comment에 조치 가능한 리뷰가 있어 이를 기준으로 반영했다.

- `/features/in-bounds`: 공간 후보 CTE는 유지하되 `LIMIT` subset 안정성을 위해 후보 materialize
  뒤 `feature_id ASC` 정렬을 복구했다.
- T-212d EXPLAIN 테스트: 기존 `enable_seqscan=off` 인덱스 적격성 검증에 더해 대표 bbox/admin
  sort=name 경로는 seqscan hint 없이 planner가 base table `Seq Scan`을 고르지 않는지 확인한다.
- `/admin/features sort=name`은 `idx_features_lower_name_keyset` 사용을 별도 검증한다.
- dedup/enrichment review cursor는 끝까지 순회해 전체 정렬셋과 1:1로 맞는지 검증한다.
- 리포트/성능 문서에 `feature_files` 임시 DDL, 일반 index DDL 잠금 유의 사항,
  `idx_import_jobs_state` 대량화 재검토 포인트를 명시했다.

**다음 한 작업 후보**: **T-212e 실데이터 full reload + offline upload 실데이터 검증 + 최종 리포트**.

## 2026-06-08 Codex 작업 메모 — T-212d seeded PostGIS 성능 baseline 완료

사용자 지시대로 main을 다시 동기화한 뒤 T-212d 성능 baseline/tuning을 진행했다. 로컬 live
Postgres(`python-krtour-map-codex-postgres-1`)는 `features/source_records/source_links/import_jobs`
각 1건, `consistency_reports`/`dedup_review_queue` 0건, alembic `0016` 상태라 성능 기준으로
쓰기에는 부족했다. 대신 CI에서 재현 가능한 3,200 feature 규모 seeded PostGIS/testcontainers
baseline을 만들고 EXPLAIN 인덱스 사용을 고정했다.

- DB schema: `0020_t212d_perf_keyset_indexes` 추가. `feature.features` updated/status/name/opening_hours,
  `ops.import_jobs`, consistency report/violation, dedup/enrichment review queue keyset 인덱스를
  보강했다.
- Query: `/features/in-bounds`는 공간 후보 CTE로 GiST 사용을 고정하고, q 검색은 trigram 후보
  CTE를 분리해 `idx_features_name_trgm`을 먼저 탄다. dedup/enrichment review와 F7 consistency는
  UUID `review_id` tie-breaker로 keyset cursor를 정렬한다.
- Test: `tests/integration/test_t212d_perf_explain.py`가 `/features/search`, `/features/in-bounds`,
  `/features/nearby`, `/admin/features`, `/ops/import-jobs`, consistency F4/F6/F7/F8, dedup refresh,
  dedup/enrichment review list EXPLAIN을 live-like seed로 검증한다.
- 검증: T-212d 전용 ruff + EXPLAIN 통합 4, 관련 통합 45, 관련 단위 44 통과.

**현재 상태**: T-212d 완료. 남은 큰 축은 T-212e 실데이터 full reload 최종 검증, T-210 TripMate
연계 정리, Sprint 5 closure다.

**다음 한 작업 후보**: **T-212e 실데이터 full reload + offline upload 실데이터 검증 + 최종 리포트**.

## 2026-06-08 Codex 작업 메모 — T-212b admin UI 완결성 완료

PR#291(Dagster tick/run failure 드릴다운)과 PR#277(admin feature/issues/logs 화면)을 최신
main에 머지한 뒤, T-212b 마지막 잔여였던 **offline upload/POI cache target 주요 mutation e2e**를
별도 PR 범위로 닫았다.

- `/admin/poi-cache-targets`: Playwright route mock으로 target upsert(`PUT`) → 목록 반영 →
  target 선택 → `/features/nearby/by-target` 조회 → target delete(`DELETE`)까지 운영자 흐름을
  검증한다.
- `/admin/offline-uploads`: CSV multipart upload(`POST`) → preview 조회 → validation
  실행(`POST /validate`) → 상태 필터 전환 → Dagster load 실행(`POST /load`) alert까지 검증한다.
- backend DB/RustFS/Dagster 실스택 검증은 T-212e live full reload에서 수행하고, 이번 e2e는
  브라우저 상호작용과 API 계약 요청/응답 shape를 고정하는 범위다.

**현재 상태**: T-212b 완료. 남은 큰 축은 T-212d seeded PostGIS perf baseline, T-212e 실데이터
full reload 최종 검증, T-210 TripMate 연계 정리, Sprint 5 closure다.

**다음 한 작업 후보**: 실데이터 없이 바로 가능한 **T-212d seeded PostGIS perf baseline**.

## 2026-06-08 Claude 작업 메모 — T-RV-04b 완전 종료 (opinet 3/3 POI-타깃 완료)

opinet wiring 3 PR 전부 머지(또는 머지 대기): opinet-1 ADR-044 재정렬(#302) · opinet-2 bbox(#303)
· opinet-3 POI-타깃(머지 대기). `fetch_opinet_stations`가 settings.opinet_scope_mode로 bbox /
poi_cache_target(DSN sync DB 조회로 opinet POI target→bbox) 둘 다 지원.

**→ T-RV-04b 완전 종료**: provider 8종 live wiring 완료. T-RV-04b 및 후속 program(T-RV-50~55)
전부 종결.

**다음 한 작업**: T-RV-04b 관련 남은 항목 없음. 새 지시 대기. (별도 트랙: T-212d perf baseline,
T-212e 실데이터 full reload 최종 검증 — `docs/tasks.md` Phase 6/7.)

## 2026-06-08 Claude 작업 메모 — T-RV-04b opinet wiring 2/3 (bbox) 완료

T-RV-04b 본체 마지막 1건(opinet) 진행 중. 사용자 결정 = bbox + POI-타깃 둘 다 지원, 3 PR:
- [x] opinet-1 ADR-044 Protocol 재정렬(#302 merged) — `Station` 필드명 정렬.
- [x] opinet-2 bbox fetcher(머지 대기) — settings `opinet_scope_*` + `fetch_opinet_stations`
  (bbox enumerate + uni_id dedup) + resource guard→live.
- [ ] opinet-3 POI-타깃 모드.

**다음 한 작업**: **T-RV-04b opinet-3** — `fetch_opinet_stations`의 `poi_cache_target` 분기 구현.
설정 DSN(`pg_dsn`)으로 **동기** DB 연결을 열어 `ops.poi_cache_targets`에서 `external_system=
'opinet'` 활성 target(lon/lat/radius_km) 조회 → 각 center±radius를 bbox로 변환 → 기존
`_enumerate_opinet_stations`로 enumerate(uni_id dedup). 단위 테스트(fake target + fake opinet).
완료 시 **T-RV-04b 완전 종료**. (POI 인프라: `infra/scope_repo.py`/`PoiCacheTargetRow`.)

## 2026-06-08 Claude 작업 메모 — T-RV-04b 후속 program 전체 완료

T-RV-55d-2(airkorea orchestration)까지 완료·머지하며 **T-RV-04b 후속 program(T-RV-50~55) 전체
종료**. 이번 세션에서 머지한 PR: #296(55e krairport) · #297/#298/#299(52c enrichment review
backend/API/frontend) · #300(55d-1 airkorea provider) · 55d-2(airkorea orchestration).

**완료 상태 요약**:
- 50 maplibre 최신화 · 51 dedup 수동 UI · 52 visitkorea 축제 enrichment(provider+wiring+review UI)
- 53 krforest · 54 박물관/미술관 · 55a~e place 보조 dataset 5종 · 55d 대기질(weather value)
- 모든 데이터소스 MOIS dedup(후보 있는 source만) + 자동 매칭 실패분 수동 처리 UI(dedup-reviews,
  enrichment-reviews) 구현.

**다음 한 작업**: T-RV-04b 후속 program에 남은 항목 없음. 새 지시 대기. (참고: 실데이터 full
reload 최종 검증은 T-212e, perf baseline은 T-212d로 별도 트랙 — `docs/tasks.md` Phase 6/7.)

## 2026-06-08 Claude 작업 메모 — T-RV-55d-1 airkorea 대기질 provider 완료

사용자 결정(대기질 지금 구현, 측정소=weather feature)에 따라 마지막 남은 항목 T-RV-55d 착수.
2 PR 중 1번째(provider) 완료·머지 대기.

- `providers/airkorea.py`: `air_quality_stations_to_bundles`(측정소→weather-kind FeatureBundle,
  category 99000000) + `air_quality_to_weather_values`(측정 row→오염물질별 WeatherValue,
  domain=air_quality/style=observed). 기존 WeatherValue 패턴(`feature.feature_weather_values`,
  weather_repo) 재사용 — 신규 테이블 없음. unit+lint 965/coverage 81% green.

**다음 한 작업**: **T-RV-55d-2 orchestration** — client `load_air_quality`(① station bundle을
`load_feature_bundles`로 적재 → ② station_name→feature_id 매핑 → ③ `air_quality_to_weather_values`
→ `load_weather_values`) + dagster fetcher(`AirKoreaClient.stations()`+`sido_measurements`/
`station_measurements`)/asset/resource/definitions + ETL preview + 테스트. 완료 시 T-RV-04b 후속
program(T-RV-50~55) 전체 종료.

## 2026-06-08 Claude 작업 메모 — T-RV-52c-1 enrichment 검토 큐 backend 완료

축제 enrichment(visitkorea 2차 ↔ datagokr 1차) 수동 검토를 dedup-reviews처럼 만드는 작업
(T-RV-52c)을 3 PR로 분해해 **1번째(backend 도메인/infra)를 완료·머지 대기**.

- 점수 밴드 분류(`festival_to_review_candidates`: auto ≥0.90 / review [0.70,0.90) / drop) +
  `ops.enrichment_review_queue`(migration 0019) + `infra/enrichment_review_repo.py`(enqueue/
  pending/decide, accept→ENRICHMENT link) + client 3메서드(`refresh_festival_enrichment_reviews`/
  `list_pending_enrichment_reviews`/`resolve_enrichment_review`). 게이트 전수 green(unit+lint 959
  coverage 81%, integration 13건).

52c-2 admin API + 52c-3 frontend 모두 완료·머지 → **T-RV-52(visitkorea 축제 enrichment) 전체
완료**. frontend = `admin/enrichment-reviews` 페이지(accept/reject/ignore) + `src/api/enrichment.ts`
훅 + nav + e2e smoke. gen:types:check/tsc/next build/eslint green.

**현재 상태**: T-RV-04b 후속 program(T-RV-50~55)에서 place dataset 5종(55a~e) + enrichment review
UI(52) + dedup 수동 UI(51) + maplibre 최신화(50) + krforest(53)/박물관미술관(54) 전부 완료.

**다음 한 작업(유일하게 남은 항목)**: **T-RV-55d airkorea 대기질** — place feature가 아니라
측정값(weather-like)이라 feature-load 4-step과 다름. **설계 결정 선행 필요**(WeatherValue 패턴 vs
별도 측정 DTO vs 본 스코프 제외) → 사용자 결정 대기. 결정 전까지 T-RV 후속 program은 사실상 완료.

**병행 대기**: **T-RV-55d airkorea 대기질**은 place feature가 아니라(측정값) **설계 결정 선행**
필요 — 사용자 결정 대기(WeatherValue 패턴 vs 별도 DTO vs 제외).

## 2026-06-08 Claude 작업 메모 — T-RV-55 place 보조 dataset 5종 완료(55a~55e)

T-RV-55 ADR-034 보조 dataset 중 **place feature 5종 전부 풀스택 완료**:
55a 관광지 · 55b 주차장 · 55c khoa 해수욕장 · 55e krairport 공항(keyless, 신규 모듈).
각 = transform + asset/fetcher/resource/definitions + ETL preview + 단위/dagster 테스트 +
게이트 전수(coverage 81%). MOIS dedup은 PROMOTED 슬러그에 후보가 있는 source만 추가했고
(tourist↔mois) 해수욕장/공항/주차장은 후보 없음.

**남은 작업(우선순위順)**:
1. **T-RV-55d airkorea 대기질** — **place feature가 아님**(측정값, weather-like). feature-load
   4-step과 근본적으로 다름 → **설계 결정 선행 필요**: (a) WeatherValue류 별도 value 패턴,
   (b) 별도 측정 DTO, (c) 본 스코프에서 제외. **사용자 결정 대기**(의사결정 사항).
2. **T-RV-52c** visitkorea↔datagokr 축제 enrichment **매칭 review UI**(dedup-reviews와 유사한
   신규 API+UI surface) — enrichment wiring(52a/52b)은 완료, 수동 review UI만 trailing.

**다음 한 작업**: 위 1(55d) 설계 결정을 사용자에게 surface → 결정 후 진행. 그 전까지는 2(52c)
enrichment review UI를 진행 가능.
## 2026-06-07 Codex 작업 메모 — T-212b Dagster 드릴다운

T-212b-3의 Dagster monitoring 일부를 닫았다. backend `GET /ops/dagster/summary`는
schedule/sensor 최근 tick을 포함하고, 신규 `GET /ops/dagster/runs/{run_id}`는 run summary,
event log, failure/PythonError payload를 `{data, meta}` envelope로 반환한다. frontend
`/admin/dagster`는 recent run row 또는 tick run id 선택 시 `Run detail` panel에서 event/failure를
조회한다. Dagster GraphQL이 500이어도 summary는 `unavailable` alert와 empty state로 유지된다.

검증: admin Dagster router unit 8, ruff, mypy(라우터), OpenAPI all drift check, frontend
generated type check/type-check/lint/build, React Doctor(exit 0, 기존 optional warning만), Windows
Playwright `/admin/dagster` smoke 1 passed.

**다음 한 작업 후보**: T-212b-3 잔여인 offline upload/POI cache target 주요 mutation e2e,
또는 T-212d seeded PostGIS perf baseline. 다른 T-RV-52 계열은 최신 `origin/main`에 이미
진행분이 있으므로 새 브랜치 시작 전 반드시 fetch/rebase 상태를 확인한다.

## 2026-06-07 Claude 작업 메모 — T-RV-50 시리즈 착수 (T-RV-04b 완전 마무리 + 후속 프로그램)

사용자 지시(T-RV-04b 및 후속 관련 모든 task 완료까지 진행)에 따라 `docs/tasks.md`에
**T-RV-50 시리즈** 프로그램을 구체화했다(7개 요구사항 → PR 단위 분해). provider 라이브러리
surface 전수 조사 완료. 미구현 데이터소스 = **휴양림/수목원(krforest, 모듈 없음)** · **박물관/미술관
(standard_data festival만)** · **visitkorea 축제 enrichment(모듈 있음, 미wiring)**. dedup 인프라는
성숙(scoring/queue/admin router+page)하나 **merge master 선택 UI 미완 + 기본 scope 미설정**.

**프로그램(tasks.md T-RV-50~55)**:
- T-RV-50 maplibre-vworld-js 최신화(point 6) — frontend는 최신 태그 v0.1.3 핀, main untagged
  후속 커밋 확인 필요(기능 변경 시 신규 태그 릴리스).
- T-RV-51 dedup 수동처리 UI 완성 + 기본 scope(point 4 기반).
- T-RV-52 visitkorea 축제 enrichment(points 1·5·5.1, provider+krtour+UI; provider TourItem에
  eventstart/end date promote 보강 필요).
- T-RV-53 krforest 휴양림/수목원(points 1·2·3·4; `ForestClient.travel.standard_recreation_forests`,
  READY).
- T-RV-54 standard_data 박물관/미술관(points 1·3·4; `datagokr.museum_art.iter_all`, READY).
- T-RV-55 point-7 후속(관광지/주차장/khoa/airkorea/krairport) 평가.

**다음 한 작업**: T-RV-50부터 순차 PR. 각 PR = 격리 sandbox + 게이트 전수 + (provider 수정 시
해당 repo PR+머지 선행) + (frontend는 type-check/Windows Playwright e2e). 실데이터 검증은 T-212e.

## 2026-06-07 Codex 작업 메모 — T-212b admin UI 핵심 화면 보강

사용자 지시 “t212b 진행”에 따라 T-212b admin UI lane을 착수했다. 이번 PR 범위는
backend 계약이 이미 있는 화면을 frontend에 붙이는 데 한정했다.

- **`/admin/features`**: 운영자용 table 목록(`GET /admin/features`) + 검색/상태/kind/
  이슈/정렬/page size/cursor, 선택 상세(`GET /features/{id}`), weather panel
  (`GET /features/{id}/weather`), 단건 deactivate mutation을 추가했다.
- **`/admin/issues`**: `GET /admin/issues` 목록 필터(q/status/severity/type/provider/
  dataset/bbox), 단건 상세, resolve/ignore/reopen/retry geocode/retry reverse/apply
  kraddr/manual override action UI를 추가했다.
- **`/ops/logs`**: T-212c에서 추가된 `GET /ops/system-logs`와
  `GET /ops/api-call-logs` 조회 UI를 추가했다.
- 기존 `/features` 상세 panel에도 weather card를 노출했고, sidebar nav/README/e2e
  smoke를 갱신했다.
- 기존 `/admin/dagster` recent runs table의 run id를 Dagster webserver run detail로
  바로 열 수 있게 연결했다.

**검증**: WSL Node 20.20.2로 `npm run type-check`, `npm run lint`, env 명시
`npm run build`, `npm run doctor`, `npm run test` 통과. `React Doctor --verbose --diff`
잔여 10건은 기존 shadcn/ui primitive non-component export/multi component, 기존
Dagster iframe sandbox 탐지 false positive(이미 sandbox 있음), 기존 unused detail hook이다.
`http://127.0.0.1:9014` dev server에서 `/admin/features`, `/admin/issues`,
`/ops/logs`, `/features` HTTP 200 확인. Windows 호스트 Playwright로
`npm -w packages/krtour-map-admin/frontend run e2e -- e2e/admin-ops.spec.ts --reporter=line`
실행해 9 passed.

**남은 T-212b**: Dagster schedule/sensor tick history와 backend-backed failure detail은
summary/embed 중심 계약을 확장하는 후속 API/UX 필요.

**다음 한 작업**: Dagster tick/backend detail API/UX를 별도 작은 PR로 설계·구현.

## 2026-06-07 Codex 작업 메모 — Sprint 5 운영 진입 잔여 task 상세화

사용자 지시 “sprint 5 관련 테스크 상세화 하고 pr 후 머지”에 따라 Sprint 5 최종
운영 진입까지 남은 작업을 1-PR 단위로 실행 가능한 형태로 정리한다. 새 정본 리포트는
`docs/reports/sprint5-final-task-breakdown-2026-06-07.md`다.

- 남은 큰 축: **T-RV-04b-opinet krtour wiring**, **T-212b admin UI 완결성**,
  **T-212d perf baseline/tuning**, **T-212e live full reload 최종 검증**,
  **T-210 TripMate 연계 정리**, **Sprint 5 closure 문서/gate 전환**.
- `tasks.md` Phase 6/7와 `SPRINT-5.md` §4.1에 같은 순서와 DoD를 연결했다.
- 현재 main 기준 `python-opinet-api#8` 보강은 merged이며, opinet은 전국 nightly가 아니라
  bounded bbox 또는 POI-target scope 결정 후 krtour Dagster resource에 연결해야 한다.

**다음 한 작업 후보**: 실데이터/운영 scope 결정 없이 바로 진행 가능한 **T-212d seeded
PostGIS perf baseline**. T-RV-04b-opinet은 bounded bbox vs POI-target 결정이 먼저 필요하고,
T-212b는 admin UI 변경 폭이 커 별도 작업 브랜치와 충돌 여부를 확인한 뒤 진행한다.

## 2026-06-07 Claude 작업 메모 — T-RV-04b opinet provider 보강(#8) + 다음=T-212d perf

사용자 결정(“opinet: AI agent로 라이브러리 직접 보강”)대로 `python-opinet-api`를 보강.
**조사 결론: OpiNet OpenAPI에 지역/전국 bulk 주유소 목록 엔드포인트가 물리적으로 없음**
(station 반환은 aroundAll≤5km/lowTop10 top20/detailById 단건뿐). `python-opinet-api#7`에 결론
코멘트.

- **`python-opinet-api#8` merged(v0.2.0)**: `iter_stations_in_bbox()`(sync+async) — bbox를
  aroundAll 반경 격자(`radius*√2`)로 덮고 `uni_id` dedup하는 근사 enumeration. 한계(면적 비례
  호출수 급증→bounded 권장, tel/lpg_yn 부재→detail N+1) 문서화. ruff/mypy/183 pytest green.
- **krtour-opinet wiring = 후속(scope 결정 필요)**: 전국 nightly는 쿼터 비현실 → bounded
  bbox(operator 설정) 또는 POI-타깃 모델. krtour `OpinetStationItem` Protocol을 provider
  `Station`에 ADR-044 재정렬 + settings-gated bbox fetcher 필요. (이 1건 외 T-RV-04b provider
  wiring 전부 완료: datagokr/krheritage/krex×2/mois A+B/knps×2.)

**다음 한 작업(사용자 지시): T-212d perf 부분 진행** — 실데이터 없이 가능한 범위부터:
seeded PostGIS(testcontainers, WSL)로 hot read 쿼리(nearby/in-bounds/search/ops cursor/F-checks)
EXPLAIN 수집 + 기존 인덱스 vs 쿼리 커버리지 분석 + 인덱스 후보 문서화
(`docs/reports/t-212d-perf-baseline-*.md`). 실 볼륨 측정/프런트 프로파일링은 T-212e/codex lane.

## 2026-06-07 Claude 작업 메모 — T-RV-04b mois Phase A 소스 DB sync (mois 마무리)

사용자 지시 “knps 후 mois 마무리”에 따라 MOIS **Phase A**(LOCALDATA 다운로드→소스 DB
적재)를 구현해 mois를 완결했다. Phase B fetcher가 읽는 SQLite 소스 DB를 채우는 단계다.

- **신규** `mois_source_sync.py`: 순수 helper `sync_mois_source_db(settings,
  service_slugs=None)`(lazy `import mois`, `create_sqlite_schema` → keyless
  `LocalDataFileClient` → `sync_localdata_source_db(PROMOTED_SERVICE_SLUGS, commit=True)`,
  결과를 `MoisSourceSyncSummary`로 복사) + Dagster op `mois_localdata_source_sync` + job +
  주간 schedule(STOPPED, `0 4 * * 1` KST). `definitions.py` 등록.
- **정정**: Phase A는 공개 파일 포털(`file.localdata.go.kr`)에서 받으므로 **API key
  불요(네트워크만)** — provider `LocalDataFileClient` 생성자에 key 파라미터 없음. 기존
  문서의 `data_go_kr_service_key` 필요 서술을 정정.
- db_path는 `settings.mois_source_db_path`(미설정 시 `ProviderCredentialMissing`, Phase B와
  동일 계약). 실데이터(실 다운로드) 검증은 T-212e.

**다음 한 작업**: T-RV-04b 잔여는 **opinet 1건뿐**(차단 — bulk/region station endpoint
없음, `python-opinet-api#7` 보강 대기 또는 POI-타깃 모델 전환 product 결정). opinet을
제외하면 provider live fetcher wiring은 datagokr/krheritage/krex(rest+traffic)/mois(A+B)/
knps(point+geometry) 전부 완료. 그 외 T-212 잔여(b: codex UI lane, d: perf baseline,
e: 실데이터 full reload)는 lane 조율/실 스택 필요.

## 2026-06-07 Claude 작업 메모 — T-RV-04b ⑥ knps live fetcher (provider 보강) 완료

**knps**(국립공원/트래킹)를 T-RV-04b 여섯 번째로 닫는다. 사용자 지시(“knps는
미완성이거나 빠진 부분이 많아. 적극적으로 python-knps-api를 수정하며 진행”)에 따라
**provider 라이브러리 자체를 보강**했다: `python-knps-api#7`(merged, **v0.2.0**)로
헤더 정규화 typed record(`KnpsPlaceRecord`/`KnpsGeoRecord`)와 read 메서드
(`client.files.read_place_records(key)`·`read_geo_records(key)`)를 추가했다. krtour는
best-guess 컬럼 매핑(구 `KnpsPointColumnMap` 등, dead) 대신 provider typed record를
**직접 소비**(ADR-044).

- 실 스키마 3종(standard `(CODE)` 헤더 / weather_stations / trails 한글 props)을
  라이브 다운로드로 확인 후 provider에서 정규화. source_id 우선순위
  `ID_CD→STN_ID→OBJECTID→SEQNO→NO→row-hash`.
- krtour 측: `provider_fetchers.fetch_knps_point_records`/`fetch_knps_geometry_records`
  (**async generator** — 다운로드/파싱이 async, `KnpsClient().files.read_*` await 후
  yield, `finally: await client.aclose()`). `resources.build_provider_record_live_resource`
  시그니처를 `Iterable | AsyncIterator`로 확장, asset `_record_batches`는 이미
  `AsyncIterable` 지원.
- dataset key는 `KrtourMapSettings.knps_point_dataset_key`(기본 `knps_visitor_centers`)
  /`knps_geometry_dataset_key`(기본 `knps_trails`)로 두고, `definitions.py`
  `SETTINGS_VALUE_RESOURCES` + `_settings_value_resource`로 fetcher와 asset의
  `knps_*_dataset_key` resource가 **같은 settings 값**을 보게 해 불일치 제거.
- keyless 공개 파일셋이라 credential guard 불요(`setting_names` 비어 live guard 항상
  활성). 실 fetch 검증은 T-212e.

**다음 한 작업: mois 마무리(Phase A)** — LOCALDATA download +
`sync_localdata_source_db(PROMOTED_SERVICE_SLUGS)` → SQLite 소스 DB를 만드는 Dagster
op/스케줄(Phase B fetcher는 이미 그 DB를 읽음). network + `data_go_kr_service_key`
필요, 실검증은 T-212e. 그 다음 잔여 T-RV-04b는 opinet(차단, `python-opinet-api#7` 대기).

## 2026-06-07 Codex 작업 메모 — T-209 final backup/restore safety automation

사용자 지시에 따라 T-209 계열을 마무리한다. T-212 계열과 T-RV-04b는 Claude Code
진행 범위라 건드리지 않는다. 이번 범위는 `T-209e-c` 이후 잔여였던 ADR-039 mutex,
staging restore smoke/count 검증, restore hot-swap env 전환 자동화다.

`scripts/docker-backup.sh`, `scripts/docker-restore.sh`,
`scripts/docker-restore-swap.sh`는 `scripts/with-pg-advisory-lock.py`로 PostgreSQL
advisory lock `maintenance:backup-restore`를 잡고 실행된다. `docker-restore.sh`는
복원 뒤 기본으로 `scripts/docker-restore-verify.sh`를 호출해 staging app DB
`feature.features` count, Dagster table count, RustFS file count를 확인한다.
`scripts/docker-restore-swap.sh`는 검증된 staging DB/volume을 가리키는
`.env.restore-swap`을 만들고, `KRTOUR_MAP_RESTORE_SWAP_APPLY=1`일 때만 compose
서비스를 해당 env로 재기동한다. `docker-compose.yml`은 기본 RustFS volume name은
유지하되 `KRTOUR_MAP_RUSTFS_VOLUME` override를 지원한다.

**다음 한 작업**: T-209 계열은 이번 PR로 닫는다. 후속 선택 시 사용자 조율상
T-212/T-RV-04b는 피하고, 새 리뷰 코멘트나 비충돌 백로그를 최신 main 기준으로 다시
확인한다.

## 2026-06-07 Codex 작업 메모 — T-209e-c backup/restore admin surface

사용자 지시에 따라 T-212 계열과 T-RV-04b는 Claude Code 진행 범위로 두고, Codex는
T-209 계열로 이동한다. 이번 범위는 `T-209e-c` admin backup/restore router +
hot-swap UI다. `/admin/backups`는 `data/backups/<backup_id>` artifact와 manifest를
읽고, `POST /admin/backups`는 cold backup command plan을 만든다.
`/admin/restore/{backup_id}`는 staging restore command plan을 만들며, host command
실행은 `KRTOUR_MAP_ADMIN_BACKUP_COMMAND_ENABLED=true` opt-in과 요청별
`execute=true`가 모두 있어야 한다. `/admin/restore/{backup_id}/swap`은 운영
DSN/volume switch를 자동 실행하지 않고 manual-required 승인 경계만 반환한다.

**다음 한 작업**: T-209e-c 이후 남은 T-209e 범위는 ADR-039 advisory lock critical
section, staging restore 후 smoke/count check 자동화, 운영 DSN/volume hot-swap 자동
실행이다. 후속 착수 전 사용자 지시와 Claude lane을 다시 확인하고 T-212/T-RV-04b
파생은 피한다.

## 2026-06-07 Codex 작업 메모 — T-RV-37 잔여 hygiene 마무리

남은 PR 리뷰 후속 중 `T-RV-37` 잔여 hygiene을 한 PR로 닫는다. 범위는
frontend `DebugUi*`/`debug_ui` → `Admin*`/`admin`, `/features/search` 실제
`total_count`, offline upload encoding fallback, CORS 일원화, Dagster repository
selector 설정화, router/Dagster S3 store factory 공유, production
`NEXT_PUBLIC_*` fail-fast, kraddr-geo timeout 설정화다. `admin_issues.py` timeout은
T-212 범위라 제외하고, `T-RV-04b` provider live fetcher wiring도 Claude Code 진행
범위라 Codex에서 건드리지 않는다.

**다음 한 작업**: 사용자 지시에 따라 `T-209` 계열로 이동한다. 현재 남은 후보는
**T-209e-c admin backup/restore router + hot-swap UI**다.

## 2026-06-07 Claude 작업 메모 — T-RV-04b provider live fetcher (순차 진행 중)

T-212c 완료 후 **T-RV-04b**(provider public client live fetcher wiring)를 provider
순차로 진행. 패턴: `provider_fetchers.fetch_<provider>(settings)`(lazy provider import,
credential 없으면 guard 메시지) + `resources.build_provider_record_live_resource(spec,
fetch)`로 해당 resource_key만 guard→live 교체. dagster 테스트는 provider 패키지 fake로
검증(실 키 불요), 실 fetch 검증은 키 있는 환경(T-212e)에서.

- [x] **① datagokr_cultural_festivals**(festival, #261) — clean match.
- [x] **② krheritage_events**(2026-06-07) — ADR-044 cross-repo 재조정: upstream
  `python-krheritage-api#4`(HeritageEvent.raw 주입, merged) + krtour `KrHeritageEvent`
  Protocol/transform을 provider 필드명(starts_on/place/address)에 재정렬 + fetcher
  (`event.iter_months()` rolling window).
- [x] **③ krex_rest_areas**(2026-06-07) — ADR-044 재정렬 + **option 2 파생 자연키**
  (`name::route_name::direction`, `|`는 ADR-009 예약→`::`). Protocol을 RestArea 필드명으로
  재정렬(uni_id/address 제거). provider 안정 id/address는 **이슈 `python-krex-api#7`**로 분리.
- **적합성 감사(`docs/reports/t-rv-04b-provider-fetcher-audit-2026-06-07.md`): datagokr
  외는 전부 model↔Protocol 실검증 필수(감사 "ASSUMED CLEAN" 신뢰 불가).**
  - [x] **④ krex_traffic_notices**(2026-06-07) — ADR-044 재정렬(Protocol→Incident shape) +
    krtour-side 파생(notice_id `::` 복합키, title 합성, valid 파싱, source_agency 기본,
    coordless). 잔여: EX incidentType 코드 매핑(krtour follow-up).
  - **opinet**: ⏸ provider 차단 — bulk/지역 엔드포인트 없음(aroundAll 5km만) → 이슈
    `python-opinet-api#7`. 라이브러리 보강 대기 또는 POI 타깃 모델 전환(product 결정).
  - [x] **⑤ mois_license_records**(Phase B, 2026-06-07) — clean match. fetcher가
    `mois_source_db_path`(env `KRTOUR_MAP_MOIS_SOURCE_DB_PATH`)의 미리 sync된 MOIS 소스
    SQLite DB → `iter_open_place_records(PROMOTED_SERVICE_SLUGS)` stream.
    **잔여 mois Phase A**: LOCALDATA 다운로드+`sync_localdata_source_db` Dagster op/스케줄.
  - [x] **⑥ knps**(point + geometry, 2026-06-07) — provider 보강(`python-knps-api#7`,
    v0.2.0)으로 헤더 정규화 typed record + `read_place_records`/`read_geo_records` 추가,
    krtour는 직접 소비(best-guess 컬럼 매핑 폐기). fetcher는 async generator(다운로드/
    파싱 async), live builder는 `Iterable | AsyncIterator`로 확장. dataset key는 settings
    값을 fetcher/asset이 공유(`SETTINGS_VALUE_RESOURCES`). keyless라 credential 불요.
- **원칙(업데이트)**: provider 착수 전 (1) 이미 구현됐는지 grep, (2) provider model이
  krtour Protocol을 실제로 만족하는지 검증(미검증 wiring은 런타임 AttributeError),
  (3) **provider 라이브러리 수정이 필요하면 직접 편집 대신 해당 repo에 AI agent용 상세
  GitHub 이슈 생성**(사용자 지시 2026-06-07). 자연키 파생 시 `|` 금지(ADR-009)·`::` 사용.

## 2026-06-07 Claude 작업 메모 — T-DA-13 `/admin/issues` 완료 → 다음 T-212 후속

DA-D-03 envelope 전면 통일(T-DA-15/16/18, #250~#255) **완료**. 이어서 **T-DA-13
`/admin/issues`(DA-D-04 = T-212 핵심 API) 구현 완료** — `routers/admin_issues.py`
(GET 목록 keyset cursor + GET 단건 + PATCH 7 action) + 신규 `infra/feature_address_repo.py`
(feature.features UPDATE + `ops.feature_overrides` upsert) + kraddr-geo 정/역지오코딩.
`{data, meta}` envelope. 단위 14 + PostGIS 통합 3. **목록 `q`/`bbox` 필터도 마무리**
(`ops_repo` 확장: q ILIKE + bbox EXISTS 4326 GiST `&&`, PostGIS 통합 테스트).

**T-212c 완료**: envelope 통일 + `/ops/health-deep`(readiness, degraded 503) +
**system/API-call 로그 표면**(마이그레이션 `0018_ops_logs`, `infra/log_repo.py`,
`GET /ops/system-logs`·`GET /ops/api-call-logs`, opt-in api-call-log middleware
`KRTOUR_MAP_ADMIN_API_CALL_LOG_ENABLED`) + error envelope 중앙화(기구현 확인).

**남은 T-212 = 내 API lane 밖**:
- **T-212b**(admin UI: `/admin/issues` 검토 화면, `/admin/features`, weather panel,
  로그/이슈 화면) — codex lane. API 계약(envelope/필드)은 `openapi.json` 정본 frozen.
- **T-212d**(EXPLAIN/perf baseline) — 라이브 데이터로 측정·문서화. `T-RV-40`(F6 LATERAL
  4회 풀스캔) 인덱스 검토 포함.
- **T-212e**(실데이터 full reload + offline upload 검증 + 최종 리포트) — 실 provider
  키 + 라이브 스택 필요(operator/codex 환경). 사전: reload 스크립트(`T-209e` 계열)·
  consistency gate 재사용.

**다음 한 작업 후보**: T-212d perf baseline 문서(EXPLAIN 수집 가능한 쿼리부터) 또는
T-RV-40 F6 인덱스, 그 외 codex와 lane 조율(b/e).

**조율 갱신**: Codex는 사용자 지시에 따라 T-209e-c(backup/restore)만 잡고,
T-212 계열은 Claude Code 진행 범위로 둔다. `/admin/issues` API 계약은
`openapi.json` 정본을 따른다.

## 2026-06-06 Codex 작업 메모 — T-RV-27/40/41 운영 hardening + F6 성능 전제

PR 리뷰 후속 중 같은 운영 hardening/performance 범위인 `T-RV-27`, `T-RV-40`,
`T-RV-41`을 한 묶음으로 닫는다. Docker compose host publish 기본값은
`KRTOUR_MAP_DOCKER_BIND_HOST=127.0.0.1`로 제한하고, 컨테이너 내부 `0.0.0.0` listen은
유지한다. host 모든 interface 노출은 `KRTOUR_MAP_DOCKER_BIND_HOST=0.0.0.0` 명시
opt-in과 네트워크 보호 전제로만 문서화한다.

F6 opening_hours consistency SQL은 `feature.features`를 4회 풀스캔하지 않도록
`candidate_features` CTE로 feature table을 한 번만 읽고, 4개 JSONPath period 추출을
단일 `CROSS JOIN LATERAL` 내부로 모은다. MV `CONCURRENTLY` 전제는 `T-101`
체크리스트와 performance/Dagster 문서에 `UNIQUE` 인덱스 + 최초 비-concurrent populate
후 전환으로 고정한다.

다음 리뷰 후속은 **T-RV-37 잔여 hygiene** 또는 **T-RV-04b(provider public client
live fetcher wiring)** 이다. `T-RV-04b`는 provider별 정책(OpiNet scope, MOIS source
DB refresh, KNPS file parser)을 함께 정해야 하므로 별도 PR로 분리한다.

## 2026-06-06 Codex 작업 메모 — T-212a inventory + e2e gap matrix

T-212a를 완료한다. `docs/reports/t-212a-inventory-gap-matrix-2026-06-06.md`에 최신
main 기준 admin OpenAPI 43 path, user OpenAPI 13 path, frontend route 10개, Dagster
assets/jobs/sensors/schedules/resources, DB/API/frontend/e2e gap을 재분류했다.

핵심 후속은 **T-209e-c**(backup/restore admin router + hot-swap UI), **T-212b**
(`/admin/features`, `/admin/issues`, weather card UI, admin workflow e2e), **T-212c**
(admin envelope/error/log contract + `/ops/health-deep`), **T-212d**(EXPLAIN/React
Doctor/Playwright 성능 baseline), **T-212e**(full reload + 실데이터 최종 검증)다.

## 2026-06-06 Codex 작업 메모 — T-RV-38/39 consistency count 의미 정리

T-RV-38/39를 한 묶음으로 닫는다. F4 dedup backlog WARN은 더 이상 pending row 수를
`count`에 직접 넣지 않는다. 임계 초과형 케이스로 `count=1`만 기록하고, 실제
백로그 수와 기준값은 `CaseResult.metadata` 및 `summary.case_metadata.F4`의
`pending_count`/`threshold`/`over_threshold`에 둔다. 따라서
`summary.total_violations`와 `by_severity.WARN`은 행 위반 수와 백로그 규모를 섞지
않는다.

F8 file object orphan은 같은 `feature_files.file_id`가
`metadata_without_active_feature`와 `metadata_missing_object`를 동시에 만족해도
count는 distinct metadata row 1건으로 센다. 문제 유형별 `sample_ids`는 그대로 남기고,
`metadata.metadata_file_issue_count`와 `metadata.object_missing_metadata_count`로
breakdown을 보존한다.

검증은 `TMPDIR=/tmp .venv/bin/python -m pytest tests/unit/test_infra_consistency.py tests/integration/test_consistency_reports.py tests/unit/test_cli_consistency_report.py packages/krtour-map-dagster/tests/test_maintenance.py -q`,
`ruff check .`, `mypy --strict`, `lint-imports`로 진행했다. 다음 T-RV 후보는
**T-RV-40(F6 perf, T-212d 편입)**, **T-RV-41(MV CONCURRENTLY 전제, T-101 체크리스트)**,
또는 **T-RV-04b(provider live fetcher wiring)** 이다.

## 2026-06-06 Codex 작업 메모 — mcp-telegram 완료 알림 셋업

각 agent worktree의 MCP 설정에 `mcp-telegram`을 추가한다. Codex는
`.codex/config.toml`, Claude는 `claude.json`, Antigravity는 `antigravity.json`과
`.gemini/mcp.json`에 등록한다. credential은 tracked 설정에 쓰지 않고 각 worktree의
로컬 `.env.mcp-telegram`에만 둔다.

단위 작업 완료 후 PR을 만들면 Telegram으로 짧은 작업 요약과 PR 링크를 보낸다는
운영 규칙을 `AGENTS.md`, `SKILL.md`, `docs/runbooks/agent-workflow.md`,
`docs/codegraph-worktree.md`에 명시한다. 다음 한 작업은 직전 메모의
**T-209e-c admin backup/restore router + hot-swap UI** 또는 **T-212 전체점검**
흐름을 유지한다.

## 2026-06-06 Codex 작업 메모 — T-209e-b staging cold restore 자동화

T-209e-b를 구현한다. `npm run docker:restore -- <backup_id>`는 `T-209e-a` cold backup
산출물을 staging app DB(`krtour_map_restore`), staging Dagster DB
(`krtour_map_dagster_restore`), staging RustFS Docker volume
(`krtour-map-rustfs-restore`)으로 복원한다. script는 `meta/SHA256SUMS`를 먼저 검증하고,
운영 DB 이름으로 restore하려는 경우 즉시 실패한다. 기존 staging 대상 재사용/삭제도
기본 금지이며 `KRTOUR_MAP_RESTORE_RECREATE=1`을 명시해야 한다.

이번 PR은 restore 자동화와 문서/정적 회귀 테스트를 닫는다. 다음 비 T-RV/T-213 후보는
**T-209e-c admin backup/restore router + hot-swap UI** 또는 ADR-045 잔여 정리 후
**T-212 전체점검**이다.

## 2026-06-06 claude 작업 메모 — T-213e(weather card) 완료 → T-213a~h 전부 완료

T-213 묶음 마지막(7/7) 완료. weather 적재/조회 전체 스택: `feature_weather_values`
테이블(**alembic 0017**), `weather_repo`(load + `build_weather_card`),
`GET /features/{feature_id}/weather`(user spec), client helper.

**T-213(TripMate 요구사항 후속) a~h 전부 완료**: a(리포트) b(`/features/nearby`)
c(clustering) d(client read parity) e(weather card) f(`/categories`) g(provider
last-sync) h(public health/version). 다음 비-T-213 후보는 감사 전 백로그
**T-DA-15/16**(응답 envelope 전면 통일, DA-D-03) 또는 **T-DA-13**(`/admin/issues`,
T-212) 또는 codex 진행 외 잔여(T-209 Docker polish 등). 각 작업은 작은 독립 PR +
origin/main rebase + 격리 sandbox + (endpoint 추가 시) frontend types 재생성.

## 2026-06-06 claude 작업 메모 — T-213c(bbox clustering) 완료

T-213 묶음 6번째 완료. `/features/in-bounds` 서버 클러스터링 — **설계 결정: 행정구역
rollup**(client/grid 대신, feature의 sido/sigungu/legal_dong 코드 GROUP BY).
`cluster_unit`(sido|sigungu|eupmyeondong) 쿼리 + zoom 유도. 응답 `data.clusters[]`.

진행 순서: d✅ b✅ f✅ h✅ g✅ → **T-213c ✅** → 마지막 **T-213e**(weather card/시계열:
weather value 테이블·쿼리 + `build_weather_card` + `GET /features/{id}/weather`). 가장
크고 schema/쿼리 동반. 각 subtask 작은 독립 PR + rebase + 격리 sandbox + frontend types 재생성.

## 2026-06-06 Codex 작업 메모 — T-201b Phase 2 dry-run report

T-201b의 마지막 잔여인 Phase 2 dry-run report 산출 경로를 구현한다.
`krtour-map consistency-report` CLI는 `run_consistency_checks()` F1~F8을 기본
`persist=false`로 실행하고 Markdown/JSON report를 출력한다. `--known-file-objects`
JSON/JSONL로 RustFS/S3 object snapshot을 받아 F8 양방향 검사를 실제 운영 preflight에
포함할 수 있다. `--persist`는 같은 report를 `ops.feature_consistency_reports`에도
저장하고, `--fail-on-error`는 gate enable 전 CI/운영 preflight에서 ERROR를 실패로
전환한다.

이번 PR은 CLI contract와 `docs/reports/t-201b-phase2-dry-run-report-2026-06-06.md`를
첨부해 T-201b를 닫는다. T-213 계열은 별도 에이전트가 진행 중이므로 다음 비 T-RV
후보는 **T-209 Docker/daemon polish**다.

## 2026-06-06 Codex 작업 메모 — T-RV-34/35 Dagster 실행 품질

T-RV-34/35를 한 묶음으로 닫는다. `feature_update_request_queue_sensor`는 더 이상
읽지 않는 cursor를 갱신하지 않고, `peek_update_requests(limit=10)`로 queued request를
batch 조회해 tick 1회에 최대 10개 `RunRequest`를 낸다. 실행 멱등성은 기존처럼
`run_key`와 request 상태전이/claim 계약이 담당한다. failure sensor는
`fail_update_request`나 운영 notifier가 실패해도 sensor 자체가 다시 실패하지 않게
예외를 흡수하고 로그만 남긴다.

MOIS bulk feature-load asset은 provider record resource를 한 번에 list로 만들지 않고
`MOIS_RECORD_BATCH_SIZE` 단위로 변환/적재한다. 공통 Dagster load helper도
`FEATURE_LOAD_CHUNK_SIZE` 단위 DB load를 수행하며, chunk 결과는 `FeatureLoadResult.merge()`
기준으로 합산한다. 모든 feature-load asset과 consistency/dedup maintenance op에는
exponential `RetryPolicy(max_retries=3, delay=60)`를 붙였다.

검증은 Dagster sensor/asset/maintenance/ETL unit 19개, feature update repo/client 및
Dagster ETL integration 16개, `ruff`, `mypy --strict`, `lint-imports`로 진행했다. 다음
T-RV 후보는 **T-RV-04b(provider live fetcher wiring)** 또는 새 리뷰 백로그
**T-RV-38~41**이다. **T-RV-27은 production hardening 전까지 계속 skip/deferred**다.

## 2026-06-06 claude 작업 메모 — T-213g(provider last-sync) 완료

T-213 묶음 5번째 완료. `GET /providers/{provider}/last-sync`(provider_sync_state
기반, items[] + 필터 + 404, **내부 cursor 비노출**) + client read/write sync-state
helper 4종 + `krtour.map.providers` knps/krheritage re-export.

진행 순서: T-213d ✅ → T-213b ✅ → T-213f ✅ → T-213h ✅ → **T-213g ✅** → 남음
**T-213c**(bbox clustering — `/features/in-bounds` `cluster_unit` 서버 집계 설계/구현)
→ **T-213e**(weather card / 시계열 — 가장 큼). 각 subtask 작은 독립 PR + rebase +
격리 sandbox + frontend types 재생성.

## 2026-06-06 claude 작업 메모 — T-213h(public `/health`,`/version`) 완료

T-213 묶음 4번째 완료. public `GET /health`(liveness, DB-free, 항상 mount) +
`GET /version`(admin/lib/commit)을 `routers/public_status.py`로 추가, user spec 포함.
deep readiness(DB/RustFS/Dagster)는 후속 `/ops/health-deep`로 분리.

진행 순서: T-213d ✅ → T-213b ✅ → T-213f ✅ → **T-213h ✅** → 다음 **T-213g**
(provider export + `GET /providers/{provider}/last-sync`) → T-213c(bbox clustering) →
T-213e(weather card). 각 subtask는 작은 독립 PR + 매 PR 전 origin/main rebase +
격리 WSL sandbox. **OpenAPI endpoint 추가 시 frontend `types.ts`
(`openapi-typescript@7.13.0`) 재생성 필수**.

## 2026-06-06 claude 작업 메모 — T-213f(`GET /categories`) 완료

T-213 묶음 3번째 완료. `GET /categories`로 144건 정적 카탈로그(+선택적 DB 분포)를
노출했다. drift gate는 marker-react `maki.ts`가 name→glyph 구조라 ADR-029 원안
1:1이 아닌 완화형(self-consistency + TS kebab 유효성 + 핵심 maki 커버)으로 적용.
docstring/category.md tier·icon 개수도 코드 기준 reconcile.

진행 순서: T-213d ✅ → T-213b ✅ → **T-213f ✅** → 다음 **T-213h**(public
`/health`/`/version` user spec) → T-213g(provider last-sync) → T-213c(bbox
clustering) → T-213e(weather card). 각 subtask는 작은 독립 PR + 매 PR 전
origin/main rebase + 격리 WSL sandbox(codex 충돌 회피). **OpenAPI endpoint 추가 시
프론트 `types.ts`(`openapi-typescript@7.13.0`) 재생성 필수**(drift gate).

## 2026-06-06 claude 작업 메모 — T-213b(좌표 `/features/nearby`) 완료

T-213 묶음 2번째 완료. `GET /features/nearby`(좌표 중심 반경) repo+client+endpoint+
OpenAPI(user subset 포함)를 추가했다. ADR-012로 입력 좌표만 CTE에서 1회 5179 변환하고
술어는 stored `coord_5179`에 적용(by-target nearby와 동일 candidates CTE 재사용).
PostGIS 통합 4건(필터/거리·cursor·invalid·EXPLAIN ADR-012)·router/client unit·OpenAPI
drift 모두 격리 sandbox에서 green.

진행 순서: T-213d ✅ → **T-213b ✅** → 다음 **T-213f**(`/categories` 카탈로그 HTTP
표면 + marker drift gate) → T-213h(public health/version) → T-213g(provider last-sync)
→ T-213c(bbox clustering) → T-213e(weather card). 각 subtask는 작은 독립 PR + 매번
origin/main rebase + 격리 WSL sandbox(codex 충돌 회피).

## 2026-06-06 claude 작업 메모 — T-213 진행 시작: T-213d(read parity) 완료

사용자 지시로 T-213(TripMate 요구사항 후속) 묶음을 하나씩, 적합한 순서로 진행한다.
codex가 Dagster/T-RV/T-209 쪽을 작업 중이라 충돌 회피를 위해 **각 subtask를 작은
독립 PR + 매번 origin/main rebase + 격리 WSL sandbox(`~/dev/python-krtour-map-claude`)**
로 진행한다.

진행 순서(저위험·선행 먼저): **T-213d(✅ 선행/client read parity)** → T-213b
(좌표 `/features/nearby`) → T-213f(`/categories`) → T-213h(public health/version)
→ T-213g(provider last-sync) → T-213c(bbox clustering) → T-213e(weather card).

**T-213d 완료**: `AsyncKrtourMapClient.get_features` / `search_features` /
`features_nearby_poi_cache_target` 추가(기존 repo 위임, 새 SQL 없음) + unit 3건.
다음 한 작업은 **T-213b**(좌표 기준 `/features/nearby` repo+endpoint+client+EXPLAIN
통합테스트).

## 2026-06-06 Codex 작업 메모 — T-209b-a Dagster Postgres instance storage 고정

T-209b-a를 구현한다. Docker와 로컬 admin-stack 모두 `docker/dagster.yaml`의 unified
`storage.postgres` 설정을 `KRTOUR_MAP_DAGSTER_PG_URL` 기준으로 사용한다. Dagster
instance config에서 이 key는 run/event/schedule-sensor tick metadata를 함께
PostgreSQL에 저장하므로, local/Docker 모두 `krtour_map_dagster`가 단일 metadata DB다.

`scripts/run-admin-stack.sh`는 시작 전 `krtour_map_dagster` DB 존재를 확인/생성하고,
`docker/dagster.yaml`을 `$DAGSTER_HOME/dagster.yaml`로 설치한다. 또한 `dagster dev`
대신 `dagster-webserver`와 `dagster-daemon`을 분리 실행하고, daemon pid 생존 여부를
readiness 뒤 확인한다. `$DAGSTER_HOME/schedules/schedules.db*` 생성은 회귀로 문서화했다.

다음 한 작업 후보는 **T-201b Phase 2 dry-run report** 또는 **T-209 Docker/daemon
polish**다. T-RV 잔여 실행 품질 묶음은 별도 T-RV 백로그에서 계속 추적한다.

## 2026-06-06 Codex 작업 메모 — T-RV-31/32/33 router/executor 정확성

T-RV-31/32/33을 한 묶음으로 닫는다. `execute_feature_update_request()`의 provider
runner 1회 호출을 `session.begin_nested()` savepoint 안에 격리해 runner가 DB write를
일부 수행한 뒤 실패해도 해당 write가 rollback되도록 했다. 요청 상태, matched scope,
target failure timestamp 같은 executor 메타데이터는 바깥 트랜잭션에서 `failed`로
기록된다. PostGIS 통합 테스트는 runner가 feature/source record를 적재한 뒤 예외를
던지는 경우 loaded feature가 남지 않는지 검증한다.

Admin feature issue summary는 `AdminFeatureIssueRecord.extra="allow"`를
`extra="forbid"`로 바꿔 OpenAPI open object drift를 닫았다. 생성 spec의
`additionalProperties=false`와 frontend generated type에서 index signature가 제거되는
것을 테스트/생성물로 고정했다.

`/features/nearby/by-target`의 `NearbyFeatureSummary.lon/lat`는 public 계약상 필수
`float`를 유지한다. repo SQL이 이미 `f.coord IS NOT NULL`과 `f.coord_5179 IS NOT NULL`을
동시에 필터링하므로 nullable DTO로 느슨하게 만들지 않고, 이 non-null 보장을 단위
테스트로 고정했다. 다음 T-RV 영역은 **T-RV-34/35(Dagster sensor/asset 실행 품질)** 이며,
**T-RV-27은 production hardening 전까지 계속 skip/deferred**다.

## 2026-06-06 Codex 작업 메모 — TripMate 요구사항 대조 task 반영

TripMate `docs/krtour-map-requirements.md`를 현재 krtour-map `origin/main`
(`ae67a88`, PR#232 이후)과 대조했다. TripMate 문서의 기준선은 `b775c74`라 OpenAPI
HTTP 모델, `krtour-map-admin`, user OpenAPI, feature update request 큐 구현 이전
상태가 섞여 있었으므로 그대로 복사하지 않고
`docs/reports/tripmate-requirements-reconcile-2026-06-06.md`로 K-1~K-14를 재분류했다.

`docs/tasks.md`에는 후속 묶음 `T-213a~h`를 추가했다. 핵심 잔여는 일반 좌표 기준
`/features/nearby`(`T-213b`), bbox clustering(`T-213c`), `AsyncKrtourMapClient`
read parity(`T-213d`), weather card(`T-213e`), category catalog(`T-213f`), provider
export/sync state/last-sync(`T-213g`), public health/version(`T-213h`)다. #232의
`/tripmate/feature-update-requests*` 공개 경로 분리도 반영했다. 최신 사용자 지시대로
단순 호환성·최소 수정이 아니라 완성도, 안정성, 확장성, 성능을 기준으로 task를
정의했다.

즉시 다음 한 작업은 기존 순서대로 **T-209b-a 구현**이다.

## 2026-06-06 Codex 작업 메모 — T-RV-29/30 OpenAPI user spec + frontend generated types

T-RV-29/30을 닫는다. TripMate/user OpenAPI에서 admin write/read path가 노출되지
않도록 feature update request 공개 경로를 `/tripmate/feature-update-requests`와
`/tripmate/feature-update-requests/{request_id}`로 분리했다. 기존 admin UI 경로
`/admin/feature-update-requests*`는 admin spec에 그대로 남고, 두 경로는 같은
`ops.feature_update_requests` queue와 repo 함수를 사용한다. user profile 생성 시
`USER_OPERATIONS`에 지정된 경로/메서드가 실제 full OpenAPI에 없으면 실패하도록
drift 가드를 추가했다.

Frontend는 `openapi-typescript` 생성물
`packages/krtour-map-admin/frontend/src/api/types.ts`를 커밋하고,
`src/api/*` DTO를 `paths`/`components` 파생 타입으로 전환했다. `gen:types`는
`../openapi.json`을 읽고, `gen:types:check`가 frontend CI에서 drift를 차단한다.
generated 타입이 더 정확히 표현한 optional nullable 필드에 맞춰 Dagster/dedup/features
화면 렌더링도 보정했다.

검증은 frontend `type-check`, `gen:types:check`, OpenAPI all profile check, 관련 admin
router/export unit test, ruff/mypy/lint-imports를 기준으로 진행했다. React Doctor
optional warning 7건은 기존 shadcn/ui primitive export 구조와 Dagster iframe sandbox
false positive 성격으로 확인했다. 다음 T-RV 영역은
**T-RV-31/32/33(router/executor 정확성)** 이며, **T-RV-27은 production hardening
전까지 계속 skip/deferred**다.

## 2026-06-06 Codex 작업 메모 — T-201b-d F8 file object orphan 정합성 검사

ADR-033 Phase 2의 마지막 정합성 케이스인 `F8`을 `run_consistency_checks()`에 WARN
케이스로 추가한다. `feature.feature_files` metadata와 객체 저장소 snapshot
(`known_file_objects`)을 비교해 DB metadata만 있고 실제 object가 없는 경우,
object만 있고 DB metadata가 없는 경우, 삭제/누락 feature에 연결된 file metadata를
각각 `metadata_missing_object` / `object_missing_metadata` /
`metadata_without_active_feature` sample로 보고한다.

현재 Alembic head에는 `feature.feature_files` 테이블이 아직 없으므로, F8은 테이블
부재 시 기존 호출에서는 OK로 남고, 객체 snapshot이 주입된 경우 object-only orphan만
WARN으로 보고한다. 향후 `feature_files` 정식 migration/업로드 경로가 들어오면 같은
검사 계약을 그대로 사용한다.

검증은 `TMPDIR=/tmp pytest -s tests/unit/test_infra_consistency.py -q` 14 passed,
`TMPDIR=/tmp pytest -s tests/integration/test_consistency_reports.py -q` 12 passed로
진행했다. 다음 한 작업은 사용자 지시에 따라 **T-209b-a 구현**이다.
## 2026-06-06 Codex 작업 메모 — T-209b-a Dagster SQLite schedule storage 제거 task 등록

운영 확인 중 Dagster가 `DAGSTER_HOME` 아래 `.dagster/schedules/schedules.db-*`
SQLite 파일을 내부 schedule storage로 생성하는 경로가 남아 있음을 확인했다. ADR-045
운영 모델은 독립 PostgreSQL `krtour_map_dagster`를 Dagster metadata DB로 둔다고
정했으므로, schedule/run/event storage가 로컬 SQLite에 남아 있으면 webserver/daemon
분리 운영과 백업/복구 범위가 깨진다.

`docs/tasks.md`에 즉시 실행 task **T-209b-a**를 추가했다. 범위는 Docker standalone과
로컬 admin-stack의 Dagster instance config를 PostgreSQL-backed storage로 맞추고,
`schedule_storage`, `run_storage`, `event_log_storage`가 모두
`KRTOUR_MAP_DAGSTER_PG_URL`/`krtour_map_dagster`를 쓰게 하는 것이다. DoD는 schedule
state toggle의 PostgreSQL 지속성, webserver/daemon 동일 config 공유,
`$DAGSTER_HOME/.dagster/schedules/schedules.db-*` 미생성 확인, compose/runbook 회귀
테스트다.

다음 한 작업은 **T-209b-a 구현**이다. T-201b-d F8, T-RV-29/30, T-212 전체점검은
이 SQLite schedule storage 제거가 끝난 뒤 진행한다.

## 2026-06-06 claude 작업 메모 — 문서 전수 정합성 감사(T-DA)

`origin/main`(PR#225) 기준 문서 전체를 감사해
`docs/reports/docs-consistency-audit-2026-06-06.md`(T-DA-01~11, DA-D-01/02)로 정리하고
무쟁점 drift를 같은 PR에서 수정했다. 사용자 결정 DA-D-01에 따라 CLAUDE.md §2 /
AGENTS.md "코드 작성 단계" / sprints/README "현 위치"의 PR 번호·스프린트 완료여부
서술을 제거하고 **진척의 단일 정본은 본 `resume.md` + `tasks.md`**라고 못박았다.
앞으로 이 두 파일이 진척 정본이므로, entry/정책 문서에 PR 번호를 다시 박지 않는다.

같은 PR에서 고친 사실오류: CLAUDE.md geocoding 포트 `8888`→`12201`, ADR 현황
`001~047/다음 048`, category 개수 라벨 `141`→`144`(코드 실측), architecture 의존체인
`category` 추가, decisions.md ADR-002/025/036 현행 기준 교차참조.

사용자 추가 요청으로 **외부 노출 API 일관성/완결성**도 점검했다(감사 §8). 생성 spec
↔ contract 대조 결과: `/admin/issues`(ADR-046 주소 이슈 수동 처리) 미구현(T-DA-13),
`/admin/providers` 미구현 표기 누락(T-DA-14), list/단건 응답 셰입 이원화(T-DA-15/16).
사용자 결정: **DA-D-03 = 전면 통일**(모든 admin 응답 `{data,meta}` — 코드 전환은 별도
PR), **DA-D-04 = T-212 묶음**(`/admin/issues`는 T-212b/c). 본 PR에는 contract §3.1
표준화 명시 + §4 미구현 배지(문서)만 반영했다.

다음 한 작업 후보: ① **T-DA-15/16 envelope 전면 통일**(별도 코드 PR — 3 flat list +
6 bare 단건 + admin frontend hook + openapi 재생성), ② **T-DA-13 `/admin/issues`
구현**(T-212b/c), ③ 감사 전 백로그 **T-201b-d F8** 또는 **T-RV-29/30**.

## 2026-06-06 Codex 작업 메모 — T-RV-23 offline upload idempotency/load TOCTOU

T-RV-23을 닫는다. offline upload 생성은 이제 업로드 body SHA-256 checksum을
metadata 기준값으로 저장하고, `provider + dataset_key + sync_scope + checksum_sha256`
unique constraint(`alembic 0016`)로 같은 파일 재업로드를 멱등 충돌로 처리한다.
중복 시 방금 쓴 object는 보상 삭제하고, 응답은 `OFFLINE_UPLOAD_DUPLICATE` 코드와
기존 `upload_id` details를 담은 409 error envelope를 반환한다.

`/admin/offline-uploads/{upload_id}/load`는 Dagster launch 전에 `ops.import_jobs`를
만들고 같은 트랜잭션에서 `offline_uploads.status='loading'`,
`load_job_id=<job_id>`를 선점한다. Dagster launch 실패 시 job은 `failed`, upload는
`load_failed`로 닫는다. Dagster op는 advisory lock 미획득을 성공 no-op로 보지 않고
`Failure`로 기록하며, 이미 `loading + load_job_id`인 preclaimed load는 기존 job을
재사용한다.

검증은 `TMPDIR=/tmp pytest -s` 기준 offline upload router/Dagster/core/PostGIS 묶음
`42 passed`, `ruff check .`, `mypy --strict`, `lint-imports`, OpenAPI all profile
check로 진행했다. 다음 한 작업 후보는 **T-201b-d F8(file object orphan WARN)** 또는
**T-RV-29/30(OpenAPI/user spec + generated frontend types)** 다. **T-RV-27은
production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-25 offline upload store 재사용

T-RV-25를 닫는다. offline upload router는 이제
`_offline_upload_store_from_request()`를 통해 `request.app.state.offline_upload_store`를
우선 재사용하고, 없을 때만 `KrtourMapSettings()`/S3 client를 lazy 1회 생성해
`app.state`에 캐시한다. `create` 경로뿐 아니라 `preview`/`validate` 경로도 같은
cached app-state store를 우선한다.

FastAPI lifespan 종료 시 cached store가 boto3-like `s3_client.close()`를 제공하면
닫는다. 같은 app에서 연속 upload 요청이 store builder를 한 번만 호출하는지와 shutdown
close를 router 단위 테스트로 고정했다.

남은 offline upload 리뷰 후속은 **T-RV-23(checksum/idempotency + load TOCTOU)** 다.
그 다음 작은 후보는 T-RV-29/30(OpenAPI/user spec + generated frontend types) 또는
T-201b-d F8(file object orphan WARN)다. **T-RV-27은 production 레벨 hardening 전까지
계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-24 후속 offline upload ORM state check 동기화

T-RV-24 후속으로 offline upload 상태 단일 계약을 ORM 모델까지 확장한다.
`OFFLINE_UPLOAD_STATE_VALUES` tuple을 추가하고, `OfflineUploadRow`의
`ck_offline_uploads_state`가 이 tuple을 참조하게 했다. 상태 tuple/집합과 ORM check
constraint 문자열에 모든 상태가 포함되는지 단위 테스트로 고정한다.

DB migration은 추가하지 않는다. 실제 check 값은 기존 migration과 동일하며, 이번
변경은 Python ORM 모델의 상태 목록을 core 계약에 맞추는 정렬이다.

다음 한 작업은 **T-RV-25(upload store app.state 재사용)** 또는
**T-RV-23(offline upload checksum/idempotency + load TOCTOU)** 다. 둘은 같은
offline upload router/store 경계에 걸려 있으므로 먼저 T-RV-25를 작은 PR로 닫는 편이
충돌 위험이 낮다. **T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-24 offline upload 상태 계약 단일화

T-RV-24를 처리한다. offline upload 상태와 포맷 집합을
`krtour.map.core.offline_upload_states`로 분리해 admin router,
`krtour.map.offline_upload`, `infra.offline_upload_repo`가 같은 계약을 공유하게 한다.
`LOADABLE_STATES`와 tabular format set 복붙을 제거했고, 상태 집합 단위 테스트를
추가했다.

validation 상태(`validating`/`validated`/`validation_failed`)는 이미 validate API/job이
producer이므로 dead state가 아니다. `cancelled`는 DB terminal state로 유지하되, 현재
offline upload cancel API가 없으므로 reserved state로 문서화한다.

다음 한 작업은 **T-RV-25(upload store app.state 재사용)** 또는
**T-RV-23(offline upload checksum/idempotency + load TOCTOU)** 다. 둘은 같은
offline upload router/store 경계에 걸려 있으므로 PR을 합치거나, 먼저 T-RV-25를 작은
PR로 닫는 편이 충돌 위험이 낮다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-22 offline upload write rollback

T-RV-22를 처리한다. `POST /admin/offline-uploads`는 RustFS/S3 object write 성공 후
`ops.offline_uploads` metadata insert가 실패하면 같은 요청에서 방금 쓴 object를
보상 삭제한다. 정상 등록된 offline upload 원본은 ADR-045 D-14 기준 그대로 무기한
보존하며, 이번 삭제는 DB row가 없는 write-rollback 전용 예외다.

`S3ObjectStore`에는 boto3 S3 호환 `delete_object` async wrapper를 추가했다. fake S3
단위 테스트와 admin router metadata insert 실패 회귀 테스트로 object orphan 방지
경로를 고정한다.

다음 한 작업은 **T-RV-23(offline upload checksum/idempotency + load TOCTOU)** 또는
**T-RV-25(upload store app.state 재사용)** 다. T-RV-24 상태 상수 단일화는 이 두 작업
사이에 작게 분리할 수 있다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — PR#153~#179 리뷰 리포트 상태 동기화

`docs/reports/pr-153-179-review-2026-06-04.md`의 표와 권장 처리 순서를
2026-06-05 `origin/main` 기준으로 다시 맞췄다. 처리 로그와 `docs/tasks.md`에는
반영되어 있었지만 표에 미반영으로 남아 있던 T-RV-01/02/03, T-RV-05~21,
T-RV-26, T-RV-28, T-RV-36, T-RV-37a~37e를 완료 표시로 정리했다.

T-RV-04는 `T-RV-04a` guard resource/env mapping 완료와 `T-RV-04b` provider
public client live fetcher 잔여로 분리했다. 다음 구현 후보는 계속
**T-201b-d F8(file object orphan WARN)** 또는
**T-RV-23/25(offline upload idempotency/store reuse)** 다.

## 2026-06-05 Codex 작업 메모 — T-201b-c F7 dedup score 회귀

ADR-033 Phase 2의 `F7`를 `run_consistency_checks()`에 WARN 케이스로 추가한다.
`ops.dedup_review_queue`의 pending 후보 중 양쪽 feature의 primary source provider가
서로 다른 cross-provider 후보만 검사한다. 큐에 저장된 `total_score`를
baseline으로 삼고, 현재 feature의 이름/좌표/카테고리를 `core.scoring.score_pair()`로
재계산한 점수가 baseline보다 기본 10점 이상 낮아지면 회귀로 보고한다. 같은
provider/sibling 후보와 이미 검토 완료된 행은 F7 대상이 아니다.

다음 한 작업은 **T-201b-d F8(file object orphan WARN)** 다. 이후 Phase 2 dry-run
report를 붙여 T-201b를 닫는다.

## 2026-06-05 Codex 작업 메모 — T-201b-b F5 provider last_success SLA

ADR-033 Phase 2의 `F5`를 `run_consistency_checks()`에 WARN 케이스로 추가한다. active
`provider_sync.provider_sync_state` cursor 중 `last_success_at`이 SLA를 넘겼거나 아직
성공 기록이 없는 row를 provider/dataset/scope 단위로 샘플링한다. 기본 SLA는 24시간이고,
`ops.provider_refresh_policies.system_interval_seconds`가 있으면 provider 정책값을 우선한다.
`enabled=false` policy는 관측 대상에서 제외한다.

다음 한 작업은 **T-201b-c F7(cross-provider dedup score 회귀 WARN)** 다. 이후
F8(file object orphan)과 Phase 2 dry-run report를 작은 PR로 닫는다.

## 2026-06-05 Codex 작업 메모 — T-RV-19 POI/cache target cursor/schema

T-RV-19를 처리한다. `GET /admin/poi-cache-targets`는 이제 단순 `LIMIT` 목록이 아니라
`updated_at DESC, target_id DESC` keyset pagination을 사용하며, query `cursor`와 응답
`next_cursor`를 제공한다. cursor payload는 repo에서 base64 JSON으로 검증하고,
decode/schema 오류는 DB 조회 전에 `422`로 반환한다.

`PUT /admin/poi-cache-targets/{external_system}/{target_key}` request body의
`provider_overrides`는 최대 64개 provider/dataset key와 typed override 필드만 허용한다.
`metadata`도 `tripmate_poi_id`, `external_ref`, `source_url`, `labels`, `note`로
한정했다. Pydantic 내부 필드는 reserved name 충돌을 피하려고 `metadata_`를 쓰고,
외부 JSON/OpenAPI는 계속 `metadata` alias를 노출한다.

admin frontend의 `/admin/poi-cache-targets` typed hook과 화면은 cursor를 전달하고,
이전/다음 pagination과 저장 후 첫 페이지 복귀를 지원한다. 다음 한 작업은
**T-201b-b F5(provider last_success SLA WARN)** 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다. 병행 에이전트가
다른 PR을 머지할 수 있으므로, 다음 작업 시작 전 `origin/main`을 다시 fetch/rebase한다.

## 2026-06-05 Codex 작업 메모 — T-201b-a F6 opening_hours 정합성 검사

ADR-033 Phase 2를 한 번에 끝내지 않고, DB 외부 의존이 없는 `F6`부터 분리한다.
`run_consistency_checks()`는 이제 F1/F2/F3/F6 정적 SQL 케이스와 F4 dedup backlog
threshold 케이스를 함께 평가한다. F6는 `detail.business_hours` 또는
`detail.opening_hours`의 `periods`/`special_days[].periods` 중 같은 요일에서
`open.time > close.time`인 period를 ERROR로 보고한다. 다음 요일로 넘어가는
overnight period와 close가 없는 24/7 표현은 허용한다.

다음 한 작업은 **T-201b-b F5(provider last_success SLA WARN)** 다. 이후 F7(dedup score
회귀), F8(file object orphan), dry-run report를 각각 작은 PR로 닫는다.

## 2026-06-05 Codex 작업 메모 — T-203 PR CI workflow full matrix

Sprint 5 운영 진입 gate 중 `T-203`을 처리한다. `.github/workflows/ci.yml`은 기존
branch protection 호환을 위해 `pytest (Python X)` check 이름을 유지하되, 해당 matrix는
unit/lint/admin/dagster unit test만 실행한다. PostGIS 통합 테스트는
`pytest integration (PostGIS)`, fixture replay는 `pytest fixture replay` 별도 always-on
job으로 분리한다.

`openapi-drift`와 `type-check + next build (Node 20)`은 path filter를 제거해 문서-only
PR에서도 check가 생성되도록 한다. 이 상태에서 `docs/runbooks/branch-protection.md`의
required check 목록을 T-203 이후 기준으로 승격한다.

다음 한 작업은 **T-201b(ADR-033 Phase 2 F4~F8 + Dagster 게이트)** 다. 충돌 위험을 낮게
유지하려면 먼저 F5/F6 같은 단일 consistency case 또는 dry-run report 문서/테스트부터
분리한다.

## 2026-06-05 Codex 작업 메모 — T-204 branch protection 설정 가이드

Sprint 5 운영 진입 gate 중 `T-204`를 처리한다. `docs/runbooks/branch-protection.md`는
GitHub `main` branch protection 설정값을 운영자용으로 분리한다. 필수 설정은 PR 기반
merge, approval 1개, branch 최신화 요구, force-push/delete 차단, squash merge 기준이다.

현재 모든 PR에서 항상 생성되는 required check는 `lint`, `pytest (Python 3.11)`,
`pytest (Python 3.12)`, `pytest (Python 3.13)`로 문서화한다. `openapi-drift`와
`type-check + next build (Node 20)`은 path-filtered workflow라 지금 바로 required로
고정하면 check가 생성되지 않은 PR이 막힐 수 있다. 이 둘은 T-203에서 neutral/success
check를 모든 PR에 만들도록 바꾼 뒤 required로 승격한다.

다음 한 작업은 **T-203(PR CI workflow full matrix 정리)** 다. 그 외 병행 가능성이 낮은
문서 작업을 고르면 `docs/runbooks/agent-workflow.md`의 T-202/T-204 반영 여부를 점검한다.

## 2026-06-05 Codex 작업 메모 — T-202 pre-commit hook 정착

Sprint 5 운영 진입 gate 중 `T-202`를 처리한다. `.pre-commit-config.yaml`은 local
hook 4개를 등록한다. `krtour-map-journal-required`는 staged `src/` 또는 `tests/` 계열
변경에 대해 `docs/journal.md` 갱신을 요구하고, 운영자가 명시적으로
`BYPASS=1`을 준 경우에만 한 번 우회한다.

Python code/test 변경 시 `scripts/run-precommit-check.sh`가 `.venv` Python을 우선
찾아 staged Python 파일 대상 `ruff format --check`, `mypy --strict -p krtour.map`,
`mypy --strict -p krtour.map_dagster`, `lint-imports`를 실행한다.
전체 codebase는 아직 ruff format baseline이 아니므로 all-files 리포맷은 별도 PR로
남기고, 개발환경 문서에는 `pre-commit install`, `pre-commit run`, journal gate
우회 기준을 추가한다. hook 설치 위치는 WSL `/mnt/f`가 아니라 Git metadata가 있는 NTFS
worktree의 Windows Git/Git Bash 기준으로 문서화한다.

다음 한 작업은 **T-203(PR CI workflow full matrix 정리)** 또는
**T-204(branch protection 설정 가이드)** 다. 충돌 위험이 더 낮은 문서 작업을 우선하면
T-204가 적합하다.

## 2026-06-05 Codex 작업 메모 — T-RV-20 feature update request schema 검증

T-RV-20을 처리한다. `POST /admin/feature-update-requests` request body의 `scope`는
이제 `scope.type` discriminator를 기준으로 6개 scope 모델
(`feature_ids`, `center_radius`, `sigungu_by_radius`, `bbox`, `provider_dataset`,
`cache_target_keys`) 중 하나로 검증된다. `center_radius`와 `sigungu_by_radius`는
OpenAPI 계약처럼 `center: {lon, lat}`를 요구하며, legacy root `lon`/`lat` payload는
enqueue 전에 `422`로 거절된다.

`update_policy`는 알려진 필드만 허용하는 모델로 바꿨고,
`providers`/`dataset_keys`에는 list 상한을 추가했다. admin frontend 생성 화면도 같은
`center` payload를 보내도록 정렬했다. admin/user OpenAPI 산출물은 재생성했으며,
legacy scope shape, unknown policy key, 과도한 provider filter list 회귀 테스트를
추가했다.

다음 한 작업은 **T-209e-b(restore/admin router/hot-swap 설계 분리)**,
**T-RV-19(admin UI 지도 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다. 병행 에이전트가
다른 PR을 머지할 수 있으므로, 다음 작업 시작 전 `origin/main`을 fetch/rebase한 뒤
충돌 위험이 낮은 파일 범위만 잡는다.

## 2026-06-05 Codex 작업 메모 — T-209e-a standalone cold backup

T-209e를 restore/admin router/hot-swap까지 한 번에 다루지 않고, 먼저 충돌 가능성이
낮은 cold backup 단위로 분리한다. `npm run docker:backup`은
`scripts/docker-backup.sh`를 호출해 standalone Docker compose의 `krtour_map` app DB,
`krtour_map_dagster` Dagster metadata DB, RustFS volume을
`data/backups/<backup_id>/` 아래에 저장한다.

스크립트는 API/frontend/Dagster/RustFS writer service가 실행 중이면 기본 중단하고,
운영자가 명시적으로 `KRTOUR_MAP_BACKUP_ALLOW_RUNNING=1`을 준 경우에만 best-effort
snapshot을 허용한다. restore는 아직 자동 실행하지 않으며, `docs/backup-restore.md`는
checksum 검증, `pg_restore --list`, RustFS tar 목록 확인, 수동 cold restore 경계를
문서화한다.


## 2026-06-05 Codex 작업 메모 — T-RV-37e Docker image hygiene

T-RV-37 cleanup 묶음 중 Docker 이미지 multi-stage/non-root/standalone 항목을 처리한다.
`docker/api.Dockerfile`과 `docker/dagster.Dockerfile`은 builder stage에서 패키지를
설치하고 runtime stage에서 `appuser`로 실행한다. frontend는 Next.js
`output: "standalone"`과 `outputFileTracingRoot`를 사용해 `.next/standalone` 서버만
runner 이미지에 복사하고 `nextjs`로 실행한다.

회귀 테스트는 Dockerfile이 multi-stage/non-root인지, frontend가 `next start` 대신
standalone `server.js`를 실행하는지 정적으로 검증한다.

## 2026-06-05 Codex 작업 메모 — T-RV-37d ops cursor decode 예외 축소

T-RV-37 cleanup 묶음 중 `src/krtour/map/infra/ops_repo.py`의 `_decode_cursor` broad
exception catch를 줄였다. cursor base64/UTF-8/JSON parse 단계는
`binascii.Error`, `UnicodeDecodeError`, `json.JSONDecodeError`만 잡고, payload shape와
`datetime.fromisoformat` 오류는 별도 `ValueError("invalid {kind} cursor")`로 감싼다.

unit test는 import job cursor의 wrong-kind, `at` 누락, invalid datetime, non-object
payload를 추가해 DB query 실행 전에 거절되는지 검증한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19(admin UI 지도 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-37c map-marker-react dependency metadata

T-RV-37 cleanup 묶음 중 `@krtour/map-marker-react` dependency metadata를 정리했다.
`maplibre-vworld` peer dependency는 더 이상 floating range `^0.1.2`가 아니라 정확히
`0.1.2`를 요구한다. 실제 설치 spec은 workspace devDependency와 lockfile의
`github:digitie/maplibre-vworld-js#v0.1.3`이 담당한다.

패키지가 아직 skeleton이라 test file이 없으므로, `npm run test`는
`vitest run --passWithNoTests`로 성공 종료하게 했다. README는 ADR-043에 맞춰 npm
registry 게시가 보류되어 있고 현재 공유는 monorepo workspace 또는 git URL 기준임을
명시한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19(admin UI 지도 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-21 Dagster router hardening

T-RV-21을 처리한다. `GET /ops/dagster/summary`는 이제 repository, asset,
schedule/sensor, recent run 정보를 읽기만 하며 Dagster `setNuxSeen` mutation을 호출하지
않는다. embedded Dagster UI의 NUX 처리는 `POST /ops/dagster/nux-seen`으로 분리했고,
frontend `/admin/dagster`는 summary가 정상 조회되면 이 POST를 한 번 호출한다.

backend Dagster GraphQL 대상은 `KRTOUR_MAP_ADMIN_DAGSTER_ALLOWED_HOSTS` allowlist를
통과해야 한다. 기본 허용 host는 로컬/Docker 내부(`127.0.0.1`, `localhost`, `::1`,
`dagster`)이며, URL scheme은 `http`/`https`, GraphQL endpoint path는 `/graphql`이어야
한다. 설정 오류는 Dagster로 네트워크 호출을 보내기 전에 `status="error"` 응답으로
표시한다.

Dagster GraphQL HTTP 호출은 요청마다 `httpx.AsyncClient`를 새로 만들지 않고 FastAPI
lifespan/app state의 공유 client를 사용한다. TestClient나 특수 실행 경로에서 lifespan이
없는 경우에도 router가 lazy fallback으로 app state client를 만든다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19(admin UI 지도 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-37b Dagster purge schedule 문서 정리

T-RV-37 cleanup 묶음 중 `dagster-boundary.md` stale purge job/schedule 문서를
정리한다. 실제 `packages/krtour-map-dagster` 구현은 provider 적재 schedule 9개와
`consistency_dedup_refresh_daily_schedule`만 등록하며, purge job 또는 schedule은 없다.

`docs/dagster-boundary.md`에서 `feature_purge_weather_old`,
`feature_purge_notice_old`, `purge notice old (>1y)` 행을 제거했다. ADR-045 D-14
기준 offline upload/RustFS 원본은 만료 없이 보존하므로, purge는 TTL·삭제 정책과
실제 Dagster job 구현이 함께 들어오기 전까지 schedule 표에 추가하지 않는다고 명시한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-37a shell script 실행 셸 문서화

T-RV-37 cleanup 묶음 중 `scripts/*.sh` Bash 전용 실행 셸 문서화를 처리한다.
루트 `package.json`의 `docker:build`, `docker:up`, `admin:stack`, `ports:stop`은 모두
`bash scripts/*.sh`를 호출하고, 실제 스크립트도 `source`, Bash array,
`BASH_SOURCE`를 사용한다.

`docs/dev-environment.md`와 Docker runbook은 이제 이 스크립트들을 WSL 또는 Git Bash
에서 실행해야 하며, PowerShell에서는 직접 `.sh`를 실행하지 않고 `wsl bash -lc ...`
형태로 위임한다고 명시한다. PS 래퍼는 이번 범위에서 만들지 않고, 문서화된 실행
경로로 drift를 줄인다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-36 Dagster dependency hygiene

T-RV-36을 처리한다. `packages/krtour-map-dagster/pyproject.toml`은 더 이상
`python-krtour-map`을 무핀으로 두지 않고 같은 릴리스인
`python-krtour-map==0.2.0-dev`에 맞춘다.

Dagster `offline_upload_store` resource는 `resources.py`에서 `boto3`와
`botocore.config`를 직접 import하므로, clean install에서도 ImportError가 나지 않게
`boto3`/`botocore`를 runtime dependency로 선언한다. 패키지 로컬 pytest 설정에는
`asyncio_mode="auto"`를 추가했고, pyproject 회귀 테스트가 세 의존성과 async 설정을
고정한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-26 Docker healthcheck/readiness

T-RV-26을 처리한다. Docker compose의 `api`, `frontend`, `dagster` 서비스에 runtime
healthcheck를 추가했다. API는 컨테이너 내부에서 `/debug/health`, frontend는 Next.js
root(`:12305`), Dagster는 webserver root(`KRTOUR_MAP_DAGSTER_PORT`, 기본 `12302`)를
확인한다.

`frontend.depends_on`은 short form에서 `api: condition: service_healthy`로 전환해
API readiness 전 frontend가 먼저 healthy로 오판되는 경로를 줄였다. compose 회귀
테스트는 세 healthcheck와 frontend readiness dependency를 고정한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-28 frontend Docker npm ci

T-RV-28을 처리한다. frontend Docker image는 더 이상 floating dependency를
`npm install`로 해석하지 않는다. 루트 `package-lock.json`을 정식 커밋 대상으로
전환하고, `docker/frontend.Dockerfile`은 workspace package manifest와 lockfile을
먼저 복사한 뒤 `npm ci --workspaces --include=optional`로 설치한다.

`.gitignore`와 `.dockerignore`에서 `package-lock.json` 제외를 제거해 Docker build
context와 git 추적 기준이 일치하게 했다. Docker runbook과 deploy 메모는 frontend
Docker build가 lockfile 기반임을 명시한다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는
**T-RV-22/23/25(offline upload orphan/idempotency/store reuse)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-18 router typed error mapping

T-RV-18을 처리한다. feature update request 라우터는 더 이상
`"sigungu_resolver" in message` 같은 substring으로 503을 판단하지 않는다.
kraddr-geo resolver 설정 누락은 `SigunguResolverUnavailable` 타입으로 표현하고
`_handle_enqueue_error`에서 HTTP `503`으로 매핑한다. 알 수 없는 enqueue 예외는 내부
메시지를 응답에 노출하지 않고 `feature update request enqueue failed`만 반환한다.

dedup merge 경로는 `MergeError` 하위 타입인 `MergeNotFoundError`와
`MergeConflictError`를 추가했다. `/admin/dedup-reviews` merge 라우터는 not found를
404, 상태/입력 충돌을 409로 매핑하고, 알 수 없는 `MergeError`는 generic 500으로
숨긴다. 기존 CLI와 repo 호출자는 상위 `MergeError` catch로 계속 처리된다.

다음 한 작업은 **T-RV-20(router scope/update_policy schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는 **T-RV-04b(provider public
client live fetch wiring)** 다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-17 상태전이 guard

T-RV-17을 처리한다. `admin_feature_repo.deactivate_feature`는 이제 deleted 또는
soft-deleted feature를 inactive로 되살리지 않고 `FeatureStateConflict`를 올린다.
admin 라우터는 이를 HTTP `409`로 매핑해 404(없음)와 상태 충돌을 분리한다.

`integrity_violation_repo.set_data_integrity_violation_status`는
`resolved`/`ignored` terminal issue를 다른 상태로 되돌리지 않는다. 같은 terminal
상태로 재호출하면 멱등 처리로 보고 기존 `resolved_at`을 보존한다.

`offline_upload_repo`는 validation/load mark/finish 쿼리에 source-state guard를
추가했다. `loaded` 상태는 더 이상 loadable 상태가 아니며, admin load API와 core
오케스트레이터 모두 `loaded -> loading` 역전이/중복 Dagster launch를 허용하지 않는다.

다음 한 작업은 **T-RV-18/20(router typed error/schema 검증)**,
**T-RV-19/21(admin UI 지도/Dagster 선행 안정화)**, 또는 **T-RV-04b(provider public
client live fetch wiring)** 다. **T-RV-27은 production 레벨 hardening 전까지 계속
skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-16 dedup refresh master 신호/keyset

T-RV-16을 처리한다. `Feature` DTO와 `feature.features`에
`coord_precision_digits`를 정식 계약으로 추가한다. 좌표가 있는 `Feature`는 기본
precision 6을 갖고, 좌표가 없으면 precision도 `None`이어야 한다. DB는
`feature.set_feature_coord_precision()` trigger와 `ck_features_coord_precision`으로
같은 의미를 보강한다. 기존 좌표 row는 migration에서 6으로 backfill한다.

`list_dedup_refresh_features`는 이제 `updated_at DESC, feature_id DESC` keyset cursor를
받고, `idx_features_dedup_refresh_keyset` partial index를 사용하도록 설계한다.
`DedupRefreshFeature`는 `updated_at`, `coord_precision_digits`,
`as_master_candidate()`를 노출해 ADR-016 master 선정과 admin dedup 검토 UI가 같은
신호를 공유할 수 있게 한다. Dagster maintenance config도
`cursor_updated_at`/`cursor_feature_id`를 받을 수 있다.

이번 작업 중 사용자 지시에 따라 코드 수정 원칙도 명시했다. 앞으로는 최소 코드 수정
또는 임시 호환성보다 완성도, 최적 구조, 확장성, 안정성을 우선한다. 이 원칙은
`SKILL.md`와 `docs/agent-guide.md`에 반영했다.

다음 한 작업은 **T-RV-17(상태전이 가드)**, **T-RV-18/20(router error/schema
정리)**, 또는 **T-RV-19/21(admin UI 지도/Dagster 선행 안정화)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-05 Codex 작업 메모 — T-RV-15 scope resolver count/preview 분리

T-RV-15를 처리한다. `count_features_matching_scope`는 더 이상 dry-run/count 용도로
전체 feature row를 materialize하지 않는다. `center_radius`, `bbox`,
`sigungu_by_radius`, `provider_dataset`, `feature_ids`는 전체 match 수를 `count(*)`
계열 SQL로 계산하고, provider/dataset fanout과 sigungu code도 전체 scope 기준 별도
집계 SQL로 계산한다.

`ScopeResolution.feature_count`는 optional `matched_feature_count`를 우선 사용한다.
feature 목록은 기본 `DEFAULT_SCOPE_PREVIEW_LIMIT=1000`까지만 보존하며, preview가
잘리면 matched scope에 `feature_preview_count`, `feature_preview_limit`,
`feature_preview_truncated`를 기록한다. cache target scope는 provider별 target id
fanout이 필요하므로 이번 PR에서는 기존 full match 동작을 유지하고, T-RV-19/20 계열
scope validation/cursor 보강에서 별도 상한을 다룬다.

다음 한 작업은 **T-RV-16(dedup refresh master 선정 신호 보강)**, **T-RV-17(상태전이
가드)**, 또는 **T-RV-04b(provider public client live fetch wiring)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-14 dedup merge review row 잠금

T-RV-14를 처리한다. `merge_from_review`는 자동 master 선정 전에
`ops.dedup_review_queue` review row를 `FOR UPDATE`로 잠그고 pending 상태를 확인한다.
admin `merge_dedup_review`의 수동 master 지정 경로도 같은 row lock을 사용해 자동/수동
merge 경로의 TOCTOU 차이를 없앤다.

integration test는 한 트랜잭션이 review row를 `FOR UPDATE`로 보유한 동안 다른
트랜잭션의 자동 merge와 수동 merge가 `lock_timeout`까지 대기하는지 검증한다.

다음 한 작업은 **T-RV-15(scope resolver count/limit)**, **T-RV-04b(provider public
client live fetch wiring)**, 또는 **T-RV-16(dedup refresh master 선정 신호 보강)** 다.
**T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-13 UUID default 스키마 한정

T-RV-13을 처리한다. ADR-008에 따라 pgcrypto는 `x_extension` schema에 격리되어
있으므로, 운영 테이블 UUID default가 search_path에 의존하지 않도록
`x_extension.gen_random_uuid()`로 표준화한다.

대상은 bare default가 남아 있던 `ops.feature_consistency_reports.report_id`,
`ops.dedup_review_queue.review_id`, `ops.import_jobs.job_id`,
`ops.feature_merge_history.merge_id`다. 모델과 기존 migration source를 정리하고,
`alembic/versions/0014_uuid_default_schema.py`로 기존 DB default도 ALTER한다.
integration test는 Postgres catalog의 ops UUID default expression을 직접 검증한다.

다음 한 작업은 **T-RV-14(dedup merge FOR UPDATE)** 또는 **T-RV-15(scope resolver
count/limit)** 다. **T-RV-27은 production 레벨 hardening 전까지 계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-12 dedup pair 순서 독립 unique

T-RV-12를 처리한다. `ops.dedup_review_queue`는 이제 `feature_id_a < feature_id_b`
check(`ck_dedup_pair_order`)를 갖고, `(feature_id_a, feature_id_b)` unique가 canonical
방향에서만 적용된다. `alembic/versions/0013_dedup_pair_order_invariant.py`는 기존
self-pair를 제거하고, unordered duplicate pair는 검토 완료 행을 우선 보존한 뒤 하나만
남겨 canonical 방향으로 정규화한다.

`dedup_repo`는 `DedupCandidate` upsert 전에 pair를 정렬해 `(a,b)`와 `(b,a)`를 같은
row로 수렴시킨다. self-pair는 검토 큐 의미가 없으므로 DB에 넣지 않고 `skipped`로
처리한다. integration test는 reversed pair update, self-pair skip, 직접 insert의
check 위반을 검증한다.

다음 한 작업은 **T-RV-13(UUID default schema qualification)** 또는
**T-RV-14(dedup merge FOR UPDATE)** 다. **T-RV-27은 production 레벨 hardening 전까지
계속 skip/deferred**다.

## 2026-06-04 Codex 작업 메모 — T-RV-10 keyset cursor 정밀도

T-RV-10을 처리한다. `/features/search`는 q 검색 cursor에 DB에서 받은
`score::text`를 저장하고, 다음 페이지 predicate를 `(-score, feature_id) >
(-cursor_score, cursor_feature_id)`로 바꿔 `ORDER BY score DESC, feature_id ASC`와
같은 정렬축을 사용한다. 사용자 응답의 `score`는 계속 float로 내려가지만 cursor
비교는 DB score text 기반이다.

`/admin/dedup-reviews`는 `total_score` `NUMERIC` cursor를 float가 아니라 문자열로
운반하고, predicate와 `ORDER BY` 모두 `review_id::text`를 사용하도록 통일했다. 같은
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
`scripts/run-admin-stack.sh` 실제 실행(API `12301`, Web `12305`, Dagster `12302`
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
uploads 화면에는 해당하지 않는다. WSL 실제 서버(API `12301`, web `12305`, Dagster
`12302`)에서는 multipart upload → RustFS `krtour-uploads` 저장 → Dagster
`offline_upload_load` run `SUCCESS` → DB `upload_status=loaded`, `job_status=done`,
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
- `docker-compose.yml`: RustFS service를 추가했다. host port는 API `12101`, console
  `12105`이며, `rustfs-init`가 `krtour-map`/`krtour-uploads` bucket을 생성한다.
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
`ops.import_jobs.status='failed'`, `ops.offline_uploads.status='load_failed'` 전이를
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
- `/admin/dedup-reviews`: pending/accepted/rejected/ignored/merged 필터와 결정 버튼.
- `/admin/feature-update-requests`: center radius 기반 request 생성, dry-run, cancel,
  run-now, request 상태 목록.
- `/admin/poi-cache-targets`: `external_system + target_key` upsert/delete와
  `/features/nearby/by-target` 주변 feature 조회.
- `/admin/dagster`: Dagster summary 자체 UI에 schedules/sensors 상태를 추가하고
  Dagster webserver iframe embed를 유지.

`/features`는 기존 지도/테이블 workflow를 유지하면서 운영 화면 링크를 헤더에 추가했다.
Playwright e2e는 새 home dashboard와 신규 admin/ops route smoke 기준으로 갱신했다.
검증 중 WSL root listener 또는 Windows `node.exe`/`wslrelay.exe`가 12305를 점유하면
새 WSL 서버 대신 stale UI를 보는 문제가 확인되어, `scripts/stop-fixed-ports.sh`가 WSL
root/Windows listener도 정리하도록 보강했다. Windows localhost relay가 내려간 경우를
위해 `scripts/load-env.sh` 기본 CORS origin에는 WSL IP 기반 `http://<WSL-IP>:12305`도
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
- `src/api/dedup.ts`: `/admin/dedup-reviews`
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

ADR-045 T-208d로 `packages/krtour-map-dagster`에 당시 구현된 9개 Feature 적재 asset의
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

중복 검토 backend로 `/admin/dedup-reviews` 목록과 `PATCH /admin/dedup-reviews/{review_id}`를
추가했다. accepted/rejected/ignored 전이는 queue status만 갱신하고, merged는
ADR-039 `dedup-merge:{review_id}` advisory lock 안에서 `feature_merge_history`를 남기는
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
발생했다. 대신 현재 로컬 API `http://127.0.0.1:12201`에
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

ADR-047로 krtour-map standalone 로컬 포트를 API `12301`, admin UI `12305`, Dagster
`12302`으로 고정했다. `AdminSettings`, frontend scripts, Playwright 기본 baseURL,
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

실데이터 확인은 로컬 kraddr-geo REST `http://127.0.0.1:12201` + T-027 최종 적재
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
기본값은 FastAPI backend `http://127.0.0.1:12201`로 맞췄다.

Sprint 1 scaffolding (PR#17~#27) 종료 후 Sprint 2 (PR#28~#59)에서
ADR-034 9단계 중 ①~④ provider + 디버그 UI + ETL live 11/11 dataset을 구현했다.
Sprint 3(PR#60~#95)에서는 DB 적재/조회, consistency report, dedup queue,
client orchestration, KNPS/krheritage provider, `/features` debug UI까지 완료했다.

ADR **001~049 모두 accepted**. 029→043, 003·035 일부→045로 supersede.
ADR-044 = 관련 라이브러리 `F:\dev\` 로컬 우선 조회 + 데이터 정합성 책임은 각
provider 라이브러리. ADR-045 = krtour-map Docker 독립 프로그램 + 독립 DB/Dagster +
TripMate OpenAPI 연동(ADR-003 함수 직접 호출 모델 supersede). ADR-046 = 호환 shim
없이 정본 방향으로 이행. ADR-047 = standalone 고정 포트. ADR-048 = `/v1` REST clean
cut + 정합성 표준. ADR-049 = TripMate-agent YouTube 후보 provider pull. 다음 후보 번호 = ADR-050.

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
  `http://127.0.0.1:12201`).
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
- [x] geocoder 보강 라이브 재검증 — kraddr-geo REST(`127.0.0.1:12201`) 실연동으로
  MOIS 좌표 → bjd_code 보강 200/200(100%) 확인. `docs/reports/mois-live-test-2026-06-01.md`
  §5. 코드 변경 없음.
- [x] CLI mutate 명령 ①  `krtour-map import mois <records-file>` — NDJSON snapshot
  record source(`cli/records.py`, ADR-006 provider 미import) → `run_mois_license_bulk_job`
  (advisory lock self-serialize + import_jobs 추적, lock 미획득 시 exit 3).
  `--geocoder-url` 선택 보강. unit 17 + integration 2. (ruff/mypy 58/import-linter 4 /
  776 passed.)
- [x] CLI mutate 명령 ② `krtour-map dedup-merge <review_id>` — 수동 병합(ADR-016).
  merge primitive 신규: `core.scoring.select_master`(좌표→updated_at→원천우선순위) +
  `infra.merge_repo`(source_link 재지정+충돌drop / loser soft-delete / 큐 merged 전이)
  + alembic 0007 `ops.feature_merge_history` + `client.merge_dedup_review`. lock은 CLI
  소유(`dedup-merge:{review_id}`), skip exit 3 / 미존재·이미검토 exit 2. unit 9 +
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

**accepted (text on main)**: ADR-001 ~ ADR-049 전부.
029→043 supersede, 044 (로컬 우선 조회 + 정합성 책임), 045 (krtour-map Docker 독립
+ OpenAPI, ADR-003 supersede), 046 (호환 shim 금지), 047 (고정 포트
API 12301/admin UI 12305/Dagster 12302), 048 (`/v1` REST clean cut + 정합성 표준),
049 (TripMate-agent YouTube 후보 provider pull). 다음 후보 번호 = ADR-050.

**후보 (미작성)**:
- ADR-050+ — 신규 provider 추가 절차 표준 (체크리스트)
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
