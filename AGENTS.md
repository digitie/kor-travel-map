# AGENTS.md

## 문서 언어 정책

이 저장소의 모든 Markdown/RST 문서는 한국어로 작성한다. 공식 API 필드명, 코드 식별자,
명령어, URL, 라이브러리·제공자 원문, 환경변수처럼 그대로 보존해야 하는 값만 영어를
유지한다. 신규 문서와 기존 문서 모두 동일 규칙을 우선한다.

## 역할

이 저장소(GitHub 이름 `python-krtour-map`, Python 패키지 `krtour_map`)는 여러 한국
공공 API 라이브러리(`python-*-api`)에서 올라오는 여행 지도 데이터를 단일 `Feature`
계약으로 정규화·저장·조회·수정·삭제할 수 있게 하는 **TripMate 하부 라이브러리**다.

`python-krtour-map`은 TripMate에 **함수 라이브러리 형태**로 import되어 사용된다.
TripMate ↔ krtour-map 사이에는 REST API가 없다. 이 라이브러리가 자체적으로 노출하는
FastAPI 라우터(`api/`)는 **디버그 UI 전용 및 향후 내부 활용 목적**이며, 별도의 인증
키를 요구하지 않는다(내부망 전용, ADR-013 패턴).

이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. master(main)는 v2 사양으로 처음부터
다시 구현한다(ADR-001).

## 식별자 (혼동 방지)

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `python-krtour-map` |
| Python import | `from krtour_map import ...` |
| CLI 명령 (있다면) | `krtour-map ...` |
| 환경변수 prefix | `KRTOUR_MAP_*` |
| PostgreSQL DB 이름 (개발) | `krtour_map` (운영은 TripMate가 호스팅하는 공유 DB) |
| Postgres schema | `feature`, `provider_sync`, `ops` (TripMate 도메인 테이블과 분리) |
| PostGIS extension schema | `x_extension` (ADR-008) |
| 디버그 UI 패키지 | `krtour-map-debug-ui` (별도 Node.js — 옵션, v2 1차 범위 외) |

## 개발 환경 정책 (PC, WSL)

PC 개발은 **WSL ext4** 위에서 수행한다. NTFS 마운트에서 직접 `git`/`pip`/`uvicorn`을
실행하지 않는다 — 파일 권한, inotify, 심볼릭 링크, 대량 I/O 성능 모두 저하된다.

- **코드/가상환경**: ext4 (`~/dev/python-krtour-map/`).
- **데이터(`data/`)**: NTFS의 프로젝트 디렉토리 (예: `/mnt/f/dev/python-krtour-map/data/`).
  KRMOIS localdata zip, krheritage SHP, fixture 대용량은 모두 NTFS. ext4 작업
  디렉토리에는 심볼릭 링크(`ln -s /mnt/f/dev/python-krtour-map/data data`).
- **테스트**: 단위 테스트 픽스처는 소량을 ext4의 `tests/fixtures/`에. 통합/e2e와
  전수 검증은 NTFS의 `data/`를 reference.
- **카피 정책**: 작업이 끝나면 ext4 → NTFS로 rsync. Git의 source of truth는 ext4.

자세한 절차는 `docs/dev-environment.md`. Windows 재설치/WSL 초기화/새 세션 인수인계
시 `docs/windows-reinstall-recovery.md`도 함께 읽는다.

작업 전 반드시 다음을 읽는다:

1. `README.md` — 프로젝트 개요와 빠른 시작
2. `SKILL.md` — DO NOT 룰, 자주 묻는 작업, 도메인 어휘
3. `docs/architecture.md` — 의존 방향, 계층, 데이터 흐름
4. `docs/resume.md` — 현재 진척도와 "다음 한 작업"
5. `docs/decisions.md` — 관련 ADR
6. 이번 작업과 직결된 docs 항목 (provider 추가면 `docs/provider-contract.md` 등)

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

## 디버그 REST API 정책

라이브러리는 `krtour_map.api`에 FastAPI 라우터를 별도로 노출할 수 있다(옵션
extra `[api]`).

- **목적**: 디버그 UI 백엔드 + 향후 내부 도구 활용.
- **인증**: 별도 키 없음. 내부망(localhost / WSL / 사내망) 전제. 외부 노출 금지.
- **위치**: `src/krtour_map/api/` (ADR-016 미정 시 보류).
- **TripMate가 의존하지 않는다**. TripMate는 함수 직접 호출.

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
- Coverage 목표: **`core/` 90%+, `infra/` 80%+, `providers/` 70%+, 전체 80%+**.
- 모든 ETL provider 변환 함수는 fixture 기반 회귀 테스트 ≥3개 (정상/엣지/실패).
- 모든 raw SQL은 통합 테스트에서 EXPLAIN 결과로 `Index Scan` 또는 `Bitmap Heap
  Scan` 사용을 확인한다. 풀스캔 발견 시 PR block.
- 자세한 사양은 `docs/test-strategy.md`.

## 절대 하지 말 것 (DO NOT)

`SKILL.md` §4가 최신본이지만 핵심은 다음과 같다:

1. **의존 방향 역행 금지** — `dto → core → infra → providers → client → api`
   한 방향. `import-linter`가 CI에서 강제.
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
14. **디버그 API에 인증 추가 금지** — 내부망 전제. 외부 노출이 필요해지면
    네트워크 계층(SSO 게이트웨이/IP allowlist)에서 보호.
15. **데이터/원천 파일을 git에 커밋 금지** — `data/`는 `.gitignore`. NTFS에 보관.

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
python -m mypy src/krtour_map
lint-imports

# 통합 (PostGIS testcontainers 필요)
python -m pytest tests/integration -q

# 전체
python -m pytest -q
```

## 코드 작성 금지 (현 단계)

설계·문서화 단계 동안에는 `src/`, `tests/`, `alembic/`, `scripts/`에 코드를
작성하지 않는다. 별도의 코드 작성 요청이 있을 때까지 본 저장소는 문서·계약·결정의
저장소다. 단, 빈 패키지 마커(`pyproject.toml`, `py.typed`)는 패키지 구조를 잡기
위해 허용한다.
