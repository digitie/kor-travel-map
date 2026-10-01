"""migration 402가 weather 데이터·weather 전용 스키마를 지우고 나머지를 건드리지 않는지.

ADR-105: Map은 ``weather`` kind Feature의 기능을 전부 내려놓고, 기상 출처 notice
(provider ``python-kma-api``가 내는 notice)도 함께 내려놓는다. 정의(kind 값·capabilities
값·identity kind CHECK)는 남는다.

이 파일은 **401까지 올린 빈 DB**에 실제와 같은 모양의 데이터를 심고 402를 올린다.
심는 것은 seed 카탈로그의 실제 dataset이다(이름이 아니라 정체성으로 고른다는 migration
규칙을 실제 카탈로그 위에서 잰다).

- 지워져야 하는 것: weather Feature 둘(KMA 단기예보·KREX 휴게소 기상 — 출처 무관),
  KMA 기상특보 notice 하나, 그리고 그 의존 행 전부(fact·summary·summary run·source
  lineage·identity·alias·override·dedup 큐·integrity finding·notice lifecycle).
- 남아야 하는 것: place 하나, KREX 교통 notice, 산림청 산사태 notice(산림청 hazard는
  기상 출처가 아니다), price summary run, 다른 dataset 카탈로그 — **행 단위로 같아야**
  한다.

"검사는 한 번 빨갛게 만든다": 지워짐을 재는 탐침은 401에서 **전부 0이 아님**을 먼저
확인한다. 같은 탐침이 402 뒤 0이어야 한다 — 401에서 0이었다면 그 탐침은 아무것도 재지
않는 항진명제다.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from alembic.config import Config

from alembic import command
from kortravelmap.infra.db import normalize_async_dsn
from tests.integration._application_300_bootstrap import (
    alembic_schema_owner_role,
    bootstrapped_application_300_migrator_dsn,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_MIGRATION_PATH: Final = _ROOT / "alembic" / "versions" / "402_remove_map_weather_data.py"
_BEFORE: Final = "401_retire_map_kma_refresh"
_AFTER: Final = "402_remove_map_weather_data"

_T0: Final = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

#: (provider, dataset_key) — seed 카탈로그의 실제 dataset.
_KMA_SHORT: Final = ("python-kma-api", "kma_short_forecast")
_KREX_WEATHER: Final = ("python-krex-api", "krex_rest_area_weather")
_KMA_ALERTS: Final = ("python-kma-api", "kma_weather_alerts")
_KREX_PLACE: Final = ("python-krex-api", "krex_rest_areas")
_KREX_TRAFFIC: Final = ("python-krex-api", "krex_traffic_notices")
_LANDSLIDE: Final = ("python-krforest-api", "krforest_landslide_forecast_issues")

#: migration과 같은 정체성 규칙. 테스트가 이름 목록을 들지 않는다.
_TARGET_DATASETS_SQL: Final = """
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE (dataset.capabilities -> 'produces') @> '["weather"]'::jsonb
    OR ((dataset.capabilities -> 'produces') @> '["notice"]'::jsonb
        AND dataset.provider = 'python-kma-api')
"""


# ---------------------------------------------------------------------------
# DB 수명
# ---------------------------------------------------------------------------


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _connect(url: str) -> Any:
    import asyncpg

    parts = urlsplit(url)
    return await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )


async def _admin_execute(url: str, statement: str) -> None:
    connection = await _connect(url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


@pytest.fixture
async def db_at_401(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """fresh DB를 배포 경로(bootstrap → migrator → schema owner)로 **401까지만** 올린다.

    돌려주는 것은 (402를 올릴 Config, superuser DSN)이다. 데이터는 superuser로 심는다 —
    상태 전이 감사 트리거가 superuser 직접 쓰기만 fixture seeding으로 허용한다.
    """

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"weather_removal_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    superuser_dsn = _with_database(raw_dsn, database)
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    try:
        config.set_main_option(
            "sqlalchemy.url",
            await bootstrapped_application_300_migrator_dsn(normalize_async_dsn(superuser_dsn)),
        )
        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, config, _BEFORE)
        yield config, superuser_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


async def _upgrade_to_402(config: Config) -> None:
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, _AFTER)


async def _version(connection: Any) -> str:
    return str(await connection.fetchval("SELECT version_num FROM public.alembic_version"))


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


async def _dataset_id(connection: Any, identity: tuple[str, str]) -> int:
    value = await connection.fetchval(
        "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
        "WHERE provider = $1 AND dataset_key = $2",
        *identity,
    )
    assert value is not None, f"seed 카탈로그에 {identity}가 없다 — 이 검사의 전제가 깨졌다"
    return int(value)


async def _seed_source(
    connection: Any,
    *,
    dataset_id: int,
    key: str,
    entity_type: str,
    raw: str = "{}",
) -> str:
    """entity·record·head 한 벌. record key를 돌려준다."""

    record_key = f"{key}-record"
    await connection.execute(
        """
        INSERT INTO provider_sync.source_entities (
            source_entity_key, source_entity_type, source_entity_id,
            first_seen_at, last_seen_at, provider_dataset_id
        ) VALUES ($1, $2, $1, $3, $3, $4)
        """,
        key,
        entity_type,
        _T0,
        dataset_id,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_records (
            source_record_key, raw_data, raw_payload_hash, fetched_at, source_entity_key
        ) VALUES ($1, $2::jsonb, $3, $4, $5)
        """,
        record_key,
        raw,
        hashlib.sha256(record_key.encode()).hexdigest(),
        _T0,
        key,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_entity_heads (
            source_entity_key, current_source_record_key, observed_at
        ) VALUES ($1, $2, $3)
        """,
        key,
        record_key,
        _T0,
    )
    return record_key


async def _seed_feature(
    connection: Any,
    *,
    feature_id: UUID,
    kind: str,
    dataset_id: int,
    entity_key: str,
) -> None:
    """core + (notice면) subtype + identity claim + primary link."""

    await connection.execute(
        "INSERT INTO feature.features (feature_id, kind, name, category) "
        "VALUES ($1, $2, $3, '00000000')",
        feature_id,
        kind,
        f"402 {kind} {entity_key}",
    )
    if kind == "notice":
        await connection.execute(
            "INSERT INTO feature.feature_notices (feature_id, kind, notice_type, severity) "
            "VALUES ($1, 'notice', 'test', 2)",
            feature_id,
        )
    await connection.execute(
        """
        INSERT INTO provider_sync.provider_feature_identities (
            provider_dataset_id, feature_kind, natural_key, feature_id, bound_by_operation
        ) VALUES ($1, $2, $3, $4, 'provider_sync')
        """,
        dataset_id,
        kind,
        entity_key,
        feature_id,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_role, match_method, confidence, source_entity_key
        ) VALUES ($1, 'primary', 'provider_key', 100, $2)
        """,
        feature_id,
        entity_key,
    )


async def _seed_notice_lifecycle(
    connection: Any, *, dataset_id: int, entity_type: str, lineage_key: str
) -> None:
    scope_id = await connection.fetchval(
        """
        INSERT INTO provider_sync.notice_lifecycle_scopes (
            source_entity_type, mode, applied_at, state_fingerprint, provider_dataset_id
        ) VALUES ($1, 'snapshot', $2, $3, $4)
        RETURNING notice_lifecycle_scope_id
        """,
        entity_type,
        _T0,
        hashlib.sha256(lineage_key.encode()).hexdigest(),
        dataset_id,
    )
    await connection.execute(
        """
        INSERT INTO provider_sync.notice_lineage_states (
            lineage_key, present, changed_at, notice_lifecycle_scope_id
        ) VALUES ($1, true, $2, $3)
        """,
        lineage_key,
        _T0,
        scope_id,
    )


class _Seeded:
    """심은 행의 식별자."""

    def __init__(self) -> None:
        self.weather_kma = uuid4()
        self.weather_krex = uuid4()
        self.kma_alert = uuid4()
        self.place = uuid4()
        self.traffic = uuid4()
        self.landslide = uuid4()
        self.kma_entity = f"402-kma-short-{uuid4().hex[:8]}"
        self.krex_weather_entity = f"402-krex-weather-{uuid4().hex[:8]}"
        self.alert_entity = f"402-kma-alert-{uuid4().hex[:8]}"
        self.place_entity = f"402-krex-place-{uuid4().hex[:8]}"
        self.traffic_entity = f"402-krex-traffic-{uuid4().hex[:8]}"
        self.landslide_entity = f"402-krforest-landslide-{uuid4().hex[:8]}"
        self.weather_item: UUID | None = None
        self.place_item: UUID | None = None

    @property
    def kept_features(self) -> list[UUID]:
        return [self.place, self.traffic, self.landslide]

    @property
    def kept_entities(self) -> list[str]:
        return [self.place_entity, self.traffic_entity, self.landslide_entity]


async def _seed_population(connection: Any) -> _Seeded:
    seeded = _Seeded()
    kma_short = await _dataset_id(connection, _KMA_SHORT)
    krex_weather = await _dataset_id(connection, _KREX_WEATHER)
    kma_alerts = await _dataset_id(connection, _KMA_ALERTS)
    krex_place = await _dataset_id(connection, _KREX_PLACE)
    krex_traffic = await _dataset_id(connection, _KREX_TRAFFIC)
    landslide = await _dataset_id(connection, _LANDSLIDE)

    async with connection.transaction():
        # --- 지워질 것 ---------------------------------------------------------
        kma_record = await _seed_source(
            connection, dataset_id=kma_short, key=seeded.kma_entity, entity_type="grid_forecast"
        )
        await _seed_feature(
            connection,
            feature_id=seeded.weather_kma,
            kind="weather",
            dataset_id=kma_short,
            entity_key=seeded.kma_entity,
        )
        await _seed_source(
            connection,
            dataset_id=krex_weather,
            key=seeded.krex_weather_entity,
            entity_type="rest_area_weather",
        )
        await _seed_feature(
            connection,
            feature_id=seeded.weather_krex,
            kind="weather",
            dataset_id=krex_weather,
            entity_key=seeded.krex_weather_entity,
        )
        await _seed_source(
            connection,
            dataset_id=kma_alerts,
            key=seeded.alert_entity,
            entity_type="weather_alert",
            raw='{"region_code": "L1100100", "phenomenon": "호우"}',
        )
        await _seed_feature(
            connection,
            feature_id=seeded.kma_alert,
            kind="notice",
            dataset_id=kma_alerts,
            entity_key=seeded.alert_entity,
        )
        await _seed_notice_lifecycle(
            connection,
            dataset_id=kma_alerts,
            entity_type="weather_alert",
            lineage_key="L1100100::호우",
        )

        # weather fact → summary run → current summary
        await connection.execute(
            """
            INSERT INTO feature.feature_weather_values (
                weather_value_key, feature_id, provider_dataset_id, weather_domain,
                forecast_style, metric_key, value_number, target_at, known_at,
                source_entity_key, source_record_key
            ) VALUES ($1, $2, $3, 'forecast', 'short', 'TMP', 21.5, $4, $5, $6, $7)
            """,
            f"{seeded.kma_entity}-fact",
            seeded.weather_kma,
            kma_short,
            _T0 + timedelta(hours=3),
            _T0,
            seeded.kma_entity,
            kma_record,
        )
        weather_run = await connection.fetchval(
            """
            INSERT INTO ops.current_summary_runs (
                projection_kind, run_kind, status, started_at, finished_at
            ) VALUES ('weather', 'reconcile', 'succeeded', $1, $2)
            RETURNING summary_run_id
            """,
            _T0,
            _T0 + timedelta(minutes=1),
        )
        await connection.execute(
            """
            INSERT INTO feature.current_weather_summary (
                feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key,
                weather_value_key, summary_run_id, selected_at, refresh_after
            ) VALUES ($1, $2, 'forecast', 'short', 'TMP', $3, $4, $5, $6)
            """,
            seeded.weather_kma,
            kma_short,
            f"{seeded.kma_entity}-fact",
            weather_run,
            _T0 + timedelta(minutes=1),
            _T0 + timedelta(hours=1),
        )

        # weather Feature의 FK 의존 행 — alias·override·integrity finding
        await connection.execute(
            "INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind) "
            "VALUES ($1, $2, 'legacy_feature_id')",
            f"f_weather_w_{uuid4().hex[:16]}",
            seeded.weather_kma,
        )
        await connection.execute(
            """
            INSERT INTO ops.feature_overrides (feature_id, field_path, override_value, status)
            VALUES ($1, 'core.name', '"덮어쓴 날씨 이름"'::jsonb, 'active')
            """,
            seeded.weather_kma,
        )
        await connection.execute(
            """
            INSERT INTO ops.data_integrity_violations (
                violation_type, severity, message, feature_id, provider_dataset_id,
                source_record_key
            ) VALUES ('402_weather_probe', 'warning', 'weather finding', $1, $2, $3)
            """,
            seeded.weather_kma,
            kma_short,
            kma_record,
        )

        # --- 남을 것 -----------------------------------------------------------
        place_record = await _seed_source(
            connection, dataset_id=krex_place, key=seeded.place_entity, entity_type="rest_area"
        )
        await _seed_feature(
            connection,
            feature_id=seeded.place,
            kind="place",
            dataset_id=krex_place,
            entity_key=seeded.place_entity,
        )
        # 남는 place가 weather entity를 가리키는 보조 link — link만 지워지고 place는 남는다.
        await connection.execute(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_role, match_method, confidence, source_entity_key
            ) VALUES ($1, 'weather_context', 'nearest_grid', 80, $2)
            """,
            seeded.place,
            seeded.kma_entity,
        )
        await _seed_source(
            connection,
            dataset_id=krex_traffic,
            key=seeded.traffic_entity,
            entity_type="traffic_notice",
            raw='{"route_no": "0010", "point_name": "서울"}',
        )
        await _seed_feature(
            connection,
            feature_id=seeded.traffic,
            kind="notice",
            dataset_id=krex_traffic,
            entity_key=seeded.traffic_entity,
        )
        await _seed_notice_lifecycle(
            connection,
            dataset_id=krex_traffic,
            entity_type="traffic_notice",
            lineage_key="0010::서울",
        )
        await _seed_source(
            connection,
            dataset_id=landslide,
            key=seeded.landslide_entity,
            entity_type="landslide_forecast_issue",
        )
        await _seed_feature(
            connection,
            feature_id=seeded.landslide,
            kind="notice",
            dataset_id=landslide,
            entity_key=seeded.landslide_entity,
        )
        await connection.execute(
            """
            INSERT INTO ops.current_summary_runs (
                projection_kind, run_kind, status, started_at, finished_at
            ) VALUES ('price', 'reconcile', 'succeeded', $1, $2)
            """,
            _T0,
            _T0 + timedelta(minutes=1),
        )
        await connection.execute(
            """
            INSERT INTO ops.data_integrity_violations (
                violation_type, severity, message, feature_id, provider_dataset_id,
                source_record_key
            ) VALUES ('402_place_probe', 'warning', 'place finding', $1, $2, $3)
            """,
            seeded.place,
            krex_place,
            place_record,
        )

        # 두 Feature를 함께 묶는 행 — weather 쪽이 사라지면 CASCADE로 함께 간다.
        first, second = sorted((seeded.weather_kma, seeded.place))
        await connection.execute(
            """
            INSERT INTO ops.dedup_review_queue (
                feature_id_a, feature_id_b, total_score, name_score, spatial_score,
                category_score
            ) VALUES ($1, $2, 50, 50, 50, 50)
            """,
            first,
            second,
        )

        # curation item 둘 — weather 쪽은 SET NULL로 남고, place 쪽은 그대로다.
        theme_id = await connection.fetchval(
            "INSERT INTO feature.curated_themes (theme_slug, theme_name, theme_group) "
            "VALUES ($1, '402 테마', 'test') RETURNING theme_id",
            f"weather-removal-{uuid4().hex[:8]}",
        )
        collection_id = await connection.fetchval(
            "INSERT INTO feature.curation_collections (collection_key, theme_id, title) "
            "VALUES ($1, $2, '402 컬렉션') RETURNING collection_id",
            f"weather-removal-{uuid4().hex[:8]}",
            theme_id,
        )
        seeded.weather_item = await connection.fetchval(
            "INSERT INTO feature.curation_items "
            "(collection_id, feature_id, external_item_id, place_name) "
            "VALUES ($1, $2, 'weather-item', '날씨 항목') RETURNING curation_item_id",
            collection_id,
            seeded.weather_kma,
        )
        seeded.place_item = await connection.fetchval(
            "INSERT INTO feature.curation_items "
            "(collection_id, feature_id, external_item_id, place_name) "
            "VALUES ($1, $2, 'place-item', '휴게소 항목') RETURNING curation_item_id",
            collection_id,
            seeded.place,
        )
    return seeded


# ---------------------------------------------------------------------------
# 탐침
# ---------------------------------------------------------------------------


async def _removal_probes(connection: Any, seeded: _Seeded) -> dict[str, int]:
    """지워져야 하는 것의 개수. 401에서는 전부 > 0, 402 뒤에는 전부 0이어야 한다."""

    targets = [seeded.weather_kma, seeded.weather_krex, seeded.kma_alert]
    probes: dict[str, str] = {
        "weather Feature (kind)": "SELECT count(*) FROM feature.features WHERE kind = 'weather'",
        "KMA alert notice Feature": (
            f"SELECT count(*) FROM feature.features WHERE feature_id = '{seeded.kma_alert}'"
        ),
        "KMA alert notice subtype": (
            "SELECT count(*) FROM feature.feature_notices "
            f"WHERE feature_id = '{seeded.kma_alert}'"
        ),
        "target dataset source entity": (
            "SELECT count(*) FROM provider_sync.source_entities "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "target dataset source record": (
            "SELECT count(*) FROM provider_sync.source_records AS record "
            "JOIN provider_sync.source_entities AS entity USING (source_entity_key) "
            f"WHERE entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "target dataset source head": (
            "SELECT count(*) FROM provider_sync.source_entity_heads AS head "
            "JOIN provider_sync.source_entities AS entity USING (source_entity_key) "
            f"WHERE entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "link to a target entity (incl. weather_context of a kept place)": (
            "SELECT count(*) FROM provider_sync.source_links AS link "
            "JOIN provider_sync.source_entities AS entity USING (source_entity_key) "
            f"WHERE entity.provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "target identity claim": (
            "SELECT count(*) FROM provider_sync.provider_feature_identities "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL}) "
            "OR feature_kind = 'weather'"
        ),
        "target notice lifecycle scope": (
            "SELECT count(*) FROM provider_sync.notice_lifecycle_scopes "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "target notice lineage state": (
            "SELECT count(*) FROM provider_sync.notice_lineage_states AS state "
            "JOIN provider_sync.notice_lifecycle_scopes AS scope "
            "USING (notice_lifecycle_scope_id) "
            f"WHERE scope.provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "weather summary run": (
            "SELECT count(*) FROM ops.current_summary_runs WHERE projection_kind = 'weather'"
        ),
        "alias of a target Feature": (
            "SELECT count(*) FROM feature.feature_aliases WHERE feature_id = ANY($1::uuid[])"
        ),
        "override of a target Feature": (
            "SELECT count(*) FROM ops.feature_overrides WHERE feature_id = ANY($1::uuid[])"
        ),
        "integrity finding of a target Feature/dataset": (
            "SELECT count(*) FROM ops.data_integrity_violations "
            "WHERE feature_id = ANY($1::uuid[]) "
            f"OR provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ),
        "dedup pair touching a target Feature": (
            "SELECT count(*) FROM ops.dedup_review_queue "
            "WHERE feature_id_a = ANY($1::uuid[]) OR feature_id_b = ANY($1::uuid[])"
        ),
        "curation item pointing at a target Feature": (
            "SELECT count(*) FROM feature.curation_items WHERE feature_id = ANY($1::uuid[])"
        ),
        "enabled target operation (refresh/feature_load/preview)": (
            "SELECT count(*) FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL}) AND is_enabled"
        ),
        "active target dataset": (
            "SELECT count(*) FROM provider_sync.provider_datasets AS row_ "
            f"WHERE row_.provider_dataset_id IN ({_TARGET_DATASETS_SQL}) AND row_.is_active"
        ),
        "weather-only schema object": (
            "SELECT (to_regclass('feature.feature_weather_values') IS NOT NULL)::int"
            " + (to_regclass('feature.current_weather_summary') IS NOT NULL)::int"
            " + (to_regclass('feature.idx_features_public_weather_coord_5179_gist')"
            " IS NOT NULL)::int"
            " + (to_regprocedure('feature.reject_weather_value_mutation()')"
            " IS NOT NULL)::int"
        ),
    }
    measured: dict[str, int] = {}
    for label, sql in probes.items():
        arguments = (targets,) if "$1" in sql else ()
        measured[label] = int(await connection.fetchval(sql, *arguments))
    return measured


async def _weather_table_counts(connection: Any) -> dict[str, int]:
    """401에서만 존재하는 표의 행 수 — 402 뒤에는 표 자체가 없다."""

    return {
        "feature.feature_weather_values": int(
            await connection.fetchval("SELECT count(*) FROM feature.feature_weather_values")
        ),
        "feature.current_weather_summary": int(
            await connection.fetchval("SELECT count(*) FROM feature.current_weather_summary")
        ),
    }


async def _kept_snapshot(connection: Any, seeded: _Seeded) -> dict[str, str]:
    """남아야 하는 행의 **행 단위** 사본. 402 전후로 문자 그대로 같아야 한다."""

    features = seeded.kept_features
    entities = seeded.kept_entities
    queries: dict[str, tuple[str, tuple[Any, ...]]] = {
        "kept dataset catalog": (
            "SELECT * FROM provider_sync.provider_datasets "
            f"WHERE provider_dataset_id NOT IN ({_TARGET_DATASETS_SQL})",
            (),
        ),
        "kept dataset operations": (
            "SELECT * FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id NOT IN ({_TARGET_DATASETS_SQL})",
            (),
        ),
        "kept Feature core": (
            "SELECT * FROM feature.features WHERE feature_id = ANY($1::uuid[])",
            (features,),
        ),
        "kept notice subtype": (
            "SELECT * FROM feature.feature_notices WHERE feature_id = ANY($1::uuid[])",
            (features,),
        ),
        "kept identity claim": (
            "SELECT * FROM provider_sync.provider_feature_identities "
            "WHERE feature_id = ANY($1::uuid[])",
            (features,),
        ),
        "kept primary link": (
            "SELECT * FROM provider_sync.source_links "
            "WHERE feature_id = ANY($1::uuid[]) AND source_entity_key = ANY($2::text[])",
            (features, entities),
        ),
        "kept source entity": (
            "SELECT * FROM provider_sync.source_entities "
            "WHERE source_entity_key = ANY($1::text[])",
            (entities,),
        ),
        "kept source record": (
            "SELECT * FROM provider_sync.source_records "
            "WHERE source_entity_key = ANY($1::text[])",
            (entities,),
        ),
        "kept source head": (
            "SELECT * FROM provider_sync.source_entity_heads "
            "WHERE source_entity_key = ANY($1::text[])",
            (entities,),
        ),
        "kept notice lifecycle": (
            "SELECT scope.*, state.lineage_key, state.present, state.changed_at "
            "FROM provider_sync.notice_lifecycle_scopes AS scope "
            "JOIN provider_sync.notice_lineage_states AS state "
            "USING (notice_lifecycle_scope_id) "
            f"WHERE scope.provider_dataset_id NOT IN ({_TARGET_DATASETS_SQL})",
            (),
        ),
        "price summary run": (
            "SELECT * FROM ops.current_summary_runs WHERE projection_kind = 'price'",
            (),
        ),
        "kept integrity finding": (
            "SELECT * FROM ops.data_integrity_violations WHERE feature_id = ANY($1::uuid[])",
            (features,),
        ),
        "kept curation item": (
            "SELECT * FROM feature.curation_items WHERE curation_item_id = $1",
            (seeded.place_item,),
        ),
    }
    snapshot: dict[str, str] = {}
    for label, (sql, arguments) in queries.items():
        snapshot[label] = str(
            await connection.fetchval(
                "SELECT coalesce(jsonb_agg(to_jsonb(row_) ORDER BY to_jsonb(row_)::text),"
                f" '[]'::jsonb)::text FROM ({sql}) AS row_",
                *arguments,
            )
        )
    return snapshot


# ---------------------------------------------------------------------------
# FK 전수 — RESTRICT/NO ACTION 참조자가 전부 다뤄지는지
# ---------------------------------------------------------------------------


def _migration_module() -> Any:
    spec = importlib.util.spec_from_file_location("_weather_removal_402", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _handled_relations() -> set[str]:
    """migration이 **실제로** 다루는 relation — 문장에서 읽는다(이름 목록을 따로 두지 않는다).

    - ``DELETE FROM x`` / ``DROP TABLE x``가 실행 문장에 있으면 다룬다.
    - preflight 항목 이름이 ``schema.table``로 시작하면 그 relation은 막는 쪽으로 다룬다.
    """

    module = _migration_module()
    executed = "\n".join(module._UPGRADE_STATEMENTS)
    handled = set(re.findall(r"DELETE FROM ([a-z_]+\.[a-z_]+)", executed))
    handled |= set(re.findall(r"DROP TABLE ([a-z_]+\.[a-z_]+)", executed))
    for label, _sql in module._PREFLIGHT_BLOCKERS:
        match = re.match(r"([a-z_]+\.[a-z_]+)", label)
        if match is not None:
            handled.add(match.group(1))
    return handled


#: FK CASCADE로 대상 Feature와 함께 지워지는 relation 중, 대상 entity를 RESTRICT로도
#: 붙드는 것. 남는 Feature 쪽 행은 preflight("non-target Feature bound ...")가 막는다.
#: 아래 테스트가 (1) features로의 CASCADE FK가 실재하는지, (2) preflight SQL이 이 표를
#: 실제로 읽는지를 함께 잰다 — 목록만 두면 근거 없이 늘어난다.
_COVERED_BY_FEATURE_CASCADE: Final = frozenset({"feature.feature_base_field_values"})

_BLOCKING_FKS_SQL: Final = """
SELECT DISTINCT
       referencing_ns.nspname || '.' || referencing.relname AS referencing,
       referenced_ns.nspname || '.' || referenced.relname AS referenced
  FROM pg_catalog.pg_constraint AS fk
  JOIN pg_catalog.pg_class AS referencing ON referencing.oid = fk.conrelid
  JOIN pg_catalog.pg_namespace AS referencing_ns ON referencing_ns.oid = referencing.relnamespace
  JOIN pg_catalog.pg_class AS referenced ON referenced.oid = fk.confrelid
  JOIN pg_catalog.pg_namespace AS referenced_ns ON referenced_ns.oid = referenced.relnamespace
 WHERE fk.contype = 'f'
   AND fk.confdeltype IN ('r', 'a')
   AND fk.confrelid IN (
       'feature.features'::regclass,
       'provider_sync.source_entities'::regclass,
       'provider_sync.source_records'::regclass,
       'provider_sync.source_entity_heads'::regclass,
       'provider_sync.notice_lifecycle_scopes'::regclass
   )
 ORDER BY 1, 2
"""


async def _assert_every_blocking_fk_is_handled(connection: Any) -> None:
    rows = await connection.fetch(_BLOCKING_FKS_SQL)
    # 하한은 본 것에 건다 — 401 head에서 RESTRICT/NO ACTION 참조자가 실재해야 이 검사가
    # 무언가를 잰다(theme candidate·dedup case·reconciliation·feature request 등).
    assert rows, "RESTRICT/NO ACTION FK를 하나도 읽지 못했다 — 질의를 의심하라"
    handled = _handled_relations() | _COVERED_BY_FEATURE_CASCADE
    unhandled = sorted(
        f"{row['referencing']} -> {row['referenced']}"
        for row in rows
        if row["referencing"] not in handled
    )
    assert not unhandled, (
        "402가 지우는 행을 RESTRICT/NO ACTION으로 붙드는 relation을 migration이 다루지 "
        f"않는다(지우지도 막지도 않는다): {unhandled}"
    )

    for relation in _COVERED_BY_FEATURE_CASCADE:
        cascades = await connection.fetchval(
            """
            SELECT count(*) FROM pg_catalog.pg_constraint
             WHERE contype = 'f' AND confdeltype = 'c'
               AND conrelid = $1::regclass AND confrelid = 'feature.features'::regclass
            """,
            relation,
        )
        assert cascades, f"{relation}: feature.features로의 CASCADE FK가 없다"
        preflight = "\n".join(sql for _label, sql in _migration_module()._PREFLIGHT_BLOCKERS)
        assert relation in preflight, f"{relation}: 남는 Feature 쪽을 막는 preflight가 없다"


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


async def test_402_removes_weather_and_kma_alert_data_and_keeps_everything_else(
    db_at_401: tuple[Config, str],
) -> None:
    config, superuser_dsn = db_at_401
    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        await _assert_every_blocking_fk_is_handled(connection)
        seeded = await _seed_population(connection)

        # 401: 같은 탐침이 **전부** 무언가를 본다(빨강). 0인 탐침은 항진명제다.
        before = await _removal_probes(connection, seeded)
        vacuous = sorted(label for label, count in before.items() if count == 0)
        assert not vacuous, f"401에서 이미 0인 탐침 — 아무것도 재지 않는다: {vacuous}"
        assert all(count > 0 for count in (await _weather_table_counts(connection)).values())
        kept_before = await _kept_snapshot(connection, seeded)
        empty = sorted(label for label, rows in kept_before.items() if rows == "[]")
        assert not empty, f"남을 것의 사본이 비었다 — 비교가 무의미하다: {empty}"
        catalog_rows_before = await connection.fetchval(
            f"SELECT count(*) FROM ({_TARGET_DATASETS_SQL}) AS target"
        )
        operation_rows_before = await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        )
    finally:
        await connection.close()

    await _upgrade_to_402(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _AFTER

        after = await _removal_probes(connection, seeded)
        survivors = {label: count for label, count in after.items() if count != 0}
        assert not survivors, f"402 뒤에 남은 weather 데이터/객체: {survivors}"

        kept_after = await _kept_snapshot(connection, seeded)
        changed = sorted(label for label in kept_before if kept_before[label] != kept_after[label])
        assert not changed, f"남아야 할 행이 바뀌었다: {changed}"

        # weather Feature를 가리키던 curation item은 FK 선언대로 SET NULL로 남는다.
        assert await connection.fetchval(
            "SELECT feature_id IS NULL FROM feature.curation_items WHERE curation_item_id = $1",
            seeded.weather_item,
        ) is True

        # 카탈로그 행은 지우지 않는다(이력 FK) — 비활성·비활성화만.
        assert await connection.fetchval(
            f"SELECT count(*) FROM ({_TARGET_DATASETS_SQL}) AS target"
        ) == catalog_rows_before
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_dataset_operations "
            f"WHERE provider_dataset_id IN ({_TARGET_DATASETS_SQL})"
        ) == operation_rows_before

        # 정의는 남는다 — 효과로 잰다(kind CHECK가 'weather'를 받는다). 행은 남기지 않는다.
        definition_probe = connection.transaction()
        await definition_probe.start()
        try:
            await connection.execute(
                "INSERT INTO feature.features (feature_id, kind, name, category) "
                "VALUES ($1, 'weather', '정의 확인', '00000000')",
                uuid4(),
            )
        finally:
            await definition_probe.rollback()
        assert await connection.fetchval(
            "SELECT provider_sync.is_valid_provider_dataset_capabilities("
            """'{"produces": ["weather"], "extensions": {}, "schema_version": 1}'::jsonb)"""
        ) is True
        identity_kind = await connection.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname = 'ck_provider_feature_identities_kind'"
        )
        assert "'weather'" in str(identity_kind)

        # summary run은 price 전용이 됐다 — weather 영수증은 DB가 거부한다.
        import asyncpg

        with pytest.raises(asyncpg.CheckViolationError, match="projection_kind"):
            await connection.execute(
                "INSERT INTO ops.current_summary_runs (projection_kind, run_kind, status) "
                "VALUES ('weather', 'ingest', 'running')"
            )
        # 불변 fence는 다시 켜져 있다.
        assert await connection.fetchval(
            "SELECT tgenabled::text FROM pg_catalog.pg_trigger "
            "WHERE tgrelid = 'ops.current_summary_runs'::regclass "
            "AND tgname = 'trg_current_summary_runs_terminal_immutable'"
        ) == "O"
    finally:
        await connection.close()


async def test_402_refuses_when_a_kept_feature_is_bound_to_a_weather_dataset(
    db_at_401: tuple[Config, str],
) -> None:
    """남는 Feature의 primary lineage가 weather dataset에 있으면 아무것도 바꾸지 않는다.

    지우면 그 Feature가 출처를 잃는다. preflight가 이름을 대고 멈춰야 하고, 트랜잭션
    전체가 되돌아가 401 그대로여야 한다.
    """

    config, superuser_dsn = db_at_401
    connection = await _connect(superuser_dsn)
    try:
        kma_short = await _dataset_id(connection, _KMA_SHORT)
        entity = f"402-bound-{uuid4().hex[:8]}"
        place = uuid4()
        async with connection.transaction():
            await _seed_source(
                connection, dataset_id=kma_short, key=entity, entity_type="grid_forecast"
            )
            await connection.execute(
                "INSERT INTO feature.features (feature_id, kind, name, category) "
                "VALUES ($1, 'place', '날씨 출처 place', '00000000')",
                place,
            )
            await connection.execute(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_role, match_method, confidence, source_entity_key
                ) VALUES ($1, 'primary', 'provider_key', 100, $2)
                """,
                place,
                entity,
            )
    finally:
        await connection.close()

    with pytest.raises(Exception, match="non-target Feature bound to a target dataset"):
        await _upgrade_to_402(config)

    connection = await _connect(superuser_dsn)
    try:
        assert await _version(connection) == _BEFORE
        assert await connection.fetchval(
            "SELECT to_regclass('feature.feature_weather_values') IS NOT NULL"
        ) is True
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.source_entities WHERE source_entity_key = $1",
            entity,
        ) == 1
        assert await connection.fetchval(
            "SELECT count(*) FROM provider_sync.provider_datasets AS row_ "
            f"WHERE row_.provider_dataset_id IN ({_TARGET_DATASETS_SQL}) AND NOT row_.is_active"
        ) == 0
    finally:
        await connection.close()
