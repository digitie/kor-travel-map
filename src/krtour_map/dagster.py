from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEFAULT_DAGSTER_DOWNLOAD_DIR = "/tmp/tripmate-dagster/downloads"
DEFAULT_DAGSTER_LOG_DIR = "/opt/tripmate/.tmp/dagster-logs"

JsonValue: TypeAlias = Any
EtlLoader: TypeAlias = Callable[[Any, "DagsterEtlRun"], object]
EtlIdentityResolver: TypeAlias = Callable[[Any, str, "DagsterEtlExecution"], "EtlRunIdentity"]
ScheduleEnabled: TypeAlias = Callable[[], bool]


class EtlSkip(Exception):
    """Skip an ETL run without treating provider/data absence as a failure."""


@dataclass(frozen=True)
class DagsterEtlExecution:
    logical_datetime: datetime
    run_type: str
    op_config: Mapping[str, object]

    @property
    def logical_datetime_kst(self) -> datetime:
        return self.logical_datetime.astimezone(KST)


@dataclass(frozen=True)
class DagsterEtlRun:
    dataset_key: str
    run_key: str
    run_type: str
    trigger_date: date
    logical_datetime: datetime
    op_config: Mapping[str, object]

    @property
    def collected_at(self) -> datetime:
        return self.logical_datetime.astimezone(KST)


@dataclass(frozen=True)
class EtlRunIdentity:
    run_key: str
    run_type: str
    trigger_date: date
    should_skip: bool = False
    skip_message: str | None = None
    skip_extra: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class EtlJobSpec:
    job_name: str
    op_name: str
    dataset_key: str
    description: str
    tags: tuple[str, ...]
    loader: EtlLoader
    success_message: str
    failure_message: str
    identity_resolver: EtlIdentityResolver | None = None
    schedule_enabled: ScheduleEnabled | None = None


def parse_logical_datetime(value: object | None) -> datetime:
    if value is None:
        return datetime.now(KST)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time())
    else:
        raise TypeError("logical_datetime must be an ISO datetime/date string.")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def source_year_month_override_from_config(config: Mapping[str, object]) -> str | None:
    value = config.get("source_year_month")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{6}", value):
        raise ValueError("source_year_month config must be a YYYYMM string.")
    month = int(value[4:6])
    if month < 1 or month > 12:
        raise ValueError("source_year_month config month must be between 01 and 12.")
    return value


def execution_from_config(config: Mapping[str, object]) -> DagsterEtlExecution:
    run_type = config.get("run_type", "manual")
    if run_type not in ("manual", "scheduled"):
        raise ValueError("run_type must be 'manual' or 'scheduled'.")
    return DagsterEtlExecution(
        logical_datetime=parse_logical_datetime(config.get("logical_datetime")),
        run_type=str(run_type),
        op_config=config,
    )


def default_identity(
    _session: Any,
    _dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_datetime = execution.logical_datetime_kst
    return EtlRunIdentity(
        run_key=logical_datetime.strftime("%Y%m%dT%H%M%S"),
        run_type=execution.run_type,
        trigger_date=logical_datetime.date(),
    )


def json_ready(value: object) -> dict[str, JsonValue]:
    converted = _json_ready(value)
    if isinstance(converted, dict):
        return converted
    return {"value": converted}


def resolve_download_dir(dataset_slug: str) -> Path:
    root = os.environ.get("TRIPMATE_DAGSTER_DOWNLOAD_DIR") or DEFAULT_DAGSTER_DOWNLOAD_DIR
    return Path(root) / dataset_slug


def resolve_log_dir() -> Path:
    root = os.environ.get("TRIPMATE_DAGSTER_LOG_DIR") or DEFAULT_DAGSTER_LOG_DIR
    return Path(root)


def schedule_is_enabled_by_default() -> bool:
    return True


def schedule_requires_any_env(*names: str) -> ScheduleEnabled:
    def enabled() -> bool:
        return any(bool(os.environ.get(name)) for name in names)

    return enabled


def _json_ready(value: object) -> JsonValue:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_ready(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
