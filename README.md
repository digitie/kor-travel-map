# python-krtour-map

`python-krtour-map`은 여러 한국 공공 API 라이브러리(`python-*-api`)에서 올라오는
여행 지도 데이터를 단일 `Feature` 계약으로 정규화·저장·조회·수정·삭제하는
**krtour-map 독립 프로그램 + 내부 Python 라이브러리**다. PostgreSQL + PostGIS +
SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas 위에서 동작한다.

> **현재 상태 (v2 Sprint 4(4a+4b) 완료, Sprint 5 + ADR-045 독립 프로그램화 진입
> 준비 — PR#149 이후 기준)**:
> master/main 브랜치는 v2 사양으로 새로 시작했다. 이전(v1) 구현은 `v1`
> 브랜치에 보존되어 있다. Sprint 2~3에서 provider 변환, PostGIS 적재/조회,
> consistency report, dedup queue, `AsyncKrtourMapClient`, debug UI `/features`와
> geocoding 경로까지 구현했고, Sprint 4에서 MOIS Step A~D lifecycle(bulk/
> incremental/closed/detail), `krtour-map dedup-merge` + `feature_merge_history`,
> dedup 운영 FP 통계, ADR-033 F4, Place phone enrichment, coverage 80% 달성(실측
> 94.12%)까지 마쳤다. 현재 geocoding 정본은 kraddr-geo REST v2
> `POST /v2/{reverse,geocode}` + 로컬 `http://127.0.0.1:8888`, frontend 정본은
> Next.js 16 + `maplibre-vworld-js#v0.1.2`다. 2026-06-01 ADR-045로 운영 모델은
> Docker 독립 프로그램 + 독립 DB/Dagster + TripMate OpenAPI 연동으로 전환됐다.
> ADR 현황: **001~046 모두 accepted** (다음 후보 047). Sprint 계획은
> `docs/sprints/`, 다음 작업은 `docs/resume.md` 참조. v1 산출물 요약은
> `python-krtour-map-spec.docx`(저장소 루트, 약 80쪽) 참고.

## 정체성

- **GitHub 저장소**: `python-krtour-map`
- **Python import**: `from krtour.map import ...` (ADR-022, PEP 420 implicit namespace `krtour`)
- **환경변수 prefix**: `KRTOUR_MAP_*`
- **PostgreSQL DB 이름 (개발/운영 기본)**: `krtour_map` (TripMate 공유 DB 아님)
- **Dagster metadata DB 기본**: `krtour_map_dagster`
- **스키마 분리**: `feature`, `provider_sync`, `ops`, `x_extension`

## TripMate와의 연계

ADR-045 이후 TripMate와 krtour-map은 **OpenAPI 기반 HTTP**로 연결된다.
TripMate는 krtour-map DB에 직접 접근하지 않고, `python-krtour-map`을 운영 코드에서
직접 import하지 않는다.

`python-krtour-map` 메인 패키지는 krtour-map API/Dagster 내부 구현에서 사용하는
async 함수 라이브러리다. REST/OpenAPI와 admin UI는 **별도 Python 패키지**
`krtour-map-admin`(`packages/krtour-map-admin/`, ADR-020/035/045)에 둔다.
OpenAPI는 우선 admin UI 기준으로 작성하고, TripMate 연동 시 필요한 API를 보완·확장한다.

## 책임 / 비책임 요약

### 책임

- 공통 feature DTO: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- 결정적 `feature_id` 생성
- `python-*-api` provider 결과를 `Feature`/`SourceRecord`/`WeatherValue`/`PriceValue`/
  `FeatureFile`로 정규화
- PostgreSQL + PostGIS 스키마 + Alembic 마이그레이션 + raw SQL repository
- S3 호환 객체 저장소(RustFS) 연동: 이미지/문서 메타데이터
- 주소/좌표 정규화: 내장 `Address`/`Coordinate` DTO + `python-kraddr-geo`
  REST 서비스 연동
- OpenAPI backend/admin UI (별도 패키지, 인증 없음, 내부망/네트워크 계층 보호)
- 독립 Dagster 기반 provider sync / feature update queue / consistency job

### 비책임

- 사용자/여행계획/POI 도메인 (TripMate가 소유)
- TripMate FastAPI 라우터, 사용자 UI, 여행계획/POI 도메인
- provider별 wrapper/adapter/gateway 신규 생성
- TripMate DB migration 또는 TripMate DB 직접 FK
- 외부 노출용 인증 REST API

자세한 책임 경계는 `docs/architecture.md` 및 `docs/provider-contract.md`.

## 💻 개발 환경 (PC, WSL)

> [!WARNING]
> PC 개발의 Git 원본은 **Windows NTFS (`F:\dev\python-krtour-map`)** 입니다.
> 브랜치 전환, 커밋, PR 준비는 Windows Git(`git.exe`) 기준으로 수행합니다.
> WSL은 PostGIS/testcontainers/e2e처럼 Linux 실행 환경이 필요할 때만
> NTFS 소스를 ext4 샌드박스로 `rsync`해서 사용합니다.

```
NTFS (Git 원본): F:\dev\python-krtour-map\              ← 코드/git/source of truth
agent worktree:  F:\dev\python-krtour-map-codex\        ← ChatGPT Codex 전용
WSL 샌드박스:    ~/dev/python-krtour-map/                ← 테스트/실행 전용 복사본
data/:           F:\dev\python-krtour-map\data\          ← git 제외, NTFS 보관
```

자세한 셋업은 `docs/dev-environment.md` (Windows Git + WSL 실행 기준). 정책은 `AGENTS.md`
§"개발 환경 정책 (PC, WSL)" + `SKILL.md` §"개발 환경 (PC, WSL)".

## 빠른 시작 (Sprint 4 완료 — feature 적재/조회/병합 + admin/API UI 동작)

```bash
# Windows Git 작업은 F:\dev\python-krtour-map 또는 agent worktree에서 수행
git.exe -C F:/dev/python-krtour-map status

# 테스트 전 WSL ext4 샌드박스로 동기화
rsync -a --delete --exclude .git --exclude .venv --exclude data \
  /mnt/f/dev/python-krtour-map/ ~/dev/python-krtour-map/
cd ~/dev/python-krtour-map
ln -sfn /mnt/f/dev/python-krtour-map/data data

# 메인 라이브러리 (FastAPI 의존 없음)
uv venv && uv pip install -e ".[dev,geo,providers]"

# PostgreSQL + PostGIS (Docker)
docker compose up -d postgres

# 스키마 적용
alembic upgrade head

# (옵션) 디버그 UI 별도 패키지 설치
uv pip install -e packages/krtour-map-admin

# (디버그) REST API 기동 — 인증 없음, localhost 전용
uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 8087

# (옵션) geocoding live 연동 — python-kraddr-geo FastAPI backend
export KRTOUR_MAP_ADMIN_KRADDR_GEO_BASE_URL=http://127.0.0.1:8888

# (옵션) 디버그 UI frontend (Next.js + maplibre-vworld, ADR-025 2차 보강)
cd packages/krtour-map-admin/frontend
cp .env.example .env.local  # NEXT_PUBLIC_VWORLD_API_KEY 설정
npm ci && npm run dev        # http://127.0.0.1:8610
```

## 의존 스택 (v2 확정)

| 계층 | 라이브러리 |
|------|-----------|
| DB | PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto |
| ORM/SQL | SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 |
| 공간 처리 | GeoPandas, Shapely 2, GDAL Python binding |
| 모델 | Pydantic v2 |
| HTTP (디버그 API, 별도 패키지) | FastAPI + Uvicorn — `krtour-map-admin`만 |
| HTTP client | httpx + tenacity |
| 마이그레이션 | Alembic |
| 주소/좌표 | `python-kraddr-base`, `python-kraddr-geo` |
| Provider client | `python-{visitkorea,mois,opinet,krex,kma,khoa,airkorea,krforest,krheritage,kasi,datagokr,mcst,krairport}-api` |
| 객체 저장소 | S3 호환 (RustFS 우선) |
| Orchestration | Dagster (krtour-map 독립 프로그램이 소유; OpenAPI로 update request 큐잉/제어) |
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

packages/krtour-map-admin/      ← 별도 패키지 (ADR-020)
  pyproject.toml
  src/krtour/                      ← 같은 namespace 공유 (NO __init__.py)
    map_admin/
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

별도 패키지 `krtour.map_admin`는 `krtour.map.client`만 import해서 함수
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
- **ADR-045 이행은 정본 우선** — 구 `krtour-map-debug-ui` 경로/env/import,
  TripMate 직접 import, 공유 DB, TripMate-owned Dagster 호환 shim은 만들지 않는다
  (ADR-046).

## 검증

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/krtour/map
lint-imports
```

통합 테스트와 DB schema 검증은 PostGIS testcontainers 또는 로컬 Postgres 준비가
필요하다. 자세한 절차는 `docs/agent-guide.md` 참고.

## 문서 지도

- [`AGENTS.md`](AGENTS.md) — 에이전트 지시 우선순위, DO NOT 룰, TripMate 경계
- [`SKILL.md`](SKILL.md) — 작업 매뉴얼 (DO NOT, 자주 묻는 작업, 도메인 어휘)
- [`CLAUDE.md`](CLAUDE.md) — Claude(Code/Agent SDK)용 1쪽 진입 요약
- [`CHANGELOG.md`](CHANGELOG.md) — Keep a Changelog 형식 (Unreleased + ADR-024~034)
- [`docs/architecture.md`](docs/architecture.md) — 의존 방향, 계층, 데이터 흐름
- [`docs/decisions.md`](docs/decisions.md) — ADR 누적 (ADR-001~046)
- [`docs/sprints/README.md`](docs/sprints/README.md) — Sprint 1~5 계획 + ADR-034 9단계 구현 순서
  - [`docs/sprints/SPRINT-1.md`](docs/sprints/SPRINT-1.md) — 코드 작성 단계 진입 + scaffolding (provider 없음)
  - [`docs/sprints/SPRINT-2.md`](docs/sprints/SPRINT-2.md) — MOIS-독립 4 provider (축제/날씨/유가/휴게소) + 디버그 UI 첫 라우터
  - [`docs/sprints/SPRINT-3.md`](docs/sprints/SPRINT-3.md) — KNPS/krheritage + 정합성 Phase 1 (F1~F3)
  - [`docs/sprints/SPRINT-4.md`](docs/sprints/SPRINT-4.md) — MOIS bulk 4단계 + dedup queue + Coverage 80% 도달
  - [`docs/sprints/SPRINT-5.md`](docs/sprints/SPRINT-5.md) — MOIS-sibling (휴양림/박물관) + Phase 2 + 운영 진입
- [`docs/data-model.md`](docs/data-model.md) — Postgres 테이블·인덱스 reference
- [`docs/backend-package.md`](docs/backend-package.md) — 메인 라이브러리 사양
- [`docs/debug-ui-package.md`](docs/debug-ui-package.md) — `krtour-map-admin` 별도 패키지 사양 (ADR-020)
- [`docs/debug-ui-admin-workflows.md`](docs/debug-ui-admin-workflows.md) — debug UI/admin 운영 콘솔 상세 구현 사양
- [`docs/openapi-admin-contract.md`](docs/openapi-admin-contract.md) — Admin 우선 OpenAPI + Dagster feature update queue 계약
- [`docs/regions-within-radius.md`](docs/regions-within-radius.md) — POI 반경 내/교차 행정구역 조회(kraddr-geo REST v2) 사양
- [`docs/adr045-standalone-plan.md`](docs/adr045-standalone-plan.md) — **ADR-045 독립 프로그램화 실행 계획**(T-205~T-210, AI agent 실행용)
- [`docs/adr045-open-decisions.md`](docs/adr045-open-decisions.md) — ADR-045 의사결정 결과(D-1~D-16, 전부 결정 완료)
- [`docs/tripmate-rest-api.md`](docs/tripmate-rest-api.md) — TripMate 연계 REST API params/returns 계약
- [`docs/poi-cache-update-targets.md`](docs/poi-cache-update-targets.md) — 외부 POI key 기반 주변 feature 캐시 갱신 타깃
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
- [`docs/tripmate-integration.md`](docs/tripmate-integration.md) — TripMate ↔ krtour-map OpenAPI 연동
- [`docs/event-feature-etl.md`](docs/event-feature-etl.md) — VisitKorea 축제 ETL
- [`docs/mois-feature-etl.md`](docs/mois-feature-etl.md) — `python-mois-api` 활용 feature 적재 full lifecycle (Step A/B/C/D)
- [`docs/mois-license-feature-etl.md`](docs/mois-license-feature-etl.md) — MOIS 인허가 → place 승격 (Step B 좁은 가이드)
- [`docs/opinet-place-price-etl.md`](docs/opinet-place-price-etl.md) — OpiNet 주유소+유가 ETL
- [`docs/khoa-beach-info-etl.md`](docs/khoa-beach-info-etl.md) — KHOA 해수욕장 ETL
- [`docs/krheritage-feature-etl.md`](docs/krheritage-feature-etl.md) — 국가유산청 ETL
- [`docs/forest-feature-etl.md`](docs/forest-feature-etl.md) — 산림청 + 국립공원공단(KNPS) 통합 계획 (§11 = KNPS scaffold 반영)
- [`docs/knps-feature-etl.md`](docs/knps-feature-etl.md) — `python-knps-api` (`digitie/python-knps-api`) feature 적재 계약 (14 dataset, ADR-028)
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
- [`docs/dev-environment.md`](docs/dev-environment.md) — Windows Git + WSL 실행 설정
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
