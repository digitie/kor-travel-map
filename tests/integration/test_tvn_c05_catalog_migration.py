"""TVN-C05 catalog migration(0230) — 대리키가 아니라 자연키로 붙는지 검증한다.

이 gate가 왜 따로 필요한가: 통합 테스트 DB는 ``0200_schema_baseline``이
``alembic/baseline/seed.sql``을 실행하므로 C05 catalog가 이미 70~74번으로 서 있는
DB만 본다. 그래서 **0230이 대리키를 하드코딩해도 CI는 늘 초록이었다** — 실제
prod는 같은 자연키를 다른 번호로 들고 있었고(73번은
``python-datagokr-api/standard_special_streets``), 거기서만 배포가 멈췄다.
여기서는 그 prod 모양을 명시적으로 만들어 놓고 migration을 돌린다.

핵심 단언은 "성공했다"가 아니라 **"엉뚱한 dataset에 붙지 않았다"**다. 예전 판은
``ON CONFLICT (provider_dataset_id) DO NOTHING``으로 dataset을 건너뛴 뒤 같은
숫자로 operation을 밀어 넣었으므로, 선점된 대리키 아래에서 가드를 걷어내면 남의
dataset에 C05 operation이 달라붙는다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic.config import Config
from sqlalchemy.exc import DBAPIError

from alembic import command

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

_GATE_DB = "tvn_c05_catalog_gate"

#: 0230 직전 revision. 여기까지 올린 DB를 prod 모양으로 깎은 뒤 0230만 적용한다.
_BEFORE_C05 = "0229_tvn40b_source_rule_action"
_C05 = "0230_tvn_c05_krforest_datasets"

_C05_PROVIDER = "python-krforest-api"

#: (dataset_key, refresh operation_key)
_C05_DATASETS: tuple[tuple[str, str], ...] = (
    ("krforest_mountain_trails", "feature_route_krforest_mountain_trails_job"),
    ("krforest_dulle_trails", "feature_route_krforest_dulle_trails_job"),
    ("krforest_mountain_weather", "feature_weather_krforest_mountain_weather_job"),
    (
        "krforest_wildfire_risk_forecast",
        "feature_weather_krforest_wildfire_risk_forecast_job",
    ),
    (
        "krforest_landslide_forecast_issues",
        "feature_notice_krforest_landslide_forecast_issues_job",
    ),
)

#: prod에서 실제로 선점돼 있던 대리키. 예전 판이 ``krforest_wildfire_risk_forecast``
#: 에 배정하려던 번호다.
_OCCUPIED_SURROGATE_ID = 73

_DECOY_PROVIDER = "python-decoy-api"
_DECOY_DATASET_KEY = "decoy_occupies_surrogate_73"


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _connect(url: str) -> Any:
    import asyncpg  # local import — dev/integration 전용 의존.

    parts = urlsplit(url)
    return await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )


async def _execute(url: str, statement: str) -> None:
    conn = await _connect(url)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


async def _fetch(url: str, statement: str) -> list[Any]:
    conn = await _connect(url)
    try:
        return list(await conn.fetch(statement))
    finally:
        await conn.close()


async def _fetchval(url: str, statement: str) -> Any:
    conn = await _connect(url)
    try:
        return await conn.fetchval(statement)
    finally:
        await conn.close()


@pytest.fixture
async def c05_alembic_config(pg_container: object) -> AsyncIterator[Config]:
    """전용 빈 DB + alembic Config. 종료 시 DB를 제거한다."""

    from kortravelmap.infra.db import normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    await _execute(raw_dsn, f'DROP DATABASE IF EXISTS "{_GATE_DB}" WITH (FORCE)')
    await _execute(raw_dsn, f'CREATE DATABASE "{_GATE_DB}"')

    gate_dsn = normalize_async_dsn(_with_database(raw_dsn, _GATE_DB))
    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240 — 순수 경로 연산.
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", gate_dsn)
    try:
        yield cfg
    finally:
        await _execute(raw_dsn, f'DROP DATABASE IF EXISTS "{_GATE_DB}" WITH (FORCE)')


async def _upgrade(cfg: Config, revision: str) -> None:
    from tests.integration._tvn34_migration_bootstrap import alembic_schema_owner_role

    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, cfg, revision)


async def _stage_before_c05(cfg: Config) -> str:
    """0229까지 올리고 **admin(superuser) DSN**을 돌려준다.

    반환값은 migrator 자격으로 바꿔치우기 **전**의 fixture DSN이다. 이후 fixture
    조작·단언은 반드시 이 반환값을 써야 한다 — ``ktm_feature_migrator``는
    NOINHERIT라 ``SET ROLE`` 없이는 app schema를 읽지도 못한다(ADR-090).
    """

    from tests.integration._tvn34_migration_bootstrap import bootstrapped_migrator_dsn

    admin_dsn = cfg.get_main_option("sqlalchemy.url")
    assert admin_dsn is not None
    cfg.set_main_option("sqlalchemy.url", await bootstrapped_migrator_dsn(admin_dsn))
    await _upgrade(cfg, _BEFORE_C05)
    return admin_dsn


_DATASET_KEY_LIST = ", ".join(f"'{key}'" for key, _ in _C05_DATASETS)

#: baseline seed가 이미 심어 둔 C05 catalog를 걷어내고, 예전 판이 노리던 대리키를
#: 다른 자연키가 선점하게 만든다 — 곧 prod가 실제로 있던 상태다.
_MAKE_PROD_SHAPE_SQL = f"""
DELETE FROM provider_sync.provider_dataset_operation_scopes AS scope
 USING provider_sync.provider_datasets AS dataset
 WHERE dataset.provider_dataset_id = scope.provider_dataset_id
   AND dataset.provider = '{_C05_PROVIDER}'
   AND dataset.dataset_key IN ({_DATASET_KEY_LIST});

DELETE FROM provider_sync.provider_dataset_operations AS operation
 USING provider_sync.provider_datasets AS dataset
 WHERE dataset.provider_dataset_id = operation.provider_dataset_id
   AND dataset.provider = '{_C05_PROVIDER}'
   AND dataset.dataset_key IN ({_DATASET_KEY_LIST});

DELETE FROM provider_sync.provider_datasets
 WHERE provider = '{_C05_PROVIDER}'
   AND dataset_key IN ({_DATASET_KEY_LIST});

INSERT INTO provider_sync.provider_datasets
    (provider_dataset_id, provider, dataset_key, display_name, source_kind,
     is_active, capabilities, created_at, updated_at)
OVERRIDING SYSTEM VALUE
VALUES
    ({_OCCUPIED_SURROGATE_ID}, '{_DECOY_PROVIDER}', '{_DECOY_DATASET_KEY}',
     'C05 대리키 선점 재현', 'system', true,
     '{{"produces": [], "extensions": {{}}, "schema_version": 1}}',
     now(), now());
"""


async def _assert_prod_shape(admin_dsn: str) -> None:
    """fixture가 실제로 prod 모양을 만들었는지 먼저 확인한다.

    이 선행 단언이 없으면 fixture가 아무것도 안 해도(예: seed 구성이 바뀌어
    DELETE가 0행) 아래 본 단언이 그대로 통과해 버린다.
    """

    remaining = await _fetchval(
        admin_dsn,
        f"SELECT count(*) FROM provider_sync.provider_datasets "
        f"WHERE provider = '{_C05_PROVIDER}' "
        f"AND dataset_key IN ({_DATASET_KEY_LIST})",
    )
    assert remaining == 0, "fixture가 C05 catalog를 걷어내지 못했다"

    occupant = await _fetchval(
        admin_dsn,
        "SELECT provider || '/' || dataset_key FROM provider_sync.provider_datasets "
        f"WHERE provider_dataset_id = {_OCCUPIED_SURROGATE_ID}",
    )
    assert occupant == f"{_DECOY_PROVIDER}/{_DECOY_DATASET_KEY}", (
        f"대리키 {_OCCUPIED_SURROGATE_ID}가 선점된 상태여야 한다 (실제: {occupant})"
    )


async def _c05_dataset_ids(admin_dsn: str) -> dict[str, int]:
    rows = await _fetch(
        admin_dsn,
        "SELECT dataset_key, provider_dataset_id FROM provider_sync.provider_datasets "
        f"WHERE provider = '{_C05_PROVIDER}' "
        f"AND dataset_key IN ({_DATASET_KEY_LIST})",
    )
    return {row["dataset_key"]: row["provider_dataset_id"] for row in rows}


async def test_c05_catalog_binds_by_natural_key_when_surrogate_id_is_taken(
    c05_alembic_config: Config,
) -> None:
    """대리키가 남에게 배정된 DB에서도 0230이 자연키로 정확히 붙는다."""

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(admin_dsn, _MAKE_PROD_SHAPE_SQL)
    await _assert_prod_shape(admin_dsn)

    await _upgrade(cfg, _C05)

    dataset_ids = await _c05_dataset_ids(admin_dsn)
    assert set(dataset_ids) == {key for key, _ in _C05_DATASETS}
    assert len(set(dataset_ids.values())) == len(_C05_DATASETS)
    assert _OCCUPIED_SURROGATE_ID not in dataset_ids.values(), (
        "선점된 대리키를 빼앗았다 — 자연키가 아니라 숫자로 붙고 있다"
    )

    # 선점자는 손대지 않았고, C05 operation/scope가 **거기 붙지 않았다**.
    occupant = await _fetchval(
        admin_dsn,
        "SELECT provider || '/' || dataset_key FROM provider_sync.provider_datasets "
        f"WHERE provider_dataset_id = {_OCCUPIED_SURROGATE_ID}",
    )
    assert occupant == f"{_DECOY_PROVIDER}/{_DECOY_DATASET_KEY}"
    strays = await _fetchval(
        admin_dsn,
        "SELECT ("
        "  SELECT count(*) FROM provider_sync.provider_dataset_operations"
        f"   WHERE provider_dataset_id = {_OCCUPIED_SURROGATE_ID}"
        ") + ("
        "  SELECT count(*) FROM provider_sync.provider_dataset_operation_scopes"
        f"   WHERE provider_dataset_id = {_OCCUPIED_SURROGATE_ID}"
        ")",
    )
    assert strays == 0, "C05 operation/scope가 남의 dataset에 붙었다"

    # 각 dataset이 refresh+preview 2건과 dataset_wide scope 1건을 자기 id로 갖는다.
    for dataset_key, refresh_key in _C05_DATASETS:
        dataset_id = dataset_ids[dataset_key]
        operations = await _fetch(
            admin_dsn,
            "SELECT operation_key, operation_kind "
            "FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id = {dataset_id} ORDER BY operation_key",
        )
        assert [(row["operation_key"], row["operation_kind"]) for row in operations] == [
            (refresh_key, "refresh"),
            (f"{refresh_key}.preview", "preview"),
        ], f"{dataset_key} operation이 어긋났다"

        scopes = await _fetch(
            admin_dsn,
            "SELECT sync_scope, operation_key, operation_kind "
            "FROM provider_sync.provider_dataset_operation_scopes "
            f"WHERE provider_dataset_id = {dataset_id}",
        )
        assert [
            (row["sync_scope"], row["operation_key"], row["operation_kind"])
            for row in scopes
        ] == [("dataset_wide", refresh_key, "refresh")], f"{dataset_key} scope가 어긋났다"


async def test_c05_catalog_migration_is_idempotent_on_seeded_db(
    c05_alembic_config: Config,
) -> None:
    """baseline seed가 이미 심어 둔 DB에서는 행을 늘리지도 옮기지도 않는다."""

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)

    before_ids = await _c05_dataset_ids(admin_dsn)
    assert before_ids, "seed가 C05 catalog를 심어 둔 상태여야 한다"
    before_counts = await _fetchval(
        admin_dsn,
        "SELECT (SELECT count(*) FROM provider_sync.provider_datasets) || '/' || "
        "(SELECT count(*) FROM provider_sync.provider_dataset_operations) || '/' || "
        "(SELECT count(*) FROM provider_sync.provider_dataset_operation_scopes)",
    )

    await _upgrade(cfg, _C05)

    assert await _c05_dataset_ids(admin_dsn) == before_ids
    after_counts = await _fetchval(
        admin_dsn,
        "SELECT (SELECT count(*) FROM provider_sync.provider_datasets) || '/' || "
        "(SELECT count(*) FROM provider_sync.provider_dataset_operations) || '/' || "
        "(SELECT count(*) FROM provider_sync.provider_dataset_operation_scopes)",
    )
    assert after_counts == before_counts


async def test_c05_catalog_migration_does_not_rewind_the_identity_sequence(
    c05_alembic_config: Config,
) -> None:
    """sequence를 max(id)로 되감지 않는다.

    seed는 ``setval(..., 82)``로 대리키 sequence를 max(74)보다 앞에 세워 둔다.
    예전 판의 ``setval(GREATEST(max(id), 1))``은 그것을 74로 되감았다.
    """

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)

    before = await _fetchval(
        admin_dsn,
        "SELECT last_value FROM "
        "provider_sync.provider_datasets_provider_dataset_id_seq",
    )
    max_id = await _fetchval(
        admin_dsn,
        "SELECT max(provider_dataset_id) FROM provider_sync.provider_datasets",
    )
    assert before > max_id, (
        "이 gate는 sequence가 max보다 앞선 상태를 전제한다 "
        f"(sequence={before}, max={max_id})"
    )

    await _upgrade(cfg, _C05)

    after = await _fetchval(
        admin_dsn,
        "SELECT last_value FROM "
        "provider_sync.provider_datasets_provider_dataset_id_seq",
    )
    assert after >= before, f"sequence를 되감았다: {before} → {after}"


async def test_c05_catalog_migration_refuses_a_conflicting_contract(
    c05_alembic_config: Config,
) -> None:
    """같은 자연키가 다른 계약으로 이미 있으면 조용히 넘어가지 않고 멈춘다.

    사후 단언 DO 블록이 실제로 돈다는 증거이기도 하다 — 이게 없으면 "아무것도 보지
    않는 초록"이 다시 생긴다.
    """

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)

    await _execute(
        admin_dsn,
        "UPDATE provider_sync.provider_datasets "
        "SET capabilities = "
        '\'{"produces": ["place"], "extensions": {}, "schema_version": 1}\'::jsonb '
        f"WHERE provider = '{_C05_PROVIDER}' "
        "AND dataset_key = 'krforest_wildfire_risk_forecast'",
    )

    with pytest.raises(DBAPIError, match="계약이 선언과 다르다"):
        await _upgrade(cfg, _C05)
