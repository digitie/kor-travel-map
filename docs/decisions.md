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
    (현행 체인은 ADR-020으로 `api` 제거 + ADR-023으로 최하단 `category` 추가 →
    `category → dto → core → infra → providers → client → cli`. 본문은 채택 당시
    표기.)
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

- **상태**: accepted, **TripMate 연동/운영 배포 모델은 ADR-045로 superseded**
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
  단, TripMate와의 운영 연동은 2026-06-01 ADR-045 이후 함수 직접 호출이 아니라
  Docker로 운영되는 독립 krtour-map 프로그램의 OpenAPI 호출을 기준으로 한다.
  `AsyncKrtourMapClient`는 독립 프로그램 내부 구현과 단위/통합 테스트용 public
  Python API로 유지한다.

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
  패키지 `krtour-map-admin`에 둠. 인증 없음 + 내부망 전용 정책은 ADR-035
  amendment에서 "프로덕션 admin/관리 라우터로도 운영 가능"으로 확장 — 인증/
  네트워크 보호는 호출자(TripMate Cloudflare Tunnel/SSO 게이트웨이) 책임이라는
  근본 원칙은 그대로)
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 라이브러리는 자체 FastAPI 라우터(`krtour.map.api`)를 옵션으로
  노출한다. 목적은 디버그 UI 백엔드 + 향후 내부 활용. TripMate는 이 API에
  의존하지 않는다 (ADR-003).
- **결정**: 디버그 API에 인증 키, JWT, OAuth 등 어떤 인증 로직도 추가하지
  않는다. 내부망(localhost, WSL, 사내망) 사용을 전제로 한다.
- **Amendment (2026-06-02, ADR-045 D-1)**: ADR-045로 API가 TripMate(외부)에도
  서비스되지만 **코드에 인증 로직을 추가하지 않는 원칙은 유지**한다. 운영 인증은
  **infra 계층**(Cloudflare Tunnel SSO + IP allowlist)이 책임지고, TripMate 서비스
  토큰은 **`X-Krtour-Service-Token`** 헤더로 pass-through한다(앱은 검증하지 않고
  "인증된 요청만 도달"을 가정, 로그/감사만). reverse proxy에서 미인증 요청을 차단.
- **Amendment (2026-06-08, D-1 "B안" defense-in-depth)**: 운영 인증의 **1차 책임은
  여전히 infra 계층**이나, 그 위에 **얇은 앱 레벨 방어를 옵션으로** 더한다(네트워크를
  무조건 신뢰하지 않기 위함). `map_admin/auth.py`:
  - `service_token`(`KRTOUR_MAP_ADMIN_SERVICE_TOKEN`, opt-in) 설정 시 **service read
    엔드포인트 `POST /features/batch`**에서 `X-Krtour-Service-Token`을 **상수시간 비교**로
    검증(불일치/누락 → 401). 미설정이면 강제하지 않음(intranet/dev 하위호환). **공용 read
    surface(`/features` GET·`/categories`·`/providers`)는 브라우저 admin UI도 쓰므로 앱 토큰을
    강제하지 않는다**(operator는 proxy SSO). (`/tripmate/*` namespace는 제거됨 — krtour-map은
    TripMate 전용이 아니다; batch가 `/features/batch`로 일반화되며 route-level gate.)
  - `admin_destructive_enabled=False`(kill-switch) 시 파괴적 `/admin` 작업
    (restore/swap/deactivate/POI delete) 차단(403).
  - `APIKeyHeader`를 통해 OpenAPI `securitySchemes.ServiceToken`이 선언되고
    `POST /features/batch` operation에 `security`가 기록된다(계약 문서화, API 리뷰 P1 해소).
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
    ADR-045 T-205d 이후 batch DAG 연결용 `load_batch_id`, `parent_job_id` self-FK를
    추가했다.
  - 상태 전이: `queued → running → done | failed | cancelled`.
  - lifespan startup 복구: `state='running'` 잔존 행 → 무조건 `failed` (heartbeat
    만료 가정). `state='queued'` → 자원 있으면 재큐잉, 없으면 `failed`.
  - 다중 워커 직렬: `pg_try_advisory_lock(ADVISORY_SLOT_IMPORT_QUEUE)` +
    `SELECT ... FOR UPDATE SKIP LOCKED`.
- **근거**: kraddr-geo ADR-011 운영 검증.
- **결과 (긍정)**: 재시작 안전성. 중복 실행 방지.
- **결과 (부정)**: Dagster도 자체 내부 queue(RunRequest/asset materialization)를
  가질 수 있으나, **ADR-045 모델에서 `ops.import_jobs`가 1차 영속 큐이고 krtour-map
  소유 Dagster sensor가 이를 폴링·claim한다**(ADR-045 §5). (이전 "ADR-016에서 분리"
  표현은 오참조 — ADR-016은 Record Linkage.)
- **후속**: `infra/jobs_repo.py` + Alembic migration + 통합 테스트 (완료). ADR-045
  feature-update 큐(`ops.feature_update_requests`)가 import_jobs 위에 얹힌다
  (`docs/adr045-standalone-plan.md` §2).

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

## ADR-020: 디버그/admin UI는 별도 Python 패키지 (`krtour-map-admin`)

- **상태**: accepted (ADR-005의 위치 부분을 supersede. ADR-035 amendment에서
  "프로덕션 admin/관리/유지보수 UI"로 운영 범위 확장 — 패키지 분리 결정은
  유지. ADR-045에서 Docker 독립 프로그램의 API/admin UI 패키지로 운영 범위 확장)
- **Amendment (2026-06-01, ADR-045 D-9)**: 패키지를 `krtour-map-debug-ui` →
  **`krtour-map-admin`** 으로 rename(Python namespace `krtour.map_debug_ui` →
  `krtour.map_admin`, settings env prefix `KRTOUR_MAP_DEBUG_UI_` →
  `KRTOUR_MAP_ADMIN_`, frontend `krtour-map-admin-frontend`, openapi.json 경로
  이동). 역할이 "debug UI"를 넘어 admin/API 프로그램으로 확장된 것을 이름에 반영.
  라우터 prefix(`/debug` vs `/admin`·`/ops`·`/features`)는 그대로. 이 ADR 본문의
  옛 이름 표기는 새 이름으로 갱신됨.
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
    `krtour-map-admin`로 분리.
  - 본 저장소 내 `packages/krtour-map-admin/` 디렉토리에 패키지 소스를 둔다
    (monorepo 레이아웃, v1 동일).
  - 본 라이브러리(`python-krtour-map`)에서는 FastAPI/Uvicorn 의존성 제거.
    `[api]` extra 폐기. `src/krtour/map/`에 `api/` 폴더 두지 않음.
  - `krtour-map-admin` 패키지가 `python-krtour-map`을 의존하고
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
  - `packages/krtour-map-admin/pyproject.toml` 신규.
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
  - 별도 패키지 `krtour-map-admin`(ADR-020)의 Python import는
    `krtour.map_admin` (sibling under `krtour` namespace, 별도 distribution이
    같은 namespace를 공유). 디렉토리 layout: `packages/krtour-map-admin/src/
    krtour/map_admin/__init__.py`, `src/krtour/__init__.py` **없음**.
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
  - 별도 패키지 `krtour-map-admin`의 pyproject + README도 동일 패턴 적용.

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

## ADR-024: canonical provider name 정정 — `python-krmois-api` → `python-mois-api`

- **상태**: accepted (ADR-022의 식별자 표 및 provider-contract.md의 canonical name
  세부 정정. ADR-006/ADR-022의 큰 결정은 그대로 유지)
- **날짜**: 2026-05-24
- **결정자**: Claude (사용자 위임)
- **컨텍스트**: v1 산출물을 바탕으로 v2 docs를 작성하면서 행정안전부(MOIS)
  지방행정 인허가 OpenAPI 라이브러리를 `python-krmois-api` (`import krmois`)로
  표기했다. 실제 라이브러리 확인 결과:
  - PyPI distribution 이름: `python-mois-api`
  - Python import 이름: `mois`
  - GitHub: `digitie/python-mois-api`
  - pyproject.toml `project.name`: `python-mois-api`
  - README 명시: "설치 패키지 이름은 `python-mois-api`, import 패키지 이름은
    `mois`입니다"
  
  `krmois`는 본 라이브러리(v1) 내부에서만 쓰던 alias였고 실제 라이브러리에는
  존재하지 않음.

- **결정**:
  - canonical provider name: **`python-mois-api`** (변경)
  - Python import: `from mois import MoisClient` (변경)
  - `CANONICAL_PROVIDER_NAMES`에 `python-mois-api` 등록
  - `LEGACY_PROVIDER_ALIASES`에 다음 추가 (호환):
    - `"krmois"` → `"python-mois-api"`
    - `"mois"` → `"python-mois-api"`
    - `"pykrmois"` → `"python-mois-api"`
    - `"python-krmois-api"` → `"python-mois-api"` (이미 작성된 docs 호환)
  - 본 라이브러리에서 import path: `krtour.map.providers.mois` (ADR-022 namespace)
  - loader 모듈: `krtour.map.mois`
  - dataset_key prefix: `mois_*` (예: `mois_license_features`,
    `mois_license_features_bulk`, `mois_license_features_history`)
  - source_entity_type: `license_place` (변경 없음)

- **근거**:
  - 외부 라이브러리의 실제 이름과 일치 → 사용자/에이전트 혼동 방지
  - PyPI distribution 이름을 canonical로 사용하는 v2 표준(ADR-022)과 정합
  - `LEGACY_PROVIDER_ALIASES`로 v1 호환 유지 — 갑작스러운 BREAKING 회피

- **결과 (긍정)**:
  - import path와 PyPI 이름이 일치
  - 신규 에이전트가 `python-mois-api` GitHub repo를 바로 찾을 수 있음
  - alias로 점진 마이그레이션 가능

- **결과 (부정)**:
  - 기존 v2 docs (`docs/krmois-license-feature-etl.md`, `docs/provider-contract.md`,
    이전 ADR text 등)에 `python-krmois-api` 표기 남아 있음 → 본 ADR PR에서 일괄
    rename.
  - `docs/krmois-license-feature-etl.md` 파일명도 `docs/mois-license-feature-etl.md`로
    변경 또는 alias 유지 결정 필요 (본 ADR에서는 **파일명도 변경** — git mv).

- **후속**:
  - `docs/provider-contract.md` §2 (canonical names) + §3 (dataset_key) + §4
    (카탈로그) 갱신
  - `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
    (git mv) + 내용 정정
  - 새 `docs/mois-feature-etl.md`로 full lifecycle 통합 또는 license 전용 +
    full lifecycle 두 docs 유지 — 본 PR에서 후자 채택 (`mois-license-feature-etl.md`
    유지 + `mois-feature-etl.md` 신규 = 상위 개요 + 4단계 lifecycle).
  - 모든 신규/기존 docs의 `krmois.*` import 예시 → `mois.*`로 정정
  - PR description에 변경 요약

## ADR-025: 디버그 UI frontend는 `maplibre-vworld-js` 채택

> **현행 기준(2026-06-06)**: frontend는 **Next.js 16**(ADR-036 amendment 2026-05-31),
> dev 포트는 admin UI **9012**(ADR-047). 본문의 "Next.js 15"·"`next dev --port 8610`"
> 은 채택/2차 보강 당시 값이며 위 ADR이 정본이다.

- **상태**: accepted
- **날짜**: 2026-05-25
- **결정자**: 사용자
- **컨텍스트**: ADR-020으로 디버그 UI를 별도 패키지 `krtour-map-admin`로
  분리. FastAPI backend는 결정되었지만 frontend 기술 선택이 미정이었다.
  v1은 Kakao Maps JS SDK 사용. v2 후보:
  - Kakao Maps JS SDK (Canvas, JS key 필요, 일 호출 한도, 오프라인 캐싱 금지)
  - MapLibre GL JS + raster tile (OpenStreetMap 또는 VWorld raster 직접)
  - **MapLibre GL JS + `maplibre-vworld-js`** (`digitie/maplibre-vworld-js`,
    React/TS, WebGL 60fps, `MakiMarker` + cluster layer 내장, `zod` 좌표 검증,
    Next.js App Router 지원) — *실제 릴리스 버전 **v0.1.0**, npm 미게시(git
    URL+tag 핀). 결정 당시 추정한 v1.0.0은 ADR-036 amendment(2026-05-28)로 정정.*

  사용자가 maplibre-vworld-js 채택을 지시.

- **결정** (2차 보강 적용 — Vite → Next.js):
  - 디버그 UI frontend: **Next.js 15 (App Router) + React 19 + TypeScript +
    `maplibre-vworld` + `maplibre-gl` + `zod`**. (1차 결정의 "Vite"는 2차
    보강으로 정정 — 본 ADR 하단 §사용자 보강 2차 참조).
  - VWorld 지도 (국토교통부) — **Kakao Maps SDK 사용 안 함**.
    `NEXT_PUBLIC_KAKAO_JS_KEY` 같은 변수 미사용.
  - 마커: `MakiMarker` (kraddr-base / `krtour.map.category` maki icon 55종과
    정합) + `MarkerClusterer` (10만+ feature viewport culling + KDBush).
  - 라이선스: `maplibre-vworld` ISC license + `maplibre-gl` BSD-3 + 본 라이브러리
    GPL-3.0 호환.
  - 디렉토리: `packages/krtour-map-admin/frontend/` (`python-kraddr-geo`의
    `kraddr-geo-ui` 패턴 미러).
  - 빌드: Next.js (2차 보강 — 1차의 Vite에서 정정). 개발 `next dev --port 8610`
    (kraddr-geo-ui와 동일 stack). 운영은 `next build` + standalone /
    FastAPI proxy / static export 중 선택 (`debug-ui-package.md §14.3`).
  - 백엔드 API 경유: 환경변수 `NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API` (Next.js
    rewrites 또는 fetch base URL).
  - SPA로 충분 — SSR 불필요 (디버그 UI는 내부망 전용).
  - 인증 없음 (ADR-005 + ADR-020 그대로). VWorld API key만 frontend에 안전하게
    전달 (key restriction by HTTP referrer).
- **근거**:
  - **VWorld 우선**: 국토교통부 공식 지도. 한국 행정구역 경계·도로명주소
    레이어와 정합. `python-kraddr-geo`와 동일한 source.
  - **WebGL 렌더링**: 10만+ feature (MOIS 인허가, krheritage, opinet 주유소
    등)을 Canvas 기반보다 부드럽게 60fps 렌더링.
  - **선언형 React**: `map.panTo()` 같은 명령형 API 없음 → Props 조작만으로
    상태 동기 (디버그 콘솔에서 feature 클릭 → 지도 이동 단순).
  - **MakiMarker 내장**: 본 라이브러리의 `krtour.map.category` maki icon
    매핑(55종)을 그대로 활용.
  - **클러스터링 내장**: viewport culling + KDBush로 zoom-level별 마커 자동
    합치기 — 본 라이브러리의 `cluster_unit` (`sido`/`sigungu`/`eupmyeondong`)
    개념과 정합.
  - **TypeScript**: openapi-typescript로 본 라이브러리 디버그 REST와 타입 동기
    가능.
  - **kraddr-geo-ui 패턴 일관**: 운영자/에이전트 학습 비용 절감. (2차 보강에
    따라 Next.js stack 통일 — 1차의 Vite 가설보다 정확.)
- **결과 (긍정)**:
  - 한국 운영 환경(VWorld, 행정구역, 도로명주소)에 정합.
  - kraddr-geo-ui 및 TripMate `apps/web`와 같은 frontend stack (Next.js +
    React + TS, 2차 보강) → 형제 라이브러리 + 상위 app 운영 일관성.
  - Kakao 호출 한도 / JS key 발급 부담 없음.
  - 대용량 feature 렌더링 성능 우수.
  - maki icon이 본 라이브러리 category 체계와 자동 정합.
- **결과 (부정)**:
  - VWorld API key 필요 — `python-kraddr-geo` ADR-019의
    `KRADDR_GEO_VWORLD_API_KEY` **공유** (별도 발급 X, 사용자 결정 2026-05-25).
  - 디버그 UI 운영자는 React/Next.js/TypeScript 기본 지식 필요 (운영자는 한
    명 이상이라 학습 부담 있음 — 단 TripMate `apps/web` 운영 학습이 그대로
    이전됨).
- **사용자 보강 (2026-05-25, 1차)**:
  1. **VWorld API key 공유 정책 확정**: 디버그 UI는 `python-kraddr-geo`의
     `KRADDR_GEO_VWORLD_API_KEY`를 **공유 사용**. 별도 발급 / 별도 환경변수
     금지. frontend는 backend가 주입한 값을 `NEXT_PUBLIC_VWORLD_API_KEY`로
     노출 (이름은 Next.js 규약 — 2차 보강으로 정정, 값은 동일 출처). HTTP
     referrer 제한은 backend가 서빙하는 호스트(`127.0.0.1` + 내부망 운영
     호스트)로 통일.
  2. **maplibre-vworld-js 유지보수 정책**: provider 라이브러리에서 문제
     발생 시 `digitie/maplibre-vworld-js` 저장소에 **직접 PR로 적극 수정**.
     본 사용자가 직접 운영하는 저장소이므로 stability 우려는 "외부 의존"이
     아닌 "관리 부담"으로 분류 — wrapper 도입(ADR-006 위배) 대신 upstream
     수정으로 해소. 이로써 `maplibre-vworld` (v0.1.0) 채택의 부정적 결과
     "stability 모니터링 필요" 항목은 **해소됨**.
- **사용자 보강 (2026-05-25, 2차) — 빌드 도구 정정 Vite → Next.js**:
  3. **디버그 UI frontend = Next.js (App Router)**. 1차 결정의 "React + Vite"
     는 잠정 가설이었고, **kraddr-geo-ui** 및 **TripMate `apps/web`**(ADR-026)
     이 모두 Next.js이므로 **단일 stack 통일**을 위해 Next.js로 정정.
     - 빌드: `next build` → `.next/`. 운영 옵션 3가지 (standalone /
       FastAPI reverse proxy / static export — `debug-ui-package.md §14.3`).
     - 개발: `next dev --port 8610 --hostname 127.0.0.1` (포트 8610은 TripMate
       `apps/web` dev (3000) 충돌 회피).
     - Env 규약: `NEXT_PUBLIC_*` 만 브라우저 노출. `VITE_*` 미사용. 1차 결정의
       `VITE_VWORLD_API_KEY` / `VITE_KRTOUR_MAP_ADMIN_API`는 각각
       `NEXT_PUBLIC_VWORLD_API_KEY` / `NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API`
       로 정정.
     - 본 패키지 `@krtour/map-marker-react` (ADR-029)는 React 19 라이브러리로
       framework-agnostic. Next.js의 `transpilePackages`로 monorepo workspace
       에서 직접 import.
     - **근거**: (1) kraddr-geo-ui와 동일 stack — 학습 비용 0. (2) TripMate
       `apps/web`와 동일 stack — 운영자가 두 UI 사이 학습 부담 0. (3) App
       Router의 server actions / streaming SSR은 본 디버그 UI는 read-mostly
       이라 미필요하지만, 향후 server-side admin 기능 (SQL EXPLAIN bulk,
       fixture management 등) 확장 시 유용.
- **후속**:
  - `docs/debug-ui-package.md` 갱신 — frontend 디렉토리/기동/Env/마커 매핑
    + key 공유 정책 §14.2 + **Next.js 기반으로 §14.3 운영 옵션 (standalone /
    proxy / export) 명기**.
  - `packages/krtour-map-admin/README.md` 갱신.
  - `packages/krtour-map-admin/frontend/` skeleton — Vite 가정의
    `package.json`/`README`/`.env.example`/`.gitignore`를 **Next.js로 일괄
    전환** + `next.config.js` 신설 (본 PR#11에서 완료).
  - 환경변수 prefix: `NEXT_PUBLIC_*` (Next.js 규약).
  - VWorld API key 발급 절차는 `docs/external-apis.md` 갱신 (공유 정책 +
    Next.js env 명기).
  - `docs/forest-feature-etl.md` §11.6의 "ADR-025 후보" 카테고리 확장은 번호
    충돌 회피로 **ADR-027 후보**로 변경 (ADR-026은 TripMate UI 통일 ADR이
    선점).

## ADR-026: TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8 v8_3 supersede)

- **상태**: accepted
- **날짜**: 2026-05-25
- **결정자**: 사용자
- **컨텍스트**: ADR-025로 본 라이브러리의 **디버그 UI** frontend는
  `maplibre-vworld` 채택. 그러나 상위 app TripMate의 **사용자 가시 지도 UI**
  (SPEC V8 v8_3 spec)는 Kakao Maps JS SDK를 사용하도록 명시되어 있었다.
  두 개의 다른 지도 stack을 유지하면:
  - frontend 운영 비용 2배 (Kakao + VWorld 양쪽 학습/디버깅).
  - category maki icon 매핑 코드가 두 곳에 산재.
  - 좌표 변환·proj4·KAKAO_ID vs VWorld coord 정합 부담.
  - Kakao JS key 호출 한도와 모니터링 분리.

  사용자가 "둘 다 바꿈"으로 지시 — TripMate 사용자 UI도 `maplibre-vworld`
  통일.

- **결정**:
  - **TripMate `apps/web` 사용자 가시 지도 UI도 `maplibre-vworld` 채택**.
  - SPEC V8 v8_3의 "Kakao Maps JS SDK" 섹션은 **superseded** — TripMate 측
    spec에 본 ADR 링크 박음.
  - 두 UI(본 라이브러리 디버그 UI + TripMate 사용자 UI)는 동일 frontend
    stack (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`).
  - 마커 / category maki icon 매핑 로직은 npm 패키지로 추출 후보
    (`@krtour/map-marker-react`, 추후 ADR로 결정) — 두 UI에서 import.
  - VWorld API key는 TripMate 사용자 UI도 동일하게 `KRADDR_GEO_VWORLD_API_KEY`
    공유 (또는 TripMate 사용자 환경의 동일 출처 키). 운영자 키와 사용자
    프런트 키는 referrer 제한으로 분리 권장.
  - Kakao Maps JS SDK 의존 / `NEXT_PUBLIC_KAKAO_JS_KEY` 등 관련 변수 일괄
    제거 (TripMate 측 후속 PR).

- **근거**:
  - **단일 stack 운영**: 한 frontend stack(React + Vite + TS +
    maplibre-vworld)으로 디버그 UI와 사용자 UI 양쪽 운영 — 학습/디버깅 비용
    절감.
  - **VWorld 일관성**: 본 라이브러리·`python-kraddr-geo`·디버그 UI·TripMate
    UI 모두 VWorld 단일 source — 좌표·행정구역·도로명주소 시각화 정합.
  - **호출 한도 일원화**: Kakao JS SDK 일 호출 한도 모니터링 불필요. VWorld
    referrer 제한만 관리.
  - **maki icon 단일 매핑**: `krtour.map.category` Tier 1~4 → maki icon
    매핑 1회로 두 UI 공통 (추후 npm 패키지 추출).
  - **WebGL 성능**: 10만+ feature 렌더링은 디버그 UI뿐 아니라 사용자 UI에서도
    이점 (예: "주변 100km 내 모든 옵셈 주유소" 같은 시나리오).
  - **사용자 직접 지시 + 본 사용자가 maplibre-vworld-js를 직접 관리** — 결정
    번복 리스크 낮음.

- **결과 (긍정)**:
  - frontend stack 일원화 (React + Vite + TS + maplibre-vworld).
  - category maki icon 매핑 단일화 가능.
  - VWorld key 일원화 (Kakao key 발급/회전/모니터링 제거).
  - 본 라이브러리의 디버그 UI 학습이 TripMate 운영 학습으로 직결.

- **결과 (부정)**:
  - TripMate `apps/web`의 기존 Kakao Maps 코드 제거/대체 PR 필요 (TripMate
    저장소 측 작업, 본 저장소 외).
  - SPEC V8 v8_3의 Kakao Maps 의존 섹션 supersede 표기/링크 필요.
  - 본 라이브러리는 wrapper 도입하지 않음(ADR-006) — TripMate 측이 본 라이브러리
    debug-ui frontend의 컴포넌트를 직접 import할 수 없으므로, 공통 마커 패키지를
    별도 npm 패키지로 추출하는 ADR이 추가 필요 (후속).

- **후속**:
  - TripMate 저장소에 본 ADR 링크하는 supersede 표기 PR (TripMate 측 작업).
  - SPEC V8 v8_3 문서에 "superseded by python-krtour-map ADR-026" 추가
    (SPEC 저장소 측 작업).
  - `docs/tripmate-integration.md` 갱신 — 사용자 UI도 maplibre-vworld
    사용 명기, Kakao 의존 제거.
  - 공통 마커/카테고리 매핑 npm 패키지 추출 ADR (후속, ADR-028~ 후보).
  - `docs/external-apis.md` §8 비용 관리에서 Kakao Maps JS SDK 항목 제거
    또는 "TripMate UI 통일 이후 미사용"으로 표기.
  - `docs/category.md` §4 maki icon 매핑은 두 UI 공통 reference 명기.

## ADR-027: forest 카테고리 확장 (대피소 PlaceCategory, hazard_zone area, 일반화된 notice_type)

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (notice_type 일반화)
- **컨텍스트**: `docs/forest-feature-etl.md §11` (KNPS data.go.kr 통합)에서
  7건의 분류 확장 후보가 도출됨 (대피소 / 위험지역 / 산악관측소 / 식생서식지 /
  area_kind=hazard_zone / 입산통제 / 산불경보). 각 후보는 PlaceCategory /
  area_kind / notice_type 어디에 속하느냐, 위치가 어디여야 하느냐가 미정.
  코드 작성 단계 진입 전에 분류 정책을 박지 않으면 T-018(`python-knps-api`
  provider 등록) 시점에 매 케이스마다 재협상.

  사용자 결정 (2026-05-25): 입산통제/산불경보를 forest 도메인에 묶지 말고
  **일반화** — 산림(KNPS/산림청) 외 해변(KHOA), 도로(KREX), 도시(공사현장)
  등에서도 재사용 가능한 generic notice_type으로.

- **결정**:

  **A. 신규 PlaceCategory** — `LODGING_MOUNTAIN_SHELTER` 1건 (Tier 2 신설):

  | 코드 | enum name | 한국어 | maki icon |
  |------|-----------|--------|-----------|
  | `03080000` | `LODGING_MOUNTAIN_SHELTER` | 대피소·산장 | `shelter` |
  | `03080100` | `LODGING_MOUNTAIN_SHELTER_KNPS` | 국립공원 대피소 | `shelter` |
  | `03080200` | `LODGING_MOUNTAIN_SHELTER_KFS` | 산림청 산장 | `shelter` |

  - Tier 1 enum (`PlaceCategoryTier1Code`)은 그대로 8개 유지 — Tier 1 신설
    없음.
  - `03 LODGING` 하위 새 Tier 2 (휴양림 `03.03`과 의미 분리 — 휴양림은
    휴양 목적, 대피소는 안전/일시 휴식).
  - maki icon: `shelter` (Maki 표준에 존재).

  **B. 신규 `area_kind`** — `hazard_zone` 1건:

  ```python
  # AreaDetail.area_kind enum 확장 (feature-model.md §9)
  area_kind: Literal[
      "area", "national_park", "provincial_park", "recreation_forest",
      "tourism_district", "beach", "campsite", "heritage_area",
      "natural_heritage_area", "buried_heritage_area",
      "hazard_zone",                        # NEW (ADR-027)
      "other",
  ]
  ```

  - 위험지역(낙석/급류/멧돼지 출몰 등)은 시설(place)이 아닌 **지역(area)**.
    Feature `kind=area`, AreaDetail.area_kind=`'hazard_zone'` +
    `payload.hazard_type` (e.g. `'rockfall'`, `'flash_flood'`, `'wildlife'`)
    + polygon geometry.
  - 별도 PlaceCategory(`SAFETY_*` 또는 Tier 1 `08 SAFETY`) 신설 **하지
    않는다** (B-1 사용자 거부 사유: 새 Tier 1은 광범위 영향 — 모든 ETL/UI
    매핑 변경 필요, 위험지역은 area로 표현이 본질적으로 정확).

  **C. 신규 `notice_type`** — `access_restriction` + `fire_alert` 2건
  (**generic 명명**, 사용자 결정):

  ```python
  # docs/notice-feature-etl.md §3 NOTICE_TYPES 확장
  NOTICE_TYPE_ACCESS_RESTRICTION = "access_restriction"   # NEW (ADR-027)
  NOTICE_TYPE_FIRE_ALERT         = "fire_alert"           # NEW (ADR-027)
  ```

  - `access_restriction`: 입산통제(KNPS) / 해수욕장 폐장(KHOA) / 공원 폐쇄
    / 공사 통제 / 등산로 통제 등 **출입 제한** 통칭.
  - `fire_alert`: 산불경보(KNPS/산림청) + 향후 화재 관련 일반 경보.
  - 명칭에서 `forest_` prefix 제거 — 산림 외 적용 가능. provider 출처/세부
    구분은 `payload`에 (`payload.domain='forest'`, `'beach'`, `'urban'` 등).
  - `normalize_notice_type` alias 추가:
    | 입력 | 출력 |
    |------|------|
    | `"입산통제"`, `"입산제한"`, `"forest_access"` | `access_restriction` |
    | `"해수욕장폐장"`, `"beach_closure"` | `access_restriction` |
    | `"공사구간"`, `"construction_zone"` | `access_restriction` (선택, road_closure와 구분) |
    | `"산불경보"`, `"forest_fire"`, `"fire"` | `fire_alert` |
    | `"화재경보"` | `fire_alert` |

  **D. 거부/연기**:

  - **`SAFETY_*` PlaceCategory 신설**: 거부 (B 결정으로 area_kind으로 대체).
  - **`WEATHER_MOUNTAIN_STATION` PlaceCategory 신설**: 거부. `kind=weather`
    feature 자체가 분류 역할 + meta `station_type='mountain'` 충분. 디버그
    UI에서 maki icon dispatch는 fallback `viewpoint` 또는 `observation-tower`
    매핑으로 처리.
  - **`NATURE_ECOLOGY` PlaceCategory 신설**: 연기 (v2 1차 범위 밖). 식생/
    서식지 학술 데이터는 TripMate 사용자 노출 가치 낮음. 향후 분석 도구에서
    KNPS 원본 dataset 직접 사용 권고.

- **근거**:
  - **kind 분리 정신 (feature-model.md)**: 시설은 place, 지역은 area, 안내는
    notice. SAFETY를 PlaceCategory에 넣는 건 이 정신 위배.
  - **Tier 1 변경 회피**: PlaceCategoryTier1Code는 enum + maki + 모든 ETL
    매핑 + 디버그 UI에 광범위 영향. Tier 2 추가는 한 행 추가로 마무리.
  - **generic notice_type**: 산림 외 도메인(해변/도로/도시)에서 동일 의미를
    표현해야 할 때 `forest_access_restriction`은 잘못된 이름. `payload.
    domain`으로 출처 구분이 정확.
  - **사용자 직접 결정 (일반화)**: 사용자가 forest prefix 제거를 명시
    지시 — provider별 prefix 없는 generic notice_type 패턴은 기존
    `road_closure` / `heavy_rain_warning` / `coastal_isolation` 등과
    일관.

- **결과 (긍정)**:
  - 대피소가 PlaceCategory로 명확히 분류 → 디버그 UI 마커 + 검색 필터 자연.
  - 위험지역이 area로 표현 → polygon geometry + radius 검색 자연 (place
    point보다 정확).
  - generic notice_type → 향후 새 provider(해변 폐장/도시 공사 등) 추가 시
    이름 재협상 0회.
  - Tier 1 enum 그대로 → 기존 매핑/디버그 UI 영향 0.

- **결과 (부정)**:
  - `LODGING_MOUNTAIN_SHELTER`는 03.03 (휴양림)과 인접 → "산림 시설" 묶음
    인지 차원에서 약간 혼동 여지. category.md에 의미 차이 명기로 완화.
  - `access_restriction`은 기존 `road_closure`와 의미 일부 겹침 — road_closure
    는 *도로*, access_restriction은 *지역/시설* 접근 제한. category.md /
    notice-feature-etl.md에 사용 가이드 명기.

- **후속**:
  - `docs/category.md` §4: `03.08` Tier 2 + Tier 3 두 행 추가 (Tier 1 표는
    변경 없음).
  - `docs/notice-feature-etl.md` §3: `NOTICE_TYPE_ACCESS_RESTRICTION` /
    `NOTICE_TYPE_FIRE_ALERT` 추가 + `normalize_notice_type` alias 표 확장
    + §7 마커 스타일 표에 maki icon/color 추가.
  - `docs/feature-model.md` §9: AreaDetail.area_kind에 `hazard_zone` 추가.
  - `docs/data-model.md` §3: `feature_area_details.area_kind` CHECK 제약
    (있다면) 갱신.
  - `docs/forest-feature-etl.md` §11.6: 본 ADR 링크 + Phase별 결정 사항으로
    정리 (현재의 "후보" 표 정리).
  - 코드 작성 단계에서:
    - `PLACE_CATEGORY_DEFINITIONS`에 3행 추가 + `PLACE_CATEGORY_MAPBOX_MAKI_ICONS`
      에 매핑.
    - `NOTICE_TYPES` tuple + `normalize_notice_type` validator + 마커
      스타일 helper 갱신.
    - `AreaDetail.area_kind` Literal 확장 + DB CHECK 제약 갱신 (alembic).
  - T-018 (`python-knps-api` provider 등록, ADR-028 후보)와 한 sprint
    안에서 함께 진행 권고.

## ADR-030: 라이브러리 in-memory 캐시 금지 (immutable 카탈로그 예외)

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `docs/performance.md §9.1`에 이미 "in-memory 캐시 두지 않는다"
  방침이 박혀 있으나, 정식 ADR로 격상되지 않았다. 코드 작성 단계에서 누군가
  "이 hot path는 캐시하면 빠르지 않나"라고 시작하면 매번 review에서 같은 논쟁
  반복. 정식 ADR + `import-linter` 계약으로 차단해 두는 게 협상 비용을
  영구히 제거한다.
- **결정**:
  - **본 라이브러리(`krtour.map`)는 in-memory 캐시를 두지 않는다**. `core/`
    / `infra/` / `providers/` / `client/` 어디에도 `cachetools` /
    `async-lru` / `aiocache` / 수동 `dict` 캐시 금지.
  - **Narrow 예외 (모듈 레벨 `functools.cache` 한정 허용)**:
    1. `krtour.map.category` Tier 1~4 PlaceCategoryCode 카탈로그 (144건,
       릴리스 단위 immutable).
    2. `pyproj.Transformer` CRS 변환 인스턴스 — `Transformer.from_crs(...)`
       는 본질적으로 immutable + thread-safe, 모듈 레벨 singleton 보관.
    3. 위 두 예외는 모두 **데이터 mutability 0** 이어야 한다 — feature/
       place_detail/file_object 등 mutable 데이터는 절대 금지.
  - **`import-linter` 계약 추가** (`pyproject.toml`):
    ```toml
    [[tool.importlinter.contracts]]
    name = "main package must not depend on cache libraries"
    type = "forbidden"
    source_modules = ["krtour.map"]
    forbidden_modules = ["cachetools", "async_lru", "aiocache", "diskcache"]
    ```
- **근거**:
  - **stateless function library (ADR-003)**: 호출자(TripMate)는 multi-worker
    uvicorn으로 동작. 워커별 캐시 일관성 깨짐 → silent stale data.
  - **invalidation 책임 분리**: 캐시 무효화는 비즈니스 lifecycle (요청/세션)
    에 종속. 라이브러리가 책임지면 invalidation API가 library → caller로
    역전 → ADR-001 의존 방향 위배.
  - **EXPLAIN 기반 latency 측정 정직성**: 캐시 layer가 있으면 첫 호출과 N번째
    호출 latency가 다름 → P99 SLO 측정 무의미 + 회귀 추적 어려움.
  - **호출자(TripMate) 측 캐시는 자유**: Redis/in-process LRU를 TripMate가
    `apps/api`에 두는 건 ADR 범위 밖. 캐시 키 설계와 무효화 책임은 TripMate가
    가져간다.
- **결과 (긍정)**:
  - 모든 hot path latency가 DB query latency = EXPLAIN 검증 통합 테스트
    (`docs/performance.md §10`)가 곧 SLO 보증.
  - multi-worker / 컨테이너 재시작 시 cache warm-up 비용 0.
  - 새 코드 작성 시 "이거 캐시할까" 협상 0회.
- **결과 (부정)**:
  - PlaceCategoryCode 같은 hot lookup이 모든 호출마다 모듈 로드 시 한 번
    채워진 카탈로그를 참조 — `functools.cache`로 충분히 빠르지만, 위 narrow
    예외가 늘어나려는 압력이 발생할 수 있음. ADR을 명시적으로 좁게 박아
    예외 확장을 차단.
- **후속**:
  - `docs/performance.md §9.1`에 본 ADR 링크 + narrow 예외 명기.
  - `pyproject.toml`에 import-linter 계약 추가 (코드 작성 단계 진입 시).
  - `tests/lint/test_import_linter.py` — 본 계약 회귀 테스트 (코드 작성
    단계).

## ADR-031: 디버그 패키지 OpenAPI export 정책 (첫 라우터부터 활성화)

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **Amendment (2026-06-02, ADR-045 D-3)**: ADR-045로 API가 admin과 TripMate(사용자)
  양쪽에 서비스되므로 OpenAPI를 **이원화**한다 — admin schema(`/admin`·`/ops`·
  `/debug`·`/features` admin 뷰)와 사용자 schema(`/features` 공개 뷰, `tripmate-rest-
  api.md`)를 **별도 export + 별도 drift gate**(CI 2개). versioning은 **SemVer**
  (필드 추가=minor / 제거·의미변경=major, breaking 시 구버전 한동안 유지),
  CHANGELOG `### API` 섹션에 변경 기록(D-16). frontend client는 `openapi-typescript`
  codegen(D-4).
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `packages/krtour-map-admin`가 FastAPI 라우터를 노출하면
  OpenAPI spec (`openapi.json`)이 자동 생성된다. 이를 저장소에 커밋하고
  drift gate를 두는 정책은 `kraddr-geo` ADR-015 패턴이 있으나, 본 저장소는
  *언제* 활성화할지 미정. 활용 측은 (1) 디버그 UI frontend `openapi-typescript`
  → `src/api/types.ts` 생성, (2) 운영자/에이전트 API spec 참조, (3) 외부
  도구(curl/postman) 검증.

- **결정**:
  - **첫 FastAPI 라우터 등장 PR부터 즉시 활성화** (Sprint 1, 메인 라이브러리
    코어 ETL이 아직 부분 구현이어도 무관).
  - `packages/krtour-map-admin/openapi.json`과
    `packages/krtour-map-admin/openapi.user.json`을 저장소에 커밋.
  - `packages/krtour-map-admin/scripts/export_openapi.py` 신설 (이미
    `docs/debug-ui-package.md §8`에 사양 박힘).
  - `.github/workflows/openapi.yml` — admin/user 이원 `--profile all --check` drift 게이트:
    ```yaml
    - run: python packages/krtour-map-admin/scripts/export_openapi.py \
             --profile all --check
    ```
  - 라우터/DTO/디버그 패키지 의존성 변경 PR은 반드시 `openapi.json` 또는
    `openapi.user.json` diff 동반 — 누락 시 CI fail.
  - 메인 라이브러리(`krtour.map`)는 FastAPI 미의존(ADR-020)이라 본 ADR
    범위에 들어오지 않음. **항상 디버그 패키지 한정**.

- **근거**:
  - **활성화 비용 cheap**: 스크립트 ~30줄 + workflow ~10줄.
  - **frontend 도입 시점 부채 회피**: frontend가 도입되기 전부터 drift gate가
    돌고 있으면, frontend 첫 PR에서 `npm run gen:types`가 깨끗하게 동작 →
    type drift 회귀 0회.
  - **운영자/에이전트 진입 비용 절감**: 저장소에 `openapi.json`이 박혀 있으면
    backend 미기동 상태에서도 API 표면 확인 가능 (Swagger Viewer 등).
  - **kraddr-geo 패턴 일관**: 형제 라이브러리 운영 일관성.

- **결과 (긍정)**:
  - 라우터 변경의 외부 효과(frontend type / 외부 도구)가 PR diff에서 즉시
    가시화.
  - 디버그 UI frontend 도입 시 type drift 부담 0.
  - 외부 운영자가 spec을 PR diff로 review 가능 (코드 + spec이 한 PR에).

- **결과 (부정)**:
  - 라우터 PR마다 `openapi.json` 갱신 강제 — 운영자가 잊을 수 있음. CI 게이트
    + agent-guide 체크리스트에 명기로 완화.

- **후속**:
  - `packages/krtour-map-admin/scripts/export_openapi.py` 작성 (코드 작성
    단계).
  - `.github/workflows/openapi.yml` 신설 (T-203 일부).
  - `docs/agent-guide.md` §체크리스트에 "라우터 변경 시 `openapi.json` 갱신"
    추가.
  - `docs/debug-ui-package.md §8` + `§14.6`에 본 ADR 링크 + drift gate 명기
    (현재 "kraddr-geo ADR-015 패턴 미러"로만 표기됨).

## ADR-032: Coverage 단계적 상향 일정 (Sprint 1 → Sprint 5)

- **상태**: accepted (T-014 Sprint 1 진입과 동시 확정, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `docs/test-strategy.md §2`에 최종 coverage 목표(core 90% /
  infra 80% / providers 70% / client 80% / api 70% / dto 100% / 전체 80%
  branch)가 박혀 있고 "단계적으로 상향"이라고만 표기. 실제 schedule이 박혀
  있지 않으면 매 PR마다 "이번엔 얼마?" 협상 → CI fail 빈도와 PR 사이클 시간
  늘어남.

- **결정 (Sprint별 `fail_under` schedule)**:

  | Sprint | 전체 (branch) | `core/` | `providers/` | `infra/client/api/` | 비고 |
  |--------|---------------|---------|--------------|---------------------|------|
  | Sprint 1 (scaffolding) | 50% | 60% | 50% | 50% | 코드 자체가 적음 — bar 형식적 |
  | Sprint 2 (core + 첫 provider 4건) | 65% | 75% | 55% | 60% | core 우선 |
  | Sprint 3 (provider 절반 + infra) | 75% | 85% | 65% | 70% | provider 확장 |
  | Sprint 4 (integrity + edge cases) | **80%** | **90%** | **70%** | **80%** | 목표치 도달 |
  | Sprint 5 (operational entry) | 유지 + 회귀 방지 | 유지 | 유지 | 유지 | 신규 코드만 incremental check |

  - `pyproject.toml`의 `[tool.coverage.report] fail_under`를 Sprint별 PR로
    상향 (한 줄 변경 + journal 엔트리).
  - 단계 상향 PR은 항상 **coverage gap 해소 PR과 묶음** — gap을 먼저 채운
    후 bar를 올린다 (반대 순서는 PR이 red로 시작).
  - `dto/` 100% branch는 **Sprint 2부터 항상 강제** (Pydantic validator는
    line 수 적고 critical).

- **근거**:
  - **초기 강제는 prototype iteration 방해**: 첫 PR이 80% 강제면 5줄 추가에
    mock 30줄 — 의미 없는 snapshot 남발.
  - **마지막 spurt는 실효성 없음**: 마지막 Sprint에 몰아 채우면 happy path
    snapshot만 늘고 edge case 누락.
  - **bar가 박혀 있으면 협상 0회**: 매 PR이 "이번 sprint의 bar를 넘었나"만
    확인.
  - **dto는 예외**: line이 적고 validator branch가 곧 비즈니스 룰 — 처음부터
    100% 강제가 합리적.

- **결과 (긍정)**:
  - 단계별 quality gate가 명시적 → PR review 협상 비용 0.
  - Sprint 4에 목표 도달 → Sprint 5는 운영 진입 + 회귀 방지에 집중 가능.
  - 단계 상향 PR이 항상 gap 해소 PR과 묶이므로 red main 0회.

- **결과 (부정)**:
  - Sprint 일정이 변동되면 schedule도 변동 — 본 ADR을 update하는 부담.
  - Sprint 1의 50% bar는 형식적이라 "왜 있는가" 비판 가능 → 본 ADR이 "초기
    bar는 형식이지만 단계 상향의 anchor 역할"이라고 명기.

- **후속**:
  - `docs/test-strategy.md §2`에 본 ADR 링크 + Sprint별 표 그대로 옮김.
  - 코드 작성 단계 진입 결정(T-014) PR에 본 ADR을 묶어 `proposed` →
    `accepted` 전환 + Sprint 일정 확정.
  - 단계 상향 PR template: "Sprint N coverage bar 상향 + gap 해소".

## ADR-033: `feature_consistency_reports` 단계적 도입 (Sprint 3~4: F1~F3, Sprint 5: F4~F8 + 게이트)

- **상태**: accepted (T-014 Sprint 1 진입과 동시 확정 — Phase 1은 Sprint 3, Phase 2는 Sprint 5에 코드 적용, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `kraddr-geo` ADR-017 미러로 `ops.feature_consistency_reports`
  + batch DAG 게이트가 T-201로 잡혀 있음 (`docs/dagster-boundary.md §12`).
  F1~F8 케이스는 `python-krtour-map-spec.docx` B.18에 정의. 도입 시점이
  미정 — Sprint 5 운영 진입 직전에 몰아넣으면 게이트 자체가 Sprint 5 일정
  리스크, 너무 일찍 도입하면 schema가 미성숙 상태에서 굳어짐. 그러나
  정합성 검증 없이 Sprint 5 운영 진입은 silent data corruption 후 발견 비용
  폭증.

- **결정 (두 단계로 분할)**:

  **Phase 1 (Sprint 3~4, T-201a)** — 스키마 + critical 3건:
  - `ops.feature_consistency_reports` 테이블 마이그레이션:
    ```sql
    CREATE TABLE ops.feature_consistency_reports (
      report_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
      batch_id UUID NOT NULL,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      finished_at TIMESTAMPTZ,
      severity_max TEXT NOT NULL CHECK (severity_max IN ('OK','WARN','ERROR')),
      cases JSONB NOT NULL,         -- case별 결과 array
      summary JSONB NOT NULL        -- 집계: total/by_severity/by_kind
    );
    CREATE INDEX idx_reports_batch ON ops.feature_consistency_reports (batch_id);
    CREATE INDEX idx_reports_started ON ops.feature_consistency_reports (started_at DESC);
    ```
  - **F1**: `SourceRecord`가 있는데 `Feature`가 없음 (orphan source — ETL
    transform 실패 누수). severity=ERROR.
  - **F2**: `Feature.kind='place'` 인데 `PlaceDetail` 행 없음 (detail 누락 —
    ADR-018 위배). severity=ERROR. 다른 kind도 동일 패턴.
  - **F3**: `Feature.coord_5179 ≠ ST_Transform(coord, 5179)` (CRS drift —
    ADR-012 위배 / generated column 신뢰 손상). severity=ERROR.
  - Dagster 게이트는 **미적용** — 검증만 하고 mv_refresh swap은 차단 안 함.
    Phase 1은 "보이게 만들기" 목적.

  **Phase 2 (Sprint 5 운영 진입 직전, T-201b)** — 나머지 + Dagster 게이트:
  - **F4**: `dedup_review_queue` 미해소 N건 초과. severity=WARN.
  - **F5**: provider별 `last_success`가 SLA(예: 24h) 초과. severity=WARN.
  - **F6**: `opening_hours` 모순 (start > end, ADR-019 위배). severity=ERROR.
  - **F7**: cross-provider dedup mismatch (record linkage 점수 회귀 — Sprint
    별 baseline 대비 N% 이상 하락). severity=WARN.
  - **F8**: `file_object` orphan (RustFS object 존재 + DB feature 없음 / 그
    반대). severity=WARN.
  - **Dagster 게이트 적용** (`dagster-boundary.md §12`): root → child 적재 →
    `consistency_check` 실행 → `severity_max != ERROR` 시 `mv_refresh
    strategy='swap'`. ERROR 시 알림 + swap 차단.

- **근거**:
  - **스키마 비용 cheap**: 테이블 정의 + 인덱스 2개 → 초기 마이그레이션에
    함께 박는 게 alembic revision 비용 절감.
  - **F1~F3는 cheap + critical**: 단순 SQL이고 high-value. 첫 부트스트랩에서
    잡힘 — 누락 시 며칠 후 dedup 검토 큐에서 발견 = too late.
  - **F4~F8은 비용 더 큼**: cross-provider dedup score baseline 필요 (F7),
    file_object orphan 검사는 RustFS 스캔 비용 (F8) — Sprint 5에 묶는 게
    구현 비용 정직.
  - **Dagster 게이트는 Phase 2로**: Phase 1에서 게이트까지 박으면 첫 ERROR가
    swap 차단 → 운영 학습 곡선이 너무 가파름. Phase 1은 "관측", Phase 2는
    "차단".

- **결과 (긍정)**:
  - Sprint 5 운영 진입 시점에는 F1~F8 + 게이트 완성 → silent corruption 0.
  - F1~F3을 Sprint 3~4에 박아 두면 코드 작성 단계 내내 회귀 감지.
  - 스키마는 Sprint 3 초기에 박혀 있으므로 F4~F8 추가는 행 추가만 — alembic
    revision 1개로 끝.

- **결과 (부정)**:
  - Phase 1 시점에는 게이트 미적용 → 검증 결과를 운영자가 직접 확인해야
    함 (디버그 UI `/integrity` 페이지 또는 `feature_consistency_reports`
    direct SQL).
  - Phase 2에서 게이트 켤 때 첫 운영 batch가 F4~F8 위반으로 일제히 fail
    가능 — Phase 2 도입 PR은 반드시 dry-run report 첨부 후 점진 enable.

- **후속**:
  - `docs/test-strategy.md`에 F1~F8 케이스별 통합 테스트 매트릭스 추가.
  - `docs/dagster-boundary.md §12`에 본 ADR 링크 + Phase 1/Phase 2 분할 명기.
  - `docs/postgres-schema.md`에 `ops.feature_consistency_reports` 테이블
    정의 추가 (Phase 1 마이그레이션 시점).
  - 코드 작성 단계 진입 결정(T-014) PR에 본 ADR을 묶어 `proposed` →
    `accepted` 전환 + T-201을 T-201a (Phase 1) / T-201b (Phase 2)로 분할.

- **Amendment (2026-05-29, Sprint 3) — Phase 1 (T-201a) 구현 완료**:
  - `alembic 0003_feature_consistency_reports` — `ops.feature_consistency_reports`
    테이블 + `idx_reports_batch` / `idx_reports_started` (PK
    `x_extension.gen_random_uuid()`; T-RV-13에서 schema-qualified default로 정정).
  - `infra/models.py` `FeatureConsistencyReportRow` (Alembic target_metadata).
  - `infra/consistency.py` — F1~F3 raw SQL(ADR-004) + `build_report`(순수 집계) +
    `run_consistency_checks(session, *, batch_id, persist)`. **Dagster 게이트
    미적용** (Phase 1 = 관측). 케이스 추가는 `CONSISTENCY_CASES`에 선언만 추가.
  - **schema 현실 반영**: 본 저장소는 detail을 별도 테이블이 아닌 `features.detail`
    JSONB로 보관(ADR-018)하므로, F2는 "PlaceDetail 행 없음"이 아니라 "detail-bearing
    kind(place/event/notice/route/area)인데 `detail` JSONB 비어있음"으로 구현.
    price/weather는 detail 미보유(DETAIL_MODELS 제외)라 F2 대상 아님.
  - 테스트: `tests/unit/infra/test_consistency.py`(집계 5건) +
    `tests/integration/test_consistency_reports.py`(F1/F2 검출 + OK + 영속화, 2건).

## ADR-028: `python-knps-api` provider 라이브러리 등록

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25) +
  **amendment 2026-05-25 (keyless, file-only)** — 아래 §H 참조.
- **날짜**: 2026-05-25 (원본) / 2026-05-25 (amendment, knps-api PR#4 후)
- **결정자**: claude 제안 + 사용자 (외부 repo 작성 + downstream 반영)
- **컨텍스트**: `docs/forest-feature-etl.md §11`에서 KNPS dataset 14건 통합
  plan 결정 (옵션 B = 별도 `python-knps-api`, ADR-027 기반 카테고리/notice_type
  적용). 외부에서 `digitie/python-knps-api` 저장소가 사용자 주도로 scaffold
  완료 (`6e36990 Initial KNPS API client scaffold`, public client + catalog
  + Pydantic models + exceptions + httpx async + token bucket). 본 라이브러리
  에서는 이 provider를 정식 등록하고 `krtour.map.providers.knps` 변환 모듈을
  후속 sprint에서 작성한다.

- **결정**:

  **A. provider 등록**:
  - canonical provider name: `python-knps-api`
  - import: `from knps import KnpsClient, KnpsConfig, ApiEndpoint, FileDataset,
    CatalogEntry, Page, PROVIDER_NAME, KnpsApiError, KnpsAuthError,
    KnpsNoDataError, KnpsParseError, KnpsRateLimitError, KnpsRequestError,
    KnpsServerError, api_endpoint, api_endpoints, catalog_entries,
    file_dataset, file_datasets`
  - 본 라이브러리 변환 모듈: `krtour.map.providers.knps` (Sprint 2 작성)
  - dataset_key prefix: `knps_*`
  - 라이선스: GPL-3.0-or-later (본 라이브러리와 동일).
  - 인증 env (`knps.config.KnpsConfig.from_env`):
    1. `KNPS_SERVICE_KEY` (우선)
    2. `DATA_GO_KR_SERVICE_KEY` (폴백)
  - `pyproject.toml` `providers` extras에 git URL 주석 추가:
    ```toml
    # "python-knps-api @ git+https://github.com/digitie/python-knps-api.git@<sha>"
    ```

  **B. SHP/GeoJSON 파싱 책임 분리** → **Amendment I(2026-05-29)로 확정**:
  - knps-api는 원본 bytes (`client.files.download(key)`)와 file artifact preview
    를 안정 제공.
  - ~~SHP/GeoJSON 파싱은 본 라이브러리 `krtour.map.providers.knps`에서 수행~~
    → **knps-api 책임으로 확정** (Amendment I / ADR-044): raw 파일 → typed
    record(좌표·geometry WKT)는 knps-api, 본 lib는 record Protocol 소비만.
  - knps-api 측 `[geo]` extra(placeholder)에 parser 구현 — 미구현 시 upstream
    PR (Sprint 2 진입 시 재검토 → 2026-05-29 확정).

  **C. ADR-027 코드 적용 시기 정렬**:
  - T-018 시점에 ADR-027 (forest 카테고리/notice_type 확장) + ADR-028 (본
    ADR) 모두 accepted 전환.
  - `PLACE_CATEGORY_DEFINITIONS`에 3행 (`03.08` Tier 2 + 2 Tier 3),
    `NOTICE_TYPES` tuple에 `access_restriction`/`fire_alert`,
    `AreaDetail.area_kind` Literal에 `hazard_zone` 일괄 추가.

  **D. 양방향 PR 워크플로** (사용자 결정 2026-05-25):
  - 본 라이브러리 작업 중 knps-api에서 발견한 maki/카테고리/명명/dataset
    정합 이슈는 **upstream PR로 적극 수정** (ADR-025 사용자 보강 2차
    `maplibre-vworld-js` 패턴 미러). 본 라이브러리에 wrapper/패치 도입
    금지 (ADR-006 위배 회피).
  - 예: knps-api PR#1 (`docs/knps-feature-maki-icons`) — `shelter`/`barrier`
    maki icon 정정 (본 라이브러리 ADR-027/ADR-029 매핑 정합).

  **E. 본 라이브러리 신설 docs**:
  - `docs/knps-feature-etl.md` (본 PR#12) — feature 적재 계약. upstream
    knps-api `docs/knps-feature-etl.md`와 정합 유지 (양방향 PR로).

  **F. 14 dataset_key 카탈로그** (provider-contract.md §3에 추가):
  - **API endpoints** (3): `knps_visitor_statistics`,
    `knps_access_restrictions`, `knps_fire_alerts`
  - **File datasets** (11): `knps_park_boundaries`, `knps_trails`,
    `knps_visitor_centers`, `knps_hazard_zones`, `knps_weather_stations`,
    `knps_restrooms`, `knps_cultural_resources`, `knps_campgrounds`,
    `knps_shelters`, `knps_recommended_courses`, `knps_park_photos`
  - knps-api `verification_status` (`verified` / `needs_verification` /
    `planned`) 그대로 존중.

- **근거**:
  - **1기관 1라이브러리 컨벤션 (옵션 B)**: KNPS = 환경부, KFS = 농림식품부 —
    별도 기관. `python-mois-api`, `python-krheritage-api`, `python-khoa-api`,
    `python-krforest-api`와 동일 패턴.
  - **외부 scaffold 완료**: 사용자가 작성한 repo의 공개 API/catalog를
    *그대로 채택*. 본 라이브러리에서 wrapper 만들지 않음 (ADR-006).
  - **PR 양방향 (D)**: maplibre-vworld-js 패턴 (ADR-025 2차 보강) 미러 —
    "본 사용자가 직접 운영하는 저장소 = 외부 의존이 아닌 관리 부담".
  - **knps-api 측 catalog는 source of truth**: 본 라이브러리 docs는
    *downstream 입장*의 ETL 계약만. 카탈로그 자체는 knps-api에 있고 본
    라이브러리는 `from knps import file_datasets` 등으로 직접 사용.

- **결과 (긍정)**:
  - 본 라이브러리 통합 비용 낮음 (Sprint 2 한 PR로 `krtour.map.providers.knps`
    모듈 작성 + Dagster asset 11종).
  - knps-api의 SHP/GeoJSON parser placeholder는 본 라이브러리에서 처리
    가능 — Sprint 2 진입 시 양쪽 어디에 둘지 cost/benefit 평가 후 결정.
  - ADR-027 정합 (LODGING_MOUNTAIN_SHELTER + area_kind=hazard_zone + generic
    notice_type) — knps-api 측에서 이미 정확히 반영 (PR#1로 maki icon 마저
    정정).
  - 양방향 PR 워크플로로 명명/매핑 drift 0.

- **결과 (부정)**:
  - 외부 repo 의존 — knps-api에 breaking change가 생기면 본 라이브러리도
    영향. 단, 본 사용자 직접 운영 저장소이므로 통제 가능. fragile 시
    `pyproject.toml` git URL을 commit sha로 핀.
  - SHP/GeoJSON parsing 위치 결정이 Sprint 2로 연기 — 본 라이브러리에서
    하면 `pyproj`/`pyshp` 의존 추가, knps-api에서 하면 본 라이브러리는
    `FeatureBundle` 입력만 받음. 양쪽 모두 가능, Sprint 2에서 결정.

- **후속**:
  - `docs/forest-feature-etl.md §11` 갱신 (본 PR#12) — knps-api scaffold
    완료 명기 + 공개 API 표면 (`KnpsClient` 등) 명기.
  - `docs/knps-feature-etl.md` 신설 (본 PR#12) — feature 적재 계약.
  - `docs/provider-contract.md` 갱신 (본 PR#12):
    - §2 `CANONICAL_PROVIDER_NAMES`에 `python-knps-api` 추가.
    - §3 dataset_key 표에 14건 추가.
    - §4 책임 매트릭스에 한 줄 추가.
  - `docs/external-apis.md` §2 환경변수 카탈로그 (본 PR#12):
    - `KNPS_SERVICE_KEY` 추가 (`python-knps-api` 우선)
    - `DATA_GO_KR_SERVICE_KEY` 비고에 KNPS 폴백 명기.
  - `docs/external-apis.md` §3 provider별 발급 절차 (본 PR#12):
    - §3.13 KNPS 신설 — data.go.kr "국립공원공단" 검색 → API 활용 신청
      → `KNPS_SERVICE_KEY` 환경변수.
  - `pyproject.toml` `providers` extras에 git URL 주석 (본 PR#12).
  - upstream knps-api PR#1 (`docs/knps-feature-maki-icons`) merge 후 본
    라이브러리 동기.
  - T-018 시점에 ADR-027/ADR-028 모두 `accepted` 전환 + 코드 적용 PR.
  - Sprint 2에서 SHP/GeoJSON parsing 책임 위치 결정 (`krtour.map.providers.
    knps` vs knps-api `[geo]` extra).

### H. Amendment 2026-05-25 (keyless + file-only, knps-api PR#3+PR#4 merged)

knps-api 측 변경 (commit `06da125f`, PR#4 `codex/keyless-file-download-dtos`
merged 2026-05-25):

1. **PR#3 (`aa40541` Remove KNPS OpenAPI surface)** — data.go.kr OpenAPI/REST
   endpoint 표면 전체 삭제. `ApiEndpoint`/`api_endpoint`/`api_endpoints`/
   `raw_endpoint`/`Page` 클래스/함수 모두 제거. 카탈로그는 14건 모두
   `kind="file_dataset"`로 통일.
2. **PR#4 (`3269f22`+`3cac75e`+`80c17ed`)** — keyless file artifact DTOs
   추가. `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 모델 추가.
   `client.files.inspect_bytes()` / `client.files.download_artifact()` 메서드
   추가. `KnpsConfig`에서 `service_key`/`api_key` 필드 + `from_env` ENV 읽기
   완전 제거 — `timeout` + `max_rps`만 남음.

본 라이브러리 영향 (PR#25 일괄 반영):

- **A 갱신 — provider 등록**:
  - 인증 env 제거 — `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함.
    `external-apis.md §3.8.1`에서 auth 단계 삭제, "data.go.kr 직접 다운로드
    URL (keyless)" 명기.
  - 공개 API import 목록 정정:
    ```python
    # 신규 (삭제: ApiEndpoint, Page, api_endpoint, api_endpoints)
    from knps import (
        KnpsClient, KnpsConfig, CatalogEntry, FileDataset,
        FileArtifact, FileMember, CsvPreview, CsvPreviewRow,
        PROVIDER_NAME, KnpsApiError, KnpsAuthError, KnpsNoDataError,
        KnpsParseError, KnpsRateLimitError, KnpsRequestError, KnpsServerError,
        catalog_entries, file_dataset, file_datasets,
    )
    ```
  - `KnpsClient` 생성: `KnpsClient(timeout=10.0, max_rps=5.0)` 또는
    `KnpsClient.from_env(...)` (env var 읽지 않음, alias). authentication 인자
    없음.

- **F 갱신 — 14 dataset_key 카탈로그**:
  - **모두 file_dataset** (API endpoints 0건). 이전 §F의 "API endpoints (3)
    /File datasets (11)" 분류 무효.
  - 신규 verified 카탈로그 (knps-api `FILE_DATASETS` 14건):
    | key | data.go.kr ID | feature.kind | verification |
    |-----|---------------|--------------|--------------|
    | `knps_park_boundaries` | `15017313` | area (MultiPolygon) | verified |
    | `knps_trails` | `15003467` | route (LineString) | verified |
    | `knps_visitor_centers` | `15003445` | place (Point) | verified |
    | `knps_hazard_zones` | `15003441` | area (Polygon) | verified |
    | `knps_weather_stations` | `15090557` | weather (Point) | verified |
    | `knps_restrooms` | `15003468` | place (Point) | verified |
    | `knps_cultural_resources` | `15003443` | place (Point) | verified |
    | `knps_campgrounds` | `15003469` | place (Point) | verified |
    | `knps_shelters` | `2982556` | place (Point) | verified |
    | `knps_linear_facilities` | `15091972` | route (LineString) | verified |
    | `knps_basic_statistics` | `15087598` | timeseries | needs_verification |
    | `knps_visitor_statistics` | `15107577` | timeseries | verified |
    | `knps_protected_areas` | `15127921` | area (Polygon) | verified |
    | `knps_lod_table_catalog` | `15118945` | metadata | verified |
  - **삭제된 이전 keys** (knps-api에 더 이상 없음): `knps_access_restrictions`,
    `knps_fire_alerts`, `knps_recommended_courses`, `knps_park_photos`.
    이 중 `access_restriction`/`fire_alert` notice는 다른 provider
    (`python-krforest-api`, 산림청 산불경보) 또는 web scraping으로 보완 — 별도
    ADR로 결정 (KNPS 단독 source 아님).
  - 신규 dataset 구현을 위해 DTO 표준값도 확장:
    `AreaDetail.area_kind='protected_area'`,
    `RouteDetail.route_type='facility_road'`.

- **G 신규 — file artifact API 사용 패턴**:
  ```python
  async with KnpsClient(max_rps=5.0) as client:
      # raw bytes — 본 라이브러리의 SHP/CSV parser에 직접 공급
      data: bytes = await client.files.download("knps_park_boundaries")
      # 또는 preview용 (debug UI / 디버깅)
      artifact: FileArtifact = await client.files.download_artifact(
          "knps_trails", preview_rows=5,
      )
      for csv in artifact.csv_previews:
          print(csv.member_name, csv.encoding, csv.headers, csv.rows[:1])
  ```
  - ~~SHP/GeoJSON parsing은 여전히 본 라이브러리 책임~~ → **Amendment I로 정정
    (2026-05-29)**: SHP/CSV 파싱·geometry 추출은 **knps-api 책임** (ADR-044).

- **pyproject.toml `providers` extras**: git URL 핀 active 권고 (코드 작성
  단계 진입):
  ```toml
  "python-knps-api @ git+https://github.com/digitie/python-knps-api.git@06da125f",
  ```

**근거**:
- knps-api 외부 repo가 keyless로 단순화 → 본 라이브러리는 ENV var/auth wiring
  부담 0 (test fixture에서도 API key mock 불필요).
- 14 dataset 모두 verified status → Sprint 3 KNPS 적재 시 needs_verification
  대응 코드 분기 1건 (`knps_basic_statistics`)만.
- notice 도메인 (`access_restriction`/`fire_alert`) 공급원이 knps에서 사라짐
  → ADR-027 generic notice_type은 다른 provider (산림청 RSS, KFS 공시 등)
  에서 채울 수 있도록 후속 ADR (TBD)에서 명시.

**후속 (본 amendment 적용 PR#25)**:
- `docs/knps-feature-etl.md` 재작성 (API endpoints 섹션 삭제, 14 file dataset
  표 갱신, 인증 단계 삭제, FileArtifact API 사용 예시 추가).
- `docs/forest-feature-etl.md §11` 동기 (provider 공개 API 표면 정정, auth env
  삭제).
- `docs/external-apis.md §3.8.1` 정정 (keyless, ServiceKey 단계 삭제).
- `docs/provider-contract.md` (해당 시) — dataset_key 14건 갱신.
- `pyproject.toml` knps git URL 핀 활성화.
- 후속 ADR (TBD): `access_restriction`/`fire_alert` notice source 결정.

### I. Amendment 2026-05-29 (SHP/CSV 파싱 책임 = knps-api, 결정 B 확정)

§B에서 Sprint 2로 연기했던 "SHP/GeoJSON parsing 위치"를 사용자 결정(2026-05-29)
으로 확정: **raw 파일(SHP ZIP / CSV) → typed record(좌표·geometry WKT 4326)
파싱은 knps-api 책임** (ADR-044 — 데이터 정합성·파싱의 1차 책임은 provider
라이브러리). 본 라이브러리 `providers/knps`는 그 결과를 Protocol로 **소비**만.

- **분계**:
  - knps-api: SHP(ZIP) geometry 디코딩, CP949/euc-kr 인코딩, EPSG:5179→4326
    좌표 변환, geometry를 **WKT(4326)**로 노출. 미구현 시 upstream PR (ADR-025
    보강 패턴, knps-api `[geo]` extra 활용).
  - 본 lib: `KnpsPointRecord`(좌표) / `KnpsGeometryRecord`(geom WKT) Protocol로
    소비 → `Feature` 정규화. geometry 검증·centroid·DTO 조립은
    `core/geometry.py`(shapely). **`pyshp`/SHP 디코딩은 본 lib 의존 아님.**
- **이미 구현 (PR#77/#78)**: `knps_point_records_to_bundles`(place 5건) +
  `knps_geometry_records_to_bundles`(route/area 5건, WKT 입력) + `Feature.geom`
  필드 + `feature_repo` geom 적재. 변환 함수가 처음부터 WKT/좌표 입력이라 본
  amendment로 인한 본 lib **코드 변경 없음** — 문서/주석 정합만.
- **근거**: ADR-006(provider raw, 본 lib 변환)의 "raw"를 ADR-044 기준으로
  "parsed typed record"까지 provider 책임으로 당김 — 형제 provider(kma/opinet/
  datagokr 등)가 모두 typed model을 노출하는 패턴과 일치. SHP byte 핸들링/GDAL
  계열 의존을 provider에 가두어 본 lib 의존 스택을 가볍게 유지.
- **후속**: `docs/knps-feature-etl.md §5` + `providers/knps.py` docstring +
  `docs/tasks.md`/`docs/resume.md` 정합 (본 PR). knps-api 측 record 파싱 API
  (예: `client.files.parse_records(key)`)는 Sprint 3 적재 직전 upstream PR.

## ADR-029: 공통 maki marker / category 매핑 npm 패키지 추출 (`@krtour/map-marker-react`)

- **상태**: superseded by ADR-043 — npm 게시 보류, `packages/map-marker-react/`
  는 모노레포 내부 share 모듈로만 사용 (코드 자체는 유지, registry publish X).
  (구 상태: accepted at T-014 Sprint 1 진입 2026-05-25.)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (T-014 Sprint 1 진입)
- **컨텍스트**: ADR-025 (디버그 UI = maplibre-vworld) + ADR-026 (TripMate 사용자
  UI도 maplibre-vworld 통일)으로 frontend stack은 일원화됨. 그러나 두 UI에서
  공통으로 쓰는 코드 — `krtour.map.category` Tier 1~4 → maki icon(55종)
  dispatch, `MakiMarker` 컴포넌트, marker color 팔레트(P-01~P-16),
  notice_type → maki 매핑 — 가 두 저장소에 중복 박혀야 한다. 이는:
  - 분류 정책 변경(예: ADR-027의 `03.08 shelter` 추가)이 두 곳에 동일하게
    반영되어야 → 누락/drift 위험.
  - 두 곳에 유사 컴포넌트 작성 → maintenance 비용 ×2.
  - 본 라이브러리는 wrapper 도입 금지(ADR-006)라 TripMate가 본 라이브러리의
    debug-ui frontend 컴포넌트를 직접 import할 수 없음.

  해결: **별도 npm 패키지로 추출**.

- **결정**:
  - **패키지명**: `@krtour/map-marker-react`
  - **저장소 위치**: `packages/map-marker-react/` (본 monorepo 내, ADR-020
    debug-ui 패턴 미러). 별도 저장소가 아닌 monorepo로 두는 이유: maki
    매핑/카테고리 코드가 본 라이브러리의 `krtour.map.category` Tier 1~4 +
    `notice-feature-etl.md` notice_type과 직접 정합 — 같은 PR/commit에서
    동기 변경되어야 한다.
  - **포함 항목**:
    - `categoryMaki.ts` — `krtour.map.category` PlaceCategoryCode (144건, ADR-027
      반영) → maki icon (55종 + shelter) dispatch 테이블.
    - `noticeMaki.ts` — `notice_type` (14건, ADR-027 반영) → maki icon
      dispatch.
    - `<MakiMarker>` React 컴포넌트 — maplibre-gl `Marker` 래핑.
    - `markerColor.ts` — P-01~P-16 팔레트 + severity → color helper.
    - TypeScript 타입 (`PlaceCategoryCode`, `NoticeType`, `MakiIconName` 등)
      — 본 라이브러리의 Pydantic DTO와 정합 (수동 mirror 또는
      openapi-typescript에서 import).
  - **빌드/배포**:
    - Vite 라이브러리 모드 (`vite build --mode lib`) → ESM + CJS + d.ts.
    - 게시는 GitHub Packages (npm) 또는 npm public. **공개 npm 권고** (TripMate
      proprietary와 라이선스 충돌 회피).
    - 본 monorepo의 npm workspace 또는 pnpm workspace로 디버그 UI frontend가
      local file:로 참조 (`"@krtour/map-marker-react": "workspace:*"`).
  - **라이선스**: **MIT**. 본 라이브러리(GPL-3.0)와 별도 라이선스인 이유:
    - TripMate(proprietary) `apps/web`이 import해야 함 → GPL 적용 시 TripMate
      전체가 GPL 영향.
    - 본 패키지는 *UI 유틸*이지 비즈니스 로직이 아님 — MIT로 분리해도 본
      라이브러리의 GPL 보호 손상 없음.
    - 본 라이브러리(`krtour.map` Python)는 GPL 유지. npm 패키지만 MIT.
  - **버저닝**:
    - SemVer 0.x로 시작 (breaking change 자유로움).
    - 본 라이브러리 `krtour.map.category` 변경 시 npm 패키지 minor bump.
    - 1.0.0은 ADR-029 구현 + 두 UI 양쪽에서 정착 후 (Sprint 5 운영 진입과
      함께).
  - **TripMate 측 사용**:
    ```typescript
    import { MakiMarker, categoryMakiIcon } from "@krtour/map-marker-react";
    
    <VWorldMap>
      {features.map(f => (
        <MakiMarker
          key={f.feature_id}
          lon={f.lon} lat={f.lat}
          icon={categoryMakiIcon(f.category)}
          color={f.marker_color}
        />
      ))}
    </VWorldMap>
    ```
  - **본 라이브러리(`krtour.map`) 측 정합**:
    - `krtour.map.category`에 `MAPBOX_MAKI_ICON_FOR_CATEGORY` dict 추가
      (이미 `category.md`에 사양 박힘).
    - 코드 작성 단계에서 `tests/unit/test_category_maki_consistency.py` —
      Python ↔ TypeScript 매핑 표 1:1 일치 검증. drift gate.
    - `packages/map-marker-react/scripts/sync_from_python.ts` — Python 측
      매핑을 읽어 TypeScript 테이블 생성 (또는 build time 검증).

- **근거**:
  - **drift 회피**: 단일 source → 두 UI에 분배. category/notice_type 정책
    변경이 자동 반영.
  - **monorepo + npm workspace**: 본 라이브러리 PR에서 동시 변경 가능 → 매핑
    drift 0.
  - **MIT 라이선스**: TripMate proprietary 호환. UI 유틸은 일반 공개에도
    무리 없음.
  - **wrapper 아님**: ADR-006 위반 아님 — provider client wrapper가 아닌 *UI
    공통 모듈*. provider 호출 책임은 본 라이브러리에 그대로.

- **결과 (긍정)**:
  - 두 UI 마커 코드 단일 source. 카테고리/notice 변경 시 매핑 drift 0.
  - TripMate 운영 학습 비용 절감 — `@krtour/map-marker-react` 한 번 익히면
    디버그 UI도 동일.
  - 외부 (제3자 maplibre-vworld 사용자)도 본 패키지를 npm으로 받아 사용
    가능 → 한국 관광 도메인 표준 정착에 기여.

- **결과 (부정)**:
  - npm workspace 운영 부담 (Vite 라이브러리 모드 빌드, d.ts 생성, 게시).
  - 본 라이브러리 PR에서 두 언어(Python + TypeScript) 변경 → 리뷰 부담 약간
    증가. `tests/unit/test_category_maki_consistency.py` drift gate로 완화.
  - MIT vs GPL 분리는 의도적이지만 운영자가 라이선스 정책을 두 종류로 관리
    해야 함.

- **후속**:
  - `packages/map-marker-react/` 디렉토리 생성 — `package.json` skeleton +
    README + `.gitignore` + `vite.config.ts` (T-017 실행 시).
  - `docs/debug-ui-package.md` §14 — `categoryMaki.ts`를 `@krtour/map-marker-react`
    에서 import하도록 명기.
  - `docs/tripmate-integration.md` §14.5 — TripMate 사용자 UI가 본 npm 패키지를
    사용한다고 명기.
  - `docs/category.md` §4.4 — maki icon 매핑이 두 UI 공통 reference임 명기
    (ADR-025/026 후속의 잔존 항목).
  - `tests/unit/test_category_maki_consistency.py` — Python ↔ TS 매핑 1:1
    검증 통합 테스트 (코드 작성 단계).
  - npm 게시 절차 ADR (후속, ADR-035+) — release 자동화 + version sync.

## ADR-034: Provider 구현 순서 — MOIS-독립 먼저, MOIS bulk, MOIS-sibling 후

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: 사용자 (구현 순서 명시) + claude (Sprint 매핑)
- **컨텍스트**: 본 라이브러리는 14+ provider를 적재한다. provider별 구현
  순서가 정해져 있지 않으면 dedup 룰 검증이 흐트러진다. 특히 `python-mois-api`
  의 인허가 데이터는 **가장 큰 bulk** (195 슬러그 × 시군구 다수)이고, 산림청
  휴양림/수목원·표준데이터 박물관/미술관 등과 **카테고리/슬러그 중복**이
  많다. MOIS를 먼저 적재하고 다른 provider를 들이면 `dedup_review_queue`가
  폭증 + Record Linkage 가중치 검증이 large dataset에서 시작 → 디버깅 비용
  ↑.

  사용자가 다음 구현 순서를 명시:
  > 축제 → 날씨 → 유가 → 휴게소 → 국립공원/트래킹코스
  >   (인허가와 무관한 정보들)
  > → 국가유산 → **MOIS 인허가** → 수목원/휴양림 → 박물관/미술관

  핵심 통찰: MOIS-독립 provider를 먼저 적재해 dedup 룰을 작은 dataset에서
  검증 → MOIS bulk 진입 시점에 정합성 게이트가 안정 → MOIS-sibling provider
  (휴양림/수목원/박물관 — MOIS와 중복 가능)는 이미 검증된 룰로 진입.

- **결정**:

  **9단계 구현 순서** (Sprint 2~5 매핑):

  | 순서 | provider / source | Feature.kind | 적재 단계 (Sprint) | MOIS와 dedup 가능성 |
  |------|------------------|--------------|------------------|---------------------|
  | 1 | 축제 (`python-visitkorea-api`) | event | Sprint 2 | 없음 (event는 PROMOTED 슬러그 없음) |
  | 2 | 날씨 (`python-kma-api`) | weather | Sprint 2 | 없음 |
  | 3 | 유가 (`python-opinet-api`) | place + price | Sprint 2 | 없음 (주유소 ≠ MOIS 슬러그) |
  | 4 | 휴게소 (`python-krex-api`) | place + price + weather + notice | Sprint 2 | 없음 (휴게소 ≠ MOIS 슬러그) |
  | 5 | 국립공원/트래킹 (`python-knps-api`) | area + route + place + notice + weather | Sprint 3 | 없음 (KNPS area/route는 MOIS 슬러그와 무관) |
  | 6 | 국가유산 (`python-krheritage-api`) | place + area + event | Sprint 3 | **부분** (사찰/한옥은 MOIS `hanok_experience` 등과 sibling 가능 — Sprint 3 시점엔 MOIS 미적재라 dedup queue 미발생) |
  | 7 | **MOIS 인허가** (`python-mois-api`) | place (대량) | Sprint 4 | (자기 자신) — 4단계 lifecycle, dedup 룰 본격 검증 |
  | 8 | 휴양림/수목원 (`python-krforest-api`) | place + area | Sprint 5 | **있음** (휴양림 = MOIS `condo_resorts`/`tourist_accommodations` sibling, 수목원 = MOIS `botanical_gardens` sibling) |
  | 9 | 박물관/미술관 (`data.go.kr-standard`) | place | Sprint 5 | **있음** (`standard_museums` ≅ MOIS `museums_art_galleries`) |

  **MOIS 외 보조 dataset도 위 순서를 따른다**:
  - `python-khoa-api` (해수욕장 + 해양공지) — Sprint 2 (날씨와 같이, MOIS sibling 약함)
  - `python-airkorea-api` (대기질) — Sprint 2 (날씨와 같이)
  - `python-krairport-api` (공항) — Sprint 3 (krex와 같이, MOIS와 중복 없음)
  - `python-krforest-api` 산악기상 — Sprint 2 (날씨), 산악 trails는 Sprint 3 (knps와 같이)
  - `python-knps-api` 시설(visitor_centers/restrooms/cultural_resources) — Sprint 3 (area와 같이, MOIS 약한 중복 → 시점상 무관)
  - `data.go.kr-standard` 관광지/주차장/관광길/문화축제 — Sprint 5 (박물관과 같이)
  - `place_phone_enrichment` (Kakao Local / NAVER / Google Places) — Sprint 4~5 백그라운드 (MOIS 적재 후 전화번호 보강)

- **근거**:
  - **dedup 룰 검증 순서**: 작은 dataset (축제 < 100k, 유가 ~12k, 휴게소
    ~200, 국립공원 22개 + 탐방로 ~수천)에서 Record Linkage scoring(ADR-016
    가중치 0.45/0.35/0.20)을 먼저 검증. MOIS bulk(수십만~수백만 row) 진입
    시점에는 룰이 이미 stable.
  - **dedup_review_queue 폭증 회피**: MOIS를 먼저 적재하면 후속 provider
    들어올 때 *모든* MOIS row와 새 row를 비교 → queue 폭증. MOIS를 마지막에
    적재하면 후속 provider가 없으므로 queue 안정.
  - **정합성 게이트 (ADR-033) 적용 시점 정렬**: F1~F3 (Sprint 3 도입)는 작은
    dataset에서 검증, F4 (dedup_review 미해소) / F7 (dedup score 회귀)는
    MOIS 진입 시점에 의미 있는 baseline 확보 후 작동.
  - **MOIS sibling provider (8/9)는 MOIS 이후**: MOIS가 먼저 들어가 있어야
    `LODGING_RECREATION_FOREST` / `LODGING_HOTEL` / `TOURISM_BOTANICAL` /
    `01.04.01 박물관` 슬러그에 대한 dedup 비교가 자연. MOIS가 sibling을
    primary로 가져가고, 이후 다른 provider가 enrichment/추가 정보로 join.
  - **사용자 도메인 지식 반영**: 사용자가 한국 관광 API 생태계를 잘 알고
    9단계를 명시 → 본 라이브러리 운영 직관과 일치.

- **결과 (긍정)**:
  - dedup 룰 디버깅이 작은 dataset에서 → MOIS 진입 시점에는 black-box
    문제로만 다룰 수 있음.
  - 각 Sprint별 산출물이 명확 (Sprint 2 = 작은 provider 4개, Sprint 3 = 중간
    + 정합성 Phase 1, Sprint 4 = MOIS bulk, Sprint 5 = sibling + 운영 진입).
  - Sprint 5 운영 진입 시점에 전체 14+ provider가 들어와 있음 → SLO 측정
    baseline 확보.

- **결과 (부정)**:
  - 사용자/TripMate 입장에서 "박물관/미술관"이 가장 흔한 카테고리인데 마지막
    Sprint까지 미적재 → demo/PoC에 미흡. 완화: Sprint 2 끝에 `data.go.kr-
    standard` 박물관만 *임시 sample* 1~2건 manual fixture로 디버그 UI에
    시연 가능하게.
  - MOIS Sprint 4가 다른 어떤 Sprint보다 무겁다 (bulk + 4단계 lifecycle +
    dedup queue 운영 시작) → 일정 risk 큼. 완화: Sprint 4를 길게 잡거나
    Sprint 4a/4b로 분할 (4a = Step A bulk + Step B incremental, 4b = Step C
    closed + Step D detail + dedup queue 운영).

- **후속**:
  - `docs/sprints/SPRINT-2.md` ~ `SPRINT-5.md` 신설 (본 PR#14) — 9단계
    순서를 Sprint 진입 조건/산출물/DoD에 박음.
  - `docs/sprints/SPRINT-1.md` §"비목표" 갱신 — "provider 호출"이 Sprint 2
    부터인 점 명확화.
  - `docs/dagster-boundary.md §5` asset 명명 표 — Sprint별로 그룹화 가능.
  - `docs/test-strategy.md` §4 통합 테스트 매트릭스 — provider별 fixture가
    위 순서로 추가됨.
  - T-018 Sprint 매핑 명확화 — `krtour.map.providers.knps`는 Sprint 3,
    `krtour.map.providers.mois`는 Sprint 4, `krtour.map.providers.krforest`
    (휴양림/수목원) + standard_data는 Sprint 5.
  - Sprint 4 분할 여부는 Sprint 3 종료 시점에 진척도 보고 결정.

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

---

## ADR-035: 디버그/관리 REST API는 프로덕션 환경에서도 admin/유지보수 UI로 운영

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-005/ADR-020에서 `krtour-map-admin` 패키지는 "디버그 + 내부망 전용 + 인증
없음"으로 정의되었다. 운영 단계에 들어가면서 다음 요구가 등장:

- 운영자가 적재 jobs / dedup queue / consistency reports / RustFS 사용량 등을
  **실시간으로 보고 손볼** UI가 필요.
- TripMate 본 앱에 admin 화면을 별도로 만들 만큼 트래픽이 없음 — `krtour-map-
  debug-ui` 패키지를 그대로 admin UI로 활용하는 게 자연.
- 단, 인증 키는 본 패키지 코드 안에 박지 않는다 (ADR-005 원칙 유지). 네트워크
  계층(Cloudflare Tunnel + SSO 게이트웨이 / IP allowlist)에서 보호.

### 결정

- `krtour-map-admin` 패키지의 운영 범위를 **"디버그 + 내부망 전용"에서 "디버그
  + admin/유지보수/프로덕션 운영"으로 확장**.
- 인증/접근 제어는 여전히 코드 외부 (Cloudflare Tunnel / SSO / IP allowlist).
  패키지 자체에 인증 로직 추가 금지(ADR-005 §SKILL DO NOT #14 그대로).
- 프로덕션에서 노출되는 라우터 prefix는 `/admin/...` 또는 `/ops/...`로 분리해
  디버그용(`/debug/...`)과 시각적으로 구분.
- 운영 라우터는 **읽기 우선** + 쓰기는 explicit confirmation 필수(예: rerun
  job, manual dedup decision). delete/purge는 별도 ADR.

### 근거

- 별도 admin 앱을 만들면 인증·DB 연결·이슈 디버깅이 모두 중복.
- 디버그 패키지에 admin 라우터를 더하면 한 코드베이스가 됨 — 발견된 버그가
  운영에 즉시 반영.
- 인증을 코드에서 떼어내면 패키지 자체가 가볍고, 인프라 보안 정책 변경 시 코드
  수정 불필요.

### 결과 (긍정)

- 운영자/개발자가 같은 UI에서 같은 데이터를 봄 → 일관성.
- 운영 라우터가 patch/post 빈도가 낮아 부담 적음.

### 결과 (부정)

- 운영용 admin UI는 결국 인증이 필요한데, 인프라 계층에 의존하면 PC 개발자가
  로컬에서 실수로 외부 노출하면 위험 → README/Settings에 경고 + `KRTOUR_MAP_
  DEBUG_UI_HOST` 기본 `127.0.0.1` 강제 유지.

### 후속

- `docs/debug-ui-package.md` §"운영 라우터" 추가 — `/admin/jobs`, `/admin/dedup-
  review`, `/ops/consistency`, `/ops/rustfs-usage` 등 prefix 분리.
- `docs/decisions.md` ADR-005/020 supersede note 추가 (본 PR에서 동시).
- `packages/krtour-map-admin/README.md` "프로덕션 admin 가이드" 절 추가.

---

## ADR-036: `maplibre-vworld-js` 라이브러리 분리 + v0.1.0 — 공통 기능은 상류, TripMate 전용만 본 저장소

> **현행 핀(2026-06-06 기준)**: `maplibre-vworld-js#v0.1.2` + Next.js 16. 본 ADR
> 제목/초기 본문의 `v0.1.0`은 채택 당시 값이며, v0.1.2 + Next.js 16 정합은 아래
> "Amendment (2026-05-31, PR#114)"가 정본이다.

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-025/ADR-026에서 디버그 UI frontend + TripMate 사용자 UI 모두 `maplibre-
vworld` 통일. 현재 `packages/krtour-map-admin/frontend/`에 vworld basemap +
maki marker + 카테고리 토글 + bounds 검색 등 공통 기능이 빠르게 자란다. 이중
중복 위험:

- TripMate apps/web도 같은 vworld basemap 코드를 재구현해야 함.
- 공통 기능 버그 수정이 두 코드베이스를 동시에 손봐야 함.

별도 라이브러리 `maplibre-vworld-js`(또는 `maplibre-vworld`)로 빼서 한쪽에서
유지보수 + 두 UI에서 import.

### 결정

- **공통 frontend 기능**(vworld basemap 설정 / maki marker render / 카테고리
  legend / bounds 검색 helper / tile cache)는 **`maplibre-vworld-js` 별도
  라이브러리**로 분리. 본 저장소 외부에 둔다 (사용자가 `digitie/maplibre-
  vworld-js` 신규 GitHub repo 신설 예정).
- **TripMate 전용 기능**(adminUI 시각화 / debug fixture replay / map overlay
  on top of TripMate route plan 등)은 본 저장소(`packages/krtour-map-debug-
  ui/frontend/` + 향후 `packages/tripmate-map-extensions/`)에 둔다.
- 목표 release: **`maplibre-vworld-js@0.1.0`** — vworld basemap + maki marker
  + 카테고리 legend 3종 안정화.

### 근거

- 공통 라이브러리 분리는 `python-kraddr-geo` / `python-knps-api`와 동일 패턴.
- 분리 시점이 빠를수록 cross-cutting 책임 분리 비용이 작음.

### 결과 (긍정)

- TripMate apps/web이 본 저장소 디버그 UI와 vworld basemap 코드를 공유.
- 라이브러리 단위로 semver 관리 + 회귀 테스트.

### 결과 (부정)

- 라이브러리 분리 작업 자체가 추가 PR/유지보수 비용.
- npm registry 게시는 보류(ADR-043) — 형제 라이브러리 git URL + commit sha
  핀으로 import.

### 후속

- 신규 저장소 `digitie/maplibre-vworld-js` 생성 (별도 작업, 사용자 직접 또는
  Sprint 3 진입 시 본 라이브러리 측에서 PR 보조).
- 본 저장소 `packages/krtour-map-admin/frontend/` 코드 중 공통 부분을
  `maplibre-vworld-js`로 이전 (Sprint 3 후반 PR).
- `docs/decisions.md` ADR-025 amendment — 라이브러리 분리 시점/책임 분배 명시.
- `packages/krtour-map-admin/README.md` 의존성 트리 갱신.

### Amendment (2026-05-28, PR#49) — v0.1.0 릴리스 + 의존 핀 정합

`digitie/maplibre-vworld-js` **v0.1.0 태그가 실제 릴리스됨**. 이에 본 저장소
의존 핀을 v0.1.0 기준으로 정정:

- **npm 미게시 확인** — `maplibre-vworld`는 npm registry에 없음. 따라서
  semver(`^1.0.0`)로는 설치 불가. **git URL + release tag**로 핀:
  `"maplibre-vworld": "github:digitie/maplibre-vworld-js#v0.1.0"` (ADR-043
  형제 라이브러리 git 핀 패턴과 동일 정신).
- 기존 `frontend/package.json` + `packages/map-marker-react/package.json`의
  `"^1.0.0"`은 **이중으로 잘못됨** (그 버전 미존재 + npm 미게시) → 정정.
- v0.1.0 **peerDependencies 정합**: `maplibre-gl ^5.24.0` / `react >=18 <20`
  / `zod ^4.4.3`. 본 저장소 frontend의 `zod`를 `^3.23.0` → `^4.4.3`으로 상향.
  `map-marker-react` peer/dev도 동일 정합 (zod peer 추가).
- v0.1.0 공개 API 표면(참고): `VWorldMap`(`apiKey`/`center`/`zoom`/`fallback`)
  + `MapStore`/`useMap`/`useMapZoom`/`useMapSelector` hook + 마커 13종
  (`MakiMarker`/`PlaceMarker`/`PriceMarker`/`WeatherMarker`/`ClusterMarker`
  등) + 레이어(`ClusterLayer`/`ServerClusterLayer`/`RouteLine`/`PolygonArea`)
  + `zod` schemas(`LngLatSchema`/`BoundsSchema` + `parseBoundsParam` 등).
- 본 저장소 frontend의 Zustand `useMapStore`(viewport/selectedFeatureId/
  activeCategoryCodes)는 v0.1.0의 map-인스턴스 바인딩 `MapStore`와 **역할이
  다르다**(앱 UI 상태 vs 지도 인스턴스 상태) — 병존 OK, 중복 아님.

### Amendment (2026-05-31, PR#114) — v0.1.2 + Next.js 16 최신화

로컬 `F:\dev\maplibre-vworld-js` 최신 `main`/tag를 확인한 결과
`maplibre-vworld-js` 최신 릴리스는 **v0.1.2**다. 본 저장소 frontend와
`@krtour/map-marker-react`의 git URL 핀을 `#v0.1.2`로 올리고, Next.js는 공식
v16 업그레이드 가이드에 따라 **Next.js 16 + ESLint CLI(flat config)** 기준으로
정렬한다.

- `next lint`는 Next.js 16에서 제거되었으므로 `npm run lint`는 `eslint .`를
  실행한다.
- `packages/krtour-map-admin/frontend/eslint.config.mjs`는
  `eslint-config-next/core-web-vitals` + `eslint-config-next/typescript` flat config를
  사용한다.
- npm workspace에서 Next.js 16 production build(Turbopack)가 root를 `src/app`으로
  오판하지 않도록 `next.config.ts`에 repo root 기준 `turbopack.root`를 명시한다.
- Next.js 16.2.6 stable은 아직 transitive `postcss 8.4.31`을 선언하므로
  npm audit의 `GHSA-qx2v-qp2m-jg93` 차단을 위해 root `package.json`에서
  `next > postcss`를 `^8.5.15`로 override한다. canary(`16.3.0-canary.*`)로
  넘어가지 않고 stable을 유지한다.
- `maplibre-gl ^5.24.0`, `zod ^4.4.3`, React 19 계열은 v0.1.2 peer와 정합하다.

---

## ADR-037: 디버그/관리 UI frontend state 관리 — TanStack Query + Zustand

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-025에서 frontend는 Next.js + maplibre-vworld로 정의. state 관리 라이브러리
는 미정. Sprint 2/3에서 라우터/UI 추가가 본격 시작되므로 표준 박음:

- 서버 상태(REST 응답 캐싱/refetch): TanStack Query (구 react-query).
- 클라이언트 상태(UI toggle / map viewport / filter chip 등): Zustand.

### 결정

- **TanStack Query** — REST API 데이터 fetching/캐싱/invalidation. 모든
  `/admin/...`, `/ops/...`, `/features/...` 라우터 응답은 TanStack Query hook
  으로 래핑.
- **Zustand** — UI 클라이언트 상태(map viewport / 선택된 feature / 카테고리
  filter / debug fixture playback 상태 등). Redux/MobX/Context-API 대신.
- Redux Toolkit / SWR / Jotai / Recoil 검토했으나 본 use case 규모에 과함 —
  Zustand의 hook 기반 store + TanStack의 query/mutation hook이 가장 가볍고
  타입 강함.

### 근거

- TanStack Query는 stale-while-revalidate / refetch on focus / mutation
  invalidation이 기본 → admin/유지보수 UI에서 운영자가 새로고침 의식 없이
  최신 상태 보임.
- Zustand는 React 18 concurrent feature 호환 + boilerplate 적음.

### 결과 (긍정)

- 두 라이브러리 모두 npm 다운로드 수백만/주 + 타입 강함 + 작은 번들.
- 디버그 UI에서 검증한 state 패턴을 maplibre-vworld-js 라이브러리에도 그대로
  이식 가능.

### 결과 (부정)

- 새 frontend 개발자가 두 라이브러리 학습 필요 — 단, learning curve가 낮아
  허용.

### 후속

- `packages/krtour-map-admin/frontend/package.json`에 `@tanstack/react-
  query` + `zustand` 추가 (Sprint 2 첫 frontend PR과 함께).
- `docs/decisions.md` ADR-025 amendment — frontend state stack 박음.
- `packages/krtour-map-admin/frontend/src/state/` 컨벤션 폴더 구조 docs.

---

## ADR-038: GitHub Actions CI/CD 재활성화 — 머지 게이트 다시 켬

- **상태**: accepted (PR#33, 2026-05-27 — 종전 "쓰지마" 지시 reverse)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

2026-05-26 사용자가 "깃헙 ci/cd 쓰지마"로 지시 → 로컬 검증(pytest + ruff +
mypy + lint-imports) 기반 머지 직행 운영. `.github/workflows/{ci,lint,
openapi}.yml`은 워크플로우 파일은 남겨두고 실행 결과를 머지 게이트로 쓰지 않음.

운영 단계 진입 + 다중 에이전트 PR이 늘면서 다음 문제 인지:

- 로컬 검증만으로는 "내 PC에서 됨" 함정 (testcontainers PostGIS 환경 차이,
  Python 3.11/3.12/3.13 matrix 누락, OS 차이 등).
- 사용자가 직접 일일이 머지 직전 검증을 보강하기 어렵다.

### 결정

- **GitHub Actions CI/CD 재활성화**. 다음 워크플로우를 PR/main push 기준 머지
  게이트로 사용:
  - `.github/workflows/ci.yml` — pytest unit + integration matrix (3.11/12/13)
  - `.github/workflows/lint.yml` — ruff + mypy + import-linter
  - `.github/workflows/openapi.yml` — OpenAPI drift gate (ADR-031, Sprint 2
    첫 라우터 진입 후 실효)
- branch protection rules에서 위 워크플로우 통과 + 1 review approval 필수
  (사용자 직접 설정 — Settings → Branches → main).
- 로컬 검증은 **유지** — PR 푸시 전 1차 확인용. CI는 2차 검증 + matrix.

### 근거

- CI는 환경 격차/regression의 마지막 차단선. 끄면 후속 PR 빚을 진다.
- "쓰지마" 시기의 효율 이점(로컬 검증만 → 즉시 머지)은 PR 1~2건짜리 sprint
  scaffolding에서만 유효 — Sprint 2 본격 진입하면 코드 변경량/충돌이 늘어
  CI 없이 위험.

### 결과 (긍정)

- matrix CI로 3.11/3.12/3.13 + ubuntu-latest 환경 자동 검증.
- testcontainers PostGIS가 CI에서 매번 부트 → 적재 회귀 차단.

### 결과 (부정)

- 머지 latency가 늘어남 (PR push → CI 실행 ~5~8분 대기).
- CI 실패 시 fix 푸시 + 재실행 cycle.
- 완화: branch protection을 `Require status checks` + `Require branches up
  to date` 두 가지만, `Require linear history`/`Require signed commits`는
  당장은 보류(Sprint 4 진입 시 재검토).

### 후속

- `AGENTS.md` 작업 후 체크리스트 §"검증" 갱신 — "로컬 + CI 모두 green"
  표기.
- `SKILL.md` DO NOT 룰 #17 "main 직접 push 금지" 옆에 "CI green 통과 후
  머지" 추가.
- 사용자 측 GitHub Settings → Branches → main → Branch protection rules
  활성화 (사용자 직접 / 본 라이브러리 코드 변경 X).
- 종전 머지 직행 패턴 폐기 — `docs/journal.md` 2026-05-26 "쓰지마" 지시
  reference에 reverse note.

---

## ADR-039: CLI 중복 실행 차단 — 비-동시-실행 명령은 lock으로 보호

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

본 라이브러리는 향후 `krtour-map` CLI를 제공한다 (Sprint 4~5). 일부 CLI 명령은
동시 실행이 부적절:

- `krtour-map import <provider>` — 같은 provider+dataset_key를 두 워커가
  동시에 적재하면 source_record_key UNIQUE 충돌 + import_jobs 상태 불일치.
- `krtour-map dedup-merge <feature_id>` — manual merge가 동시에 두 명에 의해
  실행되면 master 선정 충돌.
- `krtour-map backup` / `restore` — ADR-040의 hot-swap 절차 도중 두 번째
  실행이 들어오면 데이터 손상.
- `alembic upgrade head` — 다중 워커 동시 실행 시 잠금 경쟁 / migration
  duplicate revision 위험.

### 결정

- 위 부류 CLI 명령에 **PostgreSQL advisory lock** (`pg_try_advisory_lock`)을
  기반으로 한 mutex 가드 박음.
- lock key naming: `hash(f"krtour-map:{command}:{scope}")` (예: `import:
  python-visitkorea-api:festival`, `dedup-merge:f_xxx`, `backup`,
  `alembic-upgrade`).
- 이미 lock이 잡혀 있으면 즉시 `ImportJobConflictError`(또는 동등) raise +
  exit code 2 반환.
- 정상 종료/abort 시 `pg_advisory_unlock` 자동.
- 동시 실행을 허용해도 무방한 read-only 명령(예: `krtour-map status`,
  `--dry-run`)은 lock 없이 그대로.

### 근거

- DB advisory lock은 본 라이브러리 모든 CLI 명령이 PostgreSQL 연결을 갖고
  있으므로 추가 의존 X.
- in-memory file lock보다 multi-host 안전.
- `import_jobs` 상태 + `pg_advisory_lock`은 ADR-013의 "in-memory 신뢰 금지"
  원칙과 일관.

### 결과 (긍정)

- 사용자가 CLI를 잘못 두 번 호출해도 두 번째가 즉시 reject.
- backup/restore 같은 critical path가 동시 진입 차단.

### 결과 (부정)

- lock acquire 실패 시 메시지가 명시적이지 않으면 사용자 혼란 — error 메시지에
  현재 lock holder의 `pg_stat_activity` query 보여주는 helper 필요.
- `restore` 같은 명령은 정상 종료가 보장 안 되면 lock 잔존 → `lifespan`/
  `atexit`로 unlock fallback.

### 후속

- `src/krtour/map/cli/mutex.py` 신설 (Sprint 4 진입 시) — `with mutex_lock
  (session, key)` async context manager.
- `src/krtour/map/cli/` 첫 명령(예: `import`)부터 본 mutex 적용.
- `docs/backend-package.md` §"CLI 명령 표"에 mutex 여부 컬럼 추가.
- `SKILL.md` DO NOT 룰에 "mutex 필요한 CLI는 advisory lock 박음" 추가.

---

## ADR-040: Backup/Restore + 핫스왑 UI

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

운영 단계에서 다음 시나리오 필요:

- **백업**: PostgreSQL `feature.*` + `provider_sync.*` + `ops.*` schema + RustFS
  `feature-files` 버킷을 한 번에 dump → 외부 저장소(NTFS / R2 / S3) 보관.
- **복원**: 위 dump를 새 환경에 hot-swap. 운영 DB를 멈추지 않고 staging DB로
  먼저 복원 후 atomic switch (DNS / connection pool 재설정).
- **운영 UI**: 백업 schedule 보기 + 실행 / 복원 큐 보기 + 진행률 / failed
  엔트리 retry.

이 기능은 ADR-035의 "프로덕션 admin UI"의 한 갈래.

### 결정

- **Backup 단위**:
  - PostgreSQL: `pg_dump --format=custom --schema=feature --schema=provider_
    sync --schema=ops` (extension schema는 별도, `x_extension`은 복원 시
    `CREATE EXTENSION ... SCHEMA x_extension`만 수동).
  - RustFS: `rclone sync rustfs:feature-files <backup-target>:feature-files-
    <YYYYMMDD-HHMMSS>` 또는 RustFS native snapshot.
- **저장 위치**: 1차 NTFS의 `data/backups/<YYYYMMDD-HHMMSS>/`, 2차 외부
  (S3/R2) — `KRTOUR_MAP_BACKUP_TARGETS` settings로 multi-target.
- **Restore 패턴**: hot-swap 권장 — staging DB에 복원 → smoke test (디버그
  API ping + count check) → connection pool DSN 교체 → 구 DB 제거.
- **운영 UI 라우터** (ADR-035):
  - `GET /admin/backups` — 목록 (날짜 / 사이즈 / status)
  - `POST /admin/backups` — 즉시 백업 실행 (ADR-039 mutex `backup`)
  - `POST /admin/restore/{backup_id}` — staging DB로 복원 (ADR-039 mutex
    `restore`)
  - `POST /admin/restore/{backup_id}/swap` — atomic switch
- **스케줄**: daily full + hourly WAL(추후). Sprint 5 진입 시 cron 또는
  Dagster schedule.

### 근거

- PostgreSQL `pg_dump --format=custom` + RustFS snapshot이 industry-standard.
- hot-swap은 비용이 비싸지만 운영 downtime 0 — 본 라이브러리는 TripMate에
  실시간 의존하므로 downtime cost가 크다.

### 결과 (긍정)

- 운영자가 콘솔에서 백업/복원 가능 — DB shell 진입 불필요.
- staging 복원으로 PIT(point-in-time) 검증 후 switch.

### 결과 (부정)

- hot-swap을 위한 dual DB 환경이 필요 — 운영 인프라 비용 증가.
- 완화: 초기 단계는 cold restore(downtime 허용)로 시작, Sprint 5에 hot-swap
  도입.

### 후속

- `docs/decisions.md` ADR-035 amendment — admin 라우터 표에 backup/restore
  prefix 추가.
- `docs/backup-restore.md` 신설 (Sprint 4~5 prep PR).
- `src/krtour/map/infra/backup.py` (Sprint 5).
- `packages/krtour-map-admin/src/krtour/map_admin/routers/admin_backups.py`.
- `KRTOUR_MAP_BACKUP_TARGETS` settings + Pydantic validator.

---

## ADR-041: `python-kraddr-base` 코드 본 라이브러리로 흡수 — kraddr-base 폐기 예정

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-023에서 `python-kraddr-base.categories` 모듈을 `krtour.map.category`로
이전 완료(PR#18). 다른 kraddr-base 모듈(`address`, `domain`, 일부 utility 함수)
도 본 라이브러리 외에 사용처가 없거나 적음. `python-kraddr-base` 자체를 폐기하고
필요한 코드만 본 라이브러리로 흡수.

**중요 제외**: `PlaceCoordinate`는 본 라이브러리의 `dto/coordinate.py` `Coordinate`
와 책임 중복 + EPSG/Decimal 처리 정책 충돌 → **가져오지 않음**. 호출자 측에서는
`krtour.map.dto.Coordinate`만 사용.

### 결정

- **흡수 대상**(예시, 실 작업 시 kraddr-base 전수 survey 후 PR 단위):
  - `kraddr.base.address` — `Address` 모델 + 한국 주소 정규화 helper. 본 lib
    `dto/address.py`와 머지(필요 필드만 추가).
  - `kraddr.base.domain` — 도메인 분류 enum/helper. `category` 모듈에 흡수
    or `dto/_enums.py`로.
  - utility 함수(예: `kraddr.base.utils.normalize_bjd_code`,
    `clean_phone_number` 등) — `core/normalize.py` 또는 `core/strings.py`
    신규 모듈로.
- **제외 대상**:
  - `PlaceCoordinate` — `krtour.map.dto.Coordinate`로 단일화. 호출자가
    명시적으로 ergonomics에 맞춰 변환.
- **`python-kraddr-base` 라이브러리는 본 흡수 PR이 모두 머지된 후 GitHub
  repo archive**. v2 마지막 release에 deprecation note.

### 근거

- kraddr-base는 현재 본 라이브러리 + TripMate apps 외 호출자 없음 → 별도
  유지비용 회피.
- 코드 흡수 시 import 경로가 짧아짐 (`from krtour.map.core import normalize_
  bjd_code` vs `from kraddr.base.utils import normalize_bjd_code`).
- `PlaceCoordinate`를 가져오지 않는 것은 단일 책임 — 좌표 DTO는 본 lib가
  source of truth.

### 결과 (긍정)

- 외부 의존 패키지 1개 감소 → install / version pinning 단순화.
- 본 라이브러리 안에서 한국 주소/좌표/도메인 helper가 한곳에 모임.

### 결과 (부정)

- 흡수 PR이 코드 옮김 + import path 변경 + 테스트 회귀까지 포함 → 큰 PR.
- 완화: 모듈 단위로 PR 분할 (address PR / domain PR / utils PR).

### 후속

- `python-kraddr-base` 저장소 전수 survey PR(Sprint 4 진입 prep).
- 흡수 모듈 단위 PR 3~5건 (`docs/kraddr-base-absorption.md`로 추적).
- `python-kraddr-base` deprecation note + archive (Sprint 5 종료 시).
- `pyproject.toml` `python-kraddr-base` git URL 제거 (마지막 흡수 PR과 함께).
- `docs/kraddr-base-types.md` superseded note.

---

## ADR-042: 전국관광지정보표준데이터 / 전국문화축제표준데이터 — `python-datagokr-api` 경유로 본 라이브러리에서 적재

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-034 9단계 1단계가 "축제(`python-visitkorea-api`)"였다. 그러나 사용자가
data.go.kr 표준데이터 2종을 1차 source로 사용하라고 지시:

- **전국관광지정보표준데이터** — 전국 관광지 점 정보 (place kind).
- **전국문화축제표준데이터** — 전국 축제/문화행사 (event kind).

두 표준데이터는 안정성/갱신주기/품질이 visitkorea TourAPI보다 좋다. provider
경계는 `python-datagokr-api` 라이브러리에서 client + typed model을 두고, 본
라이브러리는 그 model을 `Feature` bundle로 변환.

### 결정

- **축제 1차 source 변경**: visitkorea festival → `data.go.kr-standard`
  전국문화축제표준데이터. visitkorea는 enrichment(image / 상세 description /
  contentId 매핑)로 활용 (`source_role='enrichment'`).
- **관광지 표준데이터** — Sprint 5 박물관/미술관 라인에 추가. `data.go.kr-
  standard.tourism_points` (place kind, 카테고리는 `01 TOURISM` 아래 세분류로
  매핑 — kraddr-base category catalog의 8자리 코드).
- **provider 라이브러리 책임**: `python-datagokr-api`에서 client + typed
  model + iter_pages를 안정화. 본 라이브러리는 import + 변환 함수만.
- **dataset_key 명명**:
  - `datagokr_tourism_points` (관광지)
  - `datagokr_cultural_festivals` (축제)
- **Sprint 2 1단계 PR scope 갱신**: visitkorea festival → datagokr_cultural_
  festivals로 변경. visitkorea는 Sprint 2 끝물에 enrichment PR 별도.

### 근거

- 표준데이터는 행정안전부 / 공공데이터포털이 안정 운영 — 갱신 주기가 명시되어
  있고 schema 변경이 announce.
- visitkorea TourAPI는 contentId 매핑은 좋으나 좌표 nullable이 많고 축제
  데이터 정합성이 들쭉날쭉.
- "여러 source가 같은 entity를 채운다"는 본 라이브러리의 1차 use case →
  표준데이터 primary + visitkorea enrichment 패턴이 정석.

### 결과 (긍정)

- 축제 데이터 baseline 품질 향상.
- `python-datagokr-api`를 본격 활용 → standard data 5종(관광지/축제/주차장/
  도로/박물관)이 동일 client로 들어옴.

### 결과 (부정)

- visitkorea를 1차에서 enrichment로 강등하면 Sprint 2 1단계 fixture/test가
  바뀜.
- 완화: ADR-034 9단계 1단계 description을 본 ADR에서 amendment — "축제 (data.
  go.kr-standard 1차 + visitkorea enrichment)"로 변경.

### 후속

- `docs/sprints/SPRINT-2.md` §2.1 갱신 — provider 1단계가 `data.go.kr-
  standard` + `python-datagokr-api`로.
- `docs/event-feature-etl.md` 1차 source를 datagokr 표준데이터로 정정,
  visitkorea는 enrichment 절로 보강.
- `docs/decisions.md` ADR-034 amendment — 9단계 1단계 표 행 수정.
- `python-datagokr-api` 측 client/model 검증 (별도 라이브러리 작업).
- `pyproject.toml` `[providers]` extra에 `python-datagokr-api` 핀 (Sprint 2
  진입 시).
- 본 라이브러리 신규 모듈 `src/krtour/map/providers/standard_data.py` —
  `tourism_points_to_bundles` / `cultural_festivals_to_bundles`.

---

## ADR-043: `@krtour/map-marker-react` npm 게시 보류 — 모노레포 내부 share로만

- **상태**: accepted (PR#33, 2026-05-27) — ADR-029를 supersede
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-029에서 `packages/map-marker-react/`를 별도 npm 패키지(`@krtour/map-
marker-react`)로 추출 + npm registry 게시까지 계획. 사용자가 검토 후 "npm
게시는 하지 말 것"으로 지시.

### 결정

- `packages/map-marker-react/` 코드 자체는 **유지** — 디버그 UI + TripMate
  apps/web이 같은 카테고리/maki 매핑을 공유하는 단일 source.
- **npm registry 게시 안 함** — `package.json`에 `"private": true` 박음.
- TripMate apps/web 등 외부 사용처는 git URL + commit sha 또는 yarn/pnpm
  workspace로 import (모노레포 내부 share).
- `@krtour/map-marker-react` scope 이름은 유지(이전 등록 X). 향후 다시
  registry 게시 필요해지면 새 ADR로 unfreeze.

### 근거

- npm registry 게시는 namespace 점유 / 버전 관리 / 보안 책임이 따른다.
- 본 라이브러리 + TripMate 둘만이 사용처라 git share로 충분.
- 사용자 결정 — registry 외부 노출 보류는 보안/유지보수 비용 절약.

### 결과 (긍정)

- npm 계정/2FA/access token 관리 회피.
- 라이브러리 코드 변경이 즉시 디버그 UI/TripMate에 반영 (git URL refresh).

### 결과 (부정)

- 외부 OSS 사용자가 본 패키지를 쓰려면 git clone + workspace 설정 필요 —
  진입장벽 약간 상승. (현재 외부 OSS user 0 → 비용 없음.)

### 후속

- `packages/map-marker-react/package.json`에 `"private": true` 박음.
- ADR-029 status `superseded by ADR-043` 표기 (본 PR 동시).
- `docs/journal.md`에 결정 reverse note.
- `pyproject.toml`/TripMate `package.json` 등에서 `@krtour/map-marker-react`
  의존성은 git URL 형식 유지(npm install registry 의존 X).

---

## ADR-044: 관련 라이브러리 로컬(`F:\dev\` / `~/dev/`) 우선 조회 + 데이터 정합성 책임은 각 라이브러리

- **상태**: accepted (2026-05-28)
- **날짜**: 2026-05-28
- **결정자**: 사용자

### 컨텍스트

본 라이브러리는 형제 `python-*-api` provider 라이브러리들(`python-kma-api`,
`python-opinet-api`, `python-krex-api`, `python-datagokr-api`, `python-
visitkorea-api`, `python-knps-api`, ... + `maplibre-vworld-js`)을 참조한다
(Protocol shape 확인 / API 스펙 조사 / 디버그 live loader wiring 등). 이들은
모두 같은 개발 머신의 `F:\dev\` (WSL: `~/dev/`) 아래 **로컬에 체크아웃**되어
있다.

PR#53 작업 중 실제 사고가 발생: 디버그 ETL live loader 조사에서 `python-
datagokr-api`를 **GitHub API로만 확인**(404 → private/미존재로 오판)하여
"repo 부재, wiring 불가"로 잘못 보류했다. 그러나 `F:\dev\python-datagokr-api`
는 로컬에 멀쩡히 존재했다. 같은 맥락에서 OpiNet product code 매핑(K015/C004)이
본 lib와 upstream `python-opinet-api`가 **불일치**했는데, 어느 쪽이 정답인지의
1차 근거는 provider 라이브러리(+공식 API 스펙)였다.

### 결정

**1. 관련 라이브러리는 로컬 `F:\dev\` (WSL `~/dev/`)를 먼저 탐색한다.**
- provider 라이브러리 / 형제 라이브러리의 client·model·codes·스펙을 확인할
  때는 **로컬 체크아웃을 1차 source**로 본다 (`F:\dev\python-*-api/src/...`).
- GitHub 원격 fetch(`raw.githubusercontent`/`gh api`)는 **로컬에 없을 때만**
  fallback. GitHub 404/private는 "존재하지 않음"의 근거가 **아니다** — 먼저
  로컬을 본다.
- AI 에이전트(Claude/Codex/Antigravity)도 동일 — `Glob`/`Read`로 `F:\dev\`
  로컬을 먼저 조회한 뒤에야 원격 조사로 넘어간다.

**2. 데이터 정합성(코드 매핑 / 필드 의미 / 단위 / 분류값)의 1차 책임은 각
provider 라이브러리에 있다.**
- 예: OpiNet 제품코드(B027/D047/...)의 의미·매핑은 `python-opinet-api`가
  authoritative. 본 lib는 그 정의를 **신뢰·미러**한다.
- 본 lib에서 불일치를 발견하면 **provider 라이브러리(+공식 API 스펙)를 기준**
  으로 정렬하고, 필요 시 해당 라이브러리에 **직접 PR로 수정**한다 (maplibre-
  vworld-js 양방향 PR 패턴, ADR-025 2차 보강과 동일 정신).
- 본 lib는 provider별 의미를 재정의·재해석하지 않는다 — 변환(정규화)만 한다
  (ADR-006 wrapper 금지 정신의 연장).

### 근거

- 로컬 우선 조회: 정확(실제 설치 버전과 일치) + 빠름(네트워크 X) + private repo
  접근 문제 회피. GitHub 404 오판 같은 사고 방지.
- 데이터 정합성 책임 분계: provider 라이브러리가 원천 API와 1:1로 마주하므로
  코드·의미의 single source of truth. 본 lib가 독자 매핑을 들고 있으면 drift
  (PR#53 K015/C004 사고)가 재발.

### 결과 (긍정)

- provider 스펙 조사가 정확·신속. 디버그 live loader wiring 시 로컬 client를
  근거로 faithful하게 매핑.
- 데이터 정합성 버그의 책임 소재가 명확 — provider 라이브러리에서 고치면 본
  lib + TripMate 전체가 일관.

### 결과 (부정)

- 로컬 체크아웃이 stale할 수 있음 → 정기 `git pull` 필요(개발 환경 책임).
- provider 라이브러리에 PR을 보내야 하는 경우 round-trip 비용.

### 후속

- `AGENTS.md` — 에이전트 운영 룰에 "관련 라이브러리 로컬 우선 조회" 추가.
- `CLAUDE.md` §4 — `F:\dev\` 형제 repo 목록 + 우선 조회 룰 명시.
- `docs/provider-contract.md` — 데이터 정합성 책임 = 각 라이브러리 절 추가.
- `docs/dev-environment.md` — `F:\dev\` provider 라이브러리 로컬 레이아웃.

---

## ADR-045: krtour-map은 Docker 독립 프로그램으로 운영하고 TripMate는 OpenAPI로 연동

- **상태**: accepted (2026-06-01)
- **날짜**: 2026-06-01
- **결정자**: 사용자
- **supersedes**: ADR-003의 TripMate 함수 직접 호출 운영 모델, ADR-035의 "debug-ui"
  범위 표현 일부

### 컨텍스트

초기 v2 설계는 `python-krtour-map`을 TripMate가 같은 Python process에서 import하는
하부 라이브러리로 정의했다. 그러나 admin 기능 범위가 feature 전체 운영, provider
강제 적재, 중복/결측 검토, offline upload, Dagster 기반 업데이트 큐까지 커지면서
다음 요구가 확정됐다.

- krtour-map은 TripMate와 별개로 Docker에서 실행되는 **독자 프로그램**이어야 한다.
- DB도 TripMate 공유 DB가 아니라 krtour-map이 소유하는 독립 PostgreSQL/PostGIS DB다.
- Dagster도 TripMate와 별개로 krtour-map 프로그램 안에 둔다.
- TripMate와 krtour-map 사이의 통신은 OpenAPI 기반 HTTP API로 한다.
- OpenAPI는 우선 admin UI를 기준으로 설계하고, TripMate 연동 시 필요한 사용자/서비스
  API를 보완·확장한다.
- Dagster는 feature 업데이트를 수행하는 내부 실행 엔진이며, OpenAPI로 즉시 실행
  또는 큐잉을 제어할 수 있어야 한다.

### 결정

1. **운영 단위**
   - krtour-map은 Docker Compose 또는 단일 배포 묶음으로 실행되는 독립 프로그램이다.
   - 논리 서비스는 `api`(FastAPI/OpenAPI), `frontend`(Next.js admin UI),
     `dagster`(feature update orchestration), `postgres`(독립 PostGIS DB),
     선택 `rustfs`(객체 저장소)로 나눈다.
   - `krtour-map-admin` 패키지는 구 `krtour-map-debug-ui`에서 rename 완료된
     **krtour-map admin/API 프로그램**이다. 역할은 "debug UI"를 넘어 독립
     프로그램의 API/admin 표면을 제공한다(ADR-020 amendment, PR#148).

2. **TripMate 연동**
   - TripMate는 `python-krtour-map`을 직접 import하지 않는다.
   - TripMate는 krtour-map OpenAPI client를 생성해 HTTP로 feature 조회/상세/업데이트
     요청을 호출한다.
   - TripMate는 krtour-map DB에 직접 연결하지 않는다.
   - TripMate 도메인 테이블은 `feature_id`를 외부 참조 값으로 저장할 수 있지만 FK는
     TripMate DB 안에서 걸지 않는다.

3. **OpenAPI 우선순위**
   - 1차 OpenAPI는 admin UI가 쓰는 API를 기준으로 작성한다.
   - admin API는 `/admin/...`, `/ops/...`, `/features/...`, `/debug/...` prefix를
     사용한다.
   - TripMate 사용자/서비스 연동 API는 admin API를 재사용하되, 필요한 응답 경량화,
     공개 필드 제한, batch 조회, 캐시 헤더 등을 후속으로 추가한다.
   - OpenAPI schema drift gate는 계속 유지한다(ADR-031).

4. **독립 DB**
   - 운영 DB 이름 기본값은 `krtour_map`.
   - schema는 기존 `feature`, `provider_sync`, `ops`, `x_extension`을 유지한다.
   - 필요하면 Dagster metadata는 같은 PostgreSQL instance의 별도 DB
     `krtour_map_dagster` 또는 별도 schema로 둔다. 운영 단순성을 위해 Docker Compose
     기본값은 같은 Postgres container 안의 별도 DB를 권장한다.

5. **독립 Dagster**
   - Dagster asset/job/schedule은 TripMate가 아니라 krtour-map 프로그램 소유다.
   - provider 정기 적재, feature 업데이트, consistency check, dedup candidate refresh,
     offline upload load는 krtour-map Dagster가 실행한다.
   - admin API는 Dagster run을 직접 만들거나 `ops.import_jobs`에 queue item을 만들고,
     Dagster sensor/worker가 이를 claim해 실행한다.
   - 동일 provider/dataset/scope 또는 destructive job은 ADR-039 advisory lock을
     적용한다.

6. **OpenAPI 기반 feature update 요청**
   - admin UI 또는 TripMate는 OpenAPI로 feature update request를 만들 수 있다.
   - 지원 scope:
     - `feature_ids`: 특정 feature_id 목록 업데이트.
     - `center_radius`: 특정 좌표 중심 반경 `n` km 안의 feature 업데이트.
     - `sigungu_by_radius`: 특정 좌표 중심 반경 `n` km와 교차하거나 그 안에 있는
       시군구를 계산하고, 해당 시군구의 feature를 업데이트.
     - `bbox`: bbox 안의 feature 업데이트.
     - `provider_dataset`: 특정 provider/dataset/sync_scope 업데이트.
   - 실행 방식:
     - `run_mode="queued"`: queue에 등록 후 worker/Dagster가 순서대로 실행.
     - `run_mode="now"`: 가능한 즉시 실행. 단 lock이 잡혀 있으면 409 또는 queued
       fallback 정책을 명확히 반환.
     - `dry_run=true`: 대상 feature/provider count와 예상 작업만 계산하고 실행하지 않음.

7. **Frontend stack**
   - admin frontend는 Next.js, React, TypeScript, TanStack Query, Zustand, Zod,
     React Hook Form, shadcn/ui, maplibre-vworld-js, `@krtour/map-marker-react`를
     표준 stack으로 쓴다.
   - 서버 상태는 TanStack Query, 클라이언트 UI 상태는 Zustand, form 검증은
     React Hook Form + Zod resolver, 공통 UI primitive는 shadcn/ui를 사용한다.
   - frontend 작업 후에는 React Doctor를 실행하고 결과를 검토·개선해야 한다.

### 근거

- admin/운영 기능이 커지면 TripMate process 안에 라이브러리로 끼워 넣는 방식은
  배포·장애 격리·DB 소유권이 흐려진다.
- 독립 DB와 OpenAPI는 TripMate와 krtour-map의 데이터/운영 책임을 명확히 나눈다.
- Dagster가 krtour-map 내부에 있으면 provider rate limit, 정합성 검사, offline
  upload load, feature update queue를 한 곳에서 제어할 수 있다.
- OpenAPI를 admin UI 기준으로 먼저 만들면 실제 운영 화면이 API 계약을 계속 검증한다.
  TripMate 연동 API는 이후 필요한 공개 범위에 맞춰 얇게 확장하면 된다.

### 결과 (긍정)

- krtour-map 배포, DB migration, provider key, Dagster schedule을 TripMate와 독립적으로
  운영할 수 있다.
- TripMate는 HTTP/OpenAPI client만 알면 되므로 언어·프로세스·DB 경계가 명확하다.
- admin UI와 TripMate가 같은 OpenAPI 기반 계약을 공유하므로 schema drift를 줄인다.
- 지리 범위 기반 업데이트를 queue로 제어할 수 있어 운영자가 문제 구역만 즉시
  재적재할 수 있다.

### 결과 (부정)

- HTTP boundary가 생겨 직렬화/네트워크 비용과 장애 지점이 늘어난다.
- OpenAPI versioning, client generation, backward compatibility 관리가 필요하다.
- 기존 문서의 "TripMate 함수 직접 호출/공유 DB" 표현을 ADR-045 기준으로 정리해야
  한다.
- Docker Compose, Dagster metadata DB, migration 순서까지 운영해야 한다.

### 후속

- `docs/architecture.md` 큰 그림을 독립 프로그램 모델로 갱신.
- `docs/debug-ui-package.md`와 `docs/debug-ui-admin-workflows.md`에 standalone,
  OpenAPI, frontend stack, React Doctor, Dagster queue 제어 사양 반영.
- `docs/dagster-boundary.md`를 TripMate-owned Dagster에서 krtour-map-owned Dagster로
  갱신.
- `docs/tripmate-integration.md`는 OpenAPI 연동 문서로 재작성 또는 supersede banner
  추가.
- Docker Compose 운영 문서와 admin-first OpenAPI 계약 문서 추가.

---

## ADR-046: ADR-045 이행은 호환 shim 없이 정본 방향으로 전환하고 주소는 kraddr-geo REST v2로 통일

- **상태**: accepted
- **날짜**: 2026-06-02
- **결정자**: 사용자
- **관련**: ADR-041, ADR-045

### 컨텍스트

ADR-045로 krtour-map 운영 모델이 Docker 독립 프로그램 + 독립 DB/Dagster +
TripMate OpenAPI 연동으로 바뀌었다. 또한 ADR-041로 `python-kraddr-base` 의존을
제거하고 좌표는 `Coordinate`, 주소는 `Address`로 본 저장소가 소유한다. 문서와
일부 예시에는 여전히 다음 구 모델 표현이 남아 있었다.

- `krtour-map-debug-ui`, `map_debug_ui`, `KRTOUR_MAP_DEBUG_UI_*` 같은 구 패키지명/env.
- TripMate가 `python-krtour-map`을 직접 import하거나 같은 DB를 공유하는 흐름.
- TripMate-owned Dagster asset이 provider 적재를 직접 수행하는 흐름.
- provider 주소 문자열이나 자체 행정코드를 그대로 `features.address`/행정코드로
  저장하는 흐름.
- kraddr-geo v1 `/v1/address/*` 또는 `PlaceCoordinate`/`kraddr.base.Address` 예시.

사용자는 "호환성 신경 안쓰고 올바른 방향으로 검토"와 "kraddr geo rest api는 v2로
다 바꿔"를 지시했고, provider 주소도 kraddr-geo를 통해 얻은 주소로 통일하며
결측값과 주소/좌표 불일치도 admin UI에서 수동 처리할 수 있어야 한다고 확정했다.

### 결정

1. **구 모델 호환 shim 금지**
   - 구 패키지 경로 `packages/krtour-map-debug-ui/`, Python namespace
     `krtour.map_debug_ui`, env prefix `KRTOUR_MAP_DEBUG_UI_*` 호환 shim을 만들지
     않는다.
   - TripMate 직접 import, 공유 DB, TripMate-owned Dagster 경로를 유지하기 위한
     adapter도 만들지 않는다.
   - 문서와 코드의 정본은 `krtour-map-admin`, `krtour.map_admin`,
     `KRTOUR_MAP_ADMIN_*`, OpenAPI, 독립 DB/Dagster다.

2. **kraddr-geo REST v2만 사용**
   - 주소/좌표 보강은 `POST /v2/reverse`, `POST /v2/geocode`만 정본으로 문서화한다.
   - `/v1/address/*`는 역사 기록 외 실행 문서에서 사용하지 않는다.
   - health check 같은 운영 endpoint는 이 ADR의 주소 정/역지오코딩 계약 범위 밖이다.
     주소 기능 문서와 krtour-map 구현 지시는 kraddr-geo REST v2만 기준으로 삼는다.

3. **주소 정본은 kraddr-geo 결과**
   - provider가 제공하는 주소 문자열, 시군구명, 자체 행정코드는 raw/provenance다.
   - `features.address`, `legal_dong_code`, `sigungu_code`, `sido_code`,
     `road_name_code`, `road_address_management_no`, `zipcode`의 정본은 kraddr-geo
     REST v2 결과로 만든 `krtour.map.dto.Address`다.
   - 좌표가 있으면 좌표 기준 `POST /v2/reverse` 결과를 정본 주소로 삼는다.
   - 좌표가 없고 주소 문자열이 있으면 `POST /v2/geocode`로 좌표 후보를 얻고,
     다시 `POST /v2/reverse`로 주소를 정규화한다.
   - 좌표와 주소가 모두 있으면 좌표 기준 reverse 결과와 provider 주소를 비교해
     `AddressMatchReport`를 남긴다.

4. **결측/불일치는 admin issue로 수동 처리**
   - kraddr-geo 호출 실패, 결과 없음, confidence 미달, provider 주소와 좌표 기준 주소
     불일치, 법정동코드 충돌은 `ops.data_integrity_violations` 또는 후속 주소 검토
     큐에 올린다.
   - Admin UI는 `provider_address_mismatch`, `provider_address_partial_match`,
     `geocode_failed`, `reverse_geocode_failed`, `missing_address`, `missing_bjd_code`
     issue를 지도/테이블에서 보여준다.
   - 운영자는 admin UI에서 kraddr-geo 재시도, 좌표 수정, 주소 수정, kraddr-geo 주소
     채택, 수동 override, ignored/reopen 처리를 할 수 있어야 한다.
   - 수동 override는 `ops.feature_overrides`와 audit log에 기록하고 provider 재적재가
     덮어쓰지 않도록 한다.

### 근거

- 호환 shim은 이행 기간을 길게 만들고 에이전트가 구 경로를 계속 복붙하게 만든다.
- provider 주소와 행정코드는 형식·정밀도·의미가 provider마다 달라 정본으로 삼기 어렵다.
- kraddr-geo는 주소/좌표/행정구역 정규화 전용 서비스이므로 정본 책임을 한 곳에 모으는
  편이 운영상 명확하다.
- 주소와 좌표가 동시에 있을 때는 좌표가 지도 feature의 실제 위치를 결정하므로, 좌표
  기준 reverse 결과를 우선하고 provider 주소는 검증 대상으로 쓰는 편이 일관적이다.

### 결과 (긍정)

- 문서와 코드 경계가 단순해진다. 새 구현자는 하나의 이름/환경/API만 따른다.
- feature 주소와 행정코드 품질이 provider별 편차에 덜 흔들린다.
- 주소/좌표 오류가 운영 큐로 표면화되어 admin UI에서 수정 가능하다.

### 결과 (부정)

- 구 env/import/path를 쓰는 로컬 스크립트는 깨질 수 있다. 의도된 결과다.
- kraddr-geo 장애 시 provider 적재의 주소 품질이 떨어지고 issue가 증가한다.
- 좌표가 잘못된 provider row는 주소도 잘못 정규화될 수 있으므로 admin 검토와
  manual override 흐름이 필수다.

### 후속

- 실행 문서의 `/v1/address/*`, `PlaceCoordinate`, `kraddr.base.Address`,
  TripMate-owned Dagster 표현을 정리한다.
- `docs/address-geocoding.md`에 주소 정본 정책과 `AddressMatchReport`/admin issue
  흐름을 명시한다.
- `docs/debug-ui-admin-workflows.md`와 `docs/openapi-admin-contract.md`에 주소 검토
  issue action을 추가한다.
- `ops.data_integrity_violations` 구현 시 주소/좌표 issue payload shape를 포함한다.

---

## ADR-047: krtour-map standalone 로컬 포트는 API 9011, admin UI 9012, Dagster 9013으로 고정

- **상태**: accepted
- **날짜**: 2026-06-02
- **결정자**: 사용자
- **관련**: ADR-020, ADR-035, ADR-045

### 컨텍스트

ADR-045 이후 krtour-map은 Docker 독립 프로그램 + 독립 DB/Dagster + admin UI를 함께
운영한다. 이전 문서와 스크립트에는 debug API `8087`, frontend `8610`, Dagster 기본
포트 같은 값이 섞여 있었고, Windows/WSL 하이브리드 검증에서 stale 프로세스가 같은
포트를 점유하면 브라우저가 다른 서버를 보는 문제가 반복됐다.

사용자는 API, 웹, Dagster 포트를 항상 일정하게 유지하고, 해당 포트를 점유한
프로세스가 있으면 종료 후 다시 올리라고 지시했다.

### 결정

1. krtour-map standalone의 로컬/개발/compose 기본 포트는 다음으로 고정한다.
   - API(FastAPI `krtour-map-admin`): `9011`
   - admin UI(Next.js): `9012`
   - Dagster UI/code location dev server: `9013`
2. `scripts/stop-fixed-ports.sh`는 기본으로 `9011`, `9012`, `9013` listener를 찾아
   종료한다. 로컬 stack과 Docker stack 기동 스크립트는 먼저 이 스크립트를 실행한다.
3. `.env`의 기존 provider service key 이름은 `scripts/load-env.sh`와
   `docker-compose.yml`에서 `KRTOUR_MAP_ADMIN_*`/`NEXT_PUBLIC_*` 환경변수로 매핑한다.
   평문 키는 git에 커밋하지 않는다.
4. Docker compose 1차 서비스는 `postgres`, `api`, `frontend`, `dagster`다. API
   컨테이너는 기동 전 `alembic upgrade head`를 실행한다. Dagster metadata DB 분리,
   daemon/schedule 운영, RustFS/backup 묶음은 후속 T-209b/T-209e에서 확장한다.

### 근거

- 포트를 고정해야 TripMate OpenAPI 연동, Windows Playwright, WSL 서버, Docker compose
  검증이 같은 주소를 바라본다.
- 점유 프로세스를 명시 종료한 뒤 기동해야 stale Next.js/uvicorn/Dagster 프로세스가
  검증 결과를 오염시키지 않는다.
- `.env`는 provider repo별 키 이름이 이미 다르므로, 실행 스크립트가 표준 env 이름으로
  한 번 매핑하는 편이 운영 실수를 줄인다.

### 결과 (긍정)

- 문서, 설정, 스크립트, Docker compose가 같은 포트 표준을 사용한다.
- `npm run admin:stack`, `npm run docker:up`, `npm run ports:stop`으로 같은 규칙을
  반복 실행할 수 있다.
- Docker image build와 local dev stack이 같은 `.env` 키 매핑을 공유한다.

### 결과 (부정)

- 기존 `8087`/`8610`을 직접 쓰던 로컬 북마크와 스크립트는 수정해야 한다.
- `docker compose config`나 compose 로그는 환경변수를 출력할 수 있으므로, 서비스 키가
  들어간 출력은 PR/문서에 붙이지 않는다.

### 후속

- admin UI Dagster 관측/관리 화면 1차는 `/admin/dagster` +
  `GET /ops/dagster/summary`로 보강했다. feature update queue와 sensor/worker 연결은
  별도 후속으로 둔다.
- Dagster metadata DB 분리, daemon/schedule/sensor 운영, RustFS/backup compose 확장은
  T-209b/T-209e에서 이어간다.

## ADR-048: REST API versioning을 admin/ops까지 확장하고 envelope·pagination·parameter·response 정합성 표준을 고정한다 (T-214/T-215 위에 보강)

- **상태**: accepted
- **날짜**: 2026-06-09
- **결정자**: 사용자
- **관련**: ADR-005(인증=인프라), ADR-035(namespace), ADR-044(provider 충실),
  ADR-045(TripMate OpenAPI 연동), ADR-046(무-shim),
  `docs/tripmate-rest-api.md`(#317, 외부 `/v1` 정본), `docs/rest-api.md`(전 표면 보강),
  `docs/reports/api-endpoint-review-2026-06-08.md`(검토 근거), T-214/T-215(#317)

### 컨텍스트

PR #317(T-214/T-215)이 REST API `/v1` 정리의 1차를 이미 끝냈다 — `docs/tripmate-rest-api.md`를
외부 `/v1` 목표 계약으로 재작성, `/tripmate/feature-update-requests*` alias 제거(admin
단일화), place/event **단건 feature 추가·수정·삭제 admin API**(K-15 해소) + version 0(provider)/
1(user) 분리(`feature.feature_versions`/`ops.feature_change_requests`/
`KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE`). 보안 스킴(P1-B)은 #314로 이미 해소.

`docs/reports/api-endpoint-review-2026-06-08.md` findings를 **전부** 닫으려면 #317 범위 밖의
두 가지가 남는다. (1) #317 T-214b는 **`/admin`·`/ops`·`/debug`를 비버저닝으로 고정**했는데,
사용자는 **admin 표면도 versioning**하라고 지시했다. (2) envelope/pagination/parameter/
response의 **코드 실측 불일치**(라우터별 `*Meta` 중복, page-size 파라미터 3종·캡 3종,
bbox 인코딩 2종, `status`↔`state`, 응답 `*_key`↔`*_id`)가 #317의 고수준 정리 아래에 남아
있다. 본 ADR은 #317 위에 이 두 가지를 보강한다.

### 결정 (#317 위의 delta)

1. **versioning을 전 표면으로 확장.** #317 T-214b/§2.1의 "`/admin`·`/ops`·`/debug` 비버저닝"을
   **supersede**하여 `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`도 `/v1` 아래 둔다(사용자 지시).
   liveness `/health`·`/version`만 비버저닝 유지. 외부 표면(`/v1/features`(batch 포함)·
   `/v1/categories`·`/v1/providers`)은 #317 T-214b/d가 진행 중인 그대로. **`/tripmate/*`
   namespace는 제거**(krtour-map은 TripMate 전용이 아니다; batch → `/v1/features/batch`).
2. **envelope 공유 모델 — payload와 메타 완전 분리.** 라우터별 `*Meta` 중복을 공유
   `Meta`로 통합한다. `data`는 **payload만**(단건=객체, 목록=`{items:[...]}`, in-bounds=
   `{clusters,items}`, batch=`{found:{feature_id:Feature},missing:[...]}`). **`items`는 list array
   전용**이고 id-keyed map은 `found`처럼 별도 키를 쓴다. **페이지네이션·추적·뷰 해석 메타는
   `meta`로 모은다**: `meta = { duration_ms, request_id, page?: { page_size, next_cursor, total },
   cluster?: { cluster_unit } }`(`page`는 pageable 목록에만, `total`은 opt-in null 기본,
   `cluster`는 in-bounds에만). 즉 `data.next_cursor`/`data.total_count`/`data.cluster_unit`/
   파생 `count`를 **폐기**하고 `meta.page`/`meta.cluster`로 일원화한다(payload=데이터,
   meta=cross-cutting → 확장 시 meta만 늘리면 됨). 성공 응답에도 `request_id`를 실어 오류
   envelope와 대칭.
3. **pagination 단일화(T-214e 심화).** page-size 파라미터를 `page_size`로 통일
   (`limit`/`run_limit`/`event_limit` 폐기), 2-티어 캡(기본 50/200, 지도 nearby 100/500),
   opaque `cursor`. `/v1/features` 평면은 keyset cursor(현재 `limit le=5000` 폐기),
   `/v1/features/in-bounds`는 cursor 없이 `max_items` 하드캡 5000→2000 + 결정적 `feature_id`
   정렬(T-212d). `total`은 `?include_total=true` opt-in(현재 `search`는 항상 COUNT).
4. **parameter 일관성(T-214e 심화).** bbox는 분리 float 4개로 통일(`search` CSV `bbox`
   제거, clean cut). 다중값 필터는 단수 반복(`kind`/`category`/`provider`/`status`). lifecycle 상태
   필드는 `status`로 통일(`import-jobs`/`offline-uploads`/`feature-update-requests`의 `state`
   개명; `severity` 별개 축 유지). issue/violation noun은 외부 표면에서 `issue_*`로 통일.
5. **에러 problem+json(T-214g 보강).** `{error:{…}}`를 RFC 7807 `application/problem+json`
   (`type`/`title`/`status`/`detail` + 확장 `code`/`request_id`/`errors[]`)으로 발전.
   `code`·`request_id`는 problem+json 객체의 **top-level 확장 멤버**로 두고(소비자 파싱 위치
   고정), 코드 enum(`FEATURE_NOT_FOUND`/`INVALID_BBOX`/`TOO_MANY_IDS`/`VALIDATION_ERROR`/
   `RATE_LIMITED`/`LOCK_BUSY`/`DESTRUCTIVE_DISABLED`/`UNAUTHORIZED`/`UPSTREAM_UNAVAILABLE`)을
   확장 `code`로 유지한다.
6. **응답 식별자 접미사 규약 — 의미(본질) 기준 전면 적용.** 호환성/외부 동결 같은 동기는
   두지 않고 **의미**로만 정한다: 시스템 단일 surrogate = `*_id`, **복합/자연키 = `*_key`**.
   응답 본문 전체(외부 read 포함)에 적용 — surrogate인 `review_id`→`review_id`,
   `issue_id`→`issue_id`, `system_log_id`/`api_call_log_id`/`override_id`/`step_id`→
   `*_id`. **`*_key` 유지는 본질이 자연/복합키인 것**: **`cluster_key`(행정구역 코드 sido/
   sigungu/eupmyeondong = 자연키 → 유지, #316 재리뷰 C; 2차의 `cluster_id` 개명을 철회)**,
   복합 자연키 `target_key`(+`external_system`), provider/source 어휘(ADR-044), canonical
   `feature_id`. `lon`/`lat`/`name`/`category`/`marker_*`/`status`는 이미 일관 → 불변.
7. **명명 통일을 코드/DB 레벨까지 전파.** REST 단 개명을 영구 edge 매핑으로 두면 ADR-046
   (무-shim)과 어긋나므로, **surrogate 식별자/상태를 물리 컬럼·ORM 속성·repo 함수/변수까지
   end-to-end 정렬**(테이블별 1-PR migration, codegraph impact 선행). 대상: `review_id`→
   `review_id`, `issue_id`→`issue_id`, ops 로그/내부 키 `*_key`→`*_id`, `state`→`status`.
   **경계(개명 금지 — 자연/복합/provider/canonical)**: `cluster_key`(행정코드 자연키),
   `target_key`(+`external_system`), provider/source 어휘(ADR-044 — `dataset_key`/
   `source_record_key`/`source_entity_id`/`source_dataset_key`/`raw_*`), canonical `feature_id`.
8. **action sub-resource 규약(확장성).** 부수효과 있는 상태 전이(Dagster 트리거/snapshot/
   lock/승인·거절)는 `POST {collection}/{id}/{verb}`(`deactivate`/`cancel`/`run-now`/`approve`/
   `reject`/`load`/`validate`/`swap`), 순수 필드 수정은 `PATCH {id}`, 생성은 `POST {collection}`,
   조회는 `GET`. 이 규약을 계약에 명시해 신규 action도 같은 형태로 확장한다.
9. **정본 관계 — 단일 전 표면 정본으로 수렴.** drift 회피를 위해 **`docs/rest-api.md`를 전
   표면(외부+admin/ops) 계약 단일 정본**으로 두고, `docs/tripmate-rest-api.md`는 TripMate
   **소비 매핑 view**로 축소(계약 세부는 rest-api.md로 위임). 기계 정본 =
   `openapi.json`/`openapi.user.json`. 충돌 시 OpenAPI 우선. (수렴은 T-216g.)
10. **좌표 필드명 cross-repo 정렬 = `lon`/`lat`(#316 재리뷰 B).** TripMate 정본(DEC-07)은
    `longitude`/`latitude`지만, krtour는 `lon`/`lat`로 이미 일관하고 대용량 지도 feature
    payload에 terse가 바이트·파싱에 유리하다. **krtour 정본 = `lon`/`lat` 유지**, TripMate가
    DEC-07을 `lon`/`lat`로 하향 정렬해 **경계 매핑 0**으로 만든다.
11. **`feature_id` 값 불변식(#316 재리뷰 D — 안정성 최우선).** 외부 `feature_id` **값**은
    provider 재적재·사용자 편집(#317 v0/v1)·버전 승급·soft delete에도 **절대 바뀌지 않는다**.
    정체성이 바뀌는 사건(bjd 변경 등)은 **id 변경이 아니라 새 feature + link**로 모델링한다.
    이름 동결(#6)과 **별개로 값 불변**을 외부 계약에 명문화한다(소비자가 FK·snapshot 키로 영속).
12. **envelope 불변식(#316 재리뷰 E).** `meta`는 **모든 응답에 항상 present**(단건 GET 포함)
    하고, 모든 응답(성공 `meta` 또는 problem+json)은 `request_id`를 싣는다. `meta.page.next_cursor`
    는 **항상 키로 존재**하고 소진 시 `null`(omit 금지) — 페이지 종료 신호를 계약으로 lock.
13. **`/vN` major 거버넌스(#316 재리뷰 F).** hard cutover 하에서 `/v1`→`/v2`가 유일한 breaking
    수단이므로 규칙을 둔다: **pre-1.0(현재)** = `/v1` 가변, in-place breaking 허용(지금 정리
    방침과 일치). **v1.0.0 GA에서 `/v1` 동결**, 이후 breaking = `/v2` + N-1 동시지원. OpenAPI는
    major별 분리 export.
14. **Base URL과 path 분리(#316 추가 리뷰).** 환경변수 base URL은 host root까지만 포함하고
    `/v1`는 path에 둔다(예: base `http://127.0.0.1:9011` + path `/v1/features/search`).
    base와 path 양쪽에 `/v1`를 중복 삽입하지 않는다.

### 근거

- 사용자가 admin 표면 versioning을 명시 지시 — breaking 분리 수단을 운영 표면에도 둔다.
- 코드 실측 불일치(파라미터 3종·캡 3종·`*Meta` 중복·`total_count` 항상 COUNT)는 #317의
  고수준 정리만으로는 닫히지 않으며, 공유 모델·opt-in count로 예측가능성·비용을 개선한다.
- 내부 어휘를 물리 레벨까지 정렬하면 영구 매핑 shim을 피한다(ADR-046). provider/복합키 경계는
  ADR-044로 보존.

### 결과 (긍정)

- 외부+내부 전 표면이 버전·envelope·pagination·error·명명 규약을 공유한다.
- `*Meta` 통합 + `request_id` 전파로 응답 셰입을 한 곳에서 진화시키고 상관추적을 일관화.

### 결과 (부정)

- admin/ops도 `/v1`로 이동 — #317이 비버저닝으로 둔 결정을 되돌려 라우터 mount·OpenAPI
  export·frontend·docs를 admin/ops까지 일괄 갱신해야 한다.
- 내부 식별자 물리 개명은 테이블별 migration + 큰 mechanical churn(`review_id` 291·
  `issue_id` 118건)을 동반 — codegraph impact 후 단계화.
- **무-호환 clean cut**: envelope 재배치(`data.next_cursor`→`meta.page`)·파라미터/필드 개명·
  좌표명 정렬(`lon`/`lat`)·구 경로 제거가 소비자(TripMate)를 한 번에 깬다. pre-prod 단계라
  의도적으로 수용 — 안정 spec commit에서 소비자가 lockstep으로 추종한다(T-181).

### 전환 정책 — 무-호환 clean cut (#316 2차 리뷰, 사용자 지시)

사용자 지시 = **호환성은 고려하지 않는다. 늦기 전에 일관성·확장성·안정성으로 한 번에
정리한다.** TripMate는 pre-production 소비자이므로 최신 spec을 따라오면 된다.

- **dual-support/deprecation 창 없음**: 구 unprefixed 경로·호환 alias를 유지하지 않고 `/v1`로
  **즉시 단일 전환**한다(이중 코드경로 제거 = 안정성). `/debug/health`·`/debug/version`은
  deprecate가 아니라 **제거**(→ `/health`·`/version`·`/v1/ops/health-deep`로 수렴).
- **개명도 즉시 전면 적용(의미 기준)**: 명명 규칙을 외부 read 포함 한 번에 적용(#6·#7).
  단 `cluster_key`(행정코드 자연키)는 규칙상 `*_key`가 맞아 **유지**(동결이 아니라 본질).
  `longitude`/`latitude`↔`lon`/`lat` cross-repo 정렬도 이 컷에서 처리(#10).
- **기계 정본 + codegen pin**: `openapi.json`/`openapi.user.json`을 기계 정본으로 유지하고,
  `/v1` 안정 commit에서 소비자(T-210e codegen + 계약 테스트)가 그 spec에 핀한다. 이게
  유일한 "안전판"이며, 별도 호환 창은 두지 않는다.
- **에러 `code` 고정**: problem+json top-level 확장 `code`/`request_id` + enum(#5).
- **Base URL은 host root**: `/v1`는 path에만 둔다(#14).

### 후속

- 실행은 `docs/tasks.md` **Phase 6.8 / T-216a~g**로 분해(#317의 T-214/T-215와 별도 번호).
  `docs/tripmate-rest-api.md` §2.1의 "admin/ops 비버저닝" 문구는 본 ADR로 갱신했다.
- **반영 순서**: 외부+admin `/v1` clean cut(T-216a/b) → 명명·코드/DB 전파(T-216e/f) →
  정본 수렴(T-216g). API shape `/v1` 안정 commit에서 T-210e(codegen) 진행. 소비자(TripMate)는
  안정 spec commit 기준으로 base/에러파싱/파라미터/필드명을 일괄 갱신한다.

## ADR-049: TripMate-agent YouTube 장소 후보는 `tripmate-agent-youtube` provider로 pull한다

### 상태

Accepted (2026-06-10)

### 배경

TripMate-agent는 YouTube 여행 콘텐츠에서 장소 후보, 영상·채널·플레이리스트 근거,
외부 geocoding evidence를 만든다. 그러나 krtour-map feature schema와 `feature_id`
생성 책임은 `python-krtour-map`에 있다. TripMate-agent가 krtour-map DB나
`FeatureBundle` schema에 직접 쓰면 ADR-045의 독립 프로그램 경계와 owner 책임이 흐려진다.

### 결정

- canonical provider name은 `tripmate-agent-youtube`로 둔다.
- dataset_key는 `youtube_place_candidates`, source_entity_type은
  `extracted_place_candidate`를 기본값으로 둔다.
- TripMate-agent는 snapshot/changes REST export를 제공한다. 외부 호출이므로
  TripMate-agent ADR-24의 `X-API-Key` 인증을 그대로 사용한다.
  (경로는 ADR-050에서 `/api/v1/features/{snapshot,changes}`로 보정 — downstream
  이름을 path에 넣지 않는다.)
- krtour-map Dagster는 이 export를 HTTP로 pull하고, `providers.tripmate_agent`의
  순수 변환 함수가 export item JSON을 `FeatureBundle`로 바꾼다.
- 최종 `feature_id`, `SourceRecord.source_record_key`, `SourceLink` 생성과 PostGIS
  적재는 krtour-map 책임이다.
- `operation=upsert`만 즉시 `FeatureBundle`로 적재한다. `reject`/`tombstone`은
  적재형 bundle로 표현하지 않고 export ledger/cursor 영속화 후속에서 별도 상태 전이로
  처리한다.

### 근거

- TripMate-agent는 외부 app provider이고, krtour-map은 feature owner다.
- full snapshot과 incremental changes를 모두 pull할 수 있어 재동기화와 운영 효율을
  분리할 수 있다.
- provider wrapper/adapter 금지(ADR-006)를 지키기 위해 krtour-map에는 client facade가
  아니라 fetcher resource와 순수 변환 함수만 둔다.

### 결과

- `core.providers.CANONICAL_PROVIDER_NAMES`에 `tripmate-agent-youtube`를 추가한다.
- Dagster resource는 `KRTOUR_MAP_TRIPMATE_AGENT_BASE_URL`과
  `KRTOUR_MAP_TRIPMATE_AGENT_API_KEY`를 사용한다. API key 값은 TripMate-agent 운영
  `API_KEYS` 중 하나여야 한다.
- 실제 TripMate-agent export API 구현(T-066)이 배포되기 전까지 krtour-map live smoke는
  fake response/계약 테스트로 제한된다.

## ADR-050: TripMate-agent feature export 계약을 보강한다 — 경로 중립화·정본 위치·노출 정책·철회 라이프사이클

### 상태

Accepted (2026-06-10) — ADR-049 보강. 배경은 `docs/reports/service-completeness-review-2026-06-10.md`
§4 C-4 · §5 R-3/R-4, 의사결정 `docs/reports/decisions-needed-2026-06-10.md` D-03/D-04/D-05.

### 결정

1. **경로 중립화**: export 경로는 `/api/v1/features/snapshot`·`/api/v1/features/changes`다.
   REST path에 특정 downstream 이름(`krtour`)을 넣지 않는다 (ADR-049 표기 보정).
   krtour-map fetcher의 현재 하드코딩 `/api/v1/krtour/features/*`는 TripMate-agent
   T-066 배포와 동시에 정렬한다 (T-217a).
2. **계약 정본 위치**: export 계약(스키마·cursor·operation)의 정본은 **TripMate-agent
   repo의 독립 계약 문서**(`docs/feature-export-api.md`류)다. 본 repo는
   `docs/rest-api.md` 계열에서 링크 + 소비 측 기대치(`{items, has_more, next_cursor}`,
   `X-API-Key`, env 키)만 요약한다. ADR-044 관행(데이터 정합성 1차 책임 = 공급 측)과 일치.
3. **노출 정책**: TripMate-agent는 **검수 통과 후보만 export**한다
   (`matched`/`user_corrected`; `needs_review`/`ignored` 제외). 검수 후 철회는
   `reject` operation으로 증분 export한다.
4. **철회 라이프사이클**: krtour-map은 `reject`/`tombstone` operation을 skip으로
   끝내지 않고 해당 feature의 **inactive 전환**(+사유 기록)으로 처리한다 — MOIS
   Step C(폐업→inactive)와 동형 (T-217b). 1단계로 skip 건수 WARN/admin 이슈 노출을
   선행할 수 있다.

### 근거

- path에 소비자 이름이 박히면 공급 API가 1:1 전용이 되어 확장(다른 소비자)이 막힌다.
- 계획 문서(`youtube-feature-pipeline-plan.md`)는 완료 후 동결되므로 계약 정본으로 부적합.
- 검수 전 후보가 일반 feature와 동급 노출되면 사용자 신뢰도 구분이 불가능하다.
- skip-only 처리는 철회된 후보를 feature로 영구 잔존시켜 데이터 품질을 해친다.

### 결과

- krtour-map: T-217a(fetcher 경로 정렬, T-066 배포와 동시) + T-217b(inactive 전환).
- TripMate-agent: T-066 구현 시 본 ADR 준수 — 상세 체크리스트는 해당 repo
  `docs/cross-repo-consistency-actions-2026-06-10.md` TA-01~03.
- inactive 전환된 feature의 소비자 응답 정책 확정(D-12, 2026-06-10): batch/단건
  read에서 **`found`에 포함하되 status(inactive)를 노출**한다 — `missing` 처리하면
  "삭제됨"과 "철회됨"을 구분할 수 없다. 기존 admin deactivate read 정책과 동일해야
  하며, T-217b에서 일관성 검증을 포함한다.

## ADR-051: TripMate 사용자 장소 제보는 krtour-map 서비스용 수신 API로 받는다

### 상태

Accepted (2026-06-10) — `docs/reports/decisions-needed-2026-06-10.md` D-02.

### 배경

설계된 흐름은 **2단 검토**다: TripMate 사용자가 feature 추가/수정/삭제를 요청
(`FeatureSuggestion`, 일일 한도 20건) → **TripMate admin이 1차 검토**(자체
`/admin/feature-requests` 큐) → 승인분이 krtour-map으로 전달 → **krtour-map admin이
최종 반영**(`/v1/admin/features*`·`/v1/admin/feature-update-requests*`,
`docs/tripmate-rest-api.md` §2 "제안 원본은 TripMate app DB 소유, 운영자 승인 후 전달").
이 설계에서 빠진 것은 사용자 요청 경로가 아니라 **TripMate admin 승인분 → krtour-map
사이의 자동 전송 구간**뿐이다 — TripMate public client의 `/v1/admin/*` 직접 호출은
금지(관리망 인증 경계)이므로 수동 운영자 입력 외 수단이 없다.

### 결정

- 기존 2단 검토 설계를 유지한다 — 1차 검토는 TripMate admin, 최종 반영은 krtour-map
  admin 책임 그대로.
- krtour-map에 **서비스용 수신 API**를 신설한다: `POST /v1/features/suggestions`
  (가칭, `X-Krtour-Service-Token` 인증 + rate-limit). 이 API는 사용자 원시 제보가
  아니라 **TripMate admin이 1차 승인한 요청**을 받는 전송 구간이다.
- 수신분은 기존 `admin/features/change-requests` 승인 큐로 합류한다 — krtour-map측
  별도 승인 flow를 만들지 않는다 (TripMate 1차 + krtour-map 최종의 2단 유지).
- TripMate는 admin 1차 승인 시점에 이 API로 릴레이한다 (TripMate TM-13).

### 결과

- 신규 task T-217c (API + change-requests 합류 + admin 표시 — 출처가 TripMate admin
  승인분임을 큐에서 식별 가능하게).
- 제보 페이로드의 사용자 식별 정보 범위 확정(D-11, 2026-06-10): **익명** —
  TripMate 측 불투명 참조 ID(suggestion_id)만 싣고 krtour-map은 개인정보를 저장하지
  않는다. 역추적이 필요하면 TripMate admin에서 수행한다 (PIPA 부담 비전이).
- 거절/반려의 역방향 통지(krtour-map 최종 거절 → TripMate admin 큐 상태 갱신)는
  1차 범위 외 — 필요해지면 후속 결정.

## ADR-052: RustFS 버킷은 당분간 공유하되 prefix 소유권을 명문화하고, 추후 전용 버킷으로 분리한다

### 상태

Accepted (2026-06-10, 잠정) — `docs/reports/decisions-needed-2026-06-10.md` D-01 옵션 (b)
채택, **추후 옵션 (a)(전용 버킷 분리)로 이행 예정**.

### 배경

TripMate-agent가 미디어 원본(영상/자막/전사/프레임, 무기한 보존)을 krtour-map 소유
버킷(`krtour-map`, prefix `features/`)에 직접 저장한다. krtour-map의 backup/restore·
수명주기·용량 책임과 충돌 소지가 있다.

### 결정

- **당분간 공유 유지**: 단일 RustFS(S3 `9003`/console `9004`)의 `krtour-map` 버킷을
  공유한다.
- **prefix 소유권 명문화**: TripMate-agent가 쓰는 prefix 이하 객체의 소유·수명주기·
  복구 책임은 TripMate-agent에 있다. krtour-map cold backup 범위에서 해당 prefix는
  **제외**한다 (T-217e에서 architecture.md·backup 문서에 반영).
- **추후 분리**: TripMate-agent 전용 버킷으로 분리한다. 분리 시점 확정(D-10,
  2026-06-10): **TripMate-agent T-066 운영 개시(krtour-map 실데이터 pull 시작) 전** —
  운영 데이터가 쌓이기 전이 마이그레이션 비용 최소다. 분리 작업 주체는 TripMate-agent
  (버킷 config + 객체 이전), krtour-map은 backup 정책 갱신만.

### 결과

- T-217e — 공유 정책을 `docs/architecture.md` rustfs 절 + backup/restore 문서에 명문화.
- TripMate-agent 측: 분리 전까지 버킷 기본값 의존 신규 기능 보류 권고 유지 (해당 repo
  TA-04).
