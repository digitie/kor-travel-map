"""재개형 적재의 "이미 그대로 있는가" 판정과 재관측 SQL — 실 PostGIS, 실 ``load_bundle`` (ADR-108).

대역 테스트는 판정 **의미**를 시험하고, 여기서는 그 의미를 SQL이 실제로 구현하는지 본다.
판정이 틀리면 둘 중 하나가 된다 — 바뀐 행을 건너뛰어 조용히 낡거나(위험), 그대로인 행을
매번 다시 지오코딩해 재개가 무의미해진다(낭비). 둘 다 여기서 빨개져야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.dto import kst_now
from kortravelmap.infra.feature_repo import (
    ProviderEntityReobservationConflict,
    find_unchanged_active_source_entities,
    load_bundles,
    reobserve_unchanged_source_entities,
    retire_features_by_source_entity_ids,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    PROVIDER_NAME,
    license_record_payload_hash,
    license_records_to_bundles,
    license_source_entity_id,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_ENTITY_TYPE = "license_place"


@dataclass(frozen=True)
class _Record:
    service_slug: str
    mng_no: str | None
    place_name: str | None = "재개 테스트"
    is_open: bool | None = True
    legal_dong_code: str | None = "1111010100"
    lon: float | None = 126.978
    lat: float | None = 37.566
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
    road_name_code: str | None = None
    building_management_number: str | None = None
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


_KW = {
    "provider": PROVIDER_NAME,
    "dataset_key": DATASET_KEY_BULK,
    "source_entity_type": _ENTITY_TYPE,
}


def _records(tag: str) -> list[_Record]:
    return [_Record(service_slug="bakeries", mng_no=f"resume-{tag}-{i}") for i in range(3)]


def _hashes(records: list[_Record]) -> dict[str, str]:
    return {license_source_entity_id(r): license_record_payload_hash(r) for r in records}


async def _load(session: AsyncSession, records: list[_Record]) -> None:
    bundles = await license_records_to_bundles(
        records, fetched_at=kst_now(), dataset_key=DATASET_KEY_BULK
    )
    await load_bundles(session, bundles)


async def _observed(session: AsyncSession, entity_ids: list[str]) -> dict[str, object]:
    rows = (
        await session.execute(
            text(
                """
                SELECT entity.source_entity_id, head.observed_at, entity.last_seen_at
                FROM provider_sync.source_entities AS entity
                JOIN provider_sync.source_entity_heads AS head
                  ON head.source_entity_key = entity.source_entity_key
                WHERE entity.source_entity_id = ANY(CAST(:ids AS text[]))
                """
            ),
            {"ids": entity_ids},
        )
    ).all()
    return {str(r.source_entity_id): (r.observed_at, r.last_seen_at) for r in rows}


async def test_loaded_rows_are_found_unchanged_and_changed_rows_are_not(
    migrated_session: AsyncSession,
) -> None:
    records = _records("a")
    hashes = _hashes(records)
    assert await find_unchanged_active_source_entities(
        migrated_session, payload_hashes=hashes, **_KW
    ) == frozenset(), "적재 전인데 그대로라고 한다 — 재개가 아무것도 적재하지 않는다"

    await _load(migrated_session, records)

    assert await find_unchanged_active_source_entities(
        migrated_session, payload_hashes=hashes, **_KW
    ) == frozenset(hashes)

    changed = dict(hashes)
    first = license_source_entity_id(records[0])
    changed[first] = license_record_payload_hash(
        _Record(service_slug="bakeries", mng_no=records[0].mng_no, place_name="상호 변경")
    )
    assert await find_unchanged_active_source_entities(
        migrated_session, payload_hashes=changed, **_KW
    ) == frozenset(hashes) - {first}, "payload가 바뀐 행을 건너뛰면 조용히 낡는다"


async def test_retired_feature_is_not_reported_unchanged(
    migrated_session: AsyncSession,
) -> None:
    records = _records("b")
    hashes = _hashes(records)
    await _load(migrated_session, records)
    retired = license_source_entity_id(records[1])

    await retire_features_by_source_entity_ids(
        migrated_session, source_entity_ids={retired}, **_KW
    )

    assert await find_unchanged_active_source_entities(
        migrated_session, payload_hashes=hashes, **_KW
    ) == frozenset(hashes) - {retired}


async def test_reobservation_moves_time_forward_once_and_detects_drift(
    migrated_session: AsyncSession,
) -> None:
    records = _records("c")
    hashes = _hashes(records)
    await _load(migrated_session, records)
    before = await _observed(migrated_session, list(hashes))
    later = kst_now() + timedelta(days=1)

    touched = await reobserve_unchanged_source_entities(
        migrated_session, payload_hashes=hashes, observed_at=later, **_KW
    )
    after = await _observed(migrated_session, list(hashes))

    assert touched == len(hashes)
    for entity_id in hashes:
        assert after[entity_id] == (later, later), entity_id
        assert before[entity_id] != after[entity_id]

    # 같은 snapshot 시각으로 다시 돌린 run은 아무것도 다시 쓰지 않는다.
    assert (
        await reobserve_unchanged_source_entities(
            migrated_session, payload_hashes=hashes, observed_at=later, **_KW
        )
        == 0
    )

    stale = dict(hashes)
    stale[license_source_entity_id(records[2])] = "0" * 64
    with pytest.raises(ProviderEntityReobservationConflict):
        await reobserve_unchanged_source_entities(
            migrated_session, payload_hashes=stale, observed_at=later, **_KW
        )


async def test_empty_inputs_do_not_touch_the_database(
    migrated_session: AsyncSession,
) -> None:
    assert (
        await find_unchanged_active_source_entities(migrated_session, payload_hashes={}, **_KW)
        == frozenset()
    )
    assert (
        await reobserve_unchanged_source_entities(
            migrated_session, payload_hashes={}, observed_at=kst_now(), **_KW
        )
        == 0
    )


# -- ADR-108 §3a-3: 역지오코딩 불가 표식(finding 재사용) ------------------------------------


async def _seed_marker(
    session: AsyncSession, *, dedupe_key: str, source_record_key: str
) -> None:
    from kortravelmap.infra.feature_repo import resolve_active_provider_dataset_id
    from kortravelmap.infra.integrity_violation_repo import sync_integrity_findings

    dataset_id = await resolve_active_provider_dataset_id(
        session, provider=PROVIDER_NAME, dataset_key=DATASET_KEY_BULK
    )
    await sync_integrity_findings(
        session,
        provider_dataset_id=dataset_id,
        findings=[
            {
                "provider": PROVIDER_NAME,
                "dataset_key": DATASET_KEY_BULK,
                "source_record_key": None,
                "feature_id": None,
                "violation_type": "mois_reverse_geocode_unresolvable",
                "severity": "info",
                "message": "marker",
                "payload": {
                    "dedupe_key": dedupe_key,
                    "occurrence_count": 1,
                    "source_record_key": source_record_key,
                },
            }
        ],
    )


def _marker_key(entity_id: str) -> str:
    from kortravelmap.core.ids import make_integrity_finding_key

    return make_integrity_finding_key(
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_BULK,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=entity_id,
        violation_type="mois_reverse_geocode_unresolvable",
    )


async def test_fresh_open_marker_matches_only_the_same_payload_and_ages_out(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.infra.integrity_violation_repo import find_fresh_open_findings

    marker = _marker_key("bakeries::adr108-marker")
    missing = _marker_key("bakeries::adr108-never-marked")
    await _seed_marker(migrated_session, dedupe_key=marker, source_record_key="srk-a")

    async def _find(expected: dict[str, str], *, days: int = 30) -> frozenset[str]:
        return await find_fresh_open_findings(
            migrated_session,
            violation_type="mois_reverse_geocode_unresolvable",
            expected_source_record_keys=expected,
            max_age_days=days,
        )

    assert await _find({marker: "srk-a"}) == frozenset({marker})
    assert await _find({marker: "srk-changed"}) == frozenset()
    assert await _find({missing: "srk-a"}) == frozenset()

    await migrated_session.execute(
        text(
            "UPDATE ops.data_integrity_violations SET last_seen_at = now() - interval '31 days' "
            "WHERE payload ->> 'dedupe_key' = :key"
        ),
        {"key": marker},
    )
    assert await _find({marker: "srk-a"}) == frozenset(), "낡은 표식을 믿었다"

    await migrated_session.execute(
        text(
            "UPDATE ops.data_integrity_violations SET status = 'resolved', last_seen_at = now(), "
            "resolved_at = now() WHERE payload ->> 'dedupe_key' = :key"
        ),
        {"key": marker},
    )
    assert await _find({marker: "srk-a"}) == frozenset(), "닫힌 표식을 믿었다"


async def test_resolving_a_marker_closes_only_open_findings_of_that_type(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.infra.integrity_violation_repo import (
        find_fresh_open_findings,
        resolve_open_findings_by_key,
    )

    marker = _marker_key("bakeries::adr108-resolve")
    await _seed_marker(migrated_session, dedupe_key=marker, source_record_key="srk-r")

    assert (
        await resolve_open_findings_by_key(
            migrated_session,
            violation_type="mois_reverse_geocode_unresolvable",
            dedupe_keys=[_marker_key("bakeries::adr108-not-marked")],
            reason="test",
        )
        == 0
    )
    assert (
        await resolve_open_findings_by_key(
            migrated_session,
            violation_type="mois_reverse_geocode_unresolvable",
            dedupe_keys=[marker, marker],
            reason="reverse geocode resolved",
        )
        == 1
    )
    assert (
        await find_fresh_open_findings(
            migrated_session,
            violation_type="mois_reverse_geocode_unresolvable",
            expected_source_record_keys={marker: "srk-r"},
            max_age_days=30,
        )
        == frozenset()
    )
    status = (
        await migrated_session.execute(
            text(
                "SELECT status FROM ops.data_integrity_violations "
                "WHERE payload ->> 'dedupe_key' = :key"
            ),
            {"key": marker},
        )
    ).scalar_one()
    assert status == "resolved"
