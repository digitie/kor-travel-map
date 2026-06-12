"""``test_cli_import_mois`` — ``ktmctl import mois`` round-trip (Sprint 4a).

NDJSON snapshot 파일 → CLI ``import`` 명령(자체 engine, ``--dsn`` 주입) →
``run_mois_license_bulk_job`` → 실 PostGIS 적재를 검증한다. CLI는 commit하므로
(``migrated_session`` rollback 격리와 달리) teardown에서 관련 테이블을 TRUNCATE한다.

검증: ① PROMOTED·영업중 record만 적재(EXCLUDED skip) + exit 0 ② import advisory
lock을 다른 세션이 쥐고 있으면 skip(exit 3) + 미적재.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.cli import import_lock_key
from kortravelmap.cli.main import build_parser
from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.models import FeatureRow
from kortravelmap.providers.mois import DATASET_KEY_BULK, PROVIDER_NAME

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, provider_sync.provider_sync_state, "
    "ops.import_jobs RESTART IDENTITY CASCADE"
)

# 영업중 PROMOTED 2건 + EXCLUDED 1건(적재 안 됨).
_NDJSON = (
    '{"service_slug":"general_restaurants","mng_no":"cli-1",'
    '"place_name":"민어집","lon":126.97,"lat":37.56,"is_open":true,'
    '"status_code":"01","legal_dong_code":"1111010100","license_date":"2020-05-01"}\n'
    '{"service_slug":"bakeries","mng_no":"cli-2","place_name":"빵집",'
    '"is_open":true,"legal_dong_code":"1111010100"}\n'
    '{"service_slug":"billiard_halls","mng_no":"cli-skip","is_open":true}\n'
)


@pytest.fixture
async def container_dsn(
    pg_container: object, migrated_engine: AsyncEngine
) -> AsyncIterator[str]:
    """테스트 컨테이너 async DSN + teardown TRUNCATE.

    ``migrated_engine``을 의존해 테이블(alembic head)을 보장하고, CLI가 만드는
    독립 engine이 붙을 DSN을 돌려준다. CLI는 commit하므로 teardown에서 정리한다.
    """
    from kortravelmap.infra.db import normalize_async_dsn

    dsn = normalize_async_dsn(pg_container.get_connection_url())  # type: ignore[attr-defined]
    yield dsn
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(text(_TRUNCATE_SQL))


async def _feature_count(engine: AsyncEngine) -> int:
    async with AsyncSession(engine) as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(FeatureRow))
            ).scalar_one()
        )


def _import_args(dsn: str, path: Path) -> object:
    return build_parser().parse_args(
        ["--dsn", dsn, "import", "mois", str(path)]
    )


async def test_cli_import_mois_loads_promoted(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    path = tmp_path / "snap.ndjson"
    path.write_text(_NDJSON, encoding="utf-8")

    args = _import_args(container_dsn, path)
    rc = await args.func(args)  # type: ignore[attr-defined]

    assert rc == 0
    # PROMOTED·영업중 2건만 적재 (billiard_halls EXCLUDED skip).
    assert await _feature_count(migrated_engine) == 2


async def test_cli_import_mois_skips_when_locked(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    path = tmp_path / "snap.ndjson"
    path.write_text(_NDJSON, encoding="utf-8")

    key = import_lock_key(PROVIDER_NAME, DATASET_KEY_BULK)
    args = _import_args(container_dsn, path)

    # 다른 세션이 import advisory lock을 쥐고 있으면 CLI job은 즉시 skip.
    async with (
        AsyncSession(migrated_engine) as holder,
        advisory_lock(holder, key),
    ):
        rc = await args.func(args)  # type: ignore[attr-defined]

    assert rc == 3  # _EXIT_LOCK_SKIPPED
    assert await _feature_count(migrated_engine) == 0


async def test_cli_import_mois_incremental_advances_cursor(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    path = tmp_path / "inc.ndjson"
    path.write_text(_NDJSON, encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--dsn", container_dsn, "import", "mois", str(path),
            "--mode", "incremental", "--cursor", "2026-06-01",
        ]
    )
    rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 0
    assert await _feature_count(migrated_engine) == 2
    # cursor가 history dataset에 영속화됨.
    from kortravelmap.infra.sync_state_repo import get_sync_state
    from kortravelmap.providers.mois import DATASET_KEY_HISTORY

    async with AsyncSession(migrated_engine) as session:
        state = await get_sync_state(
            session, provider=PROVIDER_NAME, dataset_key=DATASET_KEY_HISTORY
        )
    assert state is not None
    assert state.cursor == {"last_modified_date": "2026-06-01"}


async def test_cli_import_mois_incremental_requires_cursor(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    path = tmp_path / "inc.ndjson"
    path.write_text(_NDJSON, encoding="utf-8")
    args = build_parser().parse_args(
        ["--dsn", container_dsn, "import", "mois", str(path), "--mode", "incremental"]
    )
    rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 2  # _EXIT_INVALID — cursor 누락


_CLOSED_NDJSON = '{"service_slug":"general_restaurants","mng_no":"cli-1"}\n'


async def _active_feature_count(engine: AsyncEngine) -> int:
    async with AsyncSession(engine) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM feature.features "
                        "WHERE deleted_at IS NULL"
                    )
                )
            ).scalar_one()
        )


async def test_cli_import_mois_closed_inactivates(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    # bulk 적재(2건).
    bulk = tmp_path / "snap.ndjson"
    bulk.write_text(_NDJSON, encoding="utf-8")
    bulk_args = _import_args(container_dsn, bulk)
    rc = await bulk_args.func(bulk_args)  # type: ignore[attr-defined]
    assert rc == 0
    assert await _active_feature_count(migrated_engine) == 2

    # 폐업 통지(cli-1) → inactive.
    closed = tmp_path / "closed.ndjson"
    closed.write_text(_CLOSED_NDJSON, encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--dsn", container_dsn, "import", "mois", str(closed),
            "--mode", "closed", "--cursor", "2026-06-03",
        ]
    )
    rc2 = await args.func(args)  # type: ignore[attr-defined]
    assert rc2 == 0
    # cli-1 inactive → active 1건(cli-2)만.
    assert await _active_feature_count(migrated_engine) == 1

    # closed dataset cursor 영속.
    from kortravelmap.infra.sync_state_repo import get_sync_state
    from kortravelmap.providers.mois import DATASET_KEY_CLOSED

    async with AsyncSession(migrated_engine) as session:
        state = await get_sync_state(
            session, provider=PROVIDER_NAME, dataset_key=DATASET_KEY_CLOSED
        )
    assert state is not None
    assert state.cursor == {"last_modified_date": "2026-06-03"}


async def test_cli_import_mois_closed_requires_cursor(
    container_dsn: str, migrated_engine: AsyncEngine, tmp_path: Path
) -> None:
    closed = tmp_path / "closed.ndjson"
    closed.write_text(_CLOSED_NDJSON, encoding="utf-8")
    args = build_parser().parse_args(
        ["--dsn", container_dsn, "import", "mois", str(closed), "--mode", "closed"]
    )
    rc = await args.func(args)  # type: ignore[attr-defined]
    assert rc == 2  # _EXIT_INVALID — cursor 누락
