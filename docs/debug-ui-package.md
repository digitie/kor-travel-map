# debug-ui-package.md — `krtour-map-debug-ui` 사양

본 문서는 `python-krtour-map` 저장소 내 별도 Python 패키지
`krtour-map-debug-ui`의 사양 reference다. 결정 근거는 `docs/decisions.md`의
ADR-005(인증 없음, 내부망 전용) + ADR-020(별도 패키지 분리).

## 1. 정체성

| 항목 | 값 |
|------|----|
| 패키지명 (PyPI 형식) | `krtour-map-debug-ui` |
| Python import | `from krtour.map_debug_ui import ...` |
| 위치 | `packages/krtour-map-debug-ui/` (monorepo) |
| 별도 `pyproject.toml` | 예 |
| 의존성 | `python-krtour-map`, FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| 인증 | **없음** (ADR-005, 내부망 전제) |
| TripMate 의존 | **없음** — TripMate는 메인 라이브러리만 import |
| Release | 메인 라이브러리와 동일 version 동기 (monorepo lockstep) |

## 2. 패키지 디렉토리 (계획)

```
packages/krtour-map-debug-ui/
├── pyproject.toml
├── README.md
├── src/krtour/map_debug_ui/
│   ├── __init__.py
│   ├── py.typed
│   ├── app.py           — FastAPI app factory + uvicorn entrypoint
│   ├── settings.py      — KRTOUR_MAP_DEBUG_UI_* + 메인 settings 상속
│   ├── deps.py          — AsyncKrtourMapClient + Engine 주입 (FastAPI Depends)
│   ├── cli.py           — uvicorn launcher (optional)
│   ├── responses.py     — 공통 응답 래핑 (data/meta/error) + 에러 코드 매핑
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── features.py        — GET /features/...
│   │   ├── weather.py
│   │   ├── sources.py
│   │   ├── files.py
│   │   ├── providers.py       — sync-state
│   │   ├── import_jobs.py
│   │   ├── dedup_review.py
│   │   ├── integrity.py
│   │   ├── debug.py           — /debug/explain, /debug/fixtures
│   │   └── fixtures.py        — /debug/fixtures (저장/replay)
│   └── static/                — Next.js static export 산출물 mount 시 (옵션 C, frontend/out/ 복사)
├── frontend/                  — Next.js 15 + React 19 + TS + maplibre-vworld (ADR-025 2차 보강)
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── .env.example           — NEXT_PUBLIC_VWORLD_API_KEY, NEXT_PUBLIC_KRTOUR_MAP_DEBUG_UI_API
│   └── src/
│       ├── app/                     — Next.js App Router
│       │   ├── layout.tsx
│       │   ├── page.tsx             — / (FeatureMap)
│       │   ├── features/[id]/page.tsx
│       │   ├── import-jobs/page.tsx
│       │   ├── dedup-review/page.tsx
│       │   ├── integrity/page.tsx
│       │   └── debug/
│       │       ├── explain/page.tsx — SQL EXPLAIN viewer
│       │       └── fixtures/page.tsx
│       ├── api/               — openapi-typescript 생성 + 수동 zod mirror
│       ├── components/
│       │   ├── VWorldMap.tsx        — maplibre-vworld 래핑
│       │   ├── FeatureMakiMarker.tsx — @krtour/map-marker-react 사용 (ADR-029)
│       │   └── ProviderSyncBadge.tsx
│       └── lib/
│           └── queryClient.ts       — @tanstack/react-query setup
│           # (categoryMaki / markerColor는 @krtour/map-marker-react에서 import — ADR-029)
└── tests/
    ├── unit/                  — Fake repo + httpx ASGITransport
    ├── e2e/                   — testcontainers PostGIS + 실제 메인 라이브러리
    └── conftest.py
```

## 3. 의존 방향

```
krtour.map_debug_ui.app
   ↓
krtour.map_debug_ui.routers.*
   ↓
krtour.map_debug_ui.deps   ──→   krtour.map.client (AsyncKrtourMapClient)
                                       ↓
                              메인 패키지 (dto/core/infra/providers)
```

- 본 패키지는 `krtour.map.client`만 import한다.
- `krtour.map.infra`, `krtour.map.providers` 직접 import 금지 — 본 패키지의
  존재 이유는 디버깅 UI이지 비즈니스 로직 우회가 아니다.
- 본 패키지는 자체 settings 외에 메인 라이브러리의 `KrtourMapSettings`를
  상속/병합한다.

## 4. settings

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class DebugUiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRTOUR_MAP_DEBUG_UI_", env_file=".env")

    host: str = "127.0.0.1"                   # 외부 노출 금지 default (ADR-005)
    port: int = 8600
    reload: bool = False                      # dev 모드 hot-reload
    cors_allow_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
```

메인 라이브러리 settings는 별도 `KrtourMapSettings`를 그대로 import해서 사용한다.
`pg_dsn`, `object_store_*` 같은 항목은 본 패키지에서 재정의하지 않는다.

## 5. 기동

```bash
# 메인 + 디버그 UI 둘 다 editable install
uv pip install -e .
uv pip install -e packages/krtour-map-debug-ui

# 기동 (인증 없음, localhost 전용)
uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8600

# 환경변수로 override
KRTOUR_MAP_DEBUG_UI_HOST=127.0.0.1 \
KRTOUR_MAP_DEBUG_UI_PORT=8600 \
KRTOUR_MAP_PG_DSN=postgresql+asyncpg://... \
uvicorn krtour.map_debug_ui.app:app

# 또는 CLI (옵션)
krtour-map-debug-ui run --host 127.0.0.1 --port 8600
```

`0.0.0.0` 바인드 시 경고 로그 (ADR-005 후속). 코드 작성 단계에서
`warn_if_external_bind(host)` helper를 박는다.

## 6. 엔드포인트

모두 인증 없음. `OpenAPI` 자동 노출 — `/docs` (Swagger UI), `/openapi.json`.

| Path | 메서드 | 설명 |
|------|--------|------|
| `/health` | GET | engine ping + 객체 저장소 ping (옵션) |
| `/version` | GET | 메인 라이브러리 + 디버그 패키지 version + git sha |
| `/features` | GET | 검색 + 필터 + paging (admin용) |
| `/features/{feature_id}` | GET | full detail + sources + files |
| `/features/in-bounds` | GET | bbox 검색 + zoom 클러스터링 |
| `/features/nearby` | GET | 반경 검색 (`lon, lat, radius_m`) |
| `/features/{feature_id}/weather` | GET | `WeatherCard` |
| `/features/{feature_id}/sources` | GET | source_links |
| `/features/{feature_id}/files` | GET | feature_files |
| `/providers/{name}/sync-state` | GET | `ProviderSyncState` |
| `/import-jobs` | GET, POST | 작업 큐 조회/등록 |
| `/import-jobs/{job_id}` | GET, PATCH | 상태 변경 |
| `/dedup-review` | GET | pending 큐 |
| `/dedup-review/{review_key}` | PATCH | accept/reject/merged |
| `/integrity-violations` | GET | `data_integrity_violations` |
| `/debug/explain` | POST | body에 SQL (allowlist 적용) → EXPLAIN (FORMAT JSON, ANALYZE) |
| `/debug/fixtures` | GET, POST | fixture 저장/replay 메타 |

### 6.1 SQL EXPLAIN 안전 가드

`/debug/explain`은 SELECT/WITH/EXPLAIN으로 시작하는 쿼리만 허용. INSERT/UPDATE/
DELETE/DDL은 거부. `READ ONLY` transaction에서 실행.

## 7. 응답 셰입

성공:
```json
{ "data": ..., "meta": {"count": 50, "duration_ms": 23} }
```

에러:
```json
{ "error": {"code": "VALIDATION_ERROR", "message": "...", "details": {...}} }
```

에러 코드는 메인 라이브러리 `core.exceptions`의 예외를 매핑:

| 예외 | HTTP | code |
|------|------|------|
| `ValidationError` | 422 | `VALIDATION_ERROR` |
| `FeatureNotFoundError` | 404 | `FEATURE_NOT_FOUND` |
| `SourceRecordNotFoundError` | 404 | `SOURCE_RECORD_NOT_FOUND` |
| `DuplicateFeatureError` | 409 | `DUPLICATE_FEATURE` |
| `ImportJobConflictError` | 409 | `JOB_CONFLICT` |
| `ProviderError` | 502 | `PROVIDER_ERROR` |
| `FileStoreError` | 502 | `FILE_STORE_ERROR` |
| 기타 | 500 | `INTERNAL_ERROR` |

## 8. OpenAPI export

```bash
# packages/krtour-map-debug-ui/scripts/export_openapi.py
python packages/krtour-map-debug-ui/scripts/export_openapi.py \
    --output packages/krtour-map-debug-ui/openapi.json

# CI drift 검증
python packages/krtour-map-debug-ui/scripts/export_openapi.py \
    --check --output packages/krtour-map-debug-ui/openapi.json
```

`.github/workflows/openapi.yml`에 본 패키지용 step 추가. DTO/라우터 변경 시
`openapi.json` 갱신 강제. 정식 결정은 **ADR-031** (proposed) — 첫 FastAPI
라우터 등장 PR부터 즉시 활성화 (frontend 도입 전부터 drift gate 가동 →
type drift 부채 0).

향후 Next.js bridge를 두는 경우 `npm run gen:types`에 본 openapi.json을
입력으로.

## 9. 테스트

- **unit** (`tests/unit/`): Fake repo (메인 라이브러리의 Fake repo 재사용) +
  `httpx.AsyncClient(ASGITransport)`. DB 없이 라우터 응답 셰입 검증.
- **e2e** (`tests/e2e/`): testcontainers PostGIS + 실제 메인 라이브러리 wiring.
  EXPLAIN 통합 테스트는 메인 라이브러리 책임이지만, 라우터 통합 path도 검증.
- 인증 없음 동작 회귀 테스트 (Authorization 헤더 무시 확인).
- `0.0.0.0` 바인드 경고 로그 회귀 테스트.

자세한 매트릭스는 `docs/test-strategy.md`.

## 10. 운영 시 주의 사항

- **외부 노출 금지**. host default `127.0.0.1`. `0.0.0.0` 바인드 시 경고.
- **방화벽**: Odroid 운영 노드에서 외부 포트 차단. `ufw allow from 192.168.0.0/16
  to any port 8600` 같은 사내망 한정 허용만.
- **Cloudflare Tunnel** 또는 **Tailscale**로 원격 접근 시에도 인증은 네트워크
  계층에서.
- **로그**: structlog JSON to stdout. 메인 라이브러리와 동일 키 표준
  (`provider`, `dataset_key`, `request_id`, `feature_id`).
- **PII 노출**: provider raw payload, location 데이터가 응답에 그대로 노출되므로
  운영자만 접근 가능한 환경에서만 사용.

## 11. 비책임

본 패키지는 다음을 하지 않는다:

- 사용자 가시 UI (사용자 대상 지도/POI 보기 등 — TripMate)
- 인증/세션/권한 (네트워크 계층 책임)
- SQL write/DDL (`/debug/explain`은 read-only)
- 백업/복구/DR (운영자 책임)
- TripMate Admin UI 페이지 — TripMate가 별도 구현

## 12. 향후 확장 (보류)

- **별도 frontend (Next.js)**: 본 디렉토리에서 운영하거나 별도 패키지
  (`krtour-map-debug-ui-frontend`?) 분리. v2 1차 범위 외 (T-100).
- **WebSocket 실시간 디버그**: 큰 적재 job 진행률 streaming.
- **EXPLAIN ANALYZE 결과 timeline 시각화**: pg_stat_statements 연동.

## 13. 외부 배포

- 본 패키지를 PyPI에 별도 배포하지 않을 가능성이 높다 (내부망 전용 도구).
- TripMate 운영 노드에서는 git checkout → editable install로 충분.
- PyPI 배포가 필요해지면 메인 라이브러리와 동일 version으로 lockstep release.

## 14. Frontend — `maplibre-vworld-js` on Next.js (ADR-025, 2차 보강)

### 14.1 기술 스택

| 항목 | 값 |
|------|----|
| Framework | **Next.js 15 (App Router)** — `kraddr-geo-ui` / TripMate `apps/web`와 동일 stack (ADR-025 2차 보강 2026-05-25) |
| 라이브러리 | `maplibre-vworld` **v0.1.0** (`github:digitie/maplibre-vworld-js#v0.1.0` — npm 미게시, git URL+tag 핀, ADR-043 패턴) |
| 의존 | `maplibre-gl` ^5.24.0 (BSD-3), `zod` ^4.4.3 (좌표 검증, v0.1.0 peer), React 19, `@tanstack/react-query` |
| 공통 마커 | `@krtour/map-marker-react` (workspace, ADR-029) |
| 언어 | TypeScript |
| 라이선스 | MIT (`next`) + ISC (`maplibre-vworld`) + BSD-3 (`maplibre-gl`) + GPL-3.0 (본 저장소) — 호환 |
| 디렉토리 | `packages/krtour-map-debug-ui/frontend/` |
| 개발 포트 | `8610` (`next dev --port 8610`, TripMate `apps/web` dev 3000 충돌 회피) |

**Kakao Maps SDK 사용 안 함** (ADR-025/026). VWorld 지도가 1차 + 유일.

### 14.2 환경변수

| 변수 | 의미 |
|------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | VWorld API key. **`KRADDR_GEO_VWORLD_API_KEY`와 동일 값 공유** (ADR-025 사용자 보강 1차 + 2차 2026-05-25). frontend 빌드/런타임 주입. |
| `NEXT_PUBLIC_KRTOUR_MAP_DEBUG_UI_API` | 백엔드 API base URL (개발: `http://127.0.0.1:8600`) |
| `KRTOUR_MAP_DEBUG_UI_FRONTEND_DIST` | (FastAPI 측) Next.js build 산출물 경로 — static export 모드 시에만 사용 (`.next/` 또는 `out/`) |

**VWorld API key 공유 정책 (확정, ADR-025 보강 2026-05-25)**:
`python-kraddr-geo` ADR-019의 `KRADDR_GEO_VWORLD_API_KEY`를 **공유 사용**한다.
별도 발급 / 별도 환경변수 / 디버그 UI 전용 키 금지. 운영 시 backend가 `.env`
또는 vault에서 `KRADDR_GEO_VWORLD_API_KEY`를 읽어, frontend 빌드 시 Next.js
규약상 `NEXT_PUBLIC_VWORLD_API_KEY`로 동일 값을 주입한다 (CI/CD 또는 운영 셸
스크립트 책임). **TripMate 사용자 UI** (ADR-026)도 동일 키를 공유한다. HTTP
referrer 제한은 backend 호스트(`127.0.0.1` + 내부망 호스트) + TripMate frontend
호스트로 통일.

Next.js env 규약: `NEXT_PUBLIC_*` 만 브라우저로 노출. server-only 키는
prefix 없이 박는다 (본 디버그 UI는 read-mostly이라 server-only 키는 없음).

### 14.3 기동 / 운영 옵션

**개발**:
```bash
# 1. 본 라이브러리 install (이미 됨)
cd ~/dev/python-krtour-map
uv pip install -e ".[dev]"
uv pip install -e packages/krtour-map-debug-ui

# 2. backend (FastAPI) 기동
uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8600

# 3. frontend (Next.js dev) 기동
cd packages/krtour-map-debug-ui/frontend
npm ci
cp .env.example .env.local
$EDITOR .env.local           # VWorld API key
npm run dev                  # http://127.0.0.1:8610
```

**운영 옵션 3가지** (운영자 결정):

- **A. standalone (default 권고)**: `next build` + `next start` — frontend는
  8610 포트, backend는 8600 포트로 동일 호스트에서 별도 프로세스. CORS
  미필요 (Next.js rewrites로 same-origin fetch).
  ```bash
  cd packages/krtour-map-debug-ui/frontend
  npm run build                # .next/
  npm run start                # next start --port 8610 --hostname 127.0.0.1
  ```
- **B. FastAPI reverse proxy**: backend의 `/ui/*` 경로가 Next.js로 proxy.
  Next.js는 `basePath: '/ui'` 설정. 단일 포트 운영 (8600).
- **C. static export**: `next build` + `next export` → `out/` HTML/JS.
  FastAPI가 `out/`을 static mount. SSR 미사용 (App Router의 client-only
  페이지만 가능). 본 디버그 UI는 read-mostly이라 가능하지만 server actions
  추가 시 disable됨.

운영자가 옵션을 정한 후 `next.config.js`의 주석 처리된 `output` 설정 활성화.

### 14.4 핵심 컴포넌트 매핑

| 컴포넌트 | 역할 | 본 라이브러리 연계 |
|---------|------|------------------|
| `<VWorldMap>` | MapLibre + VWorld raster/vector tile 기본 지도 | viewport bbox → `/features/in-bounds` API |
| `<MakiMarker>` | feature 1건 마커 | `krtour.map.category` Tier 4 → maki icon 55종 |
| `<MarkerClusterer>` | viewport culling + KDBush | 10만+ feature 동시 표시 (MOIS 인허가 등) |
| `<FeatureMakiMarker>` (custom) | maki + 카테고리 color (P-01~P-16) | category code → maki + 색상 dispatch |
| `<DetailPanel>` | feature 클릭 시 상세 | `GET /features/{id}` |
| `<ProviderSyncBadge>` | provider sync 상태 | `GET /providers/{name}/sync-state` |
| `<DebugExplain>` | SQL EXPLAIN viewer | `POST /debug/explain` (read-only) |

### 14.5 카테고리 → maki icon 매핑

`packages/krtour-map-debug-ui/frontend/src/lib/categoryMaki.ts`:

```typescript
// krtour.map.category와 동기. openapi-typescript로 자동 생성 후 수동 보강.
export const CATEGORY_MAKI: Record<string, string> = {
  "01050100": "beach",        // TOURISM_NATURE_BEACH (KHOA)
  "01070100": "religious-buddhist",   // 전통사찰
  "01070300": "monument",     // 사적·기념물
  "03030101": "park",         // 휴양림 (산림청)
  "06020000": "fuel",         // 주유소 (OpiNet)
  "06040101": "highway-rest-area",    // 휴게소 (KREX)
  // ... (전체 141건은 docs/category.md §4)
};

export const CATEGORY_COLOR: Record<string, string> = {
  // marker_color 필드는 features 테이블에 직접 저장됨 (P-01 ~ P-16)
  // 본 dict는 fallback only
  "01000000": "P-11",         // 관광 fallback (자홍)
  "02000000": "P-01",         // 식음 fallback (빨강)
  "03000000": "P-10",         // 숙박 fallback (보라)
  // ...
};
```

자세한 카테고리 트리는 `docs/category.md` §4.

### 14.6 OpenAPI → TypeScript 동기

```bash
# 백엔드에서 OpenAPI export
python scripts/export_openapi.py --output frontend/openapi.json

# frontend에서 타입 생성
cd packages/krtour-map-debug-ui/frontend
npm run gen:types            # openapi-typescript openapi.json -o src/api/types.ts
```

CI에서 drift 검증 (kraddr-geo ADR-015 패턴 미러). 자세한 절차는 §8 OpenAPI export.

### 14.7 e2e 테스트

- backend는 testcontainers PostGIS (Python 측, §9).
- frontend는 Playwright (e2e) + Vitest (단위) 로 테스트 (코드 작성 단계,
  Next.js 공식 가이드 미러).
- 통합 e2e (frontend + backend + PostGIS)는 Sprint 5 진입 직전 (T-200 계열).

### 14.8 외부 노출 안전

- frontend는 `127.0.0.1:8610` (Next.js dev/standalone) 또는 `127.0.0.1:8600`
  (FastAPI proxy/static mount, §14.3 옵션 B/C) 만.
- VWorld API key는 frontend에 노출되지만 HTTP referrer 제한으로 보호.
  공유 키(`KRADDR_GEO_VWORLD_API_KEY`)이므로 referrer 화이트리스트에 backend
  호스트 + TripMate frontend 호스트(ADR-026) 모두 포함.
- 운영자 외부 접근은 SSH 터널 / Cloudflare Tunnel (ADR-005).

## 15. 핵심 메시지

본 패키지의 존재 이유는 **메인 라이브러리(`python-krtour-map`)의 의존성 축소**다.
TripMate가 본 라이브러리를 import할 때 FastAPI/Uvicorn/React가 딸려 들어오면 안
된다. 디버그 UI를 쓰고 싶으면 별도로 `pip install -e packages/krtour-map-debug-ui`
+ `cd frontend && npm ci && npm run build`.

이 분리는 ADR-020에 박혀 있고, `import-linter` 계약(`pyproject.toml`)이 메인
패키지의 FastAPI import를 차단한다. 지도 frontend는 ADR-025로 `maplibre-vworld-js`
가 박혔다 (VWorld 지도, Kakao Maps SDK 미사용). VWorld API key는
`KRADDR_GEO_VWORLD_API_KEY` 공유 정책으로 일원화되며 (ADR-025 사용자 보강
2026-05-25), TripMate 사용자 UI 측 지도 stack도 동일하게 통일된다 (ADR-026).
`maplibre-vworld-js` 자체에서 문제가 발생하면 wrapper 도입(ADR-006 위배) 대신
upstream 저장소(`digitie/maplibre-vworld-js`)에 직접 PR로 적극 수정한다.
