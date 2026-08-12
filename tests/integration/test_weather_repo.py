"""T-VN-38 final weather writer/card/anchor integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash
from kortravelmap.dto import SourceRecord
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import weather_repo
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration

# ``build_weather_card`` deliberately reads the *current* receipt projection
# and rejects rows past ``refresh_after``.  Keep its receipt fresh relative to
# the test run, while snapshot assertions below still establish ordering via
# the fixed offset between these two instants.
_BASE = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
_TARGET = _BASE + timedelta(hours=1)
_KMA = "python-kma-api"
_KREX = "python-krex-api"


async def _insert_feature(
    session: AsyncSession,
    feature_id: str,
    *,
    kind: str = "weather",
    lon: float | None = None,
    lat: float | None = None,
) -> None:
    """weather anchor/target 후보 1건을 **공개 표면에 보이는 상태로** 심는다.

    이 파일이 상태에 거는 요구는 단 하나 — ``weather_repo``의 card/anchor 조회가
    전부 ``feature.public_features``(ADR-067) 위에서만 돌기 때문에 심은 feature가
    그 projection에 떠야 한다는 것이다. T-VN-34(0097)가 ``status``를 물리 삭제하며
    그 가시성 조건을 3축으로 옮겼고, 0097의 view 술어가 곧
    ``lifecycle='active' AND publication='published' AND quality='valid'``다.
    옛 ``status='active'``와 정확히 같은 뜻이라 그 tuple을 명시적으로 심는다.

    축 값 자체는 이 파일의 관심사가 아니므로, 아래에서 축을 다시 읽어 확인하는 대신
    ``public_features`` 실재를 단언한다 — 테스트가 실제로 의존하는 사실이 그것이고,
    typed subtype 분해(0085~0087) 같은 projection 변경이 조용히 anchor 후보를
    지워버리면 weather 단언이 엉뚱하게 깨지기 전에 여기서 먼저 잡힌다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state
            ) VALUES (
                :feature_id, :kind, :feature_id, '00000000',
                CASE
                    WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                    ELSE x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CAST(:lon AS double precision), CAST(:lat AS double precision)
                    ), 4326
                ) END,
                'active', 'published', 'valid'
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "lon": lon,
            "lat": lat,
        },
    )
    assert await session.scalar(
        text(
            "SELECT count(*) FROM feature.public_features WHERE feature_id = :feature_id"
        ),
        {"feature_id": feature_id},
    ) == 1


async def _dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    dataset_id = await session.scalar(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES (:provider, :dataset_key, :display_name, 'manual')
            RETURNING provider_dataset_id
            """
        ),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "display_name": f"test {dataset_key}",
        },
    )
    assert dataset_id is not None
    await upsert_provider_refresh_policy(
        session,
        provider_dataset_id=int(dataset_id),
        source_kind="manual",
        expected_revision=None,
        stale_after_minutes=24 * 60,
    )
    return int(dataset_id)


def _response(
    *, provider: str, dataset_key: str, suffix: str, fetched_at: datetime
) -> SourceRecord:
    raw_data = {"response": suffix}
    return SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type="weather_response",
        source_entity_id=f"{dataset_key}-response",
        raw_payload_hash=make_payload_hash(raw_data),
        raw_data=raw_data,
        fetched_at=fetched_at,
        imported_at=fetched_at,
        source_record_key=f"weather-response-{dataset_key}-{suffix}",
    )


def _value(
    feature_id: str,
    metric_key: str,
    *,
    provider: str,
    domain: str,
    style: str,
    target_at: datetime,
    value_number: str | None = None,
    value_text: str | None = None,
    observed: bool = False,
) -> WeatherValue:
    return WeatherValue(
        feature_id=feature_id,
        provider=provider,
        weather_domain=domain,
        forecast_style=style,
        timeline_bucket=(
            "ultra_short" if observed else style if style in {"short", "mid"} else None
        ),
        metric_key=metric_key,
        metric_name=metric_key,
        value_number=Decimal(value_number) if value_number is not None else None,
        value_text=value_text,
        unit="deg_c" if metric_key in {"TMP", "T1H"} else "%",
        issued_at=None if observed else _BASE,
        observed_at=target_at if observed else None,
        valid_at=None if observed else target_at,
    )


async def test_current_card_uses_receipt_summary_and_snapshot_uses_raw_facts(
    migrated_session: AsyncSession,
) -> None:
    """normal card와 time-travel reader를 서로 다른 명시적 경계로 유지한다."""
    dataset_key = "tvn38_current"
    dataset_id = await _dataset(
        migrated_session, provider=_KMA, dataset_key=dataset_key
    )
    await _insert_feature(migrated_session, "weather-current")
    response = _response(
        provider=_KMA, dataset_key=dataset_key, suffix="a", fetched_at=_BASE
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-current",
                "TMP",
                provider=_KMA,
                domain="kma_short_forecast",
                style="short",
                target_at=_BASE,
                value_number="20",
            ),
            _value(
                "weather-current",
                "TMP",
                provider=_KMA,
                domain="kma_short_forecast",
                style="short",
                target_at=_TARGET,
                value_number="25",
            ),
            _value(
                "weather-current",
                "FIRE_RISK",
                provider=_KMA,
                domain="kma_weather_alert",
                style="advisory",
                target_at=_TARGET,
                value_text="주의보",
            ),
        ],
        provider_dataset_id=dataset_id,
        source_record=response,
        selected_at=_TARGET,
    ) == 3

    current = await weather_repo.build_weather_card(
        migrated_session, feature_id="weather-current"
    )
    current_by_key = {(item.forecast_style, item.metric_key): item for item in current.metrics}
    assert current_by_key[("short", "TMP")].value_number == Decimal("25")
    assert current_by_key[("short", "TMP")].provider_dataset_id == dataset_id
    assert current_by_key[("short", "TMP")].dataset_key == dataset_key
    assert current_by_key[("short", "TMP")].known_at == _BASE
    assert current.selected_at == _TARGET
    assert current.refresh_after is not None

    snapshot = await weather_repo.build_weather_snapshot(
        migrated_session,
        feature_id="weather-current",
        target_at=_BASE + timedelta(minutes=30),
        known_at=_TARGET,
    )
    snapshot_by_key = {(item.forecast_style, item.metric_key): item for item in snapshot.metrics}
    assert snapshot_by_key[("short", "TMP")].value_number == Decimal("20")
    assert ("advisory", "FIRE_RISK") not in snapshot_by_key


async def test_current_card_merges_kma_and_observed_anchors_only_without_own_temperature(
    migrated_session: AsyncSession,
) -> None:
    """own → KMA → observed tier order가 current summary에서도 보존된다."""
    kma_key = "tvn38_kma_anchor"
    krex_key = "tvn38_krex_anchor"
    kma_id = await _dataset(migrated_session, provider=_KMA, dataset_key=kma_key)
    krex_id = await _dataset(migrated_session, provider=_KREX, dataset_key=krex_key)
    await _insert_feature(
        migrated_session, "weather-rural", kind="place", lon=126.9784, lat=37.5665
    )
    await _insert_feature(
        migrated_session, "weather-kma", lon=127.0684, lat=37.5665
    )
    await _insert_feature(
        migrated_session, "weather-krex", lon=127.0124, lat=37.5665
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-kma", "SKY", provider=_KMA, domain="kma_mid_forecast",
                style="mid", target_at=_TARGET, value_text="구름많음"
            ),
            _value(
                "weather-kma", "TMP", provider=_KMA, domain="kma_short_forecast",
                style="short", target_at=_TARGET, value_number="21"
            ),
        ],
        provider_dataset_id=kma_id,
        source_record=_response(
            provider=_KMA, dataset_key=kma_key, suffix="a", fetched_at=_BASE
        ),
        selected_at=_TARGET,
    ) == 2
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-krex", "T1H", provider=_KREX,
                domain="rest_area_weather", style="observed", target_at=_TARGET,
                value_number="18", observed=True
            )
        ],
        provider_dataset_id=krex_id,
        source_record=_response(
            provider=_KREX, dataset_key=krex_key, suffix="a", fetched_at=_BASE
        ),
        selected_at=_TARGET,
    ) == 1

    rural = await weather_repo.build_weather_card(
        migrated_session, feature_id="weather-rural"
    )
    by_key = {(item.forecast_style, item.metric_key): item for item in rural.metrics}
    assert by_key[("mid", "SKY")].value_text == "구름많음"
    assert by_key[("short", "TMP")].value_number == Decimal("21")
    assert by_key[("observed", "T1H")].value_number == Decimal("18")

    await _insert_feature(
        migrated_session, "weather-own", kind="place", lon=126.9794, lat=37.5665
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-own", "TMP", provider=_KMA, domain="kma_short_forecast",
                style="short", target_at=_TARGET, value_number="22"
            )
        ],
        provider_dataset_id=kma_id,
        source_record=_response(
            provider=_KMA, dataset_key=kma_key, suffix="b", fetched_at=_BASE + timedelta(minutes=1)
        ),
        selected_at=_TARGET,
    ) == 1
    own = await weather_repo.build_weather_card(migrated_session, feature_id="weather-own")
    assert {(item.forecast_style, item.metric_key) for item in own.metrics} == {("short", "TMP")}

    # 자기 anchor가 SKY만 가진 KMA row여도 KMA tier가 자기 자신을 재선정하면 안 된다.
    # 다음 KMA anchor의 기온을 병합해 own → KMA → observed 순서를 완결한다.
    await _insert_feature(
        migrated_session,
        "weather-partial-own",
        kind="place",
        lon=126.9804,
        lat=37.5665,
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-partial-own",
                "SKY",
                provider=_KMA,
                domain="kma_short_forecast",
                style="short",
                target_at=_TARGET,
                value_text="맑음",
            )
        ],
        provider_dataset_id=kma_id,
        source_record=_response(
            provider=_KMA,
            dataset_key=kma_key,
            suffix="c",
            fetched_at=_BASE + timedelta(minutes=2),
        ),
        selected_at=_TARGET,
    ) == 1
    partial = await weather_repo.build_weather_card(
        migrated_session, feature_id="weather-partial-own"
    )
    partial_by_key = {
        (item.forecast_style, item.metric_key): item for item in partial.metrics
    }
    assert partial_by_key[("short", "SKY")].value_text == "맑음"
    assert partial_by_key[("short", "TMP")].value_number == Decimal("21")


async def test_nearest_weather_anchor_reads_current_summary_not_legacy_catalog(
    migrated_session: AsyncSession,
) -> None:
    dataset_key = "tvn38_nearest"
    dataset_id = await _dataset(
        migrated_session, provider=_KMA, dataset_key=dataset_key
    )
    await _insert_feature(migrated_session, "weather-nearest", lon=126.9784, lat=37.5665)
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value(
                "weather-nearest", "TMP", provider=_KMA,
                domain="kma_short_forecast", style="short", target_at=_TARGET,
                value_number="20"
            )
        ],
        provider_dataset_id=dataset_id,
        source_record=_response(
            provider=_KMA, dataset_key=dataset_key, suffix="a", fetched_at=_BASE
        ),
        selected_at=_TARGET,
    ) == 1
    anchor = await weather_repo.nearest_weather_feature_for_coordinate(
        migrated_session, lon=126.9794, lat=37.5665
    )
    assert anchor is not None
    assert anchor.feature_id == "weather-nearest"
