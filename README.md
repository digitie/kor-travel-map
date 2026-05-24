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
- **Python import**: `from krtour_map import ...`
- **환경변수 prefix**: `KRTOUR_MAP_*`
- **PostgreSQL DB 이름 (개발)**: `krtour_map`
- **스키마 분리**: `feature`, `provider_sync`, `ops`, `x_extension`

## TripMate와의 연계

`python-krtour-map`은 TripMate에 **함수 라이브러리 형태**로 연결된다.
HTTP/REST가 아니다.

```python
from krtour_map import AsyncKrtourMapClient

async with AsyncKrtourMapClient(engine=tripmate_engine, providers=...) as client:
    features = await client.features_in_bounds(bbox, kinds=["place", "event"])
    weather = await client.build_weather_card(feature_id, asof=datetime.utcnow())
```

라이브러리가 자체적으로 노출하는 FastAPI 라우터(`krtour_map.api`)는 **디버그 UI
백엔드 + 향후 내부 활용 전용**이며 인증 키를 요구하지 않는다(내부망 전제).
TripMate ↔ 라이브러리 통신에는 사용하지 않는다.

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

# 의존성 (v2 코드 작성 단계 이후)
uv venv && uv pip install -e ".[dev,api,providers]"

# PostgreSQL + PostGIS (Docker)
docker compose up -d postgres

# 스키마 적용
alembic upgrade head

# (디버그) REST API 기동 — 인증 없음
uvicorn krtour_map.api.app:app --reload --port 8600
```

## 의존 스택 (v2 확정)

| 계층 | 라이브러리 |
|------|-----------|
| DB | PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto |
| ORM/SQL | SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 |
| 공간 처리 | GeoPandas, Shapely 2, GDAL Python binding |
| 모델 | Pydantic v2 |
| HTTP (디버그 API) | FastAPI + Uvicorn |
| HTTP client | httpx + tenacity |
| 마이그레이션 | Alembic |
| 주소/좌표 | `python-kraddr-base`, `python-kraddr-geo` |
| Provider client | `python-{visitkorea,krmois,opinet,krex,kma,khoa,airkorea,krforest,krheritage,kasi,datagokr,mcst,krairport}-api` |
| 객체 저장소 | S3 호환 (RustFS 우선) |
| Orchestration | Dagster (TripMate가 wiring; 라이브러리는 collect/load 순수 함수만 제공) |
| Lint/Type | ruff, mypy --strict, import-linter |
| Test | pytest, pytest-asyncio, hypothesis, testcontainers-python, VCR.py |

`python-kraddr-geo`와 동일한 스택을 의도적으로 채택했다 (운영 환경 통일,
ADR-007/008 참조).

## 디렉토리 (계획)

```
src/krtour_map/
  dto/         — pydantic v2 입력/출력 (DB/FastAPI 의존 없음)
  core/        — 비즈니스 로직 (Protocol에만 의존; make_feature_id, scoring, merge)
  infra/       — DB 어댑터 (SQLAlchemy 2 async + raw SQL + Alembic)
  providers/   — provider별 raw → DTO 변환 모듈 (wrapper 신규 생성 금지)
  client.py    — AsyncKrtourMapClient (라이브러리 진입점)
  api/         — FastAPI 라우터 (옵션, 디버그 UI 전용, 인증 없음)
  cli/         — typer CLI (옵션)
alembic/, sql/ — 스키마 마이그레이션과 DDL
tests/
  unit/        — Fake repo 기반
  integration/ — testcontainers PostGIS
  e2e/         — 디버그 API + integration DB
  fixtures/    — replay 회귀
docs/          — 사양·결정·작업 기록 (한국어)
data/          — 원천/픽스처 대용량 (NTFS, .gitignore)
```

의존 방향: **dto → core → infra → providers → client → api/cli** 한 방향.
`import-linter`가 CI에서 강제 (ADR-002, `docs/architecture.md`).

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
python -m mypy src/krtour_map
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
- [`docs/backend-package.md`](docs/backend-package.md) — 라이브러리 사양 + 디버그 API
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
각 기관 이용약관·저작권을 따른다(KMA, VisitKorea, KRMOIS, OpiNet, KREX, KHOA,
국가유산청, 산림청, AirKorea 등).
