"""``infra.dedup_refresh_repo`` DB 기준 dedup refresh 입력 조회 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import md5
from typing import TYPE_CHECKING

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from kortravelmap.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_PROVIDER = "python-dedup-refresh-api"
_DATASET = "dedup_refresh_features"
_CAT = "01070100"
_T1 = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 5, 10, 0, tzinfo=UTC)

#: 세 seed의 정본 키. T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``는
#: uuid이고, 이 모듈이 재는 것은 keyset 페이지네이션이다 —
#: ``ORDER BY updated_at DESC, feature_id DESC``에서 ``_T2`` 동률 두 건의 순서를
#: 가르는 것이 곧 ``feature_id``다. 그래서 라벨에서 유도한 uuid
#: (``tests.integration._feature_ids.feature_uuid``)를 쓰지 않는다: 유도값의 순서는
#: 라벨의 사전순과 무관해 기대 순서가 값에 따라 뒤집힌다. 순서를 눈으로 확인할 수
#: 있는 리터럴을 이 파일이 직접 든다 — 종전 ``'dedup-refresh-a' < ... < '-c'``와 같은
#: 순서이고, uuid 비교는 canonical 표기의 사전식과 같다.
_F_A = "00000000-0000-7000-8000-0000000da001"
_F_B = "00000000-0000-7000-8000-0000000da002"
_F_C = "00000000-0000-7000-8000-0000000da003"


async def test_list_dedup_refresh_features_exposes_master_signals_and_keyset(
    migrated_session: AsyncSession,
) -> None:
    await _seed_feature(
        migrated_session,
        feature_id=_F_A,
        label="dedup-refresh-a",
        updated_at=_T1,
        coord_precision_digits=5,
    )
    await _seed_feature(
        migrated_session,
        feature_id=_F_B,
        label="dedup-refresh-b",
        updated_at=_T2,
        coord_precision_digits=7,
    )
    await _seed_feature(
        migrated_session,
        feature_id=_F_C,
        label="dedup-refresh-c",
        updated_at=_T2,
        coord_precision_digits=6,
    )

    first_page = await list_dedup_refresh_features(
        migrated_session,
        DedupRefreshScope(provider=_PROVIDER, dataset_key=_DATASET, limit=2),
    )

    assert [item.feature_id for item in first_page] == [_F_C, _F_B]
    assert [item.coord_precision_digits for item in first_page] == [6, 7]
    assert first_page[0].updated_at == _T2
    assert first_page[0].as_master_candidate().feature_id == _F_C
    assert first_page[0].as_master_candidate().has_coord is True

    last = first_page[-1]
    second_page = await list_dedup_refresh_features(
        migrated_session,
        DedupRefreshScope(
            provider=_PROVIDER,
            dataset_key=_DATASET,
            limit=2,
            cursor_updated_at=last.updated_at,
            cursor_feature_id=last.feature_id,
        ),
    )

    assert [item.feature_id for item in second_page] == [_F_A]
    assert second_page[0].coord_precision_digits == 5


async def test_list_dedup_refresh_features_rejects_partial_cursor(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="cursor_updated_at"):
        await list_dedup_refresh_features(
            migrated_session,
            DedupRefreshScope(
                provider=_PROVIDER,
                dataset_key=_DATASET,
                limit=10,
                cursor_updated_at=_T1,
            ),
        )


async def _dataset_id(session: AsyncSession) -> int:
    """fixture 전용 catalog 행을 만들고 canonical id를 돌려준다 (T-VN-33).

    dedup refresh scope는 여전히 provider/dataset_key 표시 자연키를 받지만,
    source entity의 identity는 ``provider_dataset_id`` 하나다.
    """

    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": _PROVIDER, "dataset_key": _DATASET},
            )
        ).scalar_one()
    )


async def _seed_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    label: str,
    updated_at: datetime,
    coord_precision_digits: int,
) -> None:
    """정본 키(uuid)로 core 행을, 라벨로 lineage 자연키를 심는다.

    두 축이 갈린 것이 T-VN-39의 요지다 — ``feature_id``는 uuid이고, source
    entity/record의 키와 사람이 읽을 이름은 여전히 text 라벨이다.
    """
    dataset_id = await _dataset_id(session)
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name=f"중복 후보 {label}",
            category=_CAT,
            coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
            coord_precision_digits=coord_precision_digits,
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
            created_at=_T1,
            updated_at=updated_at,
        )
    )
    session.add(
        SourceEntityRow(
            source_entity_key=f"se-{label}",
            provider_dataset_id=dataset_id,
            source_entity_type="place",
            source_entity_id=label,
            first_seen_at=updated_at,
            last_seen_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=f"sr-{label}",
            source_entity_key=f"se-{label}",
            # ck_source_records_payload_hash_canonical = ^[0-9a-f]{1,64}$
            raw_payload_hash=md5(label.encode()).hexdigest(),
            raw_data={"feature_id": feature_id},
            fetched_at=updated_at,
            imported_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=f"se-{label}",
            current_source_record_key=f"sr-{label}",
            observed_at=updated_at,
        )
    )
    await session.flush()
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=f"se-{label}",
            source_role="primary",
            match_method="natural_key",
            confidence=100,
            created_at=updated_at,
        )
    )
    await session.flush()
