# kor-travel-map

`kor-travel-map`은 여러 한국 공공 API 라이브러리(`python-*-api`)에서 올라오는
여행 지도 데이터를 단일 `Feature` 계약으로 정규화·저장·조회·수정·삭제하는
**kor-travel-map 독립 프로그램 + 내부 Python 라이브러리**다. PostgreSQL + PostGIS +
SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas 위에서 동작한다.

> **운영 모델 (ADR-045)**: master/main은 v2 사양으로 재시작했고 이전(v1) 구현은
> `v1` 브랜치에 보존되어 있다. kor-travel-map은 TripMate와 별개로 **Docker 독립
> 프로그램**(논리 서비스 api/frontend/dagster/postgres + 선택 rustfs)으로 실행되며
> 독립 DB/Dagster를 가지고, TripMate는 라이브러리를 직접 import하지 않고 OpenAPI
> (HTTP)로만 연동한다.
>
> **기준값(잘 바뀌지 않는 사실)**: docker-manager 로컬 포트 기준 API `12701` /
> admin UI `12705` / Dagster `12702`, RustFS S3 `12101`·console `12105`, geocoding은
> kor-travel-geo REST v2 `POST /v2/{reverse,geocode}` 로컬 `http://127.0.0.1:12501`,
> frontend Next.js 16 + `maplibre-vworld-js#v0.1.3`. ADR 현황: **001~056 accepted**
> (다음 후보 057). ADR-048은 `/v1` REST clean cut + 정합성 표준, ADR-053은
> `kor-travel-concierge` YouTube provider
> identity와 TripMate 직접 연동 제거 경계, ADR-054는
> `kor-travel-map` / `kortravelmap` package identity clean cut. admin UI는
> `/admin/dagster`에서 Dagster 요약 + webserver embed 제공. ADR-056은
> `pinvi` T-108에서 streaming replication을 제외하고 N150/Odroid
> multi-platform Docker build를 본 저장소 운영 자동화로 고정한다.
>
> **현재 진척·스프린트 상태의 단일 정본은 `docs/resume.md`(다음 한 작업) +
> `docs/tasks.md`(백로그)다** — 이 README에는 자주 바뀌는 PR 번호/완료여부를 박지
> 않는다(반복 drift 회피 — `docs/reports/docs-consistency-audit-2026-06-06.md`
> DA-D-01). Sprint 계획은 `docs/sprints/`. v1 산출물 요약은
> `kor-travel-map-spec.docx`(저장소 루트, 약 80쪽).

## 정체성

> **T-226 package identity**: ADR-054에 따라 public 배포명은 `kor-travel-map`, Python import
> root는 `kortravelmap`, 권장 예시는 `import kortravelmap as ktm`로 clean cut했다.
> CLI 목표명은 `ktmctl`, PostgreSQL 기본 DB는 `kor_travel_map`, RustFS bucket/prefix는
> `kor-travel-map` 계열로 둔다.
> 전환 정본은
> [`docs/package-identity-rename.md`](docs/package-identity-rename.md).

- **GitHub 저장소**: `kor-travel-map`
- **Python import**: `import kortravelmap as ktm` 또는 `from kortravelmap import ...`
- **환경변수 prefix**: `KOR_TRAVEL_MAP_*`
- **PostgreSQL DB 이름 (개발/운영 기본)**: `kor_travel_map` (TripMate 공유 DB 아님)
- **Dagster metadata DB 기본**: `kor_travel_map_dagster`
- **스키마 분리**: `feature`, `provider_sync`, `ops`, `x_extension`

## TripMate와의 연계

ADR-045 이후 TripMate와 kor-travel-map은 **OpenAPI 기반 HTTP**로 연결된다.
TripMate는 kor-travel-map DB에 직접 접근하지 않고, `kor-travel-map`을 운영 코드에서
직접 import하지 않는다.

`kor-travel-map` 메인 패키지는 kor-travel-map API/Dagster 내부 구현에서 사용하는
async 함수 라이브러리다. REST/OpenAPI backend는 **별도 Python 패키지**
`kor-travel-map-api`(`packages/kor-travel-map-api/`, ADR-055)에 두고, admin UI는
`kor-travel-map-admin`(`packages/kor-travel-map-admin/frontend/`)가 소유한다.
OpenAPI는 admin/ops/debug와 TripMate/user-facing 표면을 같은 API 서버에서 관리한다.

## 책임 / 비책임 요약

### 책임

- 공통 feature DTO: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- 결정적 `feature_id` 생성
- `python-*-api` provider 결과를 `Feature`/`SourceRecord`/`WeatherValue`/`PriceValue`/
  `FeatureFile`로 정규화
- `kor-travel-concierge`의 YouTube 장소 후보 REST export를 `kor-travel-concierge-youtube`
  provider로 소비해 `FeatureBundle`로 정규화
- PostgreSQL + PostGIS 스키마 + Alembic 마이그레이션 + raw SQL repository
- S3 호환 객체 저장소(RustFS) 연동: 이미지/문서 메타데이터
- 주소/좌표 정규화: 내장 `Address`/`Coordinate` DTO + `kor-travel-geo`
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
> PC 개발의 Git 원본은 **Windows NTFS (`F:\dev\kor-travel-map`)** 입니다.
> 브랜치 전환, 커밋, push 같은 순수 Git 명령만 Windows Git(`git.exe`)으로
> 수행합니다. 파일 조회·수정·테스트·lint·build·Docker·GitHub CLI 등 나머지 작업은
> WSL에서 `/mnt/f/dev/kor-travel-map-<agent>` 경로로 실행합니다.
> Playwright e2e만 Windows 호스트에서 실행합니다.

```
NTFS (Git 원본): F:\dev\kor-travel-map\              ← 코드/git/source of truth
agent worktree:  F:\dev\kor-travel-map-codex\        ← ChatGPT Codex 전용
WSL 실행 경로:   /mnt/f/dev/kor-travel-map-codex/     ← Git 외 작업 기본 위치
WSL ext4 mirror: ~/dev/kor-travel-map/                ← 성능·격리 필요 시 선택
data/:           F:\dev\kor-travel-map\data\          ← git 제외, NTFS 보관
```

자세한 셋업은 `docs/dev-environment.md` (Windows Git + WSL 실행 기준). 정책은 `AGENTS.md`
§"개발 환경 정책 (PC, WSL)" + `SKILL.md` §"개발 환경 (PC, WSL)".

## 빠른 시작 (feature 적재/조회/병합 + admin/API UI)

```bash
# Windows Git 작업은 F:\dev\kor-travel-map 또는 agent worktree에서 수행
git.exe -C F:/dev/kor-travel-map-codex status

# Git 외 작업은 WSL에서 NTFS worktree를 직접 사용
cd /mnt/f/dev/kor-travel-map-codex
ln -sfn /mnt/f/dev/kor-travel-map/data data

# 메인 라이브러리 (FastAPI 의존 없음)
uv venv && uv pip install -e ".[dev,geo,providers]"

# PostgreSQL + PostGIS (Docker)
docker compose up -d postgres

# 스키마 적용
alembic upgrade head

# (옵션) REST API 별도 패키지 설치
uv pip install -e packages/kor-travel-map-api

# (디버그) REST API 기동 — 인증 없음, localhost 전용
uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 12701

# (옵션) 디버그 UI frontend — WSL 셸에서 실행
cd packages/kor-travel-map-admin/frontend
which node npm              # /home/.../.nvm/... 등 WSL 경로여야 함 (/mnt/c/... 금지)
cp .env.example .env.local  # NEXT_PUBLIC_VWORLD_API_KEY 설정
npm install && npm run dev   # http://127.0.0.1:12705
```

Frontend dev/prod 서버(`npm run dev`, `npm run start`)는 **WSL에서 실행**한다.
Windows Node/npm(`/mnt/c/Program Files/nodejs/...`)으로 frontend 서버를 띄우지
않는다. `which node`/`which npm`이 `/mnt/c/...`를 가리키면 WSL nvm Node를 먼저
활성화한다. Windows는 Playwright e2e 검증 시 Chromium 실행용으로만 사용한다
(`docs/dev-environment.md` §8.1).

## 의존 스택 (v2 확정)

| 계층 | 라이브러리 |
|------|-----------|
| DB | PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto |
| ORM/SQL | SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 |
| 공간 처리 | GeoPandas, Shapely 2, GDAL Python binding |
| 모델 | Pydantic v2 |
| HTTP API (별도 패키지) | FastAPI + Uvicorn — `kor-travel-map-api`만 |
| HTTP client | httpx + tenacity |
| 마이그레이션 | Alembic |
| 주소/좌표 | `python-kraddr-base`, `kor-travel-geo` |
| Provider client/export | `python-{visitkorea,mois,opinet,krex,kma,khoa,airkorea,krforest,krheritage,kasi,datagokr,mcst,krairport}-api` + `kor-travel-concierge` REST export |
| 객체 저장소 | S3 호환 (RustFS 우선, 로컬 API `12101` / console `12105`) |
| Orchestration | Dagster (kor-travel-map 독립 프로그램이 소유; OpenAPI로 update request 큐잉/제어) |
| Lint/Type | ruff, mypy --strict, import-linter |
| Test | pytest, pytest-asyncio, hypothesis, testcontainers-python, VCR.py |

`kor-travel-geo`와 동일한 스택을 의도적으로 채택했다 (운영 환경 통일,
ADR-007/008 참조).

## 디렉토리 (계획)

본 저장소는 **monorepo**다. Python 패키지와 frontend workspace:

```
src/kortravelmap/                  ← 메인 패키지 (FastAPI 의존 없음)
    __init__.py
    category/    — kraddr-base에서 이전 (ADR-023)
    dto/         — pydantic v2 입력/출력 (DB/FastAPI 의존 없음)
    core/        — 비즈니스 로직 (Protocol에만 의존; make_feature_id, scoring, merge)
    infra/       — DB 어댑터 (SQLAlchemy 2 async + raw SQL + Alembic)
    providers/   — provider별 raw → DTO 변환 모듈 (wrapper 신규 생성 금지)
    client.py    — AsyncKorTravelMapClient (라이브러리 진입점)
    cli/         — typer CLI (옵션)

packages/kor-travel-map-api/        ← REST API Python 패키지 (ADR-055)
  pyproject.toml
  src/kortravelmap/
    api/
      __init__.py
      app.py     — FastAPI app factory + uvicorn entrypoint
      routers/   — debug/admin/ops 엔드포인트
      settings.py

packages/kor-travel-map-admin/
  frontend/     — Next.js admin UI

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
별도 패키지 `kortravelmap.api`는 FastAPI/OpenAPI 서버이며, 메인 라이브러리에
FastAPI/Uvicorn 의존성을 끌어오지 않는다 (ADR-020/055, `docs/debug-ui-package.md`).

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
- **ADR-045 이행은 정본 우선** — 구 debug-ui 경로/env/import,
  TripMate 직접 import, 공유 DB, TripMate-owned Dagster 호환 shim은 만들지 않는다
  (ADR-046).

## 검증

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/kortravelmap
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
- [`docs/decisions.md`](docs/decisions.md) — ADR 누적 (ADR-001~056)
- [`docs/sprints/README.md`](docs/sprints/README.md) — Sprint 1~5 계획 + ADR-034 9단계 구현 순서
  - [`docs/sprints/SPRINT-1.md`](docs/sprints/SPRINT-1.md) — 코드 작성 단계 진입 + scaffolding (provider 없음)
  - [`docs/sprints/SPRINT-2.md`](docs/sprints/SPRINT-2.md) — MOIS-독립 4 provider (축제/날씨/유가/휴게소) + 디버그 UI 첫 라우터
  - [`docs/sprints/SPRINT-3.md`](docs/sprints/SPRINT-3.md) — KNPS/krheritage + 정합성 Phase 1 (F1~F3)
  - [`docs/sprints/SPRINT-4.md`](docs/sprints/SPRINT-4.md) — MOIS bulk 4단계 + dedup queue + Coverage 80% 도달
  - [`docs/sprints/SPRINT-5.md`](docs/sprints/SPRINT-5.md) — MOIS-sibling (휴양림/박물관) + Phase 2 + 운영 진입
- [`docs/data-model.md`](docs/data-model.md) — Postgres 테이블·인덱스 reference
- [`docs/backend-package.md`](docs/backend-package.md) — 메인 라이브러리 사양
- [`docs/debug-ui-package.md`](docs/debug-ui-package.md) — `kor-travel-map-api` backend와 `kor-travel-map-admin` frontend 분리 사양
- [`docs/debug-ui-admin-workflows.md`](docs/debug-ui-admin-workflows.md) — debug UI/admin 운영 콘솔 상세 구현 사양
- [`docs/openapi-admin-contract.md`](docs/openapi-admin-contract.md) — Admin 우선 OpenAPI + Dagster feature update queue 계약
- [`docs/regions-within-radius.md`](docs/regions-within-radius.md) — POI 반경 내/교차 행정구역 조회(kor-travel-geo REST v2) 사양
- [`docs/adr045-standalone-plan.md`](docs/adr045-standalone-plan.md) — **ADR-045 독립 프로그램화 실행 계획**(T-205~T-210, AI agent 실행용)
- [`docs/adr045-open-decisions.md`](docs/adr045-open-decisions.md) — ADR-045 의사결정 결과(D-1~D-16, 전부 결정 완료)
- [`docs/tripmate-rest-api.md`](docs/tripmate-rest-api.md) — TripMate 연계 REST API params/returns 계약
- [`docs/public-views-api.md`](docs/public-views-api.md) — TripMate T-130 공개 해수욕장/축제 뷰 후보 사양
- [`docs/poi-cache-update-targets.md`](docs/poi-cache-update-targets.md) — 외부 POI key 기반 주변 feature 캐시 갱신 타깃
- [`docs/category.md`](docs/category.md) — `kortravelmap.category` 모듈 사양 (kraddr-base에서 이전, ADR-023)
- [`docs/postgres-schema.md`](docs/postgres-schema.md) — PostgreSQL 스키마 reference 카탈로그 (data-model의 빠른 참조)
- [`docs/feature-files-rustfs.md`](docs/feature-files-rustfs.md) — S3 호환 객체 저장소 + 파일 메타
- [`docs/feature-opening-hours.md`](docs/feature-opening-hours.md) — 영업시간 DTO + DB
- [`docs/kraddr-base-types.md`](docs/kraddr-base-types.md) — `python-kraddr-base` 사용 기준
- [`docs/address-geocoding.md`](docs/address-geocoding.md) — 주소·좌표 보강 + match level
- [`docs/weather-feature-normalization.md`](docs/weather-feature-normalization.md) — weather 정규화 (forecast_style + timeline_bucket)
- [`docs/dagster-boundary.md`](docs/dagster-boundary.md) — Dagster 책임 경계
- [`docs/debug-fixture-workflow.md`](docs/debug-fixture-workflow.md) — fixture 저장/replay
- [`docs/feature-db-initialization.md`](docs/feature-db-initialization.md) — DB 부트스트랩
- [`docs/tripmate-integration.md`](docs/tripmate-integration.md) — TripMate ↔ kor-travel-map OpenAPI 연동
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
- [`docs/tasks.md`](docs/tasks.md)(진행/예정 백로그) · [`docs/tasks-done.md`](docs/tasks-done.md)(완료·아카이브),
  [`docs/resume.md`](docs/resume.md),
  [`docs/journal.md`](docs/journal.md) — 백로그·진척도·작업 일지

## 라이선스

GPL-3.0-or-later. 자세한 내용은 [`LICENSE`](LICENSE).

저장소에 포함된 소스 코드/문서에만 적용된다. provider 원천 데이터·API 응답은
각 기관 이용약관·저작권을 따른다(KMA, VisitKorea, MOIS, OpiNet, KREX, KHOA,
국가유산청, 산림청, AirKorea 등).
