# python-krtour-map

`python-krtour-map`은 여러 한국 공공 API 라이브러리(`python-*-api`)에서 올라오는
여행 지도 데이터를 단일 `Feature` 계약으로 정규화·저장·조회·수정·삭제하는
**TripMate 하부 라이브러리**다. PostgreSQL + PostGIS + SQLAlchemy 2 async +
GeoAlchemy2 + GeoPandas 위에서 동작한다.

> **현재 상태 (v2 설계 단계)**: master/main 브랜치는 v2 사양으로 새로 시작했다.
> 이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. 본 단계는 **문서/설계 전용**이며
> 별도 요청 전에는 코드를 작성하지 않는다. v1 산출물 요약은
> `python-krtour-map-spec.docx`(저장소 루트, 약 80쪽) 참고.

## 정체성

- **GitHub 저장소**: `python-krtour-map`
- **Python import**: `from krtour.map import ...` (ADR-022, PEP 420 implicit namespace `krtour`)
- **환경변수 prefix**: `KRTOUR_MAP_*`
- **PostgreSQL DB 이름 (개발)**: `krtour_map`
- **스키마 분리**: `feature`, `provider_sync`, `ops`, `x_extension`

## TripMate와의 연계

`python-krtour-map`은 TripMate에 **함수 라이브러리 형태**로 연결된다.
HTTP/REST가 아니다.

```python
from krtour.map import AsyncKrtourMapClient

async with AsyncKrtourMapClient(engine=tripmate_engine, providers=...) as client:
    features = await client.features_in_bounds(bbox, kinds=["place", "event"])
    weather = await client.build_weather_card(feature_id, asof=datetime.utcnow())
```

디버그 REST/UI는 **별도 Python 패키지** `krtour-map-debug-ui`
(`packages/krtour-map-debug-ui/`, ADR-020)로 분리되어 있고 **디버그 UI 백엔드 +
향후 내부 활용 전용**이며 인증 키를 요구하지 않는다(내부망 전제). TripMate ↔
라이브러리 통신에는 사용하지 않는다. 메인 라이브러리는 FastAPI 의존이 없다.

## 책임 / 비책임 요약

### 책임

- 공통 feature DTO: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- 결정적 `feature_id` 생성
- `python-*-api` provider 결과를 `Feature`/`SourceRecord`/`WeatherValue`/`PriceValue`/
  `FeatureFile`로 정규화
- PostgreSQL + PostGIS 스키마 + Alembic 마이그레이션 + raw SQL repository
- S3 호환 객체 저장소(RustFS) 연동: 이미지/문서 메타데이터
- 주소/좌표 정규화: `python-kraddr-base`/`python-kraddr-geo` 직접 사용
- 디버그 REST API (옵션, 인증 없음, 내부망 전용)
- Dagster asset에서 호출 가능한 collect/load 순수 함수

### 비책임

- 사용자/여행계획/POI 도메인 (TripMate가 소유)
- TripMate FastAPI 라우터, Admin UI, Alembic migration 직접 실행
- provider별 wrapper/adapter/gateway 신규 생성
- 별도 feature DB 복제 (TripMate는 라이브러리 schema를 import해 사용)
- 외부 노출용 인증 REST API

자세한 책임 경계는 `docs/architecture.md` 및 `docs/provider-contract.md`.

## 빠른 시작 (구현 후 사용 예정)

```bash
# WSL ext4 작업 디렉토리에서
cd ~/dev/python-krtour-map

# 메인 라이브러리 (FastAPI 의존 없음)
uv venv && uv pip install -e ".[dev,geo,providers]"

# PostgreSQL + PostGIS (Docker)
docker compose up -d postgres

# 스키마 적용
alembic upgrade head

# (옵션) 디버그 UI 별도 패키지 설치
uv pip install -e packages/krtour-map-debug-ui

# (디버그) REST API 기동 — 인증 없음, localhost 전용
uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8600
```

## 의존 스택 (v2 확정)

| 계층 | 라이브러리 |
|------|-----------|
| DB | PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto |
| ORM/SQL | SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 |
| 공간 처리 | GeoPandas, Shapely 2, GDAL Python binding |
| 모델 | Pydantic v2 |
| HTTP (디버그 API, 별도 패키지) | FastAPI + Uvicorn — `krtour-map-debug-ui`만 |
| HTTP client | httpx + tenacity |
| 마이그레이션 | Alembic |
| 주소/좌표 | `python-kraddr-base`, `python-kraddr-geo` |
| Provider client | `python-{visitkorea,mois,opinet,krex,kma,khoa,airkorea,krforest,krheritage,kasi,datagokr,mcst,krairport}-api` |
| 객체 저장소 | S3 호환 (RustFS 우선) |
| Orchestration | Dagster (TripMate가 wiring; 라이브러리는 collect/load 순수 함수만 제공) |
| Lint/Type | ruff, mypy --strict, import-linter |
| Test | pytest, pytest-asyncio, hypothesis, testcontainers-python, VCR.py |

`python-kraddr-geo`와 동일한 스택을 의도적으로 채택했다 (운영 환경 통일,
ADR-007/008 참조).

## 디렉토리 (계획)

본 저장소는 **monorepo**다. Python 패키지 2개:

```
src/krtour/                        ← PEP 420 implicit namespace (NO __init__.py)
  map/                             ← 메인 패키지 (FastAPI 의존 없음)
    __init__.py
    category/    — kraddr-base에서 이전 (ADR-023)
    dto/         — pydantic v2 입력/출력 (DB/FastAPI 의존 없음)
    core/        — 비즈니스 로직 (Protocol에만 의존; make_feature_id, scoring, merge)
    infra/       — DB 어댑터 (SQLAlchemy 2 async + raw SQL + Alembic)
    providers/   — provider별 raw → DTO 변환 모듈 (wrapper 신규 생성 금지)
    client.py    — AsyncKrtourMapClient (라이브러리 진입점)
    cli/         — typer CLI (옵션)

packages/krtour-map-debug-ui/      ← 별도 패키지 (ADR-020)
  pyproject.toml
  src/krtour/                      ← 같은 namespace 공유 (NO __init__.py)
    map_debug_ui/
      __init__.py
      app.py     — FastAPI app factory + uvicorn entrypoint
      routers/   — 디버그 엔드포인트
      deps.py    — AsyncKrtourMapClient 주입
      settings.py
      views/     — (옵션) 정적 UI

alembic/, sql/ — 스키마 마이그레이션과 DDL
tests/
  unit/        — Fake repo 기반
  integration/ — testcontainers PostGIS
  e2e/         — 디버그 패키지 + integration DB
  fixtures/    — replay 회귀
docs/          — 사양·결정·작업 기록 (한국어)
data/          — 원천/픽스처 대용량 (NTFS, .gitignore)
```

메인 패키지 의존 방향: **category → dto → core → infra → providers → client →
cli** 한 방향. `import-linter`가 CI에서 강제 (ADR-002, `docs/architecture.md`).
`krtour.map.api`는 존재하지 않는다 (ADR-020).

별도 패키지 `krtour.map_debug_ui`는 `krtour.map.client`만 import해서 함수
호출한다 (ADR-020 + ADR-022, `docs/debug-ui-package.md`).

## 설계 원칙

- **성능 설계는 인덱스부터** — 모든 신규 table은 ADR에 인덱스 설계 동반.
  자세한 룰은 `docs/performance.md`.
- **테스트는 촘촘하게** — unit(Fake repo) + integration(testcontainers) +
  e2e + replay fixture. Coverage 목표 `core 90%+ / infra 80%+ / 전체 80%+`.
  자세한 사양은 `docs/test-strategy.md`.
- **결정은 ADR로 박는다** — `docs/decisions.md`. 결정이 뒤집힐 때도 이전 기록은
  지우지 않고 `superseded by ADR-XXX`.
- **async-only API** — 동기 인터페이스 추가 금지. 호출자가 `asyncio.run`.
- **wrapper 금지** — provider client는 그대로 사용. 변환 순수 함수까지만 허용.

## 검증

```bash
python -m pytest -q               # 코드 작성 단계 이후
python -m ruff check .
python -m mypy src/krtour/map
lint-imports
```

문서 단계에서는 위 명령이 의미 있는 산출물을 만들지 않는다. `docs/agent-guide.md`
참고.

## 문서 지도

- [`AGENTS.md`](AGENTS.md) — 에이전트 지시 우선순위, DO NOT 룰, TripMate 경계
- [`SKILL.md`](SKILL.md) — 작업 매뉴얼 (DO NOT, 자주 묻는 작업, 도메인 어휘)
- [`CLAUDE.md`](CLAUDE.md) — Claude(Code/Agent SDK)용 1쪽 진입 요약
- [`docs/architecture.md`](docs/architecture.md) — 의존 방향, 계층, 데이터 흐름
- [`docs/decisions.md`](docs/decisions.md) — ADR 누적 (ADR-001~)
- [`docs/data-model.md`](docs/data-model.md) — Postgres 테이블·인덱스 reference
- [`docs/backend-package.md`](docs/backend-package.md) — 메인 라이브러리 사양
- [`docs/debug-ui-package.md`](docs/debug-ui-package.md) — `krtour-map-debug-ui` 별도 패키지 사양 (ADR-020)
- [`docs/category.md`](docs/category.md) — `krtour.map.category` 모듈 사양 (kraddr-base에서 이전, ADR-023)
- [`docs/postgres-schema.md`](docs/postgres-schema.md) — PostgreSQL 스키마 reference 카탈로그 (data-model의 빠른 참조)
- [`docs/feature-files-rustfs.md`](docs/feature-files-rustfs.md) — S3 호환 객체 저장소 + 파일 메타
- [`docs/feature-opening-hours.md`](docs/feature-opening-hours.md) — 영업시간 DTO + DB
- [`docs/kraddr-base-types.md`](docs/kraddr-base-types.md) — `python-kraddr-base` 사용 기준
- [`docs/address-geocoding.md`](docs/address-geocoding.md) — 주소·좌표 보강 + match level
- [`docs/weather-feature-normalization.md`](docs/weather-feature-normalization.md) — weather 정규화 (forecast_style + timeline_bucket)
- [`docs/dagster-boundary.md`](docs/dagster-boundary.md) — Dagster 책임 경계
- [`docs/debug-fixture-workflow.md`](docs/debug-fixture-workflow.md) — fixture 저장/replay
- [`docs/feature-db-initialization.md`](docs/feature-db-initialization.md) — DB 부트스트랩
- [`docs/tripmate-integration.md`](docs/tripmate-integration.md) — TripMate가 본 라이브러리 사용하는 법
- [`docs/event-feature-etl.md`](docs/event-feature-etl.md) — VisitKorea 축제 ETL
- [`docs/mois-feature-etl.md`](docs/mois-feature-etl.md) — `python-mois-api` 활용 feature 적재 full lifecycle (Step A/B/C/D)
- [`docs/mois-license-feature-etl.md`](docs/mois-license-feature-etl.md) — MOIS 인허가 → place 승격 (Step B 좁은 가이드)
- [`docs/opinet-place-price-etl.md`](docs/opinet-place-price-etl.md) — OpiNet 주유소+유가 ETL
- [`docs/khoa-beach-info-etl.md`](docs/khoa-beach-info-etl.md) — KHOA 해수욕장 ETL
- [`docs/krheritage-feature-etl.md`](docs/krheritage-feature-etl.md) — 국가유산청 ETL
- [`docs/forest-feature-etl.md`](docs/forest-feature-etl.md) — 산림청 + 국립공원공단(KNPS) ETL
- [`docs/krex-rest-area-feature-etl.md`](docs/krex-rest-area-feature-etl.md) — 도로공사 휴게소 ETL
- [`docs/standard-data-feature-etl.md`](docs/standard-data-feature-etl.md) — data.go.kr 표준데이터 5종 ETL
- [`docs/notice-feature-etl.md`](docs/notice-feature-etl.md) — 통합 notice ETL (4 provider)
- [`docs/kma-weather-etl.md`](docs/kma-weather-etl.md) — KMA weather ETL
- [`docs/place-phone-enrichment.md`](docs/place-phone-enrichment.md) — 장소 전화번호 보강
- [`docs/performance.md`](docs/performance.md) — 인덱스 설계 + 공간 쿼리 가이드 +
  bulk insert 룰
- [`docs/test-strategy.md`](docs/test-strategy.md) — 4단계 테스트 + 커버리지 목표
- [`docs/provider-contract.md`](docs/provider-contract.md) — wrapper 금지 + provider
  카탈로그
- [`docs/feature-model.md`](docs/feature-model.md) — Feature DTO 7 kind + detail
- [`docs/agent-guide.md`](docs/agent-guide.md) — 작업·문서화 가이드, 첫 5분 프로토콜
- [`docs/dev-environment.md`](docs/dev-environment.md) — WSL ext4/NTFS 설정
- [`docs/windows-reinstall-recovery.md`](docs/windows-reinstall-recovery.md) —
  세션 복구 절차
- [`docs/external-apis.md`](docs/external-apis.md) — provider API 키 발급/호출
- [`docs/tasks.md`](docs/tasks.md), [`docs/resume.md`](docs/resume.md),
  [`docs/journal.md`](docs/journal.md) — 백로그·진척도·작업 일지

## 라이선스

GPL-3.0-or-later. 자세한 내용은 [`LICENSE`](LICENSE).

저장소에 포함된 소스 코드/문서에만 적용된다. provider 원천 데이터·API 응답은
각 기관 이용약관·저작권을 따른다(KMA, VisitKorea, MOIS, OpiNet, KREX, KHOA,
국가유산청, 산림청, AirKorea 등).
