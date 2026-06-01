# journal.md — 작업 일지 (역시간순)

가장 위가 가장 최근. 새 엔트리는 위에 append.

## 2026-06-01 (claude) — dedup MOIS self-sibling (within-set pairwise)

**작업**: SPRINT-4 §2.2 — 한 dataset 안에서 같은 사업장이 2슬러그로 중복 등록된
경우(MOIS self-sibling)를 탐지해 dedup queue 적재.

- **산출물**:
  - `core/dedup.py` — `find_sibling_candidates(features)` within-set pairwise(i<j, self-pair/대칭 제외) + 공통 `_score_candidate` helper로 `find_dedup_candidates`와 스코어링 공유.
  - `AsyncKrtourMapClient.sync_sibling_candidates` — 탐지 → `ops.dedup_review_queue` upsert (cross-provider `sync_dedup_candidates`와 같은 enqueue 경로).
  - tests: unit 6(같은 사업장 2슬러그/고유쌍/self-pair 제외/KEEP_SEPARATE/빈·단일/auto_merge 제외) + integration 1(MOIS 2슬러그 적재 → sibling 탐지 → 큐 적재 + FK).
- **검증(WSL)**: mypy --strict 57 files / ruff All checks passed / import-linter 4 kept / 신규 unit 6 + integration 1 / 전체 **751 passed, 5 skipped**.

## 2026-06-01 (claude) — krtour-map CLI 골격 + status 명령

**작업**: SPRINT-4 §2.8 CLI entry-point 신설. read-only `status` 명령 + argparse
프레임. mutate 명령(`import`/`dedup-merge`)은 provider record source 주입 설계 후
후속.

- **산출물**:
  - `src/krtour/map/cli/main.py` — `krtour-map` argparse(`build_parser`) + `status` 서브명령(`KrtourMapSettings.pg_dsn`/`--dsn`로 engine → `AsyncKrtourMapClient.status_counts` → 출력) + `main(argv)` entry-point.
  - `infra/status_repo.py` — `gather_status_counts`(features 활성/비활성/kind별 + source_records provider별 + import_jobs state별 + dedup_queue status별) + `StatusCounts`. read-only raw SQL(ADR-004).
  - `AsyncKrtourMapClient.status_counts` + `pyproject.toml [project.scripts] krtour-map`.
  - tests: unit 5(parser/format) + integration 2(빈/데이터).
- **검증(WSL)**: mypy --strict 57 files / ruff All checks passed / import-linter 4 kept(cli layer) / 신규 unit 5 + integration 2 / 전체 **744 passed, 5 skipped**. `krtour-map --help` 실동작 확인(entry-point 등록).

## 2026-06-01 (claude) — MOIS Step A 실데이터 라이브 테스트

**작업**: Sprint 4a MOIS 파이프라인을 행안부 LOCALDATA 실데이터로 end-to-end
검증 (사용자 지시). 서비스키는 `F:\dev\python-krmois-api\.env`
(`DATA_GO_KR_SERVICE_KEY`) — 단, 파일 다운로드 경로(`LocalDataFileClient`,
`file.localdata.go.kr`)는 키 불필요.

- **변환**: 4 PROMOTED 슬러그(bakeries/traditional_temples/public_baths/
  museums_and_art_galleries) 실데이터 변환 — category/place_kind 매핑 docs §6.1과
  100% 일치, 좌표 96~99% 보유(EPSG:5174→WGS84 mois 변환). EXCLUDED(pet_grooming)
  영업중 200건 → 0건 skip.
- **적재**: public_baths 300건 testcontainers PostGIS 적재 → 재조회 300, coord_5179
  generated SRID=5179(ADR-012), source_records 300. alembic 0001~0006 적용.
- **발견(데이터 정합성)**: 파일 다운로드 CSV에 법정동코드 컬럼 부재 →
  `legal_dong_code` 전부 None → geocoder 미주입 시 `f_global_*` bucket. 본 lib는
  좌표 reverse geocoding으로 보강 설계(ADR-009) — 운영 시 kraddr-geo geocoder 주입
  필수. `opn_authority_code`는 bjd 미사용(payload만) 확인.
- 상세: `docs/reports/mois-live-test-2026-06-01.md`. (geocoder 보강 실연동 +
  OpenAPI 경로 법정동코드는 후속 — kraddr-geo REST 미기동.)

## 2026-06-01 (claude) — CLI mutex 첫 도입 (cli layer 신설, ADR-039)

**작업**: SPRINT-4 §2.8 — `src/krtour/map/cli/` layer 신설 + advisory lock 기반
CLI 명령 mutex. import-linter layered 최상위에 cli 추가.

- **산출물**:
  - `src/krtour/map/cli/__init__.py` + `cli/mutex.py` — `mutex_lock`(blocking)/`try_mutex_lock`(non-blocking) async ctx (`infra.advisory_lock` 얇은 래퍼) + lock key 헬퍼(`import_lock_key`/`dedup_merge_lock_key`/`alembic_upgrade_lock_key`, §2.8 컨벤션).
  - `pyproject.toml` import-linter layers에 `krtour.map.cli` 최상위 추가(`cli → client → providers → geocoding → infra → core → dto → category`).
  - `tests/unit/test_cli_mutex_keys.py`(4) + `tests/integration/test_cli_mutex.py`(3 — 상호배제/release/독립 키).
- **검증(WSL)**: mypy --strict 55 files / ruff All checks passed / import-linter 4 kept(cli layer 강제) / 신규 unit 4 + integration 3 / 전체 **737 passed, 5 skipped**.
- 실제 CLI 명령(`krtour-map import` 등 argparse/entry-point)은 후속 PR.

## 2026-06-01 (claude) — MOIS Step A streaming 배치 적재 (source DB 연결 준비)

**작업**: Step A bulk 적재를 대용량 source DB 스트림 대응 streaming 배치로 전환.
ADR-006상 mois를 import 안 하므로 iterator는 호출자 주입 — `records`로
`mois.db.iter_open_place_records(...)`를 그대로 넘기면 Step A가 완성된다.

- **산출물**:
  - `krtour.map.mois`: `_batched` helper + `DEFAULT_BATCH_SIZE=500`. `sync_mois_license_features_bulk`/`run_mois_license_bulk_job`/client 메서드에 `batch_size` 인자 추가 — `batch_size`개씩 변환·upsert하며 snapshot key만 누적(메모리 바운드), 전체 적재 후 prune.
  - `infra/feature_repo.py`: `FeatureLoadResult.merge`(배치 결과 누적) + `load_bundles`도 `.merge()`로 정리.
  - `tests/unit/test_mois_batched.py`(7 — _batched 분할/순서/빈, merge 합산/항등) + `test_mois_loader.py` +1(batch_size=2 streaming 적재+prune 동치).
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 unit 7 + integration 1 / 전체 **730 passed, 5 skipped**.

## 2026-06-01 (claude) — MOIS Step A 작업 통합 (advisory lock + import_jobs)

**작업**: advisory lock + import_jobs(앞 entry들) 위에 MOIS Step A bulk 적재를
작업 추적 + 단일 워커 직렬화로 감싸는 오케스트레이션.

- **산출물**:
  - `infra/jobs_repo.py` `start_import_job` — queue를 거치지 않고 곧바로 `state='running'` INSERT(self-driven inline job; enqueue+claim queue-worker 경로와 구분).
  - `krtour.map.mois.run_mois_license_bulk_job` — `try_advisory_lock("import:python-mois-api:<dataset>")`로 단일 워커 직렬화(미획득 시 `acquired=False` skip) → `start_import_job`(running) → `sync_mois_license_features_bulk`(변환·upsert·snapshot prune) → `finish_import_job`(done/예외 시 failed+re-raise) + `MoisBulkJobResult`.
  - `AsyncKrtourMapClient.run_mois_license_bulk_job` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` +2 — done 추적+sync / lock 보유 중 skip(작업·feature 미생성).
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 integration 2 / 전체 **722 passed, 5 skipped**.

## 2026-06-01 (claude) — ops.import_jobs 작업 큐 + jobs_repo (ADR-011)

**작업**: advisory lock helper 위에 ADR-011 작업 큐 영속화. 프로세스 재시작
안전성 + 다중 워커 직렬화(SKIP LOCKED). data-model.md §9.1 DDL 그대로.

- **산출물**:
  - `alembic/versions/0006_import_jobs.py` — `ops.import_jobs`(job_id/kind/payload/state/progress/current_stage/source_checksum/error_message/started_at/finished_at/heartbeat_at/created_at) + state/progress CHECK + 3 인덱스(state·kind_state·heartbeat partial).
  - `infra/models.py` `ImportJobRow` ORM.
  - `infra/jobs_repo.py` — `enqueue_import_job` / `claim_next_import_job`(advisory lock + `FOR UPDATE SKIP LOCKED`로 가장 오래된 queued→running) / `heartbeat_import_job` / `finish_import_job`(done→progress 100/failed/cancelled) / `recover_stale_running_jobs`(lifespan 복구 — heartbeat 만료 running→failed) + `ImportJob` dataclass.
  - `infra/__init__.py` export (jobs_repo + 누락됐던 soft_delete_features_not_in_snapshot 보강).
  - `tests/integration/test_jobs_repo.py`(9) — enqueue/claim FIFO/빈 큐 None/heartbeat/finish done·failed/invalid state raise/recover stale·fresh.
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 integration 9 + alembic 0006 upgrade green / 전체 **720 passed, 5 skipped**.

## 2026-06-01 (claude) — advisory lock helper (ADR-011 기초)

**작업**: ADR-011 작업 큐 직렬화 / ADR-039 CLI mutex의 공통 기초인 PostgreSQL
advisory lock 헬퍼 추가. 사용자 결정에 따라 **helper만** (import_jobs 테이블 +
jobs_repo는 후속).

- **산출물**:
  - `src/krtour/map/infra/advisory_lock.py` — `advisory_lock(session, key)`(blocking, `pg_advisory_lock`/`pg_advisory_unlock`) + `try_advisory_lock(session, key)`(non-blocking `pg_try_advisory_lock`, acquired bool yield) async context manager + `advisory_lock_key`(문자열 → BLAKE2b 8바이트 → signed int64 결정적 해시). session-level lock은 finally에서 명시 unlock(commit 자동해제 X).
  - `infra/__init__.py` export.
  - `tests/unit/test_advisory_lock_key.py`(3) + `tests/integration/test_advisory_lock.py`(3, 두 세션 상호배제/release/int 키).
- **conftest 방어 보강**: `pg_engine`에 `ALTER ROLE CURRENT_USER SET search_path`
  추가. bare `AsyncSession`이 connection을 recycle하면 asyncpg reset이
  connect-event의 session-level search_path를 지워 후속 unqualified `ST_*`가
  깨지던 잠복 버그 해소(advisory 테스트가 노출, migrated_engine과 동일 방어).
- **검증(WSL)**: mypy --strict 52 files / ruff All checks passed / import-linter 4 kept / 신규 unit 3 + integration 3 / 전체 **711 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a MOIS snapshot prune (delete_not_in)

**작업**: loader(앞 entry)에 이어 Step A bulk snapshot soft-delete 추가. 사용자
결정에 따라 **snapshot delete_not_in만** (advisory lock / import_jobs / mois source
DB iterator는 후속).

- **산출물**:
  - `infra/feature_repo.py` — `soft_delete_features_not_in_snapshot(session, *, provider, dataset_key, source_entity_type, snapshot_source_entity_ids)`. 주어진 primary source의 활성 feature 중 snapshot에 없는 것을 `status='inactive'` + `deleted_at`으로 비활성화(ADR-017, place 무기한 유지). raw SQL `UPDATE ... WHERE feature_id IN (… source_links ⨝ source_records … NOT IN snapshot)` + RETURNING count. 이미 비활성은 skip(idempotent).
  - `krtour.map.mois` — `delete_mois_license_features_not_in`(mois 래퍼) + `sync_mois_license_features_bulk`(변환→upsert→prune 한 단위 of work) + `MoisBulkSyncResult`(load 카운트 + deactivated).
  - `AsyncKrtourMapClient.sync_mois_license_features_bulk` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` +3 (snapshot 누락 soft-delete + idempotent / sync 1콜 load+prune / 빈 snapshot 전체 비활성화).
- **검증(WSL)**: mypy --strict 51 files / ruff All checks passed / import-linter 4 kept / integration 6(+3) / 전체 **705 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a MOIS loader (변환 → 적재 오케스트레이션)

**작업**: MOIS provider 변환 코어(앞 entry)에 이어 적재 loader 추가. 사용자
결정에 따라 **loader 모듈만** (advisory lock / snapshot delete_not_in / mois
source DB iterator는 후속 PR).

- **산출물**:
  - `src/krtour/map/mois.py` — `load_mois_license_features_bulk(session, records, *, fetched_at, dataset_key, reverse_geocoder)`. `providers.mois.license_records_to_bundles`(async 변환) → `infra.load_bundles`(idempotent upsert) 얇은 오케스트레이션. mois 라이브러리 런타임 import 안 함(Protocol 입력). commit은 호출자/감싼 transaction 소유(ADR-002/004).
  - `AsyncKrtourMapClient.load_mois_license_features_bulk` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` — testcontainers PostGIS 3건: PROMOTED 적재+EXCLUDED/미매핑/비영업 skip / 재적재 idempotent(feature 수 불변) / 전부 skip 시 빈 결과.
- **검증(WSL)**: mypy --strict 51 files / ruff All checks passed / import-linter 4 kept / 신규 integration 3 / 전체 **702 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a 진입: MOIS provider 변환 코어

**작업**: ADR-034 9단계 ⑦ — MOIS 인허가(LOCALDATA) provider 변환 코어 추가. `python-mois-api`(`import mois`)의 `PlaceRecord`를 place `FeatureBundle`로 정규화. 사용자 지시에 따라 **변환까지만** (적재/dedup/CLI mutex는 후속 PR).

- **산출물**:
  - `src/krtour/map/providers/mois.py` — structural Protocol `MoisLicensePlaceRecord`(`mois` 런타임 import 안 함, ADR-006) + async `license_record_to_bundle` / `license_records_to_bundles`(reverse_geocoder 보강). PROMOTED 42 슬러그만 승격 + `PROMOTED_CATEGORY_BY_SLUG`/`PROMOTED_PLACE_KIND_BY_SLUG` (docs §6.1, category 31코드 `_definitions` 검증). EXCLUDED 21 + 미매핑 + 비영업 skip. facility_info(building/medical/food/culture_sports).
  - `tests/unit/test_providers_mois.py` (23 test).
  - `providers/__init__.py` mois export + `__all__`.
- **설계 결정 2건**: ① 자연키 구분자 `::` (`make_feature_id`/`make_source_record_key`가 `|` 금지 → kma 패턴) ② marker_color `P-01` (미사용 팔레트). `docs/mois-feature-etl.md` §8 `|`→`::` 정정.
- **검증(WSL)**: mypy --strict 50 files / ruff All checks passed / import-linter 4 kept / 신규 23 test / 전체 699 passed·5 skip. 좌표는 mois가 변환한 WGS84 그대로(ADR-012/044, 좌표계 변환 X), legal_dong_code 1차 bjd_code·없으면 역지오코딩(ADR-009).

## 2026-06-01 (codex) — PR review 누락 보강 + 문서 정합성 sweep

**작업**: 사용자 지시 "4일전 PR부터 검색해서 리뷰를 달지 않은 PR에는 상세리뷰"에
따라 2026-05-28 이후 PR #45~#114를 GitHub에서 조회했다. review submission이 없던
PR #61~#114에 한국어 사후 상세 리뷰를 등록했고, 재조회 결과 review 누락 PR 0건을
확인했다.

**문서 보강**:
- `AGENTS.md`/`SKILL.md`/`docs/sprints/SPRINT-4.md`: 이미 accepted인 ADR-035/039/040/041을
  proposed로 표기하던 문구를 정정.
- `docs/address-geocoding.md`/`docs/resume.md`/`docs/sprints/README.md`: geocoding 현재
  endpoint 정본을 REST `/v1/address/*` + 로컬 `http://127.0.0.1:8888`로 명확히 하고,
  서비스 메타 버전 2.0과 endpoint prefix v1이 서로 다른 축임을 명시.
- `docs/address-geocoding.md`: `PlaceCoordinate` 잔존 예시를 `Coordinate`로 교체.
- `docs/tasks.md`: 오래된 Sprint 2 진행 중 문구를 PR#114 기준 현재 상태와 Sprint 4 4a
  다음 작업으로 갱신.

**검증**: review 누락 목록 재조회 결과 없음. 문서 변경은 `ruff format --check` 대상이
아니므로 Markdown 링크/키워드 검색과 `git diff --check`로 확인.

## 2026-05-31 (codex) — kraddr-geo 최신 포트 8888 정합 + 라이브 검증 준비

**작업**: 사용자 지시 "라이브러리 최신버전을 기준으로 업데이트"에 따라 로컬
`F:\dev\python-kraddr-geo` 최신 `main`과 `docs/ports.md`를 확인하고, 지오코딩 REST
기본 연동 포트를 공식 FastAPI backend `http://127.0.0.1:8888`로 정렬함. 기존
Next proxy(`13088/api/proxy`) 또는 컨테이너 예제(`kraddr-geo:8080`)는 테스트 기본값과
문서 예시에서 제거했다.

- `packages/krtour-map-debug-ui/settings.py`: `KRTOUR_MAP_DEBUG_UI_KRADDR_GEO_BASE_URL`
  기본값을 `http://127.0.0.1:8888`로 지정. 명시적으로 `None`을 주면 기존처럼
  `/debug/geocoding/*` 503 응답.
- `tests/*live*.py`: geocoding live 기본 URL을 `http://127.0.0.1:8888`로 정렬.
- `.env.example`, `docs/address-geocoding.md`, `docs/debug-ui-package.md`,
  debug-ui/frontend README, `CHANGELOG.md`, `docs/resume.md`에 동일 정책 반영.
- 로컬 `maplibre-vworld-js` 최신 tag `v0.1.2`도 확인해 frontend와
  `@krtour/map-marker-react`의 git URL 핀을 `#v0.1.2`로 올림. Next.js 16에서
  `next lint`가 제거된 점에 맞춰 `eslint .` + flat `eslint.config.mjs`로 전환.
  Next.js stable은 유지하되 transitive `postcss` audit 이슈는 root override로
  `^8.5.15`를 강제해 `npm audit` 0건 확인.
- WSL 설치 검증 중 `gdal>=3.8`이 최신 Python binding 3.13.0/3.8.5를 잡아 시스템
  `libgdal 3.8.4`와 ABI mismatch를 일으키는 문제 확인. geo extra는
  `gdal==3.8.4`로 고정해 현재 WSL/Docker 개발 환경과 patch 버전까지 맞춤.

**검증**:
- WSL ext4 샌드박스 `/home/digitie/dev/python-krtour-map`에 NTFS 원본 rsync 후
  editable install 성공 (`gdal-3.8.4` wheel).
- `pytest tests/unit`: 642 passed.
- `pytest packages/krtour-map-debug-ui/tests -m "not live"`: 113 passed / 45 deselected.
- kraddr-geo live 8888 geocoding/debug/provider tests: 45 passed.
- `pytest tests/integration`: 35 passed. `test_dedup_with_kraddr_geo_live.py`: 5 passed.
- 전체 main pytest: 681 passed. `ruff`, `mypy`, `lint-imports` green.
- Windows frontend: `npm run lint`, `type-check`, `next build`, `npm audit` 0건,
  Windows Playwright e2e 14/14 passed.

## 2026-05-31 (codex) — Windows Git 기준 개발 환경 명시 보강

**작업**: 사용자 지시 "windows git 사용 환경으로 명시"에 따라 NTFS worktree를
Git source of truth로 쓰고, WSL은 테스트/실행용 ext4 샌드박스로만 동기화한다는
정책을 entry 문서 전반에 명확히 반영함.

- `README.md`, `SKILL.md`, `CLAUDE.md`, `docs/agent-guide.md`: 기존 WSL ext4
  원본 문구를 Windows Git(`git.exe`) + NTFS worktree 기준으로 수정.
- `docs/dev-environment.md`: 제목과 본문 첫 정책 설명에 Windows Git 원본 +
  WSL 실행 모델을 명시.
- `AGENTS.md`, `docs/codegraph-worktree.md`: 남아 있던 `~/dev/krtour-map-*`
  예시를 `F:\dev\python-krtour-map-*` 기준으로 정리.

## 2026-05-31 (antigravity) — 개발 정책 NTFS 메인레포 전환 및 에이전트 워크트리 재설정

**작업**: 개발 및 형상관리의 중심을 WSL ext4에서 NTFS(`F:\dev\python-krtour-map`)로 전면 이전함. WSL ext4는 가상/컨테이너 가속 테스트(PostGIS testcontainers) 실행을 위한 **샌드박스**로 역할을 재규정함. 이에 따라 에이전트별 worktree를 NTFS상에 신설 및 프리픽스를 `python-krtour-map-`으로 개정하고 로컬 키값(`.env`)을 동기화 완료함. 정책 관련 문서 3종을 전면 정비하여 PR#110 머지 완료.

- **산출물**:
  - `python-krtour-map-codex` (worktree): F:\dev\ 하위에 `sandbox/codex` 브랜치로 신설 및 `.env` 키값 복사.
  - `python-krtour-map-claude` (worktree): F:\dev\ 하위에 `sandbox/claude` 브랜치로 신설 및 `.env` 키값 복사.
  - `python-krtour-map-antigravity` (worktree): F:\dev\ 하위에 `sandbox/antigravity` 브랜치로 신설 및 `.env` 키값 복사.
- **문서 및 설정 개정**:
  - `AGENTS.md`, `docs/dev-environment.md`, `docs/codegraph-worktree.md` 정책 문서 개정 (NTFS 메인레포 & WSL ext4 복사 테스트 전략 구체화 및 워크트리 프리픽스 반영).
  - 메인 레포 및 에이전트 워크트리별 MCP 설정 파일 (`antigravity.json`, `claude.json`, `.codex/config.toml`, `.gemini/mcp.json`)의 `codegraph.cwd` 를 새로운 워크트리 명명 경로로 정합성 보정.
- **배포 및 통합**:
  - `chore/ntfs-policy-transition` 브랜치 생성 후 GitHub `gh` CLI 도구를 사용하여 PR#110 생성 및 main 브랜치 Squash merge 완료.

## 2026-05-31 (antigravity) — maplibre-vworld-js 스타일 및 MCP 설정 동기화

**작업**: 사용자 지시에 따라 `maplibre-vworld-js` 프로젝트의 스타일(`react-doctor.config.json`) 및 에이전트별 MCP 설정 파일(`.gemini/mcp.json`, `antigravity.json`, `claude.json`, `.codex/config.toml`)을 가져와서 현재 프로젝트의 worktree 경로(`F:\dev\krtour-map-*`)에 맞춤 보정 후 적용. PR #107 생성 후 성공적으로 머지 및 리모트/로컬 동기화 완료.

- **산출물**:
  - `react-doctor.config.json` (프로젝트 루트): React 정적 분석 규칙 및 스타일 일관성 검사 예외 설정 복사.
  - `.gemini/mcp.json` (새로 생성): Antigravity 에이전트용 `codegraph` (`cwd: F:\\dev\\krtour-map-antigravity`), Playwright, Sequential Thinking MCP 서버 등록.
  - `antigravity.json` (프로젝트 루트): Antigravity용 MCP 구성 동기화.
  - `claude.json` (프로젝트 루트): Claude Code용 `codegraph` (`cwd: F:\\dev\\krtour-map-claude`) 등 MCP 설정 동기화.
  - `.codex/config.toml` (프로젝트 루트): Codex용 `codegraph` (`cwd: F:\\dev\\krtour-map-codex`) 등 MCP 설정 동기화.
- **배포 및 통합**:
  - `chore/sync-mcp-style` 브랜치 생성 및 형상관리 추가.
  - GitHub `gh` CLI 도구를 사용하여 PR#107 생성 후 Squash merge 및 원격 main 브랜치 머지 완료.

## 2026-05-31 (antigravity) — agent별 MCP 서버 설정 파일 추가 및 형상관리

**작업**: 사용자 지시에 따라 `claude code`, `gpt codex`, `antigravity` 각 에이전트의 MCP 설정 파일을 작성 및 형상관리(git)에 추가하고, PR 생성 및 메인 브랜치 머지까지 성공적으로 수행함.

- **산출물**:
  - `claude.json` (프로젝트 루트): Playwright 및 Sequential Thinking MCP 서버 설정 등록.
  - `antigravity.json` (프로젝트 루트): Playwright 및 Sequential Thinking MCP 서버 설정 등록.
  - `.codex/config.toml` (프로젝트 루트): Codegraph, Playwright 및 Sequential Thinking MCP 서버 설정 등록.
- **배포 및 통합**:
  - `chore/agent-mcp-configs` 브랜치 생성 및 형상관리 추가.
  - GitHub `gh` CLI 도구를 사용하여 PR#105 생성.
  - PR 승인 및 `main` 브랜치로의 squash merge 완료.

## 2026-05-30 (claude) — Sprint 3 종료 회고 + Sprint 4 진입 준비 (4a/4b 분할 채택)

**작업**: 사용자 지시 "스프린트4 진입 전 단계까지 진행" — Sprint 3 종료 게이트
일괄 정리 + Sprint 4 진입 조건 충족 표기 + 4a/4b 분할 결정.

- `pyproject.toml`: `[tool.coverage.report] fail_under = 65 → 75` (ADR-032 Sprint 3
  bar). 실측 92.66%로 무위험 상향(unit 599 통과).
- `docs/sprints/SPRINT-3.md` §6 종료 조건 7개 모두 ☑ 또는 ~(deferred): provider
  ⑤⑥ merge / ADR-033 Phase 1 green / consistency 적재(Dagster 트리거는 Phase 2
  Sprint 5로 묶음) / dedup_review_queue 첫 운영 안정 / coverage 75 / 회고 entry /
  Sprint 4 진입 PR 준비.
- `docs/sprints/SPRINT-4.md` §1 진입 조건 6개 모두 ☑ 표기 + §3 **4a/4b 분할
  채택** 결정 명시. 분할 사유: MOIS 4단계 한 sprint risk(bulk 시간 + dedup queue
  폭증) + dedup 룰 false-positive 측정 자연 인큐베이션 + coverage 80% 도달
  단계 분리.
- `docs/sprints/README.md`: Sprint 3 상태 → ✅ 완료(PR#60~#95) / Sprint 4 상태
  → 🟡 진입 준비 완료(4a/4b) / 현 위치 노트 2026-05-30로 갱신.

**Sprint 3 정리(이 sprint에 머지된 핵심)**:
- Provider ⑤ KNPS(point + geometry + CSV preview) / ⑥ krheritage(place/area/event
  + media file_sources + 측지 면적).
- DB 적재: `infra/feature_repo.py` raw SQL 3-table upsert / `infra/dedup_repo.py`
  + `ops.dedup_review_queue` / `AsyncKrtourMapClient` 오케스트레이터.
- Core: `find_dedup_candidates` 순수 함수(ADR-016 cross-score) /
  `geometry_area_square_meters` 측지 면적 / `consistency.py` F1~F3.
- 데이터 통로: geocoding **python API → REST API v2** 전환(httpx 주입,
  TYPE_CHECKING-only) — kraddr-geo DB/패키지 의존 0.
- Frontend & 검증: `/features` 지도(maplibre + Zustand viewport + bbox refetch) /
  Windows Playwright e2e **9/9 통과**(WSL frontend↔backend, npm workspace 루트
  확립) / **frontend CI 게이트**(type-check + next build) + `etl/page.tsx` 잠복
  `*/` 주석 버그 검출+수정.
- 거버넌스: docs 일괄 정합(`address-geocoding.md` REST API v2 + vworld level
  매핑 표) + CHANGELOG Sprint 3 섹션 + journal 2 entry.

**다음(Sprint 4 진입 PR)**: 4a 첫 작업 — MOIS Step A(bulk) provider 모듈 + 첫
적재. 가중치 조정 후보 측정을 위한 dedup queue 모니터링 패널(`/dedup`?) 후속.

## 2026-05-30 (claude) — Debug UI WSL+Windows Playwright e2e + frontend CI 게이트 (#117 마무리)

**작업**: 사용자 지시 "frontend도 WSL에서 돌고 Playwright만 Windows에서 구동" →
debug UI 전체를 WSL에서 띄우고 Windows Playwright로 라이브 e2e를 7/7 통과시킴.
그 과정에서 잠복 버그 검출+수정.

- **PR#92 — workspace 루트 + frontend WSL 기동 + 라이브 e2e + 버그 fix**: 저장소에
  npm workspace 루트가 없어 frontend가 한 번도 install된 적 없었다. 루트
  `package.json`(workspaces: map-marker-react + debug-ui/frontend) 신설 + frontend
  `"@krtour/map-marker-react": "workspace:*"`(pnpm/yarn 문법) → npm 호환 `"*"`.
  `npm install` 419 pkgs(github `maplibre-vworld#v0.1.0` 포함) 성공. WSL backend(:8087)
  + frontend(:8610, `--hostname 0.0.0.0`) 기동 → Windows `.e2e-win`(gitignored
  scratch — node_modules 플랫폼 충돌 회피)에서 `@playwright/test` 1.60.0 +
  chromium → `npx playwright test` → **7/7 통과**(home 4 + etl 3, 실 backend 연동).
  🐞 **검출+수정**: `etl/page.tsx` JSDoc 주석의 `` `/debug/etl/*/preview` ``에서
  `*/`가 블록 주석을 조기 종료해 빌드 실패(PR#44 이후 잠복, frontend 미컴파일로
  미검출). 주석을 `/debug/etl/{provider}/{dataset}/preview`로 수정 → 정상 빌드.
  WSL `/mnt/f`(NTFS) inotify hot-reload가 파일 수정을 놓쳐 `.next` 클린 + dev
  재시작 필요했던 점도 리포트에 기록.
- **PR#91 — Playwright e2e 스위트 + backend 라이브 검증 리포트**: `playwright.
  config.ts` + `e2e/home.spec.ts`/`etl.spec.ts` (실 backend 연동, role/heading +
  native select nth 선택자). `docs/reports/debug-ui-e2e-2026-05-29.md`에 backend
  5경로 실 HTTP 통과 증거 + 사람용 런북.
- **PR#93 — frontend CI 게이트**: `.github/workflows/frontend.yml` (Node 20 +
  workspace `npm install` + `tsc --noEmit` + `next build`, paths 필터). PR#92
  회고에 따라 잠복 syntax/타입 오류를 PR 머지 전에 차단. 로컬 검증: type-check ✓ /
  next build ✓ (13.5s, 5 static pages).

**다음**: 지도 캔버스(`/features/*` + maplibre-vworld) 도입 — (c).

## 2026-05-29 (claude) — DB 적재 오케스트레이션 + cross-provider dedup + geocoding REST (#120~#123)

**작업**: 사용자 지시 시퀀스 — krheritage 후속 마지막(#120) + SPRINT-3 §2.5 dedup
큐(#121/#122) + kraddr-geo 호출 python API → REST API v2 전환(#123). 5 PR 머지.

- **PR#86 (#120) — `geometry_area_square_meters` 측지 면적**: `pyproj.Geod
  (ellps='WGS84').geometry_area_perimeter` 측지 면적 helper + krheritage AREA
  변환기가 `AreaDetail.area_square_meters` 채움. test_core_geometry +4건.
- **PR#87 (#121) — `core/dedup.py` cross-provider 후보 탐지**:
  `find_dedup_candidates(left, right, *, include_auto_merge)` 순수 함수 —
  `core.scoring.score_pair`(ADR-016)로 cross-score, KEEP_SEPARATE 제외, score
  내림차순. `DedupInput` Protocol(`Feature`가 그대로 만족) + `DedupCandidate`
  frozen dataclass(score + decision + 성분 점수). test_core_dedup 6건.
- **PR#88 (#122) — `ops.dedup_review_queue` + `infra/dedup_repo.py`**: alembic
  0005 (UUID PK, FK→features CASCADE, NUMERIC(5,2) 0~100 score, `uq_dedup_pair`,
  `ck_dedup_scores`/`ck_dedup_status`, `idx_dedup_status_score`). 점수 0.0~1.0 →
  0~100 변환, **검토완료 행 보존 upsert**(`DO UPDATE ... WHERE status='pending'`).
  integration 5(testcontainers).
- **PR#89 (#122) — `AsyncKrtourMapClient` 오케스트레이터**: placeholder 진입점에
  transaction 소유 메서드 — `load_feature_bundles`(`infra.load_bundles` 래핑),
  `sync_dedup_candidates`(`core.dedup` + `infra.enqueue_dedup_candidates`), 읽기
  (`get_feature`/`features_in_bounds`/`pending_dedup_reviews`). engine 수명은
  호출자 소유 (`__aexit__`는 dispose X). unit 2 + integration 3(teardown TRUNCATE).
- **PR#90 (#123) — geocoding python API → REST API v2 전환**: 기존 geocoding은
  in-process `AsyncAddressClient.reverse_v2/geocode_v2`를 가정했으나, 그 메서드는
  현 kraddr-geo에 **존재하지 않음**(미존재). 실제 REST API(`/v1/address/*`,
  ServiceMeta ver 2.0)에 맞춰 재작성. structural Protocol을 실제
  `ReverseResponse`/`GeocodeResponse`/`AddressStructure`(vworld 호환 levels —
  `level4LC=bjd_cd` 등)/`GeocodeExtension`으로 교체. 순수 변환
  `reverse_response_to_address` / `geocode_response_to_coordinate` + 새
  `KraddrGeoRestClient`(httpx **주입**, TYPE_CHECKING-only import — 메인 패키지
  런타임 httpx 의존 X). 소비자 계약(`ReverseGeocoder`/`AddressGeocoder`/
  `cached_reverse_geocoder`) 유지 → provider 무영향. `KRTOUR_MAP_KRADDR_GEO_BASE_URL`
  설정 추가. test_geocoding 21건(fake dataclass + `httpx.MockTransport`).

검증: ruff / mypy --strict(49 src files) / unit 599 / integration 11 +
lint-imports 4 contracts 모두 green. main 5개 PR fast-merge 적용 (no CI wait).

**다음**: #117 라이브 e2e 실행 (다음 entry).

## 2026-05-29 (claude) — FeatureFileSource DTO + krheritage 미디어 file_sources (#119)

**작업**: krheritage 후속 1/3 — 미디어 파일 참조 DTO.

- `dto/file.py` 신규 `FeatureFileSource` (docs/feature-files-rustfs.md §2.2 — 업로드
  전 입력: feature_id/source_url/role/display_order/file_type/content_type/
  alt_text/provider/dataset_key/source_record_key/payload). `FileRole`/`FileType`
  Literal. dto/__init__ export.
- `FeatureBundle.file_sources: list[FeatureFileSource]` 필드 추가(기본 빈 list) +
  validator에 file_sources[].feature_id ↔ feature.feature_id FK 검증.
- `krheritage`: `KrHeritageItem.image_url` / `KrHeritageEvent.main_image` Protocol
  property 추가 + `_image_file_sources` helper → heritage/event bundle이 대표
  이미지를 role='primary' file_source로 변환 (getattr로 기존 fixture 호환).
- 테스트: `test_dto_file.py`(6) + krheritage file_sources 3 + item/event fixture에
  image 필드. 589 unit / cov 93.75% / ruff / mypy strict / import-linter 4 /
  openapi drift 0 (FeatureBundle는 preview가 dict라 spec 무영향).

**다음**: #120 area_square_meters (krheritage AREA 면적 GIS 보강).

## 2026-05-29 (claude) — Provider ⑥ krheritage (국가유산 place/area/event, ADR-034 8단계)

**작업**: 사용자 "krheritage 진행". `src/krtour/map/providers/krheritage.py` 신설.
`docs/krheritage-feature-etl.md` + SPRINT-3 §2.2 사양 구현.

**설계**: krheritage-api 미설치 → knps/datagokr와 동일하게 **structural Protocol**
입력(`KrHeritageItem`/`KrHeritageEvent`), krheritage import 안 함(ADR-006). PR#83
패턴 따라 변환 함수 **async + reverse_geocoder**(feature_id 전 bjd_code 보강, ADR-009).
- `classify_heritage_kind(item)` — ccba_kdcd로 place/area (13/16 사적·명승→area,
  15 천연기념물→경계 있으면 area 없으면 place, 그 외 place).
- `resolve_heritage_category(item)` — 명칭/유형 키워드 우선(사찰 01070100 / 궁궐·왕릉
  01070200 / 한옥·민속 01070400 / 사적·명승 01070300) + 15→01020400(자연) +
  미분류 01070000. maki override(religious-buddhist/castle/village/monument), P-07.
- `heritage_items_to_bundles` — place/area. area + geom_wkt이면 normalize_geometry
  (AREA_GEOMETRY_TYPES) → Feature.geom + centroid 좌표; 불량 WKT면 좌표 fallback.
  PlaceDetail/AreaDetail(area_kind heritage_area/natural_heritage_area). 자연키
  ccbaKdcd-ccbaAsno-ccbaCtcd.
- `heritage_events_to_bundles` — EventDetail(event_kind=heritage_event,
  content_id=sn), category 01070000. 자연키 sn.
- 소재지 텍스트는 reverse 결과에 legal 보강(`_merge_address`).

**범위 밖(후속)**: 미디어 file_sources(FeatureFileSource DTO 미구현, bundle.py
주석 처리) / GIS spca 면적 보강(area_square_meters) / knps 사찰↔temple dedup(§2.5).

**검증(로컬)**: 단위 25건 추가 → unit+lint **581** / ruff / mypy --strict
(-p krtour.map, 46 files) / import-linter 4 kept / coverage gate green.

**다음**: GIS 면적 보강 + dedup_review_queue(§2.5) 또는 실 DB 적재 오케스트레이션.

## 2026-05-29 (claude) — 적재 자동 보강 wiring: provider 변환기 전면 async + geocoder 주입

**작업**: 사용자 "knps 재검토 + kraddr geo v2 연동" 후속으로 "적재 자동 보강
wiring" 선택 → 진행 중 "모두 async로 구현" 지시. 두 결정 반영.

**핵심 제약**: `feature_id = f_{bjd_code or 'global'}_...` (ADR-009) — bjd_code가
feature_id에 박히므로 역지오코딩은 **feature_id 계산 전**에 끝나야 한다. 사후
보강은 불가('global' bucket 고정). + kraddr-geo v2는 async(`reverse_v2`).
→ 결론: provider 변환 함수를 async로 만들어 feature_id 직전 `await`.

**설계 (사용자 승인: 사전해소 → 전면 async)**:
- `geocoding.cached_reverse_geocoder(geocoder, *, precision=6)` — 좌표 양자화
  메모이즈 async wrapper (중복 좌표 1회 호출, None도 캐싱). (초기 sync
  `ReverseLookup`/`build_reverse_lookup` 설계는 "모두 async" 지시로 폐기.)
- **provider 변환 함수 전면 async화** + `reverse_geocoder: ReverseGeocoder | None`
  주입: standard_data(festival) / opinet(stations) / krex(rest_areas·notices) /
  knps(point·geometry·CsvPreview 브리지). 각자 cached_reverse_geocoder로 래핑 후
  feature_id 전에 await해 Address(bjd_code 등) 채움. geometry는 centroid 역지오.
- standard_data의 bespoke sync `ReverseGeocoder`/`ReverseGeocodeResult` Protocol
  제거 → geocoding의 async `ReverseGeocoder`로 통일 (krex/opinet도 이 import로
  교체, `.admin_address`→Address `.admin`).
- knps Feature에 `address=address or Address()` (Feature.address는 non-optional).

**테스트**: 단위 테스트는 sync ergonomics shim(`asyncio.run`)으로 기존 호출처
보존; geocoder fake는 async 콜러블(→Address)로 교체. 통합/debug-ui adapter
테스트는 `async def`+`await` (asyncio_mode=auto). debug-ui `etl_fixtures`
(`_convert_*`/`run_fixture_preview`) + `etl_live` + route도 async 전파.
geocoding cached_reverse_geocoder 테스트 2건 추가.

**검증(로컬)**: main unit+lint **556** / debug-ui **79** / ruff / mypy --strict
(-p krtour.map, 45 files) / import-linter 4 kept / openapi --check 0 green.

**경계**: kraddr-geo client 수명·실제 호출은 호출자(TripMate/Dagster). 본 lib는
async 변환 + geocoder 주입 지점까지. DB write(적재) 경로는 여전히 feature_repo.

**다음**: provider ⑥ krheritage 또는 실 DB 적재 오케스트레이션.

## 2026-05-29 (claude) — KNPS provider 재검토 + kraddr-geo v2 함수 연동(`krtour.map.geocoding`)

**작업**: 사용자 요청 "knps api 프로바이더 재검토 + kraddr geo v2 함수 연동 구현".

**① KNPS 재검토 (코드 변경 없음 — 정상 확인)**: 설치된 `python-knps-api` 0.1.0
소스 직접 대조.
- `FileArtifact`(dataset_key/data_go_id/kind/size_bytes/members/csv_previews) +
  `CsvPreview`(member_name/encoding/headers/rows) + `CsvPreviewRow`(values/
  extra_fields, `.as_dict`) — 내 CsvPreview 브리지 Protocol과 1:1 일치 (실제
  객체로 동작 재확인).
- `files.download_artifact(key, *, preview_rows=N, max_bytes=None) → FileArtifact`.
  `artifacts.py`의 `rows[1:1+preview_rows]` 확인 → preview_rows 크게 = 전 행.
  내 docs 예시 정확. geometry/SHP 파싱 여전히 미구현(knps-api 책임, Amendment I).
- 결론: KNPS provider + CsvPreview 브리지 정합. 재검토發 코드 수정 없음.

**② kraddr-geo v2 함수 연동 — `krtour.map.geocoding` 신설**: kraddr-geo가
이 환경에 없어 GitHub raw로 v2 API 전수 확인:
- client(`AsyncAddressClient`) v2 메서드: `reverse_v2(lon,lat,*,radius_m,...)`
  → `ReverseV2Response`, `geocode_v2(*,road_address,jibun_address,sig_cd,bjd_cd,
  limit,...)` → `GeocodeV2Response`. `open_client(pg_dsn=...)`. v2는 PostgreSQL
  DSN 기반(v1 sqlite store 폐기).
- 응답 DTO: `*V2Response`(status: "OK"/"NOT_FOUND"/"ERROR", candidates:
  tuple[CandidateV2]), `CandidateV2`(confidence/address/point/region/...),
  `RegionV2`(sig_cd/bjd_cd/sido/sigungu/admin_dong/...), `AddressV2`(road_address/
  parcel_address/postal_code/legal_dong_code/admin_dong_code/road_name_code/...),
  `Point`(x=lon,y=lat).
- 구현: kraddr-geo를 import하지 않고 **structural Protocol**로 소비(ADR-006,
  knps/datagokr 패턴 동일). 순수 변환 함수 `reverse_v2_to_address`(최고 confidence
  후보 → Address, 자릿수 틀린 코드는 None으로 떨궈 validator 거부 회피) /
  `geocode_v2_to_coordinate`(point 보유 최고 후보 → Coordinate). 비동기 콜러블
  팩토리 `kraddr_geo_reverse_geocoder`/`kraddr_geo_address_geocoder`(client는
  `KraddrGeoClient` Protocol, 수명은 호출자). async 타입 별칭 `AddressGeocoder`/
  `ReverseGeocoder`(docs §2).
- import-linter layers에 `krtour.map.geocoding`(providers↔infra 사이) 추가.
- 테스트 17건(매핑/confidence/fallback/잘못된코드/status/팩토리). 실제 kraddr-geo
  없이 fake v2 응답으로 검증. `KraddrGeoClient` Protocol 구조 적합성도 mypy 확인.

**검증(로컬)**: unit+lint **554** / ruff / mypy --strict(-p krtour.map, 45 files) /
import-linter 4 kept green.

**경계**: 데이터 정합성 1차 책임은 kraddr-geo(ADR-044). 본 모듈은 v2 응답 신뢰·
미러. standard_data의 sync `ReverseGeocoder`(lookup table용)와 본 모듈 async
콜러블은 별개. 적재 파이프라인 자동 보강 wiring은 후속.

**다음**: 적재 함수에 geocoder resource 자동 보강(§7) 또는 provider ⑥ krheritage.

## 2026-05-29 (claude) — KNPS CsvPreview → FeatureBundle 브리지 (knps-api DTO 직접 소비)

**작업**: 사용자 요청 "knps api 다시 확인해서 프로바이더 구현". knps-api 소스 전수
재확인(catalog/models/files/artifacts) 결과:
- knps-api는 CSV를 `CsvPreview`(headers + `CsvPreviewRow.as_dict`)로 파싱 제공
  (`download_artifact(preview_rows=N)`, N 크게 주면 전 행). **geometry/SHP 파싱은
  미구현**(자체 testing.md "planned", knps-api.md "parser가 WGS84+geometry 노출").
- 실제 feature dataset CSV 컬럼명은 어디에도 없음(소스/테스트/문서). live 확인은
  이 환경 data.go.kr 차단(403 allowlist). → 사용자 결정: "브리지 + 추정 컬럼
  기본값(검증 필요 표기)".

**구현(`providers/knps.py`)**: knps를 import하지 않고 structural Protocol로 소비.
- `KnpsCsvRow`/`KnpsCsvPreview` Protocol (knps-api `CsvPreviewRow`/`CsvPreview`와
  구조 일치 — 실제 객체로 동작 확인).
- `KnpsPointColumnMap`/`KnpsGeometryColumnMap` + best-guess 기본 후보맵
  (`KNPS_DEFAULT_*_COLUMN_MAP`, 경도/위도/명칭/관리번호/WKT 한·영 후보, ⚠️VERIFY).
- `knps_csv_preview_to_point_bundles` / `knps_csv_preview_to_geometry_bundles` —
  행 dict에서 첫 매칭 컬럼 추출 → 기존 `knps_*_records_to_bundles` 재사용.
  좌표 없으면 coord=None, id 컬럼 없으면 행 해시 fallback, geom 없으면 skip.
  `column_map` 인자로 override.

**검증(로컬)**: unit+lint 537(+9), ruff/mypy --strict/import-linter green. 실제
knps-api `CsvPreview`(`knps.models`)가 브리지 Protocol 만족함을 직접 확인.

**경계 재확인**: geometry/SHP 파싱은 여전히 knps-api 책임(ADR-028 Amendment I).
본 브리지는 knps-api가 현재 제공하는 CSV preview를 잇는 현실 경로.

**다음**: live 컬럼명 확정(별도 환경/세션) 또는 provider ⑥ krheritage.

## 2026-05-29 (claude) — KNPS 최신 재검토: 국립공원 경계 category + route/area maki 정정

**작업**: 사용자 요청 "knps api 최신으로 읽어서 다시 검토". knps-api 최신 HEAD =
`06da125f`(내가 핀한 것과 동일, upstream 변경 없음) 소스를 직접 clone해 catalog/
models/files API + upstream `docs/knps-feature-etl.md §4` 표 대조.

**확인**: 14 dataset의 key/geometry_type/feature_kind/formats가 내 `KNPS_*_DATASETS`
와 1:1 일치. place 5건의 maki는 `get_category().mapbox_maki_icon`이 upstream 표와
완전 일치(information/toilet/campsite/shelter/religious-buddhist/monument). `files`
API는 download(bytes)/inspect_bytes/download_artifact(preview)만 — record/geometry
파싱 없음 → Amendment I(파싱=knps-api 책임, upstream PR 필요) 재확인.

**정정(upstream §4 대조로 발견한 내 오류)**:
- `knps_park_boundaries`: category를 sentinel `00000000`로 잘못 둠 → upstream은
  실제 `01020101`(국립공원 경계도 관광 category 보유) + maki `park`. 수정.
- `knps_trails`/`knps_linear_facilities`: maki가 기본 "marker" → upstream `park`. 수정.
- hazard/protected는 category 없음 + barrier 유지(정확). place 5건 무변경(이미 정합).
- 변경 파일: `providers/knps.py`(spec + 상수 `_NATIONAL_PARK_CATEGORY`/`_PARK_MAKI`),
  `knps-feature-etl.md §3.1/§4` 표, 테스트(park=01020101/park maki assert + place
  maki parity parametrized 4건).

**검증(네이티브 PostGIS)**: unit+lint 528, 통합 feature_repo 6/6, ruff/mypy/
import-linter green.

**주의**: park_boundaries의 feature_id가 category 변경으로 달라짐 — 아직 적재 전
(Sprint 3 미실행)이라 영향 없음.

## 2026-05-29 (claude) — KNPS SHP/CSV 파싱 책임 = knps-api 확정 (ADR-028 Amendment I)

**결정(사용자)**: "knps shp 로딩은 knps-api 에서 진행하는게 맞음." → ADR-028 §B
에서 Sprint 2로 연기됐던 "SHP/GeoJSON parsing 위치"를 **knps-api 책임**으로 확정
(ADR-044 — 파싱·정합성 1차 책임은 provider 라이브러리). raw 파일(SHP ZIP/CSV) →
typed record(좌표·geometry WKT 4326) 변환은 knps-api에서, 본 lib는 record
Protocol로 소비만.

**본 lib 코드 변경 없음** — PR#77/#78의 변환 함수가 처음부터 WKT/좌표 입력
(`KnpsPointRecord`/`KnpsGeometryRecord`)이라 설계가 이미 정합. 문서/주석만 정정:
- `decisions.md` ADR-028 — Amendment I 추가 + §G 모순 문구(SHP 본 lib 책임) 정정.
- `knps-feature-etl.md §5` — 파싱 책임 knps-api로 flip + 구현된 함수 시그니처로
  교체(raw_bytes stub 제거). `providers/knps.py` 모듈 docstring 정정.
- `tasks.md`/`resume.md` — SHP parser 위치 open item 해소 표기.

**검증**: ruff/mypy(knps.py docstring only) green, 코드 무변경이라 테스트 영향 없음.

**다음**: provider ⑥ krheritage (ADR-034 8단계). knps-api record 파싱 API
(`parse_records`)는 Sprint 3 적재 직전 upstream PR.

## 2026-05-29 (claude) — KNPS geometry(route/area) 파서 + Feature.geom (Sprint 3)

**작업**: KNPS route(LINESTRING)/area(POLYGON) dataset 변환. Point/place(PR#77)에
이은 KNPS 2단계. geometry는 WKT(4326)로 `Feature.geom`(신규 필드) + `features.geom`
컬럼에 저장, centroid를 `coord`로 (ADR-012 지도 마커용).

- `core/geometry.py` (신규) — shapely 기반 순수 함수: `parse_wkt`(type 검증) +
  `geometry_centroid`(한국 경계 검증) + `normalize_geometry`. `GeometryError`.
  ROUTE/AREA_GEOMETRY_TYPES 집합. core→dto import (layers 정합).
- `dto/feature.py` — `Feature.geom: str | None`(WKT, 4326) 필드 추가.
- `infra/feature_repo.py` — INSERT에 geom 컬럼 추가 (`x_extension.ST_GeomFromText`
  + ST_SetSRID 4326, ADR-008 함수 한정). ON CONFLICT에도 geom 갱신.
- `providers/knps.py` — `KnpsGeometryRecord` Protocol(WKT 입력) +
  `KNPS_GEOMETRY_DATASETS` 5건(trails/linear_facilities=route, park_boundaries/
  hazard_zones/protected_areas=area) + `knps_geometry_records_to_bundles`. route는
  category 01020103, area는 sentinel 00000000(트리 밖, area_kind로만 식별). 파싱
  실패/경계밖/type불일치 행은 skip. SHP→WKT 디코딩은 호출자/파서 책임(Protocol).
- `pyproject.toml` — shapely mypy override(stub 없음, import-untyped 무시).
- 테스트: 단위 `test_core_geometry.py`(10) + knps geometry(18 추가) + 통합
  geom 적재(POLYGON SRID 4326 확인) 1.

**검증(네이티브 PostGIS)**: 통합 22/22, unit+lint 524, ruff/mypy --strict/
import-linter(4 kept) green.

**다음**: KNPS SHP bytes→WKT 파서(pyshp, park_boundaries) 또는 provider ⑥ krheritage.

## 2026-05-29 (claude) — Provider ⑤ KNPS Point/place 변환 (Sprint 3, ADR-034 7단계)

**작업**: `python-knps-api`(06da125f, GitHub에서 설치 가능 확인) 실제 catalog/model을
근거로 `providers/knps.py` 구현. ADR-006(wrapper 금지) — knps-api public 직접 사용,
본 모듈은 순수 변환 함수.

- knps-api 실측: `file_datasets()` 14건, `FileDataset.geometry_type`/`feature_kind`
  필드로 Point/place 5건(visitor_centers/restrooms/campgrounds/shelters/
  cultural_resources) 확인.
- `providers/knps.py` — `KnpsPointRecord` Protocol(파싱된 행 입력) +
  `KNPS_PLACE_DATASETS` spec(category/place_kind/marker, knps-feature-etl.md §4
  검증표) + `knps_point_records_to_bundles` + cultural_resources subtype 분기
  (`resolve_cultural_resource_category`: 사찰→01070100/유적→01070300/기타→01070000).
  category→maki는 `get_category().mapbox_maki_icon`. SourceRole.PRIMARY.
- 좌표는 WGS84 `Coordinate`(한국 경계 밖/None은 coord=None). 결정적 ID(ADR-009).
- **SHP(area)/LineString(route) parsing은 후속** — pyshp+shapely 필요. 미지원
  dataset_key는 명시적 KeyError.
- CSV 디코딩/컬럼 추출은 호출자/파서 책임(Protocol 입력) — 변환 함수는 좌표계·
  category·DTO 조립에 집중(테스트 용이). 다른 provider처럼 본 lib 본 의존 X.
- 테스트 `tests/unit/test_providers_knps.py` 18건(매핑/subtype/좌표/결정성/FK/미지원).

**검증(로컬 venv)**: unit+lint 504 passed(+18), ruff/mypy --strict/import-linter
(4 kept) green. DB 무관(순수 변환)이라 통합 테스트 불필요.

**다음**: KNPS SHP/route geometry parser 또는 provider ⑥ krheritage.

## 2026-05-29 (claude) — 문서 정리 리포트 §2.2/§2.3 후속 (문서만)

**작업**: docs-consistency-sweep 리포트의 남은 2건을 문서 정리로 해소 (코드 무수정).

- **§2.2** `data-model.md §4 provider_sync_state` — 초기 설계(metadata_hash /
  last_attempt_at / last_full_scan_at / last_error / extra 등)를 실제 구현 스키마
  (last_failure_at / consecutive_failures + status CHECK)로 교체. 제외 컬럼은
  "후속 후보 (미구현)" 주석으로 명시. index도 `(next_run_after)`로 정합.
- **§2.3** `postgres-schema.md §8.4` 명명 규약 — 미사용 `YYYYMMDDhhmm` 예시를 실제
  컨벤션 `NNNN_<descriptive>.py`(파일명≠revision id 허용, 4건 실례)로 갱신.
- 리포트 §2.2/§2.3 "해소" 표기.

코드/스키마 무변경 — 문서가 구현 현실을 정확히 반영하도록 정렬만.

## 2026-05-29 (claude) — source_role CHECK 정합 (문서 정리 리포트 §2.1 후속 코드 수정)

**작업**: 문서 정리(PR#74) 리포트 §2.1에서 발견한 코드 레벨 잠재 버그 수정.
`source_links` CHECK가 DTO `SourceRole` enum과 불일치 → DTO로 BASE_ADDRESS 등
적재 시 DB CHECK 위반 가능했음.

- 정본 확인: DTO `_enums.SourceRole` = `feature-model.md §3` = `data-model.md`
  (primary/base_address/base_coordinate/enrichment/correction/duplicate_candidate/
  media/weather_context). `geocoded`/`phone`/`observation`/`external_link`(0002
  CHECK)는 코드/테스트/문서 어디에도 미사용 → 잘못 들어간 값.
- `infra/models.py` `ck_source_links_role` CHECK를 정본 8종으로 교체.
- alembic `0004_fix_source_links_role_check` — 기존 DB CHECK를 ALTER(drop+create).
  기존 데이터는 primary/enrichment만이라 위반 없음. downgrade는 0002 값 복원.
- 회귀 테스트 `tests/integration/test_source_role_check.py` — 8 enum 값 전부 INSERT
  가능 확인.

**검증(네이티브 PostGIS)**: 통합 21/21, unit+lint 486, ruff/mypy --strict green.
alembic upgrade/downgrade/re-upgrade(0004↔0003) round-trip OK. head 단일.

## 2026-05-29 (claude) — 문서 정합성 정리 (PR#69~#73 머지 후 drift sweep)

**작업**: Sprint 3 코드 머지(ADR-033 Phase 1 + feature_repo + /features 라우터)
이후 전체 문서를 재검토(Explore 에이전트 3대 병렬 → 실제 소스로 재검증)하고
코드와의 충돌·drift·누락을 문서 정리. **코드 무수정**.

- **포트 drift**: debug-ui 기본 포트 8600 → 8087 정정 (16곳/6파일 — architecture/
  debug-ui-package/backend-package/standard-data-feature-etl/tripmate-integration/
  README). journal 역사 기록은 보존.
- **구현 현황 동기화**: architecture §4 엔드포인트(구현됨 vs 예정 구분), debug-ui-
  package §6 구현 현황 블록, §4 settings 실제 필드 반영, backend-package
  AsyncKrtourMapClient "설계 단계" 주석, README 빠른시작 제목.
- **신규 테이블 문서화**: data-model §9.7 `ops.feature_consistency_reports`(ADR-033
  Phase 1) 추가 + §9.5 data_integrity_violations "미구현(계획)" 표기.
- **테스트 경로**: test-strategy §5 e2e → `packages/krtour-map-debug-ui/tests/`.
- **ADR 현황**: agent-guide/CLAUDE/AGENTS "027~034 proposed"·"다음 후보 044" →
  "001~044 accepted, 다음 후보 045" + 030~033/Phase 1 반영.
- 요약 리포트: `docs/reports/docs-consistency-sweep-2026-05-29.md`.

**미수정(코드 범위, 별도 PR 필요)**: ① `source_role` enum 불일치 — DTO/data-model
(base_address 등) ↔ ORM/migration(geocoded/phone 등). DTO로 BASE_ADDRESS 적재 시
DB CHECK 위반 가능(잠재 버그). ② provider_sync_state 컬럼 설계 차이. ③ alembic
0003 파일명↔revision id. 리포트 §2에 기록.

## 2026-05-29 (claude) — debug-ui /features 조회 라우터 (Sprint 3)

**작업**: 적재된 feature를 조회하는 `/features` REST 라우터 (debug-ui, ADR-035).
feature_repo의 raw SQL(ADR-004)을 HTTP 표면으로 노출 — 지도/목록 조회.

- `infra/feature_repo.py` `features_in_bbox` 추가 — bbox(4326) 안 feature 경량
  표현. `coord && ST_MakeEnvelope(...)`로 GIST 인덱스(`idx_features_coord_gist`)
  사용 (ADR-012, 술어에 ST_Transform 없음). `x_extension.` 함수 한정(ADR-008).
  kind 필터(`text[]`) + limit. infra `__init__` export.
- debug-ui `db.py` — `get_session` FastAPI 의존성 (메인 lib `KrtourMapSettings.
  pg_dsn` → async engine, lazy singleton). `set_engine_for_test`/`reset_engine`.
- debug-ui `routers/features.py` — `GET /features`(bbox) + `GET /features/{id}`
  (단건). 경량 `FeatureSummary` / `FeatureDetailResponse`. bbox min>max 422.
- `settings.features_routes_enabled`(기본 True) + app.py wiring + routers export.
- `openapi.json` 갱신(drift gate, ADR-031) — `/features` 2 path + 3 schema.
- 테스트: debug-ui 단위 6(마운트/disable/422/404/매핑, 의존성 override) + 메인
  통합 1(`features_in_bbox` 적재→조회→kind/밖 bbox).

**검증(네이티브 PostGIS)**: 통합 20/20, debug-ui 79, 메인 unit+lint 486,
ruff/mypy --strict/openapi drift(exit 0) green.

**다음**: frontend 지도 wiring(#117 e2e) 또는 provider ⑤ KNPS.

## 2026-05-29 (claude) — infra/feature_repo.py — 첫 DB write 경로 (Sprint 3)

**작업**: `FeatureBundle` → DB 적재 raw SQL repository (ADR-004). provider 변환
결과를 실제로 적재하는 첫 write 경로.

- `infra/feature_repo.py` — `_SQL` 상수 3종(features/source_records/source_links
  upsert) + `get_feature_row` 조회. `upsert_feature`/`upsert_source_record`/
  `upsert_source_link`/`load_bundle`/`load_bundles` + `FeatureLoadResult` dataclass.
- **idempotent**: features/source_links는 `ON CONFLICT DO UPDATE`
  (`RETURNING xmax=0`으로 신규/갱신 구분), source_records는 `DO NOTHING`
  (payload_hash UNIQUE → 이력 보존, ADR-017).
- **ADR-012 준수**: `coord`(4326)만 `ST_SetSRID(ST_MakePoint(lon,lat),4326)`으로
  INSERT, `coord_5179`는 STORED generated라 제외. 술어에 `ST_Transform` 없음.
- commit은 호출자 책임(단위 of work). bulk COPY(ADR-013)는 후속.
- `infra/__init__.py` export + `__all__` 추가.
- 테스트: 단위 `tests/unit/test_infra_feature_repo.py`(param 빌더/집계 6) + 통합
  `tests/integration/test_feature_repo_load.py`(적재/idempotent/coord_5179/FK/조회 4).

**검증(로컬 venv)**: unit+lint 486 passed(+6), mypy --strict OK, ruff OK,
import-linter 4 kept. 통합은 로컬 docker 부재로 skip → CI에서 실행.

**다음**: `/features/*` 조회 라우터(debug-ui) + frontend 지도 wiring, 또는
provider ⑤ KNPS.

## 2026-05-29 (claude) — ADR-033 Phase 1 (T-201a) feature_consistency_reports F1~F3

**작업**: ADR-033 Phase 1 구현 (Sprint 3). 정합성 검사 스키마 + critical 3건 +
관측(Dagster 게이트 미적용).

- `alembic 0003_feature_consistency_reports` — `ops.feature_consistency_reports`
  (report_id `gen_random_uuid()`/batch_id/started_at/finished_at/severity_max
  CHECK/cases JSONB/summary JSONB) + `idx_reports_batch`/`idx_reports_started`.
- `infra/models.py` `FeatureConsistencyReportRow` (target_metadata) + `__all__`.
- `infra/consistency.py` — F1(orphan source_record)/F2(detail-bearing kind인데
  `detail` JSONB 비어있음, ADR-018)/F3(CRS drift, `coord_5179`≠ST_Transform,
  ADR-012) raw SQL(ADR-004) + 순수 집계 `build_report` + `run_consistency_checks`.
  **Dagster 게이트 미적용**(Phase 1=관측). 케이스 확장은 `CONSISTENCY_CASES` 추가.
- 테스트: 단위 `tests/unit/test_infra_consistency.py`(집계) + 통합
  `tests/integration/test_consistency_reports.py`(F1/F2 검출+영속화/정상 OK).
- 문서: decisions ADR-033 Amendment / postgres-schema ops / dagster-boundary §12 /
  test-strategy 정합성 매트릭스.

**검증(로컬 venv)**: 단위+lint 503 passed + 신규 6, mypy --strict OK, ruff OK,
import-linter 4 kept, alembic head 단일(0003). 통합은 로컬 docker 부재로 skip(2) →
CI에서 실행.

**다음**: Sprint 3 본작업 — KNPS/krheritage provider 또는 `/features/*` 라우터 +
`feature_repo.py` 실 적재.

## 2026-05-29 (claude) — ADR-030~033 사용자 승인 확정 + 문서 drift 정정

**작업**: 사용자가 ADR-030/031/032/033을 "제안한 대로 진행" 승인. 이 4건은
이미 PR#16(T-014)에서 `accepted`로 전환됐으나 `결정자` 라인에 "claude 제안,
사용자 검토 대기" 잔존 + 교차 참조 문서가 `(proposed)`로 남아 있던 drift를 정정.

- `docs/decisions.md`: ADR-030/031/032/033 `결정자` → "claude 제안 + 사용자
  결정 (2026-05-29 승인 확정)" (형제 ADR-027 컨벤션 정합).
- 교차 참조 `(proposed)` → `(accepted)`: `performance.md §9.1`(ADR-030) /
  `debug-ui-package.md §`(ADR-031) / `test-strategy.md §2`(ADR-032) /
  `dagster-boundary.md §12`(ADR-033).
- `docs/tasks.md`: T-012 (proposed→accepted 검토 대기) `[ ]` → `[x]` 종결.
- 역사적 기록(journal PR#8 / resume 완료 PR / SPRINT-1 전환표 / 리뷰 리포트)은
  당시 상태를 정확히 기록하므로 미변경.

**다음**: #117 Debug UI(WSL) + Windows Playwright e2e (변동 없음).

## 2026-05-29 (claude) — debug UI CORS (Playwright e2e #117 Stage A)

**작업**: #117 e2e 준비 중 발견 — frontend(Next.js 8610)가 브라우저에서
backend(8087)로 cross-origin fetch하는데 **backend에 CORS 미들웨어 부재** →
실제 debug UI가 동작 불가였음. CORS 추가.

- `settings.cors_allow_origins`(기본 `localhost:8610`/`127.0.0.1:8610`, ADR-005
  내부 도구라 localhost frontend만) + `app.py` `CORSMiddleware`.
- OpenAPI spec 무영향(미들웨어) → drift gate green 확인.
- 테스트 +2 (allow-origin GET, preflight OPTIONS) → debug-ui 73 통과. ruff/mypy.

**다음 (#117 Stage B)**: WSL node 설치 → frontend npm install + next dev + uvicorn
기동 → Windows Playwright로 frontend e2e.

## 2026-05-28 16:00 (claude) — DB 적재 통합 테스트 (통합 검증 #116)

**작업**: FeatureBundle → ORM → testcontainer PostGIS → 재조회 round-trip 검증.

- `tests/integration/conftest.py`: `migrated_engine`(alembic upgrade head +
  search_path x_extension) + `migrated_session`(per-test, flush 후 재조회, rollback)
  fixture 추가.
- `tests/integration/test_feature_bundle_persist.py`: datagokr 축제(좌표 포함)
  FeatureBundle을 FeatureRow/SourceRecordRow/SourceLinkRow로 적재 → 재조회. 검증:
  ① JSONB(detail/address) round-trip ② STORED generated `coord_5179`
  (ST_SRID=5179, ST_X/ST_Y가 입력 lon/lat과 1e-6 이내, ADR-012) ③ source_link FK.
- 실 적재 경로 `feature_repo.py`는 Sprint 3 — 본 테스트가 DTO→DB 계약 선행 검증.

**검증**: 통합 13/13 통과(회귀 없음), ruff. report §5 완료로 갱신.

**다음**: #117 Debug UI(WSL) + Windows Playwright e2e.

## 2026-05-28 15:30 (claude) — KMA 소스 정책: data.go.kr primary + apihub fallback

**작업**: 사용자 정책 정정 — "KMA는 data.go.kr 소스가 있으면 data.go.kr이 우선,
apihub가 fallback". PR#60에서 weather_alerts를 apihub primary로 둔 것을 **뒤집음**.

**변경 — `kma_weather_alerts_live`**:
- **primary**: data.go.kr `getWthrWrnList`(kma_service_key). HTTP 200이면 빈 결과
  (무특보)도 valid로 반환. **에러/무키 시에만** apihub fallback.
- **fallback**: apihub `wrn_now_data`(kma_apihub_key, 구조화 REG_ID, 활용신청 필요).
- `?via=apihub`(구조화 강제) / `?via=datagokr` override.
- 503 메시지·settings(`kma_apihub_key`) docstring·`.env.example`·report §2/§4.1을
  정책 정합으로 정정.
- 동네예보 3종(short/nowcast/ultra_short)은 이미 data.go.kr 단독 → 정책 정합.

**live 검증**: weather_alerts → data.go.kr primary로 19 notice 정상. ruff/mypy/
debug-ui 71 test 통과.

## 2026-05-28 15:00 (claude) — PR#63 opinet live auto-discovery

**작업**: opinet live 검증의 "UNI_ID 필요" 마찰 해소 (사용자 지시 — 단,
python-opinet-api는 검증 결과 이미 완전하여 라이브러리 무수정, 개선은 debug-ui
로더에 적용하기로 결정).

**python-opinet-api 검증**: 라이브러리 정상 — `get_lowest_price_top20`(5)/
`search_stations_around`(서울 54, WGS84→KATEC OK)/`get_station_detail`(A0019581)
전부 실 데이터. key param=`certkey`, KATEC proj는 본 loader `_OPINET_KATEC_PROJ`와
동일(ADR-044). 앞선 내 smoke aroundAll 빈 결과는 내가 key를 `code`로 보낸 실수.

**변경 — debug-ui `etl_live.py` opinet auto-discovery**:
- `_opinet_discover_uni_id`: ``id`` 명시 > ``(lon,lat)`` aroundAll > lowTop10
  (전국 최저가, 좌표 불필요·가장 견고). `_opinet_call`(certkey) 재사용.
- `_opinet_wgs84_to_katec`(역변환) + `_opinet_first_uni_id`(순수) 추가.
- `opinet_fuel_station_details_live`/`opinet_gas_station_prices_live`가 UNI_ID
  미지정 시 자동 discovery → detail/prices. (`?id=`/`?lon=&lat=` override 가능.)
- 기존 `_opinet_station_id`(id 없으면 raise) 제거.

**live 검증**: opinet_fuel_station_details 1건(coord in-range, place)/
opinet_gas_station_prices 2건(KRW/L) — **id 없이 동작**. → **11/11 dataset
모두 live 검증 가능** 달성.

**테스트**: opinet adapter +2(wgs84→katec round-trip, first_uni_id) = 12,
debug-ui 71 전부. ruff, mypy strict.

## 2026-05-28 14:30 (claude) — PR#62 krex live robustness (실 EX 키 검증)

> 주: PR#61은 타 에이전트의 "PR 17~60 리뷰 취합" 문서 PR로 선점됨 → 본 작업은 PR#62.

**작업**: 사용자 제공 EX 키(`2668138864`/`1371545112`)로 krex live 검증 →
실데이터에서 드러난 버그 수정 + EX endpoint 이슈 규명.

**EX 키 진단**: 두 키 모두 유효(serviceAreaRoute 221 / curStateStation 226 /
restWeatherList 200). 앞선 "인증키 무효"는 사용자 .env의 `KEX_GO_API_KEY`가 EX키가
아니었던 것(EX는 `KEX_EX_API_KEY` 필요).

**수정 (검증됨)**:
- `rest_areas_to_bundles`(main lib): EX serviceAreaRoute가 모든 표시필드 null인
  placeholder 행 반환 → name="" → Feature ValidationError. **빈 name/uni_id skip**
  추가 → live 98 place Feature 정상.
- `_adapt_krex_fuel_row`/`_adapt_krex_food_row`: 비숫자 가격 `Decimal` 변환 실패
  guard(skip) → InvalidOperation crash 방지.
- prices 로더: 식음료(`restMenuList`) 404 best-effort → 주유 가격만으로 진행.

**EX endpoint 이슈 (krex-api upstream 과제 — introduce02 JS 렌더라 자동 추출 불가)**:
- `restMenuList`(식음료) HTTP 404 deprecated. `restBrandList`는 200(브랜드 목록,
  가격 아님).
- `incident`(돌발) HTTP 404 — 유효 키로도 404, 경로 deprecated/변경.
- `curStateStation`은 주유가격이 아닌 휴게소 목록 반환 → prices fuel 0건(필드 불일치).
  → krex 주유/식음료/돌발 정확한 EX endpoint는 introduce02(브라우저) 확인 후
  krex-api + 본 loader 정정 필요. (rest_areas/weather endpoint는 정상.)

**테스트**: krex provider +2(빈 name/uni_id skip) = 20, krex adapter 14, ruff,
mypy strict 통과.

**다음**: #116 DB 적재 통합 테스트 → #117 Playwright e2e → #118 종합 리포트(키/
endpoint 이슈 + 사람 조치 항목 정리).

## 2026-05-28 14:00 (claude) — PR#60 weather_alerts data.go.kr fallback + 키 drift 정정

**작업**: 통합 검증 1단계 (task #114). apihub 키 진단 결과 반영.

**apihub 키 진단** (사용자 제공 `gagX...`): 3개 endpoint(wrn_now_data/
wrn_now_data_new/kma_sfctm2) 전부 **HTTP 403 "활용신청이 필요한 API"** — 키는
인증되나 활용신청된 apihub API 0건. → 사람이 apihub.kma.go.kr에서 활용신청 필요.

**대응 — `kma_weather_alerts_live`를 apihub primary + data.go.kr fallback로**:
- primary: apihub `wrn_now_data`(구조화 특보구역 REG_ID). 403/무키/무특보면 강등.
- fallback: data.go.kr `WthrWrnInfoService/getWthrWrnList`(공통 serviceKey =
  kma_service_key). 실 응답 stnId/title/tmFc/tmSeq → 관서 단위 pseudo-region 1건,
  title 요약문 keyword→notice_type/level. `?via=datagokr`로 강제 가능.
- **live 검증**: 실 키로 e2e 실행 → apihub 403 → fallback → **특보 19건 수신**
  (호우주의보→heavy_rain_warning, 강풍·풍랑→weather_alert, region 기상청 본청, KST).

**키 이름 drift 정정** (settings.py docstring + .env.example): 실제 provider .env
키 이름은 공통 `DATA_GO_KR_SERVICE_KEY`(kma/datagokr/krex/visitkorea) /
`OPINET_API_KEY` / `KEX_GO_API_KEY`(data.ex.co.kr) — 기존 가정과 달라 source 명시.

**테스트**: `test_etl_live_kma_alert_adapters.py` +5 (fallback adapter/keyword/level/
미지 stn/transform) = 13 case. 라우터 503 테스트는 두 키 안내로 갱신.
adapter 13/13 + ruff + mypy strict 통과.

**CI 회귀 hotfix (같은 PR)**: starlette 1.0+ TestClient이 httpx2를 hard-require
→ debug-ui 테스트 수집 단계 `ModuleNotFoundError: httpx2`로 전면 실패(내 코드
무관, starlette 1.2.0 신규 릴리스 영향). `pyproject.toml`에 `starlette>=0.40,<1.0`
+ `httpx>=0.27,<1.0` 핀(코드가 httpx 0.x API 의존) → fastapi 0.136.3 + starlette
0.52.1 + httpx 0.28.1로 resolve. debug-ui 69 test 전부 통과 확인.

**live 검증 (실 키, repo 밖 임시 스크립트)**: 11 dataset 중 kma_short(1000)/
nowcast(8)/ultra_short_fcst(60, 재시도)/datagokr 축제/weather_alerts(19) = **유입+
정합성 OK**. krex 4 = EX 키(`KEX_EX_API_KEY`) 부재로 "인증키 무효"(사용자 .env엔
`KEX_GO_API_KEY`만). opinet 2 = UNI_ID 필요(detailById 설계상) — 별도 확보 필요.
apihub 특보 primary = 활용신청 필요(403). → 상세는 #118 리포트.

**다음**: #115 전 dataset live 정합성 + #116 DB 적재 + #117 Playwright + #118 리포트.

## 2026-05-28 13:30 (claude) — Sprint 2 종료 회고 (PR#59)

**작업**: item 4 — Sprint 2 종료 게이트. `pyproject.toml` `fail_under` 50→65
(실측 96%, ADR-032 schedule상 Sprint 2 bar) + `SPRINT-2.md` ✅완료 +
`SPRINT-3.md` 🔵active 진입 + `sprints/README.md` 상태표 + `resume.md` 종합 갱신.

**Sprint 2 (PR#28~#59) 회고**:
- ✅ Provider ①~④ (datagokr 축제 / kma 날씨 4종+중기 / opinet 유가 / krex 휴게소
  4종) provider→DTO 변환 + visitkorea enrichment.
- ✅ 디버그 UI backend (create_app + health/version + ETL preview fixture/live)
  + OpenAPI drift gate + frontend skeleton.
- ✅ **ETL live 11/11 dataset** wiring (PR#47 KMA 3 + PR#55~58 8종). ADR-044
  로컬 repo 기준.
- ✅ Coverage 96% / fail_under 65 / ruff / mypy strict / import-linter 4.
- **회고 인사이트**:
  - ADR-044(로컬 우선)가 datagokr·opinet·krex wiring 정확도를 크게 높임.
    GitHub 404로 보류했던 provider가 `F:\dev\`에 존재한 사례 다수.
  - apihub vs data.go.kr 게이트웨이 키 분리(서로 다른 인증)를 weather_alerts에서
    실증 — settings에 `kma_apihub_key` 분리 필요했음.
  - **drift 발견**: provider repo .env 실제 키 이름이 debug-ui settings 가정과
    다름 (공통 `DATA_GO_KR_SERVICE_KEY` / `OPINET_API_KEY` / `KEX_GO_API_KEY`).
    → 통합 검증 단계에서 매핑 + settings 문서 정정 예정.

**다음 (사용자 지시)**: 통합 검증 — ETL live 실데이터 유입/정합성 + DB 적재
(ORM→PostGIS) + Debug UI Playwright e2e + 상세 리포트 (tasks #114~#118).

## 2026-05-28 13:00 (claude)

**작업**: PR#58 — ETL live `kma_weather_alerts` loader (특보현황). 8종 중 4차이자
**마지막 → 11/11 fixture dataset 전부 live 지원**. ADR-044: 로컬
`python-kma-api/apihub_endpoints.py`의 `wrn_now_data`(특보현황) endpoint 기준.

**핵심 결정 — apihub 경로 선택**:
- data.go.kr `getWthrWrnList`는 `t6` free-text 블롭만 줘서 구조화 특보구역 없음.
- apihub `wrn_now_data`는 **특보구역(REG_ID) 단위 행** 제공 → provider
  `weather_alerts_to_notice_bundles`(region fan-out)에 정합 → apihub 채택.
- apihub는 `authKey`(apihub.kma.go.kr)로 인증 — data.go.kr `serviceKey`와 **별개
  키** → `settings.kma_apihub_key` (`KRTOUR_MAP_DEBUG_UI_KMA_APIHUB_KEY`) +
  `.env.example` 추가. 미설정 시 503 (다른 KMA loader와 일관).

**변경 — `etl_live.py`** (KMA apihub 섹션):
- `_kma_apihub_text`(text/plain GET) + `_kma_apihub_parse_table`(`#`-주석 헤더
  검출 → 콤마/공백 데이터 행 dict, 로컬 `apihub.parse_apihub_text_table` 정책
  정합). 헤더 못 찾으면 빈 list (graceful).
- `_adapt_kma_wrn_row` — WRN 1자 코드→(한글,canonical notice_type) 매핑. alias
  미등록 종류(강풍/한파/건조/풍랑/태풍/황사/해일)는 `weather_alert`로 강등
  (`normalize_notice_type` ValueError 회피). LVL→등급, TM_FC/TM_EF/ED_TM 파싱,
  REG_ID 1건=1 region.
- `kma_weather_alerts_live` → `weather_alerts_to_notice_bundles`.
- `LIVE_LOADER_REGISTRY` 등록 (11/11). registry 후속-PR 주석 제거.

**신규 테스트**: `test_etl_live_kma_alert_adapters.py` (8 case — dt 파싱 변형,
콤마/공백 헤더 파싱, 헤더 없음 graceful, WRN 코드 매핑, 미스펙 강등, 필수 결측
None, 변환 통과). `test_etl_routers.py`: 501 테스트를 monkeypatch 방식으로 교체
(11/11 등록되어 실 dataset로는 트리거 불가) + weather_alerts live_supported/503 +2.

**⚠️ 잔여 검증**: apihub help 블록의 정확한 컬럼 헤더 표기(REG_ID/TM_FC/...)는
authKey 발급 후 실 응답으로 확인 필요. 파서는 헤더 미검출 시 빈 list라 무해.

**Verification**: adapter 8/8 (WSL venv) + ruff + mypy strict (etl_live/settings)
통과. 라우터 테스트(fastapi 필요)는 CI 검증.

**다음**: item 4 — `fail_under` 50→65 + Sprint 2 종료 회고 + Sprint 3 진입 준비.

## 2026-05-28 12:30 (claude)

**작업**: PR#57 — ETL live datagokr 전국문화축제표준데이터 loader. 8종 중 3차.
**ADR-044 직접 효과** — GitHub 404로 보류했던 `python-datagokr-api`가 `F:\dev\`
로컬에 존재 확인 → 정확히 wiring.

**변경 — `etl_live.py`** (datagokr 섹션):
- `_datagokr_call`(`api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api`,
  serviceKey/type=json/pageNo/numOfRows, `response.body.items[]`).
- `datagokr_cultural_festivals_live` → `cultural_festivals_to_bundles`.
- `_adapt_datagokr_festival` — 로컬 `PublicCulturalFestival` alias(fstvlNm/opar/
  fstvlStartDate/fstvlEndDate/fstvlCo/mnnstNm/phoneNumber/rdnmadr/lnmadr/
  latitude/longitude/referenceDate/instt_nm) → `CulturalFestivalItem` Protocol.
  관리번호 컬럼 없어 (축제명@도로명) 결정적 합성. 날짜/Decimal 파서.
- `LIVE_LOADER_REGISTRY` datagokr 등록 (KMA 3 + krex 4 + opinet 2 + datagokr 1
  = 10 live). `_ = date` 묵음 처리 제거(date 실사용).

**신규 테스트**: `test_etl_live_datagokr_adapters.py` (7 case — 날짜 변형 파싱,
alias 매핑, 관리번호 합성 결정성, 좌표 없음, 변환 통과). `test_etl_routers.py`:
501 테스트를 datagokr→kma_weather_alerts로 교체(datagokr 이제 등록됨) +
datagokr live_supported/503 +2.

**Verification**: debug-ui 54 / ruff / mypy strict 49 / import-linter 4 /
openapi drift 0.

**다음**: kma_weather_alerts 1(PR#58, apihub wrn_now_data) → 11/11 live → item 4.

## 2026-05-28 12:00 (claude)

**작업**: PR#56 — ETL live opinet 2 dataset loader (station/prices). 8종 중
2차. ADR-044 로컬 우선 — `python-opinet-api` client `_build_station_detail`/
`_build_oil_price` + `coords.py` KATEC proj 그대로 참조.

**변경 — `etl_live.py`** (opinet 섹션):
- `_opinet_call`(`opinet.co.kr/api`, `certkey`+`out=json`, `RESULT.OIL[]`).
- `opinet_fuel_station_details_live`(detailById.do `?id=<UNI_ID>` 필수 → station
  place) / `opinet_gas_station_prices_live`(같은 호출 중첩 `OIL_PRICE[]` →
  PriceValue).
- KATEC→WGS84: 로컬 `coords.py` proj4를 그대로 박아 pyproj 변환, 범위 밖/실패
  시 좌표 None 강등.
- adapter 2종 순수 함수. raw 필드: UNI_ID/OS_NM/POLL_DIV_CO/NEW_ADR|VAN_ADR/
  GIS_X|Y_COOR/TEL/LPG_YN + OIL_PRICE[PRODCD/PRICE/TRADE_DT/TRADE_TM].
- `LIVE_LOADER_REGISTRY` opinet 2 등록 (KMA 3 + krex 4 + opinet 2 = 9 live).

**신규 테스트**: `test_etl_live_opinet_adapters.py` (10 case — KATEC round-trip
서울 forward→back ~127/37.5, 좌표 없음 None, station/price 매핑, 변환 통과).
`test_etl_routers.py` +2 (opinet live_supported / 503).

**설계**: detailById.do는 전체 목록 endpoint 없어 `?id=<UNI_ID>` 필수. 좌표는
KATEC라 reproject 필수(미변환 시 Coordinate 범위 validator reject).

**Verification**: debug-ui 47 / 메인 469 / ruff / mypy strict 49 / import-linter
4 / openapi drift 0.

**다음**: datagokr 1(PR#57) → kma_weather_alerts 1(PR#58) → 11/11 live → item 4.

## 2026-05-28 11:30 (claude)

**작업**: PR#55 — Sprint 2 item 3(ETL live) krex 4 dataset loader. 사용자
"8종 전부 wiring" 결정 중 첫 4종. ADR-044 로컬 우선 조회로 `python-krex-api`
EX OpenAPI 스펙 확인 후 정확히 wiring.

**변경 — `etl_live.py`** (krex 섹션):
- EX OpenAPI(`data.ex.co.kr`, `key`+`type=json`, `payload.list[]`) `_krex_call`.
- 4 loader: `krex_rest_areas_live`(serviceAreaRoute, 좌표 없음→None) /
  `krex_rest_area_prices_live`(curStateStation 주유 explode + restMenuList 식음료
  combine) / `krex_rest_area_weather_live`(restWeatherList, sdate/stdHour 기본
  현재, wide→long melt, -99 sentinel drop) / `krex_traffic_notices_live`
  (incident, notice_id 합성, incidentType 코드→notice_type 매핑).
- 순수 adapter 5종(`_adapt_krex_*`) — async fetch는 key 필요해 CI 미검증이라
  adapter를 테스트 핵심으로 분리.
- `LIVE_LOADER_REGISTRY`에 krex 4 등록 (이제 KMA 3 + krex 4 = 7 live).

**신규 테스트**: `tests/test_etl_live_krex_adapters.py` (14 case — rest_area
매핑, fuel explode, food, weather melt+sentinel, notice 합성/매핑, 각 adapter가
실제 변환 함수 통과). `test_etl_routers.py` +2 (krex live_supported / 503).

**설계**: EX incidentType 코드(1사고/2공사/3기상/4기타) → 표준 notice_type
(traffic_accident/roadwork/weather_alert/traffic) 매핑 — NoticeDetail validator
정합. rest_areas는 serviceAreaRoute에 좌표 없어 coord=None(좌표는 후속 join).

**Verification**: debug-ui 37 passed (krex adapter 14 + 기존) / 메인 469 /
ruff / mypy strict 49 / import-linter 4. openapi drift 0.

**다음**: opinet 2(PR#56) → datagokr 1(PR#57) → kma_weather_alerts 1(PR#58)
→ item 4 Sprint 2 종료.

## 2026-05-28 11:00 (claude)

**작업**: PR#54 — ADR-044: 관련 라이브러리 로컬(`F:\dev\`) 우선 조회 + 데이터
정합성 책임은 각 라이브러리. 사용자 지시 문서화. 순수 docs.

**계기**: PR#53(ETL live) 조사 중 `python-datagokr-api`를 **GitHub 404로만 확인**
하여 "repo 부재 → wiring 불가"로 잘못 보류. 그러나 `F:\dev\python-datagokr-api`
는 로컬에 존재. 모든 형제 `python-*-api` + `maplibre-vworld-js`가 `F:\dev\`
아래 로컬 체크아웃됨. → 로컬 우선 조회 룰 + 데이터 정합성 책임 분계를 ADR로 박음.

**ADR-044 결정**:
1. **로컬 우선 조회** — provider/형제 라이브러리의 client·model·codes·스펙은
   `F:\dev\` (WSL `~/dev/`) 로컬을 `Glob`/`Read`로 먼저 조회. GitHub fetch는
   로컬에 없을 때만 fallback. GitHub 404/private ≠ "미존재".
2. **데이터 정합성 책임 = 각 provider 라이브러리** — 코드 매핑/필드 의미/단위/
   분류값의 1차 책임은 provider 라이브러리. 본 lib는 신뢰·미러만, 재정의 X.
   불일치 시 그 라이브러리(+공식 스펙) 기준 정렬 + 필요 시 upstream PR.

**변경 (docs 5)**:
- `docs/decisions.md` — ADR-044 본문 추가 (001~044 accepted).
- `AGENTS.md` §"Provider API 사용 원칙" — 로컬 우선 + 정합성 책임 2 bullet.
- `CLAUDE.md` §4 — `F:\dev\` 형제 repo 목록 + 우선 조회/정합성 룰.
- `docs/provider-contract.md` §1.4 — 로컬 우선 + 정합성 책임 (PR#53 사례).
- `docs/dev-environment.md` §7 — `F:\dev\` provider 로컬 레이아웃 트리 + 룰.
- `docs/tasks.md` / `docs/resume.md` — ADR 가이드 001~044 / 다음 ADR-045.

**영향**: Sprint 2 item 3(ETL live)에서 **datagokr live는 실제 feasible**
(로컬 repo 존재) — 기존 "infeasible" 보류 재검토 대상. kma_weather_alerts도
`python-kma-api/apihub_endpoints.py`(wrn_now_data 구조화) 재검토 가능.

## 2026-05-28 10:30 (claude)

**작업**: opinet product code 정정 — `OPINET_PRODUCT_KEY_MAP`에서 `K015`/`C004`가
서로 뒤바뀌어 있던 것을 수정. 데이터 정합성 단일 fix (PR feat/fix-opinet-product-codes).

**근거**: upstream `python-opinet-api` `codes.py`(`KEROSENE="C004"` / `LPG="K015"`)와
한국석유공사 OpiNet OpenAPI 공식 제품코드(C004=실내등유, K015=자동차용부탄)가 일치.
기존 map은 `K015→kerosene` / `C004→lpg`로 정반대였음.

**변경**:
- `providers/opinet.py` — `OPINET_PRODUCT_KEY_MAP` `C004→kerosene` / `K015→lpg`로
  정정 + 모듈 docstring 표 동기화.
- `tests/unit/test_providers_opinet.py` — `_LPG` fixture `prodcd` `C004→K015`(실제
  LPG 코드)로 정정 + `test_product_code_map_complete` assertion 정정.
- `docs/sprints/SPRINT-2.md` §2.3 — 잘못된 위치 매핑(`…/K015/C004`) 정정.

**Verification**: `pytest tests/unit -k opinet` 26 passed / `ruff check src tests`
clean / `mypy --strict src` 40 files.

**비고**: `prices_to_values` 변환 경로는 무변(lookup table만 정정). debug-ui
`etl_fixtures.py`의 C004 데모는 그대로 두되 이제 kerosene으로 정상 출력됨.

## 2026-05-28 09:40 (claude)

**작업**: PR#52 — Sprint 2 잔여 2/4: KMA 중기예보 (mid forecast). ADR-010
forecast_style=mid / timeline=mid.

**변경 — `providers/kma.py`** (mid 섹션 추가):
- `KmaMidLandForecastItem` Protocol (중기육상 getMidLandFcst — reg_id/tm_fc +
  wf_{3..7}_{am|pm}/wf_{8..10} 날씨 텍스트 + rn_st_* 강수확률).
- `KmaMidTemperatureItem` Protocol (중기기온 getMidTa — ta_min/ta_max_{3..10}).
- `mid_land_forecast_to_weather_values` — 한 region을 day-period로 fan-out:
  3~7일 AM/PM 2건 + 8~10일 단일. 각 period에 SKY(`value_text`) + POP
  (`value_number`). **AM/PM 구간 = `valid_from`/`valid_until`**, identity
  유일성 = `valid_at`(구간 시작) — ADR-010에서 valid_from은 identity 제외라
  day-period 구분용으로 valid_at을 박음.
- `mid_temperature_to_weather_values` — 일자별 TMN/TMX (종일 구간).
- `_parse_mid_announce`(tm_fc YYYYMMDDHHMM) + `_mid_window`(발표일+N일 구간).
- 빈 텍스트/None metric 생략.

**신규 테스트**: `tests/unit/test_providers_kma_mid.py` (11 case — fan-out count
26/16, AM/PM window, day8 종일, POP numeric, None 생략, **identity 유일성**,
tm_fc reject).

**변경**: `providers/__init__.py` mid 6 심볼 re-export / `SPRINT-2.md` §2.2 +
§7 잔여 2 완료.

**설계 결정**:
- 중기 날씨는 텍스트("맑음"/"흐리고 비")라 표준 `SKY`에 `value_text`로 담고
  원천 필드는 `source_metric_key='wf3Am'`로 보존 (단기 SKY code와 의미 다르나
  표준 키 재사용 — §2 "표준에 없는 지표는 source_metric_key 유지" 정신).
- 26-field flat Protocol은 `getattr(item, f"wf_{day}{suffix}")` 스케줄 테이블
  로 DRY 처리 (mypy strict OK — getattr→Any→typed local).
- WeatherValue.identity()가 valid_at 사용 → mid는 valid_at을 구간 시작으로
  박아 day-period별 유일 (DB UNIQUE 충돌 방지). 테스트로 검증.

**Verification**: 469 passed (+11) / ruff / mypy strict 49 files / import-linter
4 contracts green.

**Sprint 2 종료 게이트**: 2/4 완료. 다음 = ETL live 나머지 8 dataset (3/4).

## 2026-05-28 09:10 (claude)

**작업**: PR#51 — Sprint 2 잔여 1/4: VisitKorea TourAPI enrichment
(`festival_to_enrichment_links`). ADR-042 2차 source.

**신규** (2):
- `src/krtour/map/providers/visitkorea.py` (~290 line) — datagokr 1차로 적재된
  festival `feature_id`에 visitkorea `SourceRecord` + `SourceLink`
  (`source_role='enrichment'`)만 잇는다. **새 Feature를 만들지 않음.**
  - `VisitKoreaFestivalItem` Protocol (contentId/overview/first_image 등)
  - `FestivalMatcher`/`FestivalMatch` Protocol — datagokr↔visitkorea 매칭은
    이름/지역 fuzzy(ADR-016)라 plug-in 주입 (`standard_data.ReverseGeocoder`
    패턴). `match()->None`이면 해당 item enrichment 생략.
  - `FestivalEnrichment` 결과 모델 (source_record + source_link) + consistency
    validator (role=ENRICHMENT / key 일치 / not primary).
  - `festival_to_enrichment_links(items, *, matcher, fetched_at)`.
- `tests/unit/test_providers_visitkorea.py` (8 case).

**변경**:
- `providers/__init__.py` — visitkorea 7 심볼 re-export.
- `docs/event-feature-etl.md §7.1.5` "미구현" → PR#51 구현 + 시그니처 안내.
- `docs/sprints/SPRINT-2.md` §2.1 + §7 잔여 1 → 완료.

**설계 결정**:
- enrichment는 `FeatureBundle`이 아님 (Feature 없음) → `FestivalEnrichment`
  (record+link 쌍) 신설. 일반화(`EnrichmentBundle` in dto/)는 2번째 enrichment
  provider 등장 시(Sprint 3+) 검토 — 지금 dto/ 확장은 과함.
- 이미지 URL은 `SourceRecord.raw_data`에만 보존 — `FeatureFileSource` DTO는
  Sprint 2-3 (bundle.py 주석 명시).

**Verification**: 458 passed (+8) / ruff / mypy strict 49 files / import-linter
4 contracts green.

**Sprint 2 종료 게이트**: 1/4 완료. 다음 = KMA mid_forecast (2/4).

## 2026-05-28 08:40 (claude)

**작업**: PR#50 — Sprint/task/resume 문서 일관성 재정비 (사용자 지시 "코드와
PR 상태 확인해서 sprint/task 정리 + resume.md 정리 + 일관성·목표 명확화").
순수 docs.

**그라운드 트루스 확인** (codegraph + git + pytest):
- main `225ac77`, **open PR 없음**, 총 49 PR merged.
- 구현 완료: provider 4종(standard_data/kma/opinet/krex) + dto 18 + core 8 +
  infra 3(models/db/crs)+Alembic + debug-ui 라우터 3(health/version/etl) +
  frontend skeleton. **coverage 96%** (unit 450 + debug-ui 21).
- 미구현: visitkorea / knps / krheritage / mois provider, `infra/feature_repo.py`,
  `/features/*` 라우터.

**변경 — docs** (4):
- `docs/resume.md` — 직전 세션의 미커밋 재작성본 채택 + PR#49 merged 사실 정합
  (main hash/PR수/open PR 표/완료 목록). 기존의 **중복 "다음 PR 후보" 3블록
  제거** → 현 상태/다음 한 작업/완료 PR/진척도/ADR/차단 단일 구조.
- `docs/sprints/README.md` — 상태 컬럼 정정: Sprint 1 ✅완료 / Sprint 2 🔵
  active(~90%) / Sprint 3 다음. "현 위치" 박스 추가.
- `docs/sprints/SPRINT-2.md` — header 상태 active, §1 진입조건 [x], §7 종료조건
  완료/잔여 분리 (잔여 4건 = 단일 출처). `/features/*`는 Sprint 2 게이트 아님 명시.
- `docs/tasks.md` — 진행 중→open PR 없음 + Sprint 2 종료 게이트 4건 / 최근 완료
  PR#48·#49 추가 / 머지 history #48·#49 merged + #50 open.

**Sprint 2 종료 게이트 = 잔여 4건** (resume/tasks/SPRINT-2 §7 동일):
visitkorea enrichment / KMA mid_forecast / ETL live 8 dataset / coverage bar
상향+회고. 이후 Sprint 3 (KNPS·krheritage + 정합성 Phase 1 + `/features/*`).

**부수**: 직전 세션 잔류 0-byte 잡파일(`3`, `~220줄`) 제거.

## 2026-05-28 08:10 (claude)

**작업**: PR#49 — `maplibre-vworld-js` **v0.1.0** 기준 의존 핀 정합 (사용자
지시 "0.1.0 기준으로 코드 재확인"). 순수 frontend 의존/docs.

**핵심 발견 — 기존 `^1.0.0` 핀이 이중으로 잘못됨**:
- upstream `digitie/maplibre-vworld-js`는 **v0.1.0 태그만 릴리스** (v1.0.0
  미존재).
- npm `maplibre-vworld` 패키지 **미게시** → semver `^1.0.0`로는 애초에 설치
  불가. git URL+tag로 핀해야 함.

**변경 — package.json** (2):
- `frontend/package.json`: `maplibre-vworld ^1.0.0` →
  `github:digitie/maplibre-vworld-js#v0.1.0`; `zod ^3.23.0` → `^4.4.3`
  (v0.1.0 peer).
- `map-marker-react/package.json`: peer `maplibre-vworld ^0.1.0` + `zod
  ^4.4.3` 추가 + `maplibre-gl ^5.0.0`→`^5.24.0`; devDep maplibre-vworld git
  URL + zod + maplibre-gl 동일 정합.

**변경 — docs** (5):
- `frontend/README.md` / `docs/debug-ui-package.md §14` /
  `docs/tripmate-integration.md §14.5` — v1.0.0 → v0.1.0 + npm 미게시 + peer
  버전.
- `docs/decisions.md` ADR-025 v1.0.0 inline 2건 정정 + **ADR-036 amendment
  (2026-05-28, PR#49)** 추가 — v0.1.0 릴리스/npm 미게시/git URL 핀/peer 정합
  /v0.1.0 공개 API 표면/Zustand vs MapStore 역할 구분.
- `packages/map-marker-react/README.md` peer deps 표.

**v0.1.0 API 확인** (upstream `src/index.ts`): `VWorldMap`(apiKey/center/zoom/
fallback) + `MapStore`/`useMap`/`useMapZoom`/`useMapSelector` + 마커 13종 +
레이어 4종 + `zod` schemas. 현 frontend는 아직 지도 미렌더(skeleton)라 API
직접 사용 0 — 핀/문서 정합만. 본 frontend Zustand `useMapStore`(앱 UI 상태)는
v0.1.0 `MapStore`(지도 인스턴스 상태)와 역할이 달라 병존.

**Verification**: 순수 frontend 의존/docs (Python 코드 0). 두 package.json
JSON 유효성 확인. ruff/mypy/pytest 무관.

## 2026-05-28 07:40 (claude)

**작업**: PR#48 — agent worktree 접두사 `geo-*` → `krtour-map-*` 일괄 rename
+ `docs/tasks.md` 최신화 (순수 docs).

**worktree rename** (사용자 지시 — `krtour-map-` 접두사):
- `geo-codex`/`geo-claude`/`geo-antigravity` → `krtour-map-codex`/
  `krtour-map-claude`/`krtour-map-antigravity`.
- 변경 파일: `AGENTS.md` / `CLAUDE.md` / `SKILL.md` / `docs/codegraph-
  worktree.md` (§2 명명 규약 + rationale reword + tree + setup 예시) /
  `docs/dev-environment.md` / `docs/agent-guide.md` / `docs/resume.md`.
- `docs/codegraph-worktree.md` §2 rationale 재작성 — 접두사를 본 저장소
  (`python-krtour-map`) 이름에서 따와 한 머신의 여러 저장소 worktree를 1:1
  식별. (이전 `geo-*`는 형제 `python-kraddr-geo`와 모호.)
- `docs/journal.md` 과거 엔트리(2026-05-27 PR#30~31)의 `geo-*`는 역사
  기록이라 보존.

**tasks.md 최신화** (PR#19 open으로 멈춰 있던 백로그 → PR#47 merged 반영):
- "진행 중" → PR#48만. "최근 완료 (Sprint 2)" → PR#34~#47 요약 추가.
- 우선순위 가이드 — Sprint 2 ①②③④ + 디버그 UI ✅ 표기, 다음(live 매트릭스
  확장 / maplibre-vworld v0.1.0 정합 / mid_forecast / `/features/*`).
- ADR 가이드 — 001~034 → **001~043 accepted**, 다음 후보 **ADR-044**.
- 머지 history 표 — #19~#47 (26행) 추가, #48 open.
- T-014 history block의 stale 미완 bullet 2건 (PR#28/#29) 완료 처리.

**Verification**: 순수 docs (코드 변경 0). ruff/mypy 무관. 별도 신규 테스트
없음.

## 2026-05-28 07:00 (claude)

**작업**: PR#47 — ETL preview `?source=live` 활성화 + 8 provider API key를
`DebugUiSettings`에 추가. KMA 3 dataset (short / nowcast / ultra_short_forecast)
부터 실 호출 + 변환 통과. 다른 8 dataset (datagokr / kma_weather_alerts / opinet
2 / krex 4)은 framework 등록만 — 미등록은 `501 Not Implemented`.

**서비스 키 컨벤션** (.env 공유):
- 각 provider repo (`python-kma-api`/`python-opinet-api`/…)의 `.env`에 박힌
  키 이름을 그대로 가져오고, prefix `KRTOUR_MAP_DEBUG_UI_`만 붙여 디버그 UI
  `.env`로 옮긴다.
- 예: `python-kma-api/.env`의 `KMA_SERVICE_KEY=...` → 디버그 UI의
  `.env`에 `KRTOUR_MAP_DEBUG_UI_KMA_SERVICE_KEY=...`로 저장.
- ADR-005 + ADR-035: 운영 시 Cloudflare Tunnel/SSO 뒤. `SecretStr` 보호
  (plaintext 로그/JSON 노출 방지).

**신규 파일** (2):
- `packages/krtour-map-debug-ui/.env.example` (8 provider 키 자리 + 컨벤션
  주석)
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/etl_live.py` (~270
  line):
  - `LiveLoader` 타입 + `LiveLoaderError` exception
  - KMA 3 endpoint async httpx wrapper (`_kma_call`)
  - base_date/base_time 자동 계산 (`_kma_now_base`/`_kma_ncst_base`/
    `_kma_usf_base`)
  - `_KmaShortAdapter` / `_KmaNowcastAdapter` dataclass — provider raw JSON
    → Protocol 만족 adapter (httpx 직접 사용 — provider client 의존 회피)
  - `kma_short_forecast_live` / `kma_ultra_short_nowcast_live` /
    `kma_ultra_short_forecast_live` 3 loader 함수
  - `LIVE_LOADER_REGISTRY: dict[tuple[str,str], LiveLoader]` (KMA 3건만
    등록 — 나머지는 `find_live_loader` 반환 `None`)

**변경 — 디버그 UI** (4):
- `pyproject.toml`: `httpx>=0.27` 추가 (provider raw API 호출용 async client)
- `src/krtour/map_debug_ui/settings.py`: 8 `SecretStr | None` field 추가
  (kma/opinet/datagokr/visitkorea/krex/knps/airkorea/krforest)
- `src/krtour/map_debug_ui/routers/etl.py`:
  - `_DatasetEntry`에 `live_supported: bool` 필드 추가 (`LIVE_LOADER_REGISTRY`
    참조)
  - `post_preview()` `?source=live` 분기 활성 — `_run_live_preview()`로
    dispatch
  - 응답 매핑: 404 (dataset 미등록) / 501 (live loader 미구현) / 503 (key
    미설정) / 502 (provider 외부 API 실패)
- `openapi.json` drift gate 재생성 (live_supported 필드 + 502/503 응답
  추가)

**신규 테스트** (3건 추가 — 11 → 21):
- `test_preview_live_source_501_when_not_registered` — datagokr는 live 미등록
  → 501
- `test_preview_live_kma_503_when_key_missing` — KMA live 등록됐지만 `.env`
  키 없으면 503
- `test_providers_dataset_marks_live_supported` — KMA 3 dataset
  `live_supported=True`, weather_alerts는 False

**Verification**:
- `python -m pytest -q` → **450 passed, 16 skipped** (메인 lib)
- `cd packages/krtour-map-debug-ui && python -m pytest -q` → **21 passed**
  (PR#46 18 + PR#47 3)
- `ruff` All checks passed
- `mypy --strict src packages/krtour-map-debug-ui/src` → **no issues found in
  48 source files**
- `lint-imports` 4 contracts KEPT
- openapi drift exit 0

**의도적 type ignore 3건** — `etl_live.py`:
- `_KmaShortAdapter` 와 `KmaUltraShortForecastItem` Protocol은 attribute
  set이 동일하나 mypy strict는 nominal 매칭만 한다. 실행 시 Protocol
  structural check은 통과. 각 호출 부에 `# type: ignore[arg-type]` + 사유
  주석.

**디버그 UI live mode 매트릭스 (11 dataset 중 3건 활성)**:
| Provider | Dataset | live_supported |
|----------|---------|----------------|
| python-kma-api | short_forecast / ultra_short_nowcast / ultra_short_forecast | ✅ |
| python-kma-api | weather_alerts | ⏳ (framework only) |
| data.go.kr-standard | cultural_festivals | ⏳ |
| python-opinet-api | station_details / prices | ⏳ |
| python-krex-api | rest_areas / prices / weather / traffic_notices | ⏳ |

**Sprint 2 §2.5 진입 — debug UI live mode**. 다음 후보:
- 디버그 UI live 매트릭스 확장 (datagokr 1 + opinet 2 + krex 4 + kma_weather
  _alerts 1 = 8건)
- KMA mid_forecast (텍스트 + AM/PM split)
- `/features/*` 라우터 + infra/feature_repo
- ADR-016 dedup scoring preview

## 2026-05-28 06:00 (claude)

**작업**: PR#46 — KMA weather_alerts → notice FeatureBundle + krex
TRAFFIC_NOTICE_CATEGORY 정정 + ETL preview registry 11 dataset 확장.

**변경 — 본 lib** (3):
- `src/krtour/map/providers/kma.py`:
  - `KmaWeatherAlertRegion`/`KmaWeatherAlertItem` Protocols
  - `weather_alerts_to_notice_bundles(items, *, fetched_at)` — 한 alert × N
    region fan-out
  - 상수: `KMA_WEATHER_ALERT_DATASET_KEY`/`KMA_WEATHER_ALERT_CATEGORY=
    "99000000"`(placeholder)/marker/`KMA_ALERT_LEVEL_SEVERITY` 매핑
- `src/krtour/map/providers/krex.py`: `TRAFFIC_NOTICE_CATEGORY`
  `"06010000"`(PARKING 오용) → `"99000000"` (notice placeholder) 정정
- `src/krtour/map/providers/__init__.py` — kma 9 신규 re-export

**변경 — 디버그 UI** (2):
- `etl_fixtures.py`: krex 4 + kma alerts → registry 6 row → 11 row 확장
- `openapi.json` — drift gate baseline 재생성

**신규 테스트**:
- `tests/unit/test_providers_kma_alerts.py` (14 case)
- `tests/unit/test_providers_krex.py` 코멘트 정정

**Verification**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **469 passed** (PR#45 455 + 신규 14)
- `ruff` All checks passed / `mypy --strict` no issues found in 47 source files
- openapi drift exit 0

**디버그 UI ETL preview 매트릭스 (총 11 dataset)**:
| Provider | Datasets |
|----------|----------|
| data.go.kr-standard | 1 (cultural_festivals) |
| python-kma-api | 4 (short/nowcast/ultra_short_forecast/weather_alerts) |
| python-opinet-api | 2 (station_details/prices) |
| python-krex-api | 4 (rest_areas/prices/weather/traffic_notices) |

**KMA 진행**: short ✅ / nowcast ✅ / ultra_short_forecast ✅ / weather_alerts ✅
/ mid_forecast ⏳ (텍스트 + AM/PM split, 별도 후속)

**Sprint 2 §2.4 완료 + §2.2 거의 마무리**. 다음은 사용자 지시 — 디버그 UI 추가
작업.

## 2026-05-28 05:30 (claude)

**작업**: PR#45 — Sprint 2 §2.4 krex 휴게소 multi-kind 진입. 한 provider에서
**place + price + weather + notice** 4 kind 동시 처리 — 본 라이브러리 multi-
kind FeatureBundle/시계열 통합 검증.

**신규 파일** (2):
- `src/krtour/map/providers/krex.py` (~520 line):
  - Protocols 4종: `KrexRestAreaItem` / `KrexRestAreaPriceItem` / `KrexRest
    AreaWeatherItem` / `KrexTrafficNoticeItem`
  - 변환 함수 4종:
    - `rest_areas_to_bundles(items, *, fetched_at, reverse_geocoder=None)`
      → list[FeatureBundle] (place kind, category `06040101` TRANSPORT_REST_
      AREA_HIGHWAY_EX, marker `fast-food` P-06, PlaceDetail.place_kind=
      "rest_area" + facility_info{direction, highway_name})
    - `rest_area_prices_to_values(items, *, feature_id, source_record_key=
      None)` → list[PriceValue] (category 'food' → REST_AREA_FOOD/KRW or
      'fuel' → REST_AREA_FUEL/KRW/L)
    - `rest_area_weather_to_values(items, *, feature_id, source_record_key=
      None)` → list[WeatherValue] (REST_AREA_WEATHER, observed, ultra_short
      bucket)
    - `traffic_notices_to_bundles(items, *, fetched_at, reverse_geocoder=
      None)` → list[FeatureBundle] (notice kind, category `06010000`
      TRANSPORT_ROAD, marker `roadblock` P-13, NoticeDetail + normalize_
      notice_type alias 적용)
  - helpers: `_coord_or_none` / `_parse_numeric` (천단위 ',' 흡수) /
    `_reverse_geocode` / `_price_domain_for` / `_price_unit_for`
  - 상수: `KREX_PROVIDER_NAME` / 4 dataset_key / 2 category / 2 marker set
- `tests/unit/test_providers_krex.py` (~310 line, 18 case)

**변경 파일** (2):
- `src/krtour/map/providers/__init__.py` — krex 18 신규 식별자 re-export
- `docs/sprints/SPRINT-2.md` §2.4 — PR#45 4 함수 merged + multi-kind 통합
  검증 완료 표기

**테스트 (18 case)**:
- rest_areas: bundle count/order / feature metadata / source_record dataset /
  phone normalize / FK consistency
- rest_area_prices: fuel KRW/L / food KRW / bad category raises / 비숫자 raises
- rest_area_weather: observed metadata / count per metric
- traffic_notices: bundle metadata / alias normalize ('교통사고' → 'traffic_
  accident') / no coord global fallback / source_record / source_link primary
- 통합: `test_multi_kind_pipeline_uses_same_feature_id` — rest_areas → bundles
  → 그 feature_id로 prices/weather 호출이 일관 / 4 empty iterables

**ADR 정합**:
- ADR-006 — `python-krex-api` typed model 직접 import X (Protocol input only)
- ADR-009/018/019 — make_*/Feature.detail/aware datetime
- ADR-010 — WeatherValue 두 축 (observed/ultra_short)
- ADR-013/014 — PriceValue/WeatherValue bulk/BRIN 적재 호환 (적재 PR에서 검증)
- ADR-027 — NOTICE_TYPES + normalize_notice_type alias 활용
- ADR-041 — address utility (normalize_korean_text/phone/bjd_code) 적극

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **455 passed, 4 skipped** (PR#44 437 + 신규 18)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 47 source files

**Sprint 2 §2.4 완료**. 다음 PR#46 — KMA weather_alerts (notice FeatureBundle)
마무리.

## 2026-05-28 05:00 (claude)

**작업**: PR#44 — 디버그 UI ETL preview 라우터 + frontend 페이지. 운영자가
지금까지 구현한 provider 변환 함수를 디버그 UI에서 **수동 trigger**해서 변환
결과를 JSON으로 확인할 수 있음. **적재(DB write) 없음** — dry-run preview만.

**컨텍스트**: 사용자 지시 — "디버그 서버에서 지금까지 구현한 내용들 테스트
할 수 있도록 준비. 단 ETL 부분은 디버그 UI에서 수동으로 받아올 수 있도록
구성." PR#34/38/39/41/42/43에서 박힌 6개 dataset(datagokr 축제 / kma short·
nowcast·ultra_short_forecast / opinet stations·prices)을 fixture 기반으로
시연.

**신규 파일 — backend** (2):
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/etl_fixtures.py`
  (~340 line):
  - 6 Protocol-만족 dataclass + 6 fixture builder + 6 converter
  - `FIXTURE_REGISTRY: tuple[EtlFixtureEntry, ...]` (6 row)
  - `list_providers()` / `list_datasets(provider)` / `run_fixture_preview(
    provider, dataset)`
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/routers/etl.py`
  (~150 line):
  - `GET /debug/etl/providers` — provider/dataset 매트릭스
  - `GET /debug/etl/{provider}/datasets` — provider별 dataset 목록 (404)
  - `POST /debug/etl/{provider}/{dataset}/preview?source=fixture` — 변환
    결과 JSON. `source=live`는 501 (후속 PR)

**신규 파일 — frontend** (2):
- `packages/krtour-map-debug-ui/frontend/src/api/etl.ts` — TanStack Query
  hook: `useProviders` (60s staleTime), `useEtlPreviewMutation`
- `packages/krtour-map-debug-ui/frontend/src/app/etl/page.tsx` — provider/
  dataset/source 선택 UI + Preview 실행 버튼 + 결과 JSON 표시

**변경 파일** (4):
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/app.py` —
  `etl_router` include
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/routers/__init__.py`
  — re-export
- `packages/krtour-map-debug-ui/frontend/src/app/page.tsx` — `/etl` 링크
- `packages/krtour-map-debug-ui/openapi.json` — drift gate baseline 재생성

**테스트**:
- `packages/krtour-map-debug-ui/tests/test_etl_routers.py` (13 case):
  - `/providers` registry 정합 / kma 3 dataset 포함
  - `/datasets` opinet 2종 + unknown 404
  - `/preview` datagokr/kma_short/kma_nowcast/opinet_stations/opinet_prices
    happy path (각 variant + count 정합)
  - `/preview` unknown dataset 404 / `?source=live` 501 / `?source=bogus`
    422 (FastAPI Literal validator)
  - `debug_routes_enabled=False` → 404 unmount

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **437 passed, 4 skipped** (PR#43 424 + 신규 13)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 46 source files
- `python packages/krtour-map-debug-ui/scripts/export_openapi.py --check`
  → exit 0

**디버그 서버 사용 흐름** (사용자가 지금 바로):
1. `pip install -e packages/krtour-map-debug-ui` (PR#35 시점에 1회만 필요)
2. `uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8087`
3. browser → `http://127.0.0.1:8087/docs` (Swagger UI) 또는 `/debug/etl/
   providers`로 매트릭스 확인
4. 또는 frontend `cd packages/krtour-map-debug-ui/frontend && npm run dev` →
   `http://127.0.0.1:8610/etl` → provider/dataset 선택 후 Preview 실행
5. fixture 6 dataset 모두 변환 결과 JSON 확인 가능

**알려진 후속 작업**:
- `?source=live` 활성화 — provider client 호출 + .env API key 입력 절차
  (KMA `KMA_SERVICE_KEY` / OpiNet `OPINET_SERVICE_KEY` 등 dotenv 도입)
- 적재(`/admin/jobs` 라우터 + `infra/feature_repo.py`) — 별도 PR

## 2026-05-28 04:25 (claude)

**작업**: PR#43 — Sprint 2 §2.3 마무리. opinet `stations_to_bundles` (gas
station Feature) 추가. PR#34 datagokr 9-step 패턴과 동일 흐름.

**컨텍스트**: PR#42에서 PriceValue + opinet `prices_to_values`만 박았음. 본
PR로 주유소 자체 `Feature(kind=place)` 변환 완료 — Sprint 2 §2.3 (유가) 마무리.
호출자는 uni_id → feature_id 매핑을 stations_to_bundles의 결과를 통해 확립한
후 prices_to_values에서 동일 feature_id 사용.

**변경 파일** (3):
- `src/krtour/map/providers/opinet.py`:
  - `OpinetStationItem` Protocol (uni_id/station_name/brand_code/address/
    longitude/latitude/tel/lpg_yn)
  - `stations_to_bundles(items, *, fetched_at, reverse_geocoder=None) -> list
    [FeatureBundle]` (9-step)
  - `_station_item_to_bundle` private helper
  - `_coerce_bool_str` (Y/N/bool/None → bool|None)
  - 상수: `OPINET_STATION_DATASET_KEY="opinet_fuel_station_details"` /
    `OPINET_STATION_CATEGORY="06020000"` (TRANSPORT_FUEL) / marker `"fuel"`
    "P-08"
  - `Address`/`Coordinate`/`Feature`/`PlaceDetail`/`SourceRecord`/`SourceLink`
    / `make_*` / address utility 모두 활용 (ADR-006 wrapper 금지 + PR#37
    address utility 적극 활용)
- `src/krtour/map/providers/__init__.py` — opinet 6 신규 re-export
- `docs/sprints/SPRINT-2.md` §2.3 — PR#43 stations_to_bundles merged

**신규 파일** (1):
- `tests/unit/test_providers_opinet_stations.py` (15 case)

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **424 passed, 4 skipped** (PR#42 409 + 신규 15)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 44 source files

**ADR 정합**:
- ADR-006 wrapper 금지 — `python-opinet-api` typed model 직접 import X.
- ADR-041 (PR#37) — address utility 적극 사용 (normalize_korean_text,
  normalize_phone_number, normalize_bjd_code, extract_sigungu_code/sido_code).
- ADR-009 — make_feature_id/make_source_record_key/make_payload_hash 모두 사용.
- ADR-018 — `Feature.detail=PlaceDetail` instance.

**Sprint 2 §2.3 진행**:
- ✅ PriceValue DTO + make_price_value_key (PR#42)
- ✅ prices_to_values (PR#42)
- ✅ stations_to_bundles (PR#43)
- ⏳ infra/feature_repo.py 적재 (별도 PR — BRIN bulk 검증)

**다음 작업**: PR#44 — 디버그 UI ETL preview 라우터.

## 2026-05-28 04:00 (claude)

**작업**: PR#42 — Sprint 2 §2.3 진입. `PriceValue` DTO foundation +
`PriceDomain` enum + `make_price_value_key` + `providers/opinet.py prices_
to_values` (가격 시계열만, gas station feature는 별도 PR).

**컨텍스트**: ADR-034 9단계 ③ 진입. PR#38(WeatherValue) 패턴 그대로 적용 —
시계열 값 DTO + provider 변환 함수 분리. opinet 주유소 자체(`Feature`)는
infra 진입 후 별도 PR로.

**신규 파일** (4):
- `src/krtour/map/dto/price.py` (~140 line) — `PriceValue` DTO
  - feature_id / provider / price_domain / product_key (+ source_*)
  - product_name 한글 (예: '휘발유')
  - observed_at (시계열, KST aware)
  - value_number (Decimal NUMERIC(14,4)), unit 기본 'KRW'
  - normalization_version / payload / collected_at / source_record_key
  - field validator: aware datetime
  - model_validator: value_number ≥ 0
  - identity() tuple — (feature_id, provider, domain, product_key, observed_at)
- `src/krtour/map/providers/opinet.py` (~170 line)
  - `OpinetPriceItem` Protocol (uni_id/prodcd/price/trade_dt)
  - `prices_to_values(items, *, feature_id, source_record_key=None) -> list
    [PriceValue]`
  - `_parse_price_value` — 천 단위 구분자 "," 흡수
  - 상수: `OPINET_PROVIDER_NAME` / `OPINET_PRODUCT_KEY_MAP` (5종 매핑) /
    `OPINET_PRODUCT_NAME_KO`
- `tests/unit/test_dto_price.py` (9 case)
- `tests/unit/test_ids_price.py` (7 case)
- `tests/unit/test_providers_opinet.py` (10 case)

**변경 파일** (4):
- `src/krtour/map/dto/_enums.py` — `PriceDomain` enum 5값 (opinet_gas_station/
  rest_area_food/rest_area_fuel/toll_fee/admission_fee)
- `src/krtour/map/dto/__init__.py` — `PriceDomain` + `PriceValue` re-export
- `src/krtour/map/core/ids.py` — `make_price_value_key(*, feature_id,
  provider, price_domain, product_key, observed_at)` (`pv_{sha1[:20]}`,
  PRICE_VALUE_KEY_HASH_LENGTH=20)
- `src/krtour/map/core/__init__.py` — 2 신규 re-export
- `src/krtour/map/providers/__init__.py` — opinet 5 신규
- `docs/sprints/SPRINT-2.md` §2.3 — PR#42 prices_to_values merged

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **409 passed, 4 skipped** (PR#41 383 + 신규 26)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
  (auto-fix 1회 후 clean)
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 44 source files
- `lint-imports` / openapi drift — 영향 없음

**ADR-006 준수**: `python-opinet-api` typed model 직접 import X. `Opinet
PriceItem` Protocol로 input shape만 정의. uni_id → feature_id 매핑은 호출자
책임.

**알려진 후속 작업**:
- **PR#43 (Sprint 2 §2.3 마무리)**: opinet `stations_to_bundles` — gas station
  Feature(kind=place, category="06020000") + SourceRecord + SourceLink
- **PR#44+**: Sprint 2 §2.4 krex 휴게소 (multi-kind: place + price + weather
  + notice — PriceValue/WeatherValue 모두 활용)
- KMA 마무리: mid_forecast (텍스트 + AM/PM split) / weather_alerts (notice
  FeatureBundle)

## 2026-05-28 03:30 (claude)

**작업**: PR#41 — Sprint 2 §2.2 진행. KMA 초단기예보(`getUltraSrtFcst`)
변환 추가. PR#38 단기예보 패턴과 거의 동일, domain/style/timeline만
ultra_short. LGT(낙뢰) metric 추가.

**컨텍스트**: PR#39 nowcast 이후 KMA dataset 3번째. 같은 fcst_date/fcst_time
필드 shape이지만 forecast_style=ULTRA_SHORT, timeline=ULTRA_SHORT. 카테고리에
LGT(낙뢰)가 추가됨 — 초단기예보 전용.

**변경 파일** (4):
- `src/krtour/map/providers/kma.py`:
  - `KmaUltraShortForecastItem` Protocol — 단기예보와 동일 shape (base/fcst
    분리)
  - `ultra_short_forecast_to_weather_values(items, *, feature_id, source_
    record_key=None)`
  - `_ultra_short_forecast_item_to_weather_value` private helper
  - `KMA_METRIC_UNITS["LGT"] = "code"` + `KMA_METRIC_NAMES["LGT"] = "낙뢰"`
- `src/krtour/map/providers/__init__.py` — 2 신규 re-export
- `docs/sprints/SPRINT-2.md` §2.2 — PR#41 merged
- `tests/unit/test_providers_kma_ultra_short_forecast.py` (10 case 신규)

**Verification**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **383 passed, 4 skipped** (PR#40 373 + 신규 10)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 42 source files

**KMA dataset 진행 상황**:
- ✅ short_forecast (PR#38)
- ✅ ultra_short_nowcast (PR#39)
- ✅ ultra_short_forecast (PR#41) ← 본 PR
- ⏳ mid_forecast (텍스트 + AM/PM split, 별도 PR)
- ⏳ weather_alerts → notice FeatureBundle (별도 PR)

## 2026-05-28 03:00 (claude)

**작업**: PR#40 — `python-*-api` provider 라이브러리들의 본 lib 측 status를
최신화. `pyproject.toml [providers]` extra를 Sprint 그룹화 + Protocol 박힌
라이브러리는 본 lib 측 참조 명시. `docs/provider-contract.md` §4 책임 매트릭스
+ §12 git URL/sha 핀 status 표 갱신.

**컨텍스트**: 사용자 지시 "최신 python-*-api 반영". 본 라이브러리는 외부 lib
typed model을 직접 import하지 않음(ADR-006) — Protocol로만 정합 유지. 그러나
운영 single source of truth는 `pyproject.toml [providers]` + `provider-
contract.md`. 최근 작업들(PR#37 kraddr-base archive, PR#34 datagokr/PR#38/39
kma Protocol 박음, PR#25 knps `@06da125f`)이 반영된 일관 status가 필요.

**변경 파일** (4):
- `pyproject.toml [providers]` extra:
  - **`python-kraddr-base` 라인 완전 제거** (ADR-041 흡수 완료, PR#37)
  - Sprint 그룹화 + 코멘트로 Protocol 박힌 라이브러리 표시:
    - kraddr-geo (on-demand geocoder, ReverseGeocoder Protocol)
    - **Sprint 2 §2.1**: datagokr-api (CulturalFestivalItem Protocol, PR#34)
    - **Sprint 2 §2.2**: kma-api (KmaShortForecastItem/KmaUltraShortNowcast
      Item Protocol, PR#38/39) + airkorea + khoa + krforest
    - **Sprint 2 §2.3**: opinet-api
    - **Sprint 2 §2.4**: krex-api
    - **Sprint 2 §2.1 enrichment**: visitkorea-api (ADR-042 2차)
    - **Sprint 3**: knps (`@06da125f` 박음, PR#25) + krforest_trails +
      krheritage + krairport
    - **Sprint 4**: mois (ADR-024) + kasi
    - **Sprint 5**: mcst + standard data
- `docs/provider-contract.md`:
  - §4 책임 매트릭스 — 헤더 row 명시 + datagokr 1차 표 row 추가 (ADR-042) +
    visitkorea 행 enrichment 메모 + Protocol 박힌 라이브러리는 PR 번호 표시
    + kraddr-base 행 `~~strikethrough~~` + ADR-041 archive 메모
  - §12 status 표 (16 row) — 모든 provider의 `pyproject 핀` / `본 lib
    Protocol` / `활성 PR` / `메모` 4 컬럼. 최신 sha 갱신 절차 5단계 박음
    + `[providers]` extra optional 정책 명시
- `AGENTS.md` 식별자 표 — "Provider 라이브러리 git URL/sha 핀 status" 행
  추가 (`docs/provider-contract.md §12` 참조)

**Verification**:
- 본 PR은 docs/pyproject only — 소스 코드 영향 X.
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **373 passed, 4 skipped** (PR#39와 동일)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- openapi drift / lint-imports / mypy 영향 없음 (점검 생략 시 안전)

**다음 작업 권고**:
- 외부 lib 모니터링이 동반되면 `[providers]` extra의 `<sha>` placeholder
  들을 실 sha로 정정. 본 PR은 운영 정합 framework만 정리.
- Sprint 2 §2.2 KMA 마무리(ultra_short_forecast / mid_forecast / alerts) 또는
  Sprint 2 §2.3 opinet/§2.4 krex 진입 — provider 라이브러리 sha가 박혀 있지
  않아도 Protocol-only 작업이라 진행 가능.

## 2026-05-28 02:30 (claude)

**작업**: PR#39 — Sprint 2 §2.2 KMA 초단기실황 진입 + `core/weather.py` pure
헬퍼 5종. PR#38 weather foundation을 활용한 두 번째 KMA dataset + DB 없이
동작하는 weather card 합성 빌드 블록.

**컨텍스트**: PR#38로 WeatherValue DTO + KMA 단기예보가 들어간 뒤 후속.
`build_weather_card(client, ...)`는 `infra/feature_repo.py` 진입 후에 가능
하지만, pure helper(`pick_nowcast_value` / `pick_timeline_slice` 등)는 DB 없이
동작하므로 본 PR에 미리 박음. 후속 PR이 `core/weather.py`를 import해서 admin
UI / TripMate apps/web 양쪽 build_weather_card 합성에 사용.

**신규 파일** (3):
- `src/krtour/map/core/weather.py` (~150 line) — pure helpers:
  - `pick_nowcast_value(values, *, metric_key)` — nowcast/observed 중 가장
    최근 `observed_at` (collected_at tie-break)
  - `pick_timeline_slice(values, *, bucket)` — timeline_bucket 매칭 + valid_at
    오름차순 정렬 (valid_at=None 제외)
  - `group_by_metric_key(values)` — defaultdict(list), 입력 순서 유지
  - `filter_by_provider(values, *, provider)` — canonical provider name 필터
  - `latest_by_metric_key(values)` — metric별 최근 (observed > valid > collected)
- `tests/unit/test_providers_kma_nowcast.py` (8 case)
- `tests/unit/test_core_weather.py` (13 case)

**변경 파일** (4):
- `src/krtour/map/providers/kma.py`:
  - `KmaUltraShortNowcastItem` Protocol — base_date/base_time/nx/ny/category/
    obsr_value (단기예보의 fcst_date/fcst_time 없음, observed 성격)
  - `ultra_short_nowcast_to_weather_values(items, *, feature_id, source_
    record_key=None)` — `forecast_style=nowcast` + `timeline_bucket=ultra_
    short` + `observed_at = base_date+base_time` + `valid_at=None`
  - `_nowcast_item_to_weather_value` private helper
- `src/krtour/map/core/__init__.py` — 5 신규 re-export
- `src/krtour/map/providers/__init__.py` — kma 2 신규 (Protocol + 함수)
- `docs/sprints/SPRINT-2.md` §2.2 — PR#39 nowcast merged 표기

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **373 passed, 4 skipped** (PR#38 352 + 신규 21)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 42 source files
- `lint-imports` → 4 contracts kept, 0 broken
- openapi drift → exit 0

**알려진 후속 작업 (Sprint 2 §2.2 완료까지)**:
- `ultra_short_forecast_to_weather_values` (초단기예보)
- `mid_forecast_to_weather_values` (중기예보, 텍스트 형식 + AM/PM split)
- `weather_alerts_to_notice_bundles` (특보 → notice kind FeatureBundle)
- `WeatherCard` DTO + async `build_weather_card(client, feature_id)`
- 보조 providers (airkorea / krforest_weather / khoa_weather)
- Sprint 2 §2.5 `/features/{id}` 라우터에 weather 응답 wiring

## 2026-05-28 01:45 (claude)

**작업**: PR#38 — Sprint 2 §2.2 KMA 단기예보 1차 진입. `WeatherValue` DTO +
3 enum + `make_weather_value_key` + `providers/kma.py` `short_forecast_to_
weather_values` + 8 fixture / 32 case 테스트.

**컨텍스트**: PR#37 후 다음 한 작업 — Sprint 2 §2.2 (날씨 group). 본 PR이
weather 도메인 foundation. WeatherCard + `build_weather_card` + 보조 providers
(airkorea/khoa/krforest) + KMA의 나머지 dataset 4종은 별도 후속 PR로 분리.

**신규 파일** (4):
- `src/krtour/map/dto/weather.py` (~220 line) — `WeatherValue` DTO
  - ADR-010 두 축: `weather_domain` (WeatherDomain enum 16종) + `forecast_
    style` (7종) + `timeline_bucket` (3종, nullable)
  - metric: `metric_key` 표준 + source_metric_key / source_metric_name /
    metric_name (한글)
  - 시간축: issued_at / valid_at / valid_from / valid_until / observed_at /
    collected_at (모두 KST aware, ADR-019)
  - 값: value_number(Decimal) / value_text / unit / severity
  - 메타: normalization_version / payload(JSONB) / source_record_key
  - model_validator: `_check_value_present` + `_check_valid_range_order`
  - `identity()` tuple — unique key (timeline_bucket 제외, ADR-010)
- `src/krtour/map/providers/kma.py` (~270 line):
  - `KmaShortForecastItem` Protocol — KMA 단기예보 row shape
  - `short_forecast_to_weather_values(items, *, feature_id, source_record_
    key=None) -> list[WeatherValue]`
  - `_parse_kma_datetime(YYYYMMDD, HHMM) -> KST aware datetime`
  - `_parse_value(category, raw) -> (Decimal, text)` — `강수없음`/`적설없음`/
    `1mm 미만` 텍스트 표기 흡수
  - 상수: `KMA_PROVIDER_NAME` / `KMA_METRIC_UNITS` (18종) / `KMA_METRIC_
    NAMES` (한글 18종)
- `tests/unit/test_dto_weather.py` (12 case)
- `tests/unit/test_providers_kma.py` (11 case)
- `tests/unit/test_ids_weather.py` (9 case)

**변경 파일** (6):
- `src/krtour/map/dto/_enums.py` — `WeatherDomain` / `ForecastStyle` /
  `TimelineBucket` 3 enum 추가 (총 26 값)
- `src/krtour/map/dto/__init__.py` — re-export 4 신규
- `src/krtour/map/core/ids.py` — `make_weather_value_key` + `WEATHER_VALUE_
  KEY_HASH_LENGTH=20` 추가. `wv_{sha1[:20]}` 포맷. timeline_bucket 제외.
- `src/krtour/map/core/__init__.py` — 2 신규 re-export
- `src/krtour/map/providers/__init__.py` — kma 5 신규
- `docs/sprints/SPRINT-2.md` §2.2 — PR#38 1차 merged + 후속 PR 매핑

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration
  -q` → **352 passed, 4 skipped** (PR#37 320 + 신규 32)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → no issues found in 41 source files
- `lint-imports` → 4 contracts kept, 0 broken
- openapi drift → exit 0

**ADR-006 준수**:
- `python-kma-api` typed model을 직접 import하지 않음 — `KmaShortForecastItem`
  Protocol로 입력 shape만 정의.
- KMA 격자점 → weather feature_id 매핑은 본 모듈 책임 X — 호출자가
  `feature_id` 명시 전달.

**알려진 후속 작업**: KMA 나머지 4종 / core/weather.py pure helpers /
WeatherCard DTO + async build_weather_card / 보조 providers (airkorea /
krforest / khoa) / Sprint 2 §2.5 `routers/features.py`에 weather 응답 wiring.

## 2026-05-28 01:10 (claude)

**작업**: PR#37 — ADR-041 본격 구현. `python-kraddr-base` 의존 완전 제거 +
Address DTO 보강 + `core/address` utility 흡수 + `standard_data.py`에서 적극
활용. PR 머지 후 `python-kraddr-base` 라이브러리는 archive 후보.

**컨텍스트**: 사용자 지시 — `python-kraddr-base` 의존성을 완전히 삭제하고
Address 관련 DTO 및 utility를 본 라이브러리로 이전, 본 lib 내에서 적극 활용.
`PlaceCoordinate`는 제외 (ADR-041 명시).

**Pre-state**: `python-kraddr-base` dependency는 이미 `pyproject.toml`에서
주석 처리됨 (ADR-041 proposed/accepted 시점에 active dep 아님). 소스 import도
없음 (docs reference만). 본 PR이 "흡수"의 실 구현.

**신규 파일** (3):
- `src/krtour/map/core/address.py` (~280 line) — kraddr-base 흡수 utility:
  - `BjdParts` NamedTuple (sido/sigungu/eupmyeondong/ri) + compose helper
    (sido_code / sigungu_code / eupmyeondong_code / to_bjd_code)
  - `normalize_bjd_code(value)` — None/empty/int/str/dash/dot/9자리 padding
    모두 흡수, 10자리 숫자 아니면 ValueError
  - `is_valid_bjd_code(value)` — raise 없이 bool
  - `parse_bjd_code(value)` → `BjdParts`
  - `extract_sigungu_code(bjd_code)` / `extract_sido_code(bjd_code)` —
    5자리/2자리 추출
  - `normalize_phone_number(value)` — 한국 전화 표기 (02 지역 9/10자리,
    일반 10자리 3-3-4, 11자리 3-4-4, normalize 불가능 시 원본 trim)
  - `normalize_korean_text(value)` — NFKC + strip + 다중공백 1개로 (전각
    공백 흡수)
- `tests/unit/test_core_address.py` (~220 line, 30+ case)
- `tests/unit/test_dto_address.py` (~140 line, 32 case)

**변경 파일** (6):
- `src/krtour/map/dto/address.py` — `Address` 모델 풍부화:
  - 새 필드: `admin_dong_code` / `road_name_code` / `road_address_management_no`
    / `zipcode` / `sido_name` / `sigungu_name`
  - field validator: bjd_code/admin_dong_code(10자리) / sigungu_code(5자리) /
    sido_code(2자리) / zipcode(5자리) 모두 strict 자릿수 검증
  - model_validator: bjd_code prefix와 sido_code/sigungu_code 일관성 검증
    (둘 다 있을 때만, 한쪽 None이면 skip)
  - helper method: `is_complete()` (bjd + road or legal), `display()`
    (우선순위 road → legal → admin → '')
  - kraddr-base의 `LegalAddress` / `RoadAddress` / `AddressRegion`을 한
    모델로 통합 (분리 모델 안 만듦)
- `src/krtour/map/core/__init__.py` — 8 신규 식별자 re-export
- `src/krtour/map/providers/standard_data.py` — `_item_to_bundle`에서 utility
  적극 활용:
  - `normalize_bjd_code(rg.bjd_code)` — reverse_geocoder 응답에 dash 변형
    있어도 흡수
  - `extract_sigungu_code(bjd_code)` / `extract_sido_code(bjd_code)` —
    reverse_geocoder가 sigungu/sido 안 채워줘도 bjd_code에서 자동 추출
  - `normalize_korean_text` — road/legal/admin/festival_name/venue_name/
    organizer_name/provider_org_name 모두 전각공백 + 다중공백 흡수
  - `normalize_phone_number(organizer_tel)` — dash 표준 표기 강제
- `src/krtour/map/infra/models.py` — comment "kraddr.base.Address" →
  "krtour.map.dto.Address (ADR-041)"
- `docs/address-geocoding.md` §1 의존 라이브러리 정리 (kraddr-base 흡수 반영,
  `Coordinate` 단일 source 명시, PlaceCoordinate 제외 강조), §2 핵심 callable
  본 lib 타입으로 정정
- `docs/kraddr-base-types.md` — 상단에 SUPERSEDED note 추가 (ADR-041, PR#37,
  2026-05-27). 본문은 결정 이력 보존을 위해 유지.
- `AGENTS.md` 식별자 표 — Address DTO + 행정코드 utility 행 신설
- `docs/journal.md` / `docs/resume.md` / `docs/sprints/SPRINT-4.md` (계획
  반영)

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/
  integration -q` → **320 passed, 4 skipped** (PR#36 258 + 신규 62)
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
  (auto-fix 1회 후 clean)
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → Success: no issues found in 39 source files
- `lint-imports` → 4 contracts kept, 0 broken
- `python packages/krtour-map-debug-ui/scripts/export_openapi.py --check` →
  exit 0 (Address 변경은 backend 라우터/응답 schema에 영향 없음)

**ADR-041 명시적 제외 ("`PlaceCoordinate`는 제외")**:
- `core/address.py` 모듈 docstring + `dto/address.py` docstring 두 곳에서
  명시. 좌표 DTO는 `krtour.map.dto.coordinate.Coordinate` 단일 source.
- `SKILL.md` DO NOT 룰 26 ("kraddr-base의 PlaceCoordinate import 금지")가
  CI에서 강제 — import 시점 차단.

**알려진 후속 작업** (Sprint 4 prep + 별도 PR):
- `python-kraddr-base` 저장소 archive PR (그쪽 저장소).
- TripMate apps/etl이 본 라이브러리 새 Address/utility로 마이그레이션
  (별도 저장소).
- 다른 provider 모듈(`visitkorea`/`kma`/`opinet`/...) 진입 시 본 utility
  적극 활용.

## 2026-05-28 00:30 (claude)

**작업**: PR#36 — Sprint 2 §2.5 frontend skeleton 시작. Next.js 15 App Router
+ React 19 + TanStack Query + Zustand (ADR-025 + ADR-037 + ADR-043). `/debug/
version` + `/debug/health` 첫 wiring + Zustand map viewport store.

**컨텍스트**: PR#35로 backend FastAPI app + 2 라우터 + openapi.json drift gate
가 활성화된 뒤 frontend 측 진입. 본 PR 이전엔 `package.json`(의존성 placeholder)
+ `README.md` + `next.config.js` skeleton만. 본 PR이 첫 실제 source.

**신규 파일** (10):
- `next.config.ts` (TS로 마이그레이션, `next.config.js` 삭제) — `transpile
  Packages: ["@krtour/map-marker-react"]` + `productionBrowserSourceMaps:
  false` + `poweredByHeader: false`
- `tsconfig.json` — Next.js 15 권장 + paths `"@/*": ["./src/*"]`
- `src/api/client.ts` — fetch wrapper, `BASE_URL` (env `NEXT_PUBLIC_KRTOUR_MAP
  _DEBUG_UI_API` 또는 `http://127.0.0.1:8087` 기본), `HealthResponse` /
  `VersionResponse` TS interface, `fetchHealth` / `fetchVersion`,
  `DebugUiApiError`
- `src/api/queries.ts` — TanStack Query hook (`useHealth` 5초 polling /
  `useVersion` staleTime 60s) + `queryKeys` 컨벤션
- `src/state/map.ts` — Zustand `useMapStore` (viewport / selectedFeatureId /
  activeCategoryCodes Set + actions setViewport/resetViewport/toggleCategory/
  clearCategories). DEFAULT_VIEWPORT 한국 본토 중심 (대전 부근)
- `src/providers/query-client-provider.tsx` — `"use client"` +
  `AppQueryClientProvider` (refetchOnWindowFocus: false / retry: 1)
- `src/app/layout.tsx` — Root layout + `metadata` + `<html lang="ko">` +
  `AppQueryClientProvider` wrapping
- `src/app/page.tsx` — `"use client"` Landing page. health/version useQuery
  hook 호출 + Zustand viewport 표시 + 미세 이동 / 초기화 버튼

**변경 파일** (5):
- `packages/krtour-map-debug-ui/frontend/package.json` — `_comment_dependencies`
  placeholder 제거, `zustand: ^5.0.0` 추가 (ADR-037)
- `packages/map-marker-react/package.json` — `"private": true` 박음 (ADR-043
  npm 게시 보류), `publishConfig.access` 제거, description에 ADR-043 명시
- `packages/krtour-map-debug-ui/frontend/.env.example` — default backend port
  `8600` → `8087` (PR#35 DebugUiSettings.port 기본과 정합)
- `packages/krtour-map-debug-ui/frontend/README.md` — Sprint 1 skeleton note →
  PR#36 진입 status로 정정 + ADR-043 명시
- `docs/sprints/SPRINT-2.md` §2.5 frontend block — PR#36 merged + 다음 단계
  매핑

**삭제 파일** (1):
- `packages/krtour-map-debug-ui/frontend/next.config.js` — `next.config.ts`로
  대체

**Verification (python 측, 변동 없음)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration`
  → 258 passed, 4 skipped
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
- `python packages/krtour-map-debug-ui/scripts/export_openapi.py --check` →
  exit 0 (backend 영향 없음 → drift 없음)

**Frontend 측 검증은 follow-up**: CI에 frontend type-check/lint step 추가 +
`openapi-typescript`로 `src/api/types.ts` 자동 생성 + 실 maplibre-vworld
컴포넌트 통합은 별도 PR.

## 2026-05-27 23:50 (claude)

**작업**: PR#35 — Sprint 2 §2.5 debug/관리 UI backend 첫 라우터 + OpenAPI
drift gate 활성화 (ADR-031 + ADR-035 + ADR-038).

**컨텍스트**: `packages/krtour-map-debug-ui/`는 Sprint 1까지 `pyproject.toml`
+ `scripts/export_openapi.py` skeleton만 존재. 본 PR이 첫 실제 FastAPI app +
2개 라우터 + openapi.json baseline 추가. `/features/...` + `/admin/...`은
infra(`feature_repo.py` / `import_jobs`) 의존이라 후속 PR.

**신규 파일** (7):
- `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/__init__.py` —
  namespace package + `__version__ = "0.2.0-dev"`.
- `py.typed` — PEP 561 marker.
- `settings.py` — `DebugUiSettings` (pydantic-settings, host/port/log_level/
  debug_routes_enabled, `KRTOUR_MAP_DEBUG_UI_*` env prefix).
- `app.py` — `create_app(settings) -> FastAPI` factory + 모듈 레벨 `app`.
- `routers/__init__.py` + `health.py` + `version.py` — 2 라우터 + 응답 schema
  Pydantic 모델 (`HealthResponse` / `VersionResponse`, `extra="forbid"`).
- `tests/test_routers.py` — pytest + httpx ASGI 테스트 6건 (200 OK / schema
  정합 / `debug_routes_enabled=False`로 unmount / openapi 노출 / title-version
  매칭).
- `packages/krtour-map-debug-ui/openapi.json` — drift gate baseline (FastAPI
  `app.openapi()` 직접 결과, sort_keys + indent=2).

**변경 파일** (4):
- `pyproject.toml` `tool.mypy.mypy_path` — `"src"` → `"src:packages/krtour-map-
  debug-ui/src"` (PEP 420 namespace 통합).
- `.github/workflows/openapi.yml` — `continue-on-error: true` 제거, debug-ui
  graceful skip block 제거 (정상 install 가능 시점 진입).
- `.github/workflows/ci.yml` — debug-ui editable install step + pytest step
  추가 (main lib coverage gate에는 영향 X).
- `docs/sprints/SPRINT-2.md` §2.5 — PR#35 merged + 후속 라우터 매핑.

**Verification (local)**:
- `pytest tests/ packages/krtour-map-debug-ui/tests/ --ignore=tests/integration`
  → **258 passed, 4 skipped** (PR#34 252 + debug-ui 6).
- `ruff check src/ tests/ packages/krtour-map-debug-ui/` → All checks passed
  (auto-fix 1회 후 clean — `@pytest.fixture()` 괄호 제거 3건).
- `mypy --strict src/krtour/map packages/krtour-map-debug-ui/src/krtour/
  map_debug_ui` → Success: no issues found in 38 source files.
- `lint-imports` → 4 contracts kept, 0 broken (debug-ui는 main lib 룰과 독립).
- `python packages/krtour-map-debug-ui/scripts/export_openapi.py --check` →
  exit 0 (drift 없음).

**OpenAPI 노출**:
- `GET /openapi.json` — schemas 2 (HealthResponse + VersionResponse) + paths
  2 (/debug/health, /debug/version).
- `info.title = "krtour-map-debug-ui"`, `info.version = "0.2.0-dev"`,
  `servers = []` (호스트별 drift 회피).

**알려진 후속 작업**: `/features/*` + `/admin/*` 라우터는 infra layer 진입
PR(`feature_repo.py`, `import_jobs` 테이블)과 함께.

## 2026-05-27 23:20 (claude)

**작업**: PR#34 — Sprint 2 §2.1 1차 provider 진입. ADR-042 datagokr 전국
문화축제표준데이터 → `FeatureBundle` 변환 함수 + Protocol + fixture 5건 +
unit test 14건. ADR-038 CI green 게이트 active 후 첫 PR.

**컨텍스트**: ADR-042로 축제 1차 source가 visitkorea TourAPI에서 datagokr
표준데이터로 변경. `python-datagokr-api` provider 라이브러리는 외부 별도
저장소이고, 본 라이브러리는 ADR-006(wrapper 금지)에 따라 그 typed model을
직접 import하지 않는다 — 대신 `CulturalFestivalItem` Protocol로 입력 shape만
정의. provider 라이브러리는 자기 모델이 본 Protocol을 만족하도록 필드 이름
맞춤.

**신규 파일** (2):
- `src/krtour/map/providers/standard_data.py` (~340 line)
  - `CulturalFestivalItem` `Protocol` (14 필드 — management_no/festival_name/
    start_date/end_date/latitude/longitude/road_address/jibun_address/
    organizer_name/organizer_tel/data_reference_date/provider_org_name 등)
  - `ReverseGeocodeResult` / `ReverseGeocoder` Protocol — 좌표→bjd_code helper
    plug-in 인터페이스
  - `cultural_festivals_to_bundles(items, *, fetched_at, reverse_geocoder=None)
    -> list[FeatureBundle]`
  - `_item_to_bundle` 내부 helper — 9 단계 (Coordinate / reverse_geocode /
    Address / raw_data canonical / payload_hash / source_record_key /
    feature_id / Feature+EventDetail / SourceRecord+SourceLink+Bundle).
  - 상수: `DATASET_KEY_CULTURAL_FESTIVALS = "datagokr_cultural_festivals"` /
    `FESTIVAL_CATEGORY = "01000000"` (TOURISM 대분류, ADR-042) /
    `FESTIVAL_MARKER_ICON = "star"` / `FESTIVAL_MARKER_COLOR = "P-11"`.
- `tests/unit/test_providers_standard_data.py` (~390 line, 14 case):
  - 5 fixture (`_F1`/`_F2`/`_F3` 좌표 있음 + `_F4_NO_COORD`/`_F5_NO_COORD_
    MINIMAL` 좌표 nullable).
  - happy path (bundle 필드 정합 / EventDetail 날짜·kind / SourceRecord
    canonical / SourceLink PRIMARY).
  - 좌표 nullable → `Feature.coord=None` + `feature_id` `global` fallback.
  - minimal nullable fixture — Feature 여전히 valid.
  - bundle FK consistency (PR#26 model_validator 가동).
  - 결정성 (같은 입력 같은 ID).
  - payload 변경 시 `raw_payload_hash` + `source_record_key`는 다르나
    `feature_id`는 같음 (이력 보존).
  - `EventDetail.starts_on > ends_on` reject.
  - naive `fetched_at` reject (ADR-019).
  - `ReverseGeocoder` 적용 시 `Address.bjd_code` 채워짐 + `feature_id`가
    bjd_code 기반으로 변경.
  - `ReverseGeocoder` lookup이 좌표 없을 때 호출 안 됨 (불필요 lookup 회피).

**변경 파일** (3):
- `src/krtour/map/providers/__init__.py` — `standard_data` re-export (`__all__`
  4 식별자 + 4 상수).
- `docs/event-feature-etl.md` §7.1 collect — datagokr 1차 source 예시 보강
  + §7.1.5 visitkorea enrichment 별도 PR placeholder.
- `docs/sprints/SPRINT-2.md` §2.1 — PR#34 merged 표기.

**Verification (local)**:
- `pytest tests/ --ignore=tests/integration` → **252 passed, 4 skipped**
  (PR#29 238 + PR#34 신규 14).
- `ruff check src/ tests/` → All checks passed (auto-fix 1회 후 clean).
- `mypy --strict src/krtour/map` → Success: no issues found in 32 source files.
- `lint-imports` → 4 contracts kept, 0 broken.

**CI 게이트 (ADR-038)**: 본 PR이 ADR-038 머지 후 첫 PR — branch protection
rules가 켜져 있으면 push 후 ci/lint/openapi 워크플로우 자동 실행, 1 review
approval 필요. (사용자 측 GitHub Settings 활성 여부에 의존.)

## 2026-05-27 22:50 (claude)

**작업**: PR#33 — ADR-035~043 9건 일괄 accepted 전환. PR#16(027~034 일괄)과
동일 패턴. proposed → accepted, 1차 implement는 ADR별 매핑된 Sprint에서.

**변경 파일** (5):
- `docs/decisions.md` — 9개 ADR 상태 `accepted (PR#33, 2026-05-27)`. ADR-038은
  "쓰지마" reverse note 유지, ADR-043은 ADR-029 supersede note 유지.
- `AGENTS.md` — ADR accepted/proposed 행 정정 (001~028, 030~043 accepted /
  proposed 비어 있음 / 다음 번호 044).
- `CLAUDE.md` — ADR 현황 "001~043 모두 accepted" + implementation 시점 매핑.
- `docs/agent-guide.md` — 다음 ADR 번호 035 → 044 정정.
- `docs/resume.md` — PR#33 완료 표기 + 다음 한 작업 (PR#34 ADR-038 CI 게이트
  + datagokr provider) 박음.

**Implementation 시점 매핑**:
- ADR-038 (CI/CD 재활성화) — 즉시. 사용자 측 GitHub Settings branch protection
  rules 활성 + 본 라이브러리 다음 PR(PR#34)부터 CI green 요구.
- ADR-042 (datagokr 표준데이터 축제) — SPRINT-2 §2.1 (PR#34 후보).
- ADR-035 / 037 / 043 — SPRINT-2 §2.5 debug UI 첫 라우터 PR (PR#35 후보).
- ADR-036 (maplibre-vworld-js 분리) — SPRINT-3 후반.
- ADR-039 / 040 / 041 — SPRINT-4 진입 prep.

**검증**: docs-only PR. 모든 ADR이 "accepted" 상태 + 다음 후보 번호 ADR-044
정합 확인.

## 2026-05-27 22:30 (claude)

**작업**: PR#32 거버넌스 보강 + ADR-035~043 proposed 일괄. 운영 단계 진입에
따른 사용자 지시 8건 + 정책 reverse 1건을 ADR 9건 + 거버넌스 문서 sweep으로
박음.

**컨텍스트**: PR#31(codegraph MCP 등록) 머지 직후 사용자 지시:
- REST API는 디버그/관리/운영 UI 용도로 프로덕션 환경에서도 활용
- 지도 = `maplibre-vworld-js` 별도 라이브러리(v0.1.0), 공통은 상류 / TripMate
  전용만 본 저장소
- Web UI는 유지보수 (통계/운영/관리/튜닝) 기능 보완
- 프런트엔드 state는 TanStack Query + Zustand
- **GitHub Actions CI/CD 재활성화** (2026-05-26 "쓰지마" 지시 reverse)
- CLI 중복 실행 위험 명령은 mutex 박음
- ADR 035+ 진행, npm 게시 보류 (`@krtour/map-marker-react`), 나머지 수용
- Backup/Restore + UI (핫스왑 스타일)
- `python-kraddr-base` 흡수 + 라이브러리 폐기 예정 (`PlaceCoordinate`는 제외)
- 전국관광지정보표준데이터 / 전국문화축제표준데이터 — `python-datagokr-api`
  경유, 축제는 표준데이터 primary로 전환

**ADR 9건**:
- ADR-035 디버그/관리 REST API 프로덕션 admin 운영 확장 (ADR-005/020 amendment)
- ADR-036 `maplibre-vworld-js` 라이브러리 분리 + v0.1.0 (TripMate 전용만 본
  저장소)
- ADR-037 Frontend state — TanStack Query + Zustand
- ADR-038 GitHub Actions CI/CD 재활성화 (2026-05-26 "쓰지마" 지시 reverse,
  branch protection rules 활성)
- ADR-039 CLI mutex — PostgreSQL advisory lock 기반
- ADR-040 Backup/Restore + 핫스왑 UI (1차 cold restore → Sprint 5 hot-swap)
- ADR-041 `python-kraddr-base` 코드 흡수 + 라이브러리 폐기 (`PlaceCoordinate`
  제외)
- ADR-042 datagokr 표준데이터 — 축제 1차 source 전환 + 관광지 표준데이터 추가
- ADR-043 `@krtour/map-marker-react` npm 게시 보류 (ADR-029 supersede)

**거버넌스 문서 sweep**:
- AGENTS.md ADR proposed 목록 + 디버그 REST API 정책 (admin/ops prefix) +
  Frontend stack (maplibre-vworld-js + TanStack + Zustand + `private` npm) +
  DO NOT 룰 20~22 (CLI mutex / npm 게시 / PlaceCoordinate import) + 작업 후
  체크리스트 (codegraph 영향도 + CI green) 추가.
- CLAUDE.md ADR 현황 035~043 proposed 목록 + 절대 금지 5개 §5 보강.
- SKILL.md DO NOT 룰 23~26 추가 (CI green 머지 / CLI mutex / npm 게시 /
  PlaceCoordinate import).
- docs/sprints/SPRINT-2.md §2.1 축제 1차 source = datagokr 전환 + §2.5 admin
  라우터 prefix + Frontend TanStack/Zustand + §2.8/§2.9 신규 ADR implementation
  매핑.
- docs/sprints/SPRINT-4.md §2.8 CLI mutex 첫 도입 + §2.9 kraddr-base 흡수
  prep + §2.10 Backup/Restore prep.
- docs/event-feature-etl.md 1차 source 표 변경.
- docs/decisions.md ADR-005/020/029 supersede note.

**변경 파일 (9)**:
- `docs/decisions.md` — ADR-035~043 9건 신규 (proposed) + ADR-005/020/029
  supersede note
- `AGENTS.md` — 다수 절 (식별자/디버그 REST/Frontend/DO NOT/체크리스트)
- `CLAUDE.md` — ADR 현황 + 절대 금지 5개
- `SKILL.md` — DO NOT 룰 23~26 추가
- `docs/sprints/SPRINT-2.md` — §2.1 datagokr 1차 / §2.5 admin 라우터 + frontend
  state / §2.8/§2.9 신규 ADR 매핑
- `docs/sprints/SPRINT-4.md` — §2.8/2.9/2.10 CLI mutex + kraddr-base + backup
  prep
- `docs/event-feature-etl.md` — 1차 source 표 변경
- `docs/journal.md` — 본 엔트리
- `docs/resume.md` — 다음 한 작업 갱신

**검증**: docs-only PR. ADR proposed → 사용자 review → 후속 PR로 accepted
전환 + 코드 implement.

## 2026-05-27 21:55 (claude)

**작업**: PR#30 머지 직후 후속 — `docs/codegraph-worktree.md`에 §6 "MCP
서버 등록" + §7 "Code Style & Rules (수정 전 영향도 평가)" 추가. AGENTS.md /
SKILL.md / CLAUDE.md / agent-guide.md에 동일 룰 cross-reference.

**컨텍스트**: 사용자 지시 — `~/.claude.json` `mcpServers`에 codegraph 등록할
수 있도록 snippet을 문서에 박을 것, 그리고 `codegraph_explore` 도구로 컴포넌트
수정 전 영향도를 평가하는 룰을 추가할 것.

**중요 fact-check**: 사용자가 적어준 snippet은 `args: ["-y", "@colbymchenry/
codegraph", "mcp"]`였으나 `codegraph` CLI에 `mcp` 서브커맨드는 없음. 실제 MCP
서버 명령은 `codegraph serve --mcp`. `codegraph install --print-config claude`
가 출력하는 공식 snippet으로 보정:

```json
{
  "mcpServers": {
    "codegraph": {
      "type": "stdio",
      "command": "codegraph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

사용자 의도(npx 대안)는 §6.2에 살림 — `["npx", "-y", "@colbymchenry/
codegraph", "serve", "--mcp"]`. WSL2 `/mnt`에서는 `--no-watch` 추가 권장 (§6.4).

**변경 파일** (5):
- `docs/codegraph-worktree.md` — §5 "CodeGraph Commands" 빠른 참조 + §6 "MCP
  서버 등록" 4 subsection (글로벌 / npx / 다른 에이전트 `codegraph install
  --print-config` / WSL2 `--no-watch`) + §7 "Code Style & Rules — 수정 전
  영향도 평가" 신설. §6→§8 / §7→§9 / §8→§10 / §9→§11 renumber.
- `AGENTS.md` — "에이전트 worktree + codegraph (필수)" 절에 MCP snippet +
  "Code Style & Rules — 수정 전 영향도 평가 (필수)" subsection 추가.
- `CLAUDE.md` — codegraph MCP 등록 + `codegraph_explore` 사용 룰 1 단락.
- `SKILL.md` "에이전트 worktree + codegraph" 절에 CodeGraph Commands 빠른
  참조 + MCP 등록 + DO 룰 subsection 3개 추가.
- `docs/agent-guide.md` §7.3 DTO 변경 체크리스트 첫 항목으로 "수정 전 영향도
  평가" 추가.

**검증**:
- `codegraph install --print-config claude` → 본 PR snippet과 일치.
- `codegraph serve --help` → `--mcp` 플래그 존재, `--no-watch`도 있음.
- `codegraph --help` → `mcp`라는 subcommand 없음 (있는 건 `serve`만) —
  사용자 초안 `mcp` 인자는 동작 X, 본 PR에서 `serve --mcp`로 보정.

## 2026-05-27 21:30 (claude)

**작업**: `docs/codegraph-worktree.md` 신규 + AGENTS/CLAUDE/SKILL/agent-guide/
dev-environment에 agent별 worktree + [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)
운영 룰 박음. `.gitignore`에 `.codegraph/` 추가. 본 PC에 codegraph v0.9.5
글로벌 설치 + `.codegraph/` 인덱스 초기화(64 파일, 719 노드, 1,205 edge).

**컨텍스트**: PR#29 머지 직후 사용자 지시 — "AI 에이전트별 고정 worktree
유지 + codegraph 인덱스 1개"를 표준으로 박을 것. 작업 사이에 브랜치만 새로
딴다(`git switch -c feat/<topic> main`). worktree 명명: ChatGPT Codex →
`~/dev/geo-codex`, Claude Code → `~/dev/geo-claude`, Google Antigravity 2.0
→ `~/dev/geo-antigravity`. `geo-*` 접두사는 형제 저장소 (`python-kraddr-geo`
등)와 공통 — 향후 다른 repo에도 동일 패턴 권장.

**신규 파일** (1):
- `docs/codegraph-worktree.md` (~170 line) — 9 절: 왜 agent별 worktree,
  명명 규약, 최초 setup (npm + `codegraph init -i` + 선택적 `codegraph
  install`), 작업 사이클 (sync 위주 — init 재실행 X), 자주 쓰는 커맨드
  (query/callers/callees/impact), CI 무관성, WSL ext4 + NTFS data 호환,
  사용자 직접 작업 시 메인 worktree 사용 규약, 참고.

**변경 파일** (6):
- `.gitignore` — `.codegraph/` 추가 + 주석 (SQLite worktree-local index).
- `AGENTS.md` — "에이전트 worktree + codegraph (필수)" 절 신설 (개발 환경
  정책 직후, 진입 순서 직전). 워크트리 이름 표 + 운영 룰 + 작업 사이클 +
  최초 설치 코드 블록.
- `CLAUDE.md` — "Claude Code 전용 worktree" 1 단락 추가 (`geo-claude`
  명시 + 다른 두 에이전트 worktree 이름 참고).
- `SKILL.md` §1 "개발 환경 (PC, WSL)" 뒤 "에이전트 worktree + codegraph"
  서브절 추가 (1 단락 요약 + 본문 링크).
- `docs/agent-guide.md` §1.1 "자기 worktree로 이동" 신설.
- `docs/dev-environment.md` §2.1에 agent worktree에서도 `data` 심볼릭
  링크 박는다는 1 단락 추가.

**codegraph 실제 동작 확인**:
- `npm i -g @colbymchenry/codegraph` → v0.9.5 설치.
- `codegraph init -i` (F:\dev\python-krtour-map) → `.codegraph/codegraph.db`
  SQLite (WAL 모드, 1.31 MB) 생성. 64 파일 / 719 노드 / 1,205 edge.
- `codegraph status` → "Index is up to date".
- `codegraph query make_feature_id` → `src/krtour/map/core/ids.py:73` 정확
  히 위치 + import 출처도 같이 반환 (function/variable/import 3 hit).

**검증**:
- `.gitignore`에 `.codegraph/`이 박혀 있어 SQLite DB는 커밋되지 않음 (`git
  status`에서 .codegraph 제외 확인).
- `codegraph install`은 본 PR에서 실행하지 않음 — 에이전트별 MCP 설정은
  각 에이전트(또는 사용자)가 자기 환경에서 1회 실행 권장.

## 2026-05-26 02:00 (claude)

**작업**: PR#29 — Sprint 2 prep 2. `core/scoring.py` (ADR-016 Record Linkage)
+ `core/providers.py` (CANONICAL_PROVIDER_NAMES + normalize_provider_name).
`core/weather.py`는 WeatherValue DTO 의존이라 Sprint 2 KMA PR로 연기.

**컨텍스트**: PR#28 머지(2026-05-26 12:53) 후 Sprint 2 첫 provider PR 진입
직전 마지막 prep. ADR-016 dedup scoring (자동 병합 임계값 0.85, 수동 검토
0.65) + provider 이름 정규화 (alias → canonical, ADR-024/028). `python-knps-
api`/`python-mois-api` 등 모든 형제 provider 카탈로그 박음.

**신규 파일** (4):
- `src/krtour/map/core/providers.py` (~120 line) — `CANONICAL_PROVIDER_NAMES`
  18종 + `PROVIDER_ALIASES` 24종 (krmois→mois ADR-024 포함) +
  `normalize_provider_name(value)` (raise on unknown — silent fallback 금지) +
  `is_known_provider(value)` (lenient bool 반환).
- `src/krtour/map/core/scoring.py` (~270 line) — ADR-016:
  - 가중치 상수: `WEIGHT_NAME=0.45` / `WEIGHT_SPATIAL=0.35` /
    `WEIGHT_CATEGORY=0.20` (합 1.0 assert).
  - 임계값 상수: `THRESHOLD_AUTO=0.85` / `THRESHOLD_MANUAL=0.65` /
    `SPATIAL_DECAY_METERS=50.0`.
  - `normalize_kr_place_name(name)` — NFKC + lower + 괄호 제거 + 모든 공백
    제거 (한국어 장소명 공백 변형 흡수: "서울 시청"/"서울시청"/"서울 특별 시청"
    모두 "서울시청" 또는 "서울특별시청").
  - `name_similarity(a, b)` — jellyfish.jaro_winkler_similarity (정규화 후).
  - `haversine_meters(a, b)` — Python 측 좌표 거리 (PostGIS ST_DWithin은
    별도 — ADR-012).
  - `spatial_similarity(a, b)` — `exp(-d / 50)`.
  - `category_similarity(a_tags, b_tags)` — Jaccard.
  - `score_pair(*, name_a, name_b, coord_a, coord_b, cat_a, cat_b)` — 종합
    점수 (keyword-only).
  - `DedupDecision` (AUTO_MERGE / MANUAL_REVIEW / KEEP_SEPARATE 상수) +
    `classify_decision(score)`.
- `tests/unit/test_providers.py` (8 case) — canonical 카탈로그 정합 +
  alias 검증 + ADR-024 krmois→mois + unknown reject + lenient is_known.
- `tests/unit/test_scoring.py` (24 case) — ADR-016 가중치/임계값 정합 +
  normalize_kr_place_name (4종) + name/spatial/category sim (각 4종 +
  haversine 서울-부산 325km) + score_pair (3종) + classify_decision
  parametrize 8종.

**변경 파일** (2):
- `pyproject.toml` — `jellyfish>=1.0` 본 의존 추가 (ADR-016
  jaro_winkler_similarity).
- `src/krtour/map/core/__init__.py` — providers/scoring 18 신규 식별자
  re-export.

**왜 core/weather.py는 본 PR에 없는가**:
- `build_weather_card`는 `WeatherValue`/`WeatherCard` DTO 의존.
- `WeatherValue` DTO는 Sprint 2 KMA PR (PR#31)에서 추가 — 그때 `core/
  weather.py` 함께 박음.
- 본 PR은 detail/weather/price DTO 없이 동작 가능한 scoring + providers만.

**verification**:
- `python -m pytest tests/ -q --ignore=tests/integration` → **238 passed,
  4 skipped** (PR#28 199 + 신규 32 + tasks 미세 변동).
- `python -m ruff check src/ tests/ alembic/` → All checks passed.
- `python -m mypy --strict -p krtour.map` → Success, **31 source files**.
- `import-linter` → **4 contracts kept, 0 broken**.

**ADR 적용**:
- ADR-016 (Record Linkage) — 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 +
  master 선정 룰 (TODO Sprint 3 dedup PR). 본 PR은 scoring 함수만 — master
  선정/병합은 후속.
- ADR-024 (canonical name) — `python-mois-api` (`krmois` 거부, alias로
  자동 변환).
- ADR-028 (knps) — `python-knps-api` canonical 등록.

**TripMate docs 참조** (`docs/tripmate-integration.md`):
- §10 structlog 키 표준 — `provider` 키 값은 `normalize_provider_name(...)`
  결과여야 한다. Sprint 2 첫 provider PR에서 wiring.
- §6.1 dedup 검토 — `dedup_review_queue`가 ADR-016 MANUAL_REVIEW 결정의
  output. Sprint 3 dedup PR에서 통합.

**다음 PR (PR#30, Sprint 2 1단계 ADR-034)**:
- `src/krtour/map/providers/visitkorea/__init__.py` — 축제 변환 함수
  (`festival_to_bundle`).
- `src/krtour/map/infra/feature_repo.py` — raw SQL `_SQL` 상수 + upsert
  (ADR-004 + ADR-013).
- `alembic/versions/0003_feature_event_details.py` — event detail 테이블.
- VisitKorea raw → FeatureBundle 통합 fixture 테스트.

---

## 2026-05-26 01:00 (claude)

**작업**: PR#28 Sprint 2 prep — `src/krtour/map/infra/models.py` (SQLAlchemy 2
declarative + GeoAlchemy2) + Alembic 인프라 (`alembic.ini` + `alembic/env.py`
async-compatible + `alembic/script.py.mako`) + 첫 2 revision (0001 schemas+
extensions, 0002 features+source tables).

**컨텍스트**: PR#27 머지(2026-05-25 23:41, codex `7d6136a` 후속 sweep 포함) 후
Sprint 2 진입 준비. ADR-034 1단계 visitkorea 축제 PR (PR#30)이 의존할 DB
schema + ORM 매핑 + Alembic 인프라 미리 박는다. detail 5종/opening_hours/
weather/price/file/ops.* 테이블은 각자 owning provider PR에서 추가.

**신규 파일** (8):
- `alembic.ini` — Alembic config. DSN은 env.py가 `KRTOUR_MAP_PG_DSN`에서
  read → asyncpg로 정규화. post_write_hooks ruff format/check.
- `alembic/env.py` — async-compatible. `async_engine_from_config` +
  `NullPool` + `SET search_path = public, x_extension` (ADR-008) + offline/
  online mode. `target_metadata = infra.models.metadata`.
- `alembic/script.py.mako` — 새 revision template.
- `alembic/versions/0001_initial_schemas_and_extensions.py` — 4 schema
  (feature/provider_sync/ops/x_extension) + 3 extension (postgis/pg_trgm/
  pgcrypto) on `x_extension` (ADR-008). postgis는 image 기본 public 설치를
  DROP CASCADE 후 재생성.
- `alembic/versions/0002_features_and_source_tables.py` — features (ADR-012
  `coord_5179` STORED generated column + 10 indexes incl. GiST/GIN partial)
  + source_records (UNIQUE 5-tuple + 4 indexes incl. BRIN imported/fetched_at)
  + source_links (FK CASCADE/RESTRICT + 3 indexes) + provider_sync_state
  (composite PK + partial index).
- `src/krtour/map/infra/models.py` (~290 line) — `Base` declarative +
  `metadata` (naming convention 박힘) + 4 row class (FeatureRow / SourceRecord
  Row / SourceLinkRow / ProviderSyncStateRow). Geoalchemy2 Geometry(POINT
  4326/5179, GEOMETRY 4326). CheckConstraint kind/status/coord_pair.
- `tests/integration/test_alembic_upgrade.py` (6 case) — testcontainers
  PostGIS + `alembic upgrade head` subprocess + 4 schema/3 extension/features
  컬럼/coord_5179 STORED 검증/source 3 tables/핵심 5 인덱스 존재.

**변경 파일** (2):
- `pyproject.toml` — `alembic>=1.13` 본 의존 추가 (ADR-007).
- `src/krtour/map/infra/__init__.py` — Base/metadata/FeatureRow/SourceRecord
  Row/SourceLinkRow/ProviderSyncStateRow 6 신규 식별자 re-export.

**왜 detail/weather/price/file 테이블은 본 PR에 없는가**:
- 각자 owning provider PR에서 추가 — opening_periods는 VisitKorea PR (PR#30)
  에서, weather_values는 KMA PR (PR#31)에서, price_values는 OpiNet PR (PR#32)
  에서, feature_files는 첫 사진 업로드 provider PR에서.
- 본 PR은 visitkorea 첫 적재가 깨끗하게 통과하는 최소 schema (features +
  source). detail은 Feature.detail JSONB로 임시 저장 (정식 detail row는
  provider PR 시점에 별도 테이블 + JSONB 비교 마이그레이션).

**verification**:
- `python -m pytest tests/ -q --ignore=tests/integration` → **199 passed,
  4 skipped** (PR#27 머지 후 동일).
- `python -m ruff check src/ tests/ alembic/` → All checks passed.
- `python -m mypy --strict -p krtour.map` → Success, **29 source files**
  (infra/models.py 신규).
- `import-linter` → **4 contracts kept, 0 broken**.
- 통합 테스트 (testcontainers PostGIS 환경에서): 6 case 통과 기대 — CI에서
  실 검증.

**ADR 적용**:
- ADR-004 — ORM 매핑만 (`models.py`는 declarative + Column). 쿼리는 후속
  `infra/feature_repo.py`의 raw SQL `text()`.
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + alembic>=1.13.
- ADR-008 — extensions은 `x_extension` schema 격리 (0001 revision으로 강제).
- ADR-012 — `coord_5179` STORED generated column (0002 revision + models.py
  `Computed(persisted=True)`).
- ADR-018 — `detail` JSONB column (Pydantic 직렬화 입력).
- ADR-019 — 모든 datetime `TIMESTAMPTZ` (timezone-aware).

**TripMate docs 참조** (`docs/tripmate-integration.md` §1-§18):
- §5.1 raw → feature 흐름 — 본 PR의 schema가 입력. Sprint 2 visitkorea PR
  에서 검증.
- §10 structlog 키 표준 — `provider`/`dataset_key`/`source_record_id` 등.
  현 시점 ID 생성 helpers (PR#26)와 직접 호환.
- §11 에러 변환 — `KrtourMapError` 베이스 (PR#20)로 통합.

**다음 PR**:
- **PR#29** (Sprint 2 prep): `core/scoring.py` (ADR-016 Record Linkage,
  Coordinate 의존) + `core/providers.py` (CANONICAL_PROVIDER_NAMES) +
  `core/weather.py` placeholder.
- 이후 **Sprint 2 PR#30** ADR-034 1단계: `providers/visitkorea/` 축제 적재.

---

## 2026-05-25 23:07 (claude)

**작업**: PR#27 — review report P1 docs drift sweep. PR#26 머지(2026-05-25
22:15, codex `befaf09`)로 review P0-4 4건 완전 해소 → P1 docs drift만 남음.
사용자가 Sprint 4까지 자율 반복 사이클 개시 — 본 PR이 첫 cycle entry.

**컨텍스트**: PR#26 머지 후 main 동기 결과 `befaf09 fix: tighten PR26 source
DTO contracts`가 review 4건 (P1-1 bundle cross-validation / P1-2 SourceRecord
required fields / P1-3 payload hash strict normalize / P2-4 docs sync) 모두
해소. 추가 review 불필요. P1 (docs drift) 남은 진짜 잔재 — README/CLAUDE/
SKILL/AGENTS/agent-guide의 "Sprint 1 진입 직전" / "코드 작성 금지" 문단 정정.

**변경 파일**:
- `README.md` `> [현재 상태]` callout — "v2 설계 단계 — Sprint 1 진입 직전" /
  "문서/설계 전용" / "accepted 001~026, proposed 027~034" → "Sprint 1
  scaffolding 종료, Sprint 2 진입 준비" + ADR 001~034 모두 accepted + Sprint 1
  산출물 요약 (PEP 420 namespace / category 144 / dto / core / infra / CI gate).
- `CLAUDE.md` §2 (현 단계) — 동일 내용 정정. PR#17~#26 머지 결과 명기.
- `SKILL.md` §9 — "코드 작성 금지 (현 단계)" → "코드 작성 단계 (Sprint 1 종료,
  Sprint 2 진입 준비)". 허용된 예외 5건 목록 → Sprint 1 산출물 + Sprint 2
  prep 다음 단계 명시.
- `AGENTS.md` §"코드 작성 금지" → "코드 작성 단계 (Sprint 1 종료, Sprint 2
  진입 준비)". T-014 승인 + PR#17~#26 + 산출물 + 다음 단계.
- `docs/agent-guide.md` §8 (코드 작성 금지 단계) → "코드 작성 단계 (Sprint 1
  종료, Sprint 2 진입 준비)" + 기본 작업 절차 (의도 확인 → ADR → 테스트 우선
  → 구현 → 통합 테스트/EXPLAIN → journal/resume). §4 resume.md 예시도 갱신.
- `docs/resume.md` "현재 상태" — Sprint 1 scaffolding 종료 명기 + ADR 001~034
  accepted + Sprint 1 산출물 + review report P0 4건 해소 (PR#24/#26 +
  Codex 후속).
- `docs/tasks.md` — open PR 목록에서 PR#26 잔재 제거, PR#27/PR#26 최근 완료와
  다음 PR#28 후보를 분리.
- `docs/category.md` + package README 3건 — "v2 설계 단계" 잔재를 Sprint 1
  skeleton / 구현 완료 상태로 정정.

**삭제하지 않은 것 (의도)**:
- `docs/journal.md` historical entries — 시점별 기록 보존.
- `docs/reports/pr-1-21-review.md` — 리뷰 시점 (PR#21 기준) 보존.
- 다른 docs (data-model/decisions/architecture 등) — 정책 변경 없음.

**verification**:
- `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration -s` →
  **203 passed**.
- `.venv/bin/python -m ruff check .` → All checks passed.
- `.venv/bin/python -m mypy --strict -p krtour.map` → Success, 28 source files.
- `.venv/bin/lint-imports` → 4 contracts kept, 0 broken.

**자율 반복 사이클 진행 (사용자 지시)**:
- 사이클: PR 머지 확인 → 추가 review → 신규 작업 + 완료 PR → 머지 확인 → 반복.
- 목표: Sprint 4 (ADR-034 7단계 MOIS) 완료까지.
- 첫 cycle: PR#26 머지 (codex befaf09) → review 추가 0 → PR#27 (P1 sweep).
- 다음 cycle: PR#27 머지 대기 → review → PR#28 (`infra/models.py` + Alembic
  첫 revision, Sprint 2 prep).
- TripMate docs (`docs/tripmate-integration.md`) 참고: 통합 시나리오 1~4
  (조회/적재/Admin검수/POI 도메인) + PoiSnapshot cascade + structlog 키
  표준 — Sprint 2 첫 provider 적재 + debug UI 첫 라우터 PR에 반영 예정.

**다음 PR (PR#28 Sprint 2 prep)**:
- `src/krtour/map/infra/models.py` — SQLAlchemy 2 declarative + GeoAlchemy2
  (Feature + 5 detail + opening_hours + weather + price + files). GENERATED
  column `coord_5179` (ADR-012).
- `alembic/` directory + `env.py` + 첫 migration revision (`data-model.md
  §1~3` DDL).
- `tests/integration/test_alembic_upgrade.py` — head 적용 후 schema check.

---

## 2026-05-25 23:00 (claude)

**작업**: PR#26 review report P0-4 — ID helpers (`make_source_record_key` /
`make_payload_hash`) + DTO (`SourceRecord` / `SourceLink` / `FeatureBundle`).
Sprint 2 첫 provider 변환 함수 직전 필수 묶음.

**컨텍스트**: PR#25 merged 후 review report 마지막 P0 항목 (P0-4) 처리.
사용자가 P1-1/2 (`protected_area`/`facility_road` enum)는 별도로 main에
landing해서 ADR-028 amendment와 정합. 본 PR#26은 source record/link/bundle
DTO + ID helper로 Sprint 2 진입 준비.

**신규 파일** (4):
- `src/krtour/map/dto/source.py` (~150 line):
  - `SourceRecord` — provider raw payload row (provider/dataset_key/
    source_entity_type/source_entity_id/raw_payload_hash + raw_data/raw_*/
    fetched_at/imported_at/expires_at). DB NOT NULL 계약에 맞춰
    `source_record_key`/`fetched_at` 필수, `raw_data` 기본 `{}`. datetime aware
    validator (ADR-019).
    `key()` 메서드 두지 않음 — dto는 core import 불가 (ADR-001/002), 호출자가
    `make_source_record_key(...)`로 직접 계산해서 박는다.
  - `SourceLink` — Feature ↔ SourceRecord 1:N 매핑 (source_role/match_method/
    confidence 0-100/is_primary_source). datetime aware validator.
- `src/krtour/map/dto/bundle.py` (~80 line):
  - `FeatureBundle` — provider → load 전달 단위 (feature + source_record +
    source_link 3개 필수). `source_link.feature_id`와
    `source_link.source_record_key` 교차 검증. weather/price/file_sources 필드는
    Sprint 2 DTO 추가와 함께 enable.
  - `detail` property — `feature.detail` alias (single source of truth).
- `tests/unit/test_ids_extended.py` — `make_source_record_key`
  (포맷/결정성/구성요소 변경/empty/pipe/SHA1 회귀) + `make_payload_hash`
  (default length/custom length/invalid length/canonical sort/whitespace/
  unicode/diff data/datetime+date+Decimal/top-level list/SHA256 회귀 +
  unsupported payload 거부).
- `tests/unit/test_dto_source_bundle.py` — SourceRecord/SourceLink/
  FeatureBundle 생성 + DB required fields + bundle 교차 검증 + ADR-019 datetime
  + extra='forbid' + e2e flow (raw_payload → make_payload_hash →
  make_source_record_key → make_feature_id → FeatureBundle).

**주요 변경 파일**:
- `src/krtour/map/core/ids.py` — `make_source_record_key` (`sr_{sha1[:20]}`,
  `docs/data-model.md §11`) + `make_payload_hash` (`docs/data-model.md §11`,
  canonical JSON `sort_keys`+`separators=(",", ":")`+`ensure_ascii=False`+
  `allow_nan=False` → SHA256 hexdigest prefix, default 32 chars / 1-64 범위).
  `datetime`/`date`는 ISO 문자열, `Decimal`은 문자열로 정규화하고
  `set`/`bytes`/임의 객체는 거부.
  + `SOURCE_RECORD_KEY_HASH_LENGTH` / `PAYLOAD_HASH_DEFAULT_LENGTH` constants.
- `src/krtour/map/core/__init__.py` — re-export 신규 helper + length constant
  (12 → 15 식별자).
- `src/krtour/map/dto/__init__.py` — `SourceRecord` / `SourceLink` /
  `FeatureBundle` re-export.

**ADR-001/002 의존 방향 준수**:
- 처음에 `SourceRecord.key()` 메서드에서 core의 `make_source_record_key`를
  lazy import → **import-linter 가 즉시 검출** (`dto → core` 역참조 위반).
- 해소: `key()` 메서드 제거. 호출자가 `make_source_record_key(...)`로
  계산해서 `SourceRecord.source_record_key`에 박는다. e2e test에서 이 패턴
  검증.
- PR#22에서 `dto/_time.py` 분리한 것과 동일 원칙 — dto는 core 절대 import 안 함.

**verification**:
- `.venv/bin/python -m pytest tests/ -q --ignore=tests/integration -s` →
  **203 passed**.
- `.venv/bin/python -m ruff check .` → All checks passed.
- `.venv/bin/python -m mypy --strict -p krtour.map` → Success, 28 source files.
- `.venv/bin/lint-imports` → **4 contracts kept, 0 broken** (layered +
  fastapi 금지 + cache 금지 + kafka 금지).

**ADR 적용**:
- ADR-009 — `make_source_record_key` / `make_payload_hash` 결정적 ID 생성
  (`docs/data-model.md §11` 명세 구현). canonical JSON 직렬화 규칙은 변경
  금지 (영구 약속).
- ADR-018 — `SourceRecord` / `SourceLink` / `FeatureBundle` 모두
  `ConfigDict(extra="forbid")`.
- ADR-019 — 모든 DTO datetime에 `check_aware_datetime` validator 적용.
- ADR-001/002 — dto는 core를 import하지 않는다. `SourceRecord.key()` 메서드
  제거 (lint-imports로 자동 차단).

**다음 PR**:
- **PR#27** (review report P1): docs drift sweep — README/SKILL/agent-guide/
  tasks의 "Sprint 1 진입 직전" / "코드 작성 금지" 잔재 정정.
- 이후 **Sprint 2 1단계** (ADR-034 1단계): `providers/visitkorea/` 축제 +
  `infra/models.py` SQLAlchemy + Alembic migration 첫 revision + (필요 시)
  `core/scoring.py` ADR-016.

---

## 2026-05-25 22:00 (claude)

**작업**: AI agent entry 파일 scope 축소 — OpenAI Codex / Google Antigravity
관련 (`AGENTS.md`) + Claude Code (`CLAUDE.md`)만 남기고 나머지 (Copilot /
Cursor) 삭제.

**컨텍스트**: 사용자가 "CODEX와 Antigravity 관련 내용 빼고는 다 지워" 지시.
앞서 (21:30) 신설했던 `.github/copilot-instructions.md` / `.cursorrules`는
IDE-side 룰 파일로 drift 위험 — `AGENTS.md`/`CLAUDE.md`와 정책 동기화 의무가
증가. 사용자는 본 라이브러리 작업에 Codex와 Antigravity (`AGENTS.md` 컨벤션
공유) + Claude Code만 사용 → entry 파일 2종만 유지.

**삭제 파일** (2):
- `.github/copilot-instructions.md` — GitHub Copilot 자동 검출. 삭제.
- `.cursorrules` — Cursor 자동 검출. 삭제.

**변경 파일** (3):
- `AGENTS.md` top callout 축소 — "OpenAI Codex / Google Antigravity 등
  `AGENTS.md` 컨벤션 AI agent의 표준 entry. Claude Code는 별도 `CLAUDE.md`"
  명시 (이전 sweep callout 제거).
- `CLAUDE.md` top callout 축소 — "Codex / Antigravity는 `AGENTS.md`. 본
  라이브러리는 CLAUDE.md + AGENTS.md 두 파일만 AI agent entry로 박음
  (Copilot/Cursor 등 IDE-side 룰 파일은 두지 않음 — drift 회피)" 명시.
- `docs/journal.md` — 본 엔트리 (이전 21:30 sweep 엔트리 supersede).

**최종 cardinality (2 + 1 = 3 파일)**:
- `AGENTS.md` — Codex / Antigravity 등 표준 cross-agent entry (source of
  truth).
- `CLAUDE.md` — Claude Code 1쪽 요약.
- `README.md` §"개발 환경 (PC, WSL)" — 사람 + 일반 entry.

**verification**:
- 코드 변경 0 — pytest/lint 영향 없음.
- 정책 (WSL ext4 base + Top 5 금지)은 `AGENTS.md` (Codex/Antigravity) +
  `CLAUDE.md` (Claude Code) + `SKILL.md` + `README.md`에 stamping. drift
  회피 위해 IDE-side 룰 파일 (Copilot/Cursor)은 명시적으로 두지 않음.

---

## 2026-05-25 21:30 (claude, superseded)

(앞 entry — `.github/copilot-instructions.md` / `.cursorrules` 신설.
사용자 지시로 22:00에 축소 — 본 엔트리는 history 보존용. 실 작업 결과는
22:00 엔트리 기준.)

---

## 2026-05-25 21:00 (claude)

**작업**: PR#25에 WSL ext4 base 정책 문서 명시 sweep. `python-kraddr-geo`
패턴 미러.

**컨텍스트**: 사용자가 "python-kraddr-geo와 똑같이 wsl이 베이스임을 문서에
명시하고 PR25에도 코멘트와 함께 md 파일 업데이트 반영" 지시. kraddr-geo 측
패턴 (`## 💻 개발 환경 (PC, WSL)` README 헤더 + WARNING callout + ext4/NTFS
경로 표) 조사 후 본 라이브러리 동일 stamping. AGENTS/SKILL은 이미 §"개발
환경 정책 (PC, WSL)" 섹션 존재 — README/CLAUDE/dev-environment 보강.

**변경 파일** (5):
- `README.md` — `## 💻 개발 환경 (PC, WSL)` 신규 섹션 (책임 비책임 다음).
  `> [!WARNING]` GitHub callout + ext4/NTFS 경로 표 + AGENTS/SKILL cross-
  reference. kraddr-geo `README.md:21-33`과 1:1 미러.
- `CLAUDE.md` §4 (의존 스택) — "개발 환경" 한 문단 추가. WSL ext4 base +
  형제 라이브러리 동일 정책 명기.
- `docs/dev-environment.md` — title 변경 (`dev-environment.md — 개발 환경` →
  `# 개발 환경 셋업 (WSL ext4 기준)`). 첫 단락에 AGENTS/SKILL/README cross-
  reference + 형제 라이브러리 동일 명기.
- `AGENTS.md` §"개발 환경 정책 (PC, WSL)" — 첫 단락 끝에 "형제 라이브러리
  (kraddr-geo/kraddr-base/knps-api 등)와 동일 정책" 명시.
- `SKILL.md` §"개발 환경 (PC, WSL)" — 첫 줄에 "형제 라이브러리 동일 정책"
  + AGENTS/dev-environment cross-reference 추가.

**verification**:
- 코드 변경 0 — pytest/lint 영향 없음.
- README/CLAUDE/AGENTS/SKILL/dev-environment 5개 파일이 WSL 정책을 동일하게
  "박는" 형태 — kraddr-geo와 동일 cardinality.

---

## 2026-05-25 20:00 (claude)

**작업**: PR#25 KNPS keyless sync — python-knps-api PR#4 (`codex/keyless-file-
download-dtos`, commit `06da125f`) 변경을 본 라이브러리 docs/pyproject에 일괄
반영. ADR-028 amendment §H 신설.

**컨텍스트**: 사용자가 "python-knps-api 구현 완료. 관련 부분 보강/구현할 것"
+ "review report 내용 반영" 요청. PR#24 (review report P0-1/2/3) merged 후.
upstream knps-api 측 두 큰 변경 (PR#3 OpenAPI 표면 삭제 + PR#4 keyless file
DTOs)이 본 라이브러리 docs와 어긋남 — sync 필요.

**upstream knps-api 변경 (외부 repo)**:
- **PR#3 (`aa40541` Remove KNPS OpenAPI surface)**: data.go.kr API endpoint
  표면 전체 삭제. `ApiEndpoint`/`Page`/`api_endpoint`/`api_endpoints`/
  `KnpsClient.raw_endpoint`/`KnpsClient.endpoints` 모두 제거. 카탈로그
  14건 → 모두 `kind="file_dataset"`.
- **PR#4 (`3269f22`+`3cac75e`+`80c17ed`)**: keyless file artifact DTOs 추가.
  `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 모델. `client.files.
  inspect_bytes()`/`download_artifact()` 메서드. `KnpsConfig`에서 `service_key`
  /`api_key`/env var 읽기 완전 제거.

**본 라이브러리 영향 (PR#25 일괄)**:
- ADR-028 §A-F는 historical 유지. 새 amendment §H 추가 (keyless + file-only).
- 14 dataset_key 정정 — 신규 4건 (`knps_linear_facilities`, `knps_protected_areas`,
  `knps_basic_statistics`, `knps_lod_table_catalog`), 제거 4건
  (`knps_access_restrictions`, `knps_fire_alerts`, `knps_recommended_courses`,
  `knps_park_photos`). 모두 verified data.go.kr ID 박힘 (13/14, 1건만
  `needs_verification`).
- 인증 ENV 전부 제거 — `KNPS_SERVICE_KEY` deprecated, `DATA_GO_KR_SERVICE_KEY`
  KNPS 폴백 제거.

**변경 파일**:
- `docs/decisions.md` — ADR-028 §H amendment 추가 (~90 line). 신규 14 dataset
  table + 삭제 4 keys + keyless KnpsClient 사용 패턴.
- `docs/knps-feature-etl.md` — §1 (auth=none, keyless 명기) / §2 (14 file
  dataset 표 재작성, 공간 11 + 비공간 3 + 삭제 4 분리) / §3.5-3.6 (notice는
  source 이전 명기) / §4 (category 표에 linear_facilities/protected_areas 추가)
  / §5 (FileArtifact API 예시) / §6 (Dagster asset 11건, 이전 notice 2건 제거)
  / §7 (fixture 신규 dataset) / §8 (후속 작업 정정).
- `docs/forest-feature-etl.md` §11.1-§11.5 — keyless API 사용 패턴 재작성,
  §11.4 추가 후보 표 정정 (3건 채택 + 4건 source 이전), §11.5 Dagster 카탈로그
  11건 (linear_facilities/protected_areas 추가, notice 2건 제거).
- `docs/external-apis.md` §2 env table — `KNPS_SERVICE_KEY` strikethrough +
  비고에 "사용 안 함". §3.8.1 — keyless 명기, ServiceKey 발급 단계 삭제.
- `docs/provider-contract.md` §3 dataset_key 표 — 14건 정정 + 4건 strikethrough.
- `pyproject.toml` providers extras — knps git URL 주석 갱신 (`@06da125f` commit
  pin + keyless 비고).
- `src/krtour/map/dto/{area,route}.py` — `protected_area` area_kind,
  `facility_road` route_type 추가. KNPS PR#25 문서 계약과 DTO 정합.
- `tests/unit/test_dto_{area,feature}.py` — 신규 DTO 값 회귀 테스트.
- `docs/{feature-model,resume,tasks}.md` / `CHANGELOG.md` — DTO 정합 보강과
  PR#25 상태 반영.

**ADR 적용**:
- ADR-028 §H amendment — 결정 영구화 (historical §A-F는 PR#12 시점 기록 보존).
- 후속 ADR (TBD): `access_restriction`/`fire_alert` notice source 결정 —
  산림청 (`python-krforest-api`) / 소방청 / scrape 중 선택. Sprint 3 KNPS
  적재 PR 이전 결정 필요.

**verification**:
- GitHub Actions (`a646db5`) — lint, openapi-drift, pytest Python 3.11/3.12/
  3.13 모두 green.
- 로컬: `.venv/bin/python -m ruff check src/ tests/`, `git diff --check`,
  `compileall src/krtour/map`, DTO smoke 통과.

**다음 PR**:
- **PR#26** (review report P0-4): `make_source_record_key` + `make_payload_hash`
  + `SourceRecord` + `SourceLink` + `FeatureBundle` DTO. Sprint 2 첫 provider
  변환 직전 필수.
- **PR#27** (review report P1): docs drift sweep — README/SKILL/agent-guide의
  "Sprint 1 진입 직전" / "코드 작성 금지" 잔재 정정.
- 이후 **Sprint 2 1단계**: `providers/visitkorea/` 축제 + `infra/models.py`.

---

## 2026-05-25 19:00 (claude)

**작업**: PR#24 DTO strictness P0 (Sprint 2 진입 전 차단) — review report
(PR#23 merged, `docs/reports/pr-1-21-review.md`) P0-1/2/3 해소.

**컨텍스트**: PR#22 머지(16:00) → PR#23 codex 리뷰 리포트 머지(18:08) 후
사용자 "다음 작업 진행" + PR#24-26 분할 채택. PR#24는 DTO strictness 3건 묶음 —
Sprint 2 첫 provider 변환 함수 직전 closeable. PR#24 push 후 PR#23 머지로
`docs/journal.md` + `docs/resume.md` 충돌 발생 → rebase 해결.

**review report P0 항목 해소**:
- **P0-1 `Feature.detail` dict 입력 차단**: 기존 `@model_validator(after)`는
  Pydantic union이 dict를 model로 자동 coerce한 *후* isinstance 검사 → 자유
  dict 입력이 ADR-018 gate를 통과하던 문제. 해소: `@field_validator("detail",
  mode="before")` 추가로 raw dict 즉시 거부.
- **P0-2 datetime aware 정책 일관 적용**: `Feature.created_at/updated_at/
  deleted_at`만 검증하던 것을 `NoticeDetail.valid_start_time/valid_end_time`
  + `RawDataRef.fetched_at`까지 확장. `dto/_time.py`에 공용 `check_aware_
  datetime()` helper 추가 — 매 모델마다 재구현 회피.
- **P0-3 `Feature.category` 8자리 pattern**: 기존 `min_length=1`만 보던 검증을
  `^\d{8}$` 정규식으로 강화 (ADR-023 PlaceCategoryCode value format). strict
  known-code 검증은 후속 PR — provider 입력 fallback 룰 결정 시간 확보
  (transitional 옵션).

**신규 파일** (1):
- `tests/unit/test_dto_time.py` (11 case) — `KST` 상수 / `kst_now()` aware /
  `check_aware_datetime()` (KST/UTC accept, None pass, naive reject) +
  `RawDataRef.fetched_at` aware/naive/None.

**변경 파일** (6):
- `src/krtour/map/dto/_time.py` — `check_aware_datetime(value)` 공용 helper
  추가. docstring에 ADR-019 정책 (aware = any tz, naive = reject) 명시.
- `src/krtour/map/dto/feature.py`:
  - `Feature.detail` mode=before dict 거부 validator
  - `Feature.category` 8자리 정규식 validator (`_CATEGORY_REGEX`)
  - `Feature.created_at/updated_at/deleted_at` validator → 공용 helper 사용
  - `category` Field에서 `min_length=1` 제거 (regex가 length도 강제)
  - `typing.Any` import (validator return type)
- `src/krtour/map/dto/notice.py` — `valid_start_time/valid_end_time` aware
  validator 추가.
- `src/krtour/map/dto/urls.py` — `RawDataRef.fetched_at` aware validator 추가.
- `src/krtour/map/dto/__init__.py` — `KST`/`kst_now`/`check_aware_datetime`
  공개 API 추가.
- `tests/unit/test_dto_feature.py`:
  - `test_feature_detail_dict_rejected` → 3건으로 분리 (complete keys / partial
    / empty) — 모두 `mode=before` 차단 검증
  - `test_feature_category_8digit_accepted` + `_non_8digit_rejected` 신규
- `tests/unit/test_dto_notice.py` — naive valid_start_time / valid_end_time
  reject + KST/UTC aware accept 케이스 3건 추가.

**verification**:
- `python -m pytest tests/ -q --ignore=tests/integration` → **141 passed**
  (125 + 16 신규).
- `python -m ruff check src/ tests/` → All checks passed
- `python -m mypy --strict -p krtour.map` → Success, 26 source files
- import-linter → 4 contracts kept, 0 broken

**ADR 적용**:
- ADR-018 — `Feature.detail` dict 입력 진짜 차단 (이전엔 우연한 ValidationError에
  의존).
- ADR-019 — datetime aware 정책 일관 적용. ADR 문구 해석: "aware면 OK, naive
  거부" (any tz 허용, KST 변환은 호출자 책임). Sprint 2 provider 변환 함수에서
  KST로 normalize.
- ADR-023 — `Feature.category` 8자리 PlaceCategoryCode value format 강제
  (transitional — known-code strict는 후속 PR).

**다음 PR (review report P0/P1)**:
- **PR#25** (P0-4): ID helper 확장 (`make_source_record_key`,
  `make_payload_hash`) + `FeatureBundle` + `SourceRecord` + `SourceLink` DTO.
- **PR#26** (P1): docs drift sweep — README/SKILL/agent-guide/tasks/resume의
  "Sprint 1 진입 직전" / "코드 작성 금지" 문단을 Sprint 1 active/종료 상태로
  갱신.
- 이후 **Sprint 2 1단계**: `providers/visitkorea/` 축제 + `infra/models.py`
  + Alembic migration 첫 revision.

---

## 2026-05-25 18:08 (codex)

**작업**: PR#1~#21 신규 소스·문서 상세 리뷰 리포트 충돌 해결.

**컨텍스트**: PR#23 작성 후 PR#22가 main에 merge되어 `docs/journal.md`와
`docs/resume.md`에 충돌 발생. 사용자 요청으로 `origin/main` (`01333cc`, PR#22
merge commit)을 현재 브랜치에 병합하고, PR#22의 최신 CI/import-linter 기록과
PR#1~#21 리뷰 리포트 기록을 모두 보존.

**변경 파일**:
- `docs/journal.md` — PR#22 entry 보존 + PR#23 리포트/충돌 해결 entry 추가.
- `docs/resume.md` — PR#22 merged 상태와 PR#1~#21 리뷰 리포트 보완 후보 병합.
- `docs/reports/pr-1-21-review.md` — PR#22 최종 상태를 open → merged로 갱신.

**검증**:
- `git fetch --all --prune` 후 `origin/main=01333cc` 확인.
- `git diff --check` 재실행 예정.

**다음**: 충돌 해결 merge commit push 후 PR#23 draft 해제/merge.

---

## 2026-05-25 16:00 (claude)

**작업**: Sprint 1 PR#22 — CI workflows 활성화 (`.github/workflows/
{ci,lint,openapi}.yml`) + import-linter 4 계약 활성화 + ADR-002 위반 1건
실 해소 (dto → core 역참조).

**컨텍스트**: PR#21 머지 후 사용자 "다음 진행"으로 PR#22 승인. Sprint 1
scaffolding 마지막 PR — CI gate를 박아 PR#17~#21에서 쌓인 코드의 회귀를
자동으로 막는다. import-linter 처음 가동 시 ADR-002 위반 1건 실 검출 +
해소 (`dto/feature.py`가 `core.kst_now` import).

**신규 파일** (5):
- `.github/workflows/ci.yml` — pytest unit + integration (testcontainers
  PostGIS, ADR-007) + coverage XML, Python 3.11/3.12/3.13 matrix.
  `concurrency` group으로 동일 PR 연속 push 시 이전 run 자동 cancel.
- `.github/workflows/lint.yml` — ruff check (src+tests) + mypy --strict
  (krtour.map 전체) + import-linter (4 계약).
- `.github/workflows/openapi.yml` — ADR-031 drift gate. Sprint 1은
  `continue-on-error: true` (앱 모듈 미존재 SystemExit) — Sprint 2 첫
  라우터 PR에서 제거.
- `tests/lint/test_import_linter.py` — pyproject.toml의 4 계약을 pytest로
  wrap (subprocess로 `lint-imports` 실행). 미설치 시 skip.
- `src/krtour/map/dto/_time.py` — `KST` / `kst_now()` 정의 (이전 `core/
  types.py`에서 이동, ADR-002 의존 방향 보존).

**변경 파일** (10):
- `pyproject.toml`:
  - `[tool.importlinter]` `include_external_packages = true` 추가 (외부
    forbidden modules 검증 활성화)
  - `layers` 계약에서 `krtour.map.cli` 제거 (모듈 미존재 — Sprint 4~5
    추가 시 다시 박음)
- `src/krtour/map/core/types.py` — KST/kst_now 정의 → `dto/_time` re-export
  shim. 공개 API (`from krtour.map.core import kst_now`)는 그대로.
- `src/krtour/map/dto/feature.py` — `from ..core import kst_now` →
  `from ._time import kst_now` (의존 방향 보존)
- `src/krtour/map/providers/__init__.py` — docstring 표 줄바꿈 (E501 해소)
- `tests/unit/test_dto_{notice,area,feature}.py` + `test_category.py` —
  `pytest.raises(Exception)` → `pytest.raises(ValidationError)` (B017/PT011)
  fix. 의도 명확화 + 잘못된 다른 예외 catch 방지.
- `tests/lint/test_no_namespace_init.py` — ruff auto-import-sort

**ADR-002 위반 실 해소 (import-linter 첫 가동 효과)**:
- PR#19에서 `KST`/`kst_now`를 `core/types.py`에 추가 → `dto/feature.py`
  가 `from ..core import kst_now`로 import → ADR-002 위반 (dto가 core를
  import).
- 해소: 정의를 `dto/_time.py`로 이전 (dto 레이어 내부). `core/types.py`는
  re-export shim — 호출 측 (`from krtour.map.core import kst_now`) 코드
  변경 0.

**verification**:
- `python -m pytest tests/ -q` → **125 passed, 10 skipped** (124 + 1
  새 import_linter wrapper).
- `python -m ruff check src/ tests/` → All checks passed (25 → 0건).
- `python -m mypy --strict -p krtour.map` → Success, 26 source files.
- `python -c "from importlinter.cli import lint_imports_command; ..."` →
  **4 contracts kept, 0 broken** (layered + fastapi/uvicorn + cache +
  kafka 금지).

**ADR 적용**:
- ADR-002 — import-linter `layers` 계약 활성화. `dto → core → infra →
  providers → client → cli` (cli는 Sprint 4~5 추가 시 박음).
- ADR-020 — `forbidden_modules = [fastapi, uvicorn, starlette]` 메인
  패키지 의존 차단 (디버그 UI는 별도 패키지).
- ADR-030 — `forbidden_modules = [cachetools, async_lru, aiocache,
  diskcache]` in-memory cache 의존 차단 (narrow `@functools.cache` 예외만
  허용).
- ADR-031 — `openapi.yml` workflow + `export_openapi.py --check` drift
  gate. Sprint 1은 `continue-on-error` (앱 미존재) → Sprint 2 첫 라우터 PR
  에서 활성화.
- ADR-032 — ci.yml에서 `--cov=src/krtour/map`, coverage XML upload.
  현재 `fail_under=50` (pyproject.toml), Sprint별 단계 상향.
- ADR-103 (T-103 보류) — `forbidden_modules = [kafka, aiokafka,
  confluent_kafka, faust]` streaming consumer 의존 차단.

**다음**: PR#22 사용자 review/merge → Sprint 1 scaffolding **완료**.
다음 Sprint 진입: PR#23 (또는 SPRINT-2.md 활성화로 직접 진입) — Sprint 2
ADR-034 9단계 순서대로 provider 적재 시작 (1단계 visitkorea 축제).

---

## 2026-05-25 15:00 (claude)

**작업**: Sprint 1 PR#21 — `src/krtour/map/infra/` skeleton: `crs.py`
(pyproj.Transformer singleton, ADR-030 narrow cache) + `db.py` (async
engine + session factory) + `tests/integration/conftest.py` (testcontainers
PostGIS 베이스) + 첫 통합 smoke 테스트.

**컨텍스트**: PR#20 머지(2026-05-25 14:00) 후 사용자 "다음 진행"으로 PR#21
승인. Sprint 2 첫 provider 적재 직전에 필요한 인프라 가장 바닥 (좌표 변환
+ DB engine factory + testcontainers 베이스). 실 ORM 모델 (`infra/models.py`)
과 repository (`infra/feature_repo.py`)는 Sprint 2 첫 provider PR로 분리.

**신규 파일** (6):
- `src/krtour/map/infra/crs.py` (~140 line):
  - `transformer_4326_to_5179()` / `transformer_5179_to_4326()` — pyproj
    Transformer singleton (`@functools.cache`, ADR-030 narrow 예외)
  - `project_to_5179(lon, lat)` / `project_to_4326(x_m, y_m)` — convenience
  - `EPSG_WGS84=4326` / `EPSG_UTM_K=5179` 상수
  - `always_xy=True` 강제 — pyproj 기본 axis order 혼재 회피
- `src/krtour/map/infra/db.py` (~150 line):
  - `make_async_engine(dsn, *, echo, pool_size, max_overflow, pool_pre_ping)`
    — SQLAlchemy 2 AsyncEngine + asyncpg driver 강제
  - `make_async_session_factory(engine) -> async_sessionmaker`
  - `normalize_async_dsn(dsn)` — `postgresql://` / `postgres://` / `psycopg2` /
    `psycopg` → `postgresql+asyncpg://` 통일 (testcontainers 호환)
  - `SecretStr` 입력 자동 처리 (KrtourMapSettings.pg_dsn 직접 주입 가능)
- `tests/unit/test_crs.py` (13 case parametrize 포함) — singleton 정체성 /
  EPSG 상수 / round-trip 정밀도 (서울/부산/제주/대구/경계 6점) / UTM-K
  좌표 합리성 (서울 ≈ 953000, 1952000) / 서울-부산 거리 ≈ 325km /
  always_xy 보증
- `tests/unit/test_db.py` (12 case) — DSN 정규화 (5종 parametrize) +
  empty/non-postgres ValueError + AsyncEngine 인스턴스 + SecretStr 처리 +
  echo flag + async_sessionmaker. 엔진 생성 4건은 asyncpg 미설치 환경에서
  자동 skip
- `tests/integration/__init__.py` (빈 파일) + `tests/integration/conftest.py`
  (~115 line) + `tests/integration/test_pg_smoke.py` (6 case):
  - `pg_container` (session-scope, `postgis/postgis:16-3.5-alpine`)
  - `pg_engine` (session-scope, 4 schema + 3 extension 자동 생성)
  - `pg_session` (per-test, 자동 rollback)
  - testcontainers/Docker 미설치 시 자동 `pytest.skip`
  - smoke: postgis/pg_trgm/pgcrypto x_extension 격리 확인 (ADR-008) +
    4 schema 존재 + ST_Transform 4326↔5179 Python pyproj와 1m 이내 일치

**변경 파일** (3):
- `src/krtour/map/infra/__init__.py` — 9 식별자 re-export (crs 6 + db 3),
  placeholder → PR#21 명세 + Sprint 2 후속 계획 명시
- `tests/conftest.py` — PR#21 통합 베이스 활성화 명기
- `pyproject.toml` — `pyproj>=3.6` 본 의존 추가 (ADR-012 좌표 변환 +
  ADR-030 narrow cache singleton)

**verification**:
- `python -m pytest tests/ -q` → **124 passed, 10 skipped**
  (4 asyncpg 미설치 skip + 6 testcontainers 미설치 skip).
- `python -m ruff check src/krtour/map/infra/ tests/unit/test_crs.py
  tests/unit/test_db.py tests/integration/` → All checks passed.
- `python -m mypy --strict -p krtour.map.infra` → Success, no issues
  found in 3 source files.
- pyproj round-trip (서울 시청 4326 → 5179 → 4326) → ±1cm 이내.
- 서울 시청 EPSG:5179 좌표 ≈ (953000m, 1952000m) — 한국 권역 expected.
- 서울-부산 직선거리 ≈ 325km (UTM-K Euclidean) — ADR-012 핵심.

**ADR 적용**:
- ADR-012 — 공간 쿼리 입력 좌표 1회 변환. 본 PR은 보조 Python 측 변환만
  (PostGIS ST_Transform이 1차 — 인덱스 보존).
- ADR-030 — `pyproj.Transformer` singleton을 narrow 예외에 명시적으로
  포함 (`@functools.cache`).
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto, asyncpg.
- ADR-008 — 모든 extension은 `x_extension` schema 격리 (smoke 테스트로
  회귀 방지).

**Sprint 2 후속 PR에 남긴 것**:
- `infra/models.py` — SQLAlchemy 2 declarative + GeoAlchemy2 (`Feature` +
  5 detail + opening_hours + weather + price + files). GENERATED column
  (`coord_5179`) 매핑 + UNIQUE 제약.
- `infra/feature_repo.py` — raw SQL `_SQL` 상수 + EXPLAIN 검증 통합 테스트
  (ADR-004 + ADR-012).
- `infra/source_repo.py` / `sync_repo.py` / `jobs_repo.py` — Sprint 2~4.
- `infra/file_store.py` — Sprint 3 (S3 호환 RustFS, ADR-015).
- Alembic migration 첫 revision — Sprint 2 PR (data-model.md §1~3 DDL).

**다음**: PR#21 사용자 review/merge → PR#22 (CI workflows
`.github/workflows/{ci,lint,openapi}.yml` + import-linter 계약 활성화).

---

## 2026-05-25 14:00 (claude)

**작업**: Sprint 1 PR#20 — `src/krtour/map/core/` 예외 계층 + ADR-009
`make_feature_id`. PR#19(dto) 머지 후 main rebase로 `core/__init__.py`에
`KST`/`kst_now` (PR#19) + 예외 7종 + `make_feature_id` (PR#20) 통합 export.

**컨텍스트**: 사용자가 PR#19 open 후 "이어서 진행"으로 PR#20 승인. 본 PR은
PR#19와 병행 진행을 위해 dto 의존 없이 자체 완결되어야 하므로 `kind: str`
타입으로 `make_feature_id` 정의 (`FeatureKind` StrEnum은 `str` 서브클래스
이므로 그대로 호환). PR#19 머지 직후 main rebase에서 `core/__init__.py` /
journal / tasks / resume / CHANGELOG 5건 충돌 해결.

**신규 파일** (4):
- `src/krtour/map/core/exceptions.py` (~110 line) — `KrtourMapError` 베이스 +
  7 도메인 예외 (`docs/backend-package.md §5` + `docs/debug-ui-package.md §6.4`
  HTTP 매핑):
  - `ValidationError` (422) — DTO Pydantic / 도메인 룰
  - `FeatureNotFoundError` (404)
  - `SourceRecordNotFoundError` (404)
  - `DuplicateFeatureError` (409)
  - `ImportJobConflictError` (409) — ADR-011 advisory lock 미획득
  - `ProviderError` (502) — ADR-006 raw httpx 예외 wrap
  - `FileStoreError` (502) — RustFS 접근 실패
- `src/krtour/map/core/ids.py` (~130 line) — ADR-009 결정적 ID 생성:
  - `make_feature_id(*, bjd_code, kind, category, source_type, source_natural_key, content_hash=None)`
    → `f_{bjd or 'global'}_{kind[0]}_{sha1(input)[:16]}`
  - `FEATURE_ID_HASH_LENGTH = 16` (Final[int])
  - `|` 구분자 / 빈 문자열 검증 (`_validate_component`)
  - `make_source_record_key` / `make_payload_hash`는 후속 PR로 미룸 (사용처
    없을 때 박지 않음)
- `tests/unit/test_exceptions.py` (7 case) — 베이스 상속 / 7종 parametrize /
  catch / re-export 검증
- `tests/unit/test_ids.py` (35 case parametrize 포함) — 결정성 / 7 kind prefix /
  StrEnum 호환 / 변경 감지 / validation / SHA1 회귀

**변경 파일** (1):
- `src/krtour/map/core/__init__.py` — PR#19에서 추가된 `KST`/`kst_now`와
  공존하도록 통합 re-export (총 12 식별자: types 2 + exceptions 7 + ids 3).

**ADR-009 핵심 결정 반영**:
- `kind: str` 타입 annotation (dto 의존 회피) — `FeatureKind` StrEnum은
  `str` 서브클래스이므로 PR#19 머지 후 그대로 호환 (호출 측 코드 변경 0).
- `usedforsecurity=False` 명시 (SHA1는 ID 결정성용, 보안용 아님 — FIPS 환경
  대비).
- `_BJD_FALLBACK = "global"` 행정구역 외 / 매핑 실패 케이스 표준화.
- `content_hash=None` ↔ `content_hash=""` 동치 (`x or ''` 평탄화).

**verification (rebase 후)**:
- `python -m pytest tests/ -q` → 72→? passed (rebase 후 재실행 필요).
- `python -m ruff check src/krtour/map/core/ tests/unit/test_exceptions.py tests/unit/test_ids.py`
  → all checks passed.
- `python -m mypy --strict -p krtour.map.core` → Success.
- `make_feature_id(bjd_code="1168010100", kind="place", category="PLACE_RESTAURANT",
  source_type="krex_rest_area", source_natural_key="RA00012")` →
  `f_1168010100_p_<16hex>` 결정적.

**다음**: PR#20 사용자 review/merge → PR#21 (`src/krtour/map/infra/` skeleton
+ testcontainers PostGIS + `crs.py` pyproj.Transformer ADR-030 narrow cache).

---

## 2026-05-25 13:00 (claude)

**작업**: Sprint 1 PR#19 — `src/krtour/map/dto/` Feature + 5 detail kind
+ NOTICE_TYPES 14건 (ADR-027) + AreaDetail.area_kind hazard_zone (ADR-027)
+ ADR-019 KST aware enforcement. `core/types.py`에 KST/kst_now.

**컨텍스트**: 사용자 PR#18 머지 후 "다음 진행"으로 PR#19. Sprint 1 §2.4
(ADR-027 코드 적용) + Sprint 2 진입 직전 Feature DTO 기반 구축.

**신규 파일** (13):
- `src/krtour/map/core/types.py` — `KST` / `kst_now()` (ADR-019)
- `src/krtour/map/dto/_enums.py` — `FeatureKind` 7종 / `FeatureStatus` 6종
  / `SourceRole` 8종 (StrEnum)
- `src/krtour/map/dto/coordinate.py` — `Coordinate` (Korea bounds validator
  [124, 132] × [33, 39.5], frozen)
- `src/krtour/map/dto/address.py` — `Address` (basic, kraddr-base 통합은
  Sprint 2)
- `src/krtour/map/dto/urls.py` — `FeatureUrls` + `RawDataRef`
- `src/krtour/map/dto/opening_hours.py` — `OpeningTime`/`OpeningPeriod`/
  `SpecialOpeningDay`/`FeatureOpeningHours` (Google Places 호환)
- `src/krtour/map/dto/place.py` — `PlaceDetail`
- `src/krtour/map/dto/event.py` — `EventDetail` (날짜 순서 validator)
- `src/krtour/map/dto/notice.py` — `NoticeDetail` + **NOTICE_TYPES 14건**
  (ADR-027 `access_restriction`/`fire_alert` 포함) + `normalize_notice_type`
  + 한/영 alias map (입산통제/해수욕장폐장/산불경보 등)
- `src/krtour/map/dto/route.py` — `RouteDetail` + ROUTE_TYPES 9종 +
  `normalize_route_type` (lenient unknown → 'route' fallback)
- `src/krtour/map/dto/area.py` — `AreaDetail` + AREA_KINDS 12종 (ADR-027
  **hazard_zone** 포함)
- `src/krtour/map/dto/feature.py` — `Feature` 본체:
  - coord (optional, Korea bounds), marker_color (P-01~P-16 regex), detail
    (ADR-018 discriminator), KST timestamps
  - ADR-018: kind→detail 매핑 강제, weather/price는 detail=None
  - ADR-019: naive datetime → ValidationError
- `tests/unit/test_dto_notice.py` (9 cases)
- `tests/unit/test_dto_area.py` (5 cases)
- `tests/unit/test_dto_feature.py` (13 cases)

**변경 파일** (2):
- `src/krtour/map/dto/__init__.py` — placeholder → 38 공개 식별자
  re-export
- `src/krtour/map/core/__init__.py` — `KST`/`kst_now` re-export

**verification**: `python -m pytest tests/ -q` → **62 passed** (category
16 + dto 27 + smoke 11 + lint 3 + 기타 5).

**비목표 (Sprint 2 PR로 연기)**:
- `WeatherValue` (ADR-010, Sprint 2 KMA provider)
- `PriceValue` (Sprint 2 OpiNet)
- `SourceRecord`/`SourceLink` (Sprint 2 첫 provider)
- `FeatureFile`/`FeatureFileSource` (Sprint 2~3)
- `ProviderSyncState` (Sprint 2)
- `ImportJob` (Sprint 4 MOIS bulk)
- `FeatureBundle` (적재 단위)

**다음**: PR#19 review/merge → PR#20 `src/krtour/map/core/` 본격 구현
(exceptions + `make_feature_id` ADR-009 + scoring stub ADR-016).

---

## 2026-05-25 12:00 (claude)

**작업**: Sprint 1 PR#18 — `src/krtour/map/category/` 144건 코드 이전
(ADR-023) + ADR-027 `LODGING_MOUNTAIN_SHELTER` 3건 신규.

**컨텍스트**: 사용자가 PR#17 머지 후 "이어서 진행"으로 PR#18 승인.
`python-kraddr-base/src/kraddr/base/categories.py` (~2071줄, 141건)을 본
라이브러리로 가져오고 ADR-027 3건 추가해서 총 144건.

**신규 파일** (2):
- `src/krtour/map/category/_definitions.py` (~2110줄) — kraddr-base 사본 +
  ADR-027 패치:
  - `from ._enum import StrEnum` → `from enum import StrEnum` (Python
    3.11+ stdlib)
  - `from functools import cache` 추가 (ADR-030 narrow 예외)
  - 메타 update (`PLACE_CATEGORY_SOURCE` / `_SCHEMA_DOC` / `_SYNCED_ON`)
  - **ADR-027 3건**:
    - `PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER = "03080000"` enum
    - `LODGING_MOUNTAIN_SHELTER_KNPS = "03080100"`
    - `LODGING_MOUNTAIN_SHELTER_KFS = "03080200"`
    - `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["03"]["08"] = "대피소·산장"`
    - 3건 `PLACE_CATEGORY_DEFINITIONS` row (sort_order 380/381/382)
    - 3건 `PLACE_CATEGORY_MAPBOX_MAKI_ICONS` 매핑 (`shelter`, Maki 표준)
  - `@cache` on `get_category` (ADR-030 narrow 예외)
- `tests/unit/test_category.py` (16 cases) — 총건/depth/Tier1/ADR-027
  3건/maki/helper/`@cache`/frozen dataclass 검증

**변경 파일** (2):
- `src/krtour/map/category/__init__.py` — `_definitions`에서 14 공개
  식별자 re-export.
- `docs/category.md`:
  - §4.3 depth 통계 정정 — 원본 docs는 Tier 2/Tier 4 카운트가 swap돼
    있었음 (29/33 → 실제 33/29). 실측 + ADR-027 적용 후 합계 144.
  - §3 helper 표 — `mapbox_maki_icon_for_category`가 unknown 코드에 strict
    KeyError 발생 정정 (docs의 fallback "marker" 표기는 오류였음).

**verification**:
- `python -m pytest tests/ -q` → **30 passed** (test_category 16 + smoke 5
  + lint 3 + 추가 smoke import 6, 모두 통과).
- `get_category(PlaceCategoryCode.LODGING_MOUNTAIN_SHELTER_KNPS).label` =
  "숙박 > 대피소·산장 > 국립공원 대피소"
- `mapbox_maki_icon_for_category("03080100")` → "shelter"
- `get_category.cache_info().hits ≥ 1` (ADR-030 narrow cache 동작)

**다음**: PR#18 사용자 review/merge → PR#19 (`src/krtour/map/dto/` —
Feature + 7 detail kinds + NOTICE_TYPES 14건 + AreaDetail.area_kind
hazard_zone). dto는 Sprint 2부터 100% branch 강제 (ADR-032).

---

## 2026-05-25 11:00 (claude)

**작업**: Sprint 1 PR#17 — `src/krtour/map/` PEP 420 scaffolding. **첫 실제
Python 코드 commit**.

**컨텍스트**: 사용자가 PR#16 머지 후 "다음단계 ㄱㄱ"로 PR#17 진행 승인.
Sprint 1 §2.1 디렉토리 scaffolding 첫 구현. *최소 scaffolding*만 — provider
/category/dto 실 코드는 PR#18~ 후속.

**신규 파일** (13):
- `src/krtour/map/__init__.py` — `__version__ = "0.2.0-dev"` + 공개 API
  주석 + ADR 참조 (002/003/020/022/030/034).
- `src/krtour/map/py.typed` — PEP 561 marker (빈 파일).
- `src/krtour/map/settings.py` — `KrtourMapSettings(BaseSettings)`:
  - `pg_dsn: SecretStr` (PostgreSQL DSN, ADR-007)
  - `object_store_*` (S3 호환, ADR-015)
  - `log_level` / `log_format` / `log_api_calls`
  - env prefix `KRTOUR_MAP_`, `.env` 로딩, `extra="ignore"`
- `src/krtour/map/{category,dto,core,infra,providers,client}/__init__.py`
  (6건) — 각 layer placeholder + 후속 PR 매핑 주석 + ADR 참조.
- `tests/__init__.py` / `tests/lint/__init__.py` / `tests/unit/__init__.py`
  / `tests/conftest.py` (testcontainers는 PR#21).
- `tests/lint/test_no_namespace_init.py` (3 케이스):
  - `src/krtour/__init__.py`가 존재하지 않음 (ADR-022 PEP 420 enforcement)
  - `src/krtour/map/__init__.py`는 존재
  - `src/krtour/map/py.typed`는 존재
- `tests/unit/test_smoke_import.py` (5 케이스):
  - `import krtour.map` + `__version__` 노출
  - 6 layer subpackage 모두 import 가능
  - `KrtourMapSettings()` 기본값 적용
  - `KRTOUR_MAP_*` 환경변수 우선
  - `pg_dsn` SecretStr 마스킹

**`pyproject.toml`**: `pydantic-settings>=2.4` 의존 추가.

**verification**:
- 모든 신규 .py `py_compile` 통과
- `python -c "import krtour.map; print(krtour.map.__version__)"` →
  `0.2.0-dev`
- `KrtourMapSettings()` 인스턴스 생성 + `pg_dsn` SecretStr 마스킹 확인

**문서 동기**:
- `AGENTS.md §"코드 작성 금지"` — Sprint 1 active 상태 + 진행 중 가이드 +
  박혀 있는 skeleton 8건 명기.
- `docs/tasks.md` — T-014 sub-task PR#17 `[x]` + 머지 history 갱신.

**다음**: PR#17 사용자 review/merge → PR#18 (`category/` 144건 코드 이전
from kraddr-base + ADR-027 `LODGING_MOUNTAIN_SHELTER` 3행).

---

## 2026-05-25 10:00 (claude)

**작업**: **T-014 Sprint 1 진입** — ADR 027~034 일괄 proposed → accepted 전환
+ `pyproject.toml` `fail_under=0→50` 상향. PR#16.

**컨텍스트**: 사용자가 PR#15 머지 후 "ㄱㄱ" (= 다음 단계 진행)으로 T-014
승인. CLAUDE.md / SKILL.md / AGENTS.md / SPRINT-1.md 모두 "T-014 사용자
승인 시 Sprint 1 진입 + ADR 일괄 accepted 전환"으로 합의되어 있던 시점.

**ADR 8건 전환** (text only, decisions.md):
- ADR-027 (forest 카테고리/notice_type 확장): accepted
- ADR-028 (`python-knps-api` provider 등록): accepted
- ADR-029 (`@krtour/map-marker-react` npm 패키지): accepted
- ADR-030 (라이브러리 in-memory 캐시 금지): accepted
- ADR-031 (디버그 패키지 OpenAPI export): accepted
- ADR-032 (Coverage 단계적 상향 일정): accepted (시기 의존 → 확정)
- ADR-033 (`feature_consistency_reports` 단계적 도입): accepted
  (Phase 1은 Sprint 3, Phase 2는 Sprint 5에 코드 적용)
- ADR-034 (Provider 9단계 구현 순서): accepted

**Coverage bar 상향**: `pyproject.toml [tool.coverage.report] fail_under
= 0 → 50` (ADR-032 Sprint 1 bar). 주석의 Sprint 1~5 schedule 그대로.

**Sprint status**:
- `docs/sprints/README.md`: Sprint 1 = **active**, Sprint 2~5 = accepted
  (시기 대기)
- `docs/sprints/SPRINT-1.md`: 상태 → **active**
- `docs/sprints/SPRINT-{2,3,4,5}.md`: 상태 → accepted (시기 대기)

**변경 파일** (9):
- `docs/decisions.md` — ADR-027~034 §"상태" 8건 정정
- `pyproject.toml` — `fail_under=50`
- `docs/sprints/README.md` — 5건 sprint 상태
- `docs/sprints/SPRINT-1.md` — 상단 상태
- `docs/sprints/SPRINT-{2,3,4,5}.md` — 4건 상단 상태
- `docs/tasks.md` — T-014 완료 [x] + 후속 PR sequence (PR#17~#23) +
  머지 history + ADR 가이드 단순화 (전부 accepted)
- `docs/resume.md` — 현재 상태 = "Sprint 1 active" + 다음 = PR#17~#23
- `docs/journal.md` — 본 entry

**비목표 (본 PR#16)**: 실제 `src/krtour/map/` 코드 작성 / testcontainers
infra / CI workflows — 모두 PR#17~ 후속.

**다음**: PR#16 commit + push + open. 사용자 review/merge → PR#17 (`src/
krtour/map/` PEP 420 scaffolding) 시작.

---

## 2026-05-25 09:00 (claude)

**작업**: PR#15 — governance 문서 sweep. CLAUDE.md / AGENTS.md / SKILL.md
/ docs/agent-guide.md / README.md 갱신: ADR-027~034 + Sprint 1~5 + 9단계
순서 + 신설 docs 반영. 중대 bug fix 3건 (DO NOT 룰의 self-contradicting
"from krtour.map import ... 사용 금지 — 항상 from krtour.map import ...").

**컨텍스트**: PR#9~#14 머지 후 신규 ADR 8건 (027~034) + Sprint 2~5 plan 4건
+ knps-feature-etl.md + map-marker-react skeleton + frontend Next.js 전환
등이 일괄 들어왔는데, governance 문서 (1쪽 진입 reference)는 이를 반영 못함.
새 에이전트가 진입 시 핵심 정보가 누락. PR#15로 sweep.

**중대 bug fix** (DO NOT 룰의 self-contradiction 3건):
- `CLAUDE.md §5 #2`: "`from krtour.map import ...` 사용 금지 — 항상
  `from krtour.map import ...`" → "`from krtour_map import ...` (flat) 사용
  금지 — 항상 `from krtour.map import ...`".
- `AGENTS.md §"DO NOT" #18`: 동일 패턴 + "src/krtour/map/ 디렉토리 만들지
  말 것 — src/krtour/map/" → "src/krtour_map/ 디렉토리 만들지 말 것 —
  src/krtour/map/".
- `SKILL.md §4 #20`: 동일 패턴.
- 원인 추정: PR#1 (ADR-022) 적용 시 rename script가 두 string을 같은
  치환으로 처리한 사고. 사용자가 ADR-022 본문은 정확히 박혀 있어 인지 안
  됐던 잔재.

**변경 파일** (5):
- `CLAUDE.md`:
  - §2 현 단계 — "Sprint 1 진입 직전" 명기 + ADR accepted/proposed 분류
    + 9단계 순서 한 줄 inline.
  - §3 진입 순서 — `docs/sprints/README.md` 추가 (3번째).
  - §5 #2 — bug fix.
- `AGENTS.md`:
  - §"식별자" 표 — ADR accepted/proposed 분류 + Sprint plan + 9단계 순서
    행 추가.
  - §"작업 전 반드시 읽는" — sprints/README 추가.
  - §"테스트 정책" — ADR-032 Sprint 1~5 schedule + dto 100% branch 명기.
  - §"DO NOT" #18 — bug fix.
  - §"코드 작성 금지" — Sprint 1 진입 해제 시점 + 현재 허용된 예외 5건
    (pyproject 강제, export_openapi skeleton, map-marker-react skeleton,
    frontend Next.js skeleton, sprints/) 명기.
- `SKILL.md`:
  - §4 #20 — bug fix.
  - §8 첫 5분 프로토콜 — sprints/README 추가 (3번째) + ADR 027~034 명기.
  - §9 코드 작성 금지 — Sprint 1 진입 해제 + 현재 허용된 예외 5건.
- `docs/agent-guide.md`:
  - §1 첫 5분 — sprints/README 추가.
  - §2 결정·기록 → 4종 → **5종** (sprints/SPRINT-N.md 추가).
  - §3 ADR 작성 규약 — "현재 다음 번호 = ADR-035" 명기.
- `README.md`:
  - 상단 상태 — "Sprint 1 진입 직전" + ADR 027~034 proposed 명기.
  - §"빠른 시작" — Next.js frontend dev 명령 추가 (ADR-025 2차 보강 반영).
  - §"문서 지도" — `CHANGELOG.md` + `docs/sprints/SPRINT-N.md` 5건 +
    `docs/knps-feature-etl.md` 추가.

**다음**: PR#15 commit + push + open. 사용자 review 후 머지 → 다음 단계는
T-014 (Sprint 1 진입) 사용자 승인 대기.

---

## 2026-05-25 08:00 (claude)

**작업**: ADR-034 (proposed) — Provider 구현 9단계 순서 + `docs/sprints/
SPRINT-2.md` ~ `SPRINT-5.md` 신설. PR#14.

**컨텍스트**: 사용자가 구현 순서 명시:
> 축제 → 날씨 → 유가 → 휴게소 → 국립공원/트래킹코스 (인허가와 무관한 정보들)
> → 국가유산 → MOIS 인허가 → 수목원/휴양림 → 박물관/미술관

핵심 통찰: MOIS-독립 provider를 먼저 적재해 dedup 룰을 작은 dataset에서
검증 → MOIS bulk 진입 시점에 정합성 게이트가 안정 → MOIS-sibling provider
(휴양림/수목원/박물관 — MOIS와 중복 가능)는 검증된 룰로 진입.

**ADR-034 결정 — Sprint 매핑**:
- Sprint 2: ① 축제 → ② 날씨 → ③ 유가 → ④ 휴게소 (MOIS-독립 작은 dataset)
- Sprint 3: ⑤ 국립공원/트래킹 → ⑥ 국가유산 + ADR-033 Phase 1 (F1~F3)
- Sprint 4: ⑦ MOIS bulk 4단계 + dedup queue 운영 + Coverage 80% 도달
- Sprint 5: ⑧ 휴양림/수목원 → ⑨ 박물관/미술관 + Phase 2 + T-200~204 + 운영
  진입

**변경 파일** (8):
- `docs/decisions.md`: ADR-034 (proposed) ~150줄 신설.
- `docs/sprints/README.md`: Sprint 1~5 표 + 9단계 inline + ADR 목록 갱신.
- `docs/sprints/SPRINT-1.md` §5: provider 호출 Sprint 2부터 명확화.
- `docs/sprints/SPRINT-2.md` 신설 (~180줄): MOIS-독립 4 provider.
- `docs/sprints/SPRINT-3.md` 신설 (~150줄): KNPS + krheritage + Phase 1.
- `docs/sprints/SPRINT-4.md` 신설 (~140줄): MOIS 4단계 + queue + 분할 옵션.
- `docs/sprints/SPRINT-5.md` 신설 (~200줄): sibling + Phase 2 + 운영 진입.
- `docs/tasks.md`: §"진행 중" PR#14 추가, ADR-034 ADR 가이드 추가, 머지
  history 갱신.
- `docs/resume.md`: 완료 task 명시 + ADR-034 추가.

**다음**: PR#14 commit + push + open. 사용자 review → ADR-034 accepted
전환 후 T-014 (Sprint 1 진입) 가능.

---

## 2026-05-25 07:00 (claude)

**작업**: PR#12 — `python-knps-api` (외부 repo scaffold 완료) 통합 반영 +
ADR-028 (proposed). knps-api 측 PR#1 (maki icon 정정) 동시 진행.

**컨텍스트**: 사용자가 `digitie/python-knps-api` 저장소를 push 완료
(`6e36990 Initial KNPS API client scaffold`). 본 라이브러리 통합 작업
+ knps-api 측 발견 이슈는 upstream PR로 직접 수정 정책 (ADR-025 사용자
보강 2차 패턴 미러).

**upstream knps-api repo 상태 (`6e36990`)**:
- 공개 API: `KnpsClient`, `KnpsConfig`, `ApiEndpoint`, `FileDataset`,
  `CatalogEntry`, `Page`, `PROVIDER_NAME="python-knps-api"`, 예외 7종
  (`KnpsApiError`/`KnpsAuthError`/...), helper 5종 (`api_endpoint`,
  `api_endpoints`, `catalog_entries`, `file_dataset`, `file_datasets`).
- catalog: API 3건 (`knps_visitor_statistics`, `knps_access_restrictions`,
  `knps_fire_alerts`) + 파일 11건 (forest §11.3 7건 + §11.4 4건 추가:
  campgrounds/shelters/recommended_courses/park_photos/visitor_statistics).
- 인증: `KNPS_SERVICE_KEY` 우선, `DATA_GO_KR_SERVICE_KEY` 폴백
  (`knps.config.KnpsConfig.from_env`).
- HTTP: `KnpsHttp` (httpx async + token bucket 5 RPS + `_decode_payload` +
  `_normalize_payload` data.go.kr envelope 자동 정규화 + service_key
  auto-redact in `CallContext.request_params`).
- 파일: `client.files.download(key)` — `download_url` 검증된 dataset만.
- SHP/GeoJSON parser: `[geo]` extra (`pyproj`, `pyshp`) — placeholder, 본
  라이브러리 측에서 처리 권고 (ADR-006 정신).

**knps-api 측 PR#1 (https://github.com/digitie/python-knps-api/pull/1)**:
- `docs/knps-feature-etl.md §4` maki icon 2건 정정:
  - 대피소: `lodging` → `shelter` (본 라이브러리 ADR-027의
    `PLACE_CATEGORY_MAPBOX_MAKI_ICONS[LODGING_MOUNTAIN_SHELTER]` 정합)
  - 위험지역: `danger` → `barrier` (Maki 표준에 `danger` 없음)
- 표 아래 downstream 정합 명기.

**본 라이브러리 PR#12 변경 파일**:
- `docs/decisions.md` — **ADR-028 (proposed)** 신설 (~110줄):
  - provider 등록 6항목 (canonical name / import / module / dataset prefix
    / 인증 env / pyproject extras).
  - SHP/GeoJSON 파싱 책임 분리 (본 라이브러리 권고).
  - ADR-027 코드 적용 시기 정렬 (T-018 동시).
  - 양방향 PR 워크플로 (D, maplibre-vworld-js 패턴 미러).
  - 본 라이브러리 신설 `docs/knps-feature-etl.md`.
  - 14 dataset_key 카탈로그 (API 3 + 파일 11).
- `docs/forest-feature-etl.md §11`:
  - "데이터 통합 계획" → "데이터 통합" (현재형, scaffold 완료 반영).
  - §11.1 옵션 B "권고" → "채택 ✅".
  - §11.1.1 신설 — 외부 라이브러리 공개 API 표면 + 특이사항 (현 구현 상태).
- `docs/knps-feature-etl.md` 신설 (~220줄):
  - feature 적재 계약 (upstream knps-feature-etl.md와 정합).
  - dataset 매핑 14건 (API 3 + 파일 11).
  - cultural_resources RESOURCE_TYPE 분기.
  - 매핑 룰 (area / route / place / weather / notice / timeseries+media).
  - category 매핑 검증 표 (shelter / barrier 정합).
  - 핵심 함수 시그니처 후보 (Sprint 2).
  - Dagster asset 12종.
  - 검증 (fixture / EXPLAIN / 정합성 / upstream verification).
- `docs/provider-contract.md`:
  - §2 `CANONICAL_PROVIDER_NAMES`에 `python-knps-api` 추가.
  - §3 dataset_key 표에 14건 추가.
  - §4 책임 매트릭스에 한 줄 추가.
- `docs/external-apis.md`:
  - §2 환경변수 카탈로그에 `KNPS_SERVICE_KEY` 추가.
  - §3.8.1 신설 — KNPS API key 발급 절차.
- `pyproject.toml` — `providers` extras에 `python-knps-api` git URL 주석.

**SHP/GeoJSON parsing 위치 결정 (잠정)**:
- 본 라이브러리 `krtour.map.providers.knps`에서 파싱 권고 — provider
  라이브러리는 raw bytes/page만, 변환은 본 라이브러리 책임 (ADR-006 정신).
- Sprint 2 진입 시 cost/benefit 재평가 후 최종 결정. knps-api `[geo]` extra
  가 이미 있으므로 양쪽 모두 가능.

**다음**: PR#12 commit + push + open. PR#10/PR#11과 forest-feature-etl.md /
journal.md / resume.md / tasks.md 충돌 가능 — append 위주라 resolvable.
knps-api PR#1 merge 후 본 라이브러리 `docs/knps-feature-etl.md` 동기.

---

## 2026-05-25 06:00 (claude)

**작업**: ADR-025 2차 사용자 보강 — frontend 빌드 도구 **Vite → Next.js**
정정. PR#11.

**컨텍스트**: 사용자 한 줄 지시 "디버그 ui는 next.js 기반임." 1차 결정 시
"React + Vite"로 박았던 것이 잠정 가설이었고, `kraddr-geo-ui`와 TripMate
`apps/web` 모두 Next.js이므로 stack 통일을 위해 Next.js로 정정.

**변경 파일**:
- `docs/decisions.md`:
  - ADR-025 §컨텍스트 후보 옵션 — "Next.js/Vite SSR 지원" → "Next.js App
    Router 지원" 정정.
  - ADR-025 §결정 — "React + Vite + TypeScript" → "Next.js 15 (App Router)
    + React 19 + TypeScript".
  - ADR-025 §결정 — 빌드/개발/env 설명 Next.js로 변경.
  - ADR-025 §근거 — kraddr-geo-ui 일관 + TripMate `apps/web` 동일 stack
    명기.
  - ADR-025 §결과(긍정/부정) — Vite → Next.js로 정정.
  - **ADR-025 §사용자 보강 (2026-05-25, 2차) — 빌드 도구 정정** 신설:
    `next dev --port 8610`, App Router, `NEXT_PUBLIC_*` env, `@krtour/
    map-marker-react` transpilePackages, 운영 옵션 3가지 (standalone /
    proxy / export).
  - §후속 — Vite skeleton → Next.js로 본 PR#11에서 전환 명기.
- `docs/debug-ui-package.md` §14 전체 갱신:
  - §14.1 기술 스택 — Framework Next.js 15 (App Router) 추가, 빌드 도구
    Vite 행 삭제, 공통 마커 `@krtour/map-marker-react` (ADR-029) 추가.
  - §14.2 환경변수 — `VITE_*` → `NEXT_PUBLIC_*` 일괄 정정.
  - §14.3 기동 — Next.js dev 명령 + 운영 옵션 3가지 (standalone / FastAPI
    reverse proxy / static export).
  - §2 디렉토리 트리 — `vite.config.ts`/`index.html`/`src/main.tsx`/`pages/`
    삭제, `next.config.js`/`src/app/` (App Router) 추가, categoryMaki/
    markerColor는 `@krtour/map-marker-react`로 이전 명기.
  - §9 테스트 — Playwright + Vitest (Next.js 공식 가이드 미러).
  - §10 외부 노출 — `Vite` → `Next.js dev/standalone` 정정.
- `docs/external-apis.md` — VWorld 항목 `VITE_VWORLD_API_KEY` →
  `NEXT_PUBLIC_VWORLD_API_KEY` 정정.
- `docs/tripmate-integration.md` §14.5:
  - Next.js 명기 (두 UI 동일 stack).
  - `@krtour/map-marker-react` 사용 명기.
  - 작업 분담에 "Next.js 그대로 유지, 마커 import만 교체" 명기.
- `packages/krtour-map-debug-ui/README.md`:
  - "React + Vite + maplibre-vworld" → "Next.js + React 19 + maplibre-vworld"
  - 운영 배포 옵션 3가지 명기.
  - Backend env 표의 "Vite dev 서버" → "Next.js dev 서버".
  - Frontend env 표 `VITE_*` → `NEXT_PUBLIC_*`.
- `packages/krtour-map-debug-ui/frontend/package.json` — 전체 교체:
  - `vite`/`@vitejs/plugin-react`/`vitest` → `next`/`eslint-config-next`/
    `@types/node`.
  - scripts: `vite` → `next dev/build/start/lint`.
  - dependencies: `next`/`@krtour/map-marker-react` (workspace) 추가.
- `packages/krtour-map-debug-ui/frontend/.env.example`:
  - `VITE_*` → `NEXT_PUBLIC_*`.
  - 주석에 Next.js env 규약 (NEXT_PUBLIC_ vs server-only) 명기.
- `packages/krtour-map-debug-ui/frontend/.gitignore`:
  - `dist/` 삭제, `.next/`/`out/`/`next-env.d.ts` 추가, `.vite/` 삭제.
- `packages/krtour-map-debug-ui/frontend/README.md`:
  - 기술 스택 표 Next.js 행 추가, Vite 삭제, env `NEXT_PUBLIC_*`.
  - 개발 명령 `next dev --port 8610`.
  - 빌드 / 운영 옵션 3가지 추가.
  - 페이지 표를 App Router route (`/features/[id]` 등)로 변경.
  - categoryMaki 매핑은 `@krtour/map-marker-react` 사용 (ADR-029) 명기.
- `packages/krtour-map-debug-ui/frontend/next.config.js` 신설:
  - reactStrictMode + transpilePackages (`@krtour/map-marker-react`)
  - 운영 옵션(`output: 'standalone'/'export'`, `basePath`, `rewrites`)은
    주석 처리 — 운영자 결정 후 활성화.
- `docs/tasks.md` — §폐기/재해석 — T-100 "Next.js 미채택" 기록은 잘못됨
  명기, ADR-025 2차 보강으로 채택 확정.

**핵심 인사이트**: kraddr-geo-ui = Next.js이고 TripMate `apps/web` = Next.js
이므로 디버그 UI도 Next.js가 자연. 1차에서 Vite로 박았던 것은 SPA의 단순함
가정에서 비롯됐으나, 운영 일관성 (학습 곡선 통일 + `@krtour/map-marker-react`
transpilePackages 단일 설정) 가치가 더 큼.

**다음**: PR#11 commit + push + open. PR#10과 충돌 가능 (양쪽이 frontend
README/package.json 일부 영역 수정) — 작은 충돌, resolvable.

---

## 2026-05-25 05:00 (claude)

**작업**: PR#10 — T-012~T-018 진행 + ADR-029 (proposed) + T-101~103 상세
분석 + 명명 일치화 + 코딩 (`pyproject.toml` 강제 + scripts skeleton).

**컨텍스트**: 사용자 지시 5건 동시 진행:
1. PR#9 rebase → 다시 PR (완료).
2. T-101~103 상세 의견을 문서에 반영.
3. T-012~T-018 진행 + ADR-029 작성 + tasks.md 갱신.
4. 필요한 코딩 (사용자가 "필요한 코딩도 할 것"으로 명시 허용 — 제한된
   scope, scaffolding/policy 강제 위주).
5. `python-krmois-api` → `python-mois-api` 일괄 + 비슷한 명명 일치화.
6. `digitie/python-knps-api` 모니터링 (외부에서 1시간 내 개발 완료 예정) →
   반영. 현 시점 repo 상태: empty, size=0. 백그라운드 agent 모니터링 시도
   했으나 권한 거부 — 본 세션에서 주기 체크 후 후속 PR로 반영 예정.

**결정 / 신규 ADR**:
- **ADR-029 (proposed)**: `@krtour/map-marker-react` npm 패키지 추출. MIT
  라이선스 (TripMate proprietary 호환). monorepo `packages/map-marker-react/`.
  본 라이브러리 PR에서 Python 카테고리/notice 변경과 동시에 TypeScript
  매핑 변경 → drift 0. 게시는 공개 npm.

**상세 분석 문서화 (T-101~103)**:
- `docs/performance.md §9.3` (T-101 MV): 도입 장점 (7-way JOIN → single
  table scan), 조건 (read >> write, REFRESH lag 허용, 디스크 ×2, 정합성
  게이트 선행), 부작용 (DDL 무거움, stale 혼동), 절차 (시범 → 1주 운영
  → ADR 신설).
- `docs/performance.md §9.4` (T-103 streaming): 시나리오 (산불경보/특보
  초 단위), 라이브러리 위치 (consumer는 TripMate, 본 라이브러리는 함수
  만). `pyproject.toml`에 `kafka`/`aiokafka`/`confluent_kafka`/`faust`
  import 차단 계약 추가.
- `docs/performance.md §9.5` (T-102 pg_prewarm): 장점 (cold-start cliff
  제거), 조건 (P99 SLO + 재배포 빈도 + shared_buffers fit), 절차
  (`autoprewarm = on` background + `/health` 표시).

**명명 일치화 (잔존 krmois 정리)**:
- `docs/forest-feature-etl.md:173` 컨벤션 예시: `python-krmois-api` →
  `python-mois-api`.
- `docs/mois-license-feature-etl.md:115` 예시 payload: `krmois_admin_address`
  → `mois_admin_address`.
- `docs/journal.md:151` 컨벤션 예시: `krmois/krheritage/krforest` →
  `mois/krheritage/krforest`.
- `docs/journal.md:475` 옛 provider 목록: `krmois` → `mois (구 krmois)`.
- ADR-024 migration 본문 / journal ADR-024 narrative / mois-feature-etl.md
  v1→v2 마이그레이션 표 등 *역사 기록* 컨텍스트의 krmois 표기는 유지
  (rename 사건 자체를 기록).

**코딩 (사용자 명시 허용)**:
- `CHANGELOG.md` 확장 — [Unreleased] §결정 (PR#6~PR#10 시기) + 문서 확장
  + 명명 일치화 + 코드 변경 모두 inline.
- `pyproject.toml`:
  - `[tool.coverage.report]` ADR-032 Sprint 1~5 schedule 주석 inline.
  - `[[tool.importlinter.contracts]]` `cachetools`/`async_lru`/`aiocache`/
    `diskcache` 차단 (ADR-030).
  - `[[tool.importlinter.contracts]]` `kafka`/`aiokafka`/`confluent_kafka`/
    `faust` 차단 (T-103/ADR-103 후보).
- `packages/krtour-map-debug-ui/scripts/export_openapi.py` 신설 — ADR-031
  CLI skeleton. `--check` drift gate. 코드 작성 단계 진입 전에는 module
  not found 가이드 출력.
- `packages/map-marker-react/` skeleton 신설 (`package.json` / `README.md`
  / `vite.config.ts` / `.gitignore`) — ADR-029 placeholder.
- `docs/sprints/` 신설 — `README.md` (Sprint 1~5 표) + `SPRINT-1.md` 초안
  (진입 조건 + 산출물 + DoD + Sprint 2 진입 조건).

**문서 갱신**:
- `docs/tasks.md` — T-012/013/017/018 상태 갱신, T-013 [x], T-101~103 상세
  내용 inline + 도입 조건/절차, "ADR 번호 가이드" proposed/후보 분류.
- `docs/resume.md` — "코드 작성 단계 진입 전" + "다음 ADR" 갱신.

**python-knps-api 모니터링 상태**:
- 현재 (2026-05-25 05:00 시점) `digitie/python-knps-api` repo는 size=0
  empty.
- 백그라운드 agent 실행 실패 (Bash/PowerShell/WebFetch 권한 거부).
- 본 세션에서 주기 체크 (~30분마다) → 콘텐츠 발견 시 후속 PR로 반영.
  반영 대상: ADR-028 본문 초안, `docs/forest-feature-etl.md §11` 갱신,
  새 `docs/knps-feature-etl.md` (필요 시).

**다음**: PR#10 commit + push + open. 사용자 review → merge → T-014 PR로
Sprint 1 진입.

---

## 2026-05-25 04:00 (claude)

**작업**: ADR-027 (proposed) — forest 카테고리/notice_type 확장 결정. 사용자
가 forest §11.6 candidates에 대한 의견 요청 + 입산통제/산불경보를 generic
notice_type으로 일반화 지시.

**컨텍스트**: forest §11.6에 7건 candidates가 있었고, 사용자가 그 중
입산통제/산불경보를 `forest_*` prefix 없이 generic 이름으로 일반화 결정.
나머지(대피소 / hazard_zone / 거부 항목)는 claude 제안 그대로 채택.

**결정 요약** (decisions.md ADR-027):
- ✅ `LODGING_MOUNTAIN_SHELTER` (Tier 2 `03.08` + Tier 3 `03.08.01` KNPS /
     `03.08.02` KFS, maki=`shelter`)
- ✅ `AreaDetail.area_kind='hazard_zone'` 신설 (PlaceCategory 미신설)
- ✅ `notice_type='access_restriction'` (generic, 입산통제/해수욕장폐장/
     공원폐쇄 등 통칭, payload.domain으로 출처 구분)
- ✅ `notice_type='fire_alert'` (generic, 산불경보 + 화재 일반)
- ❌ `WEATHER_MOUNTAIN_STATION` PlaceCategory (kind=weather 자체로 충분)
- ❌ `NATURE_ECOLOGY` PlaceCategory (v2 1차 범위 밖)
- ❌ `SAFETY_*` PlaceCategory / Tier 1 `08 SAFETY` (area_kind으로 대체,
     Tier 1 enum 변경 회피)

**변경 파일**:
- `docs/decisions.md`: ADR-027 (proposed) 추가 (~120줄).
- `docs/category.md`:
  - §4.2 트리 — `03.08` Tier 2 + Tier 3 두 행 추가.
  - §4.3 depth 통계 — Tier 2 29→30, Tier 3 71→73, 합계 141→144.
  - §4.4 maki icon 분포 — `shelter` 3건 추가.
- `docs/notice-feature-etl.md`:
  - §3 NOTICE_TYPES — `access_restriction` / `fire_alert` 추가.
  - §3 normalize_notice_type alias 표 — 입산통제/해수욕장폐장/산불경보 등
    한/영 alias 추가.
  - §7 마커 스타일 표 — 두 신규 type 매핑 추가 (maki `barrier`/`fire-station`).
- `docs/feature-model.md` §9: AreaDetail.area_kind에 `hazard_zone` 추가
  + payload 예시 주석.
- `docs/data-model.md` §6.3: `feature_area_details.area_kind` 컬럼 주석에
  `hazard_zone` 명기 + payload 주석.
- `docs/forest-feature-etl.md`:
  - §11.4 추가 발굴 후보 표 — `knps_shelters` (LODGING_MOUNTAIN_SHELTER_KNPS),
    `knps_access_restrictions` (generic notice_type), `knps_fire_alerts`
    (generic notice_type), 식생/서식지 (v2 범위 밖) 명기.
  - §11.6 후보 표 → ADR-027 결정 요약 표로 대체 (✅/❌ 분류).
  - §11.8 후속 작업 — ADR-027 proposed → accepted 전환 명기.
- `docs/resume.md`: "다음 ADR 후보"의 ADR-027 항목을 proposed로 명기 +
  사용자 결정 내용 inline.
- `docs/tasks.md`:
  - T-018 — ADR-027 proposed 결정 완료 명기 + accepted 전환 시점 = T-018
    실행 시점.
  - §"ADR 번호 가이드" — proposed 섹션 신설 (ADR-027).

**작성 시기 의도**: T-018 (`python-knps-api` provider 등록) 시점에 코드와
함께 accepted 전환. 지금 proposed로 박는 이유는 KNPS dataset이 확정되기
전이라도 *분류 정책*은 명확히 박혀 있어 작업 협상 비용 0.

**다음**: 사용자 review → accepted 전환 또는 추가 조정. PR#8 (ADR-030~033
proposed)과 텍스트 충돌 가능 (resume.md/tasks.md) — 머지 순서에 따라 한
쪽이 rebase 필요.

---

## 2026-05-25 03:00 (claude)

**작업**: ADR-030/031/032/033 `proposed` 작성 — 사용자가 의견 요청한 4건을
공식 ADR로 박음 + 관련 docs 교차 링크.

**컨텍스트**: 사용자가 ADR-030/033 → ADR-031/032 순으로 의견 요청. 의견을
지속 기록으로 남기지 않으면 다음 conversation에서 다시 협상해야 함 →
`proposed` ADR로 정식 박음. T-014(코드 작성 단계 진입 결정)에서 시기 의존
ADR(032/033)은 Sprint 일정 확정과 함께 accepted 전환.

**변경 파일**:
- `docs/decisions.md`:
  - **ADR-030 (proposed)**: 라이브러리 in-memory 캐시 금지. `functools.cache`
    한정 narrow 예외 (PlaceCategoryCode 카탈로그, `pyproj.Transformer`
    singleton). `import-linter` 계약으로 `cachetools`/`async_lru`/`aiocache`/
    `diskcache` 의존 차단.
  - **ADR-031 (proposed)**: 디버그 패키지 OpenAPI export 첫 FastAPI 라우터
    등장 PR부터 즉시 활성화. `openapi.json` 저장소 커밋 + CI `--check` gate.
    frontend 도입 전부터 drift gate 가동 → type drift 부채 0.
  - **ADR-032 (proposed, 시기 의존)**: Coverage 단계적 상향 일정 (Sprint 1
    50% → Sprint 4 80%). `dto/`는 Sprint 2부터 100% branch 항상 강제.
    T-014에 묶어 accepted 전환.
  - **ADR-033 (proposed, 시기 의존)**: `feature_consistency_reports` 두 단계
    분할 도입. Phase 1 (Sprint 3~4) = 스키마 + F1~F3 (orphan source / detail
    누락 / CRS drift, severity=ERROR, 게이트 미적용). Phase 2 (Sprint 5) =
    F4~F8 + Dagster 게이트 + swap 차단. T-014에 묶어 accepted 전환.
- `docs/resume.md`: "다음 ADR 후보" → "다음 ADR (proposed / 후보)" 재분류.
  ADR-030/031/032/033을 proposed로 명기.
- `docs/tasks.md`: T-012 항목을 `proposed` 4건으로 갱신. §"ADR 번호 가이드"에
  proposed 섹션 추가.
- `docs/performance.md §9.1`: ADR-030 링크 + narrow 예외 + import-linter
  계약 명기.
- `docs/test-strategy.md §2`: ADR-032 link + Sprint별 coverage schedule 표
  inline.
- `docs/dagster-boundary.md §12`: ADR-033 link + Phase 1/Phase 2 분할 명기.
- `docs/debug-ui-package.md §8`: ADR-031 link + 활성화 시점 명기.

**다음**: 사용자 review → ADR-030/031은 accepted 전환 가능 (코드 작성 단계
독립). ADR-032/033은 T-014 시점에 Sprint 일정 확정 후 accepted 전환.

---

## 2026-05-25 02:00 (claude)

**작업**: 사용자의 4건 의사결정 반영 — (1) VWorld key 공유, (2) TripMate
사용자 UI도 maplibre-vworld 통일, (3) frontend 코드는 별도 PR, (4)
maplibre-vworld-js upstream 적극 수정.

**컨텍스트**: PR#6 (ADR-025)의 결과(부정) 두 항목 — "VWorld key 별도 발급
vs 공유 미정" + "provider 라이브러리 stability 모니터링 필요" — 에 사용자가
명시 결정을 내림.

**변경 파일**:
- `docs/decisions.md`:
  - ADR-025 §결과(부정) 정리 — 공유 정책 확정으로 부정 항목 1개 흡수.
  - ADR-025 §사용자 보강(2026-05-25) 신규 — 1. key 공유 / 2. upstream 직접 PR.
  - ADR-025 §후속 — forest §11.6 후보 번호 ADR-026 → ADR-027 (ADR-026이
    TripMate UI 통일에 선점).
  - **ADR-026 신규**: TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8
    v8_3 supersede). 두 UI 단일 stack, Kakao Maps JS SDK 제거. 공통 maki
    npm 패키지 추출은 후속 ADR.
- `docs/external-apis.md`:
  - 환경변수 카탈로그에 `KRADDR_GEO_VWORLD_API_KEY` 항목 추가 (공유 키 명기).
  - §8 비용 관리에서 Kakao Maps JS SDK 항목 → "미사용 (ADR-026)" 처리.
  - VWorld 항목에 ADR-025 보강 + ADR-026 사용처 추가.
- `docs/debug-ui-package.md`:
  - §14.2 환경변수 — VITE_VWORLD_API_KEY 설명을 "공유 키" 명기, 운영자
    주입 절차 박음. TripMate UI 공유 명기.
  - §14.8 외부 노출 안전 — referrer 화이트리스트에 backend + TripMate 호스트.
  - §15 핵심 메시지 — 공유 정책 + upstream 적극 수정 정책 박음.
- `docs/tripmate-integration.md`:
  - §14.5 신설 — TripMate 사용자 UI 지도 stack (ADR-026), Kakao 제거, 공유 키.
- `docs/forest-feature-etl.md`:
  - §11.6 heading + 본문 2곳: "ADR-026 후보" → "ADR-027 후보".
  - §11.8 후속 ADR-026/027 → ADR-027/028.
- `docs/resume.md`:
  - 진척도에 ADR-025 보강 + ADR-026 추가 (둘 다 [x] 완료).
  - "다음 ADR 후보" 정리 — 이미 accepted된 ADR-021~024 항목 제거, 후보 번호
    ADR-027부터 재배열 (027 카테고리 확장, 028 KNPS provider, 029 공통 maki
    npm 패키지, 030 캐시, 031 OpenAPI, 032 coverage, 033 정합성).
- `packages/krtour-map-debug-ui/frontend/.env.example`:
  - VITE_VWORLD_API_KEY 주석 — "= $KRADDR_GEO_VWORLD_API_KEY 값과 동일" 박음.
- `packages/krtour-map-debug-ui/frontend/README.md`:
  - 환경변수 표 — 공유 정책 명기 + TripMate UI 공유 박음.

**커밋 메시지 후보**: `ADR-025 보강 + ADR-026: VWorld key 공유 + TripMate UI 통일`

**다음**: PR#6에 본 커밋 추가 push → 사용자 검토 → merge. 머지 후 ADR-029
(공통 maki npm 패키지 추출) 검토 시점에 다시 결정.

---

## 2026-05-25 01:00 (claude)

**작업**: 디버그 UI frontend 기술 결정 — `maplibre-vworld-js` 채택 (ADR-025).

**변경 파일**:
- `docs/decisions.md`:
  - **ADR-025 신설** — 디버그 UI frontend는 React + Vite + TS + `maplibre-vworld`
    + `maplibre-gl` + `zod`. Kakao Maps SDK 사용 안 함. VWorld 1차.
  - ADR-023 orphan duplicate (line 657~717) 정리 (이전 편집 사고 잔재).
- `docs/debug-ui-package.md` §2 디렉토리 + §14 신설 (~120 lines):
  - frontend 디렉토리 추가 (Vite, src/components/api/lib)
  - §14.1 기술 스택 (maplibre-vworld v1.0.0, ISC license, React 19, Vite,
    포트 8610)
  - §14.2 환경변수 (`VITE_VWORLD_API_KEY`, `VITE_KRTOUR_MAP_DEBUG_UI_API`)
  - §14.3 기동 (backend uvicorn 8600 + frontend Vite 8610)
  - §14.4 핵심 컴포넌트 매핑 (`<VWorldMap>`, `<MakiMarker>`, `<MarkerClusterer>`, etc.)
  - §14.5 category → maki icon 매핑 (`categoryMaki.ts`)
  - §14.6 OpenAPI → TypeScript 동기 (kraddr-geo ADR-015 미러)
  - §14.7~14.8 e2e + 외부 노출 안전
- `packages/krtour-map-debug-ui/README.md` — Frontend 절 추가 + env 표 분리
  (Backend / Frontend)
- **NEW**: `packages/krtour-map-debug-ui/frontend/`:
  - `package.json` (의존성 placeholder)
  - `.env.example` (VITE_VWORLD_API_KEY)
  - `.gitignore`
  - `README.md`
- `docs/external-apis.md` — VWorld API key 항목 추가 (디버그 UI용).
- `docs/forest-feature-etl.md` §11.6 — ADR-025 후보 → ADR-026 후보 renumber
  (카테고리 확장은 향후 ADR-026, knps provider 등록은 ADR-027).
- `docs/resume.md` — 후보 ADR 번호 재정렬 (ADR-026/027/028+).

**결정**:
- **ADR-025** — 디버그 UI frontend는 `maplibre-vworld-js` 채택.
  - VWorld 지도 (국토교통부 공식) — 한국 행정구역/도로명주소와 정합.
  - WebGL 60fps + MakiMarker + MarkerClusterer 내장 → 10만+ feature 처리.
  - 선언형 React → 상태 동기 단순.
  - `kraddr-geo-ui`와 동일 stack (React + Vite + TS) → 운영 일관.
  - Kakao Maps SDK 사용 안 함 (디버그 UI 측만).
  - 디렉토리: `packages/krtour-map-debug-ui/frontend/`.
  - 의존: `maplibre-vworld` v1.0.0 (ISC), `maplibre-gl` (BSD-3), `zod`, React 19.
  - VWorld API key는 `python-kraddr-geo`의 `KRADDR_GEO_VWORLD_API_KEY` 공유
    또는 별도 `VITE_VWORLD_API_KEY`.

**의사결정 (사용자 위임 — 검토 부탁)**:
- VWorld API key 발급 정책: `python-kraddr-geo`와 공유 vs 디버그 UI 전용 별도
  발급 (운영자 결정).
- TripMate 사용자 UI는 SPEC V8 v8_3 그대로 Kakao Maps SDK 유지 — 본 ADR은
  디버그 UI에만 해당.
- frontend 코드 작성은 별도 PR (코드 작성 단계 진입 시).

**발견**:
- `maplibre-vworld-js` (`digitie/maplibre-vworld-js`)는 npm `maplibre-vworld`
  v1.0.0, React/TypeScript, ISC license. 본 사용자 운영 저장소라 의존성 리스크
  낮음.
- 라이선스 호환성: ISC + BSD-3 + GPL-3.0 모두 호환 (GPL-3.0이 가장 strict이라
  배포 시 GPL 준수).
- `kraddr-geo-ui` Next.js 패턴과 비교했을 때 디버그 UI는 SPA로 충분 (Vite 만
  사용, Next.js SSR 불필요).

**다음**: PR push + 사용자 검토. PR merge 후 backlog T-200/T-201 + ADR-026/027
(카테고리 확장 + KNPS provider).

---

## 2026-05-25 00:30 (claude)

**작업**: outdoor → forest rename + 모든 feature에 category 명시 + KNPS
국립공원공단 datasets 카탈로그 + category.md Tier 1~4 상세 테이블.

**변경 파일**:
- **rename**: `docs/outdoor-feature-etl.md` → `docs/forest-feature-etl.md` (git mv)
- **신규 섹션**:
  - `docs/category.md` §4 — Tier 1~4 전체 141건 카탈로그 (트리 뷰 + maki icon 분포 표 + provider별 주된 카테고리 매핑 표)
  - `docs/forest-feature-etl.md` §11 — KNPS (국립공원공단) 데이터 통합 계획
    (provider 옵션 A/B/C 비교 + 권고, 핵심 dataset 7건 정밀 정리, 추가 발굴
    8건, Dagster asset 11종, 카테고리 확장 후보 7건)
- **갱신** (모든 ETL doc에 명시적 category code 추가):
  - `docs/forest-feature-etl.md` §4 — 8개 카테고리 (`03030101` 국립휴양림,
    `01030102` 수목원 등) 명시
  - `docs/khoa-beach-info-etl.md` — `01050100` `TOURISM_NATURE_BEACH`
  - `docs/opinet-place-price-etl.md` — `06020000` `TRANSPORT_FUEL`
  - `docs/krex-rest-area-feature-etl.md` — `06040101` `TRANSPORT_REST_AREA_HIGHWAY_EX`
  - `docs/event-feature-etl.md` — `TOURISM` 대분류 + EventDetail.event_kind
  - `docs/krheritage-feature-etl.md` §4-pre — `01070100~400` 4개 매핑 표
  - `docs/mois-feature-etl.md` §6.1 — 42 슬러그 → 정확한 카테고리 코드 매핑
    (식음/숙박/관광/문화 모두 실 카테고리 트리 기준)
  - `docs/standard-data-feature-etl.md` §2 — 5종 dataset에 category 추가
  - `docs/notice-feature-etl.md` §2.5 — notice는 카테고리 비움 / notice_type
    분류
  - `docs/kma-weather-etl.md` §1 — weather-only anchor 카테고리 규약
  - `docs/place-phone-enrichment.md` §1 — enrichment는 카테고리 변경 X
  - `README.md` — 문서 지도에 forest-feature-etl 갱신
  - `docs/resume.md` — outdoor → forest

**의사결정 (사용자 위임, 검토 부탁)**:
- **KNPS provider 옵션 B 권고** — 별도 `python-knps-api` 신설.
  - 이유: 1기관 1라이브러리 컨벤션 (mois/krheritage/krforest 등과 동일).
    KNPS는 환경부 산하, 산림청은 농림식품부 — 별도 기관. file dataset(SHP/
    GeoJSON) 처리 모듈 응집.
  - dataset_key prefix: `knps_*` (13개 + 추가 후보).
- **사용자 명시 7건 + 추가 8건** dataset 카탈로그 작성. data.go.kr ID는 web
  access 차단으로 **확인 필요** 표시 (15084538~15084545 추정).
- **카테고리 확장 후보 (ADR-025 후보)**:
  - `SAFETY_HAZARD_ZONE` (위험지역)
  - `LODGING_MOUNTAIN_SHELTER` (산장)
  - `WEATHER_MOUNTAIN_STATION` (관측소 anchor)
  - `NATURE_ECOLOGY` (식생/서식지)
  - `notice_type=forest_access_restriction` / `forest_fire_alert`
  - `area_kind=hazard_zone`
- **MOIS 식음 매핑은 부모 카테고리로 default** — `02010100` 한식 또는
  `02010000` 부모. provider가 세부 업태 자동 분류 데이터 미제공이라 보수적.
  세부 분류는 향후 ADR.

**발견**:
- `python-kraddr-base/src/kraddr/base/categories.py`는 총 141건 (Tier 0
  sentinel 1 + Tier 1 7 + Tier 2 29 + Tier 3 71 + Tier 4 33).
- maki icon 55종 unique 사용. `park` 11회 (휴양림/공원/트레킹), `lodging` 11회
  (호텔/리조트/모텔/게스트하우스) 등.
- KNPS 위험지역/관측소/산장 같은 카테고리가 현재 트리에 없음 → 카테고리 확장
  필요 (사용자 검토 후 ADR-025 작성).
- v1 `outdoor-feature-etl.md`에 KNPS dataset 단서는 없었음 — 본 §11이 v2의
  첫 정밀 카탈로그.

**다음**: PR#3 push + 사용자 검토. PR 일괄 merge 후 backlog T-200/T-201 (Sprint
5 batch DAG + consistency_reports), ADR-025 (카테고리 확장 — 사용자 결정 후).

---

## 2026-05-24 23:30 (claude)

**작업**: `python-mois-api` 활용 feature 적재 full lifecycle 문서화 + canonical
name 정정 (`python-krmois-api` → `python-mois-api`, ADR-024) + 일괄 rename.

**변경 파일**:
- **신규**:
  - `docs/mois-feature-etl.md` — 4 step lifecycle (A: source DB sync,
    B: 영업중 승격, C: 이력조회 incremental, D: on-demand detail) +
    195 슬러그 카탈로그 + PROMOTED 42종 (식음/숙박/관광/문화/MICE/스포츠/레저) +
    EXCLUDED 분류 + dataset_key 4종 (`mois_license_features_bulk` /
    `_history` / `_closed` / `mois_license_detail`) + PROMOTED_PLACE_KIND_BY_SLUG
    매핑 + Dagster asset 5종.
- **갱신**:
  - `docs/decisions.md` — **ADR-024** 신설 (canonical name 정정 +
    `LEGACY_PROVIDER_ALIASES` `krmois`/`pykrmois`/`python-krmois-api` 추가).
    중간 편집 사고로 일시 삭제된 ADR-023 복원.
  - `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
    (git mv) + 내용 정정 (Step B 좁은 가이드로 재포지셔닝, KRMOIS → MOIS).
  - `docs/provider-contract.md` — canonical name list + dataset_key 표
    (`mois_license_features_bulk/_history/_closed/detail` 4종) + 카탈로그 표.
  - `docs/dagster-boundary.md` — asset 이름 (`feature_place_mois_licenses`) +
    cron 표 (MOIS bulk + incremental 분리).
  - `docs/architecture.md`, `docs/backend-package.md`, `docs/data-model.md`,
    `docs/feature-files-rustfs.md`, `docs/feature-opening-hours.md`,
    `docs/address-geocoding.md`, `docs/debug-fixture-workflow.md`,
    `docs/khoa-beach-info-etl.md`, `docs/test-strategy.md`,
    `docs/windows-reinstall-recovery.md` — `krmois`/`KRMOIS` → `mois`/`MOIS`
    targeted 갱신.
  - `README.md` — 의존 스택 표, 문서 지도 (`mois-feature-etl.md` + `-license-`
    두 항목 별도 링크).
  - `AGENTS.md` — dev 데이터 경로 `KRMOIS localdata zip` → `MOIS`.
  - `pyproject.toml` — provider extras 주석 `python-krmois-api` → `python-mois-api`.
  - `docs/resume.md`, `docs/tasks.md` — 진척도/완료 항목 갱신.

**결정** (ADR-024):
- 외부 라이브러리 실제 이름 검증: PyPI `python-mois-api`, import `mois`,
  GitHub `digitie/python-mois-api`. `python-krmois-api`는 v1 내부 alias였을 뿐
  실제 라이브러리에는 존재하지 않음.
- canonical provider name을 `python-mois-api`로 정정.
- legacy aliases (`krmois`, `mois`, `pykrmois`, `python-krmois-api`)는
  `LEGACY_PROVIDER_ALIASES`에 추가 — v1 호환.
- import 경로 `krtour.map.providers.mois`, loader `krtour.map.mois`, dataset_key
  prefix `mois_*`.

**의사결정 (사용자 위임 사항, 검토 부탁)**:
- **PROMOTED slug 42종** — 식음 6 + 숙박 8 + 관광/문화 9 + 테마파크 5 + MICE 2
  + 스포츠/레저 9 + 쇼핑/도시여가 3. 보수적으로 선정 (TripMate 1차 범위).
- **dataset_key 4분리** — bulk + history + closed + detail. Step별 분리로
  Dagster asset 매핑 명확.
- **mois-license-feature-etl.md 유지** — Step B 좁은 가이드로 재포지셔닝.
  `mois-feature-etl.md`가 full lifecycle (상위 doc). 둘이 충돌하면 full이
  정답이라고 mois-feature-etl.md §1에 명시.
- **legacy alias `python-krmois-api`도 통과** — 본 라이브러리 적재된 기존 feature의
  `provider` 컬럼 마이그레이션은 별도 작업으로 분리.
- **org 이름**: `KRMOIS` → `MOIS`로 일괄. 라이브러리 import 이름과 일치.

**발견**:
- `mois-api` README/AGENTS는 PyPI distribution을 `python-mois-api`라고 명시.
- mois-api 195 업종 카탈로그가 `OPENAPI_SERVICES`/`FILE_DOWNLOADS`/
  `INCREMENTAL_OPENAPI_ENDPOINTS`/`RESPONSE_FIELDS` 정적 dict로 박혀있어
  본 라이브러리에서 그대로 import 가능.
- mois-api의 `mois.db` 모듈이 SQLite/SpatiaLite source DB 적재 + 영업중/폐업
  iterator를 완비 → 본 라이브러리는 reconcile만.

**다음**: PR#3 push + 사용자 검토. PR#1/2/3 모두 merge 후 backlog T-200/T-201
(Sprint 5 운영 진입 전 batch DAG + consistency_reports).

---

## 2026-05-24 22:00 (claude)

**작업**: T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전. 총 14개 신규 docs.

**변경 파일** (모두 신규):
- `docs/weather-feature-normalization.md` (T-002) — forecast_style + timeline_bucket
  + 표준 metric_key 30종 + provider 매핑 + build_weather_card helper.
- `docs/feature-files-rustfs.md` (T-003) — S3 호환 객체저장소 + FeatureFileSource
  → FeatureFile 흐름 + boto3 backend swap (ADR-015).
- `docs/feature-opening-hours.md` (T-004) — Google Places 호환 DTO + DB tables
  + 24/7 표기 + 자정 넘는 period.
- `docs/kraddr-base-types.md` (T-005a) — `python-kraddr-base` 주소/좌표/CRS 사용
  기준. category는 ADR-023으로 본 저장소 이전 명시.
- `docs/address-geocoding.md` (T-005b) — reverse geocoder callable + AddressMatchReport
  match_level 13종.
- `docs/dagster-boundary.md` (T-007) — 라이브러리 vs TripMate 책임 매트릭스 +
  표준 asset 패턴 + Dagster 없이도 호출 가능 (단위 테스트).
- `docs/postgres-schema.md` (T-008) — 4 schema × 20 table reference 카탈로그 +
  CHECK + FK CASCADE + 보관 정책 SQL + Alembic 가이드.
- `docs/debug-fixture-workflow.md` (T-009) — fixture JSON 스키마 + 민감정보 자동
  마스킹 + payload_hash drift 감지 + provider별 ≥3 케이스.
- `docs/feature-db-initialization.md` (T-010) — schema 부트스트랩 + Alembic +
  KrtourMapSettings + AsyncKrtourMapClient 생성 + healthz.
- `docs/tripmate-integration.md` (T-011) — TripMate가 본 라이브러리 import해서
  쓰는 패턴 + Dagster asset + FastAPI router + Admin + 권한/인증 경계.
- `docs/event-feature-etl.md` (T-006a, VisitKorea 축제)
- `docs/mois-license-feature-etl.md` (T-006b, KRMOIS 인허가)
- `docs/opinet-place-price-etl.md` (T-006c, OpiNet 주유소+유가)
- `docs/khoa-beach-info-etl.md` (T-006d, KHOA 해수욕장)
- `docs/krheritage-feature-etl.md` (T-006e, 국가유산청 place/area/event)
- `docs/outdoor-feature-etl.md` (T-006f, 산림청 outdoor)
- `docs/krex-rest-area-feature-etl.md` (T-006g, 도로공사 휴게소+유가+기상)
- `docs/standard-data-feature-etl.md` (T-006h, data.go.kr 표준데이터 5종)
- `docs/notice-feature-etl.md` (T-006i, 4 provider 통합 notice)
- `docs/kma-weather-etl.md` (T-006j, KMA 4종 weather endpoint)
- `docs/place-phone-enrichment.md` (T-006k, Kakao/Naver/Google 전화번호 보강)
- `README.md` — 새 docs 14개 링크 추가.

**결정**: 14개 docs는 v1 패턴을 v2 기준 (krtour.map namespace, async-only, 함수
라이브러리, FastAPI 없음, kraddr-base category 이전)으로 일관 재작성. v1
원문 식별자(`*_DATASET_KEY`, `*_full_scan_job_spec`, `load_*`)는 그대로 유지해
TripMate import 변경 비용 최소화.

**발견**:
- 모든 provider ETL이 같은 패턴: collect → upload → load → sync_state.
  Dagster asset이 동일 5단계 (`docs/dagster-boundary.md` §2).
- v1 산출물은 충실히 검증되어 있고 v2는 namespace + async + 함수 라이브러리
  3 요소만 일관 적용하면 자동으로 정합.
- `notice-feature-etl.md`는 4 provider 통합 단일 doc — provider별 분리 안 함
  (notice_type 정규화가 공통).

**다음**: feature branch `docs/v1-to-v2-feature-ports` push + PR 작성 (PR#1 위
stacked). 사용자 검토 후 squash merge.

---

## 2026-05-24 20:30 (claude)

**작업**: PR-only 룰 추가 + namespace 재명명 (`krtour_map` → `krtour.map`) +
kraddr-base category 모듈 이전 결정 + kraddr-geo 패턴 보강.

**변경 파일**:
- `docs/decisions.md` — ADR-021 (PR-only), ADR-022 (`krtour` namespace),
  ADR-023 (category 이전) 3건 추가.
- `AGENTS.md` — 식별자 표 (Python import → `krtour.map`, category 모듈 출처
  추가), DO NOT #17/#18/#19 추가 (PR-only, flat import 금지, `src/krtour/
  __init__.py` 금지) → 19개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도, DO NOT #19/#20/#21 추가 → 22개 룰.
- `CLAUDE.md` — 5 절대금지를 가장 중요한 5개로 재구성 (PR-only, namespace 1·2위).
- `README.md` — Python import 경로, 디렉토리(`src/krtour/map/` + namespace
  설명), 문서 지도에 `docs/category.md` 추가.
- `pyproject.toml` — `packages.find` (`krtour.map*` + `namespaces=true`),
  `package-data`, `import-linter` root_package + layers + forbidden 계약 갱신,
  coverage source.
- `packages/krtour-map-debug-ui/pyproject.toml` + `README.md` — namespace 정합.
- 일괄 docs 갱신 (rename script): `architecture`, `backend-package`, `decisions`,
  `test-strategy`, `windows-reinstall-recovery`, `dev-environment`, `external-apis`,
  `provider-contract`, `debug-ui-package`, `feature-model`, `resume`, `journal`,
  `CHANGELOG`.
- `docs/category.md` (신규) — `krtour.map.category` 모듈 사양서 11절.
- `docs/agent-guide.md` — §7.5 PR 워크플로 신설 (브랜치 명명, commit format,
  PR 본문 표준 포맷, branch protection, 핸드오프).
- `docs/tasks.md` — Sprint 5 진입 직전 항목 5개 추가 (T-200~T-204: batch DAG,
  consistency_reports, pre-commit hook, CI 워크플로, branch protection 가이드).

**결정**:
- **ADR-021** main 직접 push 금지 — 모든 변경은 feature branch + PR. main에 직접
  들어간 `fc8145f`/`304f2a9`는 ex post facto 인정, 본 ADR 이후 모든 변경은 PR.
- **ADR-022** `krtour` PEP 420 implicit namespace 채택 — `python-krtour-map`은
  `krtour.map`으로 import, `krtour-map-debug-ui`는 `krtour.map_debug_ui`로
  import. 같은 namespace를 share. `src/krtour/__init__.py` 금지.
- **ADR-023** kraddr-base의 category 모듈 (`kraddr.base.categories`, ~2072줄,
  141 enum)을 `krtour.map.category`로 이전. 코드 이전은 코드 작성 단계 진입 시
  별도 PR. 라이선스 호환 (둘 다 GPL-3.0-or-later).

**발견**:
- kraddr-geo ADR-015도 `kraddr` implicit namespace 채택 → 패턴 정합.
- kraddr-geo의 batch DAG + consistency_reports 패턴(ADR-017)이 본 라이브러리의
  Sprint 5 운영에 유용 → T-200/T-201로 백로그 추가.
- 변수 이름 `krtour_map_client`(snake_case)는 변경 안 함 — Python 식별자 명명
  규약과 import path는 별개.

**다음**: feature branch `chore/pr-workflow-namespace-rename-category-migration`
push → PR 작성 (ADR-021 첫 적용 사례). 사용자 리뷰 후 squash merge.

---

## 2026-05-24 19:30 (claude)

**작업**: 디버그 UI를 별도 Python 패키지로 분리 — ADR-020 추가 + 관련 문서/구조
일괄 갱신.

**변경 파일**:
- `docs/decisions.md` — ADR-020 추가. ADR-005 상태에 "위치 부분 superseded" 명시.
- `docs/architecture.md` — 큰 그림 도식에 별도 패키지 블록 추가. `§4 디버그 REST
  API`를 별도 패키지 형태로 재작성. §7 모듈 표에 디버그 패키지 모듈 추가. §8
  ADR-020 추가. §9 v1↔v2 표 갱신.
- `docs/backend-package.md` — 디버그 API 절을 축약하고 `docs/debug-ui-package.md`
  reference로 redirect.
- `docs/debug-ui-package.md` (신규) — 본 패키지 사양서 14절 (정체성/디렉토리/
  의존방향/settings/기동/엔드포인트/응답/OpenAPI/테스트/운영주의/비책임/확장/배포/
  핵심 메시지).
- `AGENTS.md` — 식별자 표 (별도 Python 패키지 명시), TripMate 경계 갱신,
  디버그 API 정책 절 재작성, DO NOT #14 갱신 + #15 신규 (메인 라이브러리 FastAPI
  import 금지) → 총 16개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도 (메인 + 별도 패키지 2 block), DO NOT
  목록에 신규 룰 #15 추가 → 총 19개 룰.
- `CLAUDE.md` — 패키지 분리 1줄 요약 + DO NOT 5개 중 #2/#5 갱신.
- `README.md` — TripMate 연계 문구, 빠른 시작 (디버그 UI 별도 install), 의존
  스택 표 (FastAPI는 별도 패키지로 표시), 디렉토리 (monorepo 2 패키지), 문서 지도.
- `pyproject.toml` — `[api]` extra 제거 (ADR-020 §후속). `import-linter`에 두
  번째 계약 추가 (`krtour_map`에서 fastapi/uvicorn/starlette import 금지).
- `.env.example` — `KRTOUR_MAP_DEBUG_API_*` → `KRTOUR_MAP_DEBUG_UI_*` 갱신 +
  주석.
- `docs/test-strategy.md` — e2e 코드 예시의 `from krtour.map.api.app import ...`
  → `from krtour.map_debug_ui.app import ...`.
- `packages/krtour-map-debug-ui/pyproject.toml` (신규) — 별도 패키지 pyproject.
- `packages/krtour-map-debug-ui/README.md` (신규) — 패키지 README.

**결정**: **ADR-020** — 디버그 UI는 별도 Python 패키지 `krtour-map-debug-ui`로
분리. monorepo 안 `packages/krtour-map-debug-ui/`에 위치. 메인 라이브러리에서
FastAPI/Uvicorn 의존성 제거. ADR-005의 위치 부분(`krtour.map.api`)은 본 ADR로
superseded; 인증 없음 + 내부망 전용 정책은 그대로 유지.

**발견**:
- 메인 라이브러리가 FastAPI 의존을 짊어지면 TripMate에 불필요한 의존성이
  딸려간다. 분리로 install footprint 축소.
- `import-linter`의 `forbidden` 계약으로 메인 패키지의 FastAPI import를 CI에서
  자동 차단 가능.
- v1의 `packages/krtour-map-debug-ui/` 디렉토리 패턴(monorepo Python 서브패키지)
  과 일관됨.

**다음**: 사용자 검토 후 commit + push. T-002(weather-feature-normalization.md
v1→v2 정리)로 복귀.

---

## 2026-05-24 19:00 (claude)

**작업**: v2 설계 단계 진입 — main을 orphan으로 새로 시작하고 핵심 문서 일괄 작성.

**변경 파일**:
- 루트:
  - `AGENTS.md` (지시 우선순위, DO NOT 18개, TripMate 함수 라이브러리 경계, 디버그 API 인증 없음)
  - `README.md` (정체성, 빠른 시작, 의존 스택 표, 문서 지도)
  - `SKILL.md` (DO NOT 18개 + 도메인 어휘 + 자주 묻는 작업)
  - `CLAUDE.md` (1쪽 진입 요약)
  - `LICENSE` (GPL-3.0-or-later)
  - `.gitignore`, `.gitattributes`, `.env.example`
  - `pyproject.toml` (스택 placeholder + ruff/mypy/pytest 설정 + import-linter 계약 박힘)
- `docs/`:
  - `architecture.md` (의존 방향 + 데이터 흐름 + 모듈 표 + v1 대비 변경)
  - `decisions.md` (ADR-001 ~ ADR-019)
  - `data-model.md` (4 schema × 16 table 전체 DDL + 인덱스 + CHECK)
  - `performance.md` (인덱스 설계 + 공간 쿼리 가이드 + bulk + 안티패턴 매트릭스)
  - `test-strategy.md` (4단계 테스트 + Fake repo + EXPLAIN 검증 + Coverage 목표)
  - `backend-package.md` (라이브러리 진입점 + 디버그 REST API + 사용 시나리오)
  - `agent-guide.md` (첫 5분 + ADR 형식 + 변경 분류별 체크리스트)
  - `dev-environment.md` (WSL ext4/NTFS + Docker PostGIS + 초기 셋업)
  - `windows-reinstall-recovery.md` (세션 복구 + PR handoff 노트 포맷)
  - `feature-model.md` (Feature DTO + 5 detail + opening hours + weather/price)
  - `provider-contract.md` (wrapper 금지 + canonical name + dataset_key 표 + 변환 함수 골격)
  - `external-apis.md` (provider별 API 키 발급/호출 + 비용 + 모니터링)
  - `tasks.md`, `resume.md`, `journal.md` (운영 docs 초기)

**결정**:
- ADR-001 ~ ADR-019 19건 박음. 핵심:
  - **ADR-003** TripMate ↔ 라이브러리는 함수 직접 호출 (REST 없음).
  - **ADR-005** 디버그 REST API는 인증 없음, 내부망 전용.
  - **ADR-006** provider adapter/wrapper 신규 생성 금지.
  - **ADR-007** 의존 스택 — kraddr-geo와 동일.
  - **ADR-008** PostGIS는 `x_extension` schema 격리.
  - **ADR-012** 공간 쿼리 1회 변환 + `coord_5179` 컬럼.
  - **ADR-013** bulk insert는 `psycopg.copy_*` 우선 (30k 안전 마진).
  - **ADR-014** 4단계 테스트 + Coverage 목표 (core 90+ / infra 80+ / 전체 80+).
  - **ADR-018** `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기).
  - **ADR-019** KST aware datetime만 허용.
- git: 현재 작업 모두 commit 후 `v1` 브랜치 생성 + origin push, main orphan 재시작
  + force-push origin/main.

**발견**:
- `python-krtour-map-spec.docx` (저장소 루트, 약 80쪽)는 v1 산출물 + SPEC V8 정합 +
  kraddr-geo 디시플린 종합 reference로 유용.
- 사용자가 명시: TripMate 연계는 함수 라이브러리 형태, REST는 디버그 UI + 향후
  내부 활용 (인증 없음). 이를 ADR-003/ADR-005로 박음.
- 사용자 강조: 속도 최적화는 설계 단계부터, 테스트는 촘촘하게.
  → `docs/performance.md` (인덱스 설계 + 안티패턴), `docs/test-strategy.md`
    (4단계 + EXPLAIN 검증)으로 박음.
- kraddr-geo와 동일 스택 (PostgreSQL + PostGIS + SQLAlchemy 2 async + GeoAlchemy2
  + GeoPandas)을 ADR-007로 명시.

**다음**: T-002 — `docs/weather-feature-normalization.md` 작성. v1 docs를
v2 기준으로 정리해 옮긴다.

---

## 2026-05-24 18:00 (claude)

**작업**: v1 작업 보존 — 현재 main의 모든 작업(provider ETL, 디버그 UI,
docs, spec docx)을 `v1` 브랜치로 commit하고 origin/v1로 push.

**변경 파일**: 56 files changed, 2858 insertions(+), 490 deletions(-)
- providers: visitkorea, mois (구 krmois), krheritage, opinet, krex, krforest, khoa,
  datagokr (standard 5 + extras), notices
- DB 스키마, RustFS file 메타, 전화번호 보강
- Debug UI 패키지 (packages/krtour-map-debug-ui)
- Extensive docs 수정
- `python-krtour-map-spec.docx` (AI 에이전트용 사양 80쪽)

**결정**: 사용자 요청 — v1 보존, main 재시작, orphan 히스토리, origin force-push.

**발견**: `~$python-krtour-map-spec.docx` Word lock 파일을 `.gitignore`에 추가.

**다음**: 새 main(orphan) 시작 후 v2 설계 문서 일괄 작성.
