"""alias-map canonical 순서의 collation 회귀 방어 — glibc 전용 (T-VN-32C 리뷰 H2).

기본 conftest PostGIS는 alpine(musl)이라 DB default collation이 byte order와
사실상 같아, ``COLLATE "C"``를 제거하는 변이가 테스트를 전부 통과한 채
생존한다(적대 리뷰 실측). 본 모듈은 **glibc 이미지**(``postgis/postgis:16-3.5``,
default collation ``en_US.utf8``)를 별도로 띄워:

① keyset 페이지 순서 == checksum canonical 정렬 == UTF-8 byte 순서를 단언하고
   (COLLATE 제거 변이는 glibc에서 en_US 순서로 갈라져 여기서 죽는다),
② ``ORDER BY alias``(default)와 ``ORDER BY alias COLLATE "C"``가 실제로
   **다름**을 단언한다(collation 감지 가드 — 같으면 이 환경은 판별력이 없다는
   뜻이므로 사유를 명시하고 skip한다. musl/C-default 환경 포함).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.core.feature_alias_map import (
    FeatureAliasMapRowV1,
    feature_alias_map_merkle_root,
)
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_alias_map_repo import (
    compute_feature_alias_map_checksum,
    fetch_feature_alias_map_page,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_GLIBC_POSTGIS_IMAGE: Final = "postgis/postgis:16-3.5"

# 리뷰 보고의 판별 세트 수준 — ASCII 대/소문자·기호·비-ASCII가 byte 순서와
# en_US 순서에서 서로 다르게 갈라진다. 전부 NFC(비-ASCII는 escape로 고정).
_SEED_IDS: Final[tuple[str, ...]] = (
    "B-Upper-probe",
    "Zeta-probe",
    "apple-probe",
    "f_1100000000_p_glibc0001",
    "f_global_e_glibc0002",
    "feature:legacy-colon-probe",
    "~tilde-probe",
    "é-cafe-probe",
    "가나다-probe",
)


def _alembic_config(dsn: str) -> Config:
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


@pytest.fixture(scope="module")
def glibc_pg_container() -> Any:
    """glibc PostGIS 컨테이너 — conftest alpine 컨테이너와 별개."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")
    try:
        container = PostgresContainer(_GLIBC_POSTGIS_IMAGE)
    except Exception as exc:  # pragma: no cover — Docker 없음
        pytest.skip(f"PostgresContainer init failed (Docker?): {exc}")
    with container:
        yield container


@pytest.fixture(scope="module")
async def glibc_engine(glibc_pg_container: Any) -> AsyncIterator[AsyncEngine]:
    admin_dsn = normalize_async_dsn(glibc_pg_container.get_connection_url())
    database = f"alias_collation_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    await admin_engine.dispose()

    # 0095부터 fresh DB는 배포와 같은 principal graph를 먼저 갖춰야 upgrade가 선다:
    # 0095는 restricted migrator가 state/audit routine owner membership을 **스스로**
    # 부여하지 않는지 검사하고, 없으면 42501로 죽는다. conftest의 공용 컨테이너는
    # 그 준비를 이미 하지만, 이 모듈은 collation 판별을 위해 glibc 컨테이너에 자기
    # DB를 따로 만들기 때문에 그 경로 밖이었다. 여기서만 다른 방식으로 올리면
    # 검증 대상 스키마가 배포와 갈리므로 공유 helper를 그대로 쓴다 —
    # bootstrap → migrator 자격 upgrade(ADR-090)까지 배포와 동일 경로다.
    # collation 검증 축(alias 정렬)은 이 변경과 무관하며 그대로다.
    from tests.integration._tvn34_migration_bootstrap import (
        alembic_schema_owner_role,
        bootstrapped_migrator_dsn,
    )

    migrator_dsn = await bootstrapped_migrator_dsn(dsn)
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, _alembic_config(migrator_dsn), "head")

    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            for feature_id in _SEED_IDS:
                await connection.execute(
                    text(
                        "INSERT INTO feature.features (feature_id, kind, name, category) "
                        "VALUES (:fid, 'place', :name, '01070100')"
                    ),
                    {"fid": feature_id, "name": f"glibc-{feature_id[:16]}"},
                )
        yield engine
    finally:
        await engine.dispose()


async def _skip_unless_collation_discriminates(engine: AsyncEngine) -> None:
    """default collation 순서가 byte 순서와 같으면 판별력이 없다 — 명시 skip.

    적대 리뷰 H2의 가드: alpine/musl(또는 C-default) 환경에서는 ``COLLATE "C"``
    제거 변이가 이 모듈로도 잡히지 않으므로, 그 사실을 조용히 green으로
    가리는 대신 skip 사유로 드러낸다.
    """
    async with engine.connect() as connection:
        default_order = list(
            (
                await connection.execute(
                    text("SELECT alias FROM feature.feature_aliases ORDER BY alias")
                )
            ).scalars()
        )
        c_order = list(
            (
                await connection.execute(
                    text(
                        "SELECT alias FROM feature.feature_aliases "
                        'ORDER BY alias COLLATE "C"'
                    )
                )
            ).scalars()
        )
    if default_order == c_order:
        pytest.skip(
            "DB default collation 순서가 byte 순서와 동일 — glibc 판별 환경이 "
            "아니므로(COLLATE 제거 변이를 잡을 수 없음) skip. "
            f"이미지가 {_GLIBC_POSTGIS_IMAGE}(glibc)인지 확인하라."
        )
    assert c_order == sorted(_SEED_IDS, key=lambda alias: alias.encode("utf-8"))


async def test_default_and_c_collation_orders_actually_differ(
    glibc_engine: AsyncEngine,
) -> None:
    """② collation 감지 가드 — glibc에서 두 순서는 반드시 갈라져야 한다."""
    await _skip_unless_collation_discriminates(glibc_engine)


async def test_keyset_pages_and_checksum_follow_byte_order_on_glibc(
    glibc_engine: AsyncEngine,
) -> None:
    """① keyset 페이지 순서 == checksum canonical 정렬 == byte 순서."""
    await _skip_unless_collation_discriminates(glibc_engine)
    expected_order = sorted(_SEED_IDS, key=lambda alias: alias.encode("utf-8"))

    collected: list[str] = []
    after: str | None = None
    async with glibc_engine.connect() as connection:
        while True:
            page = await fetch_feature_alias_map_page(
                connection,  # type: ignore[arg-type]
                after_alias=after,
                limit=3,
            )
            collected.extend(row.alias for row in page.rows)
            if not page.has_more:
                break
            after = page.rows[-1].alias
        checksum = await compute_feature_alias_map_checksum(connection)  # type: ignore[arg-type]

    assert collected == expected_order
    # 0083 이후 저장 uuid는 비파생 v7이라 파생 재계산으로 기대값을 만들 수 없다 —
    # 정본(features) 저장값을 읽어 재계산한다(collation 검증 축은 무변경).
    async with glibc_engine.connect() as connection:
        stored = (
            await connection.execute(
                text(
                    "SELECT a.alias AS alias, a.alias_kind AS alias_kind, "
                    "       CAST(f.feature_uuid AS text) AS feature_uuid "
                    "FROM feature.feature_aliases AS a "
                    "JOIN feature.features AS f ON f.feature_id = a.feature_id"
                )
            )
        ).mappings().all()
    expected_rows = [
        FeatureAliasMapRowV1(
            alias=record["alias"],
            feature_uuid=record["feature_uuid"],
            alias_kind=record["alias_kind"],
        )
        for record in stored
    ]
    assert {row.alias for row in expected_rows} == set(_SEED_IDS)
    assert checksum.alias_count == len(_SEED_IDS)
    assert checksum.merkle_root == feature_alias_map_merkle_root(expected_rows)