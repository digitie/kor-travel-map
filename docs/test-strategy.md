# test-strategy.md — 촘촘하고 다양하고 꼼꼼한 테스트 전략

본 문서는 `kor-travel-map` v2의 테스트 정책이다. 사용자 요청은
"테스트케이스는 최대한 촘촘하고 다양하고 꼼꼼하게". 이를 4단계 테스트 + 명시적
커버리지 목표 + EXPLAIN 검증 + property-based testing + fixture replay로
구현한다.

## 1. 4단계 테스트 구조 (구 ADR-014)

```
tests/
  unit/           — DB 없음. Fake repo (in-memory Protocol 구현).
                    pytest + pytest-asyncio + hypothesis.
                    실행 시간: < 5초/전체.
  integration/    — testcontainers PostGIS (postgis/postgis:16-3.5-alpine).
                    DDL fixture 세션 단위 적용. raw SQL + 인덱스 EXPLAIN 검증.
                    실행 시간: < 5분/전체.
  e2e/            — 디버그 API + integration DB.
                    httpx.AsyncClient로 FastAPI app 호출.
                    실행 시간: < 5분/전체.
  fixtures/       — replay fixture (provider API 호출 녹화/재생).
                    VCR.py + 직접 저장한 JSON.
                    실행 시간: < 2분/전체.
  fakes/          — Fake 구현체 (단위 테스트가 사용)
  factories/      — pydantic Factory Boy / hypothesis strategy
  conftest.py     — 공통 fixture
```

각 단계는 pytest marker로 분리:

```python
@pytest.mark.unit
async def test_make_feature_id_is_deterministic(): ...

@pytest.mark.integration
async def test_features_repo_upsert_then_get(pg_session): ...

@pytest.mark.e2e
async def test_debug_api_features_in_bounds(client): ...

@pytest.mark.fixture_replay
def test_visitkorea_festival_fixture_replay(fixture_path): ...
```

## 2. 커버리지 목표

| 계층 | 목표 | 강제 |
|------|------|------|
| `core/` | 90%+ branch coverage | CI 강제 |
| `infra/` | 80%+ statement coverage | CI 강제 |
| `providers/` | 70%+ statement (변환 함수당 ≥3 케이스) | CI 강제 |
| `client/` | 80%+ statement | CI 강제 |
| `api/` | 70%+ statement | CI 강제 |
| `dagster/` | 80%+ statement | CI 강제 |
| `dto/` | 100% (Pydantic validator branch) | CI 강제 |
| **전체** | **80%+ branch** | CI 강제 |

`pyproject.toml`의 `[tool.coverage.run]`에 source = `src/kortravelmap`, `branch =
true`. 단계적 상향 schedule은 아래 표 (구 ADR-032, T-014 코드 작성 단계 진입 시
전환):

CI의 메인 라이브러리 전체 coverage 판정은 Python 3.13 unit coverage 원시 데이터와 같은 commit의
PostGIS integration coverage를 합산한 뒤 한 번 수행한다. Python 3.11/3.12 unit job도
동일 테스트를 실행하되 버전별 부분 측정치만으로 `fail_under`를 판정하지 않는다. DB
transaction/repository 코드는 실제 PostgreSQL 경로를 검증하는 integration suite의 실행
증거가 전체 80% gate에 포함되어야 한다. 별도 배포 패키지인 API와 Dagster는 각 Python
matrix에서 coverage 파일을 분리해 각각 70%, 80%를 독립 강제한다.

| Sprint | 전체 (branch) | `core/` | `providers/` | `infra/client/api/` |
|--------|---------------|---------|--------------|---------------------|
| Sprint 1 (scaffolding) | 50% | 60% | 50% | 50% |
| Sprint 2 (core + 첫 provider 4건) | 65% | 75% | 55% | 60% |
| Sprint 3 (provider 절반 + infra) | 75% | 85% | 65% | 70% |
| Sprint 4 (integrity + edge cases) | **80%** | **90%** | **70%** | **80%** |
| Sprint 5 (operational entry) | 유지 + 회귀 방지 | 유지 | 유지 | 유지 |

`dto/`는 Sprint 2부터 항상 100% branch 강제 (Pydantic validator는 line 수
적고 critical).

## 3. 단위 테스트 (`tests/unit/`)

### 3.1 대상

- `core/` 전 함수
- `dto/` Pydantic 모델 (validator branch 전체)
- `providers/<name>` 순수 변환 함수 (정상/엣지/실패 ≥ 3개씩)

### 3.2 Fake repo 패턴

```python
# core/protocols.py
class FeatureRepo(Protocol):
    async def upsert_feature(self, feature: Feature) -> Feature: ...
    async def get_feature(self, feature_id: str) -> Feature | None: ...
    async def features_in_bounds(self, *, bbox: BBox, kinds: list[FeatureKind], limit: int = 1000) -> list[Feature]: ...
    # ... ~10 메서드
```

```python
# tests/fakes/in_memory_feature_repo.py (단위 테스트만 사용)
class InMemoryFeatureRepo:
    def __init__(self) -> None:
        self._store: dict[str, Feature] = {}

    async def upsert_feature(self, feature: Feature) -> Feature:
        self._store[feature.feature_id] = feature
        return feature

    async def get_feature(self, feature_id: str) -> Feature | None:
        return self._store.get(feature_id)
    # ...
```

```python
@pytest.mark.unit
async def test_load_pipeline_calls_repos_in_order():
    repo = InMemoryFeatureRepo()
    source = InMemorySourceRepo()
    link = InMemoryLinkRepo()
    file_store = InMemoryFileStore()
    pipeline = LoadPipeline(repo, source, link, file_store)
    bundle = FeatureBundleFactory.build()
    await pipeline.load(bundle)
    assert repo.get_feature(bundle.feature.feature_id) is not None
    assert source.exists(bundle.source_record.source_record_key)
    # ...
```

### 3.3 property-based (hypothesis)

```python
from hypothesis import given, strategies as st

@pytest.mark.unit
@given(
    bjd_code=st.from_regex(r"^\d{10}$", fullmatch=True),
    kind=st.sampled_from(list(FeatureKind)),
    category=st.text(min_size=1, max_size=20),
    source_type=st.text(min_size=1, max_size=30),
    source_natural_key=st.text(min_size=1, max_size=50),
)
def test_make_feature_id_is_deterministic(bjd_code, kind, category, source_type, source_natural_key):
    a = make_feature_id(bjd_code=bjd_code, kind=kind, category=category,
                        source_type=source_type, source_natural_key=source_natural_key)
    b = make_feature_id(bjd_code=bjd_code, kind=kind, category=category,
                        source_type=source_type, source_natural_key=source_natural_key)
    assert a == b
    assert a.startswith(f"f_{bjd_code}_{kind.value[0]}_")
    assert len(a.split("_")[-1]) == 16
```

```python
@given(coord=st.builds(
    Coordinate,
    lat=st.floats(min_value=33.0, max_value=39.5),
    lon=st.floats(min_value=124.0, max_value=132.0),
))
def test_korean_coord_validates_bounds(coord):
    assert Feature(feature_id="f_x", kind="place", name="x", category="x",
                   marker_icon="i", marker_color="P-01", coord=coord)
```

## 4. 통합 테스트 (`tests/integration/`)

### 4.0 정합성 케이스 매트릭스 (ADR-033)

`ops.feature_consistency_reports` F1~F8. Phase 1(F1~F3)은 통합
`tests/integration/test_consistency_reports.py` + 집계 단위
`tests/unit/test_infra_consistency.py`. Phase 2(F4~F8 + Dagster 게이트)는 Sprint 5.

| 케이스 | 정의 | severity | Phase |
|--------|------|----------|-------|
| F1 | orphan source_record (`source_links` 없음) | ERROR | 1 ✅ |
| F2 | detail-bearing kind인데 `detail` JSONB 비어있음 (ADR-018) | ERROR | 1 ✅ |
| F3 | `coord_5179` ≠ `ST_Transform(coord,5179)` (ADR-012) | ERROR | 1 ✅ |
| F4 | `dedup_review_queue` 미해소 초과 | WARN | 2 ✅ |
| F5 | provider `last_success` SLA 초과 | WARN | 2 ✅ |
| F6 | `opening_hours` 모순 (ADR-019) | ERROR | 2 ✅ |
| F7 | cross-provider dedup baseline score regression | WARN | 2 ✅ |
| F8 | `file_object` orphan (RustFS↔DB) | WARN | 2 ✅ |

집계(`build_report`): `severity_max` = 위반 케이스 최고 severity, 없으면 `OK`.
Phase 1은 **관측만**(Dagster swap 차단 없음).


### 4.1 testcontainers PostGIS

```python
# conftest.py
@pytest.fixture(scope="session")
async def pg_container():
    with PostgresContainer("postgis/postgis:16-3.5-alpine") as c:
        c.start()
        yield c

@pytest.fixture(scope="session")
async def pg_engine(pg_container):
    engine = create_async_engine(pg_container.get_connection_url().replace("psycopg2", "asyncpg"))
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS feature"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS provider_sync"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ops"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS x_extension"))
        await conn.execute(text("CREATE EXTENSION postgis WITH SCHEMA x_extension"))
        await conn.execute(text("CREATE EXTENSION pg_trgm WITH SCHEMA x_extension"))
        await conn.execute(text("CREATE EXTENSION pgcrypto WITH SCHEMA x_extension"))
        await conn.execute(text("SET search_path = public, x_extension"))
        # Alembic upgrade head
        ...
    yield engine
    await engine.dispose()

@pytest.fixture
async def pg_session(pg_engine):
    async with AsyncSession(pg_engine) as session:
        async with session.begin():     # 테스트 자동 rollback
            yield session
            await session.rollback()
```

### 4.2 EXPLAIN 검증 (필수)

모든 raw SQL `_SQL` 상수마다 EXPLAIN 검증 테스트 1개 이상.

```python
@pytest.mark.integration
async def test_features_nearby_sql_uses_coord_5179_gist(pg_session, seeded_features):
    result = await pg_session.execute(
        text("EXPLAIN (FORMAT JSON, ANALYZE) " + FEATURES_NEARBY_SQL),
        {"lon": 127.0, "lat": 37.5, "radius_m": 1000, "kinds": ["place"], "limit": 50},
    )
    plan = result.scalar_one()[0]["Plan"]
    nodes = _collect_all_nodes(plan)
    assert any("idx_features_coord_5179_gist" in n.get("Index Name", "") for n in nodes), \
        f"expected coord_5179 GIST scan, plan: {plan}"
    assert not any(n.get("Node Type") == "Seq Scan" and n.get("Relation Name") == "features" for n in nodes), \
        f"seq scan on features: {plan}"
```

### 4.3 인덱스 빠짐 회귀 차단

```python
@pytest.mark.integration
async def test_all_required_indexes_exist(pg_engine):
    required = {
        "idx_features_coord_gist", "idx_features_coord_5179_gist",
        "idx_features_kind_category", "idx_features_name_trgm",
        "idx_weather_feature_metric_time", "idx_price_values_observed_at_brin",
        # ... 전체 목록
    }
    async with pg_engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname IN ('feature', 'provider_sync', 'ops')
        """))
        existing = {row[0] for row in result}
    missing = required - existing
    assert not missing, f"missing indexes: {missing}"
```

### 4.4 ON CONFLICT 동작

```python
@pytest.mark.integration
async def test_upsert_feature_is_idempotent(pg_session, feature_factory):
    feature = feature_factory.build()
    await features_repo.upsert(pg_session, feature)
    await features_repo.upsert(pg_session, feature)
    rows = await pg_session.execute(
        text("SELECT count(*) FROM feature.features WHERE feature_id=:fid"),
        {"fid": feature.feature_id},
    )
    assert rows.scalar() == 1
```

### 4.5 transaction 격리

```python
@pytest.mark.integration
async def test_transaction_rolls_back_on_exception(pg_session):
    with pytest.raises(RuntimeError):
        async with pg_session.begin_nested():
            await features_repo.upsert(pg_session, feature_factory.build())
            raise RuntimeError("rollback")
    # SAVEPOINT가 롤백되어야 함
    count = await pg_session.scalar(text("SELECT count(*) FROM feature.features"))
    assert count == 0
```

### 4.6 동시성 (advisory lock)

```python
@pytest.mark.integration
async def test_import_job_advisory_lock_blocks_concurrent(pg_engine):
    async with pg_engine.connect() as conn1, pg_engine.connect() as conn2:
        got1 = await conn1.scalar(text("SELECT pg_try_advisory_lock(:slot)"), {"slot": 42})
        got2 = await conn2.scalar(text("SELECT pg_try_advisory_lock(:slot)"), {"slot": 42})
        assert got1 is True and got2 is False
        await conn1.execute(text("SELECT pg_advisory_unlock(:slot)"), {"slot": 42})
```

### 4.7 bulk COPY 경로

```python
@pytest.mark.integration
async def test_bulk_price_values_copy_handles_100k_rows(pg_engine, generate_price_rows):
    rows = list(generate_price_rows(100_000))  # 100k rows
    await bulk_copy_price_values(pg_engine, rows)
    count = await _scalar(pg_engine, "SELECT count(*) FROM feature.feature_price_values")
    assert count == 100_000
```

## 5. e2e 테스트 (`packages/kor-travel-map-api/tests/`)

e2e/라우터 테스트는 **별도 패키지** `kor-travel-map-api`의 FastAPI app을 띄워
검증한다 (ADR-020). 메인 패키지 `tests/` 트리에는 e2e 디렉토리가 없고, 디버그 UI
테스트는 `packages/kor-travel-map-api/tests/`에 둔다 (`test_routers.py` /
`test_features_router.py` / `test_etl_routers.py` 등 — `TestClient` 기반, 대부분
DB 없이 의존성 override). 실행 환경은 메인 + 디버그 UI 둘 다 설치된 venv
(`uv pip install -e . -e packages/kor-travel-map-admin`). 실 DB round-trip은 메인
패키지 `tests/integration/`(testcontainers PostGIS)이 담당한다.

### 5.1 디버그 FastAPI app 테스트

```python
@pytest.fixture
async def debug_client(pg_engine, file_store):
    # ↓ 메인 라이브러리 X, 별도 패키지 import
    from kortravelmap.api.app import build_app
    app = build_app(engine=pg_engine, file_store=file_store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        yield c

@pytest.mark.e2e
async def test_get_features_in_bounds(debug_client, seeded_features):
    r = await debug_client.get("/features/in-bounds",
                               params={"min_lon": 126.0, "min_lat": 37.0,
                                       "max_lon": 128.0, "max_lat": 38.0,
                                       "kinds": ["place"]})
    assert r.status_code == 200
    body = r.json()
    assert "features" in body
    assert len(body["features"]) > 0
```

### 5.2 인증 없음 동작 확인 (ADR-005)

```python
@pytest.mark.e2e
async def test_debug_api_requires_no_auth(debug_client):
    # 인증 헤더 없이도 200
    r = await debug_client.get("/features/in-bounds",
                               params={"min_lon": 126.0, "min_lat": 37.0,
                                       "max_lon": 128.0, "max_lat": 38.0})
    assert r.status_code == 200
    # Authorization 헤더가 있어도 동작은 동일
    r2 = await debug_client.get("/features/in-bounds",
                                params={...},
                                headers={"Authorization": "Bearer anything"})
    assert r2.json() == r.json()
```

### 5.3 0.0.0.0 바인드 경고 (ADR-005 후속)

```python
@pytest.mark.e2e
def test_warns_when_binding_to_all_interfaces(caplog):
    from kortravelmap.api.app import warn_if_external_bind
    with caplog.at_level("WARNING"):
        warn_if_external_bind("0.0.0.0")
    assert any("internal-only" in r.message.lower() for r in caplog.records)
```

### 5.4 Playwright UI e2e의 한계 — render-smoke 위주

admin frontend의 Playwright e2e suite는 n150 Linux 우선으로 실행하며, 현재 **render-smoke 위주**라
"33/33 passing" 같은 통과 수치가 곧 **UI-level 커버리지**를 뜻하지는 않는다.
curated-features, `features/new`, 그리고 3개 상세 페이지는 아직 시나리오로
커버되지 않는다 (상세는 `docs/reports/e2e-scenario-coverage-2026-06-16.md`).

### 5.5 C7 prod 파괴적 live E2E의 복구·인과성 gate

C7 prod runner는 실행자 입력만으로 prod를 주장하지 않는다. root-owned 고정 attestation 파일의
machine-id/hostname/origin hash와 실제 host·URL을 대조하고, 로그인 POST `200 + Set-Cookie` 및
UI container의 비어 있지 않은 admin password hash를 선행 조건으로 둔다. 값은 로그·attachment에
출력하지 않는다.

POI target mutation은 PUT 전에 자연키와 intended body를 원자 journal에 먼저 기록하고 응답 뒤
UUID·strong ETag·version을 보강한다. 모든 DELETE/cleanup은 직전 exact GET ETag를 `If-Match`로
사용하며 `412`는 concurrent update 증거로 실패 처리한다. create/update/delete 각각은 연결을
다시 열지 않은 같은 WebSocket에서 mutation 직전 frame cursor 이후의 `update` frame과
`live_revision >= dataset_projection_revision`을 확인한다. 최종 read-only 검증은 각 자연키의
exact RFC7807 `404 application/problem+json`과 owned external-system active list 0을 다시 확인한다.

KMA request 전에는 owned external-system의 active target 전체 key/UUID/ETag 집합을 journal과 exact
비교한다. 실행·event 다음 페이지는 request의 provider/dataset/sync_scope/cursor와 response item
tuple·`next_cursor`를 함께 검증한다. `route.fetch()`를 사용하는 interception은 handler in-flight
settlement가 끝나기 전 teardown하지 않는다.

같은 자연키를 삭제 후 재생성하는 시나리오는 새 UUID·ETag·version을 active 소유 객체로 교체하고
이전 UUID는 삭제된 history로 분리해 최종 두 identity를 모두 검증한다. PUT 응답 유실은 exact GET
재탐색, 서버 부재 시 동일 PUT 1회 재생, 다시 exact GET 순으로 처리한다. 어느 단계에서도 body·UUID·
strong ETag를 증명하지 못하면 target 삭제와 restored 성공을 금지한다.

preview 응답은 request의 provider-dataset scope, 빈 중복 filters, update policy, run mode, priority와
exact 일치해야 한다. terminal matched scope의 eligible/skipped/executed 집합은 KMA exact pair의
합집합이어야 하며 다른 provider/dataset을 허용하지 않는다. KMA metadata와 cursor의 fingerprint는
소문자 64자리 SHA-256, base datetime은 달력상 유효한 비어 있지 않은 `YYYYMMDDHHmm`만 허용한다.

KMA/sensor/schedule/runner journal은 임시 파일 fsync 뒤 rename하고 최종 파일과 부모 디렉터리도
fsync한다. runner state·lock·`BLOCKED.json`은 root-owned `0700` 고정 경로만 사용하며
`XDG_STATE_HOME` override를 fail-closed한다. 이 순서와 모든 route handler settlement→unroute 순서는
실제 source 구간을 읽는 정적 회귀 테스트로 고정한다.

누적 journal의 이전 payload는 현재 in-memory state를 합치기 전에 독립적으로 restored residue를
통과해야 한다. 합칠 때 현재 target/request/idempotency key나 더 전진한 status는 이전 snapshot으로
덮어쓰지 않는다. 서로 다른 scenario의 current pending 상태는 이전 restored 판정 입력에 포함하지
않는다. create와 실제 run-now/provider dispatch는 각각 직전 서버 active target 전체 집합 barrier를
독립적으로 통과해야 한다.

자연키 recreate는 삭제된 history UUID와 다른 새 UUID 및 version 1 strong ETag를 요구한다. 최종
runner는 non-empty history와 current/history UUID 상호 배타성을 교차 검증한다. lock 파일은
`O_NOFOLLOW|O_CREAT`로 열고 regular/root-owned/`0600`을 fstat한 같은 FD에 non-blocking flock을
보유하며 shell truncate redirection을 사용하지 않는다.

standalone POI journal도 temp fsync→rename→final fsync→parent fsync 순서를 따른다. PUT 응답 유실은
intended body exact GET 후 404일 때만 동일 PUT을 한 번 재생하고, 응답과 후속 GET의 body·UUID·strong
ETag·version을 다시 exact 비교한다. causal receipt가 유실됐거나 identity가 불확실하면 runner의
`BLOCKED.json`을 남기며 intended body 검증 없는 identity-only cleanup delete를 금지한다. KMA cursor
`base_datetime`은 달력상 유효한 비어 있지 않은 `YYYYMMDDHHmm` 필수값이다.

target 전체 집합 barrier는 `external_system`별 `page_size=500` cursor를 최대 두 페이지까지 완주해
501건을 검증한다. continuation page가 비거나 cursor가 반복되고, 상한 뒤에도 cursor가 남거나 다른
external-system item이 섞이면 불완전한 소유권 증거이므로 mutation을 금지한다. preview의
`matched_scope.provider_datasets`는 KMA provider/dataset/effective scope 한 쌍과 비음수 정수
`feature_count`를 반드시 포함해야 하며 빈 배열과 추가 pair는 실패다.

execution identity는 `(created_at, id, kind)`, event identity는 `(occurred_at, event_id)` total order를
사용한다. 각 API page는 중복 없는 엄격 내림차순, page 1과 page 2는 서로소이면서 경계 순서를
보존해야 한다. UI table은 각 행에 불투명 `data-row-identity`를 제공하고 현재 응답 tuple 배열과 DOM
전체 행 배열을 순서까지 exact 비교한다. 일부 행 존재나 단순 화면 text 변경은 cursor 증거가 아니다.

standalone POI 첫 create에는 실제 route가 `route.fetch()`로 upstream commit 응답·ETag·causal receipt를
먼저 보관한 뒤 client response만 abort하는 결정적 fault를 주입한다. exact GET으로 같은 intended
body/UUID/ETag/version을 재탐색하고 보관 receipt와 일치할 때만 성공하며, commit 증거가 없으면
BLOCKED한다. route handler가 모두 settlement된 뒤에만 interception을 제거한다.

## 6. fixture replay (`tests/fixtures/`)

### 6.1 구조

```
tests/fixtures/
  visitkorea/
    festival_full_scan_seoul_2026.json
    festival_full_scan_empty_response.json
    festival_full_scan_missing_image.json
  mois/
    license_promoted_restaurant.json
    license_excluded_billiards.json
    license_closed.json
  krheritage/
    heritage_place_natural_monument.json
    heritage_area_with_boundary.json
    heritage_event_monthly.json
  kma/
    short_forecast_typical.json
    short_forecast_sky_change.json
    ultra_short_nowcast.json
  ...
```

### 6.2 fixture 스키마

```json
{
  "name": "festival_full_scan_seoul_2026",
  "function": "visitkorea.festival_to_bundles",
  "description": "VisitKorea 축제 정상 케이스 — 2026년 5월 서울",
  "input": {
    "params": {"areaCode": "1", "eventStartDate": "20260501"}
  },
  "request": {
    "method": "GET",
    "url": "http://apis.data.go.kr/.../searchFestival",
    "headers": {"Accept": "application/json"}
  },
  "response": {
    "status": 200,
    "body": { ... raw provider response ... }
  },
  "parsed": { ... provider typed model dump ... },
  "processed": [ ... FeatureBundle list dump ... ],
  "assertion": {
    "type": "snapshot",
    "fields": ["feature_id", "kind", "name", "detail.event_kind", "raw_refs[0].provider"]
  },
  "meta": {
    "captured_at": "2026-05-21T10:00:00+09:00",
    "captured_by": "claude",
    "redactions": ["api_key", "Authorization"]
  }
}
```

### 6.3 replay 실행

```python
@pytest.mark.fixture_replay
@pytest.mark.parametrize("fixture_path", _discover_fixtures("visitkorea"))
def test_visitkorea_fixture_replay(fixture_path):
    fixture = load_fixture(fixture_path)
    runner = RUNNERS[fixture.function]
    actual = runner(fixture.input)
    assert_against_fixture(actual, fixture)
```

`RUNNERS`는 provider 변환 함수의 dispatch dict. `assert_against_fixture`는 fixture
`assertion.type`에 따라 snapshot/schema_only/required_fields/count 검증.

### 6.4 민감정보 자동 마스킹

fixture 저장 helper가 `api_key`, `Authorization`, `serviceKey`, `X-Naver-Client-*`,
`KakaoAK` 헤더 등을 자동으로 `<REDACTED>`로 치환한다.

```python
# tests/fixtures_helper.py
SENSITIVE_KEYS = {"api_key", "serviceKey", "service_key", "Authorization",
                  "X-Naver-Client-Id", "X-Naver-Client-Secret", "KakaoAK", "X-Goog-Api-Key"}

def mask_sensitive(obj):
    if isinstance(obj, dict):
        return {k: ("<REDACTED>" if k in SENSITIVE_KEYS else mask_sensitive(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_sensitive(v) for v in obj]
    return obj
```

## 7. 시나리오 매트릭스

각 provider 변환 함수는 최소 ≥3 케이스:

| 케이스 종류 | 예시 |
|------------|------|
| 정상 | 일반적인 provider 응답 |
| 엣지 — 빈 필드 | 좌표 없음, 주소 없음, 전화 없음 |
| 엣지 — 다중 | image 2개, sibling group 형성 |
| 엣지 — 경계값 | 좌표 한국 영역 밖, 날짜 미래/과거 극단 |
| 엣지 — UTF-8 | 특수문자, 한글-한자 혼합, 이모지 |
| 실패 — 잘못된 payload | 필수 필드 누락 → ValidationError |
| 실패 — schema drift | 새 필드 발견 → payload에 저장 후 raw_payload_hash 변경 |
| 폐업/취소 | MOIS: 영업중 X |
| 제외 업종 | MOIS: 미용실, PC방 등 |

### 7.1 검증 차원

| 차원 | 검증 |
|------|------|
| 결정성 | 같은 입력 → 같은 feature_id, 같은 hash |
| 멱등성 | 같은 입력 2회 적재 → 1개 row, updated_at만 갱신 |
| 정합성 | feature.coord ∈ 한국 영역, address 코드 매핑 일관 |
| schema | DTO ValidationError가 적절히 발생 |
| 인덱스 | 통합 테스트 EXPLAIN으로 |
| 성능 | 100k row 적재 시간, 반경 검색 응답시간 |

### 7.2 Canonical provider operation 회귀 (T-ADM-C3e)

| 경계 | 필수 회귀 |
|------|-----------|
| migration | 0050→0051 up/down, single head, exact-one request/event pair backfill, linked request 우선·multi/partial/blank/non-string identity NULL 보존, cancellation operation kind/run-termination iff backfill, run engine timestamp 컬럼/CHECK up/down, raw run status, root/child CHECK와 partial unique |
| 동시성 | 같은 run selection 동시 ensure가 root 1행+child N행, pair 누락 0; marker 선점은 ensure/provider I/O 0, ensure 선점은 child 전부 frozen scope, 반대 lock 순서 0 |
| cross-row | feature-kind constraint trigger의 parent kind/root-child trimmed run/create-time 일치, generic batch 다른 run 허용, root trigger/registry mismatch conflict, root/child identity update·root-first delete 거부, terminal/marked attach 거부 |
| retry | 첫 2회 exception 뒤 3회 성공은 root/child 각 1행 `done`; 최종 retry 실패는 각 1행 `failed`; attempt는 event로만 기록 |
| sensor/resource | event-backed QUEUED/STARTING/STARTED/CANCELING sensor와 NOT_STARTED/MANAGED periodic/guard ensure 분리, guard가 provider resource보다 선행, marker 선점 시 fetcher I/O 0, pre-resource failure/queued cancel, terminal duplicate delivery; 등록 job identity drift는 fail-closed/provider I/O·DB load 0, 비등록 arbitrary job만 panel-only |
| 공유 run | multi-asset와 MCST에서 pipeline root 1개, exact child N개, C3d frozen scope child 전부, Dagster terminate 1회 |
| partial success | MCST 전반 pair load/empty-skip 성공 뒤 후반 pair 최종 실패는 완료 child `done`, 나머지 `failed`; callback 없는 raw runner tracking 0 |
| terminal | SUCCESS exact child-set mismatch 또는 non-done child는 done 승격 없이 known active root/child를 `tracking_invariant` failed로 원자 종료하고 active 잔존 0, 전부 done일 때 root만 done; same-marker C3d도 같은 run 단위 frozen predicate와 원자 CAS, raw status 별도 보존 |
| stale recovery | 장시간 feature-load root/child는 generic recovery 제외; active/unavailable/not-found Dagster run을 heartbeat만으로 failed 처리 0 |
| queue ownership | feature-load queued root/child는 generic claim 제외; canonical API cancel은 run terminate/CANCELED 확인 1회, terminate 실패는 base queued+retryable/cancel_failed 뒤 같은 frozen member retry, QUEUED→STARTED race의 SUCCESS/FAILURE는 status/progress/stage/error/raw status/engine times까지 same-marker CAS로 reconcile, generic queued는 DB-only |
| writer ownership | reserved feature kind의 generic enqueue/start/finish/heartbeat/cancel/payload/requeue/attach는 fail-closed; append-only event와 same-marker C3d terminal writer만 허용 |
| event order | STARTED→늦은 QUEUED/STARTING, terminal→QUEUED/STARTED, duplicate delivery는 상태 역전 0과 명시 noop/blocked |
| engine 관측 | raw Dagster status는 terminal 뒤 불변이고 C3d marker 소유 terminal도 같은 CAS로 갱신; late reconcile은 authoritative create/start/finish 시각을 복구하고 완료 child finish는 보존하며 NULL start는 유일한 effective start로 보충; crash resume는 cancellation run에 저장한 동일 시각 재사용, drift/finish-before-start는 tracking conflict |
| watermark reconcile | QUEUED/STARTED/SUCCESS/CANCELED DB 실패와 run-status cursor 전진 뒤 missing root/terminal 복구, page commit 뒤 cursor 전진, crash page 멱등 재생; DB→Dagster end cursor는 다음 tick beginning으로 wrap해 장기 run의 후속 terminal과 late old-created root 회수 |
| sensor readiness | tracking sensor 전부 default RUNNING, cutover cursor 명시 초기화, 첫 tick commit/readback 전 launch ingress 0 |
| terminal CAS | sensor/retry가 `done`/`failed`/`cancelled` 또는 cancellation marker 행을 reopen/overwrite하지 않음 |
| update request | `FeatureUpdateAssetRunner` raw 호출은 standalone feature-load root 0개이고 기존 request root만 유지 |
| identity | schedule spec/asset registry의 모든 exact pair가 provider catalog에 존재하며 alias·placeholder·배열 cross-product 없음 |
| read model | twin/nested/duplicate-owner/standalone/cycle에서 overview/timeline/grid/detail의 `(kind,id)`, root/pair status 동일; direct scope는 linked typed member 1항목의 metadata만 보강; feature run projected job은 root 고정으로 pair UUID/order에 무관 |
| request identity | 0052 up/down, writer 선잠금·동시 writer 차단, jobless·terminal-source scope 불일치·reserved Dagster kind request별 canonical job 재연결, active/cancellation relink와 malformed scope/provider/dataset 필터·persisted dry-run 차단, `dry_run` 컬럼 제거·down 복원, filter JSONB→`TEXT[]`→JSONB type/default 전환, 모든 scope object/type 및 direct pair/sync shape, provider/dataset 배열 1차원·unique·32/64개·trim·길이 검증, `job_id NOT NULL/RESTRICT`, canonical job kind/scope pair 교차검증과 import kind/pair 불변 trigger, job index partial→unconditional→partial |
| overview | status/queued+running active/최근 24시간 failure는 canonical root 단위이며 timeline root count와 동일, multi-pair child N배 부풀림 0; 기존 import/update 분리 6필드 제거 |
| progress/stage | child done=100, root progress=`floor(100*done/total)`; partial failure/cancel은 완료 비율 보존, exact SUCCESS는 100, stage는 고정 lifecycle 어휘 |
| pagination | detail recent cursor가 pipeline total order와 같고 1,000 root 이상에서 page 누락·중복과 grid latest 누락 0 |
| filter/index | provider-only와 provider+dataset exact pair filter, event의 무필터/job/provider/pair/level/exact-scope별 전용 `EXPLAIN` index gate; provider 없는 dataset-only는 API/repository에서 422/`ValueError` |
| 계약 drift | base/cancellation/nullable `dagster_run_status`/freshness/trigger status와 engine 시각 분리, pipeline/datasets 양쪽 OpenAPI admin/user drift와 admin generated type drift; cancellation member operation kind/run-termination 및 cancellation run engine start/finish 포함 |
| writer | offline validate/load/reserve, MOIS 3종, exact update member는 실컬럼+event pair; multi-scope/batch aggregate NULL; event mismatch 거부 |
| 배포 | API/manual/backfill/schedule/sensor ingress 차단, active 0 drain, 두 번 backfill, Dagster 전 구성 재기동, 신 API/Dagster 정지 후 migration-image downgrade |

## 8. 테스트 데이터 정책

- **단위 테스트 fixture**: 소량 (≤ 50 row), ext4 `tests/unit/factories.py`.
- **통합 테스트 seed**: 중량 (수백~수천 row), ext4 `tests/integration/conftest.py`.
  generate by hand 또는 hypothesis seeded.
- **fixture replay**: provider 응답 1~10건씩, ext4 `tests/fixtures/<provider>/`.
  민감정보 마스킹 필수.
- **부하 테스트**: NTFS `data/loadtest/`, 100k+ row.

## 9. CI 워크플로

정본은 `.github/workflows/ci.yml`이다. PR에서는 다음 순서와 gate를 강제한다.

1. Python 3.11/3.12/3.13 matrix가 메인 unit/lint 테스트를 실행한다. 부분 측정치에는
   `fail_under=0`을 적용하고 Python 3.13 원시 coverage만 artifact로 보존한다.
2. 같은 matrix에서 API 70%, Dagster 80% coverage를 메인 파일과 분리해 독립 판정한다.
3. 세 matrix가 모두 성공한 뒤 PostGIS integration job이 Python 3.13 원시 데이터를
   내려받아 integration 측정을 append하고 메인 전체 `fail_under=80`을 판정한다.
4. fixture replay는 별도 job으로 실행한다. lint, OpenAPI drift, frontend build/type gate는
   각 전용 workflow가 모든 PR에서 실행한다.

실패한 integration도 생성된 combined `coverage.xml`을 분석 artifact로 보존하되, 파일이
생성되기 전 실패와 취소는 안전하게 건너뛴다. slow/live 외부 서비스 검증은 정규 PR gate와
분리한다.

## 10. 회귀 차단 룰 (PR block 사유)

- Coverage 목표 미달 (단계적 상향)
- EXPLAIN 통합 테스트가 `Seq Scan` 검출
- 새 raw SQL이 EXPLAIN 테스트 없이 추가
- 새 인덱스가 `test_all_required_indexes_exist`에 빠짐
- 새 provider 변환 함수가 fixture 3개 미만
- DTO field 추가/삭제가 validator branch 테스트 없음

## 11. 부하/카오스 테스트 (nightly)

- 100k feature seed → in-bounds 응답시간 < 200ms (p95)
- 10k weather values bulk COPY → 10초 이내
- 1k import_jobs 동시 큐잉 → advisory lock 동작 확인
- 동일 fixture를 10회 적재 → row count 변동 없음
- Postgres 재시작 → `import_jobs` 재시작 시 running→failed 자동 마크

## 12. 테스트 작성 우선순위 (Sprint 진입 시)

1. **dto/** Pydantic validator branch 100% (가장 빠른 회귀 차단)
2. **core/ids, core/scoring** 단위 + property-based
3. **infra/features_repo** 통합 + EXPLAIN 검증
4. **providers/<name>** fixture 3개씩
5. **client.py** 단위 (Fake repo)
6. **api/** e2e
7. **부하/카오스** nightly

## 13. 이관된 결정 (구 ADR)

provider/ETL·process·테스트 운영 결정이라 ADR에서 분리해 본 문서로 이관한다.
추적성만 남기고 본문 중복은 두지 않는다.

- **4단계 테스트 구조 + 계층별 coverage 목표** (구 ADR-014): `tests/`를
  unit(DB 없음, Fake repo, hypothesis) / integration(testcontainers PostGIS
  `postgis/postgis:16-3.5-alpine`, raw SQL EXPLAIN 인덱스 검증) /
  e2e(httpx.AsyncClient) / fixtures(provider 호출 녹화·재생) 4단계로 분리하고
  `core/ 90%·infra/ 80%·providers/ 70%·전체 80%`를 목표로 두며, 모든 provider
  변환 함수는 정상/엣지/실패 ≥3 fixture를 강제한다. kor-travel-geo 테스트 분리
  패턴 + "촘촘하고 다양하고 꼼꼼하게" 요청이 근거 (§1·§2에서 결정).

- **Coverage 단계적 상향 일정 (Sprint 1→5)** (구 ADR-032): 최종 coverage 목표를
  한 번에 강제하지 않고 Sprint별 `fail_under`를 점진 상향(전체 50→65→75→80%)해
  매 PR마다의 협상 비용을 0으로 만들고, 단계 상향 PR은 항상 gap 해소 PR과
  묶어 red main을 막는다. `dto/`만 line이 적고 validator branch가 곧
  비즈니스 룰이라 Sprint 2부터 100% branch를 항상 강제한다 (§2 Sprint별 표에서
  결정).
