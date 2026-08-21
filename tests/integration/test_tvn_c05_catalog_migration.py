"""TVN-C05 catalog migration(0230) — 대리키가 아니라 자연키로 붙는지 검증한다.

이 gate가 왜 따로 필요한가: 통합 테스트 DB는 ``0200_schema_baseline``이
``alembic/baseline/seed.sql``을 실행하므로 C05 catalog가 이미 70~74번으로 서 있는
DB만 본다. 그래서 **0230이 대리키를 하드코딩해도 CI는 늘 초록이었다** — 실제
prod는 같은 자연키를 다른 번호로 들고 있었고(73번은
``python-datagokr-api/standard_special_streets``), 거기서만 배포가 멈췄다.

여기서 지키는 성질은 세 가지다.

1. **id-agnostic delta.** "성공했다"가 아니라 "무엇이 늘었고 무엇이 그대로인가"를
   본다. catalog 세 테이블을 자연키로 정규화해 통째로 스냅숏하고, upgrade 전후의
   차이가 정확히 선언한 5 dataset + 10 operation + 5 scope인지, 기존 행은 id까지
   포함해 한 톨도 움직이지 않았는지 확인한다. 숫자 하나를 단언하는 회귀
   테스트였다면 "73만 피해 가는" 구현이 그대로 통과한다.
2. **선점된 대리키를 하나가 아니라 70~74 전부 막아 둔다.** 예전 판이 노리던 번호
   전체가 남의 것이면, 대리키를 다시 하드코딩하는 구현은 어떤 번호를 고르든 죽는다.
3. **정직한 실패 결합.** ``pytest.raises(match=...)``는 ``str(DBAPIError)``를 훑는데
   SQLAlchemy가 실행 SQL 원문을 그 문자열에 덧붙인다. assert 블록의 SQL 안에 그
   한국어 메시지가 그대로 들어 있으므로, 어떤 이유로 죽든 정규식이 맞아 버린다.
   그래서 여기서는 ``.orig``의 sqlstate와 **SQL 원문에는 없는 payload**(대상
   dataset_key가 붙은 형태)로 단언한다.
"""

from __future__ import annotations

import asyncio
import json
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

#: 예전 판이 하드코딩했던 대리키 전 구간. 하나만 막으면 "그 하나만 피해 가는"
#: 구현이 통과하므로 전부 선점시킨다.
_OCCUPIED_SURROGATE_IDS: tuple[int, ...] = (70, 71, 72, 73, 74)

#: prod에서 실제로 73번을 들고 있던 자연키. decoy 이름에 그대로 쓰지는 않고
#: (자연키 UNIQUE가 seed의 69번과 부딪힌다) 사건 기록으로만 남긴다.
_PROD_OCCUPANT = "python-datagokr-api/standard_special_streets"

_DECOY_PROVIDER = "python-decoy-api"

_ROUTE_CAPS = {"produces": ["route"], "extensions": {}, "schema_version": 1}
_WEATHER_CAPS = {"produces": ["weather"], "extensions": {}, "schema_version": 1}
_NOTICE_CAPS = {"produces": ["notice"], "extensions": {}, "schema_version": 1}

#: (dataset_key, display_name, capabilities, refresh operation_key)
_C05_DECLARED: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    (
        "krforest_mountain_trails",
        "산림청 등산로(PBD0000041) route",
        _ROUTE_CAPS,
        "feature_route_krforest_mountain_trails_job",
    ),
    (
        "krforest_dulle_trails",
        "산림청 둘레길(PBD0000031) route",
        _ROUTE_CAPS,
        "feature_route_krforest_dulle_trails_job",
    ),
    (
        "krforest_mountain_weather",
        "산림청 산악기상 관측(15084696)",
        _WEATHER_CAPS,
        "feature_weather_krforest_mountain_weather_job",
    ),
    (
        "krforest_wildfire_risk_forecast",
        "산림청 산불위험 V2 예보(15084817)",
        _WEATHER_CAPS,
        "feature_weather_krforest_wildfire_risk_forecast_job",
    ),
    (
        "krforest_landslide_forecast_issues",
        "산림청 산사태 예보발령·해제(15074798)",
        _NOTICE_CAPS,
        "feature_notice_krforest_landslide_forecast_issues_job",
    ),
)

_C05_DATASET_KEYS: tuple[str, ...] = tuple(key for key, _, _, _ in _C05_DECLARED)
_DATASET_KEY_LIST = ", ".join(f"'{key}'" for key in _C05_DATASET_KEYS)


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


#: upgrade가 만들어야 하는 dataset 행 — 대리키를 뺀 자연키 표현.
_EXPECTED_NEW_DATASETS: frozenset[tuple[str, str, str, str, bool, str]] = frozenset(
    (_C05_PROVIDER, key, display_name, "openapi", True, _canonical(capabilities))
    for key, display_name, capabilities, _ in _C05_DECLARED
)

#: upgrade가 만들어야 하는 operation 행 (refresh + preview).
_EXPECTED_NEW_OPERATIONS: frozenset[tuple[str, str, str, str, bool, str]] = frozenset(
    row
    for key, _, _, refresh_key in _C05_DECLARED
    for row in (
        (_C05_PROVIDER, key, refresh_key, "refresh", True, _canonical({})),
        (
            _C05_PROVIDER,
            key,
            f"{refresh_key}.preview",
            "preview",
            True,
            _canonical({"handler": "fixture"}),
        ),
    )
)

_EXPECTED_NEW_SCOPES: frozenset[tuple[str, str, str, str, str]] = frozenset(
    (_C05_PROVIDER, key, "dataset_wide", refresh_key, "refresh")
    for key, _, _, refresh_key in _C05_DECLARED
)


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
    """전용 빈 DB + alembic Config. 종료 시 DB를 제거한다.

    ``_GATE_DB``가 다른 gate와 부딪히지 않는 이유는 이름이 다른 것뿐 아니라
    ``pg_container``가 session(=xdist worker)마다 별도 컨테이너이기 때문이다.
    외부에서 주입한 공용 DSN으로 바뀌면 이 전제가 깨진다.
    """

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


# upgrade 대상은 리터럴 상수로만 넘긴다 — ``test_alembic_squash_boundary``의
# revision scanner는 인자로 받은 이름을 정적으로 풀 수 없어 "dynamic/unresolved"로
# 막는다(0200 이전 archive 실행 차단). 두 helper로 나눠 두면 scanner가 각각을 읽는다.
async def _upgrade_before_c05(cfg: Config) -> None:
    from tests.integration._tvn34_migration_bootstrap import alembic_schema_owner_role

    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, cfg, _BEFORE_C05)


async def _upgrade_c05(cfg: Config) -> None:
    from tests.integration._tvn34_migration_bootstrap import alembic_schema_owner_role

    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, cfg, _C05)


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
    await _upgrade_before_c05(cfg)
    return admin_dsn


# ---------------------------------------------------------------------------
# catalog 스냅숏 — 대리키를 값이 아니라 "자연키 → id" 대응으로만 들고 다닌다.
# ---------------------------------------------------------------------------

_DATASET_SNAPSHOT_SQL = """
SELECT provider, dataset_key, display_name, source_kind, is_active,
       capabilities::text AS capabilities, provider_dataset_id
  FROM provider_sync.provider_datasets
"""

_OPERATION_SNAPSHOT_SQL = """
SELECT dataset.provider, dataset.dataset_key, operation.operation_key,
       operation.operation_kind, operation.is_enabled, operation.config::text AS config
  FROM provider_sync.provider_dataset_operations AS operation
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = operation.provider_dataset_id
"""

_SCOPE_SNAPSHOT_SQL = """
SELECT dataset.provider, dataset.dataset_key, scope.sync_scope,
       scope.operation_key, scope.operation_kind
  FROM provider_sync.provider_dataset_operation_scopes AS scope
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = scope.provider_dataset_id
"""


class _CatalogSnapshot:
    """세 catalog 테이블을 자연키로 정규화한 값 묶음."""

    def __init__(
        self,
        datasets: frozenset[tuple[str, str, str, str, bool, str]],
        operations: frozenset[tuple[str, str, str, str, bool, str]],
        scopes: frozenset[tuple[str, str, str, str, str]],
        ids: dict[tuple[str, str], int],
    ) -> None:
        self.datasets = datasets
        self.operations = operations
        self.scopes = scopes
        self.ids = ids


async def _snapshot(admin_dsn: str) -> _CatalogSnapshot:
    dataset_rows = await _fetch(admin_dsn, _DATASET_SNAPSHOT_SQL)
    operation_rows = await _fetch(admin_dsn, _OPERATION_SNAPSHOT_SQL)
    scope_rows = await _fetch(admin_dsn, _SCOPE_SNAPSHOT_SQL)
    return _CatalogSnapshot(
        datasets=frozenset(
            (
                row["provider"],
                row["dataset_key"],
                row["display_name"],
                row["source_kind"],
                row["is_active"],
                _canonical(json.loads(row["capabilities"])),
            )
            for row in dataset_rows
        ),
        operations=frozenset(
            (
                row["provider"],
                row["dataset_key"],
                row["operation_key"],
                row["operation_kind"],
                row["is_enabled"],
                _canonical(json.loads(row["config"])),
            )
            for row in operation_rows
        ),
        scopes=frozenset(
            (
                row["provider"],
                row["dataset_key"],
                row["sync_scope"],
                row["operation_key"],
                row["operation_kind"],
            )
            for row in scope_rows
        ),
        ids={
            (row["provider"], row["dataset_key"]): row["provider_dataset_id"]
            for row in dataset_rows
        },
    )


def _assert_only_added(
    before: _CatalogSnapshot,
    after: _CatalogSnapshot,
    *,
    datasets: frozenset[tuple[str, str, str, str, bool, str]],
    operations: frozenset[tuple[str, str, str, str, bool, str]],
    scopes: frozenset[tuple[str, str, str, str, str]],
) -> None:
    """delta가 정확히 기대한 행이고, 기존 행은 id까지 그대로인지 본다."""

    assert after.datasets - before.datasets == datasets
    assert before.datasets - after.datasets == frozenset(), "기존 dataset이 바뀌었다"
    assert after.operations - before.operations == operations
    assert before.operations - after.operations == frozenset(), "기존 operation이 바뀌었다"
    assert after.scopes - before.scopes == scopes
    assert before.scopes - after.scopes == frozenset(), "기존 scope가 바뀌었다"
    for natural_key, dataset_id in before.ids.items():
        assert after.ids[natural_key] == dataset_id, (
            f"기존 dataset의 대리키가 움직였다: {natural_key}"
        )


# ---------------------------------------------------------------------------
# prod 모양 fixture
# ---------------------------------------------------------------------------

_DECOY_VALUES = ",\n    ".join(
    f"({surrogate_id}, '{_DECOY_PROVIDER}', 'decoy_occupies_{surrogate_id}', "
    f"'C05 대리키 선점 재현 {surrogate_id}', 'system', true, "
    '\'{"produces": [], "extensions": {}, "schema_version": 1}\', now(), now())'
    for surrogate_id in _OCCUPIED_SURROGATE_IDS
)

_STRIP_C05_SQL = f"""
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
"""

#: C05 catalog를 걷어낸 자리를 남의 자연키가 전부 선점하게 만든다 — prod가 실제로
#: 있던 상태(73번은 {_PROD_OCCUPANT})를 대리키 구간 전체로 넓힌 것이다.
_OCCUPY_SURROGATES_SQL = f"""
INSERT INTO provider_sync.provider_datasets
    (provider_dataset_id, provider, dataset_key, display_name, source_kind,
     is_active, capabilities, created_at, updated_at)
OVERRIDING SYSTEM VALUE
VALUES
    {_DECOY_VALUES};
"""


async def _assert_prod_shape(admin_dsn: str) -> None:
    """fixture가 실제로 prod 모양을 만들었는지 먼저 확인한다.

    이 선행 단언이 없으면 fixture가 아무것도 안 해도(예: seed 구성이 바뀌어
    DELETE가 0행) 아래 본 단언이 그대로 통과해 버린다.
    """

    remaining = await _fetchval(
        admin_dsn,
        "SELECT count(*) FROM provider_sync.provider_datasets "
        f"WHERE provider = '{_C05_PROVIDER}' "
        f"AND dataset_key IN ({_DATASET_KEY_LIST})",
    )
    assert remaining == 0, "fixture가 C05 catalog를 걷어내지 못했다"

    occupied = await _fetchval(
        admin_dsn,
        "SELECT count(*) FROM provider_sync.provider_datasets "
        f"WHERE provider_dataset_id = ANY(ARRAY{list(_OCCUPIED_SURROGATE_IDS)}) "
        f"AND provider = '{_DECOY_PROVIDER}'",
    )
    assert occupied == len(_OCCUPIED_SURROGATE_IDS), (
        f"대리키 {list(_OCCUPIED_SURROGATE_IDS)}가 전부 선점된 상태여야 한다 "
        f"(실제 {occupied}개)"
    )

    # sequence가 선점 구간보다 앞서 있어야 이 fixture가 의미를 갖는다. 뒤처져 있으면
    # 새 dataset이 선점 구간을 다시 노리게 되어 테스트가 다른 것을 재게 된다.
    last_value = await _fetchval(
        admin_dsn,
        "SELECT last_value FROM "
        "provider_sync.provider_datasets_provider_dataset_id_seq",
    )
    assert last_value > max(_OCCUPIED_SURROGATE_IDS), (
        f"sequence({last_value})가 선점 구간보다 앞서 있어야 한다"
    )


async def test_c05_catalog_binds_by_natural_key_when_surrogates_are_taken(
    c05_alembic_config: Config,
) -> None:
    """대리키 70~74가 전부 남의 것인 DB에서도 0230이 자연키로 정확히 붙는다."""

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(admin_dsn, _STRIP_C05_SQL)
    await _execute(admin_dsn, _OCCUPY_SURROGATES_SQL)
    await _assert_prod_shape(admin_dsn)

    before = await _snapshot(admin_dsn)
    await _upgrade_c05(cfg)
    after = await _snapshot(admin_dsn)

    _assert_only_added(
        before,
        after,
        datasets=_EXPECTED_NEW_DATASETS,
        operations=_EXPECTED_NEW_OPERATIONS,
        scopes=_EXPECTED_NEW_SCOPES,
    )

    # 선점 구간을 빼앗지 않았다 = 숫자가 아니라 자연키로 붙었다.
    new_ids = {after.ids[(_C05_PROVIDER, key)] for key in _C05_DATASET_KEYS}
    assert new_ids.isdisjoint(_OCCUPIED_SURROGATE_IDS), (
        f"선점된 대리키를 빼앗았다: {sorted(new_ids & set(_OCCUPIED_SURROGATE_IDS))}"
    )

    # 선점자에게 C05 operation/scope가 달라붙지 않았다.
    strays = await _fetchval(
        admin_dsn,
        "SELECT ("
        "  SELECT count(*) FROM provider_sync.provider_dataset_operations"
        f"   WHERE provider_dataset_id = ANY(ARRAY{list(_OCCUPIED_SURROGATE_IDS)})"
        ") + ("
        "  SELECT count(*) FROM provider_sync.provider_dataset_operation_scopes"
        f"   WHERE provider_dataset_id = ANY(ARRAY{list(_OCCUPIED_SURROGATE_IDS)})"
        ")",
    )
    assert strays == 0, "C05 operation/scope가 남의 dataset에 붙었다"


async def test_c05_catalog_migration_changes_nothing_on_seeded_db(
    c05_alembic_config: Config,
) -> None:
    """baseline seed가 이미 심어 둔 DB에서는 catalog가 한 톨도 바뀌지 않는다.

    행 수 비교가 아니라 세 테이블 전체 스냅숏 비교다 — 같은 수만큼 지웠다 넣거나
    ``config``/``is_enabled``만 덮어쓰는 구현을 행 수로는 볼 수 없다.
    """

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)

    before = await _snapshot(admin_dsn)
    assert any(key in {k for _, k in before.ids} for key in _C05_DATASET_KEYS), (
        "seed가 C05 catalog를 심어 둔 상태여야 한다"
    )

    await _upgrade_c05(cfg)
    after = await _snapshot(admin_dsn)

    _assert_only_added(
        before,
        after,
        datasets=frozenset(),
        operations=frozenset(),
        scopes=frozenset(),
    )


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

    await _upgrade_c05(cfg)

    after = await _fetchval(
        admin_dsn,
        "SELECT last_value FROM "
        "provider_sync.provider_datasets_provider_dataset_id_seq",
    )
    assert after >= before, f"sequence를 되감았다: {before} → {after}"


async def test_c05_catalog_migration_repairs_a_lagging_identity_sequence(
    c05_alembic_config: Config,
) -> None:
    """sequence가 max보다 **뒤처진** DB에서도 upgrade가 끝난다.

    ``_SEQUENCE_SQL``이 존재하는 이유가 이 상태인데, 그 문장이 dataset INSERT 뒤에
    있으면 정작 여기서 INSERT가 먼저 죽는다 — nextval이 이미 쓰이는 번호를 돌려주고
    자연키 arbiter는 대리키 충돌을 잡지 못해 ``pk_provider_datasets`` 위반이 난다.
    """

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(admin_dsn, _STRIP_C05_SQL)
    await _execute(
        admin_dsn,
        "SELECT setval("
        "'provider_sync.provider_datasets_provider_dataset_id_seq', 40, true)",
    )

    max_id = await _fetchval(
        admin_dsn,
        "SELECT max(provider_dataset_id) FROM provider_sync.provider_datasets",
    )
    assert max_id > 40, f"이 gate는 sequence가 max({max_id})보다 뒤처진 상태를 전제한다"

    before = await _snapshot(admin_dsn)
    await _upgrade_c05(cfg)
    after = await _snapshot(admin_dsn)

    _assert_only_added(
        before,
        after,
        datasets=_EXPECTED_NEW_DATASETS,
        operations=_EXPECTED_NEW_OPERATIONS,
        scopes=_EXPECTED_NEW_SCOPES,
    )
    last_value = await _fetchval(
        admin_dsn,
        "SELECT last_value FROM "
        "provider_sync.provider_datasets_provider_dataset_id_seq",
    )
    assert last_value >= max_id


async def test_c05_catalog_migration_refuses_a_conflicting_contract(
    c05_alembic_config: Config,
) -> None:
    """같은 자연키가 다른 계약으로 이미 있으면 조용히 넘어가지 않고 멈춘다.

    ``match=``를 쓰지 않는 이유는 모듈 docstring에 적었다 — SQLAlchemy가 실행 SQL
    원문을 예외 문자열에 붙이는데 그 안에 이 메시지가 그대로 들어 있다. sqlstate와
    SQL 원문에는 없는 payload(대상 dataset_key)로 결합한다.
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

    with pytest.raises(DBAPIError) as raised:
        await _upgrade_c05(cfg)

    original = raised.value.orig
    assert getattr(original, "sqlstate", None) == "23514", (
        f"다른 오류로 죽었다: {original!r}"
    )
    assert "계약이 선언과 다르다" in str(original)
    assert "krforest_wildfire_risk_forecast" in str(original)


# ---------------------------------------------------------------------------
# 사후 단언 블록의 **각 가지**가 실제로 도는지 — migration 안에서는 upgrade가
# 성공해 버려 도달하지 않으므로, SQL을 그대로 꺼내 조작한 DB에 직접 건다.
# ---------------------------------------------------------------------------


def _catalog_assert_sql() -> str:
    import importlib.util

    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240 — 순수 경로 연산.
    path = root / "alembic" / "versions" / f"{_C05}.py"
    spec = importlib.util.spec_from_file_location("tvn_c05_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statement: str = module._CATALOG_ASSERT_SQL  # noqa: SLF001 — 검증 대상 그 자체.
    return statement


async def _assert_catalog_block_rejects(
    admin_dsn: str,
    *,
    sqlstate: str,
    message_fragment: str,
    payload_fragment: str,
) -> None:
    import asyncpg

    with pytest.raises(asyncpg.PostgresError) as raised:
        await _execute(admin_dsn, _catalog_assert_sql())
    error = raised.value
    assert error.sqlstate == sqlstate, f"다른 오류로 죽었다: {error!r}"
    assert message_fragment in str(error)
    assert payload_fragment in str(error)


async def test_catalog_assert_rejects_a_missing_dataset(
    c05_alembic_config: Config,
) -> None:
    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(admin_dsn, _STRIP_C05_SQL)

    await _assert_catalog_block_rejects(
        admin_dsn,
        sqlstate="23502",
        message_fragment="provider dataset이 선언되지 않았다",
        payload_fragment="krforest_wildfire_risk_forecast",
    )


async def test_catalog_assert_rejects_a_missing_operation(
    c05_alembic_config: Config,
) -> None:
    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(
        admin_dsn,
        "DELETE FROM provider_sync.provider_dataset_operations AS operation"
        " USING provider_sync.provider_datasets AS dataset"
        " WHERE dataset.provider_dataset_id = operation.provider_dataset_id"
        f" AND dataset.provider = '{_C05_PROVIDER}'"
        " AND dataset.dataset_key = 'krforest_mountain_weather'"
        " AND operation.operation_kind = 'preview'",
    )

    await _assert_catalog_block_rejects(
        admin_dsn,
        sqlstate="23502",
        message_fragment="operation이 선언되지 않았다",
        payload_fragment=(
            "krforest_mountain_weather/"
            "feature_weather_krforest_mountain_weather_job.preview"
        ),
    )


async def test_catalog_assert_rejects_a_disabled_operation(
    c05_alembic_config: Config,
) -> None:
    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(
        admin_dsn,
        "UPDATE provider_sync.provider_dataset_operations AS operation"
        " SET is_enabled = false"
        " FROM provider_sync.provider_datasets AS dataset"
        " WHERE dataset.provider_dataset_id = operation.provider_dataset_id"
        f" AND dataset.provider = '{_C05_PROVIDER}'"
        " AND dataset.dataset_key = 'krforest_dulle_trails'"
        " AND operation.operation_kind = 'refresh'",
    )

    await _assert_catalog_block_rejects(
        admin_dsn,
        sqlstate="23514",
        message_fragment="operation이 꺼져 있다",
        payload_fragment=(
            "krforest_dulle_trails/feature_route_krforest_dulle_trails_job"
        ),
    )


async def test_catalog_assert_rejects_a_missing_scope(
    c05_alembic_config: Config,
) -> None:
    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(
        admin_dsn,
        "DELETE FROM provider_sync.provider_dataset_operation_scopes AS scope"
        " USING provider_sync.provider_datasets AS dataset"
        " WHERE dataset.provider_dataset_id = scope.provider_dataset_id"
        f" AND dataset.provider = '{_C05_PROVIDER}'"
        " AND dataset.dataset_key = 'krforest_landslide_forecast_issues'",
    )

    await _assert_catalog_block_rejects(
        admin_dsn,
        sqlstate="23502",
        message_fragment="dataset_wide scope가 선언되지 않았다",
        payload_fragment=(
            "krforest_landslide_forecast_issues/"
            "feature_notice_krforest_landslide_forecast_issues_job"
        ),
    )


async def test_catalog_assert_passes_on_the_seeded_catalog(
    c05_alembic_config: Config,
) -> None:
    """가지 4개가 모두 침묵하는 경우도 한 번 고정한다 — 늘 raise하는 블록이면
    위 네 테스트가 전부 통과하면서 아무것도 증명하지 못한다."""

    cfg = c05_alembic_config
    admin_dsn = await _stage_before_c05(cfg)
    await _execute(admin_dsn, _catalog_assert_sql())
