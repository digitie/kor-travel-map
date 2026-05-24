from __future__ import annotations

import json
import os
import sys
import traceback
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from kraddr.base import mapbox_maki_icon_or_none
from krtour_map.dagster import DagsterEtlRun, parse_logical_datetime
from krtour_map.db import (
    area_detail_from_row,
    data_integrity_violations,
    dedup_review_queue,
    event_detail_from_row,
    feature_area_details,
    feature_event_details,
    feature_files,
    feature_from_row,
    feature_notice_details,
    feature_opening_periods,
    feature_overrides,
    feature_place_details,
    feature_route_details,
    feature_special_days,
    feature_weather_values,
    features,
    initialize_feature_db,
    load_feature_rows,
    metadata,
    notice_detail_from_row,
    place_detail_from_row,
    price_points,
    price_values,
    route_detail_from_row,
    source_links,
    source_records,
)
from krtour_map.enums import FeatureKind, FeatureStatus
from krtour_map.fixtures import load_fixture, save_fixture
from krtour_map.models import Address, Feature, FeaturePatch
from krtour_map.notices import (
    NoticeLoadResources,
    collect_notice_dataset_features,
    load_notice_features,
    load_notice_result,
    notice_dataset_specs,
    notice_job_specs,
)
from krtour_map.rustfs import (
    RustfsS3Client,
    load_rustfs_settings,
    redacted_rustfs_settings,
    rustfs_config_path,
    rustfs_settings_from_mapping,
    save_rustfs_settings,
)
from krtour_map.standard_data import (
    StandardDataClient,
    StandardDataLoadResources,
    async_collect_standard_data_features,
    collect_standard_data_features,
    load_standard_data_features,
    load_standard_data_result,
    standard_data_full_scan_job_specs,
    standard_dataset_specs,
)
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./artifacts/debug-ui.sqlite3"
DEFAULT_FIXTURE_DIR = "tests/fixtures"


def handle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Handle one local debug UI command.

    The Next.js debug UI talks to this module through a Python subprocess so it
    can keep using the library's SQLAlchemy schema, Pydantic DTOs, and fixture
    helpers directly. This module is intentionally local-dev only.
    """

    action = str(payload.get("action") or "")
    if action == "defaults":
        return {
            "ok": True,
            "database_url": _database_url(payload),
            "fixture_dir": _fixture_dir(payload),
            "tables": sorted(metadata.tables),
            "feature_kinds": [str(item.value) for item in FeatureKind],
            "feature_statuses": [str(item.value) for item in FeatureStatus],
            "etl_datasets": _etl_catalog(),
            "dagster_jobs": _dagster_jobs(),
            "rustfs": _rustfs_config(payload),
        }
    if action == "sample_feature":
        return {"ok": True, "feature": _sample_feature()}
    if action == "etl_catalog":
        return {"ok": True, "datasets": _etl_catalog()}
    if action == "dagster_jobs":
        return {"ok": True, "jobs": _dagster_jobs()}
    if action == "rustfs_config":
        return {"ok": True, **_rustfs_config(payload)}
    if action == "save_rustfs_config":
        return {"ok": True, **_save_rustfs_config(payload)}
    if action == "rustfs_files":
        return {"ok": True, **_rustfs_files(payload)}
    if action == "preview_standard_data":
        return {"ok": True, **_preview_standard_data(payload)}
    if action == "fetch_standard_data":
        return {"ok": True, **_fetch_standard_data(payload)}
    if action == "preview_notice_data":
        return {"ok": True, **_preview_notice_data(payload)}

    database_url = _database_url(payload)
    _ensure_sqlite_parent(database_url)
    context = initialize_feature_db(database_url)
    try:
        if action == "schema":
            if bool(payload.get("create_schema")):
                context.create_schema()
            return {"ok": True, "database_url": database_url, "schema": _schema_summary(context)}
        if action == "list_features":
            return {"ok": True, **_list_features(context, payload)}
        if action == "get_feature":
            return {"ok": True, "feature": _get_feature(context, _required(payload, "feature_id"))}
        if action == "upsert_feature":
            return {"ok": True, "feature": _upsert_feature(context, payload)}
        if action == "patch_feature":
            return {"ok": True, "feature": _patch_feature(context, payload)}
        if action == "delete_feature":
            _delete_feature(context, payload)
            return {"ok": True}
        if action == "list_table":
            return {"ok": True, **_list_table(context, payload)}
        if action == "list_fixtures":
            return {"ok": True, "fixtures": _list_fixtures(payload)}
        if action == "load_fixture":
            return {"ok": True, "fixture": load_fixture(_required(payload, "path"))}
        if action == "save_fixture":
            return {"ok": True, "path": str(_save_fixture(payload))}
        if action == "load_standard_data":
            return {"ok": True, **_load_standard_data(context, payload)}
        if action == "load_notice_data":
            return {"ok": True, **_load_notice_data(context, payload)}
        if action == "run_dagster_etl":
            return {"ok": True, **_run_dagster_etl(context, payload)}
        return {"ok": False, "error": f"Unknown action: {action}"}
    finally:
        context.dispose()


def _database_url(payload: Mapping[str, Any]) -> str:
    value = (
        payload.get("database_url")
        or payload.get("databaseUrl")
        or os.getenv("KRTOUR_MAP_DEBUG_DATABASE_URL")
        or os.getenv("KRTOUR_MAP_DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    return str(value)


def _fixture_dir(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("fixture_dir")
        or payload.get("fixtureDir")
        or os.getenv("KRTOUR_MAP_DEBUG_FIXTURE_DIR")
        or DEFAULT_FIXTURE_DIR
    )


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite") or ":memory:" in database_url:
        return
    marker = ":///"
    if marker not in database_url:
        return
    path_text = database_url.split(marker, 1)[1]
    if path_text.startswith(("/", "\\")):
        path = Path(path_text)
    else:
        path = Path(path_text)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def _required(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{key} is required")
    return str(value)


def _schema_summary(context: Any) -> dict[str, Any]:
    tables = []
    with context.session_factory() as session:
        for table_name in sorted(metadata.tables):
            table = metadata.tables[table_name]
            count: int | None
            try:
                count = int(session.scalar(select(func.count()).select_from(table)) or 0)
            except SQLAlchemyError:
                count = None
            tables.append(
                {
                    "name": table_name,
                    "row_count": count,
                    "columns": [
                        {
                            "name": column.name,
                            "type": str(column.type),
                            "nullable": bool(column.nullable),
                            "primary_key": bool(column.primary_key),
                        }
                        for column in table.columns
                    ],
                }
            )
    return {"tables": tables}


def _list_features(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    limit = _bounded_int(payload.get("limit"), default=50, minimum=1, maximum=1000)
    offset = _bounded_int(payload.get("offset"), default=0, minimum=0, maximum=100_000)
    query = str(payload.get("q") or "").strip()
    filters = payload.get("filters") if isinstance(payload.get("filters"), Mapping) else {}

    stmt = select(features)
    count_stmt: Select[Any] = select(func.count()).select_from(features)
    conditions = []
    if query:
        like = f"%{query}%"
        conditions.append(
            or_(
                features.c.feature_id.ilike(like),
                features.c.name.ilike(like),
                features.c.category.ilike(like),
                features.c.legal_dong_code.ilike(like),
                features.c.sido_code.ilike(like),
                features.c.sigungu_code.ilike(like),
            )
        )
    for column_name in (
        "kind",
        "status",
        "category",
        "legal_dong_code",
        "sido_code",
        "sigungu_code",
    ):
        value = str(filters.get(column_name) or "").strip()
        if value:
            conditions.append(getattr(features.c, column_name) == value)
    if bool(filters.get("only_with_coord")):
        conditions.append(features.c.longitude.is_not(None))
        conditions.append(features.c.latitude.is_not(None))
    bounds = _bounds_filter(payload.get("bounds") or filters.get("bounds"))
    if bounds is not None:
        south, west, north, east = bounds
        conditions.extend(
            (
                features.c.latitude >= south,
                features.c.latitude <= north,
                features.c.longitude >= west,
                features.c.longitude <= east,
            )
        )
    notice_type = str(filters.get("notice_type") or "").strip()
    if notice_type:
        stmt = stmt.join(
            feature_notice_details,
            feature_notice_details.c.feature_id == features.c.feature_id,
        )
        count_stmt = count_stmt.join(
            feature_notice_details,
            feature_notice_details.c.feature_id == features.c.feature_id,
        )
        conditions.append(feature_notice_details.c.notice_type == notice_type)
    route_type = str(filters.get("route_type") or "").strip()
    if route_type:
        stmt = stmt.join(
            feature_route_details,
            feature_route_details.c.feature_id == features.c.feature_id,
        )
        count_stmt = count_stmt.join(
            feature_route_details,
            feature_route_details.c.feature_id == features.c.feature_id,
        )
        conditions.append(feature_route_details.c.route_type == route_type)
    provider = str(filters.get("provider") or "").strip()
    if provider:
        stmt = stmt.join(source_links, source_links.c.feature_id == features.c.feature_id).join(
            source_records,
            source_records.c.source_record_key == source_links.c.source_record_key,
        )
        count_stmt = count_stmt.join(
            source_links,
            source_links.c.feature_id == features.c.feature_id,
        ).join(
            source_records,
            source_records.c.source_record_key == source_links.c.source_record_key,
        )
        conditions.append(source_records.c.provider == provider)

    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    stmt = (
        stmt.order_by(features.c.updated_at.desc(), features.c.feature_id)
        .limit(limit)
        .offset(offset)
    )

    with context.session_factory() as session:
        rows = session.execute(stmt).mappings().all()
        total = int(session.scalar(count_stmt) or 0)
        feature_ids = [str(row["feature_id"]) for row in rows]
        notices = _detail_rows_by_feature_id(session, feature_notice_details, feature_ids)
        routes = _detail_rows_by_feature_id(session, feature_route_details, feature_ids)

    items = [
        _feature_list_item(row, notices.get(row["feature_id"]), routes.get(row["feature_id"]))
        for row in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _feature_list_item(
    row: Mapping[str, Any],
    notice_detail: Mapping[str, Any] | None = None,
    route_detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    feature = feature_from_row(row)
    category_icon = mapbox_maki_icon_or_none(feature.category)
    return {
        "feature_id": feature.feature_id,
        "kind": str(feature.kind),
        "name": feature.name,
        "category": feature.category,
        "category_label": feature.category_label,
        "category_maki_icon": category_icon,
        "status": str(feature.status),
        "coord": _jsonable(feature.coord),
        "legal_dong_code": feature.address.legal_dong_code,
        "sido_code": row.get("sido_code"),
        "sigungu_code": row.get("sigungu_code"),
        "marker_icon": feature.marker_icon,
        "marker_color": feature.marker_color,
        "notice_type": notice_detail.get("notice_type") if notice_detail else None,
        "notice_severity": notice_detail.get("severity") if notice_detail else None,
        "valid_start_time": (
            _jsonable(notice_detail.get("valid_start_time")) if notice_detail else None
        ),
        "valid_end_time": (
            _jsonable(notice_detail.get("valid_end_time")) if notice_detail else None
        ),
        "route_type": route_detail.get("route_type") if route_detail else None,
        "updated_at": _jsonable(feature.updated_at),
        "provider_refs": [ref.provider for ref in feature.raw_refs],
    }


def _detail_rows_by_feature_id(
    session: Any,
    table: Any,
    feature_ids: list[str],
) -> dict[str, Mapping[str, Any]]:
    if not feature_ids:
        return {}
    rows = (
        session.execute(select(table).where(table.c.feature_id.in_(feature_ids)))
        .mappings()
        .all()
    )
    return {str(row["feature_id"]): row for row in rows}


def _get_feature(context: Any, feature_id: str) -> dict[str, Any]:
    with context.session_factory() as session:
        row = session.execute(
            select(features).where(features.c.feature_id == feature_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"Feature not found: {feature_id}")
        feature = feature_from_row(row)
        details = {
            "place": _one_detail(session, feature_place_details, feature_id, place_detail_from_row),
            "event": _one_detail(session, feature_event_details, feature_id, event_detail_from_row),
            "area": _one_detail(session, feature_area_details, feature_id, area_detail_from_row),
            "route": _one_detail(session, feature_route_details, feature_id, route_detail_from_row),
            "notice": _one_detail(
                session,
                feature_notice_details,
                feature_id,
                notice_detail_from_row,
            ),
        }
        related = {
            "files": _table_rows(session, feature_files, feature_files.c.feature_id == feature_id),
            "opening_periods": _table_rows(
                session,
                feature_opening_periods,
                feature_opening_periods.c.feature_id == feature_id,
            ),
            "special_days": _table_rows(
                session,
                feature_special_days,
                feature_special_days.c.feature_id == feature_id,
            ),
            "weather_values": _table_rows(
                session,
                feature_weather_values,
                feature_weather_values.c.feature_id == feature_id,
                limit=200,
            ),
            "price_point": _table_rows(
                session,
                price_points,
                price_points.c.feature_id == feature_id,
            ),
            "price_values": _table_rows(
                session,
                price_values,
                price_values.c.feature_id == feature_id,
                limit=200,
            ),
            "overrides": _table_rows(
                session,
                feature_overrides,
                feature_overrides.c.feature_id == feature_id,
            ),
            "integrity_violations": _table_rows(
                session,
                data_integrity_violations,
                data_integrity_violations.c.feature_id == feature_id,
            ),
            "dedup_candidates": _table_rows(
                session,
                dedup_review_queue,
                or_(
                    dedup_review_queue.c.feature_id_a == feature_id,
                    dedup_review_queue.c.feature_id_b == feature_id,
                ),
            ),
        }
        source_rows = session.execute(
            select(source_links, source_records)
            .join(
                source_records,
                source_records.c.source_record_key == source_links.c.source_record_key,
            )
            .where(source_links.c.feature_id == feature_id)
            .order_by(source_links.c.is_primary_source.desc(), source_links.c.source_role)
        ).mappings().all()
    sources = [_nested_mapping(row, ("source_links", "source_records")) for row in source_rows]
    return {
        "model": _jsonable(feature),
        "row": _jsonable(dict(row)),
        "details": _jsonable(details),
        "sources": _jsonable(sources),
        "related": _jsonable(related),
    }


def _one_detail(
    session: Any,
    table: Any,
    feature_id: str,
    factory: Any,
) -> dict[str, Any] | None:
    row = (
        session.execute(select(table).where(table.c.feature_id == feature_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _jsonable(factory(row))


def _table_rows(
    session: Any,
    table: Any,
    condition: Any,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = session.execute(select(table).where(condition).limit(limit)).mappings().all()
    return [_jsonable(dict(row)) for row in rows]


def _nested_mapping(row: Mapping[str, Any], table_names: tuple[str, ...]) -> dict[str, Any]:
    result = {name: {} for name in table_names}
    for key, value in row.items():
        placed = False
        for table_name in table_names:
            prefix = f"{table_name}_"
            if str(key).startswith(prefix):
                result[table_name][str(key)[len(prefix) :]] = value
                placed = True
                break
        if not placed:
            result.setdefault("row", {})[str(key)] = value
    return _jsonable(result)


def _upsert_feature(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    feature_payload = payload.get("feature")
    if not isinstance(feature_payload, Mapping):
        raise ValueError("feature must be an object")
    feature = Feature.model_validate(_normalize_feature_payload(feature_payload))
    with context.session_factory() as session:
        load_feature_rows(session, feature_items=[feature])
        session.commit()
    return _jsonable(feature)


def _patch_feature(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    feature_id = _required(payload, "feature_id")
    patch_payload = payload.get("patch")
    if not isinstance(patch_payload, Mapping):
        raise ValueError("patch must be an object")
    patch = FeaturePatch.model_validate(_normalize_feature_payload(patch_payload))
    with context.session_factory() as session:
        row = session.execute(
            select(features).where(features.c.feature_id == feature_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"Feature not found: {feature_id}")
        feature = feature_from_row(row)
        updated = feature.model_copy(update=patch.model_dump(exclude_unset=True))
        load_feature_rows(session, feature_items=[updated])
        session.commit()
    return _jsonable(updated)


def _delete_feature(context: Any, payload: Mapping[str, Any]) -> None:
    feature_id = _required(payload, "feature_id")
    hard = bool(payload.get("hard"))
    with context.session_factory() as session:
        if hard:
            session.execute(delete(features).where(features.c.feature_id == feature_id))
        else:
            row = session.execute(
                select(features).where(features.c.feature_id == feature_id)
            ).mappings().one_or_none()
            if row is None:
                raise ValueError(f"Feature not found: {feature_id}")
            feature = feature_from_row(row).model_copy(
                update={
                    "status": FeatureStatus.DELETED.value,
                    "deleted_at": datetime.now().astimezone(),
                    "updated_at": datetime.now().astimezone(),
                }
            )
            load_feature_rows(session, feature_items=[feature])
        session.commit()


def _list_table(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    table_name = _required(payload, "table")
    if table_name not in metadata.tables:
        raise ValueError(f"Unknown table: {table_name}")
    table = metadata.tables[table_name]
    limit = _bounded_int(payload.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(payload.get("offset"), default=0, minimum=0, maximum=100_000)
    query = str(payload.get("q") or "").strip()

    stmt = select(table)
    count_stmt: Select[Any] = select(func.count()).select_from(table)
    if query:
        like = f"%{query}%"
        text_columns = [column for column in table.columns if "TEXT" in str(column.type).upper()]
        if text_columns:
            condition = or_(*[column.ilike(like) for column in text_columns])
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
    stmt = stmt.limit(limit).offset(offset)

    with context.session_factory() as session:
        rows = session.execute(stmt).mappings().all()
        total = int(session.scalar(count_stmt) or 0)
    return {
        "table": table_name,
        "items": [_jsonable(dict(row)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _list_fixtures(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    base = Path(_fixture_dir(payload))
    if not base.exists():
        return []
    fixtures = []
    for path in sorted(base.glob("**/*.json")):
        fixtures.append(
            {
                "path": str(path),
                "name": path.stem,
                "function": path.parent.name,
                "size": path.stat().st_size,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return fixtures


def _save_fixture(payload: Mapping[str, Any]) -> Path:
    fixture_payload = payload.get("payload")
    if not isinstance(fixture_payload, Mapping):
        raise ValueError("payload must be an object")
    return save_fixture(
        base_dir=_fixture_dir(payload),
        function_name=str(
            payload.get("function_name") or payload.get("functionName") or "debug_ui"
        ),
        case_name=str(payload.get("case_name") or payload.get("caseName") or "case"),
        description=str(payload.get("description") or "Saved from Next.js debug UI"),
        input_data=dict(fixture_payload.get("input") or {}),
        request_data=dict(fixture_payload.get("request") or {}),
        response_data=dict(fixture_payload.get("response") or {}),
        parsed_result=fixture_payload.get("parsed"),
        processed_result=fixture_payload.get("processed"),
        assertion=dict(fixture_payload.get("assertion") or {"mode": "schema_only"}),
        overwrite=bool(payload.get("overwrite")),
    )


def _etl_catalog() -> list[dict[str, Any]]:
    standard_rows = [
        {
            "provider": "data.go.kr-standard",
            "dataset_key": spec.dataset_key,
            "dataset_id": spec.dataset_id,
            "title": spec.title,
            "feature_kind": spec.feature_kind,
            "source_entity_type": spec.source_entity_type,
            "official_refresh_cycle": spec.official_refresh_cycle,
            "metadata_probe_interval_days": spec.metadata_probe_interval_days,
            "full_scan_interval_days": spec.full_scan_interval_days,
            "portal_url": spec.portal_url,
        }
        for spec in standard_dataset_specs()
    ]
    notice_rows = [
        {
            "provider": spec.provider,
            "dataset_key": spec.dataset_key,
            "dataset_id": None,
            "title": spec.title,
            "feature_kind": FeatureKind.NOTICE.value,
            "source_entity_type": spec.source_entity_type,
            "official_refresh_cycle": f"{spec.interval_minutes} minutes",
            "metadata_probe_interval_days": None,
            "full_scan_interval_days": None,
            "interval_minutes": spec.interval_minutes,
            "portal_url": None,
        }
        for spec in notice_dataset_specs()
    ]
    return standard_rows + notice_rows


def _dagster_jobs() -> list[dict[str, Any]]:
    jobs = []
    for spec in standard_data_full_scan_job_specs():
        jobs.append(
            {
                "job_name": spec.job_name,
                "op_name": spec.op_name,
                "dataset_key": spec.dataset_key,
                "description": spec.description,
                "tags": list(spec.tags),
                "success_message": spec.success_message,
                "failure_message": spec.failure_message,
                "schedule_enabled": spec.schedule_enabled() if spec.schedule_enabled else True,
            }
        )
    for spec in notice_job_specs():
        jobs.append(
            {
                "job_name": spec.job_name,
                "op_name": spec.op_name,
                "dataset_key": spec.dataset_key,
                "description": spec.description,
                "tags": list(spec.tags),
                "success_message": spec.success_message,
                "failure_message": spec.failure_message,
                "schedule_enabled": spec.schedule_enabled() if spec.schedule_enabled else True,
            }
        )
    return jobs


def _rustfs_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    path = rustfs_config_path(payload.get("config_path") or payload.get("configPath"))
    settings = load_rustfs_settings(path)
    return {
        "config_path": str(path),
        "settings": redacted_rustfs_settings(settings),
        "console_url": settings.console_url,
    }


def _save_rustfs_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("config must be an object")
    path = rustfs_config_path(payload.get("config_path") or payload.get("configPath"))
    previous = load_rustfs_settings(path)
    data = dict(config)
    if data.get("secret_access_key") == "<configured>":
        data["secret_access_key"] = previous.secret_access_key
    if data.get("access_key_id") == "<configured>":
        data["access_key_id"] = previous.access_key_id
    settings = rustfs_settings_from_mapping(data)
    saved_path = save_rustfs_settings(settings, path)
    return {
        "config_path": str(saved_path),
        "settings": redacted_rustfs_settings(settings),
        "console_url": settings.console_url,
    }


def _rustfs_files(payload: Mapping[str, Any]) -> dict[str, Any]:
    path = payload.get("config_path") or payload.get("configPath")
    settings = load_rustfs_settings(path)
    if not settings.enabled:
        return {
            "bucket": settings.bucket,
            "prefix": str(payload.get("prefix") or ""),
            "objects": [],
            "is_truncated": False,
            "next_continuation_token": None,
            "console_url": settings.console_url,
            "warning": "RustFS integration is disabled.",
        }
    client = RustfsS3Client(settings)
    listing = client.list_objects(
        bucket=str(payload.get("bucket") or settings.bucket),
        prefix=str(payload.get("prefix") or ""),
        max_keys=_bounded_int(payload.get("max_keys"), default=100, minimum=1, maximum=1000),
        continuation_token=(
            str(payload.get("continuation_token"))
            if payload.get("continuation_token") is not None
            else None
        ),
    )
    return {
        "bucket": listing.bucket,
        "prefix": listing.prefix,
        "objects": [_jsonable(item) for item in listing.objects],
        "is_truncated": listing.is_truncated,
        "next_continuation_token": listing.next_continuation_token,
        "console_url": settings.console_url,
    }


def _preview_standard_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    items = _standard_data_items(payload)
    result = collect_standard_data_features(dataset_key, items)
    return {
        "dataset_key": dataset_key,
        "counts": _etl_result_counts(result),
        "features": [_jsonable(feature) for feature in result.features[:20]],
        "source_records": [_jsonable(record) for record in result.source_records[:20]],
        "skipped_items": [_jsonable(item) for item in result.skipped_items[:20]],
    }


def _fetch_standard_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    page_size = _bounded_int(payload.get("page_size"), default=10, minimum=1, maximum=1000)
    max_pages = _bounded_int(payload.get("max_pages"), default=1, minimum=1, maximum=10)
    api_key = payload.get("api_key") or payload.get("service_key")
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}

    async def run() -> dict[str, Any]:
        client = StandardDataClient.aio(api_key=str(api_key) if api_key else None)
        result = await async_collect_standard_data_features(
            client,
            dataset_key,
            page_size=page_size,
            max_pages=max_pages,
            **dict(params),
        )
        await client.aclose()
        return {
            "dataset_key": dataset_key,
            "counts": _etl_result_counts(result),
            "features": [_jsonable(feature) for feature in result.features[:20]],
            "skipped_items": [_jsonable(item) for item in result.skipped_items[:20]],
        }

    return _run_async(run())


def _load_standard_data(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    items = _standard_data_items(payload)
    result = collect_standard_data_features(dataset_key, items)
    with context.session_factory() as session:
        load = load_standard_data_result(session, result)
        session.commit()
    return {
        "dataset_key": dataset_key,
        "counts": _etl_result_counts(result),
        "load": _jsonable(load),
        "features": [_jsonable(feature) for feature in result.features[:20]],
        "skipped_items": [_jsonable(item) for item in result.skipped_items[:20]],
    }


def _preview_notice_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    items = _standard_data_items(payload)
    result = collect_notice_dataset_features(dataset_key, items)
    return {
        "dataset_key": dataset_key,
        "counts": _etl_result_counts(result),
        "features": [_jsonable(feature) for feature in result.features[:20]],
        "notice_details": [_jsonable(detail) for detail in result.notice_details[:20]],
        "source_records": [_jsonable(record) for record in result.source_records[:20]],
        "skipped_items": [_jsonable(item) for item in result.skipped_items[:20]],
    }


def _load_notice_data(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    items = _standard_data_items(payload)
    result = collect_notice_dataset_features(dataset_key, items)
    with context.session_factory() as session:
        load = load_notice_result(session, result)
        session.commit()
    return {
        "dataset_key": dataset_key,
        "counts": _etl_result_counts(result),
        "load": _jsonable(load),
        "features": [_jsonable(feature) for feature in result.features[:20]],
        "notice_details": [_jsonable(detail) for detail in result.notice_details[:20]],
        "skipped_items": [_jsonable(item) for item in result.skipped_items[:20]],
    }


def _run_dagster_etl(context: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_key = _required(payload, "dataset_key")
    items = _standard_data_items(payload)
    logical_datetime = parse_logical_datetime(payload.get("logical_datetime"))
    run_key = payload.get("run_key") or f"debug-{dataset_key}-{logical_datetime:%Y%m%d%H%M%S}"
    run = DagsterEtlRun(
        dataset_key=dataset_key,
        run_key=str(run_key),
        run_type=str(payload.get("run_type") or "manual"),
        trigger_date=logical_datetime.date(),
        logical_datetime=logical_datetime,
        op_config={
            "dataset_key": dataset_key,
            "page_size": payload.get("page_size"),
            "max_pages": payload.get("max_pages"),
            "max_items": payload.get("max_items"),
        },
    )
    with context.session_factory() as session:
        if dataset_key in {spec.dataset_key for spec in notice_dataset_specs()}:
            result = load_notice_features(NoticeLoadResources(session=session, items=items), run)
        else:
            result = load_standard_data_features(
                StandardDataLoadResources(session=session, items=items),
                run,
            )
        session.commit()
    collection = getattr(result, "collection", result)
    load = getattr(result, "load", None)
    return {
        "run": _jsonable(run),
        "dataset_key": dataset_key,
        "counts": _etl_result_counts(collection),
        "load": _jsonable(load),
        "features": [_jsonable(feature) for feature in collection.features[:20]],
        "skipped_items": [_jsonable(item) for item in collection.skipped_items[:20]],
    }


def _standard_data_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = payload.get("items")
    if items is None:
        raw_item = payload.get("item")
        items = [raw_item] if isinstance(raw_item, Mapping) else []
    if not isinstance(items, list | tuple):
        raise ValueError("items must be a list of objects")
    records: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("items must contain only objects")
        records.append(item)
    return records


def _etl_result_counts(result: Any) -> dict[str, int]:
    return {
        "features": len(result.features),
        "source_records": len(result.source_records),
        "source_links": len(result.source_links),
        "place_details": len(getattr(result, "place_details", ())),
        "event_details": len(getattr(result, "event_details", ())),
        "area_details": len(getattr(result, "area_details", ())),
        "route_details": len(getattr(result, "route_details", ())),
        "notice_details": len(getattr(result, "notice_details", ())),
        "weather_values": len(getattr(result, "weather_values", ())),
        "price_points": len(getattr(result, "price_points", ())),
        "price_values": len(getattr(result, "price_values", ())),
        "skipped_items": len(result.skipped_items),
    }


def _run_async(coro: Any) -> Any:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(f"debug_api cannot run nested asyncio loop {loop!r}")


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounds_filter(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Mapping):
        return None
    if all(key in value for key in ("south", "west", "north", "east")):
        raw = (value["south"], value["west"], value["north"], value["east"])
    elif isinstance(value.get("sw"), Mapping) and isinstance(value.get("ne"), Mapping):
        sw = value["sw"]
        ne = value["ne"]
        raw = (
            sw.get("lat") or sw.get("latitude"),
            sw.get("lng") or sw.get("lon") or sw.get("longitude"),
            ne.get("lat") or ne.get("latitude"),
            ne.get("lng") or ne.get("lon") or ne.get("longitude"),
        )
    else:
        return None
    try:
        south, west, north, east = (float(item) for item in raw)
    except (TypeError, ValueError):
        return None
    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west
    return south, west, north, east


def _normalize_feature_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    address = data.get("address")
    if not isinstance(address, Mapping):
        return data

    address_input = dict(address)
    if "legal_dong_code" in address_input and "admCd" not in address_input:
        address_input["admCd"] = address_input["legal_dong_code"]
    if "road_name_code" in address_input and "rnMgtSn" not in address_input:
        address_input["rnMgtSn"] = address_input["road_name_code"]
    parsed = Address.from_mapping(address_input)
    if parsed is not None:
        data["address"] = _jsonable(parsed)
    return data


def _sample_feature() -> dict[str, Any]:
    now = datetime.now().astimezone().isoformat()
    address = Address.from_mapping(
        {
            "address": "Seoul Jung-gu Sejong-daero 110",
            "admCd": "1114010300",
            "rnMgtSn": "111404103000",
        }
    )
    return {
        "feature_id": "debug_feature_sample",
        "kind": "place",
        "name": "Debug Sample Feature",
        "coord": {"latitude": 37.5665, "longitude": 126.9780},
        "address": _jsonable(address) if address is not None else {},
        "category": "tourism.attraction",
        "urls": {},
        "marker_icon": "marker",
        "marker_color": "P-01",
        "detail": {"note": "created from debug UI"},
        "raw_refs": [],
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        result = handle(payload)
    except Exception as exc:  # pragma: no cover - CLI safety belt
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    json.dump(_jsonable(result), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
