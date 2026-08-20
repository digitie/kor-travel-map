"""T-VN-35 / T-VN-34C — kind별 typed subtype 최종 계약 통합 테스트.

core와 subtype의 배타 arc, writer의 subtype 정본, non-public reader의 직접 조립,
route/area geometry, 공개 projection을 DB 수준에서 고정한다. 이전 migration
왕복이나 private detail view의 호환성은 서비스 전 cutover 정책에 따라 검증 대상이
아니다. 여기서 검증하는 축은 다섯이다:

1. **배타 arc** — subtype 행이 있는 동안 core ``kind``가 못 바뀌고, 한 feature는
   최대 하나의 subtype에만 있으며, 고아 subtype과 identity 사본 불일치가
   FK로 막힌다. 코드 규율이 아니라 DB 계약이라는 것이 요점이다.
2. **upsert 왕복** — writer가 subtype에만 쓰고, non-public repository reader가
   명시 LEFT JOIN으로 조립한 ``detail``이 DTO 왕복과 동등하다.
3. **geometry 필수 kind** — geometry 없는 route/area는 write 시점에 거부되고
   core 행도 남지 않는다(``feature_routes``/``feature_areas``의 ``geom``이
   NOT NULL이므로 사후 보정이 아니라 fail-close).
4. **notice lifecycle** — supersede/purge가 typed ``timestamptz`` 컬럼을 갱신하고
   공개 read 필터가 그 typed 비교로 감산한다(``detail->>`` 문자열 파싱 소멸).
5. **merge cross-kind 거부** — kind가 subtype 소속을 결정하므로 이종 병합은
   무결성을 직접 깬다(``MergeConflictError``).

"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import feature_repo, merge_repo
from kortravelmap.infra.feature_subtype import (
    SUBTYPE_TABLES,
    subtype_params,
    subtype_upsert_sql,
)
from kortravelmap.infra.merge_repo import MergeConflictError
from tests.integration.conftest import as_api_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=_KST)

_ROUTE_WKT = "MULTILINESTRING((127.0 37.5, 127.01 37.51, 127.02 37.52))"
_AREA_WKT = (
    "MULTIPOLYGON(((127.0 37.5, 127.1 37.5, 127.1 37.6, 127.0 37.6, 127.0 37.5)))"
)


# ---------------------------------------------------------------------------
# 시드 헬퍼 — core는 raw SQL, subtype은 **프로덕션 매핑 정본**을 그대로 쓴다.
# (테스트가 매핑 규칙을 복제하면 계약이 두 벌이 된다.)
# ---------------------------------------------------------------------------


async def _insert_core(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    name: str = "타입드 서브타입 검증",
    category: str = "01070100",
    lon: float | None = 127.0,
    lat: float | None = 37.5,
    lifecycle_state: str = "active",
    publication_state: str = "published",
    quality_state: str = "valid",
) -> str:
    """core 행만 INSERT하고 저장된 ``feature_uuid``를 돌려준다."""
    stored_uuid = (
        await session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, coord,
                    lifecycle_state, publication_state, quality_state, updated_at
                )
                VALUES (
                    :feature_id, :kind, :name, :category,
                    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                         ELSE x_extension.ST_SetSRID(
                             x_extension.ST_MakePoint(
                                 CAST(:lon AS double precision),
                                 CAST(:lat AS double precision)
                             ), 4326) END,
                    :lifecycle_state, :publication_state, :quality_state,
                    CAST(:updated_at AS timestamptz)
                )
                RETURNING CAST(feature_uuid AS text)
                """
            ),
            {
                "feature_id": feature_id,
                "kind": kind,
                "name": name,
                "category": category,
                "lon": lon,
                "lat": lat,
                "lifecycle_state": lifecycle_state,
                "publication_state": publication_state,
                "quality_state": quality_state,
                "updated_at": _NOW,
            },
        )
    ).scalar_one()
    await session.flush()
    return str(stored_uuid)


async def _insert_subtype(
    session: AsyncSession,
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    detail: dict[str, Any],
    geom_wkt: str | None = None,
) -> None:
    sql = subtype_upsert_sql(kind)
    assert sql is not None, f"kind {kind!r} has no subtype table"
    params = subtype_params(
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        detail=detail,
    )
    assert params is not None
    if geom_wkt is not None:
        params["geom_wkt"] = geom_wkt
    await session.execute(text(sql), params)
    await session.flush()


async def _seed_place(
    session: AsyncSession, feature_id: str, *, place_kind: str = "cafe"
) -> str:
    feature_uuid = await _insert_core(session, feature_id=feature_id, kind="place")
    await _insert_subtype(
        session,
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind="place",
        detail={"place_kind": place_kind},
    )
    return feature_uuid


def _bundle(
    feature: Feature,
    *,
    source_entity_id: str,
    provider: str = "python-krex-api",
    dataset_key: str = "krex_traffic_notices",
    source_entity_type: str = "traffic_notice",
    raw_data: dict[str, Any] | None = None,
    fetched_at: datetime | None = None,
) -> FeatureBundle:
    """``feature_repo.load_bundle``이 받는 최소 bundle."""
    payload = raw_data if raw_data is not None else {"natural_key": source_entity_id}
    payload_hash = make_payload_hash(payload)
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    return FeatureBundle(
        feature=feature,
        source_record=SourceRecord(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
            raw_data=payload,
            fetched_at=fetched_at or _NOW,
            source_record_key=source_record_key,
        ),
        source_link=SourceLink(
            feature_id=feature.feature_id,
            source_record_key=source_record_key,
            source_role=SourceRole.PRIMARY,
            match_method="natural_key",
            confidence=100,
        ),
    )


async def _detail_from_reader(session: AsyncSession, feature_id: str) -> dict[str, Any]:
    """non-public reader의 직접 subtype 조립 결과를 반환한다."""
    row = await feature_repo.get_feature_row(session, feature_id)
    assert row is not None
    return dict(row["detail"])


async def _subtype_row(
    session: AsyncSession, table: str, feature_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(f"SELECT * FROM feature.{table} WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# ① 배타 arc — kind 불변 / 단일 subtype / 고아 금지 / identity 사본 일치
# ---------------------------------------------------------------------------


async def test_core_kind_change_is_blocked_while_subtype_row_exists(
    migrated_session: AsyncSession,
) -> None:
    """subtype 행이 있는 동안 core ``kind`` 변경이 **FK 위반**으로 막힌다.

    ADR-086 컨텍스트 1의 구멍(provider upsert의 ``kind = EXCLUDED.kind``가 kind를
    조용히 교체할 수 있던 것)을 코드 규율이 아니라 DB 계약으로 닫은 것이 이
    단언의 대상이다. 참조 대상은 0084의 ``uq_features_identity_kind``.
    """
    await _seed_place(migrated_session, "tvn35:arc:kind")

    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE feature.features SET kind = 'event' "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": "tvn35:arc:kind"},
            )
    assert "fk_feature_places_feature_kind" in str(excinfo.value)

    # subtype이 없는 kind(price)는 arc 밖이라 종전대로 자유롭다 — 배타 arc가
    # "subtype이 있는 동안"에만 kind를 묶는다는 것을 반대 방향으로 고정한다.
    await _insert_core(
        migrated_session, feature_id="tvn35:arc:price", kind="price", category="06020000"
    )
    await migrated_session.execute(
        text("UPDATE feature.features SET kind = 'weather' WHERE feature_id = :feature_id"),
        {"feature_id": "tvn35:arc:price"},
    )
    await migrated_session.flush()


async def test_second_subtype_insert_is_blocked_for_same_feature(
    migrated_session: AsyncSession,
) -> None:
    """한 feature는 최대 한 subtype에만 존재한다 — 이중 삽입은 FK 위반이다.

    core ``kind``가 단일 값이므로 다른 kind 상수를 요구하는 subtype의
    ``(feature_id, kind)`` 복합 FK가 구조적으로 실패한다.
    """
    feature_uuid = await _seed_place(migrated_session, "tvn35:arc:double")

    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:double",
                feature_uuid=feature_uuid,
                kind="event",
                detail={"event_kind": "festival"},
            )
    assert "fk_feature_events_feature_kind" in str(excinfo.value)

    # 같은 subtype 재삽입(중복 PK)도 막힌다 — upsert 경로만이 갱신 수단이다.
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_places "
                    "(feature_id, feature_uuid, kind, place_kind) "
                    "VALUES (:feature_id, CAST(:feature_uuid AS uuid), 'place', 'cafe')"
                ),
                {"feature_id": "tvn35:arc:double", "feature_uuid": feature_uuid},
            )
    assert "pk_feature_places" in str(excinfo.value)


async def test_orphan_subtype_and_identity_mismatch_are_blocked(
    migrated_session: AsyncSession,
) -> None:
    """core 행 없는 subtype과 identity 사본 불일치가 각각 FK로 막힌다."""
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:ghost",
                feature_uuid=str(uuid4()),
                kind="place",
                detail={"place_kind": "cafe"},
            )
    assert "fk_feature_places_feature_kind" in str(excinfo.value)

    # core는 있지만 feature_uuid 사본이 다르면 identity 쌍 FK가 막는다(0083 선례).
    await _insert_core(migrated_session, feature_id="tvn35:arc:identity", kind="place")
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:identity",
                feature_uuid=str(uuid4()),
                kind="place",
                detail={"place_kind": "cafe"},
            )
    assert "fk_feature_places_identity_pair" in str(excinfo.value)


async def test_core_delete_cascades_to_subtype(migrated_session: AsyncSession) -> None:
    """core 행 삭제는 subtype을 CASCADE로 데려간다(0083 ``feature_aliases`` 규약)."""
    await _seed_place(migrated_session, "tvn35:arc:cascade")
    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
        {"feature_id": "tvn35:arc:cascade"},
    )
    await migrated_session.flush()
    assert await _subtype_row(migrated_session, "feature_places", "tvn35:arc:cascade") is None


# ---------------------------------------------------------------------------
# ② upsert 왕복 — subtype이 정본, 뷰가 응답 detail을 조립
# ---------------------------------------------------------------------------


def _place_feature(feature_id: str, *, place_kind: str, phones: list[str]) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name="왕복 검증 카페",
        category="01070100",
        marker_icon="cafe",
        marker_color="P-03",
        coord=Coordinate(lon=127.0, lat=37.5),
        address=Address(),
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            phones=phones,
            biz_number="123-45-67890",
            license_date=date(2024, 3, 1),
            facility_info={"seats": 40, "wifi": None},
            payload={"origin": "tvn35"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _event_feature(feature_id: str, *, ends_on: date) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name="왕복 검증 축제",
        category="01010100",
        marker_icon="festival",
        marker_color="P-05",
        coord=Coordinate(lon=127.01, lat=37.51),
        address=Address(),
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=date(2026, 8, 1),
            ends_on=ends_on,
            venue_name="여의도공원",
            tel="02-000-0000",
            content_id="C-1",
            content_type_id="15",
            area_code="1",
            payload={"origin": "tvn35"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _notice_feature(
    feature_id: str,
    *,
    valid_end_time: datetime | None,
    valid_start_time: datetime | None = None,
) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name="왕복 검증 공지",
        category="99000000",
        marker_icon="danger",
        marker_color="P-15",
        coord=Coordinate(lon=127.02, lat=37.52),
        address=Address(),
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type="traffic",
            severity=2,
            valid_start_time=valid_start_time or _NOW - timedelta(days=1),
            valid_end_time=valid_end_time,
            source_agency="한국도로공사",
            payload={"domain": "highway"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


async def test_place_bundle_upsert_round_trips_through_subtype(
    migrated_session: AsyncSession,
) -> None:
    """place bundle 적재 → subtype 행 생성 · identity 쌍 일치 · 뷰 detail 동등."""
    feature = _place_feature(
        "tvn35:rt:place", place_kind="cafe", phones=["02-1234-5678"]
    )
    await feature_repo.load_bundle(migrated_session, _bundle(feature, source_entity_id="P-1"))
    await migrated_session.flush()

    row = await _subtype_row(migrated_session, "feature_places", "tvn35:rt:place")
    assert row is not None
    assert row["kind"] == "place"
    assert row["place_kind"] == "cafe"
    assert row["phones"] == ["02-1234-5678"]
    assert row["license_date"] == date(2024, 3, 1)
    core_uuid = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.features "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": "tvn35:rt:place"},
        )
    ).scalar_one()
    assert str(row["feature_uuid"]) == str(core_uuid)

    # 뷰가 조립한 detail이 DTO 왕복과 동등하다(응답 shape 무변경).
    assembled = await _detail_from_reader(migrated_session, "tvn35:rt:place")
    assert PlaceDetail.model_validate(assembled) == feature.detail

    # 재upsert가 subtype을 **갱신**한다(행 증식 없음).
    updated = _place_feature(
        "tvn35:rt:place", place_kind="restaurant", phones=["02-9999-0000"]
    )
    await feature_repo.load_bundle(
        migrated_session, _bundle(updated, source_entity_id="P-1", raw_data={"v": 2})
    )
    await migrated_session.flush()
    reread = await _subtype_row(migrated_session, "feature_places", "tvn35:rt:place")
    assert reread is not None
    assert reread["place_kind"] == "restaurant"
    assert reread["phones"] == ["02-9999-0000"]
    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.feature_places WHERE feature_id = :fid"),
            {"fid": "tvn35:rt:place"},
        )
    ).scalar_one() == 1


async def test_event_and_notice_bundles_round_trip_through_subtype(
    migrated_session: AsyncSession,
) -> None:
    """event/notice도 같은 계약 — typed date/timestamptz가 DTO 왕복과 동등하다."""
    event = _event_feature("tvn35:rt:event", ends_on=date(2026, 8, 10))
    notice = _notice_feature(
        "tvn35:rt:notice", valid_end_time=_NOW + timedelta(days=3)
    )
    await feature_repo.load_bundle(migrated_session, _bundle(event, source_entity_id="E-1"))
    await feature_repo.load_bundle(migrated_session, _bundle(notice, source_entity_id="N-1"))
    await migrated_session.flush()

    event_row = await _subtype_row(migrated_session, "feature_events", "tvn35:rt:event")
    assert event_row is not None
    assert event_row["starts_on"] == date(2026, 8, 1)
    assert event_row["ends_on"] == date(2026, 8, 10)
    assert event_row["timezone"] == "Asia/Seoul"

    notice_row = await _subtype_row(migrated_session, "feature_notices", "tvn35:rt:notice")
    assert notice_row is not None
    # 종전 ``detail->>`` 문자열이 아니라 typed timestamptz다.
    assert isinstance(notice_row["valid_end_time"], datetime)
    assert notice_row["valid_end_time"] == notice.detail.valid_end_time  # type: ignore[union-attr]
    assert notice_row["severity"] == 2

    assembled_event = await _detail_from_reader(migrated_session, "tvn35:rt:event")
    assert EventDetail.model_validate(assembled_event) == event.detail
    assembled_notice = await _detail_from_reader(migrated_session, "tvn35:rt:notice")
    assert NoticeDetail.model_validate(assembled_notice) == notice.detail

    # 재upsert로 종료 시각이 typed 컬럼에서 갱신된다.
    reopened = _notice_feature("tvn35:rt:notice", valid_end_time=None)
    await feature_repo.load_bundle(
        migrated_session, _bundle(reopened, source_entity_id="N-1", raw_data={"v": 2})
    )
    await migrated_session.flush()
    reread = await _subtype_row(migrated_session, "feature_notices", "tvn35:rt:notice")
    assert reread is not None
    assert reread["valid_end_time"] is None


async def test_notice_valid_during_preserves_empty_range_without_changing_read_contract(
    migrated_session: AsyncSession,
) -> None:
    """T-VN-37D의 파생 range가 empty를 보존하되 미래 공지는 계속 노출한다."""
    withdrawn_id = "tvn37d:empty:notice"
    future_id = "tvn37d:future:notice"
    reference_now = datetime.now(_KST)
    withdrawn_start = reference_now + timedelta(days=30)
    withdrawn_end = reference_now - timedelta(days=1)
    future_start = reference_now + timedelta(days=3)
    future_end = reference_now + timedelta(days=10)

    withdrawn = _notice_feature(
        withdrawn_id,
        valid_start_time=withdrawn_start,
        valid_end_time=withdrawn_end,
    )
    future = _notice_feature(
        future_id,
        valid_start_time=future_start,
        valid_end_time=future_end,
    )
    await feature_repo.load_bundle(
        migrated_session,
        _bundle(withdrawn, source_entity_id="T-VN-37D-empty"),
    )
    await feature_repo.load_bundle(
        migrated_session,
        _bundle(future, source_entity_id="T-VN-37D-future"),
    )
    await migrated_session.flush()

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT feature_id,
                       valid_during IS NULL AS is_null,
                       isempty(valid_during) AS is_empty,
                       lower(valid_during) AS lower_bound,
                       upper(valid_during) AS upper_bound
                FROM feature.feature_notices
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY feature_id
                """
            ),
            {"feature_ids": [withdrawn_id, future_id]},
        )
    ).mappings().all()
    by_id = {str(row["feature_id"]): row for row in rows}

    empty = by_id[withdrawn_id]
    assert empty["is_null"] is False
    assert empty["is_empty"] is True
    assert empty["lower_bound"] is None
    assert empty["upper_bound"] is None

    bounded = by_id[future_id]
    assert bounded["is_null"] is False
    assert bounded["is_empty"] is False
    assert bounded["lower_bound"] == future_start
    assert bounded["upper_bound"] == future_end

    # T-VN-37D는 `@> now()`로 바꾸지 않는다. 미래 발효 공지는 기존처럼 보이고,
    # 이미 끝난 empty 공지는 기존 valid_end_time 감산으로 숨겨진다.
    visible = await feature_repo.public_active_notice_feature_identities(
        migrated_session, [withdrawn_id, future_id]
    )
    assert set(visible) == {future_id}

    # 저장 range는 내부 표현이고 공개 detail 계약은 두 typed timestamp를 유지한다.
    assembled = await _detail_from_reader(migrated_session, withdrawn_id)
    assert NoticeDetail.model_validate(assembled).valid_start_time == withdrawn_start
    assert NoticeDetail.model_validate(assembled).valid_end_time == withdrawn_end


async def test_assembled_notice_times_do_not_depend_on_session_timezone(
    migrated_session: AsyncSession,
) -> None:
    """조립된 시각 문자열이 세션 ``TimeZone`` GUC에 의존하면 안 된다.

    ``to_jsonb(timestamptz)``는 세션 TimeZone으로 렌더한다 — 그대로 두면 서버
    설정이 다른 인스턴스가 **같은 공지에 다른 문자열**을 돌려준다(실측: 같은
    행이 Asia/Seoul에서 ``+09:00``, UTC에서 ``+00:00``, America/New_York에서
    ``-04:00``). 뷰가 KST 고정 렌더를 쓰므로 세 세션에서 모두 같아야 한다.

    덧붙여 마이크로초가 0이면 생략해 Python ``datetime.isoformat()``과 표기가
    같다 — 기존 prod ``valid_start_time`` 145행이 그대로 유지되는 근거다.
    """
    feature_id = "tvn35:tz:notice"
    # 마이크로초 0(생략 분기)과 non-zero(``.US`` 분기)를 함께 태운다.
    start = datetime(2026, 8, 5, 17, 35, 24, tzinfo=_KST)
    end = datetime(2026, 8, 6, 1, 2, 3, 823154, tzinfo=_KST)
    notice = _notice_feature(feature_id, valid_start_time=start, valid_end_time=end)
    await feature_repo.load_bundle(
        migrated_session, _bundle(notice, source_entity_id="N-TZ")
    )
    await migrated_session.flush()

    rendered: list[tuple[str, str]] = []
    observed_zones: list[str] = []
    for zone in ("Asia/Seoul", "UTC", "America/New_York"):
        await migrated_session.execute(text(f"SET LOCAL TIME ZONE '{zone}'"))
        observed_zones.append(
            str(
                (
                    await migrated_session.execute(text("SELECT current_setting('TimeZone')"))
                ).scalar_one()
            )
        )
        assembled = await _detail_from_reader(migrated_session, feature_id)
        rendered.append(
            (assembled["valid_start_time"], assembled["valid_end_time"])
        )
    await migrated_session.execute(text("SET LOCAL TIME ZONE 'UTC'"))

    # GUC가 실제로 바뀌었는지 먼저 고정한다 — 안 바뀌었다면 위 비교는 공허하다
    # (``SET LOCAL``은 트랜잭션 밖에서 무시된다).
    assert observed_zones == ["Asia/Seoul", "UTC", "America/New_York"], observed_zones
    assert len(set(rendered)) == 1, f"세션 TimeZone에 따라 달라졌다: {rendered}"
    assert rendered[0] == (
        "2026-08-05T17:35:24+09:00",
        "2026-08-06T01:02:03.823154+09:00",
    )
    # 같은 순간을 가리키는지도 확인한다(표기만 고정한 것이지 값이 아니다).
    assembled = await _detail_from_reader(migrated_session, feature_id)
    assert NoticeDetail.model_validate(assembled).valid_start_time == start
    assert NoticeDetail.model_validate(assembled).valid_end_time == end


async def test_event_sigungu_code_survives_subtype_round_trip(
    migrated_session: AsyncSession,
) -> None:
    """``EventDetail.sigungu_code``도 다른 필드와 같이 왕복해야 한다."""
    feature_id = "tvn35:rt:event-sigungu"
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name="시군구 코드 축제",
        category="01010100",
        marker_icon="festival",
        marker_color="P-05",
        coord=Coordinate(lon=127.03, lat=37.53),
        address=Address(),
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 8, 3),
            area_code="1",
            sigungu_code="11140",
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await feature_repo.load_bundle(
        migrated_session, _bundle(feature, source_entity_id="E-SIGUNGU")
    )
    await migrated_session.flush()

    assembled = await _detail_from_reader(migrated_session, feature_id)
    assert EventDetail.model_validate(assembled) == feature.detail


async def test_public_projection_requires_the_final_visible_state_tuple(
    migrated_session: AsyncSession,
) -> None:
    """공개 reader는 active/published/valid 조합만 반환한다.

    비공개 reader는 동일 행을 직접 subtype 조립으로 계속 읽는다. 이 경계가
    lifecycle, publication, quality의 어느 한 축에도 묻힌 legacy 상태값을 두지
    않도록 고정한다.
    """
    feature_id = "tvn35:public:axes"
    feature = _place_feature(feature_id, place_kind="cafe", phones=[])
    await feature_repo.load_bundle(
        migrated_session, _bundle(feature, source_entity_id="PUBLIC-AXES")
    )
    await migrated_session.flush()

    assert await feature_repo.get_public_feature_row(migrated_session, feature_id)
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET publication_state = 'suppressed' "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": feature_id},
    )
    assert await feature_repo.get_public_feature_row(migrated_session, feature_id) is None
    internal = await feature_repo.get_feature_row(migrated_session, feature_id)
    assert internal is not None
    assert internal["detail"]["place_kind"] == "cafe"


async def test_core_has_no_derived_detail_or_geometry_and_no_private_detail_view(
    migrated_session: AsyncSession,
) -> None:
    """detail/geometry는 subtype과 reader 조립에만 존재한다."""
    columns = set(
        (
            await migrated_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'feature' AND table_name = 'features'"
                )
            )
        ).scalars()
    )
    assert {"detail", "geom"}.isdisjoint(columns)
    assert (
        await migrated_session.execute(
            text("SELECT to_regclass('feature.features_detailed')")
        )
    ).scalar_one() is None


# ---------------------------------------------------------------------------
# ③ geometry 필수 kind — write 시점 fail-close
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "detail_factory"),
    [
        (FeatureKind.ROUTE, lambda fid: RouteDetail(feature_id=fid, route_type="trail")),
        (FeatureKind.AREA, lambda fid: AreaDetail(feature_id=fid, area_kind="area")),
    ],
)
async def test_geometryless_route_and_area_are_rejected_at_construction(
    migrated_session: AsyncSession,
    kind: FeatureKind,
    detail_factory: Any,
) -> None:
    """geometry 없는 route/area는 ``Feature`` 구성 시점에 거부된다.

    종전에는 적재 후 geometry 결측 Feature를 retirement 처리하던
    상태다. subtype ``geom``이 NOT NULL이 되면서 그 보정이 DTO 계약으로 앞당겨졌다
    (ADR-086 결정 5) — write까지 갈 것도 없다. 반대 방향(route/area가 아닌 kind의
    geometry)도 같은 validator가 막는다: 담을 곳이 없으므로 조용히 버려지느니
    거부한다.
    """
    feature_id = f"tvn35:geom:{kind.value}"
    with pytest.raises(ValueError, match="geom이 필수"):
        Feature(
            feature_id=feature_id,
            kind=kind,
            name="지오메트리 없는 경로/구역",
            category="03000000",
            marker_icon="park",
            marker_color="P-06",
            coord=Coordinate(lon=127.0, lat=37.5),
            address=Address(),
            geom=None,
            detail=detail_factory(feature_id),
            created_at=_NOW,
            updated_at=_NOW,
        )

    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).scalar_one() == 0


async def test_geometry_on_non_route_area_kind_is_rejected() -> None:
    """place/event에 geometry를 실으면 담을 곳이 없다 — 구성 시점에 거부한다."""
    with pytest.raises(ValueError, match="geom을 가질 수 없다"):
        Feature(
            feature_id="tvn35:geom:place",
            kind=FeatureKind.PLACE,
            name="선을 가진 장소",
            category="01070100",
            marker_icon="place",
            marker_color="P-01",
            coord=Coordinate(lon=127.0, lat=37.5),
            address=Address(),
            geom=_ROUTE_WKT,
            detail=PlaceDetail(feature_id="tvn35:geom:place", place_kind="cafe"),
            created_at=_NOW,
            updated_at=_NOW,
        )


@pytest.mark.parametrize(
    ("kind", "wkt", "table", "detail_factory"),
    [
        (
            FeatureKind.ROUTE,
            _ROUTE_WKT,
            "feature_routes",
            lambda fid: RouteDetail(
                feature_id=fid, route_type="trail", geometry_source="knps"
            ),
        ),
        (
            FeatureKind.AREA,
            _AREA_WKT,
            "feature_areas",
            lambda fid: AreaDetail(
                feature_id=fid, area_kind="protected_area", boundary_source="gis_spca"
            ),
        ),
    ],
)
async def test_route_and_area_with_geometry_land_in_subtype(
    migrated_session: AsyncSession,
    kind: FeatureKind,
    wkt: str,
    table: str,
    detail_factory: Any,
) -> None:
    """geometry가 있으면 subtype에 Multi* 타입으로 승격 저장되고 뷰가 되돌려준다."""
    feature_id = f"tvn35:geom-ok:{kind.value}"
    feature = Feature(
        feature_id=feature_id,
        kind=kind,
        name="지오메트리 있는 경로/구역",
        category="03000000",
        marker_icon="park",
        marker_color="P-06",
        address=Address(),
        geom=wkt,
        detail=detail_factory(feature_id),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await feature_repo.load_bundle(
        migrated_session,
        _bundle(feature, source_entity_id=f"GEOM-{kind.value}"),
    )
    await migrated_session.flush()

    geometry_type = (
        await migrated_session.execute(
            text(
                f"SELECT x_extension.ST_GeometryType(geom) FROM feature.{table} "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    assert geometry_type == (
        "ST_MultiLineString" if kind is FeatureKind.ROUTE else "ST_MultiPolygon"
    )

    assembled = await _detail_from_reader(migrated_session, feature_id)
    model = RouteDetail if kind is FeatureKind.ROUTE else AreaDetail
    assert model.model_validate(assembled) == feature.detail

    # core에는 geometry가 없다 — 직접 조립 reader가 subtype geometry를 제공한다.
    assembled_row = await feature_repo.get_feature_row(migrated_session, feature_id)
    assert assembled_row is not None
    direct_geom = (
        await migrated_session.execute(
            text(
                "SELECT x_extension.ST_GeometryType(COALESCE(r.geom, a.geom)) "
                "FROM feature.features AS f "
                "LEFT JOIN feature.feature_routes AS r ON r.feature_id = f.feature_id "
                "LEFT JOIN feature.feature_areas AS a ON a.feature_id = f.feature_id "
                "WHERE f.feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    assert direct_geom == geometry_type


# ---------------------------------------------------------------------------
# ④ notice lifecycle — typed 컬럼 갱신 + typed 비교 read 필터
# ---------------------------------------------------------------------------


async def test_supersede_writes_typed_valid_end_time_and_read_filter_hides_it(
    migrated_session: AsyncSession,
) -> None:
    """feed 소멸 supersede가 typed ``valid_end_time``을 쓰고 공개 read가 감산한다."""
    feature = _notice_feature("tvn35:lifecycle:notice", valid_end_time=None)
    await feature_repo.load_bundle(
        migrated_session,
        _bundle(
            feature,
            source_entity_id="LC-1",
            raw_data={
                "occurred_date": "2026.08.06",
                "occurred_time": "07:25:43",
                "route_no": "0550",
                "direction": "부산방향",
                "point_name": "남제천(272.5k)",
                "incident_type_code": "03",
            },
        ),
    )
    await migrated_session.flush()

    visible = await feature_repo.public_active_notice_feature_identities(
        migrated_session, ["tvn35:lifecycle:notice"]
    )
    assert set(visible) == {"tvn35:lifecycle:notice"}

    # supersede 판정은 DB ``now()``와 비교되므로 실시계 기준 과거 시각을 쓴다.
    closed_at = datetime.now(_KST) - timedelta(hours=1)
    await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        active_lineage_keys=[],
        closed_at=closed_at,
    )
    await migrated_session.flush()

    row = await _subtype_row(
        migrated_session, "feature_notices", "tvn35:lifecycle:notice"
    )
    assert row is not None
    assert row["valid_end_time"] == closed_at

    # 조립 뷰의 detail도 같은 값을 돌려준다(조립 규칙이 한 곳이라 갈라지지 않는다).
    assembled = await _detail_from_reader(migrated_session, "tvn35:lifecycle:notice")
    assert NoticeDetail.model_validate(assembled).valid_end_time == closed_at

    # typed 비교 read 필터가 종료된 notice를 감산한다.
    assert (
        await feature_repo.public_active_notice_feature_identities(
            migrated_session, ["tvn35:lifecycle:notice"]
        )
        == {}
    )


async def test_purge_expired_notices_reads_typed_columns(
    migrated_session: AsyncSession,
) -> None:
    """purge가 typed ``valid_end_time``/``valid_start_time``으로 보존 기간을 판정한다."""
    expired_id = "tvn35:purge:expired"
    fresh_id = "tvn35:purge:fresh"
    start_only_id = "tvn35:purge:start-only"

    for feature_id, end_time, start_time in (
        (expired_id, _NOW - timedelta(days=800), _NOW - timedelta(days=810)),
        (fresh_id, _NOW - timedelta(days=1), _NOW - timedelta(days=2)),
        (start_only_id, None, _NOW - timedelta(days=800)),
    ):
        await feature_repo.load_bundle(
            migrated_session,
            _bundle(
                _notice_feature(
                    feature_id,
                    valid_start_time=start_time,
                    valid_end_time=end_time,
                ),
                source_entity_id=feature_id,
            ),
        )

    purged = await feature_repo.purge_expired_notices(migrated_session)
    await migrated_session.flush()
    assert purged == 2

    lifecycles = dict(
        (
            await migrated_session.execute(
                text(
                    "SELECT feature_id, lifecycle_state FROM feature.features "
                    "WHERE feature_id = ANY(CAST(:ids AS text[]))"
                ),
                {"ids": [expired_id, fresh_id, start_only_id]},
            )
        ).all()
    )
    assert lifecycles[expired_id] == "retired"
    assert lifecycles[start_only_id] == "retired"
    assert lifecycles[fresh_id] == "active"


# ---------------------------------------------------------------------------
# ⑤ merge — cross-kind 거부 / same-kind 정상
# ---------------------------------------------------------------------------


async def test_cross_kind_merge_is_rejected(migrated_session: AsyncSession) -> None:
    """kind가 다른 두 feature 병합은 ``MergeConflictError``로 fail-close한다.

    kind가 어느 subtype에 값이 사는지를 결정하므로 이종 병합은 "provider 정체성만
    옮기고 typed 값은 남기는" 상태가 되어 무결성을 직접 깬다(ADR-086 결과절).
    """
    await _seed_place(migrated_session, "tvn35:merge:place")
    event_uuid = await _insert_core(
        migrated_session, feature_id="tvn35:merge:event", kind="event", category="01010100"
    )
    await _insert_subtype(
        migrated_session,
        feature_id="tvn35:merge:event",
        feature_uuid=event_uuid,
        kind="event",
        detail={"event_kind": "festival"},
    )

    with pytest.raises(MergeConflictError, match="kind가 다른"):
        async with migrated_session.begin_nested(), as_api_runtime(migrated_session):
            await merge_repo.apply_feature_merge(
                migrated_session,
                master_id="tvn35:merge:place",
                loser_id="tvn35:merge:event",
                merged_by="tvn35-test",
            )


async def test_same_kind_merge_keeps_master_subtype_and_preserves_loser(
    migrated_session: AsyncSession,
) -> None:
    """같은 kind 병합은 정상 동작하고, loser subtype은 ADR-017대로 남는다."""
    await _seed_place(migrated_session, "tvn35:merge:master", place_kind="cafe")
    await _seed_place(migrated_session, "tvn35:merge:loser", place_kind="restaurant")

    # merge는 실제 API runtime role로 — 0222 executor 게이트가 superuser를 거부하고, superuser는
    # ACL을 안 봐 회귀도 못 잡는다. savepoint 안이라 뒤따르는 superuser 검증 SQL은 그대로다.
    async with migrated_session.begin_nested(), as_api_runtime(migrated_session):
        await merge_repo.apply_feature_merge(
            migrated_session,
            master_id="tvn35:merge:master",
            loser_id="tvn35:merge:loser",
            merged_by="tvn35-test",
        )
    await migrated_session.flush()

    loser_lifecycle = (
        await migrated_session.execute(
            text(
                "SELECT lifecycle_state FROM feature.features "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": "tvn35:merge:loser"},
        )
    ).scalar_one()
    assert loser_lifecycle == "retired"
    # retirement은 core-only라 CASCADE가 발동하지 않는다 — typed 값이 보존된다.
    assert (
        await _subtype_row(migrated_session, "feature_places", "tvn35:merge:loser")
    ) is not None
    master_row = await _subtype_row(
        migrated_session, "feature_places", "tvn35:merge:master"
    )
    assert master_row is not None
    assert master_row["place_kind"] == "cafe"


def test_subtype_table_map_covers_every_geometry_and_detail_kind() -> None:
    """subtype 대상 kind 집합은 5종 고정 — price/weather는 값 정본이 따로 있다."""
    assert set(SUBTYPE_TABLES) == {"place", "event", "notice", "route", "area"}
    assert subtype_upsert_sql("price") is None
    assert subtype_upsert_sql("weather") is None
