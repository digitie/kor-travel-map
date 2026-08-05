"""``infra/feature_identity`` + dual read 경계 (T-VN-32B/32C, ADR-068) 통합 검증.

alembic head(0083 포함)가 적용된 실 PostGIS에서:

① 경계 alias 해석 — legacy ``f_*`` alias·canonical UUID 양쪽 참조가 같은
   정본 키 쌍으로 해석되고, 미존재는 ``None``, 형식 오류는 fail-fast.
② dual read — raw/공개 단건·bbox 목록·service batch·notice lineage read가
   ``feature_uuid``를 UUID 정본 병행(additive)으로 노출한다
   (0080이 ``public_features`` view에 컬럼을 재고정).
③ 신규 write 원자성 — provider upsert(writer 명시 생성)와 admin add SQL이
   같은 transaction에서 uuid + legacy alias를 만든다. **0083부터 신규 값은
   비파생 UUIDv7**이므로 기대값은 파생 재계산이 아니라 **저장/관측값**이고,
   writer는 ``verify_feature_uuid``로 canonical·generator 이원화를 fail-close
   한다. ``count_features_missing_identity``는 alias 결측을 관측한다.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import (
    feature_uuid_from_legacy,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import feature_identity, feature_repo
from kortravelmap.infra.admin_feature_repo import (
    _APPLY_FEATURE_ADD_SQL,
    _add_params,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 8, 4, 12, 0, tzinfo=_KST)

_PROVIDER = "python-standard-data-api"
_DATASET = "cultural_festivals"
_ENTITY_TYPE = "festival"


def _place_bundle(feature_id: str, *, name: str = "identity 검증 장소") -> FeatureBundle:
    raw_data = {"natural_key": feature_id, "name": name}
    raw_payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=feature_id,
        raw_payload_hash=raw_payload_hash,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        address=Address(),
        category="01070100",
        coord=Coordinate(lon=126.9239, lat=37.5263),
        marker_icon="star",
        marker_color="P-03",
        created_at=_FETCHED,
        updated_at=_FETCHED,
    )
    source_record = SourceRecord(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=feature_id,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_data=raw_data,
        fetched_at=_FETCHED,
        imported_at=_FETCHED,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        created_at=_FETCHED,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def _stored_feature_uuid(session: AsyncSession, feature_id: str) -> str:
    """정본(features)에 저장된 ``feature_uuid``.

    0083 이후 신규 행의 값은 비파생 v7이라 파생 재계산으로는 알 수 없다 —
    read 표면의 기대값은 전부 이 저장값이 기준이다.
    """
    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(feature_uuid AS text) FROM feature.features "
                    "WHERE feature_id = :fid"
                ),
                {"fid": feature_id},
            )
        ).scalar_one()
    )


def _sqlstate(error: BaseException) -> str | None:
    """DBAPIError에서 PostgreSQL SQLSTATE를 꺼낸다 (driver 표기 차이 흡수)."""
    for candidate in (getattr(error, "orig", None), error):
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if value:
                return str(value)
    return None


def _assert_nonderived_uuid_v7(value: str, *, feature_id: str) -> str:
    """0083 신규 행 정본 형태 — canonical UUIDv7이고 legacy 파생값이 아니다."""
    parsed = uuid_module.UUID(value)
    assert str(parsed) == value
    assert parsed.version == 7
    assert parsed.variant == uuid_module.RFC_4122
    assert value != str(feature_uuid_from_legacy(feature_id))
    return value


# ── ① 경계 alias 해석 ───────────────────────────────────────────────────────


async def test_resolve_feature_identity_accepts_legacy_and_uuid_refs(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0001"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _stored_feature_uuid(migrated_session, feature_id), feature_id=feature_id
    )

    by_legacy = await feature_identity.resolve_feature_identity(
        migrated_session, feature_id
    )
    assert by_legacy is not None
    assert by_legacy.feature_id == feature_id
    assert by_legacy.feature_uuid == expected_uuid

    # canonical UUID 참조(대문자 포함)도 같은 정본 키 쌍으로 해석된다.
    by_uuid = await feature_identity.resolve_feature_identity(
        migrated_session, expected_uuid
    )
    assert by_uuid == by_legacy
    by_uuid_upper = await feature_identity.resolve_feature_identity(
        migrated_session, expected_uuid.upper()
    )
    assert by_uuid_upper == by_legacy


async def test_resolve_feature_identity_returns_none_for_unknown_refs(
    migrated_session: AsyncSession,
) -> None:
    assert (
        await feature_identity.resolve_feature_identity(
            migrated_session, "f_global_p_nonexistent00000"
        )
        is None
    )
    assert (
        await feature_identity.resolve_feature_identity(
            migrated_session, "00000000-0000-5000-8000-00000000dead"
        )
        is None
    )


async def test_resolve_feature_identity_fail_fast_on_malformed_ref(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(feature_identity.FeatureIdentityRefError):
        await feature_identity.resolve_feature_identity(migrated_session, " f_1")


# ── ② dual read — feature_uuid 병행 노출 ────────────────────────────────────


async def test_reads_expose_feature_uuid_additively(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0002"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _stored_feature_uuid(migrated_session, feature_id), feature_id=feature_id
    )

    # 0080 — 공개 view가 feature_uuid 컬럼을 노출한다.
    view_uuid = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.public_features "
                "WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).scalar_one()
    assert view_uuid == expected_uuid

    raw_row = await feature_repo.get_feature_row(migrated_session, feature_id)
    assert raw_row is not None
    assert raw_row["feature_uuid"] == expected_uuid

    public_row = await feature_repo.get_public_feature_row(migrated_session, feature_id)
    assert public_row is not None
    assert public_row["feature_uuid"] == expected_uuid

    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=126.9,
        min_lat=37.5,
        max_lon=127.0,
        max_lat=37.6,
    )
    bbox_by_id = {row["feature_id"]: row for row in bbox_rows}
    assert bbox_by_id[feature_id]["feature_uuid"] == expected_uuid

    batch = await feature_repo.get_service_feature_batch_items(
        migrated_session,
        ((feature_id, None), ("f_global_p_missing000000000", None)),
    )
    assert batch[0].state == "found"
    assert batch[0].feature_uuid == expected_uuid
    assert batch[1].state == "missing"
    assert batch[1].feature_uuid is None

    uuid_map = await feature_identity.get_feature_uuid_map(
        migrated_session, [feature_id, "f_global_p_missing000000000"]
    )
    assert uuid_map == {feature_id: expected_uuid}


async def test_notice_lineage_read_exposes_uuid_pairs(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_global_n_idboundary00003"
    bundle = _place_bundle(feature_id, name="identity 검증 공지")
    notice_feature = bundle.feature.model_copy(
        update={
            "kind": FeatureKind.NOTICE,
            "detail": None,
            "coord": None,
            "coord_precision_digits": None,
        }
    )
    await feature_repo.load_bundle(
        migrated_session, FeatureBundle(
            feature=notice_feature,
            source_record=bundle.source_record,
            source_link=bundle.source_link,
        )
    )
    expected_uuid = _assert_nonderived_uuid_v7(
        await _stored_feature_uuid(migrated_session, feature_id), feature_id=feature_id
    )

    identities = await feature_repo.public_active_notice_feature_identities(
        migrated_session, [feature_id, "f_global_n_missing000000000"]
    )
    assert identities == {feature_id: expected_uuid}


# ── ③ 신규 write 원자성 + legacy-only 차단 ──────────────────────────────────


async def test_upsert_writes_uuid_and_alias_atomically(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0004"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    expected_uuid = _assert_nonderived_uuid_v7(
        await _stored_feature_uuid(migrated_session, feature_id), feature_id=feature_id
    )

    pair = (
        await migrated_session.execute(
            text(
                "SELECT CAST(f.feature_uuid AS text) AS feature_uuid, "
                "       a.alias, a.alias_kind "
                "FROM feature.features AS f "
                "JOIN feature.feature_aliases AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    assert pair.feature_uuid == expected_uuid
    assert pair.alias == feature_id
    assert pair.alias_kind == "legacy_feature_id"

    # 재적재(idempotent upsert)는 새 v7 후보를 바인드하지만 ON CONFLICT 경로에서
    # 버려진다 — verify_feature_uuid(inserted=False)가 기존 저장값을 정본으로
    # 받아들여야 fail-close하지 않는다(32C 값 전환의 핵심 회귀).
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    assert await _stored_feature_uuid(migrated_session, feature_id) == expected_uuid

    (
        missing_uuid,
        missing_alias,
        pair_mismatch,
        orphan_alias,
    ) = await feature_identity.count_features_missing_identity(migrated_session)
    assert (missing_uuid, missing_alias, pair_mismatch, orphan_alias) == (0, 0, 0, 0)


async def test_upsert_wires_sent_and_inserted_into_verification(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4(적대 리뷰 1) — upsert_feature가 verify에 sent/inserted를 실제로 배선한다.

    generator 이원화 차단은 verify 유닛만으로는 성립하지 않는다 — write 경로가
    kwargs를 전달하지 않으면 죽은 검사다. 배선 자체를 회귀로 고정한다.
    """
    captured: list[dict[str, object]] = []
    real_verify = feature_repo.verify_feature_uuid

    def _spy(
        feature_id: str,
        observed: object,
        *,
        sent_feature_uuid: str | None = None,
        inserted: bool | None = None,
    ) -> str:
        captured.append(
            {
                "feature_id": feature_id,
                "sent": sent_feature_uuid,
                "inserted": inserted,
            }
        )
        return real_verify(
            feature_id,
            observed,
            sent_feature_uuid=sent_feature_uuid,
            inserted=inserted,
        )

    monkeypatch.setattr(feature_repo, "verify_feature_uuid", _spy)
    feature_id = "f_global_p_wire00000000beef"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    assert captured, "upsert 경로가 verify를 호출하지 않았다"
    first = captured[0]
    assert first["inserted"] is True
    assert isinstance(first["sent"], str)
    assert len(first["sent"]) == 36
    # 같은 feature 재-upsert(conflict-update)는 inserted=False로 배선된다 —
    # 무변경 payload는 load_bundle이 short-circuit하므로 이름을 바꿔 실제
    # UPDATE 경로를 태운다.
    captured.clear()
    await feature_repo.load_bundle(
        migrated_session, _place_bundle(feature_id, name="identity 검증 장소 개정")
    )
    assert captured
    assert captured[0]["inserted"] is False


async def test_admin_add_sql_writes_uuid_and_alias(
    migrated_session: AsyncSession,
) -> None:
    feature_id = "f_1100000000_p_idboundary0005"
    # 후보는 호출마다 달라지므로 바인드한 params를 그대로 붙잡아 대조한다
    # (0083 정본 generator = candidate_feature_uuid → 비파생 v7).
    params = _add_params(
        request_id="00000000-0000-4000-8000-000000000001",
        feature_id=feature_id,
        payload={
            "kind": "place",
            "name": "admin add 장소",
            "category": "01070100",
            "marker_icon": "star",
            "marker_color": "P-03",
        },
        reason="T-VN-32C 검증",
    )
    sent = _assert_nonderived_uuid_v7(params["feature_uuid"], feature_id=feature_id)
    row = (
        await migrated_session.execute(text(_APPLY_FEATURE_ADD_SQL), params)
    ).mappings().one()
    # RETURNING 관측값 == 보낸 후보 == 저장값 (트리거가 바꿔치기하지 않는다).
    assert row["feature_uuid"] == sent
    assert await _stored_feature_uuid(migrated_session, feature_id) == sent

    alias = (
        await migrated_session.execute(
            text(
                "SELECT alias_kind, CAST(feature_uuid AS text) AS feature_uuid "
                "FROM feature.feature_aliases WHERE alias = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    assert alias.alias_kind == "legacy_feature_id"
    assert alias.feature_uuid == sent


async def test_alias_uuid_drift_is_rejected_layer_by_layer(
    migrated_session: AsyncSession,
) -> None:
    """alias uuid drift는 계층별로 거부된다 (0083 재정의).

    32B 원판은 UPDATE drift가 파생 CHECK에 걸리는 것을 관측했지만, 0082 legacy
    write fence가 alias UPDATE 자체를 전면 거부하므로(더 강한 fail-close) UPDATE
    경로는 fence가 먼저 선다. 0083이 파생 CHECK 2종을 해제한 뒤 INSERT 경로의
    축은 둘로 갈린다:

    - ``alias ≠ feature_id`` → ``ck_feature_aliases_legacy_identity`` (23514).
      파생 CHECK가 사라져 **이름이 결정적**이므로 alternation 없이 단언한다.
    - ``alias = feature_id``지만 uuid 사본 불일치 → 복합 FK
      ``fk_feature_aliases_identity_pair`` (23503) — 축별 실측은
      ``test_legacy_write_fence``/``test_feature_uuid_shadow_migration`` 소관.
    """
    from sqlalchemy.exc import DBAPIError

    feature_id = "f_1100000000_p_idboundary0007"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    # ① UPDATE drift — 0082 fence가 불변 계약으로 먼저 거부한다.
    with pytest.raises(DBAPIError) as fence_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE feature.feature_aliases "
                    "SET feature_uuid = CAST('00000000-0000-7000-8000-0000000000ff' AS uuid) "
                    "WHERE alias = :fid"
                ),
                {"fid": feature_id},
            )
    assert "legacy write fence" in str(fence_error.value)
    # ② INSERT drift — legacy identity CHECK가 저장 경계에서 단독으로 거부한다.
    with pytest.raises(DBAPIError) as check_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_aliases "
                    "(alias, feature_id, feature_uuid, alias_kind) VALUES "
                    "(:alias, :fid, "
                    "CAST('00000000-0000-7000-8000-0000000000ff' AS uuid), "
                    "'legacy_feature_id')"
                ),
                {"alias": f"{feature_id}-drift-probe", "fid": feature_id},
            )
    assert "ck_feature_aliases_legacy_identity" in str(check_error.value)
    assert _sqlstate(check_error.value) == "23514"
    # 파생 CHECK는 0083에서 해제됐다 — 이름이 다시 등장하면 회귀다.
    assert "dual_derivation" not in str(check_error.value)


async def test_missing_alias_is_observed_by_identity_invariant(
    migrated_session: AsyncSession,
) -> None:
    """alias 결측(INV-068-01 위반)은 invariant 관측 함수가 0이 아닌 값으로 보고한다.

    T-VN-32C 0081이 alias 직접 DELETE를 fence하므로(거부 자체는
    ``test_legacy_write_fence``가 고정), 결측 상태는 보장 붕괴 시뮬레이션
    (fence 트리거 일시 해제 — transaction rollback으로 원복)으로 만든다.
    """
    feature_id = "f_1100000000_p_idboundary0006"
    await feature_repo.load_bundle(migrated_session, _place_bundle(feature_id))
    await migrated_session.execute(
        text(
            "ALTER TABLE feature.feature_aliases "
            "DISABLE TRIGGER trg_feature_aliases_delete_fence"
        )
    )
    await migrated_session.execute(
        text("DELETE FROM feature.feature_aliases WHERE alias = :fid"),
        {"fid": feature_id},
    )
    await migrated_session.execute(
        text(
            "ALTER TABLE feature.feature_aliases "
            "ENABLE TRIGGER trg_feature_aliases_delete_fence"
        )
    )
    (
        missing_uuid,
        missing_alias,
        pair_mismatch,
        orphan_alias,
    ) = await feature_identity.count_features_missing_identity(migrated_session)
    assert missing_uuid == 0
    assert missing_alias >= 1
    assert pair_mismatch == 0
    assert orphan_alias == 0
