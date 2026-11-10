"""ADR-121 MCST 테마 목록 붙임 적재 — 실 PostGIS에서 apply·dry_run 경로.

각 테스트는 ``migrated_session``(테스트 끝에 rollback) 안에서 붙임 적재를 **Dagster runtime
role**로 돌린다 — 운영 적재가 그 로그인이라 superuser로는 권한 회귀를 못 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import feature_repo
from kortravelmap.infra import merge_repo as _merge_repo
from kortravelmap.infra.theme_attach_repo import (
    ThemeAttachMode,
    ThemeAttachReport,
    ThemeAttachSpec,
    load_theme_attach_bundles,
)
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME, file_rows_to_bundles
from tests.integration.conftest import as_api_runtime, as_dagster_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)

#: 서울 밖 빈 좌표대 — 다른 모듈의 seed와 150m 안에서 겹치지 않게 한다.
_LON, _LAT = 128.7012, 36.1234


def _offset(meters_east: float) -> tuple[float, float]:
    return _LON + meters_east / 89_700.0, _LAT


def _master_bundle(name: str, lonlat: tuple[float, float], key: str) -> FeatureBundle:
    """비MCST master(박물관 표준) place bundle."""

    raw = {"name": name, "key": key}
    payload_hash = make_payload_hash(raw)
    record_key = make_source_record_key(
        provider="data.go.kr-standard",
        dataset_key="datagokr_museums",
        source_entity_type="museum",
        source_entity_id=key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=None,
        kind="place",
        category="01040100",
        source_type="data.go.kr-standard:datagokr_museums",
        source_natural_key=key,
    )
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=key,
        kind=FeatureKind.PLACE,
        name=name,
        coord=Coordinate(lon=Decimal(str(lonlat[0])), lat=Decimal(str(lonlat[1]))),
        address=Address(admin="경상북도 테스트군"),
        category="01040100",
        marker_icon="museum",
        marker_color="P-12",
        detail=PlaceDetail(feature_id=feature_id, place_kind="museum"),
    )
    return FeatureBundle(
        feature=feature,
        source_record=SourceRecord(
            provider="data.go.kr-standard",
            dataset_key="datagokr_museums",
            source_entity_type="museum",
            source_entity_id=key,
            raw_payload_hash=payload_hash,
            raw_data=raw,
            fetched_at=_FETCHED,
            imported_at=_FETCHED,
            source_record_key=record_key,
        ),
        source_link=SourceLink(
            feature_id=feature_id,
            source_record_key=record_key,
            source_role=SourceRole.PRIMARY,
            match_method="natural_key",
            confidence=100,
        ),
    )


async def _mcst_bundles(slug: str, *rows: tuple[str, tuple[float, float]]) -> list[FeatureBundle]:
    return await file_rows_to_bundles(
        [
            {
                "TITLE": name,
                "ADDRESS": f"경상북도 테스트군 테스트로 {index}",
                "COORDINATES": f"N{lonlat[1]}, E{lonlat[0]}",
                "CATEGORY1": "문화관광/명소",
                "CATEGORY2": "박물관",
            }
            for index, (name, lonlat) in enumerate(rows)
        ],
        slug=slug,
        fetched_at=_FETCHED,
    )


def _spec(slug: str) -> ThemeAttachSpec:
    spec = MCST_FILE_DATASETS[slug]
    return ThemeAttachSpec(
        provider=MCST_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        master_category_prefixes=spec.master_category_prefixes,
    )


async def _attach(
    session: AsyncSession, slug: str, bundles: list[FeatureBundle], mode: ThemeAttachMode
) -> ThemeAttachReport:
    async with session.begin_nested(), as_dagster_runtime(session):
        _, report = await load_theme_attach_bundles(
            session, bundles, spec=_spec(slug), mode=mode
        )
    return report


async def _feature_of_entity(session: AsyncSession, natural_key: str, dataset_key: str) -> list[
    tuple[str, str]
]:
    rows = (
        await session.execute(
            text(
                "SELECT CAST(sl.feature_id AS text), sl.source_role "
                "FROM provider_sync.source_links sl "
                "JOIN provider_sync.source_entities se "
                "  ON se.source_entity_key = sl.source_entity_key "
                "JOIN provider_sync.provider_datasets pd "
                "  ON pd.provider_dataset_id = se.provider_dataset_id "
                "WHERE se.source_entity_id = :key AND pd.dataset_key = :dataset_key"
            ),
            {"key": natural_key, "dataset_key": dataset_key},
        )
    ).all()
    return [(str(row[0]), str(row[1])) for row in rows]


async def _attributes(session: AsyncSession, feature_id: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT dpa.attribute_code "
                "FROM provider_sync.source_links sl "
                "JOIN provider_sync.source_entities se "
                "  ON se.source_entity_key = sl.source_entity_key "
                "JOIN feature.dataset_place_attributes dpa "
                "  ON dpa.provider_dataset_id = se.provider_dataset_id "
                " AND dpa.source_entity_type = se.source_entity_type "
                "WHERE sl.feature_id = CAST(:feature_id AS uuid) "
                "  AND sl.source_role IN ('primary', 'enrichment')"
            ),
            {"feature_id": feature_id},
        )
    ).scalars()
    return set(rows)


async def _master_id(session: AsyncSession, key: str) -> str:
    links = await _feature_of_entity(session, key, "datagokr_museums")
    assert len(links) == 1
    return links[0][0]


async def _decision(session: AsyncSession, natural_key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT state, CAST(target_feature_id AS text) AS target "
                "FROM provider_sync.theme_attach_decisions WHERE natural_key = :key"
            ),
            {"key": natural_key},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def test_attribute_row_attaches_to_master_without_new_feature(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    await feature_repo.load_bundles(
        session, [_master_bundle("국립테스트박물관", _offset(0), "ta-master-1")]
    )
    master = await _master_id(session, "ta-master-1")
    [row] = await _mcst_bundles("barrier_free_places_csv", ("국립테스트박물관", _offset(10)))

    report = await _attach(session, "barrier_free_places_csv", [row], "apply")

    assert report.counts == {"matched": 1}
    links = await _feature_of_entity(
        session, str(row.feature.provider_natural_key), "mcst_barrier_free_places_csv"
    )
    assert links == [(master, "enrichment")]
    assert await _attributes(session, master) == {"barrier_free"}
    decision = await _decision(session, str(row.feature.provider_natural_key))
    assert decision == {"state": "matched", "target": master}

    # 목록에서 빠지면 속성만 사라지고 master는 그대로다.
    report = await _attach(session, "barrier_free_places_csv", [], "apply")
    assert report.enrichment_links_removed == 1
    assert await _attributes(session, master) == set()
    state = (
        await session.execute(
            text("SELECT lifecycle_state FROM feature.features WHERE feature_id = :id"),
            {"id": master},
        )
    ).scalar_one()
    assert state == "active"
    assert await _decision(session, str(row.feature.provider_natural_key)) is None


async def test_same_place_in_two_lists_is_one_feature_with_attributes(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    [owner] = await _mcst_bundles("independent_bookstores_csv", ("책방테스트오늘", _offset(500)))
    [attr] = await _mcst_bundles(
        "family_infant_culture_facilities_csv", ("책방테스트오늘", _offset(505))
    )

    first = await _attach(session, "independent_bookstores_csv", [owner], "apply")
    second = await _attach(session, "family_infant_culture_facilities_csv", [attr], "apply")

    assert first.counts == {"created": 1}
    assert second.counts == {"matched": 1}
    [(owner_feature, owner_role)] = await _feature_of_entity(
        session, str(owner.feature.provider_natural_key), "mcst_independent_bookstores_csv"
    )
    [(attr_feature, attr_role)] = await _feature_of_entity(
        session, str(attr.feature.provider_natural_key), "mcst_family_infant_culture_facilities_csv"
    )
    assert (owner_role, attr_role) == ("primary", "enrichment")
    assert owner_feature == attr_feature
    assert await _attributes(session, owner_feature) == {"bookstore_independent", "family_friendly"}

    # 다시 적재하면 owner·sticky이고 Feature는 늘지 않는다.
    again = await _attach(session, "family_infant_culture_facilities_csv", [attr], "apply")
    assert again.counts == {"sticky": 1}
    assert (await _attach(session, "independent_bookstores_csv", [owner], "apply")).counts == {
        "owner": 1
    }


async def test_duplicate_rows_in_one_list_collapse_to_one_feature(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    rows = await _mcst_bundles(
        "leisure_activity_facilities_csv",
        ("테스트레저파크", _offset(1000)),
        ("테스트레저파크", _offset(1004)),
    )
    report = await _attach(session, "leisure_activity_facilities_csv", rows, "apply")
    assert report.counts == {"created": 1, "matched": 1}
    targets = {
        feature
        for bundle in rows
        for feature, _ in await _feature_of_entity(
            session,
            str(bundle.feature.provider_natural_key),
            "mcst_leisure_activity_facilities_csv",
        )
    }
    assert len(targets) == 1


async def test_dry_run_counts_without_changing_legacy_load(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    await feature_repo.load_bundles(
        session, [_master_bundle("드라이런테스트관", _offset(2000), "ta-master-dry")]
    )
    [row] = await _mcst_bundles("barrier_free_places_csv", ("드라이런테스트관", _offset(2005)))

    report = await _attach(session, "barrier_free_places_csv", [row], "dry_run")

    assert report.mode == "dry_run"
    assert report.counts == {"matched": 1}
    # 현행 적재 그대로 — MCST가 primary인 자기 Feature가 생긴다.
    [(_, role)] = await _feature_of_entity(
        session, str(row.feature.provider_natural_key), "mcst_barrier_free_places_csv"
    )
    assert role == "primary"
    assert await _decision(session, str(row.feature.provider_natural_key)) is None


async def test_retired_claim_redirects_to_merge_survivor(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    [row] = await _mcst_bundles("barrier_free_places_csv", ("병합테스트기념관", _offset(3000)))
    natural_key = str(row.feature.provider_natural_key)
    await feature_repo.load_bundles(session, [row])  # 현행(목록별) Feature
    [(legacy_feature, _)] = await _feature_of_entity(
        session, natural_key, "mcst_barrier_free_places_csv"
    )
    await feature_repo.load_bundles(
        session, [_master_bundle("병합테스트기념관", _offset(3002), "ta-master-merge")]
    )
    master = await _master_id(session, "ta-master-merge")
    async with session.begin_nested(), as_api_runtime(session):
        await _merge_repo.apply_feature_merge(
            session, master_id=master, loser_id=legacy_feature, merged_by="test"
        )
    # 병합이 link를 강등해 옮겼다 — 다음 적재는 sticky다.
    assert await _feature_of_entity(session, natural_key, "mcst_barrier_free_places_csv") == [
        (master, "enrichment")
    ]
    sticky = await _attach(session, "barrier_free_places_csv", [row], "apply")
    assert sticky.counts == {"sticky": 1}

    # link가 없어도(퇴역 claim만 남음) 병합 이력을 따라 생존자로 간다.
    # 퇴역 Feature를 되살리지 않는다.
    await session.execute(
        text(
            "DELETE FROM provider_sync.source_links sl USING provider_sync.source_entities se "
            "WHERE se.source_entity_key = sl.source_entity_key AND se.source_entity_id = :key"
        ),
        {"key": natural_key},
    )
    redirected = await _attach(session, "barrier_free_places_csv", [row], "apply")
    assert redirected.counts == {"redirected": 1}
    assert await _feature_of_entity(session, natural_key, "mcst_barrier_free_places_csv") == [
        (master, "enrichment")
    ]
    state = (
        await session.execute(
            text("SELECT lifecycle_state FROM feature.features WHERE feature_id = :id"),
            {"id": legacy_feature},
        )
    ).scalar_one()
    assert state == "retired"


async def test_empty_snapshot_cannot_wipe_dataset_attributes(
    migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import theme_attach_repo
    from kortravelmap.infra.theme_attach_repo import ThemeAttachLossGuardError

    monkeypatch.setattr(theme_attach_repo, "_MIN_GUARDED_LINKS", 1)
    session = migrated_session
    await feature_repo.load_bundles(
        session, [_master_bundle("손실가드테스트관", _offset(4000), "ta-master-guard")]
    )
    [row] = await _mcst_bundles("barrier_free_places_csv", ("손실가드테스트관", _offset(4003)))
    assert (await _attach(session, "barrier_free_places_csv", [row], "apply")).counts == {
        "matched": 1
    }
    with pytest.raises(ThemeAttachLossGuardError):
        await _attach(session, "barrier_free_places_csv", [], "apply")
    master = await _master_id(session, "ta-master-guard")
    assert await _attributes(session, master) == {"barrier_free"}


async def test_non_merge_retired_claim_goes_back_to_owner_path(
    migrated_session: AsyncSession,
) -> None:
    """provider 퇴역(병합 아님)은 기존 적재의 재활성 규칙으로 넘긴다 — unresolved로 묻지 않는다."""

    session = migrated_session
    [row] = await _mcst_bundles("barrier_free_places_csv", ("퇴역복귀테스트관", _offset(5000)))
    natural_key = str(row.feature.provider_natural_key)
    await feature_repo.load_bundles(session, [row])
    [(feature_id, _)] = await _feature_of_entity(
        session, natural_key, "mcst_barrier_free_places_csv"
    )
    retired = await feature_repo.retire_features_absent_from_snapshot(
        session,
        provider=MCST_PROVIDER_NAME,
        dataset_key="mcst_barrier_free_places_csv",
        source_entity_type="culture_place",
        snapshot_source_entity_ids=set(),
    )
    assert retired >= 1

    report = await _attach(session, "barrier_free_places_csv", [row], "apply")

    assert report.counts == {"owner": 1}
    state = (
        await session.execute(
            text("SELECT lifecycle_state FROM feature.features WHERE feature_id = :id"),
            {"id": feature_id},
        )
    ).scalar_one()
    assert state == "active"
