# kor-travel-map-api

`kor-travel-map`의 **REST API + OpenAPI backend** 별도 Python 패키지.

> **현재 상태**: 공개 feature/provider 조회와 admin 기능을 제공하며, Dagster job·provider
> 운영은 `/ops/pipeline/*`와 `/ops/datasets/*` 두 canonical API에 통합되어 있다.
> Dataset preview는 fixture-only이고 provider credential은 Dagster runtime만 소유한다.
> 패키지 경계는
> `docs/architecture/debug-ui-package.md`, 상세 구현 사양은
> `docs/debug-ui-admin-workflows.md`, OpenAPI/Dagster update queue 계약은
> `docs/architecture/openapi-admin-contract.md`를 기준으로 한다.

## 정체성

- **패키지명**: `kor-travel-map-api` (PyPI distribution) / `kortravelmap.api` (Python import)
- **위치**: `kor-travel-map` 저장소 내 `packages/kor-travel-map-api/`
  (monorepo)
- **목적**: PinVi/user-facing REST + debug/admin/ops REST API
- **인증**: 공개 API key/service token + admin frontend proxy actor/shared secret.
  네트워크 경계에서도 reverse proxy SSO/IP allowlist를 적용한다.
- **PinVi 의존**: 없음. ADR-045 이후 PinVi는 OpenAPI client로만 연동.
- **운영 형태**: Docker에서 실행되는 kor-travel-map 독립 프로그램의 API 서버.
- **DB/Dagster**: 독립 PostgreSQL/PostGIS DB와 독립 Dagster를 사용.

## 의존성

- `kor-travel-map` (같은 저장소 메인 패키지, monorepo editable install)
- FastAPI + Uvicorn + Pydantic v2 + pydantic-settings + prometheus-client

## 설치 / 실행 (라우터 구현 이후)

### Backend (FastAPI)

```bash
# WSL ext4 작업 디렉토리에서
cd ~/dev/kor-travel-map

# 메인 라이브러리 + 디버그 UI 둘 다 editable install
uv pip install -e ".[dev,geo,providers]"
uv pip install -e packages/kor-travel-map-api

# scoped API env와 root 공유 infra env를 검증한 뒤 전체 local stack 실행
cp .env.example .env
cp packages/kor-travel-map-api/.env.example packages/kor-travel-map-api/.env
npm run admin:stack
```

`admin:stack`은 API를 package cwd에서 실행하고 API/frontend/Dagster별 환경 allowlist를
적용한다. root cwd 직접 `uvicorn`은 scoped env와 인증 검증을 우회하므로 지원하지 않는다.

### Frontend (Next.js + React 19 + maplibre-vworld, ADR-025 2차 보강)

Frontend 서버는 **항상 WSL 셸에서 실행**한다. Windows 호스트는 Playwright e2e
검증 때 Chromium을 실행하는 용도로만 사용한다.

```bash
# 저장소 루트의 Linux/WSL 셸에서
source ~/.nvm/nvm.sh && nvm use 22.23.1
which node npm              # /home/.../.nvm/... 등 Linux 경로여야 함 (/mnt/c/... 금지)
npx --yes npm@12.0.1 ci --workspaces --include=optional
npx --yes npm@12.0.1 run verify:npm-tree
cp packages/kor-travel-map-admin/frontend/.env.example \
  packages/kor-travel-map-admin/frontend/.env.local
$EDITOR packages/kor-travel-map-admin/frontend/.env.local
npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run dev
```

`node`/`npm`이 `/mnt/c/Program Files/nodejs/...`를 가리키면 Windows Node가 섞인
상태다. WSL nvm Node를 활성화한 뒤 설치/실행한다.

VWorld 지도 (Kakao Maps SDK 미사용). Next.js App Router + `maplibre-gl` +
`maplibre-vworld` + TanStack Query + Zustand + controlled React state/form validation +
shadcn/ui generated source + `@kor-travel-map/map-marker-react` (ADR-029). 자세한 사양:
`../../docs/architecture/debug-ui-package.md` §14.

운영 배포 (옵션 3가지 — `docs/architecture/debug-ui-package.md §14.3` 참조):
- **A. standalone (default)**: `npm run build` + `npm run start` → 12705.
- **B. FastAPI reverse proxy**: backend `/ui/*` → Next.js. `next.config.js`
  `basePath: '/ui'` + `output: 'standalone'`.
- **C. static export**: `next build` + `next export` → `out/` static, FastAPI
  mount.

## 환경변수

### Backend (`KOR_TRAVEL_MAP_API_*`)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `KOR_TRAVEL_MAP_API_HOST` | `127.0.0.1` | uvicorn 바인드 host (외부 노출 금지) |
| `KOR_TRAVEL_MAP_API_PORT` | `12701` | uvicorn 포트 |
| `KOR_TRAVEL_MAP_API_RELOAD` | `false` | dev 모드 hot-reload |
| `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS` | `http://localhost:12705` | Next.js dev 서버 |
| `KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED` | `true` | `/features/*` 조회 라우터 활성화 |
| `KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED` | unset | `/admin/*` 운영 라우터 활성화. unset이면 features flag를 따름 |
| `KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED` | unset | `/ops/*` 라우터 활성화. unset이면 features flag를 따름 |
| `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED` | `true` | Prometheus pull scrape용 `/metrics` endpoint와 HTTP 요청 count/duration/진행 중 요청/응답 크기, DB query count/duration 계측 활성화 |
| `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_PATH` | `/metrics` | Prometheus exposition path. API 포트 `12701`에서 노출되며 OpenAPI에는 포함하지 않음 |
| `KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS` | `["127.0.0.1","localhost","::1","dagster"]` | Dagster GraphQL 호출 host allowlist. `KOR_TRAVEL_MAP_API_DAGSTER_URL`/override host가 이 목록에 있어야 함 |
| `KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_NAME` | `__repository__` | offline upload load GraphQL launch selector의 repositoryName |
| `KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_LOCATION_NAME` | `kortravelmap.dagster.definitions` | offline upload load GraphQL launch selector의 repositoryLocationName |
| `KOR_TRAVEL_MAP_API_BACKUP_ROOT` | `data/backups` | `/admin/backups`가 조회하는 backup artifact root |
| `KOR_TRAVEL_MAP_API_BACKUP_PROJECT_ROOT` | `.` | backup/restore script 상대 경로를 해석하고 command를 실행할 project root |
| `KOR_TRAVEL_MAP_API_BACKUP_SCRIPT_PATH` | `scripts/docker-backup.sh` | backup command plan이 호출하는 script path |
| `KOR_TRAVEL_MAP_API_RESTORE_SCRIPT_PATH` | `scripts/docker-restore.sh` | restore command plan이 호출하는 script path |
| `KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED` | `false` | `POST /admin/backups`, `POST /admin/restore/{backup_id}`의 host command 실행 허용 여부. false면 plan-only |
| `KOR_TRAVEL_MAP_API_BACKUP_COMMAND_TIMEOUT_SECONDS` | `1800` | opt-in host command 실행 timeout |
| `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` | (운영 필수, root `.env`) | API와 frontend가 함께 읽는 admin REST BFF 검증·ops-live 60초 ticket HMAC server-only secret(32자 이상). API package `.env`에는 두지 않음 |
| `KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED` | `false` | `true`면 API 시작 시 non-empty read/cancel/fixture token 3종을 필수로 요구한다. n150 production은 `true`, 로컬 opt-out만 `false` |
| `KOR_TRAVEL_MAP_API_OPS_READ_TOKEN` | (선택, API package `.env`) | PinVi server의 canonical datasets/pipeline `GET` 전용 token. 로컬 `required=false`에서는 3종을 모두 비워야 비활성이다. 활성화 시 cancel/fixture token과 함께 모든 공백을 금지한 32자 이상이며 admin BFF/service token과도 서로 달라야 한다 |
| `KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN` | (선택, API package `.env`) | `POST /v1/ops/pipeline/executions/import_job/{id}/cancel` 한 곳 전용 token. local `required=false` opt-out 외에는 read/fixture token과 함께 non-empty 3종을 요구하며 schedule/policy/request 등 다른 mutation은 항상 거부 |
| `KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN` | (선택, API package `.env`) | Docker Manager만 쓰는 `ops:fixture` token. exact C6c contract-fixture route와 finalize만 허용하며 PinVi, Admin BFF, read/cancel token은 사용할 수 없다 |
| `KOR_TRAVEL_MAP_API_RESTORE_APP_DB` | `kor_travel_map_restore` | staging restore app DB 기본값 |
| `KOR_TRAVEL_MAP_API_RESTORE_DAGSTER_DB` | `kor_travel_map_dagster_restore` | staging restore Dagster DB 기본값 |
| `KOR_TRAVEL_MAP_API_RESTORE_RUSTFS_VOLUME` | `kor-travel-map-rustfs-restore` | staging restore RustFS volume 기본값 |
| `KOR_TRAVEL_MAP_API_FRONTEND_DIST` | (auto) | static export 모드 시 `frontend/out/` 경로 |
| `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE` | `require_review` | place/event feature 추가·수정·삭제 요청 처리 모드. `require_review` 또는 `immediate` |

Ops service principal의 감사 actor는 코드 상수 `service:pinvi`다. actor 설정 env는 없으며,
제거된 `KOR_TRAVEL_MAP_API_OPS_ACTOR`가 존재하면 API가 시작을 거부한다.

### Frontend (`NEXT_PUBLIC_*` — Next.js 규약)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | (필수) | VWorld API key. `KOR_TRAVEL_GEO_VWORLD_API_KEY` 공유 (ADR-025 보강). |
| `NEXT_PUBLIC_KOR_TRAVEL_MAP_API` | 개발 기본 `http://127.0.0.1:12701` | 백엔드 base URL. production에서는 명시 필수 |
| `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` | 개발 기본 `http://127.0.0.1:12702` | Dagster UI/embed base URL. production에서는 명시 필수 |
| `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` | 개발 기본 `http://127.0.0.1:12501` | 수동 feature 작성 화면의 kor-travel-geo v2 geocode/reverse base URL. production에서는 명시 필수 |
| `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY` | `NEXT_PUBLIC_VWORLD_API_KEY`와 동일 값 | kor-travel-geo v2 `key` query 값. production에서는 명시 필수 |

메인 라이브러리 환경변수(`KOR_TRAVEL_MAP_PG_DSN`, `KOR_TRAVEL_MAP_OBJECT_STORE_*` 등)는
그대로 사용한다. API 패키지는 메인 라이브러리의 settings를 함께 사용한다.

## 주요 엔드포인트

자세한 패키지 사양은 `../../docs/architecture/debug-ui-package.md`, admin 운영 콘솔 구현 사양은
`../../docs/debug-ui-admin-workflows.md`. 요약:

- `/health`, `/version`
- `/v1/features/{id}`, `/v1/features/in-bounds`, `/v1/features/nearby`
- `/v1/admin/features`, `/v1/admin/features/{id}`, `/v1/admin/features/{id}/state`,
  `/v1/admin/features/{id}/state/reactivate`,
  `/v1/admin/features/{id}/state/transitions`, `/v1/admin/features/change-requests`
- `/v1/admin/poi-cache-targets`, `/v1/features/nearby/by-target` (외부 POI key 기준 target
  등록/삭제/주변 feature summary 조회)
- `/v1/features/{id}/weather`, `/v1/features/{id}/sources`, `/v1/features/{id}/files`
- `/v1/providers`, `/v1/providers/{provider}/last-sync` (공개 provider 신선도)
- `/v1/ops/datasets`, `/v1/ops/datasets/detail?provider=...&dataset_key=...&sync_scope=...`
  (상태·정책·fixture preview)
- `/v1/ops/pipeline/overview`, `/v1/ops/pipeline/executions`, `/v1/ops/pipeline/requests`
  (실행·event·Dagster·schedule 통합)
- `/v1/admin/features/dedup-reviews`, `/v1/ops/consistency/issues`,
  `/v1/ops/system-logs`
- `/v1/admin/offline-uploads` (JSON/JSONL/CSV/TSV upload/list/detail/preview/validate/Dagster load)

`/v1/admin/*`와 canonical `/v1/ops/pipeline/*`·`/v1/ops/datasets/*`는 admin frontend
proxy 인증 context를 요구한다. 예외적으로 별도 service principal은 canonical read와 exact
import-job cancel 한 곳만 호출한다. health·metrics·live·운영 로그·정합성 같은 관측용 ops read는
별도 인프라 접근 제어 경계에서 제공한다. 런타임
`OpenAPI` 문서는 `/docs` (Swagger UI), `/openapi.json`.
저장소 산출물은 admin 전체 `packages/kor-travel-map-api/openapi.json`과
공개 사용자 subset `packages/kor-travel-map-api/openapi.user.json`, 서버 간
`ServiceToken` subset `packages/kor-travel-map-api/openapi.service.json`을 함께 관리한다.

## Prometheus

`GET /metrics`는 Prometheus exposition format으로 REST API 전체의 HTTP 요청 수,
지연 시간 histogram, 진행 중 요청 수, 응답 크기 histogram, 예외 수, DB query 수와
query 지연 시간 histogram, 프로세스/런타임 기본 메트릭을 반환한다. HTTP 메트릭은
`method`, route template `path`, `status_code`, `surface` label을 가진다. `surface`는
`public`(`/v1/features`, `/v1/categories`, `/v1/providers`, `/v1/public`,
`/v1/curated-features`), `admin`, `ops`, `debug`, `system`, `other`로 구분한다.

`kor-travel-docker-manager` 관측 스택 기준 포트는 Grafana `12205`, cAdvisor Exporter
`12301`, Prometheus `12401`다. Prometheus가 `kor-travel-map` API 포트 `12701`의
`/metrics`를 pull scrape하는 구조이며, 앱이 Prometheus로 외부 방향 연결을 만들지는 않는다.

## 라이선스

GPL-3.0-or-later (메인 라이브러리와 동일).
