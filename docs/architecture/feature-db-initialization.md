# feature-db-initialization.md — feature DB 부트스트랩

본 문서는 kor-travel-map 독립 프로그램(ADR-045)이 PostgreSQL + PostGIS 위의 feature
DB를 부트스트랩하고 내부 라이브러리 client를 초기화하는 절차다. PinVi 공유 DB를
사용하지 않는다.

## 1. 부트스트랩 순서

```
1. PostgreSQL 16 + PostGIS 3.5와 dedicated DB (`kor_travel_map`)를 준비한다.
2. ignored deployment env/vault에서 bootstrap, migrator, API runtime, Dagster runtime의
   서로 다른 credential을 주입한다.
3. virgin DB에만 `docker compose --profile fresh-init run --rm
   db-application-schema-fresh-300`을 명시 confirmation과 함께 한 번 실행한다. 이 one-shot은
   내부적으로 role/schema/extension bootstrap을 완료한 뒤 NOLOGIN `ktm_feature_schema_owner`와
   runtime group의 final ownership을 설정하고, 다음 restricted root migration까지 실행한다.
   기존 `0236` DB의 object/DB ownership transfer는 이 경로로 수행하지 않는다.
4. candidate image의 고정 `ktm-application-schema-fresh-300 migrate`만 LOGIN
   `ktm_feature_migrator` connection에서 `SET ROLE ktm_feature_schema_owner`로 실행한다. API
   daemon entrypoint나 generic `alembic upgrade head`가 blank production DB를 처리하지 않는다.
5. 같은 restricted migrator one-shot이 `python -m kortravelmap.infra.runtime_privileges`를 실행해
   closed table ACL inventory를 다시 부여한다. 이 late ACL transaction이 중단되어 raw `300`만
   남으면 final permit은 발급되지 않는다. Docker Manager가 candidate/reference/DB identity와
   pre/post receipt를 다시 확인한 뒤 fixed `fresh-300-finalize` one-shot으로만 completion을
   재시도할 수 있다. PostgreSQL default privilege는 사용하지 않는다.
6. API/Dagster는 각 LOGIN runtime DSN으로만 연결하고 실제 catalog preflight를 통과한다.
7. (선택) 객체 저장소 client + provider client를 주입하고 `AsyncKorTravelMapClient`를 만든다.
```

## 2. DB 생성

bootstrap owner password와 모든 DSN은 repository 또는 이 문서에 기록하지 않는다.
`docker/postgres-role-bootstrap.sh`가 dedicated DB superuser connection에만 연결하고
`KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE`의 exact-name 확인 뒤 역할을 provision한다.
외부/shared DB에는 이 script를 compose로 자동 실행하지 않는다.

운영 환경에서도 DB는 kor-travel-map이 소유한다. PinVi는 OpenAPI로만 접근하며
PostgreSQL에 직접 연결하지 않는다 (ADR-045).

## 3. Schema 부트스트랩

role·ownership·membership 정본은 `docker/postgres-role-bootstrap.sh`다. 핵심은
`ktm_feature_schema_owner`가 DB/application schema object를 소유하고,
`ktm_feature_migrator`만 해당 NOLOGIN group으로 `SET ROLE`할 수 있다는 점이다.
`ktm_feature_api_runtime`와 `ktm_feature_dagster_runtime`은 `ktm_feature_runtime`의
권한만 inherit하며 `SET ROLE`하지 못한다. 0095 이후 runtime이 `EXECUTE`할 수 있는
feature procedure는 `create_feature_with_initial_state`, `transition_feature_state`,
`materialize_user_feature_change_provenance`, `materialize_provider_feature_version`,
`author_lifecycle_override`, `revoke_lifecycle_override` 여섯 개뿐이고, base Feature
axis/audit direct DML은 허용하지 않는다. provider version `0`은 마지막으로 반영된
provider baseline만 가리킨다. user whole-row fence가 provider core/subtype 변경을 막은
refresh는 raw source observation만 최신화하고 user effective row를 provider snapshot으로
재기록하지 않는다. 이 임시 snapshot bridge는 T-VN-36 effective lineage가 대체한다.
bootstrap은 `REASSIGN OWNED`를 쓰지 않는다. 초기 dedicated superuser가 PostgreSQL
system object도 소유할 수 있으므로, map DB·`feature`/`provider_sync`/`ops`/`x_extension`
object만 명시적으로 transfer한다. 이어지는 ACL 재조정은 `feature.features`,
`feature.feature_state_transitions`, `feature.feature_versions`, `ops.feature_overrides`를
direct runtime mutation policy에서 제외하고, 새 feature relation은 명시 inventory 추가 전
deployment를 fail-closed 한다. lifecycle override author/revoke는 typed SECURITY DEFINER
procedure만 사용하며 runtime의 raw override `UPDATE`/`DELETE`는 허용하지 않는다.

## 4. Alembic 마이그레이션

```bash
# fresh DB: candidate image의 fixed one-shot만 migration과 ACL reconciliation을 함께 수행한다.
ktm-application-schema-fresh-300 migrate

# 현재 revision 확인
alembic current

# `300` 이후 downgrade/stamp-back/DB restore는 지원하지 않는다. 실패는 write fence 뒤
# 새 forward-fix candidate의 controlled handoff로만 처리한다.
```

`alembic/env.py`는 async DSN 정규화, migration connection 수명의
`SET ROLE ktm_feature_schema_owner`(flag가 true일 때), 그리고
`search_path = public, x_extension`를 강제한다. active `300` graph의 revision 정본은
**정확히 하나의 `public.alembic_version`** 이며, `ops.alembic_version` 같은 별도
version table은 생성하거나 수용하지 않는다. 이 physical contract는 baseline catalog
receipt와 `300_schema_baseline.py`가 함께 검증한다.

따라서 production에서는 일반 Alembic 명령을 운영 절차로 쓰지 않는다. virgin DB는
`ktm-application-schema-fresh-300 migrate`만, exact `0236` DB의 전환은 Docker Manager가
writer fence 아래 한 번만 실행하는 controlled handoff만 허용한다. 이 두 경우 외의
`alembic stamp`, generic `upgrade`, version-table 수동 생성·수정은 `300` boundary를
우회하므로 금지한다. fresh root의 ACL late failure 뒤에는 raw `300`·candidate·reference·DB
identity·receipt를 Manager가 다시 exact 확인한 경우에만
`ktm-application-schema-fresh-finalize finalize --writer-fence-receipt ...`가 허용된다.
이 completion은 migration/restore/stamp가 아니며 성공 뒤에도 Manager의 privileged postflight와
새 final permit 발급 전에는 runtime 기동 권한을 만들지 않는다.

## 5. KorTravelMapSettings 로드

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class KorTravelMapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KOR_TRAVEL_MAP_", env_file=".env")

    pg_dsn: SecretStr | None = None
    pg_dsn_sync: SecretStr | None = None
    pg_pool_size: int = 10
    pg_max_overflow: int = 10
    pg_pool_pre_ping: bool = True

    object_store_endpoint_url: str = "http://127.0.0.1:12101"
    object_store_bucket: str = "kor-travel-map"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: SecretStr | None = None
    object_store_secret_access_key: SecretStr | None = None
    object_store_public_base_url: str | None = "http://127.0.0.1:12101/kor-travel-map"

    kor_travel_geo_pg_dsn: SecretStr | None = None

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
```

환경변수 우선순위: 프로세스 환경 → `.env` 파일 → default다. `pg_dsn`에는 default가
없으며 deployment API/Dagster는 전용 runtime DSN을 반드시 주입한다. `.env`는 권한 600.

## 6. AsyncEngine 생성

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

def create_feature_engine(settings: KorTravelMapSettings) -> AsyncEngine:
    return create_async_engine(
        settings.pg_dsn.get_secret_value(),
        pool_size=settings.pg_pool_size,
        max_overflow=settings.pg_max_overflow,
        pool_pre_ping=settings.pg_pool_pre_ping,
        connect_args={
            "server_settings": {
                "search_path": "public,x_extension",
                "application_name": "kor-travel-map",
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

def create_file_store(settings: KorTravelMapSettings):
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

`kor-travel-geo`의 `AsyncAddressClient`를 본 라이브러리에 주입한다.

```python
from kraddr.geo import AsyncAddressClient

async def create_kor_travel_geo_client(settings: KorTravelMapSettings):
    if not settings.kor_travel_geo_pg_dsn:
        return None  # geocoding 미사용 — Address.legal_dong_code는 null로
    return AsyncAddressClient(pg_dsn=settings.kor_travel_geo_pg_dsn.get_secret_value())
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

## 10. AsyncKorTravelMapClient 생성

```python
from kortravelmap import AsyncKorTravelMapClient

settings = KorTravelMapSettings()
engine = create_feature_engine(settings)
file_store = create_file_store(settings)
kor_travel_geo_client = await create_kor_travel_geo_client(settings)

async with AsyncKorTravelMapClient(
    engine=engine,
    file_store=file_store,
    kor_travel_geo_client=kor_travel_geo_client,
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
async def bootstrap_from_env() -> AsyncKorTravelMapClient:
    """환경변수만으로 client 부트스트랩.
    
    디버그 / CLI / 단순 스크립트 용. 운영 API/Dagster는 명시적 의존성 주입.
    """
    settings = KorTravelMapSettings()
    engine = create_feature_engine(settings)
    file_store = create_file_store(settings)
    kor_travel_geo_client = await create_kor_travel_geo_client(settings)
    return AsyncKorTravelMapClient(
        engine=engine,
        file_store=file_store,
        kor_travel_geo_client=kor_travel_geo_client,
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
- Alembic receipt: **정확히 하나의** `public.alembic_version` row가 `300`이고, API
  production entrypoint가 Docker Manager의 root-owned final permit을 검증

디버그 API `/health`가 이를 노출 (별도 패키지, ADR-020).

## 13. 통합 테스트 부트스트랩

통합 테스트도 운영 계약과 같은 fresh-300 helper를 사용한다. testcontainers의 disposable
DB에서 `tests/integration/_application_300_bootstrap.py`가 final role/extension inventory를
준비하고 restricted migrator로 root `300`을 적용한다. 테스트 helper는 production operator
interface가 아니며, 직접 schema 생성, 수동 version table, generic Alembic command를 새
fixture 예제로 추가하지 않는다.

## 14. 멀티-DB / 멀티-환경

- **dev**: `kor_travel_map` (로컬 PostgreSQL)
- **integration test**: testcontainers (자동)
- **운영**: kor-travel-map 독립 DB (`kor_travel_map`) + Dagster metadata DB
  (`kor_travel_map_dagster`)

같은 라이브러리가 세 환경 모두 지원한다. 배포 service는 API/Dagster runtime DSN을
각각 `KOR_TRAVEL_MAP_PG_DSN`으로 주입하지만, source env가 bootstrap owner로 이를 합성하지는 않는다.
Alembic과 그 직후 ACL 재조정은 `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN`만 사용한다.

## 15. 초기화 실패 케이스

| 케이스 | 검출 위치 | 조치 |
|--------|----------|------|
| runtime DSN 미설정 | Compose/API/Dagster startup | required interpolation 또는 privilege preflight가 기동 차단 |
| DB 접근 거부 | `engine.connect()` | `OperationalError` → caller 처리 |
| schema 부재 | `client.healthz()` | warning + 사용자에게 부트스트랩 안내 |
| `300` receipt/final permit 불일치 | API production entrypoint | Map runtime을 기동하지 않고 writer fence 유지; Manager의 controlled fresh/handoff 또는 새 forward-fix candidate만 허용 |
| 확장 미설치 | 첫 SQL 실행 시 (`function st_makepoint does not exist`) | error |
| object store 접근 실패 | `client.upload_feature_files()` | `FileStoreError` |

graceful degradation:
- file_store=None: 이미지 업로드 비활성 (`NotImplementedError`)
- kor_travel_geo_client=None: 주소 보강 비활성 (legal_dong_code null 허용)
- providers={}: collect만 외부 호출 안 됨 (변환은 호출자가 직접)

## 16. 운영 체크리스트

- [ ] PostgreSQL 16 + PostGIS 3.5 컨테이너 healthy
- [ ] schema 4종 존재
- [ ] 확장 4종 존재
- [ ] `search_path` 올바름 (`SHOW search_path` → `public, x_extension`)
- [ ] `public.alembic_version`이 raw `300` 하나이고 final permit의 DB/candidate/receipt와 일치
- [ ] 객체 저장소 bucket healthy (RustFS healthcheck)
- [ ] `KOR_TRAVEL_MAP_*` 환경변수 모두 설정
- [ ] provider API 키 (kor-travel-map API/Dagster 환경)
- [ ] `client.healthz()` 모든 항목 true
