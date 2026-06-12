# krtour-map-admin

`python-krtour-map`의 **디버그 REST API + admin 운영 UI** 별도 Python 패키지.

> **현재 상태 (Sprint 3 완료, Sprint 4 진입 준비)**: health/version, ETL preview,
> `/features` bbox 조회와 frontend 지도 화면이 구현되어 있다.
> Sprint 4부터는 ADR-035에 따라 provider 적재, dedup 검토, 이슈 처리, 오프라인
> 업로드를 포함한 admin 운영 콘솔로 확장한다. 패키지 경계는
> `docs/debug-ui-package.md`, 상세 구현 사양은
> `docs/debug-ui-admin-workflows.md`, OpenAPI/Dagster update queue 계약은
> `docs/openapi-admin-contract.md`를 기준으로 한다.

## 정체성

- **패키지명**: `krtour-map-admin` (PyPI distribution) / `krtour.map_admin` (Python import, ADR-022)
- **위치**: `python-krtour-map` 저장소 내 `packages/krtour-map-admin/`
  (monorepo)
- **목적**: 디버그 UI 백엔드 + admin/유지보수/프로덕션 운영 콘솔
- **인증**: 없음. 내부망 / localhost / WSL / 사내망 전제 (ADR-005)
- **TripMate 의존**: 없음. ADR-045 이후 TripMate는 OpenAPI client로만 연동.
- **운영 형태**: Docker에서 실행되는 krtour-map 독립 프로그램의 API/admin UI.
- **DB/Dagster**: 독립 PostgreSQL/PostGIS DB와 독립 Dagster를 사용.

## 의존성

- `python-krtour-map` (같은 저장소 메인 패키지, monorepo editable install)
- FastAPI + Uvicorn + Pydantic v2 + pydantic-settings

## 설치 / 실행 (라우터 구현 이후)

### Backend (FastAPI)

```bash
# WSL ext4 작업 디렉토리에서
cd ~/dev/python-krtour-map

# 메인 라이브러리 + 디버그 UI 둘 다 editable install
uv pip install -e ".[dev,geo,providers]"
uv pip install -e packages/krtour-map-admin

# 실행 — 인증 없음, localhost 전용
uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 12301 --reload
```

기본 host `127.0.0.1` (외부 노출 금지 default). `0.0.0.0` 바인드 시 경고
로그 (ADR-005 후속).

### Frontend (Next.js + React 19 + maplibre-vworld, ADR-025 2차 보강)

Frontend 서버는 **항상 WSL 셸에서 실행**한다. Windows 호스트는 Playwright e2e
검증 때 Chromium을 실행하는 용도로만 사용한다.

```bash
# WSL ext4 작업 디렉토리에서
cd packages/krtour-map-admin/frontend
which node npm              # /home/.../.nvm/... 등 WSL 경로여야 함 (/mnt/c/... 금지)
cp .env.example .env.local
$EDITOR .env.local           # NEXT_PUBLIC_VWORLD_API_KEY 설정
npm install
npm run dev                  # http://127.0.0.1:12305 (next dev)
```

`node`/`npm`이 `/mnt/c/Program Files/nodejs/...`를 가리키면 Windows Node가 섞인
상태다. WSL nvm Node를 활성화한 뒤 설치/실행한다.

VWorld 지도 (Kakao Maps SDK 미사용). Next.js App Router + `maplibre-gl` +
`maplibre-vworld` + TanStack Query + Zustand + `zod` + React Hook Form +
shadcn/ui + `@krtour/map-marker-react` (ADR-029). 자세한 사양:
`../../docs/debug-ui-package.md` §14.

운영 배포 (옵션 3가지 — `docs/debug-ui-package.md §14.3` 참조):
- **A. standalone (default)**: `npm run build` + `npm run start` → 12305.
- **B. FastAPI reverse proxy**: backend `/ui/*` → Next.js. `next.config.js`
  `basePath: '/ui'` + `output: 'standalone'`.
- **C. static export**: `next build` + `next export` → `out/` static, FastAPI
  mount.

## 환경변수

### Backend (`KRTOUR_MAP_ADMIN_*`)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `KRTOUR_MAP_ADMIN_HOST` | `127.0.0.1` | uvicorn 바인드 host (외부 노출 금지) |
| `KRTOUR_MAP_ADMIN_PORT` | `12301` | uvicorn 포트 |
| `KRTOUR_MAP_ADMIN_RELOAD` | `false` | dev 모드 hot-reload |
| `KRTOUR_MAP_ADMIN_CORS_ALLOW_ORIGINS` | `http://localhost:12305` | Next.js dev 서버 |
| `KRTOUR_MAP_ADMIN_FEATURES_ROUTES_ENABLED` | `true` | `/features/*` 조회 라우터 활성화 |
| `KRTOUR_MAP_ADMIN_ADMIN_ROUTES_ENABLED` | unset | `/admin/*` 운영 라우터 활성화. unset이면 features flag를 따름 |
| `KRTOUR_MAP_ADMIN_OPS_ROUTES_ENABLED` | unset | `/ops/*`, `/ops/dagster/*` 라우터 활성화. unset이면 features flag를 따름 |
| `KRTOUR_MAP_ADMIN_DAGSTER_ALLOWED_HOSTS` | `["127.0.0.1","localhost","::1","dagster"]` | Dagster GraphQL 호출 host allowlist. `KRTOUR_MAP_ADMIN_DAGSTER_URL`/override host가 이 목록에 있어야 함 |
| `KRTOUR_MAP_ADMIN_DAGSTER_REPOSITORY_NAME` | `__repository__` | offline upload load GraphQL launch selector의 repositoryName |
| `KRTOUR_MAP_ADMIN_DAGSTER_REPOSITORY_LOCATION_NAME` | `krtour.map_dagster.definitions` | offline upload load GraphQL launch selector의 repositoryLocationName |
| `KRTOUR_MAP_ADMIN_BACKUP_ROOT` | `data/backups` | `/admin/backups`가 조회하는 backup artifact root |
| `KRTOUR_MAP_ADMIN_BACKUP_PROJECT_ROOT` | `.` | backup/restore script 상대 경로를 해석하고 command를 실행할 project root |
| `KRTOUR_MAP_ADMIN_BACKUP_SCRIPT_PATH` | `scripts/docker-backup.sh` | backup command plan이 호출하는 script path |
| `KRTOUR_MAP_ADMIN_RESTORE_SCRIPT_PATH` | `scripts/docker-restore.sh` | restore command plan이 호출하는 script path |
| `KRTOUR_MAP_ADMIN_BACKUP_COMMAND_ENABLED` | `false` | `POST /admin/backups`, `POST /admin/restore/{backup_id}`의 host command 실행 허용 여부. false면 plan-only |
| `KRTOUR_MAP_ADMIN_BACKUP_COMMAND_TIMEOUT_SECONDS` | `1800` | opt-in host command 실행 timeout |
| `KRTOUR_MAP_ADMIN_RESTORE_APP_DB` | `krtour_map_restore` | staging restore app DB 기본값 |
| `KRTOUR_MAP_ADMIN_RESTORE_DAGSTER_DB` | `krtour_map_dagster_restore` | staging restore Dagster DB 기본값 |
| `KRTOUR_MAP_ADMIN_RESTORE_RUSTFS_VOLUME` | `krtour-map-rustfs-restore` | staging restore RustFS volume 기본값 |
| `KRTOUR_MAP_ADMIN_FRONTEND_DIST` | (auto) | static export 모드 시 `frontend/out/` 경로 |
| `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE` | `require_review` | place/event feature 추가·수정·삭제 요청 처리 모드. `require_review` 또는 `immediate` |

### Frontend (`NEXT_PUBLIC_*` — Next.js 규약)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | (필수) | VWorld API key. `KRADDR_GEO_VWORLD_API_KEY` 공유 (ADR-025 보강). |
| `NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API` | 개발 기본 `http://127.0.0.1:12301` | 백엔드 base URL. production에서는 명시 필수 |
| `NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL` | 개발 기본 `http://127.0.0.1:12302` | Dagster UI/embed base URL. production에서는 명시 필수 |

메인 라이브러리 환경변수(`KRTOUR_MAP_PG_DSN`, `KRTOUR_MAP_OBJECT_STORE_*` 등)는
그대로 사용한다. 디버그 UI는 메인 라이브러리의 settings를 상속한다.

## 엔드포인트 (계획)

자세한 패키지 사양은 `../../docs/debug-ui-package.md`, admin 운영 콘솔 구현 사양은
`../../docs/debug-ui-admin-workflows.md`. 요약:

- `/health`, `/version`
- `/features/{id}`, `/features/in-bounds`, `/features/nearby`
- `/admin/features`, `/admin/features/{id}`, `/admin/features/{id}/deactivate`,
  `/admin/features/change-requests`
- `/admin/providers`, `/admin/providers/{provider}/datasets/{dataset_key}/runs`
- `/admin/feature-update-requests` (좌표/반경/시군구/provider 기준 업데이트 생성/조회/취소/run-now 재큐잉)
- `/admin/poi-cache-targets`, `/features/nearby/by-target` (외부 POI key 기준 target
  등록/삭제/주변 feature summary 조회)
- `/admin/provider-refresh-policies` (provider별 update 주기/rate limit 정책)
- `/features/{id}/weather`, `/features/{id}/sources`, `/features/{id}/files`
- `/providers/{name}/sync-state`
- `/import-jobs`, `/import-jobs/{job_id}`
- `/dedup-review`, `/integrity-violations`
- `/admin/offline-uploads` (JSON/JSONL/CSV/TSV upload/list/detail/preview/validate/Dagster load), `/ops/error-logs`
- `/debug/explain`, `/debug/fixtures`

모두 인증 없음. 런타임 `OpenAPI` 문서는 `/docs` (Swagger UI), `/openapi.json`.
저장소 산출물은 admin 전체 `packages/krtour-map-admin/openapi.json`과
TripMate/user subset `packages/krtour-map-admin/openapi.user.json`을 함께 관리한다.

## 라이선스

GPL-3.0-or-later (메인 라이브러리와 동일).
