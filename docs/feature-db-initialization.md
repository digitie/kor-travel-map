# feature-db-initialization.md — feature DB 부트스트랩

본 문서는 krtour-map 독립 프로그램(ADR-045)이 PostgreSQL + PostGIS 위의 feature
DB를 부트스트랩하고 내부 라이브러리 client를 초기화하는 절차다. TripMate 공유 DB를
사용하지 않는다.

## 1. 부트스트랩 순서

```
1. PostgreSQL 16 + PostGIS 3.5 컨테이너 기동
2. DB 생성 (`krtour_map`)
3. schema 생성 (feature, provider_sync, ops, x_extension)
4. 확장 설치 (postgis, postgis_topology, pg_trgm, pgcrypto) — x_extension에
5. search_path 설정 (public, x_extension)
6. Alembic upgrade head
7. KrtourMapSettings 로드 + create_async_engine
8. (선택) 객체 저장소 client + provider client 주입
9. AsyncKrtourMapClient 생성
```

## 2. DB 생성

```bash
# 컨테이너 기동
docker run -d --name krtour-postgis \
  -p 5432:5432 \
  -e POSTGRES_USER=krtour_map \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=krtour_map \
  -v krtour-pgdata:/var/lib/postgresql/data \
  postgis/postgis:16-3.5-alpine
```

DSN: `postgresql+asyncpg://krtour_map:changeme@localhost:5432/krtour_map`.

운영 환경에서도 DB는 krtour-map이 소유한다. TripMate는 OpenAPI로만 접근하며
PostgreSQL에 직접 연결하지 않는다 (ADR-045).

## 3. Schema 부트스트랩

```sql
-- 부트스트랩용 superuser/owner 세션에서 한 번만
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS provider_sync;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS x_extension;

CREATE EXTENSION IF NOT EXISTS postgis           SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS postgis_topology  SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm           SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pgcrypto          SCHEMA x_extension;

-- DB 단위 영구 설정
ALTER DATABASE krtour_map SET search_path = public, x_extension;

-- 라이브러리 user 권한
GRANT USAGE  ON SCHEMA feature, provider_sync, ops, x_extension TO krtour_map;
GRANT CREATE ON SCHEMA feature, provider_sync, ops TO krtour_map;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA x_extension TO krtour_map;
ALTER DEFAULT PRIVILEGES IN SCHEMA feature, provider_sync, ops
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO krtour_map;
```

## 4. Alembic 마이그레이션

```bash
# 마이그레이션 적용
alembic upgrade head

# 현재 revision 확인
alembic current

# 롤백
alembic downgrade -1
```

`alembic/env.py`는 다음을 강제한다:

```python
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

from krtour.map.infra.models import metadata as target_metadata

async def run_async():
    connectable = create_async_engine(DATABASE_URL)
    async with connectable.connect() as conn:
        await conn.execute(text("SET search_path = public, x_extension"))
        await conn.run_sync(_do_run, target_metadata)

def _do_run(connection, target_metadata):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,  # 다중 schema 지원
        version_table_schema="ops",
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()

asyncio.run(run_async())
```

`version_table_schema="ops"`로 Alembic revision 테이블도 ops에 격리.

## 5. KrtourMapSettings 로드

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class KrtourMapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRTOUR_MAP_", env_file=".env")

    pg_dsn: SecretStr
    pg_dsn_sync: SecretStr | None = None
    pg_pool_size: int = 10
    pg_max_overflow: int = 10
    pg_pool_pre_ping: bool = True

    object_store_endpoint_url: str = "http://127.0.0.1:12101"
    object_store_bucket: str = "krtour-map"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: SecretStr | None = None
    object_store_secret_access_key: SecretStr | None = None
    object_store_public_base_url: str | None = "http://127.0.0.1:12101/krtour-map"

    kraddr_geo_pg_dsn: SecretStr | None = None

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
```

환경변수 우선순위: 프로세스 환경 → `.env` 파일 → default. `.env`는 권한 600.

## 6. AsyncEngine 생성

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

def create_feature_engine(settings: KrtourMapSettings) -> AsyncEngine:
    return create_async_engine(
        settings.pg_dsn.get_secret_value(),
        pool_size=settings.pg_pool_size,
        max_overflow=settings.pg_max_overflow,
        pool_pre_ping=settings.pg_pool_pre_ping,
        connect_args={
            "server_settings": {
                "search_path": "public,x_extension",
                "application_name": "krtour-map",
            }
        },
    )
```

`search_path`는 DB 레벨 `ALTER DATABASE`로 박혀 있지만 connection 레벨에서도
강제 (서로 다른 운영 환경 호환).

## 7. 객체 저장소 (S3 호환) client

```python
import boto3
from botocore.config import Config as BotoConfig

def create_file_store(settings: KrtourMapSettings):
    if not settings.object_store_access_key_id:
        return None  # 옵션 — 이미지/문서 사용 안 하면 None 가능
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint_url,
        aws_access_key_id=settings.object_store_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.object_store_secret_access_key.get_secret_value(),
        region_name=settings.object_store_region,
        config=BotoConfig(signature_version="s3v4"),
    )
    return RustfsFileStore(s3, bucket=settings.object_store_bucket,
                           public_base_url=settings.object_store_public_base_url)
```

RustFS / MinIO / Ceph / AWS S3 / Cloudflare R2 모두 동일 API (ADR-015).

## 8. Geocoder 주입

`python-kraddr-geo`의 `AsyncAddressClient`를 본 라이브러리에 주입한다.

```python
from kraddr.geo import AsyncAddressClient

async def create_kraddr_geo_client(settings: KrtourMapSettings):
    if not settings.kraddr_geo_pg_dsn:
        return None  # geocoding 미사용 — Address.legal_dong_code는 null로
    return AsyncAddressClient(pg_dsn=settings.kraddr_geo_pg_dsn.get_secret_value())
```

geocoder 없이도 라이브러리는 동작한다. 주소 보강만 안 됨.

## 9. Provider client 주입 (선택)

provider 라이브러리는 호출 시점에 주입하거나 client 생성 시 dict로:

```python
from python_visitkorea_api import AsyncVisitKoreaClient
from python_kma_api import AsyncKmaClient

providers = {
    "visitkorea": AsyncVisitKoreaClient(service_key=...),
    "kma": AsyncKmaClient(api_key=...),
    # 필요한 것만
}
```

provider 라이브러리는 자기 환경변수(`KMA_API_KEY` 등)를 직접 읽는다 (본 라이브러리
설정 영역 X).

## 10. AsyncKrtourMapClient 생성

```python
from krtour.map import AsyncKrtourMapClient

settings = KrtourMapSettings()
engine = create_feature_engine(settings)
file_store = create_file_store(settings)
kraddr_geo_client = await create_kraddr_geo_client(settings)

async with AsyncKrtourMapClient(
    engine=engine,
    file_store=file_store,
    kraddr_geo_client=kraddr_geo_client,
    providers=providers,
    settings=settings,
) as client:
    # 조회 / 적재 / 운영
    feature = await client.get_feature("f_1111010100_p_abc123")
```

`async with`가 끝나면 client는 자동 cleanup (engine은 호출자가 별도 dispose).

## 11. 통합 부트스트랩 함수 (선택)

라이브러리는 부트스트랩 편의 함수를 제공할 수 있다 (확정 결정 보류):

```python
async def bootstrap_from_env() -> AsyncKrtourMapClient:
    """환경변수만으로 client 부트스트랩.
    
    디버그 / CLI / 단순 스크립트 용. 운영 API/Dagster는 명시적 의존성 주입.
    """
    settings = KrtourMapSettings()
    engine = create_feature_engine(settings)
    file_store = create_file_store(settings)
    kraddr_geo_client = await create_kraddr_geo_client(settings)
    return AsyncKrtourMapClient(
        engine=engine,
        file_store=file_store,
        kraddr_geo_client=kraddr_geo_client,
        providers={},  # provider는 호출 시점에 주입
        settings=settings,
    )
```

## 12. 헬스체크

`client.healthz()`는 다음을 ping:

```python
async def healthz(self) -> HealthCheck:
    return HealthCheck(
        engine_ok=await self._ping_engine(),
        object_store_ok=await self._ping_object_store() if self._file_store else None,
        schemas_present=await self._check_schemas(),
        alembic_head=await self._check_alembic_at_head(),
    )
```

- engine ping: `SELECT 1`
- object store ping: bucket HEAD
- schema 존재: `pg_namespace` 조회
- alembic head: `ops.alembic_version`이 현재 코드의 head revision과 일치

디버그 API `/health`가 이를 노출 (별도 패키지, ADR-020).

## 13. 통합 테스트 부트스트랩

```python
# tests/integration/conftest.py
@pytest.fixture(scope="session")
async def pg_container():
    with PostgresContainer("postgis/postgis:16-3.5-alpine") as c:
        c.start()
        yield c

@pytest.fixture(scope="session")
async def pg_engine(pg_container):
    dsn = pg_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(dsn)
    async with engine.begin() as conn:
        # schema + extensions
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS feature"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS provider_sync"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ops"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS x_extension"))
        for ext in ("postgis", "pg_trgm", "pgcrypto"):
            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext} SCHEMA x_extension"))
        # search_path
        await conn.execute(text("SET search_path = public, x_extension"))
        # Alembic upgrade head (코드 작성 단계에서 alembic_upgrade helper 추가)
        await alembic_upgrade(conn, "head")
    yield engine
    await engine.dispose()
```

## 14. 멀티-DB / 멀티-환경

- **dev**: `krtour_map` (로컬 PostgreSQL)
- **integration test**: testcontainers (자동)
- **운영**: krtour-map 독립 DB (`krtour_map`) + Dagster metadata DB
  (`krtour_map_dagster`)

같은 라이브러리가 세 환경 모두 지원. 차이는 settings (`KRTOUR_MAP_PG_DSN`)만.

## 15. 초기화 실패 케이스

| 케이스 | 검출 위치 | 조치 |
|--------|----------|------|
| `KRTOUR_MAP_PG_DSN` 미설정 | `KrtourMapSettings()` 생성 시 | Settings ValidationError |
| DB 접근 거부 | `engine.connect()` | `OperationalError` → caller 처리 |
| schema 부재 | `client.healthz()` | warning + 사용자에게 부트스트랩 안내 |
| Alembic 미적용 | `client.healthz()` | warning + `alembic upgrade head` 안내 |
| 확장 미설치 | 첫 SQL 실행 시 (`function st_makepoint does not exist`) | error |
| object store 접근 실패 | `client.upload_feature_files()` | `FileStoreError` |

graceful degradation:
- file_store=None: 이미지 업로드 비활성 (`NotImplementedError`)
- kraddr_geo_client=None: 주소 보강 비활성 (legal_dong_code null 허용)
- providers={}: collect만 외부 호출 안 됨 (변환은 호출자가 직접)

## 16. 운영 체크리스트

- [ ] PostgreSQL 16 + PostGIS 3.5 컨테이너 healthy
- [ ] schema 4종 존재
- [ ] 확장 4종 존재
- [ ] `search_path` 올바름 (`SHOW search_path` → `public, x_extension`)
- [ ] Alembic at head
- [ ] 객체 저장소 bucket healthy (RustFS healthcheck)
- [ ] `KRTOUR_MAP_*` 환경변수 모두 설정
- [ ] provider API 키 (krtour-map API/Dagster 환경)
- [ ] `client.healthz()` 모든 항목 true
