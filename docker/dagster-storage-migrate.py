#!/usr/local/bin/python -I
"""후보 이미지 안에서 Dagster metadata storage를 멱등하게 migrate한다(ADR-102).

배포는 metadata DB를 지우지 않는다. 이 one-shot은 **매 배포마다** 영속 DB 위에서 돌고,
이미 head인 DB에서는 `dagster instance migrate`/`reindex` 외에 아무것도 바꾸지 않는다.
성공의 판정은 이 명령의 stdout이 아니라 exit 0과, 끝난 뒤 Manager가 metadata DB의
`public.alembic_version`을 직접 읽는 관측이다. stdout의 결과 JSON은 로그용이다.

그래서 이 명령은 자기 신원을 증명하지 않는다. 종전의 root-owned permit(DB oid·system
identifier·후보 이미지·dagster.yaml sha 결박)과 DB 안 append-only intent/receipt outbox는
"리셋 도중 죽으면 어디서 재개하는가"와 "이 DB가 이번 회차에 만든 그 DB인가"에 답하던
장치였고, 리셋이 사라지며 그 질문도 사라졌다. Manager는 전환기 동안 permit 디렉터리를
계속 마운트하고 `KOR_TRAVEL_MAP_DAGSTER_STORAGE_PERMIT_IMAGE_ID`·
`KOR_TRAVEL_MAP_DAGSTER_STORAGE_CONFIG_SHA256`을 넣을 수 있다 — 이 파일은 그 셋을 **읽지
않는다**. 있든 없든 낡았든 결과가 같다. DB에 남은 옛 outbox는 lock 안에서 치운다.

남는 방벽은 관측이다. metadata DSN이 application DB(`feature`/`provider_sync`/`ops`
schema 또는 설치된 application graph의 revision)를 가리키면 **쓰기 전에** 거부한다.

이 파일은 의도적으로 ``kortravelmap`` package를 import하지 않는다. migration-only
경로가 Map code location, application settings 또는 application Alembic chain을 읽으면
candidate storage head의 정본이 다시 흐려진다. 여기서 읽는 migration graph는 이미지에
설치된 Dagster package 자체뿐이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import stat
import subprocess
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster._core.storage.sql import ALEMBIC_SCRIPTS_LOCATION
from sqlalchemy import create_engine, text

#: application active graph의 유일한 root. head와 달리 움직이지 않는다.
_BASELINE_ROOT_REVISION: Final = "400"

_DAGSTER_HOME_ENV: Final = "DAGSTER_HOME"
_DAGSTER_PG_URL_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_PG_URL"
_DAGSTER_PROFILE_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_PROFILE"
_DAGSTER_HOME: Final = Path("/opt/dagster/dagster_home")
_DAGSTER_YAML: Final = _DAGSTER_HOME / "dagster.yaml"
#: 이미지가 appuser에게 넘긴 유일한 쓰기 자리(`dagster.Dockerfile`).
_LOCAL_STATE_ROOT: Final = "/opt/dagster/state"
_HEAD_SCHEMA: Final = "kor-travel-map.dagster-storage-head.v1"
_MIGRATE_SCHEMA: Final = "kor-travel-map.dagster-storage-migration.v4"
_ERROR_SCHEMA: Final = "kor-travel-map.dagster-storage-migration-error.v1"
_ISOLATED_PYTHON: Final = "/usr/local/bin/python"
_DAGSTER_EXECUTABLE: Final = "/usr/local/bin/dagster"
#: ADR-102 이전 이미지의 one-shot과 **같은 key**다. 전환기에 옛 이미지와 새 이미지의
#: one-shot이 같은 metadata DB에서 겹쳐 돌아도 직렬화된다.
_OPERATION_LOCK_KEY: Final = "kor-travel-map:dagster-storage-operation"
#: 이 schema 중 하나라도 있으면 그 DB는 application DB다.
_APPLICATION_SCHEMAS: Final = ("feature", "provider_sync", "ops")
#: ADR-102 이전 이미지가 metadata DB에 설치하던 append-only intent/receipt outbox.
#: receipt가 intent를 FK로 가리키므로 둘은 한 DROP 문장에서 함께 지운다.
_LEGACY_OUTBOX_TABLES: Final = (
    "public.ktm_dagster_storage_operation_receipts",
    "public.ktm_dagster_storage_operation_intents",
)
#: 위 두 표의 불변 trigger가 부르던 함수. trigger가 표와 함께 사라진 **뒤에** 지운다.
_LEGACY_OUTBOX_FUNCTION: Final = "public.ktm_reject_dagster_storage_operation_mutation()"


class DagsterStorageMigrationError(RuntimeError):
    """외부 입력을 반사하지 않는 migration-only 계약 오류."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _dagster_storage_head() -> str:
    """실행 중인 이미지가 설치한 Dagster storage graph의 단일 head를 읽는다."""
    try:
        config = Config()
        config.set_main_option("script_location", ALEMBIC_SCRIPTS_LOCATION)
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_head_unavailable") from exc

    if len(heads) != 1:
        raise DagsterStorageMigrationError("dagster_storage_head_ambiguous")
    return heads[0]


def _bounded_tick_retention(value: object) -> bool:
    """tick 보존 설정이 **모든 status에 유한 상한**을 주는지 본다.

    Dagster는 두 모양을 받는다(`_tick_retention_config_schema`) — bare int는 네
    status 전부에, dict는 적힌 status에만 적용된다. 그리고 적지 않은 status의
    기본값은 `-1`(영구 보존)이라, dict를 쓰면서 status 하나를 빼먹으면 그 종류는
    상한이 없는 채로 남는다. 그것이 조용히 통과하면 이 봉인의 뜻이 사라진다.

    그래서 dict 형태는 **네 status가 모두 있어야** 통과한다.
    """
    if type(value) is int:
        return value >= 1
    if not isinstance(value, dict):
        return False
    if set(value) != {"skipped", "success", "started", "failure"}:
        return False
    return all(type(days) is int and days >= 1 for days in value.values())


def _validate_dagster_config(raw: bytes) -> None:
    """Dagster storage target이 canonical DSN env 외에는 읽지 못하게 한다."""
    try:
        config = yaml.safe_load(raw)
        if set(config) != {
            "telemetry",
            "python_logs",
            "storage",
            "concurrency",
            "run_monitoring",
            # 로컬 쓰기 두 축. 선언하지 않으면 Dagster가 기본값인
            # `$DAGSTER_HOME/storage`를 쓰려 하는데 그 트리는 root 소유 봉인이고
            # 컨테이너는 uid 999다 — run이 PermissionError로 죽는다(2026-09-11 실측:
            # 이 prod에서 성공한 run이 하나도 없었다). 아래에서 두 경로가 appuser
            # 소유 state 안에 있는지까지 본다.
            "local_artifact_storage",
            "compute_logs",
            # tick 이력의 상한. 없으면 `job_ticks`가 무한히 늘어난다 — 2026-09-12
            # 실측에서 그것이 이미 metadata DB의 가장 큰 표였다.
            "retention",
        }:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        storage = config["storage"]
        postgres = storage["postgres"]
        local_base_dirs = (
            config["local_artifact_storage"]["config"]["base_dir"],
            config["compute_logs"]["config"]["base_dir"],
        )
        # 최상위 key는 위에서 정확히 대조했으므로 여기서 KeyError는 나지 않는다.
        # **그 아래를 try 안에서 뽑으면 안 된다** — 누락이 `invalid_dagster_yaml`로
        # 접히고, 그러면 "봉인되지 않았다"와 "yaml이 깨졌다"가 구분되지 않는다.
        concurrency = config["concurrency"]
        retention = config["retention"]
    except (KeyError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        raise DagsterStorageMigrationError("invalid_dagster_yaml") from exc
    if storage != {
        "postgres": {
            "postgres_url": {"env": _DAGSTER_PG_URL_ENV},
            "should_autocreate_tables": False,
        }
    } or postgres != {
        "postgres_url": {"env": _DAGSTER_PG_URL_ENV},
        "should_autocreate_tables": False,
    }:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    # 봉인의 뜻은 "로컬로 새지 않는다"이다. 키를 허용하는 것으로 끝내면 그 뜻이
    # 빠져나가므로, 두 경로가 이미지가 appuser에게 넘긴 state 안에 있는지 본다.
    #
    # 접두 비교만으로는 부족하다 — `/opt/dagster/state/../dagster_home/storage`가
    # 통과한다. 그 문자열이 권한을 주지는 않지만(config는 root 0444이고 이미지와 함께
    # 핀된다) 이 검사가 잡으려는 것은 공격이 아니라 **오설정**이고, 오설정은 정확히
    # 그런 모양으로 온다. 그래서 사전적으로 정규화한 뒤 본다.
    for base_dir in local_base_dirs:
        if not isinstance(base_dir, str) or not base_dir.startswith("/"):
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        resolved = posixpath.normpath(base_dir)
        if not resolved.startswith(f"{_LOCAL_STATE_ROOT}/"):
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    # key를 허용하는 것으로 끝내면 그 뜻이 구멍으로 빠져나간다 — 로컬 쓰기 두 축에
    # 적용한 것과 같은 규율이다.
    #
    # 상한이 사라지면 큐는 Dagster 기본값으로 돌아간다. 그 값이 무엇인지는 버전이
    # 정하고 우리는 모른다 — 형제 저장소 weather가 그 상태에서 두 번 멈췄다.
    runs = concurrency.get("runs") if isinstance(concurrency, dict) else None
    if not isinstance(runs, dict) or not set(runs) <= {
        "max_concurrent_runs",
        "tag_concurrency_limits",
    }:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    run_limit = runs.get("max_concurrent_runs")
    if type(run_limit) is not int or run_limit < 1:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    # 한 job class가 큐 전량을 먹지 못하게 하는 상한. 허용만 하고 뜻을 보지 않으면
    # `limit`이 전량과 같아져도(= 아무것도 막지 않아도) 통과한다.
    #
    # `value`를 금지한다. value 있는 항목은 그 key가 **그 값일 때만** 세므로,
    # request id처럼 매번 다른 값에는 상한이 걸리지 않는다(`dagster/_utils/tags.py`).
    for entry in runs.get("tag_concurrency_limits") or ():
        if not isinstance(entry, dict) or set(entry) != {"key", "limit"}:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        if not isinstance(entry["key"], str) or not entry["key"]:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        tag_limit = entry["limit"]
        if type(tag_limit) is not int or not 1 <= tag_limit < run_limit:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    # tick 이력의 상한.
    #
    # `concurrency`와 **같은 강도로** 가드한다. 종전에는 `isinstance` 없이
    # `set(retention)`을 불러, `retention: null` 같은 흔한 오편집이
    # `DagsterStorageMigrationError`가 아니라 맨 `TypeError`로 새어 나갔다 —
    # `main()`이 잡지 않으므로 배포 래퍼가 읽는 JSON 오류 봉투를 잃는다.
    # fail-close는 유지되지만 다음 사람은 "봉인 실패"가 아니라 "스크립트 버그"를 본다.
    if not isinstance(retention, dict) or set(retention) != {"schedule", "sensor"}:
        raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
    for kind in ("schedule", "sensor"):
        section = retention[kind]
        if not isinstance(section, dict) or set(section) != {"purge_after_days"}:
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")
        if not _bounded_tick_retention(section["purge_after_days"]):
            raise DagsterStorageMigrationError("dagster_storage_target_not_sealed")


def _validate_root_owned_directory(metadata: os.stat_result) -> None:
    """appuser가 config를 rename/replace할 수 있는 상위 directory를 거부한다."""
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise DagsterStorageMigrationError("unsafe_dagster_home_parent")


def _safe_dagster_config(environment: Mapping[str, str]) -> str:
    """봉인된 canonical config가 metadata DSN env 하나만 읽는지 확인한다."""
    dagster_home_raw = environment.get(_DAGSTER_HOME_ENV)
    if not dagster_home_raw:
        raise DagsterStorageMigrationError("missing_dagster_home")

    dagster_home = Path(dagster_home_raw)
    if dagster_home != _DAGSTER_HOME:
        raise DagsterStorageMigrationError("invalid_dagster_home")

    for directory in (Path("/opt"), Path("/opt/dagster"), _DAGSTER_HOME):
        try:
            _validate_root_owned_directory(directory.lstat())
        except OSError as exc:
            raise DagsterStorageMigrationError("unsafe_dagster_home_parent") from exc

    dagster_yaml = dagster_home / "dagster.yaml"
    try:
        metadata = dagster_yaml.lstat()
    except OSError as exc:
        raise DagsterStorageMigrationError("missing_dagster_yaml") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o444
        or metadata.st_nlink != 1
        or metadata.st_size > 1024 * 1024
    ):
        raise DagsterStorageMigrationError("invalid_dagster_yaml")
    try:
        descriptor = os.open(dagster_yaml, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            ):
                raise DagsterStorageMigrationError("invalid_dagster_yaml")
            raw = stream.read(1024 * 1024 + 1)
    except OSError as exc:
        raise DagsterStorageMigrationError("invalid_dagster_yaml") from exc
    _validate_dagster_config(raw)
    return hashlib.sha256(raw).hexdigest()


def _require_migration_environment(
    environment: Mapping[str, str],
) -> tuple[str, str, str]:
    """같은 image의 canonical config, profile, metadata DSN을 명시적으로 요구한다."""
    profile = environment.get(_DAGSTER_PROFILE_ENV, "production")
    if profile not in {"production", "local-dev"}:
        raise DagsterStorageMigrationError("invalid_dagster_profile")
    config_sha256 = _safe_dagster_config(environment)

    dagster_pg_url = environment.get(_DAGSTER_PG_URL_ENV)
    if not dagster_pg_url or not dagster_pg_url.strip():
        raise DagsterStorageMigrationError("missing_dagster_pg_url")
    return dagster_pg_url, profile, config_sha256


def _installed_application_revisions() -> set[str]:
    """설치된 Map package의 migration graph가 담은 revision 전부.

    ``public.alembic_version``에는 현재 head 한 행만 있으므로, "이 DB가 application
    DB인가"를 판정하려면 **graph의 모든 revision**을 후보로 봐야 한다. head 하나만
    보면 중간 revision에서 멈춘 DB를 놓친다.

    설치본을 읽지 못하면 baseline root로 좁힌다 — 판정이 넓어져 격리 가드가 느슨해지는
    것보다 좁아져 시끄러운 편이 안전하다.
    """
    paths = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        raw_path = paths.get(key)
        if not raw_path:
            continue
        manifest = Path(raw_path) / "kortravelmap" / "_application_migration_graph.json"
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        revisions = payload.get("revisions")
        if not isinstance(revisions, list) or not revisions:
            continue
        declared = {str(entry["revision"]) for entry in revisions}
        if _BASELINE_ROOT_REVISION in declared:
            return declared
    return {_BASELINE_ROOT_REVISION}


def _has_version_table(connection: Any) -> bool:
    return bool(
        connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar_one()
    )


def _require_metadata_database(connection: Any) -> None:
    """metadata DSN이 application DB를 가리키면 **쓰기 전에** 거부한다.

    DB identity를 외부 증명과 대조하던 방벽은 없다(ADR-102). 남는 것은 DB가 스스로
    드러내는 사실이다 — application schema가 있거나, ``public.alembic_version``에
    application graph의 revision이 있으면 이 DB는 metadata DB가 아니다.

    revision 판정은 head 하나가 아니라 **설치본 graph 전부**로 한다. 종전에 raw
    revision 하나(`'300'`)만 보던 arm은 application graph에 child migration이 붙는 순간
    예외도 로그도 없이 False가 됐다. `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD` env로
    넓히려던 시도도 있었지만 그 변수는 API 서비스에만 주입돼 dagster 서비스에서는
    아무것도 고치지 않았다. 그래서 설치본의 graph 데이터 파일을 직접 읽는다 — 이 파일은
    ``kortravelmap``을 **import**하지 않을 뿐, 설치본의 데이터 파일은 읽는다
    (`docker/application-schema-head.py`도 같은 파일을 같은 방식으로 읽는다).
    """
    try:
        application_schema_count = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_namespace "
                    "WHERE nspname = ANY(CAST(:schemas AS text[]))"
                ),
                {"schemas": list(_APPLICATION_SCHEMAS)},
            ).scalar_one()
        )
        has_application_revision = False
        if _has_version_table(connection):
            has_application_revision = bool(
                connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM public.alembic_version "
                        "WHERE version_num::text = ANY(CAST(:revisions AS text[]))"
                        ")"
                    ),
                    {"revisions": sorted(_installed_application_revisions())},
                ).scalar_one()
            )
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_database_unavailable") from exc
    if application_schema_count or has_application_revision:
        raise DagsterStorageMigrationError("dagster_storage_targets_application_schema")


def _drop_legacy_operation_outbox(connection: Any) -> None:
    """ADR-102 이전 이미지가 남긴 intent/receipt outbox를 치운다. 없으면 무연산이다.

    불변 trigger는 UPDATE·DELETE·TRUNCATE만 막고 DROP은 막지 않는다. receipt가 intent를
    FK로 가리키므로 두 표는 **한 문장**에서 함께 지우고(trigger·FK는 표와 함께 사라진다),
    trigger가 의존하던 함수는 그 **뒤에** 지운다. 순서를 바꾸면 함수 DROP이 trigger
    의존으로 실패한다.
    """
    try:
        connection.execute(text(f"DROP TABLE IF EXISTS {', '.join(_LEGACY_OUTBOX_TABLES)}"))
        connection.execute(text(f"DROP FUNCTION IF EXISTS {_LEGACY_OUTBOX_FUNCTION}"))
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_legacy_outbox_drop_failed") from exc


def _run_dagster_instance_migrate(environment: Mapping[str, str]) -> None:
    """Dagster의 schema/data migration과 필수 reindex를 민감 출력 없이 실행한다."""
    for operation in ("migrate", "reindex"):
        try:
            completed = subprocess.run(
                [
                    _ISOLATED_PYTHON,
                    "-I",
                    _DAGSTER_EXECUTABLE,
                    "instance",
                    operation,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=dict(environment),
            )
        except OSError as exc:
            raise DagsterStorageMigrationError(
                "dagster_instance_migrate_unavailable"
            ) from exc
        if completed.returncode != 0:
            # Dagster의 info 출력이나 DB driver 예외에는 DSN이 포함될 수 있다. 이 명령은
            # container log로도 원문을 넘기지 않고, 호출자가 stable error code만 받게 한다.
            raise DagsterStorageMigrationError("dagster_instance_migrate_failed")


def _acquire_session_operation_lock(connection: Any) -> None:
    connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_lock("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    )
    # session lock은 transaction 밖에서도 external Dagster subprocess가 끝날 때까지
    # 유지한다. autobegin transaction만 여기서 닫는다.
    connection.commit()


def _release_session_operation_lock(connection: Any) -> None:
    unlocked = connection.execute(
        text(
            "SELECT pg_catalog.pg_advisory_unlock("
            "(SELECT oid::integer FROM pg_catalog.pg_database "
            "WHERE datname = current_database()), pg_catalog.hashtext(:lock_key))"
        ),
        {"lock_key": _OPERATION_LOCK_KEY},
    ).scalar_one()
    connection.commit()
    if unlocked is not True:
        raise DagsterStorageMigrationError("dagster_operation_lock_release_failed")


def _dagster_metadata_contract() -> tuple[
    tuple[Any, ...],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    tuple[str, ...],
]:
    """설치된 Dagster package가 fresh storage에 만드는 table/column/index를 읽는다."""

    try:
        from dagster._core.storage.event_log.migration import (
            ASSET_DATA_MIGRATIONS,
            EVENT_LOG_DATA_MIGRATIONS,
        )
        from dagster._core.storage.event_log.schema import SqlEventLogStorageMetadata
        from dagster._core.storage.runs.migration import REQUIRED_DATA_MIGRATIONS
        from dagster._core.storage.runs.schema import RunStorageSqlMetadata
        from dagster._core.storage.schedules.migration import (
            REQUIRED_SCHEDULE_DATA_MIGRATIONS,
        )
        from dagster._core.storage.schedules.schema import ScheduleStorageSqlMetadata
        from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_contract_unavailable") from exc

    metadatas = (
        RunStorageSqlMetadata,
        SqlEventLogStorageMetadata,
        ScheduleStorageSqlMetadata,
    )
    columns: dict[str, tuple[str, ...]] = {}
    indexes: dict[str, tuple[str, ...]] = {}
    for metadata in metadatas:
        for table in metadata.sorted_tables:
            table_columns = tuple(str(column.name) for column in table.columns)
            table_indexes = {str(index.name) for index in table.indexes if index.name}
            for constraint in table.constraints:
                # `.columns`는 `ColumnCollectionConstraint` 계열에만 있다. 좁히기
                # **전에** 읽으면 base `Constraint`에 없는 속성을 만진다 — 지금은
                # CHECK 제약이 없어 터지지 않을 뿐이고, 하나 추가되는 순간 런타임
                # AttributeError다. 아래 두 분기가 실제로 쓰는 것만 좁혀서 읽는다.
                if not isinstance(constraint, PrimaryKeyConstraint | UniqueConstraint):
                    continue
                constraint_columns = tuple(str(column.name) for column in constraint.columns)
                if isinstance(constraint, PrimaryKeyConstraint) and constraint_columns:
                    table_indexes.add(
                        str(constraint.name or f"{table.name}_pkey")
                    )
                elif isinstance(constraint, UniqueConstraint) and constraint_columns:
                    table_indexes.add(
                        str(
                            constraint.name
                            or f"{table.name}_{'_'.join(constraint_columns)}_key"
                        )
                    )
            table_index_names = tuple(sorted(table_indexes))
            if table.name in columns and (
                columns[table.name] != table_columns
                or indexes[table.name] != table_index_names
            ):
                raise DagsterStorageMigrationError("dagster_catalog_contract_ambiguous")
            columns[table.name] = table_columns
            indexes[table.name] = table_index_names

    required_migrations = tuple(
        sorted(
            {
                *REQUIRED_DATA_MIGRATIONS,
                *REQUIRED_SCHEDULE_DATA_MIGRATIONS,
                *EVENT_LOG_DATA_MIGRATIONS,
                *ASSET_DATA_MIGRATIONS,
            }
        )
    )
    return metadatas, columns, indexes, required_migrations


def _bootstrap_fresh_dagster_catalog(connection: Any) -> None:
    """version table이 없는 DB에 catalog 전체와 head stamp를 한 transaction으로 만든다."""

    metadatas, _, _, _ = _dagster_metadata_contract()
    try:
        for metadata in metadatas:
            metadata.create_all(connection, checkfirst=True)
        from dagster._core.storage.sql import stamp_alembic_rev
        from dagster_postgres.run_storage import run_storage
        from dagster_postgres.utils import pg_alembic_config

        stamp_alembic_rev(pg_alembic_config(run_storage.__file__), connection)
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_bootstrap_failed") from exc


def _verify_dagster_catalog(connection: Any, *, head: str) -> None:
    """설치된 Dagster가 기대하는 구조가 **전부 있는지** 본다 — 부분집합 검사다.

    ADR-102 이전에는 exact catalog를 대조하고 그 digest를 결과에 남겼다. DB가 배포를
    넘어 살아남는 지금은 여분의 표·column·index(이전 Dagster 버전의 잔재, 손으로 만든
    객체)가 있을 수 있고 그것은 Dagster 동작을 막지 않는다. 그래서 여분은 허용하고,
    기대하는 table·column·valid index와 필수 data migration marker가 모두 있는지,
    ``public.alembic_version``이 정확히 이 이미지의 head 한 행인지를 본다.
    """

    _, expected_columns, expected_indexes, required_migrations = (
        _dagster_metadata_contract()
    )
    try:
        column_rows = connection.execute(
            text(
                "SELECT relation.relname, attribute.attname "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "JOIN pg_catalog.pg_attribute AS attribute "
                "ON attribute.attrelid = relation.oid "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p') "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped"
            )
        ).all()
        index_rows = connection.execute(
            text(
                "SELECT source.relname, target.relname "
                "FROM pg_catalog.pg_index AS index_row "
                "JOIN pg_catalog.pg_class AS source ON source.oid = index_row.indrelid "
                "JOIN pg_catalog.pg_class AS target ON target.oid = index_row.indexrelid "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = source.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND index_row.indisvalid AND index_row.indisready "
                "AND index_row.indislive"
            )
        ).all()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_unavailable") from exc
    actual_columns: dict[str, set[str]] = {}
    for table_name, column_name in column_rows:
        actual_columns.setdefault(str(table_name), set()).add(str(column_name))
    actual_indexes: dict[str, set[str]] = {}
    for table_name, index_name in index_rows:
        actual_indexes.setdefault(str(table_name), set()).add(str(index_name))
    if (
        "alembic_version" not in actual_columns
        or any(
            not set(columns) <= actual_columns.get(table_name, set())
            for table_name, columns in expected_columns.items()
        )
        or any(
            not set(indexes) <= actual_indexes.get(table_name, set())
            for table_name, indexes in expected_indexes.items()
        )
    ):
        raise DagsterStorageMigrationError("dagster_catalog_postcondition_mismatch")
    try:
        version_rows = tuple(
            str(row[0])
            for row in connection.execute(
                text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            ).all()
        )
        completed_markers = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT name FROM public.secondary_indexes "
                    "WHERE migration_completed IS NOT NULL"
                )
            ).all()
        }
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_unavailable") from exc
    if version_rows != (head,) or not set(required_migrations) <= completed_markers:
        raise DagsterStorageMigrationError("dagster_catalog_postcondition_mismatch")


def _prepare_storage(connection: Any) -> None:
    """lock 안에서, 한 transaction으로: 관측 가드 → 옛 outbox 제거 → 필요하면 bootstrap."""
    try:
        with connection.begin():
            _require_metadata_database(connection)
            _drop_legacy_operation_outbox(connection)
            if not _has_version_table(connection):
                _bootstrap_fresh_dagster_catalog(connection)
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_prepare_failed") from exc


def _verify_storage(connection: Any, *, head: str) -> None:
    try:
        with connection.begin():
            _verify_dagster_catalog(connection, head=head)
    except DagsterStorageMigrationError:
        raise
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_catalog_unavailable") from exc


def _migrate(environment: Mapping[str, str]) -> dict[str, str]:
    """metadata DB를 이 이미지의 Dagster head로 올린다. 이미 head면 무연산이다.

    DB를 지우지 않는 배포(ADR-102)에서 매번 돌므로 모든 단계가 멱등이다 — version
    table이 없을 때만 bootstrap하고, Dagster의 `instance migrate`/`reindex`는 끝난
    migration을 다시 하지 않으며, 옛 outbox DROP은 `IF EXISTS`다.
    """
    head = _dagster_storage_head()
    dagster_pg_url, _profile, _config_sha256 = _require_migration_environment(environment)
    engine: Any = None
    connection: Any = None
    locked = False
    try:
        try:
            # URL 파싱 오류도 DSN 원문을 담는다 — 연결 전 단계부터 코드로만 낸다.
            engine = create_engine(dagster_pg_url)
            connection = engine.connect()
            _acquire_session_operation_lock(connection)
        except Exception as exc:
            raise DagsterStorageMigrationError(
                "dagster_storage_database_unavailable"
            ) from exc
        locked = True
        _prepare_storage(connection)
        _run_dagster_instance_migrate(environment)
        _verify_storage(connection, head=head)
    finally:
        active_exception = sys.exc_info()[0] is not None
        release_failure: Exception | None = None
        if connection is not None:
            if locked:
                try:
                    _release_session_operation_lock(connection)
                except Exception as exc:
                    release_failure = exc
            connection.close()
        if engine is not None:
            engine.dispose()
        if release_failure is not None and not active_exception:
            if isinstance(release_failure, DagsterStorageMigrationError):
                raise release_failure
            raise DagsterStorageMigrationError(
                "dagster_operation_lock_release_failed"
            ) from release_failure
    return {"schema": _MIGRATE_SCHEMA, "status": "migrated", "head": head}


def _emit(payload: Mapping[str, str], *, stream: TextIO = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    """`head` 또는 `migrate`를 실행하고 안정된 JSON 결과를 출력한다."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["head"]:
            _emit({"schema": _HEAD_SCHEMA, "head": _dagster_storage_head()})
            return 0
        if arguments == ["migrate"]:
            _emit(_migrate(os.environ))
            return 0
        raise DagsterStorageMigrationError("invalid_arguments")
    except DagsterStorageMigrationError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
