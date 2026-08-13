"""0104 최종 fence가 0101/0102 hardening을 유지하는지 DB에서 고정한다.

0104는 request-uuid 시그니처를 DROP하고 procedure를 다시 만든다. 그 입력을
0100 원문으로 두면 0101/0102가 되감겨 두 writer(provider patch는 0104가 손대지
않는다)가 서로 다른 세대가 된다. 적대 리뷰가 실 DB에서 재현한 세 가지 귀결을
여기서 고정한다 — 셋 다 배포된 procedure 본문이 아니라 **관측 가능한 동작**으로
검사하므로, 나중에 누가 어떤 경로로 procedure를 다시 만들든 red가 된다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    author_admin_feature_field_overrides,
    revoke_admin_feature_field_overrides,
)

pytestmark = pytest.mark.integration

_SOURCE_HASH = "b" * 64


async def _open_command(session: AsyncSession, *, operation: str) -> int:
    """author/revoke가 요구하는 open domain command receipt 하나."""

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                        actor, operation, idempotency_key, fingerprint_version,
                        request_fingerprint
                    ) VALUES (
                        'tester', :operation, x_extension.gen_random_uuid(), 1,
                        :fingerprint
                    )
                    RETURNING command_id
                    """
                ),
                {"operation": operation, "fingerprint": "d" * 64},
            )
        ).scalar_one()
    )


async def _seed_notice(session: AsyncSession) -> tuple[str, int]:
    """provider lineage가 붙은 notice feature 하나."""

    feature_id = "tvn36-fence-notice"
    dataset_id = int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind
                    ) VALUES ('tvn36fence', 'fence', 'T-VN-36 fence', 'manual')
                    RETURNING provider_dataset_id
                    """
                )
            )
        ).scalar_one()
    )
    for statement in (
        """
        INSERT INTO provider_sync.source_entities (
            source_entity_key, provider_dataset_id, source_entity_type,
            source_entity_id, first_seen_at, last_seen_at
        ) VALUES ('tvn36-fence-entity', :dataset_id, 'notice', 'fence', now(), now())
        """,
        """
        INSERT INTO provider_sync.source_records (
            source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
        ) VALUES ('tvn36-fence-record', 'tvn36-fence-entity',
                  '{}'::jsonb, :source_hash, now())
        """,
        """
        INSERT INTO provider_sync.source_entity_heads (
            source_entity_key, current_source_record_key, observed_at
        ) VALUES ('tvn36-fence-entity', 'tvn36-fence-record', now())
        """,
        """
        INSERT INTO feature.features (
            feature_id, feature_uuid, kind, name, category,
            lifecycle_state, publication_state, quality_state
        ) VALUES (
            :feature_id, x_extension.gen_random_uuid(), 'notice', 'fence notice',
            '01010100', 'active', 'published', 'valid'
        )
        """,
        """
        INSERT INTO feature.feature_notices (feature_id, feature_uuid, kind, notice_type)
        SELECT feature_id, feature_uuid, kind, 'closure'
        FROM feature.features
        WHERE feature_id = :feature_id
        """,
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_entity_key, source_role, match_method, confidence
        ) VALUES (
            :feature_id, 'tvn36-fence-entity', 'primary', 'fixture', 100
        )
        """,
    ):
        await session.execute(
            text(statement),
            {
                "dataset_id": dataset_id,
                "feature_id": feature_id,
                "source_hash": _SOURCE_HASH,
            },
        )
    return feature_id, dataset_id


async def _provider_patch(
    session: AsyncSession,
    feature_id: str,
    dataset_id: int,
    *,
    values: str,
    geometry_wkt: str = "{}",
) -> None:
    await session.execute(
        text(
            """
            CALL feature.apply_provider_feature_field_patch(
                CAST(:feature_id AS text), CAST(:dataset_id AS bigint),
                CAST(:entity_key AS text), CAST(:record_key AS text),
                CAST(:expected_row_revision AS bigint), CAST(:values AS jsonb),
                CAST(:geometry_wkt AS jsonb), NULL, NULL, NULL
            )
            """
        ),
        {
            "feature_id": feature_id,
            "dataset_id": dataset_id,
            "entity_key": "tvn36-fence-entity",
            "record_key": "tvn36-fence-record",
            "expected_row_revision": await _row_revision(session, feature_id),
            "values": values,
            "geometry_wkt": geometry_wkt,
        },
    )


async def _row_revision(session: AsyncSession, feature_id: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT row_revision FROM feature.features WHERE feature_id = :fid"
                ),
                {"fid": feature_id},
            )
        ).scalar_one()
    )


async def _coord_wkt(session: AsyncSession, feature_id: str) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT x_extension.st_astext(coord) FROM feature.features "
                "WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).scalar_one()


async def test_revoking_a_coord_override_restores_the_explicit_null_base(
    migrated_session: AsyncSession,
) -> None:
    """revoke는 base가 명시적 ``null``인 geometry도 effective에 되돌려야 한다.

    0102의 revoke 집계 수정은 anchor가 0100의 f-string 렌더 결과(``'{}'``)가 아니라
    소스 표기(``'{{}}'``)를 들고 있어 한 번도 적용된 적이 없었고, 0104가 다시
    0100 원문에서 procedure를 만들어 두 번째로 지워졌다. 그 결과 revoke가 200을
    돌려주고 active override가 0이 되는데도 effective ``coord``에는 운영자 값이
    그대로 남았다 — "active override가 없으면 effective == base" 불변식이 조용히
    깨진다.
    """

    feature_id, dataset_id = await _seed_notice(migrated_session)
    await _provider_patch(
        migrated_session,
        feature_id,
        dataset_id,
        values="{}",
        geometry_wkt='{"core.coord": null}',
    )
    assert await _coord_wkt(migrated_session, feature_id) is None

    author_command = await _open_command(
        migrated_session, operation="admin.feature.override.author"
    )
    await author_admin_feature_field_overrides(
        migrated_session,
        feature_id,
        expected_row_revision=await _row_revision(migrated_session, feature_id),
        command_id=author_command,
        operator="tester",
        reason_code="fence probe",
        values={},
        geometry_wkt={"core.coord": "POINT(127 37)"},
    )
    assert await _coord_wkt(migrated_session, feature_id) == "POINT(127 37)"

    revoke_command = await _open_command(
        migrated_session, operation="admin.feature.override.revoke"
    )
    await revoke_admin_feature_field_overrides(
        migrated_session,
        feature_id,
        expected_row_revision=await _row_revision(migrated_session, feature_id),
        command_id=revoke_command,
        operator="tester",
        reason_code="fence probe revoke",
        field_paths=["core.coord"],
    )

    active = int(
        (
            await migrated_session.execute(
                text(
                    "SELECT count(*) FROM ops.feature_overrides "
                    "WHERE feature_id = :fid AND status = 'active'"
                ),
                {"fid": feature_id},
            )
        ).scalar_one()
    )
    assert active == 0
    assert await _coord_wkt(migrated_session, feature_id) is None


async def test_author_accepts_an_explicit_null_geometry_override(
    migrated_session: AsyncSession,
) -> None:
    """운영자도 좌표를 명시적으로 지울 수 있어야 한다.

    0104가 0100 원문에서 author를 재생성하면 geometry 루프가 ``jsonb_each_text``로
    되돌아가 JSON ``null``이 SQL NULL이 되고, ``coalesce(btrim(...), '') = ''``가
    23514를 던진다. runtime(``admin_feature_repo``)은 ``{"coord": null}`` PATCH에서
    ``geometry_wkt["core.coord"] = None``을 그대로 보내므로 422가 된다.
    """

    feature_id, dataset_id = await _seed_notice(migrated_session)
    await _provider_patch(
        migrated_session,
        feature_id,
        dataset_id,
        values="{}",
        geometry_wkt='{"core.coord": "POINT(126 36)"}',
    )
    assert await _coord_wkt(migrated_session, feature_id) == "POINT(126 36)"

    author_command = await _open_command(
        migrated_session, operation="admin.feature.override.author"
    )
    await author_admin_feature_field_overrides(
        migrated_session,
        feature_id,
        expected_row_revision=await _row_revision(migrated_session, feature_id),
        command_id=author_command,
        operator="tester",
        reason_code="clear coord",
        values={},
        geometry_wkt={"core.coord": None},
    )
    assert await _coord_wkt(migrated_session, feature_id) is None


async def test_first_probe_preservation_reads_the_base_ledger_not_the_override(
    migrated_session: AsyncSession,
) -> None:
    """``first_probe`` 보존이 운영자 override를 provider base로 세탁하면 안 된다.

    보존 블록이 effective ``feature.feature_notices``를 읽으면, 그 값은 이미
    운영자 override에 가려져 있다(``notice.valid_start_time``은 registry에서
    operator_writable). 그것을 ``p_values``에 밀어 넣으면 현재 provider record의
    hash를 달고 base ledger에 기록된다 — provider의 실제 관측이 영구히 사라지고
    운영자 편집이 provider 진실과 구분되지 않게 된다. 0104가
    ``feature.feature_versions``를 없앤 뒤로 base ledger는 유일한 field
    provenance 기록이다.
    """

    feature_id, dataset_id = await _seed_notice(migrated_session)
    await _provider_patch(
        migrated_session,
        feature_id,
        dataset_id,
        values=(
            '{"notice.payload": {"valid_start_origin": "first_probe"}, '
            '"notice.valid_start_time": "2020-01-01T00:00:00+00:00"}'
        ),
    )

    author_command = await _open_command(
        migrated_session, operation="admin.feature.override.author"
    )
    await author_admin_feature_field_overrides(
        migrated_session,
        feature_id,
        expected_row_revision=await _row_revision(migrated_session, feature_id),
        command_id=author_command,
        operator="tester",
        reason_code="operator start time",
        values={"notice.valid_start_time": "2031-05-05T00:00:00+00:00"},
        geometry_wkt={},
    )

    await _provider_patch(
        migrated_session,
        feature_id,
        dataset_id,
        values=(
            '{"notice.payload": {"valid_start_origin": "first_probe"}, '
            '"notice.valid_start_time": "2027-02-02T00:00:00+00:00"}'
        ),
    )

    base_value = (
        await migrated_session.execute(
            text(
                "SELECT value_json #>> '{}' FROM feature.feature_base_field_values "
                "WHERE feature_id = :fid AND field_path = 'notice.valid_start_time'"
            ),
            {"fid": feature_id},
        )
    ).scalar_one()
    assert base_value is not None
    assert base_value.startswith("2020-01-01"), (
        "first_probe 보존은 base ledger의 최초 provider 관측을 유지해야 한다 — "
        f"운영자 override가 base로 새어 들어왔다: {base_value}"
    )
