# debug-ui-package.md — `krtour-map-debug-ui` 사양

본 문서는 `python-krtour-map` 저장소 내 별도 Python 패키지
`krtour-map-debug-ui`의 사양 reference다. 결정 근거는 `docs/decisions.md`의
ADR-005(인증 없음, 내부망 전용) + ADR-020(별도 패키지 분리).

## 1. 정체성

| 항목 | 값 |
|------|----|
| 패키지명 (PyPI 형식) | `krtour-map-debug-ui` |
| Python import | `from krtour_map_debug_ui import ...` |
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
├── src/krtour_map_debug_ui/
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
│   └── views/                 — (옵션) 정적 HTML/JS 또는 Next.js bridge
│       └── (Sprint 5 이후 결정)
└── tests/
    ├── unit/                 — Fake repo + httpx ASGITransport
    ├── e2e/                  — testcontainers PostGIS + 실제 메인 라이브러리
    └── conftest.py
```

## 3. 의존 방향

```
krtour_map_debug_ui.app
   ↓
krtour_map_debug_ui.routers.*
   ↓
krtour_map_debug_ui.deps   ──→   krtour_map.client (AsyncKrtourMapClient)
                                       ↓
                              메인 패키지 (dto/core/infra/providers)
```

- 본 패키지는 `krtour_map.client`만 import한다.
- `krtour_map.infra`, `krtour_map.providers` 직접 import 금지 — 본 패키지의
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
uvicorn krtour_map_debug_ui.app:app --host 127.0.0.1 --port 8600

# 환경변수로 override
KRTOUR_MAP_DEBUG_UI_HOST=127.0.0.1 \
KRTOUR_MAP_DEBUG_UI_PORT=8600 \
KRTOUR_MAP_PG_DSN=postgresql+asyncpg://... \
uvicorn krtour_map_debug_ui.app:app

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
`openapi.json` 갱신 강제.

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

## 14. 핵심 메시지

본 패키지의 존재 이유는 **메인 라이브러리(`python-krtour-map`)의 의존성 축소**다.
TripMate가 본 라이브러리를 import할 때 FastAPI/Uvicorn이 딸려 들어오면 안 된다.
디버그 UI를 쓰고 싶으면 별도로 `pip install -e packages/krtour-map-debug-ui`.

이 분리는 ADR-020에 박혀 있고, `import-linter` 계약(`pyproject.toml`)이 메인
패키지의 FastAPI import를 차단한다.
