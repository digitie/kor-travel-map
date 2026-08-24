#!/usr/bin/env python3
"""#741 production live 인수용 weather/price owned fixture 관리.

이 helper는 exact API image의 standalone container에 read-only bind mount해 실행한다.
운영 기존 row를 빌리지 않고 실행별 exact ID 두 건만 transaction으로
seed/cleanup/audit한다. host runner가 mutation 전에 root-owned BLOCKED/journal을 기록하는
것이 선행조건이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, NamedTuple

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.dto import SourceLink, SourceRecord, SourceRole
from kortravelmap.dto._time import kst_now
from kortravelmap.dto.price import PriceValue
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import feature_repo, price_repo, weather_repo
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_identity import candidate_feature_uuid
from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    upsert_provider_refresh_policy,
)
from kortravelmap.settings import KorTravelMapSettings

_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_LON: Final[float] = 127.5
_LAT: Final[float] = 36.5
_E2E_PROVIDER: Final[str] = "e2e-live-acceptance"
_FIXTURE_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"
_FIXTURE_PROCEDURE_EXECUTOR: Final[str] = "ktm_manual_feature_procedure_owner"
_FIXTURE_CONFIRM_DATABASE_ENV: Final[str] = (
    "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE"
)
_FIXTURE_CONFIRM_LOGIN_ROLE_ENV: Final[str] = (
    "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE"
)
_FIXTURE_CONFIRM_ALEMBIC_REVISION_ENV: Final[str] = (
    "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION"
)


def _dataset_key(run_id: str, kind: str) -> str:
    return f"admin-live-{run_id}-{kind}"


async def _ensure_dataset(session: AsyncSession, *, run_id: str, kind: str) -> int:
    dataset_key = _dataset_key(run_id, kind)
    value = await session.scalar(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES (:provider, :dataset_key, :display_name, 'manual')
            ON CONFLICT (provider, dataset_key) DO UPDATE
            SET is_active = true
            RETURNING provider_dataset_id
            """
        ),
        {
            "provider": _E2E_PROVIDER,
            "dataset_key": dataset_key,
            "display_name": f"E2E admin {kind} {run_id}",
        },
    )
    assert value is not None
    dataset_id = int(value)
    if kind == "weather":
        policy = await get_provider_refresh_policy(
            session, provider_dataset_id=dataset_id
        )
        await upsert_provider_refresh_policy(
            session,
            provider_dataset_id=dataset_id,
            source_kind="manual",
            expected_revision=(policy.revision if policy is not None else None),
            stale_after_minutes=24 * 60,
        )
    return dataset_id


def _response_record(
    *, run_id: str, kind: str, fetched_at: datetime
) -> SourceRecord:
    dataset_key = _dataset_key(run_id, kind)
    raw_data = {"fixture": "admin-feature-live-acceptance", "run_id": run_id, "kind": kind}
    payload_hash = make_payload_hash(raw_data)
    source_entity_id = f"run:{run_id}:{kind}"
    return SourceRecord(
        provider=_E2E_PROVIDER,
        dataset_key=dataset_key,
        source_entity_type=f"{kind}_response",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=make_source_record_key(
            provider=_E2E_PROVIDER,
            dataset_key=dataset_key,
            source_entity_type=f"{kind}_response",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )


def _feature_ids(run_id: str) -> tuple[str, str]:
    """API resolver가 재해석할 수 있는 live weather/price legacy ID 두 건."""

    return (
        _provider_fixture_feature_id(run_id, "weather"),
        _provider_fixture_feature_id(run_id, "price"),
    )


def _provider_fixture_feature_id(run_id: str, kind: str) -> str:
    return make_feature_id(
        bjd_code=None,
        kind=kind,
        category="00000000",
        source_type=_E2E_PROVIDER,
        source_natural_key=f"{run_id}:{kind}",
    )


# ── T-VN-36 API-owned fixture 계약 ───────────────────────────────────────────
# 0104(`0104_tvn36_final_fence`)가 ``ops.feature_change_requests``와
# ``feature.feature_versions``를 통째로 지웠다. review/whole-row-freeze 모델이
# 사라졌으므로 API-owned 잔재는 이제 세 곳에만 남는다.
#
#   * ``feature.features``            — live spec이 만든 Feature 한 건
#   * ``feature.feature_state_transitions`` — create/suppress/retire 전이 사슬
#   * ``ops.feature_overrides``       — create가 남긴 field ownership receipt
#     (+ 각 명령의 ``ops.domain_commands`` terminal receipt)
#
# 소유권 키도 바뀌었다. live spec은 여섯 개의 결정적 fixture id를 더 이상 쓰지
# 않고 **이름 하나**(`E2E TVN36 state fixture {run_id}`)로 자기 행을 식별한다 —
# ``POST /v1/admin/features``의 ``feature_id``는 서버가 발급한다.
_ADMIN_FIXTURE_KIND: Final[str] = "place"
_ADMIN_FIXTURE_CATEGORY: Final[str] = "01070300"
_ADMIN_FIXTURE_MARKER_ICON: Final[str] = "marker"
_ADMIN_FIXTURE_MARKER_COLOR: Final[str] = "P-02"
#: create body가 ``coord_precision_digits``를 보내지 않으므로 override writer의
#: 기본값(``_override_payload_for_change``)이 그대로 정본이 된다.
_ADMIN_FIXTURE_COORD_PRECISION_DIGITS: Final[int] = 6
#: admin proxy가 주입하는 운영자 actor. auth 감사(`ops.admin_auth_events`)의
#: ``attempted_username``과 같은 값이다.
_ADMIN_OPERATOR: Final[str] = "admin"
#: create procedure가 initial 전이에 박는 고정 reason_code
#: (``create_admin_feature_with_field_overrides``의 state context). run reason이
#: 아니라 서버 상수라서 run_id 접두어를 갖지 않는다.
_ADMIN_CREATE_TRANSITION_REASON: Final[str] = "admin_feature_create"
#: initial 전이의 ``causation_ref`` 형식 — ``domain-command:{command_id}``.
_CAUSATION_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"^domain-command:([1-9][0-9]*)$"
)
#: create가 authoring하는 field override path. live spec의 create body
#: (category/coord/kind/marker_color/marker_icon/name + 3축)에 대해
#: ``_override_payload_for_change(include_required_create_fields=True)``가
#: 만드는 정확한 집합이다: core 4개(name/category/marker_icon/marker_color) +
#: coord가 파생시키는 ``core.coord_precision_digits``(scalar)와
#: ``core.coord``(geometry). detail을 보내지 않으므로 subtype path는 없다.
#: 행 수는 path 하나당 하나이므로 개수를 따로 박지 않고 이 집합에서 유도한다.
_ADMIN_CREATE_OVERRIDE_FIELD_PATHS: Final[frozenset[str]] = frozenset(
    {
        "core.category",
        "core.coord",
        "core.coord_precision_digits",
        "core.marker_color",
        "core.marker_icon",
        "core.name",
    }
)
#: retire가 authoring하는 lifecycle override. field override와 **형태가 다르다** —
#: `feature.author_lifecycle_override`가 만들고, provider 재적재가 retire를 되돌리지
#: 못하게 `prevent_provider_reactivation = true`를 세운다(field override는 항상
#: false다). `command_id`도 남기지 않는다.
#:
#: 2026-08-13 live 실행에서 처음 관측했다. create body만 보고 기대 집합을 유도했더니
#: 이 7번째 row에서 "field override 소유권이 다릅니다"로 죽었다 — spec이 무엇을
#: 남기는지는 코드를 읽어서가 아니라 실행에서만 드러난다.
_ADMIN_RETIRE_OVERRIDE_FIELD_PATH: Final[str] = "lifecycle_state"
#: 완주한 run이 남기는 override path 전체.
_EXPECTED_OVERRIDE_FIELD_PATHS: Final[frozenset[str]] = (
    _ADMIN_CREATE_OVERRIDE_FIELD_PATHS | {_ADMIN_RETIRE_OVERRIDE_FIELD_PATH}
)
#: live spec이 실행하는 mutation 명령. GET은 domain command를 만들지 않는다.
_ADMIN_CREATE_OPERATION: Final[str] = "admin.feature.create"
_ADMIN_STATE_OPERATION: Final[str] = "admin.feature.state"


def _admin_fixture_name(run_id: str) -> str:
    """live spec의 ``FIXTURE_NAME``. API-owned row의 유일한 소유권 키다."""

    return f"E2E TVN36 state fixture {run_id}"


def _admin_reason_prefix(run_id: str) -> str:
    """live spec의 ``REASON``. run-owned reason_code는 모두 이 접두어를 갖는다."""

    return f"tvn36-live-{run_id}"


def _admin_fixture_feature_id(run_id: str) -> str:
    """서버가 발급할 ``feature_id``를 router와 같은 규칙으로 재계산한다.

    감사 자체는 이 값을 소유권 키로 쓰지 않는다 — 정본은 이름이다. 그러나 clone
    러너의 content digest는 run-owned 행을 **id 리터럴**로 제외해야 하고, 그
    목록은 Feature를 hard purge한 뒤에도 유효해야 한다(전이 감사는 append-only라
    남는다). 그래서 같은 규칙을 여기 한 곳에 두고 inspection에서 관측된 id와
    대조한다 — router 규칙이 바뀌면 digest가 조용히 새는 대신 감사가 실패한다.

    ``_create_feature_id``는 body에 ``idempotency_key``/``legal_dong_code``가
    없을 때 ``{name}:{lon:.6f},{lat:.6f}``를 자연키로 쓴다.
    """

    return make_feature_id(
        bjd_code=None,
        kind=_ADMIN_FIXTURE_KIND,
        category=_ADMIN_FIXTURE_CATEGORY,
        source_type="user_request",
        source_natural_key=f"{_admin_fixture_name(run_id)}:{_LON:.6f},{_LAT:.6f}",
    )


async def _counts(session: AsyncSession, feature_ids: tuple[str, str]) -> dict[str, int]:
    weather_id, price_id = feature_ids
    row = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM feature.features
                   WHERE feature_id = ANY(CAST(:feature_ids AS text[]))) AS features,
                  (SELECT count(*) FROM feature.feature_weather_values
                   WHERE feature_id = :weather_id) AS weather_values,
                  (SELECT count(*) FROM feature.feature_price_values
                   WHERE feature_id = :price_id) AS price_values
                """
            ),
            {
                "feature_ids": list(feature_ids),
                "weather_id": weather_id,
                "price_id": price_id,
            },
        )
    ).mappings().one()
    return {key: int(row[key]) for key in ("features", "weather_values", "price_values")}


async def _owned_summary_run_ids(
    session: AsyncSession,
    feature_ids: tuple[str, str],
) -> tuple[int, int]:
    """fixture weather/price current-summary receipt 두 건을 정확히 식별한다.

    terminal receipt는 의도적으로 불변이라 Feature cascade 뒤에도 남는다. 따라서
    clone digest는 이 exact two IDs만 run-owned 변화로 정규화해야 하며, broad
    ``run_kind``/시간 범위 필터로 다른 receipt를 숨기면 안 된다.
    """

    rows = (
        await session.execute(
            text(
                """
                SELECT summary_run_id
                FROM feature.current_weather_summary
                WHERE feature_id = :weather_id
                UNION ALL
                SELECT summary_run_id
                FROM feature.current_price_summary
                WHERE feature_id = :price_id
                ORDER BY summary_run_id
                """
            ),
            {"weather_id": feature_ids[0], "price_id": feature_ids[1]},
        )
    ).scalars().all()
    summary_run_ids = tuple(int(value) for value in rows)
    if (
        len(summary_run_ids) != 2
        or len(set(summary_run_ids)) != 2
        or any(value <= 0 for value in summary_run_ids)
    ):
        raise RuntimeError("owned weather/price current-summary receipt가 정확하지 않습니다")
    return summary_run_ids[0], summary_run_ids[1]


async def _assert_owned_or_absent(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    *,
    lock: bool = False,
) -> set[str]:
    lock_clause = " FOR UPDATE" if lock else ""
    rows = (
        await session.execute(
            text(
                """
                SELECT
                  feature_id, kind, name, category,
                  lifecycle_state, publication_state, quality_state,
                  marker_icon, marker_color, coord_precision_digits,
                  x_extension.ST_X(coord) AS lon,
                  x_extension.ST_Y(coord) AS lat
                FROM feature.features
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY feature_id
                """
                + lock_clause
            ),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings()
    expected = {
        feature_ids[0]: {
            "category": "00000000",
            "coord_precision_digits": 6,
            "kind": "weather",
            "lat": _LAT,
            "lon": _LON + 0.002,
            "marker_color": "P-03",
            "marker_icon": "weather",
            "name": f"E2E suppressed weather {run_id}",
            "lifecycle_state": "active",
            "publication_state": "suppressed",
            "quality_state": "valid",
        },
        feature_ids[1]: {
            "category": "00000000",
            "coord_precision_digits": 6,
            "kind": "price",
            "lat": _LAT,
            "lon": _LON - 0.002,
            "marker_color": "P-04",
            "marker_icon": "fuel",
            "name": f"E2E suppressed price {run_id}",
            "lifecycle_state": "active",
            "publication_state": "suppressed",
            "quality_state": "valid",
        },
    }
    present: set[str] = set()
    for row in rows:
        feature_id = str(row["feature_id"])
        present.add(feature_id)
        fingerprint = {
            "category": str(row["category"]),
            "coord_precision_digits": int(row["coord_precision_digits"]),
            "kind": str(row["kind"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "marker_color": str(row["marker_color"]),
            "marker_icon": str(row["marker_icon"]),
            "name": str(row["name"]),
            "lifecycle_state": str(row["lifecycle_state"]),
            "publication_state": str(row["publication_state"]),
            "quality_state": str(row["quality_state"]),
        }
        if expected.get(feature_id) != fingerprint:
            raise RuntimeError("owned fixture ID의 소유권 fingerprint가 다릅니다")
    return present


async def _assert_owned_source_links(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    present: set[str],
    *,
    lock: bool = False,
) -> None:
    """fixture Feature의 primary source lineage를 exact fingerprint로 감사한다.

    ``create_feature_with_initial_state``는 Feature/state만 만들고
    ``provider_sync.source_links``는 만들지 않는다. 따라서 provider ingestion과
    같은 transaction에서 별도로 primary link를 만든 뒤, source entity head가
    fixture record를 가리키는지까지 확인해야 API detail/provider filter가 보는
    계보와 실제 fixture 소유권이 일치한다.
    """

    expected: dict[str, dict[str, object]] = {}
    for feature_id, kind in zip(feature_ids, ("weather", "price"), strict=True):
        if feature_id not in present:
            continue
        expected[feature_id] = {
            "provider": _E2E_PROVIDER,
            "dataset_key": _dataset_key(run_id, kind),
            "source_entity_type": f"{kind}_response",
            "source_entity_id": f"run:{run_id}:{kind}",
            "source_record_key": _response_record(
                run_id=run_id,
                kind=kind,
                fetched_at=kst_now(),
            ).source_record_key,
            "source_role": SourceRole.PRIMARY.value,
            "match_method": "natural_key",
            "confidence": 100,
        }
    lock_clause = " FOR UPDATE OF link" if lock else ""
    rows = (
        await session.execute(
            text(
                """
                SELECT
                  link.feature_id,
                  dataset.provider,
                  dataset.dataset_key,
                  entity.source_entity_type,
                  entity.source_entity_id,
                  head.current_source_record_key AS source_record_key,
                  link.source_role,
                  link.match_method,
                  link.confidence
                FROM provider_sync.source_links AS link
                JOIN provider_sync.source_entities AS entity
                  ON entity.source_entity_key = link.source_entity_key
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = entity.provider_dataset_id
                JOIN provider_sync.source_entity_heads AS head
                  ON head.source_entity_key = entity.source_entity_key
                WHERE link.feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY link.feature_id
                """
                + lock_clause
            ),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings()
    row_list = list(rows)
    if len(row_list) != len(expected):
        raise RuntimeError(
            "owned fixture primary source lineage cardinality가 다릅니다: "
            f"expected={len(expected)}, observed={len(row_list)}"
        )
    observed = {
        str(row["feature_id"]): {
            key: row[key]
            for key in (
                "provider",
                "dataset_key",
                "source_entity_type",
                "source_entity_id",
                "source_record_key",
                "source_role",
                "match_method",
                "confidence",
            )
        }
        for row in row_list
    }
    if observed != expected:
        raise RuntimeError(
            "owned fixture primary source lineage가 다릅니다: "
            f"expected={expected!r}, observed={observed!r}"
        )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _foreign_key_reference_counts(
    session: AsyncSession,
    feature_ids: tuple[str, ...],
) -> dict[str, int]:
    constraints = (
        await session.execute(
            text(
                """
                SELECT
                  constraint_row.conname,
                  local_schema.nspname AS schema_name,
                  local_table.relname AS table_name,
                  local_column.attname AS column_name,
                  target_column.attname AS target_column_name
                FROM pg_catalog.pg_constraint AS constraint_row
                JOIN pg_catalog.pg_class AS local_table
                  ON local_table.oid = constraint_row.conrelid
                JOIN pg_catalog.pg_namespace AS local_schema
                  ON local_schema.oid = local_table.relnamespace
                JOIN pg_catalog.pg_attribute AS local_column
                  ON local_column.attrelid = constraint_row.conrelid
                 AND local_column.attnum = constraint_row.conkey[1]
                JOIN pg_catalog.pg_attribute AS target_column
                  ON target_column.attrelid = constraint_row.confrelid
                 AND target_column.attnum = constraint_row.confkey[1]
                WHERE constraint_row.contype = 'f'
                  AND constraint_row.confrelid = 'feature.features'::regclass
                  -- subtype/alias identity fence처럼 feature_id에 다른 정본 열을 붙이는
                  -- composite FK는 이 fixture가 가진 feature_id만으로 reference를 셀 수
                  -- 없다. 이 ownership 검사는 단일 feature_id FK의 cascade 잔여만
                  -- 정확히 계수한다.
                  AND cardinality(constraint_row.conkey) = 1
                  AND cardinality(constraint_row.confkey) = 1
                ORDER BY local_schema.nspname, local_table.relname,
                         local_column.attname, constraint_row.conname
                """
            )
        )
    ).mappings()
    counts: dict[str, int] = {}
    for constraint in constraints:
        if str(constraint["target_column_name"]) != "feature_id":
            raise RuntimeError("feature FK topology가 단일 feature_id 계약과 다릅니다")
        schema_name = str(constraint["schema_name"])
        table_name = str(constraint["table_name"])
        column_name = str(constraint["column_name"])
        key = f"{schema_name}.{table_name}.{column_name}"
        if key in counts:
            raise RuntimeError("같은 feature FK column에 중복 constraint가 있습니다")
        statement = text(
            "SELECT count(*) FROM "
            f"{_quote_identifier(schema_name)}.{_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier(column_name)} = ANY(CAST(:feature_ids AS text[]))"
        )
        counts[key] = int(
            (await session.execute(statement, {"feature_ids": list(feature_ids)}))
            .scalars()
            .one()
        )
    required = {
        "feature.feature_price_values.feature_id",
        "feature.feature_weather_values.feature_id",
    }
    if not required.issubset(counts):
        raise RuntimeError("weather/price feature FK constraint가 누락되었습니다")
    return counts


async def _assert_owned_values(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    present: set[str],
    *,
    lock: bool = False,
) -> None:
    lock_clause = " FOR UPDATE" if lock else ""
    weather_rows = (
        await session.execute(
            text(
                """
                SELECT
                  dataset.provider, dataset.dataset_key,
                  weather_domain, forecast_style, timeline_bucket,
                  metric_key, metric_name, value_number, unit,
                  normalization_version, payload
                FROM feature.feature_weather_values AS fact
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = fact.provider_dataset_id
                WHERE feature_id = :feature_id
                """
                + lock_clause
            ),
            {"feature_id": feature_ids[0]},
        )
    ).mappings().all()
    price_rows = (
        await session.execute(
            text(
                """
                SELECT
                  dataset.provider, dataset.dataset_key,
                  price_domain, product_key, product_name,
                  value_number, unit, normalization_version, payload
                FROM feature.feature_price_values AS fact
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = fact.provider_dataset_id
                WHERE feature_id = :feature_id
                """
                + lock_clause
            ),
            {"feature_id": feature_ids[1]},
        )
    ).mappings().all()
    expected_weather = []
    if feature_ids[0] in present:
        expected_weather.append(
            {
                "forecast_style": "short",
                "metric_key": "TMP",
                "metric_name": "인수 기온",
                "normalization_version": "e2e-v1",
                "payload": {"fixture": "admin-feature-live-acceptance"},
                "provider": _E2E_PROVIDER,
                "dataset_key": _dataset_key(run_id, "weather"),
                "timeline_bucket": "short",
                "unit": "deg_c",
                "value_number": Decimal("21.5"),
                "weather_domain": "kma_short_forecast",
            }
        )
    expected_price = []
    if feature_ids[1] in present:
        expected_price.append(
            {
                "normalization_version": "e2e-v1",
                "payload": {"fixture": "admin-feature-live-acceptance"},
                "price_domain": "opinet_gas_station",
                "product_key": "gasoline",
                "product_name": "인수 휘발유",
                "provider": _E2E_PROVIDER,
                "dataset_key": _dataset_key(run_id, "price"),
                "unit": "KRW/L",
                "value_number": Decimal("1711"),
            }
        )
    if [dict(row) for row in weather_rows] != expected_weather:
        raise RuntimeError("owned weather value fingerprint가 다릅니다")
    if [dict(row) for row in price_rows] != expected_price:
        raise RuntimeError("owned price value fingerprint가 다릅니다")


async def _assert_owned_state(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    *,
    lock: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    present = await _assert_owned_or_absent(
        session,
        run_id,
        feature_ids,
        lock=lock,
    )
    counts = await _counts(session, feature_ids)
    if counts["features"] != len(present):
        raise RuntimeError("owned fixture cardinality와 fingerprint가 다릅니다")
    await _assert_owned_source_links(
        session,
        run_id,
        feature_ids,
        present,
        lock=lock,
    )
    await _assert_owned_values(session, run_id, feature_ids, present, lock=lock)
    foreign_keys = await _foreign_key_reference_counts(session, feature_ids)
    expected_references: dict[str, int] = {}
    if present:
        # feature INSERT trigger가 canonical alias를 함께 만든다. alias는 direct
        # feature_id FK이므로 fixture cleanup의 cascade evidence에 포함한다.
        expected_references["feature.feature_aliases.feature_id"] = len(present)
        # provider procedure는 source evidence를 잠그지만 source link를 만들지
        # 않는다. fixture가 ingestion과 같은 primary lineage를 별도로 만들었는지
        # 확인하고, Feature CASCADE 뒤에는 이 reference도 0이어야 한다.
        expected_references["provider_sync.source_links.feature_id"] = len(present)
    if feature_ids[0] in present:
        expected_references["feature.feature_weather_values.feature_id"] = 1
        expected_references["feature.current_weather_summary.feature_id"] = 1
    if feature_ids[1] in present:
        expected_references["feature.feature_price_values.feature_id"] = 1
        expected_references["feature.current_price_summary.feature_id"] = 1
    observed_references = {key: value for key, value in foreign_keys.items() if value}
    if observed_references != expected_references:
        raise RuntimeError("owned fixture에 예상하지 않은 FK reference가 있습니다")
    return counts, foreign_keys


async def _seed(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int], tuple[int, int]]:
    feature_ids = _feature_ids(run_id)
    before = await _counts(session, feature_ids)
    if before != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned fixture ID가 이미 존재합니다; recovery를 먼저 실행하세요")

    now = kst_now().replace(microsecond=0)
    weather_dataset_id = await _ensure_dataset(session, run_id=run_id, kind="weather")
    price_dataset_id = await _ensure_dataset(session, run_id=run_id, kind="price")
    weather_record = _response_record(
        run_id=run_id,
        kind="weather",
        fetched_at=now,
    )
    price_record = _response_record(
        run_id=run_id,
        kind="price",
        fetched_at=now,
    )

    async def create_provider_feature(
        *,
        feature_id: str,
        kind: str,
        dataset_id: int,
        record: SourceRecord,
        name: str,
        lon: float,
        marker_icon: str,
        marker_color: str,
    ) -> None:
        # The API runtime is deliberately read-only after M01.  Register the
        # fixture's immutable source evidence first, then let the same provider
        # state procedure used by ingestion create the core Feature row.
        await feature_repo.upsert_source_record(session, record)
        membership = (
            await session.execute(
                text(
                    """
                    SELECT entity.source_entity_key,
                           head.current_source_record_key
                    FROM provider_sync.provider_datasets AS dataset
                    JOIN provider_sync.source_entities AS entity
                      ON entity.provider_dataset_id = dataset.provider_dataset_id
                    JOIN provider_sync.source_entity_heads AS head
                      ON head.source_entity_key = entity.source_entity_key
                    WHERE dataset.provider_dataset_id = :dataset_id
                      AND entity.provider = :provider
                      AND entity.dataset_key = :dataset_key
                      AND entity.source_entity_type = :source_entity_type
                      AND entity.source_entity_id = :source_entity_id
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "provider": record.provider,
                    "dataset_key": record.dataset_key,
                    "source_entity_type": record.source_entity_type,
                    "source_entity_id": record.source_entity_id,
                },
            )
        ).mappings().one()
        source_entity_key = str(membership["source_entity_key"])
        source_record_key = str(membership["current_source_record_key"])
        if source_record_key != record.source_record_key:
            raise RuntimeError("fixture source head가 방금 등록한 record를 가리키지 않습니다")
        payload = {
            "feature_id": feature_id,
            "feature_uuid": str(candidate_feature_uuid()),
            "kind": kind,
            "name": name,
            "category": "00000000",
            "lon": lon,
            "lat": _LAT,
            "coord_precision_digits": 6,
            "address": {},
            "urls": {},
            "marker_icon": marker_icon,
            "marker_color": marker_color,
            "raw_refs": [],
        }
        # M01에서 generic provider state procedure의 EXECUTE는 schema owner가
        # 아니라 dedicated manual procedure owner에만 준다. schema owner가
        # SET 가능한 NOLOGIN role로 **이 CALL 하나만** 임시 전환한다. procedure는
        # SECURITY DEFINER라 fixture helper에 테이블 write grant를 넓히지 않는다.
        await session.execute(text(f"SET LOCAL ROLE {_FIXTURE_PROCEDURE_EXECUTOR}"))
        row = (
            await session.execute(
                text(
                    """
                    CALL feature.create_feature_with_initial_state(
                        CAST(:feature_payload AS jsonb),
                        CAST(:lifecycle_state AS text),
                        CAST(:publication_state AS text),
                        CAST(:quality_state AS text),
                        CAST(:state_context AS jsonb),
                        NULL, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "feature_payload": json.dumps(payload, ensure_ascii=False),
                    "lifecycle_state": "active",
                    "publication_state": "suppressed",
                    "quality_state": "valid",
                    "state_context": json.dumps(
                        {
                            "transition_kind": "provider_sync",
                            "reason_code": "admin_live_fixture",
                            "provider_dataset_id": dataset_id,
                            "source_entity_key": source_entity_key,
                            "source_record_key": source_record_key,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            .mappings()
            .one()
        )
        # source_links와 value rows는 schema-owner SQL로만 계속 쓴다. CALL이
        # 실패하면 transaction이 abort되어 SET LOCAL도 transaction 종료와 함께
        # 사라지므로, 실패한 transaction에서 억지 reset을 시도하지 않는다.
        await session.execute(text(f"SET LOCAL ROLE {_FIXTURE_SCHEMA_OWNER}"))
        if (
            str(row["o_feature_id"]) != feature_id
            or not bool(row["o_inserted"])
        ):
            raise RuntimeError("provider fixture Feature procedure가 신규 행을 만들지 않았습니다")
        # ``create_feature_with_initial_state`` deliberately does not mutate
        # provider_sync.source_links.  Mirror ``feature_repo.load_bundle`` here:
        # after the Feature FK exists, create the canonical primary lineage in
        # the same transaction and fail closed if it was unexpectedly an update.
        link_inserted = await feature_repo.upsert_source_link(
            session,
            SourceLink(
                feature_id=feature_id,
                source_record_key=source_record_key,
                source_role=SourceRole.PRIMARY,
                match_method="natural_key",
                confidence=100,
                created_at=record.fetched_at,
            ),
        )
        if not link_inserted:
            raise RuntimeError("provider fixture primary source link가 신규 행이 아닙니다")

    weather_id, price_id = feature_ids
    await create_provider_feature(
        feature_id=weather_id,
        kind="weather",
        dataset_id=weather_dataset_id,
        record=weather_record,
        name=f"E2E suppressed weather {run_id}",
        lon=_LON + 0.002,
        marker_icon="weather",
        marker_color="P-03",
    )
    await create_provider_feature(
        feature_id=price_id,
        kind="price",
        dataset_id=price_dataset_id,
        record=price_record,
        name=f"E2E suppressed price {run_id}",
        lon=_LON - 0.002,
        marker_icon="fuel",
        marker_color="P-04",
    )
    await weather_repo.load_weather_values(
        session,
        [
            WeatherValue(
                feature_id=weather_id,
                provider="e2e-live-acceptance",
                weather_domain="kma_short_forecast",
                forecast_style="short",
                timeline_bucket="short",
                metric_key="TMP",
                metric_name="인수 기온",
                value_number=Decimal("21.5"),
                unit="deg_c",
                issued_at=now - timedelta(hours=1),
                valid_at=now,
                normalization_version="e2e-v1",
                payload={"fixture": "admin-feature-live-acceptance"},
            )
        ],
        provider_dataset_id=weather_dataset_id,
        source_record=weather_record,
        selected_at=now,
    )
    await price_repo.load_price_values(
        session,
        [
            PriceValue(
                feature_id=price_id,
                provider="e2e-live-acceptance",
                price_domain="opinet_gas_station",
                product_key="gasoline",
                product_name="인수 휘발유",
                value_number=Decimal("1711"),
                unit="KRW/L",
                observed_at=now,
                normalization_version="e2e-v1",
                payload={"fixture": "admin-feature-live-acceptance"},
            )
        ],
        provider_dataset_id=price_dataset_id,
        source_record=price_record,
    )
    observed, foreign_keys = await _assert_owned_state(session, run_id, feature_ids)
    if observed != {"features": 2, "weather_values": 1, "price_values": 1}:
        raise RuntimeError("owned weather/price fixture cardinality가 예상과 다릅니다")
    return observed, foreign_keys, await _owned_summary_run_ids(session, feature_ids)


async def _cleanup(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    feature_ids = _feature_ids(run_id)
    # Parent FOR UPDATE는 concurrent FK insert의 KEY SHARE와 충돌한다. 기존 child도
    # FOR UPDATE한 같은 transaction 안에서 fingerprint/FK audit/delete를 끝낸다.
    await _assert_owned_state(session, run_id, feature_ids, lock=True)
    await session.execute(
        text(
            """
            DELETE FROM feature.features
            WHERE (feature_id = :weather_id AND kind = 'weather')
               OR (feature_id = :price_id AND kind = 'price')
            """
        ),
        {"weather_id": feature_ids[0], "price_id": feature_ids[1]},
    )
    observed, foreign_keys = await _assert_owned_state(session, run_id, feature_ids)
    if observed != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned weather/price fixture cleanup이 완결되지 않았습니다")
    await _delete_owned_datasets(session, run_id)
    return observed, foreign_keys


async def _delete_owned_datasets(session: AsyncSession, run_id: str) -> None:
    """fixture response lineage와 dataset/policy를 feature 삭제 뒤 완전히 지운다."""

    dataset_keys = [_dataset_key(run_id, kind) for kind in ("weather", "price")]
    params = {"provider": _E2E_PROVIDER, "dataset_keys": dataset_keys}
    source_links_remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM provider_sync.source_links AS link
                    JOIN provider_sync.source_entities AS entity
                      ON entity.source_entity_key = link.source_entity_key
                    JOIN provider_sync.provider_datasets AS dataset
                      ON dataset.provider_dataset_id = entity.provider_dataset_id
                    WHERE dataset.provider = :provider
                      AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
                    """
                ),
                params,
            )
        )
        .scalars()
        .one()
    )
    if source_links_remaining:
        raise RuntimeError(
            "owned fixture source link cleanup이 완결되지 않아 dataset 삭제를 중단합니다"
        )
    # 0091의 entity-head 완결성 trigger 때문에 head → record → entity 순서가
    # 필수다. dataset은 모든 raw 계보와 policy가 사라진 뒤에만 지운다.
    for statement in (
        """
        DELETE FROM provider_sync.source_entity_heads AS head
        USING provider_sync.source_entities AS entity,
              provider_sync.provider_datasets AS dataset
        WHERE head.source_entity_key = entity.source_entity_key
          AND entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.source_records AS record
        USING provider_sync.source_entities AS entity,
              provider_sync.provider_datasets AS dataset
        WHERE record.source_entity_key = entity.source_entity_key
          AND entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.source_entities AS entity
        USING provider_sync.provider_datasets AS dataset
        WHERE entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM ops.provider_refresh_policies AS policy
        USING provider_sync.provider_datasets AS dataset
        WHERE policy.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.provider_datasets
        WHERE provider = :provider
          AND dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
    ):
        await session.execute(text(statement), params)
    remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM provider_sync.provider_datasets
                    WHERE provider = :provider
                      AND dataset_key = ANY(CAST(:dataset_keys AS text[]))
                    """
                ),
                params,
            )
        )
        .scalars()
        .one()
    )
    if remaining:
        raise RuntimeError("owned fixture provider dataset cleanup이 완결되지 않았습니다")


class _ApiOwnedInspection(NamedTuple):
    """live spec이 남긴 API-owned 행의 관측 결과.

    ``transition_chains``/``override_field_paths``/``command_operations``는 구조
    판정용이고, 개수 필드는 완료 감사(`_audit_complete_api_owned`)와 clone
    evidence가 쓴다.
    """

    feature_ids: tuple[str, ...]
    feature_uuids: tuple[str, ...]
    features: int
    field_overrides: int
    override_field_paths: frozenset[str]
    state_transitions: int
    transition_chains: dict[str, tuple[tuple[str, str], ...]]
    domain_commands: int
    command_operations: Counter[str]
    foreign_keys: dict[str, int]


_API_OWNED_FEATURE_SQL: Final[str] = """
SELECT
  feature_id, CAST(feature_uuid AS text) AS feature_uuid,
  kind, name, category,
  lifecycle_state, publication_state, quality_state,
  marker_icon, marker_color, coord_precision_digits,
  x_extension.ST_X(coord) AS lon,
  x_extension.ST_Y(coord) AS lat
FROM feature.features
WHERE name = :fixture_name
ORDER BY feature_id
FOR UPDATE
"""

# 전이 감사는 append-only trigger가 UPDATE/DELETE를 막으므로 잠글 대상이 아니다.
# Feature 행을 FOR UPDATE로 잡은 뒤 읽으면 같은 transaction 안에서 일관된다.
_API_OWNED_TRANSITION_SQL: Final[str] = """
SELECT
  feature_id, CAST(feature_uuid AS text) AS feature_uuid,
  from_lifecycle_state, from_publication_state, from_quality_state,
  to_lifecycle_state, to_publication_state, to_quality_state,
  transition_kind, reason_code, principal, causation_ref,
  provider_dataset_id, source_entity_key, source_record_key, provider_evidence
FROM feature.feature_state_transitions
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
ORDER BY feature_id, occurred_at, transition_id
"""

_API_OWNED_OVERRIDE_SQL: Final[str] = """
SELECT
  feature_id, field_path, status, reason, created_by, command_id,
  base_revision, prevent_provider_reactivation,
  revoked_at, revoked_by, revoked_reason,
  source_record_key, source_provider_dataset_id, source_entity_key,
  source_raw_payload_hash
FROM ops.feature_overrides
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
ORDER BY feature_id, field_path
FOR UPDATE
"""

# domain command receipt에는 feature 열이 없다. terminal response의
# ``data.feature_id``가 admin mutation 계약상 **feature UUID**이므로
# (``_field_override_response``/``_state_response``) 그 값만이 run-owned 명령을
# 정확히 식별한다.
_API_OWNED_COMMAND_SQL: Final[str] = """
SELECT
  command.command_id, command.actor, command.operation,
  result.response_status,
  result.response_body #>> '{data,feature_id}' AS subject_feature_uuid
FROM ops.domain_commands AS command
JOIN ops.domain_command_results AS result
  ON result.command_id = command.command_id
WHERE result.response_body #>> '{data,feature_id}'
      = ANY(CAST(:feature_uuids AS text[]))
ORDER BY command.command_id
"""


def _state_tuple(
    row: RowMapping,
    prefix: str,
) -> tuple[str | None, str | None, str | None]:
    return (
        row[f"{prefix}_lifecycle_state"],
        row[f"{prefix}_publication_state"],
        row[f"{prefix}_quality_state"],
    )


async def _inspect_api_owned(
    session: AsyncSession,
    run_id: str,
) -> _ApiOwnedInspection:
    """run이 만든 API-owned 행의 소유권과 구조를 검사한다.

    이 함수는 **부분 진행도 허용한다** — recovery lane이 중단된 run을 정리한 뒤
    hard purge를 부르는 경로에서도 같은 검사를 쓰기 때문이다. "정확히 이 집합만
    있다"는 완료 판정은 `_audit_complete_api_owned`가 따로 한다.
    """

    fixture_name = _admin_fixture_name(run_id)
    reason_prefix = _admin_reason_prefix(run_id)
    expected_feature_id = _admin_fixture_feature_id(run_id)
    rows = (
        await session.execute(
            text(_API_OWNED_FEATURE_SQL),
            {"fixture_name": fixture_name},
        )
    ).mappings().all()
    if len(rows) > 1:
        raise RuntimeError("API-owned fixture 이름에 Feature가 둘 이상 있습니다")
    feature_states: dict[str, tuple[str, str, str]] = {}
    feature_uuid_by_id: dict[str, str] = {}
    for row in rows:
        feature_id = str(row["feature_id"])
        if (
            feature_id != expected_feature_id
            or row["kind"] != _ADMIN_FIXTURE_KIND
            or row["category"] != _ADMIN_FIXTURE_CATEGORY
            or row["marker_icon"] != _ADMIN_FIXTURE_MARKER_ICON
            or row["marker_color"] != _ADMIN_FIXTURE_MARKER_COLOR
            or row["coord_precision_digits"] != _ADMIN_FIXTURE_COORD_PRECISION_DIGITS
            # cleanup/recovery lane은 소유 Feature를 반드시 retire까지 끌고 간다.
            # audit/purge는 그 뒤에만 돈다.
            or row["lifecycle_state"] != "retired"
            or row["publication_state"] != "suppressed"
            or row["quality_state"] != "valid"
            or row["lon"] is None
            or row["lat"] is None
            or not math.isclose(float(row["lon"]), _LON, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(float(row["lat"]), _LAT, rel_tol=0, abs_tol=1e-9)
        ):
            raise RuntimeError("API-owned Feature fingerprint가 다릅니다")
        feature_states[feature_id] = (
            str(row["lifecycle_state"]),
            str(row["publication_state"]),
            str(row["quality_state"]),
        )
        feature_uuid_by_id[feature_id] = str(row["feature_uuid"])
    feature_ids = tuple(feature_states)
    feature_uuids = tuple(feature_uuid_by_id[key] for key in feature_ids)

    transition_rows = (
        await session.execute(
            text(_API_OWNED_TRANSITION_SQL),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings().all()
    allowed_transition_reasons = {
        f"{reason_prefix}:{suffix}" for suffix in ("suppress", "retire", "cleanup")
    }
    chains: dict[str, list[tuple[str, str]]] = {}
    final_state: dict[str, tuple[str | None, str | None, str | None]] = {}
    create_command_ids: dict[str, int] = {}
    for transition in transition_rows:
        feature_id = str(transition["feature_id"])
        if feature_id not in feature_states:
            raise RuntimeError("API-owned 전이가 소유하지 않은 Feature를 가리킵니다")
        if (
            transition["principal"] != _ADMIN_OPERATOR
            or transition["feature_uuid"] != feature_uuid_by_id[feature_id]
            # provider provenance 열은 provider_sync 전이 전용이다.
            or transition["provider_dataset_id"] is not None
            or transition["source_entity_key"] is not None
            or transition["source_record_key"] is not None
            or transition["provider_evidence"] is not None
        ):
            raise RuntimeError("API-owned 전이 소유권이 다릅니다")
        from_state = _state_tuple(transition, "from")
        to_state = _state_tuple(transition, "to")
        kind = str(transition["transition_kind"])
        reason_code = str(transition["reason_code"])
        chain = chains.setdefault(feature_id, [])
        if not chain:
            # create procedure가 쓰는 initial 전이. reason_code는 run reason이
            # 아니라 서버 상수이고, 유일하게 domain command receipt를 역참조한다.
            command_match = _CAUSATION_COMMAND_RE.fullmatch(
                str(transition["causation_ref"] or "")
            )
            if (
                kind != "initial"
                or reason_code != _ADMIN_CREATE_TRANSITION_REASON
                or from_state != (None, None, None)
                or to_state != ("active", "published", "valid")
                or command_match is None
            ):
                raise RuntimeError("API-owned Feature의 최초 전이가 create 계약과 다릅니다")
            create_command_ids[feature_id] = int(command_match.group(1))
        elif (
            kind != "admin"
            or reason_code not in allowed_transition_reasons
            # admin state 명령은 causation_ref를 남기지 않는다
            # (`transition_admin_feature_state`의 state context).
            or transition["causation_ref"] is not None
            or from_state != final_state[feature_id]
        ):
            raise RuntimeError("API-owned 전이 사슬이 예상과 다릅니다")
        final_state[feature_id] = to_state
        chain.append((kind, reason_code))
    for feature_id, state in feature_states.items():
        if feature_id not in chains:
            raise RuntimeError("API-owned Feature에 상태 전이 이력이 없습니다")
        if final_state[feature_id] != state:
            raise RuntimeError("API-owned 전이 사슬의 끝이 현재 상태와 다릅니다")

    override_rows = (
        await session.execute(
            text(_API_OWNED_OVERRIDE_SQL),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings().all()
    override_field_paths: set[str] = set()
    seen_override_keys: set[tuple[str, str]] = set()
    for override in override_rows:
        feature_id = str(override["feature_id"])
        field_path = str(override["field_path"])
        is_retire_override = field_path == _ADMIN_RETIRE_OVERRIDE_FIELD_PATH
        if is_retire_override:
            # retire가 authoring하는 lifecycle override. field override와 달리
            # 재적재 잠금을 세우고 command_id를 남기지 않는다.
            expected_reason = f"{reason_prefix}:retire"
            expected_command_id = None
            expected_prevent = True
        else:
            expected_reason = f"{reason_prefix}:create"
            expected_command_id = create_command_ids.get(feature_id)
            expected_prevent = False
        if (
            feature_id not in feature_states
            or (
                not is_retire_override
                and field_path not in _ADMIN_CREATE_OVERRIDE_FIELD_PATHS
            )
            or (feature_id, field_path) in seen_override_keys
            or override["status"] != "active"
            or override["created_by"] != _ADMIN_OPERATOR
            or override["reason"] != expected_reason
            or override["command_id"] != expected_command_id
            or override["prevent_provider_reactivation"] is not expected_prevent
            or override["revoked_at"] is not None
            or override["revoked_by"] is not None
            or override["revoked_reason"] is not None
            # user-created Feature에는 provider base가 없다 — override는 source
            # 계보를 갖지 않는다.
            or override["source_record_key"] is not None
            or override["source_provider_dataset_id"] is not None
            or override["source_entity_key"] is not None
            or override["source_raw_payload_hash"] is not None
        ):
            raise RuntimeError("API-owned field override 소유권이 다릅니다")
        seen_override_keys.add((feature_id, field_path))
        override_field_paths.add(field_path)

    command_rows = (
        await session.execute(
            text(_API_OWNED_COMMAND_SQL),
            {"feature_uuids": list(feature_uuids)},
        )
    ).mappings().all()
    command_operations: Counter[str] = Counter()
    observed_create_commands: dict[str, int] = {}
    uuid_to_feature_id = {value: key for key, value in feature_uuid_by_id.items()}
    for command in command_rows:
        operation = str(command["operation"])
        subject = str(command["subject_feature_uuid"])
        if (
            command["actor"] != _ADMIN_OPERATOR
            or operation not in {_ADMIN_CREATE_OPERATION, _ADMIN_STATE_OPERATION}
            or command["response_status"] != 200
            or subject not in uuid_to_feature_id
        ):
            raise RuntimeError("API-owned domain command receipt 소유권이 다릅니다")
        if operation == _ADMIN_CREATE_OPERATION:
            feature_id = uuid_to_feature_id[subject]
            if feature_id in observed_create_commands:
                raise RuntimeError("API-owned Feature에 create command가 둘 이상입니다")
            observed_create_commands[feature_id] = int(command["command_id"])
        command_operations[operation] += 1
    if observed_create_commands != create_command_ids:
        raise RuntimeError("create 전이의 causation receipt가 domain command와 다릅니다")

    foreign_keys = await _foreign_key_reference_counts(session, feature_ids)
    expected_references: dict[str, int] = {}
    if rows:
        # feature INSERT trigger가 canonical alias를 함께 만든다. subtype
        # (`feature.feature_places`)은 composite FK라 이 단일 열 감사에 잡히지
        # 않는다 — 그쪽은 Feature 삭제 시 같은 CASCADE로 사라진다.
        expected_references["feature.feature_aliases.feature_id"] = len(rows)
    if override_rows:
        expected_references["ops.feature_overrides.feature_id"] = len(override_rows)
    observed_references = {key: value for key, value in foreign_keys.items() if value}
    if observed_references != expected_references:
        raise RuntimeError(
            "API-owned Feature FK reference 감사가 다릅니다: "
            f"expected={expected_references!r}, observed={observed_references!r}"
        )
    return _ApiOwnedInspection(
        feature_ids=feature_ids,
        feature_uuids=feature_uuids,
        features=len(rows),
        field_overrides=len(override_rows),
        override_field_paths=frozenset(override_field_paths),
        state_transitions=len(transition_rows),
        transition_chains={
            feature_id: tuple(chain) for feature_id, chain in chains.items()
        },
        domain_commands=len(command_rows),
        command_operations=command_operations,
        foreign_keys=foreign_keys,
    )


async def _purge_api_owned(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    inspection = await _inspect_api_owned(session, run_id)
    # ``ops.feature_overrides``/``feature.feature_aliases``/subtype은 모두
    # ON DELETE CASCADE라 Feature 삭제 한 번으로 사라진다. 0104 이전에 필요했던
    # change request 선삭제 단계는 그 표가 없어져 사라졌다.
    await session.execute(
        text(
            """
            DELETE FROM feature.features
            WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
            """
        ),
        {"feature_ids": list(inspection.feature_ids)},
    )
    remaining = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM feature.features
                   WHERE feature_id = ANY(CAST(:feature_ids AS text[])))
                    AS features,
                  (SELECT count(*) FROM ops.feature_overrides
                   WHERE feature_id = ANY(CAST(:feature_ids AS text[])))
                    AS field_overrides,
                  (SELECT count(*) FROM feature.feature_state_transitions
                   WHERE feature_id = ANY(CAST(:feature_ids AS text[])))
                    AS state_transitions
                """
            ),
            {"feature_ids": list(inspection.feature_ids)},
        )
    ).mappings().one()
    if int(remaining["features"]) or int(remaining["field_overrides"]):
        raise RuntimeError("API-owned purge가 완결되지 않았습니다")
    # 상태 전이 감사는 append-only trigger가 지키는 **의도적 잔존물**이고 Feature
    # FK도 없다(T39 UUID identity 증거). 그대로 남았음을 확인해 "purge가 감사를
    # 훼손하지 않았다"까지 증명한다.
    if int(remaining["state_transitions"]) != inspection.state_transitions:
        raise RuntimeError("append-only 상태 전이 감사가 purge로 훼손되었습니다")
    remaining_foreign_keys = await _foreign_key_reference_counts(
        session,
        inspection.feature_ids,
    )
    if any(remaining_foreign_keys.values()):
        raise RuntimeError("API-owned purge 뒤 FK reference가 남았습니다")
    return (
        {"features": 0, "price_values": 0, "weather_values": 0},
        remaining_foreign_keys,
        {
            "features": inspection.features,
            "field_overrides": inspection.field_overrides,
        },
    )


def _expected_transition_chain(run_id: str) -> tuple[tuple[str, str], ...]:
    """live spec 한 번의 실행이 남기는 정확한 전이 사슬.

    spec은 Feature 하나에 대해 create → ``PATCH state {action:"patch",
    publication_state:"suppressed"}`` → ``PATCH state {action:"retire"}``만
    실행한다. 마지막 ``cleanupOwnedFeatures``는 이미 retired인 Feature를 건너뛰고
    (`retireFeature`의 조기 반환), field override authoring은 3축을 건드리지
    않아 감사 trigger의 no-op 가드에 걸린다 — 그래서 전이는 정확히 셋이다.
    """

    reason_prefix = _admin_reason_prefix(run_id)
    return (
        ("initial", _ADMIN_CREATE_TRANSITION_REASON),
        ("admin", f"{reason_prefix}:suppress"),
        ("admin", f"{reason_prefix}:retire"),
    )


async def _audit_complete_api_owned(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int], tuple[str, ...]]:
    inspection = await _inspect_api_owned(session, run_id)
    expected_chain = _expected_transition_chain(run_id)
    feature_id = _admin_fixture_feature_id(run_id)
    # 명령 수는 spec이 실제로 보내는 mutation 수에서 유도한다: create 1건 +
    # state PATCH 2건. GET은 domain command를 만들지 않고, 마지막 cleanup도
    # 이미 retired면 명령을 만들지 않는다.
    expected_operations = Counter(
        {_ADMIN_CREATE_OPERATION: 1, _ADMIN_STATE_OPERATION: 2}
    )
    if (
        inspection.features != 1
        or inspection.feature_ids != (feature_id,)
        or inspection.transition_chains != {feature_id: expected_chain}
        or inspection.state_transitions != len(expected_chain)
        # create가 만드는 field override 6개 + retire가 만드는 lifecycle override 1개.
        or inspection.override_field_paths != _EXPECTED_OVERRIDE_FIELD_PATHS
        or inspection.field_overrides != len(_EXPECTED_OVERRIDE_FIELD_PATHS)
        or inspection.command_operations != expected_operations
        or inspection.domain_commands != sum(expected_operations.values())
    ):
        raise RuntimeError("완료 API-owned 행 집합이 예상과 다릅니다")
    return (
        {
            "domain_commands": inspection.domain_commands,
            "features": inspection.features,
            "field_overrides": inspection.field_overrides,
            "state_transitions": inspection.state_transitions,
        },
        inspection.foreign_keys,
        inspection.feature_uuids,
    )


def _auth_request_ids(run_id: str) -> dict[str, str]:
    prefix = f"e2e_live_acceptance::{run_id}::auth"
    return {
        "main": f"{prefix}::main",
        "recovery": f"{prefix}::recovery",
    }


async def _inspect_auth_audit(
    session: AsyncSession,
    run_id: str,
) -> tuple[list[RowMapping], dict[str, int]]:
    request_ids = _auth_request_ids(run_id)
    auth_rows = (
        await session.execute(
            text(
                """
                SELECT
                  auth_event_id, event_type, outcome, attempted_username,
                  actor, reason, next_path, client_ip, user_agent, request_id
                FROM ops.admin_auth_events
                WHERE request_id = ANY(CAST(:request_ids AS text[]))
                ORDER BY created_at, auth_event_id
                FOR UPDATE
                """
            ),
            {"request_ids": list(request_ids.values())},
        )
    ).mappings().all()
    counts = {"main": 0, "recovery": 0}
    for row in auth_rows:
        if (
            row["event_type"] != "login"
            or row["outcome"] != "succeeded"
            or row["attempted_username"] != "admin"
            or row["actor"] != "ui-auth"
            or row["reason"] != "authenticated"
            or row["next_path"] != "/"
            or row["client_ip"] is not None
            or row["request_id"] not in request_ids.values()
            or not isinstance(row["user_agent"], str)
            or not row["user_agent"].startswith("Mozilla/5.0 ")
        ):
            raise RuntimeError("run-bound admin 인증 감사행 소유권이 다릅니다")
        phase = "main" if row["request_id"] == request_ids["main"] else "recovery"
        counts[phase] += 1
    return list(auth_rows), counts


async def _reset_auth_audit(session: AsyncSession, run_id: str) -> dict[str, int]:
    auth_rows, counts = await _inspect_auth_audit(session, run_id)
    if auth_rows:
        await session.execute(
            text(
                """
                DELETE FROM ops.admin_auth_events
                WHERE auth_event_id = ANY(CAST(:auth_event_ids AS uuid[]))
                """
            ),
            {"auth_event_ids": [str(row["auth_event_id"]) for row in auth_rows]},
        )
    remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM ops.admin_auth_events
                    WHERE request_id = ANY(CAST(:request_ids AS text[]))
                    """
                ),
                {"request_ids": list(_auth_request_ids(run_id).values())},
            )
        )
        .scalars()
        .one()
    )
    if remaining:
        raise RuntimeError("run-bound admin 인증 감사행 reset이 완결되지 않았습니다")
    return counts


async def _verify_auth_audit(
    session: AsyncSession,
    run_id: str,
) -> dict[str, int]:
    _auth_rows, counts = await _inspect_auth_audit(session, run_id)
    if counts != {"main": 1, "recovery": 1}:
        raise RuntimeError("run-bound admin 인증 감사행 수가 예상과 다릅니다")
    return counts


def _required_fixture_target() -> tuple[str, str, str]:
    """별도 writer DSN이 API/browser lane과 같은 DB를 가리키는지 확인할 입력.

    DSN 자체를 journal이나 argv로 남기지 않고, caller가 root shell에서 읽은 세
    비민감 식별자만 helper에 전달한다. 하나라도 없으면 role 전환 전 멈춘다.
    """

    names = (
        _FIXTURE_CONFIRM_DATABASE_ENV,
        _FIXTURE_CONFIRM_LOGIN_ROLE_ENV,
        _FIXTURE_CONFIRM_ALEMBIC_REVISION_ENV,
    )
    values: list[str] = []
    for name in names:
        value = os.environ.get(name)
        if not value or "\0" in value:
            raise RuntimeError(f"fixture target confirmation is missing: {name}")
        values.append(value)
    return values[0], values[1], values[2]


async def _prepare_fixture_connection(connection: AsyncConnection) -> None:
    """mutation 전 fixture writer DB·LOGIN role·head·effective role을 fail-close한다."""

    expected_database, expected_login_role, expected_revision = _required_fixture_target()
    observed = (
        await connection.execute(
            text(
                """
                SELECT
                    current_database() AS database_name,
                    session_user AS session_user,
                    current_user AS current_user,
                    (SELECT version_num FROM public.alembic_version)
                        AS alembic_revision
                """
            )
        )
    ).mappings().one()
    if observed["database_name"] != expected_database:
        raise RuntimeError("fixture target database confirmation mismatch")
    if observed["session_user"] != expected_login_role:
        raise RuntimeError("fixture target login-role confirmation mismatch")
    if observed["current_user"] != expected_login_role:
        raise RuntimeError("fixture target initial effective-role mismatch")
    if observed["alembic_revision"] != expected_revision:
        raise RuntimeError("fixture target Alembic revision confirmation mismatch")

    await connection.execute(text(f"SET ROLE {_FIXTURE_SCHEMA_OWNER}"))
    effective_role = (
        await connection.execute(text("SELECT current_user"))
    ).scalar_one()
    if effective_role != _FIXTURE_SCHEMA_OWNER:
        raise RuntimeError("fixture schema-owner role assumption failed")
    # SET ROLE is session state. Persist only this read-only setup transaction;
    # every fixture action itself is in the following explicit transaction.
    await connection.commit()


async def _run(
    action: str,
    run_id: str,
) -> dict[str, object]:
    settings = KorTravelMapSettings()
    # make_async_engine은 normalize_async_dsn으로 plain `postgresql://` DSN도
    # asyncpg dialect로 정규화한다. raw create_async_engine을 쓰면 배포 env가
    # plain scheme일 때 컨테이너 안에서 sync psycopg2 dialect를 로드하려다
    # 실패한다 (Codex PR #792 사후 적대 리뷰 R792-3).
    engine = make_async_engine(settings.pg_dsn)
    try:
        # The supervisor replaces the API container's read-only DSN with the
        # root-only fixture DSN. Before any role change or mutation, prove that
        # this separate writer connection is the confirmed API target at the
        # confirmed schema head. No application runtime role receives writes.
        async with engine.connect() as connection:
            await _prepare_fixture_connection(connection)
            async with AsyncSession(bind=connection) as session, session.begin():
                summary_run_ids: tuple[int, int] | None = None
                api_owned_feature_uuids: tuple[str, ...] = ()
                if action == "seed":
                    counts, foreign_keys, summary_run_ids = await _seed(session, run_id)
                elif action == "cleanup":
                    counts, foreign_keys = await _cleanup(session, run_id)
                elif action == "purge":
                    counts, foreign_keys, purged = await _purge_api_owned(
                        session,
                        run_id,
                    )
                elif action == "api-audit":
                    (
                        counts,
                        foreign_keys,
                        api_owned_feature_uuids,
                    ) = await _audit_complete_api_owned(session, run_id)
                elif action == "auth-reset":
                    auth_counts = await _reset_auth_audit(session, run_id)
                elif action == "auth-verify":
                    auth_counts = await _verify_auth_audit(session, run_id)
                else:
                    counts, foreign_keys = await _assert_owned_state(
                        session,
                        run_id,
                        _feature_ids(run_id),
                    )
    finally:
        await engine.dispose()
    if action in {"auth-reset", "auth-verify"}:
        return {
            "action": action,
            "counts": auth_counts,
            "version": 1,
        }
    result: dict[str, object] = {
        "action": action,
        "counts": counts,
        "foreign_key_constraints_checked": len(foreign_keys),
        "foreign_key_references": sum(foreign_keys.values()),
        "version": 1,
    }
    if action == "seed":
        if summary_run_ids is None:
            raise AssertionError("seed summary receipt result disappeared")
        result["summary_run_ids"] = list(summary_run_ids)
    if action == "api-audit":
        # clone 러너의 content digest는 run-owned ``ops.domain_commands`` receipt를
        # 제외해야 한다. 그 표에는 feature 열이 없고 terminal response가 담는
        # 식별자는 **feature UUID**뿐이라, 감사가 관측한 UUID를 evidence로 넘긴다.
        result["feature_uuids"] = list(api_owned_feature_uuids)
    if action == "purge":
        result["purged"] = purged
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "seed",
            "cleanup",
            "audit",
            "purge",
            "api-audit",
            "auth-reset",
            "auth-verify",
        ),
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise SystemExit("run-id 형식이 올바르지 않습니다")
    print(
        json.dumps(
            asyncio.run(_run(args.action, args.run_id)),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
