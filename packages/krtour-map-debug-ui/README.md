# krtour-map-debug-ui

`python-krtour-map`의 **디버그 REST API + UI** 별도 Python 패키지.

> **현재 상태 (v2 설계 단계)**: 본 패키지는 ADR-020에 따라 메인 라이브러리에서
> 분리되어 신설되었다. 본 디렉토리는 패키지 구조의 placeholder이며, 코드는
> 별도 요청이 있을 때까지 작성하지 않는다. 설계는 `docs/debug-ui-package.md`에
> 박혀 있다.

## 정체성

- **패키지명**: `krtour-map-debug-ui` (PyPI distribution) / `krtour.map_debug_ui` (Python import, ADR-022)
- **위치**: `python-krtour-map` 저장소 내 `packages/krtour-map-debug-ui/`
  (monorepo)
- **목적**: 디버그 UI 백엔드 + 향후 내부 도구 활용
- **인증**: 없음. 내부망 / localhost / WSL / 사내망 전제 (ADR-005)
- **TripMate 의존**: 없음. TripMate는 메인 라이브러리만 import.

## 의존성

- `python-krtour-map` (같은 저장소 메인 패키지, monorepo editable install)
- FastAPI + Uvicorn + Pydantic v2 + pydantic-settings

## 설치 / 실행 (코드 작성 단계 이후)

### Backend (FastAPI)

```bash
# WSL ext4 작업 디렉토리에서
cd ~/dev/python-krtour-map

# 메인 라이브러리 + 디버그 UI 둘 다 editable install
uv pip install -e ".[dev,geo,providers]"
uv pip install -e packages/krtour-map-debug-ui

# 실행 — 인증 없음, localhost 전용
uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8600 --reload
```

기본 host `127.0.0.1` (외부 노출 금지 default). `0.0.0.0` 바인드 시 경고
로그 (ADR-005 후속).

### Frontend (Next.js + React 19 + maplibre-vworld, ADR-025 2차 보강)

```bash
cd packages/krtour-map-debug-ui/frontend
cp .env.example .env.local
$EDITOR .env.local           # NEXT_PUBLIC_VWORLD_API_KEY 설정
npm ci
npm run dev                  # http://127.0.0.1:8610 (next dev)
```

VWorld 지도 (Kakao Maps SDK 미사용). Next.js App Router + `maplibre-gl` +
`maplibre-vworld` + `zod` + `@krtour/map-marker-react` (ADR-029). 자세한
사양: `../../docs/debug-ui-package.md` §14.

운영 배포 (옵션 3가지 — `docs/debug-ui-package.md §14.3` 참조):
- **A. standalone (default)**: `npm run build` + `npm run start` → 8610.
- **B. FastAPI reverse proxy**: backend `/ui/*` → Next.js. `next.config.js`
  `basePath: '/ui'` + `output: 'standalone'`.
- **C. static export**: `next build` + `next export` → `out/` static, FastAPI
  mount.

## 환경변수

### Backend (`KRTOUR_MAP_DEBUG_UI_*`)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `KRTOUR_MAP_DEBUG_UI_HOST` | `127.0.0.1` | uvicorn 바인드 host (외부 노출 금지) |
| `KRTOUR_MAP_DEBUG_UI_PORT` | `8600` | uvicorn 포트 |
| `KRTOUR_MAP_DEBUG_UI_RELOAD` | `false` | dev 모드 hot-reload |
| `KRTOUR_MAP_DEBUG_UI_CORS_ALLOW_ORIGINS` | `http://localhost:8610` | Next.js dev 서버 |
| `KRTOUR_MAP_DEBUG_UI_FRONTEND_DIST` | (auto) | static export 모드 시 `frontend/out/` 경로 |

### Frontend (`NEXT_PUBLIC_*` — Next.js 규약)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | (필수) | VWorld API key. `KRADDR_GEO_VWORLD_API_KEY` 공유 (ADR-025 보강). |
| `NEXT_PUBLIC_KRTOUR_MAP_DEBUG_UI_API` | `http://127.0.0.1:8600` | 백엔드 base URL |

메인 라이브러리 환경변수(`KRTOUR_MAP_PG_DSN`, `KRTOUR_MAP_OBJECT_STORE_*` 등)는
그대로 사용한다. 디버그 UI는 메인 라이브러리의 settings를 상속한다.

## 엔드포인트 (계획)

자세한 사양은 `../../docs/debug-ui-package.md`. 요약:

- `/health`, `/version`
- `/features/{id}`, `/features/in-bounds`, `/features/nearby`
- `/features/{id}/weather`, `/features/{id}/sources`, `/features/{id}/files`
- `/providers/{name}/sync-state`
- `/import-jobs`, `/import-jobs/{job_id}`
- `/dedup-review`, `/integrity-violations`
- `/debug/explain`, `/debug/fixtures`

모두 인증 없음. `OpenAPI` 문서는 `/docs` (Swagger UI), `/openapi.json`.

## 라이선스

GPL-3.0-or-later (메인 라이브러리와 동일).
