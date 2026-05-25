# AGENTS.md

## 문서 언어 정책

이 저장소의 모든 Markdown/RST 문서는 한국어로 작성한다. 공식 API 필드명, 코드 식별자,
명령어, URL, 라이브러리·제공자 원문, 환경변수처럼 그대로 보존해야 하는 값만 영어를
유지한다. 신규 문서와 기존 문서 모두 동일 규칙을 우선한다.

## 역할

이 저장소(GitHub 이름 `python-krtour-map`, Python 패키지 `krtour.map` — ADR-022)는 여러 한국
공공 API 라이브러리(`python-*-api`)에서 올라오는 여행 지도 데이터를 단일 `Feature`
계약으로 정규화·저장·조회·수정·삭제할 수 있게 하는 **TripMate 하부 라이브러리**다.

`python-krtour-map`은 TripMate에 **함수 라이브러리 형태**로 import되어 사용된다.
TripMate ↔ krtour-map 사이에는 REST API가 없다.

디버그 UI/REST는 **별도 Python 패키지** `krtour-map-debug-ui`로 분리되어 있다
(ADR-020). 본 monorepo 안의 `packages/krtour-map-debug-ui/`에 위치하고, 메인
라이브러리를 import해서 `AsyncKrtourMapClient`를 함수 호출한다. 별도 인증 키를
요구하지 않는다(내부망 전용, ADR-005).

이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. master(main)는 v2 사양으로 처음부터
다시 구현한다(ADR-001).

## 식별자 (혼동 방지)

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `python-krtour-map` |
| PyPI distribution | `python-krtour-map` |
| Python import (메인) | `from krtour.map import ...` (ADR-022, PEP 420 implicit namespace `krtour`) |
| Python import (디버그 UI) | `from krtour.map_debug_ui import ...` (별도 distribution, 같은 `krtour` namespace) |
| CLI 명령 (있다면) | `krtour-map ...` |
| 환경변수 prefix | `KRTOUR_MAP_*` (env는 underscore 표준 유지) |
| PostgreSQL DB 이름 (개발) | `krtour_map` (운영은 TripMate가 호스팅하는 공유 DB) |
| Postgres schema | `feature`, `provider_sync`, `ops` (TripMate 도메인 테이블과 분리) |
| PostGIS extension schema | `x_extension` (ADR-008) |
| 디버그 UI 패키지 | `krtour-map-debug-ui` (별도 **Python** 패키지, monorepo 내 `packages/krtour-map-debug-ui/`, ADR-020) |
| Category 모듈 출처 | `krtour.map.category` (구 `kraddr.base.categories`에서 이전, ADR-023) |
| ADR accepted | 001~026 (text on main) |
| ADR proposed | 027 (forest 카테고리/notice_type) / 028 (`python-knps-api` 등록) / 029 (`@krtour/map-marker-react` npm) / 030 (캐시 금지) / 031 (OpenAPI export) / 032 (Coverage schedule, 시기 의존) / 033 (`feature_consistency_reports`, 시기 의존) / 034 (provider 9단계 구현 순서) — 사용자 review → T-014 Sprint 1 진입 PR에 일괄 accepted 전환 예정 |
| Sprint plan | `docs/sprints/SPRINT-1.md` ~ `SPRINT-5.md` |
| Provider 구현 순서 (ADR-034) | 축제→날씨→유가→휴게소→국립공원/트래킹→국가유산→**MOIS**→휴양림/수목원→박물관/미술관 |

## 개발 환경 정책 (PC, WSL)

PC 개발은 **WSL ext4** 위에서 수행한다. NTFS 마운트에서 직접 `git`/`pip`/`uvicorn`을
실행하지 않는다 — 파일 권한, inotify, 심볼릭 링크, 대량 I/O 성능 모두 저하된다.

- **코드/가상환경**: ext4 (`~/dev/python-krtour-map/`).
- **데이터(`data/`)**: NTFS의 프로젝트 디렉토리 (예: `/mnt/f/dev/python-krtour-map/data/`).
  MOIS localdata zip, krheritage SHP, fixture 대용량은 모두 NTFS. ext4 작업
  디렉토리에는 심볼릭 링크(`ln -s /mnt/f/dev/python-krtour-map/data data`).
- **테스트**: 단위 테스트 픽스처는 소량을 ext4의 `tests/fixtures/`에. 통합/e2e와
  전수 검증은 NTFS의 `data/`를 reference.
- **카피 정책**: 작업이 끝나면 ext4 → NTFS로 rsync. Git의 source of truth는 ext4.

자세한 절차는 `docs/dev-environment.md`. Windows 재설치/WSL 초기화/새 세션 인수인계
시 `docs/windows-reinstall-recovery.md`도 함께 읽는다.

작업 전 반드시 다음을 읽는다:

1. `README.md` — 프로젝트 개요와 빠른 시작
2. `SKILL.md` — DO NOT 룰, 자주 묻는 작업, 도메인 어휘
3. `docs/sprints/README.md` — Sprint 1~5 계획 + ADR-034 9단계 순서
4. `docs/architecture.md` — 의존 방향, 계층, 데이터 흐름
5. `docs/resume.md` — 현재 진척도와 "다음 한 작업"
6. `docs/decisions.md` — 관련 ADR (특히 027~034 proposed)
7. 이번 작업과 직결된 docs 항목 (provider 추가면 `docs/provider-contract.md`,
   현재 sprint면 해당 `docs/sprints/SPRINT-N.md` 등)

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `SKILL.md`
4. `docs/architecture.md`, `docs/decisions.md`, `docs/data-model.md`,
   `docs/backend-package.md`, `docs/performance.md`, `docs/test-strategy.md`,
   `docs/agent-guide.md`, `docs/provider-contract.md`
5. `README.md` 및 나머지 `docs/`
6. 기존 코드와 테스트
7. 최소한의, 되돌릴 수 있는 가정

## TripMate ↔ python-krtour-map 경계

- **TripMate는 본 라이브러리를 `pip install`하고 함수로 호출한다**. HTTP는 사용하지
  않는다.
- 라이브러리는 `AsyncKrtourMapClient`(또는 동등 API)를 진입점으로 제공한다.
  TripMate의 FastAPI 라우터/Admin UI/Dagster asset body는 이 클라이언트의 메서드를
  직접 호출한다.
- 라이브러리는 SQLAlchemy 2 async engine과 (있다면) provider client 인스턴스를
  주입받는다. 라이브러리가 자체적으로 client/engine을 만들지 않는다.
- 라이브러리는 결과 DTO를 반환한다. 그 DTO를 어떤 HTTP 응답 셰입으로 감쌀지는
  TripMate 책임이다(SPEC V8의 `{"data": ..., "meta": ...}` 규약 적용은 TripMate).

## 디버그 REST API 정책 (ADR-005 + ADR-020)

디버그 REST는 **별도 패키지** `krtour-map-debug-ui`에 둔다. 메인 라이브러리
`python-krtour-map`은 FastAPI/Uvicorn 의존이 없다.

- **위치**: `packages/krtour-map-debug-ui/src/krtour/map_debug_ui/` (본 monorepo
  내, 별도 `pyproject.toml`).
- **목적**: 디버그 UI 백엔드 + 향후 내부 도구 활용.
- **인증**: 별도 키 없음. 내부망(localhost / WSL / 사내망) 전제. 외부 노출 금지.
- **메인 라이브러리 의존**: `pip install -e packages/krtour-map-debug-ui`만
  설치하면 `python-krtour-map`을 자동으로 의존성으로 가져간다.
- **TripMate는 의존하지 않는다** — TripMate는 메인 라이브러리만 import해서
  함수 직접 호출.
- `KRTOUR_MAP_DEBUG_UI_HOST` 기본 `127.0.0.1`. `0.0.0.0` 바인드 시 경고 로그.
- 자세한 사양은 `docs/debug-ui-package.md`.

## Provider API 사용 원칙

- 외부 API 관련 작업은 단순 전달용 wrapper/adapter/gateway 지양 원칙을 먼저
  확인하고 문서/코드에 반영한 뒤 진행한다.
- 본 라이브러리는 안정된 `python-*-api` public client와 typed model을 직접 사용한다.
  새 facade를 만들지 않는다. `KmaWrapper`, `GeoAdapter`, `OpiNetGateway` 같은
  계층 금지.
- 부족한 endpoint, typed model, pagination, cursor, exception, raw payload
  보존 규칙은 TripMate나 본 저장소에 임시 facade를 만들지 않고 해당
  `python-*-api` 저장소에서 먼저 안정화한다.
- 단순 전달용 alias도 만들지 않는다.
- 허용 경계: provider model → `Feature`, `SourceRecord`, `WeatherValue`,
  `PriceValue`로 바꾸는 순수 함수와 저장소 repository까지.

## 데이터 저장 원칙

- **Postgres 16 + PostGIS 3.5 + pg_trgm + pgcrypto**가 1차 저장소. 모든 공간/검색
  기능을 PostGIS와 pg_trgm으로 처리한다. SpatiaLite/SQLite 대안은 없다.
- **SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg**가 표준 스택. 동기 인터페이스는
  추가하지 않는다(ADR-002).
- **ORM 모델은 매핑만**. 쿼리는 `infra/*_repo.py`의 raw SQL (`sqlalchemy.text()`).
  EXPLAIN 친화 + 인덱스 hint 자유 (ADR-004).
- **이미지/문서/provider 첨부**는 DB에 직접 저장하지 않는다. S3 호환 객체 저장소
  (RustFS 우선, MinIO/Ceph/R2 swap)에 저장하고 `feature_files` 1:N 메타데이터.
- **공간 쿼리 술어에서 좌표 형변환 금지**. 입력 좌표는 CTE에서 한 번만
  `ST_Transform`해서 상수로 굳히고, 술어는 인덱스 있는 컬럼(`coord_5179` 등)을
  그대로 사용한다. 자세한 패턴은 `docs/performance.md`.

## 성능 설계 원칙 (설계 단계부터)

- 모든 신규 table은 **인덱스 설계를 ADR과 함께 결정**한다. "나중에 튜닝" 금지.
- 시계열 적재(`price_values`, `weather_values`)는 `observed_at`/`valid_at` 기준
  `BRIN` 인덱스 + 시간순 bulk insert.
- 65,535 파라미터 한도 초과 가능성 있는 bulk insert는 처음부터
  `psycopg.AsyncConnection.cursor().copy()` 패턴 사용. 안전 마진 30k.
- 작업 큐 상태는 `import_jobs` 테이블 영속화. in-memory 신뢰 금지.
- 자세한 가이드는 `docs/performance.md`.

## 테스트 정책 (촘촘하게)

- 테스트는 `tests/unit/` (Fake repo) + `tests/integration/` (testcontainers
  PostGIS) + `tests/e2e/` (디버그 API + integration DB) + `tests/fixtures/`
  (replay) 4단계.
- Coverage 목표 (최종): **`core/` 90%+, `infra/` 80%+, `providers/` 70%+,
  `dto/` 100% branch, 전체 80%+**. 단계적 상향 schedule은 **ADR-032**
  (Sprint 1 50% → Sprint 4 80% 도달, `docs/test-strategy.md §2`).
- 모든 ETL provider 변환 함수는 fixture 기반 회귀 테스트 ≥3개 (정상/엣지/실패).
- 모든 raw SQL은 통합 테스트에서 EXPLAIN 결과로 `Index Scan` 또는 `Bitmap Heap
  Scan` 사용을 확인한다. 풀스캔 발견 시 PR block.
- 자세한 사양은 `docs/test-strategy.md`.

## 절대 하지 말 것 (DO NOT)

`SKILL.md` §4가 최신본이지만 핵심은 다음과 같다:

1. **의존 방향 역행 금지** — 메인 패키지: `dto → core → infra → providers →
   client → cli` 한 방향. `import-linter`가 CI에서 강제. `krtour.map.api`는
   존재하지 않는다 (ADR-020 — 디버그 REST는 별도 패키지).
2. **동기 인터페이스 추가 금지** — `AsyncKrtourMapClient`만. 동기는 호출자가
   `asyncio.run`으로 감싼다 (ADR-002).
3. **`pg_trgm.similarity_threshold` 전역 변경 금지** — 트랜잭션 내부 `SET LOCAL`.
4. **ORM에 비즈니스 로직 금지** — `infra/models.py`는 매핑만. 쿼리는
   `infra/*_repo.py`의 raw SQL (ADR-004).
5. **좌표 순서 혼동 금지** — 외부 인터페이스는 모두 `(lon, lat)`.
   PostGIS도 `ST_MakePoint(lon, lat)`.
6. **카테고리/마커 매핑 하드코드 금지** — `category_mappings` DB 또는 settings.
7. **응답 셰입 임의 변경 금지** — 라이브러리 DTO는 `data/meta/error` 같은 HTTP
   래핑 키를 갖지 않는다. 래핑은 호출자 책임.
8. **외부 API 키 평문 커밋 금지** — 모두 `SecretStr`. `.env` 권한 600 또는
   systemd `EnvironmentFile`/vault.
9. **provider adapter/wrapper 신규 생성 금지** — public client 직접 사용.
10. **`feature_id` raw string concat 금지** — 항상 `make_feature_id(...)`.
11. **공간 쿼리 술어에서 `ST_Transform` 금지** — 인덱스 무효화.
12. **SQLAlchemy bulk `insert().values(rows)` 파라미터 폭주 금지** — 65,535 한도,
    안전 마진 30k. 초과 시 `psycopg.copy_*`.
13. **작업 큐 상태를 in-memory만 신뢰 금지** — `import_jobs` 영속화.
14. **디버그 API/UI 패키지에 인증 추가 금지** — 내부망 전제. 외부 노출이
    필요해지면 네트워크 계층(SSO 게이트웨이/IP allowlist/Cloudflare Tunnel)에서
    보호. 코드/응답에 인증 로직 침투 X.
15. **메인 라이브러리(`krtour.map`)에 FastAPI/Uvicorn import 금지** — ADR-020.
    HTTP 서버 코드는 `packages/krtour-map-debug-ui/`에만.
16. **데이터/원천 파일을 git에 커밋 금지** — `data/`는 `.gitignore`. NTFS에 보관.
17. **main에 직접 push 금지** — 모든 변경은 feature branch + PR (ADR-021).
    `git push origin main` 절대 금지. 핫픽스도 단명 branch를 통해. 브랜치 명명:
    `feat/<topic>` / `fix/<topic>` / `chore/<topic>` / `docs/<topic>` /
    `refactor/<topic>` / `adr/<short>`.
18. **`from krtour_map import ...` (flat) 사용 금지** — 항상 `from krtour.map
    import ...` (ADR-022). `src/krtour_map/` 디렉토리 만들지 말 것 —
    `src/krtour/map/`.
19. **`src/krtour/__init__.py` 만들지 금지** — PEP 420 implicit namespace.
    파일이 생기는 순간 `krtour-map-debug-ui` 같은 자매 distribution과 충돌.
    CI에서 차단 체크.

## 작업 후 체크리스트

- [ ] `pytest -q` (unit + integration 일부) 통과
- [ ] `ruff check .` / `mypy --strict` / `lint-imports` 통과
- [ ] `docs/journal.md`에 작업 항목 추가 (역시간순)
- [ ] `docs/resume.md`의 진척도 갱신
- [ ] 의사결정이 있었다면 `docs/decisions.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신
- [ ] DTO/스키마 변경이면 `scripts/export_openapi.py` 재실행
       (디버그 API 라우터 노출 시점부터 적용)

## 검증

```bash
# 단위 + lint
python -m pytest tests/unit -q
python -m ruff check .
python -m mypy src/krtour/map
lint-imports

# 통합 (PostGIS testcontainers 필요)
python -m pytest tests/integration -q

# 전체
python -m pytest -q
```

## 코드 작성 금지 (현 단계)

설계·문서화 단계 동안에는 `src/`, `tests/`, `alembic/`, `scripts/`에 코드를
작성하지 않는다. 별도의 코드 작성 요청이 있을 때까지 본 저장소는 문서·계약·결정의
저장소다.

**해제 시점**: 사용자가 **T-014 (Sprint 1 진입)** 승인 → Sprint 1 PR로 모든
proposed ADR (027/028/029/030/031/032/033/034) 일괄 accepted 전환 + `src/
krtour/map/` scaffolding 시작. 자세히는 `docs/sprints/SPRINT-1.md`.

**현재 상태 (Sprint 1 active, 2026-05-25)**: 코드 작성 단계 진입 완료.
PR#17부터 `src/krtour/map/` scaffolding 진행 중. Sprint 1 종료 시점에는
`category/`/`dto/`/`core/`/`infra/` 모든 layer가 채워져야 한다.

**Sprint 1 진행 중 가이드** (`docs/sprints/SPRINT-1.md` §2 참조):
- 모든 신규 코드는 `import-linter` 의존 방향 (`category → dto → core →
  infra → providers → client → cli`) 준수.
- `src/krtour/__init__.py`는 **절대 만들지 말 것** (PEP 420 implicit
  namespace, `tests/lint/test_no_namespace_init.py`가 차단).
- Sprint 1 coverage bar `fail_under = 50` (ADR-032).
- `dto/`는 Sprint 2부터 100% branch 강제.

**현재 박혀 있는 skeleton** (Sprint 1 PR#17~):
- `src/krtour/map/__init__.py` (PR#17) — `__version__` + 공개 API 주석
- `src/krtour/map/py.typed` (PR#17) — PEP 561 marker
- `src/krtour/map/settings.py` (PR#17) — `KrtourMapSettings` 최소
- `src/krtour/map/{category,dto,core,infra,providers,client}/__init__.py`
  (PR#17) — placeholder, 후속 PR에서 채움
- `tests/lint/test_no_namespace_init.py` (PR#17) — ADR-022 enforcement
- `tests/unit/test_smoke_import.py` (PR#17) — import + settings smoke
- `pyproject.toml` (PR#10/16) — import-linter 차단 계약 + coverage 50%
- `packages/krtour-map-debug-ui/scripts/export_openapi.py` (PR#10) —
  Sprint 2 첫 라우터부터 실효 (ADR-031)
- `packages/map-marker-react/` (PR#10) — Sprint 2 실 코드 (ADR-029)
- `packages/krtour-map-debug-ui/frontend/` (PR#6/11) — Sprint 2 실 코드
