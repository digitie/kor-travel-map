"""Feature의 다중 current observation과 payload cursor history 통합 검증.

T-VN-39 재키(alembic 309) + ADR-098 뒤 "한 Feature에 current observation이 여럿"이
성립하는 축이 바뀌었다. provider 적재의 identity claim은
``(provider_dataset_id, feature_kind, natural_key)``이므로 **다른 provider dataset의
적재는 정의상 다른 Feature를 주조한다** — 종전 fixture처럼 두 provider가 같은 legacy
``f_*``를 들고 오면 두 번째 적재는 ``ck_provider_feature_alias_bound_elsewhere``
(23505)로 선다. 그 상태는 이제 loader가 만들 수 없다.

만들 수 있는 — 그리고 이 파일이 재는 — 축은 **entity**다. 한 dataset 안에서
source entity의 grain과 자연키의 grain이 다를 수 있고(``Feature.provider_natural_key``
docstring이 그 예를 든다: opinet의 entity id는 제품별 ``uni_id:prodcd``, 자연키는
주유소별 ``uni_id``라 여러 제품 관측이 같은 Feature에 쌓인다), 그때 한 Feature에
primary source link가 entity 수만큼 달린다. 그래서 이 fixture는 같은 dataset·같은
자연키에 entity 둘을 매단다 — 지키려던 성질(다중 current observation + entity별
payload 이력)은 그대로고, 그것을 만드는 방법만 재키 뒤의 진짜 경로로 옮겼다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra.feature_repo import _make_source_entity_key, load_bundle
from kortravelmap.infra.observation_repo import (
    get_current_observations,
    get_current_observations_by_feature_ids,
    get_observation_history,
)
from tests.integration._feature_ids import feature_uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_PROVIDER = "python-mcst-api"
_DATASET = "observation-test"

#: DTO가 드는 **legacy 축** 값. provider 적재 경로의 입력이므로 ``f_*``가 맞고
#: (ADR-098), 309의 ``ck_feature_aliases_legacy_alias_shape``가 그 형태를
#: ``^f_.+_[a-z]_[0-9a-f]{16}$``로 못박으므로 마지막 마디는 정확히 16자 hex다 —
#: 읽기 좋은 이름을 digest 자리에 넣은 값은 운영에서 생길 수 없고 23514로 거부된다.
_LEGACY_FEATURE_ID = "f_global_p_0b5e000000000001"

#: identity claim 축의 세 번째 성분. 두 entity가 이 값을 공유하므로 두 적재가 같은
#: 정본 키로 수렴한다 — 그것이 "한 Feature에 관측 둘"을 만드는 유일한 loader 경로다.
_NATURAL_KEY = "multi-observation-test"

#: 어떤 Feature도 갖지 않는 정본 키. batch read가 ``CAST(:feature_ids AS uuid[])``로
#: 조회하므로 "없는 참조" probe도 라벨 문자열이 아니라 uuid여야 한다.
_ABSENT_FEATURE_ID = feature_uuid("feature:missing")


async def _seed_active_provider_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> None:
    """관측 fixture가 쓰는 동적 provider/dataset 정본을 준비한다."""
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active
            ) VALUES (
                :provider, :dataset_key, 'observation integration fixture', 'manual', true
            )
            ON CONFLICT (provider, dataset_key) DO UPDATE
            SET is_active = true
            """
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )


def _bundle(
    *,
    entity_id: str,
    edition: str,
    fetched_at: datetime,
) -> FeatureBundle:
    """한 entity의 한 판(edition) 관측 bundle.

    ``provider_natural_key``는 entity id와 **다른 grain**이다 — 그것이 이 fixture의
    요지다. 이 값이 같으므로 두 entity의 적재가 같은 claim, 즉 같은 정본 키로
    수렴하고 한 Feature에 primary link가 둘 달린다. 이 값이 비면 writer가
    ``FeatureIdentityAnchorError``로 선다(fail-close).
    """
    raw_data = {"entity_id": entity_id, "edition": edition}
    payload_hash = make_payload_hash(raw_data)
    record_key = make_source_record_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="place",
        source_entity_id=entity_id,
        raw_payload_hash=payload_hash,
    )
    feature = Feature(
        feature_id=_LEGACY_FEATURE_ID,
        provider_natural_key=_NATURAL_KEY,
        kind=FeatureKind.PLACE,
        name="다중 관측 테스트 장소",
        category="01070100",
        address=Address(),
        marker_icon="place",
        marker_color="P-01",
        # T-VN-35(ADR-086): place subtype ``place_kind``는 NOT NULL이다.
        detail=PlaceDetail(feature_id=_LEGACY_FEATURE_ID, place_kind="attraction"),
        created_at=fetched_at,
        updated_at=fetched_at,
    )
    record = SourceRecord(
        source_record_key=record_key,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="place",
        source_entity_id=entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        imported_at=fetched_at,
    )
    link = SourceLink(
        feature_id=_LEGACY_FEATURE_ID,
        source_record_key=record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        created_at=fetched_at,
    )
    return FeatureBundle(feature=feature, source_record=record, source_link=link)


async def _canonical_uuid_for_alias(
    session: AsyncSession, legacy_feature_id: str
) -> str:
    """legacy ``f_*``가 가리키는 정본 키(uuid의 text 표기).

    309가 사본 컬럼 ``features.feature_uuid``를 없앴으므로 legacy 문자열에서 정본
    키로 가는 입구는 ``feature.feature_aliases`` 하나다 — provider 경로가 적재와
    같은 transaction에서 그 주소를 남긴다(ADR-098 결정 6).
    """
    return str(
        (
            await session.execute(
                text(
                    "SELECT CAST(a.feature_id AS text) "
                    "FROM feature.feature_aliases AS a "
                    "WHERE a.alias = :alias AND a.alias_kind = 'legacy_feature_id'"
                ),
                {"alias": legacy_feature_id},
            )
        ).scalar_one()
    )


async def test_current_observations_keep_multiple_primary_entities_and_history(
    migrated_session: AsyncSession,
) -> None:
    first_at = datetime(2026, 7, 13, 1, 0, tzinfo=UTC)
    second_at = first_at + timedelta(hours=1)
    entity_a = "observation-entity-a"
    entity_b = "observation-entity-b"

    old = _bundle(entity_id=entity_a, edition="2023", fetched_at=first_at)
    current = _bundle(entity_id=entity_a, edition="2025", fetched_at=second_at)
    other = _bundle(entity_id=entity_b, edition="current", fetched_at=second_at)

    await _seed_active_provider_dataset(
        migrated_session, provider=_PROVIDER, dataset_key=_DATASET
    )
    await load_bundle(migrated_session, old)
    second_result = await load_bundle(migrated_session, current)
    await load_bundle(migrated_session, other)
    reappeared_result = await load_bundle(migrated_session, old)
    await migrated_session.flush()

    assert second_result.source_records_inserted == 1
    assert second_result.source_links_inserted == 0
    assert second_result.source_links_updated == 1
    assert reappeared_result.source_records_inserted == 0
    assert reappeared_result.features_updated == 0

    # 정본 키는 서버가 발급한다 — DTO의 legacy ``f_*``는 그 주소일 뿐이고, read 표면의
    # 조회 키는 전부 uuid다. 등록부에서 한 번 풀어 아래 조회 전부에 쓴다.
    feature_id = await _canonical_uuid_for_alias(
        migrated_session, _LEGACY_FEATURE_ID
    )

    observations = await get_current_observations(migrated_session, feature_id)
    assert len(observations) == 2
    assert all(item.source_role == SourceRole.PRIMARY for item in observations)
    # 두 관측은 provider가 아니라 **entity**로 갈린다(같은 claim, 다른 grain).
    by_entity = {item.source_entity_id: item for item in observations}
    assert by_entity[entity_a].source_record_key == current.source_record.source_record_key
    assert by_entity[entity_a].raw_data["edition"] == "2025"
    assert by_entity[entity_b].raw_data["edition"] == "current"

    batch = await get_current_observations_by_feature_ids(
        migrated_session, [feature_id, _ABSENT_FEATURE_ID]
    )
    assert len(batch[feature_id]) == 2
    assert batch[_ABSENT_FEATURE_ID] == ()

    entity_key = _make_source_entity_key(
        provider=_PROVIDER,
        dataset_key=_DATASET,
        source_entity_type="place",
        source_entity_id=entity_a,
    )
    first_page = await get_observation_history(
        migrated_session,
        feature_id=feature_id,
        source_entity_key=entity_key,
        limit=1,
    )
    assert [item.raw_data["edition"] for item in first_page.items] == ["2025"]
    assert first_page.items[0].is_current
    assert first_page.next_cursor is not None

    second_page = await get_observation_history(
        migrated_session,
        feature_id=feature_id,
        source_entity_key=entity_key,
        cursor=first_page.next_cursor,
        limit=1,
    )
    assert [item.raw_data["edition"] for item in second_page.items] == ["2023"]
    assert not second_page.items[0].is_current
    assert second_page.next_cursor is None
