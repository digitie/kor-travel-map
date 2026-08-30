"""Alembic env.py — async-compatible, SecretStr DSN injection (ADR-007).

DSN은 `KorTravelMapSettings.pg_dsn` (`KOR_TRAVEL_MAP_PG_DSN` env var)에서 읽는다.
asyncpg driver로 정규화 후 `AsyncEngine`을 만들어 마이그레이션 실행.

``infra/models.py``의 ``metadata``를 ``target_metadata``로 사용 — autogenerate
지원 (현 PR#28부터). search_path는 ``public, x_extension`` (ADR-008).

사용:
    KOR_TRAVEL_MAP_PG_DSN=postgresql://... alembic upgrade head
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from logging.config import fileConfig
from pathlib import Path
from typing import TYPE_CHECKING

from alembic.runtime.migration import StampStep
from alembic.script import ScriptDirectory
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from kortravelmap.infra.alembic_exclusions import (
    UNCOMPARED_INDEXES as _UNCOMPARED_INDEXES,
)
from kortravelmap.infra.alembic_exclusions import (
    UNMAPPED_APP_TABLES as _UNMAPPED_APP_TABLES,
)
from kortravelmap.infra.db import normalize_async_dsn
from kortravelmap.infra.models import metadata

if TYPE_CHECKING:
    pass

# Alembic Config — alembic.ini.
config = context.config

# Logging setup.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# DSN 결정 우선순위:
#   1. 호출자가 ``Config.set_main_option('sqlalchemy.url', ...)``로 주입한 값
#      (예: 테스트 ``alembic.command.upgrade`` 직접 호출 시)
#   2. ``KOR_TRAVEL_MAP_PG_DSN`` env var (`KorTravelMapSettings.pg_dsn`)
# alembic.ini의 ``placeholder`` URL은 환경 미설정 fallback이며 항상 override.
_existing_url = config.get_main_option("sqlalchemy.url")
if not _existing_url or "placeholder" in _existing_url:
    from kortravelmap.settings import KorTravelMapSettings  # lazy import

    _settings = KorTravelMapSettings()
    _existing_url = normalize_async_dsn(_settings.pg_dsn.get_secret_value())
    config.set_main_option("sqlalchemy.url", _existing_url)
else:
    _existing_url = normalize_async_dsn(_existing_url)
    config.set_main_option("sqlalchemy.url", _existing_url)

# autogenerate 대상 metadata.
target_metadata = metadata

_USE_SCHEMA_OWNER_ROLE_ENV = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"
_BASELINE_300_REVISION = "300"
_BASELINE_300_HANDOFF_SOURCE = "0236_tvn41s_compaction_drained"
_BASELINE_300_HANDOFF_TAG = "application-schema-0236-to-300"
_BASELINE_300_HANDOFF_CAPABILITY_ENV = (
    "KOR_TRAVEL_MAP_APPLICATION_HANDOFF_CAPABILITY_PATH"
)
_BASELINE_300_HANDOFF_CAPABILITY_DIRECTORY = Path(
    "/run/kor-travel-map-application-handoff"
)
_BASELINE_300_HANDOFF_CAPABILITY_FILE = (
    _BASELINE_300_HANDOFF_CAPABILITY_DIRECTORY / "capability"
)
_BASELINE_300_DIR = Path(__file__).resolve().parent / "baseline"


def _verify_fresh_300_destination_facet(connection: Connection) -> None:
    """Alembic version row 기록 뒤 outer transaction commit 전에 destination을 봉인한다."""

    reference_raw = (_BASELINE_300_DIR / "application-reference.json").read_bytes()
    reference_digest_raw = (
        _BASELINE_300_DIR / "application-reference.sha256"
    ).read_bytes()
    reference_digest = reference_digest_raw.decode("ascii").strip()
    if (
        reference_digest_raw != f"{reference_digest}\n".encode("ascii")
        or hashlib.sha256(reference_raw).hexdigest() != reference_digest
    ):
        raise RuntimeError("fresh 300 destination reference manifest is invalid")
    reference = json.loads(reference_raw)
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("fresh 300 destination artifact map is invalid")
    sql_raw = (
        _BASELINE_300_DIR / "application-destination-alembic-version.sql"
    ).read_bytes()
    if hashlib.sha256(sql_raw).hexdigest() != artifacts.get(
        "destination_alembic_version_contract_sql_sha256"
    ):
        raise RuntimeError("fresh 300 destination facet SQL is invalid")
    rows = connection.execute(text(sql_raw.decode("utf-8")))
    digest = hashlib.sha256()
    for item in rows.scalars():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\n")
    if digest.hexdigest() != artifacts.get(
        "destination_alembic_version_contract_sha256"
    ):
        raise RuntimeError("fresh 300 destination facet does not match immutable reference")
_BASELINE_300_HANDOFF_CAPABILITY_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _require_application_handoff_capability() -> None:
    """root helper가 만든 one-shot capability 없이는 metadata stamp를 금지한다.

    ``Config.attributes``나 Alembic tag는 호출자가 자유롭게 만들 수 있으므로 권한
    증명이 아니다. Docker Manager가 root user로 실행한 one-shot helper만 `/run`의
    root-owned private directory에 capability를 만들고, helper가 끝나면 이를 제거한다.
    API/Dagster의 non-root runtime과 generic Alembic 호출은 이 파일을 만들거나 읽을 수
    없어야 한다.
    """

    configured = os.environ.get(_BASELINE_300_HANDOFF_CAPABILITY_ENV)
    if configured != str(_BASELINE_300_HANDOFF_CAPABILITY_FILE):
        raise RuntimeError(
            "0236-to-300 handoff requires the root-owned one-shot capability"
        )
    try:
        parent = _BASELINE_300_HANDOFF_CAPABILITY_DIRECTORY.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) != 0o700
            or parent.st_nlink != 2
        ):
            raise PermissionError("handoff capability directory is not trusted")
        metadata = _BASELINE_300_HANDOFF_CAPABILITY_FILE.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or metadata.st_nlink != 1
        ):
            raise PermissionError("handoff capability is not trusted")
        descriptor = os.open(
            _BASELINE_300_HANDOFF_CAPABILITY_FILE,
            os.O_RDONLY | os.O_NOFOLLOW,
        )
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != 0
                or stat.S_IMODE(opened.st_mode) != 0o400
                or opened.st_nlink != 1
            ):
                raise PermissionError("opened handoff capability is not trusted")
            token = os.read(descriptor, 65).decode("ascii")
            if os.read(descriptor, 1) or not _BASELINE_300_HANDOFF_CAPABILITY_PATTERN.fullmatch(
                token
            ):
                raise PermissionError("handoff capability token is invalid")
        finally:
            os.close(descriptor)
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "0236-to-300 handoff requires the root-owned one-shot capability"
        ) from exc


def _raw_alembic_heads(connection: Connection) -> tuple[str, ...]:
    """활성 script graph를 해석하지 않은 version table 원문을 읽는다."""

    version_table = connection.scalar(
        text("SELECT to_regclass('public.alembic_version')")
    )
    if version_table is None:
        return ()
    return tuple(
        str(revision)
        for revision in connection.execute(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        ).scalars()
    )


def _guard_application_schema_operation() -> bool:
    """`300` active graph 밖 lineage의 일반 조작을 시작 전에 거부한다.

    반환값이 ``True``이면 `0236 → 300` one-shot handoff만을 위한 stamp callback이
    설치된 상태다. 이 경로는 `command.stamp(..., purge=True)`의 generic resolver가
    retired `0236`을 해석하기 **전**에 빈 head set에서 `300`을 삽입하도록 교체한다.
    """

    migration_context = context.get_context()
    migration_fn = migration_context.opts.get("fn")
    operation = getattr(migration_fn, "__name__", None)
    if operation == "downgrade":
        raise RuntimeError(
            "300_schema_baseline is forward-only; application schema downgrade is "
            "unsupported"
        )
    if operation != "do_stamp":
        # 일반 fresh upgrade는 허용하되 retired `0236`을 발견하면 Alembic의
        # `Can't locate revision`보다 먼저 operator에게 정확한 protocol을 보인다.
        if operation == "upgrade" and not migration_context.as_sql:
            connection = migration_context.connection
            if connection is not None and _BASELINE_300_HANDOFF_SOURCE in _raw_alembic_heads(
                connection
            ):
                raise RuntimeError(
                    "0236 application schema requires the controlled "
                    "application-schema 0236-to-300 handoff; generic upgrade is "
                    "unsupported"
                )
        return False

    # `stamp`는 version metadata를 바꾸므로 generic invocation을 모두 막는다.
    # 도착 revision, purge, tag, root-owned one-shot capability, online mode 및 raw
    # source head가 함께 일치하는 one-shot handoff 하나만 예외다.
    destination = tuple(
        str(revision)
        for revision in migration_context.opts.get("destination_rev") or ()
    )
    is_sanctioned = (
        not migration_context.as_sql
        and migration_context.opts.get("purge") is True
        and destination == (_BASELINE_300_REVISION,)
        and context.get_tag_argument() == _BASELINE_300_HANDOFF_TAG
    )
    if not is_sanctioned:
        raise RuntimeError(
            "generic Alembic stamp is unsupported; use the controlled "
            "application-schema 0236-to-300 handoff"
        )

    connection = migration_context.connection
    if connection is None:
        raise RuntimeError("0236-to-300 handoff requires an online DB connection")
    if _raw_alembic_heads(connection) != (_BASELINE_300_HANDOFF_SOURCE,):
        raise RuntimeError(
            "0236-to-300 handoff requires exactly one raw source head "
            "0236_tvn41s_compaction_drained"
        )

    # handoff는 baseline root로 **stamp**한다. graph의 head가 아니라 그 목적지가
    # graph에 있는지를 본다 — head로 결박하면 child migration을 하나 더하는 순간 이
    # 다리가 막힌다. `docker/transition-application-schema-0236-to-300.py`도 같은
    # 이유로 이미 고쳤는데 여기가 남아 있었다.
    script = ScriptDirectory.from_config(config)
    try:
        script.get_revision(_BASELINE_300_REVISION)
    except Exception as exc:
        raise RuntimeError(
            "0236-to-300 handoff requires the active graph to contain "
            f"{_BASELINE_300_REVISION}"
        ) from exc
    _require_application_handoff_capability()

    def stamp_baseline_300_after_purge(
        current_heads: tuple[str, ...],
        _migration_context: object,
    ) -> tuple[StampStep, ...]:
        # Alembic has already run `_ensure_version_table(purge=True)` here. Do
        # not route the retired source revision through ScriptDirectory again.
        if current_heads:
            raise RuntimeError("0236-to-300 handoff expected purge to leave no heads")
        return (
            StampStep(
                (),
                _BASELINE_300_REVISION,
                True,
                True,
                script.revision_map,
            ),
        )

    migration_context._migrations_fn = stamp_baseline_300_after_purge  # noqa: SLF001
    return True


# ``alembic check`` 정합 필터 (ADR-075 D-12-2, T-VN-19).
# ``include_schemas=True`` + ``compare_type`` 은 app schema 밖 객체와 아직 ORM
# 모델이 없는 app table까지 비교해 clean DB check 를 실패시킨다. 아래 3개 명시
# 목록만 비교에서 제외한다(blanket ignore 아님 — 이름을 전부 나열).
#
# 1) PostGIS/extension 소유 객체: ``spatial_ref_sys`` 는 x_extension 확장이
#    소유하며 app 스키마가 관리하지 않는다(search_path 때문에 schema=None 으로도
#    반사돼 이름으로 건다). shared DB의 infra owner가 설치한 ``postgis_topology``는
#    extension namespace와 무관하게 전용 ``topology`` schema에 객체를 만든다.
#    ``alembic_version`` 은 alembic 이 자동 제외한다.
_POSTGIS_TABLE_NAMES = frozenset({"spatial_ref_sys"})
_POSTGIS_OWNED_TABLES = frozenset(
    {
        ("topology", "layer"),
        ("topology", "topology"),
    }
)

_MAPPED_POSTGIS_OWNED_TABLES = sorted(
    f"{table.schema}.{table.name}"
    for table in target_metadata.tables.values()
    if (table.schema, table.name) in _POSTGIS_OWNED_TABLES
)
if _MAPPED_POSTGIS_OWNED_TABLES:
    raise RuntimeError(
        "application metadata maps PostGIS-owned tables: "
        + ", ".join(_MAPPED_POSTGIS_OWNED_TABLES)
    )

# 2) ORM 모델이 아직 없는 app-owned table (raw-SQL migration 으로만 생성).
#    weather/price 는 T-VN-17/38 이, ops-live/log/key 계열은 별도 wave 가 모델을
#    도입할 때 공용 ledger에서 제거한다. 그때까지 명시 제외한다.

# 모델을 추가한 뒤 위 제외 목록을 지우지 않으면 새 metadata drift를 영구히
# 숨길 수 있다. Alembic이 시작될 때 즉시 실패시켜 exclusion의 수명을 제한한다.
_STALE_UNMAPPED_APP_TABLES = _UNMAPPED_APP_TABLES.intersection(
    (table.schema, table.name) for table in target_metadata.tables.values()
)
if _STALE_UNMAPPED_APP_TABLES:
    stale_names = ", ".join(
        f"{schema}.{table}" for schema, table in sorted(_STALE_UNMAPPED_APP_TABLES)
    )
    msg = (
        "alembic unmapped-table exclusions now have SQLAlchemy mappings; "
        f"remove the stale exclusions: {stale_names}"
    )
    raise RuntimeError(msg)

# 3) alembic autogenerate 가 round-trip 하지 못하는 partial/expression index.
#    WHERE 절·JSONB expression 의 reflected 표현을 metadata 표현과 byte-identical 로
#    맞추지 못한다. 이름으로 제외하되, 삭제·정의 변경 미탐지 공백은
#    ``test_alembic_uncompared_indexes_keep_exact_semantics``가 UNIQUE 여부·키 순서·
#    predicate까지 PostgreSQL catalog로 고정해 메운다.


def _object_schema(object_: object) -> str | None:
    schema = getattr(object_, "schema", None)
    if isinstance(schema, str):
        return schema
    table = getattr(object_, "table", None)
    table_schema = getattr(table, "schema", None)
    return table_schema if isinstance(table_schema, str) else None


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001 — alembic callback signature.
    compare_to: object | None,
) -> bool:
    """비-app 객체와 미모델 app table/expression index 를 비교에서 제외한다."""

    schema = _object_schema(object_) or _object_schema(compare_to)
    if type_ == "table":
        return (
            name not in _POSTGIS_TABLE_NAMES
            and not (reflected and (schema, name) in _POSTGIS_OWNED_TABLES)
            and (schema, name) not in _UNMAPPED_APP_TABLES
        )
    if type_ == "index":
        return (schema, name) not in _UNCOMPARED_INDEXES
    return True


def run_migrations_offline() -> None:
    """offline mode — SQL 출력만 (실 DB connect 안 함)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    _guard_application_schema_operation()
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # ⚠️ configure() 호출 시점에 connection이 트랜잭션 밖이어야 한다.
    # Alembic 1.18은 configure() 시 connection.in_transaction()을 보고
    # ``_in_external_transaction`` 을 판정하는데, True면 begin_transaction()이
    # nullcontext로 단락되어 **commit을 하지 않는다** (migration.py L156-161,
    # L416-417). 즉 search_path SET 등 어떤 execute()도 configure() 이전에
    # 하면 SQLAlchemy 2.0 autobegin으로 트랜잭션이 열려 → migration이 적용은
    # 되지만 connection close 시 rollback → 빈 DB. (Alembic ≤1.17에선 무증상.)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # 비교 시 server_default / type / nullable / ... 변경 모두 감지.
        compare_type=True,
        compare_server_default=True,
        # 비-app·미모델 객체 제외 (ADR-075 D-12-2, T-VN-19 alembic check gate).
        include_object=_include_object,
    )
    with context.begin_transaction():
        use_schema_owner_role = os.environ.get(_USE_SCHEMA_OWNER_ROLE_ENV, "false")
        if use_schema_owner_role not in {"true", "false"}:
            raise RuntimeError(
                f"{_USE_SCHEMA_OWNER_ROLE_ENV} must be exactly true or false"
            )
        if use_schema_owner_role == "true":
            # Bootstrap가 `ktm_feature_migrator`에게 이 NOLOGIN group으로의 SET
            # 권한만 부여한다. Alembic의 concurrent-index autocommit block은
            # transaction-local role을 reset하므로 dedicated migration connection
            # 수명 동안의 session role을 쓴다. connection close 시 reset되며 runtime은
            # 이 group membership을 절대 얻지 않는다.
            connection.execute(text("SET ROLE ktm_feature_schema_owner"))
        # version table purge 전 raw `0236`을 엄격히 검증하고, 일반
        # stamp/downgrade를 차단한다. sanctioned handoff이면 이 call이 retire된
        # revision을 ScriptDirectory에 다시 해석하지 않는 callback도 설치한다.
        sanctioned_handoff = _guard_application_schema_operation()
        # ADR-008 — search_path를 Alembic이 소유한 트랜잭션 **안에서** 설정.
        # 0002의 ``coord_5179`` STORED 생성 컬럼이 ``x_extension`` 의 PostGIS
        # ``ST_Transform`` 을 참조하므로 DDL 실행 전 search_path 필요.
        connection.execute(text("SET search_path = public, x_extension"))
        raw_heads_before = _raw_alembic_heads(connection)
        context.run_migrations()
        raw_heads_after = _raw_alembic_heads(connection)
        if raw_heads_before == ():
            # fresh 설치의 destination facet 봉인. **조건을 좁히지 마라** —
            # 종전에는 `raw_heads_after == (_BASELINE_300_REVISION,)`을 함께 요구했는데,
            # active graph에 child migration이 하나라도 생기면 그 조건이 영구히 False가
            # 되어 이 검증이 **예외도 로그도 없이 사라진다.** 그 상태에서 배포
            # executable 경로를 타지 않는 모든 설치(통합 fixture, local-dev
            # `alembic upgrade head`, oracle 생성 스크립트의 raw upgrade)가 facet 검증
            # 없이 통과한다.
            #
            # facet 계약(`application-destination-alembic-version.sql`)은 아직
            # `ARRAY['300']`으로 baseline root를 못 박고 있으므로, baseline root가 아닌
            # 곳에 도달한 fresh 설치는 **지원하지 않는다고 시끄럽게 말한다.** 조용히
            # 건너뛰는 것과 명시적으로 거절하는 것 사이에서 후자를 고른다.
            if raw_heads_after != (_BASELINE_300_REVISION,):
                raise RuntimeError(
                    "fresh install landed on "
                    f"{raw_heads_after!r} instead of the baseline root "
                    f"{_BASELINE_300_REVISION!r}; the destination facet contract still "
                    "pins the baseline root, so this path is unsupported until the "
                    "contract checkpoint moves"
                )
            _verify_fresh_300_destination_facet(connection)
        if sanctioned_handoff and raw_heads_after != (_BASELINE_300_REVISION,):
            raise RuntimeError(
                "0236-to-300 handoff did not leave exactly one raw 300 head"
            )


async def run_async_migrations() -> None:
    """async mode — `AsyncEngine`으로 마이그레이션 실행.

    ``config.get_section``은 alembic.ini 원본 section을 반환하므로 위에서
    ``set_main_option``으로 갱신한 sqlalchemy.url이 빠질 수 있다. 명시적으로
    section dict에 박아 보장.
    """
    section = dict(config.get_section(config.config_ini_section, {}) or {})
    section["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """online mode — 실 DB connect (async)."""
    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        if not isinstance(existing_connection, Connection):
            raise RuntimeError("Alembic external connection must be a SQLAlchemy Connection")
        # controlled `0236 → 300` handoff는 caller가 연 outer transaction과 같은
        # connection을 쓴다. 이를 새 AsyncEngine으로 바꾸면 pre/post catalog
        # preflight와 stamp가 분리되어 postflight 실패 때 raw source row를 보존할 수 없다.
        do_run_migrations(existing_connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
