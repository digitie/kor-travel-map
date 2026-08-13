"""``test_mois_loader`` — MOIS 인허가 변환 → 적재 → 재조회 (Sprint 4a loader).

``kortravelmap.mois.load_mois_license_features_bulk``가 ``providers.mois`` 변환
출력을 PostGIS에 idempotent upsert하는지 검증한다.

검증: ① PROMOTED record 적재 + 재조회(JSONB detail/address) ② EXCLUDED/비영업
record는 적재되지 않음 ③ 재적재 idempotent (feature 수 불변) ④ FeatureLoadResult
카운트.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text

from kortravelmap.infra.models import FeatureRow, SourceLinkRow
from kortravelmap.infra.sync_state_repo import get_sync_state
from kortravelmap.mois import (
    close_mois_license_features,
    load_mois_license_features_bulk,
    retire_mois_license_features_absent_from_snapshot,
    run_mois_license_bulk_job,
    run_mois_license_closed_job,
    run_mois_license_incremental_job,
    sync_mois_license_features_bulk,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_CLOSED,
    DATASET_KEY_HISTORY,
    PROVIDER_NAME,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=_KST)

# T-VN-33: sync-state identity = provider_dataset_id + sync_scope + operation_key.
# 자연키 사본이 사라졌고 scope 네임스페이스는 catalog(``provider_dataset_operation_scopes``)가
# 소유한다 — MOIS refresh operation은 모두 ``dataset_wide``다.
_SYNC_SCOPE = "dataset_wide"
_INCREMENTAL_OPERATION_KEY = "mois_license_incremental_update"
_CLOSED_OPERATION_KEY = "mois_license_closed_update"


@dataclass(frozen=True)
class _Record:
    """``MoisLicensePlaceRecord`` Protocol 만족 (mois.db.PlaceRecord 모사)."""

    service_slug: str
    mng_no: str | None = "MNG-0001"
    is_open: bool | None = True
    place_name: str | None = "테스트 사업장"
    category: str | None = None
    title: str | None = None
    opn_authority_code: str | None = None
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = None
    lot_address: str | None = None
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = "1111010100"
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = None
    lat: float | None = None
    source_x: float | None = None
    source_y: float | None = None
    business_type_name: str | None = None
    subtype_name: str | None = None
    multi_use_business_place_yn: str | None = None
    sanitation_business_status_name: str | None = None
    facility_total_scale: str | None = None
    water_supply_facility_type_name: str | None = None
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = None
    ground_floor_count: int | None = None
    underground_floor_count: int | None = None
    total_floor_count: int | None = None
    facility_area: float | None = None
    total_area: float | None = None
    sickbed_count: int | None = None
    bed_count: int | None = None
    healthcare_worker_count: int | None = None
    hospital_room_count: int | None = None
    medical_institution_type_name: str | None = None
    medical_subject_names: str | None = None


async def _feature_count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(FeatureRow))).scalar_one()
    )


async def test_loader_persists_promoted_and_skips_others(
    migrated_session: AsyncSession,
) -> None:
    records = [
        _Record(
            service_slug="general_restaurants",
            mng_no="keep-restaurant",
            place_name="한식당 가나다",
            road_address="서울특별시 종로구 세종대로 1",
            telno="0212345678",
            lon=126.9784,
            lat=37.5665,
        ),
        _Record(service_slug="public_baths", mng_no="keep-bath", place_name="대중목욕탕"),
        _Record(service_slug="billiard_halls", mng_no="drop-excluded"),  # EXCLUDED
        _Record(service_slug="hospitals", mng_no="drop-unmapped"),  # 미매핑
        _Record(
            service_slug="bakeries", mng_no="drop-closed", is_open=False
        ),  # 비영업
    ]

    result = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()

    # ② PROMOTED·영업중 2건만 적재 (EXCLUDED/미매핑/비영업 skip).
    assert result.bundles_total == 2
    assert result.features_inserted == 2
    assert await _feature_count(migrated_session) == 2

    # ① 적재된 feature 재조회 + place_kind/category.
    rows = (
        await migrated_session.execute(
            select(FeatureRow).order_by(FeatureRow.feature_id)
        )
    ).scalars().all()
    by_name = {r.name: r for r in rows}
    assert "한식당 가나다" in by_name
    restaurant = by_name["한식당 가나다"]
    assert restaurant.kind == "place"
    assert restaurant.category == "02010100"
    assert restaurant.marker_color == "P-01"
    # T-VN-35(ADR-086): place 값의 정본은 ``feature_places``다(core에 detail 없음).
    assert (
        await migrated_session.execute(
            text(
                "SELECT place_kind FROM feature.feature_places "
                "WHERE feature_id = :fid"
            ),
            {"fid": restaurant.feature_id},
        )
    ).scalar_one() == "restaurant"

    # ③ source_link FK 정합 (PRIMARY).
    links = (
        await migrated_session.execute(select(SourceLinkRow))
    ).scalars().all()
    assert len(links) == 2
    assert all(link.source_role == "primary" for link in links)


async def test_loader_idempotent_reload(migrated_session: AsyncSession) -> None:
    records = [
        _Record(service_slug="general_restaurants", mng_no="idem-1", lon=126.97, lat=37.56),
        _Record(service_slug="bakeries", mng_no="idem-2"),
    ]

    first = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert first.features_inserted == 2
    assert await _feature_count(migrated_session) == 2

    # 재적재 — 같은 source_record_key는 feature 본문을 건드리지 않고 last_seen만 갱신.
    second = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert second.bundles_total == 2
    assert second.features_inserted == 0
    assert second.features_updated == 0
    assert await _feature_count(migrated_session) == 2


async def test_loader_empty_when_all_skipped(migrated_session: AsyncSession) -> None:
    records = [
        _Record(service_slug="billiard_halls"),
        _Record(service_slug="hospitals"),
    ]
    result = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert result.bundles_total == 0
    assert result.features_inserted == 0
    count = (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features")
        )
    ).scalar_one()
    assert int(count) == 0


async def _active_entity_ids(session: AsyncSession) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT se.source_entity_id "
                "FROM feature.features f "
                "JOIN provider_sync.source_links sl ON sl.feature_id = f.feature_id "
                "JOIN provider_sync.source_entities se "
                "  ON se.source_entity_key = sl.source_entity_key "
                "WHERE f.lifecycle_state = 'active' AND sl.source_role = 'primary'"
            )
        )
    ).scalars().all()
    return set(rows)


async def test_snapshot_absence_retires_missing_features(
    migrated_session: AsyncSession,
) -> None:
    # 1차 적재 — 3건.
    first = [
        _Record(service_slug="general_restaurants", mng_no="keep-1"),
        _Record(service_slug="bakeries", mng_no="keep-2"),
        _Record(service_slug="public_baths", mng_no="gone-3"),
    ]
    await load_mois_license_features_bulk(migrated_session, first, fetched_at=_FETCHED)
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::keep-1",
        "bakeries::keep-2",
        "public_baths::gone-3",
    }

    # snapshot에 keep-1/keep-2만 → gone-3 retirement.
    snapshot = {"general_restaurants::keep-1", "bakeries::keep-2"}
    retired = await retire_mois_license_features_absent_from_snapshot(
        migrated_session, snapshot
    )
    await migrated_session.flush()
    assert retired == 1
    assert await _active_entity_ids(migrated_session) == snapshot

    # 재호출 idempotent — 이미 retired이므로 0건.
    again = await retire_mois_license_features_absent_from_snapshot(
        migrated_session, snapshot
    )
    assert again == 0

    # legacy timestamp/status 없이 retired/suppressed tuple만 확인한다.
    states = (
        await migrated_session.execute(
            text(
                "SELECT lifecycle_state, publication_state FROM feature.features"
            )
        )
    ).all()
    retired_rows = [row for row in states if row.lifecycle_state == "retired"]
    assert len(retired_rows) == 1
    assert retired_rows[0].publication_state == "suppressed"


async def test_sync_bulk_loads_and_prunes_in_one_call(
    migrated_session: AsyncSession,
) -> None:
    # 1차 snapshot — 2건.
    await sync_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="a"),
            _Record(service_slug="bakeries", mng_no="b"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::a",
        "bakeries::b",
    }

    # 2차 snapshot — a는 유지, b는 사라지고 c 신규 + EXCLUDED 1건(무시).
    result = await sync_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="a"),
            _Record(service_slug="public_baths", mng_no="c"),
            _Record(service_slug="billiard_halls", mng_no="excluded"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert result.load.bundles_total == 2  # a(update) + c(insert)
    assert result.retired == 1  # b
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::a",
        "public_baths::c",
    }


async def test_sync_bulk_empty_snapshot_retires_all(
    migrated_session: AsyncSession,
) -> None:
    await sync_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="bakeries", mng_no="solo")],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {"bakeries::solo"}

    # 빈 snapshot(전부 폐업) → 모두 retired 전이.
    result = await sync_mois_license_features_bulk(
        migrated_session, [], fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert result.load.bundles_total == 0
    assert result.retired == 1
    assert await _active_entity_ids(migrated_session) == set()


# -- run_mois_license_bulk_job (advisory lock + import_jobs 추적) -------------


async def _job_statuss(session: AsyncSession) -> list[tuple[str, str, int]]:
    rows = (
        await session.execute(
            text("SELECT kind, status, progress FROM ops.import_jobs ORDER BY created_at")
        )
    ).all()
    return [(r.kind, r.status, r.progress) for r in rows]


async def test_run_bulk_job_tracks_done_and_syncs(
    migrated_session: AsyncSession,
) -> None:
    result = await run_mois_license_bulk_job(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="j1"),
            _Record(service_slug="bakeries", mng_no="j2"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert result.acquired is True
    assert result.job is not None
    assert result.job.status == "done"
    assert result.job.progress == 100
    assert result.sync is not None
    assert result.sync.load.bundles_total == 2
    # import_jobs에 done 1건 기록.
    assert await _job_statuss(migrated_session) == [
        ("mois_license_full_update", "done", 100)
    ]
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::j1",
        "bakeries::j2",
    }


async def test_run_bulk_job_skips_when_lock_held(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession as _Session

    from kortravelmap.infra.advisory_lock import advisory_lock
    from kortravelmap.mois import _bulk_advisory_key  # type: ignore[attr-defined]
    from kortravelmap.providers.mois import DATASET_KEY_BULK

    # 다른 connection(별도 세션)이 같은 키 lock 보유 → run은 skip.
    async with (
        _Session(migrated_engine) as holder,
        advisory_lock(holder, _bulk_advisory_key(DATASET_KEY_BULK)),
    ):
        result = await run_mois_license_bulk_job(
            migrated_session,
            [_Record(service_slug="bakeries", mng_no="skip")],
            fetched_at=_FETCHED,
        )
        assert result.acquired is False
        assert result.job is None
        assert result.sync is None
    # 작업 row도, feature도 생성 안 됨.
    assert await _job_statuss(migrated_session) == []
    assert await _active_entity_ids(migrated_session) == set()


async def test_sync_bulk_streaming_batches_equivalent(
    migrated_session: AsyncSession,
) -> None:
    # batch_size=2로 5건 PROMOTED snapshot을 streaming 적재 → 전부 적재 + prune 정상.
    records = [
        _Record(service_slug="general_restaurants", mng_no=f"b{i}") for i in range(5)
    ]
    result = await sync_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED, batch_size=2
    )
    await migrated_session.flush()
    assert result.load.bundles_total == 5
    assert result.load.features_inserted == 5
    assert await _active_entity_ids(migrated_session) == {
        f"general_restaurants::b{i}" for i in range(5)
    }

    # 2차 snapshot(batch_size=2)에서 b0만 유지 → 나머지 4건 prune.
    result2 = await sync_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="general_restaurants", mng_no="b0")],
        fetched_at=_FETCHED,
        batch_size=2,
    )
    await migrated_session.flush()
    assert result2.retired == 4
    assert await _active_entity_ids(migrated_session) == {"general_restaurants::b0"}


# ── Step B: incremental(history) 적재 + cursor 전진 ──────────────────────


async def _active_count(session: AsyncSession) -> int:
    from sqlalchemy import func, select

    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(FeatureRow)
                .where(FeatureRow.lifecycle_state == "active")
            )
        ).scalar_one()
    )


async def test_incremental_job_loads_and_advances_cursor(
    migrated_session: AsyncSession,
) -> None:
    result = await run_mois_license_incremental_job(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="inc-1",
                    lon=126.97, lat=37.56),
            _Record(service_slug="bakeries", mng_no="inc-2"),
        ],
        fetched_at=_FETCHED,
        new_cursor={"last_modified_date": "2026-06-01"},
        sync_scope=_SYNC_SCOPE,
    )
    assert result.acquired is True
    assert result.job is not None
    assert result.job.status == "done"
    assert result.load is not None
    assert result.load.features_inserted == 2
    assert result.sync_state is not None
    assert result.sync_state.cursor == {"last_modified_date": "2026-06-01"}

    # cursor가 provider_sync_state에 영속화됨.
    state = await get_sync_state(
        migrated_session,
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_HISTORY,
        operation_key=_INCREMENTAL_OPERATION_KEY,
        sync_scope=_SYNC_SCOPE,
    )
    assert state is not None
    assert state.cursor == {"last_modified_date": "2026-06-01"}


async def test_incremental_does_not_prune_existing(
    migrated_session: AsyncSession,
) -> None:
    # 기존 feature 1건(history dataset)을 먼저 적재.
    await load_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="public_baths", mng_no="old-1")],
        fetched_at=_FETCHED,
        dataset_key=DATASET_KEY_HISTORY,
    )
    await migrated_session.flush()
    assert await _active_count(migrated_session) == 1

    # 증분으로 다른 record 적재 — 기존 record는 batch에 없지만 retirement 금지.
    await run_mois_license_incremental_job(
        migrated_session,
        [_Record(service_slug="bakeries", mng_no="new-1")],
        fetched_at=_FETCHED,
        new_cursor={"last_modified_date": "2026-06-02"},
        dataset_key=DATASET_KEY_HISTORY,
        sync_scope=_SYNC_SCOPE,
    )
    await migrated_session.flush()
    # 둘 다 active — prune 없음(Step B).
    assert await _active_count(migrated_session) == 2


# ── Step C: 폐업/취소 feature retirement ─────────────────────────────────


async def test_close_retires_matching_features(
    migrated_session: AsyncSession,
) -> None:
    # bulk 2건 적재.
    await load_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="keep-1"),
            _Record(service_slug="bakeries", mng_no="keep-2"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::keep-1",
        "bakeries::keep-2",
    }

    # 한 건 폐업 통지 → 해당 feature만 retired 전이.
    retired = await close_mois_license_features(
        migrated_session,
        [_Record(service_slug="general_restaurants", mng_no="keep-1")],
    )
    await migrated_session.flush()
    assert retired == 1
    assert await _active_entity_ids(migrated_session) == {"bakeries::keep-2"}


async def test_close_ignores_unmatched_records(
    migrated_session: AsyncSession,
) -> None:
    await load_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="bakeries", mng_no="b1")],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    # 미적재 mng_no 폐업 통지 — no-op.
    retired = await close_mois_license_features(
        migrated_session,
        [_Record(service_slug="bakeries", mng_no="never-loaded")],
    )
    await migrated_session.flush()
    assert retired == 0
    assert await _active_entity_ids(migrated_session) == {"bakeries::b1"}


async def test_run_closed_job_tracks_and_advances_cursor(
    migrated_session: AsyncSession,
) -> None:
    await load_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="general_restaurants", mng_no="c1")],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()

    result = await run_mois_license_closed_job(
        migrated_session,
        [_Record(service_slug="general_restaurants", mng_no="c1")],
        new_cursor={"last_modified_date": "2026-06-03"},
        sync_scope=_SYNC_SCOPE,
    )
    assert result.acquired is True
    assert result.job is not None
    assert result.job.status == "done"
    assert result.retired == 1
    assert result.sync_state is not None
    assert result.sync_state.cursor == {"last_modified_date": "2026-06-03"}

    # closed dataset cursor 영속.
    state = await get_sync_state(
        migrated_session,
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_CLOSED,
        operation_key=_CLOSED_OPERATION_KEY,
        sync_scope=_SYNC_SCOPE,
    )
    assert state is not None
    assert state.cursor == {"last_modified_date": "2026-06-03"}
    assert await _active_entity_ids(migrated_session) == set()


# ── Step D: on-demand 상세 (get_primary_source_detail) ───────────────────


async def test_primary_source_detail_round_trip(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.infra.feature_repo import get_primary_source_detail
    from kortravelmap.providers.mois import DATASET_KEY_BULK as _BULK

    await load_mois_license_features_bulk(
        migrated_session,
        [
            _Record(
                service_slug="general_restaurants",
                mng_no="d1",
                place_name="한식당 가나다",
                lon=126.97,
                lat=37.56,
            )
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()

    detail = await get_primary_source_detail(
        migrated_session,
        provider=PROVIDER_NAME,
        dataset_key=_BULK,
        source_entity_type="license_place",
        source_entity_id="general_restaurants::d1",
    )
    assert detail is not None
    assert detail["name"] == "한식당 가나다"
    assert detail["category"] == "02010100"
    assert detail["lifecycle_state"] == "active"
    assert detail["publication_state"] == "published"
    assert detail["quality_state"] == "valid"
    # 원본 provider payload(raw_data) 보존 — dict로 디시리얼라이즈.
    assert isinstance(detail["raw_data"], dict)
    assert detail["raw_data"].get("mng_no") == "d1"

    # 미적재 키 → None.
    missing = await get_primary_source_detail(
        migrated_session,
        provider=PROVIDER_NAME,
        dataset_key=_BULK,
        source_entity_type="license_place",
        source_entity_id="general_restaurants::never",
    )
    assert missing is None
