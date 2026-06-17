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
| `dto/` | 100% (Pydantic validator branch) | CI 강제 |
| **전체** | **80%+ branch** | CI 강제 |

`pyproject.toml`의 `[tool.coverage.run]`에 source = `src/kortravelmap`, `branch =
true`. 단계적 상향 schedule은 아래 표 (구 ADR-032, T-014 코드 작성 단계 진입 시
전환):

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
    count = await _scalar(pg_engine, "SELECT count(*) FROM feature.price_values")
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

admin frontend의 Windows Playwright e2e suite는 현재 **render-smoke 위주**라
"33/33 passing" 같은 통과 수치가 곧 **UI-level 커버리지**를 뜻하지는 않는다.
curated-features, `features/new`, 그리고 3개 상세 페이지는 아직 시나리오로
커버되지 않는다 (상세는 `docs/reports/e2e-scenario-coverage-2026-06-16.md`).

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

## 8. 테스트 데이터 정책

- **단위 테스트 fixture**: 소량 (≤ 50 row), ext4 `tests/unit/factories.py`.
- **통합 테스트 seed**: 중량 (수백~수천 row), ext4 `tests/integration/conftest.py`.
  generate by hand 또는 hypothesis seeded.
- **fixture replay**: provider 응답 1~10건씩, ext4 `tests/fixtures/<provider>/`.
  민감정보 마스킹 필수.
- **부하 테스트**: NTFS `data/loadtest/`, 100k+ row.

## 9. CI 워크플로

```
.github/workflows/test.yml
  jobs:
    unit:
      runs-on: ubuntu-latest
      steps:
        - pip install -e ".[dev]"
        - pytest tests/unit -q --cov=src/kortravelmap --cov-fail-under=80
        - ruff check .
        - mypy src/kortravelmap
        - lint-imports
    integration:
      runs-on: ubuntu-latest
      services:
        # testcontainers는 Docker-in-Docker 또는 docker socket mount 필요
      steps:
        - pip install -e ".[dev,api,geo,providers]"
        - pytest tests/integration -q --cov=src/kortravelmap --cov-append --cov-fail-under=80
    fixture_replay:
      runs-on: ubuntu-latest
      steps:
        - pip install -e ".[dev]"
        - pytest tests/fixtures -q
    slow:
      if: github.event_name == 'schedule'
      runs-on: ubuntu-latest
      steps:
        - pytest -m slow -q
```

PR에서는 unit + integration + fixture_replay만 강제. slow는 nightly.

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
