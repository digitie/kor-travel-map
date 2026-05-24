# decisions.md — ADR (Architecture Decision Records)

이 문서는 `python-krtour-map`의 누적 ADR이다. 결정이 뒤집힐 때도 이전 기록은
지우지 않고 `superseded by ADR-XXX`로 표시한다. 각 ADR은 PR과 함께 커밋되어
코드/문서/결정이 동기된다.

## ADR-001: v1은 `v1` 브랜치 보존, main은 orphan v2로 재시작

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: v1은 9개월 운영하면서 provider 계약, RustFS, 디버그 UI, ETL
  helper, 광범위한 docs를 축적했지만 의존 계층/테스트 전략/성능 설계가
  ad-hoc하게 추가되어 일관성을 잃었다. v1을 그대로 발전시키기보다 SPEC V8 +
  `python-kraddr-geo` 디시플린에 맞춰 처음부터 다시 설계하는 게 빠르다.
- **결정**: 현재 main의 모든 commit을 `v1` 브랜치에 보존하고, main은
  `git checkout --orphan`으로 새 히스토리를 시작한다. `python-krtour-map-spec.docx`
  (저장소 루트 약 80쪽)는 v1 산출물과 SPEC V8 정합을 담은 reference로 둔다.
- **근거**:
  - v1 코드를 완전히 폐기하지 않음 — `v1` 브랜치 + spec docx로 복구 가능.
  - main은 git graph 어수선함 없이 깨끗하게 시작.
  - 새 에이전트가 main만 봐도 v2 의도가 명확.
- **결과 (긍정)**:
  - 의존 계층, 테스트, 성능 룰을 처음부터 일관되게 박을 수 있다.
  - v1의 부분 폐기/유지 결정을 ADR로 명시적으로 박는다.
- **결과 (부정)**:
  - main `git log`로는 직전 9개월 작업이 보이지 않는다 (`v1` 브랜치 참고 필요).
  - 일부 v1 코드를 v2에 가져올 때 cherry-pick 대신 재작성이 필요.
- **후속**: v2 코드 작성 시점에 v1 산출물을 ADR-006~ 와 함께 한 번에 평가.

## ADR-002: 의존 계층 강제 + async-only API

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: v1은 모듈 간 import 방향이 명시되지 않아 `infra` → `dto` 역참조,
  순환 import가 일부 발생했다. 동기/비동기 인터페이스도 혼재했다.
- **결정**:
  - 의존 방향 `dto → core → infra → providers → client → api/cli` 한 방향.
  - `import-linter` 계약으로 CI에서 강제.
  - 동기 인터페이스 신규 추가 금지. `AsyncKrtourMapClient`만. 호출자가
    `asyncio.run`으로 감싸야 하면 호출자가 책임.
- **근거**:
  - 계층 강제는 리팩토링 자유도를 높인다 (단위 테스트가 Protocol에만 의존).
  - async-only는 FastAPI/SQLAlchemy 2/httpx/asyncpg 스택과 정합.
  - `python-kraddr-geo` ADR-002와 동일 패턴.
- **결과 (긍정)**: 단위 테스트가 Fake repo로 100% 가능. 의존 그래프가 안정.
- **결과 (부정)**: 동기 호출자는 명시적으로 `asyncio.run`을 써야 한다.
- **후속**: `pyproject.toml`의 `[tool.importlinter]`에 계약 박힘. CI 워크플로에
  `lint-imports` 추가 (코드 작성 단계).

## ADR-003: TripMate ↔ 라이브러리는 함수 호출 (REST 없음)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: SPEC V8은 TripMate Admin / Dagster asset / API 라우터에서
  feature 데이터를 사용한다. 라이브러리를 별도 HTTP 서비스로 띄울지, 같은
  process에서 함수 호출할지 결정 필요.
- **결정**: TripMate는 본 라이브러리를 `pip install`하고 `AsyncKrtourMapClient`를
  함수 호출한다. HTTP는 사용하지 않는다.
- **근거**:
  - 두 코드베이스가 같은 운영 환경(Odroid 단일 노드)에서 동작.
  - HTTP layer overhead 없음, 직렬화/역직렬화 비용 없음.
  - DB connection pool/transaction 공유 가능.
  - Pydantic DTO를 그대로 주고받음 — 타입 안전성 유지.
- **결과 (긍정)**: 운영 단순화 + 성능 향상 + 디버깅 용이.
- **결과 (부정)**: 라이브러리 변경 시 TripMate 재배포 필요 (단일 venv).
- **후속**: 라이브러리는 자체 client/engine을 생성하지 않고 모두 주입받는다.

## ADR-004: ORM은 매핑만, 쿼리는 raw SQL `text()`

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: SQLAlchemy ORM의 query DSL은 PostGIS spatial 함수, window 함수,
  CTE, EXPLAIN 친화성에서 제약이 있다. `python-kraddr-geo`는 ADR-004로
  raw SQL repository 패턴을 채택했다.
- **결정**:
  - `infra/models.py`는 SQLAlchemy ORM 매핑(`Table` 객체 또는 declarative
    mapping)만 둔다. 비즈니스 로직 금지.
  - 모든 쿼리는 `infra/*_repo.py`의 `_SQL` 상수에 `sqlalchemy.text()`로 작성한다.
  - 파라미터는 named bind (`:radius_m`), 결과는 row → Pydantic DTO 변환.
- **근거**:
  - EXPLAIN 결과 그대로 재현 가능.
  - 인덱스 hint, `SET LOCAL`, CTE 자유 사용.
  - 통합 테스트에서 EXPLAIN 결과로 인덱스 사용을 검증 가능.
- **결과 (긍정)**: 성능 튜닝 자유도 + 통합 테스트 인덱스 검증 가능.
- **결과 (부정)**: 컬럼 변경 시 raw SQL 참조도 직접 수정 필요 (통합 테스트로
  방어).
- **후속**: `docs/performance.md`의 모든 쿼리 패턴에 `text()` 예시 포함.

## ADR-005: 디버그 REST API는 인증 없음, 내부망 전용

- **상태**: accepted (위치 부분은 ADR-020에서 superseded — 디버그 REST는 별도
  패키지 `krtour-map-debug-ui`에 둠. 인증 없음 + 내부망 전용 정책은 그대로)
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 라이브러리는 자체 FastAPI 라우터(`krtour.map.api`)를 옵션으로
  노출한다. 목적은 디버그 UI 백엔드 + 향후 내부 활용. TripMate는 이 API에
  의존하지 않는다 (ADR-003).
- **결정**: 디버그 API에 인증 키, JWT, OAuth 등 어떤 인증 로직도 추가하지
  않는다. 내부망(localhost, WSL, 사내망) 사용을 전제로 한다.
- **근거**:
  - `python-kraddr-geo` ADR-013과 동일 패턴 (디버그 UI 내부망 전용).
  - 라이브러리 코드/응답에 인증 로직이 침투하지 않음 → 코드 단순.
  - 외부 노출이 필요해지면 네트워크 계층(SSO 게이트웨이, IP allowlist,
    Cloudflare Tunnel)에서 보호.
- **결과 (긍정)**: 라이브러리 코드 단순화, 디버그 UI 개발 가속.
- **결과 (부정)**: 운영자가 잘못 외부에 노출하면 데이터 유출 위험.
  → 배포 가이드에서 `127.0.0.1` 바인드를 default로 강제.
- **후속**: `KRTOUR_MAP_DEBUG_API_HOST=127.0.0.1` default. 0.0.0.0 바인드 시
  경고 로그.

## ADR-006: provider adapter/wrapper 신규 생성 금지

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 §R-1)
- **컨텍스트**: v1에서 일부 provider에 대해 `*Wrapper`, `*Gateway`, `*Adapter`
  class를 시도했으나 결국 단순 전달 layer가 되어 유지보수만 늘었다. SPEC V8
  §R-1은 이를 명시적으로 금지한다.
- **결정**:
  - `python-*-api` provider 라이브러리의 public client와 typed model을 본
    라이브러리에서 직접 사용한다.
  - 부족한 endpoint, typed model, pagination, cursor, exception, raw payload
    보존 규칙은 해당 provider 라이브러리에서 먼저 안정화한다.
  - 본 라이브러리에서 허용되는 layer는 provider model → DTO 변환의 **순수
    함수**까지다. 클래스 wrapper 금지.
- **근거**: SPEC V8 §R-1, `python-kraddr-geo` AGENTS.md "제공자 API 사용 원칙".
- **결과 (긍정)**: 코드량 감소, provider 변경 시 변경 추적 명확.
- **결과 (부정)**: provider API 한계가 호출부에 그대로 노출됨. 단점이라기보다
  의도된 결과 — 한계는 provider 라이브러리에서 고친다.
- **후속**: `docs/provider-contract.md`에 wrapper 금지 원칙 + 허용 패턴 명시.

## ADR-007: 의존 스택 — Postgres + PostGIS + SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: `python-kraddr-geo`가 동일 운영 환경에서 PostgreSQL 16 +
  PostGIS 3.5 + SQLAlchemy 2 async + asyncpg + psycopg + GeoAlchemy2 +
  GeoPandas 조합으로 검증되어 있다. 본 라이브러리도 동일 스택을 채택해 운영
  환경을 일원화한다.
- **결정**: v2 의존 스택 확정.
  - DB: PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
  - ORM/SQL: SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
  - 공간: GeoPandas, Shapely 2, GDAL Python binding
  - 모델: Pydantic v2
  - HTTP (디버그 API): FastAPI + Uvicorn
  - HTTP client: httpx + tenacity
  - 마이그레이션: Alembic
  - Lint/Type: ruff + mypy --strict + import-linter
  - Test: pytest + pytest-asyncio + hypothesis + testcontainers-python + VCR.py
- **근거**: kraddr-geo와 환경/지식 공유, ARM64 cross-build 모두 검증됨.
- **결과 (긍정)**: 두 라이브러리의 운영자/에이전트가 같은 stack을 다룸.
- **결과 (부정)**: 신규 stack 도입(예: Polars)을 하려면 ADR 필요.
- **후속**: `pyproject.toml`에 의존성 반영. provider 라이브러리 git URL +
  commit sha 핀은 코드 작성 단계에서 ADR과 함께 확정.

## ADR-008: PostGIS extension은 `x_extension` schema에 격리

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (kraddr-geo ADR-018 미러)
- **컨텍스트**: TripMate 단일 DB에 `python-krtour-map`과 다른 도메인이 공존한다.
  PostGIS / pg_trgm / pgcrypto가 `public` schema에 설치되면 dump/restore,
  search_path 관리, schema 충돌이 복잡해진다.
- **결정**:
  - `CREATE SCHEMA IF NOT EXISTS x_extension;`
  - `CREATE EXTENSION postgis WITH SCHEMA x_extension;` (postgis_topology,
    pg_trgm, pgcrypto 동일).
  - 세션 `SET search_path = public, x_extension;` 또는 DSN options.
- **근거**: kraddr-geo ADR-018. dump/restore 안전성. schema 충돌 회피.
- **결과 (긍정)**: TripMate의 다른 라이브러리(`python-kraddr-geo` 등)와 같은
  DB에서 공존 가능.
- **결과 (부정)**: search_path 설정을 잊으면 `function st_makepoint does not
  exist` 같은 에러. 통합 테스트 setup에서 강제.
- **후속**: Alembic env에서 search_path 자동 설정. CI 통합 테스트 fixture에
  포함.

## ADR-009: `feature_id` 결정적 생성 (`make_feature_id`)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (SPEC V8 D-2)
- **컨텍스트**: 같은 source 데이터가 여러 번 적재되거나 여러 provider에서
  올라올 때 feature가 중복 생성되면 안 된다.
- **결정**:
  - 포맷: `f_{bjd_code}_{kind.value[0]}_{sha1(input)[:16]}`
  - input: `f"{bjd_code}|{kind.value}|{category.value}|{source_type}|{source_natural_key}"`
  - bjd_code 미상 시 `global` 사용.
  - 옵션 `content_hash`: payload 변경 시 새 feature 생성 (기본 None — 동일
    natural key는 같은 feature).
  - 항상 `make_feature_id(...)` 통과. raw string concat 금지.
- **근거**: SPEC V8 D-2 + v1 호환.
- **결과 (긍정)**: idempotent upsert 가능. 같은 입력 → 같은 ID.
- **결과 (부정)**: bjd_code가 변경되면 feature_id가 바뀜 (의도된 동작 — 행정구역
  개편 시 새 feature).
- **후속**: 단위 테스트에 SPEC V8 D-2 입력 예제 fixture 박음.

## ADR-010: weather — `forecast_style` + `timeline_bucket` 분리

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: Claude (v1 산출물 채택)
- **컨텍스트**: provider별 weather는 성격(nowcast/observed/index/advisory)과
  KMA식 조회 축(ultra_short/short/mid)이 직교한다. 한 컬럼에 합치면 조회
  복잡도가 폭발한다.
- **결정**:
  - `forecast_style ∈ {nowcast, ultra_short, short, mid, observed, index, advisory}`
  - `timeline_bucket ∈ {ultra_short, short, mid}` (조회 축, 분류 결과)
  - unique key에는 `forecast_style`만 포함, `timeline_bucket`은 제외.
- **근거**: v1 산출물 검증됨.
- **결과 (긍정)**: provider 다양성을 흡수 가능.
- **결과 (부정)**: 새 provider 추가 시 두 축 매핑 결정 필요 → ADR로 박는다.
- **후속**: `docs/weather-feature-normalization.md`에 provider별 매핑 표 유지.

## ADR-011: 작업 큐는 `import_jobs` 영속화 + advisory lock + SKIP LOCKED

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (kraddr-geo ADR-011 미러)
- **컨텍스트**: ETL 적재 작업 상태를 메모리에만 두면 프로세스 재시작 시
  진행 상황을 잃는다. SPEC V8 M-14의 `import_jobs` 테이블이 표준.
- **결정**:
  - `import_jobs(job_id UUID PK, kind, payload JSONB, state, progress,
    current_stage, source_checksum, error_message, started_at, finished_at,
    heartbeat_at, created_at)` 영속 테이블.
  - 상태 전이: `queued → running → done | failed | cancelled`.
  - lifespan startup 복구: `state='running'` 잔존 행 → 무조건 `failed` (heartbeat
    만료 가정). `state='queued'` → 자원 있으면 재큐잉, 없으면 `failed`.
  - 다중 워커 직렬: `pg_try_advisory_lock(ADVISORY_SLOT_IMPORT_QUEUE)` +
    `SELECT ... FOR UPDATE SKIP LOCKED`.
- **근거**: kraddr-geo ADR-011 운영 검증.
- **결과 (긍정)**: 재시작 안전성. 중복 실행 방지.
- **결과 (부정)**: Dagster 자체 영속 큐와 중복 가능 — 책임 경계 ADR-016에서
  분리.
- **후속**: `infra/jobs_repo.py` + Alembic migration + 통합 테스트.

## ADR-012: 공간 쿼리는 입력 좌표 1회 변환, 반경은 `coord_5179`(meter) 컬럼

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (kraddr-geo Critical 룰 11 미러)
- **컨텍스트**: `WHERE ST_DWithin(ST_Transform(f.coord_5179, 4326), :pt_4326,
  :radius_deg)` 같은 패턴은 매 행 변환을 일으켜 GIST 인덱스를 못 탄다.
- **결정**:
  - `features` 테이블에 `coord` (EPSG:4326)와 `coord_5179` (EPSG:5179, meter)
    두 컬럼 보유. `coord_5179`는 generated column 또는 trigger.
  - 반경 검색은 항상 `coord_5179`에 적용. `ST_DWithin(f.coord_5179, :pt_5179,
    :radius_m)`.
  - 입력 좌표는 CTE에서 한 번만 `ST_Transform`해 상수로 굳힌다.
  - 외부 인터페이스는 모두 `(lon, lat)` 순서. PostGIS `ST_MakePoint(lon, lat)`만.
- **근거**: kraddr-geo `docs/data-model.md` "공간 쿼리 가이드" 검증.
- **결과 (긍정)**: GIST 인덱스 사용 보장. 응답 시간 안정적.
- **결과 (부정)**: 컬럼 하나 추가 + Alembic migration 추가 작업.
- **후속**: `docs/performance.md`의 모든 공간 쿼리 예시에 패턴 박힘. 통합
  테스트에서 EXPLAIN으로 `Index Scan using idx_features_coord_5179_gist` 검증.

## ADR-013: bulk insert는 `psycopg.copy_*` 우선, 안전 마진 30k 파라미터

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (kraddr-geo SKILL.md §4-12 미러)
- **컨텍스트**: PostgreSQL 프로토콜은 한 쿼리당 최대 65,535개 파라미터.
  `INSERT ... VALUES (?, ?, ?)` × row 수가 이 한도를 넘으면 에러. v1에서 일부
  적재 path가 이 한도에 부딪혔다.
- **결정**:
  - row × column ≥ 30,000 가능성 있는 적재는 처음부터
    `psycopg.AsyncConnection.cursor().copy("COPY ... FROM STDIN")` 사용.
  - SHP/GeoJSON 적재는 `gdal.VectorTranslate(..., options=["-lco",
    "PG_USE_COPY=YES", "-lco", "FID=feature_id"])` 사용.
  - 안전 마진: 한도의 절반(30k) 권장.
- **근거**: kraddr-geo 운영 검증. `price_values`, `weather_values`, krheritage
  SHP가 직접 영향.
- **결과 (긍정)**: 대용량 적재 안정성. 메모리도 절감.
- **결과 (부정)**: `psycopg.copy_*`는 SQLAlchemy session과 별도 connection
  관리 필요 → repository 패턴 명시.
- **후속**: `docs/performance.md`에 표준 예시. `infra/bulk.py` helper.

## ADR-014: 테스트 4단계 + Coverage 목표

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 사용자 요청 "테스트케이스는 최대한 촘촘하고 다양하고 꼼꼼하게".
- **결정**:
  - `tests/unit/` — DB 없음, Fake repo. `pytest`, `pytest-asyncio`,
    `hypothesis`.
  - `tests/integration/` — testcontainers PostGIS (`postgis/postgis:16-3.5-alpine`).
  - `tests/e2e/` — 디버그 API + integration DB. `httpx.AsyncClient`.
  - `tests/fixtures/` — replay fixture (provider 호출 녹화/재생).
  - Coverage 목표: `core/ 90%+, infra/ 80%+, providers/ 70%+, 전체 80%+`.
  - 모든 raw SQL은 통합 테스트에서 EXPLAIN 결과로 인덱스 사용 검증.
  - 모든 provider 변환 함수는 fixture 기반 회귀 ≥ 3개 (정상/엣지/실패).
- **근거**: kraddr-geo 테스트 분리 패턴 + 사용자 요청.
- **결과 (긍정)**: 회귀 차단 + 성능 회귀 차단.
- **결과 (부정)**: 통합 테스트는 Docker 필요 → CI runner 정책 결정 필요.
- **후속**: `docs/test-strategy.md`에 상세 사양.

## ADR-015: 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 v8_0)
- **컨텍스트**: SPEC V8 v8_0은 RustFS(Apache 2.0, ARM64 공식 이미지)를 1차로
  선택했지만 MinIO/Ceph/AWS S3/Cloudflare R2 swap을 전제로 한다.
- **결정**: 라이브러리는 boto3 호환 S3 API만 사용한다. RustFS 고유 기능
  의존성 금지. 환경변수 `KRTOUR_MAP_OBJECT_STORE_*`로 어떤 backend든 주입
  가능.
- **근거**: SPEC V8 v8_0 + 향후 호스팅 변경 대비.
- **결과 (긍정)**: backend swap 자유. 테스트는 MinIO testcontainer로 가능.
- **결과 (부정)**: presigned URL, multipart upload, replication 같은 backend
  고유 기능 의존 금지 — 필요 시 backend 추상화 추가.
- **후속**: `infra/file_store.py`는 boto3 client만 받음. `docs/data-model.md`에
  `feature_files` 컬럼 정의.

## ADR-016: Record Linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 D-14)
- **컨텍스트**: 같은 장소가 여러 provider에서 다른 이름/좌표로 올라온다.
  자동 병합 vs 수동 검토 임계값이 필요.
- **결정**:
  - Blocking: `ST_DWithin(coord::geography, 100)` + 같은 `bjd_code` + 같은 `kind`
  - Scoring: `0.45 * name_sim + 0.35 * spatial_sim + 0.20 * category_sim`
    - name_sim: `jellyfish.jaro_winkler_similarity(normalize_kr_place_name(a), ...)`
    - spatial_sim: `math.exp(-haversine_m / 50.0)`
    - category_sim: Jaccard on category tag set
  - 임계값: `THRESHOLD_AUTO=0.85` (자동 병합), `THRESHOLD_MANUAL=0.65`
    (수동 검토 큐 `dedup_review_queue`).
  - 마스터 선정: (1) 좌표 정밀도 → (2) `updated_at` 최신 → (3) `source_type`
    우선순위 (행안부 > TourAPI > 사용자 등록).
  - `feature_merge_history(loser_id, master_id, score, merged_at)` 보존.
- **근거**: SPEC V8 D-14.
- **결과 (긍정)**: 자동/수동 흐름 명확. 운영자가 임계값 조정 가능.
- **결과 (부정)**: 가중치는 도메인 지식 기반 추정 — 운영 데이터로 재조정
  필요 시 ADR superseded.
- **후속**: `core/scoring.py`에 함수 박힘. 통합 테스트에 명시적 케이스.

## ADR-017: 보관 정책

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 D-12)
- **컨텍스트**: 데이터별 보관 기간 차이가 크다. 일률 정책은 DB 비대를 부른다.
- **결정**:
  - `place` — 무기한 (폐업 시 `status='inactive'`)
  - `event` — 종료일 +20년
  - `notice` — 종료일 또는 발표일 +1년
  - `price_values` — 카테고리별 기본 10년 (`price_points.retention_days`)
  - `weather_values` — 계획 기준일 +30일, 참조 trip 0건 시 즉시 삭제
  - `route` / `area` — 무기한
  - `source_records` — 대응 feature 보존 기간 이상
- **근거**: SPEC V8 D-12.
- **결과 (긍정)**: 운영 비용 통제. 사용자 가시 데이터 충분.
- **결과 (부정)**: purge job 필요 — Dagster asset로 위임.
- **후속**: `docs/data-model.md`에 정책 + purge SQL 표준 예시.

## ADR-018: `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기 강제)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: Claude (v1 산출물 보강)
- **컨텍스트**: v1은 `Feature.detail: dict | None`이라 자유 dict 우회 path가
  열려 있었다. 결과적으로 detail 필드 변경이 통제되지 않았다.
- **결정**:
  - `Feature.detail`은 `PlaceDetail | EventDetail | NoticeDetail | RouteDetail
    | AreaDetail` 중 하나의 Pydantic 인스턴스를 받는다.
  - DB write는 `.model_dump(mode='json')`만, read는 `DETAIL_MODELS[kind]
    .model_validate(...)`만.
  - 자유 dict 입력은 ValidationError.
- **근거**: Spec V8 D-3~D-12 + 통제 강화.
- **결과 (긍정)**: detail 필드 변경이 ADR과 함께만 가능.
- **결과 (부정)**: 새 필드 추가 시 마이그레이션 + DTO 동시 수정 필요.
- **후속**: 통합 테스트에서 free-dict 입력 케이스가 ValidationError로 끝나는지
  검증.

## ADR-019: KST aware datetime만 허용 (`kst_now()`)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: Claude (v1 산출물 채택)
- **컨텍스트**: v1은 일부 naive datetime이 DTO에 들어가 timezone 변환 버그가
  반복 발생했다.
- **결정**: 모든 datetime은 timezone aware (Asia/Seoul). 기본 생성은 `kst_now()`.
  naive datetime DTO 입력은 ValidationError.
- **근거**: 운영 안정성.
- **결과 (긍정)**: timezone 버그 사전 차단.
- **결과 (부정)**: provider 응답이 naive면 변환 책임 명시 — provider 모듈에서
  처리.
- **후속**: `dto/_base.py`의 KrtourModel에 `datetime` validator. 통합 테스트로
  검증.

## ADR-020: 디버그 UI는 별도 Python 패키지 (`krtour-map-debug-ui`)

- **상태**: accepted (ADR-005의 위치 부분을 supersede)
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: ADR-005에서 디버그 REST API를 본 라이브러리(`krtour.map.api`)
  안에 옵션으로 두는 것으로 설계했다. 하지만 다음 문제가 있다:
  - 본 라이브러리(`python-krtour-map`)가 FastAPI/Uvicorn 의존을 짊어진다.
    TripMate는 이미 자체 FastAPI를 가지고 있어 본 라이브러리에서 FastAPI를
    가져올 필요가 없다.
  - 함수 라이브러리(ADR-003)와 HTTP 서버가 같은 패키지에 섞이면 책임 경계가
    흐려진다.
  - 디버그 UI를 별도 배포/실행하기 어렵다 (라이브러리 import만 해도 FastAPI
    코드가 딸려 옴).
  - `python-kraddr-geo`는 `kraddr-geo-ui`를 별도 Node.js 패키지로 분리 운영
    중이다. 동일 패턴으로 일관성 확보.
- **결정**:
  - 디버그 REST API와 디버그 UI(있다면)를 별도 Python 패키지
    `krtour-map-debug-ui`로 분리.
  - 본 저장소 내 `packages/krtour-map-debug-ui/` 디렉토리에 패키지 소스를 둔다
    (monorepo 레이아웃, v1 동일).
  - 본 라이브러리(`python-krtour-map`)에서는 FastAPI/Uvicorn 의존성 제거.
    `[api]` extra 폐기. `src/krtour/map/`에 `api/` 폴더 두지 않음.
  - `krtour-map-debug-ui` 패키지가 `python-krtour-map`을 의존하고
    `AsyncKrtourMapClient`를 함수 호출로 사용한다.
  - 디버그 REST는 인증 없음, 내부망 전용 (ADR-005 인증 정책 그대로 유지).
- **근거**:
  - 함수 라이브러리와 HTTP 서버의 책임 분리.
  - 본 라이브러리 의존성 최소화 (FastAPI 등 미포함).
  - kraddr-geo와 동일한 모노레포 + 별도 패키지 패턴.
  - TripMate는 본 라이브러리만 import — 디버그 UI 코드/의존성에 영향받지 않음.
- **결과 (긍정)**:
  - 본 라이브러리 install footprint 축소.
  - 디버그 UI 자체적으로 버전 관리 / 배포 가능.
  - 디버그 UI에 Streamlit, Next.js bridge, 임의 frontend 도입이 본 라이브러리에
    영향 없음.
- **결과 (부정)**:
  - 패키지 2개 관리 부담 (pyproject 2개).
  - 디버그 UI는 본 라이브러리 버전을 따라가야 함 — release 동기 필요.
- **후속**:
  - `pyproject.toml`에서 `[api]` extra 제거.
  - `packages/krtour-map-debug-ui/pyproject.toml` 신규.
  - `docs/architecture.md`, `docs/backend-package.md`, `docs/debug-ui-package.md`
    갱신/신규.
  - `import-linter` 계약에서 `krtour.map.api` 제거.

## ADR-021: main에 직접 push 금지 — 모든 변경은 PR (branch + review)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: v2 진입 초기에 main 브랜치에 직접 commit + push가 두 번 발생했다
  (`fc8145f`, `304f2a9`). 작업이 빠르고 사용자 승인을 직접 받는 상황이라
  마찰이 적었지만, 다음 문제가 있다:
  - 검토 이력이 PR로 남지 않음 — 결정의 근거/대안/회신이 분산.
  - 다중 에이전트/사람이 동시 작업할 때 main 충돌 가능.
  - CI(검증, lint-imports, OpenAPI drift 등)가 main에 들어가기 전에 돌지 않음.
  - force-push 사고 가능성.
- **결정**:
  - main 브랜치에 직접 push 금지. `git push origin main` 차단.
  - 모든 변경은 feature branch에서 commit → push → `gh pr create` → 검토 →
    merge.
  - 브랜치 명명: `feat/<topic>` / `fix/<topic>` / `chore/<topic>` / `docs/<topic>` /
    `refactor/<topic>` / `adr/<short>`.
  - PR 제목 70자 이내. 본문은 PR 표준 포맷 (Summary, Test plan).
  - GitHub branch protection: main에 require PR review (1) + status checks
    (lint, test, lint-imports, openapi drift)이 통과해야 merge 가능. 운영 정책
    설정은 사용자/관리자 권한.
  - **예외 없음**. 핫픽스도 단명 branch를 통해.
  - 본 ADR 이전의 commit (`fc8145f`, `304f2a9`)은 ex post facto 인정 — main
    히스토리 보존. 본 ADR 이후 모든 변경은 PR.
- **근거**:
  - `python-kraddr-geo`의 실제 운영 관습과 정합 (그쪽도 PR 기반).
  - main을 always-deployable 상태로 유지.
  - 다중 에이전트(`agent/<id>`) 작업 시 main 손상 회피.
- **결과 (긍정)**:
  - 모든 결정이 PR 단위로 추적 — `gh pr view <num>`으로 한 번에 확인.
  - CI 검증이 main 진입 전에 발생.
  - 사용자 검토가 한 번에 묶임.
- **결과 (부정)**:
  - 작은 docs 한 줄 수정도 branch + PR 필요 (마찰 증가).
  - 단 1명의 PR 작성자/검토자가 같을 수 있어 self-approve 가능 — 의도된 운영
    모델 (실수 차단 목적이지 강제 4-eyes 아님).
- **후속**:
  - `AGENTS.md` DO NOT에 추가.
  - `SKILL.md` DO NOT에 추가.
  - `docs/agent-guide.md`에 PR 워크플로 절 추가.
  - `docs/windows-reinstall-recovery.md`의 handoff 노트에 PR 링크 필수화.
  - GitHub branch protection 설정은 운영자 수동 작업 — 이 ADR로 가이드만 박음.

## ADR-022: `krtour` implicit namespace + Python import path `krtour.map`

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 초기 v2 설계에서 Python import 이름을 `krtour_map`(flat)으로
  잡았다. 사용자가 `krtour.map`(namespace)로 변경을 지시. 근거:
  - `python-kraddr-geo`의 ADR-015가 `kraddr` implicit namespace(PEP 420)를
    채택. 동일 도메인의 다른 라이브러리(`kraddr-base`, `kraddr-geo`,
    `kraddr-...`)가 같은 namespace를 공유 → `kraddr.base`, `kraddr.geo`.
  - `krtour` namespace를 동일 패턴으로 채택하면 향후 `krtour.weather`,
    `krtour.poi` 같은 자매 라이브러리 추가 시 일관된 import 경로 확보.
- **결정**:
  - PyPI distribution 이름은 `python-krtour-map` (그대로 유지).
  - **Python import 이름**은 `krtour.map` (PEP 420 implicit namespace).
  - 디렉토리 layout: `src/krtour/map/__init__.py` (있음), `src/krtour/__init__.py`
    (**없음** — implicit namespace).
  - `pyproject.toml` `[tool.setuptools.packages.find]`에 `namespaces = true`,
    `include = ["krtour.map*"]`.
  - import-linter 계약의 모든 module 경로를 `krtour_map.*` → `krtour.map.*`로
    교체.
  - 환경변수 prefix는 `KRTOUR_MAP_*` 유지 (이름 일관성 — env는 underscore 표준).
  - CLI 명령 이름은 `krtour-map` 유지.
  - 별도 패키지 `krtour-map-debug-ui`(ADR-020)의 Python import는
    `krtour.map_debug_ui` (sibling under `krtour` namespace, 별도 distribution이
    같은 namespace를 공유). 디렉토리 layout: `packages/krtour-map-debug-ui/src/
    krtour/map_debug_ui/__init__.py`, `src/krtour/__init__.py` **없음**.
- **근거**:
  - kraddr 라이브러리 군과 패턴 정합.
  - 향후 자매 패키지 확장 자유.
  - PEP 420은 표준이며 setuptools/poetry/uv 모두 지원.
- **결과 (긍정)**:
  - 도메인 패키지 군이 통일된 namespace 사용.
  - 별도 distribution이 같은 namespace를 공유해도 충돌 없음.
- **결과 (부정)**:
  - 일부 IDE/타입체커가 implicit namespace에 약함 → mypy/pyright 명시적 path
    설정 필요할 수 있음.
  - `src/krtour/__init__.py`를 실수로 만들면 namespace가 깨짐 → CI에서 차단
    체크 (`tests/unit/test_no_namespace_init.py`).
- **후속**:
  - 모든 docs/code 예시 import path 갱신.
  - `pyproject.toml` `package-dir` / `packages.find` / `package_data` 갱신.
  - import-linter 계약 갱신.
  - 디렉토리 layout 가이드 (`docs/architecture.md`, `docs/dev-environment.md`).
  - 별도 패키지 `krtour-map-debug-ui`의 pyproject + README도 동일 패턴 적용.

## ADR-023: `python-kraddr-base`의 category 모듈을 `krtour.map.category`로 이전

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: v1까지는 `python-kraddr-base`의 `kraddr.base.categories`
  (`PlaceCategory`, `PlaceCategoryCode`, `get_category`, `iter_categories`,
  `mapbox_maki_icon_for_category` 등 ~2,072 줄)를 의존성으로 import해 사용했다.
  사용자가 본 category 코드/문서를 `python-krtour-map`으로 이전하라고 지시.
  근거:
  - category 데이터(141 enum + maki icon 매핑)는 TripMate 지도 도메인에 직접
    종속 — `python-krtour-map`이 1차 소비자.
  - 다른 라이브러리(`python-kraddr-geo` 등)는 category에 의존하지 않음 — 분리
    시 영향 없음.
  - kraddr-base는 주소/좌표/CRS 핵심에 집중되는 게 자연스럽다.
- **결정**:
  - `kraddr.base.categories` 모듈 전체를 본 저장소로 이전 → `krtour.map.category`
    (top-level subpackage, 다른 `dto`/`core`/`infra`와 sibling).
  - 공개 식별자 (전부 그대로 유지):
    - `PlaceCategory`, `PlaceCategoryCode`, `PlaceCategoryTier1Code`
    - `PLACE_CATEGORY_DEFINITIONS`, `PLACE_CATEGORY_BY_CODE`,
      `PLACE_CATEGORY_CODES`, `PLACE_CATEGORY_TIER1_NAMES`,
      `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1`,
      `PLACE_CATEGORY_MAPBOX_MAKI_ICONS`, `PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES`
    - `get_category`, `is_known_category_code`, `iter_categories`,
      `category_path`, `category_label`,
      `mapbox_maki_icon_for_category`, `mapbox_maki_icon_or_none`,
      `format_category_tree`, `print_category_tree`
  - `dto/feature.py`의 `Feature.category` 검증·정규화는 `krtour.map.category`를
    import해서 사용.
  - 의존 계층(`import-linter`)에 `krtour.map.category`를 `dto`보다 낮은 계층
    으로 추가 (`category → dto → core → infra → providers → client → cli`).
  - `python-kraddr-base`는 `Address`, `PlaceCoordinate`, `AddressRegion`,
    `Wgs84Point`, CRS 상수 등 **주소/좌표/CRS만** 제공 (그쪽에서 category 모듈은
    별도 deprecation cycle을 두든 그대로 두든 그쪽 결정 — 본 저장소는 자체
    구현).
  - 라이선스: kraddr-base와 본 저장소 모두 GPL-3.0-or-later → 호환. 이전 시
    파일 상단에 derivation 주석 + LICENSE에 origin 표기.
  - 단위 테스트(141 seed 검증)도 함께 이전 (`tests/unit/test_category.py`).
- **근거**:
  - 단일 소비자 패턴 — 코드/데이터를 사용자 위치에 두는 게 응집도 높음.
  - kraddr-base의 책임 축소 (주소/좌표만).
  - 본 라이브러리의 의존 그래프에서 외부 dep 1개 제거 (kraddr-base는 여전히
    필요하지만 category 모듈은 자체 보유).
- **결과 (긍정)**:
  - category 변경이 본 저장소 PR 단위로 통제.
  - 추가 dep 제거 (kraddr-base의 category-only path 끊김).
- **결과 (부정)**:
  - 코드 중복(전환 기간) — kraddr-base가 이전 즉시 본 모듈을 폐기하지 않으면
    잠시 두 copy 존재. 본 저장소는 자체 copy를 정본으로 본다.
  - kraddr-base release 변경 시 본 저장소도 동기 release 검토.
- **후속**:
  - 실제 코드 이전은 **코드 작성 단계 진입 시** 수행 (현 단계는 docs/계약만).
    별도 PR로 `krtour.map.category` 모듈 + 테스트 추가.
  - `docs/category.md` 신설 — 모듈 사양 + 라이선스/derivation 명기.
  - `docs/feature-model.md`, `docs/provider-contract.md`의 category 참조를
    `krtour.map.category`로 갱신.
  - `pyproject.toml`의 `dependencies`에서 kraddr-base는 유지 (주소/좌표 사용
    중) — 단, category submodule은 본 저장소가 정본.
  - `python-kraddr-base`에 대한 category 폐기/유지 결정은 그쪽 저장소 ADR로
    분리.

---

> 새 ADR을 추가할 때는 위 포맷을 따른다:
>
> - 번호: ADR-NNN (연번)
> - 상태: proposed | accepted | superseded by ADR-XXX
> - 날짜: YYYY-MM-DD
> - 결정자: <agent | human> 또는 둘 모두
> - 본문: 컨텍스트 / 결정 / 근거 / 결과(긍정) / 결과(부정) / 후속
>
> 기존 ADR을 뒤집을 때는 새 ADR을 추가하고, 옛 ADR의 상태를 `superseded by
> ADR-XXX`로 표시한다 — 기존 본문은 지우지 않는다.
