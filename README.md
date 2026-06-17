# kor-travel-map

`kor-travel-map`은 여러 한국 공공 API 라이브러리(`python-*-api`)에서 올라오는
여행 지도 데이터를 단일 `Feature` 계약으로 정규화·저장·조회·수정·삭제하는
**kor-travel-map 독립 프로그램 + 내부 Python 라이브러리**다. PostgreSQL + PostGIS +
SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas 위에서 동작한다.

Docker 독립 프로그램으로 운영하며, PinVi는 OpenAPI(HTTP)로 연동한다. 고정
포트·ADR 현황은 [`CLAUDE.md`](CLAUDE.md) §2 / [`docs/adr/README.md`](docs/adr/README.md) 참조.
진척·스프린트 상태의 단일 정본은 [`docs/resume.md`](docs/resume.md)(다음 한 작업) +
[`docs/tasks.md`](docs/tasks.md)(백로그)다. v1은 `v1` 브랜치 보존(ADR-001),
산출물 요약은 `kor-travel-map-spec.docx`(저장소 루트, 약 80쪽).

## 정체성

- **Python import**: `import kortravelmap as ktm` 또는 `from kortravelmap import ...` (ADR-054)
- **PostgreSQL 기본 DB**: `kor_travel_map` (PinVi 공유 DB 아님)

배포명·CLI·env prefix·DB·RustFS prefix 등 전체 식별자 table은 [`AGENTS.md`](AGENTS.md) §식별자.

## PinVi와의 연계

ADR-045 이후 PinVi와 kor-travel-map은 **OpenAPI 기반 HTTP**로 연결된다.
PinVi는 kor-travel-map DB에 직접 접근하지 않고, `kor-travel-map`을 운영 코드에서
직접 import하지 않는다.

`kor-travel-map` 메인 패키지는 kor-travel-map API/Dagster 내부 구현에서 사용하는
async 함수 라이브러리다. REST/OpenAPI backend는 **별도 Python 패키지**
`kor-travel-map-api`(`packages/kor-travel-map-api/`, ADR-055)에 두고, admin UI는
`kor-travel-map-admin`(`packages/kor-travel-map-admin/frontend/`)가 소유한다.
OpenAPI는 admin/ops/debug와 PinVi/user-facing 표면을 같은 API 서버에서 관리한다.

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
- OpenAPI backend/admin UI (별도 패키지, 기본 인증 없음·내부망 보호 — 인증 경계는 ADR-005)
- 독립 Dagster 기반 provider sync / feature update queue / consistency job

### 비책임

- 사용자/여행계획/POI 도메인 (PinVi가 소유)
- PinVi FastAPI 라우터, 사용자 UI, 여행계획/POI 도메인
- provider별 wrapper/adapter/gateway 신규 생성
- PinVi DB migration 또는 PinVi DB 직접 FK
- 외부 노출용 인증 REST API

자세한 책임 경계는 `docs/architecture/architecture.md` 및 `docs/architecture/provider-contract.md`.

## 개발 환경 (PC, WSL)

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

자세한 셋업·정책은 [`docs/dev-environment.md`](docs/dev-environment.md).

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

Frontend dev/prod 서버는 **WSL에서 실행**하고 Windows Node/npm은 쓰지 않는다.
Windows는 Playwright e2e Chromium 실행용으로만 사용한다 — 자세히는
[`docs/dev-environment.md`](docs/dev-environment.md) §8.1.

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

메인 패키지 의존 방향: **category → dto → core → infra → geocoding → providers → client →
cli** 한 방향. `import-linter`가 CI에서 강제 (ADR-002, `docs/architecture/architecture.md`).
별도 패키지 `kortravelmap.api`는 FastAPI/OpenAPI 서버이며, 메인 라이브러리에
FastAPI/Uvicorn 의존성을 끌어오지 않는다 (ADR-020/055, `docs/architecture/debug-ui-package.md`).

## 설계 원칙

핵심 원칙은 async-only API, wrapper 금지(provider client 직접 사용), 인덱스 우선
설계, 4단계 테스트, ADR로 결정 고정이다. 정본은 다음을 참조한다.

- 의존 방향·계층 → [`docs/architecture/architecture.md`](docs/architecture/architecture.md)
- 인덱스/공간 쿼리/bulk insert → [`docs/architecture/performance.md`](docs/architecture/performance.md)
- 테스트·커버리지 목표 → [`docs/test-strategy.md`](docs/test-strategy.md)
- DO NOT 룰 전체 + ADR-045/046 이행 경계 → [`AGENTS.md`](AGENTS.md) / [`docs/adr/README.md`](docs/adr/README.md)

## 검증

검증 명령(`pytest` / `ruff check` / `mypy --strict` / `lint-imports`)과 절차는
[`AGENTS.md`](AGENTS.md) §검증 + [`docs/agent-guide.md`](docs/agent-guide.md). 통합
테스트는 PostGIS testcontainers 또는 로컬 Postgres가 필요하다.

## 문서 지도

- [`AGENTS.md`](AGENTS.md) — 에이전트 지시 우선순위, DO NOT 룰, PinVi 경계
- [`SKILL.md`](SKILL.md) — 작업 매뉴얼 (DO NOT, 자주 묻는 작업, 도메인 어휘)
- [`CLAUDE.md`](CLAUDE.md) — Claude(Code/Agent SDK)용 1쪽 진입 요약
- [`CHANGELOG.md`](CHANGELOG.md) — Keep a Changelog 형식 (Unreleased + ADR-024~034)
- [`docs/architecture/architecture.md`](docs/architecture/architecture.md) — 의존 방향, 계층, 데이터 흐름
- [`docs/adr/README.md`](docs/adr/README.md) — ADR 누적 (ADR-001~059)
- [`docs/sprints/README.md`](docs/sprints/README.md) — Sprint 1~5 계획 + ADR-034 9단계 구현 순서
  - [`docs/sprints/SPRINT-1.md`](docs/sprints/SPRINT-1.md) — 코드 작성 단계 진입 + scaffolding (provider 없음)
  - [`docs/sprints/SPRINT-2.md`](docs/sprints/SPRINT-2.md) — MOIS-독립 4 provider (축제/날씨/유가/휴게소) + 디버그 UI 첫 라우터
  - [`docs/sprints/SPRINT-3.md`](docs/sprints/SPRINT-3.md) — KNPS/krheritage + 정합성 Phase 1 (F1~F3)
  - [`docs/sprints/SPRINT-4.md`](docs/sprints/SPRINT-4.md) — MOIS bulk 4단계 + dedup queue + Coverage 80% 도달
  - [`docs/sprints/SPRINT-5.md`](docs/sprints/SPRINT-5.md) — MOIS-sibling (휴양림/박물관) + Phase 2 + 운영 진입
- [`docs/architecture/data-model.md`](docs/architecture/data-model.md) — Postgres 테이블·인덱스 reference
- [`docs/architecture/backend-package.md`](docs/architecture/backend-package.md) — 메인 라이브러리 사양
- [`docs/architecture/debug-ui-package.md`](docs/architecture/debug-ui-package.md) — `kor-travel-map-api` backend와 `kor-travel-map-admin` frontend 분리 사양
- [`docs/debug-ui-admin-workflows.md`](docs/debug-ui-admin-workflows.md) — debug UI/admin 운영 콘솔 상세 구현 사양
- [`docs/architecture/openapi-admin-contract.md`](docs/architecture/openapi-admin-contract.md) — Admin 우선 OpenAPI + Dagster feature update queue 계약
- [`docs/architecture/regions-within-radius.md`](docs/architecture/regions-within-radius.md) — POI 반경 내/교차 행정구역 조회(kor-travel-geo REST v2) 사양
- [`docs/adr045-standalone-plan.md`](docs/adr045-standalone-plan.md) — **ADR-045 독립 프로그램화 실행 계획**(T-205~T-210, AI agent 실행용)
- [`docs/adr045-open-decisions.md`](docs/adr045-open-decisions.md) — ADR-045 의사결정 결과(D-1~D-16, 전부 결정 완료)
- [`docs/architecture/public-views-api.md`](docs/architecture/public-views-api.md) — 공개 해수욕장/축제 뷰 API 사양
- [`docs/poi-cache-update-targets.md`](docs/poi-cache-update-targets.md) — 외부 POI key 기반 주변 feature 캐시 갱신 타깃
- [`docs/architecture/category.md`](docs/architecture/category.md) — `kortravelmap.category` 모듈 사양 (kraddr-base에서 이전, ADR-023)
- [`docs/architecture/postgres-schema.md`](docs/architecture/postgres-schema.md) — PostgreSQL 스키마 reference 카탈로그 (data-model의 빠른 참조)
- [`docs/architecture/feature-files-rustfs.md`](docs/architecture/feature-files-rustfs.md) — S3 호환 객체 저장소 + 파일 메타
- [`docs/architecture/feature-opening-hours.md`](docs/architecture/feature-opening-hours.md) — 영업시간 DTO + DB
- [`docs/kraddr-base-types.md`](docs/kraddr-base-types.md) — `python-kraddr-base` 사용 기준
- [`docs/architecture/address-geocoding.md`](docs/architecture/address-geocoding.md) — 주소·좌표 보강 + match level
- [`docs/etl/weather-feature-normalization.md`](docs/etl/weather-feature-normalization.md) — weather 정규화 (forecast_style + timeline_bucket)
- [`docs/architecture/dagster-boundary.md`](docs/architecture/dagster-boundary.md) — Dagster 책임 경계
- [`docs/debug-fixture-workflow.md`](docs/debug-fixture-workflow.md) — fixture 저장/replay
- [`docs/architecture/feature-db-initialization.md`](docs/architecture/feature-db-initialization.md) — DB 부트스트랩
- [`docs/etl/event-feature-etl.md`](docs/etl/event-feature-etl.md) — VisitKorea 축제 ETL
- [`docs/etl/mois-feature-etl.md`](docs/etl/mois-feature-etl.md) — `python-mois-api` 활용 feature 적재 full lifecycle (Step A/B/C/D)
- [`docs/etl/mois-license-feature-etl.md`](docs/etl/mois-license-feature-etl.md) — MOIS 인허가 → place 승격 (Step B 좁은 가이드)
- [`docs/etl/opinet-place-price-etl.md`](docs/etl/opinet-place-price-etl.md) — OpiNet 주유소+유가 ETL
- [`docs/etl/khoa-beach-info-etl.md`](docs/etl/khoa-beach-info-etl.md) — KHOA 해수욕장 ETL
- [`docs/etl/krheritage-feature-etl.md`](docs/etl/krheritage-feature-etl.md) — 국가유산청 ETL
- [`docs/etl/forest-feature-etl.md`](docs/etl/forest-feature-etl.md) — 산림청 + 국립공원공단(KNPS) 통합 계획 (§11 = KNPS scaffold 반영)
- [`docs/etl/knps-feature-etl.md`](docs/etl/knps-feature-etl.md) — `python-knps-api` (`digitie/python-knps-api`) feature 적재 계약 (14 dataset, ADR-028)
- [`docs/etl/krex-rest-area-feature-etl.md`](docs/etl/krex-rest-area-feature-etl.md) — 도로공사 휴게소 ETL
- [`docs/etl/standard-data-feature-etl.md`](docs/etl/standard-data-feature-etl.md) — data.go.kr 표준데이터 5종 ETL
- [`docs/etl/notice-feature-etl.md`](docs/etl/notice-feature-etl.md) — 통합 notice ETL (4 provider)
- [`docs/etl/kma-weather-etl.md`](docs/etl/kma-weather-etl.md) — KMA weather ETL
- [`docs/etl/place-phone-enrichment.md`](docs/etl/place-phone-enrichment.md) — 장소 전화번호 보강
- [`docs/architecture/performance.md`](docs/architecture/performance.md) — 인덱스 설계 + 공간 쿼리 가이드 +
  bulk insert 룰
- [`docs/test-strategy.md`](docs/test-strategy.md) — 4단계 테스트 + 커버리지 목표
- [`docs/architecture/provider-contract.md`](docs/architecture/provider-contract.md) — wrapper 금지 + provider
  카탈로그
- [`docs/architecture/feature-model.md`](docs/architecture/feature-model.md) — Feature DTO 7 kind + detail
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
