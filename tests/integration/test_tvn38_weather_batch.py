"""T-VN-38C immutable weather batch reader의 실제 PostgreSQL 회귀 검증."""

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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration

_BASE = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)
_PROVIDER = "python-kma-api"
_DATASET = "tvn38_batch_forecast"


async def _insert_feature(
    session: AsyncSession,
    feature_id: str,
    *,
    kind: str = "place",
    lon: float = 126.9784,
    lat: float = 37.5665,
) -> None:
    """batch 조회의 입력이 될 feature 1건을 공개 표면에 보이는 상태로 심는다.

    T-VN-34(0097)가 ``status``를 물리 삭제했다. 이 파일이 상태에 거는 요구는
    "``feature.public_features``에 뜨는가" 하나뿐이고 — batch reader는 parent/anchor를
    그 projection에서만 찾는다 — 그 조건이 곧
    ``lifecycle='active' AND publication='published' AND quality='valid'``,
    즉 옛 ``status='active'``와 같은 뜻이다. 세 축의 컬럼 기본값이 정확히 그 조합이라
    별도 지정 없이 INSERT하는 것으로 등가가 성립한다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord
            ) VALUES (
                :feature_id, :kind, :feature_id, '00000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(:lon, :lat), 4326
                )
            )
            """
        ),
        {"feature_id": feature_id, "kind": kind, "lon": lon, "lat": lat},
    )


async def _response(
    session: AsyncSession, *, suffix: str, fetched_at: datetime
) -> tuple[int, SourceRecord]:
    if suffix == "a":
        dataset_id = await session.scalar(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind
                ) VALUES (:provider, :dataset_key, 'T-VN-38 batch', 'manual')
                RETURNING provider_dataset_id
                """
            ),
            {"provider": _PROVIDER, "dataset_key": _DATASET},
        )
    else:
        dataset_id = await session.scalar(
            text(
                """
                SELECT provider_dataset_id
                FROM provider_sync.provider_datasets
                WHERE provider = :provider AND dataset_key = :dataset_key
                """
            ),
            {"provider": _PROVIDER, "dataset_key": _DATASET},
        )
    assert dataset_id is not None
    raw_data = {"response": suffix}
    return int(dataset_id), SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="weather_response",
        source_entity_id="batch-response",
        raw_payload_hash=make_payload_hash(raw_data),
        raw_data=raw_data,
        fetched_at=fetched_at,
        imported_at=fetched_at,
        source_record_key=f"tvn38-batch-response-{suffix}",
    )


def _value(feature_id: str, metric_key: str, *, target_at: datetime, value: str) -> WeatherValue:
    return WeatherValue(
        feature_id=feature_id,
        provider=_PROVIDER,
        weather_domain="kma_short_forecast",
        forecast_style="short",
        timeline_bucket="short",
        metric_key=metric_key,
        metric_name=metric_key,
        value_number=Decimal(value),
        unit="deg_c" if metric_key == "TMP" else "%",
        issued_at=_BASE,
        valid_at=target_at,
    )


async def test_batch_uses_final_facts_and_preserves_snapshot_source_tiers(
    migrated_session: AsyncSession,
) -> None:
    """current summary가 아닌 immutable fact로 target/known snapshot을 재현한다."""
    target_at = _BASE + timedelta(hours=2)
    future_target_at = target_at + timedelta(hours=3)
    known_at = _BASE + timedelta(hours=1)
    dataset_id, first_response = await _response(
        migrated_session, suffix="a", fetched_at=_BASE
    )
    _, future_response = await _response(
        migrated_session, suffix="b", fetched_at=known_at + timedelta(minutes=1)
    )
    await _insert_feature(migrated_session, "batch-parent")
    await _insert_feature(
        migrated_session,
        "batch-anchor",
        kind="weather",
        lon=126.9804,
        lat=37.5665,
    )
    await _insert_feature(migrated_session, "batch-empty", lon=128.0, lat=37.5665)
    await _insert_feature(migrated_session, "batch-retired", lon=126.9744, lat=37.5665)
    # 옛 ``status='deleted' + deleted_at``의 뜻은 "더 이상 공개 표면에 없다"였고,
    # 0095 backfill이 그 조건을 그대로 ``lifecycle_state='retired'``로 옮겼다.
    # 삭제 시각 자체는 이 테스트가 단언하지 않으므로(단언 대상은 batch item이
    # ``retired``로 분류되는지뿐이다) 시각 컬럼 대체물은 필요 없다. retire되면
    # ``ck_features_state_tuple``이 publication을 ``suppressed``로 강제하므로 두 축을
    # 한 문장에서 함께 옮긴다 — 그 결과 이 행은 ``feature.public_features``에서
    # 빠지고, batch reader가 parent를 못 찾아 ``retired``로 분류한다.
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET lifecycle_state = 'retired', publication_state = 'suppressed'
            WHERE feature_id = 'batch-retired'
            """
        ),
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value("batch-anchor", "TMP", target_at=target_at, value="20"),
            _value("batch-anchor", "POP", target_at=future_target_at, value="30"),
        ],
        provider_dataset_id=dataset_id,
        source_record=first_response,
        selected_at=target_at,
    ) == 2
    # 같은 target의 later knowledge correction은 첫 snapshot에 보이면 안 된다.
    assert await weather_repo.load_weather_values(
        migrated_session,
        [_value("batch-anchor", "TMP", target_at=target_at, value="99")],
        provider_dataset_id=dataset_id,
        source_record=future_response,
        selected_at=target_at,
    ) == 1
    await migrated_session.flush()

    snapshots = await weather_repo.get_weather_batch_snapshots(
        migrated_session,
        targets=(
            weather_repo.WeatherBatchTarget(
                target_at=target_at,
                feature_ids=(
                    "batch-parent",
                    "batch-anchor",
                    "batch-empty",
                    "batch-retired",
                ),
            ),
        ),
        known_at=known_at,
    )

    snapshot = snapshots[0]
    assert [item.state for item in snapshot.items] == [
        "found",
        "found",
        "no_data",
        "retired",
    ]
    assert snapshot.items[0].card_key == snapshot.items[1].card_key
    card = snapshot.cards[0]
    current = {(metric.forecast_style, metric.metric_key): metric for metric in card.current}
    assert current[("short", "TMP")].value_number == Decimal("20")
    assert current[("short", "TMP")].provider_dataset_id == dataset_id
    assert current[("short", "TMP")].dataset_key == _DATASET
    assert current[("short", "TMP")].known_at == _BASE
    timeline = {(metric.forecast_style, metric.metric_key): metric for metric in card.timeline}
    assert timeline[("short", "POP")].value_number == Decimal("30")
    assert snapshot.items[2].card_key is None
    assert snapshot.items[3].card_key is None


async def test_batch_enforces_source_work_budget_before_metrics(
    migrated_session: AsyncSession,
) -> None:
    target_at = _BASE + timedelta(hours=2)
    dataset_id, response = await _response(migrated_session, suffix="a", fetched_at=_BASE)
    await _insert_feature(migrated_session, "batch-budget", kind="weather")
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value("batch-budget", "TMP", target_at=target_at, value="20"),
            _value("batch-budget", "POP", target_at=target_at, value="30"),
        ],
        provider_dataset_id=dataset_id,
        source_record=response,
        selected_at=target_at,
    ) == 2
    with pytest.raises(
        weather_repo.WeatherBatchWorkLimitExceededError,
        match="series work 2 exceeds limit 1",
    ):
        await weather_repo.get_weather_batch_snapshots(
            migrated_session,
            targets=(
                weather_repo.WeatherBatchTarget(
                    target_at=target_at, feature_ids=("batch-budget",)
                ),
            ),
            known_at=target_at,
            series_work_limit=1,
        )


async def test_batch_partial_own_weather_uses_next_kma_anchor_for_temperature(
    migrated_session: AsyncSession,
) -> None:
    """own anchor가 온도 없이 일부 metric만 가지면 self를 fallback으로 재선정하지 않는다."""

    target_at = _BASE + timedelta(hours=2)
    dataset_id, response = await _response(
        migrated_session, suffix="a", fetched_at=_BASE
    )
    await _insert_feature(migrated_session, "batch-partial-own", kind="weather")
    await _insert_feature(
        migrated_session,
        "batch-next-kma-anchor",
        kind="weather",
        lon=126.9804,
        lat=37.5665,
    )
    assert await weather_repo.load_weather_values(
        migrated_session,
        [
            _value("batch-partial-own", "SKY", target_at=target_at, value="1"),
            _value("batch-next-kma-anchor", "TMP", target_at=target_at, value="22"),
        ],
        provider_dataset_id=dataset_id,
        source_record=response,
        selected_at=target_at,
    ) == 2

    snapshots = await weather_repo.get_weather_batch_snapshots(
        migrated_session,
        targets=(
            weather_repo.WeatherBatchTarget(
                target_at=target_at,
                feature_ids=("batch-partial-own",),
            ),
        ),
        known_at=target_at,
    )
    card = snapshots[0].cards[0]
    metrics = {(metric.forecast_style, metric.metric_key): metric for metric in card.current}
    assert metrics[("short", "SKY")].value_number == Decimal("1")
    assert metrics[("short", "TMP")].value_number == Decimal("22")
