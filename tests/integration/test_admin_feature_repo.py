"""``admin_feature_repo`` 통합 테스트 (ADR-045 T-207c)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import md5
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address, Coordinate, Feature, PlaceDetail
from kortravelmap.infra import feature_repo
from kortravelmap.infra.admin_feature_repo import (
    AdminFeatureStateConflict,
    AdminFeatureStatePreconditionFailed,
    apply_feature_change_request,
    get_feature_row_revision,
    list_admin_feature_state_transitions,
    list_admin_features,
    list_dedup_reviews,
    merge_dedup_review,
    reactivate_admin_feature_state,
    set_dedup_review_decision,
    submit_feature_change_request,
    transition_admin_feature_state,
)
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_repo import upsert_feature
from kortravelmap.infra.models import (
    DedupReviewQueueRow,
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._subtype_seed import seed_feature_subtype

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _feature_row(
    feature_id: str,
    *,
    name: str,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> FeatureRow:
    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name=name,
        category="01070300",
        coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
        address={"road": "서울특별시 종로구 세종대로 1"},
        urls={},
        raw_refs=[],
        lifecycle_state=lifecycle_state,
        publication_state=publication_state,
        quality_state=quality_state,
        created_at=_NOW,
        updated_at=_NOW,
    )


_PROVIDER = "python-mois-api"
_DATASET_KEY = "mois_license_features_bulk"

_CATALOG_ID_SQL = """
SELECT provider_dataset_id
FROM provider_sync.provider_datasets
WHERE provider = :provider AND dataset_key = :dataset_key
"""

_RUNTIME_LOGIN = "ktm_feature_api_runtime"
_RUNTIME_CREDENTIAL = uuid4().hex


async def _provision_runtime_login(engine: AsyncEngine) -> None:
    """Disposable integration DB에 실제 runtime LOGIN을 만들고 group만 상속한다."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DO $runtime_login$ "
                "BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles "
                f"WHERE rolname = '{_RUNTIME_LOGIN}') THEN "
                f"CREATE ROLE {_RUNTIME_LOGIN} LOGIN NOINHERIT NOSUPERUSER "
                f"NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION "
                f"PASSWORD '{_RUNTIME_CREDENTIAL}'; "
                "END IF; "
                "END "
                "$runtime_login$"
            )
        )
        await connection.execute(
            text(
                f"ALTER ROLE {_RUNTIME_LOGIN} LOGIN NOINHERIT NOSUPERUSER "
                f"NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION "
                f"PASSWORD '{_RUNTIME_CREDENTIAL}'"
            )
        )
        await connection.execute(
            text(
                f"GRANT ktm_feature_runtime TO {_RUNTIME_LOGIN} "
                "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE"
            )
        )


async def _runtime_engine(engine: AsyncEngine) -> AsyncEngine:
    await _provision_runtime_login(engine)
    runtime_url = engine.url.set(username=_RUNTIME_LOGIN, password=_RUNTIME_CREDENTIAL)
    return make_async_engine(runtime_url.render_as_string(hide_password=False), pool_size=1)


async def _provider_dataset_id(session: AsyncSession) -> int:
    """T-VN-33: source lineage identity는 catalog FK 하나뿐이다."""

    return int(
        (
            await session.execute(
                text(_CATALOG_ID_SQL),
                {"provider": _PROVIDER, "dataset_key": _DATASET_KEY},
            )
        ).scalar_one()
    )


def _source_entity(key: str, provider_dataset_id: int) -> SourceEntityRow:
    return SourceEntityRow(
        source_entity_key=f"se-{key}",
        provider_dataset_id=provider_dataset_id,
        source_entity_type="license_place",
        source_entity_id=key,
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )


def _source_record(key: str) -> SourceRecordRow:
    return SourceRecordRow(
        source_record_key=key,
        source_entity_key=f"se-{key}",
        # raw_payload_hash는 ``^[0-9a-f]{1,64}$`` CHECK를 만족해야 한다.
        raw_payload_hash=md5(key.encode("utf-8")).hexdigest(),
        raw_data={"id": key},
        fetched_at=_NOW,
        imported_at=_NOW,
    )


def _source_link(feature_id: str, source_record_key: str) -> SourceLinkRow:
    return SourceLinkRow(
        feature_id=feature_id,
        source_entity_key=f"se-{source_record_key}",
        source_role="primary",
        match_method="natural_key",
        confidence=100,
        created_at=_NOW,
    )


def _provider_source_membership(
    feature_id: str,
) -> feature_repo._ProviderSourceMembership:
    """`_seed_feature`가 만든 canonical source proof를 writer에 전달한다."""
    source_record_key = f"sr-{feature_id}"
    return feature_repo._ProviderSourceMembership(
        source_entity_key=f"se-{source_record_key}",
        source_record_key=source_record_key,
    )


def _dto(
    feature_id: str,
    *,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind="place",
        name="광화문 재적재",
        category="01070300",
        coord=Coordinate(lon=Decimal("126.9769"), lat=Decimal("37.5759")),
        address=Address(
            road="서울특별시 종로구 세종대로 1",
            bjd_code="1111010100",
            sigungu_code="11110",
            sido_code="11",
        ),
        marker_icon="marker",
        marker_color="P-01",
        detail=PlaceDetail(feature_id=feature_id, place_kind="attraction"),
        lifecycle_state=lifecycle_state,
        publication_state=publication_state,
        quality_state=quality_state,
        created_at=_NOW,
        updated_at=_NOW + timedelta(minutes=5),
    )


async def _seed_feature(
    session: AsyncSession,
    feature_id: str = "feature-admin-1",
) -> None:
    session.add(_feature_row(feature_id, name="광화문"))
    entity = _source_entity(f"sr-{feature_id}", await _provider_dataset_id(session))
    session.add(entity)
    await session.flush()
    session.add(_source_record(f"sr-{feature_id}"))
    await session.flush()
    # T-VN-33: 현재 record 포인터는 entity가 아니라 head가 소유한다.
    session.add(
        SourceEntityHeadRow(
            source_entity_key=f"se-sr-{feature_id}",
            current_source_record_key=f"sr-{feature_id}",
            observed_at=_NOW,
        )
    )
    await session.flush()
    session.add(_source_link(feature_id, f"sr-{feature_id}"))
    await session.flush()


async def _merge_dedup_review_with_short_lock_timeout(
    session: AsyncSession, review_id: str
) -> None:
    await session.execute(text("SET LOCAL lock_timeout = '100ms'"))
    await merge_dedup_review(
        session,
        review_id,
        master_feature_id="feature-admin-lock-a",
    )


async def test_admin_retire_reactivate_is_atomic_and_auditable(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-reactivation"
    await _seed_feature(migrated_session, feature_id)
    initial_revision = await get_feature_row_revision(migrated_session, feature_id)
    assert initial_revision is not None

    retired = await transition_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=initial_revision,
        reason_code="admin_retire",
        operator="local-admin",
        action="retire",
    )
    assert (
        retired.lifecycle_state,
        retired.publication_state,
        retired.quality_state,
    ) == ("retired", "suppressed", "valid")
    assert retired.row_revision > initial_revision
    assert retired.audit_transition_id > 0

    # 일반 provider writer는 admin retirement override를 우회하지 못한다.
    inserted = await upsert_feature(
        migrated_session,
        _dto(feature_id),
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_membership=_provider_source_membership(feature_id),
    )
    assert inserted is False

    reactivation_revision = await get_feature_row_revision(
        migrated_session, feature_id
    )
    assert reactivation_revision is not None

    reactivated = await reactivate_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=reactivation_revision,
        reason_code="admin_source_reactivated",
        operator="local-admin",
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_entity_key=f"se-sr-{feature_id}",
        source_record_key=f"sr-{feature_id}",
    )
    assert (
        reactivated.lifecycle_state,
        reactivated.publication_state,
        reactivated.quality_state,
    ) == ("active", "suppressed", "valid")
    assert reactivated.row_revision > reactivation_revision

    timeline = await list_admin_feature_state_transitions(
        migrated_session, feature_id, limit=10
    )
    assert [item.transition_id for item in timeline.items] == sorted(
        (item.transition_id for item in timeline.items), reverse=True
    )
    assert {retired.audit_transition_id, reactivated.audit_transition_id}.issubset(
        {item.transition_id for item in timeline.items}
    )


async def test_admin_state_transition_rejects_stale_revision(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-stale-revision"
    await _seed_feature(migrated_session, feature_id)
    revision = await get_feature_row_revision(migrated_session, feature_id)
    assert revision is not None

    await transition_admin_feature_state(
        migrated_session,
        feature_id,
        publication_state="suppressed",
        expected_row_revision=revision,
        reason_code="admin_suppress",
        operator="local-admin",
        action="patch",
    )
    with pytest.raises(AdminFeatureStatePreconditionFailed):
        await transition_admin_feature_state(
            migrated_session,
            feature_id,
            quality_state="quarantined",
            expected_row_revision=revision,
            reason_code="admin_quarantine",
            operator="local-admin",
            action="patch",
        )


async def test_user_update_version_overrides_provider_reload(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-update"
    await _seed_feature(migrated_session, feature_id)

    request = await submit_feature_change_request(
        migrated_session,
        action="update",
        feature_id=feature_id,
        payload={
            "name": "사용자 수정 이름",
            "road_name_code": "111104100001",
            "admin_dong_code": "1111051500",
            "urls": {"homepage": "https://example.test/user-feature"},
            # T-VN-35(ADR-086): admin detail도 kind별 typed 컬럼으로 들어가므로
            # 필수 필드(place_kind)를 갖춘 shape이어야 한다. 자유 키는 payload로.
            "detail": {"place_kind": "attraction", "payload": {"note": "사용자 수정"}},
        },
        review_mode="immediate",
        reason="사용자 제보 반영",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert request.state == "applied"

    second_request = await submit_feature_change_request(
        migrated_session,
        action="update",
        feature_id=feature_id,
        payload={
            "name": "사용자 수정 이름 2",
            "detail": {
                "place_kind": "attraction",
                "payload": {"note": "사용자 수정 2"},
            },
        },
        review_mode="immediate",
        reason="사용자 제보 추가 반영",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert second_request.state == "applied"

    inserted = await upsert_feature(
        migrated_session,
        _dto(feature_id),
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_membership=_provider_source_membership(feature_id),
    )
    assert inserted is False

    row = await feature_repo.get_feature_row(migrated_session, feature_id)
    assert row is not None
    provenance = (
        await migrated_session.execute(
            text(
                "SELECT data_origin, data_version "
                "FROM feature.features WHERE feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["name"] == "사용자 수정 이름 2"
    assert row["road_name_code"] == "111104100001"
    assert row["admin_dong_code"] == "1111051500"
    assert row["urls"]["homepage"] == "https://example.test/user-feature"
    assert row["detail"]["payload"]["note"] == "사용자 수정 2"
    assert provenance["data_origin"] == "user_request"
    assert provenance["data_version"] == 2

    versions = (
        await migrated_session.execute(
            text(
                """
                SELECT version, origin, change_kind
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                ORDER BY version
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    assert [(v["version"], v["origin"], v["change_kind"]) for v in versions] == [
        (1, "user_request", "update"),
        (2, "user_request", "update"),
    ]
    version_payloads = (
        await migrated_session.execute(
            text(
                """
                SELECT version, payload
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                  AND version IN (1, 2)
                ORDER BY version
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    assert version_payloads[0]["payload"]["name"] == "사용자 수정 이름"
    assert version_payloads[0]["payload"]["data_version"] == 1
    assert version_payloads[1]["payload"]["name"] == "사용자 수정 이름 2"
    assert version_payloads[1]["payload"]["data_version"] == 2


async def test_admin_runtime_login_uses_procedures_for_add_update_delete_and_provider_lifecycle(
    migrated_engine: AsyncEngine,
) -> None:
    """runtime LOGIN은 direct provenance DML 없이 typed writer만 실행한다."""
    feature_id = f"feature-admin-runtime-update-{uuid4().hex}"
    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as seed_session,
        seed_session.begin(),
    ):
        await _seed_feature(seed_session, feature_id)
        provider_dataset_id = await _provider_dataset_id(seed_session)

    runtime_engine = await _runtime_engine(migrated_engine)
    try:
        async with (
            AsyncSession(runtime_engine, expire_on_commit=False) as runtime_session,
            runtime_session.begin(),
        ):
            expected_row_revision = await get_feature_row_revision(
                runtime_session, feature_id
            )
            assert expected_row_revision is not None
            request = await submit_feature_change_request(
                runtime_session,
                action="update",
                feature_id=feature_id,
                payload={"name": "runtime provenance writer"},
                review_mode="immediate",
                reason="runtime security provenance receipt",
                requested_by="runtime-admin",
                expected_row_revision=expected_row_revision,
            )
            assert request.state == "applied"
            row = (
                await runtime_session.execute(
                    text(
                        """
                        SELECT name, data_origin, data_version
                        FROM feature.features
                        WHERE feature_id = :feature_id
                        """
                    ),
                    {"feature_id": feature_id},
                )
            ).mappings().one()
            assert dict(row) == {
                "name": "runtime provenance writer",
                "data_origin": "user_request",
                "data_version": 1,
            }
            provider_context = json.dumps(
                {
                    "transition_kind": "provider_sync",
                    "reason_code": "runtime_provider_retire",
                    "provider_dataset_id": provider_dataset_id,
                    "source_entity_key": f"se-sr-{feature_id}",
                    "source_record_key": f"sr-{feature_id}",
                },
                ensure_ascii=False,
            )
            revision_before_retire = await get_feature_row_revision(
                runtime_session, feature_id
            )
            assert revision_before_retire is not None
            retired = (
                await runtime_session.execute(
                    text(feature_repo._TRANSITION_FEATURE_STATE_SQL),
                    {
                        "feature_id": feature_id,
                        "lifecycle_state": "retired",
                        "publication_state": "suppressed",
                        "quality_state": "valid",
                        "expected_row_revision": revision_before_retire,
                        "state_context": provider_context,
                    },
                )
            ).mappings().one()
            reactivated_context = json.loads(provider_context)
            reactivated_context["reason_code"] = "runtime_provider_reingest"
            reactivated = (
                await runtime_session.execute(
                    text(feature_repo._TRANSITION_FEATURE_STATE_SQL),
                    {
                        "feature_id": feature_id,
                        "lifecycle_state": "active",
                        "publication_state": "suppressed",
                        "quality_state": "valid",
                        "expected_row_revision": int(retired["o_row_revision"]),
                        "state_context": json.dumps(
                            reactivated_context, ensure_ascii=False
                        ),
                    },
                )
            ).mappings().one()
            assert int(reactivated["o_row_revision"]) > int(
                retired["o_row_revision"]
            )

            delete_revision = await get_feature_row_revision(runtime_session, feature_id)
            assert delete_revision is not None
            delete_request = await submit_feature_change_request(
                runtime_session,
                action="delete",
                feature_id=feature_id,
                payload={},
                review_mode="immediate",
                reason="runtime delete provenance receipt",
                requested_by="runtime-admin",
                expected_row_revision=delete_revision,
            )
            assert delete_request.state == "applied"
            deleted = (
                await runtime_session.execute(
                    text(
                        """
                        SELECT lifecycle_state, publication_state, data_origin, data_version
                        FROM feature.features
                        WHERE feature_id = :feature_id
                        """
                    ),
                    {"feature_id": feature_id},
                )
            ).mappings().one()
            assert dict(deleted) == {
                "lifecycle_state": "retired",
                "publication_state": "suppressed",
                "data_origin": "user_request",
                "data_version": 2,
            }

            added_feature_id = f"feature-admin-runtime-add-{uuid4().hex}"
            add_request = await submit_feature_change_request(
                runtime_session,
                action="add",
                feature_id=added_feature_id,
                payload={
                    "kind": "place",
                    "name": "runtime user add",
                    "category": "01070300",
                    "coord": {"lon": 126.9769, "lat": 37.5759},
                    "marker_icon": "marker",
                    "marker_color": "P-01",
                },
                review_mode="immediate",
                reason="runtime add provenance receipt",
                requested_by="runtime-admin",
            )
            assert add_request.state == "applied"
            added = (
                await runtime_session.execute(
                    text(
                        """
                        SELECT data_origin, data_version
                        FROM feature.features
                        WHERE feature_id = :feature_id
                        """
                    ),
                    {"feature_id": added_feature_id},
                )
            ).mappings().one()
            assert dict(added) == {
                "data_origin": "user_request",
                "data_version": 1,
            }
            # 0095는 runtime에서 feature_versions를 통째로 REVOKE했지만, 0097이
            # features_detailed를 DROP하면서 admin detail 화면이 version receipt를
            # 직접 읽게 됐다(`_ADMIN_FEATURE_VERSIONS_SQL`). 그래서 0097은 runtime에
            # SELECT만 되돌려준다 — INV-34C-08이 정본이고, 읽기는 immutable trigger
            # 뒤에 있으므로 provenance 무결성과 무관하다.
            # 이 테스트가 지키려는 의미는 "runtime이 provenance를 직접 쓰지 못하고
            # typed writer(procedure)만 거친다"이다. 그 의미는 읽기 권한의 부재가
            # 아니라 쓰기 권한의 부재로 표현된다. has_table_privilege는 나열한 권한
            # 중 하나라도 있으면 true이므로, 아래 한 번의 단언이 INSERT/UPDATE/DELETE
            # 셋 모두의 부재를 뜻한다.
            privileges = (
                await runtime_session.execute(
                    text(
                        "SELECT has_table_privilege("
                        "session_user, 'feature.feature_versions', 'SELECT') AS can_read, "
                        "has_table_privilege("
                        "session_user, 'feature.feature_versions', "
                        "'INSERT, UPDATE, DELETE') AS can_write"
                    )
                )
            ).mappings().one()
            assert privileges["can_read"] is True
            assert privileges["can_write"] is False
    finally:
        await runtime_engine.dispose()


async def test_user_delete_retirement_prevents_provider_resurrection(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-delete"
    await _seed_feature(migrated_session, feature_id)

    request = await submit_feature_change_request(
        migrated_session,
        action="delete",
        feature_id=feature_id,
        payload={},
        review_mode="immediate",
        reason="사용자 삭제 요청",
        requested_by="admin",
        expected_row_revision=await get_feature_row_revision(
            migrated_session, feature_id
        ),
    )
    assert request.state == "applied"

    await upsert_feature(
        migrated_session,
        _dto(feature_id),
        provider_dataset_id=await _provider_dataset_id(migrated_session),
        source_membership=_provider_source_membership(feature_id),
    )

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT lifecycle_state, publication_state, data_origin, data_version
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["lifecycle_state"] == "retired"
    assert row["publication_state"] == "suppressed"
    assert row["data_origin"] == "user_request"
    assert row["data_version"] == 1


async def test_review_required_add_applies_only_after_admin_approval(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "feature-admin-user-add"
    payload = {
        "kind": "place",
        "name": "사용자 추가 장소",
        "category": "01070300",
        "coord": {"lon": 126.9769, "lat": 37.5759},
        "marker_icon": "marker",
        "marker_color": "P-01",
        "detail": {"place_kind": "attraction"},
    }

    request = await submit_feature_change_request(
        migrated_session,
        action="add",
        feature_id=feature_id,
        payload=payload,
        review_mode="require_review",
        reason="사용자 추가 요청",
        requested_by="external-app",
    )
    assert request.state == "pending"
    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).scalar_one() == 0

    applied = await apply_feature_change_request(
        migrated_session,
        request.request_id,
        operator="admin",
    )
    assert applied is not None
    assert applied.state == "applied"

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT name, data_origin, data_version
                FROM feature.features
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert row["name"] == "사용자 추가 장소"
    assert row["data_origin"] == "user_request"
    assert row["data_version"] == 1
    versions = (
        await migrated_session.execute(
            text(
                """
                SELECT version, origin, change_kind, payload
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    assert [
        (version["version"], version["origin"], version["change_kind"])
        for version in versions
    ] == [(1, "user_request", "add")]
    assert versions[0]["payload"]["detail"]["place_kind"] == "attraction"


async def test_list_admin_features_filters_issue_and_primary_source(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature(migrated_session, "feature-admin-list")
    provider_dataset_id = await _provider_dataset_id(migrated_session)
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.data_integrity_violations (
                feature_id, provider_dataset_id,
                violation_type, severity, message
            ) VALUES (
                :feature_id, :provider_dataset_id,
                'missing_address', 'warning', '주소 검토 필요'
            )
            """
        ),
        {
            "feature_id": "feature-admin-list",
            "provider_dataset_id": provider_dataset_id,
        },
    )

    page = await list_admin_features(
        migrated_session,
        q="광화문",
        provider_dataset_id=provider_dataset_id,
        has_issue=True,
        page_size=10,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.feature_id == "feature-admin-list"
    assert item.primary_provider == _PROVIDER
    assert item.primary_dataset_key == _DATASET_KEY
    assert item.issue_count == 1
    assert item.issues[0]["violation_type"] == "missing_address"


async def test_dedup_review_decision_updates_pending_only(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    session.add(_feature_row("feature-admin-dedup-a", name="중복 A"))
    session.add(_feature_row("feature-admin-dedup-b", name="중복 B"))
    await session.flush()
    review = DedupReviewQueueRow(
        feature_id_a="feature-admin-dedup-a",
        feature_id_b="feature-admin-dedup-b",
        total_score=90,
        name_score=95,
        spatial_score=80,
        category_score=100,
    )
    session.add(review)
    await session.flush()

    changed = await set_dedup_review_decision(
        session,
        str(review.review_id),
        decision="rejected",
        reviewed_by="local-admin",
        decision_reason="서로 다른 장소",
    )
    assert changed is True

    unchanged = await set_dedup_review_decision(
        session,
        str(review.review_id),
        decision="ignored",
    )
    assert unchanged is False


async def test_merge_dedup_review_explicit_master_locks_review_row(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        session.add(_feature_row("feature-admin-lock-a", name="잠금 A"))
        session.add(_feature_row("feature-admin-lock-b", name="잠금 B"))
        await session.flush()
        # 이 블록은 rollback이 아니라 **커밋**된다(세션 공유 DB). subtype 없는
        # core 행을 남기면 뒤따르는 테스트의 consistency 게이트(F2 — subtype 결측)가
        # 막힌다. 프로덕션 writer는 두 쓰기를 한 트랜잭션에서 하므로, 시드도 그렇게 한다.
        for locked_id in ("feature-admin-lock-a", "feature-admin-lock-b"):
            await seed_feature_subtype(session, feature_id=locked_id, kind="place")
        review = DedupReviewQueueRow(
            feature_id_a="feature-admin-lock-a",
            feature_id_b="feature-admin-lock-b",
            total_score=90,
            name_score=95,
            spatial_score=80,
            category_score=100,
            status="rejected",
        )
        session.add(review)
        await session.flush()
        review_id = str(review.review_id)

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT review_id FROM ops.dedup_review_queue "
                "WHERE review_id = :review_id FOR UPDATE"
            ),
            {"review_id": review_id},
        )

        async with AsyncSession(migrated_engine) as contender:
            with pytest.raises(DBAPIError):
                await _merge_dedup_review_with_short_lock_timeout(
                    contender, review_id
                )


async def test_list_dedup_reviews_keyset_walk_stable_under_mutation(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    for feature_id in (
        "feature-admin-page-a",
        "feature-admin-page-b",
        "feature-admin-page-c",
        "feature-admin-page-d",
        "feature-admin-page-e",
    ):
        session.add(_feature_row(feature_id, name=feature_id))
    await session.flush()
    reviews = [
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000003",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-b",
            total_score=Decimal("90.01"),
            name_score=95,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000002",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-c",
            total_score=Decimal("90.01"),
            name_score=94,
            spatial_score=80,
            category_score=100,
        ),
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000001",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-d",
            total_score=Decimal("90.01"),
            name_score=93,
            spatial_score=80,
            category_score=100,
        ),
    ]
    session.add_all(reviews)
    await session.flush()

    # 동일 total_score에서 (total_score DESC, review_id DESC) total order를 keyset이
    # page_size=1로 정확히 walk한다.
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        page = await list_dedup_reviews(session, page_size=1, cursor=cursor)
        assert len(page.items) == 1
        assert page.total_count == 3
        seen.append(page.items[0].review_id)
        cursor = page.next_cursor
    assert seen == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert cursor is None  # 마지막 페이지 뒤 next_cursor는 None

    # 페이지 경계 mutation 회귀: page1 뒤 커서보다 앞(더 높은 점수) 행을 삽입해도 keyset은
    # 남은 행만 중복·누락 없이 이어간다. OFFSET이라면 삽입이 뒤 페이지를 한 칸 밀어 앞
    # 페이지 행을 재노출한다.
    page1 = await list_dedup_reviews(session, page_size=1, cursor=None)
    assert [item.review_id for item in page1.items] == [
        "00000000-0000-0000-0000-000000000003"
    ]
    session.add(
        DedupReviewQueueRow(
            review_id="00000000-0000-0000-0000-000000000009",
            feature_id_a="feature-admin-page-a",
            feature_id_b="feature-admin-page-e",
            total_score=Decimal("99.99"),  # page1 커서보다 상위 순위
            name_score=99,
            spatial_score=80,
            category_score=100,
        )
    )
    await session.flush()

    walked: list[str] = [page1.items[0].review_id]
    cursor = page1.next_cursor
    while cursor is not None:
        page = await list_dedup_reviews(session, page_size=1, cursor=cursor)
        assert len(page.items) <= 1
        walked.extend(item.review_id for item in page.items)
        cursor = page.next_cursor

    # 삽입한 상위 점수 009는 커서 앞이라 이 walk에 나타나지 않고, 003 재노출 없이 002·001을
    # 각각 정확히 한 번 본다(중복·누락 0).
    assert walked == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert len(walked) == len(set(walked))


async def test_list_dedup_reviews_cursor_rejects_filter_change(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    for feature_id in ("feature-fp-a", "feature-fp-b", "feature-fp-c"):
        session.add(_feature_row(feature_id, name=feature_id))
    await session.flush()
    session.add_all(
        [
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a2",
                feature_id_a="feature-fp-a",
                feature_id_b="feature-fp-b",
                total_score=Decimal("60.00"),
                name_score=60,
                spatial_score=60,
                category_score=60,
            ),
            DedupReviewQueueRow(
                review_id="00000000-0000-0000-0000-0000000000a1",
                feature_id_a="feature-fp-a",
                feature_id_b="feature-fp-c",
                total_score=Decimal("55.00"),
                name_score=55,
                spatial_score=55,
                category_score=55,
            ),
        ]
    )
    await session.flush()

    page = await list_dedup_reviews(session, page_size=1, min_score=10)
    assert page.next_cursor is not None

    # 같은 커서를 다른 필터(min_score 변경)로 재사용하면 fingerprint 불일치로 거부한다.
    with pytest.raises(ValueError, match="invalid dedup_review cursor"):
        await list_dedup_reviews(
            session, page_size=1, min_score=20, cursor=page.next_cursor
        )
    # 같은 필터면 keyset을 정상적으로 이어간다.
    page2 = await list_dedup_reviews(
        session, page_size=1, min_score=10, cursor=page.next_cursor
    )
    assert [item.review_id for item in page2.items] == [
        "00000000-0000-0000-0000-0000000000a1"
    ]


async def test_retired_feature_publication_patch_is_a_conflict_not_a_500(
    migrated_session: AsyncSession,
) -> None:
    """``ck_features_state_tuple`` 위반이 도메인 오류로 보존되는지 **실 DB로** 본다.

    이 축이 없으면 매핑은 조용히 죽는다. 실제로 그랬다 — constraint 이름을
    ``error.orig``에서만 찾았는데 asyncpg는 그것을 ``error.orig.__cause__``에 둔다.
    그래서 두 집합의 이름 8개가 **하나도** 매칭되지 않았고 모든 23514가 라우터의
    except 사슬을 통과해 catch-all 500이 됐다. 이름을 집합에서 빼도 게이트가 전부
    green이었으므로 매핑에는 부하가 전혀 없었다.

    단언 대상을 상태코드가 아니라 **도메인 예외 타입**으로 두는 이유는, 라우터가
    그 타입으로 409를 만들기 때문이다(타입이 맞으면 상태코드는 라우터 테스트가 고정한다).
    """

    feature_id = "feature-retired-publication-patch"
    await _seed_feature(migrated_session, feature_id)
    revision = await get_feature_row_revision(migrated_session, feature_id)
    assert revision is not None

    retired = await transition_admin_feature_state(
        migrated_session,
        feature_id,
        expected_row_revision=revision,
        reason_code="admin_retire",
        operator="local-admin",
        action="retire",
    )
    assert retired.lifecycle_state == "retired"

    with pytest.raises(AdminFeatureStateConflict):
        await transition_admin_feature_state(
            migrated_session,
            feature_id,
            expected_row_revision=retired.row_revision,
            reason_code="admin_publish_retired",
            operator="local-admin",
            action="patch",
            publication_state="published",
        )
